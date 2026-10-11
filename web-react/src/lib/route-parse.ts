// Pure hash-route parsing (no window access, so it runs under unit tests in node). The router store in ./router.ts
// wraps it and re-exports everything here. Design: docs/ui/design-spec.md 2.3-2.5 and 12.2.
//
// Routes are "#/<area>/<page>[/<param>][?<query>]"; `param` is every segment after the page, so
// "#/review/sessions/<id>/compare" gives param "<id>/compare". The query inside the hash is kept as-is on the
// canonical hash: the Svelte dashboard accepts `#/radio?token=…` (web/src/lib/radio.svelte.ts tokenFromUrl), which is
// the only way a LAN device without the auth cookie authenticates, so a legacy link must not lose it (see ./auth.ts,
// which also remembers the token for the tab so navigating away from that hash keeps working).
//
// Old Svelte-dashboard hashes (#/live, #/sessions/<id>, #/profiles, #/settings, ...) and the interim web-react ids
// (#/drive/live, #/review/compare, #/settings/engine, #/settings/status) map to the new paths. Unknown pages fall
// back to the area's default page; unknown areas fall back to Drive.

export type AreaId = "drive" | "review" | "setup" | "settings";

export interface Route {
  area: AreaId;
  /** Sub-page id within the area (an area's default page when the hash names none or an unknown one). */
  page: string;
  /** Every segment after the page, joined with "/" (decoded), e.g. "<id>/compare"; null when there is none. */
  param: string | null;
  /** Normalised path without the leading "#" or the query, e.g. "/review/sessions/abc". */
  path: string;
  /** The query inside the hash without its "?" ("token=abc"), or "" when there is none. */
  query: string;
}

export const AREA_IDS: readonly AreaId[] = ["drive", "review", "setup", "settings"];

/** Page ids per area, in display order. The single list the router validates against; src/routes.tsx registers a
 * component for each (a unit test keeps the two in step). */
export const AREA_PAGES: Readonly<Record<AreaId, readonly string[]>> = {
  drive: ["coach", "car", "track", "radio"],
  review: ["sessions", "coaching", "progress", "ask"],
  setup: ["game", "connect", "rig", "car", "validation"], // "validation": validation kit (lane validate)
  settings: ["drivers", "radio", "ai", "display", "system"],
};

/** Default sub-page per area (spec 12.2): where an area lands with nothing remembered. */
export const DEFAULT_PAGE: Readonly<Record<AreaId, string>> = {
  drive: "coach",
  review: "sessions",
  setup: "rig",
  settings: "drivers",
};

/** Interim area-qualified ids (web-react at /next/ before v2) -> their v2 page. Any param after them is dropped. */
export const AREA_ALIASES: Readonly<Record<string, string>> = {
  "drive/live": "drive/coach",
  "review/compare": "review/sessions",
  "settings/engine": "settings/ai",
  "settings/status": "settings/system",
};

/** The last sub-page used per area (per device; see router.ts). */
export type RememberedPages = Partial<Record<AreaId, string>>;

export function isAreaId(s: string | null | undefined): s is AreaId {
  return (AREA_IDS as readonly (string | null | undefined)[]).includes(s);
}

export function isPage(area: AreaId, page: string | null | undefined): page is string {
  return page != null && AREA_PAGES[area].includes(page);
}

/**
 * The page an area opens on (spec 2.1 / 2.5): the remembered sub-page when it is a real page, else the default.
 * Setup opens on Game while no game is selected (`gameSelected === false`, game-selection spec 5.1), else on Connect
 * while there is no real (non-synthetic) session yet (`hasRealSession === false`); `null` means "not known yet" (or
 * a server that predates game selection) and changes nothing.
 */
export function landingPage(
  area: AreaId,
  remembered?: RememberedPages,
  hasRealSession: boolean | null = null,
  gameSelected: boolean | null = null,
): string {
  if (area === "setup" && gameSelected === false) return "game";
  if (area === "setup" && hasRealSession === false) return "connect";
  const r = remembered?.[area];
  return isPage(area, r) ? r : DEFAULT_PAGE[area];
}

/** The full path an area link points at, e.g. "/settings/drivers". Navigation links use this, never a bare
 * "/<area>": a bare "#/settings" is the Svelte dashboard's AI-settings link (see legacyRedirect). */
export function areaPath(
  area: AreaId,
  remembered?: RememberedPages,
  hasRealSession: boolean | null = null,
  gameSelected: boolean | null = null,
): string {
  return `/${area}/${landingPage(area, remembered, hasRealSession, gameSelected)}`;
}

/** Split a location hash ("#/radio?token=x") into its path ("/radio") and query ("token=x"). */
export function splitHash(hash: string): { path: string; query: string } {
  const h = hash.replace(/^#/, "");
  const i = h.indexOf("?");
  let path = i >= 0 ? h.slice(0, i) : h;
  const query = i >= 0 ? h.slice(i + 1) : "";
  if (!path.startsWith("/")) path = `/${path}`;
  return { path, query };
}

/**
 * Svelte-dashboard and interim hashes -> new paths (`path` without the query), or null when `path` is not a legacy
 * one (spec 2.4). Bare `#/review` is not here: it opens the remembered sub-page (see parseHash).
 */
export function legacyRedirect(path: string): string | null {
  const seg = (path.split("?")[0] ?? "").split("/").filter(Boolean);
  const head = seg[0];
  const rest = seg.slice(1).join("/");
  if (seg.length >= 2) {
    const alias = AREA_ALIASES[`${seg[0]}/${seg[1]}`];
    if (alias) return `/${alias}`;
  }
  switch (head) {
    case undefined:
      return "/drive/coach";
    case "live":
      return "/drive/coach";
    case "drive":
      return rest ? null : "/drive/coach";
    case "radio":
      // Permanent: docs/radio-setup.md and Home Screen icons use #/radio (with ?token=).
      return "/drive/radio";
    case "sessions":
      return rest ? `/review/sessions/${rest}` : "/review/sessions";
    case "engineer":
      return "/review/ask";
    case "setup":
      // Bare #/setup was the Svelte rig page (SetupView).
      return rest ? null : "/setup/rig";
    case "connect":
      return "/setup/connect";
    case "carsetup":
      return "/setup/car";
    case "profiles":
      return "/settings/drivers";
    case "settings":
      // Bare #/settings was the Svelte AI page (SettingsView), not the Settings area's default (Drivers).
      return rest ? null : "/settings/ai";
    case "status":
      return "/settings/system";
    default:
      return null;
  }
}

function decodeSegment(s: string): string {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
}

/**
 * Parse a location hash ("#/review/sessions/abc") into a route. Legacy hashes are redirected (2.4), bare `#/review`
 * opens the remembered Review page, unknown pages open the area's default and unknown areas open Drive.
 */
export function parseHash(hash: string, remembered?: RememberedPages): Route {
  const { path: raw, query } = splitHash(hash);
  const path = legacyRedirect(raw) ?? raw;
  const seg = path.split("/").filter(Boolean).map(decodeSegment);
  const known = isAreaId(seg[0]);
  const area: AreaId = known ? (seg[0] as AreaId) : "drive";
  let page: string;
  let params: string[] = [];
  if (!known || seg.length < 2) {
    page = known ? landingPage(area, remembered) : DEFAULT_PAGE.drive;
  } else if (isPage(area, seg[1])) {
    page = seg[1] as string;
    params = seg.slice(2);
  } else {
    page = DEFAULT_PAGE[area];
  }
  const norm = `/${[area, page, ...params].map(encodeURIComponent).join("/")}`;
  return { area, page, param: params.length ? params.join("/") : null, path: norm, query };
}

/** href for a route path (which may carry its own "?query"), e.g. href("/review/sessions") -> "#/review/sessions". */
export function href(path: string): string {
  return `#${path.startsWith("/") ? path : `/${path}`}`;
}

/** The canonical location hash for a route: its normalised path plus the query it arrived with. */
export function canonicalHash(route: Pick<Route, "path" | "query">): string {
  return `${href(route.path)}${route.query ? `?${route.query}` : ""}`;
}

/** Query values for withQuery: null, undefined and "" are left out. */
export type QueryValues = Record<string, string | number | boolean | null | undefined>;

/** A path with a query: withQuery("/review/progress", { driver: 2, track: "silverstone" }). Keys keep their order. */
export function withQuery(path: string, values: QueryValues): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(values)) {
    if (v === null || v === undefined || v === "") continue;
    q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `${path}?${s}` : path;
}

/** The route's query as URLSearchParams (read with .get("ref") etc.). */
export function queryParams(route: Pick<Route, "query">): URLSearchParams {
  return new URLSearchParams(route.query);
}

/** A path from encoded segments: pathOf("review", "sessions", id, "compare") -> "/review/sessions/<id>/compare". */
export function pathOf(...segments: (string | number)[]): string {
  return `/${segments.map((s) => encodeURIComponent(String(s))).join("/")}`;
}

// ---------------------------------------------------------------------------------------------------- page params

export type SessionTab = "summary" | "laps" | "compare" | "corners" | "ask";
export const SESSION_TABS: readonly SessionTab[] = ["summary", "laps", "compare", "corners", "ask"];

/** `#/review/sessions/<id>[/<tab>]`: param "<id>/<tab>" -> { id, tab }. No id = the list; unknown tab = Summary. */
export function parseSessionParam(param: string | null): { id: string | null; tab: SessionTab } {
  const [id, tab] = (param ?? "").split("/");
  return {
    id: id ? id : null,
    tab: (SESSION_TABS as readonly (string | undefined)[]).includes(tab) ? (tab as SessionTab) : "summary",
  };
}

/** Path of a session tab: sessionPath("abc", "compare") -> "/review/sessions/abc/compare" (Summary has no suffix). */
export function sessionPath(id: string, tab: SessionTab = "summary"): string {
  return tab === "summary" ? pathOf("review", "sessions", id) : pathOf("review", "sessions", id, tab);
}

export type RigView = "walk" | "settings" | "check" | "upgrades";
export const RIG_VIEWS: readonly RigView[] = ["walk", "settings", "check", "upgrades"];

/**
 * `#/setup/rig[/walk/<section>/<n>|/settings|/check|/upgrades]` -> { view, section, n }. The walkthrough is the
 * default view; `section` is the walkthrough section id and `n` the 1-based step (null when absent or not a
 * positive integer).
 */
export function parseRigParam(param: string | null): { view: RigView; section: string | null; n: number | null } {
  const [view, section, n] = (param ?? "").split("/");
  const v: RigView = (RIG_VIEWS as readonly (string | undefined)[]).includes(view) ? (view as RigView) : "walk";
  if (v !== "walk") return { view: v, section: null, n: null };
  const step = n !== undefined && /^\d+$/.test(n) && Number(n) > 0 ? Number(n) : null;
  return { view: "walk", section: section ? section : null, n: section ? step : null };
}

/** `#/setup/car[/session/<id>]` -> { sessionId } (null = the recommendation view; its inputs are in the query). */
export function parseCarSetupParam(param: string | null): { sessionId: string | null } {
  const [kind, id] = (param ?? "").split("/");
  return { sessionId: kind === "session" && id ? id : null };
}
