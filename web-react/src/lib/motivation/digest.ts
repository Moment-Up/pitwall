// The weekly digest on Review › Progress (lane motivation, spec 4.9 and 9 WeekCard): one Monday-to-Sunday week of a
// driver's real driving. The server counts and words it (headline, sessions, best improvements, goal changes,
// badges, the markdown to copy and the printable page); this module lays it out. Pure; tested in plain node.

import { changeWords } from "../bests";
import type { DigestImprovement, DigestSession, WeeklyDigest } from "../endpoints/motivation";
import { lapTime } from "../format";
import { count, drivingTime, percent, shortDay, weekLabel } from "./format";
import { goalTitle } from "./goals";

export const WEEK_SESSIONS_SHOWN = 7;
export const WEEK_IMPROVEMENTS_SHOWN = 3;
/** Badges listed on the card; the rest are counted (the Streaks and badges card has them all). */
export const WEEK_BADGES_SHOWN = 6;

export interface WeekSessionRow {
  id: string;
  day: string;
  /** "Austria · Race". */
  title: string;
  car: string | null;
  /** "9 of 10 clean". */
  laps: string;
  bestMs: number | null;
  pb: boolean;
  synthetic: boolean;
}

export interface WeekImprovementRow {
  key: string;
  scopeText: string;
  /** "1:10.549 · 1.2 s faster than 1:11.745", or "First clean laps here: 1:36.360". */
  text: string;
  bestMs: number;
  newTrack: boolean;
  sessionId: string;
}

export interface WeekGoalRow {
  id: number;
  title: string;
  /** Reached: the achievement sentence. Moving: the progress sentence. */
  text: string;
  reached: boolean;
  /** 0..100 at the start of the week and at its end (or now); null when unknown. */
  from: number | null;
  to: number | null;
}

export interface WeekView {
  weekStart: string;
  label: string;
  isCurrent: boolean;
  headline: string;
  /** "17 sessions · 60 laps, 47 clean · 1 h 12 min of laps · 6 tracks"; null in an empty week. */
  totals: string | null;
  /** "Week before: 3 sessions, 12 laps (9 clean)"; null when it had none. */
  previous: string | null;
  sessions: WeekSessionRow[];
  moreSessions: number;
  improvements: WeekImprovementRow[];
  goals: WeekGoalRow[];
  badges: string[];
  empty: boolean;
  markdown: string;
  simple: boolean;
}

function sessionTitle(s: DigestSession): string {
  const type = s.session_type ? s.session_type.replace(/_/g, " ") : null;
  const t = type ? type[0]!.toUpperCase() + type.slice(1).toLowerCase() : null;
  return [s.track_name || "Unknown track", t].filter(Boolean).join(" · ");
}

function improvementText(i: DigestImprovement): string {
  if (i.new_track || i.before_ms == null) return `First clean laps here: ${lapTime(i.best_ms)}`;
  const c = changeWords(i.gain_ms != null ? -i.gain_ms : i.best_ms - i.before_ms);
  return `${lapTime(i.best_ms)} · ${c && c.word !== "level" ? `${c.text} than` : "level with"} ${lapTime(i.before_ms)}`;
}

export function weekView(d: WeeklyDigest, simpleOverride?: boolean): WeekView {
  const simple = simpleOverride ?? d.simple;
  const t = d.totals;
  const empty = t.sessions === 0;
  const totals = empty
    ? null
    : [
        count(t.sessions, "session"),
        `${count(t.laps, "lap")}, ${t.clean_laps} clean`,
        t.lap_time_s > 0 ? `${drivingTime(t.lap_time_s)} of laps` : null,
        count(t.tracks, "track"),
      ]
        .filter(Boolean)
        .join(" · ");
  const p = d.previous_week;
  const previous = p.sessions > 0 ? `Week before: ${count(p.sessions, "session")}, ${count(p.laps, "lap")} (${p.clean_laps} clean)` : null;
  const sessions = [...d.sessions]
    .sort((a, b) => a.started_unix - b.started_unix)
    .map<WeekSessionRow>((s) => ({
      id: s.session_id,
      day: shortDay(s.started_unix),
      title: sessionTitle(s),
      car: s.car_name,
      laps: `${s.clean_laps} of ${count(s.laps, "lap")} clean`,
      bestMs: s.best_clean_ms,
      pb: s.pb,
      synthetic: s.synthetic,
    }));
  const gains = d.improvements.filter((i) => !i.new_track && i.gain_ms != null && i.gain_ms > 0);
  const fresh = d.improvements.filter((i) => i.new_track);
  const improvements = [...gains, ...fresh].slice(0, WEEK_IMPROVEMENTS_SHOWN).map<WeekImprovementRow>((i) => ({
    key: `${i.session_id}:${i.lap_id}`,
    scopeText: i.scope_text,
    text: improvementText(i),
    bestMs: i.best_ms,
    newTrack: i.new_track,
    sessionId: i.session_id,
  }));
  const goals: WeekGoalRow[] = [
    ...d.goals.achieved.map<WeekGoalRow>((g) => ({
      id: g.id,
      title: goalTitle(g, simple),
      text: (g.achieved ? (simple && g.achieved.text_simple ? g.achieved.text_simple : g.achieved.text) : "") || "Reached",
      reached: true,
      from: null,
      to: 100,
    })),
    ...d.goals.active.map<WeekGoalRow>((a) => ({
      id: a.goal.id,
      title: goalTitle(a.goal, simple),
      text: (simple && a.goal.progress.text_simple ? a.goal.progress.text_simple : a.goal.progress.text) || "-",
      reached: false,
      from: percent(a.from_fraction),
      to: percent(a.to_fraction),
    })),
  ];
  return {
    weekStart: d.week_start,
    label: weekLabel(d.week_start),
    isCurrent: d.is_current_week,
    headline: (simple && d.headline_simple ? d.headline_simple : d.headline) || (empty ? "No driving this week." : "-"),
    totals,
    previous,
    sessions: sessions.slice(0, WEEK_SESSIONS_SHOWN),
    moreSessions: Math.max(0, sessions.length - WEEK_SESSIONS_SHOWN),
    improvements,
    goals,
    badges: [...d.badges].sort((a, b) => b.earned_unix - a.earned_unix).map((b) => (simple && b.title_simple ? b.title_simple : b.title)),
    empty,
    markdown: d.markdown,
    simple,
  };
}

/** A goal's change over the week in words: "from 20% to 65% of the way", "65% of the way", or null when unknown. */
export function fractionChange(from: number | null, to: number | null): string | null {
  if (to == null) return null;
  if (from == null || Math.round(from) === Math.round(to)) return `${Math.round(to)}% of the way`;
  return `from ${Math.round(from)}% to ${Math.round(to)}% of the way`;
}
