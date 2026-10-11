// The 10 Hz delta throttle (spec 4.5, 4.11): leading + trailing, never more than one change per interval.
import { describe, expect, it } from "vitest";
import { createThrottle } from "./useThrottledValue";

describe("createThrottle", () => {
  it("shows the first value at once and holds changes inside the interval", () => {
    const t = createThrottle<string>(100);
    expect(t.push("−0.21", 0)).toBe("−0.21");
    expect(t.push("−0.22", 30)).toBeUndefined();
    expect(t.push("−0.23", 60)).toBeUndefined();
    expect(t.dueAt()).toBe(100);
    expect(t.flush(99)).toBeNull();
    expect(t.flush(100)).toEqual({ value: "−0.23" }); // the newest held value, never an older one
    expect(t.dueAt()).toBeNull();
  });

  it("at 20 Hz input shows at most 10 values a second and always the newest one", () => {
    const t = createThrottle<number>(100);
    const shown: number[] = [];
    for (let i = 0; i < 40; i += 1) {
      const now = i * 50; // 20 Hz for 2 s
      const due = t.dueAt();
      if (due != null && now >= due) {
        const out = t.flush(now);
        if (out) shown.push(out.value);
      }
      const v = t.push(i, now);
      if (v !== undefined) shown.push(v);
    }
    const due = t.dueAt();
    if (due != null) shown.push(t.flush(due)!.value);
    expect(shown.length).toBeLessThanOrEqual(21);
    expect(shown.at(-1)).toBe(39);
  });

  it("an unchanged value never schedules anything, and returning to the shown value cancels a held one", () => {
    const t = createThrottle<string>(100);
    t.push("+0.53", 0);
    expect(t.push("+0.53", 10)).toBeUndefined();
    expect(t.dueAt()).toBeNull();
    t.push("+0.54", 20);
    expect(t.dueAt()).toBe(100);
    t.push("+0.53", 40);
    expect(t.dueAt()).toBeNull();
  });

  it("shows a change at once when the interval has passed", () => {
    const t = createThrottle<string>(100);
    t.push("a", 0);
    expect(t.push("b", 150)).toBe("b");
    expect(t.push("c", 260)).toBe("c");
  });

  it("uses the equality function (view models compared by content)", () => {
    const t = createThrottle<{ text: string }>(100, (a, b) => a.text === b.text);
    const first = { text: "−0.21" };
    expect(t.push(first, 0)).toBe(first);
    expect(t.push({ text: "−0.21" }, 200)).toBeUndefined();
  });
});
