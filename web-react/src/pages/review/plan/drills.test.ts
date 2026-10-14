// Review with coachref (spec 10.6, 10.7), static markup in plain node: the Coaching page's Drills card from the
// request cache (rows, empty, a server without coachref), and the Work on card's "Drill this" (only while this
// session's driver is live at the same track).
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { crFixture } from "../../../test/coachref";
import { ApiError } from "../../../lib/api";
import { fixture } from "../../../lib/drive/testkit";
import type { DrillView, DrillsQuery } from "../../../lib/endpoints/coachref";
import type { ReviewTrackModel, SessionDetail } from "../../../lib/endpoints/review";
import type { CoachingItem } from "../../../lib/review/coaching";
import { stubBrowser } from "../../../test/fakes";
import type { DrillsCardProps } from "./DrillsCard";
import type { WorkOnCardProps } from "../session/WorkOnCard";

function stubDom(): void {
  const { win } = stubBrowser("http://127.0.0.1:8810/#/review/coaching");
  Object.assign(win, {
    navigator: globalThis.navigator,
    removeEventListener: () => {},
    screen: { orientation: {} },
    visualViewport: {},
    matchMedia: () => ({ matches: true, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }),
  });
}

let DrillsCard: ComponentType<DrillsCardProps>;
let WorkOnCard: ComponentType<WorkOnCardProps>;
let cache: typeof import("../../../lib/cache").cache;
let coachrefKeys: typeof import("../../../lib/endpoints/coachref").coachrefKeys;
let reviewKeys: typeof import("../../../lib/endpoints/review").reviewKeys;
let live: typeof import("../../../lib/live").live;
let drivers: typeof import("../../../lib/drivers").drivers;

beforeAll(async () => {
  stubDom();
  DrillsCard = (await import("./DrillsCard")).DrillsCard;
  WorkOnCard = (await import("../session/WorkOnCard")).WorkOnCard;
  cache = (await import("../../../lib/cache")).cache;
  coachrefKeys = (await import("../../../lib/endpoints/coachref")).coachrefKeys;
  reviewKeys = (await import("../../../lib/endpoints/review")).reviewKeys;
  live = (await import("../../../lib/live")).live;
  drivers = (await import("../../../lib/drivers")).drivers;
  vi.unstubAllGlobals();
});

afterEach(() => {
  cache.clear();
  (live as unknown as { set(p: object): void }).set({ snap: null, connected: false });
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

const SUZUKA = fixture("edited-garage-between-runs").track_model as unknown as ReviewTrackModel;
const Q: DrillsQuery = { driver_id: 1, game: "f1_25", track_id: "f1:13", car_id: "f1:team:41", limit: 20 };

function renderCard(simple = false): string {
  stubDom();
  const html = renderToStaticMarkup(createElement(DrillsCard, { query: Q, model: SUZUKA, gameLengthM: 5807, simple }));
  vi.unstubAllGlobals();
  return html;
}

describe("Review › Coaching: Drills (spec 10.7)", () => {
  it("lists the drills here, newest first, with score, best, trend and whose lap they were against", () => {
    cache.set(coachrefKeys.drills(Q), crFixture<DrillView[]>("drills-history-suzuka"));
    const text = visible(renderCard());
    expect(text).toMatch(
      /^Drills T11 Hairpin Brake point 3 of 4 on the point .*Best: 1 m from the point · vs Sam's best Closer T9 Degner 2 Minimum speed 1 of 2 on target .*Best: 99 km\/h · vs Your best · Stopped after 2 of 5 laps$/,
    );
    for (const bad of ["undefined", "null", "NaN"]) expect(text).not.toContain(bad);
  });

  it("beginners: no best numbers in the rows (the sheet keeps them)", () => {
    cache.set(coachrefKeys.drills(Q), crFixture<DrillView[]>("drills-history-suzuka"));
    expect(visible(renderCard(true))).not.toContain("best 1 m");
  });

  it("no drills yet: how to start one", () => {
    cache.set(coachrefKeys.drills(Q), []);
    expect(visible(renderCard())).toBe('Drills No drills here yet. Start one from Drive before a run, or say "start a drill on turn 3".');
  });

  it("a synthetic row (never expected: drills refuse synthetic data) carries the SYNTHETIC chip", () => {
    const [first] = crFixture<DrillView[]>("drills-history-suzuka");
    cache.set(coachrefKeys.drills(Q), [{ ...first!, synthetic: true }]);
    expect(visible(renderCard())).toContain("SYNTHETIC");
  });

  it("a server without coachref: no card", () => {
    const c = cache as unknown as { load: typeof cache.load };
    void c.load(coachrefKeys.drills(Q), () => Promise.reject(new ApiError(404, "Not Found"))).catch(() => {});
    return Promise.resolve().then(async () => {
      await new Promise((r) => setTimeout(r, 0));
      expect(renderCard()).toBe("");
    });
  });
});

describe("Work on: Drill this (spec 10.6)", () => {
  const session = {
    id: "e3e0d6df9e22",
    game: "f1_25",
    platform: "ps5",
    track_id: "f1:13",
    track_name: "Suzuka",
    track_length_m: 5807,
    session_type: "Practice",
    session_type_raw: "Practice",
    car_name: "Ferrari",
    started_unix: 1791140400,
    source: "udp:20777",
    synthetic: false,
    lap_count: 6,
    best_clean_ms: 90986,
    weather: {},
    driver_id: 1,
    driver_name: "James",
    laps: [],
    setup: null,
  } as unknown as SessionDetail;
  const item = {
    key: "T6:low_min_speed",
    corner: "T6",
    kind: "low_min_speed",
    latest: {
      id: "o1",
      kind: "low_min_speed",
      corner: "T6",
      lap_number: 4,
      ref_lap_number: 3,
      value: -6,
      unit: "km/h",
      impact_s: 0.12,
      confidence: 0.9,
      text: "Degner 2: you carry 6 km/h less through the slowest point than on your reference lap.",
      consistency: "3 of the last 5 laps",
      positive: false,
      priority: 2,
      evidence: { min_speed_delta_kph: -6 },
    },
    latestLapId: 104,
    positive: false,
    lapNumbers: [2, 3, 4],
    seen: 3,
    compared: 5,
    meanImpactS: 0.11,
    meanConfidence: 0.9,
    meanPriority: 2,
    score: 1.2,
    repeated: true,
  } as unknown as CoachingItem;

  function renderWorkOn(): string {
    stubDom();
    cache.set(reviewKeys.session(session.id), session);
    const html = renderToStaticMarkup(
      createElement(WorkOnCard, {
        item,
        sessionId: session.id,
        model: SUZUKA,
        refLapId: 5,
        density: { signedBadges: true, simpleWording: false, workOnTextPx: 16 },
        gameLengthM: 5807,
      }),
    );
    vi.unstubAllGlobals();
    return html;
  }

  function goLive(over: { track?: string; driverId?: number } = {}) {
    const snap = fixture("recorded-d246-suzuka-on-track-brake-ahead");
    snap.session = { ...snap.session!, car_name: "Ferrari", track_id: over.track ?? "f1:13" };
    snap.connection = { ...snap.connection, source: "udp:20777", synthetic: false };
    snap.coachref = { driver_id: over.driverId ?? 1, choice: null, used_kind: "own_best", reason: null, pending: false, drill: null };
    (live as unknown as { set(p: object): void }).set({ snap, connected: true });
    (drivers as unknown as { set(p: object): void }).set({ activeId: over.driverId ?? 1 });
  }

  it("shows while this session's driver is live at this track", () => {
    goLive();
    expect(visible(renderWorkOn())).toContain("Drill this");
  });

  it("asks the server first: a drill that cannot run there shows the reason, not a button (UX review H1)", () => {
    goLive();
    const opts = crFixture<import("../../../lib/endpoints/coachref").DrillOptionsResponse>("drill-options-t11");
    cache.set(coachrefKeys.drillOptions("T6"), { ...opts, corner: "T6" }); // min_speed: unavailable there
    const text = visible(renderWorkOn());
    expect(text).not.toContain("Drill this");
    expect(text).toContain("You already reach the best minimum speed driven here (71 km/h): pick another skill.");
    cache.set(coachrefKeys.drillOptions("T6"), { ...opts, corner: "T6", available: false, reason: "Drills run on your own live driving." });
    expect(visible(renderWorkOn())).toContain("Drills run on your own live driving.");
  });

  it("hidden once the session is over (stale telemetry or ended): a tap could only be refused", () => {
    goLive();
    const snap = (live as unknown as { get(): { snap: Record<string, unknown> } }).get().snap;
    (live as unknown as { set(p: object): void }).set({ snap: { ...snap, session_state: "ended" }, connected: true });
    expect(visible(renderWorkOn())).not.toContain("Drill this");
    (live as unknown as { set(p: object): void }).set({ snap: { ...snap, connection: { ...(snap.connection as object), status: "stale" } }, connected: true });
    expect(visible(renderWorkOn())).not.toContain("Drill this");
  });

  it("hidden with nobody live, at another track, or with another driver in the seat", () => {
    expect(visible(renderWorkOn())).not.toContain("Drill this");
    goLive({ track: "f1:7" });
    expect(visible(renderWorkOn())).not.toContain("Drill this");
    goLive({ driverId: 2 });
    expect(visible(renderWorkOn())).not.toContain("Drill this");
  });
});

describe("Review › Coaching: the session's own work-on card shows the Summary's count (UX review)", () => {
  it("evidence: the recap's line when given, else the coach's own window", async () => {
    stubDom();
    const { WorkingOnCard } = await import("./WorkingOnCard");
    const latest = {
      ...(fixture("edited-garage-between-runs").observations[0] as unknown as CoachingItem["latest"]),
      consistency: "6 of the last 6 laps",
    };
    const item: CoachingItem = {
      key: "T1:low_min_speed",
      corner: "T1",
      kind: "low_min_speed",
      positive: false,
      latest,
      latestLapId: 31,
      lapNumbers: [2, 3],
      seen: 25,
      compared: 31,
      meanImpactS: 0.3,
      meanConfidence: 0.9,
      meanPriority: 0.3,
      score: 1,
      repeated: true,
      lapIds: [30, 31],
      recent: true,
      fixed: false,
    };
    const w = { item, label: "T1", name: null, spoken: "Turn 1", apexM: null, trend: null };
    const base = { w, sessionId: "s1", refLapId: 2, atM: null, simple: false, textPx: 17 };
    const own = visible(
      renderToStaticMarkup(createElement(WorkingOnCard, { ...base, evidence: "Seen on 25 of 31 laps compared with your reference" })),
    );
    expect(own).toContain("Seen on 25 of 31 laps compared with your reference");
    expect(own).not.toContain("6 of the last 6 laps");
    const other = visible(renderToStaticMarkup(createElement(WorkingOnCard, base)));
    expect(other).toContain("6 of");
    vi.unstubAllGlobals();
  });
});
