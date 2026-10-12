// F1 spotter endpoints (lib/endpoints/spotter.ts, design spec 8.1-8.2) over the contract fixtures
// (src/test/fixtures/spotter): parsing, tolerance of older/newer servers, and the three calls.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { json, stubBrowser } from "../../test/fakes";
import { spotterFixture } from "../../test/spotter";
import { resetTokenCacheForTests } from "../auth";
import { SPOTTER_DEFAULTS } from "../spotter/types";
import { EndpointError, messageOf } from "./settings";
import { isNotFound, isRadioOff, parseSpotterInfo, parseSpotterSettings, settingsPatch, spotterApi } from "./spotter";

describe("parseSpotterInfo", () => {
  it("keeps the contract's active payload as it is", () => {
    const raw = spotterFixture("contract-active") as Record<string, unknown>;
    expect(parseSpotterInfo(raw)).toEqual(raw);
  });

  it("keeps the other contract payloads", () => {
    for (const n of ["contract-off", "contract-gt7", "contract-low-rate"] as const) {
      const raw = spotterFixture(n);
      expect(parseSpotterInfo(raw), n).toEqual(raw);
    }
  });

  it("refuses an unknown version and non-objects (never a half-read payload)", () => {
    expect(parseSpotterInfo({ ...(spotterFixture("contract-active") as object), v: 2 })).toBeNull();
    for (const raw of [null, undefined, "x", [], 1]) expect(parseSpotterInfo(raw)).toBeNull();
  });

  it("unknown stays unknown: a bare v1 payload has the master OFF, no numbers and empty lists", () => {
    const s = parseSpotterInfo({ v: 1 });
    expect(s).toEqual({
      v: 1,
      settings: { ...SPOTTER_DEFAULTS },
      availability: { available: false, game: null, reason: null },
      status: { active: false, reason: null, motion_hz: null, send_rate_low: false, dims: null, audio: null },
      latency: { n: 0, decide_ms: null, queued_ms: null, started_ms: null, onset_game_ms: null, data_age_ms: null },
      counters: { calls: {}, suppressed_short: 0, dropped: {}, items: 0, skipped: 0, invalid: 0, errors: 0 },
      recent: [],
    });
  });

  it("drops malformed parts and keeps the rest", () => {
    const s = parseSpotterInfo({
      v: 1,
      availability: { available: true, game: "f1_25", reason: "moon_phase" },
      status: { active: true, reason: "warp", motion_hz: -3, dims: { length_m: 99, width_m: 2, formula: "", source: "regs" } },
      latency: { n: 3.7, decide_ms: { p50: "1" }, queued_ms: { p50: 2, p95: Number.NaN, max: 4 } },
      counters: { calls: { car_left: 2, clear_left: -1, bogus: "x" }, items: 10.9 },
      recent: [{ kind: "car_left", t_unix: "now", spoken: 1 }, { spoken: true }, "x", null],
    })!;
    expect(s.availability).toEqual({ available: true, game: "f1_25", reason: null });
    expect(s.status).toMatchObject({ active: true, reason: null, motion_hz: null });
    expect(s.status.dims).toEqual({ length_m: null, width_m: 2, formula: null, source: "regs" });
    expect(s.latency).toMatchObject({ n: 3, decide_ms: null, queued_ms: { p50: 2, p95: null, max: 4 } });
    expect(s.counters).toMatchObject({ calls: { car_left: 2 }, items: 10 });
    expect(s.recent).toEqual([{ t_unix: null, kind: "car_left", side: null, spoken: false, queued_ms: null, started_ms: null }]);
  });

  it("keeps the newest 20 calls, newest first, whatever the order on the wire", () => {
    const oldestFirst = Array.from({ length: 25 }, (_, i) => ({ t_unix: i, kind: "car_left", spoken: true }));
    for (const recent of [oldestFirst, [...oldestFirst].reverse()]) {
      const s = parseSpotterInfo({ v: 1, recent })!;
      expect(s.recent).toHaveLength(20);
      expect(s.recent[0]?.t_unix).toBe(24);
      expect(s.recent.at(-1)?.t_unix).toBe(5);
    }
  });
});

describe("parseSpotterSettings", () => {
  it("out-of-range values fall back to the defaults (the master never to on)", () => {
    expect(
      parseSpotterSettings({
        enabled: "true",
        audio: "no",
        start_delay_s: 25,
        wording: "posh",
        voice: "",
        car_length_m: 2,
        car_width_m: 2.2,
      }),
    ).toEqual({ ...SPOTTER_DEFAULTS, car_width_m: 2.2 });
    expect(parseSpotterSettings({ start_delay_s: 0 }).start_delay_s).toBe(0);
  });
});

describe("settingsPatch", () => {
  it("sends only the keys PUT accepts", () => {
    const patch = { enabled: true, voice: null, junk: 1 } as unknown as Parameters<typeof settingsPatch>[0];
    expect(settingsPatch(patch)).toEqual({ enabled: true, voice: null });
  });
});

describe("calls", () => {
  beforeEach(() => {
    stubBrowser("http://127.0.0.1:8770/#/settings/radio");
    resetTokenCacheForTests();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("GET /api/spotter; PUT a partial JSON body; POST the test with an empty JSON body", async () => {
    const f = vi.fn(async (path: string, _init?: RequestInit) =>
      path === "/api/spotter/test" ? json({ ok: true }) : json(spotterFixture("contract-active")),
    );
    vi.stubGlobal("fetch", f);
    expect((await spotterApi.get()).status.active).toBe(true);
    expect((await spotterApi.update({ enabled: true, start_delay_s: 3 })).settings.enabled).toBe(true);
    await spotterApi.test();
    const calls = f.mock.calls.map(([path, init]) => [path, init?.method ?? "GET", new Headers(init?.headers).get("Content-Type"), init?.body ?? null]);
    expect(calls).toEqual([
      ["/api/spotter", "GET", null, null],
      ["/api/spotter/settings", "PUT", "application/json", '{"enabled":true,"start_delay_s":3}'],
      ["/api/spotter/test", "POST", "application/json", "{}"],
    ]);
  });

  it("a 422 carries the server's words", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ detail: [{ loc: ["body", "start_delay_s"], msg: "must be between 0 and 20" }] }, 422)),
    );
    const err = await spotterApi.update({ start_delay_s: 30 }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(EndpointError);
    expect(messageOf(err)).toBe("start_delay_s: must be between 0 and 20");
  });

  it("the test with no radio connected is a 409 the card explains", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: "No radio is connected." }, 409)));
    const err = await spotterApi.test().catch((e: unknown) => e);
    expect(isRadioOff(err)).toBe(true);
    expect(isNotFound(err)).toBe(false);
  });

  it("an older server without /api/spotter is a 404 the card hides", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: "Not Found" }, 404)));
    const err = await spotterApi.get().catch((e: unknown) => e);
    expect(isNotFound(err)).toBe(true);
    expect(isRadioOff(new Error("x"))).toBe(false);
  });

  it("a payload of an unknown version is an error, not a misread card", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ v: 2 })));
    const err = await spotterApi.get().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(EndpointError);
    expect(messageOf(err)).toContain("does not understand");
  });
});
