// Lane X's endpoint modules (src/lib/endpoints/{carsetup,connect}.ts): paths, bodies and error details, with fetch
// stubbed (plain node, no server).

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { json, stubBrowser } from "../../test/fakes";
import { resetTokenCacheForTests } from "../auth";
import {
  CARSETUP_KEYS,
  CarSetupError,
  asUnavailable,
  carsetupApi,
  detailText,
  errorText,
  experimentsPath,
  proposeBody,
  qs,
  recommendationPath,
  sessionSetupPath,
} from "../endpoints/carsetup";
import { ConnectError, connectApi } from "../endpoints/connect";
import { fixtures } from "./fixtures";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  resetTokenCacheForTests();
  stubBrowser("http://127.0.0.1:8770/next/#/setup/car");
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

const lastCall = () => {
  const c = fetchMock.mock.calls.at(-1) as [string, RequestInit | undefined] | undefined;
  if (!c) throw new Error("fetch was not called");
  return { path: c[0], init: c[1] ?? {} };
};

describe("car setup paths", () => {
  it("qs leaves unset values out", () => {
    expect(qs({ a: 1, b: null, c: undefined, d: "", e: "x" })).toBe("?a=1&e=x");
    expect(qs({})).toBe("");
  });

  it("recommendation: no style means the driver's skill picks it", () => {
    expect(recommendationPath({ car_format: "f1_2025", track_id: 7, session: "race", conditions: "dry", driver_id: 2 })).toBe(
      "/api/carsetup/recommendation?car_format=f1_2025&track_id=7&session=race&conditions=dry&driver_id=2",
    );
    expect(recommendationPath({ car_format: "f1_2026", track_id: 0, session: "qualifying", conditions: "wet", style: "stable" })).toBe(
      "/api/carsetup/recommendation?car_format=f1_2026&track_id=0&session=qualifying&conditions=wet&style=stable",
    );
  });

  it("session and experiments paths encode ids", () => {
    expect(sessionSetupPath("a/b", { car_format: "f1_2025" })).toBe("/api/carsetup/sessions/a%2Fb?car_format=f1_2025");
    expect(sessionSetupPath("abc")).toBe("/api/carsetup/sessions/abc");
    expect(experimentsPath({ track_id: 7, limit: 20 })).toBe("/api/carsetup/experiments?track_id=7&limit=20");
    expect(experimentsPath()).toBe("/api/carsetup/experiments");
  });

  it("cache keys differ per request", () => {
    const a = CARSETUP_KEYS.recommendation({ car_format: "f1_2025", track_id: 7, session: "race", conditions: "dry" });
    const b = CARSETUP_KEYS.recommendation({ car_format: "f1_2025", track_id: 7, session: "race", conditions: "wet" });
    expect(a).not.toBe(b);
    expect(a.startsWith("carsetup:rec:")).toBe(true);
    expect(CARSETUP_KEYS.experiments({ session_id: "x" }).startsWith("carsetup:experiments:")).toBe(true);
  });

  it("proposeBody sends optional fields only when set", () => {
    expect(proposeBody({ before_session_id: "s", parameter: "rear_wing", to_value: 25, hypothesis: "  ", car_format: null })).toEqual({
      before_session_id: "s",
      parameter: "rear_wing",
      to_value: 25,
    });
    expect(proposeBody({ before_session_id: "s", parameter: "p", to_value: 1, hypothesis: " calmer ", car_format: "f1_2026" })).toEqual({
      before_session_id: "s",
      parameter: "p",
      to_value: 1,
      hypothesis: "calmer",
      car_format: "f1_2026",
    });
  });
});

describe("car setup transport", () => {
  it("GETs the catalogue with same-origin credentials", async () => {
    fetchMock.mockResolvedValueOnce(json(fixtures.catalog()));
    const cat = await carsetupApi.catalog();
    expect(cat.formats).toHaveLength(2);
    expect(lastCall().path).toBe("/api/carsetup/catalog");
    expect(lastCall().init.credentials).toBe("same-origin");
  });

  it("a 404 keeps {reason, alternatives} intact", async () => {
    const recorded = fixtures.unavailableImola2026().body;
    fetchMock.mockResolvedValueOnce(json(recorded, 404));
    const err = await carsetupApi
      .recommendation({ car_format: "f1_2026", track_id: 27, session: "race", conditions: "wet" })
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(CarSetupError);
    const e = err as CarSetupError;
    expect(e.status).toBe(404);
    expect(e.unavailable?.reason).toBe(recorded.detail.reason);
    expect(e.unavailable?.alternatives.length).toBe(recorded.detail.alternatives.length);
    expect(errorText(e)).toBe(recorded.detail.reason);
  });

  it("other errors read FastAPI's detail in words", async () => {
    fetchMock.mockResolvedValueOnce(json({ detail: "experiment 3 is proposed; start it first" }, 409));
    const e = (await carsetupApi.conclude(3).catch((x: unknown) => x)) as CarSetupError;
    expect(e.unavailable).toBeNull();
    expect(errorText(e)).toBe("experiment 3 is proposed; start it first");
    expect(lastCall().init.method).toBe("POST");
    expect(lastCall().path).toBe("/api/carsetup/experiments/3/conclude");
  });

  it("detailText handles strings, validation lists, {reason} and nothing", () => {
    expect(detailText("x")).toBe("x");
    expect(detailText(" ", 500)).toBe("request failed (HTTP 500)");
    expect(detailText([{ loc: ["body", "to_value"], msg: "field required" }])).toBe("to_value: field required");
    expect(detailText({ reason: "no setup" })).toBe("no setup");
    expect(detailText(null)).toBe("request failed");
    expect(asUnavailable({ reason: 1 })).toBeNull();
    expect(errorText(new Error("boom"))).toBe("boom");
  });

  it("propose, start and abandon POST JSON bodies", async () => {
    fetchMock.mockImplementation(async () => json({ id: 1 }));
    await carsetupApi.propose({ before_session_id: "s", parameter: "rear_wing", to_value: 25 });
    expect(lastCall().path).toBe("/api/carsetup/experiments");
    expect(JSON.parse(String(lastCall().init.body))).toEqual({ before_session_id: "s", parameter: "rear_wing", to_value: 25 });
    expect(new Headers(lastCall().init.headers).get("Content-Type")).toBe("application/json");
    await carsetupApi.start(1, "after");
    expect(JSON.parse(String(lastCall().init.body))).toEqual({ after_session_id: "after" });
    await carsetupApi.abandon(1, "  ");
    expect(JSON.parse(String(lastCall().init.body))).toEqual({ reason: null });
    await carsetupApi.abandon(1, " wrong car ");
    expect(JSON.parse(String(lastCall().init.body))).toEqual({ reason: "wrong car" });
  });

  it("sends a hash token as the header (LAN devices)", async () => {
    stubBrowser("http://192.0.2.10:8770/next/#/setup/car?token=T0K");
    fetchMock.mockResolvedValueOnce(json([]));
    await carsetupApi.experiments({ session_id: "s" });
    expect(new Headers(lastCall().init.headers).get("X-Pitwall-Token")).toBe("T0K");
  });
});

describe("connect transport", () => {
  it("GET /api/connect", async () => {
    fetchMock.mockResolvedValueOnce(json(fixtures.connectNoData()));
    const info = await connectApi.get();
    expect(info.integrations).toHaveLength(5);
    expect(lastCall().path).toBe("/api/connect");
  });

  it("PUT /api/integrations/{key} with only the changed fields", async () => {
    fetchMock.mockResolvedValueOnce(json(fixtures.connectNoData().integrations));
    await connectApi.updateIntegration("gt7", { console_ip: "192.168.1.231" });
    expect(lastCall().path).toBe("/api/integrations/gt7");
    expect(lastCall().init.method).toBe("PUT");
    expect(JSON.parse(String(lastCall().init.body))).toEqual({ console_ip: "192.168.1.231" });
  });

  it("422 and 409 details are shown in words", async () => {
    fetchMock.mockResolvedValueOnce(json({ detail: "console IP must be a private LAN address like 192.168.1.100" }, 422));
    const e = (await connectApi.updateIntegration("gt7", { console_ip: "8.8.8.8" }).catch((x: unknown) => x)) as ConnectError;
    expect(e).toBeInstanceOf(ConnectError);
    expect(e.status).toBe(422);
    expect(e.message).toBe("console IP must be a private LAN address like 192.168.1.100");
    fetchMock.mockResolvedValueOnce(json({ detail: [{ msg: "bad" }, { msg: "worse" }] }, 422));
    expect(((await connectApi.integrations().catch((x: unknown) => x)) as ConnectError).message).toBe("bad; worse");
    fetchMock.mockResolvedValueOnce(new Response("oops", { status: 500, statusText: "Server Error" }));
    expect(((await connectApi.get().catch((x: unknown) => x)) as ConnectError).message).toBe("500 Server Error");
  });
});
