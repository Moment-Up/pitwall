// Track knowledge for the map (ported from web/src/lib/TrackMap.svelte and web/src/lib/api.ts, commit 0d5fec1). Pure:
// the wire types, the rules for what may be drawn, and plain-words titles. The drawing is lib/viz/track-map.ts.
//
// Wire shape of TrackKnowledge.to_dict() (src/pitwall/core/track_knowledge.py), sent in /ws/live snapshots at the
// static cadence (every ~5 s, like track_model and skeleton). Layers: L3 learned (the driver's own laps) > L0b
// field_observed (the AI field of THIS session) > L1c physics_predicted (severity only). Everything with tier
// "field_observed" is an AI reference: never the driver's line, never their braking point, never a target. Every
// read here is defensive (optional chaining, finite checks): a field that is missing or not a number draws nothing.

import { grouped, metres } from "../format";
import { finite, positive } from "./scale";

export const TIER_FIELD = "field_observed";

export interface KnowledgeZone {
  /** Learned corner ("T3"), provisional field corner ("F2") or "zone@<onset>". */
  key: string;
  /** Official label from the track sheet. */
  label: string | null;
  /** The AI field's median braking onset (game metres). */
  onset_m: number | null;
  profile_onset_m?: number | null;
  /** Conservative early point (onset - uncertainty). */
  heads_up_m: number | null;
  uncertainty_m?: number | null;
  end_m?: number | null;
  entry_speed_kph: number | null;
  min_speed_kph: number | null;
  min_speed_m: number | null;
  peak_brake?: number | null;
  severity?: "heavy" | "medium" | "light";
  /** Car-laps that braked here. */
  support: number;
  cars: number;
  onset_q25_m?: number | null;
  onset_q75_m?: number | null;
  spread_m?: number | null;
  corner?: string | null;
  complete?: boolean;
  /** "learned" when a learned corner's braking covers the zone (the driver's own data wins). */
  superseded_by: "learned" | null;
  tier: string;
  source?: string;
}

export interface KnowledgeCorner {
  key: string;
  name: string;
  label: string | null;
  text: { short: string; long: string; voice: string | null } | null;
  apex_m: number | null;
  entry_m?: number | null;
  exit_m?: number | null;
  min_speed_kph?: number | null;
  direction?: string | null;
  tier: string;
  source?: string;
}

export interface FieldLayerInfo {
  tier: string;
  source?: string;
  available: boolean;
  version: number | null;
  car_laps: number;
  cars: number;
  coverage: number;
  braking_zones: number;
  heads_up: number;
  min_support: number;
  brake_envelope?: unknown;
  counts?: Record<string, number>;
}

export interface TrackKnowledge {
  game: string | null;
  track_id: string | null;
  track_name: string | null;
  track_length_m: number | null;
  session_uid: string | null;
  synthetic: boolean;
  /** Bumped by the resolver on every input change (per server process). */
  version: number;
  positions: "learned" | "field_observed" | "physics_predicted" | null;
  layers: {
    L3?: { tier: string; available: boolean; version: number | null; n_laps: number | null; corners: number };
    L0b?: FieldLayerInfo;
    L1c?: { tier: string; available: boolean; source: string | null; severity_tags: number };
  };
  corners: KnowledgeCorner[];
  braking_zones: KnowledgeZone[];
  heads_up?: unknown[];
  severity_tags?: unknown[];
  /** The learned centreline once it covers the lap, else the field's median line (unknown bins [null, null]). */
  line: { tier: string; source?: string; step_m: number; points: [number | null, number | null][] } | null;
  speed_profile?: unknown;
}

type Pt = [number, number];

/**
 * The AI field's median line (layer L0b), one point per bin; null where the field has no data yet, so a path breaks
 * there (no chord across track nobody has driven). Empty unless the line is the field's own (a learned line in the
 * knowledge is the model's, which the map already has).
 */
export function fieldLinePoints(k: TrackKnowledge | null | undefined): (Pt | null)[] {
  const line = k?.line;
  if (!line || line.tier !== TIER_FIELD || !Array.isArray(line.points)) return [];
  return line.points.map((p): Pt | null => (p && finite(p[0]) && finite(p[1]) ? [p[0], p[1]] : null));
}

/**
 * Knowledge may be drawn with this model: never across tracks (the resolver ignores a model of another track, and a
 * synthetic replay's `synthetic:` track id never matches a real one). Unknown ids on either side do not block it.
 */
export function knowledgeMatches(
  model: { game?: string | null; track_id?: string | null } | null | undefined,
  k: TrackKnowledge | null | undefined,
): boolean {
  if (!k) return false;
  if (model?.track_id && k.track_id && model.track_id !== k.track_id) return false;
  if (model?.game && k.game && model.game !== k.game) return false;
  return true;
}

/** The field's braking zones a learned corner does not cover, with a drawable onset -> slowest point. */
export function fieldZones(k: TrackKnowledge | null | undefined): KnowledgeZone[] {
  return (k?.braking_zones ?? []).filter((z) => z && z.superseded_by == null && finite(z.onset_m) && finite(z.min_speed_m));
}

/** Support needed before a heads-up point is drawn (L0b.min_support); null when unknown (then none is drawn). */
export function minSupport(k: TrackKnowledge | null | undefined): number | null {
  const v = k?.layers?.L0b?.min_support;
  return finite(v) && v >= 1 ? v : null;
}

/** Plain-words title of one field zone: an AI reference, never the driver's braking point. */
export function fieldZoneTitle(z: KnowledgeZone): string {
  const speeds =
    finite(z.entry_speed_kph) && finite(z.min_speed_kph)
      ? `, ${Math.round(z.entry_speed_kph)} → ${Math.round(z.min_speed_kph)} km/h`
      : "";
  return (
    `${z.label ?? z.key}: AI field brakes from ${metres(z.onset_m, 1)} (${grouped(z.support)} car-laps, ${grouped(z.cars)} cars)` +
    `${speeds}. AI reference, not your braking point.`
  );
}

/** Title of the field's median line. */
export function fieldLineTitle(k: TrackKnowledge | null | undefined): string {
  const n = k?.layers?.L0b?.car_laps;
  const laps = finite(n) ? ` (${grouped(n)} car-laps)` : "";
  return `AI field median line${laps}: an AI reference, not your line`;
}

/** The field corners to mark while the field's line is drawn (field tier, known apex). */
export function fieldCorners(k: TrackKnowledge | null | undefined): KnowledgeCorner[] {
  return (k?.corners ?? []).filter((c) => c && c.tier === TIER_FIELD && finite(c.apex_m));
}

/** A field corner's label: official label, else the sheet's short text, else its key. */
export function fieldCornerLabel(c: KnowledgeCorner): string {
  return c.label || c.text?.short || c.key;
}

/**
 * "AI reference: 12 cars, 140 car-laps, 9 heads-ups" (the Svelte LiveView's line) while the field layer is available;
 * null otherwise. For a tile caption next to the map.
 */
export function fieldReferenceText(k: TrackKnowledge | null | undefined): string | null {
  const l = k?.layers?.L0b;
  if (!l?.available) return null;
  return `AI reference: ${grouped(l.cars)} cars, ${grouped(l.car_laps)} car-laps, ${grouped(l.heads_up)} heads-ups`;
}

/** The game lap length the knowledge's metres use, or null. */
export function knowledgeLengthM(k: TrackKnowledge | null | undefined): number | null {
  return positive(k?.track_length_m);
}
