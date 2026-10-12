// Car setup client: types mirroring /api/carsetup (src/pitwall/api/routes_carsetup.py and the to_dict shapes in
// src/pitwall/carsetup/{recommend,compare,context,experiments}.py) plus pure helpers for CarSetupView.
//
// Rules the UI keeps visible: car formats (F1 25 cars vs 2026 Season Pack cars) are never mixed; wet is never
// served from dry (a missing combination is a 404 whose detail is {reason, alternatives}); every value carries its
// confidence and whether pitwall derived it; a setup is a starting point, never a guaranteed fix (the caveat).
// Own fetch helper (like rig.ts) because the 404 detail is an object the view needs intact, not a string.

import { api, type SessionRow } from "./api";

export type CarFormat = "f1_2025" | "f1_2026" | "f2";
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

export const SESSION_KINDS: readonly SessionKind[] = ["race", "qualifying"];
export const CONDITIONS: readonly Conditions[] = ["dry", "wet"];
export const STYLES: readonly SetupStyle[] = ["balanced", "stable", "aggressive"];

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
  /** null for a format without a known handling patch (F2) */
  latest_handling_patch: HandlingPatch | null;
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

function asUnavailable(v: unknown): Unavailable | null {
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

/** The message to show inline for any error (without the "404: " status prefix for known API errors). */
export function errorText(e: unknown): string {
  if (e instanceof CarSetupError) return detailText(e.detail, e.status);
  return e instanceof Error ? e.message : String(e);
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { credentials: "same-origin", ...init });
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

function qs(params: Record<string, string | number | null | undefined>): string {
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

export const carsetup = {
  catalog: () => req<CarSetupCatalog>("/api/carsetup/catalog"),
  recommendation: (q: RecommendationQuery) =>
    req<RecommendationResponse>(
      `/api/carsetup/recommendation${qs({
        car_format: q.car_format,
        track_id: q.track_id,
        session: q.session,
        conditions: q.conditions,
        style: q.style,
        driver_id: q.driver_id,
      })}`,
    ),
  session: (sid: string, q: SessionSetupQuery = {}) =>
    req<SessionSetupResponse>(
      `/api/carsetup/sessions/${encodeURIComponent(sid)}${qs({
        car_format: q.car_format,
        session: q.session,
        conditions: q.conditions,
        style: q.style,
      })}`,
    ),
  /** Recent sessions for the pickers (the existing /api/sessions client). */
  sessions: (): Promise<SessionOption[]> => api.sessions(),
  experiments: (f: { session_id?: string | null; track_id?: string | null; status?: ExperimentStatus | null; limit?: number } = {}) =>
    req<SetupExperiment[]>(`/api/carsetup/experiments${qs(f)}`),
  experiment: (id: number) => req<SetupExperiment>(`/api/carsetup/experiments/${id}`),
  propose: (body: { before_session_id: string; parameter: string; to_value: number; hypothesis?: string | null; car_format?: CarFormat | null }) =>
    post<SetupExperiment>("/api/carsetup/experiments", {
      before_session_id: body.before_session_id,
      parameter: body.parameter,
      to_value: body.to_value,
      ...(body.hypothesis ? { hypothesis: body.hypothesis } : {}),
      ...(body.car_format ? { car_format: body.car_format } : {}),
    }),
  start: (id: number, afterSessionId: string) =>
    post<SetupExperiment>(`/api/carsetup/experiments/${id}/start`, { after_session_id: afterSessionId }),
  conclude: (id: number) => post<SetupExperiment>(`/api/carsetup/experiments/${id}/conclude`),
  abandon: (id: number, reason?: string | null) =>
    post<SetupExperiment>(`/api/carsetup/experiments/${id}/abandon`, { reason: reason?.trim() ? reason.trim() : null }),
};

// ---------------------------------------------------------------------------------------------- labels
export const SESSION_LABEL: Record<SessionKind, string> = { race: "Race", qualifying: "Qualifying" };
export const CONDITIONS_LABEL: Record<Conditions, string> = { dry: "Dry", wet: "Wet" };
export const STYLE_LABEL: Record<SetupStyle, string> = { balanced: "Balanced", stable: "Stable", aggressive: "Aggressive" };
export const SELECTION_LABEL: Record<SelectionRule, string> = {
  single_source: "one published setup",
  medoid: "the most typical of several published setups",
  derived: "derived by pitwall from a published setup",
};
export const STATUS_LABEL: Record<ExperimentStatus, string> = {
  proposed: "Proposed",
  running: "Running",
  concluded: "Concluded",
  abandoned: "Abandoned",
};
export const VERDICT_LABEL: Record<Verdict, string> = {
  faster: "Faster",
  slower: "Slower",
  no_clear_difference: "No clear difference",
  inconclusive: "Inconclusive",
};
export const DIRECTION_ARROW: Record<Direction, string> = { higher: "↑", lower: "↓", same: "=", unknown: "?" };

/** The style pitwall starts a driver on when none is chosen (mirrors ``recommend.default_style``). */
export function defaultStyle(skill: SkillLevel | null | undefined): SetupStyle {
  return skill === "beginner" ? "stable" : "balanced";
}

export function formatLabel(cat: CarSetupCatalog | null, id: CarFormat | null | undefined): string {
  if (!id) return "unknown";
  return cat?.formats.find((f) => f.id === id)?.label ?? id;
}

export function trackLabel(cat: CarSetupCatalog | null, fmt: CarFormat | null, trackId: number): string {
  for (const f of cat?.formats ?? []) {
    if (fmt !== null && f.id !== fmt) continue;
    const t = f.tracks.find((x) => x.id === trackId);
    if (t) return t.name;
  }
  return `track ${trackId}`;
}

// ---------------------------------------------------------------------------------------------- values and copy text
/** "10", "24.3 psi", "unknown": the menu value with its unit, as the driver types it into the game. */
export function valueText(r: { display: string; unit: string | null; value?: number | null }): string {
  if (r.value === null || r.display === "unknown") return "unknown";
  return r.unit ? `${r.display} ${r.unit}` : r.display;
}

/** A number in a parameter's menu format ("-3.50", "24.3 psi"). */
export function paramValue(p: ParameterInfo | undefined, v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "unknown";
  const s = p ? v.toFixed(p.decimals) : String(v);
  return p?.unit ? `${s} ${p.unit}` : s;
}

/** "Front Wing Aero: 10"; a value pitwall derived keeps its mark in the copy (as rig.ts does). */
export function rowCopyLine(r: { label: string; display: string; unit: string | null; value: number | null; derived: boolean }): string {
  return `${r.label}: ${valueText(r)}${r.derived && r.value !== null ? "  [pitwall derived]" : ""}`;
}

/** "+1 step", "−2 steps", "+0.50 steps": how many menu clicks the recommendation is from yours. */
export function stepsText(steps: number): string {
  const whole = Math.abs(steps - Math.round(steps)) < 1e-9;
  const n = Math.abs(steps);
  const sign = steps > 0 ? "+" : steps < 0 ? "−" : "±";
  return `${sign}${whole ? n.toFixed(0) : n.toFixed(2)} ${whole && Math.round(n) === 1 ? "step" : "steps"}`;
}

/** Rows grouped by menu section, sections and rows in the game's menu order. */
export function groupRows<R extends { group: string; order: number }>(rows: R[], groupOrder: string[] = []): { group: string; rows: R[] }[] {
  const sorted = [...rows].sort((a, b) => a.order - b.order);
  const names: string[] = [...groupOrder];
  for (const r of sorted) if (!names.includes(r.group)) names.push(r.group);
  return names
    .map((group) => ({ group, rows: sorted.filter((r) => r.group === group) }))
    .filter((g) => g.rows.length > 0);
}

export function sectionCopyText(group: string, rows: SetupRow[], heading?: string): string {
  const lines = heading ? [heading, group] : [group];
  for (const r of [...rows].sort((a, b) => a.order - b.order)) lines.push(rowCopyLine(r));
  return lines.join("\n");
}

export function setupHeading(res: SetupResult, cat: CarSetupCatalog | null): string {
  return [res.track_name, formatLabel(cat, res.car_format), SESSION_LABEL[res.session], CONDITIONS_LABEL[res.conditions], STYLE_LABEL[res.style]].join(" · ");
}

/** The whole setup as plain text, one "Label: value" line per parameter, sections in menu order. */
export function setupCopyText(res: SetupResult, cat: CarSetupCatalog | null): string {
  const parts = [setupHeading(res, cat)];
  for (const g of groupRows(res.rows, res.groups)) parts.push(sectionCopyText(g.group, g.rows));
  return parts.join("\n\n");
}

// ---------------------------------------------------------------------------------------------- availability
export interface ComboQuery {
  car_format: CarFormat;
  track_id: number;
  session: SessionKind;
  conditions: Conditions;
  style: SetupStyle;
}

/**
 * Which catalogue key ``recommend.recommend`` would serve for a request, in its order: the exact key, balanced for a
 * missing style, then the other session's setup (labelled stand-ins). Never the other conditions or car format:
 * null means there is no recommendation (the API answers 404 with the alternatives).
 */
export function servedAs(av: Combination[], q: ComboQuery): { session: SessionKind; style: SetupStyle } | null {
  const other: SessionKind = q.session === "qualifying" ? "race" : "qualifying";
  const attempts: [SessionKind, SetupStyle][] = [[q.session, q.style]];
  if (q.style !== "balanced") attempts.push([q.session, "balanced"]);
  attempts.push([other, q.style]);
  if (q.style !== "balanced") attempts.push([other, "balanced"]);
  for (const [session, style] of attempts) {
    const hit = av.some(
      (a) =>
        a.car_format === q.car_format &&
        a.track_id === q.track_id &&
        a.conditions === q.conditions &&
        a.session === session &&
        a.style === style,
    );
    if (hit) return { session, style };
  }
  return null;
}

/** A picker option's sub-label: "" when served as asked, what stands in for it, or "no setup". */
export function servedNote(av: Combination[], q: ComboQuery): string {
  const s = servedAs(av, q);
  if (s === null) return "no setup";
  if (s.session !== q.session) return `${SESSION_LABEL[s.session].toLowerCase()} setup shown`;
  if (s.style !== q.style) return `${STYLE_LABEL[s.style].toLowerCase()} shown`;
  return "";
}

export function trackHasSetup(av: Combination[], fmt: CarFormat, trackId: number): boolean {
  return av.some((a) => a.car_format === fmt && a.track_id === trackId);
}

/** Alternatives closest to what was asked first: same format, track, conditions, session, style. */
export function sortAlternatives(
  alts: Combination[],
  want: { car_format?: CarFormat | null; track_id?: number | null; session?: SessionKind | null; conditions?: Conditions | null; style?: SetupStyle | null },
): Combination[] {
  const score = (a: Combination) =>
    (a.car_format === want.car_format ? 16 : 0) +
    (a.track_id === want.track_id ? 8 : 0) +
    (a.conditions === want.conditions ? 4 : 0) +
    (a.session === want.session ? 2 : 0) +
    (a.style === want.style ? 1 : 0);
  return [...alts].sort((a, b) => score(b) - score(a));
}

/** Short label for an alternative, naming only what differs from the current track and car format. */
export function comboLabel(c: Combination, cat: CarSetupCatalog | null, current: { car_format?: CarFormat | null; track_id?: number | null }): string {
  const parts: string[] = [];
  if (current.track_id !== c.track_id) parts.push(trackLabel(cat, c.car_format, c.track_id));
  if (current.car_format !== c.car_format) parts.push(formatLabel(cat, c.car_format));
  parts.push(CONDITIONS_LABEL[c.conditions], SESSION_LABEL[c.session], STYLE_LABEL[c.style]);
  return parts.join(" · ");
}

export function comboKey(c: Combination): string {
  return `${c.car_format}:${c.track_id}:${c.session}:${c.conditions}:${c.style}`;
}

// ---------------------------------------------------------------------------------------------- sessions
/** EA track id from pitwall's "f1:<id>" (null for other games, synthetic tracks and unknown). */
export function f1TrackId(trackId: string | null | undefined): number | null {
  if (!trackId || !trackId.startsWith("f1:")) return null;
  const tail = trackId.slice(3);
  return /^\d+$/.test(tail) ? Number(tail) : null;
}

/** Catalogue session for a stored session type (mirrors ``context.session_kind``; time trial -> qualifying). */
export function sessionKindOf(sessionType: string | null | undefined): SessionKind | null {
  if (sessionType === "race" || sessionType === "practice") return "race";
  if (sessionType === "qualifying" || sessionType === "time_trial") return "qualifying";
  return null;
}

/** Dry/wet from the game's current weather (mirrors ``context.conditions_for``); unknown stays null. */
export function conditionsOf(weather: { condition?: string } | null | undefined): Conditions | null {
  const c = weather?.condition;
  if (c === "light_rain" || c === "heavy_rain" || c === "storm") return "wet";
  if (c === "clear" || c === "light_cloud" || c === "overcast") return "dry";
  return null;
}

export function when(unix: number | null | undefined): string {
  return unix ? new Date(unix * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "";
}

export function sessionTypeLabel(t: string | null | undefined): string {
  return t ? t.replace(/_/g, " ") : "session";
}

export function sessionLabel(s: SessionOption): string {
  const parts = [s.track_name ?? s.track_id ?? "Unknown track", sessionTypeLabel(s.session_type_raw ?? s.session_type), when(s.started_unix)];
  if (s.driver_name) parts.push(s.driver_name);
  if (s.synthetic) parts.push("synthetic");
  return parts.join(" · ");
}

// ---------------------------------------------------------------------------------------------- patches
/**
 * Was a cited setup made before the car format's latest handling patch? Follows ``build.is_current``: a stated game
 * version is compared with the patch version; without one, a full publication date before the patch day is "yes",
 * and a month-only date in the patch's month, or no date at all, is "maybe" (it cannot be told).
 */
export function predatesPatch(s: { patch: string | null; published: string | null }, p: { version: string; date: string } | null | undefined): "yes" | "maybe" | "no" {
  if (!p) return "no";
  if (s.patch) return patchOlder(s.patch, p.version) ? "yes" : "no";
  if (!s.published) return "maybe";
  if (s.published.length >= 10) return s.published.slice(0, 10) < p.date ? "yes" : "no";
  const month = p.date.slice(0, 7);
  return s.published < month ? "yes" : s.published === month ? "maybe" : "no";
}

/** True when game version ``a`` ("1.9") is older than ``b`` ("1.12"); false when either is unknown. */
export function patchOlder(a: string | null | undefined, b: string | null | undefined): boolean {
  if (!a || !b) return false;
  const pa = a.split(".").map(Number);
  const pb = b.split(".").map(Number);
  if (pa.some(Number.isNaN) || pb.some(Number.isNaN)) return false;
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const x = pa[i] ?? 0;
    const y = pb[i] ?? 0;
    if (x !== y) return x < y;
  }
  return false;
}
