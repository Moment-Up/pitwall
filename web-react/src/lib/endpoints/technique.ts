// Technique endpoints (feat/technique, design spec "Technique analysis and setup engineer" §6): typed client for
// /api/technique/* (src/pitwall/api/routes_technique.py). Racing line against the driver's own reference lap, brake
// and throttle technique per corner, handling balance from tyre slip at the limit, and one-parameter setup
// suggestions for F1 25 that feed the existing experiments flow.
//
// The shapes are the spec's JSON contract, verbatim. Every number arrives rounded (m 0.01, deg 0.1, s 0.01,
// fractions 0.01) and NaN arrives as null: unknown stays unknown, and the UI shows "-".
//
// Cache keys (lib/cache.ts). Session-level results sit under "analysis:<id>" so a completed lap of the live session
// refreshes them with the analysis (hooks/useApi.ts); a comparison of two stored laps only changes when the track model
// grows, so it lives under its own prefix with a minute's freshness (data hooks in pages/review/session/technique):
//   techniqueKeys.session(id, ref)   GET /api/technique/sessions/{id}?ref_lap_id=
//   techniqueKeys.balance(id, fmt)   GET /api/technique/sessions/{id}/balance?car_format=  (the Setup page's car format:
//                                    the driver's choice sizes suggestions when the game's generic car hides it)
//   techniqueKeys.compare(ref, lap)  GET /api/technique/compare?ref=&lap=

import { ApiError } from "../api";
import { authFetch } from "../auth";
import type { CarFormat, ExperimentComparison } from "./carsetup";

export type LinePointKey = "turn_in" | "apex" | "track_out";
export type Phase = "entry" | "mid" | "exit";
export type BalanceClass = "understeer" | "neutral" | "oversteer";
export type SpeedClass = "slow" | "medium" | "fast";
export type SlipStatus = "measured" | "abs_on" | "no_data" | "not_applicable";
export type ReleaseShape = "step" | "steady" | "drop_then_trail" | "late_drop";
export type Wheel = "fl" | "fr" | "rl" | "rr";

export const LINE_POINTS: readonly LinePointKey[] = ["turn_in", "apex", "track_out"];
export const PHASES: readonly Phase[] = ["entry", "mid", "exit"];

export interface Availability {
  ok: boolean;
  reason: string | null;
  note: string | null;
}

export interface TechniqueAvailability {
  line: Availability;
  inputs: Availability;
  slip: Availability;
  balance: Availability;
  setup: Availability;
}

export interface PedalInfo {
  pedals: "csl" | "csl_load_cell" | null;
  label: string | null;
  brake_sensor: "hall_position" | "load_cell" | null;
  peak_tol: number;
  time_tol_s: number;
  changed_since_reference: boolean | null;
  note: string;
}

export interface AssistInfo {
  abs: boolean | null;
  traction_control: number | null;
  braking_assist: number | null;
  notes: string[];
}

export interface ThresholdInfo {
  key: string;
  value: number;
  unit: string;
  heuristic: boolean;
  text: string;
  /** The sheet's heading (servers before the review fix send none: "other"). */
  group?: "line" | "inputs" | "slip" | "balance" | "pedals" | "other";
}

export interface SlipEvents {
  status: SlipStatus;
  events: number | null;
  total_s: number | null;
  peak_slip: number | null;
  wheels: Wheel[];
  at_m: number[];
  tc_level: number | null;
}

export interface CornerInputs {
  braked: boolean;
  brake_start_m: number | null;
  brake_peak: number | null;
  time_to_peak_s: number | null;
  peak_hold_s: number | null;
  release_s: number | null;
  release_shape: ReleaseShape | null;
  brake_at_turn_in: number | null;
  brake_at_apex: number | null;
  trail_overlap_s: number | null;
  coast_s: number | null;
  coast_m: number | null;
  pickup_m: number | null;
  pickup_vs_apex_m: number | null;
  full_throttle_m: number | null;
  throttle_ramp_s: number | null;
  throttle_lifts: number | null;
  lockup: SlipEvents;
  wheelspin: SlipEvents;
}

export type NoteMetric =
  | "brake_peak"
  | "time_to_peak"
  | "release"
  | "brake_at_turn_in"
  | "trail_overlap"
  | "coast"
  | "throttle_pickup"
  | "throttle_ramp"
  | "throttle_lifts"
  | "lockup"
  | "wheelspin";

export interface TechniqueNote {
  metric: NoteMetric;
  lap_value: number | null;
  ref_value: number | null;
  delta: number | null;
  unit: string;
  notable: boolean;
  muted: boolean;
  laps: number | null;
  laps_total: number | null;
  text: string;
  text_simple: string;
}

export interface PhaseBalance {
  cls: BalanceClass | null;
  slip_diff_deg: number | null;
  body_slip_max_deg: number | null;
  slide: boolean;
  samples: number;
}

export interface PhaseSummary {
  laps: number;
  understeer: number;
  neutral: number;
  oversteer: number;
  median_slip_diff_deg: number | null;
  slides: number;
  recurring: BalanceClass | null;
  best_lap: BalanceClass | null;
  verdict: "car" | "driving" | null;
}

export type PhaseRecord<T> = Record<Phase, T>;

export interface LapCornerTechnique {
  lap_id: number;
  lap_number: number;
  clean: boolean;
  incident: boolean;
  time_delta_s: number | null;
  line: Record<LinePointKey, number | null> | null;
  inputs: CornerInputs | null;
  notes: TechniqueNote[];
  balance: PhaseRecord<PhaseBalance | null> | null;
}

export interface LinePointSummary {
  median_offset_m: number | null;
  laps: number;
  laps_wider: number;
  laps_tighter: number;
}

export type XZ = [number, number];

export interface CornerLineSummary {
  inside_known: boolean;
  points: Record<LinePointKey, LinePointSummary | null>;
  view: { lap_id: number; lap_number: number; ref_xz: (XZ | null)[]; lap_xz: (XZ | null)[] } | null;
}

export interface TechniqueCorner {
  /** The learned corner name (the key of analyses, observations and corner_summary). */
  corner: string;
  /** Official short label ("T3"), when the track sheet maps this corner. */
  label: string | null;
  /** Official name ("Stowe"). */
  name: string | null;
  direction: "left" | "right" | null;
  /** Game lap metres (the reference's slowest point). */
  apex_m: number;
  speed_class: SpeedClass | null;
  ref_min_speed_kph: number | null;
  /** Game lap metres of the reference's turn-in, apex and track-out. */
  points: Record<LinePointKey, number | null>;
  ref: { inputs: CornerInputs | null; balance: PhaseRecord<PhaseBalance | null> | null };
  laps: LapCornerTechnique[];
  line: CornerLineSummary | null;
  balance: PhaseRecord<PhaseSummary> | null;
  habits: TechniqueNote[];
}

export interface BalanceSymptom {
  id: string;
  phase: Phase;
  cls: "understeer" | "oversteer";
  verdict: "car" | "driving";
  speed_class: SpeedClass | "mixed";
  corners: string[];
  corner_labels: string[];
  laps: number;
  laps_total: number;
  median_slip_diff_deg: number;
  with_braking: boolean;
  with_wheelspin: boolean;
  text: string;
  text_simple: string;
}

export interface SetupSuggestion {
  symptom_id: string;
  rank: number;
  parameter: string;
  label: string;
  unit: string | null;
  direction: "higher" | "lower";
  from_value: number | null;
  to_value: number | null;
  steps: number;
  effect: string;
  why: string;
  hypothesis: string;
  blocked: string | null;
}

export interface SetupEngineer {
  car_format: "f1_2025" | "f1_2026" | null;
  setup_known: boolean;
  suggestions: SetupSuggestion[];
  caveat: string;
  note: string | null;
}

export interface TechniqueLap {
  lap_id: number;
  lap_number: number;
  clean: boolean;
  usable: boolean;
  reason: string | null;
}

/** GET /api/technique/sessions/{sid}?ref_lap_id= */
export interface TechniqueSession {
  session_id: string;
  game: string;
  synthetic: boolean;
  source: string;
  ref_lap_id: number | null;
  ref_lap_number: number | null;
  ref_session_id: string | null;
  available: TechniqueAvailability;
  pedals: PedalInfo;
  assists: AssistInfo;
  laps: TechniqueLap[];
  corners: TechniqueCorner[];
  symptoms: BalanceSymptom[];
  setup: SetupEngineer | null;
  thresholds: ThresholdInfo[];
}

/** GET /api/technique/sessions/{sid}/balance */
export interface TechniqueBalance {
  session_id: string;
  symptoms: BalanceSymptom[];
  setup: SetupEngineer | null;
  available: TechniqueAvailability;
  assists: AssistInfo;
}

export interface LineMarker {
  corner: string;
  label: string | null;
  point: LinePointKey;
  d_m: number;
  offset_m: number;
  xz: XZ;
  text: string;
  text_simple: string;
}

export interface CompareCornerTechnique {
  corner: string;
  label: string | null;
  name: string | null;
  direction: "left" | "right" | null;
  time_delta_s: number | null;
  incident: boolean;
  inside_known: boolean;
  points: Record<LinePointKey, number | null>;
  /** + = tighter (towards the inside of this corner), − = wider; |offset| when the inside is unknown. */
  offsets: Record<LinePointKey, number | null>;
  window: { d_m: number[]; offset_m: (number | null)[] } | null;
  ref_inputs: CornerInputs | null;
  lap_inputs: CornerInputs | null;
  notes: TechniqueNote[];
  ref_balance: PhaseRecord<PhaseBalance | null> | null;
  lap_balance: PhaseRecord<PhaseBalance | null> | null;
}

/** GET /api/technique/compare?ref=&lap= */
export interface TechniqueCompare {
  ref_lap_id: number;
  lap_id: number;
  ref_lap_number: number;
  lap_number: number;
  synthetic: boolean;
  compatible: boolean;
  blocking: string[];
  warnings: string[];
  lines: { step_m: number; ref_xz: (XZ | null)[]; lap_xz: (XZ | null)[] } | null;
  markers: LineMarker[];
  corners: CompareCornerTechnique[];
  available: TechniqueAvailability;
  pedals: PedalInfo;
  assists: AssistInfo;
}

/** Added to carsetup's ExperimentComparison (after_metrics.comparison.balance); optional. */
export interface BalanceChange {
  corner: string;
  label: string;
  phase: Phase;
  before: PhaseSummary;
  after: PhaseSummary;
  delta_deg: number | null;
  words: string;
}

export interface ExperimentBalance {
  available: boolean;
  reason: string | null;
  changes: BalanceChange[];
  note: string;
}

/** An experiment comparison as a server with feat/technique sends it (older servers leave `balance` out). */
export type ExperimentComparisonWithBalance = ExperimentComparison & { balance?: ExperimentBalance | null };

// ---------------------------------------------------------------------------------------------- transport

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

const enc = encodeURIComponent;

export function techniqueSessionPath(sid: string, refLapId?: number | null): string {
  return `/api/technique/sessions/${enc(sid)}${refLapId != null ? `?ref_lap_id=${refLapId}` : ""}`;
}

/** `carFormat`: the car format the Setup page knows (the driver's choice or the game's), so the server can size
 * suggestions for a generic car whose format it cannot tell (like /api/carsetup/sessions). */
export function techniqueBalancePath(sid: string, carFormat?: CarFormat | null): string {
  return `/api/technique/sessions/${enc(sid)}/balance${carFormat ? `?car_format=${enc(carFormat)}` : ""}`;
}

export function techniqueComparePath(ref: number, lap: number): string {
  return `/api/technique/compare?ref=${ref}&lap=${lap}`;
}

export const techniqueApi = {
  session: (sid: string, refLapId?: number | null) => req<TechniqueSession>(techniqueSessionPath(sid, refLapId)),
  balance: (sid: string, carFormat?: CarFormat | null) => req<TechniqueBalance>(techniqueBalancePath(sid, carFormat)),
  compare: (ref: number, lap: number) => req<TechniqueCompare>(techniqueComparePath(ref, lap)),
};

export const techniqueKeys = {
  /** Under "analysis:<id>": a completed lap of the live session refreshes it (hooks/useApi.ts). */
  session: (sid: string, refLapId?: number | null) =>
    refLapId == null ? `analysis:${sid}:technique` : `analysis:${sid}:technique:ref:${refLapId}`,
  balance: (sid: string, carFormat?: CarFormat | null) => `analysis:${sid}:technique-balance${carFormat ? `:${carFormat}` : ""}`,
  compare: (ref: number, lap: number) => `technique-compare:${ref}:${lap}`,
} as const;

/** What a technique request failure means for the page. */
export type TechniqueErrorKind =
  /** The server predates feat/technique (FastAPI's own 404 / 405): the technique blocks stay hidden. */
  | "missing"
  /** 409: no track model yet for this track. */
  | "no_model"
  /** 404 with a detail: the session or lap is unknown. */
  | "not_found"
  | "other";

export function techniqueErrorKind(e: unknown): TechniqueErrorKind {
  if (e instanceof ApiError) {
    if ((e.status === 404 && e.message === "404: Not Found") || (e.status === 405 && e.message === "405: Method Not Allowed")) {
      return "missing";
    }
    if (e.status === 409) return "no_model";
    if (e.status === 404) return "not_found";
  }
  return "other";
}

/** The server's words for an error, without the "409: " prefix. */
export function techniqueErrorText(e: unknown): string {
  if (e instanceof ApiError) {
    const m = e.message.replace(/^\d{3}: /, "");
    return m ? m[0]!.toUpperCase() + m.slice(1) : m;
  }
  return e instanceof Error ? e.message : String(e);
}
