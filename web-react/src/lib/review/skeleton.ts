// A stored session's game-native skeleton (sectors, zones) for Review charts and maps: the API's `skeleton` when it
// sends one, else the sector starts every stored F1 session keeps in `info` (legacy keys), as the Svelte session page
// does. Geometry only: marshal flags are live state, never a fact about a stored session. Pure.

import { finite } from "./words";
import { legacySkeleton, type TrackSkeleton } from "../skeleton";

export function sessionSkeleton(s: {
  skeleton?: unknown;
  track_length_m?: number | null;
  info?: Record<string, unknown> | null;
  synthetic?: boolean | null;
}): TrackSkeleton | null {
  const sk = s.skeleton as TrackSkeleton | null | undefined;
  if (sk && typeof sk === "object" && Array.isArray(sk.sectors)) return sk;
  return legacySkeleton(s.track_length_m, s.info?.sector2_start_m, s.info?.sector3_start_m, s.synthetic === true);
}

/** Neutral sector bands for the distance charts, game metres. */
export function sectorBands(sk: TrackSkeleton | null | undefined): { a: number; b: number }[] {
  return (sk?.sectors ?? [])
    .filter((x) => finite(x.start_m) && finite(x.end_m) && x.end_m > x.start_m)
    .map((x) => ({ a: x.start_m, b: x.end_m }));
}
