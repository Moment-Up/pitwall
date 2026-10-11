// Technique words (feat/technique spec §4, §9): descriptions relative to the driver's own reference, unknown is "-",
// U+2212 for minus, the pedals' tolerances decide "about the same", never advice.
import { describe, expect, it } from "vitest";
import type { CornerInputs, PhaseSummary, SlipEvents, TechniqueNote } from "../endpoints/technique";
import { MINUS } from "../format";
import { ADVICE_WORDS, techniqueFixtures } from "./testkit";
import {
  BALANCE_WORDS,
  inputDifference,
  inputValue,
  INPUT_ROWS_ALL,
  lapsUsedText,
  linePointSummaryText,
  lockupWords,
  offsetShort,
  offsetWords,
  phaseBalanceWords,
  phaseSummaryText,
  signedNumber,
  slipWords,
  suggestionChange,
  symptomLapsText,
  symptomTitle,
  wheelspinWords,
} from "./words";

const slip = (over: Partial<SlipEvents> = {}): SlipEvents => ({
  status: "measured",
  events: 0,
  total_s: null,
  peak_slip: null,
  wheels: [],
  at_m: [],
  tc_level: null,
  ...over,
});

function inputs(over: Partial<CornerInputs> = {}): CornerInputs {
  return {
    braked: true,
    brake_start_m: 100,
    brake_peak: 0.95,
    time_to_peak_s: 0.22,
    peak_hold_s: 0.6,
    release_s: 0.42,
    release_shape: "steady",
    brake_at_turn_in: 0.3,
    brake_at_apex: 0.04,
    trail_overlap_s: 0.55,
    coast_s: 0.08,
    coast_m: 2.4,
    pickup_m: 250,
    pickup_vs_apex_m: 9,
    full_throttle_m: 300,
    throttle_ramp_s: 1.6,
    throttle_lifts: 0,
    lockup: slip({ status: "abs_on", events: null }),
    wheelspin: slip({ tc_level: 1 }),
    ...over,
  };
}

const summary = (over: Partial<PhaseSummary> = {}): PhaseSummary => ({
  laps: 3,
  understeer: 0,
  neutral: 3,
  oversteer: 0,
  median_slip_diff_deg: 1.2,
  slides: 0,
  recurring: null,
  best_lap: null,
  verdict: null,
  ...over,
});

describe("line offsets", () => {
  it("+ is tighter, − is wider, relative to the reference; inside unknown says only the distance", () => {
    expect(offsetWords(-1.5, true)).toBe("1.5 m wider than your reference");
    expect(offsetWords(0.42, true, "your target lap")).toBe("0.4 m tighter than your target lap");
    expect(offsetWords(-1.5, false)).toBe("1.5 m off your reference line");
    expect(offsetWords(0.01, true)).toBe("on your reference line");
    expect(offsetWords(null, true)).toBe("-");
    expect(offsetShort(-1.84, true)).toBe("1.8 m wider");
    expect(offsetShort(1.2, false)).toBe("1.2 m off");
    expect(offsetShort(undefined, true)).toBe("-");
  });

  it("session summaries: the median and the laps beyond 1 m, or 'about the same'", () => {
    expect(linePointSummaryText("apex", { median_offset_m: -1.2, laps: 4, laps_wider: 3, laps_tighter: 0 }, true)).toBe(
      "Apex: 1.2 m wider on 3 of 4 laps",
    );
    expect(linePointSummaryText("track_out", { median_offset_m: 1.4, laps: 3, laps_wider: 0, laps_tighter: 2 }, true)).toBe(
      "Track-out: 1.4 m tighter on 2 of 3 laps",
    );
    expect(linePointSummaryText("turn_in", { median_offset_m: 0.3, laps: 4, laps_wider: 1, laps_tighter: 0 }, true)).toBe(
      "Turn-in: about the same line as your reference (median 0.3 m over 4 laps); wider by 1 m or more on 1 lap",
    );
    expect(linePointSummaryText("apex", { median_offset_m: 0.9, laps: 2, laps_wider: 0, laps_tighter: 0 }, false)).toBe(
      "Apex: 0.9 m off the reference line (median of 2 laps)",
    );
    expect(linePointSummaryText("apex", null, true)).toBeNull();
    expect(linePointSummaryText("apex", { median_offset_m: null, laps: 2, laps_wider: 0, laps_tighter: 0 }, true)).toBeNull();
  });

  it("signed numbers use U+2212", () => {
    expect(signedNumber(-7.24, 1, "°")).toBe(`${MINUS}7.2°`);
    expect(signedNumber(3, 1)).toBe("+3.0");
    expect(signedNumber(0)).toBe("0.0");
    expect(signedNumber(null)).toBe("-");
  });
});

describe("brake and throttle", () => {
  it("values per row; unknown is '-', no braking says so", () => {
    const i = inputs({ release_shape: "step", release_s: 0.12, pickup_vs_apex_m: -4, throttle_ramp_s: null, throttle_lifts: 2 });
    expect(inputValue("release", i)).toBe("0.12 s · let off in one go");
    expect(inputValue("coast", i)).toBe("0.08 s (2 m)");
    expect(inputValue("throttle_pickup", i)).toBe("4 m before the slowest point");
    expect(inputValue("brake_peak", i)).toBe("95 %");
    expect(inputValue("throttle_ramp", i)).toBe("not full before the next corner");
    expect(inputValue("throttle_lifts", i)).toBe("2 lifts");
    expect(inputValue("slip", i)).toBe("ABS on: no lock-up data · no wheelspin");
    expect(inputValue("release", inputs({ braked: false }))).toBe("no braking");
    expect(inputValue("time_to_peak", inputs({ time_to_peak_s: null }))).toBe("-");
    for (const row of INPUT_ROWS_ALL) expect(inputValue(row, null)).toBe("-");
  });

  it("slip words: ABS on, no data, measured events", () => {
    expect(lockupWords(slip({ status: "abs_on", events: null }))).toBe("ABS on: no lock-up data");
    expect(lockupWords(slip({ events: 2, total_s: 0.3 }))).toBe("2 lock-ups (0.30 s)");
    expect(lockupWords(slip({ status: "not_applicable" }))).toBeNull();
    expect(wheelspinWords(slip({ events: 2, total_s: 0.45 }))).toBe("wheelspin 0.45 s (2 times)");
    expect(wheelspinWords(slip({ events: 1, total_s: 0.3 }))).toBe("wheelspin 0.30 s");
    expect(slipWords(inputs({ lockup: slip({ status: "no_data", events: null }), wheelspin: slip({ status: "no_data", events: null }) }))).toBe("-");
  });

  it("the difference is the backend's note verbatim (simple wording when asked), else the numbers restated", () => {
    const note: TechniqueNote = {
      metric: "coast",
      lap_value: 0.32,
      ref_value: 0.08,
      delta: 0.24,
      unit: "s",
      notable: true,
      muted: false,
      laps: null,
      laps_total: null,
      text: "coasted for 0.32 s between brake and throttle vs 0.08 s on your reference",
      text_simple: "you were off both pedals for longer than on your reference",
    };
    const ref = inputs();
    const lap = inputs({ coast_s: 0.32, release_s: 0.2, pickup_vs_apex_m: 21, throttle_lifts: 1 });
    expect(inputDifference("coast", ref, lap, { notes: [note] })).toBe(note.text);
    expect(inputDifference("coast", ref, lap, { notes: [note], simple: true })).toBe(note.text_simple);
    expect(inputDifference("release", ref, lap)).toBe("0.22 s shorter");
    expect(inputDifference("throttle_pickup", ref, lap)).toBe("12 m later");
    expect(inputDifference("throttle_lifts", ref, lap)).toBe("1 lift more");
    expect(inputDifference("release", ref, null)).toBe("-");
    // a note the backend did not call notable is restated within the tolerances, not quoted
    const quiet = { ...note, metric: "release" as const, notable: false, text: "Released the brake over 0.37 s vs 0.43 s on your reference." };
    expect(inputDifference("release", inputs({ release_s: 0.43 }), inputs({ release_s: 0.37 }), { notes: [quiet] })).toBe("about the same");
    expect(inputDifference("release", inputs({ braked: false }), lap)).toBe("braked here, the reference did not");
  });

  it("the pedals decide what is 'about the same': a stock CSL hides a 0.06 brake difference, a load cell shows it", () => {
    const ref = inputs({ brake_peak: 0.9, release_s: 0.4 });
    const lap = inputs({ brake_peak: 0.84, release_s: 0.48 });
    const csl = { peak: 0.08, time: 0.1 };
    const loadCell = { peak: 0.05, time: 0.07 };
    expect(inputDifference("brake_peak", ref, lap, { tol: csl })).toBe("about the same");
    expect(inputDifference("brake_peak", ref, lap, { tol: loadCell })).toBe("6 % less brake");
    expect(inputDifference("release", ref, lap, { tol: csl })).toBe("about the same");
    expect(inputDifference("release", ref, lap, { tol: loadCell })).toBe("0.08 s longer");
  });
});

describe("balance", () => {
  it("chips say it in words; degrees for advanced; '-' when unknown", () => {
    expect(BALANCE_WORDS.understeer).toBe("Pushed wide (understeer)");
    expect(phaseBalanceWords({ cls: "neutral", slip_diff_deg: 1.4, body_slip_max_deg: 1, slide: false, samples: 20 })).toBe("Balanced");
    expect(phaseBalanceWords({ cls: "understeer", slip_diff_deg: 7.24, body_slip_max_deg: 1, slide: false, samples: 20 }, true)).toBe(
      "Pushed wide (understeer) · +7.2°",
    );
    expect(phaseBalanceWords({ cls: "oversteer", slip_diff_deg: -0.4, body_slip_max_deg: 6.1, slide: true, samples: 18 }, true)).toBe(
      `Rear stepped out (oversteer) · slide · ${MINUS}0.4°`,
    );
    expect(phaseBalanceWords(null)).toBe("-");
  });

  it("session phases: car (even on your best lap) against driving (not on your best lap)", () => {
    expect(phaseSummaryText("mid", summary({ understeer: 3, neutral: 0, recurring: "understeer", best_lap: "understeer", verdict: "car" }))).toBe(
      "Mid: understeer on 3 of 3 laps, even on your best lap",
    );
    expect(phaseSummaryText("entry", summary({ understeer: 2, neutral: 1, recurring: "understeer", best_lap: "neutral", verdict: "driving" }))).toBe(
      "Entry: understeer on 2 of 3 laps, not on your best lap",
    );
    expect(phaseSummaryText("exit", summary())).toBe("Exit: balanced on 3 of 3 laps");
    expect(phaseSummaryText("exit", summary({ laps: 0, neutral: 0 }))).toBeNull();
  });

  it("symptoms", () => {
    const [car, , driving] = techniqueFixtures.suzukaBalance().symptoms;
    expect(symptomTitle(car!)).toBe("Mid-corner understeer");
    expect(symptomLapsText(car!)).toBe("3 of 3 laps, including your best");
    expect(symptomLapsText(driving!)).toBe("2 of 3 laps, not on your best lap");
  });
});

describe("setup and laps", () => {
  it("a suggestion in menu units, U+2212 for negative values", () => {
    expect(suggestionChange({ label: "Front Anti-Roll Bar", from_value: 9, to_value: 7, unit: null })).toBe("Front Anti-Roll Bar 9 → 7");
    expect(
      suggestionChange(
        { label: "Front Camber", from_value: -3.5, to_value: -3.3, unit: "deg" },
        { decimals: 2, unit: "deg" } as Parameters<typeof suggestionChange>[1],
      ),
    ).toBe(`Front Camber ${MINUS}3.50 deg → ${MINUS}3.30 deg`);
    expect(suggestionChange({ label: "Brake Pressure", from_value: null, to_value: null, unit: "%" })).toBe("Brake Pressure - → -");
  });

  it("laps used, the reference never counted", () => {
    const s = techniqueFixtures.austriaSession();
    expect(lapsUsedText(s.laps, s.ref_lap_id)).toBe("8 of 9 laps compared · lap 65 flashback");
  });

  it("nothing in the fixtures' words is advice", () => {
    const s = techniqueFixtures.austriaSession();
    const all: string[] = [];
    for (const c of s.corners) {
      for (const k of ["turn_in", "apex", "track_out"] as const) {
        all.push(linePointSummaryText(k, c.line?.points[k], c.line?.inside_known ?? false) ?? "");
      }
      for (const l of c.laps) for (const row of INPUT_ROWS_ALL) all.push(inputDifference(row, c.ref.inputs, l.inputs, { notes: l.notes }));
    }
    for (const t of all) for (const re of ADVICE_WORDS) expect(t, t).not.toMatch(re);
  });
});
