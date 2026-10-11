import { afterEach, describe, expect, it, vi } from "vitest";
import { RequestCache } from "../cache";
import { isMissingRoute } from "./review";
import { normaliseTimeline, strategyApi, strategyKeys } from "./strategy";

describe("strategy cache keys follow the app's invalidation rules (spec 12.3)", () => {
  it("a completed lap of the live session refreshes its strategy with its row; other sessions keep theirs", () => {
    const c = new RequestCache();
    c.set(strategyKeys.session("abc"), {});
    c.set(strategyKeys.session("other"), {});
    c.set("sessions", []);
    c.invalidate("session:abc"); // hooks/useApi.ts useCacheInvalidation on a `lap` event
    expect(c.entry(strategyKeys.session("abc")).stale).toBe(true);
    expect(c.entry(strategyKeys.session("other")).stale).toBe(false);
    expect(strategyKeys.session("abc")).toBe("session:abc:strategy");
    // a list refresh never touches one session's strategy
    c.invalidate("sessions");
    expect(c.entry(strategyKeys.session("other")).stale).toBe(false);
  });
});

describe("strategy endpoints", () => {
  afterEach(() => vi.unstubAllGlobals());

  function stubFetch(body: unknown, status = 200) {
    const f = vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", f);
    vi.stubGlobal("window", { location: { protocol: "http:", host: "127.0.0.1:8770", pathname: "/next/", search: "", hash: "" } });
    vi.stubGlobal("sessionStorage", { getItem: () => null, setItem: () => {}, removeItem: () => {} });
    return f;
  }

  it("asks for a session's timeline by its encoded id and fills missing lists", async () => {
    const f = stubFetch({ session_id: "a b", available: false, reason: "not a race" });
    const t = await strategyApi.session("a b");
    expect(String((f.mock.calls[0] as unknown[])[0])).toContain("/api/sessions/a%20b/strategy");
    expect(t).toMatchObject({ session_id: "a b", available: false, reason: "not a race", laps: [], stops: [], field_stops: [], calls: [] });
    expect(t.pit_loss).toBeNull();
    expect(t.total_laps).toBeNull();
  });

  it("the live view: version 1 is read, an unknown contract is ignored (null), never guessed", async () => {
    stubFetch({ version: 1, mode: "off", reason: "no live session", calls: [] });
    expect(await strategyApi.live()).toMatchObject({ mode: "off", reason: "no live session" });
    stubFetch({ version: 2, mode: "race" });
    expect(await strategyApi.live()).toBeNull();
  });

  it("a missing session is the route's 404; a server without the engine is FastAPI's own", async () => {
    stubFetch({ detail: "session not found" }, 404);
    const e1 = await strategyApi.session("nope").catch((e: unknown) => e);
    expect(String(e1)).toContain("404: session not found");
    expect(isMissingRoute(e1)).toBe(false);
    stubFetch({ detail: "Not Found" }, 404);
    const e2 = await strategyApi.session("abc").catch((e: unknown) => e);
    expect(isMissingRoute(e2)).toBe(true);
  });

  it("normalises a partial timeline without inventing values", () => {
    const t = normaliseTimeline({ session_id: "x", available: true, laps: null as never, grid_position: 4 });
    expect(t).toMatchObject({ available: true, grid_position: 4, finish_position: null, laps: [], weather: [] });
  });
});
