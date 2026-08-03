"""Regression tests for sector_model.py, covering the specific bugs found
during development: annualizing a short-window effect by 252 instead of
~4x, and predicting raw (not demeaned) forward returns so the stock's
baseline drift leaked into the "adjustment" and got double-counted on top
of the risk-free rate. Network calls are mocked out — this only tests the
math, deterministically.

Run from backend/: venv/Scripts/python -m unittest tests.test_sector_model
"""
import sys
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.price_series_helper import build_price_series

from app.pricing import sector_model


class AnnualizationFactorTest(unittest.TestCase):
    def test_annualization_factor_is_quarterly_not_daily(self):
        # Regression guard: this used to be 252 (treating the fitted
        # next-day effect as if it repeated identically every trading day
        # of the year), which massively overstated any signal.
        self.assertAlmostEqual(sector_model.ANNUALIZATION_FACTOR, 252 / 63)
        self.assertNotAlmostEqual(sector_model.ANNUALIZATION_FACTOR, 252)


class ShrinkageTest(unittest.TestCase):
    def test_bounded_between_min_and_max(self):
        self.assertAlmostEqual(sector_model._shrinkage_for(0), sector_model.MIN_SHRINKAGE)
        self.assertAlmostEqual(
            sector_model._shrinkage_for(sector_model.FULL_CONFIDENCE_INDEPENDENT_EPISODES * sector_model.MOMENTUM_WINDOW_DAYS),
            sector_model.MAX_SHRINKAGE,
        )
        # Far more data than the "full confidence" point still caps at MAX_SHRINKAGE.
        huge = sector_model._shrinkage_for(1_000_000)
        self.assertAlmostEqual(huge, sector_model.MAX_SHRINKAGE)

    def test_increases_with_sample_size(self):
        small = sector_model._shrinkage_for(500)
        medium = sector_model._shrinkage_for(1500)
        large = sector_model._shrinkage_for(3000)
        self.assertLess(small, medium)
        self.assertLess(medium, large)


class BuildFeaturesTest(unittest.TestCase):
    def test_forward_return_looks_ahead_not_behind(self):
        # Flat returns except one clean +10% jump placed well into the future
        # relative to the start of the series.
        n = 300
        jump_at = 200
        returns = [0.0001] * n
        returns[jump_at] = 0.10

        stock_prices = build_price_series(returns)
        sector_prices = build_price_series([0.0001] * n)

        with patch.object(sector_model.market_data, "get_price_history") as mock_history:
            mock_history.side_effect = lambda symbol: stock_prices if symbol == "TEST" else sector_prices
            df = sector_model._build_features("TEST", "TESTSECTOR")

        # _daily_log_returns drops the series' first row, and the final
        # dropna() drops the first MOMENTUM_WINDOW_DAYS-1 rows too (no full
        # trailing momentum window yet) — both shift the jump's position
        # within the returned df.
        jump_df_pos = jump_at - 1 - (sector_model.MOMENTUM_WINDOW_DAYS - 1)

        # A row comfortably before the jump should have it captured ahead of it...
        row_before_jump = jump_df_pos - 50
        self.assertGreater(df["forward_return"].iloc[row_before_jump], 0.05)

        # ...while df's last valid row (whose forward window starts well
        # after the jump) should not see it again ahead.
        self.assertLess(abs(df["forward_return"].iloc[-1]), 0.02)


class PredictDriftAdjustmentTest(unittest.TestCase):
    def setUp(self):
        # train_symbol writes a .joblib file to MODEL_DIR — redirect it to a
        # temp dir for the test so it never touches the real trained models.
        self._tmp_dir = tempfile.mkdtemp()
        self._model_dir_patch = patch.object(sector_model, "MODEL_DIR", self._tmp_dir)
        self._model_dir_patch.start()

    def tearDown(self):
        self._model_dir_patch.stop()
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def _mock_symbol(self, symbol, stock_prices, sector_prices):
        return patch.object(
            sector_model.market_data,
            "get_price_history",
            side_effect=lambda s: stock_prices if s == symbol else sector_prices,
        )

    def test_typical_momentum_does_not_leak_baseline_drift(self):
        # Strong constant baseline drift (~28%/yr) with random noise and NO
        # real relationship between momentum and forward returns. At the
        # stock's own typical (average) momentum, the adjustment should be
        # small — not a reflection of that baseline drift, which belongs to
        # the stock's normal expected return, not an "unusual momentum" signal.
        rng = np.random.default_rng(42)
        n = 900
        stock_returns = list(0.0011 + rng.normal(0, 0.0004, n))
        sector_returns = list(0.0005 + rng.normal(0, 0.0003, n))

        stock_prices = build_price_series(stock_returns)
        sector_prices = build_price_series(sector_returns)

        with self._mock_symbol("NVDA", stock_prices, sector_prices):
            sector_model.train_symbol("NVDA")
            adjustment = sector_model.predict_drift_adjustment("NVDA")

        self.assertLess(abs(adjustment), 0.05)

    def test_cap_is_enforced_even_for_extreme_momentum(self):
        rng = np.random.default_rng(7)
        n = 900
        stock_returns = list(rng.normal(0, 0.01, n))
        sector_returns = list(rng.normal(0, 0.01, n))
        # Make the tail momentum extreme so the raw prediction would blow past the cap.
        for i in range(1, sector_model.MOMENTUM_WINDOW_DAYS + 1):
            stock_returns[-i] = 0.05
            sector_returns[-i] = 0.05

        stock_prices = build_price_series(stock_returns)
        sector_prices = build_price_series(sector_returns)

        with self._mock_symbol("NVDA", stock_prices, sector_prices):
            sector_model.train_symbol("NVDA")
            adjustment = sector_model.predict_drift_adjustment("NVDA")

        self.assertLessEqual(abs(adjustment), sector_model.MAX_ANNUALIZED_ADJUSTMENT + 1e-9)

    def test_returns_zero_when_no_trained_model_exists(self):
        with patch.object(sector_model.os.path, "exists", return_value=False):
            self.assertEqual(sector_model.predict_drift_adjustment("NVDA"), 0.0)


if __name__ == "__main__":
    unittest.main()
