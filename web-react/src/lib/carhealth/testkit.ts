// Test helpers for the car-health views (imported only by *.test.ts; never by app code). The fixtures
// (src/test/fixtures/carhealth) carry `_fixture` provenance: every one is "edited", hand-built from the lane spec's
// JSON contract (3.11 / 3.12) and its real-capture findings, because the backend worker did not exist when the
// dashboard was built. Test data, not game data: never evidence that a game works.

import type { SnapshotNext } from "../drive/types";
import type { StrategyView } from "../strategy/types";
import type { CarHealthFixtureMeta, CarHealthSettings, CarHealthView, RacecraftView } from "./types";

type WithMeta<T> = T & { _fixture?: CarHealthFixtureMeta };

const ALL = import.meta.glob<WithMeta<unknown>>("../../test/fixtures/carhealth/*.json", { eager: true, import: "default" });

const BY_NAME = new Map(
  Object.entries(ALL).map(([path, v]) => [path.slice(path.lastIndexOf("/") + 1).replace(/\.json$/, ""), v]),
);

export const CARHEALTH_FIXTURES: readonly string[] = [...BY_NAME.keys()].sort();

function get<T>(name: string): WithMeta<T> {
  const v = BY_NAME.get(name);
  if (!v) throw new Error(`no car-health fixture ${name}`);
  return structuredClone(v) as WithMeta<T>;
}

export function healthMeta(name: string): CarHealthFixtureMeta | undefined {
  return get<unknown>(name)._fixture;
}

/** A CarHealthView fixture (`edited-live-*`), deep-copied. */
export function healthView(name: string): WithMeta<CarHealthView> {
  return get<CarHealthView>(name);
}

/** A RacecraftView fixture (`edited-racecraft-*`), deep-copied. */
export function racecraftView(name: string): WithMeta<RacecraftView> {
  return get<RacecraftView>(name);
}

/** A settings payload fixture (`edited-settings-*`), deep-copied. */
export function settingsFixture(name: string): WithMeta<CarHealthSettings> {
  return get<CarHealthSettings>(name);
}

/** The strategy view with rejoin v2 (`edited-strategy-race-rejoin-v2`), deep-copied. */
export function rejoinStrategy(): WithMeta<StrategyView> {
  return get<StrategyView>("edited-strategy-race-rejoin-v2");
}

/** Put the blocks on a snapshot as /ws/live carries them: same session as the snapshot. Edits in place, returns it. */
export function withHealth<T extends SnapshotNext>(
  s: T,
  blocks: { car_health?: CarHealthView | null; racecraft?: RacecraftView | null; strategy?: StrategyView | null },
): T {
  if (blocks.car_health !== undefined) {
    s.car_health = blocks.car_health ? { ...blocks.car_health, session_id: s.session_id } : blocks.car_health;
  }
  if (blocks.racecraft !== undefined) {
    s.racecraft = blocks.racecraft ? { ...blocks.racecraft, session_id: s.session_id } : blocks.racecraft;
  }
  if (blocks.strategy !== undefined) {
    s.strategy = blocks.strategy ? { ...blocks.strategy, session_id: s.session_id } : blocks.strategy;
  }
  return s;
}
