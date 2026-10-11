// In-app links from Review (spec 2.3): always name the sub-page, keep queries in the hash. Pure.

import { pathOf, sessionPath, withQuery, type SessionTab } from "../route-parse";

export { sessionPath };

/** Compare for a session: `/review/sessions/<id>/compare?ref=<lap_id>&lap=<lap_id>&at=<metres>` (unknown parts
 * are left out; Compare picks its own defaults). */
export function comparePath(
  sessionId: string,
  q: { ref?: number | null; lap?: number | null; at?: number | null } = {},
): string {
  return withQuery(sessionPath(sessionId, "compare"), {
    ref: q.ref ?? undefined,
    lap: q.lap ?? undefined,
    at: q.at != null && Number.isFinite(q.at) ? Math.round(q.at) : undefined,
  });
}

/** The session's Ask tab, pre-filled: `/review/sessions/<id>/ask?q=<question>`. */
export function askPath(sessionId: string, question?: string | null): string {
  return withQuery(sessionPath(sessionId, "ask"), { q: question || undefined });
}

/** Progress for a driver at a track (+ car): `/review/progress?driver=&track=&car=` (`car=any` = every car). */
export function progressPath(q: { driver?: number | null; track?: string | null; car?: string | null }): string {
  return withQuery(pathOf("review", "progress"), {
    driver: q.driver ?? undefined,
    track: q.track || undefined,
    car: q.car || undefined,
  });
}

/** Coaching plan for a driver at a track (+ car): `/review/coaching?driver=&track=&car=` (`car=any` = every car). */
export function coachingPath(q: { driver?: number | null; track?: string | null; car?: string | null }): string {
  return withQuery(pathOf("review", "coaching"), {
    driver: q.driver ?? undefined,
    track: q.track || undefined,
    car: q.car || undefined,
  });
}

/** A session tab path. */
export function tabPath(sessionId: string, tab: SessionTab): string {
  return sessionPath(sessionId, tab);
}

/** The question "Ask the engineer" pre-fills for a Work on card (spec 6.3 #2). With the official label the engineer
 * finds the corner itself ("Why am I losing time at Stowe (T15)?": ai/engineer.py reads "T15" and resolves the
 * official label to its learned corner); a corner without a name is asked by its label alone. */
export function workOnQuestion(spoken: string, label?: string | null): string {
  const where = label && label !== spoken ? `${spoken} (${label})` : spoken;
  return `Why am I losing time at ${where}?`;
}

/** Laps with another reference lap for this page (Laps "Set as reference"): `/review/sessions/<id>/laps?ref=`. */
export function lapsPath(sessionId: string, ref?: number | null): string {
  return withQuery(sessionPath(sessionId, "laps"), { ref: ref ?? undefined });
}

/** Engineer for any session: `/review/ask?session=<id>&q=<question>`. */
export function engineerPath(sessionId?: string | null, question?: string | null): string {
  return withQuery(pathOf("review", "ask"), { session: sessionId || undefined, q: question || undefined });
}
