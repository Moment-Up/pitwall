// Review › Coaching plan (spec 6.8): per driver and track + car, this session's focus (led by the corner the session's
// "One to work on" names, so Coaching and the Summary agree; integration plan 5.1; with a trend once D5 sends corner
// means per session), what repeats lap after lap (observations carrying the coach's consistency string), corners
// recently fixed (D5), and what the radio calls next run (the live cue plan, only when this driver is in the seat at
// this track). Pure; tested in node.
//
// Every coaching text is the coach's own (analysis/coaching.py), verbatim; this module only picks, orders and adds
// neutral words ("0.40 s lost a lap, against 0.79 s before").

import { focusReasonOf } from "../drive/corner";
import type { CueSnapshot } from "../drive/types";
import type { SessionAnalysis } from "../endpoints/review";
import { groupObservations, rankItems, workOnItems, type CoachingItem } from "./coaching";
import { cornerIdentity } from "./corners";
import {
  comparedPoints,
  cornerTextOf,
  DEFAULT_THRESHOLD_S,
  lostWords,
  trendOf,
  type CornerText,
  type SessionPoint,
  type TrendWord,
} from "./progress";
import type { ProgressCornerText } from "../endpoints/review";
import { consistencyWords, finite, plural } from "./words";

/** Corners shown under "This session's focus". */
export const WORKING_ON_MAX = 3;
/** Sessions a trend looks back over (the plan session and up to 4 before it: "the last 3-5 sessions"). */
export const TREND_WINDOW = 5;

/**
 * The session the plan is read from: with D5, the newest session compared with the reference (it has corner means);
 * else the newest session with laps. Null when there is none.
 */
export function planSession(points: readonly SessionPoint[]): SessionPoint | null {
  const compared = comparedPoints(points);
  return compared[compared.length - 1] ?? points[points.length - 1] ?? null;
}

export interface CornerTrendView {
  trend: TrendWord;
  /** "Session average here: 0.40 s lost a lap, against 0.79 s lost the session before" (neutral words). */
  words: string;
  /** Sessions the trend covers (the plan session included). */
  sessions: number;
}

/**
 * A corner's trend over the last sessions (D5): the plan session's mean against the mean of up to 4 compared sessions
 * before it. Null without D5, without earlier sessions, or when the plan session did not measure the corner.
 */
export function cornerTrendAt(
  points: readonly SessionPoint[],
  planSessionId: string,
  corner: string,
  thresholdS = DEFAULT_THRESHOLD_S,
): CornerTrendView | null {
  const compared = comparedPoints(points);
  const at = compared.findIndex((p) => p.sessionId === planSessionId);
  if (at < 0) return null;
  const latest = compared[at]!.corners?.[corner];
  if (!finite(latest)) return null;
  const before = compared
    .slice(Math.max(0, at - (TREND_WINDOW - 1)), at)
    .map((p) => p.corners?.[corner])
    .filter(finite);
  if (!before.length) return null;
  const mean = before.reduce((a, b) => a + b, 0) / before.length;
  const n = before.length + 1;
  return {
    trend: trendOf(latest - mean, thresholdS),
    words: `Session average here: ${lostWords(latest)} a lap, against ${lostWords(mean)} ${before.length === 1 ? "the session before" : `on average over the ${before.length} sessions before`}`,
    sessions: n,
  };
}

export interface WorkingOn {
  item: CoachingItem;
  /** Official label and name from the plan session's track model. */
  label: string;
  name: string | null;
  spoken: string;
  apexM: number | null;
  trend: CornerTrendView | null;
}

/**
 * "This session's focus" (spec 6.8, was "Working on now"): the plan session's corrections, ranked by the coach (as the
 * Summary's Work on), one per corner, at most 3; each with its trend over the last sessions when D5 is there.
 * `focusKey` is the observation the session's recap names as its "One to work on" (`recap.work_on`, `corner:kind`):
 * that one leads, so Coaching and the Summary show the same corner (integration plan 5.1, acceptance D3). Unknown
 * (no recap, an older server, a recap item that is not an observation): the coach's own order.
 */
export function workingOnNow(
  analysis: Pick<SessionAnalysis, "observations" | "comparisons" | "track_model"> | null | undefined,
  points: readonly SessionPoint[],
  planSessionId: string | null,
  thresholdS = DEFAULT_THRESHOLD_S,
  max = WORKING_ON_MAX,
  focusKey: string | null = null,
): WorkingOn[] {
  return focusFirst(analysis, focusKey)
    .slice(0, max)
    .map((item) => {
      const id = cornerIdentity(analysis?.track_model, item.corner, item.latest.corner_label);
      return {
        item,
        label: id.label,
        name: id.name,
        spoken: id.spoken,
        apexM: id.apexM,
        trend: planSessionId ? cornerTrendAt(points, planSessionId, item.corner, thresholdS) : null,
      };
    });
}

/** The Work on items with the recap's own item first. It may be a kind the one-per-corner list left out at its corner
 * (another kind ranked higher there): it then takes that corner's place. */
function focusFirst(
  analysis: Pick<SessionAnalysis, "observations" | "comparisons"> | null | undefined,
  focusKey: string | null,
): CoachingItem[] {
  const items = workOnItems(analysis);
  if (!focusKey) return items;
  const hit =
    items.find((i) => i.key === focusKey) ??
    groupObservations(analysis).find((i) => !i.positive && i.key === focusKey) ??
    null;
  if (!hit) return items;
  return [hit, ...items.filter((i) => i.key !== hit.key && i.corner !== hit.corner)];
}

export interface Habit {
  item: CoachingItem;
  label: string;
  name: string | null;
  /** The coach's consistency string as the evidence line says it ("4 of your last 5 laps"). */
  consistency: string;
}

/** Habits (spec 6.8): corrections that carry the coach's consistency string, ranked, one per corner and kind. */
export function habits(
  analysis: Pick<SessionAnalysis, "observations" | "comparisons" | "track_model"> | null | undefined,
  max = 6,
): Habit[] {
  return rankItems(groupObservations(analysis).filter((i) => !i.positive && !!i.latest.consistency))
    .slice(0, max)
    .map((item) => {
      const id = cornerIdentity(analysis?.track_model, item.corner, item.latest.corner_label);
      return { item, label: id.label, name: id.name, consistency: consistencyWords(item.latest.consistency) ?? "" };
    });
}

export interface FixedCorner extends CornerText {
  key: string;
  /** Compared sessions in a row (the newest included) under the threshold. */
  sessions: number;
  /** The last loss at or above the threshold, seconds. */
  wasS: number;
  nowS: number;
  /** "Average loss below 0.02 s for 3 sessions (it was 0.21 s)". */
  words: string;
}

/** A corner counts as fixed after this many compared sessions in a row under the threshold. */
export const FIXED_SESSIONS = 2;

/**
 * Recently fixed (spec 6.8, D5): corners whose average loss fell below the coaching threshold and stayed there for at
 * least 2 compared sessions in a row (the newest included), after a session at or above it within the last 6.
 */
export function recentlyFixed(
  points: readonly SessionPoint[],
  text: ProgressCornerText | null | undefined,
  game: string,
  trackId: string,
  thresholdS = DEFAULT_THRESHOLD_S,
): FixedCorner[] {
  const compared = comparedPoints(points).slice(-6);
  if (compared.length < FIXED_SESSIONS + 1) return [];
  const keys = new Set(compared.flatMap((p) => Object.keys(p.corners ?? {})));
  const out: FixedCorner[] = [];
  for (const key of keys) {
    const vals = compared.map((p) => p.corners?.[key]);
    let run = 0;
    for (let i = vals.length - 1; i >= 0; i -= 1) {
      const v = vals[i];
      if (!finite(v) || v >= thresholdS) break;
      run += 1;
    }
    if (run < FIXED_SESSIONS) continue;
    const was = vals.slice(0, vals.length - run).reverse().find(finite);
    if (was == null || was < thresholdS) continue;
    const nowS = vals[vals.length - 1] as number;
    out.push({
      key,
      ...cornerTextOf(text, game, trackId, key),
      sessions: run,
      wasS: was,
      nowS,
      words: `Average loss below ${thresholdS.toFixed(2)} s for ${plural(run, "session")} (it was ${was.toFixed(2)} s a lap)`,
    });
  }
  return out.sort((a, b) => b.wasS - a.wasS || a.key.localeCompare(b.key));
}

// ------------------------------------------------------------------------------------------- the radio's focus

export interface LiveFocusInput {
  seatedId: number | null;
  /** The dashboard's live socket is down: nothing live is known. */
  offline?: boolean;
  live: { game: string; track_id: string | null } | null;
  cues: Pick<CueSnapshot, "mode" | "reason" | "focus" | "cues"> | null | undefined;
  corners: readonly { name: string; label?: string | null; display_name?: string | null }[];
}

export type RadioFocus =
  | { state: "focus"; items: { key: string; label: string; name: string | null; reason: string | null }[] }
  | { state: "none"; reason: string };

/**
 * "Radio calls next run" (spec 6.8, was "The radio will focus on"): the live cue plan's focus corners with their
 * reasons, only when this driver is in the seat and the live session is at this track; otherwise why not, in words.
 */
export function radioFocus(
  input: LiveFocusInput,
  viewed: { id: number; name: string },
  scope: { game: string; trackId: string; trackLabel: string },
): RadioFocus {
  if (input.offline) return { state: "none", reason: "The live connection is down, so the radio's plan is not known." };
  if (input.seatedId !== viewed.id) {
    return { state: "none", reason: `${viewed.name} is not in the seat: the radio plans its focus for whoever is.` };
  }
  if (!input.live || input.live.game !== scope.game || input.live.track_id !== scope.trackId) {
    return { state: "none", reason: `No live session at ${scope.trackLabel}: the radio picks its focus once ${viewed.name} drives here.` };
  }
  const cues = input.cues;
  if (!cues) return { state: "none", reason: "The live data carries no braking-call plan." };
  if (cues.mode === "off") return { state: "none", reason: "Braking calls are off (Drive › Radio)." };
  if (!cues.focus?.length) {
    return {
      state: "none",
      reason: cues.reason ? `No plan yet: ${cues.reason}.` : "The radio has no focus corners for this lap.",
    };
  }
  return {
    state: "focus",
    items: cues.focus.map((key) => {
      const c = input.corners.find((x) => x.name === key);
      return {
        key,
        label: c?.label?.trim() || key,
        name: c?.display_name?.trim() || null,
        reason: focusReasonOf(cues as CueSnapshot, key),
      };
    }),
  };
}

/** The live snapshot fields the radio focus reads. */
export interface LiveFocusSnap {
  session?: { game: string; track_id: string | null } | null;
  cues?: Pick<CueSnapshot, "mode" | "reason" | "focus" | "cues"> | null;
  track_model?: { corners: readonly { name: string; label?: string | null; display_name?: string | null }[] } | null;
}

/**
 * A small string of what the radio focus needs from a live snapshot (session, cue mode, reason, focus corners with
 * their plan entries and identities). Snapshots arrive 20 times a second; a page selects this string, so it only
 * re-renders when the plan itself changes.
 */
export function liveFocusKey(snap: LiveFocusSnap | null | undefined, connected: boolean): string {
  if (!connected) return JSON.stringify({ offline: true });
  const focus = snap?.cues?.focus ?? [];
  return JSON.stringify({
    live: snap?.session ? { game: snap.session.game, track_id: snap.session.track_id } : null,
    cues: snap?.cues
      ? {
          mode: snap.cues.mode,
          reason: snap.cues.reason ?? null,
          focus,
          cues: (snap.cues.cues ?? []).filter((c) => c.focus && focus.includes(c.corner)),
        }
      : null,
    corners: (snap?.track_model?.corners ?? [])
      .filter((c) => focus.includes(c.name))
      .map((c) => ({ name: c.name, label: c.label ?? null, display_name: c.display_name ?? null })),
  });
}

/** The input `radioFocus` takes, from a `liveFocusKey` string and the seated driver. */
export function parseLiveFocus(key: string, seatedId: number | null): LiveFocusInput {
  const v = JSON.parse(key) as Partial<LiveFocusInput> & { offline?: boolean };
  return { seatedId, offline: !!v.offline, live: v.live ?? null, cues: v.cues ?? null, corners: v.corners ?? [] };
}
