// Technique view models (feat/technique spec §9): Compare's default focus, markers, muted brake rows under braking
// assist, Corners slip totals, which setup suggestions can be tried (driving symptoms never get one), reasons.
import { describe, expect, it } from "vitest";
import type { SetupExperiment } from "../endpoints/carsetup";
import { densityFor } from "../review/density";
import { driver } from "../review/testkit";
import { offsetDomain, offsetRows, offsetTick, pointTicks, tickLabels } from "./chart";
import { techniqueDensity } from "./density";
import { techniqueFixtures } from "./testkit";
import {
  ALREADY_TRYING,
  availabilityNotes,
  biggestOffset,
  brakingAssistNote,
  compareWindowM,
  cornerAtCursor,
  defaultFocus,
  FORMAT_UNKNOWN,
  markerItems,
  rowMuted,
  shownNotes,
  slipTotals,
  symptomViews,
  unavailableReasons,
  valueForFormat,
  zoomPoints,
} from "./view";
import { fixtures as setupFixtures } from "../setup/fixtures";

const setupCatalog = () => setupFixtures.catalog();

describe("Compare focus and markers", () => {
  it("focus: the corner under the cursor, else the first marker's, else the biggest loss", () => {
    const cmp = techniqueFixtures.austriaCompare();
    expect(defaultFocus(cmp, 3790)).toBe("T6"); // inside T9 Rindt Kurve's window
    expect(defaultFocus(cmp, null)).toBe("T3"); // marker 1: T4 apex
    expect(defaultFocus({ ...cmp, markers: [] }, null)).toBe("T3"); // biggest time loss (+0.12 s)
    expect(defaultFocus({ ...cmp, corners: cmp.corners.map((c) => ({ ...c, incident: c.corner === "T3" })), markers: [] }, null)).toBe("T4");
    expect(defaultFocus(null)).toBeNull();
  });

  it("the corner under the cursor follows the cursor (Compare's corner table moves it); none on a straight", () => {
    const cmp = techniqueFixtures.austriaCompare();
    expect(cornerAtCursor(cmp, 3790)).toBe("T6");
    for (const c of cmp.corners) {
      if (c.incident || c.points.apex == null) continue;
      expect(cornerAtCursor(cmp, c.points.apex), c.corner).toBe(c.corner); // its own apex always selects it
    }
    expect(cornerAtCursor(cmp, -500)).toBeNull();
    expect(cornerAtCursor(cmp, null)).toBeNull();
    expect(cornerAtCursor({ corners: cmp.corners.map((c) => ({ ...c, incident: true })) }, 3790)).toBeNull();
  });

  it("with no line marker, a corner with something to say (a lock-up) comes before the biggest time loss", () => {
    const cmp = techniqueFixtures.austriaCompare();
    const quiet = cmp.corners.map((c) => ({ ...c, notes: [] }));
    const lock = { metric: "lockup" as const, lap_value: 1, ref_value: 0, delta: 1, unit: "events", notable: true, muted: false, laps: null, laps_total: null, text: "Locked a wheel 1 time under braking vs 0 on your reference.", text_simple: "You locked a wheel under braking." };
    const last = quiet[quiet.length - 1]!;
    const corners = quiet.map((c) => (c === last ? { ...c, notes: [lock], time_delta_s: -0.05 } : c));
    expect(defaultFocus({ corners, markers: [] }, null)).toBe(last.corner);
    expect(defaultFocus({ corners: quiet, markers: [] }, null)).toBe("T3"); // nothing to say anywhere: the biggest loss
  });

  it("markers are numbered in the API's order with its sentence (simple wording for beginners)", () => {
    const cmp = techniqueFixtures.austriaCompare();
    const m = markerItems(cmp, false);
    expect(m.map((x) => x.n)).toEqual([1, 2, 3]);
    expect(m[0]).toMatchObject({ corner: "T3", point: "apex", text: "T4 apex: 1.8 m wider than your reference" });
    expect(m[0]!.label).toBe("1: T4 apex: 1.8 m wider than your reference");
    expect(markerItems(cmp, true)[0]!.text).toBe("You ran wider at the apex of T4");
  });

  it("zoom window and points; biggest offset", () => {
    const t4 = techniqueFixtures.austriaCompare().corners.find((c) => c.corner === "T3")!;
    const w = compareWindowM(t4)!;
    expect(Math.abs(w[0] - (t4.points.turn_in! - 40))).toBeLessThan(2); // the API's window, on its 2 m grid
    expect(Math.abs(w[1] - (t4.points.track_out! + 40))).toBeLessThan(2);
    expect(compareWindowM({ window: null, points: { turn_in: null, apex: 500, track_out: null } })).toEqual([400, 600]);
    expect(compareWindowM({ window: null, points: { turn_in: null, apex: null, track_out: null } })).toBeNull();
    expect(zoomPoints(t4).map((p) => p.label)).toEqual(["Turn-in", "Apex", "Track-out"]);
    expect(biggestOffset(t4)).toEqual({ point: "apex", offset: -1.8 });
  });
});

describe("brake and throttle rows", () => {
  it("braking assist on: brake rows are muted with the API's assist sentence; throttle rows are not", () => {
    const { assists } = techniqueFixtures.austriaCompare();
    expect(rowMuted("release", assists)).toBe(true);
    expect(rowMuted("brake_peak", assists)).toBe(true);
    expect(rowMuted("coast", assists)).toBe(false);
    expect(rowMuted("throttle_pickup", assists)).toBe(false);
    expect(rowMuted("release", { braking_assist: 0 })).toBe(false);
    expect(brakingAssistNote(assists)).toBe(
      "Braking assist is on (medium): the game adds its own braking, so these brake figures are not all yours.",
    );
    expect(brakingAssistNote({ ...assists, braking_assist: 0 })).toBeNull();
  });

  it("a muted note greys its row even without the assist flag; muted notes are not listed", () => {
    const t4 = techniqueFixtures.austriaCompare().corners.find((c) => c.corner === "T3")!;
    expect(rowMuted("release", { braking_assist: 0 }, t4.notes)).toBe(true);
    expect(shownNotes(t4.notes).map((n) => n.metric)).toEqual(["coast", "throttle_pickup"]);
  });
});

describe("Corners: slip over the session", () => {
  it("ABS on says there is no lock-up data; wheelspin counted with traction control", () => {
    const s = techniqueFixtures.austriaSession();
    const t9 = s.corners.find((c) => c.corner === "T6")!;
    expect(slipTotals(t9)).toEqual({ lockups: "ABS on: no lock-up data", wheelspin: "Wheelspin on 1 of 8 laps (traction control on)" });
    const t10 = s.corners.find((c) => c.corner === "T7")!;
    expect(slipTotals(t10).lockups).toBeNull(); // no braking there: not applicable
  });

  it("a game without slip data: both unknown", () => {
    const c = techniqueFixtures.gt7Session().corners[0]!;
    expect(slipTotals(c)).toEqual({ lockups: null, wheelspin: null });
  });
});

describe("setup suggestions", () => {
  const exps = (): SetupExperiment[] => [
    {
      id: 2,
      game: "f1_25",
      track_id: "f1:13",
      car_id: null,
      created_unix: 1,
      hypothesis: "",
      parameter: "rear_arb",
      from_value: 10,
      to_value: 20,
      status: "running",
      before_session_id: "df149ca2d149",
      after_session_id: null,
      before_metrics: null,
      after_metrics: null,
      conclusion: null,
    },
  ];

  it("car symptoms carry ranked suggestions; driving symptoms never do", () => {
    const b = techniqueFixtures.suzukaBalance();
    const v = symptomViews(b.symptoms, b.setup);
    expect(v.car.map((x) => x.symptom.id)).toEqual(["mid-understeer-car", "exit-oversteer-car"]);
    expect(v.driving.map((x) => x.id)).toEqual(["entry-understeer-driving"]);
    expect(v.car[0]!.suggestions.map((x) => [x.parameter, x.from_value, x.to_value])).toEqual([
      ["front_arb", 15, 13],
      ["front_wing", 10, 12],
    ]);
    expect(v.car[1]!.suggestions.find((x) => x.parameter === "rear_suspension")!.blockedNow).toMatch(/already at its minimum/);
  });

  it("an experiment already open from this session on the parameter blocks it ('already in your experiments')", () => {
    const b = techniqueFixtures.suzukaBalance();
    const v = symptomViews(b.symptoms, b.setup, { experiments: exps(), sid: "df149ca2d149" });
    expect(v.car[1]!.suggestions.find((x) => x.parameter === "rear_arb")!.blockedNow).toBe(ALREADY_TRYING);
    expect(v.car[0]!.suggestions.find((x) => x.parameter === "front_arb")!.blockedNow).toBeNull();
    // another session's experiment does not
    const other = symptomViews(b.symptoms, b.setup, { experiments: exps(), sid: "another" });
    expect(other.car[1]!.suggestions.find((x) => x.parameter === "rear_arb")!.blockedNow).toBeNull();
  });

  it("synthetic sessions: shown, never offered as experiments", () => {
    const b = techniqueFixtures.suzukaBalance();
    const v = symptomViews(b.symptoms, b.setup, { synthetic: true });
    for (const s of v.car) for (const x of s.suggestions) expect(x.blockedNow).toBeTruthy();
  });

  it("the server could not tell the car format: the page's chosen format sizes the change (snapped to its range)", () => {
    const catalog = setupCatalog();
    const params = new Map(catalog.parameters.map((p) => [p.key, p]));
    const b = techniqueFixtures.suzukaBalance();
    const blocked = "The car format is unknown (2025 or 2026 car): choose it in Setup › Car setup.";
    const setup = {
      car_format: null,
      suggestions: b.setup!.suggestions.map((x) => ({
        ...x,
        to_value: null,
        blocked,
        hypothesis: x.hypothesis.replace(/ → [^:]+:/, " → unknown:"),
      })),
    };
    const none = symptomViews(b.symptoms, setup, { params });
    expect(none.car[0]!.suggestions[0]!).toMatchObject({ blockedNow: FORMAT_UNKNOWN, formatUnknown: true });
    const v = symptomViews(b.symptoms, setup, { params, carFormat: "f1_2025" });
    const arb = v.car[0]!.suggestions[0]!;
    expect(arb).toMatchObject({ parameter: "front_arb", to_value: 13, blockedNow: null, forFormat: "f1_2025", formatUnknown: false });
    expect(arb.hypothesis).toMatch(/^Front Anti-Roll Bar 15 → 13: /);
    const diff = v.car[1]!.suggestions.find((x) => x.parameter === "diff_on_throttle")!;
    expect(diff.to_value).toBe(80);
    expect(diff.hypothesis).toMatch(/ → 80 %: /);
    // at the range end there is nothing to try
    const susp = v.car[1]!.suggestions.find((x) => x.parameter === "rear_suspension")!;
    expect(susp.blockedNow).toBe("Rear Suspension is already at its minimum for this car.");
    expect(valueForFormat({ from_value: 59, steps: 3, direction: "higher" }, params.get("brake_bias"), "f1_2025")).toBe(60);
    expect(valueForFormat({ from_value: null, steps: 3, direction: "higher" }, params.get("brake_bias"), "f1_2025")).toBeNull();
    expect(valueForFormat({ from_value: 58, steps: 1, direction: "lower" }, params.get("brake_bias"), null)).toBeNull();
  });

  it("the same change for two symptoms is listed once, with its button under the first", () => {
    const b = techniqueFixtures.suzukaBalance();
    const extra = { ...b.symptoms[0]!, id: "entry-understeer-car", phase: "entry" as const };
    const again = { ...b.setup!.suggestions[0]!, symptom_id: "entry-understeer-car" };
    const v = symptomViews([b.symptoms[0]!, extra], { ...b.setup!, suggestions: [...b.setup!.suggestions, again] });
    expect(v.car[0]!.suggestions[0]!.duplicateOf).toBeNull();
    expect(v.car[1]!.suggestions[0]).toMatchObject({ parameter: "front_arb", duplicateOf: "mid-understeer-car" });
  });

  it("an unknown setup cannot be tried", () => {
    const b = techniqueFixtures.suzukaBalance();
    const setup = { suggestions: b.setup!.suggestions.map((x) => ({ ...x, from_value: null, to_value: null, blocked: null })) };
    const v = symptomViews(b.symptoms, setup);
    expect(v.car[0]!.suggestions[0]!.blockedNow).toBe("Your setup for this session is unknown");
  });
});

describe("availability", () => {
  it("reasons for what is missing, notes for what is there", () => {
    const gt7 = techniqueFixtures.gt7Session();
    expect(unavailableReasons(gt7.available, ["slip", "balance", "setup"])).toEqual([
      "Pitwall does not read tyre slip from this game yet, so wheelspin, lock-ups and balance are unknown.",
      "Setup suggestions are for F1 25 only.",
    ]);
    expect(availabilityNotes(gt7.available, ["line", "inputs"])).toHaveLength(2);
    const nr = techniqueFixtures.noReference();
    expect(unavailableReasons(nr.available, ["line", "inputs"])).toEqual(["No reference lap yet: drive a clean lap at this track to compare with."]);
    expect(unavailableReasons(null, ["line"])).toEqual([]);
  });
});

describe("density (spec §9, read from the viewed session's driver)", () => {
  it("beginner 4 rows, collapsed corners, no offset chart or mini map; intermediate 8; advanced all with degrees", () => {
    const b = techniqueDensity(densityFor(2, [driver(2, "Alex", "beginner")]));
    expect(b.inputRows).toEqual(["release", "coast", "throttle_pickup", "slip"]);
    expect(b).toMatchObject({ offsetChart: false, miniMap: false, cornerCollapsed: true, balanceDegrees: false, glossary: true, simpleWording: true, signed: false });
    const i = techniqueDensity(densityFor(3, [driver(3, "Sam", "intermediate")]));
    expect(i.inputRows).toHaveLength(8);
    expect(i).toMatchObject({ offsetChart: true, miniMap: true, cornerCollapsed: false, balanceDegrees: false, glossary: true });
    const a = techniqueDensity(densityFor(1, [driver(1, "James", "advanced")]));
    expect(a.inputRows).toHaveLength(12);
    expect(a).toMatchObject({ balanceDegrees: true, glossary: false, signed: true });
  });

  it("an unknown driver gets the intermediate view", () => {
    expect(techniqueDensity(densityFor(null, [])).inputRows).toHaveLength(8);
  });
});

describe("offset chart data", () => {
  it("rows keep gaps unknown, never 0; inside unknown plots the distance", () => {
    const t4 = techniqueFixtures.austriaCompare().corners.find((c) => c.corner === "T3")!;
    const rows = offsetRows(t4);
    expect(rows).toHaveLength(t4.window!.d_m.length);
    expect(rows[3]).toEqual({ d: t4.window!.d_m[3] }); // the fixture's one unknown sample
    expect(Math.min(...rows.filter((r) => r.o !== undefined).map((r) => r.o!))).toBeLessThan(-1.7);
    const t7 = techniqueFixtures.austriaCompare().corners.find((c) => c.corner === "T5")!;
    expect(t7.inside_known).toBe(false);
    expect(offsetRows(t7).every((r) => r.o === undefined || r.o >= 0)).toBe(true);
    expect(offsetRows({ window: null, inside_known: true })).toEqual([]);
  });

  it("domain, ticks and point ticks", () => {
    expect(offsetDomain([{ d: 0, o: -1.8 }, { d: 2, o: 0.4 }], true)).toEqual({ domain: [-2, 2], ticks: [-2, -1, 0, 1, 2] });
    expect(offsetDomain([{ d: 0 }], true).domain).toEqual([-1, 1]);
    expect(offsetDomain([{ d: 0, o: 2.6 }], false)).toEqual({ domain: [0, 3], ticks: [0, 1.5, 3] });
    expect(offsetTick(-1)).toBe("−1");
    expect(offsetTick(1.5)).toBe("+1.5");
    expect(offsetTick(0)).toBe("0");
    const t4 = techniqueFixtures.austriaCompare().corners.find((c) => c.corner === "T3")!;
    expect(pointTicks(t4).map((t) => t.label)).toEqual(["Turn-in", "Apex", "Track-out"]);
    // GT7 T5: apex and track-out 6 m apart in a 200 m window share one label instead of losing "Apex"
    const close = [
      { d: 100, label: "Turn-in" },
      { d: 150, label: "Apex" },
      { d: 156, label: "Track-out" },
    ];
    expect(tickLabels(close, 60, 260)).toEqual([
      { d: 100, label: "Turn-in" },
      { d: 150, label: "Apex · Track-out" },
    ]);
    expect(tickLabels(close.slice(0, 2), 60, 260)).toHaveLength(2);
  });
});

describe("how this is measured", () => {
  it("a curvature reads as a radius; thresholds by heading, heuristics first; every note once", async () => {
    const { thresholdValue, thresholdGroups, sheetNotes } = await import("../../pages/review/session/technique/MeasuredSheet");
    expect(thresholdValue({ value: 0.0005, unit: "1/m" })).toBe("radius 2 km");
    expect(thresholdValue({ value: 0.01, unit: "1/m" })).toBe("radius 100 m");
    expect(thresholdValue({ value: 0.6, unit: "fraction" })).toBe("60 %");
    const t = (key: string, group: "line" | "balance" | undefined, heuristic: boolean) => ({ key, value: 1, unit: "m", heuristic, text: key, group });
    const groups = thresholdGroups([t("LINE_SMOOTH_M", "line", false), t("LINE_NOTABLE_M", "line", true), t("US_DIFF_DEG", "balance", true), t("OLD", undefined, true)]);
    expect(groups.map((g) => g.title)).toEqual(["Racing line", "Handling balance", "Other"]);
    expect(groups[0]!.heuristic.map((x) => x.key)).toEqual(["LINE_NOTABLE_M"]);
    expect(groups[0]!.rules.map((x) => x.key)).toEqual(["LINE_SMOOTH_M"]);
    const note = "Braking assist is on (medium): the game adds its own braking.";
    expect(sheetNotes([[note, null], ["Stock CSL brake."], [note]])).toEqual([note, "Stock CSL brake."]);
  });
});
