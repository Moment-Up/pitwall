"""Hands-free talking (lane handsfree): the radio answers when the driver starts with the wake word.

Push-to-talk stays the default. A device that turns hands-free on (``settings`` frame: ``handsfree``, ``wake_word``)
runs a small energy voice-activity detector in the browser and tells the server when speech starts and ends (``vad``
frames, docs/voice-protocol.md). The server keeps the last ``PRE_ROLL_S`` of that device's microphone in a ring
buffer, captures the segment, transcribes it, and answers only when the transcript starts with the wake word
("Pitwall" by default, or "Radio"). Everything else is thrown away at once: never shown, stored or logged (logs and
observers carry reasons, lengths and counts only, never ignored text).

Safety and politeness:

* **Off by default** on every device, and refused on the server with ``PITWALL_VOICE_HANDSFREE=false``.
* **Stationary scope by default.** Hands-free listens only while the car is stationary (``MotionGate``, a port of
  Drive's hysteresis rule in ``web-react/src/lib/drive/motion.ts``) until the seated driver's profile allows
  "Hands-free while driving" (``DriverPreferences.handsfree_while_driving``). On real captures the car is still for
  only 2-25 % of a race (docs/research/handsfree.md).
* **Half-duplex.** A segment cannot start while the radio speaks or in its gate tail, a message going on air aborts a
  capture, and a transcript that repeats something the radio said in the last ``ECHO_WINDOW_S`` is dropped (some
  engineer lines start with "Pitwall" or "Radio").
* **Budgets.** At most ``TRANSCRIBE_LIMIT`` transcriptions and ``ANSWER_LIMIT`` answers a minute, one acknowledgement
  every ``ACK_WINDOW_S``, and error frames at most once a minute.
* **No LLM in the time-critical path.** An addressed question goes through the hub's normal ``_answer``: deterministic
  while the car moves, the LLM only when it is stationary.

The pure rules (``match_wake``, ``is_echo``, ``MotionGate``, ``RateBudget``) are module functions so they can be
tested and reused by ``scripts/handsfree_check.py``. ``HandsFreeController`` is the hub's side; the hub calls it from
small hooks marked ``# --- hands-free (lane handsfree) ---``. All its methods run on the event loop.

Every number here is a heuristic from synthetic audio and recorded telemetry (docs/research/handsfree.md); none has been
checked with a real voice on the rig yet.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import re
import time
import unicodedata
from collections import deque
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any, Literal

from pitwall.ai.engineer import detect_intent
from pitwall.model.telemetry import CarFrame, FrameQuality
from pitwall.voice.stt import EnergyGate, pcm16_to_float32
from pitwall.voice.types import MIC_SAMPLE_RATE, AudioClip, MessageKind, Priority, RadioMessage

if TYPE_CHECKING:
    from pitwall.drivers import Driver
    from pitwall.voice.hub import RadioClient, RadioHub

log = logging.getLogger(__name__)

Scope = Literal["stationary", "driving"]

WAKE_WORDS: tuple[str, ...] = ("pitwall", "radio")
DEFAULT_WAKE_WORD = "pitwall"

# --- audio [heuristics: docs/research/handsfree.md section 3.4] -----------------------------------------------------
PRE_ROLL_S = 0.5  # kept before the browser's "start" (its onset lag is 0-224 ms)
PRE_ROLL_BYTES = round(PRE_ROLL_S * MIC_SAMPLE_RATE) * 2  # int16 mono: 16 000 bytes
MIN_SPEECH_S = 0.4  # audio after the pre-roll; shorter is a cough or a click
MAX_SPEECH_S = 8.0  # longer is talk to someone else, or noise (the browser caps a segment at 8 s)
CAPTURE_WATCHDOG_S = 9.0  # a capture whose "end" never came
QUEUE_MAX = 2  # segments waiting for the speech engine (the oldest is dropped)
SEGMENT_GATE = EnergyGate(min_clip_s=0.4, min_voiced_s=0.3, threshold_dbfs=-45.0)

# --- budgets ---------------------------------------------------------------------------------------------------------
TRANSCRIBE_LIMIT, TRANSCRIBE_WINDOW_S = 12, 60.0
ANSWER_LIMIT, ANSWER_WINDOW_S = 6, 60.0
ACK_LIMIT, ACK_WINDOW_S = 1, 20.0
ERROR_FRAME_EVERY_S = 60.0

# --- echo guard ------------------------------------------------------------------------------------------------------
ECHO_WINDOW_S = 10.0  # after a message finished (estimated): its words may still come back through the mic
ECHO_RATIO = 0.8
ECHO_MIN_TOKENS = 3

# --- the wake word alone ---------------------------------------------------------------------------------------------
TRIGGER_GRACE_S = 1.2  # "Pitwall ... what's my fuel?": wait this long for the question before saying "Go ahead."
FOLLOW_UP_S = 6.0  # after "Go ahead." ends, the next segment of that device needs no wake word (once)

# --- motion (port of web-react/src/lib/drive/motion.ts) --------------------------------------------------------------
STOP_BELOW_KPH = 3.0
STOP_AFTER_S = 1.5
MOVE_ABOVE_KPH = 8.0
_NOT_DRIVING = int(FrameQuality.PAUSED | FrameQuality.REPLAY_OR_SPECTATING)

# --- radio messages (section 4.5) ------------------------------------------------------------------------------------
ACK_TEXT = "Go ahead."
ACK_TEXT_SIMPLE = "Go ahead, I'm listening."
HINT_TEXT = "Hands-free is off while you drive. Hold the button to talk on track."
HINT_TEXT_SIMPLE = "I only listen for '{word}' when the car is stopped. Press the button to talk while you drive."

# Rejection / outcome codes (docs/voice-protocol.md). "rejected" = never transcribed or not answered for a reason;
# "ignored" = transcribed and silently dropped (not addressed to the radio, or the radio's own echo).
START_REASONS = ("not_armed", "unavailable", "ptt", "other_device", "speaking", "busy", "paused_moving", "rate_limited")
IGNORED_REASONS = ("echo", "not_addressed")


# ============================================================================================ wake word
_FILLERS = frozenset({"hey", "hi", "ok", "okay", "oi", "right", "so", "um", "uh", "er", "erm", "ah", "oh", "yeah"})
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)*")
_QUESTION_STRIP = " ,.;:!?-–—"
_WORD_CHAR_RE = re.compile(r"\w")
_APOSTROPHES = "\u2018\u2019\u02bc"  # curly and modifier apostrophes fold to "'"
_REASON_RE = re.compile(r"[a-z_]{1,24}")  # a device's own abort reason ("suppressed"), kept for diagnostics
_MAX_REASONS = 64


def _fold(text: str) -> tuple[str, list[int]]:
    """ASCII lower-case fold, character by character, with the original index of every folded character (so a match
    in the folded text maps back to a span of the original: "é" -> "e", "ﬁ" -> "fi", a curly apostrophe -> "'")."""
    out: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        folded = "'" if ch in _APOSTROPHES else unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode()
        for c in folded.lower():
            out.append(c)
            index.append(i)
    return "".join(out), index


def tokens(text: str) -> list[str]:
    """Normalised words: ASCII-folded, lower case, ``[a-z0-9]+(?:'[a-z0-9]+)*``."""
    return _TOKEN_RE.findall(_fold(text)[0])


def levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _pitwall_distance(candidate: str) -> int | None:
    """How far a candidate is from "pitwall" when it counts as the wake word, else ``None``.

    Speech engines hear "Pitwall" as "Pit wall", "Pigwall", "Bidwall", "Big wall", "Tidwall", "Hitwall", "It wall",
    "Pitbull", "Pitfall"... (docs/research/handsfree.md section 3.3): a candidate counts when it is "pitwall" or
    "itwall", or starts with p/b/t/d/h/f, has 5-9 characters and is within 2 edits."""
    if candidate in ("pitwall", "itwall"):
        return 0
    if candidate[:1] in ("p", "b", "t", "d", "h", "f") and 5 <= len(candidate) <= 9:
        d = levenshtein(candidate, "pitwall")
        return d if d <= 2 else None
    return None


def _is_radio(token: str) -> bool:
    if token in ("radio", "radios", "radio's"):
        return True
    return token[:1] == "r" and 4 <= len(token) <= 7 and levenshtein(token, "radio") <= 1


@dataclass(frozen=True, slots=True)
class WakeMatch:
    word: str  # the wake word matched ("pitwall" | "radio")
    question: str  # the original text after the wake word ("" when nothing follows)

    @property
    def trigger_only(self) -> bool:
        """The wake word alone ("Pitwall."): no word characters after it."""
        return _WORD_CHAR_RE.search(self.question) is None


def match_wake(text: str, word: str) -> WakeMatch | None:
    """Does ``text`` start with the wake word ``word``? Returns the question after it, else ``None``.

    Up to two leading fillers ("hey", "ok", "um"...) are skipped. "pitwall" is tried on the next two words joined
    ("pit wall", "big wall") and on the next word alone; the closer of the two wins, the two-word span on a tie (so
    "Pitwall, OK?" keeps "OK" as the question instead of hearing "pitwallok"). "radio" is one word only; when the whole
    text is a radio check ("Radio check"), the question is the whole text, so the engineer answers it.
    """
    if word not in WAKE_WORDS:
        raise ValueError(f"unknown wake word {word!r}")
    folded, index = _fold(text)
    toks = [(m.group(0), m.end()) for m in _TOKEN_RE.finditer(folded)]
    i = 0
    while i < len(toks) and i < 2 and toks[i][0] in _FILLERS:
        i += 1
    end: int | None = None  # folded index just after the wake word
    if word == "pitwall":
        best: tuple[int, int] | None = None  # (distance, n words)
        for n in (2, 1):
            if len(toks) - i < n:
                continue
            d = _pitwall_distance("".join(t for t, _ in toks[i : i + n]))
            if d is not None and (best is None or d < best[0]):
                best = (d, n)
        if best is not None:
            end = toks[i + best[1] - 1][1]
    elif i < len(toks) and _is_radio(toks[i][0]):
        end = toks[i][1]
    if end is None:
        return None
    if word == "radio" and detect_intent(text).name == "radio_check":
        return WakeMatch(word, text.strip())
    return WakeMatch(word, text[index[end - 1] + 1 :].lstrip(_QUESTION_STRIP).strip())


# ============================================================================================ echo guard
def is_echo(heard: list[str], spoken: list[str]) -> bool:
    """The transcript (tokens) is the radio's own words coming back: SequenceMatcher ratio of at least ``ECHO_RATIO``,
    or at least ``ECHO_MIN_TOKENS`` words that appear as a contiguous run of what was said."""
    if not heard or not spoken:
        return False
    if SequenceMatcher(None, heard, spoken, autojunk=False).ratio() >= ECHO_RATIO:
        return True
    n = len(heard)
    if ECHO_MIN_TOKENS <= n <= len(spoken):
        return any(spoken[k : k + n] == heard for k in range(len(spoken) - n + 1))
    return False


# ============================================================================================ budgets
class RateBudget:
    """At most ``limit`` events in any ``window_s`` (sliding window)."""

    def __init__(self, limit: int, window_s: float) -> None:
        self.limit = limit
        self.window_s = window_s
        self._times: deque[float] = deque()

    def _trim(self, now: float) -> None:
        while self._times and now - self._times[0] >= self.window_s:
            self._times.popleft()

    def count(self, now: float) -> int:
        self._trim(now)
        return len(self._times)

    def available(self, now: float) -> bool:
        return self.count(now) < self.limit

    def take(self, now: float) -> bool:
        """Spend one if there is one left."""
        if not self.available(now):
            return False
        self._times.append(now)
        return True

    def clear(self) -> None:
        self._times.clear()


# ============================================================================================ motion
@dataclass(slots=True)
class MotionGate:
    """Moving or stationary with hysteresis: the server's port of Drive's rule (``web-react/src/lib/drive/motion.ts``)
    plus the frame's own quality flags.

    * stationary: no frame, data that is not live (stale: the game is in a menu or paused the stream), a paused or
      replay frame, or a known speed under ``STOP_BELOW_KPH`` for ``STOP_AFTER_S`` (at once in the pit lane or the
      garage, ``pit_status`` 1 or 2, or straight after a stop).
    * moving: a known speed over ``MOVE_ABOVE_KPH``.

    Between the thresholds, or with an unknown speed, the previous answer stands; with nothing before it the car is
    not known to be stationary (moving: the safe side). A single 8 km/h line flipped up to 22 times in 5.6 minutes
    of a real race; this rule flips 1-12 times per capture (docs/research/handsfree.md section 3.1)."""

    stationary: bool | None = None
    slow_since: float | None = None

    def update(self, frame: CarFrame | None, live: bool, now: float) -> bool:
        if frame is None or not live or int(frame.quality) & _NOT_DRIVING:
            self.stationary, self.slow_since = True, None
            return True
        v = frame.speed_kph
        if v is None or not math.isfinite(v):
            if self.stationary is None:
                self.stationary = False
            return self.stationary
        if v > MOVE_ABOVE_KPH:
            self.stationary, self.slow_since = False, None
        elif v >= STOP_BELOW_KPH:
            if not self.stationary:  # a stop in progress starts over
                self.stationary, self.slow_since = False, None
        elif self.stationary is None or self.stationary or frame.pit_status in (1, 2):
            self.stationary, self.slow_since = True, None
        else:
            since = self.slow_since if self.slow_since is not None else now
            if now - since >= STOP_AFTER_S:
                self.stationary, self.slow_since = True, None
            else:
                self.stationary, self.slow_since = False, since
        return bool(self.stationary)


# ============================================================================================ controller
@dataclass(slots=True, eq=False)
class _Device:
    armed: bool = False
    wake_word: str = DEFAULT_WAKE_WORD
    ring: bytearray = field(default_factory=bytearray)


@dataclass(slots=True, eq=False)
class _Segment:
    client: RadioClient
    seq: int
    t0: float  # monotonic time the capture started
    wake: str
    buf: bytearray
    preroll: int  # bytes of pre-roll at the start of ``buf``
    t_end: float = 0.0
    pre_addressed: bool = False  # a follow-up: no wake word needed

    @property
    def audio_s(self) -> float:
        return len(self.buf) / 2 / MIC_SAMPLE_RATE

    @property
    def speech_s(self) -> float:
        return (len(self.buf) - self.preroll) / 2 / MIC_SAMPLE_RATE


@dataclass(slots=True, eq=False)
class _FollowUp:
    """The wake word alone was heard: "grace" (the question may still come), "ack" ("Go ahead." on air), "window"
    (the next segment of that device needs no wake word until ``deadline``)."""

    client: RadioClient
    seq: int
    wake: str
    phase: Literal["grace", "ack", "window"]
    deadline: float
    ack_id: str | None = None
    ack_task: asyncio.Task[None] | None = None


class HandsFreeController:
    """The hub's hands-free side (see the module docstring). Event loop only."""

    def __init__(self, hub: RadioHub, enabled: bool = True) -> None:
        self.hub = hub
        self.enabled = enabled
        self.scope: Scope = "stationary"
        self._devices: dict[RadioClient, _Device] = {}
        self._motion = MotionGate()
        self._stationary = True
        self._capture: _Segment | None = None
        self._queue: deque[_Segment] = deque()
        self._draining = False
        self._transcribe = RateBudget(TRANSCRIBE_LIMIT, TRANSCRIBE_WINDOW_S)
        self._answers = RateBudget(ANSWER_LIMIT, ANSWER_WINDOW_S)
        self._acks = RateBudget(ACK_LIMIT, ACK_WINDOW_S)
        self._spoken: deque[tuple[float, list[str], list[str]]] = deque(maxlen=32)  # (keep until, text, speech)
        self._follow: _FollowUp | None = None
        self._hint_word: str | None = None  # a start was refused while moving: say the hint at the next stop
        self._hint_said = False  # once per session
        self._last_error_mono = -math.inf
        self.counts: dict[str, int] = {"heard": 0, "addressed": 0, "ignored": 0, "rejected": 0}
        self._reasons: dict[str, int] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=20)
        self._published: tuple[Any, ...] | None = None
        self._refresh_motion(time.monotonic())

    # ------------------------------------------------------------------ state
    @property
    def armed(self) -> int:
        return sum(1 for d in self._devices.values() if d.armed)

    @property
    def capturing(self) -> bool:
        return self._capture is not None

    @property
    def stationary(self) -> bool:
        return self._stationary

    def unavailable_reason(self) -> str | None:
        """Why the server cannot listen hands-free, else ``None``."""
        if not self.enabled:
            return "switched off on the server (PITWALL_VOICE_HANDSFREE=false)"
        why = self.hub._stt_unavailable()
        return None if why is None else f"needs speech recognition: {why}"

    @property
    def available(self) -> bool:
        return self.unavailable_reason() is None

    @property
    def active(self) -> bool:
        return self.available and self.armed >= 1 and (self.scope == "driving" or self._stationary)

    @property
    def paused(self) -> str | None:
        return "moving" if self.armed >= 1 and self.scope == "stationary" and not self._stationary else None

    @property
    def follow_up(self) -> bool:
        return self._follow is not None

    def state(self) -> dict[str, Any]:
        """The ``handsfree`` block of the radio's ``state`` frame (docs/voice-protocol.md)."""
        return {
            "available": self.available,
            "reason": self.unavailable_reason(),
            "armed": self.armed,
            "scope": self.scope,
            "active": self.active,
            "paused": self.paused,
            "capturing": self.capturing,
            "follow_up": self.follow_up,
            "wake_words": list(WAKE_WORDS),
            "counts": dict(self.counts),
        }

    def client_info(self, client: RadioClient) -> dict[str, Any]:
        d = self._devices.get(client)
        return {"handsfree": bool(d and d.armed), "wake_word": d.wake_word if d else DEFAULT_WAKE_WORD}

    def diagnostics(self) -> dict[str, Any]:
        """``/api/voice/status`` ``handsfree_diag``: counters per reason, the last 20 events (never any text) and the
        server thresholds."""
        now = time.monotonic()
        return {
            "reasons": dict(self._reasons),
            "events": list(self._events),
            "stationary": self._stationary,
            "queue": len(self._queue),
            "processing": self._draining,
            "budgets": {
                "transcriptions_last_60s": self._transcribe.count(now),
                "answers_last_60s": self._answers.count(now),
            },
            "thresholds": {
                "pre_roll_s": PRE_ROLL_S,
                "min_speech_s": MIN_SPEECH_S,
                "max_speech_s": MAX_SPEECH_S,
                "capture_watchdog_s": CAPTURE_WATCHDOG_S,
                "segment_gate_dbfs": SEGMENT_GATE.threshold_dbfs,
                "transcriptions_per_min": TRANSCRIBE_LIMIT,
                "answers_per_min": ANSWER_LIMIT,
                "ack_every_s": ACK_WINDOW_S,
                "echo_window_s": ECHO_WINDOW_S,
                "trigger_grace_s": TRIGGER_GRACE_S,
                "follow_up_s": FOLLOW_UP_S,
                "stop_below_kph": STOP_BELOW_KPH,
                "stop_after_s": STOP_AFTER_S,
                "move_above_kph": MOVE_ABOVE_KPH,
            },
        }

    # ------------------------------------------------------------------ devices
    def configure(self, client: RadioClient, msg: dict[str, Any]) -> str | None:
        """``settings`` frame fields ``handsfree`` / ``wake_word`` for this device. Returns an error message (and
        changes nothing) for an invalid value."""
        dev = self._devices.get(client) or _Device()
        armed = dev.armed
        word = dev.wake_word
        if "handsfree" in msg:
            if not isinstance(msg["handsfree"], bool):
                return "handsfree must be true or false"
            armed = msg["handsfree"]
        if "wake_word" in msg:
            raw = msg["wake_word"]
            w = raw.strip().lower() if isinstance(raw, str) else None
            if w not in WAKE_WORDS:
                return f"unknown wake word {raw!r}: use one of {', '.join(WAKE_WORDS)}"
            word = w
        self._devices[client] = dev
        if dev.armed and not armed:
            self._disarm(client, dev)
        if word != dev.wake_word and self._follow is not None and self._follow.client is client:
            self._follow = None
        dev.armed, dev.wake_word = armed, word
        log.info("hands-free %s for %s (wake word %s)", "on" if armed else "off", client.name, word)
        return None

    def _disarm(self, client: RadioClient, dev: _Device) -> None:
        dev.ring.clear()
        cap = self._capture
        if cap is not None and cap.client is client:
            self._capture = None
            self._record("aborted", "disarmed", cap.seq, client, cap.audio_s)
        if self._follow is not None and self._follow.client is client:
            self._follow = None

    def forget(self, client: RadioClient) -> None:
        """The device disconnected: its ring, capture and follow-up go (queued segments are still answered)."""
        dev = self._devices.pop(client, None)
        if dev is not None:
            self._disarm(client, dev)

    # ------------------------------------------------------------------ audio
    def on_audio(self, client: RadioClient, data: bytes, now: float) -> None:
        """Microphone frame of ``client`` (event loop; O(1) apart from a 16 kB ring trim). Discarded at once when the
        device is not armed."""
        dev = self._devices.get(client)
        if dev is None or not dev.armed:
            return
        if len(data) % 2:
            data = data[:-1]
        cap = self._capture
        if cap is not None and cap.client is client:
            cap.buf.extend(data)
            return
        hub = self.hub
        if hub.ptt_down or hub.speaking_id is not None or now < hub._gate_until or not self.active:
            if dev.ring:
                dev.ring.clear()
            return
        ring = dev.ring
        ring.extend(data)
        if len(ring) > PRE_ROLL_BYTES:
            del ring[: len(ring) - PRE_ROLL_BYTES]

    def on_vad(self, client: RadioClient, msg: dict[str, Any]) -> None:
        """``{"type":"vad","state":"start"|"end"|"abort","seq":n}`` from a device."""
        seq = msg.get("seq")
        if not isinstance(seq, int) or isinstance(seq, bool):
            client.put({"type": "error", "message": "vad frames need an integer seq"})
            return
        now = time.monotonic()
        state = msg.get("state")
        if state == "start":
            self._start(client, seq, now)
        elif state == "end":
            self._end(client, seq, now)
        elif state == "abort":
            cap = self._capture
            if cap is not None and cap.client is client and cap.seq == seq:
                self._capture = None
                why = msg.get("reason")
                why = why if isinstance(why, str) and _REASON_RE.fullmatch(why) else "device"
                self._record("aborted", why, seq, client, cap.audio_s)
                self.hub._send_state()

    def _start_block(self, client: RadioClient, now: float) -> str | None:
        """Why a segment may not start now (the first failing check, in the documented order), else ``None``."""
        hub = self.hub
        dev = self._devices.get(client)
        if dev is None or not dev.armed:
            return "not_armed"
        if not self.available:
            return "unavailable"
        if hub.ptt_down:
            return "ptt"
        cap = self._capture
        if cap is not None and cap.client is not client:
            return "other_device"
        if hub.speaking_id is not None or now < hub._gate_until:
            return "speaking"
        if hub._busy or len(self._queue) >= QUEUE_MAX:
            return "busy"
        if not self.active:
            return "paused_moving"
        if not self._transcribe.available(now):
            return "rate_limited"
        return None

    def _start(self, client: RadioClient, seq: int, now: float) -> None:
        self._refresh_motion(now)
        reason = self._start_block(client, now)
        if reason is not None:
            if reason == "paused_moving" and not self._hint_said:
                self._hint_word = self._devices[client].wake_word
            self._reject(client, seq, reason)
            return
        dev = self._devices[client]
        old = self._capture
        if old is not None:  # the same device started again without an end: the newer segment wins
            self._record("aborted", "restarted", old.seq, client, old.audio_s)
        cap = _Segment(client, seq, now, dev.wake_word, bytearray(dev.ring), len(dev.ring))
        dev.ring.clear()
        fu = self._follow
        if fu is not None and fu.client is client and fu.phase in ("grace", "window") and now <= fu.deadline:
            cap.pre_addressed = True  # the question after the wake word alone (no "Go ahead." in the grace)
            self._follow = None
        self._capture = cap
        self._event(client, "accepted", seq)
        self.hub._send_state()

    def _end(self, client: RadioClient, seq: int, now: float) -> None:
        cap = self._capture
        if cap is None or cap.client is not client or cap.seq != seq:
            return  # aborted on the server meanwhile (it already said so), or a stale seq
        self._capture = None
        cap.t_end = now
        if len(self._queue) >= QUEUE_MAX:
            dropped = self._queue.popleft()
            self._reject(dropped.client, dropped.seq, "busy", dropped.audio_s)
        self._queue.append(cap)
        if not self._draining:
            self._draining = True
            self.hub._spawn(self._drain())
        self.hub._send_state()

    def abort(self, reason: str) -> None:
        """The driver keyed push-to-talk (``reason`` "ptt"): cancel a capture and forget every pre-roll."""
        for dev in self._devices.values():
            dev.ring.clear()
        cap = self._capture
        if cap is not None:
            self._capture = None
            self._reject(cap.client, cap.seq, reason, cap.audio_s)

    def on_spoken(self, msg: RadioMessage, now: float, duration_s: float) -> None:
        """A message goes on air (``hub._deliver``): remember its words for the echo guard, cut a capture (the driver
        repeats after it) and forget every pre-roll (it would hold the radio's own voice)."""
        keep = now + max(0.0, duration_s) + ECHO_WINDOW_S
        self._spoken.append((keep, tokens(msg.text), tokens(msg.speech)))
        for dev in self._devices.values():
            dev.ring.clear()
        cap = self._capture
        if cap is not None:
            self._capture = None
            self._reject(cap.client, cap.seq, "speaking", cap.audio_s)

    # ------------------------------------------------------------------ hub hooks: driver, session, tick
    def set_driver(self, driver: Driver | None) -> None:
        """The seated driver's profile sets the scope (nobody seated: stationary only)."""
        allowed = driver is not None and bool(getattr(driver.preferences, "handsfree_while_driving", False))
        self.scope = "driving" if allowed else "stationary"
        self._follow = None

    def new_session(self) -> None:
        """A new live session: the "paused while driving" hint may be said once again."""
        self._hint_said = False
        self._hint_word = None

    def tick(self, now: float) -> None:
        """10 Hz from the hub's tick: motion, the capture watchdog, the wake-word-alone flow, the paused hint, and a
        state frame when what the devices show changed."""
        self._refresh_motion(now)
        cap = self._capture
        if cap is not None and now - cap.t0 >= CAPTURE_WATCHDOG_S:
            self._capture = None
            self._reject(cap.client, cap.seq, "too_long", cap.audio_s)
        self._tick_follow(now)
        self._tick_hint()
        while self._spoken and self._spoken[0][0] < now:
            self._spoken.popleft()
        shown = (self.available, self.armed, self.scope, self.active, self.paused, self.capturing, self.follow_up)
        if shown != self._published:
            self._published = shown
            self.hub._send_state()

    def _refresh_motion(self, now: float) -> None:
        live = self.hub.live
        self._stationary = self._motion.update(live.frame, live.connection()["status"] == "live", now)

    def _tick_follow(self, now: float) -> None:
        fu = self._follow
        if fu is None:
            return
        if fu.phase == "grace" and now >= fu.deadline:
            if self._acks.take(now):
                simple = self.hub.coaching_limits is not None and self.hub.coaching_limits.simple_wording
                msg = self._control(ACK_TEXT_SIMPLE if simple else ACK_TEXT, "hf_ack")
                fu.phase, fu.ack_id = "ack", msg.id
                task = asyncio.ensure_future(self.hub.say(msg, None, None))
                self.hub._tasks.add(task)  # strong reference, as ``hub._spawn``
                task.add_done_callback(self.hub._tasks.discard)
                fu.ack_task = task
            else:  # acknowledged a moment ago: just listen
                fu.phase, fu.deadline = "window", now + FOLLOW_UP_S
                self._event(fu.client, "follow_up", fu.seq)
        elif fu.phase == "ack":
            pending = fu.ack_task
            if (pending is None or pending.done()) and self.hub.speaking_id != fu.ack_id:
                fu.phase, fu.deadline, fu.ack_task = "window", now + FOLLOW_UP_S, None
                self._event(fu.client, "follow_up", fu.seq)
        elif fu.phase == "window" and now > fu.deadline:
            self._follow = None

    def _radio_quiet(self) -> bool:
        hub = self.hub
        if not hub.voice_enabled or not hub.clients or hub.intensity == "quiet":
            return True
        is_quiet = getattr(hub.scheduler, "is_quiet", None)
        if callable(is_quiet):
            f = hub.live.frame
            return bool(is_quiet(f.lap_number if f is not None else None))
        return False

    def _tick_hint(self) -> None:
        word = self._hint_word
        if word is None or self._hint_said or not self._stationary:
            return
        hub = self.hub
        if (
            hub.speaking_id is not None
            or hub._busy
            or hub.ptt_down
            or self._capture is not None
            or hub._held_urgent is not None
            or self._radio_quiet()
        ):
            return
        self._hint_said, self._hint_word = True, None
        simple = hub.coaching_limits is not None and hub.coaching_limits.simple_wording
        text = HINT_TEXT_SIMPLE.format(word="Pitwall" if word == "pitwall" else "Radio") if simple else HINT_TEXT
        hub._spawn(hub.say(self._control(text, "hf_paused_hint"), None, None))

    def _control(self, text: str, what: str) -> RadioMessage:
        msg = self.hub._msg(MessageKind.CONTROL, Priority.HIGH, text, bypass=True)
        msg.meta = {"intent": "handsfree", "handsfree": what, "grounded": True, "fallback": True, "facts": []}
        return msg

    # ------------------------------------------------------------------ processing
    async def _drain(self) -> None:
        try:
            while self._queue:
                seg = self._queue.popleft()
                try:
                    await self._process(seg)
                except Exception:
                    log.exception("hands-free segment %s failed", seg.seq)
        finally:
            self._draining = False
            with contextlib.suppress(Exception):
                self.hub._send_state()

    async def _process(self, seg: _Segment) -> None:
        hub = self.hub
        client, seq, audio_s = seg.client, seg.seq, seg.audio_s
        if seg.speech_s < MIN_SPEECH_S:
            self._reject(client, seq, "too_short", audio_s)
            return
        if seg.speech_s > MAX_SPEECH_S:
            self._reject(client, seq, "too_long", audio_s)
            return
        pcm = bytes(seg.buf)
        if SEGMENT_GATE.speech_span(pcm16_to_float32(pcm), MIC_SAMPLE_RATE) is None:
            self._reject(client, seq, "no_speech", audio_s)
            return
        if not self._transcribe.take(time.monotonic()):
            self._reject(client, seq, "rate_limited", audio_s)
            return
        try:
            res = await asyncio.to_thread(hub.stt.transcribe, AudioClip(pcm, MIC_SAMPLE_RATE), None)
        except Exception as e:
            log.warning("hands-free: speech recognition failed (%s)", type(e).__name__)
            self._reject(client, seq, "stt_error", audio_s)
            now = time.monotonic()
            if now - self._last_error_mono >= ERROR_FRAME_EVERY_S:
                self._last_error_mono = now
                hub._broadcast({"type": "error", "message": f"hands-free: speech recognition failed: {e}"})
            return
        self.counts["heard"] += 1
        text = res.text.strip()
        now = time.monotonic()
        if not text:
            self._reject(client, seq, "no_speech", audio_s, stt_ms=res.latency_ms)
            return
        if self._is_echo(text, now):
            self._ignore(client, seq, "echo", audio_s, res.latency_ms)
            return
        m = match_wake(text, seg.wake)
        pre = seg.pre_addressed or self._follows_trigger(seg)
        if m is None and not pre:
            self._ignore(client, seq, "not_addressed", audio_s, res.latency_ms)
            return
        if m is not None and m.trigger_only:
            self._addressed(seg, res.latency_ms)
            self._open_trigger(seg)
            return
        if not self._answers.take(now):
            self._reject(client, seq, "answer_limit", audio_s, stt_ms=res.latency_ms)
            return
        question = m.question if m is not None else text
        self._addressed(seg, res.latency_ms)
        hub._broadcast(
            {
                "type": "transcript",
                "text": question,
                "stt_ms": res.latency_ms,
                "audio_s": round(audio_s, 2),
                "source": "handsfree",
                "wake": seg.wake,
            }
        )
        hub._observe(  # validation kit hook: only addressed speech is ever observed with text
            "transcript",
            lambda: {
                "text": question,
                "stt_ms": res.latency_ms,
                "audio_s": round(audio_s, 2),
                "ptt_source": "handsfree",
                "source": "handsfree",
                "wake": seg.wake,
            },
        )
        hub.history.appendleft({"role": "driver", "text": question, "t": time.time()})
        from pitwall.voice.hub import LatencyRecord  # runtime import: hub imports this module

        rec = LatencyRecord(kind="question", text=question, audio_s=round(audio_s, 2), stt_ms=res.latency_ms)
        await hub._answer(question, rec, seg.t_end)

    def _follows_trigger(self, seg: _Segment) -> bool:
        """The segment started inside the open follow-up of its device (it may have been captured while the wake word
        alone was still being transcribed). Consumes the follow-up."""
        fu = self._follow
        if fu is None or fu.client is not seg.client or fu.phase not in ("grace", "window") or seg.t0 > fu.deadline:
            return False
        self._follow = None
        return True

    def _open_trigger(self, seg: _Segment) -> None:
        """The wake word alone: a segment of the same device that started within ``TRIGGER_GRACE_S`` of its end is the
        question (no acknowledgement); otherwise "Go ahead." follows the grace (``_tick_follow``)."""
        deadline = seg.t_end + TRIGGER_GRACE_S
        cap = self._capture
        if cap is not None and cap.client is seg.client and cap.t0 <= deadline:
            cap.pre_addressed = True
            return
        for queued in self._queue:
            if queued.client is seg.client and queued.t0 <= deadline:
                queued.pre_addressed = True
                return
        self._follow = _FollowUp(seg.client, seg.seq, seg.wake, "grace", deadline)
        self._event(seg.client, "follow_up", seg.seq)
        self.hub._send_state()

    def _is_echo(self, text: str, now: float) -> bool:
        heard = tokens(text)
        return any(is_echo(heard, said) or is_echo(heard, speech) for keep, said, speech in self._spoken if keep >= now)

    # ------------------------------------------------------------------ outcomes (never any text)
    def _addressed(self, seg: _Segment, stt_ms: int) -> None:
        self.counts["addressed"] += 1
        self._event(seg.client, "addressed", seg.seq, audio_s=seg.audio_s, wake=seg.wake, stt_ms=stt_ms)

    def _ignore(self, client: RadioClient, seq: int, reason: str, audio_s: float, stt_ms: int) -> None:
        self.counts["ignored"] += 1
        self._event(client, "ignored", seq, reason=reason, audio_s=audio_s, stt_ms=stt_ms)

    def _reject(
        self, client: RadioClient, seq: int, reason: str, audio_s: float | None = None, stt_ms: int | None = None
    ) -> None:
        self.counts["rejected"] += 1
        self._event(client, "rejected", seq, reason=reason, audio_s=audio_s, stt_ms=stt_ms)

    def _record(self, event: str, reason: str | None, seq: int, client: RadioClient, audio_s: float | None) -> None:
        """Diagnostics only (no frame to the device): counters per reason and the recent-event log."""
        key = reason or event
        if key not in self._reasons and len(self._reasons) >= _MAX_REASONS:
            key = "other"
        self._reasons[key] = self._reasons.get(key, 0) + 1
        entry: dict[str, Any] = {"t": round(time.time(), 3), "event": event, "seq": seq, "client": client.name}
        if reason is not None:
            entry["reason"] = reason
        if audio_s is not None:
            entry["audio_s"] = round(audio_s, 2)
        self._events.appendleft(entry)

    def _event(
        self,
        client: RadioClient,
        event: str,
        seq: int,
        *,
        reason: str | None = None,
        audio_s: float | None = None,
        wake: str | None = None,
        stt_ms: int | None = None,
    ) -> None:
        frame: dict[str, Any] = {"type": "handsfree", "event": event, "seq": seq}
        if reason is not None:
            frame["reason"] = reason
        if audio_s is not None:
            frame["audio_s"] = round(audio_s, 2)
        if wake is not None:
            frame["wake"] = wake
        client.put(frame)
        if event != "accepted":
            self._record(event, reason, seq, client, audio_s)
        level = logging.INFO if event in ("addressed", "follow_up") else logging.DEBUG
        log.log(level, "hands-free %s seq=%d reason=%s audio=%s stt_ms=%s", event, seq, reason, audio_s, stt_ms)
        self.hub._observe(  # validation kit hook: no text
            "handsfree",
            lambda: {"event": event, "seq": seq, "reason": reason, "audio_s": audio_s, "client": client.name},
        )


__all__ = [
    "DEFAULT_WAKE_WORD",
    "WAKE_WORDS",
    "HandsFreeController",
    "MotionGate",
    "RateBudget",
    "WakeMatch",
    "is_echo",
    "levenshtein",
    "match_wake",
    "tokens",
]
