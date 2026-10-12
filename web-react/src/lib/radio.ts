// Radio client store for `/ws/radio` - protocol in docs/voice-protocol.md.
//
// Framework-agnostic port of the Svelte store web/src/lib/radio.svelte.ts, which stays the behaviour reference and
// is not edited. Same WebSocket protocol, same iOS rules, same public API (state fields + methods), on the shared
// `Store` base class: immutable state + subscribe, the contract React's useSyncExternalStore needs. `radio` is a
// module-level singleton, so the radio keeps running whichever page is open (Drive strip, Drive › Radio, the mini
// radio bar on every other page).
//
// The driver's iPad/iPhone is the radio: one AirPod is mic and earpiece, game audio stays on the TV. Every iOS
// rule below comes from docs/research/voice-stack.md §5.2 and fixes a failure mode reported against WebKit:
// * ONE AudioContext per session, created and resume()d synchronously inside the "Go live" tap (autoplay
//   unlock). All speech plays through it as AudioBufferSourceNodes; no <audio> elements (mixing them with
//   capture degrades both on iOS).
// * navigator.audioSession.type = "play-and-record" (Safari 16.4+, feature-detected) before getUserMedia.
// * getUserMedia once per session and the track stays open: PTT never opens/closes the mic (that breaks AirPods
//   routing). Mic audio streams continuously as 16 kHz int16 frames (resampled in public/mic-worklet.js, an
//   identical copy of web/public/mic-worklet.js); the server does all gating (PTT, half-duplex).
// * iOS ends or silently mutes capture in the background, and drops the wake lock when hidden: on return to the
//   foreground (or when the track ends) the mic and wake lock are re-acquired and `hello` is resent.
// Playback: `say` is followed by binary int16 frames until `say_end`; the clip is then scheduled on the shared
// context. `playback started/ended` reports feed the server's half-duplex gate and latency measurement.
// Pressing PTT while audio plays is a local barge-in: playback stops at once and `stop_tts` is sent. A message that
// arrives while the driver is transmitting (screen PTT, or the wheel button seen through server state) is not
// played (the server gates the mic while a message is "speaking", which would silently cut the transmission): it is
// shown, logged, and answered with `stop_tts`. While the AudioContext is not running (iOS interruption) only the
// newest clip is kept, and clips that went stale during the interruption are dropped on resume instead of being
// played back to back.
// PTT release has a hang time: the end of the driver's last word is still in the capture path (iOS voice
// processing, Bluetooth HFP, the worklet's partial frame) when the thumb lifts, and the server discards every frame
// after `ptt down:false`. So the release goes out RELEASE_TAIL_MS later, after the worklet flushed its partial frame.
// Link health: backoff resets only once the server sent `state` (a server that accepts and closes at once must not
// cause a reconnect storm); a refused handshake (the server rejects auth before accept(), which a browser only sees
// as close code 1006) is diagnosed over HTTP; a connect that hangs is abandoned after CONNECT_TIMEOUT_MS.
//
// Differences from the Svelte store (none changes the protocol):
// * the access token comes from ./auth (same sessionStorage key, shared with every other request of this app);
// * the worklet URL follows Vite's base, so it loads at /next/ as well as at /;
// * capabilities (secure context, Web Speech, wake lock) are detected per instance instead of at import, so the
//   module can be imported in plain node (tests) and each test can stub the browser it needs.

import { accessToken, forgetToken, wsUrl } from "./auth";
import { Store } from "./store";

export type Intensity = "quiet" | "normal" | "detailed";
/** "strategy": the race engineer's proactive strategy calls (voice/types.py MessageKind.STRATEGY, pitwall.strategy);
 * "goal": a goal reached (MessageKind.GOAL); "validation": a rig validation prompt (MessageKind.VALIDATION). Every
 * `say` frame is spoken whatever its kind: a kind this dashboard does not know is only labelled INFO. */
export type SayKind =
  | "answer"
  | "control"
  | "cue"
  | "alert"
  | "lap_summary"
  | "coaching"
  | "info"
  | "strategy"
  | "goal"
  | "validation"
  /* --- spotter --- */
  | "spotter"; // F1 spotter calls (MessageKind.SPOTTER: "car left", "clear left"; lib/spotter); never shown as `current`
/* --- end spotter --- */
export type LogKind = SayKind | "transcript" | "you" | "error" | "system";
export type Phase = "idle" | "starting" | "live";
export type ConnStatus = "offline" | "connecting" | "open" | "waiting";
export type MicStatus = "off" | "requesting" | "live" | "muted" | "ended" | "denied" | "unavailable" | "error";
export type WakeStatus = "unsupported" | "off" | "on";
export type AudioSessionStatus = "play-and-record" | "unsupported" | "unset";
export type VoiceTestStatus = "idle" | "sent" | "failed";

/** Live braking cues (server coach/cues.py): none, focus corners only, corner names, or every braking zone. */
export type CueMode = "off" | "focus" | "markers" | "all";

export interface RadioServerState {
  cue_mode?: CueMode;
  ptt: boolean;
  listening: boolean;
  speaking: boolean;
  busy?: boolean;
  quiet?: { until_lap?: number | null; indefinite?: boolean };
  intensity: Intensity;
  voice_enabled?: boolean;
  stt: string;
  /** Configured server voice engine: "kokoro" (neural, with `say` as fallback) | "say" | "none". */
  tts: string;
  /** Server voice in use (Kokoro voice id, or the macOS voice for `say`). */
  tts_voice?: string | null;
  /** Server voices the driver may pick (empty: the engine has no picker). */
  tts_voices?: string[];
  /** Engine rendering messages right now: "kokoro", or "say" while the Kokoro worker starts / restarts. */
  tts_active?: string;
  tts_ready?: boolean;
  tts_neural?: boolean;
  /** Kokoro worker state: "starting" | "ready" | "restarting" | "unavailable" | "stopped". */
  tts_status?: string | null;
  telemetry: "live" | "stale" | "no_data";
  ptt_source: "screen" | "wheel" | null;
  clients?: number;
  /* --- spotter --- spec 8.4: on, its phrase audio made, its own Kokoro voice (null = the engineer's). Absent on
   * servers without the spotter. Informational: the settings card reads GET /api/spotter. */
  spotter?: { enabled: boolean; audio_ready: boolean; voice: string | null };
  /* --- end spotter --- */
}

export type VoiceSource = "device" | "server";

export interface DeviceVoice {
  uri: string;
  name: string;
  lang: string;
  quality: "premium" | "enhanced" | "standard";
}

/** Every voice the browser exposes (all languages): shown for diagnosis and reported to the server. */
export interface BrowserVoice {
  name: string;
  lang: string;
  uri: string;
  local: boolean;
  default: boolean;
}

export interface RadioSettings {
  voiceEnabled: boolean;
  intensity: Intensity;
  /** "device": this device speaks message text with its own voices (e.g. iOS Premium); "server": play the Mac's PCM. */
  voiceSource: VoiceSource;
  deviceVoice: string | null; // SpeechSynthesisVoice.voiceURI; null = best available
  deviceRate: number; // SpeechSynthesisUtterance.rate (1 = normal)
  /**
   * Settings schema version. 2 = the one-time switch to the Mac's natural (neural) voice has been offered: when
   * the server first reports a neural engine that is ready, a stored "device" choice becomes "server" once. The
   * driver can switch back, and that choice then sticks.
   */
  version: number;
}

export interface LogEntry {
  seq: number;
  at: number; // Date.now()
  kind: LogKind;
  text: string;
  meta: string;
  id: string | null; // message id for `say` entries
  count: number; // identical consecutive entries are folded
}

export interface CurrentMessage {
  id: string;
  kind: SayKind;
  text: string;
  at: number; // Date.now()
  audioS: number; // 0 = display only
}

export interface RadioStats {
  contextRate: number;
  taps: number;
  framesSent: number;
  framesDropped: number;
  bufferedBytes: number;
}

/** Everything the UI reads. Immutable: every change produces a new object (and new nested objects / arrays). */
export interface RadioState {
  phase: Phase;
  conn: ConnStatus;
  mic: MicStatus;
  /** Mic frames have been digital silence for a while: likely an iOS muted-but-"live" track. */
  micSilent: boolean;
  wake: WakeStatus;
  /** AudioContext state ("none" before Go live). iOS adds "interrupted" (calls, Siri). */
  audio: string;
  audioSession: AudioSessionStatus;
  /** The hub's last `state` frame; null while the link is down. */
  server: RadioServerState | null;
  /** The newest engineer message (kept after the radio stops, like the log). */
  current: CurrentMessage | null;
  /** Id of the message whose audio is audible now. */
  speakingId: string | null;
  /** Audio is playing or scheduled locally (PTT now = barge-in). */
  speaking: boolean;
  log: readonly LogEntry[];
  /** Input level meter position 0..1 (-60..0 dBFS), with a short decay. */
  level: number;
  rttMs: number | null;
  /** On-screen (or Space key) PTT held on this device. */
  pttHeld: boolean;
  settings: RadioSettings;
  /** Problem that needs the driver's attention (cleared when resolved). */
  error: string | null;
  /** Last "Test voice" request for the Mac's voice. */
  serverVoiceTest: VoiceTestStatus;
  retryInS: number | null;
  stats: RadioStats;
  /** English voices installed on this device (Premium first, British first). */
  deviceVoices: readonly DeviceVoice[];
  allVoices: readonly BrowserVoice[];
  /** This page can capture audio at all (HTTPS/localhost + AudioWorklet). False = listen-only. */
  micCapable: boolean;
  /** This browser can speak messages with its own voices (Web Speech API). */
  deviceTtsCapable: boolean;
}

type ServerMessage =
  | ({ type: "state" } & RadioServerState)
  | { type: "transcript"; text: string; stt_ms: number; audio_s: number }
  | {
      type: "say";
      id: string;
      kind: SayKind;
      text: string;
      speech: string;
      sample_rate: number;
      n_bytes: number;
      meta?: Record<string, unknown>;
      device_tts?: boolean;
    }
  | { type: "say_end"; id: string }
  | { type: "cancel"; id?: string }
  | { type: "pong"; t: number; server_ms: number }
  | { type: "error"; message: string };

type WorkletMessage =
  | { type: "ready"; inputRate: number; outputRate: number; taps: number; phases: number; exact: boolean }
  | { type: "frame"; pcm: ArrayBuffer; rms: number; peak: number }
  | { type: "flushed"; seq: number };

interface PendingSay {
  id: string;
  kind: SayKind;
  sampleRate: number;
  expected: number;
  chunks: ArrayBuffer[];
  received: number;
}

interface Playback {
  id: string;
  kind: SayKind;
  source: AudioBufferSourceNode;
  startAt: number; // AudioContext time
  receivedAt: number; // performance.now()
  started: boolean;
  timer: ReturnType<typeof setTimeout> | null;
}

interface DeviceUtterance {
  u: SpeechSynthesisUtterance;
  kind: SayKind;
  queuedAt: number; // performance.now()
  started: boolean;
}

/** One WebSocket connection attempt and what it has shown so far. */
interface LinkAttempt {
  startedAt: number; // performance.now()
  opened: boolean;
  /** The server sent `state`: the hub accepted us. Only this resets the reconnect backoff. */
  healthy: boolean;
  /** `error` received before any `state` (e.g. "voice is disabled", sent just before the server closes). */
  serverError: string | null;
}

/** What playback-queue policies see of a message being played (AudioContext clip or device utterance). */
interface ClipInfo {
  id: string;
  started: boolean;
  at: number; // performance.now() when it arrived
  device: boolean; // spoken by the Web Speech API
}

type ProbeResult = "ok" | "denied" | "disabled" | "unreachable";

/** The AudioWorklet module could not be loaded or instantiated (not a microphone problem). */
class WorkletLoadError extends Error {}

export const MIC_SAMPLE_RATE = 16000;
export const PROTOCOL_VERSION = 1;
// Vite's base (/next/ until the switch-over, / after it). Bump `v` when the worklet changes (it is cached like any
// static file); web/ and web-react/ ship identical copies.
const WORKLET_URL = `${import.meta.env.BASE_URL}mic-worklet.js?v=2`;
const WORKLET_NAME = "pitwall-mic";
const MIC_CONSTRAINTS: MediaTrackConstraints = {
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: true,
  channelCount: 1,
};
const WS_OPEN = 1; // WebSocket.OPEN, as a literal so tests can stub the class without its statics
export const BACKOFF_MIN_MS = 500;
export const BACKOFF_MAX_MS = 8000;
/** Retry interval when the server refused us for a reason a quick retry will not fix (auth, voice disabled). */
export const BACKOFF_REFUSED_MS = 30_000;
export const CONNECT_TIMEOUT_MS = 7000; // a handshake stuck this long (black-holed SYN, Tailscale re-connecting) is abandoned
const FOREGROUND_RECONNECT_MS = 2000; // back in the foreground / online: a connect older than this is restarted
const PROBE_TIMEOUT_MS = 5000;
const REFUSALS_BEFORE_HINT = 3; // refused handshakes while HTTP works before suspecting the proxy
// Release hang time. Covers the capture path that is still delivering the last word when the thumb lifts: iOS
// voice-processing I/O plus Bluetooth HFP from an AirPod (tens to 150+ ms) and the hand-off to the page.
export const RELEASE_TAIL_MS = 250;
export const FLUSH_TIMEOUT_MS = 150; // the worklet did not answer the flush (context suspended): release anyway
export const STALE_CLIP_MS = 6000; // a message not heard within this of arriving is dropped instead of played late
const TICK_MS = 1000;
const PING_EVERY_TICKS = 2;
export const SILENCE_TIMEOUT_MS = 8000; // no inbound frame (state, pong, audio) for this long = dead socket
const VISIBLE_PROBE_MS = 3000; // after returning to the foreground: a reply is due within this
export const MAX_BUFFERED_BYTES = 128 * 1024; // ~4 s of mic audio stuck in the socket: drop frames instead
const SILENT_RMS = 1e-5; // -100 dBFS: digital silence (iOS muted-but-"live" track)
const SILENT_AFTER_MS = 8000;
const LEVEL_FLOOR_DB = -60;
export const LOG_MAX = 200;
const TURN_LATENCY_WINDOW_MS = 30_000; // replies later than this are not attributed to the driver's turn
export const SETTINGS_KEY = "pitwall-radio";
export const SETTINGS_VERSION = 2; // see RadioSettings.version
export const VOICE_TEST_TEXT = "Radio check, loud and clear. Box this lap for mediums.";
/** Display names for the Kokoro voices the server offers. */
export const SERVER_VOICE_LABELS: Record<string, string> = {
  bm_fable: "Fable · British male",
  bm_george: "George · British male",
  bf_emma: "Emma · British female",
  bf_isabella: "Isabella · British female",
};
export const ACCESS_DENIED =
  "Access denied: open the dashboard through Tailscale, or once with the ?token=… link from `pitwall token`.";
export const VOICE_DISABLED =
  "Voice is disabled on the Mac (PITWALL_VOICE_ENABLED=false): restart `pitwall serve` with voice on.";
export const PROXY_HINT =
  "The Mac answers over HTTPS but refuses the radio connection: check that the proxy (Tailscale Serve) passes WebSockets.";
const INTENSITIES: readonly Intensity[] = ["quiet", "normal", "detailed"];

// ---------------------------------------------------------------------------------------------- pure helpers

/** int16 little-endian mono PCM -> Float32 in [-1, 1). Odd trailing byte is ignored. */
export function pcm16ToFloat32(bytes: Uint8Array): Float32Array {
  const n = bytes.byteLength >> 1;
  const view = new DataView(bytes.buffer, bytes.byteOffset, n * 2);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) out[i] = view.getInt16(i * 2, true) / 32768;
  return out;
}

/** RMS (linear, full scale = 1) -> meter position 0..1 over LEVEL_FLOOR_DB..0 dBFS. */
export function levelFromRms(rms: number): number {
  if (!(rms > 0)) return 0;
  const db = 20 * Math.log10(rms);
  return Math.min(1, Math.max(0, (db - LEVEL_FLOOR_DB) / -LEVEL_FLOOR_DB));
}

/** The first `total` bytes of the chunks, concatenated. */
export function concatChunks(chunks: readonly ArrayBuffer[], total: number): Uint8Array {
  const out = new Uint8Array(total);
  let o = 0;
  for (const c of chunks) {
    const n = Math.min(c.byteLength, total - o);
    out.set(new Uint8Array(c, 0, n), o);
    o += n;
    if (o >= total) break;
  }
  return out;
}

function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function isIntensity(v: unknown): v is Intensity {
  return typeof v === "string" && (INTENSITIES as readonly string[]).includes(v);
}

// ------------------------------------------------------------------------------------------ device voices
// Web Speech API: on iOS/iPadOS Safari this exposes the voices installed in Settings › Accessibility › Spoken
// Content, including Premium/Enhanced neural voices, so the engineer can use e.g. "Jamie (Premium)" without any
// audio being generated on the Mac. Quality is inferred from the voiceURI (com.apple.voice.premium.en-GB.Jamie).

/** The browser can speak with its own voices (checked when called: tests stub the globals). */
export function deviceSpeechSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window && typeof SpeechSynthesisUtterance !== "undefined";
}

function voiceQuality(v: SpeechSynthesisVoice): DeviceVoice["quality"] {
  const s = `${v.voiceURI} ${v.name}`.toLowerCase();
  if (s.includes("premium")) return "premium";
  if (s.includes("enhanced")) return "enhanced";
  return "standard";
}

const QUALITY_RANK: Record<DeviceVoice["quality"], number> = { premium: 0, enhanced: 1, standard: 2 };

/** English device voices: Premium first, then Enhanced, British first within a quality, then by name. */
export function listDeviceVoices(): DeviceVoice[] {
  if (!deviceSpeechSupported()) return [];
  return speechSynthesis
    .getVoices()
    .filter((v) => v.lang.toLowerCase().replace("_", "-").startsWith("en"))
    .map((v) => ({ uri: v.voiceURI, name: v.name, lang: v.lang, quality: voiceQuality(v) }))
    .sort(
      (a, b) =>
        QUALITY_RANK[a.quality] - QUALITY_RANK[b.quality] ||
        Number(!a.lang.toLowerCase().includes("gb")) - Number(!b.lang.toLowerCase().includes("gb")) ||
        a.name.localeCompare(b.name),
    );
}

function tokenQuery(token: string | null): string {
  return token ? `?token=${encodeURIComponent(token)}` : "";
}

/**
 * Ask the HTTP side what a refused WebSocket handshake meant: the server rejects unauthorised radios before
 * accept(), which reaches the page only as close code 1006, indistinguishable from network loss. The token goes in
 * the query (not the header) on purpose: the server sets its auth cookie only for a query token, so one probe makes a
 * reload or a new tab work without the link.
 */
async function probeServer(token: string | null): Promise<ProbeResult> {
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), PROBE_TIMEOUT_MS);
  try {
    const r = await fetch(`/api/voice/status${tokenQuery(token)}`, {
      cache: "no-store",
      credentials: "same-origin",
      signal: abort.signal,
    });
    if (r.status === 401 || r.status === 403) return "denied";
    if (!r.ok) return "unreachable";
    const body = (await r.json()) as { enabled?: unknown };
    return body.enabled === false ? "disabled" : "ok";
  } catch {
    return "unreachable";
  } finally {
    clearTimeout(timer);
  }
}

function detectClient(): string {
  const ua = navigator.userAgent;
  // iPadOS 13+ reports a desktop Mac UA; touch support gives it away.
  if (/iPad/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) return "ipad";
  if (/iPhone|iPod/.test(ua)) return "iphone";
  if (/Android/.test(ua)) return "android";
  return "browser";
}

interface AudioSessionLike {
  type: string;
}

/** Safari 16.4+ Audio Session API. Returns false where unsupported (Chrome, Firefox, older iOS). */
function setAudioSessionType(type: string): boolean {
  const session = (navigator as Navigator & { audioSession?: AudioSessionLike }).audioSession;
  if (!session) return false;
  try {
    if (session.type !== type) session.type = type;
    return true;
  } catch {
    return false;
  }
}

/** Mic capture needs a secure context (HTTPS or localhost) for both getUserMedia and AudioWorklet. */
export function micSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    window.isSecureContext === true &&
    typeof navigator !== "undefined" &&
    typeof navigator.mediaDevices?.getUserMedia === "function" &&
    typeof AudioWorkletNode !== "undefined"
  );
}

function wakeLockSupported(): boolean {
  return typeof navigator !== "undefined" && "wakeLock" in navigator;
}

function stopStream(stream: MediaStream): void {
  for (const t of stream.getTracks()) t.stop();
}

/** Stored radio preferences (per device), validated field by field. Exported for tests. */
export function loadSettings(deviceTts: boolean): RadioSettings {
  const fallback: RadioSettings = {
    voiceEnabled: true,
    intensity: "normal",
    voiceSource: deviceTts ? "device" : "server",
    deviceVoice: null,
    deviceRate: 1,
    version: 1,
  };
  if (typeof window === "undefined") return fallback; // not a browser (the module imported in plain node)
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return fallback;
    const v = JSON.parse(raw) as Partial<RadioSettings>;
    return {
      voiceEnabled: typeof v.voiceEnabled === "boolean" ? v.voiceEnabled : fallback.voiceEnabled,
      intensity: isIntensity(v.intensity) ? v.intensity : fallback.intensity,
      voiceSource: v.voiceSource === "device" || v.voiceSource === "server" ? v.voiceSource : fallback.voiceSource,
      deviceVoice: typeof v.deviceVoice === "string" ? v.deviceVoice : null,
      deviceRate:
        typeof v.deviceRate === "number" && v.deviceRate >= 0.5 && v.deviceRate <= 2 ? v.deviceRate : fallback.deviceRate,
      version: typeof v.version === "number" && v.version >= 1 ? Math.floor(v.version) : 1,
    };
  } catch {
    return fallback; // storage unavailable (private mode, plain node) or corrupt JSON
  }
}

function describeMicError(e: unknown): { status: MicStatus; text: string } {
  if (e instanceof WorkletLoadError) {
    return {
      status: "error",
      text: `The audio processor (mic-worklet.js) failed to load: ${e.message}. Reload the page, then tap Restart mic.`,
    };
  }
  const name = e instanceof DOMException ? e.name : (e as { name?: unknown } | null)?.name;
  if (name === "NotAllowedError" || name === "SecurityError") {
    return {
      status: "denied",
      text:
        "Microphone permission denied. Allow it for this site (Safari aA menu › Website Settings › Microphone), " +
        "then tap Restart mic.",
    };
  }
  if (name === "NotFoundError" || name === "OverconstrainedError") {
    return { status: "error", text: "No microphone found. Connect the AirPod and tap Restart mic." };
  }
  if (name === "NotReadableError" || name === "AbortError") {
    return { status: "error", text: "The microphone is busy (another app or call?). Tap Restart mic." };
  }
  return { status: "error", text: `Microphone failed: ${errText(e)}` };
}

function initialState(micCapable: boolean, deviceTts: boolean): RadioState {
  return {
    phase: "idle",
    conn: "offline",
    mic: micCapable ? "off" : "unavailable",
    micSilent: false,
    wake: wakeLockSupported() ? "off" : "unsupported",
    audio: "none",
    audioSession: "unset",
    server: null,
    current: null,
    speakingId: null,
    speaking: false,
    log: [],
    level: 0,
    rttMs: null,
    pttHeld: false,
    settings: loadSettings(deviceTts),
    error: null,
    serverVoiceTest: "idle",
    retryInS: null,
    stats: { contextRate: 0, taps: 0, framesSent: 0, framesDropped: 0, bufferedBytes: 0 },
    deviceVoices: listDeviceVoices(),
    allVoices: [],
    micCapable,
    deviceTtsCapable: deviceTts,
  };
}

// ---------------------------------------------------------------------------------------------- store

export class RadioStore extends Store<RadioState> {
  /** True when this page can capture audio at all (HTTPS/localhost + AudioWorklet). */
  readonly micCapable: boolean;
  readonly deviceTtsCapable: boolean;

  private ctx: AudioContext | null = null;
  private playbackOut: GainNode | null = null;
  private worklet: AudioWorkletNode | null = null;
  private workletReady: Promise<AudioWorkletNode> | null = null;
  private stream: MediaStream | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private reacquiring: Promise<void> | null = null;
  private ws: WebSocket | null = null;
  private attempt: LinkAttempt | null = null; // describes `ws`
  /** The banner text this store set for a link problem (cleared when the link is healthy again). */
  private linkError: string | null = null;
  private refusals = 0; // consecutive refused handshakes
  private probing = false;
  private backoffMs = BACKOFF_MIN_MS;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAt = 0;
  private tickTimer: ReturnType<typeof setInterval> | null = null;
  private ticks = 0;
  private lastRxAt = 0;
  private wakeSentinel: WakeLockSentinel | null = null;
  private wakeRequest: Promise<void> | null = null;
  /** We sent `ptt down:true` and not yet the release (true through the release hang time). */
  private pttOnAir = false;
  private releaseTimer: ReturnType<typeof setTimeout> | null = null;
  private flushTimer: ReturnType<typeof setTimeout> | null = null;
  private flushSeq = 0;
  private pending: PendingSay | null = null;
  private playing = new Map<string, Playback>();
  /** Messages being spoken by the device voice (Web Speech API). */
  private utterances = new Map<string, DeviceUtterance>();
  private playEndAt = 0;
  private pausedAt: number | null = null; // when the AudioContext left "running"
  private session = 0; // bumped by goLive/stop; async work from an older session discards its result
  private seq = 0;
  private framesSent = 0;
  private framesDropped = 0;
  private silentSince: number | null = null;
  /** When the driver's current turn ended (PTT release or typed ask), for the latency notes in the log. */
  private turnAt: number | null = null;
  private turnBy: "release" | "ask" = "release";
  private hiddenAt: number | null = null;

  constructor() {
    const micCapable = micSupported();
    const deviceTts = deviceSpeechSupported();
    super(initialState(micCapable, deviceTts));
    this.micCapable = micCapable;
    this.deviceTtsCapable = deviceTts;
    accessToken(); // remember a token from the URL this app was opened with, before a nav tab replaces the hash
    if (deviceTts) {
      // iOS fills the voice list asynchronously
      speechSynthesis.addEventListener("voiceschanged", () => this.refreshVoices());
      this.refreshVoices();
    }
  }

  private refreshVoices(): void {
    if (!this.deviceTtsCapable) return;
    this.set({
      deviceVoices: listDeviceVoices(),
      allVoices: speechSynthesis.getVoices().map((v) => ({
        name: v.name,
        lang: v.lang,
        uri: v.voiceURI,
        local: v.localService,
        default: v.default,
      })),
    });
    this.reportVoices();
  }

  /** Diagnostic: tell the server which voices this browser exposes (names/languages only). */
  private reportVoices(): void {
    const voices = this.get().allVoices;
    if (voices.length) this.send({ type: "voices", voices });
  }

  // ------------------------------------------------------------------------------------------ lifecycle

  /**
   * Start the radio. MUST be called synchronously from a user gesture (click/tap handler): the AudioContext is
   * created and resumed, the wake lock requested and getUserMedia started before the handler returns.
   */
  goLive(): void {
    if (this.get().phase !== "idle") return;
    this.session++;
    this.set({
      phase: "starting",
      error: null,
      audioSession: setAudioSessionType("play-and-record") ? "play-and-record" : "unsupported",
    });
    let ctx: AudioContext;
    try {
      ctx = new AudioContext({ latencyHint: "interactive" });
    } catch (e) {
      this.set({ phase: "idle", error: `This browser cannot play audio (${errText(e)}).` });
      return;
    }
    this.ctx = ctx;
    void ctx.resume().catch(() => undefined);
    // A one-sample silent buffer started inside the gesture fully unlocks output on older iOS versions.
    const unlock = ctx.createBufferSource();
    unlock.buffer = ctx.createBuffer(1, 1, ctx.sampleRate);
    unlock.connect(ctx.destination);
    unlock.start(0);
    ctx.onstatechange = this.onContextState;
    this.set({ audio: ctx.state, stats: { ...this.get().stats, contextRate: ctx.sampleRate } });
    this.playbackOut = ctx.createGain();
    this.playbackOut.connect(ctx.destination);
    if (this.ttsMode() === "device") {
      // iOS only lets speechSynthesis speak after it was used inside a user gesture
      try {
        const u = new SpeechSynthesisUtterance(" ");
        u.volume = 0;
        speechSynthesis.speak(u);
      } catch {
        /* no device speech */
      }
      this.refreshVoices();
    }

    document.addEventListener("visibilitychange", this.onVisibility);
    window.addEventListener("online", this.onOnline);
    this.tickTimer = setInterval(this.onTick, TICK_MS);

    void this.requestWakeLock();
    const mic = this.micCapable ? this.acquireMic() : Promise.resolve();
    if (!this.micCapable) this.set({ mic: "unavailable" });
    this.connect();
    // With a token link, one HTTP request makes the server set its auth cookie (a WebSocket handshake does not),
    // so a reload or a new tab keeps working without the link.
    const token = accessToken();
    if (token) void probeServer(token);
    const session = this.session;
    void mic.finally(() => {
      if (session === this.session) this.set({ phase: "live" });
    });
    this.addLog("system", "Radio on", this.micCapable ? "" : "listen-only: no microphone over plain HTTP");
  }

  /** Stop everything: socket, mic, playback, wake lock, AudioContext. A new Go live tap is needed to restart. */
  stop(): void {
    if (this.get().phase === "idle") return;
    this.pttRelease(true);
    this.session++;
    this.set({ phase: "idle" });
    document.removeEventListener("visibilitychange", this.onVisibility);
    window.removeEventListener("online", this.onOnline);
    if (this.tickTimer) clearInterval(this.tickTimer);
    this.tickTimer = null;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.discardSocket(1000, "radio off");
    this.clearLinkError();
    this.refusals = 0;
    this.stopPlayback(null);
    this.pending = null;
    this.detachStream();
    if (this.worklet) {
      this.worklet.port.onmessage = null;
      this.worklet.disconnect();
    }
    this.worklet = null;
    this.workletReady = null;
    this.playbackOut = null;
    if (this.ctx) {
      this.ctx.onstatechange = null;
      void this.ctx.close().catch(() => undefined);
    }
    this.ctx = null;
    this.pausedAt = null;
    const sentinel = this.wakeSentinel;
    this.wakeSentinel = null;
    if (sentinel) void sentinel.release().catch(() => undefined);
    this.backoffMs = BACKOFF_MIN_MS;
    this.set({
      conn: "offline",
      mic: this.micCapable ? "off" : "unavailable",
      micSilent: false,
      wake: wakeLockSupported() ? "off" : "unsupported",
      audio: "none",
      server: null,
      speakingId: null,
      speaking: false,
      level: 0,
      rttMs: null,
      retryInS: null,
    });
    this.addLog("system", "Radio off");
  }

  // ------------------------------------------------------------------------------------------ driver actions

  /** PTT pressed (button press start / Space keydown). Barge-in if the engineer is talking. */
  pttPress(): void {
    const st = this.get();
    if (st.phase === "idle" || st.pttHeld) return;
    this.onGesture();
    const bargeIn = st.speaking || this.pending !== null;
    this.set({ pttHeld: true });
    this.turnAt = null;
    if (this.releaseTimer !== null) {
      // Re-keyed within the release hang time: the server never saw the release, so the transmission continues.
      clearTimeout(this.releaseTimer);
      this.releaseTimer = null;
    } else {
      this.finishRelease(); // a release still waiting for the worklet flush goes out first
      // PTT goes out before the playback `ended` report and stop_tts: the server treats PTT-while-speaking as a
      // barge-in (short mic gate), whereas `ended`/stop_tts first would apply the full echo tail and clip the
      // driver's first word. All of this runs in one task, so the audio still stops immediately.
      this.pttOnAir = this.send({ type: "ptt", down: true });
    }
    if (bargeIn) {
      this.stopPlayback(null);
      this.pending = null;
      this.send({ type: "stop_tts" });
    }
  }

  /**
   * PTT released. The server hears the release RELEASE_TAIL_MS later (after the worklet's partial frame), so the
   * end of the last word still in the capture path is kept. `immediate` skips the hang time (page hidden, radio
   * off) and also completes a release already in its hang time. Safe to call when nothing is held.
   */
  pttRelease(immediate = false): void {
    if (this.get().pttHeld) {
      this.set({ pttHeld: false });
      this.startTurn("release");
      if (!immediate && this.pttOnAir) this.releaseTimer = setTimeout(this.onReleaseTail, RELEASE_TAIL_MS);
    }
    if (immediate) this.finishRelease();
  }

  /** Typed question (same pipeline as speech, minus STT). */
  ask(text: string): boolean {
    const t = text.trim().slice(0, 300);
    if (!t) return false;
    this.onGesture();
    const sent = this.send({ type: "ask", text: t });
    if (sent) this.startTurn("ask");
    this.addLog("you", t, sent ? "typed" : "not sent: radio offline");
    return sent;
  }

  radioCheck(): boolean {
    return this.ask("radio check");
  }

  /** Stop the engineer talking without keying the mic. */
  stopSpeaking(): void {
    this.onGesture();
    this.stopPlayback(null);
    this.pending = null;
    this.send({ type: "stop_tts" });
  }

  setVoiceEnabled(on: boolean): void {
    this.updateSettings({ voiceEnabled: on });
    this.saveSettings();
    this.sendSettings();
  }

  setIntensity(intensity: Intensity): void {
    this.updateSettings({ intensity });
    this.saveSettings();
    this.sendSettings();
  }

  /** Server-wide setting (the cue engine is shared by every radio); the next state frame confirms it. */
  setCueMode(mode: CueMode): void {
    this.send({ type: "settings", cue_mode: mode });
  }

  /** Who speaks: this device's own voices, or the Mac's synthesised audio. */
  setVoiceSource(src: VoiceSource): void {
    this.onGesture();
    // an explicit choice answers the one-time natural-voice offer: migrateToNeuralVoice must not undo it later
    this.updateSettings({ voiceSource: src, version: SETTINGS_VERSION });
    this.saveSettings();
    this.sendSettings();
    if (src === "device") this.refreshVoices();
  }

  /** Server-wide voice (Kokoro voice id); the next state frame confirms it, an error frame reports a bad one. */
  setServerVoice(voice: string): void {
    if (!voice || voice === this.get().server?.tts_voice) return;
    this.send({ type: "settings", tts_voice: voice });
  }

  /** Have the Mac say a test phrase on every connected radio (server audio: switch this device to Mac voice). */
  testServerVoice(): void {
    this.onGesture();
    this.set({ serverVoiceTest: this.send({ type: "test_voice", text: VOICE_TEST_TEXT }) ? "sent" : "failed" });
  }

  setDeviceVoice(uri: string): void {
    this.updateSettings({ deviceVoice: uri || null });
    this.saveSettings();
  }

  setDeviceRate(rate: number): void {
    this.updateSettings({ deviceRate: Math.min(1.5, Math.max(0.7, rate)) });
    this.saveSettings();
  }

  /** The voice that will be used: the chosen one if installed, else the best available. */
  currentDeviceVoiceUri(): string | null {
    const { deviceVoices: list, settings } = this.get();
    const chosen = settings.deviceVoice;
    if (chosen && list.some((v) => v.uri === chosen)) return chosen;
    return list[0]?.uri ?? null;
  }

  /** Speak a sample locally with the selected device voice (user gesture; not sent to the server). */
  testDeviceVoice(): void {
    if (!this.deviceTtsCapable) return;
    this.onGesture();
    speechSynthesis.cancel();
    speechSynthesis.speak(this.makeUtterance(VOICE_TEST_TEXT));
  }

  /** Re-acquire the microphone on demand (user gesture: "Restart mic"). */
  restartMic(): Promise<void> {
    this.onGesture();
    return this.reacquireMic("restart");
  }

  /** Resume an interrupted/suspended AudioContext. Call from a user gesture. */
  resumeAudio(): void {
    this.onGesture();
  }

  // ------------------------------------------------------------------------------------------ PTT release

  /** End of the hang time: have the worklet post its partial frame, then release (onWorkletMessage "flushed"). */
  private onReleaseTail = (): void => {
    this.releaseTimer = null;
    if (!this.pttOnAir) return;
    const node = this.worklet;
    const ws = this.ws;
    if (node === null || ws === null || ws.readyState !== WS_OPEN) {
      this.finishRelease();
      return;
    }
    const seq = ++this.flushSeq;
    this.flushTimer = setTimeout(() => this.finishRelease(), FLUSH_TIMEOUT_MS);
    node.port.postMessage({ type: "flush", seq });
  };

  /** Send the pending release now (no-op when none is pending). Frames already posted have been sent. */
  private finishRelease(): void {
    if (this.releaseTimer !== null) clearTimeout(this.releaseTimer);
    if (this.flushTimer !== null) clearTimeout(this.flushTimer);
    this.releaseTimer = this.flushTimer = null;
    if (!this.pttOnAir) return;
    this.pttOnAir = false;
    this.send({ type: "ptt", down: false });
  }

  /** The driver is transmitting now: PTT held on this device, or the wheel button (seen through server state). */
  private transmitting(): boolean {
    const { pttHeld, server } = this.get();
    return pttHeld || (server?.ptt === true && server.ptt_source === "wheel");
  }

  // ------------------------------------------------------------------------------------------ microphone

  private ensureWorklet(ctx: AudioContext): Promise<AudioWorkletNode> {
    if (!this.workletReady) {
      const detail = (e: unknown) => (e instanceof Error ? e.message || e.name : String(e));
      this.workletReady = (async () => {
        try {
          // Rejects with an AbortError on any fetch or parse failure: tagged so it is not reported as a busy mic.
          await ctx.audioWorklet.addModule(WORKLET_URL);
        } catch (e) {
          throw new WorkletLoadError(detail(e));
        }
        if (this.ctx !== ctx) throw new Error("radio stopped");
        let node: AudioWorkletNode;
        try {
          node = new AudioWorkletNode(ctx, WORKLET_NAME, {
            numberOfInputs: 1,
            numberOfOutputs: 1,
            outputChannelCount: [1],
            channelCount: 1,
            channelCountMode: "explicit",
            channelInterpretation: "speakers",
          });
        } catch (e) {
          throw new WorkletLoadError(detail(e)); // module loaded but did not register the processor
        }
        node.port.onmessage = (ev: MessageEvent<WorkletMessage>) => this.onWorkletMessage(ev.data);
        // The output is silence; connecting it keeps the node pulled by the render graph on every engine.
        node.connect(ctx.destination);
        this.worklet = node;
        return node;
      })();
      this.workletReady.catch(() => {
        this.workletReady = null;
      });
    }
    return this.workletReady;
  }

  /** getUserMedia is called before the first await, so a call from goLive() runs inside the user gesture. */
  private async acquireMic(): Promise<void> {
    const ctx = this.ctx;
    if (!ctx) return;
    if (!this.micCapable) {
      this.set({ mic: "unavailable" });
      return;
    }
    const session = this.session;
    setAudioSessionType("play-and-record"); // idempotent; must precede every getUserMedia
    this.set({ mic: "requesting" });
    let streamP: Promise<MediaStream>;
    try {
      streamP = navigator.mediaDevices.getUserMedia({ audio: MIC_CONSTRAINTS, video: false });
    } catch (e) {
      streamP = Promise.reject(e); // some engines throw synchronously instead of rejecting
    }
    // Settle both, so a permission problem is reported as such even when the worklet failed too.
    const [streamR, nodeR] = await Promise.allSettled([streamP, this.ensureWorklet(ctx)]);
    if (streamR.status === "rejected" || nodeR.status === "rejected") {
      if (streamR.status === "fulfilled") stopStream(streamR.value); // the mic opened but cannot be used
      if (session !== this.session) return;
      this.micFailed(streamR.status === "rejected" ? streamR.reason : nodeR.status === "rejected" ? nodeR.reason : null);
      return;
    }
    const stream = streamR.value;
    const node = nodeR.value;
    if (session !== this.session || this.ctx !== ctx) {
      stopStream(stream);
      return;
    }
    const track = stream.getAudioTracks()[0];
    if (!track) {
      stopStream(stream);
      this.set({ mic: "error", error: "The browser returned no audio track." });
      return;
    }
    this.detachStream();
    this.stream = stream;
    track.addEventListener("ended", this.onTrackEnded);
    track.addEventListener("mute", this.onTrackMute);
    track.addEventListener("unmute", this.onTrackUnmute);
    try {
      this.source = ctx.createMediaStreamSource(stream);
      this.source.connect(node);
    } catch (e) {
      this.detachStream();
      this.micFailed(e);
      return;
    }
    this.micSilentReset();
    const error = this.get().error;
    this.set({
      mic: track.muted ? "muted" : "live",
      error: error && /microphone|mic/i.test(error) ? null : error,
    });
    // Opening capture can move iOS to a new audio route and suspend the context; it was unlocked by the tap.
    if (ctx.state !== "running") void ctx.resume().catch(() => undefined);
  }

  private micFailed(e: unknown): void {
    const { status, text } = describeMicError(e);
    this.set({ mic: status, error: text });
    this.addLog("error", text);
  }

  private micSilentReset(): void {
    this.silentSince = null;
    this.set({ micSilent: false });
  }

  private detachStream(): void {
    const stream = this.stream;
    this.stream = null;
    if (this.source) {
      this.source.disconnect();
      this.source = null;
    }
    if (!stream) return;
    for (const t of stream.getAudioTracks()) {
      t.removeEventListener("ended", this.onTrackEnded);
      t.removeEventListener("mute", this.onTrackMute);
      t.removeEventListener("unmute", this.onTrackUnmute);
    }
    stopStream(stream);
  }

  /** Close the old capture first (iOS allows one; a second getUserMedia mutes the first), then reopen. */
  private reacquireMic(reason: string): Promise<void> {
    if (this.get().phase === "idle" || !this.micCapable) return Promise.resolve();
    if (this.reacquiring) return this.reacquiring;
    this.reacquiring = (async () => {
      try {
        this.detachStream();
        await this.acquireMic();
        const mic = this.get().mic;
        if (mic === "live" || mic === "muted") this.addLog("system", "Mic re-acquired", reason);
        this.sendHello();
      } finally {
        this.reacquiring = null;
      }
    })();
    return this.reacquiring;
  }

  private micWasOpen(): boolean {
    const mic = this.get().mic;
    return mic === "live" || mic === "muted" || mic === "ended" || mic === "error";
  }

  private onTrackEnded = (): void => {
    this.set({ mic: "ended" });
    // getUserMedia fails while hidden; the visibility handler re-acquires on return.
    if (document.visibilityState === "visible") void this.reacquireMic("track ended");
  };

  private onTrackMute = (): void => {
    if (this.get().mic === "live") this.set({ mic: "muted" });
  };

  private onTrackUnmute = (): void => {
    if (this.get().mic === "muted") this.set({ mic: "live" });
  };

  private onWorkletMessage(m: WorkletMessage): void {
    if (m.type === "ready") {
      this.set({ stats: { ...this.get().stats, contextRate: m.inputRate, taps: m.taps } });
      return;
    }
    if (m.type === "flushed") {
      // The port is ordered: the partial frame (if any) arrived and was sent just before this.
      if (m.seq === this.flushSeq && this.flushTimer !== null) this.finishRelease();
      return;
    }
    const st = this.get();
    const level = Math.max(levelFromRms(m.rms), st.level - 0.04);
    let micSilent = st.micSilent;
    const now = performance.now();
    if (m.rms < SILENT_RMS && st.mic === "live") {
      this.silentSince ??= now;
      if (!micSilent && now - this.silentSince > SILENT_AFTER_MS) micSilent = true;
    } else {
      this.silentSince = null;
      micSilent = false;
    }
    this.set({ level, micSilent });
    const ws = this.ws;
    if (ws === null || ws.readyState !== WS_OPEN) return;
    if (ws.bufferedAmount > MAX_BUFFERED_BYTES) {
      this.framesDropped++;
      return;
    }
    ws.send(m.pcm);
    this.framesSent++;
  }

  // ------------------------------------------------------------------------------------------ socket

  private connect(): void {
    if (this.get().phase === "idle") return;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.set({ retryInS: null });
    this.discardSocket(4000, "reconnecting"); // reconnectNow() may restart a hung connect
    this.set({ conn: "connecting" });
    let ws: WebSocket;
    try {
      ws = new WebSocket(wsUrl("/ws/radio"));
    } catch (e) {
      this.addLog("error", `Cannot open radio socket: ${errText(e)}`);
      this.scheduleReconnect();
      return;
    }
    ws.binaryType = "arraybuffer";
    const attempt: LinkAttempt = { startedAt: performance.now(), opened: false, healthy: false, serverError: null };
    this.ws = ws;
    this.attempt = attempt;
    ws.onopen = () => {
      attempt.opened = true;
      this.set({ conn: "open" });
      this.lastRxAt = performance.now();
      this.sendHello();
      this.sendSettings();
      this.sendPing();
    };
    ws.onmessage = (ev: MessageEvent<string | ArrayBuffer>) => {
      this.lastRxAt = performance.now();
      if (typeof ev.data === "string") this.onText(ev.data);
      else this.onBinary(ev.data);
    };
    ws.onclose = (ev: CloseEvent) => {
      if (this.ws === ws) this.onSocketClosed(attempt, ev.code);
    };
    ws.onerror = () => undefined; // a close event always follows
  }

  /** First `state` on this socket: the hub accepted the radio. Only now is the link known to be good. */
  private onLinkHealthy(): void {
    this.backoffMs = BACKOFF_MIN_MS;
    this.refusals = 0;
    this.clearLinkError();
  }

  private onSocketClosed(attempt: LinkAttempt, code: number): void {
    if (code === 4401 || code === 1008) {
      // Only seen when a server closes after accept(); a rejected handshake arrives as 1006 (diagnoseRefusal).
      this.refused(ACCESS_DENIED);
    } else if (attempt.healthy) {
      this.socketGone();
    } else if (attempt.serverError !== null) {
      // Accepted, said why, closed (e.g. "voice is disabled"): retrying every few hundred ms would only spin.
      const err = attempt.serverError;
      this.refused(/voice is disabled/i.test(err) ? VOICE_DISABLED : `Radio unavailable: ${err}.`);
    } else {
      this.socketGone(); // never healthy: the backoff keeps growing
      if (!attempt.opened) void this.diagnoseRefusal();
    }
  }

  /** The server refused this radio for a reason a quick retry will not fix: say why, and retry slowly. */
  private refused(text: string): void {
    this.setLinkError(text);
    this.socketGone(BACKOFF_REFUSED_MS);
  }

  /** A handshake failed without a reason (close code 1006): ask the HTTP side whether it was auth or the network. */
  private async diagnoseRefusal(): Promise<void> {
    if (this.probing) return;
    this.probing = true;
    const session = this.session;
    const token = accessToken();
    let verdict: ProbeResult;
    try {
      verdict = await probeServer(token);
    } finally {
      this.probing = false;
    }
    if (session !== this.session || this.attempt?.healthy) return; // radio stopped, or the link recovered meanwhile
    if (verdict === "denied") {
      this.setLinkError(ACCESS_DENIED);
      // A forgotten stale token may have been hiding a valid cookie: then the next normal retry can succeed.
      if (!(token !== null && forgetToken())) this.retrySlowly();
    } else if (verdict === "disabled") {
      this.setLinkError(VOICE_DISABLED);
      this.retrySlowly();
    } else if (verdict === "ok" && ++this.refusals >= REFUSALS_BEFORE_HINT) {
      this.setLinkError(PROXY_HINT);
    }
  }

  /** Detach and close the current socket without waiting for a close handshake (it may never come). */
  private discardSocket(code: number, reason: string): void {
    const ws = this.ws;
    this.ws = null;
    this.attempt = null;
    if (!ws) return;
    ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null;
    try {
      ws.close(code, reason);
    } catch {
      /* already closing */
    }
  }

  /** Give up on the current socket (dead link, or a connect that never completes) and schedule a reconnect. */
  private dropSocket(reason: string, label = "Radio link lost"): void {
    if (!this.ws) return;
    this.discardSocket(4000, reason);
    this.addLog("system", label, reason);
    this.socketGone();
  }

  private socketGone(minDelayMs = 0): void {
    this.ws = null;
    this.attempt = null;
    this.pending = null; // a half-received clip is useless
    // The server releases PTT on disconnect; finishRelease() only clears the release state (nothing to send on).
    this.set({ server: null, rttMs: null, pttHeld: false });
    this.finishRelease();
    this.scheduleReconnect(minDelayMs);
  }

  private scheduleReconnect(minDelayMs = 0): void {
    if (this.get().phase === "idle") return;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    const delay = Math.max(minDelayMs, this.backoffMs * (0.8 + Math.random() * 0.4));
    this.backoffMs = Math.min(this.backoffMs * 2, BACKOFF_MAX_MS);
    this.reconnectAt = performance.now() + delay;
    this.set({ conn: "waiting", retryInS: Math.ceil(delay / 1000) });
    this.reconnectTimer = setTimeout(() => this.connect(), delay);
  }

  private retrySlowly(): void {
    if (this.get().conn === "waiting") this.scheduleReconnect(BACKOFF_REFUSED_MS);
  }

  /** Back in the foreground or online again: retry now instead of waiting out the backoff or a hung connect. */
  private reconnectNow(): void {
    const { phase, conn } = this.get();
    if (phase === "idle") return;
    const hung =
      conn === "connecting" &&
      this.attempt !== null &&
      performance.now() - this.attempt.startedAt > FOREGROUND_RECONNECT_MS;
    if (conn !== "waiting" && !hung) return;
    this.backoffMs = BACKOFF_MIN_MS;
    this.connect();
  }

  private setLinkError(text: string): void {
    this.linkError = text;
    this.set({ error: text });
  }

  private clearLinkError(): void {
    if (this.linkError !== null && this.get().error === this.linkError) this.set({ error: null });
    this.linkError = null;
  }

  private send(msg: Record<string, unknown>): boolean {
    const ws = this.ws;
    if (ws === null || ws.readyState !== WS_OPEN) return false;
    ws.send(JSON.stringify(msg));
    return true;
  }

  private sendHello(): void {
    queueMicrotask(() => this.reportVoices());
    this.send({
      type: "hello",
      client: detectClient(),
      sample_rate: MIC_SAMPLE_RATE,
      version: PROTOCOL_VERSION,
      tts_mode: this.ttsMode(),
    });
  }

  private sendSettings(): void {
    const { settings } = this.get();
    this.send({
      type: "settings",
      voice_enabled: settings.voiceEnabled,
      intensity: settings.intensity,
      tts_mode: this.ttsMode(),
    });
  }

  private ttsMode(): VoiceSource {
    return this.get().settings.voiceSource === "device" && this.deviceTtsCapable ? "device" : "server";
  }

  private sendPing(): void {
    this.send({ type: "ping", t: performance.now() });
  }

  private onText(raw: string): void {
    let msg: ServerMessage;
    try {
      msg = JSON.parse(raw) as ServerMessage;
    } catch {
      return;
    }
    switch (msg.type) {
      case "state":
        if (this.attempt !== null && !this.attempt.healthy) {
          this.attempt.healthy = true;
          this.onLinkHealthy();
        }
        this.onState(msg);
        break;
      case "transcript": {
        const ms = this.turnAt !== null && this.turnBy === "release" ? performance.now() - this.turnAt : Infinity;
        const sinceRelease = ms < TURN_LATENCY_WINDOW_MS ? ` · +${Math.round(ms)} ms after release` : "";
        this.addLog(
          "transcript",
          String(msg.text ?? "").trim() || "(nothing understood)",
          `STT ${msg.stt_ms} ms · ${Number(msg.audio_s).toFixed(1)} s audio${sinceRelease}`,
        );
        break;
      }
      case "say":
        this.onSay(msg);
        break;
      case "say_end":
        this.onSayEnd(msg.id);
        break;
      case "cancel":
        if (this.pending && (msg.id === undefined || this.pending.id === msg.id)) this.pending = null;
        this.stopPlayback(msg.id ?? null);
        break;
      case "pong":
        if (typeof msg.t === "number") this.set({ rttMs: Math.max(0, performance.now() - msg.t) });
        break;
      case "error":
        // Before any state this is the reason the server is about to close (onSocketClosed shows it).
        if (this.attempt !== null && !this.attempt.healthy) this.attempt.serverError = String(msg.message);
        this.addLog("error", String(msg.message));
        break;
    }
  }

  private onState(s: RadioServerState): void {
    const prev = this.get().server;
    this.set({ server: s });
    this.migrateToNeuralVoice(s);
    // Follow changes made on the server side (voice commands such as "more detail"). The first state after a
    // (re)connect is skipped: it predates our settings message and would overwrite the stored preference.
    if (prev === null) return;
    // Wheel PTT is only visible through state: track its release for the latency figures in the log.
    if (!prev.ptt && s.ptt && s.ptt_source === "wheel") this.turnAt = null;
    if (prev.ptt && !s.ptt && prev.ptt_source === "wheel") this.startTurn("release");
    const { settings } = this.get();
    const patch: Partial<RadioSettings> = {};
    if (isIntensity(s.intensity) && s.intensity !== prev.intensity && s.intensity !== settings.intensity) {
      patch.intensity = s.intensity;
    }
    if (
      typeof s.voice_enabled === "boolean" &&
      s.voice_enabled !== prev.voice_enabled &&
      s.voice_enabled !== settings.voiceEnabled
    ) {
      patch.voiceEnabled = s.voice_enabled;
    }
    if (patch.intensity !== undefined || patch.voiceEnabled !== undefined) {
      this.updateSettings(patch);
      this.saveSettings();
    }
  }

  /**
   * One-time switch to the Mac's natural voice: the first time the server reports a neural engine (Kokoro) ready, a
   * device that speaks with its own voice is moved to server audio, and the settings version records that the
   * offer was made. The driver can switch back to "This device"; that choice is kept from then on.
   */
  private migrateToNeuralVoice(s: RadioServerState): void {
    const { settings } = this.get();
    // only once the natural voice is really up: a Mac still on its `say` fallback is no upgrade over iOS voices
    if (settings.version >= SETTINGS_VERSION || s.tts_neural !== true || s.tts_ready !== true) return;
    if (settings.voiceSource === "device") {
      this.updateSettings({ version: SETTINGS_VERSION, voiceSource: "server" });
      this.addLog(
        "system",
        "Switched to the Mac's natural voice. You can switch back to this device's voice in Settings › Radio & voice.",
      );
      this.sendSettings();
    } else {
      this.updateSettings({ version: SETTINGS_VERSION });
    }
    this.saveSettings();
  }

  // ------------------------------------------------------------------------------------------ playback

  private onSay(m: Extract<ServerMessage, { type: "say" }>): void {
    if (this.pending) this.addLog("error", `Audio for ${this.pending.id} never finished`);
    const nBytes = Math.max(0, Math.floor(Number(m.n_bytes) || 0));
    const rate = Math.floor(Number(m.sample_rate) || 0);
    const audioS = nBytes > 0 && rate > 0 ? nBytes / 2 / rate : 0;
    const text = String(m.text ?? "");
    /* --- spotter: a spotter call never replaces the engineer's message on screen (the Drive bars show it, and the
     * log folds it); it is logged and played like any other message --- */
    if (m.kind !== "spotter") this.set({ current: { id: m.id, kind: m.kind, text, at: Date.now(), audioS } });
    /* --- end spotter --- */
    if (this.transmitting()) {
      // Playing this over the driver would cut their transmission: the server drops mic audio while a message is
      // "speaking". Treat it as a barge-in instead: show it, do not play it, and tell the server to stop.
      this.pending = null; // its PCM (if any) is ignored
      this.addLog(m.kind, text, "not played: you were transmitting", m.id);
      this.send({ type: "stop_tts" });
      return;
    }
    const speech = String(m.speech ?? text);
    const deviceSpeaks = audioS === 0 && m.device_tts === true && this.ttsMode() === "device" && speech.trim() !== "";
    this.addLog(
      m.kind,
      text,
      audioS > 0 ? `${audioS.toFixed(1)} s audio` : deviceSpeaks ? "device voice" : "text only",
      m.id,
    );
    this.pending =
      audioS > 0 ? { id: m.id, kind: m.kind, sampleRate: rate, expected: nBytes, chunks: [], received: 0 } : null;
    if (deviceSpeaks) this.speakDevice(m.id, m.kind, speech);
  }

  private makeUtterance(text: string): SpeechSynthesisUtterance {
    const u = new SpeechSynthesisUtterance(text);
    const uri = this.currentDeviceVoiceUri();
    const voice = uri ? speechSynthesis.getVoices().find((v) => v.voiceURI === uri) : undefined;
    if (voice) {
      u.voice = voice;
      u.lang = voice.lang;
    } else {
      u.lang = "en-GB";
    }
    u.rate = this.get().settings.deviceRate;
    return u;
  }

  /** Speak a message with the device voice; start/end reports feed the server's half-duplex gate. */
  private speakDevice(id: string, kind: SayKind, text: string): void {
    const now = performance.now();
    if (this.utterances.has(id)) {
      this.stopPlayback(id);
    } else if ([...this.utterances.values()].some((r) => !r.started && now - r.queuedAt > STALE_CLIP_MS)) {
      // Speech has been stuck (interruption, or WebKit's synthesiser hung): drop the backlog rather than play it
      // late. Web Speech cannot remove single utterances, so the whole queue goes.
      this.dropClips((c) => c.device, "dropped: speech was stuck");
    }
    if (this.ctx && this.ctx.state !== "running") void this.ctx.resume().catch(() => undefined);
    const rec: DeviceUtterance = { u: this.makeUtterance(text), kind, queuedAt: now, started: false };
    this.utterances.set(id, rec);
    rec.u.onstart = () => {
      if (this.utterances.get(id) !== rec) return;
      rec.started = true;
      this.set({ speakingId: id });
      this.send({ type: "playback", id, state: "started" });
      this.noteHeard(id, kind);
    };
    const done = () => {
      if (this.utterances.get(id) !== rec) return; // already stopped/replaced
      this.utterances.delete(id);
      if (rec.started) this.send({ type: "playback", id, state: "ended" });
      this.afterPlaybackChange();
    };
    rec.u.onend = done;
    rec.u.onerror = done;
    speechSynthesis.speak(rec.u); // the queue never overlaps two messages
    this.set({ speaking: true });
  }

  /** Latency note for replies: time from the driver's turn to the reply becoming audible. */
  private noteHeard(id: string, kind: SayKind): void {
    if (this.turnAt !== null && (kind === "answer" || kind === "control")) {
      const ms = performance.now() - this.turnAt;
      if (ms < TURN_LATENCY_WINDOW_MS) this.appendMeta(id, `heard +${(ms / 1000).toFixed(2)} s after ${this.turnBy}`);
      if (kind === "answer") this.turnAt = null; // the turn is complete
    }
  }

  private onBinary(data: ArrayBuffer): void {
    const p = this.pending;
    if (!p) return; // audio for a cancelled message still in flight
    p.chunks.push(data);
    p.received += data.byteLength;
  }

  private onSayEnd(id: string): void {
    const p = this.pending;
    if (!p || p.id !== id) return;
    this.pending = null;
    if (p.received !== p.expected) {
      this.addLog("error", `Audio for ${id}: got ${p.received} of ${p.expected} bytes`);
    }
    if (this.transmitting()) {
      // The driver keyed up (wheel) while the audio was arriving and the server did not cancel it.
      this.appendMeta(id, "not played: you were transmitting");
      this.send({ type: "stop_tts" });
      return;
    }
    const n = Math.min(p.received, p.expected) & ~1;
    if (n >= 2) this.play(p.id, p.kind, concatChunks(p.chunks, n), p.sampleRate);
  }

  private play(id: string, kind: SayKind, pcm: Uint8Array, sampleRate: number): void {
    const ctx = this.ctx;
    const out = this.playbackOut;
    if (!ctx || !out) return;
    const samples = pcm16ToFloat32(pcm);
    let buffer: AudioBuffer;
    try {
      buffer = ctx.createBuffer(1, samples.length, sampleRate);
    } catch (e) {
      this.addLog("error", `Cannot play ${sampleRate} Hz audio: ${errText(e)}`);
      return;
    }
    buffer.getChannelData(0).set(samples);
    this.stopPlayback(id); // duplicate id: replace
    if (ctx.state !== "running") {
      // Nothing is audible (iOS interruption, or audio waiting for a tap) and the server stops waiting for our
      // `ended` after its deadline, so messages would pile up and play back to back later. Keep only the newest.
      this.dropClips((c) => !c.device, "dropped: audio paused, newer message");
      void ctx.resume().catch(() => undefined);
    }
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(out);
    // Never overlap two messages: queue behind whatever is still audible.
    const startAt = Math.max(ctx.currentTime, this.playEndAt);
    this.playEndAt = startAt + buffer.duration;
    const pb: Playback = { id, kind, source: src, startAt, receivedAt: performance.now(), started: false, timer: null };
    this.playing.set(id, pb);
    this.set({ speaking: true });
    src.onended = () => {
      if (this.playing.get(id) === pb) this.finishPlayback(pb);
    };
    src.start(startAt);
    this.armStarted(pb);
  }

  /** Report `started` once the context clock reaches the scheduled start (not merely when scheduled). */
  private armStarted(pb: Playback): void {
    const ctx = this.ctx;
    if (!ctx || this.playing.get(pb.id) !== pb) return;
    const waitMs = (pb.startAt - ctx.currentTime) * 1000;
    if (waitMs <= 0 && ctx.state === "running") {
      pb.started = true;
      this.set({ speakingId: pb.id });
      this.send({ type: "playback", id: pb.id, state: "started" });
      // Only replies belong to the driver's turn; proactive messages (lap summary, coaching...) do not.
      this.noteHeard(pb.id, pb.kind);
      return;
    }
    pb.timer = setTimeout(
      () => {
        pb.timer = null;
        this.armStarted(pb);
      },
      ctx.state === "running" ? Math.max(5, waitMs) : 50,
    );
  }

  private finishPlayback(pb: Playback): void {
    if (pb.timer) clearTimeout(pb.timer);
    pb.timer = null;
    this.playing.delete(pb.id);
    if (pb.started) this.send({ type: "playback", id: pb.id, state: "ended" });
    this.afterPlaybackChange();
  }

  /** Stop one message (`id`) or everything (`null`). Started messages still get their `ended` report. */
  private stopPlayback(id: string | null): void {
    this.removeClips((c) => id === null || c.id === id, false);
  }

  /**
   * Drop messages that should no longer be heard, noting why in the log. `ended` is reported even for messages
   * that never started: the server may still be holding its half-duplex gate for one of them.
   */
  private dropClips(match: (c: ClipInfo) => boolean, why: string): void {
    for (const id of this.removeClips(match, true)) this.appendMeta(id, why);
  }

  /** Remove matching messages from both players; returns their ids. */
  private removeClips(match: (c: ClipInfo) => boolean, reportUnstarted: boolean): string[] {
    const removed: string[] = [];
    const speech = [...this.utterances].some(([id, r]) =>
      match({ id, started: r.started, at: r.queuedAt, device: true }),
    );
    if (speech) {
      // Web Speech cannot cancel a single queued utterance: cancel the queue and report every one.
      for (const [id, r] of this.utterances) {
        if (r.started || reportUnstarted) this.send({ type: "playback", id, state: "ended" });
        removed.push(id);
      }
      this.utterances.clear();
      speechSynthesis.cancel();
    }
    for (const pb of [...this.playing.values()]) {
      if (!match({ id: pb.id, started: pb.started, at: pb.receivedAt, device: false })) continue;
      this.playing.delete(pb.id);
      if (pb.timer) clearTimeout(pb.timer);
      pb.timer = null;
      pb.source.onended = null;
      try {
        pb.source.stop();
      } catch {
        /* not started yet on some engines */
      }
      pb.source.disconnect();
      if (pb.started || reportUnstarted) this.send({ type: "playback", id: pb.id, state: "ended" });
      removed.push(pb.id);
    }
    this.afterPlaybackChange();
    return removed;
  }

  private afterPlaybackChange(): void {
    let audible: string | null = null;
    for (const [uid, rec] of this.utterances) if (rec.started) audible = uid;
    let end = 0;
    for (const pb of this.playing.values()) {
      if (pb.started) audible = pb.id;
      const d = pb.source.buffer?.duration ?? 0;
      end = Math.max(end, pb.startAt + d);
    }
    this.playEndAt = end;
    this.set({ speaking: this.playing.size > 0 || this.utterances.size > 0, speakingId: audible });
  }

  // ------------------------------------------------------------------------------------------ environment

  private onGesture(): void {
    const ctx = this.ctx;
    if (ctx && ctx.state !== "running" && ctx.state !== "closed") void ctx.resume().catch(() => undefined);
    const { phase, wake } = this.get();
    if (phase !== "idle" && wake === "off") void this.requestWakeLock();
  }

  private requestWakeLock(): Promise<void> {
    if (!wakeLockSupported()) {
      this.set({ wake: "unsupported" });
      return Promise.resolve();
    }
    if ((this.wakeSentinel && !this.wakeSentinel.released) || document.visibilityState !== "visible") {
      return Promise.resolve();
    }
    this.wakeRequest ??= navigator.wakeLock
      .request("screen")
      .then((s) => {
        if (this.get().phase === "idle") {
          void s.release();
          return;
        }
        this.wakeSentinel = s;
        this.set({ wake: "on" });
        s.addEventListener("release", () => {
          if (this.wakeSentinel !== s) return;
          this.wakeSentinel = null;
          if (this.get().phase !== "idle") this.set({ wake: "off" });
        });
      })
      .catch(() => {
        this.set({ wake: "off" }); // e.g. Low Power Mode; retried on the next tap
      })
      .finally(() => {
        this.wakeRequest = null;
      });
    return this.wakeRequest;
  }

  private onContextState = (): void => {
    const ctx = this.ctx;
    if (!ctx) return;
    this.set({ audio: ctx.state });
    const now = performance.now();
    if (ctx.state === "running") {
      const pausedFor = this.pausedAt === null ? 0 : now - this.pausedAt;
      this.pausedAt = null;
      // A clip not heard within STALE_CLIP_MS (waiting since it arrived, or frozen mid-way) is dropped, not played
      // late; its text stays in the log.
      this.dropClips(
        (c) => !c.device && (c.started ? pausedFor : now - c.at) > STALE_CLIP_MS,
        "dropped: audio was paused",
      );
      return;
    }
    this.pausedAt ??= now;
    // After an interruption (call, Siri) WebKit may leave the context suspended; try without a gesture first.
    if (ctx.state !== "closed" && document.visibilityState === "visible") void ctx.resume().catch(() => undefined);
  };

  private onVisibility = (): void => {
    if (this.get().phase === "idle") return;
    if (document.visibilityState === "hidden") {
      this.hiddenAt = performance.now();
      // No hang time: the page may be frozen before the timer fires, leaving PTT down on the server.
      this.pttRelease(true);
      return;
    }
    const wasHidden = this.hiddenAt !== null;
    this.hiddenAt = null;
    void this.requestWakeLock();
    if (this.ctx && this.ctx.state !== "running") void this.ctx.resume().catch(() => undefined);
    this.reconnectNow();
    if (this.get().conn === "open") {
      // The socket may have died in the background: probe now and give it a short window instead of the
      // full silence timeout (timers were frozen while hidden, so lastRxAt is meaningless).
      this.lastRxAt = performance.now() - (SILENCE_TIMEOUT_MS - VISIBLE_PROBE_MS);
      this.sendPing();
    }
    if (!wasHidden) return;
    // iOS ends or silently mutes capture in the background, even when the track still says "live".
    if (this.micWasOpen()) void this.reacquireMic("back in foreground");
    else this.sendHello();
  };

  private onOnline = (): void => this.reconnectNow();

  private onTick = (): void => {
    const now = performance.now();
    this.ticks++;
    // Hidden tabs get throttled timers, so silence while hidden proves nothing; the visibility handler
    // re-probes the link on return.
    const hidden = document.visibilityState === "hidden";
    const { conn } = this.get();
    if (conn === "open") {
      if (!hidden && now - this.lastRxAt > SILENCE_TIMEOUT_MS) {
        this.dropSocket("no reply from the server");
      } else if (this.ticks % PING_EVERY_TICKS === 0) {
        this.sendPing();
      }
    } else if (conn === "connecting") {
      // Without this a black-holed handshake waits for the OS TCP timeout (about a minute).
      if (!hidden && this.attempt !== null && now - this.attempt.startedAt > CONNECT_TIMEOUT_MS) {
        this.dropSocket("no answer to connect", "Cannot reach the radio");
      }
    } else if (conn === "waiting") {
      this.set({ retryInS: Math.max(0, Math.ceil((this.reconnectAt - now) / 1000)) });
    }
    const stats = this.get().stats;
    const bufferedBytes = this.ws?.bufferedAmount ?? 0;
    if (
      stats.framesSent !== this.framesSent ||
      stats.framesDropped !== this.framesDropped ||
      stats.bufferedBytes !== bufferedBytes
    ) {
      this.set({ stats: { ...stats, framesSent: this.framesSent, framesDropped: this.framesDropped, bufferedBytes } });
    }
  };

  // ------------------------------------------------------------------------------------------ log + settings

  private startTurn(by: "release" | "ask"): void {
    this.turnAt = performance.now();
    this.turnBy = by;
  }

  private addLog(kind: LogKind, text: string, meta = "", id: string | null = null): void {
    const log = this.get().log;
    const last = log[log.length - 1];
    if (last && id === null && last.kind === kind && last.text === text && last.meta === meta) {
      this.set({ log: [...log.slice(0, -1), { ...last, count: last.count + 1, at: Date.now() }] });
      return;
    }
    const next = [...log, { seq: ++this.seq, at: Date.now(), kind, text, meta, id, count: 1 }];
    this.set({ log: next.length > LOG_MAX ? next.slice(next.length - LOG_MAX) : next });
  }

  private appendMeta(id: string, extra: string): void {
    const log = this.get().log;
    for (let i = log.length - 1; i >= 0; i--) {
      const e = log[i];
      if (e?.id === id) {
        const next = log.slice();
        next[i] = { ...e, meta: e.meta ? `${e.meta} · ${extra}` : extra };
        this.set({ log: next });
        return;
      }
    }
  }

  private updateSettings(patch: Partial<RadioSettings>): void {
    this.set({ settings: { ...this.get().settings, ...patch } });
  }

  private saveSettings(): void {
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(this.get().settings));
    } catch {
      /* storage unavailable (private mode) */
    }
  }
}

/** The app's one radio: module level, so it keeps running across routes and areas. */
export const radio = new RadioStore();

// Dev only: a hot update of this module would leave the old instance holding the mic and socket.
if (import.meta.hot) import.meta.hot.dispose(() => radio.stop());

// ------------------------------------------------------------------------------------------ derived (pure)

/** The driver is on air: PTT held on this device, or the hub reports PTT down (wheel or another screen). */
export function pttActive(s: Pick<RadioState, "pttHeld" | "server">): boolean {
  return s.pttHeld || (s.server?.ptt ?? false);
}

/** The engineer is talking: audio playing here, or the hub says a message is being spoken. */
export function engineerTalking(s: Pick<RadioState, "speaking" | "server">): boolean {
  return s.speaking || (s.server?.speaking ?? false);
}

/** Push-to-talk can be used now: radio started, link up, mic open. */
export function pttUsable(s: Pick<RadioState, "phase" | "conn" | "mic">): boolean {
  return s.phase !== "idle" && s.conn === "open" && (s.mic === "live" || s.mic === "muted");
}
