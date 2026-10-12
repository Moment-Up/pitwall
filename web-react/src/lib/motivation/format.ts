// Formatting for goals, streaks and the weekly digest (lane motivation). Pure; tested in plain node.
//
// Copy rules (design spec 9.6): unknown is "-", plain British English, times m:ss.SSS. Every sentence about the
// driver's progress comes from the server (titles, progress texts, recap items, headlines); the browser only formats
// numbers, dates and labels, and checks what a driver types before it is sent.
//
// Weeks are Monday to Sunday in local time, moved with calendar arithmetic (Date#setDate), never by adding
// 7 × 86 400 s: the change from summer time on 25 Oct 2026 must not move a week.

import { lapTime, UNKNOWN } from "../format";

export { UNKNOWN };

function finite(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/** A goal's lap time: "1:10.000" (m:ss.SSS), "-" when unknown. */
export function goalLapTime(ms: number | null | undefined): string {
  return lapTime(ms);
}

/** A lap time a driver can type back: "1:10.0" (tenths), "" when unknown. */
export function tenthsText(ms: number | null | undefined): string {
  if (!finite(ms) || ms <= 0) return "";
  return lapTime(Math.round(ms / 100) * 100, 1);
}

/** Seconds in words with one decimal: "1.1 s" (a spread, a gap); "-" when unknown. */
export function secondsShort(ms: number | null | undefined): string {
  if (!finite(ms) || ms < 0) return UNKNOWN;
  return `${(Math.round(ms / 100) / 10).toFixed(1)} s`;
}

export type Parsed = { ok: true; ms: number } | { ok: false; error: string };

export const LAP_TARGET_MIN_MS = 10_000;
export const LAP_TARGET_MAX_MS = 3_600_000;

/**
 * A lap time typed as `m:ss.s` ("1:10.0", "1:10", "70.5" seconds) to whole tenths in ms. Anything finer than a
 * tenth that is not a whole tenth ("1:10.05") is refused rather than rounded: the goal must be what the driver typed.
 */
export function parseLapTarget(text: string): Parsed {
  const t = text.trim().replace(",", ".");
  if (!t) return { ok: false, error: "Type a lap time, like 1:10.0." };
  const m = /^(?:(\d{1,2}):)?(\d{1,4})(?:\.(\d{1,3}))?$/.exec(t);
  if (!m) return { ok: false, error: "Type the time as minutes:seconds, like 1:10.0." };
  const minutes = m[1] ? Number(m[1]) : 0;
  const secs = Number(m[2]);
  if (m[1] && secs >= 60) return { ok: false, error: "Seconds go up to 59, like 1:10.0." };
  const frac = (m[3] ?? "").padEnd(3, "0");
  const ms = (minutes * 60 + secs) * 1000 + Number(frac || "0");
  if (ms % 100 !== 0) return { ok: false, error: "Use tenths of a second, like 1:10.4." };
  if (ms < LAP_TARGET_MIN_MS || ms > LAP_TARGET_MAX_MS) {
    return { ok: false, error: "A lap target is between 0:10.0 and 60:00.0." };
  }
  return { ok: true, ms };
}

/** A 0..1 fraction as a 0..100 value for a progress bar; null when unknown. */
export function percent(fraction: number | null | undefined): number | null {
  if (!finite(fraction)) return null;
  return Math.round(Math.min(1, Math.max(0, fraction)) * 1000) / 10;
}

/** "Sam's", "James's": always 's, as the server's reference labels say it ("James's best"; Review's `whoFor` too). */
export function possessive(name: string): string {
  return `${name}'s`;
}

/** "1 lap", "8 laps". */
export function count(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** Whether a game id is an F1 game (race goals and best sectors need F1's session type, lap total and sectors). */
export function isF1Game(game: string | null | undefined): boolean {
  return typeof game === "string" && game.toLowerCase().startsWith("f1");
}

/**
 * A car class as a choice: F1's formula ("f1_25:formula:F1 World" -> "any F1 World car"); a Forza class number has
 * no letter Pitwall can trust, so it is named after the car ("any car of the same class as the Porsche 911 GT3").
 * Null when the class is unknown.
 */
export function classLabel(carClass: string | null | undefined, carName?: string | null): string | null {
  if (!carClass) return null;
  const f = /^[^:]+:formula:(.+)$/.exec(carClass);
  if (f?.[1]) return `any ${f[1]} car`;
  if (/^[^:]+:class:\d+$/.test(carClass)) return carName ? `any car of the same class as the ${carName}` : "any car of the same class";
  return null;
}

// ------------------------------------------------------------------------------------------------- weeks

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** A local date as "YYYY-MM-DD". */
export function isoDate(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** "YYYY-MM-DD" as a local date at midnight; null when it is not a date. */
export function parseIsoDate(s: string | null | undefined): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s ?? "");
  if (!m) return null;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return d.getMonth() === Number(m[2]) - 1 ? d : null;
}

/** The Monday of the week holding `d` (local), as "YYYY-MM-DD". */
export function mondayOf(d: Date): string {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  x.setDate(x.getDate() - ((x.getDay() + 6) % 7));
  return isoDate(x);
}

/** A day `days` calendar days after an ISO date (negative goes back); the input itself when it is not a date. */
export function addDays(iso: string, days: number): string {
  const d = parseIsoDate(iso);
  if (!d) return iso;
  d.setDate(d.getDate() + days);
  return isoDate(d);
}

/** The Monday `weeks` weeks after the week holding `iso`. */
export function shiftWeek(iso: string, weeks: number): string {
  const d = parseIsoDate(iso);
  if (!d) return iso;
  return addDays(mondayOf(d), weeks * 7);
}

/** "5 to 11 Oct", "28 Sep to 4 Oct", "29 Dec 2025 to 4 Jan 2026"; from the week's Monday. */
export function weekLabel(weekStart: string): string {
  const a = parseIsoDate(weekStart);
  if (!a) return UNKNOWN;
  const b = new Date(a.getFullYear(), a.getMonth(), a.getDate() + 6);
  if (a.getFullYear() !== b.getFullYear()) {
    return `${a.getDate()} ${MONTHS[a.getMonth()]} ${a.getFullYear()} to ${b.getDate()} ${MONTHS[b.getMonth()]} ${b.getFullYear()}`;
  }
  if (a.getMonth() !== b.getMonth()) return `${a.getDate()} ${MONTHS[a.getMonth()]} to ${b.getDate()} ${MONTHS[b.getMonth()]}`;
  return `${a.getDate()} to ${b.getDate()} ${MONTHS[b.getMonth()]}`;
}

/** Driving time in words: "45 min", "1 h 12 min"; "-" when unknown. */
export function drivingTime(seconds: number | null | undefined): string {
  if (!finite(seconds) || seconds < 0) return UNKNOWN;
  const min = Math.round(seconds / 60);
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  const rest = min % 60;
  return rest ? `${h} h ${rest} min` : `${h} h`;
}

/** "Sat 10 Oct" (local), for a date in a list; "-" when unknown. */
export function shortDay(unixS: number | null | undefined): string {
  if (!finite(unixS)) return UNKNOWN;
  const d = new Date(unixS * 1000);
  return `${["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]}`;
}
