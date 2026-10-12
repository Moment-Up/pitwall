// Drive › Car with race radio (pitwall.raceradio; race-radio spec 10.2, 10.5): the race-control line gives the newest
// race-control call's reason, the position's evidence note sits under it (GT7, Forza), and the status slot shows P for
// GT7. Static markup in plain node, like wall.test.ts.

import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { driveModel } from "../../../lib/drive/model";
import { fixture, newestT } from "../../../lib/drive/testkit";
import type { LiveEvent, SnapshotNext } from "../../../lib/drive/types";
import { raceView, withRace } from "../../../lib/raceradio/testkit";
import { stubBrowser } from "../../../test/fakes";
import type { CarScreenProps } from "./CarScreen";
import { raceControlLine, raceNote } from "./view";

const ev = (kind: string, code: string | null, t: number, player?: boolean): LiveEvent => ({
  kind,
  code,
  session_time_s: null,
  t,
  ...(player === undefined ? {} : { player }),
});

describe("race-control line with race radio", () => {
  const v = raceView("edited-race-f1-mid-race"); // newest race-control call: the 3 s penalty at T + 130.05
  const T = v.calls[0]!.t_unix;

  it("the call gives the reason when it is at least as new as the newest event", () => {
    const events = [ev("penalty", "PENA", T - 0.3, true), ev("other", "OVTK", T - 1)];
    expect(raceControlLine(events, T + 2, null, v)).toBe("Race control · 3 second penalty: corner cutting · just now");
    expect(raceControlLine([], T + 125, null, v)).toBe("Race control · 3 second penalty: corner cutting · 2 min ago");
  });

  it("a newer event wins over an older call", () => {
    const events = [ev("chequered_flag", "CHQF", T + 60)];
    expect(raceControlLine(events, T + 61, null, v)).toBe("Race control · Chequered flag · just now");
  });

  it("calls that are not race control (positions, the start, gaps) never take the line", () => {
    const positions = raceView("edited-race-forza"); // a position call only
    expect(raceControlLine([], 2_000_000_000, null, positions)).toBe("Race control · nothing yet");
    const events = [ev("penalty", "PENA", 1000)];
    expect(raceControlLine(events, 1001, null, positions)).toBe("Race control · Penalty issued · just now");
  });

  it("without a race block the line is as before", () => {
    const events = [ev("other", "OVTK", 999), ev("penalty", "PENA", 880)];
    expect(raceControlLine(events, 1000)).toBe("Race control · Penalty issued · 2 min ago");
    expect(raceControlLine(events, 1000, null, null)).toBe("Race control · Penalty issued · 2 min ago");
  });

  it("a red flag call (synthetic session) reads in full", () => {
    const red = raceView("edited-race-f1-red-flag-synthetic");
    expect(raceControlLine([ev("red_flag", "RDFL", red.calls[0]!.t_unix - 0.2)], red.calls[0]!.t_unix + 1, null, red)).toBe(
      "Race control · Red flag, red flag. Slow down, back to the pits · just now",
    );
  });

  it("an event without a time never hides a call", () => {
    const events = [{ ...ev("penalty", "PENA", 0), t: Number.NaN }];
    expect(raceControlLine(events, T + 1, null, v)).toBe("Race control · 3 second penalty: corner cutting · just now");
  });
});

describe("the position's evidence note", () => {
  it("GT7 and Forza carry the backend's words; F1 none; none without a position", () => {
    expect(raceNote(raceView("edited-race-gt7-grid"))).toBe("From GT7's race position; not yet checked against the game's screen.");
    expect(raceNote(raceView("edited-race-forza"))).toMatch(/^From Forza's race position/);
    expect(raceNote(raceView("edited-race-f1-mid-race"))).toBeNull();
    expect(raceNote(raceView("edited-off-gt7-not-race"))).toBeNull();
    expect(raceNote(null)).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------ render

function stubDom(): void {
  const { win } = stubBrowser("http://127.0.0.1:8770/#/drive/car");
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

beforeAll(async () => {
  stubDom();
  CarScreen = (await import("./CarScreen")).CarScreen;
  vi.unstubAllGlobals();
});

/** The GT7 recorded snapshot as live data (its connection was stale when it was recorded). */
function gt7(): SnapshotNext {
  const s = fixture("recorded-live-api-gt7-stale");
  s.connection = { ...s.connection, status: "live", last_packet_age_s: 0.02 };
  return s;
}

function car(s: SnapshotNext): string {
  const nowS = newestT(s) + 1;
  return renderToStaticMarkup(
    createElement(CarScreen, { model: driveModel({ snap: s, connected: true, nowS, driver: null }), snap: s, history: [], nowS }),
  );
}

const visible = (m: string): string =>
  m
    .replace(/<span class="sr-only">[^<]*<\/span>/g, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/\s+/g, " ")
    .trim();

describe("Drive › Car rendered with a race block", () => {
  it("GT7: P8 in the status slot and the evidence note under the race-control line", () => {
    const html = car(withRace(gt7(), { ...raceView("edited-race-gt7-grid"), lap: 5 }));
    const t = visible(html);
    expect(t).toMatch(/Lap 5 \/ 10 P8 /); // the slot: track · lap / total · position
    expect(html).toContain('class="pww-foot__note"');
    expect(t).toContain("Race control · nothing yet From GT7's race position; not yet checked against the game's screen.");
  });

  it("GT7 without a block: no P and no note (as before)", () => {
    const html = car(gt7());
    expect(visible(html)).toMatch(/Lap 5 \/ 10 Coach /);
    expect(visible(html)).not.toMatch(/\bP8\b/);
    expect(html).not.toContain("pww-foot__note");
  });

  it("F1: the race-control line carries the call's reason, no note", () => {
    const s = withRace(fixture("recorded-suzuka-penalty-any-car"), raceView("edited-race-f1-mid-race"));
    s.race!.calls = s.race!.calls.map((c) => ({ ...c, t_unix: newestT(s) + 0.5 }));
    const html = car(s);
    expect(visible(html)).toContain("Race control · 3 second penalty: corner cutting · just now");
    expect(html).not.toContain("pww-foot__note");
  });
});
