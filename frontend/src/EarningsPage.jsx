import { useEffect, useMemo, useState } from "react";
import { API_BASE, pct } from "./api";
import PriceWindowChart from "./PriceWindowChart";

const TREND_WINDOW_LABELS = { 5: "1 sem", 10: "2 sem", 20: "1 mes", 60: "3 meses" };
const MIN_PAIRS_FOR_CORRELATION = 5; // mirrors earnings_model.MIN_PAIRS_FOR_CORRELATION

const UPTREND_TOGGLE_OPTIONS = [
  { value: "", label: "Cualquiera" },
  { value: "true", label: "Solo subiendo" },
  { value: "false", label: "Solo bajando" },
];
const BEAT_TOGGLE_OPTIONS = [
  { value: "", label: "Cualquiera" },
  { value: "true", label: "Solo beats" },
  { value: "false", label: "Solo misses" },
];
const SECTOR_TOGGLE_OPTIONS = [
  { value: "", label: "Cualquiera" },
  { value: "true", label: "Superó al sector" },
  { value: "false", label: "Quedó debajo" },
];

function mean(values) {
  return values.reduce((a, b) => a + b, 0) / values.length;
}

function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 !== 0 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function pearsonCorrelation(xs, ys) {
  const n = xs.length;
  const meanX = mean(xs);
  const meanY = mean(ys);
  let num = 0;
  let denX = 0;
  let denY = 0;
  for (let i = 0; i < n; i++) {
    const dx = xs[i] - meanX;
    const dy = ys[i] - meanY;
    num += dx * dy;
    denX += dx * dx;
    denY += dy * dy;
  }
  if (denX === 0 || denY === 0) return null;
  return num / Math.sqrt(denX * denY);
}

function beatMissStats(reactions, wantBeat) {
  const group = reactions
    .filter(
      (r) =>
        r.surprise_pct != null &&
        r.reaction_day_return != null &&
        (wantBeat ? r.surprise_pct > 0 : r.surprise_pct < 0)
    )
    .map((r) => r.reaction_day_return);
  if (group.length === 0) return { n: 0, mean_reaction: null, median_reaction: null };
  return { n: group.length, mean_reaction: mean(group), median_reaction: median(group) };
}

// Recomputes the same aggregate stats earnings_model.py used to return, but
// on whatever subset the secondary filters have already narrowed down to —
// so they stay in sync with the table/chart without another server request.
function computeStats(reactions) {
  const nBeats = reactions.filter((r) => (r.surprise_pct ?? 0) > 0).length;
  const nMisses = reactions.filter((r) => (r.surprise_pct ?? 0) < 0).length;

  const validReactionDays = reactions.map((r) => r.reaction_day_return).filter((v) => v != null);
  const pctPositive = validReactionDays.length
    ? validReactionDays.filter((v) => v > 0).length / validReactionDays.length
    : null;

  const pairs = reactions.filter((r) => r.surprise_pct != null && r.reaction_day_return != null);
  let correlation = null;
  if (pairs.length >= MIN_PAIRS_FOR_CORRELATION) {
    const xs = pairs.map((p) => p.surprise_pct);
    const ys = pairs.map((p) => p.reaction_day_return);
    correlation = pearsonCorrelation(xs, ys);
  }

  return {
    nBeats,
    nMisses,
    pctPositive,
    correlation,
    beatStats: beatMissStats(reactions, true),
    missStats: beatMissStats(reactions, false),
  };
}

function applySecondaryFilters(reactions, filters) {
  const { requireBeat, sinceYear, trendMinPct, trendMaxPct, requireSector } = filters;
  return reactions.filter((r) => {
    if (requireBeat !== "") {
      if (r.surprise_pct == null || String(r.surprise_pct > 0) !== requireBeat) return false;
    }
    if (sinceYear !== "") {
      if (Number(r.report_date.slice(0, 4)) < Number(sinceYear)) return false;
    }
    if (trendMinPct !== "") {
      if (r.trend_before_pct == null || r.trend_before_pct < Number(trendMinPct) / 100) return false;
    }
    if (trendMaxPct !== "") {
      if (r.trend_before_pct == null || r.trend_before_pct > Number(trendMaxPct) / 100) return false;
    }
    if (requireSector !== "") {
      if (r.excess_reaction_day_return == null || String(r.excess_reaction_day_return > 0) !== requireSector)
        return false;
    }
    return true;
  });
}

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

function ToggleGroup({ value, onChange, options }) {
  return (
    <div className="toggle-group">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          className={"toggle-button" + (value === o.value ? " toggle-button-active" : "")}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export default function EarningsPage() {
  const [stocks, setStocks] = useState([]);
  const [symbol, setSymbol] = useState("");
  // Primary filters — the only ones submitted to the server via "Analizar".
  const [requireUptrend, setRequireUptrend] = useState("");
  const [trendWindowDays, setTrendWindowDays] = useState("20");

  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  // Secondary filters — applied instantly, client-side, on top of whatever
  // "Analizar" already fetched. No new request on change.
  const [secRequireBeat, setSecRequireBeat] = useState("");
  const [secSinceYear, setSecSinceYear] = useState("");
  const [secTrendMinPct, setSecTrendMinPct] = useState("");
  const [secTrendMaxPct, setSecTrendMaxPct] = useState("");
  const [secRequireSector, setSecRequireSector] = useState("");

  const [selectedReport, setSelectedReport] = useState(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/stocks`)
      .then((res) => res.json())
      .then((data) => {
        setStocks(data);
        if (data.length > 0) setSymbol(data[0].symbol);
      })
      .catch(() => setError("No se pudo conectar con el backend"));
  }, []);

  const filteredReactions = useMemo(() => {
    if (!result) return [];
    return applySecondaryFilters(result.reactions, {
      requireBeat: secRequireBeat,
      sinceYear: secSinceYear,
      trendMinPct: secTrendMinPct,
      trendMaxPct: secTrendMaxPct,
      requireSector: secRequireSector,
    });
  }, [result, secRequireBeat, secSinceYear, secTrendMinPct, secTrendMaxPct, secRequireSector]);

  const stats = useMemo(() => computeStats(filteredReactions), [filteredReactions]);

  const hasActiveSecondaryFilters =
    secRequireBeat !== "" || secSinceYear !== "" || secTrendMinPct !== "" || secTrendMaxPct !== "" || secRequireSector !== "";

  function clearSecondaryFilters() {
    setSecRequireBeat("");
    setSecSinceYear("");
    setSecTrendMinPct("");
    setSecTrendMaxPct("");
    setSecRequireSector("");
  }

  // Keeps the chart selection stable across secondary-filter tweaks when
  // possible, and only jumps to a fallback report when the selected one got
  // filtered out (or on a fresh "Analizar" fetch).
  useEffect(() => {
    if (filteredReactions.length === 0) {
      setSelectedReport(null);
      return;
    }
    setSelectedReport((prev) => {
      if (prev && filteredReactions.some((r) => r.report_date === prev && r.price_window.length > 0)) {
        return prev;
      }
      const withChart = [...filteredReactions].reverse().find((r) => r.price_window.length > 0);
      return withChart ? withChart.report_date : null;
    });
  }, [filteredReactions]);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setResult(null);
    setLoading(true);
    try {
      const params = new URLSearchParams({ symbol, trend_window_days: trendWindowDays });
      if (requireUptrend !== "") params.set("require_uptrend_before", requireUptrend);

      const res = await fetch(`${API_BASE}/api/earnings-analysis?${params}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Error desconocido");
      setResult(data);
      clearSecondaryFilters();
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
            <label>Venía subiendo antes del reporte</label>
            <ToggleGroup value={requireUptrend} onChange={setRequireUptrend} options={UPTREND_TOGGLE_OPTIONS} />
          </div>

          <div className="field">
            <label htmlFor="trend_window">Ventana para medir "venía subiendo/bajando"</label>
            <select id="trend_window" value={trendWindowDays} onChange={(e) => setTrendWindowDays(e.target.value)}>
              <option value="5">1 semana antes</option>
              <option value="10">2 semanas antes</option>
              <option value="20">1 mes antes</option>
              <option value="60">3 meses antes</option>
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
              <p className="result-summary">No hay reportes que cumplan el filtro inicial para esta acción.</p>
            ) : (
              <>
                <div className="card earnings-secondary-filters">
                  <div className="secondary-filters-header">
                    <h2 className="sidebar-title">Filtros secundarios</h2>
                    {hasActiveSecondaryFilters && (
                      <button type="button" className="link-button" onClick={clearSecondaryFilters}>
                        Limpiar filtros
                      </button>
                    )}
                  </div>
                  <p className="field-hint" style={{ marginBottom: "1rem" }}>
                    Se aplican al instante sobre los {result.reactions.length} reportes ya cargados por el filtro
                    inicial — cambian la tabla, las estadísticas y el gráfico sin volver a consultar al servidor.
                  </p>
                  <div className="secondary-filters-grid">
                    <div className="field">
                      <label>Resultado del reporte</label>
                      <ToggleGroup value={secRequireBeat} onChange={setSecRequireBeat} options={BEAT_TOGGLE_OPTIONS} />
                    </div>

                    <div className="field">
                      <label>Excedió al sector ese día</label>
                      <ToggleGroup
                        value={secRequireSector}
                        onChange={setSecRequireSector}
                        options={SECTOR_TOGGLE_OPTIONS}
                      />
                    </div>

                    <div className="field">
                      <label htmlFor="sec_since_year">Desde el año</label>
                      <input
                        id="sec_since_year"
                        type="number"
                        placeholder="Ej. 2022 (vacío = todo)"
                        value={secSinceYear}
                        onChange={(e) => setSecSinceYear(e.target.value)}
                      />
                    </div>

                    <div className="field">
                      <label>Rango de tendencia previa (%)</label>
                      <div style={{ display: "flex", gap: "0.6rem" }}>
                        <input
                          type="number"
                          placeholder="Mínimo, ej. -10"
                          value={secTrendMinPct}
                          onChange={(e) => setSecTrendMinPct(e.target.value)}
                          style={{ flex: 1 }}
                        />
                        <input
                          type="number"
                          placeholder="Máximo, ej. 15"
                          value={secTrendMaxPct}
                          onChange={(e) => setSecTrendMaxPct(e.target.value)}
                          style={{ flex: 1 }}
                        />
                      </div>
                    </div>
                  </div>
                </div>

                {filteredReactions.length === 0 ? (
                  <p className="result-summary">Ningún reporte cumple estos filtros secundarios.</p>
                ) : (
                  <>
                    <p className="result-summary">
                      <strong>{result.symbol}</strong>
                      {hasActiveSecondaryFilters && (
                        <> ({filteredReactions.length} de {result.reactions.length} reportes tras los filtros secundarios)</>
                      )}
                      : superó estimaciones en {stats.nBeats} reportes, no las alcanzó en {stats.nMisses}. De las
                      reacciones medibles, {pct(stats.pctPositive)} fueron positivas el día del reporte.
                      {stats.correlation != null && (
                        <>
                          {" "}
                          Correlación entre tamaño de la sorpresa y tamaño de la reacción:{" "}
                          <strong>{stats.correlation.toFixed(2)}</strong> (de -1 a 1; cerca de 0 = poca relación).
                        </>
                      )}
                    </p>

                    {filteredReactions.length < 8 && (
                      <p className="error">
                        Muestra chica ({filteredReactions.length} reportes) — orientativo, no una predicción.
                      </p>
                    )}

                    <div
                      className="tiles momentum-tiles"
                      style={{ gridTemplateColumns: "1fr 1fr", marginBottom: "1.25rem" }}
                    >
                      <StatBlock label="Reacción tras un beat" stats={stats.beatStats} />
                      <StatBlock label="Reacción tras un miss" stats={stats.missStats} />
                    </div>

                    <p className="field-hint" style={{ marginBottom: "0.5rem" }}>
                      Clic en una fila para ver ese reporte en el gráfico.
                    </p>

                    <div className="earnings-table-wrap card">
                      <table className="earnings-table">
                        <thead>
                          <tr>
                            <th>Fecha reporte</th>
                            <th>EPS real</th>
                            <th>EPS estimado</th>
                            <th>Sorpresa EPS</th>
                            <th>Tendencia previa ({TREND_WINDOW_LABELS[result.trend_window_days]})</th>
                            <th>Fecha reacción</th>
                            <th>Día</th>
                            <th>Volumen</th>
                            <th>Exceso vs sector</th>
                            <th>+1 sem</th>
                            <th>+2 sem</th>
                            <th>+1 mes</th>
                            <th>+3 meses</th>
                          </tr>
                        </thead>
                        <tbody>
                          {filteredReactions.map((r) => {
                            const clickable = r.price_window.length > 0;
                            const selected = r.report_date === selectedReport;
                            return (
                              <tr
                                key={r.report_date}
                                onClick={() => clickable && setSelectedReport(r.report_date)}
                                className={
                                  (clickable ? "earnings-row-clickable" : "") +
                                  (selected ? " earnings-row-selected" : "")
                                }
                              >
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
                                  <SignedPct value={r.forward_returns["2w"]} />
                                </td>
                                <td>
                                  <SignedPct value={r.forward_returns["1m"]} />
                                </td>
                                <td>
                                  <SignedPct value={r.forward_returns["3m"]} />
                                </td>
                              </tr>
                            );
                          })}
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
                            {filteredReactions
                              .filter((r) => r.price_window.length > 0)
                              .map((r) => (
                                <option key={r.report_date} value={r.report_date}>
                                  Reporte {r.report_date} (reacción {r.reaction_date})
                                </option>
                              ))}
                          </select>
                        </div>
                        {(() => {
                          const selected = filteredReactions.find((r) => r.report_date === selectedReport);
                          return selected ? (
                            <PriceWindowChart priceWindow={selected.price_window} reactionDate={selected.reaction_date} />
                          ) : null;
                        })()}
                      </div>
                    )}
                  </>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
