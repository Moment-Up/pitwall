// SYNTHETIC evidence for the browser energy VAD (acceptance A6, lane handsfree), on the backend's committed traces:
// tests/fixtures/handsfree/vad_rms.json.gz (714 traces of macOS `say` clips in pink noise, one RMS value per 512-sample
// frame at 16 kHz, from scripts/handsfree_check.py --rms). Its `expected` block is the Python reference VAD (the
// design's rules). The shipped EnergyVad adds two loud-noise rules (handsfree.ts) that never fire on these traces, so
// it must reproduce that table exactly, and meet the A6 thresholds. Not a recording of a driver: real AirPod levels
// are still owed (A9).

import { describe, expect, it } from "vitest";
import { EnergyVad, VAD_START_WINDOW } from "./handsfree";

interface RmsTrace {
  clip: string;
  condition: string;
  /** Clip start / end frame. */
  speech: [number, number];
  rms: number[];
}

interface Tally {
  n: number;
  single: number;
  split: number;
  missed: number;
  falseSegs: number;
}

// node:fs / node:zlib through the process object (tsconfig types are vite/client only), as pro-css.test.ts.
const proc = (
  globalThis as unknown as {
    process: {
      getBuiltinModule(id: "node:fs"): { readFileSync(p: URL): Uint8Array };
      getBuiltinModule(id: "node:zlib"): { gunzipSync(b: Uint8Array): { toString(enc: "utf8"): string } };
    };
  }
).process;

const FIXTURE = new URL("../../../tests/fixtures/handsfree/vad_rms.json.gz", import.meta.url);

interface Expected {
  n: number;
  single: number;
  split: number;
  missed: number;
  false: number;
}

function load(): { traces: RmsTrace[]; expected: Record<string, Expected> } {
  const raw = proc.getBuiltinModule("node:fs").readFileSync(FIXTURE);
  return JSON.parse(proc.getBuiltinModule("node:zlib").gunzipSync(raw).toString("utf8")) as {
    traces: RmsTrace[];
    expected: Record<string, Expected>;
  };
}

function segmentsOf(rms: readonly number[]): [number, number][] {
  const vad = new EnergyVad();
  const segs: [number, number][] = [];
  let start: number | null = null;
  rms.forEach((r, k) => {
    const ev = vad.push(r);
    if (ev?.type === "start") start = k - VAD_START_WINDOW + 1;
    else if (ev && start !== null) {
      segs.push([start, k]);
      start = null;
    }
  });
  if (start !== null) segs.push([start, rms.length - 1]);
  return segs;
}

function tally(traces: readonly RmsTrace[]): Record<string, Tally> {
  const out: Record<string, Tally> = {};
  for (const t of traces) {
    const [sp0, sp1] = t.speech;
    const segs = segmentsOf(t.rms);
    const hit = segs.filter(([a, b]) => a <= sp1 && b >= sp0).length;
    const s = (out[t.condition] ??= { n: 0, single: 0, split: 0, missed: 0, falseSegs: 0 });
    s.n++;
    if (hit === 0) s.missed++;
    else if (hit === 1) s.single++;
    else s.split++;
    s.falseSegs += segs.length - hit;
  }
  return out;
}

describe("EnergyVad on the backend's 714 synthetic traces (A6)", () => {
  const fixture = load();
  const t = tally(fixture.traces);

  it("covers every condition", () => {
    expect(Object.keys(t).sort()).toEqual(["quiet", "snr0", "snr10", "snr20", "snr30"]);
    expect(t.quiet!.n).toBe(238);
  });

  it("reproduces the Python reference VAD's table (scripts/handsfree_check.py) exactly", () => {
    const got = Object.fromEntries(
      Object.entries(t).map(([cond, s]) => [cond, { n: s.n, single: s.single, split: s.split, missed: s.missed, false: s.falseSegs }]),
    );
    expect(got).toEqual(fixture.expected);
  });

  it("meets A6: quiet ≥ 236/238 single, 20 dB ≥ 115/119, 0 dB → no segment, no false segment anywhere", () => {
    expect(t.quiet!.single).toBeGreaterThanOrEqual(236);
    expect(t.snr30!.single).toBeGreaterThanOrEqual(117);
    expect(t.snr20!.single).toBeGreaterThanOrEqual(115);
    expect(t.snr10!.single + t.snr10!.split).toBeGreaterThanOrEqual(t.snr10!.n - 4);
    expect(t.snr0!.single + t.snr0!.split).toBe(0);
    for (const [cond, s] of Object.entries(t)) expect(s.falseSegs, cond).toBe(0);
  });
});
