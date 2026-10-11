// Drive › Car strategy tile (lane "strategy"; design spec 5.1 tile row, strategy spec 10): pure view model from the
// live snapshot's `strategy` block. No React, so every rule is tested in plain node (view.test.ts).
//
// The tile takes the bottom-left slot (Inputs, last 12 s) only while `strategy.mode === "race"`. The mode changes
// only at a session change, so nothing moves while driving (P2). Six fixed rows (the label, then the value):
//   Ahead       "+1.8 s · closing 0.3/lap"        tags IN PIT / DRS / WITHIN 1 S / 1 STOP; unsettled values dimmed
//   Behind      "0.8 s · closing 0.2/lap"         band word DRS or WITHIN 1 S (amber, never colour alone)
//   Pit window  "L38-44 · best ~L41" / "No stop needed" / "Not enough laps yet"
//   Undercut    "ahead marginal · behind threat"
//   Fuel        "+0.4 laps" / "−0.3 laps · lift & coast 2.1 s/lap" (amber)
//   Weather     "Light rain in ~10 min (≈7 laps)" / "Dry for 15 min"; under SC / VSC the row becomes Safety car:
//               "Stop ≈12 s, green 19 s (estimate)" with the band word VSC / SC
// Footer: the newest strategy call, verbatim (P9). Unknown is "-" (P5); game figures say "(game)", Pitwall rules of
// thumb "(estimate)" (P8). Simple wording (the seated driver's profile) swaps the jargon for plain words.

import type { DriveModel } from "../drive/model";
import type { SnapshotNext } from "../drive/types";
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

/** The tile replaces Inputs only in a race (the mode only changes at a session change, P2). */
export function showStrategyTile(s: Pick<SnapshotNext, "strategy"> | null | undefined): boolean {
  return snapStrategy(s)?.mode === "race";
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
  /** Amber text (within a second, fuel tight / short, rain coming, a safety car): the tags say why in words. */
  tone: "plain" | "warn";
  /** The value is the last settled one while the gap is in doubt (position change, a car in the pit lane). */
  dim: boolean;
  tags: StrategyTag[];
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
}

function row(key: StrategyRowKey, label: string, text: string, extra: Partial<StrategyRowView> = {}): StrategyRowView {
  const r: StrategyRowView = { key, label, text, tone: "plain", dim: false, tags: [], aria: "", ...extra };
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

function gapRow(v: StrategyView, side: "ahead" | "behind", simple: boolean): StrategyRowView {
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
  const close = car.drs_range === true ? "DRS" : car.within_1s === true ? "WITHIN 1 S" : null;
  if (car.in_pit) tags.push({ text: "IN PIT", tone: "info" });
  if (close) tags.push({ text: close, tone: side === "behind" ? "warn" : "info" });
  const stops = stopsTag(car.stops);
  if (stops) tags.push(stops);
  const parts = [
    `${side === "ahead" ? "Car ahead" : "Car behind"}: ${finite(car.gap_s) ? `${one(car.gap_s)} seconds` : "gap unknown"}`,
    trendAria(car.trend_s_per_lap, side),
    car.drs_range === true ? "in DRS range" : car.within_1s === true ? "within a second" : null,
    car.in_pit ? "in the pit lane" : null,
    finite(car.stops) ? plural(car.stops, "stop") : null,
    car.settled || !finite(car.gap_s) ? null : "last settled value",
  ].filter(Boolean);
  return row(side, label, text, {
    tone: side === "behind" && close ? "warn" : "plain",
    dim: !car.settled,
    tags,
    aria: parts.join(", "),
  });
}

function windowRow(v: StrategyView, simple: boolean): StrategyRowView {
  const label = simple ? "Pit stop" : "Pit window";
  const p = v.pit;
  if (!p) return unknownRow("window", label);
  if (p.stop_needed === false) {
    return row("window", label, p.stops_done > 0 ? "No more stops needed" : "No stop needed");
  }
  const w = p.window;
  if (w) {
    const range = `${w.open_lap}-${w.close_lap}`;
    const best = finite(w.ideal_lap) ? w.ideal_lap : null;
    const text = simple
      ? `Stop lap ${range}${best != null ? ` · best ${best}` : ""}${tierSuffix(w.tier)}`
      : `L${range}${best != null ? ` · best ~L${best}` : ""}${tierSuffix(w.tier)}`;
    const tags: StrategyTag[] = [];
    const lap = v.lap;
    if (finite(lap) && lap >= w.open_lap && lap <= w.close_lap) {
      tags.push(lap >= w.close_lap - 1 ? { text: "LAST LAPS", tone: "warn" } : { text: "OPEN", tone: "info" });
    }
    if (p.two_stops) tags.push({ text: "2 STOPS", tone: "neutral" });
    const aria =
      `Pit window: laps ${w.open_lap} to ${w.close_lap}` +
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

function undercutRow(v: StrategyView, simple: boolean): StrategyRowView {
  const label = simple ? "Pit first" : "Undercut";
  const p = v.pit;
  const a = p?.undercut_ahead ?? null;
  const t = p?.undercut_threat ?? null;
  if (!p || (!a && !t)) return unknownRow("undercut", label);
  const aS = a?.status ?? "unknown";
  const tS = t?.status ?? "unknown";
  if (aS === "unknown" && tS === "unknown") {
    const why = a?.reason || t?.reason || null;
    return row("undercut", label, why ? shortNote(why) : UNKNOWN, { aria: `${label}: ${why ?? "unknown"}` });
  }
  const warn = tS === "likely";
  if (simple) {
    const text =
      tS === "likely"
        ? "Car behind could pass you"
        : aS === "likely"
          ? "Could pass the car ahead"
          : aS === "marginal"
            ? "Might pass the car ahead"
            : aS === "unlikely"
              ? "Unlikely to pass car ahead"
              : tS === "marginal"
                ? "Car behind might pass you"
                : "Car behind unlikely to pass";
    return row("undercut", label, text, { tone: warn ? "warn" : "plain" });
  }
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
      return row("fuel", label, `${signedOne(f.game_margin_laps)} laps (game)`, {
        aria: `Fuel: ${signedOne(f.game_margin_laps)} laps at the flag, the game's figure; Pitwall needs two green laps`,
      });
    }
    return unknownRow("fuel", label);
  }
  const m = f.margin_laps;
  const lc = f.lift_coast;
  const lcText = lc ? (lc.feasible ? `lift & coast ${one(lc.seconds_per_lap)} s/lap` : "beyond lift & coast") : null;
  let text: string;
  if (simple) {
    // "a lap" is implied on the tile; the aria and the radio say it in full
    const lcShort = lc ? (lc.feasible ? `lift & coast ${one(lc.seconds_per_lap)} s` : "beyond lift & coast") : null;
    text =
      f.status === "short"
        ? `${one(Math.abs(m))} laps short${lcShort ? ` · ${lcShort}` : ""}`
        : f.status === "tight"
          ? `Only ${one(m)} laps spare`
          : `${one(m)} laps spare`;
  } else {
    text = `${signedOne(m)} laps${f.status === "short" && lcText ? ` · ${lcText}` : ""}`;
  }
  const tags: StrategyTag[] =
    f.status === "short" ? [{ text: "SHORT", tone: "warn" }] : f.status === "tight" ? [{ text: "TIGHT", tone: "warn" }] : [];
  const aria =
    `Fuel: ${signedOne(m)} laps at the flag` +
    `${f.status === "short" || f.status === "tight" ? `, ${f.status}` : ""}` +
    `${lc && f.status === "short" ? (lc.feasible ? `, lift and coast about ${one(lc.seconds_per_lap)} seconds a lap, brake at your normal point` : ", more than lift and coast can save") : ""}`;
  return row("fuel", label, text, { tone: tags.length ? "warn" : "plain", tags, aria });
}

function safetyCarRow(v: StrategyView): StrategyRowView | null {
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
      const green = finite(b.green_pit_loss_s) ? `, green ${Math.round(b.green_pit_loss_s)} s` : "";
      text = `Stop ≈${Math.round(b.pit_loss_s)} s${green}${tierSuffix(b.tier)}`;
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

function weatherRow(v: StrategyView): StrategyRowView {
  const sc = safetyCarRow(v);
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
    const laps = finite(n.in_laps) && n.in_laps > 0 ? ` (≈${n.in_laps} ${n.in_laps === 1 ? "lap" : "laps"})` : "";
    const text = `${word} in ~${Math.round(n.in_min)} min${laps}`;
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

function footText(v: StrategyView, stale: boolean): { foot: string; level: CallView["level"] | null } {
  const c = v.calls[0];
  const prefix = stale ? "Last known · " : "";
  if (!c || !c.text) return { foot: `${prefix}No strategy calls yet`, level: null };
  return { foot: `${prefix}${finite(c.lap) ? `L${c.lap} · ` : ""}${c.text}`, level: c.level };
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
  snap: Pick<SnapshotNext, "strategy"> | null | undefined,
  model: Pick<DriveModel, "dim" | "state"> | null = null,
  opts: StrategyTileOptions = {},
): StrategyTileView {
  const simple = !!opts.simple;
  const v = snapStrategy(snap) ?? EMPTY_VIEW;
  const stale = !!model?.dim;
  const { foot, level } = footText(v, stale);
  return {
    show: v.mode === "race",
    title: "Strategy",
    aside: asideText(v),
    synthetic: v.synthetic === true,
    rows: [
      gapRow(v, "ahead", simple),
      gapRow(v, "behind", simple),
      windowRow(v, simple),
      undercutRow(v, simple),
      fuelRow(v, simple),
      weatherRow(v),
    ],
    foot,
    footLevel: level,
  };
}
