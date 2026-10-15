// "Work on" and "Went well" (spec 6.3 #2-3) from a session's analysis. Pure; tested in node.
//
// Source: `analysis.observations` (keyed by lap id), every lap compared with the reference. The same point at the
// same corner usually fires on several laps, so observations are grouped by corner + kind. Ranking ("by priority
// then impact_s, preferring a repeated consistency"): the coach's priority (impact x confidence, boosted for habits)
// summed over the laps it fired on and divided by the laps compared, so a habit seen on most laps outranks a big
// one-off; ties go to the point seen on more laps, then to the larger mean time impact. One card per corner: the
// best-ranked point at a corner represents it (the Corners tab shows the rest).
// Incident observations (spin, contact, a slow-down) are never coaching (6.6) and are left out, and so is a point the
// technique graph says does not fit the driver (recap.py rank_points, analysis/coaching.py `applies`; the Corners tab
// shows it greyed with the reason) - though it still makes its corner unclean on its lap, as the habit tracker counts.
// The evidence line leads with the cause the newest occurrence's measured signals named, when that cause is shown to
// tell its fault apart (lib/knowledge/annotation.ts cardCause); a cause only also measured is left to the Corners tab.
//
// The card text is the coach's, verbatim: the newest lap's occurrence (it carries the longest consistency
// history), `text_simple` (D6) for simple-wording profiles when the backend sends it.
//
// Habits, not one-offs (habits spec 6; mirrors motivation/recap.py, the report's "One to work on"): the one to work on
// is a point seen on MIN_REPEAT or more laps that is still there (on one of the last RECENT_LAPS compared laps of its
// corner), else the top big one-off (the radio's rule: analysis/coaching.py is_big_one_off), else none. A point seen
// on MIN_REPEAT or more laps and then on none of its corner's last RECENT_LAPS compared laps - those laps clean at
// the corner, and for a braking-early habit the corner faster on each of them than on any lap it was seen on (later
// braking is praised only when the corner got faster) - is fixed: it went well, and it leaves the Work on list. A
// corner counts as compared on a lap when that lap's comparison was usable and had the corner, not lost to an
// incident there (an incident observation); a lap with an observation at the corner counts too.

import type { ReviewObservation, SessionAnalysis } from "../endpoints/review";
import { cardCause, fitsDriver, joinLine } from "../knowledge/annotation";
import { evidenceLine, finite } from "./words";

export const INCIDENT_KIND = "incident";
/** [H] recap.py MIN_REPEAT: a point on 2 or more laps is a repeat, not a one-off. */
export const MIN_REPEAT = 2;
/** [H] recap.py RECENT_LAPS: the corner's last 3 compared laps say whether a point is still there or fixed. */
export const RECENT_LAPS = 3;
/** [H] analysis/coaching.py BIG_ONE_OFF_S / BIG_ONE_OFF_CONFIDENCE / HABIT_RATIO (the radio's big one-off). */
export const BIG_ONE_OFF_S = 0.3;
export const BIG_ONE_OFF_CONFIDENCE = 0.8;
export const HABIT_RATIO = 0.6;
/** analysis/coaching.py LATER_BRAKING_FIXES: a fixed braking-early habit is later braking, praised only when the corner
 * got faster. tests/unit/test_motivation_recap.py pins these copies to the Python constants. */
const LATER_BRAKING_FIXES: ReadonlySet<string> = new Set(["brake_early"]);

export interface CoachingItem {
  /** `${corner}:${kind}`. */
  key: string;
  /** Learned corner name. */
  corner: string;
  kind: string;
  positive: boolean;
  /** The newest lap's occurrence (text, consistency, evidence). */
  latest: ReviewObservation;
  /** Lap id of `latest` (for Compare). */
  latestLapId: number | null;
  /** Lap numbers it was seen on, ascending. */
  lapNumbers: number[];
  seen: number;
  /** Laps compared with the reference in this session. */
  compared: number;
  /** Mean time impact where seen, seconds (positive = lost; gains are negative). */
  meanImpactS: number | null;
  meanConfidence: number | null;
  meanPriority: number;
  /** Ranking score: summed priority per compared lap. */
  score: number;
  /** Seen on two or more laps. */
  repeated: boolean;
  /** Lap ids it was seen on, ascending. */
  lapIds: number[];
  /** Seen on one of the last RECENT_LAPS compared laps of its corner. */
  recent: boolean;
  /** Corrections only: seen on MIN_REPEAT or more laps, then clean on its corner's last RECENT_LAPS compared laps. */
  fixed: boolean;
}

/** Corner -> lap id -> the corner's time against the reference that lap (s, + = lost; null = unknown), lap ids
 * ascending: the laps the corner was compared on. */
export type CornerLaps = Map<string, Map<number, number | null>>;

function mean(values: readonly number[]): number | null {
  return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
}

/** Every observation of the session with its lap id (incidents excluded). */
export function flatObservations(
  analysis: Pick<SessionAnalysis, "observations"> | null | undefined,
): { lapId: number | null; o: ReviewObservation }[] {
  if (!analysis) return [];
  const out: { lapId: number | null; o: ReviewObservation }[] = [];
  for (const [lapKey, list] of Object.entries(analysis.observations ?? {})) {
    const lapId = Number(lapKey);
    for (const o of list ?? []) {
      if (o.kind === INCIDENT_KIND) continue;
      out.push({ lapId: Number.isFinite(lapId) ? lapId : null, o });
    }
  }
  return out;
}

/**
 * The laps each corner was compared on, with its time (recap.py compared_corner_laps + corner_laps): a usable
 * comparison that had the corner, unless an incident observation says the corner was lost to an incident there (no
 * technique evidence); plus every lap with an observation at the corner, whose `impact_s` is the corner's time.
 */
export function cornerLaps(analysis: Pick<SessionAnalysis, "observations" | "comparisons"> | null | undefined): CornerLaps {
  const incidents = new Set<string>();
  for (const [lapKey, list] of Object.entries(analysis?.observations ?? {})) {
    for (const o of list ?? []) if (o.kind === INCIDENT_KIND) incidents.add(`${Number(lapKey)}|${o.corner}`);
  }
  const out: CornerLaps = new Map();
  const at = (corner: string) => {
    let m = out.get(corner);
    if (!m) out.set(corner, (m = new Map()));
    return m;
  };
  for (const [lapKey, c] of Object.entries(analysis?.comparisons ?? {})) {
    const lapId = Number(lapKey);
    if (!Number.isFinite(lapId) || !c?.compatibility?.ok) continue;
    for (const cd of c.corners ?? []) {
      if (!cd.corner || incidents.has(`${lapId}|${cd.corner}`)) continue;
      at(cd.corner).set(lapId, finite(cd.time_delta_s) ? cd.time_delta_s : null);
    }
  }
  for (const { lapId, o } of flatObservations(analysis)) {
    if (lapId == null || !o.corner) continue;
    const m = at(o.corner);
    if (m.get(lapId) == null) m.set(lapId, finite(o.impact_s) ? o.impact_s : null);
  }
  for (const [corner, m] of out) out.set(corner, new Map([...m].sort((a, b) => a[0] - b[0])));
  return out;
}

function corrective(o: ReviewObservation): boolean {
  return !o.positive && o.kind !== INCIDENT_KIND;
}

/** recap.py _is_fixed: MIN_REPEAT laps or more, then its corner's last RECENT_LAPS compared laps all after it, clean
 * at the corner (no correction of any kind there) and, for a braking-early habit, each faster than any lap it was
 * seen on (every time known). */
function isFixed(
  corner: string,
  kind: string,
  seen: number,
  items: readonly { lapId: number | null; o: ReviewObservation }[],
  laps: CornerLaps,
  byLap: Map<number, ReviewObservation[]>,
): boolean {
  const ids = items.map((e) => e.lapId).filter((i): i is number => i != null);
  if (seen < MIN_REPEAT || !ids.length) return false;
  const lastSeen = Math.max(...ids);
  const times = laps.get(corner) ?? new Map<number, number | null>();
  const last = [...times.keys()].filter((i) => i > lastSeen).slice(-RECENT_LAPS);
  if (last.length < RECENT_LAPS) return false;
  if (last.some((i) => (byLap.get(i) ?? []).some((o) => o.corner === corner && corrective(o)))) return false;
  if (!LATER_BRAKING_FIXES.has(kind)) return true;
  const lost = items.map((e) => e.o.impact_s).filter(finite);
  if (!lost.length) return false;
  const least = Math.min(...lost);
  return last.every((i) => {
    const t = times.get(i);
    return finite(t) && t < least;
  });
}

/** Group observations by corner + kind (positives and corrections apart). */
export function groupObservations(
  analysis: Pick<SessionAnalysis, "observations" | "comparisons"> | null | undefined,
): CoachingItem[] {
  const compared = Object.keys(analysis?.comparisons ?? {}).length;
  const laps = cornerLaps(analysis);
  const byLap = new Map<number, ReviewObservation[]>();
  const groups = new Map<string, { lapId: number | null; o: ReviewObservation }[]>();
  for (const e of flatObservations(analysis)) {
    if (e.lapId != null) {
      const on = byLap.get(e.lapId);
      if (on) on.push(e.o);
      else byLap.set(e.lapId, [e.o]);
    }
    if (!fitsDriver(e.o)) continue; // not this driver's point: no item, but its lap stays unclean at the corner
    const key = `${e.o.positive ? "+" : "-"}${e.o.corner}:${e.o.kind}`;
    const g = groups.get(key);
    if (g) g.push(e);
    else groups.set(key, [e]);
  }
  const items: CoachingItem[] = [];
  for (const list of groups.values()) {
    const sorted = [...list].sort((a, b) => a.o.lap_number - b.o.lap_number);
    const last = sorted[sorted.length - 1];
    if (!last) continue;
    const lapNumbers = [...new Set(sorted.map((e) => e.o.lap_number))];
    const impacts = sorted.map((e) => e.o.impact_s).filter(finite);
    const confidences = sorted.map((e) => e.o.confidence).filter(finite);
    const priorities = sorted.map((e) => e.o.priority).filter(finite);
    const lapIds = [...new Set(sorted.map((e) => e.lapId).filter((i): i is number => i != null))].sort((x, y) => x - y);
    const recentIds = new Set([...(laps.get(last.o.corner)?.keys() ?? [])].slice(-RECENT_LAPS));
    items.push({
      key: `${last.o.corner}:${last.o.kind}`,
      corner: last.o.corner,
      kind: last.o.kind,
      positive: last.o.positive,
      latest: last.o,
      latestLapId: last.lapId,
      lapNumbers,
      seen: lapNumbers.length,
      compared: Math.max(compared, lapNumbers.length),
      meanImpactS: mean(impacts),
      meanConfidence: mean(confidences),
      meanPriority: mean(priorities) ?? 0,
      score: priorities.reduce((a, b) => a + b, 0) / Math.max(compared, lapNumbers.length, 1),
      repeated: lapNumbers.length >= 2,
      lapIds,
      recent: lapIds.some((i) => recentIds.has(i)),
      fixed: !last.o.positive && isFixed(last.o.corner, last.o.kind, lapNumbers.length, sorted, laps, byLap),
    });
  }
  return items;
}

/** Priority per compared lap, then laps seen, then mean impact (absolute), then corner name (stable). */
export function rankItems(items: readonly CoachingItem[]): CoachingItem[] {
  return [...items].sort(
    (a, b) =>
      b.score - a.score ||
      b.seen - a.seen ||
      Math.abs(b.meanImpactS ?? 0) - Math.abs(a.meanImpactS ?? 0) ||
      a.corner.localeCompare(b.corner) ||
      a.kind.localeCompare(b.kind),
  );
}

function onePerCorner(items: readonly CoachingItem[]): CoachingItem[] {
  const seen = new Set<string>();
  const out: CoachingItem[] = [];
  for (const i of items) {
    if (seen.has(i.corner)) continue;
    seen.add(i.corner);
    out.push(i);
  }
  return out;
}

/** "Work on": corrections, ranked, one per corner; a fixed point is not one (it went well: `fixedItems`), so another
 * point at its corner may stand for the corner. `exclude` (lane motivation): the `corner:kind` key a card above
 * already shows ("Today's 3 things"), left out of the list; its corner is not refilled by another point. */
export function workOnItems(
  analysis: Pick<SessionAnalysis, "observations" | "comparisons"> | null | undefined,
  exclude?: string | null,
): CoachingItem[] {
  const items = onePerCorner(rankItems(groupObservations(analysis).filter((i) => !i.positive && !i.fixed)));
  return exclude ? items.filter((i) => i.key !== exclude) : items;
}

/** analysis/coaching.py is_big_one_off on an item's occurrence: a correction that is no habit by the coach's own
 * consistency, cost BIG_ONE_OFF_S or more, measured with BIG_ONE_OFF_CONFIDENCE or more. */
export function isBigOneOff(o: ReviewObservation): boolean {
  const habit = finite(o.consistency_ratio) && o.consistency_ratio >= HABIT_RATIO;
  const big = finite(o.impact_s) && o.impact_s >= BIG_ONE_OFF_S;
  return corrective(o) && !habit && big && finite(o.confidence) && o.confidence >= BIG_ONE_OFF_CONFIDENCE;
}

/** The session's one thing to work on (recap.py work_on, before the driver's limits): the top point seen on
 * MIN_REPEAT or more laps that is still there, else the top big one-off, else null (a small one-off, or a corner
 * already fixed, is never the session's lesson). */
export function oneToWorkOn(analysis: Pick<SessionAnalysis, "observations" | "comparisons"> | null | undefined): CoachingItem | null {
  const ranked = rankItems(groupObservations(analysis).filter((i) => !i.positive));
  return (
    ranked.find((i) => i.seen >= MIN_REPEAT && i.recent) ??
    ranked.find((i) => i.seen < MIN_REPEAT && isBigOneOff(i.latest)) ??
    null
  );
}

/** Corrections that are fixed (recap.py's "sorted" Went well), ranked. */
export function fixedItems(analysis: Pick<SessionAnalysis, "observations" | "comparisons"> | null | undefined): CoachingItem[] {
  return rankItems(groupObservations(analysis).filter((i) => !i.positive && i.fixed));
}

/** "Went well": positive observations, ranked, one per corner, at most `max` (3). */
export function wentWellItems(
  analysis: Pick<SessionAnalysis, "observations" | "comparisons"> | null | undefined,
  max = 3,
): CoachingItem[] {
  return onePerCorner(rankItems(groupObservations(analysis).filter((i) => i.positive))).slice(0, max);
}

/** The coach's text for the card: `text_simple` (D6) for simple wording when sent, else `text`. Verbatim. */
export function itemText(item: Pick<CoachingItem, "latest">, simple: boolean): string {
  const o = item.latest;
  return simple && o.text_simple ? o.text_simple : o.text;
}

/**
 * The card's evidence line from the shown observation's own fields (spec 9.6: `consistency`, `impact_s`,
 * `confidence`), so its amount matches the coach's text above it: "Seen on 3 of your last 5 laps · about 0.11 s a
 * lap · confidence high". Without the coach's consistency it says how many of this session's laps showed it. When the
 * technique graph named a cause on that lap that tells its fault apart, its screen line leads ("Braking ended sooner,
 * longer roll after · Seen on ...").
 */
export function itemEvidence(item: CoachingItem): string {
  const line = evidenceLine({
    consistency: item.latest.consistency,
    seen: item.seen,
    compared: item.compared,
    impactS: item.latest.impact_s,
    confidence: item.latest.confidence,
  });
  return joinLine(cardCause(item.latest), line) ?? line;
}

/** Counts for the "Last session" card: corrections and positives (grouped, one per corner). */
export function coachingCounts(analysis: Pick<SessionAnalysis, "observations" | "comparisons"> | null | undefined): {
  workOn: number;
  wentWell: number;
} {
  return { workOn: workOnItems(analysis).length, wentWell: wentWellItems(analysis, Infinity).length };
}
