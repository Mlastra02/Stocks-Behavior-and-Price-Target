import os
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from flask import Flask, jsonify, request
from flask_cors import CORS

from app.config.stocks import TRACKED_STOCKS
from app.data import market_data_client as market_data
from app.pricing import black_scholes, earnings_model, momentum_model, monte_carlo, sector_model

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


@app.get("/api/momentum-analysis")
def momentum_analysis():
    """Historical event study: after moves like the current one, what happened next?

    The lookback window is auto-detected (see momentum_model.py) — the caller
    only supplies the symbol.
    """
    symbol = request.args.get("symbol", "").upper()

    if symbol not in TRACKED_STOCKS:
        return jsonify({"error": f"'{symbol}' no está en la lista de acciones soportadas"}), 400

    try:
        result = momentum_model.analyze(symbol)
    except market_data.MarketDataError as exc:
        return jsonify({"error": str(exc)}), 502

    ctx = result.analyst_context

    return jsonify(
        {
            "symbol": result.symbol,
            "current_price": result.current_price,
            "detected_window_days": result.detected_window_days,
            "current_move_pct": result.current_move_pct,
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
    """Historical earnings-day reactions: EPS surprise + how the stock actually moved after."""
    symbol = request.args.get("symbol", "").upper()

    if symbol not in TRACKED_STOCKS:
        return jsonify({"error": f"'{symbol}' no está en la lista de acciones soportadas"}), 400

    try:
        result = earnings_model.analyze(symbol)
    except market_data.MarketDataError as exc:
        return jsonify({"error": str(exc)}), 502

    return jsonify(
        {
            "symbol": result.symbol,
            "n_beats": result.n_beats,
            "n_misses": result.n_misses,
            "pct_positive_reaction_day": result.pct_positive_reaction_day,
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
                }
                for r in result.reactions
            ],
        }
    )


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
