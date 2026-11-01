from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from .domain import Decision, Forecast, OrderBook, OrderIntent, PaperAccount, RiskDecision
from .settings import settings


@dataclass(frozen=True, slots=True)
class RiskLimits:
    max_order_notional: Decimal = settings.paper_max_order_notional
    max_single_market_exposure: Decimal = settings.paper_max_single_market_exposure
    max_portfolio_exposure: Decimal = settings.paper_max_portfolio_exposure
    max_daily_loss: Decimal = settings.paper_max_daily_loss
    max_kelly_fraction: Decimal = settings.paper_max_kelly_fraction
    max_data_age_seconds: int = settings.market_data_max_age_seconds


class RiskEngine:
    def __init__(self, limits: RiskLimits | None = None) -> None:
        self.limits = limits or RiskLimits()
        self.kill_switch_active = False

    def evaluate_paper(
        self,
        intent: OrderIntent,
        forecast: Forecast,
        book: OrderBook,
        account: PaperAccount,
        requested_kelly_fraction: Decimal,
        net_expected_value: Decimal,
        now: datetime | None = None,
    ) -> RiskDecision:
        now = now or datetime.now(UTC)
        passed: list[str] = []
        failed: list[str] = []
        exposure_increment = intent.notional if intent.side.value == "BUY" else Decimal("0")
        checks = [
            (not self.kill_switch_active, "kill_switch_clear"),
            (intent.limit_price > 0 and intent.limit_price < 1, "valid_binary_price"),
            (intent.quantity > 0, "positive_quantity"),
            (intent.notional <= self.limits.max_order_notional, "max_order_notional"),
            (intent.notional <= account.initial_cash * requested_kelly_fraction, "kelly_notional_budget"),
            (book.token_id == intent.token_id, "token_matches_book"),
            (book.market_id == intent.market_id, "market_matches_book"),
            (book.age_seconds(now) <= self.limits.max_data_age_seconds, "fresh_market_data"),
            (forecast.market_id == intent.market_id, "forecast_matches_market"),
            (forecast.confidence >= Decimal("0.50"), "minimum_forecast_confidence"),
            (net_expected_value > 0, "positive_net_expected_value"),
            (requested_kelly_fraction >= 0 and requested_kelly_fraction <= self.limits.max_kelly_fraction, "kelly_cap"),
            (account.daily_loss < self.limits.max_daily_loss, "daily_loss_limit"),
            (account.cash >= intent.notional if intent.side.value == "BUY" else account.positions.get(intent.token_id, Decimal("0")) >= intent.quantity, "funds_or_inventory_available"),
            (account.market_exposure.get(intent.market_id, Decimal("0")) + exposure_increment <= self.limits.max_single_market_exposure, "single_market_exposure"),
            (sum(account.market_exposure.values(), Decimal("0")) + exposure_increment <= self.limits.max_portfolio_exposure, "portfolio_exposure"),
        ]
        for ok, label in checks:
            (passed if ok else failed).append(label)
        decision = Decision.APPROVE if not failed else Decision.REJECT
        max_notional = min(intent.notional, self.limits.max_order_notional) if decision == Decision.APPROVE else Decimal("0")
        return RiskDecision(
            decision=decision,
            max_notional=max_notional,
            checks_passed=tuple(passed),
            checks_failed=tuple(failed),
            rationale="Paper-only deterministic risk evaluation; LLM cannot alter this result.",
        )

    def evaluate_live(self, *_: object, **__: object) -> RiskDecision:
        # No live execution capability is shipped in this initial implementation.
        return RiskDecision(
            decision=Decision.REJECT,
            max_notional=Decimal("0"),
            checks_failed=("live_execution_not_implemented", "legal_review_not_verified"),
            rationale="Live execution is hard-disabled in the ORACLE private paper-only build.",
        )
