// public/mic-worklet.js (an identical copy of web/public/mic-worklet.js): the resampler and frame packer the radio
// depends on - 16 kHz int16 frames of 512 samples, a flush that posts the partial frame (PTT release hang time).
// The module's processor registration is guarded, so its pure exports import in plain node.
// The identity check keeps the two dashboards' radios on the same audio path; drop it when web/ is retired.

import { describe, expect, it } from "vitest";
import ours from "../../public/mic-worklet.js?raw";
import svelte from "../../../web/public/mic-worklet.js?raw";

interface WorkletModule {
  TARGET_RATE: number;
  FRAME_SAMPLES: number;
  floatToInt16: (x: number) => number;
  Resampler: new (fin: number, fout: number) => { push: (x: Float32Array) => Float32Array; bank: { taps: number; phases: number; exact: boolean } };
  FramePacker: new (emit: (pcm: ArrayBuffer, rms: number, peak: number) => void) => {
    push: (s: Float32Array) => void;
    flush: () => boolean;
  };
}

const URL_ = new URL("../../public/mic-worklet.js", import.meta.url);
const load = async (): Promise<WorkletModule> => (await import(/* @vite-ignore */ URL_.href)) as WorkletModule;

describe("mic worklet", () => {
  it("is identical to the Svelte dashboard's copy (the reference)", () => {
    expect(ours.length).toBeGreaterThan(1000);
    expect(ours).toBe(svelte);
  });

  it("packs 16 kHz int16 frames of 512 samples and flushes the partial frame", async () => {
    const w = await load();
    expect(w.TARGET_RATE).toBe(16000);
    expect(w.FRAME_SAMPLES).toBe(512);
    const frames: { bytes: number; rms: number }[] = [];
    const packer = new w.FramePacker((pcm, rms) => frames.push({ bytes: pcm.byteLength, rms }));
    packer.push(new Float32Array(700).fill(0.5));
    expect(frames).toEqual([{ bytes: 1024, rms: 0.5 }]);
    expect(packer.flush()).toBe(true);
    expect(frames[1]).toEqual({ bytes: (700 - 512) * 2, rms: 0.5 });
    expect(packer.flush()).toBe(false); // nothing held
  });

  it("clips and rounds to int16", async () => {
    const w = await load();
    expect(w.floatToInt16(1.5)).toBe(32767);
    expect(w.floatToInt16(-1.5)).toBe(-32768);
    expect(w.floatToInt16(0.5)).toBe(16384);
  });

  it("resamples 48 kHz to 16 kHz (3:1) and keeps a 1 kHz tone's level", async () => {
    const w = await load();
    const r = new w.Resampler(48000, 16000);
    expect(r.bank.phases).toBe(1);
    const n = 48000;
    const x = new Float32Array(n);
    for (let i = 0; i < n; i++) x[i] = 0.5 * Math.sin((2 * Math.PI * 1000 * i) / 48000);
    const y = r.push(x);
    expect(Math.abs(y.length - n / 3)).toBeLessThan(200); // minus the filter's look-ahead
    const tail = y.subarray(1000);
    const rms = Math.sqrt(tail.reduce((a, v) => a + v * v, 0) / tail.length);
    expect(rms).toBeCloseTo(0.5 / Math.SQRT2, 2);
  });
});
