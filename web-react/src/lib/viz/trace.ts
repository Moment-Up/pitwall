// Live inputs trace geometry (design spec v2, 5.1 "Inputs": speed, throttle and brake over the last 12 s,
// redrawn at 10 Hz). Pure: components/viz/LiveTrace.tsx draws these polylines on a canvas. Not a Pro chart: Recharts
// re-rendering at 20 Hz is too heavy on the iPad.
//
// Layout (mockup traceSvg): speed in the top lane, throttle and brake in two thin lanes under it, newest sample at
// the right edge. Unknown samples (null) and gaps in the stream (> 0.5 s between samples: a pause, a menu, a lost
// link) break the line; nothing is interpolated across them.

import { clamp, finite } from "./scale";

/** One sample of lib/live.ts's rolling history (seconds on the page's clock; throttle and brake 0..1). */
export interface TraceSample {
  t: number;
  speed: number | null;
  throttle: number | null;
  brake: number | null;
}

export const TRACE_SECONDS = 12;
/** A longer gap between two samples breaks the line. */
export const TRACE_GAP_S = 0.5;
/** Speed axis floor and rounding (km/h). */
export const SPEED_FLOOR_KPH = 100;
export const SPEED_STEP_KPH = 50;

export interface TraceLane {
  y0: number;
  y1: number;
}

export interface LiveTraceLayout {
  width: number;
  height: number;
  x0: number;
  x1: number;
  lanes: { speed: TraceLane; throttle: TraceLane; brake: TraceLane };
  /** Top of the speed lane in km/h. */
  speedMax: number;
  /** Polylines as flat [x0, y0, x1, y1, ...] arrays, broken at unknowns and gaps. */
  speed: number[][];
  throttle: number[][];
  brake: number[][];
  /** The newest sample's time, or null when there is none. */
  tNow: number | null;
}

/** The speed lane's top: the window's fastest sample rounded up to 50 km/h, at least 100. */
export function speedCeiling(maxKph: number | null | undefined): number {
  if (!finite(maxKph) || maxKph <= SPEED_FLOOR_KPH) return SPEED_FLOOR_KPH;
  return Math.ceil(maxKph / SPEED_STEP_KPH) * SPEED_STEP_KPH;
}

/** Lane boxes: speed 56 % of the height, throttle and brake the rest, 6 px apart. */
export function traceLanes(height: number, pad = 4, gap = 6): { speed: TraceLane; throttle: TraceLane; brake: TraceLane } {
  const inner = Math.max(30, height - 2 * pad);
  const speedH = inner * 0.56;
  const laneH = (inner - speedH - 2 * gap) / 2;
  const speed = { y0: pad, y1: pad + speedH };
  const throttle = { y0: speed.y1 + gap, y1: speed.y1 + gap + laneH };
  const brake = { y0: throttle.y1 + gap, y1: throttle.y1 + gap + laneH };
  return { speed, throttle, brake };
}

function polylines(
  samples: readonly TraceSample[],
  value: (p: TraceSample) => number | null,
  x: (t: number) => number,
  y: (v: number) => number,
  gapS: number,
): number[][] {
  const out: number[][] = [];
  let cur: number[] | null = null;
  let lastT: number | null = null;
  for (const p of samples) {
    const v = value(p);
    if (!finite(v) || !finite(p.t) || (lastT != null && p.t - lastT > gapS)) {
      if (cur && cur.length >= 4) out.push(cur);
      cur = null;
    }
    lastT = finite(p.t) ? p.t : lastT;
    if (!finite(v) || !finite(p.t)) continue;
    if (!cur) cur = [];
    cur.push(x(p.t), y(v));
  }
  if (cur && cur.length >= 4) out.push(cur);
  return out;
}

export interface LiveTraceOptions {
  width: number;
  height: number;
  seconds?: number;
  gapS?: number;
  /** Left padding (room for the lane labels) and right padding, px. */
  padLeft?: number;
  padRight?: number;
}

/** Polylines for the last `seconds` of history, newest at the right edge. */
export function liveTraceLayout(history: readonly TraceSample[], o: LiveTraceOptions): LiveTraceLayout {
  const width = Math.max(1, o.width);
  const height = Math.max(1, o.height);
  const seconds = o.seconds && o.seconds > 0 ? o.seconds : TRACE_SECONDS;
  const x0 = clamp(o.padLeft ?? 8, 0, width - 1);
  const x1 = Math.max(x0 + 1, width - (o.padRight ?? 8));
  const lanes = traceLanes(height);
  const last = history.length ? history[history.length - 1] : undefined;
  const tNow = last && finite(last.t) ? last.t : null;
  if (tNow == null) return { width, height, x0, x1, lanes, speedMax: SPEED_FLOOR_KPH, speed: [], throttle: [], brake: [], tNow };
  const from = tNow - seconds;
  const win = history.filter((p) => finite(p.t) && p.t >= from && p.t <= tNow);
  let maxSpeed: number | null = null;
  for (const p of win) if (finite(p.speed) && (maxSpeed == null || p.speed > maxSpeed)) maxSpeed = p.speed;
  const speedMax = speedCeiling(maxSpeed);
  const x = (t: number) => x0 + ((t - from) / seconds) * (x1 - x0);
  const lane = (l: TraceLane) => (v: number) => l.y1 - clamp(v, 0, 1) * (l.y1 - l.y0);
  const gapS = o.gapS ?? TRACE_GAP_S;
  return {
    width,
    height,
    x0,
    x1,
    lanes,
    speedMax,
    speed: polylines(win, (p) => p.speed, x, (v) => lanes.speed.y1 - clamp(v / speedMax, 0, 1) * (lanes.speed.y1 - lanes.speed.y0), gapS),
    throttle: polylines(win, (p) => p.throttle, x, lane(lanes.throttle), gapS),
    brake: polylines(win, (p) => p.brake, x, lane(lanes.brake), gapS),
    tNow,
  };
}
