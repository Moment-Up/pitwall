// Review › Session › Strategy (lane "strategy"; strategy spec 10): pure view models from GET
// /api/sessions/{id}/strategy (strategy/timeline.py). No React; tested in plain node (timeline.test.ts).
//
//   1. KPIs          "P8 → P3" · "Stops 1 (L24)" · "Pit loss 18.9 s (1 measured)" · "Fuel at the flag +0.4 laps"
//   2. Timeline      position (step line, reversed y, "↑ better"), gaps ahead / behind on a second panel with the
//                    same lap axis, player stops as dashed verticals with compound chips, SC / VSC laps as shaded
//                    bands with words, a weather row and a stint bar (compound colour + text label)
//   3. Stints        Compound · Laps · Wear at the end · Wear rate · Median lap
//   4. Pit stops     yours, then other cars' (measured) in a Disclosure, exclusions in words; cars are numbers only
//                    (no names: online lobbies carry other players' names)
//   5. Calls         lap, level chip, the backend's text verbatim (P9)
//   6. Tier note
// Unknown is "-"; game figures say "(game)", Pitwall rules of thumb "(estimate)"; synthetic sessions carry the
// SYNTHETIC chip (the page) and say so in the note.

import { lapTime } from "../drive/text";
import type { CallView, PitStopRow, StintRow, StrategyLapRecord, StrategyTimeline } from "./types";
import {
  callChip,
  compoundColour,
  compoundShort,
  compoundWord,
  finite,
  one,
  plural,
  safetyCarShort,
  safetyCarWord,
  sentence,
  signedOne,
  UNKNOWN,
  weatherWord,
  type StrategyTerm,
} from "./words";

// ------------------------------------------------------------------------------------------------- state

export type TimelineStateKind = "ok" | "not_race" | "unsupported_game" | "before_tracking" | "no_laps" | "unavailable";

export interface TimelineState {
  kind: TimelineStateKind;
  title: string;
  text: string;
}

/** Sessions the strategy tab is shown for (6.2): races only. */
export function isRaceSession(s: { session_type?: string | null } | null | undefined): boolean {
  return (s?.session_type ?? "").toLowerCase() === "race";
}

/** Games whose race timing the strategy engine reads (strategy spec 16: F1 25 only). */
export function strategyGame(game: string | null | undefined): boolean {
  return !!game && game.toLowerCase().startsWith("f1");
}

/** What the tab can show: the timeline, or why not, in words. */
export function timelineState(
  session: { session_type?: string | null; game?: string | null },
  t: Pick<StrategyTimeline, "available" | "reason" | "laps"> | null | undefined,
): TimelineState {
  if (!isRaceSession(session)) {
    return { kind: "not_race", title: "Strategy is shown for races only.", text: "Practice, qualifying and time trials have no race strategy." };
  }
  if (!strategyGame(session.game)) {
    return {
      kind: "unsupported_game",
      title: "No race strategy for this game.",
      text: "Race strategy needs the timing of every car, which only F1 25 sends.",
    };
  }
  if (t && !t.available) {
    const why = (t.reason ?? "").toLowerCase();
    if (why.includes("not a race")) {
      return { kind: "not_race", title: "Strategy is shown for races only.", text: "Practice, qualifying and time trials have no race strategy." };
    }
    if (why.includes("no complete lap")) {
      return {
        kind: "no_laps",
        title: "No complete lap in this session.",
        text: "This part of the race ended before a lap was complete, so there is no strategy record for it.",
      };
    }
    if (why.includes("no strategy laps")) {
      return { kind: "no_laps", title: "No strategy laps yet.", text: "The first record is written when the first lap is complete." };
    }
    if (why.includes("before strategy")) {
      return {
        kind: "before_tracking",
        title: "This race was recorded before Pitwall tracked strategy.",
        text: "Races driven from now on show gaps, stints, pit stops and the engineer's strategy calls here.",
      };
    }
    if (why.includes("f1 25") || why.includes("game")) {
      return { kind: "unsupported_game", title: "No race strategy for this game.", text: sentence(t.reason ?? "") };
    }
    return { kind: "unavailable", title: "No strategy for this race.", text: t.reason ? `${sentence(t.reason)}.`.replace(/\.\.$/, ".") : "The server did not say why." };
  }
  if (t && !t.laps.length) {
    return { kind: "no_laps", title: "No strategy laps yet.", text: "The first record is written when the first lap is complete." };
  }
  return { kind: "ok", title: "", text: "" };
}

// -------------------------------------------------------------------------------------------------- KPIs

export interface StrategyKpi {
  id: "positions" | "stops" | "pit_loss" | "fuel";
  title: string;
  value: string;
  sub: string;
  term?: StrategyTerm;
}

function sortedLaps(t: Pick<StrategyTimeline, "laps">): StrategyLapRecord[] {
  return [...t.laps].sort((a, b) => a.lap - b.lap);
}

function compoundChange(before: string | null, after: string | null): string | null {
  const a = compoundWord(before);
  const b = compoundWord(after);
  if (!a && !b) return null;
  return `${a ?? UNKNOWN} → ${b ?? UNKNOWN}`;
}

export function timelineKpis(t: StrategyTimeline, opts: { simple?: boolean } = {}): StrategyKpi[] {
  const simple = !!opts.simple;
  const laps = sortedLaps(t);
  // Positions: the grid and the flag (the last record when the race did not finish here).
  // A race joined late (a resumed save) has no grid position: it starts from the first recorded lap instead, and
  // says so.
  const grid = finite(t.grid_position) && t.grid_position > 0 ? t.grid_position : null;
  const firstRec = laps.find((l) => finite(l.position) && l.position > 0) ?? null;
  const start = grid ?? firstRec?.position ?? null;
  const lastRec = [...laps].reverse().find((l) => finite(l.position) && l.position > 0) ?? null;
  // The server's finish position is the last record's: it is the flag only when that record is the last lap.
  const end = (finite(t.finish_position) && t.finish_position > 0 ? t.finish_position : null) ?? lastRec?.position ?? null;
  const lastLap = laps[laps.length - 1]?.lap ?? null;
  const finished = finite(t.total_laps) && lastLap != null && lastLap >= t.total_laps;
  const posValue = start == null && end == null ? UNKNOWN : `P${start ?? UNKNOWN} → P${end ?? UNKNOWN}`;
  let posSub: string;
  if (start != null && end != null) {
    const d = start - end;
    const single = grid == null && firstRec != null && !finished && lastLap === firstRec.lap; // one recorded lap
    const from = single ? ` on lap ${lastLap}` : grid == null && firstRec ? ` from lap ${firstRec.lap}` : "";
    const to = !single && !finished && lastLap != null ? ` to lap ${lastLap}` : "";
    if (d !== 0) posSub = `${d > 0 ? "Gained" : "Lost"} ${plural(Math.abs(d), "place")}${from}${to}`;
    else posSub = from || to ? `No change${from}${to}` : "Same place as the start";
  } else {
    posSub = start == null ? "Start position not recorded" : "Finish position not recorded";
  }

  // Stops: the player's own.
  const stops = [...t.stops].sort((a, b) => a.entry_lap - b.entry_lap);
  const stopsValue = String(stops.length);
  const stopsSub = stops.length
    ? stops
        .map((s) => {
          const change = compoundChange(s.compound_before, s.compound_after);
          return `L${s.entry_lap}${change ? ` · ${change}` : ""}`;
        })
        .join("; ")
    : simple
      ? "You did not stop"
      : "No pit stop";

  // Pit loss: this race's measured stops (player and field).
  const pl = t.pit_loss;
  const plValue = pl && finite(pl.median_s) ? `${one(pl.median_s)} s` : UNKNOWN;
  const plSub =
    pl && finite(pl.median_s)
      ? `${pl.n} measured${pl.n > 1 && finite(pl.range.low) && finite(pl.range.high) ? ` · ${one(pl.range.low)}-${one(pl.range.high)} s` : ""}`
      : "No pit stop measured in this race";

  // Fuel at the flag: the newest lap with this race's own margin; the game's figure otherwise.
  const fuelLap = [...laps].reverse().find((l) => finite(l.fuel_margin_laps));
  const gameLap = [...laps].reverse().find((l) => finite(l.game_fuel_margin_laps));
  let fuelValue = UNKNOWN;
  let fuelSub = "Needs two green laps";
  if (fuelLap) {
    fuelValue = `${signedOne(fuelLap.fuel_margin_laps)} laps`;
    const final = finite(t.total_laps) && fuelLap.lap >= t.total_laps;
    fuelSub = final ? "Left at the flag" : `Estimate at lap ${fuelLap.lap}`;
  } else if (gameLap) {
    fuelValue = `${signedOne(gameLap.game_fuel_margin_laps)} laps`;
    fuelSub = `The game's figure at lap ${gameLap.lap}`;
  }

  return [
    { id: "positions", title: simple ? "Start → finish" : "Positions", value: posValue, sub: posSub },
    { id: "stops", title: "Stops", value: stopsValue, sub: stopsSub },
    { id: "pit_loss", title: "Pit loss", value: plValue, sub: plSub, term: "pit_loss" },
    { id: "fuel", title: "Fuel at the flag", value: fuelValue, sub: fuelSub, term: "lift_and_coast" },
  ];
}

// ---------------------------------------------------------------------------------------------- the chart

export interface TimelineRow {
  lap: number;
  /** Position (reversed axis: P1 at the top). */
  position?: number;
  /** Gap to the car ahead / behind at the line, seconds. */
  ahead?: number;
  behind?: number;
  [key: string]: number | string | undefined;
}

export interface TimelineMark {
  lap: number;
  /** "M → H" */
  label: string;
  words: string;
}

export interface TimelineBand {
  start: number;
  end: number;
  short: string;
  words: string;
}

export interface TimelineSegment {
  key: string;
  /** Percent of the lap axis. */
  fromPct: number;
  widthPct: number;
  label: string;
  /** The label for a narrow segment on a phone ("H · 4", "Light rain"). */
  short: string;
  /** Long text for screen readers and the title attribute. */
  words: string;
  colour?: string;
}

export interface TimelineChartModel {
  empty: boolean;
  rows: TimelineRow[];
  /** The lap axis: half a lap of room either side, so every lap is a cell the bars line up with. */
  xDomain: [number, number];
  xTicks: number[];
  positionDomain: [number, number];
  positionTicks: number[];
  gapDomain: [number, number];
  gapTicks: number[];
  hasGaps: boolean;
  stops: TimelineMark[];
  bands: TimelineBand[];
  stints: TimelineSegment[];
  weather: TimelineSegment[];
  /** The weather changes in one line, for phones (the segments are too narrow for words there). */
  weatherLine: string | null;
  /** One sentence for screen readers: the race in words. */
  summary: string;
}

function laneTicks(lo: number, hi: number): number[] {
  const span = hi - lo;
  const step = span <= 12 ? 1 : span <= 30 ? 5 : 10;
  const out: number[] = [];
  const first = Math.ceil(lo / step) * step;
  for (let l = first; l <= hi; l += step) out.push(l);
  if (!out.includes(lo)) out.unshift(lo);
  if (!out.includes(hi)) out.push(hi);
  return out;
}

function positionTicks(maxPos: number): number[] {
  if (maxPos <= 6) return Array.from({ length: maxPos }, (_, i) => i + 1);
  const out = [1];
  const step = maxPos <= 12 ? 2 : 5;
  for (let p = step; p < maxPos; p += step) out.push(p);
  out.push(maxPos);
  return [...new Set(out)];
}

/** 0 .. max in steps a reader can count: 1 s up to 5 s, 2 s up to 10 s, then 5 s, then 10 s. */
function gapTicks(max: number): number[] {
  const step = max <= 5 ? 1 : max <= 10 ? 2 : max <= 30 ? 5 : 10;
  const top = Math.ceil(max / step) * step;
  const out: number[] = [];
  for (let v = 0; v <= top; v += step) out.push(v);
  return out;
}

function pctOf(lap: number, x0: number, x1: number): number {
  return ((lap - x0) / (x1 - x0)) * 100;
}

export function timelineChart(t: StrategyTimeline): TimelineChartModel {
  const laps = sortedLaps(t);
  if (!laps.length) {
    return {
      empty: true,
      rows: [],
      xDomain: [0, 1],
      xTicks: [],
      positionDomain: [1, 1],
      positionTicks: [1],
      gapDomain: [0, 3],
      gapTicks: [0, 1, 2, 3],
      hasGaps: false,
      stops: [],
      bands: [],
      stints: [],
      weather: [],
      weatherLine: null,
      summary: "No laps recorded.",
    };
  }
  const first = laps[0]!.lap;
  const last = laps[laps.length - 1]!.lap;
  const x0 = first - 0.5;
  const x1 = last + 0.5;
  const rows: TimelineRow[] = laps.map((l) => {
    const r: TimelineRow = { lap: l.lap };
    if (finite(l.position) && l.position > 0) r.position = l.position;
    if (finite(l.gap_ahead_ms) && l.gap_ahead_ms >= 0) r.ahead = Math.round(l.gap_ahead_ms / 100) / 10;
    if (finite(l.gap_behind_ms) && l.gap_behind_ms >= 0) r.behind = Math.round(l.gap_behind_ms / 100) / 10;
    return r;
  });
  const cars = Math.max(
    1,
    ...laps.map((l) => (finite(l.cars) ? l.cars : 0)),
    ...rows.map((r) => r.position ?? 0),
  );
  const gaps = rows.flatMap((r) => [r.ahead, r.behind]).filter(finite);
  const ticks = gapTicks(gaps.length ? Math.max(3, Math.max(...gaps)) : 3);
  const gapMax = ticks[ticks.length - 1]!;

  const stops: TimelineMark[] = [...t.stops]
    .sort((a, b) => a.entry_lap - b.entry_lap)
    .map((s) => ({
      lap: s.entry_lap,
      label: `${compoundShort(s.compound_before)} → ${compoundShort(s.compound_after)}`,
      words: `Pit stop on lap ${s.entry_lap}${compoundChange(s.compound_before, s.compound_after) ? `, ${compoundChange(s.compound_before, s.compound_after)}` : ""}`,
    }));

  const bands: TimelineBand[] = t.safety_car_periods.map((p) => {
    const end = finite(p.end_lap) ? p.end_lap : last;
    return {
      start: p.start_lap,
      end,
      short: safetyCarShort(p.status),
      words: `${safetyCarWord(p.status)} ${p.start_lap === end ? `on lap ${p.start_lap}` : `on laps ${p.start_lap}-${end}`}`,
    };
  });

  const stints: TimelineSegment[] = [...t.stints]
    .sort((a, b) => a.start_lap - b.start_lap)
    .map((s, i) => {
      const from = Math.max(s.start_lap, first) - 0.5;
      const to = Math.min(s.end_lap, last) + 0.5;
      const word = compoundWord(s.compound) ?? "Unknown tyre";
      return {
        key: `stint${i}`,
        fromPct: pctOf(from, x0, x1),
        widthPct: Math.max(0, pctOf(to, x0, x1) - pctOf(from, x0, x1)),
        label: `${word} · ${plural(s.laps, "lap")}`,
        short: `${compoundShort(s.compound)} · ${s.laps}`,
        words: `${word}, laps ${s.start_lap} to ${s.end_lap}`,
        colour: compoundColour(s.compound),
      };
    });

  // Weather: the changes only; each one holds until the next.
  const changes = [...t.weather].sort((a, b) => a.lap - b.lap);
  const weather: TimelineSegment[] = changes.map((c, i) => {
    const from = Math.max(c.lap, first) - 0.5;
    const nextLap = changes[i + 1]?.lap;
    const to = (finite(nextLap) ? Math.min(nextLap - 1, last) : last) + 0.5;
    const word = weatherWord(c.weather) ?? UNKNOWN;
    const rain = finite(c.rain_pct) ? ` · rain ${Math.round(c.rain_pct)}%` : "";
    return {
      key: `w${i}`,
      fromPct: pctOf(from, x0, x1),
      widthPct: Math.max(0, pctOf(to, x0, x1) - pctOf(from, x0, x1)),
      label: `${word}${rain}`,
      short: word,
      words: `${word} from lap ${c.lap}${finite(c.rain_pct) ? `, the game's rain figure ${Math.round(c.rain_pct)} percent` : ""}`,
    };
  });

  const firstPos = rows.find((r) => r.position != null)?.position;
  const lastPos = [...rows].reverse().find((r) => r.position != null)?.position;
  const summary = [
    `Laps ${first} to ${last}.`,
    firstPos != null && lastPos != null ? `Position P${firstPos} on lap ${first}, P${lastPos} on lap ${last}.` : null,
    stops.length ? `${plural(stops.length, "pit stop")}: ${stops.map((s) => `lap ${s.lap}`).join(", ")}.` : "No pit stop.",
    bands.length ? `${bands.map((b) => b.words).join("; ")}.` : null,
  ]
    .filter(Boolean)
    .join(" ");

  return {
    empty: false,
    rows,
    xDomain: [x0, x1],
    xTicks: laneTicks(first, last),
    positionDomain: [1, cars],
    positionTicks: positionTicks(cars),
    gapDomain: [0, gapMax],
    gapTicks: ticks,
    hasGaps: gaps.length > 0,
    stops,
    bands,
    stints,
    weather,
    weatherLine: changes.length
      ? `Weather: ${changes
          .map((c, i) => {
            const w = weatherWord(c.weather) ?? UNKNOWN;
            const rain = finite(c.rain_pct) ? ` (rain ${Math.round(c.rain_pct)}%)` : "";
            return `${i ? w.toLowerCase() : w} from lap ${c.lap}${rain}`;
          })
          .join("; ")}.`
      : null,
    summary,
  };
}

// ----------------------------------------------------------------------------------------------- tables

export interface StintRowView {
  id: string;
  compound: string;
  colour: string;
  /** "L1-24" */
  laps: string;
  count: number;
  /** "38%" */
  wearEnd: string;
  /** "1.5%/lap" */
  rate: string;
  median: string;
}

export function stintRows(stints: readonly StintRow[]): StintRowView[] {
  return [...stints]
    .sort((a, b) => a.start_lap - b.start_lap)
    .map((s, i) => ({
      id: `stint${i}`,
      compound: compoundWord(s.compound) ?? UNKNOWN,
      colour: compoundColour(s.compound),
      laps: s.start_lap === s.end_lap ? `L${s.start_lap}` : `L${s.start_lap}-${s.end_lap}`,
      count: s.laps,
      wearEnd: finite(s.wear_end_pct) ? `${Math.round(s.wear_end_pct)}%` : UNKNOWN,
      rate: finite(s.wear_rate_pct_per_lap) ? `${one(s.wear_rate_pct_per_lap)}%/lap` : UNKNOWN,
      median: lapTime(s.median_lap_ms),
    }));
}

/** Exclusion reasons (strategy/pitloss.py) in words; anything new is shown as sent, sentence case. */
export function excludedWords(reason: string | null | undefined): string | null {
  if (!reason) return null;
  const r = reason.toLowerCase();
  if (r.includes("long stop") || r.includes("repair")) return "Long stop (repair?)";
  if (r.includes("penalt")) return "Served a penalty";
  if (r.includes("pre-stop") || r.includes("pre_stop") || r.includes("no green lap") || r.includes("pre_pace")) {
    return "No green lap seen before the stop";
  }
  if (r.includes("range") || r.includes("8-45") || r.includes("implausible")) return "Pit loss outside 8-45 s";
  if (r.includes("not all observed") || r.includes("missing") || r.includes("laps_missing")) return "Not every lap of the stop was seen";
  if (r.includes("part of the stop")) return "Safety car for only part of the stop";
  if (r.includes("rewind") || r.includes("flashback")) return "Flashback during the stop";
  if (r.includes("out-lap") || r.includes("out lap") || r.includes("not completed")) return "Out lap not completed";
  return sentence(reason.replace(/_/g, " "));
}

export interface StopRowView {
  id: string;
  /** "You" or "Car 14" (car numbers only: no names). */
  car: string;
  entry: string;
  exit: string;
  lane: string;
  stationary: string;
  loss: string;
  compounds: string;
  /** Exclusion or neutralisation in words; null when the stop counts as a green stop. */
  note: string | null;
  /** Counted in the session's pit-loss figure. */
  used: boolean;
}

function secs(v: number | null | undefined): string {
  return finite(v) ? `${one(v)} s` : UNKNOWN;
}

export function stopRows(stops: readonly PitStopRow[]): StopRowView[] {
  return [...stops]
    .sort((a, b) => a.entry_lap - b.entry_lap || a.car_index - b.car_index)
    .map((s) => {
      const excl = excludedWords(s.excluded);
      const neut = s.neutralised === "full" ? "Under the safety car" : s.neutralised === "virtual" ? "Under the virtual safety car" : null;
      return {
        id: `${s.car_index}:${s.entry_lap}`,
        car: s.is_player ? "You" : `Car ${s.car_index}`,
        entry: `L${s.entry_lap}`,
        exit: finite(s.exit_lap) ? `L${s.exit_lap}` : UNKNOWN,
        lane: secs(s.lane_time_s),
        stationary: secs(s.stationary_s),
        loss: excl ? UNKNOWN : secs(s.pit_loss_s),
        compounds: compoundChange(s.compound_before, s.compound_after) ?? UNKNOWN,
        note: excl ? `Not counted: ${excl.charAt(0).toLowerCase()}${excl.slice(1)}` : neut,
        used: !excl && finite(s.pit_loss_s),
      };
    });
}

// ------------------------------------------------------------------------------------------------- calls

export interface CallRowView {
  id: string;
  lap: string;
  chip: { label: string; tone: "warning" | "ref" | "default" };
  text: string;
}

export function callRows(calls: readonly (CallView & { lap: number | null })[]): CallRowView[] {
  return [...calls]
    .sort((a, b) => (a.lap ?? 0) - (b.lap ?? 0) || (finite(a.t_unix) ? a.t_unix : 0) - (finite(b.t_unix) ? b.t_unix : 0))
    .map((c, i) => ({
      id: c.id || `call${i}`,
      lap: finite(c.lap) ? `L${c.lap}` : UNKNOWN,
      chip: callChip(c.level),
      text: c.text,
    }));
}

// ------------------------------------------------------------------------------------------------- note

/** The footer: what each tier means, and the evidence behind this page (P8). */
export function tierNote(opts: { synthetic: boolean }): string {
  const base =
    "Measured values come from this race's own timing. (game) is the game's own figure; (estimate) is a Pitwall " +
    "rule of thumb. Safety car, rain and pit-stop advice has not been checked in a real race yet.";
  return opts.synthetic ? `Synthetic session: generated data, not from a game. ${base}` : base;
}
