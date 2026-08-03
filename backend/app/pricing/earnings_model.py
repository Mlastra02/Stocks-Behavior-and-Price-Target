"""Earnings-reaction event study.

A third, narrower lens than momentum_model.py: instead of matching arbitrary
price moves, this anchors on real, identifiable earnings report events and
looks at how the stock actually moved afterward, alongside the EPS surprise
(beat/miss) that (probably) caused it.

market_data.earnings_history() gives the real report date and hour (Yahoo's
get_earnings_dates endpoint), not just the fiscal quarter it covers, so the
reaction date only needs a small adjustment, not the wide-window "biggest
move" inference this module used before that endpoint became reliable here:
reports at/after AFTER_MARKET_CLOSE_HOUR (market close, in the exchange's
local time) move the market on the NEXT trading session, not the report's
own calendar day.

Depth varies a lot across the tracked universe — established large caps go
back ~12 years, but DASH (2020 IPO) and LOAR (2024 IPO) are much shorter —
and reactions can only be computed for quarters that fall within this
stock's fetched price history (see market_data_client.TRACKED_STOCKS'
history_since), so the usable sample can still end up small for newer names.
"""
from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

from app.data import market_data_client as market_data

AFTER_MARKET_CLOSE_HOUR = 12  # reports at/after this hour react the next session
# If the nearest available price is more than this many days after the
# target reaction date, there's a real gap (the report predates this stock's
# fetched price history) rather than a normal weekend/holiday roll-forward —
# treat it as no data, not a misleadingly distant "reaction".
MAX_REACTION_SEARCH_GAP_DAYS = 7
FORWARD_HORIZONS_DAYS = {"1d": 1, "1w": 5, "1m": 20}
CHART_WINDOW_MONTHS_BEFORE = 3
CHART_WINDOW_MONTHS_AFTER = 3


@dataclass
class EarningsReaction:
    report_date: str
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


def _reaction_date(report_date: str, report_hour: int, price_index: pd.DatetimeIndex) -> Optional[pd.Timestamp]:
    """The first trading day the market could react on: the report's own day
    for a before-close report, the next trading day for an at/after-close one."""
    target = pd.Timestamp(report_date)
    if report_hour >= AFTER_MARKET_CLOSE_HOUR:
        target = target + pd.Timedelta(days=1)

    candidates = price_index[price_index >= target]
    if candidates.empty:
        return None
    reaction = candidates[0]
    if (reaction - target).days > MAX_REACTION_SEARCH_GAP_DAYS:
        return None
    return reaction


def _price_window(prices, center_date):
    start = center_date - pd.DateOffset(months=CHART_WINDOW_MONTHS_BEFORE)
    end = center_date + pd.DateOffset(months=CHART_WINDOW_MONTHS_AFTER)
    window = prices[(prices.index >= start) & (prices.index <= end)]
    return [{"date": ts.strftime("%Y-%m-%d"), "price": float(p)} for ts, p in window.items()]


def analyze(symbol: str) -> EarningsAnalysisResult:
    records = market_data.earnings_history(symbol)
    prices = market_data.get_price_history(symbol)["adj_close"]
    price_index = prices.index
    price_index_list = list(price_index)

    reactions: List[EarningsReaction] = []
    for record in records:
        reaction_date = _reaction_date(record["report_date"], record["report_hour"], price_index)

        if reaction_date is None:
            reactions.append(
                EarningsReaction(
                    report_date=record["report_date"],
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

        pos = price_index_list.index(reaction_date)
        prev_close = float(prices.iloc[pos - 1]) if pos > 0 else None
        reaction_day_return = float(prices.iloc[pos] / prev_close - 1) if prev_close else None

        forward_returns = {}
        for label, horizon in FORWARD_HORIZONS_DAYS.items():
            target_pos = pos - 1 + horizon  # measured from the close right before the reaction
            if pos > 0 and target_pos < len(price_index_list):
                forward_returns[label] = float(prices.iloc[target_pos] / prices.iloc[pos - 1] - 1)

        reactions.append(
            EarningsReaction(
                report_date=record["report_date"],
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
