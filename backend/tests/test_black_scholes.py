"""Unit tests for the Black-Scholes barrier-touch probability, both directions.

Regression test for a bug where a target below the current price always
returned 100% instead of computing the actual downward-touch probability.
Run from backend/: venv/Scripts/python -m unittest tests.test_black_scholes
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.pricing.black_scholes import probability_reach_target
from app.pricing.monte_carlo import simulate_touch_probability


class BlackScholesTouchProbabilityTest(unittest.TestCase):
    def test_upward_target_is_between_zero_and_one(self):
        result = probability_reach_target(
            s0=100, target_price=120, t_years=1, risk_free_rate=0.04, volatility=0.35
        )
        self.assertGreater(result.probability, 0.0)
        self.assertLess(result.probability, 1.0)

    def test_downward_target_is_not_always_certain(self):
        # Regression test: this used to hard-code 1.0 for any target <= s0.
        result = probability_reach_target(
            s0=200, target_price=100, t_years=1, risk_free_rate=0.045, volatility=0.38
        )
        self.assertGreater(result.probability, 0.0)
        self.assertLess(result.probability, 1.0)

    def test_farther_downward_target_is_less_likely(self):
        near = probability_reach_target(
            s0=200, target_price=180, t_years=1, risk_free_rate=0.045, volatility=0.38
        )
        far = probability_reach_target(
            s0=200, target_price=100, t_years=1, risk_free_rate=0.045, volatility=0.38
        )
        self.assertGreater(near.probability, far.probability)

    def test_farther_upward_target_is_less_likely(self):
        near = probability_reach_target(
            s0=200, target_price=220, t_years=1, risk_free_rate=0.045, volatility=0.38
        )
        far = probability_reach_target(
            s0=200, target_price=400, t_years=1, risk_free_rate=0.045, volatility=0.38
        )
        self.assertGreater(near.probability, far.probability)

    def test_target_equal_to_current_price_is_certain(self):
        result = probability_reach_target(
            s0=150, target_price=150, t_years=1, risk_free_rate=0.04, volatility=0.3
        )
        self.assertEqual(result.probability, 1.0)

    def test_continuity_correction_aligns_with_daily_monte_carlo(self):
        # With identical drift/vol inputs, the BGK correction should bring
        # Black-Scholes (continuous monitoring) close to Monte Carlo's daily
        # monitoring — within simulation noise, not several points apart.
        bs = probability_reach_target(s0=100, target_price=120, t_years=1, risk_free_rate=0.04, volatility=0.35)
        mc = simulate_touch_probability(
            s0=100, target_price=120, t_years=1, risk_free_rate=0.04, volatility=0.35, n_simulations=50_000, seed=1
        )
        self.assertLess(abs(bs.probability - mc.probability), 0.02)


if __name__ == "__main__":
    unittest.main()
