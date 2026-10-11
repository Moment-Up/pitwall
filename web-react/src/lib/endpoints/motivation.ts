// Motivation endpoints (lane motivation: goals, streaks and summaries for every driver). Typed client for a driver's
// goals (list, create, archive / reopen, delete, suggestions), badges and streaks, the weekly digest (JSON and the
// printable page) and a session's recap ("Today's 3 things"), plus the `/ws/live` "motivation" note. Server side:
// src/pitwall/api/routes_motivation.py, src/pitwall/motivation/*.
//
// The types below mirror the Python JSON contract exactly (lane spec section 6); changing them needs both builders.
// Every value is computed on the server from the driver's REAL driving (replays never count; synthetic sessions only
// with `synthetic=true`, flagged). Unknown stays unknown: null, never a guess.
//
// Cache keys (lib/cache.ts). Goals, badges and the digest live under "driver-sessions:<id>:" so a completed lap or a
// driver switch refreshes them with the rest of the driver's data (hooks/useApi.ts useCacheInvalidation); a
// successful goal mutation invalidates the driver's goals, badges and digest itself.
//   motivationKeys.goals(id)                GET  /api/drivers/{id}/goals
//   motivationKeys.suggestions(id, q)       GET  /api/drivers/{id}/goals/suggestions?game&track_id&car&from_session_id
//   motivationKeys.badges(id)               GET  /api/drivers/{id}/badges
//   motivationKeys.digest(id, week)         GET  /api/drivers/{id}/digest?week=YYYY-MM-DD
//   motivationKeys.recap(sid)               GET  /api/sessions/{sid}/recap   (Review; under "session:<sid>", so a lap
//                                                                              of the live session refreshes it)
//   motivationKeys.driveRecap(sid, laps, t) the same for Drive's stopped cards (spec 9: refetched per lap / note)

import { ApiError } from "../api";
import { accessToken, authFetch } from "../auth";
import { cache } from "../cache";

// ------------------------------------------------------------------------------------------------- contract (6)

export type GoalKind = "lap_time" | "clean_streak" | "consistency" | "race_clean";
export type GoalStatus = "active" | "achieved" | "archived";
export type RaceRule = "no_penalties" | "no_contact";
export type BasisKind = "ideal_lap" | "recent_gain" | "best_streak" | "best_window" | "race_history";
export interface GoalScope {
  game: string | null;
  track_id: string | null;
  track_name: string | null;
  track_length_m: number | null;
  car_id: string | null;
  car_class: string | null;
  car_label: string | null;
}
export interface GoalParams {
  window_laps?: 3 | 5 | 10;
  rule?: RaceRule;
}
export interface GoalBasis {
  kind: BasisKind;
  text: string;
  text_simple: string;
  values: Record<string, number | string | null>;
  session_ids: string[];
}
export interface GoalProgress {
  baseline: number | null;
  current: number | null;
  target: number;
  fraction: number | null;
  to_go: number | null;
  met: boolean;
  best_session_id: string | null;
  best_lap_id: number | null;
  sessions_since: number;
  text: string;
  text_simple: string;
}
export interface GoalAchievement {
  unix: number;
  session_id: string | null;
  lap_id: number | null;
  lap_number: number | null;
  value: number | null;
  session_owned: boolean;
  text: string;
  text_simple: string;
}
export interface Goal {
  id: number;
  driver_id: number;
  kind: GoalKind;
  status: GoalStatus;
  target: number;
  params: GoalParams;
  scope: GoalScope;
  title: string;
  title_simple: string;
  scope_text: string | null;
  source: "manual" | "suggested";
  basis: GoalBasis | null;
  created_unix: number;
  achieved: GoalAchievement | null;
  progress: GoalProgress;
}
export interface GoalsResponse {
  driver_id: number;
  simple: boolean;
  goals: Goal[];
  limits: { max_active: number; active: number };
}
export interface GoalCreate {
  kind: GoalKind;
  target: number;
  params?: GoalParams;
  game?: string | null;
  track_id?: string | null;
  car_id?: string | null;
  car_class?: string | null;
  from_session_id?: string | null;
  source?: "manual" | "suggested";
  basis?: GoalBasis | null;
}
export interface GoalSuggestion {
  kind: GoalKind;
  target: number;
  params: GoalParams;
  scope: GoalScope;
  title: string;
  title_simple: string;
  scope_text: string | null;
  basis: GoalBasis;
  create: GoalCreate;
}
export interface SuggestionsResponse {
  driver_id: number;
  simple: boolean;
  scope: GoalScope | null;
  suggestions: GoalSuggestion[];
  none_reason: string | null;
}

export type BadgeKind =
  | "first_clean_lap"
  | "under_time"
  | "clean_streak"
  | "ten_clean_session"
  | "pb_streak"
  | "weekly_streak"
  | "busy_week"
  | "clean_race"
  | "goals_reached";
export interface Badge {
  key: string;
  kind: BadgeKind;
  level: number | string | null;
  title: string;
  title_simple: string;
  detail: string | null;
  earned_unix: number;
  session_id: string | null;
  lap_id: number | null;
  scope: GoalScope | null;
  synthetic: boolean;
}
export interface Streaks {
  week_start: string;
  weekly: { current_weeks: number; best_weeks: number; this_week_sessions: number };
  clean_laps: { best: number; best_session_id: string | null; last_session: number | null; last_session_id: string | null };
  pb: { scope: GoalScope; scope_text: string; current_sessions: number; best_sessions: number }[];
}
export interface BadgesResponse {
  driver_id: number;
  simple: boolean;
  include_synthetic: boolean;
  badges: Badge[];
  streaks: Streaks;
}

export type ThingKind = "went_well" | "work_on" | "progress";
export type ThingSource =
  | "pb"
  | "observation"
  | "clean_streak"
  | "in_session_gain"
  | "all_clean"
  | "lap_hygiene"
  | "no_clean_lap"
  | "single_clean_lap"
  | "goal_reached"
  | "pb_streak"
  | "goal_progress"
  | "gap_to_pb"
  | "first_session"
  | "sessions_week";
export interface ThingItem {
  kind: ThingKind;
  source: ThingSource;
  text: string;
  text_simple: string;
  evidence: string | null;
  corner: string | null;
  corner_label: string | null;
  lap_id: number | null;
  lap_number: number | null;
  observation_kind: string | null;
  /** `${corner}:${kind}` */
  observation_key: string | null;
  goal_id: number | null;
  values: Record<string, number | string | null>;
}
export interface SessionRecap {
  session_id: string;
  driver_id: number | null;
  driver_name: string | null;
  simple: boolean;
  synthetic: boolean;
  replay: boolean;
  ended: boolean;
  laps: number;
  clean_laps: number;
  things: { went_well: ThingItem | null; work_on: ThingItem | null; progress: ThingItem | null };
  why_empty: { went_well: string | null; work_on: string | null; progress: string | null };
  goals_achieved: Goal[];
  goals_progress: Goal[];
  badges_earned: Badge[];
}

export interface DigestSession {
  session_id: string;
  started_unix: number;
  game: string;
  track_name: string | null;
  car_name: string | null;
  session_type: string | null;
  laps: number;
  clean_laps: number;
  best_clean_ms: number | null;
  pb: boolean;
  synthetic: boolean;
}
export interface DigestImprovement {
  scope: GoalScope;
  scope_text: string;
  before_ms: number | null;
  best_ms: number;
  gain_ms: number | null;
  new_track: boolean;
  session_id: string;
  lap_id: number;
}
export interface WeeklyDigest {
  driver: { id: number; name: string; skill_level: string };
  simple: boolean;
  week_start: string;
  week_end: string;
  is_current_week: boolean;
  generated_unix: number;
  include_synthetic: boolean;
  totals: { sessions: number; laps: number; clean_laps: number; lap_time_s: number; tracks: number };
  previous_week: { sessions: number; laps: number; clean_laps: number };
  headline: string;
  headline_simple: string;
  sessions: DigestSession[];
  improvements: DigestImprovement[];
  goals: { achieved: Goal[]; active: { goal: Goal; from_fraction: number | null; to_fraction: number | null }[] };
  badges: Badge[];
  streaks: Streaks;
  markdown: string;
}
export interface MotivationNote {
  kind: "goals_achieved";
  session_id: string;
  driver_id: number;
  lap_id: number | null;
  lap_number: number | null;
  t: number;
  goals: {
    id: number;
    kind: GoalKind;
    title: string;
    title_simple: string;
    scope_text: string | null;
    track_name: string | null;
    target: number;
    params: GoalParams;
    value: number | null;
  }[];
}

// ------------------------------------------------------------------------------------------------- client

/** An API error with the server's machine code (409 `{detail, code}`: "already_beaten", "too_many", "duplicate",
 * "duplicate_scope"). `detail` is the server's sentence, shown verbatim; FastAPI's 422 validation list becomes one
 * sentence. */
export class MotivationError extends ApiError {
  readonly code: string | null;
  readonly detail: string;
  constructor(status: number, detail: string, code: string | null) {
    super(status, detail);
    this.name = "MotivationError";
    this.code = code;
    this.detail = detail;
  }
}

/** FastAPI's 422 body (`detail: [{loc, msg, type}]`) as one sentence; a string detail as it is. */
export function detailText(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (d && typeof d === "object" && typeof (d as { msg?: unknown }).msg === "string" ? (d as { msg: string }).msg : null))
      .filter((m): m is string => !!m);
    if (msgs.length) return msgs.join("; ");
  }
  return fallback;
}

async function send<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await authFetch(path, init);
  if (!r.ok) {
    let detail = r.statusText;
    let code: string | null = null;
    try {
      const body = (await r.json()) as { detail?: unknown; code?: unknown };
      detail = detailText(body.detail, detail);
      if (typeof body.code === "string") code = body.code;
    } catch {
      /* not json */
    }
    throw new MotivationError(r.status, detail, code);
  }
  return r.json() as Promise<T>;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

const enc = encodeURIComponent;

/** What a suggestions request covers: the ScopeBar's game + track + car, or a session's scope. */
export interface SuggestionsQuery {
  game?: string | null;
  track_id?: string | null;
  car?: string | null;
  from_session_id?: string | null;
}

function qs(p: Record<string, string | number | boolean | null | undefined>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(p)) if (v != null && v !== "" && v !== false) u.set(k, String(v));
  const s = u.toString();
  return s ? `?${s}` : "";
}

export const motivationKeys = {
  goals: (driverId: number) => `driver-sessions:${driverId}:goals`,
  suggestions: (driverId: number, q: SuggestionsQuery) =>
    `driver-sessions:${driverId}:goals:suggestions:${q.game ?? ""}|${q.track_id ?? ""}|${q.car ?? ""}|${q.from_session_id ?? ""}`,
  badges: (driverId: number, synthetic = false) => `driver-sessions:${driverId}:badges${synthetic ? ":syn" : ""}`,
  /** `week` null = this week (the server's default). */
  digest: (driverId: number, week: string | null) => `driver-sessions:${driverId}:digest:${week ?? "current"}`,
  recap: (sessionId: string) => `session:${sessionId}:recap`,
  driveRecap: (sessionId: string, laps: number, noteT: number | null) => `motivation:recap:${sessionId}:${laps}:${noteT ?? ""}`,
} as const;

/** Paths, for links and the printable page. */
export const motivationPaths = {
  goals: (driverId: number) => `/api/drivers/${driverId}/goals`,
  goal: (driverId: number, goalId: number) => `/api/drivers/${driverId}/goals/${goalId}`,
  suggestions: (driverId: number, q: SuggestionsQuery = {}) =>
    `/api/drivers/${driverId}/goals/suggestions${qs({ game: q.game, track_id: q.track_id, car: q.car, from_session_id: q.from_session_id })}`,
  badges: (driverId: number, synthetic = false) => `/api/drivers/${driverId}/badges${qs({ synthetic })}`,
  digest: (driverId: number, week: string | null = null, synthetic = false) =>
    `/api/drivers/${driverId}/digest${qs({ week, synthetic })}`,
  /** The printable page (text/html, served by the backend; the cookie or Tailscale identity authenticates it). */
  digestHtml: (driverId: number, week: string | null = null) => `/api/drivers/${driverId}/digest.html${qs({ week })}`,
  /** The printable page for a new tab. A new tab sends only the cookie, so a device whose access token is in the
   * page link's hash (`#/…?token=`, no cookie) passes it as `?token=` (the server then sets its cookie, as for the
   * login link); otherwise the plain path. */
  digestHtmlTab: (driverId: number, week: string | null = null) => {
    const token = accessToken();
    return `/api/drivers/${driverId}/digest.html${qs({ week, token })}`;
  },
  recap: (sessionId: string) => `/api/sessions/${enc(sessionId)}/recap`,
};

/** After a goal is created, changed or deleted: the driver's goals (and suggestions), badges, digest and recaps. */
export function invalidateGoals(driverId: number): void {
  cache.invalidate(`driver-sessions:${driverId}:goals`);
  cache.invalidate(`driver-sessions:${driverId}:badges`);
  cache.invalidate(`driver-sessions:${driverId}:digest`);
  cache.invalidate("motivation:");
}

export const motivationApi = {
  /** Active goals and those reached in the last 30 days (the server's default). */
  goals: (driverId: number) => send<GoalsResponse>(motivationPaths.goals(driverId)),
  createGoal: async (driverId: number, body: GoalCreate) => {
    const g = await send<Goal>(motivationPaths.goals(driverId), json("POST", body));
    invalidateGoals(driverId);
    return g;
  },
  /** Archive (`archived`), or back to `active` (from achieved this reopens it and clears the achievement). */
  setStatus: async (driverId: number, goalId: number, status: "active" | "archived") => {
    const g = await send<Goal>(motivationPaths.goal(driverId, goalId), json("PATCH", { status }));
    invalidateGoals(driverId);
    return g;
  },
  deleteGoal: async (driverId: number, goalId: number) => {
    const r = await send<{ deleted: number }>(motivationPaths.goal(driverId, goalId), { method: "DELETE" });
    invalidateGoals(driverId);
    return r;
  },
  suggestions: (driverId: number, q: SuggestionsQuery = {}) => send<SuggestionsResponse>(motivationPaths.suggestions(driverId, q)),
  badges: (driverId: number, synthetic = false) => send<BadgesResponse>(motivationPaths.badges(driverId, synthetic)),
  digest: (driverId: number, week: string | null = null, synthetic = false) =>
    send<WeeklyDigest>(motivationPaths.digest(driverId, week, synthetic)),
  recap: (sessionId: string) => send<SessionRecap>(motivationPaths.recap(sessionId)),
};
