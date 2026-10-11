import { describe, expect, it } from "vitest";
import { RequestCache } from "../cache";
import type { AiLevelSuggestion, AiPacePoint, LiveAiPace, SessionAiPace } from "../endpoints/review";
import { aiPaceUrl, reviewKeys } from "../endpoints/review";
import {
  aiEndLine,
  aiEvidenceText,
  aiPaceQuery,
  aiPaceReasonText,
  aiPaceTile,
  aiPaceTitle,
  aiSeries,
  aiSeriesSentence,
  aiStrip,
  dotWords,
  exclusionWords,
  gapAxis,
  gapTick,
  gapToAiWords,
  isSyntheticPoint,
  ordinal,
  pctWords,
  showAiCard,
  suggestionForSeries,
  suggestionKeyLabel,
  suggestionsFor,
  suggestionView,
} from "./aipace";
import { aiFixtureBlocks, aiFixtures } from "./testkit";

const NOW = Date.UTC(2026, 9, 11, 16, 0, 0);
const AUSTRIA = { game: "f1_25", trackId: "f1:17" };

/** A suggestion with a measured level (the owner's data has none yet: every key has a single level). */
function measured(over: Partial<AiLevelSuggestion> = {}): AiLevelSuggestion {
  const base = aiFixtures.driverAustria().suggestions[0]!;
  return {
    ...base,
    basis: "measured",
    level: 38,
    range: [35, 41],
    bound: null,
    confidence: "high",
    direction: "higher",
    sessions_used: 4,
    levels_used: [30, 35, 40, 45],
    slope_pct_per_level: 0.31,
    text: "Try AI 38 here (35-41). Measured from 4 races at levels 30, 35, 40, 45.",
    ...over,
  };
}

describe("contract fixtures say where they came from", () => {
  it("every AI pace fixture has a provenance block naming the real capture it was computed from", () => {
    const blocks = aiFixtureBlocks();
    expect(blocks.length).toBeGreaterThanOrEqual(6);
    for (const { name, block } of blocks) {
      expect(block.source, name).toMatch(/real PS5 F1 25 capture/);
      expect(["contract", "recorded"], name).toContain(block.tier);
      expect(block.what.length, name).toBeGreaterThan(20);
    }
  });

  it("the Austria fixture is the spec's (section 6) with the 19 AI bests filled in", () => {
    const a = aiFixtures.austria();
    expect(a).toMatchObject({ status: "ok", ai_difficulty: 35, ai_ref_ms: 74579, ai_best_ms: 72730, gap_ms: 3772, gap_pct: 5.06 });
    expect(a.ai_bests_ms).toHaveLength(19);
    expect(a.ai_bests_ms[9]).toBe(a.ai_ref_ms); // the median of 19 sorted bests
    expect(a.ai_bests_ms[0]).toBe(a.ai_best_ms);
  });
});

describe("the contract fixtures equal the real backend's answers for the same captures", () => {
  it("session ai_pace: every field but the clock and the database's lap id", () => {
    const strip = ({ updated_unix: _u, driver_best_lap_id: _l, ...rest }: SessionAiPace) => rest;
    const real = aiFixtures.recorded.sessionAustria();
    expect(Object.keys(real).sort()).toEqual(Object.keys(aiFixtures.austria()).sort());
    expect(strip(real)).toEqual(strip(aiFixtures.austria()));
  });

  it("driver series and suggestions: the same points (other session ids and times) and the same suggestions", () => {
    for (const [real, contract] of [
      [aiFixtures.recorded.driverAustria(), aiFixtures.driverAustria()],
      [aiFixtures.recorded.driverAll(), aiFixtures.driverAll()],
    ] as const) {
      expect(Object.keys(real).sort()).toEqual(Object.keys(contract).sort());
      expect(real.scope).toEqual(contract.scope);
      // the car name is the session row's (the live database named F2 team 214 "team_214" with older code)
      const pts = (d: typeof real) => d.points.map(({ session_id: _s, started_unix: _t, car_name: _c, ...rest }) => rest);
      expect(pts(real)).toEqual(pts(contract));
      expect(real.suggestions).toEqual(contract.suggestions);
    }
  });
});

describe("endpoint and cache key", () => {
  it("asks for one driver's AI pace with only the parts that are set", () => {
    expect(aiPaceUrl(1, aiPaceQuery(AUSTRIA))).toBe("/api/drivers/1/ai-pace?game=f1_25&track_id=f1%3A17");
    expect(aiPaceUrl(2, { car_class: "F1 World", category: "race", limit: 50, target_gap_pct: 1.5 })).toBe(
      "/api/drivers/2/ai-pace?car_class=F1+World&category=race&limit=50&target_gap_pct=1.5",
    );
    expect(aiPaceUrl(3)).toBe("/api/drivers/3/ai-pace");
  });

  it("lives under the driver-sessions prefix, so a lap or a driver switch refreshes it; defaults share one key", () => {
    const key = reviewKeys.aiPace(1, aiPaceQuery(AUSTRIA));
    expect(key.startsWith("driver-sessions:1:ai-pace:")).toBe(true);
    expect(key).toBe(reviewKeys.aiPace(1, { ...aiPaceQuery(AUSTRIA), limit: 200, target_gap_pct: 0 }));
    expect(key).not.toBe(reviewKeys.aiPace(1, { ...aiPaceQuery(AUSTRIA), target_gap_pct: 2 }));
    const c = new RequestCache();
    c.set(key, {});
    c.invalidate("driver-sessions:");
    expect(c.entry(key).stale).toBe(true);
  });
});

describe("words", () => {
  it("ordinals", () => {
    expect([1, 2, 3, 4, 11, 12, 13, 20, 21, 22, 23, 101, 111].map(ordinal)).toEqual([
      "1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "20th", "21st", "22nd", "23rd", "101st", "111th",
    ]);
  });

  it("gaps ahead and behind read the app's way: a positive amount and a word, never a bare sign", () => {
    expect(gapToAiWords(3772)).toBe("3.8 s slower than the typical AI car");
    expect(gapToAiWords(-3219)).toBe("3.2 s faster than the typical AI car");
    expect(gapToAiWords(-800)).toBe("0.80 s faster than the typical AI car");
    expect(gapToAiWords(400)).toBe("0.40 s slower than the typical AI car");
    expect(gapToAiWords(3)).toBe("level with the typical AI car");
    expect(gapToAiWords(null)).toBeNull();
    for (const ms of [3772, -3219, -800]) expect(gapToAiWords(ms)).not.toMatch(/[-−+]/);
    expect(pctWords(5.06)).toBe("5.1% slower");
    expect(pctWords(-3.26)).toBe("3.3% faster");
    expect(pctWords(0.04)).toBe("level");
    expect(pctWords(null)).toBeNull();
  });

  it("titles and reasons", () => {
    expect(aiPaceTitle(35)).toBe("Pace vs AI (difficulty 35)");
    expect(aiPaceTitle(0)).toBe("Pace vs AI (difficulty 0)");
    expect(aiPaceTitle(null)).toBe("Pace vs AI");
    expect(aiPaceReasonText("ok")).toBeNull();
    expect(aiPaceReasonText("too_few_ai_cars")).toBe("Too few AI laps seen");
    expect(aiPaceReasonText("unknown_difficulty")).toBe("AI level not reported");
    expect(aiPaceReasonText("difficulty_changed")).toBe("AI level changed mid-session");
  });

  it("what a comparison is built from, exclusions in a fixed order", () => {
    expect(aiEvidenceText(aiFixtures.austria())).toBe("19 AI cars, 38 laps · not used: 19 opening laps of the race");
    expect(aiEvidenceText(aiFixtures.melbourne())).toBe(
      "21 AI cars, 22 laps · not used: 21 opening laps of the race, 20 laps with inconsistent timing",
    );
    expect(exclusionWords({ slow_car: 1, pit_in_out: 2, flashback: 1, new_reason: 3 })).toBe(
      "2 pit laps, 1 lap around a flashback, 1 car far off the pace, 3 new reason",
    );
    expect(exclusionWords({})).toBeNull();
    expect(exclusionWords({ invalid: 0 })).toBeNull();
  });
});

describe("Summary tile: Pace vs AI (difficulty 35)", () => {
  it("no AI in the session: no tile (a non-F1 session, one from before the feature, an older server, a time trial)", () => {
    expect(aiPaceTile(null)).toBeNull();
    expect(aiPaceTile(undefined)).toBeNull();
    expect(aiPaceTile({ ...aiFixtures.austria(), status: "time_trial" })).toBeNull();
  });

  it("driver behind: the gap in words, the rank on best laps; advanced adds the fastest AI car", () => {
    const t = aiPaceTile(aiFixtures.austria())!;
    expect(t.title).toBe("Pace vs AI (difficulty 35)");
    expect(t.change).toEqual({ text: "3.8 s slower", amount: "3.8 s", word: "slower" });
    expect(t.sub).toBe("than the typical AI car · 20th of 20 on best laps");
    expect(t.synthetic).toBe(false);
    expect(aiPaceTile(aiFixtures.austria(), { advanced: true })!.sub).toBe(
      "than the typical AI car · 20th of 20 on best laps · fastest AI 1:12.730",
    );
  });

  it("driver ahead (Melbourne, F2): faster, 1st of 22", () => {
    const t = aiPaceTile(aiFixtures.melbourne())!;
    expect(t.change).toEqual({ text: "3.2 s faster", amount: "3.2 s", word: "faster" });
    expect(t.sub).toBe("than the typical AI car · 1st of 22 on best laps");
    expect(t.evidence).toBe("21 AI cars, 22 laps · not used: 21 opening laps of the race, 20 laps with inconsistent timing");
  });

  it("level with the typical AI car; an unknown rank is left out, never guessed", () => {
    const t = aiPaceTile({ ...aiFixtures.austria(), gap_ms: 2, gap_pct: 0, field_rank: null, field_size: null })!;
    expect(t.change?.text).toBe("level");
    expect(t.sub).toBe("with the typical AI car");
  });

  it("difficulty unknown: no number, the title without a level, the reason in words", () => {
    const unknown: SessionAiPace = {
      ...aiFixtures.austria(),
      status: "unknown_difficulty",
      ai_difficulty: null,
      ai_ref_ms: null,
      ai_best_ms: null,
      ai_p25_ms: null,
      ai_p75_ms: null,
      ai_median_lap_ms: null,
      ai_bests_ms: [],
      gap_ms: null,
      gap_pct: null,
      field_rank: null,
      field_size: null,
    };
    const t = aiPaceTile(unknown)!;
    expect(t.title).toBe("Pace vs AI");
    expect(t.change).toBeNull();
    expect(t.sub).toBe("AI level not reported");
    expect(t.strip).toBeNull();
    const changed = aiPaceTile({ ...unknown, status: "difficulty_changed" })!;
    expect(changed.sub).toBe("AI level changed mid-session");
  });

  it("too few AI cars (Monza): '-' with the reason, even if a gap were sent", () => {
    const t = aiPaceTile(aiFixtures.monza())!;
    expect(t).toMatchObject({ title: "Pace vs AI (difficulty 35)", change: null, sub: "Too few AI laps seen", strip: null });
    expect(t.evidence).toBe(
      "3 AI cars, 3 laps · not used: 19 opening laps of the race, 19 laps not seen from their start, 16 laps with inconsistent timing",
    );
    expect(aiPaceTile({ ...aiFixtures.monza(), gap_ms: 1000 })!.change).toBeNull();
  });

  it("no clean lap of the driver's: the typical AI best is still a fact", () => {
    const p: SessionAiPace = { ...aiFixtures.austria(), status: "no_driver_lap", driver_best_ms: null, gap_ms: null, gap_pct: null, field_rank: null };
    const t = aiPaceTile(p)!;
    expect(t.change).toBeNull();
    expect(t.sub).toBe("No clean lap · typical AI best 1:14.579");
    expect(t.strip?.you).toBeNull();
    expect(t.strip?.ai).toHaveLength(19);
  });

  it("a synthetic session keeps its tile, with the SYNTHETIC tag", () => {
    expect(aiPaceTile(aiFixtures.austria(), { synthetic: true })!.synthetic).toBe(true);
  });

  it("the strip: AI best laps fastest on the left, the typical AI car and the driver placed between", () => {
    const s = aiStrip(aiFixtures.austria())!;
    expect(s.ai[0]).toBe(0);
    expect(s.you).toBe(1); // 1:18.351 is slower than every AI best
    expect(s.ref).toBeCloseTo((74579 - 72730) / (78351 - 72730), 6);
    expect(s.label).toBe("Your best lap 1:18.351 among 19 AI cars' best laps, 1:12.730 to 1:18.237: 20th of 20");
    const m = aiStrip(aiFixtures.melbourne())!;
    expect(m.you).toBe(0);
    expect(m.ai[m.ai.length - 1]).toBe(1);
    expect(aiStrip({ ...aiFixtures.monza() })).toBeNull();
  });
});

describe("Drive: the Session complete line", () => {
  const live = (): LiveAiPace => aiFixtures.live();

  it("one line for an ok comparison of this session", () => {
    expect(aiEndLine(live(), "e2c05b9f70f3")).toBe("Against the AI (35): 3.8 s slower than the typical AI car · 20th of 20");
    expect(aiEndLine({ ...live(), gap_ms: -3219, field_rank: 1, field_size: 22 }, "e2c05b9f70f3")).toBe(
      "Against the AI (35): 3.2 s faster than the typical AI car · 1st of 22",
    );
  });

  it("nothing for another session, an unknown session, or no comparison", () => {
    expect(aiEndLine(live(), "another")).toBeNull();
    expect(aiEndLine(live(), null)).toBeNull();
    expect(aiEndLine(null, "e2c05b9f70f3")).toBeNull();
    for (const status of ["no_driver_lap", "too_few_ai_cars", "unknown_difficulty", "difficulty_changed", "time_trial"] as const) {
      expect(aiEndLine({ ...live(), status }, "e2c05b9f70f3"), status).toBeNull();
    }
    expect(aiEndLine({ ...live(), ai_difficulty: null }, "e2c05b9f70f3")).toBeNull();
  });

  it("synthetic data says so", () => {
    expect(aiEndLine({ ...live(), synthetic: true }, "e2c05b9f70f3")).toBe(
      "Against the AI (35): 3.8 s slower than the typical AI car · 20th of 20 · synthetic data",
    );
  });
});

describe("Progress: the series against the AI", () => {
  it("groups by car class, newest class first; the newest session's class is shown by default", () => {
    const v = aiSeries(aiFixtures.driverAustria().points, { nowMs: NOW });
    expect(v.classes.map((c) => [c.label, c.sessions])).toEqual([
      ["F1 Modern", 2],
      ["F1 World", 1],
    ]);
    expect(v.classKey).toBe("F1 Modern");
    expect(v.categories).toEqual(["race"]);
    expect(v.dots.map((d) => [d.sessionId, d.level, d.gapPct])).toEqual([
      ["a100cbc9b5bd", 31, -4.96],
      ["332904dbe3de", 31, -6.51],
    ]);
    expect(v.levels).toEqual([31]);
    const world = aiSeries(aiFixtures.driverAustria().points, { nowMs: NOW, classKey: "F1 World" });
    expect(world.dots.map((d) => d.sessionId)).toEqual(["e2c05b9f70f3"]);
    // an unknown class falls back to the newest
    expect(aiSeries(aiFixtures.driverAustria().points, { nowMs: NOW, classKey: "GT3" }).classKey).toBe("F1 Modern");
  });

  it("a category toggle only when the class has more than one; the newest category first", () => {
    const pts = aiFixtures.driverAustria().points;
    const q: AiPacePoint = { ...pts[2]!, session_id: "q1", started_unix: pts[2]!.started_unix + 3600, session_category: "qualifying" };
    const v = aiSeries([...pts, q], { nowMs: NOW });
    expect(v.categories).toEqual(["qualifying", "race"]);
    expect(v.category).toBe("qualifying");
    expect(aiSeries([...pts, q], { nowMs: NOW, category: "race" }).dots).toHaveLength(2);
  });

  it("dots in words, ahead and behind", () => {
    const [behind] = aiSeries(aiFixtures.driverAustria().points, { nowMs: NOW, classKey: "F1 World" }).dots;
    expect(dotWords(behind!)).toBe("AI 35: 3.8 s slower than the typical AI car (5.1% slower) · 20th of 20");
    const ahead = aiSeries(aiFixtures.driverAustria().points, { nowMs: NOW }).dots[1]!;
    expect(dotWords(ahead)).toBe("AI 31: 4.9 s faster than the typical AI car (6.5% faster) · 1st of 18");
  });

  it("a session without a clean lap stays in the list, off the chart, with the AI reference", () => {
    const pts = aiFixtures.driverAustria().points;
    const none: AiPacePoint = { ...pts[0]!, status: "no_driver_lap", driver_best_ms: null, gap_ms: null, gap_pct: null, field_rank: null };
    const v = aiSeries([none], { nowMs: NOW });
    expect(v.dots).toHaveLength(1);
    expect(v.plotted).toBe(0);
    expect(dotWords(v.dots[0]!)).toBe("AI 35: no clean lap · typical AI best 1:14.579");
    expect(aiSeriesSentence(v, null, { poss: "your" })).toBe(
      "No clean lap against the AI here yet: the typical AI car's best lap at AI 35 was 1:14.579.",
    );
  });

  it("synthetic sessions are excluded: synthetic track ids, sessions known to be synthetic, synthetic suggestion keys", () => {
    const pts = aiFixtures.driverAustria().points;
    const synth: AiPacePoint = { ...pts[0]!, session_id: "6f764c9ac84d", track_id: "synthetic:f1:-1", started_unix: pts[2]!.started_unix + 10 };
    expect(isSyntheticPoint(synth)).toBe(true);
    expect(isSyntheticPoint(pts[0]!)).toBe(false);
    expect(isSyntheticPoint(pts[0]!, new Set([pts[0]!.session_id]))).toBe(true);

    const v = aiSeries([...pts, synth], { nowMs: NOW, classKey: "F1 World" });
    expect(v.dots.map((d) => d.sessionId)).toEqual(["e2c05b9f70f3"]);
    expect(v.classes.find((c) => c.key === "F1 World")?.sessions).toBe(1);
    // the caller's synthetic sessions are left out again, whatever the server sends
    const known = aiSeries(pts, { nowMs: NOW, synthetic: new Set(["a100cbc9b5bd", "332904dbe3de"]) });
    expect(known.classes.map((c) => c.label)).toEqual(["F1 World"]);
    expect(aiSeries([synth], { nowMs: NOW }).dots).toEqual([]);
    expect(aiSeriesSentence(aiSeries([synth], { nowMs: NOW }), null, { poss: "your" })).toBeNull();

    const s = aiFixtures.driverAustria().suggestions;
    const synthKey: AiLevelSuggestion = { ...s[0]!, key: { ...s[0]!.key, track_id: "synthetic:f1:17" } };
    expect(suggestionsFor([synthKey, ...s], {})).toEqual(s);
  });

  it("non-ok statuses never become points", () => {
    const pts = aiFixtures.driverAustria().points;
    const bad = { ...pts[0]!, status: "too_few_ai_cars" } as unknown as AiPacePoint;
    expect(aiSeries([bad], { nowMs: NOW }).dots).toEqual([]);
  });

  it("the sentence on top is the server's suggestion for the series on screen, verbatim", () => {
    const data = aiFixtures.driverAustria();
    const v = aiSeries(data.points, { nowMs: NOW });
    const s = suggestionForSeries(data.suggestions, AUSTRIA, v)!;
    expect(s.key.car_class).toBe("F1 Modern");
    expect(aiSeriesSentence(v, s, { poss: "your" })).toBe(
      "At AI 31 your best lap here was 6.5% faster than the typical AI car, so try a higher level. Race at a couple of difficulty levels here and Pitwall can suggest one.",
    );
    const world = aiSeries(data.points, { nowMs: NOW, classKey: "F1 World" });
    expect(suggestionForSeries(data.suggestions, AUSTRIA, world)?.text).toBe(
      "At AI 35 your best lap here was 5.1% slower than the typical AI car, so a lower level should give closer racing. Race at a couple of difficulty levels here and Pitwall can suggest one.",
    );
    // without a suggestion (e.g. mixed weather), the newest session in plain words
    expect(aiSeriesSentence(world, null, { poss: "Alex's" })).toBe("At AI 35 Alex's best lap here was 5.1% slower than the typical AI car.");
  });

  it("the chart's axis: symmetric around level, headroom for the labels, ticks in words", () => {
    expect(gapAxis([-4.96, -6.51])).toEqual({ max: 10, ticks: [-10, -5, 0, 5, 10] });
    expect(gapAxis([5.06])).toEqual({ max: 8, ticks: [-8, -4, 0, 4, 8] });
    expect(gapAxis([])).toEqual({ max: 1, ticks: [-1, -0.5, 0, 0.5, 1] });
    expect(gapAxis([0.2, Number.NaN])).toEqual({ max: 1, ticks: [-1, -0.5, 0, 0.5, 1] });
    expect([-10, -2.5, 0, 4, 1e-12].map(gapTick)).toEqual(["10% faster", "2.5% faster", "level", "4% slower", "level"]);
  });

  it("which pages show the card", () => {
    expect(showAiCard("f1_25", undefined, false)).toBe(true);
    expect(showAiCard("f1_25", { points: [] }, false)).toBe(true); // an empty state says so
    expect(showAiCard("gt7", { points: [] }, false)).toBe(false);
    expect(showAiCard("f1_25", undefined, true)).toBe(false); // an older server without the route
    expect(showAiCard("gt7", aiFixtures.driverAustria(), false)).toBe(true);
  });
});

describe("Coaching: the suggested AI level", () => {
  it("not enough data yet (one level raced here): the guidance sentence only, never a number", () => {
    const s = aiFixtures.driverAustria().suggestions.find((x) => x.key.car_class === "F1 World")!;
    const v = suggestionView(s);
    expect(v).toMatchObject({ kind: "direction", level: null, range: null, confidence: null, bound: null, direction: "lower" });
    expect(v.keyLabel).toBe("Austria · F1 World races · dry");
    expect(v.text).toBe(s.text);
  });

  it("a measured suggestion: the level large, the range, the confidence and the server's sentence", () => {
    const v = suggestionView(measured());
    expect(v).toMatchObject({
      kind: "level",
      level: "AI 38",
      range: "Range 35–41",
      bound: null,
      confidence: { word: "high", label: "High confidence", tone: "default" },
      estimate: false,
      text: "Try AI 38 here (35-41). Measured from 4 races at levels 30, 35, 40, 45.",
    });
  });

  it("an estimate from other tracks is low confidence and says so; a bound reads 'or higher'", () => {
    const e = suggestionView(measured({ basis: "estimate_other_tracks", confidence: "low", slope_sources: ["Silverstone"] }));
    expect(e).toMatchObject({ kind: "level", estimate: true, confidence: { label: "Low confidence · rough estimate", tone: "warning" } });
    expect(suggestionView(measured({ bound: "at_least", level: 45, range: [43, 47] })).bound).toBe("or higher");
    expect(suggestionView(measured({ bound: "at_most", level: 0, range: [0, 2] })).bound).toBe("or lower");
  });

  it("unknown stays unknown: a measured basis without a level shows the sentence only; levels that disagree say so", () => {
    expect(suggestionView(measured({ level: null })).kind).toBe("direction");
    const d = suggestionView({ ...aiFixtures.driverAustria().suggestions[0]!, note: "levels_disagree" });
    expect(d.kind).toBe("direction");
    expect(d.note).toMatch(/do not line up yet/);
  });

  it("suggestions for a track, newest first; key labels", () => {
    const all = aiFixtures.driverAll().suggestions;
    expect(suggestionsFor(all, AUSTRIA).map((s) => s.key.car_class)).toEqual(["F1 Modern", "F1 World"]);
    expect(suggestionsFor(all, { game: "f1_25", trackId: "f1:0" }).map((s) => suggestionKeyLabel(s.key))).toEqual(["Melbourne · F2 races · dry"]);
    expect(suggestionsFor(all, { game: "gt7", trackId: "f1:17" })).toEqual([]);
    expect(suggestionsFor(null, AUSTRIA)).toEqual([]);
  });
});
