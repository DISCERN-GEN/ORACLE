from __future__ import annotations

from decimal import Decimal, InvalidOperation
from math import log
from typing import Iterable

D = Decimal


def decimal(value: str | int | float | Decimal) -> Decimal:
    try:
        return value if isinstance(value, Decimal) else D(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid decimal value: {value!r}") from exc


def expected_value_yes(probability: Decimal, executable_price: Decimal, cost_per_share: Decimal = D("0")) -> Decimal:
    _probability(probability)
    _price(executable_price)
    if cost_per_share < 0:
        raise ValueError("cost_per_share cannot be negative")
    return probability - executable_price - cost_per_share


def expected_value_no(probability_yes: Decimal, executable_no_price: Decimal, cost_per_share: Decimal = D("0")) -> Decimal:
    _probability(probability_yes)
    _price(executable_no_price)
    if cost_per_share < 0:
        raise ValueError("cost_per_share cannot be negative")
    return (D("1") - probability_yes) - executable_no_price - cost_per_share


def binary_kelly_fraction(probability: Decimal, price: Decimal) -> Decimal:
    """Full-Kelly bankroll fraction for a $1 binary payout bought at `price`."""
    _probability(probability)
    _price(price)
    if price <= 0 or price >= 1:
        raise ValueError("price must be strictly between 0 and 1")
    b = (D("1") - price) / price
    q = D("1") - probability
    result = (b * probability - q) / b
    return max(D("0"), result)


def fractional_kelly_size(
    bankroll: Decimal,
    probability: Decimal,
    price: Decimal,
    multiplier: Decimal = D("0.25"),
    max_fraction: Decimal = D("0.02"),
) -> tuple[Decimal, Decimal]:
    if bankroll <= 0:
        raise ValueError("bankroll must be positive")
    if not D("0") <= multiplier <= D("1"):
        raise ValueError("multiplier must be in [0, 1]")
    if not D("0") <= max_fraction <= D("1"):
        raise ValueError("max_fraction must be in [0, 1]")
    full = binary_kelly_fraction(probability, price)
    actual_fraction = min(full * multiplier, max_fraction)
    return actual_fraction, bankroll * actual_fraction


def bayesian_update(prior: Decimal, likelihood_ratio: Decimal) -> Decimal:
    """Bayes update from prior probability and a likelihood ratio P(E|H)/P(E|not H)."""
    _probability(prior)
    if likelihood_ratio <= 0:
        raise ValueError("likelihood_ratio must be positive")
    if prior in (D("0"), D("1")):
        return prior
    odds = prior / (D("1") - prior)
    posterior_odds = odds * likelihood_ratio
    return posterior_odds / (D("1") + posterior_odds)


def brier_score(probabilities: Iterable[Decimal], outcomes: Iterable[int]) -> Decimal:
    pairs = list(zip(probabilities, outcomes, strict=True))
    if not pairs:
        raise ValueError("At least one forecast is required")
    for p, y in pairs:
        _probability(p)
        if y not in (0, 1):
            raise ValueError("Outcomes must be binary (0 or 1)")
    return sum(((p - D(y)) ** 2 for p, y in pairs), D("0")) / D(len(pairs))


def log_loss(probabilities: Iterable[Decimal], outcomes: Iterable[int], epsilon: Decimal = D("0.000001")) -> Decimal:
    pairs = list(zip(probabilities, outcomes, strict=True))
    if not pairs:
        raise ValueError("At least one forecast is required")
    if not D("0") < epsilon < D("0.5"):
        raise ValueError("epsilon must be between 0 and 0.5")
    values: list[Decimal] = []
    for p, y in pairs:
        _probability(p)
        if y not in (0, 1):
            raise ValueError("Outcomes must be binary (0 or 1)")
        clipped = min(max(p, epsilon), D("1") - epsilon)
        values.append(D(str(-(y * log(float(clipped)) + (1 - y) * log(float(1 - clipped))))))
    return sum(values, D("0")) / D(len(values))


def weighted_wallet_score(metrics: dict[str, Decimal], sample_size: int, prior_score: Decimal = D("0.5")) -> Decimal:
    """Apply the blueprint's weights, then shrink small samples toward a neutral prior."""
    weights = {
        "oos_predictive_skill": D("0.25"),
        "risk_adjusted_return": D("0.20"),
        "closing_line_value": D("0.15"),
        "consistency": D("0.15"),
        "timing_advantage": D("0.10"),
        "liquidity_capacity": D("0.10"),
        "data_quality": D("0.05"),
    }
    if sample_size < 0:
        raise ValueError("sample_size cannot be negative")
    missing = set(weights) - set(metrics)
    if missing:
        raise ValueError(f"Missing wallet metrics: {sorted(missing)}")
    for key, value in metrics.items():
        _probability(value)
    _probability(prior_score)
    raw = sum((metrics[k] * w for k, w in weights.items()), D("0"))
    # Transparent shrinkage; effective sample size saturates at 50 observations.
    reliability = D(sample_size) / (D(sample_size) + D("50")) if sample_size else D("0")
    return raw * reliability + prior_score * (D("1") - reliability)


def _probability(value: Decimal) -> None:
    if not D("0") <= value <= D("1"):
        raise ValueError("probability must be between 0 and 1")


def _price(value: Decimal) -> None:
    if not D("0") <= value <= D("1"):
        raise ValueError("price must be between 0 and 1")
