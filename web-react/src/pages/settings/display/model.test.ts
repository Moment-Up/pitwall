import { describe, expect, it } from "vitest";
import { DEFAULT_PREFS, type Prefs } from "../../../lib/prefs";
import { COLOUR_VISION, DRIVE_LOCKS, DRIVE_SIZES, HINTS, PREVIEW, THEMES, lockNow, nightHint, pageTheme, previewCaption } from "./model";

const P = (over: Partial<Prefs> = {}): Prefs => ({ ...DEFAULT_PREFS, ...over });

describe("rows", () => {
  it("offer the spec's choices in the mockup's words", () => {
    expect(THEMES.map((c) => [c.value, c.label])).toEqual([
      ["dark", "Dark"],
      ["light", "Light"],
      ["system", "Match device"],
    ]);
    expect(DRIVE_SIZES.map((c) => c.label)).toEqual(["Standard", "Large"]);
    expect(COLOUR_VISION.map((c) => c.label)).toEqual(["Standard", "Red-green safe"]);
    expect(DRIVE_LOCKS.map((c) => [c.value, c.label])).toEqual([
      ["off", "Off"],
      ["beginners", "Beginners"],
      ["everyone", "Everyone"],
    ]);
    expect(HINTS.driveLock).toBe("Hold 0.5 s to leave Drive while driving");
    expect(HINTS.cvd).toBe("Green becomes blue, red becomes orange");
  });

  it("defaults follow the decisions: dark, Drive always dark, Standard size, lock for beginners", () => {
    expect(DEFAULT_PREFS).toMatchObject({ theme: "dark", driveAlwaysDark: true, driveSize: "standard", driveLock: "beginners", dimNav: true });
  });
});

describe("lockNow", () => {
  const alex = { name: "Alex", skill: "beginner" as const };
  const james = { name: "James", skill: "advanced" as const };

  it("beginner profiles (default): on for a beginner in the seat, off for an advanced driver", () => {
    expect(lockNow("beginners", alex)).toBe("On for Alex (beginner) while on track.");
    expect(lockNow("beginners", james)).toBe("Off for James (advanced); on for beginner profiles.");
    expect(lockNow("beginners", { name: "Jo", skill: "intermediate" })).toBe("Off for Jo (intermediate); on for beginner profiles.");
  });

  it("an unknown skill counts as a beginner (the safe side, prefs.driveLockApplies)", () => {
    expect(lockNow("beginners", { name: "Sam", skill: null })).toBe("On for Sam while on track (no skill level set).");
    expect(lockNow("beginners", null)).toBe("On for beginner profiles while on track.");
  });

  it("off and everyone", () => {
    expect(lockNow("off", james)).toBe("Off for every driver.");
    expect(lockNow("everyone", james)).toBe("On for every driver, James included, while on track.");
    expect(lockNow("everyone", null)).toBe("On for every driver while on track.");
  });
});

describe("night dim and the preview caption", () => {
  it("night dim: plain hint while the app is dark", () => {
    expect(nightHint(P(), false)).toBe("Dark room, low brightness");
  });

  it("night dim: says where it shows while the app is light", () => {
    expect(nightHint(P({ theme: "light" }), true)).toBe("Dark room, low brightness. Shows on Drive only while the app is light");
    expect(nightHint(P({ theme: "light", driveAlwaysDark: false }), true)).toBe("Dark room, low brightness. Dark theme only");
    expect(nightHint(P({ theme: "system" }), true)).toBe("Dark room, low brightness"); // device is dark
  });

  it("the page theme resolves Match device", () => {
    expect(pageTheme(P({ theme: "system" }), false)).toBe("light");
    expect(pageTheme(P({ theme: "system" }), true)).toBe("dark");
  });

  it("caption: the mockup line, plus a note when Drive and this page differ", () => {
    expect(previewCaption(P(), false)).toBe("Stored on this device. The preview uses the same tokens as Drive.");
    expect(previewCaption(P({ theme: "light" }), false)).toBe(
      "Stored on this device. The preview uses the same tokens as Drive. It follows this page's light theme; Drive itself is dark.",
    );
    expect(previewCaption(P({ theme: "light", driveAlwaysDark: false }), false)).toBe(
      "Stored on this device. The preview uses the same tokens as Drive.",
    );
  });
});

describe("preview samples", () => {
  it("never show purple (household record needs D2) and cover green, yellow, ahead and behind", () => {
    const statuses: string[] = PREVIEW.sectors.map((s) => s.status);
    expect(statuses).not.toContain("rec");
    expect(statuses).not.toContain("pb");
    expect(statuses).toEqual(["sb", "slower"]);
    expect(PREVIEW.deltas.map((d) => Math.sign(d.ms))).toEqual([-1, 1]);
    expect(PREVIEW.deltas.map((d) => d.word)).toEqual(["AHEAD", "BEHIND"]);
  });
});
