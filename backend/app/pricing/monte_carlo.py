"""Monte Carlo barrier-touch probability, with a hook for a sector/ML adjustment.

Simulates full price paths (not just the endpoint) so "touches the target
at any point within the horizon" falls out naturally from the simulation,
using historical volatility as the base input.
"""
from dataclasses import dataclass
from typing import Optional

import numpy as np

TRADING_DAYS_PER_YEAR = 252
# Checking the price only once a day (at close) misses touches that happen
# and reverse intraday. Simulating several checks per trading day brings the
# discretization closer to continuous monitoring, which is what
# black_scholes.py's closed-form formula assumes (its BGK continuity
# correction is calibrated to this same per-year step count — keep both in
# sync if this changes).
INTRADAY_STEPS_PER_DAY = 8
DEFAULT_STEPS_PER_YEAR = TRADING_DAYS_PER_YEAR * INTRADAY_STEPS_PER_DAY


@dataclass
class MonteCarloResult:
    probability: float
    method: str
    volatility_used: float
    volatility_source: str
    n_simulations: int
    sector_adjustment_applied: Optional[float] = None


def simulate_touch_probability(
    s0: float,
    target_price: float,
    t_years: float,
    risk_free_rate: float,
    volatility: float,
    n_simulations: int = 20_000,
    n_steps_per_year: int = DEFAULT_STEPS_PER_YEAR,
    sector_adjustment: Optional[float] = None,
    seed: Optional[int] = None,
) -> MonteCarloResult:
    """Simulate GBM price paths and estimate P(path touches target_price within t_years).

    sector_adjustment is an optional multiplicative nudge (e.g. from the ML
    sector-trend model) applied to the drift before simulating, so a strong
    sector tailwind/headwind shifts the simulated paths accordingly.
    """
    rng = np.random.default_rng(seed)
    n_steps = max(1, round(t_years * n_steps_per_year))
    dt = t_years / n_steps

    drift = risk_free_rate
    if sector_adjustment is not None:
        drift = drift + sector_adjustment

    increments = (drift - 0.5 * volatility ** 2) * dt + volatility * np.sqrt(dt) * rng.standard_normal(
        (n_simulations, n_steps)
    )
    log_paths = np.cumsum(increments, axis=1)
    price_paths = s0 * np.exp(log_paths)

    if target_price >= s0:
        touched = np.any(price_paths >= target_price, axis=1)
    else:
        touched = np.any(price_paths <= target_price, axis=1)

    probability = float(np.mean(touched))

    return MonteCarloResult(
        probability=probability,
        method="monte_carlo_barrier",
        volatility_used=volatility,
        volatility_source="historical",
        n_simulations=n_simulations,
        sector_adjustment_applied=sector_adjustment,
    )
