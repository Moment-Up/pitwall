import { describe, expect, it } from "vitest";
import {
  alignTraces,
  deltaDomain,
  deltaRows,
  distanceTick,
  distanceTicks,
  lapChartModel,
  lapPointWords,
  nearestIndex,
  niceDomain,
  timeTick,
  timeTicks,
  valuesAt,
  type LapPoint,
} from "./charts";
import { CursorSync } from "./cursor";
import { clamp, lapFraction, mapMetres, niceStep, niceTicks, wrapMetres } from "./scale";

// Lap times of a real session (Austria, F1 25 on PS5, session 332904dbe3de laps 62-71, read from the live API);
// lap 65 was not clean (flashback). The out lap row is added by hand to test the off-scale rule.
const AUSTRIA: LapPoint[] = [
  { id: 49, x: 61, ms: 98_500, clean: false, reason: "out lap" },
  { id: 50, x: 62, ms: 76_325, clean: true },
  { id: 51, x: 63, ms: 72_311, clean: true },
  { id: 52, x: 64, ms: 70_549, clean: true, status: "sb", tag: "SB" },
  { id: 53, x: 65, ms: 70_889, clean: false, reason: "flashback" },
  { id: 54, x: 66, ms: 71_000, clean: true },
  { id: 55, x: 67, ms: 71_718, clean: true },
  { id: 60, x: 72, ms: null, clean: false, reason: "invalid" },
];

describe("lapChartModel", () => {
  const m = lapChartModel(AUSTRIA, [70_549]);

  it("splits clean, not-clean and untimed laps into their own series (a missing key is a gap)", () => {
    expect(m.empty).toBe(false);
    expect(m.rows.find((r) => r.x === 64)).toEqual({ x: 64, clean: 70_549 });
    expect(m.rows.find((r) => r.x === 65)).toEqual({ x: 65, other: 70_889 });
    expect(m.rows.find((r) => r.x === 72)).toEqual({ x: 72, none: m.domain[1] });
    expect(m.byX.get(64)?.tag).toBe("SB");
  });

  it("scales on the clean laps (with padding) and puts a far slower out lap at the slow edge, flagged", () => {
    expect(m.domain[0]).toBeLessThan(70_549);
    expect(m.domain[1]).toBeGreaterThan(76_325);
    expect(m.domain[1]).toBeLessThan(98_500);
    expect(m.offScale.has(49)).toBe(true);
    expect(m.rows.find((r) => r.x === 61)).toEqual({ x: 61, other: m.domain[1] });
    expect(m.offScale.has(53)).toBe(false);
  });

  it("ticks on whole tenths and labels them m:ss.S", () => {
    expect(m.ticks.length).toBeGreaterThanOrEqual(3);
    for (const t of m.ticks) expect(t % 100).toBe(0);
    expect(m.ticks.map(timeTick)).toContain("1:12.0");
    expect(m.xDomain).toEqual([60.5, 72.5]);
  });

  it("is empty when no lap has a time", () => {
    const e = lapChartModel([{ id: 1, x: 1, ms: null, clean: false }]);
    expect(e.empty).toBe(true);
    expect(lapChartModel([]).empty).toBe(true);
  });

  it("describes a point in words", () => {
    expect(lapPointWords(AUSTRIA[4]!)).toBe("Lap 65 · 1:10.889 · not clean: flashback");
    expect(lapPointWords(AUSTRIA[0]!, { offScale: true })).toBe("Lap 61 · 1:38.500 · not clean: out lap · off the scale");
    expect(lapPointWords({ id: "s", x: 0, xLabel: "3 Oct", ms: 90_702, clean: true }, { xName: "" })).toBe("3 Oct · 1:30.702 · clean");
    expect(lapPointWords(AUSTRIA[7]!)).toBe("Lap 72 · - · not clean: invalid");
  });
});

describe("time ticks", () => {
  it("picks steps of 0.1 / 0.2 / 0.5 / 1 / 2 s ... for about four intervals", () => {
    expect(timeTicks(90_000, 91_000)).toEqual([90_000, 90_500, 91_000]);
    expect(timeTicks(90_050, 90_390)).toEqual([90_100, 90_200, 90_300]);
    expect(timeTicks(70_000, 78_000)).toEqual([70_000, 72_000, 74_000, 76_000, 78_000]);
    expect(timeTicks(5, 5)).toEqual([0]);
  });

  it("formats ticks as m:ss.S, or ss.S under a minute, '-' when unknown", () => {
    expect(timeTick(91_000)).toBe("1:31.0");
    expect(timeTick(29_500)).toBe("29.5");
    expect(timeTick(0)).toBe("-");
    expect(timeTick(Number.NaN)).toBe("-");
  });
});

describe("traces by distance", () => {
  const ref = { d: [0, 5, 10, 15], speed_kph: [100, 110, null, 130], throttle: [1, 1, 0.5, 0] };
  const cmp = { d: [0, 5, 10], speed_kph: [99, 108, 111], throttle: [1, 0.9, 0.4] };

  it("aligns both laps on the reference grid; unknown values and missing samples are gaps", () => {
    expect(alignTraces(ref, cmp, "speed_kph")).toEqual([
      { d: 0, a: 100, b: 99 },
      { d: 5, a: 110, b: 108 },
      { d: 10, b: 111 },
      { d: 15, a: 130 },
    ]);
  });

  it("scales pedals to percent and finds a shifted sample within half a step", () => {
    const shifted = { d: [1, 6, 11], throttle: [1, 0.5, 0] };
    expect(alignTraces(ref, shifted, "throttle", 100).map((r) => r.b)).toEqual([100, 50, 0, undefined]);
    expect(alignTraces(null, cmp, "throttle", 100)).toEqual([
      { d: 0, b: 100 },
      { d: 5, b: 90 },
      { d: 10, b: 40 },
    ]);
    expect(alignTraces(null, null, "throttle")).toEqual([]);
  });

  it("turns a comparison into delta rows and a symmetric domain of at least +-0.2 s", () => {
    const rows = deltaRows({ delta_d: [0, 10, 20], delta_s: [0, 0.31, Number.NaN] });
    expect(rows).toEqual([{ d: 0, delta: 0 }, { d: 10, delta: 0.31 }, { d: 20 }]);
    const dd = deltaDomain(rows);
    expect(dd.domain[0]).toBe(-dd.domain[1]);
    expect(dd.domain[1]).toBeGreaterThanOrEqual(0.31);
    expect(deltaDomain([]).domain).toEqual([-0.2, 0.2]);
    expect(deltaRows(null)).toEqual([]);
  });

  it("reads values at the nearest row (the readout under the cursor)", () => {
    const rows = alignTraces(ref, cmp, "speed_kph");
    expect(valuesAt(rows, 6.9, ["a", "b"])).toEqual({ d: 5, values: { a: 110, b: 108 } });
    expect(valuesAt(rows, 9, ["a", "b"])).toEqual({ d: 10, values: { a: null, b: 111 } });
    expect(valuesAt(rows, null, ["a"])).toBeNull();
    expect(nearestIndex([0, 5, 10], 7.5)).toBe(1);
    expect(nearestIndex([0, 5, 10], 99)).toBe(2);
    expect(nearestIndex([], 1)).toBe(-1);
  });

  it("rounds an automatic y domain to nice ticks (no 85 / 170 / 255 axes)", () => {
    const rows: Record<string, number>[] = [{ d: 0, a: 86.4, b: 92 }, { d: 5, a: 318.7 }];
    expect(niceDomain(rows, ["a", "b"])).toEqual({ domain: [50, 350], ticks: [50, 100, 150, 200, 250, 300, 350] });
    expect(niceDomain(rows, ["c"])).toBeNull();
    expect(niceDomain([{ d: 0, a: 5 }], ["a"])?.domain[0]).toBeLessThan(5);
  });

  it("ticks distance every kilometre (500 m on short tracks)", () => {
    expect(distanceTicks(4323)).toEqual([0, 1000, 2000, 3000, 4000]);
    expect(distanceTicks(913)).toEqual([0, 500]);
    expect(distanceTicks(null)).toEqual([]);
    expect(distanceTick(0)).toBe("0");
    expect(distanceTick(2500)).toBe("2.5 km");
    expect(distanceTick(3000)).toBe("3 km");
  });
});

describe("scale helpers", () => {
  it("maps metres between lap lengths by lap fraction (identity when unknown)", () => {
    expect(mapMetres(2904.5, 5809, 5810)).toBeCloseTo(2905);
    expect(mapMetres(100, null, 5810)).toBe(100);
    expect(lapFraction(2904.5, 5809)).toBeCloseTo(0.5);
    expect(lapFraction(-5, 5809)).toBe(0);
    expect(lapFraction(5, null)).toBeNull();
    expect(wrapMetres(-5, 100)).toBe(95);
    expect(wrapMetres(205, 100)).toBe(5);
    expect(clamp(5, 0, 1)).toBe(1);
  });

  it("finds nice ticks", () => {
    expect(niceStep(1, 4)).toBe(0.25);
    expect(niceTicks(-0.31, 0.31, 4)).toEqual([-0.2, 0, 0.2]);
    expect(niceTicks(0, 10, 5)).toEqual([0, 2, 4, 6, 8, 10]);
    expect(niceTicks(2, 1)).toEqual([]);
  });
});

describe("CursorSync", () => {
  it("notifies only on change and clears to null", () => {
    const c = new CursorSync();
    let n = 0;
    const off = c.subscribe(() => (n += 1));
    c.set(100);
    c.set(100);
    c.set(Number.NaN);
    expect(c.get()).toBeNull();
    expect(n).toBe(2);
    off();
    c.set(5);
    expect(n).toBe(2);
    expect(new CursorSync(Number.POSITIVE_INFINITY).get()).toBeNull();
  });
});
