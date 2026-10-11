// Technique test helpers (tests only; app code never imports this). Fixtures in src/test/fixtures/technique/*.json are
// CONTRACT fixtures ("edited-"): the shapes are the feat/technique spec's JSON contract, written before the backend
// could be recorded; geometry and identities come from recorded review fixtures where noted, every technique value is
// hand-made sample data. Each file's `_fixture` block says so. They are never evidence that a game works.

import type { ExperimentBalance, TechniqueBalance, TechniqueCompare, TechniqueSession } from "../endpoints/technique";

interface FixtureFile<T> {
  _fixture: { source: string; recorded: string; what: string; tier: "recorded" | "synthetic" | "edited" };
  response: T;
}

const ALL = import.meta.glob<FixtureFile<unknown>>("../../test/fixtures/technique/*.json", { eager: true, import: "default" });

function load<T>(name: string): T {
  const f = Object.entries(ALL).find(([p]) => p.endsWith(`/${name}.json`))?.[1];
  if (!f) throw new Error(`no technique fixture ${name}`);
  return structuredClone(f.response) as T;
}

export const techniqueFixtures = {
  /** Austria race 332904dbe3de (recorded identities and lap ids), reference lap 64 (id 52); hand-made values. */
  austriaSession: () => load<TechniqueSession>("edited-austria-technique-session"),
  /** Lap 66 (id 54) against lap 64 (id 52): the reference line is the recorded track model's centreline. */
  austriaCompare: () => load<TechniqueCompare>("edited-austria-technique-compare-52-54"),
  /** Suzuka df149ca2d149 (the car setup fixtures' session): car and driving symptoms, suggestions, one blocked. */
  suzukaBalance: () => load<TechniqueBalance>("edited-suzuka-technique-balance"),
  /** A GT7 session: no slip, so no balance and no setup suggestions, with the reasons. */
  gt7Balance: () => load<TechniqueBalance>("edited-gt7-technique-balance"),
  gt7Session: () => load<TechniqueSession>("edited-gt7-technique-session"),
  /** An F1 session recorded before the slip channels existed. */
  oldF1Balance: () => load<TechniqueBalance>("edited-old-f1-technique-balance"),
  /** A session with no reference lap yet: line and inputs unavailable. */
  noReference: () => load<TechniqueSession>("edited-no-reference-technique-session"),
  /** `after_metrics.comparison.balance` for a concluded experiment. */
  experimentBalance: () => load<ExperimentBalance>("edited-experiment-balance"),
};

export function techniqueFixtureBlocks(): { name: string; block: FixtureFile<unknown>["_fixture"] }[] {
  return Object.entries(ALL).map(([p, f]) => ({ name: p.split("/").pop() ?? p, block: f._fixture }));
}

/** Words that would turn a description into advice (design spec P9; the spec's "never recommends braking later"). */
export const ADVICE_WORDS: readonly RegExp[] = [
  /\bbrake later\b/i,
  /\bbraking later\b/i,
  /\bbrake earlier\b/i,
  /\bbrake harder\b/i,
  /\byou should\b/i,
  /\btry to\b/i,
  /\btake a (?:tighter|wider) line\b/i,
  /\bturn in (?:earlier|later)\b/i,
];
