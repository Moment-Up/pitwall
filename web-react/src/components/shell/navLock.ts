// Drive while on track (spec 3.3): the rail dims, and with the Drive lock leaving Drive › Coach needs a 0.5 s hold.
//
// "On track" is the Drive state `on_track` (4.7). The Drive pages own that state (lib/drive/state.ts): they publish
// it here with navLock.publishOnTrack(state === "on_track") and publishOnTrack(null) on unmount. Until a Drive page
// publishes, the shell uses the 3.3 definition directly: telemetry live and pit_status == 0.
//
// A short tap on a locked item shows the 2 s hint "Hold to leave Drive while driving" in the Drive status slot
// (DriveStatusSlot renders it; no toast).

import type { Snapshot } from "../../lib/api";
import type { AreaId } from "../../lib/route-parse";
import { Store } from "../../lib/store";

export const LOCK_HOLD_MS = 500;
export const LOCK_HINT_MS = 2000;
export const LOCK_HINT_TEXT = "Hold to leave Drive while driving";
/** A touch on the dimmed rail restores it for this long. */
export const NAV_WAKE_MS = 5000;

/** Spec 3.3 fallback: telemetry live (and the dashboard's socket up) with the car on track (pit_status 0). */
export function onTrackFallback(snap: Snapshot | null, connected: boolean): boolean {
  return connected && snap?.connection.status === "live" && snap.frame?.pit_status === 0;
}

/**
 * The one rule every nav item uses (rail, tab bar, Drive Segment), so they cannot disagree: while the lock applies,
 * going anywhere but Drive › Coach needs the 0.5 s hold. `page` undefined = the area's landing page.
 */
export function holdNeeded(lock: { locked: boolean }, area: AreaId, page?: string): boolean {
  return lock.locked && !(area === "drive" && (page === undefined || page === "coach"));
}

export interface NavLockState {
  /** The Drive page's own on-track verdict; null = none published (use the fallback). */
  published: boolean | null;
  /** The lock hint is showing. */
  hint: boolean;
}

class NavLockStore extends Store<NavLockState> {
  private hintTimer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    super({ published: null, hint: false });
  }

  /** Drive pages: publish whether the Drive state is on_track; null when the page unmounts. */
  publishOnTrack(onTrack: boolean | null): void {
    this.set({ published: onTrack });
  }

  /** Show "Hold to leave Drive while driving" for 2 s (a short tap on a locked item). */
  showHint(): void {
    if (this.hintTimer) clearTimeout(this.hintTimer);
    this.set({ hint: true });
    this.hintTimer = setTimeout(() => {
      this.hintTimer = null;
      this.set({ hint: false });
    }, LOCK_HINT_MS);
  }

  clearHint(): void {
    if (this.hintTimer) clearTimeout(this.hintTimer);
    this.hintTimer = null;
    this.set({ hint: false });
  }
}

export const navLock = new NavLockStore();
