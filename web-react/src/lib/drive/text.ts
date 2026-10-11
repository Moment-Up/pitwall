// Drive text formatting (design spec 9.6): unknown is "-", minus is U+2212, times m:ss.SSS, sectors ss.SSS,
// distances "285 m", thousands with a narrow no-break space ("5 890 m"). Pure; no locale-dependent number output.

export const UNKNOWN = "-";
export const MINUS = "−";
/** Narrow no-break space: the thousands separator in "5 890 m". */
export const THIN = " ";

export function finite(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/** "−0.21" / "+0.21" / "0.00": the sign is dropped when the rounded value is zero. */
export function signedFixed(v: number | null | undefined, digits: number): string {
  if (!finite(v)) return UNKNOWN;
  const abs = Math.abs(v).toFixed(digits);
  if (Number(abs) === 0) return abs;
  return `${v < 0 ? MINUS : "+"}${abs}`;
}

/** Whole number with thin-space thousands: 5890 -> "5 890". */
export function thousands(n: number): string {
  const s = String(Math.round(Math.abs(n)));
  const out = s.replace(/\B(?=(\d{3})+(?!\d))/g, THIN);
  return n < 0 && Math.round(Math.abs(n)) !== 0 ? `${MINUS}${out}` : out;
}

/** "320 m" (whole metres, thin-space thousands); "-" when unknown. */
export function metres(m: number | null | undefined): string {
  return finite(m) ? `${thousands(m)} m` : UNKNOWN;
}

/** A distance for a secondary line: "850 m" below 1 km, else "1.4 km". */
export function distanceShort(m: number | null | undefined): string {
  if (!finite(m)) return UNKNOWN;
  return m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(1)} km`;
}

/** Round to the nearest 10 m (the hero distance). */
export function round10(m: number): number {
  return Math.max(0, Math.round(m / 10) * 10);
}

/** m:ss.SSS ("1:31.512"); "-" when unknown or not positive. */
export function lapTime(ms: number | null | undefined): string {
  if (!finite(ms) || ms <= 0) return UNKNOWN;
  const total = Math.round(ms);
  const m = Math.floor(total / 60000);
  const rest = total - m * 60000;
  const s = Math.floor(rest / 1000);
  const milli = rest - s * 1000;
  return `${m}:${String(s).padStart(2, "0")}.${String(milli).padStart(3, "0")}`;
}

/** m:ss.SS ("1:30.77"), rounded to hundredths; "-" when unknown or not positive. */
export function lapTimeHundredths(ms: number | null | undefined): string {
  if (!finite(ms) || ms <= 0) return UNKNOWN;
  const cs = Math.round(ms / 10);
  const m = Math.floor(cs / 6000);
  const rest = cs - m * 6000;
  const s = Math.floor(rest / 100);
  return `${m}:${String(s).padStart(2, "0")}.${String(rest - s * 100).padStart(2, "0")}`;
}

/** Running lap clock in tenths ("1:09.5", truncated like a stopwatch); "-" when unknown or negative. */
export function lapClockTenths(ms: number | null | undefined): string {
  if (!finite(ms) || ms < 0) return UNKNOWN;
  const tenths = Math.floor(ms / 100);
  const m = Math.floor(tenths / 600);
  const rest = tenths - m * 600;
  const s = Math.floor(rest / 10);
  return `${m}:${String(s).padStart(2, "0")}.${rest - s * 10}`;
}

/** Sector time: "29.318", or "1:02.345" at a minute or more; "-" when unknown or not positive. */
export function sectorTime(ms: number | null | undefined): string {
  if (!finite(ms) || ms <= 0) return UNKNOWN;
  if (ms >= 60000) return lapTime(ms);
  return (Math.round(ms) / 1000).toFixed(3);
}

/** Running sector clock in tenths: "4.6", "1:02.3". */
export function sectorClockTenths(ms: number | null | undefined): string {
  if (!finite(ms) || ms < 0) return UNKNOWN;
  if (ms >= 60000) return lapClockTenths(ms);
  return (Math.floor(ms / 100) / 10).toFixed(1);
}

/** Seconds with a sign and 3 decimals from a millisecond difference: −23 -> "−0.023". */
export function signedMs(diffMs: number | null | undefined, digits = 3): string {
  return finite(diffMs) ? signedFixed(diffMs / 1000, digits) : UNKNOWN;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function sameLocalDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/** "today" when `unix` falls on the same local day as `nowS`, else "3 Oct" (and the year when it differs). */
export function dayText(unix: number | null | undefined, nowS: number): string | null {
  if (!finite(unix)) return null;
  const d = new Date(unix * 1000);
  const now = new Date(nowS * 1000);
  if (sameLocalDay(d, now)) return "today";
  const base = `${d.getDate()} ${MONTHS[d.getMonth()] ?? ""}`;
  return d.getFullYear() === now.getFullYear() ? base : `${base} ${d.getFullYear()}`;
}

/** A signal age for the status slot: "6 s", "21 min", "3 h". */
export function ageText(sec: number): string {
  if (sec < 120) return `${Math.round(sec)} s`;
  if (sec < 7200) return `${Math.round(sec / 60)} min`;
  return `${Math.round(sec / 3600)} h`;
}

/** First letter upper case (server reasons arrive in lower case: "no reference lap yet"). */
export function sentence(s: string): string {
  return s.length ? s[0]!.toUpperCase() + s.slice(1) : s;
}

/** "1 lap" / "3 laps". */
export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** Confidence in words (9.6): high >= 0.8, medium 0.6-0.8, low < 0.6. */
export function confidenceWord(c: number | null | undefined): "high" | "medium" | "low" | null {
  if (!finite(c)) return null;
  return c >= 0.8 ? "high" : c >= 0.6 ? "medium" : "low";
}
