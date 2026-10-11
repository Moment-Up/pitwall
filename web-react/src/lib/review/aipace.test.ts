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
  aiCarNamesByClass,
  aiUnusableSentence,
  suggestionAim,
  suggestionSentence,
} from "./aipace";
import { askSuggestions, AI_SUGGESTION, SUGGESTIONS } from "./ask";
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
    text: "Try AI 38 here, between 35 and 41. Measured from 4 races at levels 30, 35, 40 and 45.",
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
    // best lap against best lap, and it says so (a bare "3.8 s slower" reads as a race gap)
    expect(gapToAiWords(3772)).toBe("3.8 s slower than the typical AI car's best lap");
    expect(gapToAiWords(-3219)).toBe("3.2 s faster than the typical AI car's best lap");
    expect(gapToAiWords(-800)).toBe("0.80 s faster than the typical AI car's best lap");
    expect(gapToAiWords(400)).toBe("0.40 s slower than the typical AI car's best lap");
    expect(gapToAiWords(3)).toBe("level with the typical AI car's best lap");
    expect(gapToAiWords(null)).toBeNull();
    for (const ms of [3772, -3219, -800]) expect(gapToAiWords(ms)).not.toMatch(/[-−+]/);
    expect(pctWords(5.06)).toBe("5.1% slower");
    expect(pctWords(-3.26)).toBe("3.3% faster");
    expect(pctWords(0.04)).toBe("level");
    expect(pctWords(null)).toBeNull();
  });

  it("titles and reasons", () => {
    // the game's own name for the setting, "AI difficulty", in every label
    expect(aiPaceTitle(35)).toBe("Pace vs AI · AI difficulty 35");
    expect(aiPaceTitle(0)).toBe("Pace vs AI · AI difficulty 0");
    expect(aiPaceTitle(null)).toBe("Pace vs AI");
    expect(aiPaceReasonText("ok")).toBeNull();
    expect(aiPaceReasonText("too_few_ai_cars")).toBe("Too few AI laps seen");
    // with the session's row: the rule and what was seen; an online lobby says it had other players
    expect(aiPaceReasonText("too_few_ai_cars", { ai_cars: 3, online: false })).toBe("Too few AI laps: needs clean laps from 5 AI cars, saw 3");
    expect(aiPaceReasonText("too_few_ai_cars", { ai_cars: 1, online: true })).toBe("Online session: other players, too few AI cars to compare");
    expect(aiPaceReasonText("unknown_difficulty")).toBe("AI difficulty not reported");
    expect(aiPaceReasonText("difficulty_changed")).toBe("AI difficulty changed mid-session");
  });

  it("what a comparison is built from, exclusions in a fixed order", () => {
    expect(aiEvidenceText(aiFixtures.austria())).toBe("From 19 AI cars, 38 laps · not used: 19 opening laps of the race");
    expect(aiEvidenceText(aiFixtures.melbourne())).toBe(
      "From 21 AI cars, 21 laps · not used: 21 opening laps of the race, 21 laps the game filled in (not driven)",
    );
    // no comparison: nothing was built "from" them
    expect(aiEvidenceText(aiFixtures.monza())).toMatch(/^Seen: 2 AI cars, 2 laps · not used: /);
    expect(exclusionWords({ slow_car: 1, pit_in_out: 2, flashback: 1, new_reason: 3 })).toBe(
      "2 pit laps, 1 lap around a flashback, 1 car far off the pace, 3 new reason",
    );
    expect(exclusionWords({ fast_outlier: 1, red_flag: 2, results_skip: 21, not_ai_driven: 2 })).toBe(
      "2 laps a human drove before the AI took over, 21 laps the game filled in (not driven), 2 laps around a red flag, 1 impossibly fast lap",
    );
    expect(exclusionWords({})).toBeNull();
    expect(exclusionWords({ invalid: 0 })).toBeNull();
  });
});

describe("Summary tile: Pace vs AI · AI difficulty 35", () => {
  it("no AI in the session: no tile (a non-F1 session, one from before the feature, an older server, a time trial)", () => {
    expect(aiPaceTile(null)).toBeNull();
    expect(aiPaceTile(undefined)).toBeNull();
    expect(aiPaceTile({ ...aiFixtures.austria(), status: "time_trial" })).toBeNull();
  });

  it("driver behind: the gap in words, the rank on best laps; advanced adds the fastest AI car", () => {
    const t = aiPaceTile(aiFixtures.austria())!;
    expect(t.title).toBe("Pace vs AI · AI difficulty 35");
    expect(t.change).toEqual({ text: "3.8 s slower", amount: "3.8 s", word: "slower" });
    expect(t.sub).toBe("than the typical AI car's best lap · 20th of 20 on best laps");
    expect(t.synthetic).toBe(false);
    expect(aiPaceTile(aiFixtures.austria(), { advanced: true })!.sub).toBe(
      "than the typical AI car's best lap · 20th of 20 on best laps · fastest AI 1:12.730",
    );
    expect(t.evidence).toBe("From 19 AI cars, 38 laps · not used: 19 opening laps of the race");
    expect(aiPaceTile(aiFixtures.austria(), { brief: true })!.evidence).toBe("From 19 AI cars, 38 laps"); // core summaries
  });

  it("driver ahead (Melbourne, F2): faster, 1st of 22", () => {
    const t = aiPaceTile(aiFixtures.melbourne())!;
    expect(t.change).toEqual({ text: "3.2 s faster", amount: "3.2 s", word: "faster" });
    expect(t.sub).toBe("than the typical AI car's best lap · 1st of 22 on best laps");
    expect(t.evidence).toBe("From 21 AI cars, 21 laps · not used: 21 opening laps of the race, 21 laps the game filled in (not driven)");
  });

  it("level with the typical AI car; an unknown rank is left out, never guessed", () => {
    const t = aiPaceTile({ ...aiFixtures.austria(), gap_ms: 2, gap_pct: 0, field_rank: null, field_size: null })!;
    expect(t.change?.text).toBe("level");
    expect(t.sub).toBe("with the typical AI car's best lap");
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
    expect(t.sub).toBe("AI difficulty not reported");
    expect(t.strip).toBeNull();
    const changed = aiPaceTile({ ...unknown, status: "difficulty_changed" })!;
    expect(changed.sub).toBe("AI difficulty changed mid-session");
  });

  it("too few AI cars (Monza): '-' with the reason, even if a gap were sent", () => {
    const t = aiPaceTile(aiFixtures.monza())!;
    expect(t).toMatchObject({
      title: "Pace vs AI · AI difficulty 35",
      change: null,
      sub: "Too few AI laps: needs clean laps from 5 AI cars, saw 2",
      strip: null,
    });
    expect(t.evidence).toBe(
      "Seen: 2 AI cars, 2 laps · not used: 19 opening laps of the race, 19 laps not seen from their start, 17 laps the game filled in (not driven)",
    );
    // an online lobby (other players): says so
    expect(aiPaceTile({ ...aiFixtures.monza(), online: true })!.sub).toBe("Online session: other players, too few AI cars to compare");
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
    expect(aiEndLine(live(), "e2c05b9f70f3")).toBe(
      "AI difficulty 35: best lap 3.8 s slower than the typical AI car's best lap · 20th of 20 on best laps",
    );
    expect(aiEndLine({ ...live(), gap_ms: -3219, field_rank: 1, field_size: 22 }, "e2c05b9f70f3")).toBe(
      "AI difficulty 35: best lap 3.2 s faster than the typical AI car's best lap · 1st of 22 on best laps",
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
      "AI difficulty 35: best lap 3.8 s slower than the typical AI car's best lap · 20th of 20 on best laps · synthetic data",
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
    expect(dotWords(behind!)).toBe("AI 35: 3.8 s slower than the typical AI car's best lap (5.1% slower) · 20th of 20 on best laps");
    const ahead = aiSeries(aiFixtures.driverAustria().points, { nowMs: NOW }).dots[1]!;
    expect(dotWords(ahead)).toBe("AI 31: 4.9 s faster than the typical AI car's best lap (6.5% faster) · 1st of 18 on best laps");
    expect(dotWords({ ...ahead, online: true })).toMatch(/ · online$/);
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

  it("the sentence on top is the suggestion for the series on screen, about the driver who is viewed", () => {
    const data = aiFixtures.driverAustria();
    const v = aiSeries(data.points, { nowMs: NOW });
    const s = suggestionForSeries(data.suggestions, AUSTRIA, v)!;
    expect(s.key.car_class).toBe("F1 Modern");
    const mine =
      "At AI 31 your best lap here was 4.9 s (6.5%) faster than the typical AI car's best lap, so try a higher level. Race here once more at AI 36 or higher and Pitwall can suggest a level.";
    expect(aiSeriesSentence(v, s, { poss: "your" })).toBe(mine);
    expect(s.text).toBe(mine); // the real backend's own sentence, word for word
    expect(aiSeriesSentence(v, s, { poss: "Sam's" })).toBe(mine.replace("your best lap", "Sam's best lap"));
    const world = aiSeries(data.points, { nowMs: NOW, classKey: "F1 World" });
    expect(suggestionForSeries(data.suggestions, AUSTRIA, world)?.text).toBe(
      "At AI 35 your best lap here was 3.8 s (5.1%) slower than the typical AI car's best lap, so a lower level should give closer racing. Race here once more at AI 30 or lower and Pitwall can suggest a level.",
    );
    // without a suggestion (e.g. mixed weather), the newest session in plain words
    expect(aiSeriesSentence(world, null, { poss: "Alex's" })).toBe("At AI 35 Alex's best lap here was 5.1% slower than the typical AI car's best lap.");
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
  it("not enough data yet (one level raced here): which way to go and the next level, never a level of its own", () => {
    const s = aiFixtures.driverAustria().suggestions.find((x) => x.key.car_class === "F1 World")!;
    expect(s.next_level).toBe(30);
    const v = suggestionView(s);
    expect(v).toMatchObject({ kind: "direction", level: null, range: null, confidence: null, bound: null, direction: "lower", headline: "Lower than AI 35" });
    expect(v.keyLabel).toBe("Austria · F1 World class · races · dry");
    expect(v.text).toBe(s.text); // for the driver in the seat: the server's sentence, word for word
  });

  it("a measured suggestion: the level large, the range, the confidence and the server's sentence", () => {
    const v = suggestionView(measured());
    expect(v).toMatchObject({
      kind: "level",
      level: "AI 38",
      range: "Range 35–41",
      bound: null,
      confidence: { word: "high", label: "High confidence", tone: "default" },
      measured: true,
      estimate: false,
      text: "Try AI 38 here, between 35 and 41. Measured from 4 races at levels 30, 35, 40 and 45.",
    });
  });

  it("an estimate from other tracks is low confidence and says so; a bound reads 'or higher'", () => {
    const e = suggestionView(measured({ basis: "estimate_other_tracks", confidence: "low", slope_sources: ["Silverstone"] }));
    expect(e).toMatchObject({ kind: "level", estimate: true, confidence: { label: "Low confidence · rough estimate", tone: "warning" } });
    expect(e.level).toBe("about AI 38");
    // a bound: "or higher" / "or lower" and never a range around it (even if an older server sent one)
    expect(suggestionView(measured({ bound: "at_least", level: 45, range: [43, 47] }))).toMatchObject({ bound: "or higher", range: null });
    expect(suggestionView(measured({ bound: "at_most", level: 0, range: [0, 2] }))).toMatchObject({ bound: "or lower", range: null });
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
    expect(suggestionsFor(all, { game: "f1_25", trackId: "f1:0" }).map((s) => suggestionKeyLabel(s.key))).toEqual(["Melbourne · F2 class · races · dry"]);
    expect(suggestionsFor(all, { game: "gt7", trackId: "f1:17" })).toEqual([]);
    expect(suggestionsFor(null, AUSTRIA)).toEqual([]);
  });
});


describe("the suggestion's sentence is about the driver who is viewed", () => {
  const key = { game: "f1_25", track_id: "f1:17", track_name: "Austria", car_class: "F1 World", session_category: "race" as const, weather_class: "dry" as const };
  const base: AiLevelSuggestion = {
    key,
    basis: "direction_only",
    level: null,
    range: null,
    bound: null,
    confidence: null,
    direction: "lower",
    note: null,
    latest_level: 35,
    latest_gap_pct: 5.06,
    latest_gap_ms: 3772,
    next_level: 30,
    target_gap_pct: 0,
    sessions_used: 1,
    levels_used: [35],
    slope_pct_per_level: null,
    slope_sources: [],
    // the server's own sentence (analysis/ai_level.py; tests/unit/test_ai_level.py)
    text: "At AI 35 your best lap here was 3.8 s (5.1%) slower than the typical AI car's best lap, so a lower level should give closer racing. Race here once more at AI 30 or lower and Pitwall can suggest a level.",
  };

  it("for the driver in the seat it is the server's sentence, word for word, in every tier", () => {
    const cases: AiLevelSuggestion[] = [
      base,
      {
        ...base,
        direction: "higher",
        latest_level: 35,
        latest_gap_pct: -3.26,
        latest_gap_ms: null,
        next_level: 40,
        text: "At AI 35 your best lap here was 3.3% faster than the typical AI car's best lap, so try a higher level. Race here once more at AI 40 or higher and Pitwall can suggest a level.",
      },
      {
        ...base,
        direction: "about_right",
        latest_gap_pct: 0.4,
        latest_gap_ms: null,
        next_level: null,
        text: "At AI 35 your best lap here was 0.4% slower than the typical AI car's best lap: about level, so AI 35 looks about right. Racing here once more at AI 30 or 40 would let Pitwall measure your level.",
      },
      {
        ...base,
        basis: "measured",
        level: 35,
        range: [33, 37],
        confidence: "medium",
        sessions_used: 2,
        levels_used: [30, 40],
        text: "Try AI 35 here, between 33 and 37. Measured from 2 races at levels 30 and 40.",
      },
      {
        ...base,
        basis: "measured",
        level: 45,
        bound: "at_least",
        confidence: "low",
        sessions_used: 2,
        levels_used: [30, 35],
        text: "Try AI 45 or higher here: the trend of your 2 races at levels 30 and 35 puts level racing with the typical AI car above AI 45.",
      },
      {
        ...base,
        basis: "estimate_other_tracks",
        level: 25,
        range: [22, 28],
        confidence: "low",
        slope_sources: ["Silverstone"],
        text: "Estimated AI level here: about 25, between 22 and 28. Based on how the AI's pace changed with level at Silverstone; race here at another level to measure it.",
      },
      {
        ...base,
        basis: "estimate_other_tracks",
        level: 20,
        bound: "at_most",
        confidence: "low",
        slope_sources: ["Silverstone"],
        text: "Estimated AI level here: 20 or lower. Based on how the AI's pace changed with level at Silverstone; race here at another level to measure it.",
      },
      {
        ...base,
        note: "levels_disagree",
        next_level: null,
        sessions_used: 2,
        levels_used: [30, 40],
        latest_level: 40,
        latest_gap_pct: 2.1,
        latest_gap_ms: null,
        text: "At AI 40 your best lap here was 2.1% slower than the typical AI car's best lap, so a lower level should give closer racing. Your races here at levels 30 and 40 do not yet show the AI getting faster with level, so Pitwall cannot suggest one yet.",
      },
    ];
    for (const c of cases) expect(suggestionSentence(c, { poss: "your" }), c.text).toBe(c.text);
  });

  it("a parent viewing a child reads about the child, never 'your'", () => {
    const sam = { poss: "Sam's", Poss: "Sam's" };
    expect(suggestionSentence(base, sam)).toBe(
      "At AI 35 Sam's best lap here was 3.8 s (5.1%) slower than the typical AI car's best lap, so a lower level should give closer racing. Race here once more at AI 30 or lower and Pitwall can suggest a level.",
    );
    const bound: AiLevelSuggestion = { ...base, basis: "measured", level: 45, bound: "at_least", sessions_used: 2, levels_used: [30, 35] };
    expect(suggestionSentence(bound, sam)).toContain("the trend of Sam's 2 races at levels 30 and 35");
    expect(suggestionSentence({ ...base, note: "levels_disagree", levels_used: [30, 40] }, sam)).toContain("Sam's races here at levels 30 and 40");
    expect(suggestionSentence({ ...base, direction: "about_right", latest_gap_pct: 0.4 }, sam)).toContain("would let Pitwall measure Sam's level");
    for (const c of [base, bound]) expect(suggestionSentence(c, sam)).not.toMatch(/\byour\b/i);
    // the card and the Progress sentence use it
    expect(suggestionView(base, sam).text).toBe(suggestionSentence(base, sam));
  });

  it("the next level is named; an older server without one, and the game's limits, still read right", () => {
    expect(suggestionSentence({ ...base, next_level: undefined }, { poss: "your" })).toMatch(/Race here once more at a level 5 or more lower and Pitwall can suggest a level\.$/);
    expect(suggestionSentence({ ...base, latest_level: 3, next_level: 0 }, { poss: "your" })).toMatch(/Race here once more at AI 0 and Pitwall/);
    expect(suggestionSentence({ ...base, latest_level: 0, next_level: null }, { poss: "your" })).toMatch(/AI 0 is already the game's lowest level\.$/);
  });

  it("the card: a level large (an estimate 'about'), a range only without a bound, where it comes from", () => {
    const m = suggestionView({ ...base, basis: "measured", level: 38, range: [35, 41], confidence: "high", sessions_used: 4, levels_used: [30, 35, 40, 45] });
    expect(m).toMatchObject({ kind: "level", level: "AI 38", range: "Range 35–41", measured: true, estimate: false, headline: null });
    const e = suggestionView({ ...base, basis: "estimate_other_tracks", level: 25, range: [22, 28], confidence: "low", slope_sources: ["Silverstone"] });
    expect(e).toMatchObject({ level: "about AI 25", range: "Range 22–28", measured: false, estimate: true });
    // a bound never shows a range, even from an older server that sent one
    const b = suggestionView({ ...base, basis: "estimate_other_tracks", level: 20, range: [17, 23], bound: "at_most", confidence: "low", slope_sources: ["Silverstone"] });
    expect(b).toMatchObject({ level: "AI 20", bound: "or lower", range: null });
    // one level raced: which way, large, and no number of its own
    expect(suggestionView(base)).toMatchObject({ kind: "direction", headline: "Lower than AI 35", level: null, range: null, measured: false });
    expect(suggestionView({ ...base, direction: "higher" }).headline).toBe("Higher than AI 35");
    expect(suggestionView({ ...base, direction: "about_right" }).headline).toBe("AI 35 looks about right");
    expect(suggestionAim(0)).toBe("Aim: a best lap level with the typical AI car's (mid-pack)");
    expect(suggestionAim(2)).toBe("Aim: a best lap 2.0% slower than the typical AI car's");
  });

  it("the key names the class as a class, with the car when it differs", () => {
    expect(suggestionKeyLabel(key)).toBe("Austria · F1 World class · races · dry");
    expect(suggestionKeyLabel(key, "F1 Generic")).toBe("Austria · F1 World class (F1 Generic) · races · dry");
    expect(suggestionKeyLabel({ ...key, car_class: null })).toBe("Austria · Unknown class · races · dry");
    const names = aiCarNamesByClass([
      { car_class: "F1 World", car_name: "Old car", started_unix: 1 },
      { car_class: "F1 World", car_name: "F1 Generic", started_unix: 2 },
      { car_class: "F2", car_name: null, started_unix: 3 },
      { car_class: "F3", car_name: "Unknown team (id 214)", started_unix: 4 },
    ]);
    expect([...names]).toEqual([["F1 World", "F1 Generic"]]);
  });
});

describe("a race that could not be compared is said so, never 'no races'", () => {
  it("names the newest one's level and reason, about the viewed driver", () => {
    const monza = { session_id: "m", started_unix: 1, session_category: "race" as const, ai_difficulty: 35, status: "too_few_ai_cars" as const, online: false, ai_cars: 2 };
    expect(aiUnusableSentence([monza], { poss: "your" })).toBe(
      "Your race here at AI difficulty 35 could not be compared with the AI: too few clean AI laps were seen.",
    );
    expect(aiUnusableSentence([monza], { poss: "Sam's" })).toBe(
      "Sam's race here at AI difficulty 35 could not be compared with the AI: too few clean AI laps were seen.",
    );
    expect(aiUnusableSentence([{ ...monza, online: true }], { poss: "your" })).toMatch(/online session with other players/);
    expect(aiUnusableSentence([monza, { ...monza, status: "difficulty_changed", ai_difficulty: null }], { poss: "your" })).toBe(
      "2 sessions here against the AI could not be compared; the newest: the AI difficulty changed during the session.",
    );
    expect(aiUnusableSentence([], { poss: "your" })).toBeNull();
    expect(aiUnusableSentence(undefined, { poss: "your" })).toBeNull();
  });
});

describe("Ask offers the AI question only for a session raced against the AI", () => {
  it("adds it after the first three", () => {
    expect(askSuggestions()).toEqual(SUGGESTIONS);
    const ai = askSuggestions({ aiPace: true });
    expect(ai).toHaveLength(SUGGESTIONS.length + 1);
    expect(ai[3]).toBe(AI_SUGGESTION);
  });
});
