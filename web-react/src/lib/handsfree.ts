// Hands-free talking and the Bluetooth talk button (lane handsfree): the pure rules, no DOM and no React, so every
// rule is unit-tested in plain node (handsfree.test.ts). The radio store (lib/radio.ts) feeds them; the server side
// is voice/handsfree.py, the protocol docs/voice-protocol.md.
//
// Three ways to talk, all optional except the first:
//  * push-to-talk (screen button, Space on a Mac, the F1 25 wheel button): unchanged;
//  * a "Bluetooth button": a learned keyboard key (page turners and pedals that present as a keyboard) or a spare game
//    controller's button (Gamepad API). Hold it to talk, or tap it once and speak: the transmission then ends when
//    the driver goes quiet (the endpoint rule below), on the next press, or after 12 s. AirPods stem presses and
//    headphone play buttons never reach a web page on iPad Safari (native-app features), so they are not offered;
//  * hands-free: this device detects speech by its energy (EnergyVad) and tells the server where a stretch of speech
//    starts and ends (`vad` frames, sent after the audio frame they confirm). The server keeps a 0.5 s pre-roll,
//    transcribes, and answers only when the words start with the wake word ("Pitwall", or "Radio"). Off by default on
//    every device; while it is on, the server listens only while the car is stopped unless the seated driver's
//    profile allows hands-free while driving.
//
// Every number below is a heuristic tuned on synthetic audio (macOS `say` voices with engine-like and pink noise,
// docs/research/handsfree.md): no recorded voice from the rig exists yet.

// ------------------------------------------------------------------------------------------------- settings

export type WakeWord = "pitwall" | "radio";
export const WAKE_WORDS: readonly WakeWord[] = ["pitwall", "radio"];
/** The wake word as the driver says it and reads it. */
export const WAKE_WORD_LABEL: Record<WakeWord, string> = { pitwall: "Pitwall", radio: "Radio" };

export function isWakeWord(v: unknown): v is WakeWord {
  return v === "pitwall" || v === "radio";
}

/** A learned talk button: a keyboard key (KeyboardEvent.code) or a game controller's button (Gamepad API index). */
export type TalkButton = { kind: "key"; code: string } | { kind: "gamepad"; id: string; button: number };

/** A stored talk button, validated (anything else is no button). */
export function parseTalkButton(v: unknown): TalkButton | null {
  if (typeof v !== "object" || v === null) return null;
  const o = v as Record<string, unknown>;
  if (o.kind === "key" && typeof o.code === "string" && learnableCode(o.code)) return { kind: "key", code: o.code };
  if (
    o.kind === "gamepad" &&
    typeof o.id === "string" &&
    o.id.length > 0 &&
    o.id.length <= 200 &&
    typeof o.button === "number" &&
    Number.isInteger(o.button) &&
    o.button >= 0 &&
    o.button < 64
  ) {
    return { kind: "gamepad", id: o.id, button: o.button };
  }
  return null;
}

export function sameTalkButton(a: TalkButton | null, b: TalkButton | null): boolean {
  if (a === null || b === null) return a === b;
  if (a.kind === "key" && b.kind === "key") return a.code === b.code;
  if (a.kind === "gamepad" && b.kind === "gamepad") return a.id === b.id && a.button === b.button;
  return false;
}

// ------------------------------------------------------------------------------------------------- keys

const MODIFIER_CODES = new Set([
  "ShiftLeft",
  "ShiftRight",
  "ControlLeft",
  "ControlRight",
  "AltLeft",
  "AltRight",
  "MetaLeft",
  "MetaRight",
  "OSLeft",
  "OSRight",
  "CapsLock",
  "Fn",
  "FnLock",
  "NumLock",
  "ScrollLock",
]);
/** Keys that type text or move focus: never a talk button (Space stays the Mac's hold-to-talk key). */
const TYPING_CODES = new Set([
  "Space",
  "Tab",
  "Escape",
  "Backspace",
  "Minus",
  "Equal",
  "BracketLeft",
  "BracketRight",
  "Backslash",
  "Semicolon",
  "Quote",
  "Backquote",
  "Comma",
  "Period",
  "Slash",
  "IntlBackslash",
  "IntlRo",
  "IntlYen",
]);

/** A KeyboardEvent.code that may become the talk button: not a letter, digit, punctuation, Space, Tab, Escape or
 * modifier (those type text, move focus, cancel, or are held with other keys). Page turners send arrows, Page Up /
 * Down or Enter; pedals often F13+. */
export function learnableCode(code: string): boolean {
  if (!code || code === "Unidentified" || code.length > 40) return false;
  if (MODIFIER_CODES.has(code) || TYPING_CODES.has(code)) return false;
  if (/^Key[A-Z]$/.test(code) || /^Digit[0-9]$/.test(code)) return false;
  return /^[A-Za-z0-9]+$/.test(code);
}

/** The talk button a keydown may teach: its code, or null (a typing key, a modifier, or a shortcut with one). */
export function learnableKey(e: {
  code: string;
  metaKey?: boolean;
  ctrlKey?: boolean;
  altKey?: boolean;
  repeat?: boolean;
}): string | null {
  if (e.repeat || e.metaKey || e.ctrlKey || e.altKey) return null;
  return learnableCode(e.code) ? e.code : null;
}

const KEY_NAMES: Record<string, string> = {
  ArrowUp: "Up arrow",
  ArrowDown: "Down arrow",
  ArrowLeft: "Left arrow",
  ArrowRight: "Right arrow",
  PageUp: "Page Up",
  PageDown: "Page Down",
  Enter: "Return",
  NumpadEnter: "Keypad Enter",
  Home: "Home",
  End: "End",
  Delete: "Delete",
  Insert: "Insert",
  MediaPlayPause: "Play/Pause",
  MediaTrackNext: "Next track",
  MediaTrackPrevious: "Previous track",
  AudioVolumeUp: "Volume up",
  AudioVolumeDown: "Volume down",
  AudioVolumeMute: "Mute",
};

/** A KeyboardEvent.code as the driver reads it: "Right arrow", "Page Down", "F13", "Keypad 5". */
export function keyLabel(code: string): string {
  const named = KEY_NAMES[code];
  if (named) return named;
  const pad = /^Numpad(.+)$/.exec(code);
  if (pad?.[1]) return `Keypad ${pad[1].replace(/([a-z])([A-Z])/g, "$1 $2")}`;
  return code.replace(/([a-z])([A-Z0-9])/g, "$1 $2");
}

/** Button names of the W3C "standard" gamepad layout (Xbox / PlayStation); other layouts only have numbers. */
const STANDARD_BUTTONS = [
  "A / Cross",
  "B / Circle",
  "X / Square",
  "Y / Triangle",
  "LB / L1",
  "RB / R1",
  "LT / L2",
  "RT / R2",
  "View / Create",
  "Menu / Options",
  "Left stick press",
  "Right stick press",
  "D-pad up",
  "D-pad down",
  "D-pad left",
  "D-pad right",
  "Home / PS",
];

/** A controller's name without the vendor/product codes some browsers add ("Xbox Wireless Controller"). */
export function padName(id: string): string {
  const cleaned = id
    .replace(/\(.*?(vendor|product|STANDARD GAMEPAD).*?\)/gi, "")
    .replace(/^[0-9a-f]{4}-[0-9a-f]{4}-/i, "")
    .replace(/\s+/g, " ")
    .trim();
  const name = cleaned || "Game controller";
  return name.length > 40 ? `${name.slice(0, 39)}…` : name;
}

/** "Right arrow" / "Xbox Wireless Controller · button 0 (A / Cross on most controllers)". */
export function talkButtonLabel(b: TalkButton): string {
  if (b.kind === "key") return keyLabel(b.code);
  const std = STANDARD_BUTTONS[b.button];
  return `${padName(b.id)} · button ${b.button}${std ? ` (${std} on most controllers)` : ""}`;
}

// ------------------------------------------------------------------------------------------------- gamepads

export interface PadButtonLike {
  pressed: boolean;
  value?: number;
}

export interface PadLike {
  id: string;
  index: number;
  connected?: boolean;
  buttons: readonly PadButtonLike[];
}

/** navigator.getGamepads() (null slots for empty ports). */
export type GetPads = () => readonly (PadLike | null | undefined)[];

/** A button is down when the browser says pressed, or an analogue trigger is past half way. */
export function padButtonDown(b: PadButtonLike | undefined): boolean {
  return !!b && (b.pressed || (b.value ?? 0) > 0.5);
}

export interface PadEdge {
  id: string;
  index: number;
  button: number;
  down: boolean;
}

/**
 * Turns successive navigator.getGamepads() polls into button edges (up -> down, down -> up). A controller seen for the
 * first time reports no edges for buttons already held (Safari only exposes a controller after a button press: that
 * press is not a talk-button press).
 */
export class PadWatcher {
  private prev = new Map<string, boolean[]>();

  poll(pads: readonly (PadLike | null | undefined)[]): PadEdge[] {
    const edges: PadEdge[] = [];
    const seen = new Set<string>();
    for (const p of pads) {
      if (!p || p.connected === false) continue;
      const key = `${p.index}:${p.id}`;
      seen.add(key);
      const now = p.buttons.map((b) => padButtonDown(b));
      const before = this.prev.get(key);
      if (before) {
        for (let i = 0; i < now.length; i++) {
          if (now[i] !== (before[i] ?? false)) edges.push({ id: p.id, index: p.index, button: i, down: now[i] === true });
        }
      }
      this.prev.set(key, now);
    }
    for (const [key, before] of this.prev) {
      if (seen.has(key)) continue;
      // disconnected while a button was down: report the release so a held talk button never stays keyed
      const [index, ...rest] = key.split(":");
      before.forEach((d, i) => {
        if (d) edges.push({ id: rest.join(":"), index: Number(index), button: i, down: false });
      });
      this.prev.delete(key);
    }
    return edges;
  }

  reset(): void {
    this.prev.clear();
  }
}

/** Edges of the learned button (any controller with the learned id). */
export function talkPadEdges(edges: readonly PadEdge[], b: TalkButton | null): PadEdge[] {
  if (b === null || b.kind !== "gamepad") return [];
  return edges.filter((e) => e.id === b.id && e.button === b.button);
}

/** How often controllers are polled while the radio is live on a Drive page (and while learning a button). */
export const PAD_POLL_MS = 33;

// ------------------------------------------------------------------------------------------------- hold or tap

/** A release this soon after the press is a tap: the transmission stays on until the driver goes quiet. */
export const TAP_MAX_MS = 300;
/** A press this soon after a release is contact bounce or a duplicate event from the device: ignored. */
export const BOUNCE_MS = 80;
/** A tapped transmission ends after this long whatever happens. */
export const TAP_LIMIT_MS = 12_000;

export type TalkState = "idle" | "held" | "tap";
export type TalkAction = "press" | "release" | null;

/**
 * The talk button's hold-or-tap rule. press(): key the mic, or end a tapped transmission. release(): a hold ends
 * the transmission; a tap (released within TAP_MAX_MS) leaves it on (state "tap"): the radio store then ends it on
 * the endpoint rule (Endpointer), the next press, or TAP_LIMIT_MS. Keyboard auto-repeat arrives as repeated keydowns
 * (ignored by the caller) and one keyup, so holding a key is a hold.
 */
export class TalkButtonMachine {
  state: TalkState = "idle";
  private pressAt = 0;
  private releaseAt = -Infinity;

  press(nowMs: number): TalkAction {
    if (nowMs - this.releaseAt < BOUNCE_MS) return null;
    if (this.state === "held") return null;
    if (this.state === "tap") {
      this.state = "idle";
      this.releaseAt = nowMs; // the release of a tap transmission: its own bounce is ignored too
      return "release";
    }
    this.state = "held";
    this.pressAt = nowMs;
    return "press";
  }

  release(nowMs: number): TalkAction {
    if (this.state !== "held") return null;
    this.releaseAt = nowMs;
    if (nowMs - this.pressAt >= TAP_MAX_MS) {
      this.state = "idle";
      return "release";
    }
    this.state = "tap";
    return null;
  }

  /** When the press that keyed the current transmission happened (for the 12 s limit). */
  get pressedAt(): number {
    return this.pressAt;
  }

  /** The transmission ended elsewhere (endpoint, limit, the screen button, the link, the page hidden). */
  reset(): void {
    this.state = "idle";
  }
}

// ------------------------------------------------------------------------------------------------- energy VAD

/** One worklet frame: 512 samples at 16 kHz. */
export const VAD_FRAME_MS = 32;
/** Calibration after the mic opens or the VAD is reset: 1.0 s; the noise floor is their median. */
export const VAD_CALIBRATION_FRAMES = 31;
/** A frame is voiced at the floor + 12 dB, and never below -50 dBFS. The floor is the noise estimate clamped to
 * [-90, -35] dBFS, so speech at a normal level is still heard over noise up to about -35 dBFS. */
export const VAD_MARGIN_DB = 12;
export const VAD_MIN_THRESHOLD_DB = -50;
export const VAD_FLOOR_MIN_DB = -90;
export const VAD_FLOOR_MAX_DB = -35;
/**
 * Loud noise (lane handsfree, measured on the synthetic traces; an addition to the design note, whose floor clamp
 * alone lets steady noise above about -25 dBFS trigger 8 s captures back to back): a voiced frame must also be 10 dB
 * above the noise estimate itself (not clamped), and above -26 dBFS of noise the listener refuses altogether ("too
 * noisy"): there speech cannot be told from noise by its energy. Only matters in noise louder than about -33 dBFS.
 * Synthetic result: 0 dB SNR gives no segment, 10 dB SNR still hears every clip.
 */
export const VAD_NOISE_MARGIN_DB = 10;
export const VAD_REFUSE_ABOVE_DB = -26;
/** The noise estimate itself stays within [-90, -10] dBFS. */
const NOISE_MAX_DB = -10;
/** Floor tracking per frame: fast down (the room got quieter), slow up (noise rose; speech is not noise). */
export const VAD_FLOOR_DOWN = 0.2;
export const VAD_FLOOR_UP = 0.005;
/** Speech starts at 4 voiced frames among the last 5 (about 130-160 ms). */
export const VAD_START_WINDOW = 5;
export const VAD_START_VOICED = 4;
/** ... and ends after 22 unvoiced frames in a row (about 0.7 s). */
export const VAD_END_FRAMES = 22;
/** A segment is cut after 250 frames (8.0 s); the floor then becomes its 10th percentile (steady noise). */
export const VAD_MAX_FRAMES = 250;
/** No segment while the engineer talks here and for this long after (the AirPod's echo tail). */
export const PLAYBACK_TAIL_MS = 300;
/** Endpoint mode (a tapped talk button): wait 4.0 s for speech, end after 0.8 s quiet. */
export const ENDPOINT_WAIT_FRAMES = 125;
export const ENDPOINT_END_FRAMES = 25;
export const ENDPOINT_MAX_FRAMES = Math.round(TAP_LIMIT_MS / VAD_FRAME_MS);

export type VadEndReason = "silence" | "max";
export type VadEvent =
  | { type: "start" }
  | { type: "end"; reason: VadEndReason; frames: number }
  | { type: "abort"; reason: "suppressed"; frames: number };
export type VadPhase = "calibrating" | "idle" | "speech" | "noisy";

/** Linear RMS (full scale 1) -> dBFS, floored at -120 dBFS (silence, NaN). */
export function rmsToDb(rms: number): number {
  return 20 * Math.log10(Number.isFinite(rms) && rms > 1e-6 ? rms : 1e-6);
}

function clampFloor(db: number): number {
  return Math.min(VAD_FLOOR_MAX_DB, Math.max(VAD_FLOOR_MIN_DB, db));
}

function clampNoise(db: number): number {
  return Math.min(NOISE_MAX_DB, Math.max(VAD_FLOOR_MIN_DB, db));
}

export function median(xs: readonly number[]): number {
  if (xs.length === 0) return NaN;
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m]! : (s[m - 1]! + s[m]!) / 2;
}

/** Percentile with linear interpolation between ranks (numpy's default), p in 0..100. */
export function percentile(xs: readonly number[], p: number): number {
  if (xs.length === 0) return NaN;
  const s = [...xs].sort((a, b) => a - b);
  const r = (Math.min(100, Math.max(0, p)) / 100) * (s.length - 1);
  const lo = Math.floor(r);
  const hi = Math.min(s.length - 1, lo + 1);
  return s[lo]! + (s[hi]! - s[lo]!) * (r - lo);
}

/** The voiced threshold for a noise estimate (dBFS): floor (clamped) + 12 dB, at least -50, at least noise + 10 dB. */
export function thresholdFor(noiseDb: number): number {
  return Math.max(clampFloor(noiseDb) + VAD_MARGIN_DB, VAD_MIN_THRESHOLD_DB, noiseDb + VAD_NOISE_MARGIN_DB);
}

/**
 * Energy voice-activity detector, one call per worklet frame (rms over 32 ms). Calibrates for 1 s, then tracks the
 * noise floor and reports where speech starts and ends. `suppressed` frames (the engineer talking, push-to-talk, a
 * silent or closed mic, the page hidden, the link down...) freeze the floor, do not count towards calibration, and
 * abort a segment in progress.
 */
export class EnergyVad {
  private calib: number[] = [];
  /** The noise estimate (dBFS, not clamped to the floor's range); null while calibrating. */
  private noise: number | null = null;
  private hist: boolean[] = [];
  private histDb: number[] = [];
  private speech = false;
  private segDb: number[] = [];
  private silent = 0;
  /** Level of the last frame (dBFS). */
  lastDb = -120;

  get phase(): VadPhase {
    if (this.noise === null) return "calibrating";
    if (this.speech) return "speech";
    return this.noise > VAD_REFUSE_ABOVE_DB ? "noisy" : "idle";
  }

  /** The tracked noise level (dBFS); null while calibrating. */
  get floorDb(): number | null {
    return this.noise;
  }

  /** The voiced threshold (dBFS); null while calibrating. */
  get thresholdDb(): number | null {
    return this.noise === null ? null : thresholdFor(this.noise);
  }

  /** A threshold even while calibrating (endpoint mode): the frames so far, else the absolute minimum. */
  effectiveThreshold(): number {
    if (this.noise !== null) return thresholdFor(this.noise);
    return this.calib.length ? thresholdFor(clampNoise(median(this.calib))) : VAD_MIN_THRESHOLD_DB;
  }

  /** Start over: calibrate again (the mic reopened, or hands-free was just turned on). */
  reset(): void {
    this.calib = [];
    this.noise = null;
    this.clearSegment();
  }

  private clearSegment(): void {
    this.hist = [];
    this.histDb = [];
    this.speech = false;
    this.segDb = [];
    this.silent = 0;
  }

  push(rms: number, suppressed = false): VadEvent | null {
    const db = rmsToDb(rms);
    this.lastDb = db;
    if (suppressed) {
      const frames = this.segDb.length;
      const was = this.speech;
      this.clearSegment();
      return was ? { type: "abort", reason: "suppressed", frames } : null;
    }
    if (this.noise === null) {
      this.calib.push(db);
      if (this.calib.length >= VAD_CALIBRATION_FRAMES) {
        this.noise = clampNoise(median(this.calib));
        this.calib = [];
      }
      return null;
    }
    const voiced = db >= thresholdFor(this.noise) && this.noise <= VAD_REFUSE_ABOVE_DB;
    if (!this.speech) {
      this.hist.push(voiced);
      this.histDb.push(db);
      if (this.hist.length > VAD_START_WINDOW) {
        this.hist.shift();
        this.histDb.shift();
      }
      if (this.hist.filter(Boolean).length >= VAD_START_VOICED) {
        this.speech = true;
        this.segDb = [...this.histDb]; // the segment starts with the window that confirmed it
        this.silent = 0;
        return { type: "start" };
      }
      const rate = db < this.noise ? VAD_FLOOR_DOWN : VAD_FLOOR_UP;
      this.noise = clampNoise(this.noise + rate * (db - this.noise));
      return null;
    }
    this.segDb.push(db);
    this.silent = voiced ? 0 : this.silent + 1;
    this.noise = clampNoise(this.noise + VAD_FLOOR_UP * Math.max(0, db - this.noise));
    const frames = this.segDb.length;
    if (frames > VAD_MAX_FRAMES) {
      // continuous sound for 8 s is noise: it becomes the floor
      this.noise = clampNoise(percentile(this.segDb, 10));
      this.clearSegment();
      return { type: "end", reason: "max", frames };
    }
    if (this.silent >= VAD_END_FRAMES) {
      this.clearSegment();
      return { type: "end", reason: "silence", frames };
    }
    return null;
  }
}

export type EndpointReason = "no_speech" | "silence" | "max";

/**
 * Endpoint mode for a tapped talk button: the transmission is on; release it when no speech started within 4.0 s,
 * when speech ended (0.8 s quiet), or after 12 s. Uses the VAD's threshold (its floor is frozen while on air).
 */
export class Endpointer {
  private frames = 0;
  private hist: boolean[] = [];
  private started = false;
  private silent = 0;

  get speechStarted(): boolean {
    return this.started;
  }

  push(db: number, thresholdDb: number): EndpointReason | null {
    this.frames++;
    const voiced = db >= thresholdDb;
    if (!this.started) {
      this.hist.push(voiced);
      if (this.hist.length > VAD_START_WINDOW) this.hist.shift();
      if (this.hist.filter(Boolean).length >= VAD_START_VOICED) {
        this.started = true;
        this.silent = 0;
      } else if (this.frames >= ENDPOINT_WAIT_FRAMES) {
        return "no_speech";
      }
    } else {
      this.silent = voiced ? 0 : this.silent + 1;
      if (this.silent >= ENDPOINT_END_FRAMES) return "silence";
    }
    return this.frames >= ENDPOINT_MAX_FRAMES ? "max" : null;
  }
}

// ------------------------------------------------------------------------------------------------- server state

/** Rejection and ignore reasons the server reports (voice/handsfree.py; docs/voice-protocol.md). */
export type HandsFreeReason =
  | "not_armed"
  | "unavailable"
  | "ptt"
  | "other_device"
  | "speaking"
  | "busy"
  | "paused_moving"
  | "rate_limited"
  | "too_short"
  | "too_long"
  | "no_speech"
  | "stt_error"
  | "echo"
  | "not_addressed"
  | "answer_limit";

/** The `handsfree` block of the hub's `state` frame (and of GET /api/voice/status). */
export interface HandsFreeServerState {
  /** The Mac can do hands-free now (speech recognition up, not turned off by PITWALL_VOICE_HANDSFREE=false). */
  available: boolean;
  /** Why not, when unavailable (a code or a sentence; shown in the chip's detail). */
  reason: string | null;
  /** Devices that have hands-free on. */
  armed: number;
  /** "stationary": listens only while the car is stopped; "driving": the seated driver allows it on track. */
  scope: "stationary" | "driving";
  /** Listening now (available, armed, and the scope allows it). */
  active: boolean;
  /** "moving": armed, but the car is moving and the scope is stationary. */
  paused: "moving" | null;
  /** A stretch of speech is being captured now (on any device). */
  capturing: boolean;
  /** The engineer said "Go ahead": the next stretch of speech needs no wake word. */
  follow_up: boolean;
  wake_words: string[];
  counts: { heard: number; addressed: number; ignored: number; rejected: number };
}

function count(v: unknown): number {
  return typeof v === "number" && Number.isFinite(v) && v >= 0 ? Math.floor(v) : 0;
}

/** The server's hands-free block, validated field by field; null when absent (a server without hands-free). */
export function parseHandsFreeState(v: unknown): HandsFreeServerState | null {
  if (typeof v !== "object" || v === null || Array.isArray(v)) return null;
  const o = v as Record<string, unknown>;
  const c = (typeof o.counts === "object" && o.counts !== null ? o.counts : {}) as Record<string, unknown>;
  return {
    available: o.available === true,
    reason: typeof o.reason === "string" && o.reason ? o.reason : null,
    armed: count(o.armed),
    scope: o.scope === "driving" ? "driving" : "stationary",
    active: o.active === true,
    paused: o.paused === "moving" ? "moving" : null,
    capturing: o.capturing === true,
    follow_up: o.follow_up === true,
    wake_words: Array.isArray(o.wake_words) ? o.wake_words.filter((w): w is string => typeof w === "string") : [],
    counts: { heard: count(c.heard), addressed: count(c.addressed), ignored: count(c.ignored), rejected: count(c.rejected) },
  };
}

export type HandsFreeEventKind = "accepted" | "rejected" | "ignored" | "addressed" | "follow_up";

/** A per-device `handsfree` event frame (never carries what was said). */
export interface HandsFreeEvent {
  event: HandsFreeEventKind;
  seq: number | null;
  reason: string | null;
  audioS: number | null;
  wake: string | null;
}

export function parseHandsFreeEvent(v: Record<string, unknown>): HandsFreeEvent | null {
  const e = v.event;
  if (e !== "accepted" && e !== "rejected" && e !== "ignored" && e !== "addressed" && e !== "follow_up") return null;
  return {
    event: e,
    seq: typeof v.seq === "number" && Number.isFinite(v.seq) ? v.seq : null,
    reason: typeof v.reason === "string" && v.reason ? v.reason : null,
    audioS: typeof v.audio_s === "number" && Number.isFinite(v.audio_s) ? v.audio_s : null,
    wake: typeof v.wake === "string" && v.wake ? v.wake : null,
  };
}

// ------------------------------------------------------------------------------------------------- this device

/** What this device's listener is doing (RadioState.handsFree.vad). "noisy": too much noise to tell speech apart. */
export type LocalVad = "off" | "calibrating" | "listening" | "speech" | "suppressed" | "noisy";

/** This device's side of hands-free and the talk button, for the chips and diagnostics. */
export interface HandsFreeLocal {
  vad: LocalVad;
  /** Noise floor and voiced threshold (dBFS, rounded); null while calibrating or before the mic opened. */
  floorDb: number | null;
  thresholdDb: number | null;
  /** The talk button's transmission: "held" (hold to talk) or "tap" (ends when the driver goes quiet). */
  button: "off" | "held" | "tap";
  /** The server's per-device events since the radio went live. */
  events: { accepted: number; rejected: number; ignored: number; addressed: number; tooLong: number };
  /** The newest event (reason only: what was said is never sent for ignored speech). */
  last: { event: HandsFreeEventKind; reason: string | null; at: number } | null;
}

export const HANDS_FREE_IDLE: HandsFreeLocal = Object.freeze({
  vad: "off",
  floorDb: null,
  thresholdDb: null,
  button: "off",
  events: Object.freeze({ accepted: 0, rejected: 0, ignored: 0, addressed: 0, tooLong: 0 }),
  last: null,
}) as HandsFreeLocal;

/** Count one server event into the device's tallies (a new object). */
export function tallyEvent(h: HandsFreeLocal, ev: HandsFreeEvent, atMs: number): HandsFreeLocal {
  const events = { ...h.events };
  if (ev.event === "accepted" || ev.event === "rejected" || ev.event === "ignored" || ev.event === "addressed") {
    events[ev.event] += 1;
  }
  if (ev.reason === "too_long") events.tooLong += 1;
  return { ...h, events, last: { event: ev.event, reason: ev.reason, at: atMs } };
}

// ------------------------------------------------------------------------------------------------- learning

/**
 * Settings › Set up button: the first learnable key or controller button pressed wins. Keys that type text or move
 * focus are refused (`refused` names them, so the page can say why); controllers already holding a button when first
 * seen do not count (PadWatcher).
 */
export class ButtonLearner {
  private pads = new PadWatcher();
  learned: TalkButton | null = null;
  /** The last key refused (it types text, or a modifier was held), for "That key types text". */
  refused: string | null = null;

  key(e: { code: string; metaKey?: boolean; ctrlKey?: boolean; altKey?: boolean; repeat?: boolean }): TalkButton | null {
    if (this.learned) return null;
    const code = learnableKey(e);
    if (code === null) {
      if (!e.repeat && e.code !== "Escape" && e.code !== "Tab" && !MODIFIER_CODES.has(e.code)) this.refused = e.code;
      return null;
    }
    this.refused = null;
    this.learned = { kind: "key", code };
    return this.learned;
  }

  poll(pads: readonly (PadLike | null | undefined)[]): TalkButton | null {
    const edges = this.pads.poll(pads);
    if (this.learned) return null;
    const down = edges.find((e) => e.down);
    if (!down) return null;
    this.refused = null;
    this.learned = { kind: "gamepad", id: down.id, button: down.button };
    return this.learned;
  }

  /** Try again: forget what was learned (controllers keep their state, so a held button does not count). */
  restart(): void {
    this.learned = null;
    this.refused = null;
  }
}
