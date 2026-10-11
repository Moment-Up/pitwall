import { describe, expect, it } from "vitest";
import { ribbon } from "./ribbon";
import { fixture, snap } from "./testkit";

describe("lap ribbon view model", () => {
  it("lays out sectors, corners, the cue notch and the car as lap fractions (real Suzuka)", () => {
    const s = fixture("recorded-suzuka-on-track-brake-ahead");
    const r = ribbon(s, "on_track", "T7");
    expect(r.lengthM).toBe(5809);
    expect(r.empty).toBe(false);
    expect(r.sectors.map((x) => x.label)).toEqual(["S1", "S2", "S3"]);
    expect(r.sectors[0]?.a).toBe(0);
    expect(r.sectors[1]?.a).toBeCloseTo(2225.65 / 5809);
    expect(r.sectors[2]?.b).toBe(1);
    expect(r.corners).toHaveLength(11);
    const t7 = r.corners.find((c) => c.name === "T7");
    expect(t7).toMatchObject({ label: "T11", next: true, focus: true, showLabel: true });
    expect(t7?.at).toBeCloseTo(2948 / 5809);
    expect(r.corners.filter((c) => c.showLabel).map((c) => c.label)).toEqual(["T11"]);
    expect(r.cueNotches).toHaveLength(1);
    expect(r.cueNotches[0]).toBeCloseTo(2826.3 / 5809);
    expect(r.car).toBeCloseTo(2483.1 / 5809);
    expect(r.drs).toEqual([]); // format 2025 sends no DRS table here
    expect(r.yellow).toEqual([]);
  });

  it("hatches only the zones with a live yellow (marshal_flags), not the static skeleton flag", () => {
    const s = fixture("recorded-suzuka-yellow-flag");
    const r = ribbon(s, "on_track");
    expect(r.yellow).toHaveLength(1);
    expect(r.yellow[0]?.[0]).toBeCloseTo(858.65 / 5809);
    s.marshal_flags = [];
    expect(ribbon(s, "on_track").yellow).toEqual([]);
  });

  it("splits a zone that runs through the line into its pieces", () => {
    const s = fixture("recorded-austria-blue-in-zone");
    s.marshal_flags = [{ game_number: 1, flag: "yellow" }]; // zone 1 = 4283.38 -> 342.33 (wraps)
    const r = ribbon(s, "on_track");
    expect(r.yellow).toHaveLength(2);
    expect(r.yellow.some(([a]) => a === 0)).toBe(true);
    expect(r.yellow.some(([, b]) => b === 1)).toBe(true);
  });

  it("hides the car in states that do not show it, and when its position is unknown", () => {
    const s = fixture("recorded-suzuka-on-track-brake-ahead");
    for (const st of ["stale", "offline", "ended", "garage"] as const) expect(ribbon(s, st).car, st).toBeNull();
    expect(ribbon(s, "pit_lane").car).not.toBeNull();
    expect(ribbon(fixture("recorded-live-api-gt7-stale"), "on_track").car).toBeNull(); // GT7 distance past the lap
  });

  it("is one neutral band without telemetry, and has no corner ticks without a model", () => {
    expect(ribbon(null, "no_data").empty).toBe(true);
    expect(ribbon(fixture("pipeline-no-data"), "no_data").empty).toBe(true);
    const r = ribbon(fixture("recorded-suzuka-grid-before-start"), "garage");
    expect(r.corners).toEqual([]);
    expect(r.sectors).toHaveLength(3);
    const bare = ribbon(snap(), "on_track");
    expect(bare.sectors).toEqual([]); // no skeleton: draw one band
    expect(bare.car).toBeCloseTo(4560 / 5890);
  });

  it("draws neither focus labels nor brake notches for the AI field's heads-ups (not the driver's braking points)", () => {
    const s = fixture("edited-ai-field-suzuka");
    const r = ribbon(s, "on_track", "T7");
    expect(r.corners.filter((c) => c.focus)).toEqual([]);
    expect(r.corners.filter((c) => c.showLabel).map((c) => c.label)).toEqual(["T11"]); // the next corner only
    expect(r.cueNotches).toEqual([]);
  });
});
