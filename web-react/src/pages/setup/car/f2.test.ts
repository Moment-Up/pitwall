// Setup › Car setup for an F2 session (F2 support, contract v1), rendered to static markup in plain node: the page never
// asks for a car format for an F2 car, names the car and the race as F2 calls them, says "No F2 setups for this track in
// Pitwall yet." where there are none (the setup cards still show), refuses an F1 override with a way back, and the
// handling suggestions say they are sized for the F2 car. Fixtures: the contract's F2 session answers
// (carsetup-f2-contract-edited.json) and the recorded catalogue with the contract's F2 format.
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { CarSetupError, type CarSetupCatalog, type SessionSetupQuery, type SessionSetupResponse } from "../../../lib/endpoints/carsetup";
import type { Route } from "../../../lib/route-parse";
import { fixtures as setupFixtures } from "../../../lib/setup/fixtures";
import { techniqueFixtures } from "../../../lib/technique/testkit";
import { stubBrowser } from "../../../test/fakes";
import type { HandlingBalanceCardProps } from "./HandlingBalanceCard";

let SessionSetupView: ComponentType<{ sid: string; route: Route; catalog: CarSetupCatalog }>;
let UnavailableCard: typeof import("./UnavailableCard").UnavailableCard;
let Card: ComponentType<HandlingBalanceCardProps>;
let cache: typeof import("../../../lib/cache").cache;
let carsetupKeys: typeof import("../../../lib/endpoints/carsetup").CARSETUP_KEYS;
let techniqueKeys: typeof import("../../../lib/endpoints/technique").techniqueKeys;

beforeAll(async () => {
  const { win } = stubBrowser("http://127.0.0.1:8770/#/setup/car/session/16b73e89c55b");
  Object.assign(win, {
    navigator: globalThis.navigator,
    removeEventListener: () => {},
    screen: { orientation: {} },
    visualViewport: {},
    matchMedia: () => ({ matches: true, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }),
  });
  SessionSetupView = (await import("./SessionSetupView")).SessionSetupView;
  UnavailableCard = (await import("./UnavailableCard")).UnavailableCard;
  Card = (await import("./HandlingBalanceCard")).HandlingBalanceCard;
  cache = (await import("../../../lib/cache")).cache;
  carsetupKeys = (await import("../../../lib/endpoints/carsetup")).CARSETUP_KEYS;
  techniqueKeys = (await import("../../../lib/endpoints/technique")).techniqueKeys;
  vi.unstubAllGlobals();
});

const CAT = setupFixtures.catalogWithF2();
const NO_QUERY: SessionSetupQuery = { car_format: null, session: null, conditions: null, style: null };

function visible(markup: string): string {
  return markup
    .replace(/<span class="sr-only">[^<]*<\/span>/g, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/\s+/g, " ")
    .trim();
}

function route(sid: string, query = ""): Route {
  return { area: "setup", page: "car", param: `session/${sid}`, path: `/setup/car/session/${sid}`, query };
}

function page(res: SessionSetupResponse, query = ""): string {
  const sid = res.session.id;
  cache.set(carsetupKeys.session(sid, NO_QUERY), res);
  cache.set(carsetupKeys.sessions, []);
  cache.set(carsetupKeys.experiments({ session_id: sid }), []);
  cache.set(techniqueKeys.balance(sid, res.chosen.car_format), techniqueFixtures.gt7Balance());
  return visible(renderToStaticMarkup(createElement(SessionSetupView, { sid, route: route(sid, query), catalog: CAT })));
}

describe("an F2 session's setup page", () => {
  it("Sakhir: the F2 car as the game reported it, no format question, the race as F2 calls it", () => {
    const text = page(setupFixtures.f2().sessions.sakhir);
    expect(text).toContain("Your setup vs recommended");
    expect(text).toMatch(/Car F2 car certain/);
    expect(text).toContain("Game car: F2 · Art GP '24");
    expect(text).toContain("Game: Feature race (Race 2)");
    expect(text).toContain("Sakhir (Bahrain) · Feature race");
    expect(text).not.toContain("Pitwall cannot tell");
    expect(text).not.toContain("Car format");
    expect(text).not.toMatch(/2025 car|2026 car/);
    expect(text).toContain("Experiments from this session");
    for (const bad of ["undefined", "null", "NaN", "Unknown team"]) expect(text).not.toContain(bad);
  });

  it("Silverstone: 'No F2 setups for this track in Pitwall yet.', no F1 setup offered, the cards still there", () => {
    const text = page(setupFixtures.f2().sessions.silverstone);
    expect(text).toContain("No recommendation yet");
    expect(text).toContain("No F2 setups for this track in Pitwall yet.");
    expect(text).not.toContain("Setups that exist for this track");
    expect(text).toContain("How the car handled");
    expect(text).toContain("Experiments from this session");
    expect(text).toContain("Silverstone · Sprint race");
  });

  it("a 2026 F2 car: no setups, said in words; the car still reads 'F2 car', never a raw id", () => {
    const text = page(setupFixtures.f2().sessions.f2_2026);
    expect(text).toContain("No setups for the 2026 F2 cars in Pitwall yet.");
    expect(text).toMatch(/Car F2 car/);
    expect(text).not.toContain("Unknown team (id 490)");
    expect(text).not.toContain("Pitwall cannot tell");
  });

  it("an F1 format forced on an F2 session (422): says so and offers the car the game reported", async () => {
    const res = setupFixtures.f2().sessions.sakhir;
    const q: SessionSetupQuery = { ...NO_QUERY, car_format: "f1_2025" };
    const key = carsetupKeys.session(res.session.id, q);
    const err = new CarSetupError(422, "f1_2025 is an F1 car format; this session's car is an F2 car");
    void cache.load(key, () => Promise.reject(err)).catch(() => {});
    await new Promise((r) => setTimeout(r, 0));
    const text = visible(renderToStaticMarkup(createElement(SessionSetupView, { sid: res.session.id, route: route(res.session.id, "format=f1_2025"), catalog: CAT })));
    expect(text).toContain("That car format does not fit this session's car");
    expect(text).toContain("f1_2025 is an F1 car format; this session's car is an F2 car");
    expect(text).toContain("Use the car the game reported");
  });
});

describe("the catalogue's 'no setup' card", () => {
  it("offers alternatives of the asked car's family only", () => {
    const alts = [...setupFixtures.sessionNeedsFormat().unavailable!.alternatives, ...setupFixtures.f2().available];
    const f2 = visible(
      renderToStaticMarkup(
        createElement(UnavailableCard, {
          reason: "No F2 setups for this track in Pitwall yet.",
          alts,
          catalog: CAT,
          current: { car_format: "f2", track_id: 7 },
          onPick: () => {},
        }),
      ),
    );
    expect(f2).toContain("No F2 setups for this track in Pitwall yet.");
    expect(f2).not.toMatch(/2025 car|2026 car/);
    const f1 = visible(
      renderToStaticMarkup(createElement(UnavailableCard, { reason: "x", alts, catalog: CAT, current: { car_format: "f1_2025", track_id: 13 }, onPick: () => {} })),
    );
    expect(f1).not.toContain("F2 car");
  });
});

describe("How the car handled, for the F2 car", () => {
  it("each change says it is sized for the F2 car; an F1 car the game reported needs no words", () => {
    const sid = "16b73e89c55b";
    const b = techniqueFixtures.suzukaBalance();
    const session = { ...setupFixtures.f2().sessions.sakhir.session };
    const render = (fmt: "f2" | "f1_2025") => {
      cache.set(techniqueKeys.balance(sid, fmt), { ...b, setup: { ...b.setup!, car_format: fmt } });
      return visible(
        renderToStaticMarkup(
          createElement(Card, { sid, carFormat: fmt, session, catalog: CAT, experiments: [], onTry: () => {} }),
        ),
      );
    };
    const f2 = render("f2");
    expect(f2).toContain("for the F2 car");
    expect(f2.match(/for the F2 car/g)?.length).toBeGreaterThan(1);
    expect(render("f1_2025")).not.toContain("for the F2 car");
    expect(render("f1_2025")).not.toContain("car you chose");
  });
});
