import { describe, expect, it } from "vitest";
import { fractionChange, weekView, WEEK_SESSIONS_SHOWN } from "./digest";
import { mfx } from "./testkit";

describe("the week (spec 4.9, section 12.7: 17 sessions, 60 laps, 47 clean)", () => {
  it("label, headline, totals and the week before", () => {
    const v = weekView(mfx.digest());
    expect(v.label).toBe("5 to 11 Oct");
    expect(v.weekStart).toBe("2026-10-05");
    expect(v.isCurrent).toBe(true);
    expect(v.headline).toBe("17 sessions, 60 laps, a new best at Austria");
    // the headline says the sessions and laps; the totals say the rest, in the printable page's words
    expect(v.totals).toBe("47 clean laps · 1 h 32 min driving · 12 tracks");
    expect(v.previous).toBeNull(); // nothing the week before: no line, not "0 sessions"
    expect(v.empty).toBe(false);
    expect(v.markdown.startsWith("# Sam's week: 5 to 11 October 2026")).toBe(true);
  });

  it("sessions newest first, all of them (the card shows 7, then Show all; integration plan 1.3)", () => {
    const v = weekView(mfx.digest());
    expect(v.sessions).toHaveLength(WEEK_SESSIONS_SHOWN + 10);
    expect(v.moreSessions).toBe(10);
    const starts = mfx.digest().sessions.map((s) => s.started_unix).sort((a, b) => b - a);
    expect(v.sessions.map((s) => s.id)).toEqual(
      starts.map((t) => mfx.digest().sessions.find((s) => s.started_unix === t)!.session_id),
    );
    const suzuka = v.sessions.find((s) => s.title === "Suzuka · Race" && s.pb)!;
    expect(suzuka).toMatchObject({ day: "Sat 10 Oct", car: "F1 Generic", laps: "3 of 3 laps clean", bestMs: 96_360 });
    // a session without a clean lap keeps its unknown best as unknown
    expect(v.sessions.find((s) => s.title === "Melbourne · Race")).toMatchObject({ laps: "0 of 1 lap clean", bestMs: null, pb: false });
  });

  it("two groups, 3 at most each: improvements (gains) and new tracks (every scope new this week, so no gains)", () => {
    const v = weekView(mfx.digest());
    expect(v.improvements).toEqual([]);
    expect(v.newTracks.map((i) => i.scopeText)).toEqual(["Suzuka · F1 Generic", "Austria · Haas", "Montreal · F1 Generic"]);
    // an older server: no sentence, no first lap
    expect(v.newTracks[1]!.text).toBe("First clean laps here: 1:10.549");
    const d = mfx.digest();
    d.improvements.push({ ...d.improvements[1]!, before_ms: 71_745, best_ms: 70_549, gain_ms: 1196, new_track: false, lap_id: 99 });
    const g = weekView(d).improvements[0]!;
    expect(g.text).toBe("1:10.549 · 1.2 s faster than 1:11.745");
    expect(g.newTrack).toBe(false);
  });

  it("a new track: the first clean lap there, then how much that car gained by the end of the week (plan 5.8)", () => {
    const d = mfx.digest();
    const austria = d.improvements[1]! as (typeof d.improvements)[number] & { first_ms?: number; week_gain_ms?: number | null; text?: string };
    Object.assign(austria, { first_ms: 71_745, best_ms: 70_549, week_gain_ms: 1196 });
    expect(weekView(d).newTracks[1]!.text).toBe("New this week: 1:11.745 → 1:10.549 (1.2 s faster)");
    Object.assign(austria, { best_ms: 71_745, week_gain_ms: null });
    expect(weekView(d).newTracks[1]!.text).toBe("New this week: 1:11.745");
    // the server's own sentence wins (motivation/digest.py new_track_text)
    austria.text = "New this week: 1:11.745 → 1:10.549 (1.2 s faster)";
    expect(weekView(d).newTracks[1]!.text).toBe("New this week: 1:11.745 → 1:10.549 (1.2 s faster)");
  });

  it("the week before says its counting rule (plan 5.7)", () => {
    const d = mfx.digest();
    d.previous_week = { sessions: 1, laps: 12, clean_laps: 9 };
    expect(weekView(d).previous).toBe("Week before: 1 session with a timed lap, 12 laps, 9 clean");
  });

  it("goals: reached first, then how each active goal moved", () => {
    const v = weekView(mfx.digest());
    expect(v.goals.map((g) => [g.id, g.reached, g.from, g.to])).toEqual([
      [3, true, null, 100],
      [4, false, null, 45.2],
      [5, false, 50, 75],
    ]);
    expect(v.goals[0]!.text).toBe("Done: Suzuka, Sat 10 Oct");
    expect(fractionChange(50, 75)).toBe("from 50% to 75% of the way");
    expect(fractionChange(null, 45.2)).toBe("45% of the way");
    expect(fractionChange(null, null)).toBeNull();
  });

  it("badges newest first; simple wording for a beginner", () => {
    const v = weekView(mfx.digest());
    expect(v.badges[0]).toBe("First clean lap at Brands Hatch");
    const s = weekView(mfx.digest(), true);
    expect(s.headline).toBe("You drove 17 times this week");
    expect(s.goals[1]!.title).toBe("Beat 1:10.000");
    expect(s.badges).toContain("You beat 1:11 at Austria in the Haas for the first time");
  });

  it("a week without driving says so and shows nothing invented", () => {
    const v = weekView(mfx.digestEmpty());
    expect(v.empty).toBe(true);
    expect(v.headline).toBe("No driving this week.");
    expect(v.totals).toBeNull();
    expect(v.sessions).toEqual([]);
    expect(v.improvements).toEqual([]);
    expect(v.label).toBe("28 Sep to 4 Oct");
    expect(v.isCurrent).toBe(false);
    // an active goal with no measurement: no bar, no number
    expect(v.goals[0]).toMatchObject({ from: null, to: null });
  });
});
