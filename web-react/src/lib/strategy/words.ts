// Race strategy words (lane "strategy"): compounds, weather, tiers, call levels and the strategy glossary, in plain
// British English. Pure. Unknown is "-" (P5); the minus is U+2212; tiers are always said ("(game)", "(estimate)") so
// a game figure or a Pitwall rule of thumb never reads as a measurement (P8). The glossary explains terms, never
// actions (9.6): nothing here tells the driver what to do, and nothing recommends braking later.

import { finite, MINUS, UNKNOWN } from "../drive/text";
import type { CallLevel, SafetyCarStatus, Tier } from "./types";

export { finite, UNKNOWN };

/** " (game)" / " (estimate)" / "" (measured: this race's own timing needs no suffix). */
export function tierSuffix(tier: Tier | null | undefined): string {
  return tier === "game" ? " (game)" : tier === "heuristic" ? " (estimate)" : "";
}

/** Tier in words for tables and notes. */
export function tierWord(tier: Tier | null | undefined): string {
  return tier === "measured" ? "measured" : tier === "game" ? "game estimate" : tier === "heuristic" ? "Pitwall estimate" : UNKNOWN;
}

/** "1.8" from 1.83 (one decimal, U+2212 for negatives, "-" when unknown). */
export function one(v: number | null | undefined): string {
  if (!finite(v)) return UNKNOWN;
  const abs = Math.abs(v).toFixed(1);
  return v < 0 && Number(abs) !== 0 ? `${MINUS}${abs}` : abs;
}

/** "+0.4" / "−0.3" / "0.0" (one decimal, signed). */
export function signedOne(v: number | null | undefined): string {
  if (!finite(v)) return UNKNOWN;
  const abs = Math.abs(v).toFixed(1);
  if (Number(abs) === 0) return abs;
  return `${v < 0 ? MINUS : "+"}${abs}`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** Sentence case: the first letter upper case. */
export function sentence(s: string): string {
  return s.length ? s[0]!.toUpperCase() + s.slice(1) : s;
}

// --------------------------------------------------------------------------------------------- tyre compounds

/** Visual compounds as the F1 adapter labels them (adapters/f1/enums.py VISUAL_COMPOUNDS). */
const COMPOUND_WORD: Record<string, { word: string; plural: string; short: string }> = {
  soft: { word: "Soft", plural: "softs", short: "S" },
  super_soft: { word: "Super soft", plural: "super softs", short: "SS" },
  medium: { word: "Medium", plural: "mediums", short: "M" },
  hard: { word: "Hard", plural: "hards", short: "H" },
  inter: { word: "Intermediate", plural: "inters", short: "I" },
  intermediate: { word: "Intermediate", plural: "inters", short: "I" },
  wet: { word: "Wet", plural: "wets", short: "W" },
  slick: { word: "Slick", plural: "slicks", short: "S" },
};

/** "Medium"; an unknown label is shown as sent (sentence case); null when the game does not say. */
export function compoundWord(c: string | null | undefined): string | null {
  if (!c) return null;
  return COMPOUND_WORD[c]?.word ?? sentence(c.replace(/_/g, " "));
}

/** "mediums" (new mediums), for sentences. */
export function compoundPlural(c: string | null | undefined): string | null {
  if (!c) return null;
  return COMPOUND_WORD[c]?.plural ?? `${c.replace(/_/g, " ")}s`;
}

/** "M" for compact chips ("M → H"). */
export function compoundShort(c: string | null | undefined): string {
  if (!c) return UNKNOWN;
  return COMPOUND_WORD[c]?.short ?? c.slice(0, 1).toUpperCase();
}

/** The compound's identity colour (a ring beside its label; never the only signal, P4). Tokens only. */
export function compoundColour(c: string | null | undefined): string {
  switch (c) {
    case "soft":
    case "super_soft":
      return "var(--pw-tyre-over)";
    case "medium":
      return "var(--pw-flag-yellow)";
    case "hard":
      return "var(--foreground)";
    case "inter":
    case "intermediate":
      return "var(--pw-pb)";
    case "wet":
      return "var(--pw-ref)";
    default:
      return "var(--pw-faint)";
  }
}

// ------------------------------------------------------------------------------------------------- weather

const WEATHER_WORD: Record<string, string> = {
  clear: "Clear",
  light_cloud: "Light cloud",
  overcast: "Overcast",
  light_rain: "Light rain",
  heavy_rain: "Heavy rain",
  storm: "Storm",
};

export type WeatherCategory = "dry" | "light_rain" | "heavy";

export function weatherWord(w: string | null | undefined): string | null {
  if (!w) return null;
  return WEATHER_WORD[w] ?? sentence(w.replace(/_/g, " "));
}

/** Dry = clear / light cloud / overcast; heavy = heavy rain / storm (strategy/weather.py). Unknown labels: null. */
export function weatherCategory(w: string | null | undefined): WeatherCategory | null {
  switch (w) {
    case "clear":
    case "light_cloud":
    case "overcast":
      return "dry";
    case "light_rain":
      return "light_rain";
    case "heavy_rain":
    case "storm":
      return "heavy";
    default:
      return null;
  }
}

// --------------------------------------------------------------------------------------------- safety car

export function safetyCarWord(s: SafetyCarStatus | "full" | "virtual" | null | undefined): string | null {
  switch (s) {
    case "full":
      return "Safety car";
    case "virtual":
      return "Virtual safety car";
    case "formation_lap":
      return "Formation lap";
    default:
      return null;
  }
}

/** "SC" / "VSC" for chart bands and tags. */
export function safetyCarShort(s: "full" | "virtual"): string {
  return s === "full" ? "SC" : "VSC";
}

// ------------------------------------------------------------------------------------------------- calls

/** Radio chip of a call level: the same words and tones as the radio log (components/radio/radio-view.ts). */
export const CALL_CHIP: Readonly<Record<CallLevel, { label: string; tone: "warning" | "ref" | "default" }>> = {
  alert: { label: "ALERT", tone: "warning" },
  normal: { label: "STRATEGY", tone: "ref" },
  detailed: { label: "INFO", tone: "default" },
};

export function callChip(level: string | null | undefined): { label: string; tone: "warning" | "ref" | "default" } {
  return CALL_CHIP[level as CallLevel] ?? { label: "STRATEGY", tone: "ref" };
}

// ------------------------------------------------------------------------------------------------ glossary

export type StrategyTerm =
  | "pit_window"
  | "pit_loss"
  | "undercut"
  | "lift_and_coast"
  | "stint"
  | "tiers"
  | "fuel_margin"
  | "box"
  | "safety_car";

/** Strategy terms for the `?` buttons (6.10: beginner and intermediate). Terms only, never actions. */
export const STRATEGY_GLOSSARY: Readonly<Record<StrategyTerm, { title: string; text: string }>> = {
  pit_window: {
    title: "Pit window",
    text:
      "The laps in which a pit stop fits: from the first lap a new set of tyres can last to the flag, to the lap " +
      "your current tyres reach the wear limit.",
  },
  pit_loss: {
    title: "Pit loss",
    text:
      "The time a pit stop costs compared with staying out: the drive through the pit lane plus the stop itself. " +
      "Pitwall measures it from the lap times of the stops in this race.",
  },
  undercut: {
    title: "Undercut",
    text:
      "Pitting a lap before the car ahead, so the lap times on new tyres make up the gap while it is still on old " +
      "ones. Pitwall rates it from the gap and how much a new set is worth.",
  },
  lift_and_coast: {
    title: "Lift and coast",
    text:
      "Lifting off the throttle a little before your braking point and rolling to it, to save fuel. You still brake " +
      "at your normal point.",
  },
  stint: {
    title: "Stint",
    text: "The laps driven on one set of tyres, from the start or a pit stop to the next stop or the flag.",
  },
  fuel_margin: {
    title: "Fuel at the flag",
    text:
      "How many laps of fuel would be left when the race ends, at the rate this race has used it. Below zero, the " +
      "fuel would run out before the flag.",
  },
  box: {
    title: "Box",
    text: "The radio word for the pit stop: \"box this lap\" means come into the pits at the end of this lap.",
  },
  safety_car: {
    title: "Safety car and VSC",
    text:
      "After a crash the field is slowed down: behind a safety car, or with a virtual safety car (VSC) every car " +
      "keeps to a slower lap. A pit stop costs less time then, because everyone else is slow too.",
  },
  tiers: {
    title: "Measured, game and estimate",
    text:
      "Measured: from this race's own timing. (game): the game's own figure, such as its tyre model or fuel " +
      "display. (estimate): a Pitwall rule of thumb that has not been checked in a real race yet.",
  },
};
