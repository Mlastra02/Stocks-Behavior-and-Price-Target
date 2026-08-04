import { useEffect, useRef, useState } from "react";

const WIDTH = 560;
const HEIGHT = 74;
const MARGIN = { top: 10, right: 14, bottom: 20, left: 14 };
const TRACK_Y = MARGIN.top + 34;
const DOTS_Y = MARGIN.top + 10;
const EPSILON = 1e-9;

// A one-dimensional "rug plot" (one dot per data point) with a draggable
// two-handle range brush underneath — lets you isolate an arbitrary slice of
// the loaded reports by dragging instead of typing numbers, and see the
// actual distribution (plus which points other active filters already
// exclude) while you do it.
export default function RangeStrip({ points, domainMin, domainMax, selectedMin, selectedMax, onChange, formatValue }) {
  const svgRef = useRef(null);
  const [dragging, setDragging] = useState(null); // "min" | "max" | null

  const innerWidth = WIDTH - MARGIN.left - MARGIN.right;
  const span = domainMax - domainMin || 1;
  const xAt = (v) => MARGIN.left + ((v - domainMin) / span) * innerWidth;
  const valueAt = (x) => domainMin + ((x - MARGIN.left) / innerWidth) * span;
  const clamp = (v) => Math.min(domainMax, Math.max(domainMin, v));

  function valueAtClientX(clientX) {
    const rect = svgRef.current.getBoundingClientRect();
    const x = ((clientX - rect.left) / rect.width) * WIDTH;
    return clamp(valueAt(x));
  }

  useEffect(() => {
    if (!dragging) return;

    function handleMove(e) {
      const v = valueAtClientX(e.clientX);
      if (dragging === "min") {
        onChange(Math.min(v, selectedMax), selectedMax);
      } else {
        onChange(selectedMin, Math.max(v, selectedMin));
      }
    }
    function handleUp() {
      setDragging(null);
    }

    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp);
    return () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dragging, selectedMin, selectedMax]);

  const isFiltered = selectedMin > domainMin + EPSILON || selectedMax < domainMax - EPSILON;

  function resetRange() {
    onChange(domainMin, domainMax);
  }

  return (
    <div className="range-strip">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="range-strip-svg"
        onDoubleClick={resetRange}
      >
        <line x1={MARGIN.left} y1={TRACK_Y} x2={WIDTH - MARGIN.right} y2={TRACK_Y} className="range-strip-track" />
        <rect
          x={xAt(selectedMin)}
          y={TRACK_Y - 3}
          width={Math.max(0, xAt(selectedMax) - xAt(selectedMin))}
          height={6}
          rx={3}
          className="range-strip-selection"
        />

        {points.map((p, i) => (
          <circle
            key={i}
            cx={xAt(p.value)}
            cy={DOTS_Y}
            r={3}
            className={"range-strip-dot" + (p.active ? "" : " range-strip-dot-inactive")}
          />
        ))}

        <text x={MARGIN.left} y={HEIGHT - 6} textAnchor="start" className="range-strip-domain-label">
          {formatValue(domainMin)}
        </text>
        <text x={WIDTH - MARGIN.right} y={HEIGHT - 6} textAnchor="end" className="range-strip-domain-label">
          {formatValue(domainMax)}
        </text>

        <g onPointerDown={() => setDragging("min")} className="range-strip-handle-hit">
          <circle cx={xAt(selectedMin)} cy={TRACK_Y} r={8} className="range-strip-handle" />
        </g>
        <g onPointerDown={() => setDragging("max")} className="range-strip-handle-hit">
          <circle cx={xAt(selectedMax)} cy={TRACK_Y} r={8} className="range-strip-handle" />
        </g>
      </svg>
      <div className="range-strip-footer">
        <span className="field-hint">
          {isFiltered ? `Mostrando: ${formatValue(selectedMin)} – ${formatValue(selectedMax)}` : "Rango completo (sin filtrar) — arrastrá para acotar"}
        </span>
        {isFiltered && (
          <button type="button" className="link-button" onClick={resetRange}>
            Restablecer
          </button>
        )}
      </div>
    </div>
  );
}
