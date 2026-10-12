// ONE rule for the timing badges on Drive, Review and Progress (design spec 4.6). Pure; tested in node (bests.test.ts).
//
//   REC  the household (family) record: the fastest clean lap anyone has driven here.
//   PB   the driver's best ever here.
//   SB   the best clean lap of this session.
//   The strongest badge that applies wins (REC > PB > SB): a lap that is the household record is never badged as only
//   a PB or an SB anywhere (its lap badge, and the tag of a tile that says "this session set it").
//
// "Here" is the same scope everywhere: the same game + track + car + layout (track lengths within 3 %; an unknown
// length does not veto), clean laps only, real driving only. Synthetic data and replays are never coloured and never
// count as a best. A badge says what a lap IS now (current standing): when two laps tie, the earlier one keeps the
// best. Drive reads the holders from D2 (snapshot.bests, `repo.lap_bests`, which applies exactly this scope); Review
// and Progress have no D2 for past sessions, so they find the same holders in the session list (`sessionBests`), which
// carries each session's game, track, car, length, owner and best clean lap.
//
// The session list is a window (the newest SESSION_LIST_LIMIT sessions). When it is cut off, an older faster lap can
// be outside it, so a REC / PB found in the window is only claimed when each driver's all-time best at the track
// (`stats.best_laps`, any car of the same car family: an F1 lap never contradicts an F2 PB) cannot contradict it;
// otherwise the lap keeps the badge that is certain (SB).

import { fitsFamily, type CarClass, type CarFamily } from "./carclass";
import type { Driver } from "./drivers";

export type BestBadge = "rec" | "pb" | "sb" | "neutral";

export interface BadgeFacts {
  /** The session is in the timing scope (not synthetic, not a replay). */
  coloured: boolean;
  /** The lap holds the household record here. */
  household: boolean;
  /** The lap holds the driver's best ever here. */
  driver: boolean;
  /** The lap is the best clean lap of its session. */
  session: boolean;
}

/** The one rule: outside the timing scope nothing is coloured; otherwise the strongest badge that applies. */
export function bestBadge(f: BadgeFacts): BestBadge {
  if (!f.coloured) return "neutral";
  if (f.household) return "rec";
  if (f.driver) return "pb";
  if (f.session) return "sb";
  return "neutral";
}

/** Badge strength, for "the strongest wins" comparisons. */
export const BADGE_RANK: Readonly<Record<BestBadge, number>> = { rec: 3, pb: 2, sb: 1, neutral: 0 };

// --------------------------------------------------------------------------------------------------------- scope

/** Two track lengths within this fraction are one layout (`repo.BESTS_LENGTH_TOLERANCE`). */
export const LAYOUT_TOLERANCE = 0.03;

const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const positive = (v: unknown): v is number => finite(v) && v > 0;

/** Same layout: false only when both lengths are known and differ by more than 3 % (unknown = no veto). */
export function sameLayout(a: number | null | undefined, b: number | null | undefined): boolean {
  if (!positive(a) || !positive(b)) return true;
  return Math.abs(a - b) <= LAYOUT_TOLERANCE * Math.max(a, b);
}

/** The session list fields the rule needs (`repo.list_sessions`). */
export interface ScopeRow {
  id: string;
  driver_id: number | null;
  game: string;
  track_id: string | null;
  car_id?: string | null;
  track_length_m: number | null;
  synthetic: boolean;
  source?: string | null;
  best_clean_ms: number | null;
  started_unix: number;
  /** F2 support: the session's car class (absent from older servers). */
  car_class?: CarClass | null;
}

/** Real driving: never synthetic, never a replay (`source` "replay:…"). */
export function rowInTimingScope(r: Pick<ScopeRow, "synthetic" | "source">): boolean {
  return r.synthetic !== true && !(typeof r.source === "string" && r.source.startsWith("replay:"));
}

/** The session has a scope at all: a known track and car (a record in another car is not a record here). */
export function hasScope(r: Pick<ScopeRow, "track_id" | "car_id">): boolean {
  return !!r.track_id && !!r.car_id;
}

/** `r` counts towards the bests of `ref`'s scope: same game, track, car and layout, real driving. */
export function sameScope(r: ScopeRow, ref: ScopeRow): boolean {
  return (
    rowInTimingScope(r) &&
    hasScope(ref) &&
    r.game === ref.game &&
    r.track_id === ref.track_id &&
    (r.car_id ?? null) === (ref.car_id ?? null) &&
    sameLayout(r.track_length_m, ref.track_length_m)
  );
}

// ------------------------------------------------------------------------------------------------------- holders

/** Who holds a best: the session of the lap, its driver, the time. */
export interface Holder {
  sessionId: string;
  driverId: number | null;
  ms: number;
  startedUnix: number;
}

function holderOf(r: ScopeRow): Holder | null {
  return positive(r.best_clean_ms)
    ? { sessionId: r.id, driverId: r.driver_id, ms: r.best_clean_ms, startedUnix: r.started_unix }
    : null;
}

/** `a` holds the best against `b`: faster, or the same time set earlier (the earlier lap keeps a tie). */
function beats(a: Holder, b: Holder): boolean {
  if (a.ms !== b.ms) return a.ms < b.ms;
  if (a.startedUnix !== b.startedUnix) return a.startedUnix < b.startedUnix;
  return a.sessionId < b.sessionId;
}

function fastest(rows: readonly ScopeRow[]): Holder | null {
  let best: Holder | null = null;
  for (const r of rows) {
    const h = holderOf(r);
    if (h && (!best || beats(h, best))) best = h;
  }
  return best;
}

/** A driver's all-time best at a track in any car of one family (`stats.best_laps`): a lower bound for the certainty
 * check. */
export interface AllTimeBest {
  driverId: number;
  game: string;
  trackId: string;
  ms: number;
  sessionId: string;
  synthetic: boolean;
  /** F2 support: the car family the best was set in; null / absent = unknown (it then counts for every family). */
  family?: CarFamily | null;
}

export function allTimeBests(drivers: readonly Pick<Driver, "id" | "stats">[] | null | undefined): AllTimeBest[] {
  const out: AllTimeBest[] = [];
  for (const d of drivers ?? []) {
    for (const b of d.stats?.best_laps ?? []) {
      if (positive(b.lap_time_ms)) {
        out.push({
          driverId: d.id,
          game: b.game,
          trackId: b.track_id,
          ms: b.lap_time_ms,
          sessionId: b.session_id,
          synthetic: b.synthetic,
          family: b.car_family ?? null,
        });
      }
    }
  }
  return out;
}

export interface SessionBests {
  /** Badges beyond SB can apply: real driving with a known track and car. */
  scoped: boolean;
  /** The household record here, in the window. */
  household: Holder | null;
  /** The session driver's best ever here, in the window (null without a driver). */
  driver: Holder | null;
  /** The driver's best here before this session started (for "faster than your earlier best"). */
  previous: Holder | null;
  /** A REC / PB found in the window holds for certain (the window is complete, or no all-time best contradicts it). */
  certain: { household: boolean; driver: boolean };
}

export interface BestsOptions {
  /** The window is the whole history (the list came back shorter than its limit). */
  complete: boolean;
  /** Every driver's all-time best per track (`allTimeBests`), for a cut-off window. */
  allTime?: readonly AllTimeBest[];
}

/** No all-time best of anyone (or of `driverId`) at this track, in a car of this family, is faster than, or ties
 * elsewhere with, `h`. */
function confirmed(h: Holder, session: ScopeRow, allTime: readonly AllTimeBest[], driverId: number | null): boolean {
  return allTime
    .filter(
      (a) =>
        !a.synthetic &&
        a.game === session.game &&
        a.trackId === session.track_id &&
        fitsFamily(a.family, session.car_class) &&
        (driverId == null || a.driverId === driverId),
    )
    .every((a) => a.sessionId === h.sessionId || a.ms > h.ms);
}

/**
 * The bests of `session`'s scope found in `rows` (the session list; `session` itself is counted even when the list
 * does not have it yet).
 */
export function sessionBests(session: ScopeRow, rows: readonly ScopeRow[], opts: BestsOptions): SessionBests {
  const none: SessionBests = { scoped: false, household: null, driver: null, previous: null, certain: { household: false, driver: false } };
  if (!rowInTimingScope(session) || !hasScope(session)) return none;
  const inScope = rows.filter((r) => r.id !== session.id && sameScope(r, session));
  inScope.push(session);
  const household = fastest(inScope);
  const mine = session.driver_id == null ? [] : inScope.filter((r) => r.driver_id === session.driver_id);
  const driver = session.driver_id == null ? null : fastest(mine);
  const previous = fastest(
    mine.filter((r) => r.id !== session.id && (r.started_unix < session.started_unix || (r.started_unix === session.started_unix && r.id < session.id))),
  );
  const allTime = opts.allTime ?? [];
  return {
    scoped: true,
    household,
    driver,
    previous,
    certain: {
      household: opts.complete || (household != null && confirmed(household, session, allTime, null)),
      driver: opts.complete || (driver != null && confirmed(driver, session, allTime, session.driver_id)),
    },
  };
}

/** The badge of `session`'s best clean lap under the one rule. */
export function sessionBadge(session: ScopeRow, b: SessionBests): BestBadge {
  const own = positive(session.best_clean_ms);
  return bestBadge({
    coloured: rowInTimingScope(session) && own,
    household: b.scoped && b.certain.household && b.household?.sessionId === session.id,
    driver: b.scoped && b.certain.driver && b.driver?.sessionId === session.id,
    session: own,
  });
}

/** Each listed session's badge (its best clean lap), from one window of rows. */
export function sessionBadges(
  sessions: readonly ScopeRow[],
  rows: readonly ScopeRow[],
  opts: BestsOptions,
): Map<string, BestBadge> {
  const out = new Map<string, BestBadge>();
  for (const s of sessions) out.set(s.id, sessionBadge(s, sessionBests(s, rows, opts)));
  return out;
}

// --------------------------------------------------------------------------------------------------------- words

/** Seconds for a gain or a gap: 2 decimals below 1 s, 1 decimal from 1 s up ("0.35 s", "5.8 s"). Never signed. */
export function gainSeconds(ms: number): string {
  const s = Math.abs(ms) / 1000;
  return `${s.toFixed(s >= 0.995 ? 1 : 2)} s`;
}

/** A change in lap time as words: the amount (null when level) and the word. */
export interface ChangeText {
  /** "5.8 s faster", "0.40 s slower", "level". */
  text: string;
  /** "5.8 s", or null when level. */
  amount: string | null;
  word: "faster" | "slower" | "level";
}

/** Under this a change reads "level" (a lap time has whole milliseconds; 0.004 s is not a change worth a word). */
export const LEVEL_MS = 5;

/**
 * A change in lap time in words, the one convention on every page (spec 9.6): a positive number and a word, never a
 * bare sign. `ms` is new minus old: negative = faster. "5.8 s faster", "0.40 s slower", "level". For a session's own
 * progress (Gained today); a gap to a best uses `gapWords`.
 */
export function changeWords(ms: number | null | undefined): ChangeText | null {
  if (!finite(ms)) return null;
  if (Math.abs(ms) < LEVEL_MS) return { text: "level", amount: null, word: "level" };
  const word = ms < 0 ? "faster" : "slower";
  const amount = gainSeconds(ms);
  return { text: `${amount} ${word}`, amount, word };
}

/** Seconds for a gap to a best: 3 decimals below 1 s ("0.003 s"), as precise as the lap times compared; 1 decimal
 * from 1 s up ("5.8 s"). Never signed. */
export function gapSeconds(ms: number): string {
  const whole = Math.round(Math.abs(ms));
  return `${(whole / 1000).toFixed(whole >= 1000 ? 1 : 3)} s`;
}

/**
 * A gap to a best (your PB, the family record, the leader, an earlier best) in words, `changeWords`' convention but
 * as precise as the badges: a lap 0.003 s off the PB reads "0.003 s slower", never "level" while its badge says it is
 * not the best. "level" only for an exact tie (the earlier lap keeps the best). `ms` is new minus best.
 */
export function gapWords(ms: number | null | undefined): ChangeText | null {
  if (!finite(ms)) return null;
  if (Math.round(Math.abs(ms)) === 0) return { text: "level", amount: null, word: "level" };
  const word = ms < 0 ? "faster" : "slower";
  const amount = gapSeconds(ms);
  return { text: `${amount} ${word}`, amount, word };
}
