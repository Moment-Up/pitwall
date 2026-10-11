import { describe, expect, it } from "vitest";
import { badgeWords, thingsView } from "./recap";
import { mfx } from "./testkit";

describe("Today's 3 things (spec 4.8): the server's items, laid out", () => {
  it("went well, work on, progress, in that order, verbatim with their evidence", () => {
    const v = thingsView(mfx.recap(), false);
    expect(v.items.map((t) => t.kind)).toEqual(["went_well", "work_on", "progress"]);
    const [good, work, prog] = v.items;
    expect(good).toMatchObject({ heading: "Went well", tone: "success", icon: "check", source: "pb", empty: false });
    expect(good.text).toBe("New personal best at Austria in the Haas: 1:10.549 on lap 64, 1.196 s faster than before.");
    expect(work).toMatchObject({ heading: "One to work on", tone: "warning", icon: "warning", lapId: 59, corner: "T4" });
    expect(work.text).toBe(
      "Turn 6: minimum speed is 9 km/h lower than your reference (164 vs 173 km/h), losing 0.23 s through the corner.",
    );
    expect(work.evidence).toBe("Seen on 9 of 9 laps compared with your reference");
    expect(prog).toMatchObject({ heading: "Progress", tone: "neutral", icon: "chart", source: "sessions_week" });
    expect(v.workOnKey).toBe("T4:low_min_speed");
    expect(v.synthetic).toBe(false);
    expect(v.replay).toBe(false);
  });

  it("a goal reached this session is the celebration: Goal reached, the star, success tone", () => {
    const prog = thingsView(mfx.recapReached(), false).items[0]; // the celebration first
    expect(prog).toMatchObject({ heading: "Goal reached", icon: "star", tone: "success", goalId: 4, source: "goal_reached" });
    expect(prog.text).toBe("A lap under 1:10.000 (1:09.981 on lap 7).");
    expect(thingsView(mfx.recapReached(), true).items[0].text).toBe("You did it: beat 1:10.000.");
    const two = mfx.recapReached();
    two.things.progress = { ...two.things.progress!, values: { ...two.things.progress!.values, goals: 2 } };
    expect(thingsView(two, false).items[0].heading).toBe("2 goals reached");
  });

  it("simple wording for a beginner", () => {
    const v = thingsView(mfx.recapBeginner(), true);
    expect(v.items[1].text).toBe("Turn 15 (130R): you were 25 km/h slower at the slowest point of the corner.");
    expect(v.items[2].text).toBe("1:36.360 is your time to beat at Suzuka.");
    // the same recap read by an advanced viewer: the coach's full text
    expect(thingsView(mfx.recapBeginner(), false).items[1].text).toContain("minimum speed is 25 km/h lower");
  });

  it("synthetic: progress is '-' with the reason; the flags carry to the card", () => {
    const v = thingsView(mfx.recapSynthetic(), false);
    expect(v.synthetic).toBe(true);
    expect(v.items[2]).toMatchObject({ empty: true, text: "-", source: null, evidence: "Synthetic sessions do not count towards progress" });
    expect(v.items[0].empty).toBe(false);
  });

  it("a replay with no clean lap: work on says so; went well and progress give their reasons", () => {
    const v = thingsView(mfx.recapReplay(), false);
    expect(v.replay).toBe(true);
    expect(v.items[1]).toMatchObject({ source: "no_clean_lap", text: "No clean lap this time, so there is nothing to compare yet." });
    expect(v.items[0]).toMatchObject({ empty: true, text: "-" });
    expect(v.items[2].evidence).toBe("Replays are not anyone's driving");
    expect(v.workOnKey).toBeNull(); // not an observation: nothing to hide from Work on
  });

  it("a real session without a clean lap: lap hygiene, nothing went well", () => {
    const v = thingsView(mfx.recapNoClean(), true);
    expect(v.items[1].text).toBe("2 timed laps did not count this time.");
    expect(v.items[0].evidence).toBe("No clean lap this time, so nothing to compare yet");
  });

  it("the UI adds no advice: no text it composes ever says to brake later (P9)", () => {
    for (const r of [mfx.recap(), mfx.recapReached(), mfx.recapBeginner(), mfx.recapSynthetic(), mfx.recapReplay(), mfx.recapNoClean()]) {
      for (const simple of [false, true]) {
        for (const t of thingsView(r, simple).items) {
          // headings and empty texts are the UI's own words; the item texts are the server's, verbatim
          expect(`${t.heading} ${t.empty ? t.text : ""}`).not.toMatch(/brak\w* later|later brak/i);
        }
      }
    }
  });

  it("badges this session as words, newest first", () => {
    expect(badgeWords(mfx.recapReached().badges_earned, false)).toEqual([
      "First time under 1:10 at Austria in the Haas",
      "First goal reached",
      "First time under 1:11 at Austria in the Haas",
    ]);
    expect(badgeWords(mfx.recapReached().badges_earned, true)[1]).toBe("Your first goal reached");
    expect(badgeWords(null, false)).toEqual([]);
  });
});
