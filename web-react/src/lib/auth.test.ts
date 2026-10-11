import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { json, stubBrowser } from "../test/fakes";
import {
  accessToken,
  authFetch,
  forgetToken,
  rememberUrlToken,
  resetTokenCacheForTests,
  TOKEN_KEY,
  urlToken,
  wsUrl,
} from "./auth";

beforeEach(() => resetTokenCacheForTests());
afterEach(() => vi.unstubAllGlobals());

const headerOf = (init: RequestInit | undefined) => new Headers(init?.headers).get("X-Pitwall-Token");

describe("urlToken", () => {
  it.each([
    ["http://h/next/", null],
    ["http://h/next/?token=abc", "abc"],
    ["http://h/next/?token=abc#/drive/live", "abc"],
    ["http://h/next/#/radio?token=XYZ", "XYZ"],
    ["http://h/next/#/drive/radio?a=1&token=XYZ", "XYZ"],
    ["http://h/next/#/radio?token=", null],
  ])("%s -> %j", (url, token) => {
    stubBrowser(url);
    expect(urlToken()).toBe(token);
  });
});

describe("accessToken", () => {
  it("remembers a hash token for the tab after navigation replaces the hash", () => {
    const { win, storage } = stubBrowser("http://h/next/#/radio?token=XYZ");
    rememberUrlToken();
    expect(storage.getItem(TOKEN_KEY)).toBe("XYZ");
    win.location.hash = "#/review/sessions";
    expect(accessToken()).toBe("XYZ");
    resetTokenCacheForTests(); // e.g. a reload of the tab: read back from sessionStorage
    expect(accessToken()).toBe("XYZ");
  });

  it("is null with no token anywhere", () => {
    stubBrowser("http://127.0.0.1:8770/next/#/drive/live");
    expect(accessToken()).toBeNull();
  });

  it("forgetToken drops a remembered token but never one still in the URL", () => {
    const { win, storage } = stubBrowser("http://h/next/#/radio?token=XYZ");
    rememberUrlToken();
    expect(forgetToken()).toBe(false); // the user is using that link
    win.location.hash = "#/drive/live";
    expect(forgetToken()).toBe(true);
    expect(storage.getItem(TOKEN_KEY)).toBeNull();
    expect(accessToken()).toBeNull();
    expect(forgetToken()).toBe(false);
  });
});

describe("wsUrl", () => {
  it("uses ws on http and carries no token on localhost", () => {
    stubBrowser("http://127.0.0.1:8770/next/#/drive/live");
    expect(wsUrl("/ws/live")).toBe("ws://127.0.0.1:8770/ws/live");
  });

  it("uses wss on https and forwards the hash token (encoded)", () => {
    stubBrowser("https://mac.tailnet.ts.net:8443/next/#/radio?token=a%2Bb");
    expect(wsUrl("/ws/live")).toBe("wss://mac.tailnet.ts.net:8443/ws/live?token=a%2Bb");
  });
});

describe("authFetch", () => {
  it("sends same-origin credentials and no token header when there is no token", async () => {
    stubBrowser("http://127.0.0.1:8770/next/");
    const fetchMock = vi.fn(async (_p: string, _i?: RequestInit) => json({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    await authFetch("/api/health");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[1]?.credentials).toBe("same-origin");
    expect(headerOf(fetchMock.mock.calls[0]?.[1])).toBeNull();
  });

  it("sends the hash token as a header (the cookie was never set for it)", async () => {
    stubBrowser("http://h/next/#/radio?token=XYZ");
    const fetchMock = vi.fn(async (_p: string, _i?: RequestInit) => json({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    await authFetch("/api/drivers", { method: "PUT", headers: { "Content-Type": "application/json" } });
    const init = fetchMock.mock.calls[0]?.[1];
    expect(headerOf(init)).toBe("XYZ");
    expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
    expect(init?.method).toBe("PUT");
  });

  it("forgets a refused remembered token and retries once on the cookie alone", async () => {
    const { win, storage } = stubBrowser("http://h/next/#/radio?token=OLD");
    rememberUrlToken();
    win.location.hash = "#/drive/live";
    const fetchMock = vi.fn(async (_p: string, init?: RequestInit) =>
      headerOf(init) ? json({ detail: "access token required" }, 401) : json({ ok: true }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const r = await authFetch("/api/drivers");
    expect(r.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(storage.getItem(TOKEN_KEY)).toBeNull();
  });

  it("does not retry when the refused token is in the URL", async () => {
    stubBrowser("http://h/next/?token=BAD#/drive/live");
    const fetchMock = vi.fn(async () => json({ detail: "access token required" }, 401));
    vi.stubGlobal("fetch", fetchMock);
    const r = await authFetch("/api/drivers");
    expect(r.status).toBe(401);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
