"""RSI / SMA / EMA / golden-death-cross / price-volume read for a single
stock — the "how does this look technically, right now" companion to the
earnings and momentum event studies.

Two design rules run through this whole module:

1. Every "alto/moderado/bajo" band is a threshold on a concrete, stated
   number (RSI value, % distance from a moving average) — never a vibe.
2. The golden/death-cross proximity call and the price-volume rule are
   both allowed to say "no hay señal clara" instead of forcing a category
   when the evidence is thin. Forcing a call on noise is worse than no
   call — every classification here ships with the numbers behind it so
   the caller can see exactly why (or why not).
"""
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

from app.data import market_data_client as market_data

RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70

EMA_SHORT_SPAN = 20
SMA_MEDIUM_WINDOW = 50
SMA_LONG_WINDOW = 200

# How far price has to sit from a moving average, as a fraction, before it
# counts as "alto"/"bajo" instead of "moderado" — i.e. close enough to the
# average that direction alone isn't a strong signal.
MA_BAND_THRESHOLD_PCT = 0.05

# Golden/death cross: only look at crosses within this many trading days as
# "recent", and only call a cross "approaching" when the SMA50-SMA200 gap is
# both this close (as a fraction of price) AND has been consistently closing
# over CONVERGENCE_LOOKBACK_DAYS (R^2 of a linear fit above the R^2 floor) —
# a genuine, clean trend, not two noisy lines that happened to twitch closer.
RECENT_CROSS_LOOKBACK_DAYS = 10
CONVERGENCE_LOOKBACK_DAYS = 15
CROSS_PROXIMITY_THRESHOLD_PCT = 0.025
CONVERGENCE_R2_FLOOR = 0.5

# Price-volume rule: only classify when BOTH the price move and the volume
# deviation from baseline clear these floors — otherwise "sin señal clara".
VOLUME_BASELINE_DAYS = 60
VOLUME_SIGNAL_PRICE_WINDOW_DAYS = 10
VOLUME_SIGNAL_PRICE_MOVE_FLOOR = 0.03
VOLUME_SIGNAL_VOLUME_DEVIATION_FLOOR = 0.20


@dataclass
class BandedValue:
    value: Optional[float]
    band: Optional[str]  # "alto" | "moderado" | "bajo" | None
    explanation: str


@dataclass
class CrossSignal:
    state: str  # "golden_recent" | "death_recent" | "approaching_golden" | "approaching_death" | "bullish" | "bearish" | "none"
    sma50: Optional[float]
    sma200: Optional[float]
    gap_pct: Optional[float]
    explanation: str


@dataclass
class VolumeSignal:
    current_volume: Optional[float]
    volume_ratio: Optional[float]  # last VOLUME_SIGNAL_PRICE_WINDOW_DAYS avg / trailing baseline avg
    price_change_pct: Optional[float]
    quadrant: Optional[str]  # one of the 4 rules below, or None if evidence is too thin
    explanation: str


@dataclass
class ChartPoint:
    date: str
    price: float
    sma50: Optional[float]
    sma200: Optional[float]
    ema20: Optional[float]
    rsi: Optional[float]


@dataclass
class TechnicalAnalysisResult:
    symbol: str
    as_of_date: str
    current_price: float
    price_target: Optional[float]
    upside_pct: Optional[float]
    rsi: BandedValue
    ema_short: BandedValue
    sma_medium: BandedValue
    cross_signal: CrossSignal
    volume_signal: VolumeSignal
    chart: List[ChartPoint] = field(default_factory=list)
    earnings_dates: List[str] = field(default_factory=list)  # report dates within the chart window


def _rsi(prices: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    """Wilder's RSI — the original/standard smoothing, not a plain rolling mean."""
    delta = prices.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.where(avg_loss != 0, 100.0)  # no losses in the lookback -> maximally overbought
    rsi = rsi.where(~((avg_gain == 0) & (avg_loss == 0)), 50.0)  # flat -> neutral
    return rsi


def _rsi_band(value: Optional[float]) -> BandedValue:
    if value is None or pd.isna(value):
        return BandedValue(value=None, band=None, explanation="No hay suficiente historial para calcular el RSI.")
    if value >= RSI_OVERBOUGHT:
        band = "alto"
        explanation = f"RSI {value:.0f} ≥ {RSI_OVERBOUGHT} — zona de sobrecompra, la suba viene acelerada."
    elif value <= RSI_OVERSOLD:
        band = "bajo"
        explanation = f"RSI {value:.0f} ≤ {RSI_OVERSOLD} — zona de sobreventa, la baja viene acelerada."
    else:
        band = "moderado"
        explanation = f"RSI {value:.0f} entre {RSI_OVERSOLD} y {RSI_OVERBOUGHT} — momentum sin extremos."
    return BandedValue(value=float(value), band=band, explanation=explanation)


def _ma_band(current_price: float, ma_value: Optional[float], ma_label: str) -> BandedValue:
    if ma_value is None or pd.isna(ma_value):
        return BandedValue(value=None, band=None, explanation=f"No hay suficiente historial para calcular {ma_label}.")
    diff_pct = current_price / ma_value - 1
    if diff_pct >= MA_BAND_THRESHOLD_PCT:
        band = "alto"
        explanation = f"Precio {diff_pct * 100:+.1f}% por encima de {ma_label} — por encima de la banda de ±{MA_BAND_THRESHOLD_PCT * 100:.0f}%, sesgo alcista."
    elif diff_pct <= -MA_BAND_THRESHOLD_PCT:
        band = "bajo"
        explanation = f"Precio {diff_pct * 100:+.1f}% por debajo de {ma_label} — por debajo de la banda de ±{MA_BAND_THRESHOLD_PCT * 100:.0f}%, sesgo bajista."
    else:
        band = "moderado"
        explanation = f"Precio {diff_pct * 100:+.1f}% respecto a {ma_label} — dentro de la banda de ±{MA_BAND_THRESHOLD_PCT * 100:.0f}%, cerca de la media."
    return BandedValue(value=float(ma_value), band=band, explanation=explanation)


def _cross_signal(sma50: pd.Series, sma200: pd.Series) -> CrossSignal:
    valid = sma50.notna() & sma200.notna()
    if valid.sum() < RECENT_CROSS_LOOKBACK_DAYS + 1:
        return CrossSignal(
            state="none", sma50=None, sma200=None, gap_pct=None,
            explanation="No hay suficiente historial para calcular SMA50/SMA200.",
        )

    s50 = sma50[valid]
    s200 = sma200[valid]
    gap = s50 - s200
    gap_pct = float(gap.iloc[-1] / s200.iloc[-1])
    current_bullish = gap.iloc[-1] > 0

    # 1) An actual cross within the recent window beats any "approaching" read.
    recent_gap = gap.iloc[-(RECENT_CROSS_LOOKBACK_DAYS + 1):]
    sign_changes = np.sign(recent_gap).diff().fillna(0) != 0
    if sign_changes.any():
        days_ago = len(recent_gap) - 1 - np.where(sign_changes)[0][-1]
        if current_bullish:
            return CrossSignal(
                state="golden_recent", sma50=float(s50.iloc[-1]), sma200=float(s200.iloc[-1]), gap_pct=gap_pct,
                explanation=f"SMA50 cruzó por encima de SMA200 hace {days_ago} sesiones (golden cross) — régimen de tendencia de largo plazo alcista.",
            )
        return CrossSignal(
            state="death_recent", sma50=float(s50.iloc[-1]), sma200=float(s200.iloc[-1]), gap_pct=gap_pct,
            explanation=f"SMA50 cruzó por debajo de SMA200 hace {days_ago} sesiones (death cross) — régimen de tendencia de largo plazo bajista.",
        )

    # 2) No recent cross — only call an approach with real evidence: the gap
    # has to already be close AND consistently narrowing (clean linear fit),
    # not just noisy lines that happen to be near each other right now.
    if abs(gap_pct) <= CROSS_PROXIMITY_THRESHOLD_PCT and len(gap) >= CONVERGENCE_LOOKBACK_DAYS:
        window = gap.iloc[-CONVERGENCE_LOOKBACK_DAYS:]
        x = np.arange(len(window))
        slope, intercept = np.polyfit(x, window.values, 1)
        fitted = slope * x + intercept
        ss_res = float(np.sum((window.values - fitted) ** 2))
        ss_tot = float(np.sum((window.values - window.values.mean()) ** 2))
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

        narrowing_toward_golden = not current_bullish and slope > 0
        narrowing_toward_death = current_bullish and slope < 0

        if r2 >= CONVERGENCE_R2_FLOOR and (narrowing_toward_golden or narrowing_toward_death):
            state = "approaching_golden" if narrowing_toward_golden else "approaching_death"
            label = "golden cross" if narrowing_toward_golden else "death cross"
            return CrossSignal(
                state=state, sma50=float(s50.iloc[-1]), sma200=float(s200.iloc[-1]), gap_pct=gap_pct,
                explanation=(
                    f"SMA50 y SMA200 están a {abs(gap_pct) * 100:.1f}% de distancia y se vienen acercando de forma "
                    f"consistente en los últimos {CONVERGENCE_LOOKBACK_DAYS} días (ajuste lineal R²={r2:.2f}) — "
                    f"posible {label} cerca si sigue así. No es una garantía, solo lo que muestra la tendencia reciente."
                ),
            )

    # 3) No cross, no clean convergence — just report the current alignment.
    if current_bullish:
        return CrossSignal(
            state="bullish", sma50=float(s50.iloc[-1]), sma200=float(s200.iloc[-1]), gap_pct=gap_pct,
            explanation=f"SMA50 sigue {gap_pct * 100:.1f}% por encima de SMA200, sin señal de acercamiento a un death cross.",
        )
    return CrossSignal(
        state="bearish", sma50=float(s50.iloc[-1]), sma200=float(s200.iloc[-1]), gap_pct=gap_pct,
        explanation=f"SMA50 sigue {abs(gap_pct) * 100:.1f}% por debajo de SMA200, sin señal de acercamiento a un golden cross.",
    )


def _volume_signal(prices: pd.Series, volume: pd.Series) -> VolumeSignal:
    n = len(prices)
    if n < VOLUME_BASELINE_DAYS + VOLUME_SIGNAL_PRICE_WINDOW_DAYS:
        return VolumeSignal(
            current_volume=None, volume_ratio=None, price_change_pct=None, quadrant=None,
            explanation="No hay suficiente historial para leer la relación precio-volumen.",
        )

    recent_volume = volume.iloc[-VOLUME_SIGNAL_PRICE_WINDOW_DAYS:]
    baseline_volume = volume.iloc[-(VOLUME_BASELINE_DAYS + VOLUME_SIGNAL_PRICE_WINDOW_DAYS):-VOLUME_SIGNAL_PRICE_WINDOW_DAYS]
    if baseline_volume.mean() <= 0:
        return VolumeSignal(
            current_volume=float(volume.iloc[-1]), volume_ratio=None, price_change_pct=None, quadrant=None,
            explanation="Volumen base insuficiente para comparar.",
        )

    volume_ratio = float(recent_volume.mean() / baseline_volume.mean())
    price_change_pct = float(prices.iloc[-1] / prices.iloc[-1 - VOLUME_SIGNAL_PRICE_WINDOW_DAYS] - 1)

    price_meaningful = abs(price_change_pct) >= VOLUME_SIGNAL_PRICE_MOVE_FLOOR
    volume_deviation = abs(volume_ratio - 1)
    volume_meaningful = volume_deviation >= VOLUME_SIGNAL_VOLUME_DEVIATION_FLOOR

    base_facts = (
        f"Precio {price_change_pct * 100:+.1f}% en los últimos {VOLUME_SIGNAL_PRICE_WINDOW_DAYS} días hábiles, "
        f"volumen promedio {volume_ratio:.2f}x el de los {VOLUME_BASELINE_DAYS} días previos."
    )

    if not price_meaningful or not volume_meaningful:
        missing = []
        if not price_meaningful:
            missing.append(f"el movimiento de precio no llega al umbral de ±{VOLUME_SIGNAL_PRICE_MOVE_FLOOR * 100:.0f}%")
        if not volume_meaningful:
            missing.append(f"el volumen no se desvía lo suficiente del umbral de ±{VOLUME_SIGNAL_VOLUME_DEVIATION_FLOOR * 100:.0f}%")
        return VolumeSignal(
            current_volume=float(volume.iloc[-1]), volume_ratio=volume_ratio, price_change_pct=price_change_pct,
            quadrant=None,
            explanation=f"Sin señal clara: {' y '.join(missing)}. {base_facts}",
        )

    price_up = price_change_pct > 0
    volume_up = volume_ratio > 1
    if price_up and volume_up:
        quadrant = "confirmacion_alcista"
        rule = "precio y volumen suben juntos: confirmación alcista, la suba viene con respaldo real."
    elif price_up and not volume_up:
        quadrant = "advertencia_alcista"
        rule = "el precio sube pero el volumen cae: suba sin mucha convicción, posible agotamiento cerca."
    elif not price_up and volume_up:
        quadrant = "confirmacion_bajista"
        rule = "el precio baja y el volumen sube: confirmación bajista, hay presión vendedora real."
    else:
        quadrant = "advertencia_bajista"
        rule = "el precio baja pero el volumen también cae: baja sin mucha convicción, podría estar agotándose."

    return VolumeSignal(
        current_volume=float(volume.iloc[-1]), volume_ratio=volume_ratio, price_change_pct=price_change_pct,
        quadrant=quadrant, explanation=f"{base_facts} {rule[0].upper() + rule[1:]}",
    )


def analyze(symbol: str, chart_months: int = 24) -> TechnicalAnalysisResult:
    history = market_data.get_price_history(symbol)
    prices = history["adj_close"]
    volume = history["volume"]

    current_price = float(prices.iloc[-1])
    as_of_date = prices.index[-1].strftime("%Y-%m-%d")

    price_target = market_data.analyst_price_target(symbol)
    upside_pct = (price_target / current_price - 1) if price_target else None

    rsi_series = _rsi(prices)
    rsi = _rsi_band(rsi_series.iloc[-1] if len(rsi_series) else None)

    ema_short_series = prices.ewm(span=EMA_SHORT_SPAN, adjust=False).mean()
    ema_short = _ma_band(current_price, ema_short_series.iloc[-1] if len(ema_short_series) else None, f"la EMA({EMA_SHORT_SPAN})")

    sma_medium_series = prices.rolling(SMA_MEDIUM_WINDOW).mean()
    sma_medium = _ma_band(current_price, sma_medium_series.iloc[-1] if len(sma_medium_series) else None, f"la SMA({SMA_MEDIUM_WINDOW})")

    sma_long_series = prices.rolling(SMA_LONG_WINDOW).mean()
    cross_signal = _cross_signal(sma_medium_series, sma_long_series)

    volume_signal = _volume_signal(prices, volume)

    chart_start = prices.index[-1] - pd.DateOffset(months=chart_months)
    chart_mask = prices.index >= chart_start
    chart = [
        ChartPoint(
            date=ts.strftime("%Y-%m-%d"),
            price=float(prices.loc[ts]),
            sma50=float(sma_medium_series.loc[ts]) if pd.notna(sma_medium_series.loc[ts]) else None,
            sma200=float(sma_long_series.loc[ts]) if pd.notna(sma_long_series.loc[ts]) else None,
            ema20=float(ema_short_series.loc[ts]) if pd.notna(ema_short_series.loc[ts]) else None,
            rsi=float(rsi_series.loc[ts]) if ts in rsi_series.index and pd.notna(rsi_series.loc[ts]) else None,
        )
        for ts in prices.index[chart_mask]
    ]

    chart_end = prices.index[-1]
    earnings_dates = [
        record["report_date"]
        for record in market_data.earnings_history(symbol)
        if chart_start <= pd.Timestamp(record["report_date"]) <= chart_end
    ]

    return TechnicalAnalysisResult(
        symbol=symbol,
        as_of_date=as_of_date,
        current_price=current_price,
        price_target=price_target,
        upside_pct=upside_pct,
        rsi=rsi,
        ema_short=ema_short,
        sma_medium=sma_medium,
        cross_signal=cross_signal,
        volume_signal=volume_signal,
        chart=chart,
        earnings_dates=earnings_dates,
    )
