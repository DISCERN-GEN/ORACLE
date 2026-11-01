from decimal import Decimal as D

import pytest

from oracle_platform.quantitative import (
    bayesian_update,
    brier_score,
    expected_value_yes,
    fractional_kelly_size,
    log_loss,
    weighted_wallet_score,
)


def test_expected_value_yes_deducts_costs():
    assert expected_value_yes(D("0.72"), D("0.58"), D("0.01")) == D("0.13")


def test_fractional_kelly_respects_hard_cap():
    fraction, notional = fractional_kelly_size(D("10000"), D("0.72"), D("0.58"),
                                               D("0.25"), D("0.02"))
    assert fraction == D("0.02")
    assert notional == D("200.00")


def test_bayesian_update():
    posterior = bayesian_update(D("0.50"), D("3"))
    assert posterior == D("0.75")


def test_brier_score():
    assert brier_score([D("0.8"), D("0.3")], [1, 0]) == D("0.065")


def test_log_loss_is_finite_and_positive():
    value = log_loss([D("0.8"), D("0.3")], [1, 0])
    assert value > 0


def test_wallet_score_shrinks_small_samples_to_neutral():
    metrics = {k: D("1") for k in [
        "oos_predictive_skill", "risk_adjusted_return", "closing_line_value",
        "consistency", "timing_advantage", "liquidity_capacity", "data_quality"]}
    score = weighted_wallet_score(metrics, sample_size=1)
    assert D("0.5") < score < D("0.52")


def test_invalid_probability_rejected():
    with pytest.raises(ValueError):
        bayesian_update(D("1.2"), D("2"))
