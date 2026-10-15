// Progress (6.9) and the Coaching plan (6.8) rendered from recorded data (static markup in plain node, no DOM
// library): James's real Austria sessions, D5 computed on a read-only copy of the live database, and the newest
// session's analysis. Data is put in the request cache first, so nothing is fetched. Checks: one computed sentence per
// question, unknown is "-", purple only with exact data, the lap-level fallback says what is missing, density follows
// the VIEWED driver, the radio focus only for the seated driver at this track.
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../../lib/api";
import type { Driver } from "../../../lib/drivers";
import type { DriverProgress } from "../../../lib/endpoints/review";
import { parseHash } from "../../../lib/route-parse";
import { mfx } from "../../../lib/motivation/testkit";
import { workOnItems } from "../../../lib/review/coaching";
import { resolveScope, scopeChoices, scopeQuery } from "../../../lib/review/progress";
import { boardFixtures, driver, fixtures } from "../../../lib/review/testkit";
import { stubBrowser } from "../../../test/fakes";
import type { PageProps } from "../../../routes";

function stubDom(): void {
  const { win } = stubBrowser("http://127.0.0.1:8770/next/#/review/progress");
  Object.assign(win, {
    navigator: globalThis.navigator,
    removeEventListener: () => {},
    screen: { orientation: {} },
    visualViewport: {},
    matchMedia: () => ({ matches: true, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }),
  });
}

let ProgressPage: ComponentType<PageProps>;
let CoachingPage: ComponentType<PageProps>;
let cache: typeof import("../../../lib/cache").cache;
let keys: typeof import("../../../lib/endpoints/review").reviewKeys;
let mkeys: typeof import("../../../lib/endpoints/motivation").motivationKeys;
let lkeys: typeof import("../../../lib/endpoints/leaderboard").leaderboardKeys;
let drivers: typeof import("../../../lib/drivers").drivers;
let live: typeof import("../../../lib/live").live;

beforeAll(async () => {
  stubDom();
  ProgressPage = (await import("../ProgressPage")).ProgressPage;
  CoachingPage = (await import("../CoachingPage")).CoachingPage;
  cache = (await import("../../../lib/cache")).cache;
  keys = (await import("../../../lib/endpoints/review")).reviewKeys;
  mkeys = (await import("../../../lib/endpoints/motivation")).motivationKeys;
  lkeys = (await import("../../../lib/endpoints/leaderboard")).leaderboardKeys;
  drivers = (await import("../../../lib/drivers")).drivers;
  live = (await import("../../../lib/live")).live;
  vi.unstubAllGlobals();
});

function visible(markup: string): string {
  return markup
    .replace(/<span class="sr-only">[^<]*<\/span>/g, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/\s+/g, " ")
    .trim();
}

function honest(text: string, what: string): void {
  for (const bad of ["0:00.000", "--:--", "—", "NaN", "undefined", "null", "Infinity", "[object Object]"]) {
    expect(text, `${what}: ${bad}`).not.toContain(bad);
  }
}

const AUSTRIA = "f1:17";
const HAAS = "f1:team:7";
const james = (): Driver => fixtures.drivers().drivers[0]!;

function setDrivers(list: Driver[], activeId = list[0]?.id ?? null): void {
  (drivers as unknown as { set(p: object): void }).set({ drivers: list, activeId, loaded: true });
}

function setLive(snap: object | null, connected = true): void {
  (live as unknown as { set(p: object): void }).set({ snap, connected });
}

function route(page: "progress" | "coaching", q = `driver=1&track=${encodeURIComponent(AUSTRIA)}&car=${encodeURIComponent(HAAS)}`) {
  return { route: parseHash(`#/review/${page}?${q}`) };
}

const AUSTRIA_HAAS_BOARD = "f1_25~f1:17~4323~f1:team:7~f1~0~race~dry~b2.a?.t?.g3.l2";

/** The keys the pages ask for, filled from fixtures. `d5`: the progress answer, or a 404 like an older server.
 * `board`: the Records section's board (the recorded Austria · Haas · Race board unless given; null: not loaded). */
async function seed(opts: {
  d5: DriverProgress | "missing";
  driverId?: number;
  board?: ReturnType<typeof boardFixtures.austriaHaas> | null;
}): Promise<void> {
  cache.clear();
  const id = opts.driverId ?? 1;
  const rows = fixtures.sessions().map((r) => ({ ...r, driver_id: id }));
  cache.set(keys.driverSessions(id), rows);
  cache.set(keys.sessions, rows); // everyone's newest sessions: where the REC / PB badges are found (lib/bests.ts)
  const scope = resolveScope(scopeChoices(rows, { includeSynthetic: false }), { track: AUSTRIA, car: HAAS })!;
  const k = keys.progress(id, scopeQuery(scope, { corners: true }));
  if (opts.d5 === "missing") await cache.load(k, () => Promise.reject(new ApiError(404, "Not Found"))).catch(() => {});
  else cache.set(k, opts.d5);
  cache.set(keys.analysis("332904dbe3de"), fixtures.austriaAnalysis());
  // Records: the boards at Austria where this driver has a lap, then the board it opens on (the Haas race board)
  cache.set(lkeys.records({ game: "f1_25", track_id: AUSTRIA, driver_id: id }), boardFixtures.recordsAustriaJames());
  const board = opts.board === undefined ? boardFixtures.austriaHaas() : opts.board;
  if (board) cache.set(lkeys.board({ key: AUSTRIA_HAAS_BOARD }), board);
}

beforeEach(() => setLive(null, false));

describe("Progress (6.9) with D5", () => {
  it("advanced, one driver: three questions with one computed sentence each, tiles, milestones, the board", async () => {
    await seed({ d5: fixtures.progressAustriaHaas() });
    setDrivers([james()]);
    const html = renderToStaticMarkup(createElement(ProgressPage, route("progress")));
    const text = visible(html);
    honest(text, "progress");
    expect(text).toContain("Getting faster? Yes: your best here dropped 1.2 s over 2 sessions, and the last one set it.");
    expect(text).toContain(
      "Getting steadier? Less steady than at first: your clean laps are now within 5.8 s of each other, against 4.8 s in the first session here.",
    );
    expect(text).toContain("What changed? 2 sessions compared with the same reference lap");
    expect(text).toContain("Biggest change at Turn 7: 0.82 s lost a lap in the first compared session here, 0.37 s lost in the last.");
    // tiles: best here with the gain in words and a sensible time phrase, sessions, clean laps (D5), PBs this month
    for (const t of ["Best here", "1:10.549", "1.2 s faster since your first session here (", "Sessions", "at Austria in the Haas", "Clean laps", "of 20 laps"]) {
      expect(text).toContain(t);
    }
    expect(text).toContain("New PB 1:10.549");
    expect(text).toContain("First clean lap at Austria");
    expect(text).toContain("Typical clean lap");
    expect(text).toContain("Slower at the slowest point");
    // advanced: corner trends come before Getting faster?
    expect(text.indexOf("What changed?")).toBeLessThan(text.indexOf("Getting faster?"));
    // the one rule (lib/bests.ts): 1:10.549 is the fastest clean lap anyone drove here in the Haas, so it is the
    // family record, purple REC, as on Review and Drive (it was "PB" here before); never "since today"
    expect(html).toContain('data-status="rec"');
    expect(text).not.toContain("since today");
    expect(text).toContain("All of James's driving, every track: 70 laps, 48 clean, at 12 tracks (23 sessions on record).");
    expect(text).not.toContain("Lap-level view");
    expect(text).toContain("Real sessions only");
    // Records (leaderboard spec 5): the exact board, advanced density (percentages, dates, sectors, game version)
    expect(text).toContain("Records Family board Austria · Haas · Race · Dry");
    expect(text).toContain("4.32 km · Braking assist medium, ABS unknown, Traction control unknown, Automatic gears, Racing line full");
    expect(text).toMatch(
      /James in the seat Sat 10 Oct · 18 clean laps 1:10\.549 Fastest 6\.578 s slower 10\.28 % 16\.662 · 31\.149 · 22\.151 Added up: 1:09\.962, 0\.587 s to find/,
    );
    expect(text).toContain("Alex Sun 11 Oct · 5 clean laps 1:13.616 3.067 s behind 4.35 % 9.645 s slower 15.08 %");
    expect(text).toContain("Game version 1.26");
    // the real pole with its caveat and the linked F1DB credit; no band at +10.28 % (none is drawn)
    expect(text).toContain("Times to beat Real F1 pole 2025 · Lando Norris 1:03.971 Austrian Grand Prix, 28 Jun 2025");
    expect(text).toContain("F1 25 is not the real car");
    expect(text).toContain("Real F1 times: F1DB , CC BY 4.0");
    expect(html).toContain('href="https://github.com/f1db/f1db"');
    expect(html).toContain('href="https://creativecommons.org/licenses/by/4.0/"');
    expect(html).not.toContain("data-band=");
    expect(text).not.toContain("Gold: within 3 %");
    // the record history, newest first
    expect(text).toContain("Record history 3 records since Sat 10 Oct");
    expect(text.indexOf("James improved the record: 1:10.549, 1.196 s faster")).toBeLessThan(
      text.indexOf("James set the first record: 1:16.577"),
    );
    // advanced: no glossary
    expect(html).not.toContain("What is family board?");
  });

  it("a beginner's progress (density of the VIEWED driver): captions, Getting faster? first, glossary", async () => {
    await seed({ d5: fixtures.progressAustriaHaas() });
    const beginner = { ...driver(1, "James", "beginner"), stats: james().stats };
    setDrivers([beginner, { ...driver(2, "Alex", "advanced"), stats: { ...james().stats, best_laps: [] } }], 2);
    const html = renderToStaticMarkup(createElement(ProgressPage, route("progress")));
    const text = visible(html);
    honest(text, "beginner");
    expect(text.indexOf("Getting faster?")).toBeLessThan(text.indexOf("What changed?"));
    expect(text).toContain("Each dot is the best clean lap of one session here");
    // James is not in the seat (Alex is): his name, not "your"
    expect(text).toContain("James's best here dropped 1.2 s over 2 sessions");
    // Records, beginner density: the gap in words only (no percentages, dates or sectors), the latest record change
    expect(text).toContain("James 1:10.549 Fastest 6.578 s slower");
    expect(text).toContain("AL Alex in the seat 1:13.616 3.067 s behind 9.645 s slower");
    expect(text).not.toContain("4.35 %");
    expect(text).not.toContain("Game version");
    expect(text).not.toContain("Pole lap: qualifying P1's deciding lap");
    expect(text).toContain("James improved the record: 1:10.549, 1.196 s faster");
    expect(text).not.toContain("James set the first record");
    expect(text).toContain("Show all 3");
    // the caveat and the credit are never left out
    expect(text).toContain("F1 25 is not the real car");
    expect(text).toContain("Real F1 times: F1DB , CC BY 4.0");
    expect(html).toContain('aria-label="What is family board?"');
  });

  it("the family board is one exact board from the server, never any car (an intermediate's view)", async () => {
    await seed({ d5: fixtures.progressAustriaHaas() });
    const jamesMid = { ...driver(1, "James", "intermediate"), stats: james().stats };
    const alex = { ...driver(2, "Alex", "beginner"), stats: { ...james().stats, best_laps: [] } };
    setDrivers([jamesMid, alex], 2);
    const html = renderToStaticMarkup(createElement(ProgressPage, route("progress")));
    const text = visible(html);
    honest(text, "records");
    expect(text).toMatch(/James Sat 10 Oct · 18 clean laps 1:10\.549 Fastest/);
    expect(text).toMatch(/Alex in the seat Sun 11 Oct · 5 clean laps 1:13\.616 3\.067 s behind 4\.35 %/);
    expect(text).not.toContain("cars may differ");
    expect(text).not.toContain("any car");
    // intermediate: percentages and dates, not sectors
    expect(text).not.toContain("16.662 · 31.149 · 22.151");
  });

  it("Records while the board loads, and on a server without boards", async () => {
    await seed({ d5: fixtures.progressAustriaHaas(), board: null });
    setDrivers([james()]);
    const loading = renderToStaticMarkup(createElement(ProgressPage, route("progress")));
    expect(loading).toMatch(/data-records-board="" aria-busy="true"|aria-busy="true"[^>]*data-records-board/);
    expect(visible(loading)).toContain("Records Family board");
    // an older server: the boards' routes answer FastAPI's own 404
    const notFound = () => Promise.reject(new ApiError(404, "Not Found"));
    await cache.load(lkeys.board({ key: AUSTRIA_HAAS_BOARD }), notFound).catch(() => {});
    const text = visible(renderToStaticMarkup(createElement(ProgressPage, route("progress"))));
    expect(text).toContain("The family board needs a newer Pitwall server.");
  });

});

describe("Progress (6.9) before D5", () => {
  it("lap level from the session rows, says what is missing; the badges follow the one rule all the same", async () => {
    await seed({ d5: "missing" });
    setDrivers([james()]);
    const html = renderToStaticMarkup(createElement(ProgressPage, route("progress")));
    const text = visible(html);
    honest(text, "fallback");
    expect(text).toContain("Lap-level view: this Pitwall server does not send progress history yet");
    expect(text).toContain("Yes: your best here dropped 1.2 s over 2 sessions, and the last one set it.");
    expect(text).toContain("Laps");
    expect(text).toContain("Clean laps per session need a newer Pitwall server");
    expect(text).toContain("The spread of clean laps per session needs a newer Pitwall server.");
    expect(text).toContain("Corner trends and habit counts need a newer Pitwall server.");
    expect(text).not.toContain("Typical clean lap");
    // REC / PB come from the session list (lib/bests.ts), not from D5: James's 1:10.549 is the family record here
    expect(html).toContain('data-status="rec"');
    expect(text).toContain("Fastest");
    expect(text).toContain("best that session 1:11.745");
  });

  it("no sessions: an empty state that says what to do", async () => {
    cache.clear();
    cache.set(keys.driverSessions(1), []);
    setDrivers([james()]);
    const text = visible(renderToStaticMarkup(createElement(ProgressPage, route("progress", "driver=1"))));
    expect(text).toContain("No sessions for James yet");
    expect(text).toContain("Open Drive");
  });
});

describe("Coaching plan (6.8)", () => {
  it("This session's focus from the newest compared session, verbatim, with trends; repeats; radio and fixed", async () => {
    await seed({ d5: fixtures.progressAustriaHaas() });
    setDrivers([james()]);
    const html = renderToStaticMarkup(createElement(CoachingPage, route("coaching")));
    const text = visible(html);
    honest(text, "coaching");
    expect(text).toContain("From your last session here, with trends over the sessions before it:");
    // the labels say which question each answers (integration plan 1.3, 5.1)
    expect(text).toContain("This session's focus");
    expect(text).not.toContain("Working on now");
    expect(text).toContain("Turn 6: minimum speed is 9 km/h lower than your reference (164 vs 173 km/h), losing 0.23 s through the corner.");
    expect(text).toContain("better");
    expect(text).toContain("worse");
    expect(text).toContain("Session average here: 0.40 s lost a lap, against 0.79 s lost the session before.");
    expect(text).toContain("See it");
    expect(text).toContain("Repeats lap after lap");
    expect(text).not.toContain("Habits");
    expect(text).toContain("6 of your last 6 laps");
    expect(text).toContain("Radio calls next run");
    // the dashboard's live socket is down in this test: nothing live is claimed
    expect(text).toContain("The live connection is down, so the radio's plan is not known.");
    expect(text).toContain("Recently fixed");
    expect(text).toContain("Nothing yet: a corner shows here once its loss stays under 0.02 s a lap for 2 sessions in a row.");
  });

  it("the session's own 'One to work on' leads the focus, as on its Summary (integration plan 5.1, acceptance D3)", async () => {
    await seed({ d5: fixtures.progressAustriaHaas() });
    setDrivers([james()]);
    const items = workOnItems(fixtures.austriaAnalysis());
    const coachFirst = items[0]!;
    const recapPick = items[1]!; // a corner the coach ranks second
    const recap = mfx.recap();
    recap.things!.work_on = { ...recap.things!.work_on!, observation_key: recapPick.key, corner: recapPick.corner };
    cache.set(mkeys.recap("332904dbe3de"), recap);
    const text = visible(renderToStaticMarkup(createElement(CoachingPage, route("coaching"))));
    const focus = text.slice(text.indexOf("This session's focus"), text.indexOf("Repeats lap after lap"));
    expect(focus).toContain("One to work on (this session)");
    expect(focus.split("One to work on (this session)").length - 1).toBe(1);
    expect(focus.indexOf(recapPick.latest.text)).toBeLessThan(focus.indexOf(coachFirst.latest.text));
    expect(focus.indexOf("One to work on (this session)")).toBeLessThan(focus.indexOf(recapPick.latest.text));
    // without a recap (an older server, or still loading) the coach's own order
    await seed({ d5: fixtures.progressAustriaHaas() });
    const plain = visible(renderToStaticMarkup(createElement(CoachingPage, route("coaching"))));
    expect(plain).not.toContain("One to work on (this session)");
    expect(plain.indexOf(coachFirst.latest.text)).toBeLessThan(plain.indexOf(recapPick.latest.text));
  });

  it("the radio's focus corners from the live plan when this driver is in the seat at this track", async () => {
    await seed({ d5: fixtures.progressAustriaHaas() });
    setDrivers([james()]);
    setLive({
      session: { game: "f1_25", track_id: AUSTRIA },
      cues: {
        mode: "focus",
        reason: null,
        focus: ["T4"],
        cues: [{ corner: "T4", kind: "brake", target_m: 1200, text: "brake", focus: true, reason: "low_min_speed on 4 of the last 5 lap(s)" }],
      },
      track_model: fixtures.austriaAnalysis().track_model,
    });
    const text = visible(renderToStaticMarkup(createElement(CoachingPage, route("coaching"))));
    expect(text).toMatch(/T6\s+FOCUS/);
    expect(text).toContain("slow minimum speed · 4 of the last 5 laps");
  });

  it("before D5: no trends, recently fixed needs the server, the plan still comes from the newest session", async () => {
    await seed({ d5: "missing" });
    setDrivers([james()]);
    const text = visible(renderToStaticMarkup(createElement(CoachingPage, route("coaching"))));
    honest(text, "coaching fallback");
    expect(text).toContain("From your last session here:");
    expect(text).toContain("Turn 6: minimum speed is 9 km/h lower");
    expect(text).not.toContain("Session average here");
    expect(text).toContain("Needs the progress history of a newer Pitwall server.");
  });

  it("a beginner sees the coach's simple wording when the backend sends it", async () => {
    await seed({ d5: fixtures.progressAustriaHaas() });
    const a = fixtures.austriaAnalysis();
    for (const list of Object.values(a.observations)) for (const o of list) o.text_simple = `SIMPLE ${o.corner} ${o.kind}`;
    cache.set(keys.analysis("332904dbe3de"), a);
    setDrivers([{ ...driver(1, "James", "beginner"), stats: james().stats }]);
    const text = visible(renderToStaticMarkup(createElement(CoachingPage, route("coaching"))));
    expect(text).toContain("SIMPLE T4 low_min_speed");
    expect(text).not.toContain("Turn 6: minimum speed is 9 km/h lower");
  });
});
