// Per-device display preferences (spec 3.3, 8 "Display", 9.2, 11, 12.3). Framework-agnostic store, stored in
// localStorage (`pitwall-prefs`, read and written in try/catch: without storage the defaults last for the page).
//
// Applied to <html> (the tokens in styles/tokens.css key off these):
//   class="dark|light" + data-theme   effectiveTheme(): the chosen theme, or the device's with "Match device";
//                                     always dark while a Drive page is open and "Drive always dark" is on, so the
//                                     rail, the Drive grid and any overlay switch together
//   data-night="on"                   Night dim (the tokens only change the dark scheme)
//   data-cvd="rg"                     Red-green safe colour vision
//   data-drive-size="large"           Drive text size Large (x 1.12)
// index.html applies the same rules before first paint (keep the two in step: tests/prefs.test.ts checks the keys).
//
// The theme is also written to the Svelte dashboard's key (`pitwall-theme`) so both apps on this origin agree.

import type { SkillLevel } from "./drivers";
import type { AreaId } from "./route-parse";
import { Store } from "./store";

export type ThemePref = "dark" | "light" | "system";
export type ThemeName = "dark" | "light";
export type ColourVision = "standard" | "rg";
export type DriveSize = "standard" | "large";
/** Who the Drive lock applies to while on track (3.3): nobody, beginner profiles (default) or everyone. */
export type DriveLock = "off" | "beginners" | "everyone";

export interface Prefs {
  theme: ThemePref;
  /** Drive stays dark when the app is light (default on). */
  driveAlwaysDark: boolean;
  /** Night dim: darker surfaces and dimmer text for a dark room (dark scheme only). */
  night: boolean;
  cvd: ColourVision;
  driveSize: DriveSize;
  /** Dim the rail to 55 % while on track (default on). */
  dimNav: boolean;
  driveLock: DriveLock;
}

export const DEFAULT_PREFS: Readonly<Prefs> = {
  theme: "dark",
  driveAlwaysDark: true,
  night: false,
  cvd: "standard",
  driveSize: "standard",
  dimNav: true,
  driveLock: "beginners",
};

export const PREFS_KEY = "pitwall-prefs";
/** The Svelte dashboard's theme key ("dark" | "light"); read as a fallback and kept in sync. */
export const LEGACY_THEME_KEY = "pitwall-theme";

/** theme-color meta per effective theme (= --background, spec 9.2). */
export const THEME_COLOR: Readonly<Record<ThemeName, string>> = { dark: "#06080b", light: "#f3f5f8" };

const oneOf = <T extends string>(v: unknown, allowed: readonly T[], fallback: T): T =>
  typeof v === "string" && (allowed as readonly string[]).includes(v) ? (v as T) : fallback;
const bool = (v: unknown, fallback: boolean): boolean => (typeof v === "boolean" ? v : fallback);

/** Stored JSON -> Prefs. Every field is validated on its own; anything missing or malformed takes its default. */
export function parsePrefs(raw: string | null, legacyTheme: string | null = null): Prefs {
  let v: Record<string, unknown> = {};
  if (raw) {
    try {
      const parsed = JSON.parse(raw) as unknown;
      if (parsed && typeof parsed === "object") v = parsed as Record<string, unknown>;
    } catch {
      /* corrupt: defaults */
    }
  }
  const legacy: ThemePref = legacyTheme === "light" ? "light" : DEFAULT_PREFS.theme;
  return {
    theme: oneOf(v.theme, ["dark", "light", "system"] as const, legacy),
    driveAlwaysDark: bool(v.driveAlwaysDark, DEFAULT_PREFS.driveAlwaysDark),
    night: bool(v.night, DEFAULT_PREFS.night),
    cvd: oneOf(v.cvd, ["standard", "rg"] as const, DEFAULT_PREFS.cvd),
    driveSize: oneOf(v.driveSize, ["standard", "large"] as const, DEFAULT_PREFS.driveSize),
    dimNav: bool(v.dimNav, DEFAULT_PREFS.dimNav),
    driveLock: oneOf(v.driveLock, ["off", "beginners", "everyone"] as const, DEFAULT_PREFS.driveLock),
  };
}

/** The theme actually shown: dark on Drive with "Drive always dark", else the chosen one (or the device's). */
export function effectiveTheme(p: Prefs, area: AreaId | null, systemDark: boolean): ThemeName {
  if (area === "drive" && p.driveAlwaysDark) return "dark";
  if (p.theme === "system") return systemDark ? "dark" : "light";
  return p.theme;
}

/** The attributes prefs put on <html>; `null` = attribute removed. */
export function htmlAttributes(p: Prefs, theme: ThemeName): Record<"data-theme" | "data-night" | "data-cvd" | "data-drive-size", string | null> {
  return {
    "data-theme": theme,
    "data-night": p.night ? "on" : null,
    "data-cvd": p.cvd === "rg" ? "rg" : null,
    "data-drive-size": p.driveSize === "large" ? "large" : null,
  };
}

/** Whether the Drive lock applies to a driver of this skill (unknown skill counts as a beginner: the safe side). */
export function driveLockApplies(lock: DriveLock, skill: SkillLevel | null | undefined): boolean {
  if (lock === "off") return false;
  if (lock === "everyone") return true;
  return skill == null || skill === "beginner";
}

function readStorage(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage unavailable (private mode): the choice lasts for this page only */
  }
}

function systemPrefersDark(): boolean {
  try {
    return typeof matchMedia === "function" ? matchMedia("(prefers-color-scheme: dark)").matches : true;
  } catch {
    return true;
  }
}

export interface PrefsState {
  prefs: Prefs;
  /** The area on screen (fed from the router by follow()); null before it is known. */
  area: AreaId | null;
  systemDark: boolean;
  /** effectiveTheme(prefs, area, systemDark). */
  theme: ThemeName;
}

/** A store the prefs can follow for the current area (the router). */
export interface AreaSource {
  get(): { route: { area: AreaId } };
  subscribe(listener: () => void): () => void;
}

export class PrefsStore extends Store<PrefsState> {
  constructor() {
    const prefs = parsePrefs(readStorage(PREFS_KEY), readStorage(LEGACY_THEME_KEY));
    const systemDark = systemPrefersDark();
    super({ prefs, area: null, systemDark, theme: effectiveTheme(prefs, null, systemDark) });
    try {
      matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => this.update({ systemDark: e.matches }));
    } catch {
      /* no matchMedia (tests, old browsers): the device theme is read once */
    }
    this.apply();
  }

  /** Change one preference (stored on this device). */
  setPref<K extends keyof Prefs>(key: K, value: Prefs[K]): void {
    this.setPrefs({ [key]: value } as Partial<Prefs>);
  }

  setPrefs(patch: Partial<Prefs>): void {
    const prefs = { ...this.get().prefs, ...patch };
    writeStorage(PREFS_KEY, JSON.stringify(prefs));
    if (prefs.theme !== "system") writeStorage(LEGACY_THEME_KEY, prefs.theme);
    this.update({ prefs });
  }

  /** Track the current area (Drive always dark). Returns the unsubscribe function. */
  follow(source: AreaSource): () => void {
    const sync = () => this.update({ area: source.get().route.area });
    sync();
    return source.subscribe(sync);
  }

  private update(patch: Partial<Omit<PrefsState, "theme">>): void {
    const next = { ...this.get(), ...patch };
    this.set({ ...patch, theme: effectiveTheme(next.prefs, next.area, next.systemDark) });
    this.apply();
  }

  /** Put the effective theme and the display attributes on <html>. */
  private apply(): void {
    if (typeof document === "undefined") return;
    const { prefs, theme } = this.get();
    const el = document.documentElement;
    el.classList.remove("dark", "light");
    el.classList.add(theme);
    for (const [k, v] of Object.entries(htmlAttributes(prefs, theme))) {
      if (v === null) el.removeAttribute(k);
      else el.setAttribute(k, v);
    }
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", THEME_COLOR[theme]);
  }
}

export const prefs = new PrefsStore();
