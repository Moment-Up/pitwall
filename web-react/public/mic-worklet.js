// Microphone capture worklet for the radio client (docs/voice-protocol.md).
//
// Runs on the audio rendering thread. Takes the microphone at the AudioContext rate (iOS ignores requested
// rates: usually 48 kHz, sometimes 44.1 kHz or 24 kHz), down-mixes to mono, resamples to 16 kHz with a proper
// anti-alias filter, converts to int16 little-endian and posts 512-sample (32 ms, 1024-byte) frames to the main
// thread, which sends them as binary WebSocket frames. Each frame carries its RMS and peak so the page can draw a
// level meter without touching the audio again.
//
// Flush: the page posts {type: "flush", seq} at the end of a push-to-talk release. The worklet posts the partial
// frame it is holding (fewer than 512 samples, so it is not stuck behind the PTT release) followed by
// {type: "flushed", seq}; the port is ordered, so once "flushed" arrives every captured sample has been posted.
//
// Plain JS module (served from web/public, loaded with audioWorklet.addModule). The resampler and int16
// conversion are exported pure code with no dependency on the worklet globals, so they can be exercised outside
// a browser; `export` statements are legal (and ignored) in a worklet module.
//
// Resampler design: polyphase windowed-sinc FIR (band-limited interpolation).
//   y(t) = sum_j x[j] * h(t - j / fin) / fin, with the continuous kernel
//   h(tau) = 2 fc * sinc(2 fc tau) * kaiser(tau / (T / 2), beta), |tau| <= T / 2.
// * Band edges are relative to the LOWER of the two rates (so the same code anti-aliases when decimating and
//   anti-images when interpolating): passband to 0.4375 * min(fin, fout) (7.0 kHz at 16 kHz out), stopband from
//   0.5 * min(fin, fout) (8.0 kHz, the output Nyquist), cutoff fc in the middle (7.5 kHz, -6 dB).
// * Kaiser design formulas for A = 80 dB stopband attenuation: beta = 0.1102 (A - 8.7) = 7.857; window length
//   T = (A - 7.95) / (2.285 * 2 pi * transition_width) = 5.0 ms for a 1 kHz transition. The length is fixed in
//   seconds, so the tap count scales with the input rate (244 taps at 48 kHz, 224 at 44.1 kHz).
// * Output instants are n * fin / fout input samples. With fin / fout = down / up in lowest terms the fractional
//   position repeats every `up` outputs, so one coefficient set per phase is precomputed (1 phase for 48 kHz,
//   160 for 44.1 kHz). Rates whose ratio needs more than MAX_PHASES phases round to the nearest of MAX_PHASES
//   (timing error < 1 / (2 * MAX_PHASES) of an output sample).
// * Each phase is normalised to unit DC gain. The kernel is symmetric, so the filter is linear phase; the only
//   delay is the K-sample look-ahead (about 2.5 ms).

export const TARGET_RATE = 16000;
export const FRAME_SAMPLES = 512;
export const MAX_PHASES = 1024;

const STOPBAND_DB = 80;
const PASS_FRAC = 0.4375; // passband edge as a fraction of min(fin, fout)
const STOP_FRAC = 0.5; // stopband edge (= Nyquist of the lower rate)

/** Zeroth-order modified Bessel function of the first kind (power series; converges fast for beta < 20). */
export function besselI0(x) {
  let sum = 1;
  let term = 1;
  const q = (x * x) / 4;
  for (let k = 1; k < 200; k++) {
    term *= q / (k * k);
    sum += term;
    if (term < sum * 1e-15) break;
  }
  return sum;
}

function gcd(a, b) {
  while (b) [a, b] = [b, a % b];
  return a;
}

/**
 * Design the polyphase filter bank for fin -> fout (positive integer rates).
 * @param {number} fin
 * @param {number} fout
 * @returns {{fin: number, fout: number, up: number, down: number, phases: number, exact: boolean, half: number,
 *   taps: number, coeffs: Float32Array, fc: number}}
 *   `coeffs[p * taps + k]` multiplies input sample `base - half + 1 + k` for an output whose position is
 *   `base + p / phases` (input-sample units). `half` is the look-ahead in input samples.
 */
export function designResampler(fin, fout) {
  if (!(Number.isInteger(fin) && Number.isInteger(fout) && fin > 0 && fout > 0)) {
    throw new RangeError(`rates must be positive integers, got ${fin} -> ${fout}`);
  }
  const g = gcd(fin, fout);
  const up = fout / g;
  const down = fin / g;
  const exact = up <= MAX_PHASES;
  const phases = exact ? up : MAX_PHASES;
  const base = Math.min(fin, fout);
  const fc = ((PASS_FRAC + STOP_FRAC) / 2) * base;
  const transitionHz = (STOP_FRAC - PASS_FRAC) * base;
  const beta = 0.1102 * (STOPBAND_DB - 8.7);
  const windowS = (STOPBAND_DB - 7.95) / (2.285 * 2 * Math.PI * transitionHz);
  const halfS = windowS / 2;
  const half = Math.ceil(halfS * fin) + 1;
  const taps = 2 * half;
  const coeffs = new Float32Array(phases * taps);
  const i0Beta = besselI0(beta);
  const row = new Float64Array(taps);
  for (let p = 0; p < phases; p++) {
    const frac = p / phases;
    let sum = 0;
    for (let k = 0; k < taps; k++) {
      // input sample offset relative to the output position, in seconds
      const tau = (frac - (k - half + 1)) / fin;
      let c = 0;
      if (Math.abs(tau) <= halfS) {
        const r = tau / halfS;
        const w = besselI0(beta * Math.sqrt(Math.max(0, 1 - r * r))) / i0Beta;
        const u = 2 * fc * tau;
        const sinc = u === 0 ? 1 : Math.sin(Math.PI * u) / (Math.PI * u);
        c = ((2 * fc) / fin) * sinc * w;
      }
      row[k] = c;
      sum += c;
    }
    for (let k = 0; k < taps; k++) coeffs[p * taps + k] = row[k] / sum;
  }
  return { fin, fout, up, down, phases, exact, half, taps, coeffs, fc };
}

/** Streaming resampler over a `designResampler` bank. Not thread-safe; one instance per stream. */
export class Resampler {
  /** @param {number} fin @param {number} fout */
  constructor(fin, fout) {
    this.passthrough = fin === fout;
    this.bank = designResampler(fin, fout);
    const { half, up, down } = this.bank;
    this.buf = new Float32Array(8192 + 2 * half);
    // Zero history so the first output is centred on the first input sample.
    this.len = half - 1;
    // Position of the next output in input samples, times `up` (exact integer arithmetic, no drift).
    this.acc = (half - 1) * up;
    this.out = new Float32Array(Math.ceil((8192 * up) / down) + 2);
  }

  /**
   * Feed input samples; returns the newly available output samples. The returned array is a view into an
   * internal buffer that is overwritten by the next call.
   * @param {Float32Array} input
   * @returns {Float32Array}
   */
  push(input) {
    if (this.passthrough) return input;
    const { half, taps, up, down, phases, exact, coeffs } = this.bank;
    let produced = 0;
    let offset = 0;
    while (offset < input.length) {
      const n = Math.min(input.length - offset, this.buf.length - this.len);
      this.buf.set(input.subarray(offset, offset + n), this.len);
      this.len += n;
      offset += n;
      if (this.out.length - produced < Math.ceil((this.len * up) / down) + 2) {
        const bigger = new Float32Array(produced + Math.ceil((this.len * up) / down) + 2);
        bigger.set(this.out.subarray(0, produced));
        this.out = bigger;
      }
      for (;;) {
        let base = Math.floor(this.acc / up);
        let p = this.acc - base * up;
        if (!exact) {
          p = Math.round((p * phases) / up);
          if (p === phases) {
            p = 0;
            base += 1;
          }
        }
        if (base + half >= this.len) break; // taps reach input index base + half (the look-ahead)
        const start = base - half + 1;
        const c0 = p * taps;
        let s = 0;
        for (let k = 0; k < taps; k++) s += coeffs[c0 + k] * this.buf[start + k];
        this.out[produced++] = s;
        this.acc += down;
      }
      // Drop input no longer needed by any future output (keep `half - 1` samples of history).
      const nextBase = Math.floor(this.acc / up);
      const drop = Math.max(0, Math.min(this.len, nextBase - half + 1));
      if (drop > 0) {
        this.buf.copyWithin(0, drop, this.len);
        this.len -= drop;
        this.acc -= drop * up;
      }
    }
    return this.out.subarray(0, produced);
  }
}

/** Float [-1, 1] -> int16 with clipping and round-to-nearest (no dither: speech at -30 dBFS hides it). */
export function floatToInt16(x) {
  const v = Math.round(x * 32767);
  return v > 32767 ? 32767 : v < -32768 ? -32768 : v;
}

/**
 * Packs 16 kHz float samples into int16 little-endian frames of FRAME_SAMPLES and hands each one to `emit` with its
 * RMS and peak. `flush` emits the partial frame early (shorter buffer). Ownership of every emitted buffer passes to
 * `emit` (the worklet transfers it to the main thread).
 */
export class FramePacker {
  /** @param {(pcm: ArrayBuffer, rms: number, peak: number) => void} emit */
  constructor(emit) {
    this.emit = emit;
    this.reset();
  }

  reset() {
    this.frame = new ArrayBuffer(FRAME_SAMPLES * 2);
    this.view = new DataView(this.frame);
    this.fill = 0;
    this.sumSq = 0;
    this.peak = 0;
  }

  /** @param {Float32Array} samples */
  push(samples) {
    for (let i = 0; i < samples.length; i++) {
      const x = samples[i];
      this.sumSq += x * x;
      const a = x < 0 ? -x : x;
      if (a > this.peak) this.peak = a;
      this.view.setInt16(this.fill * 2, floatToInt16(x), true);
      if (++this.fill === FRAME_SAMPLES) this.release(this.frame);
    }
  }

  /** Emit the partial frame, if any. Returns whether one was emitted. */
  flush() {
    if (this.fill === 0) return false;
    this.release(this.frame.slice(0, this.fill * 2));
    return true;
  }

  /** @param {ArrayBuffer} pcm */
  release(pcm) {
    const rms = Math.sqrt(this.sumSq / this.fill);
    const peak = Math.min(1, this.peak);
    this.reset();
    this.emit(pcm, rms, peak);
  }
}

// AudioWorklet glue. Guarded so the module can be imported outside an AudioWorkletGlobalScope.
if (typeof AudioWorkletProcessor !== "undefined" && typeof registerProcessor === "function") {
  class MicProcessor extends AudioWorkletProcessor {
    constructor() {
      super();
      // `sampleRate` is the AudioWorkletGlobalScope's context rate.
      this.resampler = new Resampler(sampleRate, TARGET_RATE);
      this.mono = new Float32Array(128);
      this.packer = new FramePacker((pcm, rms, peak) =>
        this.port.postMessage({ type: "frame", pcm, rms, peak }, [pcm]),
      );
      this.port.onmessage = (e) => {
        const m = e.data;
        if (m && m.type === "flush") {
          this.packer.flush();
          this.port.postMessage({ type: "flushed", seq: m.seq });
        }
      };
      const { taps, phases, exact } = this.resampler.bank;
      this.port.postMessage({ type: "ready", inputRate: sampleRate, outputRate: TARGET_RATE, taps, phases, exact });
    }

    process(inputs) {
      const channels = inputs[0];
      if (!channels || channels.length === 0 || channels[0].length === 0) return true; // no source connected
      const n = channels[0].length;
      if (this.mono.length !== n) this.mono = new Float32Array(n);
      if (channels.length === 1) {
        this.mono.set(channels[0]);
      } else {
        this.mono.fill(0);
        for (const ch of channels) for (let i = 0; i < n; i++) this.mono[i] += ch[i];
        for (let i = 0; i < n; i++) this.mono[i] /= channels.length;
      }
      this.packer.push(this.resampler.push(this.mono));
      return true;
    }
  }
  registerProcessor("pitwall-mic", MicProcessor);
}
