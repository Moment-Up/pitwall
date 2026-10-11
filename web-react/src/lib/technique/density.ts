// How much technique detail each skill level sees (feat/technique spec §9, design spec 6.10). Like the rest of
// Review, the level is the VIEWED session's driver's (lib/review/density.ts), never the seated driver's; this module
// only maps that level to the technique blocks. Pure; tested in node.

import type { Density } from "../review/density";
import { INPUT_ROWS_ALL, type InputRow } from "./words";

export interface TechniqueDensity {
  level: Density["level"];
  /** Corner inputs table rows: beginners 4 (release, coasting, throttle pick-up, wheelspin / lock-ups), intermediate
   * 8, advanced all. */
  inputRows: readonly InputRow[];
  /** The line offset chart of the focused corner (intermediate and advanced). */
  offsetChart: boolean;
  /** The mini line map on the Corners cards (intermediate and advanced). */
  miniMap: boolean;
  /** "Line, inputs and balance" on the Corners cards starts collapsed (beginners). */
  cornerCollapsed: boolean;
  /** Balance chips also show the measured slip difference in degrees (advanced). */
  balanceDegrees: boolean;
  /** Glossary `?` buttons (beginner and intermediate). */
  glossary: boolean;
  /** Use the backend's `text_simple` for notes and markers. */
  simpleWording: boolean;
  /** Signed numbers in tables ("+1.5 m"); beginners read words only. */
  signed: boolean;
}

const BEGINNER_ROWS: readonly InputRow[] = ["release", "coast", "throttle_pickup", "slip"];
const INTERMEDIATE_ROWS: readonly InputRow[] = [...BEGINNER_ROWS, "brake_peak", "brake_at_turn_in", "trail_overlap", "throttle_ramp"];

export function techniqueDensity(d: Pick<Density, "level" | "glossary" | "simpleWording" | "signedBadges">): TechniqueDensity {
  const level = d.level;
  return {
    level,
    inputRows: level === "beginner" ? BEGINNER_ROWS : level === "intermediate" ? INTERMEDIATE_ROWS : INPUT_ROWS_ALL,
    offsetChart: level !== "beginner",
    miniMap: level !== "beginner",
    cornerCollapsed: level === "beginner",
    balanceDegrees: level === "advanced",
    glossary: d.glossary,
    simpleWording: d.simpleWording,
    signed: d.signedBadges,
  };
}
