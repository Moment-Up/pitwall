// The technique knowledge on one coaching point (technique knowledge graph spec, section 3;
// src/pitwall/knowledge/annotate.py): whether the point fits the driver, the causes its measured signals named (each
// with the evidence that named it) and the graph's advice at the driver's skill and braking style. Pure.
//
// Three shapes reach the dashboard, one type here (fields only some of them have are optional):
//   - the full annotation (`knowledge` on GET /api/sessions/{id}/analysis, /api/compare and /api/coachref/compare
//     observations, and the lap notification): Review reads it;
//   - the coach block's slim copy (`knowledge` on every coach point): the annotation's shape, each cause's evidence as
//     its measured values without the plain-words test;
//   - the card's copy on every /ws/live snapshot observation: `fault`, `applies` and the first measured cause's id,
//     name and screen line - all the coach card reads (fitsDriver, cardCause).
// Absent or null on an older server, without the graph, or for a kind the graph has no fault for: the point is then
// coached exactly as before the graph (applies), and nothing below adds a word.
//
// The words are the graph's, verbatim (P9: the UI composes no advice): a cause's screen line, its discriminators'
// plain-words tests with the value measured on that lap, the fault's `why_not`, and advice written for the driver's
// skill or style (`advice.tailored`). Rules mirrored from the backend: a point whose `applies` is false is never
// coaching (analysis/coaching.py `applies`: not on the coach card, not a Work on, never a habit) but is shown in
// Review with its reason.

export type AdviceForm = "radio" | "screen" | "review";

/** One discriminator that held: its plain-words test and the value measured on that lap (null = a yes/no test). */
export interface KnowledgeEvidence {
  signal?: string;
  /** Full annotation only: the plain-words test. */
  test?: string | null;
  value: number | boolean | null;
  unit: string | null;
}

export interface KnowledgeAdvice {
  radio: string | null;
  screen: string | null;
  review: string | null;
  /** Full annotation: the graph advice id each form came from. */
  ids?: Partial<Record<AdviceForm, string | null>>;
  /** Full annotation: the form's advice is written for the driver's skill or braking style (not the `any` wording). */
  tailored?: Partial<Record<AdviceForm, boolean>>;
}

export interface PointCause {
  id: string;
  name: string;
  tier?: string;
  /** Absent on a snapshot observation's copy. */
  evidence?: KnowledgeEvidence[];
  /** Slim copies: the cause advice's screen line. */
  screen?: string | null;
  /** Full annotation: the cause's advice at the driver's skill and style. */
  advice?: KnowledgeAdvice | null;
}

/** `knowledge` on an observation or a coach point. */
export interface PointKnowledge {
  /** The graph fault id (the coaching kind for the live faults). */
  fault: string | null;
  name?: string;
  status?: string;
  tier?: string;
  /** False: the fault does not fit this driver or the game cannot measure it (never coaching; Review only). */
  applies: boolean | null;
  /** Absent on a snapshot observation's copy. */
  why_not?: string | null;
  causes: PointCause[];
  /** Absent on a snapshot observation's copy. */
  advice?: KnowledgeAdvice | null;
  digest?: string;
}

/** Anything that may carry an annotation (an observation, a coach point). */
export interface Annotated {
  knowledge?: PointKnowledge | null;
}

/** analysis/coaching.py `applies`: false only when the annotation says the point does not fit the driver. No
 * annotation fits, as before the graph. */
export function fitsDriver(o: Annotated | null | undefined): boolean {
  return o?.knowledge?.applies !== false;
}

/** Why a point is not coached for this driver, in the graph's words ("Only for: H-pattern gearbox (gearbox not
 * known)", "GT7 does not send lateral g"); null when it fits. */
export function notForYou(o: Annotated | null | undefined): string | null {
  const k = o?.knowledge;
  if (k?.applies !== false) return null;
  return k.why_not?.trim() || "Not for this driver and car";
}

/** A cause's one line for a screen: its advice's screen line, else its name. */
export function causeScreen(c: PointCause): string {
  return c.screen?.trim() || c.advice?.screen?.trim() || c.name;
}

/** The coach card's cause line (stationary evidence line, Ready card, Review cards): the first measured cause's
 * screen line; null without one. */
export function cardCause(o: Annotated | null | undefined): string | null {
  const c = o?.knowledge?.applies === false ? undefined : o?.knowledge?.causes?.[0];
  return c ? causeScreen(c) : null;
}

const SIGNED_UNITS = new Set(["m", "km/h", "deg", "s"]);
/** Units said in words ("deg" is jargon). */
const UNIT_WORDS: Record<string, string> = { deg: "degrees" };

/** A delta signal (this lap minus the reference: brake_point_delta_m, entry_speed_delta_kph ...): its value is signed
 * "+" or "−" against the reference. Any other value (this lap's exit balance, a count) is the value itself. */
function isDelta(signal: string | null | undefined): boolean {
  return typeof signal === "string" && signal.includes("_delta");
}

function amount(v: number, unit: string | null, delta: boolean): string {
  const a = Math.abs(v);
  const digits = unit === "s" ? 2 : a >= 10 || Number.isInteger(v) ? 0 : 1;
  const n = a.toFixed(digits);
  const nonzero = Math.round(a * 10 ** digits) !== 0;
  const sign = !nonzero ? "" : delta && unit && SIGNED_UNITS.has(unit) ? (v < 0 ? "−" : "+") : v < 0 ? "−" : "";
  if (unit === "count") return `${n} ${a === 1 ? "time" : "times"}`;
  const words = unit ? (UNIT_WORDS[unit] ?? unit) : null;
  return words && unit !== "bool" && unit !== "ratio" && unit !== "fraction" ? `${sign}${n} ${words}` : `${sign}${n}`;
}

/** One piece of evidence in words: the test, and the value measured on the lap - a delta signed as it was (lap minus
 * reference: "braked at least 8 m earlier than on the reference lap (measured −12 m)"), any other value as it is ("no
 * clear understeer on the way out (measured 1.3 degrees)", this lap's own balance, not a difference); a yes/no test
 * is its words. */
export function evidenceWords(e: KnowledgeEvidence): string {
  const test = e.test?.trim() || e.signal || "";
  const v = e.value;
  if (typeof v !== "number" || !Number.isFinite(v)) return test;
  return `${test} (measured ${amount(v, e.unit, isDelta(e.signal))})`;
}

export interface CauseLine {
  id: string;
  name: string;
  /** The cause's screen line. */
  line: string;
  /** The evidence that named it, in words. */
  evidence: string[];
}

/** Every measured cause of a point, with its evidence in words (Review). */
export function causeLines(o: Annotated | null | undefined): CauseLine[] {
  const k = o?.knowledge;
  if (!k || k.applies === false) return [];
  return (k.causes ?? []).map((c) => ({
    id: c.id,
    name: c.name,
    line: causeScreen(c),
    evidence: (c.evidence ?? []).map(evidenceWords).filter((x) => x.length > 0),
  }));
}

/** The graph's explanation written for this driver's skill or braking style (beginner advice, the trail-braking
 * explanation of coasting), shown in Review under the coach's own text; null when the review advice is the general
 * wording, which the coach's text already says. */
export function tailoredExplanation(o: Annotated | null | undefined): string | null {
  const a = o?.knowledge?.applies === false ? null : o?.knowledge?.advice;
  return a?.tailored?.review && a.review ? a.review : null;
}

/** A cause's evidence as one sentence: "Braked at least 8 m earlier than on the reference lap (measured −8.6 m); at
 * least 4 km/h slower at the corner entry ..." with a capital and a full stop; "" without evidence. */
export function evidenceSentence(evidence: readonly string[]): string {
  const text = evidence.filter((e) => e.trim().length > 0).join("; ");
  return text ? `${text.charAt(0).toUpperCase()}${text.slice(1)}.` : "";
}

/** "cause · evidence" joined, empty parts dropped; null when nothing is left. */
export function joinLine(...parts: readonly (string | null | undefined)[]): string | null {
  const kept = parts.filter((p): p is string => typeof p === "string" && p.trim().length > 0);
  return kept.length ? kept.join(" · ") : null;
}
