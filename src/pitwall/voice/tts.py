"""Text-to-speech engines for the radio: Kokoro (neural, worker process), macOS ``say``, Windows SAPI and a silent
null engine.

``WorkerTts`` (the default, ``tts_engine=kokoro``) - docs/research/tts-evaluation.md sections 5-6:

- **Kokoro-82M on Metal** (mlx-audio) in a long-lived child process (``tts_worker.py``) run by its own venv
  (``scripts/setup-tts.sh``): engine dependencies, crashes, Metal OOMs and memory stay out of pitwall. The
  child is started in a background thread when the radio hub starts; until it reports ready (cold start
  ~10 s, warm ~3 s [measured]) every message goes to ``say``, so the radio is never silent.
- **One request at a time** (a lock), JSON line in, framed records out (``tts_worker`` docstring). Each request
  has a deadline of 2 s + 0.3 x the estimated speech seconds. On a timeout, EOF or a malformed frame the child
  is killed, *that* message is rendered by ``say`` instead, and the child is restarted with back-off
  (1, 2, 5, 10, 30, 60 s). A worker-reported error for one request falls back the same way without a restart.
- **Text front-end** (``tts_lexicon.prepare_text``): numbers to British words, accents folded, phrase rewrites;
  the worker adds pitwall's lexicon of racing names to misaki's G2P (GPL-free: no espeak).
- **Post-processing** (``audio_post.process``): silence trimmed to 40 ms, speech RMS normalised to -17 dBFS,
  peaks limited to -3 dBFS, 5/15 ms fades. ``say`` fallback audio gets the same treatment and is rendered at
  Kokoro's native 24 kHz, so cue parts from either engine can be joined.
- **Voice** switchable at runtime (``set_voice``; per request, no restart). ``diagnostics()`` reports state,
  voice, synthesis time p50/p95, restarts, fallbacks, worker memory and words the G2P dropped.
- ``synthesize_detailed`` says which engine rendered a clip, so the hub only runs the spoken-number check
  (``speech_mismatch``) on neural audio.
- **Measured on the M4 Max** (2026-10-10/11, llama-server idle): warm start 1.4-2.1 s (cold 11 s); call ->
  post-processed PCM for the evaluation's six phrases 81-224 ms median (two-sentence phrase 3: 224 ms), p50
  ~120 ms. Worker footprint ~0.7 GB between requests; per-request peak 1.4-1.6 GB for those phrases, at most
  2.18 GB over 200 adversarial run-on requests (calls are bounded in length: ``tts_worker`` docstring; the
  evaluation's budget is 2.5 GB transient). ``diagnostics()["memory_mb"]`` reports the last and the largest
  recent request peak. While the 27B LLM decodes, phrase 3 takes ~320 ms and the LLM drops from 17 to 12 tok/s
  for the duration of each synthesis only. ``keep_warm`` re-touches an idle worker every 5 minutes during a live
  session so paging never lands on a real message.
- **Short texts** (cue parts such as "turn four", "Box, box.") are said with a carrier word that the worker cuts
  off: alone, Kokoro misread them in some voices ("turn ninth", "box boxy"); with it, 0 of 920 renders failed
  the Parakeet check [measured].

``SayTts`` runs one ``say`` process per message and reads back a WAV as an ``AudioClip``:

- **No shell, no text in argv.** The text is written to a private temp file and passed with ``say -f``, so a
  message starting with ``-`` cannot be parsed as an option and nothing is shell-interpreted. ``say``'s
  embedded speech commands (``[[volm 0]]``, ``[[rate 50]]``...) are neutralised so model output cannot
  change how the rest of the message sounds, and lone surrogates (half of a split emoji escape) are dropped
  so the text always encodes.
- **PCM in the wire format.** ``--data-format=LEI16@<rate>`` makes ``say`` render 16-bit little-endian mono at
  the engine's sample rate, so the frames go to the device without resampling. The WAV is read with the
  standard ``wave`` module (it skips the ``FLLR`` padding chunk Core Audio writes) and its format is checked.
- **Voice validated once.** ``say`` silently uses the system voice when the requested one is missing - even
  for a wrong-case name such as ``daniel`` [measured] - so the voice is resolved against ``say -v ?`` at
  construction and passed by its exact name. A missing voice, or a listing that cannot be produced, logs a
  warning and uses the system default. The listing is decoded as UTF-8 with replacement whatever the locale:
  its sample sentences are in every script, and an ASCII locale must not turn the radio text-only.
- **Bounded.** Each run has a timeout (15 s; ~100 s of speech renders in under 1 s) and its own temp
  directory, removed afterwards, so concurrent calls from worker threads cannot collide.
- Failures raise ``TtsError``; the radio hub catches it and sends the message as text only.

Measured on the M4 Max (Daniel, 200 wpm, 22.05 kHz), call to complete PCM for a two-sentence engineer message
(~9 s of speech): median 0.41-0.45 s over two runs of 10 (all calls 0.40-0.49 s), first call 0.41-0.51 s;
"Copy." takes 0.37 s. That is mostly process start-up and voice load, so cost barely grows with length (12
messages in one call: 0.85 s). Construction (``say -v ?``) takes 0.2-0.3 s. ``warmup()`` pays the first-call
cost up front.

``SapiTts`` (Windows) speaks with the voices Windows itself ships - SAPI 5 "Desktop" voices such as Microsoft
Hazel (en-GB), David and Zira (en-US) - through .NET's ``System.Speech``, run by the in-box Windows PowerShell 5.1:
no extra dependency, one process per message like ``say``:

- **No shell, no text on the command line.** The fixed script goes in as ``-EncodedCommand`` (Base64 UTF-16, not
  subject to the execution policy, nothing to quote); text, voice, rate and paths travel as environment variables
  and a UTF-8 temp file. ``Speak(string)`` reads plain text (not SSML), so markup in a message is just spoken.
- **PCM in the wire format.** ``SetOutputToWaveFile`` with ``SpeechAudioFormatInfo(rate, 16 bit, mono)`` renders
  at the engine's sample rate; the WAV is read and checked like ``say``'s.
- **Voice validated once.** The installed, enabled voices are listed at construction (JSON in a UTF-8 file) and
  the voice is passed by its exact name: ``tts_sapi_voice`` (case-insensitive, or a unique part such as "Hazel"),
  else an en-GB voice, else another English voice, else the system default. OneCore/"natural" voices are not
  visible to SAPI 5 programs and so are not offered.
- **Bounded.** 30 s timeout per run (PowerShell starts cold), own temp directory per call, ``CREATE_NO_WINDOW`` so
  a windowless pitwall never flashes a console. Unmeasured on real hardware: ``typical_synth_s`` (1 s) is an
  estimate the hub replaces with its own timing of cue parts.
- Failures raise ``TtsError`` (the hub sends text only); no PowerShell / no voice makes ``build_tts`` return
  ``NullTts``, and a radio set to device voices speaks on the iPad regardless.

``build_tts`` picks the engine from settings and never raises: kokoro that cannot run becomes ``say`` (on Windows:
``sapi``), ``say`` on Windows becomes ``sapi``, and anything unusable becomes ``NullTts``.
"""

from __future__ import annotations

import base64
import contextlib
import itertools
import json
import logging
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from collections import Counter, deque
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from pitwall.compat import app_support_dir, venv_python
from pitwall.config import Settings
from pitwall.voice import audio_post
from pitwall.voice.tts_lexicon import LEXICON_PATH, Lexicon, load_lexicon, prepare_text
from pitwall.voice.tts_worker import read_frame
from pitwall.voice.types import AudioClip, SynthResult, TtsEngine

__all__ = [
    "DEFAULT_SAMPLE_RATE",
    "KOKORO_SAMPLE_RATE",
    "KOKORO_VOICES",
    "NullTts",
    "SapiTts",
    "SapiVoice",
    "SayTts",
    "SayVoice",
    "TtsError",
    "WorkerTts",
    "build_tts",
    "list_say_voices",
    "parse_sapi_voices",
    "parse_say_voices",
    "speech_mismatch",
]

log = logging.getLogger(__name__)

DEFAULT_SAMPLE_RATE = 22_050
SAY_TIMEOUT_S = 15.0
_VOICE_LIST_TIMEOUT_S = 10.0
_MIN_RATE_WPM, _MAX_RATE_WPM = 50, 600
_MIN_SAMPLE_RATE, _MAX_SAMPLE_RATE = 8_000, 48_000

# "Daniel              en_GB    # Hello! My name is Daniel."  /  "Eddy (English (UK)) en_GB    # Hello! ..."
_VOICE_LINE = re.compile(r"^(?P<name>\S.*?)\s+(?P<locale>[a-z]{2,3}[_-][A-Za-z0-9]+)\s+#")
_UNSAFE_TEXT = re.compile(r"\[\[|\]\]|[\ud800-\udfff]")  # say embedded-command brackets, lone surrogates


class TtsError(RuntimeError):
    """Synthesis failed (engine missing, timed out, exited non-zero or produced unreadable audio)."""


@dataclass(slots=True, frozen=True)
class SayVoice:
    name: str
    locale: str


def parse_say_voices(listing: str) -> list[SayVoice]:
    """Parse ``say -v ?`` output. Voice names may contain spaces and parentheses."""
    voices: list[SayVoice] = []
    for line in listing.splitlines():
        m = _VOICE_LINE.match(line)
        if m:
            voices.append(SayVoice(m.group("name"), m.group("locale")))
    return voices


def list_say_voices(say_path: str = "say", timeout_s: float = _VOICE_LIST_TIMEOUT_S) -> list[SayVoice]:
    """Voices installed for ``say``. Raises ``TtsError`` if the listing cannot be produced."""
    try:
        proc = subprocess.run(
            [say_path, "-v", "?"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as e:
        raise TtsError(f"'say -v ?' timed out after {timeout_s:g} s") from e
    except (OSError, ValueError) as e:  # ValueError: unusable path (e.g. NUL byte)
        raise TtsError(f"cannot run {say_path!r}: {e}") from e
    if proc.returncode != 0:
        raise TtsError(f"'say -v ?' exited with {proc.returncode}: {proc.stderr.strip()[:200]}")
    return parse_say_voices(proc.stdout)


class SayTts:
    """macOS ``say`` engine. ``voice=None`` (or a voice that is not installed) uses the system default voice."""

    __slots__ = ("_say", "name", "rate_wpm", "sample_rate", "timeout_s", "voice")

    name: str
    sample_rate: int
    voice: str | None  # exact installed voice name, or None for the system default
    rate_wpm: int
    timeout_s: float

    def __init__(
        self,
        voice: str | None = "Daniel",
        rate_wpm: int = 200,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        *,
        timeout_s: float = SAY_TIMEOUT_S,
        say_path: str | None = None,
    ) -> None:
        if not _MIN_RATE_WPM <= rate_wpm <= _MAX_RATE_WPM:
            raise ValueError(f"rate_wpm must be {_MIN_RATE_WPM}-{_MAX_RATE_WPM}, got {rate_wpm}")
        if not _MIN_SAMPLE_RATE <= sample_rate <= _MAX_SAMPLE_RATE:
            raise ValueError(f"sample_rate must be {_MIN_SAMPLE_RATE}-{_MAX_SAMPLE_RATE} Hz, got {sample_rate}")
        if timeout_s <= 0:
            raise ValueError(f"timeout_s must be positive, got {timeout_s}")
        exe = say_path or shutil.which("say")
        if exe is None:
            raise TtsError("macOS 'say' command not found")
        self._say = exe
        self.name = "say"
        self.sample_rate = sample_rate
        self.rate_wpm = rate_wpm
        self.timeout_s = timeout_s
        self.voice = self._resolve_voice(voice)

    def _resolve_voice(self, wanted: str | None) -> str | None:
        if not wanted or not wanted.strip():
            return None
        wanted = wanted.strip()
        try:
            voices = list_say_voices(self._say)
        except TtsError as e:
            log.warning("cannot list 'say' voices (%s); using the system default voice", e)
            return None
        by_name = {v.name.casefold(): v.name for v in voices}
        exact = by_name.get(wanted.casefold())
        if exact is None:
            english = sorted(v.name for v in voices if v.locale.startswith("en"))
            log.warning(
                "TTS voice %r is not installed; using the system default voice. Installed English voices: %s. "
                "Add voices in System Settings > Accessibility > Spoken Content.",
                wanted,
                ", ".join(english) or "none",
            )
        return exact

    def synthesize(self, text: str) -> AudioClip:
        """Blocking synthesis (~0.4 s). Raises ``TtsError`` on failure; empty text gives empty audio."""
        text = _UNSAFE_TEXT.sub(" ", text).strip()
        if not text:
            return AudioClip(b"", self.sample_rate)
        try:
            with tempfile.TemporaryDirectory(prefix="pitwall-tts-", ignore_cleanup_errors=True) as tmp:
                src = Path(tmp) / "text.txt"
                out = Path(tmp) / "speech.wav"
                src.write_text(text, encoding="utf-8")
                self._run_say(src, out)
                return self._read_wav(out)
        except OSError as e:  # temp directory or text file (say's own failures are already TtsError)
            raise TtsError(f"cannot stage text for say: {e}") from e

    def _run_say(self, src: Path, out: Path) -> None:
        cmd = [self._say]
        if self.voice is not None:
            cmd += ["-v", self.voice]
        cmd += [
            "-r",
            str(self.rate_wpm),
            "-f",
            str(src),
            "-o",
            str(out),
            "--file-format=WAVE",
            f"--data-format=LEI16@{self.sample_rate}",
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, timeout=self.timeout_s, check=False, stdin=subprocess.DEVNULL
            )
        except subprocess.TimeoutExpired as e:  # run() has already killed and reaped the child
            raise TtsError(f"say timed out after {self.timeout_s:g} s") from e
        except OSError as e:
            raise TtsError(f"cannot run {self._say!r}: {e}") from e
        if proc.returncode != 0:
            detail = proc.stderr.decode("utf-8", "replace").strip()[:200]
            raise TtsError(f"say exited with {proc.returncode}: {detail}")

    def _read_wav(self, path: Path) -> AudioClip:
        try:
            with path.open("rb") as fh, wave.open(fh, "rb") as w:
                channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
                frames = w.readframes(w.getnframes())
        except (OSError, EOFError, wave.Error) as e:
            raise TtsError(f"say produced no readable WAV: {e}") from e
        if (channels, width, rate) != (1, 2, self.sample_rate):
            raise TtsError(
                f"say produced {channels} ch / {8 * width}-bit / {rate} Hz, expected mono 16-bit {self.sample_rate} Hz"
            )
        return AudioClip(frames, rate)

    def warmup(self) -> None:
        """Synthesise a short phrase so the first real message does not pay the cold voice-load cost."""
        t0 = time.perf_counter()
        try:
            self.synthesize("Radio check.")
        except TtsError as e:
            log.warning("TTS warm-up failed: %s", e)
            return
        log.info("TTS warm (say, voice %s): %.0f ms", self.voice or "system default", (time.perf_counter() - t0) * 1e3)

    def __repr__(self) -> str:
        return f"SayTts(voice={self.voice!r}, rate_wpm={self.rate_wpm}, sample_rate={self.sample_rate})"


@dataclass(slots=True)
class NullTts:
    """No audio: radio messages are delivered as text only (``n_bytes`` 0 on the wire)."""

    name: str = "none"
    sample_rate: int = DEFAULT_SAMPLE_RATE
    reason: str = ""  # why there is no real engine, for diagnostics

    def synthesize(self, text: str) -> AudioClip:
        return AudioClip(b"", self.sample_rate)

    def warmup(self) -> None:
        return None


# ============================================================================================ Windows SAPI
SAPI_TIMEOUT_S = 30.0  # per run: Windows PowerShell can take seconds to start cold [estimate]
SAPI_LIST_TIMEOUT_S = 30.0
SAPI_TYPICAL_SYNTH_S = 1.0  # [estimate, unmeasured]: PowerShell start + System.Speech load + synthesis
_SAPI_MIN_RATE, _SAPI_MAX_RATE = -10, 10
_SAPI_UNSAFE_TEXT = re.compile(r"[\ud800-\udfff]")  # lone surrogates cannot be written as UTF-8
_CREATE_NO_WINDOW: int = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # 0 off Windows (subprocess rejects others)

# Runs in Windows PowerShell 5.1 (powershell.exe; System.Speech is a .NET Framework assembly). Inputs arrive in
# PWSAPI_* environment variables, results in files; a failure exits 3 with the message in PWSAPI_ERR.
_SAPI_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$utf8 = New-Object -TypeName System.Text.UTF8Encoding -ArgumentList $false
try {
    Add-Type -AssemblyName System.Speech
    $synth = New-Object -TypeName System.Speech.Synthesis.SpeechSynthesizer
    try {
        if ($env:PWSAPI_MODE -eq 'list') {
            $voices = @(foreach ($v in $synth.GetInstalledVoices()) {
                if ($v.Enabled) {
                    $info = $v.VoiceInfo
                    @{ name = $info.Name; culture = $info.Culture.Name; gender = [string]$info.Gender }
                }
            })
            [System.IO.File]::WriteAllText($env:PWSAPI_OUT, (ConvertTo-Json -InputObject $voices -Compress), $utf8)
        } else {
            $text = [System.IO.File]::ReadAllText($env:PWSAPI_TEXT, [System.Text.Encoding]::UTF8)
            if ($env:PWSAPI_VOICE) { $synth.SelectVoice($env:PWSAPI_VOICE) }
            $synth.Rate = [int]$env:PWSAPI_RATE
            $synth.Volume = 100
            $hz = [int]$env:PWSAPI_SAMPLE_RATE
            $bits = [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen
            $mono = [System.Speech.AudioFormat.AudioChannel]::Mono
            $formatType = 'System.Speech.AudioFormat.SpeechAudioFormatInfo'
            $format = New-Object -TypeName $formatType -ArgumentList $hz, $bits, $mono
            $synth.SetOutputToWaveFile($env:PWSAPI_OUT, $format)
            $synth.Speak($text)
            $synth.SetOutputToNull()
        }
    } finally {
        $synth.Dispose()
    }
} catch {
    if ($env:PWSAPI_ERR) { [System.IO.File]::WriteAllText($env:PWSAPI_ERR, [string]$_.Exception.Message, $utf8) }
    exit 3
}
exit 0
"""


def _encoded_command(script: str) -> str:
    """``powershell -EncodedCommand`` takes the script as Base64 of its UTF-16LE text."""
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def find_powershell() -> str | None:
    """Windows PowerShell 5.1 (``powershell.exe``, which has ``System.Speech``), or ``None``. The System32 copy
    first, so a ``powershell.exe`` earlier on PATH cannot stand in for it; PowerShell 7 (``pwsh``) lacks the
    assembly."""
    root = os.environ.get("SYSTEMROOT")  # Windows environment names are case-insensitive
    if root:
        exe = Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        if exe.is_file():
            return str(exe)
    return shutil.which("powershell")


@dataclass(slots=True, frozen=True)
class SapiVoice:
    name: str  # e.g. "Microsoft Hazel Desktop"
    culture: str  # e.g. "en-GB"
    gender: str = ""


def parse_sapi_voices(raw: str) -> list[SapiVoice]:
    """Parse the voice listing (a JSON array of ``{name, culture, gender}``; tolerates a lone object or nothing)."""
    try:
        data = json.loads(raw) if raw.strip() else []
    except ValueError as e:
        raise TtsError(f"unreadable SAPI voice list: {e}") from e
    if isinstance(data, dict):
        data = [data]
    voices: list[SapiVoice] = []
    for item in data if isinstance(data, list) else []:
        if isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"].strip():
            voices.append(SapiVoice(item["name"], str(item.get("culture") or ""), str(item.get("gender") or "")))
    return voices


def choose_sapi_voice(wanted: str | None, voices: Sequence[SapiVoice]) -> str | None:
    """The exact name of the voice to use, or ``None`` for the system default voice.

    ``wanted`` matches case-insensitively, or by a part that only one voice contains ("hazel"). Without a match
    (or without ``wanted``): the first en-GB voice, else the first other English voice - the engineer's text is
    English whatever the Windows display language - else the system default."""
    if wanted and wanted.strip():
        key = wanted.strip().casefold()
        exact = {v.name.casefold(): v.name for v in voices}.get(key)
        if exact is not None:
            return exact
        partial = [v.name for v in voices if key in v.name.casefold()]
        if len(partial) == 1:
            return partial[0]
        english = sorted(v.name for v in voices if v.culture.lower().startswith("en"))
        log.warning(
            "Windows voice %r is not installed (or not unique); installed English voices: %s. Add voices in "
            "Settings > Time & language > Speech (SAPI programs see only the 'Desktop' voices).",
            wanted,
            ", ".join(english) or "none",
        )
    for prefix in ("en-gb", "en"):
        for v in voices:
            if v.culture.lower().startswith(prefix):
                return v.name
    return None


class SapiTts:
    """Windows' built-in SAPI voices through ``System.Speech`` in Windows PowerShell (module docstring)."""

    __slots__ = ("_powershell", "installed_voices", "name", "rate", "sample_rate", "timeout_s", "voice")

    typical_synth_s = SAPI_TYPICAL_SYNTH_S  # read by the radio hub until it has timed cue parts itself

    name: str
    sample_rate: int
    voice: str | None  # exact installed voice name, or None for the system default
    rate: int
    timeout_s: float
    installed_voices: list[SapiVoice]

    def __init__(
        self,
        voice: str | None = None,
        rate: int = 0,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        *,
        timeout_s: float = SAPI_TIMEOUT_S,
        powershell: str | None = None,
    ) -> None:
        if not _SAPI_MIN_RATE <= rate <= _SAPI_MAX_RATE:
            raise ValueError(f"rate must be {_SAPI_MIN_RATE}..{_SAPI_MAX_RATE}, got {rate}")
        if not _MIN_SAMPLE_RATE <= sample_rate <= _MAX_SAMPLE_RATE:
            raise ValueError(f"sample_rate must be {_MIN_SAMPLE_RATE}-{_MAX_SAMPLE_RATE} Hz, got {sample_rate}")
        if timeout_s <= 0:
            raise ValueError(f"timeout_s must be positive, got {timeout_s}")
        exe = powershell or find_powershell()
        if exe is None:
            raise TtsError("Windows PowerShell (powershell.exe) not found")
        self._powershell = exe
        self.name = "sapi"
        self.sample_rate = sample_rate
        self.rate = rate
        self.timeout_s = timeout_s
        try:
            self.installed_voices = self.list_voices()
        except TtsError as e:
            log.warning("cannot list Windows voices (%s); using the system default voice", e)
            self.installed_voices = []
        self.voice = choose_sapi_voice(voice, self.installed_voices)

    def list_voices(self) -> list[SapiVoice]:
        """Installed, enabled SAPI voices. Raises ``TtsError`` if the listing cannot be produced."""
        with tempfile.TemporaryDirectory(prefix="pitwall-tts-", ignore_cleanup_errors=True) as tmp:
            out = Path(tmp) / "voices.json"
            self._run({"PWSAPI_MODE": "list", "PWSAPI_OUT": str(out)}, Path(tmp), SAPI_LIST_TIMEOUT_S)
            try:
                raw = out.read_text(encoding="utf-8-sig")
            except OSError as e:
                raise TtsError(f"SAPI voice list not written: {e}") from e
        return parse_sapi_voices(raw)

    def synthesize(self, text: str) -> AudioClip:
        """Blocking synthesis. Raises ``TtsError`` on failure; empty text gives empty audio without a process."""
        text = _SAPI_UNSAFE_TEXT.sub(" ", text).strip()
        if not text:
            return AudioClip(b"", self.sample_rate)
        try:
            with tempfile.TemporaryDirectory(prefix="pitwall-tts-", ignore_cleanup_errors=True) as tmp:
                src = Path(tmp) / "text.txt"
                out = Path(tmp) / "speech.wav"
                src.write_text(text, encoding="utf-8")
                env = {
                    "PWSAPI_MODE": "speak",
                    "PWSAPI_TEXT": str(src),
                    "PWSAPI_OUT": str(out),
                    "PWSAPI_VOICE": self.voice or "",
                    "PWSAPI_RATE": str(self.rate),
                    "PWSAPI_SAMPLE_RATE": str(self.sample_rate),
                }
                self._run(env, Path(tmp), self.timeout_s)
                return self._read_wav(out)
        except OSError as e:  # temp directory or text file (PowerShell's own failures are already TtsError)
            raise TtsError(f"cannot stage text for SAPI: {e}") from e

    def _run(self, env_extra: dict[str, str], tmp: Path, timeout_s: float) -> None:
        err = tmp / "error.txt"
        cmd = [
            self._powershell,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            _encoded_command(_SAPI_SCRIPT),
        ]
        env = {**os.environ, **env_extra, "PWSAPI_ERR": str(err)}
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout_s,
                check=False,
                stdin=subprocess.DEVNULL,
                env=env,
                creationflags=_CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired as e:  # run() has already killed and reaped the child
            raise TtsError(f"SAPI (PowerShell) timed out after {timeout_s:g} s") from e
        except (OSError, ValueError) as e:  # ValueError: unusable path (e.g. NUL byte)
            raise TtsError(f"cannot run {self._powershell!r}: {e}") from e
        if proc.returncode != 0:
            detail = ""
            with contextlib.suppress(OSError):
                detail = err.read_text(encoding="utf-8-sig", errors="replace").strip()
            if not detail:
                detail = proc.stderr.decode("utf-8", "replace").strip()
            raise TtsError(f"SAPI (PowerShell) exited with {proc.returncode}: {detail[:200]}")

    def _read_wav(self, path: Path) -> AudioClip:
        try:
            with path.open("rb") as fh, wave.open(fh, "rb") as w:
                channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
                frames = w.readframes(w.getnframes())
        except (OSError, EOFError, wave.Error) as e:
            raise TtsError(f"SAPI produced no readable WAV: {e}") from e
        if (channels, width, rate) != (1, 2, self.sample_rate):
            raise TtsError(
                f"SAPI produced {channels} ch / {8 * width}-bit / {rate} Hz, expected mono 16-bit {self.sample_rate} Hz"
            )
        return AudioClip(frames, rate)

    def warmup(self) -> None:
        """Synthesise a short phrase so the first real message does not pay the cold start alone."""
        t0 = time.perf_counter()
        try:
            self.synthesize("Radio check.")
        except TtsError as e:
            log.warning("TTS warm-up failed: %s", e)
            return
        log.info("TTS warm (sapi, voice %s): %.0f ms", self.voice or "system default", (time.perf_counter() - t0) * 1e3)

    def diagnostics(self) -> dict[str, Any]:
        return {
            "engine": self.name,
            "voice": self.voice,
            "rate": self.rate,
            "sample_rate": self.sample_rate,
            "installed_voices": [f"{v.name} ({v.culture})" for v in self.installed_voices],
            "powershell": self._powershell,
        }

    def __repr__(self) -> str:
        return f"SapiTts(voice={self.voice!r}, rate={self.rate}, sample_rate={self.sample_rate})"


# ============================================================================================ Kokoro worker
KOKORO_VOICES = ("bm_fable", "bm_george", "bf_emma", "bf_isabella")  # the radio page's picker
KOKORO_DEFAULT_VOICE = "bm_fable"
KOKORO_SAMPLE_RATE = 24_000
KOKORO_TYPICAL_SYNTH_S = 0.26  # two-sentence message, mlx-audio on the M4 Max [measured, tts-evaluation 2.2]
SAY_TYPICAL_SYNTH_S = 0.4  # [measured, see SayTts]
TTS_HOME = app_support_dir()  # macOS: ~/Library/Application Support/pitwall
WORKER_SCRIPT = Path(__file__).resolve().with_name("tts_worker.py")
WORKER_START_TIMEOUT_S = 180.0  # cold start 11 s [measured]; minutes when the Mac is deep in swap
WORKER_DEADLINE_BASE_S = 2.0
WORKER_DEADLINE_PER_SPEECH_S = 0.3
WORKER_WORDS_PER_S = 2.6  # speech-time estimate for the deadline (same as the hub's)
RESTART_BACKOFF_S = (1.0, 2.0, 5.0, 10.0, 30.0, 60.0)
STABLE_AFTER_S = 60.0  # a worker up this long resets the back-off
UNAVAILABLE_RECHECK_S = 60.0  # worker venv missing: look again this often (scripts/setup-tts.sh may run later)
STATS_WINDOW = 50
KEEP_WARM_IDLE_S = 300.0  # idle longer than this while a session is live: one throw-away synthesis (keep_warm)
_KOKORO_VOICE_RE = re.compile(r"^[a-z][fm]_[a-z]+$")


class _WorkerFailure(Exception):
    """A request the worker did not answer properly; the message falls back to ``say``."""


def _percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))]


class WorkerTts:
    """Kokoro-82M (mlx-audio) in a persistent worker process, with ``say`` as the automatic fallback.

    Thread-safe. ``start()`` launches the supervisor thread (non-blocking); ``close()`` stops the worker.
    ``synthesize`` never waits for the worker to load: until it is ready the fallback renders the message.
    """

    name = "kokoro"
    neural = True

    def __init__(
        self,
        *,
        python: Path,
        voice: str = KOKORO_DEFAULT_VOICE,
        speed: float = 1.1,
        model: str = "mlx-community/Kokoro-82M-bf16",
        revision: str | None = None,
        lexicon: Path | None = LEXICON_PATH,
        hf_home: Path | None = None,
        cache_limit_mb: float = 0.0,
        fallback: TtsEngine | None = None,
        script: Path = WORKER_SCRIPT,
        start_timeout_s: float = WORKER_START_TIMEOUT_S,
        deadline_base_s: float = WORKER_DEADLINE_BASE_S,
        deadline_per_speech_s: float = WORKER_DEADLINE_PER_SPEECH_S,
        backoff_s: Sequence[float] = RESTART_BACKOFF_S,
        extra_args: Sequence[str] = (),
    ) -> None:
        if not 0.5 <= speed <= 2.0:
            raise ValueError(f"speed must be 0.5-2.0, got {speed}")
        self.sample_rate = KOKORO_SAMPLE_RATE
        self.python = python
        self.script = script
        self.model = model
        self.revision = revision
        self.lexicon_path = lexicon
        self.hf_home = hf_home
        self.cache_limit_mb = cache_limit_mb
        self.speed = speed
        self.start_timeout_s = start_timeout_s
        self.deadline_base_s = deadline_base_s
        self.deadline_per_speech_s = deadline_per_speech_s
        self.backoff_s = tuple(backoff_s) or (1.0,)
        self.extra_args = tuple(extra_args)
        self._fallback = fallback
        self._voice = voice
        self._lexicon: Lexicon = load_lexicon(lexicon) if lexicon is not None else Lexicon()
        self._lock = threading.Lock()  # one request at a time on the worker's pipes
        self._proc: subprocess.Popen[bytes] | None = None
        self._gen = 0
        self._frames: queue.Queue[tuple[int, str | None, bytes]] = queue.Queue()
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._ids = itertools.count(1)
        self._status = "stopped"
        self._ready_info: dict[str, Any] = {}
        self._ready_mono = 0.0
        self._last_error: str | None = None
        self._restarts = 0
        self._failures = 0  # consecutive start failures / crashes (back-off index)
        self._wall_s: deque[float] = deque(maxlen=STATS_WINDOW)  # call -> post-processed clip, worker path
        self._worker_ms: deque[float] = deque(maxlen=STATS_WINDOW)  # the worker's own synth_ms
        self._served: Counter[str] = Counter()
        self._fallback_reasons: Counter[str] = Counter()
        self._memory: dict[str, float] = {}
        self._request_peaks: deque[float] = deque(maxlen=STATS_WINDOW)  # worker footprint peak per request (MB)
        self._dropped: Counter[str] = Counter()
        self._last_used = time.monotonic()
        self._keep_warms = 0
        self._gpl_free: bool | None = None  # from the ready record, then every request's end record

    # ------------------------------------------------------------------ public state
    @property
    def ready(self) -> bool:
        return self._ready.is_set()

    @property
    def voice(self) -> str:
        return self._voice

    @property
    def voices(self) -> list[str]:
        """Voices offered to the driver: the picker's, as far as the worker has them."""
        have = self._ready_info.get("voices")
        return [v for v in KOKORO_VOICES if not isinstance(have, list) or v in have]

    @property
    def active(self) -> str:
        """The engine that renders a message right now."""
        if self.ready:
            return self.name
        return self.fallback_name or "none"

    @property
    def status(self) -> str:
        return self._status

    @property
    def fallback_name(self) -> str | None:
        return getattr(self._fallback, "name", None) if self._fallback is not None else None

    @property
    def typical_synth_s(self) -> float:
        return KOKORO_TYPICAL_SYNTH_S if self.ready else SAY_TYPICAL_SYNTH_S

    def measured_synth_s(self) -> float | None:
        """Median call -> clip time of recent worker syntheses (s); ``None`` before three were timed or while the
        fallback speaks (its time is ``typical_synth_s``)."""
        samples = list(self._wall_s)
        return _percentile(samples, 0.5) if len(samples) >= 3 and self.ready else None

    def set_voice(self, voice: str) -> None:
        """Switch voice for every following message (no restart). Raises ``ValueError`` for an unknown voice."""
        voice = voice.strip()
        have = self._ready_info.get("voices")
        allowed = set(KOKORO_VOICES)
        if isinstance(have, list):
            allowed |= {v for v in have if isinstance(v, str) and v[:3] in ("bf_", "bm_", "af_", "am_")}
            allowed &= set(have)
        if voice not in allowed:
            raise ValueError(f"unknown voice {voice!r}; choose one of {', '.join(KOKORO_VOICES)}")
        if voice != self._voice:
            log.info("kokoro voice: %s -> %s", self._voice, voice)
        self._voice = voice

    def diagnostics(self) -> dict[str, Any]:
        wall = [s * 1000.0 for s in self._wall_s]
        worker = list(self._worker_ms)
        proc = self._proc
        info = self._ready_info
        return {
            "engine": self.name,
            "status": self._status,
            "ready": self.ready,
            "active": self.active,
            "voice": self._voice,
            "voices": self.voices,
            "speed": self.speed,
            "sample_rate": self.sample_rate,
            "fallback": getattr(self._fallback, "name", None),
            "fallback_voice": getattr(self._fallback, "voice", None),
            "pid": proc.pid if proc is not None and proc.poll() is None else None,
            "restarts": self._restarts,
            "consecutive_failures": self._failures,
            "last_error": self._last_error,
            "served": dict(self._served),
            "fallback_reasons": dict(self._fallback_reasons.most_common(8)),
            "synth_ms": {
                "n": len(wall),
                "p50": _round(_percentile(wall, 0.5)),
                "p95": _round(_percentile(wall, 0.95)),
                "worker_p50": _round(_percentile(worker, 0.5)),
            },
            "memory_mb": {
                **self._memory,
                "request_peak_max_mb": max(self._request_peaks) if self._request_peaks else None,
            },
            "load_ms": info.get("load_ms"),
            "warmup_ms": info.get("warmup_ms"),
            "gpl_free": self._gpl_free,
            "dropped_words": dict(self._dropped.most_common(20)),
            "keep_warms": self._keep_warms,
            "python": str(self.python),
            "model": self.model,
            "revision": self.revision,
        }

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        """Launch the worker in the background (idempotent). Messages use the fallback until it is ready."""
        if self._thread is not None or self._stop.is_set():
            return
        self._status = "starting"
        self._thread = threading.Thread(target=self._supervise, name="tts-worker", daemon=True)
        self._thread.start()

    def close(self, timeout_s: float = 3.0) -> None:
        self._stop.set()
        self._wake.set()
        self._ready.clear()
        proc = self._proc
        if proc is not None:
            _stop_process(proc, timeout_s)
        if self._thread is not None:
            self._thread.join(timeout_s)
        self._status = "stopped"

    def warmup(self) -> None:
        """The worker warms itself up when it starts (``start``)."""
        return None

    def keep_warm(self, idle_s: float = KEEP_WARM_IDLE_S) -> bool:
        """One throw-away synthesis if the worker has been idle for ``idle_s`` (blocking, ~0.05 s; call from a
        thread). Under memory pressure an idle worker's pages are compressed or swapped out, and the next real
        message would pay for paging them back (tts-evaluation section 6.2). Never waits for a busy worker.
        True if it ran."""
        if not self.ready or time.monotonic() - self._last_used < idle_s:
            return False
        if not self._lock.acquire(blocking=False):
            return False
        self._lock.release()  # _worker_synth takes it again; a real message may slip in first, which is fine
        self._last_used = time.monotonic()
        try:
            self._worker_synth("Copy.")
        except _WorkerFailure as e:
            log.warning("kokoro keep-warm failed: %s", e)
            return False
        self._keep_warms += 1
        return True

    def _supervise(self) -> None:
        while not self._stop.is_set():
            if not self.python.exists():
                level = logging.DEBUG if self._status == "unavailable" else logging.WARNING  # once, not every minute
                self._status = "unavailable"
                self._last_error = f"worker venv not found ({self.python}): run scripts/setup-tts.sh"
                log.log(level, "kokoro TTS unavailable: %s; the radio uses 'say'", self._last_error)
                self._wake.wait(UNAVAILABLE_RECHECK_S)
                self._wake.clear()
                continue
            if self._spawn_and_wait():
                self._watch()
                if self._stop.is_set():
                    break
                self._restarts += 1
                if time.monotonic() - self._ready_mono >= STABLE_AFTER_S:
                    self._failures = 0
            if self._stop.is_set():
                break
            delay = self.backoff_s[min(self._failures, len(self.backoff_s) - 1)]
            self._failures += 1
            self._status = "restarting"
            log.warning("kokoro TTS worker down (%s); restarting in %.0f s", self._last_error, delay)
            self._stop.wait(delay)

    def _watch(self) -> None:
        """Block while the ready worker lives (a request that kills it sets ``_wake``)."""
        while not self._stop.is_set():
            proc = self._proc
            if proc is None or proc.poll() is not None:
                break
            self._wake.wait(1.0)
            self._wake.clear()
        self._ready.clear()
        proc = self._proc
        if proc is not None and proc.poll() is None and not self._stop.is_set():
            _stop_process(proc, 1.0)
        if proc is not None and proc.returncode not in (None, 0) and self._last_error is None:
            self._last_error = f"worker exited with code {proc.returncode}"

    def _command(self) -> list[str]:
        cmd = [str(self.python), "-I", str(self.script), "--model", self.model, "--voice", self._voice]
        if self.revision:
            cmd += ["--revision", self.revision]
        if self.lexicon_path is not None:
            cmd += ["--lexicon", str(self.lexicon_path)]
        cmd += ["--speed", f"{self.speed:g}", "--cache-limit-mb", f"{self.cache_limit_mb:g}", *self.extra_args]
        return cmd

    def _env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "VIRTUAL_ENV"))}
        env.update({"HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1", "TOKENIZERS_PARALLELISM": "false"})
        if self.hf_home is not None:
            env["HF_HOME"] = str(self.hf_home)
        return env

    def _spawn_and_wait(self) -> bool:
        """Start a worker process and wait for its ready record. True when it is ready."""
        self._status = "starting"
        self._ready.clear()
        t0 = time.perf_counter()
        try:
            proc = subprocess.Popen(
                self._command(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self._env(),
                cwd=str(self.python.parent),
            )
        except OSError as e:
            self._last_error = f"cannot start worker: {e}"
            return False
        with self._lock:
            self._gen += 1
            gen = self._gen
            self._proc = proc
        assert proc.stdout is not None and proc.stderr is not None
        threading.Thread(target=self._read_frames, args=(proc.stdout, gen), name="tts-worker-out", daemon=True).start()
        threading.Thread(target=self._read_log, args=(proc.stderr,), name="tts-worker-log", daemon=True).start()
        deadline = time.monotonic() + self.start_timeout_s
        while not self._stop.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._last_error = f"worker not ready after {self.start_timeout_s:.0f} s"
                break
            try:
                g, kind, payload = self._frames.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue
            if g != gen:
                continue
            if kind == "R":
                info = _loads(payload)
                if info is None or int(info.get("sample_rate") or 0) != self.sample_rate:
                    self._last_error = f"unexpected ready record: {payload[:200]!r}"
                    break
                self._ready_info = info
                self._gpl_free = info.get("gpl_free") is True
                self._ready_mono = time.monotonic()
                self._last_error = None
                self._status = "ready"
                self._ready.set()
                if self._voice not in (info.get("voices") or []):
                    used = info.get("voice")
                    used = used if isinstance(used, str) and used else KOKORO_DEFAULT_VOICE
                    log.warning("kokoro voice %r not installed; using %s", self._voice, used)
                    self._voice = used
                log.info(
                    "kokoro TTS ready in %.1f s (pid %d, voice %s, load %s ms, warm-up %s ms, footprint %s MB)",
                    time.perf_counter() - t0,
                    proc.pid,
                    self._voice,
                    info.get("load_ms"),
                    info.get("warmup_ms"),
                    info.get("footprint_mb"),
                )
                return True
            if kind == "X":
                err = _loads(payload) or {}
                self._last_error = f"worker failed to start: {err.get('error', payload[:200])}"
                break
            if kind is None or kind == "!":
                self._last_error = f"worker exited during start-up (code {proc.poll()})"
                break
        _stop_process(proc, 1.0)
        return False

    def _read_frames(self, stream: IO[bytes], gen: int) -> None:
        try:
            while True:
                frame = read_frame(stream)
                if frame is None:
                    break
                self._frames.put((gen, frame[0], frame[1]))
        except (ValueError, OSError) as e:
            self._frames.put((gen, "!", str(e).encode()))
            return
        self._frames.put((gen, None, b""))

    def _read_log(self, stream: IO[bytes]) -> None:
        """The worker's stderr into pitwall's log (tracebacks and errors as warnings)."""
        for raw in stream:
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                level = logging.WARNING if "Traceback" in line or "Error" in line else logging.INFO
                log.log(level, "%s", line[:500])

    # ------------------------------------------------------------------ synthesis
    def synthesize(self, text: str) -> AudioClip:
        return self.synthesize_detailed(text).clip

    def synthesize_detailed(self, text: str, voice: str | None = None) -> SynthResult:
        """Kokoro if the worker is ready and answers in time, else ``say`` (``TtsError`` if neither works).
        ``voice`` (spotter): another Kokoro voice for this request only; None = the engineer's voice. The fallback
        always speaks with its own voice."""
        t0 = time.perf_counter()
        if not text.strip():
            return SynthResult(AudioClip(b"", self.sample_rate), self.name, True, 0.0)
        if self.ready:
            try:
                clip, worker_ms = self._worker_synth(text, voice)
            except _WorkerFailure as e:
                reason = str(e)
                log.warning("kokoro TTS failed (%s); this message uses %s", reason, self.active)
            else:
                wall = time.perf_counter() - t0
                self._wall_s.append(wall)
                self._worker_ms.append(worker_ms)
                self._served[self.name] += 1
                if time.monotonic() - self._ready_mono >= STABLE_AFTER_S:
                    self._failures = 0
                return SynthResult(clip, self.name, True, wall * 1000.0)
        else:
            reason = f"worker {self._status}"
        clip = self.synthesize_fallback(text)
        name = getattr(self._fallback, "name", "none")
        self._served[name] += 1
        self._fallback_reasons[reason.split(":")[0][:60]] += 1
        return SynthResult(clip, name, False, (time.perf_counter() - t0) * 1000.0, reason)

    def synthesize_fallback(self, text: str) -> AudioClip:
        """``say`` at 24 kHz, post-processed like Kokoro's audio. Raises ``TtsError`` without a fallback."""
        if self._fallback is None:
            raise TtsError(f"kokoro unavailable ({self._last_error or self._status}) and no fallback voice")
        raw = self._fallback.synthesize(text)
        if raw.sample_rate != self.sample_rate:
            raise TtsError(f"fallback rendered {raw.sample_rate} Hz, expected {self.sample_rate} Hz")
        return audio_post.process(raw)

    def _deadline_s(self, text: str) -> float:
        speech_s = len(text.split()) / (WORKER_WORDS_PER_S * self.speed)
        return self.deadline_base_s + self.deadline_per_speech_s * speech_s

    def _worker_synth(self, text: str, voice: str | None = None) -> tuple[AudioClip, float]:
        self._last_used = time.monotonic()
        prepared = prepare_text(text, self._lexicon)
        if not prepared:
            return AudioClip(b"", self.sample_rate), 0.0
        with self._lock:
            proc, gen = self._proc, self._gen
            if proc is None or proc.stdin is None or proc.poll() is not None or not self.ready:
                if proc is not None and proc.poll() is not None:
                    self._kill(proc, f"worker exited with code {proc.returncode}")  # before the supervisor noticed
                raise _WorkerFailure("worker not running")
            while True:  # frames left from an earlier (killed) generation; or this worker died while idle
                try:
                    g, kind, _payload = self._frames.get_nowait()
                except queue.Empty:
                    break
                if g == gen and kind in (None, "!"):
                    self._kill(proc, "worker exited while idle")
                    raise _WorkerFailure("worker exited while idle")
            rid = f"r{next(self._ids)}"
            request = {"id": rid, "text": prepared, "voice": voice or self._voice, "speed": self.speed}
            try:
                proc.stdin.write((json.dumps(request) + "\n").encode())
                proc.stdin.flush()
            except (OSError, ValueError) as e:
                self._kill(proc, f"request pipe closed: {e}")
                raise _WorkerFailure(f"request pipe closed: {e}") from e
            budget = self._deadline_s(prepared)
            pcm, end = self._collect(proc, gen, rid, time.monotonic() + budget, budget)
        self._note_end(end)
        return audio_post.process(AudioClip(pcm, self.sample_rate)), float(end.get("synth_ms") or 0.0)

    def _collect(
        self, proc: subprocess.Popen[bytes], gen: int, rid: str, deadline: float, budget: float
    ) -> tuple[bytes, dict[str, Any]]:
        header: dict[str, Any] | None = None
        chunks: list[bytes] = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._kill(proc, f"no answer within {budget:.1f} s")
                raise _WorkerFailure(f"timed out after {budget:.1f} s")
            try:
                g, kind, payload = self._frames.get(timeout=remaining)
            except queue.Empty:
                continue
            if g != gen:
                continue
            if kind is None or kind == "!":
                why = "worker exited" if kind is None else f"malformed frame: {payload[:120]!r}"
                self._kill(proc, why)
                raise _WorkerFailure(why)
            if kind == "A" and header is not None:
                chunks.append(payload)
                continue
            obj = _loads(payload) if kind in ("H", "E", "X") else None
            if kind == "X" and obj is not None and obj.get("id") in (rid, None):
                if obj.get("fatal"):
                    self._kill(proc, f"fatal worker error: {obj.get('error')}")
                raise _WorkerFailure(f"worker error: {obj.get('error')}")
            if obj is None or obj.get("id") != rid:
                self._kill(proc, f"protocol error ({kind!r} frame)")
                raise _WorkerFailure(f"protocol error ({kind!r} frame)")
            if kind == "H":
                if int(obj.get("sample_rate") or 0) != self.sample_rate:
                    self._kill(proc, f"sample rate {obj.get('sample_rate')}")
                    raise _WorkerFailure(f"unexpected sample rate {obj.get('sample_rate')}")
                header = obj
            elif kind == "E" and header is not None:
                pcm = b"".join(chunks)
                return pcm[: len(pcm) & ~1], obj
            else:
                self._kill(proc, f"protocol error ({kind!r} frame)")
                raise _WorkerFailure(f"protocol error ({kind!r} frame)")

    def _note_end(self, end: dict[str, Any]) -> None:
        mem = {k: end.get(k) for k in ("rss_mb", "footprint_mb", "peak_mb", "request_peak_mb")}
        self._memory = {k: float(v) for k, v in mem.items() if isinstance(v, int | float)}
        if "request_peak_mb" in self._memory:
            self._request_peaks.append(self._memory["request_peak_mb"])
        gpl = end.get("gpl_loaded")
        if isinstance(gpl, list) and gpl and self._gpl_free is not False:
            self._gpl_free = False
            log.error("GPL modules were imported in the TTS worker (%s): the worker venv changed", gpl)
        dropped = end.get("dropped")
        if isinstance(dropped, list):
            for word in dropped[:20]:
                w = str(word)[:40]
                if w not in self._dropped:
                    log.warning("kokoro G2P dropped %r (not in the lexicon): add it to voice/data/lexicon.json", w)
                self._dropped[w] += 1
            if len(self._dropped) > 200:
                self._dropped = Counter(dict(self._dropped.most_common(100)))

    def _kill(self, proc: subprocess.Popen[bytes], reason: str) -> None:
        """Take a misbehaving worker down; the supervisor restarts it (with back-off)."""
        self._ready.clear()
        self._last_error = reason
        self._status = "restarting"
        with contextlib.suppress(Exception):
            proc.kill()
        self._wake.set()

    def __repr__(self) -> str:
        return f"WorkerTts(status={self._status!r}, voice={self._voice!r}, speed={self.speed:g})"


def _round(v: float | None) -> float | None:
    return None if v is None else round(v, 1)


def _loads(payload: bytes) -> dict[str, Any] | None:
    try:
        obj = json.loads(payload)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _stop_process(proc: subprocess.Popen[bytes], timeout_s: float) -> None:
    """Ask the worker to exit (stdin closed = EOF), then terminate, then kill."""
    if proc.poll() is None:
        with contextlib.suppress(Exception):
            if proc.stdin is not None:
                proc.stdin.close()
        try:
            proc.wait(timeout_s / 2)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(Exception):
                proc.terminate()
            try:
                proc.wait(timeout_s / 2)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(Exception):
                    proc.kill()
                with contextlib.suppress(Exception):
                    proc.wait(1.0)
    for stream in (proc.stdin, proc.stdout, proc.stderr):
        if stream is not None:
            with contextlib.suppress(Exception):
                stream.close()


# ============================================================================================ spoken-number check
_HOMOPHONES = {
    "breaking": "braking", "break": "brake", "breaks": "brakes", "tires": "tyres", "tire": "tyre",
    "meters": "metres", "meter": "metre", "to": "two", "too": "two", "for": "four",
    "won": "one", "ate": "eight", "boxed": "box", "boxes": "box", "box's": "box", "dont": "don't",
}  # fmt: skip
_OH = frozenset({"oh", "o"})  # zero only next to another number ("one oh five"); "Eau Rouge" is heard "Oh Rouge"
_UNITS = {w: i for i, w in enumerate(("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"))}
_TEENS = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}  # fmt: skip
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_SCALES = {"hundred": 100, "thousand": 1000, "million": 1_000_000}
# Words whose loss or substitution changes an instruction (numbers are checked separately).
KEY_WORDS = frozenset(
    {
        "box", "brake", "braking", "brakes", "lift", "push", "earlier", "later", "plus", "minus", "faster",
        "slower", "left", "right", "front", "rear", "inside", "outside", "stay", "pit", "pits", "yellow", "red",
        "green", "blue", "flag", "safety", "fuel", "tyres", "don't", "not", "no", "gain", "gained", "lose",
        "losing", "lost", "slow", "careful", "overtake", "defend", "mediums", "softs", "hards", "inters",
        "wets", "purple",
    }
)  # fmt: skip
_TOKEN = re.compile(r"\d+(?:[:.]\d+)*|[a-z]+(?:'[a-z]+)?|[,;.!?]")


def _tokens(text: str) -> list[str]:
    toks = [_HOMOPHONES.get(t, t) for t in _TOKEN.findall(text.lower().replace("’", "'").replace("-", " "))]
    for _ in range(2):  # twice: "one oh oh five" / "oh oh five" chain through a neighbouring "oh"
        for i, t in enumerate(toks):
            if t in _OH and any(
                0 <= j < len(toks) and (toks[j][0].isdigit() or _is_number_word(toks[j])) for j in (i - 1, i + 1)
            ):
                toks[i] = "zero"
    return toks


def _starts_number(t: str) -> bool:
    return t in _UNITS or t[0].isdigit()


def _is_number_word(t: str) -> bool:
    return t in _UNITS or t in _TEENS or t in _TENS or t in _SCALES


def _spoken_run(words: list[str]) -> str:
    """Number words of one run -> digits: "one oh five" -> "105", "one hundred and five" -> "105",
    "twenty nine" -> "29", "one twenty nine" -> "129"."""
    words = [w for w in words if w != "and"]
    if any(w in _SCALES for w in words):
        total, current = 0, 0
        for w in words:
            if w in _SCALES:
                scale = _SCALES[w]
                current = max(current, 1) * scale
                if scale >= 1000:
                    total, current = total + current, 0
            else:
                current += _UNITS.get(w, _TEENS.get(w, _TENS.get(w, 0)))
        return str(total + current)
    out: list[str] = []
    i = 0
    while i < len(words):
        w = words[i]
        if w in _TENS and i + 1 < len(words) and words[i + 1] in _UNITS and words[i + 1] != "zero":
            out.append(str(_TENS[w] + _UNITS[words[i + 1]]))
            i += 2
            continue
        out.append(str(_UNITS.get(w, _TEENS.get(w, _TENS.get(w, 0)))))
        i += 1
    return "".join(out)


def spoken_numbers(text: str) -> str:
    """Every number in ``text`` (digits or British number words) as one digit string, ``|`` between runs that
    a word separates (punctuation is ignored: a transcript may or may not put a comma between "lap four" and
    "one oh five")."""
    runs: list[str] = []
    cur: list[str] = []  # pieces of the current run (digit strings or number words)
    words: list[str] = []

    def flush_words() -> None:
        if words:
            cur.append(_spoken_run(words))
            words.clear()

    def flush() -> None:
        flush_words()
        if cur:
            runs.append("".join(cur))
            cur.clear()

    toks = _tokens(text)
    for i, t in enumerate(toks):
        if t[0].isdigit():
            flush_words()
            cur.append(t.replace(":", ""))
        elif _is_number_word(t):
            words.append(t)
        elif t == "point" and (cur or words) and i + 1 < len(toks) and _starts_number(toks[i + 1]):
            flush_words()
            cur.append(".")
        elif t == "and" and words and i + 1 < len(toks) and _is_number_word(toks[i + 1]):
            words.append(t)
        elif t in ",;.!?":
            flush_words()  # a pause, not a word: the digits may still belong together
        else:
            flush()
    flush()
    return "|".join(runs)


def speech_mismatch(expected: str, heard: str) -> str | None:
    """Why ``heard`` (an STT transcript of synthesised audio) does not say ``expected``, or ``None`` if every
    number and key word survived (tts-evaluation section 6.9). Names and filler words are not compared: STT
    cannot spell "Luyendykbocht", and that is not what a misread "thirteen" -> "thirty" looks like."""
    want_n = spoken_numbers(expected).replace("|", "")
    got_n = spoken_numbers(heard).replace("|", "")
    if want_n != got_n:
        return f"numbers {want_n or '-'} heard as {got_n or '-'}"
    want = Counter(t for t in _tokens(expected) if t in KEY_WORDS)
    got = Counter(t for t in _tokens(heard) if t in KEY_WORDS)
    missing = [w for w, n in want.items() if got[w] < n]
    if missing:
        return f"missing {', '.join(sorted(missing))}"
    return None


# ============================================================================================ factory
def _sapi(settings: Settings, sample_rate: int) -> TtsEngine:
    if sys.platform != "win32":
        log.warning("TTS engine 'sapi' needs Windows (running on %s); radio will be text-only", sys.platform)
        return NullTts(reason="'sapi' requires Windows")
    try:
        engine = SapiTts(voice=settings.tts_sapi_voice or None, rate=settings.tts_sapi_rate, sample_rate=sample_rate)
    except Exception as e:  # a broken TTS must never take the app down
        log.warning("Windows speech (SAPI) unavailable (%s); radio will be text-only", e)
        return NullTts(reason=str(e))
    log.info("radio voice: Windows SAPI, %s", engine.voice or "system default voice")
    return engine


def _say(settings: Settings, voice: str, sample_rate: int) -> TtsEngine:
    if sys.platform == "win32":  # `say` is macOS-only: Windows' own voices take its place
        log.debug("TTS engine 'say' is macOS-only; using Windows SAPI voices")
        return _sapi(settings, sample_rate)
    if sys.platform != "darwin":
        log.warning("TTS engine 'say' needs macOS (running on %s); radio will be text-only", sys.platform)
        return NullTts(reason="'say' requires macOS")
    try:
        return SayTts(voice=voice, rate_wpm=settings.tts_rate_wpm, sample_rate=sample_rate)
    except Exception as e:  # a broken TTS must never take the app down
        log.warning("macOS 'say' unavailable (%s); radio will be text-only", e)
        return NullTts(reason=str(e))


def _build_kokoro(settings: Settings, voice_override: str | None = None) -> TtsEngine:
    voice = (voice_override or settings.tts_voice or "").strip()
    fallback_voice = settings.tts_fallback_voice
    if not _KOKORO_VOICE_RE.match(voice):
        # e.g. "Jamie (Premium)" from the say days: keep it as the fallback voice, use the default Kokoro voice
        if voice:
            log.info(
                "tts_voice %r is a macOS voice: the 'say' fallback uses it, Kokoro speaks %s",
                voice,
                KOKORO_DEFAULT_VOICE,
            )
            fallback_voice = voice
        voice = KOKORO_DEFAULT_VOICE
    fallback = _say(settings, fallback_voice, KOKORO_SAMPLE_RATE)
    if sys.platform != "darwin" or platform.machine() != "arm64":
        log.warning("kokoro TTS needs an Apple-silicon Mac; using %s", fallback.name)
        return fallback
    return WorkerTts(
        python=settings.tts_worker_python or venv_python(TTS_HOME / "tts-venv"),
        voice=voice,
        speed=settings.tts_speed,
        model=settings.tts_model,
        revision=settings.tts_model_revision or None,
        lexicon=settings.tts_lexicon or LEXICON_PATH,
        hf_home=settings.tts_hf_home or TTS_HOME / "hf",
        cache_limit_mb=settings.tts_cache_limit_mb,
        fallback=None if isinstance(fallback, NullTts) else fallback,
    )


def build_tts(settings: Settings, voice_override: str | None = None) -> TtsEngine:
    """TTS engine from ``tts_engine`` / ``tts_voice`` / ``tts_speed`` / ``tts_rate_wpm``. Never raises.

    ``kokoro`` gives a ``WorkerTts`` (not yet started: the radio hub starts it) with ``say`` as its fallback; on a
    machine that cannot run it, ``say`` itself - on Windows ``sapi``, which also stands in for ``say``.
    ``voice_override`` (the voice the driver last picked) replaces ``tts_voice`` for kokoro. Anything unusable
    becomes ``NullTts`` (text-only radio).
    """
    engine = settings.tts_engine.strip().lower()
    if engine in ("", "none", "off", "disabled"):
        return NullTts(reason="disabled in settings")
    if engine in ("kokoro", "kokoro-mlx"):
        try:
            return _build_kokoro(settings, voice_override)
        except Exception as e:  # a broken TTS must never take the app down
            log.warning("kokoro TTS unavailable (%s); trying 'say'", e)
            return _say(settings, settings.tts_fallback_voice, DEFAULT_SAMPLE_RATE)
    if engine in ("sapi", "windows"):
        if sys.platform == "win32":
            return _sapi(settings, DEFAULT_SAMPLE_RATE)
        log.warning("TTS engine 'sapi' needs Windows (running on %s); trying 'say'", sys.platform)
        return _say(settings, settings.tts_fallback_voice, DEFAULT_SAMPLE_RATE)
    if engine != "say":
        log.warning(
            "unknown TTS engine %r (expected 'kokoro', 'say', 'sapi' or 'none'); radio will be text-only",
            settings.tts_engine,
        )
        return NullTts(reason=f"unknown engine {settings.tts_engine!r}")
    return _say(settings, settings.tts_voice, DEFAULT_SAMPLE_RATE)
