import { useMemo, useState } from "react";

const WIDTH = 640;
const HEIGHT = 260;
const MARGIN = { top: 16, right: 16, bottom: 28, left: 56 };

function formatDate(iso) {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("es", { day: "2-digit", month: "short", year: "2-digit" });
}

function formatPrice(value) {
  return `$${value.toFixed(2)}`;
}

export default function PriceWindowChart({ priceWindow, reactionDate }) {
  const [hoverIndex, setHoverIndex] = useState(null);

  const plot = useMemo(() => {
    if (!priceWindow || priceWindow.length < 2) return null;

    const prices = priceWindow.map((p) => p.price);
    const minPrice = Math.min(...prices);
    const maxPrice = Math.max(...prices);
    const pad = (maxPrice - minPrice) * 0.08 || maxPrice * 0.02;
    const yMin = minPrice - pad;
    const yMax = maxPrice + pad;

    const innerWidth = WIDTH - MARGIN.left - MARGIN.right;
    const innerHeight = HEIGHT - MARGIN.top - MARGIN.bottom;

    const xAt = (i) => MARGIN.left + (i / (priceWindow.length - 1)) * innerWidth;
    const yAt = (price) => MARGIN.top + innerHeight - ((price - yMin) / (yMax - yMin)) * innerHeight;

    const linePath = priceWindow.map((p, i) => `${i === 0 ? "M" : "L"}${xAt(i)},${yAt(p.price)}`).join(" ");

    const reactionIndex = priceWindow.findIndex((p) => p.date === reactionDate);

    const yTicks = [yMin + pad, (yMin + yMax) / 2, yMax - pad];

    return { xAt, yAt, linePath, reactionIndex, yTicks, innerWidth, innerHeight };
  }, [priceWindow, reactionDate]);

  if (!plot) {
    return <p className="field-hint">No hay suficientes datos de precio para graficar esta ventana.</p>;
  }

  const { xAt, yAt, linePath, reactionIndex, yTicks, innerHeight } = plot;

  function handleMove(e) {
    const svg = e.currentTarget;
    const rect = svg.getBoundingClientRect();
    const scaleX = WIDTH / rect.width;
    const mouseX = (e.clientX - rect.left) * scaleX;
    const innerWidth = WIDTH - MARGIN.left - MARGIN.right;
    const ratio = Math.min(1, Math.max(0, (mouseX - MARGIN.left) / innerWidth));
    const index = Math.round(ratio * (priceWindow.length - 1));
    setHoverIndex(index);
  }

  const hovered = hoverIndex != null ? priceWindow[hoverIndex] : null;

  return (
    <div className="price-chart">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="price-chart-svg"
        onMouseMove={handleMove}
        onMouseLeave={() => setHoverIndex(null)}
      >
        {yTicks.map((price, i) => (
          <g key={i}>
            <line
              x1={MARGIN.left}
              x2={WIDTH - MARGIN.right}
              y1={yAt(price)}
              y2={yAt(price)}
              className="price-chart-gridline"
            />
            <text x={MARGIN.left - 8} y={yAt(price)} className="price-chart-axis-label" textAnchor="end" dy="0.32em">
              {formatPrice(price)}
            </text>
          </g>
        ))}

        <text x={xAt(0)} y={HEIGHT - 6} className="price-chart-axis-label" textAnchor="start">
          {formatDate(priceWindow[0].date)}
        </text>
        <text x={xAt(priceWindow.length - 1)} y={HEIGHT - 6} className="price-chart-axis-label" textAnchor="end">
          {formatDate(priceWindow[priceWindow.length - 1].date)}
        </text>

        {reactionIndex >= 0 && (
          <>
            <line
              x1={xAt(reactionIndex)}
              x2={xAt(reactionIndex)}
              y1={MARGIN.top}
              y2={MARGIN.top + innerHeight}
              className="price-chart-reaction-line"
            />
            <text x={xAt(reactionIndex)} y={MARGIN.top - 4} className="price-chart-reaction-label" textAnchor="middle">
              Earnings
            </text>
          </>
        )}

        <path d={linePath} className="price-chart-line" />

        {hoverIndex != null && (
          <>
            <line
              x1={xAt(hoverIndex)}
              x2={xAt(hoverIndex)}
              y1={MARGIN.top}
              y2={MARGIN.top + innerHeight}
              className="price-chart-crosshair"
            />
            <circle
              cx={xAt(hoverIndex)}
              cy={yAt(priceWindow[hoverIndex].price)}
              r="4"
              className="price-chart-dot"
              strokeWidth="2"
            />
          </>
        )}
      </svg>

      <div className="price-chart-tooltip">
        {hovered ? (
          <>
            <strong>{formatPrice(hovered.price)}</strong> · {formatDate(hovered.date)}
            {hovered.date === reactionDate && <span className="price-chart-reaction-tag"> · día de earnings</span>}
          </>
        ) : (
          <span className="field-hint">Pasa el mouse sobre el gráfico para ver el detalle.</span>
        )}
      </div>
    </div>
  );
}
