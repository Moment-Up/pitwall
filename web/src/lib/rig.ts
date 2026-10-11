// Rig setup client: types mirroring /api/rig (src/pitwall/api/routes_rig.py) and small formatting helpers.
//
// Every recommended value carries provenance. The UI must keep the distinction visible: evidence V/A/U are
// published values (verified, approximate, unverified), D is a value pitwall derived or picked (a start value inside
// a published range, the Comfort 5/8 scaling) and H marks a pitwall heuristic threshold in the rig check. Self-contained (own fetch helper) so it does not depend
// on other client modules.

export type Evidence = "V" | "A" | "U" | "D" | "H";
export type StyleId = "official_default" | "balanced" | "competitive" | "realism" | "comfort";
export type GameId = "f1_25" | "gt7";
export type PedalsId = "csl" | "csl_load_cell";
export type SkillLevel = "beginner" | "intermediate" | "advanced";
export type MetricStatus = "pass" | "warn" | "fail" | "info" | "unknown";
export type UpgradeChange = "boost_kit_180" | "load_cell_kit" | "firmware" | "rim" | "other";
export type LapPolicy = "clean" | "usable";

export interface StyleInfo {
  id: StyleId;
  label: string;
  description: string;
  sourced: boolean;
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

export interface PresetSummary {
  id: string;
  code: string;
  name: string;
  game: GameId;
  platform: string; // where pitwall offers it
  applies_to_platforms: string[];
  source_platform: string; // where the author configured it
  ps5_reachable: boolean;
  torque_nm: number | null; // the source's own torque
  applies_to_torque_nm: number[];
  torque_basis: string;
  pedals: string | null;
  pedals_basis: string;
  preference: StyleId;
  preference_inferred: boolean;
  source_words: string | null;
  published: string;
  game_version: string;
  firmware_era: string;
  status: "current" | "stale" | "superseded" | "not_for_ps5";
  stale: boolean;
  stale_reasons: string[];
  superseded_by: string | null;
  confidence: "high" | "medium" | "low";
  notes: string;
  sources: SourceInfo[];
  wheel_settings: Record<string, PublishedValue>;
  ingame_settings: Record<string, PublishedValue>;
  pedal_settings: { pedal_model: string; transferable_to_pedals: string[]; values: Record<string, PublishedValue> } | null;
}

export interface PedalReport {
  id: string;
  owner: string;
  pedals: string;
  stock: boolean;
  modification: string | null;
  values: Record<string, PublishedValue>;
  game: string | null;
  torque_nm: number | null;
  latest_for_owner: boolean;
  preference: string | null;
  source_words: string | null;
  published: string;
  sources: SourceInfo[];
  notes: string;
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

export interface RigCatalog {
  schema_revision: number;
  research_date: string;
  evidence_labels: Record<Evidence, string>;
  firmware: Record<string, string>;
  platforms: { id: string; name: string; base_mode: string; tuning_interface: string }[];
  styles: StyleInfo[];
  games: { id: GameId; name: string; platforms: string[]; versions: { id: string; label: string; date: string }[] }[];
  hardware: {
    wheel_bases: {
      id: string;
      name: string;
      torque_variants: { torque_nm: number; label: string }[];
      firmware_eras: { id: string; label: string; app: string; base_fw: string; from: string | null }[];
    }[];
    pedals: { id: PedalsId; model: string; name: string; brake_sensor: string }[];
    rims: { id: string; name: string; note: string; has_items: string[]; unknown_items: string[] }[];
  };
  timeline: { date: string; event: string; effect: string }[];
  brf_owner_stats: {
    population: string;
    n: number;
    values: number[];
    median: number;
    min: number;
    max: number;
    evidence: Evidence;
    note: string;
  };
  rules: ResearchRule[];
  rig_check_metrics: {
    metric: string;
    label: string;
    unit: string;
    good_range: string;
    threshold_evidence: Evidence;
    games: string[];
    pedals: string[];
  }[];
  skill_levels: SkillLevel[];
  upgrade_changes: UpgradeChange[];
  supported: { game: GameId; platform: string }[];
  presets: PresetSummary[];
  pedal_reports: PedalReport[];
  known_issues: KnownIssue[];
  open_questions: OpenQuestion[];
}

export interface UpgradeEvent {
  date: string;
  change: UpgradeChange;
  fitted: boolean;
  note: string | null;
  recorded_unix: number;
}

export interface DriverRigPrefs {
  style: StyleId;
  strength_scale: number | null;
}

export interface RigProfile {
  platform: string;
  wheel_base: string;
  torque_nm: number;
  pedals: PedalsId;
  rim: string;
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
  strength_scale_source: "driver" | "skill_default" | "none";
}

export interface PresetRef {
  id: string;
  code: string;
  value: string | null;
  evidence: Evidence | null;
  note: string | null;
  applies_at_torque: boolean; // the preset's values are meant for the rig's torque
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

// sourced: a preset publishes this value; range_pick: pitwall's start value inside a published range (D, the range
// keeps its own label); derived: pitwall derivation; cited: a manual / single expert; instruction: a check to make,
// not a number (FFS after the Boost Kit); locked: pushed by the game (A SET)
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
  transfer: string | null; // only presets for the other torque publish this value
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

export interface Section {
  id: "base" | "wheel" | "ingame" | "pedals";
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
  hardware: { platform: string; wheel_base: string; torque_nm: number; pedals: PedalsId; rim: string };
  diffs: RowDiff[];
  steps: Step[];
  peak_before_nm: number; // the driver's peak wheel torque now (torque x FF / 100)
  peak_after_nm: number; // and with the upgrade fitted
  notes: string[]; // what the change means for this driver (e.g. a lighter wheel getting heavier)
}

export interface Recommendation {
  game: GameId;
  game_name: string;
  platform: string;
  hardware: { platform: string; wheel_base: string; torque_nm: number; pedals: PedalsId; rim: string };
  requested_style: StyleId;
  style: StyleId;
  style_label: string;
  sourced: boolean;
  skill_level: SkillLevel;
  strength_scale: number;
  strength_scale_source: "driver" | "skill_default" | "none";
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
  rotation_deg: number; // what steering +-1 spans (GT7: nominal 900 deg)
  steering_lock_deg: number | null; // the car's lock-to-lock rotation, when known
  pedals: PedalsId | null; // pedals fitted when the session was driven
  counts: Record<MetricStatus, number>;
  metrics: MetricResult[];
  notes: string[];
  generated_unix: number;
  baseline: RigCheck | null;
  comparison: MetricDelta[] | null;
  upgrade: UpgradeEvent | null;
  // why there is no baseline although an upgrade is recorded (e.g. nothing driven since the upgrade yet)
  baseline_note: string | null;
}

export interface DriverOption {
  id: number;
  name: string;
  colour?: string;
  skill_level?: SkillLevel;
}

// ---------------------------------------------------------------------------------------------- transport
async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { credentials: "same-origin", ...init });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const body = await r.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* not json */
    }
    throw new Error(`${r.status}: ${detail}`);
  }
  return r.json() as Promise<T>;
}

const send = <T>(method: "POST" | "PUT", path: string, body: unknown) =>
  req<T>(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
}

export const rig = {
  catalog: (filters: { game?: GameId; platform?: string; torque_nm?: number; pedals?: PedalsId } = {}) =>
    req<RigCatalog>(`/api/rig/catalog${qs(filters)}`),
  profile: () => req<RigProfile>("/api/rig/profile"),
  updateProfile: (body: Partial<Pick<RigProfile, "platform" | "wheel_base" | "torque_nm" | "pedals" | "rim">>) =>
    send<RigProfile>("PUT", "/api/rig/profile", body),
  upgrade: (change: UpgradeChange, fitted = true, note: string | null = null) =>
    send<RigProfile>("POST", "/api/rig/upgrades", { change, fitted, note }),
  prefs: (driverId: number) => req<DriverPrefsResponse>(`/api/rig/drivers/${driverId}/prefs`),
  // Partial update: send only what changed, so a style tap never rewrites the force scale (and vice versa).
  setPrefs: (driverId: number, prefs: Partial<DriverRigPrefs>) =>
    send<DriverPrefsResponse>("PUT", `/api/rig/drivers/${driverId}/prefs`, prefs),
  recommendations: (p: { game: GameId; driverId?: number | null; style?: StyleId | null; platform?: string | null }) =>
    req<Recommendation>(
      `/api/rig/recommendations${qs({ game: p.game, driver_id: p.driverId, style: p.style, platform: p.platform })}`,
    ),
  // Without a session, the latest real session of ``game`` (or of any game the check covers).
  check: (p: {
    sessionId?: string | null;
    driverId?: number | null;
    game?: GameId | null;
    laps?: LapPolicy;
    baseline?: "none" | "upgrade";
  }) =>
    req<RigCheck>(
      `/api/rig/check${qs({ session_id: p.sessionId, driver_id: p.driverId, game: p.game, laps: p.laps, baseline: p.baseline })}`,
    ),
  // Plain REST read of the driver list and who is in the seat (used only when the parent does not pass drivers).
  drivers: async (): Promise<{ activeId: number | null; drivers: DriverOption[] }> => {
    const r = await req<{
      active_id: number | null;
      drivers: { id: number; name: string; preferences?: { colour?: string; skill_level?: SkillLevel } }[];
    }>("/api/drivers");
    return {
      activeId: r.active_id ?? null,
      drivers: r.drivers.map((d) => ({
        id: d.id,
        name: d.name,
        colour: d.preferences?.colour,
        skill_level: d.preferences?.skill_level,
      })),
    };
  },
};

// ---------------------------------------------------------------------------------------------- helpers
export const EVIDENCE_SHORT: Record<Evidence, string> = {
  V: "Verified",
  A: "Approx.",
  U: "Unverified",
  D: "Derived",
  H: "Heuristic",
};

export function rowCopyText(r: SettingRow): string {
  return `${r.key}: ${r.value}`;
}

function rowMarks(r: SettingRow): string {
  const marks = [];
  if (r.provenance.kind === "range_pick") marks.push(`pitwall pick in ${r.range}`);
  else if (r.provenance.derived) marks.push("pitwall derived");
  if (r.provenance.transfer) marks.push("made for the other torque");
  if (r.locked) marks.push("A SET");
  return marks.length ? `  [${marks.join("; ")}]` : "";
}

export function sectionCopyText(s: Section, heading?: string): string {
  const lines = heading ? [heading] : [];
  for (const r of s.rows) lines.push(`${r.key} (${r.label}): ${r.value}${rowMarks(r)}`);
  for (const st of s.steps) lines.push(`- ${st.text}`);
  return lines.join("\n");
}

export function formatMetric(m: { value: number | null; unit: string }): string {
  if (m.value === null) return "—";
  const v = m.value;
  switch (m.unit) {
    case "%":
      return `${v < 10 ? v.toFixed(v < 1 ? 2 : 1) : v.toFixed(0)}%`;
    case "s":
      return `${v.toFixed(2)} s`;
    case "/s":
      return `${v.toFixed(1)}/s`;
    case "/min":
      return `${v.toFixed(0)}/min`;
    case "per lap":
      return `${v.toFixed(1)} / lap`;
    case "count":
    case "events":
      return v.toFixed(0);
    case "points":
      return `${v > 0 ? "+" : ""}${v.toFixed(1)} pts`;
    default:
      return v.toFixed(2);
  }
}

export function platformLabel(platform: string): string {
  return (
    (
      {
        ps5: "PS5",
        ps4: "PS4",
        pc: "PC",
        pc_ps5: "PC/PS5",
        xbox: "Xbox",
        playstation: "PlayStation",
        not_split: "every platform",
        not_stated: "platform not stated",
      } as Record<string, string>
    )[platform] ?? platform
  );
}

export function upgradeLabel(change: UpgradeChange): string {
  return (
    {
      boost_kit_180: "Boost Kit 180 (8 Nm)",
      load_cell_kit: "CSL Load Cell Kit",
      firmware: "Firmware update",
      rim: "Rim change",
      other: "Other change",
    } satisfies Record<UpgradeChange, string>
  )[change];
}
