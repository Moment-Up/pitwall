// Review › Goals: goals, the week and badges (lane motivation, spec 9; design spec 6.9, 6.10; moved off Progress by
// integration plan 1.3), rendered to static markup in plain node: the recorded Austria sessions for the scope bar,
// the edited motivation fixtures for the cards (put in the request cache first, nothing fetched). Every state: goals
// with progress and a reached goal whose session moved, no goals (suggestions inline, or why there are none), a game
// that cannot be checked, synthetic tracks, a beginner's wording, an older server; and Progress without any of them.
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../../lib/api";
import type { Driver } from "../../../lib/drivers";
import type { SuggestionsQuery } from "../../../lib/endpoints/motivation";
import { DEFAULT_DRAFT, type DraftScope, type GoalDraft } from "../../../lib/motivation/goals";
import { mfx } from "../../../lib/motivation/testkit";
import { parseHash } from "../../../lib/route-parse";
import { resolveScope, scopeChoices, scopeQuery } from "../../../lib/review/progress";
import { driver, fixtures } from "../../../lib/review/testkit";
import { stubBrowser } from "../../../test/fakes";
import type { PageProps } from "../../../routes";
import type { GoalsCardProps } from "./GoalsCard";
import type { GoalSheetProps } from "./GoalSheet";

function stubDom(): void {
  const { win } = stubBrowser("http://127.0.0.1:8825/#/review/progress");
  Object.assign(win, {
    navigator: globalThis.navigator,
    removeEventListener: () => {},
    screen: { orientation: {} },
    visualViewport: {},
    matchMedia: () => ({ matches: true, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }),
  });
}

let ProgressPage: ComponentType<PageProps>;
let GoalsPage: ComponentType<PageProps>;
let GoalsCard: ComponentType<GoalsCardProps>;
let GoalForm: ComponentType<{ draft: GoalDraft; onChange: (d: GoalDraft) => void; scope: DraftScope | null }>;
let GoalSheetBody: ComponentType<Omit<GoalSheetProps, "isOpen" | "onClose" | "driverName">>;
let WeekCard: ComponentType<{ driverId: number; simple: boolean }>;
let BadgesCard: ComponentType<{ driverId: number; driverName: string; simple: boolean }>;
let cache: typeof import("../../../lib/cache").cache;
let keys: typeof import("../../../lib/endpoints/review").reviewKeys;
let mkeys: typeof import("../../../lib/endpoints/motivation").motivationKeys;
let drivers: typeof import("../../../lib/drivers").drivers;

beforeAll(async () => {
  stubDom();
  ProgressPage = (await import("../ProgressPage")).ProgressPage;
  GoalsPage = (await import("../GoalsPage")).GoalsPage;
  GoalsCard = (await import("./GoalsCard")).GoalsCard;
  ({ GoalForm, GoalSheetBody } = await import("./GoalSheet"));
  WeekCard = (await import("./WeekCard")).WeekCard;
  BadgesCard = (await import("./BadgesCard")).BadgesCard;
  cache = (await import("../../../lib/cache")).cache;
  keys = (await import("../../../lib/endpoints/review")).reviewKeys;
  mkeys = (await import("../../../lib/endpoints/motivation")).motivationKeys;
  drivers = (await import("../../../lib/drivers")).drivers;
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
const SQ: SuggestionsQuery = { game: "f1_25", track_id: AUSTRIA, car: HAAS };

function setDrivers(list: Driver[], activeId = list[0]?.id ?? null): void {
  (drivers as unknown as { set(p: object): void }).set({ drivers: list, activeId, loaded: true });
}

const fail404 = (k: string) => cache.load(k, () => Promise.reject(new ApiError(404, "Not Found"))).catch(() => {});

/** The Progress page's own data (sessions, D5) and the motivation cards' data, for driver 1 at Austria / Haas. */
async function seed(opts: { goals?: "full" | "empty" | "missing"; suggestions?: "full" | "none"; motivation?: "missing" } = {}) {
  cache.clear();
  const rows = fixtures.sessions().map((r) => ({ ...r, driver_id: 1 }));
  cache.set(keys.driverSessions(1), rows);
  cache.set(keys.sessions, rows);
  const scope = resolveScope(scopeChoices(rows, { includeSynthetic: false }), { track: AUSTRIA, car: HAAS })!;
  cache.set(keys.progress(1, scopeQuery(scope, { corners: true })), fixtures.progressAustriaHaas());
  if (opts.motivation === "missing" || opts.goals === "missing") {
    await fail404(mkeys.goals(1));
    await fail404(mkeys.digest(1, null));
    await fail404(mkeys.badges(1));
    return;
  }
  cache.set(mkeys.goals(1), opts.goals === "empty" ? mfx.goalsEmpty() : mfx.goals());
  cache.set(mkeys.suggestions(1, SQ), opts.suggestions === "none" ? mfx.suggestionsNone() : mfx.suggestions());
  cache.set(mkeys.digest(1, null), mfx.digest());
  cache.set(mkeys.badges(1), mfx.badges());
}

function page(
  level: "beginner" | "intermediate" | "advanced" = "intermediate",
  which: "goals" | "progress" = "goals",
): { html: string; text: string } {
  setDrivers([{ ...driver(1, "Sam", level), stats: fixtures.drivers().drivers[0]!.stats }]);
  const Page = which === "goals" ? GoalsPage : ProgressPage;
  const html = renderToStaticMarkup(
    createElement(Page, { route: parseHash(`#/review/${which}?driver=1&track=${encodeURIComponent(AUSTRIA)}&car=${encodeURIComponent(HAAS)}`) }),
  );
  return { html, text: visible(html) };
}

beforeEach(() => cache.clear());

describe("Review › Goals: goals, the week and badges", () => {
  it("goals with their progress, why, the reached ones (one moved to another driver), the week and the badges", async () => {
    await seed();
    const { html, text } = page("intermediate");
    honest(text, "goals");
    // the scope bar of Progress: the driver, and the track and car a new lap-time goal is for; a way back to Progress
    expect(text).toContain("Austria");
    expect(text).toContain("Real sessions only");
    expect(text).toContain("Progress");
    // Goals
    expect(text).toContain("Goals 3 active · 2 reached in the last 30 days");
    expect(text).toContain("A lap under 1:10.000 Austria · Haas");
    expect(text).toContain("0.301 s to go · best since you set it 1:10.301");
    expect(text).toContain("Why this target?");
    expect(text).toContain("8 clean laps in a row");
    expect(text).toContain("Best since you set it: 6 of 8 laps");
    expect(text).toContain("Reached in the last 30 days");
    expect(text).toContain("Finish a race with no penalties");
    expect(text).toContain("Done: Suzuka, Sat 10 Oct");
    expect(text).toContain("The session that reached it now belongs to another driver. Reopen");
    expect(text).toContain("Open the session");
    expect(text).toContain("Add a goal");
    expect(text).toContain("From Sam's real driving: synthetic and replayed sessions never count.");
    expect(text).not.toContain("does not report track limits"); // F1 reports them
    // This week: sessions newest first, improvements and new tracks apart, no badge list of its own
    expect(text).toContain("This week 5 to 11 Oct");
    expect(text).toContain("17 sessions, 60 laps, a new best at Austria");
    expect(text).toContain("47 clean laps · 1 h 32 min driving · 12 tracks");
    expect(text).toContain("Show all 17"); // a button, not a dead "+10 more"
    expect(text).toContain("New tracks Suzuka · F1 Generic First clean laps here: 1:35.412");
    expect(text).not.toContain("New tracks and improvements");
    expect(text).toContain("Goals this week Reached: Finish a race with no penalties");
    expect(text).toContain("from 50% to 75% of the way");
    expect(text).toContain("Printable page");
    expect(text).toContain("Copy as text");
    expect(text).toContain("Real driving only: a session counts once it has a timed lap");
    expect(text).not.toContain("Badges this week");
    expect(text).not.toContain("+2 more");
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*aria-label="Week after"/); // the current week: nothing after it
    const week = text.slice(text.indexOf("This week 5 to 11 Oct"), text.indexOf("Streaks and badges"));
    const days = [...week.matchAll(/(Mon|Tue|Wed|Thu|Fri|Sat|Sun) (\d+) Oct/g)].map((m) => Number(m[2]));
    expect(days.length).toBeGreaterThan(1);
    expect(days[0]).toBeGreaterThanOrEqual(days[days.length - 1]!); // newest first
    // Streaks and badges: the one full list of badges, after goals and the week
    expect(text).toContain("Weeks in a row 1");
    expect(text).toContain("Sessions this week 17 with a timed lap, from Monday");
    expect(text).toContain("Best clean run 6");
    expect(text).toContain("First time under 1:11 at Austria in the Haas");
    expect(text).toContain("First clean lap at Brands Hatch");
    expect(text).toContain("Show all 8");
    expect(text.split("First clean lap at Brands Hatch").length - 1).toBe(1); // listed once on the page
    // Layout: goals and the week in a row under the scope bar (stacked below lg), then streaks and badges
    expect(html).toMatch(/lg:col-span-7"><div class="card[^"]*"[^>]*data-motivation="goals"/);
    expect(html).toMatch(/lg:col-span-5"><div class="card[^"]*"[^>]*data-motivation="week"/);
    expect(text.indexOf("This week")).toBeLessThan(text.indexOf("Streaks and badges"));
  });

  it("Progress keeps to the scope bar: no goals, no week, no badges; a link to Goals instead", async () => {
    await seed();
    for (const level of ["intermediate", "advanced"] as const) {
      const { html, text } = page(level, "progress");
      honest(text, `progress ${level}`);
      expect(html).not.toContain("data-motivation=");
      expect(text).not.toContain("Streaks and badges");
      expect(text).not.toContain("This week");
      expect(text).not.toContain("Add a goal");
      expect(text).toContain("Getting faster?");
      expect(text).toContain("Goals"); // the scope bar's link
    }
  });

  it("a beginner reads the simple wording everywhere", async () => {
    await seed();
    const { text } = page("beginner");
    honest(text, "beginner");
    expect(text).toContain("Beat 1:10.000");
    expect(text).toContain("About 0.3 s to go");
    expect(text).toContain("You drove 17 times this week");
    expect(text).toContain("You beat 1:11 at Austria in the Haas for the first time");
    expect(text).not.toContain("A lap under 1:10.000");
  });

  it("no goals yet: says so, with the top two suggestions inline", async () => {
    await seed({ goals: "empty" });
    const { text } = page();
    expect(text).toContain("No goals yet. Pick one Pitwall suggests from Sam's driving, or make your own.");
    expect(text).toContain("A lap under 1:10.000 Austria · Haas Your best sectors here add up to 1:09.962");
    expect(text).toContain("8 clean laps in a row");
    expect(text).not.toContain("5 clean laps within 1.1 s of each other"); // only two inline
    expect(text.split("Set this goal").length - 1).toBe(2);
  });

  it("no goals and nothing to suggest yet: the server's reason", async () => {
    await seed({ goals: "empty", suggestions: "none" });
    const { text } = page();
    expect(text).toContain(
      "Not enough history here yet: Pitwall needs your best sectors or a recent improvement to suggest a target",
    );
  });

  it("an older server: each card says what it needs", async () => {
    await seed({ motivation: "missing" });
    const { text } = page();
    honest(text, "older server");
    expect(text).toContain("Goals need a newer Pitwall server.");
    expect(text).toContain("The weekly summary needs a newer Pitwall server.");
    expect(text).toContain("Streaks and badges need a newer Pitwall server.");
    expect(text).not.toContain("Add a goal");
  });
});

describe("GoalsCard in other scopes", () => {
  const gt7: GoalsCardProps["scope"] = {
    game: "gt7",
    trackId: "gt7:loc:351",
    trackLabel: "Brands Hatch",
    carId: "gt7:car:3389",
    carLabel: "Porsche 911 GT3 RS",
    synthetic: false,
  };

  it("a game without lap validity: the footnote says what 'clean' means there", () => {
    cache.set(mkeys.goals(1), mfx.goals());
    const text = visible(renderToStaticMarkup(createElement(GoalsCard, { driverId: 1, driverName: "Sam", simple: false, scope: gt7 })));
    expect(text).toContain("This game does not report track limits, so 'clean' means no pit lap, reset or flashback.");
  });

  it("a synthetic track: no suggestions asked for, and why", () => {
    cache.set(mkeys.goals(1), mfx.goalsEmpty());
    const text = visible(
      renderToStaticMarkup(createElement(GoalsCard, { driverId: 1, driverName: "Sam", simple: false, scope: { ...gt7, synthetic: true } })),
    );
    expect(text).toContain("Pick a real track above to see suggestions: goals only count real driving.");
  });

  it("at the limit of active goals: Add is off and says why", () => {
    const g = mfx.goals();
    g.limits = { max_active: 6, active: 6 };
    cache.set(mkeys.goals(1), g);
    const html = renderToStaticMarkup(createElement(GoalsCard, { driverId: 1, driverName: "Sam", simple: false, scope: gt7 }));
    expect(visible(html)).toContain("6 goals at once at most: archive or delete one to add another.");
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>[^]*?Add a goal/);
  });
});

describe("Add a goal (GoalSheet)", () => {
  const austria: DraftScope = {
    game: "f1_25",
    trackId: AUSTRIA,
    trackLabel: "Austria",
    carId: HAAS,
    carLabel: "Haas",
    carClass: "f1_25:formula:F1 World",
    synthetic: false,
  };
  const gt7: DraftScope = { ...austria, game: "gt7", trackId: "gt7:loc:351", trackLabel: "Brands Hatch", carId: "gt7:car:3389", carLabel: "Porsche 911 GT3 RS", carClass: null };
  const form = (kind: GoalDraft["kind"], scope: DraftScope | null) =>
    visible(renderToStaticMarkup(createElement(GoalForm, { draft: { ...DEFAULT_DRAFT, kind }, onChange: () => {}, scope })));

  it("Suggested: Pitwall's targets with why and Set this goal (56 px)", () => {
    const html = renderToStaticMarkup(
      createElement(GoalSheetBody, {
        driverId: 1,
        scope: austria,
        suggestions: mfx.suggestions(),
        suggestionsError: null,
        simple: false,
        onCreated: () => {},
      }),
    );
    const text = visible(html);
    expect(text).toContain("Suggested Make your own");
    expect(text).toContain("A lap under 1:10.000 Austria · Haas");
    expect(text).toContain("9 races finished in the last 30 days: 6 without a penalty, none without contact.");
    expect(text.split("Set this goal").length - 1).toBe(4);
    expect(html).toContain("min-h-14");
  });

  it("Make your own, lap time: this car or its class, and the time to a tenth", () => {
    const text = form("lap_time", austria);
    expect(text).toContain("Lap time Clean laps Steady laps Clean race");
    expect(text).toContain("At Austria · Haas (from the track and car above).");
    expect(text).toContain("This car Haas");
    expect(text).toContain("Any F1 World car the same class");
    expect(text).toContain("A lap under");
    expect(text).toContain("Minutes and seconds to a tenth, like 1:10.0.");
    // GT7 has no class Pitwall can trust: no class choice
    expect(form("lap_time", gt7)).not.toContain("In which car?");
    // no track yet, or a synthetic one
    expect(form("lap_time", null)).toContain("A lap-time goal is for one track: drive there first");
    expect(form("lap_time", { ...austria, synthetic: true })).toContain("This is a synthetic track: goals only count real driving.");
  });

  it("Make your own, lap time: a lap-time goal already set here is said up front, and Set this goal is off", () => {
    const html = renderToStaticMarkup(
      createElement(GoalSheetBody, {
        driverId: 1,
        scope: { ...austria, carClass: null },
        suggestions: undefined,
        suggestionsError: null,
        activeGoals: mfx.goals().goals,
        simple: false,
        initialTab: "own",
        onCreated: () => {},
      }),
    );
    const text = visible(html);
    expect(text).toContain("You already have a lap-time goal here: A lap under 1:10.000. Archive it to set a new time.");
    expect(text).not.toContain("Minutes and seconds to a tenth");
    expect(html).toMatch(/<button[^>]*disabled[^>]*>[^<]*Set this goal/);
  });

  it("no track yet (a driver with no sessions): the form starts on clean laps, which count anywhere", () => {
    const text = visible(
      renderToStaticMarkup(
        createElement(GoalSheetBody, {
          driverId: 1,
          scope: null,
          suggestions: undefined,
          suggestionsError: null,
          simple: true,
          initialTab: "own",
          onCreated: () => {},
        }),
      ),
    );
    expect(text).toContain("Clean laps in a row");
    expect(text).toContain("Between 2 and 50, anywhere you drive.");
  });

  it("Make your own, clean laps, steady laps and clean race", () => {
    expect(form("clean_streak", austria)).toContain("Clean laps in a row");
    expect(form("clean_streak", austria)).toContain("Between 2 and 50, anywhere you drive.");
    const steady = form("consistency", austria);
    expect(steady).toContain("How many laps in a row? 3 laps 5 laps 10 laps");
    expect(steady).toContain("All within (seconds)");
    expect(form("race_clean", austria)).toContain("Pitwall can only check this in F1 races recorded from lap 1 to the flag.");
    // not supported by this game
    expect(form("race_clean", gt7)).toContain("Pitwall can only check this in F1 races: this game does not report races.");
  });
});

describe("a driver with no sessions yet", () => {
  function noSessions(): void {
    cache.clear();
    cache.set(keys.driverSessions(1), []);
    cache.set(keys.sessions, []);
    cache.set(mkeys.goals(1), mfx.goalsEmpty());
    setDrivers([{ ...driver(1, "Sam", "beginner"), stats: fixtures.drivers().drivers[0]!.stats }]);
  }

  it("Goals still offers goals, so a parent can set a first one before the first drive", () => {
    noSessions();
    const text = visible(renderToStaticMarkup(createElement(GoalsPage, { route: parseHash("#/review/goals?driver=1") })));
    honest(text, "no sessions");
    expect(text).toContain("Goals None active");
    expect(text).toContain("Add a goal");
    expect(text).toContain("Drive a session to see suggestions.");
  });

  it("Progress says what to do, and links to Goals for a first goal", () => {
    noSessions();
    const text = visible(renderToStaticMarkup(createElement(ProgressPage, { route: parseHash("#/review/progress?driver=1") })));
    honest(text, "no sessions");
    expect(text).toContain("No sessions for Sam yet");
    expect(text).toContain("Open Drive");
    expect(text).toContain("Set a goal");
    expect(text).not.toContain("Add a goal");
  });
});

describe("the week and badges on their own", () => {
  it("a week without driving", () => {
    cache.set(mkeys.digest(1, null), mfx.digestEmpty());
    const text = visible(renderToStaticMarkup(createElement(WeekCard, { driverId: 1, simple: false })));
    honest(text, "empty week");
    expect(text).toContain("Week 28 Sep to 4 Oct");
    expect(text).toContain("No driving this week.");
    expect(text).not.toContain("Sessions");
    expect(text).not.toContain("Printable page"); // nothing to print or copy
    expect(text).not.toContain("Copy as text");
  });

  it("a driver with no badges yet", () => {
    cache.set(mkeys.badges(3), mfx.badgesEmpty());
    const text = visible(renderToStaticMarkup(createElement(BadgesCard, { driverId: 3, driverName: "Sam", simple: true })));
    honest(text, "no badges");
    expect(text).toContain("No badges yet: Sam's first clean lap at a track earns the first one.");
    expect(text).toContain("Weeks in a row 0");
  });
});
