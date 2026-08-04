import { useMemo, useState } from "react";

const WIDTH = 900;
const HEIGHT = 320;
const MARGIN = { top: 16, right: 16, bottom: 28, left: 56 };

// Fixed, never-cycled color order — same series always gets the same slot
// regardless of how many others are selected alongside it.
const COMPARE_COLORS = [
  "var(--series-1)",
  "var(--series-2)",
  "var(--series-3)",
  "#2f9e44",
  "#e64980",
  "#f08c00",
  "#0c8599",
  "#5c5f66",
];

function formatDate(iso) {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("es", { day: "2-digit", month: "short", year: "2-digit" });
}

function nearestIndex(points, targetTime) {
  let best = 0;
  let bestDiff = Infinity;
  points.forEach((p, i) => {
    const diff = Math.abs(new Date(p.date).getTime() - targetTime);
    if (diff < bestDiff) {
      bestDiff = diff;
      best = i;
    }
  });
  return best;
}

// Indexes every series to 100 at the latest of the individual series' start
// dates — so stocks with shorter history (a recent IPO) still compare
// fairly, from the first date all of them actually have data for.
export default function CompareChart({ series }) {
  const [hoverTime, setHoverTime] = useState(null);

  const plot = useMemo(() => {
    const nonEmpty = series.filter((s) => s.chart.length > 0);
    if (nonEmpty.length === 0) return null;

    const commonStart = nonEmpty.reduce(
      (max, s) => (s.chart[0].date > max ? s.chart[0].date : max),
      nonEmpty[0].chart[0].date
    );

    const indexed = nonEmpty
      .map((s) => {
        const points = s.chart.filter((p) => p.date >= commonStart);
        if (points.length === 0) return null;
        const base = points[0].price;
        return {
          symbol: s.symbol,
          points: points.map((p) => ({ date: p.date, value: (p.price / base) * 100 })),
        };
      })
      .filter(Boolean);

    if (indexed.length === 0) return null;

    const allTimes = indexed.flatMap((s) => s.points.map((p) => new Date(p.date).getTime()));
    const minTime = Math.min(...allTimes);
    const maxTime = Math.max(...allTimes);
    const allValues = indexed.flatMap((s) => s.points.map((p) => p.value));
    const minValue = Math.min(...allValues, 100);
    const maxValue = Math.max(...allValues, 100);
    const pad = (maxValue - minValue) * 0.08 || 5;
    const yMin = minValue - pad;
    const yMax = maxValue + pad;

    const innerWidth = WIDTH - MARGIN.left - MARGIN.right;
    const innerHeight = HEIGHT - MARGIN.top - MARGIN.bottom;
    const span = maxTime - minTime || 1;
    const xAt = (time) => MARGIN.left + ((time - minTime) / span) * innerWidth;
    const yAt = (value) => MARGIN.top + innerHeight - ((value - yMin) / (yMax - yMin)) * innerHeight;

    const lines = indexed.map((s, i) => ({
      symbol: s.symbol,
      color: COMPARE_COLORS[i % COMPARE_COLORS.length],
      path: s.points.map((p, j) => `${j === 0 ? "M" : "L"}${xAt(new Date(p.date).getTime())},${yAt(p.value)}`).join(" "),
      points: s.points,
      lastValue: s.points[s.points.length - 1].value,
    }));

    const yTicks = [yMin + pad, 100, yMax - pad];

    return { xAt, yAt, lines, yTicks, innerHeight, minTime, maxTime, minDate: commonStart };
  }, [series]);

  if (!plot) {
    return <p className="field-hint">Elegí al menos una acción con datos para comparar.</p>;
  }

  const { xAt, yAt, lines, yTicks, innerHeight, minTime, maxTime } = plot;

  function handleMove(e) {
    const svg = e.currentTarget;
    const rect = svg.getBoundingClientRect();
    const scaleX = WIDTH / rect.width;
    const mouseX = (e.clientX - rect.left) * scaleX;
    const innerWidth = WIDTH - MARGIN.left - MARGIN.right;
    const ratio = Math.min(1, Math.max(0, (mouseX - MARGIN.left) / innerWidth));
    setHoverTime(minTime + ratio * (maxTime - minTime));
  }

  const hoverRows = hoverTime == null
    ? null
    : lines.map((line) => {
        const idx = nearestIndex(line.points, hoverTime);
        return { symbol: line.symbol, color: line.color, point: line.points[idx] };
      });

  return (
    <div className="compare-chart">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="price-chart-svg"
        onMouseMove={handleMove}
        onMouseLeave={() => setHoverTime(null)}
      >
        {yTicks.map((value, i) => (
          <g key={i}>
            <line x1={MARGIN.left} x2={WIDTH - MARGIN.right} y1={yAt(value)} y2={yAt(value)} className="price-chart-gridline" />
            <text x={MARGIN.left - 8} y={yAt(value)} className="price-chart-axis-label" textAnchor="end" dy="0.32em">
              {value.toFixed(0)}
            </text>
          </g>
        ))}

        <text x={xAt(minTime)} y={HEIGHT - 6} className="price-chart-axis-label" textAnchor="start">
          {formatDate(new Date(minTime).toISOString().slice(0, 10))}
        </text>
        <text x={xAt(maxTime)} y={HEIGHT - 6} className="price-chart-axis-label" textAnchor="end">
          {formatDate(new Date(maxTime).toISOString().slice(0, 10))}
        </text>

        {lines.map((line) => (
          <path key={line.symbol} d={line.path} style={{ fill: "none", stroke: line.color, strokeWidth: 2, strokeLinejoin: "round", strokeLinecap: "round" }} />
        ))}

        {hoverTime != null && (
          <line
            x1={xAt(hoverTime)}
            x2={xAt(hoverTime)}
            y1={MARGIN.top}
            y2={MARGIN.top + innerHeight}
            className="price-chart-crosshair"
          />
        )}
      </svg>

      <div className="technical-chart-legend">
        {lines.map((line) => (
          <span key={line.symbol}>
            <i className="technical-chart-dot" style={{ background: line.color }} />
            {line.symbol}{" "}
            <strong className={line.lastValue >= 100 ? "watchlist-upside-positive" : "watchlist-upside-negative"}>
              {line.lastValue >= 100 ? "+" : ""}
              {(line.lastValue - 100).toFixed(1)}%
            </strong>
          </span>
        ))}
      </div>

      <div className="price-chart-tooltip">
        {hoverRows ? (
          hoverRows.map((row) => (
            <span key={row.symbol} style={{ marginRight: "1rem" }}>
              <strong style={{ color: row.color }}>{row.symbol}</strong> {formatDate(row.point.date)}:{" "}
              {row.point.value >= 100 ? "+" : ""}
              {(row.point.value - 100).toFixed(1)}%
            </span>
          ))
        ) : (
          <span className="field-hint">Pasá el mouse sobre el gráfico para comparar en una fecha puntual.</span>
        )}
      </div>
    </div>
  );
}
