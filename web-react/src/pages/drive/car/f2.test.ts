// Drive with an F2 car (F2 support, contract v1), Car and Coach rendered to static markup in plain node: the tyre chip
// says the compound in words ("Super soft · 1 lap"), an F2 car shows no ERS at all (never "ERS -"), a borrowed track
// model says whose laps its corners come from, the strategy tile says the game sends no stop rules beside "No stop
// needed", and the status slot carries the F2 chip next to the track. Snapshots: recorded Drive moments and the
// strategy fixtures, with the contract's additions edited in.
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { F1_CLASS, F2_CLASS, f2JeddahSession } from "../../../lib/carclass-testkit";
import { driveModel, type DriveModel } from "../../../lib/drive/model";
import { fixture, frame, newestT, snap } from "../../../lib/drive/testkit";
import type { SnapshotNext } from "../../../lib/drive/types";
import { catalogue, entry } from "../../../lib/game-testkit";
import type { HistoryPoint } from "../../../lib/live";
import { liveView } from "../../../lib/strategy/testkit";
import type { PitRules, StrategyView } from "../../../lib/strategy/types";
import { STOP_RULES_LINE, strategyTile, type StrategyRowView } from "../../../lib/strategy/view";
import { stubBrowser } from "../../../test/fakes";
import type { CoachScreenProps } from "../coach/CoachScreen";
import type { CarScreenProps } from "./CarScreen";
import { trackView } from "../track/view";
import { mapTile, tyresTile } from "./view";

let CarScreen: ComponentType<CarScreenProps>;
let CoachScreen: ComponentType<CoachScreenProps>;

beforeAll(async () => {
  const { win } = stubBrowser("http://127.0.0.1:8770/#/drive/car");
  Object.assign(win, {
    navigator: globalThis.navigator,
    removeEventListener: () => {},
    screen: { orientation: {} },
    visualViewport: {},
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }),
  });
  CarScreen = (await import("./CarScreen")).CarScreen;
  CoachScreen = (await import("../coach/CoachScreen")).CoachScreen;
  vi.unstubAllGlobals();
});

const F1_25 = entry("f1_25:ps5", catalogue());
const HISTORY: HistoryPoint[] = Array.from({ length: 40 }, (_, i) => ({ t: i * 0.05, speed: 200 + i, throttle: 1, brake: 0 }));

/** contract strategy.pit.rules (F2 feature) */
const FEATURE_RULES: PitRules = {
  race: "feature",
  known: false,
  text: "The game doesn't send this race's tyre or pit-stop rules.",
  class_note:
    "In real F2 the feature race needs one pit stop and both dry compounds. In a 5-lap race on PS5, F1 25 did not enforce this; longer races are not known.",
};

function model(s: SnapshotNext | null, connected = true): DriveModel {
  return driveModel({ snap: s, connected, nowS: newestT(s) + 1, driver: null });
}

function visible(markup: string): string {
  return markup
    .replace(/<span class="sr-only">[^<]*<\/span>/g, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/\s+/g, " ")
    .trim();
}

/** An F2 frame as the server sends it (contract FrameAdditions): no ERS (null), the F2 compound, DRS fields. */
function f2Snap(over: Partial<SnapshotNext> = {}): SnapshotNext {
  return snap({
    session: f2JeddahSession(),
    frame: frame({
      tyre_compound: "super_soft",
      tyre_age_laps: 1,
      fuel_kg: 5.8,
      fuel_remaining_laps_game: 2.4,
      ers_store_j: null,
      drs_allowed: false,
      drs_activation_m: 120,
    }),
    ...over,
  });
}

describe("Tyres & energy", () => {
  it("F2: 'Super soft · 1 lap', and no ERS part at all", () => {
    const v = tyresTile(f2Snap(), F1_25);
    expect(v.chip).toBe("Super soft · 1 lap");
    expect(v.energy).toBe("Fuel 5.8 kg · +2.4 laps (game)");
    expect(v.energy).not.toContain("ERS");
  });

  it("an F1 car keeps its ERS (and '-' while unknown); an older server's snapshot is unchanged", () => {
    const f1 = f2Snap();
    f1.session = { ...f1.session!, car_class: F1_CLASS, car_label: "McLaren", session_label: "Race" };
    f1.frame = { ...f1.frame!, tyre_compound: "soft", ers_store_j: 2.8e6 };
    expect(tyresTile(f1, F1_25)).toMatchObject({ chip: "Soft · 1 lap", energy: "Fuel 5.8 kg · +2.4 laps (game) · ERS 2.8 MJ" });
    const old = f2Snap();
    old.session = { ...old.session!, car_class: undefined };
    expect(tyresTile(old, F1_25).energy).toBe("Fuel 5.8 kg · +2.4 laps (game) · ERS -");
  });
});

describe("the track tile", () => {
  it("another family's model: the caption says so; the class's own model or an older server: none", () => {
    const s = fixture("recorded-suzuka-on-track-brake-ahead");
    s.session = { ...s.session!, car_class: F2_CLASS };
    expect(mapTile(s, model(s)).borrowed).toBeNull(); // a model without families (an older server)
    s.track_model = { ...s.track_model!, car_family: "f1", car_family_match: false };
    expect(mapTile(s, model(s)).borrowed).toBe("Corners from F1 laps until your first clean F2 lap here.");
    s.track_model = { ...s.track_model!, car_family: "f2", car_family_match: true };
    expect(mapTile(s, model(s)).borrowed).toBeNull();
  });

  it("Drive › Track says it in the map's foot", () => {
    const s = fixture("recorded-suzuka-on-track-brake-ahead");
    s.session = { ...s.session!, car_class: F2_CLASS };
    expect(trackView(s, model(s), false).note).toBeNull();
    s.track_model = { ...s.track_model!, car_family: "f1", car_family_match: false };
    expect(trackView(s, model(s), false).note).toBe("Corners from F1 laps until your first clean F2 lap here.");
  });
});

describe("the strategy tile: no stop rules from the game", () => {
  function rows(v: StrategyView): Record<string, StrategyRowView> {
    return Object.fromEntries(strategyTile(snap({ strategy: v }), { dim: false, state: "on_track" }).rows.map((r) => [r.key, r]));
  }
  const withRules = (rules: PitRules | null | undefined) => {
    const v = liveView("edited-live-race-austria-l67"); // lap 67 of 71: no stop needed
    v.pit = { ...v.pit!, rules };
    return v;
  };

  it("beside 'No stop needed': 'Stop rules: not sent by the game' (in the row's words for screen readers too)", () => {
    const w = rows(withRules(FEATURE_RULES)).window!;
    expect(w).toMatchObject({ text: "No stop needed", note: STOP_RULES_LINE, tags: [] });
    expect(w.aria).toBe("Pit window: No stop needed. Stop rules: not sent by the game");
    expect(rows({ ...withRules(FEATURE_RULES) }).undercut!.note).toBeNull();
  });

  it("F1 races carry the rules block too (the game never sends them); an older server says nothing", () => {
    expect(rows(withRules({ ...FEATURE_RULES, race: null, class_note: null })).window!.note).toBe(STOP_RULES_LINE);
    expect(rows(withRules(undefined)).window!.note).toBeNull();
    expect(rows(withRules(null)).window!.note).toBeNull();
  });

  it("a pit window is no 'no stop' statement: no note", () => {
    const v = liveView("edited-live-race-window-open");
    v.pit = { ...v.pit!, rules: FEATURE_RULES };
    expect(rows(v).window!.note).toBeNull();
  });
});

describe("rendered", () => {
  function car(s: SnapshotNext): string {
    return renderToStaticMarkup(createElement(CarScreen, { model: model(s), snap: s, history: HISTORY, nowS: newestT(s) + 1, entry: F1_25 }));
  }

  it("Car: no ERS, the compound in words, the borrowed caption, the stop-rules line", () => {
    const s = fixture("recorded-austria-on-track-behind");
    s.session = { ...s.session!, car_class: F2_CLASS, car_label: "F2 · Art GP '24", session_label: "Feature race" };
    s.frame = { ...s.frame!, tyre_compound: "super_soft", tyre_age_laps: 1, ers_store_j: null };
    s.track_model = { ...s.track_model!, car_family: "f1", car_family_match: false };
    s.strategy = withRulesView();
    const text = visible(car(s));
    expect(text).toContain("Super soft · 1 lap");
    expect(text).not.toMatch(/\bERS\b/);
    expect(text).toContain("Corners from F1 laps until your first clean F2 lap here.");
    expect(text).toContain("No stop needed");
    expect(text).toContain(STOP_RULES_LINE);
    for (const bad of ["undefined", "null", "NaN"]) expect(text).not.toContain(bad);
  });

  it("Coach: the F2 chip next to the track and the race as F2 calls it", () => {
    const s = fixture("recorded-suzuka-on-track-brake-ahead");
    s.session = { ...s.session!, car_class: F2_CLASS, car_label: "F2 · Art GP '24", session_label: "Feature race" };
    const html = renderToStaticMarkup(createElement(CoachScreen, { model: model(s) }));
    const slot = html.slice(html.indexOf("pwc-status"), html.indexOf('data-slot="segment"', html.indexOf("pwc-status")));
    expect(slot).toContain("pwc-classchip");
    expect(visible(slot)).toMatch(/Suzuka F2 Feature race Lap 5/);
    // the chip's words for screen readers
    expect(slot).toContain('<span class="sr-only">Car class </span>');
    const f1 = fixture("recorded-suzuka-on-track-brake-ahead");
    expect(renderToStaticMarkup(createElement(CoachScreen, { model: model(f1) }))).not.toContain("pwc-classchip");
  });
});

function withRulesView(): StrategyView {
  const v = liveView("edited-live-race-austria-l67");
  v.pit = { ...v.pit!, rules: FEATURE_RULES };
  return v;
}
