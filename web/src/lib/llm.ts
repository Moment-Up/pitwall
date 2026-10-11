// Typed client for the AI provider settings API (/api/llm/*, see src/pitwall/api/routes_llm.py).
// API keys only ever travel browser -> server (PUT /api/llm/keys/{name}); the server returns masked values only.
// Every POST sends Content-Type: application/json - the server refuses POSTs without it (cross-site protection).

export type Purpose = "engineer" | "radio";
export type Role = "primary" | "fallback";
export type Effort = "low" | "medium" | "high" | "xhigh" | "max";
export type Location = "local" | "cloud";

export interface Preset {
  id: string;
  label: string;
  kind: "anthropic" | "openai";
  location: "local" | "cloud" | "auto";
  base_url: string;
  key_name: string | null; // fixed cloud vendors: their key; others: the key used while the URL is local
  cloud_key_name: string | null; // non-vendor presets once the URL points at the internet
  key_required: boolean;
  docs_url: string;
  notes: string;
  suggested: { engineer: string | null; radio: string | null };
  suggested_models: string[];
}

export interface ProviderSpec {
  provider: string;
  base_url: string | null;
  model: string | null;
  models: { engineer: string | null; radio: string | null };
  timeout_s: number;
  max_tokens: number | null;
  effort: Effort;
}

export interface LlmConfig {
  version: number;
  enabled: boolean;
  primary: ProviderSpec;
  fallback: ProviderSpec | null;
  privacy: {
    cloud_enabled: boolean;
    notice_version: number;
    acknowledged_at: number | null;
    redact_driver_names: boolean;
    notice_acknowledged: boolean;
  };
  budget: { daily_usd: number | null };
  prices: Record<string, { input_per_mtok: number; output_per_mtok: number }>;
}

export interface KeyState {
  set: boolean;
  masked: string | null;
  source: "env" | "file" | "settings" | null; // settings = pitwall's .env file
  env_var: string;
}

export interface SlotStatus {
  role: Role;
  provider: string;
  label: string;
  kind: string;
  location: Location;
  base_url: string;
  models: Record<Purpose, string | null>;
  key_name: string | null;
  key_set: boolean;
  blocked: string | null;
  breaker_open: boolean;
}

export interface Health {
  ok: boolean;
  base_url: string;
  model: string | null;
  detail: string;
  latency_ms: number | null;
  context_tokens: number | null;
  breaker_open: boolean;
}

export interface Overview {
  presets: Preset[];
  config: LlmConfig;
  status: {
    version: number;
    source: "settings" | "defaults";
    error: string | null;
    enabled: boolean;
    mode: "off" | Location;
    providers: SlotStatus[];
  };
  keys: Record<string, KeyState>;
  privacy_notice: { version: number; points: string[] };
  purposes: Purpose[];
  efforts: Effort[];
  prices: Record<string, { input_per_mtok: number; output_per_mtok: number }>;
  health?: { primary: Health | null; fallback: Health | null };
}

export interface SpecIn {
  provider: string;
  base_url: string | null;
  model: string | null;
  models: { engineer: string | null; radio: string | null };
  timeout_s: number;
  max_tokens: number | null;
  effort: Effort;
}

export interface ConfigIn {
  enabled: boolean;
  primary: SpecIn;
  fallback: SpecIn | null;
  // The notice version this page displayed and the user ticked (null = not acknowledged). The server answers 409
  // if the notice changed since, so an old tab can never acknowledge text it did not show.
  privacy: { cloud_enabled: boolean; acknowledged_notice_version: number | null; redact_driver_names: boolean };
  budget: { daily_usd: number | null };
  prices: Record<string, { input_per_mtok: number; output_per_mtok: number }>;
}

export interface TestResult {
  ok: boolean;
  role: Role;
  purpose: Purpose;
  provider: string;
  location: Location;
  model: string | null;
  health: Health;
  question: string;
  answer: string;
  grounded: boolean | null;
  fallback: boolean;
  llm_attempts: number;
  issues: string[];
  answer_latency_ms: number;
  total_ms: number;
  note: string;
}

export interface ModelList {
  provider: string;
  models: { id: string; display_name?: string | null }[];
  suggested: { engineer: string | null; radio: string | null };
  suggested_models: string[];
  error: string | null;
}

export interface UsageRow {
  provider: string;
  model: string | null;
  location: Location;
  calls: number;
  errors: number;
  blocked: number;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  unpriced_calls: number;
  by_purpose: Record<string, number>;
}

export interface UsageTotals {
  date: string;
  calls: number;
  errors: number;
  blocked: number;
  prompt_tokens: number;
  completion_tokens: number;
  cloud_cost_usd: number;
  unpriced_calls: number;
}

export interface Usage {
  today: UsageTotals & { by_model: UsageRow[] };
  days: UsageTotals[];
  last_block: { at: number; provider: string; model: string | null; reason: string } | null;
  budget: {
    daily_usd: number | null;
    spent_today_usd: number;
    remaining_usd: number | null;
    reached: boolean;
    unmetered_calls: number; // cloud calls today with unknown cost while a budget was set (pauses cloud calls)
  };
}

export interface LastRequest {
  at: number;
  role: Role;
  provider: string;
  provider_label: string;
  location: Location;
  base_url: string;
  model: string | null;
  purpose: Purpose;
  ok: boolean;
  driver_names_redacted: number;
  redaction_enabled: boolean;
  headers: string;
  request: unknown;
}

function errorText(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // pydantic validation errors: [{loc: [...], msg}]
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).filter((x) => x !== "body").join(".")}: ${d.msg ?? ""}`)
      .join("; ");
  }
  return fallback;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { credentials: "same-origin", ...init });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      detail = errorText((await r.json()).detail, detail);
    } catch {
      /* not json */
    }
    throw new ApiError(detail || `HTTP ${r.status}`, r.status);
  }
  return r.json() as Promise<T>;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const llmApi = {
  overview: (health = false) => call<Overview>(`/api/llm/providers${health ? "?health=true" : ""}`),
  saveConfig: (cfg: ConfigIn) => call<Overview>("/api/llm/config", json("PUT", cfg)),
  saveKey: (name: string, value: string) =>
    call<{ name: string; saved: boolean; masked: string; source: string | null; note: string | null }>(
      `/api/llm/keys/${encodeURIComponent(name)}`,
      json("PUT", { value }),
    ),
  deleteKey: (name: string) =>
    call<{ name: string; deleted: boolean; set: boolean; note: string | null }>(
      `/api/llm/keys/${encodeURIComponent(name)}`,
      { method: "DELETE" },
    ),
  test: (role: Role, purpose: Purpose) => call<TestResult>("/api/llm/test", json("POST", { role, purpose })),
  // POST: it makes an outbound request. A saved key is only sent to its own endpoint (the vendor's host, or the
  // server URL saved in the settings), so listing a not-yet-saved custom URL goes out without a key.
  models: (provider: string, baseUrl: string | null) =>
    call<ModelList>("/api/llm/models", json("POST", { provider, base_url: baseUrl })),
  usage: () => call<Usage>("/api/llm/usage"),
  lastRequest: () => call<{ last: LastRequest | null }>("/api/llm/last-request"),
};

// Client-side mirror of provider_registry.is_local_host, for instant hints while editing. The server decides.
export function isLocalHost(host: string): boolean {
  const h = host.replace(/^\[|\]$/g, "").toLowerCase().replace(/\.$/, "");
  if (!h) return false;
  if (h === "localhost" || /\.(localhost|local|ts\.net|home\.arpa)$/.test(h)) return true;
  if (!h.includes(".") && !h.includes(":")) return true;
  if (h === "::1") return true;
  const m = h.match(/^(\d+)\.(\d+)\.(\d+)\.(\d+)$/);
  if (!m) return false;
  const [a, b] = [Number(m[1]), Number(m[2])];
  return a === 127 || a === 10 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) ||
    (a === 169 && b === 254) || (a === 100 && b >= 64 && b <= 127);
}

export function locationOf(preset: Preset | undefined, baseUrl: string): Location {
  if (!preset) return "local";
  if (preset.location === "cloud") return "cloud";
  const url = baseUrl || preset.base_url;
  try {
    return isLocalHost(new URL(url).hostname) ? "local" : "cloud";
  } catch {
    return preset.location === "auto" ? "cloud" : "local";
  }
}

// Mirror of provider_registry.key_name_for: which saved key an endpoint uses (for the key field shown).
export function keyNameFor(preset: Preset | undefined, baseUrl: string): string | null {
  if (!preset) return null;
  if (preset.location === "cloud") return preset.key_name;
  return locationOf(preset, baseUrl) === "cloud" ? preset.cloud_key_name : preset.key_name;
}

export function fmtUsd(v: number | null | undefined): string {
  if (v == null) return "-";
  if (v === 0) return "$0";
  return v < 0.01 ? `$${v.toFixed(4)}` : `$${v.toFixed(2)}`;
}

export function fmtTokens(n: number): string {
  return n >= 10_000 ? `${(n / 1000).toFixed(0)}k` : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}
