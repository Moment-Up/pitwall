// Settings › Radio & voice › Spotter: the card's view rules (spotter.ts) over the contract fixtures.
import { describe, expect, it } from "vitest";
import { parseSpotterInfo } from "../../../lib/endpoints/spotter";
import type { SpotterInfo } from "../../../lib/spotter/types";
import { spotterFixture } from "../../../test/spotter";
import {
  diagnosticsRows,
  diagnosticsSummary,
  masterView,
  msText,
  NOT_SUPPORTED_HINT,
  recentRows,
  SAME_VOICE,
  sendRateWarning,
  SPOTTER_HINT,
  startDelayText,
  statusView,
  testView,
  voiceFromOption,
  voiceView,
  withPending,
  wordingHint,
} from "./spotter";

const info = (n: "contract-active" | "contract-off" | "contract-gt7" | "contract-low-rate"): SpotterInfo => parseSpotterInfo(spotterFixture(n))!;

describe("master switch", () => {
  it("off by default, with the evidence tier in its hint", () => {
    expect(masterView(info("contract-off"))).toEqual({ on: false, disabled: false, hint: SPOTTER_HINT });
    expect(SPOTTER_HINT).toContain("Tested on recorded races, not yet on track");
  });

  it("another game: disabled with the F1-only sentence", () => {
    expect(masterView(info("contract-gt7"))).toEqual({ on: false, disabled: true, hint: NOT_SUPPORTED_HINT });
  });

  it("never locked on: a switch that is on can be turned off on another game", () => {
    const i = withPending(info("contract-gt7"), { enabled: true });
    expect(masterView(i)).toMatchObject({ on: true, disabled: false });
  });

  it("no motion yet on F1 is not 'unsupported' (the switch works)", () => {
    const i = info("contract-off");
    expect(masterView({ ...i, availability: { available: false, game: "f1_25", reason: "no_motion" } }).disabled).toBe(false);
  });
});

describe("status line", () => {
  it("active: rate and audio; latency only in the diagnostics (never 'to the ear')", () => {
    const v = statusView(info("contract-active"));
    expect(v).toEqual({ title: "Active", detail: "60 Hz · audio ready", warn: false });
    expect(v.detail).not.toMatch(/ear|p95|ms/);
  });

  it("no motion yet on F1 waits; another game is 'not available'", () => {
    const i = info("contract-active");
    const closed = { ...i, status: { ...i.status, active: false, reason: "not_available" as const } };
    expect(statusView({ ...closed, availability: { available: true, game: "f1_25", reason: "no_motion" } }).title).toBe(
      "Waiting for F1 25 data",
    );
    expect(statusView({ ...closed, availability: { available: false, game: "gt7", reason: "game_not_supported" } }).title).toBe(
      "Not available for this game",
    );
  });

  it("Auto says which wording the seated driver hears now", () => {
    expect(wordingHint("auto", "simple")).toBe("Follows the seated driver's profile: simple wording now (beginner).");
    expect(wordingHint("auto", "standard")).toBe("Follows the seated driver's profile: standard wording now.");
    expect(wordingHint("auto", null)).toBe("Follows the seated driver's profile: simple wording for beginners.");
    expect(wordingHint("standard", "simple")).toBe("Short calls: “Car left.” “Clear left.”");
  });

  it("a closed gate, a low send rate, unverified phrases and an error warn", () => {
    expect(statusView(info("contract-low-rate"))).toEqual({
      title: "Silent: safety car",
      detail: "20 Hz · preparing audio · 2 phrases unverified · 1 error",
      warn: true,
    });
    expect(sendRateWarning(info("contract-low-rate"))).toBe("Set UDP Send Rate to 60 Hz for the spotter (now 20 Hz).");
    expect(sendRateWarning(info("contract-active"))).toBeNull();
    const i = info("contract-low-rate");
    expect(sendRateWarning({ ...i, status: { ...i.status, motion_hz: null } })).toBe("Set UDP Send Rate to 60 Hz for the spotter.");
  });

  it("no Mac voice and no radio say so instead of a 'preparing audio' that never ends", () => {
    const i = info("contract-active");
    const withAudio = (engine: string | null) => ({
      ...i,
      status: { ...i.status, audio: { ...i.status.audio!, ready: false, engine, phrases: 0, clip_s: {} } },
    });
    expect(statusView(withAudio("none")).detail).toBe("60 Hz · no Mac voice");
    expect(statusView(withAudio(null)).detail).toBe("60 Hz · radio off");
    expect(statusView(withAudio("kokoro")).detail).toBe("60 Hz · preparing audio");
  });

  it("spoken calls off says so; nothing known yet is an empty detail", () => {
    const a = withPending(info("contract-active"), { audio: false });
    expect(statusView(a).detail).toBe("60 Hz · spoken calls off");
    const off = info("contract-off");
    expect(statusView(off)).toEqual({ title: "Off", detail: "", warn: false });
  });
});

describe("numbers", () => {
  it.each([
    [null, "-"],
    [Number.NaN, "-"],
    [-1, "-"],
    [0.13, "0.1 ms"],
    [6.4, "6.4 ms"],
    [190.4, "190 ms"],
    [1250, "1.25 s"],
  ])("msText(%s) = %s", (ms, text) => {
    expect(msText(ms)).toBe(text);
  });

  it("start delay", () => {
    expect(startDelayText(0)).toBe("At lights out");
    expect(startDelayText(5)).toBe("5 s");
    expect(startDelayText(Number.NaN)).toBe("-");
  });
});

describe("voice", () => {
  const VOICES = ["bm_fable", "bm_george", "bf_emma", "bf_isabella"];
  it("Kokoro only; 'Same as engineer' is the API's null", () => {
    expect(voiceView("say", VOICES, null).show).toBe(false);
    expect(voiceView(null, VOICES, null).show).toBe(false);
    const v = voiceView("kokoro", VOICES, null);
    expect(v.show).toBe(true);
    expect(v.value).toBe(SAME_VOICE);
    expect(v.options.map((o) => o.label)).toEqual([
      "Same as engineer",
      "Fable · British male",
      "George · British male",
      "Emma · British female",
      "Isabella · British female",
    ]);
    expect(voiceFromOption(SAME_VOICE)).toBeNull();
    expect(voiceFromOption("bf_emma")).toBe("bf_emma");
  });

  it("a saved voice the Mac no longer lists is kept as an option, never swapped", () => {
    const v = voiceView("kokoro", VOICES, "am_adam");
    expect(v.value).toBe("am_adam");
    expect(v.options[1]).toEqual({ id: "am_adam", label: "am_adam" });
  });
});

describe("test button", () => {
  it.each([
    ["idle", true, "Says a car on your left, then clear, in the wording in use, on every connected radio.", false],
    ["sending", false, "Sending…", false],
    ["sent", true, "Sent: listen for a car on your left, then clear.", false],
    ["radio_off", true, "No radio is connected: go live first.", true],
  ] as const)("%s", (state, enabled, hint, warn) => {
    expect(testView(info("contract-active"), state)).toEqual({ enabled, hint, warn });
  });

  it("an error shows the server's words; spoken calls off disables it", () => {
    expect(testView(info("contract-active"), { error: "Voice is off." })).toEqual({ enabled: true, hint: "Voice is off.", warn: true });
    expect(testView(withPending(info("contract-active"), { audio: false }), "idle")).toMatchObject({ enabled: false, hint: "Spoken calls are off." });
  });
});

describe("diagnostics", () => {
  it("every row, in words, with the honest labels", () => {
    const rows = Object.fromEntries(diagnosticsRows(info("contract-active")).map((r) => [r.label, r.value]));
    expect(rows).toEqual({
      Status: "Active",
      "Motion data": "60 Hz",
      "Car size": "5.50 × 2.00 m · F1 World (published figures)",
      Audio: "kokoro · George · British male · 18 phrases · ready",
      "Overlap to decision": "50 ms median · 67 ms p95",
      Decision: "0.1 ms median · 0.3 ms p95",
      "Packet to radio": "2.1 ms median · 6.4 ms p95",
      "Packet to playback": "150 ms median · 190 ms p95",
      "Network delay": "6.0 ms median · 71 ms p95",
      Calls: "car left 9 · clear left 8 · three wide 1",
      "Not spoken": "3 short overlaps · you were transmitting 1 · too old 2 · onset not heard 1",
      Packets: "18234 · 0 skipped · 0 invalid · 0 errors",
    });
  });

  it("nothing known yet is '-' or 'None', never a made-up number", () => {
    const rows = Object.fromEntries(diagnosticsRows(info("contract-off")).map((r) => [r.label, r.value]));
    expect(rows).toMatchObject({
      Status: "Off",
      "Motion data": "-",
      "Car size": "-",
      Audio: "-",
      Decision: "-",
      Calls: "None",
      "Not spoken": "0 short overlaps",
    });
  });

  it("warnings: low rate, unverified audio, errors", () => {
    const warn = diagnosticsRows(info("contract-low-rate")).filter((r) => r.warn).map((r) => r.label);
    expect(warn).toEqual(["Motion data", "Audio", "Packets"]);
  });

  it("recent calls in full, newest first", () => {
    const rows = recentRows(info("contract-active").recent);
    expect(rows.map((r) => [r.text, r.spoken, r.detail])).toEqual([
      ["still there (right)", true, "176 ms to playback"],
      ["car right", false, "not spoken"],
      ["clear left", true, "queued in 2.8 ms"],
      ["car left", true, "190 ms to playback"],
    ]);
    expect(rows[0]?.time).toMatch(/^\d\d:\d\d:\d\d$/);
    expect(recentRows([{ t_unix: null, kind: "x", side: null, spoken: true, queued_ms: null, started_ms: null }])[0]).toMatchObject({
      time: "-",
      text: "call",
      detail: "spoken",
    });
  });

  it("summary", () => {
    expect(diagnosticsSummary(info("contract-active"))).toBe("18 calls · to the radio in 6.4 ms (p95)");
    expect(diagnosticsSummary(info("contract-off"))).toBe("0 calls");
  });
});

describe("withPending", () => {
  it("lays unsaved changes over the last answer without touching it", () => {
    const i = info("contract-off");
    const next = withPending(i, { enabled: true, wording: "simple" });
    expect(next.settings).toMatchObject({ enabled: true, wording: "simple", audio: true });
    expect(i.settings.enabled).toBe(false);
    expect(withPending(i, {})).toBe(i);
  });
});
