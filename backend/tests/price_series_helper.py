"""Helper to build synthetic price series for deterministic model tests."""
import numpy as np
import pandas as pd


def build_price_series(daily_returns, base_price: float = 100.0, start: str = "2018-01-01") -> pd.DataFrame:
    """A price DataFrame (adj_close column) from a list of daily log returns.

    daily_returns[0] is the return from the base_price to the first row.
    """
    dates = pd.bdate_range(start=start, periods=len(daily_returns))
    log_prices = np.log(base_price) + np.cumsum(daily_returns)
    prices = np.exp(log_prices)
    return pd.DataFrame({"adj_close": prices}, index=dates)
