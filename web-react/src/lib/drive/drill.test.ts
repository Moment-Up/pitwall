import { describe, expect, it } from "vitest";
import { crFixture, withLive } from "../../test/coachref";
import type { DrillOptionsResponse, DrillView } from "../endpoints/coachref";
import {
  activeDrill,
  bestText,
  cornersOf,
  defaultKind,
  defaultLaps,
  drillBlock,
  drillChip,
  drillCoach,
  drillCorner,
  drillResult,
  drillSuggestion,
  drillTrack,
  endedDrill,
  kindChoices,
  lapsChoices,
  raceLapsLeft,
  sheetCorners,
  stoppedText,
  toleranceText,
  toleranceTitle,
  trendWord,
} from "./drill";
import { workOnWentWell } from "./coach";
import { driveModel, type DriveModel } from "./model";
import { driver, fixture, newestT, stopped } from "./testkit";
import type { SnapshotNext } from "./types";

const ON_TRACK = "recorded-d246-suzuka-on-track-brake-ahead";
const BETWEEN = "edited-garage-between-runs";

function model(s: SnapshotNext, opts: { beginner?: boolean; simple?: boolean } = {}): DriveModel {
  const d = driver({ skill: opts.beginner ? "beginner" : "advanced", simple: opts.simple ?? false });
  return driveModel({ snap: s, connected: true, nowS: newestT(s) + 1, driver: d });
}

function noCoachref(s: SnapshotNext): SnapshotNext {
  s.coachref = { driver_id: 1, choice: null, used_kind: "own_best", reason: null, pending: false, drill: null };
  return s;
}

/** Words the drill views must never produce (P9; "coaching never recommends braking later on its own"). */
const FORBIDDEN = [/brake later/i, /later braking point/i, /\bbrake\s+(at|on|by)\b/i, /\bundefined\b/, /\bnull\b/, /NaN/];

/** Every string in a view (its words), one per line. */
function allText(v: unknown): string {
  const out: string[] = [];
  const walk = (x: unknown) => {
    if (typeof x === "string") out.push(x);
    else if (Array.isArray(x)) x.forEach(walk);
    else if (x && typeof x === "object") Object.values(x).forEach(walk);
  };
  walk(v);
  return out.join("\n");
}

describe("the status-slot chip and the hero (spec 10.3)", () => {
  it("DRILL · T11 · 2/5 · 1 ✓ while a drill runs, with the target for its popover", () => {
    const s = withLive(fixture(ON_TRACK), "live-drill");
    expect(drillChip(s)).toEqual({
      text: "DRILL · T11 · 2/5 · 1 ✓",
      progress: "2/5 · 1 ✓",
      targetText: "Brake within 5 m of Sam's braking point",
      label: "T11",
      skill: "Brake point",
      aria: "Brake point drill at T11: 2 of 5 laps done, 1 hit",
    });
    expect(drillCorner(s)).toBe("T7");
    const m = model(s);
    expect(m.hero.kind === "corner" && m.hero.corner.name).toBe("T7");
    expect(m.hero.kind === "corner" && m.hero.drill).toBe(true);
    expect(m.drill.chip?.text).toBe("DRILL · T11 · 2/5 · 1 ✓");
  });

  it("no chip without a running drill; the chip stays off the state cards", () => {
    expect(drillChip(withLive(fixture(ON_TRACK), "live-sam"))).toBeNull();
    const done = withLive(fixture(ON_TRACK), "live-drill");
    done.coachref!.drill = crFixture<DrillView>("drill-completed");
    expect(drillChip(done)).toBeNull();
    expect(activeDrill(done)).toBeNull();
    const garage = model(withLive(fixture(BETWEEN), "live-drill"));
    expect(garage.drill.chip).toBeNull(); // the Ready card shows the drill instead
    const plain = model(fixture(ON_TRACK));
    expect(plain.hero.kind === "corner" && plain.hero.drill).toBeFalsy();
  });

  it("the cue plan's drill corner marks the hero too (a server that sends cues.drill_corner)", () => {
    const s = withLive(fixture(ON_TRACK), "live-sam");
    s.cues = { ...s.cues!, drill_corner: "T7" };
    expect(drillCorner(s)).toBe("T7");
  });
});

describe("the coach card while a drill runs (spec 10.3)", () => {
  it("the drill corner shows the radio's words: short while moving, the full text stationary", () => {
    const s = withLive(fixture(ON_TRACK), "live-drill");
    const moving = drillCoach(s, "T7", false, true)!;
    // The tag says what it is; the point's own words count the attempt ("Drill 2/5: …"), never twice.
    expect(moving).toMatchObject({ tag: "drill", tagText: "Drill", text: "Drill 2/5: 11 m past the point · 1 hit", source: "d6" });
    expect(drillCoach(s, "T7", false, false)?.text).toBe("Turn 11 drill, 2 of 5: 11 m past the point. 1 hit.");
    expect(drillCoach(s, "T7", true, false)?.text).toBe("Turn 11 drill, 2 of 5: past the point."); // simple wording
    expect(model(s).coach).toMatchObject({ tag: "drill", tagText: "Drill" });
  });

  it("other corners are quiet; before the first attempt the drill corner says so", () => {
    const s = withLive(fixture(ON_TRACK), "live-drill");
    expect(drillCoach(s, "T3", false, true)).toMatchObject({ text: null, empty: "Drill on T11: other corners are quiet" });
    s.coach = { ...s.coach!, by_corner: {}, picked: [] };
    s.coachref!.drill = { ...s.coachref!.drill!, attempts: [], hits: 0, scored: 0 };
    expect(drillCoach(s, "T7", false, true)?.empty).toBe("Drill on T11: first attempt on your next lap");
  });

  it("no corner ahead yet (a new session's first lap): the drill's progress, not the first-lap line", () => {
    const s = withLive(fixture(ON_TRACK), "live-drill");
    expect(drillCoach(s, null, false, true)).toMatchObject({ text: null, empty: "Drill on T11: 2 of 5 laps done" });
    s.coachref!.drill = { ...s.coachref!.drill!, attempts: [], hits: 0, scored: 0 };
    expect(drillCoach(s, null, false, true)?.empty).toBe("Drill on T11: first attempt on your next lap");
    expect(drillCoach(withLive(fixture(ON_TRACK), "live-sam"), null, false, true)).toBeNull();
  });

  it("after the drill ends its last point stays on the drill corner; other corners are back to normal", () => {
    const s = withLive(fixture(ON_TRACK), "live-drill");
    s.coachref!.drill = crFixture<DrillView>("drill-completed");
    expect(drillCoach(s, "T7", false, true)?.tag).toBe("drill");
    expect(drillCoach(s, "T3", false, true)).toBeNull();
  });

  it("in the pit lane the running drill's last point: short while moving (78 km/h), in full once stopped (plan 2.1)", () => {
    const moving = model(withLive(fixture("edited-pit-lane"), "live-drill"));
    expect(moving.state).toBe("pit_lane");
    expect(moving.coach).toMatchObject({ tag: "drill", tagText: "Drill", full: false });
    const m = model(stopped(withLive(fixture("edited-pit-lane"), "live-drill")));
    expect(m.state).toBe("pit_lane");
    expect(m.coach).toMatchObject({ tag: "drill", tagText: "Drill", text: "Turn 11 drill, 2 of 5: 11 m past the point. 1 hit.", full: true });
  });

  it("no drill: the normal coaching point", () => {
    const s = withLive(fixture(ON_TRACK), "live-sam");
    expect(drillCoach(s, "T7", false, true)).toBeNull();
    expect(model(s).coach.tag).not.toBe("drill");
  });
});

describe("the Ready card's Drill block (spec 10.2)", () => {
  it("a server without coachref: no block", () => {
    expect(drillBlock(fixture(BETWEEN))).toBeNull();
    expect(model(fixture(BETWEEN)).drill.block).toBeNull();
    // On track there is no Ready card: nothing computed.
    expect(model(withLive(fixture(ON_TRACK), "live-drill")).drill.block).toBeNull();
  });

  it("no drill: the last lap's coaching point as a drill, mapped kind, 5 laps", () => {
    const s = noCoachref(fixture(BETWEEN));
    const b = drillBlock(s);
    expect(b).toEqual({
      kind: "none",
      suggestion: {
        corner: "T6",
        label: "T9",
        name: "Degner 2",
        kind: "min_speed",
        skill: "Minimum speed",
        observationKind: "low_min_speed",
        text: "Drill T9 · Minimum speed",
        request: { corner: "T6", kind: "min_speed", laps: 5, source: "work_on", observation_kind: "low_min_speed" },
      },
    });
    // Praise and incidents start no drill: nothing to suggest.
    s.observations = s.observations.map((o) => ({ ...o, kind: o.positive ? o.kind : "exit_gain", positive: true }));
    expect(drillSuggestion(s)).toBeNull();
  });

  it("running: the line, the target and the note", () => {
    const b = drillBlock(withLive(fixture(BETWEEN), "live-drill"));
    expect(b).toEqual({
      kind: "active",
      line: "Drill · T11 · Brake point · 2 of 5 done · 1 hit",
      targetText: "Brake within 5 m of Sam's braking point",
      note: "Braking assist is on, so the game helps with braking: these brake points are partly the assist's.",
      corner: "T7",
    });
    const s = withLive(fixture(BETWEEN), "live-drill");
    s.coachref!.drill = { ...s.coachref!.drill!, attempts: [], hits: 0 };
    expect(drillBlock(s)).toMatchObject({ line: "Drill · T11 · Brake point · 5 laps, from your next lap" });
  });

  it("just ended: the result (hits of scored laps, best, trend, one dot a lap, Again with the same drill)", () => {
    const s = withLive(fixture(BETWEEN), "live-drill");
    s.coachref!.drill = crFixture<DrillView>("drill-completed");
    const b = drillBlock(s);
    expect(b?.kind).toBe("result");
    if (b?.kind !== "result") return;
    expect(b.result).toMatchObject({
      id: 14,
      title: "T11 · Brake point",
      score: "3 of 4 on the point",
      best: "1 m from the point",
      trend: "Closer",
      stopped: null,
      reference: "vs Sam's best",
      summary: "Turn 11 drill done: 3 of 4 on the point. Best: 1 m from the point. Closer each lap.",
      again: { corner: "T7", kind: "brake_point", laps: 5, tolerance: 5, source: "work_on" },
    });
    expect(b.result.dots.map((d) => d.outcome)).toEqual(["hit", "miss", "hit", "unmeasured", "hit"]);
    expect(b.result.dots[3]?.aria).toBe("Lap 4 of 5: not measured, no braking measured");
  });

  it("a stopped speed drill says when it stopped; an abandoned one (no laps) shows the start buttons again", () => {
    const [, stopped] = crFixture<DrillView[]>("drills-history-suzuka");
    const r = drillResult(null, stopped!);
    expect(r).toMatchObject({ score: "1 of 2 on target", best: "99 km/h", stopped: "Stopped after 2 of 5 laps", trend: null });
    const s = withLive(fixture(BETWEEN), "live-drill");
    s.coachref!.drill = { ...stopped!, status: "abandoned", attempts: [] };
    expect(drillBlock(s)?.kind).toBe("none");
  });

  it("best and trend words", () => {
    // As the server says it (coach/drills.py _best_text): never "best 0 m"
    expect(bestText({ kind: "brake_point", best: 2787.8, best_delta: 0.3, unit: "m" })).toBe("right on the point");
    expect(bestText({ kind: "brake_point", best: 2788.4, best_delta: 0.6, unit: "m" })).toBe("1 m from the point");
    expect(bestText({ kind: "entry_speed", best: 240.2, best_delta: 0.2, unit: "km/h" })).toBe("on target");
    expect(bestText({ kind: "entry_speed", best: 241, best_delta: -2.4, unit: "km/h" })).toBe("2 km/h from the target");
    expect(bestText({ kind: "exit_speed", best: null, best_delta: null, unit: "km/h" })).toBeNull();
    expect([trendWord("closer"), trendWord("steady"), trendWord("further"), trendWord("rising"), trendWord("falling"), trendWord(null)]).toEqual([
      "Closer",
      "Steady",
      "Drifting",
      "Rising",
      "Dropping",
      null,
    ]);
  });
});

describe("the drill sheet's choices (spec 10.2)", () => {
  it("corners in lap order with their FOCUS and Work on chips (garage only)", () => {
    const s = noCoachref(fixture(BETWEEN));
    const c = sheetCorners(s);
    // The parts of one official corner are told apart ("T16-17 (1)", "T16-17 (2)") when the sheet's text says so.
    expect(c.map((x) => x.label)).toEqual(
      c.map((x) => fixture(BETWEEN).track_model!.corner_text?.[x.name]?.short ?? x.label),
    );
    expect(new Set(c.map((x) => x.label)).size).toBe(c.length);
    expect(c.find((x) => x.name === "T7")).toMatchObject({ label: "T11", officialName: "Hairpin", focus: true });
    expect(c.filter((x) => x.workOn).map((x) => x.name)).toEqual(expect.arrayContaining(["T6", "T3"]));
    expect(model(s).drill.corners).toHaveLength(11);
    expect(model(noCoachref(fixture(ON_TRACK))).drill.corners).toEqual([]);
  });

  it("before the first lap (no live model yet) the sheet can list a stored model's corners for this game and track", () => {
    const s = noCoachref(fixture("recorded-d246-suzuka-grid-before-start"));
    expect(sheetCorners(s)).toEqual([]);
    expect(drillTrack(s)).toEqual({ game: "f1_25", trackId: "f1:13" });
    // the recorded grid moment is at 135 km/h (on track: no Ready card); once the car stands on the grid it is
    expect(model(s).drill.track).toBeNull();
    expect(model(stopped(s)).drill.track).toEqual({ game: "f1_25", trackId: "f1:13" });
    const stored = cornersOf(fixture(BETWEEN).track_model!);
    expect(stored).toHaveLength(11);
    expect(stored.every((c) => !c.focus && !c.workOn)).toBe(true);
  });

  it("kinds: the suggested one first when it can run; the others keep the server's reason", () => {
    const o = crFixture<DrillOptionsResponse>("drill-options-t11");
    const k = kindChoices(o);
    expect(k.map((x) => [x.kind, x.disabled])).toEqual([
      ["brake_point", false],
      ["min_speed", true],
      ["exit_speed", false],
      ["entry_speed", false],
    ]);
    expect(k[1]?.reason).toBe("You already reach the best minimum speed driven here (71 km/h): pick another skill.");
    expect(defaultKind(k)).toBe("brake_point");
    expect(lapsChoices(o)).toEqual([3, 5, 8, 10]);
    // A brake-point window is before the point (past it counts only when the corner was faster)
    expect(toleranceText("brake_point", 5, "m")).toBe("5 m");
    expect(toleranceTitle("brake_point")).toBe("Window before the point");
    expect(toleranceTitle("entry_speed")).toBe("Window");
    expect(toleranceText("entry_speed", 8, "km/h")).toBe("±8 km/h");
    expect(toleranceText("min_speed", 3, "km/h")).toBe("+3 km/h");
  });

  it("a track still being learned, or a synthetic session: every kind disabled with the reason, nothing to start", () => {
    for (const name of ["drill-options-learning", "drill-options-synthetic"]) {
      const k = kindChoices(crFixture<DrillOptionsResponse>(name));
      expect(k.every((x) => x.disabled), name).toBe(true);
      expect(defaultKind(k), name).toBeNull();
    }
  });
});

describe("words (P9, British English)", () => {
  it("no drill view tells the driver to brake later, and nothing leaks a JS value", () => {
    const views: unknown[] = [];
    for (const live of ["live-drill", "live-sam", "live-own", "live-fallback"]) {
      for (const name of [ON_TRACK, BETWEEN]) {
        const s = withLive(fixture(name), live);
        const m = model(s);
        views.push(m.drill, m.ref, m.coach);
      }
    }
    const s = withLive(fixture(BETWEEN), "live-drill");
    s.coachref!.drill = crFixture<DrillView>("drill-completed");
    views.push(drillBlock(s));
    for (const re of FORBIDDEN) expect(allText(views)).not.toMatch(re);
  });
});

describe("the Session complete card (spec 4.9)", () => {
  it("never shows a drill attempt as the session's Work on point", () => {
    const s = withLive(fixture(BETWEEN), "live-drill");
    expect(s.coach?.picked.some((o) => o.kind === "drill")).toBe(true);
    const { workOn, wentWell } = workOnWentWell(s, false);
    expect(workOn).toBeNull();
    expect(wentWell).toBeNull();
  });
});

describe("review fixes (UX review)", () => {
  it("M4: in a race the laps default fits the laps left (at least 3); elsewhere the server's default", () => {
    const s = withLive(fixture(BETWEEN), "live-drill");
    s.session = { ...s.session!, session_type: "race", total_laps: 3 };
    s.frame = { ...s.frame!, lap_number: 1 };
    expect(raceLapsLeft(s)).toBe(2);
    expect(defaultLaps([3, 5, 8, 10], 5, raceLapsLeft(s))).toBe(3); // a 3-lap race: the smallest choice
    s.session = { ...s.session!, total_laps: 12 };
    s.frame = { ...s.frame!, lap_number: 5 };
    expect(defaultLaps([3, 5, 8, 10], 5, raceLapsLeft(s))).toBe(5); // the default fits
    s.frame = { ...s.frame!, lap_number: 6 };
    expect(defaultLaps([3, 5, 8, 10], 5, raceLapsLeft(s))).toBe(5);
    s.frame = { ...s.frame!, lap_number: 8 };
    expect(defaultLaps([3, 5, 8, 10], 5, raceLapsLeft(s))).toBe(3); // 4 left
    s.session = { ...s.session!, session_type: "practice_1" };
    expect(raceLapsLeft(s)).toBeNull();
    expect(defaultLaps([3, 5, 8, 10], 5, null)).toBe(5);
  });

  it("M4: the Session complete card names the drill driven in this session", () => {
    const s = withLive(fixture(BETWEEN), "live-drill");
    const d = s.coachref!.drill!;
    s.laps = [...s.laps, { ...s.laps[0]!, lap_id: d.attempts[0]!.lap_id!, lap_number: 6 }];
    expect(endedDrill(s)).toEqual({ title: "Drill T11 · Brake point", line: "1 of 2 on the point (2 of 5 laps)" });
    s.laps = s.laps.filter((l) => !d.attempts.some((a) => a.lap_id === l.lap_id)); // another session's drill
    expect(endedDrill(s)).toBeNull();
  });

  it("L6: a drill stopped early says after how many laps and why", () => {
    const d = crFixture<DrillView>("drill-completed");
    expect(stoppedText({ ...d, status: "stopped", stop_reason: "driver_changed", attempts: d.attempts.slice(0, 2) })).toBe(
      "Stopped after 2 of 5 laps: the driver changed",
    );
    expect(stoppedText({ ...d, status: "stopped", stop_reason: "driver" })).toBe("Stopped after 5 of 5 laps");
    expect(stoppedText(d)).toBeNull();
  });

  it("M7: a corner without an official name is said in words, not only as a code", () => {
    const m = structuredClone(fixture(BETWEEN).track_model!);
    const c = m.corners[0]!;
    m.corner_text = { ...m.corner_text, [c.name]: { short: "T6-9 (2)", long: "Turns 6-9, part 2", voice: "Turns 6 to 9, second part" } };
    m.corners = m.corners.map((x) => (x.name === c.name ? { ...x, display_name: null } : x));
    const row = cornersOf(m).find((x) => x.name === c.name)!;
    expect(row).toMatchObject({ label: "T6-9 (2)", officialName: "Turns 6-9, part 2" });
    m.corners = m.corners.map((x) => (x.name === c.name ? { ...x, display_name: "Hairpin" } : x));
    expect(cornersOf(m).find((x) => x.name === c.name)?.officialName).toBe("Hairpin"); // an official name wins
    m.corner_text = { ...m.corner_text, [c.name]: { short: "T5", long: "T5", voice: "Turn 5" } };
    m.corners = m.corners.map((x) => (x.name === c.name ? { ...x, display_name: null } : x));
    expect(cornersOf(m).find((x) => x.name === c.name)?.officialName).toBeNull(); // nothing more than the label
  });
});
