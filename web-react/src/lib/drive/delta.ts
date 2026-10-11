// Delta to the reference lap (design spec 4.3 #5 and 4.5). Pure.
//
// Tone ahead below -0.02 s, behind above +0.02 s, level in between (word LEVEL). Two decimals; one at 10 s or more.
// Invalid lap or safety car: muted (real, but not meaningful) with an INV / SC chip. Stale, offline and every
// state without a live delta: "-" with one reason line. A frozen delta must never look current.

import type { DriveOverlays, DriveState } from "./state";
import { waitingText } from "./reference";
import type { SnapshotNext } from "./types";
import { MINUS, UNKNOWN, ageText, dayText, finite, lapTime, lapTimeHundredths } from "./text";

export const DELTA_NEUTRAL_S = 0.02;
export const DELTA_SCALE_S = 1.0;
/** Bar ticks (seconds) drawn on the +-1.0 s scale. */
export const DELTA_TICKS_S = [-0.5, -0.25, 0.25, 0.5] as const;

export interface DeltaView {
  text: string;
  tone: "ahead" | "behind" | "level" | "muted" | "unknown";
  word: "AHEAD" | "BEHIND" | "LEVEL" | null;
  /** -1..1 on the +-1.0 s scale (negative = ahead, drawn to the left). */
  bar: number;
  /** |delta| > 1.0 s: the bar is full and shows a chevron. */
  clamped: boolean;
  /** Chip next to the number when the delta is muted. */
  chip: "SC" | "INV" | null;
  projectedMs: number | null;
  /** "1:30.77" (hundredths, as the spec and mockup show it). */
  projectedText: string;
  /** "Delta to reference", or "vs your target lap" for beginners. */
  label: string;
  /** Reference chip: "Lap 4 · 1:30.986 · today", or null without a reference. */
  refLabel: string | null;
  /** One reason line when the number is "-". */
  reason: string | null;
  showProjected: boolean;
  aria: string;
}

/** "−0.21", "+0.53", "0.00", "+12.4": two decimals, one at 10 s or more; sign dropped at zero. */
export function deltaText(v: number): string {
  const digits = Math.abs(v) >= 10 ? 1 : 2;
  const abs = Math.abs(v).toFixed(digits);
  if (Number(abs) === 0) return abs;
  return `${v < 0 ? MINUS : "+"}${abs}`;
}

export function deltaTone(v: number): "ahead" | "behind" | "level" {
  return v < -DELTA_NEUTRAL_S ? "ahead" : v > DELTA_NEUTRAL_S ? "behind" : "level";
}

/** The reference chip text. The date of a reference from another session is the descriptor's `set_unix` (coachref),
 * else the seated driver's best laps when one of them is that lap (`refDates`: lap id -> unix time); otherwise it
 * says "another session". */
export function referenceLabel(
  s: SnapshotNext | null,
  nowS: number,
  refDates?: ReadonlyMap<number, number> | null,
): string | null {
  const r = s?.reference;
  if (!r) return null;
  const parts = [`Lap ${r.lap_number}`];
  if (finite(r.lap_time_ms)) parts.push(lapTime(r.lap_time_ms));
  if (r.session_id === s?.session_id) parts.push("today");
  else {
    const set = r.set_unix ?? refDates?.get(r.lap_id);
    parts.push(dayText(set, nowS) ?? "another session");
  }
  return parts.join(" · ");
}

const NO_REFERENCE = "No reference yet: your first clean lap becomes the reference";

function unknownReason(s: SnapshotNext | null, state: DriveState): string | null {
  switch (state) {
    case "offline":
      return "Offline";
    case "no_data":
      return "No telemetry";
    case "stale": {
      const age = s?.connection.last_packet_age_s;
      return finite(age) && age >= 1 ? `No signal · ${ageText(age)}` : "No signal";
    }
    case "pit_lane":
      return "No delta in the pit lane";
    case "red_flag":
      return "Red flag";
    case "garage":
    case "ended":
      return null;
    default: {
      if (!s?.reference) {
        // coachref: another driver's lap is chosen and not in place yet: the Ready card's words (waitingText).
        const waiting = waitingText(s?.coachref?.choice);
        return waiting ? `No reference yet: ${waiting}` : NO_REFERENCE;
      }
      const ds = s.frame?.driver_status;
      if (ds === "out_lap") return "Out lap";
      if (ds === "in_lap") return "In lap";
      return "No delta at this point of the lap";
    }
  }
}

export function deltaView(
  s: SnapshotNext | null,
  state: DriveState,
  o: DriveOverlays,
  beginner: boolean,
  opts: { nowS?: number; refDates?: ReadonlyMap<number, number> | null } = {},
): DeltaView {
  const label = beginner ? "vs your target lap" : "Delta to reference";
  const refLabel = referenceLabel(s, opts.nowS ?? Date.now() / 1000, opts.refDates);
  const showProjected = !beginner;
  const live = state === "on_track";
  const v = s?.delta_s;
  if (!live || !finite(v)) {
    const reason = unknownReason(s, state);
    return {
      text: UNKNOWN,
      tone: "unknown",
      word: null,
      bar: 0,
      clamped: false,
      chip: null,
      projectedMs: null,
      projectedText: UNKNOWN,
      label,
      refLabel,
      reason,
      showProjected,
      aria: reason ? `Delta unknown: ${reason}` : "Delta unknown",
    };
  }
  const tone0 = deltaTone(v);
  const chip = o.invalid ? "INV" : o.safetyCar ? "SC" : null;
  const tone = chip ? "muted" : tone0;
  const word = tone0 === "ahead" ? "AHEAD" : tone0 === "behind" ? "BEHIND" : "LEVEL";
  const bar = Math.max(-1, Math.min(1, v / DELTA_SCALE_S));
  const refMs = s?.reference?.lap_time_ms;
  const projectedMs = !o.invalid && finite(refMs) ? Math.round(refMs + v * 1000) : null;
  const abs = Math.abs(v).toFixed(Math.abs(v) >= 10 ? 1 : 2);
  const lap = s?.reference ? ` of reference lap ${s.reference.lap_number}` : "";
  const aria =
    tone0 === "level" ? `Level with reference${lap ? ` lap ${s?.reference?.lap_number}` : ""}` : `${abs} seconds ${tone0}${lap}`;
  return {
    text: deltaText(v),
    tone,
    word,
    bar,
    clamped: Math.abs(v) > DELTA_SCALE_S,
    chip,
    projectedMs,
    projectedText: projectedMs != null && projectedMs > 0 ? lapTimeHundredths(projectedMs) : UNKNOWN,
    label,
    refLabel,
    reason: null,
    showProjected,
    aria: chip ? `${aria} (${chip === "INV" ? "invalid lap" : "safety car"})` : aria,
  };
}
