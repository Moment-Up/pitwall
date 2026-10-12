// Drive with an F2 car (F2 support, contract v1): the status line names the class and the race as F2 calls it, the
// "Your best here" stand-in stays within the car's family, and a borrowed track model says so. The snapshots are
// recorded Drive moments with the contract's session additions (edited in each test); an older server's snapshot (no
// class) renders exactly as before.
import { describe, expect, it } from "vitest";
import { F1_CLASS, F2_CLASS, f2JeddahSession, f2MelbourneSprintSession } from "../carclass-testkit";
import type { DriverBestLap } from "../drivers";
import { driveModel, type DriveModelInput } from "./model";
import { liveSessionType, NO_OVERLAYS, statusLine, statusSlot } from "./state";
import { driver, fixture, newestT, snap, stopped } from "./testkit";
import type { SnapshotNext } from "./types";

function model(s: SnapshotNext | null, over: Partial<DriveModelInput> = {}) {
  return driveModel({ snap: s, connected: true, nowS: newestT(s) + 1, driver: driver(), ...over });
}

/** A recorded moment with the F2 feature race's session block (track kept). */
function asF2<T extends SnapshotNext>(s: T, session = f2JeddahSession()): T {
  s.session = { ...session, track_id: s.session!.track_id, track_name: s.session!.track_name, track_length_m: s.session!.track_length_m };
  return s;
}

describe("the status line names the class and the race as F2 calls it", () => {
  it("on track: track, F2 chip, Feature race, lap / total, position", () => {
    const s = asF2(fixture("recorded-suzuka-on-track-brake-ahead"));
    expect(statusLine(s)).toEqual({
      track: "Suzuka",
      carClass: "F2",
      session: "Feature race",
      lap: "Lap 5",
      lapTotal: "5",
      position: "P16", // "Feature race" is a race: the position shows
    });
    const slot = statusSlot("on_track", NO_OVERLAYS, s);
    expect(slot).toMatchObject({ kind: "normal", band: "normal", text: "Suzuka · F2 · Feature race · Lap 5 / 5 · P16" });
  });

  it("the game's 'Race' is the sprint, 'Race 2' the feature race; anything else as the game names it", () => {
    expect(liveSessionType(f2MelbourneSprintSession())).toBe("Sprint race");
    expect(liveSessionType(f2JeddahSession())).toBe("Feature race");
    expect(liveSessionType({ ...f2JeddahSession(), session_type: "One-Shot Qualifying", session_label: "One-Shot Qualifying" })).toBe(
      "One-shot qualifying",
    );
    // an older server: the game's own name, as before
    expect(liveSessionType({ ...f2JeddahSession(), session_label: undefined })).toBe("Race 2");
  });

  it("garage: 'Ready · Sprint race'; ended: the complete band names the race", () => {
    const grid = asF2(stopped(fixture("recorded-suzuka-grid-before-start")), f2MelbourneSprintSession());
    expect(model(grid).status).toMatchObject({ band: "ready", text: "Ready · Sprint race" });
    expect(model(grid).status.line.carClass).toBe("F2");
    const ended = asF2(stopped(fixture("recorded-austria-session-ended")));
    expect(model(ended).status.sub).toBe("Austria · Feature race · 10 laps");
  });

  it("an F1 car carries no chip, and an older server's snapshot is unchanged", () => {
    const f1 = fixture("recorded-suzuka-on-track-brake-ahead");
    f1.session = { ...f1.session!, car_class: F1_CLASS, car_label: "McLaren", session_label: "Race" };
    expect(statusLine(f1)).toMatchObject({ carClass: null, session: "Race" });
    expect(statusSlot("on_track", NO_OVERLAYS, f1).text).toBe("Suzuka · Race · Lap 5 / 5 · P16");
    const old = fixture("recorded-suzuka-on-track-brake-ahead");
    expect(statusLine(old)).toMatchObject({ carClass: null, session: "Race" });
  });
});

describe("Your best here stays within the car's family (stats.best_laps: one per family)", () => {
  const nowS = new Date(2026, 9, 12, 14).getTime() / 1000;
  const set = new Date(2026, 9, 3, 20).getTime() / 1000;
  const best = (family: DriverBestLap["car_family"], ms: number, car = "Art GP '24"): DriverBestLap => ({
    game: "f1_25",
    track_id: "f1:13",
    track_name: "Suzuka",
    lap_time_ms: ms,
    lap_id: ms,
    session_id: `s${ms}`,
    car_name: car,
    synthetic: false,
    set_unix: set,
    car_family: family,
    car_label: family === "f2" ? `F2 · ${car}` : car,
  });
  const jo = (laps: DriverBestLap[]) =>
    driver({ stats: { sessions: 2, laps: 2, clean_laps: 2, tracks: 1, last_session_unix: null, best_laps: laps } });
  const grid = () => asF2(stopped(fixture("recorded-d246-suzuka-grid-before-start"))); // no bests block (before D2)

  it("an F2 car: the F2 best, even when an F1 lap here is faster", () => {
    const y = model(grid(), { driver: jo([best("f1", 90986, "McLaren"), best("f2", 101500)]), nowS }).ready?.target.yourBest;
    expect(y).toEqual({ text: "1:41.500", status: "neutral", tag: null, date: "3 Oct", anyCar: false });
  });

  it("only an F1 best here: shown as the F1 car's, never as 'any car'", () => {
    const y = model(grid(), { driver: jo([best("f1", 90986, "McLaren")]), nowS }).ready?.target.yourBest;
    expect(y).toEqual({ text: "1:30.986", status: "neutral", tag: null, date: "3 Oct · F1 car", anyCar: true });
  });

  it("a best of unknown family (a session from before classes) still stands in as 'any car'", () => {
    const y = model(grid(), { driver: jo([best(null, 99000, "Ferrari")]), nowS }).ready?.target.yourBest;
    expect(y).toMatchObject({ text: "1:39.000", date: "3 Oct · any car", anyCar: true });
  });

  it("an older server (no class on the session): the fastest best here, as before", () => {
    const s = stopped(fixture("recorded-d246-suzuka-grid-before-start"));
    s.session = { ...s.session!, car_name: "McLaren" };
    const y = model(s, { driver: jo([best("f1", 90986, "McLaren"), best("f2", 101500)]), nowS }).ready?.target.yourBest;
    expect(y).toMatchObject({ text: "1:30.986", date: "3 Oct", anyCar: false });
  });

  it("an F1 car with only an F2 best here: 'F2 car'", () => {
    const s = stopped(fixture("recorded-d246-suzuka-grid-before-start"));
    s.session = { ...s.session!, car_name: "McLaren", car_class: F1_CLASS, car_label: "McLaren", session_label: "One-Shot Qualifying" };
    const y = model(s, { driver: jo([best("f2", 101500)]), nowS }).ready?.target.yourBest;
    expect(y).toMatchObject({ text: "1:41.500", date: "3 Oct · F2 car", anyCar: true });
  });
});

describe("a borrowed track model", () => {
  it("the Ready card's footer says whose laps the corners come from", () => {
    const s = asF2(stopped(fixture("edited-garage-between-runs")));
    const corners = s.track_model?.corners.length ?? 0;
    expect(corners).toBeGreaterThan(0);
    s.track_model = { ...s.track_model!, car_family: "f1", car_family_match: false };
    expect(model(s).ready?.footer).toContain(`${corners} corners from F1 laps`);
    s.track_model = { ...s.track_model!, car_family: "f2", car_family_match: true };
    expect(model(s).ready?.footer).toContain(`${corners} corners learned`);
  });
});

describe("the F2 class block never breaks a minimal snapshot", () => {
  it("snap() with the class: the line and the model work", () => {
    const s = snap({ session: { ...f2JeddahSession(), car_class: F2_CLASS } });
    expect(statusLine(s).carClass).toBe("F2");
    expect(model(s).status.text).toContain("Jeddah · F2 · Feature race");
  });
});
