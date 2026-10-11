import { describe, expect, it } from "vitest";
import {
  EMPTY_MEMO,
  NO_OVERLAYS,
  RED_FLAG_MAX_AGE_S,
  chipText,
  connectionPill,
  driveState,
  evidence,
  nextMemo,
  sessionTypeText,
  statusLine,
  statusSlot,
  type DriveOverlays,
} from "./state";
import { driveModel } from "./model";
import { fixture, frame, lap, newestT, snap } from "./testkit";
import type { LiveEvent, SnapshotNext } from "./types";

const ev = (kind: string, t: number, extra: Partial<LiveEvent> = {}): LiveEvent => ({
  kind,
  code: null,
  session_time_s: null,
  t,
  ...extra,
});

function stateOf(s: SnapshotNext | null, connected = true, nowS = 1000) {
  return driveState(s, connected, nowS);
}

describe("driveState: states (4.7), first match wins", () => {
  it("is offline whenever the dashboard socket is down, whatever the snapshot says", () => {
    expect(stateOf(null, false).state).toBe("offline");
    expect(stateOf(snap(), false).state).toBe("offline");
    expect(stateOf(fixture("recorded-austria-stale"), false).state).toBe("offline");
    expect(stateOf(snap(), false).overlays).toEqual(NO_OVERLAYS);
  });

  it("has no telemetry before the first snapshot and while the server has no data", () => {
    expect(stateOf(null).state).toBe("no_data");
    expect(stateOf(fixture("pipeline-no-data")).state).toBe("no_data");
  });

  it("is stale before anything the track says, and shows no flag as current", () => {
    const s = fixture("recorded-austria-stale");
    expect(stateOf(s).state).toBe("stale");
    s.marshal_flags = [{ game_number: 3, flag: "yellow" }];
    expect(stateOf(s).overlays).toEqual(NO_OVERLAYS);
    // before D4 "ended" is inferred from the 10-event window: stale still wins (this capture ended too)
    expect(fixture("recorded-austria-stale").events.some((e) => e.kind === "session_ended")).toBe(true);
  });

  it("keeps D4 ended over stale: a fact the server keeps, not a live value (F1 stops sending at session_ended)", () => {
    const s = fixture("recorded-d246-austria-stale-ended");
    expect(s.connection.status).toBe("stale");
    const r = stateOf(s);
    expect(r.state).toBe("ended");
    expect(r.overlays).toEqual(NO_OVERLAYS);
    expect(statusSlot(r.state, r.overlays, s)).toMatchObject({ kind: "fill", band: "complete", text: "SESSION COMPLETE" });
    expect(connectionPill(s, true)).toEqual({ tone: "stale", text: "Stale 2 s" }); // the age stays on the pill
    // still stale with no D4 phase, and offline still wins over everything
    expect(stateOf({ ...s, session_state: "running" }).state).toBe("stale");
    expect(stateOf(s, false).state).toBe("offline");
  });

  it("ends on session_ended (before D4) and on D4 ended", () => {
    expect(stateOf(fixture("recorded-austria-session-ended")).state).toBe("ended");
    expect(stateOf(fixture("synthetic-demo-session-ended")).state).toBe("ended");
    expect(stateOf(fixture("recorded-d246-austria-session-ended")).state).toBe("ended");
    expect(stateOf(snap({ session_state: "ended" })).state).toBe("ended");
  });

  it("keeps the hero under a chequered flag while the driver's last lap runs, then ends", () => {
    for (const name of ["recorded-suzuka-chequered-flag", "recorded-d246-suzuka-chequered-flag"]) {
      const s = fixture(name);
      const first = stateOf(s);
      expect(first.state).toBe("on_track");
      expect(first.overlays.chequered).toBe(true);
      expect(first.memo.chequered).toEqual({ lap: 5 });
      // the driver crosses the line: lap 6 starts
      const after = structuredClone(s);
      after.frame = { ...after.frame!, lap_number: 6, lap_distance_m: 20, current_lap_time_ms: 900 };
      const done = driveState(after, true, 1000, first.memo);
      expect(done.state).toBe("ended");
      expect(done.overlays.chequered).toBe(true);
      expect(statusSlot(done.state, done.overlays, after)).toMatchObject({ band: "complete", text: "CHEQUERED FLAG" });
    }
  });

  it("ends a chequered session once the lap count is done or the car leaves the track", () => {
    const s = fixture("recorded-suzuka-chequered-flag");
    s.laps = [lap(5, 97000), ...s.laps]; // total_laps 5
    expect(stateOf(s).state).toBe("ended");
    const pit = fixture("recorded-suzuka-chequered-flag");
    pit.frame = { ...pit.frame!, pit_status: 1 };
    expect(stateOf(pit).state).toBe("ended");
  });

  it("remembers the chequered flag after AI events push it out of the 10-event window", () => {
    const s = fixture("recorded-suzuka-chequered-flag");
    const m = stateOf(s).memo;
    const later = structuredClone(s);
    const t = newestT(s);
    later.events = Array.from({ length: 10 }, (_, i) => ev("other", t + 1 + i));
    expect(driveState(later, true, t + 20).state).toBe("on_track");
    expect(driveState(later, true, t + 20).overlays.chequered).toBe(false); // without the memo it is lost
    expect(driveState(later, true, t + 20, m).overlays.chequered).toBe(true);
  });

  it("shows a red flag for 120 s before D4, cleared by a newer start, and follows D4", () => {
    const s = fixture("edited-red-flag");
    const t = newestT(s);
    expect(stateOf(s, true, t + 5).state).toBe("red_flag");
    expect(stateOf(s, true, t + RED_FLAG_MAX_AGE_S + 1).state).toBe("on_track");
    s.events = [ev("lights_out", t + 30), ...s.events];
    expect(stateOf(s, true, t + 31).state).toBe("on_track");
    expect(stateOf(fixture("edited-d4-red-flag"), true, 0).state).toBe("red_flag"); // D4 has no expiry
    const d4 = fixture("recorded-d246-suzuka-on-track-brake-ahead");
    d4.events = [ev("red_flag", newestT(d4) + 1), ...d4.events];
    expect(stateOf(d4, true, newestT(d4)).state).toBe("on_track"); // D4 says running: the server wins
  });

  it("is in the pit lane on pit_status 1", () => {
    expect(stateOf(fixture("edited-pit-lane")).state).toBe("pit_lane");
  });

  it("is in the garage on pit_status 2, D3 in_garage, without a frame, or before the first lap starts", () => {
    expect(stateOf(fixture("edited-garage-between-runs")).state).toBe("garage");
    expect(stateOf(snap({ frame: frame({ driver_status: "in_garage" }) })).state).toBe("garage");
    expect(stateOf(snap({ frame: null })).state).toBe("garage");
    expect(stateOf(fixture("recorded-suzuka-grid-before-start")).state).toBe("garage");
    expect(stateOf(fixture("recorded-melbourne-grid-negative-distance")).state).toBe("garage");
    expect(stateOf(fixture("recorded-d246-suzuka-grid-before-start")).state).toBe("garage");
    // lights out: the lap clock runs
    const g = fixture("recorded-suzuka-grid-before-start");
    g.frame = { ...g.frame!, current_lap_time_ms: 1200 };
    expect(stateOf(g).state).toBe("on_track");
  });

  it("is on track otherwise", () => {
    for (const name of [
      "recorded-suzuka-on-track-brake-ahead",
      "recorded-suzuka-on-track-in-corner",
      "recorded-austria-on-track-behind",
      "synthetic-demo-on-track-brake-ahead",
      "edited-d1-d6",
    ]) {
      expect(stateOf(fixture(name)).state, name).toBe("on_track");
    }
  });
});

describe("driveState: overlays", () => {
  it("reads the safety car status", () => {
    expect(stateOf(fixture("edited-safety-car")).overlays.safetyCar).toBe("full");
    for (const v of ["virtual", "formation_lap"] as const) {
      const s = snap();
      s.session = { ...s.session!, safety_car_status: v };
      expect(stateOf(s).overlays.safetyCar).toBe(v);
    }
    expect(stateOf(snap()).overlays.safetyCar).toBeNull();
  });

  it("names a yellow zone, its sector and whether the car is in it (real Suzuka yellow)", () => {
    const o = stateOf(fixture("recorded-suzuka-yellow-flag")).overlays;
    expect(o.yellow).toEqual({ zone: 2, sector: 1, aheadM: null, inZone: true, count: 1 });
  });

  it("gives the distance to a yellow zone starting within 1000 m ahead, and the nearest of several", () => {
    const s = fixture("recorded-suzuka-yellow-flag"); // zones 2 = 858.65-1221.09, 4 = 1601.39-...; car at 1002.9
    s.frame = { ...s.frame!, lap_distance_m: 500 };
    expect(stateOf(s).overlays.yellow).toMatchObject({ zone: 2, aheadM: expect.closeTo(358.65, 1), inZone: false });
    s.marshal_flags = [
      { game_number: 4, flag: "yellow" },
      { game_number: 2, flag: "yellow" },
    ];
    expect(stateOf(s).overlays.yellow).toMatchObject({ zone: 2, count: 2 });
    s.frame = { ...s.frame!, lap_distance_m: 5000 }; // zone 2 is ~1660 m ahead (wrapping)
    s.marshal_flags = [{ game_number: 2, flag: "yellow" }];
    expect(stateOf(s).overlays.yellow).toMatchObject({ zone: 2, aheadM: null, inZone: false });
  });

  it("still flags a yellow zone the skeleton does not describe", () => {
    const s = snap({ marshal_flags: [{ game_number: 9, flag: "yellow" }] });
    expect(stateOf(s).overlays.yellow).toEqual({ zone: 9, sector: null, aheadM: null, inZone: false, count: 1 });
  });

  it("shows blue only while the car is inside a blue zone, when that is knowable", () => {
    expect(stateOf(fixture("recorded-austria-blue-in-zone")).overlays.blue).toBe(true);
    expect(stateOf(fixture("recorded-austria-blue-elsewhere")).overlays.blue).toBe(false);
    expect(stateOf(snap({ marshal_flags: [{ game_number: 4, flag: "blue" }] })).overlays.blue).toBe(true); // no zones
  });

  it("marks an invalid lap", () => {
    expect(stateOf(fixture("recorded-monza-invalid-lap")).overlays.invalid).toBe(true);
    expect(stateOf(fixture("synthetic-demo-invalid-lap")).overlays.invalid).toBe(true);
    expect(stateOf(snap()).overlays.invalid).toBe(false);
  });

  it("shows a 6 s incident chip only for the player's own events", () => {
    const any = fixture("recorded-suzuka-penalty-any-car");
    const t = newestT(any);
    expect(stateOf(any, true, t + 1).overlays.chip).toBeNull(); // F1 reports every car's penalties
    const mine = fixture("edited-penalty-player");
    expect(stateOf(mine, true, t + 1).overlays.chip).toEqual({ kind: "penalty", ageS: 1 });
    expect(stateOf(mine, true, t + 7).overlays.chip).toBeNull();
    expect(stateOf(mine, true, t - 1).overlays.chip).toEqual({ kind: "penalty", ageS: 0 }); // small clock skew
    const fb = fixture("recorded-austria-flashback");
    expect(stateOf(fb, true, newestT(fb) + 2).overlays.chip).toMatchObject({ kind: "flashback" });
    fb.events[0] = { ...fb.events[0]!, player: false };
    expect(stateOf(fb, true, newestT(fb) + 2).overlays.chip).toBeNull();
  });

  it("is not hidden by a newer event of another car", () => {
    const s = fixture("edited-penalty-player");
    const t = newestT(s);
    s.events = [ev("collision", t + 1), ...s.events]; // AI contact, player unknown
    expect(stateOf(s, true, t + 2).overlays.chip).toEqual({ kind: "penalty", ageS: 2 });
    s.events = [ev("constructor", t + 3), ...s.events]; // unknown kinds are ignored, prototype names included
    expect(stateOf(s, true, t + 3).state).toBe("on_track");
  });

  it("combines overlays with red flag, pit lane, garage and on track only", () => {
    const pit = fixture("edited-pit-lane");
    pit.session = { ...pit.session!, safety_car_status: "virtual" };
    expect(stateOf(pit).overlays.safetyCar).toBe("virtual");
    const ended = fixture("recorded-austria-session-ended");
    ended.session = { ...ended.session!, safety_car_status: "full" };
    expect(stateOf(ended).overlays).toEqual(NO_OVERLAYS);
  });
});

describe("memo", () => {
  it("keeps its identity when nothing changes and resets on a new session", () => {
    const s = fixture("recorded-suzuka-on-track-brake-ahead");
    const m1 = nextMemo(s, EMPTY_MEMO);
    expect(nextMemo(s, m1)).toBe(m1);
    const other = structuredClone(s);
    other.session_id = "another";
    expect(nextMemo(other, { ...m1, lastCorner: "T7" })).toMatchObject({ sessionId: "another", lastCorner: null });
  });

  it("clears the chequered flag when D4 says the session restarted", () => {
    const s = fixture("recorded-d246-suzuka-chequered-flag");
    const m = nextMemo(s, null);
    expect(m.chequered).not.toBeNull();
    s.session_state_info = { ...s.session_state_info!, chequered_flag: false };
    expect(nextMemo(s, m).chequered).toBeNull();
  });
});

describe("status slot (4.8)", () => {
  const O = (over: Partial<DriveOverlays> = {}): DriveOverlays => ({ ...NO_OVERLAYS, ...over });

  it("outlines doubt and fills track facts, with the spec's words", () => {
    expect(statusSlot("offline", O(), null)).toEqual({
      kind: "outline",
      tone: "bad",
      band: "offline",
      text: "Offline",
      sub: "reconnecting…",
      role: "status",
    });
    expect(statusSlot("stale", O(), fixture("recorded-austria-stale"))).toMatchObject({
      kind: "outline",
      tone: "warn",
      text: "No signal · 2 s",
      sub: "game paused or in a menu?",
    });
    expect(statusSlot("stale", O(), fixture("recorded-live-api-gt7-stale")).text).toBe("No signal · 21 min");
    expect(statusSlot("no_data", O(), null)).toMatchObject({ kind: "normal", text: "Waiting for telemetry" });
    expect(statusSlot("red_flag", O(), snap())).toMatchObject({ kind: "fill", tone: "red", text: "RED FLAG", role: "alert" });
    expect(statusSlot("ended", O(), fixture("recorded-austria-session-ended"))).toMatchObject({
      kind: "fill",
      tone: "neutral",
      text: "SESSION COMPLETE",
      sub: "Austria · Race · 10 laps",
      role: "status",
    });
  });

  it("game mismatch (game selection 5.3): below every flag, stale, offline and session complete; above ready / normal", () => {
    const mm = { text: "F1 25 data · GT7 selected", sub: "change on Setup › Game" };
    const yellow = { zone: 16, sector: 3, aheadM: 384, inZone: false, count: 1 };
    const s = fixture("edited-safety-car");
    // the outline line, not interactive, a status (never an alert)
    expect(statusSlot("on_track", O(), snap(), mm)).toEqual({
      kind: "outline",
      tone: "warn",
      band: "mismatch",
      text: "F1 25 data · GT7 selected",
      sub: "change on Setup › Game",
      role: "status",
    });
    expect(statusSlot("garage", O(), snap(), mm).band).toBe("mismatch"); // above ready
    expect(statusSlot("offline", O(), null, mm).band).toBe("offline");
    expect(statusSlot("stale", O(), fixture("recorded-austria-stale"), mm).band).toBe("stale");
    expect(statusSlot("no_data", O(), null, mm).band).toBe("no_data");
    expect(statusSlot("red_flag", O(), snap(), mm).band).toBe("red");
    expect(statusSlot("on_track", O({ safetyCar: "full" }), s, mm).band).toBe("sc");
    expect(statusSlot("on_track", O({ yellow }), s, mm).band).toBe("yellow");
    expect(statusSlot("on_track", O({ blue: true }), s, mm).band).toBe("blue");
    expect(statusSlot("pit_lane", O(), s, mm).band).toBe("pit");
    expect(statusSlot("on_track", O({ chequered: true }), s, mm).band).toBe("chequered");
    expect(statusSlot("ended", O(), fixture("recorded-austria-session-ended"), mm).band).toBe("complete");
    // without a mismatch (none, or moving: lib/game.ts driveMismatch gives null) the slot is as before
    expect(statusSlot("on_track", O(), snap(), null)).toEqual(statusSlot("on_track", O(), snap()));
    expect(statusSlot("garage", O(), snap(), null).band).toBe("ready");
  });

  it("the Drive model carries the mismatch into the status slot", () => {
    const s = snap({ frame: frame({ speed_kph: 0 }) });
    const mismatch = { text: "F1 25 data · GT7 selected", sub: "change on Setup › Game" };
    const m = driveModel({ snap: s, connected: true, nowS: newestT(s) + 1, driver: null, mismatch });
    expect(m.status).toMatchObject({ kind: "outline", band: "mismatch", text: "F1 25 data · GT7 selected" });
    expect(driveModel({ snap: s, connected: true, nowS: newestT(s) + 1, driver: null }).status.band).not.toBe("mismatch");
  });

  it("orders the bands: safety car > yellow > blue > pit > chequered", () => {
    const s = fixture("edited-safety-car");
    const yellow = { zone: 16, sector: 3, aheadM: 384, inZone: false, count: 1 };
    const all = O({ safetyCar: "full", yellow, blue: true, chequered: true });
    expect(statusSlot("pit_lane", all, s)).toMatchObject({ band: "sc", text: "SAFETY CAR", sub: "calls paused" });
    expect(statusSlot("pit_lane", O({ yellow, blue: true }), s)).toMatchObject({
      band: "yellow",
      tone: "yellow",
      text: "YELLOW FLAG · SECTOR 3 · ZONE 16",
      sub: "380 m ahead",
    });
    expect(statusSlot("on_track", O({ blue: true, chequered: true }), s)).toMatchObject({
      band: "blue",
      text: "BLUE FLAG",
      sub: "let the car behind through",
    });
    expect(statusSlot("pit_lane", O({ chequered: true }), s)).toMatchObject({ band: "pit", text: "PIT LANE", sub: "limit 80 km/h" });
    expect(statusSlot("on_track", O({ chequered: true }), s)).toMatchObject({ band: "chequered", text: "CHEQUERED FLAG", sub: "last lap" });
    expect(statusSlot("on_track", O({ safetyCar: "virtual" }), snap())).toMatchObject({ text: "VIRTUAL SAFETY CAR", sub: null });
    expect(statusSlot("on_track", O({ safetyCar: "formation_lap" }), snap()).text).toBe("FORMATION LAP");
    expect(statusSlot("red_flag", all, s).band).toBe("red");
  });

  it("describes a yellow zone without a skeleton, the car inside one, and several", () => {
    const s = snap();
    expect(statusSlot("on_track", O({ yellow: { zone: 9, sector: null, aheadM: null, inZone: false, count: 1 } }), s)).toMatchObject({
      text: "YELLOW FLAG · ZONE 9",
      sub: null,
    });
    expect(statusSlot("on_track", O({ yellow: { zone: 2, sector: 1, aheadM: null, inZone: true, count: 3 } }), s).sub).toBe(
      "in this zone · 3 zones",
    );
  });

  it("says Ready in the garage and gives the normal line on track", () => {
    expect(statusSlot("garage", O(), snap())).toMatchObject({ kind: "normal", band: "ready", text: "Ready · Practice" });
    expect(statusSlot("on_track", O(), fixture("recorded-suzuka-on-track-brake-ahead"))).toMatchObject({
      kind: "normal",
      band: "normal",
      text: "Suzuka · Race · Lap 5 / 5 · P16",
    });
  });

  it("leaves the pit limit out when unknown", () => {
    const s = snap();
    expect(statusSlot("pit_lane", O(), s)).toMatchObject({ text: "PIT LANE", sub: null });
  });
});

describe("status line, pill, evidence", () => {
  it("shows the position in races only and the total laps when known", () => {
    expect(statusLine(fixture("recorded-suzuka-on-track-brake-ahead"))).toEqual({
      track: "Suzuka",
      session: "Race",
      lap: "Lap 5",
      lapTotal: "5",
      position: "P16",
    });
    expect(statusLine(snap())).toMatchObject({ session: "Practice", lapTotal: null, position: null });
    expect(statusLine(null)).toEqual({ track: "-", session: "-", lap: "Lap -", lapTotal: null, position: null });
    expect(sessionTypeText("unknown")).toBeNull();
    expect(sessionTypeText("time_trial")).toBe("Time trial");
  });

  it("derives the connection pill like badgeFor", () => {
    expect(connectionPill(snap(), true)).toEqual({ tone: "live", text: "Live" });
    expect(connectionPill(fixture("recorded-austria-stale"), true)).toEqual({ tone: "stale", text: "Stale 2 s" });
    expect(connectionPill(fixture("pipeline-no-data"), true)).toEqual({ tone: "idle", text: "No data" });
    expect(connectionPill(snap(), false)).toEqual({ tone: "offline", text: "Offline" });
  });

  it("labels synthetic and replayed data", () => {
    expect(evidence(fixture("synthetic-demo-on-track-brake-ahead"))).toEqual({ synthetic: true, replay: true });
    expect(evidence(fixture("recorded-suzuka-on-track-brake-ahead"))).toEqual({ synthetic: false, replay: true });
    expect(evidence(fixture("recorded-live-api-gt7-stale"))).toEqual({ synthetic: false, replay: false });
  });

  it("words the incident chips", () => {
    expect(chipText("collision")).toBe("CONTACT");
    expect(chipText("flashback")).toBe("FLASHBACK · lap won't count");
    expect(chipText("fastest_lap")).toBe("FASTEST LAP");
  });
});
