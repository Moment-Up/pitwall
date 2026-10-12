"""Opt-in audio check of the spotter phrases (manual; NOT part of ``make check``): render every phrase of both wording
sets in every Kokoro voice of the radio's picker and in ``say``, transcribe each clip with Parakeet the way the hub
checks it (silence trimmed, ``VERIFY_PAD_S`` of padding), and report mismatches - "left" and "right" must match
exactly - and every clip's duration.

    nice uv run python scripts/spotter_phrases_check.py [--voices bm_fable,bm_george] [--no-say] [--json out.json]

Needs the Kokoro worker venv (``scripts/setup-tts.sh``) and parakeet-mlx (``uv sync --extra voice``). It starts one
Kokoro worker (~0.7 GB) and loads Parakeet: the Mac is memory-tight, so run it with ``nice``, one at a time, never
while a race is live. It stops the worker before exiting. Phrases that fail are pinned to the fallback voice at run
time by ``voice.spotter_audio`` (re-render once, then ``say``); this script only reports.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--voices", default=None, help="comma-separated Kokoro voices (default: the picker's)")
    ap.add_argument("--no-say", action="store_true", help="skip the say fallback voice")
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args(argv)

    from pitwall.config import Settings
    from pitwall.spotter.phrases import all_texts, heard_mismatch
    from pitwall.voice.hub import VERIFY_PAD_S, trim_silence
    from pitwall.voice.stt import ParakeetStt
    from pitwall.voice.tts import KOKORO_VOICES, WorkerTts, build_tts
    from pitwall.voice.types import AudioClip

    stt = ParakeetStt(postprocess=False)
    stt.warmup()

    def heard(clip: AudioClip) -> str:
        pad = b"\x00\x00" * round(VERIFY_PAD_S * clip.sample_rate)
        return stt.transcribe(AudioClip(pad + clip.pcm + pad, clip.sample_rate), None).text

    rows: list[dict[str, Any]] = []
    tts = build_tts(Settings(tts_engine="kokoro"))
    if not isinstance(tts, WorkerTts):
        print(f"kokoro unavailable ({type(tts).__name__}): only say is checked", file=sys.stderr)
    try:
        engines: list[tuple[str, Any]] = []
        if isinstance(tts, WorkerTts):
            tts.start()
            t0 = time.monotonic()
            while not tts.ready and time.monotonic() - t0 < 180:
                time.sleep(0.2)
            if tts.ready:
                voices = a.voices.split(",") if a.voices else [v for v in KOKORO_VOICES if v in tts.voices]
                for v in voices:
                    engines.append((f"kokoro:{v}", lambda text, v=v: tts.synthesize_detailed(text, voice=v).clip))
            if not a.no_say:
                engines.append(("say", tts.synthesize_fallback))
        elif not a.no_say:
            engines.append((getattr(tts, "name", "say"), tts.synthesize))
        for name, synth in engines:
            bad = 0
            for pid, wording, text in all_texts():
                clip = trim_silence(synth(text))
                got = heard(clip)
                why = heard_mismatch(pid, wording == "simple", got)
                bad += why is not None
                rows.append(
                    {
                        "engine": name,
                        "phrase": pid,
                        "wording": wording,
                        "text": text,
                        "heard": got,
                        "ok": why is None,
                        "why": why,
                        "clip_s": round(clip.duration_s, 2),
                    }
                )
                flag = "OK " if why is None else "BAD"
                print(f"{flag} {name:16} {wording:8} {text:40} {clip.duration_s:4.2f}s heard {got!r}", flush=True)
            print(f"== {name}: {bad} mismatch(es) of {len(all_texts())}", flush=True)
    finally:
        close = getattr(tts, "close", None)
        if callable(close):
            close()
    if a.json is not None:
        a.json.write_text(json.dumps(rows, indent=1))
    swapped = [r for r in rows if _swapped(r["text"], r["heard"])]
    for r in swapped:
        print(f"SIDE SWAPPED: {r['engine']} {r['text']!r} heard as {r['heard']!r}", flush=True)
    return 1 if swapped else 0


def _swapped(text: str, heard: str) -> bool:
    """The dangerous case: a phrase about one side heard with the other side's word."""
    from pitwall.spotter.phrases import heard_words

    said, got = set(heard_words(text)), set(heard_words(heard))
    return ("left" in said and "right" in got) or ("right" in said and "left" in got)


if __name__ == "__main__":
    sys.exit(main())
