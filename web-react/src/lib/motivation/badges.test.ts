import { describe, expect, it } from "vitest";
import { badgeViews, streakTiles } from "./badges";
import { mfx } from "./testkit";

describe("streak tiles (spec 4.7)", () => {
  it("weeks in a row, sessions this week, best clean run, new bests in a row", () => {
    const tiles = streakTiles(mfx.badges().streaks);
    expect(tiles.map((t) => [t.title, t.value, t.sub])).toEqual([
      ["Weeks in a row", 1, "weeks with at least one session"],
      ["Sessions this week", 17, "from Monday"],
      ["Best clean run", 6, "2 laps in the last session"],
      ["New bests in a row", 0, "sessions with a new personal best"],
    ]);
  });

  it("a PB streak names its scope and the best one when it was longer", () => {
    const s = mfx.badges().streaks;
    s.pb = [{ scope: mfx.badges().badges[6]!.scope!, scope_text: "Austria · Haas", current_sessions: 2, best_sessions: 3 }];
    s.weekly = { current_weeks: 2, best_weeks: 4, this_week_sessions: 1 };
    const tiles = streakTiles(s);
    expect(tiles[3]).toMatchObject({ value: 2, sub: "Austria · Haas · best 3" });
    expect(tiles[0]).toMatchObject({ value: 2, sub: "best 4 weeks" });
  });

  it("a driver who has not driven: zeros the server counted; unknown stays '-'", () => {
    const tiles = streakTiles(mfx.badgesEmpty().streaks);
    expect(tiles.map((t) => t.value)).toEqual([0, 0, 0, 0]);
    expect(tiles[2]!.sub).toBe("clean laps in a row");
    expect(streakTiles(null).map((t) => t.value)).toEqual([null, null, null, null]);
  });
});

describe("badges", () => {
  it("newest first, with the day and what earned it", () => {
    const b = badgeViews(mfx.badges());
    expect(b[0]).toMatchObject({ title: "First clean lap at Brands Hatch", day: "Sun 11 Oct" });
    expect(b[1]).toMatchObject({ title: "First time under 1:11 at Austria", detail: "1:10.549 in the Haas", sessionId: "332904dbe3de" });
    expect(b).toHaveLength(8);
    expect(b.every((x) => !x.synthetic)).toBe(true);
  });

  it("simple wording; none yet", () => {
    expect(badgeViews(mfx.badges(), true)[1]!.title).toBe("You beat 1:11 at Austria for the first time");
    expect(badgeViews(mfx.badgesEmpty())).toEqual([]);
  });
});
