// The rig walkthrough (spec 7.2; lane X): the research copy, the plan built from it and a recorded recommendation,
// tick-as-you-go progress (per device, per driver and game; changed rows reopen as "Updated"), position and recovery
// tips. Recorded answers of the live API: src/lib/setup/fixtures/rig-*.json.

import { afterEach, describe, expect, it, vi } from "vitest";
import ours from "../../data/walkthrough.json?raw";
import research from "../../../../docs/research/gt-dd-pro-ps5-walkthrough.json?raw";
import { memoryStorage } from "../../test/fakes";
import type { Hardware, Recommendation } from "../endpoints/rig";
import { fixtures } from "./fixtures";
import {
  PROGRESS_KEY,
  TIP_TARGETS,
  WALKTHROUGH,
  WALK_SECTIONS,
  buildPlan,
  firstOpen,
  flatten,
  guideChips,
  guideRun,
  guidesApply,
  hasCheck,
  hash,
  isUnverified,
  itemAt,
  itemState,
  itemTitle,
  loadTicks,
  locate,
  neighbour,
  parseWalkthrough,
  pitwallPages,
  progressScope,
  readProgress,
  relevantMistakes,
  saveTicks,
  sectionCounts,
  sectionDone,
  sourceRefs,
  tick,
  untick,
  type WalkItem,
  type WalkPlan,
} from "./walkthrough";

afterEach(() => vi.unstubAllGlobals());

const PS5: Hardware = { platform: "ps5", wheel_base: "fanatec_gt_dd_pro", torque_nm: 5, pedals: "csl", rim: "gt_dd_pro_bundled" };

const ids = (plan: WalkPlan, section: string) => plan.sections.find((s) => s.id === section)!.items.map((i) => i.id);
const all = (plan: WalkPlan): WalkItem[] => plan.sections.flatMap((s) => s.items);

describe("the research copy", () => {
  it("is byte-identical to docs/research/gt-dd-pro-ps5-walkthrough.json", () => {
    expect(ours.length).toBeGreaterThan(10_000);
    expect(ours).toBe(research);
  });

  it("parses into guides, mistakes and sources", () => {
    expect(WALKTHROUGH.walkthroughs.map((g) => g.id)).toEqual([
      "controls",
      "mode",
      "menu_basics",
      "standard_advanced",
      "slot",
      "values",
      "pedals_hall",
      "load_cell_brf",
      "f1_25",
      "gt7",
      "centre_calibration",
    ]);
    expect(WALKTHROUGH.mistakes.length).toBeGreaterThan(10);
    expect(WALKTHROUGH.sources.M?.title).toMatch(/manual/i);
    for (const g of WALKTHROUGH.walkthroughs)
      for (const s of g.steps) {
        expect(typeof s.verified).toBe("boolean");
        expect(["V", "A", "U", "D"]).toContain(s.evidence);
      }
  });

  it("anything malformed becomes an empty doc, never a crash", () => {
    expect(parseWalkthrough(null).walkthroughs).toEqual([]);
    expect(parseWalkthrough({ walkthroughs: [{ id: 1 }, { id: "x", steps: [{ text: "a", evidence: "Z" }] }] }).walkthroughs).toEqual([
      { id: "x", title: "x", steps: [{ text: "a", evidence: "U", check: "-", source: "", verified: false }] },
    ]);
  });

  it("every research mistake is a recovery tip somewhere", () => {
    for (const m of WALKTHROUGH.mistakes) expect(TIP_TARGETS[m.id], m.id).toBeDefined();
  });

  it("old Svelte page names point at the new pages", () => {
    expect(pitwallPages("pitwall Live tab (F1 25 telemetry on, on track): bars")).toBe("Drive › Car in Pitwall (F1 25 telemetry on, on track): bars");
    expect(pitwallPages("pitwall Live brake bar reaches 100")).toBe("The brake input on Drive › Car in Pitwall reaches 100");
    expect(pitwallPages("(pitwall Setup tab)")).toBe("(Setup › Rig › All settings in Pitwall)");
    expect(pitwallPages("from the pitwall Setup sheet")).toBe("from the Setup › Rig › All settings in Pitwall");
    const texts = WALKTHROUGH.walkthroughs.flatMap((g) => g.steps.flatMap((s) => [s.text, s.check])).concat(WALKTHROUGH.mistakes.map((m) => m.fix));
    for (const t of texts) expect(pitwallPages(t)).not.toMatch(/pitwall (Live|Setup) (tab|sheet|brake)/);
  });
});

describe("evidence of a guide step", () => {
  it("flags unverified steps, with the research's own explanation", () => {
    const labels = WALKTHROUGH.evidence_labels;
    expect(guideChips({ verified: true, evidence: "V" }, labels)).toEqual([{ label: "Verified", tone: "default", title: labels.V }]);
    expect(guideChips({ verified: false, evidence: "A" }, labels).map((c) => c.label)).toEqual(["Seen in Fanatec's video", "Unverified"]);
    expect(guideChips({ verified: false, evidence: "U" }, labels)).toEqual([{ label: "Unverified", tone: "warning", title: labels.U }]);
    expect(isUnverified({ verified: true, evidence: "U" })).toBe(true);
    expect(isUnverified({ verified: true, evidence: "D" })).toBe(false);
    expect(hasCheck({ check: "-" })).toBe(false);
    expect(hasCheck({ check: "Ring is dark blue." })).toBe(true);
  });

  it("resolves source codes to titled links; free text and repository paths stay text", () => {
    const refs = sourceRefs("M p19 figure; VID25 ~10:15; derived from M p21; RSS 3.1", WALKTHROUGH);
    expect(refs[0]).toMatchObject({ code: "M", locator: "p19 figure", url: WALKTHROUGH.sources.M!.url });
    expect(refs[1]).toMatchObject({ code: "VID25", locator: "~10:15" });
    expect(refs[2]).toMatchObject({ code: null, text: "derived from M p21", url: null });
    expect(refs[3]).toMatchObject({ code: "RSS", url: null }); // docs/research/... is not a web link
    expect(sourceRefs("FORUM-LOCK [U]", WALKTHROUGH)[0]?.code).toBe("FORUM-LOCK");
  });
});

describe("the plan: F1 25 on the researched rig (PS5, GT DD Pro, stock CSL pedals)", () => {
  const rec = fixtures.rigRecF1James();
  const plan = buildPlan(rec, PS5, "f1_25");

  it("has the five sections of the spec, each with items", () => {
    expect(plan.sections.map((s) => s.title)).toEqual(["Base mode", "Wheel menu", "In game", "Pedals", "Check on track"]);
    expect(plan.sections.map((s) => s.id)).toEqual(WALK_SECTIONS.map((s) => s.id));
    for (const s of plan.sections) expect(s.items.length).toBeGreaterThan(0);
    expect(plan.guided).toBe(true);
  });

  it("base mode: find the controls, power on in dark blue, then the firmware note", () => {
    const base = ids(plan, "base");
    expect(base[0]).toBe("g:controls:0");
    expect(base).toContain("g:mode:7");
    expect(base.at(-1)).toBe("s:base:firmware");
    expect(base).not.toContain("s:base:mode"); // the mode guide says it in more detail
  });

  it("wheel menu: how to use the menu, Advanced, the slot, then every wheel row in menu order between the value how-tos", () => {
    const wheel = ids(plan, "wheel");
    const at = (id: string) => wheel.indexOf(id);
    expect(at("g:menu_basics:0")).toBe(0);
    expect(at("s:base:menu")).toBeGreaterThan(at("g:menu_basics:5"));
    expect(at("g:standard_advanced:0")).toBeGreaterThan(at("s:base:menu"));
    expect(at("g:slot:0")).toBeGreaterThan(at("s:base:no_a_set_f1"));
    expect(at("s:base:sen_match")).toBeGreaterThan(at("g:slot:6"));
    const rows = rec.sections.find((s) => s.id === "wheel")!.rows.map((r) => `r:wheel:${r.key}`);
    expect(wheel.filter((i) => i.startsWith("r:"))).toEqual(rows);
    expect(at(rows[0]!)).toBe(at("g:values:2") + 1);
    expect(at("g:values:3")).toBe(at(rows.at(-1)!) + 1);
  });

  it("in game: where the F1 25 settings are, then the in-game rows", () => {
    const ingame = ids(plan, "ingame");
    expect(ingame[0]).toBe("g:f1_25:0");
    expect(ingame.filter((i) => i.startsWith("r:"))).toEqual(rec.sections.find((s) => s.id === "ingame")!.rows.map((r) => `r:ingame:${r.key}`));
    expect(ingame.some((i) => i.startsWith("g:gt7"))).toBe(false);
  });

  it("pedals: the stock CSL routine replaces the API's three matching steps", () => {
    expect(ids(plan, "pedals")).toEqual(["g:pedals_hall:0", "g:pedals_hall:1", "g:pedals_hall:2"]);
    expect(plan.covered.sort()).toEqual(["connection", "hall_no_brf", "mode", "power_on_press"]);
  });

  it("check on track: the known bug, one change at a time, then the rig check card with the API's text", () => {
    const check = plan.sections.find((s) => s.id === "check")!.items;
    expect(check.map((i) => i.id)).toEqual(["s:base:v125_bug", "s:base:one_change", "check"]);
    const last = check.at(-1)!;
    expect(last.kind === "check" && last.step?.id).toBe("rig_check");
  });

  it("loses nothing: every research step of the shown guides and every API step or row is placed exactly once", () => {
    const items = all(plan);
    expect(new Set(items.map((i) => i.id)).size).toBe(items.length);
    for (const g of ["controls", "mode", "menu_basics", "standard_advanced", "slot", "values", "f1_25", "pedals_hall"]) {
      const n = WALKTHROUGH.walkthroughs.find((x) => x.id === g)!.steps.length;
      expect(items.filter((i) => i.kind === "guide" && i.guide.id === g)).toHaveLength(n);
    }
    const apiSteps = rec.sections.flatMap((s) => s.steps.map((st) => st.id)).filter((id) => !plan.covered.includes(id));
    const placed = items.flatMap((i) => (i.kind === "step" || (i.kind === "check" && i.step) ? [i.step!.id] : []));
    expect(placed.sort()).toEqual(apiSteps.sort());
    const rows = rec.sections.flatMap((s) => s.rows.map((r) => `r:${s.id}:${r.key}`));
    expect(items.filter((i) => i.kind === "row").map((i) => i.id)).toEqual(rows);
    expect(
      items.some((i) => i.kind === "guide" && (i.guide.id === "gt7" || i.guide.id === "load_cell_brf" || i.guide.id === "centre_calibration")),
    ).toBe(false);
  });

  it("recovery tips sit where they help", () => {
    const find = (id: string) => all(plan).find((i) => i.id === id)!;
    expect(find("r:wheel:FF").tips).toContain("a_set_locked");
    expect(find("r:wheel:SEN").tips).toEqual(expect.arrayContaining(["a_set_locked", "sen_mismatch"]));
    expect(find("r:wheel:INT").tips).toContain("standard_menu");
    expect(find("g:mode:4").tips).toEqual(expect.arrayContaining(["wrong_mode", "power_held", "cal_flashing"]));
    expect(find("r:ingame:MAX_WHEEL_ROTATION").tips).toEqual(["sen_mismatch"]);
    expect(find("check").tips).toEqual(["f1_v125_oscillation"]);
    expect(all(plan).flatMap((i) => i.tips)).not.toContain("gt7_wheel_spins");
  });
});

describe("the plan for other games, styles and rigs", () => {
  it("GT7 (A SET): no Advanced switch, no slot or value how-tos, every wheel row locked, the GT7 guide in game", () => {
    const rec = fixtures.rigRecGt7James();
    const plan = buildPlan(rec, PS5, "gt7");
    const wheel = ids(plan, "wheel");
    expect(wheel.some((i) => i.startsWith("g:standard_advanced") || i.startsWith("g:slot") || i.startsWith("g:values"))).toBe(false);
    expect(wheel).toContain("s:base:slot"); // the API's "Select A SET" step
    const rows = all(plan).filter((i) => i.kind === "row" && i.from === "wheel");
    expect(rows.length).toBeGreaterThan(5);
    for (const r of rows) expect(r.tips).not.toContain("a_set_locked"); // A SET is meant here
    expect(ids(plan, "ingame")[0]).toBe("g:gt7:0");
    expect(ids(plan, "pedals")).toContain("s:pedals:gt7_no_pedal_settings");
    expect(all(plan).flatMap((i) => i.tips)).not.toContain("f1_v125_oscillation");
  });

  it("Comfort for a beginner: the driver's own slot, and the safety steps before driving", () => {
    const rec = fixtures.rigRecF1ComfortBeginner();
    const plan = buildPlan(rec, PS5, "f1_25");
    expect(ids(plan, "wheel")).toContain("s:base:driver_slot");
    expect(ids(plan, "check").slice(0, 2)).toEqual(["s:safety:lighter_wheel", "s:safety:hands"]);
  });

  it("with the Load Cell Kit: the BRF guide, and the API's pedal steps stay", () => {
    const rec = fixtures.rigRecF1James();
    const plan = buildPlan(rec, { ...PS5, pedals: "csl_load_cell" }, "f1_25");
    const pedals = ids(plan, "pedals");
    expect(pedals[0]).toBe("g:load_cell_brf:0");
    expect(pedals).toContain("s:pedals:power_on_press"); // only the stock-pedal guide covers it
    expect(plan.covered).toEqual(["mode"]);
  });

  it("on another rig (PC) the research does not apply: only the API's steps and rows", () => {
    const rec = fixtures.rigRecF1James();
    expect(guidesApply({ platform: "pc", wheel_base: "fanatec_gt_dd_pro" })).toBe(false);
    const plan = buildPlan(rec, { ...PS5, platform: "pc" }, "f1_25");
    expect(plan.guided).toBe(false);
    expect(all(plan).some((i) => i.kind === "guide")).toBe(false);
    expect(plan.covered).toEqual([]);
    expect(ids(plan, "base")).toContain("s:base:mode");
    expect(ids(plan, "pedals")).toEqual(["s:pedals:power_on_press", "s:pedals:hall_no_brf", "s:pedals:connection"]);
  });

  it("an empty recommendation still ends on the rig check card", () => {
    const empty = { ...fixtures.rigRecF1James(), sections: [], safety: [] } as Recommendation;
    const plan = buildPlan(empty, { ...PS5, platform: "pc" }, "f1_25");
    expect(all(plan).map((i) => i.id)).toEqual(["check"]);
  });

  it("relevant mistakes follow the game and the hardware", () => {
    const f1 = relevantMistakes(WALKTHROUGH, "f1_25", PS5).map((m) => m.id);
    expect(f1).toContain("sen_mismatch");
    expect(f1).toContain("pedal_range");
    expect(f1).not.toContain("gt7_wheel_spins");
    expect(f1).not.toContain("lc_input_at_rest");
    expect(f1).not.toContain("ffs_missing_boost");
    const gt7 = relevantMistakes(WALKTHROUGH, "gt7", { pedals: "csl_load_cell", torque_nm: 8 }).map((m) => m.id);
    expect(gt7).toEqual(expect.arrayContaining(["gt7_wheel_spins", "lc_input_at_rest", "ffs_missing_boost"]));
    expect(gt7).not.toContain("f1_v125_oscillation");
  });
});

describe("progress: tick as you go", () => {
  const rec = fixtures.rigRecF1James();
  const plan = buildPlan(rec, PS5, "f1_25");

  it("a tick remembers what was asked; a changed value reopens as Updated", () => {
    const ff = all(plan).find((i) => i.id === "r:wheel:FF")!;
    let ticks = tick({}, [ff]);
    expect(itemState(ff, ticks)).toBe("done");
    const lighter = buildPlan(
      { ...rec, sections: rec.sections.map((s) => ({ ...s, rows: s.rows.map((r) => (r.key === "FF" ? { ...r, value: "60" } : r)) })) },
      PS5,
      "f1_25",
    );
    const ff60 = all(lighter).find((i) => i.id === "r:wheel:FF")!;
    expect(itemState(ff60, ticks)).toBe("updated");
    ticks = untick(ticks, ff);
    expect(itemState(ff, ticks)).toBe("open");
    expect(hash("a")).toMatch(/^[0-9a-f]{8}$/);
    expect(hash("a")).not.toBe(hash("b"));
  });

  it("sections are done when every item is; a guide can be skipped as a whole", () => {
    const pedals = plan.sections.find((s) => s.id === "pedals")!;
    expect(sectionDone(pedals, {})).toBe(false);
    const ticks = tick({}, guideRun(pedals, pedals.items[1]!));
    expect(sectionCounts(pedals, ticks)).toEqual({ done: 3, total: 3 });
    expect(sectionDone(pedals, ticks)).toBe(true);
    expect(guideRun(pedals, pedals.items[0]!)).toHaveLength(3);
  });

  it("is stored per game and driver, survives junk and blocked storage", () => {
    const local = memoryStorage();
    vi.stubGlobal("localStorage", local);
    const james = progressScope("f1_25", 1);
    const alex = progressScope("f1_25", 2);
    expect(james).not.toBe(alex);
    saveTicks(james, { a: "1" });
    saveTicks(alex, { b: "2" });
    expect(loadTicks(james)).toEqual({ a: "1" });
    expect(loadTicks(alex)).toEqual({ b: "2" });
    expect(loadTicks(progressScope("gt7", 1))).toEqual({});
    local.setItem(PROGRESS_KEY, "{not json");
    expect(loadTicks(james)).toEqual({});
    expect(readProgress(JSON.stringify({ x: { a: "1", b: 2 }, y: 3 }))).toEqual({ x: { a: "1" } });
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    });
    expect(loadTicks(james)).toEqual({});
    expect(() => saveTicks(james, { a: "1" })).not.toThrow();
  });
});

describe("position and moving on", () => {
  const plan = buildPlan(fixtures.rigRecF1James(), PS5, "f1_25");
  const flat = flatten(plan);

  it("lands on the first step not done; a section on its first open step; a named step as named", () => {
    expect(locate(plan, null, null, {})).toEqual({ s: 0, i: 0 });
    const base = plan.sections[0]!;
    const ticks = tick({}, base.items.slice(0, 4));
    expect(locate(plan, null, null, ticks)).toEqual({ s: 0, i: 4 });
    expect(locate(plan, "base", null, ticks)).toEqual({ s: 0, i: 4 });
    expect(locate(plan, "wheel", 3, ticks)).toEqual({ s: 1, i: 2 });
    expect(locate(plan, "wheel", 999, ticks)).toEqual({ s: 1, i: 0 }); // out of range: the section's first open step
    expect(locate(plan, "nope", 2, ticks)).toEqual({ s: 0, i: 4 });
    const everything = tick({}, all(plan));
    expect(firstOpen(plan, everything)).toBeNull();
    expect(locate(plan, null, null, everything)).toEqual({ s: 4, i: plan.sections[4]!.items.length - 1 });
  });

  it("next and previous cross sections and stop at the ends", () => {
    expect(neighbour(plan, { s: 0, i: 0 }, -1)).toBeNull();
    const lastBase = { s: 0, i: plan.sections[0]!.items.length - 1 };
    expect(neighbour(plan, lastBase, 1)).toEqual({ s: 1, i: 0 });
    expect(neighbour(plan, { s: 1, i: 0 }, -1)).toEqual(lastBase);
    expect(neighbour(plan, flat.at(-1)!, 1)).toBeNull();
    expect(itemAt(plan, { s: 9, i: 0 })).toBeNull();
  });

  it("firstOpen wraps from the current position", () => {
    const ticks = tick({}, plan.sections[1]!.items.concat(plan.sections[2]!.items, plan.sections[3]!.items, plan.sections[4]!.items));
    expect(firstOpen(plan, ticks, { s: 2, i: 0 })).toEqual({ s: 0, i: 0 });
  });

  it("list titles: rows show code and value, instructions say check", () => {
    const items = all(plan);
    expect(itemTitle(items.find((i) => i.id === "r:wheel:FF")!)).toEqual({
      code: "FF",
      text: expect.stringMatching(/^Force Feedback/),
      value: "100",
    });
    const comfort = buildPlan(fixtures.rigRecF1ComfortBeginner(), PS5, "f1_25");
    expect(itemTitle(all(comfort).find((i) => i.id === "r:ingame:BRAKE_LINEARITY")!).value).toBe("check");
    expect(itemTitle(items.find((i) => i.id === "check")!).text).toBe("Drive 3 clean laps, then open Rig check");
  });
});
