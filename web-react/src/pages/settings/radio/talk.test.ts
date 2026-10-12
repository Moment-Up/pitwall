// Settings › Radio & voice › Talking to the engineer (lane handsfree): static render of the section (plain node, like
// render.test.ts), the button set-up dialog's words, and the section inside the full page.

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import frames from "../../../test/fixtures/handsfree/server-frames.json";
import { HANDS_FREE_IDLE, parseHandsFreeState } from "../../../lib/handsfree";
import type { RadioServerState, RadioSettings } from "../../../lib/radio";
import { setupText } from "./ButtonSetupDialog";
import { TalkSection, type TalkSectionProps, type TalkSectionState } from "./TalkSection";

const SETTINGS: RadioSettings = {
  voiceEnabled: true,
  intensity: "normal",
  voiceSource: "server",
  deviceVoice: null,
  deviceRate: 1,
  version: 2,
  handsFree: false,
  wakeWord: "pitwall",
  handsFreeConsent: false,
  talkButton: null,
};

const SERVER: RadioServerState = {
  ptt: false,
  listening: false,
  speaking: false,
  intensity: "normal",
  stt: "parakeet",
  tts: "kokoro",
  telemetry: "no_data",
  ptt_source: null,
  handsfree: parseHandsFreeState(frames.handsfree.listening)!,
};

function r(over: Partial<TalkSectionState> = {}): TalkSectionState {
  return {
    phase: "idle",
    conn: "offline",
    mic: "off",
    micSilent: false,
    server: null,
    settings: SETTINGS,
    handsFree: HANDS_FREE_IDLE,
    micCapable: true,
    ...over,
  };
}

function render(over: Partial<TalkSectionProps> = {}): string {
  const props: TalkSectionProps = {
    r: r(),
    statusHandsFree: null,
    noun: "iPad",
    actions: { setHandsFree: vi.fn(), acceptHandsFreeConsent: vi.fn(), setWakeWord: vi.fn(), setTalkButton: vi.fn() },
    ...over,
  };
  return renderToStaticMarkup(createElement(TalkSection, props));
}

const text = (m: string): string =>
  m
    .replace(/<[^>]+>/g, " ")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/\s+/g, " ")
    .trim();

describe("Talking to the engineer", () => {
  it("off by default: hold to talk, set up a button (AirPods can't), hands-free off, Pitwall as the wake word", () => {
    const m = render();
    const t = text(m);
    expect(t).toContain("Hold to talk");
    expect(t).toContain("Space on a keyboard");
    expect(t).toContain("UDP Action 1");
    expect(t).toContain("Bluetooth button");
    expect(t).toContain("paired with this iPad. AirPods taps and headphone play buttons can't reach a web page");
    expect(t).toContain("Set up");
    expect(t).not.toContain("Remove");
    expect(t).toContain("Hands-free");
    expect(t).toContain('Off. Turn on to ask without a button: start with "Pitwall"');
    expect(t).toContain("keyboard only");
    // the keyboard-only advice is part of the Bluetooth button's hint, before the hands-free row
    expect(t.indexOf("keyboard only")).toBeLessThan(t.indexOf("Hands-free"));
    const checked = m.match(/<button[^>]*role="radio"[^>]*aria-checked="true"[^>]*>.*?<\/button>/g) ?? [];
    expect(checked).toHaveLength(1);
    expect(checked[0]).toContain(">Pitwall<");
    expect(m).toMatch(/role="switch"(?![^>]*checked=""[^>]*)/);
  });

  it("a learned button: its name, how it works, Change and Remove", () => {
    const t = text(render({ r: r({ settings: { ...SETTINGS, talkButton: { kind: "key", code: "PageDown" } } }) }));
    expect(t).toContain("Page Down. Hold it to talk, or tap it once and speak");
    expect(t).toContain("Change");
    expect(t).toContain("Remove");
  });

  it("on and live: says when it listens; the radio wake word changes the hint", () => {
    const on = { ...SETTINGS, handsFree: true, handsFreeConsent: true, wakeWord: "radio" as const };
    const t = text(render({ r: r({ phase: "live", conn: "open", mic: "live", server: SERVER, settings: on }) }));
    expect(t).toContain('Listening while the car is stopped (or no game data arrives). Start with "Radio"');
    expect(t).toContain(`Start with "Radio": "Radio, what's the gap?"`);
  });

  it("radio off: the Mac's availability from GET /api/voice/status", () => {
    const on = { ...SETTINGS, handsFree: true, handsFreeConsent: true };
    const unavailable = parseHandsFreeState(frames.handsfree.unavailable_env);
    const t = text(render({ r: r({ settings: on }), statusHandsFree: unavailable }));
    expect(t).toContain("PITWALL_VOICE_HANDSFREE=false");
  });

  it("no microphone: the switch is disabled and says why", () => {
    const m = render({ r: r({ micCapable: false, mic: "unavailable" }) });
    expect(text(m)).toContain("needs the microphone");
    expect(m).toMatch(/disabled/);
  });
});

describe("Set up button dialog words", () => {
  it("waiting, a refused key, the learned button", () => {
    expect(setupText(null, null, "iPad")).toMatchObject({ title: "Press your button now…" });
    expect(setupText(null, null, "iPad").body).toContain("paired with this iPad");
    expect(setupText(null, "KeyA", "iPad").body).toContain('"Key A" types text');
    const learned = setupText({ kind: "gamepad", id: "Xbox Wireless Controller", button: 0 }, null, "iPad");
    expect(learned.title).toBe("Xbox Wireless Controller · button 0 (A / Cross on most controllers)");
    expect(learned.body).toContain("tap it once and speak");
  });
});
