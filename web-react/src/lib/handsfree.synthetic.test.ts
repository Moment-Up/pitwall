// SYNTHETIC evidence for the browser energy VAD (acceptance A6, lane handsfree): per-frame levels of macOS `say`
// clips ("Pitwall …", "Radio …" and negatives, 7 voices) mixed with pink noise, run through the shipped EnergyVad.
// Not a recording of a driver: real AirPod levels are still owed (A9). The committed fixture is a subset ("Pitwall,
// what's my fuel?" and the shortest clip, "Pitwall.", for the 7 voices, in every condition); the full 714-trace run
// reads PITWALL_HF_TRACES (JSON lines of the same shape, made from the design clips) when set.

import { describe, expect, it } from "vitest";
import fixture from "../test/fixtures/handsfree/vad-traces.synthetic.json";
import { EnergyVad, VAD_START_WINDOW } from "./handsfree";

interface Trace {
  clip: string;
  cond: string;
  /** Clip start / end frame. */
  sp0: number;
  sp1: number;
  /** First frame of speech (the clean clip's first frame within 30 dB of its loudest). */
  onset: number;
  db: number[];
}

interface Tally {
  n: number;
  single: number;
  split: number;
  missed: number;
  falseSegs: number;
  /** Speech onset to the frame that confirmed the start (what the server's 0.5 s pre-roll must cover). */
  lagsMs: number[];
}

/** Run one trace; segments are [first frame, last frame] like the design's vad_sim.py. */
function segmentsOf(db: readonly number[]): [number, number][] {
  const vad = new EnergyVad();
  const segs: [number, number][] = [];
  let start: number | null = null;
  db.forEach((d, k) => {
    const ev = vad.push(10 ** (d / 20));
    if (ev?.type === "start") start = k - VAD_START_WINDOW + 1;
    else if (ev && start !== null) {
      segs.push([start, k]);
      start = null;
    }
  });
  if (start !== null) segs.push([start, db.length - 1]);
  return segs;
}

function tally(traces: readonly Trace[]): Map<string, Tally> {
  const out = new Map<string, Tally>();
  for (const t of traces) {
    const segs = segmentsOf(t.db);
    const hit = segs.filter(([a, b]) => a <= t.sp1 && b >= t.sp0);
    let s = out.get(t.cond);
    if (!s) out.set(t.cond, (s = { n: 0, single: 0, split: 0, missed: 0, falseSegs: 0, lagsMs: [] }));
    s.n++;
    if (hit.length === 0) s.missed++;
    else if (hit.length === 1) {
      s.single++;
      s.lagsMs.push((hit[0]![0] + VAD_START_WINDOW - 1 - t.onset) * 32);
    } else s.split++;
    s.falseSegs += segs.length - hit.length;
  }
  return out;
}

const traces = (fixture as { tier: string; traces: Trace[] }).traces;

describe("EnergyVad on synthetic speech in noise (committed subset)", () => {
  const t = tally(traces);

  it("is synthetic and covers every condition", () => {
    expect((fixture as { tier: string }).tier).toBe("synthetic");
    expect([...t.keys()].sort()).toEqual(["quiet", "quiet_-20dB", "snr0", "snr10", "snr20", "snr30"]);
    expect(t.get("quiet")!.n).toBe(14);
  });

  it("quiet room and 30 / 20 dB SNR: one segment per clip, no false segment", () => {
    for (const cond of ["quiet", "quiet_-20dB", "snr30", "snr20"]) {
      const s = t.get(cond)!;
      expect(s.single, cond).toBe(s.n);
      expect(s.falseSegs, cond).toBe(0);
    }
  });

  it("10 dB SNR: most clips heard, no false segment", () => {
    const s = t.get("snr10")!;
    expect(s.single + s.split).toBeGreaterThanOrEqual(s.n - 1);
    expect(s.falseSegs).toBe(0);
  });

  it("0 dB SNR: refuses (no segment at all, so no 8 s captures of noise)", () => {
    const s = t.get("snr0")!;
    expect(s.single + s.split).toBe(0);
    expect(s.falseSegs).toBe(0);
  });

  it("a start is confirmed within the server's 0.5 s pre-roll of the speech onset", () => {
    for (const s of t.values()) for (const lag of s.lagsMs) expect(lag).toBeLessThan(500);
  });
});

// node:fs and the environment through the process object (tsconfig types are vite/client only), as pro-css.test.ts.
const proc = (
  globalThis as unknown as {
    process: { env: Record<string, string | undefined>; getBuiltinModule(id: "node:fs"): { readFileSync(p: string, enc: "utf8"): string } };
  }
).process;
const full = proc.env.PITWALL_HF_TRACES;

describe.skipIf(!full)("EnergyVad on the full synthetic set (A6, PITWALL_HF_TRACES)", () => {
  it("meets A6: quiet ≥ 236/238 single, 20 dB ≥ 115/119, 0 dB → 0 segments, 0 false segments", () => {
    const all = proc
      .getBuiltinModule("node:fs")
      .readFileSync(full!, "utf8")
      .split("\n")
      .filter(Boolean)
      .map((l) => JSON.parse(l) as Trace);
    const t = tally(all);
    const report = Object.fromEntries(
      [...t].map(([k, s]) => {
        const lags = [...s.lagsMs].sort((a, b) => a - b);
        return [k, { n: s.n, single: s.single, split: s.split, missed: s.missed, false: s.falseSegs, medianLagMs: lags[lags.length >> 1] ?? null }];
      }),
    );
    console.log(JSON.stringify(report, null, 1));
    const quiet = (t.get("quiet")?.single ?? 0) + (t.get("quiet_-20dB")?.single ?? 0);
    expect(quiet).toBeGreaterThanOrEqual(236);
    // the median start is confirmed inside the pre-roll (in 10 dB noise a quiet first word is buried: it starts later)
    for (const r of Object.values(report)) if (r.medianLagMs !== null) expect(r.medianLagMs).toBeLessThan(500);
    expect(t.get("snr20")!.single).toBeGreaterThanOrEqual(115);
    expect(t.get("snr0")!.single + t.get("snr0")!.split).toBe(0);
    for (const s of t.values()) expect(s.falseSegs).toBe(0);
  });
});
