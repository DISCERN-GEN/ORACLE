from decimal import Decimal as D

import pytest

from oracle_platform.forecasting import BetaPrior, EvidenceItem, evaluate_forecasts, update_with_independent_evidence


def test_beta_prior_updates_with_resolved_observations():
    prior = BetaPrior(D("1"), D("1"))
    posterior = prior.update(successes=7, failures=3)
    assert prior.mean == D("0.5")
    assert posterior.mean == D("0.6666666666666666666666666667")


def test_bayesian_evidence_requires_independent_groups():
    items = [
        EvidenceItem("official-release", D("3"), "primary"),
        EvidenceItem("independent-report", D("1.5"), "journalism"),
    ]
    posterior, refs = update_with_independent_evidence(D("0.5"), items)
    assert posterior > D("0.5")
    assert refs == ("official-release", "independent-report")
    with pytest.raises(ValueError, match="Dependent/duplicate"):
        update_with_independent_evidence(D("0.5"), [items[0], EvidenceItem("copy", D("2"), "primary")])


def test_forecast_evaluation_uses_oos_probabilities_and_binary_scores():
    result = evaluate_forecasts([D("0.8"), D("0.2")], [1, 0])
    assert result["sample_size"] == 2
    assert result["brier_score"] == D("0.04")
