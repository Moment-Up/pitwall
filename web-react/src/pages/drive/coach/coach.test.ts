// Drive › Coach rendered from every Drive fixture (server-rendered to static markup in plain node, no DOM library):
// every state and overlay of spec 4.7 shows its band, card or slot content, unknown values are "-", nothing is
// invented, and the chunk rules of 4.11 hold.
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { driveModel, type DriveModel } from "../../../lib/drive/model";
import { FIXTURES, fixture, frame, newestT, snap } from "../../../lib/drive/testkit";
import type { SnapshotNext } from "../../../lib/drive/types";
import { aiFixtures } from "../../../lib/review/testkit";
import type { Driver } from "../../../lib/drivers";
import { stubBrowser } from "../../../test/fakes";
import type { CoachScreenProps } from "./CoachScreen";
import { cornerTitle, endedCorners } from "./view";

/** Browser globals the HeroUI / React Aria / Pro modules touch at import (router, matchMedia, visualViewport). */
function stubDom(): void {
  const { win } = stubBrowser("http://127.0.0.1:8770/next/#/drive/coach");
  Object.assign(win, {
    navigator: globalThis.navigator,
    removeEventListener: () => {},
    screen: { orientation: {} },
    visualViewport: {},
    matchMedia: () => ({
      matches: false,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
    }),
  });
}

let CoachScreen: ComponentType<CoachScreenProps>;
let SessionCompleteCard: ComponentType<{
  ended: NonNullable<DriveModel["ended"]>;
  tier: 1 | 2;
  corners?: { workOn: string | null; wentWell: string | null };
}>;

beforeAll(async () => {
  stubDom();
  CoachScreen = (await import("./CoachScreen")).CoachScreen;
  SessionCompleteCard = (await import("./SessionCompleteCard")).SessionCompleteCard;
  vi.unstubAllGlobals();
});

const JAMES: Driver = {
  id: 1,
  name: "James",
  created_unix: 0,
  preferences: { colour: "#ff6a2b", initials: "JR", skill_level: "advanced", coaching_intensity: "normal", voice_enabled: true },
  coaching: {
    skill_level: "advanced",
    intensity: "normal",
    min_confidence: 0.6,
    min_impact_s: 0.05,
    max_per_lap: 3,
    max_corrective_per_lap: 2,
    max_positive_per_lap: 1,
    allowed_kinds: null,
    simple_wording: false,
    mention_consistency: true,
    corner_repeat_gap_laps: 2,
  },
  active: true,
  stats: { sessions: 0, laps: 0, clean_laps: 0, tracks: 0, last_session_unix: null, best_laps: [] },
};

function model(name: string, opts: { connected?: boolean; driver?: Driver | null } = {}): DriveModel {
  const s = fixture(name);
  const driver = "driver" in opts ? (opts.driver ?? null) : JAMES;
  return driveModel({ snap: s, connected: opts.connected ?? true, nowS: newestT(s) + 1, driver });
}

function render(m: DriveModel, extra: Partial<CoachScreenProps> = {}): string {
  return renderToStaticMarkup(createElement(CoachScreen, { model: m, ...extra }));
}

/** Text a sighted user sees: tags stripped, visually hidden spans removed, entities decoded. */
function visible(markup: string): string {
  return markup
    .replace(/<span class="sr-only">[^<]*<\/span>/g, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/\s+/g, " ")
    .trim();
}

/** The status slot's markup (the first card). */
function slot(markup: string): string {
  const start = markup.indexOf("pwc-status");
  return markup.slice(start, markup.indexOf('data-slot="segment"', start));
}

describe("every fixture renders honestly", () => {
  it.each(FIXTURES)("%s (connected and offline)", (name) => {
    for (const connected of [true, false]) {
      const m = model(name, { connected });
      const html = render(m);
      const text = visible(html);
      expect(html).toContain(`data-state="${m.state}"`);
      // Unknown is "-": never the placeholders the spec bans (a zero time, --:--.---, an em dash), never a leaked
      // JS value. ("0.000 vs today's best" is a real difference of zero, not a placeholder.)
      for (const bad of ["0:00.000", "--:--", "—", "NaN", "undefined", "null", "Infinity", "[object Object]"]) {
        expect(text, `${name} ${connected ? "connected" : "offline"}: ${bad}`).not.toContain(bad);
      }
      expect(text.replace(/0\.000 (vs|on) today's best/g, ""), name).not.toMatch(/(^|\s)0\.000(\s|$)/);
      // The status slot is always there, and the radio strip always offers its one action.
      expect(html).toContain("pwc-status");
      expect(text).toMatch(/Go live|Listen only|Hold to talk/);
      // Evidence tiers stay visible (P8).
      if (m.status.evidence.synthetic) expect(text).toContain("SYNTHETIC");
      if (m.status.evidence.replay) expect(text).toContain("REPLAY");
    }
  });

  it("purple and PB never appear without D2 (4.6)", () => {
    for (const name of FIXTURES) {
      const m = model(name);
      if (m.tier === 2) continue;
      const html = render(m);
      expect(html, name).not.toContain('data-status="rec"');
      expect(html, name).not.toContain('data-status="pb"');
    }
  });
});

describe("states (4.7)", () => {
  it("offline: outline band, last content dimmed, every running value '-'", () => {
    const m = model("recorded-d246-suzuka-on-track-brake-ahead", { connected: false });
    const html = render(m);
    expect(m.state).toBe("offline");
    expect(html).toContain("data-dim");
    expect(visible(slot(html))).toContain("Offline reconnecting…");
    expect(html).toContain('class="pwc-dv" data-tone="unknown"');
    expect(html).not.toContain("data-car");
  });

  it("no telemetry: the waiting card with the three steps and the way to Setup › Connect", () => {
    const html = render(model("pipeline-no-data"), { listening: "Listening on UDP 20777" });
    const text = visible(html);
    expect(text).toContain("Waiting for telemetry");
    expect(text).toContain("Turn on UDP telemetry in the game");
    expect(text).toContain("Drive out of the garage");
    expect(text).toContain("Open Setup › Connect");
    expect(text).toContain("Try a demo replay (synthetic)");
    expect(visible(slot(html))).toContain("Listening on UDP 20777");
    expect(html).not.toContain("pwc-hero");
  });

  it("stale: amber outline with the age, distances and delta '-', facts kept, dimmed", () => {
    const m = model("recorded-austria-stale");
    const html = render(m);
    expect(m.state).toBe("stale");
    expect(html).toContain("data-dim");
    expect(visible(slot(html))).toMatch(/No signal · \d+ (s|min|h) game paused or in a menu\?/);
    expect(html).toContain('class="pwc-dv" data-tone="unknown"');
    expect(html).not.toMatch(/class="pwc-cdist"[^>]*>\d/); // the corner distance is "-", never a frozen number
    expect(html).not.toContain("data-car");
  });

  it("stale data of a game chosen away from: the chosen game's card replaces the old session's paused screen", () => {
    const m = model("recorded-austria-stale");
    const card = createElement("div", { className: "pwc-nodata" }, "Waiting for GT7 telemetry");
    const html = render(m, { noData: card, showNoData: true });
    expect(visible(html)).toContain("Waiting for GT7 telemetry");
    expect(html).not.toContain("pwc-hero");
    expect(render(m, { noData: card })).toContain("pwc-hero"); // not chosen away: the paused screen stays
  });

  it("ready (garage): the card with the seat, Not you? Switch driver, and the radio strip below", () => {
    const html = render(model("recorded-d246-suzuka-grid-before-start"));
    const text = visible(html);
    expect(text).toContain("James is in the seat");
    expect(text).toContain("Not you? Switch driver");
    expect(text).toMatch(/Target|Last run/);
    expect(text).toContain("Radio:");
    expect(text).not.toContain("Delta to reference"); // the card spans hero, coach and delta
    expect(html).toContain("pwc-ready pw-chamfer");
  });

  it("ready between runs leads with the last run", () => {
    const text = visible(render(model("edited-garage-between-runs")));
    expect(text).toContain("Last run");
    expect(text).toContain("Clean laps");
  });

  it("nobody in the seat says so", () => {
    expect(visible(render(model("recorded-suzuka-grid-before-start", { driver: null })))).toContain("Nobody is in the seat");
  });

  it("session complete: neutral band; the lazy card's fallback keeps the size, and the card itself renders", () => {
    const m = model("recorded-d246-austria-session-ended");
    const html = render(m);
    expect(visible(slot(html))).toMatch(/SESSION COMPLETE|CHEQUERED FLAG/);
    // A server render shows the same-size fallback until the lazy chunk has loaded once, then the card.
    expect(html.includes('aria-busy="true"') || html.includes("Review this session")).toBe(true);
    const card = visible(renderToStaticMarkup(createElement(SessionCompleteCard, { ended: m.ended!, tier: m.tier })));
    expect(card).toContain("Best lap");
    expect(card).toContain("Clean laps");
    expect(card).toContain("Gained today");
    expect(card).toContain("To the family record");
    expect(card).toContain("Review this session");
  });

  it("red flag: red band with role alert, hero kept, calls paused, delta '-'", () => {
    const html = render(model("edited-red-flag"));
    expect(html).toContain('role="alert"');
    expect(visible(slot(html))).toContain("RED FLAG");
    expect(visible(html)).toContain("Calls paused");
    expect(html).toContain("pwc-hero");
    expect(html).toContain('class="pwc-dv" data-tone="unknown"');
  });

  it("pit lane: cyan band with the limit, PIT + speed / limit, no delta, the next-run point", () => {
    const html = render(model("edited-pit-lane"));
    const text = visible(html);
    expect(visible(slot(html))).toContain("PIT LANE limit 80 km/h");
    expect(text).toContain("Pit lane · speed / limit");
    expect(text).toMatch(/PIT 78 \/ 80 km\/h/);
    expect(text).toContain("No delta in the pit lane");
    expect(text).toContain("Calls resume on your out lap");
  });

  it("on track: next corner, braking call, coaching point, delta with word and bar, sectors, lap times, car", () => {
    const html = render(model("recorded-d246-suzuka-on-track-brake-ahead"));
    const text = visible(html);
    expect(text).toContain("Next corner");
    expect(text).toContain("T11 Hairpin");
    expect(text).toMatch(/BRAKE T11 brake in \d+ m/);
    expect(text).toContain("Work on · last lap");
    expect(text).toContain("AHEAD");
    expect(html).toContain('data-side="ahead"');
    expect(text).toMatch(/S1 .*S2 .*S3/);
    expect(text).toMatch(/Lap .*Last .*Best/);
    expect(html).toContain("data-car"); // the car on the lap ribbon
    expect(html).toContain("pw-chamfer"); // the one accent edge
  });

  it("long corner rule: T10-13 Maggotts and Becketts on two lines", () => {
    const html = render(model("recorded-d246-silverstone-long-label"));
    expect(html).toContain('data-layout="two"');
    expect(visible(html)).toMatch(/T10-13/);
  });
});

describe("overlays (4.7)", () => {
  it("safety car: amber band, muted delta with the SC chip, calls paused", () => {
    const html = render(model("edited-safety-car"));
    expect(visible(slot(html))).toContain("SAFETY CAR");
    expect(html).toContain('class="pwc-dv" data-tone="muted"');
    expect(visible(html)).toMatch(/AHEAD SC|BEHIND SC|LEVEL SC/);
    expect(visible(html)).toContain("Calls paused");
  });

  it("yellow flag: yellow band naming the zone, hatched on the ribbon", () => {
    const html = render(model("recorded-suzuka-yellow-flag"));
    expect(visible(slot(html))).toMatch(/YELLOW FLAG .*ZONE \d+/);
    expect(html).toMatch(/fill="url\(#pw-ribbon-/); // hatched on the lap ribbon
  });

  it("blue flag: blue band only while the car is in a blue zone", () => {
    expect(visible(slot(render(model("recorded-austria-blue-in-zone"))))).toContain("BLUE FLAG let the car behind through");
    expect(visible(slot(render(model("recorded-austria-blue-elsewhere"))))).not.toContain("BLUE FLAG");
  });

  it("invalid lap: INVALID chip next to Lap, muted delta with INV, projected '-'", () => {
    for (const name of ["recorded-monza-invalid-lap", "synthetic-demo-invalid-lap"]) {
      const m = model(name);
      const html = render(m);
      expect(visible(html), name).toContain("INVALID");
      if (m.delta.tone !== "unknown") {
        expect(html, name).toContain('class="pwc-dv" data-tone="muted"');
        expect(visible(html), name).toContain("INV");
      }
    }
  });

  it("incident chip: the player's penalty shows for 6 s; another car's never", () => {
    expect(visible(slot(render(model("edited-penalty-player"))))).toContain("PENALTY");
    expect(visible(slot(render(model("recorded-suzuka-penalty-any-car"))))).not.toContain("PENALTY");
  });

  it("chequered flag while the last lap runs: neutral band over the normal screen", () => {
    const html = render(model("recorded-d246-suzuka-chequered-flag"));
    expect(visible(slot(html))).toContain("CHEQUERED FLAG");
    expect(html).toContain("pwc-hero");
  });

  it("radio off keeps the braking call on screen with a Radio off chip (4.5 [critic])", () => {
    const s = fixture("synthetic-demo-on-track-brake-ahead");
    s.cues = { ...s.cues!, muted: "radio off" };
    const m = driveModel({ snap: s, connected: true, nowS: newestT(s) + 1, driver: JAMES });
    const text = visible(render(m));
    if (m.cue.next) {
      expect(text).toContain("BRAKE");
      expect(text).toContain("Radio off");
    }
    expect(text).not.toContain("Calls paused");
  });

  it("evidence: the synthetic demo is labelled SYNTHETIC in the status slot, also on a band", () => {
    const html = render(model("synthetic-demo-on-track-brake-ahead"));
    expect(visible(slot(html))).toContain("SYNTHETIC");
  });

  it("Screen may sleep shows in the status slot when the wake lock is refused", () => {
    const html = render(model("recorded-d246-suzuka-on-track-brake-ahead"), { maySleep: true });
    expect(visible(slot(html))).toContain("Screen may sleep");
  });
});

describe("status slot: one line; chips never wrap or clip (4.8, P8)", () => {
  // Plain node has no layout engine: the one-line guarantee is checked as the CSS that makes it (no wrap, no shrink,
  // no clipping on the chips; ellipsis on what gives way instead) plus the markup each state renders. The measured
  // check at 1180 x 820 (chips height <= the 52 px slot) is done in a browser.
  // vitest serves CSS imports (even ?raw) empty, so the file is read from disk; node:fs through the process object
  // because tsconfig types are vite/client only (no @types/node).
  const fs = (
    globalThis as unknown as { process: { getBuiltinModule(id: "node:fs"): { readFileSync(p: URL, enc: "utf8"): string } } }
  ).process.getBuiltinModule("node:fs");
  const CSS = fs.readFileSync(new URL("./coach.css", import.meta.url), "utf8");
  /** The declarations of a top-level rule, by its exact selector. */
  const rule = (sel: string): string => {
    const esc = sel.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp(`(?:^|\\n)${esc} \\{([^}]*)\\}`).exec(CSS)?.[1] ?? "";
  };
  let navLock: { showHint(): void; clearHint(): void };
  beforeAll(async () => {
    navLock = (await import("../../../components/shell/navLock")).navLock;
  });

  it("the chips are one fixed line: no wrap, no shrink, no clipping; track, session and band detail ellipsize", () => {
    const chips = rule(".pwc-chips");
    expect(chips).toMatch(/flex:\s*none/);
    expect(chips).toMatch(/flex-wrap:\s*nowrap/);
    expect(chips).toMatch(/white-space:\s*nowrap/);
    expect(chips).not.toMatch(/overflow:\s*hidden/);
    expect(rule(".pwc-chips .pw-evidence")).toMatch(/flex-wrap:\s*nowrap/);
    for (const sel of [".pwc-trk", ".pwc-meta", ".pwc-band__sub"]) {
      expect(rule(sel), sel).toMatch(/text-overflow:\s*ellipsis/);
      expect(rule(sel), sel).toMatch(/min-width:\s*0/);
    }
    // The band detail gives way before the band words; the words never shrink while the detail has room (a
    // fractional shrink already shows the ellipsis), and ellipsize only when they alone overflow the band.
    expect(rule(".pwc-band__sub")).toMatch(/flex:\s*0 1000 auto/);
    expect(rule(".pwc-band__words")).toMatch(/flex:\s*none/);
    expect(rule(".pwc-band__words")).toMatch(/max-width:\s*100%/);
  });

  it("synthetic demo: SYNTHETIC and REPLAY in one nowrap container; the wake chip in words on the normal line", () => {
    const m = model("synthetic-demo-on-track-brake-ahead");
    expect(m.status.kind).toBe("normal");
    const html = slot(render(m, { maySleep: true }));
    expect(html.match(/class="pwc-chips"/g)).toHaveLength(1);
    expect(html).toMatch(/class="pw-evidence flex-nowrap"/);
    expect(visible(html)).toContain("SYNTHETIC");
    expect(visible(html)).toContain("Screen may sleep");
  });

  it("on a band the wake chip is icon-only (its label keeps the words) and the flag detail is its own span", () => {
    for (const name of ["recorded-suzuka-yellow-flag", "recorded-d246-austria-session-ended", "recorded-austria-stale"]) {
      const m = model(name);
      expect(m.status.kind, name).not.toBe("normal");
      const html = slot(render(m, { maySleep: true }));
      expect(html, name).toContain('aria-label="Screen may sleep"');
      expect(visible(html), name).not.toContain("Screen may sleep");
      expect(html, name).toContain('class="pwc-band__words"');
    }
    expect(slot(render(model("recorded-suzuka-yellow-flag")))).toMatch(/class="pwc-band__sub"/);
  });

  it("while the Drive lock hint shows, the wake chip is icon-only on the normal line too", () => {
    const m = model("recorded-d246-suzuka-on-track-brake-ahead");
    navLock.showHint();
    try {
      const html = slot(render(m, { maySleep: true }));
      expect(html).toContain('aria-label="Screen may sleep"');
      expect(visible(html)).not.toContain("Screen may sleep");
    } finally {
      navLock.clearHint();
    }
    expect(visible(slot(render(m, { maySleep: true })))).toContain("Screen may sleep");
  });
});

describe("Session complete card: Work on / Went well name their corner (mockup)", () => {
  it("by official label and name, resolved through the track model", () => {
    const s = fixture("recorded-d246-austria-session-ended");
    const m = driveModel({ snap: s, connected: true, nowS: newestT(s) + 1, driver: JAMES });
    expect(m.ended?.workOn?.corner).toBe("T4"); // D6 pick: the learned key "T4" is the official T6
    const corners = endedCorners(m.ended!, s.track_model);
    expect(corners.workOn).toBe("T6");
    const card = visible(renderToStaticMarkup(createElement(SessionCompleteCard, { ended: m.ended!, tier: m.tier, corners })));
    expect(card).toContain("Work on · T6");
    if (corners.wentWell) expect(card).toContain(`Went well · ${corners.wentWell}`);
    // Without a track model the learned key is all there is; without the prop, the bare titles.
    const bare = visible(renderToStaticMarkup(createElement(SessionCompleteCard, { ended: m.ended!, tier: m.tier })));
    expect(bare).toContain("Work on ");
    expect(bare).not.toContain("Work on ·");
  });

  it("cornerTitle: label and official name; the learned key resolves to the official label; null without a corner", () => {
    const tm = fixture("recorded-d246-austria-session-ended").track_model;
    expect(cornerTitle(tm, "T1")).toBe("T1 Niki Lauda Kurve");
    expect(cornerTitle(tm, "T4")).toBe("T6");
    expect(cornerTitle(tm, null)).toBeNull();
    expect(cornerTitle(null, "T4")).toBe("T4");
  });
});

describe("Session complete card: pace vs AI (AI pace spec 8)", () => {
  /** The ended Austria fixture with the AI comparison the server would publish for it (contract values). */
  function ended(ai: Partial<NonNullable<SnapshotNext["ai_pace"]>> | null) {
    const s = fixture("recorded-d246-austria-session-ended");
    const snap: SnapshotNext = { ...s, ai_pace: ai ? { ...aiFixtures.live(), session_id: s.session_id ?? "", ...ai } : null };
    return driveModel({ snap, connected: true, nowS: newestT(s) + 1, driver: JAMES });
  }

  it("one line when the session has an ok comparison: the gap in words and the rank, on best laps", () => {
    const m = ended({});
    expect(m.ended?.aiLine).toBe("AI difficulty 35: best lap 3.8 s slower than the typical AI car's best lap · 20th of 20 on best laps");
    const html = renderToStaticMarkup(createElement(SessionCompleteCard, { ended: m.ended!, tier: m.tier }));
    const card = visible(html);
    expect(card).toContain("AI difficulty 35: best lap 3.8 s slower than the typical AI car's best lap · 20th of 20 on best laps");
    expect(card).toContain("Review this session");
    // a row of its own, before the actions (not inside the REC / PB / SB legend's block)
    const line = html.indexOf("data-ai-line");
    expect(line).toBeGreaterThan(-1);
    expect(line).toBeLessThan(html.indexOf("pwc-end__actions"));
  });

  it("no line without a comparison, for another session, or for a status other than ok; no live AI widget", () => {
    for (const m of [ended(null), ended({ session_id: "another" }), ended({ status: "too_few_ai_cars" }), ended({ status: "unknown_difficulty", ai_difficulty: null })]) {
      expect(m.ended?.aiLine).toBeNull();
      const card = visible(renderToStaticMarkup(createElement(SessionCompleteCard, { ended: m.ended!, tier: m.tier })));
      expect(card).not.toContain("AI difficulty");
    }
    // on track, Drive shows nothing about the AI
    const onTrack = fixture("recorded-suzuka-on-track-brake-ahead");
    const live = driveModel({
      snap: { ...onTrack, ai_pace: { ...aiFixtures.live(), session_id: onTrack.session_id ?? "" } },
      connected: true,
      nowS: newestT(onTrack) + 1,
      driver: JAMES,
    });
    expect(visible(render(live))).not.toContain("typical AI car");
  });

  it("synthetic data says so", () => {
    expect(ended({ synthetic: true }).ended?.aiLine).toBe("AI difficulty 35: best lap 3.8 s slower than the typical AI car's best lap · 20th of 20 on best laps · synthetic data");
  });
});

describe("chunks (4.9, 4.11)", () => {
  /** Every Drive page source file (src/pages/drive/**), as text. */
  const SOURCES = Object.entries(
    import.meta.glob<string>(["../**/*.ts", "../**/*.tsx", "!../**/*.test.ts"], { query: "?raw", import: "default", eager: true }),
  );

  it("reads the Drive page sources", () => {
    expect(SOURCES.some(([f]) => f.endsWith("CoachPage.tsx"))).toBe(true);
    expect(SOURCES.some(([f]) => f.endsWith("SessionCompleteCard.tsx"))).toBe(true);
  });

  it("only the lazy Session complete card imports Pro KPI or a chart (Recharts stays out of the Drive bundle)", () => {
    for (const [f, src] of SOURCES) {
      const heavy = /from\s+["'](recharts|@heroui-pro\/react\/(kpi|line-chart|area-chart|bar-chart|markdown|code-block))["']/.test(src);
      expect(heavy && !f.endsWith("SessionCompleteCard.tsx"), f).toBe(false);
    }
  });

  it("the Session complete card is only ever imported dynamically", () => {
    for (const [f, src] of SOURCES) {
      expect(/import\s[^;]*from\s+["']\.\/SessionCompleteCard["']/.test(src), f).toBe(false);
    }
  });

  it("Drive numerals never animate: no NumberValue, NumberFlow or motion on Drive pages", () => {
    for (const [f, src] of SOURCES) {
      expect(/NumberValue|@number-flow|from\s+["']motion/.test(src), f).toBe(false);
    }
  });
});

describe("game selection on Coach (spec 5.3): only the sector slot, the delta header and the no-data card", () => {
  it("a game without sectors and with an estimated distance: one muted sector cell, '· estimated' on the delta", () => {
    const m = model("recorded-d246-suzuka-on-track-brake-ahead");
    const plain = render(m);
    const html = render(m, { game: { sectors: "Sectors · Not sent by GT7", deltaEstimated: true } });
    const text = visible(html);
    expect(text).toContain("Sectors · Not sent by GT7");
    expect(text).toContain("Delta to reference · estimated");
    expect(visible(plain)).not.toContain("estimated");
    // nothing else on Coach mentions the game: the status slot is the same
    expect(slot(html)).toBe(slot(plain));
  });

  it("the no-data slot shows the card it is given (the picker or the selected game's steps)", () => {
    const m = model("pipeline-no-data");
    expect(m.card).toBe("no_data");
    const html = render(m, { noData: createElement("div", { className: "probe" }, "What are you playing?") });
    expect(visible(html)).toContain("What are you playing?");
    expect(html).not.toContain("No packet has arrived yet");
  });

  it("the status slot carries a stationary game mismatch as an outline line", () => {
    const s = snap({ frame: frame({ speed_kph: 0 }) });
    const m = driveModel({
      snap: s,
      connected: true,
      nowS: newestT(s) + 1,
      driver: JAMES,
      mismatch: { text: "F1 25 data · GT7 selected", sub: "tap to change" },
    });
    expect(m.status.band).toBe("mismatch");
    const html = render(m);
    const text = visible(slot(html));
    expect(text).toContain("F1 25 data · GT7 selected");
    expect(text).toContain("tap to change");
    expect(slot(html)).toMatch(/<a [^>]*href="[^"]*\/setup\/game"/); // the band opens Setup › Game
  });
});
