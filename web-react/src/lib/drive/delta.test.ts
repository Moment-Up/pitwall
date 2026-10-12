import { describe, expect, it } from "vitest";
import { DELTA_NEUTRAL_S, deltaText, deltaTone, deltaView, referenceLabel } from "./delta";
import { NO_OVERLAYS, type DriveOverlays, type DriveState } from "./state";
import { fixture, lap, snap } from "./testkit";
import { MINUS } from "./text";

const O = (over: Partial<DriveOverlays> = {}): DriveOverlays => ({ ...NO_OVERLAYS, ...over });
const NOW = new Date(2026, 9, 11, 14).getTime() / 1000;

describe("delta text and tone", () => {
  it("uses two decimals, one at 10 s or more, and drops the sign at zero", () => {
    expect(deltaText(-0.214)).toBe(`${MINUS}0.21`);
    expect(deltaText(0.53)).toBe("+0.53");
    expect(deltaText(12.44)).toBe("+12.4");
    expect(deltaText(-10.04)).toBe(`${MINUS}10.0`);
    expect(deltaText(0.004)).toBe("0.00");
  });

  it("is level inside +-0.02 s", () => {
    expect(deltaTone(-DELTA_NEUTRAL_S)).toBe("level");
    expect(deltaTone(DELTA_NEUTRAL_S)).toBe("level");
    expect(deltaTone(-0.021)).toBe("ahead");
    expect(deltaTone(0.021)).toBe("behind");
  });
});

describe("deltaView", () => {
  it("shows a live delta with word, bar, reference chip and projected lap", () => {
    const s = fixture("recorded-suzuka-on-track-brake-ahead"); // delta -0.604, reference lap 3 1:37.191
    const v = deltaView(s, "on_track", O(), false, { nowS: NOW });
    expect(v).toMatchObject({
      text: `${MINUS}0.60`,
      tone: "ahead",
      word: "AHEAD",
      chip: null,
      clamped: false,
      projectedMs: 96587,
      projectedText: "1:36.59",
      label: "Delta to reference",
      refLabel: "Lap 3 · 1:37.191 · today",
      reason: null,
      showProjected: true,
    });
    expect(v.bar).toBeCloseTo(-0.604);
    expect(v.aria).toBe("0.60 seconds ahead of reference lap 3");
  });

  it("clamps the bar at one second and says LEVEL inside the band", () => {
    const behind = deltaView(snap({ delta_s: 8.975 }), "on_track", O(), false);
    expect(behind).toMatchObject({ text: "+8.97", tone: "behind", word: "BEHIND", bar: 1, clamped: true });
    const level = deltaView(snap({ delta_s: -0.01 }), "on_track", O(), false);
    expect(level).toMatchObject({ text: `${MINUS}0.01`, tone: "level", word: "LEVEL", clamped: false });
  });

  it("mutes the delta on an invalid lap (no projected) and under a safety car", () => {
    const inv = deltaView(fixture("synthetic-demo-invalid-lap"), "on_track", O({ invalid: true }), false);
    expect(inv).toMatchObject({ tone: "muted", chip: "INV", projectedMs: null, projectedText: "-" });
    const sc = deltaView(fixture("edited-safety-car"), "on_track", O({ safetyCar: "full" }), false);
    expect(sc).toMatchObject({ tone: "muted", chip: "SC", word: "AHEAD", projectedText: "1:36.59" });
    expect(sc.aria).toContain("safety car");
  });

  it("is '-' with one reason in every state without a live delta (a frozen delta never looks current)", () => {
    const s = fixture("recorded-suzuka-on-track-brake-ahead");
    const cases: [DriveState, string | null][] = [
      ["offline", "Offline"],
      ["no_data", "No telemetry"],
      ["stale", "No signal"],
      ["pit_lane", "No delta in the pit lane"],
      ["red_flag", "Red flag"],
      ["garage", null],
      ["ended", null],
    ];
    for (const [state, reason] of cases) {
      const v = deltaView(s, state, O(), false);
      expect(v.text, state).toBe("-");
      expect(v.tone, state).toBe("unknown");
      expect(v.reason, state).toBe(reason);
      expect(v.projectedText, state).toBe("-");
    }
    expect(deltaView(fixture("recorded-austria-stale"), "stale", O(), false).reason).toBe("No signal · 2 s");
  });

  it("explains a missing delta on track", () => {
    expect(deltaView(snap({ delta_s: null, reference: null }), "on_track", O(), false).reason).toBe(
      "No reference yet: your first clean lap becomes the reference",
    );
    // a clean lap is in, not yet published as the reference: no longer "your first clean lap" (UX review)
    const after = snap({ delta_s: null, reference: null, laps: [lap(2, 90_000)] });
    expect(deltaView(after, "on_track", O(), false).reason).toBe("Delta from your next lap");
    const out = snap({ delta_s: null });
    out.frame = { ...out.frame!, driver_status: "out_lap" };
    expect(deltaView(out, "on_track", O(), false).reason).toBe("Out lap");
    expect(deltaView(snap({ delta_s: null }), "on_track", O(), false).reason).toBe("No delta at this point of the lap");
  });

  it("speaks to beginners about their target lap and hides the projected lap", () => {
    const v = deltaView(snap(), "on_track", O(), true);
    expect(v.label).toBe("vs your target lap");
    expect(v.showProjected).toBe(false);
  });
});

describe("referenceLabel", () => {
  it("dates a reference from another session from the driver's best laps, else says so", () => {
    const s = snap({ reference: { lap_id: 52, lap_number: 5, lap_time_ms: 90874, session_id: "older" } });
    const oct3 = new Date(2026, 9, 3, 12).getTime() / 1000;
    expect(referenceLabel(s, NOW, new Map([[52, oct3]]))).toBe("Lap 5 · 1:30.874 · 3 Oct");
    expect(referenceLabel(s, NOW, null)).toBe("Lap 5 · 1:30.874 · another session");
    expect(referenceLabel(snap({ reference: null }), NOW)).toBeNull();
  });
});
