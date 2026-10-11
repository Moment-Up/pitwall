import { describe, expect, it } from "vitest";
import type { Overview, Preset, ProviderSpec } from "../../../lib/endpoints/settings";
import {
  blankSpec,
  buildConfig,
  changeProvider,
  cloudInUse,
  configKey,
  draftFromOverview,
  fromSpec,
  modelLabel,
  modelOptions,
  otherSide,
  pricedModels,
  primarySide,
  quickPicksFor,
  saveState,
  secs,
  setMode,
  shortModel,
  showCloud,
  showLocal,
  toSpecIn,
  type AiDraft,
} from "./draft";

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

// Shapes from the live server (GET /api/llm/providers, 2026-10-11).
const PRESETS: Preset[] = [
  preset({ id: "llamacpp", location: "local", base_url: "http://127.0.0.1:8081/v1", key_name: "llm_api_key", cloud_key_name: "custom_api_key" }),
  preset({
    id: "anthropic",
    kind: "anthropic",
    location: "cloud",
    base_url: "https://api.anthropic.com",
    key_name: "anthropic_api_key",
    key_required: true,
    suggested: { engineer: "claude-opus-5-5", radio: "claude-haiku-5-5" },
    suggested_models: ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"],
  }),
  preset({ id: "openai", location: "cloud", base_url: "https://api.openai.com/v1", key_name: "openai_api_key", key_required: true }),
  preset({ id: "custom", location: "auto", key_name: "llm_api_key", cloud_key_name: "custom_api_key" }),
];

function spec(p: Partial<ProviderSpec> & Pick<ProviderSpec, "provider">): ProviderSpec {
  return { base_url: null, model: null, models: { engineer: null, radio: null }, timeout_s: 90, max_tokens: 350, effort: "low", ...p };
}

function overview(config: Partial<Overview["config"]> = {}, noticeVersion = 1): Overview {
  return {
    presets: PRESETS,
    config: {
      version: 1,
      enabled: true,
      primary: spec({ provider: "llamacpp" }),
      fallback: null,
      privacy: { cloud_enabled: false, notice_version: 0, acknowledged_at: null, redact_driver_names: true, notice_acknowledged: false },
      budget: { daily_usd: null },
      prices: {},
      ...config,
    },
    status: { version: 1, source: "defaults", error: null, enabled: true, mode: "local", providers: [] },
    keys: {},
    privacy_notice: { version: noticeVersion, points: ["Cloud AI sends data to a third-party company."] },
    purposes: ["engineer", "radio"],
    efforts: ["low", "medium", "high", "xhigh", "max"],
    prices: {},
  };
}

describe("draftFromOverview", () => {
  it("the live default (local llama.cpp, enabled): Local mode, a blank Anthropic cloud draft with its suggestions", () => {
    const d = draftFromOverview(overview());
    expect(d.mode).toBe("local");
    expect(d.lastOn).toBe("local");
    expect(d.local).toMatchObject({ provider: "llamacpp", timeout_s: "90", max_tokens: "350" });
    expect(d.cloud).toMatchObject({ provider: "anthropic", engineer: "claude-opus-5-5", radio: "claude-haiku-5-5" });
    expect(d).toMatchObject({ useFallback: false, ack: false, redact: true, budget: "", prices: {} });
  });

  it("disabled config: Off, remembering which side was primary", () => {
    const o = overview({ enabled: false, primary: spec({ provider: "anthropic", models: { engineer: "claude-sonnet-5-5", radio: null } }) });
    const d = draftFromOverview(o);
    expect(d.mode).toBe("off");
    expect(d.lastOn).toBe("cloud");
    expect(d.cloud.engineer).toBe("claude-sonnet-5-5");
  });

  it("splits primary and fallback by where they run; a local preset pointed at the internet is the cloud side", () => {
    const o = overview({
      primary: spec({ provider: "llamacpp", base_url: "https://llm.example.com/v1" }),
      fallback: spec({ provider: "llamacpp" }),
      budget: { daily_usd: 2.5 },
      prices: { "gpt-x": { input_per_mtok: 1, output_per_mtok: 4 } },
    });
    const d = draftFromOverview(o);
    expect(d.mode).toBe("cloud");
    expect(d.cloud.base_url).toBe("https://llm.example.com/v1");
    expect(d.local.base_url).toBe("");
    expect(d.useFallback).toBe(true);
    expect(d.budget).toBe("2.5");
    expect(d.prices).toEqual({ "gpt-x": { input: "1", output: "4" } });
  });

  it("an unchanged draft builds the saved config again (not dirty after load)", () => {
    const o = overview();
    const d = draftFromOverview(o);
    expect(configKey(o, d)).toBe(configKey(o, draftFromOverview(o)));
    const c = buildConfig(o, d);
    expect(c).toEqual({
      enabled: true,
      primary: { provider: "llamacpp", base_url: null, model: null, models: { engineer: null, radio: null }, timeout_s: 90, max_tokens: 350, effort: "low" },
      fallback: null,
      privacy: { cloud_enabled: false, acknowledged_notice_version: null, redact_driver_names: true },
      budget: { daily_usd: null },
      prices: {},
    });
  });
});

describe("spec drafts", () => {
  it("round-trips a spec", () => {
    const s = spec({ provider: "anthropic", base_url: null, models: { engineer: "claude-opus-5-5", radio: "claude-haiku-5-5" }, max_tokens: null, effort: "medium" });
    expect(toSpecIn(fromSpec(s))).toEqual({ ...s, timeout_s: 90 });
  });

  it("empty strings become null; a bad timeout falls back to 60 s; max tokens are whole", () => {
    const d = { ...blankSpec("llamacpp"), base_url: "  ", engineer: " qwen ", timeout_s: "abc", max_tokens: "350.6" };
    expect(toSpecIn(d)).toMatchObject({ base_url: null, models: { engineer: "qwen", radio: null }, timeout_s: 60, max_tokens: 351 });
    expect(toSpecIn({ ...d, timeout_s: "" }).timeout_s).toBe(60);
    expect(toSpecIn({ ...d, timeout_s: "-5" }).timeout_s).toBe(60);
    expect(toSpecIn({ ...d, max_tokens: "x" }).max_tokens).toBeNull();
  });

  it("changing provider resets the URL; Anthropic fills only empty models", () => {
    const d = { ...blankSpec("openai"), base_url: "https://x", engineer: "gpt-x" };
    expect(changeProvider(PRESETS, d, "anthropic")).toMatchObject({ provider: "anthropic", base_url: "", engineer: "gpt-x", radio: "claude-haiku-5-5" });
    expect(changeProvider(PRESETS, d, "custom")).toMatchObject({ provider: "custom", base_url: "", engineer: "gpt-x", radio: "" });
  });
});

describe("sides and privacy", () => {
  const base = draftFromOverview(overview());

  it("Off keeps the last side as primary, but never an unacknowledged cloud one", () => {
    const offCloud: AiDraft = { ...setMode(setMode(base, "cloud"), "off") };
    expect(offCloud.lastOn).toBe("cloud");
    expect(primarySide(offCloud)).toBe("local");
    expect(primarySide({ ...offCloud, ack: true })).toBe("cloud");
    expect(otherSide({ ...offCloud, ack: true })).toBe("local");
  });

  it("which editors show: the mode's side, plus the other one while it is the fallback", () => {
    expect([showLocal(base), showCloud(base)]).toEqual([true, false]);
    expect([showLocal({ ...base, useFallback: true }), showCloud({ ...base, useFallback: true })]).toEqual([true, true]);
    const cloud = setMode(base, "cloud");
    expect([showLocal(cloud), showCloud(cloud)]).toEqual([false, true]);
    const off = setMode(base, "off");
    expect([showLocal(off), showCloud(off)]).toEqual([false, false]);
  });

  it("cloud in use: a cloud primary, a cloud fallback, or a local preset pointed at the internet", () => {
    expect(cloudInUse(PRESETS, base)).toBe(false);
    expect(cloudInUse(PRESETS, setMode(base, "cloud"))).toBe(true);
    expect(cloudInUse(PRESETS, { ...base, useFallback: true })).toBe(true);
    expect(cloudInUse(PRESETS, { ...base, local: { ...base.local, base_url: "https://llm.example.com/v1" } })).toBe(true);
    expect(cloudInUse(PRESETS, { ...base, local: { ...base.local, base_url: "http://192.168.1.20:8081/v1" } })).toBe(false);
  });

  it("the config carries the acknowledged notice version (the server refuses a stale one) and cloud_enabled", () => {
    const o = overview({}, 3);
    const d = { ...setMode(base, "cloud"), ack: true, redact: false };
    const c = buildConfig(o, d);
    expect(c.enabled).toBe(true);
    expect(c.primary.provider).toBe("anthropic");
    expect(c.privacy).toEqual({ cloud_enabled: true, acknowledged_notice_version: 3, redact_driver_names: false });
    expect(buildConfig(o, { ...d, ack: false }).privacy.acknowledged_notice_version).toBeNull();
  });

  it("Off saves enabled: false with the last side as primary", () => {
    const c = buildConfig(overview(), setMode(base, "off"));
    expect(c.enabled).toBe(false);
    expect(c.primary.provider).toBe("llamacpp");
  });

  it("fallback is the other side", () => {
    const c = buildConfig(overview(), { ...base, useFallback: true, ack: true });
    expect(c.primary.provider).toBe("llamacpp");
    expect(c.fallback?.provider).toBe("anthropic");
  });
});

describe("budget and prices", () => {
  const cloud: AiDraft = {
    ...setMode(draftFromOverview(overview()), "cloud"),
    ack: true,
    cloud: { ...blankSpec("openai"), engineer: "gpt-big", radio: "gpt-small" },
  };

  it("prices are asked for non-Anthropic cloud models only while a budget is set", () => {
    expect(pricedModels(PRESETS, cloud)).toEqual([]);
    expect(pricedModels(PRESETS, { ...cloud, budget: "5" })).toEqual(["gpt-big", "gpt-small"]);
    expect(pricedModels(PRESETS, { ...cloud, budget: "5", cloud: { ...cloud.cloud, radio: "", model: "gpt-big" } })).toEqual(["gpt-big"]);
    const anthropic = { ...cloud, budget: "5", cloud: blankSpec("anthropic") };
    expect(pricedModels(PRESETS, anthropic)).toEqual([]);
  });

  it("only complete prices for models in use are sent; the budget is a number or null", () => {
    const d = {
      ...cloud,
      budget: " 2.5 ",
      prices: {
        "gpt-big": { input: "10", output: "30" },
        "gpt-small": { input: "1", output: "" },
        "old-model": { input: "1", output: "2" },
      },
    };
    const c = buildConfig(overview(), d);
    expect(c.prices).toEqual({ "gpt-big": { input_per_mtok: 10, output_per_mtok: 30 } });
    expect(c.budget.daily_usd).toBe(2.5);
    expect(buildConfig(overview(), { ...d, budget: "" }).budget.daily_usd).toBeNull();
    expect(buildConfig(overview(), { ...d, budget: "lots" }).budget.daily_usd).toBeNull();
  });
});

describe("save bar", () => {
  it("priority: error, then the privacy tick, then saved, then unsaved", () => {
    expect(saveState({ error: "boom", needsAck: true, savedNote: "Saved", dirty: true })).toEqual({ kind: "error", text: "boom" });
    expect(saveState({ error: null, needsAck: true, savedNote: null, dirty: true })).toEqual({ kind: "needs-ack" });
    expect(saveState({ error: null, needsAck: false, savedNote: "Saved", dirty: false })).toEqual({ kind: "saved", text: "Saved" });
    expect(saveState({ error: null, needsAck: false, savedNote: "Saved", dirty: true })).toEqual({ kind: "dirty" });
    expect(saveState({ error: null, needsAck: false, savedNote: null, dirty: false })).toEqual({ kind: "clean" });
  });
});

describe("models", () => {
  it("suggestions first, then listed ids, without duplicates", () => {
    const listed = {
      provider: "anthropic",
      models: [{ id: "claude-haiku-5-5" }, { id: "claude-opus-4-8" }],
      suggested: { engineer: null, radio: null },
      suggested_models: [],
      error: null,
    };
    expect(modelOptions(PRESETS, blankSpec("anthropic"), listed)).toEqual([
      "claude-opus-5-5",
      "claude-sonnet-5-5",
      "claude-haiku-5-5",
      "claude-opus-4-8",
    ]);
    expect(modelOptions(PRESETS, blankSpec("llamacpp"), null)).toEqual([]);
  });

  it("quick picks only for Anthropic, and only with models the preset knows", () => {
    expect(quickPicksFor(PRESETS[1]).map((q) => q.engineer)).toEqual(["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]);
    expect(quickPicksFor(PRESETS[0])).toEqual([]);
    expect(quickPicksFor({ ...PRESETS[1]!, suggested_models: ["claude-haiku-5-5"] }).map((q) => q.label)).toEqual([
      "Haiku 5.5 for both (cheapest)",
    ]);
  });

  it("labels", () => {
    expect(modelLabel("claude-opus-5-5")).toBe("Opus 5.5");
    expect(modelLabel("claude-haiku-5")).toBe("Haiku 5");
    expect(modelLabel("gpt-4o")).toBe("gpt-4o");
    expect(shortModel("/Users/x/models/Qwen3.8-27B-UD-Q4_K_XL.gguf")).toBe("Qwen3.8-27B-UD-Q4_K_XL.gguf");
    expect(shortModel(null)).toBe("Server default");
    expect(secs(9)).toBe("9 ms");
    expect(secs(1440)).toBe("1.4 s");
    expect(secs(null)).toBe("-");
  });
});
