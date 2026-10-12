// Race strategy engineer (lane "strategy"): the JSON contract of `pitwall/strategy` as the dashboard reads it. A
// TypeScript mirror of the backend's strategy/view.py (`snapshot["strategy"]`, GET /api/strategy/live) and
// strategy/timeline.py (GET /api/sessions/{id}/strategy). Pure types.
//
// Honesty rules carried by the contract (CLAUDE.md "unknown stays unknown"): every number is null when the engine
// does not know it, never 0. Every estimate carries its tier: "measured" (this race's own timing), "game" (the game's
// own model or figure, e.g. TyreSets, the MFD fuel margin) or "heuristic" (a Pitwall rule of thumb, unvalidated in
// F1 25). Nothing here is advice the UI invents: calls are the backend's text, verbatim.

export type Tier = "measured" | "game" | "heuristic";
export type Wheel = "FL" | "FR" | "RL" | "RR";

/** A value with its quantisation / uncertainty range; `high` null = open-ended. */
export interface Range {
  low: number;
  high: number | null;
}

export type StrategyMode = "race" | "practice" | "off";

export interface CarGap {
  car_index: number;
  gap_s: number | null;
  /** false while the gap is in doubt (position change, a car in the pit lane): the last settled value, dimmed. */
  settled: boolean;
  /** + growing, − closing (s per lap). */
  trend_s_per_lap: number | null;
  /** Line gaps the trend was fitted on. */
  trend_laps: number;
  laps_to_1s: number | null;
  within_1s: boolean | null;
  /** Within a second with DRS enabled (format 2025); null when DRS state is unknown. */
  drs_range: boolean | null;
  stops: number | null;
  in_pit: boolean;
  /** Null for cars whose telemetry is restricted (online humans). */
  tyre: { compound: string | null; age_laps: number | null } | null;
}

export interface GapsView {
  ahead: CarGap | null;
  behind: CarGap | null;
  leader_s: number | null;
  note: string | null;
}

export interface TyresView {
  compound: string | null;
  age_laps: number | null;
  stint_laps: number;
  /** FL FR RL RR. */
  wear_pct: [number, number, number, number] | null;
  limiting_wheel: Wheel | null;
  rate_pct_per_lap: number | null;
  rate_range: Range | null;
  limit_pct: number;
  laps_to_limit: Range | null;
  enough_laps: boolean;
  note: string | null;
  game_laps_left: number | null;
  game_usable_life: number | null;
  new_set: { compound: string; gain_s: number; deg_s_per_lap: number | null; tier: "game" } | null;
}

export interface FuelView {
  fuel_kg: number | null;
  per_lap_kg: number | null;
  laps_used: number;
  margin_laps: number | null;
  margin_kg: number | null;
  /** The game's MFD figure (tier game). */
  game_margin_laps: number | null;
  status: "ok" | "tight" | "short" | "unknown";
  lift_coast: { save_kg_per_lap: number; seconds_per_lap: number; feasible: boolean; corners: string[] } | null;
  burn_model: { full_throttle_kg_per_s: number; r2: number; windows: number } | null;
}

export type CutStatus = "likely" | "marginal" | "unlikely" | "unknown";

export interface CutView {
  status: CutStatus;
  gap_s: number | null;
  gain: Range | null;
  reason: string;
  tier: Tier;
}

export interface NeighbourStopView {
  car: "ahead" | "behind";
  car_index: number;
  rejoin_gap_s: number | null;
  status: "covered" | "close" | "ahead" | "unknown";
  traffic: boolean | null;
}

/** `pit.rejoin`: where the player would come out if they boxed now. The first five keys exist on every server; the
 * rest come from strategy/rejoin.py (lane "health", "rejoin v2"): read only when `basis` is present, because the older
 * rule silently dropped cars whose timing gap F1 25 had zeroed and was wrong on real races. */
export interface RejoinView {
  position: number | null;
  gap_ahead_s: number | null;
  gap_behind_s: number | null;
  traffic: boolean | null;
  game_position: number | null;
  // --- health lane: rejoin v2 (all optional: absent from older servers) ---
  /** "measured_loss": Pitwall's prediction from this race's pit loss; "estimated_loss": from the safety-car / VSC
   * loss rule of thumb (loss_tier "heuristic"); "game_only": no stop measured yet, only the game's own figure
   * (`position` is null). */
  basis?: "measured_loss" | "estimated_loss" | "game_only" | string;
  position_low?: number | null;
  position_high?: number | null;
  ahead_position?: number | null;
  behind_position?: number | null;
  road_ahead_s?: number | null;
  road_behind_s?: number | null;
  unknown_cars?: number | null;
  /** The player is on the in-lap or in the pit lane: the last prediction made on track, held. */
  frozen?: boolean;
  loss_s?: number | null;
  loss_tier?: Tier | null;
  loss_n?: number | null;
  /** basis "game_only": why Pitwall has no estimate - "no_loss" (no stop timed yet) or "no_gap" (the player's own gap
   * unknown this moment, e.g. right after their own stop). Absent from older servers. */
  reason?: "no_loss" | "no_gap" | string | null;
  // --- end health lane ---
}

export interface PitView {
  /** The game's count; null before the first timing tick (unknown, not 0). */
  stops_done: number | null;
  stop_needed: boolean | null;
  two_stops: boolean | null;
  window: {
    open_lap: number;
    close_lap: number;
    ideal_lap: number | null;
    close_source: "measured" | "game";
    tier: Tier;
    /** At or past the wear limit already: the window is this lap (absent from older servers). */
    overdue?: boolean;
  } | null;
  game_window: { ideal_lap: number; latest_lap: number } | null;
  pit_loss: { median_s: number; range: Range; n: number } | null;
  pit_loss_sc: { full_s: number | null; virtual_s: number | null; tier: Tier } | null;
  pit_entry_m: number | null;
  rejoin: RejoinView | null;
  undercut_ahead: CutView | null;
  undercut_threat: CutView | null;
  neighbour_stop: NeighbourStopView | null;
  note: string | null;
  /** F2 support: the race's tyre and pit-stop rules, which the game never sends (absent from older servers). */
  rules?: PitRules | null;
}

/** strategy/view.py pit.rules (F2 support). The game sends no tyre or pit-stop rules (EA spec), so `known` is always
 * false: strategy never says a stop is not mandatory, it says the rules are not known. */
export interface PitRules {
  /** F2 only (recorded: the game's "Race" is the sprint, "Race 2" the feature race); null for F1 and unknown. */
  race: "sprint" | "feature" | null;
  known: false;
  /** "The game doesn't send this race's tyre or pit-stop rules." (verbatim) */
  text: string;
  /** The F2 feature or sprint note (verbatim); null otherwise. */
  class_note: string | null;
}

export type SafetyCarStatus = "none" | "full" | "virtual" | "formation_lap";

export interface SafetyCarView {
  status: SafetyCarStatus | null;
  since_lap: number | null;
  box: {
    pit_loss_s: number | null;
    green_pit_loss_s: number | null;
    stop_needed: boolean;
    /** null while the pit entry is unknown (no stop seen in this race yet). */
    this_lap: boolean | null;
    tier: Tier;
  } | null;
}

export interface ForecastPoint {
  in_min: number;
  weather: string | null;
  /** The game's rain number, shown verbatim; never read as a probability. */
  rain_pct: number | null;
  in_laps: number | null;
}

export interface WeatherView {
  now: string | null;
  rain_pct: number | null;
  track_temp_c: number | null;
  accuracy: "perfect" | "approximate" | null;
  /** <= 60 min. */
  forecast: ForecastPoint[];
  next_change: ForecastPoint | null;
  crossover: { compound: "inter" | "wet" | "slick"; gain_s: number; tier: "game" } | null;
}

export type CallLevel = "alert" | "normal" | "detailed";

export interface CallView {
  id: string;
  topic: string;
  level: CallLevel;
  /** The backend's words, verbatim (P9). */
  text: string;
  /** The same call in plain words, for a driver with simple wording; null for calls meant for experienced drivers
   * only. Absent from older servers. */
  text_simple?: string | null;
  /** "experienced": never said to (or shown for) a driver with simple wording. Absent from older servers. */
  audience?: "all" | "experienced";
  /** How long the call holds, seconds (a "box this lap" call ends at the pit entry). Absent from older servers. */
  ttl_s?: number;
  lap: number | null;
  t_unix: number;
}

/** `snapshot["strategy"]` and GET /api/strategy/live (strategy/view.py, version 1). */
export interface StrategyView {
  version: 1;
  mode: StrategyMode;
  /** Why the mode is off or limited ("time trial", "qualifying", "race strategy needs F1 25 timing", "no live
   * session"); null in a race. */
  reason: string | null;
  session_id: string | null;
  synthetic: boolean;
  lap: number | null;
  total_laps: number | null;
  laps_remaining: number | null;
  position: number | null;
  cars: number | null;
  /** Race only. */
  gaps: GapsView | null;
  tyres: TyresView | null;
  fuel: FuelView | null;
  /** Race only. */
  pit: PitView | null;
  /** Race only. */
  safety_car: SafetyCarView | null;
  weather: WeatherView | null;
  /** Newest first, max 3. */
  calls: CallView[];
  /** F2 support, race mode: the game's DRS-enabled state (DRSE / DRSD events); null = not known yet; absent from older
   * servers. */
  drs_enabled?: boolean | null;
}

// ------------------------------------------------------------------------------------------- Review timeline

/** `strategy_laps.data` (strategy/engine.py StrategyLapRecord, v1): the race as it stood at the end of one lap. */
export interface StrategyLapRecord {
  v: 1;
  lap: number;
  position: number | null;
  cars: number | null;
  lap_time_ms: number | null;
  gap_ahead_ms: number | null;
  ahead_car: number | null;
  ahead_stops: number | null;
  gap_behind_ms: number | null;
  behind_car: number | null;
  behind_stops: number | null;
  gap_leader_ms: number | null;
  pit: "in" | "out" | "in_out" | null;
  stops: number | null;
  compound: string | null;
  tyre_age_laps: number | null;
  wear_pct: [number, number, number, number] | null;
  fuel_kg: number | null;
  fuel_per_lap_kg: number | null;
  fuel_margin_laps: number | null;
  game_fuel_margin_laps: number | null;
  safety_car: SafetyCarStatus | null;
  weather: string | null;
  rain_pct: number | null;
  next_weather: string | null;
  window: { open: number; close: number; ideal: number | null } | null;
  undercut_ahead: CutStatus | null;
  undercut_threat: CutStatus | null;
  tyre_gain_s: number | null;
  calls: {
    id: string;
    topic: string;
    level: CallLevel;
    text: string;
    text_simple?: string | null;
    audience?: "all" | "experienced";
    ttl_s?: number;
    lap?: number | null;
    t_unix?: number;
  }[];
  // Additive fields the engine also writes (strategy/engine.py record): read when present, never required.
  total_laps?: number | null;
  grid_position?: number | null;
  /** A car beside the player pitted or SC / VSC ran on this lap: the line gaps are not race pace. */
  neutralised_gaps?: boolean;
  laps_to_limit?: Range | null;
  limiting_wheel?: Wheel | null;
}

export interface PitStopRow {
  car_index: number;
  is_player: boolean;
  entry_lap: number;
  exit_lap: number | null;
  lane_time_s: number | null;
  stationary_s: number | null;
  pit_loss_s: number | null;
  neutralised: "full" | "virtual" | null;
  /** Why the stop is not used for the pit-loss figure ("long stop (repair?)", ...); null when used. */
  excluded: string | null;
  compound_before: string | null;
  compound_after: string | null;
}

export interface StintRow {
  compound: string | null;
  start_lap: number;
  end_lap: number;
  laps: number;
  wear_end_pct: number | null;
  wear_rate_pct_per_lap: number | null;
  median_lap_ms: number | null;
}

/** GET /api/sessions/{id}/strategy (strategy/timeline.py). */
export interface StrategyTimeline {
  session_id: string;
  available: boolean;
  /** "not a race" | "recorded before strategy tracking" (or another reason in words); null when available. */
  reason: string | null;
  total_laps: number | null;
  grid_position: number | null;
  finish_position: number | null;
  laps: StrategyLapRecord[];
  stints: StintRow[];
  /** The player's stops. */
  stops: PitStopRow[];
  /** Other cars' stops (measured from the timing; no names). */
  field_stops: PitStopRow[];
  pit_loss: { median_s: number; range: Range; n: number } | null;
  safety_car_periods: { status: "full" | "virtual"; start_lap: number; end_lap: number | null }[];
  /** Changes only. */
  weather: { lap: number; weather: string | null; rain_pct: number | null }[];
  calls: (CallView & { lap: number | null })[];
}

/** Provenance a strategy fixture carries (src/test/fixtures/strategy); never part of the wire format. */
export interface StrategyFixtureMeta {
  tier: "recorded" | "synthetic" | "edited";
  source: string;
  moment: string;
  edits?: string[];
  notes?: string;
}
