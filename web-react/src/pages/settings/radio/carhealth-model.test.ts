// Settings › Radio & voice, "Car health calls" (lane "health", spec 3.13 D5): the view model in every state, and the
// card rendered to static markup in plain node (like render.test.ts): loading, an older server, a load error, the
// settings, a save in flight, a failed save; switches never drawn as off while the value is unknown.
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../../../lib/api";
import { settingsFixture } from "../../../lib/carhealth/testkit";
import { DEFAULT_CAR_HEALTH_SETTINGS } from "../../../lib/carhealth/view";
import { CarHealthError } from "../../../lib/endpoints/carhealth";
import { CarHealthCardView, type CarHealthCardViewProps } from "./CarHealthCard";
import { CARD_HELP, carHealthCardView, SLIP_CHOICES, SLIP_RULE, TOGGLES, withChange } from "./carhealth-model";

const READY = { data: DEFAULT_CAR_HEALTH_SETTINGS, loadError: null, saving: false, saveError: null };

describe("Car health calls: view model", () => {
  it("ready: the settings, editable, the slip hint follows the choice", () => {
    const v = carHealthCardView(READY);
    expect(v).toMatchObject({ state: "ready", editable: true, note: null, saveError: null });
    expect(v.slipHint).toBe("Only when Coaching is on Detailed.");
    expect(carHealthCardView({ ...READY, data: { ...READY.data, slip_calls: "off" } }).slipHint).toMatch(/^Never on the radio/);
    expect(carHealthCardView({ ...READY, data: { ...READY.data, slip_calls: "normal" } }).slipHint).toBe("At Normal coaching too.");
  });

  it("loading, an older server, a load error: no settings (never guessed), one row says why", () => {
    expect(carHealthCardView({ ...READY, data: undefined })).toMatchObject({ state: "loading", settings: null, note: "Loading from the Mac…" });
    expect(carHealthCardView({ ...READY, data: undefined, loadError: new ApiError(404, "Not Found") })).toMatchObject({
      state: "missing",
      retry: false,
      note: "This Pitwall server doesn't have car health calls yet: update Pitwall on the Mac.",
    });
    expect(carHealthCardView({ ...READY, data: undefined, loadError: new CarHealthError(500, "database is locked") })).toMatchObject({
      state: "error",
      retry: true,
      noteTone: "warning",
      note: "Couldn't load: database is locked",
    });
  });

  it("a save in flight locks the rows; a failed save says why", () => {
    expect(carHealthCardView({ ...READY, saving: true }).editable).toBe(false);
    expect(carHealthCardView({ ...READY, saveError: "slip_calls must be off, detailed or normal" }).saveError).toBe(
      "Couldn't save: slip_calls must be off, detailed or normal",
    );
  });

  it("a change keeps the other three (the card always sends all four)", () => {
    const q = settingsFixture("edited-settings-quiet");
    expect(withChange(q, { tyre_calls: false })).toEqual({ ...q, tyre_calls: false });
    expect(SLIP_CHOICES.map((c) => c.label)).toEqual(["Off", "Detailed radio only", "Always"]);
    expect(TOGGLES.map((t) => t.key)).toEqual(["tyre_calls", "wear_calls", "fuel_calls"]);
  });

  it("no hint recommends braking later", () => {
    for (const t of [...TOGGLES.map((x) => x.hint), ...SLIP_CHOICES.map((x) => x.hint), CARD_HELP, SLIP_RULE]) {
      expect(t).not.toMatch(/brake\w* (?:a (?:bit|little) )?later|later on the brakes|brake deeper/i);
    }
  });
});

function render(over: Partial<CarHealthCardViewProps> = {}): string {
  return renderToStaticMarkup(
    createElement(CarHealthCardView, { ...READY, onChange: vi.fn(), onRetry: vi.fn(), ...over }),
  );
}

const text = (m: string): string =>
  m
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ");

describe("Car health calls: the card", () => {
  it("ready: three switches and the three-way choice, the help under them", () => {
    const m = render({ data: settingsFixture("edited-settings-quiet") });
    const t = text(m);
    for (const w of ["Car health calls", "Tyre temperature calls", "Tyre wear calls", "Fuel calls", "Lock-up and wheelspin notes"]) {
      expect(t).toContain(w);
    }
    expect(t).toContain(`${CARD_HELP} ${SLIP_RULE}`);
    expect(m.match(/role="switch"/g)).toHaveLength(3);
    // tyre on, wear off, fuel off
    expect([...m.matchAll(/<input[^>]*role="switch"[^>]*>/g)].map((x) => /checked=""/.test(x[0]))).toEqual([true, false, false]);
    expect(m.match(/<button[^>]*role="radio"[^>]*aria-checked="true"[^>]*>.*?<\/button>/g)?.join(" ")).toContain(">Always<");
    expect(t).toContain("At Normal coaching too.");
  });

  it("loading: no switches drawn (unknown is never 'off')", () => {
    const m = render({ data: undefined });
    expect(m).not.toContain('role="switch"');
    expect(text(m)).toContain("Loading from the Mac…");
  });

  it("a load error offers Try again; an older server just says so", () => {
    const err = render({ data: undefined, loadError: new CarHealthError(500, "database is locked") });
    expect(text(err)).toContain("Couldn't load: database is locked");
    expect(text(err)).toContain("Try again");
    const old = render({ data: undefined, loadError: new ApiError(404, "Not Found") });
    expect(text(old)).toContain("doesn't have car health calls yet");
    expect(text(old)).not.toContain("Try again");
  });

  it("saving locks the rows; a failed save is announced", () => {
    const m = render({ saving: true });
    const switches = [...m.matchAll(/<input[^>]*role="switch"[^>]*>/g)].map((x) => x[0]);
    expect(switches).toHaveLength(3);
    for (const sw of switches) expect(sw).toContain('disabled=""');
    expect(render({}).match(/<input[^>]*disabled=""[^>]*role="switch"/g)).toBeNull();
    const bad = render({ saveError: "slip_calls must be off, detailed or normal" });
    expect(bad).toMatch(/role="alert"[^>]*>Couldn&#x27;t save: slip_calls must be off, detailed or normal/);
  });
});
