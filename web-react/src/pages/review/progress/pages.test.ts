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
import { resolveScope, scopeChoices, scopeQuery } from "../../../lib/review/progress";
import { driver, fixtures } from "../../../lib/review/testkit";
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
let drivers: typeof import("../../../lib/drivers").drivers;
let live: typeof import("../../../lib/live").live;

beforeAll(async () => {
  stubDom();
  ProgressPage = (await import("../ProgressPage")).ProgressPage;
  CoachingPage = (await import("../CoachingPage")).CoachingPage;
  cache = (await import("../../../lib/cache")).cache;
  keys = (await import("../../../lib/endpoints/review")).reviewKeys;
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

/** The keys the pages ask for, filled from fixtures. `d5`: the progress answer, or a 404 like an older server. */
async function seed(opts: { d5: DriverProgress | "missing"; driverId?: number }): Promise<void> {
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
  });

  it("a beginner's progress (density of the VIEWED driver): captions, Getting faster? first, glossary", async () => {
    await seed({ d5: fixtures.progressAustriaHaas() });
    const beginner = { ...driver(1, "James", "beginner"), stats: james().stats };
    setDrivers([beginner, { ...driver(2, "Jo", "advanced"), stats: { ...james().stats, best_laps: [] } }], 2);
    const text = visible(renderToStaticMarkup(createElement(ProgressPage, route("progress"))));
    honest(text, "beginner");
    expect(text.indexOf("Getting faster?")).toBeLessThan(text.indexOf("What changed?"));
    expect(text).toContain("Each dot is the best clean lap of one session here");
    // James is not in the seat (Jo is): his name, not "your"
    expect(text).toContain("James' best here dropped 1.2 s over 2 sessions");
    // two drivers but no family answer cached yet: neutral board, any car
    expect(text).toContain("Best lap at this track in any car, so the cars may differ.");
  });

  it("family board with D5 for every driver at one car: exact car, neutral times, the leader 'Fastest'", async () => {
    await seed({ d5: fixtures.progressAustriaHaas() });
    const haas = fixtures.progressAustriaHaas();
    const jo = { ...driver(2, "Jo", "intermediate"), stats: { ...james().stats, best_laps: [] } };
    setDrivers([james(), jo]);
    const fam = new Map<number, DriverProgress>([
      [1, haas],
      [2, { ...haas, driver_id: 2, pb_history: [{ ...haas.pb_history[0]!, lap_ms: 70_100, session_id: "jo1" }] }],
    ]);
    const rows = fixtures.sessions();
    const scope = resolveScope(scopeChoices(rows, { includeSynthetic: false }), { track: AUSTRIA, car: HAAS })!;
    cache.set(keys.familyProgress([1, 2], scopeQuery(scope, { corners: false })), fam);
    // Jo's faster session is in everyone's session list too (where the badges are found)
    const james1 = rows.find((r) => r.id === "332904dbe3de")!;
    cache.set(keys.sessions, [{ ...james1, id: "jo1", driver_id: 2, best_clean_ms: 70_100, started_unix: james1.started_unix + 3600 }, ...rows]);
    const html = renderToStaticMarkup(createElement(ProgressPage, route("progress")));
    const text = visible(html);
    // (the chart's fastest-in-the-family line is drawn by Recharts in the browser only; the board says it in words)
    expect(text).toMatch(/Jo 1:10\.100 Fastest/);
    expect(text).toMatch(/James in the seat 1:10\.549 0\.449 s slower/); // a gap to a best: as precise as the times
    expect(text).toContain("Each driver's best clean lap here in this car.");
    expect(text).not.toContain("cars may differ");
    // Jo holds the family record; James's best here is his PB (the one rule, lib/bests.ts), never REC on his page
    expect(html).not.toContain('data-status="rec"');
    expect(html).toContain('data-status="pb"');
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
  it("Working on now from the newest compared session, verbatim, with trends; habits; radio and fixed", async () => {
    await seed({ d5: fixtures.progressAustriaHaas() });
    setDrivers([james()]);
    const html = renderToStaticMarkup(createElement(CoachingPage, route("coaching")));
    const text = visible(html);
    honest(text, "coaching");
    expect(text).toContain("From your last session here, with trends over the sessions before it:");
    expect(text).toContain("Working on now");
    expect(text).toContain("Turn 6: minimum speed is 9 km/h lower than your reference (164 vs 173 km/h), losing 0.23 s through the corner.");
    expect(text).toContain("better");
    expect(text).toContain("worse");
    expect(text).toContain("Session average here: 0.40 s lost a lap, against 0.79 s lost the session before.");
    expect(text).toContain("See it");
    expect(text).toContain("Habits");
    expect(text).toContain("6 of your last 6 laps");
    // the dashboard's live socket is down in this test: nothing live is claimed
    expect(text).toContain("The live connection is down, so the radio's plan is not known.");
    expect(text).toContain("Recently fixed");
    expect(text).toContain("Nothing yet: a corner shows here once its loss stays under 0.02 s a lap for 2 sessions in a row.");
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
