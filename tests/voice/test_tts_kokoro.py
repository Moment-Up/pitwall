"""Opt-in tests against the REAL Kokoro worker (``uv run pytest -m tts -s``).

Needs the worker venv and model from ``scripts/setup-tts.sh``; skipped cleanly without them, and skipped unless
``-m tts`` is given (they start a ~0.7 GB worker process and, for the round trips, load Parakeet).

- Lexicon coverage: every corner, track, team and driver name pitwall knows goes through the real misaki G2P
  (``--g2p-only``, no model) and no word may be dropped.
- In **every voice of the radio's picker**:
  - the evaluation's six phrases are synthesised and checked with Parakeet: every number and key word must
    survive, and "thirteen" must never become "thirty" (tts-evaluation sections 3 and 6.9);
  - the cue parts the hub pre-synthesises (turn one to twenty, "brake", "Box, box.") are checked the way the hub
    checks them (silence trimmed, ``VERIFY_PAD_S`` of padding) - these short inputs are where Kokoro misbehaved.
- A long run-on answer stays inside the evaluation's memory budget (section 6.7: 2.5 GB transient).
- A voice that is not installed does not stop the worker from starting.
- The worker venv holds no GPL G2P package, and no GPL module is imported after real syntheses either.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pitwall.compat import venv_python
from pitwall.voice import audio_post
from pitwall.voice.hub import VERIFY_PAD_S, trim_silence
from pitwall.voice.speech import to_speech
from pitwall.voice.tts import KOKORO_VOICES, TTS_HOME, WorkerTts, speech_mismatch
from pitwall.voice.tts_lexicon import LEXICON_PATH, known_names, prepare_text
from pitwall.voice.tts_worker import MAX_SEGMENT_CHARS, read_frame
from pitwall.voice.types import AudioClip

pytestmark = pytest.mark.tts

PYTHON = venv_python(TTS_HOME / "tts-venv")
HF_HOME = TTS_HOME / "hf"
WORKER = Path(__file__).resolve().parents[2] / "src" / "pitwall" / "voice" / "tts_worker.py"
REVISION = "a71e4d38b236d968966a2002c4c895dbd12b1c3c"
MEMORY_BUDGET_MB = 2500.0  # tts-evaluation section 6.7: transient
LIST_DISTRIBUTIONS = "import importlib.metadata as m\nfor d in m.distributions(): print(d.metadata['Name'].lower())"
PHRASES = [
    "Radio check, loud and clear.",
    "Box, box. Box this lap for mediums.",
    "Turn two: you're braking about thirteen metres earlier than your reference. That's costing you three tenths.",
    "Lap four, one oh five point seven. Purple in sector two, keep pushing.",
    "Fuel is fine, we're plus zero point four laps. Tyres look good, the front left is the limit.",
    "Copy, checking.",
]
CUE_PARTS = [to_speech(f"T{n}") for n in range(1, 21)] + ["brake", "Box, box."]


@pytest.fixture(autouse=True, scope="module")
def _opt_in(request: pytest.FixtureRequest) -> None:
    # module scope: runs before the module-scoped worker fixture, so a plain `pytest` never starts a worker
    if "tts" not in (request.config.option.markexpr or ""):
        pytest.skip("opt-in: run with `pytest -m tts`")
    if not PYTHON.exists():
        pytest.skip(f"worker venv missing ({PYTHON}): run scripts/setup-tts.sh")


def _env() -> dict[str, str]:
    return {**os.environ, "HF_HOME": str(HF_HOME), "HF_HUB_OFFLINE": "1", "TOKENIZERS_PARALLELISM": "false"}


def _worker(voice: str = "bm_fable") -> WorkerTts:
    tts = WorkerTts(python=PYTHON, voice=voice, revision=REVISION, hf_home=HF_HOME, lexicon=LEXICON_PATH, fallback=None)
    tts.start()
    t0 = time.monotonic()
    while not tts.ready:
        assert time.monotonic() - t0 < 180, tts.diagnostics()
        time.sleep(0.1)
    return tts


@pytest.fixture(scope="module")
def kokoro() -> Iterator[WorkerTts]:
    tts = _worker()
    try:
        yield tts
    finally:
        tts.close()


@pytest.fixture(scope="module")
def parakeet() -> Any:
    if importlib.util.find_spec("parakeet_mlx") is None:
        pytest.skip("parakeet-mlx not installed (uv sync --extra voice)")
    from pitwall.voice.stt import ParakeetStt

    stt = ParakeetStt(postprocess=False)
    stt.warmup()
    return stt


def test_worker_venv_is_gpl_free() -> None:
    out = subprocess.run(
        [str(PYTHON), "-I", "-c", LIST_DISTRIBUTIONS],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout.split()
    for bad in ("phonemizer", "phonemizer-fork", "espeakng-loader", "pykakasi", "torch"):
        assert bad not in out, f"{bad} is installed in the worker venv"


def test_lexicon_covers_every_known_name() -> None:
    proc = subprocess.Popen(
        [str(PYTHON), "-I", str(WORKER), "--g2p-only", "--lexicon", str(LEXICON_PATH)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=_env(),
    )
    assert proc.stdin is not None and proc.stdout is not None
    try:
        ready = read_frame(proc.stdout)
        assert ready is not None and ready[0] == "R", ready
        assert json.loads(ready[1])["gpl_free"] is True
        dropped: dict[str, list[str]] = {}
        names = known_names()
        for i, name in enumerate(names):
            proc.stdin.write((json.dumps({"op": "g2p", "id": i, "text": prepare_text(name)}) + "\n").encode())
            proc.stdin.flush()
            frame = read_frame(proc.stdout)
            assert frame is not None and frame[0] == "E", frame
            reply = json.loads(frame[1])
            assert reply["id"] == i and reply["gpl_loaded"] == []
            for word in reply["dropped"]:
                dropped.setdefault(word, []).append(name)
        assert not dropped, f"G2P drops these words (add them to voice/data/lexicon.json): {dropped}"
        print(f"\nlexicon: {len(names)} names, none dropped")
    finally:
        proc.stdin.close()
        proc.wait(10)


@pytest.mark.parametrize("voice", KOKORO_VOICES)
def test_six_phrases_round_trip_through_parakeet(kokoro: WorkerTts, parakeet: Any, voice: str) -> None:
    kokoro.set_voice(voice)
    pad = b"\x00\x00" * 6000
    report = []
    for phrase in PHRASES:
        res = kokoro.synthesize_detailed(phrase)
        assert res.engine == "kokoro" and res.neural, res.fallback_reason
        m = audio_post.measure(res.clip)
        assert m is not None and -19.5 < m.rms_dbfs < -15.5 and m.peak_dbfs <= -2.9 and m.lead_s <= 0.05
        heard = parakeet.transcribe(AudioClip(pad + res.clip.pcm + pad, res.clip.sample_rate)).text
        report.append((phrase, round(res.synth_ms), round(res.clip.duration_s, 2), heard))
        assert speech_mismatch(phrase, heard) is None, (voice, phrase, heard)
        if "thirteen" in phrase:
            assert "thirty" not in heard.lower() and "30" not in heard, heard
    for row in report:
        print(f"\n{voice} {row[1]:5d} ms  {row[2]:5.2f} s  {row[0]!r}\n                heard {row[3]!r}", end="")
    diag = kokoro.diagnostics()
    print(f"\nsynth p50 {diag['synth_ms']['p50']} ms, memory {diag['memory_mb']}")
    assert diag["dropped_words"] == {}
    assert diag["gpl_free"] is True  # every end record so far reported no GPL module imported


@pytest.mark.parametrize("voice", KOKORO_VOICES)
def test_cue_parts_round_trip_through_parakeet(kokoro: WorkerTts, parakeet: Any, voice: str) -> None:
    """Short inputs, checked like the hub does it (``RadioHub._cue_part_audio`` / ``_verified``). Before the worker
    said them with a cut-off carrier, bf_isabella's "turn nine" was "turn ninth" every time and the female
    voices' "Box, box." was "box boxy"."""
    kokoro.set_voice(voice)
    misheard = []
    for part in CUE_PARTS:
        res = kokoro.synthesize_detailed(part)
        assert res.engine == "kokoro", res.fallback_reason
        clip = trim_silence(res.clip)
        assert 0.15 < clip.duration_s < 1.5, (part, clip.duration_s)  # the carrier was cut off
        pad = b"\x00\x00" * round(VERIFY_PAD_S * clip.sample_rate)
        heard = parakeet.transcribe(AudioClip(pad + clip.pcm + pad, clip.sample_rate)).text
        if speech_mismatch(part, heard) is not None or "over" in heard.lower():
            misheard.append((part, heard))
    assert not misheard, f"{voice}: {misheard}"


def test_long_run_on_answer_stays_inside_the_memory_budget(kokoro: WorkerTts) -> None:
    kokoro.set_voice("bm_fable")
    base = "you are braking a little early into the hairpin and losing time on the exit because the rear steps out"
    text = ((base + " and ") * 14)[:1400].rsplit(" ", 1)[0] + "."  # one 1,400-character sentence
    res = kokoro.synthesize_detailed(text)
    assert res.engine == "kokoro" and res.clip.duration_s > 60
    mem = kokoro.diagnostics()["memory_mb"]
    print(f"\n1,400-character sentence: {res.synth_ms:.0f} ms, memory {mem}")
    assert mem["request_peak_mb"] <= MEMORY_BUDGET_MB, (mem, MAX_SEGMENT_CHARS)


def test_uninstalled_voice_does_not_stop_the_worker() -> None:
    tts = _worker(voice="bm_nobody")
    try:
        d = tts.diagnostics()
        assert tts.voice == "bm_fable" and d["status"] == "ready" and d["consecutive_failures"] == 0
        assert tts.synthesize_detailed("Copy.").engine == "kokoro"
    finally:
        tts.close()
