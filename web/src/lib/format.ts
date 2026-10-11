export function lapTime(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms) || ms <= 0) return "--:--.---";
  const m = Math.floor(ms / 60000);
  const s = (ms % 60000) / 1000;
  return `${m}:${s.toFixed(3).padStart(6, "0")}`;
}

export function sector(ms: number | null | undefined): string {
  if (ms == null || ms <= 0) return "--.---";
  return (ms / 1000).toFixed(3);
}

export function signed(v: number | null | undefined, digits = 3, unit = ""): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v > 0 ? "+" : v < 0 ? "−" : "±"}${Math.abs(v).toFixed(digits)}${unit}`;
}

export function deltaClass(v: number | null | undefined, tolerance = 0.005): string {
  if (v == null) return "muted";
  if (v < -tolerance) return "gain";
  if (v > tolerance) return "loss";
  return "muted";
}

export function num(v: number | null | undefined, digits = 0, fallback = "—"): string {
  return v == null || !Number.isFinite(v) ? fallback : v.toFixed(digits);
}

export function gearLabel(g: number | null | undefined): string {
  if (g == null) return "–";
  if (g < 0) return "R";
  if (g === 0) return "N";
  return String(g);
}

export function ago(unix: number): string {
  const d = (Date.now() / 1000 - unix) | 0;
  if (d < 60) return "just now";
  if (d < 3600) return `${(d / 60) | 0} min ago`;
  if (d < 86400) return `${(d / 3600) | 0} h ago`;
  return new Date(unix * 1000).toLocaleDateString();
}

// Tyre temperature colour band (generic slick window, F1-like): cold -> optimal -> hot.
export function tyreTempColor(t: number | null | undefined): string {
  if (t == null) return "var(--faint)";
  if (t < 75) return "#38bdf8";
  if (t < 85) return "#7dd3fc";
  if (t <= 105) return "#3ddc84";
  if (t <= 115) return "#ffb020";
  return "#ff4d5e";
}
