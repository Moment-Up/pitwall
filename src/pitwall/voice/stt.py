"""Speech-to-text engines for the driver radio (implementations of ``voice.types.SttEngine``).

Engines
-------
* ``ParakeetStt``: NVIDIA Parakeet-TDT through ``parakeet-mlx`` (MLX on the Metal GPU, in process). The model
  loads in ``warmup()``, which blocks and is meant for a worker thread; the radio hub calls it when a device
  connects. ``transcribe()`` never waits for a load (a first-run download is 2.5 GB). If the model is not
  ready it raises ``SttError`` at once, so the driver gets an error instead of silence, and starts a
  background load unless a recent failure is still backing off. That background retry is also how the engine
  recovers when the start-up warm-up failed, for example offline. A separate lock serialises inference, so
  only one thread runs MLX at a time. MLX 0.32 lets a model loaded on one thread be used from another.
  Push-to-talk utterances are transcribed in one pass with no streaming. Parakeet has no vocabulary biasing,
  so ``prompt`` is ignored and ``correct_racing_terms`` does that job instead.
* ``WhisperCppStt``: a whisper.cpp ``whisper-server`` sidecar over HTTP (``POST /inference`` with a WAV
  file). ``prompt`` carries vocabulary such as corner names. The server is a separate process, so a crash
  there cannot take down the app.
* ``NullStt``: always returns "". Used when speech recognition is disabled or unavailable (e.g. Parakeet off an
  Apple-silicon Mac, so on Windows unless ``stt_engine=whispercpp``), so the radio still accepts typed questions.
  Its ``reason`` says why; the radio hub tells the driver instead of asking them to repeat themselves.

Shared behaviour
----------------
* Input is ``AudioClip`` int16 PCM at any rate. Engines convert it to float32 in [-1, 1) and resample to the
  model rate with a polyphase filter.
* An energy gate (``EnergyGate``) runs before any model work. A clip that is too short, or has too little
  voiced audio, returns ``text == ""`` in well under a millisecond. Clips that pass are trimmed to the voiced
  span plus generous padding. The gate is deliberately lenient. Its job is to drop empty and accidental PTT
  presses cheaply, not to act as a VAD, because a false reject would lose a real question.
* What the gate lets through can still be noise. A transcript made only of fillers ("uh", "um", "hmm") or
  punctuation becomes "": real Parakeet turned 4 s of -30 dBFS white noise into "Uh". ``WhisperCppStt`` also
  drops whisper's well-known near-silence hallucinations ("Thank you.", "Thanks for watching").
* ``text == ""`` always means "nothing understood". Engine failures raise ``SttError``, such as a model that
  is still loading or cannot load, or a sidecar that is down. The radio hub turns that into an error frame for
  the device, not "say again?".
* Transcripts pass through ``correct_racing_terms``. This is a small, deterministic and idempotent fixer for
  mis-hearings that matter to the engineer's intent rules. Examples: Parakeet hears "braking" as "breaking"
  in most questions with every ``say`` voice tried ("Is my breaking consistent?"), hears the British voice's
  "brake bias" as "break bars", and its "Turn two, what went wrong?" as "Turn to. What went wrong?".
* Memory: Parakeet 0.6B uses about 1.3 GB of MLX memory at bf16. By default the engine caps MLX's
  process-wide buffer cache at 256 MB; uncapped, it adds about 0.8 to 1 GB of footprint after the first
  utterance.
* ``latency_ms`` covers the whole ``transcribe`` call: conversion, gate, resample and inference. ``audio_s``
  is the duration of the clip as received. Measured with ``scripts/bench_stt.py`` on the M4 Max (2 s
  questions, Qwen and a second Parakeet loaded, swap nearly full): about 70 ms median with the GPU hot
  (back-to-back calls), but radio questions come seconds or minutes apart. After 10 s idle the median was
  84 ms (61 to 283 ms); after 30 s it was 230 ms (62 ms to 1.7 s), as the process's pages had been
  compressed or swapped out. Under memory pressure the tail is paging, not inference.
"""

from __future__ import annotations

import importlib
import io
import logging
import math
import platform
import re
import sys
import threading
import time
import wave
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

import httpx
import numpy as np
import numpy.typing as npt

from pitwall.voice.types import AudioClip, SttEngine, SttResult

if TYPE_CHECKING:
    from pitwall.config import Settings

log = logging.getLogger(__name__)

DEFAULT_PARAKEET_MODEL = "mlx-community/parakeet-tdt-0.6b-v3"
DEFAULT_WHISPERCPP_URL = "http://127.0.0.1:8178"
# whisper.cpp weights the most recent prompt tokens most heavily, so callers append track corners last.
DEFAULT_WHISPER_PROMPT = (
    "Race engineer radio. Turn 1, Turn 2, apex, braking point, brake bias, tyres, fuel, lap time, delta, "
    "sector, front wing, understeer, oversteer."
)

Float32Array = npt.NDArray[np.float32]


class SttError(RuntimeError):
    """The speech engine could not run (model loading or unavailable, sidecar down, bad response)."""


# ---------------------------------------------------------------------------------------------- audio utils
def pcm16_to_float32(pcm: bytes) -> Float32Array:
    """int16 little-endian mono PCM -> float32 in [-1, 1). A trailing odd byte (torn frame) is dropped."""
    n = len(pcm) // 2
    ints = np.frombuffer(pcm, dtype="<i2", count=n)
    return (ints.astype(np.float32) / np.float32(32768.0)).astype(np.float32, copy=False)


def float32_to_pcm16(samples: Float32Array) -> bytes:
    """float32 [-1, 1] -> int16 little-endian PCM, clipping out-of-range values."""
    scaled = np.clip(np.rint(samples * 32768.0), -32768, 32767)
    return scaled.astype("<i2").tobytes()


def resample(samples: Float32Array, src_rate: int, dst_rate: int) -> Float32Array:
    """Band-limited polyphase resampling (e.g. 48 kHz or 44.1 kHz -> 16 kHz). Identity when rates match."""
    if src_rate <= 0 or dst_rate <= 0:
        raise ValueError(f"invalid sample rates {src_rate} -> {dst_rate}")
    if src_rate == dst_rate or samples.size == 0:
        return samples
    from scipy.signal import resample_poly

    g = math.gcd(src_rate, dst_rate)
    out = resample_poly(samples, dst_rate // g, src_rate // g)
    return np.asarray(out, dtype=np.float32)


def encode_wav(samples: Float32Array, sample_rate: int) -> bytes:
    """Mono 16-bit WAV file bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(float32_to_pcm16(samples))
    return buf.getvalue()


@dataclass(slots=True, frozen=True)
class EnergyGate:
    """Cheap pre-model check: is there enough voiced audio to be worth transcribing?

    Per-frame energy is the standard deviation, not the raw RMS, so a DC offset from a cheap mic does not
    read as speech. A frame counts as voiced above ``threshold_dbfs``. Defaults sit well below normal speech
    (about -35 to -15 dBFS) and above digital silence or a quiet room.
    """

    min_clip_s: float = 0.2  # shorter presses are accidental taps
    min_voiced_s: float = 0.15  # total voiced audio required (about one short syllable)
    threshold_dbfs: float = -50.0
    frame_s: float = 0.02
    pad_s: float = 0.3  # kept around the voiced span when trimming (soft onsets and tails)

    def speech_span(self, samples: Float32Array, sample_rate: int) -> tuple[int, int] | None:
        """``(start, end)`` sample indices of the voiced region plus padding, or ``None`` to skip the clip."""
        if sample_rate <= 0:
            raise ValueError(f"invalid sample rate {sample_rate}")
        if samples.size < self.min_clip_s * sample_rate:
            return None
        frame = max(1, round(self.frame_s * sample_rate))
        n_frames = samples.size // frame
        if n_frames == 0:
            return None
        frames = samples[: n_frames * frame].reshape(n_frames, frame)
        level = frames.std(axis=1)
        threshold = 10.0 ** (self.threshold_dbfs / 20.0)
        voiced = np.flatnonzero(level > threshold)
        if voiced.size * frame < self.min_voiced_s * sample_rate:
            return None
        pad = round(self.pad_s * sample_rate)
        start = max(0, int(voiced[0]) * frame - pad)
        end = min(samples.size, (int(voiced[-1]) + 1) * frame + pad)
        return start, end


def _elapsed_ms(t0: float) -> int:
    return round((time.perf_counter() - t0) * 1000)


# ------------------------------------------------------------------------------------- racing corrections
def _cased(replacement: str, original: str) -> str:
    if len(original) > 1 and original.isupper():
        return replacement.upper()
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _rx(pattern: str) -> re.Pattern[str]:
    # ASCII matching: with Unicode case folding, "ı" would match "i" and "ſ" would match "s", and the matched
    # word would then be missing from the rule's mapping.
    return re.compile(pattern, re.I | re.ASCII)


@dataclass(slots=True, frozen=True)
class _Rule:
    """Rewrite the target word of each match, leaving its context intact.

    The target is the named group ``w``. Patterns with alternatives use ``w2``, ``w3`` and so on, one per
    branch. Its lower-cased text is looked up in ``mapping``, and the original capitalisation is kept.
    ``unless_after`` vetoes a match when it matches the text just before it (it should end with ``$``); this
    stands in for the variable-width look-behind that ``re`` lacks.
    """

    name: str
    pattern: re.Pattern[str]
    mapping: Mapping[str, str]
    unless_after: re.Pattern[str] | None = None

    def apply(self, text: str) -> str:
        targets = [g for g in self.pattern.groupindex if g.startswith("w")]

        def sub(m: re.Match[str]) -> str:
            if self.unless_after is not None and self.unless_after.search(m.string, 0, m.start()):
                return m.group(0)
            for g in targets:
                word = m.group(g)
                if word is not None:
                    replacement = self.mapping.get(word.lower())
                    if replacement is None:
                        return m.group(0)
                    ws, we = m.span(g)
                    ms, me = m.span()
                    return m.string[ms:ws] + _cased(replacement, word) + m.string[we:me]
            return m.group(0)

        return self.pattern.sub(sub, text)


_BRAKE = {"break": "brake", "breaks": "brakes", "breaking": "braking"}
_BREAK_W = r"(?P<w>break(?:s|ing)?)"
_BREAKING_W = r"(?P<w>breaking)"
# A bare number counts as a corner only at the end of a clause: "brake for 7?" but not "a break for 3 laps".
_CORNER_OBJECT = (
    r"(?:(?:turns?|corners?|t\s?\d{1,2}|the\s+(?:hairpin|chicane|corner|apex|kink|bend|bus\s*stop|"
    r"(?:first|second|third|last|next|final)\s+(?:corner|turn|chicane|hairpin|bend|kink)))\b"
    r"|\d{1,2}(?=\s*(?:[.,;:!?]|$)))"
)
# "Take a short break later", "give me a break for 3 laps": a determiner, optionally with a typical
# rest-break modifier, right before "break" makes it the noun.
_DETERMINER_BEFORE = _rx(
    r"\b(?:a|an|the|any|my|your|our|some)\s+(?:(?:short|quick|little|small|long|proper|good|nice|real|big|brief|"
    r"wee|coffee|lunch|tea|toilet|loo|bathroom|drinks?|water|[a-z]+-minute)\s+){0,2}$"
)
_FUEL = {"fool": "fuel", "feul": "fuel", "fule": "fuel", "few": "fuel", "full": "fuel"}
_CORNER_NUM = {"to": "two", "too": "two", "for": "four", "fore": "four", "won": "one", "ate": "eight"}
_CORNER_NUM_W = r"(?P<w>to|too|for|fore|won|ate)"
_LAP = {"lab": "lap", "labs": "laps", "lapse": "laps"}

# Order matters only for speed: ``correct_racing_terms`` repeats the pass until nothing changes. Rules whose
# output is context for others come first ("per lab" -> "per lap" before the fuel rules, "braking" before
# "turn to braking").
_RULES: tuple[_Rule, ...] = (
    # --- lap heard as lab / lapse
    _Rule(
        "lap",
        _rx(
            r"\b(?:that|this|last|my|best|next|fastest|previous|quickest|out|in|per|each|every)\s+(?P<w>lab)\b"
            r"|\b(?P<w2>lab)(?=\s+(?:times?|delta|record)\b)"
            r"|\b(?:few|couple(?:\s+of)?|several|\d+|two|three|four|five|six|seven|eight|nine|ten)\s+"
            r"(?P<w3>labs|lapse)\b"
        ),
        _LAP,
    ),
    # "brake bias" in a British accent comes out as "break bars"; no racing phrase uses "brake bars".
    _Rule("brake_bias", _rx(r"\b(?:brake|break)\s+(?P<w>bars|bios)\b"), {"bars": "bias", "bios": "bias"}),
    # --- brake vs break. "break" is rewritten only where the context makes the braking sense unambiguous, so
    # "take a break", "give me a break for 3 laps" and "you're breaking up" are never touched.
    _Rule(
        "brake_component",
        _rx(
            r"\b" + _BREAK_W + r"(?=[\s-]+(?:points?|zones?|bias|balance|pressures?|pedal|markers?|boards?|"
            r"temps?|temperatures?|wear|fade|ducts?|discs?|disks?|lock(?:ing|ups?|-ups?)?|migration|release|"
            r"application|trace|phase|distance|feedback|technique|performance|consistency)\b)"
        ),
        _BRAKE,
    ),
    _Rule(
        "brake_timing",
        _rx(
            r"\b" + _BREAK_W + r"(?=\s+(?:earlier|later|harder|hard|sooner|deeper|"
            r"too\s+(?:early|late|soon|hard|much)|a\s+(?:bit|little|touch)\s+(?:earlier|later|harder))\b)"
        ),
        _BRAKE,
        unless_after=_DETERMINER_BEFORE,
    ),
    _Rule(
        "brake_modifier",
        _rx(
            r"\b(?:trail|threshold|front|rear|hard|harder|heavy|heavier|late|later|early|earlier)[\s-]+"
            + _BREAKING_W
            + r"\b"
        ),
        _BRAKE,
    ),
    _Rule("brake_modifier_noun", _rx(r"\b(?:trail|threshold|front|rear)[\s-]+(?P<w>breaks?)\b"), _BRAKE),
    _Rule(
        "brake_for_corner",
        _rx(r"\b" + _BREAK_W + r"(?=\s+(?:for|into|before|at|in|on|through|approaching)\s+" + _CORNER_OBJECT + ")"),
        _BRAKE,
        unless_after=_DETERMINER_BEFORE,
    ),
    _Rule(
        "brake_question",
        _rx(
            r"\b(?:where|when|how\s+(?:late|early|hard))\s+(?:(?:should|do|can|could|did|must|would|shall)\s+"
            r"(?:i|we)|am\s+i|are\s+we)\s+(?:be\s+)?" + _BREAK_W + r"\b"
        ),
        _BRAKE,
    ),
    # "Is my breaking consistent?", "How was my breaking that lap?". "Your breaking up" (a common spelling
    # of "you're breaking up") is left alone.
    _Rule(
        "brake_possessive",
        _rx(
            r"\b(?:my|your|our|the|his|her|their)\s+"
            + _BREAKING_W
            + r"\b(?!\s+(?:up|away|off|out|down|loose|free|news)\b)"
        ),
        _BRAKE,
    ),
    # "Am I breaking consistently?", "Am I breaking okay?": verdict words that only follow the braking sense.
    _Rule(
        "brake_quality",
        _rx(
            r"\b" + _BREAKING_W + r"(?=\s+(?:consistent(?:ly)?|ok|okay|alright|all\s+right|better|worse|well|smoothly|"
            r"enough|properly|correctly)\b)"
        ),
        _BRAKE,
    ),
    # --- corner numbers heard as function words: only after a corner preposition AND followed by the end of
    # the clause or a corner word, so "turn to the left" is left alone.
    _Rule(
        "corner_number",
        _rx(
            r"\b(?:for|at|into|in|through|on|before|after|approaching|exiting|entering|from|of|towards?|exit|"
            r"entry|apex)\s+turn\s+" + _CORNER_NUM_W + r"(?=\s*(?:[.,;:!?]|$)|\s+(?:entry|exit|apex|braking|brake|"
            r"and|or|is|was|please|then)\b)"
        ),
        _CORNER_NUM,
    ),
    # A clause that is only "Turn to." ("Turn two, what went wrong?" in a British accent).
    _Rule(
        "corner_number_clause",
        _rx(r"(?:^|(?<=[.!?;:,] ))turn\s+" + _CORNER_NUM_W + r"(?=\s*(?:[.,;:!?]|$))"),
        _CORNER_NUM,
    ),
    # --- fuel homophones, each limited to contexts where the real word could not appear ("a few remaining
    # laps", "the full situation" and "full left lock" stay).
    _Rule(
        "fuel_strong",
        _rx(
            r"\b(?P<w>fool|feul|fule)(?=\s+(?:situation|levels?|remaining|left|usage|use|consumption|status|"
            r"target|delta|sav(?:e|ing)|burn|state|load|mix|mode|per\s+lap)\b)"
        ),
        _FUEL,
    ),
    _Rule(
        "fuel_strong_object",
        _rx(r"\b(?:how\s+much|my|save|saving|enough|low\s+on|out\s+of)\s+(?P<w>fool|feul|fule)\b"),
        _FUEL,
    ),
    _Rule(
        "fuel_few",
        _rx(
            r"\b(?P<w>few)(?=\s+(?:situation|levels?|usage|consumption|status|target|delta|burn|per\s+lap)\b)"
            r"|\bhow\s+much\s+(?P<w2>few)\b"
        ),
        _FUEL,
    ),
    _Rule("fuel_full", _rx(r"\b(?P<w>full)(?=\s+(?:levels?|remaining|usage|consumption|burn|per\s+lap)\b)"), _FUEL),
)

# Every rule replaces a word from its mapping's keys with a word that is no rule's key, so each pass that
# changes the text removes at least one rewritable word and the loop converges, normally in one or two passes.
# The cap is only a guard against a future rule breaking that property.
_MAX_PASSES = 8

_WS_RE = re.compile(r"\s+")


def correct_racing_terms(text: str) -> str:
    """Fix common speech-recognition mis-hearings of racing vocabulary. Deterministic and idempotent.

    Conservative by design: a rule fires only when the surrounding words make the racing meaning
    unambiguous. Both "tires" and "tyres" are kept as heard (the intent rules accept either), and number
    words are not converted (the intent rules read "turn two" as T2). The rules are applied until the text
    stops changing, because one fix can supply the context for another ("fool per lab" -> "fuel per lap").
    """
    out = _WS_RE.sub(" ", text).strip()
    for _ in range(_MAX_PASSES):
        before = out
        for rule in _RULES:
            out = rule.apply(out)
        if out == before:
            break
    return out


# ---------------------------------------------------------------------------------------------- non-speech
_WORD_RE = re.compile(r"[^\W_]+(?:['\N{RIGHT SINGLE QUOTATION MARK}][^\W_]+)*")
_FILLER_RE = re.compile(r"u+h+|u+h*m+|e+r+m*|a+h+|e+h+|o+h+|h+m+|m+h?m+", re.ASCII)
# whisper's near-silence hallucinations (training-data artefacts); a driver never asks the engineer these.
_WHISPER_PHANTOMS = frozenset(
    {"thank you", "thank you very much", "thanks for watching", "thank you for watching", "you"}
)


def _words(text: str) -> list[str]:
    return [w for w in _WORD_RE.findall(text.lower()) if not _FILLER_RE.fullmatch(w)]


def _finish(raw: str, postprocess: bool, phantoms: frozenset[str] = frozenset()) -> str:
    """Final transcript: racing corrections (or just whitespace clean-up), then "" for non-speech."""
    text = correct_racing_terms(raw) if postprocess else _WS_RE.sub(" ", raw).strip()
    words = _words(text)
    if not words or " ".join(words) in phantoms:
        return ""
    return text


# ------------------------------------------------------------------------------------------------ engines
class ArrayRecognizer(Protocol):
    """A loaded speech model: float32 mono samples at ``sample_rate`` -> transcript."""

    sample_rate: int

    def __call__(self, audio: Float32Array) -> str: ...


class _MlxParakeet:
    """``parakeet-mlx`` 0.5.3 model wrapper for in-memory audio.

    ``BaseParakeet.transcribe`` only accepts file paths (decoded through ffmpeg), so this replicates its
    single-chunk path instead: ``get_logmel(float32 mx.array, preprocessor_config)`` -> ``generate(mel)[0]``.
    Weights load as bf16, the library default (about 1.3 GB of MLX memory for the 0.6B model).

    ``cache_limit_mb`` caps MLX's buffer cache. The cap is **process-wide** in MLX. Uncapped, the cache holds
    about 0.8 to 1 GB of freed buffers after every utterance. Measured on the M4 Max with
    ``scripts/bench_stt.py --idle-s 10``, a 256 MB cap cut the process footprint from 2.7 GB to 1.9 GB at no
    measurable latency cost: median 68 ms vs 74 ms uncapped back-to-back, and 84 ms vs 103 ms after 10 s idle.
    Run-to-run noise is larger than either difference. A smaller footprint also means less to page back in
    after idle on a machine short of memory. A 0 cap made inference about 2.6x slower.
    """

    def __init__(self, model_id: str, cache_limit_mb: int | None = None) -> None:
        import mlx.core as mx
        from parakeet_mlx import from_pretrained
        from parakeet_mlx.audio import get_logmel

        if cache_limit_mb is not None:
            mx.set_cache_limit(cache_limit_mb * 1024 * 1024)
        self._mx: Any = mx
        self._get_logmel: Any = get_logmel
        self._model: Any = from_pretrained(model_id)
        mx.eval(self._model.parameters())  # materialise now, not lazily inside the first utterance
        mx.clear_cache()  # drop the freed fp32 buffers from the fp32 -> bf16 cast
        self.sample_rate = int(self._model.preprocessor_config.sample_rate)

    def __call__(self, audio: Float32Array) -> str:
        mel = self._get_logmel(self._mx.array(audio), self._model.preprocessor_config)
        result = self._model.generate(mel)[0]
        return str(result.text)


class ParakeetStt:
    """Parakeet-TDT via parakeet-mlx. Thread-safe: one inference at a time, and ``transcribe`` never waits
    for a model load (see the module docstring).

    ``mlx_cache_limit_mb`` sets MLX's process-wide buffer-cache cap when the model loads (see
    ``_MlxParakeet``). Pass ``None`` to leave MLX's default. ``loader`` replaces the model, for tests.
    ``retry_after_s`` is the back-off after a failed load, during which no new load is attempted.
    """

    name = "parakeet"

    def __init__(
        self,
        model_id: str = DEFAULT_PARAKEET_MODEL,
        *,
        gate: EnergyGate | None = None,
        postprocess: bool = True,
        loader: Callable[[str], ArrayRecognizer] | None = None,
        retry_after_s: float = 30.0,
        mlx_cache_limit_mb: int | None = 256,
    ) -> None:
        self.model_id = model_id
        self.gate = gate or EnergyGate()
        self.postprocess = postprocess
        self.retry_after_s = retry_after_s
        self._loader = loader or (lambda model: _MlxParakeet(model, cache_limit_mb=mlx_cache_limit_mb))
        self._load_lock = threading.Lock()  # held for a whole load + warm-up inference
        self._infer_lock = threading.Lock()  # serialises inference; never held while loading
        self._recognizer: ArrayRecognizer | None = None  # published only once loaded AND warmed
        self._load_error: str | None = None
        self._load_failed_mono = 0.0
        self._background: threading.Thread | None = None
        self.load_s: float | None = None
        self.warm_s: float | None = None

    @property
    def loaded(self) -> bool:
        """The model is loaded, warmed and ready for ``transcribe``."""
        return self._recognizer is not None

    @property
    def loading(self) -> bool:
        return self._load_lock.locked()

    @property
    def last_error(self) -> str | None:
        return self._load_error

    def warmup(self) -> None:
        """Load the model and run one tiny inference so Metal kernels are compiled before the first question.

        Blocks, including through a first-run download, and waits for a load already in progress. Without
        the warm-up inference the first real utterance pays roughly 1.3 s of kernel compilation. Raises
        ``SttError`` if the model cannot load, or straight away while a recent failure is backing off.
        """
        with self._load_lock:
            self._load_locked()

    def transcribe(self, clip: AudioClip, prompt: str | None = None) -> SttResult:
        # ``prompt`` is accepted for interface compatibility; parakeet-mlx has no vocabulary biasing.
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
                raise SttError(f"parakeet inference failed: {type(e).__name__}: {e}") from e
        return SttResult(_finish(raw, self.postprocess), self.name, _elapsed_ms(t0), clip.duration_s)

    def _backing_off(self) -> bool:
        return self._load_error is not None and time.monotonic() - self._load_failed_mono < self.retry_after_s

    def _unavailable(self) -> str:
        return f"parakeet model {self.model_id} unavailable: {self._load_error}"

    def _not_ready(self) -> str:
        """Why ``transcribe`` cannot run yet, starting a background load if one is due."""
        if not self._load_lock.locked():
            if self._backing_off():
                return self._unavailable()
            bg = self._background
            if bg is None or not bg.is_alive():
                bg = threading.Thread(target=self._background_load, name="parakeet-load", daemon=True)
                self._background = bg
                bg.start()
        return f"speech model {self.model_id} is still loading; try again in a moment"

    def _background_load(self) -> None:
        if not self._load_lock.acquire(blocking=False):
            return  # warmup() or another background load got there first
        try:
            self._load_locked()
        except SttError:
            pass  # logged, and kept in ``last_error`` for the next caller
        finally:
            self._load_lock.release()

    def _load_locked(self) -> None:
        if self._recognizer is not None:
            return
        if self._backing_off():
            # Don't hammer the HF hub or disk on every press after a failure.
            raise SttError(self._unavailable())
        t0 = time.perf_counter()
        try:
            rec = self._loader(self.model_id)
            t1 = time.perf_counter()
            rng = np.random.default_rng(0)
            rec((rng.standard_normal(rec.sample_rate // 2) * 1e-3).astype(np.float32))
        except Exception as e:
            self._load_error = f"{type(e).__name__}: {e}"
            self._load_failed_mono = time.monotonic()
            log.warning("parakeet model %s failed to load: %s", self.model_id, self._load_error)
            raise SttError(self._unavailable()) from e
        self.load_s = t1 - t0
        self.warm_s = time.perf_counter() - t1
        self._load_error = None
        self._recognizer = rec
        log.info(
            "parakeet model %s loaded in %.1f s + %.1f s warm-up (%d Hz)",
            self.model_id,
            self.load_s,
            self.warm_s,
            rec.sample_rate,
        )


_NON_SPEECH_RE = re.compile(r"\[[^\]]*\]|\([^)]*\)|\*[^*]*\*")


class WhisperCppStt:
    """whisper.cpp ``whisper-server`` sidecar, for example started with
    ``whisper-server --host 127.0.0.1 --port 8178 -m ggml-small.en-q5_1.bin``.
    """

    name = "whispercpp"
    sample_rate = 16_000  # whisper's native rate; resampling here keeps the server's decode trivial

    def __init__(
        self,
        url: str = DEFAULT_WHISPERCPP_URL,
        *,
        timeout_s: float = 15.0,
        default_prompt: str | None = DEFAULT_WHISPER_PROMPT,
        language: str | None = None,
        gate: EnergyGate | None = None,
        postprocess: bool = True,
        client: httpx.Client | None = None,
    ) -> None:
        base = url.rstrip("/")
        self.base_url = base.removesuffix("/inference")
        self.inference_url = self.base_url + "/inference"
        self.default_prompt = default_prompt
        self.language = language
        self.gate = gate or EnergyGate()
        self.postprocess = postprocess
        self._client = client or httpx.Client(timeout=timeout_s)

    def warmup(self) -> None:
        """Check the sidecar is reachable. The server loads its model at start-up, so there is nothing else
        to warm up.
        """
        try:
            self._client.get(self.base_url + "/", timeout=3.0)
        except httpx.HTTPError as e:
            raise SttError(f"whisper-server not reachable at {self.base_url}: {e}") from e

    def transcribe(self, clip: AudioClip, prompt: str | None = None) -> SttResult:
        t0 = time.perf_counter()
        samples = pcm16_to_float32(clip.pcm)
        span = self.gate.speech_span(samples, clip.sample_rate)
        if span is None:
            return SttResult("", self.name, _elapsed_ms(t0), clip.duration_s)
        audio = resample(samples[span[0] : span[1]], clip.sample_rate, self.sample_rate)
        data: dict[str, str] = {"response_format": "json", "temperature": "0.0"}
        vocab = prompt if prompt is not None else self.default_prompt
        if vocab:
            data["prompt"] = vocab
        if self.language:
            data["language"] = self.language
        files = {"file": ("utterance.wav", encode_wav(audio, self.sample_rate), "audio/wav")}
        try:
            resp = self._client.post(self.inference_url, data=data, files=files)
            resp.raise_for_status()
            body = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise SttError(f"whisper-server request failed: {e}") from e
        if not isinstance(body, dict) or "text" not in body:
            detail = body.get("error") if isinstance(body, dict) else body
            raise SttError(f"whisper-server returned no text: {detail!r}")
        raw = _NON_SPEECH_RE.sub(" ", str(body["text"]))  # [BLANK_AUDIO], (engine revving), *music*
        text = _finish(raw, self.postprocess, _WHISPER_PHANTOMS)
        return SttResult(text, self.name, _elapsed_ms(t0), clip.duration_s)

    def close(self) -> None:
        self._client.close()


class NullStt:
    """No speech recognition: every utterance is "nothing understood" (typed questions still work).

    ``reason`` (for the radio and diagnostics) says why there is no engine."""

    name = "none"

    def __init__(self, reason: str = "speech recognition is off") -> None:
        self.reason = reason

    def warmup(self) -> None:
        return None

    def transcribe(self, clip: AudioClip, prompt: str | None = None) -> SttResult:
        return SttResult("", self.name, 0, clip.duration_s)


# ------------------------------------------------------------------------------------------------ factory
def _parakeet_supported() -> str | None:
    """``None`` if parakeet-mlx can run here, else the reason it cannot."""
    if sys.platform != "darwin" or platform.machine() != "arm64":
        return (
            f"parakeet-mlx needs macOS on Apple Silicon (this is {sys.platform}/{platform.machine()}); "
            "set PITWALL_STT_ENGINE=whispercpp to use a whisper.cpp server instead"
        )
    try:
        importlib.import_module("mlx.core")
        importlib.import_module("parakeet_mlx")
    except Exception as e:  # ImportError, or a broken native extension
        return f"parakeet-mlx not importable ({type(e).__name__}: {e}); install with `uv sync --extra voice`"
    return None


def build_stt(settings: Settings) -> SttEngine:
    """The configured engine (``settings.stt_engine``), or ``NullStt`` with a warning if it cannot be used.

    Never raises and never loads a model. The model loads in ``warmup()``, which the radio hub calls on a
    worker thread.
    """
    engine = settings.stt_engine.strip().lower()
    try:
        if engine in ("none", "off", "null", "disabled", ""):
            log.info("speech recognition disabled (stt_engine=%r)", settings.stt_engine)
            return NullStt("speech recognition is switched off on the server")
        if engine == "parakeet":
            reason = _parakeet_supported()
            if reason is not None:
                log.warning("STT engine 'parakeet' unavailable, voice questions disabled: %s", reason)
                if sys.platform != "darwin" or platform.machine() != "arm64":
                    return NullStt("server speech recognition (Parakeet) needs an Apple-silicon Mac")
                return NullStt("the server's speech recognition (Parakeet) is not installed")
            return ParakeetStt(settings.stt_model or DEFAULT_PARAKEET_MODEL)
        if engine in ("whispercpp", "whisper.cpp", "whisper-cpp", "whisper"):
            return WhisperCppStt(settings.whispercpp_url or DEFAULT_WHISPERCPP_URL)
        log.warning("unknown stt_engine %r (expected parakeet | whispercpp | none); voice questions disabled", engine)
        return NullStt(f"unknown speech recognition engine {settings.stt_engine!r}")
    except Exception:
        log.exception("STT engine %r failed to initialise; voice questions disabled", engine)
    return NullStt("the server's speech recognition failed to start")


__all__ = [
    "DEFAULT_PARAKEET_MODEL",
    "DEFAULT_WHISPERCPP_URL",
    "DEFAULT_WHISPER_PROMPT",
    "ArrayRecognizer",
    "EnergyGate",
    "NullStt",
    "ParakeetStt",
    "SttError",
    "WhisperCppStt",
    "build_stt",
    "correct_racing_terms",
    "encode_wav",
    "float32_to_pcm16",
    "pcm16_to_float32",
    "resample",
]
