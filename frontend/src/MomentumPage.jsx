import { useEffect, useState } from "react";
import { API_BASE, pct, TRI_STATE_OPTIONS } from "./api";

const HORIZON_LABELS = { 5: "+1 semana", 10: "+2 semanas", 20: "+1 mes" };

function ReturnStat({ label, value }) {
  if (value == null) return null;
  const positive = value >= 0;
  return (
    <div className="momentum-stat">
      <span className="momentum-stat-label">{label}</span>
      <span className={"momentum-stat-value " + (positive ? "watchlist-upside-positive" : "watchlist-upside-negative")}>
        {positive ? "+" : ""}
        {(value * 100).toFixed(1)}%
      </span>
    </div>
  );
}

export default function MomentumPage() {
  const [stocks, setStocks] = useState([]);
  const [symbol, setSymbol] = useState("");
  const [requireEarnings, setRequireEarnings] = useState("");
  const [requireVolumeAnomaly, setRequireVolumeAnomaly] = useState("");
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
  }, []);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setResult(null);
    setLoading(true);
    try {
      const params = new URLSearchParams({ symbol });
      if (requireEarnings !== "") params.set("require_earnings", requireEarnings);
      if (requireVolumeAnomaly !== "") params.set("require_volume_anomaly", requireVolumeAnomaly);
      const res = await fetch(`${API_BASE}/api/momentum-analysis?${params}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Error desconocido");
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  const moveDirection = result && result.current_move_pct >= 0 ? "subió" : "bajó";
  const ctx = result?.analyst_context;

  return (
    <div className="layout momentum-layout">
      <div className="app">
        <header className="app-header">
          <p className="eyebrow">Momentum Post-Evento</p>
          <h1>¿Después de un salto así, qué pasó históricamente?</h1>
          <p className="subtitle">
            Detecta sola la racha reciente de la acción (no hace falta elegir una ventana), busca movimientos
            históricos de magnitud parecida — sin importar cuántos días tomaron — y muestra qué pasó después. No
            es Black-Scholes ni Montecarlo: es un estudio histórico directo.
          </p>
        </header>

        <form onSubmit={handleSubmit} className="card form">
          <div className="field">
            <label htmlFor="momentum_symbol">Acción</label>
            <select id="momentum_symbol" value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              {stocks.map((s) => (
                <option key={s.symbol} value={s.symbol}>
                  {s.symbol} — {s.name}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label htmlFor="require_earnings">Episodios que coincidieron con earnings</label>
            <select id="require_earnings" value={requireEarnings} onChange={(e) => setRequireEarnings(e.target.value)}>
              {TRI_STATE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label htmlFor="require_volume">Episodios con volumen anómalo</label>
            <select
              id="require_volume"
              value={requireVolumeAnomaly}
              onChange={(e) => setRequireVolumeAnomaly(e.target.value)}
            >
              {TRI_STATE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <p className="field-hint">
              Filtrar reduce la muestra — algunas combinaciones pueden no encontrar ningún episodio.
            </p>
          </div>

          <button type="submit" disabled={loading}>
            {loading ? "Analizando…" : "Analizar racha actual"}
          </button>
        </form>

        {error && <p className="error">{error}</p>}

        {result && (
          <div className="result">
            <p className="result-summary">
              <strong>{result.symbol}</strong> {moveDirection}{" "}
              <strong>
                {result.current_move_pct >= 0 ? "+" : ""}
                {(result.current_move_pct * 100).toFixed(1)}%
              </strong>{" "}
              en los últimos {result.detected_window_days} días hábiles (precio actual: $
              {result.current_price.toFixed(2)}) — esa fue la racha que detectó automáticamente como la más
              relevante.
            </p>

            <p className="field-hint" style={{ marginBottom: "1.25rem" }}>
              Contexto de esta racha: {result.current_coincided_with_earnings ? "coincidió con earnings" : "sin earnings cerca"}
              {" · "}
              {result.current_volume_anomaly
                ? `volumen anómalo (${result.current_volume_ratio.toFixed(1)}x el promedio)`
                : "volumen normal"}
            </p>

            {ctx && ctx.target_price != null && (
              <div className="card momentum-analyst-card">
                <p className="sidebar-title" style={{ marginBottom: "0.5rem" }}>
                  Precio objetivo de analistas: ${ctx.target_price.toFixed(2)}
                </p>
                {ctx.already_above_target ? (
                  <p className="error">
                    El precio ya está por encima del objetivo promedio de analistas — ya no queda upside implícito
                    a 12 meses según ese dato.
                  </p>
                ) : (
                  <p className="field-hint">
                    Upside implícito ahora: <strong className="watchlist-upside-positive">{pct(ctx.upside_now_pct)}</strong>
                    {ctx.upside_before_move_pct != null && (
                      <>
                        {" "}
                        (antes de esta racha era{" "}
                        <strong>{pct(ctx.upside_before_move_pct)}</strong> — la racha ya consumió{" "}
                        <strong>
                          {((ctx.upside_before_move_pct - ctx.upside_now_pct) * 100).toFixed(1)} puntos
                        </strong>{" "}
                        de ese upside anual)
                      </>
                    )}
                    .
                  </p>
                )}
              </div>
            )}

            {result.episodes_found === 0 ? (
              <p className="result-summary">
                No se encontraron movimientos similares (misma dirección) en los últimos ~2 años de historial —
                este parece ser un movimiento sin precedente reciente para esta acción.
              </p>
            ) : (
              <>
                <p className="result-summary">
                  {result.used_fallback ? (
                    <>
                      Ningún movimiento histórico llegó a esta magnitud (se buscaban de al menos{" "}
                      {(result.threshold_pct * 100).toFixed(1)}%). Mostrando los {result.episodes_found} movimientos
                      más grandes en la misma dirección que sí ocurrieron, aunque menores — cada uno con la
                      duración que realmente tuvo:
                    </>
                  ) : (
                    <>
                      Se encontraron {result.episodes_found} movimientos históricos de magnitud comparable (≥
                      {(result.threshold_pct * 100).toFixed(1)}%):
                    </>
                  )}
                </p>

                <ul className="momentum-episode-list">
                  {result.episode_details.map((e) => (
                    <li key={e.date}>
                      {e.date}: {e.move_pct >= 0 ? "+" : ""}
                      {(e.move_pct * 100).toFixed(1)}% en {e.window_days} días
                      {result.used_fallback && e.pct_of_current != null && (
                        <span className="field-hint"> — {(e.pct_of_current * 100).toFixed(0)}% del movimiento actual</span>
                      )}
                      <span className="field-hint">
                        {" "}
                        · {e.coincided_with_earnings ? "earnings" : "sin earnings"}
                        {" · "}
                        {e.volume_anomaly ? `volumen ${e.volume_ratio.toFixed(1)}x` : "volumen normal"}
                      </span>
                    </li>
                  ))}
                </ul>

                {result.low_confidence && (
                  <p className="error">
                    Muestra pequeña ({result.episodes_found} episodios) — estos resultados son orientativos, no
                    estadísticamente robustos. No los tomes como una predicción confiable.
                  </p>
                )}

                <div className="tiles momentum-tiles">
                  {[5, 10, 20].map((horizon) => {
                    const stats = result.forward_windows[String(horizon)];
                    if (!stats || stats.n === 0) return null;
                    return (
                      <div className="tile" key={horizon}>
                        <p className="tile-label">
                          <span className="tile-dot" style={{ background: "var(--series-1)" }} />
                          {HORIZON_LABELS[horizon]}
                        </p>
                        <p className="tile-value">{pct(stats.pct_positive)}</p>
                        <p className="field-hint">de {stats.n} episodios terminaron en positivo</p>
                        <div className="momentum-stats">
                          <ReturnStat label="Promedio" value={stats.mean_return} />
                          <ReturnStat label="Mediana" value={stats.median_return} />
                          <ReturnStat label="Mínimo" value={stats.min_return} />
                          <ReturnStat label="Máximo" value={stats.max_return} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
