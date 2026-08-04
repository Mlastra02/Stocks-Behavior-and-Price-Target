import { useMemo, useState } from "react";

const WIDTH = 900;
const HEIGHT = 340;
const MARGIN = { top: 16, right: 16, bottom: 28, left: 64 };

function formatDate(iso) {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("es", { day: "2-digit", month: "short", year: "2-digit" });
}

function formatPrice(value) {
  return `$${value.toFixed(2)}`;
}

// Builds an SVG path from a series that may have leading nulls (moving
// averages don't exist until their window fills) — breaks the line instead
// of drawing a spurious segment through the gap.
function linePath(chart, xAt, yAt, key) {
  let path = "";
  let drawing = false;
  chart.forEach((p, i) => {
    const v = p[key];
    if (v == null) {
      drawing = false;
      return;
    }
    path += `${drawing ? "L" : "M"}${xAt(i)},${yAt(v)} `;
    drawing = true;
  });
  return path.trim();
}

export default function TechnicalChart({ chart, earningsDates }) {
  const [selectedIndex, setSelectedIndex] = useState(chart.length > 0 ? chart.length - 1 : null);

  const plot = useMemo(() => {
    if (!chart || chart.length < 2) return null;

    const allValues = chart.flatMap((p) => [p.price, p.sma50, p.sma200].filter((v) => v != null));
    const minPrice = Math.min(...allValues);
    const maxPrice = Math.max(...allValues);
    const pad = (maxPrice - minPrice) * 0.08 || maxPrice * 0.02;
    const yMin = minPrice - pad;
    const yMax = maxPrice + pad;

    const innerWidth = WIDTH - MARGIN.left - MARGIN.right;
    const innerHeight = HEIGHT - MARGIN.top - MARGIN.bottom;
    const xAt = (i) => MARGIN.left + (i / (chart.length - 1)) * innerWidth;
    const yAt = (price) => MARGIN.top + innerHeight - ((price - yMin) / (yMax - yMin)) * innerHeight;

    const earningsSet = new Set(earningsDates);
    const earningsIndices = chart.map((p, i) => (earningsSet.has(p.date) ? i : -1)).filter((i) => i >= 0);

    const yTicks = [yMin + pad, (yMin + yMax) / 2, yMax - pad];

    return {
      xAt,
      yAt,
      pricePath: linePath(chart, xAt, yAt, "price"),
      sma50Path: linePath(chart, xAt, yAt, "sma50"),
      sma200Path: linePath(chart, xAt, yAt, "sma200"),
      earningsIndices,
      yTicks,
      innerHeight,
    };
  }, [chart, earningsDates]);

  if (!plot) {
    return <p className="field-hint">No hay suficientes datos de precio para graficar esta ventana.</p>;
  }

  const { xAt, yAt, pricePath, sma50Path, sma200Path, earningsIndices, yTicks, innerHeight } = plot;

  function handleClick(e) {
    const svg = e.currentTarget;
    const rect = svg.getBoundingClientRect();
    const scaleX = WIDTH / rect.width;
    const mouseX = (e.clientX - rect.left) * scaleX;
    const innerWidth = WIDTH - MARGIN.left - MARGIN.right;
    const ratio = Math.min(1, Math.max(0, (mouseX - MARGIN.left) / innerWidth));
    setSelectedIndex(Math.round(ratio * (chart.length - 1)));
  }

  const selected = selectedIndex != null ? chart[selectedIndex] : null;
  const selectedIsEarnings = selected && earningsDates.includes(selected.date);

  return (
    <div className="technical-chart">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="price-chart-svg technical-chart-svg"
        onClick={handleClick}
      >
        {yTicks.map((price, i) => (
          <g key={i}>
            <line x1={MARGIN.left} x2={WIDTH - MARGIN.right} y1={yAt(price)} y2={yAt(price)} className="price-chart-gridline" />
            <text x={MARGIN.left - 8} y={yAt(price)} className="price-chart-axis-label" textAnchor="end" dy="0.32em">
              {formatPrice(price)}
            </text>
          </g>
        ))}

        <text x={xAt(0)} y={HEIGHT - 6} className="price-chart-axis-label" textAnchor="start">
          {formatDate(chart[0].date)}
        </text>
        <text x={xAt(chart.length - 1)} y={HEIGHT - 6} className="price-chart-axis-label" textAnchor="end">
          {formatDate(chart[chart.length - 1].date)}
        </text>

        {earningsIndices.map((i) => (
          <line
            key={i}
            x1={xAt(i)}
            x2={xAt(i)}
            y1={MARGIN.top}
            y2={MARGIN.top + innerHeight}
            className="technical-chart-earnings-line"
          />
        ))}

        <path d={sma200Path} className="technical-chart-sma200-line" />
        <path d={sma50Path} className="technical-chart-sma50-line" />
        <path d={pricePath} className="price-chart-line" />

        {selectedIndex != null && (
          <>
            <line
              x1={xAt(selectedIndex)}
              x2={xAt(selectedIndex)}
              y1={MARGIN.top}
              y2={MARGIN.top + innerHeight}
              className="price-chart-crosshair"
            />
            <circle cx={xAt(selectedIndex)} cy={yAt(selected.price)} r="4" className="price-chart-dot" strokeWidth="2" />
          </>
        )}
      </svg>

      <div className="technical-chart-legend">
        <span><i className="technical-chart-dot technical-chart-dot-price" /> Precio</span>
        <span><i className="technical-chart-dot technical-chart-dot-sma50" /> SMA(50)</span>
        <span><i className="technical-chart-dot technical-chart-dot-sma200" /> SMA(200)</span>
        <span><i className="technical-chart-dot technical-chart-dot-earnings" /> Earnings</span>
      </div>

      {selected && (
        <div className="card technical-chart-detail">
          <p className="sidebar-title" style={{ marginBottom: "0.5rem" }}>
            {formatDate(selected.date)}
            {selectedIsEarnings && <span className="price-chart-reaction-tag"> · reporte de earnings</span>}
          </p>
          <div className="technical-chart-detail-grid">
            <div>
              <p className="field-hint">Precio</p>
              <strong>{formatPrice(selected.price)}</strong>
            </div>
            <div>
              <p className="field-hint">RSI</p>
              <strong>{selected.rsi != null ? selected.rsi.toFixed(0) : "—"}</strong>
            </div>
            <div>
              <p className="field-hint">EMA(20)</p>
              <strong>{selected.ema20 != null ? formatPrice(selected.ema20) : "—"}</strong>
            </div>
            <div>
              <p className="field-hint">SMA(50)</p>
              <strong>{selected.sma50 != null ? formatPrice(selected.sma50) : "—"}</strong>
            </div>
            <div>
              <p className="field-hint">SMA(200)</p>
              <strong>{selected.sma200 != null ? formatPrice(selected.sma200) : "—"}</strong>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
