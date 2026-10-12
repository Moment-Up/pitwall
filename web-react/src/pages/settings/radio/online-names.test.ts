// Settings › Radio & voice, race radio P2 (race-radio spec 8.3, 10.5): "Say online players' names", a household
// setting on the Mac (GET/PUT /api/race/settings), off by default and hidden on a server without it.

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../../../lib/api";
import { RadioVoiceView, type RadioActions, type RadioVoiceViewProps } from "./RadioVoiceView";
import { ONLINE_NAMES_HINT, ONLINE_NAMES_TITLE, onlineNamesView } from "./model";

const MISSING = new ApiError(404, "Not Found"); // FastAPI's own: the route does not exist
const DOWN = new Error("Failed to fetch");

describe("onlineNamesView", () => {
  it("a server without the setting: no row", () => {
    expect(onlineNamesView({ data: undefined, error: MISSING, saving: false, saveError: null }).shown).toBe(false);
  });

  it("while it loads: shown, nothing selected, locked", () => {
    expect(onlineNamesView({ data: undefined, error: null, saving: false, saveError: null })).toEqual({
      shown: true,
      value: null,
      disabled: true,
      hint: "Reading the Mac's setting…",
      warn: false,
    });
  });

  it("unknown after an error: never guessed, says so", () => {
    expect(onlineNamesView({ data: undefined, error: DOWN, saving: false, saveError: null })).toMatchObject({
      shown: true,
      value: null,
      disabled: true,
      hint: "Unknown: the Mac has not answered.",
      warn: true,
    });
  });

  it("the stored value with the promise about names; locked while saving", () => {
    expect(onlineNamesView({ data: { online_names: false }, error: null, saving: false, saveError: null })).toEqual({
      shown: true,
      value: false,
      disabled: false,
      hint: ONLINE_NAMES_HINT,
      warn: false,
    });
    expect(onlineNamesView({ data: { online_names: true }, error: null, saving: true, saveError: null })).toMatchObject({
      value: true,
      disabled: true,
    });
  });

  it("a refused change says it was not saved and keeps the stored value", () => {
    expect(
      onlineNamesView({ data: { online_names: false }, error: null, saving: false, saveError: "422: not allowed" }),
    ).toMatchObject({ shown: true, value: false, disabled: false, hint: "Not saved: 422: not allowed", warn: true });
  });

  it("stale data stays on screen after a failed refresh", () => {
    expect(onlineNamesView({ data: { online_names: true }, error: DOWN, saving: false, saveError: null })).toMatchObject({
      value: true,
      disabled: false,
      hint: ONLINE_NAMES_HINT,
    });
  });

  it("the copy promises what the backend does", () => {
    expect(ONLINE_NAMES_TITLE).toBe("Say online players' names");
    expect(ONLINE_NAMES_HINT).toBe("Only when you ask who's ahead or behind. Names are never saved or written to logs.");
  });
});

describe("the row on Settings › Radio & voice", () => {
  const actions = (): RadioActions => ({
    setVoiceEnabled: vi.fn(),
    setIntensity: vi.fn(),
    setCueMode: vi.fn(),
    setVoiceSource: vi.fn(),
    setServerVoice: vi.fn(),
    testServerVoice: vi.fn(),
    setDeviceVoice: vi.fn(),
    setDeviceRate: vi.fn(),
    testDeviceVoice: vi.fn(),
  });

  function render(over: Partial<RadioVoiceViewProps> = {}): string {
    const props: RadioVoiceViewProps = {
      r: {
        phase: "idle",
        conn: "offline",
        retryInS: null,
        error: null,
        server: null,
        settings: { voiceEnabled: true, intensity: "normal", voiceSource: "server", deviceVoice: null, deviceRate: 1, version: 2 },
        deviceVoices: [],
        deviceTtsCapable: true,
        micCapable: true,
        serverVoiceTest: "idle",
        mic: "off",
        micSilent: false,
        pttHeld: false,
      },
      status: undefined,
      radioFollowsDriver: false,
      noun: "iPad",
      actions: actions(),
      goLive: false,
      ...over,
    };
    return renderToStaticMarkup(createElement(RadioVoiceView, props));
  }

  const text = (m: string): string => m.replace(/<[^>]+>/g, " ").replace(/&#x27;/g, "'").replace(/\s+/g, " ");

  it("absent on an older server or page (no prop) and when not shown", () => {
    expect(text(render())).not.toContain(ONLINE_NAMES_TITLE);
    const hidden = onlineNamesView({ data: undefined, error: MISSING, saving: false, saveError: null });
    expect(text(render({ onlineNames: hidden, onOnlineNames: vi.fn() }))).not.toContain(ONLINE_NAMES_TITLE);
  });

  /** Selected switches on the page (React Aria marks a selected switch's input as checked). */
  const checked = (html: string): number => (html.match(/checked=""/g) ?? []).length;

  it("off by default: the title, the promise, an unselected switch", () => {
    const v = onlineNamesView({ data: { online_names: false }, error: null, saving: false, saveError: null });
    const html = render({ onlineNames: v, onOnlineNames: vi.fn() });
    expect(text(html)).toContain(ONLINE_NAMES_TITLE);
    expect(text(html)).toContain(ONLINE_NAMES_HINT);
    expect(checked(html)).toBe(checked(render())); // the voice switch only
  });

  it("on: the switch is selected; a problem is shown in the warning colour", () => {
    const on = onlineNamesView({ data: { online_names: true }, error: null, saving: false, saveError: null });
    expect(checked(render({ onlineNames: on, onOnlineNames: vi.fn() }))).toBe(checked(render()) + 1);
    const failed = onlineNamesView({ data: { online_names: true }, error: null, saving: false, saveError: "boom" });
    expect(render({ onlineNames: failed, onOnlineNames: vi.fn() })).toContain('<span class="text-warning">Not saved: boom</span>');
  });
});
