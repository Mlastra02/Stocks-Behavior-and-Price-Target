"""Tests for momentum_model.py's event-matching logic: window-proximity
filtering (a 3-day spike shouldn't match a 20-day grind just because the
% is similar), magnitude thresholding + fallback, and the analyst-target
before/after context. Network calls are mocked — deterministic, synthetic
price series only.

Run from backend/: venv/Scripts/python -m unittest tests.test_momentum_model
"""
import sys
import os
import math
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.price_series_helper import build_price_series

from app.pricing import momentum_model


def _set_window_move(returns, start, window, total_log_return):
    """Overwrite `window` consecutive daily returns starting at `start` so
    their cumulative log-return equals total_log_return."""
    daily = total_log_return / window
    for i in range(start, start + window):
        returns[i] = daily


class AnalyzeEventMatchingTest(unittest.TestCase):
    def _analyze_with(self, prices, analyst_target=None):
        with patch.object(momentum_model.market_data, "get_price_history", return_value=prices), patch.object(
            momentum_model.market_data, "analyst_price_target", return_value=analyst_target
        ):
            return momentum_model.analyze("TEST")

    def test_window_proximity_filter_excludes_distant_duration_episodes(self):
        rng = np.random.default_rng(1)
        n = 500
        returns = list(rng.normal(0, 0.0015, n))

        # A big, slow 20-day climb to +20%, well before the end.
        _set_window_move(returns, 150, 20, math.log(1.20))
        # Current move: a sharp 3-day +20% jump at the very end.
        _set_window_move(returns, n - 3, 3, math.log(1.20))

        prices = build_price_series(returns)
        result = self._analyze_with(prices)

        self.assertEqual(result.detected_window_days, 3)
        self.assertGreater(result.current_move_pct, 0.15)

        # The 20-day episode must never surface, matched or fallback — its
        # duration is outside the proximity band around the 3-day current move.
        max_allowed_window = 3 * momentum_model.WINDOW_PROXIMITY_RATIO
        for ep in result.episode_details:
            self.assertLessEqual(ep["window_days"], max_allowed_window)

    def test_finds_true_match_with_similar_window_and_magnitude(self):
        rng = np.random.default_rng(2)
        n = 500
        returns = list(rng.normal(0, 0.0015, n))

        _set_window_move(returns, 200, 3, math.log(1.18))  # comparable magnitude, same window
        _set_window_move(returns, n - 3, 3, math.log(1.20))  # current move

        prices = build_price_series(returns)
        result = self._analyze_with(prices)

        self.assertFalse(result.used_fallback)
        self.assertGreaterEqual(result.episodes_found, 1)
        # Not necessarily exactly window=3 (the scan can land a day or two
        # off the engineered block's edge), but must stay within the
        # proximity band around the current 3-day move — the code already
        # guarantees this for non-fallback matches, so this just confirms it.
        max_allowed_window = 3 * momentum_model.WINDOW_PROXIMITY_RATIO
        self.assertTrue(all(e["window_days"] <= max_allowed_window for e in result.episode_details))

    def test_opposite_direction_move_is_never_matched(self):
        rng = np.random.default_rng(4)
        n = 500
        returns = list(rng.normal(0, 0.0015, n))

        _set_window_move(returns, 200, 3, math.log(0.80))  # a -20% drop, opposite direction
        _set_window_move(returns, n - 3, 3, math.log(1.20))  # current move: +20%

        prices = build_price_series(returns)
        result = self._analyze_with(prices)

        for ep in result.episode_details:
            self.assertGreaterEqual(ep["move_pct"], 0)

    def test_fallback_reports_pct_of_current_consistently(self):
        rng = np.random.default_rng(3)
        n = 400
        returns = list(rng.normal(0, 0.001, n))

        _set_window_move(returns, 100, 3, math.log(1.05))  # far smaller than the current move
        _set_window_move(returns, n - 3, 3, math.log(1.30))  # current move

        prices = build_price_series(returns)
        result = self._analyze_with(prices)

        self.assertTrue(result.used_fallback)
        self.assertGreaterEqual(len(result.episode_details), 1)
        for e in result.episode_details:
            expected = abs(e["move_pct"]) / abs(result.current_move_pct)
            self.assertAlmostEqual(e["pct_of_current"], expected, places=9)


class AnalystContextTest(unittest.TestCase):
    def test_upside_now_and_before_move(self):
        returns = [0.0] * 50 + [math.log(1.20) / 3] * 3
        prices = build_price_series(returns)["adj_close"]

        # Target comfortably above the ~120 the series lands on, so this
        # doesn't hinge on exact floating-point equality with the price.
        target = 150.0
        with patch.object(momentum_model.market_data, "analyst_price_target", return_value=target):
            ctx = momentum_model._analyst_context("TEST", prices, current_window=3)

        current_price = float(prices.iloc[-1])
        price_before_move = float(prices.iloc[-1 - 3])

        self.assertAlmostEqual(ctx.upside_now_pct, target / current_price - 1, places=9)
        self.assertAlmostEqual(ctx.upside_before_move_pct, target / price_before_move - 1, places=9)
        self.assertFalse(ctx.already_above_target)

    def test_already_above_target_flag(self):
        prices = build_price_series([0.001] * 60)["adj_close"]

        with patch.object(momentum_model.market_data, "analyst_price_target", return_value=1.0):
            ctx = momentum_model._analyst_context("TEST", prices, current_window=3)

        self.assertTrue(ctx.already_above_target)
        self.assertLess(ctx.upside_now_pct, 0)

    def test_no_analyst_coverage_returns_none_fields(self):
        prices = build_price_series([0.001] * 60)["adj_close"]

        with patch.object(momentum_model.market_data, "analyst_price_target", return_value=None):
            ctx = momentum_model._analyst_context("TEST", prices, current_window=3)

        self.assertIsNone(ctx.target_price)
        self.assertIsNone(ctx.upside_now_pct)
        self.assertIsNone(ctx.upside_before_move_pct)
        self.assertFalse(ctx.already_above_target)


if __name__ == "__main__":
    unittest.main()
