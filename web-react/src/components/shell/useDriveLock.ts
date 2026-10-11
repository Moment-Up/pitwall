// React side of navLock.ts: whether the car is on track, whether the Drive lock applies right now, whether the rail
// dims, and whether the lock hint is showing.

import { useActiveDriver, useLive, usePrefs, useRoute, useStore } from "../../hooks/stores";
import { driveLockApplies } from "../../lib/prefs";
import { navLock, onTrackFallback } from "./navLock";

export interface DriveLockView {
  /** Drive state on_track (published by the Drive page, else the 3.3 fallback). */
  onTrack: boolean;
  /** Leaving Drive › Coach needs a 0.5 s hold now (on track, on Coach, and the lock applies to the seated driver). */
  locked: boolean;
  /** The rail dims to 55 % (on track on a Drive page, "Dim navigation on track" on). */
  dimNav: boolean;
  /** "Hold to leave Drive while driving" is showing. */
  hint: boolean;
}

export function useDriveLock(): DriveLockView {
  const route = useRoute();
  const published = useStore(navLock, (s) => s.published);
  const hint = useStore(navLock, (s) => s.hint);
  const fallback = useLive((s) => onTrackFallback(s.snap, s.connected));
  const lockPref = usePrefs((p) => p.driveLock);
  const dimPref = usePrefs((p) => p.dimNav);
  const skill = useActiveDriver()?.preferences.skill_level ?? null;
  const onDrive = route.area === "drive";
  const onTrack = onDrive && (published ?? fallback);
  return {
    onTrack,
    locked: onTrack && route.page === "coach" && driveLockApplies(lockPref, skill),
    dimNav: onTrack && dimPref,
    hint: hint && onDrive,
  };
}

export { holdNeeded } from "./navLock";
