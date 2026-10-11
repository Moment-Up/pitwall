// "Work on" and "Went well" (spec 6.3 #2-3) from a session's analysis. Pure; tested in node.
//
// Source: `analysis.observations` (keyed by lap id), every lap compared with the reference. The same point at the
// same corner usually fires on several laps, so observations are grouped by corner + kind. Ranking ("by priority
// then impact_s, preferring a repeated consistency"): the coach's priority (impact x confidence, boosted for habits)
// summed over the laps it fired on and divided by the laps compared, so a habit seen on most laps outranks a big
// one-off; ties go to the point seen on more laps, then to the larger mean time impact. One card per corner: the
// best-ranked point at a corner represents it (the Corners tab shows the rest).
// Incident observations (spin, contact, a slow-down) are never coaching (6.6) and are left out.
//
// The card text is the coach's, verbatim: the newest lap's occurrence (it carries the longest consistency
// history), `text_simple` (D6) for simple-wording profiles when the backend sends it.

import type { ReviewObservation, SessionAnalysis } from "../endpoints/review";
import { evidenceLine, finite } from "./words";

export const INCIDENT_KIND = "incident";

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
}

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

/** Group observations by corner + kind (positives and corrections apart). */
export function groupObservations(
  analysis: Pick<SessionAnalysis, "observations" | "comparisons"> | null | undefined,
): CoachingItem[] {
  const compared = Object.keys(analysis?.comparisons ?? {}).length;
  const groups = new Map<string, { lapId: number | null; o: ReviewObservation }[]>();
  for (const e of flatObservations(analysis)) {
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

/** "Work on": corrections, ranked, one per corner. `exclude` (lane motivation): the `corner:kind` key a card above
 * already shows ("Today's 3 things"), left out of the list; its corner is not refilled by another point. */
export function workOnItems(
  analysis: Pick<SessionAnalysis, "observations" | "comparisons"> | null | undefined,
  exclude?: string | null,
): CoachingItem[] {
  const items = onePerCorner(rankItems(groupObservations(analysis).filter((i) => !i.positive)));
  return exclude ? items.filter((i) => i.key !== exclude) : items;
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
 * lap · confidence high". Without the coach's consistency it says how many of this session's laps showed it.
 */
export function itemEvidence(item: CoachingItem): string {
  return evidenceLine({
    consistency: item.latest.consistency,
    seen: item.seen,
    compared: item.compared,
    impactS: item.latest.impact_s,
    confidence: item.latest.confidence,
  });
}

/** Counts for the "Last session" card: corrections and positives (grouped, one per corner). */
export function coachingCounts(analysis: Pick<SessionAnalysis, "observations" | "comparisons"> | null | undefined): {
  workOn: number;
  wentWell: number;
} {
  return { workOn: workOnItems(analysis).length, wentWell: wentWellItems(analysis, Infinity).length };
}
