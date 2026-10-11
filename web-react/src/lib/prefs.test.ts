import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import indexHtml from "../../index.html?raw";
import { memoryStorage } from "../test/fakes";
import {
  DEFAULT_PREFS,
  LEGACY_THEME_KEY,
  PREFS_KEY,
  driveLockApplies,
  effectiveTheme,
  htmlAttributes,
  parsePrefs,
  type Prefs,
} from "./prefs";

describe("parsePrefs", () => {
  it("defaults: dark, Drive always dark, lock for beginners, rail dims", () => {
    expect(parsePrefs(null)).toEqual(DEFAULT_PREFS);
    expect(DEFAULT_PREFS).toMatchObject({ theme: "dark", driveAlwaysDark: true, driveLock: "beginners", dimNav: true });
  });

  it("takes the Svelte dashboard's theme when nothing else is stored", () => {
    expect(parsePrefs(null, "light").theme).toBe("light");
    expect(parsePrefs(JSON.stringify({ theme: "dark" }), "light").theme).toBe("dark");
  });

  it("validates each field on its own", () => {
    const p = parsePrefs(
      JSON.stringify({ theme: "purple", night: "yes", cvd: "rg", driveSize: "huge", driveLock: "everyone", dimNav: false }),
    );
    expect(p).toEqual({ ...DEFAULT_PREFS, cvd: "rg", driveLock: "everyone", dimNav: false });
  });

  it.each(["", "{", "null", "[]", "42"])("survives corrupt storage %j", (raw) => {
    expect(parsePrefs(raw)).toEqual(DEFAULT_PREFS);
  });
});

describe("effectiveTheme", () => {
  const p = (patch: Partial<Prefs>): Prefs => ({ ...DEFAULT_PREFS, ...patch });

  it("Drive stays dark with Drive always dark, whatever the theme", () => {
    expect(effectiveTheme(p({ theme: "light" }), "drive", false)).toBe("dark");
    expect(effectiveTheme(p({ theme: "system" }), "drive", false)).toBe("dark");
    expect(effectiveTheme(p({ theme: "light", driveAlwaysDark: false }), "drive", false)).toBe("light");
  });

  it("other areas use the chosen theme, or the device's with Match device", () => {
    expect(effectiveTheme(p({ theme: "light" }), "review", true)).toBe("light");
    expect(effectiveTheme(p({ theme: "system" }), "settings", true)).toBe("dark");
    expect(effectiveTheme(p({ theme: "system" }), "settings", false)).toBe("light");
    expect(effectiveTheme(p({ theme: "dark" }), null, false)).toBe("dark");
  });
});

describe("htmlAttributes", () => {
  it("sets only what is on", () => {
    expect(htmlAttributes(DEFAULT_PREFS, "dark")).toEqual({
      "data-theme": "dark",
      "data-night": null,
      "data-cvd": null,
      "data-drive-size": null,
    });
    expect(htmlAttributes({ ...DEFAULT_PREFS, night: true, cvd: "rg", driveSize: "large" }, "light")).toEqual({
      "data-theme": "light",
      "data-night": "on",
      "data-cvd": "rg",
      "data-drive-size": "large",
    });
  });

  it("index.html's first-paint script uses the same storage keys and attributes", () => {
    const html = indexHtml;
    for (const s of [PREFS_KEY, LEGACY_THEME_KEY, "data-night", "data-cvd", "data-drive-size", "driveAlwaysDark"]) {
      expect(html).toContain(s);
    }
  });
});

describe("driveLockApplies", () => {
  it.each([
    ["off", "beginner", false],
    ["beginners", "beginner", true],
    ["beginners", "intermediate", false],
    ["beginners", "advanced", false],
    ["beginners", null, true], // unknown driver: the safe side
    ["everyone", "advanced", true],
  ] as const)("%s / %s -> %s", (lock, skill, want) => {
    expect(driveLockApplies(lock, skill)).toBe(want);
  });
});

describe("prefs store", () => {
  let local: Storage;
  beforeEach(() => {
    local = memoryStorage();
    vi.stubGlobal("localStorage", local);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("stores changes per device and mirrors the theme for the Svelte dashboard", async () => {
    const { prefs } = await import("./prefs");
    prefs.setPref("theme", "light");
    prefs.setPref("driveLock", "everyone");
    expect(JSON.parse(local.getItem(PREFS_KEY) ?? "{}")).toMatchObject({ theme: "light", driveLock: "everyone" });
    expect(local.getItem(LEGACY_THEME_KEY)).toBe("light");
    prefs.setPref("theme", "system");
    expect(local.getItem(LEGACY_THEME_KEY)).toBe("light"); // "system" has no Svelte equivalent: left as it was
  });

  it("follows the area: dark on Drive, light elsewhere", async () => {
    local.setItem(PREFS_KEY, JSON.stringify({ theme: "light" }));
    const { prefs } = await import("./prefs");
    let area: "drive" | "review" = "drive";
    const listeners = new Set<() => void>();
    prefs.follow({
      get: () => ({ route: { area } }),
      subscribe: (l) => {
        listeners.add(l);
        return () => listeners.delete(l);
      },
    });
    expect(prefs.get().theme).toBe("dark");
    area = "review";
    for (const l of listeners) l();
    expect(prefs.get().theme).toBe("light");
    prefs.setPref("driveAlwaysDark", false);
    area = "drive";
    for (const l of listeners) l();
    expect(prefs.get().theme).toBe("light");
  });

  it("works without storage", async () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    });
    const { prefs } = await import("./prefs");
    expect(prefs.get().prefs).toEqual(DEFAULT_PREFS);
    prefs.setPref("night", true);
    expect(prefs.get().prefs.night).toBe(true);
  });
});
