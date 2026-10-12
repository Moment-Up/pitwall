// The weekly digest on Review › Goals (lane motivation, spec 4.9 and 9 WeekCard): one Monday-to-Sunday week of a
// driver's real driving. The server counts and words it (headline, sessions, improvements, new tracks, goal changes,
// badges, the markdown to copy and the printable page); this module lays it out. Pure; tested in plain node.
//
// Integration plan 5.7, 5.8: counts carry their rule ("3 sessions with a timed lap"); the sessions are listed newest
// first; improvements and new tracks are two groups ("Improvements", "New tracks", the printable page's titles); a new
// track is the session that first set a clean lap there, in its own car, with how much that car gained there by the
// end of the week ("New this week: 1:11.745 → 1:10.549 (1.2 s faster)"). The badges of the week stay in the data (the
// printable page and the markdown list them); the card leaves them to the badges card, the one full list.

import { changeWords } from "../bests";
import type { DigestImprovement, DigestSession, WeeklyDigest } from "../endpoints/motivation";
import { lapTime } from "../format";
import { trackLabel } from "../review/words";
import { carText } from "../carclass";
import { count, drivingTime, percent, shortDay, weekLabel } from "./format";
import { goalTitle } from "./goals";

export const WEEK_SESSIONS_SHOWN = 7;
/** Per group (Improvements, New tracks): the server's own limit too. */
export const WEEK_IMPROVEMENTS_SHOWN = 3;

/** The counting rule's words (plan 5.7; motivation/digest.py `sessions_words`): "1 session with a timed lap". */
export function sessionsWithTimedLap(n: number): string {
  return `${count(n, "session")} with a timed lap`;
}

/** An improvement as a newer server sends it: its sentence (`text`) and, for a new track, the first clean lap there
 * and that car's gain by the end of the week. Older servers send neither. */
type ImprovementWire = DigestImprovement & {
  text?: string | null;
  first_ms?: number | null;
  week_gain_ms?: number | null;
};

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
  /** The server's sentence when it sends one ("1:10.549, 1.196 s faster than before", "New this week: 1:11.745 →
   * 1:10.549 (1.2 s faster)"), else "1:10.549 · 1.2 s faster than 1:11.745" or "First clean laps here: 1:36.360". */
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
  /** What the headline does not say already, in the printable page's words: "47 clean laps · 1 h 12 min driving ·
   * 6 tracks"; null in an empty week. */
  totals: string | null;
  /** "Week before: 3 sessions with a timed lap, 12 laps, 9 clean"; null when it had none. */
  previous: string | null;
  /** Every session of the week, newest first (the card shows WEEK_SESSIONS_SHOWN, then "Show all"). */
  sessions: WeekSessionRow[];
  moreSessions: number;
  /** Faster than before the week, biggest gain first ("Improvements"). */
  improvements: WeekImprovementRow[];
  /** A first clean lap this week at a track never driven before ("New tracks"), in the order first driven. */
  newTracks: WeekImprovementRow[];
  goals: WeekGoalRow[];
  /** The week's badges, newest first (the printable page lists them; the card does not). */
  badges: string[];
  empty: boolean;
  markdown: string;
  simple: boolean;
}

function sessionTitle(s: DigestSession): string {
  const type = s.session_type ? s.session_type.replace(/_/g, " ") : null;
  const t = type && type !== "unknown" ? type[0]!.toUpperCase() + type.slice(1).toLowerCase() : null;
  return [trackLabel(s), t].filter(Boolean).join(" · ");
}

function improvementText(i: ImprovementWire): string {
  if (i.text) return i.text;
  if (i.new_track || i.before_ms == null) {
    if (i.first_ms == null) return `First clean laps here: ${lapTime(i.best_ms)}`;
    const gain = i.week_gain_ms ?? 0;
    if (gain <= 0) return `New this week: ${lapTime(i.first_ms)}`;
    const c = changeWords(-gain);
    return `New this week: ${lapTime(i.first_ms)} → ${lapTime(i.best_ms)}${c && c.word !== "level" ? ` (${c.text})` : ""}`;
  }
  const c = changeWords(i.gain_ms != null ? -i.gain_ms : i.best_ms - i.before_ms);
  return `${lapTime(i.best_ms)} · ${c && c.word !== "level" ? `${c.text} than` : "level with"} ${lapTime(i.before_ms)}`;
}

function improvementRow(i: ImprovementWire): WeekImprovementRow {
  return {
    key: `${i.session_id}:${i.lap_id}`,
    scopeText: i.scope_text,
    text: improvementText(i),
    bestMs: i.best_ms,
    newTrack: i.new_track,
    sessionId: i.session_id,
  };
}

export function weekView(d: WeeklyDigest, simpleOverride?: boolean): WeekView {
  const simple = simpleOverride ?? d.simple;
  const t = d.totals;
  const empty = t.sessions === 0;
  // the headline says the sessions and laps already (motivation/digest.py totals_line: the same words)
  const totals = empty
    ? null
    : [count(t.clean_laps, "clean lap"), t.lap_time_s > 0 ? `${drivingTime(t.lap_time_s)} driving` : null, count(t.tracks, "track")]
        .filter(Boolean)
        .join(" · ");
  const p = d.previous_week;
  const previous =
    p.sessions > 0 ? `Week before: ${sessionsWithTimedLap(p.sessions)}, ${count(p.laps, "lap")}, ${p.clean_laps} clean` : null;
  const sessions = [...d.sessions]
    .sort((a, b) => b.started_unix - a.started_unix)
    .map<WeekSessionRow>((s) => ({
      id: s.session_id,
      day: shortDay(s.started_unix),
      title: sessionTitle(s),
      car: carText(s), // the server's car_label when it sends one (F2 support), else the stored name
      laps: `${s.clean_laps} of ${count(s.laps, "lap")} clean`,
      bestMs: s.best_clean_ms,
      pb: s.pb,
      synthetic: s.synthetic,
    }));
  const items = d.improvements as readonly ImprovementWire[];
  const improvements = items
    .filter((i) => !i.new_track && i.gain_ms != null && i.gain_ms > 0)
    .slice(0, WEEK_IMPROVEMENTS_SHOWN)
    .map(improvementRow);
  const newTracks = items.filter((i) => i.new_track).slice(0, WEEK_IMPROVEMENTS_SHOWN).map(improvementRow);
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
    sessions,
    moreSessions: Math.max(0, sessions.length - WEEK_SESSIONS_SHOWN),
    improvements,
    newTracks,
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
