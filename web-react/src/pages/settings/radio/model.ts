// Settings › Radio & voice (spec 8; moved from the Svelte RadioView's settings block): pure view rules, unit-tested in
// plain node (model.test.ts). The page reads the radio store (lib/radio.ts, lane A) and, while the radio link is
// down, the read-only GET /api/voice/status, so the Mac's current voice and braking-call mode show before Go live.
//
// Where each setting lives (behaviour of the radio store and voice/hub.py, unchanged here):
//   this device   voice on/off, coaching amount, engineer voice (device or Mac), device voice, speaking speed: saved
//                 in localStorage at once; voice on/off and coaching are sent to the Mac whenever the radio connects
//   the Mac       the Mac's voice (Kokoro: bm_fable, bm_george, bf_emma, bf_isabella) and the braking-call mode are
//                 shared by every radio and can only be changed over the radio link (`settings` on /ws/radio)
// Unknown values stay unknown: no mode is pre-selected before the Mac has said which one is on.

import { INTENSITIES } from "../../../lib/drivers";
import { isMissingRoute } from "../../../lib/endpoints/review";
import type { VoiceStatus } from "../../../lib/endpoints/settings";
import type { RaceSettings } from "../../../lib/raceradio/types";
import {
  SERVER_VOICE_LABELS,
  VOICE_DISABLED,
  type CueMode,
  type DeviceVoice,
  type Intensity,
  type RadioServerState,
  type RadioState,
  type VoiceSource,
} from "../../../lib/radio";

// ------------------------------------------------------------------------------------------------- choices

export interface Choice<V extends string> {
  value: V;
  label: string;
  hint: string;
}

/** Braking calls (server coach/cues.py): the Svelte RadioView's wording. Also on Drive › Radio (spec 5.3). */
export const CUE_MODES: readonly Choice<CueMode>[] = [
  { value: "off", label: "Off", hint: "No braking calls during the lap." },
  { value: "focus", label: "Focus", hint: "Brake calls only for the 1-3 corners where you lose the most time." },
  { value: "markers", label: "Markers", hint: "The corner's name about 2 s before every braking zone." },
  { value: "all", label: "All", hint: "A brake call at every braking zone." },
];

/** Coaching amount on the radio: the same three levels and hints as a driver profile (lib/drivers.ts). */
export const COACHING: readonly Choice<Intensity>[] = INTENSITIES.map((i) => ({ value: i.value, label: i.label, hint: i.hint }));

export function isCueMode(v: unknown): v is CueMode {
  return typeof v === "string" && CUE_MODES.some((m) => m.value === v);
}

export function isIntensity(v: unknown): v is Intensity {
  return typeof v === "string" && COACHING.some((c) => c.value === v);
}

// ------------------------------------------------------------------------------------------------- labels

/** The device in the driver's hand, for "This iPad". iPadOS 13+ reports a desktop Mac UA; touch gives it away. */
export function deviceNoun(ua: string, maxTouchPoints: number): "iPad" | "iPhone" | "device" {
  if (/iPad/.test(ua) || (/Macintosh/.test(ua) && maxTouchPoints > 1)) return "iPad";
  if (/iPhone|iPod/.test(ua)) return "iPhone";
  return "device";
}

/** "This iPad" / "This iPhone" / "This device" (never "This Mac": the other choice is the Mac's voice). */
export function thisDevice(noun: ReturnType<typeof deviceNoun>): string {
  return `This ${noun}`;
}

/** A Kokoro voice id as the driver reads it ("George · British male"); unknown ids show as sent. */
export function macVoiceLabel(v: string | null | undefined): string {
  if (!v) return "System default";
  return SERVER_VOICE_LABELS[v] ?? v;
}

const QUALITY_WORD: Record<DeviceVoice["quality"], string> = { premium: "Premium", enhanced: "Enhanced", standard: "" };

/** "Jamie (Premium) · en-GB"; the quality is added only when the name does not already say it. */
export function deviceVoiceLabel(v: DeviceVoice): string {
  const q = QUALITY_WORD[v.quality];
  const quality = q && !v.name.toLowerCase().includes(v.quality) ? ` (${q})` : "";
  return `${v.name}${quality} · ${v.lang}`;
}

/** The device voice in use: the chosen one if installed, else the best available (radio.currentDeviceVoiceUri). */
export function currentDeviceVoice(voices: readonly DeviceVoice[], chosen: string | null): string | null {
  if (chosen && voices.some((v) => v.uri === chosen)) return chosen;
  return voices[0]?.uri ?? null;
}

/** Speaking speed as shown next to the slider: "1.05×". */
export function speedText(rate: number): string {
  return Number.isFinite(rate) ? `${rate.toFixed(2)}×` : "-";
}

// ------------------------------------------------------------------------------------------------- the Mac's side

/** What the Mac reports about its voice and the radio, from the live link or from GET /api/voice/status. */
export type MacState = Pick<
  RadioServerState,
  "tts" | "tts_voice" | "tts_voices" | "tts_active" | "tts_ready" | "tts_neural" | "tts_status" | "cue_mode" | "stt"
> & { intensity: Intensity | null; voice_enabled: boolean | null; telemetry: string | null; from: "radio" | "status" };

/**
 * The Mac's state: the radio link's own state frame while it is up (always current), else the HTTP status read
 * once (shows the Mac's voice and braking-call mode before Go live). null = unknown (voice off, or not read yet).
 */
export function macState(server: RadioServerState | null, status: VoiceStatus | null | undefined): MacState | null {
  if (server) {
    return {
      tts: server.tts,
      tts_voice: server.tts_voice,
      tts_voices: server.tts_voices,
      tts_active: server.tts_active,
      tts_ready: server.tts_ready,
      tts_neural: server.tts_neural,
      tts_status: server.tts_status,
      cue_mode: server.cue_mode,
      stt: server.stt,
      intensity: isIntensity(server.intensity) ? server.intensity : null,
      voice_enabled: typeof server.voice_enabled === "boolean" ? server.voice_enabled : null,
      telemetry: server.telemetry ?? null,
      from: "radio",
    };
  }
  if (!status || status.enabled !== true || typeof status.tts !== "string") return null;
  return {
    tts: status.tts,
    tts_voice: typeof status.tts_voice === "string" ? status.tts_voice : null,
    tts_voices: Array.isArray(status.tts_voices) ? status.tts_voices.filter((v): v is string => typeof v === "string") : [],
    tts_active: typeof status.tts_active === "string" ? status.tts_active : undefined,
    tts_ready: status.tts_ready === true,
    tts_neural: status.tts_neural === true,
    tts_status: typeof status.tts_status === "string" ? status.tts_status : null,
    cue_mode: isCueMode(status.cue_mode) ? status.cue_mode : undefined,
    stt: typeof status.stt === "string" ? status.stt : "-",
    intensity: isIntensity(status.intensity) ? status.intensity : null,
    voice_enabled: typeof status.voice_enabled === "boolean" ? status.voice_enabled : null,
    telemetry: typeof status.telemetry === "string" ? status.telemetry : null,
    from: "status",
  };
}

export interface MacVoiceView {
  /** Short engine line for diagnostics ("Kokoro · bm_george", "say (fallback)"). */
  chip: string;
  /** One sentence for the driver. */
  note: string;
  /** The Mac is not speaking with its natural voice (fallback, starting, off). */
  warn: boolean;
  /** No voice at all on the Mac: messages are text only. */
  off: boolean;
}

/** The Mac's voice engine in words: the Svelte RadioView's `macVoice` rules. */
export function macVoiceView(s: Pick<MacState, "tts" | "tts_voice" | "tts_ready" | "tts_status" | "tts_active">): MacVoiceView {
  if (s.tts === "none") return { chip: "Off", note: "No voice on the Mac: messages are text only.", warn: true, off: true };
  if (s.tts === "kokoro") {
    if (s.tts_ready) {
      return { chip: `Kokoro · ${s.tts_voice ?? "default"}`, note: `Natural voice (Kokoro): ${macVoiceLabel(s.tts_voice)}.`, warn: false, off: false };
    }
    const why =
      s.tts_status === "unavailable"
        ? "The natural voice is not installed on the Mac (run scripts/setup-tts.sh)"
        : s.tts_status === "restarting"
          ? "The natural voice is restarting"
          : "The natural voice is starting";
    const fallback = s.tts_active === "say" ? "the macOS voice speaks meanwhile" : "messages are text only meanwhile";
    return { chip: `${s.tts_active ?? "say"} (fallback)`, note: `${why}; ${fallback}.`, warn: true, off: false };
  }
  return {
    chip: `${s.tts}${s.tts_voice ? ` · ${s.tts_voice}` : ""}`,
    note: `macOS voice: ${s.tts_voice ?? "system default"}.`,
    warn: false,
    off: false,
  };
}

// ------------------------------------------------------------------------------------------------- the radio link

export type LinkState = "off" | "starting" | "connecting" | "open" | "reconnecting";

export function linkState(s: Pick<RadioState, "phase" | "conn">): LinkState {
  if (s.phase === "idle") return "off";
  if (s.conn === "open") return "open";
  if (s.phase === "starting") return "starting";
  return s.conn === "connecting" ? "connecting" : "reconnecting";
}

export interface LinkBanner {
  tone: "default" | "accent" | "warning" | "danger";
  title: string;
  text: string;
  /** Offer Go live (the radio is off and the Mac's voice hub is on). */
  goLive: boolean;
}

/**
 * The one banner above the settings. The Mac's voice and the braking calls change only over the radio link, so with
 * the radio off the page says so and offers Go live; everything saved on this device works without it.
 */
export function linkBanner(input: {
  link: LinkState;
  retryInS: number | null;
  error: string | null;
  /** GET /api/voice/status said the voice hub is off (PITWALL_VOICE_ENABLED=false). */
  voiceDisabled: boolean;
}): LinkBanner | null {
  if (input.voiceDisabled) return { tone: "danger", title: "Voice is off on the Mac", text: VOICE_DISABLED, goLive: false };
  if (input.error && input.link !== "open") {
    return { tone: "warning", title: "The radio needs attention", text: input.error, goLive: input.link === "off" };
  }
  switch (input.link) {
    case "off":
      return {
        tone: "default",
        title: "The radio is off",
        text:
          "The Mac's voice and the braking calls change over the radio link: go live to change them. Everything else " +
          "here is saved on this device now and used when the radio goes live.",
        goLive: true,
      };
    case "starting":
    case "connecting":
      return { tone: "default", title: "Connecting to the radio…", text: "The Mac's settings unlock once the link is up.", goLive: false };
    case "reconnecting":
      return {
        tone: "warning",
        title: input.retryInS ? `Radio link lost · retrying in ${input.retryInS} s` : "Radio link lost · reconnecting",
        text: "The Mac's voice and the braking calls unlock again when the link is back.",
        goLive: false,
      };
    case "open":
      return null;
  }
}

// ------------------------------------------------------------------------------------------------- test voice

export interface TestVoiceView {
  target: VoiceSource;
  enabled: boolean;
  hint: string;
  warn: boolean;
}

/** One Test voice button for the voice in use: this device's (works offline) or the Mac's (needs the link). */
export function testVoiceView(input: {
  source: VoiceSource;
  deviceTtsCapable: boolean;
  noun: ReturnType<typeof deviceNoun>;
  link: LinkState;
  macOff: boolean;
  /** The Mac's voice hub is off (GET /api/voice/status: enabled false): no radio at all. */
  voiceDisabled?: boolean;
  serverVoiceTest: RadioState["serverVoiceTest"];
}): TestVoiceView {
  if (input.source === "device" && input.deviceTtsCapable) {
    return { target: "device", enabled: true, hint: `Says a radio check with this ${input.noun}'s voice.`, warn: false };
  }
  if (input.voiceDisabled) return { target: "server", enabled: false, hint: "Voice is off on the Mac.", warn: true };
  if (input.macOff) return { target: "server", enabled: false, hint: "The Mac has no voice: messages are text only.", warn: true };
  if (input.link !== "open") {
    return { target: "server", enabled: false, hint: "Go live first: the Mac's voice comes over the radio link.", warn: false };
  }
  if (input.serverVoiceTest === "failed") {
    return { target: "server", enabled: true, hint: "The test did not reach the Mac: the radio link is down.", warn: true };
  }
  if (input.serverVoiceTest === "sent") {
    return { target: "server", enabled: true, hint: "Sent: the Mac says a radio check on every connected radio.", warn: false };
  }
  return { target: "server", enabled: true, hint: "The Mac says a radio check on every connected radio.", warn: false };
}

// ------------------------------------------------------------------------------------------------- effective values

/** Voice on/off in effect: the Mac's while the link is up (a driver change may have set it), else this device's. */
export function voiceOn(link: LinkState, mac: MacState | null, local: boolean): boolean {
  return link === "open" && mac?.from === "radio" && mac.voice_enabled !== null ? mac.voice_enabled : local;
}

/** Coaching amount in effect: the Mac's while the link is up, else this device's (sent when the radio goes live). */
export function coachingIn(link: LinkState, mac: MacState | null, local: Intensity): Intensity {
  return link === "open" && mac?.from === "radio" && mac.intensity ? mac.intensity : local;
}

export function voiceHint(on: boolean): string {
  return on ? "The engineer speaks on the radio." : "Answers only: the engineer speaks only when you ask.";
}

export function sourceHint(source: VoiceSource, noun: ReturnType<typeof deviceNoun>, deviceTtsCapable: boolean): string {
  if (!deviceTtsCapable) return "This browser cannot speak by itself: the Mac's voice plays here.";
  return source === "device"
    ? `This ${noun} speaks the messages with its own voice.`
    : `The Mac's voice plays on this ${noun}.`;
}

/** Coaching and voice also follow the seated driver's profile when the radio follows drivers (voice/hub.py
 * apply_driver): the profile applies when its driver sits in or is edited. */
export function followsDriverNote(radioFollowsDriver: boolean): string | null {
  if (!radioFollowsDriver) return null;
  return "Each driver's profile sets coaching and voice when they sit in (Settings › Drivers). A change here lasts until the next driver change.";
}

/** The collapsed Diagnostics line: who speaks, the link, the mic. */
export function diagnosticsSummary(input: {
  source: VoiceSource;
  deviceTtsCapable: boolean;
  noun: ReturnType<typeof deviceNoun>;
  mac: MacState | null;
  link: LinkState;
  micLabel: string;
}): string {
  const tts =
    input.source === "device" && input.deviceTtsCapable
      ? `this ${input.noun}`
      : input.mac
        ? macVoiceView(input.mac).chip
        : "-";
  if (input.link === "off") return `Speech: ${tts} · radio off`;
  const link = input.link === "open" ? "link up" : "link down";
  return `Speech: ${tts} · ${link} · ${input.micLabel.toLowerCase()}`;
}

// --------------------------------------------------------------------------- race radio (P2): online names

/** Say online players' names (household; GET/PUT /api/race/settings, race-radio spec 8.3): off by default. */
export const ONLINE_NAMES_TITLE = "Say online players' names";
/** Where the race calls are chosen (the coaching amount above also sets how many a lap). */
export const RACE_CALLS_NOTE = "Race calls are set per driver: Settings › Drivers.";
export const ONLINE_NAMES_HINT = "Only when you ask who's ahead or behind. Names are never saved or written to logs.";

export interface OnlineNamesView {
  /** The Mac has the setting. A server without it answers FastAPI's own 404: the row is left out. */
  shown: boolean;
  /** The stored value; null while unknown (nothing is pre-selected). */
  value: boolean | null;
  disabled: boolean;
  hint: string;
  /** The hint is a problem (unknown, or a change that was not saved). */
  warn: boolean;
}

export function onlineNamesView(input: {
  data: RaceSettings | undefined;
  error: unknown;
  saving: boolean;
  saveError: string | null;
}): OnlineNamesView {
  const { data, error, saving, saveError } = input;
  if (data === undefined && isMissingRoute(error)) {
    return { shown: false, value: null, disabled: true, hint: ONLINE_NAMES_HINT, warn: false };
  }
  const value = data ? data.online_names : null;
  if (saveError) return { shown: true, value, disabled: saving || value === null, hint: `Not saved: ${saveError}`, warn: true };
  if (value === null) {
    const hint = error ? "Unknown: the Mac has not answered." : "Reading the Mac's setting…";
    return { shown: true, value, disabled: true, hint, warn: !!error };
  }
  return { shown: true, value, disabled: saving, hint: ONLINE_NAMES_HINT, warn: false };
}

// ------------------------------------------------------------------------------------------------- diagnostics

export interface DiagRow {
  label: string;
  value: string;
  warn?: boolean;
}

const TELEMETRY_WORD: Record<string, string> = { live: "Live", stale: "Stale", no_data: "No data" };

/** The Diagnostics list (the Svelte RadioView's status badges and stats line, in words). Unknown is "-". */
export function diagnosticsRows(
  s: Pick<
    RadioState,
    | "phase"
    | "conn"
    | "retryInS"
    | "rttMs"
    | "wake"
    | "audio"
    | "audioSession"
    | "server"
    | "stats"
    | "deviceVoices"
    | "allVoices"
    | "deviceTtsCapable"
  >,
  mac: MacState | null,
  micLabel: string,
): DiagRow[] {
  const link = linkState(s);
  const linkText =
    link === "open"
      ? s.rttMs != null && Number.isFinite(s.rttMs)
        ? `Up · ${Math.round(s.rttMs)} ms round trip`
        : "Up"
      : link === "off"
        ? "Off"
        : link === "reconnecting"
          ? s.retryInS
            ? `Reconnecting · ${s.retryInS} s`
            : "Reconnecting…"
          : "Connecting…";
  const wake = s.wake === "on" ? "Kept awake" : s.wake === "off" ? "May sleep" : "No wake lock in this browser";
  const audio = s.audio === "none" ? "-" : `${s.audio}${s.audioSession !== "unset" ? ` · session ${s.audioSession}` : ""}`;
  const mv = mac ? macVoiceView(mac) : null;
  const st = s.stats;
  const capture = st.contextRate
    ? `${st.contextRate} Hz → 16 kHz${st.taps ? ` · ${st.taps}-tap filter` : ""} · ${st.framesSent} frames sent` +
      (st.framesDropped ? ` · ${st.framesDropped} dropped` : "")
    : "-";
  const english = s.allVoices.filter((v) => v.lang.toLowerCase().replace("_", "-").startsWith("en")).length;
  return [
    { label: "Radio link", value: linkText, warn: link === "reconnecting" },
    { label: "Microphone", value: micLabel },
    { label: "Screen", value: wake, warn: s.wake === "off" && s.phase !== "idle" },
    { label: "Audio", value: audio, warn: s.audio !== "none" && s.audio !== "running" },
    { label: "Mic audio", value: capture },
    { label: "Speech to text (Mac)", value: mac?.stt || "-" },
    { label: "Mac voice", value: mv ? `${mv.chip}. ${mv.note}` : "-", warn: mv?.warn },
    { label: "Telemetry (Mac)", value: mac?.telemetry ? (TELEMETRY_WORD[mac.telemetry] ?? mac.telemetry) : "-" },
    { label: "Push to talk", value: link === "open" ? (s.server?.ptt_source ?? "Not pressed") : "-" },
    {
      label: "Voices in this browser",
      value: s.deviceTtsCapable ? `${s.deviceVoices.length} English to choose from · ${english} English of ${s.allVoices.length} in total` : "None (no Web Speech)",
    },
  ];
}
