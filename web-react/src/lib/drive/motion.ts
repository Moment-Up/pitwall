// Moving or stationary (integration plan 2.1): the one rule every "only while stopped" thing on Drive follows. Pure.
//
//   stationary  no car frame, no live data (stale, offline: the frame on screen is not current), or a known speed
//               under 3 km/h for at least 1.5 s (in the pit lane and the garage as soon as it is under 3 km/h)
//   moving      a known speed over 8 km/h
//
// Between the two thresholds the previous answer stands, so a car crawling at 4-6 km/h never flickers between the
// two. An unknown speed (a frame without one) keeps the previous answer too; with nothing before it the car is not
// known to be stationary (the safe side: nothing that is "stationary only" appears).
//
// Stationary only (useDriveModel / model.ts): the Ready card, the Session complete card, the game mismatch band and
// the full coaching text (22 px). While moving Drive shows the status band or line, at most the chips, the hero, the
// delta, the short coaching text and the radio strip. It replaces game.ts's DRIVE_MISMATCH_MAX_KPH (a single 5 km/h
// threshold, which flickered at walking pace in the pit lane) and the coach card's fixed "on track = moving".

import { finite } from "./text";
import type { SnapshotNext } from "./types";

/** Under this speed the car is stopping. */
export const STOP_BELOW_KPH = 3;
/** ... and must stay under it this long to count as stationary (away from the pit lane and the garage). */
export const STOP_AFTER_S = 1.5;
/** Over this speed the car is moving again. */
export const MOVE_ABOVE_KPH = 8;

export interface Motion {
  stationary: boolean;
  /** Device clock (s) when the speed first went under STOP_BELOW_KPH while moving; null otherwise. */
  slowSince: number | null;
}

/** Where the car is, for the quick rule: in the pit lane or the garage, under 3 km/h is stationary at once. */
export type MotionPlace = "pits" | "track";

const STILL: Motion = Object.freeze({ stationary: true, slowSince: null }) as Motion;
const MOVING: Motion = Object.freeze({ stationary: false, slowSince: null }) as Motion;

/**
 * The next motion state from one frame. `frame`: the live frame (null / undefined = none: stationary). `live`: the
 * frame is current (the connection is live); a stale or offline frame is not a moving car. `nowS`: a device clock in
 * seconds (fractions count). Returns `prev` itself when nothing changed, so callers can compare by identity.
 */
export function nextMotion(
  frame: { speed_kph?: number | null } | null | undefined,
  prev: Motion | null | undefined,
  nowS: number,
  opts: { live?: boolean; place?: MotionPlace } = {},
): Motion {
  const keep = (m: Motion): Motion =>
    prev && prev.stationary === m.stationary && prev.slowSince === m.slowSince ? prev : m;
  if (!frame || opts.live === false) return keep(STILL);
  const v = frame.speed_kph;
  if (!finite(v)) return prev ?? MOVING; // unknown speed: nothing new is known
  if (v > MOVE_ABOVE_KPH) return keep(MOVING);
  if (v >= STOP_BELOW_KPH) {
    // between the thresholds: the previous answer stands (a stop in progress starts over)
    if (!prev) return MOVING;
    return prev.stationary ? prev : keep(MOVING);
  }
  // under STOP_BELOW_KPH
  if (!prev || prev.stationary || opts.place === "pits") return keep(STILL);
  const since = prev.slowSince ?? nowS;
  return nowS - since >= STOP_AFTER_S ? keep(STILL) : keep({ stationary: false, slowSince: since });
}

/** Stationary now, from the snapshot (plan 2.1 `stationary(frame, prev)`): see nextMotion. */
export function motionOf(s: SnapshotNext | null, prev: Motion | null | undefined, nowS: number, place: MotionPlace): Motion {
  return nextMotion(s?.frame, prev, nowS, { live: s?.connection.status === "live", place });
}
