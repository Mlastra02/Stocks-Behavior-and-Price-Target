"""Trend-based drift adjustment model.

Learns how a stock's own recent momentum and its sector ETF's momentum
together predict its excess return over the following ~3 months. At
prediction time this turns "this stock (and its sector) has been trending
up" into a small drift nudge that monte_carlo.simulate_touch_probability
adds on top of the risk-free drift.

Two bugs from earlier versions, both worth remembering:
1. Only using sector momentum meant a stock's own current trend (e.g. a
   post-earnings rally) had no direct effect — only how it historically
   co-moved with its sector did, which can point the wrong way. Own-stock
   momentum is now the primary signal; sector momentum is secondary.
2. The model predicted NEXT-DAY excess return and that got multiplied by 252
   to "annualize" it — implicitly assuming a one-day edge repeats identically
   every trading day for a year, which massively overstates any signal. The
   model now predicts the FORWARD ~3-month (MOMENTUM_WINDOW_DAYS) excess
   return directly, scaled to an annual rate by ~4x instead of ~252x.

Training is triggered manually (train_sector_model.py) for now; weekly
automatic retraining is a future enhancement, not wired in yet.
"""
import os
from dataclasses import dataclass
from typing import Dict

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from app.config.stocks import TRACKED_STOCKS
from app.data import market_data_client as market_data

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "models")
MOMENTUM_WINDOW_DAYS = 63  # ~3 trading months
MIN_TRAINING_OBSERVATIONS = 100
ANNUALIZATION_FACTOR = 252 / MOMENTUM_WINDOW_DAYS
# A plain linear regression can still extrapolate to unrealistic drift values
# during extreme momentum stretches; cap the annualized adjustment.
MAX_ANNUALIZED_ADJUSTMENT = 0.20
# ~2 years of history gives only a handful of independent MOMENTUM_WINDOW_DAYS
# episodes to learn from (~6), so the fitted coefficients are estimated with a
# lot of uncertainty. Shrink toward zero so a noisy/overconfident fit doesn't
# dominate the drift; calibrated so MAX_ANNUALIZED_ADJUSTMENT is a rare
# safety net rather than the typical outcome (see raw magnitudes measured
# across the tracked universe: roughly -0.68 to +0.37 pre-shrinkage).
SHRINKAGE_FACTOR = 0.3


@dataclass
class SectorModelBundle:
    model: LinearRegression
    trained_at: str
    n_observations: int


def _model_path(symbol: str) -> str:
    return os.path.join(MODEL_DIR, f"{symbol}_sector_model.joblib")


def _daily_log_returns(prices: pd.Series) -> pd.Series:
    return np.log(prices / prices.shift(1)).dropna()


def _rolling_momentum(returns: pd.Series, window: int) -> pd.Series:
    return returns.rolling(window).sum()


def _build_features(symbol: str, sector_etf: str) -> pd.DataFrame:
    stock_prices = market_data.get_price_history(symbol)["adj_close"]
    sector_prices = market_data.get_price_history(sector_etf)["adj_close"]

    stock_returns = _daily_log_returns(stock_prices)
    sector_returns = _daily_log_returns(sector_prices)

    df = pd.concat([stock_returns.rename("stock"), sector_returns.rename("sector")], axis=1).dropna()
    df["stock_momentum"] = _rolling_momentum(df["stock"], MOMENTUM_WINDOW_DAYS)
    df["sector_momentum"] = _rolling_momentum(df["sector"], MOMENTUM_WINDOW_DAYS)

    # Forward realized return over the next MOMENTUM_WINDOW_DAYS sessions (not
    # including today): a trailing rolling sum shifted back by the window
    # length lines each row up with the sum of the days *after* it.
    df["forward_return"] = df["stock"].rolling(MOMENTUM_WINDOW_DAYS).sum().shift(-MOMENTUM_WINDOW_DAYS)

    return df.dropna()


def train_symbol(symbol: str) -> SectorModelBundle:
    """Fit excess_forward_return ~ own_momentum + sector_momentum for one symbol.

    The target is demeaned (forward_return minus its own average) so the
    fitted intercept doesn't absorb the stock's baseline historical drift —
    that baseline would otherwise double-count on top of the risk-free rate
    at prediction time. The model only measures the incremental effect of
    momentum being unusually strong or weak right now.
    """
    if symbol not in TRACKED_STOCKS:
        raise ValueError(f"{symbol} no está en TRACKED_STOCKS")

    sector_etf = TRACKED_STOCKS[symbol]["sector_etf"]
    df = _build_features(symbol, sector_etf)

    if len(df) < MIN_TRAINING_OBSERVATIONS:
        raise ValueError(f"Historial insuficiente para entrenar el modelo de tendencia de {symbol}")

    X = df[["stock_momentum", "sector_momentum"]].values
    y = (df["forward_return"] - df["forward_return"].mean()).values

    model = LinearRegression()
    model.fit(X, y)

    bundle = SectorModelBundle(
        model=model,
        trained_at=pd.Timestamp.utcnow().isoformat(),
        n_observations=len(df),
    )

    os.makedirs(MODEL_DIR, exist_ok=True)
    joblib.dump(bundle, _model_path(symbol))
    return bundle


def predict_drift_adjustment(symbol: str) -> float:
    """Annualized drift adjustment implied by the stock's own current trend + its sector's.

    Returns 0.0 (no adjustment) if no trained model exists yet for this symbol.
    """
    path = _model_path(symbol)
    if not os.path.exists(path):
        return 0.0

    bundle: SectorModelBundle = joblib.load(path)
    sector_etf = TRACKED_STOCKS[symbol]["sector_etf"]

    stock_prices = market_data.get_price_history(symbol)["adj_close"]
    sector_prices = market_data.get_price_history(sector_etf)["adj_close"]

    stock_returns = _daily_log_returns(stock_prices)
    sector_returns = _daily_log_returns(sector_prices)

    current_stock_momentum = stock_returns.tail(MOMENTUM_WINDOW_DAYS).sum()
    current_sector_momentum = sector_returns.tail(MOMENTUM_WINDOW_DAYS).sum()

    predicted_forward_excess_return = float(
        bundle.model.predict([[current_stock_momentum, current_sector_momentum]])[0]
    )
    annualized = predicted_forward_excess_return * ANNUALIZATION_FACTOR * SHRINKAGE_FACTOR
    return max(-MAX_ANNUALIZED_ADJUSTMENT, min(MAX_ANNUALIZED_ADJUSTMENT, annualized))


def train_all() -> Dict[str, SectorModelBundle]:
    return {symbol: train_symbol(symbol) for symbol in TRACKED_STOCKS}
