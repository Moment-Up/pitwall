// View models for the technique blocks (feat/technique spec §9): which corner Compare focuses, the line markers and
// corner rows, what the Corners cards summarise, which setup suggestions can be tried, and which availability reasons
// to show. Pure; tested in node. Words live in ./words.ts.

import type { CarFormat, ParameterInfo, SetupExperiment } from "../endpoints/carsetup";
import type {
  AssistInfo,
  BalanceSymptom,
  CompareCornerTechnique,
  LinePointKey,
  SetupEngineer,
  SetupSuggestion,
  TechniqueAvailability,
  TechniqueCompare,
  TechniqueCorner,
  TechniqueNote,
} from "../endpoints/technique";
import { BRAKE_ROWS, finite, POINT_LABEL, type InputRow } from "./words";

// ---------------------------------------------------------------------------------------------------- compare

/** A corner's lap-distance window (game metres) for the zoom and the offset chart: the window the API sent, else
 * turn-in − 40 to track-out + 40. */
export function compareWindowM(c: Pick<CompareCornerTechnique, "window" | "points">): [number, number] | null {
  const d = c.window?.d_m;
  if (d && d.length >= 2) {
    const a = d[0];
    const b = d[d.length - 1];
    if (finite(a) && finite(b)) return [a, b];
  }
  const ti = c.points.turn_in;
  const to = c.points.track_out;
  const ap = c.points.apex;
  if (finite(ti) && finite(to)) return [ti - 40, to + 40];
  if (finite(ap)) return [ap - 100, ap + 100];
  return null;
}

/** Whether lap distance `m` falls inside a corner's window. */
function inWindow(c: CompareCornerTechnique, m: number): boolean {
  const w = compareWindowM(c);
  return !!w && m >= w[0] && m <= w[1];
}

/**
 * The corner Compare's technique panel opens on: the corner under the shared cursor (the route's `at`), else the
 * first marker's corner (the biggest line difference), else the corner that lost most time, else the first.
 * Incidents never become the default.
 */
export function defaultFocus(cmp: Pick<TechniqueCompare, "corners" | "markers"> | null | undefined, cursorM?: number | null): string | null {
  if (!cmp || !cmp.corners.length) return null;
  const usable = cmp.corners.filter((c) => !c.incident);
  if (finite(cursorM)) {
    const at = usable.find((c) => inWindow(c, cursorM));
    if (at) return at.corner;
  }
  const marker = cmp.markers.find((m) => usable.some((c) => c.corner === m.corner));
  if (marker) return marker.corner;
  let worst: CompareCornerTechnique | null = null;
  for (const c of usable) if (finite(c.time_delta_s) && (!worst || c.time_delta_s > (worst.time_delta_s as number))) worst = c;
  return (worst ?? usable[0] ?? cmp.corners[0])!.corner;
}

export interface MarkerItem {
  n: number;
  corner: string;
  point: LinePointKey;
  d: number;
  xz: [number, number];
  /** "1: T4 apex: 1.8 m wider than your reference" (accessible name). */
  label: string;
  /** The backend's sentence (text_simple for simple wording). */
  text: string;
}

/** Numbered markers in the API's order (largest difference first), with their sentence. */
export function markerItems(cmp: Pick<TechniqueCompare, "markers"> | null | undefined, simple: boolean): MarkerItem[] {
  return (cmp?.markers ?? []).map((m, i) => {
    const text = simple && m.text_simple ? m.text_simple : m.text;
    return { n: i + 1, corner: m.corner, point: m.point, d: m.d_m, xz: m.xz, label: `${i + 1}: ${text}`, text };
  });
}

/** The reference's turn-in / apex / track-out for the zoomed map (known points only). */
export function zoomPoints(c: Pick<CompareCornerTechnique, "points">): { label: string; d: number }[] {
  return (["turn_in", "apex", "track_out"] as const)
    .filter((k) => finite(c.points[k]))
    .map((k) => ({ label: POINT_LABEL[k], d: c.points[k] as number }));
}

/** The biggest |offset| of a corner's three points (null when none is known). */
export function biggestOffset(c: Pick<CompareCornerTechnique, "offsets">): { point: LinePointKey; offset: number } | null {
  let best: { point: LinePointKey; offset: number } | null = null;
  for (const k of ["turn_in", "apex", "track_out"] as const) {
    const v = c.offsets[k];
    if (finite(v) && (!best || Math.abs(v) > Math.abs(best.offset))) best = { point: k, offset: v };
  }
  return best;
}

// ---------------------------------------------------------------------------------------------------- inputs

/**
 * Whether a row is greyed: a brake row while the game's braking assist is on (its figures are not all the driver's),
 * or a row whose note the backend muted.
 */
export function rowMuted(row: InputRow, assists: Pick<AssistInfo, "braking_assist"> | null | undefined, notes: readonly TechniqueNote[] = []): boolean {
  if (BRAKE_ROWS.has(row) && finite(assists?.braking_assist) && (assists?.braking_assist as number) > 0) return true;
  return notes.some((n) => n.muted && rowOfMetric(n.metric) === row);
}

function rowOfMetric(m: TechniqueNote["metric"]): InputRow | null {
  switch (m) {
    case "lockup":
    case "wheelspin":
      return "slip";
    case "brake_peak":
    case "time_to_peak":
    case "release":
    case "brake_at_turn_in":
    case "trail_overlap":
    case "coast":
    case "throttle_pickup":
    case "throttle_ramp":
    case "throttle_lifts":
      return m;
  }
}

/** The assist note to show beside muted rows (the API's braking assist sentence), else a plain fallback. */
export function brakingAssistNote(assists: AssistInfo | null | undefined): string | null {
  if (!assists || !finite(assists.braking_assist) || assists.braking_assist <= 0) return null;
  return (
    assists.notes.find((n) => /braking assist/i.test(n)) ??
    "Braking assist is on: the game adds its own braking, so these brake figures are not all yours."
  );
}

/** Notes worth listing under a corner: notable, not muted (muted notes stay in the greyed table rows only). */
export function shownNotes(notes: readonly TechniqueNote[] | null | undefined): TechniqueNote[] {
  return (notes ?? []).filter((n) => n.notable && !n.muted);
}

// ---------------------------------------------------------------------------------------------------- corners tab

export interface SlipTotals {
  lockups: string | null;
  wheelspin: string | null;
}

/**
 * Lock-ups and wheelspin over the session's compared laps at one corner: "ABS on: no lock-up data", "No lock-ups",
 * "2 lock-ups on 1 of 8 laps"; wheelspin likewise. Null parts are unknown (no slip data) or not applicable.
 */
export function slipTotals(c: Pick<TechniqueCorner, "laps">): SlipTotals {
  const laps = c.laps.filter((l) => l.clean && !l.incident && l.inputs);
  if (!laps.length) return { lockups: null, wheelspin: null };
  const lock = laps.map((l) => l.inputs!.lockup);
  const spin = laps.map((l) => l.inputs!.wheelspin);
  let lockups: string | null = null;
  if (lock.some((e) => e.status === "abs_on")) lockups = "ABS on: no lock-up data";
  else {
    const measured = lock.filter((e) => e.status === "measured" && finite(e.events));
    if (measured.length) {
      const events = measured.reduce((a, e) => a + (e.events as number), 0);
      const lapsWith = measured.filter((e) => (e.events as number) > 0).length;
      lockups = events ? `${events} lock-up${events === 1 ? "" : "s"} on ${lapsWith} of ${measured.length} laps` : "No lock-ups";
    }
  }
  let wheelspin: string | null = null;
  const sm = spin.filter((e) => e.status === "measured" && finite(e.events));
  if (sm.length) {
    const lapsWith = sm.filter((e) => (e.events as number) > 0).length;
    const tc = sm.find((e) => finite(e.tc_level) && (e.tc_level as number) > 0);
    wheelspin = lapsWith
      ? `Wheelspin on ${lapsWith} of ${sm.length} laps${tc ? " (traction control on)" : ""}`
      : `No wheelspin${tc ? " (traction control on)" : ""}`;
  }
  return { lockups, wheelspin };
}

/** The technique of one learned corner, or null. */
export function techniqueCorner<T extends { corner: string }>(corners: readonly T[] | null | undefined, key: string): T | null {
  return corners?.find((c) => c.corner === key) ?? null;
}

// ---------------------------------------------------------------------------------------------------- setup

export interface SymptomView {
  symptom: BalanceSymptom;
  /** `to_value` / `hypothesis` completed for the page's car format when the server could not tell it (`forFormat`). */
  suggestions: (SetupSuggestion & {
    blockedNow: string | null;
    forFormat: CarFormat | null;
    /** The same change is already listed under an earlier symptom (its id): shown once, with its button there. */
    duplicateOf: string | null;
  })[];
}

/**
 * A suggestion's new value in one car format's menu: from ± its trial steps (menu units), snapped onto the format's
 * range like carsetup's Range.snap. The page sends its car format (`?car_format=`), so the server normally sizes the
 * suggestion itself; this is the fallback for a server that still could not (`setup.car_format` null). Null when
 * anything is unknown.
 */
export function valueForFormat(
  x: Pick<SetupSuggestion, "from_value" | "steps" | "direction">,
  p: Pick<ParameterInfo, "ranges"> | undefined,
  format: CarFormat | null | undefined,
): number | null {
  if (!format || !p || !finite(x.from_value) || !finite(x.steps)) return null;
  const r = p.ranges[format];
  if (!r || !(r.step > 0)) return null;
  const v = x.from_value + (x.direction === "higher" ? 1 : -1) * x.steps;
  const k = Math.round((v - r.min) / r.step);
  const snapped = Math.min(r.max, Math.max(r.min, r.min + k * r.step));
  return Math.round(snapped * 1e6) / 1e6;
}

function menuText(v: number, p: Pick<ParameterInfo, "decimals" | "unit"> | undefined): string {
  const t = p ? v.toFixed(p.decimals) : String(v);
  return p?.unit ? `${t} ${p.unit}` : t;
}

/** An open experiment from this session on this parameter: the suggestion is already being tried. */
export function alreadyTrying(experiments: readonly SetupExperiment[], sid: string, parameter: string): boolean {
  return experiments.some(
    (e) => (e.status === "proposed" || e.status === "running") && e.before_session_id === sid && e.parameter === parameter,
  );
}

export const ALREADY_TRYING = "Already in your experiments from this session";

/**
 * Car symptoms with their suggestions (rank order), driving symptoms with none (spec §4.3: driving symptoms never get
 * setup suggestions). `blockedNow` is the backend's reason, or "already in your experiments" when one was proposed
 * since the page loaded (the experiments list refreshes on every proposal), or the synthetic rule.
 */
export function symptomViews(
  symptoms: readonly BalanceSymptom[],
  setup: (Pick<SetupEngineer, "suggestions"> & Partial<Pick<SetupEngineer, "car_format">>) | null | undefined,
  opts: {
    experiments?: readonly SetupExperiment[];
    sid?: string;
    synthetic?: boolean;
    /** The car format the Setup page knows (the driver's choice or the game's), used when the server had none. */
    carFormat?: CarFormat | null;
    params?: ReadonlyMap<string, ParameterInfo>;
  } = {},
): { car: SymptomView[]; driving: BalanceSymptom[] } {
  const car: SymptomView[] = [];
  const driving: BalanceSymptom[] = [];
  const listed = new Map<string, string>(); // "parameter:direction" -> the first symptom listing it
  for (const s of symptoms) {
    if (s.verdict === "driving") {
      driving.push(s);
      continue;
    }
    const suggestions = (setup?.suggestions ?? [])
      .filter((x) => x.symptom_id === s.id)
      .sort((a, b) => a.rank - b.rank)
      .map((x) => {
        let blockedNow = x.blocked;
        let out: SetupSuggestion = x;
        let forFormat: CarFormat | null = null;
        if (x.to_value === null && setup?.car_format == null && opts.carFormat) {
          const p = opts.params?.get(x.parameter);
          const to = valueForFormat(x, p, opts.carFormat);
          if (to !== null && finite(x.from_value)) {
            forFormat = opts.carFormat;
            out = { ...x, to_value: to, hypothesis: x.hypothesis.replace(/ -> unknown:/, ` -> ${menuText(to, p)}:`) };
            blockedNow =
              Math.abs(to - x.from_value) < 1e-9
                ? `${x.label} is already at its ${x.direction === "lower" ? "minimum" : "maximum"} for this car.`
                : null;
          }
        }
        if (!blockedNow && opts.synthetic) blockedNow = "Synthetic session: generated data, not your car";
        if (!blockedNow && opts.sid && opts.experiments && alreadyTrying(opts.experiments, opts.sid, x.parameter)) blockedNow = ALREADY_TRYING;
        if (!blockedNow && (out.to_value === null || out.from_value === null)) blockedNow = "Your setup for this session is unknown";
        const key = `${x.parameter}:${x.direction}`;
        const duplicateOf = listed.get(key) ?? null;
        if (!duplicateOf) listed.set(key, s.id);
        return { ...out, blockedNow, forFormat, duplicateOf };
      });
    car.push({ symptom: s, suggestions });
  }
  return { car, driving };
}

// ---------------------------------------------------------------------------------------------------- availability

export type AvailabilityKey = keyof TechniqueAvailability;

/** The reasons to show for parts that are not available (one line each, duplicates merged). */
export function unavailableReasons(a: TechniqueAvailability | null | undefined, keys: readonly AvailabilityKey[]): string[] {
  if (!a) return [];
  const out: string[] = [];
  for (const k of keys) {
    const v = a[k];
    if (v && !v.ok && v.reason && !out.includes(v.reason)) out.push(v.reason);
  }
  return out;
}

/** The notes the API attached to available parts (heuristic thresholds, derived distance, post-assist pedals). */
export function availabilityNotes(a: TechniqueAvailability | null | undefined, keys: readonly AvailabilityKey[]): string[] {
  if (!a) return [];
  const out: string[] = [];
  for (const k of keys) {
    const v = a[k];
    if (v && v.ok && v.note && !out.includes(v.note)) out.push(v.note);
  }
  return out;
}
