// Session › Summary with "3 things from this session" (lane motivation, spec 9; design spec 6.3, 6.10), rendered to
// static markup in plain node from the recorded Austria session and analysis plus the edited recap fixtures (data
// put in the request cache first, nothing fetched). Checks: the card right after the tiles with the server's texts
// verbatim and their evidence, the links, the viewed driver's wording, SYNTHETIC / REPLAY on the header, the Work on
// list without the point the card shows ("More to work on"), a beginner's lists behind More detail, and an older
// server leaving the page as it was.
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../../lib/api";
import type { Driver } from "../../../lib/drivers";
import type { SessionRecap } from "../../../lib/endpoints/motivation";
import { densityFor } from "../../../lib/review/density";
import { driver, fixtures } from "../../../lib/review/testkit";
import { mfx } from "../../../lib/motivation/testkit";
import { stubBrowser } from "../../../test/fakes";
import type { SummaryTabProps } from "./SummaryTab";

function stubDom(): void {
  const { win } = stubBrowser("http://127.0.0.1:8825/#/review/sessions/332904dbe3de");
  Object.assign(win, {
    navigator: globalThis.navigator,
    removeEventListener: () => {},
    screen: { orientation: {} },
    visualViewport: {},
    matchMedia: () => ({ matches: true, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }),
  });
}

let SummaryTab: ComponentType<SummaryTabProps>;
let cache: typeof import("../../../lib/cache").cache;
let keys: typeof import("../../../lib/endpoints/motivation").motivationKeys;
let drivers: typeof import("../../../lib/drivers").drivers;

beforeAll(async () => {
  stubDom();
  SummaryTab = (await import("./SummaryTab")).SummaryTab;
  cache = (await import("../../../lib/cache")).cache;
  keys = (await import("../../../lib/endpoints/motivation")).motivationKeys;
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

const SID = "332904dbe3de";

function setDrivers(list: Driver[]): void {
  (drivers as unknown as { set(p: object): void }).set({ drivers: list, activeId: list[0]?.id ?? null, loaded: true });
}

function render(level: "beginner" | "intermediate" | "advanced", recap: SessionRecap | "missing" | "none"): { html: string; text: string } {
  const sam = driver(1, "Sam", level);
  setDrivers([sam]);
  const session = fixtures.austria();
  if (recap === "missing") {
    void cache.load(keys.recap(SID), () => Promise.reject(new ApiError(404, "Not Found"))).catch(() => {});
  } else if (recap !== "none") cache.set(keys.recap(SID), { ...recap, session_id: SID });
  const html = renderToStaticMarkup(
    createElement(SummaryTab, {
      session,
      analysis: fixtures.austriaAnalysis(),
      analysisError: null,
      density: densityFor(session.driver_id, [sam]),
      onOverride: () => {},
    }),
  );
  return { html, text: visible(html) };
}

const count = (s: string, sub: string) => s.split(sub).length - 1;

beforeEach(() => cache.clear());

describe("3 things from this session (Summary, after the tiles)", () => {
  it("the server's three items, verbatim, with evidence and links; then 'More to work on' without that point", async () => {
    await Promise.resolve();
    const { html, text } = render("advanced", mfx.recap());
    honest(text, "summary");
    expect(html).toContain('data-motivation="three-things"');
    expect(text).toContain("3 things from this session");
    // right after the KPI tiles, before the Work on list
    expect(text.indexOf("3 things from this session")).toBeLessThan(text.indexOf("More to work on"));
    expect(text).toContain("Went well New personal best at Austria in the Haas: 1:10.549 on lap 64, 1.196 s faster than before.");
    // the label says which question it answers (integration plan 5.1): this session, not the last lap or the radio's plan
    expect(text).toContain("One to work on (this session) Turn 6: minimum speed is 9 km/h lower than your reference (164 vs 173 km/h)");
    expect(text).toContain("Seen on 9 of 9 laps compared with your reference");
    expect(text).toContain("Progress Session 12 this week, 41 laps so far.");
    expect(text).toContain("See it on the lap");
    // the Work on list leaves out the point the card shows: Turn 6 appears once
    expect(text).toContain("More to work on");
    expect(count(text, "Turn 6: minimum speed is 9 km/h lower")).toBe(1);
    expect(text).toContain("Went well"); // the full positives list stays for an advanced driver
  });

  it("a goal reached: Goal reached with Open goals", () => {
    const { html, text } = render("intermediate", mfx.recapReached());
    expect(text).toContain("Goal reached A lap under 1:10.000 (1:09.981 on lap 7).");
    expect(text).toContain("Open goals");
    expect(html).toContain('data-thing="progress" data-source="goal_reached"');
  });

  it("a beginner: simple words, and the longer lists wait behind More detail", () => {
    const { text } = render("beginner", mfx.recap());
    honest(text, "beginner");
    expect(text).toContain("Turn 6: you were 9 km/h slower at the slowest point of the corner.");
    expect(text).toContain("Your fastest lap ever at Austria in the Haas: 1:10.549.");
    expect(text).not.toContain("One thing to work on"); // the list heading moved into More detail
    expect(text).not.toContain("More to work on");
    expect(text).toContain("More detail: more to work on, what went well, where the time is");
  });

  it("synthetic and replay sessions are labelled; their empty items say why", () => {
    const syn = render("intermediate", mfx.recapSynthetic());
    expect(syn.text).toContain("3 things from this session SYNTHETIC");
    expect(syn.text).toContain("Progress - Synthetic sessions do not count towards progress");
    const rep = render("intermediate", mfx.recapReplay());
    expect(rep.text).toContain("REPLAY");
    expect(rep.text).toContain("Went well - Nothing went well enough to stand out: no clean lap to compare");
    expect(rep.text).toContain("Replays are not anyone's driving");
    // no observation behind it: the Work on list is whole
    expect(rep.text).toContain("Work on");
    expect(rep.text).not.toContain("More to work on");
  });

  it("an older server (404): no card, the page as it was", async () => {
    cache.clear();
    const sam = driver(1, "Sam", "advanced");
    setDrivers([sam]);
    await cache.load(keys.recap(SID), () => Promise.reject(new ApiError(404, "Not Found"))).catch(() => {});
    const session = fixtures.austria();
    const text = visible(
      renderToStaticMarkup(
        createElement(SummaryTab, {
          session,
          analysis: fixtures.austriaAnalysis(),
          analysisError: null,
          density: densityFor(session.driver_id, [sam]),
          onOverride: () => {},
        }),
      ),
    );
    honest(text, "older server");
    expect(text).not.toContain("3 things");
    expect(text).not.toContain("could not be loaded");
    expect(text).toContain("Work on");
    expect(text).not.toContain("More to work on");
  });

  it("not loaded yet: a same-size skeleton", () => {
    const { html } = render("advanced", "none");
    expect(html).toContain('aria-label="Loading 3 things from this session"');
  });
});
