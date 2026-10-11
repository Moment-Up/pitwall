import { describe, expect, it } from "vitest";
import { endedMotivation, noteFor, readyGoal, type DriveMotivation } from "./drive";
import { mfx } from "./testkit";

const SID = "332904dbe3de";
const m = (p: Partial<DriveMotivation>): DriveMotivation => ({ note: null, recap: null, status: "ready", ...p });

describe("the Ready card's goal row (between runs)", () => {
  it("a goal reached this session wins, in the short form, full bar", () => {
    const g = readyGoal(m({ recap: mfx.recapReached() }), SID)!;
    expect(g).toEqual({
      title: "Beat 1:10.000",
      scopeText: "Austria · Haas",
      progressText: "Reached: 1:09.981 on lap 7, Sat 10 Oct",
      fraction: 1,
      reached: true,
    });
  });

  it("before the recap arrives, the socket's note says it was reached", () => {
    const g = readyGoal(m({ note: mfx.note(), status: "loading" }), SID)!;
    expect(g).toMatchObject({ title: "Beat 1:10.000", progressText: "Reached on lap 7", reached: true, fraction: 1 });
    const two = mfx.note();
    two.goals.push({ ...two.goals[0]!, id: 5, title_simple: "8 clean laps in a row" });
    expect(readyGoal(m({ note: two }), SID)!.progressText).toBe("Reached on lap 7 · +1 more");
  });

  it("else the goal in this scope, with its progress", () => {
    const g = readyGoal(m({ recap: mfx.recap() }), SID)!;
    expect(g).toEqual({
      title: "Beat 1:10.000",
      scopeText: "Austria · Haas",
      progressText: "0.301 s to go · best since you set it 1:10.301",
      fraction: 0.4517,
      reached: false,
    });
    const simple = { ...mfx.recap(), simple: true };
    expect(readyGoal(m({ recap: simple }), SID)!.progressText).toBe("About 0.3 s to go");
  });

  it("nothing for another session's note or recap, or with no goals", () => {
    expect(readyGoal(m({ note: mfx.note(), recap: mfx.recap() }), "other-session")).toBeNull();
    expect(noteFor(m({ note: mfx.note() }), "other-session")).toBeNull();
    expect(readyGoal(m({ recap: { ...mfx.recap(), goals_progress: [] } }), SID)).toBeNull();
    expect(readyGoal(null, SID)).toBeNull();
    expect(readyGoal(m({ recap: mfx.recap() }), null)).toBeNull();
  });
});

describe("the Session complete card's 3 things", () => {
  it("with the recap: three things in the recap's wording and the badges it earned", () => {
    const e = endedMotivation(m({ recap: mfx.recapReached() }), SID);
    expect(e.things?.items.map((t) => t.heading)).toEqual(["Goal reached", "Went well", "One to work on"]);
    expect(e.thingsLoading).toBe(false);
    expect(e.badges).toEqual(["First time under 1:10 at Austria in the Haas", "First goal reached", "First time under 1:11 at Austria in the Haas"]);
    const beginner = endedMotivation(m({ recap: { ...mfx.recapBeginner(), session_id: SID } }), SID);
    expect(beginner.things?.items[1]!.text).toBe("Turn 15 (130R): you were 25 km/h slower at the slowest point of the corner.");
  });

  it("while it loads (or before it is asked): skeletons; on error or with no motivation input: the card as before", () => {
    expect(endedMotivation(m({ status: "loading" }), SID)).toEqual({ things: null, thingsLoading: true, badges: [], owner: null });
    expect(endedMotivation(m({ status: "off" }), SID).thingsLoading).toBe(true);
    expect(endedMotivation(m({ status: "error" }), SID)).toEqual({ things: null, thingsLoading: false, badges: [], owner: null });
    expect(endedMotivation(null, SID)).toEqual({ things: null, thingsLoading: false, badges: [], owner: null });
    // another session's recap is never shown
    expect(endedMotivation(m({ recap: mfx.recap(), status: "error" }), "other").things).toBeNull();
  });
});

describe("the seat changed: another driver's session is never celebrated as the seated driver's", () => {
  const theirs = () => ({ ...mfx.recapReached(), driver_id: 1, driver_name: "Alex" });
  it("Session complete: says whose session it was, and shows none of its badges", () => {
    const e = endedMotivation(m({ recap: theirs() }), SID, 2);
    expect(e.owner).toBe("Alex");
    expect(e.badges).toEqual([]);
    expect(e.things?.items[0]!.heading).toBe("Goal reached"); // still that session's things, under Alex's name
    const own = endedMotivation(m({ recap: theirs() }), SID, 1);
    expect(own.owner).toBeNull();
    expect(own.badges.length).toBeGreaterThan(0);
    // nobody seated: it is still someone else's session
    expect(endedMotivation(m({ recap: theirs() }), SID, null).owner).toBe("Alex");
  });

  it("Ready card: no goal row for someone else's session or note", () => {
    expect(readyGoal(m({ recap: theirs() }), SID, 2)).toBeNull();
    expect(readyGoal(m({ note: { ...mfx.note(), driver_id: 1 } }), SID, 2)).toBeNull();
    expect(readyGoal(m({ recap: theirs() }), SID, 1)?.reached).toBe(true);
  });
});
