// Render tests for the Drive edge bars (SpotterBarsView: static markup in plain node) at the two target sizes, iPad
// 1180 x 820 (content area right of the 72 px rail) and phone 390 x 844 (between the app bar and the tab bar), for
// every state the view model can be in.

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { barsView, parseSpotterBlock, type BarsContext } from "../../lib/spotter/view";
import { spotterFixture, type SpotterLiveFixture } from "../../test/spotter";
import { BAR_W, SpotterBarsView, type BarsRect } from "./SpotterBarsView";

const IPAD: BarsRect = { left: 72, top: 0, width: 1108, height: 820 };
const PHONE: BarsRect = { left: 0, top: 52, width: 390, height: 728 };
const LIVE: BarsContext = { connected: true, status: "live", fresh: true };

function render(name: SpotterLiveFixture, rect: BarsRect | null = IPAD, ctx: BarsContext = LIVE): string {
  const view = barsView(parseSpotterBlock(spotterFixture(name)), ctx);
  return renderToStaticMarkup(createElement(SpotterBarsView, { view, rect }));
}

const bars = (m: string): string[] => m.match(/<div class="pw-spotter-bar[^"]*"[^>]*>/g) ?? [];

describe("SpotterBarsView", () => {
  it.each([["iPad 1180 x 820", IPAD] as const, ["phone 390 x 844", PHONE] as const])(
    "%s: fixed to the content area, never takes a tap, says nothing to a screen reader",
    (_what, rect) => {
      const m = render("live-alongside-left", rect);
      expect(m).toContain("pointer-events-none fixed");
      expect(m).toContain('aria-hidden="true"');
      const px = (n: number) => (n === 0 ? "0" : `${n}px`);
      expect(m).toContain(`left:${px(rect.left)};top:${px(rect.top)};width:${px(rect.width)};height:${px(rect.height)}`);
      expect(m).toContain(`width:${BAR_W}`);
      expect(BAR_W).toBe("clamp(12px, 2.5vw, 32px)");
    },
  );

  it("alongside left: one amber bar on the left with the car block", () => {
    const m = render("live-alongside-left");
    const b = bars(m);
    expect(b).toHaveLength(1);
    expect(b[0]).toContain('data-side="left"');
    expect(b[0]).toContain('data-tone="alongside"');
    expect(b[0]).toContain("bg-warning/30");
    expect(b[0]).toContain('data-label="left alongside 1.8 m behind"');
    expect(m).toMatch(/class="pw-spotter-car[^"]*bg-warning"[^>]*style="top:\d+(\.\d)?%;height:39.3%"/);
  });

  it("close right: a solid red bar (fill differs from 'alongside', so red-green safe mode still tells them apart)", () => {
    const m = render("live-close-right");
    const b = bars(m);
    expect(b).toHaveLength(1);
    expect(b[0]).toContain('data-side="right"');
    expect(b[0]).toContain('data-tone="close"');
    expect(b[0]).toMatch(/ bg-danger"/);
    expect(m).toContain("bg-danger-foreground/70");
  });

  it("three wide: both bars, no text", () => {
    const m = render("live-three-wide");
    expect(bars(m).map((b) => b.match(/data-side="(\w+)"/)?.[1])).toEqual(["left", "right"]);
    expect(m).toContain("data-three-wide");
    expect(m.replace(/<[^>]+>/g, "").trim()).toBe("");
  });

  it("outside a three-wide: one bar, two cars", () => {
    expect(bars(render("live-outside-three-wide"))[0]).toContain('data-cars="2"');
  });

  it.each([
    ["clear", "live-clear", LIVE],
    ["switched off", "live-off", LIVE],
    ["safety car", "live-safety-car", LIVE],
    ["newer block version", "live-newer-version", LIVE],
    ["socket down", "live-alongside-left", { ...LIVE, connected: false }],
    ["stream stale", "live-alongside-left", { ...LIVE, status: "stale" }],
    ["no fresh block", "live-alongside-left", { ...LIVE, fresh: false }],
  ] as const)("%s: nothing rendered at all", (_what, name, ctx) => {
    expect(render(name, IPAD, ctx)).toBe("");
  });

  it("not measured yet (first frame): nothing", () => {
    expect(render("live-alongside-left", null)).toBe("");
  });

  it("nothing animates (no transition classes)", () => {
    for (const n of ["live-alongside-left", "live-close-right", "live-three-wide"] as const) {
      expect(render(n)).not.toMatch(/transition|animate|duration-/);
    }
  });
});
