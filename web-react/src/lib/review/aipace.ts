// Pace vs AI difficulty (AI pace design spec 8): the words and view models of the Summary tile, the Progress card
// "Against the AI", the Coaching card "Suggested AI level" and the Drive Session complete line. Pure; tested in node.
//
// The numbers are the server's (session_ai_pace, /api/drivers/{id}/ai-pace, snapshot.ai_pace), computed from the
// game's own telemetry only. This module never estimates anything: a status other than "ok" shows "-" and the reason
// in words; a suggested level appears only when the server measured or estimated one from the driver's own data; the
// suggestion's sentence is the server's, verbatim. Gaps read the way every page says them (lib/bests.ts
// `changeWords`): "3.8 s slower" / "0.40 s faster" / "level", a positive amount and a word, never a bare sign.
//
// Evidence tiers: a synthetic session keeps its own row (the Summary tile shows it with the SYNTHETIC tag, the Drive
// line says "synthetic data"), but synthetic sessions never feed a driver's series or a suggestion. The server leaves
// them out; this module leaves them out again (synthetic track ids, or sessions the caller knows are synthetic).

import { changeWords, type ChangeText } from "../bests";
// Types only: Drive's model imports `aiEndLine`, and the endpoint module must stay out of its eager bundle.
import type {
  AiExclusion,
  AiLevelKey,
  AiLevelSuggestion,
  AiPacePoint,
  AiPaceQuery,
  AiPaceStatus,
  DriverAiPace,
  LiveAiPace,
  SessionAiPace,
  SessionCategory,
  WeatherClass,
} from "../endpoints/review";
import { lapTime } from "../format";
import { finite, plural, sessionLabels } from "./words";

/** The typical AI car, as every AI pace text names it. */
export const TYPICAL_AI = "the typical AI car";

/** Under this gap in percent a session reads "level" with the typical AI car (the gap is stored to 2 decimals). */
export const LEVEL_PCT = 0.05;

/** "1st", "2nd", "3rd", "4th", "11th", "22nd". */
export function ordinal(n: number): string {
  const r100 = n % 100;
  if (r100 >= 11 && r100 <= 13) return `${n}th`;
  const r10 = n % 10;
  return `${n}${r10 === 1 ? "st" : r10 === 2 ? "nd" : r10 === 3 ? "rd" : "th"}`;
}

/** "Pace vs AI (difficulty 35)", or "Pace vs AI" while the difficulty is unknown. */
export function aiPaceTitle(difficulty: number | null | undefined): string {
  return finite(difficulty) ? `Pace vs AI (difficulty ${difficulty})` : "Pace vs AI";
}

/** Why there is no comparison, short (the tile's sub line); null for "ok". */
export function aiPaceReasonText(status: AiPaceStatus): string | null {
  switch (status) {
    case "ok":
      return null;
    case "no_driver_lap":
      return "No clean lap";
    case "too_few_ai_cars":
      return "Too few AI laps seen";
    case "unknown_difficulty":
      return "AI level not reported";
    case "difficulty_changed":
      return "AI level changed mid-session";
    case "time_trial":
      return "No AI cars in a time trial";
  }
}

/** "20th of 20 on best laps" (null while the rank is unknown). */
function rankText(rank: number | null | undefined, size: number | null | undefined, suffix = " on best laps"): string | null {
  return finite(rank) && finite(size) && rank >= 1 && size >= rank ? `${ordinal(rank)} of ${size}${suffix}` : null;
}

/** "3.8 s slower than the typical AI car", "level with the typical AI car"; null when the gap is unknown. */
export function gapToAiWords(gapMs: number | null | undefined): string | null {
  const c = changeWords(gapMs);
  if (!c) return null;
  return c.word === "level" ? `level with ${TYPICAL_AI}` : `${c.text} than ${TYPICAL_AI}`;
}

/** A gap in percent in words: "5.1% slower", "3.3% faster", "level". */
export function pctWords(pct: number | null | undefined): string | null {
  if (!finite(pct)) return null;
  if (Math.abs(pct) < LEVEL_PCT) return "level";
  return `${Math.abs(pct).toFixed(1)}% ${pct < 0 ? "faster" : "slower"}`;
}

// ------------------------------------------------------------------------------------------- exclusions in words

const EXCLUSION_ORDER: readonly AiExclusion[] = [
  "race_lap_1",
  "not_observed",
  "invalid",
  "pit_in_out",
  "safety_car",
  "flashback",
  "timing_inconsistent",
  "slow_car",
];

const EXCLUSION_WORDS: Readonly<Record<AiExclusion, [string, string]>> = {
  race_lap_1: ["opening lap of the race", "opening laps of the race"],
  not_observed: ["lap not seen from its start", "laps not seen from their start"],
  invalid: ["invalid lap", "invalid laps"],
  pit_in_out: ["pit lap", "pit laps"],
  safety_car: ["safety car lap", "safety car laps"],
  flashback: ["lap around a flashback", "laps around a flashback"],
  timing_inconsistent: ["lap with inconsistent timing", "laps with inconsistent timing"],
  slow_car: ["car far off the pace", "cars far off the pace"],
};

/** The AI laps (and cars) left out, in words, in a fixed order: "19 opening laps of the race, 20 laps with
 * inconsistent timing"; null when nothing was left out. Unknown reasons are named as sent. */
export function exclusionWords(excluded: Partial<Record<string, number>> | null | undefined): string | null {
  if (!excluded) return null;
  const known = EXCLUSION_ORDER.filter((k) => finite(excluded[k]) && (excluded[k] as number) > 0);
  const other = Object.keys(excluded)
    .filter((k) => !(EXCLUSION_ORDER as readonly string[]).includes(k) && finite(excluded[k]) && (excluded[k] as number) > 0)
    .sort();
  const parts = [
    ...known.map((k) => {
      const n = excluded[k] as number;
      const [one, many] = EXCLUSION_WORDS[k];
      return `${n} ${n === 1 ? one : many}`;
    }),
    ...other.map((k) => `${excluded[k]} ${k.replace(/_/g, " ")}`),
  ];
  return parts.length ? parts.join(", ") : null;
}

/** What the comparison is built from: "19 AI cars, 38 laps · not used: 19 opening laps of the race". */
export function aiEvidenceText(p: Pick<SessionAiPace, "ai_cars" | "ai_laps" | "excluded">): string {
  const used = `${plural(p.ai_cars, "AI car")}, ${plural(p.ai_laps, "lap")}`;
  const out = exclusionWords(p.excluded);
  return out ? `${used} · not used: ${out}` : used;
}

// ------------------------------------------------------------------------------------------------ Summary tile

/** Where the driver's best lap sits among the AI cars' best laps: positions 0..1, faster on the left. */
export interface AiStrip {
  /** One per AI car (sorted, fastest first). */
  ai: number[];
  /** The typical AI car (median). */
  ref: number | null;
  /** The driver's best clean lap (null without one). */
  you: number | null;
  fastestMs: number;
  slowestMs: number;
  /** The strip in words (its accessible name). */
  label: string;
}

/** The strip of AI best laps with the driver's best among them; null without AI best laps. */
export function aiStrip(p: Pick<SessionAiPace, "ai_bests_ms" | "ai_ref_ms" | "driver_best_ms" | "field_rank" | "field_size">): AiStrip | null {
  const bests = (p.ai_bests_ms ?? []).filter((v): v is number => finite(v) && v > 0).sort((a, b) => a - b);
  if (!bests.length) return null;
  const you = finite(p.driver_best_ms) && p.driver_best_ms > 0 ? p.driver_best_ms : null;
  const lo = Math.min(bests[0]!, you ?? Infinity);
  const hi = Math.max(bests[bests.length - 1]!, you ?? -Infinity);
  const span = hi - lo;
  const at = (ms: number) => (span > 0 ? (ms - lo) / span : 0.5);
  const ref = finite(p.ai_ref_ms) ? p.ai_ref_ms : null;
  const rank = rankText(p.field_rank, p.field_size, "");
  const label =
    you != null
      ? `Your best lap ${lapTime(you)} among ${plural(bests.length, "AI car")}' best laps, ${lapTime(bests[0])} to ${lapTime(bests[bests.length - 1])}${rank ? `: ${rank}` : ""}`
      : `${plural(bests.length, "AI car")}' best laps, ${lapTime(bests[0])} to ${lapTime(bests[bests.length - 1])}`;
  return {
    ai: bests.map(at),
    ref: ref != null ? at(ref) : null,
    you: you != null ? at(you) : null,
    fastestMs: bests[0]!,
    slowestMs: bests[bests.length - 1]!,
    label,
  };
}

export interface AiPaceTileView {
  /** "Pace vs AI (difficulty 35)". */
  title: string;
  status: AiPaceStatus;
  /** The gap in words ("3.8 s slower"); null shows "-". */
  change: ChangeText | null;
  /** "than the typical AI car · 20th of 20 on best laps", or the reason there is no comparison. */
  sub: string;
  /** The session is synthetic: the tile carries the SYNTHETIC tag. */
  synthetic: boolean;
  strip: AiStrip | null;
  /** What it is built from ("19 AI cars, 38 laps · not used: …"); null when there were no AI laps at all. */
  evidence: string | null;
}

/**
 * The Summary tile "Pace vs AI (difficulty 35)": hidden (null) when the session has no AI pace (a non-F1 session, one
 * from before the feature, a server without it) or is a time trial. `advanced` adds the fastest AI car's best lap.
 */
export function aiPaceTile(
  p: SessionAiPace | null | undefined,
  opts: { synthetic?: boolean | null; advanced?: boolean } = {},
): AiPaceTileView | null {
  if (!p || p.status === "time_trial") return null;
  const base = {
    title: aiPaceTitle(p.ai_difficulty),
    status: p.status,
    synthetic: opts.synthetic === true,
    evidence: p.ai_cars > 0 || p.ai_laps > 0 || exclusionWords(p.excluded) ? aiEvidenceText(p) : null,
  };
  if (p.status === "ok") {
    const change = changeWords(p.gap_ms);
    if (change) {
      const parts = [
        change.word === "level" ? `with ${TYPICAL_AI}` : `than ${TYPICAL_AI}`,
        rankText(p.field_rank, p.field_size),
        opts.advanced && finite(p.ai_best_ms) ? `fastest AI ${lapTime(p.ai_best_ms)}` : null,
      ];
      return { ...base, change, sub: parts.filter(Boolean).join(" · "), strip: aiStrip(p) };
    }
  }
  if (p.status === "ok" || p.status === "no_driver_lap") {
    // No gap to show: the AI reference at this level is still a fact.
    const ref = finite(p.ai_ref_ms) ? `typical AI best ${lapTime(p.ai_ref_ms)}` : null;
    return { ...base, change: null, sub: ["No clean lap", ref].filter(Boolean).join(" · "), strip: aiStrip(p) };
  }
  return { ...base, change: null, sub: aiPaceReasonText(p.status) ?? "Not available", strip: null };
}

// ------------------------------------------------------------------------------------------------- Drive line

/**
 * The Session complete card's one line: "Against the AI (35): 3.8 s slower than the typical AI car · 20th of 20".
 * Only for an "ok" comparison that belongs to the session on screen (`sessionId`, which must be known); a synthetic
 * session says so ("synthetic data"). Null otherwise: Drive has no other AI widget.
 */
export function aiEndLine(live: LiveAiPace | null | undefined, sessionId: string | null | undefined): string | null {
  if (!live || live.status !== "ok" || sessionId == null || live.session_id !== sessionId) return null;
  if (!finite(live.ai_difficulty)) return null;
  const gap = gapToAiWords(live.gap_ms);
  if (!gap) return null;
  const rank = rankText(live.field_rank, live.field_size, "");
  return `Against the AI (${live.ai_difficulty}): ${gap}${rank ? ` · ${rank}` : ""}${live.synthetic ? " · synthetic data" : ""}`;
}

// --------------------------------------------------------------------------------------- Progress: the series

/** A synthetic replay or stream: its own `synthetic:` track id, or a session the caller knows is synthetic. */
export function isSyntheticPoint(p: Pick<AiPacePoint, "session_id" | "track_id">, synthetic?: ReadonlySet<string> | null): boolean {
  return p.track_id.startsWith("synthetic:") || (synthetic?.has(p.session_id) ?? false);
}

const CATEGORY_WORDS: Readonly<Record<SessionCategory, { one: string; many: string; tab: string }>> = {
  race: { one: "race", many: "races", tab: "Races" },
  qualifying: { one: "qualifying session", many: "qualifying sessions", tab: "Qualifying" },
  practice: { one: "practice session", many: "practice sessions", tab: "Practice" },
  time_trial: { one: "time trial", many: "time trials", tab: "Time trial" },
  unknown: { one: "session", many: "sessions", tab: "Other" },
};

/** "Races", "Qualifying" (the toggle's words). */
export function categoryTab(c: SessionCategory): string {
  return (CATEGORY_WORDS[c] ?? CATEGORY_WORDS.unknown).tab;
}

/** "races", "qualifying sessions". */
export function categoryMany(c: SessionCategory): string {
  return (CATEGORY_WORDS[c] ?? CATEGORY_WORDS.unknown).many;
}

/** The car class as stored ("F1 World", "F2"), or words when the game did not say. */
export function classLabel(carClass: string | null | undefined): string {
  return carClass?.trim() || "Unknown class";
}

const classKeyOf = (carClass: string | null | undefined): string => carClass?.trim() ?? "";

export interface AiDot {
  sessionId: string;
  startedUnix: number;
  /** "3 Oct", "Today 19:15" (lib/review/progress.ts sessionLabels). */
  xLabel: string;
  level: number;
  status: "ok" | "no_driver_lap";
  /** Driver minus the typical AI car in percent (negative = faster); null without a clean lap. */
  gapPct: number | null;
  gapMs: number | null;
  aiRefMs: number;
  aiBestMs: number;
  aiCars: number;
  driverBestMs: number | null;
  rank: number | null;
  fieldSize: number | null;
  weather: WeatherClass | null;
  online: boolean | null;
  carName: string | null;
}

export interface AiClassChoice {
  /** "" for an unknown class. */
  key: string;
  label: string;
  sessions: number;
  newest: number;
}

export interface AiSeriesView {
  /** Car classes with sessions here, newest first. */
  classes: AiClassChoice[];
  /** The class shown (the newest point's by default); null without points. */
  classKey: string | null;
  /** Session categories in that class, newest first (a toggle only when there is more than one). */
  categories: SessionCategory[];
  category: SessionCategory | null;
  /** The sessions shown, oldest first. */
  dots: AiDot[];
  /** Dots with a gap (drawn on the chart). */
  plotted: number;
  /** Distinct AI levels among the dots, ascending. */
  levels: number[];
}

function usable(p: AiPacePoint, synthetic?: ReadonlySet<string> | null): boolean {
  return (p.status === "ok" || p.status === "no_driver_lap") && finite(p.ai_difficulty) && finite(p.ai_ref_ms) && !isSyntheticPoint(p, synthetic);
}

/**
 * The Progress card's series: the driver's sessions against the AI at this track, grouped by car class (default: the
 * class of the newest session) and session category (default: the newest one in that class). Synthetic sessions
 * never count; a session without a clean lap is kept (its gap is unknown, the AI reference at that level is a fact).
 */
export function aiSeries(
  points: readonly AiPacePoint[],
  opts: { classKey?: string | null; category?: SessionCategory | null; nowMs: number; synthetic?: ReadonlySet<string> | null },
): AiSeriesView {
  const ok = points.filter((p) => usable(p, opts.synthetic)).sort((a, b) => a.started_unix - b.started_unix);
  const by = new Map<string, AiClassChoice>();
  for (const p of ok) {
    const key = classKeyOf(p.car_class);
    const c = by.get(key) ?? { key, label: classLabel(p.car_class), sessions: 0, newest: -Infinity };
    c.sessions += 1;
    c.newest = Math.max(c.newest, p.started_unix);
    by.set(key, c);
  }
  const classes = [...by.values()].sort((a, b) => b.newest - a.newest || a.label.localeCompare(b.label));
  const classKey = opts.classKey != null && by.has(opts.classKey) ? opts.classKey : (classes[0]?.key ?? null);
  const inClass = classKey == null ? [] : ok.filter((p) => classKeyOf(p.car_class) === classKey);
  const categories: SessionCategory[] = [];
  for (const p of [...inClass].reverse()) if (!categories.includes(p.session_category)) categories.push(p.session_category);
  const category = opts.category != null && categories.includes(opts.category) ? opts.category : (categories[0] ?? null);
  const shown = inClass.filter((p) => p.session_category === category);
  const labels = sessionLabels(
    shown.map((p) => ({ startedUnix: p.started_unix })),
    opts.nowMs,
  );
  const dots: AiDot[] = shown.map((p, i) => ({
    sessionId: p.session_id,
    startedUnix: p.started_unix,
    xLabel: labels[i] ?? "",
    level: p.ai_difficulty,
    status: p.status,
    gapPct: p.status === "ok" && finite(p.gap_pct) ? p.gap_pct : null,
    gapMs: p.status === "ok" && finite(p.gap_ms) ? p.gap_ms : null,
    aiRefMs: p.ai_ref_ms,
    aiBestMs: p.ai_best_ms,
    aiCars: p.ai_cars,
    driverBestMs: finite(p.driver_best_ms) ? p.driver_best_ms : null,
    rank: finite(p.field_rank) ? p.field_rank : null,
    fieldSize: finite(p.field_size) ? p.field_size : null,
    weather: p.weather_class,
    online: p.online,
    carName: p.car_name,
  }));
  return {
    classes,
    classKey,
    categories,
    category,
    dots,
    plotted: dots.filter((d) => d.gapPct != null).length,
    levels: [...new Set(dots.map((d) => d.level))].sort((a, b) => a - b),
  };
}

const NICE = [1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 75, 100];

/** The chart's y axis: a symmetric domain around zero with headroom (room for the level label above the top dot),
 * and five ticks. */
export function gapAxis(values: readonly number[]): { max: number; ticks: number[] } {
  const peak = Math.max(1, ...values.filter(finite).map((v) => Math.abs(v) * 1.35));
  const max = NICE.find((n) => n >= peak) ?? Math.ceil(peak);
  return { max, ticks: [-max, -max / 2, 0, max / 2, max] };
}

/** A y tick in words: "level", "4% faster", "2.5% slower" (unsigned: the word carries the direction). */
export function gapTick(v: number): string {
  if (Math.abs(v) < 1e-9) return "level";
  const a = Math.abs(v);
  return `${Number.isInteger(a) ? a : a.toFixed(1)}% ${v < 0 ? "faster" : "slower"}`;
}

/** One session of the series in words (the accessible list under the chart, and the tooltip's line):
 * "AI 35: 3.8 s slower than the typical AI car (5.1% slower) · 20th of 20", or "AI 35: no clean lap · typical AI
 * best 1:14.579". */
export function dotWords(d: AiDot): string {
  const head = `AI ${d.level}`;
  const gap = d.gapMs != null ? gapToAiWords(d.gapMs) : null;
  if (!gap) return `${head}: no clean lap · typical AI best ${lapTime(d.aiRefMs)}`;
  const pct = pctWords(d.gapPct);
  const rank = rankText(d.rank, d.fieldSize, "");
  return [`${head}: ${gap}${pct && pct !== "level" ? ` (${pct})` : ""}`, rank].filter(Boolean).join(" · ");
}

// ------------------------------------------------------------------------------------- suggestions (Coaching)

function keyOfSuggestion(s: AiLevelSuggestion): AiLevelKey {
  return s.key;
}

/** The suggestions for a track (and, when given, a class and category), newest first; synthetic keys never. */
export function suggestionsFor(
  suggestions: readonly AiLevelSuggestion[] | null | undefined,
  scope: { game?: string | null; trackId?: string | null; classKey?: string | null; category?: SessionCategory | null },
): AiLevelSuggestion[] {
  return (suggestions ?? []).filter((s) => {
    const k = keyOfSuggestion(s);
    if (k.track_id.startsWith("synthetic:")) return false;
    if (scope.game && k.game !== scope.game) return false;
    if (scope.trackId && k.track_id !== scope.trackId) return false;
    if (scope.classKey != null && classKeyOf(k.car_class) !== scope.classKey) return false;
    if (scope.category && k.session_category !== scope.category) return false;
    return true;
  });
}

/** The one suggestion for the series on screen: its class and category, the newest session's weather first. */
export function suggestionForSeries(
  suggestions: readonly AiLevelSuggestion[] | null | undefined,
  scope: { game: string; trackId: string },
  view: Pick<AiSeriesView, "classKey" | "category" | "dots">,
): AiLevelSuggestion | null {
  if (view.classKey == null || view.category == null) return null;
  const all = suggestionsFor(suggestions, { ...scope, classKey: view.classKey, category: view.category });
  const weather = view.dots[view.dots.length - 1]?.weather ?? null;
  return all.find((s) => s.key.weather_class === weather) ?? all[0] ?? null;
}

/** "Austria · F1 World races · dry". */
export function suggestionKeyLabel(k: AiLevelKey): string {
  const where = k.track_name?.trim() || k.track_id;
  const what = `${classLabel(k.car_class)} ${categoryMany(k.session_category)}`;
  return [where, what, k.weather_class].filter(Boolean).join(" · ");
}

export interface SuggestionView {
  /** "level": a measured or estimated level to show large; "direction": the guidance sentence only. */
  kind: "level" | "direction";
  keyLabel: string;
  /** "AI 38". */
  level: string | null;
  /** "or higher" / "or lower" when the level is a bound. */
  bound: string | null;
  /** "Range 35–41". */
  range: string | null;
  confidence: { word: "high" | "medium" | "low"; label: string; tone: "default" | "warning" } | null;
  /** Estimated from the driver's other tracks (never measured here). */
  estimate: boolean;
  /** The server's sentence, verbatim. */
  text: string;
  /** Why no level yet, when the levels raced here disagree. */
  note: string | null;
  direction: "higher" | "lower" | "about_right" | null;
}

/**
 * A suggestion as the Coaching card shows it. A level is shown only for a measured or estimated basis that carries
 * one (never computed here); anything else is the guidance sentence alone.
 */
export function suggestionView(s: AiLevelSuggestion): SuggestionView {
  const hasLevel = (s.basis === "measured" || s.basis === "estimate_other_tracks") && finite(s.level);
  const range =
    hasLevel && s.range && finite(s.range[0]) && finite(s.range[1]) && s.range[0] !== s.range[1]
      ? `Range ${s.range[0]}–${s.range[1]}`
      : null;
  const conf = hasLevel ? s.confidence : null;
  return {
    kind: hasLevel ? "level" : "direction",
    keyLabel: suggestionKeyLabel(s.key),
    level: hasLevel ? `AI ${s.level}` : null,
    bound: hasLevel ? (s.bound === "at_least" ? "or higher" : s.bound === "at_most" ? "or lower" : null) : null,
    range,
    confidence: conf
      ? {
          word: conf,
          label: conf === "low" ? "Low confidence · rough estimate" : `${conf === "high" ? "High" : "Medium"} confidence`,
          tone: conf === "low" ? "warning" : "default",
        }
      : null,
    estimate: hasLevel && s.basis === "estimate_other_tracks",
    text: s.text,
    note: s.note === "levels_disagree" ? "Your results at different levels here do not line up yet, so no level is suggested." : null,
    direction: s.direction,
  };
}

/**
 * The Progress card's one sentence: the server's suggestion text for the series on screen (verbatim), else a plain
 * description of the newest session; null without sessions (the card says so).
 */
export function aiSeriesSentence(
  view: Pick<AiSeriesView, "dots">,
  suggestion: AiLevelSuggestion | null,
  who: { poss: string },
): string | null {
  if (!view.dots.length) return null;
  if (suggestion?.text) return suggestion.text;
  const newest = view.dots[view.dots.length - 1]!;
  const plotted = [...view.dots].reverse().find((d) => d.gapPct != null && d.gapMs != null);
  if (!plotted) {
    return `No clean lap against the AI here yet: the typical AI car's best lap at AI ${newest.level} was ${lapTime(newest.aiRefMs)}.`;
  }
  const pct = pctWords(plotted.gapPct);
  return pct === "level"
    ? `At AI ${plotted.level} ${who.poss} best lap here was level with ${TYPICAL_AI}.`
    : `At AI ${plotted.level} ${who.poss} best lap here was ${pct} than ${TYPICAL_AI}.`;
}

// ------------------------------------------------------------------------------------------- pages: the request

/** The request Progress and the Coaching plan share for a driver at a track (one cache entry for both; the server's
 * defaults: the newest 200 sessions, target level with the typical AI car). */
export function aiPaceQuery(scope: { game: string; trackId: string }): AiPaceQuery {
  return { game: scope.game, track_id: scope.trackId };
}

/** Games whose sessions can have an AI comparison (the AI difficulty and the AI field's lap times come from F1's
 * Session and Session History packets). Others never get a row, so the cards stay out of their pages. */
export function aiPaceGame(game: string | null | undefined): boolean {
  return typeof game === "string" && game.startsWith("f1");
}

/**
 * Whether a page shows its AI card: never when the server predates AI pace (a 404 from its router), always when there
 * are points, otherwise for games that can have AI pace (an empty state there says why it is empty).
 */
export function showAiCard(game: string | null | undefined, data: Pick<DriverAiPace, "points"> | undefined, missingRoute: boolean): boolean {
  if (missingRoute) return false;
  if (data && data.points.length > 0) return true;
  return aiPaceGame(game);
}
