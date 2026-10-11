// Car setup endpoints (lane X, spec 7.3 and 12.4): typed client for /api/carsetup/* (src/pitwall/api/routes_carsetup.py
// and the to_dict shapes in src/pitwall/carsetup/{recommend,compare,context,experiments}.py). Ported from the Svelte
// reference web/src/lib/carsetup.ts; the pure helpers live in src/lib/setup/carsetup.ts.
//
// Rules the UI keeps visible: car formats (F1 25 cars vs 2026 Season Pack cars) are never mixed; wet is never served
// from dry (a missing combination is a 404 whose detail is {reason, alternatives}); every value carries its
// confidence and whether pitwall derived it; a setup is a starting point, never a guaranteed fix (the caveat).
//
// Own request helper (not lib/api.ts, which is frozen) because the 404 detail is an object the page needs intact.
// Requests go through authFetch, so LAN devices with a token in the hash work like every other page.

import type { SessionRow } from "../api";
import { authFetch } from "../auth";

export type CarFormat = "f1_2025" | "f1_2026";
export type SessionKind = "race" | "qualifying";
export type Conditions = "dry" | "wet";
export type SetupStyle = "balanced" | "stable" | "aggressive";
export type Confidence = "high" | "medium" | "low";
export type SkillLevel = "beginner" | "intermediate" | "advanced";
export type SelectionRule = "single_source" | "medoid" | "derived";
export type Direction = "higher" | "lower" | "same" | "unknown";
export type Magnitude = "same" | "small" | "moderate" | "large" | "unknown";
export type NeedField = "car_format" | "session" | "conditions";
export type ExperimentStatus = "proposed" | "running" | "concluded" | "abandoned";
export type Verdict = "faster" | "slower" | "no_clear_difference" | "inconclusive";

export const CAR_FORMATS: readonly CarFormat[] = ["f1_2025", "f1_2026"];
export const SESSION_KINDS: readonly SessionKind[] = ["race", "qualifying"];
export const CONDITIONS: readonly Conditions[] = ["dry", "wet"];
export const STYLES: readonly SetupStyle[] = ["balanced", "stable", "aggressive"];
export const EXPERIMENT_STATUSES: readonly ExperimentStatus[] = ["proposed", "running", "concluded", "abandoned"];

// ---------------------------------------------------------------------------------------------- catalogue
export interface HandlingPatch {
  version: string;
  date: string;
  note: string;
  source: string;
}

export interface FormatInfo {
  id: CarFormat;
  label: string;
  description: string;
  latest_handling_patch: HandlingPatch;
  tracks: { id: number; name: string }[];
  notes: string[];
}

export interface ParamRange {
  min: number;
  max: number;
  step: number;
  /** false: this end is only the bound of the published values seen; the game menu's own limit is unknown */
  min_confirmed: boolean;
  max_confirmed: boolean;
  confidence: Confidence;
  note: string | null;
}

export interface ParameterInfo {
  key: string;
  label: string;
  group: string;
  order: number;
  unit: string | null;
  decimals: number;
  /** What a higher value does, in plain words (catalogue text, shown verbatim). */
  higher: string;
  lower: string;
  sources: string[];
  ranges: Partial<Record<CarFormat, ParamRange>>;
}

export interface SourceInfo {
  id: string;
  name: string;
  url: string;
  kind: string;
  terms_url: string | null;
  terms: string;
  use_policy: "use" | "use_limited" | "do_not_use";
  accessed: string;
  setups: number;
}

export interface RuleInfo {
  id: string;
  description: string;
  sources: string[];
}

/** One catalogue key that has a recommendation (``recommend.available``). */
export interface Combination {
  car_format: CarFormat;
  track_id: number;
  session: SessionKind;
  conditions: Conditions;
  style: SetupStyle;
  derived: boolean;
}

export interface CarSetupCatalog {
  game: string;
  updated: string;
  research_doc: string;
  caveat: string;
  formats: FormatInfo[];
  parameters: ParameterInfo[];
  sources: SourceInfo[];
  rules: RuleInfo[];
  available: Combination[];
}

// ---------------------------------------------------------------------------------------------- recommendation
export interface SetupRow {
  key: string;
  label: string;
  group: string;
  order: number;
  value: number | null;
  /** Menu-formatted, copy-friendly ("-3.50", "24.3"); "unknown" when no source gave the value. */
  display: string;
  unit: string | null;
  min: number | null;
  max: number | null;
  step: number | null;
  confidence: Confidence;
  derived: boolean;
  rule: string | null;
  from_setup: string | null;
  sources: string[];
  patches: string[];
  spread: [number, number] | null;
}

/** Attribution for one cited community setup. */
export interface SetupRef {
  id: string;
  source: string;
  source_name: string;
  url: string;
  author: string | null;
  /** null when the source gives no date */
  published: string | null;
  patch: string | null;
  session: string;
  conditions: string;
  style: string | null;
  input: string | null;
  verified: string;
}

export interface SetupResult {
  id: string;
  car_format: CarFormat;
  track_id: number;
  track_name: string;
  session: SessionKind;
  conditions: Conditions;
  style: SetupStyle;
  requested_session: SessionKind;
  requested_style: SetupStyle;
  style_reason: string;
  selection: SelectionRule;
  groups: string[];
  rows: SetupRow[];
  setups: Record<string, SetupRef>;
  disagreements: string[];
  notes: string[];
  caveat: string;
}

export interface RecommendationResponse extends SetupResult {
  skill_level: SkillLevel | null;
  skill_source: "request" | "driver" | "none";
}

/** Why there is no recommendation, and the catalogue keys that do exist (never silently substituted). */
export interface Unavailable {
  reason: string;
  alternatives: Combination[];
}

// ---------------------------------------------------------------------------------------------- your setup vs recommended
export interface DiffRow {
  key: string;
  label: string;
  group: string;
  order: number;
  unit: string | null;
  yours: number | null;
  yours_display: string;
  recommended: number | null;
  recommended_display: string;
  /** recommended - yours, in the parameter's unit */
  delta: number | null;
  steps: number | null;
  /** which way the recommendation moves the parameter from yours */
  direction: Direction;
  magnitude: Magnitude;
  /** false: beyond a confirmed menu limit of this car format (usually the wrong car format); null: unknown, or only
   * beyond the bounds of published setups (unusual, not impossible) */
  in_range: boolean | null;
  confidence: Confidence;
  derived: boolean;
  explanation: string;
}

export interface SuggestedExperiment {
  key: string;
  label: string;
  from_value: number;
  to_value: number;
  text: string;
}

export interface SetupDiff {
  recommendation_id: string;
  rows: DiffRow[];
  differing: number;
  out_of_range: string[];
  not_compared: string[];
  summary: string;
  experiment: SuggestedExperiment | null;
  caveat: string;
}

export interface SetupContext {
  track_id: number | null;
  track_name: string | null;
  car_format: CarFormat | null;
  car_format_certain: boolean;
  session: SessionKind | null;
  conditions: Conditions | null;
  reasons: Partial<Record<"game" | "track_id" | NeedField, string>>;
  notes: string[];
}

export interface SessionSetupResponse {
  session: {
    id: string;
    game: string | null;
    track_id: string | null;
    track_name: string | null;
    session_type: string | null;
    session_type_raw: string | null;
    car_name: string | null;
    weather: { condition?: string; track_temp_c?: number; air_temp_c?: number };
    synthetic: boolean;
    driver: { id: number; name: string; skill_level: SkillLevel | null } | null;
  };
  context: SetupContext;
  chosen: {
    car_format: CarFormat | null;
    session: SessionKind | null;
    conditions: Conditions | null;
    style: SetupStyle | null;
  };
  needs: NeedField[];
  setup: { t_recv_ns: number | null; fingerprint: string | null; params: Record<string, unknown> } | null;
  recommendation: SetupResult | null;
  unavailable: Unavailable | null;
  diff: SetupDiff | null;
  caveat: string;
}

// ---------------------------------------------------------------------------------------------- experiments
export interface SessionMetrics {
  session_id: string;
  clean_laps: number;
  best_clean_ms: number | null;
  median_clean_ms: number | null;
  stdev_clean_ms: number | null;
  theoretical_best_ms: number | null;
  tyre_compound: string | null;
  /** FL, FR, RL, RR */
  wear_rate_pct_per_lap: number[] | null;
  weather: string | null;
  track_temp_c: number | null;
  setup: Record<string, number>;
}

export interface ExperimentCorner {
  corner: string;
  label: string;
  laps: number;
  mean_time_delta_s: number;
  mean_min_speed_delta_kph: number | null;
  mean_exit_speed_delta_kph: number | null;
}

export interface SetupCheck {
  /** was the experiment's value in the after session's setup (null: no setup received) */
  applied: boolean | null;
  other_changes: { key: string; label: string; before: number; after: number }[];
  note: string | null;
}

export interface ExperimentComparison {
  verdict: Verdict;
  reason: string;
  noise_s: number | null;
  best_delta_s: number | null;
  median_delta_s: number | null;
  theoretical_delta_s: number | null;
  reference_lap_id: number | null;
  corners: ExperimentCorner[];
  setup_check: SetupCheck;
}

export interface SetupExperiment {
  id: number;
  game: string;
  track_id: string | null;
  car_id: string | null;
  created_unix: number;
  hypothesis: string;
  parameter: string;
  from_value: number | null;
  to_value: number | null;
  status: ExperimentStatus;
  before_session_id: string | null;
  after_session_id: string | null;
  before_metrics: SessionMetrics | null;
  after_metrics: (SessionMetrics & { comparison?: ExperimentComparison }) | null;
  conclusion: string | null;
}

/** Session rows from /api/sessions also carry their owner (repo.list_sessions joins the driver) and car id. */
export type SessionOption = SessionRow & { driver_id?: number | null; driver_name?: string | null; car_id?: string | null };

// ---------------------------------------------------------------------------------------------- transport
/** A non-2xx answer. ``detail`` is FastAPI's detail as sent (a string, a validation list or {reason, alternatives}). */
export class CarSetupError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown) {
    super(`${status}: ${detailText(detail, status)}`);
    this.name = "CarSetupError";
    this.status = status;
    this.detail = detail;
  }

  /** The {reason, alternatives} of a "no recommendation for this combination" 404, else null. */
  get unavailable(): Unavailable | null {
    return this.status === 404 ? asUnavailable(this.detail) : null;
  }
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

export function asUnavailable(v: unknown): Unavailable | null {
  if (!isRecord(v) || typeof v.reason !== "string") return null;
  return { reason: v.reason, alternatives: Array.isArray(v.alternatives) ? (v.alternatives as Combination[]) : [] };
}

/** Readable text for a FastAPI error detail: a string, pydantic's [{loc, msg}] list or {reason}. */
export function detailText(detail: unknown, status?: number): string {
  const fallback = status ? `request failed (HTTP ${status})` : "request failed";
  if (typeof detail === "string") return detail.trim() ? detail : fallback;
  if (Array.isArray(detail)) {
    const msgs = detail.map((d) => {
      if (!isRecord(d)) return String(d);
      const loc = Array.isArray(d.loc) ? d.loc.filter((x) => x !== "body").join(".") : "";
      return `${loc ? `${loc}: ` : ""}${typeof d.msg === "string" ? d.msg : JSON.stringify(d)}`;
    });
    return msgs.join("; ") || fallback;
  }
  if (isRecord(detail) && typeof detail.reason === "string") return detail.reason;
  return detail === undefined || detail === null ? fallback : JSON.stringify(detail);
}

/** The message to show inline for any error (without the "404: " prefix for known API errors). */
export function errorText(e: unknown): string {
  if (e instanceof CarSetupError) return detailText(e.detail, e.status);
  return e instanceof Error ? e.message : String(e);
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await authFetch(path, init);
  if (!r.ok) {
    let detail: unknown = r.statusText;
    try {
      const body: unknown = await r.json();
      detail = isRecord(body) && "detail" in body ? body.detail : body;
    } catch {
      /* not json */
    }
    throw new CarSetupError(r.status, detail);
  }
  return r.json() as Promise<T>;
}

const post = <T>(path: string, body?: unknown) =>
  req<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

/** "?a=1&b=x" from the set values (null, undefined and "" left out); "" when nothing is set. */
export function qs(params: Record<string, string | number | null | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
}

export interface RecommendationQuery {
  car_format: CarFormat;
  track_id: number;
  session: SessionKind;
  conditions: Conditions;
  /** omitted = the driver's skill picks it (beginner -> stable) */
  style?: SetupStyle | null;
  driver_id?: number | null;
}

export interface SessionSetupQuery {
  car_format?: CarFormat | null;
  session?: SessionKind | null;
  conditions?: Conditions | null;
  style?: SetupStyle | null;
}

export interface ExperimentFilter {
  session_id?: string | null;
  /** EA track id (the API maps it to "f1:<id>") or a pitwall track id */
  track_id?: string | number | null;
  status?: ExperimentStatus | null;
  limit?: number;
}

export interface ProposeBody {
  before_session_id: string;
  parameter: string;
  to_value: number;
  hypothesis?: string | null;
  car_format?: CarFormat | null;
}

export function recommendationPath(q: RecommendationQuery): string {
  return `/api/carsetup/recommendation${qs({
    car_format: q.car_format,
    track_id: q.track_id,
    session: q.session,
    conditions: q.conditions,
    style: q.style,
    driver_id: q.driver_id,
  })}`;
}

export function sessionSetupPath(sid: string, q: SessionSetupQuery = {}): string {
  return `/api/carsetup/sessions/${encodeURIComponent(sid)}${qs({
    car_format: q.car_format,
    session: q.session,
    conditions: q.conditions,
    style: q.style,
  })}`;
}

export function experimentsPath(f: ExperimentFilter = {}): string {
  return `/api/carsetup/experiments${qs({
    session_id: f.session_id,
    track_id: f.track_id,
    status: f.status,
    limit: f.limit,
  })}`;
}

/** The body the API accepts for a proposal (optional fields only when set). */
export function proposeBody(b: ProposeBody): Record<string, unknown> {
  return {
    before_session_id: b.before_session_id,
    parameter: b.parameter,
    to_value: b.to_value,
    ...(b.hypothesis?.trim() ? { hypothesis: b.hypothesis.trim() } : {}),
    ...(b.car_format ? { car_format: b.car_format } : {}),
  };
}

export const carsetupApi = {
  catalog: () => req<CarSetupCatalog>("/api/carsetup/catalog"),
  recommendation: (q: RecommendationQuery) => req<RecommendationResponse>(recommendationPath(q)),
  session: (sid: string, q: SessionSetupQuery = {}) => req<SessionSetupResponse>(sessionSetupPath(sid, q)),
  /** Recent sessions for the pickers (same rows as GET /api/sessions). */
  sessions: () => req<SessionOption[]>("/api/sessions"),
  experiments: (f: ExperimentFilter = {}) => req<SetupExperiment[]>(experimentsPath(f)),
  experiment: (id: number) => req<SetupExperiment>(`/api/carsetup/experiments/${id}`),
  propose: (b: ProposeBody) => post<SetupExperiment>("/api/carsetup/experiments", proposeBody(b)),
  start: (id: number, afterSessionId: string) =>
    post<SetupExperiment>(`/api/carsetup/experiments/${id}/start`, { after_session_id: afterSessionId }),
  conclude: (id: number) => post<SetupExperiment>(`/api/carsetup/experiments/${id}/conclude`),
  abandon: (id: number, reason?: string | null) =>
    post<SetupExperiment>(`/api/carsetup/experiments/${id}/abandon`, { reason: reason?.trim() ? reason.trim() : null }),
};

// ---------------------------------------------------------------------------------------------- cache keys
/** Request-cache keys (src/lib/cache.ts). Mutations invalidate "carsetup:experiments" and "carsetup:session:". */
export const CARSETUP_KEYS = {
  catalog: "carsetup:catalog",
  recommendation: (q: RecommendationQuery) => `carsetup:rec:${recommendationPath(q)}`,
  session: (sid: string, q: SessionSetupQuery = {}) => `carsetup:session:${sessionSetupPath(sid, q)}`,
  experiments: (f: ExperimentFilter = {}) => `carsetup:experiments:${experimentsPath(f)}`,
  /** Shared with the Review lane: GET /api/sessions holds the same rows under "sessions". */
  sessions: "sessions",
} as const;
