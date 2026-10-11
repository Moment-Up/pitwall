import { describe, expect, it } from "vitest";
import { PALETTE, type CoachingLimits, type Driver } from "../../../lib/drivers";
import {
  bestLaps,
  canDelete,
  coachingLine,
  coachingSummary,
  defaultReassign,
  deletePrompt,
  driverSubtitle,
  formBody,
  formFromDriver,
  newDriverForm,
  nextColour,
  previewInitials,
  skillEffects,
  sortDrivers,
  swatchesFor,
  usualGameOptions,
  usualGameValue,
  withInitials,
  withName,
} from "./model";
import { catalogue } from "../../../lib/game-testkit";

// James's limits as the live server computes them (advanced, normal intensity).
const ADVANCED: CoachingLimits = {
  skill_level: "advanced",
  intensity: "normal",
  min_confidence: 0.6,
  min_impact_s: 0.02,
  max_per_lap: 1,
  max_corrective_per_lap: 1,
  max_positive_per_lap: 0,
  allowed_kinds: null,
  simple_wording: false,
  mention_consistency: true,
  corner_repeat_gap_laps: 0,
};

function driver(id: number, name: string, over: Partial<Driver> = {}, prefs: Partial<Driver["preferences"]> = {}): Driver {
  return {
    id,
    name,
    created_unix: id * 100,
    preferences: {
      colour: PALETTE[id % PALETTE.length] ?? "#ff6a2b",
      initials: name.slice(0, 2).toUpperCase(),
      skill_level: "beginner",
      coaching_intensity: "normal",
      voice_enabled: true,
      ...prefs,
    },
    coaching: ADVANCED,
    active: false,
    stats: { sessions: 0, laps: 0, clean_laps: 0, tracks: 0, last_session_unix: null, best_laps: [] },
    ...over,
  };
}

const JAMES = driver(0, "James", { active: true, stats: { sessions: 23, laps: 70, clean_laps: 48, tracks: 12, last_session_unix: 1, best_laps: [] } }, { skill_level: "advanced", initials: "JR" });
const ALEX = driver(1, "Alex", { stats: { sessions: 6, laps: 41, clean_laps: 30, tracks: 1, last_session_unix: 1, best_laps: [] } });
const JO = driver(2, "Jo", {}, { skill_level: "intermediate" });

describe("cards", () => {
  it("oldest profile first, so cards never jump when the seat changes", () => {
    const later = { ...JAMES, created_unix: 999 };
    expect(sortDrivers([later, JO, ALEX]).map((d) => d.name)).toEqual(["Alex", "Jo", "James"]);
    expect(sortDrivers([driver(5, "B", { created_unix: 1 }), driver(4, "A", { created_unix: 1 })]).map((d) => d.id)).toEqual([4, 5]);
  });

  it("subtitle: skill, plus coaching and voice only while the radio follows the driver", () => {
    expect(driverSubtitle(JAMES, true)).toBe("Advanced · coaching normal");
    expect(driverSubtitle(JAMES, false)).toBe("Advanced");
    const quiet = driver(3, "Sam", {}, { coaching_intensity: "quiet", voice_enabled: false });
    expect(driverSubtitle(quiet, true)).toBe("Beginner · coaching quiet · voice off");
  });

  it("coaching summary from the server's limits", () => {
    expect(coachingSummary(ADVANCED)).toBe("Up to 1 tip a lap, only losses over 0.02 s.");
    expect(
      coachingSummary({ ...ADVANCED, max_corrective_per_lap: 2, max_positive_per_lap: 1, min_impact_s: 0.1, simple_wording: true }),
    ).toBe("Up to 2 tips a lap, praise when it goes well, only losses over 0.10 s, simple wording.");
    expect(coachingSummary({ ...ADVANCED, max_per_lap: 0 })).toBe("Radio: alerts and answers only.");
  });

  it("the card's coaching line falls back to what the skill does for the engineer", () => {
    expect(coachingLine(JAMES, true)).toBe("Up to 1 tip a lap, only losses over 0.02 s.");
    expect(coachingLine(ALEX, false)).toBe("The engineer answers in plain words, one point at a time.");
  });

  it("best laps: real ones first, synthetic last, server order kept", () => {
    const lap = (track: string, synthetic: boolean) => ({
      game: "f1_25",
      track_id: track,
      track_name: track,
      lap_time_ms: 90_000,
      lap_id: 1,
      session_id: "s",
      car_name: null,
      synthetic,
      set_unix: 0,
    });
    const d = driver(9, "X", {
      stats: { ...JAMES.stats, best_laps: [lap("A", true), lap("B", false), lap("C", false)] },
    });
    expect(bestLaps(d).map((b) => b.track_id)).toEqual(["B", "C", "A"]);
  });
});

describe("the form", () => {
  it("a new driver: beginner, normal coaching, voice on, the first free colour", () => {
    const f = newDriverForm([JAMES]);
    expect(f).toMatchObject({ id: null, skill_level: "beginner", coaching_intensity: "normal", voice_enabled: true });
    expect(f.colour).toBe(nextColour([JAMES]));
    expect(f.colour).not.toBe(JAMES.preferences.colour);
  });

  it("next colour skips used ones (any case) and wraps to the first when all are taken", () => {
    const used = PALETTE.slice(0, 3).map((c, i) => driver(i, `D${i}`, {}, { colour: c.toUpperCase() }));
    expect(nextColour(used)).toBe(PALETTE[3]);
    const all = PALETTE.map((c, i) => driver(i, `D${i}`, {}, { colour: c }));
    expect(nextColour(all)).toBe(PALETTE[0]);
  });

  it("initials follow the name until typed by hand", () => {
    let f = newDriverForm([]);
    f = withName(f, "sam racer");
    expect(f.initials).toBe("SR");
    f = withInitials(f, "sx9z");
    expect(f.initials).toBe("SX9");
    f = withName(f, "Samantha");
    expect(f.initials).toBe("SX9");
  });

  it("a name with no letter to take leaves the initials empty and previews '?'", () => {
    const f = withName(newDriverForm([]), "李");
    expect(f.initials).toBe("");
    expect(previewInitials(f)).toBe("?");
  });

  it("validates before sending", () => {
    const f = formFromDriver(JAMES);
    expect(formBody({ ...f, name: "   " })).toEqual({ ok: false, error: "Give the driver a name." });
    expect(formBody({ ...f, name: "x".repeat(41) })).toMatchObject({ ok: false });
    expect(formBody({ ...f, initials: "J-R" })).toEqual({ ok: false, error: "Initials are 1 to 3 letters or digits (A-Z, 0-9)." });
    expect(formBody({ ...f, colour: "orange" })).toEqual({ ok: false, error: "Pick a colour." });
  });

  it("builds the body the server accepts (the '?' fallback is never sent)", () => {
    expect(formBody({ ...formFromDriver(JAMES), name: " James  " })).toEqual({
      ok: true,
      body: {
        name: "James",
        initials: "JR",
        colour: JAMES.preferences.colour,
        skill_level: "advanced",
        coaching_intensity: "normal",
        voice_enabled: true,
      },
    });
    const r = formBody({ ...newDriverForm([]), name: "李" });
    expect(r.ok && "initials" in r.body).toBe(false);
    expect(formBody({ ...newDriverForm([]), name: "sam", initials: "" })).toMatchObject({ ok: true, body: { initials: "S" } });
  });

  it("the colour picker keeps a custom colour that is not in the palette", () => {
    expect(swatchesFor(PALETTE[0] ?? "")).toEqual(PALETTE);
    expect(swatchesFor("#123456")).toEqual([...PALETTE, "#123456"]);
    expect(swatchesFor("bad")).toEqual(PALETTE);
  });
});

describe("usually plays (game selection)", () => {
  it("is sent only when offered: an older server rejects unknown keys", () => {
    const james = formBody(formFromDriver(JAMES));
    expect(james.ok && "default_game" in james.body).toBe(false);
    expect(formBody({ ...formFromDriver(JAMES), default_game: "gt7:ps5" })).toMatchObject({
      ok: true,
      body: { default_game: "gt7:ps5" },
    });
    const cleared = formBody({ ...formFromDriver(JAMES), default_game: null });
    expect(cleared.ok && cleared.body.default_game).toBeNull();
    const fromServer = formFromDriver({ ...JAMES, preferences: { ...JAMES.preferences, default_game: "ac:ps5" } });
    expect(fromServer.default_game).toBe("ac:ps5");
  });

  it("offers none, then every catalogue entry in catalogue order; an unknown id reads as none", () => {
    const entries = catalogue().entries;
    const opts = usualGameOptions(entries);
    expect(opts[0]).toEqual({ id: "none", label: "No usual game" });
    expect(opts).toHaveLength(entries.length + 1);
    expect(opts.find((o) => o.id === "gt7:ps5")?.label).toBe("Gran Turismo 7 · PS5");
    expect(opts.find((o) => o.id === "other:any")?.label).toBe("Another game");
    expect(usualGameValue({ default_game: "gt7:ps5" }, opts)).toBe("gt7:ps5");
    expect(usualGameValue({ default_game: "fm7:xbox" }, opts)).toBe("none");
    expect(usualGameValue({}, opts)).toBe("none");
  });
});

describe("what the skill level changes", () => {
  it("radio lines only while the radio follows the driver", () => {
    expect(skillEffects("beginner", false, "off").map((e) => e.label)).toEqual(["Engineer"]);
    expect(skillEffects("beginner", true, "off")).toEqual([
      { label: "Radio", text: "One clear tip a lap at most, simple wording, praise when it goes well." },
      { label: "Engineer", text: "Answers in plain words, one point at a time." },
    ]);
  });

  it("names this device's Drive lock when it applies to that level", () => {
    expect(skillEffects("beginner", false, "beginners").map((e) => e.label)).toEqual(["Engineer", "Drive lock"]);
    expect(skillEffects("advanced", false, "beginners").map((e) => e.label)).toEqual(["Engineer"]);
    expect(skillEffects("advanced", false, "everyone").map((e) => e.label)).toEqual(["Engineer", "Drive lock"]);
  });
});

describe("delete", () => {
  it("sessions move to the seated driver by default, else the first other one; nothing to move -> null", () => {
    expect(defaultReassign(ALEX, [JAMES, ALEX, JO])).toBe(JAMES.id);
    expect(defaultReassign(JAMES, [JAMES, ALEX, JO])).toBe(ALEX.id);
    expect(defaultReassign(JO, [JAMES, ALEX, JO])).toBeNull();
  });

  it("the last profile cannot be deleted", () => {
    expect(canDelete([JAMES])).toBe(false);
    expect(canDelete([JAMES, ALEX])).toBe(true);
  });

  it("says what happens", () => {
    expect(deletePrompt(ALEX)).toBe("Alex has 6 sessions.");
    expect(deletePrompt({ ...ALEX, stats: { ...ALEX.stats, sessions: 1 } })).toBe("Alex has 1 session.");
    expect(deletePrompt(JO)).toBe("Jo has no sessions.");
  });
});
