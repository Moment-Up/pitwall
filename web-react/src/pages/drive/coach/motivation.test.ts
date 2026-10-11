// Drive › Coach with goals and "3 things" (lane motivation, spec 9 Drive), server-rendered to static markup in plain
// node: the GOAL REACHED chip in the status slot on track, the Ready card's goal row (and the celebration between
// runs), the Session complete card's three things, its skeletons while they load and the old points when the server
// is older, and the badges. Plus the glanceability rules: no recap is asked for on track, nothing animates, the
// three things stay in the lazy chunk.
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { driveModel, type DriveModel } from "../../../lib/drive/model";
import { driver, fixture, lap, newestT, snap } from "../../../lib/drive/testkit";
import type { DriveMotivation } from "../../../lib/motivation/drive";
import { mfx } from "../../../lib/motivation/testkit";
import { stubBrowser } from "../../../test/fakes";
import type { CoachScreenProps } from "./CoachScreen";
import { recapWanted } from "./useRecap";

function stubDom(): void {
  const { win } = stubBrowser("http://127.0.0.1:8825/#/drive/coach");
  Object.assign(win, {
    navigator: globalThis.navigator,
    removeEventListener: () => {},
    screen: { orientation: {} },
    visualViewport: {},
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }),
  });
}

let CoachScreen: ComponentType<CoachScreenProps>;
let SessionCompleteCard: ComponentType<{ ended: NonNullable<DriveModel["ended"]>; tier: 1 | 2 }>;

beforeAll(async () => {
  stubDom();
  CoachScreen = (await import("./CoachScreen")).CoachScreen;
  SessionCompleteCard = (await import("./SessionCompleteCard")).SessionCompleteCard;
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
    .replace(/\s+/g, " ")
    .trim();
}

function honest(text: string, what: string): void {
  for (const bad of ["0:00.000", "--:--", "—", "NaN", "undefined", "null", "Infinity", "[object Object]"]) {
    expect(text, `${what}: ${bad}`).not.toContain(bad);
  }
}

const SAM = driver({ name: "Sam", skill: "intermediate" });

function model(name: string, motivation: DriveMotivation | null, d = SAM): DriveModel {
  const s = fixture(name);
  const sid = s.session_id as string;
  const fix = (m: DriveMotivation | null): DriveMotivation | null =>
    m && {
      ...m,
      note: m.note ? { ...m.note, session_id: sid } : null,
      recap: m.recap ? { ...m.recap, session_id: sid } : null,
    };
  return driveModel({ snap: s, connected: true, nowS: newestT(s) + 1, driver: d, motivation: fix(motivation) });
}

describe("on track: only the 6 s chip (P1, P2)", () => {
  it("GOAL REACHED sits in the status slot's chip position, success tone; the rest of the screen is unchanged", () => {
    const t = 1_791_669_000;
    const s = snap({ laps: [lap(6, 91_512)] });
    const with_ = driveModel({ snap: s, connected: true, nowS: t + 2, driver: SAM, motivation: { note: { ...mfx.note(), session_id: "s1", t }, recap: null, status: "off" } });
    const html = renderToStaticMarkup(createElement(CoachScreen, { model: with_ }));
    expect(html).toContain('data-kind="goal"');
    const slot = html.slice(html.indexOf("pwc-status"), html.indexOf('data-slot="segment"'));
    expect(visible(slot)).toContain("GOAL REACHED");
    const without = renderToStaticMarkup(createElement(CoachScreen, { model: driveModel({ snap: s, connected: true, nowS: t + 2, driver: SAM }) }));
    const body = (h: string) => h.slice(h.indexOf('data-slot="segment"'));
    expect(body(html)).toBe(body(without));
  });

  it("the recap is asked for only while the car is stopped (garage, session complete)", () => {
    for (const st of ["on_track", "pit_lane", "red_flag", "stale", "offline", "no_data"] as const) expect(recapWanted(st), st).toBe(false);
    expect(recapWanted("garage")).toBe(true);
    expect(recapWanted("ended")).toBe(true);
  });
});

describe("Ready card: one goal row (state 7)", () => {
  it("between runs, the goal in this scope with its bar and progress", () => {
    const m = model("edited-garage-between-runs", { note: null, recap: mfx.recap(), status: "ready" });
    const html = renderToStaticMarkup(createElement(CoachScreen, { model: m }));
    const text = visible(html);
    honest(text, "ready goal");
    expect(html).toContain('class="pwc-goal"');
    expect(text).toContain("Beat 1:10.000");
    expect(text).toContain("Austria · Haas");
    expect(text).toContain("0.301 s to go · best since you set it 1:10.301");
    expect(html).toContain('aria-label="Goal progress"');
    expect(html).toContain("data-goal"); // the column tightens its rows: same card size
    expect(text).toContain("Last run"); // the column keeps its content
  });

  it("a goal reached on the last run: Goal reached with the star, success tone", () => {
    const m = model("edited-garage-between-runs", { note: mfx.note(), recap: null, status: "loading" });
    const html = renderToStaticMarkup(createElement(CoachScreen, { model: m }));
    expect(html).toContain('class="pwc-goal" data-reached=""');
    expect(visible(html)).toContain("Goal reached · Beat 1:10.000");
    expect(visible(html)).toContain("Reached on lap 7");
  });

  it("before the first lap with no goal, or an older server: no row, the card as before", () => {
    for (const mot of [null, { note: null, recap: null, status: "error" } as DriveMotivation]) {
      const html = renderToStaticMarkup(createElement(CoachScreen, { model: model("recorded-d246-suzuka-grid-before-start", mot) }));
      expect(html).not.toContain("pwc-goal");
      expect(visible(html)).toContain("Sam is in the seat");
    }
  });
});

describe("Session complete card: 3 things (state 4)", () => {
  const ended = (mot: DriveMotivation | null) => model("recorded-d246-austria-session-ended", mot);
  const card = (m: DriveModel) => renderToStaticMarkup(createElement(SessionCompleteCard, { ended: m.ended!, tier: m.tier }));

  it("three ItemCards: went well, one to work on, goal reached (the celebration); up to 2 badges and +N more", () => {
    const html = card(ended({ note: null, recap: mfx.recapReached(), status: "ready" }));
    const text = visible(html);
    honest(text, "three things");
    expect(html).toContain('class="pwc-end__things"');
    expect((html.match(/data-thing=/g) ?? []).length).toBe(3);
    expect(text).toContain("Went well New personal best at Austria in the Haas: 1:10.549 on lap 64, 1.196 s faster than before.");
    expect(text).toContain("One to work on Turn 6: minimum speed is 9 km/h lower");
    expect(text).toContain("losing 0.23 s through the corner. Seen on 9 of 9 laps compared with your reference");
    expect(html).toContain('<span class="pwc-item__ev">Seen on 9 of 9 laps'); // up to two lines, never cut on one
    expect(text).toContain("Goal reached A lap under 1:10.000 (1:09.981 on lap 7).");
    expect(html).toMatch(/data-tone="success" data-thing="progress"/);
    expect(text).toContain("First time under 1:10 at Austria in the Haas");
    expect(text).toContain("First goal reached");
    expect(text).toContain("+1 more");
    expect(text).not.toContain("First time under 1:11 at Austria in the Haas");
    expect(text).toContain("Review this session");
    // the D6 points give way to the three things
    expect(text).not.toMatch(/Work on · T6/);
  });

  it("the seat changed since: whose session it was, and none of its badges for the seated driver", () => {
    const alex = { ...mfx.recapReached(), driver_id: 99, driver_name: "Alex" };
    const html = card(ended({ note: null, recap: alex, status: "ready" }));
    const text = visible(html);
    expect(html).toContain('<span class="pwc-end__owner">Alex&#x27;s session</span>');
    expect(text).not.toContain("First goal reached");
    expect(text).toContain("Goal reached A lap under 1:10.000"); // Alex's own things, under Alex's name
  });

  it("a beginner's recap in simple words; empty items are '-' with their reason", () => {
    const b = card(ended({ note: null, recap: mfx.recapBeginner(), status: "ready" }));
    expect(visible(b)).toContain("Turn 15 (130R): you were 25 km/h slower at the slowest point of the corner.");
    const syn = visible(card(ended({ note: null, recap: mfx.recapSynthetic(), status: "ready" })));
    expect(syn).toContain("Progress - Synthetic sessions do not count towards progress");
  });

  it("while it loads: three same-size skeletons; an older server: Work on / Went well as before", () => {
    const loading = card(ended({ note: null, recap: null, status: "loading" }));
    expect(loading).toContain('aria-label="Loading today&#x27;s 3 things"');
    expect((loading.match(/pwc-end__thing-skel/g) ?? []).length).toBe(3);
    const older = visible(card(ended({ note: null, recap: null, status: "error" })));
    expect(older).toContain("Work on");
    expect(older).toContain("Went well");
    expect(older).not.toContain("One to work on");
    const none = visible(card(ended(null)));
    expect(none).toContain("Went well");
  });
});

describe("glanceability and chunks (spec 4.9, 4.11; lane spec 9)", () => {
  const SOURCES = Object.entries(
    import.meta.glob<string>(["../../../**/*.ts", "../../../**/*.tsx", "!../../../**/*.test.ts"], { query: "?raw", import: "default", eager: true }),
  );
  const fs = (
    globalThis as unknown as { process: { getBuiltinModule(id: "node:fs"): { readFileSync(p: URL, enc: "utf8"): string } } }
  ).process.getBuiltinModule("node:fs");
  const CSS = fs.readFileSync(new URL("./coach.css", import.meta.url), "utf8");

  it("the three things are only in the lazy Session complete chunk", () => {
    for (const [f, src] of SOURCES) {
      if (/from\s+["']\.\/ThingsRow["']/.test(src)) expect(f.endsWith("SessionCompleteCard.tsx"), f).toBe(true);
    }
  });

  it("only the Drive model hook asks for the recap (no REST from a panel)", () => {
    const users = SOURCES.filter(([, src]) => /useRecap\(/.test(src)).map(([f]) => f);
    expect(users.filter((f) => !f.endsWith("useRecap.ts"))).toEqual([expect.stringMatching(/hooks\/useDriveModel\.ts$/)]);
  });

  it("nothing celebrates by moving: the goal bar has no transition, no animation in the new rules", () => {
    expect(CSS).toMatch(/\.pwc-goal__bar \.progress-bar__fill \{[^}]*transition: none/);
    const motivationCss = CSS.slice(CSS.indexOf("lane motivation: goals"), CSS.indexOf(".pwc-nodata.card"));
    expect(motivationCss.length).toBeGreaterThan(100);
    expect(motivationCss).not.toMatch(/animation|@keyframes|transition:(?!\s*none)/);
  });

  it("iPad mini compact rows: the goal row is one line shorter, so the Ready card keeps its size", () => {
    const compact = CSS.slice(CSS.indexOf("iPad mini, Safari with toolbars (compact rows, 4.2): the progress words"));
    expect(compact).toMatch(/\.pwc-goal__scope \{ display: none; \}/);
    expect(compact).toMatch(/\.pwc-goal__text \{ grid-row: 1; grid-column: 2;/);
  });

  it("phone portrait (5.4): the three things stack, badges wrap", () => {
    const phone = CSS.slice(CSS.indexOf("@media (max-width: 767px) {"));
    expect(phone).toMatch(/\.pwc-end__things \{ grid-template-columns: minmax\(0, 1fr\)/);
    expect(phone).toMatch(/\.pwc-end__actions \{ flex-wrap: wrap/);
  });
});
