// Settings › Radio & voice, the "Car health calls" card (lane "health", spec 3.13 D5): pure view model. Which car
// health calls the radio makes, for the whole household (GET / PUT /api/car-health/settings): cold tyres, tyre wear,
// fuel, and the lock-up and wheelspin notes (off, from Detailed coaching, or from Normal coaching - never at Quiet).
// Intensity and voice stay per driver (Coaching on this page). Tested in plain node (carhealth-model.test.ts).
//
// Unknown stays unknown: until the Mac answers, no switch is drawn as off or on (one row says why instead).

import type { CarHealthSettings, SlipCallsSetting } from "../../../lib/carhealth/types";
import { carHealthErrorText } from "../../../lib/endpoints/carhealth";
import { isMissingRoute } from "../../../lib/endpoints/review";
import type { SegmentChoice } from "../cells";

export const CARD_TITLE = "Car health calls";

/** Under the card: why the tyre colours and calls never use a fixed window. */
export const CARD_HELP = "Temperatures are judged against your own warm laps; games don't publish their tyre windows.";

export interface ToggleRow {
  key: "tyre_calls" | "wear_calls" | "fuel_calls";
  title: string;
  hint: string;
}

/** The three switches, in the card's order. */
export const TOGGLES: readonly ToggleRow[] = [
  {
    key: "tyre_calls",
    title: "Cold tyre calls (F1 25)",
    hint: "New tyres in the pit lane, and the restart after a safety car. The colours on Drive › Car stay either way.",
  },
  {
    key: "wear_calls",
    title: "Worn tyre call",
    hint: "At 70 % wear in practice, qualifying and Forza Motorsport. In F1 25 races the pit-window call covers wear.",
  },
  {
    key: "fuel_calls",
    title: "Fuel calls (Forza)",
    hint: "Low fuel, from how fast the tank level falls. F1 25 fuel calls come from race strategy and stay on.",
  },
];

export const SLIP_TITLE = "Lock-up and wheelspin notes";

export const SLIP_CHOICES: readonly (SegmentChoice<SlipCallsSetting> & { hint: string })[] = [
  { value: "off", label: "Off", hint: "Never on the radio; Drive › Car still counts them." },
  // the Coaching level they are said from (never at Quiet: "Always" was wrong there, and too wide at 320 px)
  { value: "detailed", label: "Detailed", hint: "Said only when Coaching is on Detailed; never at Quiet." },
  { value: "normal", label: "Normal", hint: "Said when Coaching is on Normal or Detailed; never at Quiet." },
];

/** Under the card, after the help: when lock-ups and wheelspin count at all (F1 25 only). */
export const SLIP_RULE =
  "Lock-ups are counted only with ABS off. Wheelspin is said only with traction control off or medium (F1 25).";

export interface CarHealthCardInput {
  /** The settings as the Mac last reported them (undefined: not read yet). */
  data: CarHealthSettings | undefined;
  /** The last load failed. */
  loadError: Error | null;
  /** A save is in flight. */
  saving: boolean;
  /** The last save failed, in the server's words. */
  saveError: string | null;
}

export interface CarHealthCardView {
  /** ready: the four rows; loading / missing / error: one row saying why, never switches drawn as off. */
  state: "ready" | "loading" | "missing" | "error";
  settings: CarHealthSettings | null;
  /** The rows can be changed (not while a save is in flight). */
  editable: boolean;
  /** The one row's words when not ready. */
  note: string | null;
  noteTone: "muted" | "warning";
  /** Retry the load (error only). */
  retry: boolean;
  /** Under the rows: a failed save, in words. */
  saveError: string | null;
  slipHint: string;
}

export function carHealthCardView(p: CarHealthCardInput): CarHealthCardView {
  const base = { settings: null, editable: false, retry: false, saveError: null, slipHint: SLIP_CHOICES[1]!.hint } as const;
  if (!p.data) {
    if (p.loadError && isMissingRoute(p.loadError)) {
      return {
        ...base,
        state: "missing",
        note: "This Pitwall server doesn't have car health calls yet: update Pitwall on the Mac.",
        noteTone: "muted",
      };
    }
    if (p.loadError) {
      const note = `Couldn't load: ${carHealthErrorText(p.loadError)}`;
      return { ...base, state: "error", note, noteTone: "warning", retry: true };
    }
    return { ...base, state: "loading", note: "Loading from the Mac…", noteTone: "muted" };
  }
  const slip = SLIP_CHOICES.find((c) => c.value === p.data!.slip_calls) ?? SLIP_CHOICES[1]!;
  return {
    state: "ready",
    settings: p.data,
    editable: !p.saving,
    note: null,
    noteTone: "muted",
    retry: false,
    saveError: p.saveError ? `Couldn't save: ${p.saveError}` : null,
    slipHint: slip.hint,
  };
}

/** The settings with one change applied (the card always PUTs all four, so the server never has to merge). */
export function withChange(s: CarHealthSettings, change: Partial<CarHealthSettings>): CarHealthSettings {
  return { ...s, ...change };
}
