import { describe, expect, it, vi } from "vitest";
import type { RadioServerState, RadioState } from "../../lib/radio";
import {
  goLiveView,
  idleMessage,
  kindChip,
  messageAge,
  micChipView,
  pttView,
} from "./radio-view";
import { pttKeyHandlers, pttPressController, shallowEqual, type PttTarget } from "./useRadio";

const SERVER: RadioServerState = {
  ptt: false,
  listening: false,
  speaking: false,
  intensity: "normal",
  stt: "parakeet",
  tts: "kokoro",
  telemetry: "live",
  ptt_source: null,
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
    rttMs: 20,
    pttHeld: false,
    settings: { voiceEnabled: true, intensity: "normal", voiceSource: "server", deviceVoice: null, deviceRate: 1, version: 2 },
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

describe("kindChip", () => {
  it.each([
    ["answer", "ENGINEER", "ref"],
    ["lap_summary", "LAP", "accent"],
    ["cue", "CUE", "danger"],
    ["alert", "ALERT", "warning"],
    ["strategy", "STRATEGY", "ref"],
    ["car", "CAR", "ref"],
    ["goal", "GOAL", "success"],
    ["validation", "TEST", "default"],
    ["transcript", "YOU", "default"],
    ["you", "YOU", "default"],
    ["error", "ERROR", "danger"],
  ] as const)("%s -> %s (%s)", (kind, label, tone) => {
    expect(kindChip(kind)).toEqual({ label, tone });
  });

  it("a kind from a newer server is labelled INFO; a missing kind is a neutral RADIO chip", () => {
    expect(kindChip("brand_new_kind")).toEqual({ label: "INFO", tone: "default" });
    expect(kindChip("toString")).toEqual({ label: "INFO", tone: "default" }); // not an inherited property
    expect(kindChip(null)).toEqual({ label: "RADIO", tone: "default" });
    expect(kindChip(undefined)).toEqual({ label: "RADIO", tone: "default" });
  });
});

describe("messageAge", () => {
  const now = 1_000_000;
  it.each([
    [now, "now"],
    [now - 2999, "now"],
    [now - 8000, "8 s"],
    [now - 59_999, "59 s"],
    [now - 60_000, "1 min"],
    [now - 3_600_000, "1 h"],
    [now + 5000, "now"], // clock skew never shows a negative age
  ])("%d -> %s", (at, text) => {
    expect(messageAge(at, now)).toBe(text);
  });

  it("unknown time is -", () => {
    expect(messageAge(null, now)).toBe("-");
    expect(messageAge(Number.NaN, now)).toBe("-");
  });
});

describe("pttView", () => {
  it.each<[string, Partial<RadioState>, string, boolean]>([
    ["radio off", { phase: "idle" }, "Go live first", false],
    ["plain HTTP", { micCapable: false, mic: "unavailable" }, "Listen only", false],
    ["link down", { conn: "waiting" }, "Waiting for link…", false],
    ["mic opening", { mic: "requesting" }, "Opening mic…", false],
    ["mic denied", { mic: "denied" }, "Mic unavailable", false],
    ["ready", {}, "Hold to talk", true],
    ["muted track still keys (iOS)", { mic: "muted" }, "Hold to talk", true],
    ["held here", { pttHeld: true }, "Listening…", true],
    ["wheel", { server: { ...SERVER, ptt: true, ptt_source: "wheel" } }, "Wheel PTT…", true],
    ["engineer talking", { speaking: true }, "Hold to interrupt", true],
    ["hub speaking", { server: { ...SERVER, speaking: true } }, "Hold to interrupt", true],
  ])("%s -> %s", (_name, over, label, usable) => {
    const v = pttView(state(over));
    expect(v.label).toBe(label);
    expect(v.usable).toBe(usable);
  });

  it("short labels for the 128 px phone button", () => {
    expect(pttView(state()).shortLabel).toBe("Hold to talk");
    expect(pttView(state({ speaking: true })).shortLabel).toBe("Interrupt");
    expect(pttView(state({ conn: "waiting" })).shortLabel).toBe("No link");
    expect(pttView(state({ mic: "denied" })).shortLabel).toBe("No mic");
  });

  it("flags: on air, wheel, interrupt, listen-only", () => {
    expect(pttView(state({ pttHeld: true }))).toMatchObject({ active: true, wheel: false, interrupt: false });
    expect(pttView(state({ server: { ...SERVER, ptt: true, ptt_source: "wheel" } }))).toMatchObject({
      active: true,
      wheel: true,
    });
    expect(pttView(state({ speaking: true, pttHeld: true })).interrupt).toBe(false); // already on air
    expect(pttView(state({ micCapable: false })).listenOnly).toBe(true);
    expect(pttView(state({ micCapable: false, phase: "idle" })).listenOnly).toBe(false); // Go live shows instead
  });
});

describe("micChipView", () => {
  it.each<[string, Partial<RadioState>, string, string]>([
    ["radio off", { phase: "idle" }, "Radio off", "default"],
    ["on air", { pttHeld: true }, "On air", "accent"],
    ["on air from the wheel", { server: { ...SERVER, ptt: true, ptt_source: "wheel" } }, "On air · wheel", "accent"],
    ["connecting", { conn: "connecting", server: null }, "Connecting…", "warning"],
    ["reconnecting", { conn: "waiting", server: null, retryInS: 3 }, "Reconnecting · 3 s", "warning"],
    ["reconnecting, no countdown", { conn: "waiting", server: null }, "Reconnecting…", "warning"],
    ["mic live", {}, "Mic live", "success"],
    ["mic silent", { micSilent: true }, "Mic silent", "warning"],
    ["mic muted", { mic: "muted" }, "Mic muted", "warning"],
    ["opening", { mic: "requesting" }, "Opening mic…", "warning"],
    ["plain HTTP", { mic: "unavailable", micCapable: false }, "Listen only", "warning"],
    ["denied", { mic: "denied" }, "Mic blocked", "danger"],
    ["ended", { mic: "ended" }, "Mic lost", "danger"],
    ["error", { mic: "error" }, "Mic error", "danger"],
    ["off", { mic: "off" }, "Mic off", "default"],
  ])("%s -> %s", (_name, over, label, tone) => {
    const v = micChipView(state(over));
    expect(v.label).toBe(label);
    expect(v.tone).toBe(tone);
    expect(v.detail.length).toBeGreaterThan(0);
  });
});

describe("goLiveView and idle text", () => {
  it("Go live, Starting…, Listen only on plain HTTP", () => {
    expect(goLiveView({ phase: "idle", micCapable: true })).toEqual({ label: "Go live", starting: false, listenOnly: false });
    expect(goLiveView({ phase: "starting", micCapable: true })).toEqual({
      label: "Starting…",
      starting: true,
      listenOnly: false,
    });
    expect(goLiveView({ phase: "idle", micCapable: false })).toMatchObject({ label: "Listen only", listenOnly: true });
  });

  it("idle text: mockup copy while off, Radio quiet while live", () => {
    expect(idleMessage({ phase: "idle", micCapable: true })).toBe(
      "Radio is off. Tap Go live (iOS needs a tap to start audio and the mic).",
    );
    expect(idleMessage({ phase: "idle", micCapable: false })).toMatch(/Listen only/);
    expect(idleMessage({ phase: "live", micCapable: true })).toBe("Radio quiet");
  });
});

describe("shallowEqual", () => {
  it("compares one level deep", () => {
    expect(shallowEqual({ a: 1, b: "x" }, { a: 1, b: "x" })).toBe(true);
    expect(shallowEqual({ a: 1 }, { a: 2 })).toBe(false);
    expect(shallowEqual({ a: 1 }, { a: 1, b: 2 })).toBe(false);
    expect(shallowEqual({ a: {} }, { a: {} })).toBe(false);
    expect(shallowEqual(null, null)).toBe(true);
    expect(shallowEqual<unknown>(null, {})).toBe(false);
  });
});

// ------------------------------------------------------------------------------------------- controls logic

function fakeTarget(over: Partial<RadioState> = {}) {
  let s = state(over);
  const target: PttTarget & { set: (o: Partial<RadioState>) => void } = {
    get: () => s,
    pttPress: vi.fn(() => {
      s = { ...s, pttHeld: true };
    }),
    pttRelease: vi.fn(() => {
      s = { ...s, pttHeld: false };
    }),
    set: (o) => {
      s = { ...s, ...o };
    },
  };
  return target;
}

function key(type: "keydown" | "keyup", over: Partial<KeyboardEvent> = {}) {
  return {
    type,
    code: "Space",
    repeat: false,
    metaKey: false,
    ctrlKey: false,
    altKey: false,
    target: null,
    preventDefault: vi.fn(),
    stopPropagation: vi.fn(),
    ...over,
  } as unknown as KeyboardEvent;
}

describe("Space push-to-talk", () => {
  it("presses on keydown, ignores repeats, releases on keyup, and consumes both", () => {
    const t = fakeTarget();
    const h = pttKeyHandlers(t);
    const down = key("keydown");
    h.keydown(down);
    h.keydown(key("keydown", { repeat: true }));
    expect(t.pttPress).toHaveBeenCalledTimes(1);
    expect(down.preventDefault).toHaveBeenCalled();
    expect(down.stopPropagation).toHaveBeenCalled();
    const up = key("keyup");
    h.keyup(up);
    expect(t.pttRelease).toHaveBeenCalledTimes(1);
    expect(up.preventDefault).toHaveBeenCalled();
  });

  it("leaves Space alone when PTT is unusable, for other keys and with modifiers", () => {
    const t = fakeTarget({ conn: "waiting" });
    const h = pttKeyHandlers(t);
    const e = key("keydown");
    h.keydown(e);
    expect(e.preventDefault).not.toHaveBeenCalled();
    t.set({ conn: "open" });
    h.keydown(key("keydown", { code: "KeyA" }));
    h.keydown(key("keydown", { metaKey: true }));
    expect(t.pttPress).not.toHaveBeenCalled();
    h.keyup(key("keyup")); // nothing held: nothing released
    expect(t.pttRelease).not.toHaveBeenCalled();
  });

  it("release() (window blur) lets go of a held key once", () => {
    const t = fakeTarget();
    const h = pttKeyHandlers(t);
    h.keydown(key("keydown"));
    h.release();
    h.release();
    h.keyup(key("keyup"));
    expect(t.pttRelease).toHaveBeenCalledTimes(1);
  });
});

describe("PushToTalkButton press logic", () => {
  it("keys on press start and releases on press end, once", () => {
    const t = fakeTarget();
    const p = pttPressController(t);
    p.start();
    p.start();
    p.end();
    p.end();
    expect(t.pttPress).toHaveBeenCalledTimes(1);
    expect(t.pttRelease).toHaveBeenCalledTimes(1);
  });

  it("does not key when unusable, and never releases a press another control started", () => {
    const t = fakeTarget({ mic: "denied" });
    const p = pttPressController(t);
    p.start();
    expect(t.pttPress).not.toHaveBeenCalled();
    t.set({ mic: "live", pttHeld: true }); // held by the Space key
    p.end();
    expect(t.pttRelease).not.toHaveBeenCalled();
  });
});
