// Settings › Drivers with race radio (pitwall.raceradio; race-radio spec 9.5, 10.4): the seven call toggles and the
// radio words in the driver form, offered only by a server that knows them (older servers refuse unknown fields).

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import {
  ALL_RADIO_CALLS,
  PALETTE,
  RADIO_CALL_GROUPS,
  RADIO_WORDINGS,
  radioCallsOf,
  radioWordingOf,
  raceRadioSupported,
  type CoachingLimits,
  type Driver,
} from "../../../lib/drivers";
import { formBody, formFromDriver, newDriverForm, radioWordingHint, withRadioCall } from "./model";
import { RADIO_CALLS_ELSEWHERE, RaceRadioSettings } from "./RaceRadioSettings";

const LIMITS: CoachingLimits = {
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
  corner_repeat_gap_laps: 1,
};

function driver(id: number, name: string, prefs: Partial<Driver["preferences"]> = {}): Driver {
  return {
    id,
    name,
    created_unix: id * 100,
    preferences: {
      colour: PALETTE[id % PALETTE.length] ?? "#ff6a2b",
      initials: name.slice(0, 2).toUpperCase(),
      skill_level: "beginner",
      coaching_intensity: "normal",
      voice_enabled: true,
      ...prefs,
    },
    coaching: LIMITS,
    active: false,
    stats: { sessions: 0, laps: 0, clean_laps: 0, tracks: 0, last_session_unix: null, best_laps: [] },
  };
}

/** A profile as a server with race radio sends it (drivers.py DriverPreferences.to_dict). */
const withRadio = (id: number, name: string, prefs: Partial<Driver["preferences"]> = {}) =>
  driver(id, name, { radio_calls: { ...ALL_RADIO_CALLS }, radio_wording: "auto", ...prefs });

describe("the toggles and words as stored", () => {
  it("seven groups in the sheet's order, every one on by default", () => {
    expect(RADIO_CALL_GROUPS.map((g) => g.value)).toEqual(["flags", "start", "position", "rivals", "penalties", "damage", "name"]);
    expect(Object.values(ALL_RADIO_CALLS).every((v) => v === true)).toBe(true);
    expect(RADIO_CALL_GROUPS.find((g) => g.value === "flags")?.hint).toBe("Yellow, blue, safety car. Red flags are always on. F1 only.");
    expect(RADIO_CALL_GROUPS.find((g) => g.value === "name")).toMatchObject({ label: "Say my name sometimes", hint: "At most once a minute." });
    expect(RADIO_WORDINGS.map((w) => w.label)).toEqual(["Automatic", "Simple", "Standard"]);
  });

  it("reads leniently like the server: a missing or non-boolean value is on, unknown keys are ignored", () => {
    expect(radioCallsOf({ rivals: false, damage: "no", extra: false })).toEqual({ ...ALL_RADIO_CALLS, rivals: false });
    expect(radioCallsOf(undefined)).toEqual(ALL_RADIO_CALLS);
    expect(radioCallsOf([false])).toEqual(ALL_RADIO_CALLS);
    expect(radioWordingOf("simple")).toBe("simple");
    expect(radioWordingOf("standard")).toBe("standard");
    expect(radioWordingOf("plain")).toBe("auto");
    expect(radioWordingOf(undefined)).toBe("auto");
  });

  it("support is known from a profile the server sent", () => {
    expect(raceRadioSupported([driver(1, "Sam"), driver(2, "Alex")])).toBe(false);
    expect(raceRadioSupported([driver(1, "Sam"), withRadio(2, "Alex")])).toBe(true);
    expect(raceRadioSupported([driver(1, "Sam", { radio_wording: "simple" })])).toBe(true);
    expect(raceRadioSupported([])).toBe(false);
  });
});

describe("the driver form", () => {
  it("an older server: nothing offered, nothing sent (it refuses unknown fields)", () => {
    const list = [driver(1, "Sam")];
    const fresh = newDriverForm(list);
    expect(fresh.radio_calls).toBeUndefined();
    expect(fresh.radio_wording).toBeUndefined();
    const edit = formFromDriver(list[0]!);
    expect(edit.radio_calls).toBeUndefined();
    const body = formBody({ ...edit, name: "Sam" });
    expect(body.ok && "radio_calls" in body.body).toBe(false);
    expect(body.ok && "radio_wording" in body.body).toBe(false);
  });

  it("a new driver on a server with race radio: every call on, automatic words", () => {
    const f = newDriverForm([withRadio(1, "Sam")]);
    expect(f.radio_calls).toEqual(ALL_RADIO_CALLS);
    expect(f.radio_wording).toBe("auto");
    const r = formBody({ ...f, name: "Mia" });
    expect(r).toMatchObject({ ok: true, body: { radio_calls: ALL_RADIO_CALLS, radio_wording: "auto" } });
  });

  it("editing keeps the stored choices; missing ones read as their default", () => {
    const d = withRadio(1, "Sam", { radio_calls: { ...ALL_RADIO_CALLS, rivals: false, name: false }, radio_wording: "simple" });
    const f = formFromDriver(d);
    expect(f.radio_calls).toEqual({ ...ALL_RADIO_CALLS, rivals: false, name: false });
    expect(f.radio_wording).toBe("simple");
    const partial = formFromDriver(driver(2, "Alex", { radio_calls: { damage: false } as never }));
    expect(partial.radio_calls).toEqual({ ...ALL_RADIO_CALLS, damage: false });
    expect(partial.radio_wording).toBe("auto");
  });

  it("toggling one group changes only that group, and the form is never shared with the profile", () => {
    const d = withRadio(1, "Sam");
    const f = formFromDriver(d);
    const g = withRadioCall(f, "damage", false);
    expect(g.radio_calls).toEqual({ ...ALL_RADIO_CALLS, damage: false });
    expect(f.radio_calls).toEqual(ALL_RADIO_CALLS);
    expect(d.preferences.radio_calls).toEqual(ALL_RADIO_CALLS);
    const r = formBody(g);
    expect(r.ok && r.body.radio_calls).toEqual({ ...ALL_RADIO_CALLS, damage: false });
    expect(r.ok && r.body.radio_calls).not.toBe(g.radio_calls);
    // a form without race radio is returned as it is
    const old = formFromDriver(driver(3, "Kim"));
    expect(withRadioCall(old, "damage", false)).toBe(old);
  });

  it("the words hint shows an example, says what Automatic means for this driver, and that coaching follows", () => {
    expect(radioWordingHint("auto", "beginner")).toBe(
      'This driver is a beginner, so simple words: "You\'re up to 5th." Also for coaching and strategy calls.',
    );
    expect(radioWordingHint("auto", "advanced")).toBe(
      'Race-engineer words for this driver\'s level: "Up to P5." Beginners get simple words. Also for coaching and strategy calls.',
    );
    expect(radioWordingHint("simple", "advanced")).toMatch(/^Simple words, one idea at a time: "You're up to 5th\."/);
    expect(radioWordingHint("standard", "beginner")).toMatch(/^Race-engineer words: "Up to P5\."/);
    for (const w of ["auto", "simple", "standard"] as const) {
      expect(radioWordingHint(w, "beginner")).not.toMatch(/\((simple|standard) words for/); // never circular
    }
  });

  it("the four F1-only groups say so; start and position work in every game", () => {
    const f1Only = RADIO_CALL_GROUPS.filter((g) => g.hint?.endsWith("F1 only.")).map((g) => g.value);
    expect(f1Only).toEqual(["flags", "rivals", "penalties", "damage"]);
  });
});

describe("RaceRadioSettings (static markup)", () => {
  const render = (wording: "auto" | "simple" | "standard" = "auto") =>
    renderToStaticMarkup(createElement(RaceRadioSettings, { wording, skill: "beginner", onWording: vi.fn() }));

  it("the words with Automatic's hint, and where the race calls are now (one place: Settings › Radio & voice)", () => {
    const html = render();
    for (const w of RADIO_WORDINGS) expect(html).toContain(`>${w.label}<`);
    expect(html).toContain("This driver is a beginner, so simple words");
    expect(html).toContain(RADIO_CALLS_ELSEWHERE.replace("&", "&amp;"));
    for (const g of RADIO_CALL_GROUPS) expect(html).not.toContain(g.label.replace("&", "&amp;")); // no toggles here
    expect(html).not.toContain('checked=""');
  });

  it("never prints raw unknowns", () => {
    const html = render();
    expect(html).not.toMatch(/undefined|null|NaN/);
  });
});
