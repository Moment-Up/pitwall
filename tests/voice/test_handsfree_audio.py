"""SYNTHETIC tier, lane handsfree (A3): the wake word through the real Parakeet model (``uv run pytest -m voice``).

The 17 probe phrases (docs/research/handsfree.md section 3.3: 7 "Pitwall", 4 "Radio", 6 negatives) are rendered by
seven macOS ``say`` voices, given the 0.5 s lead-in the hands-free pre-roll provides, transcribed clean and with an
engine-like drone at 10 dB SNR, and scored with the shipped ``match_wake``. Thresholds: "Pitwall" recall >= 0.85 in
both conditions, "Radio" >= 0.85, no false accept (0/70 and 0/91). Synthetic voices clip the "P" of "Pitwall": this is
not evidence for a real voice on the rig (A9, owed).
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from pitwall.voice.stt import ParakeetStt
from pitwall.voice.types import AudioClip
from tests.unit.test_voice_stt import _real_parakeet_ready, _say_voice_installed, _voice_tests_requested

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [
    pytest.mark.voice,
    pytest.mark.synthetic,
    pytest.mark.skipif(not _real_parakeet_ready(), reason="needs macOS `say` and the Parakeet model in the HF cache"),
]


def _check() -> Any:
    spec = importlib.util.spec_from_file_location("handsfree_check", ROOT / "scripts" / "handsfree_check.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["handsfree_check"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def transcripts(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[list[dict[str, Any]]]:
    if not _voice_tests_requested(request.config):
        pytest.skip("real-model voice tests are opt-in: uv run pytest -m voice (or PITWALL_VOICE_TESTS=1)")
    hf = _check()
    voices = [v for v in hf.SAY_VOICES if _say_voice_installed(v)]
    if len(voices) < 5:
        pytest.skip(f"needs at least 5 of the probe's say voices ({', '.join(hf.SAY_VOICES)})")
    wav_dir = tmp_path_factory.mktemp("handsfree-wavs")
    for voice in voices:
        for i, phrase in enumerate(hf.PROBE):
            subprocess.run(
                [
                    "say",
                    "-v",
                    voice,
                    "--file-format=WAVE",
                    "--data-format=LEI16@16000",
                    "-o",
                    str(wav_dir / f"{voice}__{i:02d}.wav"),
                    phrase,
                ],
                check=True,
                timeout=60,
            )
    stt = ParakeetStt()
    stt.warmup()
    rows: list[dict[str, Any]] = []
    for p in sorted(wav_dir.glob("*.wav")):
        voice, idx = p.stem.split("__")
        x = hf.load_wav(p)
        x = np.concatenate([np.zeros(8000, np.float32), x, np.zeros(4800, np.float32)])
        for variant, y in (("clean", x), ("engine10", hf.mix(x, hf.engine_drone(x.size), 10))):
            pcm = (np.clip(y, -1, 1) * 32767).astype("<i2").tobytes()
            rows.append(
                {
                    "voice": voice,
                    "i": int(idx),
                    "variant": variant,
                    "heard": stt.transcribe(AudioClip(pcm, 16_000)).text,
                }
            )
    shutil.rmtree(wav_dir, ignore_errors=True)
    yield rows


@pytest.mark.parametrize("variant", ["clean", "engine10"])
def test_wake_word_recall_and_no_false_accepts(transcripts: list[dict[str, Any]], variant: str) -> None:
    hf = _check()
    score = hf.score_wake([r for r in transcripts if r["variant"] == variant], hf.PROBE_POS, hf.PROBE_NEG)
    (tp, n), (fa, _neg) = score["pitwall"]["recall"], score["pitwall"]["false_accepts"]
    assert tp >= 0.85 * n and fa == 0, score
    (tp, n), (fa, _neg) = score["radio"]["recall"], score["radio"]["false_accepts"]
    assert tp >= 0.85 * n and fa == 0, score
