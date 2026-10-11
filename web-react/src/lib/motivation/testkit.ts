// Motivation test helpers (tests only; app code never imports this). Fixtures in src/test/fixtures/motivation/ are
// hand-written from the lane's JSON contract (lane spec section 6) with the prototype's numbers on real data
// (section 12) and a fictional driver ("Sam"); each carries a `_fixture` block saying so. They are test data, never
// game evidence and never a server's answer.

import type {
  BadgesResponse,
  GoalsResponse,
  MotivationNote,
  SessionRecap,
  SuggestionsResponse,
  WeeklyDigest,
} from "../endpoints/motivation";

export interface MotivationFixture<T> {
  _fixture: { tier: "edited"; source: string; what: string; notes?: string };
  response: T;
}

const ALL = import.meta.glob<MotivationFixture<unknown>>("../../test/fixtures/motivation/*.json", {
  eager: true,
  import: "default",
});

function load<T>(name: string): T {
  const f = Object.entries(ALL).find(([p]) => p.endsWith(`/${name}.json`))?.[1];
  if (!f) throw new Error(`no motivation fixture ${name}`);
  return structuredClone(f.response) as T;
}

export const mfx = {
  goals: () => load<GoalsResponse>("edited-goals-sam"),
  goalsEmpty: () => load<GoalsResponse>("edited-goals-empty"),
  suggestions: () => load<SuggestionsResponse>("edited-suggestions-austria-haas"),
  suggestionsNone: () => load<SuggestionsResponse>("edited-suggestions-none"),
  suggestionsGt7: () => load<SuggestionsResponse>("edited-suggestions-gt7"),
  badges: () => load<BadgesResponse>("edited-badges-sam"),
  badgesEmpty: () => load<BadgesResponse>("edited-badges-empty"),
  digest: () => load<WeeklyDigest>("edited-digest-week"),
  digestEmpty: () => load<WeeklyDigest>("edited-digest-empty"),
  recap: () => load<SessionRecap>("edited-recap-austria"),
  recapReached: () => load<SessionRecap>("edited-recap-goal-reached"),
  recapBeginner: () => load<SessionRecap>("edited-recap-suzuka-beginner"),
  recapSynthetic: () => load<SessionRecap>("edited-recap-synthetic"),
  recapReplay: () => load<SessionRecap>("edited-recap-replay"),
  recapNoClean: () => load<SessionRecap>("edited-recap-no-clean"),
  note: () => load<MotivationNote>("edited-note-goal"),
};

/** Every fixture's provenance block. */
export function motivationFixtureBlocks(): { name: string; block: MotivationFixture<unknown>["_fixture"] }[] {
  return Object.entries(ALL).map(([p, f]) => ({ name: p.split("/").pop() ?? p, block: f._fixture }));
}
