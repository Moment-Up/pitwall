// Car setup for F2 cars (F2 support, contract v1): the F2 format is its own family (never mixed with the F1 car
// formats), its ranges are F2 evidence only, every cited setup keeps its credit, and a session of one family is never
// offered another family's format. Fixtures: the recorded catalogue plus the contract's F2 format, ranges and session
// answers (carsetup-f2-contract-edited.json, built before the backend existed: contract tier, not game data).
import { describe, expect, it } from "vitest";
import { F1_CLASS, F2_CLASS } from "../carclass-testkit";
import { CarSetupError, normaliseCatalog, type CarSetupCatalog, type SessionOption } from "../endpoints/carsetup";
import {
  classCarText,
  familyAlternatives,
  familyFormats,
  FORMAT_FAMILY,
  formatChoices,
  formatFamily,
  formatShortLabel,
  forFormatText,
  gameSessionText,
  latestSessionFor,
  parseSetupQuery,
  rangeText,
  refusedOverride,
  resolveRequest,
  sessionLabel,
  setupCredit,
  setupFamily,
  sizedFor,
  storedFormat,
  valueProblem,
} from "./carsetup";
import { fixtures } from "./fixtures";

const CAT = fixtures.catalogWithF2();
const F2 = fixtures.f2();

function option(id: string, started: number, over: Partial<SessionOption> = {}): SessionOption {
  return {
    id,
    game: "f1_25",
    platform: "ps5",
    track_id: "f1:3",
    track_name: "Sakhir (Bahrain)",
    track_length_m: 5408,
    session_type: "race",
    session_type_raw: "Race 2",
    car_name: "Art GP '24",
    started_unix: started,
    source: "udp:20777",
    synthetic: false,
    lap_count: 5,
    best_clean_ms: 106540,
    weather: { condition: "clear" },
    driver_id: 1,
    driver_name: "James",
    ...over,
  };
}

describe("the F2 format", () => {
  it("is the F2 family; the F1 car formats are F1's", () => {
    expect(FORMAT_FAMILY).toEqual({ f1_2025: "f1", f1_2026: "f1", f2: "f2" });
    expect(formatFamily("f2")).toBe("f2");
    expect(formatFamily("f1_2026")).toBe("f1");
    expect(formatFamily("f3")).toBeNull();
    expect(formatFamily(null)).toBeNull();
  });

  it("reads 'F2 car' in the request sentence; its catalogue label is the contract's", () => {
    expect(formatShortLabel("f2")).toBe("F2 car");
    expect(formatShortLabel("f1_2025")).toBe("2025 car");
    expect(CAT.formats.find((f) => f.id === "f2")?.label).toBe("F2 cars (2024 and 2025 seasons)");
  });

  it("a link or a remembered choice may name it", () => {
    expect(parseSetupQuery("format=f2&track=3").format).toBe("f2");
    expect(storedFormat({ getItem: () => "f2" })).toBe("f2");
  });

  it("has no handling patch, and the catalogue is read with it (null kept, bare track ids named)", () => {
    expect(CAT.formats.find((f) => f.id === "f2")?.latest_handling_patch).toBeNull();
    const raw = structuredClone(CAT) as CarSetupCatalog;
    (raw.formats.find((f) => f.id === "f2")! as unknown as { tracks: unknown[] }).tracks = [3, 29];
    const n = normaliseCatalog(raw);
    expect(n.formats.find((f) => f.id === "f2")?.tracks).toEqual([
      { id: 3, name: "Track 3" },
      { id: 29, name: "Track 29" },
    ]);
    expect(n.formats.find((f) => f.id === "f1_2025")?.tracks).toEqual(CAT.formats.find((f) => f.id === "f1_2025")?.tracks);
  });
});

describe("F2 ranges: F2 evidence only, never the F1 car's", () => {
  const p = (key: string) => CAT.parameters.find((x) => x.key === key)!;

  it("brake bias reaches 69 (the F1 range says 60); rear suspension tops out at 26 (F1 says 41)", () => {
    expect(p("brake_bias").ranges.f2).toMatchObject({ min: 50, max: 69, max_confirmed: false });
    expect(p("brake_bias").ranges.f1_2025?.max).toBe(60);
    expect(p("rear_suspension").ranges.f2).toMatchObject({ min: 1, max: 26, min_confirmed: true, max_confirmed: true });
    expect(p("rear_suspension").ranges.f1_2025?.max).toBe(41);
  });

  it("every parameter has an F2 range with the menu's step and its evidence", () => {
    for (const x of CAT.parameters) {
      const r = x.ranges.f2;
      expect(r, x.key).toBeDefined();
      expect(r!.min, x.key).toBeLessThanOrEqual(r!.max);
      expect(r!.step, x.key).toBe(x.ranges.f1_2025!.step);
      expect(r!.sources?.length, x.key).toBeGreaterThan(0);
    }
  });

  it("an experiment is checked against the F2 range (a confirmed end only), and the form says the range", () => {
    expect(valueProblem(p("rear_suspension"), "f2", 30, 20)).toBe("Outside the menu range 1 to 26");
    expect(valueProblem(p("rear_suspension"), "f1_2025", 30, 20)).toBeNull(); // the F1 car's menu goes to 41
    expect(valueProblem(p("brake_bias"), "f2", 66, 58)).toBeNull(); // past 60: fine for the F2 car
    expect(valueProblem(p("brake_bias"), "f2", 72, 58)).toBeNull(); // 69 is only the highest value seen
    expect(rangeText(p("rear_suspension"), "f2")).toBe("F2 car menu: 1 to 26");
    expect(rangeText(p("brake_bias"), "f2")).toBe("F2 car: 50 to 69 in published setups");
    expect(rangeText(p("brake_bias"), null)).toBeNull();
  });
});

describe("families on the setup page", () => {
  it("a session's formats: its family's only; every format when the class is unknown (an older server)", () => {
    expect(formatChoices(CAT, F2.sessions.sakhir).map((f) => f.id)).toEqual(["f2"]);
    const f1 = structuredClone(fixtures.sessionNeedsFormat());
    f1.context.car_class = { ...F1_CLASS, id: "f1", certain: false };
    expect(formatChoices(CAT, f1).map((f) => f.id)).toEqual(["f1_2025", "f1_2026"]);
    expect(formatChoices(CAT, fixtures.sessionNeedsFormat()).map((f) => f.id)).toEqual(["f1_2025", "f1_2026", "f2"]);
    expect(familyFormats(CAT.formats, null)).toHaveLength(3);
    expect(setupFamily(F2.sessions.sakhir)).toBe("f2");
    expect(setupFamily(null)).toBeNull();
  });

  it("an F2 session never needs a car format; its car reads 'F2 car' even without one (2026 F2 cars)", () => {
    for (const s of Object.values(F2.sessions)) expect(s.needs).not.toContain("car_format");
    expect(F2.sessions.f2_2026.context.car_format).toBeNull();
    expect(classCarText(F2.sessions.f2_2026.context.car_class)).toBe("F2 car");
    expect(classCarText(F1_CLASS)).toBeNull(); // an F1 car's format is chosen with the picker
    expect(classCarText(null)).toBeNull();
  });

  it("alternatives of the asked family only", () => {
    const alts = [...fixtures.sessionNeedsFormat().unavailable!.alternatives, ...F2.available];
    expect(new Set(familyAlternatives(alts, "f2").map((a) => a.car_format))).toEqual(new Set(["f2"]));
    expect(new Set(familyAlternatives(alts, "f1").map((a) => a.car_format))).toEqual(new Set(["f1_2025", "f1_2026"]));
    expect(familyAlternatives(alts, null)).toHaveLength(alts.length);
  });

  it("a 422 for a format override of another family is told apart from other errors", () => {
    const e = new CarSetupError(422, "car format f1_2025 is an F1 car format; this session's car is F2");
    expect(refusedOverride(e, { format: "f1_2025" })).toBe(true);
    expect(refusedOverride(e, { format: null })).toBe(false);
    expect(refusedOverride(new CarSetupError(404, "no session"), { format: "f1_2025" })).toBe(false);
  });

  it("the game's session and the class in words", () => {
    expect(gameSessionText(F2.sessions.sakhir.session)).toBe("Feature race (Race 2)");
    expect(gameSessionText({ session_type: "race", session_type_raw: "Race", session_label: "Race" })).toBe("Race");
    expect(gameSessionText({ session_type: "race", session_type_raw: "Race", session_label: undefined })).toBe("Race");
    expect(sessionLabel(option("a", 0, { session_label: "Feature race", car_class: F2_CLASS }))).toMatch(
      /^Sakhir \(Bahrain\) · Feature race · .+ · James · F2$/,
    );
    expect(sessionLabel(option("b", 0, { session_type_raw: "Race", car_class: F1_CLASS }))).toMatch(/^Sakhir \(Bahrain\) · Race · .+ · James$/);
  });

  it("handling suggestions say the car they are sized for", () => {
    expect(sizedFor(null, "f2")).toBe("f2");
    expect(sizedFor(null, "f1_2025")).toBeNull();
    expect(sizedFor("f1_2026", null)).toBe("f1_2026");
    expect(forFormatText("f2")).toBe("for the F2 car");
    expect(forFormatText("f1_2025")).toBe("for the 2025 car you chose");
    expect(forFormatText("f1_2026")).toBe("for the 2026 car you chose");
  });
});

describe("the request opens on the car of the latest session", () => {
  const f2Sakhir = option("f2s", 300, { car_class: F2_CLASS, track_id: "f1:3" });
  const f1Monza = option("f1m", 200, { car_class: F1_CLASS, track_id: "f1:11", track_name: "Monza", session_type_raw: "Race", car_name: "McLaren" });

  it("an F2 session last: the F2 car, its track (a remembered F1 format is not used)", () => {
    const q = parseSetupQuery("");
    expect(resolveRequest(q, CAT, [f2Sakhir, f1Monza], "f1_2025")).toMatchObject({ format: "f2", track: 3, session: "race", conditions: "dry" });
  });

  it("an F1 session last: the remembered F1 format and the F1 session's track", () => {
    const q = parseSetupQuery("");
    expect(resolveRequest(q, CAT, [{ ...f1Monza, started_unix: 400 }, f2Sakhir], "f1_2026")).toMatchObject({ format: "f1_2026", track: 11 });
    expect(resolveRequest(q, CAT, [{ ...f1Monza, started_unix: 400 }, f2Sakhir], "f2")).toMatchObject({ format: "f1_2025", track: 11 });
  });

  it("a format in the link: the newest session of that family seeds the track", () => {
    expect(resolveRequest(parseSetupQuery("format=f1_2025"), CAT, [f2Sakhir, f1Monza])).toMatchObject({ format: "f1_2025", track: 11 });
    expect(resolveRequest(parseSetupQuery("format=f2"), CAT, [f1Monza, f2Sakhir])).toMatchObject({ format: "f2", track: 3 });
  });

  it("an F2 session at a track without F2 setups: the first F2 track with one", () => {
    const silverstone = option("f2v", 500, { car_class: F2_CLASS, track_id: "f1:7", track_name: "Silverstone" });
    expect(resolveRequest(parseSetupQuery(""), CAT, [silverstone])).toMatchObject({ format: "f2", track: 3 });
  });

  it("a catalogue without the F2 format (setups not shipped yet): the remembered F1 format, an F1 session's track", () => {
    const f1Only = fixtures.catalog();
    expect(resolveRequest(parseSetupQuery(""), f1Only, [f2Sakhir, f1Monza], "f1_2026")).toMatchObject({ format: "f1_2026", track: 11 });
  });

  it("sessions without a class (an older server): as before", () => {
    const old = { ...f2Sakhir, car_class: undefined };
    expect(resolveRequest(parseSetupQuery(""), CAT, [old], "f1_2025")).toMatchObject({ format: "f1_2025", track: 3 });
  });

  it("'Use my latest session' prefers the format's family", () => {
    expect(latestSessionFor([f2Sakhir, f1Monza], "f1_25", 1, null, "f1")?.id).toBe("f1m");
    expect(latestSessionFor([f2Sakhir, f1Monza], "f1_25", 1, null, "f2")?.id).toBe("f2s");
    expect(latestSessionFor([f1Monza], "f1_25", 1, null, "f2")?.id).toBe("f1m"); // none of the family: any
    expect(latestSessionFor([f2Sakhir, f1Monza], "f1_25", 1)?.id).toBe("f2s");
  });
});

describe("credits", () => {
  it("every cited setup keeps its author, source and date", () => {
    expect(setupCredit({ source_name: "F1Laps", author: "Alex", published: "2025-08-01" })).toBe("Alex's setup on F1Laps, published 2025-08-01");
    expect(setupCredit({ source_name: "F1Laps", author: null, published: null })).toBe("a setup on F1Laps, date not stated");
    for (const s of Object.values(fixtures.recSilverstone().setups)) {
      expect(setupCredit(s)).toContain(s.source_name);
      if (s.author) expect(setupCredit(s)).toContain(s.author);
    }
  });
});
