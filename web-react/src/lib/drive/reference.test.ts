import { describe, expect, it } from "vitest";
import { crFixture, withLive } from "../../test/coachref";
import type { RefOptionsResponse } from "../endpoints/coachref";
import { deltaView } from "./delta";
import {
  LOCKED_HINT,
  QUALITY_NOT_RACING,
  QUALITY_PAUSED,
  appliesNotice,
  beginnerText,
  choiceRequest,
  onlyHereDefault,
  pickerRows,
  refControlView,
  refPickerLocked,
} from "./reference";
import { NO_OVERLAYS } from "./state";
import { driver, fixture, frame, snap } from "./testkit";

const NOW = 1791140400 + 3600; // the day Sam's best was not set (it reads "3 Oct"-style dates, not "today")
const SAM = driver({ id: 2, name: "Sam", preferences: { colour: "#22c55e", initials: "SM", skill_level: "intermediate", coaching_intensity: "normal", voice_enabled: true } });
const JAMES = driver({ id: 1, name: "James" });

describe("moving lock (spec 10.1)", () => {
  it("is shut while live on track at speed or with the speed unknown", () => {
    expect(refPickerLocked(snap({ frame: frame({ speed_kph: 250 }) }))).toBe(true);
    expect(refPickerLocked(snap({ frame: frame({ speed_kph: 30 }) }))).toBe(true);
    expect(refPickerLocked(snap({ frame: frame({ speed_kph: null }) }))).toBe(true); // unknown is not assumed stopped
    expect(refPickerLocked(snap({ frame: null }))).toBe(true);
  });

  it("opens when stopped, in the pit lane or garage, paused, out of the race, or without live telemetry", () => {
    expect(refPickerLocked(snap({ frame: frame({ speed_kph: 29.9 }) }))).toBe(false);
    expect(refPickerLocked(snap({ frame: frame({ speed_kph: 80, pit_status: 1 }) }))).toBe(false);
    expect(refPickerLocked(snap({ frame: frame({ speed_kph: 0, pit_status: 2 }) }))).toBe(false);
    expect(refPickerLocked(snap({ frame: { ...frame({ speed_kph: 200 }), quality: QUALITY_PAUSED } }))).toBe(false);
    expect(refPickerLocked(snap({ frame: { ...frame({ speed_kph: 200 }), quality: QUALITY_NOT_RACING } }))).toBe(false);
    const stale = snap();
    stale.connection = { ...stale.connection, status: "stale" };
    expect(refPickerLocked(stale)).toBe(false);
    expect(refPickerLocked(null)).toBe(false);
  });
});

describe("the reference control (spec 10.1, 10.2)", () => {
  it("a server without coachref: unavailable, so the delta panel keeps its plain label", () => {
    const v = refControlView(fixture("recorded-d246-suzuka-on-track-brake-ahead"), { beginner: false });
    expect(v.available).toBe(false);
  });

  it("your own best (the default): 'Delta to · Your best', no holder, no braking note", () => {
    const v = refControlView(withLive(fixture("recorded-d246-suzuka-on-track-brake-ahead"), "live-own"), { beginner: false });
    expect(v).toMatchObject({ available: true, text: "Delta to · Your best", label: "Your best", own: true, holder: null, brakeNote: null, reason: null });
  });

  it("another driver's best: their name, their initials from the profile, the braking note", () => {
    const s = withLive(fixture("recorded-d246-suzuka-on-track-brake-ahead"), "live-sam");
    const v = refControlView(s, { beginner: false, drivers: [JAMES, SAM] });
    expect(v).toMatchObject({
      text: "Delta to · Sam's best",
      label: "Sam's best",
      own: false,
      holder: { name: "Sam", initials: "SM", colour: "#22c55e" },
      brakeNote: "Braking calls use your own braking points where Sam brakes later",
      driverId: 1,
      trackName: "Suzuka",
    });
    // The chip dates the lap from the descriptor (another session): never "today", never "another session".
    const d = deltaView(s, "on_track", NO_OVERLAYS, false, { nowS: NOW });
    expect(d.refLabel).toMatch(/^Lap 3 · 1:30\.412 · \d{1,2} [A-Z][a-z]{2}( \d{4})?$/);
  });

  it("without a profile the initials come from the name the server sent", () => {
    const v = refControlView(withLive(fixture("recorded-d246-suzuka-on-track-brake-ahead"), "live-sam"), { beginner: false });
    expect(v.holder).toEqual({ name: "Sam", initials: "SA", colour: null });
  });

  it("beginners: 'vs your target lap' for their own lap, else 'vs Sam's best lap'", () => {
    const own = refControlView(withLive(fixture("recorded-d246-suzuka-on-track-brake-ahead"), "live-own"), { beginner: true });
    expect(own.text).toBe("vs your target lap");
    const sam = refControlView(withLive(fixture("recorded-d246-suzuka-on-track-brake-ahead"), "live-sam"), { beginner: true });
    expect(sam.text).toBe("vs Sam's best lap");
    expect(beginnerText("household_best", false, "the family record", "Family record · Sam")).toBe("vs the family record lap");
    expect(beginnerText("lap", false, "Sam's lap", "Sam · lap 7 · 3 Oct")).toBe("vs Sam's lap");
  });

  it("a choice that could not be used says why, and that your best is used instead", () => {
    const v = refControlView(withLive(fixture("recorded-d246-suzuka-on-track-brake-ahead"), "live-fallback"), { beginner: false });
    expect(v.text).toBe("Delta to · Your best");
    expect(v.own).toBe(true);
    expect(v.reason).toBe("Jo's laps here used a different braking assist: using your best");
    expect(v.brakeNote).toBeNull();
  });

  it("before the first lap (no reference yet) the choice names it", () => {
    const s = withLive(fixture("recorded-d246-suzuka-grid-before-start"), "live-sam");
    s.reference = null;
    const v = refControlView(s, { beginner: false });
    expect(v).toMatchObject({ text: "Delta to · Sam's best", own: false, holder: null, brakeNote: null });
    // Not "your first clean lap becomes the reference": Sam's lap is used once the first lap is in.
    expect(v.waiting).toBe("Sam's best from the end of your first lap");
    const d = deltaView(s, "on_track", NO_OVERLAYS, false, { nowS: NOW });
    expect(d.reason).toBe("No reference yet: Sam's best from your next lap");
    // Your own best (the default) keeps today's words.
    const own = withLive(fixture("recorded-d246-suzuka-grid-before-start"), "live-own");
    own.reference = null;
    expect(refControlView(own, { beginner: false }).waiting).toBeNull();
    expect(deltaView(own, "on_track", NO_OVERLAYS, false).reason).toBe("No reference yet: your first clean lap becomes the reference");
  });

  it("pending and frozen are flagged; moving with another driver's lap offers only 'Back to your best'", () => {
    const s = withLive(fixture("recorded-d246-suzuka-on-track-brake-ahead"), "live-drill");
    s.coachref!.pending = true;
    const v = refControlView(s, { beginner: false });
    expect(v.pending).toBe(true);
    expect(v.frozen).toBe(true);
    expect(v.locked).toBe(true); // 122 km/h on track
    expect(v.backToBest).toEqual({ driver_id: 1, kind: "own_best", scope: "all_tracks" });
    expect(v.ariaHint).toBe(`from next lap, held for the drill, ${LOCKED_HINT.toLowerCase()}`);
    // Your own best while moving: nothing to offer (the status slot hint instead).
    const own = refControlView(withLive(fixture("recorded-d246-suzuka-on-track-brake-ahead"), "live-own"), { beginner: false });
    expect(own.locked).toBe(true);
    expect(own.backToBest).toBeNull();
    // A per-track choice goes back to your best at that track only.
    const t = withLive(fixture("recorded-d246-suzuka-on-track-brake-ahead"), "live-sam");
    t.coachref!.choice = { ...t.coachref!.choice!, scope: "track", game: "f1_25", track_id: "f1:13" };
    expect(refControlView(t, { beginner: false }).backToBest).toEqual({
      driver_id: 1,
      kind: "own_best",
      scope: "track",
      game: "f1_25",
      track_id: "f1:13",
    });
  });
});

describe("picker rows (spec 10.1)", () => {
  it("your best, the family record (with its holder), each driver's best, then the saved laps", () => {
    const r = crFixture<RefOptionsResponse>("options-suzuka-sam");
    const { main, laps } = pickerRows(r, NOW, [JAMES, SAM]);
    expect(main.map((x) => x.title)).toEqual(["Your best", "Family record", "Jo's best", "Sam's best"]);
    expect(main[0]).toMatchObject({ key: "own_best", detail: expect.stringMatching(/^1:30\.986 · /), disabled: false, holder: null });
    expect(main[1]).toMatchObject({ key: "household_best", detail: "1:30.412 · Sam", holder: { initials: "SM" } });
    expect(main[2]).toMatchObject({
      key: "driver_best:3",
      disabled: true,
      reason: "Jo's laps here used a different braking assist",
      detail: null,
    });
    expect(main[3]).toMatchObject({ key: "driver_best:2", selected: true, warnings: ["Different tyre compound (soft vs medium)"] });
    expect(laps.map((x) => x.key)).toEqual(["lap:812", "lap:790"]);
    expect(laps[1]?.holder).toBeNull(); // your own saved lap
    expect(onlyHereDefault(r)).toBe(false);
  });

  it("a game whose car is unknown: other drivers' laps listed, disabled, with the reason (not supported here)", () => {
    const { main } = pickerRows(crFixture<RefOptionsResponse>("options-gt7-unknown-car"), NOW, []);
    expect(main.filter((x) => x.disabled).map((x) => x.reason)).toEqual([
      "the car is unknown, so other drivers' laps can't be matched",
      "the car is unknown, so other drivers' laps can't be matched",
    ]);
    expect(main[0]).toMatchObject({ key: "own_best", disabled: false, selected: true, detail: "none here yet" });
  });

  it("no live session: nothing to check against, so nothing is disabled", () => {
    const { main } = pickerRows(crFixture<RefOptionsResponse>("options-no-live-session"), NOW, []);
    expect(main.every((x) => !x.disabled && x.reason === null)).toBe(true);
  });

  it("the PUT body: all tracks by default, this track with 'Only at', a saved lap always per track", () => {
    const r = crFixture<RefOptionsResponse>("options-suzuka-sam");
    const { main, laps } = pickerRows(r, NOW, []);
    const sam = main.find((x) => x.key === "driver_best:2")!;
    expect(choiceRequest(sam, false, r)).toEqual({ driver_id: 1, kind: "driver_best", target_driver_id: 2, scope: "all_tracks" });
    expect(choiceRequest(sam, true, r)).toEqual({
      driver_id: 1,
      kind: "driver_best",
      target_driver_id: 2,
      scope: "track",
      game: "f1_25",
      track_id: "f1:13",
    });
    expect(choiceRequest(laps[0]!, true, r)).toEqual({ driver_id: 1, kind: "lap", lap_id: 812 });
    expect(choiceRequest(main[0]!, false, r)).toEqual({ driver_id: 1, kind: "own_best", scope: "all_tracks" });
  });

  it("what the status slot says after a change (spec 10.8 copy)", () => {
    expect(appliesNotice("now", "driver_best", "Sam's best")).toBeNull();
    expect(appliesNotice("next_lap", "driver_best", "Sam's best")).toBe("Delta to Sam's best from the next lap");
    expect(appliesNotice("after_drill", "driver_best", "Sam's best")).toBe("Delta to Sam's best after the drill");
    expect(appliesNotice("next_lap", "own_best", "Your best")).toBe("Delta to your best from the next lap");
    expect(appliesNotice("next_session", "household_best", "Family record")).toBe("Delta to the family record from your next session");
  });
});
