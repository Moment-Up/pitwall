"""Benchmark ParakeetStt on the driver questions from the radio protocol, using macOS ``say`` audio.

    uv run python scripts/bench_stt.py [--model ID] [--voice Daniel] [--rate 16000] [--repeats 5]
                                       [--idle-s 10] [--cache-limit-mb 256 | --cache-limit-mb -1]

For each phrase it prints the transcript, the intent the engineer would detect, and two latencies:

* hot: ``--repeats`` back-to-back calls with the GPU busy (first call and median), and the real-time factor
  (hot median / audio duration). This is the best case.
* idle: one call after ``--idle-s`` seconds without inference. Radio questions come seconds or minutes apart,
  and by then the GPU has clocked down and MLX may have released its buffers, so this is the figure to
  quote for real use. ``--idle-s 0`` skips it.

``--cache-limit-mb`` sets MLX's buffer-cache cap (the engine default is 256 MB; ``-1`` leaves MLX
uncapped), so the memory/latency trade-off of the cap can be measured under both spacings.

It also prints process memory before and after the model loads: resident set size (RSS), the physical
footprint that Activity Monitor reports, and MLX's own GPU allocator counters. On Apple Silicon most of the
model lives in Metal buffers, which RSS under-counts; the footprint is the honest figure.

The first run downloads the model (about 2.5 GB) into the default Hugging Face cache.

``say`` audio is clean synthetic speech. These numbers are a lower bound for real rig audio with engine
noise, an earbud mic and accents (see docs/research/voice-stack.md §9 for the real benchmark plan).
"""

from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path

from pitwall.ai.engineer import detect_intent
from pitwall.voice.stt import DEFAULT_PARAKEET_MODEL, ParakeetStt
from pitwall.voice.types import AudioClip

# The example driver questions from the radio protocol / engineer intent tests, plus braking and corner
# phrasings that Parakeet mis-hears ("breaking", "Turn to.") in ways only correct_racing_terms rescues.
PHRASES: tuple[str, ...] = (
    "Where am I losing the most time?",
    "Give me one thing to work on.",
    "Where should I be braking for Turn 1?",
    "Compare that lap to my best.",
    "How are my tyres?",
    "What's my fuel situation?",
    "Stop talking for a few laps.",
    "Is my braking consistent?",
    "How was my braking that lap?",
    "Turn two, what went wrong?",
)


@dataclass(slots=True, frozen=True)
class MemSnapshot:
    rss_mb: float | None
    footprint_mb: float | None
    mlx_active_mb: float | None
    mlx_cache_mb: float | None
    mlx_peak_mb: float | None

    def render(self) -> str:
        def f(v: float | None) -> str:
            return "n/a" if v is None else f"{v:,.0f} MB"

        return (
            f"RSS {f(self.rss_mb)} | phys footprint {f(self.footprint_mb)} | "
            f"MLX active {f(self.mlx_active_mb)}, cache {f(self.mlx_cache_mb)}, peak {f(self.mlx_peak_mb)}"
        )


def _proc_rusage() -> tuple[float, float] | None:
    """(resident MB, phys_footprint MB) for this process via libproc ``proc_pid_rusage`` (macOS only)."""
    if sys.platform != "darwin":
        return None
    try:
        lib = ctypes.CDLL("/usr/lib/libproc.dylib")
    except OSError:
        return None
    # struct rusage_info_v0: uint8 ri_uuid[16] (2 words), then uint64 user_time, system_time, pkg_idle_wkups,
    # interrupt_wkups, pageins, wired_size, resident_size (word 8), phys_footprint (word 9), ...
    buf = (ctypes.c_uint64 * 12)()
    if lib.proc_pid_rusage(os.getpid(), 0, ctypes.byref(buf)) != 0:
        return None
    return buf[8] / 1e6, buf[9] / 1e6


def _ps_rss_mb() -> float | None:
    try:
        out = subprocess.run(["ps", "-o", "rss=", "-p", str(os.getpid())], capture_output=True, text=True, check=True)
        return int(out.stdout.strip()) / 1024
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None


def mem_snapshot() -> MemSnapshot:
    usage = _proc_rusage()
    rss, footprint = usage if usage is not None else (_ps_rss_mb(), None)
    active = cache = peak = None
    if "mlx.core" in sys.modules:  # don't import MLX just to measure it (that would skew the "before" figure)
        mx = sys.modules["mlx.core"]
        active, cache, peak = (
            mx.get_active_memory() / 1e6,
            mx.get_cache_memory() / 1e6,
            mx.get_peak_memory() / 1e6,
        )
    return MemSnapshot(rss, footprint, active, cache, peak)


def say_to_clip(text: str, path: Path, rate: int, voice: str | None) -> AudioClip:
    cmd = ["say", "-o", str(path), f"--data-format=LEI16@{rate}"]
    if voice:
        cmd += ["-v", voice]
    subprocess.run([*cmd, text], check=True, timeout=60)
    with wave.open(str(path)) as w:
        if (w.getnchannels(), w.getsampwidth()) != (1, 2):
            raise RuntimeError(f"unexpected WAV format from say: {w.getnchannels()} ch, {w.getsampwidth()} B")
        return AudioClip(w.readframes(w.getnframes()), w.getframerate())


def _voice_available(voice: str) -> bool:
    out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, check=False).stdout
    return any(line.split()[:1] == [voice] for line in out.splitlines())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=DEFAULT_PARAKEET_MODEL)
    ap.add_argument("--voice", default="Daniel", help="macOS say voice (falls back to the system default)")
    ap.add_argument("--rate", type=int, default=16_000, help="sample rate of the generated audio")
    ap.add_argument("--repeats", type=int, default=5, help="back-to-back (hot) transcriptions per phrase")
    ap.add_argument("--idle-s", type=float, default=10.0, help="idle time before each post-idle call (0: skip)")
    ap.add_argument(
        "--cache-limit-mb", type=int, default=256, help="MLX buffer-cache cap in MB (-1: leave MLX uncapped)"
    )
    args = ap.parse_args(argv)
    cache_limit: int | None = args.cache_limit_mb if args.cache_limit_mb >= 0 else None

    if sys.platform != "darwin" or shutil.which("say") is None:
        print("needs macOS with the `say` command", file=sys.stderr)
        return 2
    voice: str | None = args.voice if args.voice and _voice_available(args.voice) else None
    if args.voice and voice is None:
        print(f"voice {args.voice!r} not installed; using the system default voice")

    with tempfile.TemporaryDirectory(prefix="pitwall-bench-stt-") as tmp:
        clips = [say_to_clip(p, Path(tmp) / f"q{i}.wav", args.rate, voice) for i, p in enumerate(PHRASES)]

    before = mem_snapshot()
    engine = ParakeetStt(args.model, mlx_cache_limit_mb=cache_limit)
    engine.warmup()
    after_load = mem_snapshot()

    cap = "uncapped" if cache_limit is None else f"{cache_limit} MB"
    print(f"model      {args.model} (MLX cache cap {cap})")
    print(f"audio      say -v {voice or '(default)'} @ {args.rate} Hz, {args.repeats} hot runs per phrase")
    print(f"load       {engine.load_s or 0.0:.2f} s load + {engine.warm_s or 0.0:.2f} s warm-up inference")
    print(f"memory     before load : {before.render()}")
    print(f"           after load  : {after_load.render()}")
    print()
    header = (
        f"{'phrase':36} {'transcript':38} {'intent':16} {'audio':>6} {'first':>7} {'hot':>7} {'RTF':>6} {'idle':>7}"
    )
    print(header)
    print("-" * len(header))
    hot: list[float] = []
    rtfs: list[float] = []
    idle: list[int] = []
    wrong = 0
    for phrase, clip in zip(PHRASES, clips, strict=True):
        lat: list[int] = []
        text = ""
        for i in range(max(1, args.repeats)):
            res = engine.transcribe(clip)
            lat.append(res.latency_ms)
            if i == 0:
                text = res.text
        med = statistics.median(lat)
        rtf = med / 1000 / clip.duration_s
        hot.append(med)
        rtfs.append(rtf)
        idle_col = ""
        if args.idle_s > 0:
            time.sleep(args.idle_s)
            idle.append(engine.transcribe(clip).latency_ms)
            idle_col = f"{idle[-1]:5d}ms"
        intent = detect_intent(text)
        expected = detect_intent(phrase)
        ok = (intent.name, intent.corner) == (expected.name, expected.corner)
        wrong += not ok
        label = intent.name + (f" {intent.corner}" if intent.corner else "") + ("" if ok else " (!)")
        print(
            f"{phrase:36} {text:38} {label:16} {clip.duration_s:5.2f}s {lat[0]:5d}ms {med:5.0f}ms {rtf:6.3f} "
            f"{idle_col:>7}"
        )

    silent = AudioClip(bytes(2 * args.rate * 4), args.rate)
    gate_ms = engine.transcribe(silent).latency_ms
    end = mem_snapshot()
    print()
    print(
        f"hot (back-to-back) median latency: {statistics.median(hot):.0f} ms; median RTF {statistics.median(rtfs):.3f}"
    )
    if idle:
        print(
            f"after {args.idle_s:g} s idle: median {statistics.median(idle):.0f} ms, "
            f"range {min(idle)}-{max(idle)} ms over {len(idle)} phrases"
        )
    print(f"intent differs from the typed phrase: {wrong}/{len(PHRASES)} (marked (!))")
    print(f"4 s of silence (energy gate): {gate_ms} ms")
    print(f"memory after benchmark: {end.render()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
