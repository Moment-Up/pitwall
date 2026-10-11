import { describe, expect, it } from "vitest";
import { fixture } from "../drive/testkit";
import type { TrackModelNext } from "../drive/types";
import {
  fieldLinePoints,
  fieldReferenceText,
  fieldZoneTitle,
  knowledgeMatches,
  type KnowledgeZone,
  type TrackKnowledge,
} from "./knowledge";
import type { BrakePrior, TrackOutline } from "./outline";
import {
  fullPath,
  knowledgeSignature,
  mapGeometry,
  pathBetween,
  pointAt,
  skeletonSignature,
  trackMapLayout,
  trackModelSignature,
} from "./track-map";

// Real data for the model-line cases: the recorded Suzuka replay (src/test/fixtures/drive, lane DL). The knowledge
// payloads below are TEST DATA in the wire shape of core/track_knowledge.py TrackKnowledge.to_dict() (no recorded
// capture with an AI-field layer exists yet): a square loop, 40 points 5 m apart, never presented as a real track.
const S = fixture("recorded-suzuka-on-track-brake-ahead");
const MODEL = S.track_model as TrackModelNext;
const SK = S.skeleton!;

function square(n = 40, side = 100): [number, number][] {
  const pts: [number, number][] = [];
  const per = n / 4;
  for (let i = 0; i < n; i++) {
    const k = Math.floor(i / per);
    const t = (i % per) / per;
    pts.push(k === 0 ? [t * side, 0] : k === 1 ? [side, t * side] : k === 2 ? [side - t * side, side] : [0, side - t * side]);
  }
  return pts;
}

function zone(key: string, onset: number, slowest: number, over: Partial<KnowledgeZone> = {}): KnowledgeZone {
  return {
    key,
    label: key.startsWith("T") ? key : null,
    onset_m: onset,
    heads_up_m: null,
    entry_speed_kph: 250,
    min_speed_kph: 90,
    min_speed_m: slowest,
    support: 10,
    cars: 4,
    superseded_by: null,
    tier: "field_observed",
    ...over,
  };
}

/** Test knowledge on the square: the field's line with a gap at points 12-14 (60-70 m), one field corner, and four
 * braking zones (one below the heads-up support, one braking through the line, one covered by a learned corner). */
function knowledge(over: Partial<TrackKnowledge> = {}): TrackKnowledge {
  const points = square().map(([x, z], i): [number | null, number | null] => (i >= 12 && i < 15 ? [null, null] : [x, z]));
  return {
    game: "f1_25",
    track_id: "f1:13",
    track_name: "Test loop",
    track_length_m: 200,
    session_uid: "s1",
    synthetic: false,
    version: 3,
    positions: "field_observed",
    layers: {
      L0b: {
        tier: "field_observed",
        available: true,
        version: 2,
        car_laps: 140,
        cars: 12,
        coverage: 0.93,
        braking_zones: 4,
        heads_up: 2,
        min_support: 3,
      },
    },
    corners: [
      { key: "F1", name: "F1", label: "T1", text: { short: "T1", long: "Turn 1", voice: null }, apex_m: 55, tier: "field_observed" },
      { key: "F2", name: "F2", label: null, text: null, apex_m: null, tier: "field_observed" },
    ],
    braking_zones: [
      zone("T1", 40, 55, { heads_up_m: 30 }),
      zone("F2", 140, 160, { heads_up_m: 130, support: 2 }),
      zone("T3", 190, 10, { heads_up_m: 180 }),
      zone("T4", 100, 110, { heads_up_m: 90, superseded_by: "learned" }),
    ],
    line: { tier: "field_observed", source: "field", step_m: 5, points },
    ...over,
  };
}

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

const bare: TrackModelNext = { ...MODEL, game: "f1_25", track_id: "f1:13", centreline: [] };

describe("a line with gaps (the AI field's, before the field has driven everywhere)", () => {
  const g = mapGeometry(fieldLinePoints(knowledge()), 5, 200)!;

  it("keeps unknown points in place, so lap distance still indexes the line", () => {
    expect(g.pts).toHaveLength(40);
    expect(g.complete).toBe(false);
    expect(pointAt(g, 60)).toBeNull(); // in the gap
    expect(pointAt(g, 75)).toEqual([100, -50]);
  });

  it("lifts the pen across the gap and never closes the line through it", () => {
    expect(fullPath(g).match(/M/g)).toHaveLength(2);
    expect(fullPath(g).endsWith("Z")).toBe(false);
    expect(pathBetween(g, 50, 90).match(/M/g)).toHaveLength(2);
    expect(fullPath(mapGeometry(square(), 5, 200)!).endsWith("Z")).toBe(true);
  });

  it("reads only the field's own line (a learned line in the knowledge is the model's)", () => {
    expect(fieldLinePoints(knowledge()).filter((p) => p === null)).toHaveLength(3);
    const learned = knowledge({ line: { tier: "learned", step_m: 5, points: square() } });
    expect(fieldLinePoints(learned)).toEqual([]);
    expect(fieldLinePoints(null)).toEqual([]);
  });
});

describe("trackMapLayout with track knowledge", () => {
  it("draws the AI field's line (dashed, labelled an AI reference) ahead of the outline while the model has none", () => {
    const l = trackMapLayout({ model: bare, outline, knowledge: knowledge(), cueTargetsM: [45] })!;
    expect(l.source).toBe("field");
    expect(l.sourceLabel?.text).toBe("AI field reference");
    expect(l.lines).toHaveLength(1);
    expect(l.lines[0]!.dash).toBeDefined();
    expect(l.lines[0]!.title).toBe("AI field median line (140 car-laps): an AI reference, not your line");
    expect(l.corners).toEqual([]); // learned corners need the learned line
    expect(l.fieldCorners.map((c) => c.label)).toEqual(["T1"]); // F2 has no apex: not drawn
    expect(l.fieldCorners[0]!.text?.text).toBe("T1");
    expect(l.notches).toEqual([]); // cue notches only on the driver's own line
    // without knowledge the outline is next
    expect(trackMapLayout({ model: bare, outline })!.source).toBe("outline");
  });

  it("dots the field's braking zones no learned corner covers, with heads-up points only from enough support", () => {
    const l = trackMapLayout({ model: bare, knowledge: knowledge() })!;
    expect(l.field.map((z) => z.key)).toEqual(["T1-0", "F2-1", "T3-2"]); // T4 is superseded by a learned corner
    expect(l.field[0]!.headsUp).toEqual(pointAt(l.geom, 30));
    expect(l.field[1]!.headsUp).toBeNull(); // 2 car-laps < min_support 3
    expect(l.field[2]!.d.match(/M/g)!.length).toBeGreaterThanOrEqual(2); // brakes through the line: two pieces
    expect(l.field[0]!.title).toBe("T1: AI field brakes from 40 m (10 car-laps, 4 cars), 250 → 90 km/h. AI reference, not your braking point.");
    expect(l.legend.map((t) => t.text)).toEqual(["AI field braking (dotted): a reference only"]);
    // unknown min_support: no heads-up point is claimed
    const k = knowledge();
    delete (k.layers as { L0b?: unknown }).L0b;
    expect(trackMapLayout({ model: bare, knowledge: k })!.field.every((z) => z.headsUp === null)).toBe(true);
  });

  it("keeps the learned line authoritative and maps the field's game metres onto it by lap fraction", () => {
    const L = MODEL.length_m * 1.01;
    const k = knowledge({
      game: MODEL.game,
      track_id: MODEL.track_id,
      track_length_m: L,
      line: null,
      braking_zones: [zone("F9", L * 0.5, L * 0.52, { heads_up_m: L * 0.48 })],
    });
    const l = trackMapLayout({ model: MODEL, skeleton: SK, knowledge: k })!;
    expect(l.source).toBe("model");
    expect(l.sourceLabel).toBeNull();
    expect(l.corners.length).toBeGreaterThan(0);
    expect(l.fieldCorners).toEqual([]);
    expect(l.field).toHaveLength(1);
    expect(l.field[0]!.headsUp).toEqual(pointAt(l.geom, MODEL.length_m * 0.48));
  });

  it("ignores knowledge for another track than the model's", () => {
    expect(knowledgeMatches({ track_id: "f1:99" }, knowledge())).toBe(false);
    expect(knowledgeMatches({ track_id: "f1:13", game: "ac" }, knowledge())).toBe(false);
    expect(knowledgeMatches(null, knowledge())).toBe(true);
    const l = trackMapLayout({ model: { ...bare, track_id: "f1:99" }, outline, knowledge: knowledge() })!;
    expect(l.source).toBe("outline");
    expect(l.field).toEqual([]);
  });

  it("drops physics windows the field's measured braking covers, and lists both legends", () => {
    const prior: BrakePrior = {
      tier: "physics_predicted",
      label: "braking estimate (physics)",
      length_m: 200,
      positional: false,
      caveat: "Not a braking point.",
      onset_error: { p90_abs_m: 70, stops: 10, layouts: 2 },
      windows: [
        { index: 0, tier: "physics_predicted", est_onset_m: 40, est_apex_m: 60, window_m: [30, 60], segments_m: [[30, 60]], uncertainty_m: 10, onset_error_p90_m: 70, est_entry_kph: 200, est_apex_kph: 90, direction: null, turn: null },
        { index: 1, tier: "physics_predicted", est_onset_m: 85, est_apex_m: 95, window_m: [80, 95], segments_m: [[80, 95]], uncertainty_m: 10, onset_error_p90_m: 70, est_entry_kph: 200, est_apex_kph: 90, direction: null, turn: null },
      ],
    };
    const l = trackMapLayout({ model: bare, knowledge: knowledge(), prior })!;
    expect(l.prior.map((p) => p.key)).toEqual(["1-0"]);
    expect(l.legend.map((t) => t.text)).toEqual([
      "braking estimate (physics): estimate, not a braking point",
      "AI field braking (dotted): a reference only",
    ]);
    expect(l.legend[1]!.y).toBeGreaterThan(l.legend[0]!.y);
    expect(l.viewBox.y + l.viewBox.h).toBeGreaterThan(l.legend[1]!.y);
  });
});

describe("knowledge copy", () => {
  it("omits unknown speeds instead of printing 0", () => {
    const z = zone("zone@1234", 1234, 1300, { label: null, entry_speed_kph: null, support: 1200 });
    expect(fieldZoneTitle(z)).toBe("zone@1234: AI field brakes from 1\u202f234 m (1\u202f200 car-laps, 4 cars). AI reference, not your braking point.");
  });

  it("says what the AI reference is built from, only while the field layer is available", () => {
    expect(fieldReferenceText(knowledge())).toBe("AI reference: 12 cars, 140 car-laps, 2 heads-ups");
    const off = knowledge();
    off.layers.L0b!.available = false;
    expect(fieldReferenceText(off)).toBeNull();
    expect(fieldReferenceText(null)).toBeNull();
  });
});

describe("memo signatures (the static parts arrive as new objects every 5 s)", () => {
  it("is equal for an equal track model and changes with what the map draws", () => {
    const sig = trackModelSignature(MODEL);
    expect(trackModelSignature(structuredClone(MODEL))).toBe(sig);
    expect(trackModelSignature({ ...MODEL, version: MODEL.version + 1 })).not.toBe(sig);
    const moved = structuredClone(MODEL);
    moved.corners[0]!.apex_m += 5;
    expect(trackModelSignature(moved)).not.toBe(sig);
    const renamed = structuredClone(MODEL);
    const first = Object.keys(renamed.corner_text ?? {})[0]!;
    renamed.corner_text![first]!.short = "T99";
    expect(trackModelSignature(renamed)).not.toBe(sig);
    expect(trackModelSignature(null)).toBe("");
  });

  it("is equal for an equal skeleton and changes with a sector or a marshal flag", () => {
    const sig = skeletonSignature(SK);
    expect(skeletonSignature(structuredClone(SK))).toBe(sig);
    const flagged = structuredClone(SK);
    flagged.marshal_zones![0]!.flag = "yellow";
    expect(skeletonSignature(flagged)).not.toBe(sig);
    const sector = structuredClone(SK);
    sector.sectors![1]!.start_m += 10;
    expect(skeletonSignature(sector)).not.toBe(sig);
  });

  it("follows the knowledge resolver's version", () => {
    const k = knowledge();
    expect(knowledgeSignature(structuredClone(k))).toBe(knowledgeSignature(k));
    expect(knowledgeSignature({ ...k, version: 4 })).not.toBe(knowledgeSignature(k));
    expect(knowledgeSignature(null)).toBe("");
  });
});
