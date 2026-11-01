from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .domain import OrderBook, OrderIntent, PaperAccount, Side


@dataclass(frozen=True, slots=True)
class PaperFill:
    price: Decimal
    quantity: Decimal
    fee: Decimal


@dataclass(frozen=True, slots=True)
class PaperExecution:
    status: str
    fills: tuple[PaperFill, ...]
    filled_quantity: Decimal
    remaining_quantity: Decimal
    average_price: Decimal | None
    fee_total: Decimal
    reason: str = ""


class PaperBroker:
    """Conservative taker simulation using only displayed opposing-side depth."""

    def execute(
        self,
        intent: OrderIntent,
        book: OrderBook,
        account: PaperAccount,
        fee_rate: Decimal,
        fee_schedule_attested: bool,
    ) -> PaperExecution:
        if not fee_schedule_attested:
            return self._empty(intent, "FEE_SCHEDULE_UNVERIFIED")
        if fee_rate < 0:
            return self._empty(intent, "INVALID_FEE_RATE")
        if book.token_id != intent.token_id:
            return self._empty(intent, "BOOK_TOKEN_MISMATCH")
        if intent.quantity <= 0 or intent.limit_price <= 0 or intent.limit_price >= 1:
            return self._empty(intent, "INVALID_ORDER")
        if intent.quantity < book.min_order_size:
            return self._empty(intent, "BELOW_VENUE_MINIMUM_SIZE")
        if book.tick_size > 0 and intent.limit_price % book.tick_size != 0:
            return self._empty(intent, "INVALID_TICK_SIZE")

        levels = sorted(book.asks if intent.side == Side.BUY else book.bids,
                        key=lambda x: x.price, reverse=intent.side == Side.SELL)
        remaining = intent.quantity
        fills: list[PaperFill] = []

        for level in levels:
            crosses = level.price <= intent.limit_price if intent.side == Side.BUY else level.price >= intent.limit_price
            if not crosses or remaining <= 0:
                continue
            available = min(level.size, remaining)
            notional = available * level.price
            fee = notional * fee_rate
            fills.append(PaperFill(price=level.price, quantity=available, fee=fee))
            remaining -= available

        filled = intent.quantity - remaining
        fee_total = sum((f.fee for f in fills), Decimal("0"))
        if filled == 0:
            return PaperExecution("UNFILLED", (), Decimal("0"), intent.quantity, None, Decimal("0"), "NO_CROSSING_DEPTH")

        gross = sum((f.price * f.quantity for f in fills), Decimal("0"))
        average = gross / filled
        if intent.side == Side.BUY:
            total_cost = gross + fee_total
            if account.cash < total_cost:
                return self._empty(intent, "INSUFFICIENT_PAPER_CASH")
            account.cash -= total_cost
            old_qty = account.positions.get(intent.token_id, Decimal("0"))
            old_cost = account.average_cost.get(intent.token_id, Decimal("0"))
            account.average_cost[intent.token_id] = ((old_cost * old_qty + gross + fee_total) / (old_qty + filled))
            account.positions[intent.token_id] = old_qty + filled
            account.market_exposure[intent.market_id] = account.market_exposure.get(intent.market_id, Decimal("0")) + total_cost
        else:
            held = account.positions.get(intent.token_id, Decimal("0"))
            if held < filled:
                return self._empty(intent, "INSUFFICIENT_PAPER_INVENTORY")
            proceeds = gross - fee_total
            average_cost = account.average_cost.get(intent.token_id, Decimal("0"))
            realised = sum(((f.price - average_cost) * f.quantity for f in fills), Decimal("0")) - fee_total
            account.realised_pnl += realised
            account.daily_realised_pnl += realised
            account.daily_loss = max(Decimal("0"), -account.daily_realised_pnl)
            account.cash += proceeds
            account.positions[intent.token_id] = held - filled
            cost_released = average_cost * filled
            if held == filled:
                account.average_cost.pop(intent.token_id, None)
            account.market_exposure[intent.market_id] = max(
                Decimal("0"), account.market_exposure.get(intent.market_id, Decimal("0")) - cost_released
            )
        account.fees_paid += fee_total
        account.order_count += 1
        status = "FILLED" if remaining == 0 else "PARTIALLY_FILLED"
        return PaperExecution(status, tuple(fills), filled, remaining, average, fee_total,
                              "Simulated against visible public order-book depth; no venue order was sent.")

    @staticmethod
    def _empty(intent: OrderIntent, reason: str) -> PaperExecution:
        return PaperExecution("REJECTED", (), Decimal("0"), intent.quantity, None, Decimal("0"), reason)
