// F1 spotter: pure view rules (design spec 9.1, 9.2), unit-tested in plain node (view.test.ts). No React here.
//
//   parseSpotterBlock   the live snapshot's `spotter` block -> SpotterBlock, or null (absent, malformed, unknown v)
//   barsView            what the Drive edge bars draw: per side hidden / amber "alongside" / red "close", and where
//                       the other car's block sits along the bar (ahead at the top)
//   reasonText, callText, sideOf   words for Settings and the radio log
//
// Drive rules kept here (spec 4.x principles): nothing animates (P2), colour is never the only signal (P4: "close" is
// a solid bar, "alongside" a faint bar with a solid car block, so red-green safe mode - where red becomes orange -
// still tells them apart), unknown stays unknown (P5: a block that is not fresh, a socket that is down, a stream that
// is not live all hide the bars; a car with no position is drawn without a block, never at a guessed place).

import type {
  SpotterBlock,
  SpotterCallKind,
  SpotterReason,
  SpotterSide,
  SpotterSideState,
} from "./types";
import { SPOTTER_CALL_KINDS, SPOTTER_REASONS } from "./types";

// ------------------------------------------------------------------------------------------------- constants

/** spotter/dims.py: the F1 car box (5.50 m; F2 5.30). Used for the bar scale when the block does not say. */
export const DEFAULT_CAR_LENGTH_M = 5.5;
/** Spec 3.4: a member stays alongside up to reach + 1.5 m; the bar spans the same distance either way. */
export const STAY_MARGIN_M = 1.5;
/** A snapshot arrives every 50 ms while the car moves (live_ws_hz 20). The server only sends a snapshot when
 * something changed, so a game that stops sending (pause, menus) leaves the LAST block on the client for up to 5 s:
 * the bars hide when no new block arrived for this long. Wi-Fi bunching is ~100 ms at p99 (spec 2.2). */
export const BARS_STALE_MS = 600;

// ------------------------------------------------------------------------------------------------- parsing

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const finite = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const SIDE_STATES: readonly SpotterSideState[] = ["clear", "alongside", "close"];

function side(v: unknown): SpotterSide {
  const o = isObj(v) ? v : {};
  // A state this dashboard does not know (a newer server) is not drawn: the radio is the primary channel.
  const state = SIDE_STATES.find((s) => s === o.state) ?? "clear";
  const cars = finite(o.cars);
  return {
    state,
    lon_m: state === "clear" ? null : finite(o.lon_m),
    gap_m: state === "clear" ? null : finite(o.gap_m),
    cars: state === "clear" ? 0 : cars !== null && cars >= 1 ? Math.floor(cars) : 1,
  };
}

/** The block's gate reason, or null; a reason a newer server adds stays visible as "inactive", never raw. */
export function parseReason(v: unknown): SpotterReason | null {
  return SPOTTER_REASONS.find((r) => r === v) ?? null;
}

/**
 * The snapshot's `spotter` block, or null: absent (older server, no F1 session), not an object, or a version this
 * dashboard does not know (it then shows nothing rather than misread a newer shape).
 */
export function parseSpotterBlock(raw: unknown): SpotterBlock | null {
  if (!isObj(raw) || raw.v !== 1) return null;
  const length = finite(raw.length_m);
  return {
    v: 1,
    enabled: raw.enabled === true,
    active: raw.active === true,
    reason: parseReason(raw.reason),
    left: side(raw.left),
    right: side(raw.right),
    three_wide: raw.three_wide === true,
    traffic: raw.traffic === true,
    rate_hz: finite(raw.rate_hz),
    seq: finite(raw.seq) ?? 0,
    length_m: length !== null && length >= 3 && length <= 7 ? length : null,
  };
}

// ------------------------------------------------------------------------------------------------- bars

export type BarTone = "alongside" | "close";

export interface SideBar {
  tone: BarTone;
  /** Top of the other car's block, % of the bar height (ahead = top); null = position unknown, no block drawn. */
  blockTopPct: number | null;
  /** Block height, % of the bar height (one car length on the bar's scale). */
  blockHeightPct: number;
  /** Cars on that side (an outside-of-three-wide pair counts 2). */
  cars: number;
  /** For screen-reader-free debugging and tests: "left alongside 1.8 m behind". */
  label: string;
}

export type BarsHidden = "no_block" | "offline" | "not_live" | "not_fresh" | "off" | "inactive";

export interface BarsView {
  /** Why nothing is drawn; null when the bars are live (each side may still be clear). */
  hidden: BarsHidden | null;
  left: SideBar | null;
  right: SideBar | null;
  three_wide: boolean;
}

export interface BarsContext {
  /** The /ws/live socket is open (lib/live.ts `connected`). */
  connected: boolean;
  /** The server's connection status for the game stream ("live" | "stale" | "idle"). */
  status: string | null | undefined;
  /** A new block arrived within BARS_STALE_MS. */
  fresh: boolean;
}

const round1 = (n: number): number => Math.round(n * 10) / 10;

/** The bar's half-span in metres: one car length plus the stay margin (spec 9.1: -(L+1.5) .. +(L+1.5)). */
export function barSpanM(lengthM: number | null | undefined): number {
  const l = lengthM != null && Number.isFinite(lengthM) && lengthM >= 3 && lengthM <= 7 ? lengthM : DEFAULT_CAR_LENGTH_M;
  return l + STAY_MARGIN_M;
}

/** Block geometry along the bar: ahead at the top, clamped so the block always stays fully on the bar. */
export function blockGeometry(lonM: number | null, lengthM: number | null | undefined): { topPct: number | null; heightPct: number } {
  const l = lengthM != null && Number.isFinite(lengthM) && lengthM >= 3 && lengthM <= 7 ? lengthM : DEFAULT_CAR_LENGTH_M;
  const span = barSpanM(l);
  const heightPct = round1((l / (2 * span)) * 100);
  if (lonM === null || !Number.isFinite(lonM)) return { topPct: null, heightPct };
  const lon = Math.max(-span, Math.min(span, lonM));
  const centre = ((span - lon) / (2 * span)) * 100;
  const top = Math.max(0, Math.min(100 - heightPct, centre - heightPct / 2));
  return { topPct: round1(top), heightPct };
}

function where(lon: number | null): string {
  if (lon === null) return "";
  if (Math.abs(lon) < 0.5) return " level";
  return lon > 0 ? ` ${round1(lon)} m ahead` : ` ${round1(-lon)} m behind`;
}

function sideBar(name: "left" | "right", s: SpotterSide, lengthM: number | null | undefined): SideBar | null {
  if (s.state === "clear") return null;
  const g = blockGeometry(s.lon_m, lengthM);
  return {
    tone: s.state,
    blockTopPct: g.topPct,
    blockHeightPct: g.heightPct,
    cars: Math.max(1, s.cars),
    label: `${name} ${s.state}${where(s.lon_m)}`,
  };
}

const HIDDEN: Omit<BarsView, "hidden"> = { left: null, right: null, three_wide: false };

/**
 * What the Drive edge bars show (spec 9.1): only while the spotter is enabled with bars on, active (every gate open),
 * the stream live, the dashboard's socket up and the block fresh. A muted spotter shows nothing (it never says
 * "clear" either).
 */
export function barsView(block: SpotterBlock | null | undefined, ctx: BarsContext): BarsView {
  if (!block) return { hidden: "no_block", ...HIDDEN };
  if (!ctx.connected) return { hidden: "offline", ...HIDDEN };
  if (ctx.status !== "live") return { hidden: "not_live", ...HIDDEN };
  if (!ctx.fresh) return { hidden: "not_fresh", ...HIDDEN };
  if (!block.enabled) return { hidden: "off", ...HIDDEN };
  if (!block.active) return { hidden: "inactive", ...HIDDEN };
  const left = sideBar("left", block.left, block.length_m);
  const right = sideBar("right", block.right, block.length_m);
  return { hidden: null, left, right, three_wide: block.three_wide && left !== null && right !== null };
}

// ------------------------------------------------------------------------------------------------- words

/** Why the spotter is silent, for Settings (spec 3.6). Unknown or null while inactive: "Inactive". */
export const REASON_TEXT: Readonly<Record<SpotterReason, string>> = {
  disabled: "Off",
  not_available: "Not available for this game",
  session_type: "Silent in this session type",
  red_flag: "Silent: red flag",
  safety_car: "Silent: safety car",
  start: "Waiting for the start",
  paused: "Silent: game paused",
  stale: "Waiting for motion data",
  flashback: "Silent after a flashback",
  pit: "Silent in the pits",
  finished: "Silent after the finish",
  slow: "Silent below 30 km/h",
};

export function reasonText(reason: SpotterReason | string | null | undefined): string {
  return reason && Object.prototype.hasOwnProperty.call(REASON_TEXT, reason)
    ? REASON_TEXT[reason as SpotterReason]
    : "Inactive";
}

/** A call id in words for logs and diagnostics: "car left", "still there (right)". Unknown ids: "call". */
export function callText(kind: string | null | undefined, side?: string | null): string {
  if (!kind || !(SPOTTER_CALL_KINDS as readonly string[]).includes(kind)) return "call";
  const k = kind as SpotterCallKind;
  const base = k.replace(/_/g, " ");
  const sided = k === "still_there" || k === "hold_your_line";
  return sided && (side === "left" || side === "right") ? `${base} (${side})` : base;
}
