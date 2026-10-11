// Drive › Coach with coachref (spec 10.1-10.4), server-rendered to static markup in plain node like coach.test.ts:
// the delta reference control, the fallback reason, the drill chip and the hero's DRILL chip, the coach card during a
// drill, the Ready card's reference control and Drill block (start, running, result), the picker and drill settings
// with their reasons, a server without coachref (unchanged), beginners' words and the phone layout.
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { crFixture, withLive } from "../../../test/coachref";
import { cache } from "../../../lib/cache";
import { coachrefKeys, type DrillOptionsResponse, type DrillView, type RefOptionsResponse } from "../../../lib/endpoints/coachref";
import { driveModel, type DriveModel } from "../../../lib/drive/model";
import { driver, fixture, newestT } from "../../../lib/drive/testkit";
import type { SnapshotNext } from "../../../lib/drive/types";
import { stubBrowser } from "../../../test/fakes";
import type { CoachScreenProps } from "./CoachScreen";

const PHONE_QUERY = "(max-width: 767px)";

function stubDom(phone = false): void {
  const { win } = stubBrowser("http://127.0.0.1:8810/#/drive/coach");
  const mm = (q: string) => ({
    matches: phone && q.includes(PHONE_QUERY),
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
  });
  Object.assign(win, { navigator: globalThis.navigator, removeEventListener: () => {}, screen: { orientation: {} }, visualViewport: {}, matchMedia: mm });
  vi.stubGlobal("matchMedia", mm);
}

let CoachScreen: ComponentType<CoachScreenProps>;
let RefPickerBody: ComponentType<{ driverId: number | null; trackName: string | null; onClose: () => void }>;
let DrillSettings: ComponentType<{ opts: DrillOptionsResponse; beginner: boolean; onStarted: () => void }>;

beforeAll(async () => {
  stubDom();
  CoachScreen = (await import("./CoachScreen")).CoachScreen;
  RefPickerBody = (await import("./RefPickerBody")).RefPickerBody;
  DrillSettings = (await import("./DrillSheet")).DrillSettings;
  vi.unstubAllGlobals();
});

afterEach(() => {
  vi.unstubAllGlobals();
  cache.clear();
});

const ON_TRACK = "recorded-d246-suzuka-on-track-brake-ahead";
const BETWEEN = "edited-garage-between-runs";
const BEFORE = "recorded-d246-suzuka-grid-before-start";

function model(s: SnapshotNext, opts: { beginner?: boolean } = {}): DriveModel {
  const d = driver({ id: 1, name: "James", skill: opts.beginner ? "beginner" : "advanced" });
  return driveModel({ snap: s, connected: true, nowS: newestT(s) + 1, driver: d });
}

function render(m: DriveModel, phone = false): string {
  if (phone) stubDom(true);
  return renderToStaticMarkup(createElement(CoachScreen, { model: m }));
}

function visible(markup: string): string {
  return markup
    .replace(/<span class="sr-only">[^<]*<\/span>/g, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/\s+/g, " ")
    .trim();
}

function slot(markup: string): string {
  const start = markup.indexOf("pwc-status");
  return markup.slice(start, markup.indexOf('data-slot="segment"', start));
}

/** The delta panel's label row (from the card to the number). */
function deltaCard(markup: string): string {
  const start = markup.search(/pwc-delta["\s]/);
  return start < 0 ? "" : markup.slice(start, markup.indexOf('class="pwc-dv"', start));
}

const BAD = ["undefined", "null", "NaN", "[object Object]", "—"];

describe("the delta reference control (spec 10.1)", () => {
  it("a server without coachref: the plain label, no control (nothing changes)", () => {
    const html = render(model(fixture(ON_TRACK)));
    expect(visible(deltaCard(html))).toContain("Delta to reference");
    expect(html).not.toContain("pwc-refctl");
  });

  it("another driver's best: 'Delta to · Sam's best', a 56 px control, the chip with their initials", () => {
    const html = render(model(withLive(fixture(ON_TRACK), "live-sam")));
    const top = deltaCard(html);
    expect(visible(top)).toMatch(/^.*Delta to · Sam's best .*SA Lap 3 · 1:30\.412 · /);
    expect(top).toContain("pwc-refctl");
    expect(top).toContain('aria-label="Delta to · Sam&#x27;s best, change the reference when stopped"');
    for (const bad of BAD) expect(visible(html)).not.toContain(bad);
  });

  it("a choice that could not be used: one muted line saying why, and that your best is used", () => {
    const top = visible(deltaCard(render(model(withLive(fixture(ON_TRACK), "live-fallback")))));
    expect(top).toContain("Delta to · Your best");
    expect(top).toContain("Jo's laps here used a different braking assist: using your best");
  });

  it("held for a drill / waiting for the next lap is said after the chip", () => {
    expect(visible(deltaCard(render(model(withLive(fixture(ON_TRACK), "live-drill")))))).toContain("Held for the drill");
    const s = withLive(fixture(ON_TRACK), "live-sam");
    s.coachref!.pending = true;
    expect(visible(deltaCard(render(model(s))))).toContain("From next lap");
  });

  it("synthetic data never uses another driver's lap: the reason says so and SYNTHETIC stays visible", () => {
    const s = withLive(fixture("synthetic-demo-on-track-brake-ahead"), "live-own");
    s.coachref!.choice = crFixture<{ coachref: { choice: NonNullable<SnapshotNext["coachref"]>["choice"] } }>("live-sam").coachref.choice;
    s.coachref!.reason = "replays and synthetic sessions use their own laps";
    const html = render(model(s));
    expect(visible(deltaCard(html))).toContain("Replays and synthetic sessions use their own laps: using your best");
    expect(visible(slot(html))).toContain("SYNTHETIC");
  });

  it("beginners: 'vs Sam's best lap'", () => {
    expect(visible(deltaCard(render(model(withLive(fixture(ON_TRACK), "live-sam"), { beginner: true }))))).toContain("vs Sam's best lap");
  });
});

describe("drills while driving (spec 10.3)", () => {
  it("the status slot carries DRILL · T11 · 2/5 · 1 ✓; the hero wears DRILL instead of FOCUS; the coach card shows the drill point", () => {
    const html = render(model(withLive(fixture(ON_TRACK), "live-drill")));
    expect(visible(slot(html))).toContain("DRILL · T11 · 2/5 · 1 ✓");
    expect(slot(html)).toContain('aria-label="Brake point drill at T11: 2 of 5 laps done, 1 hit"');
    const hero = html.slice(html.indexOf("pwc-hero"), html.indexOf("pwc-coach"));
    expect(visible(hero)).toContain("DRILL");
    expect(visible(hero)).not.toContain("FOCUS");
    const coach = html.slice(html.indexOf("pwc-coach"), html.indexOf("pwc-delta"));
    expect(visible(coach)).toContain("Drill · 2/5 Drill 2/5: 11 m past the point · 1 hit");
  });

  it("a band (pit lane, flags) hides the drill chip with the rest of the left part", () => {
    const s = withLive(fixture("edited-pit-lane"), "live-drill");
    expect(visible(slot(render(model(s))))).not.toContain("DRILL");
  });

  it("an incident chip takes the drill chip's place for its 6 s", () => {
    const s = withLive(fixture("edited-penalty-player"), "live-drill");
    const text = visible(slot(render(model(s))));
    expect(text).toContain("PENALTY");
    expect(text).not.toContain("DRILL ·");
  });

  it("phone: the same chip and control, smaller (CSS caps the chip at 180 px there)", () => {
    const html = render(model(withLive(fixture(ON_TRACK), "live-drill")), true);
    expect(visible(slot(html))).toContain("DRILL · T11 · 2/5 · 1 ✓");
    expect(html).toContain("pwc-refctl");
  });
});

describe("the Ready card (spec 10.2)", () => {
  it("before the first lap: the reference control on top of Target with the braking note; Choose a corner…", () => {
    const html = render(model(withLive(fixture(BEFORE), "live-sam")));
    const text = visible(html);
    expect(text).toMatch(/Target Delta reference Sam's best/);
    expect(html).toContain("pwc-refctl pwc-refctl--ready");
    expect(text).toContain("Braking calls use your own braking points where Sam brakes later");
    expect(text).toContain("Choose a corner…");
    for (const bad of BAD) expect(text).not.toContain(bad);
  });

  it("between runs: the last lap's point as a drill button under 'One thing for the next run'", () => {
    const s = withLive(fixture(BETWEEN), "live-own");
    const text = visible(render(model(s)));
    expect(text).toContain("One thing for the next run");
    expect(text).toContain("Drill T9 · Minimum speed");
    expect(text).toContain("Choose a corner…");
    expect(text).toMatch(/Last run .*Delta reference Your best/);
  });

  it("a drill running: the Drill column with the line, target, note and Stop drill; no focus rows", () => {
    const text = visible(render(model(withLive(fixture(BETWEEN), "live-drill"))));
    expect(text).toContain("Drill Drill · T11 · Brake point · 2 of 5 done · 1 hit");
    expect(text).toContain("Brake within 5 m of Sam's braking point");
    expect(text).toContain("Braking assist is on");
    expect(text).toContain("Stop drill");
    expect(text).not.toContain("FOCUS");
  });

  it("just ended: Drill result with hits, best, trend, a dot a lap, Again and Done", () => {
    const s = withLive(fixture(BETWEEN), "live-drill");
    s.coachref!.drill = crFixture<DrillView>("drill-completed");
    const html = render(model(s));
    const text = visible(html);
    expect(text).toContain("Drill result T11 · Brake point Closer 3 of 4 on the point best 1 m from the point");
    expect(text).toContain("vs Sam's best");
    expect(text).toMatch(/Again Done/);
    expect(html.match(/class="pwc-dot"/g)).toHaveLength(5);
    expect(html).toContain('data-outcome="unmeasured" aria-label="Lap 4 of 5: not measured, no braking measured"');
  });

  it("a server without coachref: today's Ready card (no control, no drill)", () => {
    const text = visible(render(model(fixture(BETWEEN))));
    expect(text).toContain("Delta reference");
    expect(text).not.toContain("Choose a corner…");
  });
});

describe("the picker and the drill settings (overlay content)", () => {
  function renderPicker(name: string): string {
    stubDom();
    cache.set(coachrefKeys.options(1), crFixture<RefOptionsResponse>(name));
    return renderToStaticMarkup(createElement(RefPickerBody, { driverId: 1, trackName: "Suzuka", onClose: () => {} }));
  }

  it("rows of 56 px: your best, the family record, each driver (unavailable ones disabled with the reason), saved laps, Only at", () => {
    const html = renderPicker("options-suzuka-sam");
    const text = visible(html);
    expect(text).toMatch(/Your best 1:30\.986 · .*Family record 1:30\.412 · Sam .*Jo's best Jo's laps here used a different braking assist .*Sam's best 1:30\.412/);
    expect(text).toContain("A saved lap…");
    expect(text).toContain("Only at Suzuka");
    expect(text).toContain("Different tyre compound (soft vs medium)");
    expect(html).toMatch(/aria-disabled="true"[^>]*data-key="driver_best:3"|data-key="driver_best:3"[^>]*aria-disabled="true"/);
  });

  it("a game whose car is unknown: other drivers' laps listed with why they cannot be used", () => {
    const text = visible(renderPicker("options-gt7-unknown-car"));
    expect(text.match(/the car is unknown, so other drivers' laps can't be matched/g)).toHaveLength(2);
  });

  it("drill settings: skill, the server's target and note, laps, window; unavailable kinds with their reason", () => {
    stubDom();
    const html = renderToStaticMarkup(
      createElement(DrillSettings, { opts: crFixture<DrillOptionsResponse>("drill-options-t11"), beginner: false, onStarted: () => {} }),
    );
    const text = visible(html);
    expect(text).toContain("Brake within 5 m of Sam's braking point");
    expect(text).toContain("Minimum speed: You already match the best minimum speed here (71 km/h).");
    expect(text).toMatch(/Laps 3 5 8 10/);
    expect(text).toMatch(/Window ±3 m ±5 m ±10 m/);
    expect(text).toContain("Start drill");
  });

  it("beginners get the default window (no tolerance choice)", () => {
    stubDom();
    const text = visible(
      renderToStaticMarkup(
        createElement(DrillSettings, { opts: crFixture<DrillOptionsResponse>("drill-options-t11"), beginner: true, onStarted: () => {} }),
      ),
    );
    expect(text).not.toContain("Window");
    expect(text).toContain("Start drill");
  });

  it("a track still being learned, or synthetic data: the server's sentence, nothing to start", () => {
    stubDom();
    for (const [name, words] of [
      ["drill-options-learning", "Pitwall is still learning this track: drive 3 clean laps first."],
      ["drill-options-synthetic", "Drills run on your own live driving."],
    ] as const) {
      const text = visible(
        renderToStaticMarkup(createElement(DrillSettings, { opts: crFixture<DrillOptionsResponse>(name), beginner: false, onStarted: () => {} })),
      );
      expect(text, name).toBe(words);
    }
  });
});

describe("coach.css: the coachref rules keep Drive's sizes", () => {
  const fs = (
    globalThis as unknown as { process: { getBuiltinModule(id: "node:fs"): { readFileSync(p: URL, enc: "utf8"): string } } }
  ).process.getBuiltinModule("node:fs");
  const CSS = fs.readFileSync(new URL("./coach.css", import.meta.url), "utf8");
  const rule = (sel: string): string => {
    const esc = sel.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp(`(?:^|\\n)${esc} \\{([^}]*)\\}`).exec(CSS)?.[1] ?? "";
  };

  it("the control is a Drive action (56 px; 64 px on the Ready card) and its words ellipsize", () => {
    expect(rule(".pwc-refctl")).toMatch(/min-height:\s*var\(--pw-touch-drive,\s*56px\)/);
    expect(rule(".pwc-refctl--ready")).toMatch(/min-height:\s*var\(--pw-touch-glove,\s*64px\)/);
    expect(rule(".pwc-refctl__text")).toMatch(/text-overflow:\s*ellipsis/);
    expect(rule(".pwc-refreason")).toMatch(/text-overflow:\s*ellipsis/);
  });

  it("the drill chip is fixed (never wraps the slot) and at most 220 px, 22 px / 600", () => {
    const chip = rule(".pwc-drillchip");
    expect(chip).toMatch(/flex:\s*none/);
    expect(chip).toMatch(/max-width:\s*220px/);
    expect(chip).toMatch(/font:\s*600 22px/);
  });
});
