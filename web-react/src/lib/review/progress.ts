// Review › Progress (spec 6.9) and what the Coaching plan (6.8) shares with it: the scope (driver, track, car), one
// point per session, the PB steps and milestones, the computed sentences (never an LLM), steadiness, corner trends,
// habit counts, the headline tiles and the family board. Pure; tested in node.
//
// Data tiers:
//  * D5 (`GET /api/drivers/{id}/progress`) when the server has it: clean-lap counts, median and spread per session,
//    corner trends against the driver's current reference, habit counts, and the PB history per game + track + car.
//  * Before D5 (a 404 from an older server): lap level from the driver's session rows (`best_clean_ms`, `lap_count`,
//    `clean_lap_count` once D5's list column exists). Steadiness, corner trends and habits are then unknown.
//
// Timing colours (4.6) on Progress: the one rule shared with Drive and Review (lib/bests.ts): each session's best lap
// carries REC when it is the family record, PB when it is the driver's best ever, in its own scope (game + track +
// car + layout, real driving only), found in the session list (`sessionBadges`); the page passes those badges in.
// Only REC and PB are drawn (every session's best is its own SB; a chart of green dots would say nothing). D5's PB
// history (no layout filter) drives the milestones ("New PB …"), which are events, not badges. The family board is
// the server's board of one exact key (lib/review/records.ts picks it); it stays neutral and marks its leader with
// the word "Fastest".

import type { TimingStatus } from "../../components/ui/types";
import type { BestBadge } from "../bests";
import type { Driver } from "../drivers";
import type { BoardLabels, BoardVsAll, LeaderboardBoard } from "../endpoints/leaderboard";
import type {
  DriverProgress,
  PbHistoryEntry,
  ProgressCornerText,
  ProgressQuery,
  ProgressSession,
  SessionListRow,
} from "../endpoints/review";
import { lapTime } from "../format";
import { isReplaySource } from "./kpis";
import { dayInSentence, dayTitle, finite, plural, readableCar, sessionLabels, spreadSeconds, trackLabel } from "./words";
import { carText } from "../carclass";

/** `?car=any`: every car at the track. */
export const ANY_CAR = "any";

/** Sessions a progress request covers (newest first on the server, returned oldest first). Corner trends are only
 * computed for the newest 30 by the server. */
export const PROGRESS_LIMIT = 50;

/** The coach's smallest time loss worth a point (drivers' `coaching.min_impact_s` default). */
export const DEFAULT_THRESHOLD_S = 0.02;

// --------------------------------------------------------------------------------------------------------- scope

export interface CarChoice {
  /** Car id ("f1:team:7"). */
  id: string;
  /** The car's name ("Haas"), else "Unnamed car" (numbered when a track has more than one): never a raw id ("team_214",
   * "gt7:car:919"; words.ts readableCar, integration plan 5.8). */
  label: string;
  /** The game named the car (else `label` is "Unnamed car"). */
  named: boolean;
  sessions: number;
  newest: number;
}

export interface TrackChoice {
  game: string;
  trackId: string;
  label: string;
  /** Synthetic data (synthetic streams and replays use their own track ids). */
  synthetic: boolean;
  sessions: number;
  newest: number;
  /** The car of the newest session here (null: unknown). */
  newestCarId: string | null;
  /** Cars with a known id, newest first. */
  cars: CarChoice[];
  /** Sessions here whose car is unknown (only "Any car" covers them). */
  unknownCar: number;
}

type ScopeRow = Pick<
  SessionListRow,
  "game" | "track_id" | "track_name" | "car_name" | "car_label" | "started_unix" | "source" | "synthetic" | "lap_count"
> & { car_id?: string | null };

function drivenRow(r: ScopeRow, includeSynthetic: boolean): boolean {
  return !!r.track_id && r.lap_count > 0 && !isReplaySource(r.source) && (includeSynthetic || !r.synthetic);
}

/**
 * The tracks (and cars at each) a driver has driven, from their session rows: never replays (nobody's driving),
 * synthetic only when asked, sessions without laps left out. Newest track first.
 */
export function scopeChoices(rows: readonly ScopeRow[], opts: { includeSynthetic: boolean }): TrackChoice[] {
  const by = new Map<string, TrackChoice & { _newestRow: number }>();
  for (const r of rows) {
    if (!drivenRow(r, opts.includeSynthetic)) continue;
    const key = `${r.game}|${r.track_id}`;
    let t = by.get(key);
    if (!t) {
      t = {
        game: r.game,
        trackId: r.track_id as string,
        label: trackLabel(r),
        synthetic: false,
        sessions: 0,
        newest: -Infinity,
        newestCarId: null,
        cars: [],
        unknownCar: 0,
        _newestRow: -Infinity,
      };
      by.set(key, t);
    }
    t.sessions += 1;
    if (r.synthetic) t.synthetic = true;
    if (r.started_unix > t._newestRow) {
      t._newestRow = r.started_unix;
      t.newest = r.started_unix;
      t.newestCarId = r.car_id ?? null;
      if (r.track_name?.trim()) t.label = trackLabel(r);
    }
    const carId = r.car_id ?? null;
    if (carId == null) {
      t.unknownCar += 1;
      continue;
    }
    const c = t.cars.find((x) => x.id === carId);
    const name = carText(r); // the server's car_label ("F2 · Art GP '24") when it sends one
    if (c) {
      c.sessions += 1;
      if (r.started_unix > c.newest) c.newest = r.started_unix;
      if (name && !c.named) {
        c.label = name;
        c.named = true;
      }
    } else {
      t.cars.push({ id: carId, label: name ?? "", named: !!name, sessions: 1, newest: r.started_unix });
    }
  }
  return [...by.values()]
    .map(({ _newestRow: _, ...t }) => ({ ...t, cars: unnamedLabels([...t.cars].sort((a, b) => b.newest - a.newest)) }))
    .sort((a, b) => b.newest - a.newest || a.label.localeCompare(b.label));
}

/** Cars the game did not name read "Unnamed car", numbered newest first when a track has more than one. */
function unnamedLabels(cars: CarChoice[]): CarChoice[] {
  const unnamed = cars.filter((c) => !c.named).length;
  let n = 0;
  return cars.map((c) => (c.named ? c : { ...c, label: unnamed > 1 ? `Unnamed car ${++n}` : "Unnamed car" }));
}

export interface Scope {
  track: TrackChoice;
  /** null = any car. */
  carId: string | null;
  /** The car's name for headers (its id when the game did not name it); null for any car. */
  carLabel: string | null;
  /** The game named the car (sentences say "in the Haas" only then). */
  carNamed?: boolean;
}

/**
 * The scope a page shows: the track from `?track=` when this driver has driven it, else their newest track; the car
 * from `?car=` (`any` = every car), else the car of the newest session at that track (any car when that car is
 * unknown). Null when the driver has no sessions with laps.
 */
export function resolveScope(
  choices: readonly TrackChoice[],
  q: { track?: string | null; car?: string | null },
): Scope | null {
  const track = (q.track ? choices.find((c) => c.trackId === q.track) : undefined) ?? choices[0];
  if (!track) return null;
  let carId: string | null;
  if (q.car === ANY_CAR) carId = null;
  else if (q.car && track.cars.some((c) => c.id === q.car)) carId = q.car;
  else carId = track.newestCarId && track.cars.some((c) => c.id === track.newestCarId) ? track.newestCarId : null;
  const car = carId ? track.cars.find((c) => c.id === carId) : undefined;
  return { track, carId, carLabel: car?.label ?? null, carNamed: car?.named ?? false };
}

/** The D5 request for a scope (synthetic tracks ask for synthetic sessions, which D5 leaves out otherwise). */
export function scopeQuery(scope: Scope, opts: { corners?: boolean } = {}): ProgressQuery {
  return {
    game: scope.track.game,
    track_id: scope.track.trackId,
    car: scope.carId,
    synthetic: scope.track.synthetic || undefined,
    corners: opts.corners,
    limit: PROGRESS_LIMIT,
  };
}

/** "Austria · Haas", "Austria · any car". */
export function scopeLabel(scope: Scope): string {
  return `${scope.track.label} · ${scope.carLabel ?? "any car"}`;
}

// -------------------------------------------------------------------------------------------------------- points

export interface SessionPoint {
  sessionId: string;
  startedUnix: number;
  synthetic: boolean;
  carId: string | null;
  carName: string | null;
  sessionType: string | null;
  /** Every stored lap. */
  laps: number;
  /** Clean laps; null when unknown (before D5). */
  cleanLaps: number | null;
  bestMs: number | null;
  /** D5 only. */
  medianMs: number | null;
  /** D5 only: slowest minus fastest clean lap. */
  spreadMs: number | null;
  /** D5: learned corner -> mean time lost against the current reference (s). */
  corners: Record<string, number> | null;
  /** D5: corrective rule kind -> times it fired. */
  habits: Record<string, number> | null;
  refLapId: number | null;
}

const posMs = (v: unknown): number | null => (finite(v) && v > 0 ? v : null);

/** Lap level, before D5: the driver's session rows in this scope, oldest first, the newest `limit`. */
export function pointsFromRows(
  rows: readonly (SessionListRow & { car_id?: string | null })[],
  scope: Scope,
  limit = PROGRESS_LIMIT,
): SessionPoint[] {
  const t = scope.track;
  return rows
    .filter(
      (r) =>
        r.game === t.game &&
        r.track_id === t.trackId &&
        drivenRow(r, t.synthetic) &&
        (scope.carId == null || (r.car_id ?? null) === scope.carId),
    )
    .sort((a, b) => a.started_unix - b.started_unix || a.id.localeCompare(b.id))
    .slice(-limit)
    .map((r) => ({
      sessionId: r.id,
      startedUnix: r.started_unix,
      synthetic: r.synthetic,
      carId: r.car_id ?? null,
      carName: carText(r),
      sessionType: r.session_label ?? r.session_type_raw ?? r.session_type ?? null,
      laps: r.lap_count,
      cleanLaps: finite(r.clean_lap_count) ? r.clean_lap_count : null,
      bestMs: posMs(r.best_clean_ms),
      medianMs: null,
      spreadMs: null,
      corners: null,
      habits: null,
      refLapId: null,
    }));
}

/** D5's sessions (already oldest first and scoped by the server). */
export function pointsFromProgress(p: Pick<DriverProgress, "sessions">): SessionPoint[] {
  return p.sessions.map((s: ProgressSession) => ({
    sessionId: s.session_id,
    startedUnix: s.started_unix,
    synthetic: s.synthetic,
    carId: s.car_id,
    carName: readableCar(s.car_name),
    sessionType: s.session_type,
    laps: s.laps,
    cleanLaps: finite(s.clean_laps) ? s.clean_laps : null,
    bestMs: posMs(s.best_clean_ms),
    medianMs: posMs(s.median_clean_ms),
    spreadMs: finite(s.spread_ms) && s.spread_ms >= 0 ? s.spread_ms : null,
    corners: s.corners,
    habits: s.habits,
    refLapId: s.ref_lap_id,
  }));
}

/** Axis labels for sessions (words.ts; kept here for the pages that import it from Progress). */
export { sessionLabels };

/** Distinct cars among points (unknown counts as its own). */
export function carsOf(points: readonly SessionPoint[]): number {
  return new Set(points.map((p) => p.carId ?? `?${p.carName ?? ""}`)).size;
}

// -------------------------------------------------------------------------------------------------- who is shown

export interface Who {
  /** "Your" / "Alex's" (sentence start). */
  Poss: string;
  /** "your" / "Alex's". */
  poss: string;
  name: string;
  /** The page is about the person in the seat (or the only driver): "your". */
  self: boolean;
}

export function whoFor(viewed: Pick<Driver, "id" | "name"> | null, seatedId: number | null, drivers: number): Who {
  const self = !viewed || viewed.id === seatedId || drivers <= 1;
  const name = viewed?.name ?? "This driver";
  if (self) return { Poss: "Your", poss: "your", name, self };
  const p = `${name}'s`; // "James's", as the server's reference labels say it
  return { Poss: p, poss: p, name, self };
}

// ------------------------------------------------------------------------------------------------- PBs, milestones

/** A session that set a new best for its car (laps inside one session are collapsed: its final best counts). */
export interface BestStep {
  sessionId: string;
  /** When the session's best was set (D5: the lap's time; else the session's start). */
  unix: number;
  carId: string | null;
  carName: string | null;
  ms: number;
  lapNumber: number | null;
  /** The best before this session (null: the first clean lap in this car here). */
  previousMs: number | null;
  /** previousMs - ms (> 0). */
  gainMs: number | null;
  first: boolean;
  /** For a first step with D5's PB history: the very first clean lap (the session may have improved on it). */
  firstLap: { ms: number; lapNumber: number; unix: number } | null;
}

/**
 * New bests per car, oldest first. With D5's PB history (exact, per lap) the laps of one session are collapsed into
 * one step: the best before the session, and the session's final best. Without it, from the session bests in order
 * (sessions whose car is unknown cannot be a PB and are skipped).
 */
export function bestSteps(points: readonly SessionPoint[], pbHistory: readonly PbHistoryEntry[] | null): BestStep[] {
  const steps: BestStep[] = [];
  if (pbHistory) {
    const byCar = new Map<string, PbHistoryEntry[]>();
    for (const e of pbHistory) {
      const k = e.car_id ?? "";
      const list = byCar.get(k);
      if (list) list.push(e);
      else byCar.set(k, [e]);
    }
    for (const list of byCar.values()) {
      let i = 0;
      while (i < list.length) {
        const head = list[i]!;
        let j = i;
        while (j + 1 < list.length && list[j + 1]!.session_id === head.session_id) j += 1;
        const last = list[j]!;
        const prev = head.previous_ms;
        steps.push({
          sessionId: head.session_id,
          unix: last.set_unix,
          carId: last.car_id,
          carName: readableCar(last.car_name),
          ms: last.lap_ms,
          lapNumber: last.lap_number,
          previousMs: prev,
          gainMs: prev != null ? prev - last.lap_ms : null,
          first: prev == null,
          firstLap: prev == null ? { ms: head.lap_ms, lapNumber: head.lap_number, unix: head.set_unix } : null,
        });
        i = j + 1;
      }
    }
  } else {
    const best = new Map<string, number>();
    for (const p of points) {
      if (p.bestMs == null || p.carId == null) continue;
      const prev = best.get(p.carId);
      if (prev != null && p.bestMs >= prev) continue;
      best.set(p.carId, p.bestMs);
      steps.push({
        sessionId: p.sessionId,
        unix: p.startedUnix,
        carId: p.carId,
        carName: p.carName,
        ms: p.bestMs,
        lapNumber: null,
        previousMs: prev ?? null,
        gainMs: prev != null ? prev - p.bestMs : null,
        first: prev == null,
        firstLap: null,
      });
    }
  }
  return steps.sort((a, b) => a.unix - b.unix);
}

export interface Milestone {
  key: string;
  unix: number;
  kind: "first_clean" | "pb" | "ten_clean";
  title: string;
  detail: string | null;
  sessionId: string;
}

/** A session with this many clean laps is a milestone (spec 6.9). */
export const CLEAN_LAPS_MILESTONE = 10;

/**
 * Milestones, newest first (spec 6.9): the first clean lap at the track (then in each other car when the scope is
 * any car), each new PB with its gain, and the first session with 10 clean laps (only when clean counts are known).
 */
export function milestones(
  points: readonly SessionPoint[],
  steps: readonly BestStep[],
  opts: { trackLabel: string; multiCar: boolean },
): Milestone[] {
  const out: Milestone[] = [];
  let firstSeen = false;
  for (const s of steps) {
    const car = opts.multiCar && s.carName ? ` · ${s.carName}` : "";
    const lap = s.lapNumber != null ? ` · lap ${s.lapNumber}` : "";
    if (s.first) {
      // The first clean lap itself when D5 says which it was; else the session's best (the rows know no more).
      const what = s.firstLap
        ? `${lapTime(s.firstLap.ms)} · lap ${s.firstLap.lapNumber}`
        : `best that session ${lapTime(s.ms)}`;
      out.push({
        key: `first:${s.carId ?? ""}:${s.sessionId}`,
        unix: s.firstLap?.unix ?? s.unix,
        kind: "first_clean",
        title: !firstSeen || !s.carName ? `First clean lap at ${opts.trackLabel}` : `First clean lap in the ${s.carName}`,
        detail: `${what}${firstSeen ? "" : car}`,
        sessionId: s.sessionId,
      });
      firstSeen = true;
    } else {
      out.push({
        key: `pb:${s.carId ?? ""}:${s.sessionId}`,
        unix: s.unix,
        kind: "pb",
        title: `New PB ${lapTime(s.ms)}`,
        detail: `${spreadSeconds(s.gainMs)} faster than before${lap}${car}`,
        sessionId: s.sessionId,
      });
    }
  }
  const ten = points.find((p) => p.cleanLaps != null && p.cleanLaps >= CLEAN_LAPS_MILESTONE);
  if (ten) {
    out.push({
      key: `ten:${ten.sessionId}`,
      unix: ten.startedUnix,
      kind: "ten_clean",
      title: `First session with ${CLEAN_LAPS_MILESTONE} clean laps`,
      detail: `${ten.cleanLaps} of ${plural(ten.laps, "lap")}`,
      sessionId: ten.sessionId,
    });
  }
  return out.sort((a, b) => b.unix - a.unix || a.key.localeCompare(b.key));
}

/** The badge a progress dot or tile shows for a session (lib/bests.ts): REC or PB, else nothing (neutral). Unknown
 * (badges not loaded) is neutral. */
export function recordBadge(badges: ReadonlyMap<string, BestBadge> | null | undefined, sessionId: string | null | undefined): TimingStatus {
  const b = sessionId ? badges?.get(sessionId) : undefined;
  return b === "rec" || b === "pb" ? b : "neutral";
}

// ----------------------------------------------------------------------------------------------- the sentences

function withBest(points: readonly SessionPoint[]): (SessionPoint & { bestMs: number })[] {
  return points.filter((p): p is SessionPoint & { bestMs: number } => p.bestMs != null);
}

/** A time in seconds for prose: "1.2 s", "0.35 s" (no sign; the sentence says the direction). */
const sec = (ms: number): string => spreadSeconds(ms);

/**
 * "Getting faster?" in one computed sentence (spec 6.9, never an LLM), from the best clean lap per session; with
 * D5's medians it also notices a typical lap getting faster while the best stands.
 */
export function fasterSentence(points: readonly SessionPoint[], who: Who, opts: { multiCar?: boolean } = {}): string {
  const s = fasterCore(points, who);
  if (!opts.multiCar || withBest(points).length < 2) return s;
  // Any car, and more than one car: the change mixes car and driver, and the sentence says so.
  const core = s.replace(/^Yes: (.)/, (_, c: string) => c.toUpperCase()).replace(/\.$/, "");
  return `${core}; the cars differ, so not all of that is the driver.`;
}

function fasterCore(points: readonly SessionPoint[], who: Who): string {
  const timed = withBest(points);
  if (!timed.length) {
    return points.length
      ? `No clean lap here yet in ${plural(points.length, "session")}: a clean lap starts the progress line.`
      : "No sessions here yet: drive a clean lap to start the progress line.";
  }
  if (timed.length === 1) {
    return `One session here with a clean lap so far (${who.poss} best is ${lapTime(timed[0]!.bestMs)}): drive here again to see a trend.`;
  }
  const first = timed[0]!;
  const last = timed[timed.length - 1]!;
  const best = Math.min(...timed.map((p) => p.bestMs));
  const n = timed.length;
  const gain = first.bestMs - best;
  if (gain >= 5) {
    const head = `Yes: ${who.poss} best here dropped ${sec(gain)} over ${n} sessions`;
    if (last.bestMs === best) return `${head}, and the last one set it.`;
    return `${head}; the last session was ${sec(last.bestMs - best)} off it.`;
  }
  const medians = timed.filter((p) => p.medianMs != null);
  const mFirst = medians[0]?.medianMs;
  const mLast = medians[medians.length - 1]?.medianMs;
  if (medians.length >= 2 && mFirst != null && mLast != null && mFirst - mLast >= 5) {
    return `${who.Poss} best here still dates from the first session, but ${who.poss} typical lap got ${sec(mFirst - mLast)} faster over ${n} sessions.`;
  }
  return `Not yet: ${who.poss} best here is still the ${lapTime(first.bestMs)} from the first of ${n} sessions.`;
}

/** "Getting steadier?" in one computed sentence, from the spread of clean laps (D5). */
export function steadierSentence(points: readonly SessionPoint[], who: Who): string {
  const s = points.filter((p): p is SessionPoint & { spreadMs: number } => p.spreadMs != null);
  if (!s.length) return "Needs a session here with 2 clean laps.";
  const last = s[s.length - 1]!;
  if (s.length === 1) {
    return `${who.Poss} clean laps were within ${sec(last.spreadMs)} of each other in the one session here with 2 or more.`;
  }
  const first = s[0]!;
  const a = sec(first.spreadMs);
  const b = sec(last.spreadMs);
  if (a === b) return `About as steady as at first: ${who.poss} clean laps are within ${b} of each other.`;
  if (last.spreadMs < first.spreadMs) {
    return `Steadier: ${who.poss} clean laps went from within ${a} to within ${b} of each other over ${s.length} sessions.`;
  }
  return `Less steady than at first: ${who.poss} clean laps are now within ${b} of each other, against ${a} in the first session here.`;
}

// ------------------------------------------------------------------------------------------------- headline tiles

export interface ProgressTiles {
  best: {
    ms: number | null;
    status: TimingStatus;
    /** First session's best minus the best (> 0), with 2+ sessions; null across different cars. */
    gainMs: number | null;
    /** The car of the best lap when the sessions are in more than one car. */
    carOfBest: string | null;
    /** The first session with a clean lap. */
    sinceUnix: number | null;
    /** Sparkline values: seconds faster than the first session's best (higher = faster). */
    spark: { v: number }[];
  };
  sessions: number;
  /** Clean laps over the sessions shown; `known` false before D5 (the tile then shows laps). */
  clean: { known: boolean; clean: number; laps: number };
  /** New PBs (not first laps) set this calendar month. */
  newPbs: { count: number; unix: number[] };
}

export function progressTiles(
  points: readonly SessionPoint[],
  steps: readonly BestStep[],
  nowMs: number,
  opts: { badges?: ReadonlyMap<string, BestBadge> | null; multiCar?: boolean },
): ProgressTiles {
  const timed = withBest(points);
  const bestMs = timed.length ? Math.min(...timed.map((p) => p.bestMs)) : null;
  const first = timed[0] ?? null;
  const gainMs =
    !opts.multiCar && timed.length >= 2 && first && bestMs != null && first.bestMs - bestMs > 0 ? first.bestMs - bestMs : null;
  const bestPoint = timed.find((p) => p.bestMs === bestMs) ?? null;
  // The best lap's badge under the one rule (REC / PB, lib/bests.ts); neutral until the badges are known.
  const status: TimingStatus = bestMs != null ? recordBadge(opts.badges, bestPoint?.sessionId) : "neutral";
  const known = points.length > 0 && points.every((p) => p.cleanLaps != null);
  const now = new Date(nowMs);
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1).getTime() / 1000;
  const pbs = steps.filter((s) => !s.first && s.unix >= monthStart);
  return {
    best: {
      ms: bestMs,
      status,
      gainMs,
      carOfBest: opts.multiCar ? (bestPoint?.carName ?? null) : null,
      sinceUnix: first?.startedUnix ?? null,
      spark: first ? timed.map((p) => ({ v: (first.bestMs - p.bestMs) / 1000 })) : [],
    },
    sessions: points.length,
    clean: {
      known,
      clean: points.reduce((a, p) => a + (p.cleanLaps ?? 0), 0),
      laps: points.reduce((a, p) => a + p.laps, 0),
    },
    newPbs: { count: pbs.length, unix: pbs.map((s) => s.unix) },
  };
}

/**
 * The Best here tile's line: the gain in words with a sensible time phrase (spec 9.6; one convention with Drive and
 * Review: "1.2 s faster", never a sign): "1.2 s faster today" when every session here was today, else "1.2 s faster
 * since your first session here (3 Oct)".
 */
export function bestHereLine(tiles: Pick<ProgressTiles, "best" | "sessions">, nowMs: number, who: Pick<Who, "poss">): string {
  const { best } = tiles;
  if (best.ms == null) return "No clean lap here yet";
  if (best.carOfBest) return `In the ${best.carOfBest}; the cars differ, so no trend`;
  if (best.gainMs != null && best.sinceUnix != null) {
    const gain = `${spreadSeconds(best.gainMs)} faster`;
    const day = dayTitle(best.sinceUnix, nowMs);
    return day === "Today" ? `${gain} today` : `${gain} since ${who.poss} first session here (${dayInSentence(best.sinceUnix, nowMs)})`;
  }
  return tiles.sessions > 1 ? "No faster than the first session yet" : "One session with a clean lap so far";
}

// --------------------------------------------------------------------------------------------- what changed (D5)

export type TrendWord = "better" | "same" | "worse";

/** better when the loss fell by at least the threshold, worse when it grew by at least it, else same. */
export function trendOf(changeS: number, thresholdS: number): TrendWord {
  if (changeS <= -thresholdS) return "better";
  if (changeS >= thresholdS) return "worse";
  return "same";
}

export interface CornerText {
  /** Official short label ("T6", "T10-13 (1)"), else the learned name. */
  label: string;
  /** The server's long text ("Turn 9 (Rindt Kurve)"), else the label. */
  long: string;
}

/** A learned corner's words from D5's `corner_text` (server-written; the UI never parses them). */
export function cornerTextOf(
  text: ProgressCornerText | null | undefined,
  game: string,
  trackId: string,
  key: string,
): CornerText {
  const t = text?.[`${game}/${trackId}`]?.[key];
  const label = t?.short?.trim() || key;
  return { label, long: t?.long?.trim() || label };
}

export interface CornerTrend extends CornerText {
  key: string;
  values: { sessionId: string; unix: number; s: number }[];
  first: number;
  last: number;
  /** last - first (negative = less time lost). */
  change: number;
  trend: TrendWord;
}

/** Sessions D5 compared with the reference (corner means present). */
export function comparedPoints(points: readonly SessionPoint[]): SessionPoint[] {
  return points.filter((p) => p.corners != null && Object.keys(p.corners).length > 0);
}

/**
 * Corner trends (spec 6.9 "What changed?"): per corner, the mean time lost against the driver's current reference in
 * each compared session (oldest first). Corners measured in fewer than two sessions are left out. Biggest change
 * first.
 */
export function cornerTrends(
  points: readonly SessionPoint[],
  text: ProgressCornerText | null | undefined,
  game: string,
  trackId: string,
  thresholdS = DEFAULT_THRESHOLD_S,
): CornerTrend[] {
  const compared = comparedPoints(points);
  if (compared.length < 2) return [];
  const keys = new Set(compared.flatMap((p) => Object.keys(p.corners ?? {})));
  const out: CornerTrend[] = [];
  for (const key of keys) {
    const values = compared
      .filter((p) => finite(p.corners?.[key]))
      .map((p) => ({ sessionId: p.sessionId, unix: p.startedUnix, s: p.corners![key]! }));
    if (values.length < 2) continue;
    const first = values[0]!.s;
    const last = values[values.length - 1]!.s;
    const change = last - first;
    out.push({ key, ...cornerTextOf(text, game, trackId, key), values, first, last, change, trend: trendOf(change, thresholdS) });
  }
  return out.sort((a, b) => Math.abs(b.change) - Math.abs(a.change) || b.last - a.last || a.key.localeCompare(b.key));
}

/** "0.40 s lost", "0.23 s gained", "level" for a corner mean. */
export function lostWords(s: number): string {
  if (s >= 0.005) return `${s.toFixed(2)} s lost`;
  if (s <= -0.005) return `${Math.abs(s).toFixed(2)} s gained`;
  return "level";
}

/** "What changed?" in one computed sentence. */
export function changeSentence(trends: readonly CornerTrend[], compared: number, thresholdS = DEFAULT_THRESHOLD_S): string {
  if (compared < 2) return "Needs two sessions here compared with the reference lap.";
  const top = trends[0];
  if (!top || top.trend === "same") {
    return `No corner changed by ${thresholdS.toFixed(2)} s a lap or more between the first and the last compared session.`;
  }
  return `Biggest change at ${top.long}: ${lostWords(top.first)} a lap in the first compared session here, ${lostWords(top.last)} in the last.`;
}

/** Corrective rule kinds in plain words (analysis/coaching.py); descriptions, never advice. */
export const HABIT_WORDS: Readonly<Record<string, string>> = {
  brake_early: "Braking earlier than the reference",
  brake_late_overdrive: "Braking later without a faster exit",
  low_min_speed: "Slower at the slowest point",
  overspeed_apex: "Faster into the apex, slower out",
  late_throttle: "Later to full throttle",
  coasting: "Coasting between brake and throttle",
};

export function habitWords(kind: string): string {
  return HABIT_WORDS[kind] ?? kind.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

export interface HabitTrend {
  kind: string;
  words: string;
  /** Oldest first, the last `window` compared sessions. */
  counts: { sessionId: string; unix: number; count: number; laps: number }[];
}

/** Habit counts per compared session (D5), the last `window` sessions; most seen in the last session first. */
export function habitTrends(points: readonly SessionPoint[], window = 5): HabitTrend[] {
  const s = points.filter((p) => p.habits != null).slice(-window);
  if (!s.length) return [];
  const kinds = new Set(s.flatMap((p) => Object.keys(p.habits ?? {})));
  const out: HabitTrend[] = [...kinds].map((kind) => ({
    kind,
    words: habitWords(kind),
    counts: s.map((p) => ({ sessionId: p.sessionId, unix: p.startedUnix, count: p.habits?.[kind] ?? 0, laps: p.laps })),
  }));
  const lastOf = (h: HabitTrend) => h.counts[h.counts.length - 1]?.count ?? 0;
  return out.sort((a, b) => lastOf(b) - lastOf(a) || a.kind.localeCompare(b.kind));
}

// --------------------------------------------------------------------------------------------------- family board

/** A driver on the family board: their best clean lap on the board's exact key, or no time yet (`ms` null). */
export interface FamilyRow {
  driverId: number;
  /** The profile (avatar, colour); null when this page's list does not have it. */
  driver: Driver | null;
  name: string;
  /** 1 = fastest; null without a time. */
  position: number | null;
  ms: number | null;
  lapId: number | null;
  lapNumber: number | null;
  sessionId: string | null;
  /** ms - the leader's ms; null for the leader and for drivers without a time. */
  gapMs: number | null;
  gapPct: number | null;
  /** The server's words: "3.067 s behind" ("Fastest" for the leader); null without a time. */
  gapText: string | null;
  /** Marked "Fastest" in words; its time stays neutral (REC / PB badges are on the tiles and the chart). */
  leader: boolean;
  viewed: boolean;
  dateText: string | null;
  cleanLaps: number | null;
  sectorsMs: (number | null)[] | null;
  theoreticalMs: number | null;
  theoreticalGainMs: number | null;
  gameVersion: string | null;
  /** The gap and band to each optional row of the board (EA rival, real F1). */
  vs: BoardVsAll;
}

export interface FamilyBoard {
  /** The board's key (string form); null when there is no board to show. */
  key: string | null;
  labels: BoardLabels | null;
  /** Drivers with a time, fastest first, then the household drivers with no time here, by name. */
  rows: FamilyRow[];
  /** The board's record, for the chart's neutral line. */
  record: { ms: number; name: string; driver: Driver | null } | null;
}

/**
 * The family board (spec 6.9, leaderboard spec 1 and 5) from the server's board of an EXACT key (`/api/leaderboard`:
 * game, track, layout, car, session type, weather and assists; an unknown part is its own board, never "any car"):
 * each driver's best clean, valid lap of real driving, the gap to the leader in words, the leader marked "Fastest",
 * every time neutral; then the household drivers with no time on it. `board` null (loading, or a server without
 * boards): no rows.
 */
export function familyBoard(
  drivers: readonly Driver[],
  board: Pick<LeaderboardBoard, "key" | "labels" | "rows" | "no_time" | "record"> | null,
  viewedId: number | null,
): FamilyBoard {
  const byId = new Map(drivers.map((d) => [d.id, d]));
  const timed: FamilyRow[] = (board?.rows ?? []).map((r) => ({
    driverId: r.driver_id,
    driver: byId.get(r.driver_id) ?? null,
    name: r.driver_name,
    position: r.position,
    ms: r.lap_ms,
    lapId: r.lap_id,
    lapNumber: r.lap_number,
    sessionId: r.session_id,
    gapMs: r.gap_ms,
    gapPct: r.gap_pct,
    gapText: r.gap_text,
    leader: r.leader,
    viewed: r.driver_id === viewedId,
    dateText: r.date_text,
    cleanLaps: r.clean_laps,
    sectorsMs: r.best_sectors_ms,
    theoreticalMs: r.theoretical_best_ms,
    theoreticalGainMs: r.theoretical_gain_ms,
    gameVersion: r.game_version,
    vs: r.vs ?? {},
  }));
  const none: FamilyRow[] = (board?.no_time ?? [])
    .map((n) => ({
      driverId: n.driver_id,
      driver: byId.get(n.driver_id) ?? null,
      name: n.driver_name,
      position: null,
      ms: null,
      lapId: null,
      lapNumber: null,
      sessionId: null,
      gapMs: null,
      gapPct: null,
      gapText: null,
      leader: false,
      viewed: n.driver_id === viewedId,
      dateText: null,
      cleanLaps: null,
      sectorsMs: null,
      theoreticalMs: null,
      theoreticalGainMs: null,
      gameVersion: null,
      vs: {},
    }))
    .sort((a, b) => a.name.localeCompare(b.name));
  const rec = board?.record ?? null;
  return {
    key: board?.key ?? null,
    labels: board?.labels ?? null,
    rows: [...timed, ...none],
    record: rec ? { ms: rec.lap_ms, name: rec.driver_name, driver: byId.get(rec.driver_id) ?? null } : null,
  };
}
