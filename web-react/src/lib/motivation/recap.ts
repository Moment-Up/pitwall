// "Today's 3 things" (lane motivation, spec 4.8 and 9): one thing that went well, one to work on, and one about
// progress, for a session. The server picks and words them deterministically (the coach's observation texts
// verbatim; never "brake later" on its own); this module only lays them out for Review's Summary and Drive's Session
// complete card. Pure; tested in plain node.
//
// An item the server could not fill is "-" with its reason (`why_empty`): "Synthetic sessions do not count towards
// progress", "Replays are not anyone's driving", "This session has no driver profile".

import type { Badge, SessionRecap, ThingItem, ThingKind, ThingSource } from "../endpoints/motivation";

export type ThingTone = "success" | "warning" | "neutral";
export type ThingIcon = "check" | "warning" | "chart" | "star";

export interface ThingView {
  kind: ThingKind;
  /** "Went well", "One to work on", "Progress", or "Goal reached" / "2 goals reached" (the celebration). */
  heading: string;
  /** The server's sentence (its simple wording for simple-wording drivers); "-" when there is none. */
  text: string;
  /** Evidence line ("Seen on 9 of 9 laps compared with your reference"), or the reason the item is empty. */
  evidence: string | null;
  tone: ThingTone;
  icon: ThingIcon;
  /** Null when the server had nothing for this slot (text "-", `evidence` says why). */
  source: ThingSource | null;
  empty: boolean;
  /** For links: the learned corner, the lap it was seen on, the goal it is about, the observation's `corner:kind`. */
  corner: string | null;
  lapId: number | null;
  lapNumber: number | null;
  goalId: number | null;
  observationKey: string | null;
}

export interface ThingsView {
  items: [ThingView, ThingView, ThingView];
  /** The server's flags: the card shows SYNTHETIC / REPLAY chips. */
  synthetic: boolean;
  replay: boolean;
  /** The observation the "One to work on" item shows (Review hides it from its Work on list). */
  workOnKey: string | null;
}

/** The work-on item's label where other "what to work on" answers sit beside it (Review's Summary and Coaching): it
 * says which question it answers, so a different corner elsewhere (the last lap, the radio's plan) is not a
 * contradiction (integration plan 5.1). */
export const WORK_ON_SESSION_HEADING = "One to work on (this session)";

const BASE: Readonly<Record<ThingKind, { heading: string; tone: ThingTone; icon: ThingIcon }>> = {
  went_well: { heading: "Went well", tone: "success", icon: "check" },
  work_on: { heading: "One to work on", tone: "warning", icon: "warning" },
  progress: { heading: "Progress", tone: "neutral", icon: "chart" },
};

const ORDER: readonly ThingKind[] = ["went_well", "work_on", "progress"];
/** A goal reached comes first: the radio celebrates before it coaches, and so does the card (on a phone it is the
 * one item above the fold). */
const CELEBRATION_ORDER: readonly ThingKind[] = ["progress", "went_well", "work_on"];

function thingView(kind: ThingKind, item: ThingItem | null, why: string | null, simple: boolean): ThingView {
  const base = BASE[kind];
  if (!item) {
    return {
      kind,
      ...base,
      text: "-",
      evidence: why,
      source: null,
      empty: true,
      corner: null,
      lapId: null,
      lapNumber: null,
      goalId: null,
      observationKey: null,
    };
  }
  const reached = kind === "progress" && item.source === "goal_reached";
  const text = (simple && item.text_simple ? item.text_simple : item.text) || "-";
  const n = typeof item.values?.goals === "number" ? item.values.goals : 1;
  return {
    kind,
    heading: reached ? (n > 1 ? `${n} goals reached` : "Goal reached") : base.heading,
    tone: reached ? "success" : base.tone,
    icon: reached ? "star" : base.icon,
    text,
    evidence: item.evidence,
    source: item.source,
    empty: false,
    corner: item.corner,
    lapId: item.lap_id,
    lapNumber: item.lap_number,
    goalId: item.goal_id,
    observationKey: item.observation_key,
  };
}

/** The three items of a recap, in the order went well, work on, progress (a goal reached: progress first). `simple`
 * = the reader's wording (Review: the viewed driver's density; Drive: the recap's own `simple`). `sessionLabel`: the
 * work-on item reads WORK_ON_SESSION_HEADING (Review's Summary). */
export function thingsView(r: SessionRecap, simple: boolean, opts: { sessionLabel?: boolean } = {}): ThingsView {
  const order = r.things?.progress?.source === "goal_reached" ? CELEBRATION_ORDER : ORDER;
  const items = order.map((k) => {
    const v = thingView(k, r.things?.[k] ?? null, r.why_empty?.[k] ?? null, simple);
    return k === "work_on" && opts.sessionLabel ? { ...v, heading: WORK_ON_SESSION_HEADING } : v;
  }) as [ThingView, ThingView, ThingView];
  return {
    items,
    synthetic: r.synthetic,
    replay: r.replay,
    workOnKey: r.things?.work_on?.source === "observation" ? (r.things.work_on.observation_key ?? null) : null,
  };
}

/** Badges earned in a session as chip words, newest first. */
export function badgeWords(badges: readonly Badge[] | null | undefined, simple: boolean): string[] {
  return [...(badges ?? [])]
    .sort((a, b) => b.earned_unix - a.earned_unix)
    .map((b) => (simple && b.title_simple ? b.title_simple : b.title));
}
