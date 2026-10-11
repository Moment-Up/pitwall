// The /ws/live "motivation" message (lane motivation, spec 5 and 9): the server forwards the worker's note as
// {"type": "motivation", "data": MotivationNote}; the live store keeps the newest one for Drive's GOAL REACHED chip.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeWebSocket, stubBrowser } from "../test/fakes";
import { resetTokenCacheForTests } from "./auth";
import { LiveStore } from "./live";
import { mfx } from "./motivation/testkit";

describe("LiveStore: the motivation note", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    stubBrowser("http://127.0.0.1:8825/#/drive/coach");
    resetTokenCacheForTests();
    FakeWebSocket.reset();
    vi.stubGlobal("WebSocket", FakeWebSocket);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("starts empty, keeps the newest note (text or binary frames), leaves laps and snapshots alone", () => {
    const store = new LiveStore();
    expect(store.get().lastMotivation).toBeNull();
    store.start();
    const ws = FakeWebSocket.last();
    ws.open();
    const n = mfx.note();
    ws.message({ type: "motivation", data: n });
    expect(store.get().lastMotivation).toEqual(n);
    expect(store.get().lastLapEvent).toBeNull();
    expect(store.get().snap).toBeNull();
    const later = { ...n, t: n.t + 60, lap_number: 9 };
    ws.message({ type: "motivation", data: later }, true);
    expect(store.get().lastMotivation?.lap_number).toBe(9);
    ws.message("{broken");
    expect(store.get().lastMotivation?.lap_number).toBe(9);
    ws.message({ type: "lap", data: { lap: { lap_number: 9 }, observations: [] } });
    expect(store.get().lastMotivation?.lap_number).toBe(9);
  });

  it("an unknown message type changes nothing", () => {
    const store = new LiveStore();
    store.start();
    FakeWebSocket.last().open();
    const before = store.get();
    FakeWebSocket.last().message({ type: "something_new", data: { a: 1 } });
    expect(store.get()).toBe(before);
  });
});
