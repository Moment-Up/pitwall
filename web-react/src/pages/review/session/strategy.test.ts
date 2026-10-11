// Review › Session › Strategy (lane "strategy") rendered to static markup in plain node, like tabs.test.ts: every
// state (races only, not supported by this game, recorded before strategy tracking, an older server, loading), the
// race itself (KPIs, timeline, stints, stops, calls, tier note), synthetic sessions, beginner wording and the phone
// layout. Data is passed in (StrategyTabView) or put in the request cache first, so nothing is fetched.
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../../lib/api";
import type { Driver } from "../../../lib/drivers";
import type { SessionDetail } from "../../../lib/endpoints/review";
import { densityFor, type Density } from "../../../lib/review/density";
import { driver, fixtures } from "../../../lib/review/testkit";
import { parseHash } from "../../../lib/route-parse";
import { timeline } from "../../../lib/strategy/testkit";
import type { StrategyTimeline } from "../../../lib/strategy/types";
import { stubBrowser } from "../../../test/fakes";
import type { StrategyTabViewProps } from "./StrategyTab";

let StrategyTabView: ComponentType<StrategyTabViewProps>;
let SessionPage: ComponentType<{ id: string; tab: "summary" | "strategy"; route: ReturnType<typeof parseHash> }>;
let cache: typeof import("../../../lib/cache").cache;
let reviewKeys: typeof import("../../../lib/endpoints/review").reviewKeys;
let strategyKeys: typeof import("../../../lib/endpoints/strategy").strategyKeys;
let drivers: typeof import("../../../lib/drivers").drivers;

beforeAll(async () => {
  const { win } = stubBrowser("http://127.0.0.1:8770/next/#/review/sessions/332904dbe3de/strategy");
  Object.assign(win, {
    navigator: globalThis.navigator,
    removeEventListener: () => {},
    screen: { orientation: {} },
    visualViewport: {},
    matchMedia: () => ({ matches: true, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }),
  });
  StrategyTabView = (await import("./StrategyTab")).StrategyTabView;
  SessionPage = (await import("../SessionPage")).SessionPage as never;
  cache = (await import("../../../lib/cache")).cache;
  reviewKeys = (await import("../../../lib/endpoints/review")).reviewKeys;
  strategyKeys = (await import("../../../lib/endpoints/strategy")).strategyKeys;
  drivers = (await import("../../../lib/drivers")).drivers;
  vi.unstubAllGlobals();
});

function visible(markup: string): string {
  return markup
    .replace(/<span class="sr-only">[^<]*<\/span>/g, "")
    .replace(/<p class="sr-only">[^<]*<\/p>/g, "")
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
  for (const bad of ["NaN", "undefined", "null", "Infinity", "[object Object]", "—", "0:00.000"]) {
    expect(text, `${what}: ${bad}`).not.toContain(bad);
  }
}

function setDrivers(list: Driver[]): void {
  (drivers as unknown as { set(p: object): void }).set({ drivers: list, activeId: list[0]?.id ?? null, loaded: true });
}

const austria = (): SessionDetail => fixtures.austria();

function density(level: Driver["preferences"]["skill_level"] | null): Density {
  const list = level ? [driver(9, "Test", level)] : [];
  return densityFor(level ? 9 : null, list);
}

function view(
  session: SessionDetail,
  t: StrategyTimeline | undefined,
  opts: { level?: Driver["preferences"]["skill_level"] | null; narrow?: boolean; error?: Error | null } = {},
): string {
  return renderToStaticMarkup(
    createElement(StrategyTabView, {
      session,
      density: density(opts.level ?? "intermediate"),
      timeline: t,
      error: opts.error ?? null,
      narrow: opts.narrow ?? false,
    }),
  );
}

describe("Strategy tab states", () => {
  it("a practice session: 'Strategy is shown for races only.' (Pro EmptyState)", () => {
    const html = view(fixtures.demo(), undefined);
    expect(html).toContain("data-strategy-empty");
    expect(visible(html)).toContain("Strategy is shown for races only.");
  });

  it("not supported by this game: a GT7 race", () => {
    const text = visible(view({ ...austria(), game: "gt7" }, undefined));
    expect(text).toContain("No race strategy for this game.");
    expect(text).toContain("only F1 25 sends");
  });

  it("an old race: recorded before strategy tracking", () => {
    expect(visible(view(austria(), timeline("edited-timeline-before-tracking")))).toContain(
      "This race was recorded before Pitwall tracked strategy.",
    );
  });

  it("an older server (FastAPI's own 404) and other errors say so in words", () => {
    expect(visible(view(austria(), undefined, { error: new ApiError(404, "Not Found") }))).toContain(
      "This Pitwall server has no race strategy yet.",
    );
    expect(visible(view(austria(), undefined, { error: new Error("network down") }))).toContain("network down");
  });

  it("loading: a skeleton, no numbers", () => {
    const html = view(austria(), undefined);
    expect(html).toContain('aria-busy="true"');
    expect(html).not.toContain("data-strategy-tab");
  });
});

describe("Strategy tab: a race", () => {
  it("Austria: KPIs, timeline, stint, no stop of yours, other cars' stops by number, calls verbatim, tier note", () => {
    const html = view(austria(), timeline("edited-timeline-austria"));
    const text = visible(html).replace(/ \? /g, " "); // the glossary buttons (intermediate)
    honest(text, "austria");
    for (const t of [
      "Positions P9 → P1 Gained 8 places from lap 62",
      "Stops 0 No pit stop",
      "Pit loss 18.9 s 1 measured",
      "Fuel at the flag +2.3 laps Spare fuel when the race ended",
      "Race timeline",
      "Stints",
      "You did not stop in this race.",
      "Other cars' stops (measured) · 2",
      "Strategy calls",
      "Car behind is within a second.",
      "Measured values come from this race's own timing.",
    ]) {
      expect(text).toContain(t);
    }
    expect(html).toContain('aria-label="Stints"'); // the stint bar under the chart
    expect(html).toContain("Medium, laps 62 to 71");
    expect(html).toContain('aria-label="Weather"');
    expect(html).toContain("Light cloud from lap 63, the game&#x27;s rain figure 7 percent");
    // other drivers are numbers, never names
    expect(text).not.toMatch(/Max|Lewis|Charles|Lando/);
    expect(html).not.toContain("SYNTHETIC");
  });

  it("recorded: the engine's timeline over the committed Austria excerpt renders without inventing anything", () => {
    const text = visible(view(austria(), timeline("recorded-timeline-austria-excerpt"), { level: "advanced" }));
    honest(text, "recorded excerpt");
    for (const t of ["P14 → P20", "Lost 6 places from lap 1", "No pit stop measured in this race", "+3.2 laps", "Soft", "L1\u20133 · 3"]) {
      expect(text).toContain(t);
    }
    expect(text).not.toContain("Other cars' stops");
  });

  it("synthetic: the SYNTHETIC chip, your stop under the VSC, the band in words, the note says synthetic first", () => {
    const s = { ...fixtures.demo(), session_type: "race", game: "f1_25", synthetic: true };
    const html = view(s, timeline("edited-timeline-synthetic"));
    const text = visible(html);
    honest(text, "synthetic");
    expect(html).toContain('data-evidence="synthetic"');
    expect(text).toContain("Stops 1 L8 · Medium → Hard");
    expect(text).toContain("Under the virtual safety car");
    expect(text).toContain("Shaded laps: Virtual safety car on laps 7\u20138.");
    expect(text).toContain("Synthetic session: generated data, not from a game.");
    expect(text).toContain("Fuel critical: 0.4 laps short. Lift and coast about 2 s a lap, brake at your normal point.");
    expect(text).not.toMatch(/brake\w* later/i);
  });

  it("synthetic, from the backend: the race-strategy-demo scenario's own timeline renders without inventing anything", () => {
    const s = { ...fixtures.demo(), session_type: "race", game: "f1_25", synthetic: true };
    const html = view(s, timeline("synthetic-timeline-race-strategy-demo"), { level: "advanced" });
    const text = visible(html);
    honest(text, "synthetic scenario");
    expect(html).toContain('data-evidence="synthetic"');
    // the scenario's ground truth: the player stops just after the VSC on lap 8 (not a fair measurement, said so),
    // two other cars stop under green
    expect(text).toContain("Stops 1 L8 · Medium → Soft");
    expect(text).toContain("Not counted: safety car for only part of the stop");
    expect(text).toContain("Pit loss 12.8 s 2 measured");
    expect(text).toContain("Shaded laps: Virtual safety car on laps 7\u20138.");
    expect(text).toContain("Other cars' stops (measured) · 2");
    expect(text).toContain("Virtual safety car. Pitting this lap is an option");
    expect(text).toContain("Car behind is pitting. Box next lap to cover the undercut.");
    expect(text).toContain("Synthetic session: generated data, not from a game.");
    expect(text).not.toMatch(/brake\w* later/i);
  });

  it("beginner wording: plain titles, the glossary, captions; advanced: no glossary, no captions", () => {
    const beginner = view(austria(), timeline("edited-timeline-austria"), { level: "beginner" });
    const b = visible(beginner);
    expect(b).toContain("Start → finish");
    expect(b).toContain("Tyre sets");
    expect(b).toContain("Your position lap by lap (higher is better)");
    expect(beginner).toContain('aria-label="What is pit loss?"');
    expect(beginner).toContain('aria-label="What is stint?"');
    const advanced = view(austria(), timeline("edited-timeline-austria"), { level: "advanced" });
    expect(visible(advanced)).toContain("Positions");
    expect(advanced).not.toContain("pw-gloss");
    expect(visible(advanced)).not.toContain("Your position lap by lap");
  });

  it("a race joined late: the stops the game counted before the record, never 'You did not stop' (review H2)", () => {
    const t = timeline("edited-timeline-austria");
    t.laps = t.laps.map((l) => ({ ...l, stops: 2 }));
    const text = visible(view(austria(), t)).replace(/ \? /g, " ");
    expect(text).toContain("Stops 2 2 before lap 62 (game)");
    expect(text).toContain("The game counts 2 stops before Pitwall's record began on lap 62.");
    expect(text).not.toContain("You did not stop");
    expect(text).toContain("Tyres 37 laps old at L62");
  });

  it("calls for a beginner: the plain words they heard, no experienced-only calls, the radio's words explained", () => {
    const t = timeline("edited-timeline-synthetic");
    const b = view(austria(), t, { level: "beginner" });
    const text = visible(b);
    expect(text).not.toContain("cover the undercut"); // meant for experienced drivers: never said to a beginner
    expect(text).toContain("Fuel is short. Lift off a little before each braking point, then brake as normal.");
    expect(text).toContain("Which ones you heard depends on the radio setting and the driver's level.");
    expect(b).toContain('data-call-terms=""');
    expect(b).toContain('aria-label="What is pit window?"');
    expect(b).toContain('aria-label="What is safety car and VSC?"');
    const advanced = visible(view(austria(), t, { level: "advanced" }));
    expect(advanced).toContain("Car behind is pitting. Box next lap to cover the undercut.");
  });

  it("phone: tables become two-line rows (ListView), no DataGrid", () => {
    const wide = view(austria(), timeline("edited-timeline-synthetic"));
    expect(wide).toContain('data-slot="data-grid"');
    const narrow = view(austria(), timeline("edited-timeline-synthetic"), { narrow: true });
    expect(narrow).not.toContain('data-slot="data-grid"');
    expect(narrow).toContain('data-narrow=""');
    expect(visible(narrow)).toContain("Wear 31% at the end · 3.4%/lap · median 1:31.700");
    expect(visible(narrow)).toContain("You in L8 · out L8"); // the stops list says which lap is which (review L13)
  });
});

describe("Session page: the Strategy tab is listed for races only", () => {
  function page(session: SessionDetail, tab: "summary" | "strategy"): string {
    setDrivers([]);
    cache.set(reviewKeys.session(session.id), session);
    cache.set(reviewKeys.analysis(session.id), fixtures.austriaAnalysis());
    const route = parseHash(`#/review/sessions/${session.id}${tab === "strategy" ? "/strategy" : ""}`, {});
    return renderToStaticMarkup(createElement(SessionPage, { id: session.id, tab, route }));
  }

  it("a race lists Strategy between Corners and Ask", () => {
    const html = page(austria(), "summary");
    expect(visible(html)).toMatch(/Summary Laps Compare Corners Strategy Ask/);
    // six tabs do not fit a 390 px phone: Ask leaves the strip there (the "Ask the engineer" button opens it)
    expect(html).toMatch(/max-sm:hidden[^>]*>Ask|data-key="ask"[^>]*max-sm:hidden/);
  });

  it("a practice session does not; a direct link still opens the tab with the reason", () => {
    const demo = fixtures.demo();
    expect(visible(page(demo, "summary"))).toMatch(/Summary Laps Compare Corners Ask/);
    const text = visible(page(demo, "strategy"));
    expect(text).toContain("Strategy is shown for races only.");
  });

  it("the race's tab reads the timeline from the cache key under the session prefix", () => {
    const s = austria();
    cache.set(strategyKeys.session(s.id), timeline("edited-timeline-austria"));
    const text = visible(page(s, "strategy")).replace(/ \? /g, " ");
    expect(text).toContain("Pit loss 18.9 s 1 measured");
  });
});
