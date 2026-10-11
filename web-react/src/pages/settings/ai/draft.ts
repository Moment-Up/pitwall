// Settings › AI engineer: the editable draft and the rules that turn it into the server's config (pure, unit-tested).
// Port of the <script> part of web/src/views/SettingsView.svelte. The server (src/pitwall/api/routes_llm.py)
// validates everything; this module only keeps a draft so switching between Local and Cloud never loses what was
// typed for the other side, and mirrors the server's privacy rule so the Save button can explain a refusal before
// it happens.

import {
  locationOf,
  type ConfigIn,
  type Effort,
  type Location,
  type ModelList,
  type Overview,
  type Preset,
  type ProviderSpec,
  type SpecIn,
} from "../../../lib/endpoints/settings";

export type Mode = "off" | "local" | "cloud";
export type Side = "local" | "cloud";

/** One provider as typed (strings, so a half-typed number never jumps). */
export interface SpecDraft {
  provider: string;
  base_url: string;
  model: string;
  engineer: string;
  radio: string;
  timeout_s: string;
  max_tokens: string;
  effort: Effort;
}

export interface PriceDraft {
  input: string;
  output: string;
}

export interface AiDraft {
  mode: Mode;
  /** Which side is primary while the engineer is Off (the last side chosen). */
  lastOn: Side;
  local: SpecDraft;
  cloud: SpecDraft;
  useFallback: boolean;
  /** The privacy notice is ticked on this page (for the version shown). */
  ack: boolean;
  redact: boolean;
  /** Daily cloud budget in USD as typed; "" = no limit. */
  budget: string;
  prices: Record<string, PriceDraft>;
}

export const DEFAULT_LOCAL_PROVIDER = "llamacpp";
export const DEFAULT_CLOUD_PROVIDER = "anthropic";
export const DEFAULT_TIMEOUT_S = 60;

export function blankSpec(provider: string): SpecDraft {
  return { provider, base_url: "", model: "", engineer: "", radio: "", timeout_s: String(DEFAULT_TIMEOUT_S), max_tokens: "", effort: "low" };
}

export function fromSpec(s: ProviderSpec): SpecDraft {
  return {
    provider: s.provider,
    base_url: s.base_url ?? "",
    model: s.model ?? "",
    engineer: s.models.engineer ?? "",
    radio: s.models.radio ?? "",
    timeout_s: String(s.timeout_s),
    max_tokens: s.max_tokens == null ? "" : String(s.max_tokens),
    effort: s.effort,
  };
}

const opt = (s: string): string | null => s.trim() || null;

export function toSpecIn(d: SpecDraft): SpecIn {
  const timeout = Number(d.timeout_s);
  const maxTok = d.max_tokens.trim() ? Number(d.max_tokens) : null;
  return {
    provider: d.provider,
    base_url: opt(d.base_url),
    model: opt(d.model),
    models: { engineer: opt(d.engineer), radio: opt(d.radio) },
    timeout_s: d.timeout_s.trim() !== "" && Number.isFinite(timeout) && timeout > 0 ? timeout : DEFAULT_TIMEOUT_S,
    max_tokens: maxTok != null && Number.isFinite(maxTok) ? Math.round(maxTok) : null,
    effort: d.effort,
  };
}

export function presetOf(presets: readonly Preset[], id: string): Preset | undefined {
  return presets.find((p) => p.id === id);
}

/** Where a draft runs (cloud vendor, or by its URL's host). */
export function whereOf(presets: readonly Preset[], d: SpecDraft): Location {
  return locationOf(presetOf(presets, d.provider), d.base_url);
}

/** Fill empty engineer / radio models with the preset's suggestion (Anthropic suggests Opus + Haiku). */
export function suggestModels(d: SpecDraft, p: Preset | undefined): SpecDraft {
  return {
    ...d,
    engineer: d.engineer || p?.suggested.engineer || "",
    radio: d.radio || p?.suggested.radio || "",
  };
}

/** The draft for a freshly loaded (or saved) overview. */
export function draftFromOverview(o: Overview): AiDraft {
  const c = o.config;
  const specs = [c.primary, ...(c.fallback ? [c.fallback] : [])];
  const where = (s: ProviderSpec) => locationOf(presetOf(o.presets, s.provider), s.base_url ?? "");
  const loc = specs.find((s) => where(s) === "local");
  const cl = specs.find((s) => where(s) === "cloud");
  const lastOn = where(c.primary);
  return {
    mode: c.enabled ? lastOn : "off",
    lastOn,
    local: loc ? fromSpec(loc) : blankSpec(DEFAULT_LOCAL_PROVIDER),
    cloud: cl
      ? fromSpec(cl)
      : suggestModels(blankSpec(DEFAULT_CLOUD_PROVIDER), presetOf(o.presets, DEFAULT_CLOUD_PROVIDER)),
    useFallback: c.fallback != null,
    ack: c.privacy.notice_acknowledged,
    redact: c.privacy.redact_driver_names,
    budget: c.budget.daily_usd == null ? "" : String(c.budget.daily_usd),
    prices: Object.fromEntries(
      Object.entries(c.prices).map(([m, p]) => [m, { input: String(p.input_per_mtok), output: String(p.output_per_mtok) }]),
    ),
  };
}

/** The primary side. While Off it is the last side chosen, but never an unacknowledged cloud one (the server
 * refuses that). */
export function primarySide(d: AiDraft): Side {
  if (d.mode !== "off") return d.mode;
  return d.lastOn === "cloud" && d.ack ? "cloud" : "local";
}

export function otherSide(d: AiDraft): Side {
  return primarySide(d) === "local" ? "cloud" : "local";
}

const specOf = (d: AiDraft, side: Side): SpecDraft => (side === "local" ? d.local : d.cloud);

/** Anything in this setup would send data off this network (a cloud primary, or a cloud fallback in use). */
export function cloudInUse(presets: readonly Preset[], d: AiDraft): boolean {
  return (
    whereOf(presets, specOf(d, primarySide(d))) === "cloud" ||
    (d.useFallback && whereOf(presets, specOf(d, otherSide(d))) === "cloud")
  );
}

/** Which provider editors are on screen. */
export function showLocal(d: AiDraft): boolean {
  return d.mode === "local" || (d.mode === "cloud" && d.useFallback);
}
export function showCloud(d: AiDraft): boolean {
  return d.mode === "cloud" || (d.mode === "local" && d.useFallback);
}

export function setMode(d: AiDraft, m: Mode): AiDraft {
  return { ...d, mode: m, lastOn: m === "off" ? d.lastOn : m };
}

/** Change a side's provider: the URL resets to the preset's default; Anthropic fills in its suggested models. */
export function changeProvider(presets: readonly Preset[], d: SpecDraft, id: string): SpecDraft {
  const p = presetOf(presets, id);
  const next: SpecDraft = { ...d, provider: id, base_url: "" };
  return p?.kind === "anthropic" ? suggestModels(next, p) : next;
}

/** Models whose prices are needed to enforce a budget: the cloud side's non-Anthropic models while a budget is
 * set (pitwall knows Anthropic's prices). */
export function pricedModels(presets: readonly Preset[], d: AiDraft): string[] {
  const c = d.cloud;
  if (presetOf(presets, c.provider)?.kind === "anthropic" || d.budget.trim() === "") return [];
  return [...new Set([c.engineer || c.model, c.radio || c.model].filter((m) => m !== ""))];
}

/** The body for PUT /api/llm/config. */
export function buildConfig(o: Pick<Overview, "presets" | "privacy_notice">, d: AiDraft): ConfigIn {
  const presets = o.presets;
  const primary = specOf(d, primarySide(d));
  const fallback = d.useFallback ? specOf(d, otherSide(d)) : null;
  const used = new Set(
    [primary, fallback]
      .filter(
        (s): s is SpecDraft =>
          s != null && whereOf(presets, s) === "cloud" && presetOf(presets, s.provider)?.kind !== "anthropic",
      )
      .flatMap((s) => [s.engineer || s.model, s.radio || s.model])
      .filter((m) => m !== ""),
  );
  const prices: ConfigIn["prices"] = {};
  for (const [m, p] of Object.entries(d.prices)) {
    if (!used.has(m) || p.input.trim() === "" || p.output.trim() === "") continue;
    const input = Number(p.input);
    const output = Number(p.output);
    if (!Number.isFinite(input) || !Number.isFinite(output)) continue;
    prices[m] = { input_per_mtok: input, output_per_mtok: output };
  }
  const budget = d.budget.trim() === "" ? null : Number(d.budget);
  return {
    enabled: d.mode !== "off",
    primary: toSpecIn(primary),
    fallback: fallback ? toSpecIn(fallback) : null,
    privacy: {
      cloud_enabled: cloudInUse(presets, d),
      acknowledged_notice_version: d.ack ? o.privacy_notice.version : null,
      redact_driver_names: d.redact,
    },
    budget: { daily_usd: budget != null && Number.isFinite(budget) ? budget : null },
    prices,
  };
}

/** A stable fingerprint of what Save would send (dirty = it differs from the saved one). */
export function configKey(o: Pick<Overview, "presets" | "privacy_notice">, d: AiDraft): string {
  return JSON.stringify(buildConfig(o, d));
}

/** What the save bar says, in priority order. */
export type SaveState =
  | { kind: "error"; text: string }
  | { kind: "needs-ack" }
  | { kind: "saved"; text: string }
  | { kind: "dirty" }
  | { kind: "clean" };

export function saveState(args: {
  error: string | null;
  needsAck: boolean;
  savedNote: string | null;
  dirty: boolean;
}): SaveState {
  if (args.error) return { kind: "error", text: args.error };
  if (args.needsAck) return { kind: "needs-ack" };
  if (args.savedNote && !args.dirty) return { kind: "saved", text: args.savedNote };
  if (args.dirty) return { kind: "dirty" };
  return { kind: "clean" };
}

// ---------------------------------------------------------------------------------------------- models

/** Key of a model list (per provider and URL). */
export const listKey = (d: Pick<SpecDraft, "provider" | "base_url">): string => `${d.provider}|${d.base_url}`;

/** Model ids to offer: the preset's suggestions, then what the server listed. */
export function modelOptions(presets: readonly Preset[], d: SpecDraft, listed: ModelList | null | undefined): string[] {
  const p = presetOf(presets, d.provider);
  return [...new Set([...(p?.suggested_models ?? []), ...(listed?.models.map((m) => m.id) ?? [])])];
}

/** "claude-opus-5-5" -> "Opus 5.5"; anything else unchanged. */
export function modelLabel(id: string): string {
  const m = /^claude-(opus|sonnet|haiku|fable)-(\d+)(?:-(\d+))?$/.exec(id);
  if (!m?.[1] || !m[2]) return id;
  const family = m[1];
  return `${family.charAt(0).toUpperCase()}${family.slice(1)} ${m[2]}${m[3] ? `.${m[3]}` : ""}`;
}

/** Local servers often report a file path as the model id: show the file name. null = the server's default. */
export function shortModel(m: string | null | undefined): string {
  if (!m) return "Server default";
  return m.split("/").pop() || m;
}

/** "9 ms", "1.4 s"; unknown "-". */
export function secs(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return "-";
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

/** Anthropic quick picks (engineer + radio). Only offered when the preset suggests every model in the pick. */
export const QUICK_PICKS: readonly { label: string; engineer: string; radio: string }[] = [
  { label: "Opus 5.5 engineer + Haiku 5.5 radio (recommended)", engineer: "claude-opus-5-5", radio: "claude-haiku-5-5" },
  { label: "Sonnet 5.5 + Haiku 5.5", engineer: "claude-sonnet-5-5", radio: "claude-haiku-5-5" },
  { label: "Haiku 5.5 for both (cheapest)", engineer: "claude-haiku-5-5", radio: "claude-haiku-5-5" },
];

export function quickPicksFor(p: Preset | undefined): typeof QUICK_PICKS {
  if (p?.kind !== "anthropic") return [];
  const known = new Set(p.suggested_models);
  return QUICK_PICKS.filter((q) => known.has(q.engineer) && known.has(q.radio));
}

/** Engine choices (spec 8: Off / Local / Cloud) with their one-line meaning. */
export const MODES: readonly { id: Mode; label: string; hint: string }[] = [
  { id: "off", label: "Off", hint: "Fact answers only" },
  { id: "local", label: "Local", hint: "Private, on this Mac" },
  { id: "cloud", label: "Cloud", hint: "No local model needed" },
];

/** Thinking effort choices for Anthropic models (the server accepts more; the page offers these three). */
export const EFFORTS: readonly { id: Effort; label: string }[] = [
  { id: "low", label: "Low: fastest, cheapest (recommended)" },
  { id: "medium", label: "Medium" },
  { id: "high", label: "High: slowest" },
];
