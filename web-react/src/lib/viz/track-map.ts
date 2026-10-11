// Track map geometry (design spec v2, 5.1, 5.2, 6.3 and 10.6): a pure port of web/src/lib/TrackMap.svelte's
// derivations, so components/viz/TrackMap.tsx only draws what this returns.
//
// Kept from the Svelte map: the learned centreline is authoritative and the game outline prior is drawn (dashed,
// labelled; the component puts its attribution one tap away) only while the model has no line; skeleton distances
// (game metres) map onto the line by lap fraction (toModel); sector boundaries are cross ticks with S2 / S3 labels;
// marshal zones are faint ticks; live yellow zones are drawn only for live data; DRS dashed, active aero solid; learned
// braking (entry -> apex) in the brake colour; physics prior windows hatched and dropped where learned braking or the
// AI field's braking covers them.
// Changed for v2: sector identity is neutral (three grey casing steps told apart by their labels, 9.2); corner labels
// are the official ones (label -> corner_text.short -> learned name, 4.5); the Car wall can colour each sector by
// its timing status as set (5.1); segment deltas are green gained / red lost / neutral within +-0.01 s (6.3); focus
// corners get an accent ring; labels that would overlap another are skipped (highlight and focus first).
// Track knowledge (commit 0d5fec1, lib/viz/knowledge.ts): while the model has no line, the AI field's median line
// (layer L0b) is drawn dashed ahead of the outline seed, with its gaps left open; the field's braking zones that no
// learned corner covers are dotted on whichever line is shown, with heads-up points; both are labelled as an AI
// reference in the legend. Line priority: learned model > AI field > game outline.

import type { CornerNext, TrackModelNext } from "../drive/types";
import type { TimingStatus } from "../drive/timing";
import { SECTOR_COLOUR_VARS, activeAeroZones, zoneTitle, type SkeletonZone, type TrackSkeleton } from "../skeleton";
import {
  fieldCornerLabel,
  fieldCorners,
  fieldLinePoints,
  fieldLineTitle,
  fieldZoneTitle,
  fieldZones,
  knowledgeLengthM,
  knowledgeMatches,
  minSupport,
  type TrackKnowledge,
} from "./knowledge";
import { drawsOutline, hasCentreline, priorTitle, uncoveredPriorPieces, type BrakePrior, type TrackOutline } from "./outline";
import { finite, mapMetres, positive, wrapMetres } from "./scale";

/** Centreline spacing of TrackModel.centreline (and the outline's default). */
export const CENTRELINE_STEP_M = 5;
/** Segment deltas within this many seconds are neutral (6.3). */
export const SEGMENT_NEUTRAL_S = 0.01;

export type MapLabels = "all" | "key" | "none";

export interface MapGeometry {
  /** Screen-space points (x, -z): north up. One per `step` metres of the line; null where the line is unknown (the AI
   * field's line before the field has driven there): paths lift the pen across a gap. */
  pts: readonly ([number, number] | null)[];
  /** Every point is known (the closed line may be closed with Z). */
  complete: boolean;
  step: number;
  /** The line's own lap length (model, field or outline metres). */
  lengthM: number;
  minX: number;
  minY: number;
  w: number;
  h: number;
  /** The base stroke width in world units (Svelte: largest side / 110). */
  s: number;
  centre: [number, number];
}

/** World (x, z) -> screen (x, -z). */
export function project(p: readonly [number, number]): [number, number] {
  return [p[0], -p[1]];
}

type LinePoint = readonly [number | null | undefined, number | null | undefined] | null | undefined;

/** Geometry of a centreline, or null when it is not drawable (fewer than 3 finite points). Unknown points stay in
 * place as gaps (an index is a lap distance: dropping one would shift every later point along the lap). */
export function mapGeometry(
  centreline: readonly LinePoint[] | null | undefined,
  step = CENTRELINE_STEP_M,
  lengthM?: number | null,
): MapGeometry | null {
  const pts = (centreline ?? []).map((p): [number, number] | null => {
    const x = p?.[0];
    const z = p?.[1];
    return finite(x) && finite(z) ? project([x, z]) : null;
  });
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  let known = 0;
  for (const p of pts) {
    if (!p) continue;
    known += 1;
    const [x, y] = p;
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
    if (y < minY) minY = y;
    if (y > maxY) maxY = y;
  }
  if (known < 3) return null;
  const w = maxX - minX || 1;
  const h = maxY - minY || 1;
  const st = positive(step) ?? CENTRELINE_STEP_M;
  return {
    pts,
    complete: known === pts.length,
    step: st,
    lengthM: positive(lengthM) ?? pts.length * st,
    minX,
    minY,
    w,
    h,
    s: Math.max(w, h) / 110,
    centre: [minX + w / 2, minY + h / 2],
  };
}

function index(g: MapGeometry, d: number): number {
  const i = Math.round(wrapMetres(d, g.lengthM) / g.step);
  return Math.max(0, Math.min(g.pts.length - 1, i));
}

/** The line point nearest to `d` metres of the line (wrapped into the lap), or null (unknown there). */
export function pointAt(g: MapGeometry, d: number): [number, number] | null {
  if (!finite(d)) return null;
  const p = g.pts[index(g, d)];
  return p ? [p[0], p[1]] : null;
}

const f1 = (v: number) => v.toFixed(1);

/** One non-wrapping piece of the line from `a` to `b` metres; closes onto the first point when it reaches the end.
 * An unknown point lifts the pen (the next known point starts a new subpath). */
function piece(g: MapGeometry, a: number, b: number): string {
  const last = g.pts.length - 1;
  const i0 = Math.max(0, Math.min(last, Math.floor(a / g.step)));
  const i1 = Math.max(0, Math.min(last, Math.ceil(b / g.step)));
  if (i1 < i0) return "";
  let s = "";
  let pen = false;
  for (let i = i0; i <= i1; i++) {
    const p = g.pts[i];
    if (!p) {
      pen = false;
      continue;
    }
    s += `${pen ? "L" : "M"}${f1(p[0])},${f1(p[1])}`;
    pen = true;
  }
  const first = g.pts[0];
  if (pen && b >= g.lengthM - g.step / 2 && first && i1 === last) s += `L${f1(first[0])},${f1(first[1])}`;
  return s;
}

/** The line from `a` to `b` metres; a piece that runs through the line (b < a) is split at the start. */
export function pathBetween(g: MapGeometry, a: number, b: number): string {
  if (!finite(a) || !finite(b)) return "";
  if (b < a) return piece(g, a, g.lengthM) + piece(g, 0, b);
  return piece(g, a, b);
}

/** The whole line, closed when every point is known (a line with gaps is never closed across one). */
export function fullPath(g: MapGeometry): string {
  return `${piece(g, 0, (g.pts.length - 1) * g.step)}${g.complete ? "Z" : ""}`;
}

export interface Segment {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

/** A short bar across the line at `d` metres (perpendicular to the local direction), `half` long each side. */
export function crossTick(g: MapGeometry, d: number, half: number): Segment | null {
  const p = pointAt(g, d);
  const a = pointAt(g, d - g.step);
  const b = pointAt(g, d + g.step);
  if (!p || !a || !b) return null;
  let tx = b[0] - a[0];
  let ty = b[1] - a[1];
  const n = Math.hypot(tx, ty) || 1;
  tx /= n;
  ty /= n;
  return { x1: p[0] - ty * half, y1: p[1] + tx * half, x2: p[0] + ty * half, y2: p[1] - tx * half };
}

// ---- colours (tokens only) ---------------------------------------------------------------------------------------

/** Line colour of a sector by its timing status as set (Car wall). Neutral and unknown keep the plain line. */
export function sectorStatusColour(st: TimingStatus | "running" | "future" | null | undefined): string | null {
  switch (st) {
    case "rec":
      return "var(--pw-rec)";
    case "pb":
    case "sb":
      return "var(--pw-pb)";
    case "slower":
      return "var(--pw-slower)";
    case "invalid":
      return "var(--pw-faint)";
    default:
      return null;
  }
}

/** Colour of a corner segment by its time delta (6.3): green gained, red lost, neutral within +-0.01 s, faint unknown. */
export function segmentColour(v: number | null | undefined): string {
  if (!finite(v)) return "var(--pw-faint)";
  if (v < -SEGMENT_NEUTRAL_S) return "var(--pw-ahead)";
  if (v > SEGMENT_NEUTRAL_S) return "var(--pw-behind)";
  return "var(--muted)";
}

/** Game numbers of the marshal zones under a live yellow. `flags` are the live snapshot's marshal_flags (preferred);
 * `liveFlags` says the skeleton's own flags are live (the Svelte contract). Anything else draws no yellow: a flag
 * is live state, never a fact about a stored session. */
export function liveYellowZones(
  skeleton: TrackSkeleton | null | undefined,
  flags: readonly { game_number: number; flag: string }[] | null | undefined,
  liveFlags: boolean,
): Set<number> {
  if (flags) return new Set(flags.filter((f) => f.flag === "yellow").map((f) => f.game_number));
  if (liveFlags) return new Set((skeleton?.marshal_zones ?? []).filter((z) => z.flag === "yellow").map((z) => z.game_number));
  return new Set();
}

/** The official label of a learned corner: label -> sheet short text -> learned name (4.5). */
export function mapCornerLabel(model: TrackModelNext, c: CornerNext): string {
  return c.label || model.corner_text?.[c.name]?.short || c.name;
}

// ---- layout ------------------------------------------------------------------------------------------------------

export interface TrackMapInput {
  model?: TrackModelNext | null;
  outline?: TrackOutline | null;
  skeleton?: TrackSkeleton | null;
  /** The game's lap length when there is no skeleton (for game-metre inputs). */
  lengthM?: number | null;
  highlight?: string | null;
  focus?: readonly string[] | null;
  segmentDelta?: Readonly<Record<string, number | null>> | null;
  sectorStatus?: readonly (TimingStatus | "running" | "future" | null | undefined)[] | null;
  /** Live yellow marshal zones (liveYellowZones). */
  yellow?: ReadonlySet<number> | null;
  /** Brake notches: the cue plan's targets in game metres (`cues.cues[].target_m`, Drive › Track 5.2). */
  cueTargetsM?: readonly number[] | null;
  prior?: BrakePrior | null;
  /** Track knowledge from the live snapshot (`track_knowledge`): the AI field's line and braking zones, an AI
   * reference. Ignored when it is for another track than the model's. */
  knowledge?: TrackKnowledge | null;
  labels?: MapLabels;
  /** The rendered size in px, when known: keeps labels between 12 and 20 px and strokes legible at any map size. */
  pixelSize?: { width: number; height: number } | null;
}

export interface MapLine {
  d: string;
  colour: string;
  width: number;
  dash?: string;
  opacity?: number;
  /** Tooltip (an SVG <title>). */
  title?: string;
}

export interface MapText {
  x: number;
  y: number;
  text: string;
  anchor: "start" | "middle" | "end";
}

export interface MapCorner {
  name: string;
  label: string;
  x: number;
  y: number;
  r: number;
  highlight: boolean;
  focus: boolean;
  /** Where the label is drawn, or null (skipped: overlap or label mode). */
  text: MapText | null;
}

/** One AI-field braking zone (dotted), with its heads-up point when the field's support allows one. */
export interface MapFieldZone {
  key: string;
  d: string;
  title: string;
  headsUp: [number, number] | null;
}

/** A field corner while the field's line is drawn: a muted ring and its label (no learned corner exists yet). */
export interface MapFieldCorner {
  key: string;
  label: string;
  x: number;
  y: number;
  r: number;
  text: MapText | null;
}

export type MapSource = "model" | "field" | "outline";

export interface TrackMapLayout {
  /** Which line is drawn: the learned model (authoritative), the AI field's median line, or the game outline seed. */
  source: MapSource;
  geom: MapGeometry;
  /** The game lap length used to map game metres onto the line (null = identity). */
  gameLengthM: number | null;
  viewBox: { x: number; y: number; w: number; h: number };
  s: number;
  font: number;
  sectorFont: number;
  /** The car marker's radius (6-10 px when the rendered size is known). */
  carR: number;
  full: string;
  casings: MapLine[];
  lines: MapLine[];
  zones: MapLine[];
  yellow: MapLine[];
  brake: MapLine[];
  /** AI-field braking zones no learned corner covers (dotted, an AI reference). */
  field: MapFieldZone[];
  fieldCorners: MapFieldCorner[];
  prior: { key: string; d: string; title: string }[];
  marshalTicks: (Segment & { title: string })[];
  /** Brake notches across the line at the cue plan's targets. */
  notches: Segment[];
  sectorTicks: (Segment & { label: MapText })[];
  start: Segment | null;
  corners: MapCorner[];
  /** The label of a line that is not the driver's (the outline's, or "AI field reference"), top left. */
  sourceLabel: MapText | null;
  /** Legend lines under the map (physics estimate, AI field braking), one per layer drawn. */
  legend: (MapText & { size: number })[];
}

interface Box {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

function textBox(t: MapText, font: number): Box {
  const w = t.text.length * font * 0.62;
  const x0 = t.anchor === "start" ? t.x : t.anchor === "end" ? t.x - w : t.x - w / 2;
  return { x0, y0: t.y - font * 0.8, x1: x0 + w, y1: t.y + font * 0.2 };
}

function overlaps(a: Box, b: Box): boolean {
  return a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;
}

/** A label at `gap` from `p` in the unit direction (dx, dy), anchored so the text grows away from the point. */
function textToward(p: [number, number], dx: number, dy: number, gap: number, font: number, text: string): MapText {
  const x = p[0] + dx * gap;
  const y = p[1] + dy * gap;
  if (dx > 0.35) return { x, y: y + font * 0.35, text, anchor: "start" };
  if (dx < -0.35) return { x, y: y + font * 0.35, text, anchor: "end" };
  return { x, y: dy > 0 ? y + font * 0.85 : y - font * 0.15, text, anchor: "middle" };
}

const COMPASS: readonly [number, number][] = [
  [1, 0],
  [-1, 0],
  [0, -1],
  [0, 1],
  [0.7071, -0.7071],
  [-0.7071, -0.7071],
  [0.7071, 0.7071],
  [-0.7071, 0.7071],
];

/** Candidate directions for a label at line distance `d`, best first: outward from the map centre, the two normals
 * of the line (outward side first), then the compass. */
function directions(g: MapGeometry, p: [number, number], d: number): [number, number][] {
  const out: [number, number][] = [];
  const ox = p[0] - g.centre[0];
  const oy = p[1] - g.centre[1];
  const on = Math.hypot(ox, oy);
  if (on > 0) out.push([ox / on, oy / on]);
  const a = pointAt(g, d - g.step * 2);
  const b = pointAt(g, d + g.step * 2);
  if (a && b) {
    const tx = b[0] - a[0];
    const ty = b[1] - a[1];
    const tn = Math.hypot(tx, ty);
    if (tn > 0) {
      const n1: [number, number] = [-ty / tn, tx / tn];
      const n2: [number, number] = [ty / tn, -tx / tn];
      const outFirst = n1[0] * ox + n1[1] * oy >= 0;
      out.push(...(outFirst ? [n1, n2] : [n2, n1]));
    }
  }
  out.push(...COMPASS);
  return out;
}

/** Line points (every other one) inside a box grown by `clear`: how much of the circuit a label would cover. */
function lineHits(g: MapGeometry, box: Box, clear: number): number {
  let n = 0;
  for (let i = 0; i < g.pts.length; i += 2) {
    const q = g.pts[i];
    if (q && q[0] > box.x0 - clear && q[0] < box.x1 + clear && q[1] > box.y0 - clear && q[1] < box.y1 + clear) n += 1;
  }
  return n;
}

/**
 * Place a label off the line: the first candidate that covers the fewest line points and no placed label. Null when
 * every candidate overlaps a placed label (the caller skips it), unless `force` (the highlighted corner).
 */
function placeText(
  g: MapGeometry,
  p: [number, number],
  d: number,
  gap: number,
  font: number,
  text: string,
  placed: readonly Box[],
  clear: number,
  force = false,
): MapText | null {
  let best: MapText | null = null;
  let bestScore = Infinity;
  let first: MapText | null = null;
  for (const [dx, dy] of directions(g, p, d)) {
    const t = textToward(p, dx, dy, gap, font, text);
    first ??= t;
    const box = textBox(t, font);
    if (placed.some((b) => overlaps(b, box))) continue;
    const score = lineHits(g, box, clear);
    if (score < bestScore) {
      best = t;
      bestScore = score;
      if (score === 0) break;
    }
  }
  return best ?? (force ? first : null);
}

function zonePieces(z: SkeletonZone): [number, number][] {
  const segs = z.segments_m?.length ? z.segments_m : [[z.start_m, z.end_m] as [number, number]];
  return segs.filter(([a, b]) => finite(a) && finite(b) && b > a);
}

/** Everything the map draws, or null when there is no line (no learned centreline, no AI-field line, no usable
 * outline). */
export function trackMapLayout(input: TrackMapInput): TrackMapLayout | null {
  const model = input.model ?? null;
  const k = input.knowledge && knowledgeMatches(model, input.knowledge) ? input.knowledge : null;
  // The learned line when it exists (authoritative), else the AI field's (measured this session), else the outline.
  let source: MapSource = "model";
  let geom: MapGeometry | null = null;
  if (!hasCentreline(model)) {
    geom = k ? mapGeometry(fieldLinePoints(k), k.line?.step_m, knowledgeLengthM(k)) : null;
    if (geom) source = "field";
    else if (drawsOutline(model, input.outline)) {
      geom = mapGeometry(input.outline?.centreline, input.outline?.centreline_step_m, input.outline?.length_m);
      source = "outline";
    }
  }
  if (!geom && source === "model") geom = mapGeometry(model?.centreline, CENTRELINE_STEP_M, model?.length_m);
  if (!geom) return null;
  const g = geom;
  const fromOutline = source === "outline";
  const ownLine = source === "model";
  // Units: `s` is the stroke unit (Svelte: largest side / 110). When the rendered size is known, strokes stay between
  // 1.6 and 6 px and labels between 12 and 20 px (sector labels 11-16 px), so small maps stay legible.
  const px = input.pixelSize;
  const scale =
    px && px.width > 0 && px.height > 0 ? Math.min(px.width / (g.w + g.s * 16), px.height / (g.h + g.s * 16)) : null;
  const within = (v: number, loPx: number, hiPx: number) => (scale ? Math.min(Math.max(v, loPx / scale), hiPx / scale) : v);
  const s = within(g.s, 1.6, 6);
  const font = within(g.s * 4.2, 12, 20);
  const sectorFont = within(g.s * 3.4, 11, 16);
  const carR = within(g.s * 2.2, 6, 10);
  const sk = input.skeleton ?? null;
  const gameL = positive(sk?.track_length_m) ?? positive(input.lengthM);
  const toLine = (m: number) => mapMetres(m, gameL, g.lengthM);
  const skPath = (a: number, b: number) => pathBetween(g, toLine(a), toLine(b));
  const full = fullPath(g);

  // Neutral sector casings (the "bands"), or one plain casing.
  const sectors = (sk?.sectors ?? []).filter((x) => finite(x.start_m) && finite(x.end_m) && x.end_m > x.start_m);
  const casings: MapLine[] = sectors.length
    ? sectors.map((x, i) => ({ d: skPath(x.start_m, x.end_m), colour: SECTOR_COLOUR_VARS[i % 3] ?? SECTOR_COLOUR_VARS[0], width: s * 3.2 }))
    : [{ d: full, colour: "var(--surface-tertiary)", width: s * 3.2 }];

  // The line itself.
  const lines: MapLine[] = [];
  // Learned corners need the learned line.
  const cornersShown = ownLine ? (model?.corners ?? []) : [];
  if (!ownLine) {
    const title =
      source === "field"
        ? fieldLineTitle(k)
        : `${input.outline?.label ?? "Game outline"}: not your line and not a target`;
    lines.push({ d: full, colour: "var(--muted)", width: s * 0.9, dash: `${f1(s * 2.4)} ${f1(s * 1.6)}`, title });
  } else {
    lines.push({ d: full, colour: "var(--muted)", width: s });
    if (input.segmentDelta) {
      for (const c of cornersShown) {
        if (!(c.name in input.segmentDelta)) continue;
        lines.push({ d: pathBetween(g, c.seg_start_m, c.seg_end_m), colour: segmentColour(input.segmentDelta[c.name]), width: s * 1.4 });
      }
    } else if (input.sectorStatus && sectors.length) {
      sectors.forEach((x, i) => {
        const colour = sectorStatusColour(input.sectorStatus?.[i]);
        if (colour) lines.push({ d: skPath(x.start_m, x.end_m), colour, width: s * 1.4 });
      });
    }
  }

  // Zones: active aero solid, DRS dashed (game metres).
  const zones: MapLine[] = [];
  for (const z of activeAeroZones(sk) ?? [])
    for (const [a, b] of zonePieces(z)) zones.push({ d: skPath(a, b), colour: "var(--pw-zone-aero)", width: s * 0.45 });
  for (const z of sk?.drs_zones ?? [])
    for (const [a, b] of zonePieces(z))
      zones.push({ d: skPath(a, b), colour: "var(--pw-zone-drs)", width: s * 0.45, dash: `${f1(s * 1.6)} ${f1(s)}` });

  // Live yellow zones.
  const yellowSet = input.yellow ?? new Set<number>();
  const yellow: MapLine[] = (sk?.marshal_zones ?? [])
    .filter((z) => yellowSet.has(z.game_number))
    .flatMap((z) => zonePieces(z).map(([a, b]) => ({ d: skPath(a, b), colour: "var(--pw-flag-yellow)", width: s * 2.4, opacity: 0.85 })));

  const marshalTicks = (sk?.marshal_zones ?? []).flatMap((z) => {
    const t = crossTick(g, toLine(z.start_m), s * 0.9);
    return t ? [{ ...t, title: zoneTitle("Marshal zone", z, yellowSet.has(z.game_number)) }] : [];
  });

  const placed: Box[] = [];
  const clear = s * 1.4;
  const sectorTicks = sectors.slice(1).flatMap((x) => {
    const d = toLine(x.start_m);
    const t = crossTick(g, d, s * 2.4);
    const p = pointAt(g, d);
    const label = p ? placeText(g, p, d, s * 3.2, sectorFont, x.name, placed, clear, true) : null;
    if (!t || !label) return [];
    placed.push(textBox(label, sectorFont));
    return [{ ...t, label }];
  });

  // Learned braking (entry -> apex), split where it wraps the line.
  const learned: [number, number][] = cornersShown.flatMap((c): [number, number][] =>
    !finite(c.entry_m) || !finite(c.apex_m)
      ? []
      : c.entry_m <= c.apex_m
        ? [[c.entry_m, c.apex_m]]
        : [
            [c.entry_m, g.lengthM],
            [0, c.apex_m],
          ],
  );
  const brake: MapLine[] = learned.map(([a, b]) => ({ d: pathBetween(g, a, b), colour: "var(--pw-brake)", width: s * 0.6, opacity: 0.55 }));

  // AI-field braking zones no learned corner covers (game metres, mapped by lap fraction onto the drawn line), dotted
  // on whichever line is drawn, with the heads-up point once the field's support allows one.
  const kl = knowledgeLengthM(k);
  const fieldScale = kl != null ? g.lengthM / kl : 1;
  const support = minSupport(k);
  const fieldSpans: [number, number][] = [];
  const field: MapFieldZone[] = fieldZones(k).map((z, i) => {
    const a = (z.onset_m as number) * fieldScale;
    const b = (z.min_speed_m as number) * fieldScale;
    const spans: [number, number][] =
      b >= a
        ? [[a, b]]
        : [
            [a, g.lengthM],
            [0, b],
          ]; // a zone braking through the line
    fieldSpans.push(...spans);
    const hu = finite(z.heads_up_m) && support != null && z.support >= support ? pointAt(g, z.heads_up_m * fieldScale) : null;
    return { key: `${z.key}-${i}`, d: spans.map(([x, y]) => pathBetween(g, x, y)).join(""), title: fieldZoneTitle(z), headsUp: hu };
  });

  // Physics prior windows not covered by learned braking or by the AI field's measured braking (as the resolver drops
  // covered physics tags).
  const prior = input.prior ?? null;
  const priorScale = prior?.length_m ? g.lengthM / prior.length_m : 1;
  const priorPieces = uncoveredPriorPieces(prior, [...learned, ...fieldSpans], priorScale).map((p) => ({
    key: p.key,
    d: pathBetween(g, p.a, p.b),
    title: priorTitle(p.w, prior),
  }));

  // Corners: apex dots, focus rings, official labels (highlight and focus first; overlapping labels skipped).
  const mode = input.labels ?? "all";
  const focus = new Set(input.focus ?? []);
  const corners: MapCorner[] = [];
  // One official label can cover two learned corners (Suzuka's "T16-17" complex): its text is drawn once.
  const drawnTexts = new Set<string>();
  const ordered = [...cornersShown].filter((c) => finite(c.apex_m));
  const rank = (c: CornerNext) => (c.name === input.highlight ? 0 : focus.has(c.name) ? 1 : 2);
  ordered.sort((a, b) => rank(a) - rank(b) || a.apex_m - b.apex_m);
  for (const c of ordered) {
    const p = pointAt(g, c.apex_m);
    if (!p || !model) continue;
    const highlight = c.name === input.highlight;
    const isFocus = focus.has(c.name);
    const r = s * (highlight ? 2.4 : 1.5);
    const label = mapCornerLabel(model, c);
    let text: MapText | null = null;
    const duplicate = !highlight && drawnTexts.has(label);
    if (!duplicate && (mode === "all" || (mode === "key" && (highlight || isFocus)))) {
      text = placeText(g, p, c.apex_m, r + s * (isFocus ? 3.4 : 1.4), font, label, placed, clear, highlight);
      if (text) {
        placed.push(textBox(text, font));
        drawnTexts.add(label);
      }
    }
    corners.push({ name: c.name, label, x: p[0], y: p[1], r, highlight, focus: isFocus, text });
  }
  corners.sort((a, b) => Number(a.highlight) - Number(b.highlight)); // the highlight draws last (on top)

  // Field corners, only while the field's line is drawn (muted rings; labels in "all" mode, or when highlighted).
  const fieldCornerMarks: MapFieldCorner[] = [];
  if (source === "field") {
    for (const c of fieldCorners(k)) {
      const p = pointAt(g, (c.apex_m as number) * fieldScale);
      if (!p) continue;
      const label = fieldCornerLabel(c);
      const isKey = c.key === input.highlight || c.name === input.highlight || focus.has(c.key) || focus.has(c.name);
      let text: MapText | null = null;
      if (mode === "all" || (mode === "key" && isKey)) {
        text = placeText(g, p, (c.apex_m as number) * fieldScale, s * 2.6, font, label, placed, clear);
        if (text) placed.push(textBox(text, font));
      }
      fieldCornerMarks.push({ key: c.key, label, x: p[0], y: p[1], r: s * 1.3, text });
    }
  }

  const start = crossTick(g, 0, s * 2.2);
  const notches = !ownLine
    ? []
    : (input.cueTargetsM ?? []).flatMap((m) => {
        const t = finite(m) ? crossTick(g, toLine(m), s * 2) : null;
        return t ? [t] : [];
      });

  // View box: the line (with its casing) plus every label, plus a strip for the legend.
  const half = s * 1.8;
  let box: Box = { x0: g.minX - half, y0: g.minY - half, x1: g.minX + g.w + half, y1: g.minY + g.h + half };
  const grow = (b: Box) => {
    box = { x0: Math.min(box.x0, b.x0), y0: Math.min(box.y0, b.y0), x1: Math.max(box.x1, b.x1), y1: Math.max(box.y1, b.y1) };
  };
  for (const b of placed) grow(b);
  const margin = s * 1.5;
  let sourceLabel: MapText | null = null;
  const sourceText = source === "field" ? "AI field reference" : fromOutline ? (input.outline?.label ?? null) : null;
  if (sourceText) {
    sourceLabel = { x: box.x0, y: box.y0 - margin, text: sourceText, anchor: "start" };
    grow(textBox(sourceLabel, sectorFont));
  }
  const legendTexts = [
    ...(priorPieces.length && prior ? [`${prior.label}: estimate, not a braking point`] : []),
    ...(field.length ? ["AI field braking (dotted): a reference only"] : []),
  ];
  const legend: TrackMapLayout["legend"] = [];
  if (legendTexts.length) {
    const size = Math.min(s * 3.2, (box.x1 - box.x0) / 36);
    const top = box.y1;
    legendTexts.forEach((text, i) => {
      legend.push({ x: (box.x0 + box.x1) / 2, y: top + size * (1.6 * (i + 1) - 0.2), text, anchor: "middle", size });
    });
    grow({ x0: box.x0, y0: top, x1: box.x1, y1: top + size * (1.6 * legendTexts.length + 0.2) });
  }
  const viewBox = { x: box.x0 - margin, y: box.y0 - margin, w: box.x1 - box.x0 + 2 * margin, h: box.y1 - box.y0 + 2 * margin };

  return {
    source,
    geom: g,
    gameLengthM: gameL,
    viewBox,
    s,
    font,
    sectorFont,
    carR,
    full,
    casings,
    lines,
    zones,
    yellow,
    brake,
    field,
    fieldCorners: fieldCornerMarks,
    prior: priorPieces,
    marshalTicks,
    notches,
    sectorTicks,
    start,
    corners,
    sourceLabel,
    legend,
  };
}

/** Where a game lap distance (cursor, car fallback) sits on the drawn line, or null. */
export function mapPointAtGameM(layout: Pick<TrackMapLayout, "geom" | "gameLengthM">, m: number | null | undefined): [number, number] | null {
  if (!finite(m)) return null;
  return pointAt(layout.geom, mapMetres(m, layout.gameLengthM, layout.geom.lengthM));
}

/** The ground-plane position (x, z) of a frame's `pos` [x, y, z], or null when unknown. */
export function worldXZ(pos: readonly (number | null | undefined)[] | null | undefined): [number, number] | null {
  const x = pos?.[0];
  const z = pos?.[2];
  return finite(x) && finite(z) ? [x, z] : null;
}

/** A ground-plane position (x, z) on the map, or null when unknown. */
export function mapPointOfWorld(xz: readonly [number, number] | null | undefined): [number, number] | null {
  return xz && finite(xz[0]) && finite(xz[1]) ? project(xz) : null;
}

/** A cheap identity for the live marshal flags (memo key). */
export function flagsSignature(yellow: ReadonlySet<number>): string {
  return [...yellow].sort((a, b) => a - b).join(",");
}

// ---- memo keys ---------------------------------------------------------------------------------------------------
// The server re-sends track_model, skeleton and track_knowledge every ~5 s as NEW objects with the same content.
// The map's layout is keyed on these signatures instead of object identity, so a static refresh never re-runs the
// layout or re-renders the static SVG (spec 4.11). Each is computed once per new object (useMemo on identity).

/** FNV-1a 32-bit of a string, base 36: a cheap content key (not a security hash). */
export function cheapHash(text: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(36);
}

const dm = (v: unknown): string => (finite(v) ? String(Math.round(v * 10)) : "");
const pt = (p: readonly unknown[] | null | undefined): string => (p ? `${dm(p[0])}:${dm(p[1])}` : "");

/** Content key of a learned model: identity, version, laps, the line's size and samples, the corners as drawn and
 * their official texts. */
export function trackModelSignature(m: TrackModelNext | null | undefined): string {
  if (!m) return "";
  const cl = m.centreline ?? [];
  const corners = (m.corners ?? [])
    .map((c) => `${c.name}:${c.label ?? ""}:${dm(c.apex_m)}:${dm(c.entry_m)}:${dm(c.seg_start_m)}:${dm(c.seg_end_m)}`)
    .join(",");
  const text = m.corner_text
    ? Object.entries(m.corner_text)
        .map(([k, t]) => `${k}=${t?.short ?? ""}`)
        .join(";")
    : "";
  return [
    m.game,
    m.track_id,
    m.version,
    m.n_laps,
    dm(m.length_m),
    cl.length,
    pt(cl[0]),
    pt(cl[cl.length >> 1]),
    pt(cl[cl.length - 1]),
    cheapHash(corners),
    cheapHash(text),
  ].join("|");
}

function zonesKey(zs: readonly SkeletonZone[] | null | undefined): string {
  return (zs ?? [])
    .map(
      (z) =>
        `${z.game_number}:${z.lap_order}:${dm(z.start_m)}:${dm(z.end_m)}:${(z.segments_m ?? []).map(([a, b]) => `${dm(a)}-${dm(b)}`).join("/")}:${z.flag ?? ""}`,
    )
    .join(",");
}

/** Content key of a skeleton: lap length, sectors and every zone as drawn (marshal flags included). */
export function skeletonSignature(sk: TrackSkeleton | null | undefined): string {
  if (!sk) return "";
  const sectors = (sk.sectors ?? []).map((x) => `${x.name}:${dm(x.start_m)}:${dm(x.end_m)}`).join(",");
  return [
    sk.game,
    sk.track_id,
    dm(sk.track_length_m),
    sk.active_aero_track_status ?? "",
    cheapHash([sectors, zonesKey(sk.marshal_zones), zonesKey(sk.drs_zones), zonesKey(sk.aero_full_zones), zonesKey(sk.aero_partial_zones)].join("|")),
  ].join("|");
}

/** Content key of track knowledge: the resolver bumps `version` on every change; the sizes guard a server restart
 * (versions start again at 1). */
export function knowledgeSignature(k: TrackKnowledge | null | undefined): string {
  if (!k) return "";
  const l0b = k.layers?.L0b;
  return [
    k.game,
    k.track_id,
    k.session_uid,
    k.version,
    dm(k.track_length_m),
    k.line?.tier ?? "",
    k.line?.points?.length ?? 0,
    k.braking_zones?.length ?? 0,
    k.corners?.length ?? 0,
    l0b?.version ?? "",
    l0b?.car_laps ?? "",
    l0b?.min_support ?? "",
  ].join("|");
}
