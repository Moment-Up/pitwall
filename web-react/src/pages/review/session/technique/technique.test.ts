// Line and technique on Review (feat/technique spec §9), rendered from the contract fixtures as static markup in
// plain node: Compare's panel (map, markers, the focused corner, inputs by density, balance chips; phone; another game;
// synthetic; blocked; a server without the routes; no track model) and the Corners cards' "Line, inputs and balance".
// Data is put in the request cache first, so nothing is fetched. Nothing shown is advice; unknown is "-".
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../../../lib/api";
import type { Driver } from "../../../../lib/drivers";
import type { SessionAnalysis, SessionDetail } from "../../../../lib/endpoints/review";
import type { TechniqueCompare, TechniqueSession } from "../../../../lib/endpoints/technique";
import { densityFor, type Density } from "../../../../lib/review/density";
import { driver, fixtures } from "../../../../lib/review/testkit";
import { techniqueDensity } from "../../../../lib/technique/density";
import { ADVICE_WORDS, techniqueFixtures } from "../../../../lib/technique/testkit";
import { createCursorSync } from "../../../../lib/viz/cursor";
import { stubBrowser } from "../../../../test/fakes";
import type { CornersTabProps } from "../CornersTab";
import type { CornerTechniqueCtx } from "./CornerTechnique";
import type { TechniqueComparePanelProps } from "./TechniqueComparePanel";

function stubDom(): void {
  const { win } = stubBrowser("http://127.0.0.1:8770/#/review/sessions/332904dbe3de/compare");
  Object.assign(win, {
    navigator: globalThis.navigator,
    removeEventListener: () => {},
    screen: { orientation: {} },
    visualViewport: {},
    matchMedia: () => ({ matches: true, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }),
  });
}

let Panel: ComponentType<TechniqueComparePanelProps>;
let CornersTab: ComponentType<CornersTabProps>;
let CornerTechnique: ComponentType<{ corner: string; ctx: CornerTechniqueCtx }>;
let cache: typeof import("../../../../lib/cache").cache;
let keys: typeof import("../../../../lib/endpoints/technique").techniqueKeys;

beforeAll(async () => {
  stubDom();
  Panel = (await import("./TechniqueComparePanel")).TechniqueComparePanel;
  CornersTab = (await import("../CornersTab")).CornersTab;
  CornerTechnique = (await import("./CornerTechnique")).CornerTechnique;
  cache = (await import("../../../../lib/cache")).cache;
  keys = (await import("../../../../lib/endpoints/technique")).techniqueKeys;
  vi.unstubAllGlobals();
});

function visible(markup: string): string {
  return markup
    .replace(/<span class="sr-only">[^<]*<\/span>/g, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/\s+/g, " ")
    .trim();
}

function honest(text: string, what: string): void {
  for (const bad of ["NaN", "undefined", "null", "Infinity", "[object Object]", "—"]) expect(text, `${what}: ${bad}`).not.toContain(bad);
  for (const re of ADVICE_WORDS) expect(text, `${what}: advice`).not.toMatch(re);
}

const level = (l: Driver["preferences"]["skill_level"]): Density => densityFor(9, [driver(9, "Test", l)]);
const austria = (): SessionDetail => fixtures.austria();
const analysis = (): SessionAnalysis => fixtures.austriaAnalysis();

function seedCompare(cmp: TechniqueCompare = techniqueFixtures.austriaCompare()): void {
  cache.set(keys.compare(52, 54), cmp);
}

function renderPanel(over: Partial<TechniqueComparePanelProps> = {}): string {
  return renderToStaticMarkup(
    createElement(Panel, {
      session: { id: "332904dbe3de" },
      refLapId: 52,
      lapId: 54,
      sync: createCursorSync(null),
      density: level("advanced"),
      phone: false,
      ...over,
    }),
  );
}

async function seedError(key: string, e: Error): Promise<void> {
  cache.invalidate(key);
  await cache.load(key, () => Promise.reject(e)).catch(() => {});
}

describe("Compare: line and technique", () => {
  it("advanced: the map with numbered markers, T4 in detail with every input row, muted brake rows, degrees, every corner", () => {
    seedCompare();
    const html = renderPanel();
    const text = visible(html);
    honest(text, "panel advanced");
    for (const t of [
      "Line and technique",
      "Lap 66 against the reference (lap 64)",
      "A description of the two laps, not advice.",
      "How this is measured",
      "Racing line",
      "Whole lap",
      "T4 apex: 1.8 m wider than your reference",
      "T6 apex: 1.2 m wider than your reference",
      "Pitwall does not know the track edges: the lines show where each lap went.",
      "Every corner",
      // the focused corner (marker 1): offsets in words, the backend's notes verbatim
      "1.8 m wider",
      "coasted for 0.32 s between brake and throttle vs 0.08 s on your reference",
      "Metres tighter (+) or wider (−) than the reference line",
      // balance with degrees
      "Pushed wide (understeer) · +7.4°",
      // every input row (advanced)
      "Brake release",
      "Coasting",
      "Throttle pick-up",
      "Wheelspin and lock-ups",
      "Brake pressure (peak)",
      "Time to full brake",
      "Throttle lifts",
      // braking assist greys the brake rows with the API's sentence; the pedals note
      "braking assist on",
      "Braking assist is on (medium): the game adds its own braking, so these brake figures are not all yours.",
      "Stock CSL brake (measures pedal travel)",
      "ABS on: no lock-up data",
    ]) {
      expect(text, t).toContain(t);
    }
    // the muted release note stays in its greyed row, never as a listed difference
    expect(text).not.toContain("you let go of the brake all at once");
    expect(html).toContain('data-line="ref"');
    expect(html).toContain('data-line="lap"');
    expect(html).toContain('data-marker="1"');
    expect(html).toContain('data-marker="3"');
    // advanced: no glossary
    expect(text).not.toContain("What is understeer?");
    expect(html).not.toContain("What is understeer?");
    // signed time for advanced
    expect(text).toContain("+0.12 s");
  });

  it("the route's cursor picks the corner: at T9 Rindt Kurve, the wheelspin note and the slide on exit", () => {
    seedCompare();
    const text = visible(renderPanel({ sync: createCursorSync(3783) }));
    expect(text).toContain("Rindt Kurve");
    expect(text).toContain("wheelspin for 0.45 s on exit (2 times) vs none on your reference; traction control on (medium)");
    expect(text).toContain("Rear stepped out (oversteer) · slide");
  });

  it("beginner: 4 rows in simple words, no offset chart, glossary, words not signs, 'your target lap'", () => {
    seedCompare();
    const html = renderPanel({ density: level("beginner") });
    const text = visible(html);
    honest(text, "panel beginner");
    expect(text).toContain("against your target lap (lap 64)");
    for (const t of ["Brake release", "Coasting", "Throttle pick-up", "Wheelspin and lock-ups"]) expect(text).toContain(t);
    for (const t of ["Brake pressure (peak)", "Time to full brake", "Throttle lifts", "Braking while turning"]) expect(text).not.toContain(t);
    expect(text).toContain("you were off both pedals for longer than on your reference");
    expect(text).toContain("You ran wider at the apex of T4");
    expect(text).not.toContain("Metres tighter (+)");
    expect(text).not.toContain("+7.4°");
    expect(html).toContain("What is understeer?");
    expect(html).toContain("What is line offset?");
    expect(html).toContain("What is coasting?");
    expect(text).toContain("0.12 s lost");
    expect(text).not.toContain("+0.12 s");
  });

  it("intermediate: 8 rows, the offset chart, no degrees", () => {
    seedCompare();
    const text = visible(renderPanel({ density: level("intermediate") }));
    expect(text).toContain("Braking while turning");
    expect(text).toContain("Throttle ramp to full");
    expect(text).not.toContain("Time to full brake");
    expect(text).toContain("Metres tighter (+) or wider (−)");
    expect(text).not.toContain("+7.4°");
  });

  it("phone: corners as buttons, inputs as a list, a shorter map", () => {
    seedCompare();
    const html = renderPanel({ phone: true });
    expect(html).toContain('aria-label="Corners"');
    expect(html).toContain('data-row="release"');
    expect(html).not.toContain('aria-label="Line and technique by corner"');
    expect(html).toContain("height:240px");
    expect(visible(html)).not.toContain("Tap a corner to zoom");
  });

  it("another game: no slip data, so balance gives the reason; no line gives its reason", () => {
    const cmp = techniqueFixtures.austriaCompare();
    const reason = "This game does not send tyre slip to Pitwall yet, so wheelspin, lock-ups and balance are unknown.";
    cmp.available.slip = { ok: false, reason, note: null };
    cmp.available.balance = { ok: false, reason, note: null };
    cmp.available.line = { ok: false, reason: "No positions for this lap.", note: null };
    cmp.lines = null;
    cmp.markers = [];
    for (const c of cmp.corners) {
      c.ref_balance = null;
      c.lap_balance = null;
    }
    seedCompare(cmp);
    const html = renderPanel();
    const text = visible(html);
    honest(text, "panel other game");
    expect(text).toContain(reason);
    expect(text).toContain("No positions for this lap.");
    expect(text).not.toContain("Pushed wide");
    expect(html).not.toContain('data-line="ref"');
  });

  it("synthetic laps are labelled", () => {
    seedCompare({ ...techniqueFixtures.austriaCompare(), synthetic: true });
    expect(visible(renderPanel())).toContain("SYNTHETIC");
  });

  it("a pair the server will not compare shows its reasons", () => {
    seedCompare({ ...techniqueFixtures.austriaCompare(), compatible: false, blocking: ["The reference lap is synthetic and this one is not."] });
    const text = visible(renderPanel());
    expect(text).toContain("Not compared");
    expect(text).toContain("The reference lap is synthetic and this one is not.");
    expect(text).not.toContain("Racing line");
  });

  it("a server without the routes shows nothing; no track model yet says so; no pair renders nothing", async () => {
    await seedError(keys.compare(61, 62), new ApiError(404, "Not Found"));
    expect(renderPanel({ refLapId: 61, lapId: 62 })).toBe("");
    await seedError(keys.compare(63, 64), new ApiError(409, "no track model yet for this track (complete a clean lap first)"));
    expect(visible(renderPanel({ refLapId: 63, lapId: 64 }))).toContain("No track model yet for this track (complete a clean lap first)");
    await seedError(keys.compare(65, 66), new ApiError(404, "lap 66 not found"));
    expect(visible(renderPanel({ refLapId: 65, lapId: 66 }))).toContain("Not available for these laps: Lap 66 not found");
    expect(renderPanel({ refLapId: null })).toBe("");
    expect(renderPanel({ refLapId: 54 })).toBe("");
  });

  it("loading: a skeleton, no words", () => {
    cache.invalidate("technique-compare:");
    const html = renderToStaticMarkup(
      createElement(Panel, { session: { id: "x" }, refLapId: 1, lapId: 2, sync: createCursorSync(), density: level("advanced"), phone: false }),
    );
    expect(html).toContain('aria-busy="true"');
  });
});

describe("Corners: line, inputs and balance", () => {
  function seedSession(t: TechniqueSession = techniqueFixtures.austriaSession()): void {
    cache.set(keys.session("332904dbe3de"), t);
  }

  it("advanced: open, with the line over the session, phases with their verdicts, habits, slip and a mini map", () => {
    seedSession();
    const s = austria();
    const html = renderToStaticMarkup(createElement(CornersTab, { session: s, analysis: analysis(), density: level("advanced") }));
    const text = visible(html);
    honest(text, "corners advanced");
    for (const t of [
      "Line, inputs and balance",
      "Line against your reference (lap 64)",
      "Apex: 1.4 m wider on 6 of 8 laps",
      "Mid: understeer on 8 of 9 laps, even on your best lap",
      "Entry: understeer on 5 of 9 laps, not on your best lap",
      "coasted between brake and throttle for 0.15 s or more longer than your reference on 5 of 8 laps",
      "ABS on: no lock-up data",
      "No wheelspin (traction control on)",
      "Pitwall does not know the track edges",
    ]) {
      expect(text, t).toContain(t);
    }
    expect(html).toContain('data-verdict="car"');
    expect(html).toContain('data-verdict="driving"');
    expect(html).toContain('data-line="lap"');
  });

  it("beginner: collapsed, no mini map, simple habits", () => {
    seedSession();
    const s = austria();
    const html = renderToStaticMarkup(createElement(CornersTab, { session: s, analysis: analysis(), density: level("beginner") }));
    expect(html).toContain("Line, inputs and balance");
    expect(html).toMatch(/aria-expanded="false"[^>]*>Line, inputs and balance/);
    expect(html).not.toContain('data-line="lap"');
    expect(visible(html)).toContain("you were off both pedals for longer than on your reference on 5 of 8 laps");
  });

  it("muted habits (brake figures with the game's braking assist on) are not listed on the card", () => {
    const data = techniqueFixtures.austriaSession();
    const corner = data.corners.find((c) => c.habits.length)!;
    const habit = corner.habits[0]!;
    const muted = { ...habit, metric: "release" as const, muted: true, text: "On 3 of 3 laps you released the brake more quickly.", text_simple: "Released the brake sooner." };
    const withMuted = { ...data, corners: data.corners.map((c) => (c === corner ? { ...c, habits: [muted, ...c.habits] } : c)) };
    const ctx: CornerTechniqueCtx = { state: { data: withMuted, error: null }, td: techniqueDensity(level("advanced")) };
    const text = visible(renderToStaticMarkup(createElement(CornerTechnique, { corner: corner.corner, ctx })));
    expect(text).not.toContain("released the brake more quickly");
    expect(text).toContain(habit.text);
  });

  it("a game without slip data: the reason instead of phases, the line still shown", () => {
    const data = techniqueFixtures.gt7Session();
    const ctx: CornerTechniqueCtx = { state: { data, error: null }, td: techniqueDensity(level("advanced")) };
    const text = visible(renderToStaticMarkup(createElement(CornerTechnique, { corner: "C1", ctx })));
    honest(text, "gt7 corner");
    expect(text).toContain("Apex: 1.1 m wider on 2 of 2 laps");
    expect(text).toContain("This game does not send tyre slip to Pitwall yet");
    expect(text).not.toContain("ABS on");
  });

  it("wheelspin over the session at T9 Rindt Kurve", () => {
    const data = techniqueFixtures.austriaSession();
    const ctx: CornerTechniqueCtx = { state: { data, error: null }, td: techniqueDensity(level("intermediate")) };
    const text = visible(renderToStaticMarkup(createElement(CornerTechnique, { corner: "T6", ctx })));
    expect(text).toContain("ABS on: no lock-up data · Wheelspin on 1 of 8 laps (traction control on)");
    expect(text).toContain("Exit: balanced on 8 of 9 laps");
  });

  it("no technique for a corner, or a server without the routes: nothing extra", () => {
    const td = techniqueDensity(level("advanced"));
    const data = techniqueFixtures.noReference();
    expect(renderToStaticMarkup(createElement(CornerTechnique, { corner: "T1", ctx: { state: { data, error: null }, td } }))).toBe("");
    expect(
      renderToStaticMarkup(createElement(CornerTechnique, { corner: "T1", ctx: { state: { data: undefined, error: new ApiError(404, "Not Found") }, td } })),
    ).toBe("");
  });
});
