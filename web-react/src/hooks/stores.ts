// React bindings for the framework-agnostic stores (src/lib) via useSyncExternalStore.
// Selectors must return values that are stable between store updates (fields of the state, or primitives); derive
// new objects with useMemo in the component instead of in the selector.

import { useEffect, useSyncExternalStore } from "react";
import { activeDriver, drivers, type Driver, type DriversState } from "../lib/drivers";
import { live, type LiveState } from "../lib/live";
import { prefs, type Prefs, type PrefsState, type ThemeName } from "../lib/prefs";
import { router, type AreaId, type Route, type RouterState } from "../lib/router";
import type { Store } from "../lib/store";

export function useStore<S extends object, T>(store: Store<S>, select: (s: S) => T): T {
  return useSyncExternalStore(
    store.subscribe,
    () => select(store.get()),
    () => select(store.get()),
  );
}

/** Live telemetry (/ws/live). Call useLiveConnection() once near the root to own the socket. */
export function useLive<T>(select: (s: LiveState) => T): T {
  return useStore(live, select);
}

/** Owns the /ws/live socket for the lifetime of the calling component (ref-counted, StrictMode-safe). */
export function useLiveConnection(): void {
  useEffect(() => live.start(), []);
}

/** Driver profiles; polling runs while at least one component using this hook is mounted. */
export function useDrivers<T>(select: (s: DriversState) => T): T {
  useEffect(() => drivers.start(), []);
  return useStore(drivers, select);
}

export function useActiveDriver(): Driver | null {
  return useDrivers(activeDriver);
}

export function useRoute(): Route {
  return useStore(router, (s) => s.route);
}

export function useRouter<T>(select: (s: RouterState) => T): T {
  return useStore(router, select);
}

/** The path an area link opens (its remembered sub-page; Setup: Game until a game is selected, then Connect until a
 * real session exists). */
export function useAreaPath(area: AreaId): string {
  useRouter((s) => s.remembered);
  useRouter((s) => s.hasRealSession);
  useRouter((s) => s.gameSelected);
  return router.areaPath(area);
}

/** Display preferences (per device): `usePrefs((p) => p.driveLock)`. Change them with prefs.setPref(). */
export function usePrefs<T>(select: (p: Prefs) => T): T {
  return useStore(prefs, (s) => select(s.prefs));
}

export function usePrefsState<T>(select: (s: PrefsState) => T): T {
  return useStore(prefs, select);
}

/** Radio state (lane A's binding, re-exported here as spec 12.3 lists it): `useRadio((s) => s.phase)`. */
export { useRadio } from "../components/radio/useRadio";

/** The theme on screen now (dark on Drive with "Drive always dark"). */
export function useTheme(): ThemeName {
  return useStore(prefs, (s) => s.theme);
}
