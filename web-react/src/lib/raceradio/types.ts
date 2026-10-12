// Race radio (lane "radio"): the JSON contract of `pitwall/raceradio` as the dashboard reads it. A TypeScript mirror of
// the backend's RaceView (raceradio/model.py, version 1): `snapshot["race"]` on /ws/live and GET /api/race/live, and
// the per-driver race-radio preferences (drivers.py `radio_calls`, `radio_wording`). Pure types.
//
// Honesty rules carried by the contract (CLAUDE.md "unknown stays unknown"): every value is null when the engine does
// not know it, never 0 or a guess. `position_tier` is the adapter's evidence level for the race position and
// `position_note` the backend's own words about it (GT7 and Forza: not yet checked against the game's screen): the
// dashboard shows them, it never composes a reason. Call texts are the backend's, verbatim, and never carry a
// personal (online) name: proactive calls only say official AI driver names, a team, "car 23" or "the car ahead".

/** "race": race calls on; "session": practice / qualifying (blue flags for a car on a fast lap, minutes left);
 * "off": a mode or game without race radio (`reason` says why). */
export type RaceMode = "race" | "session" | "off";

/** The adapter's FieldSupport level for `race_position` (capabilities.py SupportStatus values). */
export type PositionTier = "spec_implemented" | "recorded_validated" | "community_documented" | "live_validated";

/** What the track shows: race control's state (F1 SessionInfo.safety_car_status, SCAR, RDFL). */
export type TrackFlag = "green" | "sc" | "vsc" | "red" | "formation";

/** The player's own car flag (F1 CarStatus `m_vehicleFIAFlags`): blue means "let the car behind through", never a
 * marshal zone that shows blue because some car is being lapped there. */
export type YourFlag = "none" | "green" | "blue" | "yellow";

/** The groups a driver can switch off (drivers.py RadioCallPrefs). `name` is "say my name sometimes"; the red flag
 * ignores every toggle. */
export type RaceCallGroup = "flags" | "start" | "position" | "rivals" | "penalties" | "damage";
export type RadioCallGroup = RaceCallGroup | "name";

/** Per-driver toggles: all true by default. */
export type RadioCallPrefs = Record<RadioCallGroup, boolean>;

/** "auto": simple words for beginners (the skill level decides); "simple" / "standard": forced. Also switches the
 * coaching and strategy wording (drivers.py coaching_limits). */
export type RadioWording = "auto" | "simple" | "standard";

/** The nearest yellow zone ahead of the car (race radio's own rule: 150 m to 10 s ahead, never one behind). */
export interface YellowAhead {
  zone: number | null;
  ahead_m: number | null;
  /** The corner name the call says ("T9"), or null. */
  corner: string | null;
}

export interface RaceFlags {
  track: TrackFlag | null;
  you: YourFlag | null;
  yellow_ahead: YellowAhead | null;
}

/** The player's penalties and warnings (F1 LapData); unknown counts are null. */
export interface RacePenalties {
  time_s: number | null;
  warnings: number | null;
  track_limits: number | null;
  drive_throughs: number | null;
  stop_gos: number | null;
  serve_at_stop: boolean | null;
}

export type DamageGrade = "none" | "minor" | "major" | "severe";
export type Wheel = "FL" | "FR" | "RL" | "RR";

export interface DamagePart {
  /** "front_left_wing", "front_right_wing", "rear_wing", "floor", "diffuser", "sidepod", "brakes_FL", ... */
  part: string;
  pct: number | null;
  grade: DamageGrade;
}

export interface RaceDamage {
  grade: DamageGrade | null;
  parts: DamagePart[];
  /** Wheels with a puncture (FL, FR, RL, RR order). */
  puncture: Wheel[];
}

/** How a neighbour is named: an official AI driver name, a team, a race number, or just "the car ahead". */
export type LabelKind = "driver" | "team" | "number" | "car";

export interface RaceNeighbour {
  label: string | null;
  label_kind: LabelKind | null;
  position: number | null;
  gap_s: number | null;
  /** false while the gap is in doubt (a position change, a car in the pit lane). */
  settled: boolean | null;
}

/** One proactive call as the snapshot keeps it (the last 3). */
export interface RaceCallView {
  t_unix: number;
  group: RaceCallGroup | string;
  /** "yellow_ahead", "penalty", "position_change", ... */
  call: string;
  /** The backend's words, verbatim. */
  text: string;
}

/** `snapshot["race"]` and GET /api/race/live (raceradio/model.py RaceView, version 1; at most 1.2 kB). */
export interface RaceView {
  version: 1;
  session_id: string | null;
  game: string | null;
  mode: RaceMode;
  /** Why the mode is off ("GT7 sends a race position only in races", "no live session"), else null. */
  reason: string | null;
  synthetic: boolean;
  position: number | null;
  cars: number | null;
  grid_position: number | null;
  position_tier: PositionTier | null;
  /** The backend's words on the position's evidence (GT7, Forza), else null. Shown as written. */
  position_note: string | null;
  lap: number | null;
  total_laps: number | null;
  laps_left: number | null;
  final_lap: boolean | null;
  time_left_s: number | null;
  flags: RaceFlags | null;
  penalties: RacePenalties | null;
  damage: RaceDamage | null;
  ahead: RaceNeighbour | null;
  behind: RaceNeighbour | null;
  calls: RaceCallView[];
}

/** GET/PUT /api/race/settings (household, P2): say online players' names in "who's ahead?" answers. */
export interface RaceSettings {
  online_names: boolean;
}

/** Provenance a race-radio fixture carries (src/test/fixtures/raceradio); never part of the wire format. */
export interface RaceFixtureMeta {
  tier: "recorded" | "synthetic" | "edited";
  source: string;
  moment: string;
  edits?: string[];
  notes?: string;
}
