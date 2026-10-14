import { describe, expect, it } from "vitest";
import type { ReviewObservation, SessionAnalysis } from "../endpoints/review";
import {
  coachingCounts,
  cornerLaps,
  fixedItems,
  flatObservations,
  groupObservations,
  isBigOneOff,
  itemEvidence,
  itemText,
  oneToWorkOn,
  rankItems,
  wentWellItems,
  workOnItems,
} from "./coaching";
import { cornerIdentity } from "./corners";
import { fixtures } from "./testkit";

function obs(p: Partial<ReviewObservation> & Pick<ReviewObservation, "corner" | "kind" | "lap_number">): ReviewObservation {
  return {
    id: `L${p.lap_number}:${p.corner}:${p.kind}`,
    ref_lap_number: 1,
    value: 0,
    unit: "",
    impact_s: 0.1,
    confidence: 1,
    text: `${p.corner} ${p.kind} on lap ${p.lap_number}`,
    consistency: null,
    positive: false,
    priority: 0.1,
    ...p,
  };
}

function analysis(byLap: Record<number, ReviewObservation[]>, compared = Object.keys(byLap).length): SessionAnalysis {
  return {
    session_id: "s",
    ref_lap_id: 1,
    ref_lap: null,
    track_model: null,
    corner_summary: [],
    observations: Object.fromEntries(Object.entries(byLap).map(([k, v]) => [k, v])),
    comparisons: Object.fromEntries(
      Array.from({ length: compared }, (_, i) => [
        String(i + 2),
        { cmp_lap_number: i + 2, total_delta_s: 0, compatibility: { ok: true, blocking: [], warnings: [] }, corners: [] },
      ]),
    ),
  };
}

describe("Work on from a recorded race (Austria)", () => {
  const a = fixtures.austriaAnalysis();
  const items = workOnItems(a);

  it("ranks the habit seen on every lap first, one card per corner, incidents left out", () => {
    expect(items.map((i) => `${i.corner}:${i.kind}`)).toEqual([
      "T4:low_min_speed",
      "T5:low_min_speed",
      "T2:brake_late_overdrive",
      "T3:low_min_speed",
      "T1:brake_early",
    ]);
    expect(items.some((i) => i.kind === "incident")).toBe(false);
    expect(new Set(items.map((i) => i.corner)).size).toBe(items.length);
  });

  it("the top card carries the newest occurrence, verbatim, with its evidence", () => {
    const top = items[0]!;
    expect(top.seen).toBe(9);
    expect(top.compared).toBe(9);
    expect(top.latestLapId).toBe(59);
    expect(top.latest.lap_number).toBe(71);
    expect(itemText(top, false)).toBe(
      "Turn 6: minimum speed is 9 km/h lower than your reference (164 vs 173 km/h), losing 0.23 s through the corner.",
    );
    expect(itemEvidence(top)).toBe("Seen on 6 of your last 6 laps · about 0.23 s a lap · confidence high");
    expect(cornerIdentity(a.track_model, top.corner).full).toBe("T6");
  });

  it("went well: positives by corner, at most three", () => {
    const good = wentWellItems(a);
    expect(good.map((i) => i.corner)).toEqual(["T6", "T7", "T1"]);
    expect(good.every((i) => i.positive)).toBe(true);
    expect(cornerIdentity(a.track_model, "T6").full).toBe("T9 Rindt Kurve");
    expect(wentWellItems(a, 1)).toHaveLength(1);
  });

  it("counts for the Last session card", () => {
    expect(coachingCounts(a)).toEqual({ workOn: 5, wentWell: 3 });
  });
});

describe("grouping and ranking rules", () => {
  it("a habit outranks a bigger one-off (priority per compared lap)", () => {
    const a = analysis({
      2: [obs({ corner: "T1", kind: "brake_early", lap_number: 2, priority: 0.9, impact_s: 0.9 })],
      3: [obs({ corner: "T2", kind: "low_min_speed", lap_number: 3, priority: 0.4 })],
      4: [obs({ corner: "T2", kind: "low_min_speed", lap_number: 4, priority: 0.4 })],
      5: [obs({ corner: "T2", kind: "low_min_speed", lap_number: 5, priority: 0.4 })],
      6: [],
    });
    expect(workOnItems(a).map((i) => i.corner)).toEqual(["T2", "T1"]);
  });

  it("ties go to the point seen on more laps, then the larger impact", () => {
    const items = groupObservations(
      analysis({
        2: [
          obs({ corner: "T1", kind: "a", lap_number: 2, priority: 0.2, impact_s: 0.2 }),
          obs({ corner: "T2", kind: "a", lap_number: 2, priority: 0.1, impact_s: 0.3 }),
          obs({ corner: "T3", kind: "a", lap_number: 2, priority: 0.2, impact_s: 0.5 }),
        ],
        3: [obs({ corner: "T2", kind: "a", lap_number: 3, priority: 0.1, impact_s: 0.3 })],
      }),
    );
    expect(rankItems(items).map((i) => i.corner)).toEqual(["T2", "T3", "T1"]);
  });

  it("uses text_simple (D6) for simple wording when the backend sends it, else the full text", () => {
    const [item] = groupObservations(
      analysis({ 2: [obs({ corner: "T1", kind: "a", lap_number: 2, text: "full", text_simple: "simple" })] }),
    );
    expect(itemText(item!, true)).toBe("simple");
    expect(itemText(item!, false)).toBe("full");
    const [old] = groupObservations(analysis({ 2: [obs({ corner: "T1", kind: "a", lap_number: 2, text: "full" })] }));
    expect(itemText(old!, true)).toBe("full");
  });

  it("falls back to the session's own count when the coach gave no consistency", () => {
    const [item] = workOnItems(
      analysis(
        {
          2: [obs({ corner: "T1", kind: "a", lap_number: 2, impact_s: 0.2, confidence: 0.7 })],
          3: [obs({ corner: "T1", kind: "a", lap_number: 3, impact_s: 0.4, confidence: 0.7 })],
        },
        5,
      ),
    );
    expect(itemEvidence(item!)).toBe("Seen on 2 of 5 laps compared · about 0.40 s a lap · confidence medium");
  });

  it("nothing to show without an analysis", () => {
    expect(workOnItems(null)).toEqual([]);
    expect(wentWellItems(undefined)).toEqual([]);
    expect(flatObservations(fixtures.emptyAnalysis())).toEqual([]);
    expect(coachingCounts(fixtures.emptyAnalysis())).toEqual({ workOn: 0, wentWell: 0 });
  });

  it("works on the SYNTHETIC demo (shape only: never game evidence)", () => {
    const items = workOnItems(fixtures.demoAnalysis());
    expect(items.length).toBeGreaterThan(0);
    expect(items.every((i) => !i.positive && i.kind !== "incident")).toBe(true);
  });
});

// Habits spec 6: the dashboard mirror of motivation/recap.py (the report's "One to work on" and its "sorted" Went well).
describe("habits, not one-offs (recap.py mirror)", () => {
  /** Laps 2..n compared: `times[lap][corner]` is the corner's time against the reference (the comparison's corners). */
  function session(
    byLap: Record<number, ReviewObservation[]>,
    times: Record<number, Record<string, number | null>>,
    unusable: number[] = [],
  ): SessionAnalysis {
    const a = analysis(byLap, 0);
    a.comparisons = Object.fromEntries(
      Object.entries(times).map(([lap, corners]) => [
        lap,
        {
          cmp_lap_number: Number(lap),
          total_delta_s: 0,
          compatibility: { ok: !unusable.includes(Number(lap)), blocking: [], warnings: [] },
          corners: Object.entries(corners).map(([corner, t]) => ({ corner, time_delta_s: t })),
        },
      ]),
    );
    return a;
  }
  const t = (lap: number, kind: string, corner: string, impact = 0.2, extra: Partial<ReviewObservation> = {}) =>
    obs({ corner, kind, lap_number: lap, impact_s: impact, priority: impact * 0.9, confidence: 0.9, ...extra });

  it("knows the laps each corner was compared on, with its time", () => {
    const a = session(
      { 2: [t(2, "low_min_speed", "T2", 0.07)], 3: [t(3, "incident", "T1", 3)], 5: [t(5, "low_min_speed", "T3", 0.1)] },
      { 2: { T1: 0.1, T2: null }, 3: { T1: 3, T2: 0.01 }, 4: { T1: 0.2 } },
      [4],
    );
    const laps = cornerLaps(a);
    // T1: lap 3 was an incident there, lap 4's comparison was not usable; T2's unknown time is the observation's loss;
    // T3 shows on lap 5 only through its observation
    expect([...laps].map(([c, m]) => [c, [...m]])).toEqual([
      ["T1", [[2, 0.1]]],
      ["T2", [[2, 0.07], [3, 0.01]]],
      ["T3", [[5, 0.1]]],
    ]);
  });

  it("the one to work on is a habit still there, not a bigger one-off, and never a small one-off", () => {
    const a = session(
      {
        2: [t(2, "low_min_speed", "T6", 0.15)],
        3: [t(3, "low_min_speed", "T6", 0.15)],
        4: [t(4, "brake_early", "T4", 0.9)],
        5: [t(5, "low_min_speed", "T6", 0.15)],
        6: [t(6, "low_min_speed", "T6", 0.15)],
      },
      Object.fromEntries([2, 3, 4, 5, 6, 7].map((l) => [l, { T4: 0, T6: 0 }])),
    );
    expect(rankItems(groupObservations(a).filter((i) => !i.positive))[0]?.key).toBe("T4:brake_early");
    expect(oneToWorkOn(a)?.key).toBe("T6:low_min_speed");
    // without the habit: the big one-off (0.30 s+, confidence 0.8+); a small one-off is nobody's lesson
    const one = session({ 2: [t(2, "brake_early", "T4", 0.9)], 3: [t(3, "coasting", "T5", 0.29)] }, { 2: { T4: 0.9 }, 3: { T5: 0.29 } });
    expect(oneToWorkOn(one)?.key).toBe("T4:brake_early");
    const small = session({ 3: [t(3, "coasting", "T5", 0.29)] }, { 2: { T5: 0 }, 3: { T5: 0.29 } });
    expect(oneToWorkOn(small)).toBeNull();
    expect(workOnItems(small).map((i) => i.key)).toEqual(["T5:coasting"]); // still listed, just not the one
    // a habit by the coach's own consistency is no one-off
    expect(isBigOneOff(t(2, "brake_early", "T4", 0.9, { consistency_ratio: 0.6 }))).toBe(false);
    expect(isBigOneOff(t(2, "brake_early", "T4", 0.9, { confidence: 0.7 }))).toBe(false);
    expect(isBigOneOff(t(2, "brake_early", "T4", 0.9))).toBe(true);
  });

  it("a habit clean on its corner's last 3 laps is fixed: it leaves Work on, another point stands for the corner", () => {
    const byLap = {
      2: [t(2, "brake_early", "T1", 0.2, { value: -14 })],
      3: [t(3, "brake_early", "T1", 0.25, { value: -16 })],
      4: [t(4, "coasting", "T1", 0.03)],
    };
    const times = { 2: { T1: 0.2 }, 3: { T1: 0.25 }, 4: { T1: 0.03 }, 5: { T1: 0 }, 6: { T1: -0.05 }, 7: { T1: 0.01 } };
    const a = session(byLap, times);
    expect(fixedItems(a).map((i) => i.key)).toEqual(["T1:brake_early"]);
    expect(workOnItems(a).map((i) => i.key)).toEqual(["T1:coasting"]);
    expect(oneToWorkOn(a)).toBeNull(); // the coasting is a small one-off, the braking is fixed
  });

  it("fixed needs three clean laps after it, and for braking early a faster corner on each", () => {
    const byLap = { 2: [t(2, "brake_early", "T1", 0.2)], 3: [t(3, "brake_early", "T1", 0.25)] };
    const after = (t5: number | null, t6: number | null, t7: number | null) =>
      session(byLap, { 2: { T1: 0.2 }, 3: { T1: 0.25 }, 5: { T1: t5 }, 6: { T1: t6 }, 7: { T1: t7 } });
    expect(fixedItems(after(0, 0.19, 0))).toHaveLength(1);
    expect(fixedItems(after(0, 0.2, 0))).toEqual([]); // not faster than its best lap with the habit (0.20 s lost)
    expect(fixedItems(after(0, null, 0))).toEqual([]); // unknown stays unknown
    expect(fixedItems(session(byLap, { 2: { T1: 0.2 }, 3: { T1: 0.25 }, 5: { T1: 0 }, 6: { T1: 0 } }))).toEqual([]);
    // another kind is fixed without the time rule; a correction of any kind there on those laps is not clean
    const speed = { 2: [t(2, "low_min_speed", "T6")], 3: [t(3, "low_min_speed", "T6")] };
    const times = { 2: { T6: 0.2 }, 3: { T6: 0.2 }, 4: { T6: null }, 5: { T6: 0.3 }, 6: { T6: null } };
    expect(fixedItems(session(speed, times)).map((i) => i.key)).toEqual(["T6:low_min_speed"]);
    expect(fixedItems(session({ ...speed, 6: [t(6, "late_throttle", "T6", 0.05)] }, times))).toEqual([]);
    const item = groupObservations(session(speed, times)).find((i) => i.key === "T6:low_min_speed")!;
    expect(item).toMatchObject({ lapIds: [2, 3], recent: false, fixed: true });
  });

  it("the recorded Austria race: its one to work on is its top habit, still there; nothing there is fixed", () => {
    const a = fixtures.austriaAnalysis();
    expect(oneToWorkOn(a)?.key).toBe("T4:low_min_speed");
    expect(fixedItems(a)).toEqual([]);
    // T2 braked early on 3 laps, none of its last 3; but those were not clean there (minimum speed): not fixed
    const t2 = groupObservations(a).find((i) => i.key === "T2:brake_early")!;
    expect(t2).toMatchObject({ seen: 3, recent: false, fixed: false });
  });
});
