// Plain words for technique analysis (feat/technique spec §4, §9): line offsets against the driver's own reference
// lap, brake and throttle inputs, handling balance and setup suggestions. Pure; tested in node.
//
// Rules (design spec P5, P9, 9.6): unknown is "-"; signed numbers use U+2212; every sentence DESCRIBES what was
// measured and never says what to do ("1.5 m wider than your reference", never "take a tighter line"); nothing here
// recommends braking later (or earlier). The backend's own note texts are shown verbatim where they exist; this module
// only adds neutral restatements of the numbers. Line offsets are relative to the reference lap: Pitwall does not
// know the track edges, so "wider" and "tighter" are towards the outside or inside of the corner, nothing more.

import type { ParameterInfo } from "../endpoints/carsetup";
import type {
  BalanceClass,
  BalanceSymptom,
  CornerInputs,
  LinePointKey,
  LinePointSummary,
  NoteMetric,
  Phase,
  PhaseBalance,
  PhaseSummary,
  ReleaseShape,
  SetupSuggestion,
  SlipEvents,
  SpeedClass,
  TechniqueLap,
  TechniqueNote,
} from "../endpoints/technique";
import { MINUS, UNKNOWN } from "../format";

export function finite(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/** Below this many metres two lines are "about the same" (technique/thresholds.py LINE_NOTABLE_M; the API's
 * thresholds[] is the authority, this mirrors it for sentences). Same-driver lap-to-lap spread is 0.7-2.8 m. */
export const LINE_NOTABLE_M = 1.0;

/** "+1.50", "−1.50", "0.00" (U+2212). Unknown -> "-". */
export function signedNumber(v: number | null | undefined, digits = 1, unit = ""): string {
  if (!finite(v)) return UNKNOWN;
  const abs = Math.abs(v).toFixed(digits);
  if (Number(abs) === 0) return `${abs}${unit}`;
  return `${v > 0 ? "+" : MINUS}${abs}${unit}`;
}

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

function sentence(s: string): string {
  return s ? s[0]!.toUpperCase() + s.slice(1) : s;
}

// ---------------------------------------------------------------------------------------------------- labels

export const POINT_LABEL: Readonly<Record<LinePointKey, string>> = {
  turn_in: "Turn-in",
  apex: "Apex",
  track_out: "Track-out",
};

export const PHASE_LABEL: Readonly<Record<Phase, string>> = { entry: "Entry", mid: "Mid", exit: "Exit" };

/** How a phase reads in a sentence ("Mid-corner understeer", "understeer on entry"). */
export const PHASE_TITLE: Readonly<Record<Phase, string>> = { entry: "Entry", mid: "Mid-corner", exit: "Exit" };

/** Balance in words (spec §9): the plain words first, the term in brackets. */
export const BALANCE_WORDS: Readonly<Record<BalanceClass, string>> = {
  understeer: "Pushed wide (understeer)",
  neutral: "Balanced",
  oversteer: "Rear stepped out (oversteer)",
};

export const BALANCE_TERM: Readonly<Record<BalanceClass, string>> = {
  understeer: "understeer",
  neutral: "balanced",
  oversteer: "oversteer",
};

export const SPEED_CLASS_WORDS: Readonly<Record<SpeedClass | "mixed", string>> = {
  slow: "slow",
  medium: "medium speed",
  fast: "fast",
  mixed: "mixed speeds",
};

export const RELEASE_SHAPE_WORDS: Readonly<Record<ReleaseShape, string>> = {
  step: "let off in one go",
  steady: "eased off steadily",
  drop_then_trail: "dropped quickly, then trailed off",
  late_drop: "held on, then let off late",
};

// ---------------------------------------------------------------------------------------------------- line

/**
 * One line offset in words (spec §4.1): + = tighter (towards the inside of this corner), − = wider. With the inside
 * unknown (a nearly straight piece of track) only the distance is said. `ref` names the reference ("your reference",
 * "your target lap").
 */
export function offsetWords(offset: number | null | undefined, insideKnown: boolean, ref = "your reference"): string {
  if (!finite(offset)) return UNKNOWN;
  const abs = Math.abs(offset);
  const m = `${abs.toFixed(1)} m`;
  if (!insideKnown) return abs < 0.05 ? `on ${ref} line` : `${m} off ${ref} line`;
  if (abs < 0.05) return `on ${ref} line`;
  return `${m} ${offset < 0 ? "wider" : "tighter"} than ${ref}`;
}

/**
 * A short offset for tables, tiles and chips: "1.5 m wider", "1.2 m off"; under LINE_NOTABLE_M "about the same" (the
 * same driver's laps differ by that much anyway; the exact value stays in the tooltip and the chart). Unknown -> "-".
 */
export function offsetShort(offset: number | null | undefined, insideKnown: boolean, notableM = LINE_NOTABLE_M): string {
  if (!finite(offset)) return UNKNOWN;
  const abs = Math.abs(offset);
  if (abs < notableM) return "about the same";
  if (!insideKnown) return `${abs.toFixed(1)} m off`;
  return `${abs.toFixed(1)} m ${offset < 0 ? "wider" : "tighter"}`;
}

/**
 * The backend's sentences say "your reference"; a beginner's page calls it "your target lap" (refWordFor). `ref` is
 * the page's sentence form; anything else is returned unchanged.
 */
export function refWorded(text: string, ref: string): string {
  if (ref === "your reference" || ref === "the reference") return text;
  return text.replace(/\byour reference( lap)?\b/g, ref);
}

/** Whether an offset is big enough to call a different line (LINE_NOTABLE_M). */
export function notableOffset(offset: number | null | undefined, notableM = LINE_NOTABLE_M): boolean {
  return finite(offset) && Math.abs(offset) >= notableM;
}

/**
 * A line point over the session (Corners card): "Apex: 1.2 m wider on 3 of 4 laps", "Turn-in: about the same line
 * as your reference (median 0.3 m) on 4 laps". Null when no lap was measured there.
 */
export function linePointSummaryText(
  key: LinePointKey,
  s: LinePointSummary | null | undefined,
  insideKnown: boolean,
  notableM = LINE_NOTABLE_M,
  opts: { simple?: boolean; ref?: string } = {},
): string | null {
  if (!s || !s.laps) return null;
  const label = POINT_LABEL[key];
  const med = s.median_offset_m;
  if (!finite(med)) return null;
  const abs = Math.abs(med).toFixed(1);
  if (opts.simple && Math.abs(med) < notableM) {
    // beginners: words, not a median in metres
    const close = s.laps - s.laps_wider - s.laps_tighter;
    const when = close === s.laps ? "every lap" : close * 2 > s.laps ? "most laps" : `${close} of ${plural(s.laps, "lap")}`;
    return `${label}: about the same as ${opts.ref ?? "your reference"} on ${when}`;
  }
  if (!insideKnown) return `${label}: ${abs} m off the reference line (median of ${plural(s.laps, "lap")})`;
  if (med <= -notableM) return `${label}: ${abs} m wider on ${s.laps_wider} of ${plural(s.laps, "lap")}`;
  if (med >= notableM) return `${label}: ${abs} m tighter on ${s.laps_tighter} of ${plural(s.laps, "lap")}`;
  const odd: string[] = [];
  if (s.laps_wider) odd.push(`wider by 1 m or more on ${plural(s.laps_wider, "lap")}`);
  if (s.laps_tighter) odd.push(`tighter by 1 m or more on ${plural(s.laps_tighter, "lap")}`);
  return `${label}: about the same line as your reference (median ${abs} m over ${plural(s.laps, "lap")})${
    odd.length ? `; ${odd.join(", ")}` : ""
  }`;
}

// ---------------------------------------------------------------------------------------------------- inputs

/** Rows of the corner inputs table (spec §9: beginners 4, intermediate 8, advanced all). */
export type InputRow =
  | "release"
  | "coast"
  | "throttle_pickup"
  | "slip"
  | "brake_peak"
  | "brake_at_turn_in"
  | "trail_overlap"
  | "throttle_ramp"
  | "time_to_peak"
  | "peak_hold"
  | "brake_at_apex"
  | "throttle_lifts";

export const INPUT_ROWS_ALL: readonly InputRow[] = [
  "release",
  "coast",
  "throttle_pickup",
  "slip",
  "brake_peak",
  "brake_at_turn_in",
  "trail_overlap",
  "throttle_ramp",
  "time_to_peak",
  "peak_hold",
  "brake_at_apex",
  "throttle_lifts",
];

export const INPUT_ROW_LABEL: Readonly<Record<InputRow, string>> = {
  release: "Brake release",
  coast: "Coasting",
  throttle_pickup: "Throttle pick-up",
  slip: "Wheelspin and lock-ups",
  brake_peak: "Brake pressure (peak)",
  brake_at_turn_in: "Brake at turn-in",
  trail_overlap: "Braking while turning",
  throttle_ramp: "Throttle ramp to full",
  time_to_peak: "Time to full brake",
  peak_hold: "Full brake held",
  brake_at_apex: "Brake at the slowest point",
  throttle_lifts: "Throttle lifts",
};

/** The note metrics that belong to a row (the backend's own sentence is shown for the row when one exists). */
export const ROW_METRICS: Readonly<Record<InputRow, readonly NoteMetric[]>> = {
  release: ["release"],
  coast: ["coast"],
  throttle_pickup: ["throttle_pickup"],
  slip: ["lockup", "wheelspin"],
  brake_peak: ["brake_peak"],
  brake_at_turn_in: ["brake_at_turn_in"],
  trail_overlap: ["trail_overlap"],
  throttle_ramp: ["throttle_ramp"],
  time_to_peak: ["time_to_peak"],
  peak_hold: [],
  brake_at_apex: [],
  throttle_lifts: ["throttle_lifts"],
};

/** Rows the game's braking assist makes "not all yours" (spec §4.2: muted, never facts). */
export const BRAKE_ROWS: ReadonlySet<InputRow> = new Set<InputRow>([
  "release",
  "brake_peak",
  "brake_at_turn_in",
  "trail_overlap",
  "time_to_peak",
  "peak_hold",
  "brake_at_apex",
]);

const BRAKE_METRICS: ReadonlySet<NoteMetric> = new Set<NoteMetric>(["brake_peak", "time_to_peak", "release", "brake_at_turn_in", "trail_overlap"]);

export function isBrakeMetric(m: NoteMetric): boolean {
  return BRAKE_METRICS.has(m);
}

const pct = (v: number | null | undefined) => (finite(v) ? `${Math.round(v * 100)} %` : UNKNOWN);
const secs = (v: number | null | undefined) => (finite(v) ? `${v.toFixed(2)} s` : UNKNOWN);

/** Lock-ups in words: "ABS on: no lock-up data", "no lock-ups", "2 lock-ups (0.30 s)". Null when not applicable. */
export function lockupWords(e: SlipEvents | null | undefined): string | null {
  if (!e) return null;
  switch (e.status) {
    case "abs_on":
      return "ABS on: no lock-up data";
    case "no_data":
      return "no tyre slip data";
    case "not_applicable":
      return null;
    case "measured":
      if (!finite(e.events)) return null;
      if (e.events === 0) return "no lock-ups";
      return `${plural(e.events, "lock-up")}${finite(e.total_s) ? ` (${e.total_s.toFixed(2)} s)` : ""}`;
  }
}

/** Wheelspin in words: "no wheelspin", "wheelspin 0.45 s (2 times)". Null when not applicable. */
export function wheelspinWords(e: SlipEvents | null | undefined): string | null {
  if (!e) return null;
  switch (e.status) {
    case "abs_on":
    case "not_applicable":
      return null;
    case "no_data":
      return "no tyre slip data";
    case "measured": {
      if (!finite(e.events)) return null;
      if (e.events === 0) return "no wheelspin";
      const t = finite(e.total_s) ? ` ${e.total_s.toFixed(2)} s` : "";
      const n = e.events > 1 ? ` (${e.events} times)` : "";
      return `wheelspin${t}${n}`;
    }
  }
}

/** Lock-ups and wheelspin together; "-" when neither is known. */
export function slipWords(inputs: CornerInputs | null | undefined): string {
  if (!inputs) return UNKNOWN;
  const l = lockupWords(inputs.lockup);
  const w = wheelspinWords(inputs.wheelspin);
  if (l === "no tyre slip data" && (w === "no tyre slip data" || w === null)) return UNKNOWN;
  const parts = [l, w].filter((x): x is string => !!x && x !== "no tyre slip data");
  return parts.length ? sentence(parts.join(" · ")) : UNKNOWN;
}

/** A row's value for one lap ("0.42 s · eased off steadily", "86 %", "12 m after the slowest point"). */
export function inputValue(row: InputRow, i: CornerInputs | null | undefined): string {
  if (!i) return UNKNOWN;
  const braking = BRAKE_ROWS.has(row);
  if (braking && !i.braked) return "no braking";
  switch (row) {
    case "release":
      return finite(i.release_s)
        ? `${i.release_s.toFixed(2)} s${i.release_shape ? ` · ${RELEASE_SHAPE_WORDS[i.release_shape]}` : ""}`
        : UNKNOWN;
    case "coast":
      return finite(i.coast_s) ? `${i.coast_s.toFixed(2)} s${finite(i.coast_m) && i.coast_m >= 1 ? ` (${Math.round(i.coast_m)} m)` : ""}` : UNKNOWN;
    case "throttle_pickup": {
      const d = i.pickup_vs_apex_m;
      if (!finite(d)) return UNKNOWN;
      if (Math.abs(d) < 0.5) return "at the slowest point";
      return `${Math.round(Math.abs(d))} m ${d > 0 ? "after" : "before"} the slowest point`;
    }
    case "slip":
      return slipWords(i);
    case "brake_peak":
      return pct(i.brake_peak);
    case "brake_at_turn_in":
      return pct(i.brake_at_turn_in);
    case "trail_overlap":
      return secs(i.trail_overlap_s);
    case "throttle_ramp":
      if (finite(i.throttle_ramp_s)) return secs(i.throttle_ramp_s);
      return finite(i.pickup_m) ? "not full before the next corner" : UNKNOWN;
    case "time_to_peak":
      return secs(i.time_to_peak_s);
    case "peak_hold":
      return secs(i.peak_hold_s);
    case "brake_at_apex":
      return pct(i.brake_at_apex);
    case "throttle_lifts":
      return finite(i.throttle_lifts) ? (i.throttle_lifts === 0 ? "none" : plural(i.throttle_lifts, "lift")) : UNKNOWN;
  }
}

export interface Tolerances {
  /** Brake pressure difference below which two laps are "about the same" (PedalInfo.peak_tol, 0..1). */
  peak: number;
  /** Brake timing difference below which two laps are "about the same" (PedalInfo.time_tol_s). */
  time: number;
}

/** CSL / unknown pedals (spec §5): the conservative default when the pedals are unknown. */
export const DEFAULT_TOLERANCES: Tolerances = { peak: 0.08, time: 0.1 };

function timeDiff(lap: number | null | undefined, ref: number | null | undefined, tol: number, more: string, less: string): string {
  if (!finite(lap) || !finite(ref)) return UNKNOWN;
  const d = lap - ref;
  if (Math.abs(d) < tol) return "about the same";
  return `${Math.abs(d).toFixed(2)} s ${d > 0 ? more : less}`;
}

function pctDiff(lap: number | null | undefined, ref: number | null | undefined, tol: number): string {
  if (!finite(lap) || !finite(ref)) return UNKNOWN;
  const d = lap - ref;
  if (Math.abs(d) < tol) return "about the same";
  return `${Math.round(Math.abs(d) * 100)} % ${d > 0 ? "more" : "less"} brake`;
}

/**
 * The Difference column (your lap against the reference) in neutral words. When the backend wrote a NOTABLE note for
 * this row it is used verbatim (`text_simple` for simple wording); otherwise the numbers are restated ("0.25 s
 * longer", "about the same" within the pedals' tolerances, as the backend's own notable rule). Never advice.
 */
export function inputDifference(
  row: InputRow,
  ref: CornerInputs | null | undefined,
  lap: CornerInputs | null | undefined,
  opts: { notes?: readonly TechniqueNote[]; simple?: boolean; tol?: Tolerances } = {},
): string {
  const metrics = ROW_METRICS[row];
  const note = (opts.notes ?? []).find((n) => n.notable && metrics.includes(n.metric));
  if (note) return opts.simple && note.text_simple ? note.text_simple : note.text;
  if (!ref || !lap) return UNKNOWN;
  const tol = opts.tol ?? DEFAULT_TOLERANCES;
  if (BRAKE_ROWS.has(row) && (!ref.braked || !lap.braked)) {
    if (!ref.braked && !lap.braked) return "no braking on either lap";
    return lap.braked ? "braked here, the reference did not" : "no braking here, the reference braked";
  }
  switch (row) {
    case "release":
      return timeDiff(lap.release_s, ref.release_s, tol.time, "longer", "shorter");
    case "coast":
      return timeDiff(lap.coast_s, ref.coast_s, 0.05, "more coasting", "less coasting");
    case "throttle_pickup": {
      if (!finite(lap.pickup_vs_apex_m) || !finite(ref.pickup_vs_apex_m)) return UNKNOWN;
      const d = lap.pickup_vs_apex_m - ref.pickup_vs_apex_m;
      if (Math.abs(d) < 5) return "about the same";
      return `${Math.round(Math.abs(d))} m ${d > 0 ? "later" : "earlier"}`;
    }
    case "slip": {
      const l = slipWords(lap);
      const r = slipWords(ref);
      if (l === UNKNOWN || r === UNKNOWN) return UNKNOWN;
      return l === r ? "the same" : `${l} (reference: ${r.toLowerCase()})`;
    }
    case "brake_peak":
      return pctDiff(lap.brake_peak, ref.brake_peak, tol.peak);
    case "brake_at_turn_in":
      return pctDiff(lap.brake_at_turn_in, ref.brake_at_turn_in, tol.peak);
    case "brake_at_apex":
      return pctDiff(lap.brake_at_apex, ref.brake_at_apex, tol.peak);
    case "trail_overlap":
      return timeDiff(lap.trail_overlap_s, ref.trail_overlap_s, 0.15, "longer", "shorter");
    case "throttle_ramp":
      return timeDiff(lap.throttle_ramp_s, ref.throttle_ramp_s, 0.2, "longer", "shorter");
    case "time_to_peak":
      return timeDiff(lap.time_to_peak_s, ref.time_to_peak_s, tol.time, "longer", "shorter");
    case "peak_hold":
      return timeDiff(lap.peak_hold_s, ref.peak_hold_s, tol.time, "longer", "shorter");
    case "throttle_lifts": {
      if (!finite(lap.throttle_lifts) || !finite(ref.throttle_lifts)) return UNKNOWN;
      const d = lap.throttle_lifts - ref.throttle_lifts;
      if (d === 0) return "the same";
      return `${plural(Math.abs(d), "lift")} ${d > 0 ? "more" : "fewer"}`;
    }
  }
}

// ---------------------------------------------------------------------------------------------------- balance

/** A phase chip's words; "-" when unknown. Advanced adds the measured slip difference ("+7.2°"). */
export function phaseBalanceWords(b: PhaseBalance | null | undefined, degrees = false): string {
  if (!b || !b.cls) return UNKNOWN;
  const words = BALANCE_WORDS[b.cls];
  const slide = b.slide && b.cls === "oversteer" ? " · slide" : "";
  const deg = degrees && finite(b.slip_diff_deg) ? ` · ${signedNumber(b.slip_diff_deg, 1, "°")}` : "";
  return `${words}${slide}${deg}`;
}

/** How many laps had the phase's recurring class. */
function classCount(s: PhaseSummary, cls: BalanceClass): number {
  return cls === "understeer" ? s.understeer : cls === "oversteer" ? s.oversteer : s.neutral;
}

/**
 * A phase over the session (Corners card): "Mid: understeer on 3 of 3 laps, even on your best lap", "Entry:
 * understeer on 2 of 3 laps, not on your best lap", "Exit: balanced on 3 of 4 laps". Null without laps.
 */
export function phaseSummaryText(phase: Phase, s: PhaseSummary | null | undefined): string | null {
  if (!s || !s.laps) return null;
  const label = PHASE_LABEL[phase];
  if (s.recurring) {
    const n = classCount(s, s.recurring);
    const tail =
      s.recurring === "neutral"
        ? ""
        : s.verdict === "car"
          ? ", even on your best lap"
          : s.verdict === "driving"
            ? ", not on your best lap"
            : "";
    return `${label}: ${BALANCE_TERM[s.recurring]} on ${n} of ${plural(s.laps, "lap")}${tail}`;
  }
  // No class recurs: what was seen, every class named, without a verdict ("mixed" when none is a clear majority).
  const counts = (
    [
      ["neutral", s.neutral],
      ["understeer", s.understeer],
      ["oversteer", s.oversteer],
    ] as [BalanceClass, number][]
  ).filter(([, n]) => n > 0);
  counts.sort((a, b) => b[1] - a[1]);
  if (!counts.length) return null;
  const [top, n] = counts[0]!;
  const rest = counts.slice(1).map(([c, k]) => `${k} ${BALANCE_TERM[c]}`);
  if (n * 2 > s.laps) {
    return `${label}: ${BALANCE_TERM[top]} on ${n} of ${plural(s.laps, "lap")}${rest.length ? ` (${rest.join(", ")})` : ""}`;
  }
  return `${label}: mixed (${counts.map(([c, k]) => `${k} ${BALANCE_TERM[c]}`).join(", ")}) over ${plural(s.laps, "lap")}`;
}

/** "Mid-corner understeer", "Exit oversteer". */
export function symptomTitle(s: Pick<BalanceSymptom, "phase" | "cls">): string {
  return `${PHASE_TITLE[s.phase]} ${s.cls}`;
}

const PHASE_IN: Readonly<Record<Phase, string>> = { entry: "on entry", mid: "mid-corner", exit: "on the exit" };

/** A beginner's title, the plain words first: "Pushed wide mid-corner (understeer)". */
export function symptomTitleSimple(s: Pick<BalanceSymptom, "phase" | "cls">): string {
  return s.cls === "understeer" ? `Pushed wide ${PHASE_IN[s.phase]} (understeer)` : `Rear stepped out ${PHASE_IN[s.phase]} (oversteer)`;
}

/**
 * A beginner's line under a car symptom: a child's best lap is a weak control, so it says both possibilities. "On every
 * lap, including your best: it could be the car or how the corner is approached."
 */
export function symptomBeginnerLine(s: Pick<BalanceSymptom, "laps" | "laps_total">): string {
  const when = s.laps >= s.laps_total ? "On every lap" : `On ${s.laps} of ${plural(s.laps_total, "lap")}`;
  return `${when}, including your best: it could be the car or how the corner is approached.`;
}

/**
 * What was measured, without the title the card already shows: the backend's sentence after its first ": " ("At the
 * limit the front tyres ran 6.4° more slip angle than the rears (heuristic threshold 3°)."). The whole sentence when it
 * has no such part.
 */
export function symptomMeasure(text: string): string {
  const i = text.indexOf(": ");
  return i > 0 && i + 2 < text.length ? sentence(text.slice(i + 2)) : text;
}

function contentWords(t: string): Set<string> {
  return new Set(t.toLowerCase().split(/[^a-z-]+/).filter((w) => w.length >= 4));
}

/** Whether two sentences say much the same (the "Why" and the catalogue's effect often do): shared content words. */
export function sameIdea(a: string, b: string, min = 0.45): boolean {
  const x = contentWords(a);
  const y = contentWords(b);
  if (!x.size || !y.size) return false;
  let both = 0;
  for (const w of x) if (y.has(w)) both++;
  return both / (x.size + y.size - both) >= min;
}

/** "3 of 3 laps, including your best" (car) or "2 of 3 laps, not on your best lap" (driving). */
export function symptomLapsText(s: Pick<BalanceSymptom, "laps" | "laps_total" | "verdict">): string {
  const base = `${s.laps} of ${plural(s.laps_total, "lap")}`;
  return s.verdict === "car" ? `${base}, including your best` : `${base}, not on your best lap`;
}

export const VERDICT_WORDS: Readonly<Record<"car" | "driving", string>> = {
  car: "Even on your best lap: points at the car",
  driving: "Not on your best lap: points at how the corner was driven",
};

// ---------------------------------------------------------------------------------------------------- setup

/** A suggestion sized by nothing yet (the car format is unknown): "Front Anti-Roll Bar 15 → lower". */
export function suggestionDirection(s: Pick<SetupSuggestion, "label" | "from_value" | "unit" | "direction">, p?: ParameterInfo): string {
  const from = finite(s.from_value) ? `${p ? s.from_value.toFixed(p.decimals) : String(s.from_value)}${(p?.unit ?? s.unit) ? ` ${p?.unit ?? s.unit}` : ""}` : UNKNOWN;
  return `${s.label} ${from.startsWith("-") ? `${MINUS}${from.slice(1)}` : from} → ${s.direction}`;
}

/** A suggestion's change in menu units: "Front Anti-Roll Bar 9 → 7", "Front Brake Bias 58 % → 57 %". */
export function suggestionChange(s: Pick<SetupSuggestion, "label" | "from_value" | "to_value" | "unit">, p?: ParameterInfo): string {
  const fmt = (v: number | null) => {
    if (!finite(v)) return UNKNOWN;
    const t = p ? v.toFixed(p.decimals) : String(v);
    const signedT = t.startsWith("-") ? `${MINUS}${t.slice(1)}` : t;
    const unit = p?.unit ?? s.unit;
    return unit ? `${signedT} ${unit}` : signedT;
  };
  return `${s.label} ${fmt(s.from_value)} → ${fmt(s.to_value)}`;
}

// ---------------------------------------------------------------------------------------------------- laps

/** "4 of 6 laps used · lap 2 flashback · lap 5 pit in" (the reference itself is never counted). */
export function lapsUsedText(laps: readonly TechniqueLap[], refLapId: number | null | undefined): string | null {
  const others = laps.filter((l) => l.lap_id !== refLapId);
  if (!others.length) return null;
  const used = others.filter((l) => l.usable).length;
  const skipped = others
    .filter((l) => !l.usable)
    .map((l) => `lap ${l.lap_number}${l.reason ? ` ${l.reason}` : ""}`);
  return [`${used} of ${plural(others.length, "lap")} compared`, ...skipped].join(" · ");
}
