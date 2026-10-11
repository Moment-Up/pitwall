// The coach card (design spec 4.3 #4, 4.5) and the coaching picks of the state cards (4.9). Pure.
//
// One message, two channels (P7): with D6 the card shows coach.by_corner[shown corner], the point the radio
// picked. Before D6 it falls back to the top observation for that corner by priority, which may differ from what
// the radio said. The UI never filters by its own thresholds and never composes advice (P9): texts are the
// backend's, verbatim. The one rule mirrored from the radio is that incident observations are never coaching
// (voice/proactive.py skips them: "the driver knows they spun").
//
// Length rule (4.5): while moving, up to 60 characters at 30 px, longer at 26 px (never smaller: 22 px is under
// ISO 15008's 16' at 70 cm), clamped to 3 lines past 130 characters (the verbatim prefix and an ellipsis; D6's
// `short` makes that rare). Stationary (pit, garage, after the session) the card shows the full text at 22 px.

import { cornerLabelOf } from "./corner";
import type { ObservationNext, SnapshotNext } from "./types";
import { confidenceWord, finite } from "./text";

export type CoachTextSize = 30 | 26 | 22;

export interface CoachPoint {
  tag: "work_on" | "good" | null;
  lap: number | null;
  /** "Work on · L6" / "Good · L6". */
  tagText: string | null;
  text: string | null;
  size: CoachTextSize;
  /** Clamp to 3 lines with an ellipsis (moving, over 130 characters). */
  clamp: boolean;
  /** Muted line when there is no point to show. */
  empty: string | null;
  /** "Seen on 3 of the last 5 laps · about 0.12 s · confidence high", or null. */
  evidence: string | null;
  source: "d6" | "observation" | null;
  /** The learned corner the point is about. */
  corner: string | null;
}

export const COACH_LARGE_MAX = 60;
export const COACH_CLAMP_OVER = 130;

/** Text size: 30 px up to 60 characters and 26 px above while moving; 22 px when stationary. */
export function textSize(text: string, moving = true): CoachTextSize {
  if (!moving) return 22;
  return text.length <= COACH_LARGE_MAX ? 30 : 26;
}

/** A moving text over 130 characters is clamped to 3 lines. */
export function needsClamp(text: string, moving = true): boolean {
  return moving && text.length > COACH_CLAMP_OVER;
}

/** Evidence line from the observation's own fields (9.6). */
export function evidenceLine(o: ObservationNext): string | null {
  const parts: string[] = [];
  if (o.consistency) parts.push(`Seen on ${o.consistency}`);
  if (finite(o.impact_s) && o.impact_s !== 0) parts.push(`about ${Math.abs(o.impact_s).toFixed(2)} s`);
  const c = confidenceWord(o.confidence);
  if (c) parts.push(`confidence ${c}`);
  return parts.length ? parts.join(" · ") : null;
}

/** Coaching observations (not incidents), highest priority first. */
export function rankedObservations(s: SnapshotNext): ObservationNext[] {
  return s.observations
    .filter((o) => o.kind !== "incident")
    .slice()
    .sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0));
}

/** The text to show: on track D6's `short`, else `text_simple` for simple-wording profiles, else `text`;
 * stationary (pit, garage, after the session) the full text (`text_simple` for simple-wording profiles). */
export function pointText(o: ObservationNext, simple: boolean, moving: boolean): string {
  if (moving && o.short) return o.short;
  if (simple && o.text_simple) return o.text_simple;
  return o.text;
}

function latestLap(s: SnapshotNext): number | null {
  if (s.coach && finite(s.coach.lap_number)) return s.coach.lap_number;
  const o = s.observations[0]?.lap_number;
  if (finite(o)) return o;
  const l = s.laps[0]?.lap_number;
  return finite(l) ? l : null;
}

function view(o: ObservationNext, source: "d6" | "observation", simple: boolean, moving: boolean): CoachPoint {
  const text = pointText(o, simple, moving);
  const tag = o.positive ? "good" : "work_on";
  const lap = finite(o.lap_number) ? o.lap_number : null;
  return {
    tag,
    lap,
    tagText: `${tag === "good" ? "Good" : "Work on"}${lap != null ? ` · L${lap}` : ""}`,
    text,
    size: textSize(text, moving),
    clamp: needsClamp(text, moving),
    empty: null,
    evidence: evidenceLine(o),
    source,
    corner: o.corner,
  };
}

function emptyPoint(empty: string): CoachPoint {
  return {
    tag: null,
    lap: null,
    tagText: null,
    text: null,
    size: 26,
    clamp: false,
    empty,
    evidence: null,
    source: null,
    corner: null,
  };
}

export const NO_REFERENCE_COACHING = "Coaching starts after your first clean lap";

/** Simple wording: D6's block says what the seated driver's profile wants; else the caller's profile flag. */
export function simpleWording(s: SnapshotNext, profileSimple: boolean): boolean {
  return typeof s.coach?.simple_wording === "boolean" ? s.coach.simple_wording : profileSimple;
}

/** The coaching point for the shown corner (spec signature). `moving` = on track (glance texts allowed). */
export function coachPoint(s: SnapshotNext, corner: string | null, simple: boolean, moving: boolean): CoachPoint {
  if (!s.reference && !s.coach) return emptyPoint(NO_REFERENCE_COACHING);
  if (corner == null) return emptyPoint("No corner ahead yet");
  if (s.coach) {
    const o = s.coach.by_corner[corner];
    if (o) return view(o, "d6", simpleWording(s, simple), moving);
  } else {
    const o = rankedObservations(s).find((x) => x.corner === corner);
    if (o) return view(o, "observation", simple, moving);
  }
  const lap = latestLap(s);
  const label = cornerLabelOf(s.track_model, corner);
  return emptyPoint(`No note for ${label}${lap != null ? ` on lap ${lap}` : ""}`);
}

/**
 * The points for a whole lap, best first. D6: `picked` (what the radio says, in its order), then the other
 * per-corner points (same filters; corrective before praise, then by priority, as coach/selection.py ranks them).
 * Before D6: coaching observations by priority.
 */
export function lapPicks(s: SnapshotNext): { picks: ObservationNext[]; source: "d6" | "observation" } {
  if (s.coach) {
    const picked = s.coach.picked.filter((o) => o.kind !== "incident");
    const ids = new Set(picked.map((o) => o.id));
    const rest = Object.values(s.coach.by_corner)
      .filter((o) => o.kind !== "incident" && !ids.has(o.id))
      .sort((a, b) => Number(a.positive) - Number(b.positive) || (b.priority ?? 0) - (a.priority ?? 0));
    return { picks: [...picked, ...rest], source: "d6" };
  }
  return { picks: rankedObservations(s), source: "observation" };
}

/** The last lap's top point, full text (the pit lane's "Next run", the Ready card's "Last lap: …" between runs). */
export function topPoint(s: SnapshotNext, simple: boolean): CoachPoint | null {
  const { picks, source } = lapPicks(s);
  const o = picks.find((x) => !x.positive) ?? picks[0];
  return o ? view(o, source, simpleWording(s, simple), false) : null;
}

/** One Work on and one Went well (Session complete card). */
export function workOnWentWell(s: SnapshotNext, simple: boolean): { workOn: CoachPoint | null; wentWell: CoachPoint | null } {
  const { picks, source } = lapPicks(s);
  const sw = simpleWording(s, simple);
  const w = picks.find((x) => !x.positive);
  const g = picks.find((x) => x.positive);
  return { workOn: w ? view(w, source, sw, false) : null, wentWell: g ? view(g, source, sw, false) : null };
}
