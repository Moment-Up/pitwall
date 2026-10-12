// Setup › Controls rendered from the contract fixtures (server-rendered to static markup in plain node, no DOM
// library): every state the page has (loading, no wheel, an unsaved draft, a saved layout, F1 test unavailable,
// running and finished, GT7 "can't see your wheel", Map it, My wheel) renders without inventing anything (no
// "undefined", "null", "NaN" or em dash) and never says "validated".

import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, describe, expect, it, vi } from "vitest";
import type { ControlsCatalog, ControlsState, ControlsTest, Recommendation, WheelDef } from "../../../lib/endpoints/controls";
import { cfix, jamesWheel, type BackendCase } from "../../../lib/setup/controls-testkit";
import { parseControlsQuery, plainAssignments, resolveChoice, type ControlsQuery } from "../../../lib/setup/controls";
import { stubBrowser } from "../../../test/fakes";
import type { PageProps } from "../../../routes";
import { buildView, type ControlsActions, type ControlsView } from "./model";

function stubDom(): void {
  const { win } = stubBrowser("http://127.0.0.1:8770/#/setup/controls");
  Object.assign(win, {
    navigator: globalThis.navigator,
    removeEventListener: () => {},
    screen: { orientation: {} },
    visualViewport: {},
    matchMedia: () => ({ matches: true, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }),
  });
}

let LayoutView: ComponentType<{ v: ControlsView; a: ControlsActions }>;
let MapView: ComponentType<{ v: ControlsView; n: number | null }>;
let TestView: ComponentType<{ v: ControlsView }>;
let TestRun: ComponentType<{ v: ControlsView; test: ControlsTest; onSkip: () => void; onStop: () => void; onAgain: () => void; busy: boolean }>;
let WheelEditor: ComponentType<{ catalog: ControlsCatalog; state: ControlsState; initial: WheelDef | null; query: ControlsQuery }>;
let NoWheelCard: ComponentType<{ catalog: ControlsCatalog; onPick: () => void; onChange: () => void; onBuild: () => void }>;
let ControlsPage: ComponentType<PageProps>;
let WheelDiagram: ComponentType<{ wheel: WheelDef; rows: ControlsView["rows"]; reserved: ReadonlyMap<string, string>; catalog: ControlsCatalog; highlight?: string | null }>;

beforeAll(async () => {
  stubDom();
  LayoutView = (await import("./LayoutView")).LayoutView;
  MapView = (await import("./MapView")).MapView;
  const t = await import("./TestView");
  TestView = t.TestView;
  TestRun = t.TestRun;
  WheelEditor = (await import("./WheelEditor")).WheelEditor;
  WheelDiagram = (await import("./WheelDiagram")).WheelDiagram as typeof WheelDiagram;
  const page = await import("../ControlsPage");
  NoWheelCard = page.NoWheelCard as typeof NoWheelCard;
  ControlsPage = page.ControlsPage;
  vi.unstubAllGlobals();
});

const noop = () => {};
const actions: ControlsActions = { setAssignments: noop, useRecommended: noop, save: async () => true, saving: false, saveError: null, change: noop };

function viewInputs() {
  const catalog = cfix.catalog();
  const state = cfix.stateJames();
  const query = parseControlsQuery("");
  const choice = resolveChoice({ query, state, catalog, selected: null, driverId: 1, skill: "advanced" });
  return { catalog, state, choice, query, driverName: "James", wheel: jamesWheel(), rec: cfix.recF1Advanced(), draft: null, names: new Map([[1, "James"]]) };
}

function view(o: { state?: ControlsState; rec?: Recommendation; wheel?: WheelDef; query?: string; driverId?: number; skill?: string; driverName?: string | null } = {}): ControlsView {
  const catalog = cfix.catalog();
  const state = o.state ?? cfix.stateJames();
  const query = parseControlsQuery(o.query ?? "");
  const choice = resolveChoice({ query, state, catalog, selected: null, driverId: o.driverId ?? 1, skill: o.skill ?? "advanced" });
  return buildView({
    catalog,
    state,
    choice,
    query,
    driverName: o.driverName === undefined ? "James" : o.driverName,
    wheel: o.wheel ?? jamesWheel(),
    rec: o.rec ?? cfix.recF1Advanced(),
    draft: null,
    names: new Map([
      [1, "James"],
      [2, "Sam"],
    ]),
  });
}

const text = (html: string) =>
  html
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, "&")
    .replace(/&gt;/g, ">")
    .replace(/&lt;/g, "<")
    .replace(/\s+/g, " ");

/** The only sentences allowed to contain "validated": the ones that say nothing is. */
const NOT_VALIDATED = [/nothing here is validated on your rig( yet)?/gi, /Seen by Pitwall is not validated/gi];

function honest(html: string): string {
  const t = text(html);
  expect(t).not.toMatch(/\bundefined\b|\bnull\b|\bNaN\b|—|\[object Object\]/);
  expect(NOT_VALIDATED.reduce((x, r) => x.replace(r, ""), t)).not.toMatch(/validat/i);
  return t;
}

const render = <P extends object>(c: ComponentType<P>, p: P) => renderToStaticMarkup(createElement(c, p));

describe("the page shell", () => {
  it("loading: the header, the four views, the research-only banner and a skeleton", () => {
    stubDom();
    const html = render(ControlsPage, { route: { area: "setup", page: "controls", param: null, path: "/setup/controls", query: "" } });
    vi.unstubAllGlobals();
    const t = honest(html);
    expect(t).toContain("Layout");
    expect(t).toContain("Map it");
    expect(t).toContain("Test");
    expect(t).toContain("My wheel");
    expect(t).toContain("Research only. Pitwall can check F1 25 buttons in Test; nothing here is validated on your rig yet.");
    expect(html).toContain('data-testid="controls-loading"');
  });

  it("no wheel: Pick your wheel, brands first (any wheel, not one maker's), search every template and Build my own", () => {
    const t = honest(render(NoWheelCard, { catalog: cfix.catalog(), onPick: noop, onChange: noop, onBuild: noop }));
    expect(t).toContain("Pick your wheel");
    for (const b of ["Fanatec", "Logitech", "Thrustmaster", "MOZA", "Simagic", "Other"]) expect(t).toContain(b);
    expect(t).not.toContain("GT DD Pro"); // no one wheel is offered as if it were yours
    expect(t).toContain("Search all 23 wheels");
    expect(t).toContain("Build my own");
  });
});

describe("Layout", () => {
  it("an unsaved draft (fresh install, GT DD Pro from the research): Not saved yet, the list, the lists of what can't go on the wheel", () => {
    const v = view({ state: cfix.stateEmpty(), wheel: cfix.templateGtDdPro() });
    expect(v.layout).toBeNull();
    expect(v.dirty).toBe(true);
    const html = render(LayoutView, { v, a: actions });
    const t = honest(html);
    expect(html).toMatch(/data-testid="save-state"[^>]*>Not saved yet</);
    expect(t).toContain("Everyone on this PS5 profile");
    expect(t).toContain("Only James");
    expect(t).toContain("Brake bias +");
    expect(t).toContain("F1 25: Brake Bias Increase");
    expect(t).toContain("In F1 25, map Circle to UDP Action 1 under UDP Custom Actions.");
    expect(t).toContain("Can't change while driving in F1 25");
    expect(t).toContain("In F1 25, traction control and ABS are assists you set in the menu, not while driving.");
    expect(t).toContain("Not in F1 25");
    expect(t).toContain("Not on your wheel");
    expect(t).toContain("No free control left for Differential. Use the MFD.");
    expect(t).toContain("Kept for driving");
    expect(t).toContain("Same button as Pit limiter.");
    expect(t).toContain("Works only if F1 25 reads this wheel's extra buttons (unverified).");
    expect(t).toContain("Save first to print it.");
    // The preset warning every row carries is said once, above the list, not on each row.
    expect(html.match(/data-testid="common-warning"/g)?.length).toBe(1);
    expect(t.split("may already use this button").length - 1).toBe(1);
    // The diagram is hidden from assistive tech; the list carries the same facts.
    expect(html).toMatch(/<svg[^>]*aria-hidden="true"/);
    expect(html).toContain('data-marker="face_circle"');
  });

  it("James's saved household layout: Saved for everyone, the test results, print and copy", () => {
    const v = view();
    expect(v.layout?.id).toBe("l_9f8e7d6c");
    expect(v.dirty).toBe(false);
    const html = render(LayoutView, { v, a: actions });
    const t = honest(html);
    expect(t).toContain("Saved for everyone on this PS5 profile");
    expect(t).toContain("UDP Action 3 on Circle");
    expect(t).toMatch(/Seen by Pitwall \d+ Oct/);
    expect(html).toContain('href="/api/controls/layouts/l_9f8e7d6c/card.html?driver_id=1"');
    expect(t).toContain("Copy as text");
    expect(t).toContain("The radio listens to UDP Action 3 and 1 now (from a saved layout).");
  });

  it("a deleted driver's layout is listed under Unused layouts, not deleted", () => {
    const v = buildView({ ...viewInputs(), names: new Map([[1, "James"]]) });
    const html = render(LayoutView, { v, a: actions });
    expect(html).toContain('data-testid="unused-layouts"');
    expect(text(html)).toContain("Unused layouts (1)");
    expect(text(html)).toContain("Was for driver 2 (deleted)");
    expect(render(LayoutView, { v: view(), a: actions })).not.toContain("unused-layouts");
  });

  it("a beginner's view of the shared advanced layout: their preset, the rest under Also on this wheel", () => {
    const v = view({ driverId: 2, skill: "beginner", driverName: "Sam" });
    expect(v.choice.preset).toBe("beginner");
    const t = honest(render(LayoutView, { v, a: actions }));
    expect(t).toMatch(/Also on this wheel \(\d+\)/);
  });

  it("GT7: the coloured sticks are set by the game, Talk to Pitwall is the iPad or Space, ASM and ABS are pause-menu only", () => {
    const rec = cfix.recGt7();
    const v = view({ rec, query: "game=gt7&platform=ps5" });
    const html = render(LayoutView, { v, a: actions });
    const t = honest(html);
    expect(t).toContain("Set by the game");
    expect(t).toContain("iPad button or Space: Gran Turismo 7 doesn't send button presses");
    expect(html).toContain('data-testid="ptt-screen"');
    expect(t).toContain("GT7's stability control (ASM) and ABS are only in the pause menu, under Assistance Settings. They can't go on a button.");
    expect(t).toContain("Untested idea (Pitwall's suggestion)");
    expect(t).not.toContain("UDP Action");
  });

  it("Other game: the driver's name for it, no research", () => {
    const v = view({ rec: cfix.recOther(), query: "game=other&name=F1%2024&fns=brake_bias,drs_aero" });
    expect(v.gameLabel).toBe("F1 24");
    const t = honest(render(LayoutView, { v, a: actions }));
    expect(t).toContain("Pitwall has no research for this game: check the name in the game's Controls screen.");
  });
});

describe("Map it", () => {
  it("a draft's glance step: the game's name, the physical instruction, the control lit on the mini diagram", () => {
    const v = view({ state: cfix.stateEmpty(), wheel: cfix.templateGtDdPro() });
    const html = render(MapView, { v, n: 1 });
    const t = honest(html);
    expect(t).toContain("Where: Controls > [your wheel's preset]");
    expect(t).toContain("Official");
    expect(html).toMatch(/data-testid="map-native"[^>]*>Activate\/Deactivate DRS\/S Mode</);
    expect(html).toMatch(/data-testid="map-physical"[^>]*>Press TRIANGLE</);
    expect(t).toContain("Step 1 of");
    expect(t).toContain("‹ Previous");
    expect(t).toContain("Done, next ›");
    expect(html).toMatch(/data-marker="face_triangle"[^>]*data-highlight="true"/);
  });

  it("the last step and a step past the end", () => {
    const v = view({ state: cfix.stateEmpty(), wheel: cfix.templateGtDdPro() });
    const t = honest(render(MapView, { v, n: 99 }));
    expect(t).toContain("UDP Action 1");
    expect(t).toContain("Press CIRCLE");
    expect(t).toMatch(/Done(?!, next)/);
  });

  it("GT7 without research for the menu: it says the path was not researched to the step", () => {
    const v = view({ rec: cfix.recGt7(), query: "game=gt7&platform=ps5" });
    const t = honest(render(MapView, { v, n: null }));
    expect(t).toContain("the game's button assignment screen for your wheel");
    expect(t).toContain("Inferred");
  });
});

describe("Test", () => {
  it("GT7: Pitwall can't see your wheel, with the push-to-talk alternatives", () => {
    const v = view({ rec: cfix.recGt7(), query: "game=gt7&platform=ps5" });
    const html = render(TestView, { v });
    const t = honest(html);
    expect(html).toContain('data-testid="cant-see-wheel"');
    expect(t).toContain("Pitwall can't see your wheel in Gran Turismo 7");
    expect(t).toContain("Gran Turismo 7 doesn't send button presses, so Pitwall can't test your wheel here. Check each button in the game.");
    expect(t).toContain("hold Space on a keyboard");
  });

  it("F1 with an unsaved layout: save first", () => {
    const v = view({ state: cfix.stateEmpty(), wheel: cfix.templateGtDdPro() });
    const t = honest(render(TestView, { v }));
    expect(t).toContain("Save your layout first, then test it here.");
  });

  it("F1, saved: Start test and Identify", () => {
    const t = honest(render(TestView, { v: view() }));
    expect(t).toContain("Start test");
    expect(t).toContain("Wheel push-to-talk is paused while the test runs.");
    expect(t).toContain("Identify a control");
  });

  it("unavailable: why, that it starts by itself (the page keeps polling), and Stop", () => {
    const html = render(TestRun, { v: view(), test: cfix.testUnavailable(), onSkip: noop, onStop: noop, onAgain: noop, busy: false });
    const t = honest(html);
    expect(html).toContain('data-testid="test-unavailable"');
    expect(t).toContain("Waiting for F1 25");
    expect(t).toContain("No live F1 25 stream yet.");
    expect(t).toContain("The test starts by itself when Pitwall sees F1 25.");
    expect(t).toContain("Stop the test");
  });

  it("running: the current prompt big, every item's state, push-to-talk paused, replays tagged", () => {
    const html = render(TestRun, { v: view(), test: cfix.testRunning(), onSkip: noop, onStop: noop, onAgain: noop, busy: false });
    const t = honest(html);
    expect(t).toContain("Press Brake bias − once (L2)");
    expect(t).toContain("Wheel push-to-talk is paused while the test runs");
    expect(t).toContain("Seen by Pitwall");
    expect(t).toContain("Change seen");
    expect(t).toContain("Waiting");
    expect(t).toContain("REPLAY");
    expect(t).toContain("Skip this one ›");
    expect(t).toContain("Stop the test");
  });

  it("every item state renders (other bits, not seen, skipped) and a finished test says seen, not validated", () => {
    const test = cfix.testRunning();
    const states = ["detected", "other_bits", "timeout", "skipped", "effect_seen"] as const;
    test.items = test.items.map((i, k) => ({ ...i, state: states[k]!, detail: states[k] === "other_bits" ? "We saw Circle or B, not UDP Action 3: this button may be mapped to something else" : i.detail }));
    const html = render(TestRun, { v: view(), test, onSkip: noop, onStop: noop, onAgain: noop, busy: false });
    const t = text(html);
    expect(t).toContain("Something else");
    expect(t).toContain("Not seen");
    expect(t).toContain("Skipped");
    expect(t).toContain("We saw Circle or B, not UDP Action 3");
    expect(html).toContain('data-testid="test-finished"');
    expect(t).toContain("Test finished: 2 seen · 1 something else seen · 1 not seen · 1 skipped.");
    expect(t).toContain("To count it as proof, run Setup › Validation › Wheel buttons with F1 25 on the console.");
  });

  it("a stream sent from this computer: the run shows, says it isn't saved, and the finish says nothing was saved", () => {
    const why = "The data comes from this computer (pitwall send, a replay, or F1 25 on this PC), so presses show here but aren't saved.";
    const test = { ...cfix.testRunning(), available: true, saves: false, why };
    let html = render(TestRun, { v: view(), test, onSkip: noop, onStop: noop, onAgain: noop, busy: false });
    expect(html).toContain('data-testid="test-not-saved"');
    expect(html).not.toContain('data-testid="test-unavailable"');
    expect(text(html)).toContain("Shown here, not saved");
    expect(text(html)).toContain("F1 25 on this PC");
    const done = { ...test, items: test.items.map((i) => ({ ...i, state: "detected" as const, saved: false })) };
    html = render(TestRun, { v: view(), test: done, onSkip: noop, onStop: noop, onAgain: noop, busy: false });
    expect(text(html)).toContain(`Nothing was saved. ${why}`);
    expect(text(html)).not.toContain("The results are on your layout");
    const saved = { ...done, saves: true, why: null, items: done.items.map((i) => ({ ...i, saved: true })) };
    html = render(TestRun, { v: view(), test: saved, onSkip: noop, onStop: noop, onAgain: noop, busy: false });
    expect(text(html)).toContain("The results are on your layout with today's date.");
  });

  it("a press from F1's menus while the stream looks idle: the run shows instead of Waiting for F1 25", () => {
    const idle = cfix.testUnavailable();
    const run = cfix.testRunning();
    const test = { ...run, available: false, why: idle.why, current: 1, items: run.items.map((i, k) => (k === 0 ? { ...i, state: "detected" as const } : { ...i, state: "waiting" as const })) };
    const html = render(TestRun, { v: view(), test, onSkip: noop, onStop: noop, onAgain: noop, busy: false });
    expect(html).not.toContain('data-testid="test-unavailable"');
    expect(html).toContain('data-testid="test-not-saved"');
  });
});

describe("My wheel and the diagram", () => {
  it("a counts-only template: the banner, every control unplaced, Save but no Delete yet", () => {
    const html = render(WheelEditor, { catalog: cfix.catalog(), state: cfix.stateJames(), initial: cfix.templateMozaKs(), query: parseControlsQuery("") });
    const t = honest(html);
    expect(t).toContain("This template only says how many controls the rim has. Place them on the diagram.");
    expect(t).toContain("Not placed yet");
    expect(t).toContain("How many buttons?");
    expect(t).toContain("Rotary switches (positions)?");
  });

  it("James's wheel: Delete is blocked while layouts use it, with the list", () => {
    const html = render(WheelEditor, { catalog: cfix.catalog(), state: cfix.stateJames(), initial: jamesWheel(), query: parseControlsQuery("") });
    const t = honest(html);
    expect(html).toContain('data-testid="delete-blocked"');
    expect(t).toContain("Used by 2 layouts (F1 25 PS5, Gran Turismo 7 PS5), so it can't be deleted.");
  });

  it("a blank wheel to build", () => {
    const t = honest(render(WheelEditor, { catalog: cfix.catalog(), state: cfix.stateEmpty(), initial: null, query: parseControlsQuery("") }));
    expect(t).toContain("A new wheel");
    expect(t).toContain("None yet: start from a template or add them above.");
  });

  it("the diagram highlights one control and draws a marker per placed control", () => {
    const v = view();
    const html = render(WheelDiagram, { wheel: v.wheel, rows: v.rows, reserved: v.reserved, catalog: v.catalog, highlight: "r2" });
    expect(html.match(/data-marker=/g)?.length).toBe(v.wheel.controls.length);
    expect(html).toMatch(/data-marker="r2"[^>]*data-highlight="true"/);
    expect(text(html)).toContain("BB+");
    expect(text(html)).toContain("PITWALL");
  });

  it("the saved-layout copy text falls back to the local text with the same facts", () => {
    const v = view({ state: cfix.stateEmpty(), wheel: cfix.templateGtDdPro() });
    expect(plainAssignments(v.rec).length).toBe(v.rows.length);
  });
});

describe("the backend's own output renders (B1 modules called directly, before the API)", () => {
  async function backendView(name: BackendCase, query: string) {
    const c = cfix.backendCase(name);
    const catalog = cfix.backendCatalog();
    const state = cfix.stateEmpty();
    const q = parseControlsQuery(query);
    const choice = resolveChoice({ query: q, state, catalog, selected: null, driverId: 1, skill: "advanced" });
    return {
      c,
      v: buildView({ catalog, state, choice, query: q, driverName: "James", wheel: c.wheel, rec: c.rec, draft: null, names: new Map([[1, "James"]]) }),
    };
  }

  it("F1 25, PS5, GT DD Pro: Layout and Map it render honestly, and the draft's steps follow the server's groups", async () => {
    const { c, v } = await backendView("f1-ps5-gtddpro-advanced", "game=f1_25&platform=ps5&wheel=fanatec_gt_dd_pro_wheel&preset=advanced");
    const t = honest(render(LayoutView, { v, a: actions }));
    expect(t).toContain("Talk to Pitwall");
    expect(t).toContain("Not saved yet");
    const { draftGuide, stepGroups } = await import("../../../lib/setup/controls");
    const draft = draftGuide(v.rows, v.game);
    expect(stepGroups(draft.steps).map((g) => g.group)).toEqual(stepGroups(c.guide.steps).map((g) => g.group));
    const map = render(MapView, { v, n: 1 });
    honest(map);
    expect(map).toMatch(/data-highlight="true"/);
  });

  it("GT7, PS5, GT DD Pro; F1 25 on Xbox with the McLaren; ACC on PC with a counts-only MOZA", async () => {
    for (const [name, query] of [
      ["gt7-ps5-gtddpro-advanced", "game=gt7&platform=ps5"],
      ["f1-xbox-mclaren-advanced", "game=f1_25&platform=xbox"],
      ["acc-pc-moza-ks-beginner", "game=acc&platform=pc&preset=beginner"],
    ] as const) {
      const { v } = await backendView(name, query);
      honest(render(LayoutView, { v, a: actions }));
      honest(render(MapView, { v, n: null }));
      honest(render(TestView, { v }));
    }
  });

  it("server guide steps light the right control (the server's labels carry the action name in brackets)", async () => {
    const { c, v } = await backendView("f1-ps5-gtddpro-advanced", "game=f1_25&platform=ps5");
    const { stepControl } = await import("../../../lib/setup/controls");
    const drs = c.guide.steps.find((s) => s.label.startsWith("DRS"))!;
    expect(stepControl(drs, v.rows)).toBe(v.rows.find((r) => r.function === "drs_aero")?.control_id);
    const mfd = c.guide.steps.find((s) => s.label.startsWith("MFD"))!;
    expect(stepControl(mfd, v.rows)).toBe("menu_stick");
  });
});

describe("an isolated server's answers render (pitwall serve on 127.0.0.1, no game)", () => {
  it("the saved layout, Map it from the server's guide, and the waiting test", async () => {
    const catalog = cfix.backendCatalog();
    const state = cfix.isolated.state();
    const q = parseControlsQuery("game=f1_25&platform=ps5");
    const choice = resolveChoice({ query: q, state, catalog, selected: null, driverId: 1, skill: "advanced" });
    const wheel = state.wheels[0]!;
    const v = buildView({ catalog, state, choice, query: q, driverName: "Driver", wheel, rec: cfix.isolated.recTemplate(), draft: null, names: new Map([[1, "Driver"]]) });
    expect(v.layout?.id).toBe(state.layouts[0]!.id);
    expect(v.dirty).toBe(false);
    const t = honest(render(LayoutView, { v, a: actions }));
    expect(t).toContain("Saved for everyone on this PS5 profile");
    const { stepControl } = await import("../../../lib/setup/controls");
    for (const s of cfix.isolated.guide().steps) expect(stepControl(s, v.rows), s.label).not.toBeNull();
    const run = honest(render(TestRun, { v, test: cfix.isolated.testWaiting(), onSkip: noop, onStop: noop, onAgain: noop, busy: false }));
    expect(run).toContain("Waiting for F1 25");
    expect(run).toContain("No live F1 25 data");
  });
});
