// Shared numeric helpers for the visualisation kit (design spec v2, 10.6 and 14.1 lane V). Pure: no DOM, no React.
//
// Two metre scales exist on every track: the game's lap metres (frame.lap_distance_m, the skeleton, cue targets,
// stored lap traces) and the learned track model's metres (corners, centreline), which can differ by a few metres.
// They are mapped by lap fraction, exactly as the Svelte TrackMap.toModel and lib/drive/geometry do.

export function finite(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/** Clamp to [lo, hi]. */
export function clamp(v: number, lo: number, hi: number): number {
  return v < lo ? lo : v > hi ? hi : v;
}

/** A positive length, or null. */
export function positive(v: unknown): number | null {
  return finite(v) && v > 0 ? v : null;
}

/** Lap fraction 0..1 of a distance on a lap of `lengthM`; null when either is unknown. Clamped, never wrapped. */
export function lapFraction(m: number | null | undefined, lengthM: number | null | undefined): number | null {
  const L = positive(lengthM);
  if (!finite(m) || L == null) return null;
  return clamp(m / L, 0, 1);
}

/** Wrap a distance into [0, L). */
export function wrapMetres(m: number, lengthM: number): number {
  const x = m % lengthM;
  return x < 0 ? x + lengthM : x;
}

/**
 * Map a distance from one lap length to another by lap fraction (game metres -> model metres, or back). Identity
 * when either length is unknown: the two scales differ by a few metres at most, so an unmapped value is still close.
 */
export function mapMetres(m: number, fromLengthM: number | null | undefined, toLengthM: number | null | undefined): number {
  const a = positive(fromLengthM);
  const b = positive(toLengthM);
  return a != null && b != null ? (m / a) * b : m;
}

/** A "nice" tick step (1, 2, 2.5 or 5 x 10^n) giving about `target` intervals over `range`. */
export function niceStep(range: number, target = 4): number {
  if (!(range > 0) || !(target > 0)) return 1;
  const raw = range / target;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const r = raw / mag;
  const k = r <= 1 ? 1 : r <= 2 ? 2 : r <= 2.5 ? 2.5 : r <= 5 ? 5 : 10;
  return k * mag;
}

/** Ticks on multiples of a nice step inside [lo, hi] (inclusive, float noise rounded away). */
export function niceTicks(lo: number, hi: number, target = 4): number[] {
  if (!finite(lo) || !finite(hi) || hi < lo) return [];
  if (hi === lo) return [lo];
  const step = niceStep(hi - lo, target);
  const out: number[] = [];
  const first = Math.ceil(lo / step - 1e-9) * step;
  for (let v = first; v <= hi + step * 1e-9; v += step) out.push(Number(v.toFixed(9)));
  return out;
}
