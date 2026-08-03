"""Black-Scholes barrier-touch probability.

Given the standard Black-Scholes assumptions (geometric Brownian motion,
constant volatility and drift), the probability that the price touches a
barrier B at any point within [0, T] has a closed form via the reflection
principle. This is what we use to answer "probability the stock reaches
the price target within N months", not just "ends above it at expiry".
"""
import math
from dataclasses import dataclass
from scipy.stats import norm

# Broadie-Glasserman-Kou (1997) continuity correction. The reflection-principle
# formula below assumes the barrier is watched continuously; our Monte Carlo
# simulation (monte_carlo.py) only checks the price once a day (252 times a
# year). Left uncorrected, that mismatch alone makes Black-Scholes read
# systematically higher than Monte Carlo, even with identical drift/vol
# inputs. The correction shifts the barrier slightly further from s0 before
# evaluating the continuous formula, which approximates what a
# discretely-monitored (daily) barrier probability would be.
BGK_BETA = 0.5826  # -zeta(1/2) / sqrt(2*pi)
DISCRETE_MONITORING_POINTS_PER_YEAR = 252 * 8  # keep in sync with monte_carlo.DEFAULT_STEPS_PER_YEAR


@dataclass
class BarrierTouchResult:
    probability: float
    method: str
    volatility_used: float
    volatility_source: str


def _continuity_corrected_barrier(s0: float, barrier: float, sigma: float) -> float:
    """Shift the barrier outward so the continuous formula approximates daily monitoring."""
    dt = 1.0 / DISCRETE_MONITORING_POINTS_PER_YEAR
    shift = math.exp(BGK_BETA * sigma * math.sqrt(dt))
    return barrier * shift if barrier > s0 else barrier / shift


def _touch_probability(s0: float, barrier: float, t_years: float, mu: float, sigma: float) -> float:
    """P(exists t in [0,T]: S_t crosses barrier) under GBM with drift mu and vol sigma,
    approximating daily (not continuous) monitoring via the BGK continuity correction.

    Uses the reflection principle for Brownian motion with drift, applied to
    log(S_t / S0). Handles both directions: for a barrier below s0, the
    problem is mirrored (distance measured as ln(s0/barrier), drift negated)
    since a downward hit is the same reflection-principle result applied to
    -W_t, which is itself a standard Brownian motion.
    """
    if barrier == s0:
        return 1.0

    barrier = _continuity_corrected_barrier(s0, barrier, sigma)

    upward = barrier > s0
    if upward:
        x = math.log(barrier / s0)
        nu = mu - 0.5 * sigma ** 2
    else:
        x = math.log(s0 / barrier)
        nu = 0.5 * sigma ** 2 - mu

    sqrt_t = math.sqrt(t_years)
    d1 = (nu * t_years - x) / (sigma * sqrt_t)
    d2 = (-nu * t_years - x) / (sigma * sqrt_t)

    term1 = norm.cdf(d1)
    term2 = math.exp(2 * nu * x / sigma ** 2) * norm.cdf(d2)

    return min(1.0, term1 + term2)


def probability_reach_target(
    s0: float,
    target_price: float,
    t_years: float,
    risk_free_rate: float,
    volatility: float,
    volatility_source: str = "implied",
) -> BarrierTouchResult:
    """Probability of touching target_price within t_years, Black-Scholes closed form.

    risk_free_rate is used as the drift (risk-neutral measure), consistent
    with standard Black-Scholes option pricing.
    """
    prob = _touch_probability(s0, target_price, t_years, risk_free_rate, volatility)
    return BarrierTouchResult(
        probability=prob,
        method="black_scholes_barrier",
        volatility_used=volatility,
        volatility_source=volatility_source,
    )
