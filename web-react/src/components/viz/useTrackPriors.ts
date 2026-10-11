// The map's priors (design spec v2, 13: "GET /api/track/outline can draw the circuit before the first clean lap,
// labelled as a shipped seed with its MIT attribution"), through the request cache (hooks/useApi.ts).
//
// The outline is requested only while the learned model has no centreline (the model always wins), and only for a
// real game track (synthetic tracks have none). The physics prior is requested only when asked for. Both endpoints
// answer 404 / 422 when there is nothing trustworthy to draw: that is "unknown", so the hook returns null and the map
// shows its empty state, never a guess. Any network failure is treated the same way (a prior is never essential).

import { useApi } from "../../hooks/useApi";
import { authFetch } from "../../lib/auth";
import { hasCentreline, trackQuery, type BrakePrior, type TrackOutline } from "../../lib/viz/outline";

export interface TrackPriors {
  outline: TrackOutline | null;
  prior: BrakePrior | null;
}

/** Static per track: keep for an hour. */
const MAX_AGE_MS = 3_600_000;

async function getOrNull<T>(path: string): Promise<T | null> {
  try {
    const r = await authFetch(path);
    return r.ok ? ((await r.json()) as T) : null;
  } catch {
    return null;
  }
}

export function fetchTrackOutline(game: string, trackId: string, lengthM: number | null | undefined): Promise<TrackOutline | null> {
  return getOrNull<TrackOutline>(`/api/track/outline?${trackQuery(game, trackId, lengthM)}`);
}

export function fetchBrakePrior(game: string, trackId: string, lengthM: number | null | undefined): Promise<BrakePrior | null> {
  return getOrNull<BrakePrior>(`/api/track/prior?${trackQuery(game, trackId, lengthM)}`);
}

export interface TrackPriorsInput {
  game: string | null | undefined;
  trackId: string | null | undefined;
  /** The session's lap length (session.track_length_m), so the server can gate the outline on it. */
  lengthM?: number | null;
  /** The learned model: while it has a centreline, no outline is requested. */
  model?: { centreline?: readonly unknown[] | null } | null;
  /** Also request the physics prior (default false). */
  prior?: boolean;
}

export function useTrackPriors({ game, trackId, lengthM, model, prior = false }: TrackPriorsInput): TrackPriors {
  const real = Boolean(game && trackId && !trackId.startsWith("synthetic"));
  const q = real ? trackQuery(game as string, trackId as string, lengthM) : "";
  const wantOutline = real && !hasCentreline(model);
  const outline = useApi(wantOutline ? `track-outline:${q}` : null, () => fetchTrackOutline(game as string, trackId as string, lengthM), {
    maxAgeMs: MAX_AGE_MS,
  });
  const brake = useApi(real && prior ? `track-prior:${q}` : null, () => fetchBrakePrior(game as string, trackId as string, lengthM), {
    maxAgeMs: MAX_AGE_MS,
  });
  return { outline: wantOutline ? (outline.data ?? null) : null, prior: real && prior ? (brake.data ?? null) : null };
}
