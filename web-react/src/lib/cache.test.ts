import { afterEach, describe, expect, it, vi } from "vitest";
import { deferred, flush } from "../test/fakes";
import { RequestCache } from "./cache";

function clock(start = 1_000) {
  let t = start;
  return { now: () => t, advance: (ms: number) => (t += ms) };
}

describe("RequestCache", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("dedupes requests in flight for the same key", async () => {
    const c = new RequestCache();
    const d = deferred<number>();
    const fetcher = vi.fn(() => d.promise);
    const a = c.load("sessions", fetcher);
    const b = c.load("sessions", fetcher);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(c.entry("sessions").loading).toBe(true);
    d.resolve(3);
    expect(await a).toBe(3);
    expect(await b).toBe(3);
    expect(c.entry("sessions")).toMatchObject({ data: 3, loading: false, error: null, stale: false });
  });

  it("serves fresh data without a request; force or age refetches", async () => {
    const t = clock();
    const c = new RequestCache({ now: t.now });
    const fetcher = vi.fn(async () => "x");
    await c.load("k", fetcher);
    await c.load("k", fetcher);
    expect(fetcher).toHaveBeenCalledTimes(1);
    await c.load("k", fetcher, { force: true });
    expect(fetcher).toHaveBeenCalledTimes(2);
    t.advance(31_000);
    await c.load("k", fetcher);
    expect(fetcher).toHaveBeenCalledTimes(3);
    t.advance(5_000);
    await c.load("k", fetcher, { maxAgeMs: 1_000 });
    expect(fetcher).toHaveBeenCalledTimes(4);
  });

  it("keeps the last data on error and reports the error", async () => {
    const c = new RequestCache();
    await c.load("k", async () => [1, 2]);
    await expect(c.load("k", () => Promise.reject(new Error("503: busy")), { force: true })).rejects.toThrow("busy");
    expect(c.entry("k")).toMatchObject({ data: [1, 2], loading: false });
    expect(c.entry("k").error?.message).toBe("503: busy");
    await c.load("k", async () => [3], { force: true });
    expect(c.entry("k")).toMatchObject({ data: [3], error: null });
  });

  it("notifies only the key's listeners, with a new entry object per change", async () => {
    const c = new RequestCache();
    const onA = vi.fn();
    const onB = vi.fn();
    c.subscribe("a", onA);
    c.subscribe("b", onB);
    const before = c.entry("a");
    await c.load("a", async () => 1);
    expect(onA).toHaveBeenCalledTimes(2); // loading, then data
    expect(onB).not.toHaveBeenCalled();
    expect(c.entry("a")).not.toBe(before);
    expect(c.entry("a")).toBe(c.entry("a")); // stable between changes
  });

  it("invalidate(prefix) refetches watched keys and only marks the others stale", async () => {
    const c = new RequestCache();
    const s1 = vi.fn(async () => "s1");
    const s2 = vi.fn(async () => "s2");
    const list = vi.fn(async () => ["s1", "s2"]);
    await c.load("session:1", s1);
    await c.load("session:2", s2);
    await c.load("sessions", list);
    c.subscribe("session:1", () => {});

    c.invalidate("session:");
    await flush();
    expect(s1).toHaveBeenCalledTimes(2); // watched: refetched now
    expect(s2).toHaveBeenCalledTimes(1); // not watched: stale until next load
    expect(c.entry("session:2").stale).toBe(true);
    expect(c.entry("session:2").data).toBe("s2"); // data kept
    expect(list).toHaveBeenCalledTimes(1); // "session:" does not match "sessions"
    expect(c.entry("sessions").stale).toBe(false);

    await c.load("session:2", s2);
    expect(s2).toHaveBeenCalledTimes(2);
  });

  it("an invalidated request in flight cannot overwrite newer data", async () => {
    const c = new RequestCache();
    const old = deferred<string>();
    const fresh = deferred<string>();
    const fetcher = vi.fn().mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise);
    c.subscribe("k", () => {});
    const first = c.load("k", fetcher as () => Promise<string>);
    c.invalidate("k"); // watched: starts the second request
    expect(fetcher).toHaveBeenCalledTimes(2);
    fresh.resolve("new");
    await flush();
    old.resolve("old");
    expect(await first).toBe("old"); // the first caller still gets its answer...
    expect(c.entry("k").data).toBe("new"); // ...but the cache keeps the newer one
    expect(c.entry("k").loading).toBe(false);
  });

  it("set() stores a mutation result and supersedes a request in flight", async () => {
    const c = new RequestCache();
    const d = deferred<string>();
    void c.load("k", () => d.promise);
    c.set("k", "saved");
    d.resolve("older");
    await flush();
    expect(c.entry("k")).toMatchObject({ data: "saved", loading: false, stale: false });
  });

  it("refetches watched, older entries when the tab comes back", async () => {
    const t = clock();
    const c = new RequestCache({ now: t.now });
    const handlers: Record<string, () => void> = {};
    const doc = { visibilityState: "visible", addEventListener: (k: string, f: () => void) => (handlers[k] = f), removeEventListener: vi.fn() };
    vi.stubGlobal("window", { addEventListener: (k: string, f: () => void) => (handlers[k] = f), removeEventListener: vi.fn() });
    vi.stubGlobal("document", doc);
    const watched = vi.fn(async () => 1);
    const unwatched = vi.fn(async () => 2);
    await c.load("w", watched);
    await c.load("u", unwatched);
    c.subscribe("w", () => {});
    const off = c.refetchOnFocus();

    handlers.focus?.();
    expect(watched).toHaveBeenCalledTimes(1); // too young to refetch
    t.advance(6_000);
    handlers.visibilitychange?.();
    await flush();
    expect(watched).toHaveBeenCalledTimes(2);
    expect(unwatched).toHaveBeenCalledTimes(1);
    off();
  });

  it("past the cap, evicts the oldest keys that nobody watches and nothing is loading", async () => {
    const c = new RequestCache({ maxEntries: 3 });
    const unwatch = c.subscribe("a", () => {}); // watched: kept
    await c.load("a", async () => "a");
    const pending = deferred<string>();
    void c.load("b", () => pending.promise); // in flight: kept
    await c.load("c", async () => "c");
    await c.load("d", async () => "d");
    expect(c.keys().sort()).toEqual(["a", "b", "d"]); // "c" was the oldest evictable key
    expect(c.entry("c").data).toBeUndefined();
    pending.resolve("b");
    await flush();
    unwatch();
  });

  it("using a key (load, subscribe) makes it recent", async () => {
    const c = new RequestCache({ maxEntries: 2 });
    await c.load("x", async () => "x");
    await c.load("y", async () => "y");
    await c.load("x", async () => "x"); // fresh: served from the cache, and now the most recent
    await c.load("z", async () => "z");
    expect(c.keys().sort()).toEqual(["x", "z"]);
    c.subscribe("x", () => {})(); // a subscribe touches too
    await c.load("w", async () => "w");
    expect(c.keys().sort()).toEqual(["w", "x"]);
  });

  it("an evicted key loads again with its new fetcher, and a superseded request cannot write it back", async () => {
    const c = new RequestCache({ maxEntries: 1 });
    const slow = deferred<string>();
    void c.load("old", () => slow.promise).catch(() => {});
    c.invalidate("old"); // supersedes the request in flight (nobody watches, so no refetch)
    await c.load("new", async () => "n"); // "old" is idle now: evicted
    expect(c.keys()).toEqual(["new"]);
    slow.resolve("stale");
    await flush();
    expect(c.keys()).toEqual(["new"]);
    expect(c.entry("old").data).toBeUndefined();
    const fresh = vi.fn(async () => "again");
    expect(await c.load("old", fresh)).toBe("again");
    expect(fresh).toHaveBeenCalledTimes(1);
  });
});
