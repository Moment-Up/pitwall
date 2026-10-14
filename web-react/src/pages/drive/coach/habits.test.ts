// Drive › Coach with habits (habits spec 7), server-rendered to static markup in plain node: the coach card's one chip
// says what kind of note it is, a focus corner without a note shows its reminder, and the Ready card's "Working on"
// takes the Last lap point's place between runs. Coach blocks are built in coach/selection.py's shape (synthetic
// values on recorded fixtures: never game evidence).
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { driveModel } from "../../../lib/drive/model";
import { driver, fixture, newestT } from "../../../lib/drive/testkit";
import type { CoachBlock, FocusEntry, ObservationNext, SnapshotNext } from "../../../lib/drive/types";
import { stubBrowser } from "../../../test/fakes";
import type { CoachScreenProps } from "./CoachScreen";

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

beforeAll(async () => {
  stubDom();
  CoachScreen = (await import("./CoachScreen")).CoachScreen;
  vi.unstubAllGlobals();
});

function visible(markup: string): string {
  return markup
    .replace(/<span class="sr-only">[^<]*<\/span>/g, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ")
    .trim();
}

function render(s: SnapshotNext): { html: string; text: string } {
  const model = driveModel({ snap: s, connected: true, nowS: newestT(s) + 1, driver: driver({ name: "Sam" }) });
  const html = renderToStaticMarkup(createElement(CoachScreen, { model }));
  return { html, text: visible(html) };
}

function focusEntry(over: Partial<FocusEntry> = {}): FocusEntry {
  return {
    corner: "T6",
    corner_label: "T9",
    corner_voice: "Turn 9",
    kind: "low_min_speed",
    status: "focus",
    laps_seen: 3,
    laps: 4,
    value: -12,
    unit: "km/h",
    impact_s: 0.3,
    since_lap: 3,
    short: "T9: 12 km/h slower mid-corner",
    reminder: { parts: ["Turn 9", "apex speed, 12 down"], text: "T9: apex speed, 12 down" },
    ...over,
  };
}

/** The fixture with a coach block: `points` per corner, `focus` the habits being worked on. */
function withCoach(name: string, points: ObservationNext[], focus: FocusEntry[] = []): SnapshotNext {
  const s = fixture(name);
  const coach: CoachBlock = {
    lap_number: s.laps[0]?.lap_number ?? 1,
    picked: points.filter((o) => o.picked),
    by_corner: Object.fromEntries(points.map((o) => [o.corner, o])),
    habits: focus,
    focus,
  };
  s.coach = coach;
  return s;
}

describe("the coach card's chip", () => {
  const ahead = fixture("recorded-d246-suzuka-on-track-brake-ahead");
  const base = ahead.coach!.by_corner.T7!;

  it("a habit says its counts; a one-off says Once; one chip, the glance text beside it", () => {
    const habit = withCoach("recorded-d246-suzuka-on-track-brake-ahead", [
      { ...base, habit: { status: "seen", laps_seen: 3, laps: 4 }, one_off: false },
    ]);
    const { html, text } = render(habit);
    expect(text).toContain(`Habit · 3 of 4 laps ${base.short}`);
    expect(html).toContain('data-habit="habit"');
    expect((html.match(/pwc-coach__tag/g) ?? []).length).toBe(1);
    const once = render(withCoach("recorded-d246-suzuka-on-track-brake-ahead", [{ ...base, habit: null, one_off: true }]));
    expect(once.text).toContain(`Once · last lap ${base.short}`);
  });

  it("the focus corner's note, and its reminder when the last lap had none there", () => {
    const own = render(
      withCoach("recorded-d246-suzuka-on-track-brake-ahead", [{ ...base, habit: { status: "focus", laps_seen: 4, laps: 5 } }]),
    );
    expect(own.text).toContain(`Focus · last lap ${base.short}`);
    expect(own.html).toContain('data-habit="focus"');
    const reminder = render(
      withCoach("recorded-d246-suzuka-on-track-brake-ahead", [], [focusEntry({ corner: "T7", corner_label: "T11", reminder: { parts: ["Turn 11", "apex speed, 12 down"], text: "T11: apex speed, 12 down" } })]),
    );
    expect(reminder.text).toContain("Focus T11: apex speed, 12 down");
    expect(reminder.text).not.toContain("No note for");
  });
});

describe("the Ready card between runs", () => {
  it("Working on: the habits the radio is working on, in place of the Last lap point", () => {
    const { html, text } = render(withCoach("edited-garage-between-runs", [], [focusEntry()]));
    expect(html).toContain("data-working-on");
    expect(text).toContain("Working on: T9 apex speed, 12 down · 3 of 4 laps");
    expect(text).not.toContain("Last lap:");
    expect(text).toContain("Radio calls: T11"); // the braking calls stay
  });

  it("two habits: two rows under one label", () => {
    const two = [focusEntry(), focusEntry({ corner: "T3", corner_label: "T6", kind: "brake_early", reminder: null, laps_seen: 4, laps: 5 })];
    const { text } = render(withCoach("edited-garage-between-runs", [], two));
    expect(text).toContain("Working on: T9 apex speed, 12 down · 3 of 4 laps T6 braking point · 4 of 5 laps");
  });

  it("nothing being worked on: the Last lap point with its kind", () => {
    const once = { ...fixture("edited-garage-between-runs").observations[0]!, picked: true, one_off: true, habit: null };
    const { html, text } = render(withCoach("edited-garage-between-runs", [once]));
    expect(html).not.toContain("data-working-on");
    expect(text).toContain("Last lap: Once ");
  });
});
