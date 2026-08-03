import { useEffect, useState } from "react";
import { API_BASE, pct, TRI_STATE_OPTIONS } from "./api";
import PriceWindowChart from "./PriceWindowChart";

function SignedPct({ value }) {
  if (value == null) return <span className="field-hint">—</span>;
  const positive = value >= 0;
  return (
    <span className={positive ? "watchlist-upside-positive" : "watchlist-upside-negative"}>
      {positive ? "+" : ""}
      {(value * 100).toFixed(1)}%
    </span>
  );
}

function StatBlock({ label, stats }) {
  return (
    <div className="tile">
      <p className="tile-label">
        <span className="tile-dot" style={{ background: "var(--series-1)" }} />
        {label}
      </p>
      {stats.n === 0 ? (
        <p className="field-hint">Sin datos</p>
      ) : (
        <>
          <p className="tile-value">
            <SignedPct value={stats.mean_reaction} />
          </p>
          <p className="field-hint">
            reacción promedio de {stats.n} reportes (mediana <SignedPct value={stats.median_reaction} />)
          </p>
        </>
      )}
    </div>
  );
}

export default function EarningsPage() {
  const [stocks, setStocks] = useState([]);
  const [symbol, setSymbol] = useState("");
  const [requireUptrend, setRequireUptrend] = useState("");
  const [requireBeat, setRequireBeat] = useState("");
  const [sinceYear, setSinceYear] = useState("");
  const [result, setResult] = useState(null);
  const [selectedReport, setSelectedReport] = useState(null);
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
  }, []);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setResult(null);
    setLoading(true);
    try {
      const params = new URLSearchParams({ symbol });
      if (requireUptrend !== "") params.set("require_uptrend_before", requireUptrend);
      if (requireBeat !== "") params.set("require_beat", requireBeat);
      if (sinceYear !== "") params.set("since_year", sinceYear);

      const res = await fetch(`${API_BASE}/api/earnings-analysis?${params}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Error desconocido");
      setResult(data);
      const withChart = [...data.reactions].reverse().find((r) => r.price_window.length > 0);
      setSelectedReport(withChart ? withChart.report_date : null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="layout momentum-layout">
      <div className="app">
        <header className="app-header">
          <p className="eyebrow">Reacción a Earnings</p>
          <h1>¿Cómo reaccionó el precio a earnings pasados?</h1>
          <p className="subtitle">
            Todos los reportes de earnings disponibles (fechas reales de Yahoo, hasta ~12 años para las acciones
            más establecidas): sorpresa de EPS y cómo se movió el precio después. La reacción se mide el mismo día
            si el reporte fue antes del cierre del mercado, o el día hábil siguiente si fue después.
          </p>
        </header>

        <form onSubmit={handleSubmit} className="card form">
          <div className="field">
            <label htmlFor="earnings_symbol">Acción</label>
            <select id="earnings_symbol" value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              {stocks.map((s) => (
                <option key={s.symbol} value={s.symbol}>
                  {s.symbol} — {s.name}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label htmlFor="require_uptrend">Venía subiendo antes del reporte</label>
            <select id="require_uptrend" value={requireUptrend} onChange={(e) => setRequireUptrend(e.target.value)}>
              {TRI_STATE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label htmlFor="require_beat">Resultado del reporte</label>
            <select id="require_beat" value={requireBeat} onChange={(e) => setRequireBeat(e.target.value)}>
              <option value="">Cualquiera</option>
              <option value="true">Solo beats (superó estimaciones)</option>
              <option value="false">Solo misses (no las alcanzó)</option>
            </select>
          </div>

          <div className="field">
            <label htmlFor="since_year">Desde el año</label>
            <input
              id="since_year"
              type="number"
              placeholder="Ej. 2022 (vacío = todo el historial)"
              value={sinceYear}
              onChange={(e) => setSinceYear(e.target.value)}
            />
          </div>

          <button type="submit" disabled={loading}>
            {loading ? "Buscando…" : "Analizar"}
          </button>
        </form>

        {error && <p className="error">{error}</p>}

        {result && (
          <div className="result">
            {result.reactions.length === 0 ? (
              <p className="result-summary">No hay reportes que cumplan estos filtros para esta acción.</p>
            ) : (
              <>
                <p className="result-summary">
                  <strong>{result.symbol}</strong>: superó estimaciones en {result.n_beats} de{" "}
                  {result.reactions.length} reportes, no las alcanzó en {result.n_misses}. De las reacciones
                  medibles, {pct(result.pct_positive_reaction_day)} fueron positivas el día del reporte.
                  {result.surprise_reaction_correlation != null && (
                    <>
                      {" "}
                      Correlación entre tamaño de la sorpresa y tamaño de la reacción:{" "}
                      <strong>{result.surprise_reaction_correlation.toFixed(2)}</strong> (de -1 a 1; cerca de 0 =
                      poca relación).
                    </>
                  )}
                </p>

                {result.reactions.length < 8 && (
                  <p className="error">
                    Muestra chica ({result.reactions.length} reportes) — orientativo, no una predicción.
                  </p>
                )}

                <div className="tiles momentum-tiles" style={{ gridTemplateColumns: "1fr 1fr", marginBottom: "1.25rem" }}>
                  <StatBlock label="Reacción tras un beat" stats={result.beat_stats} />
                  <StatBlock label="Reacción tras un miss" stats={result.miss_stats} />
                </div>

                <div className="earnings-table-wrap card">
                  <table className="earnings-table">
                    <thead>
                      <tr>
                        <th>Fecha reporte</th>
                        <th>EPS real</th>
                        <th>EPS estimado</th>
                        <th>Sorpresa</th>
                        <th>Tendencia previa</th>
                        <th>Fecha reacción</th>
                        <th>Día</th>
                        <th>Volumen</th>
                        <th>Exceso vs sector</th>
                        <th>+1 sem</th>
                        <th>+1 mes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.reactions.map((r) => (
                        <tr key={r.report_date}>
                          <td>{r.report_date}</td>
                          <td>{r.eps_actual != null ? r.eps_actual.toFixed(2) : "—"}</td>
                          <td>{r.eps_estimate != null ? r.eps_estimate.toFixed(2) : "—"}</td>
                          <td>
                            <SignedPct value={r.surprise_pct} />
                          </td>
                          <td>
                            <SignedPct value={r.trend_before_pct} />
                          </td>
                          <td>{r.reaction_date || "—"}</td>
                          <td>
                            <SignedPct value={r.reaction_day_return} />
                          </td>
                          <td>{r.volume_ratio != null ? `${r.volume_ratio.toFixed(1)}x` : "—"}</td>
                          <td>
                            <SignedPct value={r.excess_reaction_day_return} />
                          </td>
                          <td>
                            <SignedPct value={r.forward_returns["1w"]} />
                          </td>
                          <td>
                            <SignedPct value={r.forward_returns["1m"]} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {selectedReport && (
                  <div className="card price-chart-card">
                    <div className="price-chart-header">
                      <h2 className="sidebar-title">Precio: 3 meses antes y después</h2>
                      <select
                        value={selectedReport}
                        onChange={(e) => setSelectedReport(e.target.value)}
                        className="price-chart-select"
                      >
                        {result.reactions
                          .filter((r) => r.price_window.length > 0)
                          .map((r) => (
                            <option key={r.report_date} value={r.report_date}>
                              Reporte {r.report_date} (reacción {r.reaction_date})
                            </option>
                          ))}
                      </select>
                    </div>
                    {(() => {
                      const selected = result.reactions.find((r) => r.report_date === selectedReport);
                      return selected ? (
                        <PriceWindowChart priceWindow={selected.price_window} reactionDate={selected.reaction_date} />
                      ) : null;
                    })()}
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
