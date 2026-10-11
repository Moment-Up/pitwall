// Track skeleton types and helpers, ported from the module script of web/src/lib/SectorBands.svelte.
//
// Wire shape of `TrackSkeleton.to_dict()` (src/pitwall/analysis/track_skeleton.py): the game's own sector
// boundaries and zones (layer L0a), in metres of lap distance. `null` = not reported (e.g. format 2025 has no
// DRS/aero tables); `[]` = the game reported zero zones. Zones with `wraps` run through the start/finish line;
// `segments_m` holds the 1-2 non-wrapping pieces to draw.
// Zones are named by `game_number` (the game's index + 1), the numbering flags and race control use; `lap_order`
// (order of starts from the line) is never shown as a name. Marshal `flag`s are live state: they are only drawn
// when the caller says the skeleton is the live one; stored sessions send them as null anyway.

export interface SkeletonZone {
  kind: "marshal" | "drs" | "aero_full" | "aero_partial";
  index: number; // the game's array index
  game_number: number; // index + 1: the zone's name ("Marshal zone 1", "DRS 1")
  lap_order: number; // 1-based order of starts from the line (drawing / tooltips only)
  start_m: number;
  end_m: number;
  length_m: number;
  start_frac: number;
  end_frac: number;
  wraps: boolean;
  segments_m: [number, number][];
  flag: string | null; // marshal zones only: "none" | "green" | "blue" | "yellow" | null
}

export interface SkeletonSector {
  index: number;
  name: string;
  start_m: number;
  end_m: number;
  length_m: number;
}

export interface TrackSkeleton {
  tier: string; // evidence tier: "game_native" | "synthetic" (generated, never game data)
  synthetic: boolean;
  source: string | null;
  game: string | null;
  track_id: string | null;
  track_length_m: number | null;
  pit_speed_limit_kph: number | null;
  sector2_start_m: number | null;
  sector3_start_m: number | null;
  sector_boundaries_m: number[] | null;
  sectors: SkeletonSector[] | null;
  marshal_zones: SkeletonZone[] | null;
  drs_zones: SkeletonZone[] | null;
  aero_full_zones: SkeletonZone[] | null;
  aero_partial_zones: SkeletonZone[] | null;
  active_aero_track_status: string | null;
}

/**
 * Sector band fills: three NEUTRAL grey steps (styles/tokens.css --pw-sector-1..3, design spec v2 9.2). Sector
 * identity is never a colour: the broadcast S1 red / S2 blue / S3 yellow clashed with red = behind and yellow =
 * slower / yellow flag, so sectors are told apart by their labels (S1 S2 S3). Labels drawn on a band use
 * --foreground (4.5:1 on every step in every mode; --muted only reaches 3:1).
 */
export const SECTOR_COLOUR_VARS = ["var(--pw-sector-1)", "var(--pw-sector-2)", "var(--pw-sector-3)"] as const;
/** Label ink for text drawn on a sector band. */
export const SECTOR_LABEL_VAR = "var(--foreground)";
/** Zone strokes: DRS dashed in the ahead green (mockup), active-aero in the reference blue (never purple: purple
 *  means timing only), yellow marshal zones hatched in the flag yellow. */
export const ZONE_COLOUR_VARS = {
  drs: "var(--pw-zone-drs)",
  aero: "var(--pw-zone-aero)",
  yellow: "var(--pw-flag-yellow)",
} as const;

/** The sector band fill for a 0-based sector index; null when the index is unknown or out of range. */
export function sectorColourVar(index: number | null | undefined): string | null {
  if (typeof index !== "number" || !Number.isInteger(index) || index < 0 || index > 2) return null;
  return SECTOR_COLOUR_VARS[index] ?? null;
}

function finite(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/**
 * Sector-only skeleton from the legacy `session.info.sector2_start_m / sector3_start_m` keys that every stored F1
 * session already has, for when the API does not send `skeleton` yet. Same validation as the Python builder:
 * both starts strictly inside the lap and in order, otherwise unknown (null). Pass the session's `synthetic` flag
 * so generated sessions are never captioned as game data.
 */
export function legacySkeleton(lengthM: unknown, s2: unknown, s3: unknown, synthetic = false): TrackSkeleton | null {
  if (!finite(lengthM) || !finite(s2) || !finite(s3) || lengthM <= 0) return null;
  if (!(0 < s2 && s2 < s3 && s3 < lengthM)) return null;
  return {
    tier: synthetic ? "synthetic" : "game_native",
    synthetic,
    source: "legacy_session_info",
    game: null,
    track_id: null,
    track_length_m: lengthM,
    pit_speed_limit_kph: null,
    sector2_start_m: s2,
    sector3_start_m: s3,
    sector_boundaries_m: [0, s2, s3, lengthM],
    sectors: [
      { index: 0, name: "S1", start_m: 0, end_m: s2, length_m: s2 },
      { index: 1, name: "S2", start_m: s2, end_m: s3, length_m: s3 - s2 },
      { index: 2, name: "S3", start_m: s3, end_m: lengthM, length_m: lengthM - s3 },
    ],
    marshal_zones: null,
    drs_zones: null,
    aero_full_zones: null,
    aero_partial_zones: null,
    active_aero_track_status: null,
  };
}

/** The active-aero table in force: the "partial" table when the game says partial, otherwise "full". */
export function activeAeroZones(sk: TrackSkeleton | null | undefined): SkeletonZone[] | null {
  if (!sk) return null;
  return sk.active_aero_track_status === "partial" ? sk.aero_partial_zones : sk.aero_full_zones;
}

/** Vertical chart markers for the sector starts and DRS zone starts (game numbering). */
export function skeletonMarkers(sk: TrackSkeleton | null | undefined): { x: number; label: string }[] {
  if (!sk) return [];
  const out: { x: number; label: string }[] = [];
  if (sk.sectors) for (const s of sk.sectors.slice(1)) out.push({ x: s.start_m, label: s.name });
  for (const z of sk.drs_zones ?? []) out.push({ x: z.start_m, label: `DRS${z.game_number}` });
  return out;
}

const ORDINAL_SUFFIX: Record<number, string> = { 1: "st", 2: "nd", 3: "rd" };
function ordinal(n: number): string {
  const teen = n % 100 >= 11 && n % 100 <= 13;
  return `${n}${teen ? "th" : (ORDINAL_SUFFIX[n % 10] ?? "th")}`;
}

/** Tooltip / title for a zone: the game's name for it, then where it sits on the lap. */
export function zoneTitle(label: string, z: SkeletonZone, flag = false): string {
  const where = `${Math.round(z.start_m)}–${Math.round(z.end_m)} m, ${ordinal(z.lap_order)} from the line`;
  const f = flag && z.flag && z.flag !== "none" ? ` · ${z.flag} flag` : "";
  return `${label} ${z.game_number} (${where})${f}`;
}

/** Live skeleton with the per-snapshot marshal flags applied (the skeleton itself only arrives every 5 s). */
export function withLiveFlags(
  sk: TrackSkeleton | null | undefined,
  flags: { game_number: number; flag: string }[] | undefined,
): TrackSkeleton | null | undefined {
  if (!sk || !sk.marshal_zones) return sk;
  const byNumber = new Map((flags ?? []).map((m) => [m.game_number, m.flag]));
  return { ...sk, marshal_zones: sk.marshal_zones.map((z) => ({ ...z, flag: byNumber.get(z.game_number) ?? "none" })) };
}
