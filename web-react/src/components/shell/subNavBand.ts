// Which Segment variant the Drive status slot uses on a band (spec 4.8: the Segment stays usable in every state, with
// ink chosen for contrast, 9.2). Pure, so the choice and its contrast are unit-tested (subNavBand.test.ts).

/** - "none": the normal slot or an outline (offline / stale): HeroUI's own colours.
 *  - "dark-ink": a light band (yellow, safety car, pit): translucent dark track, white indicator, dark ink.
 *  - "light-ink": a saturated dark band (red, blue): darker track, white ink, white indicator with dark ink.
 *  - "neutral": the neutral fill (session complete, ready). */
export type SubNavBand = "none" | "dark-ink" | "light-ink" | "neutral";

/** The slot kinds and tones of DriveStatusSlot (lib/drive/state.ts statusSlot()). */
export type StatusSlotKind = "normal" | "outline" | "fill";
export type StatusSlotTone = "bad" | "warn" | "red" | "sc" | "yellow" | "blue" | "pit" | "neutral" | null;

export function subNavBand(kind: StatusSlotKind, tone: StatusSlotTone): SubNavBand {
  if (kind !== "fill") return "none";
  switch (tone) {
    case "red":
    case "blue":
      return "light-ink";
    case "sc":
    case "yellow":
    case "pit":
      return "dark-ink";
    default:
      return "neutral";
  }
}

/** The ink SubNav.tsx paints per filled variant, as alpha over black or white (its classes must match):
 * track = the Segment's background over the band, item = unselected text, the selected item is #0c1016 on a white
 * (light-ink) or white/60 (dark-ink) indicator. */
export const BAND_INK: Record<"dark-ink" | "light-ink", { track: [rgb: 0 | 255, alpha: number]; item: [rgb: 0 | 255, alpha: number]; indicator: number }> = {
  "dark-ink": { track: [0, 0.15], item: [0, 0.7], indicator: 0.6 },
  "light-ink": { track: [0, 0.2], item: [255, 0.9], indicator: 1 },
};
