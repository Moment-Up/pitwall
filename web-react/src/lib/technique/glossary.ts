// Glossary entries for the technique blocks' `?` buttons (feat/technique spec §9; shown for beginner and
// intermediate profiles like the rest of Review's glossary, components/ui/glossary-terms.ts). They EXPLAIN TERMS,
// NEVER ACTIONS (design spec 9.6, P9): no entry tells the driver what to do, and none recommends braking later.
// Definitions follow how the backend measures them (src/pitwall/technique/*).

export type TechniqueTerm = "understeer" | "oversteer" | "trail_braking" | "coasting" | "wheelspin" | "lockup" | "line_offset";

export interface TechniqueGlossaryEntry {
  title: string;
  text: string;
}

export const TECHNIQUE_GLOSSARY: Readonly<Record<TechniqueTerm, TechniqueGlossaryEntry>> = {
  understeer: {
    title: "Understeer",
    text:
      "The front tyres slide more than the rear tyres, so the car turns less than the steering asks and runs wide. " +
      "Pitwall measures it from the game's tyre slip angles at the limit: front minus rear.",
  },
  oversteer: {
    title: "Oversteer",
    text:
      "The rear tyres slide more than the front tyres, so the back of the car swings out and the car turns more than " +
      "the steering asks. A big slide or a moment of opposite lock also counts.",
  },
  trail_braking: {
    title: "Trail braking",
    text:
      "Braking and turning at the same time: some brake is still on as the car turns in, and it fades out towards " +
      "the slowest point of the corner.",
  },
  coasting: {
    title: "Coasting",
    text: "Time with neither pedal pressed: off the brake but not yet on the throttle.",
  },
  wheelspin: {
    title: "Wheelspin",
    text:
      "A driven wheel turning faster than the car is moving, so the tyre slips instead of pushing. Traction control " +
      "limits how much it can happen.",
  },
  lockup: {
    title: "Lock-up",
    text:
      "A wheel turning much slower than the car is moving under braking, up to stopping completely. ABS prevents " +
      "it, so with ABS on there are no lock-ups to measure.",
  },
  line_offset: {
    title: "Line offset",
    text:
      "How far sideways your lap was from the reference lap at the same point of a corner, in metres. Tighter is " +
      "towards the inside of the corner, wider towards the outside. Pitwall does not know where the track edges are.",
  },
};
