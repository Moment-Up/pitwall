import { describe, expect, it } from "vitest";
import type { VoiceStatus } from "../../../lib/endpoints/settings";
import type { DeviceVoice, RadioServerState } from "../../../lib/radio";
import {
  COACHING,
  CUE_MODES,
  coachingIn,
  currentDeviceVoice,
  deviceNoun,
  deviceVoiceLabel,
  diagnosticsRows,
  diagnosticsSummary,
  followsDriverNote,
  isCueMode,
  linkBanner,
  linkState,
  macState,
  macVoiceLabel,
  macVoiceView,
  sourceHint,
  speedText,
  testVoiceView,
  thisDevice,
  voiceHint,
  voiceOn,
} from "./model";

const SERVER: RadioServerState = {
  ptt: false,
  listening: false,
  speaking: false,
  intensity: "detailed",
  voice_enabled: false,
  stt: "parakeet",
  tts: "kokoro",
  tts_voice: "bm_george",
  tts_voices: ["bm_fable", "bm_george", "bf_emma", "bf_isabella"],
  tts_active: "kokoro",
  tts_ready: true,
  tts_neural: true,
  tts_status: "ready",
  cue_mode: "markers",
  telemetry: "live",
  ptt_source: null,
};

/** A read-only GET /api/voice/status as the live service answered it (2026-10-11, no radio connected). */
const STATUS: VoiceStatus = {
  enabled: true,
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
  telemetry: "no_data",
  cue_mode: "focus",
  clients: [],
};

const voice = (name: string, quality: DeviceVoice["quality"], lang = "en-GB"): DeviceVoice => ({
  uri: `com.apple.voice.${quality}.${lang}.${name}`,
  name,
  lang,
  quality,
});

describe("choices", () => {
  it("braking calls: Off, Focus, Markers, All with a hint each", () => {
    expect(CUE_MODES.map((m) => m.label)).toEqual(["Off", "Focus", "Markers", "All"]);
    for (const m of CUE_MODES) expect(m.hint.length).toBeGreaterThan(10);
    expect(isCueMode("focus")).toBe(true);
    expect(isCueMode("loud")).toBe(false);
    expect(isCueMode(null)).toBe(false);
  });

  it("coaching: the driver profile's three levels", () => {
    expect(COACHING.map((c) => c.label)).toEqual(["Quiet", "Normal", "Detailed"]);
    expect(COACHING[0]?.hint).toBe("Alerts and answers only: flags, penalties, damage.");
    // the amount also sets the race calls a lap (voice/scheduler.py RACE_PER_LAP): the hints say so
    expect(COACHING[1]?.hint).toMatch(/2 race calls a lap/);
    expect(COACHING[2]?.hint).toMatch(/3 race calls a lap/);
  });
});

describe("labels", () => {
  it("names the device in the driver's hand, never 'This Mac'", () => {
    expect(deviceNoun("Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X)", 5)).toBe("iPad");
    expect(deviceNoun("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari", 5)).toBe("iPad"); // iPadOS desktop UA
    expect(deviceNoun("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari", 0)).toBe("device");
    expect(deviceNoun("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)", 5)).toBe("iPhone");
    expect(thisDevice("iPad")).toBe("This iPad");
    expect(thisDevice("device")).toBe("This device");
  });

  it("Kokoro voices read as names; unknown ids stay as sent", () => {
    expect(macVoiceLabel("bm_fable")).toBe("Fable · British male");
    expect(macVoiceLabel("bm_george")).toBe("George · British male");
    expect(macVoiceLabel("bf_emma")).toBe("Emma · British female");
    expect(macVoiceLabel("bf_isabella")).toBe("Isabella · British female");
    expect(macVoiceLabel("am_adam")).toBe("am_adam");
    expect(macVoiceLabel(null)).toBe("System default");
  });

  it("device voices carry their quality once", () => {
    expect(deviceVoiceLabel(voice("Jamie", "premium"))).toBe("Jamie (Premium) · en-GB");
    expect(deviceVoiceLabel(voice("Serena (Premium)", "premium"))).toBe("Serena (Premium) · en-GB");
    expect(deviceVoiceLabel(voice("Daniel", "standard"))).toBe("Daniel · en-GB");
    expect(deviceVoiceLabel(voice("Kate", "enhanced"))).toBe("Kate (Enhanced) · en-GB");
  });

  it("the device voice in use: the chosen one if installed, else the best", () => {
    const list = [voice("Jamie", "premium"), voice("Daniel", "standard")];
    expect(currentDeviceVoice(list, list[1]!.uri)).toBe(list[1]!.uri);
    expect(currentDeviceVoice(list, "gone")).toBe(list[0]!.uri);
    expect(currentDeviceVoice(list, null)).toBe(list[0]!.uri);
    expect(currentDeviceVoice([], null)).toBeNull();
  });

  it("speed as 1.05×, unknown as -", () => {
    expect(speedText(1)).toBe("1.00×");
    expect(speedText(1.05)).toBe("1.05×");
    expect(speedText(Number.NaN)).toBe("-");
  });
});

describe("macState", () => {
  it("prefers the live link's state frame", () => {
    const m = macState(SERVER, STATUS);
    expect(m?.from).toBe("radio");
    expect(m?.cue_mode).toBe("markers");
    expect(m?.intensity).toBe("detailed");
    expect(m?.voice_enabled).toBe(false);
  });

  it("falls back to the HTTP status while the link is down", () => {
    const m = macState(null, STATUS);
    expect(m?.from).toBe("status");
    expect(m?.tts_voice).toBe("bm_george");
    expect(m?.tts_voices).toEqual(["bm_fable", "bm_george", "bf_emma", "bf_isabella"]);
    expect(m?.cue_mode).toBe("focus");
    expect(m?.telemetry).toBe("no_data");
  });

  it("is unknown when the hub is off, not read yet, or malformed (never guessed)", () => {
    expect(macState(null, { enabled: false })).toBeNull();
    expect(macState(null, undefined)).toBeNull();
    expect(macState(null, { enabled: true })).toBeNull();
    const odd = macState(null, { enabled: true, tts: "kokoro", cue_mode: "loud", intensity: "max", tts_voices: "x" as unknown as string[] });
    expect(odd?.cue_mode).toBeUndefined();
    expect(odd?.intensity).toBeNull();
    expect(odd?.tts_voices).toEqual([]);
  });
});

describe("macVoiceView", () => {
  it("natural voice ready", () => {
    expect(macVoiceView(SERVER)).toEqual({
      chip: "Kokoro · bm_george",
      note: "Natural voice (Kokoro): George · British male.",
      warn: false,
      off: false,
    });
  });

  it("fallbacks while Kokoro starts, restarts or is missing", () => {
    expect(macVoiceView({ ...SERVER, tts_ready: false, tts_status: "starting", tts_active: "say" }).note).toBe(
      "The natural voice is starting; the macOS voice speaks meanwhile.",
    );
    expect(macVoiceView({ ...SERVER, tts_ready: false, tts_status: "restarting", tts_active: undefined }).note).toBe(
      "The natural voice is restarting; messages are text only meanwhile.",
    );
    const missing = macVoiceView({ ...SERVER, tts_ready: false, tts_status: "unavailable", tts_active: "say" });
    expect(missing.note).toContain("not installed on the Mac (run scripts/setup-tts.sh)");
    expect(missing.warn).toBe(true);
  });

  it("no voice, and the macOS voice", () => {
    expect(macVoiceView({ ...SERVER, tts: "none" })).toMatchObject({ off: true, warn: true });
    expect(macVoiceView({ ...SERVER, tts: "say", tts_voice: "Daniel" }).note).toBe("macOS voice: Daniel.");
    expect(macVoiceView({ ...SERVER, tts: "say", tts_voice: null }).note).toBe("macOS voice: system default.");
  });
});

describe("the radio link", () => {
  it("linkState", () => {
    expect(linkState({ phase: "idle", conn: "offline" })).toBe("off");
    expect(linkState({ phase: "starting", conn: "connecting" })).toBe("starting");
    expect(linkState({ phase: "live", conn: "connecting" })).toBe("connecting");
    expect(linkState({ phase: "live", conn: "waiting" })).toBe("reconnecting");
    expect(linkState({ phase: "live", conn: "open" })).toBe("open");
  });

  it("radio off: says why the Mac's settings are locked and offers Go live", () => {
    const b = linkBanner({ link: "off", retryInS: null, error: null, voiceDisabled: false });
    expect(b?.title).toBe("The radio is off");
    expect(b?.text).toContain("go live to change them");
    expect(b?.goLive).toBe(true);
  });

  it("no banner while the link is up; voice disabled on the Mac wins and offers nothing", () => {
    expect(linkBanner({ link: "open", retryInS: null, error: null, voiceDisabled: false })).toBeNull();
    const off = linkBanner({ link: "off", retryInS: null, error: null, voiceDisabled: true });
    expect(off).toMatchObject({ tone: "danger", goLive: false, title: "Voice is off on the Mac" });
    expect(off?.text).toContain("PITWALL_VOICE_ENABLED");
  });

  it("reconnecting with its countdown; a store error is shown as it is", () => {
    expect(linkBanner({ link: "reconnecting", retryInS: 3, error: null, voiceDisabled: false })?.title).toBe(
      "Radio link lost · retrying in 3 s",
    );
    const e = linkBanner({ link: "off", retryInS: null, error: "Access denied: …", voiceDisabled: false });
    expect(e).toMatchObject({ tone: "warning", text: "Access denied: …", goLive: true });
  });
});

describe("testVoiceView", () => {
  const base = { source: "server" as const, deviceTtsCapable: true, noun: "iPad" as const, link: "open" as const, macOff: false, serverVoiceTest: "idle" as const };

  it("this device's voice works without the link", () => {
    expect(testVoiceView({ ...base, source: "device", link: "off" })).toEqual({
      target: "device",
      enabled: true,
      hint: "Says a radio check with this iPad's voice.",
      warn: false,
    });
  });

  it("the Mac's voice needs the link and plays on every radio", () => {
    expect(testVoiceView({ ...base, link: "off" })).toMatchObject({ target: "server", enabled: false });
    expect(testVoiceView(base).hint).toBe("The Mac says a radio check on every connected radio.");
    expect(testVoiceView({ ...base, serverVoiceTest: "sent" }).hint).toMatch(/^Sent/);
    expect(testVoiceView({ ...base, serverVoiceTest: "failed" })).toMatchObject({ warn: true });
    expect(testVoiceView({ ...base, macOff: true })).toMatchObject({ enabled: false, warn: true });
  });

  it("a browser without Web Speech always tests the Mac's voice", () => {
    expect(testVoiceView({ ...base, source: "device", deviceTtsCapable: false }).target).toBe("server");
  });
});

describe("values in effect", () => {
  const live = macState(SERVER, undefined);
  const http = macState(null, STATUS);

  it("while live, the Mac's values (a driver change may have set them)", () => {
    expect(voiceOn("open", live, true)).toBe(false);
    expect(coachingIn("open", live, "quiet")).toBe("detailed");
  });

  it("with the radio off, this device's values (sent when the radio goes live)", () => {
    expect(voiceOn("off", http, true)).toBe(true);
    expect(coachingIn("off", http, "quiet")).toBe("quiet");
    expect(voiceOn("off", null, false)).toBe(false);
  });

  it("hints", () => {
    expect(voiceHint(true)).toBe("The engineer speaks on the radio.");
    expect(voiceHint(false)).toMatch(/^Answers only/);
    expect(sourceHint("device", "iPad", true)).toBe("This iPad speaks the messages with its own voice.");
    expect(sourceHint("server", "iPhone", true)).toBe("The Mac's voice plays on this iPhone.");
    expect(sourceHint("device", "device", false)).toMatch(/cannot speak/);
    expect(followsDriverNote(false)).toBeNull();
    expect(followsDriverNote(true)).toContain("Settings › Drivers");
  });
});

describe("diagnostics", () => {
  const state: Parameters<typeof diagnosticsRows>[0] = {
    phase: "live",
    conn: "open",
    retryInS: null,
    rttMs: 23.4,
    wake: "on",
    audio: "running",
    audioSession: "play-and-record",
    server: { ...SERVER, ptt_source: "wheel" },
    stats: { contextRate: 48000, taps: 244, framesSent: 1200, framesDropped: 3, bufferedBytes: 0 },
    deviceVoices: [voice("Jamie", "premium")],
    allVoices: [
      { name: "Jamie", lang: "en-GB", uri: "a", local: true, default: false },
      { name: "Thomas", lang: "fr-FR", uri: "b", local: true, default: false },
    ],
    deviceTtsCapable: true,
  };

  it("lists the link, mic, screen, audio, capture, engines and voices in words", () => {
    const rows = Object.fromEntries(diagnosticsRows(state, macState(state.server, undefined), "Mic live").map((r) => [r.label, r.value]));
    expect(rows["Radio link"]).toBe("Up · 23 ms round trip");
    expect(rows["Microphone"]).toBe("Mic live");
    expect(rows["Screen"]).toBe("Kept awake");
    expect(rows["Audio"]).toBe("running · session play-and-record");
    expect(rows["Mic audio"]).toBe("48000 Hz → 16 kHz · 244-tap filter · 1200 frames sent · 3 dropped");
    expect(rows["Speech to text (Mac)"]).toBe("parakeet");
    expect(rows["Mac voice"]).toBe("Kokoro · bm_george. Natural voice (Kokoro): George · British male.");
    expect(rows["Telemetry (Mac)"]).toBe("Live");
    expect(rows["Push to talk"]).toBe("wheel");
    expect(rows["Voices in this browser"]).toBe("1 English to choose from · 1 English of 2 in total");
  });

  it("unknown is '-' before Go live", () => {
    const idle: Parameters<typeof diagnosticsRows>[0] = {
      ...state,
      phase: "idle",
      conn: "offline",
      rttMs: null,
      wake: "off",
      audio: "none",
      audioSession: "unset",
      server: null,
      stats: { contextRate: 0, taps: 0, framesSent: 0, framesDropped: 0, bufferedBytes: 0 },
    };
    const rows = diagnosticsRows(idle, null, "Radio off");
    const byLabel = Object.fromEntries(rows.map((r) => [r.label, r]));
    expect(byLabel["Radio link"]?.value).toBe("Off");
    expect(byLabel["Audio"]?.value).toBe("-");
    expect(byLabel["Mic audio"]?.value).toBe("-");
    expect(byLabel["Mac voice"]?.value).toBe("-");
    expect(byLabel["Push to talk"]?.value).toBe("-");
    expect(byLabel["Screen"]?.warn).toBe(false); // may sleep only matters while live
  });

  it("the collapsed summary line", () => {
    const mac = macState(null, STATUS);
    expect(diagnosticsSummary({ source: "device", deviceTtsCapable: true, noun: "iPad", mac, link: "off", micLabel: "Radio off" })).toBe(
      "Speech: this iPad · radio off",
    );
    expect(diagnosticsSummary({ source: "server", deviceTtsCapable: true, noun: "iPad", mac, link: "open", micLabel: "Mic live" })).toBe(
      "Speech: Kokoro · bm_george · link up · mic live",
    );
    expect(diagnosticsSummary({ source: "server", deviceTtsCapable: false, noun: "device", mac: null, link: "reconnecting", micLabel: "Reconnecting…" })).toBe(
      "Speech: - · link down · reconnecting…",
    );
  });
});
