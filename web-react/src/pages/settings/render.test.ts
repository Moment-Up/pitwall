// Render tests for Settings › Radio & voice and Display (static markup in plain node, like src/components/ui).
// The radio view is pure: it gets the radio state, the Mac's HTTP status and the store's actions as props.

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { VoiceStatus } from "../../lib/endpoints/settings";
import type { DeviceVoice, RadioServerState } from "../../lib/radio";
import { DisplayPreview } from "./display/DisplayPreview";
import { RadioVoiceView, type RadioActions, type RadioVoiceState, type RadioVoiceViewProps } from "./radio/RadioVoiceView";

const SERVER: RadioServerState = {
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
  cue_mode: "focus",
  telemetry: "no_data",
  ptt_source: null,
};

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
  cue_mode: "all",
};

const JAMIE: DeviceVoice = { uri: "com.apple.voice.premium.en-GB.Jamie", name: "Jamie", lang: "en-GB", quality: "premium" };

function radioState(over: Partial<RadioVoiceState> = {}): RadioVoiceState {
  return {
    phase: "idle",
    conn: "offline",
    retryInS: null,
    error: null,
    server: null,
    settings: { voiceEnabled: true, intensity: "normal", voiceSource: "server", deviceVoice: null, deviceRate: 1, version: 2 },
    deviceVoices: [],
    deviceTtsCapable: true,
    micCapable: true,
    serverVoiceTest: "idle",
    mic: "off",
    micSilent: false,
    pttHeld: false,
    ...over,
  };
}

function actions(): RadioActions {
  return {
    setVoiceEnabled: vi.fn(),
    setIntensity: vi.fn(),
    setCueMode: vi.fn(),
    setVoiceSource: vi.fn(),
    setServerVoice: vi.fn(),
    testServerVoice: vi.fn(),
    setDeviceVoice: vi.fn(),
    setDeviceRate: vi.fn(),
    testDeviceVoice: vi.fn(),
  };
}

function render(over: Partial<RadioVoiceViewProps> = {}): string {
  const props: RadioVoiceViewProps = {
    r: radioState(),
    status: STATUS,
    radioFollowsDriver: false,
    noun: "iPad",
    actions: actions(),
    goLive: false,
    ...over,
  };
  return renderToStaticMarkup(createElement(RadioVoiceView, props));
}

/** Visible text, tags stripped. */
const text = (m: string): string =>
  m
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ");

describe("Settings › Radio & voice", () => {
  it("radio off: explains the link, shows the Mac's voice and mode from the HTTP status, locks them", () => {
    const m = render();
    const t = text(m);
    expect(t).toContain("The radio is off");
    expect(t).toContain("George · British male");
    expect(t).toContain("Natural voice (Kokoro): George · British male.");
    expect(t).toContain("Go live first: the Mac's voice comes over the radio link.");
    // The Mac voice picker and the braking-call Segment are locked while the link is down; the Segment shows the
    // Mac's mode (All).
    expect(m).toMatch(/disabled=""[^>]*aria-label="Mac voice"/);
    expect(m).toMatch(/role="radiogroup"[^>]*aria-disabled="true"/);
    expect(m.match(/<button[^>]*role="radio"[^>]*aria-checked="true"[^>]*>.*?<\/button>/g)?.join(" ")).toContain(">All<");
    expect(t).toContain("A brake call at every braking zone.");
    for (const w of ["Voice", "Engineer voice", "Mac voice", "Test voice", "Braking calls", "Coaching", "Diagnostics"]) {
      expect(t).toContain(w);
    }
  });

  it("radio off with no status yet: nothing guessed (no mode selected, Mac voice '-')", () => {
    const m = render({ status: undefined });
    const t = text(m);
    expect(t).toContain("Unknown until the Mac answers.");
    expect(t).toContain("Unknown: the Mac has not answered.");
    expect(t).not.toContain("George");
    // No braking-call mode is checked (cells.tsx keeps the group controlled with a key no choice uses). Coaching, the
    // local setting, is the only checked choice.
    const checked = m.match(/<button[^>]*role="radio"[^>]*aria-checked="true"[^>]*>.*?<\/button>/g) ?? [];
    expect(checked).toHaveLength(1);
    expect(checked[0]).toContain(">Normal<");
  });

  it("Test voice is a 44 px target at every width (HeroUI lg is 40 px from 768 px up)", () => {
    const m = render();
    const test = m.match(/<button[^>]*>[^<]*Test voice[^<]*<\/button>/)?.[0] ?? "";
    expect(test).toContain("min-h-11");
  });

  it("voice disabled on the Mac: a danger banner and no Go live", () => {
    const t = text(render({ status: { enabled: false }, goLive: true }));
    expect(t).toContain("Voice is off on the Mac");
    expect(t).not.toMatch(/go live/i);
  });

  it("live: no banner, the link's own state wins over the HTTP status, Test voice enabled", () => {
    const m = render({ r: radioState({ phase: "live", conn: "open", mic: "live", server: SERVER }) });
    const t = text(m);
    expect(t).not.toContain("The radio is off");
    expect(t).toContain("Brake calls only for the 1-3 corners where you lose the most time.");
    expect(t).toContain("The Mac says a radio check on every connected radio.");
    expect(t).toContain("Speech: Kokoro · bm_george · link up · mic live");
  });

  it("this device's voice: device voice, speaking speed and a local Test voice", () => {
    const t = text(
      render({
        r: radioState({ settings: { ...radioState().settings, voiceSource: "device", deviceRate: 1.05 }, deviceVoices: [JAMIE] }),
      }),
    );
    expect(t).toContain("This iPad");
    expect(t).toContain("This iPad speaks the messages with its own voice.");
    expect(t).toContain("Jamie (Premium) · en-GB");
    expect(t).toContain("Speaking speed");
    expect(t).toContain("1.05×");
    expect(t).toContain("Says a radio check with this iPad's voice.");
    expect(t).not.toContain("download a Premium voice"); // a Premium voice is installed
  });

  it("this device's voice with no voices yet says so, and the Premium tip shows without one", () => {
    const none = text(render({ r: radioState({ settings: { ...radioState().settings, voiceSource: "device" } }) }));
    expect(none).toContain("No voices yet: they load after Go live.");
    const standard = text(
      render({
        r: radioState({
          settings: { ...radioState().settings, voiceSource: "device" },
          deviceVoices: [{ ...JAMIE, quality: "standard", name: "Daniel" }],
        }),
      }),
    );
    expect(standard).toContain("download a Premium voice");
  });

  it("a browser without Web Speech: the Mac's voice, no device rows", () => {
    const t = text(render({ r: radioState({ deviceTtsCapable: false, settings: { ...radioState().settings, voiceSource: "device" } }) }));
    expect(t).toContain("This browser cannot speak by itself");
    expect(t).not.toContain("Speaking speed");
  });

  it("follows the seated driver: says where coaching and voice also come from", () => {
    expect(text(render({ radioFollowsDriver: true }))).toContain("Each driver's profile sets coaching and voice");
    expect(text(render({ radioFollowsDriver: false }))).not.toContain("Each driver's profile");
  });

  it("never prints raw unknowns", () => {
    for (const m of [render(), render({ status: undefined }), render({ r: radioState({ phase: "live", conn: "open", server: SERVER }) })]) {
      const t = text(m);
      for (const bad of ["undefined", "null", "NaN", "—", "--:--"]) expect(t).not.toContain(bad);
    }
  });
});

describe("Settings › Display preview", () => {
  const m = renderToStaticMarkup(createElement(DisplayPreview, { caption: "Stored on this device." }));
  const t = text(m);

  it("labels its values as a sample", () => {
    expect(t).toContain("Sample values");
    expect(m).toContain('aria-label="Preview with sample values"');
  });

  it("draws a green SB and a yellow sector, an ahead and a behind delta, and no purple", () => {
    expect(m).toContain('data-status="sb"');
    expect(m).toContain('data-status="slower"');
    expect(m).not.toContain('data-status="rec"');
    expect(m).not.toContain('data-status="pb"');
    expect(t).toContain("29.318");
    expect(t).toContain("36.904");
    expect(m).toContain('data-tone="ahead"');
    expect(m).toContain('data-tone="behind"');
    expect(t).toContain("AHEAD");
    expect(t).toContain("BEHIND");
    expect(t).toContain("0.21");
    expect(t).toContain("0.11");
  });

  it("scales with the Drive tokens (Large multiplies them)", () => {
    expect(m).toContain("calc(var(--pw-d-delta) * 0.5)");
    expect(m).toContain('data-size="drive"');
  });
});
