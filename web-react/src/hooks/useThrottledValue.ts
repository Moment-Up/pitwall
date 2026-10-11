// A value that changes at most every `intervalMs` (design spec 4.5, 4.11: the Drive delta string is recomputed at
// most 10 times a second). Leading and trailing: the first change shows at once, later changes inside the window
// are held and the newest one shows when the window ends, so the screen never stays behind the data for more than
// one interval and never drops the last value. Lane DV.
//
// `createThrottle` is the framework-free core (tested in plain node); `useThrottledValue` binds it to React.

import { useEffect, useRef, useState } from "react";

export interface Throttle<T> {
  /** Offer a new value at time `nowMs`. Returns the value to show now, or `undefined` to keep the shown one. */
  push(value: T, nowMs: number): T | undefined;
  /** When a held value is due (ms timestamp), or null when nothing is held. */
  dueAt(): number | null;
  /** Take the held value once it is due (null when nothing is held). */
  flush(nowMs: number): { value: T } | null;
}

export function createThrottle<T>(intervalMs: number, equal: (a: T, b: T) => boolean = Object.is): Throttle<T> {
  let shown: { value: T; at: number } | null = null;
  let held: { value: T } | null = null;
  return {
    push(value, nowMs) {
      if (shown && equal(shown.value, value)) {
        held = null; // back to what is on screen: nothing to show later
        return undefined;
      }
      if (!shown || nowMs - shown.at >= intervalMs) {
        shown = { value, at: nowMs };
        held = null;
        return value;
      }
      held = { value };
      return undefined;
    },
    dueAt() {
      return held && shown ? shown.at + intervalMs : null;
    },
    flush(nowMs) {
      if (!held || !shown || nowMs < shown.at + intervalMs) return null;
      const out = held;
      shown = { value: out.value, at: nowMs };
      held = null;
      return out;
    },
  };
}

/** `value`, updated at most every `intervalMs` (the newest value always lands within one interval). */
export function useThrottledValue<T>(value: T, intervalMs: number, equal: (a: T, b: T) => boolean = Object.is): T {
  const [shown, setShown] = useState(value);
  const throttle = useRef<Throttle<T> | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  throttle.current ??= createThrottle<T>(intervalMs, equal);

  useEffect(() => {
    const t = throttle.current!;
    const now = performance.now();
    const next = t.push(value, now);
    if (next !== undefined) {
      setShown(() => next);
      return;
    }
    const due = t.dueAt();
    if (due == null || timer.current) return;
    timer.current = setTimeout(
      () => {
        timer.current = null;
        // Timers may fire a fraction of a millisecond early: never earlier than the due time.
        const out = t.flush(Math.max(performance.now(), t.dueAt() ?? 0));
        if (out) setShown(() => out.value);
      },
      Math.max(0, due - now),
    );
  }, [value]);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
      timer.current = null;
    },
    [],
  );

  return shown;
}
