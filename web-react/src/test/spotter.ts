// F1 spotter test helpers (tests only; app code never imports this). Fixtures in src/test/fixtures/spotter/*.json are
// hand-written from the lane's JSON contracts (design spec 8.2 GET /api/spotter, 8.3 the /ws/live block), each with a
// `_fixture` block saying what it is. They are "contract" fixtures: no server produced them yet and they are not game
// telemetry, so they validate the dashboard against the contract, never game compatibility. Replace or add "server-"
// fixtures from a real spotter server once the backend lane lands.

interface FixtureFile {
  _fixture: { tier: "contract" | "server"; source: string; recorded: string; what: string };
  response: unknown;
}

const ALL = import.meta.glob<FixtureFile>("./fixtures/spotter/*.json", { eager: true, import: "default" });

export type SpotterLiveFixture =
  | "live-alongside-left"
  | "live-clear"
  | "live-close-right"
  | "live-three-wide"
  | "live-outside-three-wide"
  | "live-safety-car"
  | "live-off"
  | "live-newer-version";

export type SpotterApiFixture = "contract-active" | "contract-off" | "contract-gt7" | "contract-low-rate";

/** The fixture's response exactly as stored (a fresh copy). */
export function spotterFixture(name: SpotterLiveFixture | SpotterApiFixture): unknown {
  const f = Object.entries(ALL).find(([p]) => p.endsWith(`/${name}.json`))?.[1];
  if (!f) throw new Error(`no spotter fixture ${name}`);
  return structuredClone(f.response);
}

export function spotterFixtureMeta(name: SpotterLiveFixture | SpotterApiFixture): FixtureFile["_fixture"] {
  const f = Object.entries(ALL).find(([p]) => p.endsWith(`/${name}.json`))?.[1];
  if (!f) throw new Error(`no spotter fixture ${name}`);
  return f._fixture;
}

export const SPOTTER_FIXTURE_NAMES: readonly string[] = Object.keys(ALL).map((p) => p.replace(/^.*\//, "").replace(/\.json$/, ""));
