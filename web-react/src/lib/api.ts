// Thin typed API client, ported 1:1 from web/src/lib/api.ts (every type and endpoint kept; framework-agnostic).
// Auth: see ./auth.ts - localhost needs nothing; LAN devices open the URL printed by `pitwall token` once
// (?token=...), which sets an httpOnly cookie used by every later request.

import { authFetch } from "./auth";
import type { SnapshotGame } from "./endpoints/game";
import type { PointKnowledge } from "./knowledge/annotation";
import type { TrackSkeleton } from "./skeleton";

/** Payloads the Svelte client left untyped (`any`). Typed per screen as each screen is ported. */
export type Untyped = any;

export interface Frame {
  speed_kph: number | null;
  throttle: number | null;
  brake: number | null;
  steering: number | null;
  gear: number | null;
  rpm: number | null;
  max_rpm: number | null;
  drs_open: boolean | null;
  pos: (number | null)[];
  g_lat: number | null;
  g_lon: number | null;
  lap_number: number | null;
  lap_distance_m: number | null;
  current_lap_time_ms: number | null;
  last_lap_time_ms: number | null;
  sector: number | null;
  lap_invalid: boolean | null;
  pit_status: number | null;
  race_position: number | null;
  tyre_surface_temp_c: number[] | null;
  tyre_inner_temp_c: number[] | null;
  tyre_pressure_psi: number[] | null;
  brake_temp_c: number[] | null;
  tyre_wear_pct: number[] | null;
  tyre_compound: string | null;
  tyre_age_laps: number | null;
  fuel_kg: number | null;
  fuel_remaining_laps_game: number | null;
  ers_store_j: number | null;
  brake_bias_front_pct: number | null;
  session_time_s: number | null;
}

export interface Corner {
  name: string;
  apex_m: number;
  entry_m: number;
  exit_m: number;
  seg_start_m: number;
  seg_end_m: number;
  direction: string | null;
  ref_min_speed_kph: number;
}

export interface CornerText {
  short: string;
  long: string;
  voice: string;
}

export interface TrackModel {
  game: string;
  track_id: string;
  track_name: string | null;
  length_m: number;
  version: number;
  n_laps: number;
  corners: Corner[];
  centreline: [number, number][];
  /** Official names from the track sheets, keyed by learned corner name (short "T10", long "Turn 10 (Red Bull Mobile)"). */
  corner_text?: Record<string, CornerText>;
}

/** How to label a learned corner: the official short label when the track sheet maps it, else pitwall's own name. */
export function cornerLabel(
  model: TrackModel | null | undefined,
  name: string,
  style: "short" | "long" = "short",
): string {
  return model?.corner_text?.[name]?.[style] ?? name;
}

/** The learned corner whose segment contains `lapDistanceM` (same rule as the Svelte LiveView), or null. */
export function cornerAt(model: TrackModel | null | undefined, lapDistanceM: number | null | undefined): Corner | null {
  if (lapDistanceM == null || !model) return null;
  return model.corners.find((c) => lapDistanceM >= c.seg_start_m && lapDistanceM < c.seg_end_m) ?? null;
}

export interface Observation {
  id: string;
  kind: string;
  corner: string;
  lap_number: number;
  ref_lap_number: number;
  value: number;
  unit: string;
  impact_s: number | null;
  confidence: number;
  text: string;
  consistency: string | null;
  positive: boolean;
  priority: number;
  evidence?: Record<string, unknown>;
  /** Technique knowledge (lib/knowledge/annotation.ts): the full annotation in Review, the slim copy in live
   * snapshots and coach points; absent on older servers and without the graph. */
  knowledge?: PointKnowledge | null;
}

export interface LapSummary {
  lap_id: number;
  lap_number: number;
  lap_time_ms: number | null;
  sector_times_ms: (number | null)[];
  valid: boolean | null;
  clean: boolean;
  flags: string[];
  /** The driver's last lap of the session (the game reported their result as finished on it); null/absent = unknown. */
  final?: boolean | null;
  tyre_compound: string | null;
  fuel_used_kg: number | null;
}

export type ConnectionStatus = "live" | "stale" | "no_data";

export interface Snapshot {
  version: number;
  connection: {
    status: ConnectionStatus;
    last_packet_age_s: number | null;
    packets: number;
    packets_per_s: number;
    rejected: number;
    unrecognised: number;
    source: string | null;
    synthetic: boolean;
    decode: Record<string, unknown>;
  };
  session_id: string | null;
  session: {
    game: string;
    platform: string;
    track_id: string | null;
    track_name: string | null;
    track_length_m: number | null;
    session_type: string;
    car_name: string | null;
    weather: { condition: string | null; track_temp_c: number | null; air_temp_c: number | null };
    total_laps: number | null;
    safety_car_status: string | null;
  } | null;
  frame: Frame | null;
  delta_s: number | null;
  reference: { lap_id: number; lap_number: number; lap_time_ms: number | null; session_id: string } | null;
  laps: LapSummary[];
  observations: Observation[];
  events: { kind: string; code: string | null; session_time_s: number | null; t: number }[];
  /** Static parts (track model, skeleton) arrive every ~5 s; the live store carries them across other snapshots. */
  track_model?: TrackModel | null;
  /** Game-native sectors and zones (every 5 s); live marshal flags arrive in every snapshot. */
  skeleton?: TrackSkeleton | null;
  marshal_flags?: { game_number: number; flag: string }[];
  /** The selected and the detected game, mismatch and suggestion (lib/endpoints/game.ts). In every snapshot; absent
   * only from servers before game selection, and then every page renders as it did before. */
  game?: SnapshotGame;
}

export interface SessionRow {
  id: string;
  game: string;
  platform: string | null;
  track_id: string | null;
  track_name: string | null;
  track_length_m: number | null;
  session_type: string | null;
  session_type_raw: string | null;
  car_name: string | null;
  started_unix: number;
  source: string;
  synthetic: boolean;
  lap_count: number;
  best_clean_ms: number | null;
  weather: { condition?: string; track_temp_c?: number; air_temp_c?: number };
  /** The game catalogue entry this session was recorded with (lib/endpoints/game.ts); null when unresolvable,
   * absent from servers before game selection. */
  game_entry_id?: string | null;
}

export interface LapRow {
  id: number;
  lap_number: number;
  lap_time_ms: number | null;
  s1_ms: number | null;
  s2_ms: number | null;
  s3_ms: number | null;
  valid: boolean | null;
  clean: boolean;
  flags: string[];
  meta: Record<string, unknown>;
}

export interface LapTrace {
  lap_id: number;
  lap_number: number;
  lap_time_ms: number | null;
  d: number[];
  t_s: (number | null)[];
  speed_kph: (number | null)[];
  throttle: (number | null)[];
  brake: (number | null)[];
  steering: (number | null)[];
  gear: (number | null)[];
  pos_x_m: (number | null)[];
  pos_z_m: (number | null)[];
  g_lat: (number | null)[];
  g_lon: (number | null)[];
}

export interface CornerDelta {
  corner: string;
  time_delta_s: number | null;
  brake_point_delta_m: number | null;
  min_speed_delta_kph: number | null;
  exit_speed_delta_kph: number | null;
  entry_speed_delta_kph: number | null;
  throttle_full_delta_m: number | null;
  coast_delta_m: number | null;
}

export interface Comparison {
  ref_lap_number: number;
  cmp_lap_number: number;
  total_delta_s: number | null;
  delta_d: number[];
  delta_s: number[];
  corners: CornerDelta[];
  compatibility: { ok: boolean; blocking: string[]; warnings: string[] };
}

export interface EngineerAnswer {
  session_id: string;
  text: string;
  speech: string;
  intent: string;
  corner: string | null;
  facts: { id: string; topic: string; text: string }[];
  grounded: boolean | null;
  fallback: boolean;
  model: string | null;
  latency_ms: number;
  llm_attempts: number;
  grounding_issues: string[];
  control: Record<string, unknown> | null;
}

/** An HTTP error from the API, with the server's `detail` when it sent one. */
export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, detail: string) {
    super(`${status}: ${detail}`);
    this.name = "ApiError";
    this.status = status;
  }
}

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

export const api = {
  health: () => req<Record<string, Untyped>>("/api/health"),
  llmHealth: () => req<Record<string, Untyped>>("/api/llm/health"),
  capabilities: () => req<Untyped[]>("/api/capabilities"),
  live: (staticData = false) => req<Snapshot>(`/api/live${staticData ? "?static=true" : ""}`),
  sessions: () => req<SessionRow[]>("/api/sessions"),
  session: (id: string) => req<SessionRow & { laps: LapRow[]; setup: Untyped }>(`/api/sessions/${id}`),
  analysis: (id: string) => req<Untyped>(`/api/sessions/${id}/analysis`),
  report: (id: string) => req<{ markdown: string }>(`/api/sessions/${id}/report`),
  trace: (lapId: number, step = 2) => req<LapTrace>(`/api/laps/${lapId}/trace?step=${step}`),
  compare: (ref: number, lap: number) =>
    req<{ comparison: Comparison; observations: Observation[]; track_model: TrackModel }>(
      `/api/compare?ref=${ref}&lap=${lap}`,
    ),
  pinReference: (lapId: number) => post<Untyped>("/api/references", { lap_id: lapId }),
  captures: () => req<Untyped[]>("/api/captures"),
  replay: (path: string, speed: number | null, loop = false) => post<Untyped>("/api/replay", { path, speed, loop }),
  stopReplay: () => req<Untyped>("/api/replay", { method: "DELETE" }),
  simulate: (scenario = "coaching-demo", packet_format = 2025) =>
    post<Untyped>("/api/simulate", { scenario, packet_format }),
  ask: (question: string, session_id: string | null, use_llm = true) =>
    post<EngineerAnswer>("/api/engineer/ask", { question, session_id, use_llm }),
  history: (session_id: string | null) =>
    req<Untyped[]>(`/api/engineer/history${session_id ? `?session_id=${session_id}` : ""}`),
};
