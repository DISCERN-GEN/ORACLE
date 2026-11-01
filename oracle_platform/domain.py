from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class Decision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    DEFER = "defer"


@dataclass(frozen=True, slots=True)
class BookLevel:
    price: Decimal
    size: Decimal


@dataclass(frozen=True, slots=True)
class OrderBook:
    market_id: str
    token_id: str
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]
    captured_at: datetime
    tick_size: Decimal = Decimal("0.01")
    min_order_size: Decimal = Decimal("1")

    @property
    def best_bid(self) -> Decimal | None:
        return max((x.price for x in self.bids), default=None)

    @property
    def best_ask(self) -> Decimal | None:
        return min((x.price for x in self.asks), default=None)

    @property
    def midpoint(self) -> Decimal | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / Decimal("2")

    def age_seconds(self, now: datetime | None = None) -> Decimal:
        now = now or datetime.now(timezone.utc)
        return Decimal(str(max(0.0, (now - self.captured_at).total_seconds())))


@dataclass(frozen=True, slots=True)
class Forecast:
    market_id: str
    outcome: str
    probability: Decimal
    lower_bound: Decimal
    upper_bound: Decimal
    confidence: Decimal
    model_id: str
    model_version: str
    validated: bool = False
    evidence_references: tuple[str, ...] = ()
    invalidation_conditions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("probability", "lower_bound", "upper_bound", "confidence"):
            value = getattr(self, name)
            if value < 0 or value > 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.lower_bound > self.probability or self.probability > self.upper_bound:
            raise ValueError("Forecast bounds must contain the forecast probability")


@dataclass(frozen=True, slots=True)
class OrderIntent:
    market_id: str
    token_id: str
    side: Side
    limit_price: Decimal
    quantity: Decimal
    idempotency_key: str
    forecast_id: str | None = None
    opportunity_id: str | None = None
    model_id: str | None = None

    @property
    def notional(self) -> Decimal:
        return self.limit_price * self.quantity


@dataclass(frozen=True, slots=True)
class RiskDecision:
    decision: Decision
    max_notional: Decimal
    checks_passed: tuple[str, ...] = ()
    checks_failed: tuple[str, ...] = ()
    rationale: str = ""
    decided_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class PaperAccount:
    initial_cash: Decimal
    cash: Decimal
    positions: dict[str, Decimal] = field(default_factory=dict)
    market_exposure: dict[str, Decimal] = field(default_factory=dict)
    average_cost: dict[str, Decimal] = field(default_factory=dict)
    realised_pnl: Decimal = Decimal("0")
    daily_realised_pnl: Decimal = Decimal("0")
    fees_paid: Decimal = Decimal("0")
    order_count: int = 0
    daily_loss: Decimal = Decimal("0")

    @classmethod
    def create(cls, bankroll: Decimal) -> "PaperAccount":
        if bankroll <= 0:
            raise ValueError("Paper bankroll must be positive")
        return cls(initial_cash=bankroll, cash=bankroll)

    def snapshot(self) -> dict[str, Any]:
        return {
            "initial_cash": str(self.initial_cash),
            "cash": str(self.cash),
            "positions": {k: str(v) for k, v in self.positions.items()},
            "market_exposure": {k: str(v) for k, v in self.market_exposure.items()},
            "average_cost": {k: str(v) for k, v in self.average_cost.items()},
            "realised_pnl": str(self.realised_pnl),
            "daily_realised_pnl": str(self.daily_realised_pnl),
            "fees_paid": str(self.fees_paid),
            "order_count": self.order_count,
            "daily_loss": str(self.daily_loss),
        }
