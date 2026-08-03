"""Earnings-reaction event study.

A third, narrower lens than momentum_model.py: instead of matching arbitrary
price moves, this anchors on real, identifiable earnings report events and
looks at how the stock actually moved afterward, alongside the EPS surprise
(beat/miss) that (probably) caused it.

Yahoo's earnings-CALENDAR endpoint (yfinance's get_earnings_dates) is
unreliable in this environment — it times out under light load — so instead
this uses earnings_history (EPS actual/estimate/surprise per fiscal quarter,
a more reliable Yahoo endpoint) and INFERS the actual report date: within a
window of trading days after each quarter's end, the day with the largest
single-day price move is taken as the market's reaction to that report. This
is a heuristic, not the real calendar date, but earnings reactions are
usually the standout move in that window, so it tends to land on the right
day or the one next to it.

Only ~4 quarters are available per stock (Yahoo's free history depth for
this endpoint), so this is explicitly a small-sample, indicative-only view —
even more limited than momentum_model.py.
"""
from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

from app.data import market_data_client as market_data

REACTION_WINDOW_START_DAYS = 15  # earnings rarely land < ~3 weeks after quarter end
REACTION_WINDOW_END_DAYS = 50  # or later than ~7 weeks after
FORWARD_HORIZONS_DAYS = {"1d": 1, "1w": 5, "1m": 20}
CHART_WINDOW_MONTHS_BEFORE = 3
CHART_WINDOW_MONTHS_AFTER = 3


@dataclass
class EarningsReaction:
    quarter_end: str
    eps_actual: Optional[float]
    eps_estimate: Optional[float]
    surprise_pct: Optional[float]
    reaction_date: Optional[str]
    reaction_day_return: Optional[float]
    forward_returns: dict  # {"1d": ..., "1w": ..., "1m": ...}
    price_window: List[dict]  # [{"date": ..., "price": ...}, ...], ~3mo before to ~3mo after


@dataclass
class EarningsAnalysisResult:
    symbol: str
    reactions: List[EarningsReaction]
    n_beats: int
    n_misses: int
    pct_positive_reaction_day: Optional[float]


def _infer_reaction_date(prices, quarter_end_ts):
    window = prices[
        (prices.index >= quarter_end_ts + pd.Timedelta(days=REACTION_WINDOW_START_DAYS))
        & (prices.index <= quarter_end_ts + pd.Timedelta(days=REACTION_WINDOW_END_DAYS))
    ]
    if len(window) < 2:
        return None

    daily_returns = window / window.shift(1) - 1
    daily_returns = daily_returns.dropna()
    if daily_returns.empty:
        return None

    return daily_returns.abs().idxmax()


def _price_window(prices, center_date):
    start = center_date - pd.DateOffset(months=CHART_WINDOW_MONTHS_BEFORE)
    end = center_date + pd.DateOffset(months=CHART_WINDOW_MONTHS_AFTER)
    window = prices[(prices.index >= start) & (prices.index <= end)]
    return [{"date": ts.strftime("%Y-%m-%d"), "price": float(p)} for ts, p in window.items()]


def analyze(symbol: str) -> EarningsAnalysisResult:
    records = market_data.earnings_history(symbol)
    prices = market_data.get_price_history(symbol)["adj_close"]
    price_index = list(prices.index)

    reactions: List[EarningsReaction] = []
    for record in records:
        quarter_end_ts = pd.Timestamp(record["quarter_end"])
        reaction_date = _infer_reaction_date(prices, quarter_end_ts)

        if reaction_date is None:
            reactions.append(
                EarningsReaction(
                    quarter_end=record["quarter_end"],
                    eps_actual=record["eps_actual"],
                    eps_estimate=record["eps_estimate"],
                    surprise_pct=record["surprise_pct"],
                    reaction_date=None,
                    reaction_day_return=None,
                    forward_returns={},
                    price_window=[],
                )
            )
            continue

        pos = price_index.index(reaction_date)
        prev_close = float(prices.iloc[pos - 1]) if pos > 0 else None
        reaction_day_return = float(prices.iloc[pos] / prev_close - 1) if prev_close else None

        forward_returns = {}
        for label, horizon in FORWARD_HORIZONS_DAYS.items():
            target_pos = pos - 1 + horizon  # measured from the close right before the reaction
            if pos > 0 and target_pos < len(price_index):
                forward_returns[label] = float(prices.iloc[target_pos] / prices.iloc[pos - 1] - 1)

        reactions.append(
            EarningsReaction(
                quarter_end=record["quarter_end"],
                eps_actual=record["eps_actual"],
                eps_estimate=record["eps_estimate"],
                surprise_pct=record["surprise_pct"],
                reaction_date=reaction_date.strftime("%Y-%m-%d"),
                reaction_day_return=reaction_day_return,
                forward_returns=forward_returns,
                price_window=_price_window(prices, reaction_date),
            )
        )

    valid_reaction_days = [r.reaction_day_return for r in reactions if r.reaction_day_return is not None]
    pct_positive = (
        sum(1 for r in valid_reaction_days if r > 0) / len(valid_reaction_days) if valid_reaction_days else None
    )

    return EarningsAnalysisResult(
        symbol=symbol,
        reactions=reactions,
        n_beats=sum(1 for r in records if (r["surprise_pct"] or 0) > 0),
        n_misses=sum(1 for r in records if (r["surprise_pct"] or 0) < 0),
        pct_positive_reaction_day=pct_positive,
    )
