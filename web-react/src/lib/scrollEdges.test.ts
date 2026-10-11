import { describe, expect, it } from "vitest";
import { fadeAttr, scrollEdges } from "./scrollEdges";

describe("sideways scroller edges (ScrollRow fades)", () => {
  it("a row that fits has no hidden end", () => {
    expect(scrollEdges(0, 358, 358)).toEqual({ start: false, end: false });
    expect(scrollEdges(0, 358.6, 358)).toEqual({ start: false, end: false }); // sub-pixel rounding
    expect(fadeAttr(scrollEdges(0, 300, 358))).toBeUndefined();
  });

  it("fades the end with more content: at the start, in the middle, at the end", () => {
    // the Sessions driver filter on a 390 px phone: 484 px of Segment in a 358 px row
    expect(fadeAttr(scrollEdges(0, 484, 358))).toBe("end");
    expect(fadeAttr(scrollEdges(60, 484, 358))).toBe("both");
    expect(fadeAttr(scrollEdges(126, 484, 358))).toBe("start");
    expect(fadeAttr(scrollEdges(125.5, 484, 358))).toBe("start");
    // overscroll (iOS rubber band) clamps
    expect(scrollEdges(-20, 484, 358)).toEqual({ start: false, end: true });
    expect(scrollEdges(200, 484, 358)).toEqual({ start: true, end: false });
  });
});
