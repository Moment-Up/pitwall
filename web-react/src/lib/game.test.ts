// Game selection on the dashboard (lib/game.ts): the capability rendering rules over the catalogue fixture
// (src/test/fixtures/game, tier "edited": the backend's games.py output from hand-built inputs): supported / partial / not sent / not in Pitwall yet / unknown,
// nothing selected, a mismatch. The rule that matters most: only what a game is KNOWN not to send ever replaces a dash
// with words; an unknown feature never does, and no helper shows a claim stronger than the server's.
import { describe, expect, it } from "vitest";
import { FEATURE_IDS, type FeatureId, type GameEntry } from "./endpoints/game";
import {
  actionLines,
  available,
  carSetupGate,
  driveMismatch,
  effectiveEntry,
  entryById,
  evidenceWords,
  featureChip,
  featureCounts,
  featureGroups,
  featureOf,
  gameAlertView,
  gameChip,
  idleInputs,
  mismatchVisibleOnDrive,
  missing,
  moreGamesLabel,
  noDataText,
  noSectorsCaption,
  nounsOf,
  pickedId,
  pickerCards,
  pickerSelection,
  readable,
  rigDefaultGame,
  rigNotice,
  rigPlatformNotice,
  seatGameLine,
  selectedEntry,
  selectionReason,
  sessionEntry,
  sessionGameLabel,
  stableGameSelector,
  supportTone,
  trackEmptyText,
  tyresUnavailableText,
  unavailable,
  unavailableLine,
  unreadableReason,
} from "./game";
import { catalogue, entry, gameState, putResponse, snapGame } from "./game-testkit";

const CAT = catalogue();
const F1 = entry("f1_25:ps5", CAT);
const GT7 = entry("gt7:ps5", CAT);
const AC = entry("ac:ps5", CAT);
const FM = entry("forza_motorsport:pc", CAT);
const FH = entry("forza_horizon:xbox", CAT);
const FH_PS5 = entry("forza_horizon:ps5", CAT);
const OTHER = entry("other:any", CAT);
const ACC_PS5 = entry("acc:ps5", CAT);
const ACC_PC = entry("acc:pc", CAT);

describe("the catalogue fixture is the spec's contract", () => {
  it("has 23 entries, each with the 27 features in order", () => {
    expect(CAT.schema).toBe(1);
    expect(CAT.entries).toHaveLength(23);
    expect(new Set(CAT.entries.map((e) => e.id)).size).toBe(23);
    for (const e of CAT.entries) {
      expect(e.id).toMatch(/^[a-z0-9_]+:(ps5|ps4|xbox|pc|any)$/);
      expect(e.features.map((f) => f.id)).toEqual(FEATURE_IDS);
      for (const f of e.features) {
        expect(f.short.length).toBeLessThanOrEqual(32);
        expect(f.reason).toMatch(/\.$/);
        if (f.status !== "supported" && f.status !== "partial") expect(f.evidence).toBeNull();
      }
    }
    expect(CAT.features.map((f) => f.id)).toEqual(FEATURE_IDS);
  });

  it("carries the golden profile of spec 2.6 (spot checks)", () => {
    const st = (e: GameEntry, id: FeatureId) => featureOf(e, id)?.status;
    expect(st(F1, "sectors")).toBe("supported");
    expect(st(F1, "damage")).toBe("not_implemented");
    expect(st(F1, "session_info")).toBe("partial");
    expect(st(GT7, "sectors")).toBe("not_sent");
    expect(st(GT7, "fuel")).toBe("not_implemented");
    expect(st(GT7, "delta")).toBe("partial");
    expect(featureOf(GT7, "delta")?.short).toBe("Estimated");
    expect(st(AC, "tyre_temps")).toBe("not_sent");
    expect(st(FM, "tyre_wear")).toBe("supported");
    expect(st(FH, "tyre_wear")).toBe("not_sent");
    expect(featureOf(F1, "ai_field")?.evidence).toBe("recorded_validated");
    expect(featureOf(entry("f1_25:pc", CAT), "ai_field")?.evidence).toBe("spec_implemented");
    // --- spotter --- F1 25 sends every car's Motion (recorded on PS5 only); the other games send the player's car alone
    expect(st(F1, "spotter")).toBe("supported");
    expect(featureOf(F1, "spotter")?.evidence).toBe("recorded_validated");
    expect(st(GT7, "spotter")).toBe("not_sent");
    expect(st(FM, "spotter")).toBe("not_sent");
    expect(st(AC, "spotter")).toBe("not_sent");
    expect(ACC_PS5.features.every((f) => f.status === "not_sent")).toBe(true);
    // ACC on PC (feat/acc): read from its shared memory, every claim "partial" at most; what ACC has and Pitwall does
    // not map is "not in Pitwall yet" (fuel, flags, sectors...), never "not sent"
    expect(ACC_PC.implemented).toBe(true);
    expect(ACC_PC.support.level).toBe("partial");
    expect(st(ACC_PC, "lap_timing")).toBe("supported");
    expect(featureOf(ACC_PC, "lap_timing")?.evidence).toBe("partial");
    expect(featureOf(ACC_PC, "delta")?.short).toBe("Estimated");
    for (const id of ["sectors", "fuel", "flags", "tyre_temps", "damage", "spotter"] as const) expect(st(ACC_PC, id)).toBe("not_implemented");
    expect(st(ACC_PC, "tyre_wear")).toBe("not_sent");
    expect(ACC_PC.features.every((f) => f.evidence === null || f.evidence === "partial")).toBe(true);
    expect(OTHER.features.every((f) => f.status === "unknown")).toBe(true);
    expect(FH_PS5.features.filter((f) => f.status !== "not_sent" && f.status !== "not_implemented").every((f) => f.status === "unknown")).toBe(true);
  });
});

describe("lookups", () => {
  it("finds entries and the effective one: the detected game beats the selected one", () => {
    expect(entryById(CAT, "gt7:ps5")?.label).toBe("Gran Turismo 7");
    expect(entryById(CAT, "nope:ps5")).toBeNull();
    expect(entryById(undefined, "gt7:ps5")).toBeNull();
    expect(effectiveEntry(CAT, snapGame("mismatch"))?.id).toBe("f1_25:ps5");
    expect(selectedEntry(CAT, snapGame("mismatch"))?.id).toBe("gt7:ps5");
    expect(effectiveEntry(CAT, snapGame("gt7"))?.id).toBe("gt7:ps5");
    // the synthetic demo is detected (effective) but never a mismatch
    expect(effectiveEntry(CAT, snapGame("synthetic"))?.id).toBe("f1_25:ps5");
    expect(snapGame("synthetic").mismatch).toBeNull();
  });

  it("an older server (no snapshot.game) or no catalogue yet: nothing is known", () => {
    expect(effectiveEntry(CAT, undefined)).toBeNull();
    expect(effectiveEntry(undefined, snapGame("gt7"))).toBeNull();
    expect(selectedEntry(CAT, undefined)).toBeNull();
    expect(effectiveEntry(CAT, snapGame("none"))).toBeNull();
  });
});

describe("available / unavailable: known facts only", () => {
  it("supported and partial are available; not sent and not in Pitwall yet are unavailable; unknown is neither", () => {
    expect(available(featureOf(F1, "sectors"))).toBe(true);
    expect(available(featureOf(GT7, "delta"))).toBe(true);
    expect(unavailable(featureOf(GT7, "sectors"))).toBe(true);
    expect(unavailable(featureOf(GT7, "fuel"))).toBe(true);
    const u = featureOf(OTHER, "sectors");
    expect(u?.status).toBe("unknown");
    expect(available(u)).toBe(false);
    expect(unavailable(u)).toBe(false);
    expect(missing(OTHER, "sectors")).toBe(false);
    expect(missing(null, "sectors")).toBe(false);
    expect(missing(GT7, "sectors")).toBe(true);
  });

  it("never treats an unknown feature as unavailable, for any entry (P5: unknown stays '-')", () => {
    for (const e of CAT.entries) {
      for (const f of e.features) {
        if (f.status === "unknown") expect(unavailable(f), `${e.id} ${f.id}`).toBe(false);
        expect(available(f) && unavailable(f)).toBe(false);
      }
    }
  });
});

describe("unavailableLine", () => {
  it("groups by the server's short text and joins the nouns (spec 5.4 examples)", () => {
    expect(unavailableLine(GT7, ["fuel", "ers"])).toBe("Fuel, ERS: not in Pitwall yet");
    expect(unavailableLine(GT7, ["tyre_wear", "tyre_pressures"])).toBe("Tyre wear, pressures: not sent by GT7");
    expect(unavailableLine(AC, ["fuel", "ers"])).toBe("Fuel, ERS: not sent by Assetto Corsa");
    // health lane: Forza fuel is now estimated from the tank level (partial), so it is no longer in the line
    expect(unavailableLine(FM, ["fuel", "ers"])).toBe("ERS: not sent by Forza Motorsport");
    expect(unavailableLine(FM, ["official_corner_names", "ers"])).toBe(
      "Official corner names: not in Pitwall yet · ERS: not sent by Forza Motorsport",
    );
    expect(unavailableLine(AC, ["tyre_temps", "tyre_wear", "tyre_pressures"])).toBe(
      "Tyre temperatures, wear, pressures: not sent by Assetto Corsa",
    );
  });

  it("is null when everything is available, nothing is known, or no entry", () => {
    expect(unavailableLine(F1, ["fuel", "ers", "tyre_wear"])).toBeNull();
    expect(unavailableLine(OTHER, ["fuel", "ers"])).toBeNull(); // unknown: the dashes stay
    expect(unavailableLine(null, ["fuel"])).toBeNull();
  });

  it("leaves unknown features out of a mixed line", () => {
    // Forza Horizon on PS5 is unverified: DRS is still known not sent, tyre temperatures are unknown.
    expect(featureOf(FH_PS5, "tyre_temps")?.status).toBe("unknown");
    expect(unavailableLine(FH_PS5, ["tyre_temps", "drs"])).toBe("DRS: not sent by Forza Horizon");
  });

  it("uses the catalogue's nouns", () => {
    const nouns = nounsOf(CAT);
    expect(nouns.ers).toBe("ERS");
    expect(unavailableLine(GT7, ["field_data"], nouns)).toBe("Data about the other cars: not sent by GT7");
  });

  it("says the whole tyre block in one line only when the game sends none of it", () => {
    expect(tyresUnavailableText(AC)).toBe("Assetto Corsa doesn't send tyre data");
    expect(tyresUnavailableText(GT7)).toBeNull();
    expect(tyresUnavailableText(F1)).toBeNull();
    expect(tyresUnavailableText(OTHER)).toBeNull();
    expect(tyresUnavailableText(null)).toBeNull();
  });
});

describe("gameChip (rail / app bar)", () => {
  it("nothing selected and nothing detected: 'Game?' in the warn tone", () => {
    expect(gameChip(snapGame("none"), CAT)).toMatchObject({ text: "Game?", tone: "warn" });
  });

  it("a selection: its short label, neutral", () => {
    const v = gameChip(snapGame("gt7"), CAT);
    expect(v).toMatchObject({ text: "GT7", tone: "neutral" });
    expect(v?.aria).toBe("Game: Gran Turismo 7 on PS5 selected");
  });

  it("a seat change picked it: the chip says why, and so does the Ready card's seat line (plan 0.3 step 1)", () => {
    const g = { ...snapGame("gt7"), selected_source: "driver_default", selected_by: 2 };
    const names = new Map([[2, "Sam"]]);
    expect(gameChip(g, CAT, names)?.aria).toBe("Game: Gran Turismo 7 on PS5 selected. Selected because Sam usually plays GT7");
    expect(seatGameLine(g, CAT, names)).toBe("GT7 · Sam usually plays GT7");
    // chosen on the dashboard, an unknown driver, or another game's data on screen: no seat line
    expect(seatGameLine({ ...g, selected_source: "dashboard" }, CAT, names)).toBeNull();
    expect(seatGameLine(g, CAT, new Map())).toBeNull();
    expect(seatGameLine({ ...snapGame("mismatch"), selected_source: "driver_default", selected_by: 2 }, CAT, names)).toBeNull();
  });

  it("another game's data: the effective short label, warn, the server's mismatch words", () => {
    const v = gameChip(snapGame("mismatch"), CAT);
    expect(v).toMatchObject({ text: "F1 25", tone: "warn" });
    expect(v?.aria).toContain("Receiving F1 25, but Gran Turismo 7 (PS5) is selected.");
  });

  it("detected but nothing selected: warn; a synthetic replay of another game: neutral (no mismatch)", () => {
    expect(gameChip(snapGame("suggest"), CAT)).toMatchObject({ text: "F1 25", tone: "warn" });
    const syn = gameChip(snapGame("synthetic"), CAT);
    expect(syn).toMatchObject({ text: "F1 25", tone: "neutral" });
    expect(syn?.aria).toBe("Game: F1 25 on PS5 data on screen; Gran Turismo 7 on PS5 selected");
  });

  it("a platform / UDP-format mismatch keeps the chip neutral (it is shown on Setup › Game)", () => {
    expect(gameChip(snapGame("variant"), CAT)).toMatchObject({ text: "F1 25", tone: "neutral" });
  });

  it("renders nothing before the catalogue loads or with an older server", () => {
    expect(gameChip(undefined, CAT)).toBeNull();
    expect(gameChip(snapGame("gt7"), undefined)).toBeNull();
  });
});

describe("Drive's mismatch line", () => {
  const game = { kind: "game" as const };
  it("only for another game, only while stationary", () => {
    expect(mismatchVisibleOnDrive(game, null)).toBe(true);
    expect(mismatchVisibleOnDrive(game, { speed_kph: 0 })).toBe(true);
    expect(mismatchVisibleOnDrive(game, { speed_kph: 4.9 })).toBe(true);
    expect(mismatchVisibleOnDrive(game, { speed_kph: 5 })).toBe(false);
    expect(mismatchVisibleOnDrive(game, { speed_kph: 212 })).toBe(false);
    expect(mismatchVisibleOnDrive(game, { speed_kph: null })).toBe(false); // speed unknown: not known stationary
    expect(mismatchVisibleOnDrive({ kind: "platform" }, null)).toBe(false);
    expect(mismatchVisibleOnDrive({ kind: "variant" }, null)).toBe(false);
    expect(mismatchVisibleOnDrive(null, null)).toBe(false);
  });

  it("says which data arrives and which game is selected", () => {
    expect(driveMismatch(snapGame("mismatch"), CAT, { speed_kph: 0 })).toEqual({
      text: "F1 25 data · GT7 selected",
      sub: "tap to change", // the band is a link to Setup › Game
    });
    expect(driveMismatch(snapGame("mismatch"), CAT, { speed_kph: 150 })).toBeNull();
    expect(driveMismatch(snapGame("variant"), CAT, null)).toBeNull();
    expect(driveMismatch(snapGame("synthetic"), CAT, null)).toBeNull();
    expect(driveMismatch(snapGame("mismatch"), undefined, null)).toBeNull();
  });
});

describe("the picker", () => {
  const cards = pickerCards(CAT);

  it("main cards in the spec's order, the rest under More games", () => {
    expect(cards.main.map((c) => c.key)).toEqual(["f1_25", "gt7", "ac", "forza_motorsport", "forza_horizon", "other"]);
    expect(cards.more.map((c) => c.key)).toEqual(["acc", "iracing", "f1_24"]);
    expect(cards.main.map((c) => c.title)).toEqual([
      "F1 25",
      "Gran Turismo 7",
      "Assetto Corsa",
      "Forza Motorsport (2023)",
      "Forza Horizon 4 / 5",
      "Another game",
    ]);
  });

  it("platforms: main first, then the strongest evidence, then PS5 / PS4 / Xbox / PC", () => {
    const plat = (k: string) => [...cards.main, ...cards.more].find((c) => c.key === k)!.platforms.map((p) => p.platform);
    expect(plat("f1_25")).toEqual(["ps5", "xbox", "pc"]);
    expect(plat("gt7")).toEqual(["ps5", "ps4"]);
    expect(plat("ac")).toEqual(["ps5", "ps4", "pc", "xbox"]);
    expect(plat("forza_horizon")).toEqual(["xbox", "pc", "ps5"]);
    expect(plat("acc")).toEqual(["pc", "ps5", "xbox"]);
  });

  it("support words come from the server, never stronger (Xbox One AC is not supported, ACC on PC partial)", () => {
    const ac = cards.main.find((c) => c.key === "ac")!;
    expect(ac.platforms.map((p) => p.words)).toEqual([
      "Tested on a recording",
      "Built from community docs",
      "Built from community docs",
      "Not supported",
    ]);
    expect(cards.more.find((c) => c.key === "acc")!.platforms[0]!.words).toBe("Partial");
    expect(cards.main.find((c) => c.key === "other")!.platforms[0]!.words).toBe("Records packets only");
    expect(cards.main.find((c) => c.key === "f1_25")!.platforms[0]!.words).toBe("Tested live");
  });

  it("F1 25 folds the 2026 Season Pack into a switch", () => {
    const f1 = cards.main[0]!;
    expect(f1.hasSeason2026).toBe(true);
    expect(f1.platforms.map((p) => p.season2026)).toEqual(["f1_25_2026:ps5", "f1_25_2026:xbox", "f1_25_2026:pc"]);
    expect(pickedId(f1.platforms[0]!, true)).toBe("f1_25_2026:ps5");
    expect(pickedId(f1.platforms[0]!, false)).toBe("f1_25:ps5");
    expect(cards.main.find((c) => c.key === "gt7")!.hasSeason2026).toBe(false);
  });

  it("maps a selected id back to its card and platform", () => {
    expect(pickerSelection(cards, "f1_25_2026:pc")).toEqual({ card: "f1_25", platform: "f1_25:pc", season2026: true });
    expect(pickerSelection(cards, "gt7:ps4")).toEqual({ card: "gt7", platform: "gt7:ps4", season2026: false });
    expect(pickerSelection(cards, "iracing:pc")).toEqual({ card: "iracing", platform: "iracing:pc", season2026: false });
    expect(pickerSelection(cards, null)).toBeNull();
    expect(pickerSelection(cards, "nope:pc")).toBeNull();
  });

  it("is empty without a catalogue", () => {
    expect(pickerCards(undefined)).toEqual({ main: [], more: [] });
  });
});

describe("the feature list (Setup › Game)", () => {
  it("chips: only live / recorded evidence is green; docs-only support stays neutral (P8)", () => {
    expect(featureChip(featureOf(F1, "ai_field")!)).toEqual({ label: "Supported", tone: "success" }); // recorded
    expect(featureChip(featureOf(F1, "sectors")!)).toEqual({ label: "Supported", tone: "default" }); // spec
    expect(featureChip(featureOf(GT7, "tyre_temps")!)).toEqual({ label: "Supported", tone: "default" }); // community
    expect(featureChip(featureOf(AC, "lap_timing")!)).toEqual({ label: "Supported", tone: "success" }); // recorded
    expect(featureChip(featureOf(GT7, "delta")!).label).toBe("Estimated");
    expect(featureChip(featureOf(F1, "session_info")!).label).toBe("Partial");
    // a fact about the game, not a fault: never red (red is kept for behind / brake and failures)
    expect(featureChip(featureOf(GT7, "sectors")!)).toEqual({ label: "Not sent", tone: "default" });
    expect(featureChip(featureOf(GT7, "fuel")!).label).toBe("Not in Pitwall yet");
    expect(featureChip(featureOf(OTHER, "fuel")!)).toEqual({ label: "Unknown", tone: "default" });
  });

  it("no feature of any entry is ever green without validated evidence", () => {
    for (const e of CAT.entries) {
      for (const f of e.features) {
        if (featureChip(f).tone === "success") expect(["live_validated", "recorded_validated"]).toContain(f.evidence);
      }
    }
  });

  it("groups in the catalogue's order, available first inside a group", () => {
    const groups = featureGroups(GT7, CAT);
    expect(groups.map((g) => g.label)).toEqual(["Timing", "Coaching", "Track", "Car & tyres", "Session & race", "Setup & radio"]);
    const car = groups.find((g) => g.id === "car")!.features;
    expect(car[0]!.id).toBe("tyre_temps");
    const firstUnavailable = car.findIndex((f) => !available(f));
    expect(car.slice(firstUnavailable).some(available)).toBe(false);
    // + race radio (race_position, penalties), + health lane (engine temperature), + spotter
    expect(groups.flatMap((g) => g.features)).toHaveLength(27);
    expect(featureCounts(GT7)).toEqual({ available: 7, unavailable: 20, unknown: 0 });
    expect(featureCounts(OTHER)).toEqual({ available: 0, unavailable: 0, unknown: 27 });
  });

  it("evidence words are the server's support words", () => {
    expect(evidenceWords(featureOf(GT7, "tyre_temps")!, CAT)).toBe("Built from community docs");
    expect(evidenceWords(featureOf(GT7, "sectors")!, CAT)).toBeNull();
  });

  it("support tones: validated green, docs neutral, unsupported red", () => {
    expect(supportTone("live_validated")).toBe("success");
    expect(supportTone("community_documented")).toBe("default");
    expect(supportTone("unverified")).toBe("warning");
    expect(supportTone("unsupported")).toBe("danger");
    expect(supportTone(null)).toBe("default");
  });

  it("readable: an adapter that is implemented; others say why in the server's words", () => {
    expect(readable(GT7)).toBe(true);
    expect(readable(OTHER)).toBe(false);
    expect(readable(ACC_PS5)).toBe(false);
    expect(unreadableReason(ACC_PS5)).toBe("ACC on PS5 has no telemetry output.");
    expect(readable(ACC_PC)).toBe(true); // shared memory on the gaming PC (feat/acc)
    expect(ACC_PC.transport).toMatchObject({ kind: "shared_memory", port: null, console_ip: "no", in_game_setting: false });
    expect(ACC_PC.integration).toBe("acc");
    expect(ACC_PC.guide_id).toBe("acc");
  });

  it("PUT actions are the server's messages, toned by kind", () => {
    const lines = actionLines(putResponse().actions);
    // GT7 without a console IP: the selection is saved, the input stays off (it would search the whole network)
    expect(lines.map((l) => [l.text, l.tone])).toEqual([
      [
        "Enter the PS5's IP address to switch the GT7 input on. Without one, Pitwall can search the network for the console instead: Search the network on Setup › Game, or switch GT7 on at Setup › Connect.",
        "warning",
      ],
    ]);
    expect(actionLines([{ key: "gt7", action: "enabled", message: "GT7 input switched on (UDP 33740)." }])[0]!.tone).toBe("success");
    expect(actionLines([{ key: "forza", action: "error", message: "Port 33740 is GT7's" }])[0]!.tone).toBe("danger");
    // ACC chosen on a Mac: switched on, but it can only be read on the PC that runs the game
    expect(actionLines([{ key: "acc", action: "needs_windows", message: "ACC shares its telemetry only on ..." }])[0]!.tone).toBe(
      "warning",
    );
  });
});

describe("sessions (Review): the session's own game", () => {
  it("labels a row by its entry, else the raw game", () => {
    expect(sessionGameLabel(CAT, { game: "gt7", game_entry_id: "gt7:ps5" })).toBe("GT7");
    expect(sessionGameLabel(CAT, { game: "f1_25", game_entry_id: null })).toBe("F1 25");
    expect(sessionGameLabel(CAT, { game: "f1_25" })).toBe("F1 25");
    expect(sessionEntry(CAT, { game_entry_id: "ac:ps5" })?.id).toBe("ac:ps5");
  });

  it("with its platform for the session header (plan 5.11): the entry's words, else the row's platform", () => {
    expect(sessionGameLabel(CAT, { game: "gt7", game_entry_id: "gt7:ps5" }, { platform: true })).toBe(`GT7 · ${GT7.platform_label}`);
    expect(sessionGameLabel(CAT, { game: "f1_25", game_entry_id: "f1_25:ps5", platform: "ps5" }, { platform: true })).toBe(
      `F1 25 · ${F1.platform_label}`,
    );
    expect(sessionGameLabel(CAT, { game: "f1_25", game_entry_id: null, platform: "ps5" }, { platform: true })).toBe("F1 25 · PS5");
    expect(sessionGameLabel(null, { game: "f1_25", game_entry_id: null, platform: "xbox" }, { platform: true })).toBe("F1 25 · Xbox");
    expect(sessionGameLabel(CAT, { game: "f1_25", game_entry_id: null, platform: null }, { platform: true })).toBe("F1 25");
    expect(sessionGameLabel(CAT, { game: "f1_25", game_entry_id: null, platform: "unknown" }, { platform: true })).toBe("F1 25");
    expect(sessionGameLabel(CAT, { game: "", game_entry_id: null, platform: "ps5" }, { platform: true })).toBe("-");
  });

  it("drops the sector columns only for a game known not to send them", () => {
    expect(noSectorsCaption(GT7)).toBe("GT7 sends no sector times.");
    expect(noSectorsCaption(AC)).toBe("Assetto Corsa sends no sector times.");
    expect(noSectorsCaption(F1)).toBeNull();
    expect(noSectorsCaption(OTHER)).toBeNull();
    expect(noSectorsCaption(null)).toBeNull();
  });
});

describe("setup pages", () => {
  it("Car setup: the F1 25 only gate for a game without recommendations", () => {
    expect(carSetupGate(GT7)).toEqual({
      title: "Car setups: F1 25 only",
      text: "Gran Turismo 7 is selected. Pitwall's car setup recommendations exist for F1 25 only.",
    });
    expect(carSetupGate(FM)?.text).toBe("Forza Motorsport (2023) is selected. Pitwall's car setup recommendations exist for F1 25 only.");
    expect(carSetupGate(F1)).toBeNull(); // partial (F1 25 only) is available
    expect(carSetupGate(entry("f1_25_2026:pc", CAT))).toBeNull();
    expect(carSetupGate(OTHER)).not.toBeNull();
    expect(carSetupGate(null)).toBeNull(); // nothing selected: the page as today
  });

  it("Rig: URL, then the selected game's rig game, then the device's, then the first", () => {
    const games = ["f1_25", "gt7"] as const;
    expect(rigDefaultGame({ url: "gt7", selected: "f1_25", remembered: "f1_25", games, fallback: "f1_25" })).toBe("gt7");
    expect(rigDefaultGame({ url: null, selected: "gt7", remembered: "f1_25", games, fallback: "f1_25" })).toBe("gt7");
    expect(rigDefaultGame({ url: null, selected: null, remembered: "gt7", games, fallback: "f1_25" })).toBe("gt7");
    expect(rigDefaultGame({ url: null, selected: undefined, remembered: null, games, fallback: "f1_25" })).toBe("f1_25");
    // a game the rig catalogue does not offer for this platform is skipped
    expect(rigDefaultGame({ url: null, selected: "gt7", remembered: null, games: ["f1_25"], fallback: "f1_25" })).toBe("f1_25");
    expect(rigDefaultGame({ url: null, selected: null, remembered: null, games: [], fallback: "f1_25" })).toBe("f1_25");
  });

  it("Rig: a notice for a game without a researched rig guide, and for another platform", () => {
    expect(rigNotice(FM, "f1_25")).toBe(
      "The rig guide is researched for F1 25 and GT7; Forza Motorsport (2023) isn't covered yet. Showing F1 25.",
    );
    expect(rigNotice(GT7, "gt7")).toBeNull();
    expect(rigNotice(null, "f1_25")).toBeNull();
    expect(rigPlatformNotice(entry("f1_25:pc", CAT), "ps5", "PS5")).toBe(
      "F1 25 on PC is selected, but the rig profile is set to PS5. Change the platform under All settings if that is wrong.",
    );
    expect(rigPlatformNotice(F1, "ps5", "PS5")).toBeNull();
    expect(rigPlatformNotice(entry("f1_25:xbox", CAT), "ps5", "PS5")).toBeNull(); // no rig platform researched
  });

  it("Track: an estimated map says why after the usual words", () => {
    expect(trackEmptyText(GT7)).toBe(
      "The corners appear after your first clean lap. GT7 sends no lap distance: Pitwall works it out from speed (about 1 % drift per lap).",
    );
    expect(trackEmptyText(F1)).toBe("The corners appear after your first clean lap.");
    expect(trackEmptyText(null)).toBe("The corners appear after your first clean lap.");
    expect(featureOf(F1, "track_map")?.note).toBeTruthy();
  });
});

describe("the alert outside Drive", () => {
  it("another game: Switch / Keep, dismissed per session", () => {
    const v = gameAlertView(snapGame("mismatch"), CAT, "S1");
    expect(v).toEqual({
      kind: "mismatch",
      text: "Receiving F1 25, but Gran Turismo 7 (PS5) is selected.",
      switchId: "f1_25:ps5",
      switchLabel: "Switch to F1 25 · PS5",
      keepLabel: "Keep GT7",
      keepKey: "S1|gt7:ps5|f1_25:ps5",
    });
    expect(gameAlertView(snapGame("mismatch"), CAT, "S1", (k) => k === "S1|gt7:ps5|f1_25:ps5")).toBeNull();
    expect(gameAlertView(snapGame("mismatch"), CAT, "S2", (k) => k === "S1|gt7:ps5|f1_25:ps5")?.kind).toBe("mismatch");
  });

  it("a live suggestion while nothing is selected", () => {
    expect(gameAlertView(snapGame("suggest"), CAT, null)).toEqual({
      kind: "suggest",
      text: "Pitwall sees F1 25 telemetry from a PS5.",
      id: "f1_25:ps5",
      yesLabel: "Yes, F1 25 · PS5",
    });
  });

  it("nothing for a platform / format mismatch (Setup › Game shows it), a synthetic replay, or an older server", () => {
    expect(gameAlertView(snapGame("variant"), CAT, "S1")).toBeNull();
    expect(gameAlertView(snapGame("synthetic"), CAT, "S1")).toBeNull();
    expect(gameAlertView(snapGame("gt7"), CAT, "S1")).toBeNull();
    expect(gameAlertView(undefined, CAT, "S1")).toBeNull();
  });
});

describe("GET /api/game fixtures match the contract", () => {
  it("first run has no selection and a history suggestion; F1 can never be switched off", () => {
    const fr = gameState("first-run");
    expect(fr.first_run).toBe(true);
    expect(fr.selected).toBeNull();
    expect(fr.suggestion?.source).toBe("history");
    for (const name of ["first-run", "gt7", "ac", "mismatch", "acc", "forza"]) {
      for (const o of gameState(name).other_inputs) if (o.key === "f1") expect(o.can_disable).toBe(false);
    }
    expect(gameState("acc").input).toBeNull(); // ACC on PS5: no telemetry at all
    expect(gameState("ac").input?.console_ip_need).toBe("required");
    // ACC on PC chosen on a Mac (feat/acc): the input is on, no IP, no port, and the reader says why nothing comes
    const accPc = gameState("acc-pc").input!;
    expect(accPc).toMatchObject({ key: "acc", enabled: true, active: true, console_ip_need: "no", port: null, in_use: false });
    expect(accPc.reader?.state).toBe("not_windows");
    expect(accPc.reader?.message).toContain("this Mac can't read it");
  });
});

describe("the live binding", () => {
  it("keeps one object while snapshot.game's content is unchanged (no 20 Hz re-renders)", () => {
    const sel = stableGameSelector();
    const a = sel({ game: snapGame("gt7") });
    expect(sel({ game: snapGame("gt7") })).toBe(a); // a new snapshot, the same content
    const b = sel({ game: snapGame("mismatch") });
    expect(b).not.toBe(a);
    expect(b?.mismatch?.kind).toBe("game");
    expect(sel({})).toBeUndefined(); // an older server
    expect(sel(null)).toBeUndefined();
  });
});

describe("review fixes (game selection round 1)", () => {
  const CAT = catalogue();
  it("no-data words for a game Pitwall cannot read; none for one it reads", () => {
    expect(noDataText(entry("acc:ps5", CAT))).toBe("Pitwall can't read ACC on PS5");
    expect(noDataText(entry("f1_24:any", CAT))).toBe("Pitwall can't read F1 24");
    expect(noDataText(entry("other:any", CAT))).toBe("Pitwall can't read this game");
    expect(noDataText(entry("gt7:ps5", CAT))).toBeNull();
    expect(noDataText(null)).toBeNull();
  });

  it("idle inputs: on, receiving nothing, allowed off (never F1, never one receiving)", () => {
    const rows = [
      { key: "f1", name: "F1 25", enabled: true, in_use: false, can_disable: false },
      { key: "gt7", name: "GT7", enabled: true, in_use: false, can_disable: true },
      { key: "forza", name: "Forza", enabled: true, in_use: true, can_disable: false },
      { key: "ac", name: "AC", enabled: false, in_use: false, can_disable: true },
    ];
    expect(idleInputs(rows).map((r) => r.key)).toEqual(["gt7"]);
  });

  it("the More games disclosure names what is inside", () => {
    expect(moreGamesLabel(pickerCards(CAT).more)).toBe("More games: ACC, iRacing, F1 24");
    expect(moreGamesLabel([])).toBe("More games");
  });
});

describe("why the selected game is selected (integration plan 1.3, walk finding 13)", () => {
  const names = new Map([[2, "Sam"]]);
  it("a seat change: the driver whose usual game it is, by name", () => {
    expect(selectionReason({ source: "driver_default", by_driver_id: 2 }, GT7, names)).toBe("Selected because Sam usually plays GT7");
    // the server's name wins (it knows a driver this device has not loaded yet)
    expect(selectionReason({ source: "driver_default", by_driver_id: 3, by_driver_name: "Jo" }, GT7, names)).toBe(
      "Selected because Jo usually plays GT7",
    );
    expect(selectionReason({ source: "driver_default", by_driver_id: 2 }, GT7, (id) => (id === 2 ? "Sam" : null))).toBe(
      "Selected because Sam usually plays GT7",
    );
    // an older server (no driver id) or a driver since deleted: still honest, nobody named
    expect(selectionReason({ source: "driver_default" }, GT7, names)).toBe("Selected because the driver in the seat usually plays GT7");
    expect(selectionReason({ source: "driver_default", by_driver_id: 9 }, F1, names)).toBe(
      "Selected because the driver in the seat usually plays F1 25",
    );
  });

  it("the command line says so; a choice made on the dashboard needs no reason; unknown is null", () => {
    expect(selectionReason({ source: "cli" }, GT7)).toBe("Selected from the command line");
    expect(selectionReason({ source: "dashboard" }, GT7)).toBeNull();
    expect(selectionReason(null, GT7)).toBeNull();
    expect(selectionReason({ source: "driver_default", by_driver_id: 2 }, null, names)).toBeNull();
  });
});
