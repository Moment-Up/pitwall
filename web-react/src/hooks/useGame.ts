// React bindings for game selection (lib/endpoints/game.ts, lib/game.ts).
//
//   const cat = useGameCatalog();          // GET /api/games, once per app load (shared cache key)
//   const g = useSnapshotGame();           // snapshot.game, a stable object (re-renders only when it changes)
//   const eff = useEffectiveEntry();       // the game of the data on screen (detected, else selected)
//   const sel = useSelectedEntry();        // the game the household plays (setup flows)
//   const st = useGameState();             // GET /api/game, refetched when the selection changes
//   await selectGame({ id: "gt7:ps5" });   // PUT /api/game, then the caches it touches are invalidated
//
// With an older server (no /api/games, no snapshot.game) every hook answers undefined / null and pages render as
// before.

import { useEffect, useRef } from "react";
import { cache } from "../lib/cache";
import { CONNECT_KEYS } from "../lib/endpoints/connect";
import {
  GAME_KEYS,
  GAMES_MAX_AGE_MS,
  gameApi,
  type GameEntry,
  type GamePut,
  type GamePutResponse,
  type GameState,
  type GamesResponse,
  type SnapshotGame,
} from "../lib/endpoints/game";
import { effectiveEntry, selectedEntry, stableGameSelector } from "../lib/game";
import { useLive } from "./stores";
import { useApi } from "./useApi";

/** The catalogue (static per server version). Undefined until it loads, and with a server that predates it. */
export function useGameCatalog(): GamesResponse | undefined {
  return useApi(GAME_KEYS.games, gameApi.games, { maxAgeMs: GAMES_MAX_AGE_MS }).data;
}

const snapshotGameOf = stableGameSelector();

/** snapshot.game, the same object while its content is unchanged (lib/game.ts stableGameSelector). */
export function useSnapshotGame(): SnapshotGame | undefined {
  return useLive((s) => snapshotGameOf(s.snap));
}

export function useEffectiveEntry(): GameEntry | null {
  return effectiveEntry(useGameCatalog(), useSnapshotGame());
}

export function useSelectedEntry(): GameEntry | null {
  return selectedEntry(useGameCatalog(), useSnapshotGame());
}

/** GET /api/game (selection, input, other inputs, history suggestion). Refetched when snapshot.game.selected_id
 * changes (another device or the CLI chose a game) and after selectGame(). */
export function useGameState(enabled = true): { data: GameState | undefined; error: Error | null; refresh: () => Promise<void> } {
  const selected = useLive((s) => s.snap?.game?.selected_id ?? null);
  const r = useApi(enabled ? GAME_KEYS.state : null, gameApi.state, { maxAgeMs: 0 });
  const prev = useRef(selected);
  useEffect(() => {
    if (prev.current === selected) return;
    prev.current = selected;
    cache.invalidate(GAME_KEYS.state);
  }, [selected]);
  return { data: r.data, error: r.error, refresh: r.refresh };
}

/** PUT /api/game, then refetch what it changed: the game state and the inputs (Setup › Connect). */
export async function selectGame(body: GamePut): Promise<GamePutResponse> {
  const res = await gameApi.put(body);
  cache.invalidate(GAME_KEYS.state);
  cache.invalidate(CONNECT_KEYS.connect);
  cache.invalidate(CONNECT_KEYS.integrations);
  return res;
}

/** DELETE /api/game (the inputs stay as they are). */
export async function clearGame(): Promise<GameState> {
  const res = await gameApi.clear();
  cache.invalidate(GAME_KEYS.state);
  return res;
}
