// Lane motivation on Drive (spec 9 Drive): the 6 s GOAL REACHED chip from the /ws/live note (timing, incident
// priority, another session's note), the Ready card's goal row and the Session complete card's 3 things (and the
// fallback while they load or when the server is older). Pure; plain node.
import { describe, expect, it } from "vitest";
import type { MotivationNote } from "../endpoints/motivation";
import type { DriveMotivation } from "../motivation/drive";
import { mfx } from "../motivation/testkit";
import { driveModel } from "./model";
import { CHIP_SHOW_S, chipText, driveState } from "./state";
import { driver, fixture, lap, newestT, snap, stopped } from "./testkit";

function note(over: Partial<MotivationNote> = {}): MotivationNote {
  return { ...mfx.note(), session_id: "s1", ...over };
}

const onTrack = () => snap({ laps: [lap(6, 91_512)] });

describe("GOAL REACHED chip (status slot, 6 s)", () => {
  it("shows for 6 s after the note of this session, never before or after", () => {
    const s = onTrack();
    const t = 1_791_669_000;
    const n = note({ t });
    expect(driveState(s, true, t + 1, null, n).overlays.chip).toEqual({ kind: "goal", ageS: 1 });
    expect(driveState(s, true, t + CHIP_SHOW_S, null, n).overlays.chip?.kind).toBe("goal");
    expect(driveState(s, true, t + CHIP_SHOW_S + 1, null, n).overlays.chip).toBeNull();
    expect(driveState(s, true, t - 1, null, n).overlays.chip).toEqual({ kind: "goal", ageS: 0 }); // clock skew
    expect(driveState(s, true, t - 3, null, n).overlays.chip).toBeNull();
    expect(chipText("goal")).toBe("GOAL REACHED");
  });

  it("only for the session on screen: a note from another seat or session is ignored", () => {
    const t = 1_791_669_000;
    expect(driveState(onTrack(), true, t + 1, null, note({ t, session_id: "other" })).overlays.chip).toBeNull();
    expect(driveState(onTrack(), true, t + 1, null, null).overlays.chip).toBeNull();
  });

  it("an incident within 6 s wins over the goal (the driver needs to know first)", () => {
    const t = 1_791_669_000;
    const s = snap({ events: [{ kind: "penalty", code: "PENA", session_time_s: 600, t: t - 2, player: true }] });
    expect(driveState(s, true, t + 1, null, note({ t })).overlays.chip?.kind).toBe("penalty");
    // the incident's 6 s are over, the goal's are not: the goal shows
    expect(driveState(s, true, t + 5, null, note({ t })).overlays.chip?.kind).toBe("goal");
  });

  it("the model words it in the status slot, and nothing else on track changes (P2)", () => {
    const t = 1_791_669_000;
    const motivation: DriveMotivation = { note: note({ t }), recap: null, status: "off" };
    const withNote = driveModel({ snap: onTrack(), connected: true, nowS: t + 1, driver: driver(), motivation });
    const without = driveModel({ snap: onTrack(), connected: true, nowS: t + 1, driver: driver() });
    expect(withNote.state).toBe("on_track");
    expect(withNote.status.chip).toEqual({ kind: "goal", text: "GOAL REACHED" });
    expect(without.status.chip).toBeNull();
    const { status: _a, overlays: _b, ...rest } = withNote;
    const { status: _c, overlays: _d, ...restWithout } = without;
    expect(rest).toEqual(restWithout);
  });
});

describe("Ready card: one goal row", () => {
  const between = () => fixture("edited-garage-between-runs");
  const recapFor = (sid: string | null) => ({ ...mfx.recap(), session_id: sid ?? "" });

  it("between runs, the goal in this scope with its progress", () => {
    const s = between();
    const m = driveModel({
      snap: s,
      connected: true,
      nowS: newestT(s) + 1,
      driver: driver(),
      motivation: { note: null, recap: recapFor(s.session_id), status: "ready" },
    });
    expect(m.state).toBe("garage");
    expect(m.ready?.goal).toMatchObject({ title: "Beat 1:10.000", reached: false, fraction: 0.4517 });
  });

  it("a goal reached on the last run: the celebration, from the note before the recap", () => {
    const s = between();
    const n = { ...mfx.note(), session_id: s.session_id as string };
    const m = driveModel({ snap: s, connected: true, nowS: newestT(s) + 1, driver: driver(), motivation: { note: n, recap: null, status: "loading" } });
    expect(m.ready?.goal).toMatchObject({ title: "Beat 1:10.000", reached: true, progressText: "Reached on lap 7" });
  });

  it("no motivation (older server, or nothing to show): no row", () => {
    const s = between();
    expect(driveModel({ snap: s, connected: true, nowS: newestT(s) + 1, driver: driver() }).ready?.goal).toBeNull();
    const err = driveModel({
      snap: s,
      connected: true,
      nowS: newestT(s) + 1,
      driver: driver(),
      motivation: { note: null, recap: null, status: "error" },
    });
    expect(err.ready?.goal).toBeNull();
  });
});

describe("Session complete card: 3 things", () => {
  const ended = () => stopped(fixture("recorded-d246-austria-session-ended"));

  it("with the recap: three things replace Work on / Went well; each fact once, at most 2 badges", () => {
    const s = ended();
    const recap = { ...mfx.recapReached(), session_id: s.session_id as string };
    const m = driveModel({ snap: s, connected: true, nowS: newestT(s) + 1, driver: driver(), motivation: { note: null, recap, status: "ready" } });
    expect(m.state).toBe("ended");
    // the new personal best leads (plan 2.6, acceptance B4); the goal reached keeps the Progress slot
    expect(m.ended?.things?.items.map((t) => t.heading)).toEqual(["Went well", "One to work on", "Goal reached"]);
    expect(m.ended?.thingsLoading).toBe(false);
    // three earned: "First goal reached" only repeats the Goal reached item (plan 2.6); the two newest of the rest
    expect(m.ended?.badges).toEqual(["First time under 1:10 at Austria in the Haas", "First time under 1:11 at Austria in the Haas"]);
    expect(m.ended?.facts).toEqual(["pb:52", "goal:4", "goals_reached"]);
    // the D6 points are still computed (the fallback), the card chooses
    expect(m.ended?.workOn).not.toBeNull();
  });

  it("while it loads: skeletons; on error: the D6 points as before", () => {
    const s = ended();
    const base = { snap: s, connected: true, nowS: newestT(s) + 1, driver: driver() };
    const loading = driveModel({ ...base, motivation: { note: null, recap: null, status: "loading" } });
    expect(loading.ended).toMatchObject({ things: null, thingsLoading: true, badges: [] });
    const error = driveModel({ ...base, motivation: { note: null, recap: null, status: "error" } });
    expect(error.ended).toMatchObject({ things: null, thingsLoading: false });
    expect(driveModel(base).ended).toMatchObject({ things: null, thingsLoading: false, badges: [] });
  });
});
