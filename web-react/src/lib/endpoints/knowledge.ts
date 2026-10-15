// Technique knowledge endpoint (technique knowledge graph spec, sections 1 and 3): typed client for
// GET /api/technique/knowledge (src/pitwall/api/routes_knowledge.py; the graph is pitwall.knowledge.graph, its data the
// TOML files in src/pitwall/knowledge/graph/, its guide docs/knowledge.md).
//
// The whole graph, validated by the server: phases, conditions, techniques, signals, faults, causes, advice,
// constraints and sources, each node with its evidence tier, sources and file, plus the typed edges. Deterministic
// data: nothing here comes from an LLM. A graph that did not load is 503 with {message, errors}; a server before the
// graph answers FastAPI's own 404 and Review leaves the section out.
//
// `?session=<id>` (spec section 3) adds the session's driver and car Context, the detected style and per-node
// `applies` / `why_not`. Every one of those is OPTIONAL here: a server without that variant ignores the parameter and
// sends the plain graph, and a session it does not know (404 with a detail) falls back to the plain graph too, so the
// screen works with either (lib/knowledge/view.ts then judges fit from what the page knows: the profile's level).
//
// Cache keys (lib/cache.ts): the plain graph changes only with a release ("technique-knowledge", ten minutes fresh);
// a session's variant sits under "analysis:<id>" so a completed lap of the live session (a new style reading)
// refreshes it with the analysis (hooks/useApi.ts).

import { ApiError } from "../api";
import { authFetch } from "../auth";

export type KnowledgeTier = "expert" | "brief" | "synthetic" | "recorded" | "live" | "design";
export type FaultStatus = "live" | "experimental" | "planned" | "context_only";
export type ContextKey =
  | "skill"
  | "braking_style"
  | "coasting"
  | "game"
  | "car_family"
  | "downforce"
  | "abs"
  | "traction_control"
  | "gearbox"
  | "fuel_saving"
  | "wet";

/** Fields every node has (pitwall.knowledge.graph.Node.to_dict), plus the session variant's optional verdict. */
export interface KnowledgeNode {
  type: string;
  id: string;
  name: string;
  summary: string;
  tier: KnowledgeTier;
  /** Source ids (KnowledgeSource.id). */
  sources: string[];
  /** For contributors; never shown to drivers. */
  notes: string | null;
  /** The graph file it lives in ("techniques.toml"). */
  file: string;
  /** `?session=` only: whether the node applies to this session's driver and car. Absent from the plain graph. */
  applies?: boolean | null;
  /** `?session=` only: why it does not apply, in plain words. */
  why_not?: string | null;
}

export interface KnowledgePhase extends KnowledgeNode {
  type: "phase";
  order: number;
}

/** Atomic (`key` `op` `value`) or compound (`all_of` / `any_of` other conditions). */
export interface KnowledgeCondition extends KnowledgeNode {
  type: "condition";
  key: ContextKey | null;
  op: "eq" | "ne" | "in" | "true" | "false" | null;
  value: string | string[] | null;
  all_of: string[];
  any_of: string[];
}

export interface KnowledgeTechnique extends KnowledgeNode {
  type: "technique";
  phase: string;
  detail: string;
  /** Condition ids: all must hold. */
  applies_when: string[];
  /** Condition ids: at least one must hold (empty = no such test). */
  applies_any: string[];
  /** Technique ids, listed both ways. */
  alternatives: string[];
  /** Signal ids. */
  measured_by: string[];
}

export interface KnowledgeMeasurement {
  metric: string;
  value: number;
  /** Free text ("%", "s"). */
  unit: string;
  date: string;
  /** Source id. */
  source: string;
  note: string | null;
}

export interface KnowledgeSignal extends KnowledgeNode {
  type: "signal";
  /** "CornerMetrics.trail_brake_m"; null = not computed by Pitwall yet. */
  code: string | null;
  unit: string;
  channels: string[];
  noise: KnowledgeMeasurement[];
}

export interface KnowledgeFault extends KnowledgeNode {
  type: "fault";
  phase: string;
  /** live = a coaching rule says it today; experimental / planned / context_only = not coached. */
  status: FaultStatus;
  relative: "reference" | "absolute";
  /** The coaching kind (Observation.kind) when live. */
  kind: string | null;
  /** Praise (exit_gain), not a fault. */
  positive: boolean;
  violates: string[];
  signals: string[];
  thresholds: { name: string; value: number }[];
  applies_when: string[];
  applies_any: string[];
  causes: string[];
  advice: string[];
  measured: KnowledgeMeasurement[];
}

export interface KnowledgeDiscriminator {
  signal: string;
  test: string;
  op: "lt" | "le" | "gt" | "ge" | "true" | "false";
  value: number | null;
  need: "all" | "any";
  note: string | null;
}

export interface KnowledgeCause extends KnowledgeNode {
  type: "cause";
  explains: string[];
  advice: string[];
  discriminators: KnowledgeDiscriminator[];
}

export interface KnowledgeAdvice extends KnowledgeNode {
  type: "advice";
  for: string;
  skill: "beginner" | "intermediate" | "advanced" | "any";
  kind: "describe" | "explain" | "drill";
  review: string;
  radio: string | null;
  screen: string | null;
  style: "trail" | "straight_line" | "mixed" | null;
}

export interface KnowledgeConstraint extends KnowledgeNode {
  type: "constraint";
  text: string;
  forbidden: string[];
  scope: string[];
  except_praise: boolean;
}

export interface KnowledgeSource extends KnowledgeNode {
  type: "source";
  title: string;
  author: string;
  /** What Pitwall took from it, paraphrased. */
  note: string;
  url: string | null;
  /** YYYY, YYYY-MM or YYYY-MM-DD. */
  date: string | null;
}

export interface KnowledgeEdge {
  from: string;
  to: string;
  rel: string;
  tier: KnowledgeTier;
  sources: string[];
}

/** The driver and car a session's knowledge is judged for (pitwall.knowledge.context.Context; spec section 2). Every
 * field optional and null = unknown: an unknown trait satisfies no condition. */
export type KnowledgeContext = Partial<Record<ContextKey, string | boolean | null>>;

/** GET /api/technique/knowledge[?session=<id>] */
export interface TechniqueKnowledge {
  valid: boolean;
  errors: string[];
  /** Changes whenever the knowledge does. */
  digest: string;
  files: string[];
  /** Tier -> what it means, in the server's words. */
  tiers: Partial<Record<KnowledgeTier, string>>;
  counts: Record<string, number>;
  phases: KnowledgePhase[];
  conditions: KnowledgeCondition[];
  techniques: KnowledgeTechnique[];
  signals: KnowledgeSignal[];
  faults: KnowledgeFault[];
  causes: KnowledgeCause[];
  advice: KnowledgeAdvice[];
  constraints: KnowledgeConstraint[];
  sources: KnowledgeSource[];
  edges: KnowledgeEdge[];
  /** `?session=` only: the session's Context. */
  context?: KnowledgeContext | null;
  /** `?session=` only: the detected style, as the server reports it (shape not relied on beyond `context`). */
  style?: Record<string, unknown> | null;
}

// ---------------------------------------------------------------------------------------------- transport

/** The server's words for an error body: a string `detail`, or the 503's `{message, errors}`. */
function detailText(body: unknown, fallback: string): string {
  const d = (body as { detail?: unknown } | null)?.detail;
  if (typeof d === "string") return d;
  if (d && typeof d === "object" && typeof (d as { message?: unknown }).message === "string") {
    const errors = (d as { errors?: unknown }).errors;
    const n = Array.isArray(errors) ? errors.length : 0;
    return `${(d as { message: string }).message}${n ? ` (${n} problem${n === 1 ? "" : "s"})` : ""}`;
  }
  return fallback;
}

async function req<T>(path: string): Promise<T> {
  const r = await authFetch(path);
  if (!r.ok) {
    let detail = r.statusText;
    try {
      detail = detailText(await r.json(), detail);
    } catch {
      /* not json */
    }
    throw new ApiError(r.status, detail);
  }
  return r.json() as Promise<T>;
}

export function knowledgePath(sessionId?: string | null): string {
  return `/api/technique/knowledge${sessionId ? `?session=${encodeURIComponent(sessionId)}` : ""}`;
}

/** FastAPI's own 404 / 405: the server predates the knowledge graph. */
export function isMissingKnowledge(e: unknown): boolean {
  return (
    e instanceof ApiError &&
    ((e.status === 404 && e.message === "404: Not Found") || (e.status === 405 && e.message === "405: Method Not Allowed"))
  );
}

export const knowledgeApi = {
  /** The graph; with a session, its variant when the server has one, else the plain graph (see the header). */
  graph: async (sessionId?: string | null): Promise<TechniqueKnowledge> => {
    if (!sessionId) return req<TechniqueKnowledge>(knowledgePath());
    try {
      return await req<TechniqueKnowledge>(knowledgePath(sessionId));
    } catch (e) {
      // An unknown session or a rejected parameter: the plain graph still explains the corner. A missing route or a
      // graph that did not load (503) is the same without the session, so it is reported as it is.
      if (e instanceof ApiError && (e.status === 404 || e.status === 422) && !isMissingKnowledge(e)) {
        return req<TechniqueKnowledge>(knowledgePath());
      }
      throw e;
    }
  },
};

export const knowledgeKeys = {
  /** Plain graph: "technique-knowledge"; a session's variant under "analysis:<id>" (a completed lap refreshes it). */
  graph: (sessionId?: string | null) => (sessionId ? `analysis:${sessionId}:knowledge` : "technique-knowledge"),
} as const;

/** How long a graph stays fresh in the cache: the plain graph only changes with a release. */
export const KNOWLEDGE_MAX_AGE_MS = 10 * 60_000;
