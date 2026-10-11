// Settings › System: pure wording for health, captures and the capability matrix (unit-tested). Port of the logic
// in web/src/views/StatusView.svelte. Capability statuses come from src/pitwall/capabilities.py and are shown with
// the server's own vocabulary: the page never upgrades a claim (CLAUDE.md "Capability claims").

import type { Capability, Capture, LlmHealth, ReplayStatus, ServerHealth, SupportLevel } from "../../../lib/endpoints/settings";
import { grouped } from "../../../lib/format";

export type ChipTone = "success" | "warning" | "danger" | "default";

export interface SupportView {
  /** The status in words (sentence case of the server's vocabulary). */
  label: string;
  tone: ChipTone;
  /** The evidence behind it, one short phrase. */
  evidence: string;
  /** Strength order (0 = strongest), for sorting. */
  rank: number;
}

/** SupportLevel (strongest first): live validated > recorded validated > spec implemented > community documented >
 * partial > unverified > unsupported. Only the two validated tiers are green: nothing else is claimed to work. */
export const SUPPORT: Readonly<Record<SupportLevel, SupportView>> = {
  live_validated: { label: "Live validated", tone: "success", evidence: "Tested with the real game", rank: 0 },
  recorded_validated: { label: "Recorded validated", tone: "success", evidence: "Real captures, replayed", rank: 1 },
  spec_implemented: { label: "Spec implemented", tone: "default", evidence: "Built from the official spec, not tested", rank: 2 },
  community_documented: {
    label: "Community documented",
    tone: "default",
    evidence: "Built from community docs, not tested",
    rank: 3,
  },
  partial: { label: "Partial", tone: "warning", evidence: "Partial support only", rank: 4 },
  unverified: { label: "Unverified", tone: "warning", evidence: "Not verified", rank: 5 },
  unsupported: { label: "Unsupported", tone: "danger", evidence: "Not supported", rank: 6 },
};

/** A status the page does not know (a newer server): shown as its own words, neutral, never green. */
export function supportOf(status: string): SupportView {
  const known = (SUPPORT as Record<string, SupportView | undefined>)[status];
  if (known) return known;
  const words = status.replace(/_/g, " ").trim();
  return { label: words ? words.charAt(0).toUpperCase() + words.slice(1) : "-", tone: "default", evidence: "-", rank: 99 };
}

export interface CapabilityRow extends Capability {
  id: string;
  support: SupportView;
  /** Fields the adapter reads, by evidence level ("speed_kph" ... grouped). */
  fieldCount: number;
}

/** Matrix rows in the server's order (games grouped as listed), with a stable id. */
export function capabilityRows(caps: readonly Capability[]): CapabilityRow[] {
  return caps.map((c, i) => ({
    ...c,
    id: `${i}:${c.game}|${c.platform}`,
    support: supportOf(c.status),
    fieldCount: c.fields ? Object.keys(c.fields).length : 0,
  }));
}

/** How many fields of an adapter sit at each evidence level, strongest first: [["Live validated", 3], ...]. */
export function fieldLevels(c: Capability): [string, number][] {
  if (!c.fields) return [];
  const counts = new Map<string, number>();
  for (const f of Object.values(c.fields)) counts.set(f.level, (counts.get(f.level) ?? 0) + 1);
  return [...counts.entries()]
    .sort((a, b) => supportOf(a[0]).rank - supportOf(b[0]).rank)
    .map(([level, n]) => [supportOf(level).label, n]);
}

// ---------------------------------------------------------------------------------------------- captures

/** "37.2 MB", "8 KB", "240 B"; unknown "-". */
export function sizeText(bytes: number | null | undefined): string {
  if (bytes == null || !Number.isFinite(bytes) || bytes < 0) return "-";
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** The file name of a server path. */
export function fileName(path: string): string {
  return path.split(/[\\/]/).pop() || path;
}

export interface CaptureView {
  path: string;
  name: string;
  synthetic: boolean;
  /** "live capture · 37.2 MB · 2 h ago" */
  detail: string;
}

export function captureView(c: Capture, now = Date.now() / 1000): CaptureView {
  const when = Number.isFinite(c.created_unix) && c.created_unix > 0 ? agoAt(c.created_unix, now) : "-";
  return {
    path: c.path,
    name: c.name,
    synthetic: c.synthetic,
    detail: [c.description || "capture", sizeText(c.size_bytes), when].join(" · "),
  };
}

function agoAt(unix: number, now: number): string {
  // format.ago's wording, with `now` passed in so tests are deterministic.
  const s = Math.max(0, now - unix);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(unix * 1000).toLocaleDateString();
}

/** Synthetic captures first (the demo is what a new user replays), then the rest newest first (server order). */
export function sortCaptures(list: readonly Capture[]): Capture[] {
  return [...list].sort((a, b) => Number(b.synthetic) - Number(a.synthetic));
}

// ---------------------------------------------------------------------------------------------- health

export function workerErrors(h: ServerHealth | null | undefined): number | null {
  if (!h) return null;
  return (h.analysis_errors ?? 0) + (h.db_writer_errors ?? 0);
}

/** "12 analysis · 0 database" */
export function workerErrorDetail(h: ServerHealth): string {
  return `${grouped(h.analysis_errors)} analysis · ${grouped(h.db_writer_errors)} database`;
}

/** Telemetry in words: "Live · 190 312 packets · 0 rejected". */
export function telemetryText(h: ServerHealth): string {
  const c = h.connection;
  const status = c.status === "live" ? "Live" : c.status === "stale" ? "Stale" : "No data";
  return `${status} · ${grouped(c.packets)} packets · ${grouped(c.rejected)} rejected`;
}

/** The UDP listener: "Port 20777" or "Off". */
export function udpText(h: ServerHealth): string {
  return h.udp_port ? `Port ${h.udp_port}` : "Off";
}

/** The replay in words, or null when none ran. */
export function replayText(r: ReplayStatus | null | undefined): string | null {
  if (!r) return null;
  const speed = r.speed == null ? "max speed" : `${r.speed}×`;
  return `${fileName(r.path)} · ${speed} · ${grouped(r.sent)} packets${r.done ? " · done" : ""}`;
}

export const replayRunning = (r: ReplayStatus | null | undefined): boolean => r != null && !r.done;

export interface LlmHealthView {
  tone: ChipTone;
  label: string;
  detail: string;
}

/** The local LLM chip: "Ready · 9 ms" / "Offline" (+ the server's reason). */
export function llmHealthView(h: LlmHealth | null | undefined, error: string | null = null): LlmHealthView {
  if (!h) return error ? { tone: "danger", label: "Unreachable", detail: error } : { tone: "default", label: "-", detail: "" };
  if (!h.ok) return { tone: "danger", label: "Offline", detail: h.detail };
  const ms = h.latency_ms;
  return { tone: "success", label: ms == null ? "Ready" : `Ready · ${Math.round(ms)} ms`, detail: h.detail };
}

/** "Qwen3.8-27B-UD-Q4_K_XL.gguf" from a path; "-" when unknown. */
export function modelName(m: string | null | undefined): string {
  if (!m) return "-";
  return m.split("/").pop() || m;
}

/** "32 768 tokens"; unknown "-". */
export function contextText(n: number | null | undefined): string {
  return n == null ? "-" : `${grouped(n)} tokens`;
}

/** The synthetic demo's result, always labelled SYNTHETIC. */
export function simulateNote(path: string): string {
  return `Wrote ${fileName(path)}. It is SYNTHETIC: generated data with known mistakes, not from a game.`;
}

export function replayNote(path: string, speed: number | null): string {
  return `Replaying ${fileName(path)} ${speed ? `at ${speed}×` : "at max speed"}.`;
}
