import { afterAll, beforeAll, describe, expect, it } from "vitest";
import {
  addDays,
  classLabel,
  drivingTime,
  goalLapTime,
  isF1Game,
  mondayOf,
  parseIsoDate,
  parseLapTarget,
  percent,
  possessive,
  secondsShort,
  shiftWeek,
  shortDay,
  tenthsText,
  weekLabel,
} from "./format";

// Week maths runs in the server's time zone (Europe/London here): the change from summer time on 25 Oct 2026 must
// not move a week. Node picks up a changed TZ for every later Date.
const env = (globalThis as unknown as { process: { env: Record<string, string | undefined> } }).process.env;
let tz: string | undefined;
beforeAll(() => {
  tz = env.TZ;
  env.TZ = "Europe/London";
});
afterAll(() => {
  if (tz === undefined) delete env.TZ;
  else env.TZ = tz;
});

describe("lap targets", () => {
  it.each([
    ["1:10.0", 70_000],
    ["1:10", 70_000],
    ["1:10.4", 70_400],
    ["1:10.40", 70_400],
    ["70.5", 70_500],
    [" 1:36,3 ", 96_300],
    ["12:00.0", 720_000],
  ])("%s -> %d ms", (text, ms) => {
    expect(parseLapTarget(text)).toEqual({ ok: true, ms });
  });

  it.each([
    ["", "Type a lap time"],
    ["fast", "minutes:seconds"],
    ["1:70.0", "Seconds go up to 59"],
    ["1:10.05", "tenths"],
    ["1:10.549", "tenths"],
    ["0:05.0", "between 0:10.0 and 60:00.0"],
    ["61:00.0", "between 0:10.0 and 60:00.0"],
  ])("%j is refused (%s), never rounded", (text, why) => {
    const r = parseLapTarget(text);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toContain(why);
  });

  it("formats times the way the copy rules say, unknown is '-'", () => {
    expect(goalLapTime(70_000)).toBe("1:10.000");
    expect(goalLapTime(null)).toBe("-");
    expect(tenthsText(70_549)).toBe("1:10.5");
    expect(tenthsText(null)).toBe("");
    expect(secondsShort(1230)).toBe("1.2 s");
    expect(secondsShort(null)).toBe("-");
    expect(drivingTime(5530.4)).toBe("1 h 32 min");
    expect(drivingTime(2700)).toBe("45 min");
    expect(drivingTime(7200)).toBe("2 h");
    expect(drivingTime(null)).toBe("-");
    expect(percent(0.4517)).toBe(45.2);
    expect(percent(1.4)).toBe(100);
    expect(percent(-1)).toBe(0);
    expect(percent(null)).toBeNull();
  });

  it("names a class without guessing: F1 formula by name, a Forza class after its car, else nothing", () => {
    expect(classLabel("f1_25:formula:F1 World")).toBe("any F1 World car");
    expect(classLabel("forza_motorsport:class:5", "Porsche 911 GT3")).toBe("any car of the same class as the Porsche 911 GT3");
    expect(classLabel("forza_motorsport:class:5")).toBe("any car of the same class");
    expect(classLabel(null)).toBeNull();
    expect(classLabel("gt7:something")).toBeNull();
    expect(isF1Game("f1_25")).toBe(true);
    expect(isF1Game("gt7")).toBe(false);
    expect(isF1Game(null)).toBe(false);
    expect(possessive("Sam")).toBe("Sam's");
    expect(possessive("James")).toBe("James's");
  });
});

describe("weeks (Monday to Sunday, local calendar arithmetic)", () => {
  it("finds the Monday of any day in the week", () => {
    for (const d of ["2026-10-05", "2026-10-07", "2026-10-11"]) expect(mondayOf(parseIsoDate(d)!)).toBe("2026-10-05");
    expect(mondayOf(parseIsoDate("2026-10-12")!)).toBe("2026-10-12");
  });

  it("does not move a week across the change from summer time (25 Oct 2026)", () => {
    expect(shiftWeek("2026-10-19", 1)).toBe("2026-10-26");
    expect(shiftWeek("2026-10-26", -1)).toBe("2026-10-19");
    expect(addDays("2026-10-24", 2)).toBe("2026-10-26");
    // the naive way (+ 7 x 86 400 s from local midnight) lands on Sunday 23:00 after the change
    const naive = new Date(parseIsoDate("2026-10-19")!.getTime() + 7 * 86_400_000);
    expect(naive.getDate()).toBe(25);
    expect(shiftWeek("2026-03-23", 1)).toBe("2026-03-30"); // into summer time
    expect(shiftWeek("2026-10-07", 0)).toBe("2026-10-05");
  });

  it("labels a week from its Monday: '5 to 11 Oct', across months and years", () => {
    expect(weekLabel("2026-10-05")).toBe("5 to 11 Oct");
    expect(weekLabel("2026-09-28")).toBe("28 Sep to 4 Oct");
    expect(weekLabel("2025-12-29")).toBe("29 Dec 2025 to 4 Jan 2026");
    expect(weekLabel("not a date")).toBe("-");
    expect(parseIsoDate("2026-02-30")).toBeNull();
  });

  it("short days in local time", () => {
    expect(shortDay(new Date(2026, 9, 10, 22, 17, 49).getTime() / 1000)).toBe("Sat 10 Oct");
    expect(shortDay(null)).toBe("-");
  });
});
