// Drive › Track view model (design spec 5.2) from the Drive fixtures.
import { describe, expect, it } from "vitest";
import { driveModel } from "../../../lib/drive/model";
import { FIXTURES, fixture, newestT, snap } from "../../../lib/drive/testkit";
import type { SnapshotNext } from "../../../lib/drive/types";
import { catalogue, entry } from "../../../lib/game-testkit";
import { trackView } from "./view";

function view(s: SnapshotNext | null, opts: { connected?: boolean; simple?: boolean } = {}) {
  const m = driveModel({ snap: s, connected: opts.connected ?? true, nowS: newestT(s) + 1, driver: null });
  return trackView(s, m, opts.simple ?? false);
}

describe("corner list", () => {
  it("every corner in lap order with its official label, name, direction and focus", () => {
    const s = fixture("recorded-d246-suzuka-on-track-brake-ahead");
    const v = view(s);
    expect(v.rows.map((r) => r.name)).toEqual(["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9", "T10", "T11"]);
    const t2 = v.rows.find((r) => r.name === "T2")!;
    expect(t2).toMatchObject({ label: "T3-5", title: "S Curve", direction: "right" });
    const t7 = v.rows.find((r) => r.name === "T7")!;
    expect(t7.focus).toBe(true);
    expect(t7.label).toBe("T11");
    expect(v.caption).toBe("11 corners · official names");
  });

  it("the sheet's long name when there is no official short name, never the label twice", () => {
    const s = fixture("recorded-d246-suzuka-on-track-brake-ahead");
    const t1 = view(s).rows.find((r) => r.name === "T1")!;
    expect(t1.label).toBe("T2");
    expect(t1.title).toBe("Turn 2");
  });

  it("what the coach said on the last lap, verbatim: D6's per-corner point, full text", () => {
    const s = fixture("recorded-d246-suzuka-on-track-brake-ahead");
    const t7 = view(s).rows.find((r) => r.name === "T7")!;
    expect(t7.note).toEqual({ text: s.coach!.by_corner.T7!.text, lap: 4, good: false });
    // Plain-wording profiles read text_simple (D6 says which profile is seated; its flag wins over the device's).
    s.coach!.simple_wording = true;
    const simple = view(s).rows.find((r) => r.name === "T7")!;
    expect(simple.note?.text).toBe(s.coach!.by_corner.T7!.text_simple);
  });

  it("before D6: the top observation at that corner", () => {
    const s = fixture("recorded-suzuka-on-track-brake-ahead");
    const v = view(s);
    for (const r of v.rows) {
      const top = s.observations
        .filter((o) => o.corner === r.name && o.kind !== "incident")
        .sort((a, b) => b.priority - a.priority)[0];
      expect(r.note?.text ?? null, r.name).toBe(top?.text ?? null);
    }
  });

  it("marks the car's next corner; stale or offline marks none", () => {
    const s = fixture("recorded-d246-suzuka-on-track-brake-ahead");
    const v = view(s);
    expect(v.liveCorner).toBe("T7");
    expect(v.rows.filter((r) => r.live).map((r) => [r.name, r.live])).toEqual([["T7", "next"]]);
    expect(view(s, { connected: false }).liveCorner).toBeNull();
    expect(view(fixture("recorded-austria-stale")).rows.some((r) => r.live)).toBe(false);
  });

  it("See it on the lap: Compare at the corner's apex, last compared lap against the reference", () => {
    const s = fixture("recorded-d246-suzuka-on-track-brake-ahead");
    const t7 = view(s).rows.find((r) => r.name === "T7")!;
    expect(t7.compareHref).toBe(`/review/sessions/${s.session_id}/compare?ref=5&lap=6&at=2948`);
  });

  it("no Compare link without a reference or a session", () => {
    const s = fixture("recorded-d246-silverstone-long-label"); // no reference yet
    expect(view(s).rows.every((r) => r.compareHref === null)).toBe(true);
  });

  it("no model: an empty list that says why", () => {
    const v = view(fixture("recorded-suzuka-grid-before-start"));
    expect(v.rows).toEqual([]);
    expect(v.empty).toBe("The corners appear after your first clean lap.");
    expect(v.caption).toBe("Learning the track");
    expect(view(null).rows).toEqual([]);
  });

  it("direction null (complexes) has no word", () => {
    const s = snap({
      track_model: {
        game: "f1_25",
        track_id: "x",
        track_name: "X",
        length_m: 5000,
        version: 1,
        n_laps: 1,
        centreline: [],
        corners: [
          { name: "T1", apex_m: 500, entry_m: 400, exit_m: 600, seg_start_m: 300, seg_end_m: 700, direction: null, ref_min_speed_kph: 100 },
        ],
      },
    });
    expect(view(s).rows[0]!.direction).toBeNull();
    expect(view(s).rows[0]!.title).toBeNull();
  });

  it("every fixture: labels are never empty and notes are verbatim backend texts", () => {
    for (const name of FIXTURES) {
      const s = fixture(name);
      const texts = new Set(
        [...s.observations, ...Object.values(s.coach?.by_corner ?? {})].flatMap((o) => [o.text, o.text_simple].filter(Boolean)),
      );
      for (const r of view(s).rows) {
        expect(r.label, name).not.toBe("");
        if (r.note) expect(texts.has(r.note.text), `${name} ${r.name}`).toBe(true);
      }
    }
  });
});

describe("what the game sends (game selection 5.5)", () => {
  const CAT = catalogue();
  const noModel = (s: SnapshotNext): SnapshotNext => ({ ...s, track_model: null });

  it("an estimated track map says why the corners come later, in the server's words", () => {
    const s = noModel(fixture("recorded-live-api-gt7-stale"));
    const m = driveModel({ snap: s, connected: true, nowS: newestT(s) + 1, driver: null });
    const v = trackView(s, m, false, entry("gt7:ps5", CAT));
    expect(v.empty).toBe(
      "The corners appear after your first clean lap. GT7 sends no lap distance: Pitwall works it out from speed (about 1 % drift per lap).",
    );
    expect(v.note).toBeNull();
  });

  it("F1 25: the outline note while there is no model yet, the usual empty text", () => {
    const f1 = entry("f1_25:ps5", CAT);
    const s = noModel(fixture("recorded-d246-suzuka-on-track-brake-ahead"));
    const m = driveModel({ snap: s, connected: true, nowS: newestT(s) + 1, driver: null });
    const v = trackView(s, m, false, f1);
    expect(v.empty).toBe("The corners appear after your first clean lap.");
    expect(v.note).toBe(f1.features.find((f) => f.id === "track_map")!.note);
    // with a model: no note, the corners
    const full = fixture("recorded-d246-suzuka-on-track-brake-ahead");
    expect(trackView(full, m, false, f1).note).toBeNull();
  });

  it("without a game: as before", () => {
    const v = view(snap());
    expect(v.empty).toBe("The corners appear after your first clean lap.");
    expect(v.note).toBeNull();
  });
});
