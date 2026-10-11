import { describe, expect, it } from "vitest";
import { SPEED_FLOOR_KPH, liveTraceLayout, speedCeiling, traceLanes, type TraceSample } from "./trace";

// Test history at 20 Hz (synthetic samples, not game data).
function history(seconds: number, from = 100, hz = 20, f: (t: number) => Partial<TraceSample> = () => ({})): TraceSample[] {
  const out: TraceSample[] = [];
  for (let i = 0; i <= seconds * hz; i++) {
    const t = from + i / hz;
    out.push({ t, speed: 200, throttle: 1, brake: 0, ...f(t) });
  }
  return out;
}

describe("speedCeiling", () => {
  it("rounds the window's top speed up to 50 km/h, at least 100", () => {
    expect(speedCeiling(null)).toBe(SPEED_FLOOR_KPH);
    expect(speedCeiling(60)).toBe(100);
    expect(speedCeiling(212)).toBe(250);
    expect(speedCeiling(300)).toBe(300);
    expect(speedCeiling(301)).toBe(350);
  });
});

describe("traceLanes", () => {
  it("gives speed the top 56 % and stacks throttle and brake under it, 6 px apart", () => {
    const l = traceLanes(200);
    expect(l.speed.y0).toBe(4);
    expect(l.speed.y1).toBeCloseTo(4 + 192 * 0.56);
    expect(l.throttle.y0).toBeCloseTo(l.speed.y1 + 6);
    expect(l.brake.y0).toBeCloseTo(l.throttle.y1 + 6);
    expect(l.brake.y1).toBeCloseTo(196);
  });
});

describe("liveTraceLayout", () => {
  it("shows the last 12 s with the newest sample at the right edge", () => {
    const l = liveTraceLayout(history(20), { width: 400, height: 200, padLeft: 64, padRight: 6 });
    expect(l.tNow).toBeCloseTo(120);
    expect(l.speed).toHaveLength(1);
    const pts = l.speed[0]!;
    expect(pts.at(-2)).toBeCloseTo(394); // x of the newest sample
    expect(pts[0]).toBeCloseTo(64); // the oldest sample in the window sits on the left edge
    expect(pts.length / 2).toBe(12 * 20 + 1);
    expect(l.speedMax).toBe(200);
    expect(pts[1]).toBeCloseTo(l.lanes.speed.y0); // 200 of 200 km/h: the lane's top
  });

  it("maps throttle and brake 0..1 into their lanes, clamped", () => {
    const l = liveTraceLayout(history(2, 0, 20, () => ({ throttle: 1.4, brake: 0.5 })), { width: 300, height: 200 });
    expect(l.throttle[0]![1]).toBeCloseTo(l.lanes.throttle.y0);
    expect(l.brake[0]![1]).toBeCloseTo((l.lanes.brake.y0 + l.lanes.brake.y1) / 2);
  });

  it("breaks the lines at unknown samples and at gaps in the stream, never bridging them", () => {
    const h = history(4, 0, 20, (t) => (t > 1 && t < 1.5 ? { speed: null } : {}));
    const gap = [...h.slice(0, 20), ...h.slice(60).map((p) => ({ ...p, t: p.t + 2 }))];
    expect(liveTraceLayout(h, { width: 300, height: 200 }).speed).toHaveLength(2);
    expect(liveTraceLayout(h, { width: 300, height: 200 }).throttle).toHaveLength(1);
    expect(liveTraceLayout(gap, { width: 300, height: 200 }).throttle).toHaveLength(2);
  });

  it("draws nothing without history", () => {
    const l = liveTraceLayout([], { width: 300, height: 200 });
    expect(l.tNow).toBeNull();
    expect(l.speed).toEqual([]);
    expect(l.speedMax).toBe(SPEED_FLOOR_KPH);
  });
});
