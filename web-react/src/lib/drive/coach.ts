// The coach card (design spec 4.3 #4, 4.5) and the coaching picks of the state cards (4.9). Pure.
//
// One message, two channels (P7): with D6 the card shows coach.by_corner[shown corner], the point the radio
// picked. Before D6 it falls back to the top observation for that corner by priority, which may differ from what
// the radio said. The UI never filters by its own thresholds and never composes advice (P9): texts are the
// backend's, verbatim. The rules mirrored from the radio: incident observations are never coaching
// (voice/proactive.py skips them: "the driver knows they spun"), nor is a point the technique graph says does not fit
// the driver (analysis/coaching.py `applies`; D6's blocks already leave those out).
//
// Technique knowledge (lib/knowledge/annotation.ts): when the point's measured signals named a cause shown to tell its
// fault apart (its base-rate check, `discriminates`), its screen line leads the evidence line ("Braking ended sooner,
// longer roll after · Seen on 3 of the last 5 laps · ..."), which shows only when the car is stationary (pit lane,
// Ready, Session complete): at speed the card stays one line. A cause that was only also measured is never the card's
// reason (Review shows it as also measured).
//
// Length rule (4.5): while moving, up to 60 characters at 30 px, longer at 26 px (never smaller: 22 px is under
// ISO 15008's 16' at 70 cm), clamped to 3 lines past 130 characters (the verbatim prefix and an ellipsis; D6's
// `short` makes that rare). Stationary (pit, garage, after the session) the card shows the full text at 22 px.
//
// Habits (habits spec 7; coach/habits.py): the note's one chip says what kind of note it is - "Habit · 3 of 4 laps" (a
// habit the radio is not working on), "Focus" (the habit the radio announced and is working on), "Once" (a one-off),
// "Sorted" (a habit that stopped) - with the lap it is from, as before ("Once · last lap"). One chip, not two: the
// card is a glance at speed. A focus corner whose last lap had no note shows the habit's reminder (the words the radio
// says before the corner, verbatim). Between runs the Ready card says what the radio is working on (`workingOn`).

import { cardCause, fitsDriver, joinLine } from "../knowledge/annotation";
import { cornerLabelOf } from "./corner";
import { hasCleanLap } from "./delta";
import type { FocusEntry, ObservationNext, SnapshotNext } from "./types";
import { confidenceWord, finite } from "./text";

export type CoachTextSize = 30 | 26 | 22;

/** What kind of note it is (habits): its chip's words without the lap ("Habit · 3 of 4 laps", "Focus", "Once",
 * "Sorted"). */
export interface HabitChip {
  kind: "habit" | "focus" | "once" | "sorted";
  text: string;
}

export interface CoachPoint {
  /** "drill": a practice drill's attempt (coachref, lib/drive/drill.ts). */
  tag: "work_on" | "good" | "drill" | null;
  /** Habits: what kind of note it is (null: unknown, an older server, praise or a drill). */
  habit?: HabitChip | null;
  /** The game's number of the lap the point is from. */
  lap: number | null;
  /** "Work on · last lap" / "Good · last lap" for a point from the lap just finished; "Work on · L6" for older laps. */
  tagText: string | null;
  text: string | null;
  size: CoachTextSize;
  /** Clamp to 3 lines with an ellipsis (moving, over 130 characters). */
  clamp: boolean;
  /** Muted line when there is no point to show. */
  empty: string | null;
  /** "Seen on 3 of the last 5 laps · about 0.12 s · confidence high", led by the measured cause's screen line when the
   * technique graph named one that tells its fault apart ("Braking ended sooner, longer roll after · Seen on ..."), or
   * null. */
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

/** Coaching observations (not incidents, not points the technique graph says do not fit the driver), highest
 * priority first. */
export function rankedObservations(s: SnapshotNext): ObservationNext[] {
  return s.observations
    .filter((o) => o.kind !== "incident" && fitsDriver(o))
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

/**
 * The game's number of the lap the driver just finished: the latest completed lap, unless the car is already past
 * the lap after it (that lap's analysis still on its way), else null. A point from it is tagged "last lap", not
 * "L66": the header shows the lap in progress ("Lap 67"), so a bare "L66" next to it reads as one lap out. At the
 * chequered flag the game keeps the final lap's number, so the final lap is still the last lap.
 */
export function lastLapNumber(s: SnapshotNext): number | null {
  const l = s.laps[0]?.lap_number;
  if (!finite(l)) return null;
  const now = s.frame?.lap_number;
  return finite(now) && now > l + 1 ? null : l;
}

/** " · last lap" for the lap just finished, " · L6" for an older lap, "" when unknown. */
export function lapSuffix(lap: number | null, last: number | null): string {
  if (lap == null) return "";
  return lap === last ? " · last lap" : ` · L${lap}`;
}

/** "3 of 4 laps" ("1 of 1 lap"). */
export function lapCount(seen: number, laps: number): string {
  return `${seen} of ${laps} ${laps === 1 ? "lap" : "laps"}`;
}

/** A "sorted" line: the habit tracker's fixed event (its point keeps habit status "fixed"). Progress, not a fault. */
export function isSorted(o: Pick<ObservationNext, "habit_event" | "habit">): boolean {
  return o.habit_event === "fixed" || o.habit?.status === "fixed";
}

/**
 * The note's kind (coach block `habit` / `one_off`): "Sorted" for a habit that stopped, "Focus" for the habit being
 * worked on, "Habit · 3 of 4 laps" for a habit not on the radio, "Once" for a one-off; null for praise, a drill and
 * points without the fields (older servers, observations before D6): unknown, never guessed.
 */
export function habitChip(o: ObservationNext): HabitChip | null {
  if (o.kind === "drill") return null;
  if (isSorted(o)) return { kind: "sorted", text: "Sorted" };
  if (o.positive) return null;
  const h = o.habit;
  if (h?.status === "focus") return { kind: "focus", text: "Focus" };
  if (h?.status === "seen" && finite(h.laps_seen) && finite(h.laps) && h.laps > 0) {
    return { kind: "habit", text: `Habit · ${lapCount(h.laps_seen, h.laps)}` };
  }
  return o.one_off === true ? { kind: "once", text: "Once" } : null;
}

export type ChipTone = "warning" | "success" | "accent";

/** The coach card chip's colour: praise and "Sorted" green, a focus habit and a drill accent (as the FOCUS and DRILL
 * chips), every other note to work on amber; the pit lane's "Next run" heading amber. */
export function chipTone(p: Pick<CoachPoint, "tag" | "habit">, heading: string | null = null): ChipTone {
  if (heading) return "warning";
  if (p.tag === "good") return "success";
  return p.tag === "drill" || p.habit?.kind === "focus" ? "accent" : "warning";
}

/** The Ready card's "Last lap:" chip (its label already says the lap): the note's kind, else Good / Work on. */
export function pointChip(p: Pick<CoachPoint, "tag" | "habit">): { text: string; tone: ChipTone } | null {
  if (p.tag !== "good" && p.tag !== "work_on") return null;
  return { text: p.habit?.text ?? (p.tag === "good" ? "Good" : "Work on"), tone: chipTone(p) };
}

/** The chip's words: a habit says its counts; every other note says its kind and the lap it is from. */
function chipWords(tag: "good" | "work_on", habit: HabitChip | null, lap: number | null, last: number | null): string {
  if (habit?.kind === "habit") return habit.text;
  return `${habit?.text ?? (tag === "good" ? "Good" : "Work on")}${lapSuffix(lap, last)}`;
}

function view(
  o: ObservationNext,
  source: "d6" | "observation",
  simple: boolean,
  moving: boolean,
  last: number | null,
): CoachPoint {
  const text = pointText(o, simple, moving);
  const tag = o.positive || isSorted(o) ? "good" : "work_on";
  const lap = finite(o.lap_number) ? o.lap_number : null;
  const habit = habitChip(o);
  return {
    tag,
    habit,
    lap,
    tagText: chipWords(tag, habit, lap, last),
    text,
    size: textSize(text, moving),
    clamp: needsClamp(text, moving),
    empty: null,
    evidence: joinLine(cardCause(o), evidenceLine(o)),
    source,
    corner: o.corner,
  };
}

function emptyPoint(empty: string): CoachPoint {
  return {
    tag: null,
    habit: null,
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
/** A clean lap is in, its comparison not yet: coaching follows from the next lap. */
export const COACHING_NEXT_LAP = "Coaching from your next lap";

/** Simple wording: D6's block says what the seated driver's profile wants; else the caller's profile flag. */
export function simpleWording(s: SnapshotNext, profileSimple: boolean): boolean {
  return typeof s.coach?.simple_wording === "boolean" ? s.coach.simple_wording : profileSimple;
}

/** The coaching point for the shown corner (spec signature). `moving` = on track (glance texts allowed). */
export function coachPoint(s: SnapshotNext, corner: string | null, simple: boolean, moving: boolean): CoachPoint {
  if (!s.reference && !s.coach) return emptyPoint(hasCleanLap(s) ? COACHING_NEXT_LAP : NO_REFERENCE_COACHING);
  if (corner == null) return emptyPoint("No corner ahead yet");
  const last = lastLapNumber(s);
  if (s.coach) {
    const o = s.coach.by_corner[corner];
    if (o) return view(o, "d6", simpleWording(s, simple), moving, last);
    const f = focusAt(s, corner);
    const fp = f ? focusPoint(f, moving) : null;
    if (fp) return fp;
  } else {
    const o = rankedObservations(s).find((x) => x.corner === corner);
    if (o) return view(o, "observation", simple, moving, last);
  }
  const lap = latestLap(s);
  const label = cornerLabelOf(s.track_model, corner);
  const on = lap == null ? "" : lap === last ? " on the last lap" : ` on lap ${lap}`;
  return emptyPoint(`No note for ${label}${on}`);
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

/** The last lap's top point, full text (the pit lane's "Next run", the Ready card's "Last lap: …" between runs). A
 * "sorted" line is progress, not something to work on: a fault comes first. */
export function topPoint(s: SnapshotNext, simple: boolean): CoachPoint | null {
  const { picks, source } = lapPicks(s);
  const o = picks.find((x) => !x.positive && !isSorted(x)) ?? picks[0];
  return o ? view(o, source, simpleWording(s, simple), false, lastLapNumber(s)) : null;
}

/** One Work on and one Went well (Session complete card). A "sorted" line went well. */
export function workOnWentWell(s: SnapshotNext, simple: boolean): { workOn: CoachPoint | null; wentWell: CoachPoint | null } {
  const { picks: all, source } = lapPicks(s);
  // coachref: a drill attempt's point is a drill result, not a Work on (the drill's own card and Review › Coaching
  // show it).
  const picks = all.filter((o) => o.kind !== "drill");
  const sw = simpleWording(s, simple);
  const w = picks.find((x) => !x.positive && !isSorted(x));
  const g = picks.find((x) => x.positive || isSorted(x));
  const last = lastLapNumber(s);
  return {
    workOn: w ? view(w, source, sw, false, last) : null,
    wentWell: g ? view(g, source, sw, false, last) : null,
  };
}

// ------------------------------------------------------------------------------------------------- habits (spec 7)

/** coach/habits.py focus_slots at its largest (detailed intensity): the Ready card shows at most this many. */
export const FOCUS_SLOTS_MAX = 2;

/** The habits being worked on (coach block `focus`, status "focus"), at most FOCUS_SLOTS_MAX; [] without them. A habit
 * the latest lap could not show (`blind`: compared with a lap that had it) is left out until it is measured again, as
 * the radio leaves out its reminder. */
export function focusHabits(s: SnapshotNext | null | undefined): FocusEntry[] {
  return (s?.coach?.focus ?? [])
    .filter((f) => f?.status === "focus" && !!f.corner && f.blind !== true)
    .slice(0, FOCUS_SLOTS_MAX);
}

function focusAt(s: SnapshotNext, corner: string): FocusEntry | null {
  return focusHabits(s).find((f) => f.corner === corner) ?? null;
}

/** "Seen on 3 of the last 4 laps" for a habit's counts; null when unknown. */
function habitEvidence(f: Pick<FocusEntry, "laps_seen" | "laps">): string | null {
  if (!finite(f.laps_seen) || !finite(f.laps) || f.laps <= 0) return null;
  return `Seen on ${f.laps_seen} of the last ${f.laps} ${f.laps === 1 ? "lap" : "laps"}`;
}

/** A focus corner whose last lap had no note of its own: the habit's reminder, verbatim (the words the radio says
 * before the corner: "T6: apex speed, 12 down"), else its last glance text; not a lap's note, so no lap. */
function focusPoint(f: FocusEntry, moving: boolean): CoachPoint | null {
  const text = f.reminder?.text || f.short || null;
  if (!text) return null;
  return {
    tag: "work_on",
    habit: { kind: "focus", text: "Focus" },
    lap: null,
    tagText: "Focus",
    text,
    size: textSize(text, moving),
    clamp: needsClamp(text, moving),
    empty: null,
    evidence: habitEvidence(f),
    source: "d6",
    corner: f.corner,
  };
}

/** A habit's topic in plain words for the Ready card ("apex speed"): what the habit is about, never advice. */
const HABIT_TOPIC: Readonly<Record<string, string>> = {
  brake_early: "braking point",
  brake_late_overdrive: "corner entry",
  low_min_speed: "apex speed",
  overspeed_apex: "entry speed",
  late_throttle: "throttle on exit",
  coasting: "coasting",
};

export interface WorkingOnRow {
  /** Learned corner name. */
  corner: string;
  /** "T6". */
  label: string;
  /** The reminder's phrase ("apex speed, 12 down", verbatim from the backend), else the topic ("braking point"). */
  what: string;
  /** "3 of 4 laps"; null when unknown. */
  counts: string | null;
  /** "T6 apex speed, 12 down · 3 of 4 laps". */
  text: string;
}

/** The Ready card's "Working on" rows between runs: the habits the radio is working on, at most FOCUS_SLOTS_MAX. */
export function workingOn(s: SnapshotNext | null | undefined): WorkingOnRow[] {
  if (!s) return [];
  return focusHabits(s).map((f) => {
    const label = f.corner_label || cornerLabelOf(s.track_model, f.corner);
    const phrase = f.reminder?.parts?.[1];
    const what = phrase || HABIT_TOPIC[f.kind] || f.kind.replace(/_/g, " ");
    const counts = finite(f.laps_seen) && finite(f.laps) && f.laps > 0 ? lapCount(f.laps_seen, f.laps) : null;
    return { corner: f.corner, label, what, counts, text: [`${label} ${what}`, counts].filter(Boolean).join(" · ") };
  });
}
