// Drive › Track (design spec 5.2; mockup driveTrack): pure view models for the corner list and the large map. For
// learning a new track in practice: every corner with its official label and long name, its direction, FOCUS, and
// what the coach said about it on the last lap, verbatim (P9). No React; tested in plain node. Lane DV.

import { comparePath } from "../../../lib/review/links";
import { lapPicks, pointText, simpleWording } from "../../../lib/drive/coach";
import { cornerAhead, focusReasonOf } from "../../../lib/drive/corner";
import { gameLength } from "../../../lib/drive/geometry";
import type { DriveModel } from "../../../lib/drive/model";
import { finite } from "../../../lib/drive/text";
import type { CornerNext, ObservationNext, SnapshotNext } from "../../../lib/drive/types";
import { worldXZ } from "../../../lib/viz/track-map";
import { liveValues } from "../car/view";

export interface CornerNote {
  /** Verbatim: the full text (text_simple for plain-wording profiles); the Track page is read when stopped. */
  text: string;
  lap: number | null;
  good: boolean;
}

export interface CornerRow {
  /** Learned name: the key of cues, observations and the map. */
  name: string;
  /** Official label ("T15", "T10-13"), else the sheet's short text, else the learned name. */
  label: string;
  /** Official name ("Stowe"), else the sheet's long text; null for a corner without a sheet name. */
  title: string | null;
  /** "left" / "right"; null for complexes and unknown (no word, as on Coach). */
  direction: "left" | "right" | null;
  focus: boolean;
  focusReason: string | null;
  note: CornerNote | null;
  /** The live car's next corner ("next") or the one it is in ("in"). */
  live: "next" | "in" | null;
  /** Review › Compare at this corner on the last compared lap; null when there is nothing to compare. */
  compareHref: string | null;
}

export interface TrackView {
  rows: CornerRow[];
  /** Why the list is empty. */
  empty: string | null;
  /** The live corner (learned name). */
  liveCorner: string | null;
  focus: string[];
  cueTargetsM: number[];
  car: [number, number] | null;
  carM: number | null;
  flags: { game_number: number; flag: string }[] | null;
  /** "14 corners · official names". */
  caption: string;
}

function byApex(corners: readonly CornerNext[]): CornerNext[] {
  return [...corners].filter((c) => finite(c.apex_m)).sort((a, b) => a.apex_m - b.apex_m);
}

/** What the coach said about each corner on the last lap: D6's per-corner point, else the top observation there. */
function notesByCorner(s: SnapshotNext): Map<string, ObservationNext> {
  const out = new Map<string, ObservationNext>();
  if (s.coach) {
    for (const [corner, o] of Object.entries(s.coach.by_corner)) if (o.kind !== "incident") out.set(corner, o);
    return out;
  }
  for (const o of lapPicks(s).picks) if (!out.has(o.corner)) out.set(o.corner, o);
  return out;
}

/** The lap a corner's note is about, for Compare: D6's lap id, else the laps[] entry with that number. */
function noteLapId(s: SnapshotNext, o: ObservationNext | undefined): number | null {
  if (s.coach?.lap_id != null && (!o || o.lap_number === s.coach.lap_number)) return s.coach.lap_id;
  const n = o?.lap_number ?? s.laps.find((l) => l.clean)?.lap_number;
  const lap = n != null ? s.laps.find((l) => l.lap_number === n) : undefined;
  return lap?.lap_id ?? null;
}

export function trackView(s: SnapshotNext | null, model: Pick<DriveModel, "dim" | "state">, profileSimple: boolean): TrackView {
  const live = liveValues(model);
  const tm = s?.track_model ?? null;
  const corners = tm ? byApex(tm.corners) : [];
  const official = corners.some((c) => c.identity_tier || c.label || c.display_name);
  const caption = corners.length
    ? `${corners.length} ${corners.length === 1 ? "corner" : "corners"}${official ? " · official names" : " learned"}`
    : "Learning the track";
  const ahead = live && s ? cornerAhead(tm, s.frame?.lap_distance_m, gameLength(s), s.cues) : null;
  const simple = s ? simpleWording(s, profileSimple) : profileSimple;
  const notes = s ? notesByCorner(s) : new Map<string, ObservationNext>();
  const sessionId = s?.session_id ?? null;
  const refId = s?.reference?.lap_id ?? null;
  const rows = corners.map((c): CornerRow => {
    const o = notes.get(c.name);
    const label = c.label || tm?.corner_text?.[c.name]?.short || c.name;
    const long = tm?.corner_text?.[c.name]?.long ?? null;
    const title = c.display_name || (long && long !== label ? long : null);
    const lapId = s ? noteLapId(s, o) : null;
    const focus = !!s?.cues?.focus.includes(c.name);
    return {
      name: c.name,
      label,
      title,
      direction: c.direction === "left" || c.direction === "right" ? c.direction : null,
      focus,
      focusReason: focus ? focusReasonOf(s?.cues, c.name) : null,
      note: o ? { text: pointText(o, simple, false), lap: finite(o.lap_number) ? o.lap_number : null, good: o.positive } : null,
      live: ahead?.name === c.name ? ahead.phase : null,
      compareHref:
        sessionId && refId != null && lapId != null && lapId !== refId
          ? comparePath(sessionId, { ref: refId, lap: lapId, at: c.apex_m })
          : null,
    };
  });
  const d = s?.frame?.lap_distance_m;
  return {
    rows,
    empty: corners.length ? null : "The corners appear after your first clean lap.",
    liveCorner: ahead?.name ?? null,
    focus: [...(s?.cues?.focus ?? [])],
    cueTargetsM: (s?.cues?.cues ?? []).map((c) => c.target_m).filter(finite),
    car: live ? worldXZ(s?.frame?.pos) : null,
    carM: live && finite(d) ? d : null,
    flags: live ? (s?.marshal_flags ?? null) : null,
    caption,
  };
}
