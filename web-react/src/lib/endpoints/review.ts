// Review endpoints (lane R, spec 6 and 12.4): typed client for the session list, one session, its analysis, report
// and events, lap traces, lap comparison, reference pinning, session ownership, a driver's sessions and progress
// (D5), and the race engineer. Behaviour reference: web/src/views/{SessionsView,SessionView,EngineerView}.svelte.
// Server side: src/pitwall/api/app.py (sessions, laps, compare, engineer) and api/routes_drivers.py (ownership,
// driver sessions, progress).
//
// Cache keys (lib/cache.ts; the app invalidates "sessions", "driver-sessions:", "session:<live id>" and
// "analysis:<live id>" on every completed lap and on a driver switch, see hooks/useApi.ts):
//   reviewKeys.sessions               GET /api/sessions?limit=200               (everyone; "sessions:list", not the
//                                     shell's "sessions" key, which holds the default 50-row window)
//   reviewKeys.driverSessions(id)     GET /api/drivers/{id}/sessions?limit=…    (one driver; server-side filter)
//   reviewKeys.session(id)            GET /api/sessions/{id}                    (row + laps + setup + skeleton)
//   reviewKeys.analysis(id)           GET /api/sessions/{id}/analysis           (reference, corners, observations)
//   reviewKeys.report(id)             GET /api/sessions/{id}/report             (markdown)
//   reviewKeys.summary(id)            POST /api/engineer/ask (a summary answer, stored with cache.set)
//   reviewKeys.analysisRef(id, lap)   GET /api/sessions/{id}/analysis?ref_lap_id=… (Laps: another reference; the
//                                     "analysis:<id>" prefix keeps it inside the live invalidation)
//   reviewKeys.trace(lapId)           GET /api/laps/{id}/trace?step=5         (a stored lap never changes)
//   reviewKeys.compare(ref, lap)      GET /api/compare?ref=&lap=               (Compare)
//   reviewKeys.history(id)            GET /api/engineer/history?session_id=    (Ask)
//   reviewKeys.progress(id, q)        GET /api/drivers/{id}/progress?…         (D5: Progress, Coaching plan; under
//                                     "driver-sessions:" so laps and driver switches refresh it)
//   reviewKeys.familyProgress(ids, q) the same for every family driver, corners=false (family board)
//   reviewKeys.aiPace(id, q)          GET /api/drivers/{id}/ai-pace?…          (pace vs AI difficulty: Progress
//                                     "Against the AI", Coaching "Suggested AI difficulty"; under "driver-sessions:")
//
// `api.ts` stays frozen (lane S); the response types Review needs beyond it live here. Fields that a backend
// addition brings are optional (`clean_lap_count` is D5, `text_simple` / `short` are D6): unknown stays unknown.

import type {
  Comparison,
  Corner,
  CornerDelta,
  EngineerAnswer,
  LapRow,
  LapTrace,
  Observation,
  SessionRow,
  TrackModel,
} from "../api";
import { ApiError } from "../api";
import { authFetch } from "../auth";
import type { CarFamily, SessionCarFields } from "../carclass";
import { cache } from "../cache";
import { drivers, type AssignResult } from "../drivers";

/** How many sessions a list asks for (the server's default window is 50; a family's month fits in 200). */
export const SESSION_LIST_LIMIT = 200;

/** A session list row: `repo.list_sessions` (driver joined in) plus what D5 adds, and (F2 support) the car class, the
 * car and the session in words (`car_class`, `car_label`, `session_label`: lib/carclass.ts). */
export interface SessionListRow extends SessionRow, SessionCarFields {
  driver_id: number | null;
  driver_name: string | null;
  car_id?: string | null;
  ended_unix?: number | null;
  /** D5: clean laps in the session. Absent before D5 (rows then read "12 laps"). */
  clean_lap_count?: number | null;
  info?: Record<string, unknown> | null;
  /** AI pace: the game's AI difficulty for the session (F1 Session.aiDifficulty, 0-110). Null = not reported (or a
   * game without AI difficulty); absent on a server without AI pace. */
  ai_difficulty?: number | null;
}

/** GET /api/sessions/{id}: the row, its laps (lap number order), the latest setup and the game-native skeleton. */
export interface SessionDetail extends SessionListRow {
  laps: LapRow[];
  setup: unknown;
  skeleton?: unknown;
  /** AI pace for this session; null = not applicable or not recorded (a non-F1 session, one from before the
   * feature); absent on a server without AI pace. */
  ai_pace?: SessionAiPace | null;
}

// ---------------------------------------------------------------------------------------------------- AI pace
// Pace vs AI difficulty (contract frozen in the AI pace design spec, section 6). Only the game's own telemetry: the
// AI cars' lap times from F1's Session History, the difficulty from the Session packet. Unknown stays unknown: a
// status other than "ok" carries null metrics, never an estimate. Synthetic sessions get a row (flagged by the
// session) but never feed a driver's series or suggestions (the server filters them out).

export type AiPaceStatus = "ok" | "no_driver_lap" | "too_few_ai_cars" | "unknown_difficulty" | "difficulty_changed" | "time_trial";
export type SessionCategory = "race" | "qualifying" | "practice" | "time_trial" | "unknown";
export type WeatherClass = "dry" | "wet" | "mixed";
export type AiExclusion =
  | "race_lap_1"
  | "not_observed"
  | "not_ai_driven"
  | "results_skip"
  | "invalid"
  | "pit_in_out"
  | "safety_car"
  | "red_flag"
  | "flashback"
  | "timing_inconsistent"
  | "fast_outlier"
  | "slow_car";

/** One session against the AI (`session_ai_pace`). Gaps are the driver minus the AI: negative = the driver faster. */
export interface SessionAiPace {
  status: AiPaceStatus;
  method_version: number;
  updated_unix: number;
  ai_difficulty: number | null;
  car_class: string | null;
  weather_class: WeatherClass | null;
  online: boolean | null;
  ai_cars: number;
  ai_laps: number;
  /** The typical AI car: the median of the AI cars' best representative laps. */
  ai_ref_ms: number | null;
  ai_best_ms: number | null;
  ai_p25_ms: number | null;
  ai_p75_ms: number | null;
  /** Races only. */
  ai_median_lap_ms: number | null;
  /** Sorted, one per AI car (no identities). */
  ai_bests_ms: number[];
  driver_best_ms: number | null;
  driver_best_lap_id: number | null;
  driver_median_ms: number | null;
  driver_clean_laps: number;
  /** driver_best - ai_ref; negative = driver faster. */
  gap_ms: number | null;
  gap_pct: number | null;
  gap_to_best_ai_ms: number | null;
  race_pace_gap_pct: number | null;
  field_rank: number | null;
  field_size: number | null;
  excluded: Partial<Record<AiExclusion, number>>;
}

/** One session of a driver's series against the AI (real driving only: never synthetic, never a replay). */
export interface AiPacePoint {
  session_id: string;
  started_unix: number;
  game: string;
  track_id: string;
  track_name: string | null;
  car_id: string | null;
  car_name: string | null;
  car_class: string | null;
  session_category: SessionCategory;
  weather_class: WeatherClass | null;
  online: boolean | null;
  status: "ok" | "no_driver_lap";
  ai_difficulty: number;
  ai_ref_ms: number;
  ai_best_ms: number;
  ai_cars: number;
  driver_best_ms: number | null;
  gap_ms: number | null;
  gap_pct: number | null;
  field_rank: number | null;
  field_size: number | null;
}

export interface AiLevelKey {
  game: string;
  track_id: string;
  track_name: string | null;
  car_class: string | null;
  session_category: SessionCategory;
  weather_class: WeatherClass | null;
}

/** A suggested AI level for one key. `text` is the server's deterministic sentence to the driver ("your": the engineer
 * and the radio say it); every number in it is a field. A page that may show another driver builds its own sentence
 * from the fields (lib/review/aipace.ts suggestionSentence). */
export interface AiLevelSuggestion {
  key: AiLevelKey;
  basis: "measured" | "estimate_other_tracks" | "direction_only";
  level: number | null;
  /** Null for a bound ("or higher" / "or lower": a range around the limit would contradict it) and without a level. */
  range: [number, number] | null;
  bound: "at_least" | "at_most" | null;
  confidence: "high" | "medium" | "low" | null;
  /** Against `latest_level`. */
  direction: "higher" | "lower" | "about_right" | null;
  note: "levels_disagree" | null;
  latest_level: number;
  latest_gap_pct: number | null;
  /** The newest session's gap in ms (absent on servers before method 2). */
  latest_gap_ms?: number | null;
  /** direction_only: the level to race here next so a level can be measured (MIN_SPAN away); absent before method 2. */
  next_level?: number | null;
  target_gap_pct: number;
  sessions_used: number;
  levels_used: number[];
  slope_pct_per_level: number | null;
  slope_sources: string[];
  text: string;
}

/** `GET /api/drivers/{id}/ai-pace`. Suggestions use all of the driver's points (other tracks' slopes); the scope
 * filters `points` and which keys are returned. */
export interface DriverAiPace {
  driver_id: number;
  method_version: number;
  target_gap_pct: number;
  scope: { game: string | null; track_id: string | null; car_class: string | null; category: SessionCategory | null };
  /** Oldest first. */
  points: AiPacePoint[];
  /** One per key present in points, newest first. */
  suggestions: AiLevelSuggestion[];
  /** Sessions in scope raced against the AI that could not be compared (absent on servers before method 2). */
  unusable?: AiPaceUnusable[];
}

/** A session raced against the AI without a comparison: too few AI laps, the AI difficulty unknown or changed. */
export interface AiPaceUnusable {
  session_id: string;
  started_unix: number;
  session_category: SessionCategory;
  ai_difficulty: number | null;
  status: Exclude<AiPaceStatus, "ok" | "no_driver_lap" | "time_trial">;
  online: boolean | null;
  ai_cars: number;
}

/** The live snapshot's `ai_pace` (small, in every snapshot, like `bests`). */
export interface LiveAiPace {
  session_id: string;
  status: AiPaceStatus;
  synthetic: boolean;
  ai_difficulty: number | null;
  ai_cars: number;
  ai_ref_ms: number | null;
  driver_best_ms: number | null;
  gap_ms: number | null;
  gap_pct: number | null;
  field_rank: number | null;
  field_size: number | null;
}

/** What an AI pace request covers (all optional; `limit` default 200, `target_gap_pct` default 0, -5..5). */
export interface AiPaceQuery {
  game?: string | null;
  track_id?: string | null;
  car_class?: string | null;
  category?: SessionCategory | null;
  limit?: number;
  target_gap_pct?: number;
}

/** Default AI pace window and target (the server's defaults). */
export const AI_PACE_LIMIT = 200;
export const AI_TARGET_GAP_PCT = 0;

function aiPaceScopeKey(q: AiPaceQuery): string {
  return `${q.game ?? ""}|${q.track_id ?? ""}|${q.car_class ?? ""}|${q.category ?? ""}|${q.limit ?? AI_PACE_LIMIT}|${q.target_gap_pct ?? AI_TARGET_GAP_PCT}`;
}

/** A learned corner with its official identity (analysis/track_identity.py via track_model_payload). */
export interface ReviewCorner extends Corner {
  /** Official short label ("T15", "T10-13"); null when the track sheet does not map this corner. */
  label?: string | null;
  /** Official name ("Stowe"), when the sheet has one. */
  display_name?: string | null;
  official_numbers?: number[];
  identity_tier?: string | null;
  voice_ok?: boolean;
}

export interface ReviewTrackModel extends Omit<TrackModel, "corners"> {
  corners: ReviewCorner[];
  source_lap_ids?: number[];
  /** F2 support: the family of the laps the model was built from (null = a model from before families). */
  car_family?: CarFamily | null;
  /** F2 support: false when another family's model stands in for this session's class; null for non-F1 games. */
  car_family_match?: boolean | null;
}

/** A coaching observation as the analysis sends it (Observation.to_dict). D6 adds `text_simple` and `short`. */
export interface ReviewObservation extends Observation {
  metric?: string;
  consistency_ratio?: number | null;
  corner_label?: string | null;
  corner_voice?: string | null;
  text_simple?: string | null;
  short?: string | null;
  evidence?: ObservationEvidence;
}

/** The deltas an observation was derived from (coaching._evidence): lap minus reference. */
export interface ObservationEvidence {
  time_delta_s?: number | null;
  brake_point_delta_m?: number | null;
  min_speed_delta_kph?: number | null;
  exit_speed_delta_kph?: number | null;
  entry_speed_delta_kph?: number | null;
  throttle_full_delta_m?: number | null;
  coast_delta_m?: number | null;
  [key: string]: unknown;
}

/** One corner averaged over the session's compared laps (core/session_analysis.CornerSummary). Lap minus
 * reference: a positive time is time lost; a negative brake point is braking earlier; a negative speed is slower. */
export interface CornerSummaryRow {
  corner: string;
  direction: string | null;
  apex_m: number;
  laps: number;
  mean_time_delta_s: number | null;
  median_time_delta_s: number | null;
  mean_brake_point_delta_m: number | null;
  brake_point_std_m: number | null;
  min_speed_std_kph: number | null;
  mean_min_speed_delta_kph: number | null;
  mean_exit_speed_delta_kph: number | null;
  ref_brake_start_m: number | null;
  ref_min_speed_kph: number | null;
  ref_exit_speed_kph: number | null;
}

/** The reference lap (it may belong to another session of the same track and car). */
export interface RefLap extends LapRow {
  session_id: string;
}

export interface LapComparisonSummary {
  cmp_lap_number: number;
  total_delta_s: number | null;
  compatibility: { ok: boolean; blocking: string[]; warnings: string[] };
  corners: Partial<Comparison["corners"][number]>[];
}

/** GET /api/sessions/{id}/analysis. `observations` and `comparisons` are keyed by lap id (as a string). */
export interface SessionAnalysis {
  session_id: string;
  ref_lap_id: number | null;
  ref_lap: RefLap | null;
  track_model: ReviewTrackModel | null;
  corner_summary: CornerSummaryRow[];
  observations: Record<string, ReviewObservation[]>;
  comparisons: Record<string, LapComparisonSummary>;
}

export interface SessionReport {
  markdown: string;
  [key: string]: unknown;
}

export interface SessionEvent {
  id: number;
  session_id: string;
  t_recv_ns: number;
  session_time_s: number | null;
  kind: string;
  code: string | null;
  payload: Record<string, unknown> | null;
}

export interface EngineerFact {
  id: string;
  topic: string;
  text: string;
  data?: Record<string, unknown> | null;
  corner?: string | null;
}

/** One stored message of the engineer conversation (GET /api/engineer/history, table `conversations`). */
export interface EngineerHistoryRow {
  id: number;
  session_id: string | null;
  created_unix: number;
  role: "user" | "engineer" | string;
  text: string;
  intent: string | null;
  facts: { id: string; topic: string; text: string }[] | null;
  /** The LLM that wrote the answer; null for deterministic answers and the questions. */
  model: string | null;
  latency_ms: number | null;
  /** 1 / 0 / null (SQLite). */
  grounded: number | boolean | null;
  fallback: number | boolean;
}

/** One corner's measurements on one lap (analysis/compare.py CornerMetrics), game lap metres. */
export interface CornerMetrics {
  corner: string;
  segment_time_s: number | null;
  brake_start_m?: number | null;
  brake_end_m?: number | null;
  brake_peak?: number | null;
  entry_speed_kph?: number | null;
  min_speed_kph?: number | null;
  min_speed_m?: number | null;
  exit_speed_kph?: number | null;
  throttle_pickup_m?: number | null;
  throttle_full_m?: number | null;
  [key: string]: unknown;
}

/** A corner of a comparison (analysis/compare.py CornerDelta): lap minus reference, plus both laps' metrics. */
export interface ReviewCornerDelta extends CornerDelta {
  brake_release_delta_m?: number | null;
  min_speed_pos_delta_m?: number | null;
  throttle_pickup_delta_m?: number | null;
  release_time_delta_s?: number | null;
  ref?: CornerMetrics | null;
  cmp?: CornerMetrics | null;
}

export interface ReviewComparison extends Omit<Comparison, "corners"> {
  corners: ReviewCornerDelta[];
}

/** GET /api/compare: the comparison, the coach's observations for the compared lap, and the identified track
 * model. */
export interface CompareResponse {
  comparison: ReviewComparison;
  observations: ReviewObservation[];
  track_model: ReviewTrackModel | null;
}

/** D5: one session of a driver's progress (oldest first in `DriverProgress.sessions`). Lap statistics count clean
 * laps only; `corners` / `habits` come from the session analysis against the driver's CURRENT reference at that track
 * (so sessions are compared with the same lap) and are null when the session could not be compared, when corners
 * were not asked for, or for sessions older than the newest 30. Corner keys are learned names. */
export interface ProgressSession {
  session_id: string;
  started_unix: number;
  game: string;
  track_id: string | null;
  track_name: string | null;
  car_id: string | null;
  car_name: string | null;
  session_type: string | null;
  synthetic: boolean;
  /** Every stored lap. */
  laps: number;
  clean_laps: number;
  best_clean_ms: number | null;
  median_clean_ms: number | null;
  /** Slowest minus fastest clean lap; needs two clean laps. */
  spread_ms: number | null;
  ref_lap_id: number | null;
  /** Learned corner -> mean time lost against the reference, seconds (negative = gained). */
  corners: Record<string, number> | null;
  /** Corrective rule kind -> times it fired over the session's laps. */
  habits: Record<string, number> | null;
}

/** D5: a clean lap that beat the driver's earlier best for its game + track + car (the first lap at a track is one,
 * with `previous_ms` null). In the order driven. */
export interface PbHistoryEntry {
  game: string;
  track_id: string;
  track_name: string | null;
  car_id: string | null;
  car_name: string | null;
  lap_id: number;
  session_id: string;
  lap_number: number;
  lap_ms: number;
  set_unix: number;
  previous_ms: number | null;
  gain_ms: number | null;
  synthetic: boolean;
}

/** `corner_text["<game>/<track_id>"][learned corner]`: the official short label ("T15", "T10-13 (1)", "115 m") and
 * the long text ("Turn 15 (Stowe)"), written by the server (analysis/track_identity.py). */
export type ProgressCornerText = Record<string, Record<string, { short: string; long: string }>>;

/** D5 `GET /api/drivers/{id}/progress?game&track_id&car&synthetic&limit&corners`. Never replays; synthetic sessions
 * only with `synthetic=true` (each row flagged). */
export interface DriverProgress {
  driver_id: number;
  scope: { game: string | null; track_id: string | null; car_id: string | null };
  include_synthetic: boolean;
  sessions: ProgressSession[];
  corner_text: ProgressCornerText;
  pb_history: PbHistoryEntry[];
}

/** What a progress request covers. `car` null = any car. */
export interface ProgressQuery {
  game?: string | null;
  track_id?: string | null;
  car?: string | null;
  /** Include synthetic sessions (flagged). Default false. */
  synthetic?: boolean;
  /** Corner trends and habits (a session analysis each; the family board does not need them). Default true. */
  corners?: boolean;
  limit?: number;
}

function progressScopeKey(q: ProgressQuery): string {
  return `${q.game ?? ""}|${q.track_id ?? ""}|${q.car ?? ""}|${q.synthetic ? 1 : 0}|${q.corners === false ? 0 : 1}`;
}

export const reviewKeys = {
  sessions: "sessions:list",
  driverSessions: (driverId: number) => `driver-sessions:${driverId}`,
  session: (id: string) => `session:${id}`,
  analysis: (id: string) => `analysis:${id}`,
  /** The analysis against another reference lap (Laps "Set as reference"); same prefix as `analysis`. */
  analysisRef: (id: string, refLapId: number | null | undefined) =>
    refLapId == null ? `analysis:${id}` : `analysis:${id}:ref:${refLapId}`,
  trace: (lapId: number) => `trace:${lapId}`,
  compare: (ref: number, lap: number) => `compare:${ref}:${lap}`,
  history: (sessionId: string | null) => `engineer-history:${sessionId ?? "latest"}`,
  report: (id: string) => `report:${id}`,
  events: (id: string) => `events:${id}`,
  summary: (id: string) => `engineer-summary:${id}`,
  /** The list a filter shows: everyone, or one driver's sessions. */
  list: (driverId: number | "all") => (driverId === "all" ? "sessions:list" : `driver-sessions:${driverId}`),
  /** D5 for one driver and scope. Under "driver-sessions:" so a completed lap or a driver switch refreshes it. */
  progress: (driverId: number, q: ProgressQuery) => `driver-sessions:${driverId}:progress:${progressScopeKey(q)}`,
  /** D5 for every family driver at one scope (the family board). Same prefix rule. */
  familyProgress: (driverIds: readonly number[], q: ProgressQuery) =>
    `driver-sessions:family:${driverIds.join(",")}:progress:${progressScopeKey(q)}`,
  /** A driver's pace against the AI and the suggested level (Progress, Coaching plan). Under "driver-sessions:" so a
   * completed lap or a driver switch refreshes it. */
  aiPace: (driverId: number, q: AiPaceQuery) => `driver-sessions:${driverId}:ai-pace:${aiPaceScopeKey(q)}`,
} as const;

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await authFetch(path, init);
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const body = (await r.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* not json */
    }
    throw new ApiError(r.status, detail);
  }
  return r.json() as Promise<T>;
}

const post = <T>(path: string, body: unknown) =>
  req<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

const enc = encodeURIComponent;

/** The question the Summary's optional engineer block asks (the engineer's "summary" intent). */
export const SUMMARY_QUESTION = "Give me a summary of this session.";

export const reviewApi = {
  /** Everyone's sessions, newest first. */
  sessions: (limit = SESSION_LIST_LIMIT) => req<SessionListRow[]>(`/api/sessions?limit=${limit}`),
  /** One driver's sessions, newest first (server-side, so older sessions are not cut off by the window). */
  driverSessions: (driverId: number, limit = SESSION_LIST_LIMIT) =>
    req<SessionListRow[]>(`/api/drivers/${driverId}/sessions?limit=${limit}`),
  /** The list a filter shows. */
  list: (driverId: number | "all") =>
    driverId === "all" ? reviewApi.sessions() : reviewApi.driverSessions(driverId),
  session: (id: string) => req<SessionDetail>(`/api/sessions/${enc(id)}`),
  analysis: (id: string, refLapId?: number | null) =>
    req<SessionAnalysis>(`/api/sessions/${enc(id)}/analysis${refLapId != null ? `?ref_lap_id=${refLapId}` : ""}`),
  report: (id: string) => req<SessionReport>(`/api/sessions/${enc(id)}/report`),
  events: (id: string) => req<SessionEvent[]>(`/api/sessions/${enc(id)}/events`),
  trace: (lapId: number, step = 5) => req<LapTrace>(`/api/laps/${lapId}/trace?step=${step}`),
  compare: (ref: number, lap: number) => req<CompareResponse>(`/api/compare?ref=${ref}&lap=${lap}`),
  /** Pin a lap as the reference for its track and car. */
  pinReference: async (lapId: number, label?: string) => {
    const r = await post<{ reference_id: number; lap_id: number }>("/api/references", { lap_id: lapId, label });
    cache.invalidate("analysis:");
    return r;
  },
  /**
   * Move a session to another driver ("forgot to switch"). Re-assigning the live session also puts that driver in
   * the seat (the server does both atomically). Goes through the drivers store so the profiles' stats refresh too.
   */
  assignSession: async (sessionId: string, driverId: number): Promise<AssignResult> => {
    const r = await drivers.assignSession(sessionId, driverId);
    invalidateSessionLists(sessionId);
    return r;
  },
  /** D5: per-session progress at a track (+ car) and the PB history. A server without D5 answers 404 (see
   * `isMissingRoute`): Progress then falls back to lap-level data. */
  progress: (driverId: number, q: ProgressQuery = {}) => req<DriverProgress>(progressUrl(driverId, q)),
  /** D5 for several drivers at one scope (the family board): every driver's answer, or the first error. */
  familyProgress: (driverIds: readonly number[], q: ProgressQuery) =>
    Promise.all(driverIds.map(async (id) => [id, await reviewApi.progress(id, q)] as const)).then(
      (pairs) => new Map<number, DriverProgress>(pairs),
    ),
  /** A driver's sessions against the AI and the suggested AI level per key. A server without AI pace answers 404
   * (`isMissingRoute`): the pages then leave the AI cards out. */
  driverAiPace: (driverId: number, q: AiPaceQuery = {}) => req<DriverAiPace>(aiPaceUrl(driverId, q)),
  /** Ask the race engineer (grounded on the session's facts, or a deterministic answer). */
  ask: (question: string, sessionId: string | null, useLlm = true) =>
    post<EngineerAnswer>("/api/engineer/ask", { question, session_id: sessionId, use_llm: useLlm }),
  history: (sessionId: string | null) =>
    req<EngineerHistoryRow[]>(`/api/engineer/history${sessionId ? `?session_id=${enc(sessionId)}` : ""}`),
  facts: (sessionId: string) => req<EngineerFact[]>(`/api/engineer/facts?session_id=${enc(sessionId)}`),
};

/** `/api/drivers/{id}/progress?…` (only the parts that are set; `corners=false` and `synthetic=true` when asked). */
export function progressUrl(driverId: number, q: ProgressQuery = {}): string {
  const p = new URLSearchParams();
  if (q.game) p.set("game", q.game);
  if (q.track_id) p.set("track_id", q.track_id);
  if (q.car) p.set("car", q.car);
  if (q.synthetic) p.set("synthetic", "true");
  if (q.corners === false) p.set("corners", "false");
  if (q.limit != null) p.set("limit", String(q.limit));
  const qs = p.toString();
  return `/api/drivers/${driverId}/progress${qs ? `?${qs}` : ""}`;
}

/** `/api/drivers/{id}/ai-pace?…` (only the parts that are set). */
export function aiPaceUrl(driverId: number, q: AiPaceQuery = {}): string {
  const p = new URLSearchParams();
  if (q.game) p.set("game", q.game);
  if (q.track_id) p.set("track_id", q.track_id);
  if (q.car_class) p.set("car_class", q.car_class);
  if (q.category) p.set("category", q.category);
  if (q.limit != null) p.set("limit", String(q.limit));
  if (q.target_gap_pct != null) p.set("target_gap_pct", String(q.target_gap_pct));
  const qs = p.toString();
  return `/api/drivers/${driverId}/ai-pace${qs ? `?${qs}` : ""}`;
}

/** A 404 or 405 from FastAPI's own router ("Not Found" / "Method Not Allowed"): the server predates the route. A 404
 * with any other detail is the route answering (e.g. "driver 7 not found"). */
export function isMissingRoute(e: unknown): boolean {
  return (
    e instanceof ApiError &&
    ((e.status === 404 && e.message === "404: Not Found") || (e.status === 405 && e.message === "405: Method Not Allowed"))
  );
}

/** After an ownership change: every list, and the session's own row and analysis (they carry the owner). */
export function invalidateSessionLists(sessionId?: string): void {
  cache.invalidate("sessions");
  cache.invalidate("driver-sessions:");
  if (sessionId) {
    cache.invalidate(reviewKeys.session(sessionId));
    cache.invalidate(reviewKeys.analysis(sessionId));
  }
}
