// Review › Coaching › "How corners work" (technique knowledge spec section 4) on the real graph: three driver
// profiles from the spec (the owner's trail-braking F1 25 style, a GT7 beginner, a manual classic car), each told what
// fits them; unknown stays unknown ("Not known yet", never "for other drivers"); the server's verdicts win when the
// session variant sends them; Ed is credited; nothing on screen tells a driver to brake later.
import { describe, expect, it } from "vitest";
import type { KnowledgeCondition } from "../endpoints/knowledge";
import { BEGINNER_GT7, CLASSIC_MANUAL, knowledgeFixtureBlocks, knowledgeFixtures, OWNER_F1, withSession } from "./testkit";
import {
  allTri,
  anyTri,
  conditionTri,
  contextChips,
  contextNote,
  cornersView,
  baseRateText,
  creditLine,
  faultCauseLines,
  faultGroups,
  fitOf,
  faultFitLabel,
  FIT_LABEL,
  fitLabel,
  knowledgeDensity,
  measurementText,
  pageContext,
  phaseViews,
  sourceGroups,
  STATUS_LABEL,
  TIER_LABEL,
  unknownKeys,
  type PhaseView,
} from "./view";

const g = knowledgeFixtures.graph();
const conds = new Map(g.conditions.map((c) => [c.id, c]));
const technique = (id: string) => g.techniques.find((t) => t.id === id)!;
const fault = (id: string) => g.faults.find((f) => f.id === id)!;
const item = (phases: PhaseView[], id: string) => phases.flatMap((p) => [...p.shown, ...p.others]).find((t) => t.id === id)!;

describe("the graph fixture", () => {
  it("is the server's own payload, not a recording of a game", () => {
    const blocks = knowledgeFixtureBlocks();
    expect(blocks).toHaveLength(1);
    expect(blocks[0]!.block.tier).toBe("backend");
    expect(blocks[0]!.block.source).toMatch(/load_graph\(\)\.to_payload\(\)/);
    expect(g.valid).toBe(true);
    expect(g.errors).toEqual([]);
    expect(g.phases.map((p) => p.id)).toEqual(["approach", "braking", "turn_in", "mid_corner", "apex", "exit"]);
  });
});

describe("conditions, three-valued", () => {
  it("all / any keep unknown apart from false", () => {
    expect(allTri([true, true])).toBe(true);
    expect(allTri([true, null])).toBeNull();
    expect(allTri([null, false])).toBe(false);
    expect(allTri([])).toBe(true);
    expect(anyTri([false, null])).toBeNull();
    expect(anyTri([null, true])).toBe(true);
    expect(anyTri([false])).toBe(false);
    expect(anyTri([])).toBe(false);
  });

  it("an unknown trait satisfies nothing, not even 'ne' or 'false' (the server's rule), and says so", () => {
    expect(conditionTri("abs_off", {}, conds)).toBeNull();
    expect(conditionTri("abs_off", { abs: false }, conds)).toBe(true);
    expect(conditionTri("abs_off", { abs: true }, conds)).toBe(false);
    expect(conditionTri("dry", { wet: null }, conds)).toBeNull();
    expect(conditionTri("skill_not_beginner", { skill: "advanced" }, conds)).toBe(true);
    expect(conditionTri("gearbox_two_pedal", { gearbox: "h_pattern" }, conds)).toBe(false);
    // Compound: no ABS AND low downforce.
    expect(conditionTri("no_abs_low_downforce", { abs: false }, conds)).toBeNull();
    expect(conditionTri("no_abs_low_downforce", { abs: false, downforce: "low" }, conds)).toBe(true);
    expect(conditionTri("no_abs_low_downforce", { abs: true }, conds)).toBe(false);
    expect(conditionTri("no_such_condition", { skill: "advanced" }, conds)).toBe(false);
  });

  it("a cycle never holds (the server rejects one; the screen must not hang on it)", () => {
    const loop = new Map<string, KnowledgeCondition>([
      ["a", { ...conds.get("no_abs_low_downforce")!, id: "a", all_of: ["b"] }],
      ["b", { ...conds.get("no_abs_low_downforce")!, id: "b", all_of: ["a"] }],
    ]);
    expect(conditionTri("a", { abs: false, downforce: "low" }, loop)).toBe(false);
  });
});

describe("what fits whom (spec: any kind of driver)", () => {
  it("the owner (advanced, trail-braking, F1 car with paddles): trail braking fits, the straight-line style is for others", () => {
    const phases = phaseViews(withSession(g, OWNER_F1), OWNER_F1);
    expect(item(phases, "trail_braking").fit).toEqual({
      fit: "fits",
      universal: false,
      reason: "Matches: Trail-braking driver; High downforce.",
    });
    for (const id of ["straight_line_braking", "release_with_speed_to_spare", "coast_to_apex"]) {
      expect(item(phases, id).fit).toMatchObject({ fit: "other", reason: "For: Beginner or Straight-line braking driver or No ABS, low downforce." });
    }
    // The game blips on paddle downshifts: rev-matching is for H-pattern gearboxes; left-foot braking fits paddles.
    expect(item(phases, "rev_match_downshift").fit).toMatchObject({ fit: "other", reason: "For: H-pattern gearbox." });
    expect(item(phases, "left_foot_braking").fit).toMatchObject({ fit: "fits", reason: "Matches: No clutch pedal." });
    expect(item(phases, "fuel_save_lift_and_coast").fit).toMatchObject({ fit: "other", reason: "For: Saving fuel." });
    expect(item(phases, "flat_to_brake_marker").fit).toEqual({ fit: "fits", universal: true, reason: "For every driver and car." });
  });

  it("a GT7 beginner: Ed's straight-line corner fits; trail braking depends on what is not known yet", () => {
    const phases = phaseViews(g, BEGINNER_GT7);
    for (const id of ["straight_line_braking", "release_with_speed_to_spare", "coast_to_apex"]) {
      expect(item(phases, id).fit).toMatchObject({ fit: "fits", reason: "Matches: Beginner." });
    }
    expect(item(phases, "trail_braking").fit).toEqual({
      fit: "unknown",
      universal: false,
      reason: "For: Trail-braking driver or High downforce. Not known yet: your braking style and the car's downforce.",
    });
    expect(item(phases, "rev_match_downshift").fit).toMatchObject({ fit: "unknown" });
    expect(item(phases, "rev_match_downshift").fit.reason).toMatch(/Not known yet: the gearbox\.$/);
    expect(unknownKeys(technique("left_foot_braking"), BEGINNER_GT7, conds)).toEqual(["gearbox"]);
  });

  it("a manual classic car with no ABS, driven straight-line: blips and straight-line braking fit, left-foot braking does not", () => {
    const phases = phaseViews(g, CLASSIC_MANUAL);
    expect(item(phases, "rev_match_downshift").fit).toMatchObject({ fit: "fits", reason: "Matches: H-pattern gearbox." });
    expect(item(phases, "straight_line_braking").fit).toMatchObject({
      fit: "fits",
      reason: "Matches: Straight-line braking driver; No ABS, low downforce.",
    });
    expect(item(phases, "trail_braking").fit.fit).toBe("other");
    expect(item(phases, "left_foot_braking").fit).toMatchObject({ fit: "other", reason: "For: No clutch pedal." });
  });

  it("with only the profile's level (a server without the session variant), the rest stays 'not known yet'", () => {
    const c = pageContext(undefined, "advanced");
    expect(c).toEqual({ ctx: { skill: "advanced" }, source: "profile" });
    const phases = phaseViews(g, c.ctx);
    expect(item(phases, "straight_line_braking").fit.fit).toBe("unknown");
    expect(item(phases, "trail_braking").fit.fit).toBe("unknown");
    expect(item(phases, "single_smooth_turn_in").fit.fit).toBe("fits");
    expect(pageContext(null, null)).toEqual({ ctx: {}, source: "none" });
    expect(pageContext(OWNER_F1, "beginner").source).toBe("server");
    expect(contextNote(c)).toMatch(/your level only/);
  });

  it("the server's verdict wins; the screen only tells 'not known yet' apart from 'for other drivers'", () => {
    const why = "This game does not send the brake pedal for this car.";
    const s = withSession(g, OWNER_F1, {
      progressive_brake_release: { applies: false, why_not: why },
      trail_braking: { applies: false, why_not: null },
      rev_match_downshift: { applies: true },
    });
    const phases = phaseViews(s, OWNER_F1);
    expect(item(phases, "progressive_brake_release").fit).toMatchObject({ fit: "other", reason: why });
    expect(item(phases, "trail_braking").fit).toMatchObject({ fit: "other", reason: "For: Trail-braking driver or High downforce." });
    expect(item(phases, "rev_match_downshift").fit.fit).toBe("fits");
    const unknown = withSession(g, BEGINNER_GT7, { trail_braking: { applies: false, why_not: "Braking style not detected yet" } });
    expect(item(phaseViews(unknown, BEGINNER_GT7), "trail_braking").fit).toMatchObject({
      fit: "unknown",
      reason: "Braking style not detected yet.",
    });
  });
});

describe("phases", () => {
  it("in driving order, each technique once: what fits or is not known shown, other drivers' apart", () => {
    const phases = phaseViews(g, OWNER_F1);
    expect(phases.map((p) => p.order)).toEqual([1, 2, 3, 4, 5, 6]);
    const ids = phases.flatMap((p) => [...p.shown, ...p.others].map((t) => t.id));
    expect(ids.sort()).toEqual(g.techniques.map((t) => t.id).sort());
    for (const p of phases) {
      for (const t of p.shown) expect(t.fit.fit).not.toBe("other");
      for (const t of p.others) expect(t.fit.fit).toBe("other");
      expect(p.summary.length).toBeGreaterThan(20);
    }
    const braking = phases.find((p) => p.id === "braking")!;
    expect(braking.shown[0]!.fit.fit).toBe("fits");
    expect(braking.others.map((t) => t.id)).toEqual(expect.arrayContaining(["straight_line_braking", "rev_match_downshift"]));
  });

  it("alternatives both ways, with their own fit; signals Pitwall does not compute yet are marked", () => {
    const phases = phaseViews(g, OWNER_F1);
    expect(item(phases, "straight_line_braking").alternatives).toEqual([{ id: "trail_braking", name: "Trail braking", fit: "fits" }]);
    expect(item(phases, "trail_braking").alternatives.map((a) => a.id)).toEqual(
      expect.arrayContaining(["straight_line_braking", "release_with_speed_to_spare", "coast_to_apex"]),
    );
    expect(item(phases, "trail_braking").signals).toContainEqual({ id: "trail_brake_m", name: "Trail-braking distance", measured: true });
    expect(item(phases, "single_smooth_turn_in").signals).toEqual([{ id: "steering_reversals", name: "Steering corrections", measured: false }]);
  });
});

describe("faults Pitwall checks", () => {
  it("the eight coached kinds apart from the ones not coached yet, by status then phase", () => {
    const f = faultGroups(g, OWNER_F1);
    expect(f.coached.map((x) => x.id).sort()).toEqual(
      ["brake_early", "brake_late_overdrive", "overspeed_apex", "low_min_speed", "late_throttle", "coasting", "exit_gain", "incident"].sort(),
    );
    expect(f.coached.every((x) => x.statusLabel === "Coached now")).toBe(true);
    expect(f.coached.find((x) => x.id === "exit_gain")!.positive).toBe(true);
    expect(f.notCoached.length).toBe(g.faults.length - 8);
    const statuses = f.notCoached.map((x) => x.status);
    expect(statuses).toEqual([...statuses].sort((a, b) => ["experimental", "planned", "context_only"].indexOf(a) - ["experimental", "planned", "context_only"].indexOf(b)));
    expect(f.notCoached.at(-1)!.statusLabel).toBe(STATUS_LABEL.context_only);
  });

  it("causes Pitwall tells apart, measurements in plain numbers, and faults that are not for this car", () => {
    const f = faultGroups(g, OWNER_F1);
    const lms = f.coached.find((x) => x.id === "low_min_speed")!;
    expect(lms.causes.map((c) => c.name)).toEqual(["Over-braking", "Slowest point came sooner", "Less grip"]);
    // none of the three holds clearly more often with a low minimum speed than without (the base-rate check)
    expect(faultCauseLines(lms)).toEqual(["Also measured, not shown to tell it apart: Over-braking · Slowest point came sooner · Less grip"]);
    const coasting = f.coached.find((x) => x.id === "coasting")!;
    expect(faultCauseLines(coasting)).toEqual([
      "Causes Pitwall can tell apart: Early brake release",
      "Also measured, not shown to tell it apart: Waiting for the car to rotate",
    ]);
    expect(coasting.measured).toContain(
      "Early brake release: on 43% of these points, 20% of other corner-laps (26 of 60, 161 of 812; 2026-10-15)",
    );
    expect(lms.measured).toContain("Less grip: on 23% of these points, 14% of other corner-laps (126 of 550, 84 of 599; 2026-10-15)");
    expect(faultCauseLines(f.coached.find((x) => x.id === "brake_early")!)).toEqual([]);
    expect(baseRateText("X", { fault: "f", fault_laps: 0, fault_held: 0, other_laps: 10, other_held: 1, date: "2026-10", source: "s", note: null })).toBe(
      "X: not checked yet (2026-10)",
    );
    // an older server sends neither the flag nor the checks: every cause is only also measured, no base-rate line
    const old = structuredClone(g);
    for (const c of old.causes) {
      delete c.discriminates;
      delete c.measured;
    }
    const oldCoasting = faultGroups(old, OWNER_F1).coached.find((x) => x.id === "coasting")!;
    expect(faultCauseLines(oldCoasting)).toEqual(["Also measured, not shown to tell it apart: Early brake release · Waiting for the car to rotate"]);
    expect(oldCoasting.measured.some((m) => m.includes("other corner-laps"))).toBe(false);
    const overlap = f.notCoached.find((x) => x.id === "pedal_overlap")!;
    expect(overlap.measured[0]).toBe("Fires on corner-laps (Ed's detector): 66.8% (2026-10-14)");
    expect(f.notCoached.find((x) => x.id === "missed_blip")!.fit).toMatchObject({ fit: "other", reason: "For: H-pattern gearbox." });
    expect(faultGroups(g, BEGINNER_GT7).notCoached.find((x) => x.id === "missed_blip")!.fit.fit).toBe("unknown");
    expect(measurementText({ metric: "", value: 0.05, unit: "s", date: "2026-10", source: "x", note: null })).toBe("Measured: 0.05 s (2026-10)");
  });
});

describe("real-world measurements on techniques", () => {
  it("each line says what was measured and where it comes from", () => {
    const tb = phaseViews(g, OWNER_F1).flatMap((p) => [...p.shown, ...p.others]).find((t) => t.id === "trail_braking")!;
    expect(tb.measured[0]).toBe(
      "Real F1 qualifying braking zones trail-braked: 72% (2026-10-15) - Car data of real 2025 Formula 1 qualifying laps (OpenF1)",
    );
    expect(tb.measured.some((m) => m.startsWith("Within one driver") && m.includes("AssettoCorsaGym"))).toBe(true);
    // an older server sends no measurements: none shown
    const old = structuredClone(g);
    for (const t of old.techniques) delete t.measured;
    expect(phaseViews(old, OWNER_F1).flatMap((p) => [...p.shown, ...p.others]).every((t) => t.measured.length === 0)).toBe(true);
  });
});

describe("faults Pitwall checks, for one session", () => {
  it("a session variant leaves out the causes that cannot be named for its driver and game", () => {
    // edited: the plain graph with a GT7 session's per-cause verdicts (pitwall.knowledge.session.session_payload)
    const gt7 = structuredClone(g);
    for (const c of gt7.causes) {
      Object.assign(c, c.id === "ready_earlier" ? { applies: false, why_not: "GT7 does not send lateral g" } : { applies: true, why_not: null });
    }
    const late = (k: typeof g) => faultGroups(k, BEGINNER_GT7).coached.find((x) => x.id === "late_throttle")!.causes.map((c) => c.id);
    expect(late(gt7)).toEqual(["traction_limited"]);
    expect(late(g)).toEqual(["traction_limited", "ready_earlier"]); // the plain graph: every cause
  });
});

describe("sources", () => {
  it("credit Ed first, then published coaching, then Pitwall's own; links only when they are web links", () => {
    const s = sourceGroups(g);
    expect(s.edAuthor).toBe("Ed (Pitwall tester)");
    expect(s.ed.map((x) => x.id).sort()).toEqual(["ed_corner_brief", "ed_fault_checklist", "ed_patches"]);
    expect(s.ed.every((x) => x.tierLabel === "Ed's brief")).toBe(true);
    expect(s.published.length).toBeGreaterThanOrEqual(7);
    expect(s.published.every((x) => x.tier === "expert")).toBe(true);
    for (const x of [...s.ed, ...s.published, ...s.external, ...s.pitwall]) if (x.url) expect(x.url).toMatch(/^https?:\/\//);
    expect(s.pitwall.every((x) => !["brief", "expert", "external"].includes(x.tier))).toBe(true);
    expect(s.ed.length + s.published.length + s.external.length + s.pitwall.length).toBe(g.sources.length);
    // real-world data measured by Pitwall's scripts is its own group, cited by the techniques' measurements
    expect(s.external.map((x) => x.id).sort()).toEqual(["acgym_human_laps", "openf1_2025_qualifying"]);
    expect(s.external.every((x) => x.tierLabel === "Real-world data, measured by Pitwall" && x.cited > 0)).toBe(true);
    // Ed's brief is cited by the techniques it shaped.
    expect(s.ed.find((x) => x.id === "ed_corner_brief")!.cited).toBeGreaterThan(10);
    expect(creditLine(s)).toMatch(/^From Ed \(Pitwall tester\): .*Idealised corner brief and self-check.*Technique-fault checklist/);
    expect(creditLine({ ed: [], edAuthor: null })).toBeNull();
  });
});

describe("context chips and the section", () => {
  it("say the known traits in the graph's own words", () => {
    expect(contextChips(OWNER_F1, g.conditions)).toEqual([
      "Advanced",
      "Trail-braking driver",
      "Rarely coasts",
      "F1 game",
      "F1 car",
      "High downforce",
      "No ABS",
      "No traction control",
      "Paddles with auto-blip",
      "Dry track",
    ]);
    expect(contextChips(BEGINNER_GT7, g.conditions)).toEqual(["Beginner", "Gran Turismo 7", "Other car"]);
    expect(contextChips({}, g.conditions)).toEqual([]);
  });

  it("cornersView uses the server's Context when it sends one, else the profile's level", () => {
    expect(cornersView(g, "beginner").context.source).toBe("profile");
    expect(cornersView(g, "beginner").chips).toEqual(["Beginner"]);
    const v = cornersView(withSession(g, OWNER_F1), "beginner");
    expect(v.context.source).toBe("server");
    expect(v.chips[0]).toBe("Advanced");
    expect(v.tiers.brief).toMatch(/not validated by Pitwall/);
  });

  it("labels never present expert or brief knowledge as Pitwall's own validation", () => {
    expect(TIER_LABEL.expert).toBe("Published coaching");
    expect(TIER_LABEL.brief).toBe("Ed's brief");
    expect(Object.values(FIT_LABEL)).toEqual(["Fits you", "For other drivers", "Not known yet"]);
    expect(fitLabel("fits", "Alex")).toBe("Fits Alex");
    expect(faultFitLabel("other")).toBe("Does not apply here");
    expect(faultFitLabel("fits", "Alex")).toBe("Applies to Alex");
    expect(faultFitLabel("unknown")).toBe("Not known yet");
    expect(fitLabel("other", "Alex")).toBe("For other drivers");
    expect(contextNote({ ctx: {}, source: "server" }, "Alex")).toBe("Matched to the driver and car of Alex's last session here.");
  });
});

describe("density: beginners read the narrative, advanced drivers get the detail", () => {
  it("follows the levels", () => {
    expect(knowledgeDensity("beginner")).toMatchObject({ detail: "none", othersOpen: false, tiers: false, notCoached: "hidden", textPx: 18 });
    expect(knowledgeDensity("intermediate")).toMatchObject({ detail: "fold", alternatives: true, notCoached: "fold", causes: true, textPx: 16 });
    expect(knowledgeDensity("advanced")).toMatchObject({ detail: "open", othersOpen: true, tiers: true, signals: true, notCoached: "open", measured: true, sourcesOpen: true });
  });
});

describe("words on screen obey the graph's constraints (no 'brake later', 'brake less', ...)", () => {
  it("every reason, note, chip and shown text passes every forbidden pattern (praise excepted where the rule allows)", () => {
    const patterns = g.constraints.flatMap((c) => c.forbidden.map((p) => ({ c, re: new RegExp(p, "i") })));
    expect(patterns.length).toBeGreaterThan(4);
    const texts: { text: string; praise: boolean }[] = [];
    for (const ctx of [OWNER_F1, BEGINNER_GT7, CLASSIC_MANUAL, {}]) {
      const v = cornersView(withSession(g, ctx), null);
      texts.push(...v.chips.map((text) => ({ text, praise: false })));
      texts.push({ text: contextNote(v.context), praise: false });
      for (const p of v.phases) {
        texts.push({ text: `${p.name} ${p.summary}`, praise: false });
        for (const t of [...p.shown, ...p.others]) texts.push({ text: `${t.name}. ${t.summary} ${t.detail} ${t.fit.reason}`, praise: false });
      }
      for (const f of [...v.faults.coached, ...v.faults.notCoached]) {
        texts.push({ text: `${f.name}. ${f.summary} ${f.fit.reason}`, praise: f.positive });
      }
    }
    for (const { text, praise } of texts) {
      for (const { c, re } of patterns) {
        if (praise && c.except_praise) continue;
        expect(re.test(text), `${c.id}: ${text}`).toBe(false);
      }
    }
    expect(fitOf(technique("trail_braking"), {}, conds).reason).not.toMatch(/later/i);
    expect(fault("exit_gain").positive).toBe(true);
  });
});
