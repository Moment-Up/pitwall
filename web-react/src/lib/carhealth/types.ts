// Car health and racecraft (lane "health"): the JSON contract of `pitwall/carhealth` as the dashboard reads it. A
// TypeScript mirror of the backend's carhealth/view.py (`snapshot["car_health"]`, GET /api/car-health/live),
// `snapshot["racecraft"]` (GET /api/racecraft/live) and carhealth/settings.py (GET/PUT /api/car-health/settings).
// Lane spec section 3.11 / 3.12. Pure types.
//
// Honesty rules carried by the contract (CLAUDE.md "unknown stays unknown"): every number is null when the engine
// does not know it, never 0. A section the game cannot fill is `{available: false, reason}` with the capability
// sentence. Tyre temperatures are judged against the driver's own warm laps in this session, never against a fixed
// window: no game publishes its windows. Racecraft carries positions, car indexes and corners only (no names).

export type HealthWheel = "FL" | "FR" | "RL" | "RR";

/** Which temperature the game simulates: "carcass" (F1 surface & carcass model: the inner temperature is real) or
 * "surface" (surface only: F1 then sends a constant inner temperature, so Pitwall never uses or shows it). */
export type TyreModel = "carcass" | "surface";

/** Per wheel, against this session's own warm laps. "hot" is display only and unvalidated (heuristic). */
export type TyreTempBand = "cold" | "ok" | "hot" | "unknown";

export interface TyreWheelHealth {
  wheel: HealthWheel;
  band: TyreTempBand;
  /** Rolling window median (°C) in the model's temperature. */
  window_c: number | null;
  lap_median_c: number | null;
  /** The baseline in use for this wheel (°C). */
  baseline_c: number | null;
  pressure_psi: number | null;
  wear_pct: number | null;
}

export interface TyreHealth {
  available: true;
  model: TyreModel;
  compound: string | null;
  /** The cold-tyre state machine: "cold" after a pit exit or a safety-car end until warm again. */
  state: "cold" | "ok" | "unknown";
  since: { lap: number | null; reason: "pit_exit" | "sc_end" | "warm" | "timeout" | string } | null;
  /** Mean of the four wheels, rolling median (°C). */
  index_c: number | null;
  baseline_c: number | null;
  baseline_source: "this_stint" | "previous_stint" | null | string;
  wheels: TyreWheelHealth[];
  note: string | null;
  tier: "heuristic" | "measured" | string;
}

/** A section the game cannot fill: the capability sentence ("GT7 doesn't send brake temperatures"). */
export interface Unavailable {
  available: false;
  reason: string | null;
}

export interface BrakeHealth {
  available: true;
  /** FL FR RL RR, °C; null entries are unknown. */
  last_lap_max_c: (number | null)[] | null;
  baseline_max_c: (number | null)[] | null;
  word: "normal" | "hotter" | "cooler" | null | string;
  reason: string | null;
}

export interface EngineHealth {
  available: true;
  lap_median_c: number | null;
  baseline_c: number | null;
  max_c: number | null;
  word: "steady" | "hotter" | "cooler" | null | string;
  reason: string | null;
}

export interface SlipCorner {
  /** Learned corner name ("T1"). */
  corner: string;
  /** Spoken label ("Turn 1"). */
  text: string;
  lockups: number;
  wheelspin: number;
}

export interface SlipLap {
  lap: number;
  lockups: number | null;
  lockup_s: number | null;
  wheelspin: number | null;
  wheelspin_s: number | null;
  corners: SlipCorner[];
}

export interface SlipHealth {
  available: true;
  /** ABS on (per frame); null = unknown. */
  abs: boolean | null;
  /** Traction control level at the latest frame: 0 off, 1 medium, 2 full; null = unknown. */
  tc: number | null;
  /** false while ABS is on: lock-ups are not counted ("not applicable"), never "0". */
  lockups_applicable: boolean;
  last_lap: SlipLap | null;
  current: { lap: number; lockups: number | null; wheelspin: number | null } | null;
  session: { laps: number; lockups: number | null; wheelspin: number | null } | null;
  reason: string | null;
}

export type FuelStatus = "ok" | "low" | "critical" | "unknown" | "not_used" | "unverified" | "not_sent";

/** Fuel from the tank level (Forza; GT7 once verified). F1 keeps the strategy engine's fuel: this block is null. */
export interface TankFuel {
  /** null when the game sends no fuel at all (status "not_sent"). */
  source: "tank_fraction" | null;
  status: FuelStatus;
  /** 0..1 */
  fraction: number | null;
  per_lap: number | null;
  laps_of_fuel: number | null;
  laps_used: number | null;
  /** "community" (Forza Data Out), "unverified" (GT7), null when not sent. */
  tier: "community" | "unverified" | string | null;
  reason: string | null;
}

export type HealthCallLevel = "alert" | "normal" | "detailed";

export interface HealthCall {
  id: string;
  /** tyres_cold | tyres_warm | wear_high | fuel_low | fuel_critical | slip_lockups | slip_wheelspin */
  topic: string;
  level: HealthCallLevel;
  /** The backend's words, verbatim (P9). */
  text: string;
  text_simple?: string | null;
  lap: number | null;
  /** Server clock, whole seconds in the snapshot's view (carhealth/view.py); the TYRES COLD chip times itself from it. */
  t_unix: number;
  ttl_s?: number;
}

export interface HealthThreshold {
  name: string;
  value: number;
  unit: string;
  heuristic: boolean;
  meaning: string;
  evidence: string;
}

/** `snapshot["car_health"]` and GET /api/car-health/live (carhealth/view.py, version 1). */
export interface CarHealthView {
  version: 1;
  session_id: string | null;
  game: string | null;
  synthetic: boolean;
  tyres: TyreHealth | Unavailable | null;
  brakes: BrakeHealth | Unavailable | null;
  engine: EngineHealth | Unavailable | null;
  slip: SlipHealth | Unavailable | null;
  /** null for F1 (strategy owns fuel) and before the first data. */
  fuel: TankFuel | null;
  /** Newest first. */
  calls: HealthCall[];
  thresholds: HealthThreshold[];
}

// ------------------------------------------------------------------------------------------------ racecraft

/** "unknown": not enough usable laps of the player or that car yet (laps_compared null). */
export type RacecraftVerdict = "clear" | "spread" | "none" | "unknown";

export interface RacecraftCorner {
  /** Learned name ("T2"): the key of the track model's corners. */
  name: string;
  /** Spoken label ("Turn 3"). */
  text: string;
  /** Player minus that car over the segment (s): negative = the player is quicker there. */
  delta_s: number;
}

export interface RacecraftSide {
  car_index: number;
  position: number | null;
  /** [player laps, that car's laps] compared (each 2..3); null before both have two usable laps. */
  laps_compared: [number, number] | null;
  verdict: RacecraftVerdict;
  corner: RacecraftCorner | null;
  second: RacecraftCorner | null;
  margin_s: number | null;
  /** Σ of the segment deltas (s a lap): negative = the player is quicker over the lap. */
  lap_delta_s: number | null;
  /** The gap to that car is under the backend's CLOSE_GAP_S (1.5 s); null when the game gives no gap. Absent from
   * older servers. */
  close?: boolean | null;
  /** Why there is no verdict ("needs two clean laps of you", "... of that car", "leading: ..."). */
  reason?: string | null;
}

/** `snapshot["racecraft"]` and GET /api/racecraft/live (carhealth/racecraft.py, version 1). */
export interface RacecraftView {
  version: 1;
  session_id: string | null;
  /** "off" outside F1 races, with a reason. */
  mode: "race" | "off";
  reason: string | null;
  corners_source: "learned" | "official" | null | string;
  ahead: RacecraftSide | null;
  behind: RacecraftSide | null;
}

// ------------------------------------------------------------------------------------------------- settings

export type SlipCallsSetting = "off" | "detailed" | "normal";

/** GET/PUT /api/car-health/settings (carhealth/settings.py; household-wide). */
export interface CarHealthSettings {
  tyre_calls: boolean;
  wear_calls: boolean;
  fuel_calls: boolean;
  slip_calls: SlipCallsSetting;
}

/** Provenance a car-health fixture carries (src/test/fixtures/carhealth); never part of the wire format. */
export interface CarHealthFixtureMeta {
  tier: "recorded" | "synthetic" | "edited";
  source: string;
  moment: string;
  edits?: string[];
  notes?: string;
}
