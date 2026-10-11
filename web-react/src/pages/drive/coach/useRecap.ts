// The session recap for Drive's stopped cards (lane motivation, spec 9 Drive). Lane DV.
//
// Drive makes REST calls only for the cards shown while the car is stopped (P10: on track it is /ws/live and the
// radio store only): the recap is asked for in the garage (the Ready card's goal row, between runs) and once the
// session is over (the Session complete card's three things), never on track. The key carries the lap count, the
// newest goal note and the car (F1 sends it a few seconds after the session starts: a recap asked before it has no
// lap-time goal in scope), so a lap, a goal reached or the car arriving asks again; data younger than 30 s is served
// from the cache.
// An older server (404) or an error leaves the cards as they were before (the D6 Work on / Went well). While a newer
// key loads, the last recap of the same session stays on screen (nothing flickers between runs).

import { useRef } from "react";
import { useApi } from "../../../hooks/useApi";
import { motivationApi, motivationKeys, type MotivationNote, type SessionRecap } from "../../../lib/endpoints/motivation";
import type { DriveState } from "../../../lib/drive/state";
import type { DriveMotivation } from "../../../lib/motivation/drive";

export const RECAP_MAX_AGE_MS = 30_000;

/** States whose card reads the recap (Ready, Session complete). */
export function recapWanted(state: DriveState | null | undefined): boolean {
  return state === "garage" || state === "ended";
}

export function useRecap(
  sessionId: string | null | undefined,
  laps: number,
  note: MotivationNote | null,
  state: DriveState | null,
  carId: string | null = null,
): DriveMotivation {
  const want = recapWanted(state) && !!sessionId;
  const noteT = note && note.session_id === sessionId ? note.t : null;
  const r = useApi(
    want && sessionId ? motivationKeys.driveRecap(sessionId, laps, noteT, carId) : null,
    () => motivationApi.recap(sessionId as string),
    { enabled: want, maxAgeMs: RECAP_MAX_AGE_MS },
  );
  const last = useRef<SessionRecap | null>(null);
  if (r.data) last.current = r.data;
  if (!want) return { note, recap: null, status: "off" };
  if (r.data) return { note, recap: r.data, status: "ready" };
  if (r.error) return { note, recap: null, status: "error" };
  const prev = last.current && last.current.session_id === sessionId ? last.current : null;
  return prev ? { note, recap: prev, status: "ready" } : { note, recap: null, status: "loading" };
}
