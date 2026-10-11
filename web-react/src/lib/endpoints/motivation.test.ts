import { afterEach, describe, expect, it, vi } from "vitest";
import { resetTokenCacheForTests } from "../auth";
import { RequestCache } from "../cache";
import { stubBrowser } from "../../test/fakes";
import { motivationFixtureBlocks, mfx } from "../motivation/testkit";
import { isMissingRoute } from "./review";
import { detailText, motivationApi, motivationKeys, motivationPaths, MotivationError } from "./motivation";

describe("motivation cache keys follow the app's invalidation rules (spec 12.3)", () => {
  it("goals, suggestions, badges and the digest refresh with the driver's sessions (a lap, a driver switch)", () => {
    const c = new RequestCache();
    const keys = [
      motivationKeys.goals(2),
      motivationKeys.suggestions(2, { game: "f1_25", track_id: "f1:17", car: "f1:team:7" }),
      motivationKeys.badges(2),
      motivationKeys.digest(2, null),
      motivationKeys.digest(2, "2026-10-05"),
    ];
    for (const k of keys) c.set(k, {});
    c.invalidate("driver-sessions:");
    for (const k of keys) expect(c.entry(k).stale, k).toBe(true);
  });

  it("a goal mutation's prefix covers the goals and their suggestions, not another driver", () => {
    const c = new RequestCache();
    c.set(motivationKeys.goals(2), {});
    c.set(motivationKeys.suggestions(2, {}), {});
    c.set(motivationKeys.goals(3), {});
    c.invalidate(motivationKeys.goals(2));
    expect(c.entry(motivationKeys.goals(2)).stale).toBe(true);
    expect(c.entry(motivationKeys.suggestions(2, {})).stale).toBe(true);
    expect(c.entry(motivationKeys.goals(3)).stale).toBe(false);
  });

  it("a session's recap refreshes with the live session (\"session:<id>\"); Drive's key names the lap and note", () => {
    const c = new RequestCache();
    c.set(motivationKeys.recap("abc"), {});
    c.invalidate("session:abc");
    expect(c.entry(motivationKeys.recap("abc")).stale).toBe(true);
    expect(motivationKeys.driveRecap("abc", 7, null)).toBe("motivation:recap:abc:7:");
    expect(motivationKeys.driveRecap("abc", 7, 1791669000)).toBe("motivation:recap:abc:7:1791669000");
  });
});

describe("motivation endpoints", () => {
  afterEach(() => vi.unstubAllGlobals());

  function stubFetch(body: unknown, status = 200) {
    const f = vi.fn(
      async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
    );
    vi.stubGlobal("fetch", f);
    vi.stubGlobal("window", { location: { protocol: "http:", host: "127.0.0.1:8825", pathname: "/", search: "", hash: "" } });
    vi.stubGlobal("sessionStorage", { getItem: () => null, setItem: () => {}, removeItem: () => {} });
    return f;
  }

  const call = (f: ReturnType<typeof stubFetch>, i: number) => f.mock.calls[i] as unknown as [string, RequestInit | undefined];

  it("builds every URL of the contract (section 6)", async () => {
    const f = stubFetch({});
    await motivationApi.goals(2);
    await motivationApi.suggestions(2, { game: "f1_25", track_id: "f1:17", car: "f1:team:7" });
    await motivationApi.suggestions(2, { from_session_id: "a b" });
    await motivationApi.badges(2);
    await motivationApi.badges(2, true);
    await motivationApi.digest(2);
    await motivationApi.digest(2, "2026-10-05");
    await motivationApi.recap("a b");
    const urls = f.mock.calls.map((_, i) => call(f, i)[0]);
    expect(urls).toEqual([
      "/api/drivers/2/goals",
      "/api/drivers/2/goals/suggestions?game=f1_25&track_id=f1%3A17&car=f1%3Ateam%3A7",
      "/api/drivers/2/goals/suggestions?from_session_id=a+b",
      "/api/drivers/2/badges",
      "/api/drivers/2/badges?synthetic=true",
      "/api/drivers/2/digest",
      "/api/drivers/2/digest?week=2026-10-05",
      "/api/sessions/a%20b/recap",
    ]);
    expect(motivationPaths.digestHtml(2, "2026-10-05")).toBe("/api/drivers/2/digest.html?week=2026-10-05");
    expect(motivationPaths.digestHtml(2)).toBe("/api/drivers/2/digest.html");
  });

  it("the printable page's new tab carries a hash token (no cookie on that device), else the plain path", () => {
    resetTokenCacheForTests();
    stubBrowser("http://h/#/review/progress?driver=2");
    expect(motivationPaths.digestHtmlTab(2, "2026-10-05")).toBe("/api/drivers/2/digest.html?week=2026-10-05");
    resetTokenCacheForTests();
    stubBrowser("http://h/#/review/progress?driver=2&token=a b");
    expect(motivationPaths.digestHtmlTab(2, "2026-10-05")).toBe("/api/drivers/2/digest.html?week=2026-10-05&token=a+b");
    resetTokenCacheForTests();
  });

  it("creates, archives, reopens and deletes with the right methods and bodies", async () => {
    const f = stubFetch(mfx.goals().goals[0]);
    await motivationApi.createGoal(2, { kind: "clean_streak", target: 8, source: "manual" });
    await motivationApi.setStatus(2, 4, "archived");
    await motivationApi.setStatus(2, 2, "active");
    await motivationApi.deleteGoal(2, 4);
    const [u0, i0] = call(f, 0);
    expect(u0).toBe("/api/drivers/2/goals");
    expect(i0?.method).toBe("POST");
    expect(JSON.parse(String(i0?.body))).toEqual({ kind: "clean_streak", target: 8, source: "manual" });
    expect(call(f, 1)[0]).toBe("/api/drivers/2/goals/4");
    expect(call(f, 1)[1]?.method).toBe("PATCH");
    expect(JSON.parse(String(call(f, 1)[1]?.body))).toEqual({ status: "archived" });
    expect(JSON.parse(String(call(f, 2)[1]?.body))).toEqual({ status: "active" });
    expect(call(f, 3)[1]?.method).toBe("DELETE");
  });

  it("a 409 carries the server's sentence and code, shown as it is", async () => {
    stubFetch({ detail: "Your best here is already 1:10.549", code: "already_beaten" }, 409);
    const e = await motivationApi.createGoal(2, { kind: "lap_time", target: 71000 }).catch((x: unknown) => x);
    expect(e).toBeInstanceOf(MotivationError);
    expect((e as MotivationError).status).toBe(409);
    expect((e as MotivationError).code).toBe("already_beaten");
    expect((e as MotivationError).detail).toBe("Your best here is already 1:10.549");
  });

  it("a 422 validation list becomes one sentence; an older server's 404 is a missing route", async () => {
    stubFetch({ detail: [{ loc: ["body", "target"], msg: "target must be a multiple of 100", type: "value_error" }] }, 422);
    const e = (await motivationApi.createGoal(2, { kind: "lap_time", target: 70050 }).catch((x: unknown) => x)) as MotivationError;
    expect(e.detail).toBe("target must be a multiple of 100");
    stubFetch({ detail: "Not Found" }, 404);
    const m = await motivationApi.goals(2).catch((x: unknown) => x);
    expect(isMissingRoute(m)).toBe(true);
    stubFetch({ detail: "driver 7 not found" }, 404);
    expect(isMissingRoute(await motivationApi.goals(7).catch((x: unknown) => x))).toBe(false);
  });

  it("detailText never shows a raw object", () => {
    expect(detailText({ a: 1 }, "Bad Request")).toBe("Bad Request");
    expect(detailText("", "Conflict")).toBe("Conflict");
    expect(detailText([{ nope: 1 }], "Unprocessable")).toBe("Unprocessable");
  });
});

describe("motivation fixtures say where they came from", () => {
  it("every fixture is hand-edited, from the lane spec, with a fictional driver", () => {
    const blocks = motivationFixtureBlocks();
    expect(blocks.length).toBeGreaterThanOrEqual(15);
    for (const { name, block } of blocks) {
      expect(name.startsWith("edited-"), name).toBe(true);
      expect(block.tier, name).toBe("edited");
      expect(block.source, name).toMatch(/lane spec/);
      expect(block.what.length, name).toBeGreaterThan(10);
      expect(block.notes ?? "", name).toMatch(/Fictional driver 'Sam'/);
    }
  });

  it("no fixture names a real player: the only driver names are the fictional ones", () => {
    const text = JSON.stringify([mfx.goals(), mfx.digest(), mfx.recap(), mfx.recapReplay(), mfx.badges()]);
    for (const m of text.matchAll(/"(?:driver_name|name)":"([^"]+)"/g)) expect(["Sam"]).toContain(m[1]);
  });
});
