import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { memoryStorage, stubBrowser } from "../test/fakes";
import {
  AREA_ALIASES,
  AREA_IDS,
  AREA_PAGES,
  DEFAULT_PAGE,
  areaPath,
  canonicalHash,
  landingPage,
  legacyRedirect,
  parseCarSetupParam,
  parseHash,
  parseRigParam,
  parseSessionParam,
  pathOf,
  queryParams,
  sessionPath,
  splitHash,
  withQuery,
} from "./route-parse";

describe("splitHash", () => {
  it.each([
    ["", "/", ""],
    ["#", "/", ""],
    ["#/drive/coach", "/drive/coach", ""],
    ["#radio", "/radio", ""],
    ["#/radio?token=XYZ", "/radio", "token=XYZ"],
    ["#/radio?", "/radio", ""],
    ["#/review/sessions/abc?x=1&token=t", "/review/sessions/abc", "x=1&token=t"],
  ])("%j -> path %j, query %j", (hash, path, query) => {
    expect(splitHash(hash)).toEqual({ path, query });
  });
});

describe("defaults (spec 12.2)", () => {
  it("each area's default page is one of its pages", () => {
    expect(DEFAULT_PAGE).toEqual({ drive: "coach", review: "sessions", setup: "rig", settings: "drivers" });
    for (const a of AREA_IDS) expect(AREA_PAGES[a]).toContain(DEFAULT_PAGE[a]);
  });

  it("every alias points at a real page", () => {
    for (const to of Object.values(AREA_ALIASES)) {
      const [area, page] = to.split("/");
      expect(AREA_PAGES[area as keyof typeof AREA_PAGES]).toContain(page);
    }
  });
});

// Every row of the redirect table (spec 2.4), as full hashes through parseHash -> canonicalHash.
describe("redirects (spec 2.4) keep the ?query", () => {
  it.each([
    ["", "#/drive/coach"],
    ["#/", "#/drive/coach"],
    ["#/live", "#/drive/coach"],
    ["#/drive", "#/drive/coach"],
    ["#/drive/live", "#/drive/coach"],
    ["#/radio", "#/drive/radio"],
    ["#/radio?token=abc", "#/drive/radio?token=abc"],
    ["#/sessions", "#/review/sessions"],
    ["#/sessions/s-123", "#/review/sessions/s-123"],
    ["#/sessions/s-123?token=abc", "#/review/sessions/s-123?token=abc"],
    ["#/engineer", "#/review/ask"],
    ["#/review/compare", "#/review/sessions"],
    ["#/setup", "#/setup/rig"],
    ["#/connect", "#/setup/connect"],
    ["#/carsetup", "#/setup/car"],
    ["#/profiles", "#/settings/drivers"],
    ["#/settings", "#/settings/ai"],
    ["#/settings/engine", "#/settings/ai"],
    ["#/status", "#/settings/system"],
    ["#/settings/status", "#/settings/system"],
    ["#/review", "#/review/sessions"],
    ["#/settings?token=abc", "#/settings/ai?token=abc"],
  ])("%j -> %j", (from, to) => {
    expect(canonicalHash(parseHash(from))).toBe(to);
  });

  it("bare #/review opens the remembered sub-page", () => {
    expect(canonicalHash(parseHash("#/review", { review: "progress" }))).toBe("#/review/progress");
    expect(canonicalHash(parseHash("#/review?driver=2", { review: "coaching" }))).toBe("#/review/coaching?driver=2");
    // a remembered id that is not a page any more is ignored
    expect(parseHash("#/review", { review: "compare" }).page).toBe("sessions");
  });

  it("bare #/setup and #/settings keep their Svelte meaning whatever is remembered", () => {
    expect(parseHash("#/setup", { setup: "car" }).path).toBe("/setup/rig");
    expect(parseHash("#/settings", { settings: "display" }).path).toBe("/settings/ai");
  });

  it("interim aliases drop anything after them", () => {
    expect(parseHash("#/review/compare/123").path).toBe("/review/sessions");
    expect(parseHash("#/drive/live/x").path).toBe("/drive/coach");
  });
});

describe("legacyRedirect", () => {
  it.each(["/drive/coach", "/settings/drivers", "/settings/ai", "/setup/rig", "/review/sessions/x", "/review"])(
    "%s is not legacy",
    (path) => {
      expect(legacyRedirect(path)).toBeNull();
    },
  );

  it("ignores a query on the path", () => {
    expect(legacyRedirect("/radio?token=XYZ")).toBe("/drive/radio");
  });
});

describe("parseHash", () => {
  it.each([
    // unknown area -> Drive's default page
    ["#/nope/x", { area: "drive", page: "coach", param: null, path: "/drive/coach", query: "" }],
    // unknown page -> the area's default page (its params dropped)
    ["#/settings/nope", { area: "settings", page: "drivers", param: null, path: "/settings/drivers", query: "" }],
    ["#/review/nope/x?q=1", { area: "review", page: "sessions", param: null, path: "/review/sessions", query: "q=1" }],
    ["#/drive/garage", { area: "drive", page: "coach", param: null, path: "/drive/coach", query: "" }],
    // pages, with params
    ["#/setup/connect", { area: "setup", page: "connect", param: null, path: "/setup/connect", query: "" }],
    ["#/setup/car", { area: "setup", page: "car", param: null, path: "/setup/car", query: "" }],
    ["#/drive/car", { area: "drive", page: "car", param: null, path: "/drive/car", query: "" }],
    ["#/settings/radio", { area: "settings", page: "radio", param: null, path: "/settings/radio", query: "" }],
    [
      "#/review/sessions/abc",
      { area: "review", page: "sessions", param: "abc", path: "/review/sessions/abc", query: "" },
    ],
    [
      "#/review/sessions/a%20b",
      { area: "review", page: "sessions", param: "a b", path: "/review/sessions/a%20b", query: "" },
    ],
    [
      "#/review/sessions/abc/compare?ref=1&lap=2&at=350",
      {
        area: "review",
        page: "sessions",
        param: "abc/compare",
        path: "/review/sessions/abc/compare",
        query: "ref=1&lap=2&at=350",
      },
    ],
    [
      "#/setup/rig/walk/wheel/3",
      { area: "setup", page: "rig", param: "walk/wheel/3", path: "/setup/rig/walk/wheel/3", query: "" },
    ],
    [
      "#/setup/car/session/s9",
      { area: "setup", page: "car", param: "session/s9", path: "/setup/car/session/s9", query: "" },
    ],
    [
      "#/drive/radio?token=XYZ",
      { area: "drive", page: "radio", param: null, path: "/drive/radio", query: "token=XYZ" },
    ],
  ])("%j", (hash, route) => {
    expect(parseHash(hash)).toEqual(route);
  });

  it("encodes each param segment on its own (no %2F in the canonical hash)", () => {
    expect(canonicalHash(parseHash("#/review/sessions/a%2Fb/laps"))).toBe("#/review/sessions/a%2Fb/laps");
    expect(parseHash("#/review/sessions/x/laps").path).toBe("/review/sessions/x/laps");
  });

  it("a canonical hash parses to itself", () => {
    for (const area of AREA_IDS) {
      for (const page of AREA_PAGES[area]) {
        expect(canonicalHash(parseHash(`#/${area}/${page}`))).toBe(`#/${area}/${page}`);
      }
    }
  });
});

describe("landing rules (spec 2.5)", () => {
  it("areas open on their remembered page, else their default", () => {
    expect(areaPath("settings")).toBe("/settings/drivers");
    expect(areaPath("settings", { settings: "display" })).toBe("/settings/display");
    expect(areaPath("drive", { drive: "nope" })).toBe("/drive/coach");
    expect(parseHash(`#${areaPath("settings")}`).page).toBe("drivers");
  });

  it("Setup opens on Connect until a real session exists", () => {
    expect(landingPage("setup", { setup: "car" }, false)).toBe("connect");
    expect(landingPage("setup", { setup: "car" }, true)).toBe("car");
    expect(landingPage("setup", {}, true)).toBe("rig");
    expect(landingPage("setup", {}, null)).toBe("rig"); // unknown yet: no change
    expect(landingPage("review", {}, false)).toBe("sessions"); // only Setup has the rule
  });
});

describe("page params", () => {
  it.each([
    [null, { id: null, tab: "summary" }],
    ["abc", { id: "abc", tab: "summary" }],
    ["abc/compare", { id: "abc", tab: "compare" }],
    ["abc/laps", { id: "abc", tab: "laps" }],
    ["abc/corners", { id: "abc", tab: "corners" }],
    ["abc/ask", { id: "abc", tab: "ask" }],
    ["abc/nope", { id: "abc", tab: "summary" }],
  ])("session %j", (param, out) => {
    expect(parseSessionParam(param)).toEqual(out);
  });

  it("sessionPath builds the tab paths", () => {
    expect(sessionPath("abc")).toBe("/review/sessions/abc");
    expect(sessionPath("abc", "compare")).toBe("/review/sessions/abc/compare");
    expect(parseSessionParam(parseHash(`#${sessionPath("a b", "laps")}`).param)).toEqual({ id: "a b", tab: "laps" });
  });

  it.each([
    [null, { view: "walk", section: null, n: null }],
    ["walk", { view: "walk", section: null, n: null }],
    ["walk/wheel", { view: "walk", section: "wheel", n: null }],
    ["walk/wheel/3", { view: "walk", section: "wheel", n: 3 }],
    ["walk/wheel/0", { view: "walk", section: "wheel", n: null }],
    ["walk/wheel/x", { view: "walk", section: "wheel", n: null }],
    ["settings", { view: "settings", section: null, n: null }],
    ["check", { view: "check", section: null, n: null }],
    ["upgrades", { view: "upgrades", section: null, n: null }],
    ["nope", { view: "walk", section: null, n: null }],
  ])("rig %j", (param, out) => {
    expect(parseRigParam(param)).toEqual(out);
  });

  it.each([
    [null, { sessionId: null }],
    ["session/s9", { sessionId: "s9" }],
    ["session", { sessionId: null }],
    ["other/s9", { sessionId: null }],
  ])("car setup %j", (param, out) => {
    expect(parseCarSetupParam(param)).toEqual(out);
  });
});

describe("query helpers", () => {
  it("withQuery drops empty values and keeps order", () => {
    expect(withQuery("/review/progress", { driver: 2, track: "silverstone", car: null, x: "" })).toBe(
      "/review/progress?driver=2&track=silverstone",
    );
    expect(withQuery("/review/ask", {})).toBe("/review/ask");
    expect(withQuery("/review/ask", { q: "where did I lose time?" })).toBe("/review/ask?q=where+did+I+lose+time%3F");
  });

  it("queryParams reads the route's query", () => {
    const r = parseHash("#/review/sessions/abc/compare?ref=11&lap=12&at=350");
    expect(queryParams(r).get("ref")).toBe("11");
    expect(queryParams(r).get("at")).toBe("350");
  });

  it("pathOf encodes segments", () => {
    expect(pathOf("review", "sessions", "a/b", 3)).toBe("/review/sessions/a%2Fb/3");
  });
});

describe("router store", () => {
  beforeEach(() => {
    // Node has its own localStorage global; give every test a fresh one.
    vi.stubGlobal("localStorage", memoryStorage());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("rewrites a legacy #/radio?token= link without dropping the token, and remembers it for the tab", async () => {
    const { win, storage } = stubBrowser("http://192.168.1.20:8770/next/#/radio?token=XYZ");
    const { router } = await import("./router");
    const { TOKEN_KEY } = await import("./auth");
    expect(router.get().route).toMatchObject({ area: "drive", page: "radio", query: "token=XYZ" });
    expect(win.history.replaceState).toHaveBeenCalledWith(null, "", "/next/#/drive/radio?token=XYZ");
    expect(win.location.hash).toBe("#/drive/radio?token=XYZ");
    expect(storage.getItem(TOKEN_KEY)).toBe("XYZ");
  });

  it("sends the Svelte #/settings bookmark to the AI engineer page", async () => {
    const { win } = stubBrowser("http://127.0.0.1:8770/next/#/settings");
    const { router } = await import("./router");
    expect(router.get().route.path).toBe("/settings/ai");
    expect(win.location.hash).toBe("#/settings/ai");
  });

  it("sends the interim #/drive/live to Coach", async () => {
    const { win } = stubBrowser("http://127.0.0.1:8770/next/#/drive/live");
    await import("./router");
    expect(win.location.hash).toBe("#/drive/coach");
  });

  it("leaves a canonical hash alone", async () => {
    const { win } = stubBrowser("http://127.0.0.1:8770/next/?token=abc#/review/sessions");
    await import("./router");
    expect(win.history.replaceState).not.toHaveBeenCalled();
  });

  it("remembers each area's last page on this device and opens bare #/review there", async () => {
    const local = memoryStorage();
    vi.stubGlobal("localStorage", local);
    const { win } = stubBrowser("http://127.0.0.1:8770/next/#/review/progress");
    const { router, AREA_PAGES_KEY } = await import("./router");
    expect(JSON.parse(local.getItem(AREA_PAGES_KEY) ?? "{}")).toEqual({ review: "progress" });
    expect(router.areaPath("review")).toBe("/review/progress");
    expect(router.areaPath("settings")).toBe("/settings/drivers");

    // a fresh load with a bare #/review lands on the remembered page
    vi.resetModules();
    win.location.hash = "#/review";
    const again = (await import("./router")).router;
    expect(again.get().route.path).toBe("/review/progress");
  });

  it("works without storage (areas open on their first page)", async () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    });
    stubBrowser("http://127.0.0.1:8770/next/#/settings/display");
    const { router } = await import("./router");
    expect(router.get().route.page).toBe("display");
    expect(router.areaPath("settings")).toBe("/settings/display"); // kept in memory for this page
  });

  it("Setup's link follows the real-session flag", async () => {
    stubBrowser("http://127.0.0.1:8770/next/#/drive/coach");
    const { router } = await import("./router");
    expect(router.areaPath("setup")).toBe("/setup/rig");
    router.setHasRealSession(false);
    expect(router.areaPath("setup")).toBe("/setup/connect");
    router.setHasRealSession(true);
    expect(router.areaPath("setup")).toBe("/setup/rig");
  });

  it("replace() updates the route without a history entry", async () => {
    const { win } = stubBrowser("http://127.0.0.1:8770/next/#/review/sessions/abc/compare?ref=1&lap=2");
    const { router } = await import("./router");
    router.replace("/review/sessions/abc/compare?ref=1&lap=2&at=350");
    expect(win.history.replaceState).toHaveBeenLastCalledWith(
      null,
      "",
      "/next/#/review/sessions/abc/compare?ref=1&lap=2&at=350",
    );
    expect(router.get().route.query).toBe("ref=1&lap=2&at=350");
  });
});
