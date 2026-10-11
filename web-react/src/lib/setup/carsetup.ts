// Car setup: pure helpers for Setup › Car setup (spec 7.3), ported from the Svelte reference web/src/lib/carsetup.ts
// and extended for the v2 page (the request as a sentence kept in the route query, rows against their range, the
// session comparison with changed rows first, experiments as Proposed → Running → Concluded). No React, no fetch:
// unit-tested in plain node (carsetup.test.ts).
//
// Honesty rules kept here: unknown is "-" (P5); a value pitwall derived keeps its mark, also in copied text; car
// formats, conditions and sessions are never silently substituted (servedAs mirrors recommend.recommend's order and
// returns null rather than another format or the other conditions); the catalogue caveat is shown verbatim.

import type {
  CarFormat,
  CarSetupCatalog,
  Combination,
  Conditions,
  Confidence,
  DiffRow,
  Direction,
  ExperimentStatus,
  NeedField,
  ParameterInfo,
  SelectionRule,
  SessionKind,
  SessionOption,
  SetupExperiment,
  SetupResult,
  SetupRow,
  SetupStyle,
  SkillLevel,
  SuggestedExperiment,
  Verdict,
} from "../endpoints/carsetup";
import { CAR_FORMATS, CONDITIONS, SESSION_KINDS, STYLES } from "../endpoints/carsetup";
import { MINUS, UNKNOWN } from "../format";

// ---------------------------------------------------------------------------------------------- labels
export const SESSION_LABEL: Record<SessionKind, string> = { race: "Race", qualifying: "Qualifying" };
export const CONDITIONS_LABEL: Record<Conditions, string> = { dry: "Dry", wet: "Wet" };
export const STYLE_LABEL: Record<SetupStyle, string> = { balanced: "Balanced", stable: "Stable", aggressive: "Aggressive" };
/** What each style means, in plain words (popover descriptions). */
export const STYLE_HINT: Record<SetupStyle, string> = {
  balanced: "The typical published setup",
  stable: "Calmer rear, easier to drive",
  aggressive: "Sharper, less forgiving",
};
export const SELECTION_LABEL: Record<SelectionRule, string> = {
  single_source: "one published setup",
  medoid: "the most typical of several published setups",
  derived: "derived by Pitwall from a published setup",
};
export const STATUS_LABEL: Record<ExperimentStatus, string> = {
  proposed: "Proposed",
  running: "Running",
  concluded: "Concluded",
  abandoned: "Abandoned",
};
export const VERDICT_LABEL: Record<Verdict, string> = {
  faster: "Faster",
  slower: "Slower",
  no_clear_difference: "No clear difference",
  inconclusive: "Inconclusive",
};
export const CONFIDENCE_LABEL: Record<Confidence, string> = { high: "High", medium: "Medium", low: "Low" };
/** What each confidence level means (catalogue rules, shown in the row sheet and the legend). */
export const CONFIDENCE_HINT: Record<Confidence, string> = {
  high: "Three or more current published setups, at least two thirds agree",
  medium: "At least two current published setups agree",
  low: "One setup, setups that disagree, or setups from before the latest handling patch",
};
export const DIRECTION_ARROW: Record<Direction, string> = { higher: "↑", lower: "↓", same: "=", unknown: "?" };
export const NEED_LABEL: Record<NeedField, string> = { car_format: "Car format", session: "Session", conditions: "Conditions" };

/** The style Pitwall starts a driver on when none is chosen (mirrors ``recommend.default_style``). */
export function defaultStyle(skill: SkillLevel | null | undefined): SetupStyle {
  return skill === "beginner" ? "stable" : "balanced";
}

/** "2025 car" / "2026 car" for the request sentence (the catalogue label is long); the label otherwise. */
export function formatShortLabel(id: CarFormat | null | undefined, cat?: CarSetupCatalog | null): string {
  if (!id) return UNKNOWN;
  const year = /(\d{4})$/.exec(id)?.[1];
  if (year) return `${year} car`;
  return cat?.formats.find((f) => f.id === id)?.label ?? id;
}

export function formatLabel(cat: CarSetupCatalog | null | undefined, id: CarFormat | null | undefined): string {
  if (!id) return UNKNOWN;
  return cat?.formats.find((f) => f.id === id)?.label ?? id;
}

export function trackLabel(cat: CarSetupCatalog | null | undefined, fmt: CarFormat | null, trackId: number): string {
  for (const f of cat?.formats ?? []) {
    if (fmt !== null && f.id !== fmt) continue;
    const t = f.tracks.find((x) => x.id === trackId);
    if (t) return t.name;
  }
  return `Track ${trackId}`;
}

// ---------------------------------------------------------------------------------------------- values and copy text
/** "10", "24.3 psi", "-": the menu value with its unit, as the driver types it into the game. */
export function valueText(r: { display: string; unit: string | null; value?: number | null }): string {
  if (r.value === null || r.display === "unknown" || r.display === "") return UNKNOWN;
  return r.unit ? `${r.display} ${r.unit}` : r.display;
}

/** A unit as shown next to a value ("deg" from the catalogue reads "°"); null stays null. */
export function unitText(u: string | null | undefined): string | null {
  if (!u) return null;
  return u === "deg" ? "°" : u;
}

/** " %", " psi", "°" (no space before a degree sign), "" for none. */
export function unitSuffix(u: string | null | undefined): string {
  const t = unitText(u);
  if (!t) return "";
  return t === "°" ? t : ` ${t}`;
}

/** The menu value without its unit, or null when unknown (SettingValue renders null as "-"). */
export function displayValue(r: { display: string; value: number | null }): string | null {
  return r.value === null || r.display === "unknown" || r.display === "" ? null : r.display;
}

/** A number in a parameter's menu format ("-3.50", "24.3 psi"). Unknown -> "-". */
export function paramValue(p: ParameterInfo | undefined, v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return UNKNOWN;
  const s = p ? v.toFixed(p.decimals) : String(v);
  return p?.unit ? `${s} ${p.unit}` : s;
}

/** A number in the parameter's menu format without its unit (range ends), real minus sign. */
export function fixed(p: Pick<ParameterInfo, "decimals"> | undefined, v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return UNKNOWN;
  const s = p ? v.toFixed(p.decimals) : String(v);
  return s.startsWith("-") ? `${MINUS}${s.slice(1)}` : s;
}

/** "Front Wing Aero: 10"; a value Pitwall derived keeps its mark in the copy. */
export function rowCopyLine(r: { label: string; display: string; unit: string | null; value: number | null; derived: boolean }): string {
  return `${r.label}: ${valueText(r)}${r.derived && r.value !== null ? "  [pitwall derived]" : ""}`;
}

/** "+1 step", "−2 steps", "+0.50 steps": how many menu clicks the recommendation is from yours. */
export function stepsText(steps: number | null | undefined): string {
  if (steps === null || steps === undefined || !Number.isFinite(steps)) return UNKNOWN;
  const whole = Math.abs(steps - Math.round(steps)) < 1e-9;
  const n = Math.abs(steps);
  const sign = steps > 0 ? "+" : steps < 0 ? MINUS : "±";
  return `${sign}${whole ? n.toFixed(0) : n.toFixed(2)} ${whole && Math.round(n) === 1 ? "step" : "steps"}`;
}

/** Rows grouped by menu section, sections and rows in the game's menu order. */
export function groupRows<R extends { group: string; order: number }>(rows: readonly R[], groupOrder: readonly string[] = []): { group: string; rows: R[] }[] {
  const sorted = [...rows].sort((a, b) => a.order - b.order);
  const names: string[] = [...groupOrder];
  for (const r of sorted) if (!names.includes(r.group)) names.push(r.group);
  return names
    .map((group) => ({ group, rows: sorted.filter((r) => r.group === group) }))
    .filter((g) => g.rows.length > 0);
}

export function setupHeading(res: Pick<SetupResult, "track_name" | "car_format" | "session" | "conditions" | "style">, cat: CarSetupCatalog | null | undefined): string {
  return [res.track_name, formatLabel(cat, res.car_format), SESSION_LABEL[res.session], CONDITIONS_LABEL[res.conditions], STYLE_LABEL[res.style]].join(" · ");
}

export function sectionCopyText(group: string, rows: readonly SetupRow[], heading?: string): string {
  const lines = heading ? [heading, group] : [group];
  for (const r of [...rows].sort((a, b) => a.order - b.order)) lines.push(rowCopyLine(r));
  return lines.join("\n");
}

/** The whole setup as plain text, one "Label: value" line per parameter, sections in menu order. */
export function setupCopyText(res: SetupResult, cat: CarSetupCatalog | null | undefined): string {
  const parts = [setupHeading(res, cat)];
  for (const g of groupRows(res.rows, res.groups)) parts.push(sectionCopyText(g.group, g.rows));
  return parts.join("\n\n");
}

// ---------------------------------------------------------------------------------------------- rows
export interface ConfidenceCounts {
  high: number;
  medium: number;
  low: number;
  /** rows no source gave a value for */
  unknown: number;
  derived: number;
}

export function confidenceCounts(rows: readonly SetupRow[]): ConfidenceCounts {
  const c: ConfidenceCounts = { high: 0, medium: 0, low: 0, unknown: 0, derived: 0 };
  for (const r of rows) {
    if (r.value === null) c.unknown++;
    else c[r.confidence]++;
    if (r.derived) c.derived++;
  }
  return c;
}

/** "14 high · 4 medium · 2 low" (zero counts left out; "-" when there are no rows). */
export function confidenceSummary(c: ConfidenceCounts): string {
  const parts: string[] = [];
  if (c.high) parts.push(`${c.high} high`);
  if (c.medium) parts.push(`${c.medium} medium`);
  if (c.low) parts.push(`${c.low} low`);
  if (c.unknown) parts.push(`${c.unknown} unknown`);
  return parts.length ? parts.join(" · ") : UNKNOWN;
}

/**
 * The chip on a setup row (spec 7.3: confidence / Derived / number of sources; mockup "3 sources"). High confidence
 * is the norm, so its chip only counts the sources; medium and low say so, low in the warning tone. Status words,
 * never timing colours. `label` is the full sentence for assistive tech.
 */
export function rowChip(r: Pick<SetupRow, "value" | "derived" | "sources" | "confidence">): { text: string; tone: "default" | "warning"; label: string } {
  if (r.value === null) return { text: "No source", tone: "warning", label: "No source gives this value" };
  if (r.derived) return { text: "Derived", tone: "default", label: `Derived by Pitwall, ${r.confidence} confidence` };
  const n = r.sources.length;
  const src = n === 1 ? "1 source" : `${n} sources`;
  const label = `${src}, ${r.confidence} confidence`;
  if (r.confidence === "high") return { text: src, tone: "default", label };
  return { text: `${CONFIDENCE_LABEL[r.confidence]} · ${src}`, tone: r.confidence === "low" ? "warning" : "default", label };
}

/** Number of distinct published setups behind a recommendation. */
export function setupCount(res: Pick<SetupResult, "setups">): number {
  return Object.keys(res.setups).length;
}

/** A skill level as a noun phrase: "a beginner", "an intermediate driver", "an advanced driver" (never the bare
 * adjective: "Style chosen for Alex, an advanced" read as a cut-off sentence). */
export function skillPhrase(skill: SkillLevel): string {
  return skill === "beginner" ? "a beginner" : `${/^[aeiou]/.test(skill) ? "an" : "a"} ${skill} driver`;
}

/** The style line under the request (spec 7.3): why this style, in words. */
export function styleNote(
  res: { style_reason: string; requested_style: SetupStyle } | null | undefined,
  explicit: boolean,
  driver: { name: string; skill: SkillLevel | null } | null,
): string {
  if (explicit) return "your choice";
  if (driver?.skill) return `chosen for ${driver.name}, ${skillPhrase(driver.skill)}`;
  if (driver) return `${driver.name}'s skill level is not set: balanced`;
  return res?.style_reason ?? "balanced until a driver is chosen";
}

// ---------------------------------------------------------------------------------------------- patches
/**
 * Was a cited setup made before the car format's latest handling patch? Follows ``build.is_current``: a stated game
 * version is compared with the patch version; without one, a full publication date before the patch day is "yes",
 * and a month-only date in the patch's month, or no date at all, is "maybe" (it cannot be told).
 */
export function predatesPatch(s: { patch: string | null; published: string | null }, p: { version: string; date: string } | null | undefined): "yes" | "maybe" | "no" {
  if (!p) return "no";
  if (s.patch) return patchOlder(s.patch, p.version) ? "yes" : "no";
  if (!s.published) return "maybe";
  if (s.published.length >= 10) return s.published.slice(0, 10) < p.date ? "yes" : "no";
  const month = p.date.slice(0, 7);
  return s.published < month ? "yes" : s.published === month ? "maybe" : "no";
}

/** True when game version ``a`` ("1.9") is older than ``b`` ("1.12"); false when either is unknown. */
export function patchOlder(a: string | null | undefined, b: string | null | undefined): boolean {
  if (!a || !b) return false;
  const pa = a.split(".").map(Number);
  const pb = b.split(".").map(Number);
  if (pa.some(Number.isNaN) || pb.some(Number.isNaN)) return false;
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const x = pa[i] ?? 0;
    const y = pb[i] ?? 0;
    if (x !== y) return x < y;
  }
  return false;
}

/** Cited setups newest first; a setup without a date last. */
export function sortedSetups<S extends { published: string | null }>(setups: Record<string, S>): S[] {
  return Object.values(setups).sort((a, b) => (b.published ?? "").localeCompare(a.published ?? ""));
}

// ---------------------------------------------------------------------------------------------- availability
export interface ComboQuery {
  car_format: CarFormat;
  track_id: number;
  session: SessionKind;
  conditions: Conditions;
  style: SetupStyle;
}

/**
 * Which catalogue key ``recommend.recommend`` would serve for a request, in its order: the exact key, balanced for a
 * missing style, then the other session's setup (labelled stand-ins). Never the other conditions or car format:
 * null means there is no recommendation (the API answers 404 with the alternatives).
 */
export function servedAs(av: readonly Combination[], q: ComboQuery): { session: SessionKind; style: SetupStyle } | null {
  const other: SessionKind = q.session === "qualifying" ? "race" : "qualifying";
  const attempts: [SessionKind, SetupStyle][] = [[q.session, q.style]];
  if (q.style !== "balanced") attempts.push([q.session, "balanced"]);
  attempts.push([other, q.style]);
  if (q.style !== "balanced") attempts.push([other, "balanced"]);
  for (const [session, style] of attempts) {
    const hit = av.some(
      (a) =>
        a.car_format === q.car_format &&
        a.track_id === q.track_id &&
        a.conditions === q.conditions &&
        a.session === session &&
        a.style === style,
    );
    if (hit) return { session, style };
  }
  return null;
}

/** A picker option's sub-label: "" when served as asked, what stands in for it, or "no setup". */
export function servedNote(av: readonly Combination[], q: ComboQuery): string {
  const s = servedAs(av, q);
  if (s === null) return "no setup";
  if (s.session !== q.session) return `${SESSION_LABEL[s.session].toLowerCase()} setup shown`;
  if (s.style !== q.style) return `${STYLE_LABEL[s.style].toLowerCase()} shown`;
  return "";
}

export function trackHasSetup(av: readonly Combination[], fmt: CarFormat, trackId: number): boolean {
  return av.some((a) => a.car_format === fmt && a.track_id === trackId);
}

/** Alternatives closest to what was asked first: same format, track, conditions, session, style. */
export function sortAlternatives(
  alts: readonly Combination[],
  want: { car_format?: CarFormat | null; track_id?: number | null; session?: SessionKind | null; conditions?: Conditions | null; style?: SetupStyle | null },
): Combination[] {
  const score = (a: Combination) =>
    (a.car_format === want.car_format ? 16 : 0) +
    (a.track_id === want.track_id ? 8 : 0) +
    (a.conditions === want.conditions ? 4 : 0) +
    (a.session === want.session ? 2 : 0) +
    (a.style === want.style ? 1 : 0);
  return [...alts].sort((a, b) => score(b) - score(a));
}

/** Short label for an alternative, naming only what differs from the current track and car format. */
export function comboLabel(c: Combination, cat: CarSetupCatalog | null | undefined, current: { car_format?: CarFormat | null; track_id?: number | null }): string {
  const parts: string[] = [];
  if (current.track_id !== c.track_id) parts.push(trackLabel(cat, c.car_format, c.track_id));
  if (current.car_format !== c.car_format) parts.push(formatShortLabel(c.car_format, cat));
  parts.push(CONDITIONS_LABEL[c.conditions], SESSION_LABEL[c.session], STYLE_LABEL[c.style]);
  return parts.join(" · ");
}

export function comboKey(c: Pick<Combination, "car_format" | "track_id" | "session" | "conditions" | "style">): string {
  return `${c.car_format}:${c.track_id}:${c.session}:${c.conditions}:${c.style}`;
}

// ---------------------------------------------------------------------------------------------- the request (route query)
/** `#/setup/car?format=&track=&session=&conditions=&style=&driver=` (spec 2.3). Every field may be missing. */
export interface SetupRequestQuery {
  format: CarFormat | null;
  track: number | null;
  session: SessionKind | null;
  conditions: Conditions | null;
  /** null = the driver's skill picks it */
  style: SetupStyle | null;
  /** null = the driver in the seat */
  driver: number | null;
}

function oneOf<T extends string>(list: readonly T[], v: string | null): T | null {
  return v !== null && (list as readonly string[]).includes(v) ? (v as T) : null;
}

function intOrNull(v: string | null): number | null {
  if (v === null || !/^\d+$/.test(v)) return null;
  const n = Number(v);
  return Number.isSafeInteger(n) ? n : null;
}

/** Parse the route query (invalid values are dropped, never guessed). */
export function parseSetupQuery(query: string | URLSearchParams): SetupRequestQuery {
  const q = typeof query === "string" ? new URLSearchParams(query) : query;
  return {
    format: oneOf(CAR_FORMATS, q.get("format")),
    track: intOrNull(q.get("track")),
    session: oneOf(SESSION_KINDS, q.get("session")),
    conditions: oneOf(CONDITIONS, q.get("conditions")),
    style: oneOf(STYLES, q.get("style")),
    driver: intOrNull(q.get("driver")),
  };
}

/** Values for router withQuery(), in the spec's order (unset ones are left out). */
export function setupQueryValues(r: Partial<SetupRequestQuery>): Record<string, string | number | null> {
  return {
    format: r.format ?? null,
    track: r.track ?? null,
    session: r.session ?? null,
    conditions: r.conditions ?? null,
    style: r.style ?? null,
    driver: r.driver ?? null,
  };
}

/** A complete request: what the page asks the API for. */
export interface ResolvedRequest {
  format: CarFormat;
  track: number;
  session: SessionKind;
  conditions: Conditions;
  style: SetupStyle | null;
}

/** EA track id from Pitwall's "f1:<id>" (null for other games, synthetic tracks and unknown). */
export function f1TrackId(trackId: string | null | undefined): number | null {
  if (!trackId || !trackId.startsWith("f1:")) return null;
  const tail = trackId.slice(3);
  return /^\d+$/.test(tail) ? Number(tail) : null;
}

/** Catalogue session for a stored session type (mirrors ``context.session_kind``; time trial -> qualifying). */
export function sessionKindOf(sessionType: string | null | undefined): SessionKind | null {
  if (sessionType === "race" || sessionType === "practice") return "race";
  if (sessionType === "qualifying" || sessionType === "time_trial") return "qualifying";
  return null;
}

/** Dry/wet from the game's weather (mirrors ``context.conditions_for``); unknown stays null. */
export function conditionsOf(weather: { condition?: string | null } | null | undefined): Conditions | null {
  const c = weather?.condition;
  if (c === "light_rain" || c === "heavy_rain" || c === "storm") return "wet";
  if (c === "clear" || c === "light_cloud" || c === "overcast") return "dry";
  return null;
}

function firstTrackWithSetup(cat: CarSetupCatalog, fmt: CarFormat): number | null {
  const f = cat.formats.find((x) => x.id === fmt);
  if (!f) return null;
  return f.tracks.find((t) => trackHasSetup(cat.available, fmt, t.id))?.id ?? f.tracks[0]?.id ?? null;
}

/**
 * Fill a request from the route query. Missing fields are seeded as the Svelte page did: the remembered car format
 * (else the first), and the track / session / weather of the latest real (not synthetic) F1 session when that track
 * is drivable with that format, else the first track that has a setup, race, dry. A track the format does not have
 * is replaced by the format's first track. Null when the catalogue has no format at all.
 */
export function resolveRequest(
  q: SetupRequestQuery,
  cat: CarSetupCatalog,
  sessions: readonly SessionOption[] = [],
  rememberedFormat: CarFormat | null = null,
): ResolvedRequest | null {
  const ids = cat.formats.map((f) => f.id);
  const format = (q.format && ids.includes(q.format) ? q.format : null) ?? (rememberedFormat && ids.includes(rememberedFormat) ? rememberedFormat : null) ?? ids[0];
  if (!format) return null;
  const f = cat.formats.find((x) => x.id === format);
  if (!f) return null;
  const latest = q.track === null ? sessions.find((s) => !s.synthetic && f1TrackId(s.track_id) !== null) : undefined;
  const lt = latest ? f1TrackId(latest.track_id) : null;
  const seedFromSession = latest !== undefined && lt !== null && f.tracks.some((t) => t.id === lt);
  let track = q.track !== null && f.tracks.some((t) => t.id === q.track) ? q.track : null;
  if (track === null) track = seedFromSession ? lt : firstTrackWithSetup(cat, format);
  if (track === null) return null;
  return {
    format,
    track,
    session: q.session ?? (seedFromSession && latest ? sessionKindOf(latest.session_type) : null) ?? "race",
    conditions: q.conditions ?? (seedFromSession && latest ? conditionsOf(latest.weather) : null) ?? "dry",
    style: q.style,
  };
}

/** Whether the query already names everything resolveRequest filled in (else the page rewrites the URL once). */
export function queryIsComplete(q: SetupRequestQuery, r: ResolvedRequest): boolean {
  return q.format === r.format && q.track === r.track && q.session === r.session && q.conditions === r.conditions;
}

// ---------------------------------------------------------------------------------------------- remembered format
export const FORMAT_KEY = "pitwall-carsetup-format"; // shared with the Svelte page

export function storedFormat(storage: Pick<Storage, "getItem"> | null | undefined = safeLocalStorage()): CarFormat | null {
  try {
    return oneOf(CAR_FORMATS, storage?.getItem(FORMAT_KEY) ?? null);
  } catch {
    return null;
  }
}

export function rememberFormat(v: CarFormat, storage: Pick<Storage, "setItem"> | null | undefined = safeLocalStorage()): void {
  try {
    storage?.setItem(FORMAT_KEY, v);
  } catch {
    /* storage unavailable: the first format is used next time */
  }
}

function safeLocalStorage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------------------------- sessions
export function sessionTypeLabel(t: string | null | undefined): string {
  if (!t) return "Session";
  const s = t.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** "11 Oct 2026, 14:20" in the device's locale; "-" when unknown. */
export function when(unix: number | null | undefined): string {
  return unix ? new Date(unix * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : UNKNOWN;
}

/** "Silverstone · Race · 11 Oct 2026, 14:20 · James" (the synthetic tier is shown as a chip next to it). */
export function sessionLabel(s: Pick<SessionOption, "track_name" | "track_id" | "session_type" | "session_type_raw" | "started_unix"> & { driver_name?: string | null }): string {
  const parts = [s.track_name ?? s.track_id ?? "Unknown track", sessionTypeLabel(s.session_type_raw ?? s.session_type), when(s.started_unix)];
  if (s.driver_name) parts.push(s.driver_name);
  return parts.join(" · ");
}

/** Sessions the car setup catalogue covers (its game), newest first as the API sends them. */
export function setupSessions(sessions: readonly SessionOption[], game: string | null | undefined): SessionOption[] {
  return game ? sessions.filter((s) => s.game === game) : [];
}

/**
 * "Use my latest session" (spec 7.3): the newest real session of the catalogue's game for this driver, else the
 * newest real one of anyone; never a synthetic one unless nothing else exists (it is labelled where shown).
 */
export function latestSessionFor(
  sessions: readonly SessionOption[],
  game: string | null | undefined,
  driverId: number | null,
  /** Prefer sessions at this EA track id (the track on screen), falling back to any track. */
  trackId: number | null = null,
): SessionOption | null {
  if (trackId !== null) {
    const here = setupSessions(sessions, game).filter((s) => f1TrackId(s.track_id) === trackId && !s.synthetic);
    const hit = (driverId !== null ? here.find((s) => s.driver_id === driverId) : undefined) ?? here[0];
    if (hit) return hit;
  }
  const mine = setupSessions(sessions, game);
  const real = mine.filter((s) => !s.synthetic);
  return (
    (driverId !== null ? real.find((s) => s.driver_id === driverId) : undefined) ??
    real[0] ??
    mine[0] ??
    null
  );
}

// ---------------------------------------------------------------------------------------------- your setup vs recommended
/** A row the recommendation changes (or one outside the format's confirmed range). */
export function isChanged(r: Pick<DiffRow, "direction" | "in_range">): boolean {
  return r.direction === "higher" || r.direction === "lower" || r.in_range === false;
}

/** Spec 7.3: changed rows first, each part in the game's menu order. */
export function changedFirst<R extends Pick<DiffRow, "direction" | "in_range" | "order">>(rows: readonly R[]): R[] {
  return [...rows].sort((a, b) => Number(isChanged(b)) - Number(isChanged(a)) || a.order - b.order);
}

/** "+7", "−15 %", "-" : recommended minus yours in the parameter's unit. */
export function differenceText(r: Pick<DiffRow, "delta" | "unit" | "direction">, decimals = 0): string {
  if (r.delta === null || !Number.isFinite(r.delta) || r.direction === "unknown") return UNKNOWN;
  if (r.direction === "same" || Number(Math.abs(r.delta).toFixed(decimals)) === 0) return "Same";
  const n = Math.abs(r.delta).toFixed(decimals);
  return `${r.delta > 0 ? "+" : MINUS}${n}${unitSuffix(r.unit)}`;
}

/** "Pitwall cannot tell the car format and session from the game" lists: "a", "a or b", "a, b or c". */
export function listText(xs: readonly string[]): string {
  return xs.length <= 1 ? (xs[0] ?? "") : `${xs.slice(0, -1).join(", ")} or ${xs[xs.length - 1]}`;
}

// ---------------------------------------------------------------------------------------------- experiments
/** Pro Stepper position for Proposed → Running → Concluded (a concluded experiment shows every step complete). */
export function experimentStep(e: Pick<SetupExperiment, "status" | "after_session_id">): number {
  switch (e.status) {
    case "proposed":
      return 0;
    case "running":
      return 1;
    case "concluded":
      return 3;
    case "abandoned":
      return e.after_session_id ? 1 : 0;
  }
}

export function isOpenExperiment(e: Pick<SetupExperiment, "status">): boolean {
  return e.status === "proposed" || e.status === "running";
}

/** Open experiments first (newest first), then the rest newest first. */
export function sortExperiments<E extends Pick<SetupExperiment, "status" | "created_unix">>(list: readonly E[]): E[] {
  return [...list].sort((a, b) => Number(isOpenExperiment(b)) - Number(isOpenExperiment(a)) || b.created_unix - a.created_unix);
}

/** Sessions the backend accepts as the after session: same game, track and (when both are known) car, driven later. */
export function afterCandidates(exp: SetupExperiment, sessions: readonly SessionOption[]): SessionOption[] {
  const before = sessions.find((s) => s.id === exp.before_session_id);
  return sessions.filter(
    (s) =>
      s.id !== exp.before_session_id &&
      s.game === exp.game &&
      s.track_id === exp.track_id &&
      (!exp.car_id || !s.car_id || s.car_id === exp.car_id) &&
      (before === undefined || s.started_unix > before.started_unix),
  );
}

/** The after session to link: the one picked, else the linked one, else the newest candidate. */
export function afterFor(exp: SetupExperiment, sessions: readonly SessionOption[], picked: string | null | undefined): string | null {
  const cands = afterCandidates(exp, sessions);
  if (picked && cands.some((c) => c.id === picked)) return picked;
  return exp.after_session_id ?? cands[0]?.id ?? null;
}

/** Is this suggestion already an open experiment for the session? */
export function alreadyTesting(list: readonly SetupExperiment[], x: SuggestedExperiment, sid: string): boolean {
  return list.some(
    (e) => isOpenExperiment(e) && e.before_session_id === sid && e.parameter === x.key && e.to_value !== null && Math.abs(e.to_value - x.to_value) < 1e-6,
  );
}

export function mean(xs: readonly number[] | null | undefined): number | null {
  return xs && xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
}

/** "1.23 %" or "-". */
export function pct(v: number | null | undefined, digits = 2): string {
  return v === null || v === undefined || !Number.isFinite(v) ? UNKNOWN : `${v.toFixed(digits)} %`;
}

/** Parse a number typed into the experiment form ("−3.5", "-3.5", "3,5"); null when it is not a number. */
export function parseNumber(text: string): number | null {
  const t = text.trim().replace(/−/g, "-").replace(",", ".");
  if (!/^-?\d+(\.\d+)?$/.test(t)) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

/**
 * Check a new value for a parameter against the format's range and step (the backend re-checks; this only saves a
 * round trip). Returns the message to show, or null when fine.
 */
export function valueProblem(p: ParameterInfo | undefined, fmt: CarFormat | null, v: number | null, from: number | null): string | null {
  if (v === null) return "Enter a number";
  if (from !== null && Math.abs(v - from) < 1e-9) return "That is the value you already have";
  const r = p && fmt ? p.ranges[fmt] : undefined;
  if (!r) return null;
  if ((r.min_confirmed && v < r.min - 1e-9) || (r.max_confirmed && v > r.max + 1e-9)) {
    return `Outside the menu range ${fixed(p, r.min)} to ${fixed(p, r.max)}`;
  }
  return null;
}

/** The parameter's value in a session's stored setup (a number, or its {value} as the API sends it), or null. */
export function setupValue(params: Record<string, unknown> | null | undefined, key: string): number | null {
  const v = params?.[key];
  // feat/technique: the stored setup sends {key, value, unit, ...} per parameter (GET /api/carsetup/sessions/{sid}
  // `setup.params`), so "yours" read "-" in the experiment modal; plain numbers still work.
  const n = typeof v === "object" && v !== null && "value" in v ? (v as { value: unknown }).value : v;
  return typeof n === "number" && Number.isFinite(n) ? n : null;
}
