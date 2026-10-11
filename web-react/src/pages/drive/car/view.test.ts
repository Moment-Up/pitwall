// Drive › Car view models (design spec 5.1) from the recorded, synthetic and edited Drive fixtures.
import { describe, expect, it } from "vitest";
import { driveModel, type DriveModel } from "../../../lib/drive/model";
import { FIXTURES, fixture, frame, lap, newestT, snap } from "../../../lib/drive/testkit";
import type { SnapshotNext } from "../../../lib/drive/types";
import { catalogue, entry } from "../../../lib/game-testkit";
import {
  carTile,
  coachingTile,
  eventWords,
  lapsTile,
  liveValues,
  mapTile,
  raceControlLine,
  RPM_HOT,
  tyreBand,
  tyresTile,
  WALL_LAPS,
  WALL_POINTS,
} from "./view";

function model(s: SnapshotNext | null, connected = true): DriveModel {
  return driveModel({ snap: s, connected, nowS: newestT(s) + 1, driver: null });
}

describe("car tile", () => {
  it("shows the live car while telemetry is current", () => {
    const s = fixture("recorded-d246-suzuka-on-track-brake-ahead");
    const v = carTile(s, model(s));
    expect(v.speed).toBe("122");
    expect(v.gear).toBe("3");
    expect(v.rpm.text).toBe("9\u202f244");
    expect(v.rpm.frac).toBeCloseTo(9244 / 13099, 5);
    expect(v.rpm.hot).toBe(false);
    expect(v.throttle).toEqual({ text: "62%", frac: 0.621, hot: false });
    expect(v.brake.text).toBe("0%");
    expect(v.steering).toBe("0.48"); // 0.485 in binary floating point
    expect(v.bias).toBe("58%");
    expect(v.drs).toBe("closed");
    expect(v.rate).toMatch(/^Telemetry [\d ]+\/s$/);
    expect(v.health).toBe("0 rejected · 0 unrecognised · replay:20261010-225601_udp20777.pwcap");
  });

  it("turns the RPM bar red above 94 % of the maximum", () => {
    const s = snap({ frame: frame({ rpm: 12_400, max_rpm: 13_000 }) });
    expect(12_400 / 13_000).toBeGreaterThan(RPM_HOT);
    expect(carTile(s, model(s)).rpm.hot).toBe(true);
  });

  it("negative steering uses the minus sign; reverse and neutral gears are words", () => {
    const s = snap({ frame: frame({ steering: -0.04, gear: -1 }) });
    const v = carTile(s, model(s));
    expect(v.steering).toBe("−0.04");
    expect(v.gear).toBe("R");
    expect(carTile(snap({ frame: frame({ gear: 0 }) }), model(snap())).gear).toBe("N");
  });

  it("stale: every live value is '-', the brake bias (a setting) stays", () => {
    const s = fixture("recorded-austria-stale");
    const m = model(s);
    expect(m.state).toBe("stale");
    expect(liveValues(m)).toBe(false);
    const v = carTile(s, m);
    for (const t of [v.speed, v.gear, v.rpm.text, v.throttle.text, v.brake.text, v.steering, v.drs]) expect(t).toBe("-");
    expect(v.rpm.frac).toBeNull();
    expect(v.throttle.frac).toBeNull();
  });

  it("offline: '-' everywhere, the rate and health say nothing current", () => {
    const s = fixture("recorded-d246-suzuka-on-track-brake-ahead");
    const m = model(s, false);
    expect(m.state).toBe("offline");
    const v = carTile(s, m);
    expect(v.speed).toBe("-");
    expect(v.rate).toBe("Telemetry -");
    expect(v.health).toBe("Telemetry health unknown while offline");
  });

  it("unknown inputs are never 0", () => {
    const s = snap({ frame: frame({ speed_kph: null, throttle: null, brake: null, rpm: null, steering: null, drs_open: null }) });
    const v = carTile(s, model(s));
    expect(v.speed).toBe("-");
    expect(v.throttle).toEqual({ text: "-", frac: null, hot: false });
    expect(v.rpm.text).toBe("-");
    expect(v.drs).toBe("-");
    expect(v.bias).toBe("-");
  });
});

describe("tyres tile", () => {
  it("FL FR RL RR with the band colour and a word outside the window", () => {
    const s = fixture("recorded-d246-suzuka-on-track-brake-ahead"); // 89 69 75 67 °C
    const v = tyresTile(s);
    expect(v.wheels.map((w) => w.wheel)).toEqual(["FL", "FR", "RL", "RR"]);
    expect(v.wheels.map((w) => w.temp)).toEqual(["89°", "69°", "75°", "67°"]);
    expect(v.wheels[0]).toMatchObject({ band: "ok", word: null, colour: "var(--pw-tyre-optimal)" });
    expect(v.wheels[1]).toMatchObject({ band: "cold", word: "cold", colour: "var(--pw-tyre-cold)" });
    expect(v.wheels[2]).toMatchObject({ band: "cool", word: "cool" });
    expect(v.wheels[0]!.sub).toBe("12% · 24.3 psi");
    expect(v.wheels[1]!.aria).toBe("FR: surface 69 degrees, cold, wear 13 percent, pressure 24.3 psi");
    expect(v.chip).toBe("Soft · 4 laps");
    expect(v.energy).toBe("Fuel 5.8 kg · +2.4 laps (game) · ERS 4.0 MJ");
  });

  it("bands: cold < 75, cool < 85, in the window to 105, hot to 115, over above", () => {
    expect([60, 80, 95, 110, 120, null].map(tyreBand)).toEqual(["cold", "cool", "ok", "hot", "over", "unknown"]);
  });

  it("unknown tyres and fuel are '-', the game's margin left out", () => {
    const v = tyresTile(snap());
    expect(v.wheels.every((w) => w.temp === "-" && w.sub === "- · -" && w.band === "unknown")).toBe(true);
    expect(v.chip).toBeNull();
    expect(v.energy).toBe("Fuel - · ERS -");
    expect(tyresTile(null).energy).toBe("Fuel - · ERS -");
  });
});

describe("laps tile (current standing)", () => {
  it("newest first, SB only on the session best, R on the reference, INV with the reason", () => {
    const s = fixture("recorded-d246-suzuka-on-track-brake-ahead");
    s.connection = { ...s.connection, source: "udp:20777" }; // as the live session (the fixture is a replay)
    const v = lapsTile(s);
    expect(v.sub).toBe("current standing · ref L3");
    expect(v.rows.map((r) => r.lap)).toEqual([4, 3, 2, 1]);
    const [l4, l3, l2, l1] = v.rows;
    expect(l4!.time).toEqual({ ms: 97037, status: "sb" });
    expect(l3!.time.status).toBe("slower");
    expect(l3!.ref).toBe(true);
    expect(l3!.delta).toBeNull();
    expect(l4!.delta).toBe("−0.15");
    expect(l2!.time.status).toBe("invalid");
    expect(l2!.reason).toBe("reset to track");
    expect(l1!.reason).toBe("reset to track, flashback, standing start");
    // Sectors by current standing: S1 best on lap 4, S2 best on lap 3.
    expect(l4!.sectors.map((c) => c.status)).toEqual(["sb", "slower", "sb"]);
    expect(l3!.sectors.map((c) => c.status)).toEqual(["slower", "sb", "slower"]);
    expect(l2!.sectors.every((c) => c.status === "invalid")).toBe(true);
  });

  it("purple and PB never appear without D2 records (replays never get them)", () => {
    for (const name of FIXTURES) {
      const v = lapsTile(fixture(name));
      for (const r of v.rows) {
        for (const c of [r.time, ...r.sectors]) expect(["rec", "pb"], name).not.toContain(c.status);
      }
    }
  });

  it("with D2 records in a real session: REC and PB by current standing", () => {
    const s = fixture("edited-d1-d6");
    s.connection = { ...s.connection, source: "udp:20777" }; // the edit's records, as a live session would get them
    // D2 recomputed after lap 4, as `repo.lap_bests` does: lap 4 (97037) set the driver's best (not the household's,
    // 96100), and its S1 (35546) the household's S1; the setter ids say so
    const l4 = s.laps[0]!.lap_id;
    s.bests!.driver = { ...s.bests!.driver!, lap_ms: 97037, lap_id: l4 };
    s.bests!.household = { ...s.bests!.household!, sectors_ms: [35546, 41500, 18500], sector_lap_ids: [l4, 1, 1] };
    const v = lapsTile(s);
    expect(v.tier).toBe(2);
    expect(v.rows[0]!.time.status).toBe("pb");
    expect(v.rows[0]!.sectors[0]!.status).toBe("rec");
    // a later lap that only ties those bests does not take them (the earlier setter keeps them)
    s.bests!.driver = { ...s.bests!.driver!, lap_id: l4 - 50 };
    expect(lapsTile(s).rows[0]!.time.status).toBe("sb");
  });

  it("synthetic and replay laps carry no timing colour (4.6, as on Coach and in Review > Laps); INV stays", () => {
    const s = fixture("recorded-d246-suzuka-on-track-brake-ahead");
    for (const conn of [{ synthetic: true }, { source: "replay:capture.pwcap" }]) {
      const v = lapsTile({ ...s, connection: { ...s.connection, ...conn } });
      const statuses = v.rows.flatMap((r) => [r.time, ...r.sectors].map((c) => c.status));
      expect(statuses.filter((st) => st !== "neutral" && st !== "invalid")).toEqual([]);
      expect(statuses).toContain("invalid");
    }
  });

  it("PIT tag on pit laps; at most 8 rows; unknown times stay null", () => {
    const laps = Array.from({ length: 12 }, (_, i) => lap(12 - i, 90_000 + i * 100, [30_000, 30_000, null]));
    laps[1] = lap(11, null, [], { clean: false, flags: ["pit_in"] });
    const v = lapsTile(snap({ laps, reference: null }));
    expect(v.rows).toHaveLength(WALL_LAPS);
    expect(v.rows[1]).toMatchObject({ pit: true, reason: "pit in", time: { ms: null, status: "invalid" } });
    expect(v.rows[0]!.sectors[2]).toEqual({ ms: null, status: "neutral" });
    expect(v.sub).toBe("current standing · no reference yet");
    expect(v.rows[0]!.delta).toBeNull();
  });

  it("no laps: an empty state, never a table of dashes", () => {
    expect(lapsTile(fixture("pipeline-no-data")).empty).toBe("No completed laps yet");
    expect(lapsTile(null).rows).toEqual([]);
  });
});

describe("coaching tile", () => {
  it("D6: the radio's picks first, corner chips by official label, signed time in the corner", () => {
    const s = fixture("recorded-d246-suzuka-on-track-brake-ahead");
    const v = coachingTile(s, false);
    expect(v.source).toBe("d6");
    expect(v.title).toBe(`Coaching · lap ${s.coach!.lap_number}`);
    expect(v.items.length).toBeLessThanOrEqual(WALL_POINTS);
    expect(v.items.length).toBeGreaterThan(0);
    const first = s.coach!.picked.filter((o) => o.kind !== "incident")[0]!;
    expect(v.items[0]!.id).toBe(first.id);
    expect(v.items[0]!.text).toBe(first.short ?? first.text);
    for (const it of v.items) {
      if (it.impact) expect(it.impact).toMatch(/^[+−]\d+\.\d\d s$/);
      expect(it.impactTone === "ahead").toBe(it.impact?.startsWith("−") ?? false);
      if (it.good) expect(it.chip).toMatch(/ · good$/);
    }
  });

  it("before D6: the top observations by priority, verbatim, never an incident", () => {
    const s = fixture("recorded-suzuka-on-track-brake-ahead");
    const v = coachingTile(s, false);
    expect(v.source).toBe("observation");
    const top = s.observations.filter((o) => o.kind !== "incident").sort((a, b) => b.priority - a.priority)[0]!;
    expect(v.items[0]!.text).toBe(top.text);
  });

  it("says why there is nothing", () => {
    expect(coachingTile(snap({ reference: null }), false).empty).toBe("Coaching starts after your first clean lap");
    expect(coachingTile(snap(), false).empty).toBe("No coaching points on the last lap");
    expect(coachingTile(null, false).empty).toBe("No coaching yet");
  });
});

describe("race control line", () => {
  it("names session events; per-car events never claim whose car", () => {
    expect(eventWords({ kind: "penalty", code: "PENA" })).toBe("Penalty issued");
    expect(eventWords({ kind: "penalty", code: "PENA", player: true })).toBe("Penalty for you");
    expect(eventWords({ kind: "collision", code: "COLL" })).toBe("Collision reported");
    expect(eventWords({ kind: "chequered_flag", code: "CHQF" })).toBe("Chequered flag");
    expect(eventWords({ kind: "other", code: "DRSE" })).toBe("DRS enabled");
    expect(eventWords({ kind: "other", code: "OVTK" })).toBeNull();
    expect(eventWords({ kind: "button", code: "BUTN" })).toBeNull();
  });

  it("the newest announced event with its age; overtakes and speed traps skipped", () => {
    const now = 1_000;
    const ev = (kind: string, code: string | null, t: number) => ({ kind, code, session_time_s: null, t });
    expect(raceControlLine([ev("other", "OVTK", 999), ev("penalty", "PENA", 880)], now)).toBe("Race control · Penalty issued · 2 min ago");
    expect(raceControlLine([ev("session_started", "SSTA", 998)], now)).toBe("Race control · Session started · just now");
    expect(raceControlLine([ev("other", "SPTP", 990)], now)).toBe("Race control · nothing yet");
    expect(raceControlLine([], now)).toBe("Race control · nothing yet");
  });

  it("from a recorded race", () => {
    const s = fixture("recorded-austria-session-ended");
    expect(raceControlLine(s.events, newestT(s) + 30)).toBe("Race control · Session ended · 30 s ago");
  });
});

describe("map tile", () => {
  it("live: the car, the next corner, focus, brake notches and the live flags", () => {
    const s = fixture("recorded-d246-suzuka-on-track-brake-ahead");
    const v = mapTile(s, model(s));
    expect(v.car).toEqual([-88.92, 148.55]);
    expect(v.highlight).toBe("T7");
    expect(v.focus).toEqual(["T7"]);
    expect(v.cueTargetsM).toEqual([2826.3]);
    expect(v.flags).toEqual(s.marshal_flags);
    expect(v.caption).toMatch(/^\d+ corners · official names$/);
    expect(v.sectorStatus).toBeNull(); // no D1: the last lap's sectors are never painted on as this lap's
  });

  it("D1: this lap's sectors as set", () => {
    const s = fixture("edited-d1-d6");
    const v = mapTile(s, model(s));
    expect(v.sectorStatus).toHaveLength(3);
    expect(v.sectorStatus![1]).toBe("running");
  });

  it("stale and offline: no car, no flags, no next corner", () => {
    const s = fixture("recorded-austria-stale");
    const v = mapTile(s, model(s));
    expect(v).toMatchObject({ car: null, carM: null, flags: null, highlight: null });
    const off = mapTile(fixture("recorded-d246-suzuka-on-track-brake-ahead"), model(fixture("recorded-d246-suzuka-on-track-brake-ahead"), false));
    expect(off.car).toBeNull();
  });

  it("learned names say so; no model says the track is being learned", () => {
    const s = fixture("synthetic-demo-on-track-brake-ahead");
    expect(mapTile(s, model(s)).caption).toMatch(/^\d+ corners learned$/);
    expect(mapTile(snap(), model(snap())).caption).toBe("Learning the track");
  });
});

// ------------------------------------------------------------------------------------- game selection (spec 5.4)
describe("what the game sends (game selection)", () => {
  const CAT = catalogue();
  const F1 = entry("f1_25:ps5", CAT);
  const GT7 = entry("gt7:ps5", CAT);
  const AC = entry("ac:ps5", CAT);
  const FM = entry("forza_motorsport:pc", CAT);
  const OTHER = entry("other:any", CAT);

  it("F1 25: every tile exactly as without a game (existing behaviour)", () => {
    const s = fixture("recorded-d246-suzuka-on-track-brake-ahead");
    const m = model(s);
    expect(carTile(s, m, F1)).toEqual(carTile(s, m));
    expect(tyresTile(s, F1)).toEqual(tyresTile(s));
    expect(lapsTile(s, WALL_LAPS, F1)).toEqual(lapsTile(s));
    expect(raceControlLine(s.events, newestT(s) + 1, F1)).toBe(raceControlLine(s.events, newestT(s) + 1));
    expect(tyresTile(s, F1).caption).toBeNull();
    expect(tyresTile(s, F1).empty).toBeNull();
  });

  it("GT7 (a real GT7 snapshot): temperatures only, no DRS cell, fuel and ERS said in words", () => {
    const s = fixture("recorded-live-api-gt7-stale");
    const v = tyresTile(s, GT7);
    expect(v.wheels.map((w) => w.temp)).toEqual(["65°", "71°", "66°", "72°"]);
    expect(v.wheels.every((w) => w.sub === null)).toBe(true); // no wear and no pressures: no sub line
    expect(v.wheels[0]!.aria).toBe("FL: surface 65 degrees, cold");
    expect(v.caption).toBe("Tyre wear, pressures: not sent by GT7");
    expect(v.empty).toBeNull();
    expect(v.energy).toBe("Fuel, ERS: not in Pitwall yet");
    const c = carTile(s, model(s), GT7);
    expect(c.drsShown).toBe(false);
    expect(carTile(s, model(s)).drsShown).toBe(true);
  });

  it("Assetto Corsa: one line instead of a grid of dashes; fuel and ERS not sent", () => {
    const s = snap({ frame: frame({ tyre_surface_temp_c: null, tyre_wear_pct: null, tyre_pressure_psi: null, fuel_kg: null, ers_store_j: null }) });
    const v = tyresTile(s, AC);
    expect(v.empty).toBe("Assetto Corsa doesn't send tyre data");
    expect(v.caption).toBeNull();
    expect(v.energy).toBe("Fuel, ERS: not sent by Assetto Corsa");
  });

  it("Forza Motorsport: wear kept, pressures said; the fuel / ERS footer mixes the two reasons", () => {
    const s = snap({ frame: frame({ tyre_surface_temp_c: [80, 81, 82, 83], tyre_wear_pct: [3, 3, 4, 4], tyre_pressure_psi: null }) });
    const v = tyresTile(s, FM);
    expect(v.wheels[0]!.sub).toBe("3%");
    expect(v.caption).toBe("Tyre pressures: not sent by Forza Motorsport");
    expect(v.energy).toBe("Fuel: not in Pitwall yet · ERS: not sent by Forza Motorsport");
  });

  it("an unknown game ('Another game') keeps every dash: nothing is claimed about it", () => {
    const s = snap();
    expect(tyresTile(s, OTHER)).toEqual(tyresTile(s));
    expect(carTile(s, model(s), OTHER).drsShown).toBe(true);
    expect(lapsTile(s, WALL_LAPS, OTHER).sectors).toBe(true);
    expect(raceControlLine([], 0, OTHER)).toBe("Race control · nothing yet");
  });

  it("laps tile: no sector columns for GT7, with the reason in the foot", () => {
    const s = fixture("recorded-live-api-gt7-stale");
    const v = lapsTile(s, WALL_LAPS, GT7);
    expect(v.sectors).toBe(false);
    expect(v.noSectors).toBe("No sectors from GT7");
    const f1 = lapsTile(fixture("recorded-d246-suzuka-on-track-brake-ahead"), WALL_LAPS, F1);
    expect(f1.sectors).toBe(true);
    expect(f1.noSectors).toBeNull();
    expect(lapsTile(null, WALL_LAPS, AC)).toMatchObject({ empty: "No completed laps yet", sectors: false, noSectors: "No sectors from Assetto Corsa" });
  });

  it("map foot: the newest event first, else that the game sends no race control", () => {
    expect(raceControlLine([], 100, GT7)).toBe("Race control · not sent by GT7");
    expect(raceControlLine([], 100, F1)).toBe("Race control · nothing yet");
    expect(raceControlLine([{ kind: "session_started", code: null, session_time_s: 0, t: 90 }], 100, GT7)).toBe(
      "Race control · Session started · 10 s ago",
    );
  });
});
