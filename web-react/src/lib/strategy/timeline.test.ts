// Review › Strategy view models (lib/strategy/timeline.ts) from the timeline fixtures (hand-built "edited"
// StrategyTimelines: see each file's _fixture): states, KPIs, the chart model, tables, calls and the tier note.
import { describe, expect, it } from "vitest";
import { timeline } from "./testkit";
import {
  callRows,
  excludedWords,
  isRaceSession,
  stintRows,
  stopRows,
  strategyGame,
  tierNote,
  timelineChart,
  timelineKpis,
  timelineState,
} from "./timeline";

const RACE = { session_type: "race", game: "f1_25" };

function honest(text: string, what: string): void {
  for (const bad of ["NaN", "undefined", "null", "Infinity", "[object Object]", "—"]) {
    expect(text, `${what}: ${bad}`).not.toContain(bad);
  }
}

describe("what the tab can show", () => {
  it("races only, F1 only", () => {
    expect(isRaceSession({ session_type: "race" })).toBe(true);
    expect(isRaceSession({ session_type: "Race" })).toBe(true);
    expect(isRaceSession({ session_type: "practice" })).toBe(false);
    expect(isRaceSession(null)).toBe(false);
    expect(strategyGame("f1_25")).toBe(true);
    expect(strategyGame("gt7")).toBe(false);
    expect(strategyGame(null)).toBe(false);
  });

  it("a practice session: 'Strategy is shown for races only.'", () => {
    const s = timelineState({ session_type: "practice", game: "f1_25" }, undefined);
    expect(s.kind).toBe("not_race");
    expect(s.title).toBe("Strategy is shown for races only.");
    expect(timelineState(RACE, timeline("edited-timeline-not-race")).kind).toBe("not_race");
  });

  it("not supported by this game: GT7 races have no all-car timing", () => {
    const s = timelineState({ session_type: "race", game: "gt7" }, undefined);
    expect(s.kind).toBe("unsupported_game");
    expect(s.text).toBe("Race strategy needs the timing of every car, which only F1 25 sends.");
    expect(timelineState(RACE, { available: false, reason: "race strategy needs F1 25 timing", laps: [] }).kind).toBe(
      "unsupported_game",
    );
  });

  it("an old race: recorded before strategy tracking", () => {
    const s = timelineState(RACE, timeline("edited-timeline-before-tracking"));
    expect(s.kind).toBe("before_tracking");
    expect(s.title).toBe("This race was recorded before Pitwall tracked strategy.");
  });

  it("no laps yet, another reason in words, and the normal case", () => {
    expect(timelineState(RACE, { available: true, reason: null, laps: [] }).kind).toBe("no_laps");
    // the live race before its first lap record (strategy/timeline.py REASON_NO_LAPS_YET)
    expect(timelineState(RACE, { available: false, reason: "no strategy laps yet", laps: [] }).kind).toBe("no_laps");
    const split = timelineState(RACE, { available: false, reason: "no complete lap in this session", laps: [] });
    expect(split.kind).toBe("no_laps");
    expect(split.title).toBe("No complete lap in this session.");
    const other = timelineState(RACE, { available: false, reason: "session still loading", laps: [] });
    expect(other).toMatchObject({ kind: "unavailable", text: "Session still loading." });
    expect(timelineState(RACE, timeline("edited-timeline-austria")).kind).toBe("ok");
    expect(timelineState(RACE, undefined).kind).toBe("ok"); // loading: the tab shows its skeleton
  });
});

describe("KPIs", () => {
  it("Austria (a resumed race, no grid position): from the first recorded lap, no stop, one measured field stop", () => {
    const k = timelineKpis(timeline("edited-timeline-austria"));
    expect(k.map((x) => [x.title, x.value, x.sub])).toEqual([
      ["Positions", "P9 → P1", "Gained 8 places from lap 62"],
      ["Stops", "0", "No pit stop"],
      ["Pit loss", "18.9 s", "1 measured"],
      ["Fuel at the flag", "+2.3 laps", "Left at the flag"],
    ]);
  });

  it("synthetic demo: grid to flag, the stop with its compounds, the range of measured stops", () => {
    const k = timelineKpis(timeline("edited-timeline-synthetic"));
    expect(k[0]).toMatchObject({ value: "P4 → P3", sub: "Gained 1 place" });
    expect(k[1]).toMatchObject({ value: "1", sub: "L8 · Medium → Hard" });
    expect(k[2]).toMatchObject({ value: "19.1 s", sub: "2 measured · 19.0-19.1 s", term: "pit_loss" });
    expect(k[3]).toMatchObject({ value: "0.0 laps", sub: "Left at the flag" });
  });

  it("unknown stays unknown; a race in progress says where its numbers are from", () => {
    const t = timeline("edited-timeline-austria");
    t.pit_loss = null;
    t.finish_position = null;
    t.laps = t.laps.filter((l) => l.lap <= 66).map((l) => ({ ...l, fuel_margin_laps: null }));
    const k = timelineKpis(t);
    expect(k[0]).toMatchObject({ value: "P9 → P4", sub: "Gained 5 places from lap 62 to lap 66" });
    // the server sends the last record's position as finish_position: still "to lap 66" until the flag
    expect(timelineKpis({ ...t, finish_position: 4 })[0]).toMatchObject({ sub: "Gained 5 places from lap 62 to lap 66" });
    expect(k[2]).toMatchObject({ value: "-", sub: "No pit stop measured in this race" });
    expect(k[3]).toMatchObject({ value: "+2.2 laps", sub: "The game's figure at lap 66" });
    t.laps = t.laps.map((l) => ({ ...l, game_fuel_margin_laps: null, position: null }));
    const none = timelineKpis(t);
    expect(none[0]).toMatchObject({ value: "-", sub: "Start position not recorded" });
    expect(none[3]).toMatchObject({ value: "-", sub: "Needs two green laps" });
  });

  it("no change in position, said plainly", () => {
    const t = timeline("edited-timeline-austria");
    t.laps = t.laps.filter((l) => l.lap === 66);
    t.finish_position = null;
    expect(timelineKpis(t)[0]).toMatchObject({ value: "P4 → P4", sub: "No change on lap 66" });
    const g = timeline("edited-timeline-synthetic");
    g.finish_position = 4;
    expect(timelineKpis(g)[0]).toMatchObject({ value: "P4 → P4", sub: "Same place as the start" });
  });

  it("beginner wording: plain titles", () => {
    const k = timelineKpis(timeline("edited-timeline-austria"), { simple: true });
    expect(k[0]!.title).toBe("Start → finish");
    expect(k[1]!.sub).toBe("You did not stop");
  });
});

describe("recorded: the Austria excerpt timeline (the engine's records over the committed capture)", () => {
  it("KPIs, chart and stint from real decoding; no stop, no measured pit loss", () => {
    const t = timeline("recorded-timeline-austria-excerpt");
    expect(timelineState(RACE, t).kind).toBe("ok");
    const k = timelineKpis(t);
    expect(k.map((x) => [x.value, x.sub])).toEqual([
      ["P14 → P20", "Lost 6 places from lap 1"],
      ["0", "No pit stop"],
      ["-", "No pit stop measured in this race"],
      ["+3.2 laps", "Left at the flag"],
    ]);
    const m = timelineChart(t);
    expect(m.rows[0]).toEqual({ lap: 1, position: 14, behind: 0.1 }); // no settled gap ahead on lap 1: no value
    expect(m.stints.map((s) => s.label)).toEqual(["Soft · 3 laps"]);
    expect(stintRows(t.stints)[0]).toMatchObject({ wearEnd: "16%", rate: "5.0%/lap", median: "1:23.352" });
    expect(callRows(t.calls).map((c) => `${c.lap} ${c.chip.label} ${c.text}`)).toEqual(["L2 STRATEGY Car behind is within a second."]);
  });
});

describe("the race timeline chart", () => {
  it("Austria: laps 62-71 on a half-lap padded axis, positions reversed on 1..20, gaps in seconds, no bands", () => {
    const m = timelineChart(timeline("edited-timeline-austria"));
    expect(m.empty).toBe(false);
    expect(m.xDomain).toEqual([61.5, 71.5]);
    expect(m.xTicks).toEqual([62, 63, 64, 65, 66, 67, 68, 69, 70, 71]);
    expect(m.positionDomain).toEqual([1, 20]);
    expect(m.positionTicks).toEqual([1, 5, 10, 15, 20]);
    expect(m.rows[2]).toEqual({ lap: 64, position: 6, ahead: 1.7, behind: 3.9 });
    expect(m.rows[7]).toEqual({ lap: 69, position: 1, behind: 1 }); // the leader has no car ahead: no value, not 0
    expect(m.gapDomain).toEqual([0, 4]);
    expect(m.gapTicks).toEqual([0, 1, 2, 3, 4]);
    expect(m.weatherLine).toBe(
      "Weather: Clear from lap 62 (rain 7%); light cloud from lap 63 (rain 7%); overcast from lap 67 (rain 9%); light cloud from lap 71 (rain 6%).",
    );
    expect(m.stops).toEqual([]);
    expect(m.bands).toEqual([]);
    expect(m.stints).toHaveLength(1);
    expect(m.stints[0]).toMatchObject({ fromPct: 0, widthPct: 100, label: "Medium · 10 laps", colour: "var(--pw-flag-yellow)" });
    expect(m.weather.map((w) => w.label)).toEqual(["Clear · rain 7%", "Light cloud · rain 7%", "Overcast · rain 9%", "Light cloud · rain 6%"]);
    expect(m.weather[1]).toMatchObject({ fromPct: 10, widthPct: 40 });
    expect(m.summary).toBe("Laps 62 to 71. Position P9 on lap 62, P1 on lap 71. No pit stop.");
  });

  it("synthetic demo: the player's stop as a dashed mark with its compounds, the VSC band in words", () => {
    const m = timelineChart(timeline("edited-timeline-synthetic"));
    expect(m.stops).toEqual([{ lap: 8, label: "M → H", words: "Pit stop on lap 8, Medium → Hard" }]);
    expect(m.bands).toEqual([{ start: 7, end: 8, short: "VSC", words: "Virtual safety car on laps 7-8" }]);
    expect(m.stints.map((s) => s.label)).toEqual(["Medium · 8 laps", "Hard · 4 laps"]);
    expect(m.stints.map((s) => s.short)).toEqual(["M · 8", "H · 4"]); // phones
    expect(m.weather.map((w) => w.short)).toEqual(["Clear", "Light rain"]);
    expect(m.gapTicks).toEqual([0, 2, 4, 6, 8, 10]);
    expect(m.stints[0]!.widthPct + m.stints[1]!.widthPct).toBeCloseTo(100, 6);
    expect(m.positionTicks).toEqual([1, 2, 3, 4, 5, 6]);
    expect(m.summary).toContain("1 pit stop: lap 8.");
    expect(m.summary).toContain("Virtual safety car on laps 7-8.");
  });

  it("an open safety car period runs to the last lap; no laps is an empty chart", () => {
    const t = timeline("edited-timeline-synthetic");
    t.safety_car_periods = [{ status: "full", start_lap: 11, end_lap: null }];
    expect(timelineChart(t).bands).toEqual([{ start: 11, end: 12, short: "SC", words: "Safety car on laps 11-12" }]);
    t.laps = [];
    expect(timelineChart(t).empty).toBe(true);
  });

  it("long races thin the lap ticks", () => {
    const t = timeline("edited-timeline-synthetic");
    t.laps = Array.from({ length: 52 }, (_, i) => ({ ...t.laps[0]!, lap: i + 1 }));
    expect(timelineChart(t).xTicks).toEqual([1, 10, 20, 30, 40, 50, 52]);
  });
});

describe("tables and calls", () => {
  it("stints with wear and median lap", () => {
    expect(stintRows(timeline("edited-timeline-synthetic").stints)).toEqual([
      { id: "stint0", compound: "Medium", colour: "var(--pw-flag-yellow)", laps: "L1-8", count: 8, wearEnd: "31%", rate: "3.4%/lap", median: "1:31.700" },
      { id: "stint1", compound: "Hard", colour: "var(--foreground)", laps: "L9-12", count: 4, wearEnd: "9%", rate: "2.1%/lap", median: "1:31.200" },
    ]);
  });

  it("pit stops: you or a car number (never a name), exclusions and neutralisation in words", () => {
    const t = timeline("edited-timeline-synthetic");
    expect(stopRows(t.stops)[0]).toEqual({
      id: "3:8",
      car: "You",
      entry: "L8",
      exit: "L8",
      lane: "21.0 s",
      stationary: "2.6 s",
      loss: "11.4 s",
      compounds: "Medium → Hard",
      note: "Under the virtual safety car",
      used: true,
    });
    const field = stopRows(t.field_stops);
    expect(field.map((r) => r.car)).toEqual(["Car 2", "Car 5", "Car 4"]);
    expect(field[2]).toMatchObject({ exit: "-", loss: "-", note: "Not counted: out lap not completed", used: false });
    const austria = stopRows(timeline("edited-timeline-austria").field_stops);
    expect(austria[0]).toMatchObject({ car: "Car 7", loss: "-", note: "Not counted: long stop (repair?)", compounds: "-" });
    expect(austria[1]).toMatchObject({ car: "Car 14", entry: "L65", exit: "L66", lane: "20.0 s", stationary: "3.4 s", loss: "18.9 s", note: null });
  });

  it("exclusion reasons in words (strategy/pitloss.py EXCLUDED_*); anything new as sent", () => {
    expect(excludedWords("long stop (repair?)")).toBe("Long stop (repair?)");
    expect(excludedWords("penalty served")).toBe("Served a penalty");
    expect(excludedWords("safety car on only part of the stop")).toBe("Safety car for only part of the stop");
    expect(excludedWords("no pre-stop green lap observed")).toBe("No green lap seen before the stop");
    expect(excludedWords("implausible loss")).toBe("Pit loss outside 8-45 s");
    expect(excludedWords("laps not all observed")).toBe("Not every lap of the stop was seen");
    expect(excludedWords("flashback during the stop")).toBe("Flashback during the stop");
    expect(excludedWords("out-lap not completed")).toBe("Out lap not completed");
    expect(excludedWords("serve_penalty")).toBe("Served a penalty");
    expect(excludedWords("no pre-stop green lap")).toBe("No green lap seen before the stop");
    expect(excludedWords("loss outside 8-45 s")).toBe("Pit loss outside 8-45 s");
    expect(excludedWords("E..X laps not all observed")).toBe("Not every lap of the stop was seen");
    expect(excludedWords("rewind during the visit")).toBe("Flashback during the stop");
    expect(excludedWords("brand_new_reason")).toBe("Brand new reason");
    expect(excludedWords(null)).toBeNull();
  });

  it("calls in lap order, the radio's chip per level, the text verbatim", () => {
    const rows = callRows(timeline("edited-timeline-synthetic").calls);
    expect(rows.map((r) => r.lap)).toEqual(["L5", "L6", "L7", "L9", "L10"]);
    expect(rows.map((r) => r.chip.label)).toEqual(["STRATEGY", "ALERT", "ALERT", "ALERT", "STRATEGY"]);
    expect(rows[1]!.text).toBe("Fuel critical: 0.4 laps short. Lift and coast about 2 s a lap, brake at your normal point.");
    for (const r of rows) expect(r.text).not.toMatch(/brake\w* later/i);
  });

  it("the tier note names the tiers, and synthetic sessions say so first", () => {
    expect(tierNote({ synthetic: false })).toMatch(/^Measured values come from this race's own timing\. \(game\)/);
    expect(tierNote({ synthetic: true })).toMatch(/^Synthetic session: generated data, not from a game\./);
  });

  it("every timeline fixture renders honest words", () => {
    for (const name of ["edited-timeline-austria", "edited-timeline-synthetic", "recorded-timeline-austria-excerpt"]) {
      const t = timeline(name);
      const m = timelineChart(t);
      const all = [
        ...timelineKpis(t).flatMap((k) => [k.value, k.sub]),
        ...m.stints.map((s) => s.label),
        ...m.weather.map((s) => s.label),
        m.summary,
        ...stintRows(t.stints).flatMap((r) => Object.values(r).map(String)),
        ...stopRows([...t.stops, ...t.field_stops]).flatMap((r) => [r.car, r.entry, r.exit, r.lane, r.stationary, r.loss, r.compounds, r.note ?? ""]),
      ];
      for (const s of all) honest(s, name);
    }
  });
});
