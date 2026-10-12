// Hands-free and the talk button, the pure rules (lib/handsfree.ts, lane handsfree): the energy VAD and its endpoint
// mode on synthetic rms sequences, hold vs tap, controller polling, learning a button, and the server's blocks.

import { describe, expect, it } from "vitest";
import frames from "../test/fixtures/handsfree/server-frames.json";
import {
  BOUNCE_MS,
  ButtonLearner,
  ENDPOINT_END_FRAMES,
  ENDPOINT_MAX_FRAMES,
  ENDPOINT_WAIT_FRAMES,
  Endpointer,
  EnergyVad,
  HANDS_FREE_IDLE,
  PadWatcher,
  TAP_MAX_MS,
  TalkButtonMachine,
  VAD_CALIBRATION_FRAMES,
  VAD_END_FRAMES,
  VAD_MAX_FRAMES,
  isWakeWord,
  keyLabel,
  learnableCode,
  learnableKey,
  median,
  padName,
  parseHandsFreeEvent,
  parseHandsFreeState,
  parseTalkButton,
  percentile,
  rmsToDb,
  sameTalkButton,
  talkButtonLabel,
  talkPadEdges,
  tallyEvent,
  thresholdFor,
  type PadLike,
  type VadEvent,
} from "./handsfree";

/** Linear rms for a level in dBFS. */
const rms = (db: number) => 10 ** (db / 20);

/** Feed `n` frames at `db`; returns the events (non-null). */
function feed(vad: EnergyVad, db: number, n: number, suppressed = false): VadEvent[] {
  const out: VadEvent[] = [];
  for (let i = 0; i < n; i++) {
    const e = vad.push(rms(db), suppressed);
    if (e) out.push(e);
  }
  return out;
}

/** A VAD calibrated on a -70 dBFS room. */
function calibrated(db = -70): EnergyVad {
  const v = new EnergyVad();
  feed(v, db, VAD_CALIBRATION_FRAMES);
  return v;
}

describe("levels", () => {
  it("rms -> dBFS, floored at -120 dBFS for silence and garbage", () => {
    expect(rmsToDb(1)).toBe(0);
    expect(rmsToDb(0.1)).toBeCloseTo(-20, 6);
    expect(rmsToDb(0)).toBe(-120);
    expect(rmsToDb(Number.NaN)).toBe(-120);
  });

  it("median and the 10th percentile (linear, like numpy)", () => {
    expect(median([3, 1, 2])).toBe(2);
    expect(median([4, 1, 2, 3])).toBe(2.5);
    expect(percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11], 10)).toBe(2);
    expect(percentile([0, 10], 10)).toBe(1);
    expect(Number.isNaN(median([]))).toBe(true);
  });

  it("threshold: floor + 12 dB, never under -50 dBFS; in loud noise at least noise + 10 dB", () => {
    expect(thresholdFor(-70)).toBe(-50);
    expect(thresholdFor(-55)).toBe(-43);
    expect(thresholdFor(-35)).toBe(-23);
    expect(thresholdFor(-30)).toBe(-20); // floor clamped to -35 (-23), noise + 10 = -20
    expect(thresholdFor(-20)).toBe(-10);
  });
});

describe("EnergyVad", () => {
  it("calibrates for 1 s (31 frames) without any segment, then uses the median as the floor", () => {
    const v = new EnergyVad();
    expect(v.phase).toBe("calibrating");
    expect(feed(v, -20, 30)).toEqual([]); // loud, but still calibrating
    expect(v.floorDb).toBeNull();
    expect(v.thresholdDb).toBeNull();
    feed(v, -64, 1);
    expect(v.floorDb).toBeCloseTo(-20, 6); // the median of 30 x -20 and one -64
    expect(v.thresholdDb).toBe(-10);
    expect(v.phase).toBe("noisy"); // -20 dBFS of noise: too loud to listen
    const q = new EnergyVad();
    feed(q, -62, VAD_CALIBRATION_FRAMES);
    expect(q.phase).toBe("idle");
    expect(q.floorDb).toBeCloseTo(-62, 6);
  });

  it("starts at 4 voiced frames among 5 and ends after 22 quiet frames (silence)", () => {
    const v = calibrated();
    expect(v.thresholdDb).toBe(-50);
    expect(feed(v, -30, 3)).toEqual([]);
    expect(feed(v, -30, 1)).toEqual([{ type: "start" }]);
    expect(v.phase).toBe("speech");
    expect(feed(v, -30, 20)).toEqual([]);
    expect(feed(v, -70, VAD_END_FRAMES - 1)).toEqual([]);
    const [end] = feed(v, -70, 1);
    expect(end).toMatchObject({ type: "end", reason: "silence" });
    expect(v.phase).toBe("idle");
  });

  it("one quiet frame inside a 5-frame window still starts; two do not", () => {
    const a = calibrated();
    const evs: (VadEvent | null)[] = [-30, -30, -70, -30, -30].map((d) => a.push(rms(d)));
    expect(evs.at(-1)).toEqual({ type: "start" });
    const b = calibrated();
    expect([-30, -70, -30, -70, -30].map((d) => b.push(rms(d))).filter(Boolean)).toEqual([]);
  });

  it("short gaps inside speech do not end it (fewer than 22 quiet frames)", () => {
    const v = calibrated();
    feed(v, -30, 4);
    for (let i = 0; i < 5; i++) {
      expect(feed(v, -70, 15)).toEqual([]); // ~0.5 s pause between words
      expect(feed(v, -30, 10)).toEqual([]);
    }
    expect(v.phase).toBe("speech");
  });

  it("cuts a segment at 8 s (max) and takes its 10th percentile as the new floor", () => {
    const v = calibrated();
    const evs = feed(v, -25, 4 + VAD_MAX_FRAMES);
    expect(evs[0]).toEqual({ type: "start" });
    expect(evs[1]).toMatchObject({ type: "end", reason: "max" });
    expect(evs[1]!.type === "end" && evs[1]!.frames).toBe(VAD_MAX_FRAMES + 1);
    expect(v.floorDb).toBeCloseTo(-25, 1); // the steady sound is the floor now
    expect(feed(v, -25, 100)).toEqual([]); // and no longer starts segments
  });

  it("a steady sound that is not loud enough to last 8 s fades into the floor (the floor rises during speech)", () => {
    const v = calibrated();
    const evs = feed(v, -40, 300);
    expect(evs[0]).toEqual({ type: "start" });
    expect(evs[1]).toMatchObject({ type: "end", reason: "silence" });
    expect(feed(v, -40, 300)).toEqual([]);
  });

  it("tracks the floor fast downwards and slowly upwards while idle", () => {
    const v = calibrated(-50);
    feed(v, -70, 10);
    expect(v.floorDb!).toBeLessThan(-67); // 0.2 per frame towards -70
    const before = v.floorDb!;
    feed(v, -60, 20); // under the threshold (-50): rises slowly (0.005 per frame)
    expect(v.floorDb! - before).toBeLessThan(1);
    expect(v.floorDb! - before).toBeGreaterThan(0);
  });

  it("only raises the floor during speech (never lowers it)", () => {
    const v = calibrated(-60);
    feed(v, -30, 4);
    const f0 = v.floorDb!;
    feed(v, -70, 10); // quiet frames inside speech
    expect(v.floorDb!).toBeGreaterThanOrEqual(f0);
  });

  it("suppressed frames freeze the floor, abort a segment and do not calibrate", () => {
    const v = new EnergyVad();
    expect(feed(v, -70, 100, true)).toEqual([]);
    expect(v.phase).toBe("calibrating"); // the engineer talking is not the room's noise
    feed(v, -70, VAD_CALIBRATION_FRAMES);
    feed(v, -30, 4);
    expect(v.phase).toBe("speech");
    const [abort] = feed(v, -30, 1, true);
    expect(abort).toMatchObject({ type: "abort", reason: "suppressed" });
    const floor = v.floorDb;
    feed(v, -10, 50, true);
    expect(v.floorDb).toBe(floor);
    expect(v.phase).toBe("idle");
    expect(feed(v, -30, 3)).toEqual([]); // the start window starts over after suppression
    expect(feed(v, -30, 1)).toEqual([{ type: "start" }]);
  });

  it("refuses in noise too loud to tell speech apart (noisy), and recovers when it drops", () => {
    const v = calibrated(-20);
    expect(v.phase).toBe("noisy");
    expect(feed(v, -5, 50)).toEqual([]); // even much louder frames: no capture of noise
    feed(v, -70, 40);
    expect(v.phase).toBe("idle");
    expect(feed(v, -30, 4)).toEqual([{ type: "start" }]);
  });

  it("clamps the noise estimate and resets to calibration", () => {
    const v = calibrated(-120);
    expect(v.floorDb).toBe(-90);
    v.reset();
    expect(v.phase).toBe("calibrating");
    expect(v.effectiveThreshold()).toBe(-50);
    feed(v, -40, 5);
    expect(v.effectiveThreshold()).toBe(-28); // from the frames so far while calibrating
  });
});

describe("Endpointer (a tapped talk button)", () => {
  it("releases when no speech starts within 4 s", () => {
    const e = new Endpointer();
    for (let i = 1; i < ENDPOINT_WAIT_FRAMES; i++) expect(e.push(-70, -50)).toBeNull();
    expect(e.push(-70, -50)).toBe("no_speech");
  });

  it("after speech, releases on 0.8 s of quiet", () => {
    const e = new Endpointer();
    for (let i = 0; i < 4; i++) e.push(-30, -50);
    expect(e.speechStarted).toBe(true);
    for (let i = 0; i < 30; i++) expect(e.push(-30, -50)).toBeNull();
    for (let i = 1; i < ENDPOINT_END_FRAMES; i++) expect(e.push(-70, -50)).toBeNull();
    expect(e.push(-70, -50)).toBe("silence");
  });

  it("releases at 12 s whatever happens", () => {
    const e = new Endpointer();
    let last: string | null = null;
    for (let i = 0; i < ENDPOINT_MAX_FRAMES; i++) last = e.push(-30, -50);
    expect(last).toBe("max");
  });
});

describe("TalkButtonMachine (hold or tap)", () => {
  it("hold: press keys, a release after 300 ms ends the transmission", () => {
    const m = new TalkButtonMachine();
    expect(m.press(1000)).toBe("press");
    expect(m.press(1100)).toBeNull(); // auto-repeat
    expect(m.release(1000 + TAP_MAX_MS)).toBe("release");
    expect(m.state).toBe("idle");
  });

  it("tap: a quick release leaves the mic on; the next press ends it", () => {
    const m = new TalkButtonMachine();
    expect(m.press(1000)).toBe("press");
    expect(m.release(1100)).toBeNull();
    expect(m.state).toBe("tap");
    expect(m.pressedAt).toBe(1000);
    expect(m.release(1150)).toBeNull(); // a stray keyup
    expect(m.press(3000)).toBe("release");
    expect(m.state).toBe("idle");
    expect(m.release(3050)).toBeNull(); // the keyup of the ending press
    expect(m.press(3200)).toBe("press"); // a new transmission
  });

  it("ignores contact bounce right after a release", () => {
    const m = new TalkButtonMachine();
    m.press(0);
    m.release(50); // tap
    expect(m.press(50 + BOUNCE_MS - 1)).toBeNull();
    expect(m.state).toBe("tap");
    expect(m.press(50 + BOUNCE_MS)).toBe("release");
  });

  it("reset forgets a transmission ended elsewhere", () => {
    const m = new TalkButtonMachine();
    m.press(0);
    m.release(10);
    m.reset();
    expect(m.state).toBe("idle");
    expect(m.press(1000)).toBe("press");
  });
});

describe("talk buttons", () => {
  it("parses stored buttons and refuses anything else", () => {
    expect(parseTalkButton({ kind: "key", code: "PageDown" })).toEqual({ kind: "key", code: "PageDown" });
    expect(parseTalkButton({ kind: "gamepad", id: "Xbox Wireless Controller", button: 3 })).toEqual({
      kind: "gamepad",
      id: "Xbox Wireless Controller",
      button: 3,
    });
    for (const bad of [null, 3, "x", { kind: "key", code: "KeyA" }, { kind: "key", code: "Space" }, { kind: "gamepad", id: "", button: 1 }, { kind: "gamepad", id: "x", button: 1.5 }, { kind: "gamepad", id: "x", button: -1 }]) {
      expect(parseTalkButton(bad)).toBeNull();
    }
  });

  it("compares buttons", () => {
    expect(sameTalkButton(null, null)).toBe(true);
    expect(sameTalkButton({ kind: "key", code: "F13" }, { kind: "key", code: "F13" })).toBe(true);
    expect(sameTalkButton({ kind: "key", code: "F13" }, null)).toBe(false);
    expect(sameTalkButton({ kind: "gamepad", id: "a", button: 1 }, { kind: "gamepad", id: "a", button: 2 })).toBe(false);
  });

  it("learnable keys: page-turner and pedal keys yes; typing keys, Space, Tab, Escape and modifiers no", () => {
    for (const ok of ["ArrowRight", "ArrowDown", "PageDown", "PageUp", "Enter", "F13", "F19", "MediaPlayPause", "Numpad5", "Home"]) {
      expect(learnableCode(ok), ok).toBe(true);
    }
    for (const no of ["KeyA", "Digit1", "Space", "Tab", "Escape", "Backspace", "ShiftLeft", "MetaRight", "Comma", "", "Unidentified"]) {
      expect(learnableCode(no), no).toBe(false);
    }
    expect(learnableKey({ code: "PageDown" })).toBe("PageDown");
    expect(learnableKey({ code: "PageDown", metaKey: true })).toBeNull();
    expect(learnableKey({ code: "PageDown", repeat: true })).toBeNull();
  });

  it("labels keys and controllers for the driver", () => {
    expect(keyLabel("ArrowRight")).toBe("Right arrow");
    expect(keyLabel("PageDown")).toBe("Page Down");
    expect(keyLabel("F13")).toBe("F13");
    expect(keyLabel("NumpadEnter")).toBe("Keypad Enter");
    expect(keyLabel("Numpad5")).toBe("Keypad 5");
    expect(padName("045e-02fd-Xbox Wireless Controller")).toBe("Xbox Wireless Controller");
    expect(padName("DualSense Wireless Controller (STANDARD GAMEPAD Vendor: 054c Product: 0ce6)")).toBe(
      "DualSense Wireless Controller",
    );
    expect(padName("")).toBe("Game controller");
    expect(talkButtonLabel({ kind: "key", code: "PageDown" })).toBe("Page Down");
    expect(talkButtonLabel({ kind: "gamepad", id: "Xbox Wireless Controller", button: 0 })).toBe(
      "Xbox Wireless Controller · button 0 (A / Cross on most controllers)",
    );
    expect(talkButtonLabel({ kind: "gamepad", id: "Pad", button: 40 })).toBe("Pad · button 40");
  });

  it("wake words", () => {
    expect(isWakeWord("pitwall")).toBe(true);
    expect(isWakeWord("radio")).toBe(true);
    expect(isWakeWord("hey")).toBe(false);
  });
});

/** A fake controller (navigator.getGamepads() entry). */
function pad(id: string, down: number[] = [], index = 0, n = 17): PadLike {
  return { id, index, connected: true, buttons: Array.from({ length: n }, (_, i) => ({ pressed: down.includes(i), value: down.includes(i) ? 1 : 0 })) };
}

describe("PadWatcher (controller polling)", () => {
  it("reports up/down edges between polls, not buttons already held when first seen", () => {
    const w = new PadWatcher();
    expect(w.poll([pad("X", [0])])).toEqual([]); // seen for the first time with A held (the wake-up press)
    expect(w.poll([pad("X", [0, 3])])).toEqual([{ id: "X", index: 0, button: 3, down: true }]);
    expect(w.poll([pad("X", [3])])).toEqual([{ id: "X", index: 0, button: 0, down: false }]);
    expect(w.poll([pad("X", [])])).toEqual([{ id: "X", index: 0, button: 3, down: false }]);
  });

  it("an analogue trigger past half way is down; empty slots are skipped", () => {
    const w = new PadWatcher();
    const p = pad("X");
    w.poll([null, p]);
    const t: PadLike = { ...p, buttons: p.buttons.map((b, i) => (i === 7 ? { pressed: false, value: 0.8 } : b)) };
    expect(w.poll([null, t])).toEqual([{ id: "X", index: 0, button: 7, down: true }]);
  });

  it("a controller that disconnects with a button down reports the release", () => {
    const w = new PadWatcher();
    w.poll([pad("X")]);
    w.poll([pad("X", [5])]);
    expect(w.poll([])).toEqual([{ id: "X", index: 0, button: 5, down: false }]);
  });

  it("talkPadEdges keeps only the learned controller's learned button", () => {
    const edges = [
      { id: "X", index: 0, button: 3, down: true },
      { id: "X", index: 0, button: 2, down: true },
      { id: "Y", index: 1, button: 3, down: true },
    ];
    expect(talkPadEdges(edges, { kind: "gamepad", id: "X", button: 3 })).toEqual([edges[0]]);
    expect(talkPadEdges(edges, { kind: "key", code: "F13" })).toEqual([]);
    expect(talkPadEdges(edges, null)).toEqual([]);
  });
});

describe("ButtonLearner (Settings › Set up button)", () => {
  it("the first learnable key wins; a typing key is refused and named", () => {
    const l = new ButtonLearner();
    expect(l.key({ code: "KeyA" })).toBeNull();
    expect(l.refused).toBe("KeyA");
    expect(l.key({ code: "Escape" })).toBeNull();
    expect(l.refused).toBe("KeyA"); // Escape closes the dialog; it is not "refused"
    expect(l.key({ code: "PageDown" })).toEqual({ kind: "key", code: "PageDown" });
    expect(l.refused).toBeNull();
    expect(l.key({ code: "ArrowRight" })).toBeNull(); // already learned
    expect(l.learned).toEqual({ kind: "key", code: "PageDown" });
  });

  it("a controller button pressed after the first poll wins; try again forgets it", () => {
    const l = new ButtonLearner();
    expect(l.poll([pad("Pad", [1])])).toBeNull(); // held when first seen
    expect(l.poll([pad("Pad", [1, 4])])).toEqual({ kind: "gamepad", id: "Pad", button: 4 });
    l.restart();
    expect(l.learned).toBeNull();
    expect(l.poll([pad("Pad", [1, 4])])).toBeNull(); // still held: not a new press
    expect(l.poll([pad("Pad", [1])])).toBeNull();
    expect(l.poll([pad("Pad", [1, 4])])).toEqual({ kind: "gamepad", id: "Pad", button: 4 });
  });
});

describe("the server's hands-free block and events", () => {
  it("parses every fixture state", () => {
    for (const [name, raw] of Object.entries(frames.handsfree)) {
      const hf = parseHandsFreeState(raw);
      expect(hf, name).not.toBeNull();
      expect(hf).toMatchObject({ available: raw.available, scope: raw.scope, active: raw.active, capturing: raw.capturing });
    }
    expect(parseHandsFreeState(frames.handsfree.paused_moving)?.paused).toBe("moving");
    expect(parseHandsFreeState(frames.handsfree.unavailable_env)?.reason).toContain("PITWALL_VOICE_HANDSFREE=false");
  });

  it("is lenient: missing or wrong fields read as off / zero; absent is null", () => {
    expect(parseHandsFreeState(undefined)).toBeNull();
    expect(parseHandsFreeState([])).toBeNull();
    expect(parseHandsFreeState({ available: "yes", armed: -3, scope: "everywhere", paused: "parked", counts: { heard: 2.7 } })).toEqual({
      available: false,
      reason: null,
      armed: 0,
      scope: "stationary",
      active: false,
      paused: null,
      capturing: false,
      follow_up: false,
      wake_words: [],
      counts: { heard: 2, addressed: 0, ignored: 0, rejected: 0 },
    });
  });

  it("parses events and tallies them (too long counted apart)", () => {
    let h = HANDS_FREE_IDLE;
    for (const raw of frames.events) {
      const ev = parseHandsFreeEvent(raw as Record<string, unknown>);
      expect(ev).not.toBeNull();
      h = tallyEvent(h, ev!, 1000);
    }
    expect(h.events).toEqual({ accepted: 1, rejected: 2, ignored: 1, addressed: 1, tooLong: 1 });
    expect(h.last).toEqual({ event: "follow_up", reason: null, at: 1000 });
    expect(parseHandsFreeEvent({ event: "said", text: "anything" })).toBeNull();
    expect(parseHandsFreeEvent({ event: "addressed", wake: "pitwall", seq: 3 })).toMatchObject({ wake: "pitwall", seq: 3 });
    expect(HANDS_FREE_IDLE.events.accepted).toBe(0); // tallying never mutates
  });
});
