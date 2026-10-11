// The validation kit's endpoint module (lane validate): paths, bodies, errors in words, and the device report's
// transport (a beacon when hidden, or a keepalive fetch when the tab carries a token), with fetch stubbed.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { json, stubBrowser } from "../../test/fakes";
import { resetTokenCacheForTests } from "../auth";
import { vfix } from "../validation/testkit";
import {
  NOTES_MAX,
  VALIDATION_FORMAT,
  VALIDATION_KEYS,
  ValidationError,
  isRunId,
  postClientReport,
  startBody,
  validationApi,
  validationErrorText,
  validationPaths,
  verdictBody,
  type ClientReport,
} from "./validation";

let fetchMock: ReturnType<typeof vi.fn>;
const ID = "20261012-193012-a3f1";

beforeEach(() => {
  resetTokenCacheForTests();
  stubBrowser("http://127.0.0.1:8770/#/setup/validation");
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

const lastCall = () => {
  const c = fetchMock.mock.calls.at(-1) as [string, RequestInit | undefined] | undefined;
  if (!c) throw new Error("fetch was not called");
  return { path: c[0], init: c[1] ?? {} };
};

const REPORT: ClientReport = {
  run_id: ID,
  client_id: "5f1c2a9e-7b3d-4c11-9a2e-0d4b8f6e1a77",
  seq: 3,
  reason: "hidden",
  t_client_ms: 1791833500000,
  device: "browser",
  standalone: false,
  secure_context: true,
  origin_kind: "localhost",
  safari_version: null,
  viewport: { w: 1180, h: 820, dpr: 2, orientation: "landscape" },
  visibility: "hidden",
  route: "setup/validation",
  wake: { wanted: false, state: "off" },
  radio: null,
  audio_input_kind: null,
  fps_10s: null,
};

describe("the shared fixture matches the contract", () => {
  it("format, run id, every item state and the report", () => {
    const run = vfix.runFull();
    expect(run.format).toBe(VALIDATION_FORMAT);
    expect(isRunId(run.id)).toBe(true);
    expect(run.items.map((i) => i.id)).toEqual(run.selected_items);
    expect(run.evidence?.cues[0]?.heard_vs_point_m).toBeCloseTo(-3.4);
    expect(vfix.run().evidence).toBeUndefined();
    const rep = vfix.report();
    expect(rep.disclaimer).toBe(
      "This report never changes capability statuses. Review it, then update src/pitwall/capabilities.py and docs/status.md by hand.",
    );
    // The catalogue holds every item the example run uses.
    const ids = new Set(vfix.catalog().items.map((i) => i.id));
    for (const id of run.selected_items) expect(ids.has(id)).toBe(true);
  });
});

describe("paths and bodies", () => {
  it("run ids are validated before they reach a path", () => {
    expect(isRunId(ID)).toBe(true);
    expect(isRunId("../etc")).toBe(false);
    expect(isRunId("20261012-193012-A3F1")).toBe(false);
    expect(isRunId(null)).toBe(false);
  });

  it("every endpoint's path", () => {
    expect(validationPaths.catalog()).toBe("/api/validation/catalog");
    expect(validationPaths.active()).toBe("/api/validation/active");
    expect(validationPaths.run(ID)).toBe(`/api/validation/runs/${ID}`);
    expect(validationPaths.run(ID, "full")).toBe(`/api/validation/runs/${ID}?detail=full`);
    expect(validationPaths.verdict(ID, "a/b")).toBe(`/api/validation/runs/${ID}/items/a%2Fb/verdict`);
    expect(validationPaths.inputCheck(ID, "gt7_ps5")).toBe(`/api/validation/runs/${ID}/items/gt7_ps5/input-check`);
    expect(validationPaths.ptt(ID, "m88")).toBe(`/api/validation/runs/${ID}/records/ptt/m88`);
    expect(validationPaths.reportMd(ID)).toBe(`/api/validation/runs/${ID}/report.md`);
    expect(validationPaths.reportMd(ID, true)).toBe(`/api/validation/runs/${ID}/report.md?redact_transcripts=true`);
    expect(validationPaths.client()).toBe("/api/validation/client");
  });

  it("start: optional fields only when set", () => {
    expect(startBody(null, null, null)).toEqual({});
    expect(startBody(["a", "b"], "  First rig run ", true)).toEqual({ items: ["a", "b"], label: "First rig run", radio_prompts: true });
    expect(startBody([], "   ", false)).toEqual({ items: [], radio_prompts: false });
  });

  it("verdict: notes trimmed and cut, empty maps left out, null clears", () => {
    expect(verdictBody("worked", "  ", {}, {})).toEqual({ verdict: "worked" });
    expect(verdictBody("didnt", " slow ", { airpod_used: true }, { first_look: "corner" })).toEqual({
      verdict: "didnt",
      notes: "slow",
      attestations: { airpod_used: true },
      extra: { first_look: "corner" },
    });
    expect(verdictBody("worked", "x".repeat(NOTES_MAX + 50), {}, {}).notes).toHaveLength(NOTES_MAX);
    expect(verdictBody(null, "kept?", { a: true }, {})).toEqual({ verdict: null });
  });

  it("cache keys", () => {
    expect(VALIDATION_KEYS.run(ID)).toBe(`validation:run:${ID}`);
    expect(VALIDATION_KEYS.full(ID)).not.toBe(VALIDATION_KEYS.run(ID));
    // invalidating the run list must not reach a run's own key, and the other way round
    expect(VALIDATION_KEYS.run(ID).startsWith(VALIDATION_KEYS.runs)).toBe(false);
  });
});

describe("requests", () => {
  it("GET and POST with JSON bodies", async () => {
    fetchMock.mockImplementation(async () => json(vfix.run()));
    await validationApi.run(ID);
    expect(lastCall().path).toBe(`/api/validation/runs/${ID}`);
    await validationApi.verdict(ID, "cues_timing", { verdict: "worked" });
    const { path, init } = lastCall();
    expect(path).toBe(`/api/validation/runs/${ID}/items/cues_timing/verdict`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ verdict: "worked" });
    await validationApi.next(ID);
    expect(JSON.parse(String(lastCall().init.body))).toEqual({});
    await validationApi.finish(ID, "  ");
    expect(JSON.parse(String(lastCall().init.body))).toEqual({ notes: null });
    await validationApi.inputCheck(ID, "ac_ps5", { phase: "left", rotation_deg: 900 });
    expect(JSON.parse(String(lastCall().init.body))).toEqual({ phase: "left", rotation_deg: 900 });
    await validationApi.markPtt(ID, "m88", false);
    expect(JSON.parse(String(lastCall().init.body))).toEqual({ heard_right: false });
  });

  it("errors carry the server's detail in words; an older server says so", async () => {
    fetchMock.mockResolvedValue(json({ detail: "a validation run is already active" }, 409));
    const e = await validationApi.start({}).catch((x: unknown) => x);
    expect(e).toBeInstanceOf(ValidationError);
    expect((e as ValidationError).status).toBe(409);
    expect(validationErrorText(e)).toBe("a validation run is already active");
    fetchMock.mockResolvedValue(json({ detail: "Not Found" }, 404));
    const old = await validationApi.catalog().catch((x: unknown) => x);
    expect(validationErrorText(old)).toBe("This server has no validation kit yet: update Pitwall on the Mac.");
    fetchMock.mockResolvedValue(json({ detail: "unknown run" }, 404));
    expect(validationErrorText(await validationApi.run(ID).catch((x: unknown) => x))).toBe("unknown run");
    fetchMock.mockResolvedValue(json({ detail: [{ msg: "String should have at most 2000 characters" }] }, 422));
    expect(validationErrorText(await validationApi.finish(ID, "x").catch((x: unknown) => x))).toBe("String should have at most 2000 characters");
    expect(validationErrorText(new Error("offline"))).toBe("offline");
  });

  it("report.md comes back as text", async () => {
    fetchMock.mockResolvedValue(new Response("# Pitwall validation run", { status: 200, headers: { "Content-Type": "text/markdown" } }));
    expect(await validationApi.reportMarkdown(ID, true)).toBe("# Pitwall validation run");
    expect(lastCall().path).toBe(`/api/validation/runs/${ID}/report.md?redact_transcripts=true`);
  });
});

describe("device reports", () => {
  it("204 ok, 409 no run, anything else an error; a network failure never throws", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    expect(await postClientReport({ ...REPORT, reason: "interval" })).toBe("ok");
    expect(JSON.parse(String(lastCall().init.body))).toMatchObject({ run_id: ID, seq: 3 });
    fetchMock.mockResolvedValue(json({ detail: "no active run" }, 409));
    expect(await postClientReport(REPORT)).toBe("no_run");
    fetchMock.mockResolvedValue(json({ detail: "bad" }, 422));
    expect(await postClientReport(REPORT)).toBe("error");
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    expect(await postClientReport(REPORT)).toBe("error");
  });

  it("hidden: a beacon when nothing needs a token header", async () => {
    const beacon = vi.fn(() => true);
    vi.stubGlobal("navigator", { sendBeacon: beacon });
    expect(await postClientReport(REPORT, true)).toBe("ok");
    expect(beacon).toHaveBeenCalledTimes(1);
    expect(fetchMock).not.toHaveBeenCalled();
    const call = beacon.mock.calls[0] as unknown as [string, Blob];
    expect(call[0]).toBe("/api/validation/client");
    expect(JSON.parse(await call[1].text())).toMatchObject({ reason: "hidden" });
  });

  it("hidden with a tab token: a keepalive fetch that carries it", async () => {
    stubBrowser("http://192.168.1.20:8770/#/drive/radio?token=abc");
    resetTokenCacheForTests();
    const beacon = vi.fn(() => true);
    vi.stubGlobal("navigator", { sendBeacon: beacon });
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    expect(await postClientReport(REPORT, true)).toBe("ok");
    expect(beacon).not.toHaveBeenCalled();
    const { init } = lastCall();
    expect(init.keepalive).toBe(true);
    expect(new Headers(init.headers).get("X-Pitwall-Token")).toBe("abc");
  });
});
