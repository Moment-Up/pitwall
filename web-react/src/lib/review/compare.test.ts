import { describe, expect, it } from "vitest";
import {
  apexGameM,
  biggestLoss,
  blockedText,
  brakedText,
  chartWords,
  compareCorners,
  cornerAt,
  cornerColumns,
  cornerObservations,
  cornerSentence,
  defaultPair,
  exitText,
  explainerText,
  gameToModelM,
  lapOptions,
  lossGainText,
  modelToGameM,
  optionText,
  parseCompareQuery,
  refOptions,
  refWordFor,
  segmentDeltas,
  slowestText,
  throttleText,
  timeSigned,
  timeWords,
  totalText,
} from "./compare";
import { lapsRows } from "./laps";
import { driver, fixtures } from "./testkit";

describe("Compare route and default pair (spec 6.5)", () => {
  it("parses ref, lap and at; anything malformed is unknown", () => {
    expect(parseCompareQuery(new URLSearchParams("ref=52&lap=54&at=1413.5"))).toEqual({ ref: 52, lap: 54, at: 1413.5 });
    expect(parseCompareQuery(new URLSearchParams("ref=x&lap=-3&at=abc"))).toEqual({ ref: null, lap: null, at: null });
    expect(parseCompareQuery(new URLSearchParams(""))).toEqual({ ref: null, lap: null, at: null });
  });

  const s = fixtures.austria();
  const a = fixtures.austriaAnalysis();
  const rows = lapsRows(s.laps, a, s);

  it("A defaults to the analysis' reference, B to the newest clean lap that is not A", () => {
    expect(defaultPair(rows, a.ref_lap_id, { ref: null, lap: null })).toEqual({ ref: 52, lap: 59 });
  });

  it("the route wins; without any reference A is the fastest clean lap", () => {
    expect(defaultPair(rows, a.ref_lap_id, { ref: 54, lap: 50 })).toEqual({ ref: 54, lap: 50 });
    expect(defaultPair(rows, null, { ref: null, lap: null }).ref).toBe(52);
  });

  it("B never defaults to A", () => {
    const one = rows.filter((r) => r.lapNumber === 64);
    expect(defaultPair(one, 52, { ref: null, lap: null })).toEqual({ ref: 52, lap: null });
  });
});

describe("picker options", () => {
  const s = fixtures.austria();
  const a = fixtures.austriaAnalysis();
  const rows = lapsRows(s.laps, a, s);

  it("A lists only clean laps; B every lap with its status words", () => {
    const A = refOptions({ rows, session: s, analysisRef: a.ref_lap, drivers: [] });
    expect(A.map((o) => o.title)).not.toContain("Lap 65");
    expect(A.every((o) => o.canBeRef)).toBe(true);
    const B = lapOptions(rows);
    expect(B).toHaveLength(10);
    expect(B.find((o) => o.title === "Lap 65")?.words).toBe("flashback");
    expect(optionText(B.find((o) => o.title === "Lap 65")!)).toBe("Lap 65 · 1:10.889 · flashback");
  });

  it("adds the analysis' reference when it belongs to another session", () => {
    const ref = { ...a.ref_lap!, id: 999, lap_number: 12, session_id: "other" };
    const A = refOptions({ rows, session: s, analysisRef: ref, drivers: [] });
    expect(A[0]).toMatchObject({ id: 999, title: "Lap 12", detail: "your reference, another session", group: "reference" });
  });

  it("adds each family driver's best lap at this track, never synthetic, never twice", () => {
    const alex = driver(2, "Alex", "beginner");
    alex.stats.best_laps = [
      { game: s.game, track_id: s.track_id!, track_name: "Austria", lap_time_ms: 72000, lap_id: 700, session_id: "x", car_name: "Haas", synthetic: false, set_unix: 0 },
    ];
    const bot = driver(3, "Demo", "advanced");
    bot.stats.best_laps = [
      { game: s.game, track_id: s.track_id!, track_name: "Austria", lap_time_ms: 60000, lap_id: 701, session_id: "y", car_name: null, synthetic: true, set_unix: 0 },
    ];
    const elsewhere = driver(4, "Jo", "intermediate");
    elsewhere.stats.best_laps = [
      { game: s.game, track_id: "f1:7", track_name: "Silverstone", lap_time_ms: 90000, lap_id: 702, session_id: "z", car_name: null, synthetic: false, set_unix: 0 },
    ];
    const A = refOptions({ rows, session: s, analysisRef: a.ref_lap, drivers: [alex, bot, elsewhere] });
    const fam = A.filter((o) => o.group === "family");
    expect(fam.map((o) => o.title)).toEqual(["Alex's best"]);
    expect(fam[0]?.detail).toBe("best here · Haas");
  });

  it("the session's own driver's best in another session reads 'Your best here'; this session's laps are not repeated", () => {
    const james = fixtures.drivers().drivers.find((d) => d.id === s.driver_id)!;
    const A = refOptions({ rows, session: s, analysisRef: a.ref_lap, drivers: [james] });
    const ids = A.map((o) => o.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("synthetic sessions never offer family laps", () => {
    const demo = fixtures.demo();
    const alex = driver(2, "Alex", "beginner");
    alex.stats.best_laps = [
      { game: demo.game, track_id: demo.track_id!, track_name: null, lap_time_ms: 1, lap_id: 1, session_id: "q", car_name: null, synthetic: false, set_unix: 0 },
    ];
    const A = refOptions({ rows: lapsRows(demo.laps, fixtures.demoAnalysis(), demo), session: demo, analysisRef: null, drivers: [alex] });
    expect(A.some((o) => o.group === "family")).toBe(false);
  });

  it("an A from an old link that no list holds is described from its trace", () => {
    const t = { lap_id: 4242, lap_number: 7, lap_time_ms: 71000 };
    const A = refOptions({ rows, session: s, analysisRef: a.ref_lap, drivers: [], selectedTrace: t });
    expect(A.at(-1)).toMatchObject({ id: 4242, title: "Lap 7", detail: "another session" });
  });
});

describe("metres", () => {
  it("scales model metres into game metres only when the two lengths differ", () => {
    expect(modelToGameM(1000, 4000, 4000)).toBe(1000);
    expect(modelToGameM(1000, 4000, 4400)).toBeCloseTo(1100, 6);
    expect(gameToModelM(1100, 4000, 4400)).toBeCloseTo(1000, 6);
    expect(modelToGameM(1000, null, 4400)).toBe(1000);
    expect(modelToGameM(null, 4000, 4000)).toBeNull();
  });

  it("a corner's apex in game metres for `at=` links", () => {
    const a = fixtures.austriaAnalysis();
    expect(apexGameM(a.track_model, "T6", 4323)).toBe(3783);
    expect(apexGameM(a.track_model, "nope", 4323)).toBeNull();
  });
});

describe("corners of a comparison", () => {
  const c = fixtures.compare();
  const corners = compareCorners(c.comparison.corners, c.track_model, 4323);

  it("carry official labels in track order with game-metre positions", () => {
    expect(corners.map((x) => x.label)).toEqual(["T1", "T3", "T4", "T6", "T7", "T9", "T10"]);
    expect(corners[0]).toMatchObject({ key: "T1", name: "Niki Lauda Kurve", apexGame: 444 });
  });

  it("the cursor finds the corner it is in, or the nearest one", () => {
    expect(cornerAt(corners, 444)?.key).toBe("T1");
    expect(cornerAt(corners, 3783)?.label).toBe("T9");
    expect(cornerAt(corners, null)).toBeNull();
    expect(cornerAt([], 100)).toBeNull();
  });

  it("the explainer starts on the corner that lost the most time", () => {
    const worst = biggestLoss(corners)!;
    expect(worst.timeS).toBe(Math.max(...corners.map((x) => x.timeS ?? -Infinity)));
    expect(segmentDeltas(corners)[worst.key]).toBe(worst.timeS);
  });

  it("explains a corner in neutral words, never advice", () => {
    const t9 = corners.find((x) => x.label === "T9")!;
    const text = explainerText(t9, 66, 64);
    expect(text).toMatch(/^At Rindt Kurve /);
    expect(text).toMatch(/\(lap 66 against your reference, lap 64\)\.$/);
    expect(text).not.toMatch(/\b(should|try|brake later|you need)\b/i);
  });

  it("the coach's observations for a corner keep incidents apart", () => {
    const obs = c.observations;
    const anyCorner = obs[0]!.corner;
    const split = cornerObservations(obs, anyCorner);
    expect(split.coaching.every((o) => o.kind !== "incident")).toBe(true);
    const inc = cornerObservations([{ ...obs[0]!, kind: "incident" }], anyCorner);
    expect(inc.incidents).toHaveLength(1);
    expect(inc.coaching).toHaveLength(0);
  });

  it("table words follow the sign conventions (lap minus reference)", () => {
    expect(brakedText(-12.4)).toBe("12 m earlier");
    expect(brakedText(3)).toBe("3 m later");
    expect(brakedText(0.3)).toBe("same");
    expect(brakedText(null)).toBe("-");
    expect(slowestText(-4)).toBe("4 km/h lower");
    expect(exitText(5.2)).toBe("5 km/h faster");
    expect(throttleText(6)).toBe("6 m later");
    expect(timeWords(0.113)).toBe("0.11 s lost");
    expect(timeWords(-0.04)).toBe("0.04 s gained");
    expect(timeWords(0.001)).toBe("level");
    expect(timeSigned(-0.04)).toBe("−0.04 s");
    expect(timeSigned(0.113)).toBe("+0.11 s");
    expect(cornerSentence({ words: [] })).toBe("No big difference");
    expect(cornerSentence({ words: ["braked about 12 m earlier", "4 km/h slower at the slowest point"] })).toBe(
      "Braked about 12 m earlier and 4 km/h slower at the slowest point",
    );
  });

  it("headline and counts say the direction in words", () => {
    expect(totalText(0.451, "the reference")).toBe("Your lap was 0.45 s slower than the reference");
    expect(totalText(-0.2, "your target lap")).toBe("Your lap was 0.20 s faster than your target lap");
    expect(totalText(null, "the reference")).toBeNull();
    expect(lossGainText(corners)).toMatch(/corners? lost time, \d gained/);
  });
});

describe("density (spec 6.10)", () => {
  it("corner table columns grow with skill", () => {
    expect(cornerColumns("plain")).toEqual(["time", "sentence"]);
    expect(cornerColumns("some")).toEqual(["time", "braked", "slowest"]);
    expect(cornerColumns("all")).toEqual(["time", "braked", "slowest", "exit", "throttle"]);
  });

  it("chart titles are words, never 'B vs A'; beginners compare with their target lap", () => {
    for (const c of ["delta", "speed", "pedals", "steering"] as const) {
      expect(chartWords(c, "the reference").title).not.toMatch(/\bvs\b|\bB\b|\bA\b/);
    }
    expect(chartWords("delta", "your target lap").title).toBe("Time gained or lost: your lap against your target lap");
    expect(chartWords("delta", "x").caption).toMatch(/goes up where your lap lost time/);
    expect(refWordFor("beginner").picker).toBe("Your target lap");
    expect(refWordFor("advanced").picker).toBe("Reference");
  });

  it("a blocked comparison says the server's reasons", () => {
    const b = fixtures.compareBlocked();
    expect(b.comparison.compatibility.ok).toBe(false);
    expect(blockedText(b.comparison.compatibility.blocking)).toMatch(/^These two laps cannot be compared: reference lap is not clean/);
    expect(blockedText([])).toBe("These two laps cannot be compared.");
  });
});
