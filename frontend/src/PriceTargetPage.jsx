import { useEffect, useState } from "react";
import { API_BASE, pct } from "./api";

function ProbabilityTile({ label, colorVar, probability, children }) {
  const percent = Math.max(0, Math.min(100, probability * 100));
  return (
    <div className="tile">
      <p className="tile-label" style={{ "--tile-color": `var(${colorVar})` }}>
        <span className="tile-dot" />
        {label}
      </p>
      <p className="tile-value">{pct(probability)}</p>
      <div className="meter">
        <div className="meter-fill" style={{ width: `${percent}%`, background: `var(${colorVar})` }} />
      </div>
      <div className="tile-details">{children}</div>
    </div>
  );
}

export default function PriceTargetPage() {
  const [stocks, setStocks] = useState([]);
  const [overview, setOverview] = useState([]);
  const [overviewLoading, setOverviewLoading] = useState(true);
  const [symbol, setSymbol] = useState("");
  const [targetPrice, setTargetPrice] = useState("");
  const [horizonMonths, setHorizonMonths] = useState(12);
  const [driftMode, setDriftMode] = useState("risk_neutral");
  const [riskFreeMaturity, setRiskFreeMaturity] = useState("10year");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/api/stocks`)
      .then((res) => res.json())
      .then((data) => {
        setStocks(data);
        if (data.length > 0) setSymbol(data[0].symbol);
      })
      .catch(() => setError("No se pudo conectar con el backend"));

    fetch(`${API_BASE}/api/stocks/overview`)
      .then((res) => res.json())
      .then(setOverview)
      .catch(() => {})
      .finally(() => setOverviewLoading(false));
  }, []);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setResult(null);
    setLoading(true);
    try {
      const params = new URLSearchParams({
        symbol,
        target_price: targetPrice,
        horizon_months: horizonMonths,
        drift_mode: driftMode,
        risk_free_maturity: riskFreeMaturity,
      });
      const res = await fetch(`${API_BASE}/api/probability?${params}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Error desconocido");
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  const selectedStock = stocks.find((s) => s.symbol === symbol);
  const direction = result && result.target_price >= result.current_price ? "suba a" : "baje a";

  return (
    <div className="layout">
      <aside className="sidebar sidebar-left card">
        <h2 className="sidebar-title">Variación de hoy</h2>
        <p className="sidebar-subtitle">Cambio de precio del último día</p>

        {overviewLoading && <p className="field-hint">Cargando…</p>}

        <ul className="watchlist">
          {overview.map((s) => (
            <li key={s.symbol} className="watchlist-row">
              <div className="watchlist-symbol">
                <span className="watchlist-ticker">{s.symbol}</span>
                <span className="watchlist-name">{s.name}</span>
              </div>
              {s.current_price != null && s.daily_change_pct != null ? (
                <div className="watchlist-prices">
                  <span>${s.current_price.toFixed(2)}</span>
                  <span
                    className={
                      "watchlist-upside " +
                      (s.daily_change_pct >= 0 ? "watchlist-upside-positive" : "watchlist-upside-negative")
                    }
                  >
                    {s.daily_change_pct >= 0 ? "+" : ""}
                    {(s.daily_change_pct * 100).toFixed(2)}%
                  </span>
                </div>
              ) : (
                <span className="field-hint">Sin datos</span>
              )}
            </li>
          ))}
        </ul>
      </aside>

      <div className="app">
        <header className="app-header">
          <p className="eyebrow">Probabilidad de Price Target</p>
          <h1>¿Va a llegar tu acción a su objetivo?</h1>
          <p className="subtitle">Black-Scholes y Montecarlo, comparados lado a lado.</p>
        </header>

        <form onSubmit={handleSubmit} className="card form">
          <div className="field">
            <label htmlFor="symbol">Acción</label>
            <select id="symbol" value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              {stocks.map((s) => (
                <option key={s.symbol} value={s.symbol}>
                  {s.symbol} — {s.name}
                </option>
              ))}
            </select>
            {selectedStock && <p className="field-hint">Sector: {selectedStock.sector_etf}</p>}
          </div>

          <div className="field">
            <label htmlFor="target_price">Precio objetivo (USD)</label>
            <input
              id="target_price"
              type="number"
              step="0.01"
              placeholder="Ej. 250.00"
              required
              value={targetPrice}
              onChange={(e) => setTargetPrice(e.target.value)}
            />
          </div>

          <div className="field">
            <label htmlFor="horizon">Horizonte</label>
            <select id="horizon" value={horizonMonths} onChange={(e) => setHorizonMonths(e.target.value)}>
              <option value={1}>1 mes</option>
              <option value={2}>2 meses</option>
              <option value={3}>3 meses</option>
              <option value={6}>6 meses</option>
              <option value={12}>12 meses</option>
            </select>
          </div>

          <div className="field">
            <label htmlFor="drift_mode">Supuesto de tendencia</label>
            <select id="drift_mode" value={driftMode} onChange={(e) => setDriftMode(e.target.value)}>
              <option value="risk_neutral">Neutral al riesgo (tasa libre de riesgo)</option>
              <option value="market_expectation">Expectativa del mercado (analistas)</option>
            </select>
            <p className="field-hint">
              {driftMode === "risk_neutral"
                ? "Conservador: asume que el precio solo sube al ritmo de la tasa libre de riesgo; toda la probabilidad viene de la volatilidad."
                : "Usa el precio objetivo promedio de analistas como tendencia esperada a 12 meses."}
            </p>
          </div>

          {driftMode === "risk_neutral" && (
            <div className="field">
              <label htmlFor="risk_free_maturity">Vencimiento de la tasa libre de riesgo</label>
              <select
                id="risk_free_maturity"
                value={riskFreeMaturity}
                onChange={(e) => setRiskFreeMaturity(e.target.value)}
              >
                <option value="3month">3 meses (letra del Tesoro)</option>
                <option value="10year">10 años (bono del Tesoro)</option>
              </select>
            </div>
          )}

          <button type="submit" disabled={loading}>
            {loading ? "Calculando…" : "Calcular probabilidad"}
          </button>
        </form>

        {error && <p className="error">{error}</p>}

        {result && (
          <div className="result">
            <p className="result-summary">
              Probabilidad de que <strong>{result.symbol}</strong> {direction}{" "}
              <strong>${result.target_price.toFixed(2)}</strong> en {result.horizon_months}{" "}
              {result.horizon_months == 1 ? "mes" : "meses"}, partiendo de $
              {result.current_price.toFixed(2)} hoy.
            </p>

            <p className="result-summary">
              Tendencia usada: {(result.drift_used * 100).toFixed(2)}% anual (
              {result.drift_source === "analyst_consensus_target"
                ? `objetivo promedio de analistas: $${result.analyst_target_price.toFixed(2)}`
                : result.drift_source === "risk_free_rate"
                ? "tasa libre de riesgo"
                : "sin cobertura de analistas, se usó la tasa libre de riesgo"}
              )
            </p>

            <div className="tiles">
              <ProbabilityTile
                label="Black-Scholes"
                colorVar="--series-1"
                probability={result.black_scholes.probability}
              >
                Vol: {(result.black_scholes.volatility_used * 100).toFixed(1)}% (
                {result.black_scholes.volatility_source})
              </ProbabilityTile>

              <ProbabilityTile
                label="Montecarlo"
                colorVar="--series-2"
                probability={result.monte_carlo.probability_without_sector_adjustment}
              >
                <div>
                  Vol: {(result.monte_carlo.volatility_used * 100).toFixed(1)}% (histórica) —{" "}
                  {result.monte_carlo.n_simulations.toLocaleString()} simulaciones
                </div>
                <div>
                  {result.monte_carlo.sector_adjustment_applied
                    ? `Con ajuste de sector (${result.monte_carlo.sector_adjustment_applied > 0 ? "+" : ""}${(
                        result.monte_carlo.sector_adjustment_applied * 100
                      ).toFixed(2)}% anual): ${pct(result.monte_carlo.probability)}`
                    : "Sin ajuste de sector (modelo aún no entrenado)"}
                </div>
              </ProbabilityTile>
            </div>

            <p className="footnote">
              Tasa libre de riesgo ({result.risk_free_maturity === "3month" ? "3 meses" : "10 años"}):{" "}
              {(result.risk_free_rate * 100).toFixed(2)}% · Consultado{" "}
              {new Date(result.queried_at).toLocaleString()}
            </p>
          </div>
        )}
      </div>

      <aside className="sidebar sidebar-right card">
        <h2 className="sidebar-title">Precio objetivo de analistas</h2>
        <p className="sidebar-subtitle">Acciones en las que está entrenado el modelo</p>

        {overviewLoading && <p className="field-hint">Cargando…</p>}

        <ul className="watchlist">
          {overview.map((s) => (
            <li key={s.symbol} className="watchlist-row">
              <div className="watchlist-symbol">
                <span className="watchlist-ticker">{s.symbol}</span>
                <span className="watchlist-name">{s.name}</span>
              </div>
              {s.current_price != null && s.analyst_target_price != null ? (
                <div className="watchlist-prices">
                  <span>${s.current_price.toFixed(2)}</span>
                  <span className="watchlist-arrow">→</span>
                  <span>${s.analyst_target_price.toFixed(2)}</span>
                  <span
                    className={
                      "watchlist-upside " + (s.upside_pct >= 0 ? "watchlist-upside-positive" : "watchlist-upside-negative")
                    }
                  >
                    {s.upside_pct >= 0 ? "+" : ""}
                    {(s.upside_pct * 100).toFixed(1)}%
                  </span>
                </div>
              ) : (
                <span className="field-hint">Sin cobertura de analistas</span>
              )}
            </li>
          ))}
        </ul>
      </aside>
    </div>
  );
}
