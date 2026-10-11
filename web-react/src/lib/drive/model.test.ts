import { describe, expect, it } from "vitest";
import { live, offlineSnapshot } from "../live";
import { DEFAULT_PREFS, type Prefs } from "../prefs";
import { driveModel, type DriveModelInput } from "./model";
import { EMPTY_MEMO } from "./state";
import { asLive, driver, fixture, newestT, snap } from "./testkit";
import { MINUS, THIN } from "./text";
import type { SnapshotNext } from "./types";

function model(s: SnapshotNext | null, over: Partial<DriveModelInput> = {}) {
  return driveModel({ snap: s, connected: true, nowS: newestT(s) + 1, driver: driver(), ...over });
}

describe("driveModel: on track (real Suzuka, braking call ahead)", () => {
  const m = model(fixture("recorded-suzuka-on-track-brake-ahead"));

  it("puts the next corner and its call in the hero", () => {
    expect(m.state).toBe("on_track");
    expect(m.card).toBeNull();
    expect(m.hero).toMatchObject({
      kind: "corner",
      head: "Next corner",
      label: "T11",
      name: "Hairpin",
      layout: "one",
      direction: "left",
      distanceText: "330 m",
      focus: true,
      frozen: false,
      aria: "Next corner, T11, Hairpin, 330 m",
    });
    expect(m.cue.next).toMatchObject({ chip: "BRAKE", text: "T11 brake", inM: 343, inText: "343 m" });
  });

  it("never shows the call just passed with a lap-wrapped distance ('brake in 5 793 m')", () => {
    const s = fixture("recorded-suzuka-on-track-brake-ahead");
    // the server's next call after its target was passed: the same corner a lap later (cues.py _next_cue)
    s.cues = { ...s.cues!, next: { ...s.cues!.next!, in_m: 5793 } };
    const w = model(s);
    expect(w.hero).toMatchObject({ kind: "corner", label: "T11" });
    expect(w.cue.next).toBeNull();
    expect(w.cue.note ?? "").not.toMatch(/km|5 793/);
  });

  it("lays out a long corner on two lines (real Silverstone T10-13)", () => {
    const h = model(fixture("recorded-d246-silverstone-long-label")).hero;
    expect(h).toMatchObject({ kind: "corner", label: "T10-13", name: "Maggotts and Becketts", layout: "two" });
  });

  it("fills the coach card, delta, sectors, laps and ribbon", () => {
    expect(m.coach).toMatchObject({ tagText: "Work on · last lap", heading: null, full: false, source: "observation" });
    expect(m.delta).toMatchObject({ text: `${MINUS}0.60`, word: "AHEAD", refLabel: "Lap 3 · 1:37.191 · today" });
    expect(m.sectors.caption).toBe("Last lap · L4");
    expect(m.laps.lap.text).toBe("0:39.8");
    expect(m.ribbon.car).toBeCloseTo(0.4275, 3);
    expect(m.status).toMatchObject({
      kind: "normal",
      band: "normal",
      pill: { tone: "live", text: "Live" },
      evidence: { synthetic: false, replay: true },
      chip: null,
    });
    expect(m.tier).toBe(1);
    expect(m.coloured).toBe(false); // a replay: outside the timing scope (4.6)
    expect(m.legend).toBe("A replay: times are not coloured");
    expect(m.laps.best).toMatchObject({ text: "1:37.037", status: "neutral", tag: null });
    expect(model(asLive(fixture("recorded-suzuka-on-track-brake-ahead")))).toMatchObject({
      coloured: true,
      legend: "SB your best today",
      laps: { best: { status: "sb", tag: "SB" } },
    });
    expect(m.telemetryLive).toBe(true);
    expect(m.onTrack).toBe(true);
    expect(m.dim).toBe(false);
    expect(m.memo.lastCorner).toBe("T7");
  });

  it("applies the Drive lock to beginner profiles by default, and as configured", () => {
    const s = fixture("recorded-suzuka-on-track-brake-ahead");
    expect(model(s, { driver: driver({ skill: "beginner" }) }).lockApplies).toBe(true);
    expect(model(s, { driver: driver({ skill: "advanced" }) }).lockApplies).toBe(false);
    expect(model(s, { prefs: { driveLock: "everyone" } }).lockApplies).toBe(true);
    expect(model(s, { driver: driver({ skill: "beginner" }), prefs: { driveLock: "off" } }).lockApplies).toBe(false);
    expect(model(fixture("edited-pit-lane"), { prefs: { driveLock: "everyone" } }).lockApplies).toBe(false);
    expect(model(s, { driver: null }).lockApplies).toBe(true); // nobody in the seat: the safe side
    const p: Prefs = { ...DEFAULT_PREFS, driveLock: "off" }; // lib/prefs.ts Prefs fits DrivePrefs
    expect(model(s, { driver: null, prefs: p }).lockApplies).toBe(false);
  });

  it("speaks to a beginner about the target lap and hides the projected lap", () => {
    const b = model(fixture("recorded-suzuka-on-track-brake-ahead"), { driver: driver({ skill: "beginner" }) });
    expect(b.beginner).toBe(true);
    expect(b.delta.label).toBe("vs your target lap");
    expect(b.delta.showProjected).toBe(false);
  });
});

describe("driveModel: each state", () => {
  it("offline keeps the last corner on screen, dimmed, and blanks every live value", () => {
    const live = fixture("recorded-suzuka-on-track-brake-ahead");
    const first = model(live);
    const off = offlineSnapshot(live) as SnapshotNext;
    const m = model(off, { connected: false, memo: first.memo });
    expect(m.state).toBe("offline");
    expect(m.dim).toBe(true);
    expect(m.status).toMatchObject({ kind: "outline", tone: "bad", text: "Offline", pill: { tone: "offline" } });
    expect(m.hero).toMatchObject({ kind: "corner", label: "T11", name: "Hairpin", distanceText: "-", approach: null, frozen: true });
    expect(m.delta).toMatchObject({ text: "-", reason: "Offline" });
    expect(m.sectors.cells.every((c) => c.text === "-")).toBe(true);
    expect(m.laps.lap.text).toBe("-");
    expect(m.ribbon.car).toBeNull();
    expect(m.telemetryLive).toBe(false);
    // without the memo there is nothing to show but the reason
    expect(model(off, { connected: false }).hero).toMatchObject({ kind: "empty", text: "Position on the lap unknown" });
  });

  it("stale dims the screen, hides the distance and the car, and keeps completed facts", () => {
    const m = model(fixture("recorded-austria-stale"));
    expect(m.state).toBe("stale");
    expect(m.dim).toBe(true);
    expect(m.hero).toMatchObject({ kind: "corner", distanceText: "-", approach: null, frozen: true });
    expect(m.delta.text).toBe("-");
    expect(m.laps.best.text).toBe("1:10.549");
    expect(m.ribbon.car).toBeNull();
  });

  it("no telemetry shows the no-telemetry card", () => {
    const m = model(fixture("pipeline-no-data"));
    expect(m).toMatchObject({ state: "no_data", card: "no_data", hero: { kind: "card" } });
    expect(m.status).toMatchObject({ text: "Waiting for telemetry", pill: { text: "No data" } });
    expect(m.ribbon.empty).toBe(true);
  });

  it("session complete shows the card with best lap, clean laps, gain and one Work on / Went well", () => {
    const m = model(asLive(fixture("recorded-austria-session-ended")));
    expect(m).toMatchObject({ state: "ended", card: "ended", hero: { kind: "card" } });
    expect(m.status).toMatchObject({ kind: "fill", text: "SESSION COMPLETE", sub: "Austria · Race · 10 laps" });
    expect(m.ended).toMatchObject({
      reviewHref: `#/review/sessions/${fixture("recorded-austria-session-ended").session_id}`,
      best: { text: "1:11.745", status: "sb", tag: "SB", lapNumber: 63, sub: "lap 63" },
      clean: { clean: 9, total: 10, text: "9 of 10", sub: "1 not used: flashback" },
      // one convention on every page: a positive number and a word, never a bare sign
      gained: { text: "4.8 s faster", amount: "4.8 s", word: "faster", sub: "first clean lap → best" },
      toYourBest: null,
      toRecord: null,
    });
    expect(m.ended?.workOn?.tag).toBe("work_on");
    expect(m.ended?.wentWell?.tag).toBe("good");
    // the replay itself: the same best lap, uncoloured
    expect(model(fixture("recorded-austria-session-ended")).ended?.best).toMatchObject({ text: "1:11.745", status: "neutral", tag: null });
  });

  it("keeps the Session complete card when D4 ended goes stale (F1 stops sending at session_ended)", () => {
    const m = model(fixture("recorded-d246-austria-stale-ended"));
    expect(m).toMatchObject({ state: "ended", card: "ended", dim: false, hero: { kind: "card" } });
    expect(m.status).toMatchObject({ kind: "fill", band: "complete", text: "SESSION COMPLETE", pill: { tone: "stale", text: "Stale 2 s" } });
    expect(m.ended?.reviewHref).toBe(`#/review/sessions/${fixture("recorded-d246-austria-stale-ended").session_id}`);
    // a replay with a D2 block whose records are off: no REC / PB legend
    expect(m).toMatchObject({ tier: 1, coloured: false, legend: "A replay: times are not coloured" });
    expect(m.ended).toMatchObject({ toYourBest: null, toRecord: null });
  });

  it("lists every reason a lap was not used once", () => {
    const m = model(fixture("recorded-austria-excerpt-session-ended"));
    expect(m.ended?.clean).toEqual({ clean: 0, total: 3, text: "0 of 3", sub: "3 not used: incomplete, standing start" });
    expect(m.ended?.best).toBeNull();
    expect(m.ended?.gained.text).toBe("-");
  });

  it("red flag keeps the hero, pauses the calls and blanks the delta", () => {
    const s = fixture("edited-red-flag");
    const m = model(s);
    expect(m.state).toBe("red_flag");
    expect(m.status).toMatchObject({ kind: "fill", tone: "red", text: "RED FLAG", role: "alert" });
    expect(m.hero.kind).toBe("corner");
    expect(m.cue).toEqual({ next: null, note: "Calls paused", muted: true, radioOff: false, ai: false });
    expect(m.delta).toMatchObject({ text: "-", reason: "Red flag" });
    expect(m.lockApplies).toBe(false);
  });

  it("pit lane shows speed against the limit and the last lap's top point in full", () => {
    const m = model(fixture("edited-pit-lane"));
    expect(m.state).toBe("pit_lane");
    expect(m.status).toMatchObject({ band: "pit", text: "PIT LANE", sub: "limit 80 km/h" });
    expect(m.hero).toEqual({
      kind: "pit",
      label: "PIT",
      speedText: "78",
      limitText: "80",
      over: false,
      aria: "Pit lane: 78 of 80 km/h",
    });
    expect(m.cue.note).toBe("Calls resume on your out lap");
    expect(m.coach).toMatchObject({ heading: "Next run · from L4", full: true, tag: "work_on", size: 22, clamp: false });
    expect(m.coach.text).toMatch(/^Turn 9 \(Degner 2\)/);
    expect(m.delta.reason).toBe("No delta in the pit lane");
    const fast = fixture("edited-pit-lane");
    fast.frame = { ...fast.frame!, speed_kph: 84.4 };
    expect(model(fast).hero).toMatchObject({ kind: "pit", speedText: "84", over: true });
  });

  it("garage before the first lap shows the Ready card with the seat, the target and today", () => {
    const s = fixture("recorded-suzuka-grid-before-start");
    const alex = driver({
      stats: {
        sessions: 3,
        laps: 30,
        clean_laps: 20,
        tracks: 2,
        last_session_unix: null,
        best_laps: [
          {
            game: "f1_25",
            track_id: "f1:13",
            track_name: "Suzuka",
            lap_time_ms: 96360,
            lap_id: 77,
            session_id: "old",
            car_name: null,
            synthetic: false,
            set_unix: new Date(2026, 9, 3, 20).getTime() / 1000,
          },
          {
            game: "f1_25",
            track_id: "f1:13",
            track_name: "Suzuka",
            lap_time_ms: 90000,
            lap_id: 78,
            session_id: "demo",
            car_name: null,
            synthetic: true, // never a best
            set_unix: 0,
          },
        ],
      },
    });
    const m = model(s, { driver: alex, nowS: new Date(2026, 9, 11, 14).getTime() / 1000 });
    expect(m).toMatchObject({ state: "garage", card: "ready" });
    expect(m.status).toMatchObject({ kind: "normal", band: "ready", text: "Ready · One-shot qualifying" });
    expect(m.ready).toMatchObject({
      seat: { name: "Alex", initials: "AL", line: "Alex is in the seat", skillText: "Advanced", coachingText: "Coaching: normal" },
      phase: "before_first_lap",
      target: {
        // stats.best_laps is per game + track, any car: never green before D2 (4.6), and it says so
        yourBest: { text: "1:36.360", status: "neutral", tag: null, date: "3 Oct · any car", anyCar: true },
        record: null,
        reference: "none yet: your first clean lap becomes the reference",
      },
      lastRun: null,
      today: { focus: [], callsMode: "Braking calls: Focus corners" },
      nextRun: null,
      footer: `5${THIN}809 m · S2 2${THIN}226 m · S3 4${THIN}690 m`,
    });
    expect(model(s, { driver: null }).ready?.seat.line).toBe("Nobody is in the seat");
  });

  it("Your best here from stats.best_laps is neutral, says 'any car' unless it was set in this car (real grid, no D2)", () => {
    const nowS = new Date(2026, 9, 11, 14).getTime() / 1000;
    const best = (car_name: string | null, lap_time_ms = 90986) => ({
      game: "f1_25",
      track_id: "f1:13",
      track_name: "Suzuka",
      lap_time_ms,
      lap_id: 77,
      session_id: "old",
      car_name,
      synthetic: false,
      set_unix: new Date(2026, 9, 3, 20).getTime() / 1000,
    });
    const jo = (b: ReturnType<typeof best>) =>
      driver({ stats: { sessions: 1, laps: 1, clean_laps: 1, tracks: 1, last_session_unix: null, best_laps: [b] } });
    const s = fixture("recorded-d246-suzuka-grid-before-start"); // no bests block
    s.session = { ...s.session!, car_name: "Ferrari" };
    expect(model(s, { driver: jo(best("Other car")), nowS }).ready?.target.yourBest).toEqual({
      text: "1:30.986",
      status: "neutral",
      tag: null,
      date: "3 Oct · any car",
      anyCar: true,
    });
    expect(model(s, { driver: jo(best("Ferrari")), nowS }).ready?.target.yourBest).toMatchObject({
      status: "neutral",
      date: "3 Oct",
      anyCar: false,
    });
    // D2 without a driver best for this car: the same neutral stand-in, never PB
    const d2 = asLive(fixture("edited-d1-d6"));
    d2.frame = { ...d2.frame!, pit_status: 2 };
    d2.session = { ...d2.session!, car_name: "Ferrari" };
    d2.bests = { ...d2.bests!, driver: null };
    expect(model(d2, { driver: jo(best("Other car", 96000)), nowS }).ready?.target.yourBest).toMatchObject({
      text: "1:36.000",
      status: "neutral",
      tag: null,
      anyCar: true,
    });
  });

  it("garage between runs leads with the last run and one thing for the next run", () => {
    const m = model(fixture("edited-garage-between-runs"));
    expect(m.ready).toMatchObject({
      phase: "between_runs",
      lastRun: {
        best: { text: "1:37.037", lapNumber: 4 },
        clean: 2,
        total: 4,
        cleanText: "2 of 4 clean",
        gainedText: "0.15 s faster",
        gained: { amount: "0.15 s", word: "faster" },
      },
      today: { focus: [{ name: "T7", label: "T11", officialName: "Hairpin", reason: "braking early · 1 of the last 1 lap" }] },
    });
    expect(m.ready?.nextRun?.text).toMatch(/^Turn 9 \(Degner 2\)/);
    expect(m.ready?.footer).toBe(`5${THIN}809 m · S2 2${THIN}226 m · S3 4${THIN}690 m · 11 corners learned · names: verified track sheet`);
  });

  it("names the household record and its holder with D2", () => {
    const s = fixture("edited-d1-d6");
    s.connection = { ...s.connection, source: "udp:20777" };
    s.frame = { ...s.frame!, pit_status: 2 };
    const jo = driver({ id: 2, name: "Jo", preferences: { colour: "#ffb020", initials: "JO", skill_level: "intermediate", coaching_intensity: "normal", voice_enabled: true } });
    const m = model(s, { drivers: [driver(), jo] });
    expect(m.ready?.target.record).toMatchObject({ text: "1:36.100", status: "rec", tag: "REC", holder: "Jo", holderInitials: "JO" });
    expect(m.ready?.target.yourBest).toMatchObject({ text: "1:36.500", status: "pb", tag: "PB", anyCar: false });
  });
});

describe("driveModel: Session complete with D2", () => {
  it("shows the gaps to your best and the family record, or that this session set them", () => {
    const s = fixture("edited-d1-d6");
    s.connection = { ...s.connection, source: "udp:20777" };
    s.session_state = "ended";
    const jo = driver({ id: 2, name: "Jo" });
    const m = model(s, { drivers: [driver(), jo] });
    expect(m.state).toBe("ended");
    expect(m.ended).toMatchObject({
      best: { text: "1:37.037", status: "sb", tag: "SB", sub: "lap 4" },
      toYourBest: { text: "0.537 s slower", amount: "0.537 s", word: "slower", sub: "1:36.500" },
      toRecord: { text: "0.937 s slower", amount: "0.937 s", word: "slower", sub: "Jo · 1:36.100" },
    });
    s.bests = { ...s.bests!, driver: { ...s.bests!.driver!, lap_ms: 97037, lap_id: s.laps[0]!.lap_id } };
    expect(model(s, { drivers: [driver(), jo] }).ended).toMatchObject({
      best: { status: "pb", tag: "PB", sub: "lap 4 · new personal best" },
      toYourBest: { text: "PB", amount: null, sub: "this session set it" },
      toRecord: { text: "0.937 s slower" },
    });
  });
});

describe("driveModel: the AI field's heads-ups are an AI reference, never the driver's focus", () => {
  /** Every string the Coach screen prints from the model (not the keys it matches on). */
  function printed(m: ReturnType<typeof model>): string {
    const { corner: _c, ...hero } = m.hero as { corner?: unknown };
    const cue = { note: m.cue.note, next: m.cue.next && { chip: m.cue.next.chip, text: m.cue.next.text, inText: m.cue.next.inText } };
    return JSON.stringify([hero, cue, m.ready?.today, m.ribbon.corners.filter((c) => c.showLabel).map((c) => c.label)]);
  }

  it("on track with a learned model: no FOCUS chip, the call labelled AI REF, no notches", () => {
    const m = model(fixture("edited-ai-field-suzuka"));
    expect(m.hero).toMatchObject({ kind: "corner", label: "T11", name: "Hairpin", focus: false, focusReason: null });
    expect(m.cue).toMatchObject({ ai: true, next: { chip: "AI REF", text: "heavy braking ahead", inText: "335 m" } });
    expect(m.ribbon.cueNotches).toEqual([]);
    expect(m.ribbon.corners.some((c) => c.focus)).toBe(false);
    expect(printed(m)).not.toMatch(/zone@|\bF\d+\b/);
  });

  it("in the garage: no focus corners on the Ready card, the calls line says AI reference, no raw keys", () => {
    for (const name of ["edited-ai-field-suzuka", "edited-ai-field-monza"]) {
      const s = fixture(name);
      s.frame = { ...s.frame!, pit_status: 2 };
      const m = model(s);
      expect(m.card, name).toBe("ready");
      expect(m.ready?.today, name).toEqual({ focus: [], callsMode: "Braking calls: AI reference (heavy braking ahead)" });
      expect(printed(m), name).not.toMatch(/zone@|\bF\d+\b/);
    }
  });

  it("first session at a track (no model): the band says AI reference, never the key", () => {
    const m = model(fixture("edited-ai-field-monza"));
    expect(m.hero).toMatchObject({ kind: "empty", text: "Corners appear after your first clean lap" });
    expect(m.cue).toMatchObject({ ai: true, next: null, note: "AI reference: heavy braking ahead · 1.0 km" });
    expect(printed(m)).not.toMatch(/zone@|\bF\d+\b/);
  });

  it("the driver's own plan keeps its FOCUS chip and focus list", () => {
    const m = model(fixture("recorded-suzuka-on-track-brake-ahead"));
    expect(m.hero).toMatchObject({ focus: true });
    expect(m.cue.ai).toBe(false);
  });
});

describe("driveModel: overlays and D-additions", () => {
  it("safety car: amber band, muted delta with SC, calls paused", () => {
    const m = model(fixture("edited-safety-car"));
    expect(m.status).toMatchObject({ band: "sc", text: "SAFETY CAR", sub: "calls paused" });
    expect(m.delta).toMatchObject({ tone: "muted", chip: "SC" });
    expect(m.cue.note).toBe("Calls paused: safety car");
  });

  it("flashback in a yellow zone: yellow band plus the incident chip (real Austria)", () => {
    const m = model(fixture("recorded-austria-flashback"));
    expect(m.status).toMatchObject({ band: "yellow", text: "YELLOW FLAG · SECTOR 2 · ZONE 7", sub: "in this zone" });
    expect(m.status.chip).toEqual({ kind: "flashback", text: "FLASHBACK · lap won't count" });
    expect(m.ribbon.yellow).toHaveLength(1);
  });

  it("synthetic data is labelled", () => {
    expect(model(fixture("synthetic-demo-on-track-brake-ahead")).status.evidence).toEqual({ synthetic: true, replay: true });
  });

  it("chequered flag: band while the last lap runs, then the Session complete card", () => {
    const s = fixture("recorded-d246-suzuka-chequered-flag");
    const m1 = model(s);
    expect(m1).toMatchObject({ state: "on_track", status: { band: "chequered", text: "CHEQUERED FLAG", sub: "last lap" } });
    const crossed = structuredClone(s);
    crossed.frame = { ...crossed.frame!, lap_number: 6, lap_distance_m: 30, current_lap_time_ms: 1000 };
    const m2 = model(crossed, { memo: m1.memo });
    expect(m2).toMatchObject({ state: "ended", card: "ended", status: { text: "CHEQUERED FLAG" } });
  });

  it("with D2/D4/D6 shows the radio's point (short text); tier 2 timing only with driver or household bests", () => {
    const m = model(fixture("recorded-d246-suzuka-on-track-brake-ahead"));
    expect(m.coach).toMatchObject({ source: "d6", size: 30, tagText: "Work on · last lap" });
    expect(m.coach.text!.length).toBeLessThanOrEqual(48);
    expect(m.tier).toBe(1); // a replay: D2 keeps no records for it
    const live = model(asLive(fixture("edited-d1-d6")));
    expect(live.tier).toBe(2);
    expect(live.legend).toBe("REC family record · PB your best ever · SB your best today");
  });

  it("D1 sectors show the lap in progress", () => {
    const s = asLive(fixture("edited-d1-d6"));
    s.bests = { ...s.bests!, driver: null, household: null };
    const m = model(s);
    expect(m.sectors.source).toBe("current");
    expect(m.sectors.cells.map((c) => c.status)).toEqual(["sb", "running", "future"]);
  });

  it("never invents a corner: GT7's runaway distance and an empty model say why", () => {
    expect(model(fixture("recorded-live-api-gt7-stale")).hero).toMatchObject({ kind: "empty", text: "Position on the lap unknown" });
    expect(model(fixture("recorded-monza-invalid-lap")).hero).toMatchObject({
      kind: "empty",
      text: "Corners appear after your first clean lap",
    });
  });

  it("is stable for an unchanged memo", () => {
    const s = fixture("recorded-suzuka-on-track-brake-ahead");
    const m1 = model(s, { memo: EMPTY_MEMO });
    expect(model(s, { memo: m1.memo }).memo).toBe(m1.memo);
  });

  it("takes the live store's snapshot as it is (no cast needed: every addition is optional)", () => {
    const fromStore: SnapshotNext | null = live.get().snap; // compile-time check
    expect(driveModel({ snap: fromStore, connected: live.get().connected, nowS: 0, driver: null }).state).toBe("offline");
  });

  it("handles the empty snapshot", () => {
    const m = model(null);
    expect(m.state).toBe("no_data");
    expect(m.hero).toEqual({ kind: "card" });
    expect(m.ready).toBeNull();
    expect(m.ended).toBeNull();
    expect(model(snap({ frame: null })).card).toBe("ready");
  });
});
