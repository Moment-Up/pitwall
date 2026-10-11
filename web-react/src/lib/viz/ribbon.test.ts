import { describe, expect, it } from "vitest";
import { ribbon } from "../drive/ribbon";
import { fixture, snap } from "../drive/testkit";
import {
  LABEL_GAP_PX,
  RIBBON_PAD_X,
  carTrianglePath,
  cursorCorner,
  placeLabels,
  ribbonFromTrack,
  ribbonLayout,
  ribbonSignature,
  ribbonX,
  type RibbonLabel,
  type RibbonView,
} from "./ribbon";

const W = 1084; // Drive baseline width of the ribbon panel (spec 4.2)

/** Estimated text extents of drawn labels (13 px / 700: 8 px per character), for overlap checks. */
function extents(labels: RibbonLabel[]): [number, number][] {
  return labels.map((l) => {
    const w = l.text.length * 8;
    const x0 = l.anchor === "start" ? l.x : l.anchor === "end" ? l.x - w : l.x - w / 2;
    return [x0, x0 + w];
  });
}

describe("ribbonLayout (Drive, real Suzuka snapshot)", () => {
  const s = fixture("recorded-suzuka-on-track-brake-ahead");
  const view = ribbon(s, "on_track", "T7");
  const l = ribbonLayout(view, { width: W, height: 56 });

  it("uses the mockup's geometry: 12 px padding, band from y 22, 24 px tall, labels 6 px above it", () => {
    expect(l.x0).toBe(RIBBON_PAD_X);
    expect(l.x1).toBe(W - RIBBON_PAD_X);
    expect(l.top).toBe(22);
    expect(l.bandH).toBe(24);
    expect(l.labelY).toBe(16);
    expect(l.plain).toBe(false);
  });

  it("draws three neutral sector bands with a 2 px gap, labelled S1 S2 S3 in the band ink", () => {
    expect(l.bands.map((b) => b.label)).toEqual(["S1", "S2", "S3"]);
    expect(l.bands.map((b) => b.fill)).toEqual(["var(--pw-sector-1)", "var(--pw-sector-2)", "var(--pw-sector-3)"]);
    const s2 = l.bands[1]!;
    expect(s2.x).toBeCloseTo(ribbonX(2225.65 / 5809, l.x0, l.x1));
    expect(l.bands[0]!.x + l.bands[0]!.w).toBeCloseTo(s2.x - 2);
  });

  it("labels the next corner (official T11, strong) and only it, ticks every corner, one notch, one focus dot", () => {
    expect(l.ticks).toHaveLength(11);
    expect(l.ticks.filter((t) => t.strong)).toHaveLength(1);
    expect(l.labels).toEqual([{ x: expect.any(Number), text: "T11", anchor: "middle", strong: true }]);
    expect(l.labels[0]!.x).toBeCloseTo(ribbonX(2948 / 5809, l.x0, l.x1));
    expect(l.notches).toHaveLength(1);
    expect(l.notches[0]).toBeCloseTo(ribbonX(2826.3 / 5809, l.x0, l.x1));
    expect(l.focusDots).toHaveLength(1);
    expect(l.drs).toEqual([]);
    expect(l.yellow).toEqual([]);
  });

  it("drops the brake notches when cues are off (Compare)", () => {
    expect(ribbonLayout(view, { width: W, height: 56, cues: false }).notches).toEqual([]);
  });

  it("hatches a live yellow zone over the band", () => {
    const y = ribbonLayout(ribbon(fixture("recorded-suzuka-yellow-flag"), "on_track"), { width: W, height: 56 });
    expect(y.yellow).toHaveLength(1);
    expect(y.yellow[0]!.x).toBeCloseTo(ribbonX(858.65 / 5809, y.x0, y.x1));
  });

  it("is one empty band without telemetry, and one plain band without a skeleton", () => {
    const empty = ribbonLayout(ribbon(null, "no_data"), { width: W, height: 56 });
    expect(empty.plain).toBe(true);
    expect(empty.bands).toHaveLength(1);
    expect(empty.bands[0]).toMatchObject({ x: 12, w: W - 24, label: null, fill: "var(--surface-secondary)" });
    expect(empty.ticks).toEqual([]);
    const bare = ribbonLayout(ribbon(snap(), "on_track"), { width: W, height: 56 });
    expect(bare.plain).toBe(true);
    expect(bare.bands).toHaveLength(1);
  });

  it("uses Compare's compact rows at 44 px (band from y 18) and lines up with a chart's plot inset", () => {
    const c = ribbonLayout(view, { width: 700, height: 44, inset: { left: 44, right: 8 } });
    expect(c.top).toBe(18);
    expect(c.bandH).toBe(16);
    expect(c.x0).toBe(44);
    expect(c.x1).toBe(692);
    expect(ribbonX(0, c.x0, c.x1)).toBe(44);
    expect(ribbonX(1, c.x0, c.x1)).toBe(692);
  });
});

describe("corner labels ([critic] 34 px rule, 6.5)", () => {
  it("with every label on (Compare), skips labels that would collide: Silverstone's T10-13 pair prints once", () => {
    const s = fixture("recorded-d246-silverstone-long-label");
    const view = ribbon(s, "on_track", null);
    const l = ribbonLayout(view, { width: 700, height: 44, allLabels: true, cues: false });
    const texts = l.labels.map((x) => x.text);
    expect(texts.filter((t) => t === "T10-13")).toHaveLength(1);
    const ex = extents(l.labels);
    for (let i = 1; i < l.labels.length; i++) {
      expect(l.labels[i]!.x - l.labels[i - 1]!.x).toBeGreaterThanOrEqual(LABEL_GAP_PX - 8); // edge anchors shift by <= 4 px
      expect(ex[i]![0]).toBeGreaterThanOrEqual(ex[i - 1]![1]); // never overlapping text
    }
  });

  it("always draws the next, focus and cursor corners, even when they crowd each other", () => {
    const view: RibbonView = {
      lengthM: 1000,
      sectors: [],
      corners: [
        { at: 0.5, label: "T5", name: "a", next: true, focus: false, showLabel: true },
        { at: 0.51, label: "T6", name: "b", next: false, focus: true, showLabel: true },
        { at: 0.52, label: "T7", name: "c", next: false, focus: false, showLabel: false },
        { at: 0.53, label: "T8", name: "d", next: false, focus: false, showLabel: false },
      ],
      cueNotches: [],
      drs: [],
      yellow: [],
      car: null,
      empty: false,
    };
    const l = ribbonLayout(view, { width: 1000, height: 56, allLabels: true, cursor: 0.53 });
    expect(l.labels.map((x) => x.text)).toEqual(["T5", "T6", "T8"]); // T7 has no room and no priority
    expect(cursorCorner(view.corners, 0.531)).toBe("d");
    expect(cursorCorner(view.corners, null)).toBeNull();
  });

  it("keeps labels inside the SVG at both ends", () => {
    const x = (f: number) => 12 + f * 976;
    const corners = [
      { at: 0, label: "T1-2", name: "a", next: true, focus: false, showLabel: true },
      { at: 1, label: "T18-19", name: "b", next: false, focus: true, showLabel: true },
    ];
    const labels = placeLabels(corners, x, 1000, { allLabels: false, cursorName: null });
    expect(labels[0]).toMatchObject({ anchor: "start" });
    expect(labels[1]).toMatchObject({ anchor: "end" });
    for (const [a, b] of extents(labels)) {
      expect(a).toBeGreaterThanOrEqual(0);
      expect(b).toBeLessThanOrEqual(1000);
    }
  });
});

describe("ribbon car and memo key", () => {
  it("draws the car as a triangle under the band with its tip inside it", () => {
    expect(carTrianglePath({ top: 22, bandH: 24 })).toBe("M-8 55 L8 55 L0 41 Z");
  });

  it("keeps the same signature when only the car moves, and changes it when a static part does", () => {
    const a = fixture("recorded-suzuka-on-track-brake-ahead");
    const b = structuredClone(a);
    b.frame!.lap_distance_m = 2600;
    const va = ribbon(a, "on_track", "T7");
    const vb = ribbon(b, "on_track", "T7");
    expect(va.car).not.toBe(vb.car);
    expect(ribbonSignature(va)).toBe(ribbonSignature(vb));
    expect(ribbonSignature(ribbon(a, "on_track", "T8"))).not.toBe(ribbonSignature(va));
  });
});

describe("ribbonFromTrack (stored sessions)", () => {
  const s = fixture("recorded-suzuka-on-track-brake-ahead");

  it("builds the same sectors and corners as the live view, with no car, cues or yellow", () => {
    const v = ribbonFromTrack({ skeleton: s.skeleton, model: s.track_model, focus: ["T7"], next: "T7" });
    const live = ribbon(s, "on_track", "T7");
    expect(v.lengthM).toBe(5809);
    expect(v.sectors).toEqual(live.sectors);
    expect(v.corners).toEqual(live.corners);
    expect(v.car).toBeNull();
    expect(v.cueNotches).toEqual([]);
    expect(v.yellow).toEqual([]);
    expect(v.empty).toBe(false);
  });

  it("never draws a yellow zone even when the stored skeleton says yellow (flags are live state)", () => {
    const sk = structuredClone(s.skeleton!);
    sk.marshal_zones = sk.marshal_zones!.map((z) => ({ ...z, flag: "yellow" }));
    expect(ribbonFromTrack({ skeleton: sk, model: s.track_model }).yellow).toEqual([]);
  });

  it("falls back to the session's lap length, and is empty when no length is known", () => {
    const v = ribbonFromTrack({ model: s.track_model, lengthM: 5809 });
    expect(v.sectors).toEqual([]);
    expect(v.corners).toHaveLength(11);
    expect(ribbonFromTrack({}).empty).toBe(true);
  });

  it("splits a DRS zone through the line into its pieces", () => {
    const sk = structuredClone(s.skeleton!);
    sk.drs_zones = [
      {
        kind: "drs",
        index: 0,
        game_number: 1,
        lap_order: 1,
        start_m: 5600,
        end_m: 200,
        length_m: 409,
        start_frac: 0.96,
        end_frac: 0.03,
        wraps: true,
        segments_m: [
          [5600, 5809],
          [0, 200],
        ],
        flag: null,
      },
    ];
    const v = ribbonFromTrack({ skeleton: sk, model: s.track_model });
    expect(v.drs).toHaveLength(2);
    expect(v.drs[0]![1]).toBe(1);
    expect(v.drs[1]![0]).toBe(0);
  });
});
