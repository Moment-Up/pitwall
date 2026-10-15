// The Records section's data (leaderboard spec 5): the boards at this track where the viewed driver has a lap
// (`/api/records?driver_id`, for the board to open on), then one exact board (`/api/leaderboard`): the one picked
// in the section, else the viewed driver's newest here in the scope's car, else the server's pick by fields. The pick
// belongs to its scope (driver, track, car): a new scope opens on its own default. `generation` is the driver's
// answer to "a 2025 or a 2026 car?" when the game cannot tell; it only fills in the real-F1 row.

import { useCallback, useRef, useState } from "react";
import { useApi } from "../../../hooks/useApi";
import { leaderboardApi, leaderboardKeys, type CarGeneration, type LeaderboardBoard } from "../../../lib/endpoints/leaderboard";
import { isMissingRoute } from "../../../lib/endpoints/review";
import { boardQuery, defaultBoardKey, recordsIndexQuery } from "../../../lib/review/records";
import type { Scope } from "../../../lib/review/progress";

export interface RecordsState {
  /** The board on show: the last answer for this scope while a new pick or generation loads (`loading`). */
  board: LeaderboardBoard | undefined;
  error: Error | null;
  /** The server has no leaderboard routes (an older Pitwall). */
  missing: boolean;
  /** A request is in flight. */
  loading: boolean;
  /** Open another board here (a key from `boards_here`). */
  pick: (key: string) => void;
  generation: CarGeneration | null;
  setGeneration: (g: CarGeneration) => void;
}

const MAX_AGE_MS = 60_000;

function scopeIdOf(scope: Scope | null, viewedId: number | null): string {
  return scope ? `${viewedId ?? ""}|${scope.track.game}|${scope.track.trackId}|${scope.carId ?? ""}` : "";
}

export function useRecords(scope: Scope | null, viewedId: number | null): RecordsState {
  const scopeId = scopeIdOf(scope, viewedId);
  const [picked, setPicked] = useState<{ scopeId: string; key: string } | null>(null);
  const [generation, setGeneration] = useState<CarGeneration | null>(null);

  const iq = scope && viewedId != null ? recordsIndexQuery(scope, viewedId) : null;
  const index = useApi(iq ? leaderboardKeys.records(iq) : null, () => leaderboardApi.records(iq ?? {}), {
    maxAgeMs: MAX_AGE_MS,
  });
  // Wait for the driver's boards before asking for one (no flash of another board); an error falls back to fields.
  const ready = iq == null || index.data !== undefined || index.error != null;
  const pickKey = picked?.scopeId === scopeId ? picked.key : null;
  const q =
    scope && ready
      ? boardQuery(scope, { pick: pickKey, fallbackKey: defaultBoardKey(index.data?.boards, scope), generation })
      : null;
  const board = useApi(q ? leaderboardKeys.board(q) : null, () => leaderboardApi.board(q!), { maxAgeMs: MAX_AGE_MS });

  // Keep the board on screen while another one of the same scope loads (a pick, the generation).
  const last = useRef<{ scopeId: string; board: LeaderboardBoard } | null>(null);
  if (board.data && last.current?.board !== board.data) last.current = { scopeId, board: board.data };
  const shown = board.data ?? (last.current?.scopeId === scopeId ? last.current.board : undefined);

  const pick = useCallback((key: string) => setPicked({ scopeId, key }), [scopeId]);
  const error = board.error ?? null;
  return {
    board: shown,
    error,
    missing: isMissingRoute(error) || (isMissingRoute(index.error) && !board.data),
    loading: !ready || board.loading,
    pick,
    generation,
    setGeneration,
  };
}
