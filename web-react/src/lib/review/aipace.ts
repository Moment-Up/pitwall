// Pace vs AI difficulty (AI pace design spec 8): the words and view models of the Summary tile, the Progress card
// "Against the AI", the Coaching card "Suggested AI difficulty" and the Drive Session complete line. Pure; tested in node.
//
// The numbers are the server's (session_ai_pace, /api/drivers/{id}/ai-pace, snapshot.ai_pace), computed from the
// game's own telemetry only. This module never estimates anything: a status other than "ok" shows "-" and the reason
// in words; a suggested level appears only when the server measured or estimated one from the driver's own data. The
// suggestion's sentence is built here from the server's fields for whoever is viewed ("your" / "Sam's"): the server's
// own `text` speaks to the driver in the seat (Ask and the radio say it). Gaps read the way every page says them
// (lib/bests.ts `changeWords`): "3.8 s slower" / "0.40 s faster" / "level", a positive amount and a word, never a
// bare sign. Words (lib/review/words.ts): the setting is "AI difficulty" in every label and sentence ("AI difficulty
// 35"); "AI 35" only as a compact value in rows, dots and suggestion levels; comparisons are best lap against best
// lap, and say so ("than the typical AI car's best lap", "on best laps").
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
  AiPaceUnusable,
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

/** AI cars with clean laps the server needs for a comparison (analysis/ai_pace.py MIN_AI_CARS). */
export const AI_MIN_CARS = 5;

/** Levels apart the driver must race at one track before a level can be measured (analysis/ai_level.py MIN_SPAN). */
export const AI_MIN_SPAN = 5;

/** The game's AI difficulty range (F1 Session.aiDifficulty 0-110). */
export const AI_LEVEL_MIN = 0;
export const AI_LEVEL_MAX = 110;

/** Under this gap in percent a session reads "level" with the typical AI car (the gap is stored to 2 decimals). */
export const LEVEL_PCT = 0.05;

/** "1st", "2nd", "3rd", "4th", "11th", "22nd". */
export function ordinal(n: number): string {
  const r100 = n % 100;
  if (r100 >= 11 && r100 <= 13) return `${n}th`;
  const r10 = n % 10;
  return `${n}${r10 === 1 ? "st" : r10 === 2 ? "nd" : r10 === 3 ? "rd" : "th"}`;
}

/** "Pace vs AI · AI difficulty 35", or "Pace vs AI" while the difficulty is unknown. */
export function aiPaceTitle(difficulty: number | null | undefined): string {
  return finite(difficulty) ? `Pace vs AI · AI difficulty ${difficulty}` : "Pace vs AI";
}

/** Why there is no comparison, short (the tile's sub line); null for "ok". With the session's row, "too few" says the
 * rule and what was seen, and an online lobby says it had other players. */
export function aiPaceReasonText(status: AiPaceStatus, p?: Pick<SessionAiPace, "ai_cars" | "online"> | null): string | null {
  switch (status) {
    case "ok":
      return null;
    case "no_driver_lap":
      return "No clean lap";
    case "too_few_ai_cars":
      if (p?.online) return "Online session: other players, too few AI cars to compare";
      return p ? `Too few AI laps: needs clean laps from ${AI_MIN_CARS} AI cars, saw ${p.ai_cars}` : "Too few AI laps seen";
    case "unknown_difficulty":
      return "AI difficulty not reported";
    case "difficulty_changed":
      return "AI difficulty changed mid-session";
    case "time_trial":
      return "No AI cars in a time trial";
  }
}

/** "20th of 20 on best laps" (null while the rank is unknown). */
function rankText(rank: number | null | undefined, size: number | null | undefined, suffix = " on best laps"): string | null {
  return finite(rank) && finite(size) && rank >= 1 && size >= rank ? `${ordinal(rank)} of ${size}${suffix}` : null;
}

/** "3.8 s slower than the typical AI car's best lap", "level with the typical AI car's best lap"; null when the gap
 * is unknown. Best lap against best lap, and it says so (a bare "3.8 s slower" reads as a race gap). */
export function gapToAiWords(gapMs: number | null | undefined): string | null {
  const c = changeWords(gapMs);
  if (!c) return null;
  return c.word === "level" ? `level with ${TYPICAL_AI}'s best lap` : `${c.text} than ${TYPICAL_AI}'s best lap`;
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
  "not_ai_driven",
  "results_skip",
  "invalid",
  "pit_in_out",
  "safety_car",
  "red_flag",
  "flashback",
  "timing_inconsistent",
  "fast_outlier",
  "slow_car",
];

const EXCLUSION_WORDS: Readonly<Record<AiExclusion, [string, string]>> = {
  race_lap_1: ["opening lap of the race", "opening laps of the race"],
  not_observed: ["lap not seen from its start", "laps not seen from their start"],
  not_ai_driven: ["lap a human drove before the AI took over", "laps a human drove before the AI took over"],
  results_skip: ["lap the game filled in (not driven)", "laps the game filled in (not driven)"],
  invalid: ["invalid lap", "invalid laps"],
  pit_in_out: ["pit lap", "pit laps"],
  safety_car: ["safety car lap", "safety car laps"],
  red_flag: ["lap around a red flag", "laps around a red flag"],
  flashback: ["lap around a flashback", "laps around a flashback"],
  timing_inconsistent: ["lap with inconsistent timing", "laps with inconsistent timing"],
  fast_outlier: ["impossibly fast lap", "impossibly fast laps"],
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

/** What the comparison is built from: "From 19 AI cars, 38 laps · not used: 19 opening laps of the race"; "Seen: …"
 * when there is no comparison (nothing was built from them). `brief` leaves the not-used list out (core summaries). */
export function aiEvidenceText(
  p: Pick<SessionAiPace, "status" | "ai_cars" | "ai_laps" | "excluded">,
  opts: { brief?: boolean } = {},
): string {
  const head = p.status === "ok" || p.status === "no_driver_lap" ? "From" : "Seen:";
  const used = `${head} ${plural(p.ai_cars, "AI car")}, ${plural(p.ai_laps, "lap")}`;
  const out = opts.brief ? null : exclusionWords(p.excluded);
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
  /** "Pace vs AI · AI difficulty 35". */
  title: string;
  status: AiPaceStatus;
  /** The gap in words ("3.8 s slower"); null shows "-". */
  change: ChangeText | null;
  /** "than the typical AI car's best lap · 20th of 20 on best laps", or the reason there is no comparison. */
  sub: string;
  /** The session is synthetic: the tile carries the SYNTHETIC tag. */
  synthetic: boolean;
  strip: AiStrip | null;
  /** What it is built from ("From 19 AI cars, 38 laps · not used: …", or "Seen: …" without a comparison); null when
   * there were no AI laps at all. */
  evidence: string | null;
}

/** The strip's caption when the page shows chart captions. */
export const AI_STRIP_CAPTION = "Each mark is one AI car's best lap; the tall mark is the typical AI car.";

/**
 * The Summary tile "Pace vs AI · AI difficulty 35": hidden (null) when the session has no AI pace (a non-F1 session,
 * one from before the feature, a server without it) or is a time trial. `advanced` adds the fastest AI car's best lap;
 * `brief` (core summaries) leaves the list of laps not used out.
 */
export function aiPaceTile(
  p: SessionAiPace | null | undefined,
  opts: { synthetic?: boolean | null; advanced?: boolean; brief?: boolean } = {},
): AiPaceTileView | null {
  if (!p || p.status === "time_trial") return null;
  const base = {
    title: aiPaceTitle(p.ai_difficulty),
    status: p.status,
    synthetic: opts.synthetic === true,
    evidence: p.ai_cars > 0 || p.ai_laps > 0 || exclusionWords(p.excluded) ? aiEvidenceText(p, { brief: opts.brief }) : null,
  };
  if (p.status === "ok") {
    const change = changeWords(p.gap_ms);
    if (change) {
      const parts = [
        change.word === "level" ? `with ${TYPICAL_AI}'s best lap` : `than ${TYPICAL_AI}'s best lap`,
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
  return { ...base, change: null, sub: aiPaceReasonText(p.status, p) ?? "Not available", strip: null };
}

// ------------------------------------------------------------------------------------------------- Drive line

/**
 * The Session complete card's one line: "AI difficulty 35: best lap 3.8 s slower than the typical AI car's best lap ·
 * 20th of 20 on best laps". Only for an "ok" comparison that belongs to the session on screen (`sessionId`, which must
 * be known); a synthetic session says so ("synthetic data"). Null otherwise: Drive has no other AI widget.
 */
export function aiEndLine(live: LiveAiPace | null | undefined, sessionId: string | null | undefined): string | null {
  if (!live || live.status !== "ok" || sessionId == null || live.session_id !== sessionId) return null;
  if (!finite(live.ai_difficulty)) return null;
  const gap = gapToAiWords(live.gap_ms);
  if (!gap) return null;
  const rank = rankText(live.field_rank, live.field_size);
  return `AI difficulty ${live.ai_difficulty}: best lap ${gap}${rank ? ` · ${rank}` : ""}${live.synthetic ? " · synthetic data" : ""}`;
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
 * "AI 35: 3.8 s slower than the typical AI car's best lap (5.1% slower) · 20th of 20 on best laps", or "AI 35: no
 * clean lap · typical AI best 1:14.579"; an online lobby says so. */
export function dotWords(d: AiDot): string {
  const head = `AI ${d.level}`;
  const online = d.online ? "online" : null;
  const gap = d.gapMs != null ? gapToAiWords(d.gapMs) : null;
  if (!gap) return [`${head}: no clean lap`, `typical AI best ${lapTime(d.aiRefMs)}`, online].filter(Boolean).join(" · ");
  const pct = pctWords(d.gapPct);
  const rank = rankText(d.rank, d.fieldSize);
  return [`${head}: ${gap}${pct && pct !== "level" ? ` (${pct})` : ""}`, rank, online].filter(Boolean).join(" · ");
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

/** "Austria · F1 World class · races · dry"; with the car the driver used when it is not the class's own name,
 * "F1 World class (F1 Generic)". */
export function suggestionKeyLabel(k: AiLevelKey, carName?: string | null): string {
  const where = k.track_name?.trim() || k.track_id;
  const cls = classLabel(k.car_class);
  const car = carName?.trim();
  const what = k.car_class?.trim() ? `${cls} class${car && car !== cls ? ` (${car})` : ""}` : cls;
  return [where, what, categoryMany(k.session_category), k.weather_class].filter(Boolean).join(" · ");
}

/** A stored car name that is a raw id or F1's neutral fallback ("team_214", "f1:team:214", "Unknown team (id 214)"). */
const RAW_CAR = /^(?:unknown\b|team_\d+$|f1:team:\d+$)/i;

/** A point's car in words: the server's label without its class prefix ("F2 · Hitech '25" -> "Hitech '25"), nothing
 * for a label that names only the class ("F2 car"), else the stored name (older servers). */
function aiCarName(p: Pick<AiPacePoint, "car_name" | "car_label">): string | null {
  const label = p.car_label?.trim();
  if (label) {
    if (label.includes("·")) return label.replace(/^[^·]+·\s*/, "") || null;
    return / car$/i.test(label) ? null : label;
  }
  return p.car_name?.trim() || null;
}

/** The car the driver used last in each car class (key: the class as stored, "" when unknown): the server's car_label
 * without its class prefix ("F2 · Hitech '25" -> "Hitech '25"), else the stored name. A name the game did not give
 * ("Unknown team (id 214)", "team_214") is left out: it would say nothing the class does not. */
export function aiCarNamesByClass(
  points: readonly Pick<AiPacePoint, "car_class" | "car_name" | "car_label" | "started_unix">[],
): Map<string, string> {
  const out = new Map<string, string>();
  for (const p of [...points].sort((a, b) => a.started_unix - b.started_unix)) {
    const name = aiCarName(p);
    if (name && !RAW_CAR.test(name)) out.set(classKeyOf(p.car_class), name);
    else out.delete(classKeyOf(p.car_class));
  }
  return out;
}

/** Who a sentence is about: "your" for the driver in the seat, "Sam's" for another driver (lib/review/progress.ts). */
export interface AiWho {
  poss: string;
  /** Sentence start ("Your" / "Sam's"); derived from `poss` when absent. */
  Poss?: string;
}

const capital = (w: string): string => (w ? w.charAt(0).toUpperCase() + w.slice(1) : w);

/** "30", "30 and 35", "30, 35 and 40" (also for names). */
function andList(values: readonly (number | string)[]): string {
  const items = values.map(String);
  return items.length <= 1 ? (items[0] ?? "") : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/** The newest gap as an amount and a word: "3.8 s (5.1%) slower" (percent only when seconds are unknown). */
function latestGapWords(s: Pick<AiLevelSuggestion, "latest_gap_pct" | "latest_gap_ms">): string | null {
  const g = s.latest_gap_pct;
  if (!finite(g)) return null;
  const word = g > 0 ? "slower" : "faster";
  const ms = s.latest_gap_ms;
  return finite(ms) ? `${(Math.abs(ms) / 1000).toFixed(1)} s (${Math.abs(g).toFixed(1)}%) ${word}` : `${Math.abs(g).toFixed(1)}% ${word}`;
}

/**
 * A suggestion in words about the driver who is viewed, built from the server's fields with the server's own wording
 * (analysis/ai_level.py): for the driver in the seat ("your") it is the server's `text`, word for word; for another
 * driver only the possessive changes ("At AI 35 Sam's best lap here was 3.8 s (5.1%) slower than the typical AI car's
 * best lap, so a lower level should give closer racing. Race here once more at AI 30 or lower and Pitwall can suggest
 * a level.").
 */
export function suggestionSentence(s: AiLevelSuggestion, who: AiWho): string {
  const poss = who.poss;
  const Poss = who.Poss ?? capital(poss);
  const cat = CATEGORY_WORDS[s.key.session_category] ?? CATEGORY_WORDS.unknown;
  const levels = andList(s.levels_used);
  const lvl = s.level;
  if ((s.basis === "measured" || s.basis === "estimate_other_tracks") && finite(lvl)) {
    const more = s.bound === "at_least" ? "or higher" : s.bound === "at_most" ? "or lower" : null;
    const range = s.range && finite(s.range[0]) && finite(s.range[1]) ? s.range : null;
    if (s.basis === "measured") {
      const sessions = plural(s.sessions_used, cat.one, cat.many);
      if (more) {
        const side = s.bound === "at_least" ? "above" : "below";
        return `Try AI ${lvl} ${more} here: the trend of ${poss} ${sessions} at levels ${levels} puts level racing with ${TYPICAL_AI} ${side} AI ${lvl}.`;
      }
      return `Try AI ${lvl} here${range ? `, between ${range[0]} and ${range[1]}` : ""}. Measured from ${sessions} at levels ${levels}.`;
    }
    const shown = more ? `${lvl} ${more}` : `about ${lvl}${range ? `, between ${range[0]} and ${range[1]}` : ""}`;
    const where = s.slope_sources.length ? andList(s.slope_sources) : "other tracks";
    return `Estimated AI level here: ${shown}. Based on how the AI's pace changed with level at ${where}; race here at another level to measure it.`;
  }
  const d = s.latest_level;
  const g = s.latest_gap_pct;
  const gap = latestGapWords(s);
  let tail: string;
  if (s.note === "levels_disagree") {
    tail = `${Poss} ${cat.many} here at levels ${levels} do not yet show the AI getting faster with level, so Pitwall cannot suggest one yet.`;
  } else if (s.direction === "about_right") {
    const others = [d - AI_MIN_SPAN, d + AI_MIN_SPAN].filter((v) => v >= AI_LEVEL_MIN && v <= AI_LEVEL_MAX);
    tail = `Racing here once more at AI ${others.join(" or ")} would let Pitwall measure ${poss} level.`;
  } else {
    const lower = s.direction === "lower";
    const next = s.next_level;
    if (finite(next) && next !== d) {
      const more = next === AI_LEVEL_MIN || next === AI_LEVEL_MAX ? "" : lower ? " or lower" : " or higher";
      tail = `Race here once more at AI ${next}${more} and Pitwall can suggest a level.`;
    } else if ((lower && d <= AI_LEVEL_MIN) || (!lower && d >= AI_LEVEL_MAX)) {
      tail = `AI ${d} is already the game's ${lower ? "lowest" : "highest"} level.`;
    } else {
      // a server before method 2 sent no next level
      tail = `Race here once more at a level ${AI_MIN_SPAN} or more ${lower ? "lower" : "higher"} and Pitwall can suggest a level.`;
    }
  }
  if (!gap || !finite(g)) return tail;
  if (s.direction === "about_right") {
    if (Math.abs(g) < LEVEL_PCT) return `At AI ${d} ${poss} best lap here was level with ${TYPICAL_AI}'s best lap. ${tail}`;
    const aim = Math.abs(s.target_gap_pct ?? 0) < 1e-9 ? "about level" : "close to the gap you aim for";
    return `At AI ${d} ${poss} best lap here was ${gap} than ${TYPICAL_AI}'s best lap: ${aim}, so AI ${d} looks about right. ${tail}`;
  }
  const advice = s.direction === "lower" ? "a lower level should give closer racing" : "try a higher level";
  return `At AI ${d} ${poss} best lap here was ${gap} than ${TYPICAL_AI}'s best lap, so ${advice}. ${tail}`;
}

export interface SuggestionView {
  /** "level": a measured or estimated level to show large; "direction": which way to move, large, with the sentence. */
  kind: "level" | "direction";
  keyLabel: string;
  /** "AI 38", "about AI 20" (an estimate). */
  level: string | null;
  /** "or higher" / "or lower" when the level is a bound. */
  bound: string | null;
  /** "Range 35–41"; never for a bound (a range around a limit would contradict it). */
  range: string | null;
  confidence: { word: "high" | "medium" | "low"; label: string; tone: "default" | "warning" } | null;
  /** Measured at this track (the "Measured here" chip). */
  measured: boolean;
  /** Estimated from the driver's other tracks (never measured here). */
  estimate: boolean;
  /** direction kind: "Lower than AI 35", "Higher than AI 31", "AI 35 looks about right". */
  headline: string | null;
  /** The sentence about the viewed driver (suggestionSentence). */
  text: string;
  /** Why no level yet, when the levels raced here disagree. */
  note: string | null;
  direction: "higher" | "lower" | "about_right" | null;
}

/** What every suggestion aims for, in words (the server's default target: level with the typical AI car). */
export function suggestionAim(targetGapPct: number | null | undefined): string {
  if (!finite(targetGapPct) || Math.abs(targetGapPct) < LEVEL_PCT) return `Aim: a best lap level with ${TYPICAL_AI}'s (mid-pack)`;
  return `Aim: a best lap ${Math.abs(targetGapPct).toFixed(1)}% ${targetGapPct > 0 ? "slower" : "faster"} than ${TYPICAL_AI}'s`;
}

/**
 * A suggestion as the Coaching card shows it. A level is shown only for a measured or estimated basis that carries
 * one (never computed here); otherwise which way to move the level is the headline.
 */
export function suggestionView(s: AiLevelSuggestion, who: AiWho = { poss: "your" }, carName?: string | null): SuggestionView {
  const hasLevel = (s.basis === "measured" || s.basis === "estimate_other_tracks") && finite(s.level);
  const estimate = hasLevel && s.basis === "estimate_other_tracks";
  const range =
    hasLevel && !s.bound && s.range && finite(s.range[0]) && finite(s.range[1]) && s.range[0] !== s.range[1]
      ? `Range ${s.range[0]}–${s.range[1]}`
      : null;
  const conf = hasLevel ? s.confidence : null;
  const d = s.latest_level;
  const headline = hasLevel
    ? null
    : s.direction === "lower"
      ? `Lower than AI ${d}`
      : s.direction === "higher"
        ? `Higher than AI ${d}`
        : s.direction === "about_right"
          ? `AI ${d} looks about right`
          : null;
  return {
    kind: hasLevel ? "level" : "direction",
    keyLabel: suggestionKeyLabel(s.key, carName),
    level: hasLevel ? `${estimate && !s.bound ? "about " : ""}AI ${s.level}` : null,
    bound: hasLevel ? (s.bound === "at_least" ? "or higher" : s.bound === "at_most" ? "or lower" : null) : null,
    range,
    confidence: conf
      ? {
          word: conf,
          label: conf === "low" ? "Low confidence · rough estimate" : `${conf === "high" ? "High" : "Medium"} confidence`,
          tone: conf === "low" ? "warning" : "default",
        }
      : null,
    measured: hasLevel && s.basis === "measured",
    estimate,
    headline,
    text: suggestionSentence(s, who),
    note: s.note === "levels_disagree" ? "The results at different levels here do not line up yet, so no level is suggested." : null,
    direction: s.direction,
  };
}

/**
 * The Progress card's one sentence: the suggestion for the series on screen in words about the viewed driver, else a
 * plain description of the newest session; null without sessions (the card says so).
 */
export function aiSeriesSentence(view: Pick<AiSeriesView, "dots">, suggestion: AiLevelSuggestion | null, who: AiWho): string | null {
  if (!view.dots.length) return null;
  if (suggestion) return suggestionSentence(suggestion, who);
  const newest = view.dots[view.dots.length - 1]!;
  const plotted = [...view.dots].reverse().find((d) => d.gapPct != null && d.gapMs != null);
  if (!plotted) {
    return `No clean lap against the AI here yet: the typical AI car's best lap at AI ${newest.level} was ${lapTime(newest.aiRefMs)}.`;
  }
  const pct = pctWords(plotted.gapPct);
  return pct === "level"
    ? `At AI ${plotted.level} ${who.poss} best lap here was level with ${TYPICAL_AI}'s best lap.`
    : `At AI ${plotted.level} ${who.poss} best lap here was ${pct} than ${TYPICAL_AI}'s best lap.`;
}

const UNUSABLE_REASON: Readonly<Record<AiPaceUnusable["status"], string>> = {
  too_few_ai_cars: "too few clean AI laps were seen",
  unknown_difficulty: "the game did not report the AI difficulty",
  difficulty_changed: "the AI difficulty changed during the session",
};

/**
 * Sessions here that were raced against the AI but could not be compared, in words about the viewed driver ("Your
 * race here at AI difficulty 35 could not be compared: too few clean AI laps were seen."); null when there are none,
 * so "no races against the AI" is said only when it is true.
 */
export function aiUnusableSentence(unusable: readonly AiPaceUnusable[] | null | undefined, who: AiWho): string | null {
  const list = unusable ?? [];
  if (!list.length) return null;
  const Poss = who.Poss ?? capital(who.poss);
  const newest = list[list.length - 1]!;
  const reason =
    newest.status === "too_few_ai_cars" && newest.online
      ? "it was an online session with other players, and too few AI cars"
      : UNUSABLE_REASON[newest.status] ?? "it could not be compared";
  const what = (CATEGORY_WORDS[newest.session_category] ?? CATEGORY_WORDS.unknown).one;
  const level = finite(newest.ai_difficulty) ? ` at AI difficulty ${newest.ai_difficulty}` : "";
  if (list.length === 1) return `${Poss} ${what} here${level} could not be compared with the AI: ${reason}.`;
  return `${plural(list.length, "session")} here against the AI could not be compared; the newest${level}: ${reason}.`;
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
