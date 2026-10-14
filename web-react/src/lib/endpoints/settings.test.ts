import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { json, stubBrowser } from "../../test/fakes";
import { resetTokenCacheForTests } from "../auth";
import {
  EndpointError,
  errorText,
  fmtTokens,
  fmtUsd,
  isLocalHost,
  keyNameFor,
  llmApi,
  locationOf,
  messageOf,
  startDemoReplay,
  systemApi,
  type Preset,
} from "./settings";

function preset(p: Partial<Preset> & Pick<Preset, "id" | "location">): Preset {
  return {
    label: p.id,
    kind: "openai",
    base_url: "",
    key_name: null,
    cloud_key_name: null,
    key_required: false,
    docs_url: "",
    notes: "",
    suggested: { engineer: null, radio: null },
    suggested_models: [],
    ...p,
  };
}

// The live server's presets (GET /api/llm/providers, 2026-10-11), the fields these rules read.
const LLAMACPP = preset({ id: "llamacpp", location: "local", base_url: "http://127.0.0.1:8081/v1", key_name: "llm_api_key", cloud_key_name: "custom_api_key" });
const ANTHROPIC = preset({ id: "anthropic", kind: "anthropic", location: "cloud", base_url: "https://api.anthropic.com", key_name: "anthropic_api_key", key_required: true });
const CUSTOM = preset({ id: "custom", location: "auto", base_url: "", key_name: "llm_api_key", cloud_key_name: "custom_api_key" });
const LMSTUDIO = preset({ id: "lmstudio", location: "local", base_url: "http://127.0.0.1:1234/v1" });

describe("isLocalHost (mirror of provider_registry.is_local_host)", () => {
  it.each([
    ["localhost", true],
    ["127.0.0.1", true],
    ["::1", true],
    ["[::1]", true],
    ["studio.local", true],
    ["mac.tail1234.ts.net", true],
    ["router.home.arpa", true],
    ["llm", true], // a bare LAN name
    ["10.0.0.5", true],
    ["172.16.0.1", true],
    ["172.31.255.1", true],
    ["192.168.1.20", true],
    ["169.254.1.1", true],
    ["100.64.0.1", true], // Tailscale CGNAT
    ["100.127.255.1", true],
    ["172.32.0.1", false],
    ["100.128.0.1", false],
    ["8.8.8.8", false],
    ["api.openai.com", false],
    ["", false],
  ])("%s -> %s", (host, local) => {
    expect(isLocalHost(host)).toBe(local);
  });
});

describe("locationOf / keyNameFor", () => {
  it("a cloud vendor is always cloud and uses its own key", () => {
    expect(locationOf(ANTHROPIC, "")).toBe("cloud");
    expect(keyNameFor(ANTHROPIC, "http://127.0.0.1:9999")).toBe("anthropic_api_key");
  });

  it("a local preset follows its URL: the default is local, an internet host counts as cloud", () => {
    expect(locationOf(LLAMACPP, "")).toBe("local");
    expect(keyNameFor(LLAMACPP, "")).toBe("llm_api_key");
    expect(locationOf(LLAMACPP, "https://llm.example.com/v1")).toBe("cloud");
    expect(keyNameFor(LLAMACPP, "https://llm.example.com/v1")).toBe("custom_api_key");
  });

  it("an unparseable URL: 'auto' presets count as cloud (the safe side), local ones stay local", () => {
    expect(locationOf(CUSTOM, "")).toBe("cloud");
    expect(locationOf(CUSTOM, "not a url")).toBe("cloud");
    expect(locationOf(LMSTUDIO, "not a url")).toBe("local");
  });

  it("no preset: local, no key", () => {
    expect(locationOf(undefined, "https://x.example")).toBe("local");
    expect(keyNameFor(undefined, "")).toBeNull();
  });

  it("a local preset without a key name has no key field", () => {
    expect(keyNameFor(LMSTUDIO, "")).toBeNull();
  });
});

describe("formatting", () => {
  it("fmtUsd: unknown '-', zero '$0', cents and sub-cent amounts", () => {
    expect(fmtUsd(null)).toBe("-");
    expect(fmtUsd(undefined)).toBe("-");
    expect(fmtUsd(Number.NaN)).toBe("-");
    expect(fmtUsd(0)).toBe("$0");
    expect(fmtUsd(0.0042)).toBe("$0.0042");
    expect(fmtUsd(1.254)).toBe("$1.25");
  });

  it("fmtTokens: plain, one decimal in thousands, whole thousands from 10k", () => {
    expect(fmtTokens(null)).toBe("-");
    expect(fmtTokens(950)).toBe("950");
    expect(fmtTokens(4170)).toBe("4.2k");
    expect(fmtTokens(13071)).toBe("13k");
  });
});

describe("errorText", () => {
  it("passes a string detail through", () => {
    expect(errorText("privacy: acknowledge the notice", "x")).toBe("privacy: acknowledge the notice");
  });

  it("joins pydantic validation errors without the 'body' prefix", () => {
    const detail = [
      { loc: ["body", "budget", "daily_usd"], msg: "Input should be greater than or equal to 0" },
      { loc: ["body", "primary", "timeout_s"], msg: "Input should be a valid number" },
    ];
    expect(errorText(detail, "x")).toBe(
      "budget.daily_usd: Input should be greater than or equal to 0; primary.timeout_s: Input should be a valid number",
    );
  });

  it("falls back for anything else", () => {
    expect(errorText({ weird: true }, "Bad Request")).toBe("Bad Request");
    expect(errorText([], "Bad Request")).toBe("Bad Request");
  });
});

describe("calls", () => {
  beforeEach(() => {
    stubBrowser("http://127.0.0.1:8770/next/#/settings/ai");
    resetTokenCacheForTests();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("a refusal becomes an EndpointError with the status and the server's words", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ detail: "privacy: the privacy notice has changed since this page was loaded" }, 409)),
    );
    const err = await llmApi.saveConfig({} as never).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(EndpointError);
    expect((err as EndpointError).status).toBe(409);
    expect(messageOf(err)).toBe("privacy: the privacy notice has changed since this page was loaded");
  });

  it("PUTs the config as JSON and saves a key without echoing it anywhere but the body", async () => {
    const f = vi.fn(async (_path: string, _init?: RequestInit) => json({ name: "anthropic_api_key", saved: true, masked: "sk-a…cdef", source: "file", note: null }));
    vi.stubGlobal("fetch", f);
    await llmApi.saveKey("anthropic_api_key", "sk-ant-secret");
    const [path, init] = f.mock.calls[0] ?? [];
    expect(path).toBe("/api/llm/keys/anthropic_api_key");
    expect(init?.method).toBe("PUT");
    expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
    expect(JSON.parse(String(init?.body))).toEqual({ value: "sk-ant-secret" });
  });

  it("POSTs every mutation with Content-Type: application/json (the server refuses JSON-less POSTs)", async () => {
    const f = vi.fn(async (_path: string, _init?: RequestInit) => json({}));
    vi.stubGlobal("fetch", f);
    await llmApi.test("primary", "radio");
    await llmApi.models("llamacpp", null);
    await systemApi.replay("/data/captures/a.pwcap", null);
    await systemApi.simulate("coaching-demo", 2026);
    const bodies = f.mock.calls.map(([path, init]) => [path, init?.method, new Headers(init?.headers).get("Content-Type"), JSON.parse(String(init?.body))]);
    expect(bodies).toEqual([
      ["/api/llm/test", "POST", "application/json", { role: "primary", purpose: "radio" }],
      ["/api/llm/models", "POST", "application/json", { provider: "llamacpp", base_url: null }],
      ["/api/replay", "POST", "application/json", { path: "/data/captures/a.pwcap", speed: null, loop: false }],
      ["/api/simulate", "POST", "application/json", { scenario: "coaching-demo", packet_format: 2026 }],
    ]);
  });

  it("asks for provider health only when told to", async () => {
    const f = vi.fn(async (_path: string, _init?: RequestInit) => json({}));
    vi.stubGlobal("fetch", f);
    await llmApi.overview();
    await llmApi.overview(true);
    expect(f.mock.calls.map((c) => c[0])).toEqual(["/api/llm/providers", "/api/llm/providers?health=true"]);
  });

  it("demo replay: always writes the synthetic demo anew (never a stale capture), then replays it at 1x", async () => {
    const story = { intro: "SYNTHETIC: 10 generated laps", beats: [{ laps: [4], when: "after the line", radio: "T5 brake", screen: null, shows: "x" }] };
    const calls: [string, string, unknown][] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (path: string, init?: RequestInit) => {
        calls.push([init?.method ?? "GET", path, init?.body ? JSON.parse(String(init.body)) : null]);
        if (path === "/api/simulate") return json({ path: "/d/synthetic-coaching-demo-2026.pwcap", synthetic: true, lap_times_ms: [], story });
        return json({ replaying: "x", speed: 1 });
      }),
    );
    expect(await startDemoReplay(2026)).toEqual({ path: "/d/synthetic-coaching-demo-2026.pwcap", story });
    expect(calls).toEqual([
      ["POST", "/api/simulate", { scenario: "coaching-demo", packet_format: 2026 }],
      ["POST", "/api/replay", { path: "/d/synthetic-coaching-demo-2026.pwcap", speed: 1, loop: false }],
    ]);
  });
});
