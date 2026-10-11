import { describe, expect, it } from "vitest";
import { sessionBests } from "../bests";
import {
  bestLapStatus,
  bestLapSub,
  cleanLapsText,
  gainedView,
  gapToBestEver,
  isReplaySource,
  lapsText,
  notUsedText,
  steadinessSentence,
  summaryKpis,
  timingEligible,
  type KpiLap,
} from "./kpis";
import { fixtures } from "./testkit";

const lap = (n: number, ms: number | null, clean = true, flags: string[] = [], valid: boolean | null = true): KpiLap => ({
  id: 100 + n,
  lap_number: n,
  lap_time_ms: ms,
  s1_ms: ms ? Math.round(ms * 0.3) : null,
  s2_ms: ms ? Math.round(ms * 0.4) : null,
  s3_ms: ms ? Math.round(ms * 0.3) : null,
  valid,
  clean,
  flags,
});

describe("summary KPIs on a recorded race (Austria, PS5 F1 25)", () => {
  const s = fixtures.austria();
  const k = summaryKpis(s.laps);

  it("best clean lap, clean count and the lap not used", () => {
    expect(k.total).toBe(10);
    expect(k.clean).toBe(9);
    expect(k.best).toEqual({ lapId: 52, lapNumber: 64, ms: 70549 });
    expect(k.first).toEqual({ lapId: 50, lapNumber: 62, ms: 76325 });
    expect(k.notUsed).toEqual([{ lapNumber: 65, reason: "flashback" }]);
    expect(notUsedText(k)).toBe("1 not used: flashback");
    expect(cleanLapsText(k)).toBe("9 of 10");
  });

  it("gained today = first clean lap minus best, steadiness = slowest minus fastest clean lap", () => {
    expect(k.gainedMs).toBe(76325 - 70549);
    expect(k.spreadMs).toBe(76325 - 70549);
    const g = gainedView(k);
    // a positive number and a word, never "5.8 s ↑ faster" or a bare sign (the one convention, lib/bests.ts)
    expect(g.change).toEqual({ text: "5.8 s faster", amount: "5.8 s", word: "faster" });
    expect(g.sub).toBe("First clean lap (lap 62) → best lap (lap 64)");
    expect(steadinessSentence(k.spreadMs)).toBe("Your clean laps were within 5.8 s of each other");
  });

  it("best sectors combined from clean laps only", () => {
    expect(k.bestSectorsMs).toEqual([16662, 31149, 22151]);
    expect(k.bestSectorsCombinedMs).toBe(16662 + 31149 + 22151);
  });

  it("the best lap carries the strongest badge it holds (lib/bests.ts): SB until the bests are known, then REC here", () => {
    expect(bestLapStatus(s, k.best)).toBe("sb");
    expect(bestLapStatus(s, k.best, "sb")).toBe("sb");
    // the recorded list: this session's 1:10.549 is the fastest clean lap anyone drove at Austria in the Haas
    const b = sessionBests({ ...s, best_clean_ms: k.best!.ms }, fixtures.sessions(), { complete: true });
    expect(b.household?.sessionId).toBe(s.id);
    expect(bestLapStatus(s, k.best, "rec")).toBe("rec");
    expect(bestLapSub(k.best, "rec")).toBe("lap 64 · the family record here");
    expect(bestLapSub(k.best, "pb")).toBe("lap 64 · your best ever here");
    expect(bestLapSub(k.best, "sb")).toBe("lap 64");
  });

  it("gap to your best ever: this session set it, with the gain on the earlier best", () => {
    const b = sessionBests({ ...s, best_clean_ms: k.best!.ms }, fixtures.sessions(), { complete: true });
    const g = gapToBestEver(s, k.best, b, Date.now());
    expect(g.pb).toBe(true);
    // the earlier Haas session at Austria (1:11.745); the F1 Generic session is another car and never counts
    expect(g.sub).toBe("1.2 s faster than your earlier best, 1:11.745");
  });
});

describe("gap to your best ever (no placeholder about future work)", () => {
  const rows = fixtures.sessions();
  const older = rows.find((r) => r.id === "a100cbc9b5bd")!; // Austria, Haas, 1:11.745, before the 1:10.549
  const ref = { lapId: 1, lapNumber: 3, ms: 71745 };

  it("a slower session reads the gap as a positive number and a word, with the best's day", () => {
    const b = sessionBests(older, rows, { complete: true });
    const g = gapToBestEver(older, ref, b, Date.UTC(2026, 9, 11, 12));
    expect(g).toMatchObject({ pb: false, change: { text: "1.2 s slower", amount: "1.2 s", word: "slower" } });
    expect(g.sub).toMatch(/^Your best ever 1:10\.549, /);
  });

  it("the first session at a track and car: an honest short line", () => {
    const first = { ...older, id: "new", car_id: "f1:team:99", started_unix: 1 };
    const g = gapToBestEver(first, ref, sessionBests(first, rows, { complete: true }), Date.now());
    expect(g).toEqual({ change: null, pb: true, sub: "No earlier best on this track and car yet" });
  });

  it("says why there is no gap: synthetic, replay, no driver, unknown car, no clean lap, loading", () => {
    const now = Date.now();
    expect(gapToBestEver({ ...older, synthetic: true }, ref, null, now).sub).toBe("Synthetic data never counts as a best");
    expect(gapToBestEver({ ...older, source: "replay:x" }, ref, null, now).sub).toBe("A replay never counts as a best");
    expect(gapToBestEver({ ...older, driver_id: null }, ref, null, now).sub).toBe("This session has no driver");
    expect(gapToBestEver({ ...older, car_id: null }, ref, null, now).sub).toBe("Car unknown: no best to compare with");
    expect(gapToBestEver(older, null, null, now).sub).toBe("Needs a clean lap");
    expect(gapToBestEver(older, ref, null, now)).toEqual({ change: null, pb: false, sub: "Loading the bests…" });
    for (const sub of [gapToBestEver(older, ref, null, now).sub]) expect(sub).not.toMatch(/arrives|coming|future/i);
  });
});

describe("evidence tiers (spec 4.6, P8)", () => {
  it("synthetic sessions never carry timing colours or a PB", () => {
    const demo = fixtures.demo();
    const k = summaryKpis(demo.laps);
    expect(demo.synthetic).toBe(true);
    expect(timingEligible(demo)).toBe(false);
    expect(bestLapStatus(demo, k.best)).toBe("neutral");
    // even a badge computed elsewhere never colours it
    expect(bestLapStatus(demo, k.best, "rec")).toBe("neutral");
  });

  it("replays are nobody's driving", () => {
    expect(isReplaySource("replay:captures/x.pwcap")).toBe(true);
    expect(isReplaySource("udp:20777")).toBe(false);
    expect(timingEligible({ synthetic: false, source: "replay:a" })).toBe(false);
    expect(timingEligible({ synthetic: false, source: "udp:20777" })).toBe(true);
    expect(bestLapStatus({ source: "replay:a" }, { lapId: 1, lapNumber: 1, ms: 1 })).toBe("neutral");
  });
});

describe("edge cases", () => {
  it("no laps: everything unknown, nothing invented", () => {
    const k = summaryKpis([]);
    expect(k).toMatchObject({ total: 0, clean: 0, best: null, first: null, gainedMs: null, spreadMs: null });
    expect(k.bestSectorsCombinedMs).toBeNull();
    expect(cleanLapsText(k)).toBe("No laps recorded");
    expect(notUsedText(k)).toBeNull();
    expect(gainedView(k).change).toBeNull();
    expect(bestLapSub(null)).toBe("No clean lap yet");
    expect(bestLapStatus({}, null)).toBe("neutral");
  });

  it("one clean lap: no gain and no steadiness yet", () => {
    const k = summaryKpis([lap(1, 90_000), lap(2, 95_000, false, ["pit_in"])]);
    expect(k.gainedMs).toBeNull();
    expect(k.spreadMs).toBeNull();
    expect(gainedView(k).sub).toBe("Needs a second clean lap");
    expect(steadinessSentence(null)).toBe("Needs 2 clean laps");
  });

  it("the first clean lap was the best: zero gained, said in words", () => {
    const k = summaryKpis([lap(1, 90_000), lap(2, 90_500)]);
    expect(gainedView(k)).toEqual({
      change: { text: "level", amount: null, word: "level" },
      sub: "Your first clean lap (lap 1) was your best",
    });
  });

  it("untimed laps and invalid clean flags are ignored for times", () => {
    const k = summaryKpis([lap(1, null), lap(2, 0), lap(3, 91_000), lap(4, 89_000, false, [], false)]);
    expect(k.clean).toBe(1);
    expect(k.best?.lapNumber).toBe(3);
    expect(k.notUsed).toEqual([{ lapNumber: 4, reason: "invalid" }]);
  });

  it("a missing sector leaves the combined time unknown", () => {
    const l = lap(1, 90_000);
    const k = summaryKpis([{ ...l, s2_ms: null }]);
    expect(k.bestSectorsMs[1]).toBeNull();
    expect(k.bestSectorsCombinedMs).toBeNull();
  });

  it("list rows: '12 laps' before D5, '9 of 12 clean' with it", () => {
    expect(lapsText({ lap_count: 12 })).toBe("12 laps");
    expect(lapsText({ lap_count: 1, clean_lap_count: null })).toBe("1 lap");
    expect(lapsText({ lap_count: 12, clean_lap_count: 9 })).toBe("9 of 12 clean");
  });
});

describe("laps not used", () => {
  it("names each reason once across laps", () => {
    const k = summaryKpis([
      lap(1, 95_000, false, ["standing_start", "distance_jump"]),
      lap(2, 91_000, false, ["distance_jump", "flashback"]),
      lap(3, 90_000),
    ]);
    expect(notUsedText(k)).toBe("2 not used: standing start, reset to track, flashback");
  });
});
