// Hands-free and the talk button in words (lane handsfree): the mic chip's order and labels for every hands-free
// state, the mini bar prefix, the Drive switch and its note, the consent text, diagnostics, and the talk-button
// bindings (key and controller) against a fake store.

import { describe, expect, it, vi } from "vitest";
import frames from "../../test/fixtures/handsfree/server-frames.json";
import { HANDS_FREE_IDLE, parseHandsFreeState, type HandsFreeLocal, type PadLike } from "../../lib/handsfree";
import type { RadioServerState, RadioSettings, RadioState } from "../../lib/radio";
import {
  consentText,
  handsFreeChipState,
  handsFreeDiagRows,
  handsFreeNote,
  handsFreeSwitchView,
  miniBarPrefix,
  talkButtonHint,
  unavailableText,
} from "./handsfree-view";
import { micChipView } from "./radio-view";
import { padTalkPoller, talkKeyHandlers, type TalkTarget } from "./useRadio";

type HfName = keyof typeof frames.handsfree;
const hf = (name: HfName) => parseHandsFreeState(frames.handsfree[name])!;

const SERVER: RadioServerState = {
  ptt: false,
  listening: false,
  speaking: false,
  intensity: "normal",
  stt: "parakeet",
  tts: "kokoro",
  telemetry: "live",
  ptt_source: null,
  handsfree: hf("listening"),
};

const SETTINGS: RadioSettings = {
  voiceEnabled: true,
  intensity: "normal",
  voiceSource: "server",
  deviceVoice: null,
  deviceRate: 1,
  version: 2,
  handsFree: true,
  wakeWord: "pitwall",
  handsFreeConsent: true,
  talkButton: null,
};

const LISTENING: HandsFreeLocal = { ...HANDS_FREE_IDLE, vad: "listening", floorDb: -68, thresholdDb: -50 };

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
    level: 0.5,
    rttMs: 20,
    pttHeld: false,
    settings: SETTINGS,
    error: null,
    serverVoiceTest: "idle",
    retryInS: null,
    stats: { contextRate: 48000, taps: 244, framesSent: 0, framesDropped: 0, bufferedBytes: 0 },
    deviceVoices: [],
    allVoices: [],
    micCapable: true,
    deviceTtsCapable: false,
    handsFree: LISTENING,
    ...over,
  };
}

const withHf = (name: HfName, over: Partial<RadioState> = {}) => state({ server: { ...SERVER, handsfree: hf(name) }, ...over });

describe("micChipView with hands-free (order: on air, link, mic problem, hands-free, Mic live)", () => {
  it.each<[string, RadioState, string, string]>([
    ["listening", state(), 'Listening for "Pitwall"', "accent"],
    ["listening for Radio", state({ settings: { ...SETTINGS, wakeWord: "radio" } }), 'Listening for "Radio"', "accent"],
    ["calibrating", state({ handsFree: { ...LISTENING, vad: "calibrating" } }), "Hands-free starting…", "default"],
    ["not armed on the Mac yet", withHf("not_armed"), "Hands-free starting…", "default"],
    ["hearing (server capturing)", withHf("capturing"), "Hearing you…", "accent"],
    ["hearing (local speech)", state({ handsFree: { ...LISTENING, vad: "speech" } }), "Hearing you…", "accent"],
    ["follow-up", withHf("follow_up"), "Go ahead…", "accent"],
    ["paused while driving", withHf("paused_moving"), "Hands-free paused · driving", "default"],
    ["too noisy", state({ handsFree: { ...LISTENING, vad: "noisy" } }), "Hands-free · too noisy", "warning"],
    ["unavailable", withHf("unavailable_env"), "Hands-free unavailable", "warning"],
    ["a Mac without hands-free", state({ server: { ...SERVER, handsfree: undefined } }), "Hands-free unavailable", "warning"],
    ["hands-free off here", state({ settings: { ...SETTINGS, handsFree: false } }), "Mic live", "success"],
    ["no consent (never on)", state({ settings: { ...SETTINGS, handsFreeConsent: false } }), "Mic live", "success"],
    // what comes first
    ["on air beats hands-free", state({ pttHeld: true }), "On air", "accent"],
    ["the talk button", state({ pttHeld: true, handsFree: { ...LISTENING, button: "tap" } }), "On air · button", "accent"],
    [
      "another device's talk button",
      state({ server: { ...SERVER, ptt: true, ptt_source: "remote" } }),
      "On air · button",
      "accent",
    ],
    ["the wheel", state({ server: { ...SERVER, ptt: true, ptt_source: "wheel" } }), "On air · wheel", "accent"],
    ["link down beats hands-free", state({ conn: "waiting", server: null }), "Reconnecting…", "warning"],
    ["a muted mic beats hands-free", state({ mic: "muted" }), "Mic muted", "warning"],
    ["a silent mic beats hands-free", state({ micSilent: true }), "Mic silent", "warning"],
    ["radio off", state({ phase: "idle" }), "Radio off", "default"],
  ])("%s -> %s", (_name, s, label, tone) => {
    const v = micChipView(s);
    expect(v.label).toBe(label);
    expect(v.tone).toBe(tone);
    expect(v.detail.length).toBeGreaterThan(0);
  });

  it("only hearing pulses", () => {
    expect(micChipView(withHf("capturing")).pulse).toBe(true);
    expect(micChipView(state()).pulse).toBeFalsy();
  });

  it("unavailable explains why in the detail", () => {
    expect(micChipView(withHf("unavailable_env")).detail).toContain("PITWALL_VOICE_HANDSFREE=false");
    expect(micChipView(withHf("unavailable_sentence")).detail).toBe("Needs speech recognition: no speech recognition engine on the server.");
    expect(micChipView(state({ server: { ...SERVER, handsfree: undefined } })).detail).toContain("update Pitwall");
  });
});

describe("unavailableText", () => {
  it("the server's sentence, capitalised; a bare code in brackets", () => {
    expect(unavailableText("Speech recognition is downloading.")).toBe("Speech recognition is downloading.");
    expect(unavailableText("switched off on the server (PITWALL_VOICE_HANDSFREE=false)")).toBe(
      "Switched off on the server (PITWALL_VOICE_HANDSFREE=false).",
    );
    expect(unavailableText("odd_code")).toBe("The Mac cannot listen hands-free right now (odd_code).");
    expect(unavailableText(null)).toBe("The Mac cannot listen hands-free right now.");
  });
});

describe("mini radio bar prefix", () => {
  it("LISTENING (accent) while hands-free listens or hears; RADIO otherwise", () => {
    expect(miniBarPrefix(state())).toEqual({ label: "LISTENING", tone: "accent" });
    expect(miniBarPrefix(withHf("capturing"))).toEqual({ label: "LISTENING", tone: "accent" });
    expect(miniBarPrefix(withHf("follow_up"))).toEqual({ label: "LISTENING", tone: "accent" });
    for (const s of [
      withHf("paused_moving"),
      withHf("unavailable_env"),
      state({ handsFree: { ...LISTENING, vad: "calibrating" } }),
      state({ settings: { ...SETTINGS, handsFree: false } }),
      state({ micSilent: true }),
    ]) {
      expect(miniBarPrefix(s)).toEqual({ label: "RADIO", tone: "success" });
    }
  });
});

describe("Drive › Radio switch and its note", () => {
  it("off: says what it would do", () => {
    const v = handsFreeSwitchView(state({ settings: { ...SETTINGS, handsFree: false } }));
    expect(v).toMatchObject({ on: false, disabled: false, consented: true, label: "Hands-free (say 'Pitwall')", warn: false });
    expect(v.note).toContain('start with "Pitwall"');
  });

  it("no microphone: disabled, and says why", () => {
    const v = handsFreeSwitchView(state({ micCapable: false, mic: "unavailable" }));
    expect(v).toMatchObject({ on: false, disabled: true, warn: true });
    expect(v.note).toContain("HTTPS");
  });

  it.each<[string, RadioState, RegExp, boolean]>([
    ["stopped only", state(), /while the car is stopped/, false],
    ["also while driving", withHf("driving"), /on track too/, false],
    ["paused while driving", withHf("paused_moving"), /Paused while you drive/, false],
    ["unavailable", withHf("unavailable_env"), /Switched off on the server/, true],
    ["a Mac without hands-free", state({ server: { ...SERVER, handsfree: undefined } }), /no hands-free yet/, true],
    ["radio off", state({ phase: "idle", conn: "offline", server: null }), /listens while the radio is live/, false],
    ["link down", state({ conn: "waiting", server: null }), /waiting for the radio link/, false],
  ])("on, %s", (_n, s, text, warn) => {
    const n = handsFreeNote(s);
    expect(n.text).toMatch(text);
    expect(n.warn).toBe(warn);
  });

  it("with the radio off, an unavailable Mac (from GET /api/voice/status) is said at once", () => {
    const n = handsFreeNote(state({ phase: "idle", conn: "offline", server: null }), hf("unavailable_env"));
    expect(n).toMatchObject({ warn: true });
    expect(n.text).toContain("PITWALL_VOICE_HANDSFREE");
  });

  it("the label follows the wake word", () => {
    expect(handsFreeSwitchView(state({ settings: { ...SETTINGS, wakeWord: "radio" } })).label).toBe("Hands-free (say 'Radio')");
  });
});

describe("consent and the talk button's words", () => {
  it("the privacy note names the device and the wake word, and says nothing else is kept", () => {
    const t = consentText("iPad", "pitwall");
    expect(t.title).toBe("Turn on hands-free?");
    expect(t.body).toContain("this iPad listens for speech");
    expect(t.body).toContain('starts with "Pitwall"');
    expect(t.body).toContain("never shown, saved or logged");
    expect(t.body).toContain("only listens while the car is stopped");
    expect([t.accept, t.decline]).toEqual(["Turn on", "Not now"]);
    expect(consentText("device", "radio").body).toContain('starts with "Radio"');
  });

  it("the talk button hint: what to use, or the learned button and how it works", () => {
    expect(talkButtonHint(null)).toContain("AirPods taps and headphone play buttons can't reach a web page");
    expect(talkButtonHint({ kind: "key", code: "PageDown" })).toMatch(/^Page Down\. Hold it to talk, or tap it once/);
  });
});

describe("hands-free diagnostics", () => {
  it("level, floor and threshold in dB, the Mac's side and the counts", () => {
    const s = state({
      handsFree: {
        ...LISTENING,
        events: { accepted: 2, rejected: 1, ignored: 1, addressed: 1, tooLong: 1 },
        last: { event: "rejected", reason: "too_long", at: 10_000 },
      },
      settings: { ...SETTINGS, talkButton: { kind: "key", code: "PageDown" } },
    });
    const rows = Object.fromEntries(handsFreeDiagRows(s, 15_000).map((r) => [r.label, r.value]));
    expect(rows["Hands-free (this device)"]).toBe("listening · level -30 dB · floor -68 dB · threshold -50 dB");
    expect(rows["Hands-free (Mac)"]).toBe("available · 1 device on · stopped only");
    expect(rows["Hands-free counts"]).toBe("heard 3 · answered 1 · ignored 2 · not taken 0 · too long 1");
    expect(rows["Hands-free last event"]).toBe("not taken (too_long) · 5 s ago");
    expect(rows["Talk button"]).toBe("Page Down");
  });

  it("radio off and hands-free off: nothing guessed", () => {
    const rows = Object.fromEntries(
      handsFreeDiagRows(state({ phase: "idle", conn: "offline", server: null, settings: { ...SETTINGS, handsFree: false }, handsFree: HANDS_FREE_IDLE }), 0).map(
        (r) => [r.label, r.value],
      ),
    );
    expect(rows).toMatchObject({
      "Hands-free (this device)": "Off",
      "Hands-free (Mac)": "-",
      "Hands-free last event": "-",
      "Talk button": "None",
    });
  });

  it("a Mac without hands-free says so", () => {
    const rows = handsFreeDiagRows(state({ server: { ...SERVER, handsfree: undefined } }), 0);
    expect(rows.find((r) => r.label === "Hands-free (Mac)")?.value).toBe("not supported by this Mac");
  });
});

describe("chip state helper", () => {
  it("is null whenever hands-free does not apply", () => {
    expect(handsFreeChipState(state({ phase: "idle" }))).toBeNull();
    expect(handsFreeChipState(state({ conn: "connecting" }))).toBeNull();
    expect(handsFreeChipState(state({ server: null }))).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------- bindings

function fakeTarget(over: Partial<RadioState> = {}): TalkTarget & { calls: string[] } {
  const calls: string[] = [];
  return {
    calls,
    get: () => state(over),
    talkButtonDown: vi.fn(() => calls.push("down")),
    talkButtonUp: vi.fn(() => calls.push("up")),
  };
}

function keyEvent(code: string, extra: Partial<KeyboardEvent> = {}) {
  return { code, repeat: false, metaKey: false, ctrlKey: false, altKey: false, target: null, preventDefault: vi.fn(), stopPropagation: vi.fn(), ...extra } as unknown as KeyboardEvent;
}

describe("talkKeyHandlers (a learned key)", () => {
  it("down on keydown (not repeats), up on keyup; only that key is consumed", () => {
    const t = fakeTarget();
    const h = talkKeyHandlers("PageDown", t);
    const other = keyEvent("ArrowDown");
    h.keydown(other);
    expect(other.preventDefault).not.toHaveBeenCalled();
    const d = keyEvent("PageDown");
    h.keydown(d);
    expect(d.preventDefault).toHaveBeenCalled();
    h.keydown(keyEvent("PageDown", { repeat: true }));
    h.keyup(keyEvent("PageDown"));
    expect(t.calls).toEqual(["down", "up"]);
  });

  it("ignored with a modifier or while the radio cannot talk; release lets go of a held key", () => {
    const off = fakeTarget({ phase: "idle" });
    talkKeyHandlers("PageDown", off).keydown(keyEvent("PageDown"));
    talkKeyHandlers("PageDown", off).keydown(keyEvent("PageDown", { metaKey: true }));
    expect(off.calls).toEqual([]);
    const t = fakeTarget();
    const h = talkKeyHandlers("F13", t);
    h.keydown(keyEvent("F13"));
    h.release();
    h.release();
    expect(t.calls).toEqual(["down", "up"]);
  });
});

function pad(down: number[] = [], id = "Xbox Wireless Controller"): PadLike {
  return { id, index: 0, connected: true, buttons: Array.from({ length: 17 }, (_, i) => ({ pressed: down.includes(i) })) };
}

describe("padTalkPoller (a learned controller button)", () => {
  it("edges of the learned button drive the store; other buttons and controllers do nothing", () => {
    const t = fakeTarget();
    let pads: PadLike[] = [pad()];
    let hidden = false;
    const p = padTalkPoller({ kind: "gamepad", id: "Xbox Wireless Controller", button: 3 }, t, () => pads, () => hidden);
    p.tick();
    pads = [pad([0]), pad([3], "Other pad")];
    p.tick();
    expect(t.calls).toEqual([]);
    pads = [pad([3])];
    p.tick();
    p.tick();
    pads = [pad()];
    p.tick();
    expect(t.calls).toEqual(["down", "up"]);
    pads = [pad([3])];
    p.tick();
    hidden = true;
    p.tick(); // page hidden: let go
    expect(t.calls).toEqual(["down", "up", "down", "up"]);
    hidden = false;
    p.tick(); // still held when the page comes back: not a new press
    expect(t.calls).toHaveLength(4);
  });

  it("survives a browser that throws from getGamepads", () => {
    const t = fakeTarget();
    const p = padTalkPoller({ kind: "gamepad", id: "X", button: 0 }, t, () => {
      throw new Error("blocked");
    }, () => false);
    expect(() => p.tick()).not.toThrow();
  });
});
