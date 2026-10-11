// Review test helpers (tests only; app code never imports this). Fixtures in src/test/fixtures/review/*.json are
// real responses of the live API recorded read-only ("recorded-"), or the SYNTHETIC demo ("synthetic-"), each with a
// `_fixture` block saying where it came from. A synthetic fixture is never game evidence.

import type { Driver } from "../drivers";
import type { LapTrace } from "../api";
import type {
  CompareResponse,
  DriverAiPace,
  DriverProgress,
  LiveAiPace,
  SessionAiPace,
  EngineerHistoryRow,
  SessionAnalysis,
  SessionDetail,
  SessionListRow,
} from "../endpoints/review";

interface FixtureFile<T> {
  _fixture: { source: string; recorded: string; what: string; tier: "recorded" | "synthetic"; edited?: string };
  response: T;
}

const ALL = import.meta.glob<FixtureFile<unknown>>("../../test/fixtures/review/*.json", { eager: true, import: "default" });

function load<T>(name: string): T {
  const f = Object.entries(ALL).find(([p]) => p.endsWith(`/${name}.json`))?.[1];
  if (!f) throw new Error(`no review fixture ${name}`);
  return structuredClone(f.response) as T;
}

export const fixtures = {
  sessions: () => load<SessionListRow[]>("recorded-sessions-list"),
  drivers: () => load<{ active_id: number | null; drivers: Driver[] }>("recorded-drivers"),
  austria: () => load<SessionDetail>("recorded-austria-race-session"),
  austriaAnalysis: () => load<SessionAnalysis>("recorded-austria-race-analysis"),
  demo: () => load<SessionDetail>("synthetic-demo-session"),
  demoAnalysis: () => load<SessionAnalysis>("synthetic-demo-analysis"),
  emptyAnalysis: () => load<SessionAnalysis>("recorded-no-laps-analysis"),
  /** Austria lap 64 (id 52, the reference) and lap 66 (id 54), 5 m grid, channels trimmed (see `_fixture.edited`). */
  trace52: () => load<LapTrace>("recorded-austria-trace-52"),
  trace54: () => load<LapTrace>("recorded-austria-trace-54"),
  /** /api/compare?ref=52&lap=54 (lap 66 against lap 64). */
  compare: () => load<CompareResponse>("recorded-austria-compare-64-66"),
  /** /api/compare?ref=53&lap=54: blocked, the reference (lap 65) is a flashback lap. */
  compareBlocked: () => load<CompareResponse>("recorded-austria-compare-blocked"),
  /** /api/engineer/history?session_id=a100cbc9b5bd (a question and an LLM-grounded answer). */
  history: () => load<EngineerHistoryRow[]>("recorded-engineer-history"),
  /** D5 for James at Austria in the Haas (f1:team:7): sessions a100cbc9b5bd and 332904dbe3de (the Austria fixture). */
  progressAustriaHaas: () => load<DriverProgress>("recorded-progress-austria-haas"),
  /** D5 for James at Austria in any car (F1 Generic, then the Haas twice). */
  progressAustriaAny: () => load<DriverProgress>("recorded-progress-austria-any"),
  /** D5 for James at Silverstone in the F1 Generic car (only the last of 3 sessions has clean laps). */
  progressSilverstone: () => load<DriverProgress>("recorded-progress-silverstone"),
};

// AI pace contract fixtures (src/test/fixtures/aipace): the frozen contract's shapes (AI pace design spec 6) filled
// with real values from the spec's prototype over the owner's real PS5 F1 25 captures; tier "contract" until the
// backend route records real responses. The "recorded-" files are the real backend's answers for the same captures
// (a scratch server of this branch fed the captures over local UDP), and tests pin the contract fixtures to them.
interface AiFixtureFile<T> {
  _fixture: { source: string; recorded: string; what: string; tier: "contract" | "recorded"; edited?: string };
  response: T;
}

const AI = import.meta.glob<AiFixtureFile<unknown>>("../../test/fixtures/aipace/*.json", { eager: true, import: "default" });

function loadAi<T>(name: string): T {
  const f = Object.entries(AI).find(([p]) => p.endsWith(`/${name}.json`))?.[1];
  if (!f) throw new Error(`no AI pace fixture ${name}`);
  return structuredClone(f.response) as T;
}

export const aiFixtures = {
  /** Austria race (e2c05b9f70f3) at AI 35 in F1 World cars: 3.8 s slower than the typical AI car, 20th of 20. */
  austria: () => loadAi<SessionAiPace>("contract-session-austria"),
  /** The review fixture's session (332904dbe3de, Austria scenario in the Haas) at AI 31: 4.9 s faster, 1st of 18. */
  austriaScenario: () => loadAi<SessionAiPace>("contract-session-austria-scenario"),
  /** Melbourne F2 race (1e7271f70c5e) at AI 35: 3.2 s faster, 1st of 22. */
  melbourne: () => loadAi<SessionAiPace>("contract-session-melbourne"),
  /** Monza race (33d6d86134af): too few AI cars seen (3 of 5). */
  monza: () => loadAi<SessionAiPace>("contract-session-monza"),
  /** snapshot.ai_pace for the Austria race. */
  live: () => loadAi<LiveAiPace>("contract-live-austria"),
  /** GET /api/drivers/1/ai-pace (no scope): 5 races, 4 direction-only suggestions. */
  driverAll: () => loadAi<DriverAiPace>("contract-driver-all"),
  /** GET /api/drivers/1/ai-pace?game=f1_25&track_id=f1:17: Austria in F1 World (AI 35) and F1 Modern (AI 31 twice). */
  driverAustria: () => loadAi<DriverAiPace>("contract-driver-austria"),
  /** The real backend's answers for the same captures (a scratch server of this branch; other session ids). */
  recorded: {
    sessionAustria: () => loadAi<SessionAiPace>("recorded-session-austria"),
    driverAustria: () => loadAi<DriverAiPace>("recorded-driver-austria"),
    driverAll: () => loadAi<DriverAiPace>("recorded-driver-all"),
  },
};

/** Every AI pace fixture's provenance block. */
export function aiFixtureBlocks(): { name: string; block: AiFixtureFile<unknown>["_fixture"] }[] {
  return Object.entries(AI).map(([p, f]) => ({ name: p.split("/").pop() ?? p, block: f._fixture }));
}

/** Every fixture file's provenance block (tests check each says where it came from). */
export function fixtureBlocks(): { name: string; block: FixtureFile<unknown>["_fixture"] }[] {
  return Object.entries(ALL).map(([p, f]) => ({ name: p.split("/").pop() ?? p, block: f._fixture }));
}

/** A driver profile for tests (the recorded James with another id, name and level). */
export function driver(id: number, name: string, level: Driver["preferences"]["skill_level"], simple = level === "beginner"): Driver {
  const base = fixtures.drivers().drivers[0]!;
  return {
    ...base,
    id,
    name,
    active: false,
    preferences: { ...base.preferences, skill_level: level, initials: name.slice(0, 2).toUpperCase() },
    coaching: { ...base.coaching, skill_level: level, simple_wording: simple },
  };
}
