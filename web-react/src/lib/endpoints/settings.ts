// Typed endpoints for Settings (spec 12.4, lane Y): the AI engineer (/api/llm/*), voice status, server and local-LLM
// health, the capability matrix, captures, replay and the synthetic demo.
//
// The /api/llm/* part is a port of web/src/lib/llm.ts (same types, same calls, same client-side mirrors of the
// server's host and key rules). API keys only ever travel browser -> server (PUT /api/llm/keys/{name}); the server
// answers with masked values only, and nothing here ever stores or logs a key. Every POST/PUT sends
// Content-Type: application/json (the server refuses JSON-less POSTs: cross-site protection).
//
// Cache keys (src/lib/cache.ts) used by the Settings pages: SETTINGS_KEYS below. A mutation invalidates its own
// prefix (e.g. saving the AI config sets "llm:overview" from the response and invalidates "llm:usage").

import { authFetch } from "../auth";
import type { Snapshot } from "../api";

// ---------------------------------------------------------------------------------------------- errors

/** An HTTP error from a Settings endpoint. `detail` is the server's message, ready to show (no "409:" prefix). */
export class EndpointError extends Error {
  readonly status: number;
  readonly detail: string;
  constructor(status: number, detail: string) {
    super(detail || `HTTP ${status}`);
    this.name = "EndpointError";
    this.status = status;
    this.detail = detail;
  }
}

/** FastAPI's `detail`: a string, or pydantic's validation list [{loc, msg}]. */
export function errorText(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((d: unknown) => {
        if (!d || typeof d !== "object") return "";
        const { loc, msg } = d as { loc?: unknown; msg?: unknown };
        const where = Array.isArray(loc) ? loc.filter((x) => x !== "body").join(".") : "";
        const text = typeof msg === "string" ? msg : "";
        return where ? `${where}: ${text}` : text;
      })
      .filter(Boolean);
    if (parts.length) return parts.join("; ");
  }
  return fallback;
}

/** The message to show for anything a call threw. */
export function messageOf(e: unknown): string {
  if (e instanceof EndpointError) return e.detail || e.message;
  return e instanceof Error ? e.message : String(e);
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await authFetch(path, init);
  if (!r.ok) {
    let detail = r.statusText;
    try {
      detail = errorText(((await r.json()) as { detail?: unknown }).detail, detail);
    } catch {
      /* not json */
    }
    throw new EndpointError(r.status, detail || `HTTP ${r.status}`);
  }
  return r.json() as Promise<T>;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

// ---------------------------------------------------------------------------------------------- AI engineer types

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
  /** Fixed cloud vendors: their key; others: the key used while the URL is local. */
  key_name: string | null;
  /** Non-vendor presets once the URL points at the internet. */
  cloud_key_name: string | null;
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

export interface Price {
  input_per_mtok: number;
  output_per_mtok: number;
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
  prices: Record<string, Price>;
}

export interface KeyState {
  set: boolean;
  /** The server's masked form (e.g. "sk-ant-…1a2b"); never the key. */
  masked: string | null;
  /** "settings" = pitwall's .env file; "file" = saved from this page. */
  source: "env" | "file" | "settings" | null;
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

/** A provider's health (also GET /api/llm/health, the local LLM the engineer uses by default). */
export interface LlmHealth {
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
  prices: Record<string, Price>;
  health?: { primary: LlmHealth | null; fallback: LlmHealth | null };
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
  /** The notice version this page displayed and the user ticked (null = not acknowledged). The server answers 409
   * if the notice changed since, so an old tab can never acknowledge text it did not show. */
  privacy: { cloud_enabled: boolean; acknowledged_notice_version: number | null; redact_driver_names: boolean };
  budget: { daily_usd: number | null };
  prices: Record<string, Price>;
}

export interface TestResult {
  ok: boolean;
  role: Role;
  purpose: Purpose;
  provider: string;
  location: Location;
  model: string | null;
  health: LlmHealth;
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

export interface UsageTotals {
  date: string;
  calls: number;
  errors: number;
  blocked: number;
  prompt_tokens: number;
  completion_tokens: number;
  cloud_cost_usd: number;
  unpriced_calls: number;
  unmetered_calls?: number;
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
  unmetered_calls?: number;
  by_purpose: Record<string, number>;
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
    /** Cloud calls today with unknown cost while a budget was set (they pause cloud calls). */
    unmetered_calls: number;
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
  /** A description of the headers sent (the key itself is never included). */
  headers: string;
  request: unknown;
}

export interface KeySaved {
  name: string;
  saved: boolean;
  masked: string;
  source: string | null;
  note: string | null;
}

export interface KeyDeleted {
  name: string;
  deleted: boolean;
  set: boolean;
  note: string | null;
}

// ---------------------------------------------------------------------------------------------- system types

/** A replay running (or finished) on the server (runtime.replay_status). */
export interface ReplayStatus {
  path: string;
  sent: number;
  done: boolean;
  speed: number | null;
  synthetic: boolean;
}

/** GET /api/health. */
export interface ServerHealth {
  version: string;
  time: number;
  connection: Snapshot["connection"];
  /** The UDP listener's port; null when the listener is off. */
  udp_port: number | null;
  replay: ReplayStatus | null;
  db_writer_errors: number;
  analysis_errors: number;
  laps_processed: number;
}

/** Status vocabulary of src/pitwall/capabilities.py (SupportLevel), strongest evidence first. */
export type SupportLevel =
  | "live_validated"
  | "recorded_validated"
  | "spec_implemented"
  | "community_documented"
  | "partial"
  | "unverified"
  | "unsupported";

export interface FieldSupport {
  level: SupportLevel | string;
  source: string;
}

/** One row of GET /api/capabilities. */
export interface Capability {
  game: string;
  platform: string;
  transport: string;
  status: SupportLevel | string;
  implemented: boolean;
  notes: string;
  fields: Record<string, FieldSupport> | null;
}

/** One row of GET /api/captures (newest first). */
export interface Capture {
  path: string;
  name: string;
  size_bytes: number;
  synthetic: boolean;
  description: string;
  created_unix: number;
}

export interface ReplayStarted {
  replaying: string;
  speed: number | null;
}

export interface SimulateResult {
  path: string;
  synthetic: true;
  lap_times_ms: number[];
  /** What to look for in its replay (sim/scenarios.py STORIES; also the capture's meta.extra.story). null or absent
   * (an older server, a scenario without one) = nothing promised. */
  story?: DemoStory | null;
}

/** One thing to look for in a SYNTHETIC demo's replay (sim/scenarios.py StoryBeat): on which laps, when ("after the
 * line", "before T5", "on the screen", "with the lap time"), the exact radio line or the screen's note, and what it
 * shows. Corner names are the ones the demo learns and shows. */
export interface DemoStoryBeat {
  laps: number[];
  when: string;
  radio: string | null;
  screen: string | null;
  shows: string;
}

export interface DemoStory {
  intro: string;
  beats: DemoStoryBeat[];
}

/** GET /api/voice/status: `{enabled: false}` when the voice hub is off, else the hub's state. Only the fields the
 * Settings pages read are typed; the rest stays open. */
export interface VoiceStatus {
  enabled: boolean;
  stt?: string;
  tts?: string;
  tts_active?: string;
  tts_ready?: boolean;
  tts_neural?: boolean;
  tts_status?: string | null;
  tts_voice?: string | null;
  tts_voices?: string[];
  voice_enabled?: boolean;
  intensity?: string;
  cue_mode?: string;
  telemetry?: string;
  clients?: unknown[];
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------------------------- calls

/** Request-cache keys for the Settings pages (spec 12.3 naming: "<what>" or "<what>:<id>"). */
export const SETTINGS_KEYS = {
  llmOverview: "llm:overview",
  llmUsage: "llm:usage",
  llmLast: "llm:last-request",
  llmHealth: "llm-health",
  health: "health",
  capabilities: "capabilities",
  captures: "captures",
  voice: "voice:status",
} as const;

export const llmApi = {
  /** Providers, config, keys (masked), privacy notice; `health` adds a live check of each configured provider. */
  overview: (health = false) => call<Overview>(`/api/llm/providers${health ? "?health=true" : ""}`),
  saveConfig: (cfg: ConfigIn) => call<Overview>("/api/llm/config", json("PUT", cfg)),
  saveKey: (name: string, value: string) => call<KeySaved>(`/api/llm/keys/${encodeURIComponent(name)}`, json("PUT", { value })),
  deleteKey: (name: string) => call<KeyDeleted>(`/api/llm/keys/${encodeURIComponent(name)}`, { method: "DELETE" }),
  /** One real question through the engineer with that provider (billed like any other call for cloud). */
  test: (role: Role, purpose: Purpose) => call<TestResult>("/api/llm/test", json("POST", { role, purpose })),
  /** POST: it makes an outbound request. A saved key is only sent to its own endpoint. */
  models: (provider: string, baseUrl: string | null) =>
    call<ModelList>("/api/llm/models", json("POST", { provider, base_url: baseUrl })),
  usage: () => call<Usage>("/api/llm/usage"),
  lastRequest: () => call<{ last: LastRequest | null }>("/api/llm/last-request"),
};

export const systemApi = {
  health: () => call<ServerHealth>("/api/health"),
  /** The local LLM's health (the default provider). */
  llmHealth: () => call<LlmHealth>("/api/llm/health"),
  capabilities: () => call<Capability[]>("/api/capabilities"),
  captures: () => call<Capture[]>("/api/captures"),
  /** Replay a capture into the live pipeline. `speed` null = as fast as possible. */
  replay: (path: string, speed: number | null, loop = false) =>
    call<ReplayStarted>("/api/replay", json("POST", { path, speed, loop })),
  stopReplay: () => call<{ stopped: boolean }>("/api/replay", { method: "DELETE" }),
  /** Write a SYNTHETIC capture with known injected mistakes (never real game output). */
  simulate: (scenario = "coaching-demo", packetFormat = 2025) =>
    call<SimulateResult>("/api/simulate", json("POST", { scenario, packet_format: packetFormat })),
  voiceStatus: () => call<VoiceStatus>("/api/voice/status"),
};

/** The synthetic demo's capture name for a packet format (api/app.py: synthetic-<scenario>-<format>.pwcap). */
export const demoCaptureName = (format = 2025, scenario = "coaching-demo"): string => `synthetic-${scenario}-${format}.pwcap`;

/**
 * "Try a demo replay" (spec 4.9, the Drive no-telemetry card; Settings › System): replay the SYNTHETIC coaching demo
 * at real time. The capture is written anew every time (POST /api/simulate overwrites demoCaptureName), so the replay
 * is always this server's demo and never a capture an older version left in the folder. Resolves with the capture's
 * path and what to look for (its story); the caller says that it is synthetic (the live snapshot is flagged too).
 */
export async function startDemoReplay(format = 2025): Promise<{ path: string; story: DemoStory | null }> {
  const r = await systemApi.simulate("coaching-demo", format);
  await systemApi.replay(r.path, 1);
  return { path: r.path, story: r.story ?? null };
}

// ---------------------------------------------------------------------------------------------- client-side mirrors

/** Mirror of provider_registry.is_local_host, for instant hints while editing. The server decides. */
export function isLocalHost(host: string): boolean {
  const h = host.replace(/^\[|\]$/g, "").toLowerCase().replace(/\.$/, "");
  if (!h) return false;
  if (h === "localhost" || /\.(localhost|local|ts\.net|home\.arpa)$/.test(h)) return true;
  if (!h.includes(".") && !h.includes(":")) return true;
  if (h === "::1") return true;
  const m = /^(\d+)\.(\d+)\.(\d+)\.(\d+)$/.exec(h);
  if (!m) return false;
  const a = Number(m[1]);
  const b = Number(m[2]);
  return (
    a === 127 ||
    a === 10 ||
    (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && b === 168) ||
    (a === 169 && b === 254) ||
    (a === 100 && b >= 64 && b <= 127)
  );
}

/** Where a provider runs: a cloud vendor, or by the host of its URL (the preset's default when empty). */
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

/** Mirror of provider_registry.key_name_for: which saved key an endpoint uses. */
export function keyNameFor(preset: Preset | undefined, baseUrl: string): string | null {
  if (!preset) return null;
  if (preset.location === "cloud") return preset.key_name;
  return locationOf(preset, baseUrl) === "cloud" ? preset.cloud_key_name : preset.key_name;
}

/** US dollars: "$0", "$0.0042", "$1.25"; unknown "-". */
export function fmtUsd(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "-";
  if (v === 0) return "$0";
  return v < 0.01 ? `$${v.toFixed(4)}` : `$${v.toFixed(2)}`;
}

/** Token counts: "950", "1.8k", "14k"; unknown "-". */
export function fmtTokens(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "-";
  return n >= 10_000 ? `${(n / 1000).toFixed(0)}k` : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}
