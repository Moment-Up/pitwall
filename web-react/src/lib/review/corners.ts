// Corner identity for Review (spec 0.4, 13): official labels and names come from the track model
// (`corners[].label / display_name`, from the verified track sheets via analysis/track_identity.py); a corner the
// sheet does not map keeps Pitwall's learned name. Names are data: the UI never invents or parses them.

import type { ReviewCorner, ReviewTrackModel } from "../endpoints/review";

export interface CornerIdentity {
  /** The learned corner name (the key of observations, comparisons and corner_summary). */
  key: string;
  /** Official short label ("T15", "T10-13"), else the sheet's short text, else the learned name. */
  label: string;
  /** Official name ("Stowe"), or null. */
  name: string | null;
  /** "T15 Stowe" or "T15". */
  full: string;
  /** How people call it in a sentence: the official name, else the label ("Stowe", "T3"). */
  spoken: string;
  apexM: number | null;
  entryM: number | null;
  exitM: number | null;
}

export function cornerOf(model: ReviewTrackModel | null | undefined, key: string): ReviewCorner | null {
  return model?.corners.find((c) => c.name === key) ?? null;
}

/** Identity of a learned corner; `fallbackLabel` (an observation's own `corner_label`) is used when the model is
 * missing. */
export function cornerIdentity(
  model: ReviewTrackModel | null | undefined,
  key: string,
  fallbackLabel?: string | null,
): CornerIdentity {
  const c = cornerOf(model, key);
  const label = c?.label?.trim() || model?.corner_text?.[key]?.short?.trim() || fallbackLabel?.trim() || key;
  const name = c?.display_name?.trim() || null;
  return {
    key,
    label,
    name,
    full: name ? `${label} ${name}` : label,
    spoken: name ?? label,
    apexM: c ? c.apex_m : null,
    entryM: c ? c.entry_m : null,
    exitM: c ? c.exit_m : null,
  };
}
