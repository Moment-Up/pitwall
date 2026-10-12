import { describe, expect, it } from "vitest";
import {
  decimal,
  deltaClass,
  deltaSeconds,
  deltaTone,
  gearLabel,
  grouped,
  lapTime,
  metres,
  MINUS,
  num,
  sector,
  signed,
  THIN_SPACE,
  unit01,
  UNKNOWN,
  withMinus,
} from "./format";

describe("unknown is '-' (spec P5)", () => {
  it("never shows placeholders that look like data", () => {
    for (const v of [null, undefined, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(lapTime(v)).toBe(UNKNOWN);
      expect(sector(v)).toBe(UNKNOWN);
      expect(signed(v)).toBe(UNKNOWN);
      expect(deltaSeconds(v)).toBe(UNKNOWN);
      expect(num(v)).toBe(UNKNOWN);
      expect(decimal(v)).toBe(UNKNOWN);
      expect(grouped(v)).toBe(UNKNOWN);
      expect(metres(v)).toBe(UNKNOWN);
      expect(gearLabel(v)).toBe(UNKNOWN);
    }
    expect(UNKNOWN).toBe("-");
  });

  it("treats zero and negative times as unknown (the game sends 0 before a lap starts)", () => {
    expect(lapTime(0)).toBe("-");
    expect(lapTime(-5)).toBe("-");
    expect(sector(0)).toBe("-");
    expect(metres(-1)).toBe("-");
  });

  it("keeps a custom fallback for num()", () => {
    expect(num(null, 0, "n/a")).toBe("n/a");
  });
});

describe("lap and sector times", () => {
  it("formats completed laps as m:ss.SSS", () => {
    expect(lapTime(91_512)).toBe("1:31.512");
    expect(lapTime(90_986)).toBe("1:30.986");
    expect(lapTime(5_004)).toBe("0:05.004");
    expect(lapTime(3_601_000)).toBe("60:01.000");
  });

  it("rounds float milliseconds without producing :60", () => {
    expect(lapTime(59_999.6)).toBe("1:00.000");
    expect(lapTime(90_986.4)).toBe("1:30.986");
  });

  it("shows the running clock in tenths, truncated like a stopwatch", () => {
    expect(lapTime(69_549, 1)).toBe("1:09.5");
    expect(lapTime(69_599, 1)).toBe("1:09.5");
    expect(lapTime(59_999, 1)).toBe("0:59.9");
    expect(lapTime(100, 1)).toBe("0:00.1");
  });

  it("formats sectors as ss.SSS, with minutes from 60 s up", () => {
    expect(sector(29_318)).toBe("29.318");
    expect(sector(9_120)).toBe("9.120");
    expect(sector(62_005)).toBe("1:02.005");
    expect(sector(12_449, 1)).toBe("12.4");
  });
});

describe("signs and deltas", () => {
  it("uses U+2212 for negatives, + for positives, ± for zero", () => {
    expect(signed(-0.021)).toBe(`${MINUS}0.021`);
    expect(signed(0.53, 2)).toBe("+0.53");
    expect(signed(0)).toBe("±0.000");
    expect(signed(-0.0004)).toBe("±0.000");
    expect(signed(1.5, 1, " s")).toBe("+1.5 s");
  });

  it("formats deltas with 2 decimals, 1 from 10 s up (spec 4.5)", () => {
    expect(deltaSeconds(-0.21)).toBe(`${MINUS}0.21`);
    expect(deltaSeconds(0.534)).toBe("+0.53");
    expect(deltaSeconds(12.44)).toBe("+12.4");
    expect(deltaSeconds(-9.996)).toBe(`${MINUS}10.0`);
    expect(deltaSeconds(0.1234, 3)).toBe("+0.123");
  });

  it("says ahead / behind / level with a 0.02 s level band", () => {
    expect(deltaTone(-0.21)).toBe("ahead");
    expect(deltaTone(0.21)).toBe("behind");
    expect(deltaTone(0.02)).toBe("level");
    expect(deltaTone(-0.015)).toBe("level");
    expect(deltaTone(null)).toBeNull();
    expect(deltaTone(0.01, 0.005)).toBe("behind");
  });

  it("maps deltas to the v2 colour utilities", () => {
    expect(deltaClass(-0.3)).toBe("text-ahead");
    expect(deltaClass(0.3)).toBe("text-behind");
    expect(deltaClass(0)).toBe("text-foreground");
    expect(deltaClass(undefined)).toBe("text-faint");
  });
});

describe("numbers and distances", () => {
  it("num() keeps digits and uses U+2212", () => {
    expect(num(212.4)).toBe("212");
    expect(num(-3.5, 1)).toBe(`${MINUS}3.5`);
    expect(num(-0.04, 1)).toBe("0.0");
  });

  it("decimal() drops trailing zeros", () => {
    expect(decimal(-3.5)).toBe(`${MINUS}3.5`);
    expect(decimal(0.05)).toBe("0.05");
    expect(decimal(50)).toBe("50");
    expect(decimal(0.123456, 3)).toBe("0.123");
  });

  it("groups thousands with a narrow no-break space", () => {
    expect(grouped(5890)).toBe(`5${THIN_SPACE}890`);
    expect(grouped(123)).toBe("123");
    expect(grouped(-1813)).toBe(`${MINUS}1${THIN_SPACE}813`);
    expect(metres(5890.4)).toBe(`5${THIN_SPACE}890 m`);
    expect(metres(316, 10)).toBe("320 m");
    expect(metres(0)).toBe("0 m");
  });

  it("withMinus() converts a leading sign only", () => {
    expect(withMinus("-3.50")).toBe(`${MINUS}3.50`);
    expect(withMinus("-.5")).toBe(`${MINUS}.5`);
    expect(withMinus("70-85")).toBe("70-85");
    expect(withMinus("OFF")).toBe("OFF");
    expect(withMinus("-")).toBe("-");
  });

  it("gearLabel()", () => {
    expect(gearLabel(-1)).toBe("R");
    expect(gearLabel(0)).toBe("N");
    expect(gearLabel(7)).toBe("7");
  });

  it("unit01() clamps and keeps unknown as null", () => {
    expect(unit01(1.4)).toBe(1);
    expect(unit01(-0.2)).toBe(0);
    expect(unit01(null)).toBeNull();
  });
});
