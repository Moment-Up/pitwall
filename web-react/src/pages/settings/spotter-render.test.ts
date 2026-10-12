// Render tests for Settings › Radio & voice › Spotter (static markup in plain node, like render.test.ts): every state
// of the card - not read yet, unreadable, off, another game, active, low send rate with a closed gate, a refused save -
// and its place in the Radio & voice page.

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { parseSpotterInfo } from "../../lib/endpoints/spotter";
import type { SpotterInfo } from "../../lib/spotter/types";
import { spotterFixture } from "../../test/spotter";
import { RadioVoiceView, type RadioVoiceViewProps } from "./radio/RadioVoiceView";
import { SpotterCard, type SpotterCardProps } from "./radio/SpotterCard";
import { withPending } from "./radio/spotter";

const VOICES = ["bm_fable", "bm_george", "bf_emma", "bf_isabella"];
const info = (n: "contract-active" | "contract-off" | "contract-gt7" | "contract-low-rate"): SpotterInfo => parseSpotterInfo(spotterFixture(n))!;

function render(over: Partial<SpotterCardProps> = {}): string {
  const props: SpotterCardProps = {
    info: info("contract-active"),
    error: null,
    saveError: null,
    engine: "kokoro",
    voices: VOICES,
    test: "idle",
    actions: { update: vi.fn(), test: vi.fn() },
    ...over,
  };
  return renderToStaticMarkup(createElement(SpotterCard, props));
}

const text = (m: string): string =>
  m
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ");

const ROWS = ["Spoken calls", "iPad bars", "Also in qualifying", "Also in practice", "Start after lights out", "Wording", "Still there", "Hold your line", "Test spotter", "Spotter diagnostics"];

describe("Settings › Radio & voice › Spotter", () => {
  it("not read yet: '-' and no switch (unknown is not 'off')", () => {
    const m = render({ info: undefined });
    expect(text(m)).toContain("Unknown until the Mac answers.");
    expect(m).not.toContain('role="switch"');
  });

  it("unreadable: the error in words", () => {
    const t = text(render({ info: undefined, error: "HTTP 500" }));
    expect(t).toContain("Couldn't read the spotter's status: HTTP 500");
  });

  it("off (the default): one switch with the evidence tier, nothing else", () => {
    const m = render({ info: info("contract-off") });
    const t = text(m);
    expect(t).toContain("Calls cars alongside in F1 25 races. Tested on recorded races, not yet on track.");
    expect(m.match(/role="switch"/g)).toHaveLength(1);
    expect(m).not.toMatch(/role="switch"[^>]*checked=""/);
    for (const row of ROWS) expect(t).not.toContain(row);
  });

  it("another game: the switch is disabled with the F1-only sentence", () => {
    const m = render({ info: info("contract-gt7") });
    expect(text(m)).toContain("F1 25 only: other games don't send the other cars' positions.");
    expect(m).toMatch(/<input[^>]*disabled=""[^>]*role="switch"|role="switch"[^>]*disabled=""/);
  });

  it("on and active: status, every row, the Kokoro voice picker and Test spotter", () => {
    const m = render();
    const t = text(m);
    expect(t).toContain("Active");
    expect(t).toContain("60 Hz · audio ready");
    expect(t).not.toContain("to playback (p95)");
    for (const row of ROWS) expect(t).toContain(row);
    expect(t).toContain("Spotter voice");
    expect(t).toContain("Same as engineer");
    expect(t).toContain("5 s");
    expect(t).toContain("Follows the seated driver's profile");
    expect(t).not.toContain("UDP send rate");
    const test = m.match(/<button[^>]*>[^<]*Test spotter[^<]*<\/button>/)?.[0] ?? "";
    expect(test).toContain("min-h-11"); // a 44 px target at every width
  });

  it("the Mac speaking with `say`: no spotter voice picker (engineer's voice only in v1)", () => {
    expect(text(render({ engine: "say" }))).not.toContain("Spotter voice");
  });

  it("20 Hz under a safety car: the gate's words and the send-rate warning", () => {
    const t = text(render({ info: info("contract-low-rate") }));
    expect(t).toContain("Silent: safety car");
    expect(t).toContain("UDP send rate");
    expect(t).toContain("Set UDP Send Rate to 60 Hz for the spotter (now 20 Hz).");
    expect(t).toContain("At lights out");
    expect(t).toContain("Plain calls");
  });

  it("a refused save says why; a radio-off test says go live", () => {
    const t = text(render({ saveError: "start_delay_s: must be between 0 and 20", test: "radio_off" }));
    expect(t).toContain("Not saved");
    expect(t).toContain("start_delay_s: must be between 0 and 20");
    expect(t).toContain("No radio is connected: go live first.");
  });

  it("spoken calls off: the test is disabled and says why", () => {
    const m = render({ info: withPending(info("contract-active"), { audio: false }) });
    expect(text(m)).toContain("Spoken calls are off.");
    expect(m).toMatch(/<button[^>]*disabled=""[^>]*>[^<]*Test spotter/);
  });

  it("never prints raw unknowns", () => {
    for (const m of [render(), render({ info: info("contract-off") }), render({ info: info("contract-low-rate") }), render({ info: undefined })]) {
      const t = text(m);
      for (const bad of ["undefined", "null", "NaN", "—", "safety_car", "send_rate_low"]) expect(t).not.toContain(bad);
    }
  });
});

describe("Radio & voice page: the spotter's place", () => {
  it("renders the spotter slot in the 'On the radio' column, after the braking-call note", () => {
    const props: RadioVoiceViewProps = {
      r: {
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
      },
      status: undefined,
      radioFollowsDriver: false,
      noun: "iPad",
      actions: {
        setVoiceEnabled: vi.fn(),
        setIntensity: vi.fn(),
        setCueMode: vi.fn(),
        setVoiceSource: vi.fn(),
        setServerVoice: vi.fn(),
        testServerVoice: vi.fn(),
        setDeviceVoice: vi.fn(),
        setDeviceRate: vi.fn(),
        testDeviceVoice: vi.fn(),
      },
      goLive: false,
      spotter: createElement("section", { "data-testid": "spotter-slot" }, "SPOTTER SLOT"),
    };
    const t = text(renderToStaticMarkup(createElement(RadioVoiceView, props)));
    expect(t.indexOf("SPOTTER SLOT")).toBeGreaterThan(t.indexOf("Braking calls and coaching are also on Drive › Radio"));
    const without = text(renderToStaticMarkup(createElement(RadioVoiceView, { ...props, spotter: undefined })));
    expect(without).not.toContain("SPOTTER SLOT");
  });
});
