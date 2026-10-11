// Badges and streaks on Review › Progress (lane motivation, spec 4.7 and 9 BadgesCard): four streak tiles (weeks in
// a row, sessions this week, best clean run, PB streak) and the badge grid, newest first. The server works them out
// from stored driving when asked (nothing extra is stored); real driving only. Pure; tested in plain node.

import type { Badge, BadgesResponse, Streaks } from "../endpoints/motivation";
import { count, shortDay } from "./format";

export const BADGES_SHOWN = 6;

export interface StreakTile {
  key: "weeks" | "week_sessions" | "clean_run" | "pb_streak";
  title: string;
  /** The number, or null when unknown ("-"). */
  value: number | null;
  sub: string;
}

/** The four streak tiles. Unknown parts read "-"; a PB streak needs two sessions at the same track and car. */
export function streakTiles(s: Streaks | null | undefined): StreakTile[] {
  const w = s?.weekly;
  const c = s?.clean_laps;
  const pb = s?.pb?.[0];
  return [
    {
      key: "weeks",
      title: "Weeks in a row",
      value: w ? w.current_weeks : null,
      sub: w ? (w.best_weeks > w.current_weeks ? `best ${count(w.best_weeks, "week")}` : "weeks with at least one session") : "-",
    },
    {
      key: "week_sessions",
      title: "Sessions this week",
      value: w ? w.this_week_sessions : null,
      sub: "from Monday",
    },
    {
      key: "clean_run",
      title: "Best clean run",
      value: c ? c.best : null,
      sub: c ? (c.last_session != null ? `${count(c.last_session, "lap")} in the last session` : "clean laps in a row") : "-",
    },
    {
      key: "pb_streak",
      title: "New bests in a row",
      value: pb ? pb.current_sessions : s ? 0 : null,
      sub: pb ? `${pb.scope_text}${pb.best_sessions > pb.current_sessions ? ` · best ${pb.best_sessions}` : ""}` : "sessions with a new personal best",
    },
  ];
}

export interface BadgeView {
  key: string;
  title: string;
  detail: string | null;
  day: string;
  sessionId: string | null;
  synthetic: boolean;
}

/** Badges newest first, in the reader's wording. */
export function badgeViews(r: BadgesResponse | null | undefined, simpleOverride?: boolean): BadgeView[] {
  const simple = simpleOverride ?? !!r?.simple;
  return [...(r?.badges ?? [])]
    .sort((a: Badge, b: Badge) => b.earned_unix - a.earned_unix || a.key.localeCompare(b.key))
    .map((b) => ({
      key: b.key,
      title: simple && b.title_simple ? b.title_simple : b.title,
      detail: b.detail,
      day: shortDay(b.earned_unix),
      sessionId: b.session_id,
      synthetic: b.synthetic,
    }));
}
