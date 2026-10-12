// Live telemetry store over /ws/live, ported from web/src/lib/live.svelte.ts (framework-agnostic).
//
// Behaviour kept from the Svelte store:
//  * reconnect with exponential backoff 500 ms -> 5 s, reset on open;
//  * binary frames are UTF-8 JSON ({type: "snapshot" | "lap", data});
//  * static-snapshot merge: the server only includes `track_model`, `skeleton`, `bests` (D2), `last_comparison` and
//    `track_knowledge` every ~5 s (include_static), so a snapshot without the key (undefined - NOT null, which means
//    "none") carries the previous value across - within the same session only, so a new session never shows the
//    previous one's model or bests (it shows them as unknown until its first static snapshot, <= 5 s);
//  * a 12 s rolling history of speed/throttle/brake for traces;
//  * the last `lap` notification;
//  * the last `motivation` notification (lane motivation: goals reached, for Drive's 6 s GOAL REACHED chip).
// Added for React: ref-counted start()/stop (StrictMode mounts twice) and an immutable state object per update.
// Added for the iPad: a message watchdog (the server sends at least every 5 s, so 8 s of silence means a half-open
// socket after Wi-Fi sleep or a Tailscale re-route: drop it and reconnect) and a reconnect-now when the app returns
// to the foreground, the page is restored or the network comes back, instead of waiting out the backoff.
//
// Unknown stays unknown: when the socket drops, the car's live state (frame, delta, marshal flags) is cleared from
// the last snapshot - nothing on screen may keep showing frozen speed or delta as if it were current. Session facts
// (track, laps, reference, track model) stay as last known, and `snap.connection` stays the server's LAST report:
// always derive the connection badge with badgeFor(status, connected), which says OFFLINE while the socket is down.

import type { ConnectionStatus, Observation, Snapshot } from "./api";
import { wsUrl } from "./auth";
import type { MotivationNote } from "./endpoints/motivation";
import { Store } from "./store";

export interface HistoryPoint {
  t: number;
  speed: number | null;
  throttle: number | null;
  brake: number | null;
}

export interface LapEvent {
  lap: Record<string, unknown>;
  observations: Observation[];
}

export interface LiveState {
  snap: Snapshot | null;
  /** The WebSocket is open (not the same as telemetry flowing: see `snap.connection.status`). */
  connected: boolean;
  history: readonly HistoryPoint[];
  lastLapEvent: LapEvent | null;
  /** The newest `{"type": "motivation"}` note (goals reached on a lap or at the flag), or null. */
  lastMotivation: MotivationNote | null;
}

/** Connection badge: LIVE (packets flowing), STALE (packets stopped recently), IDLE (no data), OFFLINE (the
 * dashboard's socket to pitwall is down, so the server's last status is no longer known to be true). */
export type LiveBadge = "LIVE" | "STALE" | "IDLE" | "OFFLINE";

export function badgeFor(status: ConnectionStatus | null | undefined, connected: boolean): LiveBadge {
  if (!connected) return "OFFLINE";
  return status === "live" ? "LIVE" : status === "stale" ? "STALE" : "IDLE";
}

const HISTORY_SECONDS = 12;
export const RETRY_MIN_MS = 500;
export const RETRY_MAX_MS = 5000;
/** No frame for this long = a dead socket (the server sends a static snapshot at least every 5 s, app.py ws_live). */
export const LIVE_SILENCE_MS = 8000;
const WATCHDOG_TICK_MS = 1000;
/** Back in the foreground / online: a socket silent this long (or a connect this old) is restarted now. */
export const FOREGROUND_RECONNECT_MS = 2000;

/** The snapshot keys the server sends only with its ~5 s static payload (core/live.py snapshot(include_static)).
 * "strategy" (race strategy) is sent with it and when it changed (LiveState.strategy_rev, at most every 2 s);
 * "ai_pace", "coachref" and "lap_totals" with it and whenever they changed (api/app.py ON_CHANGE_KEYS). Absent keeps the previous
 * value within the session, null means none, and a new session starts without them (the server sends them all again
 * in a new session's first snapshot). */
export const STATIC_KEYS = [
  "track_model",
  "skeleton",
  "bests",
  "last_comparison",
  "track_knowledge",
  "strategy",
  "ai_pace",
  "coachref",
  "lap_totals",
] as const;

/** Merge the static parts of the previous snapshot into one that omitted them, within the same session (a new session
 * starts without them until its first static snapshot). Exported for tests. */
export function mergeStatic<S extends Snapshot>(prev: Snapshot | null, next: S): S {
  if (!prev || prev.session_id !== next.session_id) return next;
  const p = prev as unknown as Record<string, unknown>;
  const n = next as unknown as Record<string, unknown>;
  let patch: Record<string, unknown> | null = null;
  for (const k of STATIC_KEYS) {
    if (n[k] === undefined && p[k] !== undefined) (patch ??= {})[k] = p[k];
  }
  return patch ? ({ ...next, ...patch } as S) : next;
}

/** The last snapshot with the car's live state removed, for while the socket is down. Exported for tests. */
export function offlineSnapshot(snap: Snapshot | null): Snapshot | null {
  if (!snap || (snap.frame === null && snap.delta_s === null && snap.marshal_flags === undefined)) return snap;
  return { ...snap, frame: null, delta_s: null, marshal_flags: undefined };
}

function pageHidden(): boolean {
  return typeof document !== "undefined" && document.visibilityState === "hidden";
}

export class LiveStore extends Store<LiveState> {
  private ws: WebSocket | null = null;
  private retry = RETRY_MIN_MS;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private closeTimer: ReturnType<typeof setTimeout> | null = null;
  private watchdog: ReturnType<typeof setInterval> | null = null;
  /** Wall clock (ms) of the last sign of life: the connect attempt, the open, the last frame. Date.now(), not
   * performance.now(): iOS stops the monotonic clock while the device sleeps, and the watchdog must see that time. */
  private lastHeardAt = 0;
  private users = 0;
  private readonly decoder = new TextDecoder();

  constructor() {
    super({ snap: null, connected: false, history: [], lastLapEvent: null, lastMotivation: null });
  }

  /** Start the socket (ref-counted). Returns the release function; the socket closes when the last user releases. */
  start(): () => void {
    this.users += 1;
    if (this.users === 1) this.listen(true);
    if (this.users === 1 && !this.ws && !this.retryTimer) this.connect();
    if (this.closeTimer) {
      clearTimeout(this.closeTimer); // re-acquired before the deferred close ran (React StrictMode remount)
      this.closeTimer = null;
    }
    let released = false;
    return () => {
      if (released) return;
      released = true;
      this.users -= 1;
      if (this.users > 0) return;
      // Defer the close a tick so an immediate re-acquire keeps the socket instead of churning it.
      this.closeTimer = setTimeout(() => {
        this.closeTimer = null;
        if (this.users === 0) this.close();
      }, 0);
    };
  }

  private close(): void {
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retryTimer = null;
    this.listen(false);
    this.discard();
    this.goOffline();
  }

  /** Watchdog and foreground listeners, while anyone uses the store. */
  private listen(on: boolean): void {
    if (on) {
      if (!this.watchdog) this.watchdog = setInterval(this.onTick, WATCHDOG_TICK_MS);
    } else if (this.watchdog) {
      clearInterval(this.watchdog);
      this.watchdog = null;
    }
    if (typeof window !== "undefined") {
      const method = on ? "addEventListener" : "removeEventListener";
      window[method]?.("pageshow", this.onWake);
      window[method]?.("online", this.onWake);
    }
    if (typeof document !== "undefined") {
      document[on ? "addEventListener" : "removeEventListener"]?.("visibilitychange", this.onWake);
    }
  }

  /** Forget the current socket without its close reaching our handlers. */
  private discard(): void {
    const ws = this.ws;
    this.ws = null;
    if (!ws) return;
    ws.onopen = ws.onclose = ws.onmessage = ws.onerror = null;
    try {
      ws.close();
    } catch {
      /* already closed */
    }
  }

  private goOffline(): void {
    this.set({ connected: false, snap: offlineSnapshot(this.get().snap) });
  }

  private scheduleRetry(): void {
    this.retryTimer = setTimeout(() => this.connect(), this.retry);
    this.retry = Math.min(this.retry * 2, RETRY_MAX_MS);
  }

  /** Silence for LIVE_SILENCE_MS (half-open socket, or a handshake that never completes): drop it and retry as if
   * it had closed, so nothing keeps showing the last snapshot as current. */
  private onTick = (): void => {
    if (!this.ws || Date.now() - this.lastHeardAt <= LIVE_SILENCE_MS) return;
    this.discard();
    this.goOffline();
    this.scheduleRetry();
  };

  /** Foreground (visibilitychange), page restored (pageshow) or network back (online): reconnect now instead of
   * waiting out the backoff or a socket that may have died while the iPad slept. */
  private onWake = (): void => {
    if (this.users === 0 || pageHidden()) return;
    const silent = Date.now() - this.lastHeardAt;
    if (this.ws) {
      if (silent <= FOREGROUND_RECONNECT_MS) return;
      // An open socket whose last word was "idle" or "stale" shows nothing as current: the watchdog decides. One that
      // said "live" may be showing frozen telemetry as current, and a connect this old is probably hung: restart.
      const { connected, snap } = this.get();
      if (connected && snap?.connection.status !== "live" && silent <= LIVE_SILENCE_MS) return;
      this.discard();
      this.goOffline();
    }
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retry = RETRY_MIN_MS;
    this.connect();
  };

  private connect(): void {
    this.retryTimer = null;
    this.lastHeardAt = Date.now();
    const ws = new WebSocket(wsUrl("/ws/live"));
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onopen = () => {
      this.lastHeardAt = Date.now();
      this.retry = RETRY_MIN_MS;
      this.set({ connected: true });
    };
    ws.onclose = () => {
      if (this.ws !== ws) return; // closed by us
      this.ws = null;
      this.goOffline();
      this.scheduleRetry();
    };
    ws.onmessage = (ev: MessageEvent<string | ArrayBuffer>) => {
      this.lastHeardAt = Date.now();
      let msg: { type?: string; data?: unknown };
      try {
        const text = typeof ev.data === "string" ? ev.data : this.decoder.decode(ev.data);
        msg = JSON.parse(text) as { type?: string; data?: unknown };
      } catch {
        return; // a malformed frame must not kill the stream
      }
      if (msg.type === "snapshot") this.onSnapshot(msg.data as Snapshot);
      else if (msg.type === "lap") this.set({ lastLapEvent: msg.data as LapEvent });
      else if (msg.type === "motivation") this.set({ lastMotivation: msg.data as MotivationNote });
    };
  }

  private onSnapshot(raw: Snapshot): void {
    const prev = this.get();
    const snap = mergeStatic(prev.snap, raw);
    const f = snap.frame;
    let history = prev.history;
    if (f) {
      const now = performance.now() / 1000;
      let start = 0;
      while (start < history.length && now - (history[start]?.t ?? now) > HISTORY_SECONDS) start += 1;
      history = [...history.slice(start), { t: now, speed: f.speed_kph, throttle: f.throttle, brake: f.brake }];
    }
    this.set({ snap, history });
  }
}

export const live = new LiveStore();
