// Settings › Radio & voice › Spotter (design spec 9.2): pure view rules for the Spotter card, unit-tested in plain
// node (spotter.test.ts). The card (SpotterCard.tsx) renders them; SpotterSettings.tsx wires GET/PUT /api/spotter.
//
// Honest by construction: the master switch is OFF by default and says the evidence tier ("Tested on recorded races,
// not yet on track"); latency is "to playback" (the radio's `started` report), never "to the ear" (the AirPod's
// Bluetooth delay is not measured); an unknown value is "-".

import type { SpotterInfo, SpotterRecentCall, SpotterSettings, SpotterWording } from "../../../lib/spotter/types";
import { callText, reasonText } from "../../../lib/spotter/view";
import { macVoiceLabel } from "./model";

// ------------------------------------------------------------------------------------------------- copy

export const SPOTTER_HINT = "Calls cars alongside in F1 25 races. Tested on recorded races, not yet on track.";
export const NOT_SUPPORTED_HINT = "F1 25 only: other games don't send the other cars' positions.";
/** Option id for "the engineer's voice" (the API's null). */
export const SAME_VOICE = "__engineer__";

export interface WordingChoice {
  value: SpotterWording;
  label: string;
  hint: string;
}

export const WORDINGS: readonly WordingChoice[] = [
  { value: "auto", label: "Auto", hint: "Follows the seated driver's profile: simple wording for beginners." },
  { value: "standard", label: "Standard", hint: "Short calls: “Car left.” “Clear left.”" },
  { value: "simple", label: "Simple", hint: "Plain calls: “Car on your left.” “Left side clear.”" },
];

export const TOGGLE_HINTS = {
  audio: "The calls on the radio. Off: bars only.",
  visual: "Amber or red bars at the screen edges on every Drive page.",
  qualifying: "Races only by default. Never in time trial.",
  practice: "Races only by default. Never in time trial.",
  still_there: "Repeats the call while a car stays alongside (at most twice).",
  hold_your_line: "When a car alongside is very close and closing in.",
} as const;

/** The last answer with the changes not saved yet laid over (a switch shows its new position at once). */
export function withPending(info: SpotterInfo, pending: Partial<SpotterSettings>): SpotterInfo {
  return Object.keys(pending).length ? { ...info, settings: { ...info.settings, ...pending } } : info;
}

// ------------------------------------------------------------------------------------------------- master switch

export interface MasterView {
  on: boolean;
  disabled: boolean;
  hint: string;
}

/**
 * The master switch. Not available for the current game: disabled with the F1-only sentence; never locked ON (a
 * switch that is on can always be turned off).
 */
export function masterView(info: SpotterInfo): MasterView {
  const on = info.settings.enabled;
  const unsupported = info.availability.reason === "game_not_supported";
  return { on, disabled: unsupported && !on, hint: unsupported ? NOT_SUPPORTED_HINT : SPOTTER_HINT };
}

// ------------------------------------------------------------------------------------------------- status

/** "190 ms", "1.25 s", "4.2 ms"; unknown "-". */
export function msText(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return "-";
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`;
  if (ms < 10) return `${ms.toFixed(1)} ms`;
  return `${Math.round(ms)} ms`;
}

export function hzText(hz: number | null | undefined): string {
  return hz == null || !Number.isFinite(hz) ? "-" : `${Math.round(hz)} Hz`;
}

export interface StatusView {
  /** "Active" or why it is silent ("Silent: safety car"). */
  title: string;
  /** "60 Hz · audio ready · 190 ms to playback (p95)"; empty when nothing is known yet. */
  detail: string;
  warn: boolean;
}

/** The status row under the master switch (shown while the spotter is on). */
export function statusView(info: SpotterInfo): StatusView {
  const st = info.status;
  const parts: string[] = [];
  if (st.motion_hz !== null) parts.push(hzText(st.motion_hz));
  let warn = st.send_rate_low;
  if (!info.settings.audio) parts.push("spoken calls off");
  else if (st.audio) {
    // engine null: the server has no radio (voice off); "none": no Mac voice, so only device voices speak the calls
    // (the server never renders the phrases then: "preparing audio" would never end)
    if (st.audio.engine === null) parts.push("radio off");
    else if (st.audio.engine === "none") parts.push("no Mac voice");
    else if (st.audio.ready) parts.push("audio ready");
    else parts.push("preparing audio");
    if (st.audio.unverified > 0) {
      parts.push(`${st.audio.unverified} ${st.audio.unverified === 1 ? "phrase" : "phrases"} unverified`);
      warn = true;
    }
  }
  const p95 = info.latency.started_ms?.p95 ?? null;
  if (p95 !== null) parts.push(`${msText(p95)} to playback (p95)`);
  if (info.counters.errors > 0) {
    parts.push(`${info.counters.errors} ${info.counters.errors === 1 ? "error" : "errors"}`);
    warn = true;
  }
  return { title: st.active ? "Active" : reasonText(st.reason), detail: parts.join(" · "), warn };
}

/** The send-rate warning (spec 3.6: below 30 Hz the spotter decides later and may clear wrongly once). */
export function sendRateWarning(info: SpotterInfo): string | null {
  if (!info.status.send_rate_low) return null;
  const hz = info.status.motion_hz;
  return hz !== null
    ? `Set UDP Send Rate to 60 Hz for the spotter (now ${Math.round(hz)} Hz).`
    : "Set UDP Send Rate to 60 Hz for the spotter.";
}

export function startDelayText(s: number): string {
  if (!Number.isFinite(s)) return "-";
  return s <= 0 ? "At lights out" : `${Math.round(s)} s`;
}

// ------------------------------------------------------------------------------------------------- voice

export interface VoiceOption {
  id: string;
  label: string;
}

export interface VoiceView {
  /** Only with the Kokoro engine (spec 5.4: `say` speaks with the engineer's voice in v1). */
  show: boolean;
  value: string;
  options: VoiceOption[];
  hint: string;
}

/**
 * The spotter's voice: "Same as engineer" or a Kokoro voice, shown only while the Mac's engine is Kokoro. A voice the
 * settings hold that the Mac no longer lists is kept as an option (shown as sent), never silently swapped.
 */
export function voiceView(engine: string | null | undefined, voices: readonly string[], current: string | null): VoiceView {
  const show = engine === "kokoro";
  const ids = [...voices];
  if (current && !ids.includes(current)) ids.unshift(current);
  return {
    show,
    value: current ?? SAME_VOICE,
    options: [{ id: SAME_VOICE, label: "Same as engineer" }, ...ids.map((v) => ({ id: v, label: macVoiceLabel(v) }))],
    hint: "A different voice tells the spotter from the engineer.",
  };
}

export function voiceFromOption(id: string): string | null {
  return id === SAME_VOICE ? null : id;
}

// ------------------------------------------------------------------------------------------------- test

export type SpotterTestState = "idle" | "sending" | "sent" | "radio_off" | { error: string };

export interface TestView {
  enabled: boolean;
  hint: string;
  warn: boolean;
}

export function testView(info: SpotterInfo, state: SpotterTestState): TestView {
  if (info.availability.reason === "game_not_supported" && !info.settings.enabled) {
    return { enabled: false, hint: NOT_SUPPORTED_HINT, warn: false };
  }
  if (!info.settings.audio) return { enabled: false, hint: "Spoken calls are off.", warn: false };
  if (state === "sending") return { enabled: false, hint: "Sending…", warn: false };
  if (state === "sent") return { enabled: true, hint: "Sent: listen for “Car left”, then “Clear left”.", warn: false };
  if (state === "radio_off") return { enabled: true, hint: "No radio is connected: go live first.", warn: true };
  if (typeof state === "object") return { enabled: true, hint: state.error, warn: true };
  return { enabled: true, hint: "Says “Car left”, then “Clear left”, on every connected radio.", warn: false };
}

// ------------------------------------------------------------------------------------------------- diagnostics

export interface SpotterDiagRow {
  label: string;
  value: string;
  warn?: boolean;
}

function pair(s: { p50: number | null; p95: number | null } | null): string {
  if (!s || (s.p50 === null && s.p95 === null)) return "-";
  return `${msText(s.p50)} median · ${msText(s.p95)} p95`;
}

const DIMS_SOURCE: Record<string, string> = { regs: "published figures", settings: "your override" };
const DROP_WORDS: Record<string, string> = {
  ptt: "you were transmitting",
  voice_off: "voice off",
  stale: "too old",
  urgent_on_air: "urgent message on air",
  not_heard: "onset not heard",
};

function countsText(m: Record<string, number>, words: (k: string) => string): string {
  const parts = Object.entries(m)
    .filter(([, n]) => n > 0)
    .map(([k, n]) => `${words(k)} ${n}`);
  return parts.length ? parts.join(" · ") : "None";
}

/** "3 short overlaps · you were transmitting 1": calls decided but not spoken (short overlaps are shown, not said). */
function notSpoken(c: SpotterInfo["counters"]): string {
  const short = `${c.suppressed_short} short ${c.suppressed_short === 1 ? "overlap" : "overlaps"}`;
  const dropped = Object.entries(c.dropped).filter(([, n]) => n > 0);
  return dropped.length ? `${short} · ${countsText(c.dropped, (k) => DROP_WORDS[k] ?? k.replace(/_/g, " "))}` : short;
}

/** The Spotter diagnostics list (spec 6, 8.2). */
export function diagnosticsRows(info: SpotterInfo): SpotterDiagRow[] {
  const st = info.status;
  const d = st.dims;
  const size =
    d && d.length_m !== null && d.width_m !== null
      ? `${d.length_m.toFixed(2)} × ${d.width_m.toFixed(2)} m` +
        (d.formula ? ` · ${d.formula}` : "") +
        (d.source ? ` (${DIMS_SOURCE[d.source] ?? d.source})` : "")
      : "-";
  const a = st.audio;
  const audio = a
    ? [
        a.engine ?? "-",
        a.voice ? macVoiceLabel(a.voice) : "engineer's voice",
        a.phrases !== null ? `${a.phrases} phrases` : null,
        a.ready ? "ready" : "preparing",
        a.unverified ? `${a.unverified} unverified` : null,
        a.fallback ? `${a.fallback} on the fallback voice` : null,
      ]
        .filter(Boolean)
        .join(" · ")
    : "-";
  const c = info.counters;
  const lat = info.latency;
  return [
    { label: "Status", value: st.active ? "Active" : reasonText(st.reason) },
    { label: "Motion data", value: st.motion_hz !== null ? `${hzText(st.motion_hz)}${st.send_rate_low ? " · below 30 Hz" : ""}` : "-", warn: st.send_rate_low },
    { label: "Car size", value: size },
    { label: "Audio", value: audio, warn: !!a && (a.unverified > 0 || !a.ready) },
    { label: "Overlap to decision", value: pair(lat.onset_game_ms) },
    { label: "Decision", value: pair(lat.decide_ms) },
    { label: "Packet to radio", value: pair(lat.queued_ms) },
    { label: "Packet to playback", value: pair(lat.started_ms) },
    { label: "Network delay", value: pair(lat.data_age_ms) },
    { label: "Calls", value: countsText(c.calls, (k) => callText(k)) },
    { label: "Not spoken", value: notSpoken(c) },
    {
      label: "Packets",
      value: `${c.items} · ${c.skipped} skipped · ${c.invalid} invalid · ${c.errors} errors`,
      warn: c.errors > 0 || c.skipped > 0,
    },
  ];
}

export interface RecentRow {
  key: string;
  /** "14:03:22" local time, or "-". */
  time: string;
  text: string;
  spoken: boolean;
  /** "190 ms to playback", "not spoken", "queued 3.2 ms". */
  detail: string;
}

function clock(t: number | null): string {
  if (t === null) return "-";
  const d = new Date(t * 1000);
  if (Number.isNaN(d.getTime())) return "-";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/** The last calls in full, newest first as parsed (the radio log folds them; this list does not). */
export function recentRows(recent: readonly SpotterRecentCall[]): RecentRow[] {
  return recent.map((r, i) => ({
    key: `${r.t_unix ?? "x"}-${i}`,
    time: clock(r.t_unix),
    text: callText(r.kind, r.side),
    spoken: r.spoken,
    detail: !r.spoken
      ? "not spoken"
      : r.started_ms !== null
        ? `${msText(r.started_ms)} to playback`
        : r.queued_ms !== null
          ? `queued in ${msText(r.queued_ms)}`
          : "spoken",
  }));
}

/** The collapsed diagnostics line. */
export function diagnosticsSummary(info: SpotterInfo): string {
  const n = Object.values(info.counters.calls).reduce((a, b) => a + b, 0);
  const p95 = info.latency.queued_ms?.p95 ?? null;
  return `${n} ${n === 1 ? "call" : "calls"}${p95 !== null ? ` · to the radio in ${msText(p95)} (p95)` : ""}`;
}
