// Test helpers for F2 support (imported only by *.test.ts; never by app code). The class payloads and session blocks
// are the contract's examples (scratchpad f2/design/contract.json, v1, 12 Oct 2026): what the F2 backend sends, built
// before it existed, so they are tier "contract" - never evidence that a game works. The session rows use the
// owner's recorded F2 sessions (11 Oct 2026, F1 25 on PS5: ids, tracks, times, laps and best laps read from a scratch
// copy of the database) with the contract's three additions.

import type { CarClass, SessionCarFields } from "./carclass";
import type { SessionListRow } from "./endpoints/review";
import type { SnapshotNext } from "./drive/types";

/** "snapshot.session (F2 Driver Career, Jeddah feature race)" */
export const F2_CLASS: CarClass = {
  id: "f2",
  family: "f2",
  label: "F2",
  formula: "F2",
  certain: true,
  has_ers: false,
  chip: true,
  evidence: "recorded_validated",
  notes: ["F2 cars have no ERS: F1 25 sends 0 for them."],
};

/** "snapshot.session (F1, McLaren, Imola)" */
export const F1_CLASS: CarClass = {
  id: "f1_2025",
  family: "f1",
  label: "F1",
  formula: "F1 Modern",
  certain: true,
  has_ers: true,
  chip: false,
  evidence: "live_validated",
  notes: [],
};

/** "snapshot.session (F1 World generic car, format 2025)" */
export const F1_GENERIC_CLASS: CarClass = { ...F1_CLASS, id: "f1", formula: "F1 World", certain: false };

export const CLASSIC_CLASS: CarClass = {
  id: "f1_classic",
  family: "other",
  label: "Classic F1",
  formula: "F1 Classic",
  certain: true,
  has_ers: null,
  chip: true,
  evidence: "spec_implemented",
  notes: [],
};

export const OTHER_CLASS: CarClass = {
  id: "other",
  family: "other",
  label: null,
  formula: "Beta",
  certain: true,
  has_ers: null,
  chip: false,
  evidence: "unverified",
  notes: [],
};

/** The live session block of the contract's Jeddah feature race (session type "Race 2"). */
export function f2JeddahSession(): NonNullable<SnapshotNext["session"]> {
  return {
    game: "f1_25",
    platform: "ps5",
    track_id: "f1:29",
    track_name: "Jeddah",
    track_length_m: 6174.0,
    session_type: "Race 2",
    car_name: "Art GP '24",
    weather: { condition: "light_cloud", track_temp_c: 32.0, air_temp_c: 26.0 },
    total_laps: 5,
    safety_car_status: "none",
    car_class: F2_CLASS,
    car_label: "F2 · Art GP '24",
    session_label: "Feature race",
  };
}

/** The contract's F2 Grand Prix session (team 214, format 2025: the spec names no team, the recording does). */
export function f2MelbourneSprintSession(): NonNullable<SnapshotNext["session"]> {
  return {
    ...f2JeddahSession(),
    track_id: "f1:0",
    track_name: "Melbourne",
    track_length_m: 5276.0,
    session_type: "Race",
    car_name: "Unknown team (id 214)",
    car_label: "F2 · Hitech '25",
    session_label: "Sprint race",
  };
}

function row(over: Partial<SessionListRow>): SessionListRow {
  return {
    id: "",
    game: "f1_25",
    platform: "ps5",
    track_id: null,
    track_name: null,
    track_length_m: null,
    session_type: null,
    session_type_raw: null,
    car_name: null,
    started_unix: 0,
    source: "udp:20777",
    synthetic: false,
    lap_count: 0,
    best_clean_ms: null,
    weather: {},
    driver_id: 1,
    driver_name: "James",
    ...over,
  };
}

const F2_FIELDS = (car_label: string, session_label: string): SessionCarFields => ({ car_class: F2_CLASS, car_label, session_label });

/** Recorded F2 session rows (repo.list_sessions shape) with the contract's car_class / car_label / session_label. */
export const F2_ROWS = {
  /** 1e7271f70c5e: Melbourne, F2 Grand Prix mode, the game's "Race" (type 15) = the sprint; car stored as "team_214". */
  melbourneSprint: (): SessionListRow =>
    row({
      id: "1e7271f70c5e",
      track_id: "f1:0",
      track_name: "Melbourne",
      track_length_m: 5276,
      session_type: "race",
      session_type_raw: "Race",
      car_id: "f1:team:214",
      car_name: "team_214",
      started_unix: 1791677832.31945,
      lap_count: 3,
      best_clean_ms: 95588,
      ai_difficulty: 35,
      weather: { condition: "clear", track_temp_c: 30, air_temp_c: 21 },
      ...F2_FIELDS("F2 · Hitech '25", "Sprint race"),
    }),
  /** 94bb7e902c10: Jeddah, Driver Career, the game's "Race 2" (type 16) = the feature race, Art GP '24 (team 158). */
  jeddahFeature: (): SessionListRow =>
    row({
      id: "94bb7e902c10",
      track_id: "f1:29",
      track_name: "Jeddah",
      track_length_m: 6175,
      session_type: "race",
      session_type_raw: "Race 2",
      car_id: "f1:team:158",
      car_name: "Art GP '24",
      started_unix: 1791758551.73706,
      lap_count: 5,
      best_clean_ms: 105401,
      ai_difficulty: 50,
      weather: { condition: "clear", track_temp_c: 39, air_temp_c: 28 },
      ...F2_FIELDS("F2 · Art GP '24", "Feature race"),
    }),
  /** 969ee7a1b400: Melbourne one-shot qualifying (session_label is the game's own name). */
  melbourneOneShot: (): SessionListRow =>
    row({
      id: "969ee7a1b400",
      track_id: "f1:0",
      track_name: "Melbourne",
      track_length_m: 5276,
      session_type: "qualifying",
      session_type_raw: "One-Shot Qualifying",
      car_id: "f1:team:158",
      car_name: "Art GP '24",
      started_unix: 1791759272.73702,
      lap_count: 2,
      best_clean_ms: 91525,
      ai_difficulty: 50,
      weather: { condition: "light_cloud", track_temp_c: 26, air_temp_c: 19 },
      ...F2_FIELDS("F2 · Art GP '24", "One-Shot Qualifying"),
    }),
};
