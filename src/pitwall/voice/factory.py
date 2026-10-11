"""Assembles the radio hub from configuration, degrading gracefully if any voice component is unavailable.

The app must keep working (telemetry, dashboard, typed engineer) even when speech engines cannot load, so
every component has a null fallback: no STT -> typed questions only; no TTS -> text-only radio messages
(and the Kokoro engine has ``say`` as its own fallback).

The server voice the driver picks on the radio page is remembered in ``<data_dir>/radio_voice.json`` and wins
over ``PITWALL_TTS_VOICE`` at the next start.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pitwall.ai.engineer import RaceEngineer
from pitwall.ai.facts import FactSheet, build_fact_sheet
from pitwall.compat import replace_file
from pitwall.config import Settings
from pitwall.core.live import LiveState
from pitwall.core.session_analysis import SessionAnalyzer
from pitwall.drivers import DriverService
from pitwall.motivation.facts import add_motivation_facts  # lane motivation
from pitwall.storage import repo
from pitwall.storage.db import Database
from pitwall.voice.hub import RadioHub
from pitwall.voice.types import AudioClip, SttResult

log = logging.getLogger(__name__)


class _NullStt:
    name = "none"
    reason = "the server's speech recognition failed to load"

    def warmup(self) -> None:
        return None

    def transcribe(self, clip: AudioClip, prompt: str | None = None) -> SttResult:
        return SttResult(text="", engine=self.name, latency_ms=0, audio_s=clip.duration_s)


class _NullTts:
    name = "none"
    sample_rate = 24_000

    def synthesize(self, text: str) -> AudioClip:
        return AudioClip(b"", self.sample_rate)


def build_radio_hub(
    settings: Settings,
    live: LiveState,
    engineer: RaceEngineer,
    db: Database,
    analyzer: SessionAnalyzer,
    drivers: DriverService | None = None,
) -> RadioHub:
    stt: Any = _NullStt()
    tts: Any = _NullTts()
    to_speech: Callable[[str], str] = lambda s: s  # noqa: E731
    lap_messages = None
    try:
        from pitwall.voice.stt import build_stt

        stt = build_stt(settings)
    except Exception:
        log.exception("STT unavailable; radio will accept typed questions only")
    voice_file = settings.data_dir / VOICE_FILE
    try:
        from pitwall.voice.tts import build_tts

        tts = build_tts(settings, voice_override=load_voice_choice(voice_file, settings.tts_engine))
    except Exception:
        log.exception("TTS unavailable; radio messages will be text-only")
    try:
        from pitwall.voice.speech import to_speech as _to_speech

        to_speech = _to_speech
    except Exception:
        log.exception("speech normaliser unavailable")
    from pitwall.voice.scheduler import RadioScheduler

    try:
        from pitwall.voice.proactive import lap_messages as _lap_messages

        lap_messages = _lap_messages
    except Exception:
        log.exception("proactive lap messages unavailable")

    def fact_sheet() -> FactSheet | None:
        if drivers is not None:
            # never answer the seated driver with the previous driver's session
            sid = drivers.session_for_questions(live.session_id)
        else:
            sid = live.session_id
            if sid is None:
                with db.read() as c:
                    sid = repo.latest_session_id(c)
        if sid is None:
            return None
        sa = analyzer.analyse(sid)
        if sa is None:
            return None
        snap = live.snapshot() if live.session_id == sid else None
        sheet = build_fact_sheet(sa, snap)
        add_motivation_facts(sheet, db, sa)  # lane motivation: goals, progress
        return sheet

    return RadioHub(
        live=live,
        engineer=engineer,
        stt=stt,
        tts=tts,
        scheduler=RadioScheduler(settings.coaching_intensity),
        fact_sheet=fact_sheet,
        to_speech=to_speech,
        lap_messages=lap_messages,
        ptt_button=settings.voice_ptt_button,
        max_utterance_s=settings.voice_max_utterance_s,
        cue_mode=settings.cue_mode,
        verify_tts=settings.tts_verify,
        persist_voice=lambda voice: save_voice_choice(voice_file, settings.tts_engine, voice),
    )


VOICE_FILE = "radio_voice.json"


def load_voice_choice(path: Path, engine: str) -> str | None:
    """The voice last picked for this engine, or ``None`` (no file, another engine, unreadable)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("engine") != engine.strip().lower():
        return None
    voice = data.get("voice")
    return voice if isinstance(voice, str) and voice.strip() else None


def save_voice_choice(path: Path, engine: str, voice: str) -> None:
    """Remember the picked voice (atomic replace, so a crash never leaves half a file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"engine": engine.strip().lower(), "voice": voice}), encoding="utf-8")
    replace_file(tmp, path)
