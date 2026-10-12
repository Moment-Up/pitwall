// F1 spotter wire types (lane "F1 spotter"; design spec sections 8.1-8.4). Pure types mirroring the server:
//   * SpotterBlock      the `spotter` block of every /ws/live and /api/live snapshot (core/live.py snapshot(), set by
//                       spotter/worker.py on every Motion packet; null when there is no F1 session)
//   * SpotterInfo       GET /api/spotter (api/routes_spotter.py), also the answer of PUT /api/spotter/settings
//   * SpotterSettings   the "spotter" settings section (spotter/settings.py validates it)
//   * SpotterCallKind   meta.spotter of a radio `say` frame of kind "spotter" (docs/voice-protocol.md)
//
// Unknown stays unknown: every number the server may not have yet is `number | null`; parsers in
// lib/endpoints/spotter.ts and lib/spotter/view.ts turn anything malformed into null, never into a guess.
//
// The spotter is F1 25 only (formats 2025 and 2026): other games send the player's car alone. Evidence tier:
// recorded-tested on the owner's PS5 races, NOT live-validated (docs/status.md). Nothing here calls an LLM.

/** What one side of the car looks like right now (spec 3.4, no onset debounce: the iPad is instant). */
export type SpotterSideState = "clear" | "alongside" | "close";

export interface SpotterSide {
  state: SpotterSideState;
  /** Nearest member's longitudinal offset in metres, + = the other car is ahead; null when clear. Rounded to 0.1. */
  lon_m: number | null;
  /** Nearest member's body-side-to-body-side gap in metres; null when clear. Rounded to 0.1. */
  gap_m: number | null;
  /** Cars alongside on this side. */
  cars: number;
}

/**
 * Why the spotter is silent: the first closed gate (spec 3.6), in gate order. A newer server may add reasons; the
 * view treats any other string as "inactive" and never shows it raw.
 */
export type SpotterReason =
  | "disabled"
  | "not_available"
  | "session_type"
  | "red_flag"
  | "safety_car"
  | "start"
  | "paused"
  | "stale"
  | "flashback"
  | "pit"
  | "finished"
  | "slow";

export const SPOTTER_REASONS: readonly SpotterReason[] = [
  "disabled",
  "not_available",
  "session_type",
  "red_flag",
  "safety_car",
  "start",
  "paused",
  "stale",
  "flashback",
  "pit",
  "finished",
  "slow",
];

/** The live snapshot's `spotter` block (spec 8.3), version 1. */
export interface SpotterBlock {
  v: 1;
  /** settings.enabled && settings.visual: the iPad bars are wanted. */
  enabled: boolean;
  /** Every gate is open (a race in progress, green flag, the player on track and moving). */
  active: boolean;
  /** The first closed gate while inactive; null while active. */
  reason: SpotterReason | null;
  left: SpotterSide;
  right: SpotterSide;
  three_wide: boolean;
  /** Any side occupied, or cleared less than 1 s ago (proactive radio waits while true). */
  traffic: boolean;
  /** Measured Motion packet rate; null until measured. */
  rate_hz: number | null;
  /** The worker's publish counter. The bars do NOT rely on it for freshness (they time each snapshot's arrival). */
  seq: number;
  /** The car length the engine uses (spotter/dims.py per formula, or the settings override; added to spec 8.3 at
   * integration). Absent (an older server) = the F1 default. */
  length_m?: number | null;
}

/** Call ids (spec 5.5). `still_there` carries its side in `side`. */
export type SpotterCallKind =
  | "car_left"
  | "car_right"
  | "clear_left"
  | "clear_right"
  | "three_wide"
  | "clear_all_round"
  | "still_there"
  | "hold_your_line";

export const SPOTTER_CALL_KINDS: readonly SpotterCallKind[] = [
  "car_left",
  "car_right",
  "clear_left",
  "clear_right",
  "three_wide",
  "clear_all_round",
  "still_there",
  "hold_your_line",
];

export type SpotterWording = "auto" | "standard" | "simple";

/** Settings section "spotter" (spec 8.1). Defaults: everything as below, master OFF. */
export interface SpotterSettings {
  enabled: boolean;
  /** Spoken calls (the radio). */
  audio: boolean;
  /** iPad bars on Drive. */
  visual: boolean;
  qualifying: boolean;
  practice: boolean;
  /** 0-20 s after lights out (default 5). */
  start_delay_s: number;
  wording: SpotterWording;
  /** null = the engineer's voice; else a Kokoro voice id (only with the Kokoro engine). */
  voice: string | null;
  still_there: boolean;
  hold_your_line: boolean;
  /** Advanced override, 3.0-7.0 m; null = per formula. */
  car_length_m: number | null;
  /** Advanced override, 1.5-2.5 m; null = per formula. */
  car_width_m: number | null;
}

export const SPOTTER_DEFAULTS: Readonly<SpotterSettings> = Object.freeze({
  enabled: false,
  audio: true,
  visual: true,
  qualifying: false,
  practice: false,
  start_delay_s: 5,
  wording: "auto",
  voice: null,
  still_there: true,
  hold_your_line: true,
  car_length_m: null,
  car_width_m: null,
});

export const START_DELAY_MIN_S = 0;
export const START_DELAY_MAX_S = 20;

export type SpotterAvailabilityReason = "game_not_supported" | "no_motion";

export interface SpotterAvailability {
  available: boolean;
  /** The adapter game ("f1_25"), or null when no game is known. */
  game: string | null;
  reason: SpotterAvailabilityReason | null;
}

export interface SpotterDims {
  length_m: number | null;
  width_m: number | null;
  /** "F1 World", "F2", ... or null. */
  formula: string | null;
  /** "regs" (published figures), "settings" (the override), or what a newer server says. */
  source: string | null;
}

export interface SpotterAudio {
  ready: boolean;
  engine: string | null;
  voice: string | null;
  phrases: number | null;
  unverified: number;
  fallback: number;
  /** Trimmed clip length per phrase id, seconds. */
  clip_s: Record<string, number>;
}

export interface SpotterStatus {
  active: boolean;
  reason: SpotterReason | null;
  motion_hz: number | null;
  send_rate_low: boolean;
  dims: SpotterDims | null;
  audio: SpotterAudio | null;
}

/** p50 / p95 / max of one latency ring (ms); null where the ring is empty. */
export interface LatencyStat {
  p50: number | null;
  p95: number | null;
  max: number | null;
}

export interface SpotterLatency {
  n: number;
  decide_ms: LatencyStat | null;
  queued_ms: LatencyStat | null;
  started_ms: LatencyStat | null;
  onset_game_ms: LatencyStat | null;
  data_age_ms: LatencyStat | null;
}

export interface SpotterCounters {
  calls: Record<string, number>;
  suppressed_short: number;
  dropped: Record<string, number>;
  items: number;
  skipped: number;
  invalid: number;
  errors: number;
}

export interface SpotterRecentCall {
  t_unix: number | null;
  kind: string;
  /** The side a call concerns ("still_there", "hold_your_line" carry it); null when none or unknown. */
  side: "left" | "right" | null;
  /** Played on at least one radio. */
  spoken: boolean;
  queued_ms: number | null;
  started_ms: number | null;
}

/** GET /api/spotter (spec 8.2), version 1. */
export interface SpotterInfo {
  v: 1;
  settings: SpotterSettings;
  availability: SpotterAvailability;
  status: SpotterStatus;
  latency: SpotterLatency;
  counters: SpotterCounters;
  /** The last 20 calls, newest first (sorted by time on parsing: the order on the wire is not relied on). */
  recent: SpotterRecentCall[];
}
