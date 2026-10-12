// Drive's status slot: the TYRES COLD chip (lane "health", spec 3.13 D4). A transient chip for CHIP_SHOW_S from the
// radio's tyres_cold call (the moment the tyres turned cold after a pit exit or a safety car), only while car_health
// still says cold; it ranks below a penalty and a contact, and the bands (RED FLAG, SAFETY CAR) are drawn over it.
import { describe, expect, it } from "vitest";
import { frame, snap } from "../drive/testkit";
import { CHIP_RANK, CHIP_SHOW_S, chipsOf, chipText, driveState } from "../drive/state";
import type { LiveEvent, SnapshotNext } from "../drive/types";
import { healthView, withHealth } from "./testkit";

const cold = healthView("edited-live-f1-carcass-cold-after-stop");
const T = cold.calls[0]!.t_unix;

function s(over: Partial<SnapshotNext> = {}, ch = cold): SnapshotNext {
  return withHealth(snap({ frame: frame(), ...over }), { car_health: ch });
}

function ev(kind: string, t: number, extra: Partial<LiveEvent> = {}): LiveEvent {
  return { kind, code: null, session_time_s: null, t, player: true, ...extra };
}

describe("TYRES COLD chip", () => {
  it("for CHIP_SHOW_S after the tyres_cold call, with its words", () => {
    expect(chipsOf({ snap: s(), nowS: T + 1 }).transient).toEqual({ kind: "tyres_cold", ageS: 1 });
    expect(chipsOf({ snap: s(), nowS: T + CHIP_SHOW_S }).transient?.kind).toBe("tyres_cold");
    expect(chipsOf({ snap: s(), nowS: T + CHIP_SHOW_S + 1 }).transient).toBeNull();
    expect(chipText("tyres_cold")).toBe("TYRES COLD");
  });

  it("only while car_health still says cold; never without the block or the call", () => {
    const warm = { ...cold, tyres: { ...cold.tyres!, state: "ok" as const } };
    expect(chipsOf({ snap: s({}, warm), nowS: T + 1 }).transient).toBeNull();
    expect(chipsOf({ snap: s({}, { ...cold, calls: [] }), nowS: T + 1 }).transient).toBeNull();
    expect(chipsOf({ snap: snap(), nowS: T + 1 }).transient).toBeNull();
    // a block of another session is not about this car
    const other = s();
    other.car_health = { ...other.car_health!, session_id: "other" };
    expect(chipsOf({ snap: other, nowS: T + 1 }).transient).toBeNull();
  });

  it("ranks below a penalty and a contact, above a pit exit (the useful words at the exit)", () => {
    expect(CHIP_RANK.tyres_cold).toBeGreaterThan(CHIP_RANK.collision);
    expect(CHIP_RANK.tyres_cold).toBeLessThan(CHIP_RANK.pit_exit);
    expect(chipsOf({ snap: s({ events: [ev("penalty", T)] }), nowS: T + 1 }).transient?.kind).toBe("penalty");
    expect(chipsOf({ snap: s({ events: [ev("pit_exit", T - 1)] }), nowS: T + 1 }).transient?.kind).toBe("tyres_cold");
  });

  it("reaches the Drive state's overlays on track", () => {
    const r = driveState(s(), true, T + 1);
    expect(r.state).toBe("on_track");
    expect(r.overlays.chip?.kind).toBe("tyres_cold");
  });
});
