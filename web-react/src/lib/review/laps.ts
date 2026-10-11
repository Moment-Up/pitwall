// Session › Laps (spec 6.4): one row per lap with its time and sectors coloured by CURRENT STANDING (4.6: in a table
// only the times that are still the best are coloured), the gap to the reference lap, the status in words, and
// whether the lap can be the reference (clean laps only, as today). Pure; tested in node.
//
// The session's own best is green SB, slower laps yellow; the session's best LAP also carries REC or PB when it holds
// the family record or the driver's best ever here (`badge`: lib/bests.ts, the one rule shared with Drive and
// Progress, found in the session list; sector records need D2 and stay SB). Synthetic and replay sessions are outside
// the timing scope and carry no timing colours at all (kpis.timingEligible); a lap that is not clean is grey INV in
// every session (a fact about the lap, not a timing colour). The statuses come from Drive's `standing`, with its
// `coloured` switch, the same switch Drive takes from `bestsOf(...).coloured`.

import type { TimingStatus } from "../../components/ui/types";
import type { BestBadge } from "../bests";
import { standing } from "../drive/timing";
import type { SessionAnalysis } from "../endpoints/review";
import { timingEligible, type EvidenceTier, type KpiLap } from "./kpis";
import { finite, notCleanReason } from "./words";

export interface TimedCell {
  ms: number | null;
  status: TimingStatus;
}

export interface LapsRow {
  id: number;
  lapNumber: number;
  lap: TimedCell;
  sectors: [TimedCell, TimedCell, TimedCell];
  /** Lap minus the reference, seconds (+ = slower); null when the lap was not compared (or is the reference). */
  deltaS: number | null;
  /** This lap is the reference the page compares against. */
  isRef: boolean;
  clean: boolean;
  /** "Clean", or why not in words ("flashback", "invalid, pit in"). */
  statusText: string;
  /** Clean with a time: can be the reference (A). */
  canBeRef: boolean;
}

const positive = (v: unknown): v is number => finite(v) && v > 0;

/** Timing statuses of one column by current standing (tier 1: SB and slower; the best lap's REC / PB is applied by
 * `lapsRows` from the one rule), or
 * neutral / INV only outside the timing scope. */
function column(times: (number | null)[], clean: boolean[], coloured: boolean): TimingStatus[] {
  return standing(times, clean, { driver: null, household: null }, 1, coloured);
}

/**
 * The Laps table, in lap order. `analysis` gives the gaps (its comparisons are against `analysis.ref_lap_id`, which
 * may be a lap of another session); `session` decides whether timing colours apply.
 */
export function lapsRows(
  laps: readonly KpiLap[],
  analysis: Pick<SessionAnalysis, "ref_lap_id" | "comparisons"> | null | undefined,
  session: EvidenceTier,
  badge?: BestBadge | null,
): LapsRow[] {
  const ordered = [...laps].sort((a, b) => a.lap_number - b.lap_number);
  const coloured = timingEligible(session);
  const clean = ordered.map((l) => l.clean);
  const lapSt = column(
    ordered.map((l) => (positive(l.lap_time_ms) ? l.lap_time_ms : null)),
    clean,
    coloured,
  );
  // The session's best lap (the first of a tie, as summaryKpis picks it) takes the stronger badge it holds.
  if (coloured && (badge === "rec" || badge === "pb")) {
    const i = lapSt.indexOf("sb");
    if (i >= 0) lapSt[i] = badge;
  }
  const sectorSt = (["s1_ms", "s2_ms", "s3_ms"] as const).map((k) =>
    column(
      ordered.map((l) => (positive(l[k]) ? l[k] : null)),
      clean,
      coloured,
    ),
  );
  const refId = analysis?.ref_lap_id ?? null;
  return ordered.map((l, i) => {
    const cmp = analysis?.comparisons?.[String(l.id)];
    const isRef = refId != null && l.id === refId;
    const delta = !isRef && cmp && finite(cmp.total_delta_s) ? cmp.total_delta_s : null;
    return {
      id: l.id,
      lapNumber: l.lap_number,
      lap: { ms: positive(l.lap_time_ms) ? l.lap_time_ms : null, status: lapSt[i] ?? "neutral" },
      sectors: [0, 1, 2].map((s) => {
        const k = (["s1_ms", "s2_ms", "s3_ms"] as const)[s]!;
        return { ms: positive(l[k]) ? l[k] : null, status: sectorSt[s]?.[i] ?? "neutral" };
      }) as LapsRow["sectors"],
      deltaS: delta,
      isRef,
      clean: l.clean,
      statusText: notCleanReason(l) ?? "Clean",
      canBeRef: l.clean && positive(l.lap_time_ms),
    };
  });
}

/** Sort helper: unknown values always last, whatever the direction. */
export function compareNullable(a: number | null | undefined, b: number | null | undefined): number {
  const an = finite(a);
  const bn = finite(b);
  if (!an && !bn) return 0;
  if (!an) return 1;
  if (!bn) return -1;
  return a - b;
}

/** The line under the table: what the colours mean here (outside the timing scope: why there are none, in the words
 * Drive uses, lib/drive/timing.ts `legendOf`). */
export function lapsLegendText(session: EvidenceTier): string {
  if (!timingEligible(session)) {
    return session.synthetic
      ? "Synthetic data: times are not coloured, and never count as bests."
      : "A replay: times are not coloured, and never count as bests.";
  }
  return "Colours show the current standing: only the times that are still this session's best are green (SB); the best lap is purple REC when it is the family record here, green PB when it is your best ever here. Grey INV laps are not clean and are never a reference.";
}
