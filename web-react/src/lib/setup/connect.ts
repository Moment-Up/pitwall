// Connect: pure helpers for Setup › Connect (spec 7.1), ported from the Svelte reference
// web/src/views/ConnectView.svelte. No React, no fetch: unit-tested in plain node (connect.test.ts).
//
// Honesty: a game card says what is actually happening (receiving, listening, off, refused) and how far its support
// is proven (the capability status's evidence tier, in words): a game implemented from community documentation is
// never shown as tested. Stepper ticks appear only when that game's packets are arriving.

import type {
  ConnectInfo,
  GameGuide,
  Integration,
  IntegrationKey,
  IntegrationUpdate,
  UdpSource,
} from "../endpoints/connect";
import type { SupportLevel } from "../endpoints/game";
import { UNKNOWN } from "../format";
import { SUPPORT_WORDS, supportTone } from "../game";

/** A sender counts as live while its last packet is younger than this (the Svelte page's rule). */
export const LIVE_SOURCE_S = 2;

export const AC_PLATFORMS: readonly { id: string; label: string }[] = [
  { id: "ps5", label: "PS5" },
  { id: "ps4", label: "PS4" },
  { id: "pc", label: "PC" },
];

export const GT7_VARIANTS: readonly { id: string; label: string; hint: string }[] = [
  { id: "C", label: "C", hint: "Richest: adds wheel angle and more" },
  { id: "B", label: "B", hint: "Also works" },
  { id: "~", label: "~", hint: "Also works" },
  { id: "A", label: "A", hint: "The original packet" },
];

/** "now", "3 s ago", "2 min ago", "never". */
export function ago(s: number | null | undefined): string {
  if (s === null || s === undefined || !Number.isFinite(s)) return "never";
  if (s < 1) return "now";
  if (s < 60) return `${Math.round(s)} s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  return `${Math.round(s / 3600)} h ago`;
}

export function isLiveSource(s: Pick<UdpSource, "last_seen_s">): boolean {
  return s.last_seen_s < LIVE_SOURCE_S;
}

/** "F1 25" from "f1_25", "GT7" from "gt7": the game id as the status line shows it. */
export function gameText(game: string | null | undefined): string {
  if (!game) return "telemetry";
  return game.replace(/_/g, " ").toUpperCase();
}

/** The status card's line (Svelte statusLine): what arrives from where, or why nothing does. */
export function statusLine(info: ConnectInfo): string {
  const t = info.telemetry;
  // The freshest sender on any input (F1's port, GT7, Forza, or the AC client), not only the F1 listener.
  const src = [...info.udp.sources, ...info.integrations.flatMap((g) => g.sources)].sort((a, b) => a.last_seen_s - b.last_seen_s)[0];
  if (t.status === "live") {
    const what = t.game ? `${gameText(t.game)}${t.packet_format ? ` (format ${t.packet_format})` : ""}` : "telemetry";
    return `Receiving ${what} from ${src ? src.ip : UNKNOWN} · ${Math.round(t.packets_per_s)} packets/s`;
  }
  if (t.status === "stale") {
    return `Last packet ${ago(t.last_packet_age_s)}${src ? ` from ${src.ip}` : ""}: is the game paused or in a menu?`;
  }
  return info.udp.listening ? `Listening on UDP ${info.udp.port}, waiting for the game` : `Not listening on UDP ${info.udp.port}`;
}

/** The status card's second line: track · session · platform · game version (only what is known). */
export function statusDetail(info: ConnectInfo): string {
  const t = info.telemetry;
  return [t.track, t.session_type ? t.session_type.replace(/_/g, " ") : null, t.platform ? t.platform.toUpperCase() : null, t.game_version ? `game v${t.game_version}` : null]
    .filter((x): x is string => Boolean(x))
    .join(" · ");
}

/** Assetto Corsa's card line: the client's state in words (pitwall asks the game for telemetry). */
export function acSummary(g: Integration): string {
  if (!g.enabled) return "Off";
  const c = g.client;
  if (!g.console_ip || !c) return "Enter the console's IP address, then get on track";
  const target = `${c.console_ip ?? UNKNOWN}:${c.port}`;
  switch (c.state) {
    case "streaming":
      return `Streaming from ${c.console_ip ?? UNKNOWN} · ${Math.round(c.rate)}/s`;
    case "subscribed":
      return `Handshake answered, waiting for the stream (${c.sent} sent)`;
    case "refused":
      return `${c.console_ip ?? UNKNOWN} refused (${c.sent} sent): not in a session yet. If you are on track, this console may not serve AC telemetry`;
    case "handshaking":
      return c.received
        ? `Stream stopped, asking ${target} again (pause, menu or new session?)`
        : `Asking ${target} for telemetry: get on track (${c.sent} sent, no answer yet)`;
    case "idle":
      return "Idle";
    case "stopped":
      return "Stopped";
  }
}

/** One line per game card: who is sending and how fast, or what it is waiting for. */
export function senderSummary(g: Integration): string {
  if (g.key === "ac") return acSummary(g);
  if (!g.enabled) return "Off";
  const live = g.sources.filter(isLiveSource);
  if (live.length) {
    const rate = Math.round(live.reduce((a, s) => a + s.packets_per_s, 0));
    return `Receiving from ${live.map((s) => s.ip).join(", ")} · ${rate}/s`;
  }
  if (g.received) return `${g.received.toLocaleString("en-GB")} packets so far · idle`;
  return g.listening ? `Listening on UDP ${g.port}, waiting for the game` : "Not listening";
}

export type CardState = "receiving" | "waiting" | "off" | "problem";

/** The card's state chip: Receiving (live packets), Waiting (on, nothing arriving), Off, Problem (an error). */
export function cardState(g: Integration): CardState {
  if (!g.enabled) return "off";
  if (g.error) return "problem";
  if (g.key === "ac") {
    const st = g.client?.state;
    if (st === "streaming") return "receiving";
    if (st === "refused") return "problem";
    return "waiting";
  }
  return g.sources.some(isLiveSource) ? "receiving" : "waiting";
}

export const CARD_STATE_LABEL: Record<CardState, string> = {
  receiving: "Receiving",
  waiting: "Waiting",
  off: "Off",
  problem: "Problem",
};

/** Evidence tier of a capability status (src/pitwall/capabilities.py vocabulary), in words. Never upgraded here. */
export interface Evidence {
  label: string;
  tone: "success" | "default" | "warning";
  /** The server's full status text, shown small next to the chip. */
  detail: string;
}

export function evidenceOfStatus(status: string | null | undefined): Evidence {
  const detail = (status ?? "").replace(/_/g, " ");
  const s = status ?? "";
  if (s.startsWith("capture_only")) return { label: "Records packets only", tone: "default", detail };
  // the same words and tones as Setup › Game (lib/game.ts): one evidence vocabulary across the Setup tabs
  const level = (Object.keys(SUPPORT_WORDS) as SupportLevel[]).find((l) => s.startsWith(l));
  if (level) {
    const tone = supportTone(level);
    return { label: SUPPORT_WORDS[level], tone: tone === "danger" ? "warning" : tone, detail };
  }
  return { label: s ? detail : "Unknown", tone: "warning", detail };
}

/** The guide that belongs to an integration (F1's guide id is "f1_25"). */
export function guideFor(guides: readonly GameGuide[], key: IntegrationKey): GameGuide | null {
  const id = key === "f1" ? "f1_25" : key;
  return guides.find((g) => g.id === id) ?? null;
}

/** "EA SPORTS F1 25 · PS5" style plain-text copy of a guide's settings (Copy all settings). */
export function guideText(g: GameGuide): string {
  const lines = [g.game, `${g.menu_path}:`];
  for (const s of g.steps) lines.push(`  ${s.label}: ${s.value}`);
  for (const s of g.extras) lines.push(`  ${s.label}: ${s.value}${s.note ? `  (${s.note})` : ""}`);
  return lines.join("\n");
}

/** The last step every game shares (spec 7.1 "drive out"), added unless the guide already says to get on track. */
export const DRIVE_OUT_STEP: GameGuide["steps"][number] = {
  label: "Drive out of the garage",
  value: "Packets show up under Live senders",
  copy: false,
  note: "",
};

/** The guide's steps in menu order, ending with getting on track. */
export function guideSteps(guide: GameGuide): GameGuide["steps"] {
  const onTrack = guide.steps.some((s) => /on track|drive out/i.test(`${s.label} ${s.value}`));
  return onTrack ? guide.steps : [...guide.steps, DRIVE_OUT_STEP];
}

/** Pro Stepper position: every step complete while this game's packets arrive; otherwise no step is claimed done. */
export function guideStep(g: Integration | null, guide: GameGuide): number {
  return g !== null && cardState(g) === "receiving" ? guideSteps(guide).length : -1;
}

/** Label of the console address field. */
export function consoleIpLabel(g: Pick<Integration, "key">): string {
  return g.key === "ac" ? "Console or PC IP" : "PS5 IP";
}

export function consoleIpPlaceholder(g: Pick<Integration, "key">): string {
  return g.key === "ac" ? "e.g. 192.168.1.50" : "e.g. 192.168.1.100";
}

// ---------------------------------------------------------------------------------------------- drafts
/** What the driver is typing (kept apart from the 2 s refresh so it is never overwritten). */
export interface Draft {
  console_ip: string;
  port: string;
}

export function draftFrom(g: Pick<Integration, "console_ip" | "port">): Draft {
  return { console_ip: g.console_ip ?? "", port: String(g.port) };
}

/** Does the draft differ from what the server has? */
export function draftDirty(g: Integration, d: Draft | undefined): boolean {
  if (!d) return false;
  if (g.needs_console_ip && d.console_ip.trim() !== (g.console_ip ?? "")) return true;
  if (g.port_editable && d.port.trim() !== String(g.port)) return true;
  return false;
}

/**
 * The PUT body for a draft: only the fields that changed. Returns an error message for a port that is not a whole
 * number from 1024 to 65535 (the server checks the rest: LAN-only addresses, reserved ports, conflicts).
 */
export function updateFromDraft(g: Integration, d: Draft): { body: IntegrationUpdate | null; error: string | null } {
  const body: IntegrationUpdate = {};
  if (g.needs_console_ip) {
    const ip = d.console_ip.trim();
    if (ip !== (g.console_ip ?? "")) body.console_ip = ip === "" ? null : ip;
  }
  if (g.port_editable) {
    const p = d.port.trim();
    if (p !== String(g.port)) {
      if (!/^\d+$/.test(p) || Number(p) < 1024 || Number(p) > 65535) {
        return { body: null, error: "Port must be a whole number from 1024 to 65535" };
      }
      body.port = Number(p);
    }
  }
  return { body: Object.keys(body).length ? body : null, error: null };
}

// ---------------------------------------------------------------------------------------------- live senders
export interface SenderRow {
  id: string;
  ip: string;
  port: number;
  /** Which input it arrives on ("EA SPORTS F1 25", "Gran Turismo 7"). */
  input: string;
  packetsPerS: number;
  packets: number;
  lastSeenS: number;
  live: boolean;
}

/** Every device sending to any input, freshest first (the F1 listener's senders appear once). */
export function senderRows(info: ConnectInfo): SenderRow[] {
  const rows = new Map<string, SenderRow>();
  const add = (s: UdpSource, input: string) => {
    const id = `${input}|${s.ip}:${s.port}`;
    if (rows.has(id)) return;
    rows.set(id, {
      id,
      ip: s.ip,
      port: s.port,
      input,
      packetsPerS: s.packets_per_s,
      packets: s.packets,
      lastSeenS: s.last_seen_s,
      live: isLiveSource(s),
    });
  };
  const f1 = info.integrations.find((g) => g.key === "f1");
  for (const g of info.integrations) for (const s of g.sources) add(s, g.name);
  for (const s of info.udp.sources) add(s, f1?.name ?? `UDP ${info.udp.port}`);
  return [...rows.values()].sort((a, b) => a.lastSeenS - b.lastSeenS);
}

/** Packets decoded on the F1 port: total minus rejected and unrecognised (never below zero). */
export function decodedPackets(t: ConnectInfo["telemetry"]): number {
  return Math.max(0, t.packets - t.rejected - t.unrecognised);
}

/** The capture file name without its folder; null when nothing is recorded yet. */
export function captureName(path: string | null | undefined): string | null {
  if (!path) return null;
  return path.split("/").pop() ?? path;
}

/** The last decode error the server reported, if any. */
export function lastDecodeError(t: ConnectInfo["telemetry"]): string | null {
  const e = t.decode?.["last_error"];
  return typeof e === "string" && e.trim() ? e : null;
}

/** Games in the order the page shows them: the selected game's input first (game selection), then F1 (always on),
 * then the enabled ones, then the rest. */
export function orderedIntegrations(list: readonly Integration[], selectedKey: IntegrationKey | null = null): Integration[] {
  const rank = (g: Integration) => (selectedKey !== null && g.key === selectedKey ? -1 : g.key === "f1" ? 0 : g.enabled ? 1 : 2);
  return list.map((g, i) => ({ g, i })).sort((a, b) => rank(a.g) - rank(b.g) || a.i - b.i).map((x) => x.g);
}

/** A guide by its connect.py id (the catalogue entry's guide_id), or null. */
export function guideById(guides: readonly GameGuide[], id: string | null | undefined): GameGuide | null {
  return id ? (guides.find((g) => g.id === id) ?? null) : null;
}
