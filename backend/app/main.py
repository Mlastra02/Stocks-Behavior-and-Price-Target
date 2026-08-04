import os
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from flask import Flask, jsonify, request
from flask_cors import CORS

from app.config.stocks import TRACKED_STOCKS
from app.data import market_data_client as market_data
from app.data import portfolio_store
from app.pricing import black_scholes, earnings_model, momentum_model, monte_carlo, sector_model, technical_indicators

app = Flask(__name__)
CORS(app)


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/api/stocks")
def list_stocks():
    return jsonify(
        [{"symbol": symbol, **info} for symbol, info in TRACKED_STOCKS.items()]
    )


@app.get("/api/stocks/overview")
def stocks_overview():
    """Current price + analyst consensus target for every tracked stock, for the sidebar."""
    overview = []
    for symbol, info in TRACKED_STOCKS.items():
        try:
            current_price = market_data.latest_price(symbol)
            target_price = market_data.analyst_price_target(symbol)
            change_pct = market_data.daily_change_pct(symbol)
        except market_data.MarketDataError:
            current_price = None
            target_price = None
            change_pct = None

        upside_pct = (
            (target_price / current_price - 1)
            if current_price and target_price
            else None
        )

        overview.append(
            {
                "symbol": symbol,
                "name": info["name"],
                "current_price": current_price,
                "analyst_target_price": target_price,
                "upside_pct": upside_pct,
                "daily_change_pct": change_pct,
            }
        )

    return jsonify(overview)


def _parse_optional_bool(raw):
    if raw is None:
        return None
    if raw.lower() in ("true", "1"):
        return True
    if raw.lower() in ("false", "0"):
        return False
    raise ValueError(f"'{raw}' no es un booleano válido (true/false)")


@app.get("/api/momentum-analysis")
def momentum_analysis():
    """Historical event study: after moves like the current one, what happened next?

    The lookback window is auto-detected (see momentum_model.py) — the caller
    only needs to supply the symbol, plus optionally require_earnings /
    require_volume_anomaly ("true"/"false") to filter which historical
    episodes count, on top of magnitude + duration matching.
    """
    symbol = request.args.get("symbol", "").upper()

    if symbol not in TRACKED_STOCKS:
        return jsonify({"error": f"'{symbol}' no está en la lista de acciones soportadas"}), 400

    try:
        require_earnings = _parse_optional_bool(request.args.get("require_earnings"))
        require_volume_anomaly = _parse_optional_bool(request.args.get("require_volume_anomaly"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        result = momentum_model.analyze(
            symbol, require_earnings=require_earnings, require_volume_anomaly=require_volume_anomaly
        )
    except market_data.MarketDataError as exc:
        return jsonify({"error": str(exc)}), 502

    ctx = result.analyst_context

    return jsonify(
        {
            "symbol": result.symbol,
            "current_price": result.current_price,
            "detected_window_days": result.detected_window_days,
            "current_move_pct": result.current_move_pct,
            "current_coincided_with_earnings": result.current_coincided_with_earnings,
            "current_volume_anomaly": result.current_volume_anomaly,
            "current_volume_ratio": result.current_volume_ratio,
            "threshold_pct": result.threshold_pct,
            "episodes_found": result.episodes_found,
            "episode_details": result.episode_details,
            "low_confidence": result.low_confidence,
            "used_fallback": result.used_fallback,
            "forward_windows": {
                str(horizon): {
                    "n": stats.n,
                    "pct_positive": stats.pct_positive,
                    "mean_return": stats.mean_return,
                    "median_return": stats.median_return,
                    "min_return": stats.min_return,
                    "max_return": stats.max_return,
                }
                for horizon, stats in result.forward_windows.items()
            },
            "analyst_context": {
                "target_price": ctx.target_price,
                "upside_now_pct": ctx.upside_now_pct,
                "upside_before_move_pct": ctx.upside_before_move_pct,
                "already_above_target": ctx.already_above_target,
            },
        }
    )


@app.get("/api/earnings-analysis")
def earnings_analysis():
    """Historical earnings-day reactions: EPS surprise + how the stock actually moved after.

    This is only the INITIAL filter — symbol, require_uptrend_before
    ("true"/"false"), and trend_window_days. Everything else (beat/miss,
    since-year, an arbitrary trend %% range, sector over/under-performance)
    is applied client-side by the frontend on the already-fetched reactions,
    so it can refine instantly without another round trip.
    """
    symbol = request.args.get("symbol", "").upper()

    if symbol not in TRACKED_STOCKS:
        return jsonify({"error": f"'{symbol}' no está en la lista de acciones soportadas"}), 400

    try:
        require_uptrend_before = _parse_optional_bool(request.args.get("require_uptrend_before"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    trend_window_days = request.args.get(
        "trend_window_days", earnings_model.DEFAULT_TREND_WINDOW_DAYS, type=int
    )

    try:
        result = earnings_model.analyze(
            symbol,
            require_uptrend_before=require_uptrend_before,
            trend_window_days=trend_window_days,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except market_data.MarketDataError as exc:
        return jsonify({"error": str(exc)}), 502

    return jsonify(
        {
            "symbol": result.symbol,
            "trend_window_days": trend_window_days,
            "n_beats": result.n_beats,
            "n_misses": result.n_misses,
            "pct_positive_reaction_day": result.pct_positive_reaction_day,
            "surprise_reaction_correlation": result.surprise_reaction_correlation,
            "beat_stats": {
                "n": result.beat_stats.n,
                "mean_reaction": result.beat_stats.mean_reaction,
                "median_reaction": result.beat_stats.median_reaction,
            },
            "miss_stats": {
                "n": result.miss_stats.n,
                "mean_reaction": result.miss_stats.mean_reaction,
                "median_reaction": result.miss_stats.median_reaction,
            },
            "current_snapshot": {
                "as_of_date": result.current_snapshot.as_of_date,
                "current_price": result.current_snapshot.current_price,
                "trend_pct": result.current_snapshot.trend_pct,
                "volume_ratio": result.current_snapshot.volume_ratio,
                "sector_trend_pct": result.current_snapshot.sector_trend_pct,
                "excess_trend_pct": result.current_snapshot.excess_trend_pct,
            },
            "reactions": [
                {
                    "report_date": r.report_date,
                    "eps_actual": r.eps_actual,
                    "eps_estimate": r.eps_estimate,
                    "surprise_pct": r.surprise_pct,
                    "reaction_date": r.reaction_date,
                    "reaction_day_return": r.reaction_day_return,
                    "forward_returns": r.forward_returns,
                    "price_window": r.price_window,
                    "trend_before_pct": r.trend_before_pct,
                    "volume_ratio": r.volume_ratio,
                    "sector_reaction_day_return": r.sector_reaction_day_return,
                    "excess_reaction_day_return": r.excess_reaction_day_return,
                    "next_open_price": r.next_open_price,
                    "aftermarket_gap_pct": r.aftermarket_gap_pct,
                }
                for r in result.reactions
            ],
        }
    )


@app.get("/api/technical-analysis")
def technical_analysis():
    """RSI/SMA/EMA bands, golden/death-cross read, and the price-volume rule
    for a single stock, plus a chart series (price + SMA50/SMA200/EMA20/RSI
    per day, and earnings report dates in range) for the long-term view.
    """
    symbol = request.args.get("symbol", "").upper()

    if symbol not in TRACKED_STOCKS:
        return jsonify({"error": f"'{symbol}' no está en la lista de acciones soportadas"}), 400

    chart_months = request.args.get("chart_months", 24, type=int)
    chart_days = request.args.get("chart_days", type=int)

    try:
        result = technical_indicators.analyze(symbol, chart_months=chart_months, chart_days=chart_days)
    except market_data.MarketDataError as exc:
        return jsonify({"error": str(exc)}), 502

    def banded(b):
        return {"value": b.value, "band": b.band, "explanation": b.explanation}

    return jsonify(
        {
            "symbol": result.symbol,
            "as_of_date": result.as_of_date,
            "current_price": result.current_price,
            "price_target": result.price_target,
            "upside_pct": result.upside_pct,
            "rsi": banded(result.rsi),
            "ema_short": banded(result.ema_short),
            "sma_medium": banded(result.sma_medium),
            "sma_long": banded(result.sma_long),
            "cross_signal": {
                "state": result.cross_signal.state,
                "sma50": result.cross_signal.sma50,
                "sma200": result.cross_signal.sma200,
                "gap_pct": result.cross_signal.gap_pct,
                "explanation": result.cross_signal.explanation,
            },
            "volume_signal": {
                "current_volume": result.volume_signal.current_volume,
                "volume_ratio": result.volume_signal.volume_ratio,
                "price_change_pct": result.volume_signal.price_change_pct,
                "quadrant": result.volume_signal.quadrant,
                "explanation": result.volume_signal.explanation,
            },
            "chart": [
                {
                    "date": p.date,
                    "price": p.price,
                    "sma50": p.sma50,
                    "sma200": p.sma200,
                    "ema20": p.ema20,
                    "rsi": p.rsi,
                }
                for p in result.chart
            ],
            "earnings_dates": result.earnings_dates,
        }
    )


def _enrich_holdings(holdings: dict) -> dict:
    """Attaches live price/value/gain/allocation to each stored holding."""
    enriched = []
    total_value = 0.0

    for symbol, holding in holdings.items():
        quantity = holding["quantity"]
        avg_cost = holding["avg_cost"]
        try:
            current_price = market_data.latest_price(symbol)
            daily_change_pct = market_data.daily_change_pct(symbol)
        except market_data.MarketDataError:
            current_price = None
            daily_change_pct = None

        current_value = current_price * quantity if current_price is not None else None
        gain_pct = (current_price / avg_cost - 1) if current_price is not None else None
        if current_value is not None:
            total_value += current_value

        enriched.append(
            {
                "symbol": symbol,
                "name": TRACKED_STOCKS.get(symbol, {}).get("name", symbol),
                "quantity": quantity,
                "avg_cost": avg_cost,
                "current_price": current_price,
                "current_value": current_value,
                "daily_change_pct": daily_change_pct,
                "gain_pct": gain_pct,
            }
        )

    for row in enriched:
        row["allocation_pct"] = (row["current_value"] / total_value) if row["current_value"] is not None and total_value > 0 else None

    enriched.sort(key=lambda r: r["allocation_pct"] or 0, reverse=True)
    return {"holdings": enriched, "total_value": total_value}


@app.get("/api/portfolio")
def get_portfolio():
    return jsonify(_enrich_holdings(portfolio_store.load_holdings()))


@app.put("/api/portfolio/holdings/<symbol>")
def upsert_portfolio_holding(symbol):
    symbol = symbol.upper()
    if symbol not in TRACKED_STOCKS:
        return jsonify({"error": f"'{symbol}' no está en la lista de acciones soportadas"}), 400

    body = request.get_json(silent=True) or {}
    quantity = body.get("quantity")
    avg_cost = body.get("avg_cost")
    if not isinstance(quantity, (int, float)) or not isinstance(avg_cost, (int, float)):
        return jsonify({"error": "quantity y avg_cost son requeridos y deben ser numéricos"}), 400

    try:
        holdings = portfolio_store.upsert_holding(symbol, quantity=float(quantity), avg_cost=float(avg_cost))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(_enrich_holdings(holdings))


@app.delete("/api/portfolio/holdings/<symbol>")
def delete_portfolio_holding(symbol):
    holdings = portfolio_store.delete_holding(symbol.upper())
    return jsonify(_enrich_holdings(holdings))


DRIFT_MODES = {"risk_neutral", "market_expectation"}
RISK_FREE_MATURITIES = {"3month", "10year"}


@app.get("/api/probability")
def probability():
    symbol = request.args.get("symbol", "").upper()
    target_price = request.args.get("target_price", type=float)
    horizon_months = request.args.get("horizon_months", type=float)
    drift_mode = request.args.get("drift_mode", "risk_neutral")
    risk_free_maturity = request.args.get("risk_free_maturity", "10year")

    if symbol not in TRACKED_STOCKS:
        return jsonify({"error": f"'{symbol}' no está en la lista de acciones soportadas"}), 400
    if target_price is None or target_price <= 0:
        return jsonify({"error": "target_price es requerido y debe ser positivo"}), 400
    if horizon_months is None or horizon_months <= 0:
        return jsonify({"error": "horizon_months es requerido y debe ser positivo"}), 400
    if drift_mode not in DRIFT_MODES:
        return jsonify({"error": f"drift_mode debe ser uno de: {sorted(DRIFT_MODES)}"}), 400
    if risk_free_maturity not in RISK_FREE_MATURITIES:
        return jsonify({"error": f"risk_free_maturity debe ser uno de: {sorted(RISK_FREE_MATURITIES)}"}), 400

    t_years = horizon_months / 12.0

    try:
        current_price = market_data.latest_price(symbol)
        rf_rate = market_data.risk_free_rate(maturity=risk_free_maturity)

        hist_vol = market_data.historical_volatility(symbol)
        impl_vol = market_data.implied_volatility(symbol)
        bs_vol = impl_vol if impl_vol is not None else hist_vol
        bs_vol_source = "implied" if impl_vol is not None else "historical (sin opciones disponibles)"

        analyst_target = None
        drift_used = rf_rate
        drift_source = "risk_free_rate"
        if drift_mode == "market_expectation":
            analyst_drift = market_data.analyst_expected_drift(symbol)
            if analyst_drift is not None:
                drift_used = analyst_drift
                drift_source = "analyst_consensus_target"
                analyst_target = market_data.analyst_price_target(symbol)
            else:
                drift_source = "risk_free_rate (sin cobertura de analistas)"

        sector_adjustment = sector_model.predict_drift_adjustment(symbol)
        # Same seed for both runs so the only difference between them is the
        # sector adjustment itself, not fresh simulation noise.
        mc_seed = 42

        bs_result = black_scholes.probability_reach_target(
            s0=current_price,
            target_price=target_price,
            t_years=t_years,
            risk_free_rate=drift_used,
            volatility=bs_vol,
            volatility_source=bs_vol_source,
        )

        mc_result = monte_carlo.simulate_touch_probability(
            s0=current_price,
            target_price=target_price,
            t_years=t_years,
            risk_free_rate=drift_used,
            volatility=hist_vol,
            sector_adjustment=sector_adjustment if sector_adjustment else None,
            seed=mc_seed,
        )

        mc_no_adjustment_result = monte_carlo.simulate_touch_probability(
            s0=current_price,
            target_price=target_price,
            t_years=t_years,
            risk_free_rate=drift_used,
            volatility=hist_vol,
            sector_adjustment=None,
            seed=mc_seed,
        )

    except market_data.MarketDataError as exc:
        return jsonify({"error": str(exc)}), 502

    return jsonify(
        {
            "symbol": symbol,
            "current_price": current_price,
            "target_price": target_price,
            "horizon_months": horizon_months,
            "risk_free_rate": rf_rate,
            "risk_free_maturity": risk_free_maturity,
            "drift_mode": drift_mode,
            "drift_used": drift_used,
            "drift_source": drift_source,
            "analyst_target_price": analyst_target,
            "queried_at": datetime.now(timezone.utc).isoformat(),
            "black_scholes": {
                "probability": bs_result.probability,
                "volatility_used": bs_result.volatility_used,
                "volatility_source": bs_result.volatility_source,
            },
            "monte_carlo": {
                "probability": mc_result.probability,
                "probability_without_sector_adjustment": mc_no_adjustment_result.probability,
                "volatility_used": mc_result.volatility_used,
                "volatility_source": mc_result.volatility_source,
                "n_simulations": mc_result.n_simulations,
                "sector_adjustment_applied": mc_result.sector_adjustment_applied,
            },
        }
    )


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
