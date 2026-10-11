// Connect endpoints (lane X, spec 7.1 and 12.4): typed client for GET /api/connect (src/pitwall/api/app.py
// `connect_page` + src/pitwall/connect.py `connect_info`) and GET/PUT /api/integrations (src/pitwall/integrations.py,
// Runtime.input_status in src/pitwall/core/runtime.py). Behaviour reference: web/src/views/ConnectView.svelte.
//
// /api/connect carries this Mac's addresses, the per-game setup guides (data, not prose, so every value the driver
// types into a game menu can be copied), the UDP listener and its senders, the telemetry status, radio devices and
// the integrations (one per telemetry protocol: F1, GT7, Forza, Assetto Corsa, record-only). PUT
// /api/integrations/{key} switches a game on or off and sets its console IP, port, GT7 variant or AC platform; it is
// applied at once and answers with the new integration list. Errors: 422 (invalid value, the detail says why in
// words), 409 (two enabled games would share a port).

import { authFetch } from "../auth";

/** One device sending UDP to a listener (ingest source_snapshot). */
export interface UdpSource {
  ip: string;
  port: number;
  packets: number;
  bytes: number;
  packets_per_s: number;
  last_seen_s: number;
  connected_s: number;
}

export interface GuideStep {
  /** Menu item as the game names it. */
  label: string;
  /** What to set (this Mac's IP and the ports are filled in by the server). */
  value: string;
  /** Show a copy button (values the driver types, e.g. the IP). */
  copy: boolean;
  note: string;
}

export interface GameGuide {
  id: string;
  game: string;
  platforms: string[];
  supported: boolean;
  menu_path: string;
  steps: GuideStep[];
  /** Optional but recommended. */
  extras: GuideStep[];
  notes: string[];
}

/** Assetto Corsa: pitwall registers with the game (no port to set), so its card shows the client's state. */
export type AcClientState = "idle" | "handshaking" | "subscribed" | "streaming" | "refused" | "stopped";

export interface AcClient {
  state: AcClientState;
  console_ip: string | null;
  port: number;
  sent: number;
  received: number;
  handshakes_answered: number;
  refused: number;
  cycles: number;
  last_error: string | null;
  rate: number;
  last_rx_s_ago: number | null;
  last_handshake: { size: number; encoding: string; car: string | null; track: string | null; config: string | null } | null;
  platform: string | null;
}

export interface Gt7Heartbeat {
  console_ip?: string | null;
  target?: string | null;
  variant?: string;
  running?: boolean;
  interval_s?: number;
  sent?: number;
  errors?: number;
  last_error?: string | null;
  last_sent_s_ago?: number | null;
}

export type IntegrationKey = "f1" | "gt7" | "forza" | "ac" | "record" | (string & {});

export interface Integration {
  key: IntegrationKey;
  name: string;
  enabled: boolean;
  /** The listening port; for AC the game's own port (nothing is bound on this Mac). */
  port: number;
  console_ip: string | null;
  /** GT7 packet variant (A, B, ~, C). */
  variant: string;
  /** AC only: what runs the game (ps5 | ps4 | pc). */
  platform?: string | null;
  platforms: string[];
  /** Capability status with its evidence tier, e.g. "live_validated (PS5)", "community_documented". */
  status: string;
  port_editable: boolean;
  needs_console_ip: boolean;
  /** false: no UDP port is bound on this Mac (AC's client registers with the game). */
  listens?: boolean;
  listening: boolean;
  received: number;
  sources: UdpSource[];
  capture: string | null;
  error: string | null;
  heartbeat?: Gt7Heartbeat | null;
  client?: AcClient | null;
}

export type TelemetryStatus = "live" | "stale" | "no_data";

export interface ConnectTelemetry {
  status: TelemetryStatus;
  last_packet_age_s: number | null;
  packets: number;
  packets_per_s: number;
  rejected: number;
  unrecognised: number;
  source?: string | null;
  synthetic: boolean;
  decode: Record<string, unknown>;
  game: string | null;
  track: string | null;
  session_type: string | null;
  platform: string | null;
  packet_format: number | null;
  game_version: string | null;
  /** A plain-words fix for the decode error seen, e.g. the wrong UDP Format. */
  hint: string | null;
}

export interface RadioDevice {
  name: string;
  mic_live: boolean;
  device_tts: boolean;
  dropped: number;
}

export interface ConnectInfo {
  mac: {
    hostname: string;
    lan_ip: string;
    lan_addresses: { interface: string; ip: string }[];
    udp_port: number;
    http_port: number;
  };
  urls: {
    /** For the iPad / iPhone radio (the microphone needs HTTPS); null without Tailscale. */
    tailscale_https: string | null;
    /** Any browser on the LAN, no microphone. Carries the access token: shown to the user, never logged. */
    lan_with_token: string;
    local: string;
  };
  guides: GameGuide[];
  udp: { listening: boolean; port: number; received: number; sources: UdpSource[]; capture: string | null };
  telemetry: ConnectTelemetry;
  radio: RadioDevice[];
  radio_enabled: boolean;
  dashboards: number;
  integrations: Integration[];
  /** The selected game's catalogue id (lib/endpoints/game.ts); absent from servers before game selection. */
  selected_game?: string | null;
}

/** A partial update for PUT /api/integrations/{key} (only the fields being changed). */
export interface IntegrationUpdate {
  enabled?: boolean;
  port?: number;
  console_ip?: string | null;
  variant?: string;
  platform?: string;
}

/** A non-2xx answer with FastAPI's detail in words (422 invalid value, 409 port conflict). */
export class ConnectError extends Error {
  readonly status: number;
  readonly detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ConnectError";
    this.status = status;
    this.detail = detail;
  }
}

function detailOf(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string" && d.trim()) return d;
    if (Array.isArray(d)) {
      const msgs = d
        .map((x) => (x && typeof x === "object" && "msg" in x ? String((x as { msg: unknown }).msg) : String(x)))
        .filter(Boolean);
      if (msgs.length) return msgs.join("; ");
    }
  }
  return fallback;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await authFetch(path, init);
  if (!r.ok) {
    let body: unknown = null;
    try {
      body = await r.json();
    } catch {
      /* not json */
    }
    throw new ConnectError(r.status, detailOf(body, `${r.status} ${r.statusText}`.trim()));
  }
  return r.json() as Promise<T>;
}

export const connectApi = {
  get: () => req<ConnectInfo>("/api/connect"),
  integrations: () => req<Integration[]>("/api/integrations"),
  /** Applied at once (listeners restart as needed); answers with the new integration list. */
  updateIntegration: (key: IntegrationKey, body: IntegrationUpdate) =>
    req<Integration[]>(`/api/integrations/${encodeURIComponent(key)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};

/** Request-cache keys (src/lib/cache.ts). A successful update invalidates both. */
export const CONNECT_KEYS = { connect: "connect", integrations: "integrations" } as const;

/** Poll /api/connect this often while Setup › Connect is on screen (spec 12.3). */
export const CONNECT_POLL_MS = 2000;
