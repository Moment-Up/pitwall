// Setup › Controls pure helpers: the page's query and choice, layout rows and the driver's preset filter, the diagram's
// zone stacking (no overlap, legible at 320 px), which free controls fit each shape, Map it step order, evidence and
// test words (never "validated"), push-to-talk words and the plain-text copy.

import { describe, expect, it } from "vitest";
import { parseControlsParam } from "../route-parse";
import type { Assignment, ControlKind, PlatformId, WheelControl, WheelDef, Zone } from "../endpoints/controls";
import { cfix, jamesWheel } from "./controls-testkit";
import {
  DEFAULT_GEOMETRY,
  EVIDENCE_WORDS,
  MARKER,
  TEST_STATE,
  addControls,
  assignTo,
  checkChip,
  controlSlots,
  controlsPath,
  diagramFor,
  draftGuide,
  evidenceChip,
  findLayout,
  functionOptions,
  gameById,
  gameForTelemetryKey,
  gameGroups,
  layoutMarkers,
  layoutRows,
  layoutText,
  markKept,
  markerFontPx,
  moveControl,
  overlaps,
  fitText,
  zoneGrid,
  parseControlsQuery,
  physicalText,
  plainAssignments,
  platformsFor,
  pressText,
  pttConflict,
  pttLine,
  reservedControls,
  resolveChoice,
  sameAssignments,
  sharedSlots,
  signalText,
  slotOptions,
  splitRows,
  stepGroups,
  udpBit,
  unusedLayouts,
  weakest,
  wheelRef,
  type LayoutRow,
} from "./controls";

const cat = cfix.catalog();
const f1 = gameById(cat, "f1_25")!;
const gt7 = gameById(cat, "gt7")!;

function rowsFor(assignments: readonly Assignment[], rec = cfix.recF1Advanced(), wheel: WheelDef = jamesWheel(), platform: PlatformId = "ps5", game = f1): LayoutRow[] {
  return layoutRows({ assignments, rec, catalog: cat, game, wheel, platform });
}

describe("words never claim more than the evidence", () => {
  it("evidence words, and no validated anywhere", () => {
    expect(EVIDENCE_WORDS).toEqual({
      V: "Official",
      A: "Inferred",
      U: "Community",
      D: "Pitwall's suggestion",
      H: "Your entry",
      seen: "Seen by Pitwall",
    });
    const all = [...Object.values(EVIDENCE_WORDS), ...Object.values(TEST_STATE).map((s) => s.label)].join(" ");
    expect(all).not.toMatch(/validat/i);
    expect(evidenceChip("U")?.tone).toBe("warning");
    expect(evidenceChip("seen")?.tone).toBe("success");
    expect(evidenceChip(null)).toBeNull();
  });

  it("an assignment is never more certain than its weaker part", () => {
    expect(weakest("V", "A")).toBe("A");
    expect(weakest("A", "U")).toBe("U");
    expect(weakest("seen", "V")).toBe("V");
    expect(weakest("V", null)).toBeNull();
  });

  it("test results on a row: Seen by Pitwall with the day, never validated", () => {
    const now = new Date(1791830000 * 1000);
    expect(checkChip({ result: "detected", t_unix: 1791830000, detail: "UDP Action 3 seen", origin: "live" }, now)).toMatchObject({
      label: "Seen by Pitwall 12 Oct",
      tone: "success",
    });
    expect(checkChip({ result: "other_bits", t_unix: 1791830000, detail: "x", origin: "live" }, now)?.label).toBe("Something else seen 12 Oct");
    expect(checkChip(null)).toBeNull();
  });
});

describe("page query and route", () => {
  it("parses and rebuilds the query, dropping what isn't valid", () => {
    const q = parseControlsQuery("driver=2&game=gt7&platform=ps5&wheel=w_1a2b3c4d&preset=beginner&name=x&fns=tc");
    expect(q).toEqual({ driver: 2, game: "gt7", platform: "ps5", wheel: "w_1a2b3c4d", preset: "beginner", name: "x", fns: ["tc"] });
    expect(parseControlsQuery("driver=x&platform=switch&preset=pro&game=../x")).toMatchObject({ driver: null, platform: null, preset: null, game: null });
    expect(controlsPath("layout", q)).toBe("/setup/controls?driver=2&game=gt7&platform=ps5&wheel=w_1a2b3c4d&preset=beginner");
    expect(controlsPath("map", { game: "f1_25" }, 3)).toBe("/setup/controls/map/3?game=f1_25");
    expect(controlsPath("wheel", {}, "w_1a2b3c4d")).toBe("/setup/controls/wheel/w_1a2b3c4d");
    expect(controlsPath("test")).toBe("/setup/controls/test");
    // Other keeps its name and functions.
    expect(controlsPath("layout", { game: "other", name: "F1 24", fns: ["brake_bias", "drs_aero"] })).toBe(
      "/setup/controls?game=other&name=F1+24&fns=brake_bias%2Cdrs_aero",
    );
    expect(parseControlsParam("map/2")).toEqual({ view: "map", n: 2, wheelId: null });
  });

  it("a template draft (rev 0, virtual id) is not a saved wheel", async () => {
    const { isSavedWheel } = await import("./controls");
    expect(isSavedWheel(cfix.templateGtDdPro())).toBe(false);
    expect(isSavedWheel(jamesWheel())).toBe(true);
    expect(isSavedWheel(null)).toBe(false);
  });

  it("wheel query values: saved ids start w_, anything else is a template", () => {
    expect(wheelRef("w_1a2b3c4d")).toEqual({ kind: "saved", id: "w_1a2b3c4d" });
    expect(wheelRef("fanatec_gt_dd_pro_wheel")).toEqual({ kind: "template", id: "fanatec_gt_dd_pro_wheel" });
    expect(wheelRef(null)).toBeNull();
  });
});

describe("the choice the page opens on (design 2.5, 4)", () => {
  const base = { query: parseControlsQuery(""), catalog: cat, driverId: 1, skill: "advanced" };

  it("fresh install: the selected game mapped through telemetry keys, the rig's wheel template, the skill's preset", () => {
    const c = resolveChoice({ ...base, state: cfix.stateEmpty(), selected: { game_key: "f1_25_2026", platform: "ps5" } });
    expect(c).toMatchObject({ game: "f1_25", platform: "ps5", wheel: { kind: "template", id: "fanatec_gt_dd_pro_wheel" }, preset: "advanced" });
    expect(gameForTelemetryKey(cat, "forza_horizon")).toBe("forza_motorsport");
    expect(gameForTelemetryKey(cat, "f1_24")).toBeNull();
  });

  it("a game with no controls research becomes Other with its name; an unsupported platform falls back", () => {
    const c = resolveChoice({ ...base, state: cfix.stateEmpty(), selected: { game_key: "f1_24", platform: "ps5", label: "F1 24" } });
    expect(c).toMatchObject({ game: "other", gameName: "F1 24" });
    const g = resolveChoice({ ...base, query: parseControlsQuery("game=gt7&platform=pc"), state: cfix.stateEmpty(), selected: null });
    expect(g.platform).toBe("ps5"); // GT7 is not on PC: the query's PC is ignored, the server default PS5 is used
  });

  it("the driver's saved wheel and preset win over the defaults; a beginner without one gets Beginner", () => {
    const s = cfix.stateJames();
    expect(resolveChoice({ ...base, state: s, selected: null })).toMatchObject({ wheel: { kind: "saved", id: "w_1a2b3c4d" }, preset: "advanced" });
    const sam = resolveChoice({ ...base, state: s, selected: null, driverId: 2, skill: "beginner" });
    expect(sam).toMatchObject({ wheel: { kind: "saved", id: "w_1a2b3c4d" }, preset: "beginner" }); // the household's wheel
    const url = resolveChoice({ ...base, state: s, selected: null, query: parseControlsQuery("preset=beginner&wheel=moza_ks") });
    expect(url).toMatchObject({ preset: "beginner", presetFromUrl: true, wheel: { kind: "template", id: "moza_ks" } });
  });

  it("platforms: the game's, narrowed to the wheel's (the GT DD Pro rim has no Xbox)", () => {
    expect(platformsFor(f1, jamesWheel())).toEqual(["ps5", "ps4", "pc"]);
    expect(platformsFor(f1, cfix.templateMcLaren())).toEqual(["ps5", "ps4", "xbox", "pc"]);
    expect(platformsFor(gt7, null)).toEqual(["ps5", "ps4"]);
    expect(gameGroups(cat).controlsOnly.map((g) => g.id)).toEqual(["lmu", "rf2", "ams2", "r3e", "ac_evo"]);
  });
});

describe("layouts and push-to-talk", () => {
  it("a driver's own layout, else the household's, else none", () => {
    const s = cfix.stateJames();
    expect(findLayout(s, 1, "f1_25", "ps5")).toMatchObject({ scope: "household", layout: { id: "l_9f8e7d6c" } });
    expect(findLayout(s, 2, "gt7", "ps5")).toMatchObject({ scope: "driver", layout: { id: "l_0a1b2c3d" } });
    expect(findLayout(s, 1, "gt7", "ps5")).toBeNull();
    expect(findLayout(s, 1, "f1_25", "pc")).toBeNull();
    expect(unusedLayouts(s, [1])).toEqual([s.layouts[1]]); // driver 2 is gone: their GT7 layout is unused, not deleted
    expect(unusedLayouts(s, [1, 2])).toEqual([]);
  });

  it("warns when two layouts for the same game and platform disagree on push-to-talk", () => {
    const s = cfix.stateJames();
    expect(pttConflict(s, "f1_25", "ps5", new Map([[2, "Sam"]]))).toBeNull();
    const sam = structuredClone(s.layouts[0]!);
    sam.id = "l_sam";
    sam.owner = 2;
    sam.assignments = sam.assignments.map((a) => (a.function === "ptt_pitwall" ? { ...a, udp_action: 1 } : a));
    s.layouts.push(sam);
    s.drivers["2"]!.layouts["f1_25:ps5"] = "l_sam";
    expect(pttConflict(s, "f1_25", "ps5", new Map([[2, "Sam"]]))).toBe(
      "The shared layout uses UDP Action 3 for Talk to Pitwall and Sam's uses UDP Action 1. The game keeps one set of buttons per PS5 profile, so one of them won't work.",
    );
  });

  it("the radio's push-to-talk line", () => {
    expect(pttLine(cfix.stateJames().ptt)).toBe("Wheel in F1 25: UDP Action 3 (Circle) and UDP Action 1 · iPad button · Space");
    expect(pttLine(cfix.stateEmpty().ptt)).toBe("Wheel in F1 25: UDP Action 1 · iPad button · Space");
    expect(pttLine(null)).toBe("iPad button · Space");
    expect(udpBit(1)).toBe(0x00100000);
    expect(udpBit(3)).toBe(0x00400000);
    expect(udpBit(12)).toBe(0x80000000);
  });
});

describe("rows", () => {
  it("the recommendation's words; a moved control and a kept one say so; signals in the platform's words", () => {
    const rec = cfix.recF1Advanced();
    const rows = rowsFor(plainAssignments(rec), rec);
    const bb = rows.find((r) => r.key === "brake_bias.inc")!;
    expect(bb).toMatchObject({ label: "Brake bias +", native: "Brake Bias Increase", where: "R2", signal_text: "R2", menu_group: "MFD Shortcuts", evidence: "A" });
    expect(bb.reason).toMatch(/^Brake bias on R2/);
    const moved = rowsFor(assignTo(plainAssignments(rec), "brake_bias", jamesWheel().controls.find((c) => c.id === "face_cross")!, [{ action: "inc", slot: "press" }]), rec);
    expect(moved.find((r) => r.key === "brake_bias.inc")).toMatchObject({ where: "Cross", origin: "driver", reason: "You chose this control." });
    const kept = rowsFor(markKept(plainAssignments(rec), "ptt_pitwall.hold", true), rec);
    expect(kept.find((r) => r.key === "ptt_pitwall.hold")).toMatchObject({ origin: "kept", reason: "You already had this on a button, so Pitwall kept it." });
    // A game-specific signal carries its warning (the blue stick).
    expect(rows.find((r) => r.key === "look.press")?.warnings).toEqual(["Works only if F1 25 reads this wheel's extra buttons (unverified)."]);
    expect(signalText({ kind: "hid_button", value: null, per_slot: { cw: "34" }, evidence: "V", source_ids: [] }, "cw")).toBe("button 34");
    expect(signalText({ kind: "folded", value: "lt/rt", evidence: "V", source_ids: [] })).toBe("LT/RT (shared)");
    // A per-slot "<kind>:<value>" overrides the kind (the backend's Signal.slot).
    const funky = { kind: "game_specific" as const, value: "GSB 1", per_slot: { up: "pad:dpad_up", push: "GSB 1", left: "unknown:" }, evidence: "V" as const, source_ids: [] };
    expect(signalText(funky, "up")).toBe("D-pad up");
    expect(signalText(funky, "push")).toBe("GSB 1 (game-specific)");
    expect(signalText(funky, "left")).toBe("not known");
  });

  it("DRS and the pit limiter share one button (F1 25's own default), and the rows say so", () => {
    const rows = rowsFor(plainAssignments(cfix.recF1Advanced()));
    const shared = sharedSlots(rows);
    expect(shared.get("pit_limiter.press")).toEqual(["DRS / active aero"]);
    expect(shared.get("drs_aero.press")).toEqual(["Pit limiter"]);
  });

  it("a driver's view of a shared layout: their preset, Talk to Pitwall first, the rest under Also on this wheel", () => {
    const s = cfix.stateJames();
    const rows = rowsFor(s.layouts[0]!.assignments);
    const adv = splitRows(rows, f1, "advanced");
    expect(adv.main[0]?.function).toBe("ptt_pitwall");
    expect(adv.also).toEqual([]);
    const beg = splitRows(rows, f1, "beginner");
    expect(beg.main.map((r) => r.function)).toEqual(["ptt_pitwall", "drs_aero", "overtake", "pit_limiter"]);
    expect(new Set(beg.also.map((r) => r.function))).toEqual(new Set(["brake_bias", "ers_mode", "mfd", "radio_menu"]));
  });

  it("GT7: the coloured sticks are set by the game and not editable", () => {
    const rec = cfix.recGt7();
    const rows = rowsFor(plainAssignments(rec), rec, jamesWheel(), "ps5", gt7);
    expect(rows.filter((r) => r.fixed).map((r) => `${r.function}@${r.control_id}`)).toEqual([
      "tc@stick_blue",
      "brake_bias@stick_red",
      "engine_map@stick_green",
      "diff@stick_yellow",
    ]);
  });
});

describe("the wheel diagram: zone stacking", () => {
  function crowded(n: number, zone: Zone, kind: ControlKind = "button"): WheelDef {
    const w = cfix.templateGtDdPro();
    return { ...w, controls: addControls([], kind, n, "Button", ["ps"]).map((c, k) => ({ ...c, zone, order: k })) };
  }

  const WHEELS: [string, WheelDef, readonly LayoutRow[]][] = [
    ["GT DD Pro with the advanced layout", jamesWheel(), rowsFor(plainAssignments(cfix.recF1Advanced()))],
    ["McLaren GT3 V2, empty", cfix.templateMcLaren(), []],
    ["20 buttons in one zone", crowded(20, "right_thumb"), []],
    ["96 controls on a button box", { ...crowded(96, "box"), shape: "box" }, []],
  ];

  for (const [name, wheel, rows] of WHEELS) {
    it(`${name}: markers inside their zone and the view box, never overlapping, legible at 320 px`, () => {
      const g = diagramFor(cat, wheel.shape);
      const { markers } = layoutMarkers({ wheel, rows, reserved: reservedControls(wheel, null, "ps5"), geometry: g, catalog: cat });
      expect(markers.length).toBeGreaterThan(0);
      for (const m of markers) {
        const z = g.zones[m.zone]!;
        expect(m.x, m.id).toBeGreaterThanOrEqual(z.x);
        expect(m.y, m.id).toBeGreaterThanOrEqual(z.y);
        expect(m.x + m.w, m.id).toBeLessThanOrEqual(z.x + z.w + 0.001);
        expect(m.y + m.h, m.id).toBeLessThanOrEqual(z.y + z.h + 0.001);
        expect(m.x + m.w).toBeLessThanOrEqual(g.view_box[0]);
        expect(m.y + m.h).toBeLessThanOrEqual(g.view_box[1]);
      }
      for (let a = 0; a < markers.length; a += 1) for (let b = a + 1; b < markers.length; b += 1) expect(overlaps(markers[a]!, markers[b]!), `${markers[a]!.id} / ${markers[b]!.id}`).toBe(false);
      expect(markerFontPx(g, 320)).toBeGreaterThanOrEqual(10);
    });
  }

  it("zone boxes never overlap each other in any shape (the catalogue's and the dashboard's copy)", () => {
    for (const shape of ["round", "d", "formula", "box"] as const) {
      for (const src of [cat, {}]) {
        const boxes = Object.values(diagramFor(src, shape).zones);
        expect(boxes.length).toBeGreaterThan(10);
        for (let a = 0; a < boxes.length; a += 1) for (let b = a + 1; b < boxes.length; b += 1) expect(overlaps(boxes[a]!, boxes[b]!)).toBe(false);
      }
    }
    // The dashboard's copy is the overlay's geometry.
    expect(cat.diagram).toEqual(DEFAULT_GEOMETRY);
  });

  it("a button box on its own shows every control of a big box, inside its body", async () => {
    const { diagramHeight } = await import("./controls");
    const box = { ...crowded(30, "box"), shape: "box" as const };
    const g = diagramFor(cat, "box");
    const { markers } = layoutMarkers({ wheel: box, rows: [], reserved: new Map(), geometry: g, catalog: cat });
    expect(markers.filter((m) => m.kind === "more")).toEqual([]);
    expect(markers).toHaveLength(30);
    // the empty hub and "not placed" trays under the body are not drawn
    expect(diagramHeight(g, markers)).toBeLessThan(g.view_box[1]);
  });

  it("zone grids: the largest cells that fit, else as many minimum cells as fit and +n", () => {
    expect(zoneGrid({ x: 270, y: 108, w: 96, h: 56 }, 4)).toEqual({ cols: 2, rows: 2, cw: 44.5, ch: 22, cap: 4 });
    expect(zoneGrid({ x: 270, y: 108, w: 96, h: 56 }, 1)).toMatchObject({ cols: 1, rows: 1, cw: MARKER.maxW, ch: MARKER.maxH });
    expect(zoneGrid({ x: 0, y: 92, w: 30, h: 88 }, 2)).toMatchObject({ cols: 1, rows: 2, cw: 26, cap: 2 });
    expect(zoneGrid({ x: 270, y: 108, w: 96, h: 56 }, 20)).toMatchObject({ cols: 3, rows: 3, cap: 9 });
    // Five controls: two wide columns of shorter pills beat three narrow ones (labels stay readable).
    expect(zoneGrid({ x: 270, y: 108, w: 96, h: 56 }, 5)).toMatchObject({ cols: 2, rows: 3, cw: 44.5 });
    expect(fitText("PITWALL", 44.5)).toEqual({ text: "PITWALL", squeeze: true });
    expect(fitText("BB+", 44.5)).toEqual({ text: "BB+", squeeze: false });
    expect(fitText("Small left hub button", 44.5).text).toMatch(/…$/);
  });

  it("a crowded zone shows its first controls and +n; marker words for pairs, turns and shared buttons", () => {
    const round = diagramFor(cat, "round");
    const { markers } = layoutMarkers({ wheel: crowded(20, "right_thumb"), rows: [], reserved: new Map(), geometry: round, catalog: cat });
    expect(markers.filter((m) => m.zone === "right_thumb")).toHaveLength(9);
    expect(markers.find((m) => m.kind === "more")?.text).toBe("+12");
    const rows = rowsFor(plainAssignments(cfix.recF1Advanced()));
    const m = layoutMarkers({ wheel: jamesWheel(), rows, reserved: reservedControls(jamesWheel(), cfix.recF1Advanced(), "ps5"), geometry: round, catalog: cat }).markers;
    const by = (id: string) => m.find((x) => x.control_id === id)!;
    expect(by("face_circle")).toMatchObject({ text: "PITWALL", kind: "assigned" });
    expect(by("r2")).toMatchObject({ text: "BB+", kind: "assigned" });
    expect(by("face_triangle").text).toBe("DRS·PIT");
    expect(by("menu_stick").text).toBe("MFD");
    expect(by("paddle_right").kind).toBe("reserved");
    expect(by("ps").kind).toBe("reserved");
    // An encoder carrying both halves of a pair turns: ↻ BB.
    const mcl = cfix.templateMcLaren();
    const enc = mcl.controls.find((c) => c.id === "enc11")!;
    const pair = layoutRows({ assignments: assignTo([], "brake_bias", enc, [{ action: "inc", slot: "cw" }, { action: "dec", slot: "ccw" }]), rec: null, catalog: cat, game: f1, wheel: mcl, platform: "pc" });
    const em = layoutMarkers({ wheel: mcl, rows: pair, reserved: new Map(), geometry: round, catalog: cat }).markers.find((x) => x.control_id === "enc11");
    expect(em).toMatchObject({ text: "↻ BB", turn: true });
  });

  it("counts-only templates come out unplaced: in the diagram's tray (the first ones and +n), all listed", () => {
    const moza = cfix.templateMozaKs();
    const { markers, unplaced } = layoutMarkers({ wheel: moza, rows: [], reserved: new Map(), geometry: diagramFor(cat, "round"), catalog: cat });
    expect(new Set(markers.map((m) => m.zone))).toEqual(new Set(["unplaced"]));
    expect(markers.at(-1)?.kind).toBe("more");
    expect(unplaced).toHaveLength(moza.controls.length);
    // Without a tray in the geometry nothing unplaced is drawn.
    const g = diagramFor(cat, "round");
    const noTray = { ...g, zones: { ...g.zones, unplaced: undefined } };
    expect(layoutMarkers({ wheel: moza, rows: [], reserved: new Map(), geometry: noTray, catalog: cat }).markers).toEqual([]);
    const placed = moveControl(moza.controls, "c_1", "right_thumb");
    expect(placed.find((c) => c.id === "c_1")).toMatchObject({ zone: "right_thumb", order: 0 });
  });

  it("uses the catalogue's geometry when it has one, the dashboard's copy otherwise; bad boxes are dropped", () => {
    const own = { viewbox: [300, 200] as [number, number], shapes: { round: { outline: "M0 0", zones: { right_thumb: [0, 0, 300, 200] as [number, number, number, number], left_thumb: [1, 2] as unknown as [number, number, number, number] } } } };
    expect(diagramFor({ diagram: own }, "round")).toEqual({ view_box: [300, 200], outline: ["M0 0"], zones: { right_thumb: { x: 0, y: 0, w: 300, h: 200 } } });
    expect(diagramFor({ diagram: own }, "formula").view_box).toEqual([300, 200]); // an unknown shape falls back to round
    expect(diagramFor({}, "formula").outline[0]).toMatch(/^M60 40/);
  });
});

describe("which free controls fit a function", () => {
  const mcl = cfix.templateMcLaren();
  const zones = cat.zones;
  const opts = (fnId: string, platform: PlatformId, wheel: WheelDef = mcl, action: string | null = null, rows: LayoutRow[] = []) =>
    slotOptions({
      fn: cat.functions.find((f) => f.id === fnId)!,
      gfn: f1.functions.find((f) => f.function === fnId),
      action,
      wheel,
      platform,
      rows,
      reserved: reservedControls(wheel, null, platform),
      zones,
      game: "F1 25",
    });

  it("a pair: encoder turns, funky turns and rotary switches in ENC mode, as whole pairs", () => {
    const ids = opts("brake_bias", "pc").map((o) => o.id);
    expect(ids).toContain("enc11:cw+ccw");
    expect(ids).toContain("mps18:cw+ccw");
    expect(ids).toContain("funky5:up+down");
    const enc = opts("brake_bias", "pc").find((o) => o.id === "enc11:cw+ccw")!;
    expect(enc.slots).toEqual([
      { action: "inc", slot: "cw" },
      { action: "dec", slot: "ccw" },
    ]);
  });

  it("one half of a pair: any single press, including one encoder direction", () => {
    const ids = opts("brake_bias", "pc", mcl, "inc").map((o) => o.id);
    expect(ids).toContain("b3:press");
    expect(ids).toContain("enc11:cw");
  });

  it("Xbox: the McLaren rotary switches send nothing, so they are never offered", () => {
    expect(opts("brake_bias", "xbox").some((o) => o.control.id.startsWith("mps"))).toBe(false);
    expect(controlSlots(mcl.controls.find((c) => c.id === "mps18")!, "xbox")).toEqual([]);
  });

  it("Talk to Pitwall: only plain buttons with their own signal, never an encoder, a folded signal or a gear paddle", () => {
    const ps = opts("ptt_pitwall", "ps5");
    expect(ps.every((o) => o.control.kind === "button")).toBe(true);
    expect(ps.map((o) => o.control.id)).not.toContain("b10"); // the PS button is a console button
    expect(ps.map((o) => o.control.id)).not.toContain("paddles_l");
    const folded: WheelDef = { ...mcl, controls: mcl.controls.map((c) => (c.id === "b3" ? { ...c, signals: { ...c.signals, xbox: { kind: "folded", value: "a", evidence: "V", source_ids: [] } } } : c)) };
    expect(opts("ptt_pitwall", "xbox", folded).map((o) => o.control.id)).not.toContain("b3");
  });

  it("overtake (hold): presses and pushes only, never a turn", () => {
    const o = opts("overtake", "ps5");
    expect(o.length).toBeGreaterThan(0);
    expect(o.some((x) => x.slots.some((s) => s.slot === "cw" || s.slot === "ccw"))).toBe(false);
  });

  it("the MFD wants all four directions of one stick", () => {
    const o = opts("mfd", "ps5");
    expect(o.map((x) => x.id)).toContain("funky5:dirs");
    expect(o.every((x) => x.slots.length === 4)).toBe(true);
  });

  it("slots used by another function are not free; the one it is on now comes first", () => {
    const rows = rowsFor(plainAssignments(cfix.recF1Advanced()));
    const o = slotOptions({
      fn: cat.functions.find((f) => f.id === "overtake")!,
      gfn: f1.functions.find((f) => f.function === "overtake"),
      action: null,
      wheel: jamesWheel(),
      platform: "ps5",
      rows,
      reserved: reservedControls(jamesWheel(), cfix.recF1Advanced(), "ps5"),
      zones,
      game: "F1 25",
    });
    expect(o[0]).toMatchObject({ id: "face_square:press", current: true });
    expect(o.map((x) => x.id)).not.toContain("face_circle:press"); // Talk to Pitwall is there
    expect(o.some((x) => x.control.id === "paddle_left" || x.control.id === "ps")).toBe(false);
  });

  it("a tap on a marker lists only functions the game allows mid-race and lets you bind", () => {
    const sq = jamesWheel().controls.find((c) => c.id === "face_square")!;
    const fns = new Set(functionOptions(sq, f1, cat, "ps5", []).map((o) => o.function));
    expect(fns.has("ptt_pitwall")).toBe(true);
    expect(fns.has("tc")).toBe(false); // pause menu in F1 25
    expect(fns.has("stability")).toBe(false);
    const g7 = new Set(functionOptions(sq, gt7, cat, "ps5", []).map((o) => o.function));
    expect(g7.has("ptt_pitwall")).toBe(false); // GT7 sends no buttons
    expect(g7.has("abs")).toBe(false);
  });

  it("assigning keeps the other rows and the test result only when the control is unchanged", () => {
    const base = cfix.stateJames().layouts[0]!.assignments;
    const r2 = jamesWheel().controls.find((c) => c.id === "r2")!;
    const same = assignTo(base, "brake_bias", r2, [{ action: "inc", slot: "press" }]);
    expect(same.find((a) => a.key === "brake_bias.inc")?.check?.result).toBe("effect_seen");
    const cross = jamesWheel().controls.find((c) => c.id === "face_cross")!;
    const moved = assignTo(base, "brake_bias", cross, [{ action: "inc", slot: "press" }]);
    expect(moved.find((a) => a.key === "brake_bias.inc")).toMatchObject({ control_id: "face_cross", origin: "driver", check: null });
    expect(moved).toHaveLength(base.length);
    expect(sameAssignments(base, same)).toBe(false); // origin changed to driver
    expect(sameAssignments(base, [...base].reverse())).toBe(true);
    const ptt = assignTo(base, "ptt_pitwall", cross, [{ action: "hold", slot: "press" }]);
    expect(ptt.find((a) => a.key === "ptt_pitwall.hold")?.udp_action).toBe(3); // keeps its UDP Action
  });
});

describe("Map it", () => {
  it("draft steps follow the game's menu groups, print the game's names verbatim and the physical words", () => {
    const rows = rowsFor(plainAssignments(cfix.recF1Advanced()));
    const g = draftGuide(rows, f1);
    expect(g.where).toBe("Controls > [your wheel's preset]");
    expect(g.where_evidence).toBe("V");
    expect(stepGroups(g.steps).map((x) => x.group)).toEqual(["Control Scheme", "MFD Shortcuts", "UDP Custom Actions"]);
    expect(g.steps.map((s) => s.n)).toEqual(g.steps.map((_, k) => k + 1));
    const bb = g.steps.find((s) => s.label === "Brake bias +")!;
    expect(bb).toMatchObject({ native: "Brake Bias Increase", physical: "Press R2", group: "MFD Shortcuts" });
    const ptt = g.steps.at(-1)!;
    expect(ptt).toMatchObject({ native: "UDP Action 1", physical: "Press CIRCLE", group: "UDP Custom Actions" });
    expect(g.outro).toEqual(["Open Test and press each one once."]);
  });

  it("GT7 leaves out what the game fixes; Other uses the generic steps", () => {
    const rec = cfix.recGt7();
    const g = draftGuide(rowsFor(plainAssignments(rec), rec, jamesWheel(), "ps5", gt7), gt7);
    expect(g.steps.some((s) => ["tc", "Traction control"].includes(s.label))).toBe(false);
    expect(g.outro).toEqual(["Check each one on track."]);
    const other = draftGuide([], null, cat.other_game.steps);
    expect(other.where).toBe("the game's Controls screen");
    expect(other.intro).toEqual(cat.other_game.steps);
  });

  it("physical words for each kind of slot", () => {
    const c = (label: string, kind: ControlKind = "button") => ({ label, kind }) as Pick<WheelControl, "label" | "kind">;
    expect(physicalText(c("Triangle"), "press")).toBe("Press TRIANGLE");
    expect(physicalText(c("Left encoder", "encoder"), "cw")).toBe("Turn the LEFT ENCODER clockwise");
    expect(physicalText(c("Left encoder", "encoder"), "ccw")).toBe("Turn the LEFT ENCODER anticlockwise");
    expect(physicalText(c("Menu stick", "dpad_hat"), "up")).toBe("Push the MENU STICK up");
    expect(physicalText(c("Menu stick", "dpad_hat"), "push")).toBe("Push the MENU STICK in");
    expect(physicalText(c("Rotary switch", "multi_position"), "pos_3")).toBe("Set the ROTARY SWITCH to position 3");
    expect(physicalText(c("Ignition", "toggle_latching"), "on")).toBe("Flick the IGNITION on");
    expect(physicalText(null, null)).toBe("Use the MFD");
  });
});

describe("test words, copy text and the wheel editor", () => {
  it("presses in words; replayed, synthetic and this computer's presses are tagged; the stick noise can be hidden", async () => {
    const { bitName, isNoise, originTag, testSummary, testItemChip } = await import("./controls");
    const [down, up] = cfix.testRunning().feed;
    expect(pressText(down!)).toBe("UDP Action 3: pressed");
    expect(pressText(up!)).toBe("UDP Action 3: released");
    const p = { pressed: ["Cross or A", "Right Stick Up"], released: ["Right Stick Down"], origin: "live" };
    expect(pressText(p, "ps5", false)).toBe("Cross: pressed");
    expect(pressText(p, "xbox")).toBe("A: pressed · Right Stick Up: pressed · Right Stick Down: released");
    expect(bitName("Options or Menu", "pc")).toBe("Options or Menu");
    expect(isNoise({ pressed: ["Right Stick Up"], released: ["Right Stick Down"] })).toBe(true);
    expect(isNoise(p)).toBe(false);
    expect(originTag("loopback")).toBe("THIS COMPUTER");
    const items = [{ state: "detected" }, { state: "timeout" }, { state: "skipped" }, { state: "skipped" }] as Parameters<typeof testSummary>[0]["items"];
    expect(testSummary({ items })).toBe("1 seen · 1 not seen · 2 skipped");
    expect(testItemChip({ state: "detected", saved: false }, false).label).toBe("Seen here (not saved)");
    expect(testItemChip({ state: "detected", saved: true }, true).label).toBe("Seen by Pitwall");
  });

  it("copy text: header, research-only line, rows with the game's names, the lists", () => {
    const rec = cfix.recF1Advanced();
    const t = layoutText({ header: "Controls for James · F1 25 · PS5 · GT DD Pro wheel · Advanced", rows: rowsFor(plainAssignments(rec), rec), rec, game: "F1 25", saved: false });
    expect(t).toContain("Research only: nothing here is validated on your rig.");
    expect(t).toContain("Not saved yet.");
    expect(t).toContain("  Talk to Pitwall: Circle (UDP Action 1)  [F1 25: UDP Action 1]");
    expect(t).toContain("  Brake bias +: R2  [F1 25: Brake Bias Increase]");
    expect(t).toContain("Can't change while driving in F1 25:");
    expect(t).toContain("Not on your wheel:");
    expect(t).not.toMatch(/\bundefined\b|\bnull\b|NaN/);
    const g = cfix.recGt7();
    expect(layoutText({ header: "x", rows: [], rec: g, game: "GT7", saved: true })).toContain("Talk to Pitwall: GT7 doesn't send wheel button presses");
  });

  it("the quick form adds numbered, unplaced controls you entered (H), with an unknown signal", () => {
    const c = addControls([], "encoder", 2, "Encoder", ["pc", "ps"]);
    expect(c.map((x) => [x.id, x.label, x.zone, x.evidence, x.signals.pc?.kind])).toEqual([
      ["c_1", "Encoder 1", "unplaced", "H", "unknown"],
      ["c_2", "Encoder 2", "unplaced", "H", "unknown"],
    ]);
    expect(addControls(c, "encoder", 1, "Encoder", ["pc"]).at(-1)?.label).toBe("Encoder 3");
    expect(addControls([], "button", 200, "Button", ["pc"])).toHaveLength(96);
  });
});

describe("Identify", () => {
  it("a single live pad bit becomes the control's signal (seen), replays and UDP Actions never do", async () => {
    const { bitToPad, identifiedSignal } = await import("./controls");
    expect(bitToPad("L2 or LT", "ps5")).toBe("l2");
    expect(bitToPad("L2 or LT", "xbox")).toBe("lt");
    expect(bitToPad("UDP Action 3", "ps5")).toBeNull();
    expect(bitToPad("Cross or A", "pc")).toBeNull();
    // the same pad button on its own twice, live from the console; the Right Stick noise in between is ignored
    const live = [
      { pressed: ["L1 or LB"], origin: "live", t_unix: 9 },
      { pressed: ["Right Stick Up"], origin: "live", t_unix: 9.5 },
      { pressed: ["L1 or LB"], origin: "live", t_unix: 10 },
    ];
    expect(identifiedSignal(live, "ps5")).toEqual({
      bits: ["L1 or LB"],
      signal: { kind: "pad", value: "l1", evidence: "seen", source_ids: [], seen: { t_unix: 10, bits: ["L1 or LB"], game: "f1_25", platform: "ps5" } },
    });
    expect(identifiedSignal(live.slice(0, 1), "ps5")).toBeNull(); // once is not enough (backing out of a menu)
    expect(identifiedSignal(live.map((p) => ({ ...p, origin: "replay" })), "ps5")).toBeNull();
    expect(identifiedSignal(live.map((p) => ({ ...p, local: true })), "ps5")).toBeNull(); // pitwall send on this computer
    expect(identifiedSignal([...live, { pressed: ["R1 or RB"], origin: "live", t_unix: 11 }], "ps5")).toBeNull(); // two controls
    expect(identifiedSignal([{ pressed: ["Cross or A", "Circle or B"], origin: "live", t_unix: 8 }, ...live.slice(2)], "ps5")).toBeNull();
    expect(identifiedSignal([{ pressed: ["UDP Action 3"], origin: "live", t_unix: 10 }, { pressed: ["UDP Action 3"], origin: "live", t_unix: 11 }], "ps5")).toBeNull();
  });
});

describe("refinements from the visual check", () => {
  it("a warning every row carries is said once; a row's own warnings skip what its reason says", async () => {
    const { commonWarnings, ownWarnings } = await import("./controls");
    const rec = cfix.recF1Advanced();
    const rows = rowsFor(plainAssignments(rec), rec).filter((r) => r.control_id);
    const common = commonWarnings(rows);
    expect(common).toEqual(["The game's preset for this wheel may already use this button (EA doesn't publish the GT DD Pro defaults)."]);
    expect(ownWarnings(rows.find((r) => r.key === "look.press")!, common)).toEqual(["Works only if F1 25 reads this wheel's extra buttons (unverified)."]);
    expect(ownWarnings(rows.find((r) => r.key === "brake_bias.inc")!, common)).toEqual([]);
    const g = cfix.recGt7();
    const fixed = rowsFor(plainAssignments(g), g, jamesWheel(), "ps5", gt7).find((r) => r.fixed)!;
    expect(ownWarnings(fixed, [])).toEqual([]); // "Which colour does what is community-reported." is in its reason
    expect(commonWarnings([rows[0]!])).toEqual([]);
  });

  it("reserved markers say what they are kept for in a word", async () => {
    const { reservedShort, markerLabel } = await import("./controls");
    const by = (id: string) => jamesWheel().controls.find((c) => c.id === id)!;
    expect(reservedShort(by("paddle_left"))).toBe("Gear");
    expect(reservedShort(by("tuning"))).toBe("Menu");
    expect(reservedShort(by("ps"))).toBe("PS");
    expect(reservedShort(by("hub_left"))).toBe(markerLabel(by("hub_left").label)); // its own name, not "Console" twice
    expect(markerLabel("Yellow-ring stick")).toBe("YEL");
    expect(markerLabel("Blue stick")).toBe("BLU");
  });

  it("the drawing stops above empty trays, and keeps them when something is in one", async () => {
    const { diagramHeight } = await import("./controls");
    const g = diagramFor(cat, "round");
    const james = layoutMarkers({ wheel: jamesWheel(), rows: [], reserved: new Map(), geometry: g, catalog: cat }).markers;
    expect(diagramHeight(g, james)).toBe(244);
    const moza = layoutMarkers({ wheel: cfix.templateMozaKs(), rows: [], reserved: new Map(), geometry: g, catalog: cat }).markers;
    expect(diagramHeight(g, moza)).toBe(300);
  });

  it("a platform the wheel doesn't have is swapped, unless the URL asked for it", async () => {
    const { fitToWheel } = await import("./controls");
    const c = resolveChoice({ query: parseControlsQuery(""), state: cfix.stateEmpty(), catalog: cat, selected: null, driverId: 1, skill: "advanced" });
    expect(c.platform).toBe("ps5");
    expect(fitToWheel(c, f1, cfix.templateMozaKs(), false).platform).toBe("pc");
    expect(fitToWheel(c, f1, cfix.templateMozaKs(), true).platform).toBe("ps5");
    expect(fitToWheel(c, f1, jamesWheel(), false)).toBe(c);
  });

  it("choices list plain signals before game-specific ones, and the slot a function shares stays offered", () => {
    const rows = rowsFor(plainAssignments(cfix.recF1Advanced()));
    const opts = slotOptions({
      fn: cat.functions.find((f) => f.id === "drs_aero")!,
      gfn: f1.functions.find((f) => f.function === "drs_aero"),
      action: "press",
      wheel: jamesWheel(),
      platform: "ps5",
      rows,
      reserved: reservedControls(jamesWheel(), cfix.recF1Advanced(), "ps5"),
      zones: cat.zones,
      game: "F1 25",
    });
    expect(opts[0]).toMatchObject({ id: "face_triangle:press", current: true }); // shared with the pit limiter, still its own
    const kinds = opts.slice(1).map((o) => o.control.signals.ps?.kind);
    expect(kinds.indexOf("game_specific")).toBeGreaterThan(kinds.lastIndexOf("pad"));
  });
});

describe("the list: one row per function", () => {
  it("groups a function's actions (a pair, the MFD's directions) and words each control button", async () => {
    const { groupRows, actionWhere } = await import("./controls");
    const rows = rowsFor(plainAssignments(cfix.recF1Advanced()));
    const groups = groupRows(rows, cat);
    expect(groups.map((g) => g.function)).toEqual([...new Set(rows.map((r) => r.function))]);
    const bb = groups.find((g) => g.function === "brake_bias")!;
    expect(bb.label).toBe("Brake bias");
    expect(bb.rows.map(actionWhere)).toEqual(["+ R2", "\u2212 L2"]);
    expect(groups.find((g) => g.function === "mfd")!.rows.map(actionWhere)).toEqual(["Menu stick up", "Menu stick down", "Menu stick left", "Menu stick right"]);
  });
});

describe("review fixes: any wheel, the game's own words, honest warnings", () => {
  it("the game's name for one action, its bracketed note on a second line, no research tokens", async () => {
    const { nativeFor, splitName, stripTokens } = await import("./controls");
    expect(splitName("Activate/Deactivate DRS/S Mode (2026 cars: Active Aero)")).toEqual({ name: "Activate/Deactivate DRS/S Mode", note: "2026 cars: Active Aero" });
    expect(splitName("Pit Limiter")).toEqual({ name: "Pit Limiter", note: null });
    const mfd = f1.functions.find((x) => x.function === "mfd")!;
    expect(nativeFor(mfd, "down").name).toBe("MFD Menu Down"); // not "MFD + MFD Menu Up/Down/Left/Right; panel shortcuts (...)"
    expect(nativeFor({ ...mfd, native_found: false }, "down")).toEqual({ name: "", note: null }); // RaceRoom: no name claimed
    const bb = f1.functions.find((x) => x.function === "brake_bias")!;
    expect(nativeFor(bb, "inc")).toEqual({ name: "Brake Bias Increase", note: null }); // "(MFD shortcut)" is the step's group
    expect(stripTokens("the exact screen names are not re-checked [U]")).toBe("the exact screen names are not re-checked");
  });

  it("warnings that differ only by their control are said once, in the plural, above the list", async () => {
    const { commonWarnings, ownWarnings, signalWarnings, warningFamily } = await import("./controls");
    const unknown = { kind: "unknown" as const, value: null, evidence: "U" as const, source_ids: [] };
    const [a] = signalWarnings(unknown, "F1 25", "Cross", "pc");
    const [b] = signalWarnings(unknown, "F1 25", "Circle", "pc");
    expect(a).toBe("What Cross sends on PC isn't known: check it in the game.");
    expect(signalWarnings(unknown, "F1 25", "Menu stick", "ps5", "push")[0]).toBe("What Menu stick sends when pushed in on PlayStation isn't known: check it in the game.");
    expect(warningFamily(a!)).toBe(warningFamily(b!));
    const rows = [{ warnings: [a!] }, { warnings: [b!] }, { warnings: [a!] }];
    const common = commonWarnings(rows);
    expect(common).toEqual(["What these controls send on PC isn't known: check each one in the game."]);
    expect(ownWarnings({ warnings: [a!], reason: "" }, common)).toEqual([]);
  });

  it("the game's own defaults are not steps of Map it, and are said once", () => {
    const rec = cfix.recF1Advanced();
    const rows = rowsFor(plainAssignments(rec), rec).map((r) => (r.function === "drs_aero" ? { ...r, origin: "game_default" as const } : r));
    expect(rows.some((r) => r.function === "drs_aero" && r.control_id)).toBe(true);
    const g = draftGuide(rows, f1);
    expect(g.steps.some((s) => s.label.startsWith("DRS"))).toBe(false);
    expect(g.steps.length).toBe(rows.filter((r) => r.control_id && !r.fixed && r.function !== "drs_aero").length);
    expect(g.intro).toContain("Already set by F1 25 for this wheel (its own defaults): DRS / active aero. Nothing to change there.");
  });

  it("the wheel picker: plain names, what the research knows, PC-only marks, search", async () => {
    const { templateKnows } = await import("./controls");
    const { notFor, matchesWheel } = await import("../../pages/setup/controls/ChoiceSheet");
    expect(templateKnows({ completeness: "full", controls_total: 17, controls_placed: 2 })).toBe("Buttons and signals known, positions not");
    expect(templateKnows({ completeness: "full", controls_total: 19, controls_placed: 19 })).toBe("Buttons and signals known, positions too");
    expect(templateKnows({ completeness: "counts" })).toBe("Only how many controls");
    expect(notFor({ signal_platforms: ["pc"] }, "ps5")).toBe("PC only");
    expect(notFor({ signal_platforms: ["ps", "pc"] }, "ps5")).toBeNull();
    expect(notFor({}, "ps5")).toBeNull();
    const t = { brand: "Thrustmaster", name: "T248 (PS5/PS4/PC) and T248X (Xbox/PC) - Thrustmaster's 'hybrid' wheel family [A]", display_name: "T248 / T248X" };
    expect(matchesWheel(t, "t248")).toBe(true);
    expect(matchesWheel(t, "thrustmaster t248x")).toBe(true);
    expect(matchesWheel(t, "g923")).toBe(false);
  });
});
