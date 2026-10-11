// Drive fixtures (src/test/fixtures/drive/*.json): real snapshots from headless replays of PS5 captures
// ("recorded-"; "recorded-d246-" through the backend that adds D2 / D4 / D6), the synthetic demo ("synthetic-"), an
// idle pipeline ("pipeline-") and documented hand edits for states no capture reaches yet ("edited-"; every changed
// field is listed in `_fixture.edits`). Together they reach every Drive state and overlay (fixtures.test.ts).
//
// Loaded lazily, one chunk per fixture, so a dev-only state picker never pulls them all into the Drive bundle.
// Never show a fixture as live data: its evidence tier is in `_fixture.tier`.

import type { FixtureSnapshot } from "./types";

const LOADERS = import.meta.glob<FixtureSnapshot>("../../test/fixtures/drive/*.json", { import: "default" });

function nameOf(path: string): string {
  return path.slice(path.lastIndexOf("/") + 1).replace(/\.json$/, "");
}

const BY_NAME = new Map(Object.entries(LOADERS).map(([path, load]) => [nameOf(path), load]));

/** Every fixture name, sorted ("recorded-suzuka-on-track-brake-ahead", ...). */
export const FIXTURE_NAMES: readonly string[] = [...BY_NAME.keys()].sort();

/** Load one fixture by name. */
export async function loadFixture(name: string): Promise<FixtureSnapshot> {
  const load = BY_NAME.get(name);
  if (!load) throw new Error(`unknown Drive fixture: ${name}`);
  return load();
}
