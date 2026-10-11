// Setup › Validation view model (lane validate): grouping, chips (status colours only), progress, the context line,
// "-" for every unknown, the minus sign, plain words instead of the API's enums, the input check facts and the report
// rows. Fixtures: the lane's shared example run and the catalogue from the spec.

import { describe, expect, it } from "vitest";
import type { AutoVerdict, InputPhaseRecord, ItemResult } from "../endpoints/validation";
import { parseHash } from "../route-parse";
import { runWith, vfix } from "./testkit";
import {
  AUTO_CHIP,
  CHECK_CHIP,
  RESULT_CHIP,
  cellText,
  checkView,
  checklist,
  contextLine,
  countChips,
  dateTime,
  defaultSelection,
  driverColumn,
  duration,
  headlineMetrics,
  humaniseKey,
  inputCheckFacts,
  markFor,
  metricValue,
  minutesText,
  msAsSeconds,
  neighbourId,
  notLiveNotice,
  orderedIds,
  otherMarks,
  parseValidationParam,
  progress,
  radioLine,
  selectedIds,
  serverLine,
  signedMetres,
  summaryRows,
  tierNotice,
  tiersLine,
  validationPath,
} from "./view";

const TIMING_TONES = /pw-rec|pw-pb|pw-slower|purple|green|yellow/;

describe("chips", () => {
  it("status colours only, never the timing colours, and plain words (no API enum shows)", () => {
    const all = [...Object.values(RESULT_CHIP), ...Object.values(AUTO_CHIP), ...Object.values(CHECK_CHIP)];
    for (const c of all) {
      expect(["default", "accent", "success", "warning", "danger"]).toContain(c.tone);
      expect(c.label).not.toMatch(TIMING_TONES);
      expect(c.label).not.toMatch(/_|inconclusive|no_evidence|not_live|driver_only|needs_review/);
    }
    expect(RESULT_CHIP.pass.tone).toBe("success");
    expect(RESULT_CHIP.fail.tone).toBe("danger");
    expect(RESULT_CHIP.needs_review.tone).toBe("warning");
    expect(AUTO_CHIP.inconclusive.tone).toBe("warning");
    expect(CHECK_CHIP.unknown.label).toBe("-");
  });

  it("every result and verdict has words", () => {
    const results: ItemResult[] = ["pass", "fail", "needs_review", "not_run", "skipped"];
    const verdicts: AutoVerdict[] = ["pass", "fail", "inconclusive", "no_evidence", "not_live", "unavailable", "driver_only"];
    for (const r of results) expect(RESULT_CHIP[r].label.length).toBeGreaterThan(1);
    for (const v of verdicts) expect(AUTO_CHIP[v].label.length).toBeGreaterThan(1);
  });
});

describe("the checklist", () => {
  it("groups the run's tests in catalogue order; the current one says Now", () => {
    const cat = vfix.catalog();
    const run = vfix.run();
    const groups = checklist(cat, run);
    expect(groups.map((g) => g.title)).toEqual(["Dashboard at the wheel", "Radio", "Coaching", "Games"]);
    expect(orderedIds(groups)).toEqual(["ipad_home_screen", "radio_ptt", "cues_timing", "gt7_ps5"]);
    const rows = groups.flatMap((g) => g.rows);
    expect(rows.find((r) => r.id === "cues_timing")).toMatchObject({ current: true, chip: { label: "Now" } });
    expect(rows.find((r) => r.id === "ipad_home_screen")?.chip.label).toBe("Pass");
    expect(rows.find((r) => r.id === "radio_ptt")?.chip.label).toBe("Review");
    expect(rows.find((r) => r.id === "gt7_ps5")?.chip.label).toBe("Not yet");
  });

  it("an id this dashboard does not know keeps a readable title instead of disappearing", () => {
    const run = runWith(["ipad_home_screen", "future_test_x"]);
    const rows = checklist(vfix.catalog(), run).flatMap((g) => g.rows);
    expect(rows.map((r) => r.title)).toContain("Future test x");
  });

  it("Previous / Next follow the checklist order", () => {
    const ids = ["a", "b", "c"];
    expect(neighbourId(ids, "b", -1)).toBe("a");
    expect(neighbourId(ids, "b", 1)).toBe("c");
    expect(neighbourId(ids, "a", -1)).toBeNull();
    expect(neighbourId(ids, "c", 1)).toBeNull();
    expect(neighbourId(ids, null, 1)).toBe("a");
    expect(neighbourId(ids, "zz", 1)).toBeNull();
  });

  it("progress counts marked, done and skipped tests", () => {
    expect(progress(vfix.run()).text).toBe("2 of 4 done");
  });

  it("a new run: every available test that is not optional; unavailable ones never selected", () => {
    const cat = vfix.catalog();
    const sel = defaultSelection(cat);
    expect(sel.ipad_endurance).toBe(false); // optional
    expect(sel.game_selection).toBe(false); // not available on this server
    expect(sel.cues_timing).toBe(true);
    const ids = selectedIds(cat, { ...sel, game_selection: true });
    expect(ids).not.toContain("game_selection");
    expect(ids).toHaveLength(10);
    expect(minutesText(cat, ids)).toMatch(/^about \d h( \d+ min)?$/);
    expect(minutesText(cat, [])).toBe("-");
    expect(minutesText(cat, ["cues_timing"])).toBe("about 20 min");
  });
});

describe("run context", () => {
  it("what Pitwall sees now, unknown parts left out", () => {
    const run = vfix.run();
    expect(contextLine(run, new Map([[1, "James"]]))).toBe("F1 25 · PS5 · Austria · James · Radio: iPad (AirPod)");
    expect(contextLine(run)).toBe("F1 25 · PS5 · Austria · Driver #1 · Radio: iPad (AirPod)");
    const none = { ...run, context: { ...run.context, telemetry: "no_data" as const, game: null, platform: null, track: null, driver_id: null, radio_clients: 0 }, clients: [] };
    expect(contextLine(none)).toBe("No game data yet · Radio: not connected");
    expect(contextLine(none)).not.toMatch(/null|undefined/);
  });

  it("radio: the iPad's microphone class when known, else just the device", () => {
    const run = vfix.run();
    const c = run.clients[0]!;
    expect(radioLine({ ...run, clients: [{ ...c, audio_input_kind: null }] })).toBe("Radio: iPad");
    expect(radioLine({ ...run, clients: [{ ...c, audio_input_kind: "unknown" }] })).toBe("Radio: iPad");
    expect(radioLine({ ...run, clients: [{ ...c, radio: null }] })).toBe("Radio: 1 connected");
  });

  it("not-live data is shown but never counts, in words", () => {
    const ctx = vfix.run().context;
    expect(tierNotice(ctx)).toBeNull();
    expect(tierNotice({ ...ctx, tier: "recorded" })).toBe("This session is a replay: it is shown but does not count.");
    expect(tierNotice({ ...ctx, tier: "synthetic" })).toMatch(/generated test data \(synthetic\).*does not count/);
    expect(tierNotice({ ...ctx, tier: "loopback" })).toMatch(/recording sent from this Mac/);
    expect(tierNotice({ ...ctx, tier: "unknown" })).toMatch(/does not count/);
    expect(tierNotice({ ...ctx, telemetry: "no_data", tier: "unknown" })).toBeNull();
    expect(notLiveNotice({ verdict: "not_live", tier: "synthetic" })).toBe("Pitwall only saw this test in generated test data: it is shown but does not count.");
    expect(notLiveNotice({ verdict: "not_live", tier: null })).toMatch(/data Pitwall cannot place/);
    expect(notLiveNotice({ verdict: "inconclusive", tier: "live" })).toBeNull();
  });
});

describe("numbers", () => {
  it("unknown is '-', the minus sign is U+2212", () => {
    expect(signedMetres(-3.4)).toBe("−3.4 m");
    expect(signedMetres(2.1)).toBe("+2.1 m");
    expect(signedMetres(0)).toBe("0.0 m");
    expect(signedMetres(null)).toBe("-");
    expect(msAsSeconds(1840)).toBe("1.84 s");
    expect(msAsSeconds(21_400)).toBe("21.4 s");
    expect(msAsSeconds(null)).toBe("-");
    expect(duration(1312)).toBe("21:52");
    expect(duration(45)).toBe("45 s");
    expect(duration(3725)).toBe("1:02:05");
    expect(duration(Number.NaN)).toBe("-");
    expect(cellText(-3.4)).toBe("−3.4");
    expect(cellText("-4.2 m")).toBe("−4.2 m");
    expect(cellText(null)).toBe("-");
    expect(dateTime(null)).toBe("-");
    expect(dateTime(1791833412)).toMatch(/2026/);
  });

  it("metric values by the key's unit", () => {
    expect(metricValue("median_heard_vs_point_m", -3.1)).toBe("−3.1 m");
    expect(metricValue("median_onset_vs_word_s", 0.11)).toBe("+0.11 s");
    expect(metricValue("median_latency_ms", 312)).toBe("0.31 s");
    expect(metricValue("wake_on_streak_s", 1312)).toBe("21:52");
    expect(metricValue("fallback_share", 0.2)).toBe("20 %");
    expect(metricValue("measured", 6)).toBe("6");
    expect(metricValue("safari_version", "18.6")).toBe("18.6");
    expect(metricValue("anything", null)).toBe("-");
    expect(metricValue("anything", "")).toBe("-");
    expect(humaniseKey("median_latency_ms")).toBe("Median latency");
  });

  it("headline numbers: the test's own keys first, at most 4", () => {
    const cues = vfix.run().items.find((i) => i.id === "cues_timing")!;
    expect(headlineMetrics("cues_timing", cues.auto.metrics).map((m) => [m.label, m.value])).toEqual([
      ["Measured", "6"],
      ["Late calls", "0"],
      ["Word vs your point (median)", "−3.1 m"],
      ["Word to your braking (median)", "+0.11 s"],
    ]);
    expect(headlineMetrics("unknown_item", { a_m: 3, b: "x", c: 2, d: 1, e: 5, f: 6 })).toHaveLength(4);
    expect(headlineMetrics("gt7_ps5", {})).toEqual([]);
  });

  it("checks: '-' for unknown values, heuristic kept", () => {
    expect(checkView({ id: "x", label: "L", status: "unknown", value: null, target: ">= 8", heuristic: true })).toMatchObject({
      value: "-",
      target: "≥ 8",
      heuristic: true,
      chip: { label: "-" },
    });
  });
});

describe("marks", () => {
  const mark = (driver_id: number | null, verdict: "worked" | "didnt") => ({
    driver_id,
    verdict,
    notes: "",
    attestations: {},
    extra: {},
    at_unix: 1791833905,
    source: "screen" as const,
  });
  it("per-driver tests keep one mark per driver; others see the newest", () => {
    const state = { marks: [mark(1, "worked"), mark(2, "didnt"), mark(1, "didnt")] };
    expect(markFor(state, 1, true)?.verdict).toBe("didnt");
    expect(markFor(state, 2, true)?.verdict).toBe("didnt");
    expect(markFor(state, 3, true)).toBeNull();
    expect(markFor(state, 3, false)?.driver_id).toBe(1);
    expect(otherMarks(state, 1).map((m) => m.driver_id)).toEqual([2]);
    expect(driverColumn(state.marks, new Map([[1, "James"]]))).toBe("James: Didn't work · Driver #2: Didn't work");
    expect(driverColumn([mark(1, "worked")])).toBe("Worked");
    expect(driverColumn([])).toBe("-");
  });
});

describe("input check facts", () => {
  const rec = (phase: InputPhaseRecord["phase"], over: Partial<InputPhaseRecord> = {}): InputPhaseRecord => ({
    item_id: "gt7_ps5",
    phase,
    start_unix: 1,
    end_unix: 4,
    samples: 30,
    steer_mean: null,
    steer_min: null,
    steer_max: null,
    throttle_max: null,
    brake_max: null,
    gear_min: null,
    steer_raw_range: null,
    rotation_deg: null,
    ...over,
  });
  it("GT7: steering sign as expected or inverted, pedals in %", () => {
    const ok = [rec("centre", { steer_mean: 0.01 }), rec("left", { steer_mean: -0.98 }), rec("right", { steer_mean: 0.97 }), rec("pedals", { throttle_max: 1, brake_max: 0.98 })];
    expect(inputCheckFacts(ok, "gt7_ps5")).toEqual([
      "Hands off: +0.01",
      "Full lock left: −0.98 · right: +0.97 · sign as expected",
      "Throttle at most 100 % · brake at most 98 %",
    ]);
    const inv = [rec("left", { steer_mean: 0.9 }), rec("right", { steer_mean: -0.9 })];
    expect(inputCheckFacts(inv, "gt7_ps5")[0]).toContain("steering sign looks inverted");
    expect(inputCheckFacts(ok, "ac_ps5")).toEqual([]); // another test's records
  });
  it("AC: the raw range with the rotation entered, reverse seen or not, unknown as '-'", () => {
    const ac = [
      rec("left", { item_id: "ac_ps5", steer_raw_range: [-144.9, 211.9], rotation_deg: 900 }),
      rec("reverse", { item_id: "ac_ps5", gear_min: -1 }),
    ];
    expect(inputCheckFacts(ac, "ac_ps5")).toEqual([
      "Full lock left: - · right: -",
      "Raw steering range −144.9 to 211.9 at 900°",
      "Reverse gear seen",
    ]);
    expect(inputCheckFacts([rec("reverse", { item_id: "ac_ps5", gear_min: 0 })], "ac_ps5")).toEqual(["Reverse gear not seen"]);
    expect(inputCheckFacts([rec("reverse", { item_id: "ac_ps5" })], "ac_ps5")).toEqual(["Reverse gear: -"]);
  });
});

describe("reports", () => {
  it("count chips: non-zero only, in a fixed order, status colours", () => {
    expect(countChips(vfix.run().counts)).toEqual([
      { key: "pass", label: "1 passed", tone: "success" },
      { key: "needs_review", label: "2 to review", tone: "warning" },
      { key: "not_run", label: "1 not run", tone: "default" },
    ]);
  });
  it("server and tiers lines", () => {
    const rep = vfix.report();
    expect(serverLine(rep.run.server)).toBe("pitwall 0.1.0 (a1b2c3d) · macOS · voice on (Kokoro, Parakeet) · LLM on");
    expect(serverLine({ ...rep.run.server, stt: "none", tts: "none" })).toBe("pitwall 0.1.0 (a1b2c3d) · macOS · voice on (text only) · LLM on");
    expect(serverLine({ ...rep.run.server, stt: "none" })).toBe("pitwall 0.1.0 (a1b2c3d) · macOS · voice on (Kokoro) · LLM on");
    expect(serverLine({ ...rep.run.server, voice_enabled: false, llm_enabled: false, git_commit: null })).toBe("pitwall 0.1.0 · macOS · voice off · LLM off");
    expect(tiersLine(rep.tiers)).toBe("412 live records · 3 from replays, generated data or unknown sources");
  });
  it("summary rows: plain words, the first reason as the key evidence", () => {
    const rows = summaryRows(vfix.report());
    expect(rows).toEqual([
      {
        id: "cues_timing",
        title: "Braking calls land on time",
        result: RESULT_CHIP.needs_review,
        driver: "-",
        saw: AUTO_CHIP.inconclusive,
        key: "6 calls measured, 8 needed",
      },
    ]);
  });
});

describe("page routes", () => {
  it("checklist, reports and one report; anything else is the checklist", () => {
    expect(parseValidationParam(null)).toEqual({ view: "checklist", runId: null });
    expect(parseValidationParam("reports")).toEqual({ view: "reports", runId: null });
    expect(parseValidationParam("reports/20261012-193012-a3f1")).toEqual({ view: "reports", runId: "20261012-193012-a3f1" });
    expect(parseValidationParam("reports/../../etc")).toEqual({ view: "reports", runId: null });
    expect(parseValidationParam("nonsense")).toEqual({ view: "checklist", runId: null });
    expect(validationPath()).toBe("/setup/validation");
    expect(validationPath("reports")).toBe("/setup/validation/reports");
    expect(validationPath("reports", "20261012-193012-a3f1")).toBe("/setup/validation/reports/20261012-193012-a3f1");
  });
  it("the router knows the page (Setup › Validation)", () => {
    expect(parseHash("#/setup/validation")).toMatchObject({ area: "setup", page: "validation", param: null });
    expect(parseHash("#/setup/validation/reports/20261012-193012-a3f1")).toMatchObject({
      area: "setup",
      page: "validation",
      param: "reports/20261012-193012-a3f1",
    });
  });
});
