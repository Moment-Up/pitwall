// The validation kit's device reporter (lane validate, spec 6.4 and 12.2). A plain class with injectable dependencies:
// it never touches React state, never throws into the app, and costs one GET every 20 s while no run is active.
//
//   idle       GET /api/validation/active every 20 s (errors back off 20 s -> 30 s -> 60 s).
//   reporting  a run is active: POST /api/validation/client on start, every 15 s, on a change of what the kit
//              measures (debounced 1 s) and at once when the page is hidden (beacon) or shown again. A 409 (the run
//              ended) returns to idle; other errors back off 15 s -> 30 s -> 60 s.
//   fps        only while the run's current test is the one-hour endurance test and a Drive page is open and visible:
//              a requestAnimationFrame counter, one 10 s window at a time; each finished window is sent once, in its
//              own report, so the server can count windows.
//
// What a report carries is in ClientReport (contract): device class, Home Screen or not, how the page was reached,
// the route, the wake lock and the radio link's state. The microphone's label is classified on the device
// (device.ts) once a minute while the radio is live, and only the class is sent.

import type { AudioInputKind, ClientPostResult, ClientRadio, ClientReport, Device, OriginKind, RunSummary, WakeState } from "../endpoints/validation";
import { audioInputKind, isDriveRoute } from "./device";

export const ACTIVE_POLL_MS = 20_000;
export const REPORT_INTERVAL_MS = 15_000;
export const CHANGE_DEBOUNCE_MS = 1_000;
export const BACKOFF_MIN_MS = 15_000;
export const BACKOFF_MAX_MS = 60_000;
export const MIC_CHECK_MS = 60_000;
export const FPS_WINDOW_MS = 10_000;
/** The catalogue id of the one-hour test: the only time frames are counted. */
export const ENDURANCE_ITEM = "ipad_endurance";

/** What the page knows about this device right now (everything in a report except the run, seq, reason and fps). */
export interface DeviceSnapshot {
  device: Device;
  standalone: boolean;
  secure_context: boolean;
  origin_kind: OriginKind;
  safari_version: string | null;
  viewport: { w: number; h: number; dpr: number; orientation: "landscape" | "portrait" };
  visibility: "visible" | "hidden";
  route: string;
  wake: { wanted: boolean; state: WakeState };
  radio: ClientRadio | null;
}

export interface ReporterEnv {
  clientId: string;
  /** Device facts now. Cheap: called on store notifications. */
  snapshot(): DeviceSnapshot;
  /** Anything that can change the snapshot (wake lock, radio, route). Returns the unsubscribe function. */
  subscribe(onChange: () => void): () => void;
  /** Page visibility changes. Returns the unsubscribe function. */
  onVisibility(cb: (visible: boolean) => void): () => void;
  fetchActive(): Promise<{ run: RunSummary | null }>;
  post(report: ClientReport, hidden: boolean): Promise<ClientPostResult>;
  /** The radio is live with the microphone allowed (labels are only readable then). */
  micAllowed(): boolean;
  /** The default microphone's label, or null. Never sent anywhere: only classified. */
  micLabel(): Promise<string | null>;
  /** Device clock (ms since the epoch) for t_client_ms. */
  now(): number;
  /** Monotonic ms for the fps meter. */
  perfNow(): number;
  /** requestAnimationFrame / cancelAnimationFrame, or null where there is none (the fps meter then stays off). */
  raf: ((cb: () => void) => number) | null;
  cancelRaf: ((id: number) => void) | null;
}

export type ReporterPhase = "stopped" | "idle" | "reporting";

/** Error back-off: 15 s, 30 s, then 60 s. */
export function backoffMs(failures: number): number {
  if (failures <= 0) return 0;
  return Math.min(BACKOFF_MAX_MS, BACKOFF_MIN_MS * 2 ** (failures - 1));
}

/** The facts whose change triggers a report (not the viewport size, not the round-trip time). */
export function changeKey(s: DeviceSnapshot, mic: AudioInputKind | null): string {
  const r = s.radio;
  return [
    s.visibility,
    s.route,
    s.wake.wanted ? 1 : 0,
    s.wake.state,
    s.standalone ? 1 : 0,
    s.viewport.orientation,
    r ? `${r.phase}|${r.conn}|${r.mic}|${r.mic_silent ? 1 : 0}|${r.wake}|${r.audio}|${r.audio_session}|${r.tts_mode}` : "-",
    mic ?? "-",
  ].join("/");
}

/** Whether frames are counted: the endurance test is current and a Drive page is open and visible. */
export function fpsAllowed(run: Pick<RunSummary, "current_item"> | null, s: Pick<DeviceSnapshot, "route" | "visibility">): boolean {
  return run?.current_item === ENDURANCE_ITEM && isDriveRoute(s.route) && s.visibility === "visible";
}

type Timer = ReturnType<typeof setTimeout>;

export class ValidationReporter {
  private phaseNow: ReporterPhase = "stopped";
  private run: RunSummary | null = null;
  private seq = 0;
  private pollTimer: Timer | null = null;
  private reportTimer: Timer | null = null;
  private changeTimer: Timer | null = null;
  private micTimer: Timer | null = null;
  private pollFailures = 0;
  private postFailures = 0;
  private lastKey = "";
  private mic: AudioInputKind | null = null;
  private unsub: (() => void)[] = [];
  private sending = false;
  private queued: ClientReport["reason"] | null = null;
  // fps meter
  private rafId: number | null = null;
  private frames = 0;
  private windowStart = 0;
  private freshFps: number | null = null;
  /** Bumped by stop() / a run change so late answers of an old poll or post are ignored. */
  private epoch = 0;

  constructor(private readonly env: ReporterEnv) {}

  get phase(): ReporterPhase {
    return this.phaseNow;
  }

  /** The active run the reporter follows (null while idle). */
  get activeRun(): RunSummary | null {
    return this.run;
  }

  /** Start polling (idempotent). */
  start(): void {
    if (this.phaseNow !== "stopped") return;
    this.phaseNow = "idle";
    this.epoch += 1;
    void this.poll();
  }

  /** Stop everything (timers, listeners, the fps meter). */
  stop(): void {
    this.epoch += 1;
    this.leaveReporting();
    this.clear("pollTimer");
    this.phaseNow = "stopped";
    this.run = null;
  }

  /** Ask the server now (the page calls this after it starts, finishes or moves a run). */
  refresh(): void {
    if (this.phaseNow === "stopped") return;
    void this.poll();
  }

  // ------------------------------------------------------------------------------------------------ polling
  private async poll(): Promise<void> {
    this.clear("pollTimer");
    const epoch = this.epoch;
    let next = ACTIVE_POLL_MS;
    try {
      const { run } = await this.env.fetchActive();
      if (this.stale(epoch)) return;
      this.pollFailures = 0;
      if (!run || run.status !== "active") {
        this.goIdle();
      } else if (!this.run || this.run.id !== run.id || this.phaseNow !== "reporting") {
        this.run = run;
        this.enterReporting();
      } else {
        this.run = run;
        this.updateFps();
      }
    } catch {
      if (this.stale(epoch)) return;
      this.pollFailures += 1;
      next = Math.max(ACTIVE_POLL_MS, backoffMs(this.pollFailures));
    }
    if (this.stale(epoch)) return;
    this.pollTimer = setTimeout(() => void this.poll(), next);
  }

  /** stop() or a newer start ran while a request was out (a method, so TypeScript does not narrow the phase). */
  private stale(epoch: number): boolean {
    return epoch !== this.epoch || this.phaseNow === "stopped";
  }

  private goIdle(): void {
    if (this.phaseNow === "reporting") this.leaveReporting();
    this.run = null;
    if (this.phaseNow !== "stopped") this.phaseNow = "idle";
  }

  // ------------------------------------------------------------------------------------------------ reporting
  private enterReporting(): void {
    this.leaveReporting();
    this.phaseNow = "reporting";
    this.postFailures = 0;
    try {
      this.unsub.push(this.env.subscribe(this.onChange));
      this.unsub.push(this.env.onVisibility(this.onVisibility));
    } catch {
      /* no DOM: interval reports only */
    }
    this.updateMic();
    this.updateFps();
    void this.send("start");
  }

  private leaveReporting(): void {
    for (const u of this.unsub.splice(0)) {
      try {
        u();
      } catch {
        /* ignore */
      }
    }
    this.clear("reportTimer");
    this.clear("changeTimer");
    this.clear("micTimer");
    this.stopFps();
    this.queued = null;
  }

  /** Store notifications (the radio's level meter notifies ~50 times a second while live): one snapshot each, and
   * nothing else while a change report is already pending. */
  private readonly onChange = (): void => {
    if (this.phaseNow !== "reporting") return;
    let s: DeviceSnapshot;
    try {
      s = this.env.snapshot();
    } catch {
      return;
    }
    this.updateMic();
    this.updateFps(s);
    if (this.changeTimer) return;
    const key = changeKey(s, this.mic);
    if (key === this.lastKey) return;
    this.changeTimer = setTimeout(() => {
      this.changeTimer = null;
      void this.send("change");
    }, CHANGE_DEBOUNCE_MS);
  };

  private readonly onVisibility = (visible: boolean): void => {
    if (this.phaseNow !== "reporting") return;
    this.updateFps();
    this.clear("changeTimer");
    void this.send(visible ? "visible" : "hidden", !visible);
  };

  private build(reason: ClientReport["reason"]): ClientReport | null {
    const run = this.run;
    if (!run) return null;
    const s = this.env.snapshot();
    this.lastKey = changeKey(s, this.mic);
    const fps = this.freshFps;
    this.freshFps = null;
    this.seq += 1;
    return {
      run_id: run.id,
      client_id: this.env.clientId,
      seq: this.seq,
      reason,
      t_client_ms: Math.round(this.env.now()),
      device: s.device,
      standalone: s.standalone,
      secure_context: s.secure_context,
      origin_kind: s.origin_kind,
      safari_version: s.safari_version,
      viewport: s.viewport,
      visibility: s.visibility,
      route: s.route,
      wake: s.wake,
      radio: s.radio,
      audio_input_kind: this.mic,
      fps_10s: fps,
    };
  }

  /**
   * Send one report. Ordinary reports go one at a time (the server reads a lower `seq` as a reload, so two in flight
   * must not overtake each other); a hidden report goes at once as a beacon, because the page may be frozen next.
   */
  private async send(reason: ClientReport["reason"], hidden = false): Promise<void> {
    if (this.phaseNow !== "reporting") return;
    if (this.sending && !hidden) {
      // Keep the most informative pending reason (a fresh fps window is carried by whichever goes next).
      this.queued = this.queued === "start" ? "start" : reason;
      return;
    }
    let report: ClientReport | null;
    try {
      report = this.build(reason);
    } catch {
      report = null;
    }
    if (!report) return;
    this.clear("reportTimer");
    const epoch = this.epoch;
    if (!hidden) this.sending = true;
    let result: ClientPostResult;
    try {
      result = await this.env.post(report, hidden);
    } catch {
      result = "error";
    } finally {
      if (!hidden) this.sending = false;
    }
    if (epoch !== this.epoch || this.phaseNow !== "reporting") return;
    if (result === "no_run") {
      this.goIdle();
      this.clear("pollTimer");
      this.pollTimer = setTimeout(() => void this.poll(), ACTIVE_POLL_MS);
      return;
    }
    if (result === "ok") this.postFailures = 0;
    else this.postFailures += 1;
    const queued = this.queued;
    this.queued = null;
    if (queued) {
      void this.send(queued);
      return;
    }
    if (hidden) return; // the next visible / interval report follows as usual
    this.reportTimer = setTimeout(() => void this.send("interval"), this.postFailures ? backoffMs(this.postFailures) : REPORT_INTERVAL_MS);
  }

  // ------------------------------------------------------------------------------------------------ microphone
  private updateMic(): void {
    let allowed = false;
    try {
      allowed = this.env.micAllowed();
    } catch {
      allowed = false;
    }
    if (!allowed) {
      this.clear("micTimer");
      return;
    }
    if (this.micTimer) return;
    const check = async (): Promise<void> => {
      const epoch = this.epoch;
      try {
        const label = await this.env.micLabel();
        if (epoch !== this.epoch) return;
        const kind = audioInputKind(label);
        if (kind !== null && kind !== this.mic) {
          this.mic = kind;
          this.onChange();
        }
      } catch {
        /* unknown stays unknown */
      }
    };
    void check();
    const loop = (): void => {
      this.micTimer = setTimeout(() => {
        if (this.phaseNow !== "reporting") return;
        void check();
        loop();
      }, MIC_CHECK_MS);
    };
    loop();
  }

  // ------------------------------------------------------------------------------------------------ fps meter
  private updateFps(snap?: DeviceSnapshot): void {
    let allowed = false;
    try {
      allowed = this.phaseNow === "reporting" && fpsAllowed(this.run, snap ?? this.env.snapshot());
    } catch {
      allowed = false;
    }
    if (allowed && this.rafId === null) this.startFps();
    else if (!allowed && this.rafId !== null) this.stopFps();
  }

  private startFps(): void {
    const raf = this.env.raf;
    if (!raf) return;
    this.frames = 0;
    this.windowStart = this.env.perfNow();
    const tick = (): void => {
      this.frames += 1;
      const now = this.env.perfNow();
      const elapsed = now - this.windowStart;
      if (elapsed >= FPS_WINDOW_MS) {
        this.freshFps = Math.round((this.frames * 1000 * 10) / elapsed) / 10;
        this.frames = 0;
        this.windowStart = now;
        void this.send("interval");
      }
      this.rafId = raf(tick);
    };
    this.rafId = raf(tick);
  }

  private stopFps(): void {
    if (this.rafId !== null) {
      try {
        this.env.cancelRaf?.(this.rafId);
      } catch {
        /* ignore */
      }
    }
    this.rafId = null;
    this.frames = 0;
    this.freshFps = null;
  }

  private clear(k: "pollTimer" | "reportTimer" | "changeTimer" | "micTimer"): void {
    const t = this[k];
    if (t !== null) clearTimeout(t);
    this[k] = null;
  }
}
