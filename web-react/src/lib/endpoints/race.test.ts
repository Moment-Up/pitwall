import { afterEach, describe, expect, it, vi } from "vitest";
import { raceView } from "../raceradio/testkit";
import { normaliseRaceSettings, raceApi, raceKeys } from "./race";
import { isMissingRoute } from "./review";

describe("race-radio endpoints", () => {
  afterEach(() => vi.unstubAllGlobals());

  function stubFetch(body: unknown, status = 200) {
    const f = vi.fn(async (_url: string, _init?: RequestInit) =>
      new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
    );
    vi.stubGlobal("fetch", f);
    vi.stubGlobal("window", { location: { protocol: "http:", host: "127.0.0.1:8770", pathname: "/", search: "", hash: "" } });
    vi.stubGlobal("sessionStorage", { getItem: () => null, setItem: () => {}, removeItem: () => {} });
    return f;
  }

  it("cache keys", () => {
    expect(raceKeys).toEqual({ live: "race:live", settings: "race:settings" });
  });

  it("the live view: version 1 is read and sanitised, an unknown contract is ignored (null), never guessed", async () => {
    const f = stubFetch(raceView("edited-race-gt7-grid"));
    expect(await raceApi.live()).toMatchObject({ game: "gt7", mode: "race", position: 8, cars: 14 });
    expect(String(f.mock.calls[0]?.[0])).toContain("/api/race/live");
    stubFetch({ version: 1, mode: "off", reason: "no live session" });
    expect(await raceApi.live()).toMatchObject({ mode: "off", reason: "no live session", position: null, calls: [] });
    stubFetch({ version: 2, mode: "race" });
    expect(await raceApi.live()).toBeNull();
  });

  it("a server without race radio answers FastAPI's own 404", async () => {
    stubFetch({ detail: "Not Found" }, 404);
    const e = await raceApi.live().catch((x: unknown) => x);
    expect(isMissingRoute(e)).toBe(true);
    const e2 = await raceApi.settings().catch((x: unknown) => x);
    expect(isMissingRoute(e2)).toBe(true);
  });

  it("settings: off unless the Mac says true", async () => {
    stubFetch({ online_names: true });
    expect(await raceApi.settings()).toEqual({ online_names: true });
    stubFetch({ online_names: "yes" });
    expect(await raceApi.settings()).toEqual({ online_names: false });
    expect(normaliseRaceSettings(null)).toEqual({ online_names: false });
    expect(normaliseRaceSettings({})).toEqual({ online_names: false });
  });

  it("saving PUTs the whole body and answers what the Mac stored", async () => {
    const f = stubFetch({ online_names: false });
    expect(await raceApi.saveSettings({ online_names: true })).toEqual({ online_names: false });
    const [url, init] = f.mock.calls[0]!;
    expect(String(url)).toContain("/api/race/settings");
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(String(init?.body))).toEqual({ online_names: true });
  });

  it("a refused change carries the server's reason", async () => {
    stubFetch({ detail: "online_names must be true or false" }, 422);
    const e = await raceApi.saveSettings({ online_names: true }).catch((x: unknown) => x);
    expect(String(e)).toContain("422: online_names must be true or false");
  });
});
