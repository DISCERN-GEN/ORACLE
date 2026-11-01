from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .domain import Side

D = Decimal


@dataclass(frozen=True, slots=True)
class WalletTrade:
    trade_id: str
    wallet_address: str
    market_id: str
    token_id: str
    side: Side
    price: Decimal
    quantity: Decimal
    fee: Decimal
    executed_at: datetime
    fee_known: bool = True

    def __post_init__(self) -> None:
        if not self.trade_id or not self.wallet_address or not self.market_id or not self.token_id:
            raise ValueError("Trade identity fields are required")
        if not D("0") <= self.price <= D("1"):
            raise ValueError("Binary token price must be between 0 and 1 inclusive")
        if self.quantity <= 0 or self.fee < 0:
            raise ValueError("Quantity must be positive and fee cannot be negative")


@dataclass(slots=True)
class _Position:
    market_id: str
    quantity: Decimal = D("0")
    cost_basis: Decimal = D("0")

    @property
    def average_cost(self) -> Decimal:
        return self.cost_basis / self.quantity if self.quantity else D("0")


@dataclass(frozen=True, slots=True)
class RealisedTrade:
    trade_id: str
    quantity: Decimal
    realised_pnl: Decimal


@dataclass(frozen=True, slots=True)
class WalletReconstruction:
    wallet_address: str
    trade_count: int
    duplicate_trade_count: int
    buy_count: int
    sell_count: int
    fees_paid: Decimal | None
    gross_buy_notional: Decimal
    gross_sell_notional: Decimal
    realised_pnl: Decimal | None
    unrealised_pnl: Decimal | None
    total_pnl: Decimal | None
    open_positions: dict[str, dict[str, Decimal | str]]
    win_rate_on_matched_sells: Decimal | None
    profit_factor: Decimal | None
    capital_turnover: Decimal
    unmatched_sell_count: int
    unmatched_sell_quantity: Decimal
    history_complete: bool
    initial_balances_known: bool
    fees_complete: bool
    completeness_notes: tuple[str, ...]


def reconstruct_wallet(
    trades: Iterable[WalletTrade],
    current_marks: dict[str, Decimal] | None = None,
    *,
    history_complete: bool = False,
    initial_balances_known: bool = False,
) -> WalletReconstruction:
    """Reconstruct trade-window inventory and P&L using average cost.

    This is intentionally not presented as complete account P&L unless the caller can
    establish complete history and known starting inventory. Transfers, redemptions,
    rewards, funding and unobserved opening positions must be supplied/verified upstream.
    """
    rows = sorted(trades, key=lambda x: (x.executed_at, x.trade_id))
    wallet = rows[0].wallet_address if rows else ""
    if any(row.wallet_address != wallet for row in rows):
        raise ValueError("All trades in a reconstruction must belong to one wallet")
    unique: list[WalletTrade] = []
    seen: set[str] = set()
    duplicate_count = 0
    for row in rows:
        if row.trade_id in seen:
            duplicate_count += 1
            continue
        seen.add(row.trade_id)
        unique.append(row)

    positions: dict[str, _Position] = {}
    realised: list[RealisedTrade] = []
    fees = D("0")
    buy_notional = D("0")
    sell_notional = D("0")
    buy_count = sell_count = unmatched_count = 0
    unmatched_quantity = D("0")
    notes: list[str] = []

    fees_complete = all(trade.fee_known for trade in unique)
    for trade in unique:
        fees += trade.fee
        pos = positions.setdefault(trade.token_id, _Position(trade.market_id))
        if pos.market_id != trade.market_id:
            raise ValueError("Token was associated with multiple markets in the supplied trade data")
        notional = trade.price * trade.quantity
        if trade.side == Side.BUY:
            buy_count += 1
            buy_notional += notional
            pos.cost_basis += notional + trade.fee
            pos.quantity += trade.quantity
        else:
            sell_count += 1
            sell_notional += notional
            if pos.quantity < trade.quantity:
                unmatched_count += 1
                unmatched_quantity += trade.quantity - pos.quantity
                notes.append(f"Unmatched sell quantity on trade {trade.trade_id}; starting inventory/history is incomplete.")
                continue
            average_cost = pos.average_cost
            realised_value = (trade.price - average_cost) * trade.quantity - trade.fee
            realised.append(RealisedTrade(trade.trade_id, trade.quantity, realised_value))
            pos.quantity -= trade.quantity
            pos.cost_basis -= average_cost * trade.quantity
            if pos.quantity == 0:
                pos.cost_basis = D("0")

    if duplicate_count:
        notes.append(f"Ignored {duplicate_count} duplicate trade IDs.")
    if not history_complete:
        notes.append("Historical trade coverage has not been independently established as complete.")
    if not fees_complete:
        notes.append("One or more trade fees are unavailable; net P&L and fee-adjusted metrics are withheld.")
    if not initial_balances_known:
        notes.append("Opening inventory and non-trade balance adjustments are unknown.")
    if unmatched_count:
        notes.append("At least one sell exceeded reconstructed inventory; affected P&L is incomplete.")

    gross_realised_pnl = sum((x.realised_pnl for x in realised), D("0"))
    realised_pnl = gross_realised_pnl if fees_complete else None
    marks = current_marks or {}
    unrealised = D("0")
    all_open_positions_marked = True
    open_positions: dict[str, dict[str, Decimal | str]] = {}
    for token_id, pos in positions.items():
        if pos.quantity <= 0:
            continue
        mark = marks.get(token_id)
        if mark is None:
            all_open_positions_marked = False
            open_positions[token_id] = {
                "market_id": pos.market_id, "quantity": pos.quantity,
                "cost_basis": pos.cost_basis, "average_cost": pos.average_cost,
                "mark": "unavailable", "unrealised_pnl": "unavailable",
            }
            notes.append(f"No current mark supplied for open token {token_id}.")
            continue
        if not D("0") <= mark <= D("1"):
            raise ValueError(f"Current mark for token {token_id} must be between 0 and 1")
        token_unrealised = mark * pos.quantity - pos.cost_basis
        unrealised += token_unrealised
        open_positions[token_id] = {
            "market_id": pos.market_id, "quantity": pos.quantity,
            "cost_basis": pos.cost_basis, "average_cost": pos.average_cost,
            "mark": mark, "unrealised_pnl": token_unrealised,
        }
    unrealised_pnl = unrealised if all_open_positions_marked and fees_complete else None
    total_pnl = realised_pnl + unrealised_pnl if realised_pnl is not None and unrealised_pnl is not None else None
    wins = sum(1 for x in realised if x.realised_pnl > 0)
    win_rate = D(wins) / D(len(realised)) if realised and fees_complete else None
    gross_wins = sum((x.realised_pnl for x in realised if x.realised_pnl > 0), D("0"))
    gross_losses = -sum((x.realised_pnl for x in realised if x.realised_pnl < 0), D("0"))
    profit_factor = gross_wins / gross_losses if gross_losses > 0 and fees_complete else None
    turnover = (buy_notional + sell_notional) / buy_notional if buy_notional > 0 else D("0")
    return WalletReconstruction(
        wallet, len(unique), duplicate_count, buy_count, sell_count, fees if fees_complete else None, buy_notional,
        sell_notional, realised_pnl, unrealised_pnl, total_pnl, open_positions, win_rate,
        profit_factor, turnover, unmatched_count, unmatched_quantity,
        history_complete and initial_balances_known and fees_complete and unmatched_count == 0,
        initial_balances_known, fees_complete, tuple(dict.fromkeys(notes)),
    )
