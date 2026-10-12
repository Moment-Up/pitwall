// Timing colours (design spec 4.6) and the Drive sector / lap-time panels (4.3 #6, #7). Pure.
//
// One rule set (lib/bests.ts, shared with Review and Progress): same game + track + car + layout, clean laps only,
// never synthetic or replay sessions. Purple REC = household record, green PB = your best ever, green SB = your best
// this session (a session's first clean time is its best so far), yellow = completed and slower than your session
// best, grey INV = not clean. The strongest badge that applies wins (bests.ts `bestBadge`); a time that only ties a
// best set earlier does not take it (D2's setter lap ids decide, as `repo.lap_bests` breaks ties by the lower lap id).
// Before D2 purple and PB never appear: only SB and yellow, derived from laps[]. D2 only adds.
// "As set" (Drive): a time keeps the colour it had when it was completed. "Current standing" (tables): only the
// times that are still the best are coloured.
//
// Synthetic and replay sessions are outside the timing scope, so their times carry no timing colour at all (no
// REC / PB / SB / yellow; the same rule as Review > Laps, lib/review/kpis.ts timingEligible). Grey INV stays: it is
// a fact about the lap, not a timing colour.
// Tier = which tags can appear: 2 only while D2 actually sends a driver or household best for this scope (so the
// legend never names REC or PB where they cannot appear), else 1.

import { bestBadge } from "../bests";
import { gameLength, onLap, unit } from "./geometry";
import type { DriveState } from "./state";
import type { Bests, SnapshotNext } from "./types";
import { UNKNOWN, finite, lapClockTenths, lapTime, sectorClockTenths, sectorTime, signedFixed, signedMs } from "./text";

export type TimingStatus = "rec" | "pb" | "sb" | "slower" | "neutral" | "invalid";
export type TimingTag = "REC" | "PB" | "SB" | "INV";
export type Tier = 1 | 2;

export interface BestsView {
  /** 2 when a driver or household best is present (REC / PB can appear), else 1. */
  tier: Tier;
  /** Timing colours apply: false in synthetic and replay sessions (only INV stays). */
  coloured: boolean;
  session: Bests;
  driver: Bests | null;
  household: Bests | null;
}

const EMPTY: Bests = { lap_ms: null, sectors_ms: [null, null, null] };

function positive(v: unknown): v is number {
  return finite(v) && v > 0;
}

function minOf(values: (number | null | undefined)[]): number | null {
  let m: number | null = null;
  for (const v of values) if (positive(v) && (m === null || v < m)) m = v;
  return m;
}

/** Session bests over a list of laps (clean laps only). */
export function bestsOfLaps(laps: SnapshotNext["laps"]): Bests {
  const clean = laps.filter((l) => l.clean);
  return {
    lap_ms: minOf(clean.map((l) => l.lap_time_ms)),
    sectors_ms: [0, 1, 2].map((i) => minOf(clean.map((l) => l.sector_times_ms[i]))) as Bests["sectors_ms"],
  };
}

/** A replayed capture (connection.source "replay:..."): nobody is driving it now. */
export function isReplay(s: SnapshotNext): boolean {
  return (s.connection.source ?? "").startsWith("replay:");
}

/** Synthetic data, by the connection or the skeleton (the same test as the SYNTHETIC chip). */
export function isSynthetic(s: SnapshotNext): boolean {
  return !!s.connection.synthetic || !!s.skeleton?.synthetic;
}

/** The session is in the timing scope (4.6): never synthetic, never a replay. */
export function inTimingScope(s: SnapshotNext): boolean {
  return !isSynthetic(s) && !isReplay(s);
}

function hasAny(b: Bests | null | undefined): b is Bests {
  return !!b && (positive(b.lap_ms) || b.sectors_ms.some(positive));
}

/** The bests in force: D2's block when the server sends it, else the session bests from laps[]. Driver and
 * household bests are used only in the timing scope and when D2's scope keeps records; tier 2 only when one of
 * them is actually there. */
export function bestsOf(s: SnapshotNext): BestsView {
  const coloured = inTimingScope(s);
  if (s.bests) {
    const records = coloured && s.bests.scope?.records !== false;
    const driver = records && hasAny(s.bests.driver) ? s.bests.driver : null;
    const household = records && hasAny(s.bests.household) ? s.bests.household : null;
    return { tier: driver || household ? 2 : 1, coloured, session: s.bests.session ?? EMPTY, driver, household };
  }
  return { tier: 1, coloured, session: bestsOfLaps(s.laps), driver: null, household: null };
}

export interface Before {
  session: number | null;
  driver: number | null;
  household: number | null;
}

/** Status of a time when it was set, against the bests BEFORE it (strictly faster beats). The session's first clean
 * time is its best so far: SB. */
export function statusAsSet(t: number | null, before: Before, clean: boolean, tier: Tier): TimingStatus {
  if (!clean) return "invalid";
  if (!positive(t)) return "neutral";
  if (tier === 2 && before.household != null && t < before.household) return "rec";
  if (tier === 2 && before.driver != null && t < before.driver) return "pb";
  if (before.session != null && t >= before.session) return "slower";
  return "sb";
}

/** The bests a table is coloured against, with the laps that hold them when D2 says so (lap_id / sector_lap_ids). */
export interface StandingBests {
  driver: number | null;
  household: number | null;
  driverLapId?: number | null;
  householdLapId?: number | null;
}

/** The time `t` of lap `id` holds the best `ms` (set by lap `holderId`): by the setter's id when both are known (a
 * tie with an earlier lap does not take the best), else by time. */
function holdsBest(t: number, id: number | null | undefined, ms: number | null, holderId: number | null | undefined): boolean {
  if (ms == null) return false;
  if (id != null && holderId != null) return id === holderId;
  return t <= ms;
}

/** Status of times by current standing (tables): the bests passed in already include these times; `ids` (the laps'
 * ids, same order) let D2's setter ids settle ties. `coloured` false (synthetic or replay session,
 * BestsView.coloured): no timing colour, only INV. The session's best clean time is SB even when it is the only one. */
export function standing(
  times: (number | null)[],
  clean: boolean[],
  best: StandingBests,
  tier: Tier,
  coloured = true,
  ids?: readonly (number | null)[],
): TimingStatus[] {
  const cleanTimes = times.filter((t, i) => clean[i] && positive(t)) as number[];
  const sessionBest = cleanTimes.length ? Math.min(...cleanTimes) : null;
  return times.map((t, i) => {
    if (!clean[i]) return "invalid";
    if (!positive(t) || !coloured) return "neutral";
    const id = ids?.[i] ?? null;
    const badge = bestBadge({
      coloured: true,
      household: tier === 2 && holdsBest(t, id, best.household, best.householdLapId),
      driver: tier === 2 && holdsBest(t, id, best.driver, best.driverLapId),
      session: t === sessionBest,
    });
    return badge === "neutral" ? "slower" : badge;
  });
}

/** Which value of a Bests: the lap or a sector (0..2). */
type Part = "lap" | 0 | 1 | 2;

function valueOf(b: Bests, part: Part): number | null {
  return part === "lap" ? b.lap_ms : (b.sectors_ms[part] ?? null);
}

function setterOf(b: Bests, part: Part): number | null | undefined {
  return part === "lap" ? b.lap_id : b.sector_lap_ids?.[part];
}

/**
 * Did the lap `lapId` set this D2 best (lap or sector)? Exact when D2 sends the setter's lap id. Without it, only
 * the newest lap can be judged, by time: D2 recomputes after each lap, so a best equal to the time (and faster than
 * every older lap of the session) was set by it; a best not yet recomputed is simply beaten.
 */
function setBy(b: Bests | null, part: Part, lapId: number, t: number, newest: boolean, older: number | null): boolean {
  if (!b) return false;
  const id = setterOf(b, part);
  if (id != null) return id === lapId;
  const v = valueOf(b, part);
  return newest && v != null && t <= v && (older == null || t < older);
}

/** Status of a completed lap (or one of its sectors) as set: REC / PB from D2, then SB or slower against the
 * session's older clean laps. */
function completedStatus(
  t: number | null,
  lap: { lap_id: number; clean: boolean },
  part: Part,
  b: BestsView,
  newest: boolean,
  older: number | null,
): TimingStatus {
  if (!lap.clean) return "invalid";
  if (!positive(t) || !b.coloured) return "neutral";
  const badge = bestBadge({
    coloured: true,
    household: b.tier === 2 && setBy(b.household, part, lap.lap_id, t, newest, older),
    driver: b.tier === 2 && setBy(b.driver, part, lap.lap_id, t, newest, older),
    session: older == null || t < older, // the session's first clean time is its best so far
  });
  return badge === "neutral" ? "slower" : badge;
}

export function tagOf(status: TimingStatus | "running" | "future"): TimingTag | null {
  switch (status) {
    case "rec":
      return "REC";
    case "pb":
      return "PB";
    case "sb":
      return "SB";
    case "invalid":
      return "INV";
    default:
      return null;
  }
}

/** Legend for every timing surface. */
export function timingLegend(tier: Tier): string {
  return tier === 2 ? "REC family record · PB your best ever · SB your best today" : "SB your best today";
}

/** The legend for a snapshot: the tags that can appear, or why there are none (synthetic, replay). */
export function legendOf(s: SnapshotNext | null, bv: BestsView | null): string {
  if (!s || !bv) return timingLegend(1);
  if (bv.coloured) return timingLegend(bv.tier);
  return isSynthetic(s) ? "Synthetic data: times are not coloured" : "A replay: times are not coloured";
}

/** m:ss.t while running, m:ss.SSS when completed, "-" when unknown. */
export function lapClock(ms: number | null, running: boolean): string {
  return running ? lapClockTenths(ms) : lapTime(ms);
}

const FLAG_WORDS: Record<string, string> = {
  flashback: "flashback",
  pit_in: "pit in",
  pit_out: "out lap",
  incomplete: "incomplete",
  invalid: "invalid",
  paused: "paused",
  stale_data: "data gap",
  standing_start: "standing start",
  distance_jump: "reset to track",
};

/** Why a lap is not clean, as words ("out lap", "flashback"); empty when clean. */
export function notCleanList(lap: { clean: boolean; valid: boolean | null; flags: string[] }): string[] {
  if (lap.clean) return [];
  const words = lap.flags.map((f) => FLAG_WORDS[f] ?? f.replace(/_/g, " "));
  if (lap.valid === false && !lap.flags.includes("invalid")) words.unshift("invalid");
  return words.length ? [...new Set(words)] : ["not clean"];
}

/** Why the session's laps did not count, in words ("out lap, pit in"), from the server's whole-session totals. */
export function notCleanTotalsList(t: {
  not_clean_flags?: string[];
  not_clean_invalid?: boolean;
  not_clean_other?: boolean;
}): string[] {
  const words = (t.not_clean_flags ?? []).map((f) => FLAG_WORDS[f] ?? f.replace(/_/g, " "));
  if (t.not_clean_invalid) words.unshift("invalid");
  if (t.not_clean_other) words.push("not clean");
  return [...new Set(words)];
}

/** Why a lap is not clean, in words ("out lap, flashback"); null when clean. */
export function notCleanWords(lap: { clean: boolean; valid: boolean | null; flags: string[] }): string | null {
  const w = notCleanList(lap);
  return w.length ? w.join(", ") : null;
}

// ------------------------------------------------------------------ sector cells

export interface SectorCell {
  label: "S1" | "S2" | "S3";
  text: string;
  status: TimingStatus | "running" | "future";
  tag: TimingTag | null;
  /** Small line under the time ("−0.023 on today's best"). */
  sub: string | null;
  /** Running sector progress 0..1, else null. */
  progress: number | null;
}

export interface SectorCellsView {
  /** "Last lap · L6" when the cells show the last completed lap (before D1), else null. */
  caption: string | null;
  source: "current" | "last_lap" | "none";
  /** Last-lap values are dimmed so they never look current. */
  dim: boolean;
  cells: [SectorCell, SectorCell, SectorCell];
}

const LABELS = ["S1", "S2", "S3"] as const;

function blank(sub: (i: number) => string | null = () => null): SectorCellsView["cells"] {
  return LABELS.map((label, i) => ({
    label,
    text: UNKNOWN,
    status: "neutral" as const,
    tag: null,
    sub: sub(i),
    progress: null,
  })) as SectorCellsView["cells"];
}

function sectorSub(status: TimingStatus, t: number | null, sessionBefore: number | null): string | null {
  switch (status) {
    case "rec":
      return "family record";
    case "pb":
      return "your best ever";
    case "sb":
      return sessionBefore != null && positive(t) ? `${signedMs(t - sessionBefore)} on today's best` : "best today";
    case "slower":
      return sessionBefore != null && positive(t) ? `${signedMs(t - sessionBefore)} vs today's best` : null;
    case "invalid":
      return "not clean";
    default:
      return null;
  }
}

function beforeSector(bv: BestsView, i: number): Before {
  return {
    session: bv.session.sectors_ms[i] ?? null,
    driver: bv.driver?.sectors_ms[i] ?? null,
    household: bv.household?.sectors_ms[i] ?? null,
  };
}

/** Index 0..2 of the sector the car is in: the game's own when sent, else from the skeleton and lap distance. */
function currentSector(s: SnapshotNext): number | null {
  const k = s.frame?.sector;
  if (finite(k) && k >= 0 && k <= 2) return k;
  const d = onLap(s.frame?.lap_distance_m, gameLength(s));
  const sec = d == null ? null : (s.skeleton?.sectors ?? []).find((x) => d >= x.start_m && d < x.end_m);
  return sec ? sec.index : null;
}

function lastLapCells(s: SnapshotNext, bv: BestsView): SectorCellsView {
  const last = s.laps[0];
  if (!last) return { caption: null, source: "none", dim: false, cells: blank() };
  const older = bestsOfLaps(s.laps.slice(1));
  const cells = LABELS.map((label, i) => {
    const t = last.sector_times_ms[i] ?? null;
    const prev = older.sectors_ms[i] ?? null;
    const status = completedStatus(t, last, i as Part, bv, true, prev);
    return {
      label,
      text: sectorTime(t),
      status: positive(t) ? status : "neutral",
      tag: positive(t) ? tagOf(status) : null,
      sub: positive(t) ? sectorSub(status, t, prev) : null,
      progress: null,
    };
  }) as SectorCellsView["cells"];
  return { caption: `Last lap · L${last.lap_number}`, source: "last_lap", dim: true, cells };
}

/**
 * The three sector cells. With D1 (frame.current_lap_sector_ms) they show the lap in progress: completed sectors
 * coloured as set, the running sector's elapsed time and progress, later sectors "-". Before D1 they show the
 * last completed lap, dimmed and captioned, never as current values. Stale keeps the completed facts and blanks
 * the running sector; offline and no telemetry show "-".
 */
export function sectorCells(s: SnapshotNext | null, state: DriveState = "on_track", bv?: BestsView): SectorCellsView {
  if (!s || state === "offline" || state === "no_data") return { caption: null, source: "none", dim: false, cells: blank() };
  const b = bv ?? bestsOf(s);
  if (state === "garage" && s.laps.length === 0) {
    const own = b.driver;
    return {
      caption: null,
      source: "none",
      dim: false,
      cells: blank((i) => {
        const t = own?.sectors_ms[i];
        return positive(t) ? `your best here ${sectorTime(t)}` : null;
      }),
    };
  }
  const cur = s.frame?.current_lap_sector_ms;
  const current = Array.isArray(cur) && (state === "on_track" || state === "red_flag" || state === "pit_lane" || state === "stale");
  if (!current || !s.frame) return lastLapCells(s, b);
  const f = s.frame;
  const k = currentSector(s);
  const invalid = f.lap_invalid === true;
  const cells = LABELS.map((label, i): SectorCell => {
    if (k == null || i > k) return { label, text: UNKNOWN, status: "future", tag: null, sub: null, progress: null };
    if (i < k) {
      const t = i < 2 ? (cur[i] ?? null) : null;
      const before = beforeSector(b, i);
      const status = invalid || !b.coloured ? "neutral" : statusAsSet(t, before, true, b.tier);
      return {
        label,
        text: sectorTime(t),
        status: positive(t) ? status : "neutral",
        tag: positive(t) ? tagOf(status) : null,
        sub: positive(t) && !invalid ? sectorSub(status, t, before.session) : null,
        progress: null,
      };
    }
    // running sector
    if (state === "stale") return { label, text: UNKNOWN, status: "future", tag: null, sub: "no signal", progress: null };
    const done = cur.slice(0, i);
    const clock = f.current_lap_time_ms;
    const elapsed = done.every(positive) && finite(clock) ? clock - done.reduce((a, x) => a + (x ?? 0), 0) : null;
    const sec = s.skeleton?.sectors?.[i];
    const d = onLap(f.lap_distance_m, gameLength(s));
    const progress = sec && d != null && sec.length_m > 0 ? unit((d - sec.start_m) / sec.length_m) : null;
    return { label, text: sectorClockTenths(elapsed), status: "running", tag: null, sub: null, progress };
  }) as SectorCellsView["cells"];
  return { caption: null, source: "current", dim: false, cells };
}

// ------------------------------------------------------------------ lap times panel

export interface LapTimesView {
  lap: {
    text: string;
    running: boolean;
    /** Status of the just-completed lap while it is shown (6 s after the line), else null. */
    status: TimingStatus | null;
    tag: TimingTag | null;
    invalid: boolean;
    muted: boolean;
  };
  last: {
    text: string;
    status: TimingStatus;
    tag: TimingTag | null;
    /** Difference to the reference lap ("+0.53"), or null. */
    deltaText: string | null;
    deltaTone: "ahead" | "behind" | "level" | null;
    /** Not clean: why, in words. */
    reason: string | null;
    lapNumber: number | null;
  };
  best: {
    text: string;
    status: TimingStatus;
    tag: TimingTag | null;
    sub: string | null;
    lapNumber: number | null;
  };
}

/** Completed lap shown in the Lap cell for this long after the line, then the clock resumes. */
export const COMPLETED_LAP_SHOW_MS = 6000;

/** Status of laps[i] as set (0 = the newest completed lap). */
export function lapStatus(s: SnapshotNext, i: number, bv?: BestsView): TimingStatus {
  const lap = s.laps[i];
  if (!lap) return "neutral";
  const older = bestsOfLaps(s.laps.slice(i + 1)).lap_ms;
  return completedStatus(lap.lap_time_ms, lap, "lap", bv ?? bestsOf(s), i === 0, older);
}

/** Status of laps[0] (the newest completed lap) as set. */
export function lastLapStatus(s: SnapshotNext, bv?: BestsView): TimingStatus {
  return lapStatus(s, 0, bv);
}

/** The session best clean lap by current standing: REC / PB when it holds the D2 record / personal best, else SB
 * (neutral outside the timing scope). Null without a clean lap. */
export function sessionBest(
  s: SnapshotNext,
  bv?: BestsView,
): { ms: number; status: TimingStatus; lapNumber: number | null; index: number } | null {
  const b = bv ?? bestsOf(s);
  const ms = b.session.lap_ms;
  if (!positive(ms)) return null;
  const index = s.laps.findIndex((l) => (b.session.lap_id != null ? l.lap_id === b.session.lap_id : l.clean && l.lap_time_ms === ms));
  const lap = index >= 0 ? s.laps[index] : undefined;
  const holds = (x: Bests | null) =>
    !!x && (x.lap_id != null && lap ? x.lap_id === lap.lap_id : x.lap_ms != null && ms <= x.lap_ms);
  const status: TimingStatus = bestBadge({
    coloured: b.coloured,
    household: b.tier === 2 && holds(b.household),
    driver: b.tier === 2 && holds(b.driver),
    session: true,
  });
  return { ms, status, lapNumber: lap?.lap_number ?? null, index };
}

export function lapTimesView(s: SnapshotNext | null, state: DriveState, bv?: BestsView): LapTimesView {
  const none: LapTimesView = {
    lap: { text: UNKNOWN, running: false, status: null, tag: null, invalid: false, muted: false },
    last: { text: UNKNOWN, status: "neutral", tag: null, deltaText: null, deltaTone: null, reason: null, lapNumber: null },
    best: { text: UNKNOWN, status: "neutral", tag: null, sub: null, lapNumber: null },
  };
  if (!s || state === "offline" || state === "no_data") return none;
  const b = bv ?? bestsOf(s);
  const f = s.frame;
  const last = s.laps[0] ?? null;
  const lastStatus = lastLapStatus(s, b);

  // Lap clock
  let lap = none.lap;
  const invalid = f?.lap_invalid === true;
  if (f && (state === "on_track" || state === "red_flag" || state === "pit_lane")) {
    const clock = f.current_lap_time_ms;
    const justDone =
      last != null &&
      finite(clock) &&
      clock < COMPLETED_LAP_SHOW_MS &&
      finite(f.lap_number) &&
      last.lap_number === f.lap_number - 1 &&
      positive(last.lap_time_ms);
    lap = justDone
      ? { text: lapTime(last.lap_time_ms), running: false, status: lastStatus, tag: tagOf(lastStatus), invalid, muted: false }
      : { text: lapClockTenths(clock), running: true, status: null, tag: null, invalid, muted: state === "pit_lane" };
  }

  // Last lap
  let lastView = none.last;
  if (last) {
    const ref = s.reference;
    const diff =
      ref && ref.lap_id !== last.lap_id && positive(ref.lap_time_ms) && positive(last.lap_time_ms)
        ? (last.lap_time_ms - ref.lap_time_ms) / 1000
        : null;
    lastView = {
      text: lapTime(last.lap_time_ms),
      status: lastStatus,
      tag: tagOf(lastStatus),
      deltaText: diff == null ? null : signedFixed(diff, 2),
      deltaTone: diff == null ? null : diff < -0.02 ? "ahead" : diff > 0.02 ? "behind" : "level",
      reason: notCleanWords(last),
      lapNumber: last.lap_number,
    };
  } else if (f && positive(f.last_lap_time_ms) && state !== "garage") {
    lastView = { ...none.last, text: lapTime(f.last_lap_time_ms) };
  }

  // Best (session best clean lap)
  let best = none.best;
  const sb = sessionBest(s, b);
  if (sb) {
    best = { text: lapTime(sb.ms), status: sb.status, tag: tagOf(sb.status), sub: null, lapNumber: sb.lapNumber };
  } else if (state === "garage" || s.laps.length === 0) {
    best = { ...none.best, sub: "first lap sets it" };
  }
  return { lap, last: lastView, best };
}
