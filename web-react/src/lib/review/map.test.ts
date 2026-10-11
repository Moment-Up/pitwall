import { describe, expect, it } from "vitest";
import { cornerIdentity } from "./corners";
import { askPath, comparePath, progressPath, tabPath, workOnQuestion } from "./links";
import { CENTRELINE_STEP_M, deltaColourVar, lapPath, mapGeometry, pointAt, spacedLabels, stretchPath, viewBox } from "./map";
import { fixtures } from "./testkit";

describe("review map geometry", () => {
  const model = fixtures.austriaAnalysis().track_model!;
  const g = mapGeometry(model.centreline)!;

  it("projects the learned centreline (x, -z) every 5 m", () => {
    expect(g.pts.length).toBe(model.centreline.length);
    expect(g.pts[0]).toEqual([model.centreline[0]![0], -model.centreline[0]![1]]);
    expect(g.lengthM).toBe((model.centreline.length - 1) * CENTRELINE_STEP_M);
    expect(Math.abs(g.lengthM - model.length_m)).toBeLessThan(20);
    expect(viewBox(g).split(" ")).toHaveLength(4);
  });

  it("draws the lap closed and a corner's stretch from entry to exit", () => {
    expect(lapPath(g).endsWith("Z")).toBe(true);
    const t1 = cornerIdentity(model, "T1");
    const p = stretchPath(g, t1.entryM!, t1.exitM!);
    expect(p.startsWith("M")).toBe(true);
    expect(p.split("L").length).toBeGreaterThan(5);
  });

  it("wraps a stretch past the line", () => {
    const p = stretchPath(g, g.lengthM - 20, 20);
    expect(p.startsWith("M")).toBe(true);
    expect(p).not.toContain("NaN");
    expect((p.match(/M/g) ?? []).length).toBe(1);
  });

  it("no centreline, no map", () => {
    expect(mapGeometry(null)).toBeNull();
    expect(mapGeometry([[0, 0], [1, 1]])).toBeNull();
    expect(pointAt(g, Number.NaN)).toBeNull();
    expect(stretchPath(g, Number.NaN, 10)).toBe("");
  });

  it("colours corners green gained, red lost, neutral within ±0.01 s", () => {
    expect(deltaColourVar(0.2)).toBe("var(--pw-behind)");
    expect(deltaColourVar(-0.2)).toBe("var(--pw-ahead)");
    expect(deltaColourVar(0.005)).toBe("var(--muted)");
    expect(deltaColourVar(null)).toBe("var(--pw-faint)");
  });
});

describe("corner identity", () => {
  const model = fixtures.austriaAnalysis().track_model!;

  it("official label and name from the track sheet, else the learned name", () => {
    expect(cornerIdentity(model, "T1")).toMatchObject({ label: "T1", name: "Niki Lauda Kurve", full: "T1 Niki Lauda Kurve", spoken: "Niki Lauda Kurve" });
    expect(cornerIdentity(model, "T2")).toMatchObject({ label: "T3", name: null, full: "T3", spoken: "T3", apexM: 1413 });
    expect(cornerIdentity(null, "T9", "T11")).toMatchObject({ label: "T11", apexM: null });
    expect(cornerIdentity(null, "T9").label).toBe("T9");
  });
});

describe("links", () => {
  it("Compare with reference, lap and distance in the hash query", () => {
    expect(comparePath("abc", { ref: 52, lap: 59, at: 2726.4 })).toBe("/review/sessions/abc/compare?ref=52&lap=59&at=2726");
    expect(comparePath("abc", { ref: null, lap: 3 })).toBe("/review/sessions/abc/compare?lap=3");
    expect(comparePath("abc")).toBe("/review/sessions/abc/compare");
  });

  it("Ask pre-filled, Progress scoped, tabs named", () => {
    expect(askPath("abc", workOnQuestion("Stowe"))).toBe(
      "/review/sessions/abc/ask?q=Why+am+I+losing+time+at+Stowe%3F",
    );
    expect(askPath("abc")).toBe("/review/sessions/abc/ask");
    expect(progressPath({ driver: 2, track: "f1:7", car: null })).toBe("/review/progress?driver=2&track=f1%3A7");
    expect(tabPath("abc", "summary")).toBe("/review/sessions/abc");
    expect(tabPath("abc", "laps")).toBe("/review/sessions/abc/laps");
  });
});

describe("map labels", () => {
  it("skips a label too close to one already placed", () => {
    const g = mapGeometry([[0, 0], [100, 0], [200, 0], [300, 0]].map(([x, z]) => [x!, z!] as [number, number]))!;
    const labels = spacedLabels(
      g,
      [
        { key: "a", text: "T1", atM: 0 },
        { key: "b", text: "T2", atM: 2 },
        { key: "c", text: "T3", atM: 10 },
        { key: "d", text: "T4", atM: null },
      ],
      50,
    );
    expect(labels.map((l) => l.text)).toEqual(["T1", "T3"]);
  });
});
