// Session › Corners (spec 6.6): "what keeps happening at Stowe?". Coaching grouped by corner: one card per corner with
// the session averages (corner_summary: time, brake point mean and spread, slowest speed) and every lap where the
// coach spoke there (its text verbatim, with an evidence line). Filter Work on · Went well · All; sorted by average
// time lost (Went well: most time gained first). Incident observations stay on the card, greyed, marked "not used
// for technique advice" (they are never coaching). Pure; tested in node.

import type { CornerSummaryRow, ReviewObservation, ReviewTrackModel, SessionAnalysis } from "../endpoints/review";
import { INCIDENT_KIND } from "./coaching";
import { cornerIdentity, type CornerIdentity } from "./corners";
import { evidenceLine, finite, plural } from "./words";

export type CornersFilter = "work" | "good" | "all";

export const CORNERS_FILTERS: readonly { id: CornersFilter; label: string }[] = [
  { id: "work", label: "Work on" },
  { id: "good", label: "Went well" },
  { id: "all", label: "All" },
];

export interface CornerCardObservation {
  key: string;
  lapId: number | null;
  lapNumber: number;
  kind: string;
  /** The coach's text, verbatim (`text_simple` for simple wording when D6 sends it). */
  text: string;
  positive: boolean;
  incident: boolean;
  /** "about 0.11 s a lap · confidence high" (no consistency: each row is one lap). */
  evidence: string;
}

export interface CornerCard extends CornerIdentity {
  summary: CornerSummaryRow | null;
  /** Mean time vs the reference over the compared laps, s (+ = lost); null when unknown. */
  meanTimeS: number | null;
  observations: CornerCardObservation[];
  /** Has a correction (not an incident). */
  workOn: boolean;
  /** Has a positive observation. */
  wentWell: boolean;
  /** A cue focus corner of the live plan (same track as the live session). */
  focus: boolean;
  /** The newest lap where the coach spoke here (Compare opens on it); null when nobody spoke. */
  latestLapId: number | null;
}

function cardObservation(lapId: number | null, o: ReviewObservation, simple: boolean): CornerCardObservation {
  const incident = o.kind === INCIDENT_KIND;
  return {
    key: `${lapId ?? "x"}:${o.id}`,
    lapId,
    lapNumber: o.lap_number,
    kind: o.kind,
    text: simple && o.text_simple ? o.text_simple : o.text,
    positive: o.positive,
    incident,
    evidence: incident ? "" : evidenceLine({ impactS: o.impact_s, confidence: o.confidence }),
  };
}

/** Every corner of the session (the summary's, plus any the coach spoke about), sorted by average time lost. */
export function cornerCards(
  analysis: Pick<SessionAnalysis, "corner_summary" | "observations"> | null | undefined,
  model: ReviewTrackModel | null | undefined,
  opts: { focus?: readonly string[]; simple?: boolean } = {},
): CornerCard[] {
  if (!analysis) return [];
  const byCorner = new Map<string, CornerCardObservation[]>();
  const labels = new Map<string, string | null | undefined>();
  for (const [lapKey, list] of Object.entries(analysis.observations ?? {})) {
    const lapId = Number.isFinite(Number(lapKey)) ? Number(lapKey) : null;
    for (const o of list ?? []) {
      const arr = byCorner.get(o.corner) ?? [];
      arr.push(cardObservation(lapId, o, opts.simple === true));
      byCorner.set(o.corner, arr);
      if (!labels.has(o.corner)) labels.set(o.corner, o.corner_label);
    }
  }
  const summary = new Map((analysis.corner_summary ?? []).map((s) => [s.corner, s]));
  const keys = new Set<string>([...summary.keys(), ...byCorner.keys()]);
  const focus = new Set(opts.focus ?? []);
  const cards: CornerCard[] = [];
  for (const key of keys) {
    const obs = (byCorner.get(key) ?? []).sort((a, b) => b.lapNumber - a.lapNumber || Number(a.incident) - Number(b.incident));
    const s = summary.get(key) ?? null;
    const coaching = obs.filter((o) => !o.incident);
    cards.push({
      ...cornerIdentity(model, key, labels.get(key)),
      summary: s,
      meanTimeS: s && finite(s.mean_time_delta_s) ? s.mean_time_delta_s : null,
      observations: obs,
      workOn: coaching.some((o) => !o.positive),
      wentWell: coaching.some((o) => o.positive),
      focus: focus.has(key),
      latestLapId: coaching[0]?.lapId ?? obs[0]?.lapId ?? null,
    });
  }
  return cards.sort(byTimeLost);
}

function byTimeLost(a: CornerCard, b: CornerCard): number {
  const an = a.meanTimeS;
  const bn = b.meanTimeS;
  if (an == null && bn == null) return (a.apexM ?? 0) - (b.apexM ?? 0);
  if (an == null) return 1;
  if (bn == null) return -1;
  return bn - an || (a.apexM ?? 0) - (b.apexM ?? 0);
}

/** The cards a filter shows. Went well lists the most time gained first. */
export function filterCards(cards: readonly CornerCard[], filter: CornersFilter): CornerCard[] {
  if (filter === "work") return cards.filter((c) => c.workOn);
  if (filter === "good") {
    return cards
      .filter((c) => c.wentWell)
      .sort((a, b) => {
        if (a.meanTimeS == null || b.meanTimeS == null) return a.meanTimeS == null ? (b.meanTimeS == null ? 0 : 1) : -1;
        return a.meanTimeS - b.meanTimeS;
      });
  }
  return [...cards];
}

/** How many cards each filter shows (for the Segment and the empty states). */
export function filterCounts(cards: readonly CornerCard[]): Record<CornersFilter, number> {
  return {
    work: cards.filter((c) => c.workOn).length,
    good: cards.filter((c) => c.wentWell).length,
    all: cards.length,
  };
}

export interface AverageLine {
  label: string;
  value: string;
}

const round = (v: number) => Math.round(Math.abs(v));

/**
 * The session averages in plain words (corner_summary is lap minus reference over the compared laps), after the
 * time, which the card's header shows: "Braked · about 12 m earlier on average, spread 11 m", "Slowest speed ·
 * 126 km/h on average, 2 km/h higher than the reference".
 */
export function averageLines(s: CornerSummaryRow | null): AverageLine[] {
  if (!s) return [];
  const out: AverageLine[] = [];
  const b = s.mean_brake_point_delta_m;
  if (finite(b)) {
    const where = round(b) < 1 ? "where the reference did" : `about ${round(b)} m ${b < 0 ? "earlier" : "later"}`;
    const spread = finite(s.brake_point_std_m) ? `, spread ${round(s.brake_point_std_m)} m` : "";
    out.push({ label: "Braked", value: `${where} on average${spread}` });
  }
  const ref = s.ref_min_speed_kph;
  const d = s.mean_min_speed_delta_kph;
  if (finite(ref) && finite(d)) {
    const diff = round(d) < 1 ? "the same as the reference" : `${round(d)} km/h ${d < 0 ? "lower" : "higher"} than the reference`;
    out.push({ label: "Slowest speed", value: `${Math.round(ref + d)} km/h on average, ${diff}` });
  } else if (finite(d)) {
    out.push({ label: "Slowest speed", value: round(d) < 1 ? "the same as the reference" : `${round(d)} km/h ${d < 0 ? "lower" : "higher"} than the reference` });
  }
  return out;
}

/** The card's time line: "About 0.41 s a lap lost here, average of 9 laps" (words) or "+0.41 s a lap, average of 9
 * laps" (signed, non-beginners); null without a summary. */
export function averageTimeText(s: CornerSummaryRow | null, signed: boolean): string | null {
  if (!s || !finite(s.mean_time_delta_s)) return null;
  const t = s.mean_time_delta_s;
  const laps = finite(s.laps) && s.laps > 0 ? `, average of ${plural(s.laps, "lap")}` : "";
  if (Math.abs(t) < 0.005) return `Level with the reference${laps}`;
  const v = signed
    ? `${t > 0 ? "+" : "−"}${Math.abs(t).toFixed(2)} s a lap`
    : `About ${Math.abs(t).toFixed(2)} s a lap ${t > 0 ? "lost" : "gained"} here`;
  return `${v}${laps}`;
}

/** Laps where the coach spoke here, newest first ("Laps 71, 70 and 68"). */
export function lapsSpokenText(card: Pick<CornerCard, "observations">): string | null {
  const laps = [...new Set(card.observations.filter((o) => !o.incident).map((o) => o.lapNumber))];
  if (!laps.length) return null;
  if (laps.length === 1) return `Lap ${laps[0]}`;
  return `Laps ${laps.slice(0, -1).join(", ")} and ${laps[laps.length - 1]}`;
}

/** The live plan's focus corners, only when the live session is at this session's track (same game and track). */
export function liveFocusFor(
  snap: { session?: { game: string; track_id: string | null } | null; cues?: { focus?: readonly string[] } | null } | null | undefined,
  session: { game: string; track_id: string | null },
): string[] {
  const s = snap?.session;
  if (!s || !session.track_id || s.game !== session.game || s.track_id !== session.track_id) return [];
  return [...(snap?.cues?.focus ?? [])];
}

/** Coach notes shown per corner before "Show all N": 3 on a tablet or a computer, 1 on a phone (below 768 px, the
 * same condition that collapses the technique sections): three notes a corner made a phone's Corners tab 7 000 px
 * long (acceptance B7). */
export function notesShown(wide: boolean): number {
  return wide ? 3 : 1;
}

/** Corner cards shown on a phone before "Show all N corners" (most time first): with every corner open the page ran
 * past 7 000 px (acceptance B7: at most 4 000; a card is about 500 px with its one note). A tablet or a computer shows
 * them all. */
export const PHONE_CORNERS = 5;

export function cornersShown(wide: boolean, n: number, all: boolean): number {
  return wide || all ? n : Math.min(n, PHONE_CORNERS);
}
