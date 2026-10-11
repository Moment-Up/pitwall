// Geometry for Review's small track maps (spec 6.3 #2 mini map, #6 corners on the map). Pure; tested in node.
//
// The learned track model's centreline is world (x, z) sampled every 5 m of lap distance (TrackModel.centreline,
// the same grid the Svelte TrackMap uses); it is drawn as (x, -z) so the map reads as seen from above. A corner is
// highlighted from its entry to its exit (its braking-to-exit stretch), coloured by its mean time delta.
//
// [integration] Lane V's shared `components/viz/TrackMap` (spec 10.6) replaces the drawing in
// pages/review/session/CornerMap.tsx once it lands; this module stays as the Review-specific selection logic.

import { finite } from "./words";

/** Metres between centreline points (TrackModel.centreline). */
export const CENTRELINE_STEP_M = 5;

export interface MapGeometry {
  /** Projected points (x, -z). */
  pts: [number, number][];
  minX: number;
  minY: number;
  width: number;
  height: number;
  /** A stroke width in map units that reads at any size (about 1/90 of the larger side). */
  stroke: number;
  /** Lap length covered by the points, metres. */
  lengthM: number;
}

export function mapGeometry(centreline: readonly (readonly [number, number])[] | null | undefined): MapGeometry | null {
  const raw = (centreline ?? []).filter((p) => finite(p[0]) && finite(p[1]));
  if (raw.length < 3) return null;
  const pts = raw.map(([x, z]) => [x, -z] as [number, number]);
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  for (const [x, y] of pts) {
    minX = Math.min(minX, x);
    maxX = Math.max(maxX, x);
    minY = Math.min(minY, y);
    maxY = Math.max(maxY, y);
  }
  const width = maxX - minX || 1;
  const height = maxY - minY || 1;
  return {
    pts,
    minX,
    minY,
    width,
    height,
    stroke: Math.max(width, height) / 90,
    lengthM: (pts.length - 1) * CENTRELINE_STEP_M,
  };
}

/** SVG viewBox with a margin of `pad` strokes. */
export function viewBox(g: MapGeometry, pad = 2.5): string {
  const m = g.stroke * pad;
  return `${(g.minX - m).toFixed(1)} ${(g.minY - m).toFixed(1)} ${(g.width + 2 * m).toFixed(1)} ${(g.height + 2 * m).toFixed(1)}`;
}

function idx(g: MapGeometry, m: number): number {
  return Math.max(0, Math.min(g.pts.length - 1, Math.round(m / CENTRELINE_STEP_M)));
}

function polyline(g: MapGeometry, a: number, b: number): string {
  let s = "";
  for (let i = a; i <= b; i++) {
    const p = g.pts[i];
    if (!p) continue;
    s += `${s ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`;
  }
  return s;
}

/** The whole lap, closed. */
export function lapPath(g: MapGeometry): string {
  return `${polyline(g, 0, g.pts.length - 1)}Z`;
}

/** The stretch from `fromM` to `toM` (wrapping past the line when `toM` < `fromM`). */
export function stretchPath(g: MapGeometry, fromM: number, toM: number): string {
  if (!finite(fromM) || !finite(toM)) return "";
  const a = idx(g, fromM);
  const b = idx(g, toM);
  if (a <= b) return polyline(g, a, Math.max(b, a + 1));
  return `${polyline(g, a, g.pts.length - 1)}${polyline(g, 0, b).replace(/^M/, "L")}`;
}

/** The point at a lap distance (for a corner label or a dot). */
export function pointAt(g: MapGeometry, m: number): [number, number] | null {
  if (!finite(m)) return null;
  return g.pts[idx(g, m)] ?? null;
}

/** Map colour token for a corner's mean time delta (spec 6.3 #6): green gained, red lost, neutral within ±0.01 s. */
export function deltaColourVar(deltaS: number | null | undefined): string {
  if (!finite(deltaS)) return "var(--pw-faint)";
  if (deltaS > 0.01) return "var(--pw-behind)";
  if (deltaS < -0.01) return "var(--pw-ahead)";
  return "var(--muted)";
}

export interface MapLabel {
  key: string;
  text: string;
  x: number;
  y: number;
}

/**
 * Corner labels at their apexes, in the given order of importance, skipping any closer than `minDist` map units to
 * one already placed (with every label on, neighbouring corners print over each other).
 */
export function spacedLabels(
  g: MapGeometry,
  items: readonly { key: string; text: string; atM: number | null }[],
  minDist = g.stroke * 7,
): MapLabel[] {
  const out: MapLabel[] = [];
  for (const it of items) {
    if (it.atM == null) continue;
    const p = pointAt(g, it.atM);
    if (!p) continue;
    if (out.some((o) => Math.hypot(o.x - p[0], o.y - p[1]) < minDist)) continue;
    out.push({ key: it.key, text: it.text, x: p[0], y: p[1] });
  }
  return out;
}
