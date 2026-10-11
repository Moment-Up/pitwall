import { describe, expect, it } from "vitest";
import {
  answerSource,
  ANSWER_SOURCE_LABEL,
  confidenceWord,
  consistencyWords,
  cornerWords,
  dayTitle,
  evidenceLine,
  flagWord,
  joinAnd,
  notCleanReason,
  seconds,
  sessionTitle,
  sessionTypeLabel,
  signedSeconds,
  spreadSeconds,
  timeOfDay,
  readableCar,
  trackLabel,
  weatherText,
  whenText,
  whyText,
} from "./words";

const unix = (y: number, mo: number, d: number, h = 12, mi = 0) => new Date(y, mo - 1, d, h, mi).getTime() / 1000;

describe("confidence and numbers in words", () => {
  it("confidence: high >= 0.8, medium 0.6-0.8, low below (spec 9.6)", () => {
    expect(confidenceWord(1)).toBe("high");
    expect(confidenceWord(0.8)).toBe("high");
    expect(confidenceWord(0.79)).toBe("medium");
    expect(confidenceWord(0.6)).toBe("medium");
    expect(confidenceWord(0.59)).toBe("low");
    expect(confidenceWord(null)).toBeNull();
    expect(confidenceWord(Number.NaN)).toBeNull();
  });

  it("seconds carry no sign (the sentence says the direction); unknown is '-'", () => {
    expect(seconds(-0.114)).toBe("0.11 s");
    expect(seconds(0.5, 1)).toBe("0.5 s");
    expect(seconds(null)).toBe("-");
  });

  it("spreads: 2 decimals below a second, 1 from a second up", () => {
    expect(spreadSeconds(350)).toBe("0.35 s");
    expect(spreadSeconds(1400)).toBe("1.4 s");
    expect(spreadSeconds(996)).toBe("1.0 s");
    expect(spreadSeconds(null)).toBe("-");
  });

  it("signed badges use U+2212 for a gain", () => {
    expect(signedSeconds(0.114)).toBe("+0.11 s");
    expect(signedSeconds(-0.27)).toBe("−0.27 s");
    expect(signedSeconds(0.001)).toBe("±0.00 s");
    expect(signedSeconds(undefined)).toBe("-");
  });

  it("joins with 'and'", () => {
    expect(joinAnd([])).toBe("");
    expect(joinAnd(["a"])).toBe("a");
    expect(joinAnd(["a", "b", "c"])).toBe("a, b and c");
  });
});

describe("lap status", () => {
  it("names every LapFlag in words", () => {
    expect(flagWord("pit_out")).toBe("pit out");
    expect(flagWord("stale_data")).toBe("data gap");
    expect(flagWord("distance_jump")).toBe("reset to track");
    expect(flagWord("something_new")).toBe("something new");
  });

  it("says why a lap is not clean, and nothing for a clean lap", () => {
    expect(notCleanReason({ clean: true, valid: true, flags: [] })).toBeNull();
    expect(notCleanReason({ clean: false, valid: true, flags: ["flashback"] })).toBe("flashback");
    expect(notCleanReason({ clean: false, valid: false, flags: [] })).toBe("invalid");
    expect(notCleanReason({ clean: false, valid: false, flags: ["invalid"] })).toBe("invalid");
    expect(notCleanReason({ clean: false, valid: false, flags: ["pit_in"] })).toBe("invalid, pit in");
    expect(notCleanReason({ clean: false, valid: null, flags: [] })).toBe("not clean");
  });
});

describe("corner descriptions (neutral, never advice)", () => {
  it("describes differences over the coach's thresholds with their direction", () => {
    expect(cornerWords({ brakeM: -12.4, minSpeedKph: -4.2, exitSpeedKph: 5 })).toEqual([
      "braked about 12 m earlier",
      "4 km/h slower at the slowest point",
      "5 km/h faster out of the corner",
    ]);
    expect(cornerWords({ brakeM: 11.461, minSpeedKph: -2.683, exitSpeedKph: -5.792 })).toEqual([
      "braked about 11 m later",
      "6 km/h slower out of the corner",
    ]);
  });

  it("leaves out what is under the thresholds or unknown", () => {
    expect(cornerWords({ brakeM: -0.886, minSpeedKph: 2.129, exitSpeedKph: null })).toEqual([]);
    expect(cornerWords({})).toEqual([]);
  });

  it("never tells the driver what to do", () => {
    const all = [
      ...cornerWords({ brakeM: 30, minSpeedKph: 10, exitSpeedKph: -10 }),
      ...cornerWords({ brakeM: -30, minSpeedKph: -10, exitSpeedKph: 10 }),
      whyText({ where: "Stowe", evidence: { brake_point_delta_m: 20, time_delta_s: -0.2, throttle_full_delta_m: -10 } }) ?? "",
    ].join(" ");
    expect(all).not.toMatch(/\b(try|should|brake later|carry more|push|you need)\b/i);
  });

  it("writes the Why? sentence from the comparison's numbers", () => {
    expect(
      whyText({
        where: "Stowe",
        evidence: { brake_point_delta_m: -12.2, min_speed_delta_kph: -4, time_delta_s: 0.114 },
        lapNumber: 63,
        refLapNumber: 64,
      }),
    ).toBe(
      "At Stowe you braked 12 m earlier, your slowest speed was 4 km/h lower and the corner took 0.11 s longer (lap 63 against your reference, lap 64).",
    );
    expect(whyText({ where: "T10", evidence: { exit_speed_delta_kph: 18, time_delta_s: -0.267 } })).toBe(
      "At T10 you left the corner 18 km/h faster and the corner took 0.27 s less.",
    );
    expect(whyText({ where: "T1", evidence: {} })).toBeNull();
  });
});

describe("evidence line", () => {
  it("turns the coach's consistency into 'your last' laps", () => {
    expect(consistencyWords("3 of the last 5 laps")).toBe("3 of your last 5 laps");
    expect(consistencyWords(null)).toBeNull();
  });

  it("joins consistency, the amount a lap and the confidence word", () => {
    expect(evidenceLine({ consistency: "3 of the last 5 laps", impactS: 0.114, confidence: 0.9 })).toBe(
      "Seen on 3 of your last 5 laps · about 0.11 s a lap · confidence high",
    );
  });

  it("falls back to this session's own count when the coach has no history", () => {
    expect(evidenceLine({ consistency: null, seen: 2, compared: 9, impactS: -0.3, confidence: 0.7 })).toBe(
      "Seen on 2 of 9 laps compared · about 0.30 s a lap · confidence medium",
    );
    expect(evidenceLine({ seen: 1, compared: 1 })).toBe("Seen on 1 of 1 lap compared");
    expect(evidenceLine({})).toBe("");
  });
});

describe("sessions and days", () => {
  it("names the session type as the game does, and leaves out 'unknown'", () => {
    expect(sessionTypeLabel({ session_type_raw: "One-Shot Qualifying", session_type: "qualifying" })).toBe(
      "One-Shot Qualifying",
    );
    expect(sessionTypeLabel({ session_type_raw: null, session_type: "time_trial" })).toBe("Time trial");
    expect(sessionTypeLabel({ session_type_raw: null, session_type: "unknown" })).toBeNull();
    expect(sessionTypeLabel({})).toBeNull();
  });

  it("titles a session 'Track · Type'", () => {
    expect(sessionTitle({ track_name: "Austria", session_type_raw: "Race" })).toBe("Austria · Race");
    expect(sessionTitle({ track_name: null, session_type: "unknown" })).toBe("Unknown track");
    expect(trackLabel({ track_name: "  " })).toBe("Unknown track");
  });

  it("labels days Today, Yesterday, then dates (local time)", () => {
    const now = new Date(2026, 9, 11, 9, 0).getTime();
    expect(dayTitle(unix(2026, 10, 11, 0, 5), now)).toBe("Today");
    expect(dayTitle(unix(2026, 10, 10, 23, 55), now)).toBe("Yesterday");
    expect(dayTitle(unix(2026, 10, 3, 19, 15), now)).toBe("3 Oct");
    expect(dayTitle(unix(2025, 12, 30), now)).toBe("30 Dec 2025");
  });

  it("writes the time of day in 24 h", () => {
    expect(timeOfDay(unix(2026, 10, 11, 7, 5))).toBe("07:05");
    expect(whenText(unix(2026, 10, 11, 19, 40), new Date(2026, 9, 11, 21).getTime())).toBe("Today · 19:40");
  });

  it("says the weather in words, or nothing", () => {
    expect(weatherText({ condition: "light_cloud", track_temp_c: 34 })).toBe("Light cloud · track 34°");
    expect(weatherText({ condition: null, track_temp_c: null })).toBeNull();
    expect(weatherText(null)).toBeNull();
  });
});

describe("engineer answer source chip (spec 6.7)", () => {
  it("grounded LLM answer", () => {
    expect(answerSource({ fallback: false, grounded: true, grounding_issues: [] })).toBe("grounded");
  });
  it("deterministic fallback (LLM off, or its answers failed grounding)", () => {
    expect(answerSource({ fallback: true, grounded: true, grounding_issues: [] })).toBe("deterministic");
    expect(answerSource({ fallback: true, grounded: true, grounding_issues: ["unsupported numbers: 3.2"] })).toBe(
      "deterministic",
    );
  });
  it("LLM down", () => {
    expect(answerSource({ fallback: true, grounded: true, grounding_issues: ["llm unavailable: timeout"] })).toBe(
      "llm_down",
    );
    expect(ANSWER_SOURCE_LABEL.llm_down).toBe("LLM down · deterministic");
  });
});

describe("names a driver can read (integration plan 5.8)", () => {
  it("a raw id stored as a car or track name is never shown", () => {
    for (const raw of ["team_214", "car_12", "gt7:car:123", "f1:team:7", "Unknown team (id 214)", "", "  ", null, undefined]) {
      expect(readableCar(raw), String(raw)).toBeNull();
    }
    expect(readableCar(" Haas ")).toBe("Haas");
    expect(readableCar("Porsche 911 GT3 RS (992) '22")).toBe("Porsche 911 GT3 RS (992) '22");
    expect(trackLabel({ track_name: "unknown_-1" })).toBe("Unknown track");
    expect(trackLabel({ track_name: "f1:-1" })).toBe("Unknown track");
    expect(trackLabel({ track_name: "Unidentified GT7 circuit (0.92 km)" })).toBe("Unidentified GT7 circuit (0.92 km)");
    expect(trackLabel({ track_name: "Silverstone (Reverse)" })).toBe("Silverstone (Reverse)");
  });
});
