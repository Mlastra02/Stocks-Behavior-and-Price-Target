"""Tests for earnings_model.py's reaction-date logic, built on real report
dates/times from market_data.earnings_history() (Yahoo's get_earnings_dates),
the forward-return/beat-miss bookkeeping, and the trend/volume/sector context
+ filters on top. Network calls are mocked — deterministic, synthetic data only.

Run from backend/: venv/Scripts/python -m unittest tests.test_earnings_model
"""
import sys
import os
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.pricing import earnings_model


def _build_dated_price_series(start, periods, base_price=100.0, seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start=start, periods=periods)
    returns = rng.normal(0, 0.0015, periods)
    log_prices = np.log(base_price) + np.cumsum(returns)
    return pd.Series(np.exp(log_prices), index=dates)


def _price_df(prices, base_volume=1_000_000.0, opens=None):
    return pd.DataFrame(
        {
            "open": opens if opens is not None else prices,
            "adj_close": prices,
            "volume": np.full(len(prices), base_volume),
        },
        index=prices.index,
    )


class ReactionDateTest(unittest.TestCase):
    def setUp(self):
        self.prices = _build_dated_price_series(start="2023-06-01", periods=300)

    def test_before_close_report_reacts_same_day(self):
        # A Wednesday, well within the series, reported in the morning (BMO).
        report_date = "2023-11-08"
        result = earnings_model._reaction_date(report_date, report_hour=7, price_index=self.prices.index)
        self.assertEqual(result, pd.Timestamp(report_date))

    def test_after_close_report_reacts_next_trading_day(self):
        report_date = "2023-11-08"  # a Wednesday
        result = earnings_model._reaction_date(report_date, report_hour=16, price_index=self.prices.index)
        self.assertEqual(result, pd.Timestamp("2023-11-09"))

    def test_after_close_report_on_friday_rolls_to_monday(self):
        report_date = "2023-11-10"  # a Friday
        result = earnings_model._reaction_date(report_date, report_hour=16, price_index=self.prices.index)
        self.assertEqual(result, pd.Timestamp("2023-11-13"))

    def test_report_predating_available_price_history_returns_none(self):
        # Price history here starts 2023-06-01; a report from a year earlier
        # has no real reaction available, and must not silently snap to the
        # series' first day as if that were the reaction.
        result = earnings_model._reaction_date("2022-01-15", report_hour=16, price_index=self.prices.index)
        self.assertIsNone(result)

    def test_report_far_past_available_price_history_returns_none(self):
        result = earnings_model._reaction_date("2030-01-15", report_hour=16, price_index=self.prices.index)
        self.assertIsNone(result)


class AnalyzeTest(unittest.TestCase):
    def _analyze_with(self, prices, records, **kwargs):
        with patch.object(
            earnings_model.market_data, "get_price_history", return_value=_price_df(prices)
        ), patch.object(earnings_model.market_data, "earnings_history", return_value=records):
            return earnings_model.analyze("TEST", **kwargs)

    def test_forward_returns_measured_from_close_before_reaction(self):
        prices = _build_dated_price_series(start="2023-06-01", periods=300)
        records = [{"report_date": "2023-11-08", "report_hour": 16, "eps_actual": 1.1, "eps_estimate": 1.0, "surprise_pct": 0.10}]

        result = self._analyze_with(prices, records)

        self.assertEqual(len(result.reactions), 1)
        reaction = result.reactions[0]
        self.assertEqual(reaction.reaction_date, "2023-11-09")

        pos = list(prices.index).index(pd.Timestamp("2023-11-09"))
        prev_close = prices.iloc[pos - 1]
        expected_1d = prices.iloc[pos] / prev_close - 1
        expected_1w = prices.iloc[pos - 1 + 5] / prev_close - 1
        expected_1m = prices.iloc[pos - 1 + 20] / prev_close - 1

        expected_2w = prices.iloc[pos - 1 + 10] / prev_close - 1
        expected_3m = prices.iloc[pos - 1 + 60] / prev_close - 1

        self.assertAlmostEqual(reaction.reaction_day_return, expected_1d, places=9)
        self.assertAlmostEqual(reaction.forward_returns["1d"], expected_1d, places=9)
        self.assertAlmostEqual(reaction.forward_returns["1w"], expected_1w, places=9)
        self.assertAlmostEqual(reaction.forward_returns["2w"], expected_2w, places=9)
        self.assertAlmostEqual(reaction.forward_returns["1m"], expected_1m, places=9)
        self.assertAlmostEqual(reaction.forward_returns["3m"], expected_3m, places=9)

    def test_aftermarket_gap_measures_open_vs_close_before_reaction(self):
        prices = _build_dated_price_series(start="2023-06-01", periods=300)
        # Opens track the prior close plus a fixed +2% overnight gap, so the
        # reaction day's open is predictable regardless of that day's own close.
        opens = prices.shift(1) * 1.02
        opens.iloc[0] = prices.iloc[0]
        records = [{"report_date": "2023-11-08", "report_hour": 16, "eps_actual": 1.1, "eps_estimate": 1.0, "surprise_pct": 0.10}]

        with patch.object(
            earnings_model.market_data, "get_price_history", return_value=_price_df(prices, opens=opens)
        ), patch.object(earnings_model.market_data, "earnings_history", return_value=records):
            result = earnings_model.analyze("TEST")

        reaction = result.reactions[0]
        pos = list(prices.index).index(pd.Timestamp(reaction.reaction_date))
        prev_close = prices.iloc[pos - 1]

        self.assertAlmostEqual(reaction.next_open_price, opens.iloc[pos], places=9)
        self.assertAlmostEqual(reaction.aftermarket_gap_pct, opens.iloc[pos] / prev_close - 1, places=9)
        self.assertAlmostEqual(reaction.aftermarket_gap_pct, 0.02, places=9)

    def test_beats_and_misses_counted_from_surprise_sign(self):
        prices = _build_dated_price_series(start="2023-06-01", periods=300)
        records = [
            {"report_date": "2023-11-08", "report_hour": 16, "eps_actual": 1.1, "eps_estimate": 1.0, "surprise_pct": 0.10},
            {"report_date": "2023-08-08", "report_hour": 16, "eps_actual": 0.9, "eps_estimate": 1.0, "surprise_pct": -0.10},
            {"report_date": "2023-06-08", "report_hour": 16, "eps_actual": 1.0, "eps_estimate": 1.0, "surprise_pct": 0.0},
        ]

        result = self._analyze_with(prices, records)

        self.assertEqual(result.n_beats, 1)
        self.assertEqual(result.n_misses, 1)

    def test_price_window_spans_roughly_three_months_each_side(self):
        prices = _build_dated_price_series(start="2023-06-01", periods=300)
        records = [{"report_date": "2023-11-08", "report_hour": 16, "eps_actual": 1.1, "eps_estimate": 1.0, "surprise_pct": 0.10}]

        result = self._analyze_with(prices, records)
        window = result.reactions[0].price_window
        reaction_date = pd.Timestamp("2023-11-09")

        self.assertGreater(len(window), 0)
        first_date = pd.Timestamp(window[0]["date"])
        last_date = pd.Timestamp(window[-1]["date"])
        self.assertGreaterEqual(first_date, reaction_date - pd.DateOffset(months=3) - pd.Timedelta(days=3))
        self.assertLessEqual(last_date, reaction_date + pd.DateOffset(months=3) + pd.Timedelta(days=3))

    def test_report_outside_price_history_yields_empty_reaction(self):
        prices = _build_dated_price_series(start="2023-06-01", periods=300)
        records = [{"report_date": "2020-01-01", "report_hour": 16, "eps_actual": 1.0, "eps_estimate": 1.0, "surprise_pct": 0.0}]

        result = self._analyze_with(prices, records)

        self.assertEqual(len(result.reactions), 1)
        reaction = result.reactions[0]
        self.assertIsNone(reaction.reaction_date)
        self.assertIsNone(reaction.reaction_day_return)
        self.assertEqual(reaction.forward_returns, {})
        self.assertEqual(reaction.price_window, [])


class TrendAndVolumeTest(unittest.TestCase):
    def _analyze_with(self, prices, records, **kwargs):
        with patch.object(
            earnings_model.market_data, "get_price_history", return_value=_price_df(prices)
        ), patch.object(earnings_model.market_data, "earnings_history", return_value=records):
            return earnings_model.analyze("TEST", **kwargs)

    def test_trend_before_reflects_trailing_month_direction(self):
        # Flat, then a clean rally into the report date.
        n = 300
        rng = np.random.default_rng(1)
        returns = rng.normal(0, 0.0005, n)
        dates = pd.bdate_range(start="2023-06-01", periods=n)
        report_pos = 250
        returns[report_pos - 25: report_pos] = 0.01  # steady climb the month before
        log_prices = np.log(100.0) + np.cumsum(returns)
        prices = pd.Series(np.exp(log_prices), index=dates)

        report_date = dates[report_pos].strftime("%Y-%m-%d")
        records = [{"report_date": report_date, "report_hour": 7, "eps_actual": 1.0, "eps_estimate": 1.0, "surprise_pct": 0.0}]

        result = self._analyze_with(prices, records)
        self.assertGreater(result.reactions[0].trend_before_pct, 0.05)

    def test_require_uptrend_before_filters_by_sign(self):
        n = 300
        rng = np.random.default_rng(2)
        returns = rng.normal(0, 0.0005, n)
        dates = pd.bdate_range(start="2023-06-01", periods=n)

        up_pos, down_pos = 150, 250
        returns[up_pos - 25: up_pos] = 0.01
        returns[down_pos - 25: down_pos] = -0.01
        log_prices = np.log(100.0) + np.cumsum(returns)
        prices = pd.Series(np.exp(log_prices), index=dates)

        records = [
            {"report_date": dates[up_pos].strftime("%Y-%m-%d"), "report_hour": 7, "eps_actual": 1.0, "eps_estimate": 1.0, "surprise_pct": 0.0},
            {"report_date": dates[down_pos].strftime("%Y-%m-%d"), "report_hour": 7, "eps_actual": 1.0, "eps_estimate": 1.0, "surprise_pct": 0.0},
        ]

        uptrend_only = self._analyze_with(prices, records, require_uptrend_before=True)
        self.assertTrue(all(r.trend_before_pct > 0 for r in uptrend_only.reactions))

        downtrend_only = self._analyze_with(prices, records, require_uptrend_before=False)
        self.assertTrue(all(r.trend_before_pct < 0 for r in downtrend_only.reactions))

    def test_volume_ratio_flags_anomalous_reaction_day(self):
        prices = _build_dated_price_series(start="2023-06-01", periods=300)
        report_date = "2023-11-08"
        records = [{"report_date": report_date, "report_hour": 16, "eps_actual": 1.0, "eps_estimate": 1.0, "surprise_pct": 0.0}]

        df = _price_df(prices)
        reaction_pos = list(prices.index).index(pd.Timestamp("2023-11-09"))
        df.iloc[reaction_pos, df.columns.get_loc("volume")] = 10_000_000.0

        with patch.object(earnings_model.market_data, "get_price_history", return_value=df), patch.object(
            earnings_model.market_data, "earnings_history", return_value=records
        ):
            result = earnings_model.analyze("TEST")

        self.assertGreater(result.reactions[0].volume_ratio, 5.0)

class AggregateStatsTest(unittest.TestCase):
    def _analyze_with(self, prices, records, **kwargs):
        with patch.object(
            earnings_model.market_data, "get_price_history", return_value=_price_df(prices)
        ), patch.object(earnings_model.market_data, "earnings_history", return_value=records):
            return earnings_model.analyze("TEST", **kwargs)

    def test_beat_and_miss_stats_split_reaction_averages(self):
        prices = _build_dated_price_series(start="2018-01-01", periods=1500)
        dates = prices.index
        records = [
            {"report_date": dates[300].strftime("%Y-%m-%d"), "report_hour": 16, "eps_actual": 1.1, "eps_estimate": 1.0, "surprise_pct": 0.10},
            {"report_date": dates[600].strftime("%Y-%m-%d"), "report_hour": 16, "eps_actual": 1.2, "eps_estimate": 1.0, "surprise_pct": 0.20},
            {"report_date": dates[900].strftime("%Y-%m-%d"), "report_hour": 16, "eps_actual": 0.8, "eps_estimate": 1.0, "surprise_pct": -0.20},
        ]

        result = self._analyze_with(prices, records)

        self.assertEqual(result.beat_stats.n, 2)
        self.assertEqual(result.miss_stats.n, 1)
        self.assertIsNotNone(result.beat_stats.mean_reaction)
        self.assertIsNotNone(result.miss_stats.mean_reaction)

    def test_correlation_is_none_below_minimum_pairs(self):
        prices = _build_dated_price_series(start="2023-06-01", periods=300)
        records = [{"report_date": "2023-11-08", "report_hour": 16, "eps_actual": 1.1, "eps_estimate": 1.0, "surprise_pct": 0.10}]

        result = self._analyze_with(prices, records)
        self.assertIsNone(result.surprise_reaction_correlation)

    def test_correlation_computed_with_enough_pairs(self):
        prices = _build_dated_price_series(start="2018-01-01", periods=1800)
        dates = prices.index
        positions = [200, 400, 600, 800, 1000, 1200]
        records = [
            {
                "report_date": dates[p].strftime("%Y-%m-%d"),
                "report_hour": 16,
                "eps_actual": 1.0,
                "eps_estimate": 1.0,
                "surprise_pct": (-0.15 + 0.05 * i),
            }
            for i, p in enumerate(positions)
        ]

        result = self._analyze_with(prices, records)
        self.assertIsNotNone(result.surprise_reaction_correlation)
        self.assertGreaterEqual(result.surprise_reaction_correlation, -1.0)
        self.assertLessEqual(result.surprise_reaction_correlation, 1.0)


class SectorComparisonTest(unittest.TestCase):
    def test_excess_reaction_is_stock_minus_sector(self):
        stock_prices = _build_dated_price_series(start="2020-06-01", periods=400, seed=3)
        sector_prices = _build_dated_price_series(start="2020-06-01", periods=400, seed=4, base_price=50.0)

        report_pos = 300
        report_date = stock_prices.index[report_pos].strftime("%Y-%m-%d")
        records = [{"report_date": report_date, "report_hour": 7, "eps_actual": 1.0, "eps_estimate": 1.0, "surprise_pct": 0.0}]

        def fake_history(symbol):
            return _price_df(stock_prices) if symbol == "NVDA" else _price_df(sector_prices)

        with patch.object(earnings_model.market_data, "get_price_history", side_effect=fake_history), patch.object(
            earnings_model.market_data, "earnings_history", return_value=records
        ):
            result = earnings_model.analyze("NVDA")  # a real TRACKED_STOCKS symbol, so sector_etf resolves

        reaction = result.reactions[0]
        self.assertIsNotNone(reaction.sector_reaction_day_return)
        self.assertAlmostEqual(
            reaction.excess_reaction_day_return,
            reaction.reaction_day_return - reaction.sector_reaction_day_return,
            places=9,
        )


if __name__ == "__main__":
    unittest.main()
