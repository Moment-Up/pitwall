// Lap-distance geometry shared by the corner, ribbon and flag rules. Pure.
//
// Two metre scales exist: the game's lap metres (frame.lap_distance_m, skeleton, cue targets) and the learned
// track model's metres (corners, model.length_m), which can differ by a few metres. They are mapped by lap
// fraction, as the Svelte TrackMap.toModel does.

import type { SnapshotNext } from "./types";
import { finite } from "./text";

/** Distances a little past the lap length still count as "at the line" (F1 overshoots for a frame or two). */
const OVERSHOOT = 0.02;

/** The game's lap length: skeleton, else the session's, else the model's (same track, no better source). */
export function gameLength(s: SnapshotNext | null | undefined): number | null {
  const sk = s?.skeleton?.track_length_m;
  if (finite(sk) && sk > 0) return sk;
  const se = s?.session?.track_length_m;
  if (finite(se) && se > 0) return se;
  const tm = s?.track_model?.length_m;
  return finite(tm) && tm > 0 ? tm : null;
}

/**
 * Lap distance normalised into [0, L): a car before the line (F1 grid slots and out laps report negative
 * distances, down to -L) wraps to the end of the lap; a small overshoot wraps to the start. Anything else is not a
 * position on this lap (e.g. a GT7 distance that kept integrating while in a menu) and is unknown.
 */
export function onLap(d: number | null | undefined, length: number | null | undefined): number | null {
  if (!finite(d) || !finite(length) || length <= 0) return null;
  if (d < -length || d >= length * (1 + OVERSHOOT)) return null;
  if (d < 0) return d + length;
  if (d >= length) return d - length;
  return d;
}

/** Lap fraction 0..1 of the car, or null when its position on the lap is unknown. */
export function carFraction(s: SnapshotNext | null | undefined): number | null {
  const L = gameLength(s);
  const d = onLap(s?.frame?.lap_distance_m, L);
  return d == null || L == null ? null : d / L;
}

/** Forward distance from `from` to `to` around a lap of `length` (0 <= result < length). */
export function forward(from: number, to: number, length: number): number {
  const x = (to - from) % length;
  return x < 0 ? x + length : x;
}

/** Clamp to [0, 1]. */
export function unit(v: number): number {
  return v < 0 ? 0 : v > 1 ? 1 : v;
}
