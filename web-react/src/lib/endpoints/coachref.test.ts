import { afterEach, describe, expect, it, vi } from "vitest";
import { crFixture } from "../../test/coachref";
import { ApiError } from "../api";
import { cache } from "../cache";
import {
  coachrefApi,
  coachrefErrorText,
  coachrefKeys,
  compareWithReference,
  drillKindFor,
  isConflict,
  OBSERVATION_DRILL_KIND,
  type DrillView,
  type RefOptionsResponse,
} from "./coachref";

type Call = { url: string; method: string; body: unknown };

function stubFetch(responses: { status?: number; body?: unknown }[] | ((url: string) => { status?: number; body?: unknown })) {
  const calls: Call[] = [];
  let i = 0;
  const f = vi.fn(async (input: unknown, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, method: init?.method ?? "GET", body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const r = typeof responses === "function" ? responses(url) : (responses[Math.min(i++, responses.length - 1)] ?? {});
    const status = r.status ?? 200;
    if (status === 204) return new Response(null, { status });
    return new Response(JSON.stringify(r.body ?? {}), { status, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", f);
  vi.stubGlobal("window", { location: { protocol: "http:", host: "127.0.0.1:8810", pathname: "/", search: "", hash: "" } });
  vi.stubGlobal("sessionStorage", { getItem: () => null, setItem: () => {}, removeItem: () => {} });
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
  cache.clear();
});

describe("coachref endpoints follow the spec's contract (6.1)", () => {
  it("GET /options for the seated driver or a named one", async () => {
    const calls = stubFetch([{ body: crFixture<RefOptionsResponse>("options-suzuka-sam") }]);
    const r = await coachrefApi.options();
    await coachrefApi.options(3);
    expect(calls[0]).toMatchObject({ url: "/api/coachref/options", method: "GET" });
    expect(calls[1]?.url).toBe("/api/coachref/options?driver_id=3");
    expect(r.options.map((o) => o.kind)).toEqual(["own_best", "household_best", "driver_best", "driver_best", "lap", "lap"]);
  });

  it("PUT /choice with the body as given, and every coachref answer goes stale", async () => {
    const calls = stubFetch([{ body: crFixture("choice-next-lap") }]);
    cache.set(coachrefKeys.options(1), { stale: "no" });
    cache.set(coachrefKeys.drills({ driver_id: 1 }), []);
    cache.set("sessions", []);
    const r = await coachrefApi.setChoice({ driver_id: 1, kind: "driver_best", target_driver_id: 2, scope: "all_tracks" });
    expect(calls[0]).toEqual({
      url: "/api/coachref/choice",
      method: "PUT",
      body: { driver_id: 1, kind: "driver_best", target_driver_id: 2, scope: "all_tracks" },
    });
    expect(r.applies).toBe("next_lap");
    expect(cache.entry(coachrefKeys.options(1)).stale).toBe(true);
    expect(cache.entry(coachrefKeys.drills({ driver_id: 1 })).stale).toBe(true);
    expect(cache.entry("sessions").stale).toBe(false);
  });

  it("GET and DELETE /choice (204 has no body)", async () => {
    const calls = stubFetch([{ body: { all_tracks: null, track: null, effective: {} } }, { status: 204 }]);
    await coachrefApi.choice(1, "f1_25", "f1:13");
    await expect(coachrefApi.deleteChoice(1, "f1_25", "f1:13")).resolves.toBeUndefined();
    expect(calls[0]?.url).toBe("/api/coachref/choice?driver_id=1&game=f1_25&track_id=f1%3A13");
    expect(calls[1]).toMatchObject({ url: "/api/coachref/choice?driver_id=1&game=f1_25&track_id=f1%3A13", method: "DELETE" });
  });

  it("candidates, compare and the drill endpoints", async () => {
    const calls = stubFetch(() => ({ body: {} }));
    await coachrefApi.candidates(66);
    await coachrefApi.compare(64, 66);
    await coachrefApi.drillOptions({ corner: "T7" });
    await coachrefApi.drillOptions({ corner_ref: "Turn 11" });
    await coachrefApi.startDrill({ corner: "T7", kind: "brake_point", laps: 5, source: "work_on", observation_kind: "brake_early" });
    await coachrefApi.activeDrill();
    await coachrefApi.stopDrill();
    await coachrefApi.drills({ driver_id: 1, game: "f1_25", track_id: "f1:13", car_id: null, limit: 20 });
    await coachrefApi.drills({ include_empty: true });
    await coachrefApi.drill(14);
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      "GET /api/coachref/candidates?lap_id=66",
      "GET /api/coachref/compare?ref=64&lap=66",
      "GET /api/coachref/drills/options?corner=T7",
      "GET /api/coachref/drills/options?corner_ref=Turn+11",
      "POST /api/coachref/drills",
      "GET /api/coachref/drills/active",
      "POST /api/coachref/drills/active/stop",
      "GET /api/coachref/drills?driver_id=1&game=f1_25&track_id=f1%3A13&limit=20",
      "GET /api/coachref/drills?include_empty=true",
      "GET /api/coachref/drills/14",
    ]);
    expect(calls[4]?.body).toEqual({ corner: "T7", kind: "brake_point", laps: 5, source: "work_on", observation_kind: "brake_early" });
  });

  it("a refusal keeps the server's sentence without the status (409), and says what a 503 or an old server means", async () => {
    stubFetch([{ status: 409, body: { detail: "A drill on T11 is running: lap 2 of 5. Stop it first." } }]);
    const e = await coachrefApi.startDrill({ corner: "T3" }).catch((x: unknown) => x);
    expect(e).toBeInstanceOf(ApiError);
    expect(isConflict(e)).toBe(true);
    expect(coachrefErrorText(e)).toBe("A drill on T11 is running: lap 2 of 5. Stop it first.");
    expect(coachrefErrorText(new ApiError(503, "busy"))).toMatch(/try again/);
    expect(coachrefErrorText(new ApiError(404, "Not Found"))).toMatch(/does not have reference choice/);
    stubFetch([{ status: 422, body: { detail: [{ loc: ["body", "laps"], msg: "too big" }] } }]);
    const v = await coachrefApi.startDrill({ corner: "T3", laps: 40 }).catch((x: unknown) => x);
    expect(coachrefErrorText(v)).toBe("That request was not accepted");
  });

  it("Compare falls back to /api/compare on a server without coachref (404 Not Found), not on other errors", async () => {
    const calls = stubFetch((url) =>
      url.startsWith("/api/coachref") ? { status: 404, body: { detail: "Not Found" } } : { body: { comparison: {}, observations: [], track_model: null } },
    );
    const r = await compareWithReference(64, 66);
    expect(calls.map((c) => c.url)).toEqual(["/api/coachref/compare?ref=64&lap=66", "/api/compare?ref=64&lap=66"]);
    expect(r.reference).toBeUndefined();
    stubFetch(() => ({ status: 404, body: { detail: "lap 66 not found" } }));
    await expect(compareWithReference(64, 66)).rejects.toThrow("404: lap 66 not found");
  });

  it("every key lives under coachref: (one invalidate refreshes them all)", () => {
    for (const k of [
      coachrefKeys.options(null),
      coachrefKeys.candidates(1),
      coachrefKeys.drillOptions("T3"),
      coachrefKeys.drills({}),
      coachrefKeys.drill(1),
    ]) {
      expect(k.startsWith(coachrefKeys.all)).toBe(true);
    }
    expect(coachrefKeys.drills({ driver_id: 1, car_id: null })).not.toBe(coachrefKeys.drills({ driver_id: 1, car_id: "f1:team:41" }));
  });
});

describe("drill kinds from coaching points (spec 3.4.1)", () => {
  it("maps the corrective kinds and nothing else", () => {
    expect(drillKindFor("brake_early")).toBe("brake_point");
    expect(drillKindFor("brake_late_overdrive")).toBe("brake_point");
    expect(drillKindFor("low_min_speed")).toBe("min_speed");
    for (const k of ["overspeed_apex", "late_throttle", "coasting"]) expect(drillKindFor(k)).toBe("exit_speed");
    for (const k of ["exit_gain", "incident", "drill", "toString", "", null, undefined]) expect(drillKindFor(k)).toBeNull();
    expect(Object.values(OBSERVATION_DRILL_KIND)).not.toContain("entry_speed"); // manual only
  });
});

describe("fixtures match the contract (6.2)", () => {
  it("a DrillView carries every contract key", () => {
    const keys: (keyof DrillView)[] = [
      "id", "driver_id", "session_id", "game", "track_id", "car_id", "corner", "corner_label", "corner_voice", "kind",
      "skill_label", "source", "laps_target", "target", "tolerance", "unit", "baseline", "target_text", "note", "reference",
      "status", "stop_reason", "started_unix", "ended_unix", "attempts", "hits", "scored", "best", "best_delta", "trend",
      "summary_text", "synthetic",
    ];
    for (const name of ["drill-active", "drill-completed"]) {
      const d = crFixture<DrillView>(name);
      for (const k of keys) expect(d, `${name}.${k}`).toHaveProperty(k);
      for (const a of d.attempts) {
        for (const k of ["attempt", "lap_id", "lap_number", "value", "target", "delta", "outcome", "reason", "corner_time_s", "corner_time_delta_s", "text", "short"]) {
          expect(a, `${name} attempt ${a.attempt}.${k}`).toHaveProperty(k);
        }
        expect(a.short.length).toBeLessThanOrEqual(48);
      }
    }
  });
});
