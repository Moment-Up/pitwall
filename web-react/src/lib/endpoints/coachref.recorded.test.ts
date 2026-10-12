// The coachref JSON contract checked on real server output. The fixtures in src/test/fixtures/coachref-recorded/ are
// bodies a scratch Pitwall server sent while the owner's real F1 25 PS5 captures streamed into it over loopback UDP
// (demo drivers Ann and Ben; the captures themselves are not committed). The key sets below mirror the backend's
// contract table (tests/coachref_support.py CONTRACT): a key added or removed on either side fails here or there.
// The hand-written fixtures (src/test/fixtures/coachref/) are held to the same key sets, and the Drive and Review
// view functions run over the recorded bodies without leaking a JS value or telling anyone to brake later.

import { describe, expect, it } from "vitest";
import { snap } from "../drive/testkit";
import { drillBlock, drillChip, drillCoach, kindChoices } from "../drive/drill";
import { pickerRows, refControlView } from "../drive/reference";
import type { SnapshotNext } from "../drive/types";
import { drillRows } from "../review/drills";
import type { CandidatesResponse, DrillOptionsResponse, DrillView, RefOptionsResponse } from "./coachref";

const RECORDED = import.meta.glob<{ _fixture: { tier: string; source: string; moment: string }; body: unknown }>(
  "../../test/fixtures/coachref-recorded/*.json",
  { eager: true, import: "default" },
);
const HAND = import.meta.glob<Record<string, unknown>>("../../test/fixtures/coachref/*.json", { eager: true, import: "default" });

function file<T>(set: Record<string, unknown>, name: string): T {
  const hit = Object.entries(set).find(([p]) => p.endsWith(`/${name}.json`));
  if (!hit) throw new Error(`no fixture ${name}`);
  return structuredClone(hit[1]) as T;
}
const rec = <T>(name: string): T => file<{ body: T }>(RECORDED, name).body;
const hand = <T>(name: string): T => file<T>(HAND, name);

const K = (...keys: string[]) => new Set(keys);
const CONTRACT = {
  ReferenceChoice: K("driver_id", "kind", "target_driver_id", "lap_id", "scope", "game", "track_id", "label", "updated_unix"),
  ReferenceDescriptor: K(
    "lap_id", "lap_number", "lap_time_ms", "session_id", "kind", "own", "pinned", "driver_id", "driver_name", "set_unix",
    "label", "label_to", "ref_name", "brake_clamped", "frozen",
  ),
  RefOptionLap: K("lap_id", "lap_number", "lap_time_ms", "set_unix", "driver_id", "driver_name", "session_id", "car_name"),
  RefOption: K("kind", "target_driver_id", "lap_id", "label", "available", "reason", "warnings", "lap", "selected"),
  RefOptionsResponse: K("driver_id", "context", "choice", "has_track_override", "options", "applies"),
  RefContext: K("game", "track_id", "track_name", "car_id", "car_name", "track_length_m"),
  CandidatesResponse: K("lap_id", "driver_id", "groups"),
  CandidatesGroup: K("id", "title", "options"),
  ChoiceResponse: K("choice", "applies"),
  ChoiceRows: K("all_tracks", "track", "effective"),
  DrillAttempt: K(
    "attempt", "lap_id", "lap_number", "value", "target", "delta", "outcome", "reason", "corner_time_s",
    "corner_time_delta_s", "text", "short",
  ),
  DrillView: K(
    "id", "driver_id", "session_id", "game", "track_id", "car_id", "corner", "corner_label", "corner_voice", "kind",
    "skill_label", "source", "laps_target", "target", "tolerance", "unit", "baseline", "target_text", "note", "reference",
    "status", "stop_reason", "started_unix", "ended_unix", "attempts", "hits", "scored", "best", "best_delta", "trend",
    "summary_text", "synthetic",
  ),
  DrillReference: K("lap_id", "kind", "driver_name", "label"),
  DrillOption: K(
    "kind", "skill_label", "available", "reason", "target", "unit", "tolerance", "baseline", "target_text", "note",
    "tolerance_choices", "suggested",
  ),
  DrillOptionsResponse: K("corner", "corner_label", "corner_voice", "available", "reason", "laps_choices", "default_laps", "kinds"),
  SnapshotCoachref: K("driver_id", "choice", "used_kind", "reason", "pending", "drill"),
  DrillPointDrill: K("id", "attempt", "of", "hits", "outcome", "done"),
} as const;
type Name = keyof typeof CONTRACT;

/** Every key-set mismatch in `o` (as `Name` at `path`), descending into the contract's nested types. */
function shape(name: Name, o: unknown, path = name as string): string[] {
  if (o === null || typeof o !== "object" || Array.isArray(o)) return [`${path}: not an object`];
  const want = CONTRACT[name];
  const got = new Set(Object.keys(o).filter((k) => k !== "_fixture"));
  const errs: string[] = [];
  const missing = [...want].filter((k) => !got.has(k));
  const extra = [...got].filter((k) => !want.has(k));
  if (missing.length || extra.length) errs.push(`${path}: missing [${missing.join(", ")}] extra [${extra.join(", ")}]`);
  const v = o as Record<string, unknown>;
  const sub = (n: Name, x: unknown, p: string) => (x == null ? [] : shape(n, x, p));
  const each = (n: Name, xs: unknown, p: string) => (Array.isArray(xs) ? xs.flatMap((x, i) => shape(n, x, `${p}[${i}]`)) : [`${p}: not a list`]);
  if (name === "RefOptionsResponse") {
    errs.push(...sub("RefContext", v.context, `${path}.context`), ...sub("ReferenceChoice", v.choice, `${path}.choice`));
    errs.push(...each("RefOption", v.options, `${path}.options`));
  } else if (name === "RefOption") {
    errs.push(...sub("RefOptionLap", v.lap, `${path}.lap`));
  } else if (name === "CandidatesResponse") {
    errs.push(...each("CandidatesGroup", v.groups, `${path}.groups`));
  } else if (name === "CandidatesGroup") {
    errs.push(...each("RefOption", v.options, `${path}.options`));
  } else if (name === "ChoiceResponse") {
    errs.push(...sub("ReferenceChoice", v.choice, `${path}.choice`));
  } else if (name === "ChoiceRows") {
    for (const k of ["all_tracks", "track", "effective"]) errs.push(...sub("ReferenceChoice", v[k], `${path}.${k}`));
  } else if (name === "DrillView") {
    errs.push(...sub("DrillReference", v.reference, `${path}.reference`), ...each("DrillAttempt", v.attempts, `${path}.attempts`));
  } else if (name === "DrillOptionsResponse") {
    errs.push(...each("DrillOption", v.kinds, `${path}.kinds`));
  } else if (name === "SnapshotCoachref") {
    errs.push(...sub("ReferenceChoice", v.choice, `${path}.choice`), ...sub("DrillView", v.drill, `${path}.drill`));
  }
  return errs;
}

interface LiveBlock {
  reference?: SnapshotNext["reference"];
  coachref?: SnapshotNext["coachref"];
  coach?: SnapshotNext["coach"];
  cues_drill_corner?: string | null;
  observations?: Record<string, unknown>[];
}

/** A minimal live snapshot (no track model: labels come from the server) carrying a recorded live block. */
function live(name: string): SnapshotNext {
  const b = rec<LiveBlock>(name);
  const s = snap({ track_model: null } as Partial<SnapshotNext>);
  if (b.reference !== undefined) s.reference = b.reference;
  if (b.coachref !== undefined) s.coachref = b.coachref;
  if (b.coach !== undefined) s.coach = b.coach;
  return s;
}

/** Every string in a value, one per line. */
function words(v: unknown): string {
  const out: string[] = [];
  const walk = (x: unknown) => {
    if (typeof x === "string") out.push(x);
    else if (Array.isArray(x)) x.forEach(walk);
    else if (x && typeof x === "object") Object.values(x).forEach(walk);
  };
  walk(v);
  return out.join("\n");
}
const FORBIDDEN = [/brake later/i, /later braking point/i, /\bundefined\b/, /\bNaN\b/, /\[object Object\]/];

describe("recorded fixtures say where they came from", () => {
  it("every file is tier recorded with its moment", () => {
    const entries = Object.entries(RECORDED);
    expect(entries.length).toBeGreaterThanOrEqual(14);
    for (const [p, f] of entries) {
      expect(f._fixture.tier, p).toBe("recorded");
      expect(f._fixture.moment.length, p).toBeGreaterThan(10);
      // demo names only: the household in these bodies is Ann and Ben
      for (const m of JSON.stringify(f.body).matchAll(/"driver_name":\s*"([^"]*)"/g)) expect(["Ann", "Ben"], p).toContain(m[1]);
    }
  });
});

describe("the server's JSON matches the contract key for key (spec 6.2 / 6.3)", () => {
  const cases: [Name, string][] = [
    ["RefOptionsResponse", "options-lv-live"],
    ["RefOptionsResponse", "options-no-live"],
    ["RefOptionsResponse", "options-austria-assist"],
    ["ChoiceResponse", "choice-put"],
    ["ChoiceRows", "choice-rows"],
    ["CandidatesResponse", "candidates-lv"],
    ["DrillOptionsResponse", "drill-options-austria"],
    ["DrillView", "drill-active-lv"],
    ["DrillView", "drill-stopped-austria"],
  ];
  it.each(cases)("%s: %s", (name, fx) => {
    expect(shape(name, rec(fx))).toEqual([]);
  });

  it("drill history is a list of DrillView", () => {
    const list = rec<DrillView[]>("drills-history-austria");
    expect(list.length).toBeGreaterThan(0);
    expect(list.flatMap((d, i) => shape("DrillView", d, `[${i}]`))).toEqual([]);
  });

  it("live: the reference descriptor, coachref and a drill's coach point", () => {
    for (const n of ["live-lv-lap1", "live-lv-attempt1", "live-austria-fallback"]) {
      const b = rec<LiveBlock>(n);
      expect(shape("ReferenceDescriptor", b.reference), n).toEqual([]);
      expect(shape("SnapshotCoachref", b.coachref), n).toEqual([]);
    }
    const coach = rec<LiveBlock>("live-lv-attempt1").coach!;
    expect(coach.drill_only).toBe(true);
    expect(coach.picked).toHaveLength(1);
    const point = coach.picked[0]!;
    expect(point.kind).toBe("drill");
    expect(shape("DrillPointDrill", point.drill)).toEqual([]);
    expect(rec<LiveBlock>("live-lv-attempt1").cues_drill_corner).toBe(point.corner);
    // observations against another driver carry their name
    for (const o of rec<LiveBlock>("live-lv-lap1").observations ?? []) expect(o).toHaveProperty("ref_name");
  });

  it("compare: the descriptor of lap A relative to lap B's driver, observations reworded", () => {
    const c = rec<{ reference: unknown; observations: { text: string; ref_name: string | null }[] }>("compare-lv");
    expect(shape("ReferenceDescriptor", c.reference)).toEqual([]);
    expect(c.observations.length).toBeGreaterThan(0);
    for (const o of c.observations) {
      expect(o.ref_name).toBe("Ben");
      expect(o.text).toContain("Ben");
      expect(o.text).not.toMatch(/your reference/);
    }
  });

  it("the hand-written fixtures follow the same key sets", () => {
    const cases: [Name, string, (x: Record<string, unknown>) => unknown][] = [
      ["RefOptionsResponse", "options-suzuka-sam", (x) => x],
      ["RefOptionsResponse", "options-no-live-session", (x) => x],
      ["RefOptionsResponse", "options-gt7-unknown-car", (x) => x],
      ["ChoiceResponse", "choice-next-lap", (x) => x],
      ["CandidatesResponse", "candidates-austria-66", (x) => x],
      ["DrillOptionsResponse", "drill-options-t11", (x) => x],
      ["DrillOptionsResponse", "drill-options-learning", (x) => x],
      ["DrillOptionsResponse", "drill-options-synthetic", (x) => x],
      ["DrillView", "drill-active", (x) => x],
      ["DrillView", "drill-completed", (x) => x],
      ["SnapshotCoachref", "live-drill", (x) => x.coachref],
      ["SnapshotCoachref", "live-sam", (x) => x.coachref],
      ["SnapshotCoachref", "live-fallback", (x) => x.coachref],
      ["ReferenceDescriptor", "live-drill", (x) => x.reference],
      ["ReferenceDescriptor", "live-sam", (x) => x.reference],
    ];
    const errs = cases.flatMap(([name, fx, pick]) => shape(name, pick(hand(fx)), `${fx}:${name}`));
    expect(errs).toEqual([]);
    const history = hand<unknown[]>("drills-history-suzuka");
    expect(history.flatMap((d, i) => shape("DrillView", d, `drills-history-suzuka[${i}]`))).toEqual([]);
  });
});

describe("Drive and Review views on the recorded bodies", () => {
  const now = 1_791_750_000;

  it("the picker: Your best, the family record and Ben's best, with times; nothing leaks", () => {
    const rows = pickerRows(rec<RefOptionsResponse>("options-lv-live"), now);
    const titles = rows.main.map((r) => r.title);
    expect(titles).toContain("Your best");
    expect(titles).toContain("Ben's best");
    const ben = rows.main.find((r) => r.title === "Ben's best")!;
    expect(ben.disabled).toBe(false);
    expect(ben.detail).toMatch(/^1:36\.953/);
    for (const re of FORBIDDEN) expect(words(rows)).not.toMatch(re);
  });

  it("Ben's best unavailable at Austria shows the server's reason on its row", () => {
    const rows = pickerRows(rec<RefOptionsResponse>("options-austria-assist"), now);
    const ben = rows.main.find((r) => r.title === "Ben's best");
    expect(ben).toMatchObject({ disabled: true, reason: "Ben's laps here used a different braking assist" });
  });

  it("the delta control: Delta to · Ben's best; the fallback names the reason", () => {
    expect(refControlView(live("live-lv-lap1"), { beginner: false }).text).toBe("Delta to · Ben's best");
    const fb = refControlView(live("live-austria-fallback"), { beginner: false });
    expect(fb.text).toBe("Delta to · Your best");
    expect(fb.reason).toBe("Using your best: Ben's laps here used a different braking assist");
  });

  it("a running drill (chip, Ready block, coach card) and a stopped one (result)", () => {
    const s = live("live-lv-attempt1");
    const chip = drillChip(s)!;
    expect(chip.text).toMatch(/^DRILL · T12 · 1\/5 · 1 ✓$/);
    const block = drillBlock(s)!;
    expect(block.kind).toBe("active");
    const point = s.coach!.picked[0]!;
    const coach = drillCoach(s, point.corner, false, true)!;
    expect(coach.tag).toBe("drill");
    expect(coach.text).toBe(point.short);
    const stopped = live("live-lv-attempt1");
    stopped.coachref!.drill = rec<DrillView>("drill-stopped-austria");
    // an Austria result at Las Vegas is another session's: this Ready card keeps its own points (acceptance B3)
    expect(drillBlock(stopped)!.kind).toBe("none");
    stopped.coachref!.drill = { ...rec<DrillView>("drill-stopped-austria"), session_id: stopped.session_id };
    const res = drillBlock(stopped)!;
    expect(res.kind).toBe("result");
    for (const re of FORBIDDEN) expect(words([chip, block, coach, res])).not.toMatch(re);
  });

  it("drill options and history rows", () => {
    const choices = kindChoices(rec<DrillOptionsResponse>("drill-options-austria"));
    expect(choices.map((c) => c.kind)).toEqual(["brake_point", "min_speed", "exit_speed", "entry_speed"]);
    expect(choices.some((c) => !c.disabled)).toBe(true);
    const rows = drillRows(rec<DrillView[]>("drills-history-austria"), null, now * 1000);
    expect(rows.length).toBeGreaterThan(0);
    const cands = rec<CandidatesResponse>("candidates-lv");
    for (const re of FORBIDDEN) expect(words([choices, rows, cands])).not.toMatch(re);
  });
});
