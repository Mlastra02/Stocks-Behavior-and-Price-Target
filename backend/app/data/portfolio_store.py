"""Manual portfolio holdings (quantity + average cost per symbol), persisted
to a JSON file on disk rather than a database — this is a single-user app
with no auth, so a shared file is enough, and it survives across browsers
and devices (the previous localStorage-only option wouldn't).
"""
import json
import os
import tempfile
from typing import Dict

STORAGE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "storage")
PORTFOLIO_PATH = os.path.join(STORAGE_DIR, "portfolio.json")


def _ensure_storage_dir() -> None:
    os.makedirs(STORAGE_DIR, exist_ok=True)


def load_holdings() -> Dict[str, dict]:
    """{"SYMBOL": {"quantity": float, "avg_cost": float}, ...} — {} if nothing saved yet."""
    if not os.path.exists(PORTFOLIO_PATH):
        return {}
    with open(PORTFOLIO_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("holdings", {})


def _save_holdings(holdings: Dict[str, dict]) -> None:
    _ensure_storage_dir()
    # Write to a temp file then rename, so a crash mid-write can't corrupt
    # the existing file (the only copy of this data — there's no database).
    fd, tmp_path = tempfile.mkstemp(dir=STORAGE_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"holdings": holdings}, f, indent=2)
        os.replace(tmp_path, PORTFOLIO_PATH)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def upsert_holding(symbol: str, quantity: float, avg_cost: float) -> Dict[str, dict]:
    if quantity <= 0:
        raise ValueError("quantity debe ser positiva")
    if avg_cost <= 0:
        raise ValueError("avg_cost debe ser positivo")

    holdings = load_holdings()
    holdings[symbol] = {"quantity": quantity, "avg_cost": avg_cost}
    _save_holdings(holdings)
    return holdings


def delete_holding(symbol: str) -> Dict[str, dict]:
    holdings = load_holdings()
    holdings.pop(symbol, None)
    _save_holdings(holdings)
    return holdings
