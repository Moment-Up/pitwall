// Review › Coaching › "How corners work" (technique knowledge spec section 4): the technique graph
// (GET /api/technique/knowledge, lib/endpoints/knowledge.ts) as plain words for one driver. Pure; tested in node.
//
//   - The six phases of a corner in driving order, each with its techniques, tagged for the viewed driver:
//     "Fits you" (every condition holds), "For other drivers" (a condition is known not to hold) or "Not known yet"
//     (it depends on something Pitwall does not know about the driver or car), with a one-line reason.
//   - Alternatives (trail braking and straight-line braking are each other's), the signals that measure a technique.
//   - The faults Pitwall checks: coached now (status live) apart from the ones not coached yet (experimental, planned,
//     background), with whether each applies to this driver and car, and the causes Pitwall can tell apart.
//   - Where the knowledge comes from, Ed (Pitwall tester) credited first, by evidence tier.
//
// Fit: the session variant's per-node `applies` / `why_not` decide when the server sends them. Otherwise the
// conditions are evaluated here over the Context the page has (the server's `context`, else the viewed driver's level
// from their profile, the one trait the page knows for sure), in three values: an unknown trait satisfies no
// condition (CLAUDE.md, "unknown stays unknown"), exactly as the server's `Condition.holds`, and here that is said as
// "Not known yet" rather than passed off as "for other drivers".
//
// Evidence: expert and brief knowledge is never presented as validated by Pitwall; tier labels say what each is.
// Density (lib/review/density.ts levels): beginners read the narrative (phase and technique summaries, what fits them);
// advanced drivers get the detail inline (how it works, tiers, signals, faults not coached yet with their
// measurements, every source).

import type { SkillLevel } from "../drivers";
import type {
  ContextKey,
  FaultStatus,
  KnowledgeChannel,
  KnowledgeCondition,
  KnowledgeContext,
  KnowledgeFault,
  KnowledgeMeasurement,
  KnowledgeNode,
  KnowledgeSource,
  KnowledgeStyle,
  KnowledgeTechnique,
  KnowledgeTier,
  TechniqueKnowledge,
} from "../endpoints/knowledge";

// ---------------------------------------------------------------------------------------------- words

/** Context keys in the server's order (pitwall.knowledge.graph.CONTEXT_VALUES). */
export const CONTEXT_KEYS: readonly ContextKey[] = [
  "skill",
  "braking_style",
  "coasting",
  "game",
  "car_family",
  "downforce",
  "abs",
  "traction_control",
  "gearbox",
  "fuel_saving",
  "wet",
];

/** What an unknown trait is called in "Not known yet: ...". */
export const CONTEXT_KEY_WORDS: Readonly<Record<ContextKey, string>> = {
  skill: "your level",
  braking_style: "your braking style",
  coasting: "how often you coast",
  game: "the game",
  car_family: "the car",
  downforce: "the car's downforce",
  abs: "whether ABS is on",
  traction_control: "whether traction control is on",
  gearbox: "the gearbox",
  fuel_saving: "whether you are saving fuel",
  wet: "whether the track is wet",
};

/** Evidence tiers in plain words (the server's `tiers` has the long meaning). */
export const TIER_LABEL: Readonly<Record<KnowledgeTier, string>> = {
  expert: "Published coaching",
  brief: "Ed's brief",
  synthetic: "Synthetic only",
  recorded: "Measured by Pitwall",
  live: "Live in Pitwall",
  design: "Pitwall rule",
};

export const STATUS_LABEL: Readonly<Record<FaultStatus, string>> = {
  live: "Coached now",
  experimental: "Measured, not coached yet",
  planned: "Planned",
  context_only: "Background",
};

const STATUS_ORDER: readonly FaultStatus[] = ["live", "experimental", "planned", "context_only"];

// ---------------------------------------------------------------------------------------------- conditions

/** true holds, false does not, null depends on a trait that is unknown. */
export type Tri = boolean | null;

/** false if any is false, else null if any is unknown, else true (true for none). */
export function allTri(values: Iterable<Tri>): Tri {
  let unknown = false;
  for (const v of values) {
    if (v === false) return false;
    if (v === null) unknown = true;
  }
  return unknown ? null : true;
}

/** true if any is true, else null if any is unknown, else false (false for none). */
export function anyTri(values: Iterable<Tri>): Tri {
  let unknown = false;
  for (const v of values) {
    if (v === true) return true;
    if (v === null) unknown = true;
  }
  return unknown ? null : false;
}

type Conditions = ReadonlyMap<string, KnowledgeCondition>;

function atomicTri(c: KnowledgeCondition, ctx: KnowledgeContext): Tri {
  if (!c.key) return false;
  const v = ctx[c.key];
  if (v === null || v === undefined) return null;
  switch (c.op) {
    case "true":
      return v === true;
    case "false":
      return v === false;
    case "eq":
      return v === c.value;
    case "ne":
      return v !== c.value;
    case "in":
      return Array.isArray(c.value) && typeof v === "string" && c.value.includes(v);
    default:
      return false;
  }
}

/** A condition over a Context, three-valued (the server's TechniqueGraph.holds with "unknown" kept apart). An unknown
 * condition id, or a cycle (the server rejects both), never holds. */
export function conditionTri(id: string, ctx: KnowledgeContext, conds: Conditions, seen: ReadonlySet<string> = new Set()): Tri {
  const c = conds.get(id);
  if (!c || seen.has(id)) return false;
  if (c.all_of.length || c.any_of.length) {
    const next = new Set(seen).add(id);
    const all = allTri(c.all_of.map((x) => conditionTri(x, ctx, conds, next)));
    const any = c.any_of.length ? anyTri(c.any_of.map((x) => conditionTri(x, ctx, conds, next))) : true;
    return allTri([all, any]);
  }
  return atomicTri(c, ctx);
}

interface Gated {
  applies_when: readonly string[];
  applies_any: readonly string[];
}

/** Whether a technique or fault applies: every `applies_when` and at least one `applies_any` (when it has any). */
export function appliesTri(node: Gated, ctx: KnowledgeContext, conds: Conditions): Tri {
  const when = allTri(node.applies_when.map((id) => conditionTri(id, ctx, conds)));
  const any = node.applies_any.length ? anyTri(node.applies_any.map((id) => conditionTri(id, ctx, conds))) : true;
  return allTri([when, any]);
}

/** Context keys a node's conditions read that are unknown in `ctx`, in Context order. */
export function unknownKeys(node: Gated, ctx: KnowledgeContext, conds: Conditions): ContextKey[] {
  const keys = new Set<ContextKey>();
  const visit = (id: string, seen: Set<string>) => {
    const c = conds.get(id);
    if (!c || seen.has(id)) return;
    seen.add(id);
    if (c.key && (ctx[c.key] === null || ctx[c.key] === undefined)) keys.add(c.key);
    for (const x of [...c.all_of, ...c.any_of]) visit(x, seen);
  };
  for (const id of [...node.applies_when, ...node.applies_any]) visit(id, new Set());
  return CONTEXT_KEYS.filter((k) => keys.has(k));
}

const names = (ids: readonly string[], conds: Conditions) => ids.map((id) => conds.get(id)?.name ?? id);

/** Who a gated node is for, in the conditions' own names: "Beginner or Straight-line braking driver". */
export function whoFor(node: Gated, conds: Conditions): string {
  const when = names(node.applies_when, conds).join(" and ");
  const any = names(node.applies_any, conds).join(" or ");
  return when && any ? `${when}, and ${any}` : when || any;
}

// ---------------------------------------------------------------------------------------------- fit

export type Fit = "fits" | "other" | "unknown";

export interface FitVerdict {
  fit: Fit;
  /** No conditions: good technique for every driver and car. */
  universal: boolean;
  /** One plain line: why it fits, who it is for, or what is not known yet. */
  reason: string;
}

export const FIT_LABEL: Readonly<Record<Fit, string>> = {
  fits: "Fits you",
  other: "For other drivers",
  unknown: "Not known yet",
};

/** The tag's words; `name` when the page shows another driver's plan ("Fits Alex"). */
export function fitLabel(fit: Fit, name?: string | null): string {
  return fit === "fits" && name ? `Fits ${name}` : FIT_LABEL[fit];
}

/** A fault's tag: whether Pitwall's check of it applies to this driver and car. Not "for other drivers": the session
 * variant also rules a fault out when the game does not send a channel it needs ("GT7 does not send ..."). */
export function faultFitLabel(fit: Fit, name?: string | null): string {
  if (fit === "fits") return `Applies to ${name ?? "you"}`;
  return fit === "other" ? "Does not apply here" : FIT_LABEL.unknown;
}

/** Words for an unknown-trait list: "your braking style and the car's downforce". */
function andList(items: readonly string[]): string {
  if (items.length <= 1) return items[0] ?? "";
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/**
 * A technique's or fault's fit for the driver in `ctx`. The server's verdict (`applies` / `why_not`, session variant)
 * wins when present; the three-valued evaluation then only tells "not known yet" apart from "for other drivers".
 */
export function fitOf(node: Gated & Pick<KnowledgeNode, "applies" | "why_not">, ctx: KnowledgeContext, conds: Conditions): FitVerdict {
  const universal = !node.applies_when.length && !node.applies_any.length;
  const tri = universal ? true : appliesTri(node, ctx, conds);
  const server = typeof node.applies === "boolean" ? node.applies : null;
  const holds = server ?? tri;
  const who = whoFor(node, conds);
  if (holds === true) {
    if (universal) return { fit: "fits", universal, reason: "For every driver and car." };
    const matched = [
      ...node.applies_when,
      ...node.applies_any.filter((id) => conditionTri(id, ctx, conds) === true),
    ];
    return { fit: "fits", universal, reason: matched.length ? `Matches: ${names(matched, conds).join("; ")}.` : `For: ${who}.` };
  }
  const why = node.why_not?.trim() || null;
  if (tri === null) {
    const unknown = unknownKeys(node, ctx, conds).map((k) => CONTEXT_KEY_WORDS[k]);
    const reason = why ?? `For: ${who}. Not known yet: ${andList(unknown) || "who you are"}.`;
    return { fit: "unknown", universal, reason: withStop(reason) };
  }
  return { fit: "other", universal, reason: withStop(why ?? (who ? `For: ${who}` : "Does not apply here")) };
}

function withStop(s: string): string {
  return /[.!?]$/.test(s) ? s : `${s}.`;
}

// ---------------------------------------------------------------------------------------------- context

export interface PageContext {
  ctx: KnowledgeContext;
  /** "server": the session's Context; "profile": only the viewed driver's level; "none": nothing known. */
  source: "server" | "profile" | "none";
}

/** The Context to judge fit with: the server's (session variant) when it sent one, else the profile's level. */
export function pageContext(server: KnowledgeContext | null | undefined, skill: SkillLevel | null | undefined): PageContext {
  if (server && typeof server === "object") return { ctx: server, source: "server" };
  if (skill) return { ctx: { skill }, source: "profile" };
  return { ctx: {}, source: "none" };
}

/** The known traits as chips, in the graph's own words ("Beginner", "Trail-braking driver", "High downforce", "No
 * ABS"): the atomic eq / true / false conditions that hold, in Context order. */
export function contextChips(ctx: KnowledgeContext, conditions: readonly KnowledgeCondition[]): string[] {
  const out: { key: ContextKey; name: string }[] = [];
  for (const c of conditions) {
    if (!c.key || c.all_of.length || c.any_of.length) continue;
    if (c.op !== "eq" && c.op !== "true" && c.op !== "false") continue;
    if (atomicTri(c, ctx) === true) out.push({ key: c.key, name: c.name });
  }
  return CONTEXT_KEYS.flatMap((k) => out.filter((x) => x.key === k).map((x) => x.name));
}

// ---------------------------------------------------------------------------------------------- density

export interface KnowledgeDensity {
  level: SkillLevel;
  /** How a technique's detail shows: "none" (the summary is the narrative), "fold" (behind "How it works"), "open". */
  detail: "none" | "fold" | "open";
  /** Techniques for other drivers listed with the rest (advanced) or folded under "For other drivers (n)". */
  othersOpen: boolean;
  /** "Instead: ..." under a technique that has alternatives. */
  alternatives: boolean;
  /** Evidence tier chips on techniques and faults (the section's note says it for everyone). */
  tiers: boolean;
  /** "Measured by: ..." under each technique. */
  signals: boolean;
  /** Faults not coached yet: left out (beginners), folded, or open. */
  notCoached: "hidden" | "fold" | "open";
  /** The causes Pitwall tells apart, under each coached fault. */
  causes: boolean;
  /** Pitwall's measurements of a fault (firing rates on recorded laps). */
  measured: boolean;
  /** Every source listed open (advanced) or the credit with the list folded. */
  sourcesOpen: boolean;
  /** Body text size, px (beginners 18, like Work on). */
  textPx: 16 | 18;
}

export function knowledgeDensity(level: SkillLevel): KnowledgeDensity {
  if (level === "beginner") {
    return {
      level,
      detail: "none",
      othersOpen: false,
      alternatives: false,
      tiers: false,
      signals: false,
      notCoached: "hidden",
      causes: false,
      measured: false,
      sourcesOpen: false,
      textPx: 18,
    };
  }
  if (level === "intermediate") {
    return {
      level,
      detail: "fold",
      othersOpen: false,
      alternatives: true,
      tiers: false,
      signals: false,
      notCoached: "fold",
      causes: true,
      measured: false,
      sourcesOpen: false,
      textPx: 16,
    };
  }
  return {
    level,
    detail: "open",
    othersOpen: true,
    alternatives: true,
    tiers: true,
    signals: true,
    notCoached: "open",
    causes: true,
    measured: true,
    sourcesOpen: true,
    textPx: 16,
  };
}

// ---------------------------------------------------------------------------------------------- phases

export interface NamedRef {
  id: string;
  name: string;
}

export interface TechniqueItem {
  id: string;
  name: string;
  summary: string;
  detail: string;
  tier: KnowledgeTier;
  fit: FitVerdict;
  alternatives: (NamedRef & { fit: Fit })[];
  /** The signals that measure it; `measured` false = Pitwall does not compute it yet. */
  signals: (NamedRef & { measured: boolean })[];
}

export interface PhaseView {
  id: string;
  order: number;
  name: string;
  summary: string;
  /** Fits the driver, then not known yet: always shown. */
  shown: TechniqueItem[];
  /** For other drivers: folded below unless the density opens them. */
  others: TechniqueItem[];
}

const FIT_ORDER: Readonly<Record<Fit, number>> = { fits: 0, unknown: 1, other: 2 };

/** The phases in driving order with their techniques for the driver in `ctx` (graph order within a fit). */
export function phaseViews(g: TechniqueKnowledge, ctx: KnowledgeContext): PhaseView[] {
  const conds: Conditions = new Map(g.conditions.map((c) => [c.id, c]));
  const signals = new Map(g.signals.map((s) => [s.id, s]));
  const techniques = new Map(g.techniques.map((t) => [t.id, t]));
  const fits = new Map(g.techniques.map((t) => [t.id, fitOf(t, ctx, conds)]));
  const item = (t: KnowledgeTechnique): TechniqueItem => ({
    id: t.id,
    name: t.name,
    summary: t.summary,
    detail: t.detail,
    tier: t.tier,
    fit: fits.get(t.id)!,
    alternatives: t.alternatives
      .map((id) => techniques.get(id))
      .filter((x): x is KnowledgeTechnique => !!x)
      .map((a) => ({ id: a.id, name: a.name, fit: fits.get(a.id)!.fit })),
    signals: t.measured_by.map((id) => {
      const s = signals.get(id);
      return { id, name: s?.name ?? id, measured: !!s?.code };
    }),
  });
  return [...g.phases]
    .sort((a, b) => a.order - b.order)
    .map((p) => {
      const items = g.techniques
        .filter((t) => t.phase === p.id)
        .map(item)
        .sort((a, b) => FIT_ORDER[a.fit.fit] - FIT_ORDER[b.fit.fit]);
      return {
        id: p.id,
        order: p.order,
        name: p.name,
        summary: p.summary,
        shown: items.filter((x) => x.fit.fit !== "other"),
        others: items.filter((x) => x.fit.fit === "other"),
      };
    });
}

// ---------------------------------------------------------------------------------------------- faults

export interface FaultItem {
  id: string;
  name: string;
  summary: string;
  phase: string;
  status: FaultStatus;
  statusLabel: string;
  tier: KnowledgeTier;
  /** Praise, not a fault (exit_gain). */
  positive: boolean;
  fit: FitVerdict;
  /** The causes Pitwall can tell apart from measured signals. */
  causes: NamedRef[];
  /** Pitwall's own measurements, one line each ("Fires on corner-laps (Ed's detector): 66.8% (2026-10-14)"). */
  measured: string[];
}

export interface FaultGroups {
  /** Coached today (status live), in phase order. */
  coached: FaultItem[];
  /** Experimental, planned and background, by status then phase. */
  notCoached: FaultItem[];
}

/** "66.8%", "0.05 s", "11 count". */
function amountText(value: number, unit: string): string {
  const v = Number.isInteger(value) ? String(value) : String(Number(value.toFixed(2)));
  return unit === "%" ? `${v}%` : `${v} ${unit}`.trim();
}

export function measurementText(m: KnowledgeMeasurement): string {
  const metric = m.metric ? m.metric[0]!.toUpperCase() + m.metric.slice(1) : "Measured";
  return `${metric}: ${amountText(m.value, m.unit)} (${m.date})`;
}

export function faultGroups(g: TechniqueKnowledge, ctx: KnowledgeContext): FaultGroups {
  const conds: Conditions = new Map(g.conditions.map((c) => [c.id, c]));
  const phases = new Map(g.phases.map((p) => [p.id, p]));
  const causes = new Map(g.causes.map((c) => [c.id, c]));
  const order = (f: KnowledgeFault) => phases.get(f.phase)?.order ?? 99;
  const item = (f: KnowledgeFault): FaultItem => ({
    id: f.id,
    name: f.name,
    summary: f.summary,
    phase: phases.get(f.phase)?.name ?? f.phase,
    status: f.status,
    statusLabel: STATUS_LABEL[f.status] ?? f.status,
    tier: f.tier,
    positive: f.positive,
    fit: fitOf(f, ctx, conds),
    causes: f.causes.map((id) => ({ id, name: causes.get(id)?.name ?? id })),
    measured: f.measured.map(measurementText),
  });
  const rank = (s: FaultStatus) => {
    const i = STATUS_ORDER.indexOf(s);
    return i < 0 ? STATUS_ORDER.length : i;
  };
  const sorted = [...g.faults].sort((a, b) => rank(a.status) - rank(b.status) || order(a) - order(b));
  return {
    coached: sorted.filter((f) => f.status === "live").map(item),
    notCoached: sorted.filter((f) => f.status !== "live").map(item),
  };
}

// ---------------------------------------------------------------------------------------------- sources

export interface SourceItem {
  id: string;
  title: string;
  author: string;
  note: string;
  url: string | null;
  date: string | null;
  tier: KnowledgeTier;
  tierLabel: string;
  /** How many nodes cite it. */
  cited: number;
}

export interface SourceGroups {
  /** Ed's brief, checklist and patches (tier brief): credited first. */
  ed: SourceItem[];
  /** Published coaching (tier expert). */
  published: SourceItem[];
  /** Pitwall's own rules and measurements (design, recorded, live, synthetic). */
  pitwall: SourceItem[];
  /** "Ed (Pitwall tester)", from the brief sources' author, or null when there are none. */
  edAuthor: string | null;
}

function citations(g: TechniqueKnowledge): Map<string, number> {
  const n = new Map<string, number>();
  const nodes: readonly KnowledgeNode[] = [
    ...g.phases,
    ...g.conditions,
    ...g.techniques,
    ...g.signals,
    ...g.faults,
    ...g.causes,
    ...g.advice,
    ...g.constraints,
  ];
  for (const node of nodes) for (const s of new Set(node.sources)) n.set(s, (n.get(s) ?? 0) + 1);
  return n;
}

export function sourceGroups(g: TechniqueKnowledge): SourceGroups {
  const cited = citations(g);
  const item = (s: KnowledgeSource): SourceItem => ({
    id: s.id,
    title: s.title,
    author: s.author,
    note: s.note,
    url: s.url && /^https?:\/\//.test(s.url) ? s.url : null,
    date: s.date,
    tier: s.tier,
    tierLabel: TIER_LABEL[s.tier] ?? s.tier,
    cited: cited.get(s.id) ?? 0,
  });
  const byCited = (a: SourceItem, b: SourceItem) => b.cited - a.cited || a.title.localeCompare(b.title);
  const ed = g.sources.filter((s) => s.tier === "brief").map(item);
  return {
    ed,
    published: g.sources.filter((s) => s.tier === "expert").map(item).sort(byCited),
    pitwall: g.sources.filter((s) => s.tier !== "brief" && s.tier !== "expert").map(item).sort(byCited),
    edAuthor: ed[0]?.author ?? null,
  };
}

// ---------------------------------------------------------------------------------------------- the section

export interface CornersView {
  context: PageContext;
  chips: string[];
  phases: PhaseView[];
  faults: FaultGroups;
  sources: SourceGroups;
  /** Tier -> meaning, the server's words (for the evidence note and tier chips' titles). */
  tiers: Partial<Record<KnowledgeTier, string>>;
}

/** Everything the section shows, for the viewed driver (`skill`: their profile's level, or null). */
export function cornersView(g: TechniqueKnowledge, skill: SkillLevel | null | undefined): CornersView {
  const context = pageContext(g.context, skill);
  return {
    context,
    chips: contextChips(context.ctx, g.conditions),
    phases: phaseViews(g, context.ctx),
    faults: faultGroups(g, context.ctx),
    sources: sourceGroups(g),
    tiers: g.tiers ?? {},
  };
}

/**
 * The detected style in words, from what it was detected from (`?session=` `style`): "From 9 clean laps: the brake
 * still on into the turn at 53 of 56 braking corners, a roll off both pedals at 7." - or that there are not enough
 * clean laps to tell yet, or that the game sends no steering to tell it from (`no_steering`); null without the session
 * variant. Counts only: the shares' thresholds are the server's. With the F1 braking assist on it adds that some of
 * that braking was the game's (pitwall.knowledge.style).
 */
export function styleLine(style: KnowledgeStyle | null | undefined, name?: string | null): string | null {
  if (!style || typeof style !== "object" || !Number.isFinite(style.braking_corners)) return null;
  const your = name ? `${name}'s` : "your";
  if (style.no_steering) {
    return `This game sends no steering, so Pitwall cannot tell ${your} braking style here.`;
  }
  if (!style.enough) {
    return `Not enough clean laps in ${your} last session here to tell ${your} braking style yet.`;
  }
  const laps = `${style.laps} clean ${style.laps === 1 ? "lap" : "laps"}`;
  const trail = `the brake still on into the turn at ${style.trail_corners} of ${style.braking_corners} braking corners`;
  const coast = Number.isFinite(style.coast_measured) && style.coast_measured > 0 ? `, a roll off both pedals at ${style.coast_corners}` : "";
  const assist =
    typeof style.braking_assist === "number" && style.braking_assist >= 1
      ? " The game's braking assist was on, so some of that braking was the game's."
      : "";
  return `From ${laps}: ${trail}${coast}.${assist}`;
}

/**
 * What the session's game does not send, from `?session=` `channels`: "This game does not send lateral g or wheel
 * slip, so checks that need them do not apply here." plus each channel's caveat (GT7's throttle after traction
 * control); null when every channel is sent or unknown (an unknown channel is never assumed absent).
 */
export function channelsLine(channels: Record<string, KnowledgeChannel> | null | undefined): string | null {
  if (!channels || typeof channels !== "object") return null;
  const rows = Object.values(channels).filter((c): c is KnowledgeChannel => !!c && typeof c === "object");
  const missing = rows.filter((c) => c.status === "not_sent").map((c) => c.words);
  const caveats = [...new Set(rows.map((c) => c.caveat?.trim()).filter((c): c is string => !!c))];
  const parts: string[] = [];
  if (missing.length) {
    const or = missing.length === 1 ? missing[0] : `${missing.slice(0, -1).join(", ")} or ${missing[missing.length - 1]}`;
    parts.push(`This game does not send ${or}, so checks that need ${missing.length === 1 ? "it" : "them"} do not apply here.`);
  }
  parts.push(...caveats);
  return parts.length ? parts.join(" ") : null;
}

/** One line on what the tags were judged from; `name` when the page shows another driver's plan. */
export function contextNote(c: PageContext, name?: string | null): string {
  const your = name ? `${name}'s` : "your";
  if (c.source === "server") return `Matched to the driver and car of ${your} last session here.`;
  if (c.source === "profile") {
    return `Matched to ${your} level only: Pitwall does not know ${your} braking style or the car here yet, so techniques that depend on them say so.`;
  }
  return `Pitwall does not know ${your} level, braking style or car yet, so techniques that depend on them say so.`;
}

/** Ed's credit, from his sources' author and titles: "From Ed (Pitwall tester): Idealised corner brief and
 * self-check; Technique-fault checklist; ...", or null when the graph cites none of his material. */
export function creditLine(s: Pick<SourceGroups, "ed" | "edAuthor">): string | null {
  if (!s.edAuthor || !s.ed.length) return null;
  return `From ${s.edAuthor}: ${s.ed.map((x) => x.title).join("; ")}.`;
}
