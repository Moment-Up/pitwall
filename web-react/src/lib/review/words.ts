// Plain words for Review (spec 6, 9.6): descriptions built from measured numbers, never advice. The coach's own
// texts (analysis/coaching.py) are shown verbatim elsewhere; this module only adds neutral sentences ("braked about
// 12 m earlier"), evidence lines, lap status words, session titles and day labels. Pure; tested in node.
//
// Sign conventions (lap minus reference, as the analysis sends them): a negative brake point is braking earlier, a
// negative speed is slower, a positive time is time lost, a positive full-throttle distance is later.

import { MINUS, UNKNOWN } from "../format";

export function finite(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/** Confidence in words (9.6): high >= 0.8, medium 0.6-0.8, low < 0.6. */
export function confidenceWord(c: number | null | undefined): "high" | "medium" | "low" | null {
  if (!finite(c)) return null;
  if (c >= 0.8) return "high";
  if (c >= 0.6) return "medium";
  return "low";
}

/** "0.11 s" (no sign: the sentence carries the direction). Unknown -> "-". */
export function seconds(s: number | null | undefined, digits = 2): string {
  if (!finite(s)) return UNKNOWN;
  return `${Math.abs(s).toFixed(digits)} s`;
}

/** A steadiness or gain in seconds: 2 decimals below 1 s, 1 decimal from 1 s up ("0.35 s", "1.4 s"). */
export function spreadSeconds(ms: number | null | undefined): string {
  if (!finite(ms)) return UNKNOWN;
  const s = Math.abs(ms) / 1000;
  return `${s.toFixed(s >= 0.995 ? 1 : 2)} s`;
}

/** "1 lap", "3 laps". */
export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** First letter upper case. */
export function sentence(s: string): string {
  return s ? s[0]!.toUpperCase() + s.slice(1) : s;
}

/** "a, b and c". */
export function joinAnd(parts: readonly string[]): string {
  if (parts.length <= 1) return parts.join("");
  return `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

// ---------------------------------------------------------------------------------------------------- lap status

/** Lap flags in words (analysis/laps.py LapFlag). Unknown flags are shown with spaces for underscores. */
export const FLAG_WORDS: Readonly<Record<string, string>> = {
  flashback: "flashback",
  pit_in: "pit in",
  pit_out: "pit out",
  incomplete: "incomplete",
  invalid: "invalid",
  paused: "paused",
  stale_data: "data gap",
  standing_start: "standing start",
  distance_jump: "reset to track",
};

export function flagWord(flag: string): string {
  return FLAG_WORDS[flag] ?? flag.replace(/_/g, " ");
}

/** Why a lap is not clean, in words ("flashback", "invalid, pit in"); null for a clean lap. */
export function notCleanReason(lap: { clean: boolean; valid: boolean | null; flags: readonly string[] }): string | null {
  if (lap.clean) return null;
  const words = lap.flags.map(flagWord);
  if (lap.valid === false && !lap.flags.includes("invalid")) words.unshift("invalid");
  const unique = [...new Set(words)];
  return unique.length ? unique.join(", ") : "not clean";
}

// ------------------------------------------------------------------------------------------- corner descriptions

/** Thresholds below which a mean difference is not described (the coach's own rule thresholds,
 * analysis/coaching.py: BRAKE_POINT_M, MIN_SPEED_KPH, EXIT_SPEED_KPH). */
export const WORDS_BRAKE_M = 8;
export const WORDS_MIN_SPEED_KPH = 4;
export const WORDS_EXIT_SPEED_KPH = 3;

export interface CornerDeltas {
  brakeM?: number | null;
  minSpeedKph?: number | null;
  exitSpeedKph?: number | null;
}

/**
 * Neutral words for a corner's average differences (spec 6.3 #5): "braked about 12 m earlier", "4 km/h slower at
 * the slowest point", "5 km/h slower out of the corner". Differences under the coach's thresholds are left out.
 */
export function cornerWords(d: CornerDeltas): string[] {
  const out: string[] = [];
  if (finite(d.brakeM) && Math.abs(d.brakeM) >= WORDS_BRAKE_M) {
    out.push(`braked about ${Math.round(Math.abs(d.brakeM))} m ${d.brakeM < 0 ? "earlier" : "later"}`);
  }
  if (finite(d.minSpeedKph) && Math.abs(d.minSpeedKph) >= WORDS_MIN_SPEED_KPH) {
    out.push(
      `${Math.round(Math.abs(d.minSpeedKph))} km/h ${d.minSpeedKph < 0 ? "slower" : "faster"} at the slowest point`,
    );
  }
  if (finite(d.exitSpeedKph) && Math.abs(d.exitSpeedKph) >= WORDS_EXIT_SPEED_KPH) {
    out.push(`${Math.round(Math.abs(d.exitSpeedKph))} km/h ${d.exitSpeedKph < 0 ? "slower" : "faster"} out of the corner`);
  }
  return out;
}

export interface WhyInput {
  /** Corner as people call it ("Stowe", or "T15" when it has no name). */
  where: string;
  evidence: {
    time_delta_s?: number | null;
    brake_point_delta_m?: number | null;
    min_speed_delta_kph?: number | null;
    exit_speed_delta_kph?: number | null;
    throttle_full_delta_m?: number | null;
  };
  lapNumber?: number | null;
  refLapNumber?: number | null;
}

/**
 * The "Why?" sentence (spec 6.3 #2): the comparison's numbers in plain words, e.g. "At Stowe you braked 12 m
 * earlier, your slowest speed was 4 km/h lower and the corner took 0.11 s longer (lap 63 against your reference,
 * lap 64)." A description, never advice. Null when the observation carries no numbers.
 */
export function whyText(w: WhyInput): string | null {
  const e = w.evidence;
  const parts: string[] = [];
  if (finite(e.brake_point_delta_m) && Math.round(Math.abs(e.brake_point_delta_m)) >= 1) {
    parts.push(`you braked ${Math.round(Math.abs(e.brake_point_delta_m))} m ${e.brake_point_delta_m < 0 ? "earlier" : "later"}`);
  }
  if (finite(e.min_speed_delta_kph) && Math.round(Math.abs(e.min_speed_delta_kph)) >= 1) {
    parts.push(
      `your slowest speed was ${Math.round(Math.abs(e.min_speed_delta_kph))} km/h ${e.min_speed_delta_kph < 0 ? "lower" : "higher"}`,
    );
  }
  if (finite(e.exit_speed_delta_kph) && Math.round(Math.abs(e.exit_speed_delta_kph)) >= 1) {
    parts.push(
      `you left the corner ${Math.round(Math.abs(e.exit_speed_delta_kph))} km/h ${e.exit_speed_delta_kph < 0 ? "slower" : "faster"}`,
    );
  }
  if (finite(e.throttle_full_delta_m) && Math.round(Math.abs(e.throttle_full_delta_m)) >= 1) {
    parts.push(
      `full throttle came ${Math.round(Math.abs(e.throttle_full_delta_m))} m ${e.throttle_full_delta_m > 0 ? "later" : "earlier"}`,
    );
  }
  if (finite(e.time_delta_s) && Math.abs(e.time_delta_s) >= 0.005) {
    parts.push(`the corner took ${Math.abs(e.time_delta_s).toFixed(2)} s ${e.time_delta_s > 0 ? "longer" : "less"}`);
  }
  if (!parts.length) return null;
  const laps =
    finite(w.lapNumber) && finite(w.refLapNumber)
      ? ` (lap ${w.lapNumber} against your reference, lap ${w.refLapNumber})`
      : "";
  return `At ${w.where} ${joinAnd(parts)}${laps}.`;
}

// ------------------------------------------------------------------------------------------------- evidence line

/** The coach's consistency string ("3 of the last 5 laps") as the evidence line says it ("3 of your last 5 laps"). */
export function consistencyWords(consistency: string | null | undefined): string | null {
  if (!consistency) return null;
  return consistency.replace(/\bthe last\b/, "your last");
}

export interface EvidenceInput {
  /** The coach's consistency string of the latest occurrence. */
  consistency?: string | null;
  /** Laps the point was seen on in this session, and laps compared (fallback when the coach has no history). */
  seen?: number;
  compared?: number;
  /** Average time lost (or gained) per lap where it was seen, seconds. */
  impactS?: number | null;
  confidence?: number | null;
}

/** "Seen on 3 of your last 5 laps · about 0.11 s a lap · confidence high" (spec 6.3 #2, 9.6). */
export function evidenceLine(e: EvidenceInput): string {
  const parts: string[] = [];
  const c = consistencyWords(e.consistency);
  if (c) parts.push(`Seen on ${c}`);
  else if (finite(e.seen) && finite(e.compared) && e.compared > 0) parts.push(`Seen on ${e.seen} of ${plural(e.compared, "lap")} compared`);
  if (finite(e.impactS) && Math.abs(e.impactS) >= 0.005) parts.push(`about ${Math.abs(e.impactS).toFixed(2)} s a lap`);
  const w = confidenceWord(e.confidence);
  if (w) parts.push(`confidence ${w}`);
  return parts.join(" · ");
}

/** A signed time badge for non-beginners ("+0.11 s"); the minus is U+2212. */
export function signedSeconds(s: number | null | undefined, digits = 2): string {
  if (!finite(s)) return UNKNOWN;
  const abs = Math.abs(s).toFixed(digits);
  if (Number(abs) === 0) return `±${abs} s`;
  return `${s > 0 ? "+" : MINUS}${abs} s`;
}

// --------------------------------------------------------------------------------------------- sessions and days

/** The session type in words: the server's session_label when it sends one (F2's "Sprint race" / "Feature race" for the
 * game's "Race" / "Race 2"), else as the game names it ("Race", "One-Shot Qualifying"); null when unknown. */
export function sessionTypeLabel(row: {
  session_label?: string | null;
  session_type_raw?: string | null;
  session_type?: string | null;
}): string | null {
  const label = row.session_label?.trim();
  if (label) return label;
  const raw = row.session_type_raw?.trim();
  if (raw) return raw;
  const t = row.session_type?.trim();
  if (!t || t === "unknown") return null;
  return sentence(t.replace(/_/g, " "));
}

/** A raw id stored as a name by older adapters or other games ("team_214", "car_12", "unknown_-1", "gt7:car:123",
 * "f1:team:7"): never shown to a driver (integration plan 5.8; motivation/model.py `_RAW_CAR_ID`). */
const RAW_ID = /^(?:(?:team|car)_\d+|unknown_-?\d+|[a-z0-9_]+(?::[a-z0-9_.-]+)+)$/i;

/** F1's neutral label for a team its spec does not name ("Unknown team (id 214)"): it names no car. */
const UNKNOWN_TEAM = "Unknown team";

/** A car name a driver can read, or null: a raw id or F1's "Unknown team (id 214)" is left out, never shown (the same
 * rule as the server's `display_car`, so a sentence never says "in the team_214"). */
export function readableCar(name: string | null | undefined): string | null {
  const t = name?.trim();
  if (!t || RAW_ID.test(t) || t.startsWith(UNKNOWN_TEAM)) return null;
  return t;
}

/** The track as stored, or "Unknown track" (a title, so words rather than "-"); a raw id ("unknown_-1") is never
 * shown (integration plan 5.8). */
export function trackLabel(row: { track_name?: string | null }): string {
  const t = row.track_name?.trim();
  return t && !RAW_ID.test(t) ? t : "Unknown track";
}

/** "Silverstone · Practice", "Jeddah · Feature race" (the type is left out when unknown). */
export function sessionTitle(row: {
  track_name?: string | null;
  session_label?: string | null;
  session_type_raw?: string | null;
  session_type?: string | null;
}): string {
  const type = sessionTypeLabel(row);
  return type ? `${trackLabel(row)} · ${type}` : trackLabel(row);
}

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Day title for a group of sessions: "Today", "Yesterday", "3 Oct", or "3 Oct 2025" in another year (local time). */
export function dayTitle(unixS: number, nowMs: number): string {
  const d = new Date(unixS * 1000);
  const now = new Date(nowMs);
  const days = Math.round((startOfDay(now) - startOfDay(d)) / 86_400_000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  const base = `${d.getDate()} ${MONTHS[d.getMonth()]}`;
  return d.getFullYear() === now.getFullYear() ? base : `${base} ${d.getFullYear()}`;
}

/** dayTitle inside a sentence: "today", "yesterday", "3 Oct". */
export function dayInSentence(unixS: number, nowMs: number): string {
  const t = dayTitle(unixS, nowMs);
  return t === "Today" || t === "Yesterday" ? t.toLowerCase() : t;
}

/** A stable key for the local day ("2026-10-11"). */
export function dayKey(unixS: number): string {
  const d = new Date(unixS * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Local time of day, 24 h ("19:40"). */
export function timeOfDay(unixS: number): string {
  const d = new Date(unixS * 1000);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** Axis labels for sessions: the day ("Today", "3 Oct"), with the time when a day has more than one session
 * ("Yesterday 19:41"). */
export function sessionLabels(points: readonly { startedUnix: number }[], nowMs: number): string[] {
  const days = points.map((p) => dayTitle(p.startedUnix, nowMs));
  return days.map((d, i) => (days.indexOf(d) !== days.lastIndexOf(d) ? `${d} ${timeOfDay(points[i]!.startedUnix)}` : d));
}

/** "Today · 19:40", "3 Oct · 19:15". */
export function whenText(unixS: number, nowMs: number): string {
  return `${dayTitle(unixS, nowMs)} · ${timeOfDay(unixS)}`;
}

/** Weather in words ("Light cloud · track 34°"); null when nothing is known. */
export function weatherText(w: { condition?: string | null; track_temp_c?: number | null } | null | undefined): string | null {
  if (!w) return null;
  const parts: string[] = [];
  if (w.condition) parts.push(sentence(w.condition.replace(/_/g, " ")));
  if (finite(w.track_temp_c)) parts.push(`track ${Math.round(w.track_temp_c)}°`);
  return parts.length ? parts.join(" · ") : null;
}

// ----------------------------------------------------------------------------------------------- engineer answers

export type AnswerSource = "grounded" | "deterministic" | "llm_down";

/** Which chip an engineer answer carries (spec 6.7): `LLM · grounded`, `Deterministic` (fallback, or the LLM is
 * off), `LLM down · deterministic` (the LLM was asked but could not be reached). A reply that never went to the LLM
 * (a radio check, "quiet for 3 laps": no model, no attempt) is deterministic too; `model` / `llm_attempts` are only
 * judged when the answer carries them. */
export function answerSource(a: {
  fallback: boolean;
  grounded: boolean | null;
  grounding_issues?: readonly string[];
  model?: string | null;
  llm_attempts?: number;
}): AnswerSource {
  const noLlm = a.model === null && (a.llm_attempts ?? 0) === 0;
  if (!a.fallback && a.grounded !== false && !noLlm) return "grounded";
  if ((a.grounding_issues ?? []).some((i) => i.startsWith("llm unavailable"))) return "llm_down";
  return "deterministic";
}

/** The LLM's answer failed the grounding check and the deterministic one replaced it (the issues say why). */
export function replacedAfterGrounding(a: { fallback: boolean; grounding_issues?: readonly string[] }): boolean {
  return a.fallback && (a.grounding_issues ?? []).some((i) => !i.startsWith("llm unavailable"));
}

export const ANSWER_SOURCE_LABEL: Readonly<Record<AnswerSource, string>> = {
  grounded: "LLM · grounded",
  deterministic: "Deterministic",
  llm_down: "LLM down · deterministic",
};

// Pace vs AI words (lib/review/aipace.ts): the game's setting is "AI difficulty" in every label and sentence ("Pace vs
// AI · AI difficulty 35", "Suggested AI difficulty", the glossary); "AI 35" only as a compact value (session rows, chart
// dots, list lines, a suggested level). A comparison is the driver's best lap against the typical AI car's best lap,
// and says so ("than the typical AI car's best lap", "20th of 20 on best laps"), never a bare position.
