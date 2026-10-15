// The technique knowledge on one coaching point (technique knowledge graph spec, section 3;
// src/pitwall/knowledge/annotate.py): whether the point fits the driver, the causes its measured signals named (each
// with the evidence that named it) and the graph's advice at the driver's skill and braking style. Pure.
//
// Two shapes reach the dashboard, one type here (fields only one of them has are optional):
//   - the full annotation (`knowledge` on GET /api/sessions/{id}/analysis and /api/compare observations, and the lap
//     notification): Review reads it;
//   - the coach block's slim copy (`knowledge` on every coach point and every /ws/live snapshot observation): the
//     coach card reads it.
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
  test: string | null;
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
  evidence: KnowledgeEvidence[];
  /** Slim copy: the cause advice's screen line. */
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
  why_not: string | null;
  causes: PointCause[];
  advice: KnowledgeAdvice | null;
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

function amount(v: number, unit: string | null): string {
  const a = Math.abs(v);
  const digits = unit === "s" ? 2 : a >= 10 || Number.isInteger(v) ? 0 : 1;
  const n = a.toFixed(digits);
  const sign = unit && SIGNED_UNITS.has(unit) && Math.round(a * 10 ** digits) !== 0 ? (v < 0 ? "−" : "+") : "";
  if (unit === "count") return `${n} ${a === 1 ? "time" : "times"}`;
  return unit && unit !== "bool" && unit !== "ratio" && unit !== "fraction" ? `${sign}${n} ${unit}` : `${sign}${n}`;
}

/** One piece of evidence in words: the test, and the value measured on the lap (signed, as the delta was: lap minus
 * reference) - "braked at least 8 m earlier than on the reference lap (measured −12 m)"; a yes/no test is its words. */
export function evidenceWords(e: KnowledgeEvidence): string {
  const test = e.test?.trim() || e.signal || "";
  const v = e.value;
  if (typeof v !== "number" || !Number.isFinite(v)) return test;
  return `${test} (measured ${amount(v, e.unit)})`;
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
