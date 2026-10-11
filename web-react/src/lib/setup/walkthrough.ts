// The rig walkthrough (spec 7.2; lane X): one glance step at a time, in five sections (base mode, wheel menu, in
// game, pedals, check on track), built from two sources that each keep their own evidence:
//
//   1. How to do it: the research walkthrough for this exact rig (Fanatec GT DD Pro on a PS5;
//      docs/research/gt-dd-pro-ps5-walkthrough.json, copied byte for byte to src/data/walkthrough.json and kept identical
//      by a test). Every step has "how you know it worked" (`check`), its evidence (V official, A seen in Fanatec's
//      video, U unconfirmed, D derived) and `verified`; the research's `mistakes` are the recovery tips.
//   2. What to set: GET /api/rig/recommendations for this driver and game (sections base / wheel / ingame / pedals with
//      `steps` and `rows` in menu order, each row with provenance).
//
// The guides apply only to the rig they were researched on (PS5 + GT DD Pro). On any other rig the walkthrough is
// the recommendation's own steps and rows. A guide step that says the same as an API step replaces it (COVERED); the
// All settings view still lists every API step. Nothing here invents advice: texts are the research's or the API's,
// verbatim, except that old Svelte page names in the research ("pitwall Live tab") point at the new pages.
//
// Progress is a per-device convenience (localStorage, try/catch), never data: a tick remembers the item's signature,
// so when the recommendation changes (another style, the Boost Kit) the changed rows open again marked `Updated`.

import { UNKNOWN } from "../format";
import type { GameId, Hardware, Recommendation, SectionId, SettingRow, Step } from "../endpoints/rig";
import { wheelCode } from "./rig";

// ---------------------------------------------------------------------------------------------- the research doc
export type GuideEvidence = "V" | "A" | "U" | "D";

export interface GuideStep {
  text: string;
  /** How you know it worked ("-" when there is nothing to check). */
  check: string;
  source: string;
  verified: boolean;
  evidence: GuideEvidence;
  note?: string;
  verifier?: string;
  verifier_note?: string;
}

export interface Guide {
  id: string;
  title: string;
  steps: GuideStep[];
}

export interface Mistake {
  id: string;
  symptom: string;
  cause: string;
  fix: string;
  source: string;
  verified: boolean;
  verifier?: string;
  verifier_note?: string;
}

export interface ResearchSource {
  title: string;
  url: string;
  date: string;
  locator?: string;
  note?: string;
}

export interface WalkthroughDoc {
  version: number;
  research_date: string;
  rig: string;
  evidence_labels: Partial<Record<GuideEvidence, string>>;
  walkthroughs: Guide[];
  mistakes: Mistake[];
  unverified: string[];
  sources: Record<string, ResearchSource>;
}

const EMPTY_DOC: WalkthroughDoc = {
  version: 0,
  research_date: "",
  rig: "",
  evidence_labels: {},
  walkthroughs: [],
  mistakes: [],
  unverified: [],
  sources: {},
};

function isObj(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** The research file as typed data; anything malformed is dropped (an empty doc means "no guides", never a crash). */
export function parseWalkthrough(raw: unknown): WalkthroughDoc {
  if (!isObj(raw)) return EMPTY_DOC;
  const guides = Array.isArray(raw.walkthroughs) ? raw.walkthroughs : [];
  return {
    version: typeof raw.version === "number" ? raw.version : 0,
    research_date: typeof raw.research_date === "string" ? raw.research_date : "",
    rig: typeof raw.rig === "string" ? raw.rig : "",
    evidence_labels: isObj(raw.evidence_labels) ? (raw.evidence_labels as WalkthroughDoc["evidence_labels"]) : {},
    walkthroughs: guides
      .filter((g): g is Record<string, unknown> => isObj(g) && typeof g.id === "string" && Array.isArray(g.steps))
      .map((g) => ({
        id: g.id as string,
        title: typeof g.title === "string" ? g.title : (g.id as string),
        steps: (g.steps as unknown[])
          .filter((s): s is GuideStep => isObj(s) && typeof s.text === "string")
          .map((s) => ({
            ...s,
            check: typeof s.check === "string" ? s.check : UNKNOWN,
            source: typeof s.source === "string" ? s.source : "",
            verified: s.verified === true,
            evidence: (["V", "A", "U", "D"] as const).includes(s.evidence) ? s.evidence : "U",
          })),
      })),
    mistakes: (Array.isArray(raw.mistakes) ? raw.mistakes : []).filter(
      (m): m is Mistake => isObj(m) && typeof m.id === "string" && typeof m.symptom === "string" && typeof m.fix === "string",
    ),
    unverified: (Array.isArray(raw.unverified) ? raw.unverified : []).filter((u): u is string => typeof u === "string"),
    sources: isObj(raw.sources) ? (raw.sources as Record<string, ResearchSource>) : {},
  };
}

const FILES = import.meta.glob<unknown>("../../data/walkthrough.json", { eager: true, import: "default" });

/** The research walkthrough (src/data/walkthrough.json). */
export const WALKTHROUGH: WalkthroughDoc = parseWalkthrough(Object.values(FILES)[0]);

export function guideById(doc: WalkthroughDoc, id: string): Guide | undefined {
  return doc.walkthroughs.find((g) => g.id === id);
}

/** Old Svelte page names in the research text -> where that is now. Exact phrases only. */
const PAGE_NAMES: [string, string][] = [
  ["pitwall Live brake bar", "The brake input on Drive › Car in Pitwall"],
  ["pitwall Live tab", "Drive › Car in Pitwall"],
  ["pitwall Setup tab", "Setup › Rig › All settings in Pitwall"],
  ["pitwall Setup sheet", "Setup › Rig › All settings in Pitwall"],
];

export function pitwallPages(text: string): string {
  let out = text;
  for (const [from, to] of PAGE_NAMES) out = out.split(from).join(to);
  return out;
}

// ---------------------------------------------------------------------------------------------- evidence of a guide step
export interface GuideChip {
  label: string;
  tone: "default" | "warning";
  /** The research's own explanation of the label (evidence_labels). */
  title?: string;
}

const GUIDE_EVIDENCE_TEXT: Record<GuideEvidence, string> = {
  V: "Verified",
  A: "Seen in Fanatec's video",
  U: "Unverified",
  D: "Derived",
};

/** Whether a step is flagged as not confirmed: the verifier said so, or the evidence is an owner report. */
export function isUnverified(s: Pick<GuideStep, "verified" | "evidence">): boolean {
  return !s.verified || s.evidence === "U";
}

/** The chips of a guide step: its evidence, plus "Unverified" when the research did not confirm it. */
export function guideChips(s: Pick<GuideStep, "verified" | "evidence">, labels: WalkthroughDoc["evidence_labels"] = {}): GuideChip[] {
  const out: GuideChip[] = [{ label: GUIDE_EVIDENCE_TEXT[s.evidence], tone: s.evidence === "U" ? "warning" : "default", title: labels[s.evidence] }];
  if (!s.verified && s.evidence !== "U") out.push({ label: "Unverified", tone: "warning", title: "The research could not confirm this step." });
  return out;
}

/** Whether there is something to check after the step ("-" or empty: nothing). */
export function hasCheck(s: Pick<GuideStep, "check">): boolean {
  const c = s.check.trim();
  return c !== "" && c !== "-" && c !== UNKNOWN;
}

// ---------------------------------------------------------------------------------------------- sources
export interface SourceRef {
  /** The research's source code ("M", "VID25") when it is known, else null (free text such as "derived"). */
  code: string | null;
  /** What the step cites from it ("p19 figure", "10:30-11:40"). */
  locator: string;
  title: string | null;
  /** Only http(s) links; repository paths stay text. */
  url: string | null;
  date: string | null;
  text: string;
}

/** "PROD; M p19; GTP22" -> one reference per part, resolved against the research's source list. */
export function sourceRefs(source: string, doc: WalkthroughDoc): SourceRef[] {
  return source
    .split(";")
    .map((p) => p.trim())
    .filter(Boolean)
    .map((part) => {
      const m = /^([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*)\b\s*(.*)$/.exec(part);
      const code = m?.[1] ?? null;
      const src = code ? doc.sources[code] : undefined;
      if (!code || !src) return { code: null, locator: "", title: null, url: null, date: null, text: part };
      return {
        code,
        locator: (m?.[2] ?? "").trim(),
        title: src.title,
        url: /^https?:\/\//.test(src.url) ? src.url : null,
        date: src.date ?? null,
        text: part,
      };
    });
}

// ---------------------------------------------------------------------------------------------- the plan
export type WalkSectionId = "base" | "wheel" | "ingame" | "pedals" | "check";

export const WALK_SECTIONS: readonly { id: WalkSectionId; title: string }[] = [
  { id: "base", title: "Base mode" },
  { id: "wheel", title: "Wheel menu" },
  { id: "ingame", title: "In game" },
  { id: "pedals", title: "Pedals" },
  { id: "check", title: "Check on track" },
];

export function isWalkSection(s: string | null | undefined): s is WalkSectionId {
  return WALK_SECTIONS.some((x) => x.id === s);
}

interface ItemBase {
  /** Stable id within a plan ("g:mode:2", "s:base:firmware", "r:wheel:FF", "check"). */
  id: string;
  /** Hash of what the driver was asked to do; a tick for another signature is "Updated". */
  sig: string;
  /** Recovery tips (mistake ids of the research) for this item. */
  tips: string[];
}

export type WalkItem =
  | (ItemBase & { kind: "guide"; guide: { id: string; title: string; index: number; size: number }; step: GuideStep })
  | (ItemBase & { kind: "step"; from: SectionId | "safety"; step: Step })
  | (ItemBase & { kind: "row"; from: SectionId; row: SettingRow })
  | (ItemBase & { kind: "check"; step: Step | null });

export interface WalkSection {
  id: WalkSectionId;
  title: string;
  items: WalkItem[];
}

export interface WalkPlan {
  sections: WalkSection[];
  /** The researched PS5 + GT DD Pro guides are part of this plan. */
  guided: boolean;
  /** API step ids a guide step replaced (still listed in All settings). */
  covered: string[];
}

/** 32-bit FNV-1a as 8 hex digits (short, stable signatures for localStorage). */
export function hash(s: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(16).padStart(8, "0");
}

/** The rig the research walkthrough was written for. */
export function guidesApply(hw: Pick<Hardware, "platform" | "wheel_base">): boolean {
  return hw.platform === "ps5" && hw.wheel_base === "fanatec_gt_dd_pro";
}

/** API steps that move out of their section: Tuning Menu steps of `base` go to the wheel menu; known issues and the
 * one-change rule go to "Check on track"; the pedals' `rig_check` step is the text of the final card. */
const API_PLACE: Record<string, WalkSectionId | "final"> = {
  menu: "wheel",
  no_a_set_f1: "wheel",
  slot: "wheel",
  driver_slot: "wheel",
  sen_match: "wheel",
  v125_bug: "check",
  one_change: "check",
  rig_check: "final",
};

/** API step id -> the guide that says the same in more detail (the API step is left out when that guide is shown). */
const COVERED_BY: Record<string, string> = {
  mode: "mode",
  power_on_press: "pedals_hall",
  hall_no_brf: "pedals_hall",
  connection: "pedals_hall",
};

/** Research mistakes -> the items they are a recovery tip for. "guide:<id>" every step of a guide, "step:<id>" an
 * API step, "row:<KEY>" a row, "rows:wheel" every wheel menu row (not under A SET), "rows:advanced" rows that need the
 * Advanced menu, "check" the final card. A test keeps every mistake of the research in this table. */
export const TIP_TARGETS: Record<string, string[]> = {
  a_set_locked: ["guide:slot", "guide:values", "rows:wheel"],
  menu_locked_firmware: ["guide:slot", "guide:values"],
  standard_menu: ["guide:standard_advanced", "step:menu", "rows:advanced"],
  accidental_reset: ["guide:standard_advanced"],
  wrong_stick: ["guide:controls", "guide:menu_basics"],
  wrong_mode: ["guide:mode", "step:mode"],
  power_held: ["guide:mode"],
  sen_mismatch: ["row:SEN", "row:MAX_WHEEL_ROTATION", "step:sen_match"],
  cal_flashing: ["guide:mode", "step:firmware"],
  no_recentre: ["row:SPR"],
  pedal_range: ["guide:pedals_hall", "step:power_on_press"],
  brf_missing: ["guide:load_cell_brf", "row:BRF"],
  lc_input_at_rest: ["guide:load_cell_brf"],
  ffs_missing_boost: ["row:FFS"],
  f1_v125_oscillation: ["step:v125_bug", "check"],
  still_auto_after_switch: ["guide:slot", "guide:standard_advanced"],
  blank_display: ["guide:controls", "guide:menu_basics"],
  menu_opens_on_value: ["guide:menu_basics"],
  gt7_wheel_spins: ["guide:gt7"],
};

/** The mistakes that can happen on this game and rig (the troubleshooting sheet lists these). */
export function relevantMistakes(doc: WalkthroughDoc, game: GameId, hw: Pick<Hardware, "pedals" | "torque_nm">): Mistake[] {
  return doc.mistakes.filter((m) => {
    if (m.id === "gt7_wheel_spins") return game === "gt7";
    if (m.id === "f1_v125_oscillation" || m.id === "sen_mismatch") return game === "f1_25";
    if (m.id === "lc_input_at_rest") return hw.pedals === "csl_load_cell";
    if (m.id === "pedal_range") return hw.pedals === "csl";
    if (m.id === "ffs_missing_boost") return hw.torque_nm === 8;
    return true;
  });
}

function tipsFor(targets: string[], allowed: ReadonlySet<string>): string[] {
  const set = new Set(targets);
  return Object.entries(TIP_TARGETS)
    .filter(([id, t]) => allowed.has(id) && t.some((x) => set.has(x)))
    .map(([id]) => id);
}

/** Build the walkthrough for a recommendation on this rig. Pure: the same inputs give the same plan. */
export function buildPlan(rec: Recommendation, hw: Hardware, game: GameId, doc: WalkthroughDoc = WALKTHROUGH): WalkPlan {
  const guided = guidesApply(hw) && doc.walkthroughs.length > 0;
  const allowed = new Set(relevantMistakes(doc, game, hw).map((m) => m.id));
  const apiSection = (id: SectionId) => rec.sections.find((s) => s.id === id) ?? { id, title: id, steps: [], rows: [] };
  const wheelRows = apiSection("wheel").rows;
  const setup = wheelRows.find((r) => r.key === "SETUP");
  const aSet = rec.a_set || (setup?.value ?? "").trim().toUpperCase().startsWith("A SET");
  const needsAdvanced = apiSection("base").steps.some((s) => s.id === "menu") || wheelRows.some((r) => r.needs_advanced);

  const shown = new Set<string>(); // guide ids in the plan
  const covered: string[] = [];
  const guideItems = (id: string, from = 0, to?: number): WalkItem[] => {
    if (!guided) return [];
    const g = guideById(doc, id);
    if (!g) return [];
    shown.add(id);
    return g.steps.slice(from, to).map((step, k) => {
      const index = from + k;
      return {
        kind: "guide" as const,
        id: `g:${id}:${index}`,
        sig: hash(`g|${step.text}|${step.check}`),
        tips: tipsFor([`guide:${id}`], allowed),
        guide: { id: g.id, title: g.title, index, size: g.steps.length },
        step,
      };
    });
  };
  // Decide which guides are shown before placing API steps, so COVERED knows.
  const pedalGuide = hw.pedals === "csl_load_cell" ? "load_cell_brf" : "pedals_hall";
  const gameGuide = game === "gt7" ? "gt7" : "f1_25";
  const willShow = new Set<string>(
    guided
      ? [
          "controls",
          "mode",
          "menu_basics",
          ...(needsAdvanced ? ["standard_advanced"] : []),
          ...(aSet ? [] : ["slot", "values"]),
          gameGuide,
          pedalGuide,
        ].filter((id) => guideById(doc, id))
      : [],
  );
  const keep = (s: Step): boolean => {
    const by = COVERED_BY[s.id];
    if (by && willShow.has(by)) {
      covered.push(s.id);
      return false;
    }
    return true;
  };
  const stepItem = (from: SectionId | "safety", s: Step): WalkItem => ({
    kind: "step",
    id: `s:${from}:${s.id}`,
    sig: hash(`s|${s.text}`),
    tips: tipsFor([`step:${s.id}`], allowed),
    from,
    step: s,
  });
  const rowItem = (from: SectionId, r: SettingRow): WalkItem => {
    const targets = [`row:${r.key}`];
    if (from === "wheel" && !aSet) targets.push("rows:wheel");
    if (r.needs_advanced) targets.push("rows:advanced");
    return {
      kind: "row",
      id: `r:${from}:${r.key}`,
      sig: hash(`r|${r.value}|${r.instruction ? 1 : 0}|${r.locked ? 1 : 0}`),
      tips: tipsFor(targets, allowed),
      from,
      row: r,
    };
  };

  // API steps by where they go.
  const moved = new Map<string, { from: SectionId; step: Step }>();
  const stay: Record<SectionId, Step[]> = { base: [], wheel: [], ingame: [], pedals: [] };
  for (const sec of rec.sections) {
    for (const s of sec.steps) {
      if (!keep(s)) continue;
      if (API_PLACE[s.id] && !moved.has(s.id)) moved.set(s.id, { from: sec.id, step: s });
      else stay[sec.id]?.push(s);
    }
  }
  const take = (id: string): WalkItem[] => {
    const m = moved.get(id);
    if (!m) return [];
    moved.delete(id);
    return [stepItem(m.from, m.step)];
  };

  const base: WalkItem[] = [...guideItems("controls"), ...guideItems("mode"), ...stay.base.map((s) => stepItem("base", s))];

  const valuesGuide = guideById(doc, "values");
  const valuesSplit = 3; // how-to steps before the rows; re-read and the SEN check after them
  const wheel: WalkItem[] = [
    ...guideItems("menu_basics"),
    ...take("menu"),
    ...(needsAdvanced ? guideItems("standard_advanced") : []),
    ...take("no_a_set_f1"),
    ...(aSet ? [] : guideItems("slot")),
    ...take("slot"),
    ...take("driver_slot"),
    ...take("sen_match"),
    ...stay.wheel.map((s) => stepItem("wheel", s)),
    ...(aSet || !valuesGuide ? [] : guideItems("values", 0, valuesSplit)),
    ...apiSection("wheel").rows.map((r) => rowItem("wheel", r)),
    ...(aSet || !valuesGuide ? [] : guideItems("values", valuesSplit)),
  ];

  const ingame: WalkItem[] = [
    ...guideItems(gameGuide),
    ...stay.ingame.map((s) => stepItem("ingame", s)),
    ...apiSection("ingame").rows.map((r) => rowItem("ingame", r)),
  ];

  const pedals: WalkItem[] = [
    ...guideItems(pedalGuide),
    ...stay.pedals.map((s) => stepItem("pedals", s)),
    ...apiSection("pedals").rows.map((r) => rowItem("pedals", r)),
  ];

  const finalStep = moved.get("rig_check")?.step ?? null;
  moved.delete("rig_check");
  const check: WalkItem[] = [
    ...rec.safety.map((s) => stepItem("safety", s)),
    ...take("v125_bug"),
    ...take("one_change"),
    // anything else API_PLACE moved but no slot took (cannot happen today; never lose a step)
    ...[...moved.values()].map((m) => stepItem(m.from, m.step)),
    { kind: "check", id: "check", sig: hash("check"), tips: tipsFor(["check"], allowed), step: finalStep },
  ];

  const items: Record<WalkSectionId, WalkItem[]> = { base, wheel, ingame, pedals, check };
  return {
    sections: WALK_SECTIONS.map((s) => ({ id: s.id, title: s.title, items: items[s.id] })),
    guided: guided && shown.size > 0,
    covered,
  };
}

// ---------------------------------------------------------------------------------------------- progress
/** item id -> the item's signature when it was ticked. */
export type Ticks = Record<string, string>;
export type ItemState = "done" | "updated" | "open";

export const PROGRESS_KEY = "pitwall-rig-walk";

/** Progress is kept per game and driver (one driver's ticks are not another's). */
export function progressScope(game: GameId, driverId: number | null): string {
  return `${game}:${driverId ?? "any"}`;
}

export function itemState(item: Pick<WalkItem, "id" | "sig">, ticks: Ticks): ItemState {
  const t = ticks[item.id];
  if (t === undefined) return "open";
  return t === item.sig ? "done" : "updated";
}

export function isDone(item: Pick<WalkItem, "id" | "sig">, ticks: Ticks): boolean {
  return itemState(item, ticks) === "done";
}

export function sectionDone(section: WalkSection, ticks: Ticks): boolean {
  return section.items.length > 0 && section.items.every((i) => isDone(i, ticks));
}

export function sectionCounts(section: WalkSection, ticks: Ticks): { done: number; total: number } {
  return { done: section.items.filter((i) => isDone(i, ticks)).length, total: section.items.length };
}

/** Storage -> { scope: ticks }; anything malformed is dropped. */
export function readProgress(raw: string | null): Record<string, Ticks> {
  if (!raw) return {};
  try {
    const v = JSON.parse(raw) as unknown;
    if (!isObj(v)) return {};
    const out: Record<string, Ticks> = {};
    for (const [scope, t] of Object.entries(v)) {
      if (!isObj(t)) continue;
      const ticks: Ticks = {};
      for (const [id, sig] of Object.entries(t)) if (typeof sig === "string") ticks[id] = sig;
      out[scope] = ticks;
    }
    return out;
  } catch {
    return {};
  }
}

export function loadTicks(scope: string): Ticks {
  try {
    return readProgress(localStorage.getItem(PROGRESS_KEY))[scope] ?? {};
  } catch {
    return {};
  }
}

export function saveTicks(scope: string, ticks: Ticks): void {
  try {
    const all = readProgress(localStorage.getItem(PROGRESS_KEY));
    all[scope] = ticks;
    localStorage.setItem(PROGRESS_KEY, JSON.stringify(all));
  } catch {
    /* storage unavailable: ticks last for this visit only */
  }
}

export function tick(ticks: Ticks, items: readonly Pick<WalkItem, "id" | "sig">[]): Ticks {
  const next = { ...ticks };
  for (const i of items) next[i.id] = i.sig;
  return next;
}

export function untick(ticks: Ticks, item: Pick<WalkItem, "id">): Ticks {
  const next = { ...ticks };
  delete next[item.id];
  return next;
}

// ---------------------------------------------------------------------------------------------- position
export interface WalkPos {
  s: number;
  i: number;
}

/** The first item not done, from a position on (wrapping to the start); null when everything is done. */
export function firstOpen(plan: WalkPlan, ticks: Ticks, from: WalkPos = { s: 0, i: 0 }): WalkPos | null {
  const flat = flatten(plan);
  if (!flat.length) return null;
  const start = Math.max(
    0,
    flat.findIndex((p) => p.s === from.s && p.i === from.i),
  );
  for (let k = 0; k < flat.length; k++) {
    const p = flat[(start + k) % flat.length]!;
    if (!isDone(plan.sections[p.s]!.items[p.i]!, ticks)) return p;
  }
  return null;
}

export function flatten(plan: WalkPlan): WalkPos[] {
  const out: WalkPos[] = [];
  plan.sections.forEach((sec, s) => sec.items.forEach((_, i) => out.push({ s, i })));
  return out;
}

/** Where the route points (`/walk/<section>/<n>`, n 1-based): a named step, a section's first open step (or its
 * first), or with nothing named the first open step overall (or the very last one when all are done). */
export function locate(plan: WalkPlan, section: string | null, n: number | null, ticks: Ticks): WalkPos {
  const s = plan.sections.findIndex((x) => x.id === section);
  if (s >= 0) {
    const sec = plan.sections[s]!;
    if (!sec.items.length) return { s, i: 0 };
    if (n !== null && n >= 1 && n <= sec.items.length) return { s, i: n - 1 };
    const open = sec.items.findIndex((it) => !isDone(it, ticks));
    return { s, i: open >= 0 ? open : 0 };
  }
  const open = firstOpen(plan, ticks);
  if (open) return open;
  const last = plan.sections.length - 1;
  return { s: Math.max(0, last), i: Math.max(0, (plan.sections[last]?.items.length ?? 1) - 1) };
}

/** The next (+1) or previous (-1) item across sections, skipping empty ones; null at either end. */
export function neighbour(plan: WalkPlan, pos: WalkPos, dir: 1 | -1): WalkPos | null {
  const flat = flatten(plan);
  const k = flat.findIndex((p) => p.s === pos.s && p.i === pos.i);
  if (k < 0) return flat[0] ?? null;
  return flat[k + dir] ?? null;
}

export function itemAt(plan: WalkPlan, pos: WalkPos): WalkItem | null {
  return plan.sections[pos.s]?.items[pos.i] ?? null;
}

/** All items of the same guide as `item` (for "I know this part"). */
export function guideRun(section: WalkSection, item: WalkItem): WalkItem[] {
  if (item.kind !== "guide") return [item];
  return section.items.filter((x) => x.kind === "guide" && x.guide.id === item.guide.id);
}

/** The code the wheel's display shows for a Tuning Menu row ("FF"); in-game rows have none (their keys are API ids). */
export function menuCode(item: WalkItem): string | null {
  return item.kind === "row" ? wheelCode(item.from, item.row.key) : null;
}

/** A short line for the section list beside the step card. */
export function itemTitle(item: WalkItem): { code: string | null; text: string; value: string | null } {
  switch (item.kind) {
    case "row":
      return { code: menuCode(item), text: item.row.label, value: item.row.instruction ? "check" : item.row.value };
    case "guide":
      return { code: null, text: pitwallPages(item.step.text), value: null };
    case "step":
      return { code: null, text: item.step.text, value: null };
    case "check":
      return { code: null, text: "Drive 3 clean laps, then open Rig check", value: null };
  }
}
