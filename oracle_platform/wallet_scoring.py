from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import sqrt

from .wallet_intelligence import WalletReconstruction

D = Decimal


@dataclass(frozen=True, slots=True)
class WalletScore:
    score: Decimal
    confidence: Decimal
    evidence_status: str
    sample_size: int
    observed_weight: Decimal
    components: dict[str, Decimal | None]
    warnings: tuple[str, ...]
    classification: str


def _clamp(value: Decimal) -> Decimal:
    return max(D("0"), min(D("1"), value))


def _wilson_lower_bound(wins: int, trials: int, z: float = 1.96) -> Decimal | None:
    """Conservative 95% Wilson lower bound for a binomial win-rate estimate."""
    if trials <= 0:
        return None
    p = wins / trials
    denom = 1 + z * z / trials
    centre = p + z * z / (2 * trials)
    margin = z * sqrt((p * (1 - p) + z * z / (4 * trials)) / trials)
    return D(str(max(0.0, (centre - margin) / denom)))


def score_wallet(
    reconstruction: WalletReconstruction,
    *,
    resolved_positions: int = 0,
    resolved_position_wins: int | None = None,
    out_of_sample_skill: Decimal | None = None,
    closing_line_value: Decimal | None = None,
    timing_advantage: Decimal | None = None,
    liquidity_capacity: Decimal | None = None,
    data_quality: Decimal | None = None,
) -> WalletScore:
    """Evidence-aware wallet score. Missing evidence remains missing, never zero-filled.

    The blueprint's weights are retained. Components unavailable from public trade
    reconstruction (OOS skill, CLV, timing, capacity) are not imputed; the composite is
    rescaled over observed components and is explicitly provisional until OOS validation.
    """
    warnings = list(reconstruction.completeness_notes)
    n = max(0, resolved_positions)
    observed: dict[str, Decimal | None] = {
        "out_of_sample_skill": out_of_sample_skill,
        "risk_adjusted_return": None,
        "closing_line_value": closing_line_value,
        "consistency": None,
        "timing_advantage": timing_advantage,
        "liquidity_capacity": liquidity_capacity,
        "data_quality": data_quality,
    }

    # Net ROI cannot be honestly calculated without a defensible capital denominator.
    # Profit factor is informative but not substituted for risk-adjusted return.
    if reconstruction.history_complete and reconstruction.total_pnl is not None:
        warnings.append("Complete trade-window P&L does not by itself establish risk-adjusted return or ROI.")
    else:
        warnings.append("P&L reconstruction is incomplete; risk-adjusted return is not scored.")

    if n > 0 and resolved_position_wins is not None and 0 <= resolved_position_wins <= n:
        observed["consistency"] = _wilson_lower_bound(resolved_position_wins, n)
    else:
        warnings.append("Resolved independent-position outcomes are unavailable; consistency is unscored.")

    if data_quality is None:
        # A transparent data-quality proxy, not a claim of complete account history.
        quality = D("0")
        if reconstruction.trade_count:
            quality += D("0.20")
        if reconstruction.duplicate_trade_count == 0 and reconstruction.trade_count:
            quality += D("0.15")
        if reconstruction.unmatched_sell_count == 0 and reconstruction.trade_count:
            quality += D("0.15")
        if reconstruction.fees_complete and reconstruction.trade_count:
            quality += D("0.15")
        if reconstruction.history_complete:
            quality += D("0.20")
        if reconstruction.initial_balances_known:
            quality += D("0.15")
        observed["data_quality"] = _clamp(quality)

    weights = {
        "out_of_sample_skill": D("0.25"),
        "risk_adjusted_return": D("0.20"),
        "closing_line_value": D("0.15"),
        "consistency": D("0.15"),
        "timing_advantage": D("0.10"),
        "liquidity_capacity": D("0.10"),
        "data_quality": D("0.05"),
    }
    available = [(key, value, weights[key]) for key, value in observed.items() if value is not None]
    total_weight = sum((weight for _, _, weight in available), D("0"))
    composite = (sum((value * weight for _, value, weight in available), D("0")) / total_weight
                 if total_weight else D("0"))

    # Confidence is deliberately conservative: evidence coverage, sample size and completeness.
    sample_factor = D(str(min(1.0, n / 100.0)))
    coverage_factor = total_weight
    completeness_factor = D("1") if reconstruction.history_complete else D("0.35")
    confidence = _clamp(sample_factor * coverage_factor * completeness_factor)

    if reconstruction.trade_count == 0:
        status = "insufficient_data"
    elif not reconstruction.history_complete or out_of_sample_skill is None:
        status = "provisional_unverified"
    elif confidence < D("0.70") or n < 30:
        status = "insufficient_statistical_evidence"
    else:
        status = "eligible_for_further_validation"

    classification = "unclassified"
    if reconstruction.buy_count and reconstruction.sell_count:
        if reconstruction.capital_turnover > D("5"):
            classification = "high_turnover_participant"
        elif reconstruction.capital_turnover < D("1.5"):
            classification = "longer_horizon_directional_candidate"
        else:
            classification = "directional_or_mixed_candidate"
    elif reconstruction.buy_count:
        classification = "buy_only_or_open_inventory"

    if out_of_sample_skill is None:
        warnings.append("No independently validated out-of-sample predictive-skill evidence was supplied.")
    return WalletScore(
        score=_clamp(composite), confidence=confidence, evidence_status=status,
        sample_size=n, observed_weight=total_weight, components=observed,
        warnings=tuple(dict.fromkeys(warnings)),
        classification=classification,
    )
