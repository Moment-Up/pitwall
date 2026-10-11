// Settings › Display (spec 8, 3.3, 9.2; mockup displayPage): the rows, their hints and the live preview's sample
// values. Pure, unit-tested in plain node (model.test.ts). The preferences themselves live in lib/prefs.ts (lane S):
// this page only calls prefs.setPref().

import { SKILL_LEVELS, type SkillLevel } from "../../../lib/drivers";
import {
  driveLockApplies,
  effectiveTheme,
  type ColourVision,
  type DriveLock,
  type DriveSize,
  type Prefs,
  type ThemeName,
  type ThemePref,
} from "../../../lib/prefs";

export interface Choice<V extends string> {
  value: V;
  label: string;
}

export const THEMES: readonly Choice<ThemePref>[] = [
  { value: "dark", label: "Dark" },
  { value: "light", label: "Light" },
  { value: "system", label: "Match device" },
];

export const DRIVE_SIZES: readonly Choice<DriveSize>[] = [
  { value: "standard", label: "Standard" },
  { value: "large", label: "Large" },
];

export const COLOUR_VISION: readonly Choice<ColourVision>[] = [
  { value: "standard", label: "Standard" },
  { value: "rg", label: "Red-green safe" },
];

export const DRIVE_LOCKS: readonly Choice<DriveLock>[] = [
  { value: "off", label: "Off" },
  { value: "beginners", label: "Beginners" },
  { value: "everyone", label: "Everyone" },
];

/** Hints under each row (mockup copy where it has one). */
export const HINTS = {
  theme: "Review, Setup and Settings. Drive has its own switch below.",
  driveAlwaysDark: "Drive stays dark when the app is light",
  driveSize: "Large suits the iPad mini",
  night: "Dark room, low brightness",
  cvd: "Green becomes blue, red becomes orange",
  dimNav: "The rail fades while you drive; a touch brings it back",
  driveLock: "Hold 0.5 s to leave Drive while driving",
} as const;

function skillWord(skill: SkillLevel): string {
  return (SKILL_LEVELS.find((s) => s.value === skill)?.label ?? skill).toLowerCase();
}

/**
 * Who the Drive lock holds now (spec 3.3; decision: beginner profiles by default), for the seated driver. The lock
 * only ever applies on track: never in the pit, before or after the session, or while the data is stale.
 */
export function lockNow(lock: DriveLock, seat: { name: string; skill: SkillLevel | null | undefined } | null): string {
  if (lock === "off") return "Off for every driver.";
  if (lock === "everyone") return seat ? `On for every driver, ${seat.name} included, while on track.` : "On for every driver while on track.";
  if (!seat) return "On for beginner profiles while on track.";
  if (driveLockApplies(lock, seat.skill)) {
    return seat.skill ? `On for ${seat.name} (${skillWord(seat.skill)}) while on track.` : `On for ${seat.name} while on track (no skill level set).`;
  }
  return `Off for ${seat.name} (${seat.skill ? skillWord(seat.skill) : "no skill level"}); on for beginner profiles.`;
}

/** Night dim only changes the dark scheme: say where it shows while the app is light. */
export function nightHint(p: Prefs, systemDark: boolean): string {
  if (effectiveTheme(p, "settings", systemDark) === "dark") return HINTS.night;
  return p.driveAlwaysDark ? `${HINTS.night}. Shows on Drive only while the app is light` : `${HINTS.night}. Dark theme only`;
}

/** The theme the app pages use ("Match device" resolved), for the preview caption. */
export function pageTheme(p: Prefs, systemDark: boolean): ThemeName {
  return effectiveTheme(p, "settings", systemDark);
}

/** The line under the preview (mockup: "Stored on this device. The preview uses the same tokens as Drive."). */
export function previewCaption(p: Prefs, systemDark: boolean): string {
  const base = "Stored on this device. The preview uses the same tokens as Drive.";
  const drive = effectiveTheme(p, "drive", systemDark);
  const page = pageTheme(p, systemDark);
  if (drive === page) return base;
  return `${base} It follows this page's ${page} theme; Drive itself is ${drive}.`;
}

/**
 * The preview's sample values (spec 8: "a timing cell and the delta"). Labelled as a sample on screen, never read
 * as data. Only colours that exist today: green SB and yellow slower sectors, an ahead and a behind delta. No
 * purple: purple is the household record and only appears with the backend's D2 bests (acceptance 5).
 */
export const PREVIEW = {
  sectors: [
    { label: "S1", value: "29.318", status: "sb" as const, sub: "your best today" },
    { label: "S2", value: "36.904", status: "slower" as const, sub: "slower than best" },
  ],
  deltas: [
    { ms: -210, word: "AHEAD" },
    { ms: 110, word: "BEHIND" },
  ],
} as const;
