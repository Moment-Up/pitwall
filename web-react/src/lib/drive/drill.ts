// Practice drills on Drive (coachref, spec 10.2, 10.3): the status-slot chip, the hero's DRILL chip, the coach card
// while a drill runs, the Ready card's Drill block (start, running, result) and the drill sheet's choices. Pure;
// tested in plain node.
//
//   status slot   [DRILL · T3 · 3/5 · 2 ✓]                 accent-soft, left of the Segment, tap: target + Stop drill
//   hero          T3 Copse                       [DRILL]    replaces FOCUS when the shown corner is the drill corner
//   coach card    [Drill] Turn 3 drill, 3 of 5: on the point. 2 hits.     (the radio's words, verbatim)
//                 other corners: "Drill on T3: other corners are quiet"
//
// One message, two channels (P7): drill progress arrives as the lap's coach point (kind "drill"), so the card shows
// exactly what the radio said. The UI adds no advice (P9): targets and results are the server's sentences; the only
// words made here are neutral counts ("2 of 3 on the point") and labels.

import {
  DRILL_DEFAULT_LAPS,
  DRILL_LAPS_CHOICES,
  DRILL_SKILL_LABEL,
  drillKindFor,
  type DrillAttempt,
  type DrillKind,
  type DrillOptionsResponse,
  type DrillStartRequest,
  type DrillTrend,
  type DrillUnit,
  type DrillView,
} from "../endpoints/coachref";
import { lapPicks, needsClamp, pointText, textSize, type CoachPoint } from "./coach";
import { cornerLabelOf, isFocus, officialNameOf } from "./corner";
import type { ObservationNext, SnapshotNext, TrackModelNext } from "./types";
import { finite, plural } from "./text";

export { DRILL_LAPS_CHOICES };

/** The drill in the snapshot: running, or the one that just ended (kept for the Ready card's result). */
export function drillOf(s: SnapshotNext | null | undefined): DrillView | null {
  return s?.coachref?.drill ?? null;
}

/** The running drill, or null. */
export function activeDrill(s: SnapshotNext | null | undefined): DrillView | null {
  const d = drillOf(s);
  return d && d.status === "active" ? d : null;
}

/** The drill corner (learned name): the running drill's, else the cue plan's while it is held to one corner. */
export function drillCorner(s: SnapshotNext | null | undefined): string | null {
  return activeDrill(s)?.corner ?? s?.cues?.drill_corner ?? null;
}

/** The corner as the driver reads it on the drill: the label stored at the start ("T3"), else the model's. */
export function drillLabel(s: SnapshotNext | null | undefined, d: Pick<DrillView, "corner" | "corner_label">): string {
  return d.corner_label || cornerLabelOf(s?.track_model, d.corner);
}

export function skillOf(d: Pick<DrillView, "kind" | "skill_label">): string {
  return d.skill_label || DRILL_SKILL_LABEL[d.kind];
}

const isBrakeLike = (k: DrillKind) => k === "brake_point" || k === "entry_speed";

/** "on the point" (brake point) / "on target" (speed drills). */
export function hitWords(kind: DrillKind): string {
  return kind === "brake_point" ? "on the point" : "on target";
}

// ---------------------------------------------------------------------------------------------- status slot chip

export interface DrillChipView {
  /** "DRILL · T3 · 3/5 · 2 ✓". */
  text: string;
  /** "3/5 · 2 ✓": the part that never truncates (a long label like "T1-4 (1)" ellipsizes instead). */
  progress: string;
  /** The drill's target sentence (the chip's popover). */
  targetText: string;
  label: string;
  skill: string;
  aria: string;
}

/** The status-slot chip while a drill runs (spec 10.3). */
export function drillChip(s: SnapshotNext | null | undefined): DrillChipView | null {
  const d = activeDrill(s);
  if (!d) return null;
  const label = drillLabel(s, d);
  const done = d.attempts.length;
  const progress = `${done}/${d.laps_target} · ${d.hits} ✓`;
  return {
    text: `DRILL · ${label} · ${progress}`,
    progress,
    targetText: d.target_text,
    label,
    skill: skillOf(d),
    aria: `${skillOf(d)} drill at ${label}: ${done} of ${d.laps_target} laps done, ${plural(d.hits, "hit")}`,
  };
}

// --------------------------------------------------------------------------------------------------- coach card

function emptyPoint(text: string, corner: string | null): CoachPoint {
  return { tag: null, lap: null, tagText: null, text: null, size: 26, clamp: false, empty: text, evidence: null, source: null, corner };
}

function drillPoint(o: ObservationNext, simple: boolean, moving: boolean): CoachPoint {
  const text = pointText(o, simple, moving);
  const lap = finite(o.lap_number) ? o.lap_number : null;
  return {
    tag: "drill",
    lap,
    // The point's own text counts the attempt ("Drill 1/5: …"): the tag only says what it is.
    tagText: "Drill",
    text,
    size: textSize(text, moving),
    clamp: needsClamp(text, moving),
    empty: null,
    evidence: null,
    source: "d6",
    corner: o.corner,
  };
}

/**
 * The coach card while a drill runs (spec 10.3), or null to keep the normal point. The drill corner shows its drill
 * point (the radio's words); before the first attempt, or for other corners, one muted line. After the drill ends,
 * its last point stays on the drill corner until the next lap's block replaces it.
 */
export function drillCoach(s: SnapshotNext | null | undefined, corner: string | null, simple: boolean, moving: boolean): CoachPoint | null {
  if (!s) return null;
  const d = activeDrill(s);
  // No corner ahead yet (a new session's first lap: the live track model comes with its first lap): the drill's
  // progress line, not "Coaching starts after your first clean lap".
  if (corner == null) return d ? drillProgress(s, d, null) : null;
  const point = s.coach?.by_corner?.[corner];
  if (point && point.kind === "drill" && (!d || d.corner === corner)) return drillPoint(point, simple, moving);
  if (!d) return null;
  const label = drillLabel(s, d);
  if (corner !== d.corner) return emptyPoint(`Drill on ${label}: other corners are quiet`, corner);
  return drillProgress(s, d, corner);
}

function drillProgress(s: SnapshotNext, d: DrillView, corner: string | null): CoachPoint {
  const label = drillLabel(s, d);
  const done = d.attempts.length;
  return emptyPoint(
    done === 0 ? `Drill on ${label}: first attempt on your next lap` : `Drill on ${label}: ${done} of ${d.laps_target} laps done`,
    corner,
  );
}

// ------------------------------------------------------------------------------------------- Ready card: Drill

/** The corner and drill the last lap's coaching points to (the radio's pick first): "Drill T3 · Brake point". */
export interface DrillSuggestion {
  corner: string;
  label: string;
  name: string | null;
  kind: DrillKind;
  skill: string;
  observationKind: string;
  text: string;
  request: DrillStartRequest;
}

export function drillSuggestion(s: SnapshotNext | null | undefined): DrillSuggestion | null {
  if (!s) return null;
  for (const o of lapPicks(s).picks) {
    if (o.positive || !o.corner) continue;
    const kind = drillKindFor(o.kind);
    if (!kind) continue;
    const label = o.corner_label || cornerLabelOf(s.track_model, o.corner);
    const skill = DRILL_SKILL_LABEL[kind];
    return {
      corner: o.corner,
      label,
      name: officialNameOf(s.track_model, o.corner),
      kind,
      skill,
      observationKind: o.kind,
      text: `Drill ${label} · ${skill}`,
      request: { corner: o.corner, kind, laps: DRILL_DEFAULT_LAPS, source: "work_on", observation_kind: o.kind },
    };
  }
  return null;
}

export type DrillTrendWord = "Closer" | "Steady" | "Drifting" | "Rising" | "Dropping";

export const TREND_WORD: Readonly<Record<DrillTrend, DrillTrendWord>> = {
  closer: "Closer",
  steady: "Steady",
  further: "Drifting",
  rising: "Rising",
  falling: "Dropping",
};

export function trendWord(t: DrillTrend | null | undefined): DrillTrendWord | null {
  return t ? (TREND_WORD[t] ?? null) : null;
}

/** The best attempt in words, as the server says it (coach/drills.py _best_text): "right on the point", "3 m from the
 * point", "on target", "4 km/h from the target", or the speed reached (min, exit): "98 km/h". */
export function bestText(d: Pick<DrillView, "kind" | "best" | "best_delta" | "unit">): string | null {
  if (isBrakeLike(d.kind)) {
    if (!finite(d.best_delta)) return null;
    const a = Math.abs(d.best_delta);
    if (d.kind === "brake_point") return a < 0.5 ? "right on the point" : `${Math.max(1, Math.round(a))} m from the point`;
    const n = Math.round(a);
    return n === 0 ? "on target" : `${n} km/h from the target`;
  }
  return finite(d.best) ? `${Math.round(d.best)} km/h` : null;
}

const OUTCOME_WORD: Readonly<Record<DrillAttempt["outcome"], string>> = { hit: "hit", miss: "miss", unmeasured: "not measured" };

export interface AttemptDot {
  outcome: DrillAttempt["outcome"];
  aria: string;
}

export function attemptDots(d: Pick<DrillView, "attempts" | "laps_target">): AttemptDot[] {
  return d.attempts.map((a) => ({
    outcome: a.outcome,
    aria: `Lap ${a.attempt} of ${d.laps_target}: ${OUTCOME_WORD[a.outcome]}${a.reason ? `, ${a.reason}` : ""}`,
  }));
}

/** Start the same drill again (the server sets fresh targets). */
export function againRequest(d: Pick<DrillView, "corner" | "kind" | "laps_target" | "tolerance" | "source" | "kind">): DrillStartRequest {
  return { corner: d.corner, kind: d.kind, laps: d.laps_target, tolerance: d.tolerance, source: d.source === "work_on" ? "work_on" : "manual" };
}

/** Why a drill stopped early, in words (coach/drills.py STOP_REASONS); the driver's own Stop says nothing more. */
const STOP_WHY: Readonly<Record<string, string>> = {
  driver_changed: "the driver changed",
  context_changed: "the car, track or conditions changed",
  model_changed: "the track map changed",
  timed_out: "no lap for 30 minutes",
  service_restart: "Pitwall restarted",
};

/** "Stopped after 2 of 5 laps: the driver changed" (null unless it stopped with laps counted). */
export function stoppedText(d: Pick<DrillView, "status" | "stop_reason" | "attempts" | "laps_target">): string | null {
  if (d.status !== "stopped") return null;
  const why = STOP_WHY[d.stop_reason ?? ""];
  return `Stopped after ${d.attempts.length} of ${d.laps_target} laps${why ? `: ${why}` : ""}`;
}

export interface DrillResultView {
  id: number;
  /** "T3 · Brake point". */
  title: string;
  /** "2 of 3 on the point". */
  score: string;
  best: string | null;
  trend: DrillTrendWord | null;
  dots: AttemptDot[];
  /** The server's summary sentence, verbatim. */
  summary: string | null;
  /** "Stopped after 2 of 5 laps: the driver changed", or null when it ran its laps. */
  stopped: string | null;
  /** "vs Sam's best". */
  reference: string | null;
  again: DrillStartRequest;
}

export function drillResult(s: SnapshotNext | null | undefined, d: DrillView): DrillResultView {
  return {
    id: d.id,
    title: `${drillLabel(s, d)} · ${skillOf(d)}`,
    score: `${d.hits} of ${d.scored} ${hitWords(d.kind)}`,
    best: bestText(d),
    trend: trendWord(d.trend),
    dots: attemptDots(d),
    summary: d.summary_text,
    stopped: stoppedText(d),
    reference: d.reference?.label ? `vs ${d.reference.label}` : null,
    again: againRequest(d),
  };
}

export type DrillBlockView =
  | { kind: "none"; suggestion: DrillSuggestion | null }
  | {
      kind: "active";
      /** "Drill · T3 · Brake point · 2 of 5 done · 1 hit". */
      line: string;
      targetText: string;
      note: string | null;
      corner: string;
    }
  | { kind: "result"; result: DrillResultView };

/** The Ready card's Drill block; null on a server without coachref (no block at all). */
export function drillBlock(s: SnapshotNext | null | undefined): DrillBlockView | null {
  if (!s || s.coachref == null) return null;
  const d = drillOf(s);
  if (d && d.status === "active") {
    const label = drillLabel(s, d);
    const done = d.attempts.length;
    const progress =
      // "2 of 5 done", as the chip (2/5) and the radio ("2 of 5 done") count: "lap 2 of 5" would read as the lap
      // being driven, which the server's texts mean by it.
      done === 0 ? `${d.laps_target} laps, from your next lap` : `${done} of ${d.laps_target} done · ${plural(d.hits, "hit")}`;
    return {
      kind: "active",
      line: `Drill · ${label} · ${skillOf(d)} · ${progress}`,
      targetText: d.target_text,
      note: d.note,
      corner: d.corner,
    };
  }
  if (d && d.status !== "abandoned" && d.attempts.length > 0 && drivenHere(s, d)) {
    return { kind: "result", result: drillResult(s, d) };
  }
  return { kind: "none", suggestion: drillSuggestion(s) };
}

/** The drill was driven in the session on screen: its result belongs on this session's Ready card. A result from an
 * earlier session (another track, last night) waits in Review › Coaching instead: here it would push out "Last lap:"
 * and the FOCUS row, and before a first lap it is about somewhere else (acceptance B3). */
function drivenHere(s: SnapshotNext, d: DrillView): boolean {
  if (d.session_id != null && s.session_id != null) return d.session_id === s.session_id;
  const laps = new Set(s.laps.map((l) => l.lap_id));
  return d.attempts.some((a) => a.lap_id != null && laps.has(a.lap_id));
}

// ------------------------------------------------------------------------------------------ Session complete

export interface EndedDrillView {
  /** "Drill T12 · Brake point". */
  title: string;
  /** "2 of 2 on the point (2 of 5 laps)". */
  line: string;
}

/** The drill driven in this session (running or ended, with an attempt on one of this session's laps) for the
 * Session complete card; null otherwise. */
export function endedDrill(s: SnapshotNext | null | undefined): EndedDrillView | null {
  const d = drillOf(s);
  if (!s || !d || d.status === "abandoned" || d.attempts.length === 0) return null;
  const laps = new Set(s.laps.map((l) => l.lap_id));
  if (!d.attempts.some((a) => a.lap_id != null && laps.has(a.lap_id))) return null;
  return {
    title: `Drill ${drillLabel(s, d)} · ${skillOf(d)}`,
    line: `${d.hits} of ${d.scored} ${hitWords(d.kind)} (${d.attempts.length} of ${d.laps_target} laps)`,
  };
}

// ------------------------------------------------------------------------------------------------- drill sheet

export interface SheetCorner {
  name: string;
  label: string;
  officialName: string | null;
  focus: boolean;
  /** The last lap's coaching has a correction here. */
  workOn: boolean;
}

/** Every learned corner in lap order (spec 10.2 #1), with its FOCUS / Work on chips. */
export function sheetCorners(s: SnapshotNext | null | undefined): SheetCorner[] {
  const model = s?.track_model;
  if (!s || !model?.corners.length) return [];
  const work = new Set<string>();
  for (const o of lapPicks(s).picks) if (!o.positive && o.corner && o.kind !== "drill") work.add(o.corner);
  return cornersOf(model, (name) => isFocus(s.cues, name), (name) => work.has(name));
}

/** A learned track model's corners in lap order (any model: the live one, or a stored session's). */
export function cornersOf(
  model: Pick<TrackModelNext, "corners" | "corner_text">,
  focus: (name: string) => boolean = () => false,
  workOn: (name: string) => boolean = () => false,
): SheetCorner[] {
  const m = model as TrackModelNext;
  return [...model.corners]
    .sort((a, b) => a.apex_m - b.apex_m)
    .map((c) => {
      // The sheet's short text names the part ("T1-4 (1)", "T1-4 (2)"): two learned corners can share a label.
      const label = m.corner_text?.[c.name]?.short || cornerLabelOf(m, c.name);
      // Without an official name, the long form says it in words ("Turns 6-9, part 2"): "T6-9 (2)" alone is a code.
      const long = m.corner_text?.[c.name]?.long ?? null;
      return {
        name: c.name,
        label,
        officialName: officialNameOf(m, c.name) ?? (long && long !== label ? long : null),
        focus: focus(c.name),
        workOn: workOn(c.name),
      };
    });
}

/** Where the drill sheet finds the corners when the live snapshot has no track model yet (a session's first lap):
 * the newest stored session at this game and track. */
export function drillTrack(s: SnapshotNext | null | undefined): { game: string; trackId: string } | null {
  const game = s?.session?.game;
  const trackId = s?.session?.track_id;
  return game && trackId ? { game, trackId } : null;
}

export interface KindChoice {
  kind: DrillKind;
  label: string;
  disabled: boolean;
  /** Why it cannot be drilled here, verbatim. */
  reason: string | null;
  targetText: string | null;
  note: string | null;
  suggested: boolean;
  unit: DrillUnit;
  tolerance: number;
  toleranceChoices: number[];
}

export function kindChoices(o: DrillOptionsResponse): KindChoice[] {
  return o.kinds.map((k) => ({
    kind: k.kind,
    label: k.skill_label || DRILL_SKILL_LABEL[k.kind],
    disabled: !o.available || !k.available,
    reason: k.available ? null : (k.reason ?? "Not available at this corner"),
    targetText: k.target_text,
    note: k.note,
    suggested: k.suggested,
    unit: k.unit,
    tolerance: k.tolerance,
    toleranceChoices: k.tolerance_choices.length ? k.tolerance_choices : [k.tolerance],
  }));
}

/** The kind the sheet starts on: the suggested one when it can run, else the first that can. */
export function defaultKind(choices: readonly KindChoice[]): DrillKind | null {
  return (choices.find((c) => c.suggested && !c.disabled) ?? choices.find((c) => !c.disabled))?.kind ?? null;
}

/** "5 m" (brake point: a window before the point; past it counts only when the corner was faster), "±5 km/h" (entry
 * speed: around the target) or "+3 km/h" (speed drills: the step up). */
export function toleranceText(kind: DrillKind, value: number, unit: DrillUnit): string {
  const v = Number.isInteger(value) ? String(value) : value.toFixed(1);
  if (kind === "brake_point") return `${v} ${unit}`;
  return kind === "entry_speed" ? `±${v} ${unit}` : `+${v} ${unit}`;
}

/** What the tolerance Segment is called for this kind. */
export function toleranceTitle(kind: DrillKind): string {
  if (kind === "brake_point") return "Window before the point";
  return isBrakeLike(kind) ? "Window" : "Step up";
}

export function lapsChoices(o: Pick<DrillOptionsResponse, "laps_choices"> | null | undefined): readonly number[] {
  return o?.laps_choices?.length ? o.laps_choices : DRILL_LAPS_CHOICES;
}

/** A race's laps a drill can still use: the total less the lap being driven (or about to start: the grid start is no
 * attempt). Null outside a race or while the total is unknown. */
export function raceLapsLeft(s: SnapshotNext | null | undefined): number | null {
  const se = s?.session;
  const total = se?.total_laps;
  if (!se || !finite(total) || total <= 0 || !/race/i.test(se.session_type ?? "")) return null;
  const lap = s?.frame?.lap_number;
  return Math.max(0, total - (finite(lap) && lap > 0 ? lap : 1));
}

/** The laps the drill sheet starts on: the server's default when it fits the race's laps left, else the largest
 * choice that fits, never below the smallest choice (a 3-lap race: 3). */
export function defaultLaps(choices: readonly number[], fallback: number, lapsLeft: number | null | undefined): number {
  if (lapsLeft == null || fallback <= lapsLeft || !choices.length) return fallback;
  const fit = choices.filter((n) => n <= lapsLeft);
  return fit.length ? Math.max(...fit) : Math.min(...choices);
}
