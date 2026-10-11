// Drive states and overlays (design spec 4.7) and the status slot (4.8). Pure: the same function drives iPad,
// phone and Mac.
//
// Session phase: D4 (snapshot.session_state + session_state_info) when the server sends it. Before D4 it is
// derived from events[], which keeps only the last 10 events of every car, so a small memo carries the newest
// session-phase event across snapshots: without it, the overtakes and penalties that follow a chequered flag push
// it out of the window within seconds. Pass the returned memo back on the next call (useDriveModel does); omit it
// and every snapshot is judged on its own.
//
// Interpretations of the spec, from real captures (src/test/fixtures/recorded-*):
//  * "newest event" means the newest SESSION-PHASE event (session_started, lights_out, chequered_flag,
//    session_ended, red_flag): AI overtakes ("other") arrive after the flag in every race capture.
//  * F1 sends the chequered flag when the LEADER takes it (D4 reports it as session_state_info.chequered_flag and
//    never ends the session on it). Drive shows a CHEQUERED FLAG band over the normal screen while the driver's
//    own last lap runs, and the Session complete card (slot "CHEQUERED FLAG") once that lap is done: the line
//    crossed since the flag, the session's lap count completed, or the car off track. session_ended (or D4
//    "ended") shows SESSION COMPLETE at once.
//  * D4 "ended" is a fact the server keeps, not a live value: F1 stops sending at session_ended, so the connection
//    turns stale about 2 s later while session_state stays "ended" until the next session starts. It therefore
//    wins over stale (the stale age stays on the connection pill); "no flag while the data is in doubt" holds for
//    flags. Before D4 the phase is inferred from a 10-event window, so stale still wins there.
//  * Blue flags come from marshal zones, which show blue whenever ANY car is being lapped there. When the car's
//    position and the zones are known, the band shows only while the car is inside a blue zone.
//  * Incident chips need the event to concern the player (LiveEvent.player === true), because F1 reports every
//    car's penalties, collisions and fastest laps. Flashback (player only by nature) shows unless player === false.

import type { MotivationNote } from "../endpoints/motivation";
import { badgeFor } from "../live";
import { forward, gameLength, onLap } from "./geometry";
import type { LiveEvent, SnapshotNext } from "./types";
import { ageText, finite } from "./text";

export type DriveState = "offline" | "no_data" | "stale" | "ended" | "red_flag" | "pit_lane" | "garage" | "on_track";
export type SafetyCar = "full" | "virtual" | "formation_lap";
export type IncidentKind = "penalty" | "collision" | "flashback" | "fastest_lap" | "pit_entry" | "pit_exit";
/** The status slot's 6 s chip: an incident, or (lane motivation) a goal reached on the lap just completed. */
export type ChipKind = IncidentKind | "goal";

export interface YellowFlag {
  /** The zone's game number (the numbering race control uses). */
  zone: number;
  /** 1-based sector the zone starts in, when the skeleton is known. */
  sector: number | null;
  /** Metres from the car to the zone start when it starts within 1000 m ahead, else null. */
  aheadM: number | null;
  /** The car is inside the zone. */
  inZone: boolean;
  /** Yellow zones in total (the band names the nearest). */
  count: number;
}

export interface DriveOverlays {
  safetyCar: SafetyCar | null;
  yellow: YellowFlag | null;
  blue: boolean;
  invalid: boolean;
  /** Chequered flag shown. With state on_track: the driver's last lap still runs. With state ended: the session
   * ended by the flag (the slot says CHEQUERED FLAG instead of SESSION COMPLETE). */
  chequered: boolean;
  chip: { kind: ChipKind; ageS: number } | null;
}

export const NO_OVERLAYS: DriveOverlays = Object.freeze({
  safetyCar: null,
  yellow: null,
  blue: false,
  invalid: false,
  chequered: false,
  chip: null,
}) as DriveOverlays;

type PhaseKind = "running" | "chequered" | "ended" | "red_flag";

/** What Drive remembers across snapshots of one session (see the header). */
export interface DriveMemo {
  sessionId: string | null;
  /** Newest session-phase event seen in events[] (before D4). */
  phase: { kind: PhaseKind; t: number } | null;
  /** The chequered flag is shown, with the driver's lap when Drive first saw it. */
  chequered: { lap: number | null } | null;
  /** Learned name of the last corner shown (offline keeps it on screen, dimmed). */
  lastCorner: string | null;
}

export const EMPTY_MEMO: DriveMemo = Object.freeze({
  sessionId: null,
  phase: null,
  chequered: null,
  lastCorner: null,
}) as DriveMemo;

export const RED_FLAG_MAX_AGE_S = 120;
export const CHIP_SHOW_S = 6;
export const YELLOW_AHEAD_MAX_M = 1000;

const PHASE_OF: ReadonlyMap<string, PhaseKind> = new Map([
  ["session_started", "running"],
  ["lights_out", "running"],
  ["chequered_flag", "chequered"],
  ["session_ended", "ended"],
  ["red_flag", "red_flag"],
]);

const INCIDENTS: ReadonlySet<string> = new Set<IncidentKind>([
  "penalty",
  "collision",
  "flashback",
  "fastest_lap",
  "pit_entry",
  "pit_exit",
]);
/** Events a game reports for every car: shown only when the server says they concern the player. */
const EVERY_CAR: ReadonlySet<string> = new Set(["penalty", "collision", "fastest_lap"]);

/** An incident event the chip may show: the player's own (see the header). */
function playerIncident(e: LiveEvent): boolean {
  if (!INCIDENTS.has(e.kind)) return false;
  return EVERY_CAR.has(e.kind) ? e.player === true : e.player !== false;
}

function newest(events: readonly LiveEvent[], pick: (e: LiveEvent) => boolean): LiveEvent | null {
  let best: LiveEvent | null = null;
  for (const e of events) if (pick(e) && finite(e.t) && (best === null || e.t > best.t)) best = e;
  return best;
}

function hasD4(s: SnapshotNext | null): boolean {
  const v = s?.session_state;
  return v === "running" || v === "ended" || v === "red_flag";
}

/** Fold this snapshot into the memo: the newest session-phase event, and when the chequered flag was first seen. */
export function nextMemo(s: SnapshotNext | null, memo: DriveMemo | null | undefined): DriveMemo {
  const sid = s?.session_id ?? null;
  let m: DriveMemo =
    memo && memo.sessionId === sid ? memo : { sessionId: sid, phase: null, chequered: null, lastCorner: null };
  const e = newest(s?.events ?? [], (x) => PHASE_OF.has(x.kind));
  const kind = e ? PHASE_OF.get(e.kind) : undefined;
  if (e && kind && (!m.phase || e.t > m.phase.t)) m = { ...m, phase: { kind, t: e.t } };
  const flag = hasD4(s) ? s?.session_state_info?.chequered_flag === true : m.phase?.kind === "chequered";
  if (flag && !m.chequered) m = { ...m, chequered: { lap: s?.frame?.lap_number ?? null } };
  else if (!flag && m.chequered) m = { ...m, chequered: null };
  return m;
}

type Phase = { kind: "running" | "red_flag" | "chequered" | "ended"; by?: "session_ended" | "chequered" };

function phaseOf(s: SnapshotNext, memo: DriveMemo, nowS: number): Phase {
  let chequered = false;
  if (hasD4(s)) {
    // D4: the server's own session state wins whenever it is known.
    if (s.session_state === "ended") return { kind: "ended", by: "session_ended" };
    if (s.session_state === "red_flag") return { kind: "red_flag" };
    chequered = s.session_state_info?.chequered_flag === true;
  } else {
    const p = memo.phase;
    if (p?.kind === "ended") return { kind: "ended", by: "session_ended" };
    if (p?.kind === "red_flag" && nowS - p.t < RED_FLAG_MAX_AGE_S) return { kind: "red_flag" };
    chequered = p?.kind === "chequered";
  }
  if (!chequered) return { kind: "running" };
  const f = s.frame;
  const lap = f?.lap_number;
  const total = s.session?.total_laps;
  const lastDone = finite(total) && total > 0 && (s.laps[0]?.lap_number ?? 0) >= total;
  const at = memo.chequered?.lap;
  const crossed = finite(lap) && at != null && lap > at;
  const offTrack = !f || (f.pit_status ?? 0) !== 0;
  return lastDone || crossed || offTrack ? { kind: "ended", by: "chequered" } : { kind: "chequered" };
}

/** Not driving yet: no car frame, in the garage, or the session is known and no lap has started. */
function inGarage(s: SnapshotNext): boolean {
  const f = s.frame;
  if (!f) return true;
  if (f.pit_status === 2 || f.driver_status === "in_garage") return true;
  const clock = f.current_lap_time_ms;
  return s.laps.length === 0 && (clock == null || clock === 0) && (f.lap_number == null || f.lap_number <= 1);
}

function safetyCar(s: SnapshotNext): SafetyCar | null {
  const v = s.session?.safety_car_status;
  return v === "full" || v === "virtual" || v === "formation_lap" ? v : null;
}

interface ZoneHit {
  zone: number;
  sector: number | null;
  ahead: number | null;
  inZone: boolean;
}

function zoneHits(s: SnapshotNext, flag: string): ZoneHit[] | null {
  const numbers = (s.marshal_flags ?? []).filter((m) => m.flag === flag).map((m) => m.game_number);
  if (numbers.length === 0) return null;
  const L = gameLength(s);
  const d = onLap(s.frame?.lap_distance_m, L);
  const zones = s.skeleton?.marshal_zones ?? [];
  const sectors = s.skeleton?.sectors ?? [];
  return numbers.map((n) => {
    const z = zones.find((x) => x.game_number === n);
    if (!z) return { zone: n, sector: null, ahead: null, inZone: false };
    const sec = sectors.find((x) => z.start_m >= x.start_m && z.start_m < x.end_m);
    const pieces = z.segments_m?.length ? z.segments_m : [[z.start_m, z.end_m] as [number, number]];
    const inZone = d != null && pieces.some(([a, b]) => d >= a && d < b);
    const ahead = d != null && L != null ? forward(d, z.start_m, L) : null;
    return { zone: n, sector: sec ? sec.index + 1 : null, ahead, inZone };
  });
}

function yellowOf(s: SnapshotNext): YellowFlag | null {
  const hits = zoneHits(s, "yellow");
  if (!hits || hits.length === 0) return null;
  const sorted = [...hits].sort((a, b) => {
    if (a.inZone !== b.inZone) return a.inZone ? -1 : 1;
    return (a.ahead ?? Infinity) - (b.ahead ?? Infinity);
  });
  const h = sorted[0]!;
  const aheadM = !h.inZone && h.ahead != null && h.ahead <= YELLOW_AHEAD_MAX_M ? h.ahead : null;
  return { zone: h.zone, sector: h.sector, aheadM, inZone: h.inZone, count: hits.length };
}

function blueOf(s: SnapshotNext): boolean {
  const hits = zoneHits(s, "blue");
  if (!hits) return false;
  const knowable = hits.every((h) => h.ahead != null);
  return knowable ? hits.some((h) => h.inZone) : true;
}

function chipOf(s: SnapshotNext, nowS: number, note?: MotivationNote | null): DriveOverlays["chip"] {
  const e = newest(s.events, playerIncident);
  if (e) {
    const ageS = nowS - e.t;
    // small negative ages: clock skew between server and device
    if (ageS >= -2 && ageS <= CHIP_SHOW_S) return { kind: e.kind as IncidentKind, ageS: Math.max(0, ageS) };
  }
  // lane motivation: GOAL REACHED for 6 s after the /ws/live note of THIS session; an incident within 6 s wins.
  if (note && note.session_id === s.session_id && finite(note.t)) {
    const ageS = nowS - note.t;
    if (ageS >= -2 && ageS <= CHIP_SHOW_S) return { kind: "goal", ageS: Math.max(0, ageS) };
  }
  return null;
}

export interface DriveStateResult {
  state: DriveState;
  overlays: DriveOverlays;
  memo: DriveMemo;
}

/** One state plus overlays; the first matching state wins (4.7). Overlays combine with red flag, pit lane, garage
 * and on track only. D4 "ended" is a server-kept fact and wins over stale (see the header). `goalNote`: the newest
 * /ws/live "motivation" note (lane motivation), for the GOAL REACHED chip. */
export function driveState(
  s: SnapshotNext | null,
  wsConnected: boolean,
  nowS: number,
  memo?: DriveMemo | null,
  goalNote?: MotivationNote | null,
): DriveStateResult {
  const m = nextMemo(s, memo);
  if (!wsConnected) return { state: "offline", overlays: NO_OVERLAYS, memo: m };
  if (!s || s.connection.status === "no_data") return { state: "no_data", overlays: NO_OVERLAYS, memo: m };
  if (s.session_state === "ended") return { state: "ended", overlays: NO_OVERLAYS, memo: m };
  if (s.connection.status === "stale") return { state: "stale", overlays: NO_OVERLAYS, memo: m };
  const phase = phaseOf(s, m, nowS);
  if (phase.kind === "ended") {
    return { state: "ended", overlays: phase.by === "chequered" ? { ...NO_OVERLAYS, chequered: true } : NO_OVERLAYS, memo: m };
  }
  const overlays: DriveOverlays = {
    safetyCar: safetyCar(s),
    yellow: yellowOf(s),
    blue: blueOf(s),
    invalid: s.frame?.lap_invalid === true,
    chequered: phase.kind === "chequered",
    chip: chipOf(s, nowS, goalNote),
  };
  let state: DriveState = "on_track";
  if (phase.kind === "red_flag") state = "red_flag";
  else if (s.frame?.pit_status === 1) state = "pit_lane";
  else if (inGarage(s)) state = "garage";
  return { state, overlays, memo: m };
}

// ------------------------------------------------------------------ status slot (4.8)

export type SlotTone = "bad" | "warn" | "red" | "sc" | "yellow" | "blue" | "pit" | "neutral";
export type SlotBand =
  | "offline"
  | "no_data"
  | "stale"
  | "red"
  | "sc"
  | "yellow"
  | "blue"
  | "pit"
  | "chequered"
  | "complete"
  | "ready"
  | "normal";

export interface StatusSlot {
  /** normal = the status line; outline = the data is in doubt; fill = the track says. */
  kind: "normal" | "outline" | "fill";
  tone: SlotTone | null;
  band: SlotBand;
  /** Main words (caps for flag bands) - also the accessible text. */
  text: string;
  /** Smaller detail after the main words ("380 m ahead"), or null. */
  sub: string | null;
  role: "status" | "alert";
}

const SC_TEXT: Record<SafetyCar, string> = {
  full: "SAFETY CAR",
  virtual: "VIRTUAL SAFETY CAR",
  formation_lap: "FORMATION LAP",
};

/** Session type in words: "Race", "Practice", "Time trial"; null when unknown. */
export function sessionTypeText(raw: string | null | undefined): string | null {
  if (!raw || raw.toLowerCase() === "unknown") return null;
  const t = raw.replace(/_/g, " ").trim();
  return t ? t[0]!.toUpperCase() + t.slice(1).toLowerCase() : null;
}

function completeSub(s: SnapshotNext | null): string | null {
  if (!s) return null;
  const parts = [s.session?.track_name, sessionTypeText(s.session?.session_type)].filter(
    (p): p is string => typeof p === "string" && p.length > 0,
  );
  const n = s.laps.length;
  if (n > 0) parts.push(n >= 20 ? "20+ laps" : `${n} ${n === 1 ? "lap" : "laps"}`);
  return parts.length ? parts.join(" · ") : null;
}

/** The status slot's band for a state and its overlays. Priority (4.8): offline > stale > red > safety car >
 * yellow > blue > pit > session complete > ready > normal. When the data is in doubt no flag is shown; D4's
 * session complete is a kept fact, not a flag, so it shows while stale (driveState). */
export function statusSlot(state: DriveState, o: DriveOverlays, s: SnapshotNext | null): StatusSlot {
  const status = (band: SlotBand, text: string, tone: SlotTone | null = null): StatusSlot => ({
    kind: "normal",
    tone,
    band,
    text,
    sub: null,
    role: "status",
  });
  const fill = (band: SlotBand, tone: SlotTone, text: string, sub: string | null = null): StatusSlot => ({
    kind: "fill",
    tone,
    band,
    text,
    sub,
    role: band === "red" ? "alert" : "status",
  });
  if (state === "offline") {
    return { kind: "outline", tone: "bad", band: "offline", text: "Offline", sub: "reconnecting…", role: "status" };
  }
  if (state === "no_data") return status("no_data", "Waiting for telemetry", "neutral");
  if (state === "stale") {
    const age = s?.connection.last_packet_age_s;
    const text = finite(age) && age >= 1 ? `No signal · ${ageText(age)}` : "No signal";
    return { kind: "outline", tone: "warn", band: "stale", text, sub: "game paused or in a menu?", role: "status" };
  }
  if (state === "red_flag") return fill("red", "red", "RED FLAG");
  if (state !== "ended") {
    if (o.safetyCar) return fill("sc", "sc", SC_TEXT[o.safetyCar], s?.cues?.muted ? "calls paused" : null);
    if (o.yellow) {
      const y = o.yellow;
      const text = ["YELLOW FLAG", y.sector != null ? `SECTOR ${y.sector}` : null, `ZONE ${y.zone}`]
        .filter(Boolean)
        .join(" · ");
      const where = y.inZone ? "in this zone" : y.aheadM != null ? `${Math.round(y.aheadM / 10) * 10} m ahead` : null;
      const more = y.count > 1 ? `${y.count} zones` : null;
      const sub = [where, more].filter(Boolean).join(" · ") || null;
      return fill("yellow", "yellow", text, sub);
    }
    if (o.blue) return fill("blue", "blue", "BLUE FLAG", "let the car behind through");
    if (state === "pit_lane") {
      const limit = s?.skeleton?.pit_speed_limit_kph;
      return fill("pit", "pit", "PIT LANE", finite(limit) ? `limit ${Math.round(limit)} km/h` : null);
    }
    if (o.chequered) return fill("chequered", "neutral", "CHEQUERED FLAG", "last lap");
  }
  if (state === "ended") {
    return fill("complete", "neutral", o.chequered ? "CHEQUERED FLAG" : "SESSION COMPLETE", completeSub(s));
  }
  if (state === "garage") {
    const t = sessionTypeText(s?.session?.session_type);
    return status("ready", t ? `Ready · ${t}` : "Ready", "neutral");
  }
  return status("normal", statusLineText(s));
}

function statusLineText(s: SnapshotNext | null): string {
  const l = statusLine(s);
  return [l.track, l.session, l.lap + (l.lapTotal ? ` / ${l.lapTotal}` : ""), l.position]
    .filter((x): x is string => !!x && x !== "-")
    .join(" · ");
}

// ------------------------------------------------------------------ status line and connection pill

export interface StatusLine {
  track: string;
  /** Session type in words, "-" when unknown. */
  session: string;
  /** "Lap 7" or "Lap -". */
  lap: string;
  /** Total laps when known (the slot shows "/ 25"), else null. */
  lapTotal: string | null;
  /** "P4" in races when known, else null. */
  position: string | null;
}

export function statusLine(s: SnapshotNext | null): StatusLine {
  const se = s?.session ?? null;
  const f = s?.frame ?? null;
  const type = sessionTypeText(se?.session_type);
  const total = se?.total_laps;
  const race = !!type && type.toLowerCase().includes("race");
  const pos = f?.race_position;
  return {
    track: se?.track_name || "-",
    session: type ?? "-",
    lap: `Lap ${finite(f?.lap_number) ? f.lap_number : "-"}`,
    lapTotal: finite(total) && total > 0 ? String(total) : null,
    position: race && finite(pos) && pos > 0 ? `P${pos}` : null,
  };
}

export interface ConnectionPill {
  tone: "live" | "stale" | "idle" | "offline";
  text: string;
}

/** Connection pill: Live / Stale 6 s / No data / Offline (the dashboard's own socket is down). */
export function connectionPill(s: SnapshotNext | null, wsConnected: boolean): ConnectionPill {
  const b = badgeFor(s?.connection.status, wsConnected);
  if (b === "OFFLINE") return { tone: "offline", text: "Offline" };
  if (b === "LIVE") return { tone: "live", text: "Live" };
  if (b === "STALE") {
    const age = s?.connection.last_packet_age_s;
    return { tone: "stale", text: finite(age) && age >= 1 ? `Stale ${ageText(age)}` : "Stale" };
  }
  return { tone: "idle", text: "No data" };
}

/** Evidence chips: SYNTHETIC (hatched) and REPLAY. */
export function evidence(s: SnapshotNext | null): { synthetic: boolean; replay: boolean } {
  const c = s?.connection;
  return {
    synthetic: !!c?.synthetic || !!s?.skeleton?.synthetic,
    replay: typeof c?.source === "string" && c.source.startsWith("replay:"),
  };
}

const CHIP_TEXT: Record<ChipKind, string> = {
  penalty: "PENALTY",
  collision: "CONTACT",
  flashback: "FLASHBACK · lap won't count",
  fastest_lap: "FASTEST LAP",
  pit_entry: "PIT ENTRY",
  pit_exit: "PIT EXIT",
  goal: "GOAL REACHED",
};

/** The 6 s chip's words. */
export function chipText(kind: ChipKind): string {
  return CHIP_TEXT[kind];
}
