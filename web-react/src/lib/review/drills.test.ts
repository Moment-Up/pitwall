import { describe, expect, it } from "vitest";
import { crFixture } from "../../test/coachref";
import { fixture } from "../drive/testkit";
import type { CandidatesResponse, DrillView } from "../endpoints/coachref";
import type { ReviewTrackModel } from "../endpoints/review";
import { candidateOptions, explainerText, refOptions, refWordsFor, type CompareCorner } from "./compare";
import {
  NO_DRILLS,
  attemptRows,
  bestAttempt,
  drillComparePath,
  drillRow,
  drillRows,
  drillThisKind,
  drillsQuery,
  liveDrillKey,
  parseLiveDrill,
} from "./drills";

const SUZUKA = fixture("edited-garage-between-runs").track_model as unknown as ReviewTrackModel;
const NOW_MS = 1791140400_000 + 3600_000;

describe("Review › Coaching: Drills (spec 10.7)", () => {
  it("asks for the viewed driver at this track and car (any car = no car filter)", () => {
    const scope = { track: { game: "f1_25", trackId: "f1:13" }, carId: "f1:team:41" };
    expect(drillsQuery(1, scope)).toEqual({ driver_id: 1, game: "f1_25", track_id: "f1:13", car_id: "f1:team:41", limit: 20 });
    expect(drillsQuery(1, { ...scope, carId: null })?.car_id).toBeNull();
    expect(drillsQuery(null, scope)).toBeNull();
    expect(drillsQuery(1, null)).toBeNull();
  });

  it("rows: date · corner (official label and name) · skill · hits of scored · best · trend · vs reference, newest first", () => {
    const rows = drillRows(crFixture<DrillView[]>("drills-history-suzuka"), SUZUKA, NOW_MS);
    expect(rows.map((r) => r.id)).toEqual([14, 11]);
    expect(rows[0]).toMatchObject({
      corner: "T11 Hairpin",
      skill: "Brake point",
      score: "3 of 4 on the point",
      best: "Best: 1 m from the point",
      trend: "Closer",
      vs: "vs Sam's best",
      status: null,
      synthetic: false,
    });
    // A 5-lap drill stopped after 2 says so: "2 of 2" alone would read as finished (UX review L6)
    expect(rows[1]).toMatchObject({
      corner: "T9 Degner 2",
      skill: "Minimum speed",
      score: "1 of 2 on target",
      best: "Best: 99 km/h",
      trend: null,
      vs: "vs Your best",
      status: "Stopped after 2 of 5 laps",
    });
    expect(rows[0]?.text).toContain("3 of 4 on the point");
    expect(rows[1]?.text).toContain("1 of 2 on target");
  });

  it("without a track model the label stored at the start stands in", () => {
    expect(drillRow(crFixture<DrillView>("drill-completed"), null, NOW_MS).corner).toBe("T11");
  });

  it("the empty list's words", () => {
    expect(NO_DRILLS).toBe('No drills here yet. Start one from Drive before a run, or say "start a drill on turn 3".');
  });

  it("each lap of a drill: lap, where or how fast, against the target in words, outcome", () => {
    const rows = attemptRows(crFixture<DrillView>("drill-completed"));
    expect(rows.map((r) => [r.lap, r.value, r.delta, r.outcomeText])).toEqual([
      // a brake point's lap distance says nothing to the driver: the words against the point do
      ["L6", null, "1 m before the point", "Hit"],
      ["L7", null, "11 m past the point", "Miss"],
      ["L8", null, "3 m before the point", "Hit"],
      ["L9", null, "-", "Not measured: no braking measured"],
      ["L10", null, "1 m before the point", "Hit"],
    ]);
    const [, speed] = crFixture<DrillView[]>("drills-history-suzuka");
    expect(attemptRows(speed!).map((r) => [r.value, r.delta, r.outcomeText])).toEqual([
      ["99 km/h", "+1 km/h", "Hit"],
      ["95 km/h", "−3 km/h, short", "Miss: exit 4 km/h down"],
    ]);
  });

  it("See it on the lap: the best attempt's lap against the reference, at the corner", () => {
    const d = crFixture<DrillView>("drill-completed");
    expect(bestAttempt(d)?.attempt).toBe(5); // 0.6 m from the point
    const path = drillComparePath(d, SUZUKA, 5807);
    expect(path).toMatch(/^\/review\/sessions\/e3e0d6df9e22\/compare\?ref=812&lap=905&at=\d+$/);
    const [, speed] = crFixture<DrillView[]>("drills-history-suzuka");
    expect(bestAttempt(speed!)?.attempt).toBe(1); // the fastest minimum speed
    expect(drillComparePath({ ...d, session_id: null }, SUZUKA, 5807)).toBeNull();
    expect(drillComparePath({ ...d, attempts: [] }, SUZUKA, 5807)).toBeNull();
  });
});

describe("Work on: Drill this (spec 10.6)", () => {
  const snap = {
    connection: { status: "live", synthetic: false },
    session: { game: "f1_25", track_id: "f1:13", car_name: "Ferrari" },
    coachref: { driver_id: 1 },
  };
  const session = { game: "f1_25", track_id: "f1:13", car_name: "Ferrari", driver_id: 1, synthetic: false };

  it("shows for this driver live at this game, track and car, on a point that maps to a drill", () => {
    const live = parseLiveDrill(liveDrillKey(snap, true, 9));
    expect(live).toEqual({ game: "f1_25", trackId: "f1:13", carName: "Ferrari", driverId: 1, synthetic: false });
    expect(drillThisKind(live, session, "brake_early")).toBe("brake_point");
    expect(drillThisKind(live, session, "coasting")).toBe("exit_speed");
    expect(drillThisKind(live, { ...session, car_name: null }, "low_min_speed")).toBe("min_speed"); // car unknown: no veto
  });

  it("hides for praise, another track or car, another driver in the seat, synthetic data, or no live session", () => {
    const live = parseLiveDrill(liveDrillKey(snap, true, null));
    expect(drillThisKind(live, session, "exit_gain")).toBeNull();
    expect(drillThisKind(live, { ...session, track_id: "f1:7" }, "brake_early")).toBeNull();
    expect(drillThisKind(live, { ...session, car_name: "Haas" }, "brake_early")).toBeNull();
    expect(drillThisKind(live, { ...session, driver_id: 2 }, "brake_early")).toBeNull();
    expect(drillThisKind(live, { ...session, synthetic: true }, "brake_early")).toBeNull();
    expect(drillThisKind(parseLiveDrill(liveDrillKey({ ...snap, connection: { status: "live", synthetic: true } }, true, 1)), session, "brake_early")).toBeNull();
    expect(liveDrillKey(snap, false, 1)).toBe("");
    expect(liveDrillKey({ ...snap, connection: { status: "no_data" } }, true, 1)).toBe("");
    // UX review H1: a session that is over (stale telemetry, or the game ended it) can only refuse a drill
    expect(liveDrillKey({ ...snap, connection: { status: "stale" } }, true, 1)).toBe("");
    expect(liveDrillKey({ ...snap, session_state: "ended" }, true, 1)).toBe("");
    expect(liveDrillKey({ ...snap, session_state: "running" }, true, 1)).not.toBe("");
    expect(drillThisKind(parseLiveDrill(""), session, "brake_early")).toBeNull();
    // A server without coachref: the seated driver stands in for the owner.
    expect(parseLiveDrill(liveDrillKey({ ...snap, coachref: null }, true, 1))?.driverId).toBe(1);
  });
});

describe("Review › Compare with another driver's lap (spec 10.5)", () => {
  const cands = crFixture<CandidatesResponse>("candidates-austria-66");

  it("picker A's family group comes from the candidates: compatible laps selectable, the others disabled with the reason", () => {
    const opts = candidateOptions(cands, new Set());
    expect(opts.map((o) => [o.id, o.title, o.disabled, o.detail])).toEqual([
      [64, "Your best here", false, "Haas · " + opts[0]!.detail!.split(" · ")[1]],
      [501, "Family record", false, expect.stringMatching(/^James · Haas · \d{1,2} [A-Z][a-z]{2}$/)],
      [-1, "Jo's best", true, "Jo's laps here used a different braking assist"],
    ]);
    // James's best is the same lap as the family record: listed once.
    expect(opts.filter((o) => o.id === 501)).toHaveLength(1);
    expect(opts[2]).toMatchObject({ canBeRef: false, reason: "Jo's laps here used a different braking assist" });
  });

  it("they replace the stats.best_laps family group; laps already offered are not repeated", () => {
    const out = refOptions({
      rows: [],
      session: { id: "s-austria", game: "f1_25", track_id: "f1:17", driver_id: 2, synthetic: false, source: "udp:20777" },
      analysisRef: null,
      drivers: [],
      candidates: cands,
    });
    expect(out.map((o) => o.title)).toEqual(["Your best here", "Family record", "Jo's best"]);
    expect(out.every((o) => o.group === "family")).toBe(true);
  });

  it("names another driver's lap instead of 'the reference', and never its lap number", () => {
    expect(refWordsFor("advanced", { own: false, label: "Sam's best", label_to: "Sam's best", driver_name: "Sam" })).toEqual({
      picker: "Sam's lap",
      sentence: "Sam's best",
    });
    expect(refWordsFor("advanced", { own: false, label: "Family record · Sam", label_to: "the family record", driver_name: "Sam" })).toEqual({
      picker: "Sam's lap",
      sentence: "the family record",
    });
    expect(refWordsFor("advanced", { own: false, label: "Sam's best" })).toEqual({ picker: "Sam's best", sentence: "Sam's best" });
    expect(refWordsFor("beginner", { own: true, label: "Your best" })).toEqual({ picker: "Your target lap", sentence: "your target lap" });
    expect(refWordsFor("advanced", null)).toEqual({ picker: "Reference", sentence: "the reference" });
    const corner = { spoken: "Stowe", timeS: 0.11, brakeM: -12, minSpeedKph: -4, exitSpeedKph: null, fullThrottleM: null } as unknown as CompareCorner;
    expect(explainerText(corner, 66, 64)).toBe(
      "At Stowe you braked 12 m earlier, your slowest speed was 4 km/h lower and the corner took 0.11 s longer (lap 66 against your reference, lap 64).",
    );
    expect(explainerText(corner, 66, 64, "Sam's best")).toBe(
      "At Stowe you braked 12 m earlier, your slowest speed was 4 km/h lower and the corner took 0.11 s longer (lap 66 against Sam's best).",
    );
  });
});
