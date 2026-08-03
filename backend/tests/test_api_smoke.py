"""End-to-end smoke test for /api/probability, with Alpha Vantage mocked out.

Runs without network access or API quota, so it stays usable even when the
free Alpha Vantage daily limit (25 req/day) is exhausted.
Run from backend/: venv/Scripts/python -m unittest tests.test_api_smoke
"""
import sys
import os
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv()

from app.main import app


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


if __name__ == "__main__":
    unittest.main()
