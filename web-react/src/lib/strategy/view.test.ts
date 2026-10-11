// Drive › Car strategy tile view model (lib/strategy/view.ts) from the strategy fixtures (src/test/fixtures/strategy,
// hand-built "edited" StrategyViews: see each file's _fixture). Every state: no data, not supported by this game,
// practice, race (window, undercut, DRS, fuel, weather, safety car), synthetic, beginner wording, phone widths.
import { describe, expect, it } from "vitest";
import { tyresTile } from "../../pages/drive/car/view";
import { frame } from "../drive/testkit";
import { bareRace, fixtureMeta, liveView, snapWith, STRATEGY_FIXTURES } from "./testkit";
import type { CallView } from "./types";
import {
  callInDate,
  measuredFuelMargin,
  shortNote,
  showStrategyTile,
  snapStrategy,
  strategyOf,
  strategyTile,
  stripAlert,
  STRATEGY_TILE_MIN_LAPS,
  type StrategyRowView,
  type StrategyTileView,
} from "./view";

const LIVE = STRATEGY_FIXTURES.filter((n) => n.includes("-live-"));

function rowsOf(v: StrategyTileView): Record<string, StrategyRowView> {
  return Object.fromEntries(v.rows.map((r) => [r.key, r]));
}

function tile(name: string, simple = false): StrategyTileView {
  return strategyTile(snapWith(liveView(name)), { dim: false, state: "live" } as never, { simple });
}

function honest(text: string, what: string): void {
  for (const bad of ["NaN", "undefined", "null", "Infinity", "[object Object]", "0.000", "—", "--"]) {
    expect(text, `${what}: ${bad}`).not.toContain(bad);
  }
}

describe("engine notes on one line", () => {
  it("the part before ':' or ';', sentence case", () => {
    expect(shortNote("not enough laps on this set yet: 3 green laps needed")).toBe("Not enough laps on this set yet");
    expect(shortNote("gap 1.8 s against new tyres worth 0.6-0.9 s a lap; rejoins in traffic")).toBe(
      "Gap 1.8 s against new tyres worth 0.6-0.9 s a lap",
    );
    expect(shortNote("no stop needed")).toBe("No stop needed");
  });
});

describe("the strategy block", () => {
  it("is read only for contract version 1 with a known mode", () => {
    expect(strategyOf(null)).toBeNull();
    expect(strategyOf({})).toBeNull();
    expect(strategyOf({ version: 2, mode: "race" })).toBeNull();
    expect(strategyOf({ version: 1, mode: "pitstop" })).toBeNull();
    const v = strategyOf({ ...bareRace(), calls: undefined });
    expect(v?.calls).toEqual([]);
  });

  it("no data: an older server (no block) or no snapshot keeps the Inputs tile", () => {
    expect(showStrategyTile(null)).toBe(false);
    expect(showStrategyTile(snapWith(undefined))).toBe(false);
    expect(snapStrategy(snapWith(null))).toBeNull();
    const v = strategyTile(null);
    expect(v.show).toBe(false);
    expect(v.rows.map((r) => r.text)).toEqual(["-", "-", "-", "-", "-", "-"]);
    expect(v.aside).toBe("-");
    expect(v.foot).toBe("No strategy calls yet");
  });

  it("not supported by this game, time trial, practice: no tile (the mode says why)", () => {
    for (const name of ["edited-live-off-unsupported-game", "edited-live-off-time-trial", "edited-live-practice"]) {
      expect(tile(name).show, name).toBe(false);
    }
    expect(liveView("edited-live-off-unsupported-game").reason).toBe("race strategy needs F1 25 timing");
  });

  it("a race shows the tile from its first tick, every value '-' until known", () => {
    const v = strategyTile(snapWith(bareRace({ total_laps: 52 })));
    expect(v.show).toBe(true);
    expect(v.rows.map((r) => r.label)).toEqual(["Ahead", "Behind", "Pit window", "Undercut", "Fuel", "Weather"]);
    expect(v.rows.every((r) => r.text === "-" && r.tags.length === 0 && r.tone === "plain")).toBe(true);
    expect(v.rows[0]!.aria).toBe("Ahead: unknown");
  });
});

describe("strategy tile in a race", () => {
  it("Austria, lap 67 of 71: no stop needed, fuel from this race's own use, dry", () => {
    const v = tile("edited-live-race-austria-l67");
    expect(v.show).toBe(true);
    expect(v.aside).toBe("L67/71 · P4");
    expect(v.synthetic).toBe(false);
    const r = rowsOf(v);
    expect(r.ahead!.text).toBe("+2.0 s · closing 0.3/lap");
    expect(r.ahead!.tags.map((t) => t.text)).toEqual(["1 STOP"]);
    expect(r.ahead!.aria).toBe("Car ahead: 2.0 seconds, closing 0.3 seconds a lap, 1 stop");
    expect(r.behind!.text).toBe("3.0 s · dropping back 0.1/lap");
    expect(r.behind!.tone).toBe("plain");
    expect(r.window!.text).toBe("No stop needed");
    // no stop needed: the undercut slot gives the laps to go instead of "No stop needed" twice (review L1)
    expect([r.undercut!.label, r.undercut!.text]).toEqual(["Laps to go", "5"]);
    expect(r.fuel!.text).toBe("+2.3 laps");
    expect(r.weather!.text).toBe("Dry for 15 min");
    // the newest call is from lap 65: two laps on it no longer holds (review M2)
    expect(v.foot).toBe("No new strategy calls");
    expect(v.footLevel).toBeNull();
  });

  it("window open: the band word for the car behind, the game's window with its tier, undercut and fuel in words", () => {
    const r = rowsOf(tile("edited-live-race-window-open"));
    expect(r.ahead!.text).toBe("+1.8 s · closing 0.3/lap");
    expect(r.behind!.text).toBe("0.8 s · closing 0.2/lap");
    expect(r.behind!.tone).toBe("warn");
    expect(r.behind!.tags).toEqual([{ text: "DRS", tone: "warn" }]);
    expect(r.behind!.aria).toContain("in DRS range");
    expect(r.window!.text).toBe("L18-22 · best L20 (game)");
    expect(r.window!.tags).toEqual([{ text: "OPEN", tone: "info" }]);
    expect(r.window!.aria).toBe("Pit window: laps 18 to 22, best around lap 20, game estimate, open");
    expect(r.undercut!.text).toBe("ahead marginal · behind threat");
    expect(r.undercut!.tone).toBe("warn");
    expect(r.undercut!.tags.map((t) => t.text)).toEqual(["THREAT"]);
    expect(r.fuel!.text).toBe("+0.2 laps");
    expect(r.fuel!.tags).toEqual([{ text: "TIGHT", tone: "warn" }]);
    expect(r.fuel!.tone).toBe("warn");
  });

  it("the last laps of the window are a warning in words", () => {
    const view = liveView("edited-live-race-window-open");
    view.lap = 21;
    const r = rowsOf(strategyTile(snapWith(view)));
    expect(r.window!.tags[0]).toEqual({ text: "LAST LAPS", tone: "warn" });
    expect(r.window!.tone).toBe("warn");
  });

  it("virtual safety car: the weather row becomes the stop's cost, an estimate, with VSC in words", () => {
    const v = tile("edited-live-race-vsc");
    const r = rowsOf(v);
    expect(r.weather!.label).toBe("Safety car");
    expect(r.weather!.text).toBe("Stop 11 s · green 19 s (estimate)");
    expect(r.weather!.tags).toEqual([{ text: "VSC", tone: "warn" }]);
    expect(r.weather!.aria).toBe("Virtual safety car: a stop costs about 11 seconds now, 19 under green, Pitwall estimate");
    // the car ahead is in the pit lane: its gap is the last settled value, dimmed and said so
    expect(r.ahead!.dim).toBe(true);
    expect(r.ahead!.tags[0]).toEqual({ text: "IN PIT", tone: "info" });
    expect(r.ahead!.aria).toContain("last settled value");
    expect(r.undercut!.text).toBe("The car ahead is in the pit lane"); // both unknown: the engine's reason
    // a position change with no settled value for the new car (real Austria race, L65): unknown, not "last settled"
    const changed = liveView("edited-live-race-vsc");
    changed.gaps!.ahead = { ...changed.gaps!.ahead!, gap_s: null, settled: false, in_pit: false };
    const a = rowsOf(strategyTile(snapWith(changed))).ahead!;
    expect(a.aria).toContain("gap unknown");
    expect(a.aria).not.toContain("last settled value");
    expect(v.footLevel).toBe("alert");
    expect(v.foot).toMatch(/^L7 · Virtual safety car\. Pitting this lap is an option/);
  });

  it("a full safety car without a measured stop says so, never a number", () => {
    const view = liveView("edited-live-race-vsc");
    view.safety_car = { status: "full", since_lap: 7, box: { pit_loss_s: null, green_pit_loss_s: null, stop_needed: true, this_lap: false, tier: "heuristic" } };
    const r = rowsOf(strategyTile(snapWith(view)));
    expect(r.weather!.text).toBe("Stop cost unknown");
    expect(r.weather!.tags[0]!.text).toBe("SC");
    view.safety_car.box = null;
    expect(rowsOf(strategyTile(snapWith(view))).weather!.text).toBe("Safety car out");
  });

  it("fuel short: the lift-and-coast target, never 'brake later'; rain coming is amber with a word", () => {
    const v = tile("edited-live-race-fuel-short-rain");
    const r = rowsOf(v);
    expect(r.fuel!.text).toBe("−0.3 laps · lift & coast 2.1 s/lap");
    expect(r.fuel!.tags).toEqual([{ text: "SHORT", tone: "warn" }]);
    expect(r.fuel!.aria).toBe("Fuel: −0.3 laps at the flag, short, lift and coast about 2.1 seconds a lap, brake at your normal point");
    expect(r.weather!.text).toBe("Light rain in 5 min · 3 laps");
    expect(r.weather!.tags).toEqual([{ text: "RAIN", tone: "warn" }]);
    expect(r.window!.text).toBe("No more stops needed");
    for (const row of v.rows) expect(`${row.text} ${row.aria}`).not.toMatch(/brake\w* later/i);
  });

  it("lift and coast that cannot close the gap says so instead of a number", () => {
    const view = liveView("edited-live-race-fuel-short-rain");
    view.fuel!.lift_coast = { save_kg_per_lap: 0.9, seconds_per_lap: 8.4, feasible: false, corners: [] };
    expect(rowsOf(strategyTile(snapWith(view))).fuel!.text).toBe("−0.3 laps · beyond lift & coast");
  });

  it("the game's tyre crossover is the game's estimate, said so", () => {
    const r = rowsOf(tile("edited-live-race-crossover"));
    expect(r.weather!.text).toBe("Inters 0.8 s/lap faster (game)");
    expect(r.weather!.tone).toBe("warn");
    expect(r.window!.text).toBe("Not enough laps on this set yet");
    expect(r.fuel!.text).toBe("-");
    // a trend needs three laps: the gap alone
    expect(r.ahead!.text).toBe("+1.1 s");
  });

  it("Austria excerpt (3 laps): not enough laps yet, the game's fuel figure with its tier, the forecast's 10 min", () => {
    const v = tile("edited-live-race-austria-excerpt");
    const r = rowsOf(v);
    expect(v.show).toBe(false); // a 3-lap sprint keeps the Inputs tile (review L2); the rows are still built
    expect(v.aside).toBe("L2/3 · P11");
    expect(r.window!.text).toBe("Not enough laps on this set yet");
    expect(r.window!.aria).toBe("Pit window: not enough laps on this set yet: 3 green laps needed");
    expect(r.fuel!.text).toBe("+1.9 laps (game)");
    expect(r.weather!.text).toBe("Dry for 10 min");
    expect(r.ahead!.text).toBe("+0.9 s");
    expect(r.ahead!.tags).toEqual([{ text: "CLOSE", tone: "info" }]);
    expect(r.ahead!.tone).toBe("plain"); // within a second of the car AHEAD is no warning
    expect(v.foot).toBe("No strategy calls yet");
    expect(v.footLevel).toBeNull();
  });

  it("leading and last: words instead of a missing car", () => {
    const view = bareRace({ position: 1, cars: 20, gaps: { ahead: null, behind: null, leader_s: null, note: null } });
    expect(rowsOf(strategyTile(snapWith(view))).ahead!.text).toBe("You are leading");
    const last = bareRace({ position: 20, cars: 20, gaps: { ahead: null, behind: null, leader_s: null, note: null } });
    expect(rowsOf(strategyTile(snapWith(last))).behind!.text).toBe("No car behind");
  });

  it("a weather change to dry is good news in words, not amber", () => {
    const view = liveView("edited-live-race-crossover");
    view.weather!.crossover = null;
    view.weather!.next_change = { in_min: 5, weather: "overcast", rain_pct: 20, in_laps: 3 };
    const r = rowsOf(strategyTile(snapWith(view)));
    expect(r.weather!.text).toBe("Overcast in 5 min · 3 laps");
    expect(r.weather!.tags).toEqual([{ text: "DRYING", tone: "info" }]);
    expect(r.weather!.tone).toBe("plain");
  });
});

describe("recorded: the engine's own views over the committed PS5 excerpts (scripts/strategy_check.py)", () => {
  it("Austria excerpt, the flag of a 3-lap race: last place, no stop needed, this race's fuel, a short forecast", () => {
    const v = tile("recorded-live-race-austria-excerpt");
    const r = rowsOf(v);
    expect(v.show).toBe(false); // 3 laps: the Inputs tile keeps the slot
    expect(v.aside).toBe("L3/3 · P20");
    expect(r.ahead!.text).toBe("+7.0 s");
    expect(r.behind!.text).toBe("No car behind");
    expect(r.window!.text).toBe("No stop needed");
    expect([r.undercut!.label, r.undercut!.text]).toEqual(["Laps to go", "Chequered flag"]);
    expect(r.fuel!.text).toBe("+3.2 laps");
    expect(r.weather!.text).toBe("Dry for 10 min");
    expect(v.foot).toBe("L2 · Car behind is within a second.");
  });

  it("Monza excerpt: gaps without a trend yet, the game's fuel figure until two green laps", () => {
    const r = rowsOf(tile("recorded-live-race-monza-excerpt"));
    expect(r.ahead!.text).toBe("+1.6 s");
    expect(r.behind!.text).toBe("1.7 s");
    expect(r.fuel!.text).toBe("+2.6 laps (game)");
    expect(r.weather!.text).toBe("Dry for 10 min");
  });
});

describe("synthetic, stale and simple wording", () => {
  it("a synthetic session carries the SYNTHETIC chip", () => {
    const v = tile("edited-live-race-synthetic");
    expect(v.synthetic).toBe(true);
    expect(rowsOf(v).weather!.text).toBe("No stop needed");
    expect(rowsOf(v).weather!.label).toBe("Safety car");
  });

  it("stale or offline: the last known values, the footer says so", () => {
    const view = liveView("edited-live-race-austria-l67");
    view.lap = 66;
    const v = strategyTile(snapWith(view), { dim: true, state: "stale" } as never);
    expect(v.foot).toBe("Last known · L65 · Car behind is within a second.");
    expect(rowsOf(v).ahead!.text).toBe("+2.0 s · closing 0.3/lap");
  });

  it("beginner wording: plain labels and sentences, the same numbers", () => {
    const v = tile("edited-live-race-window-open", true);
    const r = rowsOf(v);
    expect(v.rows.map((x) => x.label)).toEqual(["Car ahead", "Car behind", "Pit stop", "Laps to go", "Fuel", "Weather"]);
    expect(r.ahead!.text).toBe("+1.8 s · you gain 0.3 s a lap");
    expect(r.behind!.text).toBe("0.8 s · it gains 0.2 s a lap");
    expect(r.behind!.tags).toEqual([{ text: "CLOSE", tone: "warn" }]); // no "DRS" for simple wording (review H3)
    expect(r.window!.text).toBe("Stop lap 18-22 · best 20 (game)");
    expect(r.undercut!.text).toBe("11"); // laps to go: "Pit first" was not clear to a child
    expect(r.fuel!.text).toBe("Only 0.2 laps spare");
    for (const x of v.rows) expect(`${x.text} ${x.tags.map((t) => t.text).join(" ")}`).not.toMatch(/undercut|marginal|threat|DRS|lift & coast/i);
    const short = rowsOf(tile("edited-live-race-fuel-short-rain", true));
    expect(short.fuel!.text).toBe("0.3 laps short · lift early");
  });
});

describe("every fixture, both wordings", () => {
  it("is honest: no NaN, null, undefined or invented zeros; unknown is '-'", () => {
    for (const name of LIVE) {
      for (const simple of [false, true]) {
        const v = tile(name, simple);
        for (const r of v.rows) {
          honest(r.text, `${name} ${r.key}`);
          honest(r.aria, `${name} ${r.key} aria`);
          expect(r.text.length, `${name} ${r.key}`).toBeGreaterThan(0);
        }
        honest(v.aside, name);
        honest(v.foot.replace(/^.*? · /, ""), name);
      }
    }
  });

  it("phone and 11-inch iPad: every value fits one line of the tile (about 36 condensed characters)", () => {
    // The tile is ~323 px wide inside on an 11" iPad landscape and ~334 px on a 390 px phone; the value line uses
    // 18 px condensed numerals (about 8 px a character): 36 characters fit without an ellipsis.
    for (const name of LIVE) {
      for (const simple of [false, true]) {
        for (const r of tile(name, simple).rows) expect(r.text.length, `${name} ${r.key}: ${r.text}`).toBeLessThanOrEqual(36);
      }
    }
  });

  it("never recommends braking later", () => {
    for (const name of LIVE) {
      const v = tile(name);
      for (const r of v.rows) expect(`${r.text} ${r.aria}`).not.toMatch(/brake\w* later/i);
    }
  });
});

describe("Tyres & energy line (shared Car view)", () => {
  it("prefers this race's measured fuel margin, keeps the game's figure until it is known", () => {
    const measured = snapWith(liveView("edited-live-race-austria-l67"), {
      frame: frame({ fuel_kg: 10.4, fuel_remaining_laps_game: 2.1, ers_store_j: 2.8e6 }),
    });
    expect(measuredFuelMargin(measured)).toBe("+2.3 laps");
    expect(tyresTile(measured).energy).toBe("Fuel 10.4 kg · +2.3 laps · ERS 2.8 MJ");
    const early = snapWith(liveView("edited-live-race-austria-excerpt"), {
      frame: frame({ fuel_kg: 4.6, fuel_remaining_laps_game: 1.9, ers_store_j: 4e6 }),
    });
    expect(measuredFuelMargin(early)).toBeNull();
    expect(tyresTile(early).energy).toBe("Fuel 4.6 kg · +1.9 laps (game) · ERS 4.0 MJ");
    const none = snapWith(undefined, { frame: frame({ fuel_kg: 4.6, fuel_remaining_laps_game: 1.9, ers_store_j: 4e6 }) });
    expect(tyresTile(none).energy).toBe("Fuel 4.6 kg · +1.9 laps (game) · ERS 4.0 MJ");
  });
});

describe("fixtures", () => {
  it("every strategy fixture says where it comes from", () => {
    for (const name of STRATEGY_FIXTURES) {
      const f = fixtureMeta(name);
      expect(f?.tier, name).toMatch(/^(recorded|synthetic|edited)$/);
      expect(f?.notes?.length, name).toBeGreaterThan(10);
      expect(name.startsWith(`${f!.tier}-`), name).toBe(true);
    }
  });
});

describe("radio: strategy calls in the log", () => {
  it("the radio's STRATEGY chip (kind 'strategy', the info blue) matches the Review call chips", async () => {
    const { kindChip } = await import("../../components/radio/radio-view");
    expect(kindChip("strategy")).toEqual({ label: "STRATEGY", tone: "ref" });
    const { callChip } = await import("./words");
    expect(callChip("normal")).toEqual(kindChip("strategy"));
    expect(callChip("alert")).toEqual(kindChip("alert"));
    expect(callChip("detailed")).toEqual(kindChip("info"));
  });
});

describe("review fixes", () => {
  const call = (over: Partial<CallView> = {}): CallView => ({
    id: "c1",
    topic: "pit_window",
    level: "alert",
    text: "Last laps of the tyre window: box this lap or next.",
    text_simple: "Pit this lap or next: your tyres are nearly worn out.",
    audience: "all",
    ttl_s: 60,
    lap: 20,
    t_unix: 1000,
    ...over,
  });

  it("a sprint keeps the Inputs tile; a race of STRATEGY_TILE_MIN_LAPS laps or more gets strategy", () => {
    expect(showStrategyTile(snapWith(bareRace({ total_laps: 5 })))).toBe(false);
    expect(showStrategyTile(snapWith(bareRace({ total_laps: null })))).toBe(false);
    expect(showStrategyTile(snapWith(bareRace({ total_laps: STRATEGY_TILE_MIN_LAPS })))).toBe(true);
  });

  it("the footer: this driver's words, never an experienced-only call for simple wording, never out of date", () => {
    const threat = call({ id: "t", topic: "undercut_threat", level: "normal", text: "Car behind is pitting. Box next lap to cover the undercut.", text_simple: null, audience: "experienced", lap: 21, t_unix: 1010 });
    const v = bareRace({ total_laps: 30, lap: 21, calls: [threat, call()] });
    expect(strategyTile(snapWith(v), null, { nowS: 1020 }).foot).toBe("L21 · Car behind is pitting. Box next lap to cover the undercut.");
    // simple wording: the threat never reached this driver; the window call in plain words
    expect(strategyTile(snapWith(v), null, { simple: true, nowS: 1020 }).foot).toBe("L20 · Pit this lap or next: your tyres are nearly worn out.");
    // a call past its TTL (at least 30 s) or two laps old leaves the footer: no amber left behind
    const old = strategyTile(snapWith(v), null, { simple: true, nowS: 1061 });
    expect([old.foot, old.footLevel]).toEqual(["No new strategy calls", null]);
    expect(callInDate(call({ ttl_s: 8 }), 20, 1029)).toBe(true); // a short TTL still shows for 30 s
    expect(callInDate(call(), 22, null)).toBe(false);
    expect(callInDate(call(), 21, null)).toBe(true);
  });

  it("Coach's radio strip with the radio off: the newest strategy alert still in date", () => {
    const v = bareRace({ total_laps: 30, lap: 20, calls: [call({ level: "normal", id: "n", text: "Fuel is tight." }), call()] });
    expect(stripAlert(snapWith(v), { nowS: 1010 })).toBe("L20 · Last laps of the tyre window: box this lap or next.");
    expect(stripAlert(snapWith(v), { simple: true, nowS: 1010 })).toBe("L20 · Pit this lap or next: your tyres are nearly worn out.");
    expect(stripAlert(snapWith(v), { nowS: 2000 })).toBeNull();
    expect(stripAlert(snapWith(bareRace({ calls: [call({ level: "normal" })] })))).toBeNull();
    expect(stripAlert(null)).toBeNull();
  });

  it("rain the forecast puts after the flag: no tag, no amber", () => {
    const view = liveView("edited-live-race-fuel-short-rain");
    view.weather!.next_change = { in_min: 10, weather: "light_rain", rain_pct: 72, in_laps: 7 };
    const w = rowsOf(strategyTile(snapWith(view))).weather!;
    expect([w.text, w.tone, w.tags]).toEqual(["Light rain after the flag", "plain", []]);
  });

  it("amber only for what to watch now", () => {
    const view = liveView("edited-live-race-window-open");
    // within a second, not in DRS range and not closing: a word, no amber (a pack race was amber for most laps)
    view.gaps!.behind = { ...view.gaps!.behind!, drs_range: false, within_1s: true, trend_s_per_lap: 0.1 };
    let r = rowsOf(strategyTile(snapWith(view)));
    expect([r.behind!.tone, r.behind!.tags]).toEqual(["plain", [{ text: "CLOSE", tone: "neutral" }]]);
    view.gaps!.behind = { ...view.gaps!.behind!, trend_s_per_lap: -0.2 };
    expect(rowsOf(strategyTile(snapWith(view))).behind!.tone).toBe("warn"); // closing within a second
    // the undercut threat is amber only while the window is open
    view.lap = 15;
    r = rowsOf(strategyTile(snapWith(view)));
    expect([r.undercut!.text, r.undercut!.tone]).toEqual(["ahead marginal · behind threat", "plain"]);
  });

  it("one-lap and overdue windows, fuel on the limit, the game's figure in plain words", () => {
    const view = liveView("edited-live-race-window-open");
    view.pit!.window = { ...view.pit!.window!, open_lap: 22, close_lap: 22, ideal_lap: 22 };
    view.lap = 22;
    expect(rowsOf(strategyTile(snapWith(view))).window!.text).toBe("L22 (game)");
    expect(rowsOf(strategyTile(snapWith(view), null, { simple: true })).window!.text).toBe("Stop on lap 22 (game)");
    view.pit!.window = { ...view.pit!.window!, overdue: true };
    const over = rowsOf(strategyTile(snapWith(view))).window!;
    expect([over.text, over.tone, over.tags]).toEqual(["L22 · at the wear limit (game)", "warn", [{ text: "LIMIT", tone: "warn" }]]);
    view.fuel = { ...view.fuel!, margin_laps: 0.02, status: "tight" };
    expect(rowsOf(strategyTile(snapWith(view))).fuel!.text).toBe("On the limit");
    expect(rowsOf(strategyTile(snapWith(view), null, { simple: true })).fuel!.text).toBe("On the limit");
    const early = liveView("edited-live-race-austria-excerpt");
    expect(rowsOf(strategyTile(snapWith(early), null, { simple: true })).fuel!.text).toBe("1.9 laps spare (game)");
  });

  it("the safety car in plain words", () => {
    const r = rowsOf(strategyTile(snapWith(liveView("edited-live-race-vsc")), null, { simple: true }));
    expect(r.weather!.text).toBe("Cheap stop now: 11 s (usually 19 s)");
  });

  it("no '≈' or '~' anywhere: 'about' in words, '·' between numbers", () => {
    for (const name of LIVE) {
      for (const simple of [false, true]) {
        for (const r of tile(name, simple).rows) expect(`${r.text} ${r.aria}`, `${name} ${r.key}`).not.toMatch(/[≈~]/);
      }
    }
  });
});
