// Coachref endpoints (lane coachref, spec section 6): choosing what the live delta, braking calls and lap coaching
// measure against (your best, the family record, another driver's best, a saved lap) and practice drills on one
// corner. Server side: src/pitwall/api/routes_coachref.py (prefix /api/coachref). Every type here mirrors the
// spec's JSON contract (6.2) and the live snapshot additions (6.3); the backend's contract test pins the same keys.
//
// Cache keys (lib/cache.ts). Everything lives under "coachref:" so one invalidate after a mutation refreshes it all:
//   coachrefKeys.options(driverId)      GET /options?driver_id=          (the Drive picker; fetched when it opens)
//   coachrefKeys.candidates(lapId)      GET /candidates?lap_id=           (Review › Compare, picker A "Family")
//   coachrefKeys.drillOptions(corner)   GET /drills/options?corner=       (Ready card, drill sheet; live context)
//   coachrefKeys.drills(q)              GET /drills?driver_id=&game=&...  (Review › Coaching, Drills)
// GET /compare (Review › Compare, a superset of /api/compare that does not depend on the choice) shares Review's
// "compare:<ref>:<lap>" key (pages/review/session/data.ts useRefCompare).
//
// Texts the server writes (labels, reasons, target_text, attempt and summary texts) are shown verbatim (P9).
// Unknown stays unknown: every field the contract allows to be null is typed so, and nothing here fills one in.

import { ApiError } from "../api";
import { authFetch } from "../auth";
import { cache } from "../cache";
import { isMissingRoute, reviewApi, type CompareResponse } from "./review";

// ------------------------------------------------------------------------------------------------- contract (6.2)

export type RefKind = "own_best" | "household_best" | "driver_best" | "lap";
export type Applies = "now" | "next_lap" | "after_drill" | "next_session";

export interface ReferenceChoice {
  driver_id: number;
  kind: RefKind;
  target_driver_id: number | null;
  lap_id: number | null;
  scope: "all_tracks" | "track";
  /** null for all_tracks. */
  game: string | null;
  track_id: string | null;
  /** "Your best", "Family record", "Sam's best", "Sam · lap 7 · 3 Oct". */
  label: string;
  /** null = the default (no stored row). */
  updated_unix: number | null;
}

/** snapshot.reference (extended; the four legacy keys unchanged), and the `reference` of /candidates and /compare. */
export interface ReferenceDescriptor {
  lap_id: number;
  lap_number: number;
  lap_time_ms: number | null;
  session_id: string;
  /** What picked it, after any fallback. */
  kind: RefKind;
  /** The lap belongs to the session's driver. */
  own: boolean;
  pinned: boolean;
  /** The lap's holder. */
  driver_id: number | null;
  driver_name: string | null;
  /** When the lap was stored. */
  set_unix: number | null;
  /** Screen label (spec 3.3 table): "Your best", "Family record · Sam", "Sam's best", "Sam · lap 7 · 3 Oct". */
  label: string;
  /** Radio phrase after "to" / "than": "your reference", "the family record", "Sam's best", "Sam's lap". */
  label_to: string;
  /** null for own references. */
  ref_name: string | null;
  /** Braking calls use the earlier of the two braking points (another driver's lap). */
  brake_clamped: boolean;
  /** Held for an active drill. */
  frozen: boolean;
}

export interface RefOptionLap {
  lap_id: number;
  lap_number: number;
  lap_time_ms: number;
  set_unix: number | null;
  driver_id: number;
  driver_name: string;
  session_id: string;
  car_name: string | null;
}

export interface RefOption {
  kind: RefKind;
  target_driver_id: number | null;
  lap_id: number | null;
  /** "Your best" | "Family record" | "Sam's best" | "Lap 7 · Sam". */
  label: string;
  /** null = no live context to check against. */
  available: boolean | null;
  /** Spec 3.1.1, when unavailable ("Sam's laps here used a different braking assist"). */
  reason: string | null;
  /** Compound / setup / fuel / temperature caveats. */
  warnings: string[];
  /** What it resolves to now. */
  lap: RefOptionLap | null;
  /** The driver's effective choice. */
  selected: boolean;
}

export interface RefContext {
  game: string;
  track_id: string;
  track_name: string | null;
  car_id: string | null;
  car_name: string | null;
  track_length_m: number | null;
}

export interface RefOptionsResponse {
  driver_id: number | null;
  context: RefContext | null;
  /** The effective choice. */
  choice: ReferenceChoice;
  has_track_override: boolean;
  /** own_best, household_best, driver_best per other driver (name order), then up to 10 compatible laps ("lap"). */
  options: RefOption[];
  /** What a change made now would do. */
  applies: Applies;
}

export interface ChoiceRequest {
  /** Default: the seated driver. */
  driver_id?: number;
  kind: RefKind;
  /** driver_best. */
  target_driver_id?: number;
  /** lap (scope forced to "track"; game and track come from the lap). */
  lap_id?: number;
  /** Default all_tracks; "track" defaults to the live session's game and track. */
  scope?: "all_tracks" | "track";
  game?: string;
  track_id?: string;
}

export interface ChoiceResponse {
  choice: ReferenceChoice;
  applies: Applies;
}

export interface ChoiceRows {
  all_tracks: ReferenceChoice | null;
  track: ReferenceChoice | null;
  effective: ReferenceChoice;
}

export interface CandidateGroup {
  id: "own" | "family";
  /** "Your best here" / "Family". */
  title: string;
  options: RefOption[];
}

export interface CandidatesResponse {
  lap_id: number;
  driver_id: number | null;
  groups: CandidateGroup[];
}

export type DrillKind = "brake_point" | "min_speed" | "exit_speed" | "entry_speed";
export type DrillStatus = "active" | "completed" | "stopped" | "abandoned";
export type DrillTrend = "closer" | "steady" | "further" | "rising" | "falling";
export type DrillUnit = "m" | "km/h";

export interface DrillAttempt {
  /** 1..laps_target. */
  attempt: number;
  lap_id: number | null;
  lap_number: number | null;
  /** m or km/h; null = not measured. */
  value: number | null;
  target: number;
  /** value - target. */
  delta: number | null;
  outcome: "hit" | "miss" | "unmeasured";
  /** "incident", "no braking measured", "exit 5 km/h down". */
  reason: string | null;
  corner_time_s: number | null;
  corner_time_delta_s: number | null;
  text: string;
  short: string;
}

export interface DrillReference {
  lap_id: number | null;
  kind: RefKind | null;
  driver_name: string | null;
  label: string | null;
}

export interface DrillView {
  id: number;
  driver_id: number | null;
  session_id: string | null;
  game: string;
  track_id: string;
  car_id: string | null;
  /** Learned key (= track_model.corners[].name). */
  corner: string;
  /** "T3". */
  corner_label: string;
  /** "Turn 3". */
  corner_voice: string;
  kind: DrillKind;
  /** "Brake point". */
  skill_label: string;
  source: "work_on" | "manual" | "radio";
  laps_target: number;
  target: number;
  tolerance: number;
  unit: DrillUnit;
  baseline: number | null;
  /** "Brake within 5 m of your reference's braking point". */
  target_text: string;
  note: string | null;
  reference: DrillReference;
  status: DrillStatus;
  stop_reason: string | null;
  started_unix: number;
  ended_unix: number | null;
  attempts: DrillAttempt[];
  hits: number;
  scored: number;
  best: number | null;
  best_delta: number | null;
  trend: DrillTrend | null;
  /** Set when completed / stopped with attempts. */
  summary_text: string | null;
  /** Always false today (drills refuse synthetic sessions); kept for evidence chips. */
  synthetic: boolean;
}

export interface DrillOption {
  kind: DrillKind;
  skill_label: string;
  available: boolean;
  reason: string | null;
  target: number | null;
  unit: DrillUnit;
  tolerance: number;
  baseline: number | null;
  target_text: string | null;
  note: string | null;
  /** brake [3, 5, 10] m, entry [3, 5, 8] km/h, speed steps [2, 3, 5] km/h. */
  tolerance_choices: number[];
  /** The kind mapped from the corner's current coaching point. */
  suggested: boolean;
}

export interface DrillOptionsResponse {
  corner: string;
  corner_label: string;
  corner_voice: string;
  /** Spec 3.4.2 #1-4 (live session, learned track, corner, no running drill). */
  available: boolean;
  reason: string | null;
  /** [3, 5, 8, 10]. */
  laps_choices: number[];
  /** 5. */
  default_laps: number;
  kinds: DrillOption[];
}

export interface DrillStartRequest {
  /** Learned key; or */
  corner?: string;
  /** "T3", "Turn 3", "Copse". */
  corner_ref?: string;
  /** Default: the kind mapped from the corner's coaching point (3.4.1). */
  kind?: DrillKind;
  /** 3-10, default 5. */
  laps?: number;
  /** brake 3-15 m, entry 2-10 km/h, speed step 1-10 km/h. */
  tolerance?: number;
  source?: "work_on" | "manual";
  observation_kind?: string;
}

export interface DrillsQuery {
  driver_id?: number | null;
  game?: string | null;
  track_id?: string | null;
  car_id?: string | null;
  /** 1-100, server default 20. */
  limit?: number;
  include_empty?: boolean;
}

/** /compare: the /api/compare body plus the reference descriptor (relative to lap B's driver). Observations are
 * reworded when the reference is another driver's ("Sam carries 6 km/h more through the slowest point"). */
export interface CoachrefCompareResponse extends CompareResponse {
  reference?: ReferenceDescriptor | null;
}

// --------------------------------------------------------------------------------------- live snapshot (6.3)

/** snapshot.coachref: the seated driver's choice, what the pipeline used, and the drill (active, or just ended). */
export interface CoachrefBlock {
  driver_id: number | null;
  choice: ReferenceChoice | null;
  used_kind: RefKind | null;
  /** Spec 3.1.1 when the choice could not be honoured ("Sam's laps here used a different braking assist"). */
  reason: string | null;
  /** A change waits for the next lap or the end of the drill. */
  pending: boolean;
  /** DrillView while active; after it ends, until another drill starts, the seat changes or the session changes. */
  drill: DrillView | null;
}

// ------------------------------------------------------------------------------------------------- shared words

/** Skill names (spec 10.8); the server's `skill_label` wins when it sends one. */
export const DRILL_SKILL_LABEL: Readonly<Record<DrillKind, string>> = {
  brake_point: "Brake point",
  min_speed: "Minimum speed",
  exit_speed: "Exit speed",
  entry_speed: "Entry speed",
};

/** Spec 3.4.1: which drill a coaching point leads to. `exit_gain` and `incident` start none. */
export const OBSERVATION_DRILL_KIND: Readonly<Record<string, DrillKind>> = {
  brake_early: "brake_point",
  brake_late_overdrive: "brake_point",
  low_min_speed: "min_speed",
  overspeed_apex: "exit_speed",
  late_throttle: "exit_speed",
  coasting: "exit_speed",
};

/** The drill a coaching point maps to, or null (praise, incidents, drill points, unknown kinds). */
export function drillKindFor(observationKind: string | null | undefined): DrillKind | null {
  if (!observationKind) return null;
  return Object.prototype.hasOwnProperty.call(OBSERVATION_DRILL_KIND, observationKind)
    ? (OBSERVATION_DRILL_KIND[observationKind] ?? null)
    : null;
}

export const DRILL_LAPS_CHOICES: readonly number[] = [3, 5, 8, 10];
export const DRILL_DEFAULT_LAPS = 5;

// --------------------------------------------------------------------------------------------------- client

function drillsQueryKey(q: DrillsQuery): string {
  return [q.driver_id ?? "", q.game ?? "", q.track_id ?? "", q.car_id ?? "", q.limit ?? "", q.include_empty ? 1 : 0].join("|");
}

export const coachrefKeys = {
  all: "coachref:",
  options: (driverId: number | null | undefined) => `coachref:options:${driverId ?? "seated"}`,
  candidates: (lapId: number) => `coachref:candidates:${lapId}`,
  drillOptions: (corner: string) => `coachref:drill-options:${corner}`,
  drills: (q: DrillsQuery) => `coachref:drills:${drillsQueryKey(q)}`,
  drill: (id: number) => `coachref:drill:${id}`,
} as const;

async function send<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await authFetch(path, init);
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const body = (await r.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = "That request was not accepted";
    } catch {
      /* not json */
    }
    throw new ApiError(r.status, detail);
  }
  if (r.status === 204) return null as T;
  return r.json() as Promise<T>;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === "") continue;
    p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

/** After any change: every coachref answer is stale (options, drill options, history, and Review › Compare's
 * "Drive against this lap"). */
function changed(): void {
  cache.invalidate(coachrefKeys.all);
}

const BASE = "/api/coachref";

export const coachrefApi = {
  options: (driverId?: number | null) => send<RefOptionsResponse>(`${BASE}/options${qs({ driver_id: driverId })}`),
  choice: (driverId: number, game?: string | null, trackId?: string | null) =>
    send<ChoiceRows>(`${BASE}/choice${qs({ driver_id: driverId, game, track_id: trackId })}`),
  setChoice: async (body: ChoiceRequest) => {
    const r = await send<ChoiceResponse>(`${BASE}/choice`, json("PUT", body));
    changed();
    return r;
  },
  /** Removes the track row (204), so the all-tracks choice applies there again. */
  deleteChoice: async (driverId: number, game: string, trackId: string) => {
    await send<null>(`${BASE}/choice${qs({ driver_id: driverId, game, track_id: trackId })}`, { method: "DELETE" });
    changed();
  },
  candidates: (lapId: number) => send<CandidatesResponse>(`${BASE}/candidates${qs({ lap_id: lapId })}`),
  compare: (ref: number, lap: number) => send<CoachrefCompareResponse>(`${BASE}/compare${qs({ ref, lap })}`),
  drillOptions: (q: { corner?: string; corner_ref?: string }) =>
    send<DrillOptionsResponse>(`${BASE}/drills/options${qs({ corner: q.corner, corner_ref: q.corner_ref })}`),
  startDrill: async (body: DrillStartRequest) => {
    const r = await send<DrillView>(`${BASE}/drills`, json("POST", body));
    changed();
    return r;
  },
  activeDrill: (driverId?: number | null) => send<DrillView | null>(`${BASE}/drills/active${qs({ driver_id: driverId })}`),
  stopDrill: async () => {
    const r = await send<DrillView>(`${BASE}/drills/active/stop`, { method: "POST" });
    changed();
    return r;
  },
  /** Done on a drill result: the seated driver's last result is no longer published (204; 404 when not showing). */
  dismissDrill: async (id: number) => {
    await send<null>(`${BASE}/drills/${id}/dismiss`, { method: "POST" });
    changed();
  },
  drills: (q: DrillsQuery = {}) =>
    send<DrillView[]>(
      `${BASE}/drills${qs({
        driver_id: q.driver_id,
        game: q.game,
        track_id: q.track_id,
        car_id: q.car_id,
        limit: q.limit,
        include_empty: q.include_empty ? true : undefined,
      })}`,
    ),
  drill: (id: number) => send<DrillView>(`${BASE}/drills/${id}`),
};

/**
 * Review › Compare's data: /api/coachref/compare (the /api/compare body plus the reference descriptor, observations
 * reworded for another driver's lap). A server without the coachref routes answers 404 Not Found: then plain
 * /api/compare, so Compare keeps working (no descriptor: own wording).
 */
export async function compareWithReference(ref: number, lap: number): Promise<CoachrefCompareResponse> {
  try {
    return await coachrefApi.compare(ref, lap);
  } catch (e) {
    if (isMissingRoute(e)) return reviewApi.compare(ref, lap);
    throw e;
  }
}

/** The server's sentence without the status prefix ("409: A drill on T3 is running…" -> "A drill on T3 is running…"). */
export function coachrefErrorText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 503) return "Pitwall is busy with the last lap: try again in a moment.";
    if (isMissingRoute(e)) return "This Pitwall server does not have reference choice and drills yet.";
    return e.message.replace(/^\d{3}:\s*/, "");
  }
  return e instanceof Error ? e.message : String(e);
}

/** A 409 (a business rule said no; the sentence says why). */
export function isConflict(e: unknown): boolean {
  return e instanceof ApiError && e.status === 409;
}
