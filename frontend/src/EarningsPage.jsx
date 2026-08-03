import { useEffect, useState } from "react";
import { API_BASE, pct } from "./api";
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

export default function EarningsPage() {
  const [stocks, setStocks] = useState([]);
  const [symbol, setSymbol] = useState("");
  const [result, setResult] = useState(null);
  const [selectedQuarter, setSelectedQuarter] = useState(null);
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
      const res = await fetch(`${API_BASE}/api/earnings-analysis?symbol=${symbol}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Error desconocido");
      setResult(data);
      const withChart = [...data.reactions].reverse().find((r) => r.price_window.length > 0);
      setSelectedQuarter(withChart ? withChart.quarter_end : null);
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
            Últimos ~4 trimestres: sorpresa de EPS (superó o no las estimaciones) y cómo se movió el precio después.
            La fecha de reacción se infiere buscando el mayor movimiento diario en las semanas después del cierre
            de cada trimestre — Yahoo no nos deja consultar la fecha exacta de forma confiable.
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

          <button type="submit" disabled={loading}>
            {loading ? "Buscando…" : "Analizar"}
          </button>
        </form>

        {error && <p className="error">{error}</p>}

        {result && (
          <div className="result">
            {result.reactions.length === 0 ? (
              <p className="result-summary">No hay datos de earnings disponibles para esta acción.</p>
            ) : (
              <>
                <p className="result-summary">
                  <strong>{result.symbol}</strong>: superó estimaciones en {result.n_beats} de{" "}
                  {result.reactions.length} trimestres, no las alcanzó en {result.n_misses}. De las reacciones
                  medibles, {pct(result.pct_positive_reaction_day)} fueron positivas el día del reporte.
                </p>

                <p className="error">
                  Muestra muy pequeña ({result.reactions.length} trimestres) — orientativo, no una predicción.
                </p>

                <div className="earnings-table-wrap card">
                  <table className="earnings-table">
                    <thead>
                      <tr>
                        <th>Trimestre</th>
                        <th>EPS real</th>
                        <th>EPS estimado</th>
                        <th>Sorpresa</th>
                        <th>Fecha reacción</th>
                        <th>Día</th>
                        <th>+1 sem</th>
                        <th>+1 mes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.reactions.map((r) => (
                        <tr key={r.quarter_end}>
                          <td>{r.quarter_end}</td>
                          <td>{r.eps_actual != null ? r.eps_actual.toFixed(2) : "—"}</td>
                          <td>{r.eps_estimate != null ? r.eps_estimate.toFixed(2) : "—"}</td>
                          <td>
                            <SignedPct value={r.surprise_pct} />
                          </td>
                          <td>{r.reaction_date || "—"}</td>
                          <td>
                            <SignedPct value={r.reaction_day_return} />
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

                {selectedQuarter && (
                  <div className="card price-chart-card">
                    <div className="price-chart-header">
                      <h2 className="sidebar-title">Precio: 3 meses antes y después</h2>
                      <select
                        value={selectedQuarter}
                        onChange={(e) => setSelectedQuarter(e.target.value)}
                        className="price-chart-select"
                      >
                        {result.reactions
                          .filter((r) => r.price_window.length > 0)
                          .map((r) => (
                            <option key={r.quarter_end} value={r.quarter_end}>
                              Trimestre {r.quarter_end} (earnings {r.reaction_date})
                            </option>
                          ))}
                      </select>
                    </div>
                    {(() => {
                      const selected = result.reactions.find((r) => r.quarter_end === selectedQuarter);
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
