import { describe, expect, it } from "vitest";
import type { SessionListRow } from "../endpoints/review";
import {
  bestHereSentence,
  bestHereSeries,
  clockTick,
  cornerBars,
  cornerDeltaMap,
  cornerTone,
  deltaAxis,
  lapChartRows,
  lapPoints,
  timeAxis,
} from "./charts";
import { summaryKpis } from "./kpis";
import { fixtures } from "./testkit";

describe("lap times chart (spec 6.3 #4)", () => {
  const s = fixtures.austria();
  const best = summaryKpis(s.laps).best;
  const pts = lapPoints(s.laps, best?.lapId ?? null);

  it("one point per timed lap, clean or not, the best tagged, the reason in words", () => {
    expect(pts).toHaveLength(10);
    expect(pts.filter((p) => p.best).map((p) => p.lap)).toEqual([64]);
    const flashback = pts.find((p) => p.lap === 65)!;
    expect(flashback).toMatchObject({ clean: false, reason: "flashback", s: 70.889 });
  });

  it("rows put not-clean laps under another key (a gap, never a 0)", () => {
    const rows = lapChartRows(pts);
    expect(rows.find((r) => r.lap === 65)).toEqual({ lap: 65, other: 70.889 });
    expect(rows.find((r) => r.lap === 64)).toEqual({ lap: 64, clean: 70.549 });
    expect(rows.every((r) => !Object.values(r).includes(0))).toBe(true);
  });

  it("ticks read m:ss.S (tenths, truncated)", () => {
    expect(clockTick(70.549)).toBe("1:10.5");
    expect(clockTick(59.99)).toBe("59.9");
    expect(clockTick(90)).toBe("1:30.0");
    expect(clockTick(0)).toBe("");
  });

  it("axis spans the laps and the reference with nice steps", () => {
    const a = timeAxis(pts.map((p) => p.s), 70.549);
    expect(a.domain[0]).toBeLessThanOrEqual(70.549);
    expect(a.domain[1]).toBeGreaterThanOrEqual(76.325);
    expect(a.ticks.length).toBeGreaterThanOrEqual(3);
    expect(a.ticks.length).toBeLessThanOrEqual(7);
    expect(timeAxis([], null)).toEqual({ domain: [0, 1], ticks: [] });
    const flat = timeAxis([90, 90.05]);
    expect(flat.domain[1] - flat.domain[0]).toBeGreaterThan(0.1);
  });
});

describe("where the time is (spec 6.3 #5)", () => {
  const a = fixtures.austriaAnalysis();
  const bars = cornerBars(a.corner_summary, a.track_model);

  it("sorted by time lost, official labels, words from the signs", () => {
    expect(bars.map((b) => b.label)).toEqual(["T3", "T6", "T7", "T1", "T4", "T10", "T9"]);
    expect(bars[0]).toMatchObject({ key: "T2", deltaS: 0.412, tone: "lost" });
    expect(bars[0]!.words).toEqual(["braked about 11 m later", "6 km/h slower out of the corner"]);
    expect(bars.at(-1)).toMatchObject({ full: "T9 Rindt Kurve", tone: "gained" });
  });

  it("neutral within ±0.01 s; unknown left out", () => {
    expect(cornerTone(0.01)).toBe("level");
    expect(cornerTone(-0.011)).toBe("gained");
    expect(cornerTone(0.011)).toBe("lost");
    expect(cornerTone(null)).toBeNull();
    expect(cornerBars([{ ...a.corner_summary[0]!, mean_time_delta_s: null }], a.track_model)).toEqual([]);
    expect(cornerBars(null, null)).toEqual([]);
  });

  it("map colours by corner key", () => {
    expect(cornerDeltaMap(a.corner_summary)).toMatchObject({ T2: 0.412, T6: -0.231 });
  });
});

describe("your best here (spec 6.3 #7)", () => {
  const rows = fixtures.sessions();

  it("best clean lap per real session at this track, oldest first", () => {
    const austria = rows.find((r) => r.id === "332904dbe3de")!;
    const pts = bestHereSeries(rows, austria);
    expect(pts.map((p) => p.ms)).toEqual([78351, 71745, 70549]);
    expect(pts.at(-1)!.current).toBe(true);
    expect(bestHereSentence(pts)).toBe("Your best here dropped 7.8 s over 3 sessions");
  });

  it("synthetic and replay sessions never count", () => {
    const demo = rows.find((r) => r.synthetic && r.source.startsWith("replay:"))!;
    expect(bestHereSeries(rows, demo)).toEqual([]);
    const synth: SessionListRow = { ...demo, source: "udp:20777" };
    expect(bestHereSeries([synth], synth)).toEqual([]);
  });

  it("sentences for few sessions", () => {
    expect(bestHereSentence([])).toBe("No clean laps here yet");
    expect(bestHereSentence([{ sessionId: "a", startedUnix: 1, ms: 90000, s: 90, current: true }])).toBe(
      "Your first session here with a clean lap",
    );
    expect(
      bestHereSentence([
        { sessionId: "a", startedUnix: 1, ms: 90000, s: 90, current: false },
        { sessionId: "b", startedUnix: 2, ms: 90200, s: 90.2, current: true },
      ]),
    ).toBe("Your first session here is still your best (2 sessions)");
  });
});

describe("delta axis", () => {
  it("includes zero, whole steps, a few ticks", () => {
    const a = deltaAxis([0.412, 0.402, -0.231, 0.097]);
    expect(a.ticks).toContain(0);
    expect(a.domain[0]).toBeLessThanOrEqual(-0.231);
    expect(a.domain[1]).toBeGreaterThanOrEqual(0.412);
    expect(a.ticks.length).toBeGreaterThanOrEqual(3);
    expect(a.ticks.length).toBeLessThanOrEqual(7);
    expect(a.ticks).toEqual([-0.4, -0.2, 0, 0.2, 0.4, 0.6]);
    expect(a.digits).toBe(1);
    expect(deltaAxis([]).ticks).toContain(0);
    expect(deltaAxis([0.03, 0.01]).digits).toBe(2);
  });
});
