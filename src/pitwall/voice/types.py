"""Shared contracts for the voice subsystem (STT, TTS, radio messages).

Audio everywhere is mono, signed 16-bit little-endian PCM (``AudioClip``). Engines are synchronous and are
called from worker threads by the radio hub, never from the asyncio loop or the telemetry ingest thread.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Protocol

MIC_SAMPLE_RATE = 16_000  # what clients send (resampled on the device)


@dataclass(slots=True, frozen=True)
class AudioClip:
    pcm: bytes  # int16 little-endian mono
    sample_rate: int

    @property
    def n_samples(self) -> int:
        return len(self.pcm) // 2

    @property
    def duration_s(self) -> float:
        return self.n_samples / self.sample_rate if self.sample_rate else 0.0


@dataclass(slots=True, frozen=True)
class SttResult:
    text: str
    engine: str
    latency_ms: int
    audio_s: float


class SttEngine(Protocol):
    name: str

    def warmup(self) -> None:
        """Load models so the first utterance is not slow. May be slow itself; call from a worker thread."""
        ...

    def transcribe(self, clip: AudioClip, prompt: str | None = None) -> SttResult:
        """Blocking transcription of a complete utterance. ``prompt`` = vocabulary hint (corner names...)."""
        ...


class TtsEngine(Protocol):
    name: str
    sample_rate: int

    def synthesize(self, text: str) -> AudioClip:
        """Blocking synthesis of already speech-normalised text."""
        ...


@dataclass(slots=True, frozen=True)
class SynthResult:
    """One synthesis with where it came from (engines that can fall back report it; see ``DetailedTts``)."""

    clip: AudioClip
    engine: str  # what actually produced the audio: "kokoro", "say", "none"...
    neural: bool  # a neural engine rendered it: subject to the spoken-number check (tts-evaluation section 6.9)
    synth_ms: float
    fallback_reason: str | None = None  # why the primary engine did not render it
    checked: bool = False  # the spoken-number check ran on this audio (the hub's ``_verified``)


class DetailedTts(Protocol):
    """Optional ``TtsEngine`` extension for engines with an automatic fallback (``tts.WorkerTts``)."""

    def synthesize_detailed(self, text: str) -> SynthResult:
        """Like ``synthesize``, reporting which engine rendered the audio. Raises like ``synthesize``."""
        ...

    def synthesize_fallback(self, text: str) -> AudioClip:
        """The fallback engine only (``say``), at the primary engine's sample rate."""
        ...


class MessageKind(StrEnum):
    """What a radio message is. The radio policy (``voice.scheduler``: intensity filter, dispatch order, per-lap talk
    budget) is decided by kind; the device shows the kind as the message's label."""

    ANSWER = "answer"  # reply to a driver question
    CONTROL = "control"  # acknowledgement of a control command ("radio quiet for 3 laps")
    CUE = "cue"  # time-critical driving cue (phase 6: predictive braking)
    ALERT = "alert"  # safety/strategy alert (fuel critical, flag, damage)
    LAP_SUMMARY = "lap_summary"  # post-lap summary
    COACHING = "coaching"  # post-lap coaching observation
    INFO = "info"  # low-priority info
    STRATEGY = "strategy"  # race strategy call (pitwall.strategy.radio): normal and detailed intensity
    GOAL = "goal"  # a goal reached (pitwall.motivation.radio): after the lap time, never holding its coaching back
    VALIDATION = "validation"  # a rig validation prompt (pitwall.validate.kit) while the driver runs a validation
    # --- race radio ---
    RACE = "race"  # race situation call (pitwall.raceradio): normal and detailed intensity, own per-lap allowance
    # --- end race radio ---
    SPOTTER = "spotter"  # --- spotter --- cars alongside (pitwall.spotter): pre-synthesised, never queued


class Priority(IntEnum):
    LOW = 10
    NORMAL = 50
    HIGH = 80
    URGENT = 100


@dataclass(slots=True)
class RadioMessage:
    """Something the engineer wants to say. ``text`` is display text; ``speech`` is TTS-normalised text."""

    id: str
    kind: MessageKind
    priority: Priority
    text: str
    speech: str
    created_mono: float  # time.monotonic() at creation
    expires_mono: float | None = None  # drop if not spoken by then (no longer actionable)
    lap_number: int | None = None  # lap the message refers to
    corner: str | None = None
    bypass_quiet: bool = False  # answers/controls/urgent alerts are spoken even in quiet mode
    needs_speak_window: bool = True  # wait for a calm part of the lap (not braking/cornering)
    meta: dict[str, object] = field(default_factory=dict)

    def expired(self, now_mono: float) -> bool:
        return self.expires_mono is not None and now_mono > self.expires_mono


@dataclass(slots=True, frozen=True)
class DrivingState:
    """Minimal live context the scheduler needs to decide whether now is a good moment to talk."""

    on_track: bool  # receiving live telemetry and not paused
    speed_kph: float | None
    brake: float | None
    steering: float | None
    lap_number: int | None
    lap_distance_m: float | None
    # seconds until the next braking zone at current speed (from the track model), None if unknown
    time_to_next_braking_s: float | None
    # --- spotter --- a car alongside now, or a side cleared less than 1 s ago (spotter enabled and active only);
    # proactive messages wait it out (``scheduler.speak_window_ok``). None = unknown / spotter off.
    traffic_alongside: bool | None = None
