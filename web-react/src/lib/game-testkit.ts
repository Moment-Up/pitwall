// Test helpers for game selection (imported only by *.test.ts; never by app code). The fixtures in
// src/test/fixtures/game are the JSON contract of the game-selection design spec (section 9), emitted by the backend's
// pure functions (src/pitwall/games.py: games_response, snapshot_block, game_state, ensure_input on a temporary
// store) from hand-built inputs, and checked against the spec's golden profiles (2.6) by game.test.ts. They carry
// `_fixture.tier = "edited"`: no game data, no running server - never evidence that a game works.

import type { GameEntry, GamePutResponse, GameState, GamesResponse, SnapshotGame } from "./endpoints/game";

const ALL = import.meta.glob<unknown>("../test/fixtures/game/*.json", { eager: true, import: "default" });

const BY_NAME = new Map(
  Object.entries(ALL).map(([path, v]) => [path.slice(path.lastIndexOf("/") + 1).replace(/\.json$/, ""), v]),
);

function load<T>(name: string): T {
  const v = BY_NAME.get(name);
  if (v === undefined) throw new Error(`no game fixture ${name}`);
  return structuredClone(v) as T;
}

/** GET /api/games */
export function catalogue(): GamesResponse {
  return load<GamesResponse>("games-response");
}

/** One catalogue entry by id (throws when missing). */
export function entry(id: string, cat: GamesResponse = catalogue()): GameEntry {
  const e = cat.entries.find((x) => x.id === id);
  if (!e) throw new Error(`no entry ${id}`);
  return e;
}

/** snapshot.game: "none" | "suggest" | "mismatch" | "gt7" | "synthetic" | "variant" | "ac" | "forza". */
export function snapGame(name: string): SnapshotGame {
  return load<SnapshotGame>(`snapshot-game-${name}`);
}

/** GET /api/game: "first-run" | "gt7" | "ac" | "mismatch" | "acc" (ACC on PS5) | "acc-pc" (on a Mac) | "forza". */
export function gameState(name: string): GameState {
  return load<GameState>(`state-${name}`);
}

export function putResponse(): GamePutResponse {
  return load<GamePutResponse>("put-gt7");
}

/** GET /api/games/gt7:ps5 (with fields). */
export function entryWithFields(): GameEntry {
  return load<GameEntry>("entry-gt7-ps5");
}
