// Updates card test helpers (tests only; app code never imports this). Fixtures in src/test/fixtures/update/*.json are
// hand-written from the lane install JSON contract ("contract-", spec §7), or real responses of an isolated test
// server talking to a local fake GitHub ("server-": real server code, made-up releases), each with a `_fixture` block
// saying where it came from. Neither is game telemetry, so no evidence tier applies to them.

import type { UpdateStatus } from "../../../lib/endpoints/update";

interface FixtureFile {
  _fixture: { source: string; recorded: string; what: string; tier: "contract" | "server"; edited?: string };
  response: UpdateStatus;
}

const ALL = import.meta.glob<FixtureFile>("../../../test/fixtures/update/*.json", { eager: true, import: "default" });

/** The tests' clock (seconds): 12 Oct 2026 18:00 UTC. The contract fixtures' times are relative to it. */
export const NOW = 1_791_828_000;

export type UpdateFixture =
  | "contract-available"
  | "contract-available-several"
  | "contract-up-to-date"
  | "contract-never-auto"
  | "contract-checking"
  | "contract-failed"
  | "contract-off"
  | "contract-git"
  | "server-git-never"
  | "server-git-available";

export function updateFixture(name: UpdateFixture, edit: Partial<UpdateStatus> = {}): UpdateStatus {
  return { ...rawUpdateFixture(name), ...edit };
}

/** The fixture's response exactly as stored. */
export function rawUpdateFixture(name: UpdateFixture): UpdateStatus {
  const f = Object.entries(ALL).find(([p]) => p.endsWith(`/${name}.json`))?.[1];
  if (!f) throw new Error(`no update fixture ${name}`);
  return structuredClone(f.response);
}

/** Every fixture file's provenance block. */
export function updateFixtureBlocks(): { name: string; block: FixtureFile["_fixture"] }[] {
  return Object.entries(ALL).map(([p, f]) => ({ name: p.split("/").pop() ?? p, block: f._fixture }));
}
