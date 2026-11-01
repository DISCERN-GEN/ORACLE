from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from .domain import OrderBook, Side
from .quantitative import _price, _probability

D = Decimal


@dataclass(frozen=True, slots=True)
class DepthFill:
    price: Decimal
    quantity: Decimal


@dataclass(frozen=True, slots=True)
class DirectionalEvaluation:
    market_id: str
    token_id: str
    side: Side
    outcome_probability: Decimal
    requested_quantity: Decimal
    filled_quantity: Decimal
    average_price: Decimal | None
    notional: Decimal
    fee_total: Decimal
    gross_edge_per_share: Decimal | None
    net_edge_per_share: Decimal | None
    net_expected_value: Decimal | None
    roi: Decimal | None
    executable: bool
    reason: str
    fills: tuple[DepthFill, ...] = ()


@dataclass(frozen=True, slots=True)
class OutcomeLeg:
    outcome: str
    book: OrderBook
    fee_rate: Decimal


@dataclass(frozen=True, slots=True)
class CompleteSetEvaluation:
    market_id: str
    outcomes: tuple[str, ...]
    quantity: Decimal
    total_cost: Decimal
    total_fees: Decimal
    guaranteed_payout: Decimal
    net_profit: Decimal
    roi: Decimal
    executable: bool
    classification: str
    reason: str
    legs: tuple[DirectionalEvaluation, ...]


def evaluate_directional(
    *,
    outcome_probability: Decimal,
    book: OrderBook,
    side: Side,
    quantity: Decimal,
    fee_rate: Decimal,
    limit_price: Decimal,
    max_book_age_seconds: int = 30,
    now: datetime | None = None,
) -> DirectionalEvaluation:
    """Evaluate one outcome against executable book depth, not the midpoint.

    The probability is the probability of the selected token outcome. BUY consumes asks;
    SELL consumes bids. The result is only a candidate calculation, not a risk approval.
    """
    _probability(outcome_probability)
    _price(limit_price)
    if limit_price <= 0 or limit_price > 1:
        raise ValueError("limit_price must be greater than 0 and at most 1")
    if quantity <= 0 or fee_rate < 0:
        raise ValueError("quantity must be positive and fee_rate non-negative")
    if max_book_age_seconds < 0:
        raise ValueError("max_book_age_seconds cannot be negative")
    now = now or datetime.now(UTC)
    if book.age_seconds(now) > max_book_age_seconds:
        return _empty_directional(book, side, outcome_probability, quantity, "STALE_ORDER_BOOK")
    if book.best_bid is None or book.best_ask is None:
        return _empty_directional(book, side, outcome_probability, quantity, "INCOMPLETE_ORDER_BOOK")
    if quantity < book.min_order_size:
        return _empty_directional(book, side, outcome_probability, quantity, "BELOW_MINIMUM_ORDER_SIZE")
    if book.tick_size > 0 and limit_price % book.tick_size != 0:
        return _empty_directional(book, side, outcome_probability, quantity, "INVALID_TICK_SIZE")

    levels = book.asks if side == Side.BUY else book.bids
    levels = tuple(sorted(levels, key=lambda x: x.price, reverse=side == Side.SELL))
    fills: list[DepthFill] = []
    remaining = quantity
    for level in levels:
        crosses = level.price <= limit_price if side == Side.BUY else level.price >= limit_price
        if not crosses:
            continue
        take = min(level.size, remaining)
        if take > 0:
            fills.append(DepthFill(level.price, take))
            remaining -= take
        if remaining <= 0:
            break
    filled = quantity - remaining
    notional = sum((x.price * x.quantity for x in fills), D("0"))
    fees = notional * fee_rate
    if filled == 0:
        return _empty_directional(book, side, outcome_probability, quantity, "NO_CROSSING_DEPTH")
    vwap = notional / filled
    if remaining > 0:
        return DirectionalEvaluation(
            book.market_id, book.token_id, side, outcome_probability, quantity, filled, vwap,
            notional, fees, None, None, None, None, False, "INSUFFICIENT_FULL_DEPTH", tuple(fills),
        )
    fee_per_share = fees / filled
    gross_edge = (outcome_probability - vwap) if side == Side.BUY else (vwap - outcome_probability)
    net_edge = gross_edge - fee_per_share
    net_value = net_edge * filled
    total_cost = notional + fees if side == Side.BUY else notional
    roi = net_value / total_cost if total_cost > 0 else D("0")
    return DirectionalEvaluation(
        book.market_id, book.token_id, side, outcome_probability, quantity, filled, vwap,
        notional, fees, gross_edge, net_edge, net_value, roi, net_edge > 0,
        "POSITIVE_NET_EDGE" if net_edge > 0 else "NO_POSITIVE_NET_EDGE", tuple(fills),
    )


def evaluate_complete_set(
    *,
    market_id: str,
    expected_outcomes: Iterable[str],
    legs: Iterable[OutcomeLeg],
    quantity: Decimal,
    outcomes_verified_exhaustive: bool,
    settlement_rules_verified: bool,
    max_book_age_seconds: int = 30,
    now: datetime | None = None,
) -> CompleteSetEvaluation:
    """Check a complete-set buy across mutually-exclusive, exhaustive outcomes.

    This function will not label a related-market price discrepancy as arbitrage. The caller
    must explicitly attest that the exact outcome set is exhaustive and settlement-equivalent.
    It computes a full set at a common quantity using asks and visible depth for every leg.
    """
    outcomes = tuple(expected_outcomes)
    leg_list = tuple(legs)
    if len(outcomes) < 2 or len(set(outcomes)) != len(outcomes):
        raise ValueError("expected_outcomes must contain at least two unique outcomes")
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    supplied = {x.outcome for x in leg_list}
    token_ids = {x.book.token_id for x in leg_list}
    if supplied != set(outcomes) or len(leg_list) != len(outcomes) or len(token_ids) != len(leg_list):
        return _empty_complete_set(market_id, outcomes, quantity, "OUTCOME_COVERAGE_MISMATCH")
    if not outcomes_verified_exhaustive:
        return _empty_complete_set(market_id, outcomes, quantity, "OUTCOMES_NOT_VERIFIED_EXHAUSTIVE")
    if not settlement_rules_verified:
        return _empty_complete_set(market_id, outcomes, quantity, "SETTLEMENT_RULES_NOT_VERIFIED")
    now = now or datetime.now(UTC)
    evaluations: list[DirectionalEvaluation] = []
    for leg in leg_list:
        if leg.book.market_id != market_id:
            return _empty_complete_set(market_id, outcomes, quantity, "MARKET_ID_MISMATCH")
        best_ask = leg.book.best_ask
        if best_ask is None:
            return _empty_complete_set(market_id, outcomes, quantity, "MISSING_ASK")
        evaluation = evaluate_directional(
            outcome_probability=D("1"), book=leg.book, side=Side.BUY, quantity=quantity,
            fee_rate=leg.fee_rate, limit_price=D("1"), max_book_age_seconds=max_book_age_seconds,
            now=now,
        )
        if not evaluation.executable:
            return _empty_complete_set(market_id, outcomes, quantity,
                                       f"LEG_NOT_EXECUTABLE:{leg.outcome}:{evaluation.reason}")
        evaluations.append(evaluation)
    total_cost = sum((x.notional for x in evaluations), D("0"))
    total_fees = sum((x.fee_total for x in evaluations), D("0"))
    payout = quantity
    net_profit = payout - total_cost - total_fees
    roi = net_profit / (total_cost + total_fees) if total_cost + total_fees > 0 else D("0")
    executable = net_profit > 0
    return CompleteSetEvaluation(
        market_id, outcomes, quantity, total_cost, total_fees, payout, net_profit, roi,
        executable,
        "COMPLETE_SET_ARBITRAGE_CANDIDATE" if executable else "NO_POSITIVE_COMPLETE_SET_EDGE",
        "All listed outcomes covered with executable book depth and caller-verified settlement semantics.",
        tuple(evaluations),
    )


def _empty_directional(book: OrderBook, side: Side, probability: Decimal,
                        quantity: Decimal, reason: str) -> DirectionalEvaluation:
    return DirectionalEvaluation(
        book.market_id, book.token_id, side, probability, quantity, D("0"), None, D("0"),
        D("0"), None, None, None, None, False, reason,
    )


def _empty_complete_set(market_id: str, outcomes: tuple[str, ...], quantity: Decimal,
                         reason: str) -> CompleteSetEvaluation:
    return CompleteSetEvaluation(
        market_id, outcomes, quantity, D("0"), D("0"), quantity, D("0"), D("0"),
        False, "REJECTED", reason, (),
    )
