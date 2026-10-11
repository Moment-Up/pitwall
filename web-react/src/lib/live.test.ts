import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeWebSocket, stubBrowser } from "../test/fakes";
import type { Frame, Snapshot, TrackModel } from "./api";
import { resetTokenCacheForTests } from "./auth";
import { bestsOf } from "./drive/timing";
import { FIXTURES, fixture } from "./drive/testkit";
import type { SnapshotNext } from "./drive/types";
import {
  badgeFor,
  FOREGROUND_RECONNECT_MS,
  LIVE_SILENCE_MS,
  LiveStore,
  mergeStatic,
  offlineSnapshot,
  STATIC_KEYS,
} from "./live";

const MODEL: TrackModel = {
  game: "f1_25",
  track_id: "silverstone",
  track_name: "Silverstone",
  length_m: 5891,
  version: 1,
  n_laps: 3,
  corners: [],
  centreline: [],
};

function frame(over: Partial<Frame> = {}): Frame {
  return { speed_kph: 250, throttle: 1, brake: 0, gear: 7, lap_number: 3, lap_distance_m: 1200, ...over } as Frame;
}

function snapshot(over: Partial<Snapshot> = {}): Snapshot {
  return {
    version: 1,
    connection: {
      status: "live",
      last_packet_age_s: 0.02,
      packets: 1000,
      packets_per_s: 60,
      rejected: 0,
      unrecognised: 0,
      source: "udp",
      synthetic: false,
      decode: {},
    },
    session_id: "s1",
    session: null,
    frame: frame(),
    delta_s: -0.12,
    reference: null,
    laps: [],
    observations: [],
    events: [],
    ...over,
  };
}

describe("badgeFor", () => {
  it.each([
    ["live", true, "LIVE"],
    ["stale", true, "STALE"],
    ["no_data", true, "IDLE"],
    [null, true, "IDLE"],
    // The socket being down outranks the server's last status: it is no longer known to be true.
    ["live", false, "OFFLINE"],
    ["stale", false, "OFFLINE"],
    [null, false, "OFFLINE"],
  ] as const)("%s, connected=%s -> %s", (status, connected, badge) => {
    expect(badgeFor(status, connected)).toBe(badge);
  });
});

/** What the server sends between its 5 s static payloads: the same snapshot without the static keys. */
function withoutStatics<S extends Snapshot>(full: S): S {
  const lean = structuredClone(full) as unknown as Record<string, unknown>;
  for (const k of STATIC_KEYS) delete lean[k];
  return lean as unknown as S;
}

/** The edited D2 fixture (driver and household bests) as if it came from the game over UDP rather than a replay,
 * so the cross-session bests are in force (tier 2, spec 4.6). */
function d2LiveSnapshot(): SnapshotNext {
  const s = fixture("edited-d1-d6");
  s.connection = { ...s.connection, source: "udp:20777", synthetic: false };
  return s;
}

describe("mergeStatic", () => {
  it("carries track_model / skeleton across a snapshot that omits them (undefined)", () => {
    const prev = snapshot({ track_model: MODEL, skeleton: null });
    const next = mergeStatic(prev, snapshot());
    expect(next.track_model).toBe(MODEL);
    expect(next.skeleton).toBeNull();
  });

  it("an explicit null means 'none' and replaces the previous value", () => {
    const next = mergeStatic(snapshot({ track_model: MODEL }), snapshot({ track_model: null }));
    expect(next.track_model).toBeNull();
  });

  it("returns the snapshot unchanged when there is nothing to carry", () => {
    const s = snapshot();
    expect(mergeStatic(null, s)).toBe(s);
    expect(mergeStatic(snapshot(), s)).toBe(s);
  });

  it("carries every static-cadence key (bests, last_comparison, track_knowledge too)", () => {
    const statics = { bests: { session: { lap_ms: 1 } }, last_comparison: { ok: true }, track_knowledge: { v: 1 } };
    const prev = { ...snapshot({ track_model: MODEL, skeleton: null }), ...statics } as Snapshot;
    const next = mergeStatic(prev, snapshot()) as unknown as Record<string, unknown>;
    for (const k of STATIC_KEYS) expect(next[k]).toBe((prev as unknown as Record<string, unknown>)[k]);
  });

  it("never carries a previous session's static parts into a new session", () => {
    const prev = { ...snapshot({ track_model: MODEL }), bests: { session: { lap_ms: 1 } } } as Snapshot;
    const next = mergeStatic(prev, snapshot({ session_id: "s2" })) as unknown as Record<string, unknown>;
    expect(next.track_model).toBeUndefined();
    expect(next.bests).toBeUndefined();
  });

  it("every Drive fixture: a static snapshot then a non-static one keeps the same bests", () => {
    for (const name of FIXTURES) {
      const full = fixture(name);
      expect(bestsOf(mergeStatic(full, withoutStatics(full))), name).toEqual(bestsOf(full));
    }
  });
});

describe("offlineSnapshot", () => {
  it("clears the car's live state and keeps the session facts", () => {
    const s = snapshot({ track_model: MODEL, marshal_flags: [{ game_number: 1, flag: "yellow" }] });
    const off = offlineSnapshot(s);
    expect(off?.frame).toBeNull();
    expect(off?.delta_s).toBeNull();
    expect(off?.marshal_flags).toBeUndefined();
    expect(off?.track_model).toBe(MODEL);
    expect(off?.session_id).toBe("s1");
  });

  it("is a no-op for null and for an already-offline snapshot", () => {
    expect(offlineSnapshot(null)).toBeNull();
    const off = offlineSnapshot(snapshot());
    expect(offlineSnapshot(off)).toBe(off);
  });
});

describe("LiveStore", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    stubBrowser("http://127.0.0.1:8770/next/#/drive/live");
    resetTokenCacheForTests();
    FakeWebSocket.reset();
    vi.stubGlobal("WebSocket", FakeWebSocket);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("opens one socket for any number of users and closes it after the last release", () => {
    const store = new LiveStore();
    const a = store.start();
    const b = store.start();
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(FakeWebSocket.last().url).toBe("ws://127.0.0.1:8770/ws/live");
    FakeWebSocket.last().open();
    expect(store.get().connected).toBe(true);
    a();
    vi.advanceTimersByTime(10);
    expect(FakeWebSocket.last().closed).toBe(false);
    b();
    vi.advanceTimersByTime(0);
    expect(FakeWebSocket.last().closed).toBe(true);
    expect(store.get().connected).toBe(false);
  });

  it("keeps the socket across a StrictMode release/re-acquire and ignores a double release", () => {
    const store = new LiveStore();
    const first = store.start();
    first();
    first(); // idempotent: must not drop the count below zero
    const second = store.start(); // remount before the deferred close ran
    vi.advanceTimersByTime(100);
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(FakeWebSocket.last().closed).toBe(false);
    second();
    vi.advanceTimersByTime(0);
    expect(FakeWebSocket.last().closed).toBe(true);
  });

  it("reconnects with exponential backoff (500 ms -> 5 s) and resets it once a socket opens", () => {
    const store = new LiveStore();
    store.start();
    const waits: number[] = [];
    for (let i = 0; i < 6; i++) {
      const n = FakeWebSocket.instances.length;
      FakeWebSocket.last().drop();
      let waited = 0;
      while (FakeWebSocket.instances.length === n) {
        vi.advanceTimersByTime(100);
        waited += 100;
      }
      waits.push(waited);
    }
    expect(waits).toEqual([500, 1000, 2000, 4000, 5000, 5000]);
    FakeWebSocket.last().open();
    FakeWebSocket.last().drop();
    vi.advanceTimersByTime(499);
    expect(FakeWebSocket.instances).toHaveLength(7);
    vi.advanceTimersByTime(1);
    expect(FakeWebSocket.instances).toHaveLength(8);
  });

  it("stops reconnecting after the last user releases, even with a retry pending", () => {
    const store = new LiveStore();
    const release = store.start();
    FakeWebSocket.last().drop(); // retry scheduled in 500 ms
    release();
    vi.advanceTimersByTime(10_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("merges static parts, decodes binary frames and survives malformed ones", () => {
    const store = new LiveStore();
    store.start();
    const ws = FakeWebSocket.last();
    ws.open();
    ws.message({ type: "snapshot", data: snapshot({ track_model: MODEL }) }, true);
    const model = store.get().snap?.track_model;
    expect(model).toEqual(MODEL);
    ws.message("{not json");
    ws.message({ type: "snapshot", data: snapshot({ frame: frame({ speed_kph: 251 }) }) });
    expect(store.get().snap?.frame?.speed_kph).toBe(251);
    expect(store.get().snap?.track_model).toBe(model); // carried across, same object
    expect(store.get().history.map((h) => h.speed)).toEqual([250, 251]);
    ws.message({ type: "lap", data: { lap: { lap_number: 3 }, observations: [] } });
    expect(store.get().lastLapEvent?.lap).toEqual({ lap_number: 3 });
  });

  it("never shows frozen telemetry as live when the socket drops (unknown stays unknown)", () => {
    const store = new LiveStore();
    store.start();
    FakeWebSocket.last().open();
    FakeWebSocket.last().message({ type: "snapshot", data: snapshot({ track_model: MODEL }) });
    const live = store.get();
    expect(badgeFor(live.snap?.connection.status, live.connected)).toBe("LIVE");

    FakeWebSocket.last().drop();
    const off = store.get();
    expect(off.connected).toBe(false);
    expect(badgeFor(off.snap?.connection.status, off.connected)).toBe("OFFLINE");
    expect(off.snap?.frame).toBeNull();
    expect(off.snap?.delta_s).toBeNull();
    expect(off.snap?.track_model).toEqual(MODEL); // session facts stay as last known

    vi.advanceTimersByTime(500);
    FakeWebSocket.last().open();
    FakeWebSocket.last().message({ type: "snapshot", data: snapshot() }); // no static parts in this one
    expect(store.get().snap?.frame?.speed_kph).toBe(250);
    expect(store.get().snap?.track_model).toEqual(MODEL);
  });

  it("a static snapshot then a non-static one keeps bests and track model in the store", () => {
    const store = new LiveStore();
    store.start();
    const ws = FakeWebSocket.last();
    ws.open();
    const full = d2LiveSnapshot();
    expect(bestsOf(full).tier).toBe(2);
    expect(bestsOf(withoutStatics(full)).tier).toBe(1); // what the bare frame alone would say
    ws.message({ type: "snapshot", data: full });
    ws.message({ type: "snapshot", data: withoutStatics(full) });
    const s = store.get().snap as SnapshotNext;
    expect(bestsOf(s).tier).toBe(2);
    expect(s.bests).toEqual(full.bests);
    expect(s.track_model).toEqual(full.track_model);
  });

  it("forwards a remembered access token on every reconnect", () => {
    const { win } = stubBrowser("http://192.168.1.20:8770/next/#/radio?token=XYZ");
    resetTokenCacheForTests();
    const store = new LiveStore();
    store.start();
    expect(FakeWebSocket.last().url).toBe("ws://192.168.1.20:8770/ws/live?token=XYZ");
    win.location.hash = "#/review/sessions"; // in-app navigation replaced the hash
    FakeWebSocket.last().drop();
    vi.advanceTimersByTime(500);
    expect(FakeWebSocket.last().url).toBe("ws://192.168.1.20:8770/ws/live?token=XYZ");
  });
});

describe("LiveStore watchdog and foreground reconnect", () => {
  type Handler = () => void;
  let winHandlers: Map<string, Handler>;
  let docHandlers: Map<string, Handler>;
  let doc: { visibilityState: "visible" | "hidden"; addEventListener: unknown; removeEventListener: unknown };

  beforeEach(() => {
    vi.useFakeTimers();
    const { win } = stubBrowser("http://127.0.0.1:8770/next/#/drive/coach");
    winHandlers = new Map();
    docHandlers = new Map();
    const w = win as unknown as Record<string, unknown>;
    w.addEventListener = vi.fn((type: string, h: Handler) => winHandlers.set(type, h));
    w.removeEventListener = vi.fn((type: string, h: Handler) => {
      if (winHandlers.get(type) === h) winHandlers.delete(type);
    });
    doc = {
      visibilityState: "visible",
      addEventListener: vi.fn((type: string, h: Handler) => docHandlers.set(type, h)),
      removeEventListener: vi.fn((type: string, h: Handler) => {
        if (docHandlers.get(type) === h) docHandlers.delete(type);
      }),
    };
    vi.stubGlobal("document", doc);
    resetTokenCacheForTests();
    FakeWebSocket.reset();
    vi.stubGlobal("WebSocket", FakeWebSocket);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  function liveStore(): { store: LiveStore; release: () => void } {
    const store = new LiveStore();
    const release = store.start();
    FakeWebSocket.last().open();
    FakeWebSocket.last().message({ type: "snapshot", data: snapshot() });
    return { store, release };
  }

  it("drops a socket that went silent (half-open) and shows nothing as current", () => {
    const { store } = liveStore();
    const first = FakeWebSocket.last();
    vi.advanceTimersByTime(LIVE_SILENCE_MS); // not yet: 8 s exactly is still allowed
    expect(first.closed).toBe(false);
    expect(store.get().connected).toBe(true);
    vi.advanceTimersByTime(1000);
    expect(first.closed).toBe(true);
    const s = store.get();
    expect(s.connected).toBe(false);
    expect(badgeFor(s.snap?.connection.status, s.connected)).toBe("OFFLINE");
    expect(s.snap?.frame).toBeNull();
    expect(s.snap?.delta_s).toBeNull();
    // and it reconnects on the normal backoff
    expect(FakeWebSocket.instances).toHaveLength(1);
    vi.advanceTimersByTime(500);
    expect(FakeWebSocket.instances).toHaveLength(2);
    // a late frame from the abandoned socket is ignored
    first.message({ type: "snapshot", data: snapshot({ delta_s: 9 }) });
    expect(store.get().snap?.delta_s).toBeNull();
  });

  it("keeps a quiet but healthy socket (the server's 5 s static refresh)", () => {
    const { store } = liveStore();
    for (let i = 0; i < 6; i++) {
      vi.advanceTimersByTime(5000);
      FakeWebSocket.last().message({ type: "snapshot", data: snapshot({ connection: { ...snapshot().connection, status: "no_data" } }) });
    }
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(store.get().connected).toBe(true);
  });

  it("abandons a handshake that never completes", () => {
    const store = new LiveStore();
    store.start(); // never opens
    vi.advanceTimersByTime(LIVE_SILENCE_MS + 1000);
    expect(FakeWebSocket.instances[0]?.closed).toBe(true);
    vi.advanceTimersByTime(500);
    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it("back in the foreground: reconnects now instead of waiting out the backoff", () => {
    const store = new LiveStore();
    store.start();
    for (let i = 0; i < 4; i++) {
      FakeWebSocket.last().drop();
      vi.advanceTimersByTime(5000); // backoff grows to 4 s, then 5 s
    }
    FakeWebSocket.last().drop(); // next retry in 5 s
    const n = FakeWebSocket.instances.length;
    doc.visibilityState = "hidden";
    docHandlers.get("visibilitychange")?.();
    expect(FakeWebSocket.instances).toHaveLength(n); // hidden: nothing
    doc.visibilityState = "visible";
    docHandlers.get("visibilitychange")?.();
    expect(FakeWebSocket.instances).toHaveLength(n + 1);
    // the pending retry was cancelled, and the backoff starts again at 500 ms
    FakeWebSocket.last().drop();
    vi.advanceTimersByTime(500);
    expect(FakeWebSocket.instances).toHaveLength(n + 2);
  });

  it("back in the foreground with a socket that last said live and then went quiet: reconnects now", () => {
    const { store } = liveStore();
    const first = FakeWebSocket.last();
    vi.advanceTimersByTime(FOREGROUND_RECONNECT_MS); // iPad locked briefly; still within the grace
    winHandlers.get("pageshow")?.();
    expect(first.closed).toBe(false);
    vi.advanceTimersByTime(500);
    winHandlers.get("pageshow")?.();
    expect(first.closed).toBe(true);
    expect(store.get().snap?.delta_s).toBeNull(); // the frozen delta is gone at once
    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it("back in the foreground with a quiet socket that said no data: keeps it (no offline flash)", () => {
    const store = new LiveStore();
    store.start();
    FakeWebSocket.last().open();
    FakeWebSocket.last().message({
      type: "snapshot",
      data: snapshot({ frame: null, connection: { ...snapshot().connection, status: "no_data" } }),
    });
    vi.advanceTimersByTime(4000);
    winHandlers.get("online")?.();
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(store.get().connected).toBe(true);
  });

  it("removes its listeners and timers after the last release", () => {
    const { release } = liveStore();
    expect(docHandlers.has("visibilitychange")).toBe(true);
    expect(winHandlers.has("online")).toBe(true);
    release();
    vi.advanceTimersByTime(0);
    expect(docHandlers.size).toBe(0);
    expect(winHandlers.size).toBe(0);
    vi.advanceTimersByTime(60_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });
});
