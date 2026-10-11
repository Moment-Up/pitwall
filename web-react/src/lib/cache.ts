// Request cache keyed by a string (spec 12.3): dedupes requests in flight, keeps the last data while it revalidates,
// invalidates by key prefix, refetches what is on screen when the tab regains focus. No dependency; React binds to it
// through hooks/useApi.ts (useSyncExternalStore on one key).
//
// Keys name what they hold, with ":" before ids so prefixes stay unambiguous: "sessions", "session:<id>",
// "analysis:<id>", "driver-sessions:<driver id>", "rig:recommendations", "connect". invalidate("session:") does not
// touch "sessions"; invalidate("sessions") does not touch "session:<id>".
//
// Invalidation (wired in App via useCacheInvalidation): a `lap` event on /ws/live invalidates the live session's
// "session:<id>" and "analysis:<id>", "sessions" and "driver-sessions:"; a driver switch invalidates "sessions" and
// "rig:"; a successful mutation invalidates its own prefix (callers do that).
//
// Bounded: past `maxEntries` (default 40) the least recently used keys that nobody watches and nothing is loading
// are forgotten with their fetcher, so browsing many laps (a trace is ~230 kB of JSON) does not grow the tab until
// iPad Safari reloads it (which would also drop a live radio). A forgotten key simply loads again when next shown.

export interface CacheEntry<T = unknown> {
  /** The last data that arrived (kept while revalidating and after an error). */
  readonly data: T | undefined;
  /** The last request's error, cleared by the next success. */
  readonly error: Error | null;
  /** A request for this key is in flight. */
  readonly loading: boolean;
  /** When data last arrived (ms, the cache's clock); null = never. */
  readonly updatedAt: number | null;
  /** Invalidated (or never loaded): the next load() requests it even when young. */
  readonly stale: boolean;
}

export type Fetcher<T> = () => Promise<T>;

export interface LoadOptions {
  /** Request even when the data is fresh. */
  force?: boolean;
  /** Data younger than this (and not invalidated) is served without a request. Default 30 s. */
  maxAgeMs?: number;
}

const EMPTY: CacheEntry<never> = Object.freeze({ data: undefined, error: null, loading: false, updatedAt: null, stale: true });

export const DEFAULT_MAX_AGE_MS = 30_000;
/** Keys kept before the least recently used unwatched ones are evicted. */
export const DEFAULT_MAX_ENTRIES = 40;
/** Focus refetch skips data younger than this (switching tabs quickly does not refetch everything). */
export const FOCUS_MIN_AGE_MS = 5_000;

function asError(e: unknown): Error {
  return e instanceof Error ? e : new Error(String(e));
}

export class RequestCache {
  private readonly entries = new Map<string, CacheEntry>();
  private readonly inflight = new Map<string, { gen: number; promise: Promise<unknown> }>();
  private readonly gens = new Map<string, number>();
  private readonly fetchers = new Map<string, Fetcher<unknown>>();
  private readonly listeners = new Map<string, Set<() => void>>();
  private readonly now: () => number;
  private readonly maxEntries: number;

  constructor(opts: { now?: () => number; maxEntries?: number } = {}) {
    this.now = opts.now ?? (() => Date.now());
    this.maxEntries = Math.max(1, opts.maxEntries ?? DEFAULT_MAX_ENTRIES);
  }

  /** The entry for a key (a stable object until it changes; an empty one for unknown keys). */
  readonly entry = <T>(key: string): CacheEntry<T> => (this.entries.get(key) as CacheEntry<T> | undefined) ?? EMPTY;

  /** Listen to one key's changes; returns the unsubscribe function. */
  readonly subscribe = (key: string, listener: () => void): (() => void) => {
    this.touch(key);
    let set = this.listeners.get(key);
    if (!set) {
      set = new Set();
      this.listeners.set(key, set);
    }
    set.add(listener);
    return () => {
      set.delete(listener);
      if (set.size === 0) this.listeners.delete(key);
    };
  };

  /** Keys currently held (for debugging and tests). */
  keys(): string[] {
    return [...this.entries.keys()];
  }

  private put(key: string, patch: Partial<CacheEntry>): void {
    const next = { ...this.entry(key), ...patch };
    this.entries.delete(key); // re-insert: the Map's order is least to most recently used
    this.entries.set(key, next);
    for (const l of [...(this.listeners.get(key) ?? [])]) l();
    this.evict(key);
  }

  /** Mark a key as just used (the Map's insertion order is the recency order). */
  private touch(key: string): void {
    const e = this.entries.get(key);
    if (!e) return;
    this.entries.delete(key);
    this.entries.set(key, e);
  }

  /** Over the cap: forget the least recently used keys nobody watches and nothing is loading (never `keep`). */
  private evict(keep: string): void {
    if (this.entries.size <= this.maxEntries) return;
    for (const key of [...this.entries.keys()]) {
      if (this.entries.size <= this.maxEntries) return;
      if (key === keep || this.listeners.get(key)?.size || this.inflight.has(key)) continue;
      // The generation stays (a few bytes): a superseded request still running must not write the key back.
      this.entries.delete(key);
      this.fetchers.delete(key);
    }
  }

  private isFresh(e: CacheEntry, maxAgeMs: number): boolean {
    return !e.stale && e.updatedAt !== null && this.now() - e.updatedAt < maxAgeMs;
  }

  /**
   * Load a key. A request already in flight for it is shared (dedupe); fresh data is returned without a request
   * unless `force`. The fetcher is remembered so invalidate() and focus can refetch the key. Rejects with the
   * request's error (which is also stored on the entry).
   */
  load<T>(key: string, fetcher: Fetcher<T>, opts: LoadOptions = {}): Promise<T> {
    this.fetchers.set(key, fetcher as Fetcher<unknown>);
    this.touch(key);
    const e = this.entry<T>(key);
    const gen = this.gens.get(key) ?? 0;
    const running = this.inflight.get(key);
    if (running && running.gen === gen) return running.promise as Promise<T>;
    if (!opts.force && this.isFresh(e, opts.maxAgeMs ?? DEFAULT_MAX_AGE_MS)) return Promise.resolve(e.data as T);

    this.put(key, { loading: true });
    const promise = (async () => {
      try {
        const data = await fetcher();
        if ((this.gens.get(key) ?? 0) === gen) {
          this.put(key, { data, error: null, loading: false, updatedAt: this.now(), stale: false });
        }
        return data;
      } catch (err) {
        const error = asError(err);
        if ((this.gens.get(key) ?? 0) === gen) this.put(key, { error, loading: false });
        throw error;
      } finally {
        if (this.inflight.get(key)?.gen === gen) this.inflight.delete(key);
      }
    })();
    this.inflight.set(key, { gen, promise });
    return promise;
  }

  /** Store data for a key directly (e.g. the response of a mutation). */
  set<T>(key: string, data: T): void {
    this.gens.set(key, (this.gens.get(key) ?? 0) + 1); // a request in flight must not overwrite this
    this.inflight.delete(key);
    this.put(key, { data, error: null, loading: false, updatedAt: this.now(), stale: false });
  }

  /**
   * Mark every key starting with `prefix` as stale. Keys someone is watching are refetched now (their data stays on
   * screen until the new data arrives); a request already in flight for them is superseded so its older answer
   * cannot land after the newer one. An empty prefix matches everything.
   */
  invalidate(prefix: string): void {
    const keys = new Set([...this.entries.keys(), ...this.inflight.keys()]);
    for (const key of keys) {
      if (!key.startsWith(prefix)) continue;
      this.gens.set(key, (this.gens.get(key) ?? 0) + 1);
      this.inflight.delete(key);
      this.put(key, { stale: true, loading: false });
      this.refetchIfWatched(key);
    }
  }

  private refetchIfWatched(key: string): void {
    const fetcher = this.fetchers.get(key);
    if (fetcher && this.listeners.get(key)?.size) {
      this.load(key, fetcher, { force: true }).catch(() => {
        /* stored on the entry */
      });
    }
  }

  /** Refetch watched keys older than `minAgeMs` (what a returning tab shows). */
  refetchWatched(minAgeMs = FOCUS_MIN_AGE_MS): void {
    for (const key of this.listeners.keys()) {
      const e = this.entry(key);
      if (e.loading) continue;
      if (e.updatedAt !== null && this.now() - e.updatedAt < minAgeMs && !e.stale) continue;
      this.refetchIfWatched(key);
    }
  }

  /**
   * Refetch what is on screen when the page becomes visible or the window regains focus. Install once (main.tsx);
   * returns the uninstall function. Without `window`/`document` (tests) it does nothing.
   */
  refetchOnFocus(): () => void {
    if (typeof window === "undefined" || typeof document === "undefined") return () => {};
    const onFocus = () => this.refetchWatched();
    const onVisible = () => {
      if (document.visibilityState === "visible") this.refetchWatched();
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }

  /** Forget everything (tests; a driver switch does not need it, use invalidate). */
  clear(): void {
    this.entries.clear();
    this.inflight.clear();
    this.gens.clear();
    this.fetchers.clear();
  }
}

/** The app's one cache. */
export const cache = new RequestCache();
