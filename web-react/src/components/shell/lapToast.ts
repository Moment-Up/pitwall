// The "Lap 7 done · 2 coaching points" toast's words (spec 2.6). Pure, so it is unit-tested. "done" says the number is
// the lap just finished (the game's numbering, as in Review), not the lap in progress the game's HUD shows.

import type { LapEvent } from "../../lib/live";

/** The server sends at most this many observations with a lap event (core/live.py on_lap_result). */
export const LAP_EVENT_OBSERVATIONS_MAX = 5;

/** "Lap 7 done · 2 coaching points"; "Lap done" when the lap number is unknown; "5+" at the server's cap. */
export function lapToastTitle(ev: LapEvent): string {
  const n = ev.lap["lap_number"];
  const lap = typeof n === "number" && Number.isFinite(n) && n > 0 ? `Lap ${n} done` : "Lap done";
  const k = Array.isArray(ev.observations) ? ev.observations.length : 0;
  if (k === 0) return lap;
  const count = k >= LAP_EVENT_OBSERVATIONS_MAX ? `${LAP_EVENT_OBSERVATIONS_MAX}+` : String(k);
  return `${lap} · ${count} coaching point${k === 1 ? "" : "s"}`;
}

/** Evidence words for the toast's second line: synthetic and replayed laps are always labelled. */
export function lapToastEvidence(conn: { synthetic?: boolean | null; source?: string | null } | null | undefined): string | null {
  if (conn?.synthetic) return "Synthetic data, not from a game";
  if ((conn?.source ?? "").startsWith("replay:")) return "Replay of a recorded session";
  return null;
}
