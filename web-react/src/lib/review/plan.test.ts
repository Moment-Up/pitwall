// Coaching plan logic (spec 6.8) on recorded data: James's Austria sessions in the Haas (D5 computed on a read-only
// copy of the live database) and the newest one's analysis from the live API. Hand-made inputs only for cases the
// recorded data has none of (a corner fixed for two sessions, a live cue plan).
import { describe, expect, it } from "vitest";
import { itemText } from "./coaching";
import {
  cornerTrendAt,
  habits,
  planSession,
  radioFocus,
  recentlyFixed,
  workingOnNow,
  type LiveFocusInput,
} from "./plan";
import { pointsFromProgress, type SessionPoint } from "./progress";
import { fixtures } from "./testkit";

const AUSTRIA = { game: "f1_25", trackId: "f1:17", trackLabel: "Austria" };

function p(id: string, t: number, corners: Record<string, number> | null): SessionPoint {
  return {
    sessionId: id,
    startedUnix: t,
    synthetic: false,
    carId: "f1:team:7",
    carName: "Haas",
    sessionType: "race",
    laps: 8,
    cleanLaps: 6,
    bestMs: 71_000,
    medianMs: null,
    spreadMs: null,
    corners,
    habits: corners ? {} : null,
    refLapId: 52,
  };
}

describe("the plan session", () => {
  it("is the newest compared session with D5, else the newest session", () => {
    const pts = pointsFromProgress(fixtures.progressAustriaHaas());
    expect(planSession(pts)?.sessionId).toBe("332904dbe3de");
    // a newer session that could not be compared does not replace it
    expect(planSession([...pts, p("new", 2e9, null)])?.sessionId).toBe("332904dbe3de");
    // before D5 (no corners at all): the newest session
    expect(planSession([p("a", 1, null), p("b", 2, null)])?.sessionId).toBe("b");
    expect(planSession([])).toBeNull();
  });
});

describe("Working on now", () => {
  it("the coach's ranked corrections, one per corner, at most 3, verbatim, with official labels and D5 trends", () => {
    const pts = pointsFromProgress(fixtures.progressAustriaHaas());
    const w = workingOnNow(fixtures.austriaAnalysis(), pts, "332904dbe3de", 0.02);
    expect(w.length).toBe(3);
    expect(new Set(w.map((x) => x.item.corner)).size).toBe(3);
    for (const x of w) {
      expect(x.item.positive).toBe(false);
      expect(itemText(x.item, false)).toBe(x.item.latest.text); // verbatim
      expect(x.trend).not.toBeNull();
    }
    const t6 = w.find((x) => x.item.corner === "T4");
    if (t6) {
      expect(t6.label).toBe("T6");
      expect(t6.trend).toMatchObject({ trend: "better", sessions: 2 });
      expect(t6.trend!.words).toBe("Session average here: 0.40 s lost a lap, against 0.79 s lost the session before");
    }
  });

  it("without D5 there is no trend; without an analysis nothing", () => {
    const w = workingOnNow(fixtures.austriaAnalysis(), [], null);
    expect(w.length).toBe(3);
    expect(w.every((x) => x.trend === null)).toBe(true);
    expect(workingOnNow(undefined, [], null)).toEqual([]);
    expect(workingOnNow(fixtures.emptyAnalysis(), [], null)).toEqual([]);
  });

  it("a trend compares the plan session with the mean of up to 4 compared sessions before it", () => {
    const pts = [
      p("a", 1, { T1: 0.3 }),
      p("b", 2, { T1: 0.2 }),
      p("c", 3, { T1: 0.1 }),
      p("d", 4, null),
      p("e", 5, { T1: 0.21 }),
    ];
    expect(cornerTrendAt(pts, "e", "T1", 0.02)).toMatchObject({ trend: "same", sessions: 4 });
    expect(cornerTrendAt(pts, "e", "T1", 0.02)!.words).toBe(
      "Session average here: 0.21 s lost a lap, against 0.20 s lost on average over the 3 sessions before",
    );
    expect(cornerTrendAt(pts, "c", "T1", 0.02)).toMatchObject({ trend: "better" });
    expect(cornerTrendAt(pts, "e", "T9", 0.02)).toBeNull();
    expect(cornerTrendAt(pts, "a", "T1", 0.02)).toBeNull();
  });
});

describe("Habits", () => {
  it("only corrections that carry the coach's consistency string, verbatim, in your words", () => {
    const h = habits(fixtures.austriaAnalysis());
    expect(h.length).toBeGreaterThan(0);
    for (const x of h) {
      expect(x.item.latest.consistency).toBeTruthy();
      expect(x.item.positive).toBe(false);
      expect(x.consistency).toMatch(/of your last \d+ laps?/);
    }
    expect(habits(fixtures.emptyAnalysis())).toEqual([]);
  });
});

describe("Recently fixed (D5)", () => {
  it("a corner under the threshold for 2 compared sessions in a row after a loss", () => {
    const pts = [p("a", 1, { T1: 0.21, T2: 0.01 }), p("b", 2, { T1: 0.015, T2: 0.0 }), p("c", 3, { T1: 0.01, T2: 0.05 })];
    const f = recentlyFixed(pts, null, "f1_25", "f1:17", 0.02);
    expect(f.map((x) => [x.key, x.sessions, x.wasS])).toEqual([["T1", 2, 0.21]]);
    expect(f[0]!.words).toBe("Average loss below 0.02 s for 2 sessions (it was 0.21 s a lap)");
  });
  it("needs history: one session under is not fixed yet; never lost is not fixed", () => {
    expect(recentlyFixed([p("a", 1, { T1: 0.2 }), p("b", 2, { T1: 0.01 })], null, "g", "t", 0.02)).toEqual([]);
    expect(recentlyFixed([p("a", 1, { T1: 0.0 }), p("b", 2, { T1: 0.01 }), p("c", 3, { T1: 0.0 })], null, "g", "t", 0.02)).toEqual([]);
    const real = pointsFromProgress(fixtures.progressAustriaHaas());
    expect(recentlyFixed(real, fixtures.progressAustriaHaas().corner_text, "f1_25", "f1:17")).toEqual([]);
  });
});

describe("The radio will focus on", () => {
  const live = (over: Partial<LiveFocusInput> = {}): LiveFocusInput => ({
    seatedId: 1,
    live: { game: "f1_25", track_id: "f1:17" },
    cues: {
      mode: "focus",
      reason: null,
      focus: ["T4"],
      cues: [{ corner: "T4", kind: "brake", target_m: 1200, text: "brake", focus: true, reason: "brake_early on 3 of the last 5 lap(s)" }],
    },
    corners: fixtures.austriaAnalysis().track_model!.corners,
    ...over,
  });
  const james = { id: 1, name: "James" };

  it("the live plan's focus corners with their official labels and reasons", () => {
    expect(radioFocus(live(), james, AUSTRIA)).toEqual({
      state: "focus",
      items: [{ key: "T4", label: "T6", name: null, reason: "braking early · 3 of the last 5 laps" }],
    });
  });

  it("otherwise says why not, in words", () => {
    expect(radioFocus(live(), { id: 2, name: "Alex" }, AUSTRIA)).toMatchObject({ state: "none", reason: expect.stringMatching(/^Alex is not in the seat/) });
    expect(radioFocus(live({ live: null }), james, AUSTRIA)).toMatchObject({ reason: expect.stringMatching(/^No live session at Austria/) });
    expect(radioFocus(live({ live: { game: "f1_25", track_id: "f1:7" } }), james, AUSTRIA).state).toBe("none");
    expect(radioFocus(live({ cues: null }), james, AUSTRIA)).toMatchObject({ reason: "The live data carries no braking-call plan." });
    expect(radioFocus(live({ cues: { mode: "off", reason: null, focus: [], cues: [] } }), james, AUSTRIA)).toMatchObject({
      reason: "Braking calls are off (Drive › Radio).",
    });
    expect(radioFocus(live({ cues: { mode: "focus", reason: "no reference lap yet", focus: [], cues: [] } }), james, AUSTRIA)).toMatchObject({
      reason: "No plan yet: no reference lap yet.",
    });
  });
});
