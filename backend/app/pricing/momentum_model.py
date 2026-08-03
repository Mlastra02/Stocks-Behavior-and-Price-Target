"""Post-move momentum event study.

Answers a different question than black_scholes/monte_carlo: not "what's the
probability of touching a price target", but "historically, after a move of
this size and direction in THIS stock, what tended to happen next?"

Deliberately not a regression (see sector_model.py's history of noisy,
sign-flipping coefficients from too few independent samples) — this is a
plain historical event study: find past episodes where the stock moved by a
similar amount, and look at what its forward return was after each one.

The lookback window is NOT fixed. Real rallies/selloffs don't always take
exactly 5, 10, or 20 sessions, so both the current move and historical
matches are found by scanning several candidate window lengths and picking
whichever is most statistically unusual for its length (return divided by
sqrt(window) — the natural scaling of a random walk's spread, so a 3-day
15% move and a 20-day 15% move are compared on equal footing rather than
just always preferring the longer window). Once a window is picked for a
given day, matching against OTHER days is still by raw return magnitude
(the actual % move), not the normalized score — the user cares about "moved
~28%", not about the statistical significance number.

Episodes are found non-overlapping (each match skips ahead past its own
window + forward-measurement period) so they're at least independent of
each other, though with ~2 years of history there are still very few of
them — every result reports its sample size and this stays explicitly a
small-sample, indicative-only tool.
"""
import math
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from app.data import market_data_client as market_data

CANDIDATE_WINDOWS = [3, 5, 8, 13, 20]  # trading days scanned to find "the current run"
FORWARD_WINDOWS_DAYS = [5, 10, 20]  # ~1 week, ~2 weeks, ~1 month
MATCH_THRESHOLD_FRACTION = 0.7  # historical move must be >= 70% as large, same direction
# A historical episode's own window must fall within [current/RATIO, current*RATIO]
# to count as comparable at all — a 3-day spike and a 20-day grind can reach the
# same %, but they're different kinds of moves. Applied before magnitude matching,
# including for the fallback pool.
WINDOW_PROXIMITY_RATIO = 2.0
MIN_EPISODES_FOR_CONFIDENCE = 5
FALLBACK_MAX_EPISODES = 5

# Context tags (not the actual "why", which needs a news source we don't
# have — these are the two proxies we can compute from data already on
# hand): did the episode coincide with a known earnings report, and was
# trading volume unusually high during it.
EARNINGS_COINCIDENCE_BUFFER_DAYS = 1  # an after-close report's reaction lands the next session
VOLUME_BASELINE_DAYS = 60
VOLUME_ANOMALY_MULTIPLIER = 1.5


@dataclass
class ForwardWindowStats:
    n: int
    pct_positive: Optional[float]
    mean_return: Optional[float]
    median_return: Optional[float]
    min_return: Optional[float]
    max_return: Optional[float]


@dataclass
class AnalystTargetContext:
    current_price: float
    target_price: Optional[float]
    upside_now_pct: Optional[float]
    upside_before_move_pct: Optional[float]
    already_above_target: bool


@dataclass
class MomentumAnalysisResult:
    symbol: str
    current_price: float
    detected_window_days: int
    current_move_pct: float
    current_coincided_with_earnings: bool
    current_volume_anomaly: bool
    current_volume_ratio: Optional[float]
    threshold_pct: float
    episodes_found: int
    episode_details: List[dict]  # [{"date": ..., "window_days": ..., "move_pct": ..., "coincided_with_earnings": ..., ...}]
    forward_windows: Dict[int, ForwardWindowStats]
    low_confidence: bool
    used_fallback: bool
    analyst_context: AnalystTargetContext


def _best_window_series(prices: pd.Series):
    """For each day, the (window, return) among CANDIDATE_WINDOWS with the highest
    |return| / sqrt(window) — the most statistically unusual move ending that day."""
    best_return = pd.Series(0.0, index=prices.index)
    best_window = pd.Series(CANDIDATE_WINDOWS[0], index=prices.index)
    best_score = pd.Series(-1.0, index=prices.index)

    for window in CANDIDATE_WINDOWS:
        ret = prices / prices.shift(window) - 1
        score = ret.abs() / math.sqrt(window)
        better = score > best_score
        best_return = best_return.where(~better, ret)
        best_window = best_window.where(~better, window)
        best_score = best_score.where(~better, score)

    return best_return, best_window


def _analyst_context(symbol: str, prices: pd.Series, current_window: int) -> AnalystTargetContext:
    current_price = float(prices.iloc[-1])
    target = market_data.analyst_price_target(symbol)

    if target is None:
        return AnalystTargetContext(
            current_price=current_price,
            target_price=None,
            upside_now_pct=None,
            upside_before_move_pct=None,
            already_above_target=False,
        )

    upside_now = target / current_price - 1

    pos_before = len(prices) - 1 - current_window
    upside_before = None
    if pos_before >= 0:
        price_before_move = float(prices.iloc[pos_before])
        upside_before = target / price_before_move - 1

    return AnalystTargetContext(
        current_price=current_price,
        target_price=float(target),
        upside_now_pct=float(upside_now),
        upside_before_move_pct=float(upside_before) if upside_before is not None else None,
        already_above_target=upside_now < 0,
    )


def _earnings_dates(symbol: str) -> set:
    """Known earnings report dates for this symbol, or an empty set if the
    (known-flaky) earnings endpoint is unavailable — episodes just come back
    untagged for earnings coincidence rather than failing the whole analysis."""
    try:
        records = market_data.earnings_history(symbol)
    except market_data.MarketDataError:
        return set()
    return {pd.Timestamp(r["report_date"]) for r in records}


def _tag_context(price_index: pd.DatetimeIndex, volume: pd.Series, date, window_days: int, earnings_dates: set):
    pos = price_index.get_loc(date)
    start_pos = max(0, pos - window_days + 1)
    episode_dates = price_index[start_pos: pos + 1]

    coincided_with_earnings = any(
        any(abs((ed - report).days) <= EARNINGS_COINCIDENCE_BUFFER_DAYS for report in earnings_dates)
        for ed in episode_dates
    )

    baseline_start = max(0, start_pos - VOLUME_BASELINE_DAYS)
    baseline_volume = volume.iloc[baseline_start:start_pos]
    episode_volume = volume.iloc[start_pos: pos + 1]

    volume_ratio = None
    volume_anomaly = False
    if len(baseline_volume) >= 10 and baseline_volume.mean() > 0:
        volume_ratio = float(episode_volume.mean() / baseline_volume.mean())
        volume_anomaly = volume_ratio >= VOLUME_ANOMALY_MULTIPLIER

    return coincided_with_earnings, volume_anomaly, volume_ratio


def analyze(
    symbol: str,
    require_earnings: Optional[bool] = None,
    require_volume_anomaly: Optional[bool] = None,
) -> MomentumAnalysisResult:
    history = market_data.get_price_history(symbol)
    prices = history["adj_close"]
    volume = history["volume"]
    earnings_dates = _earnings_dates(symbol)
    best_return, best_window = _best_window_series(prices)

    current_move = float(best_return.iloc[-1])
    current_window = int(best_window.iloc[-1])
    current_price = float(prices.iloc[-1])
    current_coincided_with_earnings, current_volume_anomaly, current_volume_ratio = _tag_context(
        prices.index, volume, prices.index[-1], current_window, earnings_dates
    )
    # Symmetric band: a match must be no smaller than MATCH_THRESHOLD_FRACTION
    # of the current move AND no larger than its reciprocal. Without the
    # upper bound, a small current move (e.g. 5%) would happily "match"
    # historical moves several times its size (e.g. 30%) just for clearing
    # the floor — comparing an 8% day to a 30% one isn't a real comparison.
    threshold = abs(current_move) * MATCH_THRESHOLD_FRACTION
    upper_threshold = abs(current_move) / MATCH_THRESHOLD_FRACTION

    max_forward = max(FORWARD_WINDOWS_DAYS)
    max_candidate_window = max(CANDIDATE_WINDOWS)
    # Exclude the tail where we can't measure the longest forward window, and
    # the head where the longest candidate window has no history yet.
    candidate_idx = list(prices.index[max_candidate_window: len(prices) - max_forward])

    same_direction = best_return >= 0 if current_move >= 0 else best_return <= 0
    min_window = current_window / WINDOW_PROXIMITY_RATIO
    max_window = current_window * WINDOW_PROXIMITY_RATIO

    all_episodes: List[dict] = []
    i = 0
    while i < len(candidate_idx):
        date = candidate_idx[i]
        window = int(best_window.loc[date])
        if bool(same_direction.loc[date]) and min_window <= window <= max_window:
            coincided, vol_anomaly, vol_ratio = _tag_context(prices.index, volume, date, window, earnings_dates)
            passes_context = (require_earnings is None or coincided == require_earnings) and (
                require_volume_anomaly is None or vol_anomaly == require_volume_anomaly
            )
            if passes_context:
                all_episodes.append(
                    {
                        "date": date,
                        "window_days": window,
                        "move_pct": float(best_return.loc[date]),
                        "coincided_with_earnings": coincided,
                        "volume_anomaly": vol_anomaly,
                        "volume_ratio": vol_ratio,
                    }
                )
            i += window + max_forward  # jump past this move regardless of the context filter
        else:
            i += 1

    matching_episodes = [e for e in all_episodes if threshold <= abs(e["move_pct"]) <= upper_threshold]

    used_fallback = False
    if matching_episodes:
        episodes = matching_episodes
    elif all_episodes:
        used_fallback = True
        # Closest in magnitude to the current move, not just "biggest
        # available" — a fallback should pick the nearest miss in either
        # direction, not necessarily the largest historical move on record.
        episodes = sorted(all_episodes, key=lambda e: abs(abs(e["move_pct"]) - abs(current_move)))[
            :FALLBACK_MAX_EPISODES
        ]
    else:
        episodes = []

    forward_windows: Dict[int, ForwardWindowStats] = {}
    price_index = list(prices.index)

    for horizon in FORWARD_WINDOWS_DAYS:
        forward_returns = []
        for episode in episodes:
            pos = price_index.index(episode["date"])
            if pos + horizon < len(price_index):
                forward_returns.append(float(prices.iloc[pos + horizon] / prices.iloc[pos] - 1))

        if forward_returns:
            arr = np.array(forward_returns)
            forward_windows[horizon] = ForwardWindowStats(
                n=len(arr),
                pct_positive=float((arr > 0).mean()),
                mean_return=float(arr.mean()),
                median_return=float(np.median(arr)),
                min_return=float(arr.min()),
                max_return=float(arr.max()),
            )
        else:
            forward_windows[horizon] = ForwardWindowStats(
                n=0, pct_positive=None, mean_return=None, median_return=None, min_return=None, max_return=None
            )

    return MomentumAnalysisResult(
        symbol=symbol,
        current_price=current_price,
        detected_window_days=current_window,
        current_move_pct=current_move,
        current_coincided_with_earnings=current_coincided_with_earnings,
        current_volume_anomaly=current_volume_anomaly,
        current_volume_ratio=current_volume_ratio,
        threshold_pct=threshold,
        episodes_found=len(episodes),
        episode_details=[
            {
                "date": e["date"].strftime("%Y-%m-%d"),
                "window_days": e["window_days"],
                "move_pct": e["move_pct"],
                "pct_of_current": abs(e["move_pct"]) / abs(current_move) if current_move else None,
                "coincided_with_earnings": e["coincided_with_earnings"],
                "volume_anomaly": e["volume_anomaly"],
                "volume_ratio": e["volume_ratio"],
            }
            for e in episodes
        ],
        forward_windows=forward_windows,
        low_confidence=len(episodes) < MIN_EPISODES_FOR_CONFIDENCE or used_fallback,
        used_fallback=used_fallback,
        analyst_context=_analyst_context(symbol, prices, current_window),
    )
