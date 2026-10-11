// Screen wake lock while a session is open on any Drive page (design spec 3.3). Lane DV.
//
// The Drive pages say whether they want the screen kept on (driveWakeWanted below: while telemetry is live, and for
// up to 10 min after the last live packet through a game pause, menus, loading, a flashback or a socket flap; never
// before the first packet), `want(false)` otherwise or when no Drive page is open. The radio store keeps its own wake
// lock while the radio is live (lib/radio.ts); the two sentinels are independent, so either one keeps the screen on.
//
// Unverified on the rig: on iPadOS before 18.4 a Home Screen web app's request resolves but the screen still sleeps
// (WebKit bug), so "Screen may sleep" cannot show there. Check the iPad's version.
//
// Browser rules handled here:
//  * the Screen Wake Lock API exists only in secure contexts (HTTPS, localhost): over plain LAN HTTP it is
//    "unsupported" and the screen may sleep;
//  * the system releases the lock whenever the page is hidden: it is requested again when the page comes back;
//  * a request can be refused (Low Power Mode, battery saver, or a browser that wants a user gesture): it is retried
//    on the next tap anywhere on the page.
// When the lock is wanted but not held (refused or unsupported), Drive's status slot shows a "Screen may sleep" chip.
// Never throws: every browser call is guarded, so the page works the same without the API.

import { Store } from "./store";

export type WakeState = "off" | "pending" | "on" | "refused" | "unsupported";

export interface WakeLockState {
  /** A Drive page wants the screen kept on. */
  wanted: boolean;
  state: WakeState;
}

/** The subset of WakeLockSentinel used here. */
interface Sentinel {
  readonly released: boolean;
  release(): Promise<void>;
  addEventListener(type: "release", listener: () => void): void;
}

interface WakeApi {
  request(type: "screen"): Promise<Sentinel>;
}

/** Words for the status slot chip. */
export const SCREEN_MAY_SLEEP = "Screen may sleep";

function wakeApi(): WakeApi | null {
  try {
    const nav = (globalThis as { navigator?: { wakeLock?: WakeApi } }).navigator;
    return nav?.wakeLock && typeof nav.wakeLock.request === "function" ? nav.wakeLock : null;
  } catch {
    return null;
  }
}

function pageVisible(): boolean {
  try {
    return typeof document === "undefined" || document.visibilityState !== "hidden";
  } catch {
    return true;
  }
}

/** How long the screen stays on after the last live packet while a session is open (pause, menus, loading). */
export const WAKE_HOLD_AFTER_LIVE_MS = 10 * 60_000;
/** A release waits this long, so a socket flap or a server restart never drops the lock. */
export const WAKE_RELEASE_DELAY_MS = 5_000;

export interface DriveWakeInput {
  /** Telemetry live on the open socket (DriveModel.telemetryLive). */
  telemetryLive: boolean;
  /** No packet since the server started (Drive state no_data). */
  noTelemetry: boolean;
  /** Device clock (ms) of the last moment telemetry was live, or null if never on this page load. */
  lastLiveMs: number | null;
  nowMs: number;
}

/** Whether a Drive page wants the screen kept on, and in how many ms the answer turns to "no" (null = never by
 * itself). Live: yes. Stale, offline, red flag, session complete…: yes for up to 10 min after the last live moment.
 * No telemetry yet, or nothing live on this page load: no. */
export function driveWakeWanted(i: DriveWakeInput): { want: boolean; untilMs: number | null } {
  if (i.telemetryLive) return { want: true, untilMs: null };
  if (i.noTelemetry || i.lastLiveMs == null) return { want: false, untilMs: null };
  const left = i.lastLiveMs + WAKE_HOLD_AFTER_LIVE_MS - i.nowMs;
  return left > 0 ? { want: true, untilMs: left } : { want: false, untilMs: null };
}

/** Whether the status slot shows "Screen may sleep": wanted, and the browser refused or cannot keep it on. */
export function screenMaySleep(s: WakeLockState): boolean {
  return s.wanted && (s.state === "refused" || s.state === "unsupported");
}

export class ScreenWake extends Store<WakeLockState> {
  private sentinel: Sentinel | null = null;
  private request: Promise<void> | null = null;
  private listening = false;

  constructor() {
    super({ wanted: false, state: wakeApi() ? "off" : "unsupported" });
  }

  /** Keep the screen on (true) or let it sleep again (false). Idempotent. */
  want(wanted: boolean): void {
    if (wanted === this.get().wanted) {
      if (wanted) void this.acquire();
      return;
    }
    this.set({ wanted });
    if (wanted) {
      this.listen();
      void this.acquire();
    } else {
      this.releaseLock();
    }
  }

  /** Request the lock now (also called on visibility and gestures). Resolves when the request settles. */
  acquire(): Promise<void> {
    const api = wakeApi();
    if (!api) {
      this.set({ state: "unsupported" });
      return Promise.resolve();
    }
    if (!this.get().wanted || !pageVisible()) return Promise.resolve();
    if (this.sentinel && !this.sentinel.released) return Promise.resolve();
    if (this.request) return this.request;
    this.set({ state: "pending" });
    let req: Promise<Sentinel>;
    try {
      req = api.request("screen");
    } catch {
      this.set({ state: "refused" });
      return Promise.resolve();
    }
    this.request = req
      .then((s) => {
        if (!this.get().wanted) {
          void s.release().catch(() => undefined);
          this.set({ state: "off" });
          return;
        }
        this.sentinel = s;
        this.set({ state: "on" });
        s.addEventListener("release", () => {
          if (this.sentinel !== s) return;
          this.sentinel = null;
          // Hidden: the system took it and it comes back with the page. Visible: something else ended it (Low
          // Power Mode): the screen may sleep until the next tap re-requests it.
          if (this.get().wanted) this.set({ state: pageVisible() ? "refused" : "off" });
          else this.set({ state: "off" });
        });
      })
      .catch(() => {
        this.set({ state: this.get().wanted ? "refused" : "off" });
      })
      .finally(() => {
        this.request = null;
      });
    return this.request;
  }

  private releaseLock(): void {
    const s = this.sentinel;
    this.sentinel = null;
    if (s && !s.released) void s.release().catch(() => undefined);
    this.set({ state: wakeApi() ? "off" : "unsupported" });
  }

  private readonly onVisibility = (): void => {
    if (pageVisible()) void this.acquire();
  };

  private readonly onGesture = (): void => {
    const st = this.get().state;
    if (this.get().wanted && (st === "refused" || st === "off")) void this.acquire();
  };

  /** Attach the page listeners once, on first use (nothing runs at import). */
  private listen(): void {
    if (this.listening) return;
    try {
      document.addEventListener("visibilitychange", this.onVisibility);
      window.addEventListener("pointerdown", this.onGesture, { passive: true });
      this.listening = true;
    } catch {
      /* no DOM (tests, SSR): the lock is only requested by want() */
    }
  }
}

/** The app's one screen wake lock (Drive pages). */
export const screenWake = new ScreenWake();
