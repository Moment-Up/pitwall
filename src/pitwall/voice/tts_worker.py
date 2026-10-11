"""Stand-alone TTS worker: Kokoro-82M on Metal (mlx-audio) behind a pipe. Never imports ``pitwall``.

Run it with the dedicated worker venv's interpreter, always with ``-I`` (isolated: the script's own directory is
then *not* put on ``sys.path``, so ``voice/types.py`` beside it cannot shadow the standard library)::

    ~/Library/Application Support/pitwall/tts-venv/bin/python -I tts_worker.py \\
        --model mlx-community/Kokoro-82M-bf16 --revision <sha> --voice bm_fable --lexicon lexicon.json

Why a separate process (docs/research/tts-evaluation.md section 6.1): engine dependencies (mlx, spaCy,
transformers) stay out of pitwall's environment; a crash, Metal OOM or hang only costs the worker, which the
parent kills and restarts; memory is reclaimed by restarting it; MLX state stays on this process's main thread.

**GPL-free.** misaki's G2P runs with ``fallback=None`` (no espeak), plus pitwall's lexicon for the racing names
misaki does not know (without it they are silently dropped). mlx-audio's ``KokoroPipeline`` constructor always
imports ``misaki.espeak`` (phonemizer + espeakng-loader, both GPL-3.0), so it is bypassed: the pipeline object is
built without it. At start-up the worker refuses to run if ``phonemizer`` or ``espeakng_loader`` is imported.

Protocol (one request at a time; the parent serialises):

- **stdin**: one JSON object per line.

  - ``{"id": "r1", "text": "...", "voice": "bm_fable", "speed": 1.1}``: synthesise (``"op": "synth"`` implied).
  - ``{"op": "g2p", "id": "g1", "text": "..."}``: phonemes and dropped words only (no audio).
  - ``{"op": "ping", "id": "p1"}``: liveness + memory. ``{"op": "exit"}`` or EOF: exit.

- **stdout**: framed records, ``1 type byte + 4-byte little-endian length + payload``:

  - ``R`` ready (once, after model load and warm-up): JSON ``protocol, engine, sample_rate, voices, voice,
    load_ms, warmup_ms, rss_mb, footprint_mb, peak_mb, lexicon_words, gpl_free``. ``voice`` is the default voice in
    use: a ``--voice`` that is not installed is replaced by ``DEFAULT_VOICE`` (``voice_requested`` then says
    which was asked for) instead of failing start-up.
  - ``H`` header: JSON ``id, sample_rate, voice``. Then zero or more ``A``: int16 little-endian mono PCM (one
    per text segment, so long messages arrive progressively).
  - ``E`` end: JSON ``id, synth_ms, first_ms, n_samples, segments, carrier, dropped, gpl_loaded, rss_mb,
    footprint_mb, peak_mb, request_peak_mb`` (for ``g2p``: ``id, phonemes, dropped, gpl_loaded``). ``peak_mb`` is
    the process's lifetime peak footprint, ``request_peak_mb`` this request's. ``gpl_loaded`` lists any GPL module
    imported since start-up (always empty unless the venv changed).
  - ``X`` error: JSON ``id, error, fatal``. A non-fatal error ends that request only.

- **stderr**: human-readable log lines (the parent forwards them to pitwall's log). Library ``print`` output is
  redirected there too, so it can never corrupt the frame stream.

Text handling here is deliberately minimal: the parent (``pitwall.voice.tts_lexicon.prepare_text``) has already
spelled out numbers, folded accents and applied phrase rewrites. The worker then bounds what one Kokoro call sees:

- **Bounded calls.** A call's peak memory is linear in the audio it renders: about 0.68 GB + 0.135 GB per second
  of speech (4 s: 1.1 GB, 8.7 s: 1.9 GB, 12.7 s: 2.6 GB [measured, M4 Max, speed 1.1]), and an LLM answer can be
  one long run-on sentence. Sentences are packed into segments of at most ``MAX_SEGMENT_CHARS`` (100); a longer
  sentence is split at clause punctuation (``, ; :`` and spaced dashes), and a clause still too long between
  words (evenly, preferring a cut before "and", "but", "then"...). Each segment is synthesised and sent as its own
  ``A`` frame; ``E`` reports the request's own peak. Measured with the rules below: a 1,400-character run-on
  sentence peaks at 1.43 GB (one 446-character sentence took 2.35 GB before), the evaluation's six phrases at
  1.4-1.6 GB, 200 adversarial requests (random name-dense run-ons up to 60 words) at 2.18 GB at most (3.27 GB
  before); the footprint between requests stays ~0.7 GB.
  Kokoro pads every call with 0.2-0.7 s of silence at each end, so the inner edges are trimmed to a natural gap:
  0.3 s after a sentence, 0.15 s after a clause, 0.1 s where a clause was cut between words.
- **No short segment alone.** Kokoro picks its style by input length: a short sentence on its own is spoken
  slowly ("That's costing you three tenths." took 2.1 s alone, ~1.3 s inside its two-sentence message [measured])
  or unstably. A piece shorter than ``MIN_SEGMENT_CHARS`` (40) joins a neighbour, so a call is at most 140
  characters. A whole text shorter than ``CARRIER_BELOW_CHARS`` (20: "Box, box.", a cue part such as "turn
  four") is synthesised with ``CARRIER`` after it, and the audio is cut in the pause before the carrier (Kokoro's
  own word timings, then the quiet run between them).
  Kokoro picks its style vector by input length and is unstable on very short inputs: alone, "Box, box." came out
  as "box boxy" and "turn nine" as "turn ninth"; the carrier gives it a normal-length input and keeps the text
  away from the end of the utterance, where the artefacts were. Measured with Parakeet over the cue parts (turn
  one to twenty, "brake", "Box, box.", "Copy.") in all four picker voices: 35 of 552 renders misheard alone
  (bf_isabella's "turn nine / eleven / eighteen / nineteen" and the female "Box, box." every time), 0 of 920
  with the carrier.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import importlib
import json
import math
import os
import re
import struct
import sys
import time
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import IO, Any

PROTOCOL = 1
ENGINE = "kokoro-mlx"
SAMPLE_RATE = 24_000
GPL_MODULES = ("phonemizer", "espeakng_loader")
DEFAULT_MODEL = "mlx-community/Kokoro-82M-bf16"
DEFAULT_REVISION = "a71e4d38b236d968966a2002c4c895dbd12b1c3c"
DEFAULT_VOICE = "bm_fable"
MIN_SEGMENT_CHARS = 40  # a shorter piece is merged into a neighbour (alone it is spoken slowly, or unstably)
MAX_SEGMENT_CHARS = 100  # per Kokoro call (bounds its peak memory); longer sentences are split at clauses / words
CARRIER_BELOW_CHARS = 20  # a whole text shorter than this is said with the carrier after it
CARRIER = "Over."  # said after a short text and cut off. Vowel-initial on purpose: before "Copy that." /
#                    "Stand by." Kokoro ended "four" as "fork" / "forth"; before "Over." no part failed [measured]
CUT_SEARCH_S = 0.03  # the cut is looked for this far around Kokoro's own word timings
# Silence between two segments of one message (Kokoro pads every call with 0.2-0.7 s at each end [measured], so
# joined segments would otherwise leave a ~1 s hole): by how the earlier segment ends.
GAP_SENTENCE_S = 0.30  # . ! ?
GAP_CLAUSE_S = 0.15  # , ; : dash
GAP_WORDS_S = 0.10  # a clause cut between words (no punctuation): a breath, not a pause
EDGE_FADE_S = 0.005
QUIET_DBFS = -40.0  # a 5 ms frame below this (and 30 dB below the peak) is part of a pause
WARMUP_PHRASES = ("Radio check, loud and clear.", "Copy.")
MAX_TEXT_CHARS = 4000
HEADER = struct.Struct("<cI")
FRAME_TYPES = frozenset(b"RHAEX")
MAX_FRAME_BYTES = 64 * 1024 * 1024

_SENTENCE_END = re.compile(r"(?<=[.!?…])[\"')\]]*\s+")
_CLAUSE_END = re.compile(r"(?<=[,;:])\s+|(?<=\s[-–—])\s+")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
# a long clause is preferably cut before one of these (the next piece then starts like a clause of its own)
_JOINERS = frozenset(
    {"and", "but", "or", "so", "then", "because", "while", "which", "where", "when", "with", "as", "into"}
    | {"through", "until", "after", "before"}
)


# ------------------------------------------------------------------------------------------------ framing
def write_frame(out: IO[bytes], kind: bytes, payload: bytes) -> None:
    out.write(HEADER.pack(kind, len(payload)))
    out.write(payload)
    out.flush()


def write_json(out: IO[bytes], kind: bytes, obj: dict[str, Any]) -> None:
    write_frame(out, kind, json.dumps(obj, separators=(",", ":")).encode())


def read_exact(inp: IO[bytes], n: int) -> bytes | None:
    """Exactly ``n`` bytes, or ``None`` at EOF (a partial read at EOF is also ``None``)."""
    buf = bytearray()
    while len(buf) < n:
        chunk = inp.read(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def read_frame(inp: IO[bytes]) -> tuple[str, bytes] | None:
    """One ``(type, payload)`` record, ``None`` at EOF. Raises ``ValueError`` on a malformed header."""
    head = read_exact(inp, HEADER.size)
    if head is None:
        return None
    kind, size = HEADER.unpack(head)
    if kind[0] not in FRAME_TYPES or size > MAX_FRAME_BYTES:
        raise ValueError(f"malformed frame header {head!r}")
    payload = read_exact(inp, size)
    if payload is None:
        return None
    return kind.decode("ascii"), payload


# ------------------------------------------------------------------------------------------------ text
def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]


def split_words(clause: str, max_chars: int = MAX_SEGMENT_CHARS) -> list[str]:
    """A clause with no usable punctuation as pieces of at most ``max_chars`` cut between words: as even as possible,
    preferring a cut before a joining word ("and", "but"...) when that is not much less even. A single word longer
    than ``max_chars`` stays whole."""
    words = clause.split()
    out: list[str] = []
    while words:
        total = sum(map(len, words)) + len(words) - 1
        if total <= max_chars:
            out.append(" ".join(words))
            break
        target = total / math.ceil(total / max_chars)
        best_i, best_score = 1, math.inf  # cut before words[best_i]
        length = len(words[0])  # of words[:i] joined
        for i in range(1, len(words)):
            if length > max_chars:
                break
            score = abs(length - target) - (0.25 * target if words[i].lower() in _JOINERS else 0.0)
            if score < best_score:
                best_i, best_score = i, score
            length += 1 + len(words[i])
        out.append(" ".join(words[:best_i]))
        words = words[best_i:]
    return out


def split_long(sentence: str, max_chars: int = MAX_SEGMENT_CHARS) -> list[str]:
    """A sentence longer than ``max_chars`` as clauses (cut after ``, ; :`` or a spaced dash), each clause still too
    long cut between words (``split_words``). Pieces are not packed here: ``segment_text`` does that."""
    if len(sentence) <= max_chars:
        return [sentence]
    out: list[str] = []
    for clause in _CLAUSE_END.split(sentence):
        clause = clause.strip()
        if clause:
            out.extend(split_words(clause, max_chars) if len(clause) > max_chars else [clause])
    return out


def segment_text(text: str, min_chars: int = MIN_SEGMENT_CHARS, max_chars: int = MAX_SEGMENT_CHARS) -> list[str]:
    """Synthesis segments: sentences (long ones split by ``split_long``) packed up to ``max_chars``, where no segment
    is shorter than ``min_chars`` unless the whole text is - a short piece joins the next one (the last one joins
    the previous), so a segment is at most ``max_chars + min_chars`` long."""
    text = " ".join(text.split())
    if not text:
        return []
    out: list[str] = []
    cur = ""
    for s in (piece for sentence in split_sentences(text) for piece in split_long(sentence, max_chars)):
        if not cur:
            cur = s
        elif len(cur) < min_chars or len(cur) + 1 + len(s) <= max_chars:
            cur = f"{cur} {s}"
        else:
            out.append(cur)
            cur = s
    if cur:
        if out and len(cur) < min_chars:
            out[-1] = f"{out[-1]} {cur}"
        else:
            out.append(cur)
    return out


def clean_text(text: str) -> str:
    return " ".join(_CONTROL.sub(" ", text).split())[:MAX_TEXT_CHARS]


def load_lexicon(path: Path | None) -> dict[str, str]:
    """``words`` of pitwall's lexicon file: word -> misaki phonemes. Missing file -> empty."""
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    words = data.get("words", {})
    return {str(k): str(v) for k, v in words.items() if isinstance(v, str) and v and not str(k).startswith("_")}


# ------------------------------------------------------------------------------------------------ memory
_RUSAGE_V4_FIELDS = (
    "ri_user_time", "ri_system_time", "ri_pkg_idle_wkups", "ri_interrupt_wkups", "ri_pageins", "ri_wired_size",
    "ri_resident_size", "ri_phys_footprint", "ri_proc_start_abstime", "ri_proc_exit_abstime",
    "ri_child_user_time", "ri_child_system_time", "ri_child_pkg_idle_wkups", "ri_child_interrupt_wkups",
    "ri_child_pageins", "ri_child_elapsed_abstime", "ri_diskio_bytesread", "ri_diskio_byteswritten",
    "ri_cpu_time_qos_default", "ri_cpu_time_qos_maintenance", "ri_cpu_time_qos_background",
    "ri_cpu_time_qos_utility", "ri_cpu_time_qos_legacy", "ri_cpu_time_qos_user_initiated",
    "ri_cpu_time_qos_user_interactive", "ri_billed_system_time", "ri_serviced_system_time", "ri_logical_writes",
    "ri_lifetime_max_phys_footprint", "ri_instructions", "ri_cycles", "ri_billed_energy", "ri_serviced_energy",
    "ri_interval_max_phys_footprint", "ri_runnable_time",
)  # fmt: skip


class _RUsageV4(ctypes.Structure):
    """``struct rusage_info_v4`` (macOS ``<sys/resource.h>``)."""

    _fields_ = [("ri_uuid", ctypes.c_uint8 * 16), *((n, ctypes.c_uint64) for n in _RUSAGE_V4_FIELDS)]


_libproc: Any = None


def _proc() -> Any:
    global _libproc
    if _libproc is None:
        _libproc = ctypes.CDLL("/usr/lib/libproc.dylib")
    return _libproc


def reset_request_peak() -> None:
    """Start a new interval for ``request_peak_mb`` (``proc_reset_footprint_interval``; no-op off macOS)."""
    with contextlib.suppress(OSError, AttributeError):
        _proc().proc_reset_footprint_interval(os.getpid())


def memory_mb() -> dict[str, float]:
    """Resident size, physical footprint (what Activity Monitor calls Memory; includes Metal buffers), the
    lifetime peak footprint and the peak since ``reset_request_peak`` of this process, in MB. Empty off macOS."""
    try:
        info = _RUsageV4()
        if _proc().proc_pid_rusage(os.getpid(), 4, ctypes.byref(info)) != 0:
            return {}
    except OSError:
        return {}
    mb = 1024.0 * 1024.0
    return {
        "rss_mb": round(info.ri_resident_size / mb, 1),
        "footprint_mb": round(info.ri_phys_footprint / mb, 1),
        "peak_mb": round(info.ri_lifetime_max_phys_footprint / mb, 1),
        "request_peak_mb": round(info.ri_interval_max_phys_footprint / mb, 1),
    }


def gpl_loaded() -> list[str]:
    """GPL modules imported in this process (the shipped configuration imports none)."""
    return [m for m in GPL_MODULES if m in sys.modules]


def assert_gpl_free() -> None:
    loaded = gpl_loaded()
    if loaded:
        raise RuntimeError(f"GPL modules imported in the TTS worker: {', '.join(loaded)} (misaki[en] installed?)")


def choose_voice(requested: str, installed: Iterable[str]) -> str:
    """``requested`` if it is installed, else ``DEFAULT_VOICE``, else the first British voice, else the first one.
    A typo in the settings or a stale saved choice must not keep the worker from starting."""
    have = sorted(installed)
    if requested in have:
        return requested
    british = [v for v in have if v.startswith(("bm_", "bf_"))]
    for v in (DEFAULT_VOICE, *british, *have):
        if v in have:
            return v
    raise ValueError("no voices installed")


def gap_after(segment: str) -> float:
    """Silence (s) to leave between ``segment`` and the next segment of the same message."""
    end = segment.rstrip("\"')]” ")[-1:]
    if end in (".", "!", "?", "…"):
        return GAP_SENTENCE_S
    if end in (",", ";", ":", "-", "–", "—"):
        return GAP_CLAUSE_S
    return GAP_WORDS_S


def trim_edges(x: Any, rate: int, keep_lead_s: float | None, keep_tail_s: float | None) -> Any:
    """Audio ``x`` (floats) with the silence before its first and after its last speech frame cut to ``keep_lead_s``
    / ``keep_tail_s`` (``None``: leave that end alone), with a 5 ms fade where it was cut. Speech is a 5 ms frame
    above -45 dBFS and above 40 dB below the clip's peak (as in pitwall's ``audio_post``)."""
    import numpy as np

    a = np.asarray(x, dtype=np.float32)
    frame = max(1, round(0.005 * rate))
    n = len(a) // frame
    if n == 0 or (keep_lead_s is None and keep_tail_s is None):
        return a
    rms = np.sqrt(np.mean(a[: n * frame].astype(np.float64).reshape(n, frame) ** 2, axis=1))
    peak = float(np.max(np.abs(a)))
    idx = np.flatnonzero(rms > max(10.0 ** (-45.0 / 20.0), peak * 10.0 ** (-40.0 / 20.0)))
    if idx.size == 0:
        return a
    start = 0 if keep_lead_s is None else max(0, int(idx[0]) * frame - round(keep_lead_s * rate))
    end = len(a) if keep_tail_s is None else min(len(a), (int(idx[-1]) + 1) * frame + round(keep_tail_s * rate))
    out = a[start:end].copy()
    fade = min(len(out), max(1, round(EDGE_FADE_S * rate)))
    if start > 0:
        out[:fade] *= np.linspace(0.0, 1.0, fade, dtype=np.float32)
    if end < len(a):
        out[len(out) - fade :] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)
    return out


def quiet_cut(x: Any, rate: int, word_end_s: float, next_start_s: float) -> int:
    """Where to cut audio ``x`` (floats) between a word that ends at ``word_end_s`` and the next word, starting at
    ``next_start_s`` (Kokoro's word timings, ~25 ms resolution): the middle of the longest quiet run within
    ``CUT_SEARCH_S`` of that gap, else its quietest 5 ms, else the middle of the gap. Returns a sample index."""
    import numpy as np

    n = len(x)
    frame = max(1, round(0.005 * rate))
    mid = min(n, max(0, round((word_end_s + next_start_s) / 2 * rate)))
    lo = max(0, round((word_end_s - CUT_SEARCH_S) * rate))
    hi = min(n, round((next_start_s + CUT_SEARCH_S) * rate))
    k = (hi - lo) // frame
    if k < 2:
        return mid
    a = np.asarray(x, dtype=np.float64)
    rms = np.sqrt(np.mean(a[lo : lo + k * frame].reshape(k, frame) ** 2, axis=1))
    peak = float(np.max(np.abs(a)))
    quiet = rms < max(10.0 ** (QUIET_DBFS / 20.0), peak * 10.0 ** (-30.0 / 20.0))
    best_len = best_start = 0
    run = 0
    for i, q in enumerate(quiet.tolist()):
        run = run + 1 if q else 0
        if run > best_len:
            best_len, best_start = run, i - run + 1
    if best_len:
        return lo + best_start * frame + (best_len * frame) // 2
    return lo + int(np.argmin(rms)) * frame + frame // 2


def log(msg: str) -> None:
    print(f"tts-worker[{os.getpid()}]: {msg}", file=sys.__stderr__, flush=True)


# ------------------------------------------------------------------------------------------------ engine
class KokoroEngine:
    """Kokoro-82M via mlx-audio with misaki G2P (British, no espeak) and pitwall's lexicon."""

    def __init__(
        self,
        model: str,
        revision: str | None,
        lexicon: dict[str, str],
        cache_limit_mb: float,
        g2p_only: bool = False,
    ) -> None:
        self.model_id = model
        self.revision = revision
        self.lexicon = lexicon
        self.cache_limit_mb = cache_limit_mb
        self.g2p_only = g2p_only
        self.sample_rate = SAMPLE_RATE
        self.voices: dict[str, str] = {}  # name -> .safetensors path
        self.last_carrier = False  # the last synth used the carrier (short text)
        self._g2p: Any = None
        self._pipeline: Any = None
        self._mx: Any = None
        self._np: Any = None

    def load(self) -> None:
        self._g2p = self._build_g2p()
        if self.g2p_only:
            assert_gpl_free()
            return
        self._np = importlib.import_module("numpy")
        self._mx = importlib.import_module("mlx.core")
        if self.cache_limit_mb >= 0:
            self._mx.set_cache_limit(int(self.cache_limit_mb * 1024 * 1024))
        utils = importlib.import_module("mlx_audio.tts.utils")
        kwargs: dict[str, Any] = {"revision": self.revision} if self.revision else {}
        model = utils.load_model(self.model_id, **kwargs)
        self.sample_rate = int(getattr(model, "sample_rate", SAMPLE_RATE))
        root = self._snapshot_dir()
        self.voices = {p.stem: str(p) for p in sorted((root / "voices").glob("*.safetensors"))}
        if not self.voices:
            raise RuntimeError(f"no voices under {root / 'voices'}")
        pipeline_mod = importlib.import_module("mlx_audio.tts.models.kokoro.pipeline")
        # Built without KokoroPipeline.__init__, which would import misaki.espeak (GPL) for its fallback.
        pipe = object.__new__(pipeline_mod.KokoroPipeline)
        pipe.lang_code = "b"
        pipe.repo_id = self.model_id
        pipe.model = model
        pipe.voices = {}
        pipe.g2p = self._g2p
        self._pipeline = pipe
        assert_gpl_free()

    def _snapshot_dir(self) -> Path:
        local = Path(self.model_id)
        if local.is_dir():
            return local
        hub = importlib.import_module("huggingface_hub")
        return Path(hub.snapshot_download(self.model_id, revision=self.revision, local_files_only=True))

    def _build_g2p(self) -> Any:
        en = importlib.import_module("misaki.en")
        g2p = en.G2P(trf=False, british=True, fallback=None, unk="")
        golds, silvers = g2p.lexicon.golds, g2p.lexicon.silvers
        for word, ps in self.lexicon.items():
            golds[word] = ps
            golds[word.capitalize()] = ps  # sentence-initial "de" -> "De"
            low = word.lower()
            if low not in golds and low not in silvers:  # never re-pronounce an English word ("Devote")
                golds[low] = ps
        return g2p

    def g2p(self, text: str) -> tuple[str, list[Any], list[str]]:
        """Phonemes, misaki tokens and the words G2P dropped (spoken as nothing)."""
        ps, tokens = self._g2p(text)
        dropped = [
            t.text
            for t in tokens
            if not t.phonemes and any(c.isalnum() for c in t.text) and not set(t.text) <= set("'’-")
        ]
        return ps, tokens, dropped

    def synth(self, text: str, voice: str, speed: float) -> Iterator[tuple[bytes, list[str]]]:
        """int16 LE PCM per segment (``segment_text``), with the words G2P dropped in it. A text shorter than
        ``CARRIER_BELOW_CHARS`` is said with the carrier after it, which is cut off (module docstring)."""
        path = self.voices.get(voice)
        if path is None:
            raise ValueError(f"unknown voice {voice!r} (have {', '.join(sorted(self.voices))})")
        mx = self._mx
        self.last_carrier = False
        try:
            segments = segment_text(text)
            if len(segments) == 1 and len(segments[0]) < CARRIER_BELOW_CHARS:
                short = self._synth_with_carrier(segments[0], path, speed)
                if short is not None:
                    self.last_carrier = True
                    yield short
                    return
            last = len(segments) - 1
            for k, seg in enumerate(segments):
                _ps, tokens, dropped = self.g2p(seg)
                audio = self._audio(tokens, path, speed)
                if audio is not None and last > 0:  # inner edges: a natural pause, not Kokoro's padding twice
                    lead = None if k == 0 else gap_after(segments[k - 1]) / 2
                    tail = None if k == last else gap_after(seg) / 2
                    audio = trim_edges(audio, self.sample_rate, lead, tail)
                yield self._pcm(audio), dropped
        finally:
            mx.clear_cache()

    def _audio(self, tokens: list[Any], path: str, speed: float) -> Any:
        """Float audio of one segment's tokens (``None`` if Kokoro produced none). Sets the tokens' timings."""
        np = self._np
        parts = [
            np.asarray(r.audio, dtype=np.float32).reshape(-1)
            for r in self._pipeline.generate_from_tokens(tokens, voice=path, speed=speed)
            if r.audio is not None
        ]
        return np.concatenate(parts) if parts else None

    def _pcm(self, audio: Any) -> bytes:
        if audio is None or not len(audio):
            return b""
        np = self._np
        return bytes((np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2").tobytes())

    def _synth_with_carrier(self, text: str, path: str, speed: float) -> tuple[bytes, list[str]] | None:
        """``text`` followed by ``CARRIER`` in one call, cut in the pause between them. ``None`` when the cut point
        cannot be found (the caller then synthesises ``text`` alone)."""
        spoken = text if text[-1] in ".!?…" else text.rstrip(",;:-–— ") + "."
        _ps, own, dropped = self.g2p(spoken)
        _ps2, tokens, _dropped = self.g2p(f"{spoken} {CARRIER}")
        n = len(own)
        if len(tokens) <= n or [t.text for t in tokens[:n]] != [t.text for t in own]:
            return None  # tokenised differently with the carrier: no safe boundary
        audio = self._audio(tokens, path, speed)
        if audio is None:
            return None
        words = [t for t in tokens[:n] if any(c.isalnum() for c in t.text)]
        nxt = [t for t in tokens[n:] if any(c.isalnum() for c in t.text)]
        if not words or not nxt or words[-1].end_ts is None or nxt[0].start_ts is None:
            return None
        cut = quiet_cut(audio, self.sample_rate, float(words[-1].end_ts), float(nxt[0].start_ts))
        if cut <= 0:
            return None
        return self._pcm(audio[:cut]), dropped


# ------------------------------------------------------------------------------------------------ server
def handle(engine: KokoroEngine, req: dict[str, Any], out: IO[bytes], default_voice: str, default_speed: float) -> None:
    rid = req.get("id")
    op = req.get("op", "synth")
    if op == "ping":
        write_json(out, b"E", {"id": rid, "gpl_loaded": gpl_loaded(), **memory_mb()})
        return
    text = clean_text(str(req.get("text") or ""))
    if op == "g2p":
        ps, _tokens, missing = engine.g2p(text)
        write_json(out, b"E", {"id": rid, "phonemes": ps, "dropped": missing, "gpl_loaded": gpl_loaded()})
        return
    if op != "synth":
        write_json(out, b"X", {"id": rid, "error": f"unknown op {op!r}", "fatal": False})
        return
    if engine.g2p_only:
        write_json(out, b"X", {"id": rid, "error": "worker started with --g2p-only", "fatal": False})
        return
    voice = str(req.get("voice") or default_voice)
    try:
        speed = float(req.get("speed") or default_speed)
    except (TypeError, ValueError):
        speed = default_speed
    speed = min(2.0, max(0.5, speed))
    reset_request_peak()
    t0 = time.perf_counter()
    write_json(out, b"H", {"id": rid, "sample_rate": engine.sample_rate, "voice": voice})
    n_samples, segments, first_ms = 0, 0, None
    dropped: list[str] = []
    for pcm, seg_dropped in engine.synth(text, voice, speed):
        segments += 1
        dropped.extend(seg_dropped)
        if pcm:
            if first_ms is None:
                first_ms = round((time.perf_counter() - t0) * 1000.0, 1)
            write_frame(out, b"A", pcm)
            n_samples += len(pcm) // 2
    write_json(
        out,
        b"E",
        {
            "id": rid,
            "synth_ms": round((time.perf_counter() - t0) * 1000.0, 1),
            "first_ms": first_ms,
            "n_samples": n_samples,
            "segments": segments,
            "carrier": bool(getattr(engine, "last_carrier", False)),
            "dropped": dropped,
            "gpl_loaded": gpl_loaded(),
            **memory_mb(),
        },
    )


def serve(engine: KokoroEngine, inp: IO[bytes], out: IO[bytes], voice: str, speed: float) -> int:
    for raw in inp:
        line = raw.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            if not isinstance(req, dict):
                raise ValueError("request is not a JSON object")
        except ValueError as e:
            write_json(out, b"X", {"id": None, "error": f"bad request: {e}", "fatal": False})
            continue
        if req.get("op") == "exit":
            return 0
        try:
            handle(engine, req, out, voice, speed)
        except Exception as e:  # one bad request must not kill the worker
            log(f"request {req.get('id')!r} failed: {type(e).__name__}: {e}")
            write_json(out, b"X", {"id": req.get("id"), "error": f"{type(e).__name__}: {e}", "fatal": False})
    return 0


def start(args: argparse.Namespace) -> tuple[KokoroEngine, dict[str, Any]]:
    """Load, prove GPL-free, warm up. Returns the engine and the ready record."""
    t0 = time.perf_counter()
    lexicon = load_lexicon(Path(args.lexicon) if args.lexicon else None)
    engine = KokoroEngine(args.model, args.revision, lexicon, args.cache_limit_mb, g2p_only=args.g2p_only)
    engine.load()
    load_ms = (time.perf_counter() - t0) * 1000.0
    t1 = time.perf_counter()
    requested = args.voice
    if not args.g2p_only:
        args.voice = choose_voice(requested, engine.voices)
        if args.voice != requested:
            log(f"voice {requested!r} is not installed; using {args.voice}")
        for phrase in WARMUP_PHRASES:  # spaCy, misaki and the Metal kernels pay their first-use cost here
            for _pcm, _dropped in engine.synth(phrase, args.voice, args.speed):
                pass
    else:
        engine.g2p("Radio check, loud and clear.")
    assert_gpl_free()
    ready = {
        "protocol": PROTOCOL,
        "engine": ENGINE,
        "sample_rate": engine.sample_rate,
        "voices": sorted(engine.voices),
        "voice": args.voice,
        **({"voice_requested": requested} if requested != args.voice else {}),
        "model": args.model,
        "revision": args.revision,
        "load_ms": round(load_ms, 1),
        "warmup_ms": round((time.perf_counter() - t1) * 1000.0, 1),
        "lexicon_words": len(lexicon),
        "gpl_free": True,
        "g2p_only": bool(args.g2p_only),
        "pid": os.getpid(),
        **memory_mb(),
    }
    return engine, ready


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--revision", default=DEFAULT_REVISION)
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    ap.add_argument("--speed", type=float, default=1.1)
    ap.add_argument("--lexicon", default=None)
    ap.add_argument("--cache-limit-mb", type=float, default=0.0, help="MLX buffer cache cap (-1 = MLX default)")
    ap.add_argument("--g2p-only", action="store_true", help="no model: answer g2p requests only (lexicon tests)")
    ap.add_argument("--self-test", action="store_true", help="start, synthesise one phrase, print a summary, exit")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    # Frames go to the real stdout; anything a library prints goes to stderr instead of corrupting them.
    out = os.fdopen(os.dup(1), "wb", buffering=0)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    try:
        engine, ready = start(args)
    except Exception as e:
        log(f"start failed: {type(e).__name__}: {e}")
        with contextlib.suppress(OSError):
            write_json(out, b"X", {"id": None, "error": f"{type(e).__name__}: {e}", "fatal": True})
        return 1
    log(
        f"ready: {ready['engine']} {args.voice} @ {ready['sample_rate']} Hz, load {ready['load_ms']:.0f} ms, "
        f"warm-up {ready['warmup_ms']:.0f} ms, footprint {ready.get('footprint_mb', '?')} MB"
    )
    if args.self_test:
        t0 = time.perf_counter()
        n = 0
        dropped: list[str] = []
        for pcm, d in engine.synth("Radio check, loud and clear. Box this lap.", args.voice, args.speed):
            n += len(pcm) // 2
            dropped += d
        summary = {
            **ready,
            "self_test_ms": round((time.perf_counter() - t0) * 1000.0, 1),
            "self_test_audio_s": round(n / engine.sample_rate, 2),
            "dropped": dropped,
            "offline": os.environ.get("HF_HUB_OFFLINE") == "1",
        }
        out.write((json.dumps(summary) + "\n").encode())
        return 0 if n > 0 else 1
    write_json(out, b"R", ready)
    try:
        return serve(engine, sys.stdin.buffer, out, args.voice, args.speed)
    except (BrokenPipeError, KeyboardInterrupt):
        return 0


if __name__ == "__main__":
    sys.exit(main())
