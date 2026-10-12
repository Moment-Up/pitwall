// Review with F2 sessions (F2 support, contract v1): titles use the server's session_label ("Feature race" for the
// game's "Race 2"), cars use its car_label ("F2 · Hitech '25" where the row stores "team_214"), ⌘K finds them by
// "F2", an F1 lap never contradicts an F2 PB, and another family's best is never offered as a reference. The rows are
// the owner's recorded F2 sessions with the contract's additions (lib/carclass-testkit.ts); without the additions (an
// older server) every word is as before.
import { describe, expect, it } from "vitest";
import { sessionBests, type AllTimeBest, type ScopeRow } from "../bests";
import { F1_CLASS, F2_CLASS, F2_ROWS } from "../carclass-testkit";
import type { DriverBestLap } from "../drivers";
import { refOptions } from "./compare";
import { lapsRows } from "./laps";
import { pointsFromRows, resolveScope, scopeChoices } from "./progress";
import { rowSubtitle, sessionSearchText } from "./sessions";
import { driver, fixtures } from "./testkit";
import { sessionTitle, sessionTypeLabel, timeOfDay } from "./words";

describe("titles and rows", () => {
  it("the race as F2 calls it: the game's 'Race' is the sprint, 'Race 2' the feature race", () => {
    expect(sessionTitle(F2_ROWS.melbourneSprint())).toBe("Melbourne · Sprint race");
    expect(sessionTitle(F2_ROWS.jeddahFeature())).toBe("Jeddah · Feature race");
    expect(sessionTitle(F2_ROWS.melbourneOneShot())).toBe("Melbourne · One-shot qualifying"); // as Drive writes it
  });

  it("an older server (no session_label): the game's own name, as before", () => {
    const { session_label: _l, ...old } = F2_ROWS.jeddahFeature();
    expect(sessionTypeLabel(old)).toBe("Race 2");
    expect(sessionTitle(old)).toBe("Jeddah · Race 2");
  });

  it("the row's second line names the car in words, never the stored raw id", () => {
    const r = F2_ROWS.melbourneSprint();
    expect(r.car_name).toBe("team_214");
    expect(rowSubtitle(r)).toBe(`Sprint race · F2 · Hitech '25 · 3 laps · ${timeOfDay(r.started_unix)} · AI 35`);
    const { car_label: _c, session_label: _s, car_class: _k, ...old } = r;
    expect(rowSubtitle(old)).toBe(`Race · 3 laps · ${timeOfDay(r.started_unix)} · AI 35`);
    expect(rowSubtitle(F2_ROWS.jeddahFeature())).toContain("Feature race · F2 · Art GP '24 · 5 laps");
  });

  it("⌘K finds the F2 sessions by 'F2'", () => {
    const t = sessionSearchText(F2_ROWS.jeddahFeature());
    expect(t).toBe("Jeddah · Feature race F2 F2 · Art GP '24");
    expect(t.toLowerCase()).toContain("f2");
    expect(sessionSearchText({ ...F2_ROWS.jeddahFeature(), synthetic: true })).toMatch(/synthetic$/);
    const { car_label: _c, car_class: _k, ...old } = F2_ROWS.melbourneSprint();
    expect(sessionSearchText(old)).toBe("Melbourne · Sprint race"); // "team_214" is never searchable text
  });
});

describe("an F1 lap never contradicts an F2 PB (a cut-off session list)", () => {
  const J = F2_ROWS.jeddahFeature();
  const row = (over: Partial<ScopeRow> = {}): ScopeRow => ({
    id: J.id,
    driver_id: 1,
    game: J.game,
    track_id: J.track_id,
    car_id: J.car_id,
    track_length_m: J.track_length_m,
    synthetic: false,
    source: J.source,
    best_clean_ms: J.best_clean_ms,
    started_unix: J.started_unix,
    car_class: F2_CLASS,
    ...over,
  });
  const at = (family: AllTimeBest["family"], ms: number, sessionId = "f1-session"): AllTimeBest => ({
    driverId: 1,
    game: "f1_25",
    trackId: "f1:29",
    ms,
    sessionId,
    synthetic: false,
    family,
  });

  it("the faster F1 best here leaves the F2 PB certain; a faster F2 best does not", () => {
    const s = row();
    expect(sessionBests(s, [s], { complete: false, allTime: [at("f1", 88000)] }).certain).toEqual({ household: true, driver: true });
    expect(sessionBests(s, [s], { complete: false, allTime: [at("f2", 104000, "older-f2")] }).certain).toEqual({
      household: false,
      driver: false,
    });
  });

  it("a best of unknown family, or a session without a class (an older server), still counts as before", () => {
    const s = row();
    expect(sessionBests(s, [s], { complete: false, allTime: [at(null, 88000)] }).certain.driver).toBe(false);
    const old = row({ car_class: undefined });
    expect(sessionBests(old, [old], { complete: false, allTime: [at("f1", 88000)] }).certain.driver).toBe(false);
  });
});

describe("Compare: another family's best is never offered as a reference", () => {
  const s = fixtures.austria();
  const a = fixtures.austriaAnalysis();
  const rows = lapsRows(s.laps, a, s);
  const best = (family: DriverBestLap["car_family"], id: number, ms: number): DriverBestLap => ({
    game: s.game,
    track_id: s.track_id!,
    track_name: "Austria",
    lap_time_ms: ms,
    lap_id: id,
    session_id: `x${id}`,
    car_name: family === "f2" ? "Art GP '24" : "Haas",
    synthetic: false,
    set_unix: 0,
    car_family: family,
    car_label: family === "f2" ? "F2 · Art GP '24" : "Haas",
  });

  it("an F2 session: Alex's F2 best, not the faster F1 one listed first", () => {
    const alex = driver(2, "Alex", "beginner");
    alex.stats.best_laps = [best("f1", 700, 72000), best("f2", 701, 79000)];
    const fam = refOptions({ rows, session: { ...s, car_class: F2_CLASS }, analysisRef: a.ref_lap, drivers: [alex] }).filter(
      (o) => o.group === "family",
    );
    expect(fam.map((o) => [o.id, o.ms])).toEqual([[701, 79000]]);
  });

  it("an F1 session with only an F2 best: nothing offered; an older server: as before", () => {
    const alex = driver(2, "Alex", "beginner");
    alex.stats.best_laps = [best("f2", 701, 79000)];
    expect(refOptions({ rows, session: { ...s, car_class: F1_CLASS }, analysisRef: a.ref_lap, drivers: [alex] }).some((o) => o.group === "family")).toBe(
      false,
    );
    expect(refOptions({ rows, session: s, analysisRef: a.ref_lap, drivers: [alex] }).filter((o) => o.group === "family").map((o) => o.id)).toEqual([
      701,
    ]);
  });
});

describe("Progress: the car and the session in the server's words", () => {
  it("the car picker and the points name the F2 car, never 'team_214'; the race as F2 calls it", () => {
    const rows = [F2_ROWS.melbourneSprint(), F2_ROWS.melbourneOneShot()];
    const choices = scopeChoices(rows, { includeSynthetic: false });
    const melbourne = choices.find((c) => c.trackId === "f1:0")!;
    expect(melbourne.cars.map((c) => c.label).sort()).toEqual(["F2 · Art GP '24", "F2 · Hitech '25"]);
    const pts = pointsFromRows(rows, resolveScope(choices, { track: "f1:0", car: "f1:team:214" })!);
    expect(pts.map((p) => [p.carName, p.sessionType])).toEqual([["F2 · Hitech '25", "Sprint race"]]);
  });
});
