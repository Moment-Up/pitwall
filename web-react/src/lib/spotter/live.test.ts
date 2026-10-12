// The spotter block travels in every /ws/live snapshot and is NOT a kept key (design spec 8.3): a snapshot without it
// means "no block", never "the previous block" (lib/live.ts mergeStatic), so stale bars can never be carried across.
import { describe, expect, it } from "vitest";
import type { Snapshot } from "../api";
import type { SnapshotNext } from "../drive/types";
import { mergeStatic, STATIC_KEYS } from "../live";
import { spotterFixture } from "../../test/spotter";
import { parseSpotterBlock } from "./view";

function snap(extra: Partial<SnapshotNext>): Snapshot {
  return { version: 1, session_id: "s1", ...extra } as unknown as Snapshot;
}

describe("the spotter block in the live store", () => {
  it("is not a kept key", () => {
    expect(STATIC_KEYS as readonly string[]).not.toContain("spotter");
  });

  it("a snapshot without the block does not inherit the previous one", () => {
    const prev = snap({ spotter: spotterFixture("live-alongside-left") as SnapshotNext["spotter"] });
    const next = mergeStatic(prev, snap({}));
    expect((next as SnapshotNext).spotter).toBeUndefined();
    expect(parseSpotterBlock((next as SnapshotNext).spotter)).toBeNull();
  });
});
