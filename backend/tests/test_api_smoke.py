"""End-to-end smoke test for /api/probability, with Alpha Vantage mocked out.

Runs without network access or API quota, so it stays usable even when the
free Alpha Vantage daily limit (25 req/day) is exhausted.
Run from backend/: venv/Scripts/python -m unittest tests.test_api_smoke
"""
import sys
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv()

from app.main import app
from app.pricing import technical_indicators as ti


class ProbabilityEndpointSmokeTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_health(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)

    def test_stocks_list_includes_tracked_universe(self):
        resp = self.client.get("/api/stocks")
        symbols = {s["symbol"] for s in resp.get_json()}
        self.assertEqual(symbols, {"NVDA", "NOW", "MSFT", "DASH", "MELI", "LOAR"})

    @patch("app.main.market_data.latest_price", return_value=140.0)
    @patch("app.main.market_data.risk_free_rate", return_value=0.042)
    @patch("app.main.market_data.historical_volatility", return_value=0.45)
    @patch("app.main.market_data.implied_volatility", return_value=None)
    @patch("app.main.sector_model.predict_drift_adjustment", return_value=0.0)
    def test_probability_endpoint_shape(self, *_mocks):
        resp = self.client.get(
            "/api/probability", query_string={"symbol": "NVDA", "target_price": 250, "horizon_months": 12}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()

        self.assertEqual(data["symbol"], "NVDA")
        self.assertAlmostEqual(data["current_price"], 140.0)
        self.assertIn("black_scholes", data)
        self.assertIn("monte_carlo", data)
        self.assertGreaterEqual(data["black_scholes"]["probability"], 0.0)
        self.assertLessEqual(data["black_scholes"]["probability"], 1.0)
        self.assertGreaterEqual(data["monte_carlo"]["probability"], 0.0)
        self.assertLessEqual(data["monte_carlo"]["probability"], 1.0)

    def test_probability_endpoint_rejects_unknown_symbol(self):
        resp = self.client.get(
            "/api/probability", query_string={"symbol": "FAKE", "target_price": 100, "horizon_months": 6}
        )
        self.assertEqual(resp.status_code, 400)


class TechnicalAnalysisEndpointSmokeTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    @patch("app.main.technical_indicators.analyze")
    def test_technical_analysis_endpoint_shape(self, mock_analyze):
        mock_analyze.return_value = ti.TechnicalAnalysisResult(
            symbol="NVDA", as_of_date="2026-08-04", current_price=200.0, price_target=250.0, upside_pct=0.25,
            rsi=ti.BandedValue(value=55.0, band="moderado", explanation="rsi ok"),
            ema_short=ti.BandedValue(value=195.0, band="moderado", explanation="ema ok"),
            sma_medium=ti.BandedValue(value=190.0, band="moderado", explanation="sma ok"),
            cross_signal=ti.CrossSignal(state="bullish", sma50=190.0, sma200=180.0, gap_pct=0.05, explanation="cross ok"),
            volume_signal=ti.VolumeSignal(current_volume=1_000_000.0, volume_ratio=1.1, price_change_pct=0.02, quadrant=None, explanation="vol ok"),
            chart=[ti.ChartPoint(date="2026-08-04", price=200.0, sma50=190.0, sma200=180.0, ema20=195.0, rsi=55.0)],
            earnings_dates=["2026-07-15"],
        )
        resp = self.client.get("/api/technical-analysis", query_string={"symbol": "NVDA"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()

        self.assertEqual(data["symbol"], "NVDA")
        self.assertEqual(data["rsi"]["band"], "moderado")
        self.assertEqual(data["cross_signal"]["state"], "bullish")
        self.assertEqual(len(data["chart"]), 1)
        self.assertEqual(data["chart"][0]["rsi"], 55.0)
        self.assertEqual(data["earnings_dates"], ["2026-07-15"])

    def test_technical_analysis_rejects_unknown_symbol(self):
        resp = self.client.get("/api/technical-analysis", query_string={"symbol": "FAKE"})
        self.assertEqual(resp.status_code, 400)


class PortfolioEndpointSmokeTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.tmp_dir = tempfile.mkdtemp()
        self.tmp_path = os.path.join(self.tmp_dir, "portfolio.json")
        self._patchers = [
            patch("app.main.portfolio_store.STORAGE_DIR", self.tmp_dir),
            patch("app.main.portfolio_store.PORTFOLIO_PATH", self.tmp_path),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    @patch("app.main.market_data.daily_change_pct", return_value=0.01)
    @patch("app.main.market_data.latest_price", return_value=200.0)
    def test_upsert_then_get_reflects_holding(self, *_mocks):
        resp = self.client.put("/api/portfolio/holdings/NVDA", json={"quantity": 2, "avg_cost": 150.0})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data["holdings"]), 1)

        holding = data["holdings"][0]
        self.assertEqual(holding["symbol"], "NVDA")
        self.assertAlmostEqual(holding["current_value"], 400.0)
        self.assertAlmostEqual(holding["gain_pct"], 200.0 / 150.0 - 1)
        self.assertAlmostEqual(holding["allocation_pct"], 1.0)

        resp2 = self.client.get("/api/portfolio")
        self.assertEqual(len(resp2.get_json()["holdings"]), 1)

    def test_upsert_rejects_unknown_symbol(self):
        resp = self.client.put("/api/portfolio/holdings/FAKE", json={"quantity": 1, "avg_cost": 10})
        self.assertEqual(resp.status_code, 400)

    def test_upsert_rejects_missing_fields(self):
        resp = self.client.put("/api/portfolio/holdings/NVDA", json={"quantity": 1})
        self.assertEqual(resp.status_code, 400)

    @patch("app.main.market_data.daily_change_pct", return_value=0.01)
    @patch("app.main.market_data.latest_price", return_value=200.0)
    def test_delete_removes_holding(self, *_mocks):
        self.client.put("/api/portfolio/holdings/NVDA", json={"quantity": 2, "avg_cost": 150.0})
        resp = self.client.delete("/api/portfolio/holdings/NVDA")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["holdings"], [])


if __name__ == "__main__":
    unittest.main()
