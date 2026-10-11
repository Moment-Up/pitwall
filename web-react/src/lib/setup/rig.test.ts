// Setup › Rig data layer (lane X, spec 7.2): src/lib/endpoints/rig.ts (paths, bodies, errors; fetch stubbed, no
// server, no write ever reaches the live service) and the pure helpers in src/lib/setup/rig.ts, on recorded answers
// of the live API (src/lib/setup/fixtures/rig-*.json).

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { json, memoryStorage, stubBrowser } from "../../test/fakes";
import { resetTokenCacheForTests } from "../auth";
import { MINUS, UNKNOWN } from "../format";
import {
  RIG_KEYS,
  RigError,
  checkPath,
  isNoSession,
  recommendationPath,
  rigApi,
  rigDetailText,
  rigErrorText,
  rigQs,
  upgradeBody,
  type SettingRow,
} from "../endpoints/rig";
import { fixtures } from "./fixtures";
import {
  GAME_KEY,
  STATUS_CHIP,
  checkLapsLine,
  checkSessionLine,
  clampScale,
  countsText,
  formatMetric,
  hardwareLine,
  isKit,
  kitFitted,
  parseRigQuery,
  rememberGame,
  rememberedGame,
  rigPath,
  rowChips,
  rowCopyText,
  rowEvidenceChip,
  rowValue,
  scaleText,
  sectionCopyText,
  sectionTitle,
  shownScale,
  strengthNote,
  styleSubtitle,
  supportedGames,
  todayIso,
  upgradeHistory,
  upgradeText,
  wheelCode,
} from "./rig";

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  resetTokenCacheForTests();
  stubBrowser("http://127.0.0.1:8770/next/#/setup/rig");
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

const lastCall = () => {
  const c = fetchMock.mock.calls.at(-1) as [string, RequestInit | undefined] | undefined;
  if (!c) throw new Error("fetch was not called");
  return { path: c[0], init: c[1] ?? {} };
};

const row = (key: string, rec = fixtures.rigRecF1James()): SettingRow => {
  const r = rec.sections.flatMap((s) => s.rows).find((x) => x.key === key);
  if (!r) throw new Error(`no row ${key}`);
  return r;
};

describe("rig paths and keys", () => {
  it("rigQs leaves unset values out", () => {
    expect(rigQs({ a: 1, b: null, c: undefined, d: "", e: false })).toBe("?a=1&e=false");
    expect(rigQs({})).toBe("");
  });

  it("recommendations: no style means the driver's saved style", () => {
    expect(recommendationPath({ game: "f1_25", driver_id: 1 })).toBe("/api/rig/recommendations?game=f1_25&driver_id=1");
    expect(recommendationPath({ game: "gt7", style: "comfort", platform: "ps5" })).toBe(
      "/api/rig/recommendations?game=gt7&style=comfort&platform=ps5",
    );
  });

  it("check: the latest session unless one is named", () => {
    expect(checkPath({ driver_id: 1, game: "f1_25", laps: "clean", baseline: "upgrade" })).toBe(
      "/api/rig/check?driver_id=1&game=f1_25&laps=clean&baseline=upgrade",
    );
    expect(checkPath({ session_id: "a b" })).toBe("/api/rig/check?session_id=a+b");
  });

  it("every cache key starts with rig: (a driver switch invalidates them all) and differs per request", () => {
    const keys = [
      RIG_KEYS.catalog,
      RIG_KEYS.profile,
      RIG_KEYS.prefs(1),
      RIG_KEYS.recommendations({ game: "f1_25", driver_id: 1 }),
      RIG_KEYS.recommendations({ game: "f1_25", driver_id: 2 }),
      RIG_KEYS.recommendations({ game: "gt7", driver_id: 1 }),
      RIG_KEYS.recommendations({ game: "f1_25", style: "comfort" }),
      RIG_KEYS.check({ driver_id: 1, game: "f1_25", laps: "clean" }),
      RIG_KEYS.check({ driver_id: 1, game: "f1_25", laps: "usable" }),
      RIG_KEYS.check({ driver_id: 1, game: "f1_25", laps: "clean", baseline: "upgrade" }),
    ];
    for (const k of keys) expect(k.startsWith(RIG_KEYS.all)).toBe(true);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("upgradeBody: fitted defaults to true, empty note and bad dates are left out, notes are capped at 200", () => {
    expect(upgradeBody({ change: "boost_kit_180" })).toEqual({ change: "boost_kit_180", fitted: true });
    expect(upgradeBody({ change: "load_cell_kit", fitted: false, date: "2026-10-11", note: "  " })).toEqual({
      change: "load_cell_kit",
      fitted: false,
      date: "2026-10-11",
    });
    expect(upgradeBody({ change: "firmware", date: "11/10/2026", note: " base 1.9.2.3 " })).toEqual({
      change: "firmware",
      fitted: true,
      note: "base 1.9.2.3",
    });
    expect(upgradeBody({ change: "other", note: "x".repeat(300) }).note).toHaveLength(200);
  });
});

describe("rig transport", () => {
  it("GETs with same-origin credentials", async () => {
    fetchMock.mockResolvedValueOnce(json(fixtures.rigProfile()));
    const p = await rigApi.profile();
    expect(p.wheel_base).toBe("fanatec_gt_dd_pro");
    expect(lastCall().path).toBe("/api/rig/profile");
    expect(lastCall().init.credentials).toBe("same-origin");
  });

  it("prefs updates are partial: a style tap never sends the force scale, and the other way round", async () => {
    fetchMock.mockImplementation(async () => json(fixtures.rigPrefsJames()));
    await rigApi.setPrefs(1, { style: "comfort" });
    expect(lastCall().path).toBe("/api/rig/drivers/1/prefs");
    expect(lastCall().init.method).toBe("PUT");
    expect(JSON.parse(String(lastCall().init.body))).toEqual({ style: "comfort" });
    await rigApi.setPrefs(1, { strength_scale: null });
    expect(JSON.parse(String(lastCall().init.body))).toEqual({ strength_scale: null });
    expect(new Headers(lastCall().init.headers).get("Content-Type")).toBe("application/json");
  });

  it("upgrades POST the cleaned body; profile changes PUT", async () => {
    fetchMock.mockImplementation(async () => json(fixtures.rigProfile()));
    await rigApi.upgrade({ change: "boost_kit_180", fitted: true, date: "2026-10-11", note: "" });
    expect(lastCall().path).toBe("/api/rig/upgrades");
    expect(lastCall().init.method).toBe("POST");
    expect(JSON.parse(String(lastCall().init.body))).toEqual({ change: "boost_kit_180", fitted: true, date: "2026-10-11" });
    await rigApi.updateProfile({ rim: "other" });
    expect(lastCall().init.method).toBe("PUT");
    expect(JSON.parse(String(lastCall().init.body))).toEqual({ rim: "other" });
  });

  it("errors keep FastAPI's detail in words (recorded 404 and 422)", async () => {
    fetchMock.mockResolvedValueOnce(json(fixtures.rigCheck404().body, 404));
    const e404 = await rigApi.check({ driver_id: 2, game: "gt7" }).catch((x: unknown) => x);
    expect(e404).toBeInstanceOf(RigError);
    expect(isNoSession(e404)).toBe(true);
    expect(rigErrorText(e404)).toBe("unknown driver 2");

    fetchMock.mockResolvedValueOnce(json(fixtures.rigRec422Gt7Pc().body, 422));
    const e422 = await rigApi.recommendations({ game: "gt7", platform: "pc" }).catch((x: unknown) => x);
    expect(isNoSession(e422)).toBe(false);
    expect(rigErrorText(e422)).toMatch(/no curated Gran Turismo 7 settings for pc/);

    fetchMock.mockResolvedValueOnce(json({ detail: "boost_kit_180 is already fitted: nothing to record" }, 409));
    const e409 = (await rigApi.upgrade({ change: "boost_kit_180" }).catch((x: unknown) => x)) as RigError;
    expect(e409.status).toBe(409);
    expect(rigErrorText(e409)).toBe("boost_kit_180 is already fitted: nothing to record");
  });

  it("rigDetailText handles strings, validation lists and nothing", () => {
    expect(rigDetailText([{ loc: ["query", "strength_scale"], msg: "Input should be less than or equal to 1" }])).toBe(
      "strength_scale: Input should be less than or equal to 1",
    );
    expect(rigDetailText(" ", 500)).toBe("request failed (HTTP 500)");
    expect(rigDetailText(null)).toBe("request failed");
    expect(rigErrorText(new Error("offline"))).toBe("offline");
  });
});

describe("rows: chips are never more certain than the evidence", () => {
  it("a sourced row says Verified with its source count; a Pitwall pick says so", () => {
    const ff = row("FF");
    expect(rowEvidenceChip(ff).label).toBe(`Verified · ${ff.provenance.consensus?.n} sources`);
    const sen = row("SEN");
    expect(sen.provenance.kind).toBe("range_pick");
    expect(rowEvidenceChip(sen).label).toBe("Pitwall pick in range");
    const ful = row("FUL");
    expect(ful.provenance.derived).toBe(true);
    expect(rowEvidenceChip(ful).label).toBe("Derived by Pitwall");
  });

  it("an unverified instruction is amber; locked rows say Set by the game", () => {
    const comfort = fixtures.rigRecF1ComfortBeginner();
    const bl = row("BRAKE_LINEARITY", comfort);
    expect(bl.instruction).toBe(true);
    expect(rowEvidenceChip(bl)).toMatchObject({ label: "Unverified", tone: "warning" });
    const gt7 = fixtures.rigRecGt7James();
    const sen = row("SEN", gt7);
    expect(sen.locked).toBe(true);
    expect(rowChips(sen).map((c) => c.label)).toContain("Set by the game");
  });

  it("chips follow the spec's order: range, factory, changed, advanced, game, evidence", () => {
    const int = row("INT");
    const labels = rowChips(int).map((c) => c.label);
    expect(labels.slice(0, 4)).toEqual([`Range ${int.range}`, `Factory ${int.factory_default}`, "Changed", "Advanced menu"]);
    expect(labels[4]).toBe("Pitwall pick in range");
  });

  it("values: words stay words, empty is -, a leading minus is U+2212", () => {
    expect(rowValue(row("FFS"))).toBe("PEA");
    expect(rowValue({ ...row("FF"), value: "" })).toBe(UNKNOWN);
    expect(rowValue({ ...row("FF"), value: "-3" })).toBe(`${MINUS}3`);
  });

  it("copy text lists rows in menu order, marks Pitwall values, then the steps", () => {
    const rec = fixtures.rigRecF1James();
    const wheel = rec.sections.find((s) => s.id === "wheel")!;
    const text = sectionCopyText(wheel, "F1 25 · Wheel");
    const lines = text.split("\n");
    expect(lines[0]).toBe("F1 25 · Wheel");
    expect(lines[1]).toBe(rowCopyText(wheel.rows[0]!));
    expect(lines.slice(1, 1 + wheel.rows.length).map((l) => l.split(" ")[0])).toEqual(wheel.rows.map((r) => r.key));
    expect(text).toContain("[Pitwall pick in 300-360]");
    expect(lines.at(-1)).toBe(`- ${wheel.steps.at(-1)!.text}`);
    expect(sectionTitle(wheel)).toBe("Wheel base Tuning Menu (on-wheel order)");
    const ingame = rec.sections.find((s) => s.id === "ingame")!;
    expect(sectionCopyText(ingame).split("\n")[0]!.startsWith(`${ingame.rows[0]!.label}: ${ingame.rows[0]!.value}`)).toBe(true); // no API ids
    expect(sectionCopyText(ingame)).not.toContain("VIB_FFB");
    expect(wheelCode("ingame", "VIB_FFB")).toBeNull();
    expect(wheelCode("wheel", "FF")).toBe("FF");
  });
});

describe("rig check", () => {
  it("formats every unit, unknown as -, negatives with U+2212", () => {
    expect(formatMetric({ value: null, unit: "%" })).toBe(UNKNOWN);
    expect(formatMetric({ value: 4.8809, unit: "%" })).toBe("4.9%");
    expect(formatMetric({ value: 100, unit: "%" })).toBe("100%");
    expect(formatMetric({ value: 0.0002, unit: "%" })).toBe("0.00%");
    expect(formatMetric({ value: 0.4336, unit: "s" })).toBe("0.43 s");
    expect(formatMetric({ value: 2.6667, unit: "per lap" })).toBe("2.7 a lap");
    expect(formatMetric({ value: -6.1179, unit: "points" })).toBe(`${MINUS}6.1 pts`);
    expect(formatMetric({ value: 3, unit: "points" })).toBe("+3.0 pts");
    expect(formatMetric({ value: 81.18, unit: "/min" })).toBe("81/min");
    expect(formatMetric({ value: 0.98, unit: "R²" })).toBe("0.98 R²");
  });

  it("status chips are status colours; unknown shows -", () => {
    expect(STATUS_CHIP.pass.tone).toBe("success");
    expect(STATUS_CHIP.warn.tone).toBe("warning");
    expect(STATUS_CHIP.fail.tone).toBe("danger");
    expect(STATUS_CHIP.unknown.label).toBe(UNKNOWN);
  });

  it("describes the recorded session", () => {
    const c = fixtures.rigCheckF1James();
    expect(countsText(c.counts)).toBe("3 warn · 7 pass · 5 info · 4 unknown");
    expect(countsText({})).toBe("No metrics");
    expect(checkSessionLine(c)).toMatch(/^Melbourne · race · /);
    expect(checkLapsLine(c)).toBe("Laps 1, 2, 3 (clean) · 60 Hz · Hall brake");
    const g = fixtures.rigCheckGt7James();
    expect(checkSessionLine(g)).toMatch(/^Unidentified GT7 circuit \(0\.92 km\) · /); // "unknown" type left out
    expect(checkLapsLine(g)).toContain("GT7 steering lock unknown");
  });
});

describe("hardware, upgrades, style and force", () => {
  it("the header line is short", () => {
    const p = fixtures.rigProfile();
    expect(hardwareLine(p, p.labels)).toBe("PS5 · GT DD Pro 5 Nm · CSL pedals");
    expect(hardwareLine({ ...p, torque_nm: 8, pedals: "csl_load_cell" })).toBe("PS5 · GT DD Pro 8 Nm · CSL pedals + load cell");
  });

  it("supported games follow the catalogue per platform", () => {
    const cat = fixtures.rigCatalog();
    expect(supportedGames(cat, "ps5")).toEqual(["f1_25", "gt7"]);
    expect(supportedGames(cat, "pc")).toEqual(["f1_25"]);
    expect(supportedGames(null, "pc")).toEqual(["f1_25", "gt7"]);
  });

  it("upgrades: only kits are fitted or removed; history is newest first", () => {
    expect(isKit("boost_kit_180")).toBe(true);
    expect(isKit("firmware")).toBe(false);
    expect(upgradeText({ change: "load_cell_kit", fitted: false })).toBe("CSL Pedals Load Cell Kit removed");
    expect(upgradeText({ change: "firmware", fitted: true })).toBe("Firmware update");
    const p = { ...fixtures.rigProfile(), boost_kit_fitted: true };
    expect(kitFitted(p, "boost_kit_180")).toBe(true);
    expect(kitFitted(p, "load_cell_kit")).toBe(false);
    expect(kitFitted(null, "boost_kit_180")).toBe(false);
    const ups = [
      { date: "2026-09-01", change: "firmware" as const, fitted: true, note: null, recorded_unix: 1 },
      { date: "2026-10-01", change: "boost_kit_180" as const, fitted: true, note: null, recorded_unix: 2 },
    ];
    expect(upgradeHistory({ upgrades: ups }).map((u) => u.date)).toEqual(["2026-10-01", "2026-09-01"]);
    expect(todayIso(new Date(2026, 0, 5))).toBe("2026-01-05");
  });

  it("style lines: Comfort says it is derived once, unsourced styles say so", () => {
    const cat = fixtures.rigCatalog();
    const comfort = cat.styles.find((s) => s.id === "comfort")!;
    expect(styleSubtitle(comfort, null)).toBe(comfort.description);
    const balanced = cat.styles.find((s) => s.id === "balanced")!;
    expect(styleSubtitle(balanced, { requested_style: "balanced", sourced: false })).toMatch(/derived by Pitwall\.$/);
    expect(styleSubtitle(balanced, { requested_style: "comfort", sourced: false })).toBe(balanced.description);
  });

  it("force scale: the driver's own value, else the default the recommendation applied", () => {
    const prefs = fixtures.rigPrefsJames();
    const comfort = fixtures.rigRecF1ComfortBeginner();
    expect(shownScale(prefs, fixtures.rigRecF1James())).toBe(1);
    expect(shownScale({ ...prefs, prefs: { ...prefs.prefs, strength_scale: null } }, comfort)).toBe(0.6);
    expect(shownScale({ ...prefs, prefs: { ...prefs.prefs, strength_scale: 0.75 } }, comfort)).toBe(0.75);
    expect(scaleText(0.6)).toBe("60%");
    expect(scaleText(null)).toBe(UNKNOWN);
    expect(clampScale(0.123)).toBe(0.2);
    expect(clampScale(0.66)).toBe(0.65);
    expect(clampScale(1.3)).toBe(1);
    const beginner = { ...prefs, skill_level: "beginner" as const, prefs: { ...prefs.prefs, strength_scale: null } };
    expect(strengthNote(beginner, comfort)).toBe("Using the beginner default (60%).");
    expect(strengthNote(beginner, { ...comfort, hardware: { ...comfort.hardware, torque_nm: 8 }, strength_scale: 0.4 })).toBe(
      "Using the beginner default (40%): lower on the 8 Nm base so the wheel keeps its 5 Nm weight.",
    );
    expect(strengthNote({ ...prefs, prefs: { ...prefs.prefs, strength_scale: 0.7 } }, comfort)).toBe("Set for this driver.");
  });
});

describe("page query and the remembered game", () => {
  it("parses driver and game, ignoring junk", () => {
    expect(parseRigQuery("driver=2&game=gt7")).toEqual({ driver: 2, game: "gt7" });
    expect(parseRigQuery("driver=x&game=forza")).toEqual({ driver: null, game: null });
    expect(parseRigQuery("")).toEqual({ driver: null, game: null });
  });

  it("builds view paths that keep the query", () => {
    expect(rigPath("walk")).toBe("/setup/rig");
    expect(rigPath("walk", { driver: 1, game: "f1_25" }, { section: "wheel", n: 3 })).toBe("/setup/rig/walk/wheel/3?driver=1&game=f1_25");
    expect(rigPath("check", { game: "gt7" })).toBe("/setup/rig/check?game=gt7");
    expect(rigPath("settings", { driver: null })).toBe("/setup/rig/settings");
  });

  it("remembers the game in the Svelte page's key, and survives blocked storage", () => {
    const local = memoryStorage();
    vi.stubGlobal("localStorage", local);
    expect(rememberedGame()).toBeNull();
    rememberGame("gt7");
    expect(local.getItem(GAME_KEY)).toBe("gt7");
    expect(rememberedGame()).toBe("gt7");
    local.setItem(GAME_KEY, "forza");
    expect(rememberedGame()).toBeNull();
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    });
    expect(rememberedGame()).toBeNull();
    expect(() => rememberGame("f1_25")).not.toThrow();
  });
});
