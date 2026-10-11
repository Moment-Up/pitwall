// Chart data for the Summary (spec 6.3 #4, #5, #7). Pure; tested in node. The chart components (Pro LineChart /
// BarChart, Recharts underneath) only draw what these return.
//
// Lap times: a dot per timed lap, y axis reversed ("faster ↑": a smaller time sits higher), filled for clean laps,
// hollow for not clean with the reason in words, the reference lap's time as a line, the best clean lap tagged.

import type { CornerSummaryRow, ReviewTrackModel, SessionListRow } from "../endpoints/review";
import { cornerIdentity } from "./corners";
import { isReplaySource, type KpiLap } from "./kpis";
import { cornerWords, finite, notCleanReason } from "./words";

export interface LapPoint {
  lapId: number;
  lap: number;
  ms: number;
  /** Seconds (the chart's y value). */
  s: number;
  clean: boolean;
  /** Why it is not clean, in words; null for a clean lap. */
  reason: string | null;
  /** The best clean lap. */
  best: boolean;
}

/** One point per timed lap, in lap order. */
export function lapPoints(laps: readonly KpiLap[], bestLapId: number | null): LapPoint[] {
  return [...laps]
    .filter((l) => finite(l.lap_time_ms) && l.lap_time_ms > 0)
    .sort((a, b) => a.lap_number - b.lap_number)
    .map((l) => ({
      lapId: l.id,
      lap: l.lap_number,
      ms: l.lap_time_ms as number,
      s: (l.lap_time_ms as number) / 1000,
      clean: l.clean,
      reason: notCleanReason(l),
      best: l.id === bestLapId,
    }));
}

/** Chart rows: clean laps under `clean`, others under `other` (a missing key leaves a gap, never a 0). */
export function lapChartRows(points: readonly LapPoint[]): Record<string, number>[] {
  return points.map((p): Record<string, number> => (p.clean ? { lap: p.lap, clean: p.s } : { lap: p.lap, other: p.s }));
}

/** "1:10.5" for an axis tick (seconds; tenths, truncated). */
export function clockTick(s: number): string {
  if (!finite(s) || s <= 0) return "";
  const tenths = Math.floor(Math.round(s * 1000) / 100);
  const m = Math.floor(tenths / 600);
  const rest = tenths - m * 600;
  const sec = Math.floor(rest / 10);
  return m > 0 ? `${m}:${String(sec).padStart(2, "0")}.${rest % 10}` : `${sec}.${rest % 10}`;
}

const NICE_STEPS_S = [0.1, 0.2, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60];

/** Y domain (seconds) padded to whole steps, and 3-6 ticks; includes the reference time when given. */
export function timeAxis(values: readonly number[], extra?: number | null): { domain: [number, number]; ticks: number[] } {
  const all = [...values, ...(finite(extra) ? [extra] : [])].filter(finite);
  if (!all.length) return { domain: [0, 1], ticks: [] };
  let lo = Math.min(...all);
  let hi = Math.max(...all);
  if (hi - lo < 0.2) {
    lo -= 0.1;
    hi += 0.1;
  }
  const span = hi - lo;
  const step = NICE_STEPS_S.find((s) => span / s <= 5) ?? 60;
  const start = Math.floor(lo / step) * step;
  const end = Math.ceil(hi / step) * step;
  const ticks: number[] = [];
  for (let t = start; t <= end + step / 1000; t += step) ticks.push(Number(t.toFixed(3)));
  return { domain: [start, end], ticks };
}

// ---------------------------------------------------------------------------------------- where the time is (#5)

export interface CornerBar {
  key: string;
  label: string;
  name: string | null;
  /** "T3 Turn name" for the axis. */
  full: string;
  /** Mean time lost per lap here, seconds (negative = gained). */
  deltaS: number;
  /** Lost, gained, or within ±0.01 s. */
  tone: "lost" | "gained" | "level";
  /** Neutral words: "braked about 12 m earlier, 4 km/h slower at the slowest point". */
  words: string[];
  laps: number;
  apexM: number;
}

/** Within this, a corner is neither gained nor lost (spec 6.3 #6). */
export const CORNER_LEVEL_S = 0.01;

export function cornerTone(deltaS: number | null | undefined): "lost" | "gained" | "level" | null {
  if (!finite(deltaS)) return null;
  if (deltaS > CORNER_LEVEL_S) return "lost";
  if (deltaS < -CORNER_LEVEL_S) return "gained";
  return "level";
}

/** Corners by mean time lost, most lost first (corners without a mean are left out). */
export function cornerBars(
  summary: readonly CornerSummaryRow[] | null | undefined,
  model: ReviewTrackModel | null | undefined,
): CornerBar[] {
  return (summary ?? [])
    .filter((c) => finite(c.mean_time_delta_s))
    .map((c) => {
      const id = cornerIdentity(model, c.corner);
      const d = c.mean_time_delta_s as number;
      return {
        key: c.corner,
        label: id.label,
        name: id.name,
        full: id.full,
        deltaS: d,
        tone: cornerTone(d) ?? "level",
        words: cornerWords({
          brakeM: c.mean_brake_point_delta_m,
          minSpeedKph: c.mean_min_speed_delta_kph,
          exitSpeedKph: c.mean_exit_speed_delta_kph,
        }),
        laps: c.laps,
        apexM: c.apex_m,
      };
    })
    .sort((a, b) => b.deltaS - a.deltaS);
}

/** Corner key -> mean time delta, for colouring the map (6.3 #6). */
export function cornerDeltaMap(summary: readonly CornerSummaryRow[] | null | undefined): Record<string, number | null> {
  return Object.fromEntries((summary ?? []).map((c) => [c.corner, finite(c.mean_time_delta_s) ? c.mean_time_delta_s : null]));
}

// --------------------------------------------------------------------------------------- your best here (#7)

export interface BestHerePoint {
  sessionId: string;
  startedUnix: number;
  ms: number;
  s: number;
  /** The session being viewed. */
  current: boolean;
}

/**
 * The driver's best clean lap per session at this session's track (same game and track id), oldest first. Synthetic
 * and replay sessions are left out (they are never anyone's driving). The car is not filtered: before D5 the
 * session rows carry no car id reliable enough to scope by (a "car may differ" note says so).
 */
export function bestHereSeries(
  rows: readonly SessionListRow[],
  session: Pick<SessionListRow, "id" | "game" | "track_id">,
): BestHerePoint[] {
  if (!session.track_id) return [];
  return rows
    .filter(
      (r) =>
        r.game === session.game &&
        r.track_id === session.track_id &&
        !r.synthetic &&
        !isReplaySource(r.source) &&
        finite(r.best_clean_ms) &&
        r.best_clean_ms > 0,
    )
    .sort((a, b) => a.started_unix - b.started_unix)
    .map((r) => ({
      sessionId: r.id,
      startedUnix: r.started_unix,
      ms: r.best_clean_ms as number,
      s: (r.best_clean_ms as number) / 1000,
      current: r.id === session.id,
    }));
}

/** One computed sentence for the best-here chart (never an LLM): "Your best here dropped 1.3 s over 4 sessions". */
export function bestHereSentence(points: readonly BestHerePoint[]): string {
  if (!points.length) return "No clean laps here yet";
  if (points.length === 1) return "Your first session here with a clean lap";
  const first = points[0]!.ms;
  const best = Math.min(...points.map((p) => p.ms));
  const n = points.length;
  const gain = (first - best) / 1000;
  if (gain < 0.005) return `Your first session here is still your best (${n} sessions)`;
  return `Your best here dropped ${gain.toFixed(gain >= 0.995 ? 1 : 2)} s over ${n} sessions`;
}

const DELTA_STEPS_S = [0.01, 0.02, 0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 5, 10];

/** Axis for time gained / lost per corner: always includes 0, whole steps, 3-6 ticks. */
export function deltaAxis(values: readonly number[]): { domain: [number, number]; ticks: number[]; digits: number } {
  const all = values.filter(finite);
  const lo = Math.min(0, ...all);
  const hi = Math.max(0, ...all);
  const span = Math.max(hi - lo, 0.05);
  const step = DELTA_STEPS_S.find((s) => span / s <= 5) ?? 10;
  const start = Math.floor(lo / step + 1e-9) * step;
  const end = Math.ceil(hi / step - 1e-9) * step;
  const ticks: number[] = [];
  for (let t = start; t <= end + step / 1000; t += step) ticks.push(Number(t.toFixed(3)));
  return { domain: [ticks[0] ?? start, ticks[ticks.length - 1] ?? end], ticks, digits: step < 0.1 ? 2 : step < 1 ? 1 : 0 };
}
