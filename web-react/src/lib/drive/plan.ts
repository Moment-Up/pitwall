// Whose braking-call plan the snapshot carries (design spec 4.3 #2, #3, 4.9). Pure.
//
// While the driver has no reference lap of their own, the cue engine stands in the AI field's "heavy braking ahead"
// heads-ups (coach/cues.py CueEngine._with_fallback, core/track_knowledge.py heads_up_cue_plan): MARKER cues placed
// early before the AI cars' braking. They are an AI reference, never the driver's target. In such a plan
// `cues.focus` lists the heads-ups' keys by priority ("T3" learned, "F2" a field corner, "zone@1234"), not the
// driver's focus corners, and those keys are never printed.

import type { CueSnapshot } from "./types";

/** The words the band and the Ready card use for the AI field's heads-ups. */
export const AI_REFERENCE = "AI reference";

/** coach/cues.py CueEngine._with_fallback: reason = f"AI field heads-ups ({plan.reason})". */
export const FIELD_REASON_PREFIX = "AI field heads-ups";

/** The plan is the AI field's heads-ups: the server's explicit `source` when sent (proposed, lane B), else the
 * engine's reason prefix. */
export function isFieldPlan(c: CueSnapshot | null | undefined): boolean {
  if (!c) return false;
  if (c.source != null) return c.source === "field";
  return typeof c.reason === "string" && c.reason.startsWith(FIELD_REASON_PREFIX);
}

const NO_FOCUS: readonly string[] = Object.freeze([]);

/** The driver's own focus corners (learned names): none while the plan is the AI field's. Use this, never
 * cues.focus directly. */
export function driverFocus(c: CueSnapshot | null | undefined): readonly string[] {
  return !c || isFieldPlan(c) ? NO_FOCUS : c.focus;
}

/** Why the AI field stands in, from its reason: "AI field heads-ups (no reference lap yet)" -> "no reference lap
 * yet"; null when it does not say. */
export function fieldPlanWhy(reason: string | null | undefined): string | null {
  const m = /^AI field heads-ups \((.+)\)$/.exec(reason ?? "");
  return m ? m[1]! : null;
}
