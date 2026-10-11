// Drive › Car, the pit wall (design spec 5.1; mockup driveCar): pure view models for its six tiles. No React, so
// every rule is tested in plain node (view.test.ts) from the recorded and synthetic fixtures. Lane DV.
//
// For a stationary reader (a parent on the phone, a Mac next to the rig): denser than Coach, but the same honesty
// rules. Unknown is "-" (P5); while the data is in doubt (stale, offline) every live car value is "-" and the rest
// is last known, dimmed by the page. Timing colours by current standing in the laps table (4.6), purple and PB only
// with D2. Coaching texts are the backend's, verbatim (P9); race-control words never claim whose car an event was
// unless the event says so.

import { cornerAhead, cornerLabelOf } from "../../../lib/drive/corner";
import { lapPicks, NO_REFERENCE_COACHING, pointText, simpleWording } from "../../../lib/drive/coach";
import { gameLength } from "../../../lib/drive/geometry";
import type { DriveModel } from "../../../lib/drive/model";
import { ageText, finite, signedFixed, UNKNOWN } from "../../../lib/drive/text";
import { bestsOf, notCleanWords, standing, type TimingStatus } from "../../../lib/drive/timing";
import type { LiveEvent, ObservationNext, SnapshotNext } from "../../../lib/drive/types";
import { decimal, gearLabel, grouped, num, tyreTempColor, unit01 } from "../../../lib/format";
import { worldXZ } from "../../../lib/viz/track-map";
import { measuredFuelMargin } from "../../../lib/strategy/view"; // race strategy (pitwall.strategy)

/** The data on screen is current: not stale, not offline, and telemetry has arrived. */
export function liveValues(model: Pick<DriveModel, "dim" | "state">): boolean {
  return !model.dim && model.state !== "no_data";
}

// ------------------------------------------------------------------------------------------------- car tile

export interface MeterView {
  /** "10 950", "100%", "-". */
  text: string;
  /** Fill 0..1, null when unknown (the bar is empty and announced as unknown, never as 0). */
  frac: number | null;
  /** RPM above 94 % of the maximum: the bar turns --pw-bad. */
  hot: boolean;
}

export interface CarTileView {
  /** Header chip: "Telemetry 60/s". */
  rate: string;
  speed: string;
  gear: string;
  rpm: MeterView;
  throttle: MeterView;
  brake: MeterView;
  steering: string;
  /** Front brake bias: "56%". A setting, kept while stale. */
  bias: string;
  /** "open" / "closed" / "-". */
  drs: string;
  /** Telemetry health footer (moved from today's Live strip): "0 rejected · 0 unrecognised · udp:20777". */
  health: string;
}

/** RPM bar turns red above this fraction of the maximum (spec 5.1). */
export const RPM_HOT = 0.94;

function pct(v: number | null | undefined): MeterView {
  const f = unit01(v);
  return { text: f == null ? UNKNOWN : `${Math.round(f * 100)}%`, frac: f, hot: false };
}

export function carTile(s: SnapshotNext | null, model: Pick<DriveModel, "dim" | "state">): CarTileView {
  const live = liveValues(model);
  const f = live ? (s?.frame ?? null) : null;
  const facts = s?.frame ?? null; // settings (bias) stay as last known
  const rpmFrac = f && finite(f.rpm) && finite(f.max_rpm) && f.max_rpm > 0 ? unit01(f.rpm / f.max_rpm) : null;
  const conn = s?.connection;
  const offline = model.state === "offline";
  const pps = conn?.packets_per_s;
  return {
    rate: !offline && finite(pps) ? `Telemetry ${grouped(pps)}/s` : "Telemetry -",
    speed: num(f?.speed_kph),
    gear: gearLabel(f?.gear),
    rpm: { text: finite(f?.rpm) ? grouped(f.rpm) : UNKNOWN, frac: rpmFrac, hot: rpmFrac != null && rpmFrac > RPM_HOT },
    throttle: pct(f?.throttle),
    brake: pct(f?.brake),
    steering: num(f?.steering, 2),
    bias: finite(facts?.brake_bias_front_pct) ? `${decimal(facts.brake_bias_front_pct, 1)}%` : UNKNOWN,
    drs: f?.drs_open == null ? UNKNOWN : f.drs_open ? "open" : "closed",
    health:
      offline || !conn
        ? "Telemetry health unknown while offline"
        : `${grouped(conn.rejected)} rejected · ${grouped(conn.unrecognised)} unrecognised · ${conn.source ?? "no source yet"}`,
  };
}

// ----------------------------------------------------------------------------------------------- tyres tile

export type TyreBand = "cold" | "cool" | "ok" | "hot" | "over" | "unknown";

export interface TyreView {
  wheel: "FL" | "FR" | "RL" | "RR";
  /** Surface temperature "92°", or "-". */
  temp: string;
  /** Colour token of the band (in the window: plain foreground). */
  colour: string;
  band: TyreBand;
  /** Out of the window in words, so colour is never the only signal (P4): "cold", "hot", "over", else null. */
  word: string | null;
  /** "6% · 23.1 psi" (wear · pressure). */
  sub: string;
  aria: string;
}

export interface TyresView {
  /** "Soft · 7 laps", or null when the game does not say. */
  chip: string | null;
  /** FL FR / RL RR (wheel order is always FL, FR, RL, RR). */
  wheels: [TyreView, TyreView, TyreView, TyreView];
  /** "Fuel 18.4 kg · +1.2 laps (game) · ERS 2.8 MJ". */
  energy: string;
}

const WHEELS = ["FL", "FR", "RL", "RR"] as const;

export function tyreBand(t: number | null | undefined): TyreBand {
  if (!finite(t)) return "unknown";
  if (t < 75) return "cold";
  if (t < 85) return "cool";
  if (t <= 105) return "ok";
  if (t <= 115) return "hot";
  return "over";
}

const BAND_WORD: Partial<Record<TyreBand, string>> = { cold: "cold", cool: "cool", hot: "hot", over: "over" };

function at(xs: readonly (number | null)[] | null | undefined, i: number): number | null {
  const v = xs?.[i];
  return finite(v) ? v : null;
}

function capitalised(s: string): string {
  return s.length ? s[0]!.toUpperCase() + s.slice(1) : s;
}

export function tyresTile(s: SnapshotNext | null): TyresView {
  const f = s?.frame ?? null;
  const wheels = WHEELS.map((wheel, i): TyreView => {
    const t = at(f?.tyre_surface_temp_c, i);
    const wear = at(f?.tyre_wear_pct, i);
    const p = at(f?.tyre_pressure_psi, i);
    const band = tyreBand(t);
    const wearText = wear == null ? UNKNOWN : `${num(wear)}%`;
    const pText = p == null ? UNKNOWN : `${num(p, 1)} psi`;
    return {
      wheel,
      temp: t == null ? UNKNOWN : `${num(t)}°`,
      colour: tyreTempColor(t),
      band,
      word: BAND_WORD[band] ?? null,
      sub: `${wearText} · ${pText}`,
      aria: `${wheel}: surface ${t == null ? "unknown" : `${num(t)} degrees`}${BAND_WORD[band] ? `, ${BAND_WORD[band]}` : ""}, wear ${
        wear == null ? "unknown" : `${num(wear)} percent`
      }, pressure ${p == null ? "unknown" : `${num(p, 1)} psi`}`,
    };
  }) as TyresView["wheels"];
  const compound = f?.tyre_compound ? capitalised(f.tyre_compound) : null;
  const age = finite(f?.tyre_age_laps) ? `${f.tyre_age_laps} ${f.tyre_age_laps === 1 ? "lap" : "laps"}` : null;
  const chip = compound ? [compound, age].filter(Boolean).join(" · ") : null;
  const fuel = finite(f?.fuel_kg) ? `${num(f.fuel_kg, 1)} kg` : UNKNOWN;
  // race strategy (pitwall.strategy): this race's own measured margin first, the game's figure until it is known
  const margin =
    measuredFuelMargin(s) ??
    (finite(f?.fuel_remaining_laps_game) ? `${signedFixed(f.fuel_remaining_laps_game, 1)} laps (game)` : null);
  const ers = finite(f?.ers_store_j) ? `${num(f.ers_store_j / 1e6, 1)} MJ` : UNKNOWN;
  return { chip, wheels, energy: [`Fuel ${fuel}`, margin, `ERS ${ers}`].filter(Boolean).join(" · ") };
}

// ------------------------------------------------------------------------------------------------ laps tile

export interface TimeCell {
  ms: number | null;
  status: TimingStatus;
}

export interface LapRowView {
  id: number;
  lap: number;
  /** This lap is the delta reference: `R`. */
  ref: boolean;
  /** Pit in / out lap: `PIT`. */
  pit: boolean;
  /** Why the lap is not clean, in words ("out lap, flashback"); null when clean. */
  reason: string | null;
  time: TimeCell;
  sectors: [TimeCell, TimeCell, TimeCell];
  /** Difference to the reference lap ("+0.53"); null for the reference itself or when unknown. */
  delta: string | null;
}

export interface LapsTileView {
  rows: LapRowView[];
  /** "current standing · ref L4" */
  sub: string;
  tier: 1 | 2;
  empty: string | null;
}

/** Newest laps shown on the wall (spec 5.1). */
export const WALL_LAPS = 8;

export function lapsTile(s: SnapshotNext | null, max = WALL_LAPS): LapsTileView {
  const laps = s?.laps ?? [];
  const ref = s?.reference ?? null;
  const sub = `current standing · ${ref ? `ref L${ref.lap_number}` : "no reference yet"}`;
  if (!s || !laps.length) return { rows: [], sub, tier: s ? bestsOf(s).tier : 1, empty: "No completed laps yet" };
  const bv = bestsOf(s);
  const clean = laps.map((l) => l.clean);
  // Standing over every lap the snapshot carries (20 newest), so the session best is right; then the newest `max`.
  // D2's setter lap ids settle ties: a lap that only equals a best set earlier (another session) does not take it.
  const ids = laps.map((l) => l.lap_id);
  const lapSt = standing(
    laps.map((l) => l.lap_time_ms),
    clean,
    {
      driver: bv.driver?.lap_ms ?? null,
      household: bv.household?.lap_ms ?? null,
      driverLapId: bv.driver?.lap_id,
      householdLapId: bv.household?.lap_id,
    },
    bv.tier,
    bv.coloured, // synthetic and replay laps carry no timing colour (4.6), as on Coach and in Review > Laps
    ids,
  );
  const secSt = [0, 1, 2].map((i) =>
    standing(
      laps.map((l) => l.sector_times_ms[i] ?? null),
      clean,
      {
        driver: bv.driver?.sectors_ms[i] ?? null,
        household: bv.household?.sectors_ms[i] ?? null,
        driverLapId: bv.driver?.sector_lap_ids?.[i],
        householdLapId: bv.household?.sector_lap_ids?.[i],
      },
      bv.tier,
      bv.coloured,
      ids,
    ),
  );
  const refMs = ref && finite(ref.lap_time_ms) && ref.lap_time_ms > 0 ? ref.lap_time_ms : null;
  const rows = laps.slice(0, max).map((l, i): LapRowView => {
    const isRef = ref != null && ref.lap_id === l.lap_id;
    const t = finite(l.lap_time_ms) && l.lap_time_ms > 0 ? l.lap_time_ms : null;
    return {
      id: l.lap_id,
      lap: l.lap_number,
      ref: isRef,
      pit: l.flags.includes("pit_in") || l.flags.includes("pit_out"),
      reason: notCleanWords(l),
      time: { ms: t, status: lapSt[i] ?? "neutral" },
      sectors: [0, 1, 2].map((k) => {
        const v = l.sector_times_ms[k];
        return { ms: finite(v) && v > 0 ? v : null, status: secSt[k]?.[i] ?? "neutral" };
      }) as LapRowView["sectors"],
      delta: isRef || t == null || refMs == null ? null : signedFixed((t - refMs) / 1000, 2),
    };
  });
  return { rows, sub, tier: bv.tier, empty: null };
}

// -------------------------------------------------------------------------------------------- coaching tile

export interface CoachItemView {
  id: string;
  /** Corner chip: "T15", or "T9 · good". */
  chip: string;
  good: boolean;
  /** Verbatim: D6's glance text when there is one, else the full text (2-line clamp on the wall). */
  text: string;
  /** Time in this corner vs the reference: "+0.11 s" lost / "−0.04 s" gained; null when unknown. */
  impact: string | null;
  impactTone: "ahead" | "behind" | null;
}

export interface CoachingTileView {
  /** "Coaching · lap 6", or "Coaching · last lap". */
  title: string;
  items: CoachItemView[];
  empty: string | null;
  /** "radio's picks" (D6) or "top by priority" (before D6). */
  source: "d6" | "observation";
}

/** Points shown on the wall (spec 5.1: up to 3). */
export const WALL_POINTS = 3;

function impactOf(o: ObservationNext): { impact: string | null; tone: "ahead" | "behind" | null } {
  if (!finite(o.impact_s) || o.impact_s === 0) return { impact: null, tone: null };
  return { impact: `${signedFixed(o.impact_s, 2)} s`, tone: o.impact_s < 0 ? "ahead" : "behind" };
}

export function coachingTile(s: SnapshotNext | null, profileSimple: boolean, max = WALL_POINTS): CoachingTileView {
  if (!s) return { title: "Coaching · last lap", items: [], empty: "No coaching yet", source: "observation" };
  const { picks, source } = lapPicks(s);
  const simple = simpleWording(s, profileSimple);
  const shown = picks.slice(0, max);
  const lap = s.coach?.lap_number ?? shown[0]?.lap_number ?? null;
  const title = finite(lap) ? `Coaching · lap ${lap}` : "Coaching · last lap";
  const items = shown.map((o): CoachItemView => {
    const label = cornerLabelOf(s.track_model, o.corner);
    const { impact, tone } = impactOf(o);
    return {
      id: o.id,
      chip: o.positive ? `${label} · good` : label,
      good: o.positive,
      text: pointText(o, simple, true),
      impact,
      impactTone: tone,
    };
  });
  const empty = items.length
    ? null
    : !s.reference && !s.coach
      ? NO_REFERENCE_COACHING
      : "No coaching points on the last lap";
  return { title, items, empty, source };
}

// ------------------------------------------------------------------------------------------ race control line

/** Session-wide events, in words. Per-car events (penalty, collision, fastest lap) never say whose car unless the
 * event carries `player` (proposed backend field): F1 reports them for every car. */
const SESSION_WORDS: Record<string, string> = {
  session_started: "Session started",
  session_ended: "Session ended",
  lights_out: "Lights out",
  chequered_flag: "Chequered flag",
  red_flag: "Red flag",
  safety_car: "Safety car",
  flashback: "Flashback",
  pit_entry: "Pit entry",
  pit_exit: "Pit exit",
};

const CAR_WORDS: Record<string, { mine: string; any: string }> = {
  penalty: { mine: "Penalty for you", any: "Penalty issued" },
  collision: { mine: "Contact", any: "Collision reported" },
  fastest_lap: { mine: "Your fastest lap of the session", any: "Fastest lap set" },
};

/** F1 event codes reported as kind "other" that race control would announce. Overtakes, speed traps, buttons and
 * mode changes are left out (they are not race control). */
const OTHER_CODES: Record<string, string> = {
  DRSE: "DRS enabled",
  DRSD: "DRS disabled",
  RTMT: "Retirement",
  STLG: "Start lights",
  DTSV: "Drive-through served",
  SGSV: "Stop-go served",
  RCWN: "Race winner",
};

export function eventWords(e: Pick<LiveEvent, "kind" | "code" | "player">): string | null {
  if (SESSION_WORDS[e.kind]) return SESSION_WORDS[e.kind]!;
  const car = CAR_WORDS[e.kind];
  if (car) return e.player === true ? car.mine : car.any;
  if (e.kind === "other" && e.code && OTHER_CODES[e.code]) return OTHER_CODES[e.code]!;
  return null;
}

/** The map tile's footer: the newest race-control event and its age ("Race control · Penalty issued · 2 min ago"). */
export function raceControlLine(events: readonly LiveEvent[] | null | undefined, nowS: number): string {
  for (const e of events ?? []) {
    const w = eventWords(e);
    if (!w) continue;
    const age = finite(e.t) && e.t <= nowS + 5 ? Math.max(0, nowS - e.t) : null;
    return `Race control · ${w}${age != null ? ` · ${age < 5 ? "just now" : `${ageText(age)} ago`}` : ""}`;
  }
  return "Race control · nothing yet";
}

// ------------------------------------------------------------------------------------------------ map tile

export interface WallMapView {
  /** The next corner (learned name), highlighted on the map. */
  highlight: string | null;
  focus: string[];
  /** Brake notches: the cue plan's targets in game metres. */
  cueTargetsM: number[];
  /** This lap's sectors as set; only with D1 (the current lap's own times), never the last lap's. */
  sectorStatus: (TimingStatus | "running" | "future")[] | null;
  car: [number, number] | null;
  carM: number | null;
  /** Live marshal flags (yellow zones); only while the data is current. */
  flags: { game_number: number; flag: string }[] | null;
  /** "14 corners · official names" / "9 corners learned" / "Learning the track". */
  caption: string;
}

export function mapTile(s: SnapshotNext | null, model: Pick<DriveModel, "dim" | "state" | "sectors">): WallMapView {
  const live = liveValues(model);
  const tm = s?.track_model ?? null;
  const corners = tm?.corners ?? [];
  const official = corners.some((c) => c.identity_tier || c.label || c.display_name);
  const caption = corners.length
    ? `${corners.length} ${corners.length === 1 ? "corner" : "corners"}${official ? " · official names" : " learned"}`
    : "Learning the track";
  const next = live ? cornerAhead(tm, s?.frame?.lap_distance_m, gameLength(s), s?.cues) : null;
  const d = s?.frame?.lap_distance_m;
  return {
    highlight: next?.name ?? null,
    focus: [...(s?.cues?.focus ?? [])],
    cueTargetsM: (s?.cues?.cues ?? []).map((c) => c.target_m).filter(finite),
    sectorStatus: model.sectors.source === "current" ? model.sectors.cells.map((c) => c.status) : null,
    car: live ? worldXZ(s?.frame?.pos) : null,
    carM: live && finite(d) ? d : null,
    flags: live ? (s?.marshal_flags ?? null) : null,
    caption,
  };
}
