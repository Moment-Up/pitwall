// Pure helpers for the Drive › Coach panels (lane DV): content equality for memoised panels, bar and ribbon
// geometry, and the small view models the panels need beyond lib/drive/model.ts. No React; tested in plain node.

import { cornerLabelOf, officialNameOf } from "../../../lib/drive/corner";
import type { DeltaView } from "../../../lib/drive/delta";
import type { EndedCard, HeroView } from "../../../lib/drive/model";
import type { TrackModelNext } from "../../../lib/drive/types";

/** Deep equality for plain view-model data (objects, arrays, primitives). Panels re-render only when it is false. */
export function sameView(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  if (typeof a !== "object" || typeof b !== "object" || a === null || b === null) return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  if (Array.isArray(a)) {
    const bb = b as unknown[];
    return a.length === bb.length && a.every((v, i) => sameView(v, bb[i]));
  }
  const ka = Object.keys(a);
  const kb = Object.keys(b);
  if (ka.length !== kb.length) return false;
  const ra = a as Record<string, unknown>;
  const rb = b as Record<string, unknown>;
  return ka.every((k) => Object.prototype.hasOwnProperty.call(rb, k) && sameView(ra[k], rb[k]));
}

/** Props equality for React.memo: every prop compared by content. */
export function sameProps<P extends object>(a: Readonly<P>, b: Readonly<P>): boolean {
  return sameView(a, b);
}

/** A fraction 0..1 as an SVG / CSS percentage ("45.123%"), clamped. */
export function pct(f: number): string {
  const v = Math.min(1, Math.max(0, Number.isFinite(f) ? f : 0));
  return `${Math.round(v * 100_000) / 1000}%`;
}

/** Scale of the two half-width delta fills (left = ahead, right = behind) for a bar value -1..1. */
export function deltaFills(bar: number): { ahead: number; behind: number } {
  const v = Number.isFinite(bar) ? Math.min(1, Math.max(-1, bar)) : 0;
  return { ahead: v < 0 ? -v : 0, behind: v > 0 ? v : 0 };
}

/** The delta panel's scale labels (mockup): with a value "◀ ahead · 1.0" "0" "1.0 · behind ▶"; unknown the ends only. */
export function deltaScale(d: Pick<DeltaView, "tone">): string[] {
  return d.tone === "unknown" ? ["◀ ahead", "behind ▶"] : ["◀ ahead · 1.0", "0", "1.0 · behind ▶"];
}

/** A bar value rounded so tiny changes do not re-render (0.5 % steps); null stays null. */
export function barStep(v: number | null | undefined): number | null {
  if (typeof v !== "number" || !Number.isFinite(v)) return null;
  return Math.round(Math.min(1, Math.max(0, v)) * 200) / 200;
}

/** The sector cells' per-cell caption ("last lap · L6") from the panel caption ("Last lap · L6"). */
export function cellCaption(caption: string | null | undefined): string | null {
  if (!caption) return null;
  return caption[0]!.toLowerCase() + caption.slice(1);
}

/** The hero without the per-frame fields (corner metres, approach), so the hero re-renders only when its text does.
 * The approach bar is its own memoised component. */
export function heroText(h: HeroView): HeroView {
  if (h.kind !== "corner") return h;
  const { corner: _corner, approach: _approach, ...rest } = h;
  return rest as HeroView;
}

// ------------------------------------------------------------------------------------------- radio on the Ready card

export interface RadioSeat {
  text: string;
  tone: "default" | "success" | "warning";
}

/** "Radio: Off" / "Radio: Live · mic OK" (4.9 Ready card, Today column). */
export function radioSeat(phase: string, mic: string, micLabel: string): RadioSeat {
  if (phase === "idle") return { text: "Off", tone: "default" };
  if (phase === "live" && mic === "live") return { text: "Live · mic OK", tone: "success" };
  if (phase === "starting") return { text: "Starting…", tone: "warning" };
  return { text: `Live · ${micLabel}`, tone: "warning" };
}

// --------------------------------------------------------------------------------------- no-telemetry card (4.9)

/** The fields of GET /api/connect the no-telemetry card reads (pitwall/connect.py + api/app.py connect_page). */
export interface ConnectInfo {
  mac?: { lan_ip?: string | null; udp_port?: number | null } | null;
  udp?: {
    listening?: boolean;
    port?: number | null;
    received?: number | null;
    sources?: { ip: string; port: number; packets: number; last_seen_s: number }[] | null;
  } | null;
  guides?: { id: string; game: string; supported: boolean; menu_path: string; steps: { label: string; value: string }[] }[] | null;
  telemetry?: { hint?: string | null } | null;
}

export interface NoTelemetryStep {
  title: string;
  description: string;
  /** The value the driver types into the game (IP / port), shown in the mono face. */
  mono: boolean;
}

export interface NoTelemetryView {
  steps: [NoTelemetryStep, NoTelemetryStep, NoTelemetryStep];
  /** 0-based step the driver is on: 0 until any sender has been seen, then 2. */
  current: number;
  /** The server's diagnosis of packets it could not use, verbatim, or null. */
  hint: string | null;
  /** "Listening on UDP 20777", or null when unknown. */
  listening: string | null;
}

const IP_PLACEHOLDER = "<this Mac's IP>";

function ipOf(c: ConnectInfo | undefined): string | null {
  const ip = c?.mac?.lan_ip;
  return typeof ip === "string" && ip && ip !== IP_PLACEHOLDER ? ip : null;
}

function portOf(c: ConnectInfo | undefined): number | null {
  const p = c?.udp?.port ?? c?.mac?.udp_port;
  return typeof p === "number" && Number.isFinite(p) ? p : null;
}

function age(s: number): string {
  if (s < 60) return `${Math.round(s)} s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  return `${Math.round(s / 3600)} h ago`;
}

/** The three steps of the no-telemetry card from /api/connect (unknown values are "-"; nothing is invented). */
export function noTelemetryView(c: ConnectInfo | undefined): NoTelemetryView {
  const guide = c?.guides?.find((g) => g.supported) ?? null;
  const step = (label: RegExp) => guide?.steps.find((s) => label.test(s.label)) ?? null;
  const on = step(/^udp telemetry$/i);
  const fmt = step(/^udp format$/i);
  const path = guide ? guide.menu_path.split(">").map((x) => x.trim()).filter(Boolean).join(" › ") : null;
  const first =
    path && on
      ? `${path} › ${on.label}: ${on.value}${fmt ? `, ${fmt.label} ${fmt.value}` : ""}`
      : "In the game's telemetry settings";
  const ip = ipOf(c);
  const port = portOf(c);
  const sources = c?.udp?.sources ?? [];
  const last = sources.length ? sources.reduce((a, b) => (b.last_seen_s < a.last_seen_s ? b : a)) : null;
  const hint = c?.telemetry?.hint;
  return {
    steps: [
      { title: "Turn on UDP telemetry in the game", description: first, mono: false },
      { title: `IP ${ip ?? "-"} · port ${port ?? "-"}`, description: "This Mac's LAN address", mono: true },
      {
        title: "Drive out of the garage",
        description: last ? `Last sender seen: ${last.ip} · ${age(last.last_seen_s)}` : "Last sender seen: none",
        mono: false,
      },
    ],
    current: last ? 2 : 0,
    hint: typeof hint === "string" && hint ? hint : null,
    listening: port != null && c?.udp?.listening !== false ? `Listening on UDP ${port}` : null,
  };
}

/** A learned corner as the driver reads it: official label and name ("T15 Stowe"), else the label alone; null when
 * the point names no corner. Resolved through the track model (the learned key "T4" can be the official "T6"). */
export function cornerTitle(model: TrackModelNext | null | undefined, corner: string | null | undefined): string | null {
  if (!corner) return null;
  const label = cornerLabelOf(model, corner);
  const name = officialNameOf(model, corner);
  return name && name !== label ? `${label} ${name}` : label;
}

/** The Session complete card's Work on / Went well corners, as plain strings (the card is memoised on content). */
export function endedCorners(
  ended: Pick<EndedCard, "workOn" | "wentWell">,
  model: TrackModelNext | null | undefined,
): { workOn: string | null; wentWell: string | null } {
  return { workOn: cornerTitle(model, ended.workOn?.corner), wentWell: cornerTitle(model, ended.wentWell?.corner) };
}
