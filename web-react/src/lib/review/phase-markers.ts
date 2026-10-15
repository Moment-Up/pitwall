// Compare's corner phase markers and g-force availability (technique knowledge spec section 4). Pure; tested in node.
//
// Phase markers: for the corner Compare is looking at, where each lap reached four points of the corner, from the
// comparison's per-lap CornerMetrics (analysis/compare.py; `ref` and `cmp` on each corner of GET /api/compare, game
// lap metres): brake on (`brake_start_m`), brake off (`brake_end_m`), the slowest point (`min_speed_m`) and full
// throttle (`throttle_full_m`). There is no turn-in marker: Pitwall does not measure turn-in in these metrics. A point
// a lap did not reach or Pitwall did not measure (no braking, never flat out before the next corner) stays unknown:
// no line and "not measured" in the key, never a guessed position.
//
// G-forces: the trace endpoint sends g_lat / g_lon for every lap, null where the game sends none (GT7 has no lateral
// g; adapters' AdapterInfo.fields). A chart with no value on either lap is hidden rather than drawn empty.

import type { LapTrace } from "../api";
import type { CornerMetrics, ReviewCornerDelta } from "../endpoints/review";
import { cornerAt, type CompareCorner } from "./compare";
import type { TraceMarker } from "../viz/charts";
import { finite } from "../viz/scale";

export type PhaseMarkerKey = "brake_start" | "brake_release" | "slowest" | "full_throttle";

interface PhaseMarkerDef {
  key: PhaseMarkerKey;
  /** Plain words for the key and the chart lines' names. */
  label: string;
  field: keyof Pick<CornerMetrics, "brake_start_m" | "brake_end_m" | "min_speed_m" | "throttle_full_m">;
}

/** In driving order. */
export const PHASE_MARKERS: readonly PhaseMarkerDef[] = [
  { key: "brake_start", label: "Brake on", field: "brake_start_m" },
  { key: "brake_release", label: "Brake off", field: "brake_end_m" },
  { key: "slowest", label: "Slowest point", field: "min_speed_m" },
  { key: "full_throttle", label: "Full throttle", field: "throttle_full_m" },
];

/** Positions closer than this are "the same place" (the trace grid is 5 m; the metrics are metre-level). */
export const SAME_PLACE_M = 1;

export interface PhaseMarkerRow {
  key: PhaseMarkerKey;
  label: string;
  /** Game lap metres on the reference (lap A), or null when not measured. */
  refM: number | null;
  /** Game lap metres on your lap (lap B), or null when not measured. */
  lapM: number | null;
  /** lapM - refM (negative = earlier on your lap), or null unless both are known. */
  deltaM: number | null;
  /** Your lap against lap A: "2 m earlier than the reference", "same place as the reference", "only measured on your
   * lap", "not measured". */
  words: string;
  /** Where "show it" moves the cursor: your lap's point, else the reference's. */
  at: number | null;
}

function metresOf(m: CornerMetrics | null | undefined, field: PhaseMarkerDef["field"]): number | null {
  const v = m?.[field];
  return finite(v) ? v : null;
}

/** Your lap's point against lap A's, in words (a description, never advice). `refWord` names lap A in a sentence
 * ("the reference", "your target lap", "Sam's best": lib/review/compare.ts refWordsFor). */
export function phaseDeltaWords(refM: number | null, lapM: number | null, refWord = "the reference"): string {
  if (refM == null && lapM == null) return "not measured";
  if (refM == null) return "only measured on your lap";
  if (lapM == null) return `only measured on ${refWord}`;
  const d = lapM - refM;
  if (Math.abs(d) < SAME_PLACE_M) return `same place as ${refWord}`;
  return `${Math.round(Math.abs(d))} m ${d < 0 ? "earlier" : "later"} than ${refWord}`;
}

/**
 * The four phase points of one corner of a comparison, in driving order. Points neither lap has are left out; an
 * empty list means nothing to mark (a corner without metrics, an older server without `ref` / `cmp`).
 */
export function phaseMarkerRows(corner: ReviewCornerDelta | null | undefined, refWord = "the reference"): PhaseMarkerRow[] {
  if (!corner) return [];
  const out: PhaseMarkerRow[] = [];
  for (const def of PHASE_MARKERS) {
    const refM = metresOf(corner.ref, def.field);
    const lapM = metresOf(corner.cmp, def.field);
    if (refM == null && lapM == null) continue;
    out.push({
      key: def.key,
      label: def.label,
      refM,
      lapM,
      deltaM: refM != null && lapM != null ? lapM - refM : null,
      words: phaseDeltaWords(refM, lapM, refWord),
      at: lapM ?? refM,
    });
  }
  return out;
}

/** The rows as chart lines: the reference dashed in its colour, your lap solid in its colour. */
export function phaseTraceMarkers(
  rows: readonly PhaseMarkerRow[],
  colours: { ref: string; lap: string },
  refLabel = "Reference",
): TraceMarker[] {
  const out: TraceMarker[] = [];
  for (const r of rows) {
    if (r.refM != null) out.push({ id: `${r.key}:ref`, d: r.refM, colour: colours.ref, dash: "4 3", label: `${r.label}, ${refLabel}` });
    if (r.lapM != null) out.push({ id: `${r.key}:lap`, d: r.lapM, colour: colours.lap, label: `${r.label}, your lap` });
  }
  return out;
}

/** The corner a comparison has under `key` (the learned corner name), or null. */
export function comparisonCorner(
  corners: readonly ReviewCornerDelta[] | null | undefined,
  key: string | null | undefined,
): ReviewCornerDelta | null {
  if (!key) return null;
  return corners?.find((c) => c.corner === key) ?? null;
}

/** A phase point the key moved the cursor to: that corner stays in focus while the cursor rests there (a brake point
 * can sit nearer the previous corner's stretch, which would otherwise take the focus and swap the markers). */
export interface PhasePin {
  key: string;
  at: number;
}

/** The corner Compare is looking at: the pinned one while the cursor is exactly at its point, else the corner at the
 * cursor (lib/review/compare.ts cornerAt); null when there is none. */
export function focusKeyAt(corners: readonly CompareCorner[], at: number | null, pin?: PhasePin | null): string | null {
  if (pin && at === pin.at && corners.some((c) => c.key === pin.key)) return pin.key;
  return cornerAt(corners, at)?.key ?? null;
}

// ---- g-forces --------------------------------------------------------------------------------------------------

type GTrace = Partial<Pick<LapTrace, "g_lat" | "g_lon">>;

/** Whether a trace has at least one measured value on a channel (absent, empty or all null = no). */
export function hasValues(values: readonly (number | null)[] | null | undefined): boolean {
  return !!values?.some((v) => finite(v));
}

/** Which g-force charts have something to draw on either lap: GT7 sends no g, so neither shows. */
export function gForceAvailable(ref: GTrace | null | undefined, lap: GTrace | null | undefined): { lat: boolean; lon: boolean } {
  return {
    lat: hasValues(ref?.g_lat) || hasValues(lap?.g_lat),
    lon: hasValues(ref?.g_lon) || hasValues(lap?.g_lon),
  };
}
