// Technique knowledge on coaching points (lib/knowledge/annotation.ts) and where the screens use it: the coach card's
// evidence line (lib/drive/coach.ts), Review › Session › Corners (lib/review/corner-cards.ts) and Review's Work on
// (lib/review/coaching.ts), plus the session variant's style and channels lines (lib/knowledge/view.ts).
//
// Annotations come from a BACKEND fixture (src/test/fixtures/knowledge/backend-annotations-melbourne.json): Pitwall's
// own code over the owner's recorded F1 25 laps, so the words and values are the server's. A point that does not fit
// the driver never happens on F1 25 for the live kinds, so that case is hand-made here ("edited", NOT_FOR_YOU) with the
// server's documented shape.

import { describe, expect, it } from "vitest";
import { coachPoint, rankedObservations } from "../drive/coach";
import { fixture, snap } from "../drive/testkit";
import type { ObservationNext } from "../drive/types";
import type { KnowledgeChannel, KnowledgeStyle } from "../endpoints/knowledge";
import type { ReviewObservation } from "../endpoints/review";
import { workOnItems, itemEvidence } from "../review/coaching";
import { cornerObservations } from "../review/compare";
import { cornerCards, filterCounts, lapsSpokenText } from "../review/corner-cards";
import {
  ALSO_MEASURED_LABEL,
  cardCause,
  causeHeading,
  causeLines,
  evidenceSentence,
  evidenceWords,
  fitsDriver,
  isReason,
  joinLine,
  notForYou,
  tailoredExplanation,
  WHY_LABEL,
  type PointKnowledge,
} from "./annotation";
import { channelsLine, styleLine } from "./view";

interface AnnotationFixture {
  _fixture: { tier: string; source: string; recorded: string; what: string };
  response: {
    review: Record<string, ReviewObservation>;
    coach_point: ObservationNext;
    context: { context: Record<string, unknown>; style: KnowledgeStyle; game: string } | null;
  };
}

const ALL = import.meta.glob<AnnotationFixture>("../../test/fixtures/knowledge/backend-annotations-*.json", {
  eager: true,
  import: "default",
});
const FILE = Object.values(ALL)[0]!;
const review = (key: string): ReviewObservation => structuredClone(FILE.response.review[key]!);

/** Edited (hand-made, the server's documented shape): a point the graph says is for another driver. */
const NOT_FOR_YOU: PointKnowledge = {
  fault: "missed_blip",
  applies: false,
  why_not: "Only for: H-pattern gearbox (gearbox paddles with auto-blip)",
  causes: [],
  advice: null,
};

describe("the backend fixture", () => {
  it("is a labelled backend fixture of real annotations", () => {
    expect(FILE._fixture.tier).toBe("backend");
    expect(FILE._fixture.source).toMatch(/recorded F1 25 laps/);
    expect(Object.keys(FILE.response.review)).toEqual(
      expect.arrayContaining(["over_braking", "low_grip", "traction_limited", "none", "tailored"]),
    );
    // traction control was on in these laps: "no grip loss on the exit" is never named then
    expect(Object.keys(FILE.response.review)).not.toContain("ready_earlier");
    expect(FILE.response.context!.context.traction_control).toBe(true);
    // the snapshot-sized coach block copy: evidence as measured values, without the plain-words test
    const slimEvidence = FILE.response.coach_point.knowledge!.causes[0]!.evidence!;
    expect(slimEvidence.length).toBeGreaterThan(0);
    expect(slimEvidence.every((e) => !("test" in e) && typeof e.signal === "string")).toBe(true);
    // every cause says whether its base-rate check showed it tells its fault apart: on these laps only the early
    // brake release does, and the coach block's copy carries only such causes
    const causes = Object.values(FILE.response.review).flatMap((o) => o.knowledge?.causes ?? []);
    expect(causes.every((c) => typeof c.discriminates === "boolean")).toBe(true);
    expect([...new Set(causes.filter((c) => c.discriminates).map((c) => c.id))]).toEqual(["early_brake_release"]);
    expect(FILE.response.coach_point.knowledge!.causes.every((c) => c.discriminates === true)).toBe(true);
  });
});

describe("annotation helpers", () => {
  it("a point fits unless its annotation says it does not (no annotation fits, as before the graph)", () => {
    expect(fitsDriver(review("over_braking"))).toBe(true);
    expect(fitsDriver({})).toBe(true);
    expect(fitsDriver({ knowledge: null })).toBe(true);
    expect(fitsDriver({ knowledge: NOT_FOR_YOU })).toBe(false);
    expect(notForYou({ knowledge: NOT_FOR_YOU })).toBe("Only for: H-pattern gearbox (gearbox paddles with auto-blip)");
    expect(notForYou({ knowledge: { ...NOT_FOR_YOU, why_not: null } })).toBe("Not for this driver and car");
    expect(notForYou(review("over_braking"))).toBeNull();
  });

  it("the card's cause line is the screen line of the first cause that tells its fault apart, verbatim", () => {
    expect(cardCause(review("early_brake_release"))).toBe("Braking ended sooner, longer roll after");
    expect(cardCause(FILE.response.coach_point)).toBe(FILE.response.coach_point.knowledge!.causes[0]!.screen);
    // measured, but about as common without the fault (its base rate): never the card's reason
    expect(cardCause(review("over_braking"))).toBeNull();
    expect(cardCause(review("low_grip"))).toBeNull();
    expect(cardCause(review("traction_limited"))).toBeNull();
    expect(cardCause(review("none"))).toBeNull();
    expect(cardCause({ knowledge: { ...NOT_FOR_YOU, causes: review("early_brake_release").knowledge!.causes } })).toBeNull();
    // edited (the server's shape): a reason after a cause only also measured is still the card's line
    const both = review("over_braking");
    both.knowledge!.causes = [...both.knowledge!.causes, ...review("early_brake_release").knowledge!.causes];
    expect(cardCause(both)).toBe("Braking ended sooner, longer roll after");
    // edited: an older server's slim copy without the flag is not shown as the reason
    const old = { ...FILE.response.coach_point.knowledge!, causes: [{ id: "x", name: "X", screen: "Old" }] };
    expect(cardCause({ knowledge: old })).toBeNull();
    expect(isReason({ id: "x", name: "X" })).toBe(false);
  });

  it("evidence in words: the test and the signed value measured on the lap; a yes/no test is its words", () => {
    const [brake, entry] = review("over_braking").knowledge!.causes[0]!.evidence!;
    expect(evidenceWords(brake!)).toBe("braked at least 8 m earlier than on the reference lap (measured −9.6 m)");
    expect(evidenceWords(entry!)).toBe("at least 4 km/h slower at the corner entry than on the reference lap (measured −18 km/h)");
    const grip = review("low_grip").knowledge!.causes[0]!.evidence![0]!;
    expect(evidenceWords(grip)).toBe(grip.test);
    expect(evidenceWords({ test: "a wheel locked in the braking zone", value: 2, unit: "count" })).toBe(
      "a wheel locked in the braking zone (measured 2 times)",
    );
    expect(evidenceWords({ test: "no wheelspin on the way out", value: 0, unit: "count" })).toBe(
      "no wheelspin on the way out (measured 0 times)",
    );
    // edited (the server's shape): this lap's exit balance is a value, not a lap-minus-reference delta - no "+",
    // the sign only where the value is negative, and degrees in words
    const balance = { signal: "exit_balance_deg", test: "no clear understeer on the way out", unit: "deg" };
    expect(evidenceWords({ ...balance, value: 1.33 })).toBe("no clear understeer on the way out (measured 1.3 degrees)");
    expect(evidenceWords({ ...balance, value: -2 })).toBe("no clear understeer on the way out (measured −2 degrees)");
    expect(evidenceWords({ signal: "brake_point_delta_m", test: "braked earlier", value: 12, unit: "m" })).toBe(
      "braked earlier (measured +12 m)",
    );
  });

  it("cause lines carry every measured cause with its evidence: 'Why' only for one that tells its fault apart", () => {
    const lines = causeLines(review("traction_limited"));
    expect(lines).toHaveLength(1);
    expect(lines[0]).toMatchObject({
      id: "traction_limited",
      line: "More wheelspin or sliding than your reference",
      reason: false,
      label: ALSO_MEASURED_LABEL,
    });
    expect(lines[0]!.evidence[0]).toBe("the back of the car slid or needed a counter-steer on the way out, and not on the reference lap");
    expect(causeHeading(lines[0]!)).toBe("Also measured on this lap: More wheelspin or sliding than your reference.");
    const [why] = causeLines(review("early_brake_release"));
    expect(why).toMatchObject({ id: "early_brake_release", reason: true, label: WHY_LABEL });
    expect(causeHeading(why!)).toBe("Why: Braking ended sooner, longer roll after.");
    // edited (the server's shape): the reasons come first, then what was also measured, each in the server's order
    const both = review("over_braking");
    both.knowledge!.causes = [...both.knowledge!.causes, ...review("early_brake_release").knowledge!.causes];
    expect(causeLines(both).map((c) => [c.id, c.label])).toEqual([
      ["early_brake_release", "Why"],
      ["over_braking", "Also measured on this lap"],
    ]);
    expect(causeLines(review("none"))).toEqual([]);
    expect(causeLines({ knowledge: NOT_FOR_YOU })).toEqual([]);
    // the words never say "why" or "because" about a cause only also measured
    for (const key of ["over_braking", "low_grip", "early_turn_in", "waiting_for_rotation", "traction_limited"]) {
      for (const c of causeLines(review(key))) expect(causeHeading(c)).not.toMatch(/\bwhy\b|\bbecause\b/i);
    }
  });

  it("an explanation shows only when written for the driver's skill or style", () => {
    // the trail-braking driver's coasting explanation (the owner's detected style on these laps)
    expect(tailoredExplanation(review("tailored"))).toMatch(/^You usually keep some brake on into the turn/);
    // the braking assist was on in these laps: the style's explanation says some of the braking was the game's
    expect(tailoredExplanation(review("tailored"))).toMatch(/The game's braking assist was on, so some of that braking was the game's\.$/);
    // the general wording: the coach's own text already says it
    expect(tailoredExplanation(review("over_braking"))).toBeNull();
  });

  it("makes a cause's evidence one sentence", () => {
    const [line] = causeLines(review("over_braking"));
    expect(evidenceSentence(line!.evidence)).toBe(
      "Braked at least 8 m earlier than on the reference lap (measured −9.6 m); at least 4 km/h slower at the corner entry than on the reference lap (measured −18 km/h).",
    );
    expect(evidenceSentence([])).toBe("");
  });

  it("joins parts, dropping empty ones", () => {
    expect(joinLine("a", null, "", "b")).toBe("a · b");
    expect(joinLine(null, undefined)).toBeNull();
  });
});

describe("the coach card", () => {
  it("leads the evidence line with a cause that tells its fault apart (shown when stationary)", () => {
    const s = fixture("recorded-d246-suzuka-on-track-brake-ahead");
    const before = coachPoint(s, "T7", false, false).evidence;
    // edited: the recorded D6 block's T7 point given the backend fixture's slim annotation
    s.coach!.by_corner.T7 = { ...s.coach!.by_corner.T7!, knowledge: FILE.response.coach_point.knowledge };
    const p = coachPoint(s, "T7", false, false);
    expect(p.evidence).toBe(joinLine(FILE.response.coach_point.knowledge!.causes[0]!.screen, before));
    expect(p.evidence).toMatch(/^Braking ended sooner, longer roll after · /);
    expect(p.text).toBe(s.coach!.by_corner.T7!.text); // the coach's own text is unchanged
    // edited: a cause that was only also measured (an older server's slim copy sent every cause) never leads it
    const measured = review("over_braking").knowledge!;
    s.coach!.by_corner.T7 = { ...s.coach!.by_corner.T7!, knowledge: measured };
    expect(coachPoint(s, "T7", false, false).evidence).toBe(before);
  });

  it("before D6, a point the graph says is for another driver is never the card's point", () => {
    const fits = { ...review("over_braking"), corner: "T9", priority: 0.1 } as ObservationNext;
    const other = { ...review("none"), id: "x", corner: "T9", priority: 0.9, knowledge: NOT_FOR_YOU } as ObservationNext;
    const s = snap({ observations: [other, fits] });
    expect(rankedObservations(s).map((o) => o.id)).toEqual([fits.id]);
    expect(coachPoint(s, "T9", false, false).text).toBe(fits.text);
  });
});

describe("Review", () => {
  const notMine = (lap: number): ReviewObservation => ({
    ...review("none"),
    id: `L${lap}:T6:missed_blip`,
    kind: "missed_blip",
    lap_number: lap,
    knowledge: NOT_FOR_YOU,
  });

  it("Corners: a point for another driver is greyed with its reason and counts for neither filter", () => {
    const ob = review("over_braking");
    const other = notMine(1);
    expect(other.corner).not.toBe(ob.corner);
    const analysis = { corner_summary: [], observations: { "201": [other], "202": [ob] } };
    const cards = cornerCards(analysis, null);
    const greyed = cards.find((c) => c.key === other.corner)!;
    expect(greyed.workOn).toBe(false);
    expect(greyed.observations[0]).toMatchObject({ notForYou: NOT_FOR_YOU.why_not, causes: [], explain: null });
    expect(lapsSpokenText(greyed)).toBeNull();
    const coached = cards.find((c) => c.key === ob.corner)!;
    expect(coached.workOn).toBe(true);
    expect(coached.observations[0]!.causes[0]).toMatchObject({
      id: "over_braking",
      line: "Braked earlier, reached the corner slower",
      reason: false,
      label: "Also measured on this lap",
    });
    expect(coached.observations[0]!.causes[0]!.evidence[0]).toMatch(/\(measured −9\.6 m\)$/);
    expect(filterCounts(cards)).toMatchObject({ work: 1 });
  });

  it("Compare: a point for another driver is kept apart from the coach's point at the corner", () => {
    const mine = { ...review("none"), priority: 0.1 };
    const other = { ...notMine(1), corner: mine.corner, priority: 0.9 };
    const split = cornerObservations([other, mine], mine.corner);
    expect(split.coaching.map((o) => o.id)).toEqual([mine.id]);
    expect(split.notForYou.map((o) => o.id)).toEqual([other.id]);
    expect(split.incidents).toEqual([]);
  });

  it("Corners: a coasting point for a trail-braking driver carries the style's explanation", () => {
    const cards = cornerCards({ corner_summary: [], observations: { "203": [review("tailored")] } }, null);
    expect(cards[0]!.observations[0]!.explain).toMatch(/^You usually keep some brake on into the turn/);
  });

  it("Work on: a point for another driver is no item; the evidence line leads only with a cause that tells it apart", () => {
    const ob = review("over_braking");
    const analysis = { observations: { "201": [notMine(1)], "202": [ob] }, comparisons: {} };
    const items = workOnItems(analysis);
    expect(items.map((i) => i.kind)).toEqual(["low_min_speed"]);
    expect(itemEvidence(items[0]!)).not.toMatch(/Braked earlier, reached the corner slower/); // only also measured
    const ebr = review("early_brake_release");
    const coasting = workOnItems({ observations: { "203": [ebr] }, comparisons: {} });
    expect(itemEvidence(coasting[0]!)).toMatch(/^Braking ended sooner, longer roll after · /);
  });
});

describe("How corners work: the session variant's style and channels", () => {
  it("says how the braking style was read, in counts", () => {
    const style = FILE.response.context!.style;
    expect(styleLine(style)).toBe(
      `From ${style.laps} clean laps: the brake still on into the turn at ${style.trail_corners} of ${style.braking_corners} braking corners, a roll off both pedals at ${style.coast_corners}. The game's braking assist was on, so some of that braking was the game's.`,
    );
    // the owner's recorded laps ran the F1 braking assist: the line says some of the braking was the game's
    expect(style.braking_assist).toBeGreaterThanOrEqual(1);
    expect(styleLine({ ...style, braking_assist: null })).not.toMatch(/assist/);
    expect(styleLine({ ...style, enough: false }, "Alex")).toBe(
      "Not enough clean laps in Alex's last session here to tell Alex's braking style yet.",
    );
    // a game with no steering (Assetto Corsa, GT7 variant A): the style is unknown, never "straight-line"
    const unsteered = { ...style, braking_style: null, enough: false, braking_corners: 0, trail_corners: 0, unsteered_corners: 24, no_steering: true };
    expect(styleLine(unsteered, "Alex")).toBe("This game sends no steering, so Pitwall cannot tell Alex's braking style here.");
    expect(styleLine(null)).toBeNull();
  });

  it("names what the game does not send, with its caveats; unknown is never absent", () => {
    // edited: GT7's channels in the server's documented shape (pitwall.knowledge.context.channels_payload)
    const gt7: Record<string, KnowledgeChannel> = {
      throttle: { status: "sent", words: "throttle", caveat: "On GT7 variants A and B the throttle is after traction control: the car's throttle, not the pedal." },
      g_lat: { status: "not_sent", words: "lateral g", caveat: null },
      wheel_slip: { status: "not_sent", words: "wheel slip", caveat: null },
      steering: { status: "unknown", words: "steering", caveat: null },
    };
    expect(channelsLine(gt7)).toBe(
      "This game does not send lateral g or wheel slip, so checks that need them do not apply here. On GT7 variants A and B the throttle is after traction control: the car's throttle, not the pedal.",
    );
    expect(channelsLine({ steering: { status: "unknown", words: "steering", caveat: null } })).toBeNull();
    expect(channelsLine(null)).toBeNull();
  });
});
