// Settings › Radio & voice, "Race calls" (v0.3.0, one page for every call family): the seated driver's race radio
// toggles (drivers.RadioCallPrefs), edited here only (the driver sheet keeps the driver's radio words). Pure.

import { radioCallsOf, type Driver, type RadioCallGroup, type RadioCallPrefs } from "../../../lib/drivers";
import { handsFreeDrivingHint } from "../drivers/model";

export const RACE_CALLS_TITLE = "Race calls";

export interface RaceCallsView {
  /** The Mac follows driver profiles and knows race radio (a profile carries the toggles). */
  shown: boolean;
  /** A driver is in the seat: the toggles are theirs. */
  editable: boolean;
  title: string;
  hint: string;
  calls: RadioCallPrefs;
  driverId: number | null;
}

export function raceCallsView(input: {
  driver: Pick<Driver, "id" | "name" | "preferences"> | null;
  follows: boolean;
  anyKnowsRaceRadio: boolean;
  saveError?: string | null;
}): RaceCallsView {
  const { driver, follows, anyKnowsRaceRadio, saveError } = input;
  const known = driver ? driver.preferences.radio_calls !== undefined : anyKnowsRaceRadio;
  const calls = radioCallsOf(driver?.preferences.radio_calls);
  if (!follows || !known) {
    return { shown: false, editable: false, title: RACE_CALLS_TITLE, hint: "", calls, driverId: null };
  }
  if (!driver) {
    return {
      shown: true,
      editable: false,
      title: RACE_CALLS_TITLE,
      hint: "Nobody is in the seat, so every race call is on. Pick who is driving on Drive to choose theirs.",
      calls,
      driverId: null,
    };
  }
  const off = Object.values(calls).filter((v) => !v).length;
  const base = `${driver.name}'s, the driver in the seat: each driver has their own.`;
  return {
    shown: true,
    editable: true,
    title: `${RACE_CALLS_TITLE} for ${driver.name}`,
    hint: saveError ? `Not saved: ${saveError}` : off ? `${base} ${off} switched off.` : base,
    calls,
    driverId: driver.id,
  };
}

/** The PATCH body for one toggle (the server merges a partial ``radio_calls``). */
export function raceCallPatch(group: RadioCallGroup, on: boolean): { radio_calls: Partial<RadioCallPrefs> } {
  return { radio_calls: { [group]: on } };
}

/** "Hands-free while driving" for the seated driver, on the radio page with the device's hands-free switch. */
export interface DrivingHandsFreeView {
  shown: boolean;
  on: boolean;
  disabled: boolean;
  title: string;
  hint: string;
  driverId: number | null;
}

export function drivingHandsFreeView(
  driver: Pick<Driver, "id" | "name" | "preferences"> | null,
  follows: boolean,
  anyKnowsHandsFree: boolean,
): DrivingHandsFreeView {
  const pref = driver?.preferences.handsfree_while_driving;
  const known = driver ? typeof pref === "boolean" : anyKnowsHandsFree;
  if (!follows || !known) {
    return { shown: false, on: false, disabled: true, title: "Hands-free while driving", hint: "", driverId: null };
  }
  if (!driver) {
    return {
      shown: true,
      on: false,
      disabled: true,
      title: "Hands-free while driving",
      hint: "Nobody is in the seat: hands-free only listens while the car is stopped.",
      driverId: null,
    };
  }
  return {
    shown: true,
    on: pref === true,
    disabled: false,
    title: `Hands-free while ${driver.name} drives`,
    hint: handsFreeDrivingHint(pref === true),
    driverId: driver.id,
  };
}
