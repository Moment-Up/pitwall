// The cue band inside the hero (design spec 4.3 #3, 4.5) and the last braking call's outcome for the radio strip
// (4.3 #9). Pure. The screen looks ahead; the radio does the timing (P6): nothing here flashes "brake now".
//
// cues.next.corner is the learned corner name, the key of track_model.corners[].name. The cue text the server
// builds starts with that learned name ("T7 brake"); where the track sheet gives the corner an official label the
// band shows the label instead ("T11 brake"), so it reads the same as the hero above it. The rest of the text is
// verbatim. (The radio speaks only "brake" for brake cues; for marker cues it speaks the learned name - see
// INTEGRATION NEEDED in the lane report.)
//
// Cue muting (4.5): cues.muted replaces the band with "Calls paused: <reason>", except when nobody is listening:
// "radio off" (the engine has no radio sink) and "no radio connected" (the hub is up, no device has joined; what the
// live service reports for a driver without an earpiece). Then the band keeps cues.next and says Radio off.
//
// AI field plan (plan.ts): the AI field's "heavy braking ahead" heads-ups stand in while the driver has no reference
// lap of their own. An AI reference, never the driver's target: the band labels them (AI REF chip, "AI reference"
// note) and never prints their raw keys ("zone@1234", "F2").

import { cornerLabelOf } from "./corner";
import { AI_REFERENCE, fieldPlanWhy, isFieldPlan } from "./plan";
import type { CueSnapshot, TrackModelNext } from "./types";
import { MINUS, UNKNOWN, distanceShort, finite, metres, sentence } from "./text";

export interface CueLine {
  kind: "brake" | "marker";
  /** Chip word: BRAKE (solid behind-red), MARKER (neutral), or AI REF (neutral) for an AI field heads-up. */
  chip: "BRAKE" | "MARKER" | "AI REF";
  /** The call is the AI field's heads-up (an AI reference), not one from the driver's reference lap. */
  ai: boolean;
  text: string;
  /** Whole metres to the call, or null when unknown or not current. */
  inM: number | null;
  /** "250 m", or "-" when unknown or not current (stale, offline). */
  inText: string;
  corner: string;
}

export interface CueBandView {
  /** The call for the shown corner, or null. */
  next: CueLine | null;
  /** Secondary line ("Next call: T3 brake · 1.4 km", "Calls off", "Calls paused: …", a reason), or null. */
  note: string | null;
  /** Calls are paused or off: the note is shown muted. */
  muted: boolean;
  /** Nobody is listening (no radio): the band keeps the call and shows a small Radio off chip. */
  radioOff: boolean;
  /** The calls are the AI field's heads-ups (AI reference): an AI REF chip / "AI reference" words, never FOCUS. */
  ai: boolean;
}

/** Mute reasons that mean "no radio is listening", not "the calls are paused". */
export const RADIO_OFF_REASONS: ReadonlySet<string> = new Set(["radio off", "no radio connected"]);

export function isRadioOff(muted: string | null | undefined): boolean {
  return !!muted && RADIO_OFF_REASONS.has(muted);
}

/** The cue text with the learned corner name replaced by the official label when they differ. A server that already
 * writes the label (coach/cues.py `cue_labels`: "T1 (2) brake" for learned "T1") is left as it is, never doubled. */
export function cueText(text: string, corner: string, model: TrackModelNext | null | undefined): string {
  const label = cornerLabelOf(model, corner);
  if (label === corner || !text.startsWith(corner) || text.startsWith(label)) return text;
  const rest = text.slice(corner.length);
  return rest === "" || /^\W/.test(rest) ? label + rest : text;
}

/** Where the car is relative to the calls (game metres): the shown corner's apex and the lap length. */
export interface CuePass {
  /** Metres to the shown corner's apex (CornerView.toApexM), or null. */
  toApexM: number | null;
  /** The game's lap length, or null. */
  lapLengthM: number | null;
}

/** A call this close to a whole lap away is one the car has just passed (or that already played on this lap); on a
 * short lap at most a quarter of it (`justPassedM`), so real calls further round a 1 km lap still show. */
export const JUST_PASSED_M = 500;
/** Share of the lap the just-passed guard may cover (the server's own wrap window is at most half a lap). */
export const JUST_PASSED_MAX_LAP_SHARE = 0.25;

/** The just-passed window for a lap of `lapLengthM` metres: 500 m, or a quarter of a short lap. */
export function justPassedM(lapLengthM: number): number {
  return Math.min(JUST_PASSED_M, JUST_PASSED_MAX_LAP_SHARE * lapLengthM);
}
/** Slack between the model's and the game's metres when a call is matched against the shown corner's apex. */
const APEX_SLACK_M = 10;

/**
 * The server's next call is that corner's call on the NEXT lap: the car has just passed its target (or it already
 * played this lap). coach/cues.py `_next_cue` wraps to the next lap with in_m = target + lap length - position, so a
 * call passed 80 m ago comes back as "brake in 5 810 m". Never shown: neither as the shown corner's call (its own call
 * can only lie before its apex) nor as "Next call · 5.8 km".
 */
export function wrappedCall(
  n: { corner: string; in_m: number } | null | undefined,
  shownCorner: string | null,
  pass: CuePass | null | undefined,
): boolean {
  if (!n || !finite(n.in_m)) return false;
  const apex = pass?.toApexM;
  if (shownCorner != null && n.corner === shownCorner && finite(apex) && n.in_m > apex + APEX_SLACK_M) return true;
  const L = pass?.lapLengthM;
  return finite(L) && L > 0 && n.in_m > L - justPassedM(L);
}

/** Track-side pauses the band states itself (the spec's red flag and pit copy). */
export type CuePause = "red_flag" | "pit_lane" | "safety_car" | null;

/** coach/cues.py NO_REFERENCE, NO_DRIVER_REFERENCE, NEW_DRIVER: the plan has no comparison for this driver yet. */
const NO_REFERENCE_REASONS: ReadonlySet<string> = new Set([
  "no reference lap yet",
  "no reference lap for this driver",
  "new driver: waiting for a lap against their reference",
]);
/** coachref: what the band says when the delta has its reference before the first lap (calls need a lap). */
export const CALLS_AFTER_FIRST_LAP = "Braking calls start after your first lap";
/** No reference of the driver's own yet (a new driver, the first laps here): plain words instead of the server's
 * reason ("new driver: waiting for a lap against their reference" ran off the band). */
export const CALLS_AFTER_FIRST_CLEAN_LAP = "Braking calls start after your first clean lap";

/**
 * The cue band. `pause` is the Drive state's own pause; `frozen` = the position is not current (stale, offline):
 * the call's distance reads "-" and the text stays (a fact). `pass` (live position) drops a call the car has just
 * passed, which the server reports a lap later (`wrappedCall`).
 */
export function cueView(
  c: CueSnapshot | undefined,
  shownCorner: string | null,
  model?: TrackModelNext | null,
  pause: CuePause = null,
  frozen = false,
  pass: CuePass | null = null,
  /** coachref: the delta already has a reference (published before the first lap): calls wait for a lap. */
  hasReference = false,
): CueBandView {
  const band = (note: string | null, muted = true): CueBandView => ({ next: null, note, muted, radioOff: false, ai: false });
  if (pause === "red_flag") return band("Calls paused");
  if (pause === "pit_lane") return band("Calls resume on your out lap");
  if (!c) return band(null);
  if (c.mode === "off") return band("Calls off");
  const radioOff = isRadioOff(c.muted);
  const ai = isFieldPlan(c);
  if (pause === "safety_car") return band(`Calls paused: ${c.muted && !radioOff ? c.muted : "safety car"}`);
  if (c.muted && !radioOff) return band(`Calls paused: ${c.muted}`);
  const n = !frozen && wrappedCall(c.next, shownCorner, pass) ? null : c.next;
  // A heads-up key is a learned name ("T3") when the model covers it; "F2" / "zone@1234" never match a corner.
  if (n && shownCorner != null && n.corner === shownCorner) {
    const inM = !frozen && finite(n.in_m) ? Math.max(0, Math.round(n.in_m)) : null;
    return {
      next: {
        kind: n.kind,
        chip: ai ? "AI REF" : n.kind === "brake" ? "BRAKE" : "MARKER",
        ai,
        text: ai ? n.text : cueText(n.text, n.corner, model),
        inM,
        inText: inM != null ? metres(inM) : UNKNOWN,
        corner: n.corner,
      },
      note: null,
      muted: false,
      radioOff,
      ai,
    };
  }
  if (n) {
    const where = frozen ? UNKNOWN : distanceShort(n.in_m);
    const note = ai ? `${AI_REFERENCE}: ${n.text} · ${where}` : `Next call: ${cueText(n.text, n.corner, model)} · ${where}`;
    return { next: null, note, muted: false, radioOff, ai };
  }
  if (ai) {
    const why = fieldPlanWhy(c.reason);
    if (why && NO_REFERENCE_REASONS.has(why)) return { ...band(`${AI_REFERENCE} until your first clean lap`), radioOff, ai };
    return { ...band(why ? `${AI_REFERENCE}: ${why}` : `${AI_REFERENCE}: no call ahead`), radioOff, ai };
  }
  if (c.reason && NO_REFERENCE_REASONS.has(c.reason)) {
    return { ...band(hasReference ? CALLS_AFTER_FIRST_LAP : CALLS_AFTER_FIRST_CLEAN_LAP), radioOff };
  }
  if (c.reason) return { ...band(sentence(c.reason)), radioOff };
  return { ...band("No call ahead"), radioOff };
}

/** A last cue is shown on the radio strip for this long (as the Svelte LiveView). */
export const CUE_LAST_SHOWN_S = 90;

export interface LastCueOutcome {
  corner: string;
  text: string;
  /** "on time −3 m", "late +6 m", "dropped (reason)", or null while the outcome is unknown. */
  words: string | null;
  tone: "ok" | "late" | "dropped" | "pending";
  ageS: number | null;
}

/** The cue that just played and how it landed: heard vs the reference braking point (+ = after it). The cue aims
 * `margin_m` before the point, so error_m (measured vs the aim) minus the margin is what the driver experienced. */
export function lastCueOutcome(c: CueSnapshot | undefined, model?: TrackModelNext | null): LastCueOutcome | null {
  const l = c?.last;
  if (!l) return null;
  const age = finite(l.age_s) ? l.age_s : null;
  if (age != null && age >= CUE_LAST_SHOWN_S) return null;
  const text = cueText(l.text, l.corner, model);
  const base = { corner: l.corner, text, ageS: age };
  if (l.status === "dropped") return { ...base, words: l.reason ? `dropped (${l.reason})` : "dropped", tone: "dropped" };
  if (finite(l.error_m)) {
    const e = Math.round(l.error_m - (c?.timing?.margin_m ?? 0));
    const metres = `${e < 0 ? MINUS : e > 0 ? "+" : ""}${Math.abs(e)} m`;
    return e > 0 ? { ...base, words: `late ${metres}`, tone: "late" } : { ...base, words: `on time ${metres}`, tone: "ok" };
  }
  return { ...base, words: null, tone: "pending" };
}

const MODE_WORDS: Record<CueSnapshot["mode"], string> = {
  off: "Off",
  focus: "Focus corners",
  markers: "Markers",
  all: "All corners",
};

/** "Braking calls: Focus corners"; while the AI field stands in, "Braking calls: AI reference (heavy braking
 * ahead)" (what the radio will say, and where it comes from). */
export function callsModeText(c: CueSnapshot | undefined): string | null {
  if (!c) return null;
  if (c.mode !== "off" && isFieldPlan(c)) {
    const phrase = c.cues.find((x) => x.text)?.text;
    return `Braking calls: ${AI_REFERENCE}${phrase ? ` (${phrase})` : ""}`;
  }
  return `Braking calls: ${MODE_WORDS[c.mode] ?? c.mode}`;
}
