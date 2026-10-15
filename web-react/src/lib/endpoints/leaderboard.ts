// Family leaderboard endpoints (Review › Progress, Records): typed client for one board and the record index. Server
// side: src/pitwall/api/routes_leaderboard.py and src/pitwall/leaderboard/{board,service}.py; the JSON contract is
// docs/leaderboard.md. Local only: the server reads its own database and sends nothing anywhere.
//
// The types mirror the Python dicts exactly; changing them needs both builders. Lap times are in ms. Unknown stays
// unknown (null); in a key string `?` is unknown and `-` "this game has no such setting".
//
// Cache keys (lib/cache.ts). Both live under "driver-sessions:" so a completed lap, a driver switch or a session moved
// to another driver refreshes them with the rest of the drivers' data (hooks/useApi.ts useCacheInvalidation):
//   leaderboardKeys.board(q)     GET /api/leaderboard?key=… | ?game&track_id[&car_id…] [&car_generation]
//   leaderboardKeys.records(q)   GET /api/records?game&track_id&driver_id[&car_generation]

import { ApiError } from "../api";
import { authFetch } from "../auth";

// ------------------------------------------------------------------------------------------------ contract

export type BoardCategory = "time_trial" | "qualifying" | "race" | "practice" | "unknown";
export type BoardConditions = "dry" | "wet" | "unknown";
/** The driver's answer when the game cannot tell a 2025 from a 2026 car (`real_f1_asks_generation`). */
export type CarGeneration = "f1_2025" | "f1_2026";
/** GT7-style bands against an optional row: gold within 3 % (or faster), silver within 5 %, bronze within 10 %. */
export type Band = "gold" | "silver" | "bronze";
export type BenchmarkKind = "ea_rival" | "real_f1";

/** One assist setting of a board in words (`keys.assist_chips`). */
export interface AssistChip {
  key: string;
  value: number | null;
  known: boolean;
  label: string;
}

/** A lap against an optional row: `gap_ms` positive = slower than it; `band` null = no band (none, or not banded). */
export interface BoardVs {
  gap_ms: number;
  gap_pct: number;
  gap_text: string;
  band: Band | null;
}

/** An index row's record against an optional row. */
export interface IndexVs extends BoardVs {
  lap_ms: number;
  label: string;
}

export type BoardVsAll = Partial<Record<BenchmarkKind, BoardVs>>;

export interface F1BoardAssists {
  braking: number | null;
  abs: number | null;
  tc: number | null;
  gearbox: number | null;
  racing_line: number | null;
}
export interface AcBoardAssists {
  abs: number | null;
  tc: number | null;
}

/** A board key as JSON: every part, null for unknown. */
export interface BoardFields {
  game: string;
  track_id: string;
  layout_m: number | null;
  car_id: string | null;
  car_class: "f1" | "f2" | "other" | null;
  equal_performance: 0 | 1 | null;
  category: BoardCategory;
  conditions: BoardConditions;
  assists: F1BoardAssists | AcBoardAssists | null;
  assists_code: string;
}

/** A board in words (public names only). */
export interface BoardLabels {
  game: string;
  track: string;
  layout: string;
  car: string;
  car_class: string | null;
  equal_performance: string | null;
  category: string;
  conditions: string;
  assists: AssistChip[];
  assists_text: string;
  title: string;
}

export interface BoardRecord {
  driver_id: number;
  driver_name: string;
  lap_ms: number;
  lap_id: number;
  session_id: string;
  set_unix: number;
  date_text: string;
}

/** A row of the record index (`/api/records`, and a board's `boards_here`). */
export interface RecordsIndexRow {
  key: string;
  fields: BoardFields;
  labels: BoardLabels;
  record: BoardRecord;
  drivers: number;
  clean_laps: number;
  last_unix: number;
  track_limits_checked: boolean;
  vs: Partial<Record<BenchmarkKind, IndexVs>>;
}

/** A household driver's best on a board, fastest first. */
export interface BoardRow {
  position: number;
  driver_id: number;
  driver_name: string;
  lap_ms: number;
  lap_id: number;
  lap_number: number | null;
  session_id: string;
  set_unix: number;
  date_text: string;
  leader: boolean;
  gap_ms: number | null;
  gap_pct: number | null;
  /** "Fastest" | "3.067 s behind". */
  gap_text: string;
  clean_laps: number;
  assists: AssistChip[];
  best_sectors_ms: [number | null, number | null, number | null];
  theoretical_best_ms: number | null;
  theoretical_gain_ms: number | null;
  game_version: string | null;
  vs: BoardVsAll;
}

/** A lap that became the family record (oldest first). */
export interface RecordHistoryEntry {
  lap_id: number;
  lap_number: number | null;
  session_id: string;
  driver_id: number;
  driver_name: string;
  lap_ms: number;
  set_unix: number;
  date_text: string;
  previous_ms: number | null;
  previous_driver_id: number | null;
  previous_driver_name: string | null;
  gain_ms: number | null;
  changed_hands: boolean;
  /** "Jo took the record from Sam: 1:05.900, 0.100 s faster". */
  text: string;
}

/** The F1 25 Time Trial rival from EA's leaderboard (UDP packet 14): spec-decoded until a recording shows it. */
export interface EaRivalRow {
  kind: "ea_rival";
  lap_ms: number;
  label: string;
  caveat: string;
  banded: true;
  sectors_ms: [number | null, number | null, number | null];
  assists: { traction_control: boolean | null; anti_lock_brakes: boolean | null; gearbox_assist: boolean | null };
  /** "Traction control off, ABS on, Gearbox assist off". */
  assists_text: string;
  equal_performance: boolean | null;
  custom_setup: boolean | null;
  valid: true;
  car_name: string | null;
  seen_unix: number;
  date_text: string | null;
  session_id: string;
  evidence: string;
  evidence_level: string;
}

/** A real Formula 1 time (F1DB). */
export interface RealF1Time {
  time_ms: number;
  time_text: string;
  year: number;
  date: string;
  driver: string;
  grand_prix: string;
  session: "race" | "qualifying";
  lap: number | null;
}

export interface RealF1Source {
  name: string;
  version: string;
  released: string;
  url: string;
  release_url: string;
  licence: string;
  licence_url: string;
  attribution: string;
}

/** A real car's pole (F1DB, CC BY 4.0): always shown with its caveat and the linked credit. */
export interface RealF1Row {
  kind: "real_f1";
  lap_ms: number;
  /** "Real F1 pole 2025 · Lando Norris". */
  label: string;
  caveat: string;
  banded: boolean;
  what: "pole";
  what_text: string;
  time_text: string;
  year: number;
  date: string;
  driver: string;
  grand_prix: string;
  season: number;
  generation: CarGeneration;
  generation_chosen: boolean;
  band_note: string | null;
  race_fastest_lap: RealF1Time | null;
  lap_record: (RealF1Time & { label: string }) | null;
  layout: { f1db_layout_id: string; layout_length_m: number; game_length_m: number };
  source: RealF1Source | null;
}

export interface BoardEvidence {
  track_limits_checked: boolean;
  note: string | null;
  counts: string;
}

/** `GET /api/leaderboard`. Nothing matched a field query: key, fields, labels, record and evidence are null. */
export interface LeaderboardBoard {
  key: string | null;
  fields: BoardFields | null;
  labels: BoardLabels | null;
  rows: BoardRow[];
  no_time: { driver_id: number; driver_name: string }[];
  record: BoardRecord | null;
  history: RecordHistoryEntry[];
  evidence: BoardEvidence | null;
  ea_rival: EaRivalRow | null;
  real_f1: RealF1Row | null;
  real_f1_note: string | null;
  real_f1_asks_generation: boolean;
  boards_here: RecordsIndexRow[];
  matched: number;
}

/** `GET /api/records`. */
export interface RecordsIndex {
  boards: RecordsIndexRow[];
  count: number;
}

// ------------------------------------------------------------------------------------------------ queries

/** A board by its key, or by fields (`game` + `track_id` always; an unset field means any, `?` the unknown bucket). */
export type BoardQuery =
  | { key: string; car_generation?: CarGeneration | null }
  | {
      key?: undefined;
      game: string;
      track_id: string;
      length_m?: number | null;
      car_id?: string | null;
      car_class?: string | null;
      equal_performance?: string | null;
      category?: string | null;
      conditions?: string | null;
      assists?: string | null;
      car_generation?: CarGeneration | null;
    };

export interface RecordsQuery {
  game?: string | null;
  track_id?: string | null;
  driver_id?: number | null;
  car_generation?: CarGeneration | null;
}

function qs(p: Record<string, string | number | null | undefined>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(p)) if (v != null && v !== "") u.set(k, String(v));
  const s = u.toString();
  return s ? `?${s}` : "";
}

/** `/api/leaderboard?…`: the key alone, or the fields that are set (each with the optional `car_generation`). */
export function leaderboardUrl(q: BoardQuery): string {
  if (q.key != null) return `/api/leaderboard${qs({ key: q.key, car_generation: q.car_generation })}`;
  return `/api/leaderboard${qs({
    game: q.game,
    track_id: q.track_id,
    length_m: q.length_m,
    car_id: q.car_id,
    car_class: q.car_class,
    equal_performance: q.equal_performance,
    category: q.category,
    conditions: q.conditions,
    assists: q.assists,
    car_generation: q.car_generation,
  })}`;
}

/** `/api/records?…` (only the parts that are set). */
export function recordsUrl(q: RecordsQuery = {}): string {
  return `/api/records${qs({ game: q.game, track_id: q.track_id, driver_id: q.driver_id, car_generation: q.car_generation })}`;
}

export const leaderboardKeys = {
  board: (q: BoardQuery) => `driver-sessions:leaderboard:${leaderboardUrl(q)}`,
  records: (q: RecordsQuery) => `driver-sessions:records:${recordsUrl(q)}`,
} as const;

async function req<T>(path: string): Promise<T> {
  const r = await authFetch(path);
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

export const leaderboardApi = {
  /** One board (422: a key or field that does not parse; an older server without boards answers 404, see
   * `isMissingRoute`). */
  board: (q: BoardQuery) => req<LeaderboardBoard>(leaderboardUrl(q)),
  /** Every board with its record (optionally one game / track, or the boards where a driver has a lap). */
  records: (q: RecordsQuery = {}) => req<RecordsIndex>(recordsUrl(q)),
};
