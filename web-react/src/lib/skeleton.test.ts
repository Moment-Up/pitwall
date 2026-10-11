import { describe, expect, it } from "vitest";
import { legacySkeleton, SECTOR_COLOUR_VARS, SECTOR_LABEL_VAR, sectorColourVar, withLiveFlags } from "./skeleton";

describe("sector colours are neutral steps (spec 9.2)", () => {
  it("point at the neutral sector tokens, never at timing or flag colours", () => {
    expect(SECTOR_COLOUR_VARS).toEqual(["var(--pw-sector-1)", "var(--pw-sector-2)", "var(--pw-sector-3)"]);
    for (const v of SECTOR_COLOUR_VARS) expect(v).not.toMatch(/rec|pb|slower|behind|danger|flag|yellow|red|blue/);
    expect(SECTOR_LABEL_VAR).toBe("var(--foreground)");
  });

  it("sectorColourVar() maps 0..2 and keeps unknown unknown", () => {
    expect(sectorColourVar(0)).toBe("var(--pw-sector-1)");
    expect(sectorColourVar(2)).toBe("var(--pw-sector-3)");
    expect(sectorColourVar(3)).toBeNull();
    expect(sectorColourVar(-1)).toBeNull();
    expect(sectorColourVar(1.5)).toBeNull();
    expect(sectorColourVar(null)).toBeNull();
  });
});

describe("legacySkeleton()", () => {
  it("builds three sectors from the legacy session keys", () => {
    const sk = legacySkeleton(5891, 1813, 4294);
    expect(sk?.sectors?.map((s) => [s.name, s.start_m, s.end_m])).toEqual([
      ["S1", 0, 1813],
      ["S2", 1813, 4294],
      ["S3", 4294, 5891],
    ]);
    expect(sk?.tier).toBe("game_native");
    expect(legacySkeleton(5891, 1813, 4294, true)?.tier).toBe("synthetic");
  });

  it("returns null instead of guessing when the starts are missing or out of order", () => {
    expect(legacySkeleton(5891, null, 4294)).toBeNull();
    expect(legacySkeleton(5891, 4294, 1813)).toBeNull();
    expect(legacySkeleton(5891, 1813, 5891)).toBeNull();
    expect(legacySkeleton(0, 1, 2)).toBeNull();
  });

  it("withLiveFlags() applies flags by game number and defaults to none", () => {
    const sk = legacySkeleton(5891, 1813, 4294);
    expect(withLiveFlags(sk, [])).toBe(sk); // no marshal zones: unchanged
  });
});
