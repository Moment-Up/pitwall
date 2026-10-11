import { describe, expect, it } from "vitest";
import { standing } from "../drive/timing";
import { compareNullable, lapsLegendText, lapsRows } from "./laps";
import { fixtures } from "./testkit";

describe("Laps table by current standing (spec 6.4, 4.6)", () => {
  const s = fixtures.austria();
  const a = fixtures.austriaAnalysis();
  const rows = lapsRows(s.laps, a, s);
  const byLap = (n: number) => rows.find((r) => r.lapNumber === n)!;

  it("orders laps by number and marks the analysis' reference (lap 64, id 52)", () => {
    expect(rows.map((r) => r.lapNumber)).toEqual([62, 63, 64, 65, 66, 67, 68, 69, 70, 71]);
    expect(rows.filter((r) => r.isRef).map((r) => r.lapNumber)).toEqual([64]);
    expect(byLap(64).deltaS).toBeNull();
  });

  it("colours only the session's best time green (SB) and the rest yellow; a lap that is not clean is INV", () => {
    expect(byLap(64).lap.status).toBe("sb");
    expect(rows.filter((r) => r.lap.status === "sb")).toHaveLength(1);
    expect(byLap(66).lap.status).toBe("slower");
    expect(byLap(65).lap.status).toBe("invalid");
    expect(byLap(65).sectors.every((x) => x.status === "invalid")).toBe(true);
    // never purple or PB before D2
    expect(rows.flatMap((r) => [r.lap.status, ...r.sectors.map((x) => x.status)])).not.toContain("rec");
    expect(rows.flatMap((r) => [r.lap.status, ...r.sectors.map((x) => x.status)])).not.toContain("pb");
  });

  it("sector colours follow each sector's own best over the clean laps (lap 65's faster S3 does not count)", () => {
    // S1: lap 66 16.662 is the fastest clean S1; lap 64's 16.900 is slower
    expect(byLap(66).sectors[0].status).toBe("sb");
    expect(byLap(64).sectors[0].status).toBe("slower");
    // S3: lap 65 (flashback) has 22.189 but is not clean; the best clean S3 is lap 66's 22.151
    expect(byLap(66).sectors[2].status).toBe("sb");
  });

  it("gaps come from the analysis' comparisons; status words say why a lap is not clean", () => {
    expect(byLap(66).deltaS).toBeCloseTo(0.451, 3);
    expect(byLap(65).statusText).toBe("flashback");
    expect(byLap(66).statusText).toBe("Clean");
    expect(byLap(65).canBeRef).toBe(false);
    expect(byLap(66).canBeRef).toBe(true);
  });

  it("without an analysis the table still lists every lap, with unknown gaps", () => {
    const r = lapsRows(s.laps, undefined, s);
    expect(r).toHaveLength(10);
    expect(r.every((x) => x.deltaS === null && !x.isRef)).toBe(true);
  });

  it("synthetic and replay sessions carry no timing colours (INV stays: it is a fact about the lap), as on Drive", () => {
    const demo = fixtures.demo();
    const r = lapsRows(demo.laps, fixtures.demoAnalysis(), demo);
    const statuses = r.flatMap((x) => [x.lap.status, ...x.sectors.map((c) => c.status)]);
    expect(statuses.filter((st) => st !== "neutral" && st !== "invalid")).toEqual([]);
    expect(r.filter((x) => !x.clean).every((x) => x.lap.status === "invalid")).toBe(true);
    // One rule set (4.6): exactly what DL's standing gives with Drive's `coloured` switch off.
    const clean = r.map((x) => x.clean);
    expect(r.map((x) => x.lap.status)).toEqual(standing(r.map((x) => x.lap.ms), clean, { driver: null, household: null }, 1, false));
    expect(lapsLegendText(demo)).toBe("Synthetic data: times are not coloured, and never count as bests.");
    expect(lapsLegendText({ synthetic: false, source: "replay:captures/x.pwcap" })).toBe("A replay: times are not coloured, and never count as bests.");
    expect(lapsLegendText(s)).toMatch(/current standing/);
  });

  it("sorting keeps unknown values last", () => {
    expect([3, null, 1].sort(compareNullable)).toEqual([1, 3, null]);
  });
});
