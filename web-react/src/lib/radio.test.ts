// Radio store tests: the /ws/radio protocol (docs/voice-protocol.md) and the behaviour of the Svelte reference
// (web/src/lib/radio.svelte.ts), driven through fakes of WebSocket, AudioContext, AudioWorkletNode, getUserMedia,
// the wake lock, Web Speech and storage. Plain node, fake timers (performance.now() is faked too).

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { memoryStorage } from "../test/fakes";
import { resetTokenCacheForTests } from "./auth";
import {
  ACCESS_DENIED,
  concatChunks,
  engineerTalking,
  levelFromRms,
  listDeviceVoices,
  loadSettings,
  LOG_MAX,
  pcm16ToFloat32,
  PROXY_HINT,
  pttActive,
  pttUsable,
  radio as singleton,
  RadioStore,
  SETTINGS_KEY,
  VOICE_DISABLED,
  VOICE_TEST_TEXT,
  type RadioState,
} from "./radio";

// ------------------------------------------------------------------------------------------------ fakes

type Handler = (ev?: unknown) => void;

class Emitter {
  private readonly handlers = new Map<string, Set<Handler>>();
  addEventListener = (type: string, h: Handler): void => {
    let set = this.handlers.get(type);
    if (!set) this.handlers.set(type, (set = new Set()));
    set.add(h);
  };
  removeEventListener = (type: string, h: Handler): void => {
    this.handlers.get(type)?.delete(h);
  };
  fire(type: string, ev?: unknown): void {
    for (const h of [...(this.handlers.get(type) ?? [])]) h(ev);
  }
  count(type: string): number {
    return this.handlers.get(type)?.size ?? 0;
  }
}

class FakeSocket {
  static instances: FakeSocket[] = [];
  readyState = 0;
  binaryType = "blob";
  bufferedAmount = 0;
  readonly sent: (string | ArrayBuffer)[] = [];
  closedWith: { code?: number; reason?: string } | null = null;
  onopen: Handler | null = null;
  onclose: ((ev: { code: number }) => void) | null = null;
  onmessage: ((ev: { data: string | ArrayBuffer }) => void) | null = null;
  onerror: Handler | null = null;

  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
  }

  static last(): FakeSocket {
    const ws = FakeSocket.instances.at(-1);
    if (!ws) throw new Error("no socket");
    return ws;
  }

  send(data: string | ArrayBuffer): void {
    if (this.readyState !== 1) throw new Error("send on a socket that is not open");
    this.sent.push(data);
  }

  close(code?: number, reason?: string): void {
    this.readyState = 3;
    this.closedWith = { code, reason };
  }

  // --- the server side
  open(): void {
    this.readyState = 1;
    this.onopen?.({});
  }

  text(msg: object): void {
    this.onmessage?.({ data: JSON.stringify(msg) });
  }

  binary(buf: ArrayBuffer): void {
    this.onmessage?.({ data: buf });
  }

  serverClose(code = 1006): void {
    this.readyState = 3;
    this.onclose?.({ code });
  }

  /** JSON frames the client sent, oldest first. */
  json(): Record<string, unknown>[] {
    return this.sent.filter((d): d is string => typeof d === "string").map((d) => JSON.parse(d) as Record<string, unknown>);
  }

  types(): string[] {
    return this.json().map((m) => String(m.type));
  }

  binaries(): ArrayBuffer[] {
    return this.sent.filter((d): d is ArrayBuffer => typeof d !== "string");
  }

  clear(): void {
    this.sent.length = 0;
  }
}

class FakeAudioBuffer {
  readonly duration: number;
  readonly data: Float32Array;
  constructor(
    length: number,
    readonly sampleRate: number,
  ) {
    this.duration = length / sampleRate;
    this.data = new Float32Array(length);
  }
  getChannelData(): Float32Array {
    return this.data;
  }
}

class FakeBufferSource {
  buffer: FakeAudioBuffer | null = null;
  onended: (() => void) | null = null;
  startAt: number | null = null;
  stopped = false;
  connect = vi.fn();
  disconnect = vi.fn();
  start(at = 0): void {
    this.startAt = at;
  }
  stop(): void {
    this.stopped = true;
  }
  /** The clip played to its end. */
  end(): void {
    this.onended?.();
  }
}

class FakeAudioContext {
  static instances: FakeAudioContext[] = [];
  static failNext = false;
  /** The next AudioContext's worklet module fails to load with this error. */
  static addModuleError: unknown = null;
  state = "running";
  sampleRate = 48000;
  currentTime = 0;
  destination = {};
  resumeWorks = true;
  onstatechange: (() => void) | null = null;
  readonly sources: FakeBufferSource[] = [];
  readonly audioWorklet = { addModule: vi.fn(async (_url: string) => undefined) };
  readonly resume = vi.fn(async () => {
    if (this.resumeWorks && this.state !== "running" && this.state !== "closed") this.setState("running");
  });
  readonly close = vi.fn(async () => {
    this.state = "closed";
  });

  constructor(readonly options?: unknown) {
    if (FakeAudioContext.failNext) {
      FakeAudioContext.failNext = false;
      throw new Error("no audio hardware");
    }
    FakeAudioContext.instances.push(this);
    const err = FakeAudioContext.addModuleError;
    if (err) {
      FakeAudioContext.addModuleError = null;
      this.audioWorklet.addModule.mockRejectedValueOnce(err);
    }
  }

  static last(): FakeAudioContext {
    const c = FakeAudioContext.instances.at(-1);
    if (!c) throw new Error("no AudioContext");
    return c;
  }

  setState(s: string): void {
    this.state = s;
    this.onstatechange?.();
  }

  createBufferSource(): FakeBufferSource {
    const s = new FakeBufferSource();
    this.sources.push(s);
    return s;
  }

  createBuffer(_channels: number, length: number, rate: number): FakeAudioBuffer {
    if (rate < 3000) throw new Error(`unsupported rate ${rate}`);
    return new FakeAudioBuffer(length, rate);
  }

  createGain() {
    return { connect: vi.fn(), disconnect: vi.fn() };
  }

  createMediaStreamSource(_stream: unknown) {
    return { connect: vi.fn(), disconnect: vi.fn() };
  }

  /** Clips the store scheduled for messages (the first source is the silent unlock buffer). */
  clips(): FakeBufferSource[] {
    return this.sources.filter((s) => s.buffer !== null && s.buffer.data.length > 1);
  }
}

class FakeWorkletNode {
  static instances: FakeWorkletNode[] = [];
  readonly port = {
    postMessage: vi.fn(),
    onmessage: null as ((ev: { data: unknown }) => void) | null,
  };
  connect = vi.fn();
  disconnect = vi.fn();
  constructor(
    readonly ctx: unknown,
    readonly name: string,
    readonly options: unknown,
  ) {
    FakeWorkletNode.instances.push(this);
  }
  static last(): FakeWorkletNode {
    const n = FakeWorkletNode.instances.at(-1);
    if (!n) throw new Error("no worklet node");
    return n;
  }
  /** A message from the worklet to the page. */
  post(data: unknown): void {
    this.port.onmessage?.({ data });
  }
  frame(rms = 0.05): void {
    this.post({ type: "frame", pcm: new ArrayBuffer(1024), rms, peak: rms * 2 });
  }
}

class FakeTrack extends Emitter {
  muted = false;
  stopped = false;
  stop(): void {
    this.stopped = true;
  }
}

function fakeStream(track = new FakeTrack()) {
  return { track, getTracks: () => [track], getAudioTracks: () => [track] };
}

class FakeSentinel extends Emitter {
  released = false;
  readonly release = vi.fn(async () => {
    this.released = true;
    this.fire("release");
  });
}

class FakeUtterance {
  static instances: FakeUtterance[] = [];
  voice: unknown = null;
  lang = "";
  rate = 1;
  volume = 1;
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(readonly text: string) {
    FakeUtterance.instances.push(this);
  }
}

interface Env {
  win: Emitter & { isSecureContext: boolean; location: Record<string, string>; speechSynthesis?: unknown };
  doc: Emitter & { visibilityState: string };
  nav: {
    userAgent: string;
    maxTouchPoints: number;
    mediaDevices: { getUserMedia: ReturnType<typeof vi.fn> };
    wakeLock?: { request: ReturnType<typeof vi.fn> };
  };
  local: Storage;
  session: Storage;
  fetch: ReturnType<typeof vi.fn>;
  streams: ReturnType<typeof fakeStream>[];
  sentinels: FakeSentinel[];
  speech: { speak: ReturnType<typeof vi.fn>; cancel: ReturnType<typeof vi.fn>; getVoices: () => unknown[] } & Emitter;
}

interface EnvOptions {
  url?: string;
  secure?: boolean;
  speech?: boolean;
  voices?: { name: string; lang: string; voiceURI: string; localService?: boolean; default?: boolean }[];
  settings?: object;
}

function setup(o: EnvOptions = {}): Env {
  const u = new URL(o.url ?? "https://mac.tail.ts.net:8443/next/#/drive/radio");
  const win = Object.assign(new Emitter(), {
    isSecureContext: o.secure ?? true,
    location: { protocol: u.protocol, host: u.host, pathname: u.pathname, search: u.search, hash: u.hash },
  }) as Env["win"];
  const doc = Object.assign(new Emitter(), { visibilityState: "visible" });
  const streams: Env["streams"] = [];
  const sentinels: FakeSentinel[] = [];
  const nav: Env["nav"] = {
    userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15",
    maxTouchPoints: 5, // an iPad that reports a desktop UA
    mediaDevices: {
      getUserMedia: vi.fn(async () => {
        const s = fakeStream();
        streams.push(s);
        return s;
      }),
    },
    wakeLock: {
      request: vi.fn(async () => {
        const s = new FakeSentinel();
        sentinels.push(s);
        return s;
      }),
    },
  };
  const voices = (o.voices ?? []).map((v) => ({ localService: true, default: false, ...v }));
  const speech = Object.assign(new Emitter(), {
    speak: vi.fn(),
    cancel: vi.fn(),
    getVoices: () => voices,
  });
  const local = memoryStorage();
  if (o.settings) local.setItem(SETTINGS_KEY, JSON.stringify(o.settings));
  const session = memoryStorage();
  // A minimal Response: undici's body reading needs more than a few microtask turns under fake timers.
  const fetchFn = vi.fn(async (_url: string, _init?: RequestInit) => httpReply(200, { enabled: true }));
  if (o.speech) {
    win.speechSynthesis = speech;
    vi.stubGlobal("speechSynthesis", speech);
    vi.stubGlobal("SpeechSynthesisUtterance", FakeUtterance);
  }
  vi.stubGlobal("window", win);
  vi.stubGlobal("document", doc);
  vi.stubGlobal("navigator", nav);
  vi.stubGlobal("localStorage", local);
  vi.stubGlobal("sessionStorage", session);
  vi.stubGlobal("fetch", fetchFn);
  vi.stubGlobal("WebSocket", FakeSocket);
  vi.stubGlobal("AudioContext", FakeAudioContext);
  vi.stubGlobal("AudioWorkletNode", FakeWorkletNode);
  return { win, doc, nav, local, session, fetch: fetchFn, streams, sentinels, speech };
}

function httpReply(status: number, body: unknown = {}): Response {
  return { status, ok: status >= 200 && status < 300, json: async () => body } as Response;
}

/** Let promise chains (getUserMedia + worklet -> mic live -> phase live) run. Timers stay frozen. */
async function settle(): Promise<void> {
  for (let i = 0; i < 25; i++) await Promise.resolve();
}

const STATE = {
  type: "state",
  ptt: false,
  listening: false,
  speaking: false,
  intensity: "normal",
  voice_enabled: true,
  stt: "parakeet",
  tts: "kokoro",
  tts_voice: "bm_george",
  tts_voices: ["bm_fable", "bm_george", "bf_emma", "bf_isabella"],
  tts_active: "kokoro",
  tts_ready: true,
  tts_neural: true,
  tts_status: "ready",
  telemetry: "live",
  ptt_source: null,
  cue_mode: "focus",
};

/** int16 PCM of `n` samples (a ramp, so the conversion is checkable). */
function pcm(n: number): ArrayBuffer {
  const b = new ArrayBuffer(n * 2);
  const v = new DataView(b);
  for (let i = 0; i < n; i++) v.setInt16(i * 2, (i % 100) * 100, true);
  return b;
}

/** Radio live, socket open, first `state` received. */
async function goLive(o: EnvOptions = {}) {
  const env = setup(o);
  const radio = new RadioStore();
  radio.goLive();
  await settle();
  const ws = FakeSocket.last();
  ws.open();
  ws.text(STATE);
  return { env, radio, ws, ctx: FakeAudioContext.last(), node: FakeWorkletNode.last() };
}

/** Send a message with audio: say, PCM in two frames, say_end. */
function sayAudio(ws: FakeSocket, id: string, samples = 2400, kind = "answer", rate = 24000): void {
  ws.text({ type: "say", id, kind, text: `text ${id}`, speech: `speech ${id}`, sample_rate: rate, n_bytes: samples * 2 });
  const all = pcm(samples);
  ws.binary(all.slice(0, samples));
  ws.binary(all.slice(samples));
  ws.text({ type: "say_end", id });
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(Math, "random").mockReturnValue(0.5); // reconnect jitter factor exactly 1
  FakeSocket.instances = [];
  FakeAudioContext.instances = [];
  FakeWorkletNode.instances = [];
  FakeUtterance.instances = [];
  resetTokenCacheForTests();
});

afterEach(() => {
  vi.useRealTimers();
});

// ------------------------------------------------------------------------------------------------ pure helpers

describe("pure helpers", () => {
  it("pcm16ToFloat32 decodes int16 little-endian and ignores an odd trailing byte", () => {
    const bytes = new Uint8Array([0x00, 0x80, 0xff, 0x7f, 0x00, 0x00, 0x01]);
    expect(Array.from(pcm16ToFloat32(bytes))).toEqual([-1, 32767 / 32768, 0]);
  });

  it("levelFromRms maps -60..0 dBFS to 0..1 and clamps", () => {
    expect(levelFromRms(0)).toBe(0);
    expect(levelFromRms(Number.NaN)).toBe(0);
    expect(levelFromRms(1)).toBe(1);
    expect(levelFromRms(0.001)).toBeCloseTo(0, 6); // -60 dBFS
    expect(levelFromRms(0.0316)).toBeCloseTo(0.5, 2); // -30 dBFS
    expect(levelFromRms(2)).toBe(1);
  });

  it("concatChunks joins chunks and stops at the expected size", () => {
    const out = concatChunks([new Uint8Array([1, 2]).buffer, new Uint8Array([3, 4, 5]).buffer], 4);
    expect(Array.from(out)).toEqual([1, 2, 3, 4]);
  });

  it("derived flags: pttActive, engineerTalking, pttUsable", () => {
    const base = { pttHeld: false, speaking: false, server: null, phase: "live", conn: "open", mic: "live" } as const;
    expect(pttActive(base)).toBe(false);
    expect(pttActive({ ...base, server: { ...STATE, ptt: true, ptt_source: "wheel" } as RadioState["server"] })).toBe(true);
    expect(engineerTalking({ ...base, server: { ...STATE, speaking: true } as RadioState["server"] })).toBe(true);
    expect(pttUsable(base)).toBe(true);
    expect(pttUsable({ ...base, conn: "waiting" })).toBe(false);
    expect(pttUsable({ ...base, mic: "denied" })).toBe(false);
    expect(pttUsable({ ...base, phase: "idle" })).toBe(false);
  });
});

describe("settings storage", () => {
  it("defaults: voice on, normal, device voice when Web Speech exists, version 1", () => {
    setup();
    expect(loadSettings(true)).toEqual({
      voiceEnabled: true,
      intensity: "normal",
      voiceSource: "device",
      deviceVoice: null,
      deviceRate: 1,
      version: 1,
      handsFree: false,
      wakeWord: "pitwall",
      handsFreeConsent: false,
      talkButton: null,
    });
    expect(loadSettings(false).voiceSource).toBe("server");
  });

  it("validates each stored field and keeps valid ones", () => {
    setup({ settings: { voiceEnabled: false, intensity: "loud", voiceSource: "x", deviceVoice: 3, deviceRate: 9, version: 2.7 } });
    expect(loadSettings(false)).toEqual({
      voiceEnabled: false,
      intensity: "normal",
      voiceSource: "server",
      deviceVoice: null,
      deviceRate: 1,
      version: 2,
      handsFree: false,
      wakeWord: "pitwall",
      handsFreeConsent: false,
      talkButton: null,
    });
  });

  it("survives corrupt JSON and missing storage", () => {
    const env = setup();
    env.local.setItem(SETTINGS_KEY, "{nope");
    expect(loadSettings(false).intensity).toBe("normal");
    vi.stubGlobal("localStorage", undefined);
    expect(loadSettings(false).version).toBe(1);
  });
});

// ------------------------------------------------------------------------------------------------ lifecycle

describe("module singleton", () => {
  it("imports in plain node (no window) as an idle, listen-only radio", () => {
    expect(singleton).toBeInstanceOf(RadioStore);
    expect(singleton.get().phase).toBe("idle");
    expect(singleton.get().micCapable).toBe(false);
    expect(singleton.get().mic).toBe("unavailable");
  });
});

describe("goLive", () => {
  it("unlocks audio, opens the mic once, loads the worklet and connects with hello / settings / ping", async () => {
    const env = setup({ url: "https://mac.tail.ts.net:8443/next/#/radio?token=abc" });
    const radio = new RadioStore();
    radio.goLive();
    // Synchronously inside the tap: AudioContext created and resumed, getUserMedia started, wake lock requested.
    const ctx = FakeAudioContext.last();
    expect(ctx.options).toEqual({ latencyHint: "interactive" });
    expect(ctx.resume).toHaveBeenCalled();
    expect(ctx.sources[0]?.startAt).toBe(0); // silent unlock buffer
    expect(env.nav.mediaDevices.getUserMedia).toHaveBeenCalledWith({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      video: false,
    });
    expect(env.nav.wakeLock?.request).toHaveBeenCalledWith("screen");
    expect(radio.get().phase).toBe("starting");
    expect(radio.get().conn).toBe("connecting");
    // A token link: one HTTP probe with the token in the query makes the server set its cookie.
    expect(env.fetch).toHaveBeenCalledWith("/api/voice/status?token=abc", expect.objectContaining({ credentials: "same-origin" }));

    await settle();
    expect(ctx.audioWorklet.addModule).toHaveBeenCalledWith("/mic-worklet.js?v=2");
    expect(FakeWorkletNode.last().name).toBe("pitwall-mic");
    expect(radio.get()).toMatchObject({ phase: "live", mic: "live", wake: "on", audio: "running" });

    const ws = FakeSocket.last();
    expect(ws.url).toBe("wss://mac.tail.ts.net:8443/ws/radio?token=abc");
    expect(ws.binaryType).toBe("arraybuffer");
    ws.open();
    expect(ws.json()).toEqual([
      { type: "hello", client: "ipad", sample_rate: 16000, version: 1, tts_mode: "server" },
      { type: "settings", voice_enabled: true, intensity: "normal", tts_mode: "server", handsfree: false, wake_word: "pitwall" },
      { type: "ping", t: expect.any(Number) },
    ]);
    expect(radio.get().conn).toBe("open");
    expect(radio.get().log.map((e) => e.text)).toEqual(["Radio on"]);
  });

  it("is a no-op while already live", async () => {
    const { radio } = await goLive();
    radio.goLive();
    expect(FakeAudioContext.instances).toHaveLength(1);
    expect(FakeSocket.instances).toHaveLength(1);
  });

  it("goes live listen-only on plain HTTP (no getUserMedia, no worklet)", async () => {
    const env = setup({ url: "http://192.168.1.20:8770/next/#/drive/coach", secure: false });
    const radio = new RadioStore();
    expect(radio.get().micCapable).toBe(false);
    radio.goLive();
    await settle();
    expect(env.nav.mediaDevices.getUserMedia).not.toHaveBeenCalled();
    expect(FakeWorkletNode.instances).toHaveLength(0);
    expect(FakeSocket.last().url).toBe("ws://192.168.1.20:8770/ws/radio");
    expect(radio.get()).toMatchObject({ phase: "live", mic: "unavailable" });
    expect(radio.get().log[0]?.meta).toBe("listen-only: no microphone over plain HTTP");
  });

  it("reports a browser that cannot create an AudioContext and stays idle", () => {
    setup();
    const radio = new RadioStore();
    FakeAudioContext.failNext = true;
    radio.goLive();
    expect(radio.get().phase).toBe("idle");
    expect(radio.get().error).toBe("This browser cannot play audio (no audio hardware).");
  });

  it("explains a denied microphone and still goes live", async () => {
    const env = setup();
    env.nav.mediaDevices.getUserMedia.mockRejectedValueOnce(new DOMException("no", "NotAllowedError"));
    const radio = new RadioStore();
    radio.goLive();
    await settle();
    expect(radio.get()).toMatchObject({ phase: "live", mic: "denied" });
    expect(radio.get().error).toMatch(/^Microphone permission denied/);
    expect(radio.get().log.at(-1)?.kind).toBe("error");
  });

  it("tells a worklet load failure apart from a busy mic, and releases the opened mic", async () => {
    const env = setup();
    const radio = new RadioStore();
    FakeAudioContext.addModuleError = new DOMException("fetch failed", "AbortError");
    radio.goLive();
    await settle();
    expect(radio.get().mic).toBe("error");
    expect(radio.get().error).toMatch(/mic-worklet\.js\) failed to load: fetch failed/);
    expect(env.streams[0]?.track.stopped).toBe(true);
  });

  it("stop() closes the socket, mic, context and wake lock and keeps the log", async () => {
    const { radio, ws, ctx, env } = await goLive();
    radio.stop();
    expect(ws.closedWith).toEqual({ code: 1000, reason: "radio off" });
    expect(env.streams[0]?.track.stopped).toBe(true);
    expect(ctx.close).toHaveBeenCalled();
    expect(env.sentinels[0]?.release).toHaveBeenCalled();
    expect(env.doc.count("visibilitychange")).toBe(0);
    expect(env.win.count("online")).toBe(0);
    expect(radio.get()).toMatchObject({
      phase: "idle",
      conn: "offline",
      mic: "off",
      wake: "off",
      audio: "none",
      server: null,
      speaking: false,
      level: 0,
    });
    expect(radio.get().log.map((e) => e.text)).toEqual(["Radio on", "Radio off"]);
    vi.advanceTimersByTime(60_000);
    expect(FakeSocket.instances).toHaveLength(1); // no reconnect after stop
  });

  it("notifies subscribers with a new immutable state object", async () => {
    const { radio } = await goLive();
    const before = radio.get();
    const seen: RadioState[] = [];
    const off = radio.subscribe(() => seen.push(radio.get()));
    radio.setIntensity("detailed");
    off();
    expect(seen).toHaveLength(1);
    expect(seen[0]).not.toBe(before);
    expect(before.settings.intensity).toBe("normal"); // the old snapshot is untouched
    expect(seen[0]?.settings.intensity).toBe("detailed");
  });
});

// ------------------------------------------------------------------------------------------------ microphone

describe("microphone frames", () => {
  it("streams worklet frames as binary, meters the level and records the worklet's rates", async () => {
    const { radio, ws, node } = await goLive();
    node.post({ type: "ready", inputRate: 44100, outputRate: 16000, taps: 224, phases: 160, exact: true });
    expect(radio.get().stats).toMatchObject({ contextRate: 44100, taps: 224 });
    node.frame(0.0316);
    expect(ws.binaries()).toHaveLength(1);
    expect(radio.get().level).toBeCloseTo(0.5, 2);
    node.frame(0); // decays 0.04 per frame instead of dropping to 0
    expect(radio.get().level).toBeCloseTo(0.46, 2);
    vi.advanceTimersByTime(1000);
    expect(radio.get().stats.framesSent).toBe(2);
  });

  it("drops frames instead of queueing when the socket is backed up", async () => {
    const { radio, ws, node } = await goLive();
    ws.bufferedAmount = 200 * 1024;
    node.frame();
    expect(ws.binaries()).toHaveLength(0);
    vi.advanceTimersByTime(1000);
    expect(radio.get().stats).toMatchObject({ framesDropped: 1, bufferedBytes: 200 * 1024 });
  });

  it("flags a live track that only delivers digital silence (iOS muted-but-live)", async () => {
    const { radio, node } = await goLive();
    node.frame(0);
    vi.advanceTimersByTime(8001);
    node.frame(0);
    expect(radio.get().micSilent).toBe(true);
    node.frame(0.01);
    expect(radio.get().micSilent).toBe(false);
  });

  it("follows track mute / unmute and re-acquires an ended track", async () => {
    const { radio, env, ws } = await goLive();
    const track = env.streams[0]!.track;
    track.fire("mute");
    expect(radio.get().mic).toBe("muted");
    track.fire("unmute");
    expect(radio.get().mic).toBe("live");
    ws.clear();
    track.fire("ended");
    expect(radio.get().mic).toBe("requesting");
    await settle();
    expect(env.nav.mediaDevices.getUserMedia).toHaveBeenCalledTimes(2);
    expect(radio.get().mic).toBe("live");
    expect(ws.types()).toContain("hello"); // the server learns the new capture
    expect(radio.get().log.at(-1)).toMatchObject({ text: "Mic re-acquired", meta: "track ended" });
  });
});

// ------------------------------------------------------------------------------------------------ push-to-talk

describe("push-to-talk", () => {
  it("sends ptt down at once and the release after the hang time and the worklet flush", async () => {
    const { radio, ws, node } = await goLive();
    ws.clear();
    radio.pttPress();
    expect(ws.json()).toEqual([{ type: "ptt", down: true }]);
    expect(radio.get().pttHeld).toBe(true);
    radio.pttRelease();
    expect(radio.get().pttHeld).toBe(false);
    vi.advanceTimersByTime(249);
    expect(ws.json()).toHaveLength(1);
    expect(node.port.postMessage).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(node.port.postMessage).toHaveBeenCalledWith({ type: "flush", seq: 1 });
    node.frame(); // the partial frame arrives before "flushed" (the port is ordered)
    node.post({ type: "flushed", seq: 1 });
    expect(ws.sent.at(-2)).toBeInstanceOf(ArrayBuffer);
    expect(ws.json().at(-1)).toEqual({ type: "ptt", down: false });
    vi.advanceTimersByTime(1000);
    expect(ws.json().filter((m) => m.type === "ptt")).toHaveLength(2);
  });

  it("releases anyway when the worklet does not answer the flush", async () => {
    const { radio, ws } = await goLive();
    radio.pttPress();
    radio.pttRelease();
    vi.advanceTimersByTime(250 + 149);
    expect(ws.json().filter((m) => m.type === "ptt")).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(ws.json().at(-1)).toEqual({ type: "ptt", down: false });
  });

  it("re-keying within the hang time continues the transmission (no release, no second press)", async () => {
    const { radio, ws } = await goLive();
    ws.clear();
    radio.pttPress();
    radio.pttRelease();
    vi.advanceTimersByTime(100);
    radio.pttPress();
    vi.advanceTimersByTime(1000);
    expect(ws.json()).toEqual([{ type: "ptt", down: true }]);
    radio.pttRelease(true); // immediate: no hang time
    expect(ws.json().at(-1)).toEqual({ type: "ptt", down: false });
  });

  it("is ignored while the radio is off and when already held", async () => {
    const { radio, ws } = await goLive();
    ws.clear();
    radio.pttPress();
    radio.pttPress();
    expect(ws.json()).toHaveLength(1);
    radio.stop();
    radio.pttPress();
    expect(radio.get().pttHeld).toBe(false);
  });

  it("releases immediately when the page is hidden (it may be frozen before the hang time ends)", async () => {
    const { radio, ws, env } = await goLive();
    radio.pttPress();
    env.doc.visibilityState = "hidden";
    env.doc.fire("visibilitychange");
    expect(radio.get().pttHeld).toBe(false);
    expect(ws.json().at(-1)).toEqual({ type: "ptt", down: false });
  });

  it("a dropped link forgets the held PTT (the server releases it on disconnect)", async () => {
    const { radio, ws } = await goLive();
    radio.pttPress();
    ws.serverClose(1006);
    expect(radio.get().pttHeld).toBe(false);
    expect(radio.get().conn).toBe("waiting");
  });
});

// ------------------------------------------------------------------------------------------------ playback

describe("playback and the half-duplex gate", () => {
  it("plays a message at its own sample rate and reports started / ended", async () => {
    const { radio, ws, ctx } = await goLive();
    ws.clear();
    sayAudio(ws, "m1", 2400, "lap_summary", 24000);
    const [clip] = ctx.clips();
    expect(clip?.buffer?.sampleRate).toBe(24000);
    expect(clip?.buffer?.duration).toBeCloseTo(0.1, 6);
    expect(clip?.buffer?.data[1]).toBeCloseTo(100 / 32768, 6);
    expect(clip?.startAt).toBe(0);
    expect(radio.get()).toMatchObject({ speaking: true, speakingId: "m1" });
    expect(radio.get().current).toMatchObject({ id: "m1", kind: "lap_summary", text: "text m1", audioS: 0.1 });
    expect(radio.get().log.at(-1)).toMatchObject({ kind: "lap_summary", meta: "0.1 s audio", id: "m1" });
    expect(ws.json()).toEqual([{ type: "playback", id: "m1", state: "started" }]);
    clip?.end();
    expect(ws.json().at(-1)).toEqual({ type: "playback", id: "m1", state: "ended" });
    expect(radio.get()).toMatchObject({ speaking: false, speakingId: null });
  });

  it("queues a second message behind the first and reports it started only when audible", async () => {
    const { ws, ctx } = await goLive();
    ws.clear();
    sayAudio(ws, "m1", 2400);
    sayAudio(ws, "m2", 4800);
    const [a, b] = ctx.clips();
    expect(b?.startAt).toBeCloseTo(0.1, 6); // never overlaps
    expect(ws.json().filter((m) => m.state === "started").map((m) => m.id)).toEqual(["m1"]);
    ctx.currentTime = 0.1;
    vi.advanceTimersByTime(100);
    expect(ws.json().filter((m) => m.state === "started").map((m) => m.id)).toEqual(["m1", "m2"]);
    a?.end();
    b?.end();
    expect(ws.json().filter((m) => m.state === "ended").map((m) => m.id)).toEqual(["m1", "m2"]);
  });

  it("logs a short clip and plays what arrived", async () => {
    const { radio, ws, ctx } = await goLive();
    ws.text({ type: "say", id: "m1", kind: "answer", text: "t", speech: "t", sample_rate: 24000, n_bytes: 4800 });
    ws.binary(pcm(1000));
    ws.text({ type: "say_end", id: "m1" });
    expect(radio.get().log.some((e) => e.text === "Audio for m1: got 2000 of 4800 bytes")).toBe(true);
    expect(ctx.clips()[0]?.buffer?.data.length).toBe(1000);
  });

  it("shows a text-only message without playing anything", async () => {
    const { radio, ws, ctx } = await goLive();
    ws.text({ type: "say", id: "m1", kind: "alert", text: "Yellow flag", speech: "Yellow flag", sample_rate: 24000, n_bytes: 0 });
    ws.text({ type: "say_end", id: "m1" });
    expect(ctx.clips()).toHaveLength(0);
    expect(radio.get().current).toMatchObject({ id: "m1", audioS: 0, text: "Yellow flag" });
    expect(radio.get().log.at(-1)?.meta).toBe("text only");
  });

  it("cancel stops the message and reports ended", async () => {
    const { radio, ws, ctx } = await goLive();
    sayAudio(ws, "m1");
    ws.clear();
    ws.text({ type: "cancel", id: "m1" });
    expect(ctx.clips()[0]?.stopped).toBe(true);
    expect(ws.json()).toEqual([{ type: "playback", id: "m1", state: "ended" }]);
    expect(radio.get().speaking).toBe(false);
  });

  it("PTT while the engineer talks is a barge-in: ptt first, then ended, then stop_tts", async () => {
    const { radio, ws, ctx } = await goLive();
    sayAudio(ws, "m1");
    ws.clear();
    radio.pttPress();
    expect(ws.json()).toEqual([
      { type: "ptt", down: true },
      { type: "playback", id: "m1", state: "ended" },
      { type: "stop_tts" },
    ]);
    expect(ctx.clips()[0]?.stopped).toBe(true);
    expect(radio.get().speaking).toBe(false);
  });

  it("PTT while a message is still arriving drops it (barge-in)", async () => {
    const { radio, ws, ctx } = await goLive();
    ws.text({ type: "say", id: "m1", kind: "answer", text: "t", speech: "t", sample_rate: 24000, n_bytes: 4800 });
    radio.pttPress();
    ws.binary(pcm(2400));
    ws.text({ type: "say_end", id: "m1" });
    expect(ctx.clips()).toHaveLength(0);
    expect(ws.types()).toContain("stop_tts");
  });

  it("a message that arrives while the driver transmits on screen is shown, not played", async () => {
    const { radio, ws, ctx } = await goLive();
    radio.pttPress();
    ws.clear();
    sayAudio(ws, "m1");
    expect(ctx.clips()).toHaveLength(0);
    expect(ws.json()).toEqual([{ type: "stop_tts" }]);
    expect(radio.get().current?.id).toBe("m1");
    expect(radio.get().log.at(-1)).toMatchObject({ id: "m1", meta: "not played: you were transmitting" });
  });

  it("wheel PTT (seen through server state) gates playback the same way", async () => {
    const { radio, ws, ctx } = await goLive();
    ws.text({ ...STATE, ptt: true, ptt_source: "wheel" });
    expect(pttActive(radio.get())).toBe(true);
    expect(radio.get().pttHeld).toBe(false);
    ws.clear();
    sayAudio(ws, "m1");
    expect(ctx.clips()).toHaveLength(0);
    expect(ws.json()).toEqual([{ type: "stop_tts" }]);
    // Keyed on the wheel while a message is still arriving (the server did not cancel it): not played either.
    ws.text({ ...STATE, ptt: false, ptt_source: "wheel" });
    ws.text({ type: "say", id: "m2", kind: "answer", text: "t", speech: "t", sample_rate: 24000, n_bytes: 4800 });
    ws.text({ ...STATE, ptt: true, ptt_source: "wheel" });
    ws.clear();
    ws.binary(pcm(2400));
    ws.text({ type: "say_end", id: "m2" });
    expect(ctx.clips()).toHaveLength(0);
    expect(ws.json()).toEqual([{ type: "stop_tts" }]);
    expect(radio.get().log.find((e) => e.id === "m2")?.meta).toMatch(/not played: you were transmitting/);
    // Wheel released: the next message plays.
    ws.text({ ...STATE, ptt: false, ptt_source: "wheel" });
    sayAudio(ws, "m3");
    expect(ctx.clips()).toHaveLength(1);
  });

  it("measures the reply latency from a wheel release", async () => {
    const { radio, ws } = await goLive();
    ws.text({ ...STATE, ptt: true, ptt_source: "wheel" });
    ws.text({ ...STATE, ptt: false, ptt_source: "wheel" });
    vi.advanceTimersByTime(420);
    ws.text({ type: "transcript", text: "how are my tyres", stt_ms: 180, audio_s: 1.4 });
    expect(radio.get().log.at(-1)).toMatchObject({
      kind: "transcript",
      text: "how are my tyres",
      meta: "STT 180 ms · 1.4 s audio · +420 ms after release",
    });
  });

  it("an empty transcript says nothing was understood", async () => {
    const { radio, ws } = await goLive();
    ws.text({ type: "transcript", text: "  ", stt_ms: 90, audio_s: 0.3 });
    expect(radio.get().log.at(-1)?.text).toBe("(nothing understood)");
  });

  it("stopSpeaking stops the audio without keying the mic", async () => {
    const { radio, ws } = await goLive();
    sayAudio(ws, "m1");
    ws.clear();
    radio.stopSpeaking();
    expect(ws.types()).toEqual(["playback", "stop_tts"]);
  });

  it("while audio is suspended only the newest clip is kept, and stale ones are dropped on resume", async () => {
    const { radio, ws, ctx } = await goLive();
    ctx.resumeWorks = false;
    ctx.setState("suspended");
    expect(radio.get().audio).toBe("suspended");
    sayAudio(ws, "m1");
    ws.clear();
    sayAudio(ws, "m2");
    // m1 never started: it is dropped, and still reported ended (the server may hold its gate for it).
    expect(ws.json()).toEqual([{ type: "playback", id: "m1", state: "ended" }]);
    expect(radio.get().log.find((e) => e.id === "m1")?.meta).toMatch(/dropped: audio paused, newer message/);
    vi.advanceTimersByTime(7000);
    ctx.setState("running");
    expect(ctx.clips()[1]?.stopped).toBe(true);
    expect(radio.get().log.find((e) => e.id === "m2")?.meta).toMatch(/dropped: audio was paused/);
    expect(radio.get().speaking).toBe(false);
  });
});

// ------------------------------------------------------------------------------------------------ device voice

describe("device voice (Web Speech)", () => {
  const VOICES = [
    { name: "Samantha", lang: "en-US", voiceURI: "com.apple.voice.compact.en-US.Samantha" },
    { name: "Jamie (Premium)", lang: "en-GB", voiceURI: "com.apple.voice.premium.en-GB.Jamie" },
    { name: "Daniel (Enhanced)", lang: "en-GB", voiceURI: "com.apple.voice.enhanced.en-GB.Daniel" },
    { name: "Thomas", lang: "fr-FR", voiceURI: "com.apple.voice.compact.fr-FR.Thomas" },
  ];

  it("lists English voices Premium first and reports every voice to the server", async () => {
    const { radio, ws } = await goLive({ speech: true, voices: VOICES, settings: { version: 2, voiceSource: "device" } });
    expect(radio.get().deviceVoices.map((v) => [v.name, v.quality])).toEqual([
      ["Jamie (Premium)", "premium"],
      ["Daniel (Enhanced)", "enhanced"],
      ["Samantha", "standard"],
    ]);
    expect(radio.currentDeviceVoiceUri()).toBe("com.apple.voice.premium.en-GB.Jamie");
    expect(ws.types()).toContain("hello");
    await settle(); // the voice report is queued as a microtask after hello
    const report = ws.json().find((m) => m.type === "voices");
    expect((report?.voices as unknown[]).length).toBe(4);
    expect(ws.json().find((m) => m.type === "hello")?.tts_mode).toBe("device");
  });

  it("speaks a display-only message with the device voice and reports started / ended", async () => {
    const { radio, ws, env } = await goLive({ speech: true, voices: VOICES, settings: { version: 2, voiceSource: "device" } });
    ws.clear();
    ws.text({ type: "say", id: "m1", kind: "answer", text: "Fronts 92", speech: "Fronts ninety two", sample_rate: 24000, n_bytes: 0, device_tts: true });
    const u = FakeUtterance.instances.at(-1)!;
    expect(env.speech.speak).toHaveBeenCalledWith(u);
    expect(u.text).toBe("Fronts ninety two");
    expect(u.lang).toBe("en-GB");
    expect(radio.get().log.at(-1)?.meta).toBe("device voice");
    u.onstart?.();
    expect(radio.get().speakingId).toBe("m1");
    u.onend?.();
    expect(ws.json()).toEqual([
      { type: "playback", id: "m1", state: "started" },
      { type: "playback", id: "m1", state: "ended" },
    ]);
  });

  it("speaks every kind: goal, validation and a kind this dashboard does not know yet", async () => {
    const { radio, ws, env } = await goLive({ speech: true, voices: VOICES, settings: { version: 2, voiceSource: "device" } });
    for (const [id, kind] of [["g1", "goal"], ["v1", "validation"], ["n1", "brand_new_kind"]] as const) {
      ws.text({ type: "say", id, kind, text: `text ${id}`, speech: `speech ${id}`, sample_rate: 24000, n_bytes: 0, device_tts: true });
      const u = FakeUtterance.instances.at(-1)!;
      expect(u.text).toBe(`speech ${id}`);
      expect(env.speech.speak).toHaveBeenCalledWith(u);
      expect(radio.get().log.at(-1)).toMatchObject({ kind, id });
      u.onstart?.();
      u.onend?.();
    }
  });

  it("a Mac-voice device ignores device_tts and stays text only", async () => {
    const { ws, env } = await goLive({ speech: true, voices: VOICES, settings: { version: 2, voiceSource: "server" } });
    ws.text({ type: "say", id: "m1", kind: "answer", text: "x", speech: "x", sample_rate: 24000, n_bytes: 0, device_tts: true });
    expect(env.speech.speak).not.toHaveBeenCalledWith(expect.objectContaining({ text: "x" }));
  });

  it("device voice and rate are stored; the rate is clamped", async () => {
    const { radio, env } = await goLive({ speech: true, voices: VOICES, settings: { version: 2, voiceSource: "device" } });
    radio.setDeviceVoice("com.apple.voice.enhanced.en-GB.Daniel");
    radio.setDeviceRate(3);
    expect(radio.get().settings).toMatchObject({ deviceVoice: "com.apple.voice.enhanced.en-GB.Daniel", deviceRate: 1.5 });
    expect(JSON.parse(env.local.getItem(SETTINGS_KEY) ?? "{}")).toMatchObject({ deviceRate: 1.5 });
    radio.testDeviceVoice();
    expect(FakeUtterance.instances.at(-1)?.text).toBe(VOICE_TEST_TEXT);
    expect(FakeUtterance.instances.at(-1)?.rate).toBe(1.5);
  });
});

// ------------------------------------------------------------------------------------------------ settings

describe("settings over the radio link", () => {
  it("intensity and voice on/off are stored and sent with tts_mode", async () => {
    const { radio, ws, env } = await goLive();
    ws.clear();
    radio.setIntensity("quiet");
    radio.setVoiceEnabled(false);
    expect(ws.json()).toEqual([
      { type: "settings", voice_enabled: true, intensity: "quiet", tts_mode: "server", handsfree: false, wake_word: "pitwall" },
      { type: "settings", voice_enabled: false, intensity: "quiet", tts_mode: "server", handsfree: false, wake_word: "pitwall" },
    ]);
    expect(JSON.parse(env.local.getItem(SETTINGS_KEY) ?? "{}")).toMatchObject({ intensity: "quiet", voiceEnabled: false });
  });

  it("cue mode and the Mac voice are server-wide settings confirmed by the next state", async () => {
    const { radio, ws } = await goLive();
    ws.clear();
    radio.setCueMode("all");
    radio.setServerVoice("bf_emma");
    radio.setServerVoice("bm_george"); // already the voice in use: nothing to send
    radio.setServerVoice("");
    expect(ws.json()).toEqual([
      { type: "settings", cue_mode: "all" },
      { type: "settings", tts_voice: "bf_emma" },
    ]);
    ws.text({ ...STATE, cue_mode: "all", tts_voice: "bf_emma" });
    expect(radio.get().server).toMatchObject({ cue_mode: "all", tts_voice: "bf_emma" });
  });

  it("test_voice asks the Mac for a radio check, and says when the link is down", async () => {
    const { radio, ws } = await goLive();
    ws.clear();
    radio.testServerVoice();
    expect(ws.json()).toEqual([{ type: "test_voice", text: VOICE_TEST_TEXT }]);
    expect(radio.get().serverVoiceTest).toBe("sent");
    ws.serverClose(1006);
    radio.testServerVoice();
    expect(radio.get().serverVoiceTest).toBe("failed");
  });

  it("follows server-side changes (voice commands) but not the first state after a connect", async () => {
    const env = setup({ settings: { intensity: "quiet", version: 2 } });
    const radio = new RadioStore();
    radio.goLive();
    await settle();
    const ws = FakeSocket.last();
    ws.open();
    ws.text({ ...STATE, intensity: "normal" }); // predates our settings message
    expect(radio.get().settings.intensity).toBe("quiet");
    ws.text({ ...STATE, intensity: "detailed", voice_enabled: false }); // "more detail" said on the radio
    expect(radio.get().settings).toMatchObject({ intensity: "detailed", voiceEnabled: false });
    expect(JSON.parse(env.local.getItem(SETTINGS_KEY) ?? "{}")).toMatchObject({ intensity: "detailed" });
  });

  it("typed questions and radio check go out as ask; offline they are logged as not sent", async () => {
    const { radio, ws } = await goLive();
    ws.clear();
    expect(radio.ask("  how are my tyres  ")).toBe(true);
    expect(radio.radioCheck()).toBe(true);
    expect(radio.ask("   ")).toBe(false);
    expect(ws.json()).toEqual([
      { type: "ask", text: "how are my tyres" },
      { type: "ask", text: "radio check" },
    ]);
    ws.serverClose(1006);
    expect(radio.ask("anyone?")).toBe(false);
    expect(radio.get().log.at(-1)).toMatchObject({ kind: "you", text: "anyone?", meta: "not sent: radio offline" });
  });
});

describe("device voices (Settings › Radio & voice)", () => {
  it("lists Premium, then Enhanced, then standard; British first within a quality, then by name", () => {
    setup({
      speech: true,
      voices: [
        { name: "Albert", lang: "en-US", voiceURI: "com.apple.speech.synthesis.voice.Albert" },
        { name: "Daniel", lang: "en-GB", voiceURI: "com.apple.voice.compact.en-GB.Daniel" },
        { name: "Zoe (Enhanced)", lang: "en-US", voiceURI: "com.apple.voice.enhanced.en-US.Zoe" },
        { name: "Amélie", lang: "fr-CA", voiceURI: "com.apple.voice.compact.fr-CA.Amelie" },
        { name: "Jamie (Premium)", lang: "en-GB", voiceURI: "com.apple.voice.premium.en-GB.Jamie" },
      ],
    });
    expect(listDeviceVoices().map((v) => v.name)).toEqual(["Jamie (Premium)", "Zoe (Enhanced)", "Daniel", "Albert"]);
  });
});

describe("settings version migration (one-time switch to the Mac's natural voice)", () => {
  const SPEECH = { speech: true, voices: [{ name: "Jamie (Premium)", lang: "en-GB", voiceURI: "premium.Jamie" }] };

  it("moves a version-1 device-voice radio to the Mac voice once Kokoro is ready", async () => {
    const env = setup({ ...SPEECH, settings: { voiceSource: "device", version: 1 } });
    const radio = new RadioStore();
    radio.goLive();
    await settle();
    const ws = FakeSocket.last();
    ws.open();
    ws.clear();
    ws.text({ ...STATE, tts_ready: false }); // still on the `say` fallback: no upgrade yet
    expect(radio.get().settings).toMatchObject({ voiceSource: "device", version: 1 });
    ws.text(STATE);
    expect(radio.get().settings).toMatchObject({ voiceSource: "server", version: 2 });
    expect(ws.json()).toEqual([{ type: "settings", voice_enabled: true, intensity: "normal", tts_mode: "server", handsfree: false, wake_word: "pitwall" }]);
    expect(radio.get().log.at(-1)?.text).toMatch(/^Switched to the Mac's natural voice/);
    expect(JSON.parse(env.local.getItem(SETTINGS_KEY) ?? "{}")).toMatchObject({ voiceSource: "server", version: 2 });
  });

  it("an explicit choice of the device voice sticks", async () => {
    const { radio, ws } = await goLive({ ...SPEECH, settings: { voiceSource: "server", version: 2 } });
    ws.clear();
    radio.setVoiceSource("device");
    expect(radio.get().settings).toMatchObject({ voiceSource: "device", version: 2 });
    expect(ws.json()[0]).toEqual({ type: "settings", voice_enabled: true, intensity: "normal", tts_mode: "device", handsfree: false, wake_word: "pitwall" });
    ws.serverClose(1006);
    vi.advanceTimersByTime(600);
    FakeSocket.last().open();
    FakeSocket.last().text(STATE);
    expect(radio.get().settings.voiceSource).toBe("device");
  });

  it("a version-1 Mac-voice radio is only stamped version 2", async () => {
    const { radio } = await goLive({ settings: { voiceSource: "server", version: 1 } });
    expect(radio.get().settings).toMatchObject({ voiceSource: "server", version: 2 });
    expect(radio.get().log.some((e) => e.text.startsWith("Switched"))).toBe(false);
  });
});

// ------------------------------------------------------------------------------------------------ link health

describe("reconnect", () => {
  it("reconnects with a growing backoff that resets only after the hub sent state", async () => {
    const { radio, ws } = await goLive();
    ws.serverClose(1006); // healthy socket lost
    expect(radio.get()).toMatchObject({ conn: "waiting", retryInS: 1, server: null });
    vi.advanceTimersByTime(499);
    expect(FakeSocket.instances).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(FakeSocket.instances).toHaveLength(2);
    // Accepted then closed without state (twice): the backoff keeps growing.
    FakeSocket.last().open();
    FakeSocket.last().serverClose(1011);
    vi.advanceTimersByTime(999);
    expect(FakeSocket.instances).toHaveLength(2);
    vi.advanceTimersByTime(1);
    FakeSocket.last().open();
    FakeSocket.last().serverClose(1011);
    vi.advanceTimersByTime(1999);
    expect(FakeSocket.instances).toHaveLength(3);
    vi.advanceTimersByTime(1);
    expect(FakeSocket.instances).toHaveLength(4);
    // Healthy again: the next loss retries after the minimum backoff.
    FakeSocket.last().open();
    FakeSocket.last().text(STATE);
    FakeSocket.last().serverClose(1006);
    vi.advanceTimersByTime(500);
    expect(FakeSocket.instances).toHaveLength(5);
    expect(radio.get().phase).toBe("live");
  });

  it("caps the backoff at 8 s and counts the retry down", async () => {
    const { radio } = await goLive();
    for (let i = 0; i < 6; i++) {
      FakeSocket.last().serverClose(1011);
      vi.advanceTimersByTime(8000);
    }
    FakeSocket.last().serverClose(1011);
    expect(radio.get().retryInS).toBe(8);
    vi.advanceTimersByTime(3000);
    expect(radio.get().retryInS).toBe(5);
  });

  it("a server close for auth (4401) shows the access message and retries slowly", async () => {
    const { radio } = await goLive();
    FakeSocket.last().serverClose(4401);
    expect(radio.get().error).toBe(ACCESS_DENIED);
    vi.advanceTimersByTime(29_999);
    expect(FakeSocket.instances).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(FakeSocket.instances).toHaveLength(2);
    FakeSocket.last().open();
    FakeSocket.last().text(STATE);
    expect(radio.get().error).toBeNull(); // the link error clears once the hub accepts us
  });

  it("an error before any state, then a close, explains why (voice disabled)", async () => {
    setup();
    const radio = new RadioStore();
    radio.goLive();
    await settle();
    const ws = FakeSocket.last();
    ws.open();
    ws.text({ type: "error", message: "voice is disabled" });
    ws.serverClose(1000);
    expect(radio.get().error).toBe(VOICE_DISABLED);
    expect(radio.get().retryInS).toBe(30);
  });

  it("a refused handshake (1006 before open) is diagnosed over HTTP", async () => {
    const env = setup();
    env.fetch.mockResolvedValue(httpReply(401));
    const radio = new RadioStore();
    radio.goLive();
    await settle();
    FakeSocket.last().serverClose(1006);
    await settle();
    expect(env.fetch).toHaveBeenCalledWith("/api/voice/status", expect.objectContaining({ cache: "no-store" }));
    expect(radio.get().error).toBe(ACCESS_DENIED);
    expect(radio.get().retryInS).toBe(30);
  });

  it("forgets a refused remembered token and retries at the normal pace", async () => {
    const env = setup();
    env.session.setItem("pitwall-radio-token", "old");
    env.fetch.mockResolvedValue(httpReply(401));
    const radio = new RadioStore();
    radio.goLive();
    await settle();
    expect(FakeSocket.last().url).toBe("wss://mac.tail.ts.net:8443/ws/radio?token=old");
    FakeSocket.last().serverClose(1006);
    await settle();
    expect(env.session.getItem("pitwall-radio-token")).toBeNull();
    vi.advanceTimersByTime(500);
    expect(FakeSocket.last().url).toBe("wss://mac.tail.ts.net:8443/ws/radio"); // the cookie may still be valid
  });

  it("suspects the proxy after repeated refusals while HTTP works", async () => {
    setup();
    const radio = new RadioStore();
    radio.goLive();
    await settle();
    for (let i = 0; i < 3; i++) {
      expect(radio.get().error).toBeNull();
      FakeSocket.last().serverClose(1006);
      await settle();
      vi.advanceTimersByTime(2000); // the next attempt (backoff 0.5, 1, 2 s), well inside the 7 s connect timeout
    }
    expect(FakeSocket.instances).toHaveLength(4);
    expect(radio.get().error).toBe(PROXY_HINT);
  });

  it("drops a silent socket after 8 s and pings every 2 s meanwhile", async () => {
    const { radio, ws } = await goLive();
    ws.clear();
    vi.advanceTimersByTime(4000);
    expect(ws.types()).toEqual(["ping", "ping"]);
    ws.text({ type: "pong", t: performance.now() - 35, server_ms: 1 });
    expect(radio.get().rttMs).toBe(35);
    vi.advanceTimersByTime(9000);
    expect(ws.closedWith?.code).toBe(4000);
    expect(radio.get().conn).toBe("waiting");
    expect(radio.get().log.at(-1)).toMatchObject({ text: "Radio link lost", meta: "no reply from the server" });
  });

  it("abandons a connect that hangs for 7 s", async () => {
    const { radio, ws } = await goLive();
    ws.serverClose(1006);
    vi.advanceTimersByTime(500);
    const hung = FakeSocket.last();
    vi.advanceTimersByTime(8000);
    expect(hung.closedWith?.code).toBe(4000);
    expect(radio.get().log.at(-1)).toMatchObject({ text: "Cannot reach the radio", meta: "no answer to connect" });
  });

  it("reconnects at once when the browser comes back online", async () => {
    const { env } = await goLive();
    FakeSocket.last().serverClose(1011); // next try in 500 ms
    env.win.fire("online");
    expect(FakeSocket.instances).toHaveLength(2);
  });

  it("back in the foreground: wake lock and mic re-acquired, link probed, hello resent", async () => {
    const { radio, ws, env } = await goLive();
    env.doc.visibilityState = "hidden";
    env.doc.fire("visibilitychange");
    env.sentinels[0]?.release();
    expect(radio.get().wake).toBe("off");
    env.doc.visibilityState = "visible";
    ws.clear();
    env.doc.fire("visibilitychange");
    expect(env.nav.wakeLock?.request).toHaveBeenCalledTimes(2);
    expect(ws.types()).toContain("ping");
    await settle();
    expect(env.nav.mediaDevices.getUserMedia).toHaveBeenCalledTimes(2);
    expect(env.streams[0]?.track.stopped).toBe(true); // the old capture is closed first (iOS allows one)
    expect(ws.types()).toContain("hello");
    expect(radio.get().wake).toBe("on");
    // The probe window is short: no reply within 3 s (checked on the 1 s tick) drops the socket.
    vi.advanceTimersByTime(4000);
    expect(radio.get().conn).toBe("waiting");
  });
});

describe("log", () => {
  it("folds identical consecutive entries and keeps the newest LOG_MAX", async () => {
    const { radio, ws } = await goLive();
    ws.text({ type: "error", message: "boom" });
    ws.text({ type: "error", message: "boom" });
    expect(radio.get().log.at(-1)).toMatchObject({ text: "boom", count: 2 });
    for (let i = 0; i < LOG_MAX + 10; i++) ws.text({ type: "error", message: `e${i}` });
    expect(radio.get().log).toHaveLength(LOG_MAX);
    expect(radio.get().log.at(-1)?.text).toBe(`e${LOG_MAX + 9}`);
  });
});

// ------------------------------------------------------------------------------------ hands-free (lane handsfree)
// The store's side of hands-free (lib/handsfree.ts rules): settings, the energy VAD's `vad` frames (after the audio
// frame they confirm), suppression, the server's hands-free block and events, and the Bluetooth talk button.

describe("hands-free and the talk button (lane handsfree)", () => {
  const HF = {
    available: true,
    reason: null,
    armed: 1,
    scope: "stationary",
    active: true,
    paused: null,
    capturing: false,
    follow_up: false,
    wake_words: ["pitwall", "radio"],
    counts: { heard: 0, addressed: 0, ignored: 0, rejected: 0 },
  };
  const CONSENTED = { version: 2, handsFree: true, handsFreeConsent: true };
  const db = (v: number) => 10 ** (v / 20);

  /** Live with hands-free on (consent given) and a Mac that can do it; the VAD calibrated on a quiet room. */
  async function liveHandsFree(settings: object = CONSENTED, hf: object | null = HF) {
    const r = await goLive({ settings });
    if (hf) r.ws.text({ ...STATE, handsfree: hf });
    for (let i = 0; i < 31; i++) r.node.frame(db(-70));
    r.ws.clear();
    return r;
  }

  function vads(ws: FakeSocket): Record<string, unknown>[] {
    return ws.json().filter((m) => m.type === "vad");
  }

  it("stores the device settings, each validated; hands-free stays off without the privacy consent", () => {
    setup({ settings: { handsFree: true, wakeWord: "radio", talkButton: { kind: "key", code: "PageDown" } } });
    expect(loadSettings(false)).toMatchObject({
      handsFree: false,
      handsFreeConsent: false,
      wakeWord: "radio",
      talkButton: { kind: "key", code: "PageDown" },
    });
    setup({ settings: { handsFree: true, handsFreeConsent: true, wakeWord: "hey", talkButton: { kind: "key", code: "KeyA" } } });
    expect(loadSettings(false)).toMatchObject({ handsFree: true, handsFreeConsent: true, wakeWord: "pitwall", talkButton: null });
  });

  it("turning on needs the consent; then handsfree and wake_word go out with the settings and are stored", async () => {
    const { radio, ws, env } = await goLive();
    ws.clear();
    radio.setHandsFree(true);
    expect(ws.json()).toEqual([]);
    expect(radio.get().settings.handsFree).toBe(false);
    radio.acceptHandsFreeConsent();
    radio.setWakeWord("radio");
    radio.setWakeWord("radio"); // unchanged: nothing sent
    radio.setWakeWord("hey" as never);
    expect(ws.json()).toEqual([
      { type: "settings", voice_enabled: true, intensity: "normal", tts_mode: "server", handsfree: true, wake_word: "pitwall" },
      { type: "settings", voice_enabled: true, intensity: "normal", tts_mode: "server", handsfree: true, wake_word: "radio" },
    ]);
    expect(JSON.parse(env.local.getItem(SETTINGS_KEY) ?? "{}")).toMatchObject({
      handsFree: true,
      handsFreeConsent: true,
      wakeWord: "radio",
    });
    expect(radio.get().log.at(-1)?.text).toBe("Hands-free on");
    radio.setHandsFree(false);
    expect(ws.json().at(-1)).toMatchObject({ handsfree: false });
    expect(radio.get().handsFree.vad).toBe("off");
    radio.setHandsFree(true); // consent is remembered
    expect(ws.json().at(-1)).toMatchObject({ handsfree: true });
  });

  it("validates the server's hands-free block (a malformed one is dropped)", async () => {
    const { radio, ws } = await goLive();
    ws.text({ ...STATE, handsfree: { ...HF, scope: "driving", armed: 2 } });
    expect(radio.get().server?.handsfree).toMatchObject({ available: true, scope: "driving", armed: 2 });
    ws.text({ ...STATE, handsfree: "yes" });
    expect(radio.get().server && "handsfree" in radio.get().server!).toBe(false);
  });

  it("calibrates for a second, then sends vad start after the frame that confirmed it, and end after 0.7 s quiet", async () => {
    const { radio, ws, node } = await liveHandsFree();
    expect(radio.get().handsFree).toMatchObject({ vad: "listening", floorDb: -70, thresholdDb: -50 });
    for (let i = 0; i < 3; i++) node.frame(db(-30));
    expect(vads(ws)).toEqual([]);
    node.frame(db(-30));
    // ordered after the binary frame it confirms: the server's ring already holds it
    expect(ws.sent.at(-2)).toBeInstanceOf(ArrayBuffer);
    expect(JSON.parse(ws.sent.at(-1) as string)).toEqual({ type: "vad", state: "start", seq: 1 });
    expect(radio.get().handsFree.vad).toBe("speech");
    for (let i = 0; i < 21; i++) node.frame(db(-70));
    expect(vads(ws)).toHaveLength(1);
    node.frame(db(-70));
    expect(vads(ws).at(-1)).toEqual({ type: "vad", state: "end", seq: 1, reason: "silence" });
    for (let i = 0; i < 4; i++) node.frame(db(-30));
    expect(vads(ws).at(-1)).toEqual({ type: "vad", state: "start", seq: 2 });
  });

  it("the mic chip's local state: starting while calibrating after hands-free is turned on", async () => {
    const { radio, node } = await goLive({ settings: { version: 2, handsFreeConsent: true } });
    radio.setHandsFree(true);
    expect(radio.get().handsFree.vad).toBe("calibrating");
    for (let i = 0; i < 31; i++) node.frame(db(-70));
    expect(radio.get().handsFree.vad).toBe("listening");
  });

  it("no vad frames while hands-free is off here, on a Mac without hands-free, or when it is unavailable", async () => {
    for (const [settings, hf] of [
      [{ version: 2 }, HF],
      [CONSENTED, null],
      [CONSENTED, { ...HF, available: false, reason: "disabled" }],
    ] as const) {
      const { ws, node } = await liveHandsFree(settings, hf);
      for (let i = 0; i < 30; i++) node.frame(db(-30));
      expect(vads(ws)).toEqual([]);
      expect(ws.binaries().length).toBe(30); // the audio itself streams as always
    }
  });

  it("no segment while the engineer talks here, nor for 300 ms after", async () => {
    const { ws, node, ctx } = await liveHandsFree();
    sayAudio(ws, "m1", 2400, "answer", 24000);
    for (let i = 0; i < 10; i++) node.frame(db(-30)); // the AirPod hears the engineer
    expect(vads(ws)).toEqual([]);
    ctx.clips()[0]?.end();
    for (let i = 0; i < 10; i++) node.frame(db(-30));
    expect(vads(ws)).toEqual([]);
    vi.advanceTimersByTime(300);
    for (let i = 0; i < 4; i++) node.frame(db(-30));
    expect(vads(ws)).toEqual([{ type: "vad", state: "start", seq: 1 }]);
  });

  it("no segment while the server says it is speaking or busy, or a PTT is down anywhere", async () => {
    const { ws, node } = await liveHandsFree();
    for (const patch of [{ speaking: true }, { busy: true }, { ptt: true, ptt_source: "wheel" }]) {
      ws.text({ ...STATE, handsfree: HF, ...patch });
      for (let i = 0; i < 10; i++) node.frame(db(-30));
    }
    expect(vads(ws)).toEqual([]);
  });

  it("push-to-talk during a segment aborts it; the press itself goes out first", async () => {
    const { radio, ws, node } = await liveHandsFree();
    for (let i = 0; i < 4; i++) node.frame(db(-30));
    radio.pttPress();
    node.frame(db(-30));
    expect(ws.json().filter((m) => m.type === "vad" || m.type === "ptt")).toEqual([
      { type: "vad", state: "start", seq: 1 },
      { type: "ptt", down: true },
      { type: "vad", state: "abort", seq: 1, reason: "suppressed" },
    ]);
  });

  it("turning hands-free off during a segment aborts it", async () => {
    const { radio, ws, node } = await liveHandsFree();
    for (let i = 0; i < 4; i++) node.frame(db(-30));
    radio.setHandsFree(false);
    node.frame(db(-30));
    expect(vads(ws).at(-1)).toEqual({ type: "vad", state: "abort", seq: 1, reason: "suppressed" });
  });

  it("a mic that ends or is reopened during a segment aborts it at once (the server stops recording)", async () => {
    const { radio, ws, node, env } = await liveHandsFree();
    for (let i = 0; i < 4; i++) node.frame(db(-30));
    expect(vads(ws).at(-1)).toEqual({ type: "vad", state: "start", seq: 1 });
    env.streams[0]!.track.fire("ended");
    expect(vads(ws).at(-1)).toEqual({ type: "vad", state: "abort", seq: 1, reason: "mic" });
    await settle(); // re-acquired: a fresh capture, calibrated afresh, and no second abort for the same segment
    expect(radio.get().mic).toBe("live");
    expect(vads(ws).filter((m) => m.state === "abort")).toHaveLength(1);
    for (let i = 0; i < 31; i++) node.frame(db(-70));
    for (let i = 0; i < 4; i++) node.frame(db(-30));
    expect(vads(ws).at(-1)).toEqual({ type: "vad", state: "start", seq: 2 });
  });

  it("tallies the server's events; an addressed question is logged as a hands-free transcript", async () => {
    const { radio, ws, node } = await liveHandsFree();
    for (let i = 0; i < 4; i++) node.frame(db(-30));
    for (let i = 0; i < 22; i++) node.frame(db(-70));
    vi.advanceTimersByTime(400);
    ws.text({ type: "handsfree", event: "accepted", seq: 1 });
    ws.text({ type: "handsfree", event: "addressed", seq: 1, wake: "pitwall", audio_s: 2.2 });
    ws.text({ type: "transcript", text: "how's my fuel", stt_ms: 180, audio_s: 2.2, source: "handsfree", wake: "pitwall" });
    expect(radio.get().log.at(-1)).toMatchObject({
      kind: "transcript",
      text: "how's my fuel",
      meta: "hands-free · STT 180 ms · 2.2 s audio · +400 ms after you stopped",
    });
    ws.text({ type: "handsfree", event: "rejected", seq: 2, reason: "too_long", audio_s: 8.6 });
    expect(radio.get().handsFree.events).toEqual({ accepted: 1, rejected: 1, ignored: 0, addressed: 1, tooLong: 1 });
    expect(radio.get().handsFree.last).toMatchObject({ event: "rejected", reason: "too_long" });
  });

  it("ignored speech leaves nothing in the log", async () => {
    const { radio, ws } = await liveHandsFree();
    const before = radio.get().log.length;
    ws.text({ type: "handsfree", event: "ignored", seq: 1, reason: "not_addressed", audio_s: 1.4 });
    expect(radio.get().log).toHaveLength(before);
    expect(radio.get().handsFree.events.ignored).toBe(1);
  });

  it("talk button held: ptt down with source remote at once, the release after the hang time", async () => {
    const { radio, ws } = await goLive();
    ws.clear();
    radio.talkButtonDown();
    expect(ws.json()).toEqual([{ type: "ptt", down: true, source: "remote" }]);
    expect(radio.get()).toMatchObject({ pttHeld: true, handsFree: expect.objectContaining({ button: "held" }) });
    vi.advanceTimersByTime(500);
    radio.talkButtonUp();
    expect(radio.get().pttHeld).toBe(false);
    vi.advanceTimersByTime(250 + 150);
    expect(ws.json().at(-1)).toEqual({ type: "ptt", down: false });
    expect(radio.get().handsFree.button).toBe("off");
  });

  it("talk button tapped: stays on air until the driver goes quiet after speaking", async () => {
    const { radio, ws, node } = await liveHandsFree({ version: 2 });
    radio.talkButtonDown();
    vi.advanceTimersByTime(100);
    radio.talkButtonUp();
    expect(radio.get()).toMatchObject({ pttHeld: true, handsFree: expect.objectContaining({ button: "tap" }) });
    for (let i = 0; i < 30; i++) node.frame(db(-30)); // speaking
    for (let i = 0; i < 24; i++) node.frame(db(-70));
    expect(radio.get().pttHeld).toBe(true);
    node.frame(db(-70)); // 0.8 s quiet
    expect(radio.get().pttHeld).toBe(false);
    vi.advanceTimersByTime(250 + 150);
    expect(ws.json().filter((m) => m.type === "ptt")).toEqual([
      { type: "ptt", down: true, source: "remote" },
      { type: "ptt", down: false },
    ]);
  });

  it("talk button tapped and nothing said: released after 4 s; a second press ends a tap at once", async () => {
    const { radio, node } = await liveHandsFree({ version: 2 });
    radio.talkButtonDown();
    radio.talkButtonUp();
    for (let i = 0; i < 124; i++) node.frame(db(-70));
    expect(radio.get().pttHeld).toBe(true);
    node.frame(db(-70));
    expect(radio.get().pttHeld).toBe(false);
    vi.advanceTimersByTime(1000);
    radio.talkButtonDown();
    radio.talkButtonUp();
    expect(radio.get().handsFree.button).toBe("tap");
    vi.advanceTimersByTime(1000);
    radio.talkButtonDown(); // ends it
    expect(radio.get().pttHeld).toBe(false);
    expect(radio.get().handsFree.button).toBe("off");
    radio.talkButtonUp();
    expect(radio.get().pttHeld).toBe(false);
  });

  it("a tapped transmission ends after 12 s even without audio frames", async () => {
    const { radio, ws } = await goLive();
    radio.talkButtonDown();
    radio.talkButtonUp();
    for (let i = 0; i < 5; i++) {
      vi.advanceTimersByTime(2000);
      ws.text(STATE); // the link stays alive
    }
    vi.advanceTimersByTime(1999);
    expect(radio.get().pttHeld).toBe(true);
    vi.advanceTimersByTime(1);
    expect(radio.get().pttHeld).toBe(false);
  });

  it("the talk button does nothing while the radio is off, the link down, or the screen button holds the mic", async () => {
    const { radio, ws } = await goLive();
    radio.pttPress();
    ws.clear();
    radio.talkButtonDown();
    radio.talkButtonUp();
    expect(ws.json()).toEqual([]);
    radio.pttRelease(true);
    ws.serverClose(1006);
    radio.talkButtonDown();
    expect(radio.get().pttHeld).toBe(false);
    radio.stop();
    radio.talkButtonDown();
    expect(radio.get().pttHeld).toBe(false);
  });

  it("a dropped link ends a tapped transmission", async () => {
    const { radio, ws } = await goLive();
    radio.talkButtonDown();
    radio.talkButtonUp();
    ws.serverClose(1006);
    expect(radio.get()).toMatchObject({ pttHeld: false, handsFree: expect.objectContaining({ button: "off" }) });
  });

  it("stores the learned talk button (validated) and forgets it", async () => {
    const { radio, env } = await goLive();
    radio.setTalkButton({ kind: "gamepad", id: "Xbox Wireless Controller", button: 3 });
    expect(radio.get().settings.talkButton).toEqual({ kind: "gamepad", id: "Xbox Wireless Controller", button: 3 });
    expect(JSON.parse(env.local.getItem(SETTINGS_KEY) ?? "{}").talkButton).toEqual({
      kind: "gamepad",
      id: "Xbox Wireless Controller",
      button: 3,
    });
    radio.setTalkButton({ kind: "key", code: "KeyA" });
    expect(radio.get().settings.talkButton).toBeNull();
    radio.setTalkButton(null);
    expect(radio.get().settings.talkButton).toBeNull();
  });
});
