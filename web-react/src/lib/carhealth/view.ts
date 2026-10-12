// Car health and racecraft (lane "health"; lane spec 3.13 D1-D6): pure view pieces over the live snapshot's
// `car_health` and `racecraft` blocks and the strategy block's `pit.rejoin`. No React, so every rule is tested in plain
// node (view.test.ts) from the fixtures in src/test/fixtures/carhealth.
//
// Used by Drive › Car's "Tyres & energy" tile (pages/drive/car/view.ts tyresTile) and its Strategy tile
// (lib/strategy/view.ts: the "Box now ≈ P7" line, the attack / defend tags), and by Settings › Radio & voice
// (the "Car health calls" card).
//
// Honesty rules:
//  * Tyre colours compare with the driver's own warm laps in this session (the backend's band per wheel). No fixed
//    window: no game publishes its tyre windows, and F1 25's real surface temperatures sit under 75 °C on 93 % of
//    wheel-laps. Colour is never the only signal (P4): a cold or hot wheel also says so in a word.
//  * In a surface-only F1 session the game sends a constant inner temperature: only the surface is ever shown then.
//  * Unknown is "-" (P5), never 0. ABS on means lock-ups are not counted ("ABS on"), never "0 lock-ups".
//  * Rejoin and racecraft numbers are estimates and say so: "≈", a range, and the tier suffix of the pit loss.
//  * Racecraft names no one: positions, car indexes and corners only.

import { cornerLabelOf } from "../drive/corner";
import { finite, UNKNOWN } from "../drive/text";
import type { FrameNext, SnapshotNext, TrackModelNext } from "../drive/types";
import type { RejoinView } from "../strategy/types";
import { tierSuffix } from "../strategy/words";
import type {
  BrakeHealth,
  CarHealthSettings,
  CarHealthView,
  EngineHealth,
  HealthCall,
  HealthWheel,
  RacecraftSide,
  RacecraftView,
  SlipCallsSetting,
  SlipHealth,
  TankFuel,
  TyreHealth,
  TyreTempBand,
} from "./types";

// ---------------------------------------------------------------------------------------------- the blocks

/**
 * The snapshot's car_health block when it is one this dashboard understands (version 1), else null: an older server
 * (no block), a newer contract or a malformed payload all leave Drive exactly as it was before the health lane.
 */
export function carHealthOf(raw: unknown): CarHealthView | null {
  if (!raw || typeof raw !== "object") return null;
  const v = raw as Partial<CarHealthView>;
  if (v.version !== 1) return null;
  return {
    version: 1,
    session_id: typeof v.session_id === "string" ? v.session_id : null,
    game: typeof v.game === "string" ? v.game : null,
    synthetic: v.synthetic === true,
    tyres: v.tyres ?? null,
    brakes: v.brakes ?? null,
    engine: v.engine ?? null,
    slip: v.slip ?? null,
    fuel: v.fuel && typeof v.fuel === "object" ? v.fuel : null,
    calls: Array.isArray(v.calls) ? v.calls : [],
    thresholds: Array.isArray(v.thresholds) ? v.thresholds : [],
  };
}

const RACECRAFT_MODES = new Set(["race", "off"]);

/** The racecraft block (version 1, a known mode), else null. */
export function racecraftOf(raw: unknown): RacecraftView | null {
  if (!raw || typeof raw !== "object") return null;
  const v = raw as Partial<RacecraftView>;
  if (v.version !== 1 || typeof v.mode !== "string" || !RACECRAFT_MODES.has(v.mode)) return null;
  return {
    version: 1,
    session_id: typeof v.session_id === "string" ? v.session_id : null,
    mode: v.mode,
    reason: typeof v.reason === "string" ? v.reason : null,
    corners_source: v.corners_source ?? null,
    ahead: v.ahead && typeof v.ahead === "object" ? v.ahead : null,
    behind: v.behind && typeof v.behind === "object" ? v.behind : null,
  };
}

/** A block that names another session than the snapshot's is not about this car (never shown). */
function sameSession(blockSid: string | null, snapSid: string | null | undefined): boolean {
  return !blockSid || !snapSid || blockSid === snapSid;
}

/** The car_health block of a live snapshot (see carHealthOf), only for the snapshot's own session. */
export function snapCarHealth(
  s: Partial<Pick<SnapshotNext, "car_health" | "session_id">> | null | undefined,
): CarHealthView | null {
  const v = carHealthOf(s?.car_health);
  return v && sameSession(v.session_id, s?.session_id) ? v : null;
}

/** The racecraft block of a live snapshot (see racecraftOf), only for the snapshot's own session. */
export function snapRacecraft(
  s: Partial<Pick<SnapshotNext, "racecraft" | "session_id">> | null | undefined,
): RacecraftView | null {
  const v = racecraftOf(s?.racecraft);
  return v && sameSession(v.session_id, s?.session_id) ? v : null;
}

/** The tyre section when the game fills it (wheels as a list), else null. */
export function tyreSection(ch: CarHealthView | null | undefined): TyreHealth | null {
  const t = ch?.tyres;
  return t && t.available === true && Array.isArray(t.wheels) ? t : null;
}

export function brakeSection(ch: CarHealthView | null | undefined): BrakeHealth | null {
  const b = ch?.brakes;
  return b && b.available === true ? b : null;
}

export function engineSection(ch: CarHealthView | null | undefined): EngineHealth | null {
  const e = ch?.engine;
  return e && e.available === true ? e : null;
}

export function slipSection(ch: CarHealthView | null | undefined): SlipHealth | null {
  const s = ch?.slip;
  return s && s.available === true ? s : null;
}

// ------------------------------------------------------------------------------------------------ tyre bands

/** Colour token per band: cold and hot have their own; in range or unknown is the plain foreground. */
export const BAND_COLOUR: Readonly<Record<TyreTempBand, string>> = Object.freeze({
  cold: "var(--pw-tyre-cold)",
  hot: "var(--pw-tyre-hot)",
  ok: "var(--pw-tyre-optimal)",
  unknown: "var(--pw-tyre-optimal)",
});

/** The word beside the wheel (colour is never the only signal, P4); null in range or unknown. */
export const BAND_WORD: Readonly<Partial<Record<TyreTempBand, string>>> = Object.freeze({ cold: "cold", hot: "hot" });

const BANDS: ReadonlySet<string> = new Set<TyreTempBand>(["cold", "ok", "hot", "unknown"]);

/** One wheel's band from the backend (matched by the wheel's name, never by position); "unknown" without one. */
export function wheelBand(t: TyreHealth | null, wheel: HealthWheel): TyreTempBand {
  const w = t?.wheels.find((x) => x.wheel === wheel);
  return w && BANDS.has(w.band) ? w.band : "unknown";
}

/** Which temperature the tile's big number is: the carcass when the game simulates it, else the surface. */
export function mainTemp(t: TyreHealth | null): "inner" | "surface" {
  return t?.model === "carcass" ? "inner" : "surface";
}

/** The caption under the wheels: what the number is and what the colours mean; null without the block. */
export function tempBasis(t: TyreHealth | null): string | null {
  if (!t) return null;
  return `${t.model === "carcass" ? "Inside" : "Surface"} temperatures · colours compare with your warm laps`;
}

/** The header chip while the tyres are cold after a stop or a safety car. */
export const COLD_CHIP = "Cold tyres";

export function tyresCold(t: TyreHealth | null): boolean {
  return t?.state === "cold";
}

/** Screen-reader words for a band ("cold for this session"); null when nothing is known. */
export function bandAria(band: TyreTempBand): string | null {
  return band === "cold"
    ? "cold for this session"
    : band === "hot"
      ? "hot for this session"
      : band === "ok"
        ? "normal for this session"
        : null;
}

// ---------------------------------------------------------------------------------------- brakes and engine

function hottest(xs: readonly (number | null)[] | null | undefined): number | null {
  const v = (xs ?? []).filter(finite);
  return v.length ? Math.max(...v) : null;
}

/**
 * "Brakes 980° · Engine 124°" from the live frame (the hottest brake). Each part only when the game is known to send
 * it: the car_health block says so (F1), or without a block the frame carries the value (or `brakesSent` from the
 * games catalogue). Null when neither part applies (GT7, Forza, AC). Unknown values are "-".
 */
export function tempsLine(
  frame: Pick<FrameNext, "brake_temp_c" | "engine_temp_c"> | null | undefined,
  ch: CarHealthView | null,
  brakesSent = true,
): string | null {
  const brakeMax = hottest(frame?.brake_temp_c);
  const engine = frame?.engine_temp_c;
  const showBrakes = ch ? brakeSection(ch) != null : brakesSent && brakeMax != null;
  const showEngine = ch ? engineSection(ch) != null : finite(engine);
  const parts = [
    showBrakes ? `Brakes ${brakeMax == null ? UNKNOWN : `${Math.round(brakeMax)}°`}` : null,
    showEngine ? `Engine ${finite(engine) ? `${Math.round(engine)}°` : UNKNOWN}` : null,
  ].filter((x): x is string => x !== null);
  return parts.length ? parts.join(" · ") : null;
}

// ------------------------------------------------------------------------------------- lock-ups and wheelspin

function countText(n: number | null | undefined, one: string, many: string, none: string): string {
  if (!finite(n)) return `${many} ${UNKNOWN}`;
  if (n <= 0) return none;
  return `${n} ${n === 1 ? one : many}`;
}

/**
 * The last completed lap's lock-ups and wheelspin (F1 MotionEx, the whole lap): "Last lap: 3 lock-ups · 4 wheelspin",
 * "Last lap: no lock-ups (ABS on) · 1 wheelspin". With ABS on lock-ups are not counted, so they are never "0". Null
 * when the game sends no slip (the line is left out).
 */
export function slipLine(slip: SlipHealth | null): string | null {
  if (!slip) return null;
  const l = slip.last_lap;
  if (!l) return `Last lap: ${UNKNOWN}`;
  const lock = slip.lockups_applicable ? countText(l.lockups, "lock-up", "lock-ups", "no lock-ups") : "no lock-ups (ABS on)";
  const spin = countText(l.wheelspin, "wheelspin", "wheelspin", "no wheelspin");
  return `Last lap: ${lock} · ${spin}`;
}

// ------------------------------------------------------------------------------------------------------ fuel

export interface TankFuelLine {
  /** "Fuel ≈ 7 laps (tank level)", "Fuel use off", "Fuel: measuring…"; or for an estimate Pitwall does not make
   * (GT7 unverified, not sent) the words to use only when the games catalogue says nothing. */
  text: string;
  tone: "plain" | "warn";
  /** true: the line replaces the catalogue's "Fuel: not in Pitwall yet" (Pitwall estimates fuel for this game). */
  estimates: boolean;
}

/** Laps of fuel for a glance: one decimal under two laps ("1.2 laps"), else whole laps rounded down ("7 laps"). */
export function lapsOfFuelText(laps: number): string {
  if (laps < 2) return `${Math.max(0, laps).toFixed(1)} laps`;
  const n = Math.floor(laps);
  return `${n} laps`;
}

/**
 * Fuel from the tank level (Forza; GT7 once verified). Null for F1 and older servers (the tile keeps the strategy's
 * kilos). GT7 "unverified": no numbers anywhere, the catalogue's sentence stays.
 */
export function tankFuelLine(fuel: TankFuel | null | undefined): TankFuelLine | null {
  // a fuel source this dashboard does not know is not read; "not sent" comes without a source
  if (!fuel || typeof fuel.status !== "string" || (fuel.source != null && fuel.source !== "tank_fraction")) return null;
  switch (fuel.status) {
    case "ok":
    case "low":
    case "critical": {
      if (!finite(fuel.laps_of_fuel)) return { text: "Fuel: measuring…", tone: "plain", estimates: true };
      const laps = `≈ ${lapsOfFuelText(fuel.laps_of_fuel)} (tank level)`;
      if (fuel.status === "critical") return { text: `Fuel almost out: ${laps}`, tone: "warn", estimates: true };
      if (fuel.status === "low") return { text: `Fuel low: ${laps}`, tone: "warn", estimates: true };
      return { text: `Fuel ${laps}`, tone: "plain", estimates: true };
    }
    case "not_used":
      return { text: "Fuel use off", tone: "plain", estimates: true };
    case "unknown":
      return { text: "Fuel: measuring…", tone: "plain", estimates: true };
    case "unverified":
      return { text: "Fuel: not estimated", tone: "plain", estimates: false };
    default:
      return { text: "Fuel: not sent", tone: "plain", estimates: false };
  }
}

// ---------------------------------------------------------------------------------------- where I'd come out

/** "1st", "2nd", "3rd", "4th", "11th", "22nd". */
export function ordinal(n: number): string {
  const v = Math.round(n);
  const t = v % 100;
  const suffix = t >= 11 && t <= 13 ? "th" : v % 10 === 1 ? "st" : v % 10 === 2 ? "nd" : v % 10 === 3 ? "rd" : "th";
  return `${v}${suffix}`;
}

export interface RejoinLine {
  /** "Box now ≈ P7 (P6–8)", "Box now: game says P8", "If you stop now: about 7th". */
  text: string;
  aria: string;
}

function pos(n: number | null | undefined): n is number {
  return finite(n) && n > 0;
}

/**
 * The Pit window row's sub-value from `pit.rejoin` (rejoin v2 only: an older server's rule was wrong on real races,
 * so its value is not shown). While the player is in the pit lane the prediction made on track is held ("Rejoin").
 */
export function rejoinLine(r: RejoinView | null | undefined, simple = false): RejoinLine | null {
  if (!r || typeof r.basis !== "string") return null;
  const game = pos(r.game_position) ? r.game_position : null;
  if (r.basis === "game_only" || !pos(r.position)) {
    if (game == null) return null;
    return {
      text: simple ? `If you stop now: game says ${ordinal(game)}` : `Box now: game says P${game}`,
      aria: `If you box now: no pit stop measured in this race yet, the game's own estimate is P${game}`,
    };
  }
  const p = r.position;
  const lo = pos(r.position_low) ? r.position_low : p;
  const hi = pos(r.position_high) ? r.position_high : p;
  const range = lo < hi ? ` (P${lo}–${hi})` : "";
  const tier = tierSuffix(r.loss_tier ?? null);
  const frozen = r.frozen === true;
  const text = simple
    ? frozen
      ? `You'll come out about ${ordinal(p)}`
      : `If you stop now: about ${ordinal(p)}`
    : `${frozen ? "Rejoin" : "Box now"} ≈ P${p}${range}${tier}`;
  const stops = pos(r.loss_n) ? ` measured on ${r.loss_n} ${r.loss_n === 1 ? "stop" : "stops"}` : "";
  const loss = finite(r.loss_s) && r.loss_s > 0 ? `, from a ${Math.round(r.loss_s)} second pit loss${stops}` : "";
  const between = lo < hi ? `, between P${lo} and P${hi}` : "";
  const aria = [
    `${frozen ? "Coming out of the pits" : "If you box now"} you'd come out around P${p}${between}`,
    `${r.loss_tier === "game" ? "game" : "Pitwall"} estimate${loss}`,
    game != null && game !== p ? `the game says P${game}` : null,
    r.traffic === true ? "in traffic" : null,
  ]
    .filter(Boolean)
    .join("; ");
  return { text, aria };
}

// ---------------------------------------------------------------------------------------------- attack / defend

export interface RacecraftMark {
  /** Experienced wording: a caps tag ("BEST T3", "WATCH T7"); null for simple wording. */
  tag: string | null;
  /** Simple wording: a phrase beside the row's label ("you catch it at T3"); null for experienced wording. */
  sub: string | null;
  aria: string;
}

/**
 * The Ahead / Behind row's racecraft mark: only when the backend's verdict is "clear" (one corner stands out), only in
 * a race, and only for the same car the gap row shows (a position change makes the comparison about another car).
 * Corners use the track's official short label when the track sheet maps it ("T3"), else the learned name.
 */
export function racecraftMark(
  rc: RacecraftView | null,
  side: "ahead" | "behind",
  opts: { carIndex?: number | null; trackModel?: TrackModelNext | null; simple?: boolean } = {},
): RacecraftMark | null {
  if (!rc || rc.mode !== "race") return null;
  const s: RacecraftSide | null = rc[side];
  if (!s || s.verdict !== "clear" || !s.corner || !finite(s.corner.delta_s)) return null;
  if (finite(opts.carIndex) && finite(s.car_index) && s.car_index !== opts.carIndex) return null;
  const label = cornerLabelOf(opts.trackModel, s.corner.name);
  const gain = Math.abs(s.corner.delta_s).toFixed(1);
  const where = s.corner.text || label;
  if (side === "ahead") {
    return {
      tag: opts.simple ? null : `BEST ${label}`,
      sub: opts.simple ? `you catch it at ${label}` : null,
      aria: `best chance on the car ahead at ${where}, you gain about ${gain} seconds a lap there`,
    };
  }
  return {
    tag: opts.simple ? null : `WATCH ${label}`,
    sub: opts.simple ? `it catches you at ${label}` : null,
    aria: `the car behind is quickest at ${where}, about ${gain} seconds a lap`,
  };
}

// --------------------------------------------------------------------------------------------- the radio's calls

/** The newest health call of a topic within `maxAgeS` of `nowS` (device clock; 2 s of clock skew allowed). */
export function recentCall(
  ch: CarHealthView | null,
  topic: string,
  nowS: number,
  maxAgeS: number,
): HealthCall | null {
  for (const c of ch?.calls ?? []) {
    if (c.topic !== topic || !finite(c.t_unix)) continue;
    const age = nowS - c.t_unix;
    if (age >= -2 && age <= maxAgeS) return c;
  }
  return null;
}

// ---------------------------------------------------------------------------------------------------- settings

export const DEFAULT_CAR_HEALTH_SETTINGS: Readonly<CarHealthSettings> = Object.freeze({
  tyre_calls: true,
  wear_calls: true,
  fuel_calls: true,
  slip_calls: "detailed",
});

const SLIP_VALUES: ReadonlySet<string> = new Set<SlipCallsSetting>(["off", "detailed", "normal"]);

/** The settings when the payload is complete and valid, else null (never guessed: the card then shows unknown). */
export function carHealthSettingsOf(raw: unknown): CarHealthSettings | null {
  if (!raw || typeof raw !== "object") return null;
  const v = raw as Partial<Record<keyof CarHealthSettings, unknown>>;
  if (typeof v.tyre_calls !== "boolean" || typeof v.wear_calls !== "boolean" || typeof v.fuel_calls !== "boolean") {
    return null;
  }
  if (typeof v.slip_calls !== "string" || !SLIP_VALUES.has(v.slip_calls)) return null;
  return {
    tyre_calls: v.tyre_calls,
    wear_calls: v.wear_calls,
    fuel_calls: v.fuel_calls,
    slip_calls: v.slip_calls as SlipCallsSetting,
  };
}
