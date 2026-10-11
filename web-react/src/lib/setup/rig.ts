// Pure helpers for Setup › Rig (spec 7.2; lane X): labels, evidence chips, copy text, metric formatting and the rig
// page's query (`#/setup/rig/<view>?driver=&game=`). Behaviour reference: web/src/lib/rig.ts and
// web/src/views/SetupView.svelte. Unknown is "-" (never an em dash), negatives use U+2212.
//
// Honesty rules kept here so every view applies them the same way:
// - an evidence chip is never more certain than the value's own evidence (V verified, A approximate, U unverified,
//   D derived by Pitwall, H a Pitwall heuristic threshold);
// - a value Pitwall picked inside a published range or derived says so;
// - rig check statuses use status colours (pass green, warn amber, fail red), never timing colours.

import { UNKNOWN, withMinus } from "../format";
import type {
  DriverPrefsResponse,
  Evidence,
  GameId,
  Hardware,
  MetricResult,
  MetricStatus,
  Recommendation,
  RigCatalog,
  RigCheck,
  RigProfile,
  Section,
  SettingRow,
  StyleId,
  StyleInfo,
  UpgradeChange,
  UpgradeEvent,
} from "../endpoints/rig";
import { GAMES } from "../endpoints/rig";

export type ChipTone = "default" | "accent" | "success" | "warning" | "danger";

export interface ChipSpec {
  label: string;
  tone: ChipTone;
  /** Longer explanation for screen readers and the provenance sheet. */
  title?: string;
}

export const GAME_LABEL: Record<GameId, string> = { f1_25: "F1 25", gt7: "GT7" };

/** Short evidence words (spec 7.2: `Verified`, `Unverified`, `Derived by Pitwall`). */
export const EVIDENCE_TEXT: Record<Evidence, string> = {
  V: "Verified",
  A: "Approximate",
  U: "Unverified",
  D: "Derived by Pitwall",
  H: "Pitwall heuristic",
};

/** Unverified and approximate values are amber; nothing published is ever shown green (green is the pass status). */
export function evidenceTone(e: Evidence | null | undefined): ChipTone {
  return e === "U" ? "warning" : "default";
}

export function evidenceChip(e: Evidence | null | undefined, labels?: Partial<Record<Evidence, string>>): ChipSpec | null {
  if (!e) return null;
  return { label: EVIDENCE_TEXT[e], tone: evidenceTone(e), title: labels?.[e] };
}

/** How many published presets carry this row (the basis and the others); 0 for derived or cited values. */
export function sourceCount(row: SettingRow): number {
  const n = row.provenance.consensus?.n;
  if (typeof n === "number" && n > 0) return n;
  return row.provenance.basis.length + row.provenance.others.length;
}

/** The evidence chip of a recommended row: a Pitwall pick or derivation says so; else the evidence (+ how many
 * sources). Never more certain than ``provenance.evidence``. */
export function rowEvidenceChip(row: SettingRow, labels?: Partial<Record<Evidence, string>>): ChipSpec {
  const p = row.provenance;
  if (p.kind === "range_pick") return { label: "Pitwall pick in range", tone: "default", title: labels?.D };
  if (p.derived || p.evidence === "D") return { label: "Derived by Pitwall", tone: "default", title: labels?.D };
  const base = EVIDENCE_TEXT[p.evidence];
  const n = sourceCount(row);
  return { label: n > 1 ? `${base} · ${n} sources` : base, tone: evidenceTone(p.evidence), title: labels?.[p.evidence] };
}

/** The chips under a walkthrough value, in the spec's order (7.2): range, factory default, Changed, Advanced menu,
 * Set by the game, evidence, then warnings (made for the other torque, stale, sources disagree). */
export function rowChips(row: SettingRow, labels?: Partial<Record<Evidence, string>>): ChipSpec[] {
  const out: ChipSpec[] = [];
  if (row.range) out.push({ label: `Range ${row.range}`, tone: "default" });
  if (row.factory_default) out.push({ label: `Factory ${row.factory_default}`, tone: "default" });
  if (row.changed_from_default) out.push({ label: "Changed", tone: "accent" });
  if (row.needs_advanced) out.push({ label: "Advanced menu", tone: "warning" });
  if (row.locked) out.push({ label: "Set by the game", tone: "default" });
  out.push(rowEvidenceChip(row, labels));
  if (row.provenance.transfer) out.push({ label: "Made for the other torque", tone: "warning", title: row.provenance.transfer });
  if (row.provenance.stale) out.push({ label: "Stale source", tone: "warning" });
  if (row.provenance.consensus?.status === "split") out.push({ label: "Sources disagree", tone: "warning" });
  return out;
}

/** The code a row has on the wheel's display ("FF"); in-game rows have none (their keys are API ids). */
export function wheelCode(sectionId: string, key: string): string | null {
  return sectionId === "ingame" ? null : key;
}

/** The value as shown: instruction rows carry words ("check on your base"), others a menu value. "" -> "-". */
export function rowValue(row: SettingRow): string {
  const v = (row.value ?? "").trim();
  return v ? withMinus(v) : UNKNOWN;
}

// ---------------------------------------------------------------------------------------------- copy text
function rowMarks(r: SettingRow): string {
  const marks: string[] = [];
  if (r.provenance.kind === "range_pick") marks.push(`Pitwall pick in ${r.range ?? "the published range"}`);
  else if (r.provenance.derived) marks.push("Pitwall derived");
  if (r.provenance.transfer) marks.push("made for the other torque");
  if (r.locked) marks.push("set by the game");
  return marks.length ? `  [${marks.join("; ")}]` : "";
}

/** One row as plain text: "FF (Force Feedback): 100"; in-game rows by their label only. */
export function rowCopyText(r: SettingRow, code: string | null = r.key): string {
  return `${code ? `${code} (${r.label})` : r.label}: ${r.value}${rowMarks(r)}`;
}

/** A section as plain text in menu order (spec 7.2 "Copy section"): rows, then the section's steps. */
export function sectionCopyText(s: Section, heading?: string): string {
  const lines = heading ? [heading] : [];
  for (const r of s.rows) lines.push(rowCopyText(r, wheelCode(s.id, r.key)));
  for (const st of s.steps) lines.push(`- ${st.text}`);
  return lines.join("\n");
}

/** The section heading without the API's "1. " numbering ("2. Wheel base Tuning Menu (on-wheel order)" -> ...). */
export function sectionTitle(s: Pick<Section, "title">): string {
  return s.title.replace(/^\d+\.\s*/, "");
}

// ---------------------------------------------------------------------------------------------- rig check
function fixedNum(v: number, digits: number): string {
  return withMinus(v.toFixed(digits));
}

/** A rig check value with its unit; null -> "-". */
export function formatMetric(m: Pick<MetricResult, "value" | "unit">): string {
  const v = m.value;
  if (v === null || v === undefined || !Number.isFinite(v)) return UNKNOWN;
  switch (m.unit) {
    case "%":
      return `${fixedNum(v, Math.abs(v) < 1 ? 2 : Math.abs(v) < 10 ? 1 : 0)}%`;
    case "s":
      return `${fixedNum(v, 2)} s`;
    case "/s":
      return `${fixedNum(v, 1)}/s`;
    case "/min":
      return `${fixedNum(v, 0)}/min`;
    case "per lap":
      return `${fixedNum(v, 1)} a lap`;
    case "count":
    case "events":
      return fixedNum(v, 0);
    case "points":
      return `${v > 0 ? "+" : ""}${fixedNum(v, 1)} pts`;
    default:
      return `${fixedNum(v, 2)}${m.unit ? ` ${m.unit}` : ""}`;
  }
}

/** Status chip: pass green, warn amber, fail red, info neutral, unknown "-" (status colours, never timing ones). */
export const STATUS_CHIP: Record<MetricStatus, ChipSpec> = {
  pass: { label: "Pass", tone: "success" },
  warn: { label: "Warn", tone: "warning" },
  fail: { label: "Fail", tone: "danger" },
  info: { label: "Info", tone: "default", title: "For comparison between your own sessions" },
  unknown: { label: UNKNOWN, tone: "default", title: "Not measured in this session" },
};

export const STATUS_ORDER: readonly MetricStatus[] = ["fail", "warn", "pass", "info", "unknown"];

/** "5 pass · 1 warn · 4 info · 10 unknown" (zero counts left out). */
export function countsText(counts: Partial<Record<MetricStatus, number>>): string {
  const parts = STATUS_ORDER.map((s) => [s, counts[s] ?? 0] as const)
    .filter(([, n]) => n > 0)
    .map(([s, n]) => `${n} ${s}`);
  return parts.length ? parts.join(" · ") : "No metrics";
}

export function when(unix: number | null | undefined): string {
  if (!unix || !Number.isFinite(unix)) return UNKNOWN;
  return new Date(unix * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

/** "Austria · Race · 11 Oct 2026, 14:02" for the checked session. */
export function checkSessionLine(c: Pick<RigCheck, "track" | "session_type" | "started_unix">): string {
  const type = c.session_type && c.session_type !== "unknown" ? c.session_type : null;
  return [c.track ?? "Unknown track", type, when(c.started_unix)].filter(Boolean).join(" · ");
}

/** "Laps 2, 3, 4 (clean) · 60 Hz · Hall brake". */
export function checkLapsLine(c: Pick<RigCheck, "laps" | "lap_policy" | "sample_rate_hz" | "pedals" | "game" | "steering_lock_deg">): string {
  const parts = [`Laps ${c.laps.length ? c.laps.join(", ") : "none"} (${c.lap_policy === "usable" ? "all usable" : "clean"})`];
  if (c.sample_rate_hz) parts.push(`${Math.round(c.sample_rate_hz)} Hz`);
  if (c.pedals) parts.push(c.pedals === "csl_load_cell" ? "load-cell brake" : "Hall brake");
  if (c.game === "gt7" && c.steering_lock_deg === null) parts.push("GT7 steering lock unknown");
  return parts.join(" · ");
}

// ---------------------------------------------------------------------------------------------- upgrades
export const UPGRADE_LABEL: Record<UpgradeChange, string> = {
  boost_kit_180: "Boost Kit 180 (8 Nm)",
  load_cell_kit: "CSL Pedals Load Cell Kit",
  firmware: "Firmware update",
  rim: "Rim change",
  other: "Other change",
};

/** Only the two kits can be fitted or removed; the others are events. */
export function isKit(change: UpgradeChange): change is "boost_kit_180" | "load_cell_kit" {
  return change === "boost_kit_180" || change === "load_cell_kit";
}

export function upgradeText(u: Pick<UpgradeEvent, "change" | "fitted">): string {
  return isKit(u.change) ? `${UPGRADE_LABEL[u.change]} ${u.fitted ? "fitted" : "removed"}` : UPGRADE_LABEL[u.change];
}

/** Whether the profile has the kit now. */
export function kitFitted(p: Pick<RigProfile, "boost_kit_fitted" | "load_cell_fitted"> | null | undefined, change: UpgradeChange): boolean {
  if (!p) return false;
  if (change === "boost_kit_180") return p.boost_kit_fitted;
  if (change === "load_cell_kit") return p.load_cell_fitted;
  return false;
}

/** Newest first (the server appends). */
export function upgradeHistory(p: Pick<RigProfile, "upgrades"> | null | undefined): UpgradeEvent[] {
  return [...(p?.upgrades ?? [])].reverse();
}

/** Today as YYYY-MM-DD in local time (the date an upgrade is recorded for). */
export function todayIso(now: Date = new Date()): string {
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/** "5.0 Nm". */
export function torqueText(nm: number | null | undefined): string {
  return typeof nm === "number" && Number.isFinite(nm) ? `${nm.toFixed(1)} Nm` : UNKNOWN;
}

// ---------------------------------------------------------------------------------------------- hardware
const PLATFORM_SHORT: Record<string, string> = {
  ps5: "PS5",
  ps4: "PS4",
  pc: "PC",
  pc_ps5: "PC/PS5",
  xbox: "Xbox",
  playstation: "PlayStation",
  not_split: "every platform",
  not_stated: "platform not stated",
};

export function platformLabel(platform: string): string {
  return PLATFORM_SHORT[platform] ?? platform;
}

const BASE_SHORT: Record<string, string> = { fanatec_gt_dd_pro: "GT DD Pro" };
const PEDALS_SHORT: Record<string, string> = { csl: "CSL pedals", csl_load_cell: "CSL pedals + load cell" };

/** "PS5 · GT DD Pro 5 Nm · CSL pedals" (spec 7.2 header). */
export function hardwareLine(hw: Hardware, labels?: Partial<RigProfile["labels"]>): string {
  const base = BASE_SHORT[hw.wheel_base] ?? labels?.wheel_base ?? hw.wheel_base;
  const pedals = PEDALS_SHORT[hw.pedals] ?? labels?.pedals ?? hw.pedals;
  return `${platformLabel(hw.platform)} · ${base} ${hw.torque_nm} Nm · ${pedals}`;
}

/** Games the catalogue covers on this platform, in a fixed order. */
export function supportedGames(catalog: Pick<RigCatalog, "supported"> | null | undefined, platform: string | null | undefined): GameId[] {
  if (!catalog || !platform) return [...GAMES];
  const ok = new Set(catalog.supported.filter((s) => s.platform === platform).map((s) => s.game));
  return GAMES.filter((g) => ok.has(g));
}

// ---------------------------------------------------------------------------------------------- style and force
export function scaleText(v: number | null | undefined): string {
  return typeof v === "number" && Number.isFinite(v) ? `${Math.round(v * 100)}%` : UNKNOWN;
}

/** A style's line under its name: the description, or that no source publishes it (for the game and torque on
 * screen the recommendation knows; the catalogue flag is the per-style default). */
export function styleSubtitle(s: StyleInfo, rec: Pick<Recommendation, "requested_style" | "sourced"> | null | undefined): string {
  const sourced = rec && rec.requested_style === s.id ? rec.sourced : s.sourced;
  if (sourced || /derived/i.test(s.description)) return s.description;
  return `${s.description} No published source here: derived by Pitwall.`;
}

/** The force scale the slider shows: the driver's own, else the default the recommendation applied. */
export function shownScale(
  prefs: Pick<DriverPrefsResponse, "prefs" | "effective_strength_scale"> | null | undefined,
  rec: Pick<Recommendation, "strength_scale" | "strength_scale_source"> | null | undefined,
): number {
  if (prefs?.prefs.strength_scale != null) return prefs.prefs.strength_scale;
  if (rec && rec.strength_scale_source !== "driver") return rec.strength_scale;
  return prefs?.effective_strength_scale ?? 1;
}

/** What the force scale line says under the slider. */
export function strengthNote(
  prefs: Pick<DriverPrefsResponse, "prefs" | "skill_level"> | null | undefined,
  rec: Pick<Recommendation, "strength_scale" | "strength_scale_source" | "hardware"> | null | undefined,
): string {
  if (!prefs) return "";
  if (prefs.prefs.strength_scale !== null) return "Set for this driver.";
  const def = rec ? scaleText(rec.strength_scale) : UNKNOWN;
  const stronger = rec && rec.strength_scale_source === "skill_default" && rec.hardware.torque_nm > 5;
  return `Using the ${prefs.skill_level} default (${def})${stronger ? `: lower on the ${rec.hardware.torque_nm} Nm base so the wheel keeps its 5 Nm weight` : ""}.`;
}

/** Round a slider value to the 5 % steps the slider uses and keep it in the API's range. */
export function clampScale(v: number): number {
  const r = Math.round(v * 20) / 20;
  return Math.min(1, Math.max(0.2, r));
}

export function styleLabel(catalog: Pick<RigCatalog, "styles"> | null | undefined, id: StyleId): string {
  return catalog?.styles.find((s) => s.id === id)?.label ?? id;
}

// ---------------------------------------------------------------------------------------------- page query
export type RigViewId = "walk" | "settings" | "check" | "upgrades";

export interface RigQuery {
  driver: number | null;
  game: GameId | null;
}

export function parseRigQuery(query: string): RigQuery {
  const q = new URLSearchParams(query);
  const d = q.get("driver");
  const g = q.get("game");
  return {
    driver: d !== null && /^\d+$/.test(d) ? Number(d) : null,
    game: (GAMES as readonly (string | null)[]).includes(g) ? (g as GameId) : null,
  };
}

/** `/setup/rig[/<view>]` (+ `/walk/<section>/<n>`) with the driver and game kept in the query. */
export function rigPath(view: RigViewId, q: Partial<RigQuery> = {}, walk?: { section: string; n: number } | null): string {
  let path = "/setup/rig";
  if (view === "walk") {
    if (walk) path += `/walk/${encodeURIComponent(walk.section)}/${walk.n}`;
  } else path += `/${view}`;
  const params = new URLSearchParams();
  if (q.driver != null) params.set("driver", String(q.driver));
  if (q.game) params.set("game", q.game);
  const s = params.toString();
  return s ? `${path}?${s}` : path;
}

/** The device's last game on this page (same key as the Svelte page, so both remember the same choice). */
export const GAME_KEY = "pitwall-setup-game";

export function rememberedGame(): GameId | null {
  try {
    const v = localStorage.getItem(GAME_KEY);
    return (GAMES as readonly (string | null)[]).includes(v) ? (v as GameId) : null;
  } catch {
    return null;
  }
}

export function rememberGame(g: GameId): void {
  try {
    localStorage.setItem(GAME_KEY, g);
  } catch {
    /* storage unavailable: the page opens on F1 25 next time */
  }
}
