import { useEffect, useMemo, useState } from "react";
import { API_BASE, pct, TRI_STATE_OPTIONS } from "./api";
import PriceWindowChart from "./PriceWindowChart";
import RangeStrip from "./RangeStrip";

const TREND_WINDOW_LABELS = { 5: "1 sem", 10: "2 sem", 20: "1 mes", 60: "3 meses" };
const MIN_PAIRS_FOR_CORRELATION = 5; // mirrors earnings_model.MIN_PAIRS_FOR_CORRELATION

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

// For reports coming into the report on an up/down trend: did the market
// gap up in the aftermarket (open vs the close right before it), and did
// that day close positive too? Each side reports both a positive-rate
// (with the raw fraction) and the average signed move, so "how often" and
// "by how much" are both visible.
function trendDirectionStats(reactions, wantUp) {
  const group = reactions.filter((r) => r.trend_before_pct != null && (wantUp ? r.trend_before_pct > 0 : r.trend_before_pct < 0));

  const gapValues = group.map((r) => r.aftermarket_gap_pct).filter((v) => v != null);
  const dayValues = group.map((r) => r.reaction_day_return).filter((v) => v != null);

  return {
    n: group.length,
    gapPositiveCount: gapValues.filter((v) => v > 0).length,
    gapTotal: gapValues.length,
    gapPositivePct: gapValues.length ? gapValues.filter((v) => v > 0).length / gapValues.length : null,
    gapMean: gapValues.length ? mean(gapValues) : null,
    dayPositiveCount: dayValues.filter((v) => v > 0).length,
    dayTotal: dayValues.length,
    dayPositivePct: dayValues.length ? dayValues.filter((v) => v > 0).length / dayValues.length : null,
    dayMean: dayValues.length ? mean(dayValues) : null,
  };
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
    trendUpStats: trendDirectionStats(reactions, true),
    trendDownStats: trendDirectionStats(reactions, false),
  };
}

const RANGE_EPSILON = 1e-9;

function reportYear(reaction) {
  return Number(reaction.report_date.slice(0, 4));
}

function computeYearDomain(reactions) {
  const years = reactions.map(reportYear);
  return { min: Math.min(...years), max: Math.max(...years) };
}

function computeTrendDomain(reactions) {
  const values = reactions.map((r) => r.trend_before_pct).filter((v) => v != null);
  if (values.length === 0) return null;
  return { min: Math.min(...values), max: Math.max(...values) };
}

// A range filter is only "active" on the side(s) a handle has actually been
// dragged in from the domain's extreme — otherwise it's a no-op, including
// for reports whose value is null (so an unmoved strip never hides them).
function applySecondaryFilters(reactions, filters) {
  const { requireBeat, requireSector, yearMin, yearMax, yearDomain, trendMin, trendMax, trendDomain } = filters;
  return reactions.filter((r) => {
    if (requireBeat !== "") {
      if (r.surprise_pct == null || String(r.surprise_pct > 0) !== requireBeat) return false;
    }
    if (requireSector !== "") {
      if (r.excess_reaction_day_return == null || String(r.excess_reaction_day_return > 0) !== requireSector)
        return false;
    }
    if (yearDomain) {
      const minActive = yearMin > yearDomain.min + RANGE_EPSILON;
      const maxActive = yearMax < yearDomain.max - RANGE_EPSILON;
      if (minActive || maxActive) {
        const year = reportYear(r);
        if (minActive && year < yearMin) return false;
        if (maxActive && year > yearMax) return false;
      }
    }
    if (trendDomain) {
      const minActive = trendMin > trendDomain.min + RANGE_EPSILON;
      const maxActive = trendMax < trendDomain.max - RANGE_EPSILON;
      if (minActive || maxActive) {
        if (r.trend_before_pct == null) return false;
        if (minActive && r.trend_before_pct < trendMin) return false;
        if (maxActive && r.trend_before_pct > trendMax) return false;
      }
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

function TrendReactionBlock({ label, stats }) {
  return (
    <div className="tile">
      <p className="tile-label">
        <span className="tile-dot" style={{ background: "var(--series-1)" }} />
        {label}
      </p>
      {stats.n === 0 ? (
        <p className="field-hint">Sin datos</p>
      ) : (
        <div className="tile-details" style={{ fontSize: "0.85rem", color: "var(--text-secondary)" }}>
          <p style={{ margin: 0 }}>
            Gap de apertura positivo: <strong>{pct(stats.gapPositivePct)}</strong> ({stats.gapPositiveCount}/{stats.gapTotal}),
            promedio <SignedPct value={stats.gapMean} />
          </p>
          <p style={{ margin: 0 }}>
            Día completo positivo: <strong>{pct(stats.dayPositivePct)}</strong> ({stats.dayPositiveCount}/{stats.dayTotal}),
            promedio <SignedPct value={stats.dayMean} />
          </p>
        </div>
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
  // "Analizar" already fetched. No new request on change. The two range
  // filters default to their full domain (i.e. "no filter") and only start
  // excluding once a handle is dragged in from an extreme.
  const [secRequireBeat, setSecRequireBeat] = useState("");
  const [secRequireSector, setSecRequireSector] = useState("");
  const [secYearMin, setSecYearMin] = useState(0);
  const [secYearMax, setSecYearMax] = useState(0);
  const [secTrendMin, setSecTrendMin] = useState(0);
  const [secTrendMax, setSecTrendMax] = useState(0);

  const [selectedReport, setSelectedReport] = useState(null);

  // Reports the user manually pulled out of the analysis (outliers, bad
  // data, whatever) — a set of report_date strings. Independent of the
  // secondary filters: it survives filter changes and only resets on a
  // fresh "Analizar" fetch, since it's about specific reports, not a rule.
  const [excludedReports, setExcludedReports] = useState(() => new Set());

  function excludeReport(reportDate) {
    setExcludedReports((prev) => new Set(prev).add(reportDate));
  }
  function restoreReport(reportDate) {
    setExcludedReports((prev) => {
      const next = new Set(prev);
      next.delete(reportDate);
      return next;
    });
  }
  function restoreAllReports() {
    setExcludedReports(new Set());
  }

  useEffect(() => {
    fetch(`${API_BASE}/api/stocks`)
      .then((res) => res.json())
      .then((data) => {
        setStocks(data);
        if (data.length > 0) setSymbol(data[0].symbol);
      })
      .catch(() => setError("No se pudo conectar con el backend"));
  }, []);

  // Domains stay pinned to the full initial fetch — they don't shrink as
  // reports get excluded, so the range strips' axes never shift underfoot
  // while you're picking outliers to remove.
  const yearDomain = useMemo(() => (result ? computeYearDomain(result.reactions) : null), [result]);
  const trendDomain = useMemo(() => (result ? computeTrendDomain(result.reactions) : null), [result]);

  // Everything below this — filters, counts, stats, the table, the strips —
  // is computed off analyzableReactions instead of the raw fetch, so a
  // manually excluded report disappears from the whole analysis at once.
  const analyzableReactions = useMemo(() => {
    if (!result) return [];
    return result.reactions.filter((r) => !excludedReports.has(r.report_date));
  }, [result, excludedReports]);

  function currentFilterState() {
    return {
      requireBeat: secRequireBeat,
      requireSector: secRequireSector,
      yearMin: secYearMin,
      yearMax: secYearMax,
      yearDomain,
      trendMin: secTrendMin,
      trendMax: secTrendMax,
      trendDomain,
    };
  }

  const filteredReactions = useMemo(() => {
    return applySecondaryFilters(analyzableReactions, currentFilterState());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analyzableReactions, secRequireBeat, secRequireSector, secYearMin, secYearMax, secTrendMin, secTrendMax, yearDomain, trendDomain]);

  const stats = useMemo(() => computeStats(filteredReactions), [filteredReactions]);

  const hasActiveSecondaryFilters =
    secRequireBeat !== "" ||
    secRequireSector !== "" ||
    (yearDomain && (secYearMin > yearDomain.min + RANGE_EPSILON || secYearMax < yearDomain.max - RANGE_EPSILON)) ||
    (trendDomain && (secTrendMin > trendDomain.min + RANGE_EPSILON || secTrendMax < trendDomain.max - RANGE_EPSILON));

  function clearSecondaryFilters() {
    setSecRequireBeat("");
    setSecRequireSector("");
    if (yearDomain) {
      setSecYearMin(yearDomain.min);
      setSecYearMax(yearDomain.max);
    }
    if (trendDomain) {
      setSecTrendMin(trendDomain.min);
      setSecTrendMax(trendDomain.max);
    }
  }

  // Toggle-button labels show a live count of how many reports would match
  // if you picked that option, holding every OTHER active secondary filter
  // constant — so the buttons stay honest about what clicking them will do.
  const beatOptionSubset = useMemo(() => {
    return applySecondaryFilters(analyzableReactions, { ...currentFilterState(), requireBeat: "" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analyzableReactions, secRequireSector, secYearMin, secYearMax, secTrendMin, secTrendMax, yearDomain, trendDomain]);

  const sectorOptionSubset = useMemo(() => {
    return applySecondaryFilters(analyzableReactions, { ...currentFilterState(), requireSector: "" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analyzableReactions, secRequireBeat, secYearMin, secYearMax, secTrendMin, secTrendMax, yearDomain, trendDomain]);

  const beatOptions = useMemo(
    () =>
      BEAT_TOGGLE_OPTIONS.map((o) => {
        const n =
          o.value === ""
            ? beatOptionSubset.length
            : beatOptionSubset.filter((r) => r.surprise_pct != null && String(r.surprise_pct > 0) === o.value).length;
        return { ...o, label: `${o.label} (${n})` };
      }),
    [beatOptionSubset]
  );

  const sectorOptions = useMemo(
    () =>
      SECTOR_TOGGLE_OPTIONS.map((o) => {
        const n =
          o.value === ""
            ? sectorOptionSubset.length
            : sectorOptionSubset.filter(
                (r) => r.excess_reaction_day_return != null && String(r.excess_reaction_day_return > 0) === o.value
              ).length;
        return { ...o, label: `${o.label} (${n})` };
      }),
    [sectorOptionSubset]
  );

  // The range strips plot every report at its true position (stable dots,
  // regardless of the strip's own selection) but fade out points that the
  // OTHER active secondary filters already exclude, so dragging one range
  // shows its effect against what's really still on the table.
  const yearStripSubset = useMemo(() => {
    if (!yearDomain) return [];
    return applySecondaryFilters(analyzableReactions, { ...currentFilterState(), yearMin: yearDomain.min, yearMax: yearDomain.max });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analyzableReactions, secRequireBeat, secRequireSector, secTrendMin, secTrendMax, yearDomain, trendDomain]);

  const trendStripSubset = useMemo(() => {
    if (!trendDomain) return [];
    return applySecondaryFilters(analyzableReactions, { ...currentFilterState(), trendMin: trendDomain.min, trendMax: trendDomain.max });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analyzableReactions, secRequireBeat, secRequireSector, secYearMin, secYearMax, yearDomain, trendDomain]);

  // Manually excluded reports simply don't appear as dots — same as they
  // don't appear in the table — rather than showing as a third, "excluded"
  // visual state on top of the existing active/filtered-out one.
  const yearStripPoints = useMemo(() => {
    const includedDates = new Set(yearStripSubset.map((r) => r.report_date));
    return analyzableReactions.map((r) => ({ value: reportYear(r), active: includedDates.has(r.report_date) }));
  }, [analyzableReactions, yearStripSubset]);

  const trendStripPoints = useMemo(() => {
    const includedDates = new Set(trendStripSubset.map((r) => r.report_date));
    return analyzableReactions
      .filter((r) => r.trend_before_pct != null)
      .map((r) => ({ value: r.trend_before_pct, active: includedDates.has(r.report_date) }));
  }, [analyzableReactions, trendStripSubset]);

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
      setExcludedReports(new Set());
      setSecRequireBeat("");
      setSecRequireSector("");
      if (data.reactions.length > 0) {
        const yd = computeYearDomain(data.reactions);
        setSecYearMin(yd.min);
        setSecYearMax(yd.max);
        const td = computeTrendDomain(data.reactions);
        if (td) {
          setSecTrendMin(td.min);
          setSecTrendMax(td.max);
        }
      }
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
                      <ToggleGroup value={secRequireBeat} onChange={setSecRequireBeat} options={beatOptions} />
                    </div>

                    <div className="field">
                      <label>Excedió al sector ese día</label>
                      <ToggleGroup value={secRequireSector} onChange={setSecRequireSector} options={sectorOptions} />
                    </div>

                    <div className="field">
                      <label>Año del reporte</label>
                      {yearDomain && yearDomain.min !== yearDomain.max ? (
                        <RangeStrip
                          points={yearStripPoints}
                          domainMin={yearDomain.min}
                          domainMax={yearDomain.max}
                          selectedMin={secYearMin}
                          selectedMax={secYearMax}
                          onChange={(min, max) => {
                            setSecYearMin(Math.round(min));
                            setSecYearMax(Math.round(max));
                          }}
                          formatValue={(v) => Math.round(v).toString()}
                        />
                      ) : (
                        <p className="field-hint">Todos los reportes son del mismo año.</p>
                      )}
                    </div>

                    <div className="field">
                      <label>Rango de tendencia previa ({TREND_WINDOW_LABELS[result.trend_window_days]})</label>
                      {trendDomain ? (
                        <RangeStrip
                          points={trendStripPoints}
                          domainMin={trendDomain.min}
                          domainMax={trendDomain.max}
                          selectedMin={secTrendMin}
                          selectedMax={secTrendMax}
                          onChange={(min, max) => {
                            setSecTrendMin(min);
                            setSecTrendMax(max);
                          }}
                          formatValue={(v) => `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`}
                        />
                      ) : (
                        <p className="field-hint">Sin datos de tendencia disponibles.</p>
                      )}
                    </div>
                  </div>
                </div>

                {excludedReports.size > 0 && (
                  <div className="card earnings-secondary-filters">
                    <div className="secondary-filters-header">
                      <h2 className="sidebar-title">Excluidos manualmente ({excludedReports.size})</h2>
                      <button type="button" className="link-button" onClick={restoreAllReports}>
                        Restaurar todos
                      </button>
                    </div>
                    <p className="field-hint" style={{ marginBottom: "0.75rem" }}>
                      Fuera de la tabla, las estadísticas, los filtros y el gráfico hasta que los restaures. Clic en
                      uno para restaurarlo.
                    </p>
                    <div className="toggle-group">
                      {[...excludedReports].sort().map((date) => (
                        <button
                          key={date}
                          type="button"
                          className="toggle-button"
                          onClick={() => restoreReport(date)}
                          title="Volver a incluir en el análisis"
                        >
                          {date} ×
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {filteredReactions.length === 0 ? (
                  <p className="result-summary">Ningún reporte cumple estos filtros secundarios.</p>
                ) : (
                  <>
                    <p className="result-summary">
                      <strong>{result.symbol}</strong>
                      {hasActiveSecondaryFilters && (
                        <> ({filteredReactions.length} de {analyzableReactions.length} reportes tras los filtros secundarios)</>
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
                      Sobre los reportes de la tabla (ya filtrados, incluido el rango de tendencia elegido arriba):
                      ¿subió en el gap de apertura (overnight/pre-market/after-hours) y también cerró en positivo ese
                      día?
                    </p>

                    <div
                      className="tiles momentum-tiles"
                      style={{ gridTemplateColumns: "1fr 1fr", marginBottom: "1.25rem" }}
                    >
                      <TrendReactionBlock label="Venía al alza" stats={stats.trendUpStats} />
                      <TrendReactionBlock label="Venía a la baja" stats={stats.trendDownStats} />
                    </div>

                    <p className="field-hint" style={{ marginBottom: "0.5rem" }}>
                      Clic en una fila para ver ese reporte en el gráfico · fondo verde/rojo = beat/miss · borde
                      izquierdo verde/rojo = venía subiendo/bajando antes del reporte · × para sacarlo del análisis.
                    </p>

                    <div className="earnings-table-wrap card">
                      <table className="earnings-table">
                        <thead>
                          <tr>
                            <th></th>
                            <th>Fecha reporte</th>
                            <th>EPS real</th>
                            <th>EPS estimado</th>
                            <th>Sorpresa EPS</th>
                            <th>Tendencia previa ({TREND_WINDOW_LABELS[result.trend_window_days]})</th>
                            <th>Fecha reacción</th>
                            <th>Apertura reacción</th>
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
                            const rowClasses = [
                              clickable && "earnings-row-clickable",
                              selected && "earnings-row-selected",
                              r.surprise_pct != null && (r.surprise_pct > 0 ? "earnings-row-beat" : r.surprise_pct < 0 ? "earnings-row-miss" : null),
                              r.trend_before_pct != null &&
                                (r.trend_before_pct > 0 ? "earnings-row-trend-up" : "earnings-row-trend-down"),
                            ]
                              .filter(Boolean)
                              .join(" ");
                            return (
                              <tr key={r.report_date} onClick={() => clickable && setSelectedReport(r.report_date)} className={rowClasses}>
                                <td onClick={(e) => e.stopPropagation()}>
                                  <button
                                    type="button"
                                    className="row-exclude-button"
                                    title="Quitar del análisis"
                                    onClick={() => excludeReport(r.report_date)}
                                  >
                                    ×
                                  </button>
                                </td>
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
                                  {r.next_open_price != null ? (
                                    <>
                                      ${r.next_open_price.toFixed(2)} <SignedPct value={r.aftermarket_gap_pct} />
                                    </>
                                  ) : (
                                    "—"
                                  )}
                                </td>
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
                            <PriceWindowChart priceWindow={selected.price_window} reportDate={selected.report_date} />
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
