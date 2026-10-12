// Drive › Car strategy tile (lane "strategy"; design spec 5.1 tile row, strategy spec 10): pure view model from the
// live snapshot's `strategy` block. No React, so every rule is tested in plain node (view.test.ts).
//
// The tile takes the bottom-left slot (Inputs, last 12 s) only in a race of at least STRATEGY_TILE_MIN_LAPS laps
// (in a 3-5 lap sprint half the tile never changes: the Inputs trace earns the slot there). Mode and race length
// change only at a session change, so nothing moves while driving (P2). Six fixed rows (the label, then the value):
//   Ahead       "+1.8 s · closing 0.3/lap"        tags IN PIT / DRS / CLOSE / 1 STOP / BEST T3 (health lane:
//                                                 the corner that stands out); unsettled values dimmed
//   Behind      "0.8 s · closing 0.2/lap"         DRS, or CLOSE and closing, is amber (with its word, never colour alone);
//                                                 WATCH T7 where the car behind is quickest (health lane)
//   Pit window  "L38-44 · best L41" / "L41" / "No stop needed" / "Not enough laps yet"; beside the label (health
//               lane) where a stop now would rejoin: "Box now ≈ P7 (P6–8)" (simple: "If you stop now: about 7th");
//               with "No stop needed", "Stop rules: not sent by the game" (F2 support: the game never sends the
//               race's tyre or pit-stop rules, so "no stop needed" is about the tyres, never the rules)
//   Undercut    "ahead marginal · behind threat"; "Laps to go" instead when no stop is needed (and for simple wording)
//   Fuel        "+0.4 laps" / "−0.3 laps · lift & coast 2.1 s/lap" / "On the limit" (amber when tight or short)
//   Weather     "Light rain in 10 min · 7 laps" / "Light rain after the flag" / "Dry for 15 min"; under SC / VSC the
//               row becomes Safety car: "Stop 12 s · green 19 s (estimate)" with the band word VSC / SC
// Amber means act or watch now, so it is kept for that: a car behind in DRS range or closing within a second, a pit
// window in its last laps, an undercut threat while the window is open, fuel tight or short, rain before the flag.
// Footer: the newest strategy call for this driver, verbatim (P9), while it holds (its TTL, or two laps). Unknown is
// "-" (P5); game figures say "(game)", Pitwall rules of thumb "(estimate)" (P8). Simple wording (the seated driver's
// profile) swaps the jargon for plain words, and leaves out the calls meant for experienced drivers.

import type { DriveModel } from "../drive/model";
import type { SnapshotNext, TrackModelNext } from "../drive/types";
import { racecraftMark, rejoinLine, snapRacecraft } from "../carhealth/view"; // health lane (pitwall.carhealth)
import type { RacecraftView } from "../carhealth/types"; // health lane
import type { CallView, CarGap, CutStatus, StrategyView, Tier } from "./types";
import {
  compoundPlural,
  finite,
  one,
  plural,
  sentence,
  signedOne,
  tierSuffix,
  UNKNOWN,
  weatherCategory,
  weatherWord,
} from "./words";

/** A trend under this (s per lap, either way) reads "steady" (strategy/gaps.py CLOSING_MIN). */
export const CLOSING_MIN = 0.05;
/** The forecast horizon the engine looks at for the next change (strategy/weather.py, minutes). */
export const FORECAST_HORIZON_MIN = 15;
/** Races shorter than this keep the Inputs tile: in a sprint the pit, undercut and fuel rows never change. */
export const STRATEGY_TILE_MIN_LAPS = 8;
/** A call stays on the footer for its TTL, and at least this long (seconds)... */
export const CALL_SHOWN_MIN_S = 30;
/** ...and never once the race is this many laps past it. */
export const CALL_SHOWN_MAX_LAPS = 2;
/** The modes of contract version 1. */
const MODES = new Set(["race", "practice", "off"]);

/**
 * The snapshot's strategy block when it is one this dashboard understands (version 1, a known mode), else null: an
 * older server (no block), a newer contract or a malformed payload all leave Drive exactly as it was.
 */
export function strategyOf(raw: unknown): StrategyView | null {
  if (!raw || typeof raw !== "object") return null;
  const v = raw as Partial<StrategyView>;
  if (v.version !== 1 || typeof v.mode !== "string" || !MODES.has(v.mode)) return null;
  return { ...(v as StrategyView), calls: Array.isArray(v.calls) ? v.calls : [] };
}

/** The strategy block of a live snapshot (see strategyOf). */
export function snapStrategy(s: Pick<SnapshotNext, "strategy"> | null | undefined): StrategyView | null {
  return strategyOf(s?.strategy);
}

/** A race long enough for strategy (STRATEGY_TILE_MIN_LAPS); both only change at a session change (P2). */
function longRace(v: StrategyView | null): boolean {
  return v?.mode === "race" && finite(v.total_laps) && v.total_laps >= STRATEGY_TILE_MIN_LAPS;
}

/** The tile replaces Inputs only in a race of STRATEGY_TILE_MIN_LAPS laps or more. */
export function showStrategyTile(s: Pick<SnapshotNext, "strategy"> | null | undefined): boolean {
  return longRace(snapStrategy(s));
}

/** "+0.4 laps" from this race's own fuel use (strategy/fuel.py), for the Tyres & energy line; null until two green
 * laps are measured (the tile then keeps the game's figure with "(game)"). */
export function measuredFuelMargin(s: Pick<SnapshotNext, "strategy"> | null | undefined): string | null {
  const f = snapStrategy(s)?.fuel;
  if (!f || f.status === "unknown" || !finite(f.margin_laps)) return null;
  return `${signedOne(f.margin_laps)} laps`;
}

// --------------------------------------------------------------------------------------------------- tile

export type StrategyRowKey = "ahead" | "behind" | "window" | "undercut" | "fuel" | "weather";

export interface StrategyTag {
  /** A short signal word in caps (9.3): "DRS", "IN PIT", "1 STOP". */
  text: string;
  tone: "warn" | "info" | "neutral";
}

export interface StrategyRowView {
  key: StrategyRowKey;
  label: string;
  /** One line; "-" when unknown. */
  text: string;
  /** Small words on the label's line where the tags go (the row has none then): "Stop rules: not sent by the game"
   * beside "No stop needed" (F2 support); null otherwise. */
  note: string | null;
  /** Amber text (within a second, fuel tight / short, rain coming, a safety car): the tags say why in words. */
  tone: "plain" | "warn";
  /** The value is the last settled one while the gap is in doubt (position change, a car in the pit lane). */
  dim: boolean;
  tags: StrategyTag[];
  /** (health lane) A short phrase beside the label: "Box now ≈ P7 (P6–8)" on the pit window, "you catch it at T3"
   * on Ahead for simple wording; null when there is none. */
  sub: string | null;
  /** The whole row for screen readers. */
  aria: string;
}

export interface StrategyTileView {
  /** mode === "race": the tile takes the Inputs slot. */
  show: boolean;
  title: string;
  /** "L34/52 · P6"; "-" when neither is known. */
  aside: string;
  synthetic: boolean;
  rows: [StrategyRowView, StrategyRowView, StrategyRowView, StrategyRowView, StrategyRowView, StrategyRowView];
  /** The newest call, verbatim ("L18 · Pit window is open: …"), or why there is none. */
  foot: string;
  /** The call's level for the footer chip; null when there is no call. */
  footLevel: CallView["level"] | null;
}

export interface StrategyTileOptions {
  /** The seated driver's profile wants plain wording. */
  simple?: boolean;
  /** Now (unix seconds, this device's clock): a call past its TTL leaves the footer. Unknown: only the lap rule. */
  nowS?: number | null;
}

function row(key: StrategyRowKey, label: string, text: string, extra: Partial<StrategyRowView> = {}): StrategyRowView {
  const r: StrategyRowView = {
    key,
    label,
    text,
    note: null,
    tone: "plain",
    dim: false,
    tags: [],
    sub: null,
    aria: "",
    ...extra,
  };
  if (!r.aria) r.aria = `${label}: ${text === UNKNOWN ? "unknown" : text}`;
  return r;
}

function unknownRow(key: StrategyRowKey, label: string): StrategyRowView {
  return row(key, label, UNKNOWN);
}

function stopsTag(n: number | null): StrategyTag | null {
  if (!finite(n) || n <= 0) return null;
  return { text: n === 1 ? "1 STOP" : `${n} STOPS`, tone: "neutral" };
}

/** "closing 0.3/lap" / "pulling away 0.3/lap" / "steady"; null without a trend. Plain: "you gain 0.3 s a lap". */
function trendText(t: number | null, side: "ahead" | "behind", simple: boolean): string | null {
  if (!finite(t)) return null;
  const amount = Math.abs(t).toFixed(1);
  if (Math.abs(t) < CLOSING_MIN || Number(amount) === 0) return "steady";
  const closing = t < 0;
  if (simple) {
    // ahead closing = you gain on it; behind closing = it gains on you
    const youGain = side === "ahead" ? closing : !closing;
    return youGain ? `you gain ${amount} s a lap` : `it gains ${amount} s a lap`;
  }
  if (closing) return `closing ${amount}/lap`;
  return side === "ahead" ? `pulling away ${amount}/lap` : `dropping back ${amount}/lap`;
}

function trendAria(t: number | null, side: "ahead" | "behind"): string | null {
  if (!finite(t)) return null;
  const amount = Math.abs(t).toFixed(1);
  if (Math.abs(t) < CLOSING_MIN || Number(amount) === 0) return "steady";
  if (t < 0) return `closing ${amount} seconds a lap`;
  return side === "ahead" ? `pulling away ${amount} seconds a lap` : `dropping back ${amount} seconds a lap`;
}

/** (health lane) What the gap rows read from the racecraft block: attack / defend per corner. */
interface RacecraftInput {
  rc: RacecraftView | null;
  trackModel: TrackModelNext | null;
}

function gapRow(v: StrategyView, side: "ahead" | "behind", simple: boolean, race: RacecraftInput | null = null): StrategyRowView {
  const label = side === "ahead" ? (simple ? "Car ahead" : "Ahead") : simple ? "Car behind" : "Behind";
  const g = v.gaps;
  const car: CarGap | null = g ? (side === "ahead" ? g.ahead : g.behind) : null;
  if (!car) {
    if (side === "ahead" && v.position === 1) return row(side, label, "You are leading");
    if (side === "behind" && finite(v.position) && finite(v.cars) && v.position === v.cars && v.cars > 0) {
      return row(side, label, "No car behind");
    }
    return unknownRow(side, label);
  }
  const gap = finite(car.gap_s) ? (side === "ahead" ? `+${one(car.gap_s)} s` : `${one(car.gap_s)} s`) : UNKNOWN;
  const trend = trendText(car.trend_s_per_lap, side, simple);
  const text = gap === UNKNOWN ? UNKNOWN : trend ? `${gap} · ${trend}` : gap;
  const tags: StrategyTag[] = [];
  const drs = car.drs_range === true;
  const near = drs || car.within_1s === true;
  const closing = finite(car.trend_s_per_lap) && car.trend_s_per_lap <= -CLOSING_MIN;
  // amber only for what to watch now: the car behind in DRS range, or within a second and still closing (in a pack
  // race "within a second" alone was amber for most laps, and amber stopped meaning anything)
  const warn = side === "behind" && (drs || (near && closing));
  const close = near ? (drs && !simple ? "DRS" : "CLOSE") : null;
  if (car.in_pit) tags.push({ text: "IN PIT", tone: "info" });
  if (close) tags.push({ text: close, tone: warn ? "warn" : side === "ahead" ? "info" : "neutral" });
  const stops = stopsTag(car.stops);
  if (stops) tags.push(stops);
  // --- health lane: the corner that stands out against this car (verdict "clear" only, same car only) ---
  const mark = race
    ? racecraftMark(race.rc, side, { carIndex: car.car_index, trackModel: race.trackModel, simple })
    : null;
  if (mark?.tag) tags.push({ text: mark.tag, tone: "neutral" });
  // --- end health lane ---
  const parts = [
    `${side === "ahead" ? "Car ahead" : "Car behind"}: ${finite(car.gap_s) ? `${one(car.gap_s)} seconds` : "gap unknown"}`,
    trendAria(car.trend_s_per_lap, side),
    car.drs_range === true ? "in DRS range" : car.within_1s === true ? "within a second" : null,
    car.in_pit ? "in the pit lane" : null,
    finite(car.stops) ? plural(car.stops, "stop") : null,
    car.settled || !finite(car.gap_s) ? null : "last settled value",
    mark?.aria ?? null, // health lane
  ].filter(Boolean);
  return row(side, label, text, {
    tone: warn ? "warn" : "plain",
    dim: !car.settled,
    tags,
    sub: mark?.sub ?? null, // health lane
    aria: parts.join(", "),
  });
}

/** Beside "No stop needed" when the server says the race's rules are not known (F2 support, contract
 * dashboard_strings.strategy_tile_rules_line). */
export const STOP_RULES_LINE = "Stop rules: not sent by the game";

/** The race's stop rules are not known (the server's pit.rules; absent from older servers, which then say nothing). */
export function stopRulesUnknown(v: Pick<StrategyView, "pit"> | null | undefined): boolean {
  return v?.pit?.rules?.known === false;
}

/** Laps before the pit window opens from which "Box now ≈ P7" is shown (before that it is noise: P20 on lap 1). */
export const REJOIN_LEAD_LAPS = 3;

/** (health lane) The rejoin line is worth a glance: in the pit lane (the held prediction), under a safety car or VSC
 * (a cheap stop), or from REJOIN_LEAD_LAPS laps before the pit window opens. */
function rejoinRelevant(v: StrategyView): boolean {
  if (v.pit?.rejoin?.frozen === true) return true;
  const sc = v.safety_car?.status;
  if (sc === "full" || sc === "virtual") return true;
  const w = v.pit?.window;
  return !!w && finite(v.lap) && finite(w.open_lap) && v.lap >= w.open_lap - REJOIN_LEAD_LAPS;
}

/** (health lane) The pit window row with "Box now ≈ P7 (P6–8)" beside its label: where the player would come out
 * (rejoin v2 only, only while a stop is still needed and the line is relevant, see rejoinRelevant). A beginner never
 * gets the game's own figure alone. */
function windowRowWithRejoin(v: StrategyView, simple: boolean): StrategyRowView {
  const r = windowRow(v, simple);
  if (v.pit?.stop_needed === false || !rejoinRelevant(v)) return r;
  const rj = rejoinLine(v.pit?.rejoin, simple);
  if (!rj || (simple && rj.gameOnly)) return r;
  return { ...r, sub: rj.text, aria: `${r.aria}; ${rj.aria}` };
}

function windowRow(v: StrategyView, simple: boolean): StrategyRowView {
  const label = simple ? "Pit stop" : "Pit window";
  const p = v.pit;
  if (!p) return unknownRow("window", label);
  if (p.stop_needed === false) {
    // a tyre statement, never a rule: the game does not send whether a stop is compulsory
    const text = (p.stops_done ?? 0) > 0 ? "No more stops needed" : "No stop needed";
    const note = stopRulesUnknown(v) ? STOP_RULES_LINE : null;
    return row("window", label, text, { note, aria: `${label}: ${text}${note ? `. ${note}` : ""}` });
  }
  const w = p.window;
  if (w) {
    const single = w.open_lap === w.close_lap;
    const best = finite(w.ideal_lap) && !single ? w.ideal_lap : null;
    const tags: StrategyTag[] = [];
    if (w.overdue) {
      // at or past the wear limit: the window is this lap (the radio has said "this lap or next" already)
      const text = simple ? `Tyres at the wear limit${tierSuffix(w.tier)}` : `L${w.close_lap} · at the wear limit${tierSuffix(w.tier)}`;
      return row("window", label, text, {
        tone: "warn",
        tags: [{ text: "LIMIT", tone: "warn" }],
        aria: `Pit window: the tyres are at the wear limit${w.tier !== "measured" ? `, ${w.tier === "game" ? "game" : "Pitwall"} estimate` : ""}`,
      });
    }
    const range = single ? `${w.open_lap}` : `${w.open_lap}-${w.close_lap}`;
    const text = simple
      ? `${single ? `Stop on lap ${range}` : `Stop lap ${range}`}${best != null ? ` · best ${best}` : ""}${tierSuffix(w.tier)}`
      : `L${range}${best != null ? ` · best L${best}` : ""}${tierSuffix(w.tier)}`;
    const lap = v.lap;
    if (finite(lap) && lap >= w.open_lap && lap <= w.close_lap) {
      tags.push(lap >= w.close_lap - 1 ? { text: "LAST LAPS", tone: "warn" } : { text: "OPEN", tone: "info" });
    }
    if (p.two_stops) tags.push({ text: "2 STOPS", tone: "neutral" });
    const aria =
      `Pit window: ${single ? `lap ${w.open_lap}` : `laps ${w.open_lap} to ${w.close_lap}`}` +
      `${best != null ? `, best around lap ${best}` : ""}${w.tier !== "measured" ? `, ${w.tier === "game" ? "game" : "Pitwall"} estimate` : ""}` +
      `${tags.length ? `, ${tags.map((t) => t.text.toLowerCase()).join(", ")}` : ""}`;
    return row("window", label, text, { tags, tone: tags.some((t) => t.tone === "warn") ? "warn" : "plain", aria });
  }
  if (p.game_window && p.game_window.latest_lap > 0) {
    const gw = p.game_window;
    const text = gw.ideal_lap > 0 ? `L${gw.ideal_lap}-${gw.latest_lap} (game)` : `By L${gw.latest_lap} (game)`;
    return row("window", label, text);
  }
  const note = p.note ?? v.tyres?.note ?? null;
  return row("window", label, note ? shortNote(note) : "Not enough laps yet", {
    aria: `${label}: ${note ?? "not enough laps yet"}`,
  });
}

/** The engine's notes on one line: the part before any ":" or ";" ("not enough laps on this set yet: 3 green laps
 * needed" -> "Not enough laps on this set yet"); the whole note goes to screen readers. */
export function shortNote(note: string): string {
  return sentence(note.split(/[:;]/)[0]!.trim());
}

const AHEAD_WORD: Record<CutStatus, string> = { likely: "likely", marginal: "marginal", unlikely: "unlikely", unknown: UNKNOWN };
const THREAT_WORD: Record<CutStatus, string> = { likely: "threat", marginal: "possible", unlikely: "unlikely", unknown: UNKNOWN };

/** "Laps to go" in the undercut slot: when no stop is needed the undercut row only repeated "No stop needed", and
 * for simple wording ("Pit first" was not clear to a child). The laps the player still drives (a lapped player's
 * race ends a lap early: the engine counts that). */
function lapsToGoRow(v: StrategyView): StrategyRowView {
  const label = "Laps to go";
  if (!finite(v.laps_remaining)) return unknownRow("undercut", label);
  const n = Math.max(0, Math.ceil(v.laps_remaining - 1e-6));
  const text = n === 0 ? "Chequered flag" : n === 1 ? "Last lap" : String(n);
  return row("undercut", label, text, { aria: n === 0 ? "The race is over" : `${plural(n, "lap")} to go` });
}

/** The window is open on this lap (an undercut threat matters then, not before). */
function windowOpen(v: StrategyView): boolean {
  const w = v.pit?.window;
  return !!w && finite(v.lap) && v.lap >= w.open_lap && v.lap <= w.close_lap;
}

function undercutRow(v: StrategyView, simple: boolean): StrategyRowView {
  const label = "Undercut";
  const p = v.pit;
  if (simple || p?.stop_needed === false) return lapsToGoRow(v);
  const a = p?.undercut_ahead ?? null;
  const t = p?.undercut_threat ?? null;
  if (!p || (!a && !t)) return unknownRow("undercut", label);
  const aS = a?.status ?? "unknown";
  const tS = t?.status ?? "unknown";
  if (aS === "unknown" && tS === "unknown") {
    const why = a?.reason || t?.reason || null;
    return row("undercut", label, why ? shortNote(why) : UNKNOWN, { aria: `${label}: ${why ?? "unknown"}` });
  }
  const warn = tS === "likely" && windowOpen(v);
  const text = `ahead ${AHEAD_WORD[aS]} · behind ${THREAT_WORD[tS]}`;
  const tier = (x: { tier: Tier } | null) => (x && x.tier !== "measured" ? ` (${x.tier === "game" ? "game" : "Pitwall"} estimate)` : "");
  const aria =
    `Undercut on the car ahead: ${aS === "unknown" ? "unknown" : aS}${aS !== "unknown" ? tier(a) : ""}; ` +
    `from the car behind: ${tS === "unknown" ? "unknown" : tS}${tS !== "unknown" ? tier(t) : ""}`;
  return row("undercut", label, text, { tone: warn ? "warn" : "plain", tags: warn ? [{ text: "THREAT", tone: "warn" }] : [], aria });
}

function fuelRow(v: StrategyView, simple: boolean): StrategyRowView {
  const label = "Fuel";
  const f = v.fuel;
  if (!f) return unknownRow("fuel", label);
  if (f.status === "unknown" || !finite(f.margin_laps)) {
    if (finite(f.game_margin_laps)) {
      const g = f.game_margin_laps;
      const text = !simple
        ? `${signedOne(g)} laps (game)`
        : onLimit(g)
          ? "On the limit (game)"
          : g < 0
            ? `${one(-g)} laps short (game)`
            : `${one(g)} laps spare (game)`;
      return row("fuel", label, text, {
        aria: `Fuel: ${signedOne(g)} laps at the flag, the game's figure; Pitwall needs two green laps`,
      });
    }
    return unknownRow("fuel", label);
  }
  const m = f.margin_laps;
  const lc = f.lift_coast;
  let text: string;
  if (simple) {
    // "lift & coast" is jargon: "lift early" (lift off before the braking point; the radio says it in full)
    const lcShort = lc ? (lc.feasible ? "lift early" : "too much to save") : null;
    text =
      f.status === "short"
        ? `${one(Math.abs(m))} laps short${lcShort ? ` · ${lcShort}` : ""}`
        : onLimit(m)
          ? "On the limit"
          : f.status === "tight"
            ? `Only ${one(m)} laps spare`
            : `${one(m)} laps spare`;
  } else {
    const lcText = lc ? (lc.feasible ? `lift & coast ${one(lc.seconds_per_lap)} s/lap` : "beyond lift & coast") : null;
    text = onLimit(m) && f.status !== "short" ? "On the limit" : `${signedOne(m)} laps`;
    if (f.status === "short" && lcText) text += ` · ${lcText}`;
  }
  const tags: StrategyTag[] =
    f.status === "short" ? [{ text: "SHORT", tone: "warn" }] : f.status === "tight" ? [{ text: "TIGHT", tone: "warn" }] : [];
  const aria =
    `Fuel: ${signedOne(m)} laps at the flag` +
    `${f.status === "short" || f.status === "tight" ? `, ${f.status}` : ""}` +
    `${lc && f.status === "short" ? (lc.feasible ? `, lift and coast about ${one(lc.seconds_per_lap)} seconds a lap, brake at your normal point` : ", more than lift and coast can save") : ""}`;
  return row("fuel", label, text, { tone: tags.length ? "warn" : "plain", tags, aria });
}

/** A margin that rounds to 0.0 laps reads "On the limit" (as the radio says it), never "Only 0.0 laps spare". */
function onLimit(m: number): boolean {
  return Math.abs(m) < 0.05;
}

function safetyCarRow(v: StrategyView, simple: boolean): StrategyRowView | null {
  const sc = v.safety_car;
  if (!sc || (sc.status !== "full" && sc.status !== "virtual")) return null;
  const full = sc.status === "full";
  const name = full ? "SC" : "VSC";
  const b = sc.box;
  let text = full ? "Safety car out" : "Virtual safety car";
  let aria = full ? "Safety car" : "Virtual safety car";
  if (b) {
    if (!b.stop_needed) {
      text = "No stop needed";
      aria += ": no stop needed";
    } else if (finite(b.pit_loss_s)) {
      const loss = Math.round(b.pit_loss_s);
      const green = finite(b.green_pit_loss_s) ? Math.round(b.green_pit_loss_s) : null;
      text = simple
        ? `Cheap stop now: ${loss} s${green != null ? ` (usually ${green} s)` : ""}`
        : `Stop ${loss} s${green != null ? ` · green ${green} s` : ""}${tierSuffix(b.tier)}`;
      aria +=
        `: a stop costs about ${Math.round(b.pit_loss_s)} seconds now` +
        `${finite(b.green_pit_loss_s) ? `, ${Math.round(b.green_pit_loss_s)} under green` : ""}` +
        `${b.tier !== "measured" ? `, ${b.tier === "game" ? "game" : "Pitwall"} estimate` : ""}`;
    } else {
      text = "Stop cost unknown";
      aria += ": no pit stop measured yet";
    }
  }
  return row("weather", "Safety car", text, { tone: "warn", tags: [{ text: name, tone: "warn" }], aria });
}

function weatherRow(v: StrategyView, simple: boolean): StrategyRowView {
  const sc = safetyCarRow(v, simple);
  if (sc) return sc;
  const label = "Weather";
  const w = v.weather;
  if (!w) return unknownRow("weather", label);
  if (w.crossover) {
    const what = w.crossover.compound === "slick" ? "Slicks" : sentence(compoundPlural(w.crossover.compound) ?? w.crossover.compound);
    const text = `${what} ${one(w.crossover.gain_s)} s/lap faster (game)`;
    return row("weather", label, text, {
      tone: "warn",
      tags: [{ text: "TYRES", tone: "warn" }],
      aria: `Weather: the game's tyre model has ${what.toLowerCase()} ${one(w.crossover.gain_s)} seconds a lap faster`,
    });
  }
  const now = weatherWord(w.now);
  const nowCat = weatherCategory(w.now);
  const n = w.next_change;
  if (n) {
    const word = weatherWord(n.weather) ?? "A change";
    // a change the forecast puts after the chequered flag is nothing to act on: no tag, no amber (the radio says
    // nothing about it either)
    if (finite(n.in_laps) && finite(v.laps_remaining) && n.in_laps >= v.laps_remaining) {
      return row("weather", label, `${word} after the flag`, {
        aria: `Weather: ${now ? `${now.toLowerCase()} now, ` : ""}${word.toLowerCase()} forecast in about ${Math.round(n.in_min)} minutes, after the flag`,
      });
    }
    const laps = finite(n.in_laps) && n.in_laps > 0 ? ` · ${plural(n.in_laps, "lap")}` : "";
    const text = `${word} in ${Math.round(n.in_min)} min${laps}`;
    const nextCat = weatherCategory(n.weather);
    const toRain = nowCat === "dry" && nextCat != null && nextCat !== "dry";
    const toDry = nowCat != null && nowCat !== "dry" && nextCat === "dry";
    const tags: StrategyTag[] = toRain ? [{ text: "RAIN", tone: "warn" }] : toDry ? [{ text: "DRYING", tone: "info" }] : [];
    return row("weather", label, text, {
      tone: toRain ? "warn" : "plain",
      tags,
      aria: `Weather: ${now ? `${now.toLowerCase()} now, ` : ""}${word.toLowerCase()} forecast in about ${Math.round(n.in_min)} minutes${laps ? `, about ${n.in_laps} laps` : ""}`,
    });
  }
  // No change ahead: how far the forecast reaches (the engine looks 15 min ahead; a short race sends 10).
  const reach = Math.min(FORECAST_HORIZON_MIN, Math.max(0, ...w.forecast.map((f) => (finite(f.in_min) ? f.in_min : 0))));
  if (!now) return unknownRow("weather", label);
  if (reach <= 0) return row("weather", label, now);
  const text = nowCat === "dry" ? `Dry for ${Math.round(reach)} min` : `${now} for ${Math.round(reach)} min`;
  return row("weather", label, text, { aria: `Weather: ${now.toLowerCase()}, no change forecast for ${Math.round(reach)} minutes` });
}

function asideText(v: StrategyView): string {
  const lap = finite(v.lap) ? (finite(v.total_laps) && v.total_laps > 0 ? `L${v.lap}/${v.total_laps}` : `L${v.lap}`) : null;
  const pos = finite(v.position) && v.position > 0 ? `P${v.position}` : null;
  return [lap, pos].filter(Boolean).join(" · ") || UNKNOWN;
}

/** The calls this driver hears: a driver with simple wording never hears (or sees) the experienced-only ones. */
export function callsFor(v: Pick<StrategyView, "calls">, simple: boolean): CallView[] {
  return v.calls.filter((c) => !(simple && c.audience === "experienced"));
}

/** The words of a call for this driver: the plain ones for simple wording, when the call has them. */
export function callWords(c: Pick<CallView, "text" | "text_simple">, simple: boolean): string {
  return simple && c.text_simple ? c.text_simple : c.text;
}

/** The call still holds: within its TTL (at least CALL_SHOWN_MIN_S) and fewer than CALL_SHOWN_MAX_LAPS laps ago. An
 * instruction past its moment ("box next lap" two laps on) is worse than no call. */
export function callInDate(c: CallView, lap: number | null | undefined, nowS?: number | null): boolean {
  if (finite(lap) && finite(c.lap) && lap - c.lap >= CALL_SHOWN_MAX_LAPS) return false;
  if (finite(nowS) && finite(c.t_unix)) {
    const ttl = finite(c.ttl_s) ? c.ttl_s : 0;
    if (nowS - c.t_unix > Math.max(ttl, CALL_SHOWN_MIN_S)) return false;
  }
  return true;
}

function footText(
  v: StrategyView,
  stale: boolean,
  simple: boolean,
  nowS: number | null | undefined,
): { foot: string; level: CallView["level"] | null } {
  const c = callsFor(v, simple)[0];
  const prefix = stale ? "Last known · " : "";
  if (!c || !c.text) return { foot: `${prefix}No strategy calls yet`, level: null };
  if (!callInDate(c, v.lap, nowS)) return { foot: `${prefix}No new strategy calls`, level: null };
  return { foot: `${prefix}${finite(c.lap) ? `L${c.lap} · ` : ""}${callWords(c, simple)}`, level: c.level };
}

/** Drive › Coach radio strip, with the radio off: the newest strategy alert still in date for this driver (fuel
 * critical, the safety-car opportunity, the last laps of the window), else null. */
export function stripAlert(
  s: Pick<SnapshotNext, "strategy"> | null | undefined,
  opts: { simple?: boolean; nowS?: number | null } = {},
): string | null {
  const v = snapStrategy(s);
  if (!v || v.mode !== "race") return null;
  const simple = !!opts.simple;
  const c = callsFor(v, simple).find((x) => x.level === "alert");
  if (!c || !c.text || !callInDate(c, v.lap, opts.nowS)) return null;
  return `${finite(c.lap) ? `L${c.lap} · ` : ""}${callWords(c, simple)}`;
}

const EMPTY_VIEW: StrategyView = {
  version: 1,
  mode: "off",
  reason: null,
  session_id: null,
  synthetic: false,
  lap: null,
  total_laps: null,
  laps_remaining: null,
  position: null,
  cars: null,
  gaps: null,
  tyres: null,
  fuel: null,
  pit: null,
  safety_car: null,
  weather: null,
  calls: [],
};

/**
 * The strategy tile (Drive › Car, bottom-left slot). `show` is false outside a race: the page keeps the Inputs tile.
 * While the data is in doubt (stale, offline) the page dims the tile and the values are the last known ones.
 */
export function strategyTile(
  snap:
    | (Pick<SnapshotNext, "strategy"> & Partial<Pick<SnapshotNext, "racecraft" | "track_model" | "session_id">>)
    | null
    | undefined,
  model: Pick<DriveModel, "dim" | "state"> | null = null,
  opts: StrategyTileOptions = {},
): StrategyTileView {
  const simple = !!opts.simple;
  const v = snapStrategy(snap) ?? EMPTY_VIEW;
  const stale = !!model?.dim;
  const { foot, level } = footText(v, stale, simple, opts.nowS);
  // health lane (pitwall.carhealth): attack / defend marks on the gap rows
  const race: RacecraftInput = { rc: snapRacecraft(snap), trackModel: snap?.track_model ?? null };
  return {
    show: longRace(v),
    title: "Strategy",
    aside: asideText(v),
    synthetic: v.synthetic === true,
    rows: [
      gapRow(v, "ahead", simple, race),
      gapRow(v, "behind", simple, race),
      windowRowWithRejoin(v, simple), // health lane: "Box now ≈ P7 (P6–8)"
      undercutRow(v, simple),
      fuelRow(v, simple),
      weatherRow(v, simple),
    ],
    foot,
    footLevel: level,
  };
}
