// Chart data for the line offset chart (feat/technique spec §9): one corner's window of your lap's sideways distance
// from the reference line, tighter (+) / wider (−), with ticks at the reference's turn-in, apex and track-out. When the
// inside of the corner is unknown, the distance alone (|offset|, "off the reference line"). Pure; tested in node.

import type { CompareCornerTechnique, LinePointKey } from "../endpoints/technique";
import { MINUS } from "../format";
import { finite, POINT_LABEL } from "./words";

export interface OffsetRow {
  d: number;
  /** Absent where unknown: the line lifts there (never drawn as 0). */
  o?: number;
}

export function offsetRows(c: Pick<CompareCornerTechnique, "window" | "inside_known">): OffsetRow[] {
  const w = c.window;
  if (!w) return [];
  const out: OffsetRow[] = [];
  for (let i = 0; i < w.d_m.length; i++) {
    const d = w.d_m[i];
    if (!finite(d)) continue;
    const v = w.offset_m[i];
    if (finite(v)) out.push({ d, o: c.inside_known ? v : Math.abs(v) });
    else out.push({ d });
  }
  return out;
}

const NICE = [1, 2, 3, 5, 10, 20, 30] as const;

/** A symmetric domain (± a round number of metres, at least ±1 m) when the inside is known, else [0, M]. */
export function offsetDomain(rows: readonly OffsetRow[], insideKnown: boolean): { domain: [number, number]; ticks: number[] } {
  let max = 0;
  for (const r of rows) if (finite(r.o)) max = Math.max(max, Math.abs(r.o));
  const want = max * 1.1;
  const m = NICE.find((n) => n >= want) ?? Math.ceil(want);
  if (!insideKnown) return { domain: [0, m], ticks: [0, m / 2, m] };
  return { domain: [-m, m], ticks: [-m, -m / 2, 0, m / 2, m] };
}

/** "+1.5", "−1.5", "0" for the y axis. */
export function offsetTick(v: number): string {
  if (Math.abs(v) < 1e-9) return "0";
  const s = Math.abs(v).toFixed(Number.isInteger(v) ? 0 : 1);
  return `${v > 0 ? "+" : MINUS}${s}`;
}

/** The x ticks: the reference's turn-in, apex and track-out inside the window, with their names. */
export function pointTicks(c: Pick<CompareCornerTechnique, "points" | "window">): { d: number; label: string; key: LinePointKey }[] {
  const d = c.window?.d_m ?? [];
  const a = d[0];
  const b = d[d.length - 1];
  const out: { d: number; label: string; key: LinePointKey }[] = [];
  for (const k of ["turn_in", "apex", "track_out"] as const) {
    const v = c.points[k];
    if (!finite(v)) continue;
    if (finite(a) && finite(b) && (v < a || v > b)) continue;
    out.push({ d: v, label: POINT_LABEL[k], key: k });
  }
  return out;
}
