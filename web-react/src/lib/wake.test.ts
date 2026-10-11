// Screen wake lock (spec 3.3): acquire while wanted, release when not, retry after a refusal, "Screen may sleep".
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { driveWakeWanted, ScreenWake, screenMaySleep, WAKE_HOLD_AFTER_LIVE_MS } from "./wake";

class FakeSentinel {
  released = false;
  private listeners: (() => void)[] = [];
  release = vi.fn(async () => {
    this.end();
  });
  addEventListener(_type: "release", l: () => void): void {
    this.listeners.push(l);
  }
  /** The system (or release()) ends the lock. */
  end(): void {
    if (this.released) return;
    this.released = true;
    for (const l of this.listeners) l();
  }
}

interface Env {
  request: ReturnType<typeof vi.fn>;
  sentinels: FakeSentinel[];
  doc: { visibilityState: string; listeners: Map<string, () => void> };
  win: { listeners: Map<string, () => void> };
  refuse: boolean;
}

function stubEnv(opts: { api?: boolean } = {}): Env {
  const env: Env = {
    request: vi.fn(),
    sentinels: [],
    doc: { visibilityState: "visible", listeners: new Map() },
    win: { listeners: new Map() },
    refuse: false,
  };
  env.request.mockImplementation(async () => {
    if (env.refuse) throw new DOMException("refused", "NotAllowedError");
    const s = new FakeSentinel();
    env.sentinels.push(s);
    return s;
  });
  vi.stubGlobal("navigator", opts.api === false ? {} : { wakeLock: { request: env.request } });
  vi.stubGlobal("document", {
    get visibilityState() {
      return env.doc.visibilityState;
    },
    addEventListener: (t: string, l: () => void) => env.doc.listeners.set(t, l),
  });
  vi.stubGlobal("window", { addEventListener: (t: string, l: () => void) => env.win.listeners.set(t, l) });
  return env;
}

const flush = () => new Promise((r) => setTimeout(r, 0));

describe("ScreenWake", () => {
  let env: Env;
  beforeEach(() => {
    env = stubEnv();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("does nothing until a Drive page wants it", () => {
    const w = new ScreenWake();
    expect(w.get()).toEqual({ wanted: false, state: "off" });
    expect(env.request).not.toHaveBeenCalled();
    expect(env.doc.listeners.size).toBe(0);
  });

  it("acquires once when wanted and releases when no longer wanted", async () => {
    const w = new ScreenWake();
    w.want(true);
    expect(w.get().state).toBe("pending");
    await flush();
    expect(w.get()).toEqual({ wanted: true, state: "on" });
    w.want(true); // idempotent: the lock is held
    await flush();
    expect(env.request).toHaveBeenCalledTimes(1);
    w.want(false);
    expect(env.sentinels[0]!.release).toHaveBeenCalled();
    expect(w.get()).toEqual({ wanted: false, state: "off" });
    expect(screenMaySleep(w.get())).toBe(false);
  });

  it("says the screen may sleep when the browser refuses, and retries on the next tap", async () => {
    env.refuse = true;
    const w = new ScreenWake();
    w.want(true);
    await flush();
    expect(w.get().state).toBe("refused");
    expect(screenMaySleep(w.get())).toBe(true);
    env.refuse = false;
    env.win.listeners.get("pointerdown")?.();
    await flush();
    expect(w.get().state).toBe("on");
    expect(screenMaySleep(w.get())).toBe(false);
  });

  it("re-acquires when the page comes back after the system released it", async () => {
    const w = new ScreenWake();
    w.want(true);
    await flush();
    env.doc.visibilityState = "hidden";
    env.sentinels[0]!.end(); // iOS drops the lock when hidden
    expect(w.get().state).toBe("off");
    expect(screenMaySleep(w.get())).toBe(false);
    env.doc.visibilityState = "visible";
    env.doc.listeners.get("visibilitychange")?.();
    await flush();
    expect(env.request).toHaveBeenCalledTimes(2);
    expect(w.get().state).toBe("on");
  });

  it("a release while visible (Low Power Mode) shows the chip until a tap gets it back", async () => {
    const w = new ScreenWake();
    w.want(true);
    await flush();
    env.sentinels[0]!.end();
    expect(w.get().state).toBe("refused");
    env.win.listeners.get("pointerdown")?.();
    await flush();
    expect(w.get().state).toBe("on");
  });

  it("drops a lock granted after the page stopped wanting it", async () => {
    const w = new ScreenWake();
    w.want(true);
    w.want(false);
    await flush();
    expect(env.sentinels[0]!.release).toHaveBeenCalled();
    expect(w.get()).toEqual({ wanted: false, state: "off" });
  });

  it("is unsupported without the API (plain HTTP): the chip shows only while wanted", () => {
    vi.unstubAllGlobals();
    env = stubEnv({ api: false });
    const w = new ScreenWake();
    expect(w.get().state).toBe("unsupported");
    expect(screenMaySleep(w.get())).toBe(false);
    w.want(true);
    expect(screenMaySleep(w.get())).toBe(true);
    w.want(false);
    expect(screenMaySleep(w.get())).toBe(false);
  });

  it("works with no DOM at all (never throws)", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal("navigator", { wakeLock: { request: env.request } });
    const w = new ScreenWake();
    w.want(true);
    await flush();
    expect(w.get().state).toBe("on");
  });
});

describe("driveWakeWanted (when a Drive page keeps the screen on)", () => {
  const T = 1_000_000;
  const at = (telemetryLive: boolean, lastLiveMs: number | null, nowMs: number, noTelemetry = false) =>
    driveWakeWanted({ telemetryLive, noTelemetry, lastLiveMs, nowMs });

  it("keeps it on while telemetry is live", () => {
    expect(at(true, T, T)).toEqual({ want: true, untilMs: null });
    expect(at(true, null, T)).toEqual({ want: true, untilMs: null });
  });

  it("holds it through a pause, menus, loading or a socket flap for up to 10 min after the last live moment", () => {
    expect(at(false, T, T + 2_000)).toEqual({ want: true, untilMs: WAKE_HOLD_AFTER_LIVE_MS - 2_000 });
    expect(at(false, T, T + WAKE_HOLD_AFTER_LIVE_MS - 1)).toEqual({ want: true, untilMs: 1 });
  });

  it("lets it go 10 min after the last live moment (the game was closed)", () => {
    expect(at(false, T, T + WAKE_HOLD_AFTER_LIVE_MS)).toEqual({ want: false, untilMs: null });
    expect(at(false, T, T + 3 * WAKE_HOLD_AFTER_LIVE_MS)).toEqual({ want: false, untilMs: null });
  });

  it("never before the first live packet, and not while the server has had no telemetry at all", () => {
    expect(at(false, null, T)).toEqual({ want: false, untilMs: null });
    expect(at(false, T, T + 1_000, true)).toEqual({ want: false, untilMs: null });
  });
});
