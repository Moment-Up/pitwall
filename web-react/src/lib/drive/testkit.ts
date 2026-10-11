// Test helpers for the Drive logic tests (imported only by *.test.ts; never by app code). Fixtures are loaded
// eagerly here; app code uses ./fixtures.ts (lazy).

import type { Driver } from "../drivers";
import type { FixtureSnapshot, SnapshotNext } from "./types";

const ALL = import.meta.glob<FixtureSnapshot>("../../test/fixtures/drive/*.json", { eager: true, import: "default" });

const BY_NAME = new Map(
  Object.entries(ALL).map(([path, snap]) => [path.slice(path.lastIndexOf("/") + 1).replace(/\.json$/, ""), snap]),
);

export const FIXTURES: readonly string[] = [...BY_NAME.keys()].sort();

/** A deep copy of one fixture (tests may edit it). */
export function fixture(name: string): FixtureSnapshot {
  const s = BY_NAME.get(name);
  if (!s) throw new Error(`no fixture ${name}`);
  return structuredClone(s);
}

/** The snapshot as a live session would carry it (source udp:20777, not synthetic): in the timing scope (4.6), so
 * timing colours apply. Recorded fixtures come from replays, which are outside it. Edits in place and returns it. */
export function asLive<T extends SnapshotNext>(s: T): T {
  s.connection = { ...s.connection, source: "udp:20777", synthetic: false };
  return s;
}

/** The same moment once the car has come to rest (edited: speed 0). The Ready and Session complete cards wait for a
 * stationary car (motion.ts): recorded "session ended" moments still carry the last frame at racing speed, and the
 * card shows once the car stops or the data goes quiet. Edits in place and returns it. */
export function stopped<T extends SnapshotNext>(s: T): T {
  if (s.frame) s.frame = { ...s.frame, speed_kph: 0 };
  return s;
}

/** The newest event time of a snapshot (server clock), or 0. */
export function newestT(s: SnapshotNext | null): number {
  return Math.max(0, ...(s?.events ?? []).map((e) => e.t));
}

/** A minimal live snapshot; `over` replaces top-level keys. */
export function snap(over: Partial<SnapshotNext> = {}): SnapshotNext {
  return {
    version: 1,
    connection: {
      status: "live",
      last_packet_age_s: 0.02,
      packets: 1000,
      packets_per_s: 60,
      rejected: 0,
      unrecognised: 0,
      source: "udp:20777",
      synthetic: false,
      decode: {},
    },
    session_id: "s1",
    session: {
      game: "f1_25",
      platform: "ps5",
      track_id: "f1:7",
      track_name: "Silverstone",
      track_length_m: 5890,
      session_type: "Practice",
      car_name: null,
      weather: { condition: null, track_temp_c: null, air_temp_c: null },
      total_laps: null,
      safety_car_status: "none",
    },
    frame: frame(),
    delta_s: -0.21,
    reference: { lap_id: 4, lap_number: 4, lap_time_ms: 90986, session_id: "s1" },
    laps: [],
    observations: [],
    events: [],
    marshal_flags: [],
    ...over,
  };
}

export function frame(over: Partial<NonNullable<SnapshotNext["frame"]>> = {}): NonNullable<SnapshotNext["frame"]> {
  return {
    speed_kph: 250,
    throttle: 1,
    brake: 0,
    steering: 0,
    gear: 7,
    rpm: 11000,
    max_rpm: 13000,
    drs_open: false,
    pos: [0, 0, 0],
    g_lat: 0,
    g_lon: 0,
    lap_number: 7,
    lap_distance_m: 4560,
    current_lap_time_ms: 69549,
    last_lap_time_ms: 91512,
    sector: 2,
    lap_invalid: false,
    pit_status: 0,
    race_position: 4,
    tyre_surface_temp_c: null,
    tyre_inner_temp_c: null,
    tyre_pressure_psi: null,
    brake_temp_c: null,
    tyre_wear_pct: null,
    tyre_compound: null,
    tyre_age_laps: null,
    fuel_kg: null,
    fuel_remaining_laps_game: null,
    ers_store_j: null,
    brake_bias_front_pct: null,
    session_time_s: 600,
    ...over,
  };
}

export function lap(n: number, ms: number | null, sectors: (number | null)[] = [], over: Partial<SnapshotNext["laps"][number]> = {}) {
  return {
    lap_id: 100 + n,
    lap_number: n,
    lap_time_ms: ms,
    sector_times_ms: sectors,
    valid: true,
    clean: true,
    flags: [],
    tyre_compound: null,
    fuel_used_kg: null,
    ...over,
  };
}

export function driver(over: Partial<Driver> & { skill?: "beginner" | "intermediate" | "advanced"; simple?: boolean } = {}): Driver {
  const { skill = "advanced", simple = false, ...rest } = over;
  return {
    id: 1,
    name: "Alex",
    created_unix: 0,
    preferences: { colour: "#38bdf8", initials: "AL", skill_level: skill, coaching_intensity: "normal", voice_enabled: true },
    coaching: {
      skill_level: skill,
      intensity: "normal",
      min_confidence: 0.6,
      min_impact_s: 0.02,
      max_per_lap: 1,
      max_corrective_per_lap: 1,
      max_positive_per_lap: 0,
      allowed_kinds: null,
      simple_wording: simple,
      mention_consistency: true,
      corner_repeat_gap_laps: 0,
    },
    active: true,
    stats: { sessions: 1, laps: 1, clean_laps: 1, tracks: 1, last_session_unix: null, best_laps: [] },
    ...rest,
  };
}
