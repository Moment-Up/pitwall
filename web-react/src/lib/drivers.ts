// Driver profiles store, ported from web/src/lib/drivers.svelte.ts (framework-agnostic): the family's profiles,
// who is in the seat, and switching.
//
// API: /api/drivers (src/pitwall/api/routes_drivers.py). The server owns the truth - the active driver is persisted
// there and read by the telemetry ingest - so every mutation re-fetches the list instead of patching local state,
// and the store polls while the page is visible so a switch made on the phone shows up on the iPad.
// Switching the active driver while a session is live hands the seat over: the server starts a new session for
// the new driver (or re-tags the current one if no lap has been completed yet).
//
// Stale reads: a GET that was already in flight when a mutation started can answer with the state from before the
// mutation. Every mutation bumps `seq` when it starts and again when it ends, and a GET's answer is applied only if
// no bump happened since it was sent and no mutation is still running; the refresh after a mutation always sends a
// fresh GET instead of joining one sent earlier.

import type { SessionRow } from "./api";
import { authFetch } from "./auth";
import { Store } from "./store";

export type SkillLevel = "beginner" | "intermediate" | "advanced";
export type CoachingIntensity = "quiet" | "normal" | "detailed";

export interface DriverPreferences {
  colour: string;
  initials: string;
  skill_level: SkillLevel;
  coaching_intensity: CoachingIntensity;
  voice_enabled: boolean;
  /** "Usually plays": a games catalogue id (GET /api/games), selected when this driver takes the seat while no
   * telemetry is live. null = none; absent from servers before game selection (never sent to those). */
  default_game?: string | null;
}

export interface DriverBestLap {
  game: string;
  track_id: string;
  track_name: string | null;
  lap_time_ms: number;
  lap_id: number;
  session_id: string;
  car_name: string | null;
  synthetic: boolean;
  set_unix: number;
}

export interface DriverStats {
  sessions: number;
  laps: number;
  clean_laps: number;
  tracks: number;
  last_session_unix: number | null;
  best_laps: DriverBestLap[];
}

export interface CoachingLimits {
  skill_level: SkillLevel;
  intensity: CoachingIntensity;
  min_confidence: number;
  min_impact_s: number;
  max_per_lap: number;
  max_corrective_per_lap: number;
  max_positive_per_lap: number;
  allowed_kinds: string[] | null;
  simple_wording: boolean;
  mention_consistency: boolean;
  corner_repeat_gap_laps: number;
}

export interface Driver {
  id: number;
  name: string;
  created_unix: number;
  preferences: DriverPreferences;
  coaching: CoachingLimits;
  active: boolean;
  stats: DriverStats;
}

export type DriverInput = Partial<DriverPreferences> & { name?: string };

/** Session rows carry their owner (repo.list_sessions joins the driver's name). */
export type DriverSessionRow = SessionRow & { driver_id: number | null; driver_name: string | null };

export interface AssignResult {
  session_id: string;
  driver_id: number;
  previous_driver_id: number | null;
  live: boolean;
  active_changed: boolean;
}

/** `radio` describes on-track coaching (only true while the radio follows the seated driver, see
 * `DriversState.radioFollowsDriver`); `engineer` is what the level changes in the engineer's answers today. */
export const SKILL_LEVELS: { value: SkillLevel; label: string; radio: string; engineer: string }[] = [
  {
    value: "beginner",
    label: "Beginner",
    radio: "One clear tip a lap at most, simple wording, praise when it goes well.",
    engineer: "The engineer answers in plain words, one point at a time.",
  },
  {
    value: "intermediate",
    label: "Intermediate",
    radio: "One focused tip a lap; skips the smallest time losses.",
    engineer: "The engineer answers like a race engineer.",
  },
  {
    value: "advanced",
    label: "Advanced",
    radio: "Full detail: small time losses, habits across laps.",
    engineer: "The engineer answers like a race engineer.",
  },
];

export const INTENSITIES: { value: CoachingIntensity; label: string; hint: string }[] = [
  { value: "quiet", label: "Quiet", hint: "Alerts and answers only." },
  { value: "normal", label: "Normal", hint: "Lap summary and the top point." },
  { value: "detailed", label: "Detailed", hint: "More points per lap (beginners still get one)." },
];

// Same palette the server picks from (pitwall.drivers.PALETTE). Data, not theme: a driver's colour is their identity.
export const PALETTE = ["#ff6a2b", "#38bdf8", "#3ddc84", "#b36bff", "#ffb020", "#f472b6", "#ff4d5e", "#94a3b8"];

const POLL_MS = 20_000;

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await authFetch(path, init);
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const body = (await r.json()) as { detail?: unknown };
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* not json */
    }
    throw new Error(detail || `HTTP ${r.status}`);
  }
  return r.json() as Promise<T>;
}

const send = <T>(method: string, path: string, body?: unknown) =>
  req<T>(path, {
    method,
    ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  });

/** Shown when a name has no ASCII letter or digit to take (pitwall.drivers.NO_INITIALS); never sent as input. */
export const NO_INITIALS = "?";

/** Initials the server would derive (pitwall.drivers.default_initials): the first character of up to two words,
 * folded to ASCII ("É" -> "E"), keeping only letters and digits - the only characters initials may contain. */
export function initialsFor(name: string): string {
  const letters = name
    .trim()
    .split(/\s+/)
    .filter((w) => w.length > 0)
    .map((w) =>
      ([...w][0] ?? "")
        .normalize("NFKD")
        .replace(/[^A-Za-z0-9]/g, "")
        .slice(0, 1)
        .toUpperCase(),
    )
    .filter((c) => c.length > 0)
    .slice(0, 2);
  return letters.join("") || NO_INITIALS;
}

/** Black or white text, whichever reads better on a #rrggbb background (WCAG relative luminance). */
export function inkOn(hex: string): string {
  const m = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!m?.[1]) return "#fff";
  const n = parseInt(m[1], 16);
  const lin = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  const L = 0.2126 * lin((n >> 16) & 255) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255);
  return L > 0.4 ? "#11151b" : "#fff";
}

export interface DriversState {
  drivers: Driver[];
  activeId: number | null;
  /** Whether the radio applies the seated driver's coaching and voice settings (server: radio_follows_driver).
   * Until it does, the profile page does not offer those settings: they would change nothing on track. */
  radioFollowsDriver: boolean;
  loaded: boolean;
  error: string | null;
  /** A switch is in flight (the switcher shows it and ignores further taps). */
  switching: boolean;
}

/** The driver in the seat (derived; use with a selector). */
export const activeDriver = (s: DriversState): Driver | null => s.drivers.find((d) => d.id === s.activeId) ?? null;

export class DriverStore extends Store<DriversState> {
  private users = 0;
  private timer: ReturnType<typeof setInterval> | null = null;
  private inflight: { seq: number; done: Promise<void> } | null = null;
  private seq = 0; // bumped when a mutation starts and when it ends
  private mutating = 0; // mutations in flight

  constructor() {
    super({ drivers: [], activeId: null, radioFollowsDriver: false, loaded: false, error: null, switching: false });
  }

  /** Start polling (ref-counted: every mounted user calls start and runs the returned stop on unmount). */
  start(): () => void {
    this.users += 1;
    if (this.users === 1) {
      void this.refresh();
      this.timer = setInterval(() => {
        if (document.visibilityState === "visible") void this.refresh();
      }, POLL_MS);
      document.addEventListener("visibilitychange", this.onVisible);
    }
    let released = false;
    return () => {
      if (released) return;
      released = true;
      this.users -= 1;
      if (this.users === 0) {
        if (this.timer) clearInterval(this.timer);
        this.timer = null;
        document.removeEventListener("visibilitychange", this.onVisible);
      }
    };
  }

  private readonly onVisible = () => {
    if (document.visibilityState === "visible") void this.refresh();
  };

  byId(id: number | null | undefined): Driver | null {
    return id == null ? null : (this.get().drivers.find((d) => d.id === id) ?? null);
  }

  /** Re-fetch the list. Callers share a request only if no mutation started or ended since it was sent. */
  refresh(): Promise<void> {
    const seq = this.seq;
    if (this.inflight && this.inflight.seq === seq) return this.inflight.done;
    const entry = { seq, done: Promise.resolve() };
    entry.done = (async () => {
      try {
        const r = await req<{ active_id: number | null; radio_follows_driver?: boolean; drivers: Driver[] }>(
          "/api/drivers",
        );
        if (!this.current(seq)) return; // may predate a mutation: the post-mutation refresh brings the truth
        this.set({
          drivers: r.drivers,
          activeId: r.active_id,
          radioFollowsDriver: r.radio_follows_driver === true,
          error: null,
          loaded: true,
        });
      } catch (e) {
        if (!this.current(seq)) return;
        this.set({ error: e instanceof Error ? e.message : String(e), loaded: true });
      } finally {
        if (this.inflight === entry) this.inflight = null;
      }
    })();
    this.inflight = entry;
    return entry.done;
  }

  /** A GET sent at `seq` may be applied: nothing was mutated since, and nothing is being mutated now. */
  private current(seq: number): boolean {
    return seq === this.seq && this.mutating === 0;
  }

  /** Run a mutation, then re-fetch with a GET sent after it finished (also after a failure: undo optimism). */
  private async mutate<T>(fn: () => Promise<T>): Promise<T> {
    this.seq += 1;
    this.mutating += 1;
    try {
      return await fn();
    } finally {
      this.mutating -= 1;
      this.seq += 1;
      await this.refresh();
    }
  }

  async setActive(id: number): Promise<void> {
    const { switching, activeId } = this.get();
    if (switching || id === activeId) return;
    const previous = activeId;
    this.set({ switching: true, activeId: id }); // optimistic: the switcher updates under the finger
    try {
      await this.mutate(async () => {
        try {
          await send<Driver>("PUT", "/api/drivers/active", { driver_id: id });
        } catch (e) {
          this.set({ activeId: previous });
          throw e;
        }
      });
    } finally {
      this.set({ switching: false });
    }
  }

  create(input: DriverInput & { name: string }): Promise<Driver> {
    return this.mutate(() => send<Driver>("POST", "/api/drivers", input));
  }

  update(id: number, patch: DriverInput): Promise<Driver> {
    return this.mutate(() => send<Driver>("PATCH", `/api/drivers/${id}`, patch));
  }

  remove(id: number, reassignTo: number | null = null): Promise<void> {
    const q = reassignTo != null ? `?reassign_to=${reassignTo}` : "";
    return this.mutate(async () => {
      await send<unknown>("DELETE", `/api/drivers/${id}${q}`);
    });
  }

  assignSession(sessionId: string, driverId: number): Promise<AssignResult> {
    return this.mutate(() =>
      send<AssignResult>("POST", `/api/drivers/sessions/${encodeURIComponent(sessionId)}/assign`, {
        driver_id: driverId,
      }),
    );
  }

  sessionsFor(driverId: number, limit = 50): Promise<DriverSessionRow[]> {
    return req<DriverSessionRow[]>(`/api/drivers/${driverId}/sessions?limit=${limit}`);
  }
}

export const drivers = new DriverStore();
