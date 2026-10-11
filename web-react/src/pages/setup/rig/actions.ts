// What a rig write refreshes (spec 12.3: a successful mutation invalidates its own prefix). The answer of the write is
// put in the cache at once, so the page shows it before the refetches land.

import { cache } from "../../../lib/cache";
import { RIG_KEYS, type DriverPrefsResponse, type RigProfile } from "../../../lib/endpoints/rig";

/** The rig changed (hardware, an upgrade): every recommendation, rig check and effective force scale depends on it. */
export function rigChanged(p: RigProfile): void {
  cache.set(RIG_KEYS.profile, p);
  cache.invalidate("rig:recommendations:");
  cache.invalidate("rig:check:");
  cache.invalidate("rig:prefs:");
}

/** A driver's style or force scale changed: their recommendations follow. */
export function prefsChanged(driverId: number, prefs: DriverPrefsResponse): void {
  cache.set(RIG_KEYS.prefs(driverId), prefs);
  cache.invalidate("rig:recommendations:");
}
