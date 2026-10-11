// Lap ribbon geometry (design spec v2, 4.3 #8, 6.5 and 10.6). Pure: turns a RibbonView (lap fractions, built by
// lib/drive/ribbon.ts for Drive, or ribbonFromTrack below for a stored session) into pixel positions for the SVG in
// components/viz/LapRibbon.tsx. The mockup's ribbonSvg() is the visual reference: 12 px side padding, sector bands
// with a 2 px gap and 6 px corners, corner ticks with labels above the band, brake notches from the top, DRS dashed
// along the bottom, yellow zones hatched over the band, the car as an orange triangle under it.
//
// [critic] Label rule (6.5): a corner label closer than 34 px to one already drawn is skipped; the cursor, next and
// focus corners always draw. Long labels also need their own width ("T10-13"), so the gap is the larger of 34 px and
// the two half-widths plus 4 px. Labels never wrap and are kept inside the SVG.

import type { RibbonCorner, RibbonView } from "../drive/ribbon";
import type { CornerNext, TrackModelNext } from "../drive/types";
import { SECTOR_COLOUR_VARS, type TrackSkeleton } from "../skeleton";
import { clamp, finite, positive } from "./scale";

export type { RibbonCorner, RibbonView };

/** Default side padding (mockup: 12 px each side). */
export const RIBBON_PAD_X = 12;
/** [critic] Minimum distance between two drawn corner labels (6.5). */
export const LABEL_GAP_PX = 34;
/** Label font: 13 px / 700 sans (4.3 #8). Estimated advance per character for collision checks. */
export const LABEL_FONT_PX = 13;
const LABEL_CHAR_PX = 8;

export interface RibbonInset {
  left: number;
  right: number;
}

export interface RibbonLayoutOptions {
  width: number;
  height: number;
  /** Plot inset, so the ribbon can line up with a chart's plot area (Compare). Default 12 px each side. */
  inset?: RibbonInset;
  /** Compare: every corner label that has room (next / focus / cursor still win). Default: next and focus only. */
  allLabels?: boolean;
  /** Draw the brake notches of the cue plan (default true; Compare has none). */
  cues?: boolean;
  /** Cursor as a lap fraction 0..1 (Compare), or null. Its nearest corner's label always draws. */
  cursor?: number | null;
}

export interface RibbonBand {
  x: number;
  w: number;
  fill: string;
  label: string | null;
  labelX: number;
}

export interface RibbonTick {
  x: number;
  strong: boolean;
}

export interface RibbonLabel {
  x: number;
  text: string;
  anchor: "start" | "middle" | "end";
  strong: boolean;
}

export interface RibbonLayout {
  width: number;
  height: number;
  /** Top of the band (labels sit above it). */
  top: number;
  bandH: number;
  /** Plot extent in px. */
  x0: number;
  x1: number;
  /** Nothing but one neutral band (no telemetry, or no skeleton). */
  plain: boolean;
  bands: RibbonBand[];
  drs: { x1: number; x2: number }[];
  yellow: { x: number; w: number }[];
  ticks: RibbonTick[];
  labels: RibbonLabel[];
  focusDots: number[];
  notches: number[];
  /** The y of the label baseline, the focus dots and the DRS line. */
  labelY: number;
  focusY: number;
  drsY: number;
  notchH: number;
}

/** Pixel x of a lap fraction. */
export function ribbonX(f: number, x0: number, x1: number): number {
  return x0 + clamp(f, 0, 1) * (x1 - x0);
}

/** The corner whose apex is nearest to a lap fraction (the cursor corner), or null. */
export function cursorCorner(corners: readonly RibbonCorner[], cursor: number | null | undefined): string | null {
  if (!finite(cursor) || !corners.length) return null;
  let best: RibbonCorner | null = null;
  for (const c of corners) if (!best || Math.abs(c.at - cursor) < Math.abs(best.at - cursor)) best = c;
  return best?.name ?? null;
}

function labelWidth(text: string): number {
  return text.length * LABEL_CHAR_PX;
}

/** Labels to draw: priority corners first (always), then the rest in lap order where they have room. */
export function placeLabels(
  corners: readonly RibbonCorner[],
  x: (f: number) => number,
  width: number,
  opts: { allLabels: boolean; cursorName: string | null },
): RibbonLabel[] {
  const priority = (c: RibbonCorner) => c.next || c.focus || c.name === opts.cursorName;
  const placed: { x: number; w: number }[] = [];
  const out: RibbonLabel[] = [];
  const fits = (px: number, w: number) =>
    placed.every((p) => Math.abs(p.x - px) >= Math.max(LABEL_GAP_PX, (p.w + w) / 2 + 4));
  const place = (c: RibbonCorner) => {
    const w = labelWidth(c.label);
    const cx = x(c.at);
    // keep the text inside the SVG: anchor at the edge instead of centring past it
    let anchor: RibbonLabel["anchor"] = "middle";
    let lx = cx;
    if (cx - w / 2 < 2) {
      anchor = "start";
      lx = Math.max(2, cx - 4);
    } else if (cx + w / 2 > width - 2) {
      anchor = "end";
      lx = Math.min(width - 2, cx + 4);
    }
    placed.push({ x: cx, w });
    out.push({ x: lx, text: c.label, anchor, strong: c.next });
  };
  const sorted = [...corners].sort((a, b) => a.at - b.at);
  for (const c of sorted) if (priority(c)) place(c);
  if (opts.allLabels) for (const c of sorted) if (!priority(c) && fits(x(c.at), labelWidth(c.label))) place(c);
  return out.sort((a, b) => a.x - b.x);
}

/** Pixel layout of a ribbon. Static for a given view, size and options: only the car moves (LapRibbon). */
export function ribbonLayout(view: RibbonView, o: RibbonLayoutOptions): RibbonLayout {
  const width = Math.max(1, o.width);
  const height = Math.max(1, o.height);
  const inset = o.inset ?? { left: RIBBON_PAD_X, right: RIBBON_PAD_X };
  const x0 = clamp(inset.left, 0, width);
  const x1 = Math.max(x0 + 1, width - clamp(inset.right, 0, width));
  const top = height > 50 ? 22 : 18;
  const bandH = Math.max(4, height - top - 10);
  const x = (f: number) => ribbonX(f, x0, x1);
  const base: RibbonLayout = {
    width,
    height,
    top,
    bandH,
    x0,
    x1,
    plain: true,
    bands: [{ x: x0, w: x1 - x0, fill: "var(--surface-secondary)", label: null, labelX: x0 + 6 }],
    drs: [],
    yellow: [],
    ticks: [],
    labels: [],
    focusDots: [],
    notches: [],
    labelY: top - 6,
    focusY: top + bandH - 7,
    drsY: top + bandH - 4,
    notchH: bandH * 0.45,
  };
  if (view.empty) return base;

  const bands: RibbonBand[] = view.sectors.length
    ? view.sectors.map((s, i) => {
        const bx = x(s.a);
        const w = Math.max(1, x(s.b) - bx - 2);
        // a label needs about 26 px of band ("S3" at 13 px plus padding)
        return { x: bx, w, fill: SECTOR_COLOUR_VARS[i % 3] ?? SECTOR_COLOUR_VARS[0], label: w >= 26 ? s.label : null, labelX: bx + 6 };
      })
    : base.bands;
  const cursorName = cursorCorner(view.corners, o.cursor ?? null);
  return {
    ...base,
    plain: view.sectors.length === 0,
    bands,
    drs: view.drs.map(([a, b]) => ({ x1: x(a), x2: x(b) })),
    yellow: view.yellow.map(([a, b]) => ({ x: x(a), w: Math.max(2, x(b) - x(a)) })),
    ticks: view.corners.map((c) => ({ x: x(c.at), strong: c.next })),
    labels: placeLabels(view.corners, x, width, { allLabels: o.allLabels === true, cursorName }),
    focusDots: view.corners.filter((c) => c.focus).map((c) => x(c.at)),
    notches: o.cues === false ? [] : view.cueNotches.map(x),
  };
}

/** The car marker: an upward triangle under the band, its tip inside it (mockup). Drawn at x = 0 and moved by
 * `transform`, so the path itself never changes. */
export function carTrianglePath(layout: Pick<RibbonLayout, "top" | "bandH">): string {
  const base = layout.top + layout.bandH + 9;
  const tip = layout.top + layout.bandH - 5;
  return `M-8 ${base} L8 ${base} L0 ${tip} Z`;
}

/** A cheap identity for the static parts of a view (DL builds a new RibbonView per snapshot). */
export function ribbonSignature(v: RibbonView): string {
  const r = (n: number) => Math.round(n * 1e5);
  return [
    v.empty ? 1 : 0,
    v.lengthM ?? "",
    v.sectors.map((s) => `${r(s.a)}:${r(s.b)}:${s.label}`).join(","),
    v.corners.map((c) => `${r(c.at)}:${c.label}:${c.name}:${c.next ? 1 : 0}${c.focus ? 1 : 0}`).join(","),
    v.cueNotches.map(r).join(","),
    v.drs.map(([a, b]) => `${r(a)}-${r(b)}`).join(","),
    v.yellow.map(([a, b]) => `${r(a)}-${r(b)}`).join(","),
  ].join("|");
}

// ---- stored sessions (Review Compare): the same view model without a live snapshot ------------------------------

export interface TrackRibbonInput {
  skeleton?: TrackSkeleton | null;
  model?: TrackModelNext | null;
  /** The game's lap length (session.track_length_m) when there is no skeleton. */
  lengthM?: number | null;
  /** Learned corner names to mark as focus corners. */
  focus?: readonly string[];
  /** Learned corner name to mark as next (strong tick and label). */
  next?: string | null;
}

function cornerLabel(model: TrackModelNext, c: CornerNext): string {
  return c.label || model.corner_text?.[c.name]?.short || c.name;
}

/**
 * A RibbonView for a stored session: sectors and DRS zones from the skeleton (game metres), corners from the track
 * model (model metres), both as fractions of their own lap length. Never a car and never a yellow zone: marshal
 * flags are live state, not facts about a stored session.
 */
export function ribbonFromTrack(input: TrackRibbonInput): RibbonView {
  const sk = input.skeleton ?? null;
  const L = positive(sk?.track_length_m) ?? positive(input.lengthM) ?? positive(input.model?.length_m);
  if (L == null) {
    return { lengthM: null, sectors: [], corners: [], cueNotches: [], drs: [], yellow: [], car: null, empty: true };
  }
  const sectors = (sk?.sectors ?? [])
    .filter((s) => finite(s.start_m) && finite(s.end_m) && s.end_m > s.start_m)
    .map((s) => ({ a: clamp(s.start_m / L, 0, 1), b: clamp(s.end_m / L, 0, 1), label: s.name }));
  const focus = new Set(input.focus ?? []);
  const model = input.model ?? null;
  const ML = positive(model?.length_m);
  const corners: RibbonCorner[] =
    model && ML != null
      ? model.corners
          .filter((c) => finite(c.apex_m))
          .map((c) => ({
            at: clamp(c.apex_m / ML, 0, 1),
            label: cornerLabel(model, c),
            name: c.name,
            next: c.name === input.next,
            focus: focus.has(c.name),
            showLabel: c.name === input.next || focus.has(c.name),
          }))
          .sort((a, b) => a.at - b.at)
      : [];
  const drs = (sk?.drs_zones ?? []).flatMap((z) => {
    const segs = z.segments_m?.length ? z.segments_m : [[z.start_m, z.end_m] as [number, number]];
    return segs
      .filter(([a, b]) => finite(a) && finite(b) && b > a)
      .map(([a, b]) => [clamp(a / L, 0, 1), clamp(b / L, 0, 1)] as [number, number]);
  });
  return { lengthM: L, sectors, corners, cueNotches: [], drs, yellow: [], car: null, empty: false };
}
