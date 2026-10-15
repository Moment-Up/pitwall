// Technique knowledge endpoint: paths and cache keys (a session's variant under "analysis:<id>", refreshed by a
// completed lap), the fallback to the plain graph when a session is not known, a server before the graph (FastAPI's
// own 404) and a graph that did not load (503 with {message, errors}).
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api";
import { cache } from "../cache";
import { isMissingKnowledge, knowledgeApi, knowledgeKeys, knowledgePath } from "./knowledge";

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubFetch(handler: (url: string) => Response) {
  const fetchMock = vi.fn(async (url: string) => handler(url));
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("sessionStorage", { getItem: () => null, setItem: () => {}, removeItem: () => {} });
  vi.stubGlobal("window", { location: { search: "", hash: "" } });
  return fetchMock;
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

describe("technique knowledge endpoint", () => {
  it("paths and keys", () => {
    expect(knowledgePath()).toBe("/api/technique/knowledge");
    expect(knowledgePath(null)).toBe("/api/technique/knowledge");
    expect(knowledgePath("a b")).toBe("/api/technique/knowledge?session=a%20b");
    expect(knowledgeKeys.graph()).toBe("technique-knowledge");
    const sid = "332904dbe3de";
    cache.set(knowledgeKeys.graph(sid), { ok: 1 });
    cache.set(knowledgeKeys.graph(), { ok: 1 });
    cache.invalidate(`analysis:${sid}`);
    expect(cache.entry(knowledgeKeys.graph(sid)).stale).toBe(true);
    expect(cache.entry(knowledgeKeys.graph()).stale).toBe(false);
  });

  it("asks for the session's variant, and falls back to the plain graph for a session the server does not know", async () => {
    const f = stubFetch((url) => (url.includes("session=") ? json({ detail: "session not found" }, 404) : json({ valid: true, phases: [] })));
    await expect(knowledgeApi.graph("nope")).resolves.toEqual({ valid: true, phases: [] });
    expect(f.mock.calls.map((c) => c[0])).toEqual(["/api/technique/knowledge?session=nope", "/api/technique/knowledge"]);
  });

  it("a server that ignores ?session= answers the plain graph in one request", async () => {
    const f = stubFetch(() => json({ valid: true, phases: [] }));
    await expect(knowledgeApi.graph("332904dbe3de")).resolves.toMatchObject({ valid: true });
    expect(f).toHaveBeenCalledTimes(1);
  });

  it("a server before the graph: FastAPI's own 404, reported as missing (no retry hides it)", async () => {
    const f = stubFetch(() => json({ detail: "Not Found" }, 404));
    const err = await knowledgeApi.graph("x").catch((e: unknown) => e);
    expect(isMissingKnowledge(err)).toBe(true);
    expect(f).toHaveBeenCalledTimes(1);
    expect(isMissingKnowledge(new ApiError(404, "session not found"))).toBe(false);
  });

  it("a graph that did not load: the 503's message and how many problems", async () => {
    stubFetch(() =>
      json({ detail: { message: "technique knowledge is unavailable: the graph did not load", errors: ["a", "b"] } }, 503),
    );
    await expect(knowledgeApi.graph()).rejects.toMatchObject({
      status: 503,
      message: "503: technique knowledge is unavailable: the graph did not load (2 problems)",
    });
  });
});
