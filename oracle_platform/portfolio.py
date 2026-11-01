from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

D = Decimal


@dataclass(frozen=True, slots=True)
class PortfolioAllocation:
    fractions: tuple[Decimal, ...]
    expected_return: Decimal
    variance: Decimal
    approximate_log_growth: Decimal
    iterations: int
    converged: bool


def mean_variance_kelly_approx(
    expected_excess_returns: Sequence[Decimal],
    covariance: Sequence[Sequence[Decimal]],
    *,
    max_single_fraction: Decimal = D("0.02"),
    max_total_fraction: Decimal = D("0.25"),
    tolerance: Decimal = D("0.00000001"),
    max_iterations: int = 20_000,
) -> PortfolioAllocation:
    """Long-only constrained Kelly approximation using mean-variance log growth.

    This solves max(mu'f - 0.5 f'Sigma f) over a capped simplex. It is a conservative
    approximation, not exact joint-outcome Kelly. Inputs must be estimated out-of-sample.
    It deliberately has no external optimiser dependency.
    """
    mu = tuple(expected_excess_returns)
    sigma = tuple(tuple(row) for row in covariance)
    n = len(mu)
    if n == 0 or len(sigma) != n or any(len(row) != n for row in sigma):
        raise ValueError("Expected-return vector and covariance matrix dimensions must match")
    if not D("0") < max_single_fraction <= D("1"):
        raise ValueError("max_single_fraction must be in (0, 1]")
    if not D("0") < max_total_fraction <= D("1"):
        raise ValueError("max_total_fraction must be in (0, 1]")
    if tolerance <= 0 or max_iterations < 1:
        raise ValueError("Invalid optimiser convergence settings")
    if any(not value.is_finite() for value in mu):
        raise ValueError("Expected returns must be finite")
    for i in range(n):
        if any(not value.is_finite() for value in sigma[i]):
            raise ValueError("Covariance values must be finite")
        if sigma[i][i] < 0:
            raise ValueError("Covariance diagonal cannot be negative")
        for j in range(n):
            if abs(sigma[i][j] - sigma[j][i]) > D("0.000000001"):
                raise ValueError("Covariance matrix must be symmetric")
            bound = (sigma[i][i] * sigma[j][j]).sqrt()
            if abs(sigma[i][j]) > bound + D("0.000000001"):
                raise ValueError("Covariance violates pairwise variance bounds")
    _require_positive_semidefinite(sigma)

    # Gershgorin upper bound on the largest eigenvalue for a stable projected step.
    lipschitz = max((sum((abs(x) for x in row), D("0")) for row in sigma), default=D("0"))
    step = D("1") / max(lipschitz, D("1"))
    fractions = [D("0") for _ in range(n)]
    converged = False
    iteration = 0
    for iteration in range(1, max_iterations + 1):  # noqa: B007 - read after the loop
        gradient = [mu[i] - sum((sigma[i][j] * fractions[j] for j in range(n)), D("0"))
                    for i in range(n)]
        candidate = _project_capped_simplex(
            [fractions[i] + step * gradient[i] for i in range(n)],
            max_single_fraction, max_total_fraction,
        )
        difference = max((abs(candidate[i] - fractions[i]) for i in range(n)), default=D("0"))
        fractions = candidate
        if difference <= tolerance:
            converged = True
            break
    expected = sum((mu[i] * fractions[i] for i in range(n)), D("0"))
    variance = sum((fractions[i] * sigma[i][j] * fractions[j]
                    for i in range(n) for j in range(n)), D("0"))
    growth = expected - variance / D("2")
    return PortfolioAllocation(tuple(fractions), expected, variance, growth, iteration, converged)


def _project_capped_simplex(values: list[Decimal], cap: Decimal, total: Decimal) -> list[Decimal]:
    clipped = [max(D("0"), min(cap, value)) for value in values]
    if sum(clipped, D("0")) <= total:
        return clipped
    low = min(values) - cap
    high = max(values)
    for _ in range(100):
        threshold = (low + high) / D("2")
        projected = [max(D("0"), min(cap, value - threshold)) for value in values]
        if sum(projected, D("0")) > total:
            low = threshold
        else:
            high = threshold
    return [max(D("0"), min(cap, value - high)) for value in values]


def _require_positive_semidefinite(matrix: Sequence[Sequence[Decimal]]) -> None:
    """Modified Cholesky check for a symmetric positive-semidefinite matrix."""
    n = len(matrix)
    lower = [[D("0") for _ in range(n)] for _ in range(n)]
    eps = D("0.0000000001")
    for i in range(n):
        for j in range(i + 1):
            residual = matrix[i][j] - sum((lower[i][k] * lower[j][k] for k in range(j)), D("0"))
            if i == j:
                if residual < -eps:
                    raise ValueError("Covariance matrix must be positive semidefinite")
                lower[i][j] = max(D("0"), residual).sqrt()
            elif lower[j][j] > eps:
                lower[i][j] = residual / lower[j][j]
            elif abs(residual) > eps:
                raise ValueError("Covariance matrix must be positive semidefinite")
