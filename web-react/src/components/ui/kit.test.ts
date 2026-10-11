import { describe, expect, it } from "vitest";
import { MINUS, THIN_SPACE } from "../../lib/format";
import { GLOSSARY } from "./glossary-terms";
import {
  cx,
  deltaToneOf,
  evidenceOf,
  isTagged,
  legendItems,
  numeralFontSize,
  rangeDescription,
  rangeGeometry,
  settingText,
  splitMinus,
  tagFor,
  timingText,
} from "./kit";

describe("timingText()", () => {
  it("formats each kind and keeps unknown as '-'", () => {
    expect(timingText(91_512, "lap")).toBe("1:31.512");
    expect(timingText(69_549, "lap", { running: true })).toBe("1:09.5");
    expect(timingText(29_318, "sector")).toBe("29.318");
    expect(timingText(12_449, "sector", { running: true })).toBe("12.4");
    expect(timingText(-210, "delta")).toBe(`${MINUS}0.21`);
    expect(timingText(530, "delta")).toBe("+0.53");
    expect(timingText(12_440, "delta")).toBe("+12.4");
    expect(timingText(-23, "delta", { digits: 3 })).toBe(`${MINUS}0.023`);
    for (const k of ["lap", "sector", "delta"] as const) {
      expect(timingText(null, k)).toBe("-");
      expect(timingText(undefined, k)).toBe("-");
      expect(timingText(Number.NaN, k)).toBe("-");
    }
    expect(timingText(0, "lap")).toBe("-");
    expect(timingText(0, "delta")).toBe("±0.00");
  });
});

describe("deltaToneOf()", () => {
  it("is ahead / behind outside +/-0.02 s and level inside", () => {
    expect(deltaToneOf(-210)).toBe("ahead");
    expect(deltaToneOf(530)).toBe("behind");
    expect(deltaToneOf(20)).toBe("level");
    expect(deltaToneOf(-19)).toBe("level");
    expect(deltaToneOf(null)).toBe("level");
  });
});

describe("tags and legend (spec 4.6)", () => {
  it("tags rec / pb / sb / invalid only", () => {
    expect(tagFor("rec")).toEqual({ text: "REC", meaning: "family record" });
    expect(tagFor("pb")?.text).toBe("PB");
    expect(tagFor("sb")?.text).toBe("SB");
    expect(tagFor("invalid")?.text).toBe("INV");
    for (const s of ["slower", "neutral", "running", "future", null, undefined, "nope"]) expect(tagFor(s)).toBeNull();
    expect(isTagged("sb")).toBe(true);
    expect(isTagged("slower")).toBe(false);
  });

  it("before D2 the legend says only SB; with D2 it adds REC and PB in that order", () => {
    expect(legendItems(1).map((i) => `${i.tag} ${i.text}`)).toEqual(["SB your best today"]);
    expect(legendItems(2).map((i) => `${i.tag} ${i.text}`)).toEqual([
      "REC family record",
      "PB your best ever",
      "SB your best today",
    ]);
    // Review: the session being reviewed may be an older one, so not "today"
    expect(legendItems(2, true, "session").map((i) => `${i.tag} ${i.text}`)).toEqual([
      "REC family record",
      "PB your best ever",
      "SB your best this session",
      "null slower than your best this session",
      "INV not a clean lap",
    ]);
    const ext = legendItems(1, true).map((i) => i.status);
    expect(ext).toEqual(["sb", "slower", "invalid"]);
    expect(legendItems(1, true).some((i) => i.status === "rec" || i.status === "pb")).toBe(false);
  });
});

describe("evidenceOf() (spec P8)", () => {
  it("flags synthetic only when told, replay when told or from the source", () => {
    expect(evidenceOf({})).toEqual({ synthetic: false, replay: false });
    expect(evidenceOf({ synthetic: true })).toEqual({ synthetic: true, replay: false });
    expect(evidenceOf({ source: "replay:captures/a.pwcap" })).toEqual({ synthetic: false, replay: true });
    expect(evidenceOf({ source: "udp:192.168.1.100" }).replay).toBe(false);
    expect(evidenceOf({ synthetic: null, replay: null, source: null })).toEqual({ synthetic: false, replay: false });
  });
});

describe("numerals", () => {
  it("splitMinus() separates a leading U+2212 only", () => {
    expect(splitMinus(`${MINUS}0.21`)).toEqual({ minus: true, rest: "0.21" });
    expect(splitMinus("+0.21")).toEqual({ minus: false, rest: "+0.21" });
    expect(splitMinus("-0.21")).toEqual({ minus: false, rest: "-0.21" });
  });

  it("settingText() shows values as given, with a real minus; empty is unknown", () => {
    expect(settingText("78")).toBe("78");
    expect(settingText("-3.50")).toBe(`${MINUS}3.50`);
    expect(settingText(" OFF ")).toBe("OFF");
    expect(settingText(-3.5)).toBe(`${MINUS}3.5`);
    expect(settingText(0.05)).toBe("0.05");
    expect(settingText("")).toBe("-");
    expect(settingText(null)).toBe("-");
    expect(settingText(Number.NaN)).toBe("-");
  });

  it("numeralFontSize() maps tokens and pixels", () => {
    expect(numeralFontSize("d-delta")).toBe("var(--pw-d-delta)");
    expect(numeralFontSize("d-l")).toBe("var(--pw-d-l)");
    expect(numeralFontSize("kpi")).toBe("32px");
    expect(numeralFontSize("table")).toBe("17px");
    expect(numeralFontSize(96)).toBe("96px");
    expect(numeralFontSize("inherit")).toBeUndefined();
    expect(numeralFontSize(undefined)).toBeUndefined();
    expect(numeralFontSize(-4)).toBeUndefined();
  });

  it("cx() joins truthy parts", () => {
    expect(cx("a", false, null, undefined, "", "b")).toBe("a b");
  });
});

describe("rangeGeometry()", () => {
  it("places the value and the spread in percent", () => {
    expect(rangeGeometry(0, 50, 22, [18, 26])).toEqual({
      valuePct: 44,
      outside: null,
      spread: { left: 36, width: 16 },
    });
  });

  it("works with negative ranges (camber) and reversed spreads", () => {
    const g = rangeGeometry(-3.5, -2.5, -3.5, [-3.3, -3.5]);
    expect(g?.valuePct).toBe(0);
    expect(g?.spread?.left).toBeCloseTo(0);
    expect(g?.spread?.width).toBeCloseTo(20);
  });

  it("clamps outside values and says so", () => {
    expect(rangeGeometry(0, 50, 60)).toMatchObject({ valuePct: 100, outside: "above" });
    expect(rangeGeometry(0, 50, -1)).toMatchObject({ valuePct: 0, outside: "below" });
  });

  it("is unknown (null) for an empty or broken range, and has no marker without a value", () => {
    expect(rangeGeometry(5, 5, 5)).toBeNull();
    expect(rangeGeometry(10, 0, 5)).toBeNull();
    expect(rangeGeometry(Number.NaN, 1, 0)).toBeNull();
    expect(rangeGeometry(0, 1, null)).toEqual({ valuePct: null, outside: null, spread: null });
  });

  it("describes itself in one sentence", () => {
    expect(rangeDescription(0, 50, 22, [18, 26], undefined, "Front wing aero")).toBe(
      "Front wing aero: 22 on a range of 0 to 50; sources 18 to 26",
    );
    expect(rangeDescription(-3.5, -2.5, -4, null)).toBe(`${MINUS}4 (outside the range) on a range of ${MINUS}3.5 to ${MINUS}2.5`);
    expect(rangeDescription(1, 1, 1, null, undefined, "X")).toBe("X: range unknown");
  });
});

describe("glossary (explains terms, never actions)", () => {
  it("has a title and text for every term", () => {
    for (const [term, e] of Object.entries(GLOSSARY)) {
      expect(e.title.length, term).toBeGreaterThan(2);
      expect(e.text.length, term).toBeGreaterThan(20);
    }
  });

  it("never tells the driver what to do (no imperative coaching, never 'brake later')", () => {
    const advice = /\b(you should|try to|make sure|brake later|brake earlier|go faster|push harder|don'?t|do not)\b/i;
    for (const [term, e] of Object.entries(GLOSSARY)) {
      expect(e.text, term).not.toMatch(advice);
      expect(e.text, term).not.toMatch(/^(Brake|Turn|Lift|Push|Try|Use|Keep|Avoid)\b/);
    }
  });

  it("uses plain prose (no thin-space numbers or unexplained jargon)", () => {
    for (const e of Object.values(GLOSSARY)) {
      expect(e.text).not.toContain(THIN_SPACE);
      expect(e.text).not.toMatch(/\bV-?min\b|\bΔt\b/);
    }
  });
});
