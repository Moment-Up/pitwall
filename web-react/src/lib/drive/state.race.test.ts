// Drive with race radio (pitwall.raceradio; race-radio spec 10.2): the status line's position for any game from the
// snapshot's `race` block, and the blue band from the player's own car flag. Kept apart from state.test.ts so the
// race-radio rules read in one place; the rules without a race block are pinned there and again here.

import { describe, expect, it } from "vitest";
import { raceView, withRace } from "../raceradio/testkit";
import { NO_OVERLAYS, driveState, statusLine, statusSlot } from "./state";
import { asLive, fixture, frame, snap } from "./testkit";
import type { SnapshotNext } from "./types";

const live = <T extends SnapshotNext>(s: T): T => {
  asLive(s);
  s.connection = { ...s.connection, status: "live", last_packet_age_s: 0.02 };
  return s;
};

/** A Forza snapshot as the adapter sends it: no session type, no race length, the race position from Dash. */
function forza(): SnapshotNext {
  return snap({
    session_id: "fz1",
    session: {
      game: "forza_motorsport",
      platform: "pc",
      track_id: "forza:12",
      track_name: "Maple Valley",
      track_length_m: 4100,
      session_type: "unknown",
      car_name: null,
      weather: { condition: null, track_temp_c: null, air_temp_c: null },
      total_laps: null,
      safety_car_status: null,
    },
    frame: frame({ race_position: 3, lap_number: 2 }),
    reference: null,
  });
}

describe("status line position from the race block (any game)", () => {
  it("GT7 (recorded snapshot): no P without the block, P8 with it", () => {
    const s = fixture("recorded-live-api-gt7-stale");
    expect(s.frame?.race_position).toBe(8);
    expect(statusLine(s).position).toBeNull(); // no session type: the old rule never shows GT7's position
    withRace(s, { ...raceView("edited-race-gt7-grid"), lap: 5 });
    expect(statusLine(s)).toMatchObject({ session: "-", lap: "Lap 5", position: "P8" });
    expect(statusSlot("on_track", NO_OVERLAYS, live(s))).toMatchObject({ band: "normal", text: expect.stringMatching(/ · P8$/) });
  });

  it("Forza: P3 with the block, none without", () => {
    expect(statusLine(forza()).position).toBeNull();
    const s = withRace(forza(), raceView("edited-race-forza"));
    expect(statusLine(s).position).toBe("P3");
    expect(statusSlot("on_track", NO_OVERLAYS, s).text).toBe("Maple Valley · Lap 2 · P3");
  });

  it("the block's position wins in an F1 race; a block without one keeps the old rule (frame, race sessions)", () => {
    const s = fixture("recorded-suzuka-on-track-brake-ahead");
    expect(statusLine(s).position).toBe("P16");
    withRace(s, { ...raceView("edited-race-f1-mid-race"), position: 15 });
    expect(statusLine(s).position).toBe("P15");
    withRace(s, raceView("edited-off-gt7-not-race")); // mode off, position null
    expect(statusLine(s).position).toBe("P16");
  });

  it("practice: no P unless the server gives one", () => {
    const s = withRace(snap(), raceView("edited-session-f1-practice-blue"));
    expect(statusLine(s).position).toBeNull();
  });

  it("a GT7 free run (race radio off): no P, as before", () => {
    const s = withRace(fixture("recorded-live-api-gt7-stale"), raceView("edited-off-gt7-not-race"));
    expect(statusLine(s).position).toBeNull();
  });

  it("a newer contract or a block of another session is ignored", () => {
    const s = fixture("recorded-live-api-gt7-stale");
    s.race = { ...raceView("edited-race-gt7-grid"), version: 2 } as unknown as SnapshotNext["race"];
    expect(statusLine(s).position).toBeNull();
    s.race = { ...raceView("edited-race-gt7-grid"), session_id: "not-this-one" };
    expect(statusLine(s).position).toBeNull();
  });
});

describe("blue band from the player's own flag (F1 vehicleFIAFlags)", () => {
  it("the own flag decides over the marshal zones when the server reads it", () => {
    // in a blue zone, but the player's own flag is not blue: no band (only 4 % of zone-blue samples were the player's)
    const inZone = withRace(fixture("recorded-austria-blue-in-zone"), raceView("edited-race-f1-mid-race"));
    expect(driveState(inZone, true, 1000).overlays.blue).toBe(false);
    // no blue zone at the car, but the player's own flag is blue: the band shows
    const elsewhere = withRace(fixture("recorded-austria-blue-elsewhere"), raceView("edited-race-f1-blue-flag"));
    expect(driveState(elsewhere, true, 1000).overlays.blue).toBe(true);
    const plain = withRace(snap(), raceView("edited-race-f1-blue-flag"));
    expect(driveState(plain, true, 1000).overlays.blue).toBe(true);
  });

  it("without the own flag (GT7, Forza, an older server) the marshal-zone rule stays", () => {
    expect(driveState(fixture("recorded-austria-blue-in-zone"), true, 1000).overlays.blue).toBe(true);
    const zones = withRace(fixture("recorded-austria-blue-in-zone"), { ...raceView("edited-race-f1-mid-race"), flags: null });
    expect(driveState(zones, true, 1000).overlays.blue).toBe(true);
    const gt7 = withRace(snap({ marshal_flags: [{ game_number: 4, flag: "blue" }] }), raceView("edited-race-gt7-grid"));
    expect(driveState(gt7, true, 1000).overlays.blue).toBe(true); // flags null: no own-flag reading
  });

  it("the band's words: let the car through in a race, a fast lap behind in practice and qualifying", () => {
    const race = withRace(snap(), raceView("edited-race-f1-blue-flag"));
    expect(statusSlot("on_track", driveState(race, true, 1000).overlays, race)).toMatchObject({
      band: "blue",
      text: "BLUE FLAG",
      sub: "let the car behind through",
    });
    const practice = withRace(snap(), raceView("edited-session-f1-practice-blue"));
    expect(statusSlot("on_track", driveState(practice, true, 1000).overlays, practice)).toMatchObject({
      band: "blue",
      sub: "car behind on a fast lap",
    });
  });

  it("no flag while the data is in doubt (stale, offline)", () => {
    const s = withRace(fixture("recorded-austria-stale"), raceView("edited-race-f1-blue-flag"));
    expect(driveState(s, true, 1000)).toMatchObject({ state: "stale", overlays: NO_OVERLAYS });
    expect(driveState(withRace(snap(), raceView("edited-race-f1-blue-flag")), false, 1000)).toMatchObject({
      state: "offline",
      overlays: NO_OVERLAYS,
    });
  });
});
