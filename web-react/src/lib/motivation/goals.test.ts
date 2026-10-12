import { describe, expect, it } from "vitest";
import {
  classChoice,
  DEFAULT_DRAFT,
  draftToCreate,
  goalRow,
  goalsFootnote,
  goalsView,
  lapGoalBlocked,
  lapGoalHere,
  lapGoalHereText,
  raceGoalBlocked,
  rowActions,
  suggestionView,
  type DraftScope,
  type GoalDraft,
} from "./goals";
import { mfx } from "./testkit";

const AUSTRIA: DraftScope = {
  game: "f1_25",
  trackId: "f1:17",
  trackLabel: "Austria",
  carId: "f1:team:7",
  carLabel: "Haas",
  carClass: "f1_25:formula:F1 World",
  synthetic: false,
};
const GT7: DraftScope = {
  game: "gt7",
  trackId: "gt7:loc:351",
  trackLabel: "Brands Hatch",
  carId: "gt7:car:3389",
  carLabel: "Porsche 911 GT3 RS",
  carClass: null,
  synthetic: false,
};
const draft = (p: Partial<GoalDraft>): GoalDraft => ({ ...DEFAULT_DRAFT, ...p });

describe("goal rows (the server's words, in the reader's wording)", () => {
  it("active goals in the server's order, then the reached ones newest first, with their limit", () => {
    const v = goalsView(mfx.goals());
    expect(v.active.map((r) => r.id)).toEqual([4, 5, 6]);
    expect(v.reached.map((r) => r.id)).toEqual([2, 3]); // goal 2 was reached later (22:20) than goal 3 (19:55)
    expect(v.canAdd).toBe(true);
    expect(v.limitText).toBeNull();
    const lap = v.active[0]!;
    expect(lap.title).toBe("A lap under 1:10.000");
    expect(lap.scopeText).toBe("Austria · Haas");
    expect(lap.percent).toBe(45.2);
    expect(lap.progressText).toBe("0.301 s to go · best since you set it 1:10.301");
    expect(lap.why).toContain("Your best sectors here add up to 1:09.962");
    // a manual goal has no "Why this target?"
    expect(v.active[1]!.why).toBeNull();
  });

  it("the goals for the page's track and car first, then those that count anywhere, then other tracks", () => {
    const r = mfx.goals();
    const lap = r.goals.find((g) => g.id === 4)!;
    const montreal = { ...lap, id: 9, scope: { ...lap.scope, track_id: "f1:6", track_name: "Montreal" } };
    r.goals = [montreal, ...r.goals];
    const here = goalsView(r, false, { game: "f1_25", trackId: "f1:17", carId: "f1:team:7" });
    expect(here.active.map((g) => g.id)).toEqual([4, 5, 6, 9]);
    const there = goalsView(r, false, { game: "f1_25", trackId: "f1:6", carId: "f1:team:7" });
    expect(there.active.map((g) => g.id)).toEqual([9, 5, 6, 4]);
    expect(goalsView(r, false, null).active.map((g) => g.id)).toEqual([9, 4, 5, 6]); // no place: the server's order
  });

  it("Reopen only for a goal reached in someone else's session", () => {
    const v = goalsView(mfx.goals());
    const moved = v.reached.find((g) => g.achieved && !g.achieved.owned)!;
    const mine = v.reached.find((g) => g.achieved?.owned)!;
    expect(rowActions(moved).map((a) => a.text)).toEqual(["Reopen", "Archive", "Delete"]);
    expect(rowActions(mine).map((a) => a.text)).toEqual(["Archive", "Delete"]);
    expect(rowActions(v.active[0]!).map((a) => a.text)).toEqual(["Archive", "Delete"]);
  });

  it("simple wording for simple-wording drivers: titles, progress and the reason", () => {
    const v = goalsView(mfx.goals(), true);
    expect(v.active[0]!.title).toBe("Beat 1:10.000");
    expect(v.active[0]!.progressText).toBe("About 0.3 s to go");
    expect(v.active[0]!.why).toBe("Your best bits of the lap add up to 1:09.962, so 1:10.000 is within reach.");
    expect(v.active[2]!.title).toBe("5 steady laps, all within 1.1 s");
  });

  it("a reached goal is full, says when, and whether its session is still this driver's", () => {
    const v = goalsView(mfx.goals());
    const moved = v.reached.find((r) => r.id === 2)!;
    expect(moved.percent).toBe(100);
    expect(moved.achieved).toEqual({ text: "Reached: 1:11.745 on lap 63, Sat 10 Oct", sessionId: "4d2c1a0b9e8f", owned: false });
    expect(v.reached.find((r) => r.id === 3)!.achieved?.owned).toBe(true);
  });

  it("nothing measured yet: no bar value invented (0 from a known baseline, null when unknown)", () => {
    const g = mfx.goals().goals[2]!;
    expect(goalRow(g, false).percent).toBe(0);
    expect(goalRow({ ...g, progress: { ...g.progress, fraction: null } }, false).percent).toBeNull();
  });

  it("at the limit, Add is off and says why", () => {
    const r = mfx.goals();
    r.limits = { max_active: 6, active: 6 };
    const v = goalsView(r);
    expect(v.canAdd).toBe(false);
    expect(v.limitText).toBe("6 goals at once at most: archive or delete one to add another.");
  });

  it("no goals: empty lists, Add on", () => {
    const v = goalsView(mfx.goalsEmpty());
    expect(v.active).toEqual([]);
    expect(v.reached).toEqual([]);
    expect(v.canAdd).toBe(true);
    expect(goalsView(undefined).active).toEqual([]);
  });
});

describe("suggestions", () => {
  it("are sent as the server built them, marked suggested with their basis", () => {
    const [lap, streak, steady, race] = mfx.suggestions().suggestions.map((s, i) => suggestionView(s, false, i));
    expect(lap!.title).toBe("A lap under 1:10.000");
    expect(lap!.create).toMatchObject({ kind: "lap_time", target: 70_000, game: "f1_25", track_id: "f1:17", car_id: "f1:team:7", source: "suggested" });
    expect(lap!.create.basis?.kind).toBe("ideal_lap");
    expect(streak!.create).toMatchObject({ kind: "clean_streak", target: 8 });
    expect(steady!.create).toMatchObject({ kind: "consistency", target: 1100, params: { window_laps: 5 } });
    expect(race!.create).toMatchObject({ kind: "race_clean", params: { rule: "no_contact" } });
    expect(race!.why).toBe("9 races finished in the last 30 days: 6 without a penalty, none without contact.");
    expect(new Set([lap, streak, steady, race].map((s) => s!.key)).size).toBe(4);
  });

  it("simple wording for the title and the reason", () => {
    const s = suggestionView(mfx.suggestions().suggestions[0]!, true);
    expect(s.title).toBe("Beat 1:10.000");
    expect(s.why).toBe("Your best bits of the lap add up to 1:09.962, so 1:10.000 is within reach.");
  });
});

describe("make your own: checked like the server checks it", () => {
  it("a lap time in this car or its class", () => {
    expect(draftToCreate(draft({ kind: "lap_time", lapText: "1:10.0" }), AUSTRIA)).toEqual({
      ok: true,
      body: { kind: "lap_time", target: 70_000, game: "f1_25", track_id: "f1:17", car_id: "f1:team:7", car_class: null, source: "manual" },
    });
    const byClass = draftToCreate(draft({ kind: "lap_time", lapText: "1:10.0", carChoice: "class" }), AUSTRIA);
    expect(byClass.ok && byClass.body).toMatchObject({ car_id: null, car_class: "f1_25:formula:F1 World" });
    // no class known: "class" falls back to the car
    const gt7 = draftToCreate(draft({ kind: "lap_time", lapText: "1:24.5", carChoice: "class" }), GT7);
    expect(gt7.ok && gt7.body).toMatchObject({ car_id: "gt7:car:3389", car_class: null, target: 84_500 });
    expect(classChoice(AUSTRIA)).toBe("any F1 World car");
    expect(classChoice(GT7)).toBeNull();
  });

  it("a lap time needs a real track and a car, and whole tenths", () => {
    expect(draftToCreate(draft({ kind: "lap_time", lapText: "1:10.05" }), AUSTRIA)).toEqual({
      ok: false,
      error: "Use tenths of a second, like 1:10.4.",
    });
    expect(lapGoalBlocked(null)).toBe("A lap-time goal is for one track: drive there first, then set it.");
    // one lap-time goal per track and car: said before anything is typed
    const goals = mfx.goals().goals;
    const here = lapGoalHere(goals, AUSTRIA, "car");
    expect(here?.id).toBe(4);
    expect(lapGoalHereText(here!, false)).toBe(
      "You already have a lap-time goal here: A lap under 1:10.000. Archive it to set a new time.",
    );
    expect(lapGoalHere(goals, AUSTRIA, "class")).toBeNull(); // any F1 World car is another place
    expect(lapGoalHere(goals, GT7, "car")).toBeNull();
    expect(lapGoalBlocked({ ...AUSTRIA, synthetic: true })).toBe("This is a synthetic track: goals only count real driving.");
    expect(lapGoalBlocked({ ...AUSTRIA, carId: null, carClass: null })).toContain("Pick a car above first");
    expect(draftToCreate(draft({ kind: "lap_time", lapText: "1:10.0" }), { ...AUSTRIA, synthetic: true }).ok).toBe(false);
  });

  it("clean laps in a row: 2 to 50, anywhere", () => {
    expect(draftToCreate(draft({ kind: "clean_streak", laps: 8 }), null)).toEqual({
      ok: true,
      body: { kind: "clean_streak", target: 8, source: "manual" },
    });
    for (const n of [1, 51, 2.5, Number.NaN]) {
      const r = draftToCreate(draft({ kind: "clean_streak", laps: n }), null);
      expect(r.ok, String(n)).toBe(false);
    }
  });

  it("steady laps: 3, 5 or 10 laps within 0.1 to 10 s, in tenths", () => {
    expect(draftToCreate(draft({ kind: "consistency", window: 5, seconds: 1.1 }), null)).toEqual({
      ok: true,
      body: { kind: "consistency", target: 1100, params: { window_laps: 5 }, source: "manual" },
    });
    expect(draftToCreate(draft({ kind: "consistency", window: 3, seconds: 0.7 }), null)).toMatchObject({ ok: true, body: { target: 700 } });
    expect(draftToCreate(draft({ kind: "consistency", seconds: 1.15 }), null)).toEqual({ ok: false, error: "Use tenths of a second, like 1.1." });
    expect(draftToCreate(draft({ kind: "consistency", seconds: 0 }), null).ok).toBe(false);
    expect(draftToCreate(draft({ kind: "consistency", seconds: 10.1 }), null).ok).toBe(false);
  });

  it("a clean race: F1 only (other games send no session type), or any game left open", () => {
    expect(draftToCreate(draft({ kind: "race_clean", rule: "no_contact" }), AUSTRIA)).toEqual({
      ok: true,
      body: { kind: "race_clean", target: 1, params: { rule: "no_contact" }, source: "manual" },
    });
    expect(draftToCreate(draft({ kind: "race_clean" }), null).ok).toBe(true);
    expect(raceGoalBlocked(GT7)).toBe("Pitwall can only check this in F1 races: this game does not report races.");
    expect(draftToCreate(draft({ kind: "race_clean" }), GT7).ok).toBe(false);
  });
});

describe("the footnote (spec 9)", () => {
  it("real driving only; and what 'clean' means where the game sends no lap validity", () => {
    expect(goalsFootnote("Sam", "f1_25")).toEqual(["From Sam's real driving: synthetic and replayed sessions never count."]);
    expect(goalsFootnote("Sam", "gt7")).toEqual([
      "From Sam's real driving: synthetic and replayed sessions never count.",
      "This game does not report track limits, so 'clean' means no pit lap, reset or flashback.",
    ]);
    expect(goalsFootnote("James", null)[0]).toContain("From James's real driving");
  });
});
