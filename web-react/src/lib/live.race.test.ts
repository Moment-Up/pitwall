// The live store keeps race radio's block within a session (race-radio spec 9.3, 10.1): the server sends `race` only
// when it changed (at most every 0.5 s, at once after a call) and with the static payload.

import { describe, expect, it } from "vitest";
import type { SnapshotNext } from "./drive/types";
import { snap } from "./drive/testkit";
import { mergeStatic, offlineSnapshot, STATIC_KEYS } from "./live";
import { raceView } from "./raceradio/testkit";
import { snapRace } from "./raceradio/view";

describe("race block across snapshots", () => {
  it("is a kept key", () => {
    expect(STATIC_KEYS).toContain("race");
  });

  it("absent keeps it, null clears it, a new session starts without it", () => {
    const view = { ...raceView("edited-race-f1-mid-race"), session_id: "s1" };
    const prev: SnapshotNext = { ...snap(), race: view };
    const kept = mergeStatic(prev, snap());
    expect(kept.race).toBe(view);
    expect(snapRace(kept)?.position).toBe(7);
    expect(mergeStatic(prev, { ...snap(), race: null }).race).toBeNull();
    const newer = { ...view, position: 6 };
    expect(mergeStatic(prev, { ...snap(), race: newer }).race).toBe(newer);
    expect(mergeStatic(prev, snap({ session_id: "s2" })).race).toBeUndefined();
  });

  it("stays while the socket is down (a fact of the session; Drive shows Offline over it, never its flags)", () => {
    const view = { ...raceView("edited-race-f1-blue-flag"), session_id: "s1" };
    const withBlock: SnapshotNext = { ...snap(), race: view };
    const off = offlineSnapshot(withBlock) as SnapshotNext;
    expect(off.frame).toBeNull();
    expect(off.race).toBe(view);
  });
});
