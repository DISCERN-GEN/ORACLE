from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from .domain import Forecast
from .quantitative import bayesian_update, brier_score, log_loss

D = Decimal


@dataclass(frozen=True, slots=True)
class BetaPrior:
    alpha: Decimal = D("1")
    beta: Decimal = D("1")

    def __post_init__(self) -> None:
        if self.alpha <= 0 or self.beta <= 0:
            raise ValueError("Beta prior parameters must be positive")

    @property
    def mean(self) -> Decimal:
        return self.alpha / (self.alpha + self.beta)

    def update(self, successes: int, failures: int) -> "BetaPrior":
        if successes < 0 or failures < 0:
            raise ValueError("successes and failures cannot be negative")
        return BetaPrior(self.alpha + D(successes), self.beta + D(failures))


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    evidence_id: str
    likelihood_ratio: Decimal
    independence_group: str
    confidence: Decimal = D("1")

    def __post_init__(self) -> None:
        if not self.evidence_id.strip() or not self.independence_group.strip():
            raise ValueError("Evidence id and independence group are required")
        if self.likelihood_ratio <= 0:
            raise ValueError("Likelihood ratio must be positive")
        if not D("0") <= self.confidence <= D("1"):
            raise ValueError("Evidence confidence must be in [0, 1]")


def update_with_independent_evidence(prior: Decimal, evidence: Iterable[EvidenceItem]) -> tuple[Decimal, tuple[str, ...]]:
    """Update a probability with one evidence item per independent source group.

    Confidence tempers each likelihood ratio in log-odds space. Duplicate sources from
    the same independence_group are rejected instead of double-counted.
    """
    posterior = prior
    seen: set[str] = set()
    references: list[str] = []
    for item in evidence:
        if item.independence_group in seen:
            raise ValueError(f"Dependent/duplicate evidence group: {item.independence_group}")
        seen.add(item.independence_group)
        if item.confidence == 0:
            references.append(item.evidence_id)
            continue
        tempered_lr = (item.likelihood_ratio.ln() * item.confidence).exp()
        posterior = bayesian_update(posterior, tempered_lr)
        references.append(item.evidence_id)
    return posterior, tuple(references)


def create_forecast(
    *, market_id: str,
    outcome: str,
    prior: BetaPrior,
    evidence: Iterable[EvidenceItem],
    lower_bound: Decimal,
    upper_bound: Decimal,
    confidence: Decimal,
    model_id: str,
    model_version: str,
    validated: bool = False,
) -> Forecast:
    posterior, refs = update_with_independent_evidence(prior.mean, evidence)
    return Forecast(market_id, outcome, posterior, lower_bound, upper_bound, confidence,
                    model_id, model_version, validated, refs)


def evaluate_forecasts(probabilities: Iterable[Decimal], outcomes: Iterable[int]) -> dict[str, Decimal | int]:
    p = list(probabilities)
    y = list(outcomes)
    if len(p) != len(y):
        raise ValueError("Forecast and outcome collections must have equal length")
    return {"sample_size": len(p), "brier_score": brier_score(p, y), "log_loss": log_loss(p, y)}
