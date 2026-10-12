// Setup › Game and Drive's game picker rendered to static markup in plain node (no DOM library) from the
// catalogue fixture (tier "edited", the backend contract): the picker shows every main game with the server's support words,
// nothing stronger; the selected card is marked; the feature list says what the game sends in the server's words;
// a game Pitwall cannot read says so; Drive's picker asks "What are you playing?" with 64 px game buttons; the Coach
// sector slot and delta header change only for known facts.

import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, describe, expect, it, vi } from "vitest";
import type { GameEntry, GamesResponse, GameState } from "../../../lib/endpoints/game";
import { catalogue, entry, gameState, putResponse } from "../../../lib/game-testkit";
import { stubBrowser } from "../../../test/fakes";
import type { GamePickerProps } from "./GamePicker";
import type { InputCardProps } from "./InputCard";

function stubDom(): void {
  const { win } = stubBrowser("http://127.0.0.1:8770/next/#/setup/game");
  Object.assign(win, {
    navigator: globalThis.navigator,
    removeEventListener: () => {},
    screen: { orientation: {} },
    visualViewport: {},
    matchMedia: () => ({ matches: true, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }),
  });
}

let GamePicker: ComponentType<GamePickerProps>;
let FeaturesCard: ComponentType<{ entry: GameEntry; catalogue: GamesResponse; wide: boolean }>;
let InputCard: ComponentType<InputCardProps>;
let UnreadableCard: ComponentType<{ entry: GameEntry; recordOn: boolean | null }>;
let GamePickerCard: ComponentType<{ catalogue: GamesResponse; onNotNow: () => void }>;
let SectorCells: ComponentType<{ sectors: import("../../../lib/drive/timing").SectorCellsView; unavailable?: string | null }>;
let inputWords: typeof import("./InputCard").inputWords;
let NoTelemetryCard: ComponentType<{ entry?: GameEntry | null }>;

beforeAll(async () => {
  stubDom();
  GamePicker = (await import("./GamePicker")).GamePicker;
  FeaturesCard = (await import("./FeaturesCard")).FeaturesCard;
  const input = await import("./InputCard");
  InputCard = input.InputCard;
  UnreadableCard = input.UnreadableCard;
  inputWords = input.inputWords;
  GamePickerCard = (await import("../../drive/coach/GamePickerCard")).GamePickerCard;
  SectorCells = (await import("../../drive/coach/TimingPanels")).SectorCells as typeof SectorCells;
  NoTelemetryCard = (await import("../../drive/coach/NoTelemetryCard")).NoTelemetryCard;
  vi.unstubAllGlobals();
});

const CAT = catalogue();
const noop = () => {};

function text(html: string): string {
  return html
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ")
    .trim();
}

function clean(html: string): void {
  for (const bad of ["undefined", "null", "NaN", "—", "[object Object]"]) expect(text(html)).not.toContain(bad);
}

describe("Setup › Game picker", () => {
  it("every main game with its platforms and the server's support words; More games collapsed", () => {
    const html = renderToStaticMarkup(
      createElement(GamePicker, { catalogue: CAT, selectedId: null, pending: null, onChoose: noop, result: null, error: null }),
    );
    clean(html);
    const t = text(html);
    expect(t).toContain("What are you playing?");
    for (const title of ["F1 25", "Gran Turismo 7", "Assetto Corsa", "Forza Motorsport (2023)", "Forza Horizon 4 / 5", "Another game"]) {
      expect(t).toContain(title);
    }
    expect(t).toContain("Tested live");
    expect(t).toContain("Tested on a recording");
    expect(t).toContain("Records packets only");
    expect(t).toContain("2026 Season Pack cars (UDP format 2026)");
    expect(t).toContain("More games: ACC, iRacing, F1 24"); // an ACC player sees where ACC is
    expect(t).not.toContain("Selected");
    // the strongest claim on screen is the server's: nothing reads "works" or "supported" for a docs-only game
    expect(t).not.toMatch(/\bworks\b/i);
  });

  it("marks the selected card and platform, and lists what the PUT did in the server's words", () => {
    const res = putResponse();
    const html = renderToStaticMarkup(
      createElement(GamePicker, {
        catalogue: CAT,
        selectedId: "gt7:ps5",
        pending: null,
        onChoose: noop,
        result: { id: "gt7:ps5", actions: res.actions },
        error: null,
      }),
    );
    const t = text(html);
    expect(t).toContain("Selected");
    expect(html).toContain('aria-label="Gran Turismo 7 on PS5: Built from community docs (selected)"');
    expect(t).toContain("Enter the PS5's IP address to switch the GT7 input on.");
    expect(html).toContain('id="pw-game-result"'); // scrolled into view after a choice
  });

  it("the selected card says why when a seat change chose it (integration plan 1.3); nothing on other cards", () => {
    const render = (reason: string | null) =>
      renderToStaticMarkup(
        createElement(GamePicker, { catalogue: CAT, selectedId: "gt7:ps5", pending: null, onChoose: noop, result: null, error: null, reason }),
      );
    const html = render("Selected because Sam usually plays GT7");
    expect(text(html)).toContain("Selected because Sam usually plays GT7. Choose another platform or game to change it.");
    expect(html.split("data-game-reason").length - 1).toBe(1);
    expect(render(null)).not.toContain("data-game-reason");
  });

  it("after a choice, an idle input left on by an earlier choice is offered for switching off", () => {
    const res = putResponse();
    const t = text(
      renderToStaticMarkup(
        createElement(GamePicker, {
          catalogue: CAT,
          selectedId: "gt7:ps5",
          pending: null,
          onChoose: noop,
          result: { id: "gt7:ps5", actions: res.actions },
          error: null,
          otherInputs: [
            { key: "f1", name: "EA SPORTS F1 25", enabled: true, in_use: false, can_disable: false },
            { key: "forza", name: "Forza", enabled: true, in_use: false, can_disable: true },
            { key: "ac", name: "Assetto Corsa", enabled: true, in_use: true, can_disable: false },
          ],
        }),
      ),
    );
    expect(t).toContain("The Forza input is still on (nothing is arriving). Turn off");
    expect(t).not.toContain("The EA SPORTS F1 25 input is still on");
    expect(t).not.toContain("The Assetto Corsa input is still on");
  });
});

describe("What the game sends", () => {
  it("GT7: grouped, the server's reasons, its support note; no green 'Supported' for docs-only evidence", () => {
    const gt7 = entry("gt7:ps5", CAT);
    const html = renderToStaticMarkup(createElement(FeaturesCard, { entry: gt7, catalogue: CAT, wide: true }));
    clean(html);
    const t = text(html);
    expect(t).toContain("What Gran Turismo 7 sends");
    expect(t).toContain(gt7.support.summary!); // one plain sentence under the title ...
    expect(t).toContain("How this was tested"); // ... the technical note behind a disclosure
    expect(t).toContain("A green Supported was checked with the real game or a recording");
    expect(t).toContain("7 available · 20 not available"); // race radio: GT7 race position; health lane: engine temperature; spotter
    for (const g of ["Timing", "Coaching", "Track", "Car & tyres", "Session & race", "Setup & radio"]) expect(t).toContain(g);
    expect(t).toContain("GT7 doesn't send tyre wear.");
    expect(t).toContain("Not in Pitwall yet");
    expect(t).toContain("Estimated");
    expect(t).toContain("Telemetry fields");
    // chips for supported features of a community-documented game are neutral, never the success colour
    expect(html).not.toMatch(/chip--success[^>]*>[^<]*<[^>]*>Supported/);
  });

  it("F1 25 on PS5: the recorded AI-field evidence is the green one", () => {
    const html = renderToStaticMarkup(createElement(FeaturesCard, { entry: entry("f1_25:ps5", CAT), catalogue: CAT, wide: true }));
    expect(html).toMatch(/chip--success[^>]*>[^<]*<[^>]*>Supported/);
    expect(text(html)).toContain("F1 25 sends car damage, but Pitwall reads only tyre wear from it so far.");
  });

  it("the wheel push-to-talk row links to Setup › Controls (Map your buttons)", () => {
    for (const id of ["f1_25:ps5", "gt7:ps5"]) {
      const html = renderToStaticMarkup(createElement(FeaturesCard, { entry: entry(id, CAT), catalogue: CAT, wide: true }));
      expect(html, id).toMatch(/<a[^>]*href="#\/setup\/controls"[^>]*>Map your buttons<\/a>/);
      expect(html.match(/Map your buttons/g)?.length, id).toBe(1);
    }
  });

  it("another game: every feature unknown, nothing claimed", () => {
    const html = renderToStaticMarkup(createElement(FeaturesCard, { entry: entry("other:any", CAT), catalogue: CAT, wide: false }));
    const t = text(html);
    expect(t).toContain("What this game sends");
    expect(t).toContain("0 available · 0 not available · 27 unknown");
    expect(t).not.toContain("Not sent");
    expect(t).toContain("Pitwall doesn't know what this game sends.");
    expect(t).toContain("All 27 features"); // 27 identical rows behind one disclosure
  });

  it("ACC on PS5: one sentence, the rows behind a disclosure, and Not sent is never red", () => {
    const html = renderToStaticMarkup(createElement(FeaturesCard, { entry: entry("acc:ps5", CAT), catalogue: CAT, wide: true }));
    const t = text(html);
    expect(t).toContain("ACC on PS5 has no telemetry output.");
    expect(t).toContain("All 27 features");
    expect(t).not.toContain("Telemetry fields");
    expect(html).not.toMatch(/chip--danger[^>]*>[^<]*<[^>]*>Not sent/);
  });
});

describe("the input card", () => {
  it("GT7 without an IP: the input stays off until the IP, or an explicit network search", () => {
    const st: GameState = gameState("gt7");
    const html = renderToStaticMarkup(
      createElement(InputCard, { entry: entry("gt7:ps5", CAT), state: st, onConsoleIp: async () => null }),
    );
    clean(html);
    const t = text(html);
    expect(t).toContain("Off");
    expect(t).toContain("Console IP");
    expect(html).toContain('id="pw-game-console-ip"');
    expect(t).toContain("Enter it to switch the GT7 input on");
    expect(t).toContain("Search the network");
    expect(t).toContain("Open Setup › Connect");
    expect(t).toContain("always on");
    expect(t).not.toContain("Turn off");
    const on = { ...st, input: { ...st.input!, enabled: true, listening: true } };
    const t2 = text(renderToStaticMarkup(createElement(InputCard, { entry: entry("gt7:ps5", CAT), state: on, onConsoleIp: async () => null })));
    expect(t2).toContain("On · listening on UDP 33740");
    expect(t2).toContain("Optional: without it Pitwall searches the network for the console.");
    expect(t2).not.toContain("Search the network for");
  });

  it("Assetto Corsa: the console IP is required; another enabled input may be turned off (after a confirm)", () => {
    const html = renderToStaticMarkup(
      createElement(InputCard, { entry: entry("ac:ps5", CAT), state: gameState("ac"), onConsoleIp: async () => null }),
    );
    const t = text(html);
    expect(t).toContain("On · needs the console IP");
    expect(t).toContain("Required: Pitwall must contact the console");
    expect(t).toContain("Turn off");
  });

  it("an input receiving packets is never offered to turn off", () => {
    const t = text(renderToStaticMarkup(createElement(InputCard, { entry: entry("gt7:ps5", CAT), state: gameState("mismatch"), onConsoleIp: async () => null })));
    expect(t).toContain("receiving");
    expect(t).not.toContain("Turn off");
  });

  it("input words never say receiving without packets", () => {
    const gt7 = entry("gt7:ps5", CAT);
    const input = { ...gameState("gt7").input!, enabled: true, listening: true };
    expect(inputWords(input, gt7).text).toBe("On · listening on UDP 33740");
    expect(inputWords({ ...input, in_use: true }, gt7)).toEqual({ text: "Receiving", tone: "success" });
    expect(inputWords({ ...input, enabled: false }, gt7).text).toBe("Off");
    expect(inputWords({ ...input, error: "port in use" }, gt7).text).toBe("Problem");
  });

  it("a game Pitwall cannot read says why in the server's words; another game can record its packets", () => {
    const acc = text(renderToStaticMarkup(createElement(UnreadableCard, { entry: entry("acc:ps5", CAT), recordOn: null })));
    expect(acc).toContain("Pitwall can't read Assetto Corsa Competizione telemetry");
    expect(acc).toContain("ACC on PS5 has no telemetry output.");
    expect(acc).not.toContain("Record its packets");
    const other = text(renderToStaticMarkup(createElement(UnreadableCard, { entry: entry("other:any", CAT), recordOn: false })));
    expect(other).toContain("Pitwall can't read this game's telemetry");
    expect(other).toContain("Record its packets");
  });
});

describe("Drive › Coach", () => {
  it("the picker asks once, with the main games as glove buttons and Not now", () => {
    const html = renderToStaticMarkup(createElement(GamePickerCard, { catalogue: CAT, onNotNow: noop }));
    clean(html);
    const t = text(html);
    expect(t).toContain("What are you playing?");
    for (const title of ["F1 25", "Gran Turismo 7", "Assetto Corsa", "Forza Motorsport (2023)", "Forza Horizon 4 / 5", "Another game"]) {
      expect(t).toContain(title);
    }
    expect(t).toContain("Not now");
    expect(t).toContain("My game isn't listed"); // the way to ACC, iRacing and F1 24 (Setup › Game)
    expect(t).not.toContain("Assetto Corsa Competizione"); // More games live on Setup › Game
    expect(html.match(/pwc-pick__btn/g)?.length).toBe(6);
  });

  it("Assetto Corsa with no console IP: the card leads with the IP, not with waiting", () => {
    const t = text(renderToStaticMarkup(createElement(NoTelemetryCard, { entry: entry("ac:ps5", CAT) })));
    expect(t).toContain("Assetto Corsa needs the console's IP address");
    expect(t).toContain("Enter console IP");
    expect(t).toContain("Enter the console's IP address");
    expect(t).toContain("Change game");
    expect(t).not.toContain("Waiting for Assetto Corsa telemetry");
    const f1 = text(renderToStaticMarkup(createElement(NoTelemetryCard, { entry: entry("f1_25:ps5", CAT) })));
    expect(f1).toContain("Waiting for F1 25 telemetry");
    expect(f1).toContain("Open Setup › Connect");
    expect(f1).toContain("Change game");
  });

  it("a game without sector times: one muted cell across the slot instead of three dashes", () => {
    const sectors = {
      caption: null,
      source: "none" as const,
      dim: false,
      cells: (["S1", "S2", "S3"] as const).map((label) => ({ label, text: "-", status: "neutral" as const, tag: null, sub: null, progress: null })) as never,
    };
    const none = renderToStaticMarkup(createElement(SectorCells, { sectors, unavailable: "Sectors · Not sent by GT7" }));
    expect(text(none)).toBe("Sectors · Not sent by GT7");
    expect(none).toContain("pwc-sect");
    const three = renderToStaticMarkup(createElement(SectorCells, { sectors }));
    expect(text(three)).toContain("S1");
    expect(text(three)).toContain("S3");
  });
});
