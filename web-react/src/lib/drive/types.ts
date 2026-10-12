// Drive logic types (docs/ui/design-spec.md v2, 4.10). Pure types: what the live snapshot carries today plus the
// backend additions D1-D6 (13). Every addition is optional: absent or null = unknown, never guessed.
//
// Wire facts checked against the live API (GET /api/live?static=true) and headless replays of real captures
// (src/test/fixtures/recorded-*.json):
//  * track_model.corners[] carry the official identity (label, display_name, identity_tier) from the verified
//    track sheets; `name` is the learned name ("T7"), the key cues and observations use.
//  * observations carry corner_label / corner_voice (official), metric and consistency_ratio.
//  * events[] are the last 10 game events of ANY car (the server keeps AI-vs-AI collisions and penalties too).
//  * skeleton.marshal_zones[].flag is the flag at the last static push (every 5 s): live flags are marshal_flags.

import type { Corner, Frame, LapSummary, Observation, Snapshot, TrackModel } from "../api";
import type { CarFamily, SessionCarFields } from "../carclass";
import type { LiveAiPace } from "../endpoints/review";
import type { StrategyView } from "../strategy/types"; // race strategy (pitwall.strategy)
import type { RaceView } from "../raceradio/types"; // race radio (pitwall.raceradio)
import type { CarHealthView, RacecraftView } from "../carhealth/types"; // health lane (pitwall.carhealth)

export type { LiveAiPace };
import type { CoachrefBlock, ReferenceDescriptor } from "../endpoints/coachref";

/** One timing scope's bests (D2, storage/repo.py lap_bests): lap and the three sectors, clean laps only, each
 * sector best on its own. The ids say which lap set each best. */
export interface Bests {
  lap_ms: number | null;
  sectors_ms: [number | null, number | null, number | null];
  lap_id?: number | null;
  sector_lap_ids?: [number | null, number | null, number | null];
  session_id?: string | null;
}

/** One planned cue (coach/cues.py CueSpec.to_dict). `target_m` is in game lap metres (the cue engine fires on
 * frame.lap_distance_m). */
export interface CuePlanEntry {
  corner: string;
  kind: "brake" | "marker";
  target_m: number;
  text: string;
  focus: boolean;
  reason: string;
}

/** coach/cues.py CueEngine.snapshot() - exists today. */
export interface CueSnapshot {
  mode: "off" | "focus" | "markers" | "all";
  armed: boolean;
  /** Why calls are paused ("safety car", "radio off", "no radio connected", ...), or null. */
  muted: string | null;
  /** Why there is no plan of the driver's own ("no reference lap yet", ...), or null. While the AI field stands in
   * (coach/cues.py CueEngine._with_fallback) it reads "AI field heads-ups (<why>)". */
  reason: string | null;
  /** Proposed (INTEGRATION NEEDED, lane B): whose plan this is. "field" = the AI field's "heavy braking ahead"
   * heads-ups (an AI reference, never the driver's target); absent = unknown, the reason prefix decides. */
  source?: "reference" | "field" | null;
  ref_lap_number: number | null;
  /** The driver's focus corners (learned names). In an AI field plan: the heads-ups' keys by priority ("T3"
   * learned, "F2" field corner, "zone@1234"), never the driver's focus (cues.ts driverFocus). */
  focus: string[];
  cues: CuePlanEntry[];
  next: { corner: string; text: string; kind: "brake" | "marker"; in_m: number } | null;
  last: {
    corner: string;
    text: string;
    status?: "pending" | "sent" | "dropped";
    reason?: string | null;
    /** Where the key word was heard vs the aim point (m, + = late). */
    error_m?: number | null;
    age_s?: number | null;
  } | null;
  timing: { latency_ms: number; path: string; margin_m: number };
  focus_limits?: Record<string, unknown>;
  stats?: Record<string, number>;
  /** coachref: the drill corner (learned name) while a drill runs: the plan holds only that corner. */
  drill_corner?: string | null;
}

/** Official identity of a learned corner (analysis/track_identity.py via track_model_payload). */
export interface CornerIdentity {
  label?: string | null;
  display_name?: string | null;
  /** "sheet_verified" | "sheet_seeded" | null */
  identity_tier?: string | null;
  official_numbers?: number[];
  voice_ok?: boolean;
  label_part?: string | null;
  identity_match?: string | null;
}

export type CornerNext = Corner & CornerIdentity;

export interface TrackModelNext extends TrackModel {
  corners: CornerNext[];
  /** F2 support: the family of the laps the model was built from; null = a model from before families (unknown). */
  car_family?: CarFamily | null;
  /** F2 support: false when this class has no model of its own here yet and another family's stands in (Drive says
   * "Corners from F1 laps until your first clean F2 lap here."); null for non-F1 games. */
  car_family_match?: boolean | null;
}

/** snapshot.session plus (F2 support) the car class, the car and the session in words (lib/carclass.ts). */
export type SessionNext = NonNullable<Snapshot["session"]> & SessionCarFields;

/** An observation as the live payload sends it, plus D6's glance texts. */
export type ObservationNext = Observation & {
  /** D6 blocks: the radio picked this point for the lap. */
  picked?: boolean;
  /** D6: one idea in plain words (simple-wording profiles). */
  text_simple?: string | null;
  /** D6: <= 48 characters, for glance use on track. */
  short?: string | null;
  corner_label?: string | null;
  corner_voice?: string | null;
  metric?: string;
  consistency_ratio?: number | null;
  /** coachref: the other driver's name when the point compares with their lap; null / absent = your own. */
  ref_name?: string | null;
  /** coachref: a drill attempt's point (kind "drill"). */
  drill?: { id: number; attempt: number; of: number; hits: number; outcome: string; done: boolean } | null;
};

/** One game event as /ws/live sends it. `player` is a proposed addition (INTEGRATION NEEDED): whether the event
 * concerns the player's car; absent = unknown. */
export interface LiveEvent {
  kind: string;
  code: string | null;
  session_time_s: number | null;
  /** Server wall clock (unix seconds) when the event was ingested. */
  t: number;
  player?: boolean | null;
}

/** D3: F1's driver status. */
export type DriverStatus = "in_garage" | "out_lap" | "in_lap" | "flying_lap" | "on_track";

export type FrameNext = Frame & {
  /** D1: [S1, S2] of the lap in progress (null until each completes); null for games that do not send them. */
  current_lap_sector_ms?: [number | null, number | null] | null;
  /** D3 */
  driver_status?: DriverStatus | null;
  /** model/telemetry.py FrameQuality bits (PAUSED 1<<2, REPLAY_OR_SPECTATING 1<<3, NOT_RACING 1<<6). */
  quality?: number | null;
  /** F2 support: CarStatus m_drsAllowed (EA spec 5.7); null = no CarStatus yet, or a game without DRS. */
  drs_allowed?: boolean | null;
  /** F2 support: metres until DRS is available (m_drsActivationDistance when above 0); null when 0 or unknown. */
  drs_activation_m?: number | null;
  // --- health lane (pitwall.carhealth) ---
  /** F1 CarTelemetry engineTemperature (°C); absent on older servers, null for games that do not send it. */
  engine_temp_c?: number | null;
  // --- end health lane ---
};

/** D6 (coach/selection.py coach_block): what the radio picks for the latest compared lap under the seated
 * driver's limits, and per corner the point the coach card shows. Observations are slim copies. */
export interface CoachBlock {
  lap_number: number;
  lap_id?: number | null;
  ref_lap_number?: number | null;
  skill_level?: string | null;
  /** The seated driver's profile wants text_simple. */
  simple_wording?: boolean;
  /** The driver's radio is on quiet: the screen shows the points, the radio says none. */
  radio_quiet?: boolean;
  picked: ObservationNext[];
  by_corner: Record<string, ObservationNext>;
  /** coachref: a drill is running: the radio and the coach card talk about the drill corner only. */
  drill_only?: boolean;
}

/** D2 (storage/repo.py lap_bests): this game + track + car + layout; driver / household are null in synthetic
 * and replayed sessions (scope.records false) and while the car is unknown. */
export interface BestsBlock {
  scope?: { game: string | null; track_id: string | null; car_id: string | null; records: boolean };
  session: Bests;
  driver: (Bests & { set_unix: number | null }) | null;
  household: (Bests & { driver_id: number | null; set_unix?: number | null }) | null;
}

/** D4 detail: what set the state and whether the chequered flag has been shown since the last (re)start. */
export interface SessionStateInfo {
  state: "running" | "ended" | "red_flag";
  /** Event kind that set the state; null = the session's start. */
  cause: string | null;
  since_unix: number;
  chequered_flag: boolean;
}

/** core/live.py lap_totals: the whole session's lap counts (``laps`` holds only the newest 20). */
export interface LapTotals {
  laps: number;
  clean: number;
  not_clean: number;
  first_clean_ms: number | null;
  best_clean_ms: number | null;
  /** The distinct flags of the laps that did not count ("out_lap", "pit_in"). */
  not_clean_flags?: string[];
  /** A lap was invalid without the "invalid" flag. */
  not_clean_invalid?: boolean;
  /** A lap did not count for no stated reason. */
  not_clean_other?: boolean;
}

export interface SnapshotNext extends Snapshot {
  /** F2 support: + car_class, car_label, session_label (all optional). ERS is null in every F2 frame (no ERS). */
  session: SessionNext | null;
  frame: FrameNext | null;
  track_model?: TrackModelNext | null;
  observations: ObservationNext[];
  events: LiveEvent[];
  laps: LapSummary[];
  /** The session's counts over every lap; absent on older servers (then counted from ``laps``). A kept key
   * (lib/live.ts STATIC_KEYS): sent when it changed. */
  lap_totals?: LapTotals | null;
  cues?: CueSnapshot;
  /** D2 */
  bests?: BestsBlock | null;
  /** D4 */
  session_state?: "running" | "ended" | "red_flag" | null;
  /** D4 */
  session_state_info?: SessionStateInfo | null;
  /** D6 */
  coach?: CoachBlock | null;
  /** AI pace: this session against the AI (null until the analysis worker has a summary, and for games without AI
   * difficulty). Its `session_id` says which session it belongs to. A kept key (lib/live.ts STATIC_KEYS): sent when
   * it changed or with the static payload. */
  ai_pace?: LiveAiPace | null;
  // --- race strategy (pitwall.strategy) ---
  /** strategy/view.py StrategyView (lib/strategy/types.ts); absent on servers without the strategy engine. A static
   * key (lib/live.ts STATIC_KEYS): /ws/live sends it when it changed or with the static payload, null = none. Read it
   * through lib/strategy/view.ts snapStrategy(), which ignores unknown versions. */
  strategy?: StrategyView | null;
  // --- end race strategy ---
  // --- race radio (pitwall.raceradio) ---
  /** raceradio/model.py RaceView (lib/raceradio/types.ts); absent on servers without race radio. A kept key
   * (lib/live.ts STATIC_KEYS): /ws/live sends it when it changed (at most every 0.5 s, at once after a call) or with
   * the static payload, null = none. Read it through lib/raceradio/view.ts snapRace(), which ignores unknown versions. */
  race?: RaceView | null;
  // --- end race radio ---
  // --- health lane (pitwall.carhealth) ---
  /** carhealth/view.py CarHealthView (lib/carhealth/types.ts); absent on servers without the car-health worker. A
   * static key (lib/live.ts STATIC_KEYS): sent when it changed or with the static payload, null = none. Read it
   * through lib/carhealth/view.ts snapCarHealth(), which ignores unknown versions and other sessions. */
  car_health?: CarHealthView | null;
  /** carhealth/racecraft.py RacecraftView: attack / defend per corner against the cars directly ahead and behind
   * (F1 races; positions and corners only, no names). A static key like car_health. */
  racecraft?: RacecraftView | null;
  // --- end health lane ---
  /** coachref: the reference with its descriptor (who, which kind, labels); the four legacy keys are unchanged. */
  reference: LiveReference | null;
  /** coachref: the seated driver's reference choice and drill. Absent = a server without coachref. A kept key
   * (lib/live.ts STATIC_KEYS): sent when it changed or with the static payload. */
  coachref?: CoachrefBlock | null;
}

/** snapshot.reference: the legacy summary plus the coachref descriptor (every addition optional: older servers). */
export type LiveReference = NonNullable<Snapshot["reference"]> &
  Partial<Omit<ReferenceDescriptor, "lap_id" | "lap_number" | "lap_time_ms" | "session_id">>;

/** Drive lock setting (Settings > Display; lib/prefs.ts DriveLock, lane S). */
export type DriveLockSetting = "off" | "beginners" | "everyone";

/** The subset of the per-device preferences Drive logic reads (lib/prefs.ts Prefs is assignable to it). */
export interface DrivePrefs {
  driveLock?: DriveLockSetting;
}

/** Provenance a fixture carries (src/test/fixtures); never part of the wire format. */
export interface FixtureMeta {
  tier: "recorded" | "synthetic" | "edited" | "pipeline";
  source: string;
  moment: string;
  trimmed?: string[];
  edits?: string[];
  notes?: string;
}

export type FixtureSnapshot = SnapshotNext & { _fixture?: FixtureMeta };
