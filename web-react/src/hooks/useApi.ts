// React binding for the request cache (src/lib/cache.ts, spec 12.3).
//
//   const { data, error, loading, refresh } = useApi("sessions", api.sessions);
//   const s = useApi(id ? `session:${id}` : null, () => api.session(id!));      // null key = nothing to load
//   const c = useApi("connect", connectApi.get, { intervalMs: 2000 });          // polls while mounted and visible
//
// The fetcher may be a new closure on every render: the latest one is used, and only a key change refetches.
// `data` stays while a refetch runs and after an error (show both: stale data with the error, never a blank).

import { useCallback, useEffect, useRef, useSyncExternalStore } from "react";
import { cache, type CacheEntry, type Fetcher } from "../lib/cache";
import { live } from "../lib/live";
import { drivers } from "../lib/drivers";

export interface UseApiOptions {
  /** Poll every n ms while mounted (paused while the page is hidden). Only where data changes on its own. */
  intervalMs?: number;
  /** false = do not load (like a null key, but keeps the last data on screen). */
  enabled?: boolean;
  /** Serve cached data younger than this without a request on mount (default 30 s; invalidation always refetches). */
  maxAgeMs?: number;
}

export interface UseApiResult<T> {
  data: T | undefined;
  error: Error | null;
  /** A request is in flight (also true during a background refetch: use `data === undefined` for first load). */
  loading: boolean;
  /** Request now (ignores freshness). Never rejects: the error lands in `error`. */
  refresh: () => Promise<void>;
}

const NO_KEY = (): (() => void) => () => {};
const EMPTY_ENTRY: CacheEntry<never> = Object.freeze({
  data: undefined,
  error: null,
  loading: false,
  updatedAt: null,
  stale: true,
});

function isHidden(): boolean {
  return typeof document !== "undefined" && document.visibilityState === "hidden";
}

export function useApi<T>(key: string | null, fetcher: Fetcher<T>, opts: UseApiOptions = {}): UseApiResult<T> {
  const { intervalMs, enabled = true, maxAgeMs } = opts;
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const latest = useCallback(() => fetcherRef.current(), []);

  const subscribe = useCallback((l: () => void) => (key ? cache.subscribe(key, l) : NO_KEY()), [key]);
  const getSnapshot = useCallback(() => (key ? cache.entry<T>(key) : (EMPTY_ENTRY as CacheEntry<T>)), [key]);
  const entry = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  useEffect(() => {
    if (!key || !enabled) return;
    cache.load(key, latest, { maxAgeMs }).catch(() => {
      /* stored on the entry */
    });
    if (!intervalMs) return;
    const t = setInterval(() => {
      if (isHidden()) return;
      cache.load(key, latest, { force: true }).catch(() => {});
    }, intervalMs);
    return () => clearInterval(t);
  }, [key, enabled, intervalMs, maxAgeMs, latest]);

  const refresh = useCallback(async () => {
    if (!key) return;
    try {
      await cache.load(key, latest, { force: true });
    } catch {
      /* stored on the entry */
    }
  }, [key, latest]);

  return { data: entry.data, error: entry.error, loading: entry.loading, refresh };
}

/**
 * The app-wide invalidation rules (spec 12.3). Mount once (App): a `lap` event on /ws/live invalidates the live
 * session and the session lists; a driver switch invalidates the session lists and the rig recommendations.
 */
export function useCacheInvalidation(): void {
  useEffect(() => {
    let lastLap = live.get().lastLapEvent;
    const offLive = live.subscribe(() => {
      const s = live.get();
      if (s.lastLapEvent === lastLap) return;
      lastLap = s.lastLapEvent;
      const id = s.snap?.session_id;
      if (id) {
        cache.invalidate(`session:${id}`);
        cache.invalidate(`analysis:${id}`);
      }
      cache.invalidate("sessions");
      cache.invalidate("driver-sessions:");
    });
    let active = drivers.get().activeId;
    const offDrivers = drivers.subscribe(() => {
      const next = drivers.get().activeId;
      if (next === active) return;
      const first = active === null;
      active = next;
      if (first) return; // the first load is not a switch
      cache.invalidate("sessions");
      cache.invalidate("driver-sessions:");
      cache.invalidate("rig:");
    });
    return () => {
      offLive();
      offDrivers();
    };
  }, []);
}
