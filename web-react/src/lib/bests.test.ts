// The one badge rule (lib/bests.ts) and its consistency across Drive, Review and Progress: the same lap must carry the
// same badge on every page. Rows are hand-built (no game data claimed); the Drive side reads the D2 block the server
// would send for the same laps (`repo.lap_bests`: fastest clean lap, ties to the lower lap id).
import { describe, expect, it } from "vitest";
import {
  allTimeBests,
  bestBadge,
  changeWords,
  gapWords,
  rowInTimingScope,
  sameLayout,
  sameScope,
  sessionBadge,
  sessionBadges,
  sessionBests,
  type ScopeRow,
} from "./bests";
import { lapsTile } from "../pages/drive/car/view";
import { bestsOf, lapTimesView, sessionBest } from "./drive/timing";
import { lap, snap } from "./drive/testkit";
import type { Bests, SnapshotNext } from "./drive/types";
import { bestLapStatus, summaryKpis } from "./review/kpis";
import { lapsRows } from "./review/laps";
import { pointsFromRows, progressTiles, resolveScope, scopeChoices } from "./review/progress";

const MONZA = { game: "f1_25", track_id: "f1:11", car_id: "f1:team:41", track_length_m: 5793 };

function row(id: string, driver: number | null, best: number | null, started: number, over: Partial<ScopeRow> = {}): ScopeRow {
  return { id, driver_id: driver, ...MONZA, synthetic: false, source: "udp:20777", best_clean_ms: best, started_unix: started, ...over };
}

describe("the rule", () => {
  it("the strongest badge that applies wins; nothing is coloured outside the timing scope", () => {
    expect(bestBadge({ coloured: true, household: true, driver: true, session: true })).toBe("rec");
    expect(bestBadge({ coloured: true, household: false, driver: true, session: true })).toBe("pb");
    expect(bestBadge({ coloured: true, household: false, driver: false, session: true })).toBe("sb");
    expect(bestBadge({ coloured: true, household: false, driver: false, session: false })).toBe("neutral");
    expect(bestBadge({ coloured: false, household: true, driver: true, session: true })).toBe("neutral");
  });

  it("scope: same game, track, car and layout (3 %), real driving only", () => {
    const ref = row("a", 1, 90000, 1);
    expect(sameScope(row("b", 2, 90000, 2), ref)).toBe(true);
    expect(sameScope(row("b", 2, 90000, 2, { car_id: "f1:team:7" }), ref)).toBe(false);
    expect(sameScope(row("b", 2, 90000, 2, { track_id: "f1:7" }), ref)).toBe(false);
    expect(sameScope(row("b", 2, 90000, 2, { game: "f1_24" }), ref)).toBe(false);
    expect(sameScope(row("b", 2, 90000, 2, { track_length_m: 3500 }), ref)).toBe(false); // another layout
    expect(sameScope(row("b", 2, 90000, 2, { track_length_m: 5800 }), ref)).toBe(true); // the same, measured again
    expect(sameScope(row("b", 2, 90000, 2, { track_length_m: null }), ref)).toBe(true); // unknown: no veto
    expect(sameScope(row("b", 2, 90000, 2, { synthetic: true }), ref)).toBe(false);
    expect(sameScope(row("b", 2, 90000, 2, { source: "replay:x.pwcap" }), ref)).toBe(false);
    expect(sameScope(row("b", 2, 90000, 2), { ...ref, car_id: null })).toBe(false); // no car, no record
    expect(sameLayout(5793, 5890)).toBe(true);
    expect(rowInTimingScope({ synthetic: false, source: "replay:x" })).toBe(false);
  });

  it("REC for the household record, PB for a driver's own best, SB for the rest; a tie stays with the earlier lap", () => {
    const rows = [
      row("alex1", 1, 88663, 100), // first: the household record
      row("sam1", 2, 88663, 200), // ties it later: Sam's best ever, not the record
      row("alex2", 1, 88663, 300), // ties Alex's own earlier best: only this session's best
      row("alex3", 1, 89500, 400),
      row("alex-other-car", 1, 80000, 500, { car_id: "f1:team:7" }), // faster, but another car
      row("alex-other-layout", 1, 60000, 600, { track_length_m: 3400 }),
      row("jo-synthetic", 3, 70000, 700, { synthetic: true }),
      row("jo-replay", 3, 70000, 800, { source: "replay:a.pwcap" }),
    ];
    const badges = sessionBadges(rows, rows, { complete: true });
    expect(Object.fromEntries(badges)).toEqual({
      alex1: "rec",
      sam1: "pb",
      alex2: "sb",
      alex3: "sb",
      "alex-other-car": "rec",
      "alex-other-layout": "rec",
      "jo-synthetic": "neutral",
      "jo-replay": "neutral",
    });
  });

  it("knows the earlier best a session beat", () => {
    const rows = [row("a", 1, 90500, 1), row("b", 1, 91000, 2), row("c", 1, 89900, 3)];
    const b = sessionBests(rows[2]!, rows, { complete: true });
    expect([b.driver?.sessionId, b.previous?.sessionId, b.previous?.ms]).toEqual(["c", "a", 90500]);
  });

  it("a cut-off list claims REC / PB only when no all-time best can contradict it", () => {
    const rows = [row("new", 1, 88000, 900)];
    const best = (driverId: number, ms: number, sessionId: string) => ({
      id: driverId,
      stats: {
        sessions: 1,
        laps: 1,
        clean_laps: 1,
        tracks: 1,
        last_session_unix: null,
        best_laps: [{ game: "f1_25", track_id: "f1:11", track_name: "Monza", lap_time_ms: ms, lap_id: 1, session_id: sessionId, car_name: null, synthetic: false, set_unix: 1 }],
      },
    });
    // Sam has a faster lap here (any car, maybe outside the window): the record cannot be claimed; Alex's own
    // all-time best is this session, so PB holds.
    const unsure = sessionBests(rows[0]!, rows, { complete: false, allTime: allTimeBests([best(1, 88000, "new"), best(2, 87000, "old")]) });
    expect(sessionBadge(rows[0]!, unsure)).toBe("pb");
    // nobody was ever faster here: REC
    const sure = sessionBests(rows[0]!, rows, { complete: false, allTime: allTimeBests([best(1, 88000, "new"), best(2, 89000, "old")]) });
    expect(sessionBadge(rows[0]!, sure)).toBe("rec");
    // Alex was faster in some other session: SB, the badge that is certain
    const neither = sessionBests(rows[0]!, rows, { complete: false, allTime: allTimeBests([best(1, 87500, "older")]) });
    expect(sessionBadge(rows[0]!, neither)).toBe("sb");
  });

  it("says a change as a positive number and a word", () => {
    expect(changeWords(-5776)?.text).toBe("5.8 s faster");
    expect(changeWords(400)?.text).toBe("0.40 s slower");
    expect(changeWords(2)).toEqual({ text: "level", amount: null, word: "level" });
    expect(changeWords(null)).toBeNull();
  });

  it("says a gap to a best as precisely as the badges: 3 ms off the PB is not level", () => {
    expect(gapWords(3)).toEqual({ text: "0.003 s slower", amount: "0.003 s", word: "slower" });
    expect(gapWords(-449)?.text).toBe("0.449 s faster");
    expect(gapWords(999)?.text).toBe("0.999 s slower");
    expect(gapWords(1204)?.text).toBe("1.2 s slower");
    expect(gapWords(0)).toEqual({ text: "level", amount: null, word: "level" }); // an exact tie only
    expect(gapWords(0.4)?.word).toBe("level");
    expect(gapWords(undefined)).toBeNull();
    expect(changeWords(3)?.text).toBe("level"); // Gained today keeps its coarser rounding
  });
});

// ---------------------------------------------------------------------------------------- one lap, three pages

/** D2's block for a live session, as `repo.lap_bests` computes it for the same laps (lap ids: alex1 lap 6, sam1 lap 11,
 * alex2 lap 15). */
function d2(sessionLap: number, driverLap: number, household: number): NonNullable<SnapshotNext["bests"]> {
  const b = (lapId: number): Bests => ({ lap_ms: 88663, sectors_ms: [30560, 28879, 29224], lap_id: lapId, sector_lap_ids: [lapId, lapId, lapId] });
  return {
    scope: { game: MONZA.game, track_id: MONZA.track_id, car_id: MONZA.car_id, records: true },
    session: b(sessionLap),
    driver: b(driverLap),
    household: b(household),
  } as NonNullable<SnapshotNext["bests"]>;
}

/** The live session `id` with one clean lap (88.663 s, lap id `lapId`) and D2's bests. */
function live(id: string, lapId: number, bests: NonNullable<SnapshotNext["bests"]>): SnapshotNext {
  return snap({
    session_id: id,
    session: { ...snap().session!, track_id: MONZA.track_id, track_name: "Monza", track_length_m: MONZA.track_length_m },
    laps: [lap(3, 88663, [30560, 28879, 29224], { lap_id: lapId }), lap(2, 87589, [28782, 29557, 29250], { lap_id: lapId - 1, clean: false, flags: ["incomplete"] })],
    bests,
  });
}

/** Review's view of the same session: its laps and the session list. */
function review(id: string, rows: ScopeRow[]) {
  const laps = [
    { id: 1, lap_number: 2, lap_time_ms: 87589, s1_ms: 28782, s2_ms: 29557, s3_ms: 29250, valid: false, clean: false, flags: ["incomplete"] },
    { id: 2, lap_number: 3, lap_time_ms: 88663, s1_ms: 30560, s2_ms: 28879, s3_ms: 29224, valid: true, clean: true, flags: [] },
  ];
  const session = rows.find((r) => r.id === id)!;
  const best = summaryKpis(laps).best;
  const badge = sessionBadge(session, sessionBests(session, rows, { complete: true }));
  return {
    tile: bestLapStatus(session, best, badge),
    lapsTable: lapsRows(laps, null, session, badge).find((r) => r.lapNumber === 3)!.lap.status,
  };
}

describe("one lap, one badge on Drive, Review and Progress", () => {
  const rows = [row("alex1", 1, 88663, 100), row("sam1", 2, 88663, 200), row("alex2", 1, 88663, 300)];

  const cases: [string, number, NonNullable<SnapshotNext["bests"]>, "rec" | "pb" | "sb"][] = [
    // the first lap anyone drove here holds the household record
    ["alex1", 6, d2(6, 6, 6), "rec"],
    // Sam ties it later: his best ever, not the record (it stays with the earlier lap)
    ["sam1", 11, d2(11, 11, 6), "pb"],
    // Alex ties his own earlier best: this session's best only (it was "REC" on Drive's laps table and "PB" on Progress)
    ["alex2", 15, d2(15, 6, 6), "sb"],
  ];

  for (const [id, lapId, bests, want] of cases) {
    it(`${id}: ${want.toUpperCase()} everywhere`, () => {
      const s = live(id, lapId, bests);
      const bv = bestsOf(s);
      // Drive: the Best panel, the Session complete card's best lap and the Car page's laps table (current standing)
      expect(sessionBest(s, bv)?.status, "Drive best").toBe(want);
      expect(lapTimesView(s, "ended", bv).best.status, "Drive lap times").toBe(want);
      expect(lapsTile(s).rows.find((r) => r.lap === 3)?.time.status, "Drive laps table").toBe(want);
      // Review: the Best lap tile and the Laps table
      const r = review(id, rows);
      expect(r.tile, "Review tile").toBe(want);
      expect(r.lapsTable, "Review laps").toBe(want);
      // Progress: the session's dot, and the Best here tile when it is the driver's best here
      const badges = sessionBadges(rows, rows, { complete: true });
      expect(badges.get(id), "Progress").toBe(want);
    });
  }

  it("Progress's Best here tile shows the badge of the lap it names", () => {
    const listRows = rows.map((r) => ({ ...r, track_name: "Monza", car_name: "F1 Generic", lap_count: 2, source: "udp:20777" }));
    const alex = listRows.filter((r) => r.driver_id === 1) as unknown as Parameters<typeof pointsFromRows>[0];
    const scope = resolveScope(scopeChoices(alex, { includeSynthetic: false }), {})!;
    const points = pointsFromRows(alex, scope);
    const t = progressTiles(points, [], Date.now(), { badges: sessionBadges(rows, rows, { complete: true }) });
    // Alex's best here is the 1:28.663 of alex1 (alex2 only ties it): the household record
    expect(t.best).toMatchObject({ ms: 88663, status: "rec" });
  });
});
