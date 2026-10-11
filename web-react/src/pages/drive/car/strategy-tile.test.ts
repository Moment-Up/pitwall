// Drive › Car with the race strategy tile (lane "strategy"), server-rendered to static markup in plain node like
// wall.test.ts: the tile takes the Inputs slot in a race only, keeps six rows, says unknown as "-", shows band words
// (never colour alone), the SYNTHETIC chip, and plain words for a simple-wording profile.
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { driveModel, type DriveModel } from "../../../lib/drive/model";
import { fixture, newestT } from "../../../lib/drive/testkit";
import type { SnapshotNext } from "../../../lib/drive/types";
import type { HistoryPoint } from "../../../lib/live";
import { bareRace, liveView } from "../../../lib/strategy/testkit";
import type { StrategyView } from "../../../lib/strategy/types";
import { stubBrowser } from "../../../test/fakes";
import type { CarScreenProps } from "./CarScreen";

let CarScreen: ComponentType<CarScreenProps>;

beforeAll(async () => {
  const { win } = stubBrowser("http://127.0.0.1:8770/next/#/drive/car");
  Object.assign(win, {
    navigator: globalThis.navigator,
    removeEventListener: () => {},
    screen: { orientation: {} },
    visualViewport: {},
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }),
  });
  CarScreen = (await import("./CarScreen")).CarScreen;
  vi.unstubAllGlobals();
});

const HISTORY: HistoryPoint[] = Array.from({ length: 40 }, (_, i) => ({ t: i * 0.05, speed: 200 + i, throttle: 1, brake: 0 }));

function model(s: SnapshotNext | null, connected = true): DriveModel {
  return driveModel({ snap: s, connected, nowS: newestT(s) + 1, driver: null });
}

/** A recorded Drive fixture with a strategy block (the wire carries both in one snapshot). */
function withStrategy(view: StrategyView | null | undefined): SnapshotNext {
  const s = fixture("recorded-austria-on-track-behind");
  s.strategy = view;
  return s;
}

function render(s: SnapshotNext, opts: { simple?: boolean; connected?: boolean } = {}): string {
  return renderToStaticMarkup(
    createElement(CarScreen, { model: model(s, opts.connected ?? true), snap: s, history: HISTORY, nowS: newestT(s) + 1, simple: opts.simple }),
  );
}

/** Text a sighted user sees. */
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

describe("Drive › Car: the strategy tile takes the Inputs slot in a race only", () => {
  it("no data (an older server), not supported by this game, or a sprint: the Inputs tile, unchanged", () => {
    const sprint = liveView("recorded-live-race-austria-excerpt"); // 3 laps (review L2)
    for (const v of [undefined, null, liveView("edited-live-off-unsupported-game"), liveView("edited-live-practice"), sprint]) {
      const html = render(withStrategy(v));
      expect(html).toContain("Inputs · last 12 s");
      expect(html).not.toContain("pws-rows");
    }
  });

  it("a race: six rows in the bottom-left slot, the same span as Inputs, the newest call in the footer", () => {
    const html = render(withStrategy(liveView("edited-live-race-window-open")));
    expect(html).not.toContain("Inputs · last 12 s");
    expect(html).toContain('pww-tile pww-s4 pws"');
    expect(html.match(/class="pws-row"/g)).toHaveLength(6);
    const text = visible(html);
    expect(text).toContain("Strategy L20/30 · P6");
    expect(text).toContain("Ahead +1.8 s · closing 0.3/lap");
    expect(text).toContain("Behind DRS 0.8 s · closing 0.2/lap");
    expect(text).toContain("Pit window OPEN L18-22 · best L20 (game)");
    expect(text).toContain("Undercut THREAT ahead marginal · behind threat");
    expect(text).toContain("Fuel TIGHT +0.2 laps");
    expect(text).toContain("Weather Dry for 15 min");
    expect(text).toContain("L19 · Car behind is within a second, DRS range.");
    // the newest call may take two lines, so the end of an instruction is never cut off (review H1)
    expect(html).toContain('class="pww-foot pww-foot--wrap"');
    // band words carry the meaning; amber is only their background (P4)
    expect(html).toContain('class="pws-tag" data-tone="warn">DRS</span>');
    expect(html).toContain('aria-label="Car behind: 0.8 seconds, closing 0.2 seconds a lap, in DRS range, 0 stops"');
  });

  it("unknown is '-' (the kit's Unknown), never 0, from the first tick of a race", () => {
    const html = render(withStrategy(bareRace({ total_laps: 52 })));
    expect(html.match(/class="pws-row"/g)).toHaveLength(6);
    expect(html.match(/pw-unknown/g)?.length).toBeGreaterThanOrEqual(6);
    expect(visible(html)).not.toMatch(/\b0\.0 (s|laps)\b/);
  });

  it("an unsettled gap is dimmed and said so", () => {
    const html = render(withStrategy(liveView("edited-live-race-vsc")));
    expect(html).toMatch(/data-row="ahead" data-tone="plain" data-dim=""/);
    expect(html).toContain("last settled value");
    expect(visible(html)).toContain("Safety car VSC Stop 11 s · green 19 s (estimate)");
  });

  it("synthetic: the hatched SYNTHETIC chip in the tile header", () => {
    const html = render(withStrategy(liveView("edited-live-race-synthetic")));
    expect(html).toContain('data-evidence="synthetic"');
    expect(visible(html)).toContain("SYNTHETIC L8/12 · P4");
  });

  it("beginner wording (simple-wording profile): plain labels, no jargon rows", () => {
    const text = visible(render(withStrategy(liveView("edited-live-race-window-open")), { simple: true }));
    expect(text).toContain("Car ahead +1.8 s · you gain 0.3 s a lap");
    expect(text).toContain("Pit stop OPEN Stop lap 18-22 · best 20 (game)");
    expect(text).toContain("Car behind CLOSE 0.8 s · it gains 0.2 s a lap"); // no "DRS"
    expect(text).toContain("Laps to go 11"); // instead of "Pit first"
    expect(text).toContain("Fuel TIGHT Only 0.2 laps spare");
    expect(text).not.toMatch(/Undercut|marginal/);
    const tile = render(withStrategy(liveView("edited-live-race-window-open")), { simple: true });
    expect(tile).not.toMatch(/class="pws-tag"[^>]*>DRS</); // the band word is CLOSE (other tiles may say DRS)
  });

  it("offline: the tile stays (last known, dimmed by the wall) and says so", () => {
    const s = withStrategy(liveView("edited-live-race-austria-l67"));
    const html = render(s, { connected: false });
    expect(html).toContain('data-dim=""');
    // the last known values; the newest call (lap 65, two laps ago) no longer holds
    expect(visible(html)).toContain("Last known · No new strategy calls");
  });

  it("the Tyres & energy line uses this race's measured fuel margin", () => {
    const s = withStrategy(liveView("edited-live-race-austria-l67"));
    expect(visible(render(s))).toMatch(/Fuel [\d.]+ kg · \+2\.3 laps · ERS/);
  });
});
