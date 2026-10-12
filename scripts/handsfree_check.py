"""Hands-free talking: acceptance checks on real and synthetic data (lane handsfree, docs/research/handsfree.md).

    uv run python scripts/handsfree_check.py --captures <copies>/*.pwcap [--moving-start]  # A1 (recorded): motion
    uv run python scripts/handsfree_check.py --rms <wav dir> --out vad_rms.json     # A6 (synthetic): VAD traces
    uv run python scripts/handsfree_check.py --wake <wav dir> [--engine parakeet]   # A3 (synthetic): wake word
    uv run --with sherpa-onnx==1.13.8 python scripts/handsfree_check.py --wake <wav dir> --engine sherpa \\
        --sherpa-dir <model dir> --threads 2                                       # A4 (synthetic, CPU engine)
    uv run python scripts/handsfree_check.py --audio data/handsfree-samples         # A9 (owed): a real voice
    uv run python scripts/handsfree_check.py --render <out dir>                     # the 17 probe phrases via `say`

Every mode prints JSON lines and exits 1 when an acceptance threshold fails.

* ``--captures``: decodes each capture with the real adapters and runs the shipped ``voice.handsfree.MotionGate``
  (Drive's hysteresis rule) over the player's frames as the hub sees them: a packet gap longer than ``LIVE_S`` makes
  the data stale ``LIVE_S`` after the last packet, and a car that was moving stays moving for ``STALE_STILL_AFTER_S``
  more (an incident gap), stationary after that. It compares flips and the longest stationary window with section 3.1
  (+-1 flip, +-0.5 s), checks that no frame above 8 km/h is classed stationary (frames the game flags paused or replay
  are counted apart), and counts the stops long enough for the "paused while driving" hint (``HINT_SETTLE_S``) and
  the shorter ones after driving (incidents, the grid) it no longer uses. Never commit or keep the captures (other
  players' names).
* ``--rms``: renders the section 3.3 conditions from ``<voice>__NN.wav`` clips (3 s of pink noise in front, the clip as
  rendered and 20 dB quieter, noise at -70 / -50 / -40 dBFS), writes one RMS value per 512-sample frame for the
  dashboard's TypeScript VAD test, and runs this script's reference ``EnergyVad`` (the same rules as
  ``web-react/src/lib/handsfree.ts``, section 4.2) on them for the expected results.
* ``--wake``: transcribes the clips (0.5 s lead-in, as the pre-roll gives) with the real speech engine, clean and with
  an engine-like drone at 10 dB SNR (and pink noise at 15 dB), and scores the shipped ``match_wake``.
* ``--audio``: a recorded voice reading ``SCRIPT`` (``NN.wav``, NN = line number, each starting with at least 1 s of
  the room's own noise): recall, false accepts and VAD splits. Recordings stay in ``data/`` and are never committed.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import re
import statistics
import subprocess
import sys
import time
import wave
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from scipy.signal import resample_poly

from pitwall.core.live import LIVE_S
from pitwall.voice.handsfree import HINT_SETTLE_S, MOVE_ABOVE_KPH, STALE_STILL_AFTER_S, MotionGate, match_wake
from pitwall.voice.types import AudioClip

RATE = 16_000
FRAME = 512  # samples per browser worklet frame (32 ms)

# ---------------------------------------------------------------------------------------------- section 3.1
# capture prefix -> (flips, longest stationary window s): the design scan (docs/research/handsfree.md section 3.1)
# (flips, longest stationary window in s) per capture as the hub sees it (section 3.1), with the shipped start
EXPECTED_MOTION: dict[str, tuple[int, float]] = {
    "20261010-191501": (2, 8.4),
    "20261010-203637": (1, 0.0),
    "20261010-215916": (2, 13.1),
    "20261010-221749": (7, 215.4),
    "20261010-225601": (5, 95.6),
    "20261011-010607": (4, 8.9),
    "20261011-183245": (0, 0.0),
    "20261011-185757": (12, 27.5),
    "20261011-013533": (1, 4.3),
    "20261011-124608": (6, 274.6),
    "20261011-182615": (1, 5.4),
}

# ---------------------------------------------------------------------------------------------- phrases
# The 17 synthetic probe phrases (section 3.2): 0-6 "Pitwall", 7-10 "Radio", 11-16 negatives.
PROBE = [
    "Pitwall, what's my fuel?",
    "Pitwall, how are my tyres?",
    "Pit wall, radio check.",
    "Pitwall.",
    "Hey Pitwall, when should I pit?",
    "OK Pitwall, gap to the car ahead?",
    "Pitwall... how was that lap?",
    "Radio, what's my gap to the car ahead?",
    "Radio check.",
    "Radio, how much fuel have I got?",
    "Radio.",
    "Pass me the water, would you?",
    "The pit wall told him to box this lap.",
    "I think the radio is too loud.",
    "That corner is a real pitfall.",
    "Box box, box box.",
    "What's for dinner tonight?",
]
PROBE_POS = {"pitwall": set(range(7)), "radio": set(range(7, 11))}
PROBE_NEG = set(range(11, 17))
SAY_VOICES = ["Daniel", "Samantha", "Fred", "Ralph", "Kathy", "Junior", "Albert"]

# A9: the owner reads these 24 lines on the rig (iPad + one AirPod), one file per line: NN.wav.
SCRIPT = [
    *PROBE,
    "Pitwall, where am I losing time?",
    "Pitwall, quiet for three laps.",
    "Pitwall... what's the gap behind?",
    "Radio, how many laps of fuel do I have left?",
    "Come on, come on, come on!",
    "Ugh, I missed the apex again.",
    "Turn nine, brake earlier next lap.",
]
SCRIPT_POS = {"pitwall": {0, 1, 2, 3, 4, 5, 6, 17, 18, 19}, "radio": {7, 8, 9, 10, 20}}
SCRIPT_NEG = {11, 12, 13, 14, 15, 16, 21, 22, 23}


def out(row: dict[str, Any]) -> None:
    print(json.dumps(row), flush=True)


# ============================================================================================ A1: motion gate
@dataclass
class MotionStats:
    capture: str
    frames: int = 0
    duration_s: float = 0.0
    still_s: float = 0.0
    runs: list[tuple[bool, float]] = field(default_factory=list)
    fast_stationary: int = 0  # frames over 8 km/h classed stationary (must be 0)
    flagged_fast: int = 0  # paused / replay frames over 8 km/h (stationary by the game's own flag)
    gaps: list[float] = field(default_factory=list)
    stale_moving: int = 0  # gaps the hub sees stale while the car still counts as moving (incidents: no stop)


def scan_capture(path: Path, moving_start: bool = False) -> MotionStats:
    from pitwall.ingest.capture import CaptureReader
    from pitwall.integrations import all_adapters
    from pitwall.model.telemetry import CarFrame, FrameQuality

    flagged = int(FrameQuality.PAUSED | FrameQuality.REPLAY_OR_SPECTATING)
    adapters = all_adapters()
    by_port: dict[int, Any] = {}
    # ``moving_start``: the design scan's start (the car counts as moving before its first frame, so a car already
    # stopped needs 1.5 s to count as stationary); the shipped gate follows motion.ts: stationary at once
    gate = MotionGate(stationary=False) if moving_start else MotionGate()
    st = MotionStats(path.name)
    state: bool | None = None
    since = 0.0
    t_prev: float | None = None
    f_prev: Any = None

    def flip(s: bool, t: float) -> None:
        nonlocal state, since
        if state is None:
            state, since = s, t
        elif s != state:
            st.runs.append((state, t - since))
            state, since = s, t

    for pk in CaptureReader(path):
        a = by_port.get(pk.src_port)
        if a is None:
            a = next((c for c in adapters if c.can_decode(pk.data)), None)
            if a is None:
                continue
            by_port[pk.src_port] = a
        try:
            items = a.decode(pk.data, pk.t_recv_ns)
        except Exception:
            continue
        for f in items:
            if not isinstance(f, CarFrame):
                continue
            t = f.t_recv_ns / 1e9
            if t_prev is not None:
                dt = t - t_prev
                if dt > LIVE_S:  # the stream stopped (menus, loading, pause, an incident): the hub sees it stale
                    st.gaps.append(dt)
                    t_stale = t_prev + LIVE_S
                    flip(gate.update(f_prev, False, t_stale), t_stale)
                    t_hold = t_stale + STALE_STILL_AFTER_S
                    if t_hold < t:
                        flip(gate.update(f_prev, False, t_hold), t_hold)
                    elif state is False:
                        st.stale_moving += 1
                st.duration_s += dt
            t_prev, f_prev = t, f
            stationary = gate.update(f, True, t)
            st.frames += 1
            v = f.speed_kph
            if v is not None and math.isfinite(v) and v > MOVE_ABOVE_KPH and stationary:
                if int(f.quality) & flagged:
                    st.flagged_fast += 1
                else:
                    st.fast_stationary += 1
            flip(stationary, t)
    if state is not None and t_prev is not None:
        st.runs.append((state, t_prev - since))
    st.still_s = sum(d for s, d in st.runs if s)
    return st


def check_captures(paths: Sequence[Path], moving_start: bool = False) -> int:
    failures = 0
    for p in paths:
        st = scan_capture(p, moving_start)
        still = [d for s, d in st.runs if s]
        flips = sum(1 for i in range(1, len(st.runs)) if st.runs[i][0] != st.runs[i - 1][0])
        longest = max(still, default=0.0)
        # stops that follow a moving stretch; the last run is cut off by the capture's end (a short one is unknown)
        last = len(st.runs) - 1
        starts = [sum(d for _, d in st.runs[:i]) for i in range(len(st.runs))]
        after_driving = [
            (starts[i], d) for i, (s, d) in enumerate(st.runs) if s and i > 0 and (i < last or d >= HINT_SETTLE_S)
        ]
        row: dict[str, Any] = {
            "capture": st.capture,
            "frames": st.frames,
            "duration_min": round(st.duration_s / 60, 1),
            "stationary_share": round(st.still_s / st.duration_s, 3) if st.duration_s else 0.0,
            "stationary_windows": len(still),
            "ge_5s": sum(d >= 5 for d in still),
            "ge_15s": sum(d >= 15 for d in still),
            "flips": flips,
            "longest_still_s": round(longest, 1),
            "stale_gaps_still_moving": st.stale_moving,
            "hint_settled_stops": sum(d >= HINT_SETTLE_S for _, d in after_driving),
            "hint_short_stops": sum(d < HINT_SETTLE_S for _, d in after_driving),
            "stops_after_driving": [[round(t / 60, 2), round(d, 1)] for t, d in after_driving],  # [minute, seconds]
            "fast_stationary": st.fast_stationary,
            "flagged_fast": st.flagged_fast,
        }
        key = p.name[:15]
        exp = EXPECTED_MOTION.get(key)
        ok = st.fast_stationary == 0
        if exp is not None and st.frames:
            row["expected"] = {"flips": exp[0], "longest_still_s": exp[1]}
            ok = ok and abs(flips - exp[0]) <= 1 and abs(longest - exp[1]) <= 0.5
        row["ok"] = ok
        failures += 0 if ok else 1
        out(row)
    out({"summary": "A1", "captures": len(paths), "failed": failures, "moving_start": moving_start})
    return 1 if failures else 0


# ============================================================================================ VAD (section 4.2)
@dataclass
class EnergyVad:
    """Reference implementation of the browser's energy VAD (web-react/src/lib/handsfree.ts, section 4.2): one RMS
    value per 32 ms frame. Every number is a heuristic."""

    calibration_frames: int = 31
    margin_db: float = 12.0
    abs_min_db: float = -50.0
    start_voiced: int = 4
    start_window: int = 5
    end_silence: int = 22
    max_frames: int = 250
    floor_down: float = 0.2
    floor_up: float = 0.005
    floor_min: float = -90.0
    floor_max: float = -35.0

    def run(self, rms: Iterable[float]) -> list[tuple[int, int, str]]:
        """Segments ``(start frame, end frame, reason)`` with reason ``silence`` | ``max`` | ``eof``."""
        db = [20.0 * math.log10(max(r, 1e-6)) for r in rms]
        segs: list[tuple[int, int, str]] = []
        if len(db) <= self.calibration_frames:
            return segs
        floor = float(statistics.median(db[: self.calibration_frames]))
        speech = False
        hist: list[bool] = []
        start = 0
        silent = 0
        for k in range(self.calibration_frames, len(db)):
            d = db[k]
            voiced = d >= max(floor + self.margin_db, self.abs_min_db)
            if not speech:
                hist = [*hist, voiced][-self.start_window :]
                if sum(hist) >= self.start_voiced:
                    speech, start, silent = True, k - self.start_window + 1, 0
                else:
                    a = self.floor_down if d < floor else self.floor_up
                    floor = min(self.floor_max, max(self.floor_min, floor + a * (d - floor)))
                continue
            silent = 0 if voiced else silent + 1
            floor = min(self.floor_max, floor + self.floor_up * max(0.0, d - floor))
            capped = k - start >= self.max_frames
            if silent >= self.end_silence or capped:
                segs.append((start, k, "max" if capped else "silence"))
                speech, hist = False, []
                if capped:  # continuous noise becomes the floor
                    floor = float(np.percentile(db[start : k + 1], 10))
        if speech:
            segs.append((start, len(db) - 1, "eof"))
        return segs


def frame_rms(x: np.ndarray) -> list[float]:
    n = x.size // FRAME
    f = x[: n * FRAME].reshape(n, FRAME).astype(np.float64)
    return [float(v) for v in np.sqrt((f**2).mean(axis=1))]


def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise SystemExit(f"{path}: need 16-bit mono WAV")
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
        rate = w.getframerate()
    if rate != RATE:
        g = math.gcd(RATE, rate)
        x = resample_poly(x, RATE // g, rate // g).astype(np.float32)
    return x


def pink(n: int, rng: np.random.Generator) -> np.ndarray:
    spectrum = np.fft.rfft(rng.standard_normal(n))
    k = np.arange(spectrum.size)
    k[0] = 1
    return np.fft.irfft(spectrum / np.sqrt(k), n).astype(np.float32)


# (name, clip gain dB, noise dBFS): the clips' speech is about -20 dBFS active, so these are about quiet, 30, 20, 10
# and 0 dB SNR (section 3.3)
VAD_CONDITIONS = [
    ("quiet", 0, -70),
    ("quiet", -20, -70),
    ("snr30", 0, -50),
    ("snr20", 0, -40),
    ("snr10", -20, -50),
    ("snr0", -20, -40),
]
A6 = {"quiet": (236, 238), "snr20": (115, 119)}  # min single segments


def vad_traces(wav_dir: Path) -> list[dict[str, Any]]:
    rng = np.random.default_rng(3)
    traces: list[dict[str, Any]] = []
    for p in sorted(wav_dir.glob("*__*.wav")):
        x = load_wav(p)
        for name, gain_db, noise_db in VAD_CONDITIONS:
            lead = np.zeros(3 * RATE, np.float32)
            tail = np.zeros(int(1.5 * RATE), np.float32)
            y = np.concatenate([lead, x * np.float32(10 ** (gain_db / 20)), tail])
            n = pink(y.size, rng)
            y = y + n / np.sqrt(np.mean(n**2)) * np.float32(10 ** (noise_db / 20))
            traces.append(
                {
                    "clip": p.stem,
                    "condition": name,
                    "gain_db": gain_db,
                    "noise_dbfs": noise_db,
                    "speech": [lead.size // FRAME, (lead.size + x.size) // FRAME],
                    "rms": [float(f"{v:.4g}") for v in frame_rms(y)],
                }
            )
    return traces


def score_vad(traces: Sequence[dict[str, Any]], vad: EnergyVad | None = None) -> dict[str, dict[str, int]]:
    vad = vad or EnergyVad()
    stats: dict[str, dict[str, int]] = {}
    for t in traces:
        segs = vad.run(t["rms"])
        sp0, sp1 = t["speech"]
        hit = [s for s in segs if s[0] <= sp1 and s[1] >= sp0]
        st = stats.setdefault(t["condition"], {"n": 0, "single": 0, "split": 0, "missed": 0, "false": 0})
        st["n"] += 1
        st["single" if len(hit) == 1 else "missed" if not hit else "split"] += 1
        st["false"] += len(segs) - len(hit)
    return stats


def check_rms(wav_dir: Path, out_path: Path | None) -> int:
    traces = vad_traces(wav_dir)
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        doc = {
            "about": "SYNTHETIC (macOS say voices): one RMS value per 512-sample frame at 16 kHz, from "
            "scripts/handsfree_check.py --rms; expected results in `expected` (the script's reference VAD).",
            "frame_samples": FRAME,
            "sample_rate": RATE,
            "expected": score_vad(traces),
            "traces": traces,
        }
        data = json.dumps(doc, separators=(",", ":")).encode("utf-8")
        if out_path.suffix == ".gz":  # reproducible bytes: no file name or time in the gzip header
            data = gzip.compress(data, compresslevel=9, mtime=0)
        out_path.write_bytes(data)
    stats = score_vad(traces)
    ok = True
    for cond, st in stats.items():
        out({"condition": cond, **st})
        ok = ok and st["false"] == 0
        if cond in A6:
            ok = ok and st["single"] >= A6[cond][0]
    if "snr0" in stats:
        ok = ok and stats["snr0"]["single"] + stats["snr0"]["split"] == 0
    out({"summary": "A6", "ok": ok, "file": str(out_path) if out_path else None})
    return 0 if ok else 1


# ============================================================================================ A3 / A4: wake word
def engine_drone(n: int) -> np.ndarray:
    t = np.arange(n) / RATE
    f0 = 110 + 20 * np.sin(2 * np.pi * 0.3 * t)
    phase = 2 * np.pi * np.cumsum(f0) / RATE
    return np.asarray(sum(np.sin(h * phase) / h for h in range(1, 12)), dtype=np.float32)


def mix(x: np.ndarray, noise: np.ndarray, snr_db: float) -> np.ndarray:
    voiced = x[np.abs(x) > 1e-3]
    ps = float(np.mean(voiced**2)) if voiced.size else 1e-6
    pn = float(np.mean(noise**2)) or 1e-9
    y: np.ndarray = np.clip(x + noise * np.sqrt(ps / (pn * 10 ** (snr_db / 10))), -1, 1).astype(np.float32)
    return y


def build_engine(name: str, sherpa_dir: Path | None, threads: int) -> Any:
    if name == "sherpa":
        from pitwall.voice.stt_sherpa import SherpaParakeetStt

        if sherpa_dir is None:
            raise SystemExit("--engine sherpa needs --sherpa-dir (a folder holding the four model files)")
        stt: Any = SherpaParakeetStt(folder=sherpa_dir, managed=False, threads=threads)
    else:
        from pitwall.voice.stt import ParakeetStt

        stt = ParakeetStt()
    t0 = time.perf_counter()
    stt.warmup()
    out({"engine": stt.name, "load_s": round(time.perf_counter() - t0, 2)})
    return stt


def score_wake(rows: Sequence[dict[str, Any]], pos: dict[str, set[int]], neg: set[int]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for word, positives in pos.items():
        others = neg | set().union(*(v for k, v in pos.items() if k != word))
        tp = sum(1 for r in rows if r["i"] in positives and match_wake(r["heard"], word) is not None)
        n_pos = sum(1 for r in rows if r["i"] in positives)
        fa = sum(1 for r in rows if r["i"] in others and match_wake(r["heard"], word) is not None)
        n_neg = sum(1 for r in rows if r["i"] in others)
        result[word] = {"recall": [tp, n_pos], "false_accepts": [fa, n_neg]}
    return result


def check_wake(wav_dir: Path, engine: str, sherpa_dir: Path | None, threads: int, variants: Sequence[str]) -> int:
    stt = build_engine(engine, sherpa_dir, threads)
    rng = np.random.default_rng(7)
    rows: list[dict[str, Any]] = []
    for p in sorted(wav_dir.glob("*__*.wav")):
        voice, idx = p.stem.split("__")
        x = load_wav(p)
        x = np.concatenate([np.zeros(RATE // 2, np.float32), x, np.zeros(int(0.3 * RATE), np.float32)])
        options = {
            "clean": x,
            "engine10": mix(x, engine_drone(x.size), 10),
            "pink15": mix(x, pink(x.size, rng), 15),
        }
        for v in variants:
            pcm = (np.clip(options[v], -1, 1) * 32767).astype("<i2").tobytes()
            t0 = time.perf_counter()
            res = stt.transcribe(AudioClip(pcm, RATE))
            ms = (time.perf_counter() - t0) * 1000
            rows.append({"voice": voice, "i": int(idx), "variant": v, "heard": res.text, "ms": round(ms, 1)})
    ok = True
    for v in variants:
        sub = [r for r in rows if r["variant"] == v]
        score = score_wake(sub, PROBE_POS, PROBE_NEG)
        lat = sorted(r["ms"] for r in sub)
        out({"variant": v, **score, "median_ms": lat[len(lat) // 2] if lat else None})
        pw, rd = score["pitwall"], score["radio"]
        bar = 0.80 if engine == "sherpa" else 0.85
        if v in ("clean", "engine10") and (engine != "sherpa" or v == "clean"):
            ok = ok and pw["recall"][0] >= bar * pw["recall"][1] and pw["false_accepts"][0] == 0
            if engine != "sherpa":
                ok = ok and rd["recall"][0] >= 0.85 * rd["recall"][1] and rd["false_accepts"][0] == 0
        for r in sub:
            if r["i"] in PROBE_POS["pitwall"] and match_wake(r["heard"], "pitwall") is None:
                out({"miss": "pitwall", "voice": r["voice"], "i": r["i"], "variant": v, "heard": r["heard"]})
    if engine == "sherpa":
        clean = sorted(r["ms"] for r in rows if r["variant"] == "clean")
        median = clean[len(clean) // 2] if clean else math.inf
        ok = ok and median <= 150.0
    out({"summary": "A4" if engine == "sherpa" else "A3", "ok": ok})
    return 0 if ok else 1


# ============================================================================================ A9: a real voice
def check_audio(sample_dir: Path, engine: str, sherpa_dir: Path | None, threads: int) -> int:
    files = sorted(p for p in sample_dir.glob("*.wav") if re.fullmatch(r"\d{2}", p.stem))
    if not files:
        raise SystemExit(f"no NN.wav recordings in {sample_dir} (read SCRIPT, one line per file)")
    stt = build_engine(engine, sherpa_dir, threads)
    vad = EnergyVad()
    rows: list[dict[str, Any]] = []
    for p in files:
        i = int(p.stem)
        x = load_wav(p)
        segs = vad.run(frame_rms(x))
        pcm = (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()
        res = stt.transcribe(AudioClip(pcm, RATE))
        row = {"i": i, "line": SCRIPT[i] if i < len(SCRIPT) else None, "heard": res.text, "vad_segments": len(segs)}
        rows.append(row)
        out(row)
    score = score_wake(rows, SCRIPT_POS, SCRIPT_NEG)
    splits = sum(1 for r in rows if r["vad_segments"] > 1 and r["i"] != 19)  # line 19 has a deliberate pause
    missed = sum(1 for r in rows if r["vad_segments"] == 0)
    out({"summary": "A9", **score, "vad_split": splits, "vad_missed": missed, "files": len(rows)})
    return 0


# ============================================================================================ rendering
def render(out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    for voice in SAY_VOICES:
        for i, phrase in enumerate(PROBE):
            wav = out_dir / f"{voice}__{i:02d}.wav"
            subprocess.run(
                ["say", "-v", voice, "--file-format=WAVE", "--data-format=LEI16@16000", "-o", str(wav), phrase],
                check=True,
                timeout=60,
            )
    out({"rendered": len(SAY_VOICES) * len(PROBE), "dir": str(out_dir)})
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--captures", nargs="+", type=Path, help="A1: .pwcap files (scratch copies)")
    mode.add_argument("--rms", type=Path, help="A6: folder of <voice>__NN.wav clips")
    mode.add_argument("--wake", type=Path, help="A3/A4: folder of <voice>__NN.wav clips")
    mode.add_argument("--audio", type=Path, help="A9: folder of NN.wav recordings of SCRIPT")
    mode.add_argument("--render", type=Path, help="render the probe phrases with macOS say into this folder")
    ap.add_argument("--out", type=Path, help="--rms: write the traces here (JSON; gzipped when it ends in .gz)")
    ap.add_argument(
        "--moving-start", action="store_true", help="--captures: the design scan's start (moving before frame 1)"
    )
    ap.add_argument("--engine", choices=("parakeet", "sherpa"), default="parakeet")
    ap.add_argument("--sherpa-dir", type=Path, help="folder holding the sherpa model's four files")
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--variants", default="clean,engine10,pink15")
    a = ap.parse_args(argv)
    if a.captures:
        return check_captures(a.captures, a.moving_start)
    if a.rms:
        return check_rms(a.rms, a.out)
    if a.wake:
        return check_wake(a.wake, a.engine, a.sherpa_dir, a.threads, a.variants.split(","))
    if a.audio:
        return check_audio(a.audio, a.engine, a.sherpa_dir, a.threads)
    return render(a.render)


if __name__ == "__main__":
    sys.exit(main())
