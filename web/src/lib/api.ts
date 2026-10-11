// Thin typed API client. Auth: localhost needs nothing; LAN devices open the URL printed by `pitwall token`
// once (?token=...), which sets an httpOnly cookie used by every later request.

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
  corner_text?: Record<string, { short: string; long: string; voice: string }>;
}

/** How to label a learned corner: the official short label when the track sheet maps it, else pitwall's own name. */
export function cornerLabel(model: TrackModel | null | undefined, name: string, style: "short" | "long" = "short"): string {
  return model?.corner_text?.[name]?.[style] ?? name;
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
}

export interface LapSummary {
  lap_id: number;
  lap_number: number;
  lap_time_ms: number | null;
  sector_times_ms: (number | null)[];
  valid: boolean | null;
  clean: boolean;
  flags: string[];
  tyre_compound: string | null;
  fuel_used_kg: number | null;
}

// Track knowledge (core/track_knowledge.py TrackKnowledge.to_dict): layers L3 (learned) > L0b (AI field) > L1c.
// Everything tier "field_observed" is an AI reference, never the driver's target.
export interface KnowledgeZone {
  key: string; // learned corner ("T3"), provisional field corner ("F2") or "zone@<onset>"
  label: string | null; // official label from the track sheet
  onset_m: number | null; // the AI field's median braking onset
  profile_onset_m: number | null;
  heads_up_m: number | null; // conservative early point (onset - uncertainty)
  uncertainty_m: number | null;
  end_m: number | null;
  entry_speed_kph: number | null;
  min_speed_kph: number | null;
  min_speed_m: number | null;
  peak_brake: number | null;
  severity: "heavy" | "medium" | "light";
  support: number; // car-laps that braked here
  cars: number;
  onset_q25_m: number | null;
  onset_q75_m: number | null;
  spread_m: number | null;
  corner: string | null;
  complete: boolean;
  superseded_by: "learned" | null;
  tier: string;
  source: string;
}

export interface KnowledgeHeadsUp {
  key: string;
  target_m: number | null;
  onset_m: number | null;
  uncertainty_m: number | null;
  severity: string;
  support: number;
  cars: number;
  entry_speed_kph: number | null;
  min_speed_kph: number | null;
  label: string | null;
  voice: string | null;
  tier: string;
  source: string;
  phrase: string;
}

export interface KnowledgeCorner {
  key: string;
  name: string;
  label: string | null;
  text: { short: string; long: string; voice: string | null };
  apex_m: number | null;
  entry_m: number | null;
  exit_m: number | null;
  min_speed_kph: number | null;
  direction: string | null;
  tier: string;
  source: string;
}

export interface FieldLayerInfo {
  tier: string;
  source: string;
  available: boolean;
  version: number | null;
  car_laps: number;
  cars: number;
  coverage: number;
  braking_zones: number;
  heads_up: number;
  min_support: number;
  brake_envelope: { brake_base: number; brake_aero: number; samples: number; decel_g_at_300_kph: number } | null;
  counts: Record<string, number>;
}

export interface TrackKnowledge {
  game: string | null;
  track_id: string | null;
  track_name: string | null;
  track_length_m: number | null;
  session_uid: string | null;
  synthetic: boolean;
  version: number;
  positions: "learned" | "field_observed" | "physics_predicted" | null;
  layers: {
    L3: { tier: string; available: boolean; version: number | null; n_laps: number | null; corners: number };
    L0b: FieldLayerInfo;
    L1c: { tier: string; available: boolean; source: string | null; severity_tags: number };
  };
  corners: KnowledgeCorner[];
  braking_zones: KnowledgeZone[];
  heads_up: KnowledgeHeadsUp[];
  severity_tags: { window_start_m: number | null; window_end_m: number | null; severity: string; label: string | null; tier: string; source: string }[];
  line: { tier: string; source: string; step_m: number; points: [number | null, number | null][] } | null;
  speed_profile: {
    tier: string;
    source: string;
    step_m: number;
    speed_kph: (number | null)[];
    speed_iqr_kph: (number | null)[];
    brake_frac: (number | null)[];
    support: number[];
  } | null;
}

export interface Snapshot {
  version: number;
  connection: {
    status: "live" | "stale" | "no_data";
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
  track_model?: TrackModel | null;
  /** Game-native sectors and zones (every 5 s); live marshal flags arrive in every snapshot. */
  skeleton?: import("./SectorBands.svelte").TrackSkeleton | null;
  marshal_flags?: { game_number: number; flag: string }[];
  /** Track knowledge by layer (every 5 s with the static fields). */
  track_knowledge?: TrackKnowledge | null;
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

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { credentials: "same-origin", ...init });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      detail = (await r.json()).detail ?? detail;
    } catch {
      /* not json */
    }
    throw new Error(`${r.status}: ${detail}`);
  }
  return r.json() as Promise<T>;
}

const post = <T>(path: string, body: unknown) =>
  req<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const api = {
  health: () => req<Record<string, any>>("/api/health"),
  llmHealth: () => req<Record<string, any>>("/api/llm/health"),
  capabilities: () => req<any[]>("/api/capabilities"),
  live: (staticData = false) => req<Snapshot>(`/api/live${staticData ? "?static=true" : ""}`),
  sessions: () => req<SessionRow[]>("/api/sessions"),
  session: (id: string) => req<SessionRow & { laps: LapRow[]; setup: any }>(`/api/sessions/${id}`),
  analysis: (id: string) => req<any>(`/api/sessions/${id}/analysis`),
  report: (id: string) => req<{ markdown: string }>(`/api/sessions/${id}/report`),
  trace: (lapId: number, step = 2) => req<LapTrace>(`/api/laps/${lapId}/trace?step=${step}`),
  compare: (ref: number, lap: number) =>
    req<{ comparison: Comparison; observations: Observation[]; track_model: TrackModel }>(
      `/api/compare?ref=${ref}&lap=${lap}`,
    ),
  pinReference: (lapId: number) => post<any>("/api/references", { lap_id: lapId }),
  captures: () => req<any[]>("/api/captures"),
  replay: (path: string, speed: number | null, loop = false) => post<any>("/api/replay", { path, speed, loop }),
  stopReplay: () => req<any>("/api/replay", { method: "DELETE" }),
  simulate: (scenario = "coaching-demo", packet_format = 2025) =>
    post<any>("/api/simulate", { scenario, packet_format }),
  ask: (question: string, session_id: string | null, use_llm = true) =>
    post<EngineerAnswer>("/api/engineer/ask", { question, session_id, use_llm }),
  history: (session_id: string | null) =>
    req<any[]>(`/api/engineer/history${session_id ? `?session_id=${session_id}` : ""}`),
};
