// Rig endpoints (lane X, spec 7.2 and 12.4): typed client for /api/rig/* (src/pitwall/api/routes_rig.py and the
// to_dict shapes in src/pitwall/rig/{catalog,recommend,rig_check}.py). Types ported from the Svelte reference
// web/src/lib/rig.ts; the pure helpers live in src/lib/setup/rig.ts and the walkthrough in src/lib/setup/walkthrough.ts.
//
// Every recommended value carries provenance and the UI keeps it visible: evidence V / A / U are published values
// (verified, approximate, unverified), D is a value Pitwall derived or picked (a start value inside a published range,
// the Comfort scaling) and H marks a Pitwall heuristic threshold in the rig check. Nothing here calls an LLM.
//
// Writes: PUT /profile (platform, wheel base, rim; the Boost Kit and the Load Cell Kit go through POST /upgrades so
// the rig check can compare before and after), PUT /drivers/{id}/prefs (partial: a style tap never sends the force
// scale and the other way round), POST /upgrades (409 when the change would not change the rig). Errors: 422 (an
// invalid value or a combination the catalogue does not cover, e.g. GT7 on PC), 404 (unknown driver or session, or no
// session with laps yet for the rig check).

import { authFetch } from "../auth";

export type Evidence = "V" | "A" | "U" | "D" | "H";
export type StyleId = "official_default" | "balanced" | "competitive" | "realism" | "comfort";
export type GameId = "f1_25" | "gt7";
export type PedalsId = "csl" | "csl_load_cell";
export type SkillLevel = "beginner" | "intermediate" | "advanced";
export type MetricStatus = "pass" | "warn" | "fail" | "info" | "unknown";
export type UpgradeChange = "boost_kit_180" | "load_cell_kit" | "firmware" | "rim" | "other";
export type LapPolicy = "clean" | "usable";
export type ScaleSource = "driver" | "skill_default" | "none";

export const GAMES: readonly GameId[] = ["f1_25", "gt7"];
export const STYLE_IDS: readonly StyleId[] = ["official_default", "balanced", "competitive", "realism", "comfort"];
export const UPGRADE_CHANGES: readonly UpgradeChange[] = ["boost_kit_180", "load_cell_kit", "firmware", "rim", "other"];
/** The force scale the API accepts (routes_rig.PrefsUpdate: 0.2..1.0). */
export const STRENGTH_MIN = 0.2;
export const STRENGTH_MAX = 1;

// ---------------------------------------------------------------------------------------------- catalogue
export interface StyleInfo {
  id: StyleId;
  label: string;
  description: string;
  sourced: boolean;
}

export interface SourceInfo {
  url: string;
  author: string;
  published: string;
  verified: boolean;
  values_evidence: string | null;
  game_version: string | null;
  software: string | null;
  source_hardware: string | null;
  note: string | null;
}

export interface PublishedValue {
  value: string | number | null;
  min: number | null;
  max: number | null;
  evidence: Evidence;
  as_published: string | null;
  note: string | null;
  display: string | null;
}

export interface ResearchRule {
  id: string;
  game: string;
  applies_to_preferences: string[];
  rule: string;
  evidence: Evidence;
  basis_presets: string[];
  factor: number | null;
}

export interface AppliesTo {
  games: string[];
  pedals: string[];
  torque_nm: number[];
}

export interface KnownIssue {
  id: string;
  title: string;
  detail: string;
  applies_to: AppliesTo;
  evidence: Evidence;
  source: string;
}

export interface OpenQuestion {
  id: number;
  question: string;
  verify: string;
  applies_to: AppliesTo;
}

export interface WheelBaseInfo {
  id: string;
  name: string;
  torque_variants: { torque_nm: number; label: string }[];
  firmware_eras: { id: string; label: string; app: string; base_fw: string; from: string | null }[];
}

export interface PedalInfo {
  id: PedalsId;
  model: string;
  name: string;
  brake_sensor: string;
}

export interface RimInfo {
  id: string;
  name: string;
  note: string;
  has_items: string[];
  unknown_items: string[];
}

export interface RigCatalog {
  schema_revision: number;
  research_date: string;
  evidence_labels: Partial<Record<Evidence, string>>;
  firmware: Record<string, string>;
  platforms: { id: string; name: string; base_mode: string; tuning_interface: string }[];
  styles: StyleInfo[];
  games: { id: GameId; name: string; platforms: string[]; versions: { id: string; label: string; date: string }[] }[];
  hardware: { wheel_bases: WheelBaseInfo[]; pedals: PedalInfo[]; rims: RimInfo[] };
  skill_levels: SkillLevel[];
  upgrade_changes: UpgradeChange[];
  supported: { game: GameId; platform: string }[];
  known_issues: KnownIssue[];
  open_questions: OpenQuestion[];
  rules: ResearchRule[];
}

// ---------------------------------------------------------------------------------------------- profile and prefs
export interface UpgradeEvent {
  date: string;
  change: UpgradeChange;
  fitted: boolean;
  note: string | null;
  recorded_unix: number | null;
}

export interface DriverRigPrefs {
  style: StyleId;
  strength_scale: number | null;
}

export interface Hardware {
  platform: string;
  wheel_base: string;
  torque_nm: number;
  pedals: PedalsId;
  rim: string;
}

export interface RigProfile extends Hardware {
  upgrades: UpgradeEvent[];
  drivers: Record<string, DriverRigPrefs>;
  labels: { platform: string; wheel_base: string; torque: string; pedals: string; rim: string };
  boost_kit_fitted: boolean;
  load_cell_fitted: boolean;
  last_hardware_upgrade: UpgradeEvent | null;
}

export interface DriverPrefsResponse {
  driver_id: number;
  prefs: DriverRigPrefs;
  skill_level: SkillLevel;
  effective_strength_scale: number;
  strength_scale_source: ScaleSource;
}

// ---------------------------------------------------------------------------------------------- recommendation
export interface PresetRef {
  id: string;
  code: string;
  value: string | null;
  evidence: Evidence | null;
  note: string | null;
  /** The preset's values are meant for the rig's torque. */
  applies_at_torque: boolean;
}

export interface ReportRef {
  id: string;
  owner: string;
  value: string | null;
  stock: boolean;
  latest_for_owner: boolean;
  published: string;
  url: string;
}

export interface Citation {
  label: string;
  url: string | null;
  evidence: Evidence | null;
}

export interface PresetInfo {
  id: string;
  code: string;
  name: string;
  preference: StyleId;
  preference_inferred: boolean;
  torque_nm: number | null;
  applies_to_torque_nm: number[];
  source_platform: string;
  pedals: string | null;
  confidence: string;
  published: string;
  game_version: string;
  status: string;
  stale: boolean;
  url: string;
  author: string;
  verified: boolean;
}

export interface Consensus {
  n: number | null;
  median: string | null;
  range: string | null;
  status: "consensus" | "strong" | "split" | "moot";
  note: string;
}

/** sourced: a preset publishes this value; range_pick: Pitwall's start value inside a published range (D, the range
 * keeps its own label); derived: a Pitwall derivation; cited: a manual or a single expert; instruction: a check to
 * make, not a number (FFS after the Boost Kit); locked: pushed by the game (A SET). */
export type ProvenanceKind = "sourced" | "range_pick" | "derived" | "cited" | "instruction" | "locked";

export interface Provenance {
  kind: ProvenanceKind;
  evidence: Evidence;
  derived: boolean;
  basis: PresetRef[];
  others: PresetRef[];
  consensus: Consensus | null;
  source: string | null;
  reports: ReportRef[];
  citations: Citation[];
  derivation: string | null;
  original: { value: string; evidence: Evidence } | null;
  range_basis: "published" | "across_sources" | "derived" | null;
  range_evidence: Evidence | null;
  /** Only presets for the other torque publish this value. */
  transfer: string | null;
  stale: boolean;
}

export interface SettingRow {
  key: string;
  label: string;
  value: string;
  range: string | null;
  menu_range: string | null;
  factory_default: string | null;
  changed_from_default: boolean;
  needs_advanced: boolean;
  locked: boolean;
  instruction: boolean;
  notes: string[];
  provenance: Provenance;
}

export interface Step {
  id: string;
  text: string;
  evidence: Evidence;
  derived: boolean;
  source: string | null;
  detail: string | null;
}

export type SectionId = "base" | "wheel" | "ingame" | "pedals";

export interface Section {
  id: SectionId;
  title: string;
  steps: Step[];
  rows: SettingRow[];
}

export interface RowDiff {
  section: string;
  key: string;
  label: string;
  before: string | null;
  after: string | null;
  derived: boolean;
  evidence: Evidence | null;
}

export interface UpgradePreview {
  change: UpgradeChange;
  label: string;
  hardware: Hardware;
  diffs: RowDiff[];
  steps: Step[];
  /** The driver's peak wheel torque now (torque x FF / 100). */
  peak_before_nm: number;
  /** And with the upgrade fitted. */
  peak_after_nm: number;
  /** What the change means for this driver (e.g. a lighter wheel getting heavier). */
  notes: string[];
}

export interface Recommendation {
  game: GameId;
  game_name: string;
  platform: string;
  hardware: Hardware;
  requested_style: StyleId;
  style: StyleId;
  style_label: string;
  sourced: boolean;
  skill_level: SkillLevel;
  strength_scale: number;
  strength_scale_source: ScaleSource;
  peak_torque_nm: number;
  confidence: string;
  pedal_confidence: string;
  summary: string;
  a_set: boolean;
  stale: boolean;
  basis: string[];
  presets: Record<string, PresetInfo>;
  sections: Section[];
  safety: Step[];
  notes: string[];
  warnings: string[];
  rules: ResearchRule[];
  known_issues: KnownIssue[];
  verify: OpenQuestion[];
  driver: { id: number; name: string | null; skill_level: SkillLevel; skill_source: string } | null;
  upcoming: UpgradePreview[];
}

// ---------------------------------------------------------------------------------------------- rig check
export interface MetricResult {
  metric: string;
  label: string;
  value: number | null;
  unit: string;
  status: MetricStatus;
  heuristic: boolean;
  good_range: string;
  target: string;
  detail: string;
  action: string | null;
  reason_unknown: string | null;
  samples: number;
  per_lap: Record<string, number | null>;
  reference: string | null;
  threshold_note: string | null;
  sources: string[];
}

export interface MetricDelta {
  metric: string;
  label: string;
  unit: string;
  before: number | null;
  after: number | null;
  delta: number | null;
  before_status: MetricStatus;
  after_status: MetricStatus;
}

export interface RigCheck {
  session_id: string | null;
  game: string | null;
  track: string | null;
  session_type: string | null;
  synthetic: boolean;
  started_unix: number | null;
  lap_policy: string;
  laps: number[];
  lap_ids: number[];
  sample_rate_hz: number | null;
  /** What steering +-1 spans (GT7: a nominal 900 deg). */
  rotation_deg: number;
  /** The car's lock-to-lock rotation, when known. */
  steering_lock_deg: number | null;
  /** The pedals fitted when the session was driven. */
  pedals: PedalsId | null;
  counts: Partial<Record<MetricStatus, number>>;
  metrics: MetricResult[];
  notes: string[];
  generated_unix: number;
  baseline: RigCheck | null;
  comparison: MetricDelta[] | null;
  upgrade: UpgradeEvent | null;
  /** Why there is no baseline although an upgrade is recorded (e.g. nothing driven since the upgrade yet). */
  baseline_note: string | null;
}

// ---------------------------------------------------------------------------------------------- transport
/** A non-2xx answer; ``detail`` is FastAPI's detail as sent (a string or pydantic's [{loc, msg}] list). */
export class RigError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown) {
    super(`${status}: ${rigDetailText(detail, status)}`);
    this.name = "RigError";
    this.status = status;
    this.detail = detail;
  }
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** Readable text for a FastAPI error detail: a string or pydantic's [{loc, msg}] list. */
export function rigDetailText(detail: unknown, status?: number): string {
  const fallback = status ? `request failed (HTTP ${status})` : "request failed";
  if (typeof detail === "string") return detail.trim() ? detail : fallback;
  if (Array.isArray(detail)) {
    const msgs = detail.map((d) => {
      if (!isRecord(d)) return String(d);
      const loc = Array.isArray(d.loc) ? d.loc.filter((x) => x !== "body" && x !== "query").join(".") : "";
      return `${loc ? `${loc}: ` : ""}${typeof d.msg === "string" ? d.msg : JSON.stringify(d)}`;
    });
    return msgs.join("; ") || fallback;
  }
  return detail === undefined || detail === null ? fallback : JSON.stringify(detail);
}

/** The message to show inline for any error (without the "422: " prefix for API errors). */
export function rigErrorText(e: unknown): string {
  if (e instanceof RigError) return rigDetailText(e.detail, e.status);
  return e instanceof Error ? e.message : String(e);
}

/** 404 from GET /check: no session with laps yet (or the named one does not exist). */
export function isNoSession(e: unknown): boolean {
  return e instanceof RigError && e.status === 404;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await authFetch(path, init);
  if (!r.ok) {
    let detail: unknown = r.statusText;
    try {
      const body: unknown = await r.json();
      detail = isRecord(body) && "detail" in body ? body.detail : body;
    } catch {
      /* not json */
    }
    throw new RigError(r.status, detail);
  }
  return r.json() as Promise<T>;
}

const send = <T>(method: "POST" | "PUT", path: string, body: unknown) =>
  req<T>(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

/** "?a=1&b=x" from the set values (null, undefined and "" left out); "" when nothing is set. */
export function rigQs(params: Record<string, string | number | boolean | null | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
}

export interface RecommendationQuery {
  game: GameId;
  driver_id?: number | null;
  /** Omitted: the driver's saved style (Official without a driver). */
  style?: StyleId | null;
  platform?: string | null;
}

export interface CheckQuery {
  session_id?: string | null;
  driver_id?: number | null;
  /** Omitted: the latest session of any game the check covers. */
  game?: GameId | null;
  laps?: LapPolicy;
  baseline?: "none" | "upgrade";
}

export type ProfileUpdate = Partial<Pick<RigProfile, "platform" | "wheel_base" | "torque_nm" | "pedals" | "rim">>;

export interface UpgradeBody {
  change: UpgradeChange;
  fitted?: boolean;
  /** YYYY-MM-DD; the server uses today when omitted. */
  date?: string | null;
  note?: string | null;
}

export function recommendationPath(q: RecommendationQuery): string {
  return `/api/rig/recommendations${rigQs({ game: q.game, driver_id: q.driver_id, style: q.style, platform: q.platform })}`;
}

export function checkPath(q: CheckQuery): string {
  return `/api/rig/check${rigQs({
    session_id: q.session_id,
    driver_id: q.driver_id,
    game: q.game,
    laps: q.laps,
    baseline: q.baseline,
  })}`;
}

/** The upgrade body as sent: empty note and date left out (the server records today). */
export function upgradeBody(b: UpgradeBody): { change: UpgradeChange; fitted: boolean; date?: string; note?: string } {
  const out: { change: UpgradeChange; fitted: boolean; date?: string; note?: string } = { change: b.change, fitted: b.fitted ?? true };
  if (b.date && /^\d{4}-\d{2}-\d{2}$/.test(b.date)) out.date = b.date;
  const note = b.note?.trim();
  if (note) out.note = note.slice(0, 200);
  return out;
}

export const rigApi = {
  catalog: () => req<RigCatalog>("/api/rig/catalog"),
  profile: () => req<RigProfile>("/api/rig/profile"),
  /** Platform, wheel base and rim. Torque and pedals change through ``upgrade`` (history for the rig check). */
  updateProfile: (body: ProfileUpdate) => send<RigProfile>("PUT", "/api/rig/profile", body),
  upgrade: (body: UpgradeBody) => send<RigProfile>("POST", "/api/rig/upgrades", upgradeBody(body)),
  prefs: (driverId: number) => req<DriverPrefsResponse>(`/api/rig/drivers/${encodeURIComponent(String(driverId))}/prefs`),
  /** Partial: send only what changed, so a style tap never rewrites the force scale (and the other way round).
   * ``strength_scale: null`` returns to the skill default. */
  setPrefs: (driverId: number, prefs: Partial<DriverRigPrefs>) =>
    send<DriverPrefsResponse>("PUT", `/api/rig/drivers/${encodeURIComponent(String(driverId))}/prefs`, prefs),
  recommendations: (q: RecommendationQuery) => req<Recommendation>(recommendationPath(q)),
  check: (q: CheckQuery) => req<RigCheck>(checkPath(q)),
};

/** Request-cache keys (src/lib/cache.ts). Every key starts with "rig:", so a driver switch (useCacheInvalidation)
 * and any rig write refetch them all. */
export const RIG_KEYS = {
  all: "rig:",
  catalog: "rig:catalog",
  profile: "rig:profile",
  prefs: (driverId: number) => `rig:prefs:${driverId}`,
  recommendations: (q: RecommendationQuery) =>
    `rig:recommendations:${q.game}:${q.driver_id ?? "none"}:${q.style ?? "saved"}:${q.platform ?? "saved"}`,
  check: (q: CheckQuery) =>
    `rig:check:${q.session_id ?? "latest"}:${q.driver_id ?? "any"}:${q.game ?? "any"}:${q.laps ?? "clean"}:${q.baseline ?? "none"}`,
} as const;
