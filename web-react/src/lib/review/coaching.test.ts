import { describe, expect, it } from "vitest";
import type { ReviewObservation, SessionAnalysis } from "../endpoints/review";
import {
  coachingCounts,
  flatObservations,
  groupObservations,
  itemEvidence,
  itemText,
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
