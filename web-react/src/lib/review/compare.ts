// Session › Compare (spec 6.5): which two laps, the picker options, the corners of the comparison in plain words,
// the corner explainer, the corner table by density, and the metres the cursor works in. Pure; tested in node.
//
// Distances: the traces (`/api/laps/{id}/trace`), the comparison's `delta_d` and the cursor are GAME lap metres
// (the session's `track_length_m`). The track model's corners are in MODEL metres (its own `length_m`); for F1 the two
// lengths are the same, elsewhere they can differ by a few metres, so corner positions are scaled into game metres.
// The route's `at=` is game metres.
//
// Words are descriptions of measured differences (lap minus reference), never advice (P9): a negative brake point is
// braking earlier, a negative speed is slower, a positive time is time lost, a positive full-throttle distance is
// later.

import type { LapTrace } from "../api";
import type { TimingStatus } from "../../components/ui/types";
import type { Driver } from "../drivers";
import type { CandidatesResponse, RefOption } from "../endpoints/coachref";
import type { RefLap, ReviewCornerDelta, ReviewObservation, ReviewTrackModel } from "../endpoints/review";
import { UNKNOWN, lapTime, MINUS } from "../format";
import { cornerIdentity, type CornerIdentity } from "./corners";
import type { Density } from "./density";
import { isReplaySource, timingEligible, type EvidenceTier } from "./kpis";
import type { LapsRow } from "./laps";
import { INCIDENT_KIND } from "./coaching";
import { cornerWords, finite, joinAnd, plural, sentence, whyText } from "./words";

// ---- route -------------------------------------------------------------------------------------------------------

export interface CompareQuery {
  ref: number | null;
  lap: number | null;
  /** Cursor, game lap metres. */
  at: number | null;
}

function positiveInt(v: string | null): number | null {
  if (v == null || v.trim() === "") return null;
  const n = Number(v);
  return Number.isInteger(n) && n > 0 ? n : null;
}

/** `?ref=<lap_id>&lap=<lap_id>&at=<metres>`; anything malformed is left unknown. */
export function parseCompareQuery(q: URLSearchParams): CompareQuery {
  const at = q.get("at");
  const atN = at != null && at.trim() !== "" ? Number(at) : NaN;
  return { ref: positiveInt(q.get("ref")), lap: positiveInt(q.get("lap")), at: Number.isFinite(atN) && atN >= 0 ? atN : null };
}

/**
 * The two laps to compare when the route does not say: A = the route's `ref`, else the analysis' reference (the
 * pinned reference or the driver's best), else the session's fastest clean lap. B = the route's `lap`, else the
 * newest clean lap that is not A, else the newest timed lap that is not A.
 */
export function defaultPair(
  rows: readonly Pick<LapsRow, "id" | "lapNumber" | "lap" | "canBeRef">[],
  analysisRefLapId: number | null | undefined,
  q: Pick<CompareQuery, "ref" | "lap">,
): { ref: number | null; lap: number | null } {
  let ref = q.ref ?? analysisRefLapId ?? null;
  if (ref == null) {
    let best: (typeof rows)[number] | null = null;
    for (const r of rows) if (r.canBeRef && r.lap.ms != null && (!best || r.lap.ms < (best.lap.ms as number))) best = r;
    ref = best?.id ?? null;
  }
  let lap = q.lap;
  if (lap == null) {
    const newestFirst = [...rows].sort((a, b) => b.lapNumber - a.lapNumber);
    lap =
      newestFirst.find((r) => r.id !== ref && r.canBeRef)?.id ??
      newestFirst.find((r) => r.id !== ref && r.lap.ms != null)?.id ??
      null;
  }
  return { ref, lap };
}

// ---- picker options -----------------------------------------------------------------------------------------------

export interface LapOption {
  id: number;
  /** "Lap 64", "Alex's best", "Your reference". */
  title: string;
  /** Where it comes from when not this session ("another session", "Haas"). */
  detail: string | null;
  ms: number | null;
  status: TimingStatus;
  sectors: { ms: number | null; status: TimingStatus }[];
  /** "Clean", "flashback", ... */
  words: string;
  group: "session" | "reference" | "family";
  /** Can be the reference (A): clean laps only. */
  canBeRef: boolean;
  /** coachref: listed but not selectable (another driver's lap that cannot be compared); `reason` says why. */
  disabled?: boolean;
  reason?: string | null;
}

function fromRow(r: LapsRow): LapOption {
  return {
    id: r.id,
    title: `Lap ${r.lapNumber}`,
    detail: null,
    ms: r.lap.ms,
    status: r.lap.status,
    sectors: r.sectors,
    words: r.statusText,
    group: "session",
    canBeRef: r.canBeRef,
  };
}

const NO_SECTORS = [
  { ms: null, status: "neutral" as TimingStatus },
  { ms: null, status: "neutral" as TimingStatus },
  { ms: null, status: "neutral" as TimingStatus },
];

/** Options for B ("Your lap"): every lap of this session. */
export function lapOptions(rows: readonly LapsRow[]): LapOption[] {
  return rows.map(fromRow);
}

export interface RefOptionsInput {
  rows: readonly LapsRow[];
  session: { id: string; game: string; track_id: string | null; driver_id: number | null } & EvidenceTier;
  /** The analysis' reference (may belong to another session of the same track and car). */
  analysisRef: RefLap | null | undefined;
  drivers: readonly Driver[];
  /** The selected A when it is none of the above (an old link): described from its trace. */
  selectedTrace?: Pick<LapTrace, "lap_id" | "lap_number" | "lap_time_ms"> | null;
  /** coachref: GET /api/coachref/candidates for lap B (compatible family laps, the others with a reason). When
   * present it replaces the `stats.best_laps` family group (any car, so often blocked). */
  candidates?: CandidatesResponse | null;
}

// --- coachref: picker A's family group from /api/coachref/candidates ---
const DAY_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function shortDay(unix: number | null | undefined): string | null {
  if (!finite(unix)) return null;
  const d = new Date(unix * 1000);
  return `${d.getDate()} ${DAY_MONTHS[d.getMonth()] ?? ""}`;
}

/** Family options for picker A from the candidates (spec 10.5): each compatible lap selectable; the unavailable ones
 * listed, disabled, with the server's reason ("Sam's laps here used a different braking assist"). */
export function candidateOptions(c: CandidatesResponse, seen: ReadonlySet<number>): LapOption[] {
  const out: LapOption[] = [];
  const listed = new Set(seen);
  let missing = 0;
  for (const g of c.groups) {
    for (const o of g.options as RefOption[]) {
      const lap = o.lap;
      const off = o.available === false;
      // One row a lap (the family record is often someone's best too): the first label wins.
      if (lap && listed.has(lap.lap_id)) continue;
      if (lap) listed.add(lap.lap_id);
      if (!lap && !off) continue;
      const who = g.id === "own" ? null : (lap?.driver_name ?? null);
      out.push({
        // A row with no lap gets a negative id: never a lap, never selectable.
        id: lap ? lap.lap_id : -(++missing),
        title: o.label,
        detail: off ? (o.reason ?? "Not comparable") : [who && !o.label.includes(who) ? who : null, lap?.car_name, shortDay(lap?.set_unix)].filter(Boolean).join(" · ") || null,
        ms: lap && finite(lap.lap_time_ms) ? lap.lap_time_ms : null,
        status: "neutral",
        sectors: NO_SECTORS,
        words: "Clean",
        group: "family",
        canBeRef: !off && !!lap,
        disabled: off || !lap,
        reason: off ? (o.reason ?? null) : null,
      });
    }
  }
  return out;
}

/**
 * Options for A ("Reference"): the clean laps of this session, the analysis' reference when it is a lap of another
 * session, and each family driver's best lap at this track (`stats.best_laps`, per game + track: the car may differ,
 * which /api/compare checks). Synthetic bests and synthetic or replay sessions never offer family laps.
 */
export function refOptions(input: RefOptionsInput): LapOption[] {
  const out: LapOption[] = input.rows.filter((r) => r.canBeRef).map(fromRow);
  const seen = new Set(input.rows.map((r) => r.id));
  const ref = input.analysisRef;
  if (ref && !seen.has(ref.id) && ref.clean) {
    out.unshift({
      id: ref.id,
      title: `Lap ${ref.lap_number}`,
      detail: "your reference, another session",
      ms: finite(ref.lap_time_ms) ? ref.lap_time_ms : null,
      status: "neutral",
      sectors: [ref.s1_ms, ref.s2_ms, ref.s3_ms].map((ms) => ({ ms: finite(ms) ? ms : null, status: "neutral" as TimingStatus })),
      words: "Clean",
      group: "reference",
      canBeRef: true,
    });
    seen.add(ref.id);
  }
  const s = input.session;
  if (input.candidates) {
    for (const o of candidateOptions(input.candidates, seen)) {
      out.push(o);
      if (o.id > 0) seen.add(o.id);
    }
  } else if (timingEligible(s) && s.track_id) {
    for (const d of input.drivers) {
      const best = d.stats.best_laps.find((b) => !b.synthetic && b.game === s.game && b.track_id === s.track_id);
      if (!best || seen.has(best.lap_id)) continue;
      const own = d.id === s.driver_id;
      out.push({
        id: best.lap_id,
        title: own ? "Your best here" : `${d.name}'s best`,
        detail: best.car_name ? `${own ? "another session" : "best here"} · ${best.car_name}` : own ? "another session" : "best here",
        ms: best.lap_time_ms,
        status: "neutral",
        sectors: NO_SECTORS,
        words: "Clean",
        group: "family",
        canBeRef: true,
      });
      seen.add(best.lap_id);
    }
  }
  const t = input.selectedTrace;
  if (t && !seen.has(t.lap_id)) {
    out.push({
      id: t.lap_id,
      title: `Lap ${t.lap_number}`,
      detail: "another session",
      ms: finite(t.lap_time_ms) ? t.lap_time_ms : null,
      status: "neutral",
      sectors: NO_SECTORS,
      words: "Clean",
      group: "reference",
      canBeRef: true,
    });
  }
  return out;
}

/** Text of an option for the closed picker and screen readers: "Lap 64 · 1:10.549 · Clean". */
export function optionText(o: LapOption): string {
  return [o.title, o.detail, lapTime(o.ms), o.words].filter(Boolean).join(" · ");
}

// ---- metres --------------------------------------------------------------------------------------------------------

/** Model metres -> game metres (scaled when the two lap lengths differ). */
export function modelToGameM(m: number | null | undefined, modelLengthM: number | null | undefined, gameLengthM: number | null | undefined): number | null {
  if (!finite(m)) return null;
  if (finite(modelLengthM) && finite(gameLengthM) && modelLengthM > 0 && gameLengthM > 0) return (m * gameLengthM) / modelLengthM;
  return m;
}

/** Game metres -> model metres. */
export function gameToModelM(m: number | null | undefined, modelLengthM: number | null | undefined, gameLengthM: number | null | undefined): number | null {
  if (!finite(m)) return null;
  if (finite(modelLengthM) && finite(gameLengthM) && modelLengthM > 0 && gameLengthM > 0) return (m * modelLengthM) / gameLengthM;
  return m;
}

/** A corner's apex in game metres (for `at=` links). */
export function apexGameM(model: ReviewTrackModel | null | undefined, corner: string, gameLengthM: number | null | undefined): number | null {
  const c = model?.corners.find((x) => x.name === corner);
  return c ? modelToGameM(c.apex_m, model?.length_m, gameLengthM) : null;
}

// ---- corners of a comparison ---------------------------------------------------------------------------------------

export interface CompareCorner extends CornerIdentity {
  /** Game metres. */
  apexGame: number | null;
  entryGame: number | null;
  exitGame: number | null;
  timeS: number | null;
  brakeM: number | null;
  minSpeedKph: number | null;
  exitSpeedKph: number | null;
  fullThrottleM: number | null;
  /** Neutral words for the differences above the coach's thresholds ("braked about 12 m earlier"). */
  words: string[];
}

/** The comparison's corners with their identity, in track order. */
export function compareCorners(
  corners: readonly ReviewCornerDelta[] | null | undefined,
  model: ReviewTrackModel | null | undefined,
  gameLengthM: number | null | undefined,
): CompareCorner[] {
  const L = model?.length_m;
  return (corners ?? [])
    .map((c) => {
      const id = cornerIdentity(model, c.corner);
      return {
        ...id,
        apexGame: modelToGameM(id.apexM, L, gameLengthM),
        entryGame: modelToGameM(id.entryM, L, gameLengthM),
        exitGame: modelToGameM(id.exitM, L, gameLengthM),
        timeS: finite(c.time_delta_s) ? c.time_delta_s : null,
        brakeM: finite(c.brake_point_delta_m) ? c.brake_point_delta_m : null,
        minSpeedKph: finite(c.min_speed_delta_kph) ? c.min_speed_delta_kph : null,
        exitSpeedKph: finite(c.exit_speed_delta_kph) ? c.exit_speed_delta_kph : null,
        fullThrottleM: finite(c.throttle_full_delta_m) ? c.throttle_full_delta_m : null,
        words: cornerWords({ brakeM: c.brake_point_delta_m, minSpeedKph: c.min_speed_delta_kph, exitSpeedKph: c.exit_speed_delta_kph }),
      };
    })
    .sort((a, b) => (a.apexGame ?? Infinity) - (b.apexGame ?? Infinity));
}

/** The corner at (or nearest to) a cursor in game metres: distance to its entry-exit stretch, apex as a fallback. */
export function cornerAt(corners: readonly CompareCorner[], m: number | null | undefined): CompareCorner | null {
  if (!finite(m) || !corners.length) return null;
  let best: CompareCorner | null = null;
  let bestD = Infinity;
  for (const c of corners) {
    const a = c.entryGame ?? c.apexGame;
    const b = c.exitGame ?? c.apexGame;
    if (a == null || b == null) continue;
    const d = m < a ? a - m : m > b ? m - b : 0;
    if (d < bestD || (d === bestD && best && Math.abs((c.apexGame ?? 0) - m) < Math.abs((best.apexGame ?? 0) - m))) {
      best = c;
      bestD = d;
    }
  }
  return best;
}

/** The corner where the lap lost the most time (the explainer's default before anyone moves the cursor). */
export function biggestLoss(corners: readonly CompareCorner[]): CompareCorner | null {
  let best: CompareCorner | null = null;
  for (const c of corners) if (c.timeS != null && (best == null || c.timeS > (best.timeS as number))) best = c;
  return best ?? corners[0] ?? null;
}

/** Corner -> time delta, for the map (green gained, red lost, neutral within +-0.01 s). */
export function segmentDeltas(corners: readonly CompareCorner[]): Record<string, number | null> {
  return Object.fromEntries(corners.map((c) => [c.key, c.timeS]));
}

// ---- words for the explainer and the table -------------------------------------------------------------------------

const LEVEL_S = 0.005;

/** "0.11 s lost" / "0.04 s gained" / "level" (words: beginners, explainers). */
export function timeWords(s: number | null | undefined): string {
  if (!finite(s)) return UNKNOWN;
  if (Math.abs(s) < LEVEL_S) return "level";
  return `${Math.abs(s).toFixed(2)} s ${s > 0 ? "lost" : "gained"}`;
}

/** "+0.11 s" / "−0.04 s" (tables and advanced density; U+2212 minus). */
export function timeSigned(s: number | null | undefined): string {
  if (!finite(s)) return UNKNOWN;
  if (Math.abs(s) < LEVEL_S) return "0.00 s";
  return `${s > 0 ? "+" : MINUS}${Math.abs(s).toFixed(2)} s`;
}

function amount(v: number | null | undefined, unit: string, less: string, more: string, minAbs = 1): string {
  if (!finite(v)) return UNKNOWN;
  const r = Math.round(Math.abs(v));
  if (r < minAbs) return "same";
  return `${r} ${unit} ${v < 0 ? less : more}`;
}

/** Braked: "12 m earlier" / "3 m later" / "same". */
export const brakedText = (m: number | null | undefined) => amount(m, "m", "earlier", "later");
/** Slowest speed: "4 km/h lower" / "higher". */
export const slowestText = (kph: number | null | undefined) => amount(kph, "km/h", "lower", "higher");
/** Exit speed: "5 km/h slower" / "faster". */
export const exitText = (kph: number | null | undefined) => amount(kph, "km/h", "slower", "faster");
/** Full throttle: "5 m earlier" / "later" (positive = later). */
export const throttleText = (m: number | null | undefined) => amount(m, "m", "earlier", "later");

/** A corner's differences as one sentence for the plain table ("Braked about 12 m earlier and 4 km/h slower at the
 * slowest point"), or "No big difference" when nothing passes the coach's thresholds. */
export function cornerSentence(c: Pick<CompareCorner, "words">): string {
  return c.words.length ? sentence(joinAnd(c.words)) : "No big difference";
}

/** The explainer's sentence (spec 6.5): "At Stowe you braked 12 m earlier, your slowest speed was 4 km/h lower and
 * the corner took 0.11 s longer (lap 66 against your reference, lap 64)." */
export function explainerText(
  c: CompareCorner,
  lapNumber?: number | null,
  refLapNumber?: number | null,
  /** coachref: another driver's lap ("Sam's best"): named instead of its lap number (it is their session's). */
  refLabel?: string | null,
): string {
  if (refLabel) {
    const base = explainerText(c);
    const lap = finite(lapNumber) ? `lap ${lapNumber}` : "your lap";
    return `${base.replace(/\.$/, "")} (${lap} against ${refLabel}).`;
  }
  return (
    whyText({
      where: c.spoken,
      evidence: {
        time_delta_s: c.timeS,
        brake_point_delta_m: c.brakeM,
        min_speed_delta_kph: c.minSpeedKph,
        exit_speed_delta_kph: c.exitSpeedKph,
        throttle_full_delta_m: c.fullThrottleM,
      },
      lapNumber,
      refLapNumber,
    }) ?? `At ${c.spoken} the two laps were the same within the measurement.`
  );
}

/** The coach's observations for a corner on the compared lap: technique first, incidents apart (never advice). */
export function cornerObservations(
  observations: readonly ReviewObservation[] | null | undefined,
  corner: string,
): { coaching: ReviewObservation[]; incidents: ReviewObservation[] } {
  const here = (observations ?? []).filter((o) => o.corner === corner);
  return {
    coaching: here.filter((o) => o.kind !== INCIDENT_KIND).sort((a, b) => b.priority - a.priority),
    incidents: here.filter((o) => o.kind === INCIDENT_KIND),
  };
}

// ---- the corner table by density -----------------------------------------------------------------------------------

export type CornerColumn = "time" | "sentence" | "braked" | "slowest" | "exit" | "throttle";

export const CORNER_COLUMN_LABEL: Readonly<Record<CornerColumn, string>> = {
  time: "Time lost here",
  sentence: "What was different",
  braked: "Braked",
  slowest: "Slowest speed",
  exit: "Exit speed",
  throttle: "Full throttle",
};

/** Columns of the corner table (6.10): beginners time + a plain sentence; intermediate + braked and slowest speed;
 * advanced every column. */
export function cornerColumns(table: Density["cornerTable"]): CornerColumn[] {
  if (table === "plain") return ["time", "sentence"];
  if (table === "some") return ["time", "braked", "slowest"];
  return ["time", "braked", "slowest", "exit", "throttle"];
}

// ---- titles, captions, compatibility -------------------------------------------------------------------------------

export type CompareChart = "delta" | "speed" | "pedals" | "steering";

export interface ChartWords {
  title: string;
  /** One fixed plain sentence (beginner and intermediate): explains the chart, never what to do. */
  caption: string | null;
}

/** Chart titles in words (never "B vs A") and their captions. `refWord` is "your target lap" for beginners. */
export function chartWords(chart: CompareChart, refWord: string): ChartWords {
  switch (chart) {
    case "delta":
      return {
        title: `Time gained or lost: your lap against ${refWord}`,
        caption: "The line goes up where your lap lost time and down where it gained time. Flat means the same as the reference.",
      };
    case "speed":
      return {
        title: "Speed",
        caption: "The blue line is the reference lap, the other line is your lap. Each dip is a corner: the lower line was slower there.",
      };
    case "pedals":
      return {
        title: "Throttle and brake",
        caption: "How far each pedal was pressed, from 0 to 100 %. Where the shapes start and end shows when each lap braked and accelerated.",
      };
    case "steering":
      return { title: "Steering", caption: null };
  }
}

/** coachref: the A picker's name and the sentences' word when A is another driver's lap (the descriptor of
 * /api/coachref/compare): "Sam's lap" for the picker (its option already says "Sam's best" / "Family record") and the
 * descriptor's sentence words ("Sam's best", "the family record") instead of "the reference"; else refWordFor. */
export function refWordsFor(
  level: Density["level"],
  ref: { own?: boolean | null; label?: string | null; label_to?: string | null; driver_name?: string | null } | null | undefined,
): { picker: string; sentence: string } {
  if (ref && ref.own === false && ref.label) {
    return { picker: ref.driver_name ? `${ref.driver_name}'s lap` : ref.label, sentence: ref.label_to || ref.label };
  }
  return refWordFor(level);
}

/** The A picker's name (9.6): "Your target lap" for beginners, "Reference" for everyone else. */
export function refWordFor(level: Density["level"]): { picker: string; sentence: string } {
  return level === "beginner"
    ? { picker: "Your target lap", sentence: "your target lap" }
    : { picker: "Reference", sentence: "the reference" };
}

/** Why the comparison cannot be drawn, in a sentence (the server's reasons, verbatim, joined). */
export function blockedText(blocking: readonly string[]): string {
  if (!blocking.length) return "These two laps cannot be compared.";
  return `These two laps cannot be compared: ${blocking.join("; ")}.`;
}

/** Evidence chips for a compared lap's session (A may come from a synthetic or replay session too). */
export function lapEvidence(s: EvidenceTier): { synthetic: boolean; replay: boolean } {
  return { synthetic: s.synthetic === true, replay: isReplaySource(s.source) };
}

/** "Time gained or lost" headline: "Your lap was 0.45 s slower than the reference" (words, never a bare sign). */
export function totalText(totalS: number | null | undefined, refWord: string): string | null {
  if (!finite(totalS)) return null;
  if (Math.abs(totalS) < LEVEL_S) return `Your lap matched ${refWord}`;
  return `Your lap was ${Math.abs(totalS).toFixed(2)} s ${totalS > 0 ? "slower" : "faster"} than ${refWord}`;
}

/** How many corners lost and gained time ("3 corners lost time, 4 gained"). */
export function lossGainText(corners: readonly CompareCorner[]): string | null {
  const lost = corners.filter((c) => c.timeS != null && c.timeS >= 0.01).length;
  const gained = corners.filter((c) => c.timeS != null && c.timeS <= -0.01).length;
  if (!lost && !gained) return null;
  return `${plural(lost, "corner")} lost time, ${gained} gained`;
}
