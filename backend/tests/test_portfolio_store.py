"""Tests for portfolio_store.py's file-backed persistence. Redirects the
module's storage path to a temp directory so tests never touch the real
storage/portfolio.json.

Run from backend/: venv/Scripts/python -m unittest tests.test_portfolio_store
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.data import portfolio_store


class PortfolioStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.tmp_path = os.path.join(self.tmp_dir, "portfolio.json")
        self._patchers = [
            patch.object(portfolio_store, "STORAGE_DIR", self.tmp_dir),
            patch.object(portfolio_store, "PORTFOLIO_PATH", self.tmp_path),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_load_holdings_returns_empty_dict_when_no_file_exists(self):
        self.assertEqual(portfolio_store.load_holdings(), {})

    def test_upsert_then_load_roundtrips(self):
        portfolio_store.upsert_holding("NVDA", quantity=3.2, avg_cost=121.5)
        holdings = portfolio_store.load_holdings()
        self.assertEqual(holdings["NVDA"], {"quantity": 3.2, "avg_cost": 121.5})

    def test_upsert_overwrites_existing_symbol(self):
        portfolio_store.upsert_holding("NVDA", quantity=3.2, avg_cost=121.5)
        portfolio_store.upsert_holding("NVDA", quantity=5.0, avg_cost=130.0)
        holdings = portfolio_store.load_holdings()
        self.assertEqual(holdings["NVDA"], {"quantity": 5.0, "avg_cost": 130.0})

    def test_upsert_rejects_non_positive_quantity_or_cost(self):
        with self.assertRaises(ValueError):
            portfolio_store.upsert_holding("NVDA", quantity=0, avg_cost=100)
        with self.assertRaises(ValueError):
            portfolio_store.upsert_holding("NVDA", quantity=1, avg_cost=-5)

    def test_delete_removes_symbol_and_is_a_no_op_if_absent(self):
        portfolio_store.upsert_holding("NVDA", quantity=3.2, avg_cost=121.5)
        portfolio_store.upsert_holding("DASH", quantity=10, avg_cost=200)

        holdings = portfolio_store.delete_holding("NVDA")
        self.assertNotIn("NVDA", holdings)
        self.assertIn("DASH", holdings)

        holdings_again = portfolio_store.delete_holding("NVDA")  # no error for a symbol that's already gone
        self.assertEqual(holdings_again, holdings)

    def test_multiple_symbols_coexist(self):
        portfolio_store.upsert_holding("NVDA", quantity=3.2, avg_cost=121.5)
        portfolio_store.upsert_holding("DASH", quantity=10, avg_cost=200)
        holdings = portfolio_store.load_holdings()
        self.assertEqual(set(holdings.keys()), {"NVDA", "DASH"})


if __name__ == "__main__":
    unittest.main()
