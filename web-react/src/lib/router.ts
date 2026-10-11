// Hash router (framework-agnostic). Hash routing means FastAPI's StaticFiles(html=True) can serve the app at /next/
// (or /) with no rewrite rules, and `?token=` in the query string survives navigation untouched.
//
// Parsing is pure and lives in ./route-parse.ts (unit-tested); this module is the store around window.location.
// Legacy and partial hashes are rewritten to the canonical one with history.replaceState (no extra history entry),
// keeping any query inside the hash (`#/radio?token=…` -> `#/drive/radio?token=…`).
//
// Landing rules (spec 2.5): every area remembers its last sub-page per device (localStorage `pitwall-area-pages`,
// read and written in try/catch - when storage is unavailable an area opens on its first page), and Setup opens on
// Connect while there is no real (non-synthetic) session yet (`setHasRealSession`, fed by the shell from
// GET /api/sessions).

import { rememberUrlToken } from "./auth";
import {
  areaPath,
  canonicalHash,
  href,
  isAreaId,
  isPage,
  parseHash,
  type AreaId,
  type RememberedPages,
  type Route,
} from "./route-parse";
import { Store } from "./store";

export * from "./route-parse";

export const AREA_PAGES_KEY = "pitwall-area-pages";

/** Remembered sub-pages from storage; anything malformed or unknown is dropped. Exported for tests. */
export function readRemembered(raw: string | null): RememberedPages {
  if (!raw) return {};
  try {
    const v = JSON.parse(raw) as unknown;
    if (!v || typeof v !== "object") return {};
    const out: RememberedPages = {};
    for (const [k, p] of Object.entries(v as Record<string, unknown>)) {
      if (isAreaId(k) && typeof p === "string" && isPage(k, p)) out[k] = p;
    }
    return out;
  } catch {
    return {};
  }
}

function loadRemembered(): RememberedPages {
  try {
    return readRemembered(localStorage.getItem(AREA_PAGES_KEY));
  } catch {
    return {};
  }
}

function saveRemembered(r: RememberedPages): void {
  try {
    localStorage.setItem(AREA_PAGES_KEY, JSON.stringify(r));
  } catch {
    /* storage unavailable (private mode, blocked): areas open on their first page next time */
  }
}

export interface RouterState {
  route: Route;
  /** The last sub-page used per area on this device. */
  remembered: RememberedPages;
  /** Whether GET /api/sessions has a non-synthetic session; null until known. */
  hasRealSession: boolean | null;
}

export class Router extends Store<RouterState> {
  constructor() {
    const remembered = loadRemembered();
    super({ route: parseHash(window.location.hash, remembered), remembered, hasRealSession: null });
    this.onLocation();
    window.addEventListener("hashchange", () => {
      this.set({ route: parseHash(window.location.hash, this.get().remembered) });
      this.onLocation();
    });
  }

  private onLocation(): void {
    // A token in the hash is dropped by the next in-app navigation; keep it for the tab before that can happen.
    rememberUrlToken();
    this.canonicalise();
    this.remember(this.get().route);
  }

  private remember(route: Route): void {
    const prev = this.get().remembered;
    if (prev[route.area] === route.page) return;
    const remembered = { ...prev, [route.area]: route.page };
    saveRemembered(remembered);
    this.set({ remembered });
  }

  /** Rewrite legacy / partial hashes to the canonical one without adding a history entry. */
  private canonicalise(): void {
    const want = canonicalHash(this.get().route);
    if (window.location.hash !== want) {
      const url = `${window.location.pathname}${window.location.search}${want}`;
      window.history.replaceState(window.history.state, "", url);
    }
  }

  /** Go to a path (it may carry a "?query"), adding a history entry. */
  navigate(path: string): void {
    const want = href(path);
    if (window.location.hash !== want) window.location.hash = want;
  }

  /** Replace the current entry (no history entry), e.g. a Compare cursor or a filter kept in the query. */
  replace(path: string): void {
    const route = parseHash(href(path), this.get().remembered);
    const want = canonicalHash(route);
    if (window.location.hash !== want) {
      window.history.replaceState(window.history.state, "", `${window.location.pathname}${window.location.search}${want}`);
    }
    this.set({ route });
    this.remember(route);
  }

  /** The path an area link opens: its remembered sub-page (Setup: Connect until a real session exists). */
  areaPath(area: AreaId): string {
    const s = this.get();
    return areaPath(area, s.remembered, s.hasRealSession);
  }

  /** Open an area on its landing page. */
  goArea(area: AreaId): void {
    this.navigate(this.areaPath(area));
  }

  /** Fed by the shell from GET /api/sessions (any session with synthetic == false). */
  setHasRealSession(v: boolean | null): void {
    this.set({ hasRealSession: v });
  }
}

export const router = new Router();
