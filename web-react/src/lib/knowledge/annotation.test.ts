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
  cardCause,
  causeLines,
  evidenceSentence,
  evidenceWords,
  fitsDriver,
  joinLine,
  notForYou,
  tailoredExplanation,
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
      expect.arrayContaining(["over_braking", "low_grip", "ready_earlier", "none", "tailored"]),
    );
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

  it("the card's cause line is the first measured cause's screen line, verbatim", () => {
    expect(cardCause(review("over_braking"))).toBe("Braked earlier, reached the corner slower");
    expect(cardCause(review("low_grip"))).toBe("More sliding here than on your reference");
    expect(cardCause(FILE.response.coach_point)).toBe(FILE.response.coach_point.knowledge!.causes[0]!.screen);
    expect(cardCause(review("none"))).toBeNull();
    expect(cardCause({ knowledge: { ...NOT_FOR_YOU, causes: review("over_braking").knowledge!.causes } })).toBeNull();
  });

  it("evidence in words: the test and the signed value measured on the lap; a yes/no test is its words", () => {
    const [brake, entry] = review("over_braking").knowledge!.causes[0]!.evidence!;
    expect(evidenceWords(brake!)).toBe("braked at least 8 m earlier than on the reference lap (measured −8.6 m)");
    expect(evidenceWords(entry!)).toBe("at least 4 km/h slower at the corner entry than on the reference lap (measured −10 km/h)");
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

  it("cause lines carry every measured cause with its evidence", () => {
    const lines = causeLines(review("ready_earlier"));
    expect(lines).toHaveLength(1);
    expect(lines[0]).toMatchObject({ id: "ready_earlier", line: "No wheelspin or slide, full throttle later" });
    expect(lines[0]!.evidence).toHaveLength(3);
    expect(causeLines(review("none"))).toEqual([]);
    expect(causeLines({ knowledge: NOT_FOR_YOU })).toEqual([]);
  });

  it("an explanation shows only when written for the driver's skill or style", () => {
    // the trail-braking driver's coasting explanation (the owner's detected style on these laps)
    expect(tailoredExplanation(review("tailored"))).toMatch(/^You usually keep some brake on into the turn/);
    // the general wording: the coach's own text already says it
    expect(tailoredExplanation(review("over_braking"))).toBeNull();
  });

  it("makes a cause's evidence one sentence", () => {
    const [line] = causeLines(review("over_braking"));
    expect(evidenceSentence(line!.evidence)).toBe(
      "Braked at least 8 m earlier than on the reference lap (measured −8.6 m); at least 4 km/h slower at the corner entry than on the reference lap (measured −10 km/h).",
    );
    expect(evidenceSentence([])).toBe("");
  });

  it("joins parts, dropping empty ones", () => {
    expect(joinLine("a", null, "", "b")).toBe("a · b");
    expect(joinLine(null, undefined)).toBeNull();
  });
});

describe("the coach card", () => {
  it("leads the evidence line with the measured cause (shown when stationary)", () => {
    const s = fixture("recorded-d246-suzuka-on-track-brake-ahead");
    const before = coachPoint(s, "T7", false, false).evidence;
    // edited: the recorded D6 block's T7 point given the backend fixture's slim annotation
    s.coach!.by_corner.T7 = { ...s.coach!.by_corner.T7!, knowledge: FILE.response.coach_point.knowledge };
    const p = coachPoint(s, "T7", false, false);
    expect(p.evidence).toBe(joinLine(FILE.response.coach_point.knowledge!.causes[0]!.screen, before));
    expect(p.text).toBe(s.coach!.by_corner.T7!.text); // the coach's own text is unchanged
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
    const analysis = { corner_summary: [], observations: { "201": [notMine(1)], "202": [review("over_braking")] } };
    const cards = cornerCards(analysis, null);
    const t6 = cards.find((c) => c.key === "T6")!;
    expect(t6.workOn).toBe(false);
    expect(t6.observations[0]).toMatchObject({ notForYou: NOT_FOR_YOU.why_not, causes: [], explain: null });
    expect(lapsSpokenText(t6)).toBeNull();
    const t4 = cards.find((c) => c.key === "T4")!;
    expect(t4.workOn).toBe(true);
    expect(t4.observations[0]!.causes[0]).toMatchObject({ id: "over_braking", line: "Braked earlier, reached the corner slower" });
    expect(t4.observations[0]!.causes[0]!.evidence[0]).toMatch(/\(measured −8\.6 m\)$/);
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

  it("Work on: a point for another driver is no item, and its evidence line leads with the cause", () => {
    const ob = review("over_braking");
    const analysis = { observations: { "201": [notMine(1)], "202": [ob] }, comparisons: {} };
    const items = workOnItems(analysis);
    expect(items.map((i) => i.kind)).toEqual(["low_min_speed"]);
    expect(itemEvidence(items[0]!)).toMatch(/^Braked earlier, reached the corner slower · /);
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
