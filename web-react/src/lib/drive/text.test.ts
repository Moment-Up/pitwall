import { describe, expect, it } from "vitest";
import { forward, onLap } from "./geometry";
import {
  MINUS,
  THIN,
  ageText,
  confidenceWord,
  dayText,
  distanceShort,
  lapClockTenths,
  lapTime,
  lapTimeHundredths,
  metres,
  round10,
  sectorClockTenths,
  sectorTime,
  sentence,
  signedFixed,
  signedMs,
  thousands,
} from "./text";

describe("drive text", () => {
  it("never formats unknown as zero", () => {
    for (const f of [lapTime, lapTimeHundredths, lapClockTenths, sectorTime, sectorClockTenths, metres, distanceShort]) {
      expect(f(null)).toBe("-");
      expect(f(undefined)).toBe("-");
      expect(f(Number.NaN)).toBe("-");
    }
    expect(signedFixed(null, 2)).toBe("-");
    expect(signedMs(undefined)).toBe("-");
  });

  it("formats lap times, the running clock in tenths (truncated) and the projected lap in hundredths", () => {
    expect(lapTime(91512)).toBe("1:31.512");
    expect(lapTime(65626)).toBe("1:05.626");
    expect(lapTime(23055)).toBe("0:23.055");
    expect(lapTime(0)).toBe("-");
    expect(lapClockTenths(69549)).toBe("1:09.5");
    expect(lapClockTenths(0)).toBe("0:00.0");
    expect(lapClockTenths(59999)).toBe("0:59.9");
    expect(lapClockTenths(-1)).toBe("-");
    expect(lapTimeHundredths(90774)).toBe("1:30.77");
    expect(lapTimeHundredths(90775)).toBe("1:30.78");
    expect(lapTimeHundredths(119996)).toBe("2:00.00");
  });

  it("formats sectors as ss.SSS and a minute or more as m:ss.SSS", () => {
    expect(sectorTime(29318)).toBe("29.318");
    expect(sectorTime(62345)).toBe("1:02.345");
    expect(sectorClockTenths(4495)).toBe("4.4");
    expect(sectorClockTenths(61234)).toBe("1:01.2");
  });

  it("uses U+2212 for minus and drops the sign at zero", () => {
    expect(signedFixed(-0.214, 2)).toBe(`${MINUS}0.21`);
    expect(signedFixed(0.53, 2)).toBe("+0.53");
    expect(signedFixed(-0.004, 2)).toBe("0.00");
    expect(signedMs(-23)).toBe(`${MINUS}0.023`);
  });

  it("writes distances with thin-space thousands", () => {
    expect(thousands(5890)).toBe(`5${THIN}890`);
    expect(thousands(320)).toBe("320");
    expect(metres(5890)).toBe(`5${THIN}890 m`);
    expect(metres(1234567)).toBe(`1${THIN}234${THIN}567 m`);
    expect(distanceShort(850)).toBe("850 m");
    expect(distanceShort(1400)).toBe("1.4 km");
    expect(round10(324)).toBe(320);
    expect(round10(325)).toBe(330);
    expect(round10(-4)).toBe(0);
  });

  it("dates a time as today or day and month", () => {
    const now = new Date(2026, 9, 11, 14, 0, 0).getTime() / 1000;
    expect(dayText(now - 3600, now)).toBe("today");
    expect(dayText(new Date(2026, 9, 3, 12).getTime() / 1000, now)).toBe("3 Oct");
    expect(dayText(new Date(2025, 9, 3, 12).getTime() / 1000, now)).toBe("3 Oct 2025");
    expect(dayText(null, now)).toBeNull();
  });

  it("has small word helpers", () => {
    expect(ageText(6.4)).toBe("6 s");
    expect(ageText(1257)).toBe("21 min");
    expect(ageText(4 * 3600)).toBe("4 h");
    expect(sentence("no reference lap yet")).toBe("No reference lap yet");
    expect(sentence("")).toBe("");
    expect(confidenceWord(0.8)).toBe("high");
    expect(confidenceWord(0.6)).toBe("medium");
    expect(confidenceWord(0.59)).toBe("low");
    expect(confidenceWord(null)).toBeNull();
  });
});

describe("drive geometry", () => {
  it("normalises lap distance into the lap and refuses positions that are not on it", () => {
    expect(onLap(100, 5000)).toBe(100);
    expect(onLap(-164.2, 5276)).toBeCloseTo(5111.8); // F1 grid slot behind the line
    expect(onLap(5050, 5000)).toBe(50); // overshoot at the line
    expect(onLap(16843.7, 913.3)).toBeNull(); // GT7 distance kept integrating in a menu
    expect(onLap(-6000, 5000)).toBeNull();
    expect(onLap(100, null)).toBeNull();
    expect(onLap(null, 5000)).toBeNull();
  });

  it("measures forward distance around the lap", () => {
    expect(forward(100, 300, 1000)).toBe(200);
    expect(forward(900, 100, 1000)).toBe(200);
    expect(forward(100, 100, 1000)).toBe(0);
  });
});
