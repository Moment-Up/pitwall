// /api/controls client: the contract fixtures carry exactly the contract's keys (the types in controls.ts), paths
// and bodies, cache keys, and errors in words, with fetch stubbed (plain node, no server).

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { json, stubBrowser } from "../../test/fakes";
import { resetTokenCacheForTests } from "../auth";
import { BACKEND_CASES, cfix } from "../setup/controls-testkit";
import {
  CONTROLS_KEYS,
  ControlsError,
  asButtonsFeed,
  asStoppedTest,
  controlsApi,
  controlsErrorText,
  controlsPaths,
  controlsQs,
  isConflict,
  type Layout,
} from "./controls";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  resetTokenCacheForTests();
  stubBrowser("http://127.0.0.1:8770/#/setup/controls");
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

const lastCall = () => {
  const c = fetchMock.mock.calls.at(-1) as [string, RequestInit | undefined] | undefined;
  if (!c) throw new Error("fetch was not called");
  return { path: c[0], init: c[1] ?? {} };
};

const keys = (o: object) => Object.keys(o).sort();

// The contract's keys (the types in controls.ts), required ones only; optional keys are listed apart.
const K = {
  catalog: ["evidence_labels", "functions", "games", "kinds", "not_possible", "other_game", "reserved", "sources", "status", "templates", "version", "zones"],
  fn: ["freq", "group", "id", "label", "shape", "short", "synonyms"],
  game: ["button_path", "functions", "id", "label", "menu", "platforms", "presets", "research_depth", "telemetry_keys"],
  gameFn: ["actions", "binding", "conditions", "evidence", "function", "in_race", "menu_group", "native_name", "pitwall_sees", "platform_note", "shares_with", "source_ids"],
  template: ["brand", "completeness", "id", "name", "platforms", "shape", "type"],
  wheel: ["controls", "created_unix", "id", "name", "parts", "platforms", "rev", "shape", "template", "template_version", "updated_unix"],
  control: ["evidence", "id", "kind", "label", "mps_mode", "note", "order", "part", "positions", "push", "reach", "signals", "zone"],
  signal: ["evidence", "kind", "source_ids", "value"],
  state: ["defaults", "drivers", "household", "layouts", "ptt", "schema", "wheels"],
  layout: ["assignments", "created_unix", "game", "game_name", "id", "other_functions", "owner", "platform", "preset", "rev", "updated_unix", "wheel_id"],
  assignment: ["action", "check", "control_id", "function", "key", "origin", "slot", "udp_action"],
  recAssignment: [
    "action",
    "check",
    "conditions",
    "control_id",
    "control_label",
    "evidence",
    "evidence_parts",
    "function",
    "key",
    "label",
    "menu_group",
    "native",
    "origin",
    "pitwall_sees",
    "reason",
    "signal",
    "slot",
    "source_ids",
    "udp_action",
    "warnings",
  ],
  rec: [
    "assignments",
    "catalogue_version",
    "driver_id",
    "game",
    "not_in_game",
    "not_on_wheel",
    "notes",
    "pitwall_ptt",
    "platform",
    "preset",
    "reserved",
    "status",
    "unplaced",
    "wheel_id",
  ],
  guide: ["intro", "outro", "steps", "where", "where_evidence"],
  step: ["evidence", "group", "label", "n", "native", "note", "physical"],
  test: ["available", "current", "feed", "id", "items", "layout_id", "started_unix", "wheel_ptt_paused", "why"],
  item: ["detail", "expect", "key", "kind", "prompt", "seen", "state"],
  press: ["origin", "pressed", "released", "seq", "status", "t_unix"],
};
const OPTIONAL = { catalog: ["diagram"], signal: ["per_slot", "seen"], state: ["updated_unix"], test: ["saves"], item: ["saved"] };

function expectKeys(o: object, required: string[], optional: string[] = [], what = ""): void {
  const extra = keys(o).filter((k) => !required.includes(k) && !optional.includes(k));
  expect(extra, `${what}: keys outside the contract`).toEqual([]);
  for (const k of required) expect(Object.hasOwn(o, k), `${what}: missing ${k}`).toBe(true);
}

describe("the contract fixtures match the contract", () => {
  it("every fixture says what it is: a contract fixture, or backend module output (never an HTTP answer)", () => {
    for (const n of cfix.names()) {
      const m = cfix.meta(n);
      if (n.startsWith("backend-b1-")) expect(m.source, n).toMatch(/Not an HTTP answer/);
      else if (n.startsWith("isolated-")) expect(m.source, n).toMatch(/isolated `pitwall serve`.*Not a live rig/s);
      else {
        expect(m.source, n).toMatch(/contract fixture/);
        expect(m.source, n).toMatch(/Not a server answer/);
      }
    }
  });

  it("the catalogue: 11 games, 30 functions, 23 templates plus custom, sources that resolve", () => {
    const c = cfix.catalog();
    expectKeys(c, K.catalog, OPTIONAL.catalog, "catalog");
    expect(c.games.map((g) => g.id)).toEqual(["f1_25", "gt7", "ac", "acc", "forza_motorsport", "iracing", "lmu", "rf2", "ams2", "r3e", "ac_evo"]);
    expect(c.functions).toHaveLength(30);
    expect(c.templates).toHaveLength(24);
    expect(c.templates.at(-1)?.id).toBe("custom");
    for (const f of c.functions) expectKeys(f, K.fn, [], f.id);
    for (const t of c.templates) expectKeys(t, K.template, [], t.id);
    for (const g of c.games) {
      expectKeys(g, K.game, [], g.id);
      for (const f of g.functions) {
        expectKeys(f, K.gameFn, [], `${g.id}.${f.function}`);
        for (const s of f.source_ids) expect(c.sources[s], `${g.id}.${f.function} source ${s}`).toBeTruthy();
      }
      // Presets never hold what the game doesn't allow mid-race (design 2.1 loader rule).
      for (const p of ["beginner", "advanced"] as const) {
        for (const id of g.presets[p]) {
          const row = g.functions.find((f) => f.function === id);
          expect(row, `${g.id} ${p} ${id}`).toBeTruthy();
          expect(["no", "pause_menu"]).not.toContain(row!.in_race);
          expect(["menu", "none"]).not.toContain(row!.binding);
        }
      }
    }
    expect(Object.keys(c.evidence_labels).sort()).toEqual(["A", "D", "H", "U", "V", "seen"]);
    // Only F1 25 sends button presses.
    expect(c.games.filter((g) => g.button_path === "f1_butn").map((g) => g.id)).toEqual(["f1_25"]);
  });

  it("wheels and controls (templates and the saved one)", () => {
    for (const w of [cfix.templateGtDdPro(), cfix.templateMcLaren(), cfix.templateMozaKs(), ...cfix.stateJames().wheels]) {
      expectKeys(w, K.wheel, [], w.name);
      for (const c of w.controls) {
        expectKeys(c, K.control, [], `${w.name}.${c.id}`);
        for (const s of Object.values(c.signals)) expectKeys(s, K.signal, OPTIONAL.signal, `${w.name}.${c.id} signal`);
      }
    }
    // A template draft is unsaved: rev 0 and the backend's stable virtual id ("w_" + 8 hex of the template id).
    expect(cfix.templateGtDdPro()).toMatchObject({ id: "w_d8c01858", rev: 0 });
    expect(cfix.stateJames().wheels[0]?.rev).toBeGreaterThan(0);
  });

  it("state, layouts and assignments", () => {
    for (const s of [cfix.stateEmpty(), cfix.stateJames()]) {
      expectKeys(s, K.state, OPTIONAL.state, "state");
      expect(keys(s.ptt)).toEqual(["fallback_kept", "from", "label", "layout_id", "udp_actions"]);
      expect(keys(s.defaults)).toEqual(["driver_id", "game", "platform", "preset", "template", "wheel_id"]);
      for (const l of s.layouts) {
        expectKeys(l, K.layout, [], l.id);
        for (const a of l.assignments) expectKeys(a, K.assignment, [], `${l.id}.${a.key}`);
      }
    }
  });

  it("recommendations, the guide, the test and the button feed", () => {
    for (const r of [cfix.recF1Advanced(), cfix.recF1Beginner(), cfix.recGt7(), cfix.recOther()]) {
      expectKeys(r, K.rec, [], `${r.game} rec`);
      expect(r.status).toBe("research_only");
      for (const a of r.assignments) {
        expectKeys(a, K.recAssignment, [], `${r.game}.${a.key}`);
        expect(a.reason.length, a.key).toBeLessThanOrEqual(160);
      }
    }
    const g = cfix.guideF1();
    expectKeys(g, K.guide, [], "guide");
    for (const s of g.steps) expectKeys(s, K.step, [], `step ${s.n}`);
    for (const t of [cfix.testRunning(), cfix.testUnavailable()]) {
      expectKeys(t, K.test, [], "test");
      for (const i of t.items) expectKeys(i, K.item, [], i.key);
      for (const p of t.feed) expectKeys(p, K.press, [], `press ${p.seq}`);
    }
    for (const p of cfix.buttons().feed) expectKeys(p, K.press, [], `press ${p.seq}`);
  });
});

describe("the backend's own output has the contract's keys (B1 modules, before the API)", () => {
  it("catalogue", () => {
    const c = cfix.backendCatalog();
    expectKeys(c, K.catalog, OPTIONAL.catalog, "catalog");
    expect(c.games.map((g) => g.id)).toEqual(cfix.catalog().games.map((g) => g.id));
    expect(c.functions.map((f) => f.id)).toEqual(cfix.catalog().functions.map((f) => f.id));
    expect(c.templates.map((t) => t.id)).toEqual(cfix.catalog().templates.map((t) => t.id));
    for (const f of c.functions) expectKeys(f, K.fn, [], f.id);
    for (const t of c.templates) expectKeys(t, K.template, [], t.id);
    for (const g of c.games) {
      expectKeys(g, K.game, [], g.id);
      for (const f of g.functions) expectKeys(f, K.gameFn, [], `${g.id}.${f.function}`);
    }
    expect(Object.keys(c.diagram?.shapes ?? {}).sort()).toEqual(["box", "d", "formula", "round"]);
  });

  for (const name of BACKEND_CASES) {
    it(name, () => {
      const { wheel, rec, guide } = cfix.backendCase(name);
      expectKeys(wheel, K.wheel, [], "wheel");
      expect(wheel.rev).toBe(0); // a template draft
      for (const ctl of wheel.controls) {
        expectKeys(ctl, K.control, [], ctl.id);
        for (const s of Object.values(ctl.signals)) expectKeys(s, K.signal, OPTIONAL.signal, `${ctl.id} signal`);
      }
      expectKeys(rec, K.rec, [], "rec");
      for (const a of rec.assignments) {
        expectKeys(a, K.recAssignment, [], a.key);
        expect(a.reason.length, a.key).toBeLessThanOrEqual(160);
      }
      expectKeys(guide, K.guide, [], "guide");
      for (const s of guide.steps) expectKeys(s, K.step, [], `step ${s.n}`);
    });
  }
});

describe("an isolated server's HTTP answers have the contract's keys", () => {
  it("state after a save, the template recommendation, the guide, buttons and tests", () => {
    const st = cfix.isolated.state();
    expectKeys(st, K.state, OPTIONAL.state, "state");
    expect(st.wheels).toHaveLength(1);
    expect(st.wheels[0]!.rev).toBeGreaterThan(0);
    for (const w of st.wheels) for (const c of w.controls) expectKeys(c, K.control, [], c.id);
    for (const l of st.layouts) {
      expectKeys(l, K.layout, [], l.id);
      for (const a of l.assignments) expectKeys(a, K.assignment, [], a.key);
    }
    expect(st.household.layouts["f1_25:ps5"]).toBe(st.layouts[0]!.id); // the owner (household) points at it
    const rec = cfix.isolated.recTemplate();
    expectKeys(rec, K.rec, [], "rec");
    for (const a of rec.assignments) expectKeys(a, K.recAssignment, [], a.key);
    const g = cfix.isolated.guide();
    expectKeys(g, K.guide, [], "guide");
    for (const s of g.steps) expectKeys(s, K.step, [], `step ${s.n}`);
    expect(asButtonsFeed(cfix.isolated.buttons())).toEqual({ seq: 0, feed: [] });
    expect(cfix.isolated.testNone()).toBeNull();
    const t = cfix.isolated.testWaiting();
    expectKeys(t, K.test, OPTIONAL.test, "test");
    expect(t).toMatchObject({ available: false, wheel_ptt_paused: expect.any(Boolean) });
    for (const i of t.items) expectKeys(i, K.item, OPTIONAL.item, i.key);
    expect(asStoppedTest(cfix.isolated.testStopped())?.items.every((i) => i.state === "skipped")).toBe(true);
  });
});

describe("paths", () => {
  it("leaves unset values out and joins lists", () => {
    expect(controlsQs({ a: 1, b: null, c: undefined, d: "", e: [], f: ["x", "y"] })).toBe("?a=1&f=x%2Cy");
    expect(controlsQs({})).toBe("");
  });

  it("recommendation: a saved wheel by id, an unsaved one by template; Other sends its name and functions", () => {
    expect(controlsPaths.recommendation({ game: "f1_25", platform: "ps5", wheel_id: "w_1a2b3c4d", template: "x", driver_id: 1, preset: "advanced" })).toBe(
      "/api/controls/recommendation?game=f1_25&platform=ps5&wheel_id=w_1a2b3c4d&driver_id=1&preset=advanced",
    );
    expect(controlsPaths.recommendation({ game: "gt7", platform: "ps5", template: "fanatec_gt_dd_pro_wheel" })).toBe(
      "/api/controls/recommendation?game=gt7&platform=ps5&template=fanatec_gt_dd_pro_wheel",
    );
    expect(
      controlsPaths.recommendation({ game: "other", platform: "pc", wheel_id: "w_1", game_name: "F1 24", functions: ["brake_bias", "drs_aero"] }),
    ).toBe("/api/controls/recommendation?game=other&platform=pc&wheel_id=w_1&game_name=F1+24&functions=brake_bias%2Cdrs_aero");
    // game_name and functions belong to Other only.
    expect(controlsPaths.recommendation({ game: "f1_25", platform: "pc", wheel_id: "w_1", game_name: "x", functions: ["tc"] })).toBe(
      "/api/controls/recommendation?game=f1_25&platform=pc&wheel_id=w_1",
    );
  });

  it("ids are encoded; the printable card carries the tab's token", () => {
    expect(controlsPaths.layout("l/1")).toBe("/api/controls/layouts/l%2F1");
    expect(controlsPaths.signal("w_1", "face triangle")).toBe("/api/controls/wheels/w_1/controls/face%20triangle/signal");
    expect(controlsPaths.guide("l_1", "ps5")).toBe("/api/controls/layouts/l_1/guide?platform=ps5");
    expect(controlsPaths.cardTxt("l_1", 2)).toBe("/api/controls/layouts/l_1/card.txt?driver_id=2");
    expect(controlsPaths.cardHtmlTab("l_1", 2)).toBe("/api/controls/layouts/l_1/card.html?driver_id=2");
    stubBrowser("http://127.0.0.1:8770/#/setup/controls?token=a b");
    resetTokenCacheForTests();
    expect(controlsPaths.cardHtmlTab("l_1", null)).toBe("/api/controls/layouts/l_1/card.html?token=a+b");
    expect(controlsPaths.buttons(41)).toBe("/api/controls/buttons?since=41");
    expect(controlsPaths.state(null)).toBe("/api/controls/state");
  });
});

describe("cache keys", () => {
  it("every key starts with controls:, a template and a saved wheel never share a recommendation", () => {
    const a = CONTROLS_KEYS.recommendation({ game: "f1_25", platform: "ps5", wheel_id: "w_1" });
    const b = CONTROLS_KEYS.recommendation({ game: "f1_25", platform: "ps5", template: "w_1" });
    expect(a).not.toBe(b);
    expect(CONTROLS_KEYS.recommendation({ game: "other", platform: "ps5", wheel_id: "w_1", game_name: "F1 24", functions: ["tc"] })).not.toBe(
      CONTROLS_KEYS.recommendation({ game: "other", platform: "ps5", wheel_id: "w_1", game_name: "F1 24", functions: ["abs"] }),
    );
    for (const k of [a, b, CONTROLS_KEYS.catalog, CONTROLS_KEYS.state(1), CONTROLS_KEYS.guide("l", "ps5", 2), CONTROLS_KEYS.card("l", 2, null), CONTROLS_KEYS.test]) {
      expect(k.startsWith(CONTROLS_KEYS.all)).toBe(true);
    }
    // A save invalidates every key under data (state, recommendations, guides, cards); never the catalogue.
    for (const p of CONTROLS_KEYS.data) expect(CONTROLS_KEYS.catalog.startsWith(p)).toBe(false);
    expect(CONTROLS_KEYS.data.some((p) => CONTROLS_KEYS.state(1).startsWith(p))).toBe(true);
    expect(CONTROLS_KEYS.data.some((p) => CONTROLS_KEYS.guide("l", "ps5", 2).startsWith(p))).toBe(true);
  });
});

describe("requests", () => {
  it("PUT layout sends the whole layout with the rev it read", async () => {
    const l = cfix.stateJames().layouts[0] as Layout;
    fetchMock.mockResolvedValue(json({ ...l, rev: l.rev + 1 }));
    const out = await controlsApi.putLayout(l);
    const { path, init } = lastCall();
    expect(path).toBe(`/api/controls/layouts/${l.id}`);
    expect(init.method).toBe("PUT");
    // LayoutPut refuses extra fields: only rev, preset, owner, the Other game's name and functions, assignments.
    expect(Object.keys(JSON.parse(String(init.body))).sort()).toEqual(["assignments", "game_name", "other_functions", "owner", "preset", "rev"]);
    expect(JSON.parse(String(init.body))).toMatchObject({ rev: l.rev, owner: "household" });
    expect(out.rev).toBe(l.rev + 1);
  });

  it("POST layout from the recommendation, POST test, skip and stop", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(json({})));
    await controlsApi.createLayout({ game: "f1_25", platform: "ps5", wheel_id: "w_1", owner: "household", preset: "advanced", from_recommendation: true });
    expect(JSON.parse(String(lastCall().init.body))).toEqual({
      game: "f1_25",
      platform: "ps5",
      wheel_id: "w_1",
      owner: "household",
      preset: "advanced",
      from_recommendation: true,
    });
    await controlsApi.startTest("l_1");
    expect(lastCall()).toMatchObject({ path: "/api/controls/test", init: { method: "POST", body: JSON.stringify({ layout_id: "l_1" }) } });
    await controlsApi.skip("t_1");
    expect(lastCall().path).toBe("/api/controls/test/t_1/skip");
    fetchMock.mockImplementationOnce(() => Promise.resolve(json({ stopped: "t_1", test: cfix.testRunning() })));
    expect((await controlsApi.stop("t_1"))?.items).toHaveLength(5);
    expect(lastCall().path).toBe("/api/controls/test/t_1/stop");
    fetchMock.mockImplementationOnce(() => Promise.resolve(json({ stopped: "t_1", test: null })));
    expect(await controlsApi.stop("t_1")).toBeNull();
    await controlsApi.deleteWheel("w_1");
    expect(lastCall()).toMatchObject({ path: "/api/controls/wheels/w_1", init: { method: "DELETE" } });
    expect(lastCall().init.body).toBeUndefined();
  });

  it("Identify saves one control's signal for one platform", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(json({})));
    await controlsApi.setSignal("w_1", "l3", "ps", { kind: "pad", value: "l3", evidence: "seen", source_ids: [] });
    const { path, init } = lastCall();
    expect(path).toBe("/api/controls/wheels/w_1/controls/l3/signal");
    expect(JSON.parse(String(init.body))).toEqual({ platform: "ps", signal: { kind: "pad", value: "l3", evidence: "seen", source_ids: [] } });
  });

  it("no test yet is null (404), not an error", async () => {
    fetchMock.mockResolvedValue(json({ detail: "No test" }, 404));
    expect(await controlsApi.test()).toBeNull();
    fetchMock.mockResolvedValue(json(null));
    expect(await controlsApi.test()).toBeNull();
    fetchMock.mockResolvedValue(json(cfix.testRunning()));
    expect((await controlsApi.test())?.items).toHaveLength(5);
  });

  it("the button feed accepts {seq, feed} and a bare list", async () => {
    expect(asButtonsFeed(cfix.buttons()).seq).toBe(3);
    // routes_controls.py names the list "presses".
    expect(asButtonsFeed({ seq: 9, presses: cfix.buttons().feed })).toMatchObject({ seq: 9, feed: cfix.buttons().feed });
    expect(asButtonsFeed(cfix.buttons().feed)).toMatchObject({ seq: 3 });
    expect(asButtonsFeed("nonsense")).toEqual({ seq: 0, feed: [] });
    fetchMock.mockResolvedValue(json(cfix.buttons().feed));
    expect((await controlsApi.buttons()).feed).toHaveLength(3);
  });

  it("errors in words: 409 says someone else saved first, 422 lists the fields", async () => {
    fetchMock.mockResolvedValue(json({ detail: [{ loc: ["body", "name"], msg: "at most 40 characters" }] }, 422));
    const e422 = await controlsApi.createWheel({ name: "x".repeat(41) }).catch((e: unknown) => e);
    expect(e422).toBeInstanceOf(ControlsError);
    expect(controlsErrorText(e422)).toBe("name: at most 40 characters");
    fetchMock.mockResolvedValue(json({ detail: { rev: 5 } }, 409));
    const e409 = await controlsApi.putLayout(cfix.stateJames().layouts[0]!).catch((e: unknown) => e);
    expect(isConflict(e409)).toBe(true);
    expect(controlsErrorText(e409)).toMatch(/Someone else changed this first/);
    fetchMock.mockResolvedValue(json({ detail: "This wheel is used by 2 layouts." }, 409));
    const used = await controlsApi.deleteWheel("w_1").catch((e: unknown) => e);
    expect(controlsErrorText(used)).toBe("This wheel is used by 2 layouts.");
  });
});
