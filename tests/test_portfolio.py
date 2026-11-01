from decimal import Decimal as D

import pytest

from oracle_platform.portfolio import mean_variance_kelly_approx


def test_portfolio_optimizer_respects_single_and_total_caps():
    result = mean_variance_kelly_approx(
        [D("0.20"), D("0.15"), D("0.12")],
        [[D("0.10"), D("0.02"), D("0.01")],
         [D("0.02"), D("0.12"), D("0.03")],
         [D("0.01"), D("0.03"), D("0.08")]],
        max_single_fraction=D("0.10"), max_total_fraction=D("0.20"),
    )
    assert all(D("0") <= x <= D("0.10") for x in result.fractions)
    assert sum(result.fractions) <= D("0.200000001")
    assert result.approximate_log_growth > 0


def test_portfolio_optimizer_rejects_asymmetric_covariance():
    with pytest.raises(ValueError, match="symmetric"):
        mean_variance_kelly_approx([D("0.1"), D("0.2")],
                                   [[D("0.1"), D("0.01")], [D("0.02"), D("0.1")]])


def test_portfolio_optimizer_rejects_non_positive_semidefinite_matrix():
    with pytest.raises(ValueError, match="positive semidefinite"):
        mean_variance_kelly_approx(
            [D("0.1"), D("0.1"), D("0.1")],
            [[D("1"), D("-0.9"), D("-0.9")],
             [D("-0.9"), D("1"), D("-0.9")],
             [D("-0.9"), D("-0.9"), D("1")]],
        )
