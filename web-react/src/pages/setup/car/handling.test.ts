// Setup › Car setup: "How the car handled" (feat/technique spec §4.3, §4.4, §9) and an experiment's balance change,
// rendered from the contract fixtures as static markup in plain node. Car symptoms carry one-parameter suggestions that
// prefill the existing experiment modal; driving symptoms never do; another game, no slip data and synthetic sessions
// say why; the catalogue caveat is verbatim; a server without the routes shows nothing.
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../../lib/api";
import type { SessionSetupResponse, SetupExperiment } from "../../../lib/endpoints/carsetup";
import type { TechniqueBalance } from "../../../lib/endpoints/technique";
import { fixtures as setupFixtures } from "../../../lib/setup/fixtures";
import { ADVICE_WORDS, techniqueFixtures } from "../../../lib/technique/testkit";
import { symptomViews } from "../../../lib/technique/view";
import type { Route } from "../../../lib/route-parse";
import { stubBrowser } from "../../../test/fakes";
import type { ExperimentCardProps } from "./ExperimentCard";
import type { HandlingBalanceCardProps } from "./HandlingBalanceCard";

let Card: ComponentType<HandlingBalanceCardProps>;
let ExperimentCard: ComponentType<ExperimentCardProps>;
let SessionSetupView: ComponentType<{ sid: string; route: Route; catalog: ReturnType<typeof setupFixtures.catalog> }>;
let mod: typeof import("./HandlingBalanceCard");
let cache: typeof import("../../../lib/cache").cache;
let keys: typeof import("../../../lib/endpoints/technique").techniqueKeys;
let carsetupKeys: typeof import("../../../lib/endpoints/carsetup").CARSETUP_KEYS;

beforeAll(async () => {
  const { win } = stubBrowser("http://127.0.0.1:8770/#/setup/car/session/df149ca2d149");
  Object.assign(win, {
    navigator: globalThis.navigator,
    removeEventListener: () => {},
    screen: { orientation: {} },
    visualViewport: {},
    matchMedia: () => ({ matches: true, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }),
  });
  mod = await import("./HandlingBalanceCard");
  Card = mod.HandlingBalanceCard;
  ExperimentCard = (await import("./ExperimentCard")).ExperimentCard;
  SessionSetupView = (await import("./SessionSetupView")).SessionSetupView;
  cache = (await import("../../../lib/cache")).cache;
  keys = (await import("../../../lib/endpoints/technique")).techniqueKeys;
  carsetupKeys = (await import("../../../lib/endpoints/carsetup")).CARSETUP_KEYS;
  vi.unstubAllGlobals();
});

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

function honest(text: string, what: string): void {
  for (const bad of ["NaN", "undefined", "null", "[object Object]"]) expect(text, `${what}: ${bad}`).not.toContain(bad);
  for (const re of ADVICE_WORDS) expect(text, `${what}: advice`).not.toMatch(re);
}

const SID = "df149ca2d149";
type SessionInfo = SessionSetupResponse["session"];

function session(over: Partial<SessionInfo> = {}): SessionInfo {
  return { ...setupFixtures.sessionDiff().session, ...over };
}

function render(balance: TechniqueBalance | Error, over: Partial<HandlingBalanceCardProps> = {}, sid = SID): string {
  const key = keys.balance(sid, over.carFormat); // the card asks for the page's car format (?car_format=)
  if (balance instanceof Error) {
    cache.invalidate(key);
    void cache.load(key, () => Promise.reject(balance)).catch(() => {});
  } else {
    cache.set(key, balance);
  }
  return renderToStaticMarkup(
    createElement(Card, {
      sid,
      session: session(),
      catalog: setupFixtures.catalog(),
      experiments: setupFixtures.experimentsEdited(),
      onTry: () => {},
      ...over,
    }),
  );
}

describe("How the car handled", () => {
  it("car symptoms with suggestions in menu units; already-tried and blocked ones say why; driving symptoms muted", () => {
    const html = render(techniqueFixtures.suzukaBalance());
    const text = visible(html);
    honest(text, "handling");
    for (const t of [
      "How the car handled",
      "Measured from tyre slip at the limit; the thresholds are Pitwall's heuristics.",
      "Mid-corner understeer",
      "medium speed",
      "3 of 3 laps, including your best",
      "Front Anti-Roll Bar 15 → 13",
      "Front Wing Aero 10 → 12",
      "Differential Adjustment On Throttle 90 % → 80 %",
      "Rear Anti-Roll Bar 10 → 8",
      "Already in your experiments from this session", // rear ARB is running from this session
      "Rear Suspension is already at its minimum (1) for the 2025 car.",
      "Setup to try (one change, then compare a session)",
      "Why",
      "Exit oversteer",
      "Not on your best lap: more about how the corner was driven",
      "Entry understeer · 2 of 3 laps, not on your best lap",
      "See it on the lap",
      "Rear Anti-Roll Bar is suggested lower for the exit oversteer only",
    ]) {
      expect(text, t).toContain(t);
    }
    expect(text).toContain(setupFixtures.catalog().caveat);
    expect(text.match(/Try this/g)).toHaveLength(3);
    expect(html).toContain('data-symptom="entry-understeer-driving"');
    // the driving symptom never carries a suggestion
    const driving = html.slice(html.indexOf('data-symptom="entry-understeer-driving"'));
    expect(driving).not.toContain("Try this");
  });

  it("a change listed twice names the first symptom with its corner labels as sent ('T2', not 't2')", () => {
    expect(mod.lowerFirst("Entry understeer at T3")).toBe("entry understeer at T3");
    expect(mod.lowerFirst("")).toBe("");
    const b = techniqueFixtures.suzukaBalance();
    const extra = { ...b.symptoms[0]!, id: "entry-understeer-car", phase: "entry" as const };
    const again = { ...b.setup!.suggestions[0]!, symptom_id: "entry-understeer-car" };
    const text = visible(render({ ...b, symptoms: [b.symptoms[0]!, extra], setup: { ...b.setup!, suggestions: [...b.setup!.suggestions, again] } }));
    expect(text).toMatch(/also listed above for mid-corner understeer at T2/);
    expect(text).not.toMatch(/at t\d/);
  });

  it("Try this prefills the existing modal with the parameter, the new value and the hypothesis", () => {
    const b = techniqueFixtures.suzukaBalance();
    const v = symptomViews(b.symptoms, b.setup, { experiments: setupFixtures.experimentsEdited(), sid: SID });
    const arb = v.car[0]!.suggestions[0]!;
    const initial = mod.tryInitial(arb)!;
    expect(initial).toMatchObject({ key: "front_arb", to: 13 });
    expect(initial.hypothesis).toMatch(/^Front Anti-Roll Bar 15 -> 13: The car pushed wide in the middle of T2 and T7/);
    expect(initial.hypothesis!.length).toBeLessThanOrEqual(500);
    expect(mod.tryInitial(v.car[1]!.suggestions.find((x) => x.parameter === "rear_arb")!)).toBeNull();
    expect(mod.tryInitial({ parameter: "x", to_value: null, hypothesis: "" })).toBeNull();
  });

  it("the server could not tell the car format: the page's choice sizes the change, and says so", () => {
    const b = techniqueFixtures.suzukaBalance();
    const unknown: TechniqueBalance = {
      ...b,
      setup: {
        ...b.setup!,
        car_format: null,
        suggestions: b.setup!.suggestions.map((x) => ({
          ...x,
          to_value: null,
          blocked: "The car format is unknown (2025 or 2026 car): choose it in Setup › Car setup.",
        })),
      },
    };
    const before = visible(render(unknown));
    expect(before).toContain("The car format is unknown (2025 or 2026 car)");
    expect(before).not.toContain("Try this");
    const after = visible(render(unknown, { carFormat: "f1_2025" }));
    expect(after).toContain("Front Anti-Roll Bar 15 → 13");
    expect(after).toContain("for the 2025 car you chose");
    expect(after).toContain("Try this");
  });

  it("the experiment modal reads 'yours' from the stored setup's {value} objects (as the API sends them)", async () => {
    const { setupValue } = await import("../../../lib/setup/carsetup");
    const params = setupFixtures.sessionDiff().setup!.params;
    expect(setupValue(params, "front_arb")).toBe(15);
    expect(setupValue({ rear_wing: 18 }, "rear_wing")).toBe(18);
    expect(setupValue({ x: { value: "a" } }, "x")).toBeNull();
  });

  it("beginner: the simple sentences", () => {
    const text = visible(render(techniqueFixtures.suzukaBalance(), { session: session({ driver: { id: 2, name: "Alex", skill_level: "beginner" } }) }));
    expect(text).toContain("The car pushed wide in the middle of T2 and T7 on 3 of 3 laps, even on your best lap.");
    expect(text).not.toContain("heuristic threshold 3°");
  });

  it("another game: the reason and 'for F1 25 only', nothing to try", () => {
    const text = visible(render(techniqueFixtures.gt7Balance(), { session: session({ game: "gt7" }) }, "4e0c2a1b7f30"));
    honest(text, "gt7");
    expect(text).toContain("This game does not send tyre slip to Pitwall yet");
    expect(text).toContain(mod.NOT_F1_TEXT);
    expect(text).not.toContain("Try this");
  });

  it("an F1 session recorded before slip data: says so", () => {
    const text = visible(render(techniqueFixtures.oldF1Balance()));
    expect(text).toContain(mod.NO_SLIP_TEXT);
    expect(text).not.toContain(mod.NOT_F1_TEXT);
    expect(text).not.toContain("Try this");
  });

  it("synthetic sessions: labelled, shown, never offered as experiments", () => {
    const text = visible(render(techniqueFixtures.suzukaBalance(), { session: session({ synthetic: true }) }));
    expect(text).toContain("SYNTHETIC");
    expect(text).toContain("Generated data: these symptoms were put there by the simulator");
    expect(text).toContain("Front Anti-Roll Bar 15 → 13");
    expect(text).not.toContain("Try this");
  });

  it("nothing recurring: no suggestion, and why", () => {
    const b = techniqueFixtures.suzukaBalance();
    const text = visible(render({ ...b, symptoms: [], setup: { ...b.setup!, suggestions: [], note: null } }));
    expect(text).toContain("No handling problem showed on most laps and on your best lap");
    expect(text).not.toContain("Try this");
  });

  it("a server without the routes shows nothing; no track model yet says so", async () => {
    render(new ApiError(404, "Not Found"), {}, "old-server");
    await new Promise((r) => setTimeout(r, 0));
    expect(render(new ApiError(404, "Not Found"), {}, "old-server")).toBe("");
    render(new ApiError(409, "no track model yet for this track (complete a clean lap first)"), {}, "no-model");
    await new Promise((r) => setTimeout(r, 0));
    expect(visible(render(new ApiError(409, "no track model yet for this track (complete a clean lap first)"), {}, "no-model"))).toContain(
      "No track model yet for this track",
    );
  });
});

describe("Experiments: how the handling changed", () => {
  function concluded(): SetupExperiment {
    return setupFixtures.experimentsEdited().find((e) => e.status === "concluded")!;
  }

  it("the backend's sentences under the verdict", () => {
    const e = concluded();
    (e.after_metrics!.comparison as unknown as Record<string, unknown>).balance = techniqueFixtures.experimentBalance();
    const text = visible(renderToStaticMarkup(createElement(ExperimentCard, { exp: e, param: undefined, sessions: [] })));
    expect(text).toContain("How the handling changed");
    expect(text).toContain("T2 mid-corner: understeer on 3 of 3 laps before, 1 of 4 after");
    expect(text).toContain("Balance is measured with heuristic thresholds; one session each side is a small sample.");
  });

  it("an older server (no balance) changes nothing", () => {
    const text = visible(renderToStaticMarkup(createElement(ExperimentCard, { exp: concluded(), param: undefined, sessions: [] })));
    expect(text).not.toContain("How the handling changed");
  });
});

describe("the session view places the card before the experiments", () => {
  it("How the car handled, then Experiments from this session", () => {
    const catalog = setupFixtures.catalog();
    cache.set(carsetupKeys.session(SID, { car_format: null, session: null, conditions: null, style: null }), setupFixtures.sessionDiff());
    cache.set(carsetupKeys.sessions, []);
    cache.set(carsetupKeys.experiments({ session_id: SID }), setupFixtures.experimentsEdited());
    // the page asks for its chosen car format (the fixture's chosen car_format is f1_2025)
    cache.set(keys.balance(SID, "f1_2025"), techniqueFixtures.suzukaBalance());
    const route: Route = { area: "setup", page: "car", param: `session/${SID}`, path: `/setup/car/session/${SID}`, query: "" };
    const text = visible(renderToStaticMarkup(createElement(SessionSetupView, { sid: SID, route, catalog })));
    const a = text.indexOf("How the car handled");
    const b = text.indexOf("Experiments from this session");
    expect(a).toBeGreaterThan(-1);
    expect(b).toBeGreaterThan(a);
    expect(text.slice(a, b)).toContain("Setup to try (one change, then compare a session)");
  });
});
