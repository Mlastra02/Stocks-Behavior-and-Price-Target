"""Helper to build synthetic price series for deterministic model tests."""
import numpy as np
import pandas as pd


def build_price_series(
    daily_returns, base_price: float = 100.0, start: str = "2018-01-01", base_volume: float = 1_000_000.0
) -> pd.DataFrame:
    """A price DataFrame (adj_close + volume columns) from a list of daily log returns.

    daily_returns[0] is the return from the base_price to the first row.
    Volume is a flat baseline by default — tests that care about volume
    anomalies overwrite specific positions on the returned DataFrame.
    """
    dates = pd.bdate_range(start=start, periods=len(daily_returns))
    log_prices = np.log(base_price) + np.cumsum(daily_returns)
    prices = np.exp(log_prices)
    volume = np.full(len(daily_returns), base_volume)
    return pd.DataFrame({"adj_close": prices, "volume": volume}, index=dates)
