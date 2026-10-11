// Setup › Validation rendered from the lane's shared fixture (server-rendered to static markup in plain node, like the
// rig page's tests): the empty state, an active run, a test this Mac cannot run, per-driver marks, data that is not
// live (shown, never counted), the phone layout, plain words for every state (no API enum, no "undefined" / "null" /
// "NaN", unknown as "-"), the transcripts, the input check and the reports.

import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, describe, expect, it, vi } from "vitest";
import type { Driver } from "../../../lib/drivers";
import type { Catalog, InputPhaseId, PttRecord, RunSummary, ValidationReport } from "../../../lib/endpoints/validation";
import { pendingState, runWith, vfix } from "../../../lib/validation/testkit";
import { stubBrowser } from "../../../test/fakes";
import type { ChecklistActions, ChecklistViewProps } from "./ChecklistView";
import type { InputCheckCardProps } from "./InputCheckCard";
import type { ReportDetailProps } from "./ReportDetail";

function stubDom(): void {
  const { win } = stubBrowser("http://127.0.0.1:8770/#/setup/validation");
  Object.assign(win, {
    navigator: globalThis.navigator,
    removeEventListener: () => {},
    screen: { orientation: {} },
    visualViewport: {},
    matchMedia: () => ({ matches: true, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }),
  });
}

let ChecklistView: ComponentType<ChecklistViewProps>;
let StartList: ComponentType<{ catalog: Catalog; selection: Record<string, boolean>; onToggle: () => void }>;
let RunList: ComponentType<{ runs: RunSummary[]; onOpen: () => void }>;
let ReportDetail: ComponentType<ReportDetailProps>;
let PttList: ComponentType<{ records: PttRecord[]; busy: boolean; onMark: () => void }>;
let InputCheckCard: ComponentType<InputCheckCardProps>;

beforeAll(async () => {
  stubDom();
  ChecklistView = (await import("./ChecklistView")).ChecklistView;
  StartList = (await import("./StartSheet")).StartList as typeof StartList;
  RunList = (await import("./ReportsView")).RunList as typeof RunList;
  ReportDetail = (await import("./ReportDetail")).ReportDetail;
  PttList = (await import("./PttTranscripts")).PttList as typeof PttList;
  InputCheckCard = (await import("./InputCheckCard")).InputCheckCard;
  vi.unstubAllGlobals();
});

const noop = () => {};
const actions: ChecklistActions = {
  openStart: noop,
  openFinish: noop,
  pick: noop,
  next: noop,
  skip: noop,
  verdict: noop,
  openTranscripts: noop,
  inputPhase: async () => true,
  inputDone: noop,
  inputOpen: noop,
  showReports: noop,
  openDrive: noop,
};

function driver(id: number, name: string, initials: string): Driver {
  return {
    id,
    name,
    created_unix: 1791000000,
    preferences: { colour: "#38bdf8", initials, skill_level: "beginner", coaching_intensity: "normal", voice_enabled: true },
    coaching: {
      skill_level: "beginner",
      intensity: "normal",
      min_confidence: 0.6,
      min_impact_s: 0.1,
      max_per_lap: 1,
      max_corrective_per_lap: 1,
      max_positive_per_lap: 1,
      allowed_kinds: null,
      simple_wording: true,
      mention_consistency: false,
      corner_repeat_gap_laps: 2,
    },
    active: true,
    stats: { sessions: 0, laps: 0, clean_laps: 0, tracks: 0, last_session_unix: null, best_laps: [] },
  };
}
const JAMES = driver(1, "James", "JR");
const SAM = driver(2, "Sam", "SR");
const NAMES = new Map([
  [1, "James"],
  [2, "Sam"],
]);

function checklist(over: Partial<ChecklistViewProps> = {}): string {
  const props: ChecklistViewProps = {
    catalog: vfix.catalog(),
    run: vfix.run(),
    driver: JAMES,
    driverId: 1,
    names: NAMES,
    busy: false,
    wide: true,
    radioBar: false,
    actionError: null,
    refreshError: null,
    inputRecords: undefined,
    actions,
    ...over,
  };
  return renderToStaticMarkup(createElement(ChecklistView, props));
}

const text = (html: string) =>
  html
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&gt;/g, ">")
    .replace(/&lt;/g, "<")
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ");

/** Nothing invented, no API words: every state reads in plain words. */
function honest(html: string): void {
  const t = text(html);
  expect(t).not.toMatch(/\bundefined\b|\bnull\b|\bNaN\b|—/);
  expect(t).not.toMatch(/\b(no_evidence|not_live|driver_only|needs_review|not_run|inconclusive|tailscale_https|lan_http|loopback)\b/);
  expect(t).not.toContain(">=");
}

describe("no run", () => {
  it("says what to do, offers Start validation (64 px) and the radio commands", () => {
    const html = checklist({ run: null });
    honest(html);
    const t = text(html);
    expect(t).toContain("No validation run yet");
    expect(t).toContain("Start one when you are in the car with the game running.");
    expect(t).toContain("11 of 12 tests can run on this Mac");
    expect(t).toContain("Reports never change what Pitwall says works");
    const start = html.match(/<button[^>]*>[^<]*Start validation[^<]*<\/button>/)?.[0] ?? "";
    expect(start).toContain("min-h-16");
    expect(t).toContain("Radio commands");
  });

  it("nothing can run here: Start is disabled, not hidden", () => {
    const cat = vfix.catalog();
    for (const i of cat.items) {
      i.available = false;
      i.unavailable_reason = "Voice is off on this server.";
    }
    const html = checklist({ run: null, catalog: cat });
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>[^<]*Start validation/);
    expect(text(html)).toContain("0 of 12 tests can run on this Mac");
  });
});

describe("an active run", () => {
  it("run bar, the tests by group and the current test's card", () => {
    const html = checklist();
    honest(html);
    const t = text(html);
    expect(t).toContain("First rig run");
    expect(t).toContain("2 of 4 done");
    expect(t).toContain("F1 25 · PS5 · Austria · James · Radio: iPad (AirPod)");
    expect(t).toMatch(/Live/);
    for (const g of ["Dashboard at the wheel", "Radio", "Coaching", "Games"]) expect(t).toContain(g);
    // The card is the current test (cues_timing), with the catalogue's words.
    expect(t).toContain("Braking calls land on time");
    expect(t).toContain("Coaching · about 20 min · test 3 of 4");
    expect(t).toContain("Why: Braking calls have not been validated live.");
    expect(t).toContain("Drive › Radio › Braking calls: Off. Drive 3 laps, braking where you normally do.");
    expect(t).toContain("Did the calls land at or just before your braking points?");
    expect(t).toContain("No call came after my braking point");
    // What Pitwall saw: plain words, numbers with units and the minus sign, heuristic marked, the rule.
    expect(t).toContain("What Pitwall saw");
    expect(t).toContain("Not enough yet");
    expect(t).toContain("6 calls measured, 8 needed");
    expect(t).toContain("−3.1 m");
    expect(t).toContain("+0.11 s");
    expect(t).toMatch(/Calls measured 6 · target ≥ 8 · heuristic/);
    expect(t).toContain("How this is measured");
    // Glove-size answers and the bottom row.
    for (const b of ["Worked", "Didn't work", "Add a note", "‹ Previous", "Next ›", "Skip for now", "Finish and save"]) expect(t).toContain(b);
    const worked = html.match(/<button[^>]*>Worked<\/button>/)?.[0] ?? "";
    expect(worked).toContain("min-h-16");
    // The test on the card is highlighted in the list and its row says Now (with words for screen readers).
    expect(html).toMatch(/class="[^"]*bg-\[color-mix[^"]*"[^>]*data-key="cues_timing"/);
    expect(html).toMatch(/aria-label="Braking calls land on time Now"/);
    expect(t).not.toContain("The last refresh failed");
  });

  it("the sticky answer row clears the mini radio bar (96 px) while it shows", () => {
    const nav = (html: string) => /<div[^>]*data-validation-nav[^>]*>/.exec(html)?.[0] ?? "";
    expect(nav(checklist())).toContain("md:bottom-0");
    expect(nav(checklist({ radioBar: true }))).toContain("md:bottom-[96px]");
  });

  it("the last test offers Finish and save instead of Next", () => {
    const run = vfix.run();
    run.current_item = "gt7_ps5";
    const t = text(checklist({ run }));
    expect(t).toContain("Gran Turismo 7 on the PS5");
    expect(t).not.toContain("Next ›");
    expect(t).toContain("Input check · optional");
    expect(t).toContain("Not seen yet");
    expect(t).toContain("No Gran Turismo 7 data in this run yet");
  });

  it("a test the driver already answered shows the answer, the note and Clear", () => {
    const run = vfix.run();
    run.current_item = "radio_ptt";
    const html = checklist({ run });
    honest(html);
    const t = text(html);
    expect(t).toContain("✓ Worked");
    expect(t).toMatch(/You said: Worked · \d\d:\d\d/);
    expect(t).toContain("Wheel button slower to start than the screen one.");
    expect(t).toContain("Clear my answer");
    expect(t).toContain("Edit the note");
    expect(t).toContain("What the engineer heard");
    expect(html).toMatch(/aria-pressed="true"[^>]*>✓ Worked/);
    expect(t).toContain("Over Tailscale HTTPS Tailscale (HTTPS) · target Tailscale (HTTPS)");
    expect(t).toContain("AirPod microphone AirPod · target AirPod · heuristic");
  });

  it("the last refresh failed: the previous answer stays, with a note", () => {
    expect(text(checklist({ refreshError: "Failed to fetch" }))).toContain("The last refresh failed (Failed to fetch); showing the previous answer.");
  });

  it("an action failed: the server's words", () => {
    expect(text(checklist({ actionError: "item unavailable" }))).toContain("That didn't work item unavailable");
  });
});

describe("states", () => {
  it("data that is not live is shown, never counted (run warning and test warning)", () => {
    const run = vfix.run();
    run.context = { ...run.context, tier: "recorded" };
    const cues = run.items.find((i) => i.id === "cues_timing")!;
    cues.auto = { ...cues.auto, verdict: "not_live", tier: "recorded" };
    const html = checklist({ run });
    honest(html);
    const t = text(html);
    expect(t).toContain("This session is a replay: it is shown but does not count.");
    expect(t).toContain("Pitwall only saw this test in a replay: it is shown but does not count.");
    expect(t).toContain("Not live data");
    // never a green "Live" next to "does not count"
    expect(t).toContain("Data arriving · not counted");
    expect(html).not.toMatch(/data-tone="success"[^>]*>(<[^>]+>)*Live</);
  });

  it("generated (synthetic) data is excluded the same way", () => {
    const run = vfix.run();
    run.context = { ...run.context, tier: "synthetic" };
    expect(text(checklist({ run }))).toContain("This is generated test data (synthetic): it is shown but does not count.");
  });

  it("a test this Mac cannot run says why and cannot be answered", () => {
    const run = runWith(["game_selection", "cues_timing"], { current_item: "game_selection" });
    const html = checklist({ run });
    honest(html);
    const t = text(html);
    expect(t).toContain("Not available on this Mac");
    expect(t).toContain("This server has no game selection yet.");
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Worked<\/button>/);
  });

  it("per-driver test: marking for the seated driver, the other driver's answer listed", () => {
    const at = 1791834000;
    const glance = pendingState("ipad_glance", {
      status: "current",
      marks: [
        { driver_id: 1, verdict: "worked", notes: "", attestations: { read_corner: true }, extra: { first_look: "corner" }, at_unix: at, source: "screen" },
        { driver_id: 2, verdict: "didnt", notes: "Delta too small for me", attestations: {}, extra: {}, at_unix: at + 60, source: "voice" },
      ],
      auto: { verdict: "driver_only", reasons: ["James: 3 laps in the window"], checks: [], metrics: {}, tier: "live", updated_unix: at },
    });
    const run = runWith(["ipad_glance"], { current_item: "ipad_glance", items: [glance] });
    const asSam = checklist({ run, driver: SAM, driverId: 2 });
    honest(asSam);
    const t = text(asSam);
    expect(t).toContain("Marking for Sam");
    expect(t).toContain("✓ Didn't work");
    expect(t).toContain("by voice");
    expect(t).toContain("James: Worked");
    expect(t).toContain("What did you look at first?");
    expect(t).toContain("Your call");
    const asJames = text(checklist({ run, driver: JAMES, driverId: 1 }));
    expect(asJames).toContain("Marking for James");
    expect(asJames).toContain("✓ Worked");
    expect(asJames).toContain("Sam: Didn't work");
    // A driver who has not answered yet sees no answer of their own.
    const asThird = text(checklist({ run, driver: null, driverId: 3 }));
    expect(asThird).toContain("Marking for Driver #3");
    expect(asThird).not.toContain("You said");
  });

  it("phone: one Select of every test instead of the list; one column; a quieter Finish and Skip on its own row", () => {
    const html = checklist({ wide: false });
    honest(html);
    expect(html).toContain('aria-label="Test on screen"');
    expect(html).not.toContain('aria-label="Test groups"');
    expect(html).not.toContain('aria-label="Tests in this run"');
    expect(text(html)).toContain("Braking calls land on time");
    // the run bar's Finish is a 48 px secondary button on a phone (the test stays the main thing on screen)
    const finish = html.match(/<button[^>]*>Finish and save<\/button>/)?.[0] ?? "";
    expect(finish).toContain("min-h-12");
    expect(finish).not.toContain("min-h-16");
    // the bottom row: two columns, Skip on a row of its own above ‹ Previous / Next ›
    const nav = /<div[^>]*data-validation-nav[^>]*>/.exec(html)?.[0] ?? "";
    expect(nav).toContain("grid-cols-2");
    expect(html).toMatch(/order-first col-span-2[^"]*"><button[^>]*>Skip for now/);
    const wide = checklist({ wide: true });
    expect(wide).toContain('aria-label="Tests in this run"');
    expect(wide).not.toContain('aria-label="Test on screen"');
  });

  it("the iPad tests driven on Drive › Coach link there", () => {
    let opened = 0;
    const run = runWith(["ipad_home_screen", "cues_timing"], { current_item: "ipad_home_screen" });
    const html = checklist({ run, actions: { ...actions, openDrive: () => (opened += 1) } });
    expect(text(html)).toContain("Open Drive › Coach");
    expect(text(checklist())).not.toContain("Open Drive › Coach"); // braking calls: not a Drive test
    expect(opened).toBe(0);
  });

  it("nothing seen yet: no big zeros; a check not met on a test just started is 'Not yet', not red", () => {
    const run = runWith(["ipad_glance"], {
      current_item: "ipad_glance",
      items: [
        pendingState("ipad_glance", {
          status: "current",
          auto: {
            verdict: "driver_only",
            reasons: ["Only you can judge what you read at a glance"],
            checks: [
              { id: "review_laps", label: "Laps driven in this test (per driver)", status: "not_met", value: "0", target: ">= 3", heuristic: true },
              { id: "review_coach_page", label: "iPad on Drive › Coach", status: "not_met", value: "no", target: "yes", heuristic: false },
            ],
            metrics: {},
            tier: null,
            updated_unix: 1791833412,
          },
        }),
      ],
    });
    const html = checklist({ run });
    honest(html);
    expect(text(html)).toContain("Not yet");
    expect(text(html)).not.toContain("Not met");
    const home = runWith(["ipad_home_screen"], {
      current_item: "ipad_home_screen",
      items: [pendingState("ipad_home_screen", { status: "current", auto: { verdict: "no_evidence", reasons: ["No reports from an iPad yet"], checks: [], metrics: { wake_on_streak_s: 0, gaps: 0, hidden_transitions: 0 }, tier: null, updated_unix: 1 } })],
    });
    const t = text(checklist({ run: home }));
    expect(t).not.toContain("Screen kept on (longest)");
    expect(t).toContain("No reports from an iPad yet");
  });

  it("both answers look the same until one is given", () => {
    const html = checklist();
    const worked = html.match(/<button[^>]*>Worked<\/button>/)?.[0] ?? "";
    const didnt = html.match(/<button[^>]*>Didn&#x27;t work<\/button>/)?.[0] ?? "";
    const variant = (b: string) => /data-variant="([^"]+)"|button--(primary|secondary|danger-soft)/.exec(b)?.slice(1).find(Boolean);
    expect(worked).not.toBe("");
    expect(variant(worked)).toBe(variant(didnt));
  });

  it("a test this dashboard does not know: a readable row and a plain card", () => {
    const run = runWith(["future_test_x"], { current_item: "future_test_x" });
    const t = text(checklist({ run }));
    expect(t).toContain("Future test x");
    expect(t).toContain("This run has no tests this version of the dashboard knows.");
  });
});

describe("start", () => {
  it("optional tests start off, unavailable ones say why and cannot be chosen", () => {
    const cat = vfix.catalog();
    const sel = Object.fromEntries(cat.items.map((i) => [i.id, i.available && !i.optional]));
    const html = renderToStaticMarkup(createElement(StartList, { catalog: cat, selection: sel, onToggle: noop }));
    honest(html);
    const t = text(html);
    // a test this Mac cannot run: a plain row at full contrast with its reason and a chip, not a faded switch
    expect(t).toContain("This server has no game selection yet.");
    expect(t).toContain("Not available");
    expect(html).toMatch(/data-unavailable="game_selection"/);
    expect(html).not.toMatch(/disabled=""[^>]*>[^<]*Game choice/);
    expect(t).toContain("About 60 min · optional.");
    for (const g of ["Dashboard at the wheel", "Radio", "Coaching", "Games", "Drivers"]) expect(t).toContain(g);
    expect(cat.items.length).toBe(12);
  });
});

describe("transcripts", () => {
  it("newest first, heard right / wrong as 56 px toggles, nothing heard said plainly", () => {
    const base = vfix.runFull().evidence!.ptt[0]!;
    const records: PttRecord[] = [base, { ...base, id: "m90", transcript: "", answer: "Say again?", heard_right: null, tier: "loopback" }];
    const html = renderToStaticMarkup(createElement(PttList, { records, busy: false, onMark: noop }));
    honest(html);
    const t = text(html);
    expect(t.indexOf("Nothing heard")).toBeLessThan(t.indexOf("How are my tyres?"));
    expect(t).toContain("1.84 s to your ear");
    expect(t).toContain("✓ Heard right");
    expect(t).toContain("Not live data");
    expect(html).toMatch(/<button[^>]*min-h-14[^>]*>Heard right/);
    expect(text(renderToStaticMarkup(createElement(PttList, { records: [], busy: false, onMark: noop })))).toContain("No questions heard yet.");
  });
});

describe("input check", () => {
  const card = (over: Partial<InputCheckCardProps> = {}) =>
    renderToStaticMarkup(
      createElement(InputCheckCard, {
        itemId: "ac_ps5",
        phases: ["centre", "left", "right", "pedals", "reverse"] as InputPhaseId[],
        askRotation: true,
        records: undefined,
        disabled: false,
        onPhase: async () => true,
        onDone: noop,
        ...over,
      }),
    );
  it("Assetto Corsa asks for the wheel rotation first; Start waits for it", () => {
    const html = card();
    honest(html);
    const t = text(html);
    expect(t).toContain("Wheel rotation set in the game (degrees)");
    expect(t).toContain("CENTRE");
    expect(t).toContain("Hands off the wheel.");
    expect(t).toContain("Enter the wheel rotation first.");
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Start<\/button>/);
    expect(html).toContain('data-size="step"');
  });
  it("GT7: no rotation; results as facts", () => {
    const html = card({
      itemId: "gt7_ps5",
      phases: ["centre", "left", "right", "pedals"],
      askRotation: false,
      records: [
        { item_id: "gt7_ps5", phase: "left", start_unix: 1, end_unix: 4, samples: 30, steer_mean: -0.9, steer_min: -0.98, steer_max: 0, throttle_max: 0, brake_max: 0, gear_min: 1, steer_raw_range: null, rotation_deg: null },
        { item_id: "gt7_ps5", phase: "right", start_unix: 5, end_unix: 8, samples: 30, steer_mean: 0.1, steer_min: -0.98, steer_max: 0.97, throttle_max: 0, brake_max: 0, gear_min: 1, steer_raw_range: null, rotation_deg: null },
      ],
    });
    const t = text(html);
    expect(t).not.toContain("Wheel rotation");
    expect(t).toContain("Full lock left: −0.98 · right: +0.97 · sign as expected");
    expect(html).toMatch(/<button[^>]*>Start<\/button>/);
    expect(html).not.toMatch(/<button[^>]*disabled=""[^>]*>Start<\/button>/);
  });
});

describe("reports", () => {
  it("the run list: name, date, status, a Live chip and result counts", () => {
    const html = renderToStaticMarkup(createElement(RunList, { runs: [vfix.summary(), { ...vfix.summary(), id: "20261011-120000-0abc", label: null, tiers: ["recorded"], status: "finished" }], onOpen: noop }));
    honest(html);
    const t = text(html);
    expect(t).toContain("First rig run");
    expect(t).toContain("In progress");
    expect(t).toContain("Live");
    expect(t).toContain("1 passed");
    expect(t).toContain("2 to check");
    expect(t).toMatch(/Run of .*2026/);
    expect(t).toContain("No live data");
    expect(t).toContain("Finished");
  });

  it("one report: summary grid, per-test detail, what the run can support, the fixed disclaimer", () => {
    const report: ValidationReport = vfix.report();
    const props: ReportDetailProps = { report, names: NAMES, error: null, onOpenMarkdown: noop, onDownloadJson: noop, onBack: noop };
    const html = renderToStaticMarkup(createElement(ReportDetail, props));
    honest(html);
    const t = text(html);
    expect(t).toContain("20261012-193012-a3f1");
    expect(t).toContain("pitwall 0.1.0 (a1b2c3d) · macOS · voice on (Kokoro, Parakeet) · LLM on");
    expect(t).toContain("412 live records");
    expect(t).toContain("This run is still going");
    for (const h of ["Test", "Result", "Driver", "Pitwall saw", "Key evidence"]) expect(t).toContain(h);
    expect(t).toContain("Braking calls land on time");
    expect(t).toContain("To check");
    expect(t).toContain("6 calls measured, 8 needed");
    expect(t).toContain("What this run can support (for the maintainer): nothing yet"); // folded: nothing met
    expect(t).toContain("This report never changes capability statuses.");
    for (const b of ["Open report", "Download JSON", "Leave out transcripts", "‹ All runs"]) expect(t).toContain(b);
    // the summary grid is for wide screens; a phone reads the per-test sections
    expect(html).toMatch(/class="[^"]*hidden[^"]*md:flex[^"]*"[^>]*data-summary-grid/);
  });

  it("Leave out transcripts is on by default, and Download JSON honours it", () => {
    const report: ValidationReport = vfix.report();
    const html = renderToStaticMarkup(createElement(ReportDetail, { report, names: NAMES, error: null, onOpenMarkdown: noop, onDownloadJson: noop, onBack: noop }));
    expect(html).toMatch(/<label[^>]*data-selected="true"[^>]*>(?:(?!<\/label>)[\s\S])*Leave out transcripts/);
  });

  it("something met: the maintainer's suggestions are listed, open", () => {
    const report: ValidationReport = vfix.report();
    report.candidates = report.candidates.map((c, k) => ({ ...c, met: k === 0 }));
    const t = text(renderToStaticMarkup(createElement(ReportDetail, { report, names: NAMES, error: null, onOpenMarkdown: noop, onDownloadJson: noop, onBack: noop })));
    expect(t).toContain("What this run can support (for the maintainer)");
    expect(t).not.toContain("nothing yet");
    expect(t).toContain("Met in this run");
  });
});


describe("recorded answers of the real backend (scratch server, recorded replays)", () => {
  it("catalogue with voice off: the radio tests say why, nothing invented", () => {
    const cat = vfix.recordedCatalog();
    const sel = Object.fromEntries(cat.items.map((i) => [i.id, i.available && !i.optional]));
    const html = renderToStaticMarkup(createElement(StartList, { catalog: cat, selection: sel, onToggle: noop }));
    honest(html);
    const t = text(html);
    expect(t).toContain("Voice is off on this Mac.");
    const empty = checklist({ run: null, catalog: cat });
    honest(empty);
    expect(text(empty)).toMatch(/\d+ of 12 tests can run on this Mac/);
  });

  it("a run fed only by replays: the replay warning, every test in plain words", () => {
    const run = vfix.recordedRun();
    run.status = "active";
    run.current_item = "ac_ps5";
    const html = checklist({ run, catalog: vfix.recordedCatalog() });
    honest(html);
    const t = text(html);
    expect(t).toContain("This session is a replay: it is shown but does not count.");
    expect(t).toContain("Pitwall only saw this test in a replay: it is shown but does not count.");
    expect(t).toContain("Assetto Corsa · PS5");
    expect(t).toContain("✓ Didn't work");
    expect(t).not.toMatch(/≥\s*$|>=/);
  });

  it("its report renders every test, the evidence tables and the disclaimer", () => {
    const report = vfix.recordedReport();
    const html = renderToStaticMarkup(createElement(ReportDetail, { report, names: NAMES, error: null, onOpenMarkdown: noop, onDownloadJson: noop, onBack: noop }));
    honest(html);
    const t = text(html);
    for (const i of report.items) expect(t).toContain(i.title);
    expect(t).toContain("0 live records");
    expect(t).toContain(report.disclaimer);
    expect(t).not.toContain("This run is still going");
  });
});
