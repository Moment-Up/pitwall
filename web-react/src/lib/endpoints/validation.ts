// Rig validation kit endpoints (lane validate): typed client for /api/validation/* (src/pitwall/api/routes_validate.py,
// the JSON of src/pitwall/validate/model.py and report.py). The types between the CONTRACT markers are a verbatim copy
// of the lane's design contract (design/contract.ts): keep them identical to the backend's JSON; the client, keys and
// errors follow below them.
//
// Nothing here changes a capability status: the kit only collects evidence and the driver's verdicts. The page polls
// the compact Run every 2 s while visible; the device reporter (src/lib/validation/reporter.ts) polls /active every 20 s
// and posts ClientReports while a run is active.

import { accessToken, authFetch } from "../auth";

// ---------------------------------------------------------------------------------------------- CONTRACT (verbatim)
// Rig validation kit: API contract (lane validate). Authoritative for web-react/src/lib/endpoints/validation.ts and
// for the JSON written by src/pitwall/validate (run.json, report.json). Every number that Pitwall does not know is
// `null` (shown as "-"). Times are unix seconds (server clock) unless named *_ms / *_s. Distances are metres along
// the lap. All endpoints live under /api/validation (see spec section 8).

export const VALIDATION_FORMAT = 1 as const;

export type ItemGroup = "dashboard" | "radio" | "coaching" | "games" | "drivers";
export type RunStatus = "active" | "finished" | "aborted";
export type ItemStatus = "pending" | "current" | "done" | "skipped";
export type DriverVerdict = "worked" | "didnt";
export type AutoVerdict = "pass" | "fail" | "inconclusive" | "no_evidence" | "not_live" | "unavailable" | "driver_only";
export type ItemResult = "pass" | "fail" | "needs_review" | "not_run" | "skipped";
export type EvidenceTier = "live" | "recorded" | "synthetic" | "loopback" | "unknown";
export type CheckStatus = "met" | "not_met" | "unknown";
export type InputPhaseId = "centre" | "left" | "right" | "pedals" | "reverse";

// ------------------------------------------------------------------------------------------------ catalogue
export interface CatalogStep {
  text: string;
  detail: string | null;
}

export interface Attestation {
  key: string;
  text: string;
}

export interface Informs {
  /** Where in docs/status.md the evidence belongs, in words. */
  status_md: string;
  /** Capability row label (game · platform (status)), or null. Text only: the kit never edits capabilities.py. */
  capability_row: string | null;
}

export interface CatalogItem {
  id: string;
  group: ItemGroup;
  title: string;
  summary: string;
  why: string;
  est_minutes: number;
  optional: boolean;
  per_driver: boolean;
  scope: "run" | "window";
  prerequisites: string[];
  steps: CatalogStep[];
  attestations: Attestation[];
  /** The Worked / Didn't work question. */
  prompt: string;
  /** What the radio says when this test starts (<= 25 words). */
  radio_brief: string;
  input_check: InputPhaseId[] | null;
  informs: Informs[];
  /** "How this is measured": the rule in words, heuristic thresholds marked. */
  rule_text: string;
  available: boolean;
  unavailable_reason: string | null;
}

export interface VoiceCommand {
  phrase: string;
  does: string;
}

export interface Catalog {
  format: typeof VALIDATION_FORMAT;
  groups: { id: ItemGroup; title: string }[];
  items: CatalogItem[];
  voice_commands: VoiceCommand[];
}

// ------------------------------------------------------------------------------------------------ run state
export interface Check {
  id: string;
  label: string;
  status: CheckStatus;
  value: string | null;
  target: string | null;
  heuristic: boolean;
}

export interface AutoState {
  verdict: AutoVerdict;
  reasons: string[];
  checks: Check[];
  metrics: Record<string, number | string | null>;
  tier: EvidenceTier | null;
  updated_unix: number;
}

export interface DriverMark {
  driver_id: number | null;
  verdict: DriverVerdict;
  notes: string;
  attestations: Record<string, boolean>;
  /** e.g. { first_look: "corner" | "delta" | "other" } for the glance test. */
  extra: Record<string, string>;
  at_unix: number;
  source: "screen" | "voice";
}

export interface ItemState {
  id: string;
  status: ItemStatus;
  windows: { start_unix: number; end_unix: number | null }[];
  /** Newest last. Per-driver items keep one mark per driver. */
  marks: DriverMark[];
  skip_reason: string | null;
  auto: AutoState;
  result: ItemResult;
}

export interface ServerInfo {
  pitwall_version: string;
  git_commit: string | null;
  os: string;
  voice_enabled: boolean;
  llm_enabled: boolean;
  stt: string | null;
  tts: string | null;
}

export interface RunContext {
  telemetry: "live" | "stale" | "no_data";
  tier: EvidenceTier;
  game: string | null;
  platform: string | null;
  track: string | null;
  session_id: string | null;
  packet_format: number | null;
  game_version: string | null;
  driver_id: number | null;
  radio_clients: number;
  cue_mode: string | null;
}

export interface ClientSummary {
  client_id: string;
  device: Device;
  standalone: boolean;
  secure_context: boolean;
  origin_kind: OriginKind;
  safari_version: string | null;
  last_seen_s: number;
  route: string;
  visibility: "visible" | "hidden";
  wake: { wanted: boolean; state: WakeState };
  radio: ClientRadio | null;
  audio_input_kind: AudioInputKind | null;
  gaps: number;
  hidden_transitions: number;
  reloads: number;
  wake_on_streak_s: number;
  fps: { median: number | null; p5: number | null; windows: number } | null;
}

export interface TimelineEvent {
  t_unix: number;
  kind: "telemetry" | "session" | "cue_mode" | "tts" | "client" | "restart" | "item" | "note";
  text: string;
}

export interface RunSummary {
  id: string;
  label: string | null;
  status: RunStatus;
  started_unix: number;
  ended_unix: number | null;
  current_item: string | null;
  counts: Record<ItemResult, number>;
  /** Tiers seen among the run's records. */
  tiers: EvidenceTier[];
}

export interface Run extends RunSummary {
  format: typeof VALIDATION_FORMAT;
  /** +1 on every change; the page skips re-rendering when unchanged. */
  version: number;
  selected_items: string[];
  radio_prompts: boolean;
  server: ServerInfo;
  items: ItemState[];
  context: RunContext;
  clients: ClientSummary[];
  /** Last 50 timeline events, newest first. */
  timeline: TimelineEvent[];
  notes: string | null;
  dropped_records: number;
  /** Only with ?detail=full. */
  evidence?: RunEvidence;
}

// ------------------------------------------------------------------------------------------------ evidence records
interface RecordBase {
  t_unix: number;
  tier: EvidenceTier;
  session_id: string | null;
  driver_id: number | null;
}

export interface CueRecord extends RecordBase {
  seq: number;
  msg_id: string | null;
  lap: number;
  corner: string;
  kind: "brake" | "marker" | "reminder";
  heads_up: boolean;
  focus: boolean;
  target_m: number;
  aim_m: number;
  d_m: number;
  speed_kph: number;
  ttg_s: number;
  path: "pcm" | "device";
  outcome: "sent" | "dropped";
  drop_reason: string | null;
  error_m: number | null;
  latency_ms: number | null;
  heard_m: number | null;
  /** heard_m - target_m: <= 0 means the word came at or before the reference braking point. */
  heard_vs_point_m: number | null;
  onset_m: number | null;
  /** onset_m - target_m: + means the driver braked after the reference point. */
  onset_vs_point_m: number | null;
  onset_vs_word_m: number | null;
  onset_vs_word_s: number | null;
  cls: "on_time" | "late" | "early" | "unmeasured" | "dropped";
  cue_mode: string | null;
}

export interface PttRecord extends RecordBase {
  id: string;
  source: "screen" | "wheel" | "typed" | null;
  client: string | null;
  transcript: string;
  stt_ms: number | null;
  audio_s: number | null;
  intent: string | null;
  answer: string | null;
  answer_source: "deterministic" | "llm" | "command" | "fallback" | "none";
  grounded: boolean | null;
  engineer_ms: number | null;
  tts_ms: number | null;
  to_first_audio_ms: number | null;
  to_playback_ms: number | null;
  heard_right: boolean | null;
}

export interface FrameBrief {
  lap: number | null;
  lap_distance_m: number | null;
  session_time_s: number | null;
}

export interface ProactiveRecord extends RecordBase {
  id: string;
  kind: string;
  text: string;
  lap: number | null;
  lap_id: number | null;
  /** analysis.coaching.Observation.id (a string key). */
  observation_id: string | null;
  held_s: number;
  state_at_send: { on_track: boolean; brake: number | null; steering: number | null; speed_kph: number | null; ttb_s: number | null };
  engine: string | null;
  started: boolean;
  start_frame: FrameBrief | null;
  end_frame: FrameBrief | null;
  duration_s: number | null;
  max_brake: number | null;
  max_abs_steering: number | null;
  gap_to_brake_s: number | null;
  cls: "clean" | "tight" | "overlap" | "off_track" | "unmeasured";
  cut: boolean;
}

export interface LapRecord extends RecordBase {
  lap_id: number;
  lap_number: number;
  lap_time_ms: number | null;
  clean: boolean;
  flags: string[];
  game: string | null;
  track_id: string | null;
  track_name: string | null;
  cue_mode: string | null;
  n_observations: number;
  /** D6 coach.picked[*].id of this lap (Observation.id strings). */
  picked_ids: string[];
}

export interface SwitchRecord extends RecordBase {
  from_driver_id: number | null;
  to_driver_id: number | null;
  session_before: string | null;
  session_after: string | null;
  laps_before_after_switch: number | null;
  laps_after: number | null;
  same_game_uid: boolean | null;
  cue_reason_after: string | null;
  ok: boolean | null;
}

export interface InputPhaseRecord {
  item_id: string;
  phase: InputPhaseId;
  start_unix: number;
  end_unix: number | null;
  samples: number;
  steer_mean: number | null;
  steer_min: number | null;
  steer_max: number | null;
  throttle_max: number | null;
  brake_max: number | null;
  gear_min: number | null;
  /** Assetto Corsa only: raw steer extremes the adapter has seen this session (unit undocumented). */
  steer_raw_range: [number, number] | null;
  rotation_deg: number | null;
}

export interface GameTransition {
  t_unix: number;
  selected_id: string | null;
  detected_id: string | null;
  mismatch: boolean;
}

export interface RunEvidence {
  cues: CueRecord[];
  ptt: PttRecord[];
  proactive: ProactiveRecord[];
  laps: LapRecord[];
  switches: SwitchRecord[];
  input_phases: InputPhaseRecord[];
  game: GameTransition[];
}

// ------------------------------------------------------------------------------------------------ device reports
export type Device = "ipad" | "iphone" | "android" | "browser";
export type OriginKind = "tailscale_https" | "https" | "localhost" | "lan_http" | "other";
export type WakeState = "off" | "pending" | "on" | "refused" | "unsupported";
export type AudioInputKind = "airpods" | "bluetooth" | "built_in" | "wired" | "unknown";

export interface ClientRadio {
  phase: string;
  conn: string;
  mic: string;
  mic_silent: boolean;
  wake: string;
  audio: string;
  audio_session: string;
  tts_mode: "device" | "server";
  rtt_ms: number | null;
}

/** POST /api/validation/client. Strings are length-limited by the server (route <= 64, version <= 16). */
export interface ClientReport {
  run_id: string;
  client_id: string;
  seq: number;
  reason: "start" | "interval" | "change" | "hidden" | "visible";
  t_client_ms: number;
  device: Device;
  standalone: boolean;
  secure_context: boolean;
  origin_kind: OriginKind;
  safari_version: string | null;
  viewport: { w: number; h: number; dpr: number; orientation: "landscape" | "portrait" };
  visibility: "visible" | "hidden";
  /** "drive/coach", "setup/validation"... */
  route: string;
  wake: { wanted: boolean; state: WakeState };
  radio: ClientRadio | null;
  audio_input_kind: AudioInputKind | null;
  /** Only while the endurance test is current and a Drive page is open: frames per second over the last 10 s. */
  fps_10s: number | null;
}

// ------------------------------------------------------------------------------------------------ requests
export interface StartRunRequest {
  items?: string[];
  label?: string | null;
  radio_prompts?: boolean;
}

export interface VerdictRequest {
  verdict: DriverVerdict | null;
  notes?: string;
  attestations?: Record<string, boolean>;
  extra?: Record<string, string>;
}

export interface InputCheckRequest {
  phase: InputPhaseId | "stop";
  rotation_deg?: number | null;
}

// ------------------------------------------------------------------------------------------------ report
export interface Candidate {
  item_id: string;
  status_md: string;
  capability_row: string | null;
  suggestion: string;
  met: boolean;
}

export interface ReportItem {
  id: string;
  title: string;
  group: ItemGroup;
  result: ItemResult;
  marks: DriverMark[];
  auto: AutoState;
  informs: Informs[];
  /** Compact tables for the report (column headers carry units). */
  evidence_tables: { title: string; columns: string[]; rows: (string | number | null)[][] }[];
}

export interface ValidationReport {
  format: typeof VALIDATION_FORMAT;
  generated_unix: number;
  in_progress: boolean;
  run: RunSummary & { server: ServerInfo; notes: string | null };
  tiers: Record<EvidenceTier, number>;
  items: ReportItem[];
  candidates: Candidate[];
  /** Fixed: "This report never changes capability statuses. Review it, then update src/pitwall/capabilities.py and
   * docs/status.md by hand." */
  disclaimer: string;
}

// ------------------------------------------------------------------------------------------------ endpoints
// GET  /api/validation/catalog                                   -> Catalog
// GET  /api/validation/active                                    -> { run: RunSummary | null }
// GET  /api/validation/runs                                      -> RunSummary[]
// POST /api/validation/runs                     StartRunRequest  -> Run (201; 409 when one is active)
// GET  /api/validation/runs/{id}?detail=compact|full             -> Run
// POST /api/validation/runs/{id}/current        { item_id }      -> Run
// POST /api/validation/runs/{id}/next           {}               -> Run
// POST /api/validation/runs/{id}/items/{item}/verdict  VerdictRequest      -> Run
// POST /api/validation/runs/{id}/items/{item}/skip     { reason?: string | null } -> Run
// POST /api/validation/runs/{id}/items/{item}/input-check  InputCheckRequest -> Run
// POST /api/validation/runs/{id}/records/ptt/{record_id}   { heard_right: boolean | null } -> Run
// POST /api/validation/runs/{id}/finish         { notes?: string | null } -> Run
// POST /api/validation/runs/{id}/abort          {}               -> Run
// GET  /api/validation/runs/{id}/report?redact_transcripts=      -> ValidationReport
// GET  /api/validation/runs/{id}/report.md?redact_transcripts=   -> text/markdown
// POST /api/validation/client                   ClientReport     -> 204 | 409 { detail: "no active run" }
// ---------------------------------------------------------------------------------------------- /CONTRACT

/** Every item id a run can hold is a catalogue id (strings, so a newer server's items still render). */
export type ItemId = string;

/** The run id format the server validates (`YYYYMMDD-HHMMSS-xxxx`): anything else is never sent in a path. */
export const RUN_ID_RE = /^\d{8}-\d{6}-[0-9a-f]{4}$/;

export function isRunId(s: string | null | undefined): s is string {
  return typeof s === "string" && RUN_ID_RE.test(s);
}

/** A non-2xx answer with FastAPI's detail in words (404 unknown run / item, 409 state conflict, 422 invalid body). */
export class ValidationError extends Error {
  readonly status: number;
  readonly detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ValidationError";
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

/** Words for an error from this module (or any other Error). */
export function validationErrorText(e: unknown): string {
  if (e instanceof ValidationError) {
    if (e.status === 404 && /not found/i.test(e.detail) && !/run|item|record/i.test(e.detail)) {
      return "This server has no validation kit yet: update Pitwall on the Mac.";
    }
    return e.detail;
  }
  if (e instanceof Error && e.message) return e.message;
  return "Something went wrong.";
}

async function failure(r: Response): Promise<ValidationError> {
  let body: unknown = null;
  try {
    body = await r.json();
  } catch {
    /* not json */
  }
  return new ValidationError(r.status, detailOf(body, `${r.status} ${r.statusText}`.trim()));
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await authFetch(path, init);
  if (!r.ok) throw await failure(r);
  return r.json() as Promise<T>;
}

function post<T>(path: string, body: unknown): Promise<T> {
  return req<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });
}

const BASE = "/api/validation";
const enc = encodeURIComponent;

/** Paths (exported for tests and links). Ids are encoded; run ids are validated by the server as well. */
export const validationPaths = {
  catalog: () => `${BASE}/catalog`,
  active: () => `${BASE}/active`,
  runs: () => `${BASE}/runs`,
  run: (id: string, detail: "compact" | "full" = "compact") => `${BASE}/runs/${enc(id)}${detail === "full" ? "?detail=full" : ""}`,
  current: (id: string) => `${BASE}/runs/${enc(id)}/current`,
  next: (id: string) => `${BASE}/runs/${enc(id)}/next`,
  verdict: (id: string, item: ItemId) => `${BASE}/runs/${enc(id)}/items/${enc(item)}/verdict`,
  skip: (id: string, item: ItemId) => `${BASE}/runs/${enc(id)}/items/${enc(item)}/skip`,
  inputCheck: (id: string, item: ItemId) => `${BASE}/runs/${enc(id)}/items/${enc(item)}/input-check`,
  ptt: (id: string, record: string) => `${BASE}/runs/${enc(id)}/records/ptt/${enc(record)}`,
  finish: (id: string) => `${BASE}/runs/${enc(id)}/finish`,
  abort: (id: string) => `${BASE}/runs/${enc(id)}/abort`,
  report: (id: string, redactTranscripts = false) => `${BASE}/runs/${enc(id)}/report${redactTranscripts ? "?redact_transcripts=true" : ""}`,
  reportMd: (id: string, redactTranscripts = false) =>
    `${BASE}/runs/${enc(id)}/report.md${redactTranscripts ? "?redact_transcripts=true" : ""}`,
  client: () => `${BASE}/client`,
};

/** The start body: optional fields only when set (the server fills in the defaults). */
export function startBody(items: ItemId[] | null, label: string | null, radioPrompts: boolean | null): StartRunRequest {
  const out: StartRunRequest = {};
  if (items) out.items = items;
  const l = label?.trim();
  if (l) out.label = l.slice(0, LABEL_MAX);
  if (radioPrompts !== null) out.radio_prompts = radioPrompts;
  return out;
}

/** Limits the server enforces (422 beyond them); the page enforces them first. */
export const NOTES_MAX = 2000;
export const LABEL_MAX = 80;

/** A verdict body: notes trimmed and cut to the limit; empty maps left out. */
export function verdictBody(
  verdict: DriverVerdict | null,
  notes: string,
  attestations: Record<string, boolean>,
  extra: Record<string, string>,
): VerdictRequest {
  const out: VerdictRequest = { verdict };
  if (verdict === null) return out;
  const n = notes.trim().slice(0, NOTES_MAX);
  if (n) out.notes = n;
  if (Object.keys(attestations).length) out.attestations = { ...attestations };
  if (Object.keys(extra).length) out.extra = { ...extra };
  return out;
}

export const validationApi = {
  catalog: () => req<Catalog>(validationPaths.catalog()),
  active: () => req<{ run: RunSummary | null }>(validationPaths.active()),
  runs: () => req<RunSummary[]>(validationPaths.runs()),
  run: (id: string, detail: "compact" | "full" = "compact") => req<Run>(validationPaths.run(id, detail)),
  start: (body: StartRunRequest) => post<Run>(validationPaths.runs(), body),
  setCurrent: (id: string, item: ItemId) => post<Run>(validationPaths.current(id), { item_id: item }),
  next: (id: string) => post<Run>(validationPaths.next(id), {}),
  verdict: (id: string, item: ItemId, body: VerdictRequest) => post<Run>(validationPaths.verdict(id, item), body),
  skip: (id: string, item: ItemId, reason: string | null) => post<Run>(validationPaths.skip(id, item), { reason }),
  inputCheck: (id: string, item: ItemId, body: InputCheckRequest) => post<Run>(validationPaths.inputCheck(id, item), body),
  markPtt: (id: string, record: string, heardRight: boolean | null) => post<Run>(validationPaths.ptt(id, record), { heard_right: heardRight }),
  finish: (id: string, notes: string | null) => post<Run>(validationPaths.finish(id), { notes: notes?.trim() ? notes.trim().slice(0, NOTES_MAX) : null }),
  abort: (id: string) => post<Run>(validationPaths.abort(id), {}),
  /** The report; with `redactTranscripts` the driver's transcripts are replaced (Download JSON honours the switch). */
  report: (id: string, redactTranscripts = false) => req<ValidationReport>(validationPaths.report(id, redactTranscripts)),
  /** The Markdown report as text (fetched with the tab's credentials). */
  reportMarkdown: async (id: string, redactTranscripts = false): Promise<string> => {
    const r = await authFetch(validationPaths.reportMd(id, redactTranscripts));
    if (!r.ok) throw await failure(r);
    return r.text();
  },
};

/** Outcome of a device report: "ok" (204), "no_run" (409: the reporter goes idle), "error" (anything else). */
export type ClientPostResult = "ok" | "no_run" | "error";

function resultOf(status: number): ClientPostResult {
  if (status >= 200 && status < 300) return "ok";
  return status === 409 ? "no_run" : "error";
}

/** POST /client. `hidden` reports go out as a beacon (or a keepalive fetch when the tab carries a token: a beacon
 * cannot send the token header), so they still leave while the page is being hidden. */
export async function postClientReport(report: ClientReport, hidden = false): Promise<ClientPostResult> {
  const path = validationPaths.client();
  const body = JSON.stringify(report);
  if (hidden) {
    try {
      const nav = (globalThis as { navigator?: Navigator }).navigator;
      if (!accessToken() && nav && typeof nav.sendBeacon === "function") {
        return nav.sendBeacon(path, new Blob([body], { type: "application/json" })) ? "ok" : "error";
      }
    } catch {
      /* fall through to fetch */
    }
  }
  try {
    const r = await authFetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body, keepalive: hidden });
    return resultOf(r.status);
  } catch {
    return "error";
  }
}

/** Request-cache keys (src/lib/cache.ts). Mutations answer with the new Run and invalidate RUNS and ACTIVE. */
export const VALIDATION_KEYS = {
  catalog: "validation:catalog",
  active: "validation:active",
  runs: "validation:runs",
  run: (id: string) => `validation:run:${id}`,
  full: (id: string) => `validation:full:${id}`,
  report: (id: string) => `validation:report:${id}`,
} as const;

/** The page polls the active run this often while visible (like Connect). */
export const VALIDATION_POLL_MS = 2000;
