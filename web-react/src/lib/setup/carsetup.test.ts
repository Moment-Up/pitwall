import { describe, expect, it } from "vitest";
import type { Combination, DiffRow, SessionOption, SetupExperiment, SetupRow } from "../endpoints/carsetup";
import { MINUS } from "../format";
import {
  afterCandidates,
  afterFor,
  alreadyTesting,
  changedFirst,
  comboKey,
  comboLabel,
  conditionsOf,
  confidenceCounts,
  confidenceSummary,
  defaultStyle,
  differenceText,
  displayValue,
  experimentStep,
  f1TrackId,
  fixed,
  formatShortLabel,
  groupRows,
  isChanged,
  latestSessionFor,
  listText,
  paramValue,
  parseNumber,
  parseSetupQuery,
  patchOlder,
  predatesPatch,
  queryIsComplete,
  rememberFormat,
  resolveRequest,
  rowChip,
  rowCopyLine,
  sectionCopyText,
  servedAs,
  servedNote,
  sessionKindOf,
  sessionLabel,
  sessionTypeLabel,
  setupCopyText,
  setupCount,
  setupQueryValues,
  setupSessions,
  setupValue,
  sortAlternatives,
  sortExperiments,
  sortedSetups,
  stepsText,
  storedFormat,
  skillPhrase,
  styleNote,
  trackHasSetup,
  trackLabel,
  unitSuffix,
  unitText,
  valueProblem,
  valueText,
} from "./carsetup";
import { fixtures } from "./fixtures";

const combo = (o: Partial<Combination> = {}): Combination => ({
  car_format: "f1_2025",
  track_id: 7,
  session: "race",
  conditions: "dry",
  style: "balanced",
  derived: false,
  ...o,
});

const session = (o: Partial<SessionOption> = {}): SessionOption => ({
  id: "s1",
  game: "f1_25",
  platform: "ps5",
  track_id: "f1:7",
  track_name: "Silverstone",
  track_length_m: 5891,
  session_type: "race",
  session_type_raw: "Race",
  car_name: null,
  started_unix: 1_791_670_000,
  source: "udp",
  synthetic: false,
  lap_count: 5,
  best_clean_ms: null,
  weather: { condition: "clear" },
  driver_id: 1,
  driver_name: "James",
  car_id: "f1:team:1",
  ...o,
});

const row = (o: Partial<SetupRow> = {}): SetupRow => ({
  key: "front_wing",
  label: "Front Wing Aero",
  group: "Aerodynamics",
  order: 1,
  value: 21,
  display: "21",
  unit: null,
  min: 0,
  max: 50,
  step: 1,
  confidence: "high",
  derived: false,
  rule: null,
  from_setup: "a",
  sources: ["a", "b", "c"],
  patches: [],
  spread: [21, 21],
  ...o,
});

const exp = (o: Partial<SetupExperiment> = {}): SetupExperiment => ({
  id: 1,
  game: "f1_25",
  track_id: "f1:7",
  car_id: "f1:team:1",
  created_unix: 100,
  hypothesis: "calmer rear",
  parameter: "rear_wing",
  from_value: 18,
  to_value: 25,
  status: "proposed",
  before_session_id: "before",
  after_session_id: null,
  before_metrics: null,
  after_metrics: null,
  conclusion: null,
  ...o,
});

describe("recorded fixtures", () => {
  it("are what the live API sent (status and shape)", () => {
    const cat = fixtures.catalog();
    expect(cat.game).toBe("f1_25");
    expect(cat.formats.map((f) => f.id)).toEqual(["f1_2025", "f1_2026"]);
    expect(cat.available.length).toBeGreaterThan(100);
    expect(fixtures.meta("carsetup-unavailable-imola-2026").status).toBe(404);
    expect(fixtures.unavailableImola2026().body.detail.reason).toMatch(/not drivable/);
  });
});

describe("labels", () => {
  it("defaultStyle: beginners start stable, everyone else balanced", () => {
    expect(defaultStyle("beginner")).toBe("stable");
    expect(defaultStyle("intermediate")).toBe("balanced");
    expect(defaultStyle(null)).toBe("balanced");
  });

  it("formatShortLabel gives the sentence's '2025 car'", () => {
    expect(formatShortLabel("f1_2025")).toBe("2025 car");
    expect(formatShortLabel("f1_2026")).toBe("2026 car");
    expect(formatShortLabel(null)).toBe("-");
  });

  it("trackLabel reads the catalogue, never invents a name", () => {
    const cat = fixtures.catalog();
    expect(trackLabel(cat, "f1_2025", 7)).toBe("Silverstone");
    expect(trackLabel(cat, "f1_2025", 999)).toBe("Track 999");
  });

  it("sessionTypeLabel and sessionLabel", () => {
    expect(sessionTypeLabel("time_trial")).toBe("Time trial");
    expect(sessionTypeLabel(null)).toBe("Session");
    const l = sessionLabel(session());
    expect(l.startsWith("Silverstone · Race · ")).toBe(true);
    expect(l.endsWith(" · James")).toBe(true);
  });
});

describe("values", () => {
  it("unknown is '-' everywhere", () => {
    expect(valueText({ display: "unknown", unit: "%", value: null })).toBe("-");
    expect(displayValue({ display: "unknown", value: null })).toBeNull();
    expect(paramValue(undefined, null)).toBe("-");
    expect(fixed({ decimals: 2 }, Number.NaN)).toBe("-");
    expect(stepsText(null)).toBe("-");
  });

  it("menu values keep their unit and format", () => {
    expect(valueText({ display: "24.3", unit: "psi", value: 24.3 })).toBe("24.3 psi");
    expect(paramValue({ decimals: 2, unit: "°" } as never, -3.5)).toBe("-3.50 °");
    expect(fixed({ decimals: 2 }, -3.5)).toBe(`${MINUS}3.50`);
  });

  it("rowCopyLine keeps the derived mark", () => {
    expect(rowCopyLine(row())).toBe("Front Wing Aero: 21");
    expect(rowCopyLine(row({ derived: true }))).toBe("Front Wing Aero: 21  [pitwall derived]");
    expect(rowCopyLine(row({ value: null, display: "unknown", derived: true }))).toBe("Front Wing Aero: -");
  });

  it("units: deg reads °, others keep a space", () => {
    expect(unitText("deg")).toBe("°");
    expect(unitText(null)).toBeNull();
    expect(unitSuffix("%")).toBe(" %");
    expect(unitSuffix("deg")).toBe("°");
    expect(unitSuffix(null)).toBe("");
  });

  it("stepsText", () => {
    expect(stepsText(1)).toBe("+1 step");
    expect(stepsText(-2)).toBe(`${MINUS}2 steps`);
    expect(stepsText(0.5)).toBe("+0.50 steps");
    expect(stepsText(0)).toBe("±0 steps");
  });

  it("groups rows in menu order with the recommendation's group order", () => {
    const rec = fixtures.recSilverstone();
    const groups = groupRows(rec.rows, rec.groups);
    expect(groups.map((g) => g.group)).toEqual(rec.groups);
    for (const g of groups) {
      const orders = g.rows.map((r) => r.order);
      expect([...orders].sort((a, b) => a - b)).toEqual(orders);
    }
  });

  it("copy text lists every row once, sections in menu order", () => {
    const cat = fixtures.catalog();
    const rec = fixtures.recSilverstone();
    const text = setupCopyText(rec, cat);
    expect(text.split("\n")[0]).toBe("Silverstone · F1 25 cars (2025 regulations) · Race · Dry · Balanced");
    for (const r of rec.rows) expect(text).toContain(`${r.label}: `);
    const sec = sectionCopyText("Aerodynamics", rec.rows.filter((r) => r.group === "Aerodynamics"), "Heading");
    expect(sec.split("\n").slice(0, 2)).toEqual(["Heading", "Aerodynamics"]);
  });
});

describe("rows", () => {
  it("counts confidence and says it in words", () => {
    const c = confidenceCounts([row(), row({ confidence: "medium" }), row({ value: null }), row({ derived: true })]);
    expect(c).toEqual({ high: 2, medium: 1, low: 0, unknown: 1, derived: 1 });
    expect(confidenceSummary(c)).toBe("2 high · 1 medium · 1 unknown");
    expect(confidenceSummary(confidenceCounts([]))).toBe("-");
  });

  it("row chip: no source / derived / confidence and sources", () => {
    expect(rowChip(row({ value: null }))).toMatchObject({ text: "No source", tone: "warning" });
    expect(rowChip(row({ derived: true, confidence: "low" }))).toEqual({ text: "Derived", tone: "default", label: "Derived by Pitwall, low confidence" });
    expect(rowChip(row())).toEqual({ text: "3 sources", tone: "default", label: "3 sources, high confidence" });
    expect(rowChip(row({ confidence: "medium", sources: ["a", "b"] }))).toMatchObject({ text: "Medium · 2 sources", tone: "default" });
    expect(rowChip(row({ confidence: "low", sources: ["a"] }))).toMatchObject({ text: "Low · 1 source", tone: "warning" });
  });

  it("setupCount counts the cited setups", () => {
    expect(setupCount(fixtures.recSilverstone())).toBe(Object.keys(fixtures.recSilverstone().setups).length);
  });

  it("skillPhrase is a whole noun phrase for every level", () => {
    expect(skillPhrase("beginner")).toBe("a beginner");
    expect(skillPhrase("intermediate")).toBe("an intermediate driver");
    expect(skillPhrase("advanced")).toBe("an advanced driver");
  });

  it("styleNote says who the style was chosen for", () => {
    expect(styleNote(null, true, null)).toBe("your choice");
    expect(styleNote(null, false, { name: "Alex", skill: "beginner" })).toBe("chosen for Alex, a beginner");
    expect(styleNote(null, false, { name: "Jo", skill: "intermediate" })).toBe("chosen for Jo, an intermediate driver");
    expect(styleNote(null, false, { name: "Alex", skill: "advanced" })).toBe("chosen for Alex, an advanced driver");
    expect(styleNote(null, false, { name: "Jo", skill: null })).toBe("Jo's skill level is not set: balanced");
    const rec = fixtures.recSilverstone();
    expect(styleNote(rec, false, null)).toBe(rec.style_reason);
  });

  it("a beginner's recommendation is the stable style", () => {
    const rec = fixtures.recSilverstoneBeginner();
    expect(rec.requested_style).toBe("stable");
    expect(rec.skill_source).toBe("request");
  });
});

describe("patches", () => {
  const p = { version: "1.06", date: "2025-07-07" };
  it("predatesPatch follows build.is_current", () => {
    expect(predatesPatch({ patch: "1.05", published: null }, p)).toBe("yes");
    expect(predatesPatch({ patch: "1.12", published: null }, p)).toBe("no");
    expect(predatesPatch({ patch: null, published: null }, p)).toBe("maybe");
    expect(predatesPatch({ patch: null, published: "2025-07-01" }, p)).toBe("yes");
    expect(predatesPatch({ patch: null, published: "2025-07-08" }, p)).toBe("no");
    expect(predatesPatch({ patch: null, published: "2025-07" }, p)).toBe("maybe");
    expect(predatesPatch({ patch: null, published: "2025-06" }, p)).toBe("yes");
    expect(predatesPatch({ patch: null, published: "2025-01-01" }, null)).toBe("no");
  });

  it("patchOlder compares numerically and refuses to guess", () => {
    expect(patchOlder("1.9", "1.12")).toBe(true);
    expect(patchOlder("1.12", "1.9")).toBe(false);
    expect(patchOlder("1.06", "1.06")).toBe(false);
    expect(patchOlder("x", "1.0")).toBe(false);
    expect(patchOlder(null, "1.0")).toBe(false);
  });

  it("sortedSetups: newest first, undated last", () => {
    const s = sortedSetups({ a: { published: "2026-01-01" }, b: { published: null }, c: { published: "2026-08-04" } });
    expect(s.map((x) => x.published)).toEqual(["2026-08-04", "2026-01-01", null]);
  });
});

describe("availability", () => {
  const av = [combo(), combo({ style: "stable", derived: true }), combo({ session: "qualifying" }), combo({ conditions: "wet" })];

  it("servedAs: exact, then balanced, then the other session; never other conditions or format", () => {
    expect(servedAs(av, { ...combo(), style: "stable" })).toEqual({ session: "race", style: "stable" });
    expect(servedAs(av, { ...combo(), style: "aggressive" })).toEqual({ session: "race", style: "balanced" });
    expect(servedAs([combo({ session: "qualifying" })], { ...combo() })).toEqual({ session: "qualifying", style: "balanced" });
    expect(servedAs([combo({ conditions: "wet" })], { ...combo() })).toBeNull();
    expect(servedAs([combo({ car_format: "f1_2026" })], { ...combo() })).toBeNull();
  });

  it("servedNote names the stand-in", () => {
    expect(servedNote(av, { ...combo() })).toBe("");
    expect(servedNote(av, { ...combo(), style: "aggressive" })).toBe("balanced shown");
    expect(servedNote([combo({ session: "qualifying" })], { ...combo() })).toBe("qualifying setup shown");
    expect(servedNote([], { ...combo() })).toBe("no setup");
  });

  it("trackHasSetup, sortAlternatives, comboLabel, comboKey", () => {
    expect(trackHasSetup(av, "f1_2025", 7)).toBe(true);
    expect(trackHasSetup(av, "f1_2026", 7)).toBe(false);
    const sorted = sortAlternatives([combo({ car_format: "f1_2026" }), combo({ conditions: "wet" }), combo()], combo());
    expect(sorted[0]).toEqual(combo());
    expect(sorted[2]?.car_format).toBe("f1_2026");
    const cat = fixtures.catalog();
    expect(comboLabel(combo({ conditions: "wet" }), cat, { car_format: "f1_2025", track_id: 7 })).toBe("Wet · Race · Balanced");
    expect(comboLabel(combo({ car_format: "f1_2026", track_id: 13 }), cat, { car_format: "f1_2025", track_id: 7 })).toBe(
      "Suzuka · 2026 car · Dry · Race · Balanced",
    );
    expect(comboKey(combo())).toBe("f1_2025:7:race:dry:balanced");
  });

  it("the recorded 404 lists alternatives for the same format only when the track is not drivable", () => {
    const u = fixtures.unavailableImola2026().body.detail;
    expect(u.alternatives.every((a) => a.car_format === "f1_2026")).toBe(true);
  });
});

describe("the request in the route query", () => {
  it("parses valid values and drops the rest", () => {
    expect(parseSetupQuery("format=f1_2026&track=7&session=qualifying&conditions=wet&style=stable&driver=2")).toEqual({
      format: "f1_2026",
      track: 7,
      session: "qualifying",
      conditions: "wet",
      style: "stable",
      driver: 2,
    });
    expect(parseSetupQuery("format=f1_2024&track=-1&session=practice&conditions=snow&style=x&driver=a")).toEqual({
      format: null,
      track: null,
      session: null,
      conditions: null,
      style: null,
      driver: null,
    });
  });

  it("setupQueryValues keeps the spec's order and leaves unset values out", () => {
    expect(Object.keys(setupQueryValues({ format: "f1_2025", track: 7, session: "race", conditions: "dry" }))).toEqual([
      "format",
      "track",
      "session",
      "conditions",
      "style",
      "driver",
    ]);
    expect(setupQueryValues({ format: "f1_2025" }).style).toBeNull();
  });

  it("resolveRequest seeds from the latest real F1 session (Svelte behaviour)", () => {
    const cat = fixtures.catalog();
    const q = parseSetupQuery("");
    const sessions = [
      session({ id: "syn", synthetic: true, track_id: "f1:13" }),
      session({ id: "gt7", game: "gt7", track_id: "gt7:sf:1" }),
      session({ id: "real", track_id: "f1:13", session_type: "qualifying", weather: { condition: "heavy_rain" } }),
    ];
    const r = resolveRequest(q, cat, sessions, null);
    expect(r).toEqual({ format: "f1_2025", track: 13, session: "qualifying", conditions: "wet", style: null });
    expect(queryIsComplete(q, r!)).toBe(false);
  });

  it("resolveRequest uses the remembered format and keeps what the query names", () => {
    const cat = fixtures.catalog();
    const r = resolveRequest(parseSetupQuery("track=7&session=race&conditions=dry&style=aggressive"), cat, [], "f1_2026");
    expect(r).toEqual({ format: "f1_2026", track: 7, session: "race", conditions: "dry", style: "aggressive" });
  });

  it("a track the format does not have falls back to the first track with a setup", () => {
    const cat = fixtures.catalog();
    const f26 = cat.formats.find((f) => f.id === "f1_2026")!;
    const missing = cat.formats.find((f) => f.id === "f1_2025")!.tracks.find((t) => !f26.tracks.some((x) => x.id === t.id));
    expect(missing).toBeDefined();
    const r = resolveRequest(parseSetupQuery(`format=f1_2026&track=${missing!.id}`), cat);
    expect(r?.track).not.toBe(missing!.id);
    expect(trackHasSetup(cat.available, "f1_2026", r!.track)).toBe(true);
  });

  it("queryIsComplete", () => {
    const r = { format: "f1_2025", track: 7, session: "race", conditions: "dry", style: null } as const;
    expect(queryIsComplete(parseSetupQuery("format=f1_2025&track=7&session=race&conditions=dry"), r)).toBe(true);
  });

  it("the remembered format survives broken storage", () => {
    const m = new Map<string, string>();
    const storage = { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) };
    rememberFormat("f1_2026", storage);
    expect(storedFormat(storage)).toBe("f1_2026");
    m.set("pitwall-carsetup-format", "nonsense");
    expect(storedFormat(storage)).toBeNull();
    const broken = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    };
    expect(storedFormat(broken)).toBeNull();
    expect(() => rememberFormat("f1_2025", broken)).not.toThrow();
  });
});

describe("sessions", () => {
  it("f1TrackId, sessionKindOf, conditionsOf mirror carsetup.context", () => {
    expect(f1TrackId("f1:13")).toBe(13);
    expect(f1TrackId("synthetic:f1:13")).toBeNull();
    expect(f1TrackId("gt7:sf:1")).toBeNull();
    expect(sessionKindOf("practice")).toBe("race");
    expect(sessionKindOf("time_trial")).toBe("qualifying");
    expect(sessionKindOf("unknown")).toBeNull();
    expect(conditionsOf({ condition: "storm" })).toBe("wet");
    expect(conditionsOf({ condition: "overcast" })).toBe("dry");
    expect(conditionsOf({})).toBeNull();
  });

  it("setupSessions keeps the catalogue's game only", () => {
    expect(setupSessions([session(), session({ id: "g", game: "gt7" })], "f1_25").map((s) => s.id)).toEqual(["s1"]);
    expect(setupSessions([session()], null)).toEqual([]);
  });

  it("latestSessionFor: the driver's newest real session, then anyone's, synthetic last", () => {
    const list = [
      session({ id: "syn", synthetic: true, driver_id: 2 }),
      session({ id: "james", driver_id: 1 }),
      session({ id: "alex", driver_id: 2 }),
    ];
    expect(latestSessionFor(list, "f1_25", 2)?.id).toBe("alex");
    expect(latestSessionFor(list, "f1_25", 3)?.id).toBe("james");
    expect(latestSessionFor([session({ id: "syn", synthetic: true })], "f1_25", 1)?.id).toBe("syn");
    expect(latestSessionFor([], "f1_25", 1)).toBeNull();
    // the track on screen first (the default pick), never a synthetic one there
    const tracks = [session({ id: "melb", track_id: "f1:0" }), session({ id: "suz-syn", track_id: "f1:13", synthetic: true }), session({ id: "suz", track_id: "f1:13" })];
    expect(latestSessionFor(tracks, "f1_25", 1, 13)?.id).toBe("suz");
    expect(latestSessionFor(tracks, "f1_25", 1, 7)?.id).toBe("melb");
  });
});

describe("your setup vs recommended", () => {
  const d = (o: Partial<DiffRow>): DiffRow => ({
    key: "k",
    label: "K",
    group: "G",
    order: 1,
    unit: null,
    yours: 1,
    yours_display: "1",
    recommended: 1,
    recommended_display: "1",
    delta: 0,
    steps: 0,
    direction: "same",
    magnitude: "same",
    in_range: true,
    confidence: "high",
    derived: false,
    explanation: "",
    ...o,
  });

  it("changed rows first, each part in menu order", () => {
    const rows = [d({ key: "a", order: 1 }), d({ key: "b", order: 2, direction: "lower" }), d({ key: "c", order: 3, in_range: false }), d({ key: "z", order: 0, direction: "higher" })];
    expect(changedFirst(rows).map((r) => r.key)).toEqual(["z", "b", "c", "a"]);
    expect(isChanged(d({ direction: "unknown" }))).toBe(false);
  });

  it("the recorded Suzuka comparison puts the 14 differing rows first", () => {
    const s = fixtures.sessionDiff();
    const rows = changedFirst(s.diff!.rows);
    const changed = rows.filter(isChanged).length;
    expect(changed).toBe(s.diff!.differing);
    expect(rows.slice(0, changed).every(isChanged)).toBe(true);
  });

  it("differenceText: recommended minus yours, signed, with the unit", () => {
    expect(differenceText(d({ delta: 7, direction: "higher" }))).toBe("+7");
    expect(differenceText(d({ delta: -15, unit: "%", direction: "lower" }))).toBe(`${MINUS}15 %`);
    expect(differenceText(d({ delta: 0.25, unit: "deg", direction: "higher" }), 2)).toBe("+0.25°");
    expect(differenceText(d({ delta: 0, direction: "same" }))).toBe("Same");
    expect(differenceText(d({ delta: null, direction: "unknown" }))).toBe("-");
  });

  it("the session that needs a car format says so and offers alternatives on its track", () => {
    const s = fixtures.sessionNeedsFormat();
    expect(s.needs).toEqual(["car_format"]);
    expect(s.recommendation).toBeNull();
    expect(s.unavailable?.alternatives.every((a) => a.track_id === s.context.track_id)).toBe(true);
  });

  it("listText", () => {
    expect(listText([])).toBe("");
    expect(listText(["car format"])).toBe("car format");
    expect(listText(["a", "b", "c"])).toBe("a, b or c");
  });
});

describe("experiments", () => {
  it("experimentStep: Proposed → Running → Concluded", () => {
    expect(experimentStep(exp())).toBe(0);
    expect(experimentStep(exp({ status: "running" }))).toBe(1);
    expect(experimentStep(exp({ status: "concluded" }))).toBe(3);
    expect(experimentStep(exp({ status: "abandoned" }))).toBe(0);
    expect(experimentStep(exp({ status: "abandoned", after_session_id: "x" }))).toBe(1);
  });

  it("the edited experiments fixture: running first, the concluded one complete", () => {
    const list = sortExperiments(fixtures.experimentsEdited());
    expect(list.map((e) => e.status)).toEqual(["running", "concluded"]);
    expect(list.map(experimentStep)).toEqual([1, 3]);
    expect(fixtures.meta("carsetup-experiments-edited").edited).toBeDefined();
  });

  it("sortExperiments: open ones first, newest first", () => {
    const list = [exp({ id: 1, status: "concluded", created_unix: 300 }), exp({ id: 2, created_unix: 100 }), exp({ id: 3, status: "running", created_unix: 200 })];
    expect(sortExperiments(list).map((e) => e.id)).toEqual([3, 2, 1]);
  });

  it("after candidates: same game, track and car, driven later", () => {
    const sessions = [
      session({ id: "before", started_unix: 100 }),
      session({ id: "later", started_unix: 200 }),
      session({ id: "earlier", started_unix: 50 }),
      session({ id: "other-track", started_unix: 300, track_id: "f1:13" }),
      session({ id: "other-car", started_unix: 300, car_id: "f1:team:9" }),
      session({ id: "unknown-car", started_unix: 400, car_id: null }),
    ];
    expect(afterCandidates(exp(), sessions).map((s) => s.id)).toEqual(["later", "unknown-car"]);
    expect(afterFor(exp(), sessions, null)).toBe("later");
    expect(afterFor(exp(), sessions, "unknown-car")).toBe("unknown-car");
    expect(afterFor(exp(), sessions, "earlier")).toBe("later");
    expect(afterFor(exp({ after_session_id: "linked" }), sessions, null)).toBe("linked");
  });

  it("alreadyTesting matches an open experiment with the same change", () => {
    const x = { key: "rear_wing", label: "Rear Wing Aero", from_value: 18, to_value: 25, text: "" };
    expect(alreadyTesting([exp()], x, "before")).toBe(true);
    expect(alreadyTesting([exp({ status: "concluded" })], x, "before")).toBe(false);
    expect(alreadyTesting([exp()], { ...x, to_value: 24 }, "before")).toBe(false);
  });

  it("parseNumber accepts a typed minus and a decimal comma", () => {
    expect(parseNumber("−3.5")).toBe(-3.5);
    expect(parseNumber(" 3,25 ")).toBe(3.25);
    expect(parseNumber("12")).toBe(12);
    expect(parseNumber("1e3")).toBeNull();
    expect(parseNumber("")).toBeNull();
  });

  it("valueProblem checks the confirmed menu range only", () => {
    const cat = fixtures.catalog();
    const fw = cat.parameters.find((p) => p.key === "front_wing");
    expect(valueProblem(fw, "f1_2025", null, 10)).toBe("Enter a number");
    expect(valueProblem(fw, "f1_2025", 10, 10)).toBe("That is the value you already have");
    expect(valueProblem(fw, "f1_2025", 51, 10)).toBe("Outside the menu range 0 to 50");
    expect(valueProblem(fw, "f1_2025", 25, 10)).toBeNull();
    expect(valueProblem(undefined, "f1_2025", 25, 10)).toBeNull();
  });

  it("setupValue reads numbers only", () => {
    expect(setupValue({ rear_wing: 18, x: "a" }, "rear_wing")).toBe(18);
    expect(setupValue({ x: "a" }, "x")).toBeNull();
    expect(setupValue(null, "x")).toBeNull();
  });
});
