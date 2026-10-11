// Technique endpoints (feat/technique spec §6): paths, cache keys under "analysis:<id>" (a completed lap refreshes
// them), error kinds (a server without the routes hides the blocks; 409 is "no track model yet"), and the contract
// fixtures saying where they came from.
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api";
import { cache } from "../cache";
import { techniqueFixtureBlocks } from "../technique/testkit";
import {
  techniqueApi,
  techniqueBalancePath,
  techniqueComparePath,
  techniqueErrorKind,
  techniqueErrorText,
  techniqueKeys,
  techniqueSessionPath,
} from "./technique";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("technique endpoints", () => {
  it("paths", () => {
    expect(techniqueSessionPath("332904dbe3de")).toBe("/api/technique/sessions/332904dbe3de");
    expect(techniqueSessionPath("a b", 52)).toBe("/api/technique/sessions/a%20b?ref_lap_id=52");
    expect(techniqueBalancePath("df149ca2d149")).toBe("/api/technique/sessions/df149ca2d149/balance");
    expect(techniqueBalancePath("df149ca2d149", null)).toBe("/api/technique/sessions/df149ca2d149/balance");
    expect(techniqueBalancePath("df149ca2d149", "f1_2025")).toBe("/api/technique/sessions/df149ca2d149/balance?car_format=f1_2025");
    expect(techniqueComparePath(52, 54)).toBe("/api/technique/compare?ref=52&lap=54");
  });

  it("session keys sit under analysis:<id>, so the live lap invalidation refreshes them", () => {
    const sid = "332904dbe3de";
    cache.set(techniqueKeys.session(sid), { ok: 1 });
    cache.set(techniqueKeys.session(sid, 54), { ok: 1 });
    cache.set(techniqueKeys.balance(sid), { ok: 1 });
    cache.set(techniqueKeys.balance(sid, "f1_2026"), { ok: 1 });
    cache.set(techniqueKeys.compare(52, 54), { ok: 1 });
    cache.invalidate(`analysis:${sid}`);
    expect(cache.entry(techniqueKeys.session(sid)).stale).toBe(true);
    expect(cache.entry(techniqueKeys.session(sid, 54)).stale).toBe(true);
    expect(cache.entry(techniqueKeys.balance(sid)).stale).toBe(true);
    expect(cache.entry(techniqueKeys.balance(sid, "f1_2026")).stale).toBe(true);
    expect(techniqueKeys.balance(sid, "f1_2026")).not.toBe(techniqueKeys.balance(sid));
    expect(cache.entry(techniqueKeys.compare(52, 54)).stale).toBe(false);
  });

  it("errors: FastAPI's own 404 means the server predates the routes; a 404 with a detail is an unknown session", () => {
    expect(techniqueErrorKind(new ApiError(404, "Not Found"))).toBe("missing");
    expect(techniqueErrorKind(new ApiError(405, "Method Not Allowed"))).toBe("missing");
    expect(techniqueErrorKind(new ApiError(404, "session not found"))).toBe("not_found");
    expect(techniqueErrorKind(new ApiError(409, "no track model yet for this track (complete a clean lap first)"))).toBe("no_model");
    expect(techniqueErrorKind(new Error("boom"))).toBe("other");
    expect(techniqueErrorText(new ApiError(409, "no track model yet for this track (complete a clean lap first)"))).toBe(
      "No track model yet for this track (complete a clean lap first)",
    );
  });

  it("requests go through authFetch and keep the server's detail", async () => {
    const fetchMock = vi.fn(async (url: string) =>
      url.includes("compare")
        ? new Response(JSON.stringify({ detail: "no track model yet for this track (complete a clean lap first)" }), { status: 409 })
        : new Response(JSON.stringify({ session_id: "x" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("sessionStorage", { getItem: () => null, setItem: () => {}, removeItem: () => {} });
    vi.stubGlobal("window", { location: { search: "", hash: "" } });
    await expect(techniqueApi.session("x")).resolves.toEqual({ session_id: "x" });
    await expect(techniqueApi.compare(1, 2)).rejects.toMatchObject({ status: 409 });
    expect(fetchMock.mock.calls[0]![0]).toBe("/api/technique/sessions/x");
  });

  it("every fixture says it is hand-made against the contract, not a recording", () => {
    const blocks = techniqueFixtureBlocks();
    expect(blocks.length).toBeGreaterThanOrEqual(8);
    for (const { name, block } of blocks) {
      expect(name.startsWith("edited-"), name).toBe(true);
      expect(block.tier, name).toBe("edited");
      expect(block.what.length, name).toBeGreaterThan(40);
      expect(block.source, name).toMatch(/hand-made/);
    }
  });
});
