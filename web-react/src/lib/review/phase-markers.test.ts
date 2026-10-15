// Compare's corner phase markers and g-force availability (technique knowledge spec section 4): the four points come
// from the comparison's per-lap CornerMetrics (recorded Austria fixture), unknown stays unknown (no line, "not
// measured"), the words describe lap B against lap A by name, and a game with no g sends no g-force chart.
import { describe, expect, it } from "vitest";
import type { ReviewCornerDelta } from "../endpoints/review";
import { compareCorners } from "./compare";
import {
  comparisonCorner,
  focusKeyAt,
  gForceAvailable,
  hasValues,
  PHASE_MARKERS,
  phaseDeltaWords,
  phaseMarkerRows,
  phaseTraceMarkers,
} from "./phase-markers";
import { fixtures } from "./testkit";

const COLOURS = { ref: "var(--pw-ref)", lap: "var(--pw-cmp)" };

describe("corner phase markers", () => {
  it("are the four measured points in driving order, with no turn-in point", () => {
    expect(PHASE_MARKERS.map((m) => m.key)).toEqual(["brake_start", "brake_release", "slowest", "full_throttle"]);
    expect(PHASE_MARKERS.map((m) => m.field)).toEqual(["brake_start_m", "brake_end_m", "min_speed_m", "throttle_full_m"]);
    expect(PHASE_MARKERS.map((m) => m.label).join(" ")).not.toMatch(/turn/i);
  });

  it("read the recorded comparison's ref and cmp metrics (Austria T1, lap 66 against lap 64)", () => {
    const c = comparisonCorner(fixtures.compare().comparison.corners, "T1");
    const rows = phaseMarkerRows(c);
    expect(rows.map((r) => r.key)).toEqual(["brake_start", "brake_release", "slowest", "full_throttle"]);
    const [on, off, slowest, full] = rows;
    expect(on).toMatchObject({ label: "Brake on", refM: 334.936, lapM: 332.937, words: "2 m earlier than the reference", at: 332.937 });
    expect(on!.deltaM).toBeCloseTo(-1.999, 3);
    expect(off).toMatchObject({ label: "Brake off", words: "same place as the reference" });
    expect(slowest).toMatchObject({ refM: 475, lapM: 468, words: "7 m earlier than the reference" });
    // The reference lap never reached full throttle before the corner's end: unknown, not a guessed position.
    expect(full).toMatchObject({ refM: null, lapM: 474.884, deltaM: null, words: "only measured on your lap", at: 474.884 });
  });

  it("name lap A as Compare does (another driver's lap, a beginner's target lap)", () => {
    const c = comparisonCorner(fixtures.compare().comparison.corners, "T1");
    expect(phaseMarkerRows(c, "Sam's best")[0]!.words).toBe("2 m earlier than Sam's best");
    expect(phaseDeltaWords(100, 112.4, "your target lap")).toBe("12 m later than your target lap");
    expect(phaseDeltaWords(100, null, "your target lap")).toBe("only measured on your target lap");
    expect(phaseDeltaWords(null, null)).toBe("not measured");
  });

  it("leave out points neither lap has, and anything that is not a number (unknown stays unknown)", () => {
    const corner = {
      corner: "T9",
      time_delta_s: 0.1,
      ref: { corner: "T9", segment_time_s: 5, brake_start_m: Number.NaN, brake_end_m: null, min_speed_m: 900 },
      cmp: { corner: "T9", segment_time_s: 5.1, brake_start_m: undefined, min_speed_m: 904, throttle_full_m: null },
    } as unknown as ReviewCornerDelta;
    const rows = phaseMarkerRows(corner);
    expect(rows.map((r) => r.key)).toEqual(["slowest"]);
    expect(rows[0]!.words).toBe("4 m later than the reference");
    expect(phaseMarkerRows(null)).toEqual([]);
    // An older server without per-lap metrics: no markers at all.
    expect(phaseMarkerRows({ corner: "T9", time_delta_s: 0.1 } as unknown as ReviewCornerDelta)).toEqual([]);
  });

  it("draw lap A dashed and your lap solid, each in its lap's colour", () => {
    const rows = phaseMarkerRows(comparisonCorner(fixtures.compare().comparison.corners, "T1"));
    const lines = phaseTraceMarkers(rows, COLOURS, "Reference");
    expect(lines).toHaveLength(7); // full throttle only on your lap
    for (const l of lines.filter((x) => x.id.endsWith(":ref"))) expect(l).toMatchObject({ colour: COLOURS.ref, dash: "4 3" });
    for (const l of lines.filter((x) => x.id.endsWith(":lap"))) expect(l.dash).toBeUndefined();
    expect(lines[0]).toMatchObject({ id: "brake_start:ref", d: 334.936, label: "Brake on, Reference" });
    expect(new Set(lines.map((l) => l.id)).size).toBe(lines.length);
  });

  it("keep the corner whose point the key showed while the cursor rests there", () => {
    const r = fixtures.compare();
    const corners = compareCorners(r.comparison.corners, r.track_model, 4318);
    const t2 = corners.find((c) => c.key === "T2")!;
    expect(focusKeyAt(corners, t2.apexGame)).toBe("T2");
    // A point in T1's stretch, pinned to T2: T2 stays the focus there, and only there.
    const t1 = corners.find((c) => c.key === "T1")!;
    const at = t1.apexGame!;
    expect(focusKeyAt(corners, at)).toBe("T1");
    expect(focusKeyAt(corners, at, { key: "T2", at })).toBe("T2");
    expect(focusKeyAt(corners, at + 1, { key: "T2", at })).toBe("T1");
    // A pin to a corner this comparison does not have is ignored.
    expect(focusKeyAt(corners, at, { key: "T99", at })).toBe("T1");
    expect(focusKeyAt(corners, null)).toBeNull();
  });
});

describe("g-force charts", () => {
  it("show a row only when either lap has a value on it", () => {
    const some = [null, 0.4, -1.2];
    const none = [null, null, null];
    expect(gForceAvailable({ g_lat: some, g_lon: some }, { g_lat: none, g_lon: none })).toEqual({ lat: true, lon: true });
    expect(gForceAvailable({ g_lat: none, g_lon: some }, { g_lat: none, g_lon: none })).toEqual({ lat: false, lon: true });
  });

  it("hide both for a game that sends no g (GT7: every value null), traces without the channels, or no traces", () => {
    const gt7 = { g_lat: [null, null], g_lon: [null, null] };
    expect(gForceAvailable(gt7, gt7)).toEqual({ lat: false, lon: false });
    // The recorded Austria trace fixtures were trimmed to the pedal channels.
    expect(gForceAvailable(fixtures.trace52(), fixtures.trace54())).toEqual({ lat: false, lon: false });
    expect(gForceAvailable(null, undefined)).toEqual({ lat: false, lon: false });
    expect(hasValues([Number.NaN, null])).toBe(false);
    expect(hasValues([])).toBe(false);
    expect(hasValues([0])).toBe(true);
  });
});
