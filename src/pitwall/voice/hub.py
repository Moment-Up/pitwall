"""Radio hub: the voice link between the driver's device and the race engineer.

Runs on the asyncio loop. Owns push-to-talk (on-screen or a wheel button via the game's BUTN event), the
half-duplex mic gate, the question pipeline (STT -> engineer -> TTS), proactive messages released by the
``RadioScheduler`` only in safe "speak windows", and per-stage latency measurement.

Blocking work (STT, TTS, fact-sheet building) runs in worker threads. Telemetry callbacks arrive on the ingest
or analysis threads and are marshalled onto the loop with ``call_soon_threadsafe``. Each client has its own
outbound queue, so a slow device can never stall the hub or other clients.

Questions: a fast intent (``FAST_INTENTS``), a question only about data the game never sends, and *every* question
while the car is moving (``MOVING_KPH``) get the deterministic answer at once, with no "Copy, checking." and no LLM.
The LLM explains only when the car is stationary (and in Review › Ask). The radio policy for unprompted messages
(intensity, order, the per-lap talk budget, the seat-change drop) is ``voice.scheduler``'s.

Hands-free talking (``voice.handsfree``, lane handsfree): a device may also talk without a button, starting with a
wake word; ``HandsFreeController`` owns it and the hub calls it from small hooks marked "hands-free (lane handsfree)".

Without a server STT engine (``NullStt``: Parakeet cannot run, or it is switched off) the state carries
``stt_reason``. On Windows (sherpa-onnx not installed, or speech recognition switched off) a push-to-talk utterance
then gets an error frame naming the reason plus a short spoken ``NO_STT_REPLY`` instead of "Say again?". macOS keeps
its behaviour (the utterance goes to ``NullStt``, which hears nothing: "Say again?"). Typed questions, cues and
proactive messages work as usual.

Live braking cues (``coach.cues``) bypass the scheduler queue because they are time-critical:

* **Precise delivery.** The cue engine decides on the ingest thread; the hub delivers on the very next loop turn
  with audio synthesised in advance (``say`` takes ~0.4 s, 33 m at 300 km/h; Kokoro ~0.1-0.2 s). Each phrase is
  built from parts synthesised separately ("turn 9" | 60 ms | "brake") with leading silence trimmed, so audio
  start is speech onset and the key word's offset inside the clip is exact. Parts are cached per spoken text for
  the life of the TTS engine and voice (a corner is synthesised once, not once per lap). Parts the ``say``
  fallback rendered while the Kokoro worker was starting are re-rendered once it is ready and swapped in phrase
  by phrase. Device-voice clients get text only and speak it locally; their key-word offset is estimated from
  spoken words (errs long = early).
* **Spoken-number check** (docs/research/tts-evaluation.md sections 6.8-6.9). Neural audio that is synthesised
  ahead of time - cue parts and proactive messages - is played back through the already-loaded STT; if a number
  or key word does not survive ("thirteen" heard as "thirty") it is re-synthesised once, then rendered by the
  ``say`` fallback. Answers are checked after sending and only logged. Skipped when the STT model is not loaded,
  while the driver transmits, and for urgent calls; never on a cue's delivery path.
* **Latency is measured, not assumed.** Fire -> playback ``started`` is folded into a per-path (server PCM /
  device voice) average and pushed back to the engine. Until measured, the seed is the scheduler's measured
  speech latency minus measured synthesis time (the cue skips synthesis). The device reports ``started`` when
  *it* starts playing; the driver hears it after the output path (Bluetooth HFP to the earbud: 30-60 ms
  [estimate], docs/research/voice-stack.md section 8). ``CUE_OUTPUT_ALLOWANCE_S`` is added to the latency the
  engine times with and to the logged error, so both describe the ear, not the device; a longer delay a device
  reports (``output_latency_s`` on the report) replaces it, a shorter one does not (it may omit the BT link).
  Every ``started`` report logs where the key word was heard versus where it should have been, in metres
  (``cue_timing``).
* **Never late.** The engine predicts the key word lands no later than the reference point and stamps each cue
  with the last moment delivery can start (``CueEvent.deadline_mono``); a cue the loop hands over after that
  (e.g. stalled by a slow request) is dropped. A cue with nothing audible to play (server audio not ready and no
  device voice) is dropped too: it must not cut what is on air for silence.
* **Priority** (as ``voice.scheduler``: urgent > cue > everything else). A cue never plays while the driver
  transmits or while an answer, acknowledgement, urgent call or another cue is on air (answers to the driver's
  own question win); it cuts a proactive message, which is held and said again in the next speak window. An
  answer or acknowledgement that becomes ready while a cue (or an urgent call) is on air waits for it to finish
  instead of cutting the key word. Quiet mode, quiet intensity ("alerts and answers only"), voice off and no
  connected radio mute cues; a muted, late or blocked cue is dropped, never said late. Proactive messages treat
  the next cue like a braking zone: the speak window must close before it fires, and a message whose synthesis
  finished while a cue was playing is held, never cut over it.
* **Spotter calls** (``voice.spotter_radio``, F1 25 only): pre-synthesised, URGENT, delivered on the next loop turn
  like cues; they cut a cue (dropped), a proactive message or an answer (said again once), wait in a one-slot mailbox
  behind another spotter call, an urgent call or the driver's transmission, and reach device-voice iPads as PCM too.
  A clear never cuts a cue (it waits for it), and a cue cuts a clear or a "still there" on air. While a car is
  alongside no speak window opens (``DrivingState.traffic_alongside``).
* **Urgent calls** (the urgent path: the red flag and race-control urgent alerts from ``voice.urgent``, and spotter
  calls) follow ONE rule, ``scheduler.may_interrupt``, wherever the hub decides (its urgent slot, the cue gate,
  ``_yield_to_on_air``) and in ``voice.spotter_radio``: they may interrupt anything except another urgent call, skip
  the speak window, and are never stuck behind anything but the driver's own transmission and another urgent call
  (a red flag waits for a spotter call on air, and a spotter call for the red flag). While the radio talks, holds a
  message for its window or answers a question, the scheduler is polled with ``speaking=True``, which hands out only
  messages that outrank what is on air. An urgent call cuts a cue or a proactive message (the latter is said again
  later). Everything else waits for a free radio, the gap, its speak window and its per-lap allowance.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import itertools
import logging
import math
import statistics
import time
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

from pitwall import games
from pitwall.ai.engineer import CONTROLS_INTENT, EngineerAnswer, RaceEngineer, detect_intent
from pitwall.ai.facts import FactSheet
from pitwall.ai.radio_phrasing import radio_answer
from pitwall.coach.cues import (
    DEFAULT_CUE_MODE,
    MAX_LATENCY_S,
    CueEvent,
    CuePlan,
    CueTiming,
    cue_timing_error_m,
)
from pitwall.compat import is_windows
from pitwall.core.live import LiveState
from pitwall.motivation.radio import GoalLineGate, goal_message  # lane motivation
from pitwall.voice.addressing import NameCaller  # race radio
from pitwall.voice.field_zones import knowledge_model  # race radio: speak windows before a learned model
from pitwall.voice.handsfree import (  # --- hands-free (lane handsfree) ---
    STT_STARTING_REPLY,
    HandsFreeController,
    no_session_sheet,
)
from pitwall.voice.scheduler import (
    DRIVER_INITIATED,
    DRIVER_LAP_KINDS,
    MIN_GAP_S,
    SPEECH_LATENCY_S,
    interrupt_rank,
    is_urgent,
    may_interrupt,
    speak_window_ok,
    spoken_word_count,
)
from pitwall.voice.spotter_radio import SpotterRadio  # --- spotter ---
from pitwall.voice.tts import speech_mismatch
from pitwall.voice.types import (
    MIC_SAMPLE_RATE,
    AudioClip,
    DrivingState,
    MessageKind,
    Priority,
    RadioMessage,
    SttEngine,
    SynthResult,
    TtsEngine,
)
from pitwall.voice.urgent import URGENT_NOTE, urgent_message  # race radio: the urgent path

ONLINE_NAME_REDACTED = "[online name]"  # race radio (raceradio.names.REDACTED): what history and observers keep

if TYPE_CHECKING:
    from pitwall.drivers import CoachingLimits, Driver
    from pitwall.spotter.worker import SpotterWorker  # --- spotter ---

log = logging.getLogger(__name__)

AUDIO_CHUNK_BYTES = 16_384
GATE_TAIL_S = 0.3  # after the device reports playback ended: ignore mic (echo / AirPod output latency)
BARGE_IN_GATE_S = 0.15  # after PTT interrupts playback: long enough for the device to stop, short enough
#                         not to clip the driver's first word
MIN_UTTERANCE_S = 0.35
PLAYBACK_REPORT_GRACE_S = 1.5
DEVICE_TTS_GRACE_S = 3.0  # device voices speak at an unknown rate: allow more slack before assuming it finished
WORDS_PER_S = 2.6
TICK_S = 0.1
DELIVERY_LEAD_S = 0.2  # audio already synthesised: transport + device start-up before it is audible
# Intents whose deterministic answer is already good radio material: answered instantly, no LLM. A question only
# about data the game never sends (games.capability_only: damage in GT7, sectors in Forza, ...) is instant too; the
# same question about a game that sends the data goes to the LLM like any other.
FAST_INTENTS = frozenset(
    {
        "radio_check",
        "control_quiet",
        "control_resume",
        # coachref: drill commands and status, and "who am I compared with?" (deterministic, no LLM)
        "drill_start",
        "drill_status",
        "drill_stop",
        "reference",
        # race strategy (pitwall.strategy) and the session's own facts: deterministic, short radio answers
        "fuel",
        "tyres",
        "strategy",
        "safety_car",
        "gaps",
        "weather",
        "lap_times",
        "last_lap",
        "line",  # feat/technique: deterministic, corner-aware answers (no phraser)
        "technique",
        "balance",
        "drs",  # F2 support: DRS now and the car ahead in DRS range (deterministic)
        "stop_rules",  # F2 support: the race's stop rules are not known (never via the LLM)
        "ai_pace",  # pace vs AI difficulty: radio_phrasing.ai_pace / ai_level
        "ai_level",
        "goals",  # lane motivation: goal facts (plan decision 1), and the week's counts and badges split from it
        "week",
        "badges",
        "controls_where",  # Setup › Controls: "which button is brake bias?" from the saved layout (no session needed)
        # --- race radio --- (raceradio.answers): who's ahead/behind, penalties, damage, sector deltas
        "who_ahead",
        "penalties",
        "damage",
        "sectors",
        "laps_left",
        # --- end race radio ---
        # --- health lane: car health, "where will I come out?", attack / defend (deterministic, instant) ---
        "car_health",
        "rejoin",
        "attack",
        "defend",
        # --- end health lane ---
    }
)
# While the car is moving every answer is deterministic (plan decision 2): with the local LLM at about 15 tokens a
# second on a shared server, an explained answer can take 20 s or more to arrive mid-lap. The LLM still explains
# when the car is stationary, and in Review › Ask. Moving = on track at this speed or more (or speed unknown on
# track); the same threshold as Drive's moving state (web-react lib/drive/motion.ts).
MOVING_KPH = 8.0
NO_GAME_REPLY = "Tell me which game you're playing: open Setup, then Game."
NO_SESSION_REPLY = "No session data yet. Get a lap in and ask me again."

UDP_ACTION_BASE = 0x00100000  # UDP Action 1; Action n = base << (n - 1)  (EA spec appendix: button flags)

# Live braking cues
CUE_PART_GAP_S = 0.06  # silence between separately synthesised parts ("turn 9" | gap | "brake")
CUE_SILENCE_THRESHOLD = 600  # |int16| above this is speech (about -35 dBFS)
CUE_TAIL_PAD_S = 0.02  # kept after a part's last loud sample (no click)
CUE_MAX_HANDOFF_S = 0.25  # absolute cap on fire -> delivery, on top of each cue's own deadline
CUE_OUTPUT_ALLOWANCE_S = 0.05  # device "started" -> in the ear (BT HFP output 30-60 ms [estimate]); a floor
MAX_OUTPUT_LATENCY_S = 0.5  # a device-reported output delay beyond this is not believed
CUE_LATENCY_SMOOTHING = 0.3  # weight of a new fire -> audible measurement
YIELD_POLL_S = 0.02  # an answer waiting for a cue / urgent call on air re-checks this often
RESENT_KEY = "resent"  # meta: how many times a cut proactive message was said again (``_rehold``)
MAX_RESENDS = 1
YIELD_MAX_S = 8.0  # ...and never waits longer than this (a lost "ended" report must not swallow the answer)
CUE_SYNTH_DEFAULT_S = 0.4  # `say` synthesis per call [measured, voice/tts.py]: last resort when an engine
#                            neither measures itself (WorkerTts) nor states a typical time and no part was timed
CUE_DEVICE_PAUSE_S = 0.15  # pause a device voice makes at the comma between parts [estimate; errs early]
CUE_INFLIGHT_TTL_S = 10.0  # forget a cue whose playback was never reported
CUE_AUDIO_CACHE = 128  # parts / phrases kept (a circuit has ~20 corners)
CUE_SYNTH_RETRY_S = 30.0
CUE_TIMING_LOG = 50
VOICE_TEST_PHRASE = "Radio check, loud and clear. Box this lap for mediums."
NO_STT_REPLY = "No voice questions on this server. Type your question instead."  # Windows without server STT
TTS_START_DELAY_S = 2.0  # the Kokoro worker starts this long after the hub (at once when a radio connects), so
#                          short-lived app instances (tests, tools) never spawn it
KEEP_WARM_CHECK_S = 30.0  # while telemetry is live, ask the TTS engine this often whether it needs keeping warm
VERIFY_PAD_S = 0.25  # silence around a clip sent to the STT check (context for very short cue parts)
VERIFY_LOG = 20
CUE_RECHECK_S = 5.0  # cue parts rendered before the STT was loaded: checked once it is, retried this often


BRAKING_ZONE_LEAD_M = 15.0  # the driver may brake a little before the model's reference braking point


def time_to_next_braking(model: dict[str, Any], d: float, speed_kph: float) -> float:
    """Seconds until the next braking zone; 0 while inside one (from just before its braking point to the
    corner exit). A zone the car has only just entered must count as *now*, not as already passed."""
    corners = model.get("corners") or []
    if not corners:
        return float("inf")
    for c in corners:
        if c["entry_m"] - BRAKING_ZONE_LEAD_M <= d <= c["exit_m"]:
            return 0.0
    length = float(model.get("length_m") or 0.0)
    entries = sorted(float(c["entry_m"]) - BRAKING_ZONE_LEAD_M for c in corners)
    ahead = [e for e in entries if e > d] or ([entries[0] + length] if length else [])
    if not ahead:
        return float("inf")
    return (ahead[0] - d) / max(speed_kph / 3.6, 1.0)


def trim_silence(
    clip: AudioClip, threshold: int = CUE_SILENCE_THRESHOLD, tail_pad_s: float = CUE_TAIL_PAD_S
) -> AudioClip:
    """Cut leading silence exactly at speech onset and trailing silence after a short pad, so the clip's start *is*
    its first audible sound (TTS engines pad both ends). A clip with nothing above ``threshold`` is unchanged."""
    n = clip.n_samples
    if n == 0:
        return clip
    x = np.frombuffer(clip.pcm, dtype="<i2", count=n)
    loud = np.flatnonzero(np.abs(x.astype(np.int32)) > threshold)
    if loud.size == 0:
        return clip
    start = int(loud[0])
    end = min(n, int(loud[-1]) + 1 + round(tail_pad_s * clip.sample_rate))
    return AudioClip(x[start:end].tobytes(), clip.sample_rate)


def compose_cue_clip(
    parts: Sequence[AudioClip], key_index: int, gap_s: float = CUE_PART_GAP_S
) -> tuple[AudioClip, float]:
    """Join separately synthesised (already trimmed) parts with short gaps. Returns the clip and the exact start of
    part ``key_index`` in it (s): that is the key word's offset from the start of the audio."""
    if not parts:
        raise ValueError("a cue needs at least one audio part")
    if not 0 <= key_index < len(parts):
        raise ValueError(f"key_index {key_index} out of range for {len(parts)} parts")
    rate = parts[0].sample_rate
    if rate <= 0 or any(p.sample_rate != rate for p in parts):
        raise ValueError("cue parts must share one positive sample rate")
    gap_n = round(gap_s * rate)
    gap = b"\x00\x00" * gap_n
    offset_n = sum(p.n_samples for p in parts[:key_index]) + key_index * gap_n
    pcm = gap.join(p.pcm[: 2 * p.n_samples] for p in parts)
    return AudioClip(pcm, rate), offset_n / rate


type _Ready = tuple[RadioMessage, AudioClip | None, float | None]  # (message, audio, synthesis s; None = no feedback)
# validation kit (lane validate): a radio observer gets (kind, payload), on the loop
type RadioObserver = Callable[[str, dict[str, Any]], None]


_urgent = is_urgent  # the urgent path is the scheduler's (voice.scheduler.may_interrupt): one definition
# a braking cue as the interrupt rule sees it (kind CUE; cues are never urgent)
_CUE_PROBE = RadioMessage(id="", kind=MessageKind.CUE, priority=Priority.HIGH, text="", speech="", created_mono=0.0)


@dataclass(slots=True)
class _CueLatency:
    """Fire -> audible average for one delivery path. The first measurement replaces the seed outright."""

    value: float | None = None
    n: int = 0

    def observe(self, sample: float) -> None:
        self.value = sample if self.value is None else self.value + CUE_LATENCY_SMOOTHING * (sample - self.value)
        self.n += 1


def ptt_action_number(name: str) -> int:
    """'udp_action_N' -> N (validated by ``ptt_button_mask``)."""
    ptt_button_mask(name)
    return int(name[len("udp_action_") :])


def ptt_button_mask(name: str) -> int:
    """'udp_action_1'..'udp_action_12' -> BUTN bit mask."""
    prefix = "udp_action_"
    if not name.startswith(prefix):
        raise ValueError(f"unsupported PTT button {name!r} (use udp_action_1..udp_action_12)")
    n = int(name[len(prefix) :])
    if not 1 <= n <= 12:
        raise ValueError("UDP action must be 1..12")
    return UDP_ACTION_BASE << (n - 1)


@dataclass(slots=True)
class LatencyRecord:
    kind: str  # "question" | "proactive"
    text: str = ""
    audio_s: float = 0.0
    stt_ms: int | None = None
    engineer_ms: int | None = None
    tts_ms: int | None = None
    to_first_audio_ms: int | None = None  # PTT release (or enqueue) -> first audio byte sent
    to_playback_ms: int | None = None  # PTT release -> device reports playback started
    llm: bool = False


@dataclass(eq=False)
class RadioClient:
    send: Callable[[Any], Awaitable[None]]  # sends a dict (JSON) or bytes
    name: str = "device"
    queue: asyncio.Queue[Any] = field(default_factory=lambda: asyncio.Queue(maxsize=512))
    mic_live: bool = False
    device_tts: bool = False  # the device speaks message text itself (e.g. iOS Premium voices); no PCM sent
    voices: list[dict[str, Any]] = field(default_factory=list)  # diagnostic: the device's Web Speech voices
    last_audio_mono: float = 0.0
    task: asyncio.Task[None] | None = None
    dropped: int = 0

    def put(self, item: Any) -> None:
        try:
            self.queue.put_nowait(item)
        except asyncio.QueueFull:
            self.dropped += 1  # a stalled device loses frames; it never blocks the hub

    async def pump(self) -> None:
        while True:
            item = await self.queue.get()
            await self.send(item)


def _session_best_clean_ms(snap: dict[str, Any]) -> int | None:
    """The session's best clean lap time so far, for the lap summary's "personal best" / "session best".

    The snapshot's ``laps`` are only the latest 20 (this lap included), so the session's D2 best from the database
    (``bests.session``: every clean lap of this session, published after each lap) covers the older ones: from lap 21
    on, the best of the last 20 is not the session best when an earlier lap was faster. Either alone while the other
    is missing (D2 waits for the track; it may not include this lap yet)."""
    times = [lap["lap_time_ms"] for lap in snap.get("laps", []) if lap.get("clean") and lap.get("lap_time_ms")]
    session = (snap.get("bests") or {}).get("session") or {}
    d2 = session.get("lap_ms")
    if isinstance(d2, int) and not isinstance(d2, bool) and d2 > 0:
        times.append(d2)
    return min(times, default=None)


class RadioHub:
    def __init__(
        self,
        live: LiveState,
        engineer: RaceEngineer,
        stt: SttEngine,
        tts: TtsEngine,
        scheduler: Any,  # voice.scheduler.RadioScheduler
        fact_sheet: Callable[[], Any],  # blocking: returns a FactSheet for the current session (or None)
        to_speech: Callable[[str], str],
        lap_messages: Callable[..., list[RadioMessage]] | None = None,
        ptt_button: str = "udp_action_1",
        max_utterance_s: float = 12.0,
        cue_mode: str = DEFAULT_CUE_MODE,
        verify_tts: bool = True,
        persist_voice: Callable[[str], None] | None = None,
        handsfree: bool = True,  # --- hands-free (lane handsfree) --- False = PITWALL_VOICE_HANDSFREE=false
    ) -> None:
        self.live = live
        self.engineer = engineer
        self.stt = stt
        self.tts = tts
        self.scheduler = scheduler
        self.fact_sheet = fact_sheet
        self.to_speech = to_speech
        self.lap_messages = lap_messages
        self.ptt_mask = ptt_button_mask(ptt_button)
        # Which UDP Actions wheel push-to-talk listens to: the deploy setting until Setup › Controls hands over the
        # seated driver's F1 25 layout (``set_ptt_actions``; the setting stays as a fallback there).
        self.ptt_actions: list[int] = [ptt_action_number(ptt_button)]
        self.ptt_label: str | None = None
        self._wheel_ptt_paused_until = 0.0  # Setup › Controls button test: wheel presses do not open the radio
        self.max_utterance_s = max_utterance_s
        self.clients: set[RadioClient] = set()
        self.voice_enabled = True
        # the scheduler starts at the configured intensity (settings.coaching_intensity): lap messages and the
        # shared coaching selection (D6) start there too
        start_intensity = getattr(scheduler, "intensity", "normal")
        self.intensity: str = start_intensity if start_intensity in ("quiet", "normal", "detailed") else "normal"
        live.coach.set_radio_intensity(self.intensity)
        self.coaching_limits: CoachingLimits | None = None  # the seated driver's profile (apply_driver)
        self._seat_known = False  # apply_driver has been called (the first call only says who is in the seat)
        self._seated_id: int | None = None
        self._last_coached: dict[str, int] = {}  # corner -> lap last coached, for the current session only
        self._last_coached_sid: str | None = None
        self._goal_lines = GoalLineGate()  # lane motivation: at most 2 goal lines per session
        # --- race radio --- the seated driver's race radio groups (drivers.RadioCallPrefs; None = all on) and name
        self.race_prefs: object | None = None
        self.addresser = NameCaller()
        # --- end race radio ---
        self.ptt_down = False
        self.ptt_source: str | None = None
        self._ptt_client: RadioClient | None = None
        self._buf = bytearray()
        self._ptt_t0 = 0.0
        self.speaking_id: str | None = None
        self._speaking_deadline = 0.0
        self._gate_until = 0.0
        self._ids = itertools.count(1)
        self._busy = False  # a question is being processed
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tick_task: asyncio.Task[None] | None = None
        self._warm = False
        self._last_button_status: int | None = None
        self.latency: deque[LatencyRecord] = deque(maxlen=50)
        self._pending_latency: dict[str, tuple[LatencyRecord, float]] = {}
        self.history: deque[dict[str, Any]] = deque(maxlen=100)
        # synthesised, awaiting a window: (message, audio, synthesis seconds; None = no latency feedback)
        self._held: _Ready | None = None
        # an urgent call waiting only for the driver's transmission or another urgent call to end
        self._held_urgent: _Ready | None = None
        self._air_free_mono = -math.inf  # monotonic time the radio last went silent (the 2 s gap counts from it)
        self._radio_sid: str | None = None  # the live session the scheduler's queue and budgets belong to
        self._dispatched: dict[str, float] = {}  # proactive message id -> dispatch time (latency feedback)
        self._tasks: set[asyncio.Task[Any]] = set()  # strong refs: un-referenced tasks can be GC'd mid-flight
        self._on_air: tuple[RadioMessage, AudioClip | None] | None = None  # last delivered (valid while speaking)
        # live braking cues
        self.cues = live.cues
        self.cues.set_mode(cue_mode)
        self._cue_tts: object | None = None  # engine the audio caches were built with
        self._cue_parts: dict[str, AudioClip] = {}  # spoken text -> trimmed audio
        self._cue_phrases: dict[tuple[str, ...], tuple[AudioClip, float]] = {}  # parts -> (audio, key offset s)
        self._cue_failed: dict[str, float] = {}  # spoken text -> monotonic time synthesis failed
        self._cue_synth_s: deque[float] = deque(maxlen=20)
        self._cue_latency: dict[str, _CueLatency] = {"pcm": _CueLatency(), "device": _CueLatency()}
        # device-reported "started" -> ear delay per path (None = not reported: CUE_OUTPUT_ALLOWANCE_S)
        self._cue_output: dict[str, _CueLatency] = {"pcm": _CueLatency(), "device": _CueLatency()}
        self._cue_inflight: dict[str, CueEvent] = {}  # message id -> cue awaiting its playback report
        self._cue_prep_task: asyncio.Task[None] | None = None
        self._cue_prep_again = False
        self.cue_timing: deque[dict[str, Any]] = deque(maxlen=CUE_TIMING_LOG)
        self._cue_voice: object | None = None  # engine voice the audio caches were built with
        self._cue_part_engine: dict[str, str] = {}  # spoken text -> engine that rendered its cached audio
        self._cue_part_pinned: set[str] = set()  # parts the spoken-number check moved to the fallback voice
        self._cue_part_unchecked: set[str] = set()  # neural parts rendered while the check could not run
        self._cue_fallback_parts: dict[str, AudioClip] = {}  # fallback-voice audio for phrases with a pinned part
        self._cue_recheck_mono = 0.0
        # --- validation kit hooks (lane validate): observers run on the loop and must never raise into the hub ---
        self.observers: list[RadioObserver] = []
        self.command_handler: Callable[[str], str | None] | None = None  # radio commands answered before the engineer
        # --- end validation kit hooks ---
        # TTS engine (voice change, spoken-number check)
        self.verify_tts = verify_tts
        self._persist_voice = persist_voice
        self._tts_seen = self._tts_key()
        self.tts_check: dict[str, int] = dict.fromkeys(
            ("ok", "mismatch", "fixed", "fallback", "skipped", "audited", "audit_mismatch"), 0
        )
        self.tts_check_log: deque[dict[str, Any]] = deque(maxlen=VERIFY_LOG)
        self._tts_start: asyncio.TimerHandle | None = None
        self._tts_started = False
        self._keep_warm_mono = 0.0
        self.handsfree = HandsFreeController(self, enabled=handsfree)  # --- hands-free (lane handsfree) ---
        self.spotter = SpotterRadio(self)  # --- spotter --- delivery, mailbox, heard pairing, phrase audio

    def _spawn(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # --- spotter ---
    def attach_spotter(self, worker: SpotterWorker) -> None:
        """Spotter calls of ``worker`` (the runtime's live worker) are said on this radio (event loop only)."""
        self.spotter.attach(worker)
        self._send_state()

    # --- end spotter ---

    # --- validation kit hooks (lane validate) -------------------------------------------------------------------
    # Observers see what the radio did (docs/architecture.md, "Rig validation kit"). With no observer attached the
    # payload builder is never called: zero cost outside a validation run. Nothing here changes radio behaviour.
    def add_observer(self, fn: RadioObserver) -> None:
        if fn not in self.observers:
            self.observers.append(fn)

    def remove_observer(self, fn: RadioObserver) -> None:
        if fn in self.observers:
            self.observers.remove(fn)

    def _observe(self, kind: str, build: Callable[[], dict[str, Any]]) -> None:
        if not self.observers:
            return
        try:
            payload = build()
        except Exception:
            log.exception("radio observer payload %s failed", kind)
            return
        payload["t_mono"] = time.monotonic()
        payload["t_unix"] = time.time()
        for fn in list(self.observers):
            try:
                fn(kind, payload)
            except Exception:
                log.exception("radio observer failed (%s)", kind)

    def _frame_brief(self) -> dict[str, Any] | None:
        f = self.live.frame
        if f is None:
            return None
        return {
            "lap": f.lap_number,
            "lap_distance_m": f.lap_distance_m,
            "session_time_s": f.session_time_s,
            "speed_kph": f.speed_kph,
            "brake": f.brake,
            "steering": f.steering,
        }

    def _observe_cue(self, ev: CueEvent, status: str, reason: str | None, msg_id: str | None, clip: Any) -> None:
        def build() -> dict[str, Any]:
            engines = (
                {self._cue_part_engine.get(self.to_speech(p)) for p in ev.cue.parts} if clip is not None else set()
            )
            engine = None if not engines or None in engines else (engines.pop() if len(engines) == 1 else "mixed")
            return {
                "seq": ev.seq,
                "status": status,
                "reason": reason,
                "msg_id": msg_id,
                "corner": ev.cue.corner,
                "text": ev.cue.text,
                "kind": ev.cue.kind.value,
                "focus": ev.cue.focus,
                "lap": ev.lap,
                "fired_lap": ev.fired_lap,
                "target_m": ev.cue.target_m,
                "aim_m": ev.aim_m,
                "d_m": ev.d_m,
                "speed_kph": ev.v_mps * 3.6,
                "ttg_s": ev.ttg_s,
                "latency_s": ev.latency_s,
                "word_offset_s": ev.word_offset_s,
                "path": ev.path,
                "ref_lap_id": ev.ref_lap_id,
                "engine": engine,
            }

        self._observe("cue", build)

    async def _validation_command(self, question: str, rec: LatencyRecord, released: float) -> bool:
        """A validation radio command ("next test", "worked"...) answered deterministically before the engineer.
        False when there is no handler or the text is not a command (the engineer answers as usual)."""
        handler = self.command_handler
        if handler is None:
            return False
        try:
            reply = handler(question)
        except Exception:
            log.exception("radio command handler failed")
            reply = None
        if reply is None:
            return False
        msg = self._msg(MessageKind.CONTROL, Priority.HIGH, reply, bypass=True)
        msg.meta = {"intent": "validation", "grounded": True, "fallback": True, "facts": []}
        self.history.appendleft({"role": "engineer", "text": reply, "t": time.time()})
        self._observe("command", lambda: {"msg_id": msg.id, "question": question, "text": reply})
        await self.say(msg, rec, released)
        return True

    # --- end validation kit hooks -------------------------------------------------------------------------------

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self.live.subscribe(self._on_live_note)
        self.live.subscribe_buttons(self._on_button_threadsafe)
        self.cues.set_plan_listener(self._on_cue_plan_threadsafe)
        self.cues.set_sink(self._on_cue_threadsafe)
        self._cue_clients_changed()
        self._tick_task = asyncio.create_task(self._tick_loop(), name="radio-tick")
        if callable(getattr(self.tts, "start", None)):
            self._tts_start = self._loop.call_later(TTS_START_DELAY_S, self._start_tts)

    def _start_tts(self) -> None:
        """Launch an engine that runs in the background (``WorkerTts``: the Kokoro worker). Idempotent."""
        if self._tts_start is not None:
            self._tts_start.cancel()
            self._tts_start = None
        if self._tts_started:
            return
        self._tts_started = True
        start = getattr(self.tts, "start", None)
        if callable(start):
            try:
                start()
            except Exception:
                log.exception("TTS engine %s failed to start; its fallback speaks", self.tts.name)

    async def stop(self) -> None:
        self.handsfree.close()  # --- hands-free (lane handsfree) ---
        self.spotter.detach()  # --- spotter ---
        self.live.unsubscribe(self._on_live_note)
        self.live.unsubscribe_buttons(self._on_button_threadsafe)
        self.cues.set_sink(None)
        self.cues.set_plan_listener(None)
        if self._cue_prep_task is not None:
            self._cue_prep_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._cue_prep_task
        if self._tick_task:
            self._tick_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._tick_task
        for c in list(self.clients):
            await self.disconnect(c)
        if self._tts_start is not None:
            self._tts_start.cancel()
            self._tts_start = None
        close = getattr(self.tts, "close", None)
        if self._tts_started and callable(close):
            with contextlib.suppress(Exception):
                await asyncio.to_thread(close)

    async def warmup(self) -> None:
        if self._warm:
            return
        self._warm = True
        t0 = time.perf_counter()
        try:
            await asyncio.to_thread(self.stt.warmup)
            log.info("STT %s warm in %.1f s", self.stt.name, time.perf_counter() - t0)
        except Exception:
            log.exception("STT warmup failed")

    # ------------------------------------------------------------------ clients
    async def connect(self, client: RadioClient) -> None:
        if self._tts_start is not None:
            self._start_tts()  # a radio is here: the natural voice is wanted now
        self.clients.add(client)
        client.task = asyncio.create_task(client.pump(), name=f"radio-client-{client.name}")
        self._cue_clients_changed()
        self._send_state()
        self._spawn(self.warmup())

    async def disconnect(self, client: RadioClient) -> None:
        self.clients.discard(client)
        self.handsfree.forget(client)  # --- hands-free (lane handsfree) ---
        self._cue_clients_changed()
        if client.task:
            client.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await client.task
        if self._ptt_client is client and self.ptt_down:
            self._ptt_up(source="disconnect")

    def _broadcast(self, item: Any) -> None:
        for c in self.clients:
            c.put(item)

    def state(self) -> dict[str, Any]:
        lap = self.live.frame.lap_number if self.live.frame else None
        quiet = self.scheduler.quiet_state(lap) if hasattr(self.scheduler, "quiet_state") else {}
        return {
            "type": "state",
            "ptt": self.ptt_down,
            "listening": self.ptt_down or self.handsfree.capturing,  # --- hands-free (lane handsfree) ---
            "speaking": self.speaking_id is not None,
            "busy": self._busy,
            "quiet": quiet,
            "intensity": self.intensity,
            "voice_enabled": self.voice_enabled,
            "stt": self.stt.name,
            "stt_reason": self._stt_unavailable(),
            "tts": self.tts.name,
            **self._tts_state(),
            "telemetry": self.live.connection()["status"],
            "ptt_source": self.ptt_source,
            "ptt_actions": list(self.ptt_actions),  # additive: the UDP Actions wheel push-to-talk listens to
            "ptt_label": self.ptt_label,  # additive: the control's name in the seated driver's layout, if known
            "wheel_ptt_paused": self.wheel_ptt_paused(),
            "clients": len(self.clients),
            "cue_mode": self.cues.mode,
            "handsfree": self.handsfree.state(),  # --- hands-free (lane handsfree) ---
            "spotter": self.spotter.state_block(),  # --- spotter ---
        }

    def _send_state(self) -> None:
        self._broadcast(self.state())

    # ------------------------------------------------------------------ inbound from devices
    async def on_text(self, client: RadioClient, msg: dict[str, Any]) -> None:
        t = msg.get("type")
        if t == "hello":
            client.name = str(msg.get("client") or client.name)[:32]
            if "tts_mode" in msg:
                client.device_tts = msg.get("tts_mode") == "device"
                self._cue_clients_changed()
            client.put(self.state())
        elif t == "ptt":
            # --- hands-free (lane handsfree) --- "remote": a learned Bluetooth button
            source = "remote" if msg.get("source") == "remote" else "screen"
            if msg.get("down"):
                self._ptt_down_now(source=source, client=client)
            else:
                self._ptt_up(source=source)
        elif t == "vad":  # --- hands-free (lane handsfree) ---
            self.handsfree.on_vad(client, msg)
        elif t == "playback":
            self._on_playback(str(msg.get("id")), str(msg.get("state")), client, _output_latency(msg))
        elif t == "stop_tts":
            self._cancel_speaking()
        elif t == "ask":
            self.ask_text(str(msg.get("text") or ""))
        elif t == "test_voice":  # radio page "Test voice": the server voice says a phrase on every radio
            text = str(msg.get("text") or "").strip()[:200] or VOICE_TEST_PHRASE
            self._spawn(self.say(self._msg(MessageKind.INFO, Priority.HIGH, text, bypass=True), None, None))
        elif t == "settings":
            if "tts_mode" in msg:
                client.device_tts = msg.get("tts_mode") == "device"
            if "voice_enabled" in msg:
                self.voice_enabled = bool(msg["voice_enabled"])
            if msg.get("intensity") in ("quiet", "normal", "detailed"):
                self._set_intensity(str(msg["intensity"]))
            if "cue_mode" in msg:
                try:
                    self.cues.set_mode(str(msg["cue_mode"]))
                except ValueError as e:
                    client.put({"type": "error", "message": str(e)})
            if "tts_voice" in msg:
                try:
                    self.set_tts_voice(str(msg["tts_voice"]))
                except ValueError as e:
                    client.put({"type": "error", "message": str(e)})
            if "handsfree" in msg or "wake_word" in msg:  # --- hands-free (lane handsfree) --- per device
                err = self.handsfree.configure(client, msg)
                if err is not None:
                    client.put({"type": "error", "message": err})
            self._cue_clients_changed()
            self._send_state()
        elif t == "voices":  # diagnostic report of the voices the device's browser exposes
            raw = msg.get("voices")
            if isinstance(raw, list):
                client.voices = [
                    {k: str(v.get(k, ""))[:80] for k in ("name", "lang", "uri", "local", "default")}
                    for v in raw[:400]
                    if isinstance(v, dict)
                ]
                log.info("%s exposes %d speech voices", client.name, len(client.voices))
        elif t == "ping":
            client.put({"type": "pong", "t": msg.get("t"), "server_ms": int(time.time() * 1000)})

    def ask_text(self, text: str) -> None:
        """A typed question answered over the radio (no STT)."""
        text = text.strip()[:300]
        if text:
            self._spawn(self._answer(text, LatencyRecord(kind="question", text=text), time.monotonic()))

    def on_audio(self, client: RadioClient, data: bytes) -> None:
        now = time.monotonic()
        client.mic_live = True
        client.last_audio_mono = now
        self.handsfree.on_audio(client, data, now)  # --- hands-free (lane handsfree) --- (unarmed: discarded)
        if not self.ptt_down:
            return  # not listening: discard (never stored)
        if self._ptt_client is not None and client is not self._ptt_client:
            return
        if self._ptt_client is None:
            self._ptt_client = client  # wheel PTT: first device that streams audio
        if now < self._gate_until or self.speaking_id is not None:
            return  # half-duplex gate
        if len(data) % 2:
            data = data[:-1]
        self._buf.extend(data)
        if len(self._buf) / 2 / MIC_SAMPLE_RATE >= self.max_utterance_s:
            self._ptt_up(source="max_length")

    # ------------------------------------------------------------------ push-to-talk
    def _ptt_down_now(self, source: str, client: RadioClient | None) -> None:
        if self.ptt_down:
            return
        self.handsfree.abort("ptt", source)  # --- hands-free (lane handsfree) --- push-to-talk wins
        if self.speaking_id is not None:
            self._cancel_speaking()  # barge-in
            self._gate_until = time.monotonic() + BARGE_IN_GATE_S
        self.ptt_down = True
        self.ptt_source = source
        self._ptt_client = client if client is not None else self._audio_client()
        self._buf = bytearray()
        self._ptt_t0 = time.monotonic()
        self._send_state()

    def _ptt_up(self, source: str) -> None:
        if not self.ptt_down:
            return
        self.ptt_down = False
        clip = AudioClip(bytes(self._buf), MIC_SAMPLE_RATE)
        self._buf = bytearray()
        self._ptt_client = None
        released = time.monotonic()
        self._send_state()
        self.spotter.on_ptt_up()  # --- spotter --- a call held while the driver transmitted
        if clip.duration_s < MIN_UTTERANCE_S:
            return
        self._spawn(self._handle_utterance(clip, released))

    def _audio_client(self) -> RadioClient | None:
        live = [c for c in self.clients if c.mic_live]
        return max(live, key=lambda c: c.last_audio_mono) if live else None

    def _on_button_threadsafe(self, status: int) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._on_button, status)

    def set_ptt_actions(self, actions: Sequence[int], label: str | None = None) -> None:
        """Listen to these UDP Actions for wheel push-to-talk (Setup › Controls, on the loop). A held wheel
        transmission whose button is no longer one of them ends."""
        mask = 0
        kept: list[int] = []
        for n in actions:
            if isinstance(n, int) and 1 <= n <= 12 and n not in kept:
                kept.append(n)
                mask |= UDP_ACTION_BASE << (n - 1)
        if not mask:
            return  # never leave the radio with no wheel button at all
        self.ptt_mask = mask
        self.ptt_actions = kept
        self.ptt_label = label
        if self.ptt_down and self.ptt_source == "wheel" and not ((self._last_button_status or 0) & mask):
            self._ptt_up(source="wheel")
        self._send_state()

    def suspend_wheel_ptt(self, on: bool, for_s: float = 15.0) -> None:
        """Pause wheel push-to-talk while Setup › Controls tests buttons (re-armed by the test while the page polls;
        it lapses on its own ``for_s`` after the last call, so a closed page never leaves the radio deaf)."""
        self._wheel_ptt_paused_until = time.monotonic() + for_s if on else 0.0
        if on and self.ptt_down and self.ptt_source == "wheel":
            self._ptt_up(source="wheel")
        self._send_state()

    def wheel_ptt_paused(self) -> bool:
        return time.monotonic() < self._wheel_ptt_paused_until

    def _on_button(self, status: int) -> None:
        if self.wheel_ptt_paused():
            self._last_button_status = status
            return
        pressed = bool(status & self.ptt_mask)
        was = bool((self._last_button_status or 0) & self.ptt_mask)
        self._last_button_status = status
        if pressed and not was:
            self._ptt_down_now(source="wheel", client=None)
        elif was and not pressed:
            self._ptt_up(source="wheel")

    # ------------------------------------------------------------------ question pipeline
    def _stt_unavailable(self) -> str | None:
        """Why the server cannot transcribe the driver (no STT engine: Windows, or switched off), else ``None``."""
        if self.stt.name != "none":
            return None
        reason = getattr(self.stt, "reason", None)
        return str(reason) if reason else "no speech recognition engine on the server"

    async def _handle_utterance(self, clip: AudioClip, released: float) -> None:
        unavailable = self._stt_unavailable() if is_windows() else None  # macOS: unchanged ("Say again?")
        if unavailable is not None:
            # Not "Say again?": repeating cannot help. Say so once per press, and how to ask instead.
            self._broadcast({"type": "error", "message": f"Voice questions are unavailable: {unavailable}."})
            await self.say(
                self._msg(MessageKind.CONTROL, Priority.HIGH, NO_STT_REPLY, bypass=True),
                None,
                released,
            )
            return
        rec = LatencyRecord(kind="question", audio_s=round(clip.duration_s, 2))
        try:
            res = await asyncio.to_thread(self.stt.transcribe, clip, None)
        except Exception as e:
            log.exception("STT failed")
            self._broadcast({"type": "error", "message": f"speech recognition failed: {e}"})
            if getattr(self.stt, "loaded", True) is False:  # --- hands-free (lane handsfree) --- model still starting
                await self.say(
                    self._msg(MessageKind.CONTROL, Priority.HIGH, STT_STARTING_REPLY, bypass=True), None, released
                )
            return
        rec.stt_ms = res.latency_ms
        rec.text = res.text
        self._broadcast(
            {"type": "transcript", "text": res.text, "stt_ms": res.latency_ms, "audio_s": round(clip.duration_s, 2)}
        )
        self._observe(  # validation kit hook
            "transcript",
            lambda: {"text": res.text, "stt_ms": res.latency_ms, "audio_s": rec.audio_s, "ptt_source": self.ptt_source},
        )
        self.history.appendleft({"role": "driver", "text": res.text, "t": time.time()})
        if not res.text.strip():
            await self.say(self._msg(MessageKind.CONTROL, Priority.HIGH, "Say again?", bypass=True), rec, released)
            return
        await self._answer(res.text, rec, released)

    async def _answer(self, question: str, rec: LatencyRecord, released: float) -> None:
        if self._busy:
            await self.say(
                self._msg(MessageKind.CONTROL, Priority.HIGH, "Stand by, still on the last one.", bypass=True),
                None,
                None,
            )
            return
        self._busy = True
        self._send_state()
        try:
            if await self._validation_command(question, rec, released):  # validation kit: radio commands first
                return
            intent = detect_intent(question)
            # the game the data comes from (live session, else the selection): a question only about data it never
            # sends is answered from what Pitwall knows about the game - no LLM, no "Copy, checking."
            entry = games.entry(self.live.effective_game_id())
            cap = games.capability_only(intent.name, entry)
            use_llm = intent.name not in FAST_INTENTS and not cap and not self.moving()
            if use_llm:
                # real engineers acknowledge immediately; the LLM answer takes several seconds
                await self.say(
                    self._msg(MessageKind.CONTROL, Priority.HIGH, "Copy, checking.", bypass=True), None, None
                )
            t0 = time.perf_counter()
            sheet = await asyncio.to_thread(self.fact_sheet)
            if sheet is None and intent.name == CONTROLS_INTENT:
                sheet = FactSheet()  # the saved button layout answers it, before the first lap too
            if sheet is None and cap and entry is not None:
                sheet = games.capability_sheet(entry)  # no session yet: the game's capabilities are still known
            if sheet is None:  # --- hands-free (lane handsfree) --- a radio check / quiet / resume needs no session
                sheet = no_session_sheet(intent)
            no_game = False
            if sheet is None:
                no_game = entry is None and intent.name in games.CAPABILITY_ONLY_INTENTS
                ans_text, ans = (NO_GAME_REPLY if no_game else NO_SESSION_REPLY), None
            else:
                # short: a deterministic radio answer is one or two facts, never a list read out at speed
                ans = await self.engineer.answer(question, sheet, use_llm=use_llm, short=True)
                ans_text = ans.text
                if not use_llm:
                    short = radio_answer(intent.name, sheet, question)  # engineer-style phrasing for instant answers
                    if short:
                        ans_text = short
            # --- race radio (raceradio.names): an online name in a "who's ahead?" answer, opt-in, never kept ---
            personal = None if sheet is None or use_llm else self._online_name_answer(intent.name, question, sheet)
            if personal is not None:
                ans_text = personal[0]
            logged = ans_text if personal is None else ans_text.replace(personal[1], ONLINE_NAME_REDACTED)
            # --- end race radio ---
            rec.engineer_ms = int((time.perf_counter() - t0) * 1000)
            rec.llm = bool(ans and not ans.fallback and ans.model)
            self._apply_control(ans)
            kind = MessageKind.CONTROL if (ans and ans.control) or no_game else MessageKind.ANSWER
            msg = self._msg(kind, Priority.HIGH, ans_text, bypass=True)
            if ans is not None and ans.intent == CONTROLS_INTENT:
                msg.speech = self.to_speech(ans.speech)  # "+" and "−" as words
            if ans is not None:
                msg.meta = {
                    "intent": ans.intent,
                    "grounded": ans.grounded,
                    "fallback": ans.fallback,
                    "facts": [f["id"] for f in ans.facts],
                }
            if personal is not None:
                msg.meta["personal"] = True  # race radio: kept out of history, observers, the audit and neural TTS
            self.history.appendleft({"role": "engineer", "text": logged, "t": time.time()})
            self._observe(  # validation kit hook
                "answer",
                lambda: {
                    "msg_id": msg.id,
                    "question": question,
                    "text": logged,
                    "intent": ans.intent if ans is not None else intent.name,
                    "grounded": ans.grounded if ans is not None else None,
                    "fallback": ans.fallback if ans is not None else True,
                    "llm": rec.llm,
                    "use_llm": use_llm,
                    "engineer_ms": rec.engineer_ms,
                },
            )
            await self.say(msg, rec, released)
        finally:
            self._busy = False
            self._send_state()

    def moving(self) -> bool:
        """The car is on track and moving (``MOVING_KPH``): answers are deterministic, never the LLM. On track with
        an unknown speed counts as moving (unknown is not stationary)."""
        state = self.driving_state()
        if not state.on_track:
            return False
        speed = state.speed_kph
        return speed is None or not (math.isfinite(speed) and speed < MOVING_KPH)

    def _apply_control(self, ans: EngineerAnswer | None) -> None:
        if ans is None or not ans.control:
            return
        lap = self.live.frame.lap_number if self.live.frame else None
        if ans.control.get("action") == "quiet":
            laps = ans.control.get("laps")
            if isinstance(laps, int) and lap is not None:
                self.scheduler.set_quiet(until_lap=lap + laps, indefinite=False)
            else:
                self.scheduler.set_quiet(until_lap=None, indefinite=True)
        elif ans.control.get("action") == "resume":
            self.scheduler.resume()

    # ------------------------------------------------------------------ speaking
    def _msg(self, kind: MessageKind, prio: Priority, text: str, bypass: bool = False) -> RadioMessage:
        return RadioMessage(
            id=f"m{next(self._ids)}",
            kind=kind,
            priority=prio,
            text=text,
            speech=self.to_speech(text),
            created_mono=time.monotonic(),
            bypass_quiet=bypass,
            needs_speak_window=False,
        )

    async def say(self, msg: RadioMessage, rec: LatencyRecord | None, released: float | None) -> None:
        """Synthesise (if any device needs PCM) and deliver a message to every device. A non-urgent message waits
        for a cue or urgent call on air to finish rather than cut it (``_yield_to_on_air``)."""
        if not self.voice_enabled and msg.kind not in (MessageKind.ANSWER, MessageKind.CONTROL):
            return
        t0 = time.perf_counter()
        res = await self._synthesize_result(msg)
        clip = None if res is None else res.clip
        if rec is not None:
            rec.tts_ms = int((time.perf_counter() - t0) * 1000)
        await self._yield_to_on_air(msg)
        self._deliver(msg, clip, rec, released)
        personal = msg.meta.get("personal") is True  # race radio: an online name is never kept by the audit's log
        if res is not None and res.neural and res.clip.pcm and self._can_verify() and not personal:
            self._spawn(self._audit(msg.speech, res))  # answers are not held back: checked after sending

    async def _yield_to_on_air(self, msg: RadioMessage) -> None:
        """Wait while a cue or an urgent call is on air and ``msg`` does not outrank it.

        A cue is about one second and time-critical (its key word marks the braking point); an answer or "Copy,
        checking." can wait that second, while cutting the cue would lose the call entirely. Bounded by the on-air
        message's own speaking deadline (the tick clears it if the device never reports the end) and by
        ``YIELD_MAX_S``."""
        if _urgent(msg):
            return
        limit = time.monotonic() + YIELD_MAX_S
        while True:
            on_air = self._on_air_message()
            # wait for anything that outranks ``msg`` (a cue, an urgent call) and for any spotter clip
            if on_air is None or not (
                on_air[0].kind is MessageKind.SPOTTER or interrupt_rank(on_air[0]) > interrupt_rank(msg)
            ):
                return
            if time.monotonic() >= min(limit, self._speaking_deadline):
                return
            await asyncio.sleep(YIELD_POLL_S)

    async def _synthesize(self, msg: RadioMessage, verify: bool = False) -> AudioClip | None:
        res = await self._synthesize_result(msg, verify)
        return None if res is None else res.clip

    async def _synthesize_result(self, msg: RadioMessage, verify: bool = False) -> SynthResult | None:
        """Audio for a message if any device needs PCM (``None`` = text only). ``verify``: the message is said
        ahead of time (proactive), so neural audio gets the spoken-number check before it goes out."""
        audio_needed = any(not c.device_tts for c in self.clients) or not self.clients
        if not msg.speech.strip() or not audio_needed:
            return None
        fallback = getattr(self.tts, "synthesize_fallback", None)
        if msg.meta.get("personal") is True and callable(fallback):  # race radio: the neural engine logs dropped words
            try:
                t0 = time.perf_counter()
                clip = await asyncio.to_thread(fallback, msg.speech)
                return SynthResult(clip, "say", False, (time.perf_counter() - t0) * 1000.0)
            except Exception:
                log.exception("fallback TTS failed; sending text only")
                return None
        try:
            res = await asyncio.to_thread(self._synth_detailed, msg.speech)
        except Exception:
            log.exception("TTS failed; sending text only")
            return None
        if verify:
            res = await self._verified(msg.speech, res, msg.kind.value)
        self._observe(  # validation kit hook
            "synth",
            lambda: {
                "msg_id": msg.id,
                "kind": msg.kind.value,
                "engine": res.engine,
                "neural": res.neural,
                "synth_ms": res.synth_ms,
                "fallback_reason": res.fallback_reason,
            },
        )
        return res

    # ------------------------------------------------------------------ TTS engine: voice, check, diagnostics
    def _synth_detailed(self, text: str) -> SynthResult:
        """Blocking (worker thread). Engines with a fallback say which engine rendered the audio."""
        detailed = getattr(self.tts, "synthesize_detailed", None)
        if callable(detailed):
            res = detailed(text)
            if isinstance(res, SynthResult):
                return res
        t0 = time.perf_counter()
        clip = self.tts.synthesize(text)
        neural = bool(getattr(self.tts, "neural", False))
        return SynthResult(clip, self.tts.name, neural, (time.perf_counter() - t0) * 1000.0)

    def _tts_key(self) -> tuple[object, object]:
        return getattr(self.tts, "active", None), getattr(self.tts, "voice", None)

    def _tts_state(self) -> dict[str, Any]:
        voices = getattr(self.tts, "voices", None)
        return {
            "tts_voice": getattr(self.tts, "voice", None),
            "tts_voices": [str(v) for v in voices] if isinstance(voices, list | tuple) else [],
            "tts_active": getattr(self.tts, "active", self.tts.name),
            "tts_ready": bool(getattr(self.tts, "ready", True)),
            "tts_neural": bool(getattr(self.tts, "neural", False)),
            "tts_status": getattr(self.tts, "status", None),
        }

    def set_tts_voice(self, voice: str) -> str:
        """Switch the server voice for every following message (cue audio is rebuilt for it). Returns the voice
        now in use; raises ``ValueError`` for an unknown voice or an engine without selectable voices."""
        setter = getattr(self.tts, "set_voice", None)
        if not callable(setter):
            raise ValueError(f"the {self.tts.name} voice engine has no selectable voices")
        setter(voice)
        now = str(getattr(self.tts, "voice", voice))
        if self._persist_voice is not None:
            try:
                self._persist_voice(now)
            except Exception:
                log.exception("could not save the radio voice choice")
        self._tts_seen = self._tts_key()
        self._cue_clients_changed()  # retime and rebuild cue audio in the new voice
        self.spotter.on_tts_changed()  # --- spotter --- phrases in the new voice
        self._send_state()
        return now

    def _check_tts_engine(self, now: float) -> None:
        """The engine came up, went down or changed voice: tell the radios, retime cues and (re)build their audio.
        While a session is live, an engine that has sat idle for minutes is kept warm (``WorkerTts.keep_warm``)."""
        key = self._tts_key()
        if key != self._tts_seen:
            self._tts_seen = key
            self._send_state()
            self._push_cue_timing()
            self._request_cue_audio()
            self.spotter.on_tts_changed()  # --- spotter ---
        if self._cue_part_unchecked and now - self._cue_recheck_mono >= CUE_RECHECK_S and self._can_verify():
            self._cue_recheck_mono = now  # the STT is up now: check the parts rendered before it was
            self._request_cue_audio()
        keep_warm = getattr(self.tts, "keep_warm", None)
        if callable(keep_warm) and now - self._keep_warm_mono >= KEEP_WARM_CHECK_S:
            self._keep_warm_mono = now
            if self.live.connection()["status"] == "live":
                self._spawn(asyncio.to_thread(keep_warm))

    def _can_verify(self) -> bool:
        return (
            self.verify_tts
            and getattr(self.stt, "loaded", False) is True
            and not self.ptt_down
            and callable(getattr(self.tts, "synthesize_fallback", None))
        )

    async def _heard(self, clip: AudioClip) -> str | None:
        """What the STT hears in a synthesised clip; ``None`` if it could not run."""
        pad = b"\x00\x00" * round(VERIFY_PAD_S * clip.sample_rate)
        try:
            res = await asyncio.to_thread(self.stt.transcribe, AudioClip(pad + clip.pcm + pad, clip.sample_rate), None)
        except Exception as e:
            log.debug("tts check skipped: STT failed (%s)", e)
            return None
        return res.text

    def _note_check(self, what: str, speech: str, heard: str, why: str, outcome: str) -> None:
        self.tts_check_log.appendleft(
            {"t": time.time(), "what": what, "text": speech, "heard": heard, "why": why, "outcome": outcome}
        )
        log.warning("tts check (%s): %r heard as %r (%s): %s", what, speech, heard, why, outcome)

    async def _verified(self, speech: str, res: SynthResult, what: str) -> SynthResult:
        """Spoken-number check of neural audio said ahead of time: re-synthesise once on a mismatch, then use the
        fallback voice. Audio that cannot be checked (STT not loaded, driver transmitting) goes out as it is."""
        if not res.neural or not res.clip.pcm:
            return res
        if not self._can_verify():
            self.tts_check["skipped"] += 1
            return res
        heard = await self._heard(res.clip)
        if heard is None:
            self.tts_check["skipped"] += 1
            return res
        why = speech_mismatch(speech, heard)
        if why is None:
            self.tts_check["ok"] += 1
            return dataclasses.replace(res, checked=True)
        self.tts_check["mismatch"] += 1
        try:
            again: SynthResult | None = await asyncio.to_thread(self._synth_detailed, speech)
        except Exception:
            again = None
        if again is not None and again.clip.pcm:
            if not again.neural:
                return again  # the worker went down meanwhile: its fallback rendered it
            heard2 = await self._heard(again.clip)
            if heard2 is not None and speech_mismatch(speech, heard2) is None:
                self.tts_check["fixed"] += 1
                self._note_check(what, speech, heard, why, "fixed by re-synthesis")
                return dataclasses.replace(again, checked=True)
        fallback = getattr(self.tts, "synthesize_fallback", None)
        if callable(fallback):
            try:
                clip = await asyncio.to_thread(fallback, speech)
            except Exception as e:
                log.warning("tts check: fallback voice failed (%s); keeping the neural audio", e)
            else:
                if isinstance(clip, AudioClip) and clip.pcm:
                    self.tts_check["fallback"] += 1
                    self._note_check(what, speech, heard, why, "fallback voice")
                    fb_name = str(getattr(self.tts, "fallback_name", None) or "say")
                    return SynthResult(clip, fb_name, False, res.synth_ms, f"spoken-number check: {why}", True)
        self._note_check(what, speech, heard, why, "sent as rendered")
        return dataclasses.replace(res, checked=True)

    async def _audit(self, speech: str, res: SynthResult) -> None:
        """After-the-fact check of an answer (never delays it): logged for diagnostics only."""
        heard = await self._heard(res.clip)
        if heard is None:
            return
        self.tts_check["audited"] += 1
        why = speech_mismatch(speech, heard)
        if why is not None:
            self.tts_check["audit_mismatch"] += 1
            self._note_check("answer, after sending", speech, heard, why, "logged")

    def _engine_synth_s(self) -> float:
        """Whole-message synthesis time of the engine speaking now (s): its own measurement (``WorkerTts``: the
        median of recent worker calls), else the hub's timing of cue parts, else the engine's typical figure,
        else ``CUE_SYNTH_DEFAULT_S``."""
        measured = getattr(self.tts, "measured_synth_s", None)
        if callable(measured):
            v = measured()
            if isinstance(v, int | float) and math.isfinite(v) and v >= 0:
                return float(v)
        if self._cue_synth_s:
            return statistics.median(self._cue_synth_s)
        typical = getattr(self.tts, "typical_synth_s", CUE_SYNTH_DEFAULT_S)
        return float(typical) if isinstance(typical, int | float) else CUE_SYNTH_DEFAULT_S

    def _speech_duration(self, msg: RadioMessage, clip: AudioClip | None) -> float:
        if clip is not None and clip.pcm:
            return clip.duration_s
        return max(1.0, len(msg.speech.split()) / WORDS_PER_S)

    def _deliver(
        self,
        msg: RadioMessage,
        clip: AudioClip | None,
        rec: LatencyRecord | None,
        released: float | None,
        *,
        pcm_to_all: bool = False,  # --- spotter --- device-voice clients get the clip too (they play any PCM)
    ) -> None:
        """Send a message: PCM for audio devices, text for devices that speak it themselves."""
        has_speech = bool(msg.speech.strip())
        all_pcm = pcm_to_all and clip is not None and bool(clip.pcm)  # --- spotter ---
        audio_clients = [c for c in self.clients if not c.device_tts or all_pcm]
        device_clients = [c for c in self.clients if c.device_tts and not all_pcm]
        n_bytes = len(clip.pcm) if clip else 0
        cancelled_id = self.speaking_id  # validation kit: what this message cuts, if anything
        if self.speaking_id is not None:
            self._cancel_speaking()  # newest high-priority message wins
        spoken = n_bytes > 0 or (has_speech and bool(device_clients))
        if spoken:  # --- hands-free (lane handsfree) --- echo guard; cuts a capture
            self.handsfree.on_spoken(msg, time.monotonic(), self._speech_duration(msg, clip))
        self.speaking_id = msg.id if spoken else None
        self._on_air = (msg, clip) if spoken else None
        grace = PLAYBACK_REPORT_GRACE_S if n_bytes else DEVICE_TTS_GRACE_S  # device voices: unknown speaking rate
        self._speaking_deadline = time.monotonic() + self._speech_duration(msg, clip) + grace
        header: dict[str, Any] = {
            "type": "say",
            "id": msg.id,
            "kind": msg.kind.value,
            "text": msg.text,
            "speech": msg.speech,
            "sample_rate": clip.sample_rate if clip else 0,
            "n_bytes": n_bytes,
            "meta": msg.meta,
        }
        for c in device_clients:  # the device speaks `speech` itself
            c.put({**header, "sample_rate": 0, "n_bytes": 0, "device_tts": True})
            c.put({"type": "say_end", "id": msg.id})
        for c in audio_clients:
            c.put(header)
            if clip is not None:
                for i in range(0, n_bytes, AUDIO_CHUNK_BYTES):
                    c.put(clip.pcm[i : i + AUDIO_CHUNK_BYTES])
            c.put({"type": "say_end", "id": msg.id})
        if rec is not None:
            if released is not None:
                rec.to_first_audio_ms = int((time.monotonic() - released) * 1000)
                self._pending_latency[msg.id] = (rec, released)
            self.latency.appendleft(rec)
        self._send_state()
        self._observe(  # validation kit hook
            "deliver",
            lambda: {
                "msg_id": msg.id,
                "kind": msg.kind.value,
                "n_bytes": n_bytes,
                "audio_clients": len(audio_clients),
                "device_clients": len(device_clients),
                "cancelled_id": cancelled_id,
            },
        )

    def _on_playback(
        self, msg_id: str, state: str, client: RadioClient | None = None, output_s: float | None = None
    ) -> None:
        now = time.monotonic()
        observed = self._pending_latency.get(msg_id) if state == "started" else None  # validation kit hook
        if state == "started":
            pend = self._pending_latency.pop(msg_id, None)
            if pend is not None:
                rec, released = pend
                rec.to_playback_ms = int((now - released) * 1000)
            dispatched = self._dispatched.pop(msg_id, None)
            if dispatched is not None and hasattr(self.scheduler, "observe_speech_latency"):
                # dispatch -> audible, so the speak window allows for how long speech really takes to start
                self.scheduler.observe_speech_latency(now - dispatched)
            cue = self._cue_inflight.pop(msg_id, None)
            if cue is not None:
                path = cue.path if client is None else ("device" if client.device_tts else "pcm")
                self._measure_cue(cue, now, path, output_s)
        elif state == "ended" and msg_id == self.speaking_id:
            self.speaking_id = None
            self._air_free_mono = now
            self._gate_until = now + GATE_TAIL_S
            self._send_state()
        self._observe(  # validation kit hook
            "playback",
            lambda: {
                "msg_id": msg_id,
                "state": state,
                "client": None if client is None else client.name,
                "device_tts": None if client is None else client.device_tts,
                "output_s": output_s,
                "frame": self._frame_brief(),
                "latency": None if observed is None else asdict(observed[0]),
            },
        )
        self.spotter.on_playback(msg_id, state)  # --- spotter --- latency stamp t3; release the mailbox

    def _cancel_speaking(self) -> None:
        if self.speaking_id is not None:
            self._broadcast({"type": "cancel", "id": self.speaking_id})
            self.speaking_id = None
            self._air_free_mono = time.monotonic()
            self._gate_until = time.monotonic() + GATE_TAIL_S
            self._send_state()

    # ------------------------------------------------------------------ proactive messages
    def _on_live_note(self, kind: str, payload: dict[str, Any]) -> None:
        if kind == "lap" and self._loop is not None:
            self._loop.call_soon_threadsafe(self._enqueue_lap, payload)
        elif kind == "motivation" and self._loop is not None:  # lane motivation: a goal was reached
            self._loop.call_soon_threadsafe(self._enqueue_motivation, payload)
        elif kind == "strategy_call" and self._loop is not None:  # race strategy (pitwall.strategy)
            self._loop.call_soon_threadsafe(self._enqueue_strategy, payload)
        # --- race radio ---
        elif kind == "race_call" and self._loop is not None:
            self._loop.call_soon_threadsafe(self._enqueue_race, payload)
        elif kind == URGENT_NOTE and self._loop is not None:
            self._loop.call_soon_threadsafe(self._enqueue_urgent, payload)
        elif kind == "race_retract" and self._loop is not None:
            self._loop.call_soon_threadsafe(self._retract_race, payload)
        # --- end race radio ---
        elif kind == "health_call" and self._loop is not None:  # --- health lane --- car health (pitwall.carhealth)
            self._loop.call_soon_threadsafe(self._enqueue_health, payload)

    def _enqueue_motivation(self, payload: dict[str, Any]) -> None:  # lane motivation (event loop only)
        simple = self.coaching_limits is not None and self.coaching_limits.simple_wording
        sid = self.live.session_id
        msg = goal_message(
            payload, self._goal_lines, sid, simple=simple, to_speech=self.to_speech, voice_enabled=self.voice_enabled
        )
        if msg is not None:
            self.scheduler.enqueue(msg)

    # --- race strategy (pitwall.strategy) ---
    def _enqueue_strategy(self, payload: dict[str, Any]) -> None:
        """A proactive strategy call: queued for the scheduler's speak windows (``strategy.radio``). Calls meant for
        experienced drivers (undercut, a neighbour pitting, gap trends) are not given to a driver whose profile asks
        for simple wording, who hears the call's plain words (``text_simple``) instead of the jargon."""
        try:
            from pitwall.strategy.radio import strategy_message

            limits = self.coaching_limits
            simple = limits is not None and limits.simple_wording
            if payload.get("audience") == "experienced" and simple:
                return
            self.scheduler.enqueue(strategy_message(payload, time.monotonic(), simple=simple))
        except Exception:
            log.exception("strategy call failed")

    # --- race radio (pitwall.raceradio) ---
    def _simple(self) -> bool:
        limits = self.coaching_limits
        return limits is not None and limits.simple_wording

    def _enqueue_race(self, payload: dict[str, Any]) -> None:
        """A race call (``raceradio.radio.race_message``: the seated driver's groups and wording) for the scheduler.

        The radio follows the live session first: a new session's first call (GT7's rolling-start brief comes with the
        session's first frame) can arrive before the tick notices the session, and the tick's reset would then drop
        it with the old session's messages. A call of a session that is no longer the live one is dropped."""
        try:
            sid, live_sid = payload.get("session_id"), self.live.session_id
            if isinstance(sid, str) and live_sid is not None and sid != live_sid:
                log.debug("race call of an earlier session dropped")
                return
            self._follow_session()
            from pitwall.raceradio.radio import race_message

            msg = race_message(
                payload, time.monotonic(), prefs=self.race_prefs, simple=self._simple(), intensity=self.intensity
            )
            if msg is not None:
                self.scheduler.enqueue(msg)
        except Exception:
            log.exception("race call failed")

    def _retract_race(self, payload: dict[str, Any]) -> None:
        """A flashback undid what the unsaid race calls of ``payload["groups"]`` say (position, damage): drop them,
        queued or held (``race_retract``, docs/voice-protocol.md)."""
        try:
            sid, groups = payload.get("session_id"), payload.get("groups")
            if sid != self.live.session_id or not isinstance(groups, list):
                return
            wanted = {g for g in groups if isinstance(g, str)}
            dropped = self.scheduler.drop_race_calls(wanted)
            held = self._held
            if held is not None and held[0].meta.get("race_call") and held[0].meta.get("group") in wanted:
                self._held = None
                dropped += 1
            if dropped:
                log.info("flashback: %d unsaid race call(s) dropped", dropped)
        except Exception:
            log.exception("race retract failed")

    def _enqueue_urgent(self, payload: dict[str, Any]) -> None:
        """An urgent call (``voice.urgent``): said at once, past quiet mode, intensity and speak windows."""
        try:
            self._follow_session()  # as a race call: the session change must not drop it
            self.scheduler.enqueue(urgent_message(payload, time.monotonic(), simple=self._simple()))
        except Exception:
            log.exception("urgent call failed")

    def _online_name_answer(self, intent: str, question: str, sheet: Any) -> tuple[str, str] | None:
        """(answer, name): "who's ahead?" with the online name of the car, when the household opted in
        (``raceradio.names``) and the race radio has no official AI driver name for it; else None."""
        if intent != "who_ahead" or not getattr(self.live, "race_online_names", False):
            return None
        roster = getattr(self.live, "race_roster", None)
        if roster is None or getattr(roster, "session_id", None) != self.live.session_id:
            return None
        from pitwall.raceradio.names import personal_who

        return personal_who(sheet, question, roster)

    def _check_name(self, name: str | None) -> None:
        """A TTS engine that can say which words its G2P drops is asked once, off the loop; a dropped name disables
        addressing (logged without the name)."""
        check = getattr(self.tts, "g2p_dropped", None)
        if name is None or not callable(check) or self._loop is None:
            return

        async def run() -> None:
            try:
                dropped = await asyncio.to_thread(check, name)
            except Exception:
                return
            if dropped and self.addresser.name == name:
                self.addresser.disable_name()
                log.info("name not in the TTS lexicon: the radio will not address the driver by name")

        self._spawn(run())

    # --- end race radio ---

    # --- health lane (pitwall.carhealth) ---
    def _enqueue_health(self, payload: dict[str, Any]) -> None:
        """A proactive car health call (cold tyres, wear, fuel, lock-ups / wheelspin): queued for the scheduler's speak
        windows (``carhealth.radio``), in plain words (``text_simple``) for a driver whose profile asks for them."""
        try:
            from pitwall.carhealth.radio import health_message

            limits = self.coaching_limits
            simple = limits is not None and limits.simple_wording
            if payload.get("audience") == "experienced" and simple:
                return
            self.scheduler.enqueue(health_message(payload, time.monotonic(), simple=simple))
        except Exception:
            log.exception("car health call failed")

    # --- end health lane ---

    def apply_driver(self, driver: Driver | None) -> None:
        """The seated driver changed or edited their profile (``DriverService.attach_radio``; event loop only).

        Their coaching amount, voice switch and skill limits now drive the radio. A spoken "quiet until lap N"
        is a temporary override and is left alone. When somebody else takes the seat, the unsaid lap summaries,
        goal lines and coaching points about the previous driver's laps are dropped (queued and held alike); alerts
        and strategy calls are about the car and stay.
        """
        seated = None if driver is None else driver.id
        if self._seat_known and seated != self._seated_id:
            dropped = self.scheduler.drop_driver_messages()
            held = self._held
            if held is not None and held[0].kind in DRIVER_LAP_KINDS:
                self._held = None
                dropped += 1
            if dropped:
                log.info("seat change: %d unsaid message(s) about the previous driver's laps dropped", dropped)
        seat_changed = self._seat_known and seated != self._seated_id  # race radio: the name confirms the seat
        self._seat_known, self._seated_id = True, seated
        self.coaching_limits = None if driver is None else driver.coaching
        if driver is not None:
            self._set_intensity(driver.preferences.coaching_intensity)
            self.voice_enabled = driver.preferences.voice_enabled
        # --- race radio ---
        prefs = None if driver is None else driver.preferences.radio_calls
        self.race_prefs = prefs
        self.addresser.set_driver(None if driver is None else driver.name, prefs is None or prefs.name, seat_changed)
        self._check_name(self.addresser.name)
        # --- end race radio ---
        self._last_coached.clear()
        self.handsfree.set_driver(driver)  # --- hands-free (lane handsfree) --- the profile sets the scope
        self._send_state()

    def _set_intensity(self, intensity: str) -> None:
        """The radio's coaching intensity: the scheduler's budget, and the shared coaching selection's (D6), which
        uses it as the budget while nobody is in the seat, so the coach card picks what this radio will say."""
        self.intensity = intensity
        self.scheduler.set_intensity(intensity)
        self.live.coach.set_radio_intensity(intensity)

    def _enqueue_lap(self, payload: dict[str, Any]) -> None:
        """One lap's radio messages. ``payload["coach"]`` is the lap's shared D6 selection (``core.live``): the radio
        says exactly its ``picked`` points, the ones the coach card shows, picked from all of the lap's observations
        under the same limits (the payload's ``observations`` are only the top five, for the dashboard). Without it
        ``lap_messages`` picks from ``observations`` with the same shared function."""
        if self.lap_messages is None:
            return
        try:
            snap = self.live.snapshot()
            best = _session_best_clean_ms(snap)
            if self.live.session_id != self._last_coached_sid:
                self._last_coached_sid = self.live.session_id
                self._last_coached.clear()
            args = (
                payload.get("lap") or {},
                payload.get("observations") or [],
                best,
                snap.get("reference"),
                self.intensity,
                time.monotonic(),
            )
            coach = payload.get("coach")
            if self.coaching_limits is None:
                msgs = self.lap_messages(*args, coach=coach)
            else:
                msgs = self.lap_messages(
                    *args, limits=self.coaching_limits, last_coached=self._last_coached, coach=coach
                )
        except Exception:
            log.exception("building lap messages failed")
            return
        for m in msgs:
            self.scheduler.enqueue(m)

    def driving_state(self) -> DrivingState:
        f = self.live.frame
        conn = self.live.connection()["status"]
        on_track = f is not None and conn == "live" and not (int(f.quality) & 0b1100)
        ttb = None
        model = self.live.track_model
        # --- race radio --- no learned model yet (a new track, a joined race): the AI field's and the physics prior's
        # braking zones, so "unknown" is never taken for calm (voice.field_zones)
        if not model:
            session = getattr(self.live, "session", None)
            track = getattr(session, "track_id", None)
            model = knowledge_model(getattr(self.live, "track_knowledge", None), track)
        # --- end race radio ---
        if f is not None and model and f.lap_distance_m is not None and f.speed_kph and f.speed_kph > 30:
            ttb = time_to_next_braking(model, f.lap_distance_m, f.speed_kph)
        to_cue = self.cues.seconds_to_next_cue()  # a cue is a braking zone for the speak window
        if to_cue is not None:
            ttb = to_cue if ttb is None else min(ttb, to_cue)
        return DrivingState(
            on_track=on_track,
            speed_kph=f.speed_kph if f else None,
            brake=f.brake if f else None,
            steering=f.steering if f else None,
            lap_number=f.lap_number if f else None,
            lap_distance_m=f.lap_distance_m if f else None,
            time_to_next_braking_s=ttb,
            traffic_alongside=self.spotter.traffic(),  # --- spotter ---
        )

    async def _tick_loop(self) -> None:
        while True:
            await asyncio.sleep(TICK_S)
            try:
                await self._tick(time.monotonic())
            except Exception:
                log.exception("radio tick failed")

    async def _tick(self, now: float) -> None:
        """One pass of the proactive radio: release what is held, else take the next message from the scheduler.

        Order of precedence: an urgent call waiting for the driver's transmission (or another urgent call) to
        end goes first and blocks the queue until it is out; then a held message once the radio is free and, if
        it needs one, a speak window is open; then the scheduler. While the radio talks, a message is held or a
        question is being answered, the scheduler is asked with ``speaking=True``: it then hands out only what
        outranks the message on air (an urgent call), which therefore never queues behind a held lap summary,
        a cue or a slow LLM answer."""
        self._sync_cue_gate()
        self._check_tts_engine(now)
        self._follow_session()
        self.handsfree.tick(now)  # --- hands-free (lane handsfree) ---
        self.spotter.tick(now)  # --- spotter --- settings, audio rebuilds, mailbox release
        if self.speaking_id is not None and now > self._speaking_deadline:
            self.speaking_id = None  # device never reported playback end
            self._air_free_mono = now
            self._gate_until = now + GATE_TAIL_S
            self._send_state()
        if not self.clients or self.ptt_down:
            return  # nothing to talk to, or the driver is talking
        urgent = self._held_urgent
        if urgent is not None:
            if urgent[0].expired(now):
                self._held_urgent = None
            elif self._urgent_may_cut(urgent[0]):
                self._held_urgent = None
                self._send_ready(urgent, now)
            return
        speaking = self.speaking_id is not None
        capturing = self.handsfree.holds_radio  # --- hands-free (lane handsfree) --- only urgent calls cut it
        if not speaking and not self._busy and not capturing and self._release_held(now):
            return
        interrupt_only = speaking or self._busy or self._held is not None or capturing
        msg = self.scheduler.next_message(self.driving_state(), now, interrupt_only)
        if msg is None:
            return
        msg = self.addresser.apply(msg, now)  # race radio: the driver's name now and then (voice.addressing)
        if not self.voice_enabled and msg.kind not in (MessageKind.ANSWER, MessageKind.CONTROL):
            return
        clip = await self._synthesize(msg, verify=not _urgent(msg))  # an urgent call is not held up by the check
        done = time.monotonic()
        self._after_synthesis((msg, clip, max(0.0, done - now)), done)

    def _after_synthesis(self, ready: _Ready, now: float) -> None:
        """Deliver a freshly synthesised proactive message, or hold it.

        Synthesis takes ~0.4 s (33 m at 300 km/h), so the radio is re-checked: the driver may have keyed the
        mic, and something may have started talking meanwhile (a braking cue, an answer). An urgent call cuts
        anything but another urgent call (equal ranks never cut each other) and skips the speak window; anything
        else is held rather than cut over what is on air, and a message that needs a speak window is held for the
        next calm stretch if a braking zone came into range meanwhile."""
        msg, clip, _synth_s = ready
        if self.ptt_down:
            may_go = False
        elif _urgent(msg):
            may_go = self._urgent_may_cut(msg)
        else:
            radio_free = (
                self.speaking_id is None
                and not self._busy
                and not self.handsfree.holds_radio  # --- hands-free (lane handsfree) ---
                and self._gap_ok(msg, now)
            )
            may_go = radio_free and (
                not msg.needs_speak_window
                or speak_window_ok(self.driving_state(), self._speech_duration(msg, clip), DELIVERY_LEAD_S)
            )
        if may_go:
            self._send_ready(ready, now)
        else:
            self._hold(ready)

    def _release_held(self, now: float) -> bool:
        """Deliver the held message if it may go now (the radio is free). True when it went out."""
        held = self._held
        if held is None:
            return False
        msg, clip, _synth_s = held
        if msg.expired(now):
            self._held = None
            return False
        if not self._gap_ok(msg, now):
            return False  # the radio only just went quiet: keep the scheduler's gap after it
        if (
            msg.needs_speak_window
            and not _urgent(msg)
            and not speak_window_ok(self.driving_state(), self._speech_duration(msg, clip), DELIVERY_LEAD_S)
        ):
            return False  # still braking / cornering: wait for the next calm stretch
        self._held = None
        self._send_ready(held, now)
        return True

    def _gap_ok(self, msg: RadioMessage, now: float) -> bool:
        """The scheduler's minimum gap (``min_gap_s``) after the radio last went silent, for a proactive message that
        was synthesised or held while something else was on air. Urgent calls, cues, answers and acknowledgements are
        exempt, as in the scheduler."""
        if _urgent(msg) or msg.kind in DRIVER_INITIATED or msg.kind is MessageKind.CUE:
            return True
        gap = getattr(self.scheduler, "min_gap_s", MIN_GAP_S)
        gap_s = float(gap) if isinstance(gap, int | float) else MIN_GAP_S
        return now >= self._air_free_mono + gap_s

    def _follow_session(self) -> None:
        """A new live session: the scheduler's queue, budgets and repeat filter belong to the old one
        (``RadioScheduler.reset_session``), and so does a held lap summary, goal line or coaching point."""
        sid = self.live.session_id
        if sid is None or sid == self._radio_sid:
            return
        previous, self._radio_sid = self._radio_sid, sid
        self.handsfree.new_session()  # --- hands-free (lane handsfree) ---
        if previous is None:
            return  # the first session this radio sees: nothing of an older one is queued
        reset = getattr(self.scheduler, "reset_session", None)
        dropped = reset() if callable(reset) else 0
        held = self._held
        if held is not None and held[0].kind in DRIVER_LAP_KINDS:
            self._held = None
            dropped = (dropped if isinstance(dropped, int) else 0) + 1
        if dropped:
            log.info("new session: %s unsaid message(s) about the previous session dropped", dropped)

    def _hold(self, ready: _Ready) -> None:
        """Keep a synthesised message for later. Urgent calls have their own slot; the other slot keeps the more
        important message (the newer on a tie: newest information wins), the other is dropped and logged."""
        msg = ready[0]
        if _urgent(msg):
            slot = self._held_urgent
            if slot is None or slot[0].expired(time.monotonic()):
                self._held_urgent = ready
            else:
                log.warning("urgent call %r dropped: another urgent call is already waiting", msg.text)
            return
        current = self._held
        if current is None or msg.priority >= current[0].priority:
            if current is not None:
                log.info("held message %r replaced by %r", current[0].text, msg.text)
            self._held = ready
        else:
            log.info("message %r dropped: %r is already held", msg.text, current[0].text)

    def _urgent_may_cut(self, msg: RadioMessage) -> bool:
        """An urgent call may go out now: the one interrupt rule (``scheduler.may_interrupt``) lets it cut what is on
        air - anything but another urgent call (a spotter call included)."""
        on_air = self._on_air_message()
        return on_air is None or may_interrupt(msg, on_air[0])

    def _send_ready(self, ready: _Ready, now: float) -> None:
        """Deliver a proactive message. A proactive message it cuts (only an urgent call cuts one) is said again
        later; ``_deliver`` cancels whatever was on air."""
        msg, clip, synth_s = ready
        interrupted = self._on_air_message()
        if synth_s is not None:
            # latency feedback means synthesis + delivery: the time spent held is not speech latency
            self._dispatched[msg.id] = now - synth_s
        self._observe(  # validation kit hook
            "proactive",
            lambda: {
                "msg_id": msg.id,
                "kind": msg.kind.value,
                "priority": int(msg.priority),
                "text": msg.text,
                "lap_number": msg.lap_number,
                "meta": {"lap_id": msg.meta.get("lap_id"), "observation_id": msg.meta.get("observation_id")},
                "needs_speak_window": msg.needs_speak_window,
                "held_s": max(0.0, now - msg.created_mono),
                "state": asdict(self.driving_state()),
            },
        )
        kind = "urgent" if msg.meta.get("urgent") is True else "proactive"  # race radio: notify -> first audio
        self._deliver(msg, clip, LatencyRecord(kind=kind, text=msg.text), msg.created_mono)
        if interrupted is not None and interrupted[0].id != msg.id:
            self._rehold(interrupted, now)

    def status(self) -> dict[str, Any]:
        pending = self.scheduler.pending() if hasattr(self.scheduler, "pending") else []
        return {
            **self.state(),
            "clients": [
                {
                    "name": c.name,
                    "mic_live": c.mic_live,
                    "device_tts": c.device_tts,
                    "dropped": c.dropped,
                    "voices": c.voices,
                    **self.handsfree.client_info(c),  # --- hands-free (lane handsfree) ---
                }
                for c in self.clients
            ],
            "pending": [{"id": m.id, "kind": m.kind.value, "text": m.text} for m in pending],
            "latency": [asdict(r) for r in self.latency],
            "history": list(self.history)[:30],
            "cues": {**self.cues.snapshot(), "timing_log": list(self.cue_timing)[:20]},
            "tts_engine": self._tts_diagnostics(),
            "tts_check": {**self.tts_check, "enabled": self.verify_tts, "recent": list(self.tts_check_log)},
            "handsfree_diag": self.handsfree.diagnostics(),  # --- hands-free (lane handsfree) ---
            "spotter": {"audio": self.spotter.status(), **self.spotter.counters()},  # --- spotter ---
        }

    def _tts_diagnostics(self) -> dict[str, Any]:
        diag = getattr(self.tts, "diagnostics", None)
        base: dict[str, Any] = {
            "engine": self.tts.name,
            **self._tts_state(),
            "synth_s_estimate": round(self._engine_synth_s(), 3),  # what cue timing subtracts
        }
        if callable(diag):
            try:
                return {**base, **diag()}
            except Exception as e:
                base["error"] = str(e)
        base["reason"] = getattr(self.tts, "reason", None)
        return base

    # ------------------------------------------------------------------ live braking cues
    def _on_cue_threadsafe(self, ev: CueEvent) -> None:
        """Cue engine sink (ingest thread): hand the cue to the loop, never block."""
        loop = self._loop
        if loop is None:
            return
        with contextlib.suppress(RuntimeError):  # loop closed: shutting down
            loop.call_soon_threadsafe(self._on_cue, ev)

    def _on_cue(self, ev: CueEvent) -> None:
        self.deliver_cue(ev, time.monotonic())

    def deliver_cue(self, ev: CueEvent, now: float) -> str | None:
        """Say a fired cue right now, or drop it. Returns the drop reason (``None`` = delivered)."""
        reason = self._cue_block_reason(ev, now)
        pcm_needed = any(not c.device_tts for c in self.clients)
        ready = self._cue_phrases.get(ev.cue.parts) if pcm_needed else None
        clip = ready[0] if ready is not None else None
        if reason is None and pcm_needed and clip is None and not any(c.device_tts for c in self.clients):
            # nothing audible to play (audio still being prepared, or synthesis failed): text alone would cut
            # whatever is on air for silence, and a cue that is not heard on time has no use
            reason = "audio not ready"
            self._request_cue_audio()
        if reason is not None:
            self.cues.record_outcome(ev.seq, "dropped", reason)
            log.info("cue %s (lap %d) dropped: %s", ev.cue.text, ev.lap, reason)
            self._observe_cue(ev, "dropped", reason, None, clip)  # validation kit hook
            return reason
        msg = RadioMessage(
            id=f"m{next(self._ids)}",
            kind=MessageKind.CUE,
            priority=Priority.HIGH,
            text=ev.cue.text,
            speech=self._cue_speech(ev.cue.parts),
            created_mono=now,
            lap_number=ev.lap,
            corner=ev.cue.corner,
            needs_speak_window=False,
            meta={
                "cue": ev.cue.kind.value,
                "corner": ev.cue.corner,
                "target_m": round(ev.cue.target_m, 1),
                "focus": ev.cue.focus,
                "seq": ev.seq,
            },
        )
        interrupted = self._on_air_message()
        self._deliver(msg, clip, None, None)
        if interrupted is not None:
            self._rehold(interrupted, now)
        if self.speaking_id == msg.id:
            for mid in [m for m, e in self._cue_inflight.items() if now - e.fired_mono > CUE_INFLIGHT_TTL_S]:
                del self._cue_inflight[mid]
            self._cue_inflight[msg.id] = ev
        note = "audio not ready: text only" if pcm_needed and clip is None else None
        self.cues.record_outcome(ev.seq, "sent", note)
        self._observe_cue(ev, "sent", note, msg.id, clip)  # validation kit hook
        return None

    def _cue_block_reason(self, ev: CueEvent, now: float) -> str | None:
        if now > min(ev.deadline_mono, ev.fired_mono + CUE_MAX_HANDOFF_S):
            return "late hand-off"  # the key word would land past the reference point
        mute = self._cue_mute_reason()
        if mute is not None:
            return mute
        if self.ptt_down:
            return "driver transmitting"
        on_air = self._on_air_message()
        if on_air is not None:
            m = on_air[0]
            if m.kind is MessageKind.CUE:
                return "previous cue still playing"
            if m.kind in (MessageKind.ANSWER, MessageKind.CONTROL):
                return "answer on air"
            # the one interrupt rule: a cue never cuts an urgent call (a spotter onset, the red flag), but does cut a
            # spotter clear or "still there" (YIELDS_TO_CUE_KEY) and anything proactive
            if not may_interrupt(_CUE_PROBE, m):
                return "spotter call on air" if m.kind is MessageKind.SPOTTER else "urgent message on air"
        return None

    def _cue_mute_reason(self) -> str | None:
        """Why cues are held right now (``None`` = they may play). Re-checked at delivery."""
        if not self.voice_enabled:
            return "voice off"
        if not self.clients:
            return "no radio connected"
        if self.intensity == "quiet":
            return "minimal radio (quiet intensity)"  # its acknowledgement promises "alerts and answers only"
        is_quiet = getattr(self.scheduler, "is_quiet", None)
        if callable(is_quiet):
            f = self.live.frame
            if is_quiet(f.lap_number if f is not None else None):
                return "quiet mode"
        return None

    def _sync_cue_gate(self) -> None:
        self.cues.set_muted(self._cue_mute_reason())

    def _on_air_message(self) -> tuple[RadioMessage, AudioClip | None] | None:
        on_air = self._on_air
        if on_air is None or self.speaking_id != on_air[0].id:
            return None
        return on_air

    def _rehold(self, interrupted: tuple[RadioMessage, AudioClip | None], now: float) -> None:
        """A proactive message cut by a cue is said again (in full, under a new id) in the next speak window, once:
        a message cut a second time is dropped (``MAX_RESENDS``), so a busy stretch never repeats it lap after lap."""
        msg, clip = interrupted
        if msg.kind in (MessageKind.ANSWER, MessageKind.CONTROL, MessageKind.CUE, MessageKind.SPOTTER) or msg.expired(
            now
        ):  # --- spotter --- a cut spotter call is never said later
            return
        resent = msg.meta.get(RESENT_KEY, 0)
        count = resent if isinstance(resent, int) and not isinstance(resent, bool) else 0
        if count >= MAX_RESENDS:
            log.info("message %r cut again: not said a third time", msg.text)
            return
        if self._held is None:
            again = dataclasses.replace(msg, id=f"m{next(self._ids)}", meta={**msg.meta, RESENT_KEY: count + 1})
            self._held = (again, clip, None)

    def _cue_speech(self, parts: Sequence[str]) -> str:
        return ", ".join(sp for sp in (self.to_speech(p).strip() for p in parts) if sp)

    def _cue_path(self) -> str:
        """Delivery path the cue timing is computed for: device voices only when every radio speaks for itself."""
        return "device" if self.clients and all(c.device_tts for c in self.clients) else "pcm"

    def _cue_output_s(self, path: str, reported: float | None = None) -> float:
        """Device "started" -> the driver's ear on this path. The allowance is a floor: a device-reported value
        (Web Audio ``outputLatency``) may leave out the Bluetooth link, so it can only lengthen the allowance -
        an underestimate would move every cue later."""
        learned = self._cue_output[path].value if reported is None else reported
        return CUE_OUTPUT_ALLOWANCE_S if learned is None else max(CUE_OUTPUT_ALLOWANCE_S, learned)

    def _cue_latency_s(self, path: str) -> float:
        """Fire -> key-word-path audible in the ear: the measured (else seeded) fire -> "started" latency plus the
        output path after it."""
        est = self._cue_latency[path]
        if est.value is not None:
            started = est.value
        else:
            raw = getattr(self.scheduler, "speech_latency_s", SPEECH_LATENCY_S)
            started = float(raw) if isinstance(raw, int | float) else SPEECH_LATENCY_S
            if path == "pcm":  # the scheduler's latency includes synthesis, which pre-synthesised cues skip
                started = max(DELIVERY_LEAD_S, started - self._engine_synth_s())
        return min(MAX_LATENCY_S, max(0.0, started) + self._cue_output_s(path))

    def _device_word_offset(self, parts: Sequence[str], key_index: int) -> float:
        words = sum(spoken_word_count(self.to_speech(p)) for p in parts[:key_index])
        return words / WORDS_PER_S + CUE_DEVICE_PAUSE_S * key_index

    def _push_cue_timing(self) -> None:
        path = self._cue_path()
        offsets: dict[tuple[str, ...], float] = {}
        for c in self.cues.plan.cues:
            if c.key_index <= 0:
                continue
            ready = self._cue_phrases.get(c.parts) if path == "pcm" else None
            offsets[c.parts] = ready[1] if ready is not None else self._device_word_offset(c.parts, c.key_index)
        self.cues.set_timing(CueTiming(latency_s=self._cue_latency_s(path), path=path, offsets_s=offsets))

    def _cue_clients_changed(self) -> None:
        """Radios, their voice source or settings changed: re-gate, retime and make sure the audio exists."""
        self._sync_cue_gate()
        self._push_cue_timing()
        self._request_cue_audio()

    def _on_cue_plan_threadsafe(self, plan: CuePlan) -> None:
        """Plan listener (analysis thread or loop): retime and pre-synthesise on the loop."""
        loop = self._loop
        if loop is None:
            return
        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(self._on_cue_plan)

    def _on_cue_plan(self) -> None:
        self._push_cue_timing()
        self._request_cue_audio()

    def _request_cue_audio(self) -> None:
        if self._loop is None:
            return
        task = self._cue_prep_task
        if task is not None and not task.done():
            self._cue_prep_again = True  # the running pass re-reads the plan when it finishes
            return
        self._cue_prep_task = asyncio.create_task(self._prepare_cue_audio(), name="radio-cue-audio")

    async def _prepare_cue_audio(self) -> None:
        """Synthesise every part of the current plan's phrases once (worker threads), compose the phrases, then
        push the exact key-word offsets to the engine. Only needed when a radio plays server audio."""
        try:
            while True:
                self._cue_prep_again = False
                voice = getattr(self.tts, "voice", None)
                if self.tts is not self._cue_tts or voice != self._cue_voice:  # new engine or voice: stale audio
                    self._cue_tts = self.tts
                    self._cue_voice = voice
                    self._cue_parts.clear()
                    self._cue_phrases.clear()
                    self._cue_failed.clear()
                    self._cue_part_engine.clear()
                    self._cue_part_pinned.clear()
                    self._cue_part_unchecked.clear()
                    self._cue_fallback_parts.clear()
                    self._cue_synth_s.clear()
                if any(not c.device_tts for c in self.clients):
                    for cue in self.cues.plan.cues:
                        if cue.parts in self._cue_phrases:
                            continue
                        for part in cue.parts:
                            if await self._cue_part_audio(self.to_speech(part)) is None:
                                break
                        else:
                            phrase = await self._phrase_audio(cue.parts, cue.key_index)
                            if phrase is not None:
                                self._cue_phrases[cue.parts] = phrase
                                _bound(self._cue_phrases)
                    await self._upgrade_cue_parts()
                self._push_cue_timing()
                if not self._cue_prep_again:
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("cue audio preparation failed; cues go out as text until it succeeds")

    async def _cue_part_audio(self, speech: str) -> AudioClip | None:
        cached = self._cue_parts.get(speech)
        if cached is not None:
            return cached
        failed = self._cue_failed.get(speech)
        if failed is not None and time.monotonic() - failed < CUE_SYNTH_RETRY_S:
            return None
        try:
            res = await asyncio.to_thread(self._synth_detailed, speech)
            res = await self._verified(speech, res, "cue part")
        except Exception as e:
            log.warning("cue audio %r: synthesis failed (%s); text only", speech, e)
            self._cue_failed[speech] = time.monotonic()
            return None
        clip = trim_silence(res.clip)
        if clip.n_samples == 0:  # e.g. no TTS engine: nothing to play
            self._cue_failed[speech] = time.monotonic()
            return None
        if res.engine == self.tts.name:
            self._cue_synth_s.append(res.synth_ms / 1000.0)
        self._remember_part(speech, clip, res)
        return clip

    def _remember_part(self, speech: str, clip: AudioClip, res: SynthResult) -> None:
        self._cue_parts[speech] = clip
        self._cue_part_engine[speech] = res.engine
        if res.fallback_reason is not None and res.fallback_reason.startswith("spoken-number check"):
            self._cue_part_pinned.add(speech)
        if res.neural and not res.checked:
            self._cue_part_unchecked.add(speech)  # e.g. Parakeet still loading: checked when it is (tick)
        else:
            self._cue_part_unchecked.discard(speech)
        if _bound(self._cue_parts):
            for k in [k for k in self._cue_part_engine if k not in self._cue_parts]:
                del self._cue_part_engine[k]
            self._cue_part_pinned &= self._cue_parts.keys()
            self._cue_part_unchecked &= self._cue_parts.keys()

    async def _phrase_audio(self, parts: tuple[str, ...], key_index: int) -> tuple[AudioClip, float] | None:
        """A phrase composed from its cached parts, in one voice: when the spoken-number check moved one of its
        parts to the fallback voice, that voice says the whole phrase (never "turn four" in one voice and "brake"
        in another). ``None`` if a part has no audio."""
        speeches = [self.to_speech(p) for p in parts]
        if not all(sp in self._cue_parts for sp in speeches):
            return None
        clips = [self._cue_parts[sp] for sp in speeches]
        engines = {self._cue_part_engine.get(sp) for sp in speeches}
        if len(engines) > 1 and any(sp in self._cue_part_pinned for sp in speeches):
            fallback = getattr(self.tts, "synthesize_fallback", None)
            fb_name = str(getattr(self.tts, "fallback_name", None) or "say")
            same: list[AudioClip] = []
            for sp, clip in zip(speeches, clips, strict=True):
                if self._cue_part_engine.get(sp) == fb_name:
                    same.append(clip)
                    continue
                fb = self._cue_fallback_parts.get(sp)
                if fb is None and callable(fallback):
                    try:
                        fb = trim_silence(await asyncio.to_thread(fallback, sp))
                    except Exception as e:
                        log.warning("cue audio %r: fallback voice failed (%s); phrase keeps two voices", sp, e)
                        break
                    self._cue_fallback_parts[sp] = fb
                    _bound(self._cue_fallback_parts)
                if fb is None or not fb.n_samples:
                    break
                same.append(fb)
            else:
                clips = same
        return compose_cue_clip(clips, key_index)

    async def _upgrade_cue_parts(self) -> None:
        """Bring cached cue parts up to the primary voice, checked: re-render parts its fallback rendered while it
        was starting (once it is ready), and run the spoken-number check on primary-voice parts rendered while
        it could not run (STT still loading). Changed parts are swapped in phrase by phrase: a phrase always has
        audio, old or new."""
        primary = self.tts.name
        fresh: dict[str, tuple[AudioClip, SynthResult]] = {}
        if getattr(self.tts, "active", primary) == primary:
            stale = [
                sp
                for sp, engine in self._cue_part_engine.items()
                if engine != primary and sp not in self._cue_part_pinned and sp in self._cue_parts
            ]
            for speech in stale:
                try:
                    res = await asyncio.to_thread(self._synth_detailed, speech)
                except Exception:
                    continue
                if res.engine != primary:
                    break  # down again: try on a later pass
                res = await self._verified(speech, res, "cue part")
                clip = trim_silence(res.clip)
                if clip.n_samples:
                    fresh[speech] = (clip, res)
        for speech in list(self._cue_part_unchecked):
            cached = self._cue_parts.get(speech)
            if cached is None or self._cue_part_engine.get(speech) != primary:
                self._cue_part_unchecked.discard(speech)
                continue
            if speech in fresh or not self._can_verify():
                continue
            res = await self._verified(speech, SynthResult(cached, primary, True, 0.0), "cue part")
            if not res.checked and res.neural:
                continue  # still could not check (e.g. the STT failed): a later pass tries again
            if res.clip is cached:
                self._cue_part_unchecked.discard(speech)  # passed (or nothing better): keep the audio
                continue
            clip = trim_silence(res.clip)
            if clip.n_samples:
                fresh[speech] = (clip, res)
        if not fresh:
            return
        for speech, (clip, res) in fresh.items():
            self._remember_part(speech, clip, res)
        key_index = {c.parts: c.key_index for c in self.cues.plan.cues}
        for parts in list(self._cue_phrases):
            speeches = [self.to_speech(p) for p in parts]
            if not any(sp in fresh for sp in speeches) or parts not in key_index:
                continue
            phrase = await self._phrase_audio(parts, key_index[parts])
            if phrase is not None:
                self._cue_phrases[parts] = phrase
        log.info("cue audio: %d part(s) re-rendered or replaced after the check (%s)", len(fresh), primary)

    def _measure_cue(self, ev: CueEvent, now: float, path: str, output_s: float | None = None) -> None:
        """Playback of a cue started (``now``): learn the latency, and log where its key word was heard vs
        intended. ``output_s`` is the device-reported delay from that report to the ear (never below the
        allowance), so the logged error and latency describe the ear, not the device's speaker call."""
        if output_s is not None:
            self._cue_output[path].observe(output_s)
        out = self._cue_output_s(path, output_s)
        started = now - ev.fired_mono
        if 0.0 <= started <= MAX_LATENCY_S:
            self._cue_latency[path].observe(started)
        if output_s is not None or 0.0 <= started <= MAX_LATENCY_S:
            self._push_cue_timing()
        latency = started + out
        error_m = cue_timing_error_m(ev, self.cues.sample(), now, self.cues.plan.length_m, out)
        self.cue_timing.appendleft(
            {
                "t": time.time(),
                "corner": ev.cue.corner,
                "text": ev.cue.text,
                "lap": ev.lap,
                "path": path,
                "speed_kph": round(ev.v_mps * 3.6),
                "latency_ms": round(latency * 1000),
                "output_ms": round(out * 1000),
                "output_reported": output_s is not None,
                "predicted_latency_ms": round(ev.latency_s * 1000),
                "error_m": None if error_m is None else round(error_m, 1),
            }
        )
        self.cues.record_timing(ev.seq, error_m=error_m, latency_s=latency)
        self._observe(  # validation kit hook
            "cue_timing",
            lambda: {
                "seq": ev.seq,
                "error_m": error_m,
                "latency_ms": round(latency * 1000),
                "output_ms": round(out * 1000),
                "output_reported": output_s is not None,
                "predicted_latency_ms": round(ev.latency_s * 1000),
            },
        )
        log.info(
            "cue %s (lap %d, %.0f km/h): key word %s vs intended, latency %.0f ms incl. %.0f ms output %s "
            "(predicted %.0f ms, %s)",
            ev.cue.text,
            ev.lap,
            ev.v_mps * 3.6,
            "unmeasured" if error_m is None else f"{error_m:+.1f} m",
            latency * 1000,
            out * 1000,
            "reported" if output_s is not None else "allowance",
            ev.latency_s * 1000,
            path,
        )


def _output_latency(msg: dict[str, Any]) -> float | None:
    """Optional ``output_latency_s`` of a playback report: how long after ``started`` the audio reaches the ear
    (e.g. Web Audio ``outputLatency``). Absent, malformed or implausible values are ignored."""
    v = msg.get("output_latency_s")
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    f = float(v)
    return f if math.isfinite(f) and 0.0 <= f <= MAX_OUTPUT_LATENCY_S else None


def _bound(cache: dict[Any, Any], size: int = CUE_AUDIO_CACHE) -> bool:
    """Drop the oldest entries beyond ``size``; True if any went."""
    dropped = False
    while len(cache) > size:
        del cache[next(iter(cache))]
        dropped = True
    return dropped
