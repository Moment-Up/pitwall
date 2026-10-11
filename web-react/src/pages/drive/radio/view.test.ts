// Drive › Radio view models (design spec 5.3), against the Svelte RadioView's behaviour.
import { describe, expect, it } from "vitest";
import type { LogEntry, RadioServerState, RadioState } from "../../../lib/radio";
import { audioBlocked, cueModeView, goLiveNote, intensityOf, linkChip, logRows, quietText } from "./view";

const SERVER: RadioServerState = {
  ptt: false,
  listening: false,
  speaking: false,
  intensity: "detailed",
  stt: "parakeet",
  tts: "kokoro",
  telemetry: "live",
  ptt_source: null,
  cue_mode: "markers",
};

function state(over: Partial<RadioState> = {}): RadioState {
  return {
    phase: "live",
    conn: "open",
    mic: "live",
    micSilent: false,
    wake: "on",
    audio: "running",
    audioSession: "play-and-record",
    server: SERVER,
    current: null,
    speakingId: null,
    speaking: false,
    log: [],
    level: 0,
    rttMs: 23.6,
    pttHeld: false,
    settings: { voiceEnabled: true, intensity: "quiet", voiceSource: "server", deviceVoice: null, deviceRate: 1, version: 2 },
    error: null,
    serverVoiceTest: "idle",
    retryInS: null,
    stats: { contextRate: 48000, taps: 244, framesSent: 0, framesDropped: 0, bufferedBytes: 0 },
    deviceVoices: [],
    allVoices: [],
    micCapable: true,
    deviceTtsCapable: false,
    ...over,
  };
}

describe("link chip", () => {
  it.each([
    [{ phase: "idle" as const }, "Radio off", "default"],
    [{}, "Link · 24 ms", "success"],
    [{ rttMs: null }, "Link", "success"],
    [{ conn: "connecting" as const }, "Connecting…", "warning"],
    [{ conn: "waiting" as const, retryInS: 3 }, "Reconnecting in 3 s", "warning"],
    [{ conn: "waiting" as const }, "Reconnecting…", "warning"],
    [{ conn: "offline" as const }, "Offline", "default"],
  ])("%o -> %s", (over, label, tone) => {
    expect(linkChip(state(over))).toEqual({ label, tone });
  });
});

describe("quiet mode and audio", () => {
  it("quiet until a lap, indefinite, or none", () => {
    expect(quietText({ ...SERVER, quiet: { until_lap: 9 } })).toBe("Quiet until lap 9");
    expect(quietText({ ...SERVER, quiet: { indefinite: true } })).toBe("Quiet mode");
    expect(quietText({ ...SERVER, quiet: {} })).toBeNull();
    expect(quietText(null)).toBeNull();
  });

  it("audio paused only while live and the context is suspended", () => {
    expect(audioBlocked(state({ audio: "suspended" }))).toBe(true);
    expect(audioBlocked(state({ audio: "interrupted" }))).toBe(true);
    expect(audioBlocked(state({ audio: "running" }))).toBe(false);
    expect(audioBlocked(state({ audio: "none" }))).toBe(false);
    expect(audioBlocked(state({ phase: "idle", audio: "suspended" }))).toBe(false);
  });
});

describe("log", () => {
  const entry = (seq: number, at: number, over: Partial<LogEntry> = {}): LogEntry => ({
    seq,
    at,
    kind: "answer",
    text: `message ${seq}`,
    meta: "",
    id: null,
    count: 1,
    ...over,
  });

  it("newest first, folded repeats counted, ages like the strip", () => {
    const now = 1_000_000;
    const rows = logRows([entry(1, now - 125_000), entry(2, now - 8_000, { count: 3, kind: "cue" }), entry(3, now - 1_000, { meta: "listen-only" })], now);
    expect(rows.map((r) => r.seq)).toEqual([3, 2, 1]);
    expect(rows[0]).toMatchObject({ age: "now", count: null, meta: "listen-only" });
    expect(rows[1]).toMatchObject({ age: "8 s", count: "×3", kind: "cue", meta: null });
    expect(rows[2]!.age).toBe("2 min");
  });

  it("empty log, empty rows", () => {
    expect(logRows([], 0)).toEqual([]);
  });
});

describe("braking calls and coaching amount", () => {
  it("live: the server's mode, editable over the link", () => {
    expect(cueModeView(state(), "focus")).toMatchObject({ value: "markers", editable: true });
  });

  it("radio off: the live snapshot's mode, read only, says how to change it", () => {
    const v = cueModeView(state({ phase: "idle" }), "focus");
    expect(v).toMatchObject({ value: "focus", editable: false });
    expect(v.note).toContain("Go live");
  });

  it("link down: read only until it is back; unknown stays unknown", () => {
    expect(cueModeView(state({ conn: "waiting" }), null).editable).toBe(false);
    expect(cueModeView(state({ phase: "idle" }), "loud").value).toBeNull();
  });

  it("coaching amount: the server's while live, this device's setting otherwise", () => {
    expect(intensityOf(state())).toBe("detailed");
    expect(intensityOf(state({ phase: "idle" }))).toBe("quiet");
    expect(intensityOf(state({ server: null }))).toBe("quiet");
  });

  it("Go live explains what it starts; plain HTTP is listen-only", () => {
    expect(goLiveNote(true)).toContain("opens the microphone");
    expect(goLiveNote(false)).toContain("listen-only");
  });
});
