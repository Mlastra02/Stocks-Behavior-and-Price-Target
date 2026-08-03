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

import numpy as np
import pandas as pd

from app.config.stocks import TRACKED_STOCKS
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
DEFAULT_TREND_WINDOW_DAYS = 20  # ~1 trading month, trailing return right before the reaction
VALID_TREND_WINDOW_DAYS = {5, 10, 20, 60}  # ~1 week, ~2 weeks, ~1 month, ~3 months
VOLUME_BASELINE_DAYS = 60
MIN_PAIRS_FOR_CORRELATION = 5


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
    trend_before_pct: Optional[float]  # trailing ~1-month return going into the report
    volume_ratio: Optional[float]  # reaction-day volume / trailing 60-day average
    sector_reaction_day_return: Optional[float]
    excess_reaction_day_return: Optional[float]  # stock's reaction minus the sector's, same day


@dataclass
class BeatMissStats:
    n: int
    mean_reaction: Optional[float]
    median_reaction: Optional[float]


@dataclass
class EarningsAnalysisResult:
    symbol: str
    reactions: List[EarningsReaction]
    n_beats: int
    n_misses: int
    pct_positive_reaction_day: Optional[float]
    surprise_reaction_correlation: Optional[float]
    beat_stats: BeatMissStats
    miss_stats: BeatMissStats


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


def _trend_before(prices, pos: int, trend_window_days: int) -> Optional[float]:
    """Trailing return ending the trading day before the reaction, over trend_window_days."""
    ref_pos = pos - 1  # the close right before the reaction, same anchor as reaction_day_return
    start_pos = ref_pos - trend_window_days
    if ref_pos <= 0 or start_pos < 0:
        return None
    return float(prices.iloc[ref_pos] / prices.iloc[start_pos] - 1)


def _volume_ratio(volume, pos: int) -> Optional[float]:
    """Reaction-day volume over the trailing 60-day average (excluding the reaction itself)."""
    baseline_start = max(0, pos - 1 - VOLUME_BASELINE_DAYS)
    baseline = volume.iloc[baseline_start: pos - 1] if pos > 0 else volume.iloc[0:0]
    if len(baseline) < 10 or baseline.mean() <= 0:
        return None
    return float(volume.iloc[pos] / baseline.mean())


def _sector_reaction(sector_prices: pd.Series, reaction_date: pd.Timestamp) -> Optional[float]:
    sector_index = list(sector_prices.index)
    if reaction_date not in sector_prices.index:
        return None
    pos = sector_index.index(reaction_date)
    if pos == 0:
        return None
    return float(sector_prices.iloc[pos] / sector_prices.iloc[pos - 1] - 1)


def _beat_miss_stats(reactions: List[EarningsReaction], want_beat: bool) -> BeatMissStats:
    group = [
        r.reaction_day_return
        for r in reactions
        if r.surprise_pct is not None
        and r.reaction_day_return is not None
        and ((r.surprise_pct > 0) if want_beat else (r.surprise_pct < 0))
    ]
    if not group:
        return BeatMissStats(n=0, mean_reaction=None, median_reaction=None)
    arr = np.array(group)
    return BeatMissStats(n=len(arr), mean_reaction=float(arr.mean()), median_reaction=float(np.median(arr)))


def analyze(
    symbol: str,
    require_uptrend_before: Optional[bool] = None,
    require_beat: Optional[bool] = None,
    since_year: Optional[int] = None,
    trend_window_days: int = DEFAULT_TREND_WINDOW_DAYS,
) -> EarningsAnalysisResult:
    if trend_window_days not in VALID_TREND_WINDOW_DAYS:
        raise ValueError(f"trend_window_days debe ser uno de: {sorted(VALID_TREND_WINDOW_DAYS)}")

    records = market_data.earnings_history(symbol)

    if since_year is not None:
        records = [r for r in records if pd.Timestamp(r["report_date"]).year >= since_year]
    if require_beat is not None:
        records = [
            r for r in records if r["surprise_pct"] is not None and (r["surprise_pct"] > 0) == require_beat
        ]

    history = market_data.get_price_history(symbol)
    prices = history["adj_close"]
    volume = history["volume"]
    price_index = prices.index
    price_index_list = list(price_index)

    sector_etf = TRACKED_STOCKS.get(symbol, {}).get("sector_etf")
    sector_prices = market_data.get_price_history(sector_etf)["adj_close"] if sector_etf else None

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
                    trend_before_pct=None,
                    volume_ratio=None,
                    sector_reaction_day_return=None,
                    excess_reaction_day_return=None,
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

        sector_reaction = _sector_reaction(sector_prices, reaction_date) if sector_prices is not None else None
        excess_reaction = (
            reaction_day_return - sector_reaction
            if reaction_day_return is not None and sector_reaction is not None
            else None
        )

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
                trend_before_pct=_trend_before(prices, pos, trend_window_days),
                volume_ratio=_volume_ratio(volume, pos),
                sector_reaction_day_return=sector_reaction,
                excess_reaction_day_return=excess_reaction,
            )
        )

    if require_uptrend_before is not None:
        reactions = [
            r
            for r in reactions
            if r.trend_before_pct is not None and (r.trend_before_pct > 0) == require_uptrend_before
        ]

    valid_reaction_days = [r.reaction_day_return for r in reactions if r.reaction_day_return is not None]
    pct_positive = (
        sum(1 for r in valid_reaction_days if r > 0) / len(valid_reaction_days) if valid_reaction_days else None
    )

    surprise_reaction_pairs = [
        (r.surprise_pct, r.reaction_day_return)
        for r in reactions
        if r.surprise_pct is not None and r.reaction_day_return is not None
    ]
    correlation = None
    if len(surprise_reaction_pairs) >= MIN_PAIRS_FOR_CORRELATION:
        surprises = np.array([p[0] for p in surprise_reaction_pairs])
        moves = np.array([p[1] for p in surprise_reaction_pairs])
        if surprises.std() > 0 and moves.std() > 0:
            correlation = float(np.corrcoef(surprises, moves)[0, 1])

    return EarningsAnalysisResult(
        symbol=symbol,
        reactions=reactions,
        n_beats=sum(1 for r in reactions if (r.surprise_pct or 0) > 0),
        n_misses=sum(1 for r in reactions if (r.surprise_pct or 0) < 0),
        pct_positive_reaction_day=pct_positive,
        surprise_reaction_correlation=correlation,
        beat_stats=_beat_miss_stats(reactions, want_beat=True),
        miss_stats=_beat_miss_stats(reactions, want_beat=False),
    )
