"""Parakeet speech recognition on the CPU through sherpa-onnx: the server's speech engine off Apple silicon (Windows).

Lane handsfree, docs/research/handsfree.md section 2. ``parakeet-mlx`` (``voice.stt.ParakeetStt``) needs Apple's MLX,
so on a Windows PC spoken questions used to be off unless the driver ran a whisper.cpp server. sherpa-onnx 1.13.8
(Apache-2.0) is a self-contained wheel (``sherpa-onnx`` plus ``sherpa-onnx-core``, about 16 MB on win_amd64, ONNX
Runtime bundled, no other dependencies), installed by the ``voice`` extra on Windows only. It runs NVIDIA's Parakeet
TDT 0.6B **v2** (English, CC-BY-4.0) converted to int8 ONNX by the sherpa-onnx project.

* **Model.** The four files are pinned by repository revision, size and sha256 (``CATALOGUE``). Chosen over the v3
  (multilingual) int8 model on measured synthetic recall of the wake word "Pitwall": 0.88 vs 0.53 (macOS ``say``
  voices, docs/research/handsfree.md section 3.3). ``Settings.stt_model`` (an MLX model id) does not apply here;
  ``stt_sherpa_model`` is a catalogue key, so the server never downloads an arbitrary model.
* **Download** (about 661 MB, once). ``warmup()`` (a worker thread: the hub calls it when a radio connects) streams
  each missing file from ``https://huggingface.co/{repo}/resolve/{revision}/{file}`` to ``<file>.part`` with a running
  sha256, checks size and hash, then moves it into ``<app support>/stt/<folder>``. A file only lands in that folder
  verified, so later starts check sizes only. ``HF_HUB_OFFLINE=1`` skips the download (with a reason);
  ``PITWALL_STT_SHERPA_DIR`` points at a folder already holding the four files (an offline install: its files are
  hashed once per start, never downloaded or changed). A failure backs off ``retry_after_s`` (30 s) like Parakeet.
* **Before it is ready** ``transcribe()`` raises ``SttError`` at once ("speech model downloading (42 %)", or loading)
  and starts a background load, so the driver sees why instead of hearing "Say again?".
* **Decoding.** One recogniser, built once and warmed with 0.5 s of -70 dBFS noise; decoding is serialised with a
  lock. Input and output follow ``voice.stt``: the same ``EnergyGate``, resampling to 16 kHz, ``_finish`` (filler-only
  transcripts become "") and the racing-term corrections.
* **Measured** (synthetic, M4 Max CPU, docs/research/handsfree.md): load 0.8 s, median 69 ms (4 threads) / about
  105 ms (2 threads) per ~2.9 s clip, max RSS about 1.9 GB. Never run on a Windows PC yet: expect 2-4x slower there.
"""

from __future__ import annotations

import hashlib
import importlib
import logging
import os
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from pitwall.compat import app_support_dir, replace_file
from pitwall.voice.stt import ArrayRecognizer, EnergyGate, SttError, _finish, pcm16_to_float32, resample
from pitwall.voice.types import AudioClip, SttResult

if TYPE_CHECKING:
    from pitwall.config import Settings

log = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
DEFAULT_SHERPA_MODEL = "parakeet-tdt-0.6b-v2-int8"
WARM_NOISE_DBFS = -70.0
CHUNK_BYTES = 1 << 20


@dataclass(frozen=True, slots=True)
class ModelFile:
    role: str  # encoder | decoder | joiner | tokens
    name: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class SherpaModel:
    key: str
    repo: str  # Hugging Face repository
    revision: str  # pinned commit
    folder: str  # under <app support>/stt/
    files: tuple[ModelFile, ...]
    licence: str
    language: str

    def url(self, f: ModelFile) -> str:
        return f"https://huggingface.co/{self.repo}/resolve/{self.revision}/{f.name}"

    @property
    def total_bytes(self) -> int:
        return sum(f.size for f in self.files)


# Pins checked against the repository's file hashes and the downloaded files (docs/research/handsfree.md section 2).
CATALOGUE: dict[str, SherpaModel] = {
    DEFAULT_SHERPA_MODEL: SherpaModel(
        key=DEFAULT_SHERPA_MODEL,
        repo="csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8",
        revision="1ab9323565ddb038682214b292f588070a538ce2",
        folder="sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8",
        files=(
            ModelFile(
                "encoder",
                "encoder.int8.onnx",
                652_184_296,
                "a32b12d17bbbc309d0686fbbcc2987b5e9b8333a7da83fa6b089f0a2acd651ab",
            ),
            ModelFile(
                "decoder",
                "decoder.int8.onnx",
                7_257_753,
                "b6bb64963457237b900e496ee9994b59294526439fbcc1fecf705b31a15c6b4e",
            ),
            ModelFile(
                "joiner",
                "joiner.int8.onnx",
                1_739_080,
                "7946164367946e7f9f29a122407c3252b680dbae9a51343eb2488d057c3c43d2",
            ),
            ModelFile(
                "tokens",
                "tokens.txt",
                9_384,
                "ec182b70dd42113aff6c5372c75cac58c952443eb22322f57bbd7f53977d497d",
            ),
        ),
        licence="CC-BY-4.0 (NVIDIA parakeet-tdt-0.6b-v2)",
        language="English",
    ),
}

Fetch = Callable[[str], Iterator[bytes]]  # url -> body chunks; raises on an HTTP error
Loader = Callable[[Mapping[str, Path], int], ArrayRecognizer]  # role -> path, threads -> recogniser


# ---------------------------------------------------------------------------------------------- helpers
def default_threads() -> int:
    """``PITWALL_STT_THREADS=0``: half the logical cores, 1-4 [heuristic: the M4 Max decoded a 2.9 s clip in 69 ms
    with 4 threads and about 105 ms with 2; more threads mostly take CPU from the game on a PC]."""
    return max(1, min(4, (os.cpu_count() or 2) // 2))


def hf_offline() -> bool:
    """``HF_HUB_OFFLINE`` is set (Hugging Face's own switch): never download."""
    return os.environ.get("HF_HUB_OFFLINE", "").strip().lower() in ("1", "true", "yes", "on")


def managed_dir(model: SherpaModel) -> Path:
    """Where the server downloads ``model``: ``<app support>/stt/<folder>`` (``%LOCALAPPDATA%\\pitwall`` on Windows)."""
    return app_support_dir() / "stt" / model.folder


def model_folder(settings: Settings) -> tuple[Path, bool]:
    """``(folder, managed)``: ``PITWALL_STT_SHERPA_DIR`` (an offline install, never written) or the managed folder."""
    model = CATALOGUE.get(settings.stt_sherpa_model.strip().lower()) or CATALOGUE[DEFAULT_SHERPA_MODEL]
    if settings.stt_sherpa_dir is not None:
        return Path(settings.stt_sherpa_dir), False
    return managed_dir(model), True


def missing_files(folder: Path, model: SherpaModel) -> list[ModelFile]:
    """Files not present with their pinned size (a cheap check: no hashing)."""
    out: list[ModelFile] = []
    for f in model.files:
        p = folder / f.name
        try:
            ok = p.is_file() and p.stat().st_size == f.size
        except OSError:
            ok = False
        if not ok:
            out.append(f)
    return out


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK_BYTES):
            h.update(chunk)
    return h.hexdigest()


def sherpa_supported() -> str | None:
    """``None`` if sherpa-onnx can be imported here, else why not."""
    try:
        importlib.import_module("sherpa_onnx")
    except Exception as e:  # ImportError, or a native library that will not load
        return f"sherpa-onnx not importable ({type(e).__name__}: {e}); install with `uv sync --all-extras`"
    return None


def _http_fetch(url: str) -> Iterator[bytes]:
    import httpx

    timeout = httpx.Timeout(30.0, read=120.0)
    with httpx.Client(follow_redirects=True, timeout=timeout) as client, client.stream("GET", url) as r:
        r.raise_for_status()
        yield from r.iter_bytes(CHUNK_BYTES)


class _SherpaRecognizer:
    """A loaded sherpa-onnx offline transducer (``ArrayRecognizer``): float32 mono 16 kHz -> text."""

    sample_rate = SAMPLE_RATE

    def __init__(self, rec: Any) -> None:
        self._rec = rec

    def __call__(self, audio: Any) -> str:
        stream = self._rec.create_stream()
        stream.accept_waveform(self.sample_rate, audio)
        self._rec.decode_stream(stream)
        return str(stream.result.text)


def _sherpa_loader(paths: Mapping[str, Path], threads: int) -> ArrayRecognizer:
    import sherpa_onnx

    rec = sherpa_onnx.OfflineRecognizer.from_transducer(
        str(paths["encoder"]),
        str(paths["decoder"]),
        str(paths["joiner"]),
        str(paths["tokens"]),
        num_threads=threads,
        decoding_method="greedy_search",
        model_type="nemo_transducer",
        provider="cpu",
    )
    return _SherpaRecognizer(rec)


# ---------------------------------------------------------------------------------------------- engine
class SherpaParakeetStt:
    """Parakeet TDT 0.6B v2 (English, int8) through sherpa-onnx on the CPU. Thread-safe: one decode at a time, and
    ``transcribe`` never waits for a download or load (see the module docstring)."""

    name = "sherpa"

    def __init__(
        self,
        model: str = DEFAULT_SHERPA_MODEL,
        *,
        folder: Path | None = None,
        managed: bool = True,
        threads: int = 0,
        gate: EnergyGate | None = None,
        postprocess: bool = True,
        fetch: Fetch | None = None,
        loader: Loader | None = None,
        retry_after_s: float = 30.0,
        offline: bool | None = None,
    ) -> None:
        spec = CATALOGUE.get(model.strip().lower())
        if spec is None:
            raise ValueError(f"unknown sherpa model {model!r} (known: {', '.join(CATALOGUE)})")
        self.model = spec
        self.folder = folder if folder is not None else managed_dir(spec)
        self.managed = managed  # False: the driver's own folder (PITWALL_STT_SHERPA_DIR): verify, never download
        self.threads = threads if threads > 0 else default_threads()
        self.gate = gate or EnergyGate()
        self.postprocess = postprocess
        self.retry_after_s = retry_after_s
        self._offline = offline
        self._fetch: Fetch = fetch or _http_fetch
        self._loader: Loader = loader or _sherpa_loader
        self._load_lock = threading.Lock()
        self._infer_lock = threading.Lock()
        self._recognizer: ArrayRecognizer | None = None
        self._load_error: str | None = None
        self._load_failed_mono = 0.0
        self._background: threading.Thread | None = None
        self._progress: tuple[int, int] | None = None  # (bytes done, bytes to fetch) while downloading
        self.load_s: float | None = None
        self.warm_s: float | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> SherpaParakeetStt:
        folder, managed = model_folder(settings)
        return cls(settings.stt_sherpa_model, folder=folder, managed=managed, threads=settings.stt_threads)

    # ------------------------------------------------------------------ status
    @property
    def loaded(self) -> bool:
        return self._recognizer is not None

    @property
    def loading(self) -> bool:
        return self._load_lock.locked()

    @property
    def last_error(self) -> str | None:
        return self._load_error

    @property
    def offline(self) -> bool:
        return hf_offline() if self._offline is None else self._offline

    def download_percent(self) -> int | None:
        p = self._progress
        if p is None or p[1] <= 0:
            return None
        return min(100, int(100 * p[0] / p[1]))

    def diagnostics(self) -> dict[str, Any]:
        return {
            "engine": self.name,
            "model": self.model.key,
            "folder": str(self.folder),
            "managed": self.managed,
            "threads": self.threads,
            "loaded": self.loaded,
            "loading": self.loading,
            "download_percent": self.download_percent(),
            "last_error": self._load_error,
            "load_s": self.load_s,
            "warm_s": self.warm_s,
        }

    # ------------------------------------------------------------------ SttEngine
    def warmup(self) -> None:
        """Download (first run), load and warm the model. Blocks: call from a worker thread. Raises ``SttError``."""
        with self._load_lock:
            self._load_locked()

    def transcribe(self, clip: AudioClip, prompt: str | None = None) -> SttResult:
        # ``prompt`` is accepted for interface compatibility; this decoder takes no vocabulary hint.
        t0 = time.perf_counter()
        samples = pcm16_to_float32(clip.pcm)
        span = self.gate.speech_span(samples, clip.sample_rate)
        if span is None:
            return SttResult("", self.name, _elapsed_ms(t0), clip.duration_s)
        rec = self._recognizer
        if rec is None:
            raise SttError(self._not_ready())
        audio = resample(samples[span[0] : span[1]], clip.sample_rate, rec.sample_rate)
        with self._infer_lock:
            try:
                raw = rec(audio)
            except Exception as e:
                raise SttError(f"sherpa-onnx decoding failed: {type(e).__name__}: {e}") from e
        return SttResult(_finish(raw, self.postprocess), self.name, _elapsed_ms(t0), clip.duration_s)

    # ------------------------------------------------------------------ loading
    def _backing_off(self) -> bool:
        return self._load_error is not None and time.monotonic() - self._load_failed_mono < self.retry_after_s

    def _unavailable(self) -> str:
        return f"speech model ({self.model.key}) unavailable: {self._load_error}"

    def _not_ready(self) -> str:
        if not self._load_lock.locked():
            if self._backing_off():
                return self._unavailable()
            bg = self._background
            if bg is None or not bg.is_alive():
                bg = threading.Thread(target=self._background_load, name="sherpa-load", daemon=True)
                self._background = bg
                bg.start()
        pct = self.download_percent()
        if pct is not None:
            return f"speech model downloading ({pct} %)"
        return "speech model is loading; try again in a moment"

    def _background_load(self) -> None:
        if not self._load_lock.acquire(blocking=False):
            return
        try:
            self._load_locked()
        except SttError:
            pass  # logged, and kept in ``last_error``
        finally:
            self._load_lock.release()

    def _load_locked(self) -> None:
        if self._recognizer is not None:
            return
        if self._backing_off():
            raise SttError(self._unavailable())
        t0 = time.perf_counter()
        try:
            paths = self._ensure_files()
            t_files = time.perf_counter()
            rec = self._loader(paths, self.threads)
            t1 = time.perf_counter()
            rng = np.random.default_rng(0)
            noise = rng.standard_normal(SAMPLE_RATE // 2) * 10.0 ** (WARM_NOISE_DBFS / 20.0)
            rec(noise.astype(np.float32))
        except Exception as e:
            self._load_error = str(e) if isinstance(e, SttError) else f"{type(e).__name__}: {e}"
            self._load_failed_mono = time.monotonic()
            log.warning("sherpa speech model %s failed to load: %s", self.model.key, self._load_error)
            raise SttError(self._unavailable()) from e
        finally:
            self._progress = None
        self.load_s = t1 - t_files
        self.warm_s = time.perf_counter() - t1
        self._load_error = None
        self._recognizer = rec
        log.info(
            "sherpa speech model %s ready in %.1f s (files %.1f s, load %.1f s, warm-up %.2f s, %d threads)",
            self.model.key,
            time.perf_counter() - t0,
            t_files - t0,
            self.load_s,
            self.warm_s,
            self.threads,
        )

    def _ensure_files(self) -> dict[str, Path]:
        """The model's four files, downloaded and verified if needed. Raises ``SttError``."""
        paths = {f.role: self.folder / f.name for f in self.model.files}
        if not self.managed:
            for f in self.model.files:
                p = paths[f.role]
                if not p.is_file():
                    raise SttError(f"{p} is missing (PITWALL_STT_SHERPA_DIR must hold all four model files)")
                if p.stat().st_size != f.size or file_sha256(p) != f.sha256:
                    raise SttError(f"{p} is not the pinned {self.model.key} model file (size or sha256 differ)")
            return paths
        missing = missing_files(self.folder, self.model)
        if not missing:
            return paths
        if self.offline:
            raise SttError(
                f"the speech model is not downloaded and HF_HUB_OFFLINE is set: put its four files in a folder and "
                f"set PITWALL_STT_SHERPA_DIR to it (about {self.model.total_bytes // 1_000_000} MB)"
            )
        self.folder.mkdir(parents=True, exist_ok=True)
        total = sum(f.size for f in missing)
        self._progress = (0, total)
        log.info("downloading speech model %s (%.0f MB) to %s", self.model.key, total / 1e6, self.folder)
        done = 0
        for f in missing:
            done = self._download(f, done, total)
        return paths

    def _download(self, f: ModelFile, done: int, total: int) -> int:
        """Stream one file to ``.part`` with a running sha256; move it into place only when size and hash match."""
        part = self.folder / (f.name + ".part")
        h = hashlib.sha256()
        n = 0
        try:
            with part.open("wb") as out:
                for chunk in self._fetch(self.model.url(f)):
                    n += len(chunk)
                    if n > f.size:
                        raise SttError(f"{f.name}: the download is larger than the pinned {f.size} bytes")
                    out.write(chunk)
                    h.update(chunk)
                    self._progress = (done + n, total)
            if n != f.size:
                raise SttError(f"{f.name}: downloaded {n} bytes, expected {f.size}")
            if h.hexdigest() != f.sha256:
                raise SttError(f"{f.name}: sha256 does not match the pinned model (download refused)")
            replace_file(part, self.folder / f.name)
        except SttError:
            raise
        except Exception as e:
            raise SttError(f"{f.name}: download failed ({type(e).__name__}: {e})") from e
        finally:
            part.unlink(missing_ok=True)
        return done + n


def _elapsed_ms(t0: float) -> int:
    return round((time.perf_counter() - t0) * 1000)


def build_sherpa(settings: Settings) -> SherpaParakeetStt | str:
    """The engine for ``settings``, or the reason it cannot be used (never raises, never downloads)."""
    why = sherpa_supported()
    if why is not None:
        return why
    key = settings.stt_sherpa_model.strip().lower()
    if key not in CATALOGUE:
        return f"unknown sherpa model {settings.stt_sherpa_model!r} (known: {', '.join(CATALOGUE)})"
    return SherpaParakeetStt.from_settings(settings)


__all__ = [
    "CATALOGUE",
    "DEFAULT_SHERPA_MODEL",
    "ModelFile",
    "SherpaModel",
    "SherpaParakeetStt",
    "build_sherpa",
    "default_threads",
    "file_sha256",
    "hf_offline",
    "managed_dir",
    "missing_files",
    "model_folder",
    "sherpa_supported",
]
