// Pure helpers for the Drive › Coach panels (lane DV): content equality for memoised panels, bar and ribbon
// geometry, and the small view models the panels need beyond lib/drive/model.ts. No React; tested in plain node.

import { cornerLabelOf, officialNameOf } from "../../../lib/drive/corner";
import type { DeltaView } from "../../../lib/drive/delta";
import type { EndedCard, HeroView } from "../../../lib/drive/model";
import type { TrackModelNext } from "../../../lib/drive/types";
import type { GameEntry, TransportKind } from "../../../lib/endpoints/game";
import { featureOf, unavailable } from "../../../lib/game";

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

/** A sender as /api/connect reports it (ingest source_snapshot). */
interface ConnectSource {
  ip: string;
  port: number;
  packets: number;
  last_seen_s: number;
}

/** The fields of GET /api/connect the no-telemetry card reads (pitwall/connect.py + api/app.py connect_page). */
export interface ConnectInfo {
  mac?: { lan_ip?: string | null; udp_port?: number | null } | null;
  udp?: {
    listening?: boolean;
    port?: number | null;
    received?: number | null;
    sources?: ConnectSource[] | null;
  } | null;
  guides?:
    | {
        id: string;
        game: string;
        supported: boolean;
        menu_path: string;
        steps: { label: string; value: string; note?: string }[];
      }[]
    | null;
  telemetry?: { hint?: string | null } | null;
  /** Per input (Runtime.input_status): on/off, its senders, the console IP; AC's client state. */
  integrations?:
    | {
        key: string;
        enabled?: boolean;
        listening?: boolean;
        console_ip?: string | null;
        sources?: ConnectSource[] | null;
        client?: { last_rx_s_ago?: number | null } | null;
      }[]
    | null;
}

/** The selected game, as far as the no-telemetry card needs it (lib/endpoints/game.ts GameEntry). */
export interface NoTelemetryGame {
  /** The game in sentences ("GT7", "Assetto Corsa"). */
  name: string;
  /** connect.py guide id: "f1_25", "gt7", "forza", "ac", "record". */
  guideId: string | null;
  /** How telemetry gets here (transport.kind). */
  kind: TransportKind;
  /** The port it arrives on (transport.port); null for Assetto Corsa (Pitwall contacts the console). */
  port: number | null;
  /** The input's key on /api/connect ("f1", "gt7", ...). */
  integration: string | null;
  /** F1 UDP format the game must send ("2026" for the Season Pack), or null. */
  variant: string | null;
}

/** The no-telemetry card's game from a catalogue entry (null: no entry selected, the card works as before). */
export function noTelemetryGame(
  e: Pick<GameEntry, "text_name" | "guide_id" | "transport" | "integration" | "variant"> | null | undefined,
): NoTelemetryGame | null {
  if (!e) return null;
  return {
    name: e.text_name,
    guideId: e.guide_id,
    kind: e.transport.kind,
    port: e.transport.port,
    integration: e.integration,
    variant: e.variant,
  };
}

export interface NoTelemetryStep {
  title: string;
  description: string;
  /** The whole title is a value the driver types into the game (IP / port): shown in the mono face. */
  mono: boolean;
  /** The title in parts when only a value inside it is mono ("Console IP" + "192.168.1.100"); absent = `title`. */
  parts?: { text: string; mono: boolean }[];
}

export interface NoTelemetryView {
  steps: [NoTelemetryStep, NoTelemetryStep, NoTelemetryStep];
  /** 0-based step the driver is on: 0 until any sender has been seen, then 2. */
  current: number;
  /** The server's diagnosis of packets it could not use, verbatim, or null. */
  hint: string | null;
  /** "Listening on UDP 20777", or null when unknown (or nothing listens: Assetto Corsa). */
  listening: string | null;
  /** Nothing can arrive until the console's IP is entered (Assetto Corsa without one; GT7 with its input off and
   * no IP): the card leads with that, not with "Waiting for telemetry". */
  needsIp: boolean;
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

function lastSender(sources: readonly ConnectSource[]): ConnectSource | null {
  return sources.length ? sources.reduce((a, b) => (b.last_seen_s < a.last_seen_s ? b : a)) : null;
}

/** The menu path in the game's words with "›" ("Settings › Telemetry Settings"). */
function menuPath(path: string): string {
  return path
    .split(">")
    .map((x) => x.trim())
    .filter(Boolean)
    .join(" › ");
}

/**
 * The three steps of the no-telemetry card from /api/connect (unknown values are "-"; nothing is invented). With a
 * selected game the steps follow its guide (`game.guideId`) and its port; without one, the first supported guide
 * (F1 25), as before game selection. Games Pitwall contacts itself (GT7's heartbeat, Assetto Corsa's handshake)
 * have nothing to set in the game: their steps are "Enable on Setup › Connect", the console IP, "Get on track".
 */
export function noTelemetryView(c: ConnectInfo | undefined, game: NoTelemetryGame | null = null): NoTelemetryView {
  const guides = c?.guides ?? [];
  const guide = game?.guideId ? (guides.find((g) => g.id === game.guideId) ?? null) : (guides.find((g) => g.supported) ?? null);
  const step = (label: RegExp) => guide?.steps.find((s) => label.test(s.label)) ?? null;
  const input = game?.integration ? (c?.integrations?.find((i) => i.key === game.integration) ?? null) : null;
  const ip = ipOf(c);
  const port = game ? (game.port ?? null) : portOf(c);
  const sources = input?.sources ?? (game && game.integration !== "f1" ? [] : (c?.udp?.sources ?? []));
  const last = lastSender(sources);
  const rxAgo = input?.client?.last_rx_s_ago;
  const hint = c?.telemetry?.hint;
  const hintText = typeof hint === "string" && hint ? hint : null;
  const listeningOn = input ? input.listening !== false : c?.udp?.listening !== false;
  const listening = port != null && game?.kind !== "udp_client" && listeningOn ? `Listening on UDP ${port}` : null;
  const lastText = last
    ? `Last sender seen: ${last.ip} · ${age(last.last_seen_s)}`
    : typeof rxAgo === "number" && Number.isFinite(rxAgo)
      ? `Last packet: ${age(rxAgo)}`
      : "Last sender seen: none";
  const seen = last !== null || (typeof rxAgo === "number" && Number.isFinite(rxAgo));

  if (game && (game.kind === "udp_heartbeat" || game.kind === "udp_client")) {
    const enable = guide?.steps[0] ?? null;
    const ipStep = step(/^console ip$/i);
    const consoleIp = input?.console_ip ?? null;
    const client = game.kind === "udp_client";
    const on = !!input?.enabled;
    const where = ipStep?.note ? menuPath(ipStep.note) : "The console's address on your network";
    // GT7 without an IP searches the network only once switched on (Setup › Game: Search the network)
    const needsIp = !consoleIp && (client || !on);
    const ipTitle: NoTelemetryStep = consoleIp
      ? {
          title: `Console IP ${consoleIp}`,
          description: where,
          mono: false,
          parts: [
            { text: "Console IP ", mono: false },
            { text: consoleIp, mono: true },
          ],
        }
      : needsIp
        ? { title: "Enter the console's IP address", description: `On Setup › Game. ${where}`, mono: false }
        : { title: "Console IP not set: Pitwall searches the network", description: `Optional. ${where}`, mono: false };
    return {
      steps: [
        on
          ? {
              title: `${game.name} input on`,
              description: enable?.note ? sentenceCase(enable.note) : "Switched on",
              mono: false,
            }
          : {
              title: `Switch the ${game.name} input on`,
              description: client
                ? "On Setup › Connect"
                : "Entering the console's IP switches it on, or let Pitwall search the network (Setup › Game)",
              mono: false,
            },
        ipTitle,
        { title: "Get on track", description: lastText, mono: false },
      ],
      current: seen ? 2 : needsIp && on ? 1 : on ? 2 : 0,
      hint: hintText,
      listening,
      needsIp,
    };
  }

  const on = step(/^(udp telemetry|data out)$/i);
  const fmt = step(/^(udp format|data out packet format)$/i);
  const fmtValue = fmt && game?.variant && /udp format/i.test(fmt.label) ? game.variant : fmt?.value;
  const path = guide ? menuPath(guide.menu_path) : null;
  const first =
    path && on ? `${path} › ${on.label}: ${on.value}${fmt ? `, ${fmt.label} ${fmtValue}` : ""}` : "In the game's telemetry settings";
  return {
    steps: [
      { title: on && /data out/i.test(on.label) ? "Turn on Data Out in the game" : "Turn on UDP telemetry in the game", description: first, mono: false },
      { title: `IP ${ip ?? "-"} · port ${port ?? "-"}`, description: "This Mac's LAN address", mono: true },
      { title: "Drive out of the garage", description: lastText, mono: false },
    ],
    current: seen ? 2 : 0,
    hint: hintText,
    listening,
    needsIp: false,
  };
}

function sentenceCase(s: string): string {
  return s ? s[0]!.toUpperCase() + s.slice(1) : s;
}

// ------------------------------------------------------------------------------------------- game on Coach

/** What the selected / detected game changes on Coach (game selection spec 5.3): nothing else moves. */
export interface CoachGameView {
  /** "Sectors · Not sent by GT7": the sector slot shows one muted cell; null = the three cells. */
  sectors: string | null;
  /** The game sends no lap distance, Pitwall estimates it: the delta header says "· estimated". */
  deltaEstimated: boolean;
}

export const NO_COACH_GAME: CoachGameView = { sectors: null, deltaEstimated: false };

/** From the effective entry (the game of the data on screen). Only known facts change anything: an unknown sector
 * feature keeps the three "-" cells (P5). */
export function coachGameView(entry: GameEntry | null | undefined): CoachGameView {
  if (!entry) return NO_COACH_GAME;
  const sect = featureOf(entry, "sectors");
  return {
    sectors: sect && unavailable(sect) ? `Sectors · ${sect.short}` : null,
    deltaEstimated: featureOf(entry, "delta")?.status === "partial",
  };
}

/** The delta panel's header with the estimate marked ("Delta to reference · estimated"). */
export function estimatedDelta<D extends { label: string }>(d: D, estimated: boolean): D {
  return estimated ? { ...d, label: `${d.label} · estimated` } : d;
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
