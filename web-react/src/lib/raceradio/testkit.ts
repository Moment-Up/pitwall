// Test helpers for the race-radio views (imported only by *.test.ts; never by app code). The fixtures
// (src/test/fixtures/raceradio) carry `_fixture` provenance. All are "edited" for now: hand-built from the RaceView v1
// contract (race-radio spec 9.3) with figures from the spec's real-data findings, until the backend's
// scripts/race_radio_check.py can write recorded ones. Test data, not game data.

import type { SnapshotNext } from "../drive/types";
import type { RaceFixtureMeta, RaceView } from "./types";

type WithMeta = RaceView & { _fixture?: RaceFixtureMeta };

const ALL = import.meta.glob<WithMeta>("../../test/fixtures/raceradio/*.json", { eager: true, import: "default" });

const BY_NAME = new Map(
  Object.entries(ALL).map(([path, v]) => [path.slice(path.lastIndexOf("/") + 1).replace(/\.json$/, ""), v]),
);

export const RACE_FIXTURES: readonly string[] = [...BY_NAME.keys()].sort();

/** A race-view fixture, deep-copied, with its `_fixture` block. */
export function raceFixture(name: string): WithMeta {
  const v = BY_NAME.get(name);
  if (!v) throw new Error(`no race-radio fixture ${name}`);
  return structuredClone(v);
}

/** A race-view fixture as the wire carries it (no `_fixture`), deep-copied. */
export function raceView(name: string): RaceView {
  const { _fixture: _meta, ...v } = raceFixture(name);
  return v;
}

/** The snapshot with this race block, as the server would send it for the snapshot's own session. Edits in place
 * and returns it. */
export function withRace<T extends SnapshotNext>(s: T, view: RaceView | null): T {
  s.race = view ? { ...view, session_id: s.session_id ?? view.session_id } : view;
  return s;
}
