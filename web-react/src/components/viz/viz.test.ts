// Render tests for the Drive-safe visualisation components (server-rendered to static markup in plain node: no DOM
// library). The Pro chart wrappers are covered through their pure data shaping (lib/viz/charts.test.ts): Recharts'
// ResponsiveContainer draws nothing before it can measure.
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ribbon } from "../../lib/drive/ribbon";
import { fixture } from "../../lib/drive/testkit";
import { ribbonX } from "../../lib/viz/ribbon";
import type { TrackKnowledge } from "../../lib/viz/knowledge";
import type { TrackOutline } from "../../lib/viz/outline";
import { LapRibbon, LiveTrace, TrackMap } from "./index";

function html<P extends object>(c: ComponentType<P>, props: P): string {
  return renderToStaticMarkup(createElement(c as ComponentType<object>, props));
}

const S = fixture("recorded-suzuka-on-track-brake-ahead");

describe("LapRibbon", () => {
  it("draws the sectors, the next corner's official label, the brake notch and the car (moved by transform)", () => {
    const view = ribbon(S, "on_track", "T7");
    const m = html(LapRibbon, { ribbon: view, width: 1084 });
    expect(m).toContain('role="img"');
    expect(m).toContain('aria-label="Lap ribbon, next corner T11"');
    expect(m).toContain('viewBox="0 0 1084 56"');
    for (const s of [">S1<", ">S2<", ">S3<", ">T11<"]) expect(m).toContain(s);
    expect(m).toContain('fill="var(--pw-brake)"');
    const x = ribbonX(view.car!, 12, 1072).toFixed(1);
    expect(m).toContain(`transform="translate(${x} 0)"`);
    expect(m).toContain('d="M-8 55 L8 55 L0 41 Z"');
  });

  it("hides the car when the state hides it, and is one empty band without telemetry", () => {
    expect(html(LapRibbon, { ribbon: ribbon(S, "stale", "T7"), width: 1084 })).not.toContain("data-car");
    const empty = html(LapRibbon, { ribbon: ribbon(null, "no_data"), width: 600 });
    expect(empty.match(/<rect/g)).toHaveLength(1);
    expect(empty).not.toContain("<text");
  });

  it("hatches a live yellow zone with its own pattern id, and draws Compare's cursor", () => {
    const m = html(LapRibbon, { ribbon: ribbon(fixture("recorded-suzuka-yellow-flag"), "on_track"), width: 800, cursor: 0.5, height: 44 });
    const id = /<pattern id="([^"]+)"/.exec(m)?.[1];
    expect(id).toMatch(/^pw-ribbon-/);
    expect(m).toContain(`fill="url(#${id})"`);
    expect(m).toContain('stroke="var(--accent)"');
  });
});

describe("TrackMap", () => {
  it("draws the learned circuit with official labels, focus ring and the car at its ground-plane position", () => {
    const m = html(TrackMap, {
      model: S.track_model,
      skeleton: S.skeleton,
      car: [-88.92, 148.55] as const,
      highlight: "T7",
      focus: ["T7"],
      flags: S.marshal_flags,
    });
    expect(m).toContain('aria-label="Track map of Suzuka"');
    expect(m).toContain(">T11<");
    expect(m).toContain(">S2<");
    expect(m).toContain('transform="translate(-88.9 -148.6)"');
    expect(m).toContain('stroke="var(--accent)"'); // the focus ring
    expect(m).not.toContain("var(--pw-flag-yellow)"); // no live yellow in this snapshot
  });

  it("says why there is no map instead of drawing a guess", () => {
    const m = html(TrackMap, { model: null, skeleton: S.skeleton });
    expect(m).toContain("The track map appears after your first clean lap.");
    expect(m).not.toContain("<svg");
  });

  it("labels the game outline seed and keeps its source to one muted line with a Source button", () => {
    const pts: [number, number][] = [];
    for (let i = 0; i < 40; i++) pts.push([Math.cos((i / 40) * 2 * Math.PI) * 300, Math.sin((i / 40) * 2 * Math.PI) * 200]);
    const outline: TrackOutline = {
      game: "f1_25",
      track_id: "f1:13",
      tier: "shipped_seed",
      label: "game outline (Pits n' Giggles)",
      attribution: "Track outline derived from Pits n' Giggles, MIT License.",
      length_m: 200,
      centreline_step_m: 5,
      centreline: pts,
      note: "Prior from recorded game data. Not your line and not a target.",
    };
    const m = html(TrackMap, { model: { ...S.track_model!, centreline: [] }, outline, height: "100%" });
    expect(m).toContain("game outline (Pits n&#x27; Giggles)");
    expect(m).toContain("stroke-dasharray");
    expect(m).toContain("Game outline ·");
    expect(m).toContain(">Source<");
    expect(m).toContain('aria-label="Source of the track outline"');
    // the full notice lives in the Sheet (mounted on first tap), not under the map
    expect(m).not.toContain("MIT License.");
    expect(m).not.toContain("Prior from recorded game data");
    expect(html(TrackMap, { model: { ...S.track_model!, centreline: [] }, outline, caption: false })).not.toContain(">Source<");
  });

  it("draws the AI field's line and braking as a labelled AI reference while the model has no line", () => {
    const n = 40;
    const points: [number | null, number | null][] = [];
    for (let i = 0; i < n; i++) points.push(i === 7 ? [null, null] : [Math.cos((i / n) * 2 * Math.PI) * 300, Math.sin((i / n) * 2 * Math.PI) * 200]);
    // test data in the TrackKnowledge wire shape (no recorded capture with an AI-field layer yet)
    const knowledge: TrackKnowledge = {
      game: S.track_model!.game,
      track_id: S.track_model!.track_id,
      track_name: "Suzuka",
      track_length_m: 200,
      session_uid: "s1",
      synthetic: false,
      version: 1,
      positions: "field_observed",
      layers: { L0b: { tier: "field_observed", available: true, version: 1, car_laps: 40, cars: 9, coverage: 0.97, braking_zones: 1, heads_up: 1, min_support: 3 } },
      corners: [],
      braking_zones: [
        { key: "T1", label: "T1", onset_m: 40, heads_up_m: 30, entry_speed_kph: 280, min_speed_kph: 95, min_speed_m: 60, support: 12, cars: 9, superseded_by: null, tier: "field_observed" },
      ],
      line: { tier: "field_observed", step_m: 5, points },
    };
    const m = html(TrackMap, { model: { ...S.track_model!, centreline: [] }, knowledge });
    expect(m).toContain('aria-label="Track map of Suzuka (AI field reference)"');
    expect(m).toContain(">AI field reference<");
    expect(m).toContain("AI field braking (dotted): a reference only");
    expect(m).toContain("AI reference, not your braking point.");
    expect(m.match(/data-heads-up/g)).toHaveLength(1); // a diamond, not an apex-like dot
    expect(m).toContain("<title>AI field median line (40 car-laps): an AI reference, not your line</title>");
    expect(m).not.toContain(">Source<");
  });
});

describe("LiveTrace", () => {
  it("renders a labelled canvas (drawn by a 10 Hz timer in the browser)", () => {
    const m = html(LiveTrace, { history: [], height: 180 });
    expect(m).toContain("<canvas");
    expect(m).toContain('aria-label="Speed, throttle and brake over the last 12 seconds"');
    expect(m).toContain("height:180px");
  });
});
