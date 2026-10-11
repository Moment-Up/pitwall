// Line map geometry (feat/technique spec §9): projection like the track map, gaps lift the pen, windows wrap through
// the start line, a corner zoom keeps equal axes and a minimum size, the scale bar is in real metres.
import { describe, expect, it } from "vitest";
import { techniqueFixtures } from "../technique/testkit";
import {
  fitAspect,
  placeLabels,
  spreadMarkers,
  boundsOf,
  cornerView,
  cornerWindowM,
  indexAt,
  inView,
  linePath,
  MIN_CORNER_VIEW_M,
  niceBarM,
  padView,
  pointAtM,
  projectLine,
  scaleBar,
  viewBoxAttr,
  wholeLapView,
  windowIndices,
} from "./line-map";

describe("line map geometry", () => {
  it("projects (x, z) to (x, −z) and keeps unknown points as gaps", () => {
    expect(projectLine([[1, 2], null, [3, -4], [Number.NaN, 1]])).toEqual([[1, -2], null, [3, 4], null]);
    expect(projectLine(null)).toEqual([]);
  });

  it("paths lift the pen across gaps and index jumps, and continue through the start line", () => {
    const pts = projectLine([[0, 0], [1, 0], null, [3, 0], [4, 0]]);
    expect(linePath(pts)).toBe("M0,0L1,0M3,0L4,0");
    expect(linePath(pts, [3, 4, 0, 1])).toBe("M3,0L4,0L0,0L1,0");
    expect(linePath(pts, [0, 3])).toBe("M0,0M3,0");
  });

  it("windows wrap through the start line", () => {
    expect(windowIndices(10, 20, 5, 100)).toEqual([2, 3, 4]);
    expect(windowIndices(12, 21, 5, 100)).toEqual([2, 3, 4, 5]);
    expect(windowIndices(-10, 5, 5, 100)).toEqual([98, 99, 0, 1]);
    expect(windowIndices(490, 10, 5, 100)).toEqual([98, 99, 0, 1, 2]);
    expect(windowIndices(0, 1000, 5, 100)).toHaveLength(100);
    expect(windowIndices(Number.NaN, 10, 5, 100)).toEqual([]);
  });

  it("indices and points at a lap distance (wrapped)", () => {
    expect(indexAt(12, 5, 100)).toBe(2);
    expect(indexAt(-5, 5, 100)).toBe(99);
    expect(indexAt(503, 5, 100)).toBe(1);
    expect(indexAt(null, 5, 100)).toBeNull();
    const pts = projectLine([[0, 0], [5, 0], [10, 0]]);
    expect(pointAtM(pts, 5, 6)).toEqual([5, -0]);
  });

  it("bounds, padding and the minimum corner size", () => {
    const pts = projectLine([[0, 0], [10, 0], [10, 20]]);
    expect(boundsOf([pts])).toEqual({ x: 0, y: -20, w: 10, h: 20 });
    expect(boundsOf([projectLine([[1, 1]])])).toBeNull();
    const p = padView({ x: 0, y: 0, w: 10, h: 2 }, 0.1, 40);
    expect(p.w).toBe(40);
    expect(p.h).toBe(40);
    expect(p.x + p.w / 2).toBeCloseTo(5);
    expect(viewBoxAttr({ x: 1.234, y: -2, w: 3, h: 4 })).toBe("1.23 -2 3 4");
    expect(inView([1, 1], { x: 0, y: 0, w: 2, h: 2 })).toBe(true);
    expect(inView(null, { x: 0, y: 0, w: 2, h: 2 })).toBe(false);
  });

  it("a corner of the fixture zooms to its window at true scale; the whole lap fits both lines", () => {
    const cmp = techniqueFixtures.austriaCompare();
    const ref = projectLine(cmp.lines!.ref_xz);
    const lap = projectLine(cmp.lines!.lap_xz);
    const whole = wholeLapView([ref, lap])!;
    const t4 = cmp.corners.find((c) => c.corner === "T3")!;
    const w = cornerWindowM(t4.points)!;
    const zoom = cornerView([ref, lap], cmp.lines!.step_m, w)!;
    expect(zoom.w).toBeGreaterThanOrEqual(MIN_CORNER_VIEW_M);
    expect(zoom.w).toBeLessThan(whole.w / 2);
    // the marker (your lap at T4's apex) is inside the zoomed view
    const m = cmp.markers[0]!;
    expect(inView([m.xz[0], -m.xz[1]], zoom)).toBe(true);
    expect(cornerWindowM({ turn_in: null, apex: 100, track_out: null })).toEqual([0, 200]);
    expect(cornerWindowM({ turn_in: null, apex: null, track_out: null })).toBeNull();
  });

  it("the view grows to the box's aspect about its centre (equal axes kept)", () => {
    expect(fitAspect({ x: 0, y: 0, w: 10, h: 10 }, 2)).toEqual({ x: -5, y: 0, w: 20, h: 10 });
    expect(fitAspect({ x: 0, y: 0, w: 40, h: 10 }, 2)).toEqual({ x: 0, y: -5, w: 40, h: 20 });
    expect(fitAspect({ x: 1, y: 2, w: 3, h: 4 }, null)).toEqual({ x: 1, y: 2, w: 3, h: 4 });
  });

  it("markers that would overlap move to a clear spot; the first keeps its place", () => {
    const out = spreadMarkers([[0, 0], [1, 0], [50, 50]], 5);
    expect(out[0]).toEqual([0, 0]);
    expect(Math.hypot(out[1]![0] - out[0]![0], out[1]![1] - out[0]![1])).toBeGreaterThanOrEqual(5);
    expect(out[2]).toEqual([50, 50]);
  });

  it("labels of close points do not print over each other", () => {
    const l = placeLabels([[0, 0], [1, 0]], [4, 9], 2);
    expect(l[0]).toMatchObject({ anchor: "start" });
    expect(l[1]!.y === l[0]!.y && l[1]!.anchor === l[0]!.anchor).toBe(false);
  });

  it("scale bars: 10 m when zoomed, a round length near a fifth of the width otherwise", () => {
    expect(niceBarM(800)).toBe(100);
    expect(niceBarM(60)).toBe(10);
    expect(niceBarM(2400)).toBe(200);
    expect(niceBarM(0)).toBe(10);
    const b = scaleBar({ x: 0, y: 0, w: 60, h: 40 }, 10);
    expect(b.x2 - b.x1).toBe(10);
    expect(b.label).toBe("10 m");
  });
});
