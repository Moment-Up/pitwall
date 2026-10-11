import { describe, expect, it } from "vitest";
import { asLive, fixture, frame, lap, snap } from "./testkit";
import { MINUS } from "./text";
import {
  bestsOf,
  bestsOfLaps,
  inTimingScope,
  lapClock,
  lapStatus,
  lapTimesView,
  lastLapStatus,
  legendOf,
  notCleanWords,
  sectorCells,
  standing,
  statusAsSet,
  tagOf,
  timingLegend,
} from "./timing";

describe("timing colours (4.6)", () => {
  const before = { session: 30000, driver: 29500, household: 29200 };

  it("colours a time as set: REC > PB > SB > slower, only with D2 for REC and PB", () => {
    expect(statusAsSet(29100, before, true, 2)).toBe("rec");
    expect(statusAsSet(29300, before, true, 2)).toBe("pb");
    expect(statusAsSet(29900, before, true, 2)).toBe("sb");
    expect(statusAsSet(30000, before, true, 2)).toBe("slower");
    // before D2 purple and PB never appear
    expect(statusAsSet(29100, before, true, 1)).toBe("sb");
    // the session's first clean time is its best so far: SB (as the Best panel, Review and Progress say it)
    expect(statusAsSet(29100, { session: null, driver: null, household: null }, true, 1)).toBe("sb");
  });

  it("greys a lap that is not clean and leaves unknown neutral", () => {
    expect(statusAsSet(29000, before, false, 2)).toBe("invalid");
    expect(statusAsSet(null, before, true, 2)).toBe("neutral");
    expect(statusAsSet(0, before, true, 2)).toBe("neutral");
  });

  it("colours tables by current standing: only the times that are still the best", () => {
    expect(standing([91512, 90986, 92611, null], [true, true, true, true], { driver: null, household: null }, 1)).toEqual([
      "slower",
      "sb",
      "slower",
      "neutral",
    ]);
    // a lone clean lap is the session's best: SB, as on the Best panel and the Review tile
    expect(standing([90986], [true], { driver: null, household: null }, 1)).toEqual(["sb"]);
    expect(standing([90100, 90986, 89000], [true, true, false], { driver: 90500, household: 90100 }, 2)).toEqual([
      "rec",
      "slower",
      "invalid",
    ]);
    expect(standing([90400, 90986], [true, true], { driver: 90400, household: 90100 }, 2)).toEqual(["pb", "slower"]);
  });

  it("a time that only ties a best set earlier does not take it (D2's setter lap ids decide)", () => {
    // lap 15 equals the family record and the driver's best, both set by lap 6 of an earlier session
    const best = { driver: 88663, household: 88663, driverLapId: 6, householdLapId: 6 };
    expect(standing([88663, 90100], [true, true], best, 2, true, [15, 14])).toEqual(["sb", "slower"]);
    // the lap that set them keeps them
    expect(standing([88663], [true], best, 2, true, [6])).toEqual(["rec"]);
    // without ids a tie counts (by time), as before
    expect(standing([88663], [true], { driver: 88663, household: 88663 }, 2)).toEqual(["rec"]);
  });

  it("colours no table times outside the timing scope (synthetic, replay): only INV stays", () => {
    expect(standing([91512, 90986, 89000], [true, true, false], { driver: 90500, household: 90100 }, 2, false)).toEqual([
      "neutral",
      "neutral",
      "invalid",
    ]);
  });

  it("tags and legends", () => {
    expect(["rec", "pb", "sb", "slower", "neutral", "invalid", "running"].map((s) => tagOf(s as never))).toEqual([
      "REC",
      "PB",
      "SB",
      null,
      null,
      "INV",
      null,
    ]);
    expect(timingLegend(1)).toBe("SB your best today");
    expect(timingLegend(2)).toBe("REC family record · PB your best ever · SB your best today");
  });

  it("names in the legend only the tags that can appear, or why there are none", () => {
    const replay = fixture("recorded-d246-austria-session-ended"); // D2 block, records off (a replay)
    expect(legendOf(replay, bestsOf(replay))).toBe("A replay: times are not coloured");
    const synth = fixture("synthetic-demo-session-ended");
    expect(legendOf(synth, bestsOf(synth))).toBe("Synthetic data: times are not coloured");
    const live = asLive(fixture("recorded-d246-austria-session-ended"));
    expect(legendOf(live, bestsOf(live))).toBe("SB your best today"); // D2 sent no driver or household best
    const d2 = asLive(fixture("edited-d1-d6"));
    expect(legendOf(d2, bestsOf(d2))).toBe("REC family record · PB your best ever · SB your best today");
    expect(legendOf(null, null)).toBe("SB your best today");
  });

  it("formats the lap clock", () => {
    expect(lapClock(69549, true)).toBe("1:09.5");
    expect(lapClock(91512, false)).toBe("1:31.512");
    expect(lapClock(null, true)).toBe("-");
  });

  it("says why a lap is not clean", () => {
    expect(notCleanWords(lap(3, 90000, [], { clean: false, flags: ["pit_out", "flashback"] }))).toBe("out lap, flashback");
    expect(notCleanWords(lap(3, 90000, [], { clean: false, valid: false, flags: [] }))).toBe("invalid");
    expect(notCleanWords(lap(3, 90000))).toBeNull();
  });
});

describe("bests", () => {
  it("derives session bests from clean laps before D2 (tier 1)", () => {
    const s = asLive(fixture("recorded-suzuka-on-track-brake-ahead"));
    expect(bestsOf(s)).toEqual({
      tier: 1,
      coloured: true,
      session: { lap_ms: 97037, sectors_ms: [35546, 41928, 18689] },
      driver: null,
      household: null,
    });
  });

  it("keeps synthetic and replayed sessions out of the timing scope (4.6)", () => {
    expect(inTimingScope(fixture("recorded-suzuka-on-track-brake-ahead"))).toBe(false); // replay:
    expect(inTimingScope(fixture("synthetic-demo-on-track-brake-ahead"))).toBe(false);
    expect(inTimingScope(snap())).toBe(true); // udp:20777
    expect(bestsOf(fixture("recorded-suzuka-on-track-brake-ahead")).coloured).toBe(false);
  });

  it("uses D2's records only in the timing scope; tier 2 only when a driver or household best is there", () => {
    const s = fixture("edited-d1-d6");
    const replayed = bestsOf(s); // connection.source is replay:
    expect(replayed).toMatchObject({ tier: 1, coloured: false, driver: null, household: null });
    expect(replayed.session.lap_ms).toBe(97037); // D2's session best still names its laps
    asLive(s);
    expect(bestsOf(s)).toMatchObject({ tier: 2, coloured: true, driver: { lap_ms: 96500 }, household: { lap_ms: 96100 } });
    expect(bestsOf({ ...s, bests: { ...s.bests!, scope: { ...s.bests!.scope!, records: false } } })).toMatchObject({
      tier: 1,
      driver: null,
      household: null,
    });
    expect(bestsOf({ ...s, bests: { ...s.bests!, driver: null, household: null } }).tier).toBe(1);
    s.connection = { ...s.connection, synthetic: true };
    expect(bestsOf(s)).toMatchObject({ tier: 1, coloured: false, household: null });
  });

  it("a replayed session with a D2 block is tier 1: no REC / PB legend for times that can never earn them", () => {
    const s = fixture("recorded-d246-austria-session-ended");
    expect(s.bests).toBeTruthy();
    expect(bestsOf(s)).toMatchObject({ tier: 1, coloured: false });
  });

  it("ignores missing sectors (GT7 sends none)", () => {
    expect(bestsOfLaps([lap(1, 23482, []), lap(2, 23055, [])])).toEqual({ lap_ms: 23055, sectors_ms: [null, null, null] });
  });
});

describe("sector cells", () => {
  it("before D1 shows the last lap, dimmed and captioned, coloured as set against older laps", () => {
    const v = sectorCells(asLive(fixture("recorded-suzuka-on-track-brake-ahead")));
    expect(v.caption).toBe("Last lap · L4");
    expect(v.source).toBe("last_lap");
    expect(v.dim).toBe(true);
    expect(v.cells.map((c) => [c.label, c.text, c.status, c.tag, c.sub])).toEqual([
      ["S1", "35.546", "sb", "SB", `${MINUS}0.179 on today's best`],
      ["S2", "42.802", "slower", null, "+0.874 vs today's best"],
      ["S3", "18.689", "sb", "SB", `${MINUS}0.849 on today's best`],
    ]);
  });

  it("colours no sector of a replayed or synthetic session; the times and INV stay", () => {
    const v = sectorCells(fixture("recorded-suzuka-on-track-brake-ahead"));
    expect(v.cells.map((c) => [c.text, c.status, c.tag, c.sub])).toEqual([
      ["35.546", "neutral", null, null],
      ["42.802", "neutral", null, null],
      ["18.689", "neutral", null, null],
    ]);
    const d1 = sectorCells(fixture("edited-d1-d6"));
    expect(d1.cells[0]).toMatchObject({ text: "35.400", status: "neutral", tag: null, sub: null });
    const synth = sectorCells(fixture("synthetic-demo-on-track-brake-ahead"));
    expect(synth.cells.every((c) => c.status === "neutral" || c.status === "invalid")).toBe(true);
  });

  it("greys the sectors of a lap that was not clean", () => {
    const v = sectorCells(fixture("recorded-monza-invalid-lap"));
    expect(v.cells.every((c) => c.status === "invalid" && c.tag === "INV")).toBe(true);
  });

  it("with D1 shows the lap in progress: completed as set, the running sector, later sectors '-'", () => {
    const s = asLive(fixture("edited-d1-d6")); // current S1 35.400, car in S2 (frame.sector 1)
    s.bests = { ...s.bests!, driver: null, household: null };
    const v = sectorCells(s);
    expect(v.source).toBe("current");
    expect(v.caption).toBeNull();
    expect(v.cells[0]).toMatchObject({ text: "35.400", status: "sb", tag: "SB", sub: `${MINUS}0.146 on today's best` });
    expect(v.cells[1]).toMatchObject({ status: "running", text: "4.4", tag: null });
    expect(v.cells[1].progress).toBeGreaterThan(0.1);
    expect(v.cells[1].progress).toBeLessThan(0.15);
    expect(v.cells[2]).toMatchObject({ status: "future", text: "-" });
  });

  it("with D1 and D2 records colours a sector purple or green", () => {
    const s = fixture("edited-d1-d6");
    s.connection = { ...s.connection, source: "udp:20777" };
    s.frame = { ...s.frame!, current_lap_sector_ms: [35050, null] };
    expect(sectorCells(s).cells[0]).toMatchObject({ status: "rec", tag: "REC", sub: "family record" });
    s.frame = { ...s.frame!, current_lap_sector_ms: [35200, null] };
    expect(sectorCells(s).cells[0]).toMatchObject({ status: "pb", tag: "PB", sub: "your best ever" });
  });

  it("stops colouring on an invalid lap and blanks the running sector when stale", () => {
    const s = fixture("edited-d1-d6");
    s.frame = { ...s.frame!, lap_invalid: true };
    expect(sectorCells(s).cells[0]).toMatchObject({ text: "35.400", status: "neutral", tag: null, sub: null });
    const stale = sectorCells(fixture("edited-d1-d6"), "stale");
    expect(stale.cells[0].text).toBe("35.400");
    expect(stale.cells[1]).toMatchObject({ text: "-", status: "future", sub: "no signal" });
  });

  it("is '-' offline and without telemetry, and offers the driver's best sectors before the first lap", () => {
    expect(sectorCells(fixture("recorded-suzuka-on-track-brake-ahead"), "offline").cells.every((c) => c.text === "-")).toBe(true);
    expect(sectorCells(null, "no_data").source).toBe("none");
    const g = fixture("edited-d1-d6");
    g.connection = { ...g.connection, source: "udp:20777" };
    g.laps = [];
    const v = sectorCells(g, "garage");
    expect(v.cells.map((c) => [c.text, c.sub])).toEqual([
      ["-", "your best here 35.300"],
      ["-", "your best here 41.700"],
      ["-", "your best here 18.600"],
    ]);
  });

  it("keeps the last lap in the garage between runs and after the session", () => {
    expect(sectorCells(fixture("edited-garage-between-runs"), "garage").source).toBe("last_lap");
    expect(sectorCells(fixture("recorded-austria-session-ended"), "ended").caption).toBe("Last lap · L71");
  });
});

describe("lap times panel", () => {
  it("runs the clock in tenths and shows Last with its delta to the reference and Best with its tag", () => {
    const v = lapTimesView(asLive(fixture("recorded-suzuka-on-track-brake-ahead")), "on_track");
    expect(v.lap).toEqual({ text: "0:39.8", running: true, status: null, tag: null, invalid: false, muted: false });
    expect(v.last).toEqual({
      text: "1:37.037",
      status: "sb",
      tag: "SB",
      deltaText: `${MINUS}0.15`,
      deltaTone: "ahead",
      reason: null,
      lapNumber: 4,
    });
    expect(v.best).toEqual({ text: "1:37.037", status: "sb", tag: "SB", sub: null, lapNumber: 4 });
  });

  it("colours no lap of a replayed session: Last and Best neutral, untagged", () => {
    const v = lapTimesView(fixture("recorded-suzuka-on-track-brake-ahead"), "on_track");
    expect(v.last).toMatchObject({ text: "1:37.037", status: "neutral", tag: null, deltaText: `${MINUS}0.15` });
    expect(v.best).toMatchObject({ text: "1:37.037", status: "neutral", tag: null, lapNumber: 4 });
    expect(lapStatus(fixture("recorded-suzuka-on-track-brake-ahead"), 1)).toBe("neutral");
  });

  it("shows the completed lap for 6 s after the line, then the clock", () => {
    const s = snap({
      laps: [lap(6, 91512, [29341, 37022, 25149]), lap(5, 90986, [29318, 36904, 24764])],
      frame: frame({ lap_number: 7, current_lap_time_ms: 5200 }),
    });
    expect(lapTimesView(s, "on_track").lap).toMatchObject({ text: "1:31.512", running: false, status: "slower" });
    s.frame = frame({ lap_number: 7, current_lap_time_ms: 6100 });
    expect(lapTimesView(s, "on_track").lap).toMatchObject({ text: "0:06.1", running: true });
  });

  it("flags an invalid lap and explains a lap that is not clean", () => {
    const v = lapTimesView(fixture("recorded-monza-invalid-lap"), "on_track");
    expect(v.lap.invalid).toBe(true);
    expect(v.last).toMatchObject({ status: "invalid", tag: "INV", reason: "standing start" });
    expect(v.best).toMatchObject({ text: "-", sub: null });
  });

  it("is muted in the pit lane, blank in the garage before the first lap, and '-' offline", () => {
    expect(lapTimesView(fixture("edited-pit-lane"), "pit_lane").lap.muted).toBe(true);
    const g = lapTimesView(fixture("recorded-suzuka-grid-before-start"), "garage");
    expect(g.lap.text).toBe("-");
    expect(g.best).toMatchObject({ text: "-", sub: "first lap sets it" });
    const off = lapTimesView(fixture("recorded-suzuka-on-track-brake-ahead"), "offline");
    expect([off.lap.text, off.last.text, off.best.text]).toEqual(["-", "-", "-"]);
  });

  it("keeps Last and Best facts when stale but blanks the lap clock", () => {
    const v = lapTimesView(fixture("recorded-austria-stale"), "stale");
    expect(v.lap.text).toBe("-");
    expect(v.last.text).toBe("1:11.208");
    expect(v.best.text).toBe("1:10.549");
  });

  it("falls back to the game's last lap time before the lap is analysed", () => {
    const v = lapTimesView(fixture("recorded-austria-blue-elsewhere"), "on_track");
    expect(v.last).toMatchObject({ text: "1:08.249", status: "neutral", tag: null });
  });

  it("tags the session best PB or REC with D2 records, by the setter's lap id", () => {
    const s = fixture("edited-d1-d6");
    s.connection = { ...s.connection, source: "udp:20777" };
    const last = s.laps[0]!; // lap 4, 1:37.037, the session best
    expect(lapTimesView(s, "on_track").best).toMatchObject({ status: "sb", tag: "SB" });
    s.bests = { ...s.bests!, driver: { ...s.bests!.driver!, lap_ms: 97037, lap_id: last.lap_id } };
    expect(lapTimesView(s, "on_track").best).toMatchObject({ status: "pb", tag: "PB", lapNumber: 4 });
    expect(lastLapStatus(s)).toBe("pb");
    s.bests = { ...s.bests!, household: { ...s.bests!.household!, lap_ms: 97037, lap_id: last.lap_id } };
    expect(lapTimesView(s, "on_track").best).toMatchObject({ status: "rec", tag: "REC" });
    expect(lastLapStatus(s)).toBe("rec");
  });

  it("judges the newest lap by time when D2 sends no setter ids", () => {
    const s = fixture("edited-d1-d6");
    s.connection = { ...s.connection, source: "udp:20777" };
    const { lap_id: _a, sector_lap_ids: _b, ...driverBest } = s.bests!.driver!;
    s.bests = { ...s.bests!, driver: { ...driverBest, lap_ms: 97037 } };
    expect(lastLapStatus(s)).toBe("pb");
    expect(lapStatus(s, 1)).toBe("sb"); // lap 3: the session's first clean lap was its best when it was set
  });
});
