// Racing line map geometry (feat/technique spec §9, components/viz/LineMap.tsx): two laps' driven lines (the
// reference and your lap, world x/z from /api/technique/compare at `step_m` metres of lap distance), numbered markers
// at the biggest differences, a zoom to one corner at true scale with a scale bar, and the chart cursor as a dot on
// each line. Pure: the component only draws what this returns. Tested in node.
//
// Screen space is the track map's (lib/viz/track-map.ts `project`: (x, z) -> (x, -z), north up), and the SVG keeps
// equal axes (one world metre is the same length across and along), so a 1.5 m difference looks like 1.5 m when
// zoomed. Pitwall does not know the track edges: nothing here draws or implies them.

import { project } from "./track-map";

export type ScreenPoint = readonly [number, number];
export type WorldPoint = readonly [number, number] | null | undefined;

export interface ViewBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

function finite(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/** World (x, z) points to screen points; unknown points stay in place as gaps (an index is a lap distance). */
export function projectLine(pts: readonly WorldPoint[] | null | undefined): (ScreenPoint | null)[] {
  return (pts ?? []).map((p) => (p && finite(p[0]) && finite(p[1]) ? project([p[0], p[1]]) : null));
}

const f2 = (v: number) => (Math.round(v * 100) / 100).toString();

/**
 * An SVG path through `pts` (every index, or only `indices` in order). An unknown point, or a jump in `indices`
 * (a window that wraps through the start line), lifts the pen.
 */
export function linePath(pts: readonly (ScreenPoint | null)[], indices?: readonly number[] | null): string {
  const order = indices ?? pts.map((_, i) => i);
  let s = "";
  let pen = false;
  let prev = -2;
  for (const i of order) {
    const p = pts[i];
    if (!p) {
      pen = false;
      prev = i;
      continue;
    }
    const contiguous = i === prev + 1 || (prev === pts.length - 1 && i === 0);
    s += `${pen && contiguous ? "L" : "M"}${f2(p[0])},${f2(p[1])}`;
    pen = true;
    prev = i;
  }
  return s;
}

/** The bounding box of the known points of every line (over `indices` when given); null with fewer than 2. */
export function boundsOf(
  lines: readonly (readonly (ScreenPoint | null)[])[],
  indices?: readonly number[] | null,
): ViewBox | null {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  let known = 0;
  for (const line of lines) {
    const order = indices ?? line.map((_, i) => i);
    for (const i of order) {
      const p = line[i];
      if (!p) continue;
      known += 1;
      if (p[0] < minX) minX = p[0];
      if (p[0] > maxX) maxX = p[0];
      if (p[1] < minY) minY = p[1];
      if (p[1] > maxY) maxY = p[1];
    }
  }
  if (known < 2) return null;
  return { x: minX, y: minY, w: maxX - minX, h: maxY - minY };
}

/** Grow a box by `padFrac` of its larger side on every side, and to at least `minSize` across (about its centre). */
export function padView(v: ViewBox, padFrac: number, minSize = 0): ViewBox {
  const pad = Math.max(v.w, v.h) * padFrac;
  let w = v.w + 2 * pad;
  let h = v.h + 2 * pad;
  const cx = v.x + v.w / 2;
  const cy = v.y + v.h / 2;
  w = Math.max(w, minSize);
  h = Math.max(h, minSize);
  return { x: cx - w / 2, y: cy - h / 2, w, h };
}

/** The index of lap distance `d` on a line sampled every `step` metres (wrapped into the lap of n samples). */
export function indexAt(d: number | null | undefined, step: number, n: number): number | null {
  if (!finite(d) || !(step > 0) || n <= 0) return null;
  const lap = n * step;
  const w = ((d % lap) + lap) % lap;
  return Math.min(n - 1, Math.round(w / step) % n);
}

/** The point at lap distance `d`, or null (unknown there). */
export function pointAtM(pts: readonly (ScreenPoint | null)[], step: number, d: number | null | undefined): ScreenPoint | null {
  const i = indexAt(d, step, pts.length);
  return i == null ? null : (pts[i] ?? null);
}

/**
 * Indices covering the lap-distance window [a, b] (metres) on a line of `n` samples every `step` metres. A window that
 * starts before the line (a < 0) or ends after it, or that is given wrapped (b < a), runs through the start line.
 */
export function windowIndices(a: number, b: number, step: number, n: number): number[] {
  if (!finite(a) || !finite(b) || !(step > 0) || n <= 0) return [];
  const lap = n * step;
  let span = b - a;
  if (span < 0) span += lap;
  if (span >= lap) return Array.from({ length: n }, (_, i) => i);
  const start = Math.floor(a / step);
  const count = Math.ceil((a + span) / step) - start + 1;
  const out: number[] = [];
  for (let k = 0; k < count; k++) out.push((((start + k) % n) + n) % n);
  return out;
}

/** A corner's zoom window (spec §9): [turn-in − pad, track-out + pad]; apex ± `fallbackHalf` when a point is unknown. */
export function cornerWindowM(
  points: { turn_in: number | null; apex: number | null; track_out: number | null },
  pad = 40,
  fallbackHalf = 100,
): [number, number] | null {
  const a = finite(points.turn_in) ? points.turn_in - pad : finite(points.apex) ? points.apex - fallbackHalf : null;
  const b = finite(points.track_out) ? points.track_out + pad : finite(points.apex) ? points.apex + fallbackHalf : null;
  if (a == null || b == null) return null;
  return [a, b];
}

/** Smallest corner view across, metres: a hairpin still shows its surroundings. */
export const MIN_CORNER_VIEW_M = 40;

/** The whole lap, padded (null when neither line has two known points). */
export function wholeLapView(lines: readonly (readonly (ScreenPoint | null)[])[]): ViewBox | null {
  const b = boundsOf(lines);
  return b ? padView(b, 0.06, 1) : null;
}

/** One corner at true scale: both lines' points inside the window, padded, at least MIN_CORNER_VIEW_M across. */
export function cornerView(
  lines: readonly (readonly (ScreenPoint | null)[])[],
  step: number,
  windowM: readonly [number, number],
): ViewBox | null {
  const n = Math.max(0, ...lines.map((l) => l.length));
  const idx = windowIndices(windowM[0], windowM[1], step, n);
  const b = boundsOf(lines, idx);
  return b ? padView(b, 0.12, MIN_CORNER_VIEW_M) : null;
}

/**
 * Grow a view about its centre to the box's aspect (width / height), so the drawing fills the box and the scale bar
 * sits in the box's corner. Equal axes are kept: only the shorter side grows. Unchanged without a known aspect.
 */
export function fitAspect(v: ViewBox, aspect: number | null | undefined): ViewBox {
  if (!finite(aspect) || aspect <= 0 || v.w <= 0 || v.h <= 0) return v;
  const cx = v.x + v.w / 2;
  const cy = v.y + v.h / 2;
  let w = v.w;
  let h = v.h;
  if (w / h < aspect) w = h * aspect;
  else h = w / aspect;
  return { x: cx - w / 2, y: cy - h / 2, w, h };
}

export interface PlacedLabel {
  x: number;
  y: number;
  anchor: "start" | "end";
}

/**
 * Where to write the labels of points (turn-in, apex, track-out) so that close points do not print over each other:
 * each label tries above-right, below-right, above-left, below-left of its point and takes the first spot clear of
 * the labels already placed. `u` is the mark unit (markUnit), `chars` each label's length.
 */
export function placeLabels(points: readonly ScreenPoint[], chars: readonly number[], u: number): PlacedLabel[] {
  const charW = u * 0.75;
  const lineH = u * 1.4;
  const boxes: { x0: number; x1: number; y0: number; y1: number }[] = [];
  const out: PlacedLabel[] = [];
  points.forEach((p, i) => {
    const w = (chars[i] ?? 6) * charW;
    const tries: PlacedLabel[] = [
      { x: p[0] + u * 1.1, y: p[1] - u * 0.8, anchor: "start" },
      { x: p[0] + u * 1.1, y: p[1] + u * 1.9, anchor: "start" },
      { x: p[0] - u * 1.1, y: p[1] - u * 0.8, anchor: "end" },
      { x: p[0] - u * 1.1, y: p[1] + u * 1.9, anchor: "end" },
    ];
    const boxOf = (t: PlacedLabel) => ({
      x0: t.anchor === "start" ? t.x : t.x - w,
      x1: t.anchor === "start" ? t.x + w : t.x,
      y0: t.y - lineH,
      y1: t.y,
    });
    const clear = (b: ReturnType<typeof boxOf>) => boxes.every((o) => b.x1 < o.x0 || b.x0 > o.x1 || b.y1 < o.y0 || b.y0 > o.y1);
    const pick = tries.find((t) => clear(boxOf(t))) ?? tries[0]!;
    boxes.push(boxOf(pick));
    out.push(pick);
  });
  return out;
}

/**
 * Marker positions that keep `minDist` apart: a marker that would sit on an earlier one moves to the nearest clear
 * spot on rings around its true point (the component draws a short leader back to the true point). Order matters:
 * earlier markers (bigger differences) keep their place.
 */
export function spreadMarkers(points: readonly ScreenPoint[], minDist: number): ScreenPoint[] {
  const placed: ScreenPoint[] = [];
  const clear = (q: ScreenPoint) => placed.every((o) => Math.hypot(o[0] - q[0], o[1] - q[1]) >= minDist);
  for (const p of points) {
    let pick: ScreenPoint = p;
    if (!clear(p)) {
      search: for (let ring = 1; ring <= 4; ring++) {
        for (let k = 0; k < 12; k++) {
          const a = -Math.PI / 2 + (k * Math.PI) / 6; // start straight up, go clockwise
          const q: ScreenPoint = [p[0] + Math.cos(a) * minDist * ring, p[1] + Math.sin(a) * minDist * ring];
          if (clear(q)) {
            pick = q;
            break search;
          }
        }
      }
    }
    placed.push(pick);
  }
  return placed;
}

const NICE_BARS = [5, 10, 20, 50, 100, 200, 500, 1000] as const;

/** A round scale-bar length near a fifth of the view's width (metres). */
export function niceBarM(widthM: number): number {
  if (!finite(widthM) || widthM <= 0) return 10;
  const target = widthM / 5;
  let best: number = NICE_BARS[0];
  for (const n of NICE_BARS) if (n <= target) best = n;
  return best;
}

export interface ScaleBar {
  x1: number;
  x2: number;
  y: number;
  /** Tick height and label offset in world units. */
  tick: number;
  metres: number;
  label: string;
}

/** A scale bar of `metres` in the view's lower-left corner (world units = metres). */
export function scaleBar(view: ViewBox, metres: number): ScaleBar {
  const u = Math.max(view.w, view.h) / 60;
  const x1 = view.x + u * 2;
  const y = view.y + view.h - u * 2;
  return { x1, x2: x1 + metres, y, tick: u * 0.8, metres, label: `${metres} m` };
}

/** World units for one "size unit" of marks drawn in world space (dots, numbers): a sixtieth of the view. */
export function markUnit(view: ViewBox): number {
  return Math.max(view.w, view.h) / 60;
}

/** Whether a screen point lies inside the view (cursor dots outside a zoomed corner are not drawn). */
export function inView(p: ScreenPoint | null, v: ViewBox): p is ScreenPoint {
  return !!p && p[0] >= v.x && p[0] <= v.x + v.w && p[1] >= v.y && p[1] <= v.y + v.h;
}

/** "x y w h" for the SVG viewBox attribute. */
export function viewBoxAttr(v: ViewBox): string {
  return `${f2(v.x)} ${f2(v.y)} ${f2(v.w)} ${f2(v.h)}`;
}
