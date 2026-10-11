import { describe, expect, it } from "vitest";
import { APPROACH_M, cornerAhead, cornerLabelOf, cornerLayout, focusReasonOf, isFocus, reasonWords } from "./corner";
import { fixture } from "./testkit";
import type { CornerNext, CueSnapshot, TrackModelNext } from "./types";

function corner(name: string, entry: number, apex: number, over: Partial<CornerNext> = {}): CornerNext {
  return {
    name,
    entry_m: entry,
    apex_m: apex,
    exit_m: apex + 50,
    seg_start_m: entry - 100,
    seg_end_m: apex + 100,
    direction: "right",
    ref_min_speed_kph: 120,
    ...over,
  };
}

/** Silverstone-like model (mockup sample geometry): lap 5890 m. */
const MODEL: TrackModelNext = {
  game: "f1_25",
  track_id: "f1:7",
  track_name: "Silverstone",
  length_m: 5890,
  version: 1,
  n_laps: 3,
  centreline: [],
  corners: [
    corner("T1", 280, 430, { label: "T1", display_name: "Abbey", identity_tier: "sheet_verified" }),
    corner("T9", 4880, 5010, { label: "T15", display_name: "Stowe", identity_tier: "sheet_verified" }),
    corner("T10", 5420, 5530, { direction: "left", label: "T16", display_name: "Vale" }),
    corner("T5", 1800, 2030, { direction: null, label: null }),
  ],
  corner_text: { T5: { short: "T6", long: "Turn 6", voice: "Turn 6" } },
};

const CUES = (over: Partial<CueSnapshot> = {}): CueSnapshot => ({
  mode: "focus",
  armed: true,
  muted: null,
  reason: null,
  ref_lap_number: 4,
  focus: ["T9"],
  cues: [{ corner: "T9", kind: "brake", target_m: 4810, text: "T9 brake", focus: true, reason: "brake_early on 3 of the last 5 lap(s)" }],
  next: null,
  last: null,
  timing: { latency_ms: 250, path: "pcm", margin_m: 5 },
  ...over,
});

describe("cornerAhead (4.5)", () => {
  it("shows the next corner by apex with the distance to its entry and the approach bar", () => {
    const v = cornerAhead(MODEL, 4560, 5890, CUES());
    expect(v).toEqual({
      name: "T9",
      label: "T15",
      officialName: "Stowe",
      direction: "right",
      phase: "next",
      toEntryM: 320,
      toApexM: 450,
      approach: 1 - 320 / APPROACH_M,
      focus: true,
      focusReason: "braking early · 3 of the last 5 laps",
      layout: "one",
    });
  });

  it("switches to In corner after the entry and keeps the corner until its apex is passed", () => {
    expect(cornerAhead(MODEL, 4900, 5890, undefined)).toMatchObject({ name: "T9", phase: "in", toEntryM: null, approach: null });
    expect(cornerAhead(MODEL, 5009, 5890, undefined)).toMatchObject({ name: "T9", phase: "in" });
    expect(cornerAhead(MODEL, 5011, 5890, undefined)).toMatchObject({ name: "T10", phase: "next", toEntryM: expect.closeTo(409, 6) });
  });

  it("wraps at the line", () => {
    const v = cornerAhead(MODEL, 5700, 5890, undefined);
    expect(v).toMatchObject({ name: "T1", label: "T1", officialName: "Abbey", phase: "next", toEntryM: expect.closeTo(470, 6), approach: 0 });
  });

  it("maps game metres to model metres by lap fraction", () => {
    const shorter: TrackModelNext = { ...MODEL, length_m: 5800 }; // learned centreline 90 m shorter
    // game 4560 m -> model 4490.3 m; entry 4880 is 389.7 model m away = 395.8 game m
    const v = cornerAhead(shorter, 4560, 5890, undefined);
    expect(v?.name).toBe("T9");
    expect(v?.toEntryM).toBeCloseTo(395.7, 1);
  });

  it("falls back from the official label to the sheet's short text to the learned name", () => {
    expect(cornerAhead(MODEL, 1500, 5890, undefined)).toMatchObject({ name: "T5", label: "T6", officialName: null, direction: null });
    expect(cornerLabelOf(MODEL, "T5")).toBe("T6");
    expect(cornerLabelOf(MODEL, "T99")).toBe("T99");
    const bare = { ...MODEL, corner_text: undefined };
    expect(cornerAhead(bare, 1500, 5890, undefined)?.label).toBe("T5");
  });

  it("is unknown without a model, corners or a position on this lap", () => {
    expect(cornerAhead(null, 100, 5890, undefined)).toBeNull();
    expect(cornerAhead({ ...MODEL, corners: [] }, 100, 5890, undefined)).toBeNull();
    expect(cornerAhead(MODEL, null, 5890, undefined)).toBeNull();
    expect(cornerAhead(MODEL, 16843.7, 913.3, undefined)).toBeNull(); // GT7 distance past the lap
  });

  it("handles a car behind the line (negative F1 distance) as the end of the lap", () => {
    expect(cornerAhead(MODEL, -100, 5890, undefined)).toMatchObject({ name: "T1", toEntryM: expect.closeTo(380, 6) });
  });

  it("works on real data: Suzuka's learned T7 is the official T11 Hairpin", () => {
    const s = fixture("recorded-suzuka-on-track-brake-ahead");
    const v = cornerAhead(s.track_model, s.frame?.lap_distance_m, s.skeleton?.track_length_m, s.cues);
    expect(v).toMatchObject({ name: "T7", label: "T11", officialName: "Hairpin", direction: "left", phase: "next", focus: true });
    expect(v?.toEntryM).toBeCloseTo(331.9, 1);
    expect(v?.focusReason).toBe("braking early · 1 of the last 1 lap");
  });
});

describe("long corner rule (4.5)", () => {
  it("puts a label over 4 characters or a name over 14 on two lines", () => {
    expect(cornerLayout("T15", "Stowe")).toBe("one");
    expect(cornerLayout("T1", null)).toBe("one");
    expect(cornerLayout("T10-13", "Maggotts and Becketts")).toBe("two");
    expect(cornerLayout("T16-18", "Club")).toBe("two");
    expect(cornerLayout("T1", "Niki Lauda Kurve")).toBe("two");
    expect(cornerLayout("T1", "Fourteen chars")).toBe("one");
  });

  it("applies to the real Silverstone and Austria corners", () => {
    const at = (name: string) => {
      const s = fixture(name);
      return cornerAhead(s.track_model, s.frame?.lap_distance_m, s.skeleton?.track_length_m, s.cues);
    };
    expect(at("recorded-d246-silverstone-long-label")).toMatchObject({
      label: "T10-13",
      officialName: "Maggotts and Becketts",
      direction: "right", // the learned corner's own direction (the first part of the complex)
      phase: "next",
      layout: "two",
    });
    expect(at("recorded-d246-silverstone-club")).toMatchObject({ label: "T16-18", officialName: "Club", layout: "two" });
    expect(at("recorded-d246-austria-long-name")).toMatchObject({ label: "T1", officialName: "Niki Lauda Kurve", layout: "two" });
    expect(at("recorded-suzuka-on-track-brake-ahead")?.layout).toBe("one");
  });
});

describe("reason words", () => {
  it("turns cue plan reasons into words and keeps unknown shapes verbatim", () => {
    expect(reasonWords("late_throttle on 2 of the last 4 lap(s)")).toBe("late to full throttle · 2 of the last 4 laps");
    expect(reasonWords("new_kind on 1 of the last 1 lap(s)")).toBe("new kind · 1 of the last 1 lap");
    expect(reasonWords("braking zone")).toBe("braking zone");
    expect(reasonWords(null)).toBeNull();
    expect(focusReasonOf(CUES(), "T1")).toBeNull();
  });
});

describe("focus corners are the driver's own", () => {
  it("never marks a corner FOCUS for the AI field's heads-ups (a learned key like T7 included)", () => {
    const s = fixture("edited-ai-field-suzuka");
    const v = cornerAhead(s.track_model, s.frame?.lap_distance_m, s.skeleton?.track_length_m, s.cues);
    expect(v).toMatchObject({ name: "T7", label: "T11", focus: false, focusReason: null });
    expect(focusReasonOf(s.cues, "T7")).toBeNull();
    expect(isFocus(s.cues, "T7")).toBe(false);
    expect(isFocus(fixture("recorded-suzuka-on-track-brake-ahead").cues, "T7")).toBe(true);
  });
});
