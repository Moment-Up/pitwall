import { describe, expect, it } from "vitest";
import { averageLines, averageTimeText, cornerCards, filterCards, filterCounts, lapsSpokenText, liveFocusFor, notesShown, cornersShown, PHONE_CORNERS } from "./corner-cards";
import { fixtures } from "./testkit";

describe("Corners tab (spec 6.6)", () => {
  const a = fixtures.austriaAnalysis();
  const cards = cornerCards(a, a.track_model);

  it("one card per corner, official labels, sorted by average time lost", () => {
    const keys = cards.map((c) => c.key);
    expect(new Set(keys).size).toBe(keys.length);
    expect(keys).toEqual(expect.arrayContaining(a.corner_summary.map((s) => s.corner)));
    const times = cards.map((c) => c.meanTimeS).filter((t): t is number => t != null);
    expect(times).toEqual([...times].sort((x, y) => y - x));
    expect(cards.find((c) => c.key === "T2")?.label).toBe("T3");
  });

  it("keeps every lap where the coach spoke, newest first, with the text verbatim", () => {
    const t2 = cards.find((c) => c.key === "T2")!;
    expect(t2.observations.length).toBeGreaterThan(1);
    const laps = t2.observations.map((o) => o.lapNumber);
    expect(laps).toEqual([...laps].sort((x, y) => y - x));
    const raw = Object.values(a.observations).flat().filter((o) => o.corner === "T2").map((o) => o.text);
    for (const o of t2.observations) expect(raw).toContain(o.text);
  });

  it("incidents are kept, marked, and never make a corner a Work on item", () => {
    const t5 = cards.find((c) => c.key === "T5")!;
    const inc = t5.observations.filter((o) => o.incident);
    expect(inc.length).toBeGreaterThan(0);
    expect(inc.every((o) => o.evidence === "")).toBe(true);
    const onlyIncidents = cornerCards(
      { corner_summary: [], observations: { "1": [{ ...Object.values(a.observations).flat().find((o) => o.kind === "incident")! }] } },
      a.track_model,
    );
    expect(onlyIncidents[0]?.workOn).toBe(false);
  });

  it("filters: Work on, Went well (most gained first), All", () => {
    const counts = filterCounts(cards);
    expect(counts.all).toBe(cards.length);
    expect(filterCards(cards, "work").every((c) => c.workOn)).toBe(true);
    const good = filterCards(cards, "good");
    expect(good.every((c) => c.wentWell)).toBe(true);
    const gt = good.map((c) => c.meanTimeS).filter((t): t is number => t != null);
    expect(gt).toEqual([...gt].sort((x, y) => x - y));
  });

  it("averages in plain words; the time line has words for beginners and a sign for the others", () => {
    const s = a.corner_summary.find((x) => x.corner === "T2")!;
    const lines = averageLines(s);
    expect(lines.map((l) => l.label)).toEqual(["Braked", "Slowest speed"]);
    expect(lines[0]!.value).toMatch(/^about \d+ m (earlier|later) on average, spread \d+ m$/);
    expect(lines[1]!.value).toMatch(/^\d+ km\/h on average, \d+ km\/h (lower|higher) than the reference$/);
    expect(averageTimeText(s, false)).toMatch(/^About 0\.\d\d s a lap lost here, average of \d+ laps$/);
    expect(averageTimeText(s, true)).toMatch(/^\+0\.\d\d s a lap, average of \d+ laps$/);
    expect(averageTimeText(null, true)).toBeNull();
  });

  it("names the laps the coach spoke on", () => {
    expect(lapsSpokenText({ observations: [] })).toBeNull();
    expect(lapsSpokenText({ observations: [{ lapNumber: 7, incident: false } as never] })).toBe("Lap 7");
    expect(
      lapsSpokenText({ observations: [{ lapNumber: 9, incident: false }, { lapNumber: 7, incident: false }, { lapNumber: 5, incident: true }] as never }),
    ).toBe("Laps 9 and 7");
  });

  it("FOCUS comes from the live plan only at the same game and track", () => {
    const snap = { session: { game: "f1_25", track_id: "f1:17" }, cues: { focus: ["T2"] } };
    expect(liveFocusFor(snap, { game: "f1_25", track_id: "f1:17" })).toEqual(["T2"]);
    expect(liveFocusFor(snap, { game: "f1_25", track_id: "f1:7" })).toEqual([]);
    expect(liveFocusFor(null, { game: "f1_25", track_id: "f1:17" })).toEqual([]);
    const withFocus = cornerCards(a, a.track_model, { focus: ["T2"] });
    expect(withFocus.find((c) => c.key === "T2")?.focus).toBe(true);
    expect(withFocus.filter((c) => c.focus)).toHaveLength(1);
  });

  it("no analysis, no cards", () => {
    expect(cornerCards(undefined, null)).toEqual([]);
  });
});

describe("notes per corner (acceptance B7: the phone page stays under 4 000 px)", () => {
  it("3 coach notes a corner on a tablet, 1 on a phone (Show all N opens the rest)", () => {
    expect(notesShown(true)).toBe(3);
    expect(notesShown(false)).toBe(1);
  });
});

describe("corners on a phone (acceptance B7)", () => {
  it("the 5 that cost most, then Show all; every corner on a tablet", () => {
    expect(PHONE_CORNERS).toBe(5);
    expect(cornersShown(false, 11, false)).toBe(5);
    expect(cornersShown(false, 11, true)).toBe(11);
    expect(cornersShown(false, 4, false)).toBe(4);
    expect(cornersShown(true, 11, false)).toBe(11);
  });
});
