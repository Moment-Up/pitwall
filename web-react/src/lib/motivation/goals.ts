// Goals on Review › Progress (lane motivation, spec 9 GoalsCard / GoalSheet): the rows a driver's goals become, the
// suggestion cards, and the "Make your own" form, checked before it is sent. Pure; tested in plain node.
//
// Every sentence is the server's (titles, progress and achievement texts, the basis of a suggestion), in its simple
// wording for simple-wording drivers. The form only checks what was typed against the same limits the server
// enforces (it answers 422 / 409 with its own `detail`, which the sheet shows as it is).

import type { Goal, GoalCreate, GoalKind, GoalsResponse, GoalSuggestion, RaceRule } from "../endpoints/motivation";
import { classLabel, count, isF1Game, parseLapTarget, percent, possessive } from "./format";

export interface GoalRowView {
  id: number;
  kind: GoalKind;
  status: Goal["status"];
  title: string;
  scopeText: string | null;
  /** 0..100 for the bar; null = no bar (nothing measured yet, or no baseline). */
  percent: number | null;
  /** The server's progress sentence (or its simple wording). */
  progressText: string;
  met: boolean;
  /** Reached: the achievement sentence, its session, and whether that session is still this driver's. */
  achieved: { text: string; sessionId: string | null; owned: boolean } | null;
  /** "Why this target?" for a goal Pitwall suggested (the basis, verbatim). */
  why: string | null;
}

/** The text a driver reads: the simple wording when the profile asks for it. */
export const goalTitle = (g: Pick<Goal, "title" | "title_simple">, simple: boolean): string =>
  simple && g.title_simple ? g.title_simple : g.title;

export function goalRow(g: Goal, simple: boolean): GoalRowView {
  const p = g.progress;
  const a = g.achieved;
  return {
    id: g.id,
    kind: g.kind,
    status: g.status,
    title: goalTitle(g, simple),
    scopeText: g.scope_text,
    percent: g.status === "achieved" ? 100 : percent(p.fraction),
    progressText: (simple && p.text_simple ? p.text_simple : p.text) || "-",
    met: p.met || g.status === "achieved",
    achieved: a
      ? { text: (simple && a.text_simple ? a.text_simple : a.text) || "-", sessionId: a.session_id, owned: a.session_owned }
      : null,
    why: g.source === "suggested" && g.basis ? (simple && g.basis.text_simple ? g.basis.text_simple : g.basis.text) : null,
  };
}

export type GoalAction = "archive" | "delete" | "reopen";

/** A row's menu: Archive · Delete, and Reopen first for a goal reached in a session that is now someone else's (only
 * then: reopened, a goal the driver's own lap still reaches would be reached and celebrated again by that lap; the
 * server refuses it, 409 "still_reached"). */
export function rowActions(row: Pick<GoalRowView, "status" | "achieved">): { id: GoalAction; text: string }[] {
  const base: { id: GoalAction; text: string }[] = [
    { id: "archive", text: "Archive" },
    { id: "delete", text: "Delete" },
  ];
  return row.status === "achieved" && row.achieved && !row.achieved.owned ? [{ id: "reopen", text: "Reopen" }, ...base] : base;
}

export interface GoalsView {
  active: GoalRowView[];
  reached: GoalRowView[];
  /** Below the server's limit of active goals. */
  canAdd: boolean;
  /** Why Add is off, or null. */
  limitText: string | null;
  simple: boolean;
}

/** Where the page is looking (the ScopeBar's game, track and car): its goals come first. */
export interface GoalsPlace {
  game: string | null;
  trackId: string | null;
  carId: string | null;
}

/** 0: this track (and this car, or any car of a class); 1: anywhere; 2: another track or car. No place: all 0 (the
 * server's order). */
function placeRank(g: Goal, place: GoalsPlace | null | undefined): number {
  if (!place?.trackId) return 0;
  if (!g.scope.track_id) return 1;
  const here = g.scope.game === place.game && g.scope.track_id === place.trackId;
  const car = g.scope.car_id == null || g.scope.car_id === place.carId;
  return here && car ? 0 : 2;
}

/** Active goals first, the ones for the page's track and car on top, then those that count anywhere, then other
 * tracks (the server's order within each); then the ones reached in the last 30 days, newest first. */
export function goalsView(r: GoalsResponse | null | undefined, simpleOverride?: boolean, place?: GoalsPlace | null): GoalsView {
  const simple = simpleOverride ?? !!r?.simple;
  const goals = r?.goals ?? [];
  const active = goals
    .filter((g) => g.status === "active")
    .map((g, i) => ({ g, i, rank: placeRank(g, place) }))
    .sort((a, b) => a.rank - b.rank || a.i - b.i)
    .map(({ g }) => goalRow(g, simple));
  const reached = goals
    .filter((g) => g.status === "achieved")
    .sort((a, b) => (b.achieved?.unix ?? 0) - (a.achieved?.unix ?? 0))
    .map((g) => goalRow(g, simple));
  const max = r?.limits.max_active ?? 6;
  const n = r?.limits.active ?? active.length;
  const canAdd = n < max;
  return {
    active,
    reached,
    canAdd,
    limitText: canAdd ? null : `${count(max, "goal")} at once at most: archive or delete one to add another.`,
    simple,
  };
}

export interface SuggestionView {
  key: string;
  kind: GoalKind;
  title: string;
  scopeText: string | null;
  why: string;
  create: GoalCreate;
}

export function suggestionView(s: GoalSuggestion, simple: boolean, i = 0): SuggestionView {
  return {
    key: `${s.kind}:${s.target}:${s.scope_text ?? ""}:${i}`,
    kind: s.kind,
    title: goalTitle(s, simple),
    scopeText: s.scope_text,
    why: simple && s.basis.text_simple ? s.basis.text_simple : s.basis.text,
    // Sent as the server built it, marked as Pitwall's suggestion with its basis (so "Why this target?" stays).
    create: { ...s.create, source: "suggested", basis: s.create.basis ?? s.basis },
  };
}

// ------------------------------------------------------------------------------------------------- the form

/** Make your own (spec 9 GoalSheet): one kind at a time, each with its own fields. */
export interface GoalDraft {
  kind: GoalKind;
  /** Lap time: "1:10.0". */
  lapText: string;
  /** Lap time: this exact car, or any car of its class (when a class is known). */
  carChoice: "car" | "class";
  /** Clean laps in a row: 2..50. */
  laps: number;
  /** Steady laps: how many in a row, and within how many seconds of each other. */
  window: 3 | 5 | 10;
  seconds: number;
  /** Clean race. */
  rule: RaceRule;
}

export const DEFAULT_DRAFT: GoalDraft = {
  kind: "lap_time",
  lapText: "",
  carChoice: "car",
  laps: 5,
  window: 5,
  seconds: 1.5,
  rule: "no_penalties",
};

/** Where a lap-time goal is set (the ScopeBar's game, track and car). `carClass` when the server knows the car's
 * class (F1 formula, Forza class). */
export interface DraftScope {
  game: string | null;
  trackId: string | null;
  trackLabel: string | null;
  carId: string | null;
  carLabel: string | null;
  carClass: string | null;
  /** The ScopeBar shows a synthetic track: a goal never counts generated data. */
  synthetic: boolean;
}

export const KIND_LABEL: Readonly<Record<GoalKind, string>> = {
  lap_time: "Lap time",
  clean_streak: "Clean laps",
  consistency: "Steady laps",
  race_clean: "Clean race",
};

export const STREAK_MIN = 2;
export const STREAK_MAX = 50;
export const SPREAD_MIN_S = 0.1;
export const SPREAD_MAX_S = 10;

export type DraftResult = { ok: true; body: GoalCreate } | { ok: false; error: string };

/** Why a lap-time goal cannot be set here, or null. */
export function lapGoalBlocked(scope: DraftScope | null): string | null {
  if (!scope) return "A lap-time goal is for one track: drive there first, then set it.";
  if (!scope.game || !scope.trackId) return "Pick a track above first: a lap-time goal is for one track.";
  if (scope.synthetic) return "This is a synthetic track: goals only count real driving.";
  if (!scope.carId && !scope.carClass) return "Pick a car above first: a lap-time goal is for one car or class.";
  return null;
}

/** Why a clean-race goal cannot be checked in this game, or null (race goals need F1's session type and lap total). */
export function raceGoalBlocked(scope: DraftScope | null): string | null {
  if (scope?.game && !isF1Game(scope.game)) return "Pitwall can only check this in F1 races: this game does not report races.";
  return null;
}

/** The active lap-time goal already set for this track and car (or class), or null: the server allows one per place,
 * so the form says so before anything is typed. */
export function lapGoalHere(
  goals: readonly Goal[] | null | undefined,
  scope: DraftScope | null,
  carChoice: GoalDraft["carChoice"],
): Goal | null {
  if (!scope?.game || !scope.trackId) return null;
  const byClass = carChoice === "class" && !!scope.carClass;
  return (
    goals?.find(
      (g) =>
        g.status === "active" &&
        g.kind === "lap_time" &&
        g.scope.game === scope.game &&
        g.scope.track_id === scope.trackId &&
        (byClass ? g.scope.car_class === scope.carClass : g.scope.car_class == null && g.scope.car_id === scope.carId),
    ) ?? null
  );
}

/** "You already have a lap-time goal here: A lap under 1:10.000. Archive it to set a new time." */
export function lapGoalHereText(g: Goal, simple: boolean): string {
  return `You already have a lap-time goal here: ${goalTitle(g, simple)}. Archive it to set a new time.`;
}

/** The class choice for a lap-time goal ("any F1 World car"), or null when the class is unknown. */
export function classChoice(scope: DraftScope | null): string | null {
  return classLabel(scope?.carClass, scope?.carLabel);
}

/** The draft as the POST body, or what to fix. Limits match the server's (lane spec 4.5). */
export function draftToCreate(d: GoalDraft, scope: DraftScope | null): DraftResult {
  switch (d.kind) {
    case "lap_time": {
      const blocked = lapGoalBlocked(scope);
      if (blocked || !scope) return { ok: false, error: blocked ?? "Pick a track above first." };
      const t = parseLapTarget(d.lapText);
      if (!t.ok) return t;
      const byClass = d.carChoice === "class" && !!scope.carClass;
      if (!byClass && !scope.carId) return { ok: false, error: "Pick a car above first: a lap-time goal is for one car or class." };
      return {
        ok: true,
        body: {
          kind: "lap_time",
          target: t.ms,
          game: scope.game,
          track_id: scope.trackId,
          car_id: byClass ? null : scope.carId,
          car_class: byClass ? scope.carClass : null,
          source: "manual",
        },
      };
    }
    case "clean_streak": {
      const n = d.laps;
      if (!Number.isInteger(n) || n < STREAK_MIN || n > STREAK_MAX) {
        return { ok: false, error: `Pick between ${STREAK_MIN} and ${STREAK_MAX} clean laps in a row.` };
      }
      return { ok: true, body: { kind: "clean_streak", target: n, source: "manual" } };
    }
    case "consistency": {
      const ms = Math.round(d.seconds * 1000);
      if (!Number.isFinite(d.seconds) || ms % 100 !== 0) return { ok: false, error: "Use tenths of a second, like 1.1." };
      if (ms < SPREAD_MIN_S * 1000 || ms > SPREAD_MAX_S * 1000) {
        return { ok: false, error: `Pick between ${SPREAD_MIN_S} and ${SPREAD_MAX_S} seconds.` };
      }
      if (![3, 5, 10].includes(d.window)) return { ok: false, error: "Pick 3, 5 or 10 laps." };
      return { ok: true, body: { kind: "consistency", target: ms, params: { window_laps: d.window }, source: "manual" } };
    }
    case "race_clean": {
      const blocked = raceGoalBlocked(scope);
      if (blocked) return { ok: false, error: blocked };
      return { ok: true, body: { kind: "race_clean", target: 1, params: { rule: d.rule }, source: "manual" } };
    }
  }
}

/** The footer note under the goals (spec 9): real driving only, and what "clean" means where the game sends no
 * lap validity (GT7, AC, Forza). */
export function goalsFootnote(name: string, game: string | null | undefined): string[] {
  const lines = [`From ${possessive(name)} real driving: synthetic and replayed sessions never count.`];
  if (game && !isF1Game(game)) {
    lines.push("This game does not report track limits, so 'clean' means no pit lap, reset or flashback.");
  }
  return lines;
}
