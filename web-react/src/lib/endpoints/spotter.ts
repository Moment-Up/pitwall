// F1 spotter endpoints (lane "F1 spotter", design spec 8.1-8.2): typed client for /api/spotter
// (src/pitwall/api/routes_spotter.py; same auth as the rig routes). Settings › Radio & voice › Spotter reads and
// changes it (pages/settings/radio/SpotterCard.tsx); Drive never calls it (the bars read the /ws/live block).
//
//   GET  /api/spotter            settings, availability, status, latency, counters, the last 20 calls
//   PUT  /api/spotter/settings   a partial body; validated and saved; answers the GET payload (422 on a bad value)
//   POST /api/spotter/test       says "Car left", then "Clear left" 1.2 s later, through the real spotter path
//                                (meta.test = true); 409 while no radio is connected
//
// Every POST/PUT sends Content-Type: application/json (the server refuses JSON-less POSTs: cross-site protection).
// Parsing is tolerant of a newer or older server: a missing number stays null, an unknown word falls back to the
// safe value (the master switch to OFF), and nothing is ever guessed. An older server has no /api/spotter (404).

import { authFetch } from "../auth";
import type {
  LatencyStat,
  SpotterAudio,
  SpotterAvailability,
  SpotterAvailabilityReason,
  SpotterCounters,
  SpotterDims,
  SpotterInfo,
  SpotterLatency,
  SpotterRecentCall,
  SpotterSettings,
  SpotterStatus,
  SpotterWording,
} from "../spotter/types";
import { SPOTTER_DEFAULTS, START_DELAY_MAX_S, START_DELAY_MIN_S } from "../spotter/types";
import { parseReason } from "../spotter/view";
import { EndpointError, errorText } from "./settings";

/** Request-cache key (src/lib/cache.ts). */
export const SPOTTER_KEY = "spotter";

async function call(path: string, init?: RequestInit): Promise<unknown> {
  const r = await authFetch(path, init);
  if (!r.ok) {
    let detail = r.statusText;
    try {
      detail = errorText(((await r.json()) as { detail?: unknown }).detail, detail);
    } catch {
      /* not json */
    }
    throw new EndpointError(r.status, detail || `HTTP ${r.status}`);
  }
  return r.json() as Promise<unknown>;
}

// ---------------------------------------------------------------------------------------------- parsing

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v : null);
const count = (v: unknown): number => {
  const n = num(v);
  return n !== null && n >= 0 ? Math.floor(n) : 0;
};
const bool = (v: unknown, fallback: boolean): boolean => (typeof v === "boolean" ? v : fallback);
const WORDINGS: readonly SpotterWording[] = ["auto", "standard", "simple"];
const AVAILABILITY_REASONS: readonly SpotterAvailabilityReason[] = ["game_not_supported", "no_motion"];

function inRange(v: unknown, min: number, max: number): number | null {
  const n = num(v);
  return n !== null && n >= min && n <= max ? n : null;
}

/** The settings section. A missing or malformed master switch reads OFF (the safe default), never on. */
export function parseSpotterSettings(raw: unknown): SpotterSettings {
  const o = isObj(raw) ? raw : {};
  const d = SPOTTER_DEFAULTS;
  return {
    enabled: o.enabled === true,
    audio: bool(o.audio, d.audio),
    visual: bool(o.visual, d.visual),
    qualifying: o.qualifying === true,
    practice: o.practice === true,
    start_delay_s: inRange(o.start_delay_s, START_DELAY_MIN_S, START_DELAY_MAX_S) ?? d.start_delay_s,
    wording: WORDINGS.find((w) => w === o.wording) ?? d.wording,
    voice: str(o.voice),
    still_there: bool(o.still_there, d.still_there),
    hold_your_line: bool(o.hold_your_line, d.hold_your_line),
    car_length_m: inRange(o.car_length_m, 3, 7),
    car_width_m: inRange(o.car_width_m, 1.5, 2.5),
  };
}

function availability(v: unknown): SpotterAvailability {
  const o = isObj(v) ? v : {};
  return {
    available: o.available === true,
    game: str(o.game),
    reason: AVAILABILITY_REASONS.find((r) => r === o.reason) ?? null,
  };
}

function dims(v: unknown): SpotterDims | null {
  if (!isObj(v)) return null;
  return {
    length_m: inRange(v.length_m, 3, 7),
    width_m: inRange(v.width_m, 1.5, 2.5),
    formula: str(v.formula),
    source: str(v.source),
  };
}

function audio(v: unknown): SpotterAudio | null {
  if (!isObj(v)) return null;
  const clips: Record<string, number> = {};
  if (isObj(v.clip_s)) {
    for (const [k, s] of Object.entries(v.clip_s)) {
      const n = num(s);
      if (n !== null && n >= 0) clips[k] = n;
    }
  }
  const phrases = num(v.phrases);
  return {
    ready: v.ready === true,
    engine: str(v.engine),
    voice: str(v.voice),
    phrases: phrases !== null && phrases >= 0 ? Math.floor(phrases) : null,
    unverified: count(v.unverified),
    fallback: count(v.fallback),
    clip_s: clips,
  };
}

function status(v: unknown): SpotterStatus {
  const o = isObj(v) ? v : {};
  const hz = num(o.motion_hz);
  return {
    active: o.active === true,
    reason: parseReason(o.reason),
    motion_hz: hz !== null && hz >= 0 ? hz : null,
    send_rate_low: o.send_rate_low === true,
    dims: dims(o.dims),
    audio: audio(o.audio),
  };
}

function stat(v: unknown): LatencyStat | null {
  if (!isObj(v)) return null;
  const s = { p50: num(v.p50), p95: num(v.p95), max: num(v.max) };
  return s.p50 === null && s.p95 === null && s.max === null ? null : s;
}

function latency(v: unknown): SpotterLatency {
  const o = isObj(v) ? v : {};
  return {
    n: count(o.n),
    decide_ms: stat(o.decide_ms),
    queued_ms: stat(o.queued_ms),
    started_ms: stat(o.started_ms),
    onset_game_ms: stat(o.onset_game_ms),
    data_age_ms: stat(o.data_age_ms),
  };
}

function counts(v: unknown): Record<string, number> {
  const out: Record<string, number> = {};
  if (!isObj(v)) return out;
  for (const [k, n] of Object.entries(v)) {
    const c = num(n);
    if (c !== null && c >= 0) out[k] = Math.floor(c);
  }
  return out;
}

function counters(v: unknown): SpotterCounters {
  const o = isObj(v) ? v : {};
  return {
    calls: counts(o.calls),
    suppressed_short: count(o.suppressed_short),
    dropped: counts(o.dropped),
    items: count(o.items),
    skipped: count(o.skipped),
    invalid: count(o.invalid),
    errors: count(o.errors),
  };
}

/** The newest 20 calls, newest first (by time; calls without a time after those with one, in wire order). */
function recent(v: unknown): SpotterRecentCall[] {
  if (!Array.isArray(v)) return [];
  const out: { r: SpotterRecentCall; i: number }[] = [];
  for (const r of v) {
    if (!isObj(r) || !str(r.kind)) continue;
    out.push({
      i: out.length,
      r: {
        t_unix: num(r.t_unix),
        kind: String(r.kind),
        side: r.side === "left" || r.side === "right" ? r.side : null,
        spoken: r.spoken === true,
        queued_ms: num(r.queued_ms),
        started_ms: num(r.started_ms),
      },
    });
  }
  out.sort((a, b) => (b.r.t_unix ?? -Infinity) - (a.r.t_unix ?? -Infinity) || a.i - b.i);
  return out.slice(0, 20).map((x) => x.r);
}

/**
 * GET /api/spotter as a SpotterInfo, or null when the answer is not a version-1 payload (a newer server's shape is
 * not misread: the card then says the spotter's status is unknown).
 */
export function parseSpotterInfo(raw: unknown): SpotterInfo | null {
  if (!isObj(raw) || raw.v !== 1) return null;
  return {
    v: 1,
    settings: parseSpotterSettings(raw.settings),
    availability: availability(raw.availability),
    status: status(raw.status),
    latency: latency(raw.latency),
    counters: counters(raw.counters),
    recent: recent(raw.recent),
  };
}

/** A version-1 payload or an error the card can show (never a half-parsed object). */
function info(raw: unknown): SpotterInfo {
  const p = parseSpotterInfo(raw);
  if (!p) throw new EndpointError(502, "The Mac answered with a spotter status this dashboard does not understand.");
  return p;
}

// ---------------------------------------------------------------------------------------------- calls

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

/** The settings keys PUT accepts (spec 8.1); anything else is dropped client-side (the server rejects unknown keys). */
const SETTING_KEYS: readonly (keyof SpotterSettings)[] = [
  "enabled",
  "audio",
  "visual",
  "qualifying",
  "practice",
  "start_delay_s",
  "wording",
  "voice",
  "still_there",
  "hold_your_line",
  "car_length_m",
  "car_width_m",
];

export function settingsPatch(patch: Partial<SpotterSettings>): Partial<SpotterSettings> {
  const out: Record<string, unknown> = {};
  for (const k of SETTING_KEYS) if (Object.prototype.hasOwnProperty.call(patch, k)) out[k] = patch[k];
  return out as Partial<SpotterSettings>;
}

export const spotterApi = {
  get: async (): Promise<SpotterInfo> => info(await call("/api/spotter")),
  /** Save a partial change; answers the full GET payload. 422 = a value out of range (the server's words). */
  update: async (patch: Partial<SpotterSettings>): Promise<SpotterInfo> =>
    info(await call("/api/spotter/settings", json("PUT", settingsPatch(patch)))),
  /** "Car left", then "Clear left" on every connected radio. 409 = no radio connected (go live first). */
  test: async (): Promise<void> => {
    await call("/api/spotter/test", json("POST", {}));
  },
};

/** An older server without /api/spotter. */
export function isNotFound(e: unknown): boolean {
  return e instanceof EndpointError && e.status === 404;
}

/** The test was refused because no radio is connected. */
export function isRadioOff(e: unknown): boolean {
  return e instanceof EndpointError && e.status === 409;
}
