import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { json, stubBrowser } from "../../test/fakes";
import { resetTokenCacheForTests } from "../auth";
import { EndpointError, messageOf } from "./settings";
import { isNotFound, parseUpdateStatus, updateApi } from "./update";

const DOCS = "https://github.com/Moment-Up/pitwall/blob/main/docs/install.md#updating";

describe("parseUpdateStatus", () => {
  it("keeps a contract-shaped status as it is", () => {
    const raw = {
      schema: 1,
      current: "v0.1.0",
      install_kind: "managed",
      mode: "auto",
      checked_unix: 1791817200,
      checking: false,
      update_available: true,
      latest: { version: "v0.2.0", published_at: "2026-10-12T09:30:00Z", url: "https://github.com/Moment-Up/pitwall/releases/tag/v0.2.0", prerelease: false, notes: ["a", "b"] },
      newer: [{ version: "v0.2.0", published_at: null, url: "https://github.com/Moment-Up/pitwall/releases/tag/v0.2.0", prerelease: true, notes: [] }],
      error: null,
      how: { command: 'cd "/x" && uv run pitwall update', folder: "/x", docs_url: DOCS },
    };
    expect(parseUpdateStatus(raw)).toEqual(raw);
  });

  it("unknown stays unknown: missing values are null or empty, never guessed", () => {
    const s = parseUpdateStatus({ current: "v0.1.0" });
    expect(s).toEqual({
      schema: 1,
      current: "v0.1.0",
      install_kind: "unknown",
      mode: "manual",
      checked_unix: null,
      checking: false,
      update_available: null,
      latest: null,
      newer: [],
      error: null,
      how: null,
    });
    expect(parseUpdateStatus(null).current).toBe("");
    expect(parseUpdateStatus("nonsense").newer).toEqual([]);
  });

  it("drops malformed releases and notes; a newer server's extra words fall back safely", () => {
    const s = parseUpdateStatus({
      current: "v0.1.0",
      install_kind: "homebrew",
      mode: "sometimes",
      checked_unix: Number.NaN,
      update_available: "yes",
      newer: [{ version: "" }, { nope: 1 }, { version: "v0.2.0", notes: ["ok", 3, "", null] }],
      how: { folder: "/x" },
    });
    expect(s.install_kind).toBe("unknown");
    expect(s.mode).toBe("manual");
    expect(s.checked_unix).toBeNull();
    expect(s.update_available).toBeNull();
    expect(s.newer).toEqual([{ version: "v0.2.0", published_at: null, url: "", prerelease: false, notes: ["ok"] }]);
    expect(s.how).toBeNull(); // no command: nothing to show
  });
});

describe("calls", () => {
  beforeEach(() => {
    stubBrowser("http://127.0.0.1:8770/next/#/settings/system");
    resetTokenCacheForTests();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("GET /api/update; Check now POSTs an empty JSON body (the server refuses JSON-less POSTs)", async () => {
    const f = vi.fn(async (_path: string, _init?: RequestInit) => json({ current: "v0.1.0", mode: "manual", checking: true }));
    vi.stubGlobal("fetch", f);
    expect((await updateApi.status()).current).toBe("v0.1.0");
    expect((await updateApi.check()).checking).toBe(true);
    const calls = f.mock.calls.map(([path, init]) => [path, init?.method ?? "GET", new Headers(init?.headers).get("Content-Type"), init?.body ?? null]);
    expect(calls).toEqual([
      ["/api/update", "GET", null, null],
      ["/api/update/check", "POST", "application/json", "{}"],
    ]);
  });

  it("checks off: the 409's words reach the card", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: "Update checks are off (PITWALL_UPDATE_CHECK=off)." }, 409)));
    const err = await updateApi.check().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(EndpointError);
    expect(messageOf(err)).toBe("Update checks are off (PITWALL_UPDATE_CHECK=off).");
    expect(isNotFound(err)).toBe(false);
  });

  it("an older server without /api/update is a 404 the card hides", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: "Not Found" }, 404)));
    const err = await updateApi.status().catch((e: unknown) => e);
    expect(isNotFound(err)).toBe(true);
    expect(isNotFound(new Error("x"))).toBe(false);
  });
});
