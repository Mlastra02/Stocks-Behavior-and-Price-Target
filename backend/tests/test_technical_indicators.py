"""Tests for technical_indicators.py: RSI/MA band thresholds, golden/death
cross detection (recent + "approaching", including the no-forced-call
paths), and the price-volume rule (including its inconclusive fallback).

Run from backend/: venv/Scripts/python -m unittest tests.test_technical_indicators
"""
import sys
import os
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.pricing import technical_indicators as ti


def _dates(periods, start="2023-01-01"):
    return pd.bdate_range(start=start, periods=periods)


class RsiTest(unittest.TestCase):
    def test_all_gains_pushes_rsi_to_100(self):
        prices = pd.Series(np.linspace(100, 200, 60), index=_dates(60))
        rsi = ti._rsi(prices)
        self.assertAlmostEqual(rsi.iloc[-1], 100.0, places=6)

    def test_all_losses_pushes_rsi_to_0(self):
        prices = pd.Series(np.linspace(200, 100, 60), index=_dates(60))
        rsi = ti._rsi(prices)
        self.assertAlmostEqual(rsi.iloc[-1], 0.0, places=6)

    def test_flat_prices_are_neutral(self):
        prices = pd.Series([100.0] * 60, index=_dates(60))
        rsi = ti._rsi(prices)
        self.assertAlmostEqual(rsi.iloc[-1], 50.0, places=6)

    def test_band_thresholds(self):
        self.assertEqual(ti._rsi_band(80).band, "alto")
        self.assertEqual(ti._rsi_band(50).band, "moderado")
        self.assertEqual(ti._rsi_band(20).band, "bajo")
        self.assertIsNone(ti._rsi_band(None).band)


class MaBandTest(unittest.TestCase):
    def test_price_well_above_ma_is_alto(self):
        result = ti._ma_band(current_price=110, ma_value=100, ma_label="la SMA(50)")
        self.assertEqual(result.band, "alto")

    def test_price_well_below_ma_is_bajo(self):
        result = ti._ma_band(current_price=90, ma_value=100, ma_label="la SMA(50)")
        self.assertEqual(result.band, "bajo")

    def test_price_near_ma_is_moderado(self):
        result = ti._ma_band(current_price=101, ma_value=100, ma_label="la SMA(50)")
        self.assertEqual(result.band, "moderado")

    def test_missing_ma_returns_none_band(self):
        result = ti._ma_band(current_price=100, ma_value=None, ma_label="la SMA(50)")
        self.assertIsNone(result.band)


class CrossSignalTest(unittest.TestCase):
    def test_detects_recent_golden_cross(self):
        n = 40
        sma200 = pd.Series([100.0] * n, index=_dates(n))
        # sma50 crosses from below to above sma200 five sessions ago.
        sma50 = pd.Series([98.0] * (n - 5) + [99, 100.5, 101, 102, 103], index=_dates(n))

        result = ti._cross_signal(sma50, sma200)
        self.assertEqual(result.state, "golden_recent")

    def test_detects_recent_death_cross(self):
        n = 40
        sma200 = pd.Series([100.0] * n, index=_dates(n))
        sma50 = pd.Series([102.0] * (n - 5) + [101, 99.5, 99, 98, 97], index=_dates(n))

        result = ti._cross_signal(sma50, sma200)
        self.assertEqual(result.state, "death_recent")

    def test_clean_convergence_flags_approaching_golden_cross(self):
        n = 30
        sma200 = pd.Series([100.0] * n, index=_dates(n))
        # sma50 starts well below and closes in smoothly, ending just under sma200 (still bearish, no cross yet).
        sma50 = pd.Series(np.linspace(94.0, 99.0, n), index=_dates(n))

        result = ti._cross_signal(sma50, sma200)
        self.assertEqual(result.state, "approaching_golden")

    def test_noisy_gap_does_not_force_an_approaching_call(self):
        n = 30
        sma200 = pd.Series([100.0] * n, index=_dates(n))
        rng = np.random.default_rng(0)
        # Close to sma200 but jittering with no consistent direction — should NOT claim "approaching".
        sma50 = pd.Series(99.0 + rng.normal(0, 0.6, n), index=_dates(n))

        result = ti._cross_signal(sma50, sma200)
        self.assertNotIn(result.state, ("approaching_golden", "approaching_death"))

    def test_far_apart_and_flat_reports_plain_alignment(self):
        n = 30
        sma200 = pd.Series([100.0] * n, index=_dates(n))
        sma50 = pd.Series([115.0] * n, index=_dates(n))

        result = ti._cross_signal(sma50, sma200)
        self.assertEqual(result.state, "bullish")


class VolumeSignalTest(unittest.TestCase):
    def _prices_and_volume(self, price_move_pct, recent_volume_ratio):
        n = 90
        dates = _dates(n)
        baseline = np.full(n - ti.VOLUME_SIGNAL_PRICE_WINDOW_DAYS, 1_000_000.0)
        recent = np.full(ti.VOLUME_SIGNAL_PRICE_WINDOW_DAYS, 1_000_000.0 * recent_volume_ratio)
        volume = pd.Series(np.concatenate([baseline, recent]), index=dates)

        prices = pd.Series([100.0] * (n - ti.VOLUME_SIGNAL_PRICE_WINDOW_DAYS), index=dates[: n - ti.VOLUME_SIGNAL_PRICE_WINDOW_DAYS])
        end_price = 100.0 * (1 + price_move_pct)
        tail = pd.Series(
            np.linspace(100.0, end_price, ti.VOLUME_SIGNAL_PRICE_WINDOW_DAYS),
            index=dates[n - ti.VOLUME_SIGNAL_PRICE_WINDOW_DAYS:],
        )
        prices = pd.concat([prices, tail])
        return prices, volume

    def test_price_up_volume_up_is_bullish_confirmation(self):
        prices, volume = self._prices_and_volume(price_move_pct=0.08, recent_volume_ratio=1.8)
        result = ti._volume_signal(prices, volume)
        self.assertEqual(result.quadrant, "confirmacion_alcista")

    def test_price_down_volume_up_is_bearish_confirmation(self):
        prices, volume = self._prices_and_volume(price_move_pct=-0.08, recent_volume_ratio=1.8)
        result = ti._volume_signal(prices, volume)
        self.assertEqual(result.quadrant, "confirmacion_bajista")

    def test_price_up_volume_down_is_bullish_warning(self):
        prices, volume = self._prices_and_volume(price_move_pct=0.08, recent_volume_ratio=0.5)
        result = ti._volume_signal(prices, volume)
        self.assertEqual(result.quadrant, "advertencia_alcista")

    def test_weak_move_does_not_force_a_quadrant(self):
        # Price barely moves and volume barely deviates — below both floors.
        prices, volume = self._prices_and_volume(price_move_pct=0.005, recent_volume_ratio=1.02)
        result = ti._volume_signal(prices, volume)
        self.assertIsNone(result.quadrant)
        self.assertIn("Sin señal clara", result.explanation)


class AnalyzeTest(unittest.TestCase):
    def _analyze_with(self, prices, volume, records, **kwargs):
        history = pd.DataFrame({"adj_close": prices, "volume": volume}, index=prices.index)
        with patch.object(ti.market_data, "get_price_history", return_value=history), patch.object(
            ti.market_data, "analyst_price_target", return_value=150.0
        ), patch.object(ti.market_data, "earnings_history", return_value=records):
            return ti.analyze("TEST", **kwargs)

    def test_analyze_returns_consistent_current_price_and_chart(self):
        n = 600
        rng = np.random.default_rng(7)
        returns = rng.normal(0.0003, 0.015, n)
        dates = _dates(n, start="2023-01-01")
        prices = pd.Series(100.0 * np.cumprod(1 + returns), index=dates)
        volume = pd.Series(np.full(n, 2_000_000.0), index=dates)

        result = self._analyze_with(prices, volume, records=[], chart_months=6)

        self.assertAlmostEqual(result.current_price, float(prices.iloc[-1]), places=9)
        self.assertEqual(result.as_of_date, dates[-1].strftime("%Y-%m-%d"))
        self.assertAlmostEqual(result.upside_pct, 150.0 / result.current_price - 1, places=9)
        self.assertGreater(len(result.chart), 0)
        self.assertLessEqual(len(result.chart), 135)  # ~6 months of trading days, generous upper bound
        self.assertEqual(result.chart[-1].date, dates[-1].strftime("%Y-%m-%d"))
        # Every chart point should carry its own RSI/EMA20 alongside price, for the click-to-inspect chart.
        self.assertTrue(any(p.rsi is not None for p in result.chart))
        self.assertTrue(any(p.ema20 is not None for p in result.chart))
        # 600 trading days is well past the SMA200 warm-up, so it should be banded like sma_medium/ema_short.
        self.assertIsNotNone(result.sma_long.value)
        self.assertIn(result.sma_long.band, ("alto", "moderado", "bajo"))

    def test_earnings_dates_within_chart_window_are_included_and_outside_ones_are_not(self):
        n = 600
        rng = np.random.default_rng(9)
        returns = rng.normal(0.0003, 0.015, n)
        dates = _dates(n, start="2023-01-01")
        prices = pd.Series(100.0 * np.cumprod(1 + returns), index=dates)
        volume = pd.Series(np.full(n, 2_000_000.0), index=dates)

        inside_date = dates[-30].strftime("%Y-%m-%d")  # well within a 6-month chart window
        outside_date = dates[0].strftime("%Y-%m-%d")  # way before the chart window starts
        records = [
            {"report_date": inside_date, "report_hour": 7, "eps_actual": 1.0, "eps_estimate": 1.0, "surprise_pct": 0.0},
            {"report_date": outside_date, "report_hour": 7, "eps_actual": 1.0, "eps_estimate": 1.0, "surprise_pct": 0.0},
        ]

        result = self._analyze_with(prices, volume, records=records, chart_months=6)

        self.assertIn(inside_date, result.earnings_dates)
        self.assertNotIn(outside_date, result.earnings_dates)


if __name__ == "__main__":
    unittest.main()
