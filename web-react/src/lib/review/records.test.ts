// Records (leaderboard spec 5): which board, the pickers, the words of the rows, the optional rows and the history,
// from the leaderboard service's real answers over a read-only copy of the owner's database ("recorded-", the second
// profile renamed Alex) and a generated Time Trial scenario with fictional names ("synthetic-").
import { describe, expect, it } from "vitest";
import type { Scope, TrackChoice } from "./progress";
import {
  anyBand,
  assistLabels,
  BAND_RULE,
  benchmarkKinds,
  benchmarkViews,
  boardPickers,
  boardQuery,
  boardShortTitle,
  candidateBoards,
  defaultBoardKey,
  emptyBoardText,
  familyLine,
  gapLine,
  HISTORY_SHOWN,
  historyItems,
  historySummary,
  isoDay,
  otherCarNote,
  pct,
  pctLine,
  pickBoard,
  recordsIndexQuery,
  sectorsLine,
  theoreticalLine,
  vsSentence,
} from "./records";
import { familyBoard } from "./progress";
import { boardFixtureBlocks, boardFixtures } from "./testkit";

const HAAS_RACE = "f1_25~f1:17~4323~f1:team:7~f1~0~race~dry~b2.a?.t?.g3.l2";
const GENERIC_RACE = "f1_25~f1:17~4323~f1:team:41~f1~0~race~dry~b0.a?.t?.g3.l2";
const TT_ABS_ON = "f1_25~f1:17~4318~f1:team:8~f1~0~time_trial~dry~b2.a1.t2.g3.l2";
const TT_ABS_OFF = "f1_25~f1:17~4318~f1:team:8~f1~0~time_trial~dry~b2.a0.t2.g3.l2";
const MCLAREN_RACE = "f1_25~f1:17~4318~f1:team:8~f1~0~race~dry~b2.a1.t2.g3.l2";

function track(over: Partial<TrackChoice> = {}): TrackChoice {
  return {
    game: "f1_25",
    trackId: "f1:17",
    label: "Austria",
    synthetic: false,
    sessions: 2,
    newest: 0,
    newestCarId: null,
    cars: [],
    unknownCar: 0,
    ...over,
  };
}

function scope(carId: string | null, carLabel: string | null = null, over: Partial<TrackChoice> = {}): Scope {
  return { track: track(over), carId, carLabel, carNamed: carLabel != null };
}

describe("which board the section opens on", () => {
  it("asks for the boards where the viewed driver has a lap at this track; never for a synthetic track", () => {
    expect(recordsIndexQuery(scope("f1:team:7"), 1)).toEqual({ game: "f1_25", track_id: "f1:17", driver_id: 1 });
    expect(recordsIndexQuery(scope(null, null, { synthetic: true, trackId: "synthetic:f1:17" }), 1)).toBeNull();
  });

  it("the viewed driver's newest board in the scope's car (any car: their newest anywhere here)", () => {
    const boards = boardFixtures.recordsAustriaJames().boards;
    expect(defaultBoardKey(boards, scope("f1:team:7", "Haas"))).toBe(HAAS_RACE);
    expect(defaultBoardKey(boards, scope("f1:team:41", "F1 Generic"))).toBe(GENERIC_RACE);
    expect(defaultBoardKey(boards, scope(null))).toBe(HAAS_RACE); // driven last
    expect(defaultBoardKey(boards, scope("f1:team:8", "McLaren"))).toBeNull();
    expect(defaultBoardKey(undefined, scope(null))).toBeNull();
    // Sam drove Time Trial with ABS off last: that board opens, not the one with the record of the family
    expect(defaultBoardKey(boardFixtures.recordsAustriaSam().boards, scope("f1:team:8", "McLaren"))).toBe(TT_ABS_OFF);
  });

  it("asks for the picked board, else the driver's, else the server's pick by fields (never any car on a board)", () => {
    const s = scope("f1:team:7", "Haas");
    expect(boardQuery(s, { pick: TT_ABS_ON, fallbackKey: HAAS_RACE, generation: null })).toEqual({
      key: TT_ABS_ON,
      car_generation: undefined,
    });
    expect(boardQuery(s, { pick: null, fallbackKey: HAAS_RACE, generation: "f1_2026" })).toEqual({
      key: HAAS_RACE,
      car_generation: "f1_2026",
    });
    expect(boardQuery(s, { pick: null, fallbackKey: null, generation: null })).toEqual({
      game: "f1_25",
      track_id: "f1:17",
      car_id: "f1:team:7",
      car_generation: undefined,
    });
    expect(boardQuery(scope(null), { pick: null, fallbackKey: null, generation: null })).toMatchObject({ car_id: undefined });
    expect(boardQuery(scope(null, null, { synthetic: true }), { pick: null, fallbackKey: null, generation: null })).toBeNull();
  });
});

describe("pickers (one per key part that differs between the boards here)", () => {
  it("in the scope's car: session type and assists, the assists named by the setting that differs", () => {
    const tt = boardFixtures.timeTrial();
    const p = boardPickers(tt.boards_here, tt, "f1:team:8");
    expect(p.map((x) => [x.dim, x.label, x.selected])).toEqual([
      ["category", "Session type", "time_trial"],
      ["assists", "Assists", "b2.a1.t2.g3.l2"],
    ]);
    expect(p[0]!.options).toEqual([
      { id: "time_trial", label: "Time trial" },
      { id: "race", label: "Race" },
    ]);
    expect(p[1]!.options).toEqual([
      { id: "b2.a0.t2.g3.l2", label: "ABS off" },
      { id: "b2.a1.t2.g3.l2", label: "ABS on" },
    ]);
  });

  it("any car: the cars too, each by name; a single choice is no picker", () => {
    const m = boardFixtures.melbourneMcLaren();
    const p = boardPickers(m.boards_here, m, null);
    expect(p.map((x) => x.dim)).toEqual(["car", "category", "assists"]);
    expect(p[0]!.options.map((o) => o.label)).toEqual(["F2 · Art GP '24", "F2 · Hitech '25", "McLaren"]);
    expect(p[1]!.options.map((o) => o.label)).toEqual(["Qualifying", "Race", "Practice"]);
    // in their usual order whatever the order of the boards (the server sorts by car first)
    const tt = boardFixtures.timeTrial();
    expect(boardPickers(tt.boards_here, tt, null).find((x) => x.dim === "category")!.options.map((o) => o.id)).toEqual([
      "time_trial",
      "race",
    ]);
    expect(p[2]!.options.map((o) => o.label)).toEqual([
      "Braking assist high, ABS on, Traction control unknown",
      "Braking assist medium, ABS unknown, Traction control unknown",
      "Braking assist low, ABS on, Traction control full",
    ]);
    // the McLaren alone: race and practice
    expect(boardPickers(m.boards_here, m, "f1:team:8").map((x) => x.dim)).toEqual(["category"]);
    // one board here: nothing to pick
    const miami = boardFixtures.miamiGeneric();
    expect(boardPickers(miami.boards_here, miami, null)).toEqual([]);
    expect(boardPickers([], null, null)).toEqual([]);
  });

  it("ABS on and off are two boards of the same car (Sakhir, F2)", () => {
    const s = boardFixtures.sakhirF2();
    const p = boardPickers(s.boards_here, s, "f1:team:158");
    expect(p).toHaveLength(1);
    expect(p[0]!.options.map((o) => o.label)).toEqual(["ABS off", "ABS on"]);
    expect(assistLabels(s.boards_here).get("b0.a1.t1.g3.l2")).toBe("ABS on");
  });

  it("a board nobody has driven yet still shows its own values", () => {
    const tt = boardFixtures.timeTrial();
    const wet = { fields: { ...tt.fields!, conditions: "wet" as const }, labels: { ...tt.labels!, conditions: "Wet" } };
    const p = boardPickers(tt.boards_here, wet, "f1:team:8");
    expect(p.find((x) => x.dim === "conditions")).toMatchObject({
      selected: "wet",
      options: [
        { id: "dry", label: "Dry" },
        { id: "wet", label: "Wet" },
      ],
    });
  });

  it("a pick opens the board that keeps the most of the others, newest first on a tie", () => {
    const tt = boardFixtures.timeTrial();
    const f = tt.fields!;
    expect(pickBoard(tt.boards_here, f, "category", "race", "f1:team:8")).toBe(MCLAREN_RACE);
    expect(pickBoard(tt.boards_here, f, "assists", "b2.a0.t2.g3.l2", "f1:team:8")).toBe(TT_ABS_OFF);
    // from the McLaren race, back to Time Trial: ABS on is kept (the race had it)
    const race = { ...f, category: "race" as const };
    expect(pickBoard(tt.boards_here, race, "category", "time_trial", "f1:team:8")).toBe(TT_ABS_ON);
    expect(pickBoard(tt.boards_here, f, "category", "qualifying", "f1:team:8")).toBeNull();
    // any car: the Haas board here
    expect(pickBoard(tt.boards_here, f, "car", "f1:team:7|f1", null)).toBe("f1_25~f1:17~4318~f1:team:7~f1~0~race~dry~b2.a1.t2.g3.l2");
  });

  it("the scope's car with no board here: the pickers choose among every board here", () => {
    const here = boardFixtures.austriaNoMatch().boards_here;
    expect(candidateBoards(here, "f1:team:3")).toHaveLength(2);
    expect(candidateBoards(here, "f1:team:7").map((b) => b.key)).toEqual([HAAS_RACE]);
  });
});

describe("rows in words", () => {
  it("the gap to the leader: the server's words, the percentage beyond the plain view; nothing for the leader", () => {
    const b = familyBoard([], boardFixtures.austriaHaas(), null);
    const [leader, second] = b.rows;
    expect(gapLine(leader!)).toBeNull();
    expect(gapLine(second!)).toBe("3.067 s behind");
    expect(pctLine(second!.gapPct, "plain")).toBeNull();
    expect(pctLine(second!.gapPct, "some")).toBe("4.35 %");
    expect(pctLine(null, "all")).toBeNull();
    expect(pct(10.28)).toBe("10.28 %");
    expect(pct(3)).toBe("3 %");
  });

  it("best sectors and their sum; a missing sector is '-', never made up", () => {
    expect(sectorsLine([16_662, 31_149, 22_151])).toBe("16.662 · 31.149 · 22.151");
    expect(sectorsLine([16_662, null, 22_151])).toBe("16.662 · - · 22.151");
    expect(sectorsLine([null, null, null])).toBeNull();
    expect(theoreticalLine(69_962, 587)).toBe("Added up: 1:09.962, 0.587 s to find");
    expect(theoreticalLine(65_900, 0)).toBe("Added up: 1:05.900");
    expect(theoreticalLine(null, null)).toBeNull();
  });

  it("a driver against an optional row: the band word only when the server sends a band", () => {
    const tt = familyBoard([], boardFixtures.timeTrial(), null);
    const jo = tt.rows[0]!;
    expect(jo.vs.ea_rival!.gap_text).toBe("1.400 s slower");
    expect(pctLine(jo.vs.real_f1!.gap_pct, "some")).toBe("3.02 %");
    expect(vsSentence(jo.vs.ea_rival!, "ea_rival")).toBe("Gold: 1.400 s slower than the EA rival");
    expect(vsSentence(jo.vs.real_f1!, "real_f1")).toBe("Silver: 1.929 s slower than the real F1 pole");
    const austria = familyBoard([], boardFixtures.austriaHaas(), null);
    expect(vsSentence(austria.rows[0]!.vs.real_f1!, "real_f1")).toBe("6.578 s slower than the real F1 pole");
    expect(vsSentence({ gap_ms: 0, gap_pct: 0, gap_text: "Same time", band: "gold" }, "ea_rival")).toBe(
      "Gold: the same time as the EA rival",
    );
    expect(anyBand(tt.rows)).toBe(true);
    expect(anyBand(austria.rows)).toBe(false); // +10.28 %: no band, and no legend
    expect(BAND_RULE).toContain("within 3 %");
  });
});

describe("the times to beat (optional rows)", () => {
  it("the EA rival is labelled spec-decoded and always keeps its caveat; more detail by density", () => {
    const tt = boardFixtures.timeTrial();
    expect(benchmarkKinds(tt)).toEqual(["ea_rival", "real_f1"]);
    const [rival] = benchmarkViews(tt, "plain");
    expect(rival).toMatchObject({ kind: "ea_rival", title: "EA rival", ms: 64_500, evidence: "spec-decoded", lines: [] });
    expect(rival!.caveat).toContain("not yet seen in a recording");
    const [some] = benchmarkViews(tt, "some");
    expect(some!.lines).toEqual(["McLaren · Traction control off, ABS on, Gearbox assist off", "Stored Sat 10 Oct (the game gives no date)"]);
    const [all] = benchmarkViews(tt, "all");
    expect(all!.lines).toEqual([
      "McLaren · Traction control off, ABS on, Gearbox assist off",
      "Realistic car performance · Default setup",
      "Sectors 16.000 · 28.000 · 20.500",
      "Stored Sat 10 Oct (the game gives no date)",
    ]);
  });

  it("a real pole: where and when, its caveat, and the F1DB credit CC BY 4.0 asks for", () => {
    const views = benchmarkViews(boardFixtures.austriaHaas(), "plain");
    expect(views).toHaveLength(1);
    const v = views[0]!;
    expect(v).toMatchObject({ kind: "real_f1", title: "Real F1 pole 2025 · Lando Norris", ms: 63_971, evidence: null, bandNote: null });
    expect(v.lines).toEqual(["Austrian Grand Prix, 28 Jun 2025"]);
    expect(v.caveat).toContain("F1 25 is not the real car");
    expect(v.credit).toMatchObject({
      name: "F1DB",
      url: "https://github.com/f1db/f1db",
      licence: "CC BY 4.0",
      licenceUrl: "https://creativecommons.org/licenses/by/4.0/",
    });
    expect(v.credit!.attribution).toContain("F1DB v2026.17.0");
    const all = benchmarkViews(boardFixtures.austriaHaas(), "all")[0]!;
    expect(all.lines).toEqual([
      "Austrian Grand Prix, 28 Jun 2025",
      "Pole lap: qualifying P1's deciding lap",
      "Fastest lap of that race: 1:07.924, Oscar Piastri",
      "Fastest race lap on this layout (F1DB): 1:05.619, Carlos Sainz Jr., 2020",
    ]);
  });

  it("no optional rows: none; the generic car asks for the season instead (the note says why)", () => {
    expect(benchmarkViews(boardFixtures.sakhirF2(), "all")).toEqual([]);
    const miami = boardFixtures.miamiGeneric();
    expect(benchmarkViews(miami, "all")).toEqual([]);
    expect(miami.real_f1_asks_generation).toBe(true);
    expect(miami.real_f1_note).toContain("2025 or a 2026 car");
    const chosen = boardFixtures.miamiGeneric2025();
    expect(chosen.real_f1?.generation_chosen).toBe(true);
    expect(benchmarkViews(chosen, "plain")[0]!.title).toBe("Real F1 pole 2025 · Max Verstappen");
    expect(benchmarkViews(null, "all")).toEqual([]);
  });

  it("ISO days in words", () => {
    expect(isoDay("2025-06-28")).toBe("28 Jun 2025");
    expect(isoDay("2026-01-05")).toBe("5 Jan 2026");
    expect(isoDay("June 2025")).toBe("June 2025");
  });
});

describe("record history and the chart's line", () => {
  it("newest first in the server's words, with a summary; the beginner sees the latest change", () => {
    const items = historyItems(boardFixtures.timeTrial().history);
    expect(items.map((i) => i.text)).toEqual([
      "Jo took the record from Sam: 1:05.900, 0.100 s faster",
      "Sam improved the record: 1:06.000, 0.500 s faster",
      "Sam set the first record: 1:06.500",
    ]);
    expect(items[0]).toMatchObject({ changedHands: true, sessionId: "tt2", dateText: "Sun 11 Oct" });
    expect(historySummary(items)).toBe("3 records since Sat 10 Oct, 1 taken from another driver");
    expect(historySummary(historyItems(boardFixtures.austriaHaas().history))).toBe("3 records since Sat 10 Oct");
    expect(historySummary([])).toBeNull();
    expect(historyItems(null)).toEqual([]);
    expect(HISTORY_SHOWN).toEqual({ plain: 1, some: 4, all: 8 });
  });

  it("the family line names the board's session type and weather (and the car when the chart has every car)", () => {
    const b = familyBoard([], boardFixtures.austriaHaas(), null);
    expect(familyLine(b, { anyCar: false })).toEqual({ ms: 70_549, label: "fastest in the family 1:10.549 · James (Race, dry)" });
    expect(familyLine(b, { anyCar: true })!.label).toBe("fastest in the family 1:10.549 · James (Haas, race, dry)");
    expect(familyLine(familyBoard([], boardFixtures.timeTrial(), null), { anyCar: false })!.label).toBe(
      "fastest in the family 1:05.900 · Jo (Time trial, dry)",
    );
    expect(familyLine(familyBoard([], null, null), { anyCar: false })).toBeNull();
  });
});

describe("words around the board", () => {
  it("says why there is no board, and when the board on show is in another car", () => {
    expect(emptyBoardText(scope(null, null, { synthetic: true }), 0)).toBe(
      "Synthetic sessions never count on a family board: only real driving here does.",
    );
    expect(emptyBoardText(scope(null), 0)).toBe("No family board at Austria yet: the first clean, valid lap here starts one.");
    expect(emptyBoardText(scope("f1:team:3", "Williams"), 2)).toBe(
      "No family board here yet in the Williams: a clean, valid lap starts one.",
    );
    const tt = boardFixtures.timeTrial();
    expect(otherCarNote(scope("f1:team:7", "Haas"), tt)).toBe("This board is in the McLaren, not the Haas picked above.");
    expect(otherCarNote(scope("f1:team:8", "McLaren"), tt)).toBeNull();
    expect(otherCarNote(scope(null), tt)).toBeNull();
    expect(boardShortTitle(tt.labels!)).toBe("McLaren · Time trial · Dry");
  });

  it("GT7: the track-limits note comes from the server; nothing about assists is made up", () => {
    const g = boardFixtures.gt7();
    expect(g.evidence?.track_limits_checked).toBe(false);
    expect(g.evidence?.note).toContain("does not say when a lap breaks track limits");
    expect(g.fields?.assists).toBeNull();
    expect(boardPickers(g.boards_here, g, null)).toEqual([]);
  });
});

describe("fixtures", () => {
  it("each says where it came from; household names are the fictional ones or the owner's (never the second profile's)", () => {
    const blocks = boardFixtureBlocks();
    expect(blocks.length).toBeGreaterThanOrEqual(10);
    for (const { name, block } of blocks) {
      expect(block.source, name).toMatch(/pitwall\.leaderboard\.service/);
      expect(name.startsWith(block.tier), name).toBe(true);
      if (block.tier === "recorded") expect(block.edited, name).toContain("Alex");
    }
    const names = new Set<string>();
    for (const b of [boardFixtures.austriaHaas(), boardFixtures.timeTrial(), boardFixtures.miamiGeneric()]) {
      for (const r of b.rows) names.add(r.driver_name);
      for (const n of b.no_time) names.add(n.driver_name);
    }
    expect([...names].sort()).toEqual(["Alex", "James", "Jo", "Kim", "Sam"]);
  });
});
