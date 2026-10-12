// Summary KPI tiles (spec 6.3 #1): best lap, clean laps, gained today, steadiness; advanced adds best sectors
// combined and the gap to your best ever. Derived from the session's own laps (GET /api/sessions/{id}) and the bests
// of its scope (lib/bests.ts `sessionBests`, from the session list); pure, tested in node.
//
// Timing colours (4.6): ONE rule with Drive and Progress (lib/bests.ts): scope game + track + car + layout, clean laps
// only, never synthetic or replay sessions; REC = household record, PB = the driver's best ever, SB = the session's
// best, the strongest badge that applies wins. Gains and gaps are said in words ("5.8 s faster", "0.40 s slower"),
// never as a bare signed number (bests.ts `changeWords`).

import type { TimingStatus } from "../../components/ui/types";
import { changeWords, gapWords, hasScope, type BestBadge, type ChangeText, type SessionBests } from "../bests";
import { lapTime } from "../format";
import { dayInSentence, finite, notCleanReason, plural } from "./words";

/** The lap fields the KPIs need (LapRow). */
export interface KpiLap {
  id: number;
  lap_number: number;
  lap_time_ms: number | null;
  s1_ms: number | null;
  s2_ms: number | null;
  s3_ms: number | null;
  valid: boolean | null;
  clean: boolean;
  flags: readonly string[];
}

export interface LapRef {
  lapId: number;
  lapNumber: number;
  ms: number;
}

export interface SummaryKpis {
  /** Laps recorded. */
  total: number;
  /** Clean laps (valid, no pit, flashback, pause or data gap). */
  clean: number;
  /** Laps not used, oldest first, with the reason in words. */
  notUsed: { lapNumber: number; reason: string }[];
  /** Fastest clean lap. */
  best: LapRef | null;
  /** First clean lap (by lap number). */
  first: LapRef | null;
  /** First clean lap minus the best clean lap, ms (>= 0); null with fewer than 2 clean laps. */
  gainedMs: number | null;
  /** Slowest minus fastest clean lap, ms; null with fewer than 2 clean laps. */
  spreadMs: number | null;
  /** Best of each sector over the clean laps (null where unknown). */
  bestSectorsMs: [number | null, number | null, number | null];
  /** Sum of the three best sectors; null unless all three are known. */
  bestSectorsCombinedMs: number | null;
}

function timed(l: KpiLap): l is KpiLap & { lap_time_ms: number } {
  return finite(l.lap_time_ms) && l.lap_time_ms > 0;
}

export function summaryKpis(laps: readonly KpiLap[]): SummaryKpis {
  const ordered = [...laps].sort((a, b) => a.lap_number - b.lap_number);
  const clean = ordered.filter((l) => l.clean && timed(l)) as (KpiLap & { lap_time_ms: number })[];
  const ref = (l: KpiLap & { lap_time_ms: number }): LapRef => ({ lapId: l.id, lapNumber: l.lap_number, ms: l.lap_time_ms });

  let best: LapRef | null = null;
  for (const l of clean) if (!best || l.lap_time_ms < best.ms) best = ref(l);
  const firstLap = clean[0];
  const first = firstLap ? ref(firstLap) : null;
  const times = clean.map((l) => l.lap_time_ms);
  const two = clean.length >= 2;

  const sectorBest = (k: "s1_ms" | "s2_ms" | "s3_ms"): number | null => {
    const v = clean.map((l) => l[k]).filter((x): x is number => finite(x) && x > 0);
    return v.length ? Math.min(...v) : null;
  };
  const bestSectorsMs: [number | null, number | null, number | null] = [
    sectorBest("s1_ms"),
    sectorBest("s2_ms"),
    sectorBest("s3_ms"),
  ];
  const [a, b, c] = bestSectorsMs;

  return {
    total: ordered.length,
    clean: clean.length,
    notUsed: ordered
      .filter((l) => !l.clean)
      .map((l) => ({ lapNumber: l.lap_number, reason: notCleanReason(l) ?? "not clean" })),
    best,
    first,
    gainedMs: two && first && best ? Math.max(0, first.ms - best.ms) : null,
    spreadMs: two ? Math.max(...times) - Math.min(...times) : null,
    bestSectorsMs,
    bestSectorsCombinedMs: a != null && b != null && c != null ? a + b + c : null,
  };
}

/** "3 not used: flashback, invalid" (each reason once, in lap order); null when every lap was clean. */
export function notUsedText(k: Pick<SummaryKpis, "notUsed">): string | null {
  if (!k.notUsed.length) return null;
  const reasons = [...new Set(k.notUsed.flatMap((n) => n.reason.split(", ")))];
  return `${k.notUsed.length} not used: ${reasons.join(", ")}`;
}

/** "9 of 12" clean laps sub line, or "No laps recorded". */
export function cleanLapsText(k: Pick<SummaryKpis, "clean" | "total">): string {
  return k.total ? `${k.clean} of ${k.total}` : "No laps recorded";
}

export interface EvidenceTier {
  synthetic?: boolean | null;
  source?: string | null;
}

/** A replayed capture (source "replay:…"): nobody's driving, never a PB or reference. */
export function isReplaySource(source: string | null | undefined): boolean {
  return typeof source === "string" && source.startsWith("replay:");
}

/**
 * Whether a session is in the timing scope (4.6): never synthetic or replay. Outside it a session's times carry no
 * timing colour at all (no REC / PB / SB / yellow; grey INV stays, it is a fact about the lap), never count as a
 * best and are never offered as a reference. One rule set with Drive: lib/drive/timing.ts `inTimingScope` /
 * `BestsView.coloured`.
 */
export function timingEligible(s: EvidenceTier): boolean {
  return s.synthetic !== true && !isReplaySource(s.source);
}

/**
 * The best lap's status (spec 4.6, lib/bests.ts): the session's badge once its scope's bests are known (REC / PB),
 * else SB, which a real session's best lap always is; neutral for synthetic and replay data.
 */
export function bestLapStatus(s: EvidenceTier, best: LapRef | null, badge?: BestBadge | null): TimingStatus {
  if (!best || !timingEligible(s)) return "neutral";
  return badge === "rec" || badge === "pb" ? badge : "sb";
}

/** The Best lap tile's sub line: "lap 64", "lap 64 · your best ever here", "lap 64 · the family record here". */
export function bestLapSub(best: LapRef | null, status: TimingStatus = "neutral"): string {
  if (!best) return "No clean lap yet";
  const lap = `lap ${best.lapNumber}`;
  if (status === "rec") return `${lap} · the family record here`;
  if (status === "pb") return `${lap} · your best ever here`;
  return lap;
}

/** F1 one-shot qualifying ("One-Shot Qualifying", "One-Shot Sprint Shootout"): one timed lap by design. */
export function isOneShot(sessionType: string | null | undefined): boolean {
  return typeof sessionType === "string" && /^one-shot\b/i.test(sessionType.trim());
}

/** Said instead of "Needs a second clean lap" in one-shot qualifying, where a second lap is impossible. */
export const ONE_SHOT_SUB = "One-shot qualifying has one timed lap";

/** The Gained today tile: the change in words ("5.8 s faster", "level"), never a bare signed number (spec 6.3,
 * 9.6, bests.ts `changeWords`); null with fewer than two clean laps (`oneShot`: one-shot qualifying says why). */
export function gainedView(
  k: Pick<SummaryKpis, "gainedMs" | "first" | "best" | "clean">,
  oneShot = false,
): {
  change: ChangeText | null;
  sub: string;
} {
  if (k.gainedMs == null || !k.first || !k.best) {
    if (oneShot && k.clean <= 1) return { change: null, sub: ONE_SHOT_SUB };
    return { change: null, sub: k.clean === 1 ? "Needs a second clean lap" : "Needs 2 clean laps" };
  }
  const change = changeWords(k.best.ms - k.first.ms);
  if (!change || change.word === "level") {
    return { change, sub: `Your first clean lap (lap ${k.first.lapNumber}) was your best` };
  }
  return { change, sub: `First clean lap (lap ${k.first.lapNumber}) → best lap (lap ${k.best.lapNumber})` };
}

/** The Gap to your best ever tile (spec 6.3): this session's best against the driver's best ever here (same game,
 * track, car and layout: bests.ts). `pb`: this session set it. */
export interface GapView {
  change: ChangeText | null;
  pb: boolean;
  sub: string;
}

/**
 * The gap from this session's best lap to its driver's best ever in this scope, from `sessionBests` (null while
 * loading). Honest about what cannot be known: synthetic and replay data, no driver, an unknown car, no clean lap.
 */
export function gapToBestEver(
  session: EvidenceTier & { id: string; driver_id: number | null; track_id: string | null; car_id?: string | null },
  best: LapRef | null,
  b: SessionBests | null | undefined,
  nowMs: number,
): GapView {
  const none = (sub: string): GapView => ({ change: null, pb: false, sub });
  if (!timingEligible(session)) {
    return none(session.synthetic ? "Synthetic data never counts as a best" : "A replay never counts as a best");
  }
  if (session.driver_id == null) return none("This session has no driver");
  if (!hasScope(session)) return none(session.track_id ? "Car unknown: no best to compare with" : "Track unknown: no best to compare with");
  if (!best) return none("Needs a clean lap");
  if (!b) return none("Loading the bests…");
  const d = b.driver;
  if (!d || !b.scoped) return none("No earlier best on this track and car yet");
  if (d.sessionId === session.id) {
    if (!b.certain.driver) return none("Your best here may be older than the sessions loaded");
    const prev = b.previous;
    const gain = prev ? gapWords(best.ms - prev.ms) : null;
    return {
      change: null,
      pb: true,
      sub:
        prev && gain && gain.word === "faster"
          ? `${gain.text} than your earlier best, ${lapTime(prev.ms)}`
          : "No earlier best on this track and car yet",
    };
  }
  const when = dayInSentence(d.startedUnix, nowMs);
  return {
    change: gapWords(best.ms - d.ms),
    pb: false,
    sub: `Your best ever ${lapTime(d.ms)}, ${when}${b.certain.driver ? "" : " (in the sessions loaded)"}`,
  };
}

/** The Steadiness tile's sentence: "your clean laps were within 1.4 s of each other". */
export function steadinessSentence(spreadMs: number | null, oneShot = false): string {
  if (spreadMs == null) return oneShot ? ONE_SHOT_SUB : "Needs 2 clean laps";
  const s = spreadMs / 1000;
  return `Your clean laps were within ${s.toFixed(s >= 0.995 ? 1 : 2)} s of each other`;
}

/** "12 laps", or "9 of 12 clean" once D5 sends `clean_lap_count` (spec 6.1). */
export function lapsText(row: { lap_count: number; clean_lap_count?: number | null }): string {
  if (finite(row.clean_lap_count)) return `${row.clean_lap_count} of ${row.lap_count} clean`;
  return plural(row.lap_count, "lap");
}
