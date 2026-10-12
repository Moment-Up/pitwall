import { describe, expect, it } from "vitest";
import { CALLS_AFTER_FIRST_LAP, CUE_LAST_SHOWN_S, JUST_PASSED_M, callsModeText, cueText, cueView, isRadioOff, justPassedM, lastCueOutcome, wrappedCall } from "./cues";
import { AI_REFERENCE, driverFocus, isFieldPlan } from "./plan";
import { fixture } from "./testkit";
import { MINUS } from "./text";
import type { CueSnapshot } from "./types";

function cues(over: Partial<CueSnapshot> = {}): CueSnapshot {
  return {
    mode: "focus",
    armed: true,
    muted: null,
    reason: null,
    ref_lap_number: 4,
    focus: ["T15"],
    cues: [],
    next: { corner: "T15", text: "T15 brake", kind: "brake", in_m: 249.6 },
    last: null,
    timing: { latency_ms: 250, path: "pcm", margin_m: 5 },
    ...over,
  };
}

describe("cue band", () => {
  it("shows the call for the shown corner with its distance", () => {
    expect(cueView(cues(), "T15")).toEqual({
      next: { kind: "brake", chip: "BRAKE", ai: false, text: "T15 brake", inM: 250, inText: "250 m", corner: "T15" },
      note: null,
      muted: false,
      radioOff: false,
      ai: false,
    });
    const marker = cueView(cues({ next: { corner: "T15", text: "T15", kind: "marker", in_m: 80 } }), "T15");
    expect(marker.next).toMatchObject({ chip: "MARKER", text: "T15" });
  });

  it("names the next call as a secondary line when it is for another corner", () => {
    expect(cueView(cues({ next: { corner: "T3", text: "T3 brake", kind: "brake", in_m: 1400 } }), "T15")).toEqual({
      next: null,
      note: "Next call: T3 brake · 1.4 km",
      muted: false,
      radioOff: false,
      ai: false,
    });
  });

  it("shows the official label in place of the learned name (real Suzuka: learned T7 = T11)", () => {
    const s = fixture("recorded-suzuka-on-track-brake-ahead");
    expect(cueView(s.cues, "T7", s.track_model).next).toMatchObject({ chip: "BRAKE", text: "T11 brake", inM: 343 });
    expect(cueText("T7 brake", "T7", s.track_model)).toBe("T11 brake");
    expect(cueText("T10 brake", "T1", s.track_model)).toBe("T10 brake"); // only a whole-word name is replaced
    expect(cueText("T7 brake", "T7", null)).toBe("T7 brake");
    // a server that already names the corner as the track view does keeps its text (it is the label already)
    expect(cueText("T11 brake", "T7", s.track_model)).toBe("T11 brake");
  });

  it("never doubles a label that extends the learned name (learned T1 = official 'T1 (2)')", () => {
    const s = fixture("recorded-suzuka-on-track-brake-ahead");
    const model = { ...s.track_model!, corners: s.track_model!.corners.map((c) => (c.name === "T7" ? { ...c, label: "T7 (2)" } : c)) };
    expect(cueText("T7 brake", "T7", model)).toBe("T7 (2) brake"); // an older server: learned name in the text
    expect(cueText("T7 (2) brake", "T7", model)).toBe("T7 (2) brake"); // a newer one: the label already there
  });

  it("says when calls are off, paused, or why there is no plan", () => {
    expect(cueView(cues({ mode: "off" }), "T15").note).toBe("Calls off");
    expect(cueView(cues({ muted: "safety car" }), "T15", null, "safety_car")).toEqual({
      next: null,
      note: "Calls paused: safety car",
      muted: true,
      radioOff: false,
      ai: false,
    });
    expect(cueView(cues({ muted: "no radio connected" }), "T15", null, "safety_car").note).toBe("Calls paused: safety car");
    expect(cueView(cues({ muted: "safety car" }), "T15").note).toBe("Calls paused: safety car");
    expect(cueView(cues({ muted: "quiet mode" }), "T15")).toMatchObject({ next: null, note: "Calls paused: quiet mode", muted: true });
    expect(cueView(cues({ next: null, reason: "no reference lap yet" }), "T15")).toEqual({
      next: null,
      note: "Braking calls start after your first clean lap", // never the server's reason ("new driver: waiting...")
      muted: true,
      radioOff: false,
      ai: false,
    });
    expect(cueView(cues({ next: null }), "T15").note).toBe("No call ahead");
    expect(cueView(undefined, "T15")).toEqual({ next: null, note: null, muted: true, radioOff: false, ai: false });
    // coachref: the delta already has its reference (published before the first lap): calls wait for a lap
    const early = cueView(cues({ next: null, reason: "no reference lap yet" }), "T15", null, null, false, null, true);
    expect(early.note).toBe(CALLS_AFTER_FIRST_LAP);
    for (const reason of ["no reference lap for this driver", "new driver: waiting for a lap against their reference"]) {
      expect(cueView(cues({ next: null, reason }), "T15", null, null, false, null, true).note, reason).toBe(CALLS_AFTER_FIRST_LAP);
    }
    expect(cueView(cues({ next: null, reason: "no braking points of your own yet" }), "T15", null, null, false, null, true).note).toBe(
      "No braking points of your own yet",
    );
    expect(CALLS_AFTER_FIRST_LAP).toBe("Braking calls start after your first lap");
  });

  it("keeps the look-ahead with a Radio off chip when nobody is listening", () => {
    for (const muted of ["radio off", "no radio connected"]) {
      const v = cueView(cues({ muted }), "T15");
      expect(v.next?.text, muted).toBe("T15 brake");
      expect(v.radioOff, muted).toBe(true);
      expect(v.note, muted).toBeNull();
    }
    expect(isRadioOff("voice off")).toBe(false);
  });

  it("blanks the call's distance when the position is not current", () => {
    expect(cueView(cues(), "T15", null, null, true).next).toMatchObject({ text: "T15 brake", inM: null, inText: "-" });
    expect(cueView(cues({ next: { corner: "T3", text: "T3 brake", kind: "brake", in_m: 1400 } }), "T15", null, null, true).note).toBe(
      "Next call: T3 brake · -",
    );
  });

  it("pauses for a red flag and in the pit lane", () => {
    expect(cueView(cues(), "T15", null, "red_flag")).toEqual({ next: null, note: "Calls paused", muted: true, radioOff: false, ai: false });
    expect(cueView(cues(), "T15", null, "pit_lane").note).toBe("Calls resume on your out lap");
  });

  it("words the braking calls mode", () => {
    expect(callsModeText(cues())).toBe("Braking calls: Focus corners");
    expect(callsModeText(cues({ mode: "all" }))).toBe("Braking calls: All corners");
    expect(callsModeText(undefined)).toBeNull();
  });
});

describe("a call the car has just passed (the server reports it a lap later)", () => {
  const L = 5890;
  // cues.py _next_cue: T15's target passed 80 m ago comes back as the next lap's call, in_m = target + L - position.
  const wrapped = { corner: "T15", text: "T15 brake", kind: "brake" as const, in_m: L - 80 };

  it("never shows the shown corner's call a lap away ('brake in 5 810 m')", () => {
    const v = cueView(cues({ next: wrapped }), "T15", null, null, false, { toApexM: 120, lapLengthM: L });
    expect(v.next).toBeNull();
    expect(v.note).toBe("No call ahead");
  });

  it("drops it for the shown corner by its apex even when the lap length is unknown", () => {
    const passed = { ...wrapped, in_m: 4311 };
    expect(wrappedCall(passed, "T15", { toApexM: 120, lapLengthM: null })).toBe(true);
    expect(cueView(cues({ next: passed }), "T15", null, null, false, { toApexM: 120, lapLengthM: null }).next).toBeNull();
  });

  it("never shows it as the next call either", () => {
    const v = cueView(cues({ next: { ...wrapped, corner: "T3", text: "T3 brake" } }), "T15", null, null, false, {
      toApexM: 400,
      lapLengthM: L,
    });
    expect(v.note).toBe("No call ahead");
    expect(v.note).not.toContain("km");
  });

  it("keeps a call that is really ahead: before the shown corner's apex, or far enough round the lap", () => {
    expect(cueView(cues(), "T15", null, null, false, { toApexM: 400, lapLengthM: L }).next).toMatchObject({ inM: 250 });
    expect(wrappedCall({ corner: "T3", in_m: L - JUST_PASSED_M - 1 }, "T15", { toApexM: 400, lapLengthM: L })).toBe(false);
    expect(wrappedCall({ corner: "T3", in_m: 1400 }, "T15", { toApexM: 400, lapLengthM: L })).toBe(false);
    // without position context nothing is dropped (as before)
    expect(cueView(cues({ next: wrapped }), "T15").next).toMatchObject({ inM: L - 80 });
  });

  it("on a short lap the just-passed window is at most a quarter of the lap, not 500 m", () => {
    const short = 1000; // e.g. a karting layout: 500 m would hide every call more than half a lap away
    expect(justPassedM(short)).toBe(250);
    expect(justPassedM(L)).toBe(JUST_PASSED_M);
    const pass = { toApexM: 900, lapLengthM: short };
    expect(wrappedCall({ corner: "T3", in_m: 600 }, "T1", pass)).toBe(false); // a real call 600 m ahead
    expect(wrappedCall({ corner: "T3", in_m: 740 }, "T1", pass)).toBe(false);
    expect(wrappedCall({ corner: "T3", in_m: 760 }, "T1", pass)).toBe(true); // passed 240 m ago, back a lap later
  });

  it("a stale band keeps the call's text with an unknown distance", () => {
    expect(cueView(cues({ next: wrapped }), "T15", null, null, true, { toApexM: 120, lapLengthM: L }).next).toMatchObject({
      inText: "-",
    });
  });
});

describe("AI field heads-ups (an AI reference, never the driver's own calls)", () => {
  it("is recognised by the server's source, else by the engine's reason", () => {
    expect(isFieldPlan(fixture("edited-ai-field-suzuka").cues)).toBe(true);
    expect(isFieldPlan(cues({ reason: "AI field heads-ups (new driver: waiting for a lap against their reference)" }))).toBe(true);
    expect(isFieldPlan(cues({ source: "field" }))).toBe(true);
    expect(isFieldPlan(cues({ source: "reference", reason: "AI field heads-ups (no reference lap yet)" }))).toBe(false);
    expect(isFieldPlan(cues({ reason: "no reference lap yet" }))).toBe(false);
    expect(isFieldPlan(undefined)).toBe(false);
  });

  it("never treats the heads-up keys as the driver's focus corners", () => {
    const c = fixture("edited-ai-field-suzuka").cues!;
    expect(c.focus).toEqual(["T7", "T10", "zone@655"]);
    expect(driverFocus(c)).toEqual([]);
    expect(driverFocus(cues())).toEqual(["T15"]);
    expect(driverFocus(undefined)).toEqual([]);
  });

  it("labels the call for the shown corner AI REF, keeps the server's phrase verbatim", () => {
    const s = fixture("edited-ai-field-suzuka"); // learned model: the heads-up for T7 (official T11)
    const v = cueView(s.cues, "T7", s.track_model);
    expect(v).toMatchObject({ ai: true, note: null, muted: false });
    expect(v.next).toMatchObject({ kind: "marker", chip: "AI REF", ai: true, text: "heavy braking ahead", inM: 335, inText: "335 m" });
  });

  it("says AI reference on the secondary line and never prints a raw key (real Monza, no learned model)", () => {
    const s = fixture("edited-ai-field-monza");
    const v = cueView(s.cues, null, s.track_model);
    expect(v).toEqual({ next: null, note: `${AI_REFERENCE}: heavy braking ahead · 1.0 km`, muted: false, radioOff: false, ai: true });
    expect(cueView(s.cues, null, null, null, true).note).toBe(`${AI_REFERENCE}: heavy braking ahead · -`);
    expect(cueView({ ...s.cues!, next: null }, null).note).toBe(`${AI_REFERENCE} until your first clean lap`);
    expect(cueView({ ...s.cues!, next: null, reason: null, source: "field" }, null).note).toBe(`${AI_REFERENCE}: no call ahead`);
    // pauses still win
    expect(cueView(s.cues, null, null, "red_flag").note).toBe("Calls paused");
    expect(cueView({ ...s.cues!, muted: "safety car" }, null).note).toBe("Calls paused: safety car");
  });

  it("words the calls mode as the AI reference and what it says", () => {
    expect(callsModeText(fixture("edited-ai-field-monza").cues)).toBe("Braking calls: AI reference (heavy braking ahead)");
    expect(callsModeText(cues({ mode: "off", reason: "AI field heads-ups (no reference lap yet)" }))).toBe("Braking calls: Off");
  });
});

describe("last cue outcome (radio strip)", () => {
  const last = (over: Partial<NonNullable<CueSnapshot["last"]>>) =>
    lastCueOutcome(cues({ last: { corner: "T7", text: "T7 brake", status: "sent", age_s: 3, ...over } }));

  it("measures the call against the braking point (error minus the margin, + = late)", () => {
    expect(last({ error_m: 2 })).toMatchObject({ words: `on time ${MINUS}3 m`, tone: "ok" });
    expect(last({ error_m: 11 })).toMatchObject({ words: "late +6 m", tone: "late" });
    expect(last({ error_m: 5 })).toMatchObject({ words: "on time 0 m", tone: "ok" });
  });

  it("says dropped with the reason, and pending while the outcome is unknown", () => {
    expect(last({ status: "dropped", reason: "audio not ready" })).toMatchObject({ words: "dropped (audio not ready)", tone: "dropped" });
    expect(last({ status: "pending" })).toMatchObject({ words: null, tone: "pending" });
  });

  it("stops showing an old call", () => {
    expect(last({ age_s: CUE_LAST_SHOWN_S })).toBeNull();
    expect(lastCueOutcome(cues())).toBeNull();
  });

  it("works on a real snapshot after a call (relabelled, outcome pending: no radio in the replay)", () => {
    const s = fixture("recorded-suzuka-on-track-after-cue");
    expect(lastCueOutcome(s.cues, s.track_model)).toMatchObject({ corner: "T7", text: "T11 brake", tone: "pending" });
  });
});
