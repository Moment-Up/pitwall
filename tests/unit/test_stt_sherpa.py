"""Parakeet on the CPU through sherpa-onnx (lane handsfree, ``voice/stt_sherpa.py``): the pinned download (size and
sha256, ``.part`` clean-up, back-off, ``HF_HUB_OFFLINE``), an offline folder, the not-ready errors, the decode path
with a fake recogniser, and the factory choosing it off Apple silicon. Nothing here downloads or loads a real model;
on Windows CI the real package must import (the ``voice`` extra installs it there)."""

from __future__ import annotations

import hashlib
import logging
import os
import platform
import sys
import threading
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pytest

import pitwall.voice.stt as stt_mod
import pitwall.voice.stt_sherpa as sherpa_mod
from pitwall.config import Settings
from pitwall.voice.stt import NullStt, ParakeetStt, SttError, build_stt
from pitwall.voice.stt_sherpa import (
    CATALOGUE,
    DEFAULT_SHERPA_MODEL,
    ModelFile,
    SherpaModel,
    SherpaParakeetStt,
    default_threads,
    missing_files,
)
from pitwall.voice.types import AudioClip

SR = 16_000
BLOBS = {"encoder": b"E" * 3000, "decoder": b"D" * 700, "joiner": b"J" * 50, "tokens": b"a 0\nb 1\n"}
NAMES = {
    "encoder": "encoder.int8.onnx",
    "decoder": "decoder.int8.onnx",
    "joiner": "joiner.int8.onnx",
    "tokens": "tokens.txt",
}


def _model(blobs: Mapping[str, bytes] = BLOBS) -> SherpaModel:
    return SherpaModel(
        key="test-model",
        repo="example/test-model",
        revision="0" * 40,
        folder="test-model",
        files=tuple(
            ModelFile(role, NAMES[role], len(data), hashlib.sha256(data).hexdigest()) for role, data in blobs.items()
        ),
        licence="test",
        language="English",
    )


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> SherpaModel:
    m = _model()
    monkeypatch.setitem(CATALOGUE, m.key, m)
    return m


class FakeFetch:
    """Serves ``BLOBS`` by URL file name in two chunks; ``corrupt`` flips a byte of that file."""

    def __init__(self, corrupt: str | None = None, oversize: str | None = None) -> None:
        self.urls: list[str] = []
        self.corrupt = corrupt
        self.oversize = oversize

    def __call__(self, url: str) -> Iterator[bytes]:
        self.urls.append(url)
        name = url.rsplit("/", 1)[1]
        role = next(r for r, n in NAMES.items() if n == name)
        data = BLOBS[role]
        if role == self.corrupt:
            data = b"X" + data[1:]
        if role == self.oversize:
            data += b"!"
        half = len(data) // 2
        yield data[:half]
        yield data[half:]


class FakeRecognizer:
    sample_rate = SR

    def __init__(self, text: str = "Is my breaking consistent?") -> None:
        self.text = text
        self.calls: list[np.ndarray] = []

    def __call__(self, audio: Any) -> str:
        self.calls.append(np.asarray(audio))
        return self.text


def tone(seconds: float, amp: int = 6000) -> AudioClip:
    t = np.arange(round(seconds * SR)) / SR
    return AudioClip((amp * np.sin(2 * np.pi * 300 * t)).astype("<i2").tobytes(), SR)


def _engine(tmp_path: Path, model: SherpaModel, **kw: Any) -> tuple[SherpaParakeetStt, FakeRecognizer, list[Any]]:
    rec = FakeRecognizer()
    loads: list[Any] = []

    def loader(paths: Mapping[str, Path], threads: int) -> FakeRecognizer:
        loads.append((dict(paths), threads))
        return rec

    kw.setdefault("fetch", FakeFetch())
    kw.setdefault("offline", False)
    engine = SherpaParakeetStt(model.key, folder=tmp_path / "stt" / model.folder, loader=loader, **kw)
    return engine, rec, loads


# ---------------------------------------------------------------------------------------------- the pins
def test_the_catalogue_pins_the_v2_int8_model() -> None:
    m = CATALOGUE[DEFAULT_SHERPA_MODEL]
    assert m.repo == "csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"
    assert m.revision == "1ab9323565ddb038682214b292f588070a538ce2"
    assert [(f.name, f.size) for f in m.files] == [
        ("encoder.int8.onnx", 652_184_296),
        ("decoder.int8.onnx", 7_257_753),
        ("joiner.int8.onnx", 1_739_080),
        ("tokens.txt", 9_384),
    ]
    assert all(len(f.sha256) == 64 for f in m.files)
    assert 660e6 < m.total_bytes < 662e6
    assert m.url(m.files[3]) == (
        "https://huggingface.co/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8/resolve/"
        "1ab9323565ddb038682214b292f588070a538ce2/tokens.txt"
    )
    assert "CC-BY-4.0" in m.licence


def test_default_threads_is_half_the_cores_between_1_and_4(monkeypatch: pytest.MonkeyPatch) -> None:
    for cores, want in ((None, 1), (1, 1), (2, 1), (6, 3), (8, 4), (32, 4)):
        monkeypatch.setattr(os, "cpu_count", lambda c=cores: c)
        assert default_threads() == want


# ---------------------------------------------------------------------------------------------- download
def test_download_verifies_and_loads_once(tmp_path: Path, model: SherpaModel) -> None:
    engine, rec, loads = _engine(tmp_path, model, threads=2)
    engine.warmup()
    folder = tmp_path / "stt" / model.folder
    assert sorted(p.name for p in folder.iterdir()) == sorted(NAMES.values())  # no .part left
    assert missing_files(folder, model) == []
    assert engine.loaded and loads[0][1] == 2 and loads[0][0]["joiner"] == folder / "joiner.int8.onnx"
    assert len(rec.calls) == 1 and rec.calls[0].size == SR // 2  # warmed with 0.5 s of noise
    assert float(np.sqrt(np.mean(rec.calls[0] ** 2))) == pytest.approx(10 ** (-70 / 20), rel=0.1)
    fetch = engine._fetch
    assert isinstance(fetch, FakeFetch) and len(fetch.urls) == 4
    assert fetch.urls[0] == f"https://huggingface.co/example/test-model/resolve/{'0' * 40}/encoder.int8.onnx"
    again, _rec, _loads = _engine(tmp_path, model)  # a later start: files present, nothing fetched
    again.warmup()
    assert isinstance(again._fetch, FakeFetch) and again._fetch.urls == []


@pytest.mark.parametrize("bad", ["corrupt", "oversize"])
def test_a_bad_download_is_refused_cleaned_up_and_backed_off(tmp_path: Path, model: SherpaModel, bad: str) -> None:
    fetch = FakeFetch(**{bad: "decoder"})
    engine, _rec, loads = _engine(tmp_path, model, fetch=fetch)
    with pytest.raises(SttError, match=r"decoder\.int8\.onnx"):
        engine.warmup()
    folder = tmp_path / "stt" / model.folder
    assert sorted(p.name for p in folder.iterdir()) == ["encoder.int8.onnx"]  # verified one kept, no .part
    assert loads == [] and not engine.loaded
    n = len(fetch.urls)
    with pytest.raises(SttError, match="unavailable"):  # backing off: no new attempt
        engine.warmup()
    assert len(fetch.urls) == n
    engine.retry_after_s = 0.0
    engine._fetch = FakeFetch()
    engine.warmup()  # the retry fetches only what is missing
    assert engine.loaded and [u.rsplit("/", 1)[1] for u in engine._fetch.urls] == [
        "decoder.int8.onnx",
        "joiner.int8.onnx",
        "tokens.txt",
    ]


def test_hf_hub_offline_never_downloads(tmp_path: Path, model: SherpaModel, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    fetch = FakeFetch()
    engine, _rec, _loads = _engine(tmp_path, model, fetch=fetch, offline=None)
    assert engine.offline
    with pytest.raises(SttError, match="PITWALL_STT_SHERPA_DIR"):
        engine.warmup()
    assert fetch.urls == []


def test_an_offline_folder_is_hashed_and_never_written(tmp_path: Path, model: SherpaModel) -> None:
    own = tmp_path / "my-model"
    own.mkdir()
    for role, data in BLOBS.items():
        (own / NAMES[role]).write_bytes(data)
    fetch = FakeFetch()
    engine, _rec, _loads = _engine(tmp_path, model, fetch=fetch)
    engine.folder, engine.managed = own, False
    engine.warmup()
    assert engine.loaded and fetch.urls == []
    (own / "tokens.txt").write_bytes(b"a 0\nc 1\n")  # same size, different bytes
    other, _r, _l = _engine(tmp_path, model, fetch=fetch)
    other.folder, other.managed = own, False
    with pytest.raises(SttError, match="not the pinned"):
        other.warmup()
    (own / "tokens.txt").unlink()
    third, _r, _l = _engine(tmp_path, model, fetch=fetch)
    third.folder, third.managed = own, False
    with pytest.raises(SttError, match="missing"):
        third.warmup()
    assert fetch.urls == []


def test_settings_choose_the_folder(tmp_path: Path) -> None:
    s = Settings(_env_file=None, data_dir=tmp_path, stt_sherpa_dir=tmp_path / "offline", stt_threads=3)  # type: ignore[call-arg]
    engine = SherpaParakeetStt.from_settings(s)
    assert engine.folder == tmp_path / "offline" and engine.managed is False and engine.threads == 3
    managed = SherpaParakeetStt.from_settings(Settings(_env_file=None, data_dir=tmp_path))  # type: ignore[call-arg]
    assert managed.managed and managed.folder.parts[-2:] == ("stt", "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8")
    with pytest.raises(ValueError, match="unknown sherpa model"):
        SherpaParakeetStt("whisper-large")


# ---------------------------------------------------------------------------------------------- transcribe
def test_not_ready_raises_at_once_and_loads_in_the_background(tmp_path: Path, model: SherpaModel) -> None:
    release = threading.Event()

    class SlowFetch(FakeFetch):
        def __call__(self, url: str) -> Iterator[bytes]:
            release.wait(5)
            yield from super().__call__(url)

    engine, _rec, _loads = _engine(tmp_path, model, fetch=SlowFetch())
    with pytest.raises(SttError, match="loading"):
        engine.transcribe(tone(1.0))
    engine._progress = (1500, 3000)
    assert "downloading (50 %)" in engine._not_ready()
    release.set()
    assert engine._background is not None
    engine._background.join(5)
    assert engine.loaded
    assert engine.transcribe(AudioClip(b"\x00\x00" * SR, SR)).text == ""  # the energy gate: no model work


def test_decoding_resamples_gates_and_corrects_racing_terms(tmp_path: Path, model: SherpaModel) -> None:
    engine, rec, _loads = _engine(tmp_path, model)
    engine.warmup()
    t = np.arange(48_000) / 48_000
    clip = AudioClip((6000 * np.sin(2 * np.pi * 300 * t)).astype("<i2").tobytes(), 48_000)
    res = engine.transcribe(clip)
    assert res.text == "Is my braking consistent?" and res.engine == "sherpa" and res.audio_s == pytest.approx(1.0)
    assert rec.calls[-1].dtype == np.float32 and 15_000 < rec.calls[-1].size <= 16_000
    rec.text = "uh"
    assert engine.transcribe(tone(1.0)).text == ""  # filler only: nothing understood
    diag = engine.diagnostics()
    assert diag["loaded"] and diag["model"] == "test-model" and diag["last_error"] is None

    class Broken(FakeRecognizer):
        def __call__(self, audio: Any) -> str:
            raise RuntimeError("onnx says no")

    engine._recognizer = Broken()
    with pytest.raises(SttError, match="decoding failed"):
        engine.transcribe(tone(1.0))


# ---------------------------------------------------------------------------------------------- factory
def _settings(tmp_path: Path, **kw: Any) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path, **kw)  # type: ignore[call-arg]


def test_parakeet_off_apple_silicon_resolves_to_sherpa(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sherpa_mod, "sherpa_supported", lambda: None)
    engine = build_stt(_settings(tmp_path, stt_engine="parakeet", stt_sherpa_dir=tmp_path / "m"))
    assert isinstance(engine, SherpaParakeetStt) and engine.name == "sherpa" and not engine.loaded
    assert engine.folder == tmp_path / "m"  # nothing downloaded or loaded by the factory
    assert isinstance(build_stt(_settings(tmp_path, stt_engine="sherpa")), SherpaParakeetStt)
    bad = build_stt(_settings(tmp_path, stt_engine="sherpa", stt_sherpa_model="nope"))
    assert isinstance(bad, NullStt) and "unknown sherpa model" in bad.reason


def test_apple_silicon_keeps_parakeet_mlx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    monkeypatch.setattr(stt_mod, "_parakeet_supported", lambda: None)
    monkeypatch.setattr(sherpa_mod, "sherpa_supported", lambda: None)  # even with sherpa-onnx installed
    assert isinstance(build_stt(_settings(tmp_path, stt_engine="parakeet")), ParakeetStt)


def test_sherpa_requested_but_not_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(sherpa_mod, "sherpa_supported", lambda: "sherpa-onnx not importable (ImportError)")
    with caplog.at_level(logging.WARNING, logger="pitwall.voice.stt"):
        engine = build_stt(_settings(tmp_path, stt_engine="sherpa"))
    assert isinstance(engine, NullStt) and "sherpa-onnx" in engine.reason
    assert "not importable" in caplog.text


# ---------------------------------------------------------------------------------------------- the real package
@pytest.mark.skipif(sys.platform != "win32", reason="the voice extra installs sherpa-onnx on Windows only")
def test_windows_has_sherpa_onnx_installed() -> None:
    """A7: ``uv sync --all-extras --locked`` on Windows CI installs sherpa-onnx and its core (ONNX Runtime)."""
    import sherpa_onnx

    assert callable(sherpa_onnx.OfflineRecognizer.from_transducer)
    assert sherpa_mod.sherpa_supported() is None
