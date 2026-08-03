"""Manual trigger to (re)train the sector-trend adjustment model for all tracked stocks.

Run from backend/: venv/Scripts/python scripts/train_sector_model.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv()

from app.pricing import sector_model

if __name__ == "__main__":
    results = sector_model.train_all()
    for symbol, bundle in results.items():
        print(f"{symbol}: entrenado con {bundle.n_observations} observaciones ({bundle.trained_at})")
