// Setup › Rig rendered from recorded answers of the live API (server-rendered to static markup in plain node, no DOM
// library): every walkthrough step of every recorded plan renders its card without inventing anything (no
// "undefined", "null", "NaN" or em dash; unknown is "-"), wheel rows carry the wheel display's code and in-game rows
// never show an API id, unverified research steps are flagged, the last step links to the rig check; and the All
// settings, Rig check and Upgrades parts render the recorded data verbatim.

import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, describe, expect, it, vi } from "vitest";
import type { Hardware, Recommendation, RigProfile } from "../../../lib/endpoints/rig";
import { fixtures } from "../../../lib/setup/fixtures";
import { WALKTHROUGH, buildPlan, relevantMistakes, tick, type WalkItem, type WalkPlan } from "../../../lib/setup/walkthrough";
import { stubBrowser } from "../../../test/fakes";
import type { StepCardProps } from "./StepCard";

function stubDom(): void {
  const { win } = stubBrowser("http://127.0.0.1:8770/next/#/setup/rig");
  Object.assign(win, {
    navigator: globalThis.navigator,
    removeEventListener: () => {},
    screen: { orientation: {} },
    visualViewport: {},
    matchMedia: () => ({ matches: true, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }),
  });
}

let StepCard: ComponentType<StepCardProps>;
let RecommendationCards: ComponentType<{ rec: Recommendation; catalog: ReturnType<typeof fixtures.rigCatalog>; onRow: () => void }>;
let SummaryCard: ComponentType<{ rec: Recommendation }>;
let UpgradesView: ComponentType<{ profile: RigProfile; rec: Recommendation | undefined }>;
let TipList: ComponentType<{ tips: ReturnType<typeof relevantMistakes> }>;

beforeAll(async () => {
  stubDom();
  StepCard = (await import("./StepCard")).StepCard;
  const cards = await import("./RecommendationCards");
  RecommendationCards = cards.RecommendationCards as typeof RecommendationCards;
  SummaryCard = cards.SummaryCard;
  UpgradesView = (await import("./UpgradesView")).UpgradesView;
  TipList = (await import("./TroubleSheet")).TipList;
  vi.unstubAllGlobals();
});

const PS5: Hardware = { platform: "ps5", wheel_base: "fanatec_gt_dd_pro", torque_nm: 5, pedals: "csl", rim: "gt_dd_pro_bundled" };
const noop = () => {};

function card(item: WalkItem, plan: WalkPlan, ticks = {}, radioBar = false): string {
  const s = plan.sections.find((x) => x.items.includes(item))!;
  return renderToStaticMarkup(
    createElement(StepCard, {
      radioBar,
      item,
      position: `${s.title} · ${s.items.indexOf(item) + 1} of ${s.items.length}`,
      ticks,
      doc: WALKTHROUGH,
      mistakes: relevantMistakes(WALKTHROUGH, "f1_25", PS5),
      isFirst: false,
      isLast: item.kind === "check",
      onPrev: noop,
      onDone: noop,
      onUndo: noop,
      onSkipGuide: item.kind === "guide" ? noop : null,
      onDetail: noop,
      onOpenCheck: noop,
    }),
  );
}

const text = (html: string) =>
  html
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ");

function honest(html: string): void {
  const t = text(html);
  expect(t).not.toMatch(/\bundefined\b|\bnull\b|\bNaN\b|—/);
}

const PLANS: [string, () => WalkPlan][] = [
  ["F1 25, James (Competitive)", () => buildPlan(fixtures.rigRecF1James(), PS5, "f1_25")],
  ["GT7 (A SET)", () => buildPlan(fixtures.rigRecGt7James(), PS5, "gt7")],
  ["F1 25 Comfort, beginner", () => buildPlan(fixtures.rigRecF1ComfortBeginner(), PS5, "f1_25")],
  ["F1 25 on PC (no research guides)", () => buildPlan(fixtures.rigRecF1James(), { ...PS5, platform: "pc" }, "f1_25")],
];

describe("walkthrough step cards", () => {
  for (const [name, make] of PLANS) {
    it(`${name}: every step renders honestly with ‹ Previous and the primary action`, () => {
      const plan = make();
      for (const item of plan.sections.flatMap((s) => s.items)) {
        const html = card(item, plan);
        honest(html);
        expect(html).toContain("‹ Previous");
        expect(text(html)).toMatch(item.kind === "check" ? /Open Rig check/ : /Done, next|Done/);
      }
    });
  }

  it("‹ Previous / Done, next › stay reachable: sticky from 768 px, 96 px up while the mini radio bar shows (3.5)", () => {
    const plan = PLANS[0]![1]();
    const long = plan.sections[0]!.items[0]!;
    const nav = (html: string) => /<div[^>]*data-walk-nav[^>]*>/.exec(html)?.[0] ?? "";
    const plain = nav(card(long, plan));
    expect(plain).toContain("md:sticky");
    expect(plain).toContain("md:bottom-0");
    expect(plain).toContain("border-transparent");
    expect(plain).not.toContain("md:border-separator");
    const withBar = nav(card(long, plan, {}, true));
    expect(withBar).toContain("md:bottom-[96px]");
    expect(withBar).not.toContain("md:bottom-0");
  });

  it("a wheel row: the display code, the value at 96 px, chips in order, Why this value?", () => {
    const plan = PLANS[0]![1]();
    const ff = plan.sections[1]!.items.find((i) => i.id === "r:wheel:FF")!;
    const html = card(ff, plan);
    expect(html).toMatch(/<kbd[^>]*>FF<\/kbd>/);
    expect(html).toContain('data-size="step"');
    expect(text(html)).toMatch(/Factory 100 .*Verified · \d+ sources/);
    expect(text(html)).toContain("Why this value?");
  });

  it("an in-game row never shows its API id", () => {
    const plan = PLANS[0]![1]();
    for (const item of plan.sections[2]!.items.filter((i) => i.kind === "row")) {
      const html = card(item, plan);
      expect(html).not.toContain("<kbd");
      if (item.kind === "row") expect(text(html)).not.toContain(item.row.key);
    }
  });

  it("an instruction row shows its words at 26 px instead of a number", () => {
    const plan = PLANS[2]![1]();
    const bl = plan.sections[2]!.items.find((i) => i.id === "r:ingame:BRAKE_LINEARITY")!;
    const html = card(bl, plan);
    expect(html).not.toContain('data-size="step"');
    expect(html).toContain("text-[26px]");
    expect(text(html)).toContain("preset default");
  });

  it("a research step: how you know it worked, its evidence, unverified flagged, Sources, I know this part", () => {
    const plan = PLANS[0]![1]();
    const items = plan.sections.flatMap((s) => s.items).filter((i) => i.kind === "guide");
    const verified = items.find((i) => i.kind === "guide" && i.step.verified && i.step.evidence === "V" && i.step.check !== "-")!;
    const t = text(card(verified, plan));
    expect(t).toContain("How you know it worked");
    expect(t).toContain("Verified");
    expect(t).not.toContain("Unverified");
    expect(t).toContain("Sources");
    expect(t).toContain("I know this part");
    const unverified = items.find((i) => i.kind === "guide" && !i.step.verified)!;
    expect(text(card(unverified, plan))).toContain("Unverified");
  });

  it("old page names in the research point at the new pages", () => {
    const plan = PLANS[0]![1]();
    const pedal = plan.sections[3]!.items.find((i) => i.id === "g:pedals_hall:1")!;
    const t = text(card(pedal, plan));
    expect(t).toContain("Drive › Car in Pitwall");
    expect(t).not.toContain("pitwall Live tab");
  });

  it("recovery tips are a Disclosure under the step; done steps offer Mark not done, updated ones say so", () => {
    const plan = PLANS[0]![1]();
    const ff = plan.sections[1]!.items.find((i) => i.id === "r:wheel:FF")!;
    expect(text(card(ff, plan))).toMatch(/If it doesn't work \(\d\)/);
    const done = text(card(ff, plan, tick({}, [ff])));
    expect(done).toContain("Mark not done");
    expect(done).toContain("Done");
    const stale = text(card(ff, plan, { [ff.id]: "00000000" }));
    expect(stale).toContain("Updated");
  });

  it("the last step links to the rig check with the API's own text", () => {
    const plan = PLANS[0]![1]();
    const last = plan.sections[4]!.items.at(-1)!;
    const t = text(card(last, plan));
    expect(t).toContain("Drive 3 clean laps, then open Rig check");
    expect(t).toContain("After a session, open the rig check");
    expect(t).toContain("Open Rig check");
  });
});

describe("all settings, upgrades and tips", () => {
  it("every section with Copy section and every row in menu order; the summary keeps the warnings", () => {
    const rec = fixtures.rigRecF1James();
    const html = renderToStaticMarkup(createElement(RecommendationCards, { rec, catalog: fixtures.rigCatalog(), onRow: noop }));
    honest(html);
    const t = text(html);
    expect((t.match(/Copy section/g) ?? []).length).toBe(rec.sections.length);
    const wheel = rec.sections.find((s) => s.id === "wheel")!;
    let at = -1;
    for (const r of wheel.rows) {
      const k = t.indexOf(r.label, at + 1);
      expect(k, r.key).toBeGreaterThan(at);
      at = k;
    }
    expect(t).not.toContain("VIB_FFB_STRENGTH");
    expect(t).toContain("How to read the labels");
    const gt7 = fixtures.rigRecGt7James();
    const s = text(renderToStaticMarkup(createElement(SummaryCard, { rec: gt7 })));
    expect(s).toContain(gt7.warnings[0]!.slice(0, 40));
    expect(s).toContain("A SET");
  });

  it("upgrades: no history yet, both kits previewed with their changes, Record buttons", () => {
    const html = renderToStaticMarkup(createElement(UpgradesView, { profile: fixtures.rigProfile(), rec: fixtures.rigRecF1James() }));
    honest(html);
    const t = text(html);
    expect(t).toContain("No upgrades recorded yet");
    expect(t).toContain("What changes with the Boost Kit 180 (8 Nm)");
    expect(t).toContain("What changes with the CSL Pedals Load Cell Kit");
    expect((t.match(/Record: fitted/g) ?? []).length).toBe(2);
    expect(t).not.toContain("VIB_FFB_STRENGTH");
  });

  it("tips: symptom, why, fix; unverified ones flagged", () => {
    const tips = relevantMistakes(WALKTHROUGH, "f1_25", PS5);
    const t = text(renderToStaticMarkup(createElement(TipList, { tips })));
    honest(t);
    expect(t).toContain("Why:");
    expect(t).toContain("Fix:");
    expect((t.match(/Unverified/g) ?? []).length).toBe(tips.filter((m) => !m.verified).length);
  });
});
