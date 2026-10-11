// Pace vs AI difficulty rendered (static markup in plain node, no DOM library) from the AI pace contract fixtures:
// real values from the owner's PS5 F1 25 captures in the frozen contract's shapes (lib/review/testkit.ts aiFixtures).
// Summary tile "Pace vs AI · AI difficulty 31", Progress "Against the AI", Coaching "Suggested AI difficulty". Data is put in
// the request cache first, so nothing is fetched. Checks: gaps in words, unknown is "-" with the reason, no number
// without the driver's own data, synthetic sessions excluded, the cards left out on an older server and for GT7.
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../../lib/api";
import type { Driver } from "../../../lib/drivers";
import type { DriverAiPace, SessionAiPace, SessionDetail } from "../../../lib/endpoints/review";
import { parseHash } from "../../../lib/route-parse";
import { aiPaceQuery } from "../../../lib/review/aipace";
import { densityFor } from "../../../lib/review/density";
import { resolveScope, scopeChoices, scopeQuery } from "../../../lib/review/progress";
import { aiFixtures, driver, fixtures } from "../../../lib/review/testkit";
import { stubBrowser } from "../../../test/fakes";
import type { PageProps } from "../../../routes";
import type { KpiTilesProps } from "../session/KpiTiles";

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
let KpiTiles: ComponentType<KpiTilesProps>;
let cache: typeof import("../../../lib/cache").cache;
let keys: typeof import("../../../lib/endpoints/review").reviewKeys;
let drivers: typeof import("../../../lib/drivers").drivers;
let live: typeof import("../../../lib/live").live;

beforeAll(async () => {
  stubDom();
  ProgressPage = (await import("../ProgressPage")).ProgressPage;
  CoachingPage = (await import("../CoachingPage")).CoachingPage;
  KpiTiles = (await import("../session/KpiTiles")).KpiTiles;
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

function route(page: "progress" | "coaching", q = `driver=1&track=${encodeURIComponent(AUSTRIA)}&car=${encodeURIComponent(HAAS)}`) {
  return { route: parseHash(`#/review/${page}?${q}`) };
}

/** The keys the pages ask for. `ai`: the AI pace answer, a 404 like an older server, or nothing (still loading). */
async function seed(opts: { ai: DriverAiPace | "missing" | null; track?: string; car?: string; driverId?: number }): Promise<void> {
  cache.clear();
  const id = opts.driverId ?? 1;
  const rows = fixtures.sessions();
  cache.set(keys.driverSessions(id), rows);
  cache.set(keys.sessions, rows);
  const scope = resolveScope(scopeChoices(rows, { includeSynthetic: false }), { track: opts.track ?? AUSTRIA, car: opts.car ?? HAAS })!;
  cache.set(keys.progress(id, scopeQuery(scope, { corners: true })), fixtures.progressAustriaHaas());
  cache.set(keys.analysis("332904dbe3de"), fixtures.austriaAnalysis());
  const k = keys.aiPace(id, aiPaceQuery({ game: scope.track.game, trackId: scope.track.trackId }));
  if (opts.ai === "missing") await cache.load(k, () => Promise.reject(new ApiError(404, "Not Found"))).catch(() => {});
  else if (opts.ai) cache.set(k, opts.ai);
}

beforeEach(() => (live as unknown as { set(p: object): void }).set({ snap: null, connected: false }));

describe("Summary tile: Pace vs AI", () => {
  const tiles = (session: SessionDetail, list: Driver[] = [james()]) => {
    cache.clear();
    setDrivers(list);
    return renderToStaticMarkup(createElement(KpiTiles, { session, density: densityFor(session.driver_id, list) }));
  };
  const withAi = (ai: SessionAiPace | null | undefined): SessionDetail => ({ ...fixtures.austria(), ai_pace: ai });

  it("the scenario race at AI 31: 4.9 s faster than the typical AI car, 1st of 18, the AI field strip", () => {
    const html = tiles(withAi(aiFixtures.austriaScenario()));
    const text = visible(html);
    honest(text, "ai tile");
    expect(text).toContain("Pace vs AI · AI difficulty 31");
    expect(text).toContain("4.9 s faster");
    expect(text).toContain("than the typical AI car's best lap · 1st of 18 on best laps");
    // advanced (the recorded James): the fastest AI car's best lap too, and no strip caption
    expect(text).toContain("fastest AI 1:13.228");
    expect(text).not.toContain("Each mark is one AI car's best lap");
    expect(text).toContain(
      "From 17 AI cars, 116 laps · not used: 94 laps not seen from their start, 16 laps the game filled in (not driven), 3 pit laps, 19 laps around a flashback",
    );
    expect(html).toContain('aria-label="Your best lap 1:10.549 among 17 AI cars&#x27; best laps, 1:13.228 to 1:17.251: 1st of 18"');
    expect(html).toContain('data-ai-status="ok"');
    // never a bare sign for the gap
    expect(text).not.toMatch(/[−-]4\.9/);
    expect(html).not.toContain("pw-chip-synthetic");
  });

  it("an intermediate driver: no fastest-AI detail, a glossary for the typical AI car", () => {
    const list = [{ ...driver(1, "James", "intermediate"), stats: james().stats }];
    const html = tiles(withAi(aiFixtures.austriaScenario()), list);
    const text = visible(html);
    expect(text).not.toContain("fastest AI");
    expect(html).toContain('aria-label="What is typical ai car?"');
    expect(text).toContain("Each mark is one AI car's best lap; the tall mark is the typical AI car.");
  });

  it("no AI in the session (null, absent on an older server, a time trial): no tile", () => {
    for (const ai of [null, undefined, { ...aiFixtures.austriaScenario(), status: "time_trial" as const }]) {
      const text = visible(tiles(withAi(ai)));
      expect(text).not.toContain("Pace vs AI");
      expect(text).toContain("Best lap");
    }
  });

  it("difficulty unknown: '-' and the reason, no level in the title", () => {
    const unknown: SessionAiPace = {
      ...aiFixtures.austriaScenario(),
      status: "unknown_difficulty",
      ai_difficulty: null,
      ai_ref_ms: null,
      ai_best_ms: null,
      ai_p25_ms: null,
      ai_p75_ms: null,
      ai_median_lap_ms: null,
      ai_bests_ms: [],
      gap_ms: null,
      gap_pct: null,
      gap_to_best_ai_ms: null,
      field_rank: null,
      field_size: null,
    };
    const html = tiles(withAi(unknown));
    const text = visible(html);
    honest(text, "unknown difficulty");
    expect(text).toContain("Pace vs AI");
    expect(text).not.toContain("AI difficulty 3");
    expect(text).toContain("AI difficulty not reported");
    expect(html).toContain('data-ai-status="unknown_difficulty"');
    expect(html.slice(html.indexOf('data-ai-status="unknown_difficulty"'))).toContain('data-unknown=""');
  });

  it("too few AI cars: '-' and the reason", () => {
    const text = visible(tiles(withAi(aiFixtures.monza())));
    expect(text).toContain("Pace vs AI · AI difficulty 35");
    expect(text).toContain("Too few AI laps: needs clean laps from 5 AI cars, saw 2");
    expect(text).toContain("Seen: 2 AI cars, 2 laps"); // never "From": nothing was built from them
  });

  it("a synthetic session keeps its tile with the SYNTHETIC tag", () => {
    const html = tiles({ ...withAi(aiFixtures.austriaScenario()), synthetic: true });
    expect(visible(html)).toContain("Pace vs AI · AI difficulty 31");
    expect(html).toContain("pw-chip-synthetic");
  });

  it("the Sessions preview keeps its four tiles", () => {
    cache.clear();
    setDrivers([james()]);
    const html = renderToStaticMarkup(
      createElement(KpiTiles, { session: withAi(aiFixtures.austriaScenario()), density: { kpiTiles: 4, glossary: false }, ai: false }),
    );
    expect(visible(html)).not.toContain("Pace vs AI");
  });
});

describe("Progress: Against the AI", () => {
  it("the newest class at this track (F1 Modern) with a toggle for F1 World; the server's sentence; the list", async () => {
    await seed({ ai: aiFixtures.driverAustria() });
    setDrivers([james()]);
    const html = renderToStaticMarkup(createElement(ProgressPage, route("progress")));
    const text = visible(html);
    honest(text, "progress ai");
    expect(text).toContain("Against the AI");
    expect(text).toContain(
      "At AI 31 your best lap here was 4.9 s (6.5%) faster than the typical AI car's best lap, so try a higher level. Race here once more at AI 36 or higher and Pitwall can suggest a level.",
    );
    expect(text).toContain("F1 Modern");
    expect(text).toContain("F1 World");
    expect(text).toContain("AI 31: 4.9 s faster than the typical AI car's best lap (6.5% faster) · 1st of 18 on best laps");
    expect(text).toContain("AI 31: 3.7 s faster than the typical AI car's best lap (5.0% faster) · 1st of 18 on best laps");
    expect(html).toContain("Your best lap against the typical AI car per session"); // two sessions: the chart
    // the F1 World race is on the other tab, not in this list
    expect(text).not.toContain("20th of 20");
    expect(html).toContain('aria-label="Sessions against the AI"');
    // after Getting faster? (an advanced driver: corner trends first, then Getting faster?, then the AI)
    expect(text.indexOf("Getting faster?")).toBeLessThan(text.indexOf("Against the AI"));
  });

  it("no races against the AI here yet: says so", async () => {
    await seed({ ai: { ...aiFixtures.driverAustria(), points: [], suggestions: [], unusable: [] } });
    setDrivers([james()]);
    const text = visible(renderToStaticMarkup(createElement(ProgressPage, route("progress"))));
    expect(text).toContain("Against the AI No races against the AI at Austria yet.");
  });

  it("a race here that could not be compared says so, about the viewed driver, never 'no races'", async () => {
    const monza = aiFixtures.driverAll().unusable![0]!;
    await seed({ ai: { ...aiFixtures.driverAustria(), points: [], suggestions: [], unusable: [monza] }, driverId: 2 });
    const sam = { ...driver(2, "Sam", "beginner"), stats: james().stats };
    setDrivers([james(), sam], 1); // James in the seat, looking at Sam's page
    const text = visible(renderToStaticMarkup(createElement(ProgressPage, route("progress", `driver=2&track=${encodeURIComponent(AUSTRIA)}&car=${encodeURIComponent(HAAS)}`))));
    expect(text).not.toContain("No races against the AI");
    expect(text).toContain("Sam's race here at AI difficulty 35 could not be compared with the AI: too few clean AI laps were seen.");
  });

  it("synthetic sessions are excluded even if the server sent one", async () => {
    const data = aiFixtures.driverAustria();
    // the recorded list has the synthetic demo (6cb367d74b7f); pretend the server sent it as a point here
    const synth = { ...data.points[2]!, session_id: "6cb367d74b7f", started_unix: data.points[2]!.started_unix + 60, gap_pct: -20, gap_ms: -15000 };
    await seed({ ai: { ...data, points: [...data.points, synth] } });
    setDrivers([james()]);
    const text = visible(renderToStaticMarkup(createElement(ProgressPage, route("progress"))));
    expect(text).toContain("Against the AI");
    expect(text).not.toContain("15.0 s faster");
    expect(text).not.toContain("20.0% faster");
    // control: the same point from a real session is shown
    await seed({ ai: { ...data, points: [...data.points, { ...synth, session_id: "real-one" }] } });
    expect(visible(renderToStaticMarkup(createElement(ProgressPage, route("progress"))))).toContain(
      "AI 31: 15.0 s faster than the typical AI car's best lap (20.0% faster) · 1st of 18 on best laps",
    );
  });

  it("left out on a server without AI pace (404) and for a game without AI difficulty", async () => {
    await seed({ ai: "missing" });
    setDrivers([james()]);
    expect(visible(renderToStaticMarkup(createElement(ProgressPage, route("progress"))))).not.toContain("Against the AI");

    const gt7 = "gt7:sf:0:100:90:920:340";
    await seed({ ai: { ...aiFixtures.driverAustria(), points: [], suggestions: [] }, track: gt7, car: "gt7:car:919" });
    const text = visible(
      renderToStaticMarkup(createElement(ProgressPage, route("progress", `driver=1&track=${encodeURIComponent(gt7)}&car=any`))),
    );
    expect(text).not.toContain("Against the AI");
  });

  it("while loading: a placeholder, no numbers", async () => {
    await seed({ ai: null });
    setDrivers([james()]);
    const html = renderToStaticMarkup(createElement(ProgressPage, route("progress")));
    expect(visible(html)).toContain("Against the AI");
    expect(visible(html)).not.toContain("typical AI car");
  });
});

describe("Coaching: Suggested AI difficulty", () => {
  it("one level raced per class here: which way to go, large, the next level to race, never a level of its own", async () => {
    await seed({ ai: aiFixtures.driverAustria() });
    setDrivers([james()]);
    const html = renderToStaticMarkup(createElement(CoachingPage, route("coaching")));
    const text = visible(html);
    honest(text, "coaching ai");
    expect(text).toContain("Suggested AI difficulty");
    expect(text).toContain("Aim: a best lap level with the typical AI car's (mid-pack)");
    expect(text).toMatch(/Austria · F1 Modern class( \([^)]+\))? · races · dry Higher than AI 31 Not enough levels raced yet/);
    expect(text).toMatch(/Austria · F1 World class( \([^)]+\))? · races · dry Lower than AI 35 Not enough levels raced yet/);
    expect(text).toContain(
      "At AI 35 your best lap here was 3.8 s (5.1%) slower than the typical AI car's best lap, so a lower level should give closer racing. Race here once more at AI 30 or lower and Pitwall can suggest a level.",
    );
    expect(html).not.toContain('data-ai-basis="level"');
    expect(text).not.toMatch(/Range \d|Measured here/);
    // first beside the repeats and the radio calls, not last on the page
    expect(text.indexOf("Suggested AI difficulty")).toBeLessThan(text.indexOf("Radio calls next run"));
  });

  it("a parent looking at a child's plan reads about the child", async () => {
    await seed({ ai: aiFixtures.driverAustria(), driverId: 2 });
    const sam = { ...driver(2, "Sam", "beginner"), stats: james().stats };
    setDrivers([james(), sam], 1);
    const text = visible(renderToStaticMarkup(createElement(CoachingPage, route("coaching", `driver=2&track=${encodeURIComponent(AUSTRIA)}&car=${encodeURIComponent(HAAS)}`))));
    expect(text).toContain("At AI 35 Sam's best lap here was 3.8 s (5.1%) slower than the typical AI car's best lap");
    expect(text).not.toMatch(/\byour best lap here\b/);
  });

  it("a measured suggestion: the level large, its range, confidence and the server's sentence", async () => {
    const data = aiFixtures.driverAustria();
    const m = {
      ...data.suggestions[0]!,
      basis: "measured" as const,
      level: 38,
      range: [35, 41] as [number, number],
      confidence: "medium" as const,
      sessions_used: 3,
      levels_used: [31, 36, 41],
      slope_pct_per_level: 0.4,
      text: "Try AI 38 here, between 35 and 41. Measured from 3 races at levels 31, 36 and 41.",
    };
    await seed({ ai: { ...data, suggestions: [m] } });
    setDrivers([james()]);
    const html = renderToStaticMarkup(createElement(CoachingPage, route("coaching")));
    const text = visible(html);
    expect(text).toMatch(/Suggested AI difficulty Austria · F1 Modern class( \([^)]+\))? · races · dry Aim: .* AI 38 Range 35–41 Medium confidence Measured here/);
    expect(text).toContain("Try AI 38 here, between 35 and 41. Measured from 3 races at levels 31, 36 and 41.");
    expect(html).toContain('data-ai-basis="level"');
  });

  it("no suggestion here, or an older server: no card", async () => {
    await seed({ ai: { ...aiFixtures.driverAustria(), points: [], suggestions: [] } });
    setDrivers([james()]);
    expect(visible(renderToStaticMarkup(createElement(CoachingPage, route("coaching"))))).not.toContain("Suggested AI difficulty");
    await seed({ ai: "missing" });
    expect(visible(renderToStaticMarkup(createElement(CoachingPage, route("coaching"))))).not.toContain("Suggested AI difficulty");
  });

  it("synthetic suggestion keys never show", async () => {
    const data = aiFixtures.driverAustria();
    const synth = data.suggestions.map((s) => ({ ...s, key: { ...s.key, track_id: `synthetic:${s.key.track_id}` } }));
    await seed({ ai: { ...data, suggestions: synth } });
    setDrivers([james()]);
    expect(visible(renderToStaticMarkup(createElement(CoachingPage, route("coaching"))))).not.toContain("Suggested AI difficulty");
  });
});
