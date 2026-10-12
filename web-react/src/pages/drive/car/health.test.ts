// Drive › Car with the health lane's blocks (lane spec 3.13 D2 / D3): the "Tyres & energy" tile against the driver's
// own warm laps (car_health), and the Strategy tile's "Box now ≈ P11" line and attack / defend tags (pit.rejoin v2,
// racecraft). View models first, then the rendered wall (static markup in plain node, like strategy-tile.test.ts):
// colour is never the only signal, unknown is "-", plain words for a simple-wording profile, the iPad and phone
// layouts keep their rows.
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { healthView, racecraftView, rejoinStrategy, withHealth } from "../../../lib/carhealth/testkit";
import type { CarHealthView } from "../../../lib/carhealth/types";
import { driveModel, type DriveModel } from "../../../lib/drive/model";
import { fixture, frame, newestT, snap } from "../../../lib/drive/testkit";
import type { SnapshotNext } from "../../../lib/drive/types";
import { catalogue, entry } from "../../../lib/game-testkit";
import type { HistoryPoint } from "../../../lib/live";
import { strategyTile, type StrategyRowView, type StrategyTileView } from "../../../lib/strategy/view";
import { stubBrowser } from "../../../test/fakes";
import type { CarScreenProps } from "./CarScreen";
import { tyresTile } from "./view";

const CAT = catalogue();
const F1 = entry("f1_25:ps5", CAT);
const GT7 = entry("gt7:ps5", CAT);
const AC = entry("ac:ps5", CAT);
const FM = entry("forza_motorsport:pc", CAT);

/** An F1 frame after a pit stop on new softs: carcass ~47 °C, surface ~60 °C. */
function coldFrame() {
  return frame({
    tyre_surface_temp_c: [61, 60, 63, 62],
    tyre_inner_temp_c: [46.4, 45.2, 48, 49],
    tyre_pressure_psi: [19.5, 19.5, 18.2, 18.2],
    tyre_wear_pct: [2, 2, 1, 1],
    brake_temp_c: [982, 979, 961, 960],
    engine_temp_c: 124,
    tyre_compound: "soft",
    tyre_age_laps: 0,
    fuel_kg: 18.4,
    ers_store_j: 2.8e6,
  });
}

function withBlock(name: string, f = coldFrame()): SnapshotNext {
  return withHealth(snap({ frame: f }), { car_health: healthView(name) });
}

// ------------------------------------------------------------------------------------------- tyres & energy

describe("Tyres & energy against the driver's own warm laps", () => {
  it("carcass model, cold after a stop: inside temperatures, cold in colour and word, the Cold tyres chip", () => {
    const v = tyresTile(withBlock("edited-live-f1-carcass-cold-after-stop"), F1);
    expect(v.wheels.map((w) => w.temp)).toEqual(["46°", "45°", "48°", "49°"]); // the carcass, not the surface
    for (const w of v.wheels) expect(w).toMatchObject({ band: "cold", word: "cold", colour: "var(--pw-tyre-cold)" });
    expect(v.wheels[0]!.aria).toBe("FL: inside 46 degrees, cold for this session, wear 2 percent, pressure 19.5 psi");
    expect(v.chip).toBe("Cold tyres");
    expect(v.chipTone).toBe("warn");
    expect(v.basis).toBe("Inside temperatures · colours compare with your warm laps");
    expect(v.caption).toBeNull();
    expect(v.energy).toBe("Fuel 18.4 kg · ERS 2.8 MJ"); // F1: the strategy's kilos, unchanged
    expect(v.temps).toBe("Brakes 982° · Engine 124°");
    expect(v.slip).toBe("Last lap: 3 lock-ups · 4 wheelspins");
  });

  it("surface-only model: the surface is the number (the game's constant inner 90 °C never shows); hot says so", () => {
    const f = { ...coldFrame(), tyre_surface_temp_c: [66, 77, 62, 61], tyre_inner_temp_c: [90, 90, 90, 90], tyre_compound: "medium", tyre_age_laps: 13 };
    const v = tyresTile(withBlock("edited-live-f1-surface-warm-abs-on", f), F1);
    expect(v.wheels.map((w) => w.temp)).toEqual(["66°", "77°", "62°", "61°"]);
    expect(v.wheels.map((w) => w.word)).toEqual([null, "hot", null, null]);
    expect(v.wheels[1]!.colour).toBe("var(--pw-tyre-hot)");
    expect(v.wheels[0]!.colour).toBe("var(--pw-tyre-optimal)");
    expect(v.wheels[1]!.aria).toMatch(/^FR: surface 77 degrees, hot for this session/);
    expect(v.chip).toBe("Medium · 13 laps");
    expect(v.chipTone).toBe("neutral");
    expect(v.basis).toBe("Surface temperatures · colours compare with your warm laps");
    expect(v.slip).toBe("Last lap: ABS on · 1 wheelspin");
    expect(JSON.stringify(v)).not.toContain("90°");
  });

  it("the first lap: no baselines yet, so no colour, no word; unknown is '-'", () => {
    const f = { ...coldFrame(), engine_temp_c: null, brake_temp_c: null };
    const v = tyresTile(withBlock("edited-live-f1-first-lap", f), F1);
    for (const w of v.wheels) expect(w).toMatchObject({ band: "unknown", word: null, colour: "var(--pw-tyre-optimal)" });
    expect(v.wheels[0]!.aria).toBe("FL: inside 46 degrees, wear 2 percent, pressure 19.5 psi");
    expect(v.chip).toBe("Soft · 0 laps");
    expect(v.temps).toBe("Brakes - · Engine -");
    expect(v.slip).toBe("Last lap: -");
  });

  it("no temperature on a wheel: '-', faint, never 0", () => {
    const f = { ...coldFrame(), tyre_inner_temp_c: [null, 45, 48, 49] as never };
    const v = tyresTile(withBlock("edited-live-f1-carcass-cold-after-stop", f), F1);
    expect(v.wheels[0]).toMatchObject({ temp: "-", colour: "var(--pw-faint)", word: "cold" });
    expect(v.wheels[0]!.aria).toMatch(/^FL: inside unknown, cold for this session/);
  });

  it("Forza: fuel in laps from the tank level replaces 'not in Pitwall yet'; no brakes, engine or slip lines", () => {
    const f = frame({ tyre_surface_temp_c: [80, 81, 62, 83], tyre_wear_pct: [3, 3, 4, 4] });
    const s = withHealth(snap({ frame: f }), { car_health: healthView("edited-live-forza-fuel-ok") });
    const v = tyresTile(s, FM);
    expect(v.energy).toBe("Fuel ≈ 7 laps (tank level) · ERS: not sent by Forza Motorsport");
    expect(v.energyTone).toBe("plain");
    expect(v.wheels[2]).toMatchObject({ band: "cold", word: "cold", temp: "62°" });
    expect(v.caption).toBe("Tyre pressures: not sent by Forza Motorsport");
    expect(v.basis).toBe("Surface temperatures · colours compare with your warm laps");
    expect(v.temps).toBeNull();
    expect(v.slip).toBeNull();
    const crit = tyresTile(withHealth(snap({ frame: f }), { car_health: healthView("edited-live-forza-fuel-critical") }), FM);
    expect(crit.energy).toBe("Fuel almost out: ≈ 1.1 laps (tank level) · ERS: not sent by Forza Motorsport");
    expect(crit.energyTone).toBe("warn");
    expect(crit.energyWarn).toBe("Fuel almost out: ≈ 1.1 laps (tank level)"); // ERS stays plain
    expect(tyresTile(s, FM).energyWarn).toBeNull();
    for (const [status, words] of [
      ["not_used", "Fuel use off"],
      ["unknown", "Fuel: measuring…"],
    ] as const) {
      const ch = healthView("edited-live-forza-fuel-ok");
      ch.fuel = { ...ch.fuel!, status, laps_of_fuel: null };
      expect(tyresTile(withHealth(snap({ frame: f }), { car_health: ch }), FM).energy, status).toBe(
        `${words} · ERS: not sent by Forza Motorsport`,
      );
    }
  });

  it("GT7: fuel stays the catalogue's sentence, no numbers; without a catalogue still no numbers", () => {
    const s = withHealth(fixture("recorded-live-api-gt7-stale"), { car_health: healthView("edited-live-gt7-fuel-unverified") });
    const v = tyresTile(s, GT7);
    expect(v.energy).toBe("Fuel, ERS: not in Pitwall yet");
    expect(v.wheels.map((w) => w.temp)).toEqual(["65°", "71°", "66°", "72°"]);
    expect(v.wheels.every((w) => w.word === null)).toBe(true); // in range for this session
    expect(v.temps).toBeNull();
    expect(v.slip).toBeNull();
    const bare = tyresTile(s);
    expect(bare.energy).toBe("Fuel: not estimated · ERS -");
    expect(bare.energy.replace("ERS -", "")).not.toMatch(/\d/);
  });

  it("Assetto Corsa: one line instead of the grid, from the catalogue or else the block's own reason", () => {
    const s = withHealth(snap({ frame: frame() }), { car_health: healthView("edited-live-ac-not-sent") });
    expect(tyresTile(s, AC).empty).toBe("Assetto Corsa doesn't send tyre data");
    expect(tyresTile(s).empty).toBe("Assetto Corsa doesn't send tyre data");
    expect(tyresTile(s).basis).toBeNull();
  });

  it("before the first frame the block's 'no car data yet' never replaces the grid (the dashes say it)", () => {
    const ch = healthView("edited-live-f1-first-lap");
    ch.tyres = { available: false, reason: "no car data yet" };
    const v = tyresTile(withHealth(snap({ frame: null }), { car_health: ch }), F1);
    expect(v.empty).toBeNull();
    expect(v.wheels.every((w) => w.temp === "-")).toBe(true);
  });

  it("a block from another session or a newer contract is ignored: the tile stays as without it", () => {
    const s = withBlock("edited-live-f1-carcass-cold-after-stop");
    const plain = tyresTile({ ...s, car_health: undefined }, F1);
    expect(tyresTile({ ...s, car_health: { ...s.car_health!, session_id: "other" } }, F1)).toEqual(plain);
    expect(tyresTile({ ...s, car_health: { ...s.car_health!, version: 2 } as unknown as CarHealthView }, F1)).toEqual(plain);
    expect(plain.wheels.map((w) => w.temp)).toEqual(["61°", "60°", "63°", "62°"]); // surface without the block
    expect(plain.chip).toBe("Soft · 0 laps");
  });
});

// ------------------------------------------------------------------------------------------- strategy tile

function rowsOf(v: StrategyTileView): Record<string, StrategyRowView> {
  return Object.fromEntries(v.rows.map((r) => [r.key, r]));
}

const LIVE = { dim: false, state: "on_track" } as never;

describe("Strategy tile: where a stop now would rejoin, and attack / defend", () => {
  function race(rc: string | null = "edited-racecraft-attack-clear"): SnapshotNext {
    return withHealth(snap(), { strategy: rejoinStrategy(), racecraft: rc ? racecraftView(rc) : null });
  }

  it("the pit window row says 'Box now ≈ P11 (P10–12)' beside its label, and why in its aria", () => {
    const w = rowsOf(strategyTile(race(), LIVE)).window!;
    expect(w.label).toBe("Pit window");
    expect(w.sub).toBe("Box now ≈ P11 (P10–12)");
    expect(w.text).toBe("L18-22 · best L20 (game)");
    expect(w.aria).toContain("; If you box now you'd come out around P11, between P10 and P12");
    expect(rowsOf(strategyTile(race(), LIVE, { simple: true })).window!.sub).toBe("If you stop now: about 11th");
  });

  it("the line only when it is worth a glance: in the pit lane, under a safety car, or near the pit window", () => {
    const early = race(); // lap 20 of a window opening on lap 18: shown; lap 1 of the same race: not (P20 noise)
    early.strategy!.lap = 1;
    expect(rowsOf(strategyTile(early, LIVE)).window!.sub).toBeNull();
    early.strategy!.lap = 15; // three laps before the window opens
    expect(rowsOf(strategyTile(early, LIVE)).window!.sub).toBe("Box now ≈ P11 (P10–12)");
    const sc = race();
    sc.strategy!.lap = 1;
    sc.strategy!.safety_car = { status: "full", since_lap: 1, box: null };
    expect(rowsOf(strategyTile(sc, LIVE)).window!.sub).toBe("Box now ≈ P11 (P10–12)"); // a cheap stop
    const lane = race();
    lane.strategy!.lap = 1;
    lane.strategy!.pit!.rejoin = { ...lane.strategy!.pit!.rejoin!, frozen: true };
    expect(rowsOf(strategyTile(lane, LIVE)).window!.sub).toBe("Rejoin ≈ P11 (P10–12)"); // held through the lane
  });

  it("a beginner never gets the game's own figure alone", () => {
    const g = race();
    g.strategy!.pit!.rejoin = { ...g.strategy!.pit!.rejoin!, basis: "game_only", position: null, reason: "no_loss" };
    expect(rowsOf(strategyTile(g, LIVE)).window!.sub).toBe("Box now: game says P10");
    expect(rowsOf(strategyTile(g, LIVE, { simple: true })).window!.sub).toBeNull();
  });

  it("no line when no stop is needed, or from an older server's rejoin", () => {
    const s = race();
    s.strategy!.pit!.stop_needed = false;
    expect(rowsOf(strategyTile(s, LIVE)).window!.sub).toBeNull();
    const old = race();
    const { position, gap_ahead_s, gap_behind_s, traffic, game_position } = old.strategy!.pit!.rejoin!;
    old.strategy!.pit!.rejoin = { position, gap_ahead_s, gap_behind_s, traffic, game_position };
    expect(rowsOf(strategyTile(old, LIVE)).window!.sub).toBeNull();
  });

  it("attack: BEST T2 on the car ahead (same car), plain words for simple wording; the car behind has none", () => {
    const rows = rowsOf(strategyTile(race(), LIVE));
    expect(rows.ahead!.tags.map((t) => t.text)).toContain("BEST T2");
    expect(rows.ahead!.tags.find((t) => t.text === "BEST T2")?.tone).toBe("neutral");
    expect(rows.ahead!.aria).toContain("best chance on the car ahead at Turn 3");
    expect(rows.behind!.tags.map((t) => t.text)).not.toContainEqual(expect.stringMatching(/^WATCH/));
    const simple = rowsOf(strategyTile(race(), LIVE, { simple: true }));
    expect(simple.ahead!.sub).toBe("you catch it at T2");
    expect(simple.ahead!.tags.map((t) => t.text)).not.toContain("BEST T2");
  });

  it("defend: WATCH T7 on the car behind, beside DRS; the spread side gets nothing", () => {
    const rows = rowsOf(strategyTile(race("edited-racecraft-defend-clear"), LIVE));
    expect(rows.behind!.tags.map((t) => t.text)).toEqual(["DRS", "WATCH T7"]);
    expect(rows.ahead!.tags.map((t) => t.text).some((t) => t.startsWith("BEST"))).toBe(false);
    expect(rowsOf(strategyTile(race("edited-racecraft-defend-clear"), LIVE, { simple: true })).behind!.sub).toBe(
      "it catches you at T7",
    );
  });

  it("another car ahead now, racecraft off, or no block: no tags", () => {
    const s = race();
    s.strategy!.gaps!.ahead!.car_index = 3;
    expect(rowsOf(strategyTile(s, LIVE)).ahead!.tags.map((t) => t.text)).not.toContain("BEST T2");
    for (const rc of ["edited-racecraft-off", "edited-racecraft-no-corners", null]) {
      const rows = rowsOf(strategyTile(race(rc), LIVE));
      expect(rows.ahead!.tags.some((t) => /^(BEST|WATCH)/.test(t.text)), String(rc)).toBe(false);
      expect(rows.ahead!.sub).toBeNull();
    }
  });
});

// --------------------------------------------------------------------------------------------- rendered wall

let CarScreen: ComponentType<CarScreenProps>;

beforeAll(async () => {
  const { win } = stubBrowser("http://127.0.0.1:8770/next/#/drive/car");
  Object.assign(win, {
    navigator: globalThis.navigator,
    removeEventListener: () => {},
    screen: { orientation: {} },
    visualViewport: {},
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }),
  });
  CarScreen = (await import("./CarScreen")).CarScreen;
  vi.unstubAllGlobals();
});

const HISTORY: HistoryPoint[] = Array.from({ length: 40 }, (_, i) => ({ t: i * 0.05, speed: 200 + i, throttle: 1, brake: 0 }));

function model(s: SnapshotNext | null): DriveModel {
  return driveModel({ snap: s, connected: true, nowS: newestT(s) + 1, driver: null });
}

function render(s: SnapshotNext, simple = false): string {
  return renderToStaticMarkup(createElement(CarScreen, { model: model(s), snap: s, history: HISTORY, nowS: newestT(s) + 1, simple, entry: F1 }));
}

function visible(markup: string): string {
  return markup
    .replace(/<span class="sr-only">[^<]*<\/span>/g, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ")
    .trim();
}

describe("Drive › Car rendered with the health lane's blocks", () => {
  function raceSnap(): SnapshotNext {
    const s = fixture("recorded-austria-on-track-behind");
    s.frame = { ...s.frame!, ...coldFrame() };
    return withHealth(s, {
      car_health: healthView("edited-live-f1-carcass-cold-after-stop"),
      strategy: rejoinStrategy(),
      racecraft: racecraftView("edited-racecraft-attack-clear"),
    });
  }

  it("the tyres tile: the amber Cold tyres chip, words beside colours, both captions, three foot lines", () => {
    const html = render(raceSnap());
    const text = visible(html);
    expect(html).toMatch(/chip--warning[^>]*>[\s\S]*?Cold tyres/);
    expect(text).toContain("Tyres & energy Cold tyres FL cold 46° 2% · 19.5 psi FR cold 45°");
    expect(text).toContain("Inside temperatures · colours compare with your warm laps");
    expect(html).toContain('class="pww-tyres__foot"');
    expect(text).toContain("Fuel 18.4 kg");
    expect(text).toContain("Brakes 982° · Engine 124°");
    expect(text).toContain("Last lap: 3 lock-ups · 4 wheelspins");
    expect(html).toContain('aria-label="FL: inside 46 degrees, cold for this session, wear 2 percent, pressure 19.5 psi"');
  });

  it("the strategy tile: 'Box now ≈ P11 (P10–12)' beside the pit window label and BEST T3 on Ahead; six rows kept", () => {
    const html = render(raceSnap());
    expect(html.match(/class="pws-row"/g)).toHaveLength(6);
    const text = visible(html);
    expect(text).toContain("Pit window · Box now ≈ P11 (P10–12)");
    // the learned corner T2 is Turn 3 on Austria's track sheet: the official short label
    expect(text).toMatch(/Ahead BEST T3 \+1\.8 s/);
    expect(html).toContain('class="pws-row__sub"');
  });

  it("simple wording: plain phrases beside the labels, no caps tags", () => {
    const text = visible(render(raceSnap(), true));
    expect(text).toContain("Pit stop · If you stop now: about 11th");
    expect(text).toContain("Car ahead · you catch it at T3");
    expect(text).not.toContain("BEST T3");
  });

  it("an older server (no blocks): the wall exactly as before, no health lines", () => {
    const s = fixture("recorded-austria-on-track-behind");
    const text = visible(render(s));
    expect(text).not.toContain("Cold tyres");
    expect(text).not.toContain("colours compare");
    expect(text).not.toContain("Box now");
    expect(text).not.toContain("Last lap:");
  });
});
