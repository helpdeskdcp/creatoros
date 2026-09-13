"""Real statistical significance testing for proportion-style metrics
(CTR, engagement rate) -- replaces a naive 'lift > 20% = HIGH confidence'
heuristic with an actual two-proportion z-test. Stdlib only (math.erf for
the normal CDF), no scipy dependency needed for this.
"""
import math

from app.core.data_quality import Confidence


def two_proportion_z_test(p1: float, n1: int, p2: float, n2: int) -> tuple[float, float]:
    """Returns (z_score, two_tailed_p_value) comparing two observed
    proportions p1 (from n1 observations) and p2 (from n2 observations).
    Standard pooled-proportion z-test for A/B comparisons."""
    if n1 <= 0 or n2 <= 0:
        return 0.0, 1.0
    p_pool = (p1 * n1 + p2 * n2) / (n1 + n2)
    variance = p_pool * (1 - p_pool) * (1 / n1 + 1 / n2)
    if variance <= 0:
        return 0.0, 1.0
    se = math.sqrt(variance)
    z = (p1 - p2) / se
    p_value = 2 * (1 - _normal_cdf(abs(z)))
    return z, p_value


def _normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def confidence_from_p_value(p_value: float) -> str:
    if p_value < 0.01:
        return Confidence.HIGH.value
    if p_value < 0.05:
        return Confidence.MEDIUM.value
    return Confidence.LOW.value
