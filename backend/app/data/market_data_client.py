"""Market data client backed by yfinance (Yahoo Finance).

Unofficial but free with no daily request cap, unlike Alpha Vantage's free
tier. Gives full-length adjusted price history and real options-chain implied
volatility, which is what makes it usable for both Black-Scholes (implied
vol) and Monte Carlo (historical vol) without a paid plan.
"""
import math
import time
from typing import List, Optional

import numpy as np
import pandas as pd
import yfinance as yf

from app.config.stocks import TRACKED_STOCKS

# symbol/key -> (fetched_at_epoch, value)
_CACHE: dict = {}
PRICE_HISTORY_TTL_SECONDS = 15 * 60
RISK_FREE_RATE_TTL_SECONDS = 12 * 60 * 60
# Fixed calendar start for symbols with no explicit "history_since" in
# TRACKED_STOCKS (e.g. sector ETFs used for the trend model) — not a rolling
# window, so it only grows over time rather than drifting forward.
DEFAULT_HISTORY_SINCE = "2016-01-01"

TREASURY_10Y_SYMBOL = "^TNX"  # CBOE 10-Year Treasury Note Yield, quoted as yield * 1 (e.g. 4.5 = 4.5%)


class MarketDataError(RuntimeError):
    pass


def _cached(key: str, ttl_seconds: int, fetch_fn):
    cached = _CACHE.get(key)
    now = time.time()
    if cached is not None and (now - cached[0]) < ttl_seconds:
        return cached[1]
    value = fetch_fn()
    _CACHE[key] = (now, value)
    return value


def _history_start_date(symbol: str) -> str:
    return TRACKED_STOCKS.get(symbol, {}).get("history_since", DEFAULT_HISTORY_SINCE)


def get_price_history(symbol: str) -> pd.DataFrame:
    """Split/dividend-adjusted daily open/close + volume, most recent last. Cached per symbol.

    Fetched from a fixed start date (see TRACKED_STOCKS / DEFAULT_HISTORY_SINCE),
    not a rolling "last N years" window — the window grows as time passes
    instead of sliding forward and eventually losing the start of the
    relevant business regime for that company.
    """

    def _fetch():
        start = _history_start_date(symbol)
        history = yf.Ticker(symbol).history(start=start, interval="1d", auto_adjust=True)
        if history.empty:
            raise MarketDataError(f"No se recibió serie de precios para {symbol}")
        df = history[["Open", "Close", "Volume"]].rename(
            columns={"Open": "open", "Close": "adj_close", "Volume": "volume"}
        )
        df.index = pd.to_datetime(df.index).tz_localize(None)
        # yfinance sometimes returns a placeholder row for the most recent
        # session (volume present, open/close not yet finalized) — drop it
        # rather than let a NaN leak into prices, ratios, or JSON responses.
        df = df.dropna(subset=["adj_close", "open"])
        return df

    return _cached(f"price_history:{symbol}", PRICE_HISTORY_TTL_SECONDS, _fetch)


def historical_volatility(symbol: str, lookback_days: int = 252) -> float:
    """Annualized historical volatility from daily log returns."""
    prices = get_price_history(symbol)["adj_close"].tail(lookback_days + 1)
    if len(prices) < 20:
        raise MarketDataError(f"Datos insuficientes para calcular volatilidad histórica de {symbol}")

    log_returns = np.log(prices / prices.shift(1)).dropna()
    daily_std = log_returns.std()
    return float(daily_std * math.sqrt(252))


def latest_price(symbol: str) -> float:
    return float(get_price_history(symbol)["adj_close"].iloc[-1])


def daily_change_pct(symbol: str) -> Optional[float]:
    """Latest session's close-to-close change, as a decimal. None if not enough history."""
    prices = get_price_history(symbol)["adj_close"]
    if len(prices) < 2:
        return None
    return float(prices.iloc[-1] / prices.iloc[-2] - 1)


MIN_DAYS_TO_EXPIRATION = 20  # skip weekly/0DTE contracts, whose IV is noisy and liquidity-thin
MAX_PLAUSIBLE_IV = 3.0  # 300%; anything above this is almost certainly a stale/illiquid quote


def implied_volatility(symbol: str) -> Optional[float]:
    """Average at-the-money implied volatility from a liquid, not-too-near-dated options chain.

    Deliberately anchored to the CURRENT price, not a user-supplied target: a
    deep out-of-the-money strike (e.g. a $100 put on a $200 stock) has thin,
    unreliable quotes where implied volatility swings wildly, since it's the
    inversion of a Black-Scholes price that's extremely sensitive to noise
    out there. At-the-money contracts are the most liquid and representative
    of the market's actual volatility expectation for the underlying.

    Returns None if the symbol has no listed options, or no contracts pass the
    liquidity/sanity filters (e.g. some ETFs or thinly-traded names), so
    callers can fall back to historical volatility.
    """

    def _fetch():
        ticker = yf.Ticker(symbol)
        expirations = ticker.options
        if not expirations:
            return None

        today = pd.Timestamp.now().normalize()
        valid_expirations = [
            exp for exp in expirations if (pd.Timestamp(exp) - today).days >= MIN_DAYS_TO_EXPIRATION
        ]
        expiration = valid_expirations[0] if valid_expirations else expirations[-1]

        chain = ticker.option_chain(expiration)
        contracts = pd.concat([chain.calls, chain.puts], ignore_index=True)
        contracts = contracts.dropna(subset=["impliedVolatility"])
        contracts = contracts[
            (contracts["impliedVolatility"] > 0)
            & (contracts["impliedVolatility"] <= MAX_PLAUSIBLE_IV)
            & (contracts.get("volume", 0).fillna(0) + contracts.get("openInterest", 0).fillna(0) > 0)
        ]
        if contracts.empty:
            return None

        current_price = latest_price(symbol)
        contracts = contracts.copy()
        contracts["distance"] = (contracts["strike"] - current_price).abs()
        contracts = contracts.sort_values("distance").head(5)

        return float(contracts["impliedVolatility"].mean())

    return _cached(f"implied_vol:{symbol}", PRICE_HISTORY_TTL_SECONDS, _fetch)


RISK_FREE_RATE_SYMBOLS = {
    "3month": "^IRX",  # 13-week Treasury bill yield
    "10year": TREASURY_10Y_SYMBOL,
}


def risk_free_rate(maturity: str = "10year") -> float:
    """Current risk-free rate proxied by a US Treasury yield, as a decimal. Cached 12h.

    maturity: "3month" (13-week T-bill, ^IRX) or "10year" (^TNX, the default).
    """
    symbol = RISK_FREE_RATE_SYMBOLS.get(maturity)
    if symbol is None:
        raise ValueError(f"maturity debe ser uno de: {sorted(RISK_FREE_RATE_SYMBOLS)}")

    def _fetch():
        history = yf.Ticker(symbol).history(period="5d", interval="1d")
        if history.empty:
            raise MarketDataError(f"No se recibió el rendimiento del Tesoro ({maturity})")
        return float(history["Close"].iloc[-1]) / 100.0

    return _cached(f"risk_free_rate:{maturity}", RISK_FREE_RATE_TTL_SECONDS, _fetch)


ANALYST_TARGET_HORIZON_YEARS = 1.0  # Wall Street price targets are conventionally ~12-month forward


def analyst_price_target(symbol: str) -> Optional[float]:
    """Mean analyst price target (Yahoo Finance consensus), or None if no coverage exists."""

    def _fetch():
        target = yf.Ticker(symbol).info.get("targetMeanPrice")
        return float(target) if target else None

    return _cached(f"analyst_target:{symbol}", PRICE_HISTORY_TTL_SECONDS, _fetch)


def analyst_expected_drift(symbol: str) -> Optional[float]:
    """Annualized drift implied by the gap between the current price and the analyst
    consensus target, assuming the conventional ~12-month analyst horizon.

    Returns None if there's no analyst coverage for this symbol, so callers can
    fall back to the risk-neutral (risk-free rate) drift.
    """
    target = analyst_price_target(symbol)
    if target is None:
        return None

    current = latest_price(symbol)
    return math.log(target / current) / ANALYST_TARGET_HORIZON_YEARS


EARNINGS_HISTORY_TTL_SECONDS = 24 * 60 * 60  # changes only once a quarter
EARNINGS_HISTORY_RETRIES = 3
EARNINGS_HISTORY_RETRY_DELAY_SECONDS = 5
# How many rows to ask Yahoo for. This scraped table returns fewer than
# requested once a symbol runs out of history (e.g. a recent IPO), so asking
# for more than any tracked stock actually has is harmless — it just gets
# capped naturally per symbol.
EARNINGS_HISTORY_ROW_LIMIT = 40


def earnings_history(symbol: str) -> List[dict]:
    """Real earnings report dates with EPS actual/estimate/surprise, oldest
    first, going back as far as Yahoo has (~12 years for well-covered large
    caps; naturally shorter for recent IPOs). Cached 24h.

    Uses get_earnings_dates() rather than the older `.earnings_history`
    property this used to call: that one only ever returns the last 4
    quarters, while this one takes a `limit` and gives the actual report
    timestamp instead of just the fiscal quarter-end (no more need to infer
    the reaction date by scanning for the biggest move afterward). This
    specific Yahoo endpoint is noticeably flakier than the others this
    client uses — it can time out under light load — so this retries a few
    times before giving up.
    """

    def _fetch():
        last_error = None
        for attempt in range(EARNINGS_HISTORY_RETRIES):
            try:
                df = yf.Ticker(symbol).get_earnings_dates(limit=EARNINGS_HISTORY_ROW_LIMIT)
                break
            except Exception as exc:  # yfinance/curl_cffi raise assorted network/parsing errors here
                last_error = exc
                if attempt < EARNINGS_HISTORY_RETRIES - 1:
                    time.sleep(EARNINGS_HISTORY_RETRY_DELAY_SECONDS)
        else:
            raise MarketDataError(f"No se recibió historial de earnings para {symbol}: {last_error}")

        if df is None or df.empty:
            return []

        df = df.dropna(subset=["Reported EPS"])  # drop future/not-yet-reported rows

        records = []
        for report_date, row in df.iterrows():
            report_date = pd.Timestamp(report_date)
            records.append(
                {
                    "report_date": report_date.strftime("%Y-%m-%d"),
                    "report_hour": report_date.hour,
                    "eps_actual": float(row["Reported EPS"]) if pd.notna(row.get("Reported EPS")) else None,
                    "eps_estimate": float(row["EPS Estimate"]) if pd.notna(row.get("EPS Estimate")) else None,
                    "surprise_pct": float(row["Surprise(%)"]) / 100.0 if pd.notna(row.get("Surprise(%)")) else None,
                }
            )
        records.sort(key=lambda r: r["report_date"])
        return records

    return _cached(f"earnings_history:{symbol}", EARNINGS_HISTORY_TTL_SECONDS, _fetch)
