// Test helpers for the strategy views (imported only by *.test.ts; never by app code). The fixtures
// (src/test/fixtures/strategy) carry `_fixture` provenance: "edited" ones are hand-built from the strategy spec's
// figures; "recorded" ones are the backend's scripts/strategy_check.py over the committed PS5 excerpts; "synthetic"
// ones are the backend's race-strategy-demo scenario run through the same engine. Test data, not game data.

import { snap } from "../drive/testkit";
import type { SnapshotNext } from "../drive/types";
import type { StrategyFixtureMeta, StrategyTimeline, StrategyView } from "./types";

type WithMeta<T> = T & { _fixture?: StrategyFixtureMeta };

const ALL = import.meta.glob<WithMeta<StrategyView | StrategyTimeline>>("../../test/fixtures/strategy/*.json", {
  eager: true,
  import: "default",
});

const BY_NAME = new Map(
  Object.entries(ALL).map(([path, v]) => [path.slice(path.lastIndexOf("/") + 1).replace(/\.json$/, ""), v]),
);

export const STRATEGY_FIXTURES: readonly string[] = [...BY_NAME.keys()].sort();

function get(name: string): WithMeta<StrategyView | StrategyTimeline> {
  const v = BY_NAME.get(name);
  if (!v) throw new Error(`no strategy fixture ${name}`);
  return structuredClone(v);
}

/** A fixture's provenance block. */
export function fixtureMeta(name: string): StrategyFixtureMeta | undefined {
  return get(name)._fixture;
}

/** A live StrategyView fixture (`edited-live-*`), deep-copied. */
export function liveView(name: string): WithMeta<StrategyView> {
  return get(name) as WithMeta<StrategyView>;
}

/** A timeline fixture (`edited-timeline-*`), deep-copied. */
export function timeline(name: string): WithMeta<StrategyTimeline> {
  return get(name) as WithMeta<StrategyTimeline>;
}

/** A minimal live snapshot carrying a strategy view. */
export function snapWith(view: StrategyView | null | undefined, over: Partial<SnapshotNext> = {}): SnapshotNext {
  return snap({ strategy: view, ...over });
}

/** A race view with every block null (the engine before its first data). */
export function bareRace(over: Partial<StrategyView> = {}): StrategyView {
  return {
    version: 1,
    mode: "race",
    reason: null,
    session_id: "s1",
    synthetic: false,
    lap: null,
    total_laps: null,
    laps_remaining: null,
    position: null,
    cars: null,
    gaps: null,
    tyres: null,
    fuel: null,
    pit: null,
    safety_car: null,
    weather: null,
    calls: [],
    ...over,
  };
}
