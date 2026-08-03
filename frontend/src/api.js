export const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:5000";

export function pct(value) {
  return value == null ? "-" : `${(value * 100).toFixed(1)}%`;
}

// Shared options for a tri-state filter select: unset (no filter) / true / false.
export const TRI_STATE_OPTIONS = [
  { value: "", label: "Cualquiera" },
  { value: "true", label: "Solo con" },
  { value: "false", label: "Solo sin" },
];
