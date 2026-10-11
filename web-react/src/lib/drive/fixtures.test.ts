// Every fixture's provenance and Drive state, and the spec's coverage promise: together the fixtures reach every
// Drive state and every overlay of 4.7 (offline = any fixture with the dashboard socket down).
import { describe, expect, it } from "vitest";
import { FIXTURE_NAMES, loadFixture } from "./fixtures";
import { driveModel } from "./model";
import { driveState, type DriveOverlays, type DriveState } from "./state";
import { FIXTURES, fixture, newestT } from "./testkit";
import type { ObservationNext } from "./types";

/** Expected state per fixture (connected, nowS one second after the newest event). */
const EXPECTED: Record<string, DriveState> = {
  "edited-ai-field-monza": "on_track",
  "edited-ai-field-suzuka": "on_track",
  "edited-d1-d6": "on_track",
  "edited-d4-red-flag": "red_flag",
  "edited-garage-between-runs": "garage",
  "edited-penalty-player": "on_track",
  "edited-pit-lane": "pit_lane",
  "edited-red-flag": "red_flag",
  "edited-safety-car": "on_track",
  "pipeline-no-data": "no_data",
  "recorded-austria-blue-elsewhere": "on_track",
  "recorded-austria-blue-in-zone": "on_track",
  "recorded-austria-excerpt-session-ended": "ended",
  "recorded-austria-flashback": "on_track",
  "recorded-austria-on-track-behind": "on_track",
  "recorded-austria-session-ended": "ended",
  "recorded-austria-stale": "stale",
  "recorded-d246-austria-long-name": "on_track",
  "recorded-d246-austria-session-ended": "ended",
  "recorded-d246-austria-stale-ended": "ended", // D4 ended is kept over stale
  "recorded-d246-silverstone-club": "on_track",
  "recorded-d246-silverstone-long-label": "on_track",
  "recorded-d246-suzuka-chequered-flag": "on_track",
  "recorded-d246-suzuka-grid-before-start": "garage",
  "recorded-d246-suzuka-on-track-brake-ahead": "on_track",
  "recorded-d246-suzuka-on-track-in-corner": "on_track",
  "recorded-live-api-gt7-stale": "stale",
  "recorded-melbourne-grid-negative-distance": "garage",
  "recorded-monza-invalid-lap": "on_track",
  "recorded-suzuka-chequered-flag": "on_track",
  "recorded-suzuka-grid-before-start": "garage",
  "recorded-suzuka-on-track-after-cue": "on_track",
  "recorded-suzuka-on-track-brake-ahead": "on_track",
  "recorded-suzuka-on-track-in-corner": "on_track",
  "recorded-suzuka-penalty-any-car": "on_track",
  "recorded-suzuka-yellow-flag": "on_track",
  "synthetic-demo-invalid-lap": "on_track",
  "synthetic-demo-on-track-brake-ahead": "on_track",
  "synthetic-demo-session-ended": "ended",
};

const ALL_STATES: DriveState[] = ["offline", "no_data", "stale", "ended", "red_flag", "pit_lane", "garage", "on_track"];

describe("Drive fixtures", () => {
  it("lists the same fixtures lazily and eagerly, and every one has an expected state", () => {
    expect([...FIXTURE_NAMES]).toEqual([...FIXTURES]);
    expect(Object.keys(EXPECTED).sort()).toEqual([...FIXTURES]);
  });

  it("loads a fixture lazily by name", async () => {
    const s = await loadFixture("recorded-suzuka-on-track-brake-ahead");
    expect(s.session?.track_name).toBe("Suzuka");
    await expect(loadFixture("nope")).rejects.toThrow(/unknown Drive fixture/);
  });

  it.each(FIXTURES)("%s states its provenance honestly", (name) => {
    const s = fixture(name);
    const meta = s._fixture;
    expect(meta, "every fixture carries _fixture").toBeDefined();
    expect(name.startsWith(`${meta!.tier}-`) || (meta!.tier === "recorded" && name.startsWith("recorded-"))).toBe(true);
    if (meta!.tier === "synthetic") expect(s.connection.synthetic).toBe(true);
    if (meta!.tier === "recorded") {
      expect(s.connection.synthetic).toBe(false);
      expect(s.track_model?.track_id ?? "").not.toMatch(/^synthetic:/);
    }
    if (meta!.tier === "edited") expect(meta!.edits?.length).toBeGreaterThan(0);
  });

  it.each(FIXTURES)("%s reaches its expected state", (name) => {
    const s = fixture(name);
    expect(driveState(s, true, newestT(s) + 1).state).toBe(EXPECTED[name]);
    expect(driveState(s, false, newestT(s) + 1).state).toBe("offline");
    // the whole model builds for every fixture, connected or not
    expect(() => driveModel({ snap: s, connected: true, nowS: newestT(s) + 1, driver: null })).not.toThrow();
    expect(() => driveModel({ snap: s, connected: false, nowS: newestT(s) + 1, driver: null })).not.toThrow();
  });

  it("together reach every Drive state and every overlay (4.7)", () => {
    const states = new Set<DriveState>();
    const overlays: Record<keyof DriveOverlays, boolean> = {
      safetyCar: false,
      yellow: false,
      blue: false,
      invalid: false,
      chequered: false,
      chip: false,
      persistent: false, // DRILL: with coachref (F9), no fixture has one yet
    };
    for (const name of FIXTURES) {
      const s = fixture(name);
      const r = driveState(s, true, newestT(s) + 1);
      states.add(r.state);
      states.add(driveState(s, false, 0).state);
      for (const k of Object.keys(overlays) as (keyof DriveOverlays)[]) if (r.overlays[k]) overlays[k] = true;
    }
    expect([...states].sort()).toEqual([...ALL_STATES].sort());
    expect(overlays).toEqual({ safetyCar: true, yellow: true, blue: true, invalid: true, chequered: true, chip: true, persistent: false });
  });
});

// ------------------------------------------------------------------ the coach card's length rule (4.5)

/**
 * Width of `text` in px at `size` px in the UI sans (SF Pro Text / -apple-system, weight 500), from per-character
 * advance estimates (em). Checked against real rendering (Chrome on macOS, SF Pro, a 588 px box, line-height 1.25)
 * for the 100 coaching texts of these fixtures at 22, 26 and 30 px: the line count was never below the real one
 * and above it in 39 of 300 cases, so the assertions below are conservative.
 */
function textWidth(text: string, size: number): number {
  let em = 0;
  for (const ch of text) {
    if (ch === " ") em += 0.27;
    else if ("il.,:;'!|ı".includes(ch)) em += 0.27;
    else if ("fjrt()[]-−/".includes(ch)) em += 0.38;
    else if ("mwMW@".includes(ch)) em += 0.9;
    else if (/[A-Z]/.test(ch)) em += 0.7;
    else if (/[0-9]/.test(ch)) em += 0.62;
    else em += 0.56;
  }
  return em * size;
}

/** Lines `text` wraps to in a box `width` px wide (greedy word wrap, as the browser does for normal text). */
function lines(text: string, size: number, width: number): number {
  const words = text.split(/\s+/).filter(Boolean);
  let n = 1;
  let line = "";
  for (const w of words) {
    const next = line ? `${line} ${w}` : w;
    if (!line || textWidth(next, size) <= width) line = next;
    else {
      n += 1;
      line = w;
    }
  }
  return n;
}

function coachingTexts(name: string): string[] {
  const s = fixture(name);
  const all: ObservationNext[] = [...s.observations, ...(s.coach?.picked ?? []), ...Object.values(s.coach?.by_corner ?? {})];
  return all.flatMap((o) => [o.text, o.text_simple, o.short]).filter((t): t is string => typeof t === "string" && t.length > 0);
}

describe("coaching texts fit the coach card", () => {
  const real = FIXTURES.filter((n) => n.startsWith("recorded-") || n.startsWith("synthetic-"));

  it("finds coaching texts to check", () => {
    expect(real.flatMap(coachingTexts).length).toBeGreaterThan(50);
  });

  it.each(real.filter((n) => n.includes("-d246-")))("%s: every D6 short text is at most 48 characters and fits 2 lines at 26 px", (name) => {
    const s = fixture(name);
    for (const o of [...(s.coach?.picked ?? []), ...Object.values(s.coach?.by_corner ?? {})]) {
      if (!o.short) continue;
      expect(o.short.length, o.short).toBeLessThanOrEqual(48);
      expect(lines(o.short, 26, 588), o.short).toBeLessThanOrEqual(2);
    }
  });

  it.each(real)("%s: every full text fits the stationary card (4 lines at 22 px in 588 px)", (name) => {
    for (const t of coachingTexts(name)) expect(lines(t, 22, 588), t).toBeLessThanOrEqual(4);
  });

  it("reports (does not fail on) the moving texts that need the 3-line clamp at 26 px", () => {
    const clamped = [...new Set(real.flatMap(coachingTexts))].filter((t) => lines(t, 26, 588) > 3);
    if (clamped.length) console.info(`coach card: ${clamped.length} text(s) clamp at 26 px on track:\n${clamped.join("\n")}`);
    expect(Array.isArray(clamped)).toBe(true);
  });

  it("the word-wrap estimate wraps words and never splits one", () => {
    expect(lines("Stowe: you braked about 12 m earlier than your reference lap.", 30, 588)).toBeLessThanOrEqual(2);
    expect(lines("x".repeat(400), 22, 588)).toBe(1); // one unbreakable word stays one (overflowing) line
  });
});
