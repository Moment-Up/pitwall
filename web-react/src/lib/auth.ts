// Auth behaviour - same as the Svelte dashboard (web/src/lib/api.ts, live.svelte.ts, radio.svelte.ts):
//  * localhost needs nothing (src/pitwall/api/auth.py);
//  * a LAN device opens the URL printed by `pitwall token` once (…/?token=...). The server's HTTP middleware sees
//    `?token=` on that page load and sets the httpOnly `pitwall_token` cookie (path /), which every later fetch
//    sends because requests are same-origin with credentials: "same-origin";
//  * a token inside the hash (`#/radio?token=…`, accepted by the Svelte radio) never reaches the server over HTTP,
//    so no cookie is set. It is remembered for the tab in sessionStorage (in-app navigation replaces the hash) and
//    sent explicitly: as `?token=` on WebSockets and as the X-Pitwall-Token header on fetches;
//  * Tailscale identity is resolved server-side; the browser does nothing special.
// A remembered token the server refuses (rotated) is forgotten: a supplied token outranks the cookie on the server,
// so a stale one would also block a valid cookie. A token still in the URL is kept - the user is using that link.
// Everything is same-origin: absolute paths (/api, /ws) work whether the app is served at / or /next/.

/** Shared with the Svelte radio (web/src/lib/radio.svelte.ts): per tab, gone when the tab closes. */
export const TOKEN_KEY = "pitwall-radio-token";
const TOKEN_HEADER = "X-Pitwall-Token";

export const FETCH_DEFAULTS: RequestInit = { credentials: "same-origin" };

let remembered: string | null | undefined; // undefined = sessionStorage not read yet

/** `?token=` from the page URL: the query before the hash, or the query inside it (`#/radio?token=…`). */
export function urlToken(): string | null {
  try {
    const { search, hash } = window.location;
    const q = new URLSearchParams(search).get("token");
    if (q) return q;
    const i = hash.indexOf("?");
    return i >= 0 ? new URLSearchParams(hash.slice(i + 1)).get("token") || null : null;
  } catch {
    return null;
  }
}

/** Remember a token in the URL for this tab (called on every route change, before the hash can be replaced). */
export function rememberUrlToken(): void {
  const t = urlToken();
  if (!t || t === remembered) return;
  remembered = t;
  try {
    sessionStorage.setItem(TOKEN_KEY, t);
  } catch {
    /* storage unavailable: memory only */
  }
}

/** The access token for this tab: the one in the URL, else the one remembered from an earlier URL, else null. */
export function accessToken(): string | null {
  const t = urlToken();
  if (t) {
    rememberUrlToken();
    return t;
  }
  if (remembered === undefined) {
    try {
      remembered = sessionStorage.getItem(TOKEN_KEY);
    } catch {
      remembered = null;
    }
  }
  return remembered;
}

/** Forget a remembered token the server refused. Returns whether one was dropped (never one still in the URL). */
export function forgetToken(): boolean {
  if (urlToken() || !accessToken()) return false;
  remembered = null;
  try {
    sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable */
  }
  return true;
}

/** ws(s)://<same host>/<path>[?token=...] - wss when the page is https (Tailscale serve). */
export function wsUrl(path: string): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const token = accessToken();
  return `${proto}://${window.location.host}${path}${token ? `?token=${encodeURIComponent(token)}` : ""}`;
}

function withToken(init: RequestInit, token: string | null): RequestInit {
  if (!token) return init;
  const headers = new Headers(init.headers);
  headers.set(TOKEN_HEADER, token);
  return { ...init, headers };
}

/**
 * fetch() for the API: same-origin credentials plus the tab's token, if any. On a 401 with a remembered token the
 * token is forgotten and the request retried once on the cookie alone (the 401 comes from the auth middleware
 * before any handler runs, so retrying a mutation is safe).
 */
export async function authFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const base: RequestInit = { ...FETCH_DEFAULTS, ...init };
  const token = accessToken();
  const r = await fetch(path, withToken(base, token));
  if (r.status === 401 && token && forgetToken()) return fetch(path, base);
  return r;
}

/** Test hook: drop the in-memory copy so the next read goes back to sessionStorage. */
export function resetTokenCacheForTests(): void {
  remembered = undefined;
}
