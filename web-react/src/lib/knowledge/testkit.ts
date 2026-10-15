// Technique knowledge test helpers (tests only; app code never imports this). The fixture in
// src/test/fixtures/knowledge/ is a BACKEND fixture: the graph payload produced by the server's own code (its
// `_fixture` block says how), so the screen is tested against the real content, Ed's brief and checklist included.
// The `?session=` variant (Context, per-node applies / why_not) is being built in parallel: `withSession` adds the
// documented fields by hand ("edited"), never claiming the server sent them.

import type { KnowledgeContext, TechniqueKnowledge } from "../endpoints/knowledge";

interface FixtureFile<T> {
  _fixture: { source: string; recorded: string; what: string; tier: string };
  response: T;
}

const ALL = import.meta.glob<FixtureFile<unknown>>("../../test/fixtures/knowledge/*.json", { eager: true, import: "default" });

function load<T>(name: string): T {
  const f = Object.entries(ALL).find(([p]) => p.endsWith(`/${name}.json`))?.[1];
  if (!f) throw new Error(`no knowledge fixture ${name}`);
  return structuredClone(f.response) as T;
}

export const knowledgeFixtures = {
  /** GET /api/technique/knowledge on feat/knowledge 828dcf8: the plain graph, no session Context. */
  graph: () => load<TechniqueKnowledge>("backend-graph-828dcf8"),
};

export function knowledgeFixtureBlocks(): { name: string; block: FixtureFile<unknown>["_fixture"] }[] {
  return Object.entries(ALL).map(([p, f]) => ({ name: p.split("/").pop() ?? p, block: f._fixture }));
}

/** Hand-made session variant (edited): the plain graph plus a Context and, for chosen node ids, the server's verdict. */
export function withSession(
  g: TechniqueKnowledge,
  context: KnowledgeContext,
  verdicts: Record<string, { applies: boolean; why_not?: string | null }> = {},
): TechniqueKnowledge {
  const mark = <N extends { id: string }>(nodes: N[]): N[] =>
    nodes.map((n) => (verdicts[n.id] ? { ...n, applies: verdicts[n.id]!.applies, why_not: verdicts[n.id]!.why_not ?? null } : n));
  return {
    ...g,
    context,
    style: { braking_style: context.braking_style ?? null, coasting: context.coasting ?? null },
    techniques: mark(g.techniques),
    faults: mark(g.faults),
  };
}

/** The owner's F1 25 profile as the spec measured it: an advanced trail-braker who rarely coasts, F1 car, paddles. */
export const OWNER_F1: KnowledgeContext = {
  skill: "advanced",
  braking_style: "trail",
  coasting: "rare",
  game: "f1",
  car_family: "f1",
  downforce: "high",
  abs: false,
  traction_control: false,
  gearbox: "paddle_autoblip",
  fuel_saving: false,
  wet: false,
};

/** A beginner in a GT7 road car: the car's downforce, ABS and gearbox not reported (unknown). */
export const BEGINNER_GT7: KnowledgeContext = {
  skill: "beginner",
  braking_style: null,
  coasting: null,
  game: "gt7",
  car_family: "other",
  downforce: null,
  abs: null,
  traction_control: null,
  gearbox: null,
  fuel_saving: null,
  wet: null,
};

/** A classic car with a manual gearbox, no ABS and little downforce, driven straight-line by an intermediate. */
export const CLASSIC_MANUAL: KnowledgeContext = {
  skill: "intermediate",
  braking_style: "straight_line",
  coasting: "often",
  game: "ac",
  car_family: "other",
  downforce: "low",
  abs: false,
  traction_control: false,
  gearbox: "h_pattern",
  fuel_saving: false,
  wet: false,
};
