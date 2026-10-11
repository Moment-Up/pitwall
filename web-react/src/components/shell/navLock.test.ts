import { afterEach, describe, expect, it, vi } from "vitest";
import type { Snapshot } from "../../lib/api";
import { LOCK_HINT_MS, holdNeeded, navLock, onTrackFallback } from "./navLock";

const snap = (status: "live" | "stale" | "no_data", pit: number | null): Snapshot =>
  ({ connection: { status }, frame: pit === null ? null : { pit_status: pit } }) as unknown as Snapshot;

describe("onTrackFallback (spec 3.3: telemetry live and pit_status 0)", () => {
  it.each([
    [snap("live", 0), true, true],
    [snap("live", 1), true, false], // pit lane
    [snap("live", 2), true, false], // garage
    [snap("live", null), true, false], // no frame: unknown is not on track
    [snap("stale", 0), true, false],
    [snap("live", 0), false, false], // dashboard offline
    [null, true, false],
  ])("%#", (s, connected, want) => {
    expect(onTrackFallback(s, connected)).toBe(want);
  });
});

describe("navLock hint", () => {
  afterEach(() => {
    vi.useRealTimers();
    navLock.clearHint();
    navLock.publishOnTrack(null);
  });

  it("shows for 2 s, restarting on each tap", () => {
    vi.useFakeTimers();
    navLock.showHint();
    expect(navLock.get().hint).toBe(true);
    vi.advanceTimersByTime(LOCK_HINT_MS - 100);
    navLock.showHint();
    vi.advanceTimersByTime(LOCK_HINT_MS - 100);
    expect(navLock.get().hint).toBe(true);
    vi.advanceTimersByTime(200);
    expect(navLock.get().hint).toBe(false);
  });

  it("Drive pages publish their on-track verdict", () => {
    navLock.publishOnTrack(true);
    expect(navLock.get().published).toBe(true);
    navLock.publishOnTrack(null);
    expect(navLock.get().published).toBeNull();
  });
});

describe("holdNeeded (one rule for the rail, the tab bar and the Drive Segment)", () => {
  it("only while locked, and never to Drive › Coach", () => {
    expect(holdNeeded({ locked: false }, "review")).toBe(false);
    expect(holdNeeded({ locked: true }, "review")).toBe(true);
    expect(holdNeeded({ locked: true }, "settings", "display")).toBe(true);
    expect(holdNeeded({ locked: true }, "drive", "car")).toBe(true);
    expect(holdNeeded({ locked: true }, "drive", "coach")).toBe(false);
    expect(holdNeeded({ locked: true }, "drive")).toBe(false);
  });
});
