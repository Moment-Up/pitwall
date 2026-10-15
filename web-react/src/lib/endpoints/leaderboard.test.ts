import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api";
import { RequestCache } from "../cache";
import { leaderboardApi, leaderboardKeys, leaderboardUrl, recordsUrl } from "./leaderboard";
import { isMissingRoute } from "./review";

const KEY = "f1_25~f1:17~4323~f1:team:7~f1~0~race~dry~b2.a?.t?.g3.l2";

describe("leaderboard urls (docs/leaderboard.md)", () => {
  it("a board by its key, escaped, with the optional car generation", () => {
    expect(leaderboardUrl({ key: KEY })).toBe(
      "/api/leaderboard?key=f1_25%7Ef1%3A17%7E4323%7Ef1%3Ateam%3A7%7Ef1%7E0%7Erace%7Edry%7Eb2.a%3F.t%3F.g3.l2",
    );
    expect(leaderboardUrl({ key: KEY, car_generation: "f1_2025" })).toMatch(/&car_generation=f1_2025$/);
    expect(leaderboardUrl({ key: KEY, car_generation: null })).not.toContain("car_generation");
  });

  it("a board by fields: only the parts that are set; '?' asks for the unknown bucket, never any", () => {
    expect(leaderboardUrl({ game: "f1_25", track_id: "f1:17" })).toBe("/api/leaderboard?game=f1_25&track_id=f1%3A17");
    expect(leaderboardUrl({ game: "f1_25", track_id: "f1:17", car_id: "?", category: "time_trial", assists: "b2.a1.t2.g3.l2" })).toBe(
      "/api/leaderboard?game=f1_25&track_id=f1%3A17&car_id=%3F&category=time_trial&assists=b2.a1.t2.g3.l2",
    );
    expect(leaderboardUrl({ game: "gt7", track_id: "gt7:x", car_id: null, length_m: 3800 })).toBe(
      "/api/leaderboard?game=gt7&track_id=gt7%3Ax&length_m=3800",
    );
  });

  it("the record index, optionally one track and one driver's boards", () => {
    expect(recordsUrl()).toBe("/api/records");
    expect(recordsUrl({ game: "f1_25", track_id: "f1:17", driver_id: 1 })).toBe("/api/records?game=f1_25&track_id=f1%3A17&driver_id=1");
    expect(recordsUrl({ car_generation: "f1_2026" })).toBe("/api/records?car_generation=f1_2026");
  });

  it("cache keys live under driver-sessions: so a lap, a driver switch or a moved session refreshes them", () => {
    const cache = new RequestCache();
    const b = leaderboardKeys.board({ key: KEY });
    const r = leaderboardKeys.records({ game: "f1_25", track_id: "f1:17", driver_id: 1 });
    cache.set(b, {});
    cache.set(r, {});
    cache.invalidate("driver-sessions:");
    expect(cache.entry(b).stale).toBe(true);
    expect(cache.entry(r).stale).toBe(true);
    expect(b).not.toBe(leaderboardKeys.board({ key: KEY, car_generation: "f1_2025" }));
  });
});

describe("leaderboard client", () => {
  afterEach(() => vi.unstubAllGlobals());

  function stubFetch(status: number, body: unknown): string[] {
    const urls: string[] = [];
    vi.stubGlobal("fetch", async (url: string) => {
      urls.push(url);
      return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    });
    vi.stubGlobal("window", { location: { protocol: "http:", host: "127.0.0.1:8825", pathname: "/", search: "", hash: "" } });
    vi.stubGlobal("sessionStorage", { getItem: () => null, setItem: () => {}, removeItem: () => {} });
    return urls;
  }

  it("reads a board and the index", async () => {
    const urls = stubFetch(200, { boards: [], count: 0 });
    await expect(leaderboardApi.records({ driver_id: 2 })).resolves.toEqual({ boards: [], count: 0 });
    expect(urls[0]).toContain("/api/records?driver_id=2");
  });

  it("a key that does not parse is the server's 422; an older server's 404 is a missing route", async () => {
    stubFetch(422, { detail: "bad key" });
    const bad = await leaderboardApi.board({ key: "x" }).catch((e: unknown) => e);
    expect(bad).toBeInstanceOf(ApiError);
    expect((bad as ApiError).status).toBe(422);
    expect((bad as ApiError).message).toBe("422: bad key");
    stubFetch(404, { detail: "Not Found" });
    const missing = await leaderboardApi.board({ key: KEY }).catch((e: unknown) => e);
    expect(isMissingRoute(missing)).toBe(true);
  });
});
