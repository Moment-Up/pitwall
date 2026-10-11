import { describe, expect, it } from "vitest";
import { BAND_INK, subNavBand, type StatusSlotTone } from "./subNavBand";

// The band colours (tokens.css --pw-flag-*, --pw-pit; the fallbacks in DriveStatusSlot.statusSlotClass).
const BAND_HEX: Record<"red" | "blue" | "yellow" | "sc" | "pit", string> = {
  red: "#d7263d",
  blue: "#2563eb",
  yellow: "#ffd23f",
  sc: "#ffb020",
  pit: "#4cc3ff",
};
const INK = "#0c1016";

type Rgb = [number, number, number];
const hex = (h: string): Rgb => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)) as Rgb;
const over = (fg: Rgb, a: number, bg: Rgb): Rgb => fg.map((c, i) => c * a + bg[i]! * (1 - a)) as Rgb;
const lum = (rgb: Rgb): number => {
  const [r, g, b] = rgb.map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  }) as Rgb;
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (a: Rgb, b: Rgb): number => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
};

describe("subNavBand", () => {
  it.each([
    ["normal", null, "none"],
    ["outline", "bad", "none"],
    ["outline", "warn", "none"],
    ["fill", "red", "light-ink"],
    ["fill", "blue", "light-ink"],
    ["fill", "yellow", "dark-ink"],
    ["fill", "sc", "dark-ink"],
    ["fill", "pit", "dark-ink"],
    ["fill", "neutral", "neutral"],
    ["fill", null, "neutral"],
  ] as const)("%s / %s -> %s", (kind, tone, want) => {
    expect(subNavBand(kind, tone)).toBe(want);
  });

  // Spec 4.8: the Segment stays usable in every state. 15 px / 500 text needs 4.5:1 (WCAG 1.4.3).
  it.each(Object.keys(BAND_HEX) as (keyof typeof BAND_HEX)[])("the %s band's Segment reads at >= 4.5:1", (tone) => {
    const variant = subNavBand("fill", tone as StatusSlotTone);
    if (variant !== "dark-ink" && variant !== "light-ink") throw new Error(`unexpected variant ${variant}`);
    const ink = BAND_INK[variant];
    const band = hex(BAND_HEX[tone]);
    const track = over([ink.track[0], ink.track[0], ink.track[0]], ink.track[1], band);
    const item = over([ink.item[0], ink.item[0], ink.item[0]], ink.item[1], track);
    expect(contrast(item, track)).toBeGreaterThanOrEqual(4.5);
    const indicator = over([255, 255, 255], ink.indicator, track);
    expect(contrast(hex(INK), indicator)).toBeGreaterThanOrEqual(7);
  });
});
