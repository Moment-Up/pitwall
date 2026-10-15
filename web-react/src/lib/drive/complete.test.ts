// Session complete: each fact once (integration plan 2.6, walk finding 2), with the Imola race from the 11 Oct walk
// of aded8ab (lib/drive/testkit-imola.ts). That card said one new family record four ways: the Best lap tile's REC
// tag, "To the family record: REC, this session set it", Progress "Your first clean laps at Imola in the McLaren:
// 1:24.528 is the time to beat next time." and a "First clean lap at Imola" badge. Pure; plain node.
import { describe, expect, it } from "vitest";
import type { SessionRecap } from "../endpoints/motivation";
import { thingsView } from "../motivation/recap";
import { ENDED_BADGES_MAX, badgeKeys, dedupeComplete, recapFacts, tagKey, thingKeys } from "./complete";
import { driveModel } from "./model";
import { driver } from "./testkit";
import {
  BEST_LAP_ID,
  FIRST_CLEAN,
  FIRST_CLEAN_BADGE,
  FIRST_CLEAN_BADGE_OLD,
  FIRST_CLEAN_FACT,
  FIRST_LAPS,
  T1_WORK,
  T3_GOOD,
  badge,
  imola,
  item,
  olderRecap,
  recap,
} from "./testkit-imola";

/** dedupeComplete for a recap, the way the model calls it. */
function dedupe(r: SessionRecap, best: { tag: "REC" | "PB" | "SB" | null; lapId: number | null } | null = { tag: "REC", lapId: BEST_LAP_ID }) {
  return dedupeComplete({ things: thingsView(r, false), facts: recapFacts(r), best, badges: r.badges_earned });
}

describe("dedupeComplete: each fact once, Went well > Best lap tag > Progress > badges", () => {
  it("keys: the server's fact key first, plus what the card derives (the tag, older servers)", () => {
    const now = thingsView(recap(), false);
    expect(thingKeys(now.items[0], FIRST_CLEAN_FACT)).toEqual([FIRST_CLEAN_FACT, "first_clean", `pb:${BEST_LAP_ID}`]);
    const old = thingsView(olderRecap(), false);
    expect(thingKeys(old.items[2])).toEqual(["first_clean"]); // an older server's "first_session", no fact key
    expect(tagKey({ tag: "REC", lapId: 8 })).toBe("record:8");
    expect(tagKey({ tag: "PB", lapId: 8 })).toBe("pb:8");
    expect(tagKey({ tag: "SB", lapId: 8 })).toBeNull();
    expect(badgeKeys(FIRST_CLEAN_BADGE)).toEqual([FIRST_CLEAN_FACT, "first_clean"]);
    expect(badgeKeys(FIRST_CLEAN_BADGE_OLD)).toEqual(["first_clean"]);
    expect(badgeKeys(badge("goals_reached:1", "goals_reached", "First goal reached"))).toEqual(["goals_reached"]);
    expect(badgeKeys(badge("under_time:x", "under_time", "First time under 1:25", {}, "pb:1208"))).toEqual(["pb:1208"]);
    expect(recapFacts(recap())).toEqual({ went_well: FIRST_CLEAN_FACT, work_on: null, progress: null });
  });

  it("Imola now: Went well says the first clean laps; REC stays on the tile; the badge only repeated it", () => {
    const v = dedupe(recap());
    expect(v.shown).toEqual([FIRST_CLEAN_FACT, "first_clean", `pb:${BEST_LAP_ID}`, `record:${BEST_LAP_ID}`]);
    expect(v.bestTag).toBe(true); // a family record is its own fact
    expect(v.things?.items.map((t) => t.source)).toEqual(["first_clean", "observation", "sessions_week"]);
    expect(v.badges).toEqual([]);
  });

  it("Imola on the walk's server (a T3 point went well, no fact keys): Progress keeps the first clean laps, the badge goes", () => {
    const v = dedupe(olderRecap());
    expect(v.shown).toEqual([`record:${BEST_LAP_ID}`, "first_clean"]);
    expect(v.things?.items.map((t) => t.kind)).toEqual(["went_well", "work_on", "progress"]);
    expect(v.badges).toEqual([]);
  });

  it("a server mixing both (Went well's first clean laps, Progress still saying them): Progress is left out", () => {
    const v = dedupe(recap(FIRST_CLEAN, [FIRST_CLEAN_BADGE], FIRST_LAPS));
    expect(v.things?.items.map((t) => t.kind)).toEqual(["went_well", "work_on"]);
  });

  it("a personal best said by Went well drops the tile's PB tag and the PB badges; other badges stay, two at most", () => {
    const pb = item(
      "went_well",
      "pb",
      "New personal best at Imola in the McLaren: 1:24.528 on lap 8, 0.3 s faster than before.",
      { lap_id: BEST_LAP_ID },
      `pb:${BEST_LAP_ID}`,
    );
    const many = [
      badge("under_time:f1_25:f1:27:f1:team:1:85000", "under_time", "First time under 1:25 at Imola in the McLaren", {}, `pb:${BEST_LAP_ID}`),
      badge("clean_streak:5", "clean_streak", "5 clean laps in a row"),
      badge("ten_clean_session", "ten_clean_session", "10 clean laps in one session"),
      badge("busy_week:3", "busy_week", "3 sessions in one week"),
    ];
    const v = dedupe(recap(pb, many), { tag: "PB", lapId: BEST_LAP_ID });
    expect(v.bestTag).toBe(false);
    expect(v.things?.items).toHaveLength(3);
    // "5 clean laps in a row" and "10 clean laps in one session" are one clean run: the second goes (UX review)
    expect(v.badges.map((b) => b.key)).toEqual(["clean_streak:5", "busy_week:3"]);
    expect(v.badges).toHaveLength(ENDED_BADGES_MAX);
  });

  it("a reached clean-laps goal and the clean-run badges say one thing: the goal stays, the badges go", () => {
    const goal = item(
      "progress",
      "goal_reached",
      "8 clean laps in a row (on lap 9).",
      { goal_id: 7, values: { target: 8, value: 8, goals: 1, goal_kind: "clean_streak" } },
      "goal:7",
    );
    const streak = item("went_well", "clean_streak", "10 clean laps in a row.", {});
    const v = dedupe(
      recap(streak, [
        badge("clean_streak:10", "clean_streak", "10 clean laps in a row"),
        badge("ten_clean_session", "ten_clean_session", "10 clean laps in one session"),
        badge("busy_week:3", "busy_week", "3 sessions in one week"),
      ], goal),
      null,
    );
    expect(v.things?.items.map((t) => t.source)).toEqual(["goal_reached", "clean_streak", "observation"]); // celebration first
    expect(v.badges.map((b) => b.key)).toEqual(["busy_week:3"]);
  });

  it("a goal reached: the Progress celebration keeps it, the 'goals reached' badge would only repeat it", () => {
    const goal = item("progress", "goal_reached", "A lap under 1:25.000 (1:24.528 on lap 8).", { goal_id: 4, lap_id: BEST_LAP_ID }, "goal:4");
    const v = dedupe(recap(T3_GOOD, [badge("goals_reached:1", "goals_reached", "First goal reached", {}, "goal:4"), FIRST_CLEAN_BADGE], goal), null);
    expect(v.shown).toEqual(["goal:4", "goals_reached", FIRST_CLEAN_FACT, "first_clean"]);
    expect(v.badges.map((b) => b.kind)).toEqual(["first_clean_lap"]);
    // an older server without keys: the same, from the kinds
    const before = olderRecap(T3_GOOD, [badge("goals_reached:1", "goals_reached", "First goal reached")]);
    const plain = item("progress", "goal_reached", "A lap under 1:25.000 (1:24.528 on lap 8).", { goal_id: 4 });
    const old = dedupe({ ...before, things: { went_well: T3_GOOD, work_on: T1_WORK, progress: plain } }, null);
    expect(old.shown).toEqual(["goal:4", "goals_reached"]);
    expect(old.badges).toEqual([]);
  });

  it("a family record: the tile's REC tag says it; the 'Family record at' badge of the same lap is left out", () => {
    const key = "f1_25~f1:27~4910~f1:team:8~f1~0~race~dry~b2.a1.t2.g3.l2";
    const rec = badge(`family_record:${key}`, "family_record", "Family record at Imola", { lap_id: BEST_LAP_ID }, `family_record:${key}`);
    expect(badgeKeys(rec)).toEqual([`family_record:${key}`, `record:${BEST_LAP_ID}`]);
    const v = dedupe(recap(T3_GOOD, [rec]));
    expect(v.bestTag).toBe(true);
    expect(v.badges).toEqual([]);
    // the tile's REC on another lap (the looser family best, game + track + car + layout): the badge is another fact
    const other = dedupe(recap(T3_GOOD, [rec]), { tag: "REC", lapId: BEST_LAP_ID + 1 });
    expect(other.badges.map((b) => b.kind)).toEqual(["family_record"]);
    // no REC tag (a PB only): the badge says it
    expect(dedupe(recap(T3_GOOD, [rec]), { tag: "PB", lapId: BEST_LAP_ID }).badges).toHaveLength(1);
    expect(badgeKeys(badge("family_record:x", "family_record", "Family record at Imola"))).toEqual([]);
  });

  it("without a recap: nothing to de-duplicate; the tag stays", () => {
    expect(dedupeComplete({ things: null, best: { tag: "REC", lapId: 1 }, badges: [] })).toEqual({
      things: null,
      bestTag: true,
      badges: [],
      shown: ["record:1"],
    });
  });
});

/* ------------------------------------------------------------------ the card's model */
describe("Session complete model: Imola", () => {
  const model = (r: SessionRecap | null) =>
    driveModel({
      snap: imola(),
      connected: true,
      nowS: 1_791_741_000,
      driver: driver({ name: "James" }),
      motivation: r ? { note: null, recap: r, status: "ready" } : null,
    });

  it("this session set the family record: the fourth tile is Laps compared, not 'To the family record: REC'", () => {
    const m = model(recap());
    expect(m.card).toBe("ended");
    expect(m.ended).toMatchObject({
      best: { text: "1:24.528", status: "rec", tag: "REC", lapNumber: 8, sub: "lap 8 · new family record" },
      recordSetHere: true,
      lapsCompared: 9,
      bestTagShown: true,
      badges: [],
    });
    expect(m.ended?.things?.items.map((t) => t.heading)).toEqual(["Went well", "One to work on", "Progress"]);
    expect(m.ended?.things?.items[0]?.text).toBe("First clean laps here in the McLaren: best 1:24.528 on lap 8.");
  });

  it("the record set in another session: 'To the family record' as before; without a recap Laps compared is unknown", () => {
    const s = imola();
    s.bests = { ...s.bests!, household: { ...s.bests!.household!, session_id: "older", lap_id: 1, lap_ms: 84_000 } };
    const m = driveModel({ snap: s, connected: true, nowS: 1_791_741_000, driver: driver({ name: "James" }) });
    expect(m.ended).toMatchObject({ recordSetHere: false, toRecord: { text: "0.528 s slower" }, lapsCompared: null });
    expect(model(null).ended).toMatchObject({ recordSetHere: true, lapsCompared: null, things: null });
  });
});
