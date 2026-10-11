// Setup › Validation view model (lane validate, spec 12.3). Pure functions: grouping, status chips, progress, the
// run's context line, number formatting and the report's rows. Tested in plain node (view.test.ts).
//
// Copy rules (design spec 9.6): unknown is "-", the minus sign is U+2212, distances "285 m", times "0.09 s", sentence
// case. Status chips use status colours only (success / warning / danger / default), never the timing colours. The UI
// adds no advice: steps, prompts and rules are the catalogue's words; the words here only name states and numbers.

import { MINUS, UNKNOWN, grouped, withMinus } from "../format";
import type {
  AutoVerdict,
  Catalog,
  CatalogItem,
  Check,
  CheckStatus,
  ClientSummary,
  DriverMark,
  DriverVerdict,
  EvidenceTier,
  InputPhaseId,
  InputPhaseRecord,
  ItemGroup,
  ItemResult,
  ItemState,
  ReportItem,
  Run,
  RunContext,
  RunStatus,
  RunSummary,
  ServerInfo,
  ValidationReport,
} from "../endpoints/validation";

export type ChipTone = "default" | "accent" | "success" | "warning" | "danger";

export interface ChipSpec {
  label: string;
  tone: ChipTone;
  /** Longer words for screen readers. */
  title?: string;
}

// ------------------------------------------------------------------------------------------------ chips
export const RESULT_CHIP: Record<ItemResult, ChipSpec> = {
  pass: { label: "Pass", tone: "success" },
  fail: { label: "Fail", tone: "danger" },
  // "To check", not "Review": Review is a tab of the app
  needs_review: { label: "To check", tone: "warning", title: "needs a look before it counts" },
  not_run: { label: "Not yet", tone: "default" },
  skipped: { label: "Skipped", tone: "default" },
};

/** A finished run's report: a test without a result was not run (not "not yet"). */
export const REPORT_RESULT_CHIP: Record<ItemResult, ChipSpec> = { ...RESULT_CHIP, not_run: { label: "Not run", tone: "default" } };

/** What Pitwall saw, in plain words (never the API's enum). */
export const AUTO_CHIP: Record<AutoVerdict, ChipSpec> = {
  pass: { label: "Looks good", tone: "success" },
  fail: { label: "Problem seen", tone: "danger" },
  inconclusive: { label: "Not enough yet", tone: "warning" },
  no_evidence: { label: "Not seen yet", tone: "default" },
  not_live: { label: "Not live data", tone: "warning", title: "only replayed, generated or relayed data: it does not count" },
  unavailable: { label: "Not available", tone: "default" },
  driver_only: { label: "Your call", tone: "default", title: "only the driver can judge this one" },
};

/** The report's words for what Pitwall saw: a finished run saw nothing (not "not seen yet"). */
export const REPORT_AUTO_CHIP: Record<AutoVerdict, ChipSpec> = { ...AUTO_CHIP, no_evidence: { label: "Nothing seen", tone: "default" } };

export const CHECK_CHIP: Record<CheckStatus, ChipSpec> = {
  met: { label: "Met", tone: "success" },
  not_met: { label: "Not met", tone: "danger" },
  unknown: { label: UNKNOWN, tone: "default", title: "not measured yet" },
};

/** A check not met while the test is going: not a failure yet (red only once Pitwall sees a problem). */
const CHECK_NOT_YET: ChipSpec = { label: "Not yet", tone: "default", title: "not met so far" };
/** A check not met on a test that otherwise passes (e.g. calls may delay braking): a warning to look at. */
const CHECK_TO_CHECK: ChipSpec = { label: "To check", tone: "warning", title: "the test passes, but this needs a look" };

export const CURRENT_CHIP: ChipSpec = { label: "Now", tone: "accent", title: "the test you are on" };

export const VERDICT_WORD: Record<DriverVerdict, string> = { worked: "Worked", didnt: "Didn't work" };

export const RUN_STATUS_WORD: Record<RunStatus, string> = { active: "In progress", finished: "Finished", aborted: "Abandoned" };

export const GROUP_TITLE: Record<ItemGroup, string> = {
  dashboard: "Dashboard at the wheel",
  radio: "Radio",
  coaching: "Coaching",
  games: "Games",
  drivers: "Drivers",
};

const GROUP_ORDER: ItemGroup[] = ["dashboard", "radio", "coaching", "games", "drivers"];

// ------------------------------------------------------------------------------------------------ labels
const GAME_LABEL: Record<string, string> = {
  f1_25: "F1 25",
  f1_24: "F1 24",
  f1: "F1",
  gt7: "Gran Turismo 7",
  ac: "Assetto Corsa",
  forza: "Forza",
};

const PLATFORM_LABEL: Record<string, string> = { ps5: "PS5", ps4: "PS4", pc: "PC", xbox: "Xbox", steam: "PC" };

const DEVICE_LABEL: Record<ClientSummary["device"], string> = { ipad: "iPad", iphone: "iPhone", android: "Android", browser: "Browser" };

const MIC_LABEL: Record<NonNullable<ClientSummary["audio_input_kind"]>, string | null> = {
  airpods: "AirPod",
  bluetooth: "Bluetooth",
  built_in: "built-in microphone",
  wired: "wired microphone",
  unknown: null,
};

export function gameLabel(id: string | null | undefined): string | null {
  if (!id) return null;
  return GAME_LABEL[id] ?? id;
}

export function platformLabel(id: string | null | undefined): string | null {
  if (!id) return null;
  return PLATFORM_LABEL[id.toLowerCase()] ?? id;
}

export function deviceLabel(d: ClientSummary["device"]): string {
  return DEVICE_LABEL[d] ?? d;
}

/** A driver by name when this device knows it, else "Driver #2" (reports never carry names). */
export function driverLabel(id: number | null | undefined, names: ReadonlyMap<number, string> = new Map()): string {
  if (id === null || id === undefined) return "No driver";
  return names.get(id) ?? `Driver #${id}`;
}

// ------------------------------------------------------------------------------------------------ numbers
function finite(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/** "3.1", "−3.1", "+1.8" (sign only when asked). */
function fixed(v: number, digits: number, sign: boolean): string {
  const abs = Math.abs(v).toFixed(digits);
  if (Number(abs) === 0) return abs;
  if (v < 0) return `${MINUS}${abs}`;
  return sign ? `+${abs}` : abs;
}

/** Signed metres along the lap: "−3.1 m", "+2.1 m". */
export function signedMetres(v: number | null | undefined, digits = 1): string {
  return finite(v) ? `${fixed(v, digits, true)} m` : UNKNOWN;
}

/** Seconds: "0.09 s", "21.4 s"; signed when asked. */
export function seconds(v: number | null | undefined, digits = 2, sign = false): string {
  return finite(v) ? `${fixed(v, digits, sign)} s` : UNKNOWN;
}

/** Milliseconds as seconds: 1840 -> "1.84 s", 21400 -> "21.4 s". */
export function msAsSeconds(ms: number | null | undefined): string {
  if (!finite(ms)) return UNKNOWN;
  const s = ms / 1000;
  return seconds(s, Math.abs(s) < 10 ? 2 : 1);
}

/** A duration: "45 s", "5:00", "21:52", "1:02:05". */
export function duration(s: number | null | undefined): string {
  if (!finite(s) || s < 0) return UNKNOWN;
  const t = Math.round(s);
  if (t < 60) return `${t} s`;
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const sec = String(t % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

export function percent(share: number | null | undefined): string {
  return finite(share) ? `${Math.round(share * 100)} %` : UNKNOWN;
}

/** A plain number from the API: integers grouped, decimals with up to 2 digits, the minus sign U+2212. */
export function plainNumber(v: number | null | undefined): string {
  if (!finite(v)) return UNKNOWN;
  if (Number.isInteger(v)) return grouped(v);
  return withMinus(String(Math.round(v * 100) / 100));
}

/** A table cell from the report (numbers with the minus sign, API words in plain words, null as "-"). */
export function cellText(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return UNKNOWN;
  if (typeof v === "number") return plainNumber(v);
  return valueWords(v);
}

const DATE_FMT: Intl.DateTimeFormatOptions = { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" };

/** "12 Oct 2026, 19:30" (this device's time zone). */
export function dateTime(unix: number | null | undefined): string {
  if (!finite(unix) || unix <= 0) return UNKNOWN;
  try {
    return new Date(unix * 1000).toLocaleString("en-GB", DATE_FMT);
  } catch {
    return new Date(unix * 1000).toISOString().slice(0, 16).replace("T", " ");
  }
}

/** "19:41". */
export function timeOfDay(unix: number | null | undefined): string {
  if (!finite(unix) || unix <= 0) return UNKNOWN;
  try {
    return new Date(unix * 1000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  } catch {
    return UNKNOWN;
  }
}

// ------------------------------------------------------------------------------------------------ metrics
const METRIC_LABEL: Record<string, string> = {
  // braking calls
  fired: "Calls fired",
  sent: "Calls sent",
  dropped_delivery: "Calls lost in delivery",
  dropped_expected: "Calls held back on purpose",
  measured: "Measured",
  late: "Late calls",
  early: "Early calls",
  zones: "Braking zones",
  median_heard_vs_point_m: "Word vs your point (median)",
  median_latency_ms: "Delay to your ear (median)",
  median_onset_vs_point_m: "You braked vs point (median)",
  median_onset_vs_word_s: "Word to your braking (median)",
  baseline_median_onset_vs_point_m: "Calls off: braked vs point (median)",
  heads_up_fired: "Heads-up calls",
  // push-to-talk
  roundtrips: "Questions answered",
  screen: "Screen button",
  wheel: "Wheel button",
  say_again: "\"Say again\"",
  median_fast_to_playback_ms: "Quick answers (median)",
  max_llm_to_playback_ms: "Slowest engineer answer",
  n_marked: "Transcripts checked",
  n_wrong: "Heard wrong",
  // screen
  wake_on_streak_s: "Screen kept on (longest)",
  gaps: "Gaps in reports",
  hidden_transitions: "Page hidden",
  reloads: "Page reloads",
  safari_version: "Safari",
  // driver switch
  switches: "Switches",
  ok: "Clean switches",
  problems: "Problems",
  // speak windows
  overlap: "Over braking or a corner",
  tight: "Close to braking",
  clean: "On a straight",
  // voice
  kokoro_messages: "Natural-voice messages",
  fallback_share: "Fallback voice",
  restarts: "Voice restarts",
  synth_p95_ms: "Voice synthesis (p95)",
};

/** Metric keys shown as headline numbers per test, in order (the rest stay in the report). */
const HEADLINE: Record<string, string[]> = {
  cues_timing: ["measured", "late", "median_heard_vs_point_m", "median_onset_vs_word_s"],
  radio_ptt: ["roundtrips", "say_again", "median_fast_to_playback_ms", "max_llm_to_playback_ms"],
  ipad_home_screen: ["wake_on_streak_s", "hidden_transitions", "gaps"],
  radio_speak_windows: ["measured", "overlap", "tight"],
  radio_kokoro: ["kokoro_messages", "fallback_share", "restarts"],
};

const UNIT_SUFFIX = /_(ms|m|s|kph|share|hz|pct)$/;

/** "median_latency_ms" -> "Median latency" (for keys this version does not know). */
export function humaniseKey(key: string): string {
  const words = key.replace(UNIT_SUFFIX, "").replace(/_/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : key;
}

export function metricLabel(key: string): string {
  return METRIC_LABEL[key] ?? humaniseKey(key);
}

/** A metric value in words by its key's unit: metres signed when it compares two points, durations as m:ss. */
export function metricValue(key: string, v: number | string | null | undefined): string {
  if (v === null || v === undefined) return UNKNOWN;
  if (typeof v === "string") return v.trim() ? valueWords(v) : UNKNOWN;
  if (!finite(v)) return UNKNOWN;
  const compares = /_vs_|_to_|onset_vs|heard_vs/.test(key);
  if (key.endsWith("_ms")) return msAsSeconds(v);
  if (key.endsWith("_m")) return compares ? signedMetres(v) : `${plainNumber(Math.round(v))} m`;
  if (key.endsWith("_s")) return /streak|duration|window/.test(key) || v >= 60 ? duration(v) : seconds(v, 2, compares);
  if (key.endsWith("_share") || key.endsWith("_pct")) return key.endsWith("_pct") ? `${Math.round(v)} %` : percent(v);
  if (key.endsWith("_kph")) return `${Math.round(v)} km/h`;
  if (key.endsWith("_hz")) return `${plainNumber(v)} Hz`;
  return plainNumber(v);
}

export interface MetricView {
  key: string;
  label: string;
  value: string;
}

/** Up to 4 headline numbers for a test: its known keys first, else the first numeric metrics. */
export function headlineMetrics(itemId: string, metrics: Record<string, number | string | null>, max = 4): MetricView[] {
  const keys = (HEADLINE[itemId] ?? []).filter((k) => k in metrics);
  const rest = Object.keys(metrics).filter((k) => !keys.includes(k) && typeof metrics[k] === "number");
  return [...keys, ...(keys.length ? [] : rest)].slice(0, max).map((k) => ({ key: k, label: metricLabel(k), value: metricValue(k, metrics[k]) }));
}

/** Every metric in words (the report's detail). */
export function allMetrics(metrics: Record<string, number | string | null>): MetricView[] {
  return Object.keys(metrics).map((k) => ({ key: k, label: metricLabel(k), value: metricValue(k, metrics[k]) }));
}

/** A reason from the backend, as written, with "≥" / "≤" and the minus sign (never reworded). */
export function reasonText(r: string): string {
  return r
    .replace(/>=\s?/g, "≥ ")
    .replace(/<=\s?/g, "≤ ")
    .replace(/(^|[\s([])-(?=\d)/g, `$1${MINUS}`);
}

export interface CheckView {
  id: string;
  label: string;
  value: string;
  target: string | null;
  heuristic: boolean;
  chip: ChipSpec;
}

/** API words a check may carry as its value or target, in plain words (anything else is shown as given). */
const VALUE_WORDS: Record<string, string> = {
  tailscale_https: "Tailscale (HTTPS)",
  https: "HTTPS",
  localhost: "this Mac",
  lan_http: "LAN (plain HTTP)",
  airpods: "AirPod",
  bluetooth: "Bluetooth",
  built_in: "built-in microphone",
  wired: "wired microphone",
  ipad: "iPad",
  iphone: "iPhone",
  android: "Android",
  browser: "a browser",
  server: "this Mac's voice",
  device: "the iPad's voice",
  full_lap: "measured from a full lap",
  estimate: "estimated",
  // evidence tiers
  live: "live",
  recorded: "replay",
  synthetic: "generated",
  loopback: "sent from this Mac",
};

/** API words in plain words; ">=" / "<=" as "≥" / "≤"; a hyphen-minus before a number as the minus sign (ranges such
 * as "70-85" are left alone). */
export function valueWords(v: string): string {
  const w = VALUE_WORDS[v.trim()];
  if (w) return w;
  return v
    .replace(/>=\s?/g, "≥ ")
    .replace(/<=\s?/g, "≤ ")
    .replace(/(^|[\s([])-(?=\d)/g, `$1${MINUS}`);
}

/** A check in words. ``verdict``: the live test's verdict (the step card); the report passes none and keeps "Not met". */
export function checkView(c: Check, verdict: AutoVerdict | null = null): CheckView {
  let chip = CHECK_CHIP[c.status] ?? CHECK_CHIP.unknown;
  if (c.status === "not_met" && verdict !== null && verdict !== "fail") chip = verdict === "pass" ? CHECK_TO_CHECK : CHECK_NOT_YET;
  return {
    id: c.id,
    label: c.label,
    value: c.value === null || c.value === "" ? UNKNOWN : valueWords(c.value),
    target: c.target ? valueWords(c.target) : null,
    heuristic: c.heuristic,
    chip,
  };
}

/** The backend's "this data is from a replay…" reason, said by the warning above the checks instead. */
const TIER_REASON = /^(This data is from a replay|This data is synthetic|This data came from a recording|Telemetry was not live)/;

/** The reasons to list under the checks: without the not-live reason when its warning already shows. */
export function shownReasons(auto: Pick<ItemState["auto"], "verdict" | "reasons">): string[] {
  return auto.verdict === "not_live" ? auto.reasons.filter((r) => !TIER_REASON.test(r)) : auto.reasons;
}

// ------------------------------------------------------------------------------------------------ the checklist
export function catalogById(catalog: Pick<Catalog, "items">): Map<string, CatalogItem> {
  return new Map(catalog.items.map((i) => [i.id, i]));
}

export function groupTitle(catalog: Pick<Catalog, "groups"> | null, g: ItemGroup): string {
  return catalog?.groups.find((x) => x.id === g)?.title ?? GROUP_TITLE[g] ?? g;
}

export interface ListRow {
  id: string;
  title: string;
  group: ItemGroup;
  status: ItemState["status"];
  result: ItemResult;
  current: boolean;
  optional: boolean;
  chip: ChipSpec;
}

export interface ListGroup {
  id: ItemGroup;
  title: string;
  rows: ListRow[];
}

/** The chip on a test's row: "Now" for the current test, else its result. */
export function rowChip(state: Pick<ItemState, "status" | "result">, current: boolean): ChipSpec {
  if (current) return CURRENT_CHIP;
  if (state.status === "skipped") return RESULT_CHIP.skipped;
  return RESULT_CHIP[state.result] ?? RESULT_CHIP.not_run;
}

/** The run's tests grouped like the catalogue (group order, then catalogue order). Unknown ids keep their place. */
export function checklist(catalog: Catalog | null, run: Pick<Run, "items" | "current_item" | "selected_items">): ListGroup[] {
  const byId = catalog ? catalogById(catalog) : new Map<string, CatalogItem>();
  const order = new Map((catalog?.items ?? []).map((i, k) => [i.id, k]));
  const states = new Map(run.items.map((s) => [s.id, s]));
  const ids = run.selected_items.length ? run.selected_items : run.items.map((s) => s.id);
  const rows: ListRow[] = [];
  for (const id of ids) {
    const s = states.get(id);
    if (!s) continue;
    const c = byId.get(id);
    rows.push({
      id,
      title: c?.title ?? humaniseKey(id),
      group: c?.group ?? "dashboard",
      status: s.status,
      result: s.result,
      current: run.current_item === id,
      optional: c?.optional ?? false,
      chip: rowChip(s, run.current_item === id),
    });
  }
  rows.sort((a, b) => (order.get(a.id) ?? 1e6) - (order.get(b.id) ?? 1e6));
  const groups: ListGroup[] = [];
  for (const g of GROUP_ORDER) {
    const r = rows.filter((x) => x.group === g);
    if (r.length) groups.push({ id: g, title: groupTitle(catalog, g), rows: r });
  }
  return groups;
}

/** The run's tests in checklist order (Previous / Next follow it). */
export function orderedIds(groups: ListGroup[]): string[] {
  return groups.flatMap((g) => g.rows.map((r) => r.id));
}

export function neighbourId(ids: string[], id: string | null, step: -1 | 1): string | null {
  if (id === null) return ids[0] ?? null;
  const k = ids.indexOf(id);
  if (k < 0) return null;
  return ids[k + step] ?? null;
}

/** "4 of 11 done" (done = marked or skipped, or finished by Next). */
export function progress(run: Pick<Run, "items">): { done: number; total: number; text: string } {
  const total = run.items.length;
  const done = run.items.filter((s) => s.status === "done" || s.status === "skipped" || s.marks.length > 0).length;
  return { done, total, text: `${done} of ${total} done` };
}

/** Default selection for a new run: every available test that is not optional (spec 11). */
export function defaultSelection(catalog: Catalog): Record<string, boolean> {
  return Object.fromEntries(catalog.items.map((i) => [i.id, i.available && !i.optional]));
}

export function selectedIds(catalog: Catalog, sel: Record<string, boolean>): string[] {
  return catalog.items.filter((i) => i.available && sel[i.id]).map((i) => i.id);
}

/** "about 85 min" for the selected tests. */
export function minutesText(catalog: Catalog, ids: string[]): string {
  const m = catalog.items.filter((i) => ids.includes(i.id)).reduce((a, i) => a + (finite(i.est_minutes) ? i.est_minutes : 0), 0);
  if (m <= 0) return UNKNOWN;
  if (m < 90) return `about ${Math.round(m)} min`;
  const h = Math.floor(m / 60);
  const r = Math.round((m % 60) / 5) * 5;
  return r ? `about ${h} h ${r} min` : `about ${h} h`;
}

// ------------------------------------------------------------------------------------------------ run context
/** The run bar's telemetry chip. Data arriving that is not live from a console (a replay, generated, sent from this Mac)
 * is never a green "Live": it sits next to a warning that it does not count. */
export function telemetryChip(t: RunContext["telemetry"], tier: EvidenceTier = "live"): ChipSpec {
  if (t === "live" && tier !== "live") return { label: "Data arriving · not counted", tone: "warning", title: "telemetry arrives, but not live from a console" };
  if (t === "live") return { label: "Live", tone: "success", title: "telemetry is arriving" };
  if (t === "stale") return { label: "Stale", tone: "warning", title: "telemetry stopped a moment ago" };
  return { label: "No telemetry", tone: "default" };
}

const TIER_NOTICE: Record<Exclude<EvidenceTier, "live">, string> = {
  recorded: "This session is a replay: it is shown but does not count.",
  synthetic: "This is generated test data (synthetic): it is shown but does not count.",
  loopback: "This data is a recording sent from this Mac: it is shown but does not count.",
  unknown: "Pitwall cannot tell where this data comes from: it does not count until it arrives live from the console.",
};

/** The warning above the checklist while the data is not live from a console (null when it is, or when there is none). */
export function tierNotice(ctx: Pick<RunContext, "telemetry" | "tier">): string | null {
  if (ctx.telemetry === "no_data" || ctx.tier === "live") return null;
  return TIER_NOTICE[ctx.tier] ?? TIER_NOTICE.unknown;
}

/** The warning on a test whose evidence is all from non-live data. */
export function notLiveNotice(auto: Pick<ItemState["auto"], "verdict" | "tier">): string | null {
  if (auto.verdict !== "not_live") return null;
  const t = auto.tier && auto.tier !== "live" ? auto.tier : "unknown";
  const what: Record<Exclude<EvidenceTier, "live">, string> = {
    recorded: "a replay",
    synthetic: "generated test data",
    loopback: "a recording sent from this Mac",
    unknown: "data Pitwall cannot place",
  };
  return `Pitwall only saw this test in ${what[t]}: it is shown but does not count.`;
}

/** The radio part of the run bar: "Radio: iPad (AirPod)", "Radio: not connected". */
export function radioLine(run: Pick<Run, "clients" | "context">): string {
  const live = run.clients.filter((c) => c.radio && c.radio.phase === "live");
  const pick = live.find((c) => c.device === "ipad") ?? live[0];
  if (pick) {
    const mic = pick.audio_input_kind ? MIC_LABEL[pick.audio_input_kind] : null;
    return `Radio: ${deviceLabel(pick.device)}${mic ? ` (${mic})` : ""}`;
  }
  if (run.context.radio_clients > 0) return `Radio: ${run.context.radio_clients} connected`;
  return "Radio: not connected";
}

/** "F1 25 · PS5 · Austria · James · Radio: iPad (AirPod)". Unknown parts are left out, never guessed. */
export function contextLine(run: Pick<Run, "clients" | "context">, names?: ReadonlyMap<number, string>): string {
  const c = run.context;
  const parts = [gameLabel(c.game), platformLabel(c.platform), c.track, c.driver_id !== null ? driverLabel(c.driver_id, names) : null];
  if (!c.game && c.telemetry === "no_data") parts.unshift("No game data yet");
  return [...parts.filter((p): p is string => !!p), radioLine(run)].join(" · ");
}

// ------------------------------------------------------------------------------------------------ marks
/** The mark this driver gave (per-driver tests keep one each); for other tests the newest mark. */
export function markFor(state: Pick<ItemState, "marks">, driverId: number | null, perDriver: boolean): DriverMark | null {
  if (!perDriver) return state.marks.at(-1) ?? null;
  for (let k = state.marks.length - 1; k >= 0; k -= 1) {
    const m = state.marks[k];
    if (m && m.driver_id === driverId) return m;
  }
  return null;
}

/** Other drivers' marks on a per-driver test (newest per driver). */
export function otherMarks(state: Pick<ItemState, "marks">, driverId: number | null): DriverMark[] {
  const seen = new Map<number | null, DriverMark>();
  for (const m of state.marks) if (m.driver_id !== driverId) seen.set(m.driver_id, m);
  return [...seen.values()];
}

/** "Worked · 19:41 · by voice". */
export function markLine(m: DriverMark): string {
  return [VERDICT_WORD[m.verdict], timeOfDay(m.at_unix), m.source === "voice" ? "by voice" : null].filter(Boolean).join(" · ");
}

// ------------------------------------------------------------------------------------------------ input check
export interface PhaseInfo {
  id: InputPhaseId;
  word: string;
  seconds: number;
  text: string;
}

/** The input check's fixed phases (spec 6.6). */
export const INPUT_PHASES: Record<InputPhaseId, PhaseInfo> = {
  centre: { id: "centre", word: "CENTRE", seconds: 3, text: "Hands off the wheel." },
  left: { id: "left", word: "LEFT", seconds: 3, text: "Full lock left, and hold it." },
  right: { id: "right", word: "RIGHT", seconds: 3, text: "Full lock right, and hold it." },
  pedals: { id: "pedals", word: "PEDALS", seconds: 6, text: "Car stopped, in neutral or in the pit lane: full throttle, then full brake." },
  reverse: { id: "reverse", word: "REVERSE", seconds: 15, text: "Select reverse and roll back a car length." },
};

function latestPhase(records: InputPhaseRecord[], itemId: string, phase: InputPhaseId): InputPhaseRecord | null {
  const r = records.filter((x) => x.item_id === itemId && x.phase === phase);
  return r.at(-1) ?? null;
}

export const NO_INPUT_DATA = "No data came from the car during the check. Is the game running?";

/** The input check's results as facts ("Full lock left: −0.98 · right: +0.97 · sign as expected"). Full lock is read
 * as the left phase's minimum and the right phase's maximum (the right phase starts from full left lock, so its mean
 * can sit near 0), as the backend's steering-sign check does. Nothing measured: one sentence, never a row of dashes. */
export function inputCheckFacts(records: InputPhaseRecord[], itemId: string): string[] {
  const out: string[] = [];
  const centre = latestPhase(records, itemId, "centre");
  const left = latestPhase(records, itemId, "left");
  const right = latestPhase(records, itemId, "right");
  const pedals = latestPhase(records, itemId, "pedals");
  const reverse = latestPhase(records, itemId, "reverse");
  const phases = [centre, left, right, pedals, reverse].filter((x): x is InputPhaseRecord => x !== null);
  if (phases.length && phases.every((x) => !x.samples)) return [NO_INPUT_DATA];
  const sgn = (v: number | null | undefined) => (finite(v) ? fixed(v, 2, true) : UNKNOWN);
  if (centre) out.push(`Hands off: ${sgn(centre.steer_mean)}`);
  if (left || right) {
    let l = left?.steer_min;
    let r = right?.steer_max;
    let sign = "";
    const lMax = left?.steer_max;
    const rMin = right?.steer_min;
    if (finite(l) && finite(r) && finite(lMax) && finite(rMin)) {
      const ok = l < -0.5 && r > 0.5;
      const inverted = lMax > 0.5 && rMin < -0.5;
      if (inverted && !ok) {
        sign = " · steering sign looks inverted";
        l = lMax;
        r = rMin;
      } else if (ok && !inverted) sign = " · sign as expected";
      else sign = " · full lock not reached";
    }
    out.push(`Full lock left: ${sgn(l)} · right: ${sgn(r)}${sign}`);
  }
  const raw = [left, right, centre].map((x) => x?.steer_raw_range).find((x): x is [number, number] => Array.isArray(x));
  if (raw) {
    const rot = [left, right, centre, pedals, reverse].map((x) => x?.rotation_deg).find(finite);
    out.push(`Raw steering range ${plainNumber(raw[0])} to ${plainNumber(raw[1])}${finite(rot) ? ` at ${Math.round(rot)}°` : ""}`);
  }
  if (pedals) out.push(`Throttle at most ${percent(pedals.throttle_max)} · brake at most ${percent(pedals.brake_max)}`);
  if (reverse) out.push(reverse.gear_min === null ? `Reverse gear: ${UNKNOWN}` : reverse.gear_min < 0 ? "Reverse gear seen" : "Reverse gear not seen");
  return out;
}

// ------------------------------------------------------------------------------------------------ reports
export interface CountChip {
  key: ItemResult;
  label: string;
  tone: ChipTone;
}

const COUNT_WORD: Record<ItemResult, string> = {
  pass: "passed",
  fail: "failed",
  needs_review: "to check",
  not_run: "not run",
  skipped: "skipped",
};

/** "5 passed", "1 failed", "3 to review"… (non-zero only, in that order). */
export function countChips(counts: Partial<Record<ItemResult, number>>): CountChip[] {
  const order: ItemResult[] = ["pass", "fail", "needs_review", "not_run", "skipped"];
  return order
    .filter((k) => (counts[k] ?? 0) > 0)
    .map((k) => ({ key: k, label: `${counts[k]} ${COUNT_WORD[k]}`, tone: RESULT_CHIP[k].tone }));
}

export function hasLive(s: Pick<RunSummary, "tiers">): boolean {
  return s.tiers.includes("live");
}

/** "First rig run" or the run's start time. */
export function runTitle(s: Pick<RunSummary, "label" | "started_unix">): string {
  return s.label?.trim() ? s.label.trim() : `Run of ${dateTime(s.started_unix)}`;
}

/** "pitwall 0.1.0 (a1b2c3d) · macOS · voice on (Kokoro, Parakeet) · LLM on". */
export function serverLine(s: ServerInfo): string {
  const os = s.os === "darwin" ? "macOS" : s.os === "win32" || s.os === "windows" ? "Windows" : s.os === "linux" ? "Linux" : s.os;
  // "none" is the engine name of a radio without speech recognition or without a voice (text only)
  const engines = [s.tts, s.stt].filter((x): x is string => !!x && x !== "none").map((x) => x.charAt(0).toUpperCase() + x.slice(1));
  const voice = s.voice_enabled ? `voice on (${engines.length ? engines.join(", ") : "text only"})` : "voice off";
  return [`pitwall ${s.pitwall_version}${s.git_commit ? ` (${s.git_commit})` : ""}`, os, voice, s.llm_enabled ? "LLM on" : "LLM off"].join(" · ");
}

/** "412 live records · 3 not live" (replays, generated, relayed or unplaced). */
export function tiersLine(t: Partial<Record<EvidenceTier, number>>): string {
  const live = t.live ?? 0;
  const other = (t.recorded ?? 0) + (t.synthetic ?? 0) + (t.loopback ?? 0) + (t.unknown ?? 0);
  return `${grouped(live)} live record${live === 1 ? "" : "s"} · ${grouped(other)} from replays, generated data or unknown sources`;
}

export interface SummaryRow {
  id: string;
  title: string;
  result: ChipSpec;
  driver: string;
  saw: ChipSpec;
  key: string;
}

/** The driver column: "Worked", or per driver "James: Worked · Sam: Didn't work". */
export function driverColumn(marks: DriverMark[], names?: ReadonlyMap<number, string>): string {
  if (!marks.length) return UNKNOWN;
  const latest = new Map<number | null, DriverMark>();
  for (const m of marks) latest.set(m.driver_id, m);
  if (latest.size === 1) return VERDICT_WORD[[...latest.values()][0]!.verdict];
  return [...latest.values()].map((m) => `${driverLabel(m.driver_id, names)}: ${VERDICT_WORD[m.verdict]}`).join(" · ");
}

/** The report's words for a result and for what Pitwall saw: a run still going keeps "Not yet" / "Not seen yet". */
export function reportChips(inProgress: boolean): { result: Record<ItemResult, ChipSpec>; saw: Record<AutoVerdict, ChipSpec> } {
  return inProgress ? { result: RESULT_CHIP, saw: AUTO_CHIP } : { result: REPORT_RESULT_CHIP, saw: REPORT_AUTO_CHIP };
}

/** "No braking calls yet" in a finished report reads "No braking calls". */
export function reportReason(r: string, inProgress: boolean): string {
  return reasonText(inProgress ? r : r.replace(/ yet(?=\b|$)/, ""));
}

export function summaryRows(
  report: Pick<ValidationReport, "items"> & Partial<Pick<ValidationReport, "in_progress">>,
  names?: ReadonlyMap<number, string>,
): SummaryRow[] {
  const going = report.in_progress ?? true;
  const chips = reportChips(going);
  return report.items.map((i: ReportItem) => ({
    id: i.id,
    title: i.title,
    result: chips.result[i.result] ?? chips.result.not_run,
    driver: driverColumn(i.marks, names),
    saw: chips.saw[i.auto.verdict] ?? chips.saw.no_evidence,
    key: i.auto.reasons[0] ? reportReason(i.auto.reasons[0], going) : UNKNOWN,
  }));
}

// ------------------------------------------------------------------------------------------------ page routes
export type ValidationView = "checklist" | "reports";

/** `#/setup/validation[/reports[/<run id>]]` -> { view, runId } (anything else is the checklist). */
export function parseValidationParam(param: string | null): { view: ValidationView; runId: string | null } {
  const [view, id] = (param ?? "").split("/");
  if (view !== "reports") return { view: "checklist", runId: null };
  return { view: "reports", runId: id && /^\d{8}-\d{6}-[0-9a-f]{4}$/.test(id) ? id : null };
}

export function validationPath(view: ValidationView = "checklist", runId: string | null = null): string {
  if (view === "checklist") return "/setup/validation";
  return runId ? `/setup/validation/reports/${encodeURIComponent(runId)}` : "/setup/validation/reports";
}
