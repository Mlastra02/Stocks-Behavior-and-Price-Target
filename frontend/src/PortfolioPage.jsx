import { useEffect, useState } from "react";
import { API_BASE, pct } from "./api";
import TechnicalChart from "./TechnicalChart";

const REFRESH_INTERVAL_MS = 60_000;

const CROSS_LABELS = {
  golden_recent: "Golden cross reciente",
  death_recent: "Death cross reciente",
  approaching_golden: "Posible golden cross cerca",
  approaching_death: "Posible death cross cerca",
  bullish: "Alineación alcista (SMA50 > SMA200)",
  bearish: "Alineación bajista (SMA50 < SMA200)",
  none: "Sin datos suficientes",
};

const VOLUME_LABELS = {
  confirmacion_alcista: "Confirmación alcista",
  advertencia_alcista: "Advertencia — suba sin respaldo de volumen",
  confirmacion_bajista: "Confirmación bajista",
  advertencia_bajista: "Posible agotamiento bajista",
};

function formatMoney(value) {
  return value == null ? "—" : `$${value.toLocaleString("es", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function SignedPct({ value }) {
  if (value == null) return <span className="field-hint">—</span>;
  const positive = value >= 0;
  return (
    <span className={positive ? "watchlist-upside-positive" : "watchlist-upside-negative"}>
      {positive ? "+" : ""}
      {(value * 100).toFixed(2)}%
    </span>
  );
}

function BandTag({ band }) {
  if (!band) return <span className="field-hint">—</span>;
  return <span className="band-tag">{band}</span>;
}

export default function PortfolioPage() {
  const [stocks, setStocks] = useState([]);
  const [portfolio, setPortfolio] = useState(null);
  const [portfolioError, setPortfolioError] = useState(null);
  const [portfolioLoading, setPortfolioLoading] = useState(true);

  const [selectedSymbol, setSelectedSymbol] = useState("");
  const [technical, setTechnical] = useState(null);
  const [technicalError, setTechnicalError] = useState(null);
  const [technicalLoading, setTechnicalLoading] = useState(false);

  const [lastUpdated, setLastUpdated] = useState(null);
  const [formError, setFormError] = useState(null);

  const [addingNew, setAddingNew] = useState(false);
  const [newSymbol, setNewSymbol] = useState("");
  const [newQuantity, setNewQuantity] = useState("");
  const [newAvgCost, setNewAvgCost] = useState("");

  const [editingSymbol, setEditingSymbol] = useState(null);
  const [editQuantity, setEditQuantity] = useState("");
  const [editAvgCost, setEditAvgCost] = useState("");

  useEffect(() => {
    fetch(`${API_BASE}/api/stocks`)
      .then((res) => res.json())
      .then(setStocks)
      .catch(() => {});
  }, []);

  async function fetchPortfolio() {
    try {
      const res = await fetch(`${API_BASE}/api/portfolio`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Error desconocido");
      setPortfolio(data);
      setPortfolioError(null);
    } catch (err) {
      setPortfolioError(err.message);
    } finally {
      setPortfolioLoading(false);
    }
  }

  async function fetchTechnical(symbol) {
    if (!symbol) return;
    setTechnicalLoading(true);
    try {
      const params = new URLSearchParams({ symbol, chart_months: "24" });
      const res = await fetch(`${API_BASE}/api/technical-analysis?${params}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Error desconocido");
      setTechnical(data);
      setTechnicalError(null);
    } catch (err) {
      setTechnicalError(err.message);
    } finally {
      setTechnicalLoading(false);
    }
  }

  useEffect(() => {
    fetchPortfolio();
  }, []);

  // Once holdings load, default the analysis panel to the biggest holding
  // (or the first tracked stock if the portfolio is still empty).
  useEffect(() => {
    if (selectedSymbol || portfolioLoading) return;
    if (portfolio && portfolio.holdings.length > 0) {
      setSelectedSymbol(portfolio.holdings[0].symbol);
    } else if (stocks.length > 0) {
      setSelectedSymbol(stocks[0].symbol);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [portfolio, stocks, portfolioLoading]);

  useEffect(() => {
    if (selectedSymbol) fetchTechnical(selectedSymbol);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSymbol]);

  // Not tick-by-tick real time — yfinance's free data has its own delay —
  // but the page refreshes itself periodically instead of only on load.
  useEffect(() => {
    const id = setInterval(() => {
      fetchPortfolio();
      if (selectedSymbol) fetchTechnical(selectedSymbol);
      setLastUpdated(new Date());
    }, REFRESH_INTERVAL_MS);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSymbol]);

  useEffect(() => {
    if (portfolio) setLastUpdated(new Date());
  }, [portfolio]);

  function manualRefresh() {
    fetchPortfolio();
    if (selectedSymbol) fetchTechnical(selectedSymbol);
  }

  async function submitNewHolding(e) {
    e.preventDefault();
    setFormError(null);
    if (!newSymbol || newQuantity === "" || newAvgCost === "") {
      setFormError("Completá acción, cantidad y precio promedio.");
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/api/portfolio/holdings/${newSymbol}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ quantity: Number(newQuantity), avg_cost: Number(newAvgCost) }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Error desconocido");
      setPortfolio(data);
      setAddingNew(false);
      setNewSymbol("");
      setNewQuantity("");
      setNewAvgCost("");
    } catch (err) {
      setFormError(err.message);
    }
  }

  function startEditing(holding) {
    setFormError(null);
    setEditingSymbol(holding.symbol);
    setEditQuantity(String(holding.quantity));
    setEditAvgCost(String(holding.avg_cost));
  }

  async function submitEdit(symbol) {
    setFormError(null);
    try {
      const res = await fetch(`${API_BASE}/api/portfolio/holdings/${symbol}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ quantity: Number(editQuantity), avg_cost: Number(editAvgCost) }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Error desconocido");
      setPortfolio(data);
      setEditingSymbol(null);
    } catch (err) {
      setFormError(err.message);
    }
  }

  async function removeHolding(symbol) {
    if (!window.confirm(`¿Quitar ${symbol} del portafolio?`)) return;
    const res = await fetch(`${API_BASE}/api/portfolio/holdings/${symbol}`, { method: "DELETE" });
    const data = await res.json();
    setPortfolio(data);
    if (editingSymbol === symbol) setEditingSymbol(null);
  }

  const availableToAdd = stocks.filter((s) => !portfolio?.holdings.some((h) => h.symbol === s.symbol));

  return (
    <div className="layout momentum-layout">
      <div className="app">
        <header className="app-header">
          <p className="eyebrow">Mi Portafolio</p>
          <h1>Tus acciones, en vivo</h1>
          <p className="subtitle">
            Cargá cuánto tenés de cada acción y a qué precio promedio la compraste — el valor, la ganancia y el
            análisis técnico se actualizan solos cada minuto con datos de Yahoo (no es tick a tick, tiene el mismo
            delay que el resto de la app).
          </p>
        </header>

        <div className="card earnings-secondary-filters">
          <div className="secondary-filters-header">
            <h2 className="sidebar-title">Portafolio</h2>
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
              {lastUpdated && (
                <span className="field-hint">Actualizado {lastUpdated.toLocaleTimeString("es")}</span>
              )}
              <button type="button" className="link-button" onClick={manualRefresh}>
                Actualizar ahora
              </button>
            </div>
          </div>

          {portfolioError && <p className="error">{portfolioError}</p>}

          {portfolioLoading ? (
            <p className="field-hint">Cargando…</p>
          ) : !portfolio || portfolio.holdings.length === 0 ? (
            <p className="field-hint" style={{ marginBottom: "1rem" }}>
              {portfolioError ? "No se pudo cargar el portafolio." : "Todavía no cargaste ninguna acción."}
            </p>
          ) : (
            <>
              <p className="result-summary" style={{ marginBottom: "1rem" }}>
                Valor total: <strong>{formatMoney(portfolio.total_value)}</strong>
              </p>
              <ul className="watchlist">
                {portfolio.holdings.map((h) => (
                  <li key={h.symbol} className="watchlist-row">
                    {editingSymbol === h.symbol ? (
                      <div style={{ display: "flex", gap: "0.6rem", alignItems: "center", flexWrap: "wrap", width: "100%" }}>
                        <strong>{h.symbol}</strong>
                        <input
                          type="number"
                          value={editQuantity}
                          onChange={(e) => setEditQuantity(e.target.value)}
                          placeholder="Cantidad"
                          style={{ width: "100px" }}
                        />
                        <input
                          type="number"
                          value={editAvgCost}
                          onChange={(e) => setEditAvgCost(e.target.value)}
                          placeholder="Precio promedio"
                          style={{ width: "120px" }}
                        />
                        <button type="button" className="link-button" onClick={() => submitEdit(h.symbol)}>
                          Guardar
                        </button>
                        <button type="button" className="link-button" onClick={() => setEditingSymbol(null)}>
                          Cancelar
                        </button>
                      </div>
                    ) : (
                      <>
                        <div className="watchlist-symbol">
                          <span className="watchlist-ticker">{h.symbol}</span>
                          <span className="watchlist-name">{h.name}</span>
                          {portfolio.total_value > 0 && (
                            <span className="field-hint">{pct(h.allocation_pct)} del portafolio</span>
                          )}
                        </div>
                        <div className="watchlist-prices">
                          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "0.15rem" }}>
                            <span>{formatMoney(h.current_value)}</span>
                            <span className="watchlist-upside">
                              <SignedPct value={h.gain_pct} />
                            </span>
                          </div>
                          <button type="button" className="row-exclude-button" title="Editar" onClick={() => startEditing(h)}>
                            ✎
                          </button>
                          <button type="button" className="row-exclude-button" title="Quitar" onClick={() => removeHolding(h.symbol)}>
                            ×
                          </button>
                        </div>
                      </>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}

          {formError && <p className="error">{formError}</p>}

          {addingNew ? (
            <form onSubmit={submitNewHolding} style={{ display: "flex", gap: "0.6rem", alignItems: "center", flexWrap: "wrap", marginTop: "1rem" }}>
              <select value={newSymbol} onChange={(e) => setNewSymbol(e.target.value)}>
                <option value="">Acción…</option>
                {availableToAdd.map((s) => (
                  <option key={s.symbol} value={s.symbol}>
                    {s.symbol} — {s.name}
                  </option>
                ))}
              </select>
              <input
                type="number"
                value={newQuantity}
                onChange={(e) => setNewQuantity(e.target.value)}
                placeholder="Cantidad"
                style={{ width: "100px" }}
              />
              <input
                type="number"
                value={newAvgCost}
                onChange={(e) => setNewAvgCost(e.target.value)}
                placeholder="Precio promedio"
                style={{ width: "130px" }}
              />
              <button type="submit">Agregar</button>
              <button type="button" className="link-button" onClick={() => setAddingNew(false)}>
                Cancelar
              </button>
            </form>
          ) : (
            <button type="button" className="link-button" style={{ marginTop: "1rem" }} onClick={() => setAddingNew(true)}>
              + Agregar acción
            </button>
          )}
        </div>

        <div className="card earnings-secondary-filters">
          <div className="secondary-filters-header">
            <h2 className="sidebar-title">Análisis por acción</h2>
          </div>
          <div className="field" style={{ marginBottom: "1rem" }}>
            <label htmlFor="ta_symbol">Acción</label>
            <select id="ta_symbol" value={selectedSymbol} onChange={(e) => setSelectedSymbol(e.target.value)}>
              {stocks.map((s) => (
                <option key={s.symbol} value={s.symbol}>
                  {s.symbol} — {s.name}
                </option>
              ))}
            </select>
          </div>

          {technicalError && <p className="error">{technicalError}</p>}

          {technicalLoading && !technical ? (
            <p className="field-hint">Cargando…</p>
          ) : (
            technical && (
              <>
                <p className="result-summary">
                  <strong>{technical.symbol}</strong> — {formatMoney(technical.current_price)} al {technical.as_of_date}
                  {technical.price_target != null && (
                    <>
                      {" "}
                      · precio objetivo de analistas {formatMoney(technical.price_target)} (
                      <SignedPct value={technical.upside_pct} /> de upside)
                    </>
                  )}
                </p>

                <div className="tiles momentum-tiles" style={{ gridTemplateColumns: "repeat(3, 1fr)", marginTop: "1rem" }}>
                  <div className="tile">
                    <p className="tile-label">
                      <span className="tile-dot" style={{ background: "var(--series-1)" }} />
                      RSI (14) — <BandTag band={technical.rsi.band} />
                    </p>
                    <p className="tile-value">{technical.rsi.value != null ? technical.rsi.value.toFixed(0) : "—"}</p>
                    <p className="field-hint">{technical.rsi.explanation}</p>
                  </div>
                  <div className="tile">
                    <p className="tile-label">
                      <span className="tile-dot" style={{ background: "var(--series-1)" }} />
                      EMA(20) — <BandTag band={technical.ema_short.band} />
                    </p>
                    <p className="tile-value">{formatMoney(technical.ema_short.value)}</p>
                    <p className="field-hint">{technical.ema_short.explanation}</p>
                  </div>
                  <div className="tile">
                    <p className="tile-label">
                      <span className="tile-dot" style={{ background: "var(--series-1)" }} />
                      SMA(50) — <BandTag band={technical.sma_medium.band} />
                    </p>
                    <p className="tile-value">{formatMoney(technical.sma_medium.value)}</p>
                    <p className="field-hint">{technical.sma_medium.explanation}</p>
                  </div>
                </div>

                <div className="tile" style={{ marginTop: "1rem" }}>
                  <p className="tile-label">
                    <span className="tile-dot" style={{ background: "var(--series-1)" }} />
                    Volumen — {technical.volume_signal.quadrant ? VOLUME_LABELS[technical.volume_signal.quadrant] : "Sin señal clara"}
                  </p>
                  {technical.volume_signal.current_volume != null && (
                    <p className="tile-value">{technical.volume_signal.current_volume.toLocaleString("es")}</p>
                  )}
                  <p className="field-hint">{technical.volume_signal.explanation}</p>
                </div>
              </>
            )
          )}
        </div>

        {technical && (
          <div className="card earnings-secondary-filters">
            <div className="secondary-filters-header">
              <h2 className="sidebar-title">Análisis a largo plazo</h2>
            </div>
            <div className="tile" style={{ marginBottom: "1rem" }}>
              <p className="tile-label">
                <span className="tile-dot" style={{ background: "var(--series-3)" }} />
                {CROSS_LABELS[technical.cross_signal.state] || technical.cross_signal.state}
              </p>
              {technical.cross_signal.sma50 != null && (
                <p className="tile-value">
                  SMA50 {formatMoney(technical.cross_signal.sma50)} vs SMA200 {formatMoney(technical.cross_signal.sma200)}
                </p>
              )}
              <p className="field-hint">{technical.cross_signal.explanation}</p>
            </div>

            <p className="field-hint" style={{ marginBottom: "0.5rem" }}>
              Precio, SMA(50) y SMA(200) de los últimos ~2 años. Las líneas punteadas marcan reportes de earnings —
              clic en cualquier punto del gráfico para ver el precio, RSI, EMA(20), SMA(50) y SMA(200) de esa fecha.
            </p>
            <TechnicalChart key={technical.symbol} chart={technical.chart} earningsDates={technical.earnings_dates} />
          </div>
        )}
      </div>
    </div>
  );
}
