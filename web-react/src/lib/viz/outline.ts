// Track priors for the map (ported from the module script of web/src/lib/TrackMap.svelte). Pure: types, the query,
// and the rules for when a prior may be drawn. The fetch lives in components/viz/useTrackPriors.ts.
//
// Wire shapes of /api/track/outline (TrackOutline.to_payload, analysis/track_geometry.py; layer L1a, tier
// "shipped_seed") and /api/track/prior (BrakePrior.to_payload, analysis/brake_prior.py; layer L1c, tier
// "physics_predicted"). Both are priors shown before / under the learned model: never the driver's line, never
// targets (spec 13: "/api/track/prior is never braking targets and never feeds the Drive cue"). Every prior position
// is an estimate (est_*); only the heads-up band (window_m) is drawn. Both endpoints answer 404 (no outline for the
// game / track) or 422 (length gate refused, or no lap length known): unknown stays unknown, so no map is drawn
// rather than a wrong one.

import { positive } from "./scale";

export interface TrackOutline {
  game: string;
  track_id: string;
  /** "shipped_seed" */
  tier: string;
  /** "game outline (Pits n' Giggles)" */
  label: string;
  /** MIT notice line; shown with the map whenever the outline is drawn. */
  attribution: string;
  /** The lap length the outline's lap distances use. */
  length_m: number;
  /** 5: the same grid as TrackModel.centreline. */
  centreline_step_m: number;
  /** World (x, z) at lap distance 0, 5, 10, ... */
  centreline: [number, number][];
  uncertainty?: { lateral_m: number; along_track_m: number };
  note?: string;
  licence?: string;
}

export interface PriorWindow {
  index: number;
  /** "physics_predicted" */
  tier: string;
  est_onset_m: number;
  est_apex_m: number;
  /** est_onset - uncertainty .. est_apex (the heads-up band). */
  window_m: [number, number];
  /** 1-2 non-wrapping pieces of window_m. */
  segments_m: [number, number][];
  /** Window margin before the estimated onset (100 m). */
  uncertainty_m: number;
  /** Measured p90 |estimated - driver onset| on real laps (70 m). */
  onset_error_p90_m: number;
  est_entry_kph: number;
  est_apex_kph: number;
  direction: string | null;
  turn: { label: string | null; name: string | null; voice_ok: boolean } | null;
}

export interface BrakePrior {
  /** "physics_predicted" */
  tier: string;
  /** "braking estimate (physics)" */
  label: string;
  length_m: number;
  positional: false;
  caveat: string;
  onset_error: { p90_abs_m: number; stops: number; layouts: number };
  windows: PriorWindow[];
}

/** Query string of both prior endpoints; the session's own lap length when known (else the server uses the sheet's
 * seeded length and says so). */
export function trackQuery(game: string, trackId: string, lengthM: number | null | undefined): string {
  const q = new URLSearchParams({ game, track_id: trackId });
  const L = positive(lengthM);
  if (L != null) q.set("track_length_m", String(L));
  return q.toString();
}

/** Minimum points for a drawable line. */
export const MIN_LINE_POINTS = 3;

/** The learned model has a line to draw (it always wins over the outline: it is the authoritative one). */
export function hasCentreline(model: { centreline?: readonly unknown[] | null } | null | undefined): boolean {
  return (model?.centreline?.length ?? 0) >= MIN_LINE_POINTS;
}

/** Draw the outline only while the learned model has no line, and only when the outline itself is drawable. */
export function drawsOutline(
  model: { centreline?: readonly unknown[] | null } | null | undefined,
  outline: TrackOutline | null | undefined,
): boolean {
  return !hasCentreline(model) && (outline?.centreline?.length ?? 0) >= MIN_LINE_POINTS && positive(outline?.length_m) != null;
}

/** Plain-words title of one prior window (the turn, the measured onset error and how early the band starts). */
export function priorTitle(w: PriorWindow, prior: BrakePrior | null | undefined): string {
  const turn = w.turn?.label ?? w.turn?.name ?? `stop ${w.index}`;
  const p90 = Math.round(w.onset_error_p90_m ?? prior?.onset_error?.p90_abs_m ?? Number.NaN);
  const err = Number.isFinite(p90) ? `; onset error p90 ${p90} m` : "";
  return `${turn}: heavy stop ahead (estimate${err}; band starts ${Math.round(w.uncertainty_m)} m early). ${prior?.caveat ?? ""}`.trim();
}

/**
 * Prior windows to draw, in the drawn line's metres: dropped wherever the driver's own learned braking (corner entry
 * -> apex, split where it wraps the line) already covers them, as core/track_knowledge's resolver drops covered
 * physics tags. `learned` is in the line's metres; `scale` maps the prior's metres onto the line's.
 */
export function uncoveredPriorPieces(
  prior: BrakePrior | null | undefined,
  learned: readonly [number, number][],
  scale: number,
): { key: string; w: PriorWindow; a: number; b: number }[] {
  if (!prior?.windows?.length) return [];
  const covered = (a: number, b: number) => learned.some(([e, x]) => e <= b && x >= a);
  return prior.windows
    .filter((w) => !w.segments_m.some(([a, b]) => covered(a * scale, b * scale)))
    .flatMap((w) => w.segments_m.map(([a, b], i) => ({ key: `${w.index}-${i}`, w, a: a * scale, b: b * scale })));
}
