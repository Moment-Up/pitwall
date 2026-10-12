// Car health endpoints (lane "health"): the paths, the contract versions, the settings PUT and the error words.
import { afterEach, describe, expect, it, vi } from "vitest";
import { healthView, racecraftView, settingsFixture } from "../carhealth/testkit";
import { DEFAULT_CAR_HEALTH_SETTINGS } from "../carhealth/view";
import { carHealthApi, CarHealthError, carHealthErrorText, carHealthKeys } from "./carhealth";
import { isMissingRoute } from "./review";

describe("car health endpoints", () => {
  afterEach(() => vi.unstubAllGlobals());

  function stubFetch(body: unknown, status = 200) {
    const f = vi.fn(
      async (_url: unknown, _init?: RequestInit) =>
        new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
    );
    vi.stubGlobal("fetch", f);
    vi.stubGlobal("window", { location: { protocol: "http:", host: "127.0.0.1:8770", pathname: "/", search: "", hash: "" } });
    vi.stubGlobal("sessionStorage", { getItem: () => null, setItem: () => {}, removeItem: () => {} });
    return f;
  }

  const url = (f: ReturnType<typeof stubFetch>, i = 0) => String((f.mock.calls[i] as unknown[])[0]);

  it("cache keys are their own (never under 'session:' or the service's 'health')", () => {
    expect(carHealthKeys).toEqual({ live: "carhealth:live", racecraft: "racecraft:live", settings: "carhealth:settings" });
  });

  it("the live car-health view: version 1 is read, anything else is null (never guessed)", async () => {
    const f = stubFetch(healthView("edited-live-forza-fuel-ok"));
    const v = await carHealthApi.live();
    expect(url(f)).toContain("/api/car-health/live");
    expect(v?.fuel?.laps_of_fuel).toBe(7.6);
    stubFetch({ version: 2 });
    expect(await carHealthApi.live()).toBeNull();
    stubFetch(null);
    expect(await carHealthApi.live()).toBeNull();
  });

  it("the live racecraft view, including the off shape", async () => {
    const f = stubFetch(racecraftView("edited-racecraft-off"));
    expect(await carHealthApi.racecraft()).toMatchObject({ mode: "off", reason: "attack and defend need an F1 race" });
    expect(url(f)).toContain("/api/racecraft/live");
  });

  it("settings: GET reads all four; PUT sends all four as JSON and answers with what the Mac stored", async () => {
    let f = stubFetch(settingsFixture("edited-settings-default"));
    expect(await carHealthApi.settings()).toEqual(DEFAULT_CAR_HEALTH_SETTINGS);
    expect(url(f)).toContain("/api/car-health/settings");
    const next = { ...DEFAULT_CAR_HEALTH_SETTINGS, slip_calls: "normal" as const };
    f = stubFetch(next);
    expect(await carHealthApi.saveSettings(next)).toEqual(next);
    const init = (f.mock.calls[0] as unknown[])[1] as RequestInit;
    expect(init.method).toBe("PUT");
    expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
    expect(JSON.parse(String(init.body))).toEqual(next);
  });

  it("a 400 says why in the server's words; a payload this dashboard does not understand is an error", async () => {
    stubFetch({ detail: "slip_calls must be off, detailed or normal" }, 400);
    const e = await carHealthApi.saveSettings(DEFAULT_CAR_HEALTH_SETTINGS).catch((x: unknown) => x);
    expect(e).toBeInstanceOf(CarHealthError);
    expect(carHealthErrorText(e)).toBe("slip_calls must be off, detailed or normal");
    stubFetch({ detail: [{ loc: ["body", "fuel_calls"], msg: "Input should be a valid boolean" }] }, 422);
    expect(carHealthErrorText(await carHealthApi.saveSettings(DEFAULT_CAR_HEALTH_SETTINGS).catch((x: unknown) => x))).toBe(
      "fuel_calls: Input should be a valid boolean",
    );
    stubFetch({ tyre_calls: true });
    expect(carHealthErrorText(await carHealthApi.settings().catch((x: unknown) => x))).toMatch(/doesn't understand/);
  });

  it("an older server (FastAPI's own 404) is told apart from the route answering", async () => {
    stubFetch({ detail: "Not Found" }, 404);
    expect(isMissingRoute(await carHealthApi.settings().catch((x: unknown) => x))).toBe(true);
    stubFetch({ detail: "no live session" }, 404);
    expect(isMissingRoute(await carHealthApi.live().catch((x: unknown) => x))).toBe(false);
  });
});
