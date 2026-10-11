// The lap ribbon's view model (design spec 4.3 #8): the lap as a straight strip, every position a fraction 0..1
// of the lap. Pure; LapRibbon (lane V) draws it as static SVG and moves only the car.
//
// Sector bands, DRS zones, marshal zones and cue targets are in game metres; corners are in model metres. Both
// map to fractions of their own lap length (the same mapping as the corner rule).
// Focus labels are the driver's own focus corners only, and the brake notches the driver's own plan only: the AI
// field's heads-ups (plan.ts) are an AI reference, not the driver's braking points, so they draw neither.

import { carFraction, gameLength } from "./geometry";
import { driverFocus, isFieldPlan } from "./plan";
import type { DriveState } from "./state";
import type { SnapshotNext } from "./types";
import { finite } from "./text";

export interface RibbonCorner {
  at: number;
  label: string;
  /** Learned name (key). */
  name: string;
  next: boolean;
  focus: boolean;
  /** Draw the label: the next corner and focus corners only. */
  showLabel: boolean;
}

export interface RibbonView {
  lengthM: number | null;
  /** Sector bands; empty = no skeleton (draw one neutral band). */
  sectors: { a: number; b: number; label: string }[];
  corners: RibbonCorner[];
  /** The driver's own plan's braking points (none for an AI field plan). */
  cueNotches: number[];
  drs: [number, number][];
  /** Live yellow marshal zones (hatched). */
  yellow: [number, number][];
  /** The car, or null (unknown position, or a state that hides it). */
  car: number | null;
  /** Nothing to draw yet but one neutral band (no telemetry). */
  empty: boolean;
}

function pieces(z: { start_m: number; end_m: number; segments_m?: [number, number][] }, L: number): [number, number][] {
  const segs = z.segments_m?.length ? z.segments_m : [[z.start_m, z.end_m] as [number, number]];
  return segs.filter(([a, b]) => finite(a) && finite(b) && b > a).map(([a, b]) => [a / L, Math.min(1, b / L)]);
}

/** States in which the ribbon shows the car (4.7): not stale, offline, ended, garage or without telemetry. */
const CAR_STATES: ReadonlySet<DriveState> = new Set(["on_track", "pit_lane", "red_flag"]);

export function ribbon(s: SnapshotNext | null, state: DriveState = "on_track", nextCorner: string | null = null): RibbonView {
  const L = gameLength(s);
  const empty: RibbonView = { lengthM: L, sectors: [], corners: [], cueNotches: [], drs: [], yellow: [], car: null, empty: true };
  if (!s || state === "no_data" || L == null) return empty;
  const sk = s.skeleton;
  const sectors = (sk?.sectors ?? [])
    .filter((x) => finite(x.start_m) && finite(x.end_m))
    .map((x) => ({ a: x.start_m / L, b: Math.min(1, x.end_m / L), label: x.name }));
  const tm = s.track_model;
  const focus = new Set(driverFocus(s.cues));
  const corners: RibbonCorner[] =
    tm && finite(tm.length_m) && tm.length_m > 0
      ? tm.corners
          .filter((c) => finite(c.apex_m))
          .map((c) => {
            const isNext = c.name === nextCorner;
            const isFocus = focus.has(c.name);
            return {
              at: Math.min(1, Math.max(0, c.apex_m / tm.length_m)),
              label: c.label || tm.corner_text?.[c.name]?.short || c.name,
              name: c.name,
              next: isNext,
              focus: isFocus,
              showLabel: isNext || isFocus,
            };
          })
          .sort((a, b) => a.at - b.at)
      : [];
  const cueNotches = (isFieldPlan(s.cues) ? [] : (s.cues?.cues ?? []))
    .filter((c) => finite(c.target_m))
    .map((c) => ((c.target_m % L) + L) % L / L)
    .sort((a, b) => a - b);
  const drs = (sk?.drs_zones ?? []).flatMap((z) => pieces(z, L));
  const live = new Set((s.marshal_flags ?? []).filter((m) => m.flag === "yellow").map((m) => m.game_number));
  const yellow = (sk?.marshal_zones ?? []).filter((z) => live.has(z.game_number)).flatMap((z) => pieces(z, L));
  const car = CAR_STATES.has(state) ? carFraction(s) : null;
  return { lengthM: L, sectors, corners, cueNotches, drs, yellow, car, empty: false };
}
