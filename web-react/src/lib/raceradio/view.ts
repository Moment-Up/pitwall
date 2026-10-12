// Race radio (lane "radio"; race-radio spec 10): pure readers of the live snapshot's `race` block. No React, so every
// rule is tested in plain node (view.test.ts).
//
//   raceOf / snapRace   the block when it is one this dashboard understands (version 1, a known mode), sanitised: a
//                       non-finite number reads as null (unknown), lists are always lists. An older server (no block),
//                       a newer contract, a malformed payload or a block of another session all read as null, and
//                       Drive stays exactly as it was.
//   racePosition        "P5" from the block, for ANY game (the status line's position; GT7 and Forza have no session
//                       type, so the old "race session" rule never showed theirs).
//   positionNote        the backend's words on the position's evidence (GT7, Forza), shown as written.
//   ownFlag             the player's own car flag (F1 vehicleFIAFlags); null when the game or server does not say.
//   raceControlCall     the newest call race control would announce (flags, penalties, retirements), for the Car
//                       screen's race-control line: it carries the reason ("3 second penalty: corner cutting").
//
// Privacy: the block never carries a personal (online) name (raceradio/roster.py); nothing here adds one.

import type { SnapshotNext } from "../drive/types";
import type {
  DamageGrade,
  DamagePart,
  LabelKind,
  PositionTier,
  RaceCallView,
  RaceDamage,
  RaceFlags,
  RaceMode,
  RaceNeighbour,
  RacePenalties,
  RaceView,
  TrackFlag,
  Wheel,
  YellowAhead,
  YourFlag,
} from "./types";

const MODES: ReadonlySet<string> = new Set<RaceMode>(["race", "session", "off"]);
const TIERS: ReadonlySet<string> = new Set<PositionTier>([
  "spec_implemented",
  "recorded_validated",
  "community_documented",
  "live_validated",
]);
const TRACK: ReadonlySet<string> = new Set<TrackFlag>(["green", "sc", "vsc", "red", "formation"]);
const YOU: ReadonlySet<string> = new Set<YourFlag>(["none", "green", "blue", "yellow"]);
const GRADES: ReadonlySet<string> = new Set<DamageGrade>(["none", "minor", "major", "severe"]);
const WHEELS: ReadonlySet<string> = new Set<Wheel>(["FL", "FR", "RL", "RR"]);
const LABEL_KINDS: ReadonlySet<string> = new Set<LabelKind>(["driver", "team", "number", "car"]);

/** The call groups and calls race control would announce (the rest is the engineer: positions, gaps, the start). */
const RACE_CONTROL_GROUPS: ReadonlySet<string> = new Set(["flags", "penalties"]);
const RACE_CONTROL_CALLS: ReadonlySet<string> = new Set(["retirement"]);

type Obj = Record<string, unknown>;

const obj = (v: unknown): Obj | null => (v && typeof v === "object" && !Array.isArray(v) ? (v as Obj) : null);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() !== "" ? v : null);
const bool = (v: unknown): boolean | null => (typeof v === "boolean" ? v : null);
const pick = <T extends string>(v: unknown, allowed: ReadonlySet<string>): T | null =>
  typeof v === "string" && allowed.has(v) ? (v as T) : null;

function yellowAhead(raw: unknown): YellowAhead | null {
  const y = obj(raw);
  return y ? { zone: num(y.zone), ahead_m: num(y.ahead_m), corner: str(y.corner) } : null;
}

function flags(raw: unknown): RaceFlags | null {
  const f = obj(raw);
  if (!f) return null;
  return { track: pick(f.track, TRACK), you: pick(f.you, YOU), yellow_ahead: yellowAhead(f.yellow_ahead) };
}

function penalties(raw: unknown): RacePenalties | null {
  const p = obj(raw);
  if (!p) return null;
  return {
    time_s: num(p.time_s),
    warnings: num(p.warnings),
    track_limits: num(p.track_limits),
    drive_throughs: num(p.drive_throughs),
    stop_gos: num(p.stop_gos),
    serve_at_stop: bool(p.serve_at_stop),
  };
}

function damage(raw: unknown): RaceDamage | null {
  const d = obj(raw);
  if (!d) return null;
  const parts: DamagePart[] = [];
  for (const x of Array.isArray(d.parts) ? d.parts : []) {
    const p = obj(x);
    const part = str(p?.part);
    const grade = pick<DamageGrade>(p?.grade, GRADES);
    if (p && part && grade) parts.push({ part, pct: num(p.pct), grade });
  }
  const puncture = (Array.isArray(d.puncture) ? d.puncture : []).filter((w): w is Wheel => WHEELS.has(w as string));
  return { grade: pick(d.grade, GRADES), parts, puncture };
}

function neighbour(raw: unknown): RaceNeighbour | null {
  const n = obj(raw);
  if (!n) return null;
  return {
    label: str(n.label),
    label_kind: pick(n.label_kind, LABEL_KINDS),
    position: num(n.position),
    gap_s: num(n.gap_s),
    settled: bool(n.settled),
  };
}

function calls(raw: unknown): RaceCallView[] {
  const out: RaceCallView[] = [];
  for (const x of Array.isArray(raw) ? raw : []) {
    const c = obj(x);
    const text = str(c?.text);
    const t = num(c?.t_unix);
    if (!c || !text || t == null) continue;
    out.push({ t_unix: t, group: str(c.group) ?? "", call: str(c.call) ?? "", text });
  }
  return out;
}

/**
 * The race block when it is one this dashboard understands (version 1, a known mode), sanitised; else null: an older
 * server (no block), a newer contract or a malformed payload all leave Drive exactly as it was.
 */
export function raceOf(raw: unknown): RaceView | null {
  const v = obj(raw);
  if (!v || v.version !== 1 || typeof v.mode !== "string" || !MODES.has(v.mode)) return null;
  return {
    version: 1,
    session_id: str(v.session_id),
    game: str(v.game),
    mode: v.mode as RaceMode,
    reason: str(v.reason),
    synthetic: v.synthetic === true,
    position: num(v.position),
    cars: num(v.cars),
    grid_position: num(v.grid_position),
    position_tier: pick(v.position_tier, TIERS),
    position_note: str(v.position_note)?.trim() ?? null,
    lap: num(v.lap),
    total_laps: num(v.total_laps),
    laps_left: num(v.laps_left),
    final_lap: bool(v.final_lap),
    time_left_s: num(v.time_left_s),
    flags: flags(v.flags),
    penalties: penalties(v.penalties),
    damage: damage(v.damage),
    ahead: neighbour(v.ahead),
    behind: neighbour(v.behind),
    calls: calls(v.calls),
  };
}

/** The race block of a live snapshot (see raceOf). A block that names another session than the snapshot's is not
 * this session's (unknown stays unknown). */
export function snapRace(s: Pick<SnapshotNext, "race" | "session_id"> | null | undefined): RaceView | null {
  const v = raceOf(s?.race);
  if (!v) return null;
  if (v.session_id && s?.session_id && v.session_id !== s.session_id) return null;
  return v;
}

/** "P5" when the block knows the position (a whole number from 1), else null. Any game: the server decides when a
 * position is a race position (raceradio/engine.py mode). */
export function racePosition(v: RaceView | null | undefined): string | null {
  const p = v?.position;
  return p != null && Number.isInteger(p) && p >= 1 ? `P${p}` : null;
}

/** The backend's note on the position's evidence ("From GT7's race position; not yet checked against the game's
 * screen."), only while a position is shown. */
export function positionNote(v: RaceView | null | undefined): string | null {
  return racePosition(v) ? (v?.position_note ?? null) : null;
}

/** The player's own car flag, or null when the game or the server does not say (GT7, Forza, an older server). */
export function ownFlag(v: RaceView | null | undefined): YourFlag | null {
  return v?.flags?.you ?? null;
}

/** The newest call (by its time, whatever order the list is in), optionally only those `keep` accepts. */
export function newestCall(
  v: RaceView | null | undefined,
  keep: (c: RaceCallView) => boolean = () => true,
): RaceCallView | null {
  let best: RaceCallView | null = null;
  for (const c of v?.calls ?? []) if (keep(c) && (best === null || c.t_unix > best.t_unix)) best = c;
  return best;
}

/** A call race control would announce: flags, penalties and warnings, retirements. */
export function isRaceControl(c: Pick<RaceCallView, "group" | "call">): boolean {
  return RACE_CONTROL_GROUPS.has(c.group) || RACE_CONTROL_CALLS.has(c.call);
}

/** The newest race-control call (see isRaceControl), or null. */
export function raceControlCall(v: RaceView | null | undefined): RaceCallView | null {
  return newestCall(v, isRaceControl);
}

/** A call's words for a line that adds its own separators: the backend's text without its closing full stop. */
export function callLineText(text: string): string {
  return text.trim().replace(/\.+$/, "");
}
