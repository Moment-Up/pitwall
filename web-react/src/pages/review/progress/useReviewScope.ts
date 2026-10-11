// The scope Progress (6.9), the Coaching plan (6.8) and Goals share: who (`?driver=`, default the seated driver),
// where (`?track=`, default their newest track) and in what (`?car=`, default the newest car there, `any` = every
// car), plus the data they read: the driver's session rows (lap level, always) and D5's progress (when the server has
// it; Goals does not ask for it). The route is rewritten (no history entry) so it always names what is on screen.

import { useEffect, useMemo, useState } from "react";
import { useDrivers } from "../../../hooks/stores";
import { useApi } from "../../../hooks/useApi";
import type { Driver } from "../../../lib/drivers";
import {
  isMissingRoute,
  reviewApi,
  reviewKeys,
  type DriverProgress,
  type SessionListRow,
} from "../../../lib/endpoints/review";
import { queryParams, router, type Route } from "../../../lib/router";
import { coachingPath, goalsPath, progressPath } from "../../../lib/review/links";
import {
  ANY_CAR,
  pointsFromProgress,
  pointsFromRows,
  resolveScope,
  scopeChoices,
  scopeQuery,
  whoFor,
  type Scope,
  type SessionPoint,
  type TrackChoice,
  type Who,
} from "../../../lib/review/progress";

export type ScopePage = "progress" | "coaching" | "goals";

/** Where the per-session data came from: D5, or the lap-level fallback (and why). */
export type ProgressTier =
  | { kind: "d5"; data: DriverProgress }
  | { kind: "rows"; why: "missing" | "error" | "loading"; error?: Error | null };

export interface ReviewScope {
  drivers: readonly Driver[];
  driversLoaded: boolean;
  seatedId: number | null;
  viewed: Driver | null;
  who: Who;
  rows: SessionListRow[] | undefined;
  rowsError: Error | null;
  choices: TrackChoice[];
  scope: Scope | null;
  /** Synthetic tracks offered (the switch, or the route names a synthetic track). */
  includeSynthetic: boolean;
  hasSynthetic: boolean;
  /** Show synthetic tracks or not (turning it off leaves a synthetic track for the newest real one). */
  setIncludeSynthetic: (v: boolean) => void;
  tier: ProgressTier;
  points: SessionPoint[];
  /** Change the scope (driver, track, car); the route is replaced, no history entry. */
  go: (q: { driver?: number | null; track?: string | null; car?: string | null }) => void;
  pathFor: (page: ScopePage) => string;
}

function intParam(v: string | null): number | null {
  const n = Number(v);
  return v != null && Number.isInteger(n) && n > 0 ? n : null;
}

const pathOf = (page: ScopePage, q: { driver?: number | null; track?: string | null; car?: string | null }) =>
  page === "progress" ? progressPath(q) : page === "goals" ? goalsPath(q) : coachingPath(q);

/** `corners`: ask D5 for corner means. `progress: false` (Goals): no D5 request at all; the tier stays "loading". */
export function useReviewScope(route: Route, page: ScopePage, opts: { corners: boolean; progress?: boolean }): ReviewScope {
  const q = queryParams(route);
  const qDriver = intParam(q.get("driver"));
  const qTrack = q.get("track");
  const qCar = q.get("car");

  const drivers = useDrivers((s) => s.drivers);
  const driversLoaded = useDrivers((s) => s.loaded);
  const seatedId = useDrivers((s) => s.activeId);
  const viewed =
    (qDriver != null ? drivers.find((d) => d.id === qDriver) : undefined) ??
    drivers.find((d) => d.id === seatedId) ??
    drivers[0] ??
    null;
  const driverId = viewed?.id ?? null;
  const who = whoFor(viewed, seatedId, drivers.length);

  const { data: rows, error: rowsError } = useApi(driverId != null ? reviewKeys.driverSessions(driverId) : null, () =>
    reviewApi.driverSessions(driverId as number),
  );

  const [synSwitch, setIncludeSynthetic] = useState(false);
  const all = useMemo(() => scopeChoices(rows ?? [], { includeSynthetic: true }), [rows]);
  const hasSynthetic = all.some((t) => t.synthetic);
  const includeSynthetic = synSwitch || all.some((t) => t.synthetic && t.trackId === qTrack);
  const choices = useMemo(() => (includeSynthetic ? all : all.filter((t) => !t.synthetic)), [all, includeSynthetic]);
  const scope = useMemo(() => resolveScope(choices, { track: qTrack, car: qCar }), [choices, qTrack, qCar]);

  const pq = useMemo(() => (scope ? scopeQuery(scope, { corners: opts.corners }) : null), [scope, opts.corners]);
  const progress = useApi(
    opts.progress !== false && driverId != null && pq ? reviewKeys.progress(driverId, pq) : null,
    () => reviewApi.progress(driverId as number, pq ?? {}),
    { maxAgeMs: 60_000 },
  );

  const tier: ProgressTier = progress.data
    ? { kind: "d5", data: progress.data }
    : progress.error
      ? { kind: "rows", why: isMissingRoute(progress.error) ? "missing" : "error", error: progress.error }
      : { kind: "rows", why: "loading" };

  const d5 = progress.data ?? null;
  const points = useMemo(() => {
    if (!scope) return [];
    return d5 ? pointsFromProgress(d5) : pointsFromRows(rows ?? [], scope);
  }, [scope, d5, rows]);

  // Keep the route naming what is shown (driver, track, car), without a history entry.
  const shown = scope && driverId != null ? { driver: driverId, track: scope.track.trackId, car: scope.carId ?? ANY_CAR } : null;
  const want = shown ? pathOf(page, shown) : null;
  useEffect(() => {
    if (want && want !== route.path + (route.query ? `?${route.query}` : "")) router.replace(want);
  }, [want, route.path, route.query]);

  const go = (next: { driver?: number | null; track?: string | null; car?: string | null }) => {
    const driver = next.driver !== undefined ? next.driver : driverId;
    // Another driver keeps the track only if they have driven it (resolveScope falls back otherwise); the car is
    // re-picked for a new track.
    const track = next.track !== undefined ? next.track : (scope?.track.trackId ?? null);
    const car = next.car !== undefined ? next.car : next.track !== undefined || next.driver !== undefined ? null : qCar;
    router.replace(pathOf(page, { driver, track, car }));
  };

  return {
    drivers,
    driversLoaded,
    seatedId,
    viewed,
    who,
    rows,
    rowsError,
    choices,
    scope,
    includeSynthetic,
    hasSynthetic,
    setIncludeSynthetic: (v: boolean) => {
      setIncludeSynthetic(v);
      if (!v && scope?.track.synthetic) router.replace(pathOf(page, { driver: driverId }));
    },
    tier,
    points,
    go,
    pathFor: (p) => pathOf(p, shown ?? { driver: driverId }),
  };
}
