// Data shaping for the Review charts (design spec v2, 6.3, 6.5, 6.9 and 10.4): pure, so the Pro chart wrappers in
// components/viz (LapTimesChart, TraceChart) only render. Times stay in milliseconds; formatting follows 9.6 (unknown
// is "-", m:ss.S ticks, U+2212 minus).
//
// Lap-time charts put faster laps HIGHER (reversed y axis, labelled "faster ↑"): clean laps are filled dots joined by
// a line, laps that are not clean are hollow dots (the reason in words on tap), a lap with no time shows "-" at the
// slow edge. A not-clean outlier (out lap, in lap) far slower than the clean laps would squash the chart, so it is
// drawn at the slow edge and flagged "off scale" (its real time is in its label): never moved inside the scale.

import type { Comparison, LapTrace } from "../api";
import type { TimingStatus } from "../drive/timing";
import { lapTime, sector, UNKNOWN } from "../format";
import { finite, niceStep, niceTicks } from "./scale";

// ---- lap times ---------------------------------------------------------------------------------------------------

export interface LapPoint {
  /** Lap id (Compare) or session id (Progress). */
  id: number | string;
  /** Position on the x axis: lap number, or a session's index. */
  x: number;
  /** Tick text ("7", "3 Oct"); default the number. */
  xLabel?: string;
  ms: number | null;
  clean: boolean;
  /** Timing status by current standing (4.6); purple "rec" only with D2 data. */
  status?: TimingStatus | null;
  /** Why the lap is not clean, in words ("flashback", "pit out"). */
  reason?: string | null;
  /** Small tag drawn by the dot ("PB", "R"). */
  tag?: string | null;
}

export type LapDotKind = "clean" | "other" | "none";

export interface LapChartModel {
  /** Recharts rows: { x, clean?, other?, none? } (ms). A missing key is a gap. */
  rows: Record<string, number>[];
  /** The point behind each row, by x. */
  byX: ReadonlyMap<number, LapPoint>;
  /** y domain in ms: [fast, slow]; the axis is reversed so fast is at the top. */
  domain: [number, number];
  /** y ticks in ms (whole tenths). */
  ticks: number[];
  xTicks: number[];
  xDomain: [number, number];
  /** Not-clean points drawn at the slow edge because their time is outside the scale. */
  offScale: ReadonlySet<string | number>;
  /** Every point has no time: nothing to plot. */
  empty: boolean;
}

/** Tick steps for time axes, in seconds (ticks on whole tenths so m:ss.S labels are exact). */
const TIME_STEPS_S = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300];

/** y ticks for a time domain in ms: about `target` intervals on whole tenths. */
export function timeTicks(lo: number, hi: number, target = 4): number[] {
  if (!finite(lo) || !finite(hi) || hi <= lo) return finite(lo) ? [Math.round(lo / 100) * 100] : [];
  const range = (hi - lo) / 1000;
  const step = TIME_STEPS_S.find((s) => range / s <= target) ?? TIME_STEPS_S[TIME_STEPS_S.length - 1]!;
  const out: number[] = [];
  const stepMs = Math.round(step * 1000);
  for (let v = Math.ceil(lo / stepMs) * stepMs; v <= hi; v += stepMs) out.push(v);
  return out;
}

/** Axis label for a time tick: "1:31.0" (m:ss.S); seconds only under a minute ("29.5"). */
export function timeTick(ms: number): string {
  if (!finite(ms) || ms <= 0) return UNKNOWN;
  return ms >= 60_000 ? lapTime(ms, 1) : sector(ms, 1);
}

function median(xs: number[]): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m]! : (s[m - 1]! + s[m]!) / 2;
}

/** Shape lap points (and reference lines, in ms) for LapTimesChart. */
export function lapChartModel(points: readonly LapPoint[], lines: readonly number[] = []): LapChartModel {
  const timed = points.filter((p) => finite(p.ms) && (p.ms as number) > 0);
  const clean = timed.filter((p) => p.clean).map((p) => p.ms as number);
  const base = clean.length ? clean : timed.map((p) => p.ms as number);
  const xs = points.map((p) => p.x).filter(finite);
  const xDomain: [number, number] = xs.length ? [Math.min(...xs) - 0.5, Math.max(...xs) + 0.5] : [0, 1];
  const byX = new Map(points.map((p) => [p.x, p]));
  if (!base.length) {
    return {
      rows: points.map((p) => ({ x: p.x })),
      byX,
      domain: [0, 1],
      ticks: [],
      xTicks: xs,
      xDomain,
      offScale: new Set(),
      empty: true,
    };
  }
  const refLines = lines.filter((v) => finite(v) && v > 0);
  let lo = Math.min(...base, ...refLines);
  let hi = Math.max(...base, ...refLines);
  // Not-clean laps join the scale when they are near it; far slower ones (out laps) stay off scale.
  const mid = median(base) ?? hi;
  const slowLimit = Math.max(hi + Math.max(1000, (hi - lo) * 0.5), mid * 1.03);
  for (const p of timed) {
    const v = p.ms as number;
    if (v < lo) lo = v;
    else if (v > hi && v <= slowLimit) hi = v;
  }
  const pad = Math.max(150, (hi - lo) * 0.12);
  const domain: [number, number] = [lo - pad, hi + pad];
  const offScale = new Set<string | number>();
  const rows = points.map((p) => {
    const r: Record<string, number> = { x: p.x };
    if (!finite(p.ms) || p.ms <= 0) {
      r.none = domain[1];
      return r;
    }
    const v = p.ms > domain[1] ? domain[1] : p.ms;
    if (p.ms > domain[1]) offScale.add(p.id);
    if (p.clean) r.clean = v;
    else r.other = v;
    return r;
  });
  return { rows, byX, domain, ticks: timeTicks(domain[0], domain[1]), xTicks: xs, xDomain, offScale, empty: false };
}

/** A content key for lap points and reference lines: parents rebuild these arrays on every render, the chart must not
 * re-run (or re-mount its dots, which drops keyboard focus) unless the data changed. */
export function lapPointsSignature(points: readonly LapPoint[], lines: readonly number[] = []): string {
  const p = points.map((x) => `${x.id}:${x.x}:${x.xLabel ?? ""}:${x.ms ?? ""}:${x.clean ? 1 : 0}:${x.status ?? ""}:${x.reason ?? ""}:${x.tag ?? ""}`);
  return `${p.join("|")}#${lines.join(",")}`;
}

/** Words for a lap point (tooltip, tap caption, aria): "Lap 7 · 1:31.120 · not clean: track limits". */
export function lapPointWords(p: LapPoint, opts: { xName?: string; offScale?: boolean } = {}): string {
  const head = opts.xName === "" ? (p.xLabel ?? String(p.x)) : `${opts.xName ?? "Lap"} ${p.xLabel ?? p.x}`;
  const time = lapTime(p.ms);
  const state = p.clean ? "clean" : `not clean${p.reason ? `: ${p.reason}` : ""}`;
  const off = opts.offScale ? " · off the scale" : "";
  return `${head} · ${time} · ${state}${off}`;
}

// ---- traces by distance (Compare) --------------------------------------------------------------------------------

export type TraceChannel = "speed_kph" | "throttle" | "brake" | "steering" | "gear";

type TraceLike = Pick<LapTrace, "d"> & Partial<Record<TraceChannel, (number | null)[]>>;

/** Index of the row whose `d` is nearest to `d` in an ascending array, or -1. */
export function nearestIndex(ds: readonly number[], d: number): number {
  if (!ds.length || !finite(d)) return -1;
  let lo = 0;
  let hi = ds.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if ((ds[mid] as number) < d) lo = mid + 1;
    else hi = mid;
  }
  if (lo > 0 && Math.abs((ds[lo - 1] as number) - d) <= Math.abs((ds[lo] as number) - d)) return lo - 1;
  return lo;
}

/**
 * Two laps' channel on the reference lap's distance grid: rows { d, a?, b? } (a = reference, b = your lap). Both
 * traces come from the same distance resampling (/api/laps/{id}/trace?step=5), so rows usually match by index; when
 * they do not, the nearest sample within half a step is used, else the value is a gap. `scale` turns 0..1 pedals
 * into percent.
 */
export function alignTraces(
  ref: TraceLike | null | undefined,
  cmp: TraceLike | null | undefined,
  channel: TraceChannel,
  scale = 1,
): Record<string, number>[] {
  const base = ref ?? cmp;
  if (!base?.d?.length) return [];
  const step = base.d.length > 1 ? Math.abs((base.d[1] as number) - (base.d[0] as number)) || 5 : 5;
  const valueAt = (t: TraceLike | null | undefined, i: number, d: number): number | null => {
    if (!t?.d?.length) return null;
    const ch = t[channel];
    if (!ch) return null;
    let j = i;
    if (t.d[j] == null || Math.abs((t.d[j] as number) - d) > step / 2) {
      j = nearestIndex(t.d, d);
      if (j < 0 || Math.abs((t.d[j] as number) - d) > step / 2) return null;
    }
    const v = ch[j];
    return finite(v) ? v * scale : null;
  };
  return base.d.map((d, i) => {
    const r: Record<string, number> = { d };
    const a = ref ? valueAt(ref, i, d) : null;
    const b = valueAt(cmp, i, d);
    if (a != null) r.a = a;
    if (b != null) r.b = b;
    return r;
  });
}

/** The comparison's time delta by distance: rows { d, delta } in seconds (+ = your lap lost time). */
export function deltaRows(c: Pick<Comparison, "delta_d" | "delta_s"> | null | undefined): Record<string, number>[] {
  if (!c?.delta_d?.length) return [];
  const out: Record<string, number>[] = [];
  c.delta_d.forEach((d, i) => {
    const v = c.delta_s[i];
    if (!finite(d)) return;
    out.push(finite(v) ? { d, delta: v } : { d });
  });
  return out;
}

/** Values of `keys` at the row nearest to `d` (rows ascending by d); null per key when unknown. */
export function valuesAt(
  rows: readonly Record<string, number>[],
  d: number | null | undefined,
  keys: readonly string[],
): { d: number; values: Record<string, number | null> } | null {
  if (!finite(d) || !rows.length) return null;
  const ds = rows.map((r) => r.d as number);
  const i = nearestIndex(ds, d);
  const row = rows[i];
  if (!row) return null;
  const values: Record<string, number | null> = {};
  for (const k of keys) values[k] = finite(row[k]) ? (row[k] as number) : null;
  return { d: row.d as number, values };
}

/** Symmetric y domain around zero for a delta chart (at least +-0.2 s), with nice ticks. */
export function deltaDomain(rows: readonly Record<string, number>[], key = "delta"): { domain: [number, number]; ticks: number[] } {
  let m = 0.2;
  for (const r of rows) {
    const v = r[key];
    if (finite(v) && Math.abs(v) > m) m = Math.abs(v);
  }
  const ticks = niceTicks(-m, m, 4);
  const top = Math.max(m, ...ticks.map(Math.abs));
  return { domain: [-top, top], ticks };
}

/** A nice y domain and ticks covering `keys` in `rows` (speed in km/h, steering), or null when there is no value. */
export function niceDomain(
  rows: readonly Record<string, number>[],
  keys: readonly string[],
  target = 5,
): { domain: [number, number]; ticks: number[] } | null {
  let lo = Infinity;
  let hi = -Infinity;
  for (const r of rows)
    for (const k of keys) {
      const v = r[k];
      if (finite(v)) {
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      }
    }
  if (!finite(lo) || !finite(hi)) return null;
  if (hi === lo) {
    hi = lo + 1;
    lo -= 1;
  }
  const step = niceStep(hi - lo, target);
  const a = Math.floor(lo / step - 1e-9) * step;
  const b = Math.ceil(hi / step - 1e-9) * step;
  const ticks: number[] = [];
  for (let v = a; v <= b + step * 1e-9; v += step) ticks.push(Number(v.toFixed(9)));
  return { domain: [Number(a.toFixed(9)), Number(b.toFixed(9))], ticks };
}

/** Distance ticks along a lap: every kilometre (every 500 m under 3 km), from 0. */
export function distanceTicks(lengthM: number | null | undefined): number[] {
  if (!finite(lengthM) || lengthM <= 0) return [];
  const step = lengthM < 3000 ? 500 : 1000;
  const out: number[] = [];
  for (let v = 0; v <= lengthM + 1e-6; v += step) out.push(v);
  return out;
}

/** "0", "1 km", "2.5 km". */
export function distanceTick(m: number): string {
  if (!finite(m)) return UNKNOWN;
  if (m === 0) return "0";
  return `${Number((m / 1000).toFixed(1))} km`;
}
