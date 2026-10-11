import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { deferred, flush, json, stubBrowser } from "../test/fakes";
import { resetTokenCacheForTests } from "./auth";
import { DriverStore, initialsFor, type Driver } from "./drivers";

function driver(id: number, name: string): Driver {
  return {
    id,
    name,
    created_unix: 0,
    preferences: {
      colour: "#ff6a2b",
      initials: initialsFor(name),
      skill_level: "beginner",
      coaching_intensity: "normal",
      voice_enabled: true,
    },
    coaching: {} as Driver["coaching"],
    active: false,
    stats: { sessions: 0, laps: 0, clean_laps: 0, tracks: 0, last_session_unix: null, best_laps: [] },
  };
}

const LIST = [driver(1, "Alex Racer"), driver(2, "Sam Racer")];
const list = (activeId: number) => json({ active_id: activeId, radio_follows_driver: false, drivers: LIST });

interface Call {
  method: string;
  path: string;
  reply: ReturnType<typeof deferred<Response>>;
}

/** fetch() whose every response the test releases explicitly, in any order. */
function controlledFetch(): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init?: RequestInit) => {
      const reply = deferred<Response>();
      calls.push({ method: init?.method ?? "GET", path, reply });
      return reply.promise;
    }),
  );
  return calls;
}

function call(calls: Call[], i: number): Call {
  const c = calls[i];
  if (!c) throw new Error(`no fetch #${i} (only ${calls.length})`);
  return c;
}

beforeEach(() => {
  stubBrowser("http://127.0.0.1:8770/next/#/settings/drivers");
  resetTokenCacheForTests();
});
afterEach(() => vi.unstubAllGlobals());

describe("DriverStore", () => {
  it("concurrent refreshes share one GET when nothing was mutated", async () => {
    const calls = controlledFetch();
    const store = new DriverStore();
    const a = store.refresh();
    const b = store.refresh();
    expect(calls).toHaveLength(1);
    call(calls, 0).reply.resolve(list(1));
    await Promise.all([a, b]);
    expect(store.get()).toMatchObject({ activeId: 1, loaded: true, error: null });
  });

  it("a GET sent before a switch cannot undo it, even when it answers mid-switch", async () => {
    const calls = controlledFetch();
    const store = new DriverStore();
    void store.refresh(); // GET #0, answers late with the old seat
    const switching = store.setActive(2); // PUT #1
    expect(store.get()).toMatchObject({ activeId: 2, switching: true }); // optimistic
    expect(call(calls, 1)).toMatchObject({ method: "PUT", path: "/api/drivers/active" });

    call(calls, 0).reply.resolve(list(1)); // stale: predates the PUT
    await flush();
    expect(store.get().activeId).toBe(2);

    call(calls, 1).reply.resolve(json(driver(2, "Sam Racer")));
    await flush();
    // The post-mutation refresh is a NEW GET, not the stale one.
    expect(call(calls, 2)).toMatchObject({ method: "GET", path: "/api/drivers" });
    call(calls, 2).reply.resolve(list(2));
    await switching;
    expect(store.get()).toMatchObject({ activeId: 2, switching: false, loaded: true });
  });

  it("a GET sent before a switch that answers after the post-switch refresh is ignored", async () => {
    const calls = controlledFetch();
    const store = new DriverStore();
    void store.refresh(); // GET #0
    const switching = store.setActive(2); // PUT #1
    call(calls, 1).reply.resolve(json(driver(2, "Sam Racer")));
    await flush();
    call(calls, 2).reply.resolve(list(2)); // fresh GET
    await switching;
    call(calls, 0).reply.resolve(list(1)); // the old answer finally arrives
    await flush();
    expect(store.get().activeId).toBe(2);
  });

  it("a refused switch rolls the seat back and the refresh brings the server's truth", async () => {
    const calls = controlledFetch();
    const store = new DriverStore();
    const first = store.refresh();
    call(calls, 0).reply.resolve(list(1));
    await first;

    const switching = store.setActive(2);
    const failed = expect(switching).rejects.toThrow("driver is locked");
    call(calls, 1).reply.resolve(json({ detail: "driver is locked" }, 409));
    await flush();
    expect(store.get().activeId).toBe(1); // rolled back before the refresh answers
    call(calls, 2).reply.resolve(list(1));
    await failed;
    expect(store.get()).toMatchObject({ activeId: 1, switching: false });
  });

  it("ignores taps while a switch is in flight and a switch to the driver already seated", async () => {
    const calls = controlledFetch();
    const store = new DriverStore();
    const first = store.refresh();
    call(calls, 0).reply.resolve(list(1));
    await first;
    await store.setActive(1);
    expect(calls).toHaveLength(1);
    void store.setActive(2);
    void store.setActive(1);
    expect(calls).toHaveLength(2);
  });
});
