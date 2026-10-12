"""Speech-to-text engines: PCM conversion, energy gate, resampling, engine behaviour with fake models and a
mocked whisper-server, factory fallbacks, racing-term corrections.

Tests marked ``voice`` run the real Parakeet model on macOS ``say`` audio. They are opt-in because they load
about 1.3 GB of MLX weights and depend on how the installed ``say`` voices pronounce each phrase:

    uv run pytest -m voice tests/unit/test_voice_stt.py      (or set PITWALL_VOICE_TESTS=1)

Even then they are skipped unless the model is already in the HF cache.
"""

from __future__ import annotations

import email.message
import email.parser
import io
import itertools
import logging
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import wave
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import numpy as np
import pytest

from pitwall.ai.engineer import detect_intent
from pitwall.config import Settings
from pitwall.voice import stt as stt_mod
from pitwall.voice.stt import (
    DEFAULT_PARAKEET_MODEL,
    DEFAULT_WHISPER_PROMPT,
    EnergyGate,
    Float32Array,
    NullStt,
    ParakeetStt,
    SttError,
    WhisperCppStt,
    build_stt,
    correct_racing_terms,
    encode_wav,
    float32_to_pcm16,
    pcm16_to_float32,
    resample,
)
from pitwall.voice.types import AudioClip, SttEngine


# ---------------------------------------------------------------------------------------------- helpers
def tone(freq_hz: float, seconds: float, rate: int, amp: float = 0.3) -> Float32Array:
    t = np.arange(round(seconds * rate)) / rate
    return (amp * np.sin(2 * np.pi * freq_hz * t)).astype(np.float32)


def silence(seconds: float, rate: int) -> Float32Array:
    return np.zeros(round(seconds * rate), dtype=np.float32)


def clip_of(samples: Float32Array, rate: int) -> AudioClip:
    return AudioClip(float32_to_pcm16(samples), rate)


def utterance(rate: int = 16_000, lead_s: float = 1.0, speech_s: float = 1.0, tail_s: float = 1.0) -> AudioClip:
    """Silence / 'speech' (a tone burst) / silence."""
    return clip_of(
        np.concatenate([silence(lead_s, rate), tone(300, speech_s, rate), silence(tail_s, rate)]),
        rate,
    )


def dominant_hz(x: Float32Array, rate: int) -> float:
    spec = np.abs(np.fft.rfft(x * np.hanning(x.size)))
    return float(np.fft.rfftfreq(x.size, 1 / rate)[int(np.argmax(spec))])


class FakeRecognizer:
    """Stands in for the MLX model: records what it was given and returns a scripted transcript."""

    def __init__(self, text: str = " Where should I be breaking for turn to? ", sample_rate: int = 16_000) -> None:
        self.sample_rate = sample_rate
        self.text = text
        self.calls: list[Float32Array] = []
        self.active = 0
        self.max_active = 0
        self.delay_s = 0.0
        self.fail: Exception | None = None
        self._guard = threading.Lock()

    def __call__(self, audio: Float32Array) -> str:
        with self._guard:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.delay_s:
                time.sleep(self.delay_s)
            if self.fail is not None:
                raise self.fail
            self.calls.append(audio)
            return self.text
        finally:
            with self._guard:
                self.active -= 1


class CountingLoader:
    def __init__(self, rec: FakeRecognizer | None = None, failures: int = 0) -> None:
        self.rec = rec or FakeRecognizer()
        self.failures = failures
        self.calls: list[str] = []

    def __call__(self, model_id: str) -> FakeRecognizer:
        self.calls.append(model_id)
        if len(self.calls) <= self.failures:
            raise OSError("model.safetensors not found")
        return self.rec


def warm(engine: ParakeetStt) -> ParakeetStt:
    engine.warmup()
    return engine


def wait_until(cond: Callable[[], bool], timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not cond():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        time.sleep(0.005)


class BlockingLoader:
    """A loader that stays 'loading' (like a model download) until released."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.rec = FakeRecognizer()

    def __call__(self, model_id: str) -> FakeRecognizer:
        self.started.set()
        if not self.release.wait(10):
            raise TimeoutError("test never released the loader")
        return self.rec


# ---------------------------------------------------------------------------------------------- audio utils
def test_pcm16_to_float32_scaling_and_dtype() -> None:
    pcm = np.array([0, 16384, -16384, 32767, -32768], dtype="<i2").tobytes()
    x = pcm16_to_float32(pcm)
    assert x.dtype == np.float32
    assert x.tolist() == pytest.approx([0.0, 0.5, -0.5, 32767 / 32768, -1.0])


def test_pcm16_to_float32_drops_torn_trailing_byte_and_handles_empty() -> None:
    pcm = np.array([1000, -1000], dtype="<i2").tobytes() + b"\x7f"
    assert pcm16_to_float32(pcm).size == 2
    assert pcm16_to_float32(b"").size == 0


def test_pcm_round_trip_and_clipping() -> None:
    x = np.array([0.0, 0.25, -0.75, 1.5, -2.0], dtype=np.float32)
    back = pcm16_to_float32(float32_to_pcm16(x))
    assert back[:3].tolist() == pytest.approx([0.0, 0.25, -0.75], abs=1 / 32768)
    assert back[3] == pytest.approx(32767 / 32768)
    assert back[4] == -1.0


def test_resample_identity_is_a_no_op() -> None:
    x = tone(440, 0.5, 16_000)
    assert resample(x, 16_000, 16_000) is x


@pytest.mark.parametrize("src", [48_000, 44_100, 22_050, 8_000])
def test_resample_preserves_duration_and_pitch(src: int) -> None:
    x = tone(440, 1.0, src)
    y = resample(x, src, 16_000)
    assert y.dtype == np.float32
    assert abs(y.size - 16_000) <= 1
    assert dominant_hz(y, 16_000) == pytest.approx(440, abs=2)


def test_resample_removes_content_above_new_nyquist() -> None:
    # 12 kHz is above 8 kHz (Nyquist at 16 kHz): a naive decimator would alias it down to 4 kHz
    y = resample(tone(12_000, 1.0, 48_000), 48_000, 16_000)
    assert float(np.sqrt(np.mean(y[200:-200] ** 2))) < 0.003


def test_resample_rejects_bad_rates() -> None:
    with pytest.raises(ValueError):
        resample(tone(440, 0.1, 16_000), 0, 16_000)


def test_encode_wav_is_16k_mono_int16() -> None:
    data = encode_wav(tone(440, 0.25, 16_000), 16_000)
    with wave.open(io.BytesIO(data)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, 16_000, 4000)


# ---------------------------------------------------------------------------------------------- energy gate
def test_gate_rejects_digital_silence_short_taps_and_dc_offset() -> None:
    gate = EnergyGate()
    assert gate.speech_span(silence(3.0, 16_000), 16_000) is None
    assert gate.speech_span(tone(300, 0.1, 16_000), 16_000) is None  # 100 ms tap
    assert gate.speech_span(np.full(32_000, 0.2, dtype=np.float32), 16_000) is None  # DC, no signal


def test_gate_rejects_quiet_room_noise_but_accepts_quiet_speech() -> None:
    rng = np.random.default_rng(1)
    noise = (rng.standard_normal(48_000) * 10 ** (-60 / 20)).astype(np.float32)  # about -60 dBFS
    assert EnergyGate().speech_span(noise, 16_000) is None
    quiet_speech = noise.copy()
    quiet_speech[16_000:24_000] += tone(300, 0.5, 16_000, amp=10 ** (-40 / 20) * np.sqrt(2))  # -40 dBFS RMS
    assert EnergyGate().speech_span(quiet_speech, 16_000) is not None


def test_gate_requires_enough_voiced_audio() -> None:
    x = np.concatenate([silence(1.0, 16_000), tone(300, 0.1, 16_000), silence(1.0, 16_000)])
    assert EnergyGate().speech_span(x, 16_000) is None
    assert EnergyGate(min_voiced_s=0.05).speech_span(x, 16_000) is not None


def test_gate_trims_to_voiced_span_with_padding() -> None:
    rate = 16_000
    x = np.concatenate([silence(2.0, rate), tone(300, 1.0, rate), silence(3.0, rate)])
    span = EnergyGate(pad_s=0.3).speech_span(x, rate)
    assert span is not None
    start, end = span
    assert start == pytest.approx(1.7 * rate, abs=0.02 * rate)
    assert end == pytest.approx(3.3 * rate, abs=0.02 * rate)
    # padding is clamped to the clip
    assert EnergyGate(pad_s=5.0).speech_span(x, rate) == (0, x.size)


def test_gate_rejects_invalid_rate() -> None:
    with pytest.raises(ValueError):
        EnergyGate().speech_span(tone(300, 1.0, 16_000), 0)


# ---------------------------------------------------------------------------------------------- ParakeetStt
def test_parakeet_silent_or_short_clip_returns_empty_fast_without_loading_model() -> None:
    loader = CountingLoader()
    engine = ParakeetStt(loader=loader)
    for clip in (
        clip_of(silence(5.0, 16_000), 16_000),
        clip_of(tone(300, 0.1, 16_000), 16_000),
        AudioClip(b"", 16_000),
    ):
        res = engine.transcribe(clip)
        assert res.text == ""
        assert res.engine == "parakeet"
        assert res.latency_ms < 50
        assert res.audio_s == pytest.approx(clip.duration_s)
    assert loader.calls == []
    assert not engine.loaded


def test_parakeet_converts_trims_resamples_and_corrects() -> None:
    loader = CountingLoader()
    engine = warm(ParakeetStt("some/model", loader=loader))
    clip = utterance(rate=48_000, lead_s=1.0, speech_s=1.0, tail_s=2.0)
    res = engine.transcribe(clip, prompt="Eau Rouge, Pouhon")  # prompt is accepted and ignored
    assert loader.calls == ["some/model"]
    assert res.text == "Where should I be braking for turn two?"
    assert res.engine == "parakeet"
    assert res.audio_s == pytest.approx(4.0)
    _warmup_call, audio = loader.rec.calls
    assert audio.dtype == np.float32
    # 1 s of speech + 2 x 0.3 s padding, resampled 48 kHz -> 16 kHz
    assert audio.size == pytest.approx(1.6 * 16_000, abs=0.03 * 16_000)
    assert float(np.max(np.abs(audio))) == pytest.approx(0.3, abs=0.02)
    assert dominant_hz(audio, 16_000) == pytest.approx(300, abs=3)


def test_parakeet_postprocess_can_be_disabled() -> None:
    engine = warm(ParakeetStt(loader=CountingLoader(), postprocess=False))
    assert engine.transcribe(utterance()).text == "Where should I be breaking for turn to?"


def test_parakeet_loads_once_and_warmup_runs_one_inference() -> None:
    loader = CountingLoader()
    engine = ParakeetStt(loader=loader)
    assert not engine.loaded
    engine.warmup()
    engine.warmup()
    assert engine.loaded
    assert loader.calls == [DEFAULT_PARAKEET_MODEL]
    assert len(loader.rec.calls) == 1  # warm-up inference (compiles kernels), only once
    assert loader.rec.calls[0].size == 8_000
    engine.transcribe(utterance())
    engine.transcribe(utterance())
    assert loader.calls == [DEFAULT_PARAKEET_MODEL]
    assert engine.load_s is not None and engine.warm_s is not None


def test_parakeet_transcribe_never_waits_for_a_load_in_progress() -> None:
    # e.g. the first-run 2.5 GB download started by the hub's warm-up when the iPad connected
    loader = BlockingLoader()
    engine = ParakeetStt(loader=loader)
    warming = threading.Thread(target=engine.warmup)
    warming.start()
    try:
        assert loader.started.wait(5)
        assert engine.loading
        t0 = time.perf_counter()
        for _ in range(3):
            with pytest.raises(SttError, match="still loading"):
                engine.transcribe(utterance())
        assert time.perf_counter() - t0 < 0.5
        assert engine.transcribe(clip_of(silence(2.0, 16_000), 16_000)).text == ""  # the gate still answers
    finally:
        loader.release.set()
        warming.join(5)
    assert engine.loaded and not engine.loading
    assert engine.transcribe(utterance()).text == "Where should I be braking for turn two?"


def test_parakeet_cold_transcribe_fails_fast_and_loads_in_background() -> None:
    loader = BlockingLoader()
    engine = ParakeetStt("some/model", loader=loader)
    with pytest.raises(SttError, match="still loading"):
        engine.transcribe(utterance())
    assert loader.started.wait(5)  # the background load is running, not the caller
    with pytest.raises(SttError, match="still loading"):
        engine.transcribe(utterance())
    loader.release.set()
    wait_until(lambda: engine.loaded)
    assert engine.transcribe(utterance()).text == "Where should I be braking for turn two?"
    assert len(loader.rec.calls) == 2  # background warm-up inference + the question


def test_parakeet_warmup_waits_for_a_background_load() -> None:
    loader = BlockingLoader()
    engine = ParakeetStt(loader=loader)
    with pytest.raises(SttError):
        engine.transcribe(utterance())
    assert loader.started.wait(5)
    threading.Timer(0.05, loader.release.set).start()
    engine.warmup()  # blocks until the background load finishes, then has nothing to do
    assert engine.loaded
    assert len(loader.rec.calls) == 1


def test_parakeet_load_failure_raises_and_backs_off() -> None:
    loader = CountingLoader(failures=1)
    engine = ParakeetStt(loader=loader, retry_after_s=60.0)
    with pytest.raises(SttError, match="unavailable"):
        engine.warmup()
    assert engine.last_error is not None and "OSError" in engine.last_error
    with pytest.raises(SttError, match=r"unavailable.*OSError"):
        engine.transcribe(utterance())
    with pytest.raises(SttError, match="unavailable"):
        engine.warmup()
    assert len(loader.calls) == 1  # within the back-off window: no second load attempt, not even in background
    assert not engine.loading
    # a silent clip still answers "" without touching the broken model
    assert engine.transcribe(clip_of(silence(2.0, 16_000), 16_000)).text == ""


def test_parakeet_retries_load_after_backoff() -> None:
    loader = CountingLoader(failures=1)
    engine = ParakeetStt(loader=loader, retry_after_s=0.0)
    with pytest.raises(SttError):
        engine.warmup()
    engine.warmup()
    assert engine.loaded
    assert engine.last_error is None
    assert len(loader.calls) == 2


def test_parakeet_recovers_in_background_after_failed_startup_warmup() -> None:
    # Started offline: the hub's single warm-up failed. A press after the back-off retries in the background.
    loader = CountingLoader(failures=1)
    engine = ParakeetStt(loader=loader, retry_after_s=0.0)
    with pytest.raises(SttError):
        engine.warmup()
    with pytest.raises(SttError, match="still loading"):
        engine.transcribe(utterance())
    wait_until(lambda: engine.loaded)
    assert engine.last_error is None
    assert engine.transcribe(utterance()).text == "Where should I be braking for turn two?"


def test_parakeet_background_load_failure_is_recorded_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    loader = CountingLoader(failures=10)
    engine = ParakeetStt(loader=loader, retry_after_s=60.0)
    with caplog.at_level(logging.WARNING, logger="pitwall.voice.stt"):
        with pytest.raises(SttError, match="still loading"):
            engine.transcribe(utterance())
        wait_until(lambda: engine.last_error is not None and not engine.loading)
    assert "failed to load" in caplog.text
    with pytest.raises(SttError, match="unavailable"):
        engine.transcribe(utterance())
    assert len(loader.calls) == 1


def test_parakeet_warmup_inference_failure_counts_as_load_failure() -> None:
    rec = FakeRecognizer()
    rec.fail = RuntimeError("metal: kernel compile failed")
    engine = ParakeetStt(loader=CountingLoader(rec), retry_after_s=60.0)
    with pytest.raises(SttError, match="kernel compile failed"):
        engine.warmup()
    assert not engine.loaded  # never published half-ready


def test_parakeet_inference_error_is_wrapped() -> None:
    rec = FakeRecognizer()
    engine = warm(ParakeetStt(loader=CountingLoader(rec)))
    rec.fail = RuntimeError("metal: out of memory")
    with pytest.raises(SttError, match="out of memory"):
        engine.transcribe(utterance())


@pytest.mark.parametrize("heard", ["Uh", " Uh. ", "Um...", "Hmm?", "uh, um", "Mm-hmm", "Erm.", "Ah!", "...", "?"])
@pytest.mark.parametrize("postprocess", [True, False])
def test_parakeet_filler_only_transcript_is_nothing_understood(heard: str, postprocess: bool) -> None:
    # real Parakeet on 4 s of white noise at about -30 dBFS (which passes the gate) produced "Uh"
    engine = warm(ParakeetStt(loader=CountingLoader(FakeRecognizer(heard)), postprocess=postprocess))
    assert engine.transcribe(utterance()).text == ""


@pytest.mark.parametrize("heard", ["Uh, how are my tyres?", "Thank you.", "Okay.", "Hmm, fuel?"])
def test_parakeet_keeps_real_words_next_to_fillers(heard: str) -> None:
    engine = warm(ParakeetStt(loader=CountingLoader(FakeRecognizer(heard))))
    assert engine.transcribe(utterance()).text == heard


def test_parakeet_serialises_concurrent_transcriptions() -> None:
    rec = FakeRecognizer()
    rec.delay_s = 0.02
    engine = warm(ParakeetStt(loader=CountingLoader(rec)))
    results: list[str] = []
    threads = [threading.Thread(target=lambda: results.append(engine.transcribe(utterance()).text)) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 6
    assert rec.max_active == 1


def test_parakeet_satisfies_protocol() -> None:
    engines: list[SttEngine] = [ParakeetStt(loader=CountingLoader()), WhisperCppStt(), NullStt()]
    assert [e.name for e in engines] == ["parakeet", "whispercpp", "none"]


# ---------------------------------------------------------------------------------------------- WhisperCppStt
def _multipart_fields(request: httpx.Request) -> dict[str, bytes]:
    raw = request.read()
    head = f"Content-Type: {request.headers['content-type']}\r\n\r\n".encode()
    msg = email.parser.BytesParser().parsebytes(head + raw)
    out: dict[str, bytes] = {}
    for part in msg.get_payload():
        assert isinstance(part, email.message.Message)
        name = part.get_param("name", header="content-disposition")
        payload = part.get_payload(decode=True)
        assert isinstance(name, str) and isinstance(payload, bytes)
        out[name] = payload
    return out


def _whisper(handler: Callable[[httpx.Request], httpx.Response], url: str = "http://127.0.0.1:8178") -> WhisperCppStt:
    return WhisperCppStt(url, client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_whispercpp_posts_16k_wav_with_prompt_and_cleans_text() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"text": " [BLANK_AUDIO] Where should I be breaking for turn one?\n"})

    engine = _whisper(handler, url="http://127.0.0.1:8178/inference/")
    res = engine.transcribe(utterance(rate=48_000), prompt="La Source, Eau Rouge, Turn 1")
    assert res.text == "Where should I be braking for turn one?"
    assert res.engine == "whispercpp"
    (req,) = seen
    assert req.method == "POST"
    assert str(req.url) == "http://127.0.0.1:8178/inference"
    fields = _multipart_fields(req)
    assert fields["prompt"] == b"La Source, Eau Rouge, Turn 1"
    assert fields["response_format"] == b"json"
    with wave.open(io.BytesIO(fields["file"])) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 16_000)
        assert w.getnframes() == pytest.approx(1.6 * 16_000, abs=0.03 * 16_000)  # trimmed + resampled


def test_whispercpp_uses_default_vocabulary_prompt() -> None:
    prompts: list[bytes] = []

    def handler(req: httpx.Request) -> httpx.Response:
        prompts.append(_multipart_fields(req)["prompt"])
        return httpx.Response(200, json={"text": "How are my tyres?"})

    assert _whisper(handler).transcribe(utterance()).text == "How are my tyres?"
    assert prompts == [DEFAULT_WHISPER_PROMPT.encode()]


def test_whispercpp_silent_clip_makes_no_request() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise AssertionError("whisper-server must not be called for silence")

    res = _whisper(handler).transcribe(clip_of(silence(3.0, 16_000), 16_000))
    assert res.text == ""


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="internal error"),
        httpx.Response(200, json={"error": "failed to read WAV file"}),
        httpx.Response(200, text="not json"),
    ],
)
def test_whispercpp_server_errors_raise(response: httpx.Response) -> None:
    with pytest.raises(SttError):
        _whisper(lambda req: response).transcribe(utterance())


def test_whispercpp_unreachable_server_raises() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=req)

    engine = _whisper(handler)
    with pytest.raises(SttError, match="request failed"):
        engine.transcribe(utterance())
    with pytest.raises(SttError, match="not reachable"):
        engine.warmup()


@pytest.mark.parametrize(
    "text",
    [" [BLANK_AUDIO]\n (engine revving) ", " Thank you.", "Thanks for watching!", " you", "[MUSIC] Um.", " Uh..."],
)
def test_whispercpp_non_speech_reply_is_empty(text: str) -> None:
    res = _whisper(lambda req: httpx.Response(200, json={"text": text})).transcribe(utterance())
    assert res.text == ""


def test_whispercpp_keeps_questions_that_contain_phantom_words() -> None:
    res = _whisper(lambda req: httpx.Response(200, json={"text": " Thank you. How are my tyres?"})).transcribe(
        utterance()
    )
    assert res.text == "Thank you. How are my tyres?"


# ---------------------------------------------------------------------------------------------- NullStt
def test_null_stt() -> None:
    engine = NullStt()
    engine.warmup()
    res = engine.transcribe(utterance())
    assert (res.text, res.engine, res.latency_ms) == ("", "none", 0)
    assert res.audio_s == pytest.approx(3.0)


# ---------------------------------------------------------------------------------------------- factory
def _settings(tmp_path: Path, **kw: str) -> Settings:
    return Settings(data_dir=tmp_path, **kw)  # type: ignore[arg-type]


@pytest.mark.parametrize("engine", ["none", "off", ""])
def test_build_stt_disabled(tmp_path: Path, engine: str) -> None:
    assert isinstance(build_stt(_settings(tmp_path, stt_engine=engine)), NullStt)


def test_build_stt_whispercpp(tmp_path: Path) -> None:
    engine = build_stt(_settings(tmp_path, stt_engine="whispercpp", whispercpp_url="http://10.0.0.5:9000/"))
    assert isinstance(engine, WhisperCppStt)
    assert engine.inference_url == "http://10.0.0.5:9000/inference"


def test_build_stt_unknown_engine_falls_back_with_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="pitwall.voice.stt"):
        engine = build_stt(_settings(tmp_path, stt_engine="sphinx"))
    assert isinstance(engine, NullStt)
    assert "sphinx" in caplog.text


def test_build_stt_parakeet_unavailable_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import pitwall.voice.stt_sherpa as sherpa_mod

    monkeypatch.setattr(stt_mod, "_parakeet_supported", lambda: "parakeet-mlx not importable (ImportError)")
    # off Apple silicon the factory falls back to sherpa-onnx (installed on Windows): not here
    monkeypatch.setattr(sherpa_mod, "sherpa_supported", lambda: "sherpa-onnx not importable (ImportError)")
    with caplog.at_level(logging.WARNING, logger="pitwall.voice.stt"):
        engine = build_stt(_settings(tmp_path, stt_engine="parakeet"))
    assert isinstance(engine, NullStt)
    assert "not importable" in caplog.text


def test_build_stt_on_windows_is_null_with_a_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Parakeet-mlx is Apple silicon only; on Windows without sherpa-onnx (lane handsfree: the voice extra installs it
    there) the radio says why voice questions are off."""
    import pitwall.voice.stt_sherpa as sherpa_mod

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sherpa_mod, "sherpa_supported", lambda: "sherpa-onnx not importable (ImportError)")
    with caplog.at_level(logging.WARNING, logger="pitwall.voice.stt"):
        engine = build_stt(_settings(tmp_path, stt_engine="parakeet"))
    assert isinstance(engine, NullStt) and "sherpa-onnx" in engine.reason and "not installed" in engine.reason
    assert "whispercpp" in caplog.text  # the log says what would work instead
    assert isinstance(build_stt(_settings(tmp_path, stt_engine="whispercpp")), WhisperCppStt)  # still available
    monkeypatch.setattr(sys, "platform", "linux")  # elsewhere: Apple silicon or sherpa-onnx
    assert "Apple-silicon Mac" in build_stt(_settings(tmp_path, stt_engine="parakeet")).reason  # type: ignore[attr-defined]


def test_null_stt_reasons(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert "switched off" in build_stt(_settings(tmp_path, stt_engine="none")).reason  # type: ignore[attr-defined]
    assert "sphinx" in build_stt(_settings(tmp_path, stt_engine="sphinx")).reason  # type: ignore[attr-defined]
    monkeypatch.setattr(stt_mod, "_parakeet_supported", lambda: None)
    monkeypatch.setattr(stt_mod, "ParakeetStt", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert "failed to start" in build_stt(_settings(tmp_path, stt_engine="parakeet")).reason  # type: ignore[attr-defined]


def test_build_stt_parakeet_missing_package_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "parakeet_mlx", None)  # import raises ImportError
    monkeypatch.setitem(sys.modules, "sherpa_onnx", None)  # no CPU fallback either (Windows has it)
    assert isinstance(build_stt(_settings(tmp_path, stt_engine="parakeet")), NullStt)


def test_build_stt_parakeet_is_lazy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stt_mod, "_parakeet_supported", lambda: None)
    engine = build_stt(_settings(tmp_path, stt_engine="Parakeet", stt_model="mlx-community/other-model"))
    assert isinstance(engine, ParakeetStt)
    assert engine.model_id == "mlx-community/other-model"
    assert not engine.loaded


def test_build_stt_never_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("constructor exploded")

    monkeypatch.setattr(stt_mod, "_parakeet_supported", lambda: None)
    monkeypatch.setattr(stt_mod, "ParakeetStt", boom)
    assert isinstance(build_stt(_settings(tmp_path, stt_engine="parakeet")), NullStt)


# ---------------------------------------------------------------------------------------------- corrections
@pytest.mark.parametrize(
    ("heard", "fixed"),
    [
        # brake / break
        ("Where should I be breaking for turn one?", "Where should I be braking for turn one?"),
        ("where do I break for turn 7", "where do I brake for turn 7"),
        ("Break bias forward two clicks.", "Brake bias forward two clicks."),
        ("Break bars forward two clicks.", "Brake bias forward two clicks."),
        ("move the break balance", "move the brake balance"),
        ("I'm breaking too late into turn 3", "I'm braking too late into turn 3"),
        ("break later for the hairpin", "brake later for the hairpin"),
        ("trail breaking into the chicane", "trail braking into the chicane"),
        ("how are my front breaks", "how are my front brakes"),
        ("breaking point for T3", "braking point for T3"),
        ("BREAK BIAS", "BRAKE BIAS"),
        ("where do I break for 7?", "where do I brake for 7?"),
        # real Parakeet output for braking questions (macOS `say`, default voice and Daniel)
        ("Is my breaking consistent?", "Is my braking consistent?"),
        ("How was my breaking that lap?", "How was my braking that lap?"),
        ("Is my breaking okay in sector two?", "Is my braking okay in sector two?"),
        ("Am I breaking consistently?", "Am I braking consistently?"),
        ("Am I breaking okay?", "Am I braking okay?"),
        ("Am I breaking hard enough?", "Am I braking hard enough?"),
        ("Give me breaking feedback.", "Give me braking feedback."),
        ("How was my breaking into turn three?", "How was my braking into turn three?"),
        ("Breaking into turn one. How was it?", "Braking into turn one. How was it?"),
        ("What about my break temperatures?", "What about my brake temperatures?"),
        ("Break earlier for turn four.", "Brake earlier for turn four."),
        # corner numbers
        ("Where should I be braking for turn to?", "Where should I be braking for turn two?"),
        ("I'm losing time at turn for.", "I'm losing time at turn four."),
        ("into turn too entry", "into turn two entry"),
        ("through turn won and three", "through turn one and three"),
        ("Turn to. What went wrong?", "Turn two. What went wrong?"),
        ("Turn for.", "Turn four."),
        ("OK, turn won, how was that?", "OK, turn one, how was that?"),
        # fuel
        ("What's my fool situation?", "What's my fuel situation?"),
        ("What's my few situation?", "What's my fuel situation?"),
        ("how much fool have I got", "how much fuel have I got"),
        ("full remaining?", "fuel remaining?"),
        # lap
        ("Compare that lab to my best.", "Compare that lap to my best."),
        ("Stop talking for a few lapse.", "Stop talking for a few laps."),
        ("Stop talking for a couple of lapse.", "Stop talking for a couple of laps."),
        ("Be quiet for a couple labs", "Be quiet for a couple laps"),
        ("what was my lab time", "what was my lap time"),
        # one fix supplies the context for another
        ("fool per lab time", "fuel per lap time"),
        ("3 few per lab time", "3 fuel per lap time"),
        # whitespace
        ("  How are   my tyres? \n", "How are my tyres?"),
    ],
)
def test_correct_racing_terms_fixes(heard: str, fixed: str) -> None:
    assert correct_racing_terms(heard) == fixed


@pytest.mark.parametrize(
    "text",
    [
        "How are my tyres?",
        "How are my tires?",
        "Can I take a break later?",
        "Give me a break.",
        "I need a break for a lap",
        "Give me a break for 3 laps",
        "I need a break for 5 minutes",
        "Take a break at 10",
        "Take a short break later",
        "I'll have a quick break later",
        "Can I take my break later?",
        "You're breaking up.",
        "Your breaking up",
        "Am I breaking up?",
        "I'm breaking traction on exit.",
        "Any breaking news?",
        "I want to turn to the left",
        "Turn to me when you're ready",
        "Then turn to the right",
        "Give me the full situation",
        "full left lock in the hairpin",
        "a few remaining laps",
        "just a few left",
        "Stop talking for a few laps.",
        "a momentary lapse in concentration",
        "How does the car feel?",
        "Where am I losing the most time?",
        "",
    ],
)
def test_correct_racing_terms_leaves_real_words_alone(text: str) -> None:
    assert correct_racing_terms(text) == " ".join(text.split())


@pytest.mark.parametrize(
    "heard",
    [
        "Where should I be breaking for turn to?",
        "What's my fool situation, and break bias?",
        "trail breaking at turn for, then compare that lab",
        "fool per lab time",
    ],
)
def test_correct_racing_terms_is_idempotent(heard: str) -> None:
    once = correct_racing_terms(heard)
    assert correct_racing_terms(once) == once


def _rule_vocabulary() -> list[str]:
    words: set[str] = set()
    for rule in stt_mod._RULES:
        words |= set(re.findall(r"[a-z]{2,}", re.sub(r"\?P<\w+>", "", rule.pattern.pattern)))
        words |= set(rule.mapping) | set(rule.mapping.values())
    return [*sorted(words), "a", "I", "the", "3", "7", "T3", ".", ",", "?", "-", "Break", "TURN", "bıos", "breakſ"]


def test_correct_racing_terms_is_idempotent_and_total_on_fuzzed_vocabulary() -> None:
    # random sentences built from every word the rules look at, plus Unicode look-alikes
    vocab = _rule_vocabulary()
    rng = random.Random(1234)
    for _ in range(5_000):
        heard = " ".join(rng.choice(vocab) for _ in range(rng.randint(1, 8)))
        once = correct_racing_terms(heard)
        assert correct_racing_terms(once) == once, heard


def test_correct_racing_terms_is_idempotent_on_every_short_chain() -> None:
    # Exhaustive over words whose fixes feed other rules' context ("fool per lab time" needs two passes).
    words: list[str] = ["fool", "few", "per", "lab", "lapse", "time", "couple", "of", "turn", "to", "into"]
    words += ["break", "my", "a", "later", "."]
    for combo in itertools.product(words, repeat=4):
        heard = " ".join(combo)
        once = correct_racing_terms(heard)
        assert correct_racing_terms(once) == once, heard


def test_no_rule_produces_a_word_another_rule_rewrites() -> None:
    # correct_racing_terms' convergence (and so its idempotence) rests on this
    sources = {k for rule in stt_mod._RULES for k in rule.mapping}
    produced = {v for rule in stt_mod._RULES for v in rule.mapping.values()}
    assert not sources & produced
    assert all(rule.pattern.flags & re.ASCII for rule in stt_mod._RULES)


@pytest.mark.parametrize("text", ["break bıos", "trail breakſ", "fooł per lab", "Turn tō."])
def test_correct_racing_terms_handles_non_ascii_lookalikes(text: str) -> None:
    # With Unicode case folding "ı" would match "i" and "ſ" would match "s", and the mapping lookup would then
    # raise KeyError. The rules are ASCII-only: no exception, and a look-alike letter is never read as its twin.
    out = correct_racing_terms(text)
    assert "bias" not in out and "brakes" not in out and "two" not in out


@pytest.mark.parametrize(
    ("heard", "intent", "corner"),
    [
        ("Where should I be breaking for turn to?", "braking", "T2"),
        ("What's my fool situation?", "fuel", None),
        ("break bias feels wrong", "setup", None),
        ("Break bars forward two clicks.", "setup", None),
        ("Is my breaking consistent?", "braking", None),
        ("How was my breaking that lap?", "braking", None),
        ("Is my breaking okay in sector two?", "braking", None),
        ("Am I breaking okay?", "braking", None),
        ("Turn to. What went wrong?", "corner", "T2"),
        ("fool per lab time", "fuel", None),
    ],
)
def test_corrections_rescue_engineer_intents(heard: str, intent: str, corner: str | None) -> None:
    fixed = detect_intent(correct_racing_terms(heard))
    assert (fixed.name, fixed.corner) == (intent, corner)
    raw = detect_intent(heard)
    assert (raw.name, raw.corner) != (intent, corner)  # the correction is what makes the difference


# ---------------------------------------------------------------------------------------------- real model
def _parakeet_cached() -> bool:
    try:
        from huggingface_hub import try_to_load_from_cache

        return isinstance(try_to_load_from_cache(DEFAULT_PARAKEET_MODEL, "model.safetensors"), str)
    except Exception:
        return False


def _real_parakeet_ready() -> bool:
    return sys.platform == "darwin" and shutil.which("say") is not None and _parakeet_cached()


def _voice_tests_requested(config: pytest.Config) -> bool:
    """Real-model tests run only when asked for: ``-m voice`` (or an expression selecting it) or the env var.

    They are not left to the default run (``make check``), which they would slow down, push into swap and
    tie to the installed ``say`` voices.
    """
    if os.environ.get("PITWALL_VOICE_TESTS") == "1":
        return True
    markexpr = str(config.getoption("markexpr", default="") or "")
    return re.search(r"(?<!not )\bvoice\b", markexpr) is not None


needs_real_parakeet = pytest.mark.skipif(
    not _real_parakeet_ready(), reason=f"needs macOS `say` and {DEFAULT_PARAKEET_MODEL} in the HF cache"
)


def _say_voice_installed(voice: str) -> bool:
    if shutil.which("say") is None:
        return False
    out = subprocess.run(
        ["say", "-v", "?"], capture_output=True, encoding="utf-8", errors="replace", check=False, timeout=30
    ).stdout
    return any(line.split()[:1] == [voice] for line in out.splitlines())


def say_clip(text: str, out_dir: Path, rate: int = 16_000, voice: str | None = None) -> AudioClip:
    path = out_dir / f"say-{abs(hash((text, rate, voice)))}.wav"
    cmd = ["say", "-o", str(path), f"--data-format=LEI16@{rate}"] + (["-v", voice] if voice else [])
    subprocess.run([*cmd, text], check=True, timeout=30)
    with wave.open(str(path)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, rate)
        return AudioClip(w.readframes(w.getnframes()), rate)


@pytest.fixture(scope="module")
def real_parakeet(request: pytest.FixtureRequest) -> Iterator[ParakeetStt]:
    # Checked here, before the model loads (module-scoped fixtures are set up before any function-scoped one).
    if not _voice_tests_requested(request.config):
        pytest.skip("real-model voice tests are opt-in: uv run pytest -m voice (or PITWALL_VOICE_TESTS=1)")
    engine = ParakeetStt()
    engine.warmup()
    yield engine


def test_voice_tests_are_opt_in(pytestconfig: pytest.Config, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PITWALL_VOICE_TESTS", raising=False)
    monkeypatch.setattr(pytestconfig.option, "markexpr", "not live and not llm")  # the default addopts
    assert not _voice_tests_requested(pytestconfig)
    monkeypatch.setattr(pytestconfig.option, "markexpr", "not voice")
    assert not _voice_tests_requested(pytestconfig)
    monkeypatch.setattr(pytestconfig.option, "markexpr", "voice")
    assert _voice_tests_requested(pytestconfig)
    monkeypatch.setattr(pytestconfig.option, "markexpr", "")
    monkeypatch.setenv("PITWALL_VOICE_TESTS", "1")
    assert _voice_tests_requested(pytestconfig)


DRIVER_QUESTIONS = [
    ("Where am I losing the most time?", ["losing", "time"], ("losing_time", None)),
    ("Give me one thing to work on.", ["one thing", "work on"], ("focus", None)),
    ("Where should I be braking for Turn 1?", ["braking", "turn"], ("braking", "T1")),
    ("Compare that lap to my best.", ["compare", "lap", "best"], ("compare", None)),
    ("How are my tyres?", ["how are my t"], ("tyres", None)),
    ("What's my fuel situation?", ["fuel"], ("fuel", None)),
    ("Stop talking for a few laps.", ["stop talking", "laps"], ("control_quiet", None)),
    ("Brake bias forward two clicks.", ["brake bias", "forward"], ("setup", None)),
    # heard as "breaking" (and "Turn to.") by Parakeet; rescued by correct_racing_terms
    ("Is my braking consistent?", ["braking", "consistent"], ("braking", None)),
    ("How was my braking that lap?", ["braking", "lap"], ("braking", None)),
    ("Is my braking OK in sector two?", ["braking", "sector"], ("braking", None)),
    ("Am I braking consistently?", ["braking"], ("braking", None)),
    ("Am I braking hard enough?", ["braking"], ("braking", None)),
    ("Turn two, what went wrong?", ["turn", "went wrong"], ("corner", "T2")),
    ("Stop talking for a couple of laps.", ["stop talking", "laps"], ("control_quiet", None)),
]

# the system default voice, and Daniel (en_GB, pitwall's TTS voice) whose accent exercises the corrections
SAY_VOICES = [
    pytest.param(None, id="default-voice"),
    pytest.param(
        "Daniel",
        id="Daniel",
        marks=pytest.mark.skipif(not _say_voice_installed("Daniel"), reason="say voice Daniel not installed"),
    ),
]


@pytest.mark.voice
@needs_real_parakeet
@pytest.mark.parametrize("voice", SAY_VOICES)
@pytest.mark.parametrize(("phrase", "keywords", "expected_intent"), DRIVER_QUESTIONS)
def test_real_parakeet_driver_questions(
    real_parakeet: ParakeetStt,
    tmp_path: Path,
    phrase: str,
    keywords: list[str],
    expected_intent: tuple[str, str | None],
    voice: str | None,
) -> None:
    clip = say_clip(phrase, tmp_path, voice=voice)
    res = real_parakeet.transcribe(clip)
    lowered = res.text.lower()
    for kw in keywords:
        assert kw in lowered, f"{kw!r} missing from transcript {res.text!r}"
    intent = detect_intent(res.text)
    assert (intent.name, intent.corner) == expected_intent, res.text
    assert res.engine == "parakeet"
    assert res.audio_s == pytest.approx(clip.duration_s)
    assert res.latency_ms < 2_000  # warm model, hot GPU: about 50 ms on an M4 Max (several times that after idle)


@pytest.mark.voice
@needs_real_parakeet
def test_real_parakeet_resamples_other_rates(real_parakeet: ParakeetStt, tmp_path: Path) -> None:
    res = real_parakeet.transcribe(say_clip("What's my fuel situation?", tmp_path, rate=22_050))
    assert "fuel" in res.text.lower()


@pytest.mark.voice
@needs_real_parakeet
def test_real_parakeet_silence_is_empty_and_fast(real_parakeet: ParakeetStt) -> None:
    res = real_parakeet.transcribe(clip_of(silence(4.0, 16_000), 16_000))
    assert res.text == ""
    assert res.latency_ms < 50
