// Setup › Game: F1 25's car classes (F2 support, contract v1), rendered to static markup in plain node. The classes
// and their status are the server's (capabilities.CAR_CLASSES on /api/games, contract GamesAndCapabilities): F2 says
// "Tested on a recording" (13 F2 sessions on PS5), never "Tested live"; a game without classes, or an older server,
// shows no section. The catalogue is the edited contract fixture with the contract's car_classes added.
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, describe, expect, it, vi } from "vitest";
import type { GameCarClass, GameEntry, GamesResponse } from "../../../lib/endpoints/game";
import { carClassRows } from "../../../lib/game";
import { catalogue, entry } from "../../../lib/game-testkit";
import { stubBrowser } from "../../../test/fakes";

let FeaturesCard: ComponentType<{ entry: GameEntry; catalogue: GamesResponse; wide: boolean }>;

beforeAll(async () => {
  const { win } = stubBrowser("http://127.0.0.1:8770/#/setup/game");
  Object.assign(win, {
    navigator: globalThis.navigator,
    removeEventListener: () => {},
    screen: { orientation: {} },
    visualViewport: {},
    matchMedia: () => ({ matches: true, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }),
  });
  FeaturesCard = (await import("./FeaturesCard")).FeaturesCard;
  vi.unstubAllGlobals();
});

/** contract section 11: the CAR_CLASSES table on F1 rows (the server sends "f1_2025" and "f1" as two "F1" rows) */
const CLASSES: GameCarClass[] = [
  { id: "f1_2025", label: "F1", status: "live_validated", notes: "The existing live run." },
  { id: "f1", label: "F1", status: "live_validated", notes: "The existing live run." },
  { id: "f1_2026", label: "F1 (2026)", status: "spec_implemented", notes: ["No live or recorded run."] },
  {
    id: "f2",
    label: "F2",
    status: "recorded_validated",
    notes: ["13 F2 sessions on PS5, F1 25 v1.26, format 2025, 11 Oct 2026.", "F2 cars have no ERS: F1 25 sends 0 for them."],
  },
  { id: "f1_classic", label: "Classic F1", status: "spec_implemented", notes: "ERS unknown." },
  { id: "other", label: null, status: "unverified", notes: null },
];

function text(html: string): string {
  return html
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ")
    .trim();
}

describe("car classes", () => {
  it("the server's classes, status words and notes, in its order, one row per class the driver can tell apart; green only for evidence from the real game", () => {
    const cat = catalogue();
    const rows = carClassRows({ ...entry("f1_25:ps5", cat), car_classes: CLASSES }, cat);
    expect(rows.map((r) => [r.label, r.chip.label, r.chip.tone])).toEqual([
      ["F1", "Tested live", "success"],
      ["F1 (2026)", "Built from the official spec", "default"],
      ["F2", "Tested on a recording", "success"],
      ["Classic F1", "Built from the official spec", "default"],
      ["Other cars", "Unverified", "warning"],
    ]);
    expect(rows[2]!.notes).toEqual(CLASSES[3]!.notes);
    expect(rows[0]!.notes).toEqual(["The existing live run."]);
    expect(rows[4]!.notes).toEqual([]);
  });

  it("none for another game or an older server", () => {
    const cat = catalogue();
    expect(carClassRows(entry("gt7:ps5", cat), cat)).toEqual([]);
    expect(carClassRows(entry("f1_25:ps5", cat), cat)).toEqual([]);
    expect(carClassRows(null)).toEqual([]);
  });

  it("Setup › Game lists them under 'Car classes'; F2 is never 'Tested live'", () => {
    const cat = catalogue();
    const f1 = { ...entry("f1_25:ps5", cat), car_classes: CLASSES };
    const html = renderToStaticMarkup(createElement(FeaturesCard, { entry: f1, catalogue: cat, wide: true }));
    const t = text(html);
    expect(t).toContain("Car classes");
    expect(t).toMatch(/F2 Tested on a recording/);
    expect(t).not.toMatch(/F2 Tested live/);
    expect(t.match(/F1 Tested live/g)).toHaveLength(1);
    expect(t).toContain("How the car classes were tested");
    expect(t).toContain("F2: 13 F2 sessions on PS5, F1 25 v1.26, format 2025, 11 Oct 2026. F2 cars have no ERS");
    expect(html).toContain('data-car-class="f2"');
    for (const bad of ["undefined", "null", "NaN"]) expect(t).not.toContain(bad);
    const gt7 = renderToStaticMarkup(createElement(FeaturesCard, { entry: entry("gt7:ps5", cat), catalogue: cat, wide: true }));
    expect(gt7).not.toContain("data-car-classes");
  });
});
