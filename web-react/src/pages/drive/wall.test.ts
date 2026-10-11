// Drive › Car, Track and Radio rendered from every Drive fixture (server-rendered to static markup in plain node,
// like coach.test.ts): the status slot is the Coach one, unknown values are "-", nothing is invented, the evidence
// tiers stay visible, purple never appears without D2 records, and the Radio stage follows the radio store.
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { driveModel, type DriveModel } from "../../lib/drive/model";
import { FIXTURES, fixture, newestT } from "../../lib/drive/testkit";
import type { SnapshotNext } from "../../lib/drive/types";
import type { HistoryPoint } from "../../lib/live";
import type { RadioState } from "../../lib/radio";
import { stubBrowser } from "../../test/fakes";
import type { CarScreenProps } from "./car/CarScreen";
import type { RadioScreenProps } from "./radio/RadioScreen";
import type { TrackScreenProps } from "./track/TrackScreen";
import { trackView } from "./track/view";

function stubDom(): void {
  const { win } = stubBrowser("http://127.0.0.1:8770/next/#/drive/car");
  Object.assign(win, {
    navigator: globalThis.navigator,
    removeEventListener: () => {},
    screen: { orientation: {} },
    visualViewport: {},
    matchMedia: () => ({
      matches: false,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
    }),
  });
}

let CarScreen: ComponentType<CarScreenProps>;
let TrackScreen: ComponentType<TrackScreenProps>;
let RadioScreen: ComponentType<RadioScreenProps>;
let setRadio: (patch: Partial<RadioState>) => void;
let initialRadio: RadioState;

beforeAll(async () => {
  stubDom();
  CarScreen = (await import("./car/CarScreen")).CarScreen;
  TrackScreen = (await import("./track/TrackScreen")).TrackScreen;
  RadioScreen = (await import("./radio/RadioScreen")).RadioScreen;
  const { radio } = await import("../../lib/radio");
  initialRadio = radio.get();
  // Store.set is protected: the test drives the store's state directly, as its socket and mic would.
  setRadio = (patch) => (radio as unknown as { set(p: Partial<RadioState>): void }).set(patch);
  vi.unstubAllGlobals();
});

afterEach(() => setRadio?.(initialRadio));

function model(s: SnapshotNext | null, connected = true): DriveModel {
  return driveModel({ snap: s, connected, nowS: newestT(s) + 1, driver: null });
}

const HISTORY: HistoryPoint[] = Array.from({ length: 40 }, (_, i) => ({ t: i * 0.05, speed: 200 + i, throttle: 1, brake: 0 }));

function car(name: string, connected = true): string {
  const s = fixture(name);
  return renderToStaticMarkup(
    createElement(CarScreen, { model: model(s, connected), snap: connected ? s : { ...s, frame: null }, history: HISTORY, nowS: newestT(s) + 1 }),
  );
}

function track(name: string, connected = true, selected: string | null = null): string {
  const s = fixture(name);
  const m = model(s, connected);
  return renderToStaticMarkup(
    createElement(TrackScreen, { model: m, snap: s, view: trackView(s, m, false), selected, onSelect: () => {} }),
  );
}

function radioPage(name = "recorded-d246-suzuka-on-track-brake-ahead"): string {
  const s = fixture(name);
  return renderToStaticMarkup(createElement(RadioScreen, { model: model(s), liveCueMode: s.cues?.mode ?? null }));
}

/** Text a sighted user sees: tags stripped, visually hidden spans removed, entities decoded. */
function visible(markup: string): string {
  return markup
    .replace(/<span class="sr-only">[^<]*<\/span>/g, "")
    .replace(/<h3 class="sr-only">[^<]*<\/h3>/g, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/\s+/g, " ")
    .trim();
}

function slot(markup: string): string {
  const start = markup.indexOf("pww-status");
  return markup.slice(start, markup.indexOf('data-slot="segment"', start));
}

/** The evidence tier is in the slot: as words, or as the icon chip whose label carries them. */
function evidenceShown(markup: string, word: "SYNTHETIC" | "REPLAY"): boolean {
  return visible(markup).includes(word) || markup.includes(`aria-label="${word}:`);
}

const BANNED = ["0:00.000", "--:--", "—", "NaN", "undefined", "null", "Infinity", "[object Object]"];

describe("every fixture renders honestly", () => {
  it.each(FIXTURES)("%s: Car, Track and Radio (connected and offline)", (name) => {
    for (const connected of [true, false]) {
      const m = model(fixture(name), connected);
      for (const [page, html] of [
        ["car", car(name, connected)],
        ["track", track(name, connected)],
        ["radio", radioPage(name)],
      ] as const) {
        const text = visible(html);
        for (const bad of BANNED) expect(text, `${name} ${page} ${connected ? "connected" : "offline"}: ${bad}`).not.toContain(bad);
        expect(html, `${name} ${page}`).toContain("pww-status"); // the Coach status slot on every Drive page
        if (page !== "radio") {
          // in words on the normal line; on a band (offline here) as its icon, the words in its label (plan 2.3)
          if (m.status.evidence.synthetic) expect(evidenceShown(slot(html), "SYNTHETIC"), `${name} ${page}`).toBe(true);
          if (m.status.evidence.replay) expect(evidenceShown(slot(html), "REPLAY"), `${name} ${page}`).toBe(true);
        }
      }
    }
  });

  it("purple and PB never appear without D2 (4.6)", () => {
    for (const name of FIXTURES) {
      if (model(fixture(name)).tier === 2) continue; // the legend names REC and PB once D2 is there
      const html = car(name) + track(name);
      expect(html, name).not.toContain('data-status="rec"');
      expect(html, name).not.toContain('data-status="pb"');
    }
  });
});

describe("Drive › Car (5.1)", () => {
  it("the six tiles of the pit wall", () => {
    const html = car("recorded-d246-suzuka-on-track-brake-ahead");
    const text = visible(html);
    for (const t of ["Car", "Track", "Tyres & energy", "Inputs · last 12 s", "Laps", "Coaching · lap 4"]) expect(text).toContain(t);
    expect(html).toContain('data-layout="car"');
    expect(text).toMatch(/122 km\/h 3 gear/);
    expect(text).toContain("RPM");
    expect(text).toContain("Steering 0.48");
    expect(text).toContain("Bias 58%");
    expect(text).toContain("FL 89° 12% · 24.3 psi");
    expect(text).toContain("FR cold 69°");
    expect(text).toContain("Fuel 5.8 kg");
    expect(text).toContain("current standing · ref L3");
    expect(text).toContain("SB your best today"); // the legend on every timing surface
    expect(text).toContain("T9: 12 km/h slower mid-corner"); // the radio's first pick, D6's glance text, verbatim
    expect(html).toContain("data-car"); // the car on the map
    expect(html).toContain("<canvas"); // the live inputs trace
  });

  it("the laps table marks the reference and the reasons laps were not clean", () => {
    const text = visible(car("recorded-d246-suzuka-on-track-brake-ahead"));
    expect(text).toMatch(/3 R /);
    expect(text).toContain("reset to track, flashback, standing start");
    expect(text).toContain("INV");
  });

  it("stale: tiles dimmed, live values '-', no car on the map", () => {
    const html = car("recorded-austria-stale");
    expect(html).toMatch(/class="pww[^"]*" data-layout="car" data-state="stale" data-dim=""/);
    expect(visible(slot(html))).toContain("No signal");
    expect(html).not.toContain("data-car");
    expect(visible(html)).toMatch(/- km\/h - gear/);
  });

  it("offline: the outline band and '-' for every car value", () => {
    const html = car("recorded-d246-suzuka-on-track-brake-ahead", false);
    expect(visible(slot(html))).toContain("Offline");
    expect(visible(html)).toContain("Telemetry -");
    expect(html).not.toContain("data-car");
  });

  it("no telemetry: empty tiles say why, the map says the track is being learned", () => {
    const text = visible(car("pipeline-no-data"));
    expect(text).toContain("Waiting for telemetry");
    expect(text).toContain("No completed laps yet");
    expect(text).toContain("Learning the track");
  });

  it("flags speak in the same slot as on Coach", () => {
    expect(visible(slot(car("edited-red-flag")))).toContain("RED FLAG");
    expect(car("edited-red-flag")).toContain('role="alert"');
    expect(visible(slot(car("edited-pit-lane")))).toContain("PIT LANE");
    expect(visible(slot(car("recorded-suzuka-yellow-flag")))).toMatch(/YELLOW FLAG/);
  });
});

describe("Drive › Track (5.2)", () => {
  it("the large map and every corner with what the coach said on the last lap", () => {
    const s = fixture("recorded-d246-suzuka-on-track-brake-ahead");
    const html = track("recorded-d246-suzuka-on-track-brake-ahead");
    const text = visible(html);
    expect(text).toContain("T3-5 S Curve");
    expect(text).toContain("FOCUS");
    expect(text).toContain("Next");
    expect(text).toContain(s.coach!.by_corner.T7!.text);
    expect(text).toContain("Following the car");
    expect(html).toContain("data-car");
  });

  it("a picked corner shows on the map, with See it on the lap and Follow the car", () => {
    const text = visible(track("recorded-d246-suzuka-on-track-brake-ahead", true, "T7"));
    expect(text).toContain("Showing T11");
    expect(text).toContain("Follow the car");
    expect(text).toContain("See it on the lap");
  });

  it("no model: says when the corners appear", () => {
    expect(visible(track("recorded-suzuka-grid-before-start"))).toContain("The corners appear after your first clean lap.");
  });
});

describe("Drive › Radio (5.3)", () => {
  it("radio off: Go live with what it starts, the calls in force, read only", () => {
    const text = visible(radioPage());
    expect(text).toContain("Go live");
    expect(text).toContain("Starts the radio");
    expect(text).toContain("Radio is off.");
    expect(text).not.toContain("Link"); // no link chip while the radio is off
    expect(text).toMatch(/Braking calls Off Focus Markers All/);
    expect(text).toMatch(/Coaching Quiet Normal Detailed/);
    expect(text).toContain("Go live to change the braking calls");
    expect(text).toContain("Radio log");
    expect(text).toContain("Transcripts and engineer messages appear here, newest first.");
    expect(text).not.toContain("End radio");
  });

  it("live: the 160 px Hold to talk, the message, the log newest first, End radio", () => {
    const now = Date.now();
    setRadio({
      phase: "live",
      micCapable: true,
      conn: "open",
      mic: "live",
      rttMs: 21,
      audio: "running",
      server: {
        ptt: false,
        listening: false,
        speaking: false,
        intensity: "normal",
        stt: "parakeet",
        tts: "kokoro",
        telemetry: "live",
        ptt_source: null,
        cue_mode: "all",
      },
      current: { id: "m2", kind: "answer", text: "Fronts 92 and 95, all in the window.", at: now - 8000, audioS: 2 },
      log: [
        { seq: 1, at: now - 120_000, kind: "lap_summary", text: "Lap 6: 1:31.512.", meta: "", id: "m1", count: 1 },
        { seq: 2, at: now - 8000, kind: "answer", text: "Fronts 92 and 95, all in the window.", meta: "", id: "m2", count: 1 },
      ],
    });
    const html = radioPage();
    const text = visible(html);
    expect(text).toContain("Link · 21 ms");
    expect(text).toContain("Mic live");
    expect(text).toContain("ENGINEER Fronts 92 and 95, all in the window.");
    expect(html).toContain("size-40"); // the 160 px round button
    expect(text).toContain("Hold to talk");
    expect(text).toContain("Radio check");
    expect(text).toContain("End radio");
    expect(text).toContain("Braking calls apply to every radio in the house.");
    // newest first
    expect(text.indexOf("Fronts 92")).toBeLessThan(text.lastIndexOf("Lap 6: 1:31.512."));
    expect(text.lastIndexOf("Fronts 92")).toBeLessThan(text.lastIndexOf("Lap 6: 1:31.512."));
  });
});
