// What every Drive page does besides drawing (design spec 3.3, 3.4). Lane DV.
//
//  * Drive lock: publishes whether the Drive state is on_track (lib/drive state, not the shell's fallback), so the
//    rail dims and leaving Drive › Coach needs the 0.5 s hold exactly when Drive says the car is on track.
//  * Screen wake lock while a session is open on any Drive page (lib/wake.ts driveWakeWanted): while telemetry is
//    live and for up to 10 min after the last live moment, so a game pause, menus, loading, a flashback or a socket
//    flap never lets iPad Auto-Lock turn the screen off mid-session. A release waits 5 s (a flap never drops the lock).
//    "Screen may sleep" when the browser refuses it.
//  * Space = push-to-talk on a Mac while the radio is live; a learned Bluetooth talk button too (lane handsfree).
// Switching between Drive pages keeps the wake lock: it is let go only when no Drive page is mounted.

import { useEffect } from "react";
import { usePushToTalkKey, useRadio, useTalkButton } from "../../components/radio";
import { navLock } from "../../components/shell/navLock";
import { useStore } from "../../hooks/stores";
import type { DriveModel } from "../../lib/drive/model";
import { driveWakeWanted, screenMaySleep, screenWake, WAKE_RELEASE_DELAY_MS } from "../../lib/wake";

let mountedDrivePages = 0;
/** Device clock (ms) of the last moment telemetry was live on a Drive page (shared by the Drive pages). */
let lastLiveMs: number | null = null;
let releaseTimer: ReturnType<typeof setTimeout> | null = null;

function cancelRelease(): void {
  if (releaseTimer) clearTimeout(releaseTimer);
  releaseTimer = null;
}

/** Keep the screen on now, or let it go after `delayMs` unless a Drive page wants it again before then. */
function wantWake(want: boolean, delayMs = WAKE_RELEASE_DELAY_MS): void {
  if (want) {
    cancelRelease();
    screenWake.want(true);
    return;
  }
  if (releaseTimer || !screenWake.get().wanted) return;
  releaseTimer = setTimeout(() => {
    releaseTimer = null;
    screenWake.want(false);
  }, delayMs);
}

/** Returns whether the status slot shows "Screen may sleep". */
export function useDriveEffects(model: Pick<DriveModel, "onTrack" | "telemetryLive" | "state">): boolean {
  const { onTrack, telemetryLive } = model;
  const noTelemetry = model.state === "no_data";

  useEffect(() => {
    navLock.publishOnTrack(onTrack);
  }, [onTrack]);
  useEffect(() => () => navLock.publishOnTrack(null), []);

  useEffect(() => {
    mountedDrivePages += 1;
    return () => {
      mountedDrivePages -= 1;
      // Let the next Drive page claim it first (page switch), then release at once if none did (Drive was left).
      setTimeout(() => {
        if (mountedDrivePages === 0) {
          cancelRelease();
          screenWake.want(false);
        }
      }, 0);
    };
  }, []);

  useEffect(() => {
    if (telemetryLive) {
      lastLiveMs = Date.now();
      wantWake(true);
      // The last live moment is when it stops being live (or this page closes while live).
      return () => {
        lastLiveMs = Date.now();
      };
    }
    const d = driveWakeWanted({ telemetryLive, noTelemetry, lastLiveMs, nowMs: Date.now() });
    wantWake(d.want);
    if (d.untilMs == null) return;
    // The hold ends by itself 10 min after the last live moment (the game was closed, nobody is driving).
    const t = setTimeout(() => wantWake(false, 0), d.untilMs);
    return () => clearTimeout(t);
  }, [telemetryLive, noTelemetry]);

  const radioLive = useRadio((s) => s.phase === "live");
  usePushToTalkKey(radioLive);
  useTalkButton(radioLive); // --- hands-free (lane handsfree): the learned Bluetooth talk button, like Space

  return useStore(screenWake, screenMaySleep);
}
