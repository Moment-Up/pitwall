import { afterEach, describe, expect, it, vi } from "vitest";
import { RequestCache } from "../cache";
import { reviewApi, reviewKeys } from "./review";

describe("review cache keys follow the app's invalidation rules (spec 12.3)", () => {
  it("a completed lap or a driver switch refreshes every session list", () => {
    const c = new RequestCache();
    c.set(reviewKeys.list("all"), []);
    c.set(reviewKeys.list(2), []);
    c.set(reviewKeys.session("abc"), {});
    c.invalidate("sessions");
    c.invalidate("driver-sessions:");
    expect(c.entry(reviewKeys.list("all")).stale).toBe(true);
    expect(c.entry(reviewKeys.list(2)).stale).toBe(true);
    // invalidate("sessions") must not touch one session's own data
    expect(c.entry(reviewKeys.session("abc")).stale).toBe(false);
  });

  it("the live session's row and analysis are refreshed by their own prefixes", () => {
    const c = new RequestCache();
    c.set(reviewKeys.session("abc"), {});
    c.set(reviewKeys.analysis("abc"), {});
    c.set(reviewKeys.analysis("other"), {});
    c.invalidate("session:abc");
    c.invalidate("analysis:abc");
    expect(c.entry(reviewKeys.session("abc")).stale).toBe(true);
    expect(c.entry(reviewKeys.analysis("abc")).stale).toBe(true);
    expect(c.entry(reviewKeys.analysis("other")).stale).toBe(false);
  });

  it("the 200-row list never shares the shell's 50-row 'sessions' entry", () => {
    expect(reviewKeys.list("all")).not.toBe("sessions");
    expect(reviewKeys.list("all").startsWith("sessions")).toBe(true);
    expect(reviewKeys.list(3)).toBe("driver-sessions:3");
  });
});

describe("review endpoints", () => {
  afterEach(() => vi.unstubAllGlobals());

  function stubFetch(body: unknown, status = 200) {
    const f = vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", f);
    vi.stubGlobal("window", { location: { protocol: "http:", host: "127.0.0.1:8770", pathname: "/next/", search: "", hash: "" } });
    vi.stubGlobal("sessionStorage", { getItem: () => null, setItem: () => {}, removeItem: () => {} });
    return f;
  }

  it("asks for a driver's sessions server-side and the analysis with an optional reference", async () => {
    const f = stubFetch([]);
    await reviewApi.list(2);
    await reviewApi.list("all");
    await reviewApi.analysis("a b", 52);
    const urls = f.mock.calls.map((c) => String((c as unknown[])[0]));
    expect(urls[0]).toContain("/api/drivers/2/sessions?limit=200");
    expect(urls[1]).toContain("/api/sessions?limit=200");
    expect(urls[2]).toContain("/api/sessions/a%20b/analysis?ref_lap_id=52");
  });

  it("surfaces the server's detail on errors", async () => {
    stubFetch({ detail: "session not found" }, 404);
    await expect(reviewApi.session("nope")).rejects.toThrow("404: session not found");
  });
});
