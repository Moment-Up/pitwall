// The delta reference control (coachref, spec 10.1, 10.2): what Drive's delta measures against, the moving lock,
// and the picker's rows. Pure; tested in plain node.
//
//   Delta to · Sam's best ▾   [Lap 3 · 1:36.953 · 3 Oct]      the delta panel's label row becomes the control
//   Using your best: Sam's laps here used a different braking assist      (coachref.reason, when set; 2 lines max)
//
// Words come from the server (labels, reasons) verbatim; this module only joins them. A server without coachref
// sends no `coachref` block: the control is then unavailable and the panel keeps today's plain label.
// Moving lock: while the car may be moving the picker does not open (the one trivial change allowed is "Back to your
// best"); unknown speed on track counts as moving (unknown is never assumed stopped).

import type { Driver } from "../drivers";
import type { Applies, ChoiceRequest, RefKind, RefOption, RefOptionsResponse } from "../endpoints/coachref";
import type { SnapshotNext } from "./types";
import { dayText, finite, lapTime } from "./text";

/** At or above this speed the car counts as moving (spec 3.4.8 MOVING_KPH). */
export const MOVING_KPH = 30;
/** model/telemetry.py FrameQuality. */
export const QUALITY_PAUSED = 1 << 2;
export const QUALITY_NOT_RACING = 1 << 6;

export const DEFAULT_LABEL = "Your best";
export const LOCKED_HINT = "Change the reference when stopped";
export const BACK_TO_BEST = "Back to your best";
export const FROM_NEXT_LAP = "From next lap";
export const HELD_FOR_DRILL = "Held for the drill";

export interface RefHolder {
  name: string;
  initials: string;
  colour: string | null;
}

export interface RefControlView {
  /** The server sends coachref: the label row is a control. False = today's plain label. */
  available: boolean;
  /** Button words: "Delta to · Sam's best"; beginners "vs Sam's best lap", own "vs your best lap". */
  text: string;
  /** The reference's own label ("Sam's best", "Your best"): the Ready card's control. */
  label: string;
  /** The reference is the driver's own lap (or there is none yet and the choice is their own best). */
  own: boolean;
  /** Whose lap it is, when it is not the driver's own (a 20 px initials avatar). */
  holder: RefHolder | null;
  /** "Using your best: Sam's laps here used a different braking assist", or null (the fallback first: a cut line
   * still says the delta is not against Sam). */
  reason: string | null;
  /** A change waits for the next lap or the end of the drill: "From next lap". */
  pending: boolean;
  /** The reference is held for a running drill. */
  frozen: boolean;
  /** "Braking calls use your own braking points where Sam brakes later" (another driver's lap). */
  brakeNote: string | null;
  /** No reference lap yet while another driver's lap is chosen: "Ben's best from the end of your first lap" (the
   * Ready card says this, and the delta panel "No reference yet: " + this); null otherwise. */
  waiting: string | null;
  /** The car may be moving: the picker stays shut. */
  locked: boolean;
  /** Locked and the choice is not "Your best": the one change allowed while moving. */
  backToBest: ChoiceRequest | null;
  /** The seated driver the choice belongs to. */
  driverId: number | null;
  /** "Only at Silverstone". */
  trackName: string | null;
  /** What screen readers hear after the visible words ("held for the drill, change the reference when stopped"). */
  ariaHint: string;
}

/**
 * The picker may not open (spec 10.1 moving lock): telemetry live, not in the pit lane or garage, not paused or out
 * of the race, and the speed unknown or at least 30 km/h.
 */
export function refPickerLocked(s: SnapshotNext | null | undefined): boolean {
  if (!s || s.connection.status !== "live") return false;
  const f = s.frame;
  const pit = f?.pit_status;
  if (pit === 1 || pit === 2) return false;
  const q = f?.quality;
  if (finite(q) && (q & (QUALITY_PAUSED | QUALITY_NOT_RACING)) !== 0) return false;
  const v = f?.speed_kph;
  return !finite(v) || v >= MOVING_KPH;
}

function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const letters = parts.length > 1 ? `${parts[0]![0]}${parts[parts.length - 1]![0]}` : (parts[0] ?? "?").slice(0, 2);
  return letters.toUpperCase();
}

/** A holder from the profiles (their initials and colour), else from the name the server sent. */
export function holderOf(id: number | null | undefined, name: string | null | undefined, drivers: readonly Driver[]): RefHolder | null {
  const d = id != null ? drivers.find((x) => x.id === id) : undefined;
  if (d) return { name: d.name, initials: d.preferences.initials || initialsOf(d.name), colour: d.preferences.colour || null };
  if (!name) return null;
  return { name, initials: initialsOf(name), colour: null };
}

/** Beginners' words (spec 10.1), one name for each reference as the radio says it (`label_to`): "vs your best lap"
 * for an own reference, "vs your pinned lap", else "vs Sam's best lap" / "vs the family record lap" / "vs Sam's lap". */
export function beginnerText(kind: RefKind | null | undefined, own: boolean, labelTo: string | null | undefined, label: string): string {
  const words = own ? labelTo || "your best" : labelTo || label;
  return kind === "lap" || /\blap$/.test(words) ? `vs ${words}` : `vs ${words} lap`;
}

/** One saved lap in words, for Review › Compare's "Drive against this lap": "Alex's lap 3 (1:36.953)" (it stays on
 * that lap; it does not follow Alex's best), else the reference's label. */
export function savedLapWords(
  holder: string | null | undefined,
  lapNumber: number | null | undefined,
  lapTimeMs: number | null | undefined,
  label: string,
): string {
  if (!holder || !finite(lapNumber)) return label;
  return `${holder}'s lap ${lapNumber}${finite(lapTimeMs) ? ` (${lapTime(lapTimeMs)})` : ""}`;
}

/** What the Ready card and the delta panel say while another driver's chosen lap is not the reference yet. */
export function waitingText(choice: { kind: RefKind; label: string } | null | undefined): string | null {
  return choice && choice.kind !== "own_best" ? `${choice.label} from the end of your first lap` : null;
}

export function refControlView(
  s: SnapshotNext | null | undefined,
  opts: { beginner: boolean; drivers?: readonly Driver[]; locked?: boolean },
): RefControlView {
  const cr = s?.coachref;
  const r = s?.reference ?? null;
  const choice = cr?.choice ?? null;
  const own = r ? r.own !== false : !choice || choice.kind === "own_best";
  const label = (r?.label || choice?.label || DEFAULT_LABEL).trim();
  const kind = r?.kind ?? choice?.kind ?? "own_best";
  const holder = !own && r ? holderOf(r.driver_id, r.driver_name ?? r.ref_name, opts.drivers ?? []) : null;
  const text = opts.beginner ? beginnerText(kind, own, r?.label_to, label) : `Delta to · ${label}`;
  const reason = cr?.reason ? `Using your best: ${cr.reason}` : null;
  const name = !own && r ? (r.ref_name ?? r.driver_name ?? null) : null;
  // Drive passes its motion rule (stationary with hysteresis, lib/drive/motion.ts); the speed rule is the fallback.
  const locked = opts.locked ?? refPickerLocked(s);
  const notOwnChoice = !!choice && choice.kind !== "own_best";
  const backToBest: ChoiceRequest | null =
    locked && notOwnChoice && choice
      ? {
          driver_id: choice.driver_id,
          kind: "own_best",
          scope: choice.scope,
          ...(choice.scope === "track" && choice.game && choice.track_id ? { game: choice.game, track_id: choice.track_id } : {}),
        }
      : null;
  const pending = cr?.pending === true;
  // Held only while the drill runs: the snapshot's descriptor keeps "frozen" until the next lap after it ends.
  const frozen = r?.frozen === true && cr?.drill?.status === "active";
  const extras = [reason, pending ? FROM_NEXT_LAP.toLowerCase() : null, frozen ? HELD_FOR_DRILL.toLowerCase() : null].filter(Boolean);
  return {
    available: cr != null,
    text,
    label,
    own,
    holder,
    reason,
    pending,
    frozen,
    brakeNote: name ? `Braking calls use your own braking points where ${name} brakes later` : null,
    waiting: r ? null : waitingText(choice),
    locked,
    backToBest,
    driverId: cr?.driver_id ?? choice?.driver_id ?? null,
    trackName: s?.session?.track_name ?? null,
    ariaHint: [...extras, locked ? LOCKED_HINT.toLowerCase() : "choose what the delta measures against"].join(", "),
  };
}

// ---------------------------------------------------------------------------------------------- picker rows

export interface PickerRow {
  /** "own_best", "household_best", "driver_best:2", "lap:812". */
  key: string;
  kind: RefKind;
  /** "Your best", "Family record", "Sam's best", "Lap 7 · Sam". */
  title: string;
  /** "1:30.986 · 3 Oct" / "1:30.412 · Jo"; null when it resolves to nothing yet. */
  detail: string | null;
  /** Why it cannot be chosen (spec 3.1.1), verbatim; null when it can. */
  reason: string | null;
  warnings: string[];
  disabled: boolean;
  selected: boolean;
  holder: RefHolder | null;
  /** What a PUT /choice sends for this row (the scope is added by choiceRequest). */
  request: Pick<ChoiceRequest, "kind" | "target_driver_id" | "lap_id">;
}

/** A compatibility warning as a sentence ("Track temperature differs by 18 °C"): the server's words, cased. */
export function warningText(w: string): string {
  const t = w.trim().replace(/(\d) C\b/g, "$1 °C");
  return t ? `${t.slice(0, 1).toUpperCase()}${t.slice(1)}` : t;
}

function rowKey(o: RefOption): string {
  if (o.kind === "driver_best") return `driver_best:${o.target_driver_id ?? "?"}`;
  if (o.kind === "lap") return `lap:${o.lap_id ?? "?"}`;
  return o.kind;
}

function rowOf(o: RefOption, nowS: number, drivers: readonly Driver[], driverId: number | null, hasContext: boolean): PickerRow {
  const lap = o.lap;
  const time = lap && finite(lap.lap_time_ms) ? lapTime(lap.lap_time_ms) : null;
  const date = lap ? dayText(lap.set_unix, nowS) : null;
  // The family record names its holder (unless it is you); the others carry the date.
  const holderName = lap && lap.driver_id !== driverId ? lap.driver_name : null;
  const tail = o.kind === "household_best" ? (holderName ?? date) : date;
  // Nothing to resolve to here yet (checked against the live context): say so rather than leave a blank.
  const detail = time ? [time, tail].filter(Boolean).join(" · ") : hasContext && o.available === true ? "none here yet" : null;
  const holder =
    lap && lap.driver_id !== driverId && (o.kind === "household_best" || o.kind === "lap")
      ? holderOf(lap.driver_id, lap.driver_name, drivers)
      : o.kind === "driver_best"
        ? holderOf(o.target_driver_id, lap?.driver_name ?? null, drivers)
        : null;
  const disabled = o.available === false;
  return {
    key: rowKey(o),
    kind: o.kind,
    title: o.label,
    detail,
    reason: disabled ? (o.reason ?? "Not available here") : null,
    warnings: (o.warnings ?? []).map(warningText),
    disabled,
    selected: o.selected,
    holder,
    request: {
      kind: o.kind,
      ...(o.kind === "driver_best" && o.target_driver_id != null ? { target_driver_id: o.target_driver_id } : {}),
      ...(o.kind === "lap" && o.lap_id != null ? { lap_id: o.lap_id } : {}),
    },
  };
}

/** The picker: your best, the family record and each other driver's best ("main"), then the saved laps ("A saved
 * lap…", nested). Unavailable rows stay listed, disabled, with the server's reason. */
export function pickerRows(r: RefOptionsResponse, nowS: number, drivers: readonly Driver[] = []): { main: PickerRow[]; laps: PickerRow[] } {
  const rows = r.options.map((o) => rowOf(o, nowS, drivers, r.driver_id, r.context != null));
  return { main: rows.filter((x) => x.kind !== "lap"), laps: rows.filter((x) => x.kind === "lap") };
}

/** The PUT /choice body for a row. "Only at {track}" stores it for this track; a saved lap is always per track. */
export function choiceRequest(row: Pick<PickerRow, "request">, onlyHere: boolean, r: Pick<RefOptionsResponse, "driver_id" | "context">): ChoiceRequest {
  const body: ChoiceRequest = { ...row.request };
  if (r.driver_id != null) body.driver_id = r.driver_id;
  if (row.request.kind === "lap") return body; // the server takes game and track from the lap
  body.scope = onlyHere ? "track" : "all_tracks";
  if (onlyHere && r.context) {
    body.game = r.context.game;
    body.track_id = r.context.track_id;
  }
  return body;
}

/** "Only at Silverstone" starts on when the effective choice is a per-track one. */
export function onlyHereDefault(r: Pick<RefOptionsResponse, "choice" | "has_track_override">): boolean {
  return r.choice.scope === "track" || r.has_track_override;
}

/** What the status slot says after a change (null = it applies now: the snapshot shows it). Short: it shares the
 * header with the session's name ("Sam's best from next lap"). */
export function appliesNotice(applies: Applies, kind: RefKind, label: string): string | null {
  // the family's best keeps the server's name: "Family record", or "Best in these conditions" (plan 5.2)
  const what = kind === "own_best" ? DEFAULT_LABEL : kind === "household_best" ? label.split(" · ")[0] || "Family record" : label;
  switch (applies) {
    case "next_lap":
      return `${what} from next lap`;
    case "after_drill":
      return `${what} after the drill`;
    case "next_session":
      return `${what} from next session`;
    default:
      return null;
  }
}
