// Records cards rendered from the leaderboard fixtures (static markup in plain node): the optional rows with their
// caveats, the F1DB credit and the bands (none when the server sends none), the spec-decoded EA rival, the pickers,
// the season question for the generic car, the empty board with the boards here, the history by density.
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, describe, expect, it, vi } from "vitest";
import type { LeaderboardBoard } from "../../../lib/endpoints/leaderboard";
import { familyBoard, type Scope, type TrackChoice } from "../../../lib/review/progress";
import { historyItems, showTimesToBeat, type RecordsDetail } from "../../../lib/review/records";
import { boardFixtures } from "../../../lib/review/testkit";
import { stubBrowser } from "../../../test/fakes";
import type { FamilyBoardCardProps } from "./FamilyBoardCard";
import type { TimesToBeatCardProps } from "./TimesToBeatCard";
import type { RecordsState } from "./useRecords";

let FamilyBoardCard: ComponentType<FamilyBoardCardProps>;
let RecordHistoryCard: ComponentType<{ items: ReturnType<typeof historyItems>; detail: RecordsDetail }>;
let TimesToBeatCard: ComponentType<TimesToBeatCardProps>;

beforeAll(async () => {
  const { win } = stubBrowser("http://127.0.0.1:8770/next/#/review/progress");
  Object.assign(win, {
    navigator: globalThis.navigator,
    removeEventListener: () => {},
    screen: { orientation: {} },
    visualViewport: {},
    matchMedia: () => ({ matches: true, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }),
  });
  FamilyBoardCard = (await import("./FamilyBoardCard")).FamilyBoardCard;
  RecordHistoryCard = (await import("./RecordHistoryCard")).RecordHistoryCard;
  TimesToBeatCard = (await import("./TimesToBeatCard")).TimesToBeatCard;
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

function honest(text: string): void {
  for (const bad of ["0:00.000", "NaN", "undefined", "null", "Infinity", "[object Object]"]) expect(text).not.toContain(bad);
}

function scope(carId: string | null, carLabel: string | null = null, over: Partial<TrackChoice> = {}): Scope {
  const track: TrackChoice = {
    game: "f1_25",
    trackId: "f1:17",
    label: "Austria",
    synthetic: false,
    sessions: 1,
    newest: 0,
    newestCarId: null,
    cars: [],
    unknownCar: 0,
    ...over,
  };
  return { track, carId, carLabel, carNamed: carLabel != null };
}

function state(board: LeaderboardBoard | undefined, over: Partial<RecordsState> = {}): RecordsState {
  return { board, error: null, missing: false, loading: false, pick: () => {}, generation: null, setGeneration: () => {}, ...over };
}

/** The board card, then the Times to beat card when the board has something for it (as the Records section). */
function render(board: LeaderboardBoard | undefined, opts: { scope?: Scope; detail?: RecordsDetail; over?: Partial<RecordsState> } = {}) {
  const records = state(board, opts.over);
  const detail = opts.detail ?? "some";
  let html = renderToStaticMarkup(
    createElement(FamilyBoardCard, {
      board: familyBoard([], board ?? null, null),
      records,
      scope: opts.scope ?? scope("f1:team:8", "McLaren"),
      seatedId: null,
      detail,
      glossary: true,
    }),
  );
  if (board && showTimesToBeat(board)) {
    html += renderToStaticMarkup(
      createElement(TimesToBeatCard, { board, detail, generation: records.generation, onGeneration: () => {} }),
    );
  }
  return { html, text: visible(html) };
}

describe("family board card", () => {
  it("Time Trial: the EA rival (spec-decoded) and the real pole, each with its caveat; gold and silver bands", () => {
    const { html, text } = render(boardFixtures.timeTrial(), { detail: "plain" });
    honest(text);
    expect(text).toContain("Family board Austria · McLaren · Time trial · Dry");
    expect(text).toContain("Driver Best Gap vs EA rival vs real pole");
    expect(text).toContain("Jo 1:05.900 Fastest Gold 1.400 s slower Silver 1.929 s slower");
    expect(text).toContain("Sam 1:06.000 0.100 s behind Gold 1.500 s slower Silver 2.029 s slower");
    expect(text).toContain("Kim no clean lap here yet");
    expect(html).toContain('data-band="gold"');
    expect(html).toContain('data-band="silver"');
    expect(text).toContain("Gold: within 3 % of that time, or faster. Silver: within 5 %. Bronze: within 10 %.");
    expect(html).toContain('aria-label="What is gold, silver and bronze?"');
    // the EA rival: labelled spec-decoded, its caveat says so; the real pole: caveat and linked credit
    expect(text).toContain("Times to beat EA rival spec-decoded 1:04.500");
    expect(text).toContain("Read from EA's spec: not yet seen in a recording.");
    expect(text).toContain("Real F1 pole 2025 · Lando Norris 1:03.971 Austrian Grand Prix, 28 Jun 2025");
    expect(text).toContain("F1 25 is not the real car");
    expect(text).toContain("Real F1 times: F1DB , CC BY 4.0");
    expect(html).toContain('href="https://github.com/f1db/f1db" target="_blank" rel="noopener noreferrer"');
    // the pickers: session type (a Segment) and assists (a Select) between the McLaren boards here
    expect(html).toContain('aria-label="Session type"');
    expect(text).toContain("Time trial Race");
    expect(html).toContain('aria-label="Assists"');
    expect(text).not.toContain("F2");
    // plain: no percentages, no assists line
    expect(text).not.toContain("2.17 %");
    expect(text).not.toContain("Traction control full, Automatic gears");
  });

  it("intermediate and advanced add percentages, dates, assists, then sectors and the theoretical best", () => {
    const some = render(boardFixtures.timeTrial(), { detail: "some" }).text;
    expect(some).toContain("4.32 km · Braking assist medium, ABS on, Traction control full, Automatic gears, Racing line full");
    expect(some).toContain("Sam Sat 10 Oct · 2 clean laps 1:06.000 0.100 s behind 0.15 % Gold 1.500 s slower 2.33 % Silver 2.029 s slower 3.17 %");
    expect(some).toContain("McLaren · Traction control off, ABS on, Gearbox assist off");
    expect(some).not.toContain("16.400");
    const all = render(boardFixtures.timeTrial(), { detail: "all" }).text;
    expect(all).toContain("16.400 · 28.100 · 21.300 Added up: 1:05.800, 0.200 s to find Game version 1.26");
    expect(all).toContain("Sectors 16.000 · 28.000 · 20.500");
    expect(all).toContain("Fastest race lap on this layout (F1DB): 1:05.619, Carlos Sainz Jr., 2020");
    expect(all).toContain("Clean, valid laps of real driving only");
  });

  it("no band is drawn when the server sends none (+10.28 %), and then no band rule either", () => {
    const { html, text } = render(boardFixtures.austriaHaas(), { scope: scope("f1:team:7", "Haas") });
    expect(text).toContain("James Sat 10 Oct · 18 clean laps 1:10.549 Fastest 6.578 s slower 10.28 %");
    expect(html).not.toContain("data-band=");
    expect(text).not.toContain("Gold: within 3 %");
    expect(text).not.toContain("EA rival");
  });

  it("the generic car: no real row, the note says why in muted words, and the season is asked", () => {
    const { html, text } = render(boardFixtures.miamiGeneric(), { scope: scope("f1:team:41", "F1 Generic", { trackId: "f1:30", label: "Miami" }) });
    expect(html).not.toContain("data-benchmark");
    expect(text).toContain("Times to beat Which real season does this car match? 2025 car 2026 car");
    expect(html).toContain('aria-label="Car season"');
    expect(text).toContain("The game does not say whether this is a 2025 or a 2026 car, so there is no real season to compare with.");
    // answered "2025": the 2025 pole, a bronze band; the question stays to change the answer
    const chosen = render(boardFixtures.miamiGeneric2025(), {
      scope: scope("f1:team:41", "F1 Generic", { trackId: "f1:30", label: "Miami" }),
      over: { generation: "f1_2025" },
    });
    expect(chosen.text).toContain("Real F1 pole 2025 · Max Verstappen");
    expect(chosen.text).toContain("Bronze 6.913 s slower");
    expect(chosen.text).toContain("2025 car 2026 car");
    expect(chosen.text).not.toContain("no real season to compare with");
  });

  it("GT7: the track-limits note, nothing about assists or sessions made up", () => {
    const { text } = render(boardFixtures.gt7(), { scope: scope("gt7:car:3353", "Car 3353", { game: "gt7", trackId: "gt7:sf:380:120:15:3800:530" }) });
    honest(text);
    expect(text).toContain("This game does not say when a lap breaks track limits: a lap with a cut still counts here.");
    expect(text).toContain("Session type unknown · Weather unknown");
    expect(text).not.toContain("Times to beat");
  });

  it("nothing on the board asked for: what to do, and the boards here to open", () => {
    const { html, text } = render(boardFixtures.austriaNoMatch(), { scope: scope("f1:team:3", "Williams") });
    honest(text);
    expect(text).toContain("No family board here yet in the Williams: a clean, valid lap starts one.");
    expect(text).toContain("F1 Generic · Race · Dry Record 1:18.351, James");
    expect(text).toContain("Haas · Race · Dry Record 1:10.549, James");
    expect(html).toContain('aria-label="Family boards here"');
    expect(html).not.toContain("<table");
  });

  it("loading, an error, an older server, a synthetic track", () => {
    expect(render(undefined).html).toContain('aria-busy="true"');
    expect(render(undefined, { over: { error: new Error("boom") } }).text).toContain("The family board could not be loaded: boom");
    expect(render(undefined, { over: { missing: true } }).text).toContain("The family board needs a newer Pitwall server.");
    expect(render(undefined, { scope: scope(null, null, { synthetic: true, trackId: "synthetic:f1:17" }) }).text).toContain(
      "Synthetic sessions never count on a family board",
    );
  });
});

describe("record history card", () => {
  const items = historyItems(boardFixtures.timeTrial().history);

  it("newest first; the beginner sees the latest change and Show all", () => {
    const plain = visible(renderToStaticMarkup(createElement(RecordHistoryCard, { items, detail: "plain" })));
    expect(plain).toContain("Record history Sun 11 Oct Jo took the record from Sam: 1:05.900, 0.100 s faster Show all 3");
    expect(plain).not.toContain("Sam set the first record");
    expect(plain).not.toContain("3 records since");
    const some = visible(renderToStaticMarkup(createElement(RecordHistoryCard, { items, detail: "some" })));
    expect(some).toContain("Record history 3 records since Sat 10 Oct, 1 taken from another driver");
    expect(some).toContain("Sam set the first record: 1:06.500");
    expect(some).not.toContain("Show all");
  });

  it("no record yet", () => {
    const t = visible(renderToStaticMarkup(createElement(RecordHistoryCard, { items: [], detail: "all" })));
    expect(t).toContain("No record here yet: the first clean, valid lap on this board sets it.");
  });
});
