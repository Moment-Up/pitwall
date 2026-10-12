// Game selection endpoints: typed client for GET /api/games, GET /api/games/{id}, GET/PUT/DELETE /api/game
// (src/pitwall/api/routes_game.py over src/pitwall/games.py). The JSON contract is the game-selection design spec,
// section 9.2: the backend emits exactly these keys (null, never a missing key, unless marked optional).
//
// The catalogue is one entry per capability row x platform (src/pitwall/capabilities.py) plus "other:any". Every
// support claim and every feature status is computed by the server from capabilities.py and the adapters'
// AdapterInfo, never stronger than that evidence; the dashboard only renders it (it never composes a reason).
// The selection is household-level (SettingsStore section "game"); selecting a game never disables anything.
//
// Errors: 422 {"detail": str} for an unknown id, an invalid console IP, or a console IP for a game that needs none;
// 404 from GET /api/games/{id} for an unknown id. A port conflict is not an error: it comes back as a GameAction.

import { authFetch } from "../auth";
import type { GameGuide } from "./connect";

export type SupportLevel =
  | "live_validated"
  | "recorded_validated"
  | "spec_implemented"
  | "community_documented"
  | "partial"
  | "unverified"
  | "unsupported";
export type GamePlatform = "ps5" | "ps4" | "xbox" | "pc" | "any";
export type FeatureStatus = "supported" | "partial" | "not_sent" | "not_implemented" | "unknown";
export type FeatureGroup = "timing" | "coaching" | "track" | "car" | "session" | "setup_radio";
export type FeatureId =
  | "lap_timing"
  | "sectors"
  | "delta"
  | "braking_cues"
  | "corner_coaching"
  | "track_map"
  | "official_corner_names"
  | "ai_field"
  | "flags"
  | "fuel"
  | "tyre_temps"
  | "tyre_wear"
  | "tyre_pressures"
  | "brake_temps"
  | "engine_temp" // health lane
  | "damage"
  | "ers"
  | "drs"
  | "weather"
  | "session_info"
  | "field_data"
  | "setup_telemetry"
  | "setup_recommendations"
  | "wheel_ptt";
export type GameIntegrationKey = "f1" | "gt7" | "forza" | "ac" | "record";
export type ConsoleIpNeed = "required" | "optional" | "no";
export type TransportKind = "udp_listen" | "udp_heartbeat" | "udp_client" | "none";

/** Every feature id, in the order the server lists them (section 2.4). */
export const FEATURE_IDS: readonly FeatureId[] = [
  "lap_timing",
  "sectors",
  "delta",
  "braking_cues",
  "corner_coaching",
  "track_map",
  "official_corner_names",
  "ai_field",
  "flags",
  "fuel",
  "tyre_temps",
  "tyre_wear",
  "tyre_pressures",
  "brake_temps",
  "engine_temp", // health lane
  "damage",
  "ers",
  "drs",
  "weather",
  "session_info",
  "field_data",
  "setup_telemetry",
  "setup_recommendations",
  "wheel_ptt",
];

export interface GameFeature {
  id: FeatureId;
  /** "Tyre wear" */
  label: string;
  group: FeatureGroup;
  status: FeatureStatus;
  /** Only for supported/partial telemetry features; never stronger than support.level. */
  evidence: SupportLevel | null;
  /** "" | "Estimated" | "Partial" | "Not sent by GT7" | "Not in Pitwall yet" | "Unknown" (<= 32 chars). */
  short: string;
  /** One plain sentence for the driver (the server's words, shown verbatim). */
  reason: string;
  /** Technical provenance (FieldSupport sources, the capability row key). */
  detail: string;
  /** Optional context, e.g. the track map's outline note. */
  note: string | null;
  /** AdapterInfo field keys behind it ([] for code facts). */
  fields: string[];
}

export interface GameField {
  level: SupportLevel;
  status: "sent" | "partial" | "not_sent" | "unknown";
  source: string;
}

export interface GameEntry {
  /** "gt7:ps5" */
  id: string;
  /** "gt7" */
  game_key: string;
  /** "Gran Turismo 7" */
  label: string;
  /** "GT7", "Forza M" (chips, at most 7 characters) */
  short_label: string;
  /** "GT7" (sentences) */
  text_name: string;
  platform: GamePlatform;
  /** "PS5", "PS5 (PS4 version)" */
  platform_label: string;
  group: "main" | "more";
  /** "f1_25" | "gt7" | "forza_motorsport" | "forza_horizon" | "ac" | null */
  adapter_game: string | null;
  /** F1 UDP format "2025" | "2026" | null */
  variant: string | null;
  implemented: boolean;
  integration: GameIntegrationKey | null;
  support: {
    level: SupportLevel | null;
    words: string;
    /** One plain sentence on how far it is tested (optional: servers before review round 1 omit it). */
    summary?: string;
    /** The capability row's notes (technical: sources, offsets, what was tested). */
    note: string;
    capability_row: string | null;
  };
  transport: {
    kind: TransportKind;
    summary: string;
    port: number | null;
    console_port: number | null;
    console_ip: ConsoleIpNeed;
    in_game_setting: boolean;
  };
  /** connect.py GameGuide.id: "f1_25" | "gt7" | "forza" | "ac" | "record" */
  guide_id: string | null;
  rig: { game: "f1_25" | "gt7"; platform: "ps5" | "pc" | null } | null;
  /** All 24, in FEATURE_IDS order. */
  features: GameFeature[];
  notes: string[];
  /** Only GET /api/games/{id}. */
  fields?: Record<string, GameField>;
  /** Only GET /api/games/{id}: the connect.py guide with this machine's values filled in. */
  guide?: GameGuide | null;
}

export interface GamesResponse {
  schema: 1;
  /** Catalogue order. */
  entries: GameEntry[];
  features: { id: FeatureId; label: string; group: FeatureGroup; noun: string }[];
  groups: { id: FeatureGroup; label: string }[];
  support_words: Record<SupportLevel, string>;
}

export interface DetectedGame {
  entry_id: string | null;
  /** Game value of the live session (or the last auto-detected sender). */
  adapter_game: string;
  platform: GamePlatform | "unknown";
  variant: string | null;
  /** false for synthetic sessions and replays. */
  real: boolean;
  status: "live" | "stale";
}
export type MismatchKind = "game" | "platform" | "variant";
export interface GameMismatch {
  kind: MismatchKind;
  selected_id: string;
  detected_id: string | null;
  text: string;
}
export interface GameSuggestion {
  id: string;
  source: "live" | "history";
  text: string;
}
export interface GameSelection {
  id: string;
  since_unix: number;
  source: "dashboard" | "cli" | "driver_default";
  /** source "driver_default": the driver whose usual game it is (absent from servers before v0.2.0). */
  by_driver_id?: number | null;
  /** That driver's name (GET /api/game only); null when the profile is gone. */
  by_driver_name?: string | null;
}
export interface GameInput {
  key: GameIntegrationKey;
  name: string;
  enabled: boolean;
  listening: boolean;
  received: number;
  console_ip: string | null;
  console_ip_need: ConsoleIpNeed;
  port: number | null;
  /** AC only. */
  platform: string | null;
  error: string | null;
  in_use: boolean;
}
export interface OtherInput {
  key: GameIntegrationKey;
  name: string;
  enabled: boolean;
  in_use: boolean;
  can_disable: boolean;
}

/** GET /api/game, DELETE /api/game. */
export interface GameState {
  selected: GameSelection | null;
  /** The selected entry (no fields / guide). */
  entry: GameEntry | null;
  effective_id: string | null;
  /** selected === null */
  first_run: boolean;
  detected: DetectedGame | null;
  mismatch: GameMismatch | null;
  suggestion: GameSuggestion | null;
  input: GameInput | null;
  other_inputs: OtherInput[];
  /** Stretch 3.6 shipped (per-driver "Usually plays"). */
  driver_defaults: boolean;
}

export interface GamePut {
  id: string;
  console_ip?: string | null;
  ensure_input?: boolean;
}
export type GameActionKind =
  | "enabled"
  | "already_enabled"
  | "set_platform"
  | "set_console_ip"
  | "needs_console_ip"
  | "skipped_live"
  | "error"
  | "none";
export interface GameAction {
  key: GameIntegrationKey | null;
  action: GameActionKind;
  message: string;
}
export interface GamePutResponse {
  state: GameState;
  actions: GameAction[];
}

/** Snapshot.game on every /ws/live snapshot and GET /api/live (absent only from servers before this feature). */
export interface SnapshotGame {
  selected_id: string | null;
  effective_id: string | null;
  detected: DetectedGame | null;
  mismatch: GameMismatch | null;
  /** Live suggestions only. */
  suggestion: GameSuggestion | null;
  /** Why the selected game is selected ("dashboard" | "cli" | "driver_default"); absent with no selection and on
   * older servers. */
  selected_source?: string | null;
  /** source "driver_default": the driver whose usual game it is. */
  selected_by?: number | null;
}

/** A non-2xx answer with FastAPI's detail in words (422 invalid id or console IP, 404 unknown entry). */
export class GameApiError extends Error {
  readonly status: number;
  readonly detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.name = "GameApiError";
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
    throw new GameApiError(r.status, detailOf(body, `${r.status} ${r.statusText}`.trim()));
  }
  return r.json() as Promise<T>;
}

export const gameApi = {
  /** The catalogue: every entry with its features, without fields or guide (static per server version). */
  games: () => req<GamesResponse>("/api/games"),
  /** One entry with its fields and its connect guide (this machine's values filled in). */
  entry: (id: string) => req<GameEntry>(`/api/games/${encodeURIComponent(id)}`),
  state: () => req<GameState>("/api/game"),
  /** Select a game; ensures its input is on (never disables another). Answers with the state and what was done. */
  put: (body: GamePut) =>
    req<GamePutResponse>("/api/game", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  /** Clear the selection (inputs are untouched). */
  clear: () => req<GameState>("/api/game", { method: "DELETE" }),
};

/** Request-cache keys (src/lib/cache.ts). invalidate("game:state") after a PUT / DELETE. */
export const GAME_KEYS = {
  games: "games",
  state: "game:state",
  entry: (id: string) => `game:entry:${id}`,
} as const;

/** The catalogue changes only with a server release (and an edited port): fetched once per app load. */
export const GAMES_MAX_AGE_MS = 60 * 60_000;
