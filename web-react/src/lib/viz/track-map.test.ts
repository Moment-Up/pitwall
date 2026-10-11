import { describe, expect, it } from "vitest";
import { fixture } from "../drive/testkit";
import type { TrackModelNext } from "../drive/types";
import type { BrakePrior, TrackOutline } from "./outline";
import { drawsOutline, priorTitle, trackQuery, uncoveredPriorPieces } from "./outline";
import {
  crossTick,
  fullPath,
  liveYellowZones,
  mapGeometry,
  mapPointAtGameM,
  mapPointOfWorld,
  pathBetween,
  pointAt,
  sectorStatusColour,
  segmentColour,
  trackMapLayout,
  worldXZ,
  type MapText,
} from "./track-map";

// Real data: a headless replay of a PS5 F1 25 capture at Suzuka (src/test/fixtures/drive, lane DL), with the learned
// centreline (1 162 points, 5 m apart), 11 learned corners carrying official labels, and the game's skeleton.
const S = fixture("recorded-suzuka-on-track-brake-ahead");
const MODEL = S.track_model as TrackModelNext;
const SK = S.skeleton!;

function square(n = 40, side = 100): [number, number][] {
  // a synthetic square loop, 5 m apart (test geometry only)
  const pts: [number, number][] = [];
  const per = n / 4;
  for (let i = 0; i < n; i++) {
    const k = Math.floor(i / per);
    const t = (i % per) / per;
    const p: [number, number] =
      k === 0 ? [t * side, 0] : k === 1 ? [side, t * side] : k === 2 ? [side - t * side, side] : [0, side - t * side];
    pts.push(p);
  }
  return pts;
}

describe("map geometry", () => {
  it("projects the real Suzuka centreline north-up (y = -z) with a stroke of the largest side / 110", () => {
    const g = mapGeometry(MODEL.centreline, 5, MODEL.length_m)!;
    expect(g.pts).toHaveLength(1162);
    expect(g.minX).toBeCloseTo(-902.22);
    expect(g.w).toBeCloseTo(1070.09 + 902.22);
    expect(g.minY).toBeCloseTo(-611.63);
    expect(g.h).toBeCloseTo(611.63 + 403.78);
    expect(g.s).toBeCloseTo(g.w / 110);
    expect(g.lengthM).toBe(5809);
  });

  it("is null when there is no drawable line", () => {
    expect(mapGeometry(null)).toBeNull();
    expect(mapGeometry([[0, 0], [1, 1]])).toBeNull();
    expect(mapGeometry([[0, 0], [Number.NaN, 1], [2, 2]])).toBeNull();
  });

  it("finds points by lap distance, wrapping past the line", () => {
    const g = mapGeometry(square(), 5, 200)!;
    expect(pointAt(g, 0)).toEqual([0, -0]);
    expect(pointAt(g, 50)).toEqual([100, -0]);
    expect(pointAt(g, 205)).toEqual(pointAt(g, 5));
    expect(pointAt(g, -5)).toEqual(pointAt(g, 195));
    expect(pointAt(g, Number.NaN)).toBeNull();
  });

  it("draws a piece through the line as two subpaths, closing onto the first point", () => {
    const g = mapGeometry(square(), 5, 200)!;
    const wrap = pathBetween(g, 180, 20);
    expect(wrap.match(/M/g)).toHaveLength(2);
    expect(wrap).toContain("L0.0,0.0M0.0,0.0"); // the end closes onto point 0, then the second piece starts there
    expect(fullPath(g).endsWith("Z")).toBe(true);
    expect(pathBetween(g, Number.NaN, 5)).toBe("");
  });

  it("puts a cross tick perpendicular to the line", () => {
    const g = mapGeometry(square(), 5, 200)!;
    const t = crossTick(g, 25, 10)!; // on the first side, running along +x
    expect(t.x1).toBeCloseTo(t.x2);
    expect(Math.abs(t.y1 - t.y2)).toBeCloseTo(20);
  });
});

describe("trackMapLayout (real Suzuka)", () => {
  const l = trackMapLayout({ model: MODEL, skeleton: SK, highlight: "T7", focus: ["T7"] })!;

  it("draws the learned line on three neutral sector casings with S2 and S3 boundary ticks", () => {
    expect(l.source).toBe("model");
    expect(l.casings.map((c) => c.colour)).toEqual(["var(--pw-sector-1)", "var(--pw-sector-2)", "var(--pw-sector-3)"]);
    expect(l.lines).toHaveLength(1);
    expect(l.lines[0]!.colour).toBe("var(--muted)");
    expect(l.sectorTicks.map((t) => t.label.text)).toEqual(["S2", "S3"]);
    expect(l.marshalTicks).toHaveLength(14);
    expect(l.marshalTicks[0]!.title).toMatch(/^Marshal zone 1 \(606–859 m/);
    expect(l.start).not.toBeNull();
  });

  it("labels corners with their OFFICIAL labels, highlight and focus first, and never overlaps two labels", () => {
    const hairpin = l.corners.find((c) => c.name === "T7")!;
    expect(hairpin).toMatchObject({ label: "T11", highlight: true, focus: true });
    expect(hairpin.text?.text).toBe("T11");
    expect(l.corners.find((c) => c.name === "T2")!.label).toBe("T3-5");
    const placed = l.corners.map((c) => c.text).filter((t): t is MapText => t != null);
    const box = (t: MapText) => {
      const w = t.text.length * l.font * 0.62;
      const x0 = t.anchor === "start" ? t.x : t.anchor === "end" ? t.x - w : t.x - w / 2;
      return { x0, x1: x0 + w, y0: t.y - l.font * 0.8, y1: t.y + l.font * 0.2 };
    };
    for (let i = 0; i < placed.length; i++)
      for (let j = i + 1; j < placed.length; j++) {
        const a = box(placed[i]!);
        const b = box(placed[j]!);
        expect(a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1, `${placed[i]!.text} / ${placed[j]!.text}`).toBe(false);
      }
    expect(l.corners.at(-1)!.highlight).toBe(true); // drawn last, on top
  });

  it("draws an official label shared by two learned corners once (Suzuka's T16-17 complex)", () => {
    const both = l.corners.filter((c) => c.label === "T16-17");
    expect(both).toHaveLength(2);
    expect(both.filter((c) => c.text)).toHaveLength(1);
  });

  it("keeps labels about 12-20 px and the car 6-10 px when the rendered size is known", () => {
    // the layout estimates its scale before labels widen the view box, so allow a pixel either way
    for (const [w, h] of [
      [320, 200],
      [640, 413],
      [1600, 1000],
    ] as const) {
      const p = trackMapLayout({ model: MODEL, skeleton: SK, pixelSize: { width: w, height: h } })!;
      const scale = Math.min(w / p.viewBox.w, h / p.viewBox.h);
      expect(p.font * scale).toBeGreaterThan(10.5);
      expect(p.font * scale).toBeLessThan(22);
      expect(p.carR * scale).toBeGreaterThan(5);
      expect(p.carR * scale).toBeLessThan(11);
    }
  });

  it("keeps every label inside the view box", () => {
    const vb = l.viewBox;
    for (const c of l.corners) {
      if (!c.text) continue;
      expect(c.text.x).toBeGreaterThanOrEqual(vb.x);
      expect(c.text.x).toBeLessThanOrEqual(vb.x + vb.w);
      expect(c.text.y).toBeGreaterThanOrEqual(vb.y);
      expect(c.text.y).toBeLessThanOrEqual(vb.y + vb.h);
    }
  });

  it("draws learned braking (entry -> apex) per corner, and labels only key corners in 'key' mode", () => {
    expect(l.brake).toHaveLength(11);
    expect(l.brake[0]!.colour).toBe("var(--pw-brake)");
    const key = trackMapLayout({ model: MODEL, skeleton: SK, highlight: "T5", focus: ["T7"], labels: "key" })!;
    expect(key.corners.filter((c) => c.text).map((c) => c.label).sort()).toEqual(["T11", "T8"]);
    const none = trackMapLayout({ model: MODEL, skeleton: SK, labels: "none" })!;
    expect(none.corners.every((c) => c.text == null)).toBe(true);
  });

  it("draws a brake notch across the line at each cue target (Drive › Track), never on an outline", () => {
    const targets = S.cues!.cues.map((c) => c.target_m);
    const n = trackMapLayout({ model: MODEL, skeleton: SK, cueTargetsM: targets })!;
    expect(n.notches).toHaveLength(1);
    const mid = [(n.notches[0]!.x1 + n.notches[0]!.x2) / 2, (n.notches[0]!.y1 + n.notches[0]!.y2) / 2];
    const p = pointAt(n.geom, 2826.3)!;
    expect(mid[0]).toBeCloseTo(p[0], 1);
    expect(mid[1]).toBeCloseTo(p[1], 1);
    expect(l.notches).toEqual([]);
  });

  it("draws yellow zones only from live flags", () => {
    expect(trackMapLayout({ model: MODEL, skeleton: SK })!.yellow).toEqual([]);
    const live = liveYellowZones(SK, [{ game_number: 2, flag: "yellow" }, { game_number: 3, flag: "green" }], false);
    expect([...live]).toEqual([2]);
    expect(trackMapLayout({ model: MODEL, skeleton: SK, yellow: live })!.yellow).toHaveLength(1);
    // a stored skeleton's flag is never drawn unless the caller says the skeleton is live
    const sk = structuredClone(SK);
    sk.marshal_zones![0]!.flag = "yellow";
    expect(liveYellowZones(sk, null, false).size).toBe(0);
    expect([...liveYellowZones(sk, null, true)]).toEqual([1]);
    expect(liveYellowZones(sk, [], true).size).toBe(0); // explicit live flags win
  });

  it("colours sectors by timing status as set (Car wall) and corners by time gained or lost (Review)", () => {
    const st = trackMapLayout({ model: MODEL, skeleton: SK, sectorStatus: ["sb", "slower", null] })!;
    expect(st.lines.map((x) => x.colour)).toEqual(["var(--muted)", "var(--pw-pb)", "var(--pw-slower)"]);
    const seg = trackMapLayout({ model: MODEL, skeleton: SK, segmentDelta: { T1: -0.05, T7: 0.11, T9: 0.004, T3: null } })!;
    expect(seg.lines.slice(1).map((x) => x.colour)).toEqual(["var(--pw-ahead)", "var(--pw-faint)", "var(--pw-behind)", "var(--muted)"]);
  });

  it("maps game metres onto the line by lap fraction (cursor, car without a position)", () => {
    const p = mapPointAtGameM(l, 2483.1)!;
    expect(p).toEqual(pointAt(l.geom, 2483.1));
    const other = trackMapLayout({ model: MODEL, skeleton: { ...SK, track_length_m: 5809 * 1.01 } })!;
    expect(mapPointAtGameM(other, 5809 * 1.01 * 0.5)).toEqual(pointAt(other.geom, 5809 * 0.5));
    expect(mapPointAtGameM(l, null)).toBeNull();
  });

  it("places the car from the frame's ground-plane position (x, z)", () => {
    expect(worldXZ(S.frame!.pos)).toEqual([-88.92, 148.55]);
    expect(mapPointOfWorld([-88.92, 148.55])).toEqual([-88.92, -148.55]);
    expect(worldXZ([1, 2, null])).toBeNull();
  });
});

describe("track priors", () => {
  const outline: TrackOutline = {
    game: "f1_25",
    track_id: "f1:13",
    tier: "shipped_seed",
    label: "game outline (Pits n' Giggles)",
    attribution: "Track outline derived from Pits n' Giggles, MIT License.",
    length_m: 200,
    centreline_step_m: 5,
    centreline: square(),
  };

  it("draws the outline (dashed, labelled) only while the learned model has no line", () => {
    expect(drawsOutline(MODEL, outline)).toBe(false);
    const bare = { ...MODEL, centreline: [] };
    expect(drawsOutline(bare, outline)).toBe(true);
    const l = trackMapLayout({ model: bare, outline })!;
    expect(l.source).toBe("outline");
    expect(l.lines[0]!.dash).toBeDefined();
    expect(l.corners).toEqual([]); // learned corners need the learned line
    expect(l.brake).toEqual([]);
    expect(l.sourceLabel?.text).toBe("game outline (Pits n' Giggles)");
    expect(l.lines[0]!.title).toBe("game outline (Pits n' Giggles): not your line and not a target");
    expect(l.notches).toEqual([]);
    expect(trackMapLayout({ model: null, outline: null })).toBeNull();
    expect(drawsOutline(null, { ...outline, centreline: [] })).toBe(false);
  });

  it("builds the endpoint query with the session's lap length when known", () => {
    expect(trackQuery("f1_25", "f1:13", 5809)).toBe("game=f1_25&track_id=f1%3A13&track_length_m=5809");
    expect(trackQuery("f1_25", "f1:13", null)).toBe("game=f1_25&track_id=f1%3A13");
  });

  it("drops physics windows that learned braking already covers, and titles the rest as estimates", () => {
    const prior: BrakePrior = {
      tier: "physics_predicted",
      label: "braking estimate (physics)",
      length_m: 200,
      positional: false,
      caveat: "Not a braking point.",
      onset_error: { p90_abs_m: 70, stops: 10, layouts: 2 },
      windows: [
        { index: 0, tier: "physics_predicted", est_onset_m: 40, est_apex_m: 60, window_m: [30, 60], segments_m: [[30, 60]], uncertainty_m: 10, onset_error_p90_m: 70, est_entry_kph: 200, est_apex_kph: 90, direction: "left", turn: { label: "T1", name: null, voice_ok: true } },
        { index: 1, tier: "physics_predicted", est_onset_m: 140, est_apex_m: 160, window_m: [130, 160], segments_m: [[130, 160]], uncertainty_m: 10, onset_error_p90_m: 70, est_entry_kph: 200, est_apex_kph: 90, direction: null, turn: null },
      ],
    };
    const pieces = uncoveredPriorPieces(prior, [[45, 55]], 1);
    expect(pieces.map((p) => p.key)).toEqual(["1-0"]);
    expect(priorTitle(prior.windows[1]!, prior)).toBe("stop 1: heavy stop ahead (estimate; onset error p90 70 m; band starts 10 m early). Not a braking point.");
    const l = trackMapLayout({ model: { ...MODEL, centreline: [] }, outline, prior })!;
    expect(l.prior).toHaveLength(2); // no learned corners on an outline: nothing covers the windows
    expect(l.legend.map((t) => t.text)).toEqual(["braking estimate (physics): estimate, not a braking point"]);
  });
});

describe("map colours", () => {
  it("uses timing colours for sector status and neutral for unknown", () => {
    expect(sectorStatusColour("rec")).toBe("var(--pw-rec)");
    expect(sectorStatusColour("pb")).toBe("var(--pw-pb)");
    expect(sectorStatusColour("invalid")).toBe("var(--pw-faint)");
    expect(sectorStatusColour("neutral")).toBeNull();
    expect(sectorStatusColour("running")).toBeNull();
    expect(sectorStatusColour(null)).toBeNull();
  });

  it("is neutral within +-0.01 s for segment deltas (6.3)", () => {
    expect(segmentColour(-0.011)).toBe("var(--pw-ahead)");
    expect(segmentColour(-0.01)).toBe("var(--muted)");
    expect(segmentColour(0.01)).toBe("var(--muted)");
    expect(segmentColour(0.02)).toBe("var(--pw-behind)");
    expect(segmentColour(null)).toBe("var(--pw-faint)");
  });
});
