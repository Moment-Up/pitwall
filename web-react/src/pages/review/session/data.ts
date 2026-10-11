// Data hooks for one session (spec 12.3): the row with its laps, its analysis, lap traces, a comparison and the
// engineer conversation. Cached by key, so the Sessions preview, the session page and its tabs share one request
// each; a completed lap of the live session invalidates the session and its analyses (hooks/useApi.ts).

import { useMemo } from "react";
import { useDrivers } from "../../../hooks/stores";
import { useApi } from "../../../hooks/useApi";
import {
  allTimeBests,
  sessionBadge,
  sessionBests,
  type BestBadge,
  type BestsOptions,
  type ScopeRow,
  type SessionBests,
} from "../../../lib/bests";
import { reviewApi, reviewKeys, SESSION_LIST_LIMIT, type SessionListRow } from "../../../lib/endpoints/review";
import { coachrefApi, coachrefKeys, compareWithReference } from "../../../lib/endpoints/coachref";

export function useSession(id: string | null) {
  return useApi(id ? reviewKeys.session(id) : null, () => reviewApi.session(id as string));
}

/** The analysis is computed on request (about 3 ms a lap) and cached server-side; keep it a minute here. */
export function useAnalysis(id: string | null) {
  return useApi(id ? reviewKeys.analysis(id) : null, () => reviewApi.analysis(id as string), { maxAgeMs: 60_000 });
}

/** The analysis against another reference lap (Laps "Set as reference"); the session's own reference when null. */
export function useAnalysisRef(id: string | null, refLapId: number | null) {
  return useApi(
    id ? reviewKeys.analysisRef(id, refLapId) : null,
    () => reviewApi.analysis(id as string, refLapId),
    { maxAgeMs: 60_000 },
  );
}

/** A stored lap's channels on a 5 m grid (never changes once recorded). */
export function useTrace(lapId: number | null) {
  return useApi(lapId != null ? reviewKeys.trace(lapId) : null, () => reviewApi.trace(lapId as number, 5), {
    maxAgeMs: 30 * 60_000,
  });
}

/** Two laps compared (identical inputs give identical output; the track model can grow, so a minute). */
export function useCompare(ref: number | null, lap: number | null) {
  const ok = ref != null && lap != null && ref !== lap;
  return useApi(ok ? reviewKeys.compare(ref, lap) : null, () => reviewApi.compare(ref as number, lap as number), {
    maxAgeMs: 60_000,
  });
}

// --- coachref ---
/** Two laps compared through /api/coachref/compare: the /api/compare body plus who A belongs to (`reference`), with
 * the coach's observations named after another driver's lap. Falls back to /api/compare on a server without it.
 * Same cache key as useCompare: the body is a superset, and neither depends on the driver's reference choice. */
export function useRefCompare(ref: number | null, lap: number | null) {
  const ok = ref != null && lap != null && ref !== lap;
  return useApi(ok ? reviewKeys.compare(ref, lap) : null, () => compareWithReference(ref as number, lap as number), {
    maxAgeMs: 60_000,
  });
}

/** Picker A's family laps for lap B (compatible ones, the others with a reason); an error leaves the old group. */
export function useCandidates(lapId: number | null) {
  return useApi(lapId != null ? coachrefKeys.candidates(lapId) : null, () => coachrefApi.candidates(lapId as number), {
    maxAgeMs: 60_000,
  });
}
// --- /coachref ---

/** The stored engineer conversation of a session. */
export function useHistory(sessionId: string | null) {
  return useApi(sessionId ? reviewKeys.history(sessionId) : null, () => reviewApi.history(sessionId), { maxAgeMs: 60_000 });
}

/**
 * The window the timing badges are found in (lib/bests.ts): everyone's newest sessions (the Sessions list's own
 * request, so no extra load) and each driver's all-time bests for when the window is cut off. `rows` is null until
 * loaded.
 */
export function useBestsWindow(): { rows: readonly SessionListRow[] | null; opts: BestsOptions } {
  const { data } = useApi(reviewKeys.sessions, () => reviewApi.sessions());
  const drivers = useDrivers((s) => s.drivers);
  const opts = useMemo<BestsOptions>(
    () => ({ complete: !!data && data.length < SESSION_LIST_LIMIT, allTime: allTimeBests(drivers) }),
    [data, drivers],
  );
  return { rows: data ?? null, opts };
}

/**
 * One session's bests (its scope: game, track, car, layout) and its best lap's badge under the one rule (REC / PB /
 * SB); both null until the window is loaded. `bestMs`: the session's best clean lap (from its laps).
 */
export function useSessionBests(
  session: (Omit<ScopeRow, "best_clean_ms"> & { best_clean_ms?: number | null }) | null | undefined,
  bestMs: number | null,
): { bests: SessionBests | null; badge: BestBadge | null } {
  const { rows, opts } = useBestsWindow();
  return useMemo(() => {
    if (!session || !rows) return { bests: null, badge: null };
    const row: ScopeRow = { ...session, best_clean_ms: bestMs };
    const bests = sessionBests(row, rows, opts);
    return { bests, badge: sessionBadge(row, bests) };
  }, [session, bestMs, rows, opts]);
}

/** A list row's badge (its best clean lap) under the one rule: "rec" / "pb" / "sb" / "neutral"; null until loaded. */
export function useRowBadge(row: ScopeRow | null | undefined): BestBadge | null {
  const { rows, opts } = useBestsWindow();
  return useMemo(() => (row && rows ? sessionBadge(row, sessionBests(row, rows, opts)) : null), [row, rows, opts]);
}

export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}
