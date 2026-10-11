// Moving or stationary with hysteresis (integration plan 2.1, 2.7): no flicker at 4-6 km/h, 1.5 s to stop away from
// the pits, at once in the pit lane and the garage, no frame / no live data = stationary. Pure; plain node.
import { describe, expect, it } from "vitest";
import { driveModel } from "./model";
import { MOVE_ABOVE_KPH, STOP_AFTER_S, STOP_BELOW_KPH, motionOf, nextMotion, type Motion } from "./motion";
import { driver, fixture, frame, newestT, snap } from "./testkit";

const at = (speed_kph: number | null) => ({ speed_kph });

/** Feed speeds one per `stepS` from `start`; returns the stationary answer after each. */
function run(speeds: (number | null)[], start: Motion | null, stepS = 0.05, place: "pits" | "track" = "track"): boolean[] {
  let m = start;
  return speeds.map((v, i) => {
    m = nextMotion(at(v), m, 100 + i * stepS, { place });
    return m.stationary;
  });
}

describe("motion.ts", () => {
  it("thresholds: under 3 km/h for 1.5 s to stop, over 8 km/h to move", () => {
    expect([STOP_BELOW_KPH, STOP_AFTER_S, MOVE_ABOVE_KPH]).toEqual([3, 1.5, 8]);
  });

  it("no flicker between 4 and 6 km/h, whichever way the car was going", () => {
    const crawl = [4, 6, 4.5, 5.9, 4.1, 6, 5, 4];
    expect(run(crawl, { stationary: true, slowSince: null })).toEqual(crawl.map(() => true));
    expect(run(crawl, { stationary: false, slowSince: null })).toEqual(crawl.map(() => false));
    // and a speedometer wobbling around 5 km/h from a stop never flips it (the old single 5 km/h line did)
    expect(run([4.9, 5.1, 4.9, 5.1, 4.9], nextMotion(at(0), null, 0))).toEqual([true, true, true, true, true]);
  });

  it("stops after 1.5 s under 3 km/h on track; a burst over 3 km/h starts the wait over", () => {
    const moving: Motion = { stationary: false, slowSince: null };
    const slow = Array.from({ length: 40 }, () => 1); // 2 s at 20 Hz
    const r = run(slow, moving);
    expect(r.indexOf(true)).toBe(30); // 30 x 50 ms = 1.5 s after the first slow frame
    const bumpy = [...Array.from({ length: 20 }, () => 1), 4, ...Array.from({ length: 40 }, () => 1)];
    expect(run(bumpy, moving).indexOf(true)).toBe(51); // 1.5 s after the 4 km/h frame
  });

  it("in the pit lane and the garage: stationary as soon as it is under 3 km/h", () => {
    expect(run([2], { stationary: false, slowSince: null }, 0.05, "pits")).toEqual([true]);
    expect(run([5], { stationary: false, slowSince: null }, 0.05, "pits")).toEqual([false]);
  });

  it("moves at once over 8 km/h", () => {
    expect(run([9], { stationary: true, slowSince: null })).toEqual([false]);
    expect(run([8], { stationary: true, slowSince: null })).toEqual([true]);
  });

  it("no frame, or data that is not live (stale, offline), is stationary; an unknown speed keeps the last answer", () => {
    expect(nextMotion(null, { stationary: false, slowSince: null }, 0).stationary).toBe(true);
    expect(nextMotion(at(250), null, 0, { live: false }).stationary).toBe(true);
    expect(nextMotion(at(null), { stationary: true, slowSince: null }, 0).stationary).toBe(true);
    expect(nextMotion(at(null), { stationary: false, slowSince: null }, 0).stationary).toBe(false);
    expect(nextMotion(at(null), null, 0).stationary).toBe(false); // not known to be stopped: the safe side
    expect(motionOf(null, null, 0, "track").stationary).toBe(true);
    const stale = fixture("recorded-austria-stale"); // 286 km/h on the last frame, then nothing
    expect(motionOf(stale, null, 0, "track").stationary).toBe(true);
  });

  it("returns the same object when nothing changed (callers compare by identity)", () => {
    const m = nextMotion(at(0), null, 0);
    expect(nextMotion(at(1), m, 1)).toBe(m);
    const going = nextMotion(at(100), null, 0);
    expect(nextMotion(at(120), going, 1)).toBe(going);
  });
});

describe("what waits for a stationary car (plan 2.1)", () => {
  const T = 1_791_669_000;
  const base = { connected: true, nowS: T, driver: driver() };

  it("the game mismatch band: only while stationary", () => {
    const mismatch = { text: "F1 25 data · GT7 selected", sub: "tap to change" };
    const still = snap({ frame: frame({ speed_kph: 0 }) });
    expect(driveModel({ ...base, snap: still, mismatch }).status.band).toBe("mismatch");
    const moving = snap({ frame: frame({ speed_kph: 120 }) });
    expect(driveModel({ ...base, snap: moving, mismatch }).status.band).toBe("normal");
    // crawling at 5 km/h after a stop: still the band; crawling at 5 km/h while pulling away: the line
    const stopped = driveModel({ ...base, snap: still, mismatch });
    const crawl = snap({ frame: frame({ speed_kph: 5 }) });
    expect(driveModel({ ...base, snap: crawl, mismatch, motion: stopped.motion }).status.band).toBe("mismatch");
    const going = driveModel({ ...base, snap: moving, mismatch });
    expect(driveModel({ ...base, snap: crawl, mismatch, motion: going.motion }).status.band).toBe("normal");
  });

  it("the full coaching text (22 px) only while stationary; the glance text while moving", () => {
    const s = fixture("edited-d1-d6");
    const moving = driveModel({ ...base, nowS: newestT(s) + 1, snap: s });
    expect(moving).toMatchObject({ state: "on_track", stationary: false, coach: { full: false } });
    expect(moving.coach.size).not.toBe(22);
    const stopped = structuredClone(s);
    stopped.frame = { ...stopped.frame!, speed_kph: 0 };
    const m1 = driveModel({ ...base, nowS: newestT(s) + 1, snap: stopped, motion: moving.motion, clockS: 10 });
    expect(m1.stationary).toBe(false); // under 3 km/h for less than 1.5 s
    const m2 = driveModel({ ...base, nowS: newestT(s) + 3, snap: stopped, motion: m1.motion, clockS: 11.5 });
    expect(m2).toMatchObject({ state: "on_track", stationary: true, coach: { full: true, size: 22 } });
  });

  it("never on track: no Ready card while the car moves, even where the garage is inferred", () => {
    const grid = fixture("recorded-d246-suzuka-grid-before-start"); // no laps, lap clock at zero, 135 km/h
    const m = driveModel({ ...base, nowS: newestT(grid) + 1, snap: grid });
    expect(m).toMatchObject({ state: "on_track", card: null, ready: null, onTrack: true });
  });
});
