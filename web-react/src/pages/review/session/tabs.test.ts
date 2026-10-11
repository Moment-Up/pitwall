// Session tabs rendered from recorded fixtures (static markup in plain node, no DOM library): Laps, Compare, Corners
// and Ask show what the API sent and nothing else; unknown is "-"; purple and PB never appear before D2; density
// follows the viewed session's driver (6.10). Data is put in the request cache first, so nothing is fetched.
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, describe, expect, it, vi } from "vitest";
import type { Driver } from "../../../lib/drivers";
import type { SessionAnalysis, SessionDetail } from "../../../lib/endpoints/review";
import { densityFor, type Density } from "../../../lib/review/density";
import { driver, fixtures } from "../../../lib/review/testkit";
import { stubBrowser } from "../../../test/fakes";
import type { AskPanelProps } from "../ask/AskPanel";
import type { CompareTabProps } from "./CompareTab";
import type { CornersTabProps } from "./CornersTab";
import type { LapsTabProps } from "./LapsTab";

function stubDom(): void {
  const { win } = stubBrowser("http://127.0.0.1:8770/next/#/review/sessions/332904dbe3de/compare");
  Object.assign(win, {
    navigator: globalThis.navigator,
    removeEventListener: () => {},
    screen: { orientation: {} },
    visualViewport: {},
    matchMedia: () => ({ matches: true, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }),
  });
}

let LapsTab: ComponentType<LapsTabProps>;
let CompareTab: ComponentType<CompareTabProps>;
let CornersTab: ComponentType<CornersTabProps>;
let AskPanel: ComponentType<AskPanelProps>;
let cache: typeof import("../../../lib/cache").cache;
let keys: typeof import("../../../lib/endpoints/review").reviewKeys;
let drivers: typeof import("../../../lib/drivers").drivers;

beforeAll(async () => {
  stubDom();
  LapsTab = (await import("./LapsTab")).LapsTab;
  CompareTab = (await import("./CompareTab")).CompareTab;
  CornersTab = (await import("./CornersTab")).CornersTab;
  AskPanel = (await import("../ask/AskPanel")).AskPanel;
  cache = (await import("../../../lib/cache")).cache;
  keys = (await import("../../../lib/endpoints/review")).reviewKeys;
  drivers = (await import("../../../lib/drivers")).drivers;
  vi.unstubAllGlobals();
});

/** Text a sighted user sees: tags stripped, visually hidden spans removed, entities decoded. */
function visible(markup: string): string {
  return markup
    .replace(/<span class="sr-only">[^<]*<\/span>/g, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/\s+/g, " ")
    .trim();
}

function honest(text: string, what: string): void {
  for (const bad of ["0:00.000", "--:--", "—", "NaN", "undefined", "null", "Infinity", "[object Object]"]) {
    expect(text, `${what}: ${bad}`).not.toContain(bad);
  }
}

function setDrivers(list: Driver[]): void {
  (drivers as unknown as { set(p: object): void }).set({ drivers: list, activeId: list[0]?.id ?? null, loaded: true });
}

const austria = (): SessionDetail => fixtures.austria();
const analysis = (): SessionAnalysis => fixtures.austriaAnalysis();

function densityOf(s: SessionDetail, list: Driver[]): Density {
  return densityFor(s.driver_id, list);
}

describe("Laps (6.4)", () => {
  it("every lap with time, sectors and gap; colours by current standing; never purple or PB", () => {
    const html = renderToStaticMarkup(createElement(LapsTab, { session: austria(), analysis: analysis(), refQuery: null }));
    const text = visible(html);
    honest(text, "laps");
    expect(text).toContain("Gaps are measured against lap 64 (the session's reference).");
    for (const t of ["1:10.549", "1:11.000", "1:10.889", "flashback", "+0.451", "Set as reference", "Compare"]) expect(text).toContain(t);
    expect(html).toContain('data-status="sb"');
    expect(html).toContain('data-status="invalid"');
    expect(html).not.toContain('data-status="rec"');
    expect(html).not.toContain('data-status="pb"');
    // Pin is only offered for another reference chosen on this page
    expect(text).not.toContain("Pin lap");
  });

  it("a reference chosen on the page offers the way back and Pin (inline, nothing saved yet)", () => {
    const s = austria();
    cache.set(keys.analysisRef(s.id, 54), { ...analysis(), ref_lap_id: 54 });
    const text = visible(renderToStaticMarkup(createElement(LapsTab, { session: s, analysis: analysis(), refQuery: 54 })));
    expect(text).toContain("Gaps are measured against lap 66 (on this page only).");
    expect(text).toContain("Back to the session's reference");
    expect(text).toContain("Pin lap 66 as reference");
  });

  it("synthetic sessions: no timing colours (the Drive rule), labelled", () => {
    const demo = fixtures.demo();
    const html = renderToStaticMarkup(createElement(LapsTab, { session: demo, analysis: fixtures.demoAnalysis(), refQuery: null }));
    for (const st of ["sb", "slower", "pb", "rec"]) expect(html).not.toContain(`data-status="${st}"`);
    expect(visible(html)).toContain("Synthetic data: times are not coloured");
  });
});

describe("Compare (6.5)", () => {
  function seed(): void {
    cache.set(keys.trace(52), fixtures.trace52());
    cache.set(keys.trace(54), fixtures.trace54());
    cache.set(keys.compare(52, 54), fixtures.compare());
    cache.set(keys.compare(53, 54), fixtures.compareBlocked());
  }

  it("advanced: pickers, words for the total, every chart, the explainer and the full corner table", () => {
    seed();
    const s = austria();
    const james = fixtures.drivers().drivers.find((d) => d.id === s.driver_id)!;
    setDrivers([james]);
    const html = renderToStaticMarkup(
      createElement(CompareTab, { session: s, analysis: analysis(), density: densityOf(s, [james]), query: new URLSearchParams("ref=52&lap=54&at=3783") }),
    );
    const text = visible(html);
    honest(text, "compare");
    expect(text).toContain("A · Reference");
    expect(text).toContain("B · Your lap");
    expect(text).toContain("Same car, track and conditions");
    expect(text).toMatch(/Your lap was 0\.45 s slower than the reference\./);
    for (const t of ["Time gained or lost: your lap against the reference", "Speed", "Throttle and brake", "Steering"]) expect(text).toContain(t);
    // advanced: captions hidden, signed times, all corner columns
    expect(text).not.toContain("The line goes up where your lap lost time");
    for (const t of ["Time lost here", "Braked", "Slowest speed", "Exit speed", "Full throttle"]) expect(text).toContain(t);
    // the explainer follows `at` (3783 m = T9 Rindt Kurve)
    expect(text).toContain("At Rindt Kurve you");
    expect(text).toContain("A description of the two laps, not advice.");
    expect(text).not.toMatch(/\bB vs A\b/);
  });

  it("beginner: 'Your target lap', delta and speed only, pedals behind Show pedals, captions, words not signs", () => {
    seed();
    const s = { ...austria(), driver_id: 2 };
    const alex = driver(2, "Alex", "beginner");
    setDrivers([alex]);
    const d = densityOf(s, [alex]);
    expect(d.level).toBe("beginner");
    const text = visible(
      renderToStaticMarkup(createElement(CompareTab, { session: s, analysis: analysis(), density: d, query: new URLSearchParams("ref=52&lap=54") })),
    );
    honest(text, "compare beginner");
    expect(text).toContain("A · Your target lap");
    expect(text).toContain("Time gained or lost: your lap against your target lap");
    expect(text).toContain("The line goes up where your lap lost time");
    expect(text).toContain("Show pedals");
    expect(text).not.toContain("Steering");
    expect(text).toContain("What was different");
    expect(text).not.toContain("Exit speed");
    expect(text).toMatch(/\d\.\d\d s (lost|gained)/);
  });

  it("a blocked comparison shows its reason instead of the charts", () => {
    seed();
    const s = austria();
    const text = visible(
      renderToStaticMarkup(
        createElement(CompareTab, { session: s, analysis: analysis(), density: densityOf(s, []), query: new URLSearchParams("ref=53&lap=54") }),
      ),
    );
    expect(text).toContain("Not comparable");
    expect(text).toContain("reference lap is not clean");
    expect(text).not.toContain("Time gained or lost");
  });

  it("the same lap twice asks for another", () => {
    const s = austria();
    const text = visible(
      renderToStaticMarkup(
        createElement(CompareTab, { session: s, analysis: analysis(), density: densityOf(s, []), query: new URLSearchParams("ref=54&lap=54") }),
      ),
    );
    expect(text).toContain("A and B are the same lap");
  });
});

describe("Corners (6.6)", () => {
  it("one card per corner with averages in words and the coach's texts; incidents marked", () => {
    const s = austria();
    const a = analysis();
    const text = visible(renderToStaticMarkup(createElement(CornersTab, { session: s, analysis: a, density: densityOf(s, []) })));
    honest(text, "corners");
    expect(text).toContain("Work on");
    expect(text).toContain("Went well");
    expect(text).toContain("See it on the lap");
    expect(text).toMatch(/Braked about \d+ m (earlier|later) on average/);
    expect(text).toContain("The coach spoke here on laps");
    expect(text).toContain("Why some laps are greyed");
  });

  it("no reference yet: says why there is nothing", () => {
    const s = austria();
    const text = visible(
      renderToStaticMarkup(createElement(CornersTab, { session: s, analysis: { ...analysis(), ref_lap_id: null }, density: densityOf(s, []) })),
    );
    expect(text).toContain("No corner averages yet");
  });
});

describe("Ask (6.7)", () => {
  it("the stored conversation with its source chip and facts; the grounding line is always there", () => {
    cache.set(keys.history("a100cbc9b5bd"), fixtures.history());
    const html = renderToStaticMarkup(createElement(AskPanel, { sessionId: "a100cbc9b5bd", initialQuestion: "Why am I losing time at Stowe (T15)?" }));
    const text = visible(html);
    honest(text, "ask");
    expect(text).toContain("Give me one thing to work on.");
    expect(text).toContain("Focus on Turn 6.");
    expect(html).toContain(">F32</sup>");
    expect(text).toContain("LLM · grounded");
    expect(text).toContain("Grounded on 1 fact");
    expect(text).toContain("Answers are grounded on the session's facts, or replaced by a deterministic answer.");
    for (const q of ["Where am I losing the most time?", "What went well?"]) expect(text).toContain(q);
    // ?q= pre-fills, it is not sent
    expect(html).toContain("Why am I losing time at Stowe (T15)?");
    expect(text).not.toContain("The engineer is thinking");
  });

  it("an empty conversation invites a question", () => {
    cache.set(keys.history("empty"), []);
    const text = visible(renderToStaticMarkup(createElement(AskPanel, { sessionId: "empty" })));
    expect(text).toContain("Ask your race engineer about this session.");
  });
});

describe("fixtures say where they came from", () => {
  it("every review fixture has a provenance block; edited ones say what changed", async () => {
    const { fixtureBlocks } = await import("../../../lib/review/testkit");
    for (const { name, block } of fixtureBlocks()) {
      expect(block.source, name).toMatch(/live pitwall service|synthetic|SYNTHETIC|simulat/i);
      expect(["recorded", "synthetic"], name).toContain(block.tier);
      if (name.startsWith("synthetic-")) expect(block.tier, name).toBe("synthetic");
    }
    expect(fixtureBlocks().filter((f) => f.name.includes("trace")).every((f) => typeof f.block.edited === "string")).toBe(true);
  });
});
