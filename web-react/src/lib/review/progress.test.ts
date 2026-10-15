// Progress logic (spec 6.9) on recorded data: James's real PS5 F1 25 sessions (the session list from the live API,
// and D5 answers computed on a read-only copy of the live database). Small hand-made inputs only where the recorded
// data has no such case (a second driver, a third session); they are test inputs, never shown as game evidence.
import { describe, expect, it } from "vitest";
import type { SessionListRow } from "../endpoints/review";
import { isMissingRoute, progressUrl, reviewKeys } from "../endpoints/review";
import { ApiError } from "../api";
import { RequestCache } from "../cache";
import {
  ANY_CAR,
  bestSteps,
  changeSentence,
  cornerTextOf,
  cornerTrends,
  familyBoard,
  fasterSentence,
  habitTrends,
  milestones,
  pointsFromProgress,
  pointsFromRows,
  progressTiles,
  bestHereLine,
  resolveScope,
  scopeChoices,
  scopeQuery,
  sessionLabels,
  steadierSentence,
  whoFor,
  type SessionPoint,
} from "./progress";
import { boardFixtures, driver, fixtures } from "./testkit";
import { sessionBadges } from "../bests";

const rows = (): (SessionListRow & { car_id?: string | null })[] => fixtures.sessions();
const you = whoFor({ id: 1, name: "James" }, 1, 1);
const AUSTRIA = "f1:17";
const HAAS = "f1:team:7";

function point(over: Partial<SessionPoint> & { sessionId: string; startedUnix: number }): SessionPoint {
  return {
    synthetic: false,
    carId: HAAS,
    carName: "Haas",
    sessionType: "race",
    laps: 10,
    cleanLaps: 9,
    bestMs: null,
    medianMs: null,
    spreadMs: null,
    corners: null,
    habits: null,
    refLapId: null,
    ...over,
  };
}

describe("scope (track + car) from the driver's sessions", () => {
  it("lists driven tracks newest first, never replays, synthetic only on request, sessions without laps left out", () => {
    const real = scopeChoices(rows(), { includeSynthetic: false });
    expect(real[0]?.label).toBe("Unidentified GT7 circuit (0.92 km)");
    expect(real.some((t) => t.synthetic)).toBe(false);
    expect(real.every((t) => t.sessions > 0)).toBe(true);
    const austria = real.find((t) => t.trackId === AUSTRIA)!;
    expect(austria.sessions).toBe(3);
    expect(austria.cars.map((c) => [c.id, c.label, c.sessions])).toEqual([
      [HAAS, "Haas", 2],
      ["f1:team:41", "F1 Generic", 1],
    ]);
    expect(austria.newestCarId).toBe(HAAS);

    const withSyn = scopeChoices(rows(), { includeSynthetic: true });
    const syn = withSyn.filter((t) => t.synthetic);
    // the replayed demo stays out: nobody's driving; a raw id stored as the name reads "Unknown track" (plan 5.8)
    expect(syn.map((t) => t.label)).toEqual(["Unknown track"]);
  });

  it("never a raw id for a car or a track (integration plan 5.8): 'Unnamed car', numbered when there are more", () => {
    const base = rows().find((r) => r.track_id === AUSTRIA)!;
    const at = (car_id: string, car_name: string | null, t: number) => ({ ...base, id: `x${t}`, car_id, car_name, started_unix: base.started_unix + t });
    const c = scopeChoices(
      [at("f1:team:214", "team_214", 30), at("gt7:car:919", null, 20), at("f1:team:99", "Unknown team (id 99)", 10), at(HAAS, "Haas", 5)],
      { includeSynthetic: false },
    );
    const austria = c.find((t) => t.trackId === AUSTRIA)!;
    expect(austria.cars.map((x) => [x.label, x.named])).toEqual([
      ["Unnamed car 1", false],
      ["Unnamed car 2", false],
      ["Unnamed car 3", false],
      ["Haas", true],
    ]);
    expect(resolveScope(c, { track: AUSTRIA, car: "f1:team:214" })!.carLabel).toBe("Unnamed car 1");
    const one = scopeChoices([at("gt7:car:919", null, 20)], { includeSynthetic: false });
    expect(one[0]!.cars[0]!.label).toBe("Unnamed car");
  });

  it("resolves ?track and ?car, defaults to the newest track and its newest car, `any` = every car", () => {
    const c = scopeChoices(rows(), { includeSynthetic: false });
    expect(resolveScope(c, {})?.track.trackId).toBe(c[0]!.trackId);
    const a = resolveScope(c, { track: AUSTRIA })!;
    expect([a.track.label, a.carId, a.carLabel]).toEqual(["Austria", HAAS, "Haas"]);
    expect(resolveScope(c, { track: AUSTRIA, car: ANY_CAR })!.carId).toBeNull();
    expect(resolveScope(c, { track: AUSTRIA, car: "f1:team:41" })!.carLabel).toBe("F1 Generic");
    // an unknown car falls back to the default, an unknown track to the newest
    expect(resolveScope(c, { track: AUSTRIA, car: "f1:team:99" })!.carId).toBe(HAAS);
    expect(resolveScope(c, { track: "f1:999" })!.track.trackId).toBe(c[0]!.trackId);
    // Suzuka's sessions have no car id: only "any car" can cover them
    const suzuka = resolveScope(c, { track: "f1:13" })!;
    expect([suzuka.carId, suzuka.track.unknownCar]).toEqual([null, 2]);
    expect(resolveScope([], {})).toBeNull();
  });

  it("asks D5 for exactly the scope", () => {
    const c = scopeChoices(rows(), { includeSynthetic: false });
    const q = scopeQuery(resolveScope(c, { track: AUSTRIA })!, { corners: false });
    expect(progressUrl(1, q)).toBe("/api/drivers/1/progress?game=f1_25&track_id=f1%3A17&car=f1%3Ateam%3A7&corners=false&limit=50");
    const syn = scopeChoices(rows(), { includeSynthetic: true }).find((t) => t.synthetic)!;
    expect(progressUrl(1, scopeQuery({ track: syn, carId: null, carLabel: null }))).toContain("synthetic=true");
  });

  it("progress keys live under driver-sessions: so laps and driver switches refresh them", () => {
    const cache = new RequestCache();
    const k = reviewKeys.progress(1, { game: "f1_25", track_id: AUSTRIA, car: HAAS });
    cache.set(k, {});
    cache.invalidate("driver-sessions:");
    expect(cache.entry(k).stale).toBe(true);
    expect(k).not.toBe(reviewKeys.progress(1, { game: "f1_25", track_id: AUSTRIA, car: null }));
  });

  it("knows an older server without the D5 route from a real 404", () => {
    expect(isMissingRoute(new ApiError(404, "Not Found"))).toBe(true);
    expect(isMissingRoute(new ApiError(404, "driver 7 not found"))).toBe(false);
    expect(isMissingRoute(new ApiError(500, "boom"))).toBe(false);
    expect(isMissingRoute(new Error("404: Not Found"))).toBe(false);
  });
});

describe("points: D5 and the lap-level fallback agree on what they share", () => {
  it("the fallback takes the scope's rows oldest first, with unknowns as null", () => {
    const c = scopeChoices(rows(), { includeSynthetic: false });
    const pts = pointsFromRows(rows(), resolveScope(c, { track: AUSTRIA })!);
    expect(pts.map((p) => [p.sessionId, p.bestMs])).toEqual([
      ["a100cbc9b5bd", 71745],
      ["332904dbe3de", 70549],
    ]);
    expect(pts.every((p) => p.cleanLaps === null && p.spreadMs === null && p.corners === null)).toBe(true);
    const any = pointsFromRows(rows(), resolveScope(c, { track: AUSTRIA, car: ANY_CAR })!);
    expect(any.map((p) => p.carName)).toEqual(["F1 Generic", "Haas", "Haas"]);
  });

  it("D5's points carry clean laps, median, spread, corners and habits", () => {
    const pts = pointsFromProgress(fixtures.progressAustriaHaas());
    expect(pts.map((p) => [p.bestMs, p.medianMs, p.spreadMs, p.cleanLaps])).toEqual([
      [71745, 72959, 4832, 9],
      [70549, 71718, 5776, 9],
    ]);
    const fallback = pointsFromRows(rows(), resolveScope(scopeChoices(rows(), { includeSynthetic: false }), { track: AUSTRIA })!);
    expect(pts.map((p) => [p.sessionId, p.bestMs])).toEqual(fallback.map((p) => [p.sessionId, p.bestMs]));
  });

  it("clean_lap_count on a row (D5's list column) is used before the progress route answers", () => {
    const r = rows().map((x) => (x.id === "332904dbe3de" ? { ...x, clean_lap_count: 9 } : x));
    const pts = pointsFromRows(r, resolveScope(scopeChoices(r, { includeSynthetic: false }), { track: AUSTRIA })!);
    expect(pts.map((p) => p.cleanLaps)).toEqual([null, 9]);
  });
});

describe("session labels on the x axis", () => {
  it("the day, with the time when a day has more than one session", () => {
    const at = (y: number, mo: number, d: number, h: number, mi = 0) => new Date(y, mo, d, h, mi).getTime() / 1000;
    const now = new Date(2026, 9, 11, 12).getTime();
    expect(
      sessionLabels([{ startedUnix: at(2026, 9, 3, 19) }, { startedUnix: at(2026, 9, 10, 19, 41) }, { startedUnix: at(2026, 9, 10, 21, 2) }, { startedUnix: at(2026, 9, 11, 9) }], now),
    ).toEqual(["3 Oct", "Yesterday 19:41", "Yesterday 21:02", "Today"]);
  });
});

describe("Getting faster? one computed sentence", () => {
  it("real data: the best dropped and the last session set it", () => {
    const pts = pointsFromProgress(fixtures.progressAustriaHaas());
    expect(fasterSentence(pts, you)).toBe("Yes: your best here dropped 1.2 s over 2 sessions, and the last one set it.");
    expect(fasterSentence(pts, whoFor({ id: 2, name: "Alex" }, 1, 3))).toContain("Alex's best here dropped 1.2 s");
    expect(whoFor({ id: 3, name: "James" }, 1, 3).poss).toBe("James's");
  });

  it("across different cars the sentence says the change mixes car and driver, and the tile has no trend", () => {
    const pts = pointsFromProgress(fixtures.progressAustriaAny());
    expect(fasterSentence(pts, you, { multiCar: true })).toBe(
      "Your best here dropped 7.8 s over 3 sessions, and the last one set it; the cars differ, so not all of that is the driver.",
    );
    const t = progressTiles(pts, [], Date.now(), { multiCar: true });
    expect([t.best.ms, t.best.gainMs, t.best.carOfBest]).toEqual([70549, null, "Haas"]);
  });

  it("one session, none, no clean lap yet", () => {
    const silverstone = pointsFromProgress(fixtures.progressSilverstone());
    expect(fasterSentence(silverstone, you)).toBe(
      "One session here with a clean lap so far (your best is 1:43.819): drive here again to see a trend.",
    );
    expect(fasterSentence([], you)).toMatch(/^No sessions here yet/);
    expect(fasterSentence([point({ sessionId: "a", startedUnix: 1 })], you)).toMatch(/^No clean lap here yet in 1 session/);
  });

  it("the last session off the best; no faster yet; a typical lap getting faster while the best stands", () => {
    const off = [
      point({ sessionId: "a", startedUnix: 1, bestMs: 72_000 }),
      point({ sessionId: "b", startedUnix: 2, bestMs: 70_800 }),
      point({ sessionId: "c", startedUnix: 3, bestMs: 71_150 }),
    ];
    expect(fasterSentence(off, you)).toBe("Yes: your best here dropped 1.2 s over 3 sessions; the last session was 0.35 s off it.");
    const flat = [point({ sessionId: "a", startedUnix: 1, bestMs: 70_000 }), point({ sessionId: "b", startedUnix: 2, bestMs: 70_400 })];
    expect(fasterSentence(flat, you)).toBe("Not yet: your best here is still the 1:10.000 from the first of 2 sessions.");
    const typical = [
      point({ sessionId: "a", startedUnix: 1, bestMs: 70_000, medianMs: 72_000 }),
      point({ sessionId: "b", startedUnix: 2, bestMs: 70_100, medianMs: 71_200 }),
    ];
    expect(fasterSentence(typical, you)).toBe(
      "Your best here still dates from the first session, but your typical lap got 0.80 s faster over 2 sessions.",
    );
  });
});

describe("Getting steadier? (D5 spread)", () => {
  it("real data says less steady, in words", () => {
    expect(steadierSentence(pointsFromProgress(fixtures.progressAustriaHaas()), you)).toBe(
      "Less steady than at first: your clean laps are now within 5.8 s of each other, against 4.8 s in the first session here.",
    );
  });
  it("steadier, about the same, one session, unknown", () => {
    const s = (a: number | null, b: number | null) => [
      point({ sessionId: "a", startedUnix: 1, spreadMs: a }),
      point({ sessionId: "b", startedUnix: 2, spreadMs: b }),
    ];
    expect(steadierSentence(s(3100, 1400), you)).toBe("Steadier: your clean laps went from within 3.1 s to within 1.4 s of each other over 2 sessions.");
    expect(steadierSentence(s(1420, 1380), you)).toBe("About as steady as at first: your clean laps are within 1.4 s of each other.");
    expect(steadierSentence(s(null, 900), you)).toMatch(/within 0.90 s of each other in the one session/);
    expect(steadierSentence(s(null, null), you)).toBe("Needs a session here with 2 clean laps.");
  });
});

describe("PBs and milestones", () => {
  it("D5's PB history is collapsed per session: the first clean lap, then the gain over the best before", () => {
    const p = fixtures.progressAustriaHaas();
    const steps = bestSteps(pointsFromProgress(p), p.pb_history);
    expect(steps.map((s) => [s.sessionId, s.ms, s.previousMs, s.gainMs, s.first])).toEqual([
      ["a100cbc9b5bd", 71745, null, null, true],
      ["332904dbe3de", 70549, 71745, 1196, false],
    ]);
    const m = milestones(pointsFromProgress(p), steps, { trackLabel: "Austria", multiCar: false });
    expect(m.map((x) => [x.kind, x.title, x.detail])).toEqual([
      ["pb", "New PB 1:10.549", "1.2 s faster than before · lap 64"],
      ["first_clean", "First clean lap at Austria", "1:16.577 · lap 62"],
    ]);
  });

  it("any car: one PB line per car; the first lap in another car is its own milestone", () => {
    const p = fixtures.progressAustriaAny();
    const steps = bestSteps(pointsFromProgress(p), p.pb_history);
    const m = milestones(pointsFromProgress(p), steps, { trackLabel: "Austria", multiCar: true });
    expect(m.map((x) => x.title)).toEqual(["New PB 1:10.549", "First clean lap in the Haas", "First clean lap at Austria"]);
    expect(m[2]!.detail).toBe("1:18.351 · lap 2 · F1 Generic");
    expect(m[0]!.detail).toBe("1.2 s faster than before · lap 64 · Haas");
  });

  it("without D5, steps come from session bests (unknown cars never count) and say less", () => {
    const pts = [
      point({ sessionId: "a", startedUnix: 1, bestMs: 72_000 }),
      point({ sessionId: "b", startedUnix: 2, bestMs: 72_500 }),
      point({ sessionId: "c", startedUnix: 3, bestMs: 71_000 }),
      point({ sessionId: "d", startedUnix: 4, bestMs: 60_000, carId: null, carName: null }),
    ];
    const steps = bestSteps(pts, null);
    expect(steps.map((s) => [s.sessionId, s.gainMs])).toEqual([
      ["a", null],
      ["c", 1000],
    ]);
    expect(milestones(pts, steps, { trackLabel: "Austria", multiCar: false }).map((m) => m.detail)).toEqual([
      "1.0 s faster than before",
      "best that session 1:12.000",
    ]);
  });

  it("the first session with 10 clean laps, only when clean counts are known", () => {
    const pts = [point({ sessionId: "a", startedUnix: 1, cleanLaps: 4 }), point({ sessionId: "b", startedUnix: 2, laps: 12, cleanLaps: 10 })];
    expect(milestones(pts, [], { trackLabel: "X", multiCar: false }).map((m) => [m.title, m.detail])).toEqual([
      ["First session with 10 clean laps", "10 of 12 laps"],
    ]);
    expect(milestones([point({ sessionId: "a", startedUnix: 1, cleanLaps: null })], [], { trackLabel: "X", multiCar: false })).toEqual([]);
  });
});

describe("headline tiles", () => {
  it("best here with its gain and sparkline, sessions, clean laps, PBs this month; the badge the one rule gives", () => {
    const p = fixtures.progressAustriaHaas();
    const pts = pointsFromProgress(p);
    const steps = bestSteps(pts, p.pb_history);
    const now = Date.UTC(2026, 9, 11, 12); // the data is from 10-11 Oct 2026
    // the same badges Review and Drive give these sessions (lib/bests.ts), from the recorded session list
    const list = fixtures.sessions();
    const badges = sessionBadges(list, list, { complete: true });
    const t = progressTiles(pts, steps, now, { badges });
    // 1:10.549 is the fastest clean lap anyone drove at Austria in the Haas: REC, as on Review (not only "PB")
    expect(t.best).toMatchObject({ ms: 70549, status: "rec", gainMs: 1196 });
    expect(t.best.spark.map((x) => Number(x.v.toFixed(3)))).toEqual([0, 1.196]);
    expect(t.sessions).toBe(2);
    expect(t.clean).toEqual({ known: true, clean: 18, laps: 20 });
    expect(t.newPbs.count).toBe(1);
    // badges not loaded yet: unknown stays unknown (no colour)
    expect(progressTiles(pts, steps, now, {}).best.status).toBe("neutral");
    // a PB that is not the family record (someone else holds a faster lap here)
    const pbOnly = new Map([["332904dbe3de", "pb" as const]]);
    expect(progressTiles(pts, steps, now, { badges: pbOnly }).best.status).toBe("pb");
    // a month later nothing is "this month"
    expect(progressTiles(pts, steps, Date.UTC(2026, 10, 20), { badges }).newPbs.count).toBe(0);
  });

  it("says the gain with a sensible time phrase: 'today', or 'since your first session here (3 Oct)'", () => {
    const p = fixtures.progressAustriaHaas();
    const pts = pointsFromProgress(p);
    const steps = bestSteps(pts, p.pb_history);
    const first = pts[0]!.startedUnix * 1000;
    const sameDay = progressTiles(pts, steps, first + 60_000, {});
    expect(bestHereLine(sameDay, first + 60_000, { poss: "your" })).toBe("1.2 s faster today");
    const later = first + 5 * 86_400_000;
    expect(bestHereLine(progressTiles(pts, steps, later, {}), later, { poss: "Alex's" })).toMatch(
      /^1\.2 s faster since Alex's first session here \(\d{1,2} [A-Z][a-z]{2}\)$/,
    );
    expect(bestHereLine(sameDay, first, { poss: "your" })).not.toContain("since today");
  });

  it("before D5 the clean count is unknown (the tile shows laps)", () => {
    const c = scopeChoices(rows(), { includeSynthetic: false });
    const pts = pointsFromRows(rows(), resolveScope(c, { track: AUSTRIA })!);
    const t = progressTiles(pts, bestSteps(pts, null), Date.now(), {});
    expect(t.clean).toEqual({ known: false, clean: 0, laps: 20 });
    expect(t.best.status).toBe("neutral");
  });
});

describe("What changed? (D5 corner trends and habits)", () => {
  it("corner means against the same reference, biggest change first, official words from corner_text", () => {
    const p = fixtures.progressAustriaHaas();
    const trends = cornerTrends(pointsFromProgress(p), p.corner_text, "f1_25", AUSTRIA, 0.02);
    expect(trends[0]).toMatchObject({ key: "T5", label: "T7", long: "Turn 7", first: 0.823, last: 0.372, trend: "better" });
    expect(trends[1]).toMatchObject({ key: "T4", label: "T6", first: 0.793, last: 0.402, trend: "better" });
    expect(trends.find((t) => t.key === "T2")).toMatchObject({ label: "T3", trend: "worse" });
    expect(changeSentence(trends, 2)).toBe("Biggest change at Turn 7: 0.82 s lost a lap in the first compared session here, 0.37 s lost in the last.");
    expect(cornerTextOf(p.corner_text, "f1_25", AUSTRIA, "T6")).toEqual({ label: "T9", long: "Turn 9 (Rindt Kurve)" });
    expect(cornerTextOf(null, "f1_25", AUSTRIA, "T6")).toEqual({ label: "T6", long: "T6" });
  });

  it("needs two compared sessions; a session without corner means does not count", () => {
    const p = fixtures.progressSilverstone();
    expect(cornerTrends(pointsFromProgress(p), p.corner_text, "f1_25", "f1:7")).toEqual([]);
    expect(changeSentence([], 1)).toBe("Needs two sessions here compared with the reference lap.");
  });

  it("habit counts per session, most seen last time first, in plain words", () => {
    const h = habitTrends(pointsFromProgress(fixtures.progressAustriaHaas()));
    expect(h[0]).toMatchObject({ kind: "low_min_speed", words: "Slower at the slowest point" });
    expect(h[0]!.counts.map((c) => [c.count, c.laps])).toEqual([
      [37, 10],
      [23, 10],
    ]);
    expect(h.find((x) => x.kind === "late_throttle")!.counts.map((c) => c.count)).toEqual([1, 0]);
  });
});

describe("family board (an exact board from the server)", () => {
  const james = () => fixtures.drivers().drivers[0]!;

  it("each driver's best on one exact key: neutral times, the leader in words, the server's gap words", () => {
    const alex = driver(2, "Alex", "beginner");
    const b = familyBoard([james(), alex], boardFixtures.austriaHaas(), 2);
    expect(b.key).toBe("f1_25~f1:17~4323~f1:team:7~f1~0~race~dry~b2.a?.t?.g3.l2");
    expect(b.labels?.title).toBe("Austria · Haas · Race · Dry");
    expect(b.rows.map((r) => [r.name, r.position, r.ms, r.gapMs, r.gapText, r.leader, r.viewed])).toEqual([
      ["James", 1, 70549, null, "Fastest", true, false],
      ["Alex", 2, 73616, 3067, "3.067 s behind", false, true],
    ]);
    expect(b.rows[0]!.driver?.name).toBe("James");
    expect(b.rows[1]).toMatchObject({ gapPct: 4.35, sessionId: expect.any(String), dateText: expect.any(String) });
    expect(b.rows[0]!.vs.real_f1).toMatchObject({ gap_ms: 6578, band: null });
    expect(b.record).toMatchObject({ ms: 70549, name: "James" });
  });

  it("household drivers with no time on the board come last, by name, with nothing made up", () => {
    const b = familyBoard([], boardFixtures.timeTrial(), 1);
    expect(b.rows.map((r) => [r.name, r.ms, r.gapText])).toEqual([
      ["Jo", 65900, "Fastest"],
      ["Sam", 66000, "0.100 s behind"],
      ["Kim", null, null],
    ]);
    // a profile this page does not know: the server's name, no avatar data
    expect(b.rows.every((r) => r.driver === null)).toBe(true);
    expect(b.rows[2]).toMatchObject({ position: null, vs: {}, sectorsMs: null, cleanLaps: null });
  });

  it("no board (loading, nothing matched, or an older server): no rows and no record, never another car's times", () => {
    expect(familyBoard([james()], null, 1)).toEqual({ key: null, labels: null, rows: [], record: null });
    const none = familyBoard([james()], boardFixtures.austriaNoMatch(), 1);
    expect(none.key).toBeNull();
    expect(none.record).toBeNull();
    expect(none.rows.every((r) => r.ms == null)).toBe(true);
  });
});
