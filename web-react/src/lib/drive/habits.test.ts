// Habits on Drive (habits spec 7): the coach card's chip says what kind of note it is (a habit with its counts, the
// focus the radio is working on, a one-off, a habit sorted), a focus corner without a note shows the habit's
// reminder, and the Ready card says what the radio is working on between runs. Coach blocks are built here in the
// shape coach/selection.py coach_block sends (synthetic values; no game evidence).
import { describe, expect, it } from "vitest";
import {
  FOCUS_SLOTS_MAX,
  chipTone,
  coachPoint,
  focusHabits,
  habitChip,
  lapCount,
  pointChip,
  topPoint,
  workOnWentWell,
  workingOn,
} from "./coach";
import { driveModel } from "./model";
import { driver, fixture, lap, newestT, snap } from "./testkit";
import type { CoachBlock, FocusEntry, ObservationNext, SnapshotNext } from "./types";

function point(over: Partial<ObservationNext>): ObservationNext {
  return {
    id: "L6:T6:low_min_speed",
    kind: "low_min_speed",
    corner: "T6",
    lap_number: 6,
    ref_lap_number: 4,
    value: -12,
    unit: "km/h",
    impact_s: 0.31,
    confidence: 0.9,
    text: "T6: minimum speed is 12 km/h lower than your reference, losing 0.31 s through the corner.",
    short: "T6: 12 km/h slower mid-corner",
    consistency: "3 of the last 4 laps",
    positive: false,
    priority: 0.28,
    habit: null,
    one_off: false,
    habit_event: null,
    ...over,
  };
}

function focusEntry(over: Partial<FocusEntry> = {}): FocusEntry {
  return {
    corner: "T6",
    corner_label: "T6",
    corner_voice: "Turn 6",
    kind: "low_min_speed",
    status: "focus",
    laps_seen: 3,
    laps: 4,
    value: -12,
    unit: "km/h",
    impact_s: 0.3,
    since_lap: 5,
    short: "T6: 12 km/h slower mid-corner",
    reminder: { parts: ["Turn 6", "apex speed, 12 down"], text: "T6: apex speed, 12 down" },
    ...over,
  };
}

function block(points: ObservationNext[], over: Partial<CoachBlock> = {}): CoachBlock {
  return {
    lap_number: 6,
    picked: points.filter((o) => o.picked),
    by_corner: Object.fromEntries(points.map((o) => [o.corner, o])),
    habits: [],
    focus: [],
    ...over,
  };
}

/** Lap 6 just finished (the car is on lap 7). */
function withCoach(coach: CoachBlock): SnapshotNext {
  return snap({ coach, laps: [lap(6, 91_000), lap(5, 91_500)] });
}

describe("the note's chip (coach card)", () => {
  it("names the kind of note from the coach block's habit and one_off", () => {
    expect(habitChip(point({ habit: { status: "seen", laps_seen: 3, laps: 4 } }))).toEqual({ kind: "habit", text: "Habit · 3 of 4 laps" });
    expect(habitChip(point({ habit: { status: "focus", laps_seen: 3, laps: 4 } }))).toEqual({ kind: "focus", text: "Focus" });
    expect(habitChip(point({ one_off: true }))).toEqual({ kind: "once", text: "Once" });
    const sorted = point({ habit_event: "fixed", habit: { status: "fixed", laps_seen: 1, laps: 5 }, text: "T6: sorted - clean on 2 of the last 3 laps." });
    expect(habitChip(sorted)).toEqual({ kind: "sorted", text: "Sorted" });
    expect(habitChip(point({ habit_event: "fixed" }))).toEqual({ kind: "sorted", text: "Sorted" });
    // praise, a drill and a point from an older server say nothing more (unknown is never guessed)
    expect(habitChip(point({ positive: true, kind: "exit_gain" }))).toBeNull();
    expect(habitChip(point({ kind: "drill", one_off: true }))).toBeNull();
    const { habit: _h, one_off: _o, habit_event: _e, ...old } = point({});
    expect(habitChip(old as ObservationNext)).toBeNull();
    expect(habitChip(point({ habit: { status: "seen", laps_seen: 3, laps: 0 } }))).toBeNull();
    expect(lapCount(1, 1)).toBe("1 of 1 lap");
  });

  it("one chip with the lap it is from; a habit says its counts instead", () => {
    const at = (o: ObservationNext) => coachPoint(withCoach(block([o])), "T6", false, true);
    expect(at(point({ habit: { status: "seen", laps_seen: 3, laps: 4 } }))).toMatchObject({
      tag: "work_on",
      tagText: "Habit · 3 of 4 laps",
      text: "T6: 12 km/h slower mid-corner",
      habit: { kind: "habit" },
    });
    expect(at(point({ habit: { status: "focus", laps_seen: 4, laps: 5 } })).tagText).toBe("Focus · last lap");
    expect(at(point({ one_off: true })).tagText).toBe("Once · last lap");
    expect(at(point({ one_off: true, lap_number: 5 })).tagText).toBe("Once · L5");
    const sorted = at(point({ habit_event: "fixed", habit: { status: "fixed", laps_seen: 1, laps: 4 }, short: "T6: sorted" }));
    expect(sorted).toMatchObject({ tag: "good", tagText: "Sorted · last lap", text: "T6: sorted" });
    expect(at(point({ positive: true, kind: "exit_gain" }))).toMatchObject({ tag: "good", tagText: "Good · last lap", habit: null });
    expect(at(point({}))).toMatchObject({ tag: "work_on", tagText: "Work on · last lap", habit: null });
  });

  it("colours: praise and sorted green, the focus accent, every other note amber", () => {
    expect(chipTone({ tag: "good", habit: { kind: "sorted", text: "Sorted" } })).toBe("success");
    expect(chipTone({ tag: "work_on", habit: { kind: "focus", text: "Focus" } })).toBe("accent");
    expect(chipTone({ tag: "work_on", habit: { kind: "habit", text: "Habit · 3 of 4 laps" } })).toBe("warning");
    expect(chipTone({ tag: "work_on", habit: { kind: "once", text: "Once" } })).toBe("warning");
    expect(chipTone({ tag: "drill", habit: null })).toBe("accent");
    expect(chipTone({ tag: "work_on", habit: { kind: "focus", text: "Focus" } }, "Next run · from last lap")).toBe("warning");
    // the Ready card's "Last lap:" chip: the kind without the lap (the label says it)
    expect(pointChip({ tag: "work_on", habit: { kind: "once", text: "Once" } })).toEqual({ text: "Once", tone: "warning" });
    expect(pointChip({ tag: "work_on", habit: null })).toEqual({ text: "Work on", tone: "warning" });
    expect(pointChip({ tag: "good", habit: null })).toEqual({ text: "Good", tone: "success" });
    expect(pointChip({ tag: "drill", habit: null })).toBeNull();
  });
});

describe("a focus corner without a note of its own", () => {
  it("shows the habit's reminder (the radio's words before the corner), verbatim, as Focus", () => {
    const s = withCoach(block([point({ corner: "T2", one_off: true })], { focus: [focusEntry()] }));
    expect(coachPoint(s, "T6", false, true)).toMatchObject({
      tag: "work_on",
      habit: { kind: "focus", text: "Focus" },
      tagText: "Focus",
      lap: null,
      text: "T6: apex speed, 12 down",
      size: 30,
      evidence: "Seen on 3 of the last 4 laps",
      corner: "T6",
    });
    // the last lap's own note at the corner comes first
    const own = withCoach(block([point({ one_off: true, kind: "late_throttle", short: "T6: throttle 40 m late" })], { focus: [focusEntry()] }));
    expect(coachPoint(own, "T6", false, true)).toMatchObject({ tagText: "Once · last lap", text: "T6: throttle 40 m late" });
  });

  it("a braking habit has no reminder: its glance text; nothing to say: no note", () => {
    const brake = focusEntry({ kind: "brake_early", reminder: null, short: "T6: braked 12 m earlier" });
    expect(coachPoint(withCoach(block([], { focus: [brake] })), "T6", false, true).text).toBe("T6: braked 12 m earlier");
    const silent = focusEntry({ reminder: null, short: null });
    expect(coachPoint(withCoach(block([], { focus: [silent] })), "T6", false, true)).toMatchObject({
      text: null,
      empty: "No note for T6 on the last lap",
    });
    // only the habits being worked on (an older or odd block's other statuses are not a focus)
    expect(coachPoint(withCoach(block([], { focus: [focusEntry({ status: "seen" })] })), "T6", false, true).text).toBeNull();
  });
});

describe("a sorted line is progress, not something to work on", () => {
  const sorted = point({
    id: "L6:T1:brake_early:fixed",
    corner: "T1",
    kind: "brake_early",
    habit_event: "fixed",
    habit: { status: "fixed", laps_seen: 1, laps: 5 },
    text: "T1: sorted - clean on 2 of the last 3 laps.",
    picked: true,
  });
  const once = point({ id: "L6:T5:late_throttle", corner: "T5", kind: "late_throttle", one_off: true, text: "T5: throttle late.", picked: true });

  it("the pit lane's next run and the Ready card's last lap take the fault", () => {
    const s = withCoach(block([sorted, once]));
    expect(topPoint(s, false)).toMatchObject({ corner: "T5", tagText: "Once · last lap" });
    // only a sorted line: it is the lap's point, as praise
    expect(topPoint(withCoach(block([sorted])), false)).toMatchObject({ corner: "T1", tag: "good", tagText: "Sorted · last lap" });
  });

  it("the Session complete card: a sorted line went well", () => {
    const { workOn, wentWell } = workOnWentWell(withCoach(block([sorted, once])), false);
    expect(workOn).toMatchObject({ corner: "T5" });
    expect(wentWell).toMatchObject({ corner: "T1", text: "T1: sorted - clean on 2 of the last 3 laps." });
  });
});

describe("Working on (Ready card, between runs)", () => {
  it("one row per habit being worked on: the reminder's words, else the topic, and the counts", () => {
    const s = withCoach(
      block([], {
        focus: [
          focusEntry(),
          focusEntry({ corner: "T9", corner_label: null, kind: "brake_early", laps_seen: 4, laps: 5, reminder: null }),
          focusEntry({ corner: "T12", corner_label: "T12" }),
        ],
      }),
    );
    expect(focusHabits(s)).toHaveLength(FOCUS_SLOTS_MAX);
    expect(workingOn(s)).toEqual([
      { corner: "T6", label: "T6", what: "apex speed, 12 down", counts: "3 of 4 laps", text: "T6 apex speed, 12 down · 3 of 4 laps" },
      { corner: "T9", label: "T9", what: "braking point", counts: "4 of 5 laps", text: "T9 braking point · 4 of 5 laps" },
    ]);
    expect(workingOn(withCoach(block([])))).toEqual([]);
    expect(workingOn(snap())).toEqual([]);
    expect(workingOn(null)).toEqual([]);
  });

  function garage(focus: FocusEntry[], laps = true, points: ObservationNext[] = []): SnapshotNext {
    const s = fixture("edited-garage-between-runs");
    s.coach = block(points, { lap_number: 4, focus });
    if (!laps) s.laps = [];
    return s;
  }
  const ready = (s: SnapshotNext) => driveModel({ snap: s, connected: true, nowS: newestT(s) + 1, driver: driver() }).ready;

  it("takes the Last lap point's place; its corner leaves the FOCUS rows", () => {
    // the cue plan's focus corner T7 (label T11) is the habit being worked on
    const r = ready(garage([focusEntry({ corner: "T7", corner_label: "T11", kind: "brake_early", reminder: null })]));
    expect(r).toMatchObject({
      phase: "between_runs",
      workingOn: [{ corner: "T7", text: "T11 braking point · 3 of 4 laps" }],
      lastLap: null,
      today: { focus: [], radioCalls: "Radio calls: T11" },
    });
    // another corner: the FOCUS row stays
    const other = ready(garage([focusEntry()]));
    expect(other?.workingOn?.map((w) => w.text)).toEqual(["T6 apex speed, 12 down · 3 of 4 laps"]);
    expect(other?.today.focus.map((f) => f.name)).toEqual(["T7"]);
  });

  it("no habit being worked on: today's content (the last lap's point); before the first lap: none", () => {
    const once = point({ lap_number: 4, one_off: true, picked: true, text: "T6: minimum speed 12 km/h down." });
    const r = ready(garage([], true, [once]));
    expect(r).toMatchObject({ workingOn: null, lastLap: { label: "Last lap", point: { text: "T6: minimum speed 12 km/h down." } } });
    expect(pointChip(r!.lastLap!.point)).toEqual({ text: "Once", tone: "warning" });
    expect(ready(fixture("edited-garage-between-runs"))?.workingOn).toBeNull();
    const before = ready(garage([focusEntry()], false));
    expect(before).toMatchObject({ phase: "before_first_lap", workingOn: null, lastLap: null });
  });
});
