// Everything Drive > Coach renders, computed once per snapshot (design spec 4.10, 4.11). Pure: panels receive
// plain view models and re-render only when their own strings change. No LLM, no network: works fully with the
// LLM down (P10).
//
// useDriveModel (lane DV) calls driveModel() per snapshot with a 1 Hz nowS tick and feeds the returned `memo` into
// the next call (session phase and the last shown corner survive snapshots that no longer carry them).

import { changeWords, gapWords, type ChangeText } from "../bests";
import type { Driver } from "../drivers";
import { endedMotivation, readyGoal, type DriveMotivation, type ReadyGoalView } from "../motivation/drive";
import type { ThingsView } from "../motivation/recap";
import { INTENSITIES, SKILL_LEVELS } from "../drivers";
import { coachPoint, simpleWording, topPoint, workOnWentWell, type CoachPoint } from "./coach";
import { cornerAhead, cornerLabelOf, cornerLayout, focusReasonOf, isFocus, officialNameOf, type CornerView } from "./corner";
import { callsModeText, cueView, lastCueOutcome, type CueBandView, type CuePause, type LastCueOutcome } from "./cues";
import { deltaView, referenceLabel, type DeltaView } from "./delta";
import { gameLength } from "./geometry";
import { driverFocus } from "./plan";
import { ribbon, type RibbonView } from "./ribbon";
import {
  EMPTY_MEMO,
  chipText,
  connectionPill,
  driveState,
  evidence,
  statusLine,
  statusSlot,
  type ConnectionPill,
  type DriveMemo,
  type DriveOverlays,
  type ChipKind,
  type DriveState,
  type StatusLine,
  type StatusSlot,
} from "./state";
import { UNKNOWN, dayText, finite, lapTime, metres, round10, thousands } from "./text";
import {
  bestsOf,
  lapStatus,
  lapTimesView,
  legendOf,
  notCleanList,
  sessionBest,
  sectorCells,
  tagOf,
  type LapTimesView,
  type SectorCellsView,
  type Tier,
  type TimingStatus,
  type TimingTag,
} from "./timing";
import type { DrivePrefs, SnapshotNext } from "./types";

export interface DriveModelInput {
  snap: SnapshotNext | null;
  /** The dashboard's own WebSocket is open (live.connected). */
  connected: boolean;
  /** Device clock, unix seconds (a 1 Hz tick is enough). */
  nowS: number;
  /** The driver in the seat. */
  driver: Driver | null;
  /** Every profile (names the household record holder). */
  drivers?: readonly Driver[];
  prefs?: DrivePrefs;
  /** The previous call's `memo`. */
  memo?: DriveMemo | null;
  /** Lane motivation: the newest /ws/live goal note (the 6 s GOAL REACHED chip) and, while the car is stopped, the
   * session's recap (the Ready card's goal row, the Session complete card's three things). Absent = neither. */
  motivation?: DriveMotivation | null;
}

export type HeroView =
  | {
      kind: "corner";
      head: "Next corner" | "In corner";
      label: string;
      name: string | null;
      /** Long corner rule (4.5): "two" = label 88 px with the distance, then the name at 32 px on its own line. */
      layout: "one" | "two";
      /** No arrow and no word when the direction is unknown (complexes). */
      direction: "left" | "right" | null;
      /** "320 m" (rounded to 10 m) before the entry; "-" when the position is not current (stale, offline); null
       * in the corner (no distance shown). */
      distanceText: string | null;
      approach: number | null;
      focus: boolean;
      focusReason: string | null;
      /** The live position is not current (stale, offline): last content, dimmed. */
      frozen: boolean;
      corner: CornerView;
      aria: string;
    }
  | { kind: "pit"; label: "PIT"; speedText: string; limitText: string; over: boolean; aria: string }
  | { kind: "empty"; text: string; aria: string }
  | { kind: "card" };

export interface StatusView extends StatusSlot {
  pill: ConnectionPill;
  line: StatusLine;
  evidence: { synthetic: boolean; replay: boolean };
  chip: { kind: ChipKind; text: string } | null;
}

export interface CoachView extends CoachPoint {
  /** Overrides tagText in the pit lane ("Next run · from L6"). */
  heading: string | null;
  /** The full text is shown (stationary): no glance texts. */
  full: boolean;
}

export interface TimingText {
  text: string;
  status: TimingStatus;
  tag: TimingTag | null;
}

export interface ReadyCard {
  seat: {
    name: string | null;
    initials: string | null;
    colour: string | null;
    /** "James is in the seat". */
    line: string;
    skillText: string | null;
    coachingText: string | null;
  };
  phase: "before_first_lap" | "between_runs";
  target: {
    /** The driver's best here. D2 (`bests.driver`: this game + track + car): green PB with its tag. Otherwise
     * `stats.best_laps` (this game + track, ANY car): neutral, never green (4.6: not the timing scope), and `date`
     * ends in "any car" unless the lap was set in this session's car ("3 Oct · any car"). */
    yourBest: (TimingText & { date: string | null; anyCar: boolean }) | null;
    /** D2 only: the household record and who holds it. */
    record: (TimingText & { holder: string | null; holderColour: string | null; holderInitials: string | null }) | null;
    /** "Lap 4 · 1:30.986 · today" or "none yet: your first clean lap becomes the reference". */
    reference: string;
  };
  lastRun: {
    best: (TimingText & { lapNumber: number | null }) | null;
    clean: number;
    total: number;
    cleanText: string;
    /** First clean lap -> best clean lap in words ("1.2 s faster", lib/bests.ts changeWords), or null with fewer
     * than two clean laps. */
    gainedText: string | null;
    /** The same as amount + word, for drawing the number large. */
    gained: ChangeText | null;
  } | null;
  today: {
    /** The driver's own focus corners; empty while the calls are the AI field's heads-ups (plan.ts). */
    focus: { name: string; label: string; officialName: string | null; reason: string | null }[];
    /** "Braking calls: Focus corners", or "Braking calls: AI reference (heavy braking ahead)". */
    callsMode: string | null;
  };
  /** Between runs: "One thing for the next run" (D6 pick or top observation, full text). */
  nextRun: CoachPoint | null;
  footer: string | null;
  /** Lane motivation: one goal (reached this session, else in this scope), or null. */
  goal: ReadyGoalView | null;
}

/** A Session complete tile value: `text` in full ("4.8 s faster", "PB", "-"); `amount` + `word` to draw the number
 * large and the word small (null for "PB", "REC", "level" and unknown). */
export interface EndedChange {
  text: string;
  amount: string | null;
  word: ChangeText["word"] | null;
  sub: string | null;
}

export interface EndedCard {
  sessionId: string | null;
  reviewHref: string | null;
  best: (TimingText & { lapNumber: number | null; sub: string | null }) | null;
  clean: { clean: number; total: number; text: string; sub: string | null };
  /** First clean lap -> best, in words ("4.8 s faster"; "-" with fewer than two clean laps). */
  gained: EndedChange;
  /** The gap from the session best to your best ever ("0.540 s slower", "level": bests.ts gapWords), or "PB" when
   * this session set it (only hides the "than your best" line; the badge is `best.tag`). */
  toYourBest: EndedChange | null;
  /** The gap to the family record, or "REC" when this session set it. */
  toRecord: EndedChange | null;
  workOn: CoachPoint | null;
  wentWell: CoachPoint | null;
  /** Lane motivation: the session's three things (null: show workOn / wentWell), while they load, and the badges it
   * earned. */
  things: ThingsView | null;
  thingsLoading: boolean;
  badges: string[];
}

export interface DriveModel {
  state: DriveState;
  overlays: DriveOverlays;
  memo: DriveMemo;
  status: StatusView;
  /** Which full-width card replaces the hero, coach and delta, if any. */
  card: "ready" | "ended" | "no_data" | null;
  hero: HeroView;
  cue: CueBandView;
  coach: CoachView;
  delta: DeltaView;
  sectors: SectorCellsView;
  laps: LapTimesView;
  ribbon: RibbonView;
  lastCue: LastCueOutcome | null;
  ready: ReadyCard | null;
  ended: EndedCard | null;
  /** 2 when REC / PB can appear (a D2 driver or household best is present), else 1. */
  tier: Tier;
  /** Timing colours apply: false in synthetic and replay sessions (4.6), where only INV is shown. */
  coloured: boolean;
  /** The legend's words: the tags that can appear, or why there are none ("A replay: times are not coloured"). */
  legend: string;
  /** Telemetry live on the open socket (wake lock, phone tab live dot). */
  telemetryLive: boolean;
  /** state on_track: dim the rail, suppress toasts. */
  onTrack: boolean;
  /** Leaving Drive > Coach needs a 0.5 s hold: on track, and the lock setting covers this driver (lib/prefs.ts
   * driveLockApplies: nobody in the seat counts as a beginner). */
  lockApplies: boolean;
  /** Content is last-known and dimmed (stale, offline). */
  dim: boolean;
  beginner: boolean;
  simpleWording: boolean;
}

const NO_MODEL = "Corners appear after your first clean lap";

function heroOf(
  s: SnapshotNext | null,
  state: DriveState,
  corner: CornerView | null,
  frozen: boolean,
): HeroView {
  if (state === "garage" || state === "ended" || state === "no_data") return { kind: "card" };
  if (state === "pit_lane") {
    const v = s?.frame?.speed_kph;
    const limit = s?.skeleton?.pit_speed_limit_kph;
    const speed = finite(v) ? Math.round(v) : null;
    const lim = finite(limit) ? Math.round(limit) : null;
    const over = speed != null && lim != null && speed > lim;
    return {
      kind: "pit",
      label: "PIT",
      speedText: speed != null ? String(speed) : UNKNOWN,
      limitText: lim != null ? String(lim) : UNKNOWN,
      over,
      aria: `Pit lane: ${speed ?? "unknown"} of ${lim ?? "unknown"} km/h${over ? ", over the limit" : ""}`,
    };
  }
  if (!s?.track_model || !s.track_model.corners.length) return { kind: "empty", text: NO_MODEL, aria: NO_MODEL };
  if (!corner) {
    const t = "Position on the lap unknown";
    return { kind: "empty", text: t, aria: t };
  }
  const distanceText =
    corner.phase === "in" ? null : frozen || corner.toEntryM == null ? UNKNOWN : metres(round10(corner.toEntryM));
  const name = corner.officialName;
  const head = corner.phase === "in" ? "In corner" : "Next corner";
  return {
    kind: "corner",
    head,
    label: corner.label,
    name,
    layout: corner.layout,
    direction: corner.direction,
    distanceText,
    approach: frozen ? null : corner.approach,
    focus: corner.focus,
    focusReason: corner.focusReason,
    frozen,
    corner,
    aria: [head, corner.label, name, distanceText !== UNKNOWN ? distanceText : null].filter(Boolean).join(", "),
  };
}

/** The last shown corner as a view without a live position (offline: the frame is gone). */
function frozenCorner(s: SnapshotNext | null, name: string | null): CornerView | null {
  if (!s?.track_model || !name) return null;
  const c = s.track_model.corners.find((x) => x.name === name);
  if (!c) return null;
  const focus = isFocus(s.cues, name);
  const label = cornerLabelOf(s.track_model, name);
  const officialName = officialNameOf(s.track_model, name);
  return {
    name,
    label,
    officialName,
    layout: cornerLayout(label, officialName),
    direction: c.direction === "left" || c.direction === "right" ? c.direction : null,
    phase: "next",
    toEntryM: null,
    toApexM: null,
    approach: null,
    focus,
    focusReason: focus ? focusReasonOf(s.cues, name) : null,
  };
}

/**
 * "Your best here". With D2 the driver's best for this game + track + car is a PB (green, tagged). Without it (no
 * D2, or D2 has no best for this car) the profile's `stats.best_laps` entry for this game + track stands in: it may
 * come from any car, so it is not the timing scope (4.6) and is never green; it says "any car" unless it was set in
 * this session's car.
 */
function bestHere(s: SnapshotNext, driver: Driver | null, nowS: number): ReadyCard["target"]["yourBest"] {
  const bv = bestsOf(s);
  if (bv.driver && finite(bv.driver.lap_ms) && bv.driver.lap_ms > 0) {
    const set = s.bests?.driver?.set_unix ?? null;
    return { text: lapTime(bv.driver.lap_ms), status: "pb", tag: "PB", date: dayText(set, nowS), anyCar: false };
  }
  const game = s.session?.game;
  const track = s.session?.track_id;
  if (!driver || !game || !track) return null;
  const mine = driver.stats.best_laps.filter((b) => b.game === game && b.track_id === track && !b.synthetic);
  const best = mine.reduce<(typeof mine)[number] | null>((a, b) => (a === null || b.lap_time_ms < a.lap_time_ms ? b : a), null);
  if (!best) return null;
  const car = s.session?.car_name;
  const anyCar = !(car && best.car_name && best.car_name === car);
  const date = [dayText(best.set_unix, nowS), anyCar ? "any car" : null].filter(Boolean).join(" · ") || null;
  return { text: lapTime(best.lap_time_ms), status: "neutral", tag: null, date, anyCar };
}

function footerOf(s: SnapshotNext): string | null {
  const parts: string[] = [];
  const L = gameLength(s);
  if (L != null) parts.push(metres(L));
  const sk = s.skeleton;
  if (sk && finite(sk.sector2_start_m)) parts.push(`S2 ${metres(sk.sector2_start_m)}`);
  if (sk && finite(sk.sector3_start_m)) parts.push(`S3 ${metres(sk.sector3_start_m)}`);
  const corners = s.track_model?.corners ?? [];
  if (corners.length) {
    parts.push(`${thousands(corners.length)} corners learned`);
    const tiers = new Set(corners.map((c) => c.identity_tier).filter(Boolean));
    parts.push(
      `names: ${tiers.has("sheet_verified") ? "verified track sheet" : tiers.has("sheet_seeded") ? "seeded track sheet" : "learned from laps"}`,
    );
  }
  return parts.length ? parts.join(" · ") : null;
}

function cleanCounts(s: SnapshotNext): { clean: number; total: number; firstClean: number | null; bestClean: number | null } {
  const clean = s.laps.filter((l) => l.clean && finite(l.lap_time_ms) && l.lap_time_ms > 0);
  const times = clean.map((l) => l.lap_time_ms as number);
  return {
    clean: clean.length,
    total: s.laps.length,
    firstClean: clean.length ? (clean[clean.length - 1]!.lap_time_ms as number) : null, // laps[] is newest first
    bestClean: times.length ? Math.min(...times) : null,
  };
}

/** First clean lap -> best clean lap in words ("4.8 s faster", "level"); null with too few clean laps. */
function gainedChange(first: number | null, best: number | null, minLaps: number, clean: number): ChangeText | null {
  if (first == null || best == null || clean < minLaps) return null;
  return changeWords(best - first);
}

function gainedText(first: number | null, best: number | null, minLaps: number, clean: number): string | null {
  return gainedChange(first, best, minLaps, clean)?.text ?? null;
}

/** A Session complete tile value from a change (or the set-it word: "PB", "REC"). */
function endedChange(c: ChangeText | null, sub: string | null): EndedChange {
  if (!c) return { text: UNKNOWN, amount: null, word: null, sub };
  return { text: c.text, amount: c.amount, word: c.word === "level" ? null : c.word, sub };
}

function readyCard(
  s: SnapshotNext,
  driver: Driver | null,
  nowS: number,
  drivers: readonly Driver[],
  simple: boolean,
  motivation: DriveMotivation | null | undefined,
): ReadyCard {
  const skill = driver ? SKILL_LEVELS.find((x) => x.value === driver.preferences.skill_level) : undefined;
  const intensity = driver ? INTENSITIES.find((x) => x.value === driver.preferences.coaching_intensity) : undefined;
  const bv = bestsOf(s);
  const hh = bv.household ? s.bests?.household : null;
  const holder = hh?.driver_id != null ? (drivers.find((d) => d.id === hh.driver_id) ?? null) : null;
  const counts = cleanCounts(s);
  const between = s.laps.length > 0;
  const lastBest = (() => {
    const sb = sessionBest(s, bv);
    if (!sb) return null;
    const st = sb.index >= 0 ? lapStatus(s, sb.index, bv) : sb.status; // coloured as set
    return { text: lapTime(sb.ms), status: st, tag: tagOf(st), lapNumber: sb.lapNumber };
  })();
  const focus = driverFocus(s.cues).map((name) => ({
    name,
    label: cornerLabelOf(s.track_model, name),
    officialName: officialNameOf(s.track_model, name),
    reason: focusReasonOf(s.cues, name),
  }));
  return {
    seat: {
      name: driver?.name ?? null,
      initials: driver?.preferences.initials ?? null,
      colour: driver?.preferences.colour ?? null,
      line: driver ? `${driver.name} is in the seat` : "Nobody is in the seat",
      skillText: skill?.label ?? null,
      coachingText: intensity ? `Coaching: ${intensity.label.toLowerCase()}` : null,
    },
    phase: between ? "between_runs" : "before_first_lap",
    target: {
      yourBest: bestHere(s, driver, nowS),
      record:
        hh && finite(hh.lap_ms)
          ? {
              text: lapTime(hh.lap_ms),
              status: "rec",
              tag: "REC",
              holder: holder?.name ?? null,
              holderColour: holder?.preferences.colour ?? null,
              holderInitials: holder?.preferences.initials ?? null,
            }
          : null,
      reference: referenceLabel(s, nowS, refDates(driver)) ?? "none yet: your first clean lap becomes the reference",
    },
    lastRun: between
      ? {
          best: lastBest,
          clean: counts.clean,
          total: counts.total,
          cleanText: `${counts.clean} of ${counts.total} clean`,
          gainedText: gainedText(counts.firstClean, counts.bestClean, 2, counts.clean),
          gained: gainedChange(counts.firstClean, counts.bestClean, 2, counts.clean),
        }
      : null,
    today: { focus, callsMode: callsModeText(s.cues) },
    nextRun: between ? topPoint(s, simple) : null,
    footer: footerOf(s),
    goal: readyGoal(motivation, s.session_id),
  };
}

function endedCard(
  s: SnapshotNext,
  drivers: readonly Driver[],
  simple: boolean,
  motivation: DriveMotivation | null | undefined,
): EndedCard {
  const bv = bestsOf(s);
  const counts = cleanCounts(s);
  const sb = sessionBest(s, bv);
  const st: TimingStatus = sb?.status ?? "neutral";
  const notClean = s.laps.filter((l) => !l.clean);
  const reasons = [...new Set(notClean.flatMap((l) => notCleanList(l)))];
  const hh = bv.household;
  const holder = hh && s.bests?.household?.driver_id != null ? drivers.find((d) => d.id === s.bests?.household?.driver_id) : null;
  const gap = (ref: number | null | undefined, sub: string | null): EndedChange =>
    endedChange(sb != null && finite(ref) ? gapWords(sb.ms - ref) : null, sub);
  const set = (word: "PB" | "REC"): EndedChange => ({ text: word, amount: null, word: null, sub: "this session set it" });
  const { workOn, wentWell } = workOnWentWell(s, simple);
  const id = s.session_id ?? null;
  return {
    sessionId: id,
    reviewHref: id ? `#/review/sessions/${id}` : null,
    best: sb
      ? {
          text: lapTime(sb.ms),
          status: st,
          tag: tagOf(st),
          lapNumber: sb.lapNumber,
          sub:
            sb.lapNumber != null
              ? `lap ${sb.lapNumber}${st === "pb" ? " · new personal best" : st === "rec" ? " · new family record" : ""}`
              : null,
        }
      : null,
    clean: {
      clean: counts.clean,
      total: counts.total,
      text: `${counts.clean} of ${counts.total}`,
      sub: notClean.length ? `${notClean.length} not used: ${reasons.join(", ")}` : null,
    },
    gained: endedChange(gainedChange(counts.firstClean, counts.bestClean, 2, counts.clean), "first clean lap → best"),
    toYourBest: !bv.driver
      ? null
      : st === "pb" || st === "rec"
        ? set("PB")
        : gap(bv.driver.lap_ms, finite(bv.driver.lap_ms) ? lapTime(bv.driver.lap_ms) : null),
    toRecord: !hh
      ? null
      : st === "rec"
        ? set("REC")
        : gap(hh.lap_ms, [holder?.name, finite(hh.lap_ms) ? lapTime(hh.lap_ms) : null].filter(Boolean).join(" · ") || null),
    workOn,
    wentWell,
    ...endedMotivation(motivation, id),
  };
}

/** lap id -> unix time of the seated driver's best laps (dates the reference chip when it is one of them). */
function refDates(driver: Driver | null): Map<number, number> {
  return new Map((driver?.stats.best_laps ?? []).map((b) => [b.lap_id, b.set_unix]));
}

const EMPTY_COACH: CoachView = {
  tag: null,
  lap: null,
  tagText: null,
  text: null,
  size: 26,
  clamp: false,
  empty: null,
  evidence: null,
  source: null,
  corner: null,
  heading: null,
  full: false,
};

export function driveModel(input: DriveModelInput): DriveModel {
  const { snap: s, connected, nowS, driver } = input;
  const drivers = input.drivers ?? (driver ? [driver] : []);
  const { state, overlays, memo: m0 } = driveState(s, connected, nowS, input.memo ?? EMPTY_MEMO, input.motivation?.note);
  const beginner = driver?.preferences.skill_level === "beginner";
  const simple = !!driver?.coaching?.simple_wording;
  const lock = input.prefs?.driveLock ?? "beginners";
  const onTrack = state === "on_track";
  const dim = state === "stale" || state === "offline";

  // Corner ahead (live), else the last one shown (offline keeps the last content, dimmed).
  const live = cornerAhead(s?.track_model, s?.frame?.lap_distance_m, gameLength(s), s?.cues);
  const corner = live ?? (dim ? frozenCorner(s, m0.lastCorner) : null);
  const memo: DriveMemo = live && live.name !== m0.lastCorner ? { ...m0, lastCorner: live.name } : m0;

  const slot = statusSlot(state, overlays, s);
  const status: StatusView = {
    ...slot,
    pill: connectionPill(s, connected),
    line: statusLine(s),
    evidence: evidence(s),
    chip: overlays.chip ? { kind: overlays.chip.kind, text: chipText(overlays.chip.kind) } : null,
  };
  const card = state === "garage" ? "ready" : state === "ended" ? "ended" : state === "no_data" ? "no_data" : null;
  const hero = heroOf(s, state, corner, dim);

  const pause: CuePause =
    state === "red_flag" ? "red_flag" : state === "pit_lane" ? "pit_lane" : overlays.safetyCar ? "safety_car" : null;
  const cue: CueBandView = card
    ? { next: null, note: null, muted: true, radioOff: false, ai: false }
    : cueView(s?.cues, corner?.name ?? null, s?.track_model, pause, dim, {
        toApexM: live?.toApexM ?? null,
        lapLengthM: gameLength(s),
      });

  let coach: CoachView = EMPTY_COACH;
  if (s && !card) {
    if (state === "pit_lane") {
      const top = topPoint(s, simple);
      coach = top
        ? { ...top, heading: `Next run${top.lap != null ? ` · from L${top.lap}` : ""}`, full: true }
        : { ...coachPoint(s, null, simple, false), heading: null, full: true };
    } else {
      coach = { ...coachPoint(s, corner?.name ?? null, simple, true), heading: null, full: false };
    }
  }

  const bv = s ? bestsOf(s) : null;
  return {
    state,
    overlays,
    memo,
    status,
    card,
    hero,
    cue,
    coach,
    delta: deltaView(s, state, overlays, beginner, { nowS, refDates: refDates(driver) }),
    sectors: sectorCells(s, state, bv ?? undefined),
    laps: lapTimesView(s, state, bv ?? undefined),
    ribbon: ribbon(s, state, live?.name ?? null),
    lastCue: lastCueOutcome(s?.cues, s?.track_model),
    ready: s && state === "garage" ? readyCard(s, driver, nowS, drivers, simple, input.motivation) : null,
    ended: s && state === "ended" ? endedCard(s, drivers, simple, input.motivation) : null,
    tier: bv?.tier ?? 1,
    coloured: bv?.coloured ?? true,
    legend: legendOf(s, bv),
    telemetryLive: connected && s?.connection.status === "live",
    onTrack,
    // Same rule as prefs.driveLockApplies: an unknown skill counts as a beginner (the safe side).
    lockApplies: onTrack && (lock === "everyone" || (lock === "beginners" && (!driver || beginner))),
    dim,
    beginner,
    simpleWording: s ? simpleWording(s, simple) : simple,
  };
}
