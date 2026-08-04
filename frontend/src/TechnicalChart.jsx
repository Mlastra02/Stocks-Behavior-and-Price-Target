import { useEffect, useMemo, useRef, useState } from "react";

const WIDTH = 900;
const HEIGHT = 340;
const MARGIN = { top: 16, right: 16, bottom: 28, left: 64 };
const DATE_TICK_COUNT = 6;
const DRAG_THRESHOLD_PX = 6; // below this, a pointerdown+up is a click (select point), not a drag (zoom)
const MIN_ZOOM_POINTS = 5; // don't let a zoom collapse to a sliver with nothing to read

function formatDate(iso) {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("es", { day: "2-digit", month: "short", year: "2-digit" });
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

function formatPrice(value) {
  return `$${value.toFixed(2)}`;
}

export default function TechnicalChart({ chart, earningsDates }) {
  const svgRef = useRef(null);
  const [zoomRange, setZoomRange] = useState(null); // { start, end } indices into the full `chart` prop
  const [selectedIndex, setSelectedIndex] = useState(chart.length > 0 ? chart.length - 1 : null);
  const [dragStartX, setDragStartX] = useState(null); // SVG viewBox units
  const [dragCurrentX, setDragCurrentX] = useState(null);

  const visibleChart = useMemo(() => {
    if (!zoomRange) return chart;
    return chart.slice(zoomRange.start, zoomRange.end + 1);
  }, [chart, zoomRange]);

  // A zoom (or reset) changes what "selected" even means positionally —
  // snap back to the latest visible point rather than keep a stale index.
  useEffect(() => {
    setSelectedIndex(visibleChart.length > 0 ? visibleChart.length - 1 : null);
  }, [visibleChart]);

  const plot = useMemo(() => {
    if (!visibleChart || visibleChart.length < 2) return null;

    const allValues = visibleChart.flatMap((p) => [p.price, p.sma50, p.sma200].filter((v) => v != null));
    const minPrice = Math.min(...allValues);
    const maxPrice = Math.max(...allValues);
    const pad = (maxPrice - minPrice) * 0.08 || maxPrice * 0.02;
    const yMin = minPrice - pad;
    const yMax = maxPrice + pad;

    const innerWidth = WIDTH - MARGIN.left - MARGIN.right;
    const innerHeight = HEIGHT - MARGIN.top - MARGIN.bottom;
    const xAt = (i) => MARGIN.left + (i / (visibleChart.length - 1)) * innerWidth;
    const yAt = (price) => MARGIN.top + innerHeight - ((price - yMin) / (yMax - yMin)) * innerHeight;

    const earningsSet = new Set(earningsDates);
    const earningsIndices = visibleChart.map((p, i) => (earningsSet.has(p.date) ? i : -1)).filter((i) => i >= 0);

    const yTicks = [yMin + pad, (yMin + yMax) / 2, yMax - pad];

    const tickCount = Math.min(DATE_TICK_COUNT, visibleChart.length);
    const dateTicks = Array.from({ length: tickCount }, (_, i) => {
      const idx = tickCount === 1 ? 0 : Math.round((i / (tickCount - 1)) * (visibleChart.length - 1));
      return idx;
    }).filter((idx, i, arr) => arr.indexOf(idx) === i); // dedupe if a short window collapses ticks together

    return {
      xAt,
      yAt,
      pricePath: linePath(visibleChart, xAt, yAt, "price"),
      sma50Path: linePath(visibleChart, xAt, yAt, "sma50"),
      sma200Path: linePath(visibleChart, xAt, yAt, "sma200"),
      earningsIndices,
      yTicks,
      dateTicks,
      innerHeight,
    };
  }, [visibleChart, earningsDates]);

  if (!plot) {
    return <p className="field-hint">No hay suficientes datos de precio para graficar esta ventana.</p>;
  }

  const { xAt, yAt, pricePath, sma50Path, sma200Path, earningsIndices, yTicks, dateTicks, innerHeight } = plot;

  function toSvgX(clientX) {
    const rect = svgRef.current.getBoundingClientRect();
    return (clientX - rect.left) * (WIDTH / rect.width);
  }

  function indexAtSvgX(svgX) {
    const innerWidth = WIDTH - MARGIN.left - MARGIN.right;
    const ratio = Math.min(1, Math.max(0, (svgX - MARGIN.left) / innerWidth));
    return Math.round(ratio * (visibleChart.length - 1));
  }

  function handlePointerDown(e) {
    const x = toSvgX(e.clientX);
    setDragStartX(x);
    setDragCurrentX(x);
  }

  function handlePointerMove(e) {
    if (dragStartX == null) return;
    setDragCurrentX(toSvgX(e.clientX));
  }

  function handlePointerUp(e) {
    if (dragStartX == null) return;
    const endX = toSvgX(e.clientX);

    if (Math.abs(endX - dragStartX) < DRAG_THRESHOLD_PX) {
      setSelectedIndex(indexAtSvgX(endX));
    } else {
      const i1 = indexAtSvgX(Math.min(dragStartX, endX));
      const i2 = indexAtSvgX(Math.max(dragStartX, endX));
      if (i2 - i1 >= MIN_ZOOM_POINTS - 1) {
        const baseOffset = zoomRange ? zoomRange.start : 0;
        setZoomRange({ start: baseOffset + i1, end: baseOffset + i2 });
      }
    }
    setDragStartX(null);
    setDragCurrentX(null);
  }

  const showingDrag = dragStartX != null && dragCurrentX != null && Math.abs(dragCurrentX - dragStartX) >= DRAG_THRESHOLD_PX;
  const selected = selectedIndex != null ? visibleChart[selectedIndex] : null;
  const selectedIsEarnings = selected && earningsDates.includes(selected.date);

  return (
    <div className="technical-chart">
      <div className="technical-chart-toolbar">
        <p className="field-hint">Arrastrá sobre el gráfico para hacer zoom en un rango · doble clic para restablecer.</p>
        {zoomRange && (
          <button type="button" className="link-button" onClick={() => setZoomRange(null)}>
            Restablecer zoom
          </button>
        )}
      </div>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="price-chart-svg technical-chart-svg"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerLeave={() => {
          setDragStartX(null);
          setDragCurrentX(null);
        }}
        onDoubleClick={() => setZoomRange(null)}
      >
        {yTicks.map((price, i) => (
          <g key={i}>
            <line x1={MARGIN.left} x2={WIDTH - MARGIN.right} y1={yAt(price)} y2={yAt(price)} className="price-chart-gridline" />
            <text x={MARGIN.left - 8} y={yAt(price)} className="price-chart-axis-label" textAnchor="end" dy="0.32em">
              {formatPrice(price)}
            </text>
          </g>
        ))}

        {dateTicks.map((idx, i) => (
          <text
            key={idx}
            x={xAt(idx)}
            y={HEIGHT - 6}
            className="price-chart-axis-label"
            textAnchor={i === 0 ? "start" : i === dateTicks.length - 1 ? "end" : "middle"}
          >
            {formatDate(visibleChart[idx].date)}
          </text>
        ))}

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

        {selected && !showingDrag && (
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

        {showingDrag && (
          <rect
            x={Math.min(dragStartX, dragCurrentX)}
            y={MARGIN.top}
            width={Math.abs(dragCurrentX - dragStartX)}
            height={innerHeight}
            className="technical-chart-zoom-selection"
          />
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
