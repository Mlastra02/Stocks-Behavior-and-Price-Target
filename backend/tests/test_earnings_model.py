"""Tests for earnings_model.py's reaction-date logic, built on real report
dates/times from market_data.earnings_history() (Yahoo's get_earnings_dates),
and the forward-return/beat-miss bookkeeping on top of it. Network calls are
mocked — deterministic, synthetic data only.

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
    def _analyze_with(self, prices, records):
        with patch.object(
            earnings_model.market_data, "get_price_history", return_value=pd.DataFrame({"adj_close": prices})
        ), patch.object(earnings_model.market_data, "earnings_history", return_value=records):
            return earnings_model.analyze("TEST")

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

        self.assertAlmostEqual(reaction.reaction_day_return, expected_1d, places=9)
        self.assertAlmostEqual(reaction.forward_returns["1d"], expected_1d, places=9)
        self.assertAlmostEqual(reaction.forward_returns["1w"], expected_1w, places=9)
        self.assertAlmostEqual(reaction.forward_returns["1m"], expected_1m, places=9)

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


if __name__ == "__main__":
    unittest.main()
