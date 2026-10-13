// v0.3.0, Settings › Radio & voice as the one page for every call family: the seated driver's race calls and "Hands-free
// while driving" (moved from the driver sheet), car health, the spotter and "What the radio says" (the radio's one
// policy from GET /api/radio/policy). Each setting appears once.

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { ALL_RADIO_CALLS, PALETTE, RADIO_CALL_GROUPS, type Driver } from "../../../lib/drivers";
import { radioPolicyOf } from "../../../lib/endpoints/radiopolicy";
import { HANDS_FREE_IDLE } from "../../../lib/handsfree";
import { ONLINE_NAMES_TITLE, onlineNamesView } from "./model";
import { familyLine, policyRows, policySummary, settingLine, whenSaid } from "./policy-model";
import { drivingHandsFreeView, raceCallPatch, raceCallsView } from "./race-calls";
import { RadioPolicyCardView } from "./RadioPolicyCard";
import { RadioVoiceView, type RadioActions, type RadioVoiceViewProps } from "./RadioVoiceView";

function driver(prefs: Partial<Driver["preferences"]> = {}): Pick<Driver, "id" | "name" | "preferences"> {
  return {
    id: 2,
    name: "Sam",
    preferences: {
      colour: PALETTE[0]!,
      initials: "SA",
      skill_level: "beginner",
      coaching_intensity: "normal",
      voice_enabled: true,
      radio_calls: { ...ALL_RADIO_CALLS },
      radio_wording: "auto",
      handsfree_while_driving: false,
      ...prefs,
    },
  };
}

const actions = (): RadioActions => ({
  setVoiceEnabled: vi.fn(),
  setIntensity: vi.fn(),
  setCueMode: vi.fn(),
  setVoiceSource: vi.fn(),
  setServerVoice: vi.fn(),
  testServerVoice: vi.fn(),
  setDeviceVoice: vi.fn(),
  setDeviceRate: vi.fn(),
  testDeviceVoice: vi.fn(),
  setHandsFree: vi.fn(),
  acceptHandsFreeConsent: vi.fn(),
  setWakeWord: vi.fn(),
  setTalkButton: vi.fn(),
});

function render(over: Partial<RadioVoiceViewProps> = {}): string {
  const props: RadioVoiceViewProps = {
    r: {
      phase: "idle",
      conn: "offline",
      retryInS: null,
      error: null,
      server: null,
      settings: {
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
      },
      deviceVoices: [],
      deviceTtsCapable: true,
      micCapable: true,
      serverVoiceTest: "idle",
      mic: "off",
      micSilent: false,
      pttHeld: false,
      handsFree: HANDS_FREE_IDLE,
    },
    status: undefined,
    radioFollowsDriver: true,
    noun: "iPad",
    actions: actions(),
    goLive: false,
    ...over,
  };
  return renderToStaticMarkup(createElement(RadioVoiceView, props));
}

const text = (m: string): string =>
  m.replace(/<[^>]+>/g, " ").replace(/&#x27;/g, "'").replace(/&amp;/g, "&").replace(/\s+/g, " ");
const checked = (m: string): number => (m.match(/checked=""/g) ?? []).length;
const count = (hay: string, needle: string): number => hay.split(needle).length - 1;

describe("race calls for the driver in the seat", () => {
  it("are the seated driver's, editable, and say how many are off", () => {
    const v = raceCallsView({ driver: driver(), follows: true, anyKnowsRaceRadio: true });
    expect(v).toMatchObject({ shown: true, editable: true, title: "Race calls for Sam", driverId: 2 });
    expect(v.hint).toBe("Sam's, the driver in the seat: each driver has their own.");
    const off = raceCallsView({
      driver: driver({ radio_calls: { ...ALL_RADIO_CALLS, rivals: false, name: false } }),
      follows: true,
      anyKnowsRaceRadio: true,
    });
    expect(off.calls.rivals).toBe(false);
    expect(off.hint).toMatch(/2 switched off\.$/);
    expect(raceCallsView({ driver: driver(), follows: true, anyKnowsRaceRadio: true, saveError: "boom" }).hint).toBe(
      "Not saved: boom",
    );
    expect(raceCallPatch("flags", false)).toEqual({ radio_calls: { flags: false } });
  });

  it("nobody seated: every call on, locked; never offered without race radio or without a radio following drivers", () => {
    const nobody = raceCallsView({ driver: null, follows: true, anyKnowsRaceRadio: true });
    expect(nobody).toMatchObject({ shown: true, editable: false, driverId: null });
    expect(Object.values(nobody.calls).every(Boolean)).toBe(true);
    expect(raceCallsView({ driver: null, follows: true, anyKnowsRaceRadio: false }).shown).toBe(false);
    expect(raceCallsView({ driver: driver(), follows: false, anyKnowsRaceRadio: true }).shown).toBe(false);
    const old = driver();
    delete old.preferences.radio_calls;
    expect(raceCallsView({ driver: old, follows: true, anyKnowsRaceRadio: false }).shown).toBe(false);
  });

  it("render: seven toggles once each, in the Radio calls section with the online names switch", () => {
    const v = raceCallsView({
      driver: driver({ radio_calls: { ...ALL_RADIO_CALLS, rivals: false } }),
      follows: true,
      anyKnowsRaceRadio: true,
    });
    const names = onlineNamesView({ data: { online_names: false }, error: null, saving: false, saveError: null });
    const html = render({ raceCalls: v, onRaceCall: vi.fn(), onlineNames: names, onOnlineNames: vi.fn() });
    const t = text(html);
    expect(t).toContain("Radio calls");
    expect(t).toContain("Race calls for Sam");
    for (const g of RADIO_CALL_GROUPS) expect(count(t, g.label)).toBe(1);
    expect(count(t, ONLINE_NAMES_TITLE)).toBe(1);
    expect(t.indexOf("Race calls for Sam")).toBeLessThan(t.indexOf(ONLINE_NAMES_TITLE));
    // six of the seven race calls on, plus the voice switch; online names off
    expect(checked(html)).toBe(checked(render()) + 6);
    expect(t).not.toContain("Race calls are set per driver"); // no pointer elsewhere: the toggles are here
  });

  it("render: locked while nobody is seated", () => {
    const html = render({ raceCalls: raceCallsView({ driver: null, follows: true, anyKnowsRaceRadio: true }), onRaceCall: vi.fn() });
    expect(text(html)).toContain("Nobody is in the seat, so every race call is on.");
    expect(count(html, 'disabled=""') - count(render(), 'disabled=""')).toBe(RADIO_CALL_GROUPS.length);
  });
});

describe("hands-free while driving, beside this device's hands-free switch", () => {
  it("is the seated driver's", () => {
    expect(drivingHandsFreeView(driver(), true, true)).toMatchObject({
      shown: true,
      on: false,
      disabled: false,
      title: "Hands-free while Sam drives",
      hint: "Off: only while the car is stopped.",
    });
    expect(drivingHandsFreeView(driver({ handsfree_while_driving: true }), true, true).hint).toMatch(/^On: also listens/);
    expect(drivingHandsFreeView(null, true, true)).toMatchObject({ shown: true, disabled: true });
    expect(drivingHandsFreeView(null, true, false).shown).toBe(false);
    expect(drivingHandsFreeView(driver(), false, true).shown).toBe(false);
  });

  it("render: in Talking to the engineer, once", () => {
    const v = drivingHandsFreeView(driver({ handsfree_while_driving: true }), true, true);
    const html = render({ drivingHandsFree: v, onDrivingHandsFree: vi.fn() });
    const t = text(html);
    expect(count(t, "Hands-free while Sam drives")).toBe(1);
    expect(t.indexOf("Hands-free while Sam drives")).toBeGreaterThan(t.indexOf("Talking to the engineer"));
    expect(checked(html)).toBe(checked(render()) + 1);
    expect(text(render())).not.toContain("drives");
  });
});

const POLICY = radioPolicyOf({
  families: [
    { key: "spotter", label: "Spotter", rank: 0, interrupts: true, intensities: ["quiet", "normal", "detailed"],
      quiet_mode: "said", speak_window: false, budget: "free", setting: "Spotter", note: "Cars alongside." },
    { key: "urgent", label: "Red flag and punctures", rank: 0, interrupts: true,
      intensities: ["quiet", "normal", "detailed"], quiet_mode: "said", speak_window: false, budget: "free",
      setting: "always on", note: "Safety-critical." },
    { key: "race", label: "Race calls", rank: 3, interrupts: false, intensities: ["normal", "detailed"],
      quiet_mode: "held", speak_window: true, budget: "waits", setting: "Race calls", note: "Position." },
    { key: "alert", label: "Flags", rank: 1, interrupts: false, intensities: ["quiet", "normal", "detailed"],
      quiet_mode: "some", speak_window: true, budget: "spends", setting: "Race calls", note: "Yellow." },
    { key: "detail", label: "Detail", rank: 7, interrupts: false, intensities: ["detailed"], quiet_mode: "held",
      speak_window: true, budget: "waits", setting: "Coaching amount: Detailed", note: "Gap trends." },
    { key: "future", budget: "sometimes" },
  ],
  constants: { talk_per_lap: { quiet: 0, normal: 3, detailed: 5 }, race_per_lap: { quiet: 0, normal: 2, detailed: 3 } },
});

describe("What the radio says: the policy as the code has it", () => {
  it("reads the served table leniently (an unknown row is skipped, a wrong shape is nothing)", () => {
    expect(POLICY?.families.map((f) => f.key)).toEqual(["spotter", "urgent", "race", "alert", "detail"]);
    expect(radioPolicyOf({ families: [] })).toBeNull();
    expect(radioPolicyOf(null)).toBeNull();
  });

  it("in the driver's words", () => {
    expect(whenSaid(["quiet", "normal", "detailed"])).toBe("Always");
    expect(whenSaid(["normal", "detailed"])).toBe("Normal and Detailed");
    expect(whenSaid(["detailed"])).toBe("Detailed only");
    expect(settingLine("")).toBe("");
    const p = POLICY!;
    expect(policySummary(p)).toBe(
      "At most 3 messages a lap at Normal, 5 at Detailed, 0 at Quiet, from every source together (race calls at most " +
        "2, 3 at Detailed). Alerts never wait but count. Only these cut in: Spotter, Red flag and punctures. " +
        "Everything else waits for a calm stretch.",
    );
    expect(familyLine(p.families[0]!)).toBe("Always · cuts in at once · outside the lap's messages");
    expect(familyLine(p.families[2]!)).toBe("Normal and Detailed · waits for room in the lap's messages");
    expect(policyRows(p).map((r) => r.key)).toEqual(["spotter", "urgent", "alert", "race", "detail"]); // race order
    expect(policyRows(p)[1]?.hint).toBe("Safety-critical. Always · cuts in at once · outside the lap's messages. Always on.");
    expect(policyRows(p)[3]?.hint).toMatch(/Switch: Race calls\.$/);
  });

  it("render: one row per family; nothing for an older server", () => {
    const html = renderToStaticMarkup(createElement(RadioPolicyCardView, { policy: POLICY }));
    const t = text(html);
    expect(t).toContain("What the radio says");
    for (const f of POLICY!.families) expect(count(t, f.note)).toBe(1);
    expect(renderToStaticMarkup(createElement(RadioPolicyCardView, { policy: null }))).toBe("");
    expect(text(render({ policy: createElement(RadioPolicyCardView, { policy: POLICY }) }))).toContain(
      "What the radio says",
    );
  });
});
