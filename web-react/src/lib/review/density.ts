// Review density by skill level (spec 6.10). The level is the VIEWED session's driver's `preferences.skill_level`,
// never the seated driver (`drivers.active`): a beginner in the seat must not make an advanced driver's session look
// like a beginner's, and a beginner's sessions open simplified even when an advanced driver holds the iPad. Anyone can expand: the page
// passes an override ("Show everything"), which only changes what is shown, never the profile.
//
// A session without a known driver (a replay is nobody's driving, or the profile was deleted) shows the
// intermediate density: every block, three Work on cards, plain captions kept.

import type { Driver, SkillLevel } from "../drivers";

export type { SkillLevel };

export interface DensityRules {
  /** Summary KPI tiles: 4, or 6 for advanced (+ Best sectors combined, + Gap to your best / record). */
  kpiTiles: 4 | 6;
  /** Work on cards before "Show more". */
  workOn: 1 | 3 | 5;
  /** Summary blocks: "core" = tiles, Work on, Went well, lap times, then one More detail button; "all". */
  summary: "core" | "all";
  /** Glossary `?` buttons. */
  glossary: boolean;
  /** Signed time badges on Work on cards ("+0.11 s"); beginners get the amount in words only. */
  signedBadges: boolean;
  /** One fixed plain sentence under each chart title. */
  chartCaptions: boolean;
  /** Work on heading: "One thing to work on" for beginners. */
  workOnHeading: string;
  /** Work on text size, px (beginners 18). */
  workOnTextPx: 16 | 18;
  /** Compare (phase 2): which trace charts show. */
  compareCharts: readonly ("delta" | "speed" | "pedals" | "steering" | "g_forces")[];
  /** Compare corner table (phase 2): "plain" = time + sentence; "some" = + braked, slowest speed; "all". */
  cornerTable: "plain" | "some" | "all";
  /** Progress (phase 3): corner trends first for advanced. */
  progressCornersFirst: boolean;
}

export const DENSITY: Readonly<Record<SkillLevel, DensityRules>> = {
  beginner: {
    kpiTiles: 4,
    workOn: 1,
    summary: "core",
    glossary: true,
    signedBadges: false,
    chartCaptions: true,
    workOnHeading: "One thing to work on",
    workOnTextPx: 18,
    compareCharts: ["delta", "speed"],
    cornerTable: "plain",
    progressCornersFirst: false,
  },
  intermediate: {
    kpiTiles: 4,
    workOn: 3,
    summary: "all",
    glossary: true,
    signedBadges: true,
    chartCaptions: true,
    workOnHeading: "Work on",
    workOnTextPx: 16,
    compareCharts: ["delta", "speed", "pedals"],
    cornerTable: "some",
    progressCornersFirst: false,
  },
  advanced: {
    kpiTiles: 6,
    workOn: 5,
    summary: "all",
    glossary: false,
    signedBadges: true,
    chartCaptions: false,
    workOnHeading: "Work on",
    workOnTextPx: 16,
    compareCharts: ["delta", "speed", "pedals", "steering", "g_forces"],
    cornerTable: "all",
    progressCornersFirst: true,
  },
};

/** Level used when the viewed session has no known driver. */
export const UNKNOWN_DRIVER_LEVEL: SkillLevel = "intermediate";

export interface Density extends DensityRules {
  /** The level whose rules apply. */
  level: SkillLevel;
  /** The driver whose session is being viewed (null: replay, unassigned or unknown profile). */
  driver: Driver | null;
  /** Where the level came from. */
  source: "driver" | "unknown" | "override";
  /** The driver's own level (null when unknown), to offer "back to <name>'s view" after an override. */
  driverLevel: SkillLevel | null;
  /** Show the coach's `text_simple` (D6) instead of `text`: simple-wording profiles, or a beginner view. */
  simpleWording: boolean;
}

/** The driver of a session (by the session's `driver_id`), or null. */
export function viewedDriver(driverId: number | null | undefined, list: readonly Driver[]): Driver | null {
  if (driverId == null) return null;
  return list.find((d) => d.id === driverId) ?? null;
}

const LEVELS: readonly SkillLevel[] = ["beginner", "intermediate", "advanced"];

function isLevel(v: unknown): v is SkillLevel {
  return typeof v === "string" && (LEVELS as readonly string[]).includes(v);
}

/**
 * The density for a session: from its own driver's skill level (`sessionDriverId`, never the seated driver), or
 * the override when someone chose to see more (or less).
 */
export function densityFor(
  sessionDriverId: number | null | undefined,
  list: readonly Driver[],
  override?: SkillLevel | null,
): Density {
  const driver = viewedDriver(sessionDriverId, list);
  const own = driver && isLevel(driver.preferences.skill_level) ? driver.preferences.skill_level : null;
  const level = override ?? own ?? UNKNOWN_DRIVER_LEVEL;
  const source: Density["source"] = override ? "override" : own ? "driver" : "unknown";
  // Simple wording follows the profile's coaching limits when the view is the driver's own; an override follows
  // the level that was picked.
  const simpleWording =
    source === "driver" ? (driver?.coaching?.simple_wording ?? level === "beginner") : level === "beginner";
  return { ...DENSITY[level], level, driver, source, driverLevel: own, simpleWording };
}

/** The next level up, for "Show more detail" (advanced stays advanced). */
export function moreDetail(level: SkillLevel): SkillLevel {
  return level === "beginner" ? "intermediate" : "advanced";
}
