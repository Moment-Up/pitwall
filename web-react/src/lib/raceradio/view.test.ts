import { describe, expect, it } from "vitest";
import { snap } from "../drive/testkit";
import { RACE_FIXTURES, raceFixture, raceView, withRace } from "./testkit";
import {
  callLineText,
  isRaceControl,
  newestCall,
  ownFlag,
  positionNote,
  raceControlCall,
  raceOf,
  racePosition,
  snapRace,
} from "./view";

/** Personal names never reach the dashboard; a scrubbed capture's placeholder or an online ID would look like these. */
const PERSONAL = /\bDriver \d{2}\b|\bplayer\b/i;

describe("race-radio fixtures", () => {
  it("every fixture is a v1 view this dashboard reads, with provenance, within the 1.2 kB contract", () => {
    expect(RACE_FIXTURES.length).toBeGreaterThanOrEqual(7);
    for (const name of RACE_FIXTURES) {
      const meta = raceFixture(name)._fixture;
      expect(meta?.tier, name).toMatch(/^(recorded|synthetic|edited)$/);
      expect(meta?.source, name).toBeTruthy();
      expect(name.startsWith(`${meta?.tier}-`), name).toBe(true);
      const wire = raceView(name);
      expect(raceOf(wire), name).not.toBeNull();
      expect(new TextEncoder().encode(JSON.stringify(wire)).length, name).toBeLessThanOrEqual(1200);
      expect(JSON.stringify(wire), name).not.toMatch(PERSONAL);
    }
  });

  it("a synthetic session's block says so", () => {
    expect(raceView("edited-race-f1-red-flag-synthetic").synthetic).toBe(true);
    expect(raceView("edited-race-f1-mid-race").synthetic).toBe(false);
  });
});

describe("raceOf", () => {
  it("reads version 1 with a known mode; an older server, a newer contract or junk is null", () => {
    expect(raceOf(raceView("edited-race-f1-mid-race"))?.mode).toBe("race");
    expect(raceOf(undefined)).toBeNull();
    expect(raceOf(null)).toBeNull();
    expect(raceOf("race")).toBeNull();
    expect(raceOf([])).toBeNull();
    expect(raceOf({ ...raceView("edited-race-f1-mid-race"), version: 2 })).toBeNull();
    expect(raceOf({ ...raceView("edited-race-f1-mid-race"), mode: "qualifying" })).toBeNull();
  });

  it("keeps every value of a full block", () => {
    const v = raceOf(raceView("edited-race-f1-mid-race"))!;
    expect(v).toMatchObject({
      game: "f1_25",
      position: 7,
      cars: 20,
      grid_position: 9,
      position_tier: "spec_implemented",
      position_note: null,
      lap: 6,
      total_laps: 10,
      laps_left: 4.6,
      flags: { track: "green", you: "none", yellow_ahead: null },
      penalties: { time_s: 3, warnings: 2, track_limits: 1, drive_throughs: 0, stop_gos: 0, serve_at_stop: false },
      damage: { grade: "minor", parts: [{ part: "front_left_wing", pct: 18, grade: "minor" }], puncture: [] },
      ahead: { label: "Norris", label_kind: "driver", position: 6, gap_s: 1.2, settled: true },
      behind: { label: "the Williams", label_kind: "team", position: 8, gap_s: 0.8, settled: false },
    });
    expect(v.calls).toHaveLength(3);
  });

  it("unknown stays unknown: NaN, strings for numbers, unknown enums and missing blocks read as null", () => {
    const v = raceOf({
      version: 1,
      mode: "race",
      position: Number.NaN,
      cars: "20",
      laps_left: Infinity,
      position_tier: "guessed",
      position_note: "  ",
      flags: { track: "chequered", you: "purple", yellow_ahead: { zone: 9, ahead_m: "420", corner: "" } },
      penalties: { time_s: null, warnings: "2", serve_at_stop: "no" },
      damage: { grade: "broken", parts: [{ part: "floor", pct: 40, grade: "major" }, { part: "", grade: "minor" }, { pct: 3 }, 7], puncture: ["RL", "XX", 2] },
      ahead: { label: 23, label_kind: "nickname", position: 4, gap_s: null, settled: "yes" },
      calls: [{ t_unix: 1, text: "Up to P5." }, { t_unix: "2", text: "x" }, { text: "no time" }, null, { t_unix: 3, text: "" }],
    })!;
    expect(v).toMatchObject({
      session_id: null,
      game: null,
      reason: null,
      synthetic: false,
      position: null,
      cars: null,
      laps_left: null,
      position_tier: null,
      position_note: null,
      flags: { track: null, you: null, yellow_ahead: { zone: 9, ahead_m: null, corner: null } },
      penalties: { time_s: null, warnings: null, track_limits: null, drive_throughs: null, stop_gos: null, serve_at_stop: null },
      damage: { grade: null, parts: [{ part: "floor", pct: 40, grade: "major" }], puncture: ["RL"] },
      ahead: { label: null, label_kind: null, position: 4, gap_s: null, settled: null },
      behind: null,
    });
    expect(v.calls).toEqual([{ t_unix: 1, group: "", call: "", text: "Up to P5." }]);
  });

  it("lists are always lists", () => {
    const v = raceOf({ version: 1, mode: "off", calls: null, damage: { parts: null, puncture: "RL" } })!;
    expect(v.calls).toEqual([]);
    expect(v.damage).toEqual({ grade: null, parts: [], puncture: [] });
  });
});

describe("snapRace", () => {
  it("reads the snapshot's block; none on an older server", () => {
    expect(snapRace(withRace(snap(), raceView("edited-race-f1-mid-race")))?.position).toBe(7);
    expect(snapRace(snap())).toBeNull();
    expect(snapRace(null)).toBeNull();
    expect(snapRace(withRace(snap(), null))).toBeNull();
  });

  it("a block of another session is not this session's (unknown stays unknown)", () => {
    const s = snap();
    s.race = { ...raceView("edited-race-f1-mid-race"), session_id: "an-older-session" };
    expect(snapRace(s)).toBeNull();
    s.race = { ...raceView("edited-race-f1-mid-race"), session_id: null };
    expect(snapRace(s)?.position).toBe(7); // the block does not say: the snapshot's
  });
});

describe("position, note and flags", () => {
  it("P from the block for any game; null when unknown or not a whole place", () => {
    expect(racePosition(raceView("edited-race-f1-mid-race"))).toBe("P7");
    expect(racePosition(raceView("edited-race-gt7-grid"))).toBe("P8");
    expect(racePosition(raceView("edited-race-forza"))).toBe("P3");
    expect(racePosition(raceView("edited-session-f1-practice-blue"))).toBeNull();
    expect(racePosition(raceView("edited-off-gt7-not-race"))).toBeNull();
    for (const position of [0, -1, 2.5]) expect(racePosition({ ...raceView("edited-race-f1-mid-race"), position })).toBeNull();
    expect(racePosition(null)).toBeNull();
  });

  it("the evidence note is the backend's, and only while a position shows", () => {
    expect(positionNote(raceView("edited-race-gt7-grid"))).toBe("From GT7's race position; not yet checked against the game's screen.");
    expect(positionNote(raceView("edited-race-forza"))).toMatch(/community docs/);
    expect(positionNote(raceView("edited-race-f1-mid-race"))).toBeNull();
    expect(positionNote({ ...raceView("edited-race-gt7-grid"), position: null })).toBeNull();
  });

  it("the player's own flag; null when the game or server does not say", () => {
    expect(ownFlag(raceView("edited-race-f1-blue-flag"))).toBe("blue");
    expect(ownFlag(raceView("edited-race-f1-mid-race"))).toBe("none");
    expect(ownFlag(raceView("edited-race-gt7-grid"))).toBeNull();
    expect(ownFlag(null)).toBeNull();
  });
});

describe("calls", () => {
  it("the newest call by time, whatever the list order", () => {
    const v = raceView("edited-race-f1-mid-race");
    expect(newestCall(v)?.call).toBe("penalty");
    expect(newestCall({ ...v, calls: [...v.calls].reverse() })?.call).toBe("penalty");
    expect(newestCall({ ...v, calls: [] })).toBeNull();
    expect(newestCall(null)).toBeNull();
  });

  it("race control: flags, penalties and retirements; positions, gaps and the start are the engineer", () => {
    expect(isRaceControl({ group: "flags", call: "yellow_ahead" })).toBe(true);
    expect(isRaceControl({ group: "penalties", call: "warning" })).toBe(true);
    expect(isRaceControl({ group: "rivals", call: "retirement" })).toBe(true);
    expect(isRaceControl({ group: "rivals", call: "gap_report" })).toBe(false);
    expect(isRaceControl({ group: "position", call: "position_change" })).toBe(false);
    expect(isRaceControl({ group: "start", call: "lights_out" })).toBe(false);
    expect(raceControlCall(raceView("edited-race-f1-mid-race"))?.text).toBe("3 second penalty: corner cutting.");
    expect(raceControlCall(raceView("edited-race-forza"))).toBeNull(); // a position call only
    expect(raceControlCall(raceView("edited-race-f1-red-flag-synthetic"))?.call).toBe("red_flag");
  });

  it("a call's words for a line drop the closing full stop only", () => {
    expect(callLineText("3 second penalty: corner cutting.")).toBe("3 second penalty: corner cutting");
    expect(callLineText("Red flag, red flag. Slow down, back to the pits.")).toBe("Red flag, red flag. Slow down, back to the pits");
    expect(callLineText(" Go, go ")).toBe("Go, go");
  });
});
