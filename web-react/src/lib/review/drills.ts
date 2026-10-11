// Drills in Review (coachref, spec 10.6, 10.7): the Coaching page's Drills list and its detail sheet, the Work on
// card's "Drill this" button, and the way back to the lap in Compare. Pure; tested in plain node.
//
//   T3 Copse · Brake point · 2 of 3 on the point      [Closer] ›
//   3 Oct · Best: 1 m from the point · vs Sam's best · Stopped after 2 of 5 laps: the driver changed
//
// Words are counts and neutral descriptions of what happened against the target (P9); the server's own sentences
// (target, note, summary) are shown verbatim. History counts real driving only: drills refuse synthetic and replayed
// sessions, and a row the server ever flags synthetic carries the SYNTHETIC chip.

import {
  DRILL_SKILL_LABEL,
  drillKindFor,
  type DrillAttempt,
  type DrillKind,
  type DrillView,
  type DrillsQuery,
} from "../endpoints/coachref";
import type { ReviewTrackModel } from "../endpoints/review";
import { bestText, hitWords, stoppedText, trendWord, type DrillTrendWord } from "../drive/drill";
import { apexGameM } from "./compare";
import { cornerIdentity } from "./corners";
import { comparePath } from "./links";
import { dayTitle, finite } from "./words";

export const NO_DRILLS = 'No drills here yet. Start one from Drive before a run, or say "start a drill on turn 3".';

const MINUS = "−";

/** The Drills list's request for a Coaching scope (driver, game + track, car or any car). */
export function drillsQuery(
  driverId: number | null | undefined,
  scope: { track: { game: string; trackId: string }; carId: string | null } | null | undefined,
): DrillsQuery | null {
  if (driverId == null || !scope) return null;
  return { driver_id: driverId, game: scope.track.game, track_id: scope.track.trackId, car_id: scope.carId, limit: 20 };
}

export interface DrillHistoryRow {
  id: number;
  /** "Today", "3 Oct". */
  date: string;
  /** "T3 Copse": the label stored at the start (it names the part, "T1-4 (1)") and the official name when known. */
  corner: string;
  skill: string;
  /** "2 of 3 on the point" (hits of scored laps). */
  score: string;
  /** "Best: 1 m from the point" / "Best: 98 km/h". */
  best: string | null;
  trend: DrillTrendWord | null;
  /** "vs Sam's best". */
  vs: string | null;
  /** "Running" / "Stopped after 2 of 5 laps: the driver changed"; null when it ran its laps. */
  status: string | null;
  synthetic: boolean;
  /** The row in one line (list text value, screen readers). */
  text: string;
}

function statusWord(d: Pick<DrillView, "status" | "stop_reason" | "attempts" | "laps_target">): string | null {
  if (d.status === "active") return "Running";
  if (d.status === "stopped") return stoppedText(d);
  if (d.status === "abandoned") return "Not started";
  return null;
}

export function drillRow(d: DrillView, model: ReviewTrackModel | null | undefined, nowMs: number): DrillHistoryRow {
  const id = cornerIdentity(model, d.corner, d.corner_label);
  // The label stored at the start names the part ("T1-4 (1)"); the model adds the official name when it has one.
  const label = d.corner_label || id.label;
  const best = bestText(d);
  const row = {
    id: d.id,
    date: dayTitle(d.started_unix, nowMs),
    corner: id.name ? `${label} ${id.name}` : label,
    skill: d.skill_label || DRILL_SKILL_LABEL[d.kind],
    score: `${d.hits} of ${d.scored} ${hitWords(d.kind)}`,
    best: best ? `Best: ${best}` : null,
    trend: trendWord(d.trend),
    vs: d.reference?.label ? `vs ${d.reference.label}` : null,
    status: statusWord(d),
    synthetic: d.synthetic === true,
  };
  const text = [row.date, row.corner, row.skill, row.score, row.best, row.trend, row.vs, row.status]
    .filter(Boolean)
    .join(" · ");
  return { ...row, text };
}

export function drillRows(list: readonly DrillView[], model: ReviewTrackModel | null | undefined, nowMs: number): DrillHistoryRow[] {
  return [...list].sort((a, b) => b.started_unix - a.started_unix || b.id - a.id).map((d) => drillRow(d, model, nowMs));
}

// ------------------------------------------------------------------------------------------------- detail sheet

export interface AttemptRow {
  attempt: number;
  /** "L4", or "-" when the lap is unknown. */
  lap: string;
  /** How fast: "98 km/h"; null for a brake point (a lap distance says nothing: the delta says where). */
  value: string | null;
  /** Against the target in words: "1 m past the point", "3 km/h short", "on target". */
  delta: string;
  outcome: DrillAttempt["outcome"];
  /** "Hit", "Miss: incident", "Not measured: no braking measured". */
  outcomeText: string;
}

function valueText(kind: DrillKind, v: number | null): string | null {
  if (kind === "brake_point") return null;
  return finite(v) ? `${Math.round(v)} km/h` : "-";
}

function deltaText(kind: DrillKind, delta: number | null): string {
  if (!finite(delta)) return "-";
  const n = Math.round(Math.abs(delta));
  if (n === 0) return hitWords(kind);
  switch (kind) {
    case "brake_point":
      return `${n} m ${delta > 0 ? "past" : "before"} the point`;
    case "entry_speed":
      return `${n} km/h ${delta > 0 ? "faster" : "slower"} than the target`;
    default:
      return delta > 0 ? `+${n} km/h` : `${MINUS}${n} km/h, short`;
  }
}

function outcomeText(a: DrillAttempt): string {
  if (a.outcome === "hit") return "Hit";
  if (a.outcome === "miss") return a.reason ? `Miss: ${a.reason}` : "Miss";
  return a.reason ? `Not measured: ${a.reason}` : "Not measured";
}

export function attemptRows(d: Pick<DrillView, "kind" | "attempts">): AttemptRow[] {
  return d.attempts.map((a) => ({
    attempt: a.attempt,
    lap: finite(a.lap_number) ? `L${a.lap_number}` : "-",
    value: valueText(d.kind, a.value),
    delta: deltaText(d.kind, a.delta),
    outcome: a.outcome,
    outcomeText: outcomeText(a),
  }));
}

/** The best scored attempt: closest to the target (brake point, entry speed) or the fastest (minimum, exit). */
export function bestAttempt(d: Pick<DrillView, "kind" | "attempts">): DrillAttempt | null {
  const scored = d.attempts.filter((a) => a.outcome !== "unmeasured" && finite(a.value));
  if (!scored.length) return null;
  const closest = d.kind === "brake_point" || d.kind === "entry_speed";
  return scored.reduce((best, a) => {
    if (closest) return Math.abs(a.delta ?? Infinity) < Math.abs(best.delta ?? Infinity) ? a : best;
    return (a.value as number) > (best.value as number) ? a : best;
  });
}

/** "See it on the lap": Compare of the drill's session, the reference against the best attempt's lap, at the corner. */
export function drillComparePath(
  d: Pick<DrillView, "kind" | "attempts" | "session_id" | "reference" | "corner">,
  model: ReviewTrackModel | null | undefined,
  gameLengthM: number | null | undefined,
): string | null {
  const best = bestAttempt(d);
  if (!d.session_id || !best?.lap_id) return null;
  return comparePath(d.session_id, { ref: d.reference?.lap_id ?? null, lap: best.lap_id, at: apexGameM(model, d.corner, gameLengthM) });
}

// ------------------------------------------------------------------------------------------- Work on: Drill this

/** What "Drill this" needs to know about the live session (a string, so a 20 Hz snapshot re-renders nothing). */
export interface LiveDrillContext {
  game: string;
  trackId: string;
  carName: string | null;
  /** The session's owner: the seated driver. */
  driverId: number | null;
  synthetic: boolean;
}

interface LiveDrillSnap {
  connection?: { status?: string; synthetic?: boolean } | null;
  session?: { game?: string; track_id?: string | null; car_name?: string | null } | null;
  /** D4: "ended" once the game ends the session (it stays until the next session starts). */
  session_state?: string | null;
  coachref?: { driver_id?: number | null } | null;
}

/** "" when there is no running live session (telemetry not live, or the session ended: a drill could only be
 * refused); else the context as JSON. `seatedId` stands in when the server sends no owner. */
export function liveDrillKey(snap: LiveDrillSnap | null | undefined, connected: boolean, seatedId: number | null): string {
  const s = snap?.session;
  if (!connected || !snap || !s?.game || !s.track_id) return "";
  if (snap.connection?.status !== "live" || snap.session_state === "ended") return "";
  const ctx: LiveDrillContext = {
    game: s.game,
    trackId: s.track_id,
    carName: s.car_name ?? null,
    driverId: snap.coachref?.driver_id ?? seatedId,
    synthetic: snap.connection?.synthetic === true,
  };
  return JSON.stringify(ctx);
}

export function parseLiveDrill(key: string): LiveDrillContext | null {
  if (!key) return null;
  try {
    return JSON.parse(key) as LiveDrillContext;
  } catch {
    return null;
  }
}

/**
 * "Drill this" on a Work on card (spec 10.6): the live session is this session's game and track (and car, when both
 * are known), its driver is this session's driver, it is real driving, and the point maps to a drill. The kind, or
 * null when the button is not shown.
 */
export function drillThisKind(
  live: LiveDrillContext | null,
  session: { game: string; track_id: string | null; car_name?: string | null; driver_id: number | null; synthetic?: boolean },
  observationKind: string,
): DrillKind | null {
  const kind = drillKindFor(observationKind);
  if (!kind || !live || live.synthetic || session.synthetic) return null;
  if (live.game !== session.game || !session.track_id || live.trackId !== session.track_id) return null;
  if (live.carName && session.car_name && live.carName !== session.car_name) return null;
  if (session.driver_id == null || live.driverId !== session.driver_id) return null;
  return kind;
}
