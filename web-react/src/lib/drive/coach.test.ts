import { describe, expect, it } from "vitest";
import {
  NO_REFERENCE_COACHING,
  coachPoint,
  evidenceLine,
  lapPicks,
  pointText,
  rankedObservations,
  needsClamp,
  simpleWording,
  textSize,
  topPoint,
  workOnWentWell,
} from "./coach";
import { fixture, snap } from "./testkit";
import type { ObservationNext } from "./types";

function obs(over: Partial<ObservationNext>): ObservationNext {
  return {
    id: "L6:T9:brake_early",
    kind: "brake_early",
    corner: "T9",
    lap_number: 6,
    ref_lap_number: 4,
    value: -12,
    unit: "m",
    impact_s: 0.11,
    confidence: 0.9,
    text: "Stowe: you braked about 12 m earlier than on your reference lap and lost about 0.11 s here.",
    consistency: null,
    positive: false,
    priority: 0.11,
    ...over,
  };
}

describe("coach card before D6 (top observation for the shown corner)", () => {
  it("shows the highest-priority observation for the corner, verbatim, with its tag", () => {
    const s = fixture("recorded-suzuka-on-track-brake-ahead");
    const p = coachPoint(s, "T7", false, true);
    expect(p).toMatchObject({
      tag: "work_on",
      lap: 4,
      tagText: "Work on · L4",
      text: "Turn 11 (Hairpin): you're braking about 12 m earlier than your reference (lap 3), losing 0.15 s through the corner.",
      size: 26,
      source: "observation",
      corner: "T7",
    });
    // T6 has three observations: the top one by priority wins
    expect(coachPoint(s, "T6", false, true).text).toMatch(/^Turn 9 \(Degner 2\): minimum speed/);
  });

  it("praises with a Good tag", () => {
    const s = fixture("recorded-suzuka-on-track-brake-ahead");
    expect(coachPoint(s, "T4", false, true)).toMatchObject({ tag: "good", tagText: "Good · L4" });
  });

  it("never shows an incident as coaching (the radio skips them too)", () => {
    const s = snap({
      observations: [
        obs({ id: "a", kind: "incident", priority: 2, text: "T9: lost 2.1 s - that looks like an incident" }),
        obs({ id: "b", priority: 0.1 }),
      ],
    });
    expect(coachPoint(s, "T9", false, true).text).toMatch(/^Stowe/);
    expect(rankedObservations(s).map((o) => o.id)).toEqual(["b"]);
  });

  it("says there is no note, or that coaching starts after the first clean lap", () => {
    const s = fixture("recorded-suzuka-on-track-in-corner");
    expect(coachPoint(s, "T1", false, true)).toMatchObject({ tag: null, text: null, empty: "No note for T2 on lap 4" });
    expect(coachPoint(snap({ reference: null }), "T9", false, true).empty).toBe(NO_REFERENCE_COACHING);
    expect(coachPoint(snap(), null, false, true).empty).toBe("No corner ahead yet");
  });
});

describe("coach card with D6 (one message, two channels)", () => {
  it("shows the radio's point for the corner, the short text on track", () => {
    const s = fixture("recorded-d246-suzuka-on-track-brake-ahead");
    const p = coachPoint(s, "T7", false, true);
    expect(p).toMatchObject({ source: "d6", tagText: "Work on · L4", size: 30 });
    expect(p.text).toBe(s.coach?.by_corner.T7?.short);
    expect(p.text!.length).toBeLessThanOrEqual(48);
    // stationary: the full text
    expect(coachPoint(s, "T7", false, false).text).toBe(s.coach?.by_corner.T7?.text);
  });

  it("uses text_simple for simple-wording profiles when stationary, and the block's own wording flag", () => {
    const s = fixture("recorded-d246-suzuka-on-track-brake-ahead");
    expect(coachPoint(s, "T7", true, false).text).toBe(s.coach?.by_corner.T7?.text); // block says simple_wording false
    s.coach = { ...s.coach!, simple_wording: true };
    expect(simpleWording(s, false)).toBe(true);
    expect(coachPoint(s, "T7", false, false).text).toBe(s.coach.by_corner.T7?.text_simple);
    delete s.coach.simple_wording;
    expect(simpleWording(s, true)).toBe(true);
  });

  it("does not fall back to observations when D6 has no point for the corner", () => {
    const s = fixture("recorded-d246-suzuka-on-track-in-corner");
    expect(coachPoint(s, "T1", false, true)).toMatchObject({ text: null, empty: "No note for T2 on lap 4" });
  });

  it("orders a lap's points: picked first, then the other corners, corrective before praise", () => {
    const s = fixture("recorded-d246-suzuka-on-track-brake-ahead");
    const { picks, source } = lapPicks(s);
    expect(source).toBe("d6");
    expect(picks[0]?.id).toBe(s.coach?.picked[0]?.id);
    const firstPraise = picks.findIndex((o) => o.positive);
    expect(picks.slice(firstPraise).every((o) => o.positive)).toBe(true);
    expect(new Set(picks.map((o) => o.id)).size).toBe(picks.length);
  });
});

describe("texts and sizes", () => {
  it("chooses short on track, text_simple for simple profiles, else text", () => {
    const o = obs({ short: "T15: braked 12 m early", text_simple: "At Stowe you braked a bit early." });
    expect(pointText(o, false, true)).toBe("T15: braked 12 m early");
    expect(pointText(o, true, false)).toBe("At Stowe you braked a bit early.");
    expect(pointText(o, false, false)).toBe(o.text);
    expect(pointText(obs({}), true, true)).toBe(obs({}).text);
  });

  it("applies the length rule: 30 px up to 60 characters, never under 26 px while moving, 22 px stationary", () => {
    expect(textSize("x".repeat(60))).toBe(30);
    expect(textSize("x".repeat(61))).toBe(26);
    expect(textSize("x".repeat(400))).toBe(26);
    expect(textSize("x".repeat(20), false)).toBe(22);
    expect(needsClamp("x".repeat(130))).toBe(false);
    expect(needsClamp("x".repeat(131))).toBe(true);
    expect(needsClamp("x".repeat(131), false)).toBe(false);
  });

  it("clamps a long point on track and shows it in full at 22 px when stationary", () => {
    const long = obs({ text: `Stowe: ${"you braked early and ".repeat(8)}lost time.` });
    const s = snap({ observations: [long] });
    expect(coachPoint(s, "T9", false, true)).toMatchObject({ size: 26, clamp: true });
    expect(topPoint(s, false)).toMatchObject({ size: 22, clamp: false, text: long.text });
  });

  it("builds the evidence line from the observation's fields", () => {
    expect(evidenceLine(obs({ consistency: "3 of the last 5 laps", impact_s: 0.123, confidence: 0.82 }))).toBe(
      "Seen on 3 of the last 5 laps · about 0.12 s · confidence high",
    );
    expect(evidenceLine(obs({ impact_s: null, confidence: 0.5 }))).toBe("confidence low");
  });
});

describe("whole-lap picks for the state cards", () => {
  it("gives the pit lane / next run its top corrective point", () => {
    expect(topPoint(fixture("recorded-suzuka-on-track-brake-ahead"), false)?.text).toMatch(/^Turn 9 \(Degner 2\)/);
    expect(topPoint(snap(), false)).toBeNull();
  });

  it("gives the session complete card one Work on and one Went well", () => {
    const { workOn, wentWell } = workOnWentWell(fixture("recorded-austria-session-ended"), false);
    expect(workOn).toMatchObject({ tag: "work_on" });
    expect(wentWell).toMatchObject({ tag: "good" });
    const d6 = workOnWentWell(fixture("recorded-d246-austria-session-ended"), false);
    expect(d6.workOn?.source).toBe("d6");
  });
});
