// Formatting helpers (ported from web/src/lib/format.ts, then moved to the v2 copy rules, design spec 9.6):
// - Unknown is "-" (UNKNOWN): never 0.000, --:--.---, or an em dash (P5).
// - Negative numbers use the minus sign U+2212 (MINUS); positive deltas carry "+".
// - Times m:ss.SSS, sectors ss.SSS; a running clock shows tenths, truncated like a stopwatch.
// - Thousands get a narrow no-break space in prose ("5 890 m").
// Colours resolve to theme tokens (styles/tokens.css). Pure functions: tested in plain node (format.test.ts).

/** Every unknown value renders as this. */
export const UNKNOWN = "-";
/** U+2212, the minus sign for every signed number. */
export const MINUS = "−";
/** U+202F narrow no-break space: thousands separator in prose. */
export const THIN_SPACE = " ";
/** Inside +/- this many seconds a delta is LEVEL (spec 4.5). */
export const DELTA_LEVEL_S = 0.02;

function finite(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/** Integer count of 10^-digits seconds in `ms`: rounded at millisecond precision, truncated below it (a clock
 *  never shows time that has not elapsed yet, and 1:30.98 must not read as 1:31.0). */
function units(ms: number, digits: number): number {
  const d = Math.max(0, Math.min(3, Math.trunc(digits)));
  const exact = Math.round(ms); // whole milliseconds first, so float noise never flips a digit
  return d === 3 ? exact : Math.floor(exact / 10 ** (3 - d));
}

function clock(ms: number, digits: number, withMinutes: boolean): string {
  const d = Math.max(0, Math.min(3, Math.trunc(digits)));
  const n = units(ms, d); // in 10^-d s
  const perSecond = 10 ** d;
  const totalS = Math.floor(n / perSecond);
  const frac = n % perSecond;
  const tail = d > 0 ? `.${String(frac).padStart(d, "0")}` : "";
  if (!withMinutes) return `${totalS}${tail}`;
  const m = Math.floor(totalS / 60);
  const s = totalS % 60;
  return `${m}:${String(s).padStart(2, "0")}${tail}`;
}

/** Lap time `m:ss.SSS` (`digits` 1 gives the running clock `m:ss.t`). Unknown, zero or negative -> "-". */
export function lapTime(ms: number | null | undefined, digits = 3): string {
  if (!finite(ms) || ms <= 0) return UNKNOWN;
  return clock(ms, digits, true);
}

/** Sector time `ss.SSS` (`m:ss.SSS` from a minute up). Unknown, zero or negative -> "-". */
export function sector(ms: number | null | undefined, digits = 3): string {
  if (!finite(ms) || ms <= 0) return UNKNOWN;
  return ms >= 60_000 ? clock(ms, digits, true) : clock(ms, digits, false);
}

/** Signed number: "+0.530", "−0.021", "±0.000". Unknown -> "-". */
export function signed(v: number | null | undefined, digits = 3, unit = ""): string {
  if (!finite(v)) return UNKNOWN;
  const abs = Math.abs(v).toFixed(digits);
  if (Number(abs) === 0) return `±${abs}${unit}`;
  return `${v > 0 ? "+" : MINUS}${abs}${unit}`;
}

/** A delta in seconds: 2 decimals, 1 decimal from 10 s up ("+12.4"), unless `digits` says otherwise. */
export function deltaSeconds(s: number | null | undefined, digits?: number): string {
  if (!finite(s)) return UNKNOWN;
  return signed(s, digits ?? (Math.abs(s) >= 9.995 ? 1 : 2));
}

export type DeltaSide = "ahead" | "behind" | "level";

/** Ahead (faster than the reference), behind, or level within `tolerance` seconds; null when unknown. */
export function deltaTone(v: number | null | undefined, tolerance = DELTA_LEVEL_S): DeltaSide | null {
  if (!finite(v)) return null;
  if (v < -tolerance) return "ahead";
  if (v > tolerance) return "behind";
  return "level";
}

/** Tailwind text colour class for a delta in seconds (tokens: text-ahead / text-behind / text-foreground). */
export function deltaClass(v: number | null | undefined, tolerance = DELTA_LEVEL_S): string {
  const t = deltaTone(v, tolerance);
  return t === "ahead" ? "text-ahead" : t === "behind" ? "text-behind" : t === "level" ? "text-foreground" : "text-faint";
}

/** Plain number with `digits` decimals; negative numbers get U+2212. Unknown -> `fallback` ("-"). */
export function num(v: number | null | undefined, digits = 0, fallback = UNKNOWN): string {
  if (!finite(v)) return fallback;
  const abs = Math.abs(v).toFixed(digits);
  return v < 0 && Number(abs) !== 0 ? `${MINUS}${abs}` : abs;
}

/** Number with at most `maxDigits` decimals and no trailing zeros ("−3.5", "0.05", "50"). Unknown -> "-". */
export function decimal(v: number | null | undefined, maxDigits = 2): string {
  if (!finite(v)) return UNKNOWN;
  const abs = String(Number(Math.abs(v).toFixed(maxDigits)));
  return v < 0 && Number(abs) !== 0 ? `${MINUS}${abs}` : abs;
}

/** Integer with narrow no-break spaces between thousands ("5 890"). Unknown -> "-". */
export function grouped(v: number | null | undefined): string {
  if (!finite(v)) return UNKNOWN;
  const n = Math.round(v);
  const digits = String(Math.abs(n)).replace(/\B(?=(\d{3})+(?!\d))/g, THIN_SPACE);
  return n < 0 ? `${MINUS}${digits}` : digits;
}

/** Distance "320 m", rounded to `step` metres ("5 890 m" in prose). Unknown or negative -> "-". */
export function metres(m: number | null | undefined, step = 1): string {
  if (!finite(m) || m < 0) return UNKNOWN;
  const s = step > 0 ? step : 1;
  return `${grouped(Math.round(m / s) * s)} m`;
}

/** A menu- or API-formatted value ("-3.50") with its leading hyphen-minus turned into U+2212. Ranges such as
 *  "70-85" are left alone (only a leading sign before a digit changes). */
export function withMinus(text: string): string {
  return text.replace(/^-(?=[\d.])/, MINUS);
}

export function gearLabel(g: number | null | undefined): string {
  if (!finite(g)) return UNKNOWN;
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

// Tyre temperature colour band (generic slick window, F1-like): cold -> in window (plain foreground) -> hot.
export function tyreTempColor(t: number | null | undefined): string {
  if (!finite(t)) return "var(--pw-faint)";
  if (t < 75) return "var(--pw-tyre-cold)";
  if (t < 85) return "var(--pw-tyre-cool)";
  if (t <= 105) return "var(--pw-tyre-optimal)";
  if (t <= 115) return "var(--pw-tyre-hot)";
  return "var(--pw-tyre-over)";
}

/** Clamp a 0..1 pedal / ratio value; unknown stays null (never coerced to 0). */
export function unit01(v: number | null | undefined): number | null {
  if (!finite(v)) return null;
  return Math.min(1, Math.max(0, v));
}
