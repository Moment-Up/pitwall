// The Session complete card says each fact once (integration plan 2.6, walk finding 2). Pure; tested in plain node.
//
// The Imola walk showed one new record four times: the Best lap tile's REC tag, "To the family record: REC, this
// session set it", "Your first clean laps at Imola …" under Progress and a "First clean lap at Imola" badge. Each fact
// now has a key and is shown once, by the first of these slots that has it:
//
//   1 Went well          2 the Best lap tile's tag          3 the Progress item          4 a badge chip
//
// The server names the facts: the recap's things and the badges carry a `fact_key` (motivation/recap.py, badges.py):
//   pb:<lap id>                          a new personal best (Went well "New personal best …", the "First time under
//                                        1:25" and "New best in 3 sessions in a row" badges, a PB streak in Progress)
//   first_clean:<game>:<track>:<car>     the first clean laps here (Went well "First clean lap here …", Progress
//                                        "Your first clean laps at …", the "First clean lap at …" badge)
//   goal:<id>                            a goal reached (Progress, the "goals reached" badge)
//   clean_run                            a run of clean laps (Went well "10 clean laps in a row", a reached clean-laps
//                                        goal, the "N clean laps in a row" and "10 clean laps in one session" badges:
//                                        three ways of saying one session's clean run, shown once - UX review)
// The card adds what only it shows, and derives keys for an older server that sends none:
//   record:<lap id>    the Best lap tile's REC tag (a new family record: its own fact), and the "Family record at …"
//                      badge of that lap (the record of its exact family board: the same lap, said once)
//   pb:<lap id>        the tile's PB tag, and a first-ever best ("first clean lap here" is the best here too)
//   first_clean, goals_reached, pb_streak   derived from the source when there is no `fact_key` (one session per card,
//                                           so no scope is needed)
// An item's keys are the server's plus the derived ones: a slot whose keys were already shown is dropped (the tile
// keeps its time and timing colour, the row keeps its size). Badges whose keys were shown are dropped and at most
// ENDED_BADGES_MAX are shown (Review › Goals lists them all).

import type { Badge, SessionRecap, ThingKind } from "../endpoints/motivation";
import type { ThingView, ThingsView } from "../motivation/recap";
import type { TimingTag } from "./timing";

/** Badges on the Session complete card (the full list is on Review › Goals). */
export const ENDED_BADGES_MAX = 2;

/** The three things after de-duplication: the server's order, with a repeated Progress item left out. */
export type CompleteThings = Omit<ThingsView, "items"> & { items: readonly ThingView[] };

/** The server's fact key on a recap thing or a badge (newer servers; absent before). */
type WithFact = { fact_key?: string | null };

export interface CompleteInput {
  /** The recap's three things (lib/motivation/recap.ts thingsView), or null (no recap: nothing to de-duplicate). */
  things: ThingsView | null;
  /** The server's fact key per thing (the recap's `things[kind].fact_key`), when it sends them. */
  facts?: Partial<Record<ThingKind, string | null | undefined>>;
  /** The Best lap tile's tag and the lap that set it. */
  best: { tag: TimingTag | null; lapId: number | null } | null;
  /** Badges this session earned, newest first (the recap's `badges_earned`). */
  badges: readonly Badge[];
}

export interface CompleteView {
  things: CompleteThings | null;
  /** The Best lap tile shows its REC / PB tag (false: Went well already said it). */
  bestTag: boolean;
  /** At most ENDED_BADGES_MAX, none repeating a fact above. */
  badges: Badge[];
  /** Every key shown, in slot order (tests and debugging). */
  shown: string[];
}

/** The server's fact keys of a recap's things (`fact_key`), by kind. */
export function recapFacts(r: SessionRecap | null | undefined): CompleteInput["facts"] {
  const t = r?.things;
  const key = (x: unknown): string | null => {
    const k = (x as WithFact | null | undefined)?.fact_key;
    return typeof k === "string" && k ? k : null;
  };
  return { went_well: key(t?.went_well), work_on: key(t?.work_on), progress: key(t?.progress) };
}

/** The fact keys of a Went well or Progress item: the server's (`server`) plus the ones derived from its source. */
export function thingKeys(t: ThingView, server?: string | null): string[] {
  if (t.empty) return [];
  const lap = t.lapId != null ? [`pb:${t.lapId}`] : [];
  const source: string = t.source ?? "";
  let derived: string[];
  switch (source) {
    case "pb":
      derived = lap;
      break;
    case "first_clean": // Went well: the first clean laps here, which are the best here too
      derived = ["first_clean", ...lap];
      break;
    case "first_session":
      derived = ["first_clean"];
      break;
    case "goal_reached":
      derived = [...(t.goalId != null ? [`goal:${t.goalId}`] : []), "goals_reached", ...(t.goalKind === "clean_streak" ? ["clean_run"] : [])];
      break;
    case "clean_streak":
      derived = ["clean_run"];
      break;
    case "pb_streak":
      derived = ["pb_streak"];
      break;
    default:
      derived = [];
  }
  return server ? [server, ...derived.filter((k) => k !== server)] : derived;
}

/** The Best lap tile tag's key: REC = a new family record, PB = a new personal best (this session set it). */
export function tagKey(best: CompleteInput["best"]): string | null {
  if (!best || best.lapId == null) return null;
  if (best.tag === "REC") return `record:${best.lapId}`;
  if (best.tag === "PB") return `pb:${best.lapId}`;
  return null;
}

/** The fact keys a badge earned this session repeats: the server's `fact_key` plus the ones derived from its kind. */
export function badgeKeys(b: Badge): string[] {
  const server = (b as Badge & WithFact).fact_key;
  let derived: string[];
  switch (b.kind) {
    case "first_clean_lap":
      derived = ["first_clean"];
      break;
    case "pb_streak":
      derived = ["pb_streak"];
      break;
    case "goals_reached":
      derived = ["goals_reached"];
      break;
    case "clean_streak":
    case "ten_clean_session":
      derived = ["clean_run"];
      break;
    case "family_record": // the lap that holds the board's record: the tile's REC tag when it is that lap
      derived = b.lap_id != null ? [`record:${b.lap_id}`] : [];
      break;
    default:
      derived = [];
  }
  return typeof server === "string" && server ? [server, ...derived.filter((k) => k !== server)] : derived;
}

/** Each fact once, in slot order: Went well, the Best lap tag, Progress, badges (plan 2.6). */
export function dedupeComplete(input: CompleteInput): CompleteView {
  const shown: string[] = [];
  const seen = new Set<string>();
  const claim = (keys: readonly string[]): boolean => {
    if (keys.some((k) => seen.has(k))) return false;
    for (const k of keys) {
      seen.add(k);
      shown.push(k);
    }
    return true;
  };
  const items = input.things?.items ?? [];
  const well = items.find((t) => t.kind === "went_well");
  if (well) claim(thingKeys(well, input.facts?.went_well));
  const tk = tagKey(input.best);
  const bestTag = tk == null || claim([tk]);
  const progress = items.find((t) => t.kind === "progress");
  const progressKeys = progress ? thingKeys(progress, input.facts?.progress) : [];
  // a goal reached is never dropped (the celebration): it only claims what Went well has not said yet
  const keepProgress =
    !progress || (progress.source === "goal_reached" ? (claim(progressKeys.filter((k) => !seen.has(k))), true) : claim(progressKeys));
  const badges: Badge[] = [];
  for (const b of input.badges) {
    if (badges.length >= ENDED_BADGES_MAX) break;
    const keys = badgeKeys(b);
    if (keys.some((k) => seen.has(k))) continue;
    claim(keys);
    badges.push(b);
  }
  const things: CompleteThings | null = input.things
    ? { ...input.things, items: items.filter((t) => t !== progress || keepProgress) }
    : null;
  return { things, bestTag, badges, shown };
}
