export const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:5000";

export function pct(value) {
  return value == null ? "-" : `${(value * 100).toFixed(1)}%`;
}
