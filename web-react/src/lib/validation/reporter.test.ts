// The validation kit's device reporter (lane validate, spec 12.2) with a fake environment and fake timers: idle
// polling, report cadence, change debounce, the beacon when hidden, 409 -> idle, back-off, the fps meter only when the
// endurance test is current on a Drive page, the microphone class (never its label).

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ClientPostResult, ClientReport, RunSummary } from "../endpoints/validation";
import {
  ACTIVE_POLL_MS,
  CHANGE_DEBOUNCE_MS,
  ENDURANCE_ITEM,
  FPS_WINDOW_MS,
  MIC_CHECK_MS,
  REPORT_INTERVAL_MS,
  ValidationReporter,
  backoffMs,
  changeKey,
  fpsAllowed,
  type DeviceSnapshot,
  type ReporterEnv,
} from "./reporter";

const RUN: RunSummary = {
  id: "20261012-193012-a3f1",
  label: null,
  status: "active",
  started_unix: 1791833412,
  ended_unix: null,
  current_item: "cues_timing",
  counts: { pass: 0, fail: 0, needs_review: 0, not_run: 4, skipped: 0 },
  tiers: [],
};

function snapshot(over: Partial<DeviceSnapshot> = {}): DeviceSnapshot {
  return {
    device: "ipad",
    standalone: true,
    secure_context: true,
    origin_kind: "tailscale_https",
    safari_version: "18.6",
    viewport: { w: 1180, h: 820, dpr: 2, orientation: "landscape" },
    visibility: "visible",
    route: "setup/validation",
    wake: { wanted: false, state: "off" },
    radio: {
      phase: "live",
      conn: "open",
      mic: "live",
      mic_silent: false,
      wake: "on",
      audio: "running",
      audio_session: "play-and-record",
      tts_mode: "server",
      rtt_ms: 38,
    },
    ...over,
  };
}

interface Fake {
  env: ReporterEnv;
  snap: DeviceSnapshot;
  posts: { report: ClientReport; hidden: boolean }[];
  setActive: (r: RunSummary | null | Error) => void;
  setPost: (r: ClientPostResult | (() => Promise<ClientPostResult>)) => void;
  notify: () => void;
  setVisible: (v: boolean) => void;
  listeners: () => number;
  frame: (perfMs: number) => void;
  rafCalls: () => number;
  setMic: (allowed: boolean, label: string | null) => void;
  fetchActive: ReturnType<typeof vi.fn>;
}

function fake(): Fake {
  const state = {
    snap: snapshot(),
    active: { run: null } as { run: RunSummary | null } | Error,
    post: "ok" as ClientPostResult | (() => Promise<ClientPostResult>),
    perf: 0,
    micAllowed: false,
    micLabel: null as string | null,
  };
  const listeners = new Set<() => void>();
  const vis = new Set<(v: boolean) => void>();
  const rafCbs = new Map<number, () => void>();
  let rafId = 0;
  let rafCalls = 0;
  const posts: Fake["posts"] = [];
  const fetchActive = vi.fn(async () => {
    if (state.active instanceof Error) throw state.active;
    return state.active;
  });
  const f: Fake = {
    env: {
      clientId: "5f1c2a9e-7b3d-4c11-9a2e-0d4b8f6e1a77",
      snapshot: () => structuredClone(state.snap),
      subscribe: (cb) => {
        listeners.add(cb);
        return () => listeners.delete(cb);
      },
      onVisibility: (cb) => {
        vis.add(cb);
        return () => vis.delete(cb);
      },
      fetchActive,
      post: async (report, hidden) => {
        posts.push({ report, hidden });
        return typeof state.post === "function" ? state.post() : state.post;
      },
      micAllowed: () => state.micAllowed,
      micLabel: async () => state.micLabel,
      now: () => 1_791_833_500_000,
      perfNow: () => state.perf,
      raf: (cb) => {
        rafCalls += 1;
        rafId += 1;
        rafCbs.set(rafId, cb);
        return rafId;
      },
      cancelRaf: (id) => {
        rafCbs.delete(id);
      },
    },
    get snap() {
      return state.snap;
    },
    posts,
    setActive: (r) => {
      state.active = r instanceof Error ? r : { run: r };
    },
    setPost: (r) => {
      state.post = r;
    },
    notify: () => {
      for (const l of [...listeners]) l();
    },
    setVisible: (v) => {
      state.snap = { ...state.snap, visibility: v ? "visible" : "hidden" };
      for (const l of [...vis]) l(v);
    },
    listeners: () => listeners.size + vis.size,
    frame: (perfMs) => {
      state.perf = perfMs;
      const cbs = [...rafCbs.values()];
      rafCbs.clear();
      for (const cb of cbs) cb();
    },
    rafCalls: () => rafCalls,
    setMic: (allowed, label) => {
      state.micAllowed = allowed;
      state.micLabel = label;
    },
    fetchActive,
  };
  Object.defineProperty(f, "snap", {
    get: () => state.snap,
    set: (v: DeviceSnapshot) => {
      state.snap = v;
    },
  });
  return f;
}

const flush = () => vi.advanceTimersByTimeAsync(0);

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

describe("pure rules", () => {
  it("back-off: 15 s, 30 s, then 60 s", () => {
    expect([0, 1, 2, 3, 4, 9].map(backoffMs)).toEqual([0, 15_000, 30_000, 60_000, 60_000, 60_000]);
  });
  it("the change key ignores the viewport size and the round-trip time", () => {
    const a = snapshot();
    expect(changeKey({ ...a, viewport: { ...a.viewport, w: 1000 } }, null)).toBe(changeKey(a, null));
    expect(changeKey({ ...a, radio: { ...a.radio!, rtt_ms: 90 } }, null)).toBe(changeKey(a, null));
    expect(changeKey({ ...a, route: "drive/coach" }, null)).not.toBe(changeKey(a, null));
    expect(changeKey({ ...a, wake: { wanted: true, state: "on" } }, null)).not.toBe(changeKey(a, null));
    expect(changeKey(a, "airpods")).not.toBe(changeKey(a, null));
  });
  it("frames are counted only for the endurance test on a visible Drive page", () => {
    const end = { current_item: ENDURANCE_ITEM };
    expect(fpsAllowed(end, { route: "drive/coach", visibility: "visible" })).toBe(true);
    expect(fpsAllowed(end, { route: "setup/validation", visibility: "visible" })).toBe(false);
    expect(fpsAllowed(end, { route: "drive/coach", visibility: "hidden" })).toBe(false);
    expect(fpsAllowed({ current_item: "cues_timing" }, { route: "drive/coach", visibility: "visible" })).toBe(false);
    expect(fpsAllowed(null, { route: "drive/coach", visibility: "visible" })).toBe(false);
  });
});

describe("idle", () => {
  it("asks /active every 20 s and posts nothing while no run is active", async () => {
    const f = fake();
    const r = new ValidationReporter(f.env);
    r.start();
    r.start(); // idempotent
    await flush();
    expect(f.fetchActive).toHaveBeenCalledTimes(1);
    expect(r.phase).toBe("idle");
    await vi.advanceTimersByTimeAsync(ACTIVE_POLL_MS);
    expect(f.fetchActive).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(ACTIVE_POLL_MS * 3);
    expect(f.fetchActive).toHaveBeenCalledTimes(5);
    expect(f.posts).toHaveLength(0);
    expect(f.listeners()).toBe(0); // no store subscriptions while idle
    r.stop();
  });

  it("a finished run counts as none", async () => {
    const f = fake();
    f.setActive({ ...RUN, status: "finished" });
    const r = new ValidationReporter(f.env);
    r.start();
    await flush();
    expect(r.phase).toBe("idle");
    expect(f.posts).toHaveLength(0);
    r.stop();
  });

  it("poll errors back off 20 s -> 30 s -> 60 s, and recover", async () => {
    const f = fake();
    f.setActive(new Error("offline"));
    const r = new ValidationReporter(f.env);
    r.start();
    await flush();
    expect(f.fetchActive).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(ACTIVE_POLL_MS); // 1st failure: max(20, 15) s
    expect(f.fetchActive).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(29_999); // 2nd failure: 30 s
    expect(f.fetchActive).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(f.fetchActive).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(59_999); // 3rd failure: 60 s
    expect(f.fetchActive).toHaveBeenCalledTimes(3);
    f.setActive(null);
    await vi.advanceTimersByTimeAsync(1);
    expect(f.fetchActive).toHaveBeenCalledTimes(4);
    await vi.advanceTimersByTimeAsync(ACTIVE_POLL_MS); // recovered: back to 20 s
    expect(f.fetchActive).toHaveBeenCalledTimes(5);
    r.stop();
  });
});

describe("reporting", () => {
  it("a start report at once, then every 15 s; seq counts up", async () => {
    const f = fake();
    f.setActive(RUN);
    const r = new ValidationReporter(f.env);
    r.start();
    await flush();
    expect(r.phase).toBe("reporting");
    expect(f.posts).toHaveLength(1);
    const first = f.posts[0]!;
    expect(first.hidden).toBe(false);
    expect(first.report).toMatchObject({
      run_id: RUN.id,
      client_id: "5f1c2a9e-7b3d-4c11-9a2e-0d4b8f6e1a77",
      seq: 1,
      reason: "start",
      device: "ipad",
      standalone: true,
      secure_context: true,
      origin_kind: "tailscale_https",
      safari_version: "18.6",
      route: "setup/validation",
      visibility: "visible",
      audio_input_kind: null,
      fps_10s: null,
    });
    expect(first.report.radio?.tts_mode).toBe("server");
    await vi.advanceTimersByTimeAsync(REPORT_INTERVAL_MS - 1);
    expect(f.posts).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(f.posts).toHaveLength(2);
    expect(f.posts[1]!.report.reason).toBe("interval");
    await vi.advanceTimersByTimeAsync(REPORT_INTERVAL_MS * 2);
    expect(f.posts.map((p) => p.report.seq)).toEqual([1, 2, 3, 4]);
    r.stop();
  });

  it("a change is reported once, 1 s after it settles; notifications without a change send nothing", async () => {
    const f = fake();
    f.setActive(RUN);
    const r = new ValidationReporter(f.env);
    r.start();
    await flush();
    expect(f.posts).toHaveLength(1);
    // The radio's level meter notifies often: nothing the kit measures changed.
    for (let k = 0; k < 50; k += 1) f.notify();
    await vi.advanceTimersByTimeAsync(CHANGE_DEBOUNCE_MS * 2);
    expect(f.posts).toHaveLength(1);
    // Drive opened and the wake lock taken, in quick succession: one report.
    f.snap = { ...f.snap, route: "drive/coach" };
    f.notify();
    f.snap = { ...f.snap, wake: { wanted: true, state: "pending" } };
    f.notify();
    f.snap = { ...f.snap, wake: { wanted: true, state: "on" } };
    f.notify();
    await vi.advanceTimersByTimeAsync(CHANGE_DEBOUNCE_MS - 1);
    expect(f.posts).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(f.posts).toHaveLength(2);
    expect(f.posts[1]!.report).toMatchObject({ reason: "change", route: "drive/coach", wake: { wanted: true, state: "on" } });
    r.stop();
  });

  it("hidden goes out at once as a beacon; visible is reported at once", async () => {
    const f = fake();
    f.setActive(RUN);
    const r = new ValidationReporter(f.env);
    r.start();
    await flush();
    f.setVisible(false);
    await flush();
    expect(f.posts.at(-1)).toMatchObject({ hidden: true, report: { reason: "hidden", visibility: "hidden" } });
    f.setVisible(true);
    await flush();
    expect(f.posts.at(-1)).toMatchObject({ hidden: false, report: { reason: "visible", visibility: "visible" } });
    r.stop();
  });

  it("409 (the run ended): back to idle, listeners removed, polling again", async () => {
    const f = fake();
    f.setActive(RUN);
    f.setPost("no_run");
    const r = new ValidationReporter(f.env);
    r.start();
    await flush();
    expect(f.posts).toHaveLength(1);
    expect(r.phase).toBe("idle");
    expect(f.listeners()).toBe(0);
    f.setActive(null);
    const polls = f.fetchActive.mock.calls.length;
    await vi.advanceTimersByTimeAsync(REPORT_INTERVAL_MS * 4);
    expect(f.posts).toHaveLength(1);
    expect(f.fetchActive.mock.calls.length).toBeGreaterThan(polls);
    r.stop();
  });

  it("post errors back off 15 s -> 30 s -> 60 s; a success resets the cadence", async () => {
    const f = fake();
    f.setActive(RUN);
    f.setPost("error");
    const r = new ValidationReporter(f.env);
    r.start();
    await flush();
    const at = () => f.posts.length;
    expect(at()).toBe(1);
    await vi.advanceTimersByTimeAsync(15_000);
    expect(at()).toBe(2);
    await vi.advanceTimersByTimeAsync(29_999);
    expect(at()).toBe(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(at()).toBe(3);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(at()).toBe(4);
    f.setPost("ok");
    await vi.advanceTimersByTimeAsync(60_000);
    expect(at()).toBe(5);
    await vi.advanceTimersByTimeAsync(REPORT_INTERVAL_MS);
    expect(at()).toBe(6);
    r.stop();
  });

  it("reports never overtake each other: a change during a slow post waits for it", async () => {
    const f = fake();
    f.setActive(RUN);
    let release: (v: ClientPostResult) => void = () => {};
    f.setPost(() => new Promise<ClientPostResult>((res) => (release = res)));
    const r = new ValidationReporter(f.env);
    r.start();
    await flush();
    expect(f.posts).toHaveLength(1);
    f.snap = { ...f.snap, route: "drive/coach" };
    f.notify();
    await vi.advanceTimersByTimeAsync(CHANGE_DEBOUNCE_MS);
    expect(f.posts).toHaveLength(1); // queued behind the slow one
    f.setPost("ok");
    release("ok");
    await flush();
    expect(f.posts).toHaveLength(2);
    expect(f.posts[1]!.report).toMatchObject({ reason: "change", seq: 2, route: "drive/coach" });
    r.stop();
  });

  it("a new run id restarts the reports for it", async () => {
    const f = fake();
    f.setActive(RUN);
    const r = new ValidationReporter(f.env);
    r.start();
    await flush();
    f.setActive({ ...RUN, id: "20261012-210000-beef" });
    r.refresh();
    await flush();
    expect(f.posts.at(-1)!.report).toMatchObject({ run_id: "20261012-210000-beef", reason: "start" });
    r.stop();
  });

  it("stop() ends everything", async () => {
    const f = fake();
    f.setActive(RUN);
    const r = new ValidationReporter(f.env);
    r.start();
    await flush();
    r.stop();
    const polls = f.fetchActive.mock.calls.length;
    const posts = f.posts.length;
    await vi.advanceTimersByTimeAsync(5 * 60_000);
    expect(f.fetchActive.mock.calls.length).toBe(polls);
    expect(f.posts.length).toBe(posts);
    expect(f.listeners()).toBe(0);
    expect(r.phase).toBe("stopped");
  });
});

describe("fps meter", () => {
  it("never runs unless the endurance test is current on a Drive page", async () => {
    const f = fake();
    f.setActive({ ...RUN, current_item: ENDURANCE_ITEM });
    f.snap = { ...f.snap, route: "setup/validation" };
    const r = new ValidationReporter(f.env);
    r.start();
    await flush();
    expect(f.rafCalls()).toBe(0);
    f.setActive(RUN); // the endurance test is no longer current…
    r.refresh();
    await flush();
    f.snap = { ...f.snap, route: "drive/coach" }; // …so opening Drive starts nothing
    f.notify();
    await flush();
    expect(f.rafCalls()).toBe(0);
    expect(f.posts.every((p) => p.report.fps_10s === null)).toBe(true);
    r.stop();
  });

  it("each 10 s window is sent once, in its own report; the meter stops when hidden", async () => {
    const f = fake();
    f.setActive({ ...RUN, current_item: ENDURANCE_ITEM });
    f.snap = { ...f.snap, route: "drive/coach" };
    const r = new ValidationReporter(f.env);
    r.start();
    await flush();
    expect(f.rafCalls()).toBe(1);
    // 600 frames over 10 s = 60 fps.
    for (let k = 1; k <= 600; k += 1) f.frame((k * FPS_WINDOW_MS) / 600);
    await flush();
    const withFps = f.posts.filter((p) => p.report.fps_10s !== null);
    expect(withFps).toHaveLength(1);
    expect(withFps[0]!.report.fps_10s).toBeCloseTo(60, 0);
    // The next report (interval) does not repeat the same window.
    await vi.advanceTimersByTimeAsync(REPORT_INTERVAL_MS);
    expect(f.posts.at(-1)!.report.fps_10s).toBeNull();
    const calls = f.rafCalls();
    f.setVisible(false);
    await flush();
    f.frame(30_000);
    expect(f.rafCalls()).toBe(calls); // cancelled: no new frame requested
    r.stop();
  });
});

describe("microphone class", () => {
  it("classified on the device once the radio is live with the mic allowed; the label is never sent", async () => {
    const f = fake();
    f.setActive(RUN);
    f.setMic(true, "James's AirPods Pro");
    const r = new ValidationReporter(f.env);
    r.start();
    await flush();
    await vi.advanceTimersByTimeAsync(CHANGE_DEBOUNCE_MS);
    const last = f.posts.at(-1)!.report;
    expect(last.audio_input_kind).toBe("airpods");
    expect(JSON.stringify(f.posts)).not.toContain("James");
    // Re-checked once a minute while allowed.
    f.setMic(true, "iPad Microphone");
    await vi.advanceTimersByTimeAsync(MIC_CHECK_MS + CHANGE_DEBOUNCE_MS);
    expect(f.posts.at(-1)!.report.audio_input_kind).toBe("built_in");
    r.stop();
  });

  it("without permission it stays unknown (null)", async () => {
    const f = fake();
    f.setActive(RUN);
    f.setMic(false, "AirPods");
    const r = new ValidationReporter(f.env);
    r.start();
    await flush();
    await vi.advanceTimersByTimeAsync(MIC_CHECK_MS * 2);
    expect(f.posts.every((p) => p.report.audio_input_kind === null)).toBe(true);
    r.stop();
  });
});
