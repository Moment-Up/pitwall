import { describe, expect, it } from "vitest";
import type { SessionListRow } from "../endpoints/review";
import {
  filterByTrack,
  groupByDay,
  initialFilter,
  parseStoredFilter,
  rowSubtitle,
  trackKey,
  trackOptions,
  unownedLabel,
} from "./sessions";
import { fixtures } from "./testkit";

const at = (d: number, h: number, mi = 0) => new Date(2026, 9, d, h, mi).getTime() / 1000;

function row(id: string, started: number, p: Partial<SessionListRow> = {}): SessionListRow {
  return {
    id,
    game: "f1_25",
    platform: "ps5",
    track_id: "f1:7",
    track_name: "Silverstone",
    track_length_m: 5891,
    session_type: "practice",
    session_type_raw: "Practice",
    car_name: "F1 Generic",
    started_unix: started,
    source: "udp:20777",
    synthetic: false,
    lap_count: 12,
    best_clean_ms: 90702,
    weather: {},
    driver_id: 1,
    driver_name: "James",
    ...p,
  };
}

describe("driver filter (spec 6.1, acceptance 6)", () => {
  const ids = [1, 2, 3];

  it("[critic] starts on the seated driver, not Everyone", () => {
    expect(initialFilter(null, 2, ids)).toBe(2);
  });

  it("keeps a choice made on this device while the same driver is in the seat", () => {
    expect(initialFilter({ filter: "all", seat: 2 }, 2, ids)).toBe("all");
    expect(initialFilter({ filter: 3, seat: 2 }, 2, ids)).toBe(3);
  });

  it("a new driver in the seat lands on their own sessions, whatever was picked before", () => {
    expect(initialFilter({ filter: "all", seat: 1 }, 2, ids)).toBe(2);
  });

  it("a remembered driver who no longer exists falls back to the seated driver", () => {
    expect(initialFilter({ filter: 9, seat: 2 }, 2, ids)).toBe(2);
  });

  it("one profile (or none loaded yet), or nobody seated: everyone", () => {
    expect(initialFilter(null, 1, [1])).toBe("all");
    expect(initialFilter(null, null, [])).toBe("all");
    expect(initialFilter(null, null, ids)).toBe("all");
  });

  it("reads the stored value defensively", () => {
    expect(parseStoredFilter(JSON.stringify({ filter: 2, seat: 1 }))).toEqual({ filter: 2, seat: 1 });
    expect(parseStoredFilter(JSON.stringify({ filter: "all", seat: null }))).toEqual({ filter: "all", seat: null });
    expect(parseStoredFilter(JSON.stringify({ filter: "x" }))).toBeNull();
    expect(parseStoredFilter("{oops")).toBeNull();
    expect(parseStoredFilter(null)).toBeNull();
    expect(parseStoredFilter(JSON.stringify({ filter: 1.5, seat: "a" }))).toBeNull();
  });
});

describe("day groups", () => {
  const now = new Date(2026, 9, 11, 21, 0).getTime();

  it("groups by local day, newest first, with Today / Yesterday / dates", () => {
    const g = groupByDay(
      [row("a", at(3, 19, 15)), row("b", at(11, 18, 55)), row("c", at(10, 20, 10)), row("d", at(11, 19, 40))],
      now,
    );
    expect(g.map((x) => [x.title, x.rows.map((r) => r.id)])).toEqual([
      ["Today", ["d", "b"]],
      ["Yesterday", ["c"]],
      ["3 Oct", ["a"]],
    ]);
  });

  it("groups the recorded list without losing a row", () => {
    const rows = fixtures.sessions();
    const g = groupByDay(rows, now);
    expect(g.reduce((n, x) => n + x.rows.length, 0)).toBe(rows.length);
    expect(new Set(g.map((x) => x.key)).size).toBe(g.length);
  });
});

describe("rows and tracks", () => {
  it("writes the second line from what is known", () => {
    expect(rowSubtitle(row("a", at(11, 19, 41), { session_type_raw: "Race", car_name: "Haas", lap_count: 10 }))).toBe(
      "Race · Haas · 10 laps · 19:41",
    );
    expect(
      rowSubtitle(row("b", at(11, 7, 5), { session_type_raw: null, session_type: "unknown", car_name: null, lap_count: 1 })),
    ).toBe("1 lap · 07:05");
    expect(rowSubtitle(row("c", at(11, 7, 5), { clean_lap_count: 9 }))).toBe("Practice · F1 Generic · 9 of 12 clean · 07:05");
    // the game's AI difficulty when it reported one (AI pace); unknown is left out, 0 is a level
    expect(rowSubtitle(row("d", at(11, 19, 15), { session_type_raw: "Race", ai_difficulty: 35, lap_count: 3 }))).toBe(
      "Race · F1 Generic · 3 laps · 19:15 · AI 35",
    );
    expect(rowSubtitle(row("e", at(11, 19, 15), { ai_difficulty: 0, lap_count: 3 }))).toBe("Practice · F1 Generic · 3 laps · 19:15 · AI 0");
    expect(rowSubtitle(row("f", at(11, 19, 15), { ai_difficulty: null, lap_count: 3 }))).toBe("Practice · F1 Generic · 3 laps · 19:15");
  });

  it("track options are per game + track id, most sessions first", () => {
    const opts = trackOptions([
      row("a", 1),
      row("b", 2, { track_id: "f1:17", track_name: "Austria" }),
      row("c", 3, { track_id: "f1:17", track_name: "Austria" }),
      row("d", 4, { track_id: null, track_name: null }),
      row("e", 5, { game: "gt7", track_id: "f1:7", track_name: "Silverstone (GT7)" }),
    ]);
    expect(opts.map((o) => [o.label, o.sessions])).toEqual([
      ["Austria", 2],
      ["Silverstone", 1],
      ["Silverstone (GT7)", 1],
    ]);
    expect(trackKey(row("x", 1, { track_id: null }))).toBeNull();
  });

  it("filters by track (null = all tracks)", () => {
    const rows = fixtures.sessions();
    const austria = filterByTrack(rows, "f1_25|f1:17");
    expect(austria.length).toBeGreaterThan(0);
    expect(austria.every((r) => r.track_name === "Austria")).toBe(true);
    expect(filterByTrack(rows, null)).toHaveLength(rows.length);
  });

  it("an unowned replay says Replay", () => {
    expect(unownedLabel({ source: "replay:synthetic.pwcap" })).toBe("Replay");
    expect(unownedLabel({ source: "udp:20777" })).toBe("Unknown driver");
  });
});
