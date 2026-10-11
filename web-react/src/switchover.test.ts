// Switch-over guards (spec 14.2 phase 3): this app replaces the Svelte dashboard (web/) at "/", with /next/ kept as an
// alias for a week (README "Switch-over"). So:
//   1. every link the Svelte dashboard used lands on a React page that is built (not a phase-0 stub);
//   2. nothing in the app depends on the path it is served from (the same build works at "/" and at "/next/");
//   3. at "/", a legacy hash is canonicalised in place, keeping the page's own path and query and the hash's query
//      (a Home Screen icon saved from the Svelte app is `https://…:8443/#/radio?token=…`).
// The Svelte app is read here as the behaviour reference only (it is frozen); if web/ is ever removed, part 1 skips.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import indexHtml from "../index.html?raw";
import manifestRaw from "../public/manifest.webmanifest?raw";
import { AREA_IDS, AREA_PAGES, canonicalHash, parseHash, parseSessionParam } from "./lib/route-parse";
import { memoryStorage, stubBrowser } from "./test/fakes";

const svelteApp = Object.values(
  import.meta.glob<string>("../../web/src/App.svelte", { query: "?raw", import: "default", eager: true }),
)[0];

const pageSources = import.meta.glob<string>("./pages/**/*Page.tsx", { query: "?raw", import: "default", eager: true });

const appSources = import.meta.glob<string>(["./**/*.ts", "./**/*.tsx", "!./**/*.test.ts", "!./test/**"], {
  query: "?raw",
  import: "default",
  eager: true,
});

/** The file each registered page lives in (src/routes.tsx imports these). */
const PAGE_FILES: Record<string, string> = {
  "drive/coach": "./pages/drive/CoachPage.tsx",
  "drive/car": "./pages/drive/CarPage.tsx",
  "drive/track": "./pages/drive/TrackPage.tsx",
  "drive/radio": "./pages/drive/RadioPage.tsx",
  "review/sessions": "./pages/review/SessionsPage.tsx",
  "review/coaching": "./pages/review/CoachingPage.tsx",
  "review/progress": "./pages/review/ProgressPage.tsx",
  "review/ask": "./pages/review/AskPage.tsx",
  "setup/game": "./pages/setup/GamePage.tsx",
  "setup/connect": "./pages/setup/ConnectPage.tsx",
  "setup/rig": "./pages/setup/RigPage.tsx",
  "setup/car": "./pages/setup/CarSetupPage.tsx",
  "setup/validation": "./pages/setup/ValidationPage.tsx", // validation kit (lane validate)
  "settings/drivers": "./pages/settings/DriversPage.tsx",
  "settings/radio": "./pages/settings/RadioVoicePage.tsx",
  "settings/ai": "./pages/settings/AiEnginePage.tsx",
  "settings/display": "./pages/settings/DisplayPage.tsx",
  "settings/system": "./pages/settings/SystemPage.tsx",
};
/** The session page (`#/review/sessions/<id>`), rendered by SessionsPage for a param. */
const SESSION_FILE = "./pages/review/SessionPage.tsx";

/** Pages R builds in phase 3 (spec 6.8, 6.9). They have no Svelte view; they may still be stubs during the switch. */
const PHASE_3_PAGES = new Set(["review/coaching", "review/progress"]);

/** Svelte link -> the React path it must land on (spec 2.2, 2.4). `<id>` stands for a session id. */
const SVELTE_LINKS: Record<string, string> = {
  "#/live": "/drive/coach",
  "#/sessions": "/review/sessions",
  "#/sessions/<id>": "/review/sessions/<id>",
  "#/engineer": "/review/ask",
  "#/radio": "/drive/radio",
  "#/setup": "/setup/rig",
  "#/carsetup": "/setup/car",
  "#/profiles": "/settings/drivers",
  "#/connect": "/setup/connect",
  "#/settings": "/settings/ai",
  "#/status": "/settings/system",
};

function isStub(file: string): boolean {
  const src = pageSources[file];
  if (src === undefined) throw new Error(`missing page file ${file}`);
  return /\bPageStub\b/.test(src);
}

function fileFor(path: string): string {
  const [area, page, ...rest] = path.split("/").filter(Boolean);
  if (area === "review" && page === "sessions" && rest.length) return SESSION_FILE;
  const f = PAGE_FILES[`${area}/${page}`];
  if (!f) throw new Error(`no page file for ${path}`);
  return f;
}

describe("every Svelte view has a built React page (spec 14.2 phase 3)", () => {
  it("PAGE_FILES covers every registered page", () => {
    expect(Object.keys(PAGE_FILES).sort()).toEqual(AREA_IDS.flatMap((a) => AREA_PAGES[a].map((p) => `${a}/${p}`)).sort());
    for (const f of [...Object.values(PAGE_FILES), SESSION_FILE]) expect(pageSources[f], f).toBeTypeOf("string");
  });

  it.runIf(svelteApp !== undefined)("each Svelte nav link is in the redirect table", () => {
    const links = [...(svelteApp ?? "").matchAll(/href:\s*"(#\/[^"]*)"/g)].map((m) => m[1]);
    expect(links.length).toBeGreaterThan(5);
    for (const l of links) expect(Object.keys(SVELTE_LINKS), `${l} (add it to spec 2.4 and SVELTE_LINKS)`).toContain(l);
    // the session page is the one dynamic link (`#/sessions/${s.id}`)
    expect(svelteApp).toContain("#/sessions/");
  });

  it.each(Object.entries(SVELTE_LINKS))("%s lands on %s, a built page", (from, to) => {
    const route = parseHash(from.replace("<id>", "s-1"));
    expect(route.path).toBe(to.replace("<id>", "s-1"));
    expect(isStub(fileFor(route.path)), `${fileFor(route.path)} is still a stub`).toBe(false);
  });

  it("the session page keeps its tabs at the new address", () => {
    const r = parseHash("#/sessions/s-1");
    expect(parseSessionParam(r.param)).toEqual({ id: "s-1", tab: "summary" });
  });

  it("no page is a stub except the phase 3 Review pages", () => {
    const stubs = Object.entries(PAGE_FILES)
      .filter(([, f]) => isStub(f))
      .map(([id]) => id);
    for (const id of stubs) expect(PHASE_3_PAGES, `${id} is a stub`).toContain(id);
    expect(isStub(SESSION_FILE)).toBe(false);
  });
});

describe("the build does not depend on its base path (served at / and /next/)", () => {
  it("index.html links public files by root path (Vite prefixes the base) and never names /next/", () => {
    expect(indexHtml).toContain('rel="manifest" href="/manifest.webmanifest"');
    expect(indexHtml).toContain('rel="apple-touch-icon" href="/apple-touch-icon.png"');
    expect(indexHtml).not.toMatch(/\/next\b/);
  });

  it("the manifest resolves against wherever it is served and has no start_url", () => {
    const m = JSON.parse(manifestRaw) as { id?: string; scope?: string; start_url?: string; icons: { src: string }[] };
    expect(m.id).toBe("./");
    expect(m.scope).toBe("./");
    // no start_url: a Home Screen icon opens the page it was added from, so `#/radio?token=…` keeps its token
    expect(m.start_url).toBeUndefined();
    for (const i of m.icons) expect(i.src).not.toMatch(/^\//);
  });

  it("no app code hard-codes /next/ or a root path to a public file", () => {
    const offenders: string[] = [];
    for (const [file, src] of Object.entries(appSources)) {
      if (/["'`]\/next\b/.test(src)) offenders.push(`${file}: /next`);
      if (/["'`]\/(mic-worklet\.js|manifest\.webmanifest|icon-\d+\.png|apple-touch-icon\.png)/.test(src)) {
        offenders.push(`${file}: public file by root path (use import.meta.env.BASE_URL)`);
      }
    }
    expect(Object.keys(appSources).length).toBeGreaterThan(50);
    expect(offenders).toEqual([]);
  });
});

describe("router at / after the switch-over", () => {
  beforeEach(() => {
    vi.stubGlobal("localStorage", memoryStorage());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("a Svelte Home Screen icon `/#/radio?token=` opens Drive › Radio at / with its token", async () => {
    const { win, storage } = stubBrowser("https://mac.tailnet.ts.net:8443/#/radio?token=XYZ");
    const { router } = await import("./lib/router");
    const { TOKEN_KEY } = await import("./lib/auth");
    expect(router.get().route).toMatchObject({ area: "drive", page: "radio", query: "token=XYZ" });
    expect(win.history.replaceState).toHaveBeenCalledWith(null, "", "/#/drive/radio?token=XYZ");
    expect(storage.getItem(TOKEN_KEY)).toBe("XYZ");
  });

  it("the bare address opens Drive › Coach", async () => {
    const { win } = stubBrowser("https://mac.tailnet.ts.net:8443/");
    await import("./lib/router");
    expect(win.history.replaceState).toHaveBeenCalledWith(null, "", "/#/drive/coach");
  });

  it("a page query (`/?token=` from `pitwall token`) is kept when a Svelte hash is rewritten", async () => {
    const { win } = stubBrowser("http://192.168.1.20:8770/?token=abc#/sessions/s-1");
    await import("./lib/router");
    expect(win.history.replaceState).toHaveBeenCalledWith(null, "", "/?token=abc#/review/sessions/s-1");
    expect(canonicalHash(parseHash(win.location.hash))).toBe("#/review/sessions/s-1");
  });

  it("the /next/ alias keeps its own path", async () => {
    const { win } = stubBrowser("https://mac.tailnet.ts.net:8443/next/#/live");
    await import("./lib/router");
    expect(win.history.replaceState).toHaveBeenCalledWith(null, "", "/next/#/drive/coach");
  });
});
