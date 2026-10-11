// Corner ahead (design spec 4.5, v1 rule). Pure.
//
// Game metres map to model metres by lap fraction. The shown corner is the first corner whose apex lies ahead of
// the car, wrapping at the line; it stays until the car passes its apex. Before its entry the head reads
// "Next corner" with the distance to the entry; after it, "In corner" and no distance.
// Corner text: label = corners[].label (official) -> corner_text[name].short -> the learned name. The official
// name is corners[].display_name, shown only when set (the server sets it only from a verified or seeded sheet).
// Long corner rule: a label over 4 characters ("T10-13") or a name over 14 ("Maggotts and Becketts") puts the
// corner on two lines (label 88 px with the distance, then the name at 32 px); labels never wrap.
// FOCUS: only the driver's own focus corners (plan.ts driverFocus), never the AI field's heads-up keys.

import { driverFocus } from "./plan";
import { forward, onLap, unit } from "./geometry";
import type { CornerNext, CueSnapshot, TrackModelNext } from "./types";
import { finite } from "./text";

export const APPROACH_M = 400;
/** Long corner rule (4.5) thresholds. */
export const LONG_LABEL_CHARS = 4;
export const LONG_NAME_CHARS = 14;

export interface CornerView {
  /** Learned name: the key of cues and observations. */
  name: string;
  /** Official short label ("T15", "T10-13"), else the learned name. */
  label: string;
  /** Official name ("Stowe") when the track sheet gives one. */
  officialName: string | null;
  direction: "left" | "right" | null;
  phase: "next" | "in";
  /** Game metres to the corner's entry ("next" only). */
  toEntryM: number | null;
  /** Game metres to the corner's apex (its call can only lie before it: cues.ts `wrappedCall`); null when unknown. */
  toApexM: number | null;
  /** Approach bar fill 0..1 over the last 400 m before the entry; null in the corner or when unknown. */
  approach: number | null;
  focus: boolean;
  /** Why the corner is a focus corner, in words ("braking early · 3 of the last 5 laps"). */
  focusReason: string | null;
  /** Long corner rule: "two" when the label is over 4 characters or the name over 14. */
  layout: "one" | "two";
}

/** The hero's corner layout for a label and official name (long corner rule, 4.5). */
export function cornerLayout(label: string, officialName: string | null): "one" | "two" {
  return label.length > LONG_LABEL_CHARS || (officialName?.length ?? 0) > LONG_NAME_CHARS ? "two" : "one";
}

/** A learned corner's label: official label, else the sheet's short text, else the learned name. */
export function cornerLabelOf(model: TrackModelNext | null | undefined, name: string): string {
  const c = model?.corners.find((x) => x.name === name);
  return c?.label || model?.corner_text?.[name]?.short || name;
}

/** Official name of a learned corner, or null. */
export function officialNameOf(model: TrackModelNext | null | undefined, name: string): string | null {
  return model?.corners.find((x) => x.name === name)?.display_name || null;
}

const KIND_WORDS: Record<string, string> = {
  brake_early: "braking early",
  brake_late_overdrive: "braking late, overdriving the entry",
  low_min_speed: "slow minimum speed",
  overspeed_apex: "over speed at the apex",
  late_throttle: "late to full throttle",
  coasting: "coasting",
  exit_gain: "better exit",
  incident: "incident",
};

/** A cue plan reason in words: "brake_early on 3 of the last 5 lap(s)" -> "braking early · 3 of the last 5 laps".
 * Unknown shapes are returned verbatim. */
export function reasonWords(reason: string | null | undefined): string | null {
  if (!reason) return null;
  const m = /^([a-z_]+) on (\d+) of the last (\d+) lap\(s\)$/.exec(reason.trim());
  if (!m) return reason;
  const words = KIND_WORDS[m[1]!] ?? m[1]!.replace(/_/g, " ");
  const total = Number(m[3]);
  return `${words} · ${m[2]} of the last ${total} ${total === 1 ? "lap" : "laps"}`;
}

/** One of the driver's own focus corners (learned name); never while the plan is the AI field's heads-ups
 * (plan.ts: their `focus` lists heads-up keys). */
export function isFocus(cues: CueSnapshot | null | undefined, name: string): boolean {
  return driverFocus(cues).includes(name);
}

/** Focus reason for one of the driver's focus corners from the cue plan; null for an AI field plan. */
export function focusReasonOf(cues: CueSnapshot | undefined, name: string): string | null {
  if (!isFocus(cues, name)) return null;
  const c = cues?.cues.find((x) => x.corner === name && x.focus) ?? null;
  return c ? reasonWords(c.reason) : null;
}

/** Corners in lap order of their apex. */
function byApex(model: TrackModelNext): CornerNext[] {
  return [...model.corners].filter((c) => finite(c.apex_m)).sort((a, b) => a.apex_m - b.apex_m);
}

export function cornerAhead(
  model: TrackModelNext | null | undefined,
  lapDistanceM: number | null | undefined,
  gameLengthM: number | null | undefined,
  cues: CueSnapshot | undefined,
): CornerView | null {
  if (!model || !model.corners.length || !finite(model.length_m) || model.length_m <= 0) return null;
  const Lm = model.length_m;
  const Lg = finite(gameLengthM) && gameLengthM > 0 ? gameLengthM : Lm;
  const dg = onLap(lapDistanceM, Lg);
  if (dg == null) return null;
  const d = (dg / Lg) * Lm; // model metres
  let shown: CornerNext | null = null;
  let toApex = Infinity;
  for (const c of byApex(model)) {
    const a = forward(d, c.apex_m, Lm);
    if (a > 0 && a < toApex) {
      toApex = a;
      shown = c;
    }
  }
  if (!shown) return null;
  const toEntry = finite(shown.entry_m) ? forward(d, shown.entry_m, Lm) : null;
  const next = toEntry != null && toEntry > 0 && toEntry < toApex;
  const toEntryM = next && toEntry != null ? (toEntry / Lm) * Lg : null;
  const focus = isFocus(cues, shown.name);
  const dir = shown.direction === "left" || shown.direction === "right" ? shown.direction : null;
  const label = shown.label || model.corner_text?.[shown.name]?.short || shown.name;
  const officialName = shown.display_name || null;
  return {
    name: shown.name,
    label,
    officialName,
    direction: dir,
    phase: next ? "next" : "in",
    toEntryM,
    toApexM: (toApex / Lm) * Lg,
    approach: toEntryM != null ? unit(1 - toEntryM / APPROACH_M) : null,
    focus,
    focusReason: focus ? focusReasonOf(cues, shown.name) : null,
    layout: cornerLayout(label, officialName),
  };
}
