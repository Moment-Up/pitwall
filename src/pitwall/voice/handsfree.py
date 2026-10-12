"""Hands-free talking (lane handsfree): the radio answers when the driver starts with the wake word.

Push-to-talk stays the default. A device that turns hands-free on (``settings`` frame: ``handsfree``, ``wake_word``)
runs a small energy voice-activity detector in the browser and tells the server when speech starts and ends (``vad``
frames, docs/voice-protocol.md). The server keeps the last ``PRE_ROLL_S`` of that device's microphone in a ring
buffer, captures the segment, transcribes it, and answers only when the transcript starts with the wake word
("Pitwall" by default, or "Radio"). Everything else is thrown away at once: never shown, stored or logged (logs and
observers carry reasons, lengths, levels and counts only, never ignored text).

Safety and politeness:

* **Off by default** on every device, and refused on the server with ``PITWALL_VOICE_HANDSFREE=false``.
* **Stationary scope by default.** Hands-free listens only while the car is stationary (``MotionGate``, a port of
  Drive's hysteresis rule in ``web-react/src/lib/drive/motion.ts``) until the seated driver's profile allows
  "Hands-free while driving" (``DriverPreferences.handsfree_while_driving``). A recording still running when the car
  moves off is dropped. On real captures the car is still for only 0-28 % of a race (docs/research/handsfree.md).
  With no game data at all the car counts as stationary (any game, or telemetry not set up); a stream that stops
  while the car moves counts as moving for ``STALE_STILL_AFTER_S`` more (an incident or a flashback, not a menu).
* **Half-duplex.** A segment cannot start while the radio speaks or in its gate tail, and a message going on air ends
  a capture: a long enough one that started with the wake word gets "Say again?" once the radio is free, anything
  else is dropped. A transcript that repeats something the radio said in the last ``ECHO_WINDOW_S`` is dropped (some
  engineer lines start with "Pitwall" or "Radio").
* **Holds the radio.** While a device records, a segment waits for the speech engine, or the wake word alone waits for
  its question, non-urgent radio messages wait (``holds_radio``); urgent calls and braking calls never do.
* **Budgets.** At most ``TRANSCRIBE_LIMIT`` transcriptions and ``ANSWER_LIMIT`` answers a minute, one acknowledgement
  ("Go ahead.", "Say again?") every ``ACK_WINDOW_S``, and error frames at most once a minute.
* **Calm moments only.** On track, "Go ahead." and "Say again?" wait for a speak window (``speak_window_ok``); the
  once-per-session "paused while driving" hint waits for a settled stop (``HINT_SETTLE_S``), a quiet radio and no
  held message, is re-checked after synthesis, never bypasses quiet mode and is a message a braking call may cut.
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
from collections.abc import Coroutine
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any, Literal

import numpy as np

from pitwall.ai.engineer import Intent, detect_intent
from pitwall.ai.facts import FactSheet
from pitwall.model.telemetry import CarFrame, FrameQuality
from pitwall.voice.scheduler import SPEECH_LATENCY_S, speak_window_ok
from pitwall.voice.stt import _FILLER_RE as _STT_FILLER_RE
from pitwall.voice.stt import EnergyGate, pcm16_to_float32
from pitwall.voice.types import MIC_SAMPLE_RATE, AudioClip, MessageKind, Priority, RadioMessage

if TYPE_CHECKING:
    from numpy.typing import NDArray

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
# -50 dBFS: the browser's own floor for a segment start and push-to-talk's gate, so speech the device heard is not
# thrown away here as "no_speech" (the level of every segment is in the diagnostics: handsfree_diag.events)
SEGMENT_GATE = EnergyGate(min_clip_s=0.4, min_voiced_s=0.3, threshold_dbfs=-50.0)
CLIPPED_PRE_ROLL_BYTES = PRE_ROLL_BYTES // 2  # less pre-roll than this: the wake word's first sound may be missing

# --- budgets ---------------------------------------------------------------------------------------------------------
TRANSCRIBE_LIMIT, TRANSCRIBE_WINDOW_S = 12, 60.0
ANSWER_LIMIT, ANSWER_WINDOW_S = 6, 60.0
ACK_LIMIT, ACK_WINDOW_S = 1, 20.0
ERROR_FRAME_EVERY_S = 60.0
STT_RETRY_S = 30.0  # the speech engine failed to load: try again this often while a device listens

# --- echo guard ------------------------------------------------------------------------------------------------------
ECHO_WINDOW_S = 10.0  # after a message finished (estimated): its words may still come back through the mic
ECHO_RATIO = 0.8
ECHO_MIN_TOKENS = 3

# --- the wake word alone, and a question cut by the radio ------------------------------------------------------------
TRIGGER_GRACE_S = 1.2  # "Pitwall ... what's my fuel?": wait this long for the question before saying "Go ahead."
ACK_WAIT_S = 2.0  # "Go ahead." waits this long after the grace for a free radio / a calm stretch, else listens silently
FOLLOW_UP_S = 6.0  # after "Go ahead." ends, the next segment of that device needs no wake word (once)
CUT_CHECK_MIN_S = 0.8  # a capture the radio cut after this much speech is transcribed: "Say again?" if it was addressed
SAY_AGAIN_WAIT_S = 6.0  # "Say again?" waits this long for a free radio / a calm stretch, else it is not said
REPLY_S = 1.0  # spoken length allowed for "Go ahead." / "Say again?" in the speak-window check
REPLY_POLL_S = 0.1

# --- motion (port of web-react/src/lib/drive/motion.ts) --------------------------------------------------------------
STOP_BELOW_KPH = 3.0
STOP_AFTER_S = 1.5
MOVE_ABOVE_KPH = 8.0
# A stream that stops while the car moves: still moving for this long after the hub sees it stale (2 s after the
# last packet). Real incident gaps (a spin, a flashback) last 2.4-3.7 s and the car drives on; a menu lasts longer.
STALE_STILL_AFTER_S = 5.0
_NOT_DRIVING = int(FrameQuality.PAUSED | FrameQuality.REPLAY_OR_SPECTATING)

# --- radio messages (section 4.5) ------------------------------------------------------------------------------------
ACK_TEXT = "Go ahead."
ACK_TEXT_SIMPLE = "Go ahead, I'm listening."
SAY_AGAIN_TEXT = "Say again?"
HINT_TEXT = "Hands-free only listens when you stop. Your driver profile can turn it on for driving."
HINT_WHEEL = " On track, use your wheel button."  # F1 25's UDP Action button was used this session
HINT_REMOTE = " On track, use your talk button."  # a learned Bluetooth button was used this session
HINT_TEXT_SIMPLE = "I can't hear you while you drive. Ask me when you stop."
HINT_SETTLE_S = 8.0  # the hint waits for a stop this long (an incident or the grid before lights out is shorter)
HINT_QUIET_S = 3.0  # ...and this much silence on the radio (the scheduler's own 2 s gap goes first)
# Push-to-talk on Windows while the speech model is still downloading or loading (hub._handle_utterance)
STT_STARTING_REPLY = "Speech recognition is still starting. Type it, or try again in a minute."
# Answered without a session (hub._answer): a radio check, and quiet / resume without a lap count
NO_SESSION_INTENTS = frozenset({"radio_check", "control_quiet", "control_resume"})

# Rejection / outcome codes (docs/voice-protocol.md). "rejected" = never transcribed or not answered for a reason;
# "ignored" = transcribed and silently dropped (not addressed to the radio, or the radio's own echo).
START_REASONS = ("not_armed", "unavailable", "ptt", "other_device", "speaking", "busy", "paused_moving", "rate_limited")
IGNORED_REASONS = ("echo", "not_addressed")


# ============================================================================================ wake word
# before the wake word; after it "right" is only a filler when nothing else follows ("Pitwall, right front tyre?")
_FILLERS = frozenset({"hey", "hi", "ok", "okay", "oi", "right", "so", "um", "uh", "er", "erm", "ah", "oh", "yeah"})
# a clipped onset: "Pitwall" heard as "A pit wall" / "K pit wall" (docs/research/handsfree.md section 3.3)
_PITWALL_FILLERS = frozenset({"a", "k"})
_RADIO_FORMS = frozenset({"radio", "radios", "radio's"})
# second words of a two-word "Pitwall" ("pit wall", "big wall", "pit well"); any other second word ("hit all", "fit
# all") only counts within one edit of "pitwall"
_WALL_FORMS = frozenset({"wall", "walls", "well", "ball", "bull", "fall", "mall", "mull", "wal"})
# "Pitwall" with its first sound missing (too little pre-roll): only with a racing question after it
_CLIPPED_FORMS = frozenset({"wall", "well", "twell", "twall"})
_IT_ALL_RE = re.compile(r"\W*(?:(?:hey|ok|okay|a|k)\W+)?(it\s*all)\s*(?=[,.!?])")  # "It all, what's my fuel?"
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)*")
_QUESTION_STRIP = " ,.;:!?-–—…"
_WORD_CHAR_RE = re.compile(r"\w")
_APOSTROPHES = "‘’ʼ"  # curly and modifier apostrophes fold to "'"
_REASON_RE = re.compile(r"[a-z_]{1,24}")  # a device's own abort reason ("suppressed"), kept for diagnostics
_MAX_REASONS = 64

# how strongly the start of a transcript matched the wake word
_STRONG, _WEAK, _CLIPPED = 0, 1, 2


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


def _is_filler(token: str, word: str) -> bool:
    """A word said before the wake word or before the question: "hey", "ok", "um", "uh-huh" sounds, and for "Pitwall"
    the "a" / "k" a clipped onset leaves."""
    return (
        token in _FILLERS
        or _STT_FILLER_RE.fullmatch(token) is not None
        or (word == "pitwall" and token in _PITWALL_FILLERS)
    )


def _pitwall_distance(candidate: str) -> int | None:
    """How far a candidate is from "pitwall" when it counts as the wake word, else ``None``.

    Speech engines hear "Pitwall" as "Pit wall", "Pigwall", "Bidwall", "Big wall", "Tidwall", "Hitwall", "It wall",
    "Pitbull", "Pitfall"... (docs/research/handsfree.md section 3.3): a candidate counts when it is "pitwall" or
    "itwall", or starts with p/b/t/d/h/f/k, has 5-9 characters and is within 2 edits."""
    if candidate in ("pitwall", "itwall"):
        return 0
    if candidate[:1] in ("p", "b", "t", "d", "h", "f", "k") and 5 <= len(candidate) <= 9:
        d = levenshtein(candidate, "pitwall")
        return d if d <= 2 else None
    return None


def _wake_span(folded: str, toks: list[tuple[str, int]], word: str, clipped: bool) -> tuple[int, int] | None:
    """``(folded index just after the wake word, strength)`` when the folded text starts with ``word``, else ``None``.

    Up to two leading fillers are skipped. Strong: "pitwall" within one edit (on the next two words joined, or the next
    word alone; the closer wins, the two-word span on a tie), or "radio" / "radios" / "radio's". Weak: two edits from
    "pitwall" ("Big wall", "Paywall"), "It all," with punctuation after it, or one edit from "radio" ("Ratio").
    Clipped (only when ``clipped``): "Wall", "Well", "Twell" as the first word."""
    i = 0
    while i < len(toks) and i < 2 and _is_filler(toks[i][0], word):
        i += 1
    if word == "radio":
        if i < len(toks):
            tok, end = toks[i]
            if tok in _RADIO_FORMS:
                return end, _STRONG
            if tok[:1] == "r" and 4 <= len(tok) <= 7 and levenshtein(tok, "radio") <= 1:
                return end, _WEAK
        return None
    best: tuple[int, int] | None = None  # (distance, n words)
    for n in (2, 1):
        if len(toks) - i < n:
            continue
        d = _pitwall_distance("".join(t for t, _ in toks[i : i + n]))
        if d is None or (n == 2 and d > 1 and toks[i + 1][0] not in _WALL_FORMS):
            continue  # "hit all", "fit all": two words only count as "pit wall" when the second sounds like "wall"
        if best is None or d < best[0]:
            best = (d, n)
    if best is not None:
        return toks[i + best[1] - 1][1], _STRONG if best[0] <= 1 else _WEAK
    mm = _IT_ALL_RE.match(folded)
    if mm is not None:
        return mm.end(1), _WEAK
    if clipped and i < len(toks) and toks[i][0] in _CLIPPED_FORMS:
        return toks[i][1], _CLIPPED
    return None


def _question_after(text: str, word: str) -> str:
    """The question in ``text`` (what followed the wake word): without the fillers and punctuation it starts with
    ("um, what's my fuel?" -> "what's my fuel?"), and "" when it is only fillers ("um.", "right.", "OK?"). A leading
    "right" stays when more follows ("right front tyre?")."""
    folded, index = _fold(text)
    words = list(_TOKEN_RE.finditer(folded))
    if all(_is_filler(m.group(0), word) or m.group(0) == "right" for m in words):
        return ""
    cut = 0
    for m in words:
        if m.group(0) == "right" or not _is_filler(m.group(0), word):
            break
        cut = index[m.end() - 1] + 1
    return text[cut:].lstrip(_QUESTION_STRIP).strip()


@dataclass(frozen=True, slots=True)
class WakeMatch:
    word: str  # the wake word matched ("pitwall" | "radio")
    question: str  # the original text after the wake word and any fillers ("" when nothing follows)

    @property
    def trigger_only(self) -> bool:
        """The wake word alone ("Pitwall.", "Pitwall, um."): no word characters after it."""
        return _WORD_CHAR_RE.search(self.question) is None


def match_wake(text: str, word: str, clipped: bool = False) -> WakeMatch | None:
    """Does ``text`` start with the wake word ``word``? Returns the question after it, else ``None``.

    Up to two leading fillers ("hey", "ok", "um"...) are skipped, and fillers after the wake word are not part of the
    question ("Pitwall, um." is the wake word alone). A strong match takes any question. A weak one (two edits away,
    "It all,", "Ratio") or, when ``clipped`` (the segment had little pre-roll, so the first sound may be missing), a
    first word "Wall" / "Well" counts only before a recognisable racing question (an intent other than "general"), or
    - weak only - alone. "radio" is one word only; when the whole text is a radio check ("Radio check"), the question
    is the whole text, so the engineer answers it.
    """
    if word not in WAKE_WORDS:
        raise ValueError(f"unknown wake word {word!r}")
    folded, index = _fold(text)
    toks = [(m.group(0), m.end()) for m in _TOKEN_RE.finditer(folded)]
    span = _wake_span(folded, toks, word, clipped)
    if span is None:
        return None
    end, strength = span
    if word == "radio" and detect_intent(text).name == "radio_check":
        return WakeMatch(word, text.strip())
    m = WakeMatch(word, _question_after(text[index[end - 1] + 1 :], word))
    if strength != _STRONG:
        if m.trigger_only:
            return m if strength == _WEAK else None
        if detect_intent(m.question).name == "general":
            return None
    return m


def _starts_with_wake(words: list[str], word: str) -> bool:
    """Normalised words (``tokens``) start with the wake word, however weakly (the echo guard's test)."""
    text = " ".join(words)
    return _wake_span(text, [(m.group(0), m.end()) for m in _TOKEN_RE.finditer(text)], word, False) is not None


def no_session_sheet(intent: Intent) -> FactSheet | None:
    """An empty fact sheet for what needs no session (``hub._answer`` before any lap): a radio check, and "quiet" or
    "resume" without a lap count ("quiet for 3 laps" needs a lap to count from). ``None`` otherwise."""
    if intent.name in NO_SESSION_INTENTS and intent.quiet_laps is None:
        return FactSheet()
    return None


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

    * stationary: no frame (no game data at all), a paused or replay frame, data that is not live (stale: the game is
      in a menu or paused the stream; after ``STALE_STILL_AFTER_S`` when the car was moving), or a known speed under
      ``STOP_BELOW_KPH`` for ``STOP_AFTER_S`` (at once in the pit lane or the garage, ``pit_status`` 1 or 2, or
      straight after a stop).
    * moving: a known speed over ``MOVE_ABOVE_KPH``.

    Between the thresholds, or with an unknown speed, the previous answer stands; with nothing before it the car is
    not known to be stationary (moving: the safe side). A single 8 km/h line flipped up to 22 times in 5.6 minutes
    of a real race; this rule flips 1-12 times per capture (docs/research/handsfree.md section 3.1)."""

    stationary: bool | None = None
    slow_since: float | None = None
    stale_since: float | None = None  # the data went stale while the car was moving

    def update(self, frame: CarFrame | None, live: bool, now: float) -> bool:
        flagged = frame is not None and bool(int(frame.quality) & _NOT_DRIVING)
        if frame is not None and not live and not flagged and self.stationary is False:
            since = self.stale_since if self.stale_since is not None else now
            if now - since < STALE_STILL_AFTER_S:
                self.stale_since = since
                return False  # an incident gap: the car is about to drive on
        if frame is None or not live or flagged:
            self.stationary, self.slow_since, self.stale_since = True, None, None
            return True
        self.stale_since = None
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


# ============================================================================================ audio level
def segment_level(samples: NDArray[np.float32]) -> tuple[float, float]:
    """``(loudest 20 ms frame in dBFS, voiced seconds over SEGMENT_GATE's threshold)``, measured as the gate does
    (frame standard deviation). For the diagnostics: why a segment was or was not speech."""
    frame = max(1, round(SEGMENT_GATE.frame_s * MIC_SAMPLE_RATE))
    n = samples.size // frame
    if n == 0:
        return -120.0, 0.0
    level = samples[: n * frame].reshape(n, frame).std(axis=1)
    peak = float(level.max())
    voiced = int(np.count_nonzero(level > 10.0 ** (SEGMENT_GATE.threshold_dbfs / 20.0)))
    return (round(20.0 * math.log10(peak), 1) if peak > 1e-6 else -120.0), round(voiced * frame / MIC_SAMPLE_RATE, 2)


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
    cut: bool = False  # a message went on air mid-sentence: transcribed only to decide on "Say again?"

    @property
    def audio_s(self) -> float:
        return len(self.buf) / 2 / MIC_SAMPLE_RATE

    @property
    def speech_s(self) -> float:
        return (len(self.buf) - self.preroll) / 2 / MIC_SAMPLE_RATE


@dataclass(slots=True, eq=False)
class _FollowUp:
    """The wake word alone was heard: "grace" (the question may still come; then "Go ahead." waits for a free radio and,
    on track, a calm stretch), "ack" ("Go ahead." being synthesised or on air), "window" (the next segment of that
    device needs no wake word until ``deadline``)."""

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
        self._still_since: float | None = None  # monotonic time the car last became stationary
        self._capture: _Segment | None = None
        self._queue: deque[_Segment] = deque()
        self._draining = False
        self._transcribe = RateBudget(TRANSCRIBE_LIMIT, TRANSCRIBE_WINDOW_S)
        self._answers = RateBudget(ANSWER_LIMIT, ANSWER_WINDOW_S)
        self._acks = RateBudget(ACK_LIMIT, ACK_WINDOW_S)
        self._spoken: deque[tuple[float, list[str], list[str]]] = deque(maxlen=32)  # (keep until, text, speech)
        self._follow: _FollowUp | None = None
        self._reply: asyncio.Task[None] | None = None  # "Say again?" waiting for a free radio
        self._hint_word: str | None = None  # a start was refused while moving: say the hint at the next settled stop
        self._hint_said = False  # once per session
        self._hint_task: asyncio.Task[None] | None = None
        self._ptt_sources: set[str] = set()  # push-to-talk sources used this session (the hint names the button)
        self._last_error_mono = -math.inf
        self._next_stt_try = time.monotonic() + STT_RETRY_S
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
    def holds_radio(self) -> bool:
        """Non-urgent radio messages wait: a device is recording, a segment waits for (or is in) the speech engine, the
        wake word alone waits for its question, or "Say again?" waits for its moment. Urgent and braking calls never
        wait (the hub's ``_tick`` / ``_after_synthesis``)."""
        return (
            self._capture is not None
            or bool(self._queue)
            or self._draining
            or self._follow is not None
            or self._reply is not None
        )

    @property
    def stationary(self) -> bool:
        return self._stationary

    def unavailable_reason(self) -> str | None:
        """Why the server cannot listen hands-free, else ``None``. A speech engine still downloading or loading its
        model says "starting: ..." (the device shows "Hands-free starting" with it)."""
        if not self.enabled:
            return "switched off on the server (PITWALL_VOICE_HANDSFREE=false)"
        why = self.hub._stt_unavailable()
        if why is not None:
            return f"needs speech recognition: {why}"
        stt = self.hub.stt
        if getattr(stt, "loaded", True) is not False:
            return None
        error = getattr(stt, "last_error", None)
        if getattr(stt, "loading", False) or not error:
            percent = getattr(stt, "download_percent", None)
            pct = percent() if callable(percent) else None
            if isinstance(pct, int):
                return f"starting: downloading the speech model ({pct} %)"
            return "starting: loading the speech model"
        return f"speech recognition failed to start: {error}"

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
        """``/api/voice/status`` ``handsfree_diag``: counters per reason, the last 20 events (never any text: reasons,
        lengths and levels) and the server thresholds."""
        now = time.monotonic()
        still = self._still_since
        return {
            "reasons": dict(self._reasons),
            "events": list(self._events),
            "stationary": self._stationary,
            "stationary_for_s": round(now - still, 1) if self._stationary and still is not None else None,
            "holds_radio": self.holds_radio,
            "queue": len(self._queue),
            "processing": self._draining,
            "hint": "said" if self._hint_said else ("due" if self._hint_word is not None else None),
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
                "segment_min_voiced_s": SEGMENT_GATE.min_voiced_s,
                "transcriptions_per_min": TRANSCRIBE_LIMIT,
                "answers_per_min": ANSWER_LIMIT,
                "ack_every_s": ACK_WINDOW_S,
                "echo_window_s": ECHO_WINDOW_S,
                "trigger_grace_s": TRIGGER_GRACE_S,
                "follow_up_s": FOLLOW_UP_S,
                "cut_check_min_s": CUT_CHECK_MIN_S,
                "stop_below_kph": STOP_BELOW_KPH,
                "stop_after_s": STOP_AFTER_S,
                "move_above_kph": MOVE_ABOVE_KPH,
                "stale_still_after_s": STALE_STILL_AFTER_S,
                "hint_settle_s": HINT_SETTLE_S,
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
            self._drop_follow()
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
            self._drop_follow()

    def forget(self, client: RadioClient) -> None:
        """The device disconnected: its ring, capture and follow-up go (queued segments are still answered)."""
        dev = self._devices.pop(client, None)
        if dev is not None:
            self._disarm(client, dev)

    def close(self) -> None:
        """The hub stops: nothing more is said or waited for."""
        self._drop_follow()
        for task in (self._reply, self._hint_task):
            if task is not None and not task.done():
                task.cancel()
        self._reply = self._hint_task = None

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
        reply = self._reply
        if reply is not None and not reply.done():
            reply.cancel()  # "Say again?" not said yet: the driver is already repeating
            self._reply = None
        fu = self._follow
        if fu is not None and fu.client is client and (fu.phase != "window" or now <= fu.deadline):
            # the question after the wake word alone: in the grace, while "Go ahead." waits or is being synthesised
            # (it is then not said: the driver is already talking), or in the window after it
            cap.pre_addressed = True
            self._drop_follow()
        self._capture = cap
        self._event(client, "accepted", seq)
        self.hub._send_state()

    def _end(self, client: RadioClient, seq: int, now: float) -> None:
        cap = self._capture
        if cap is None or cap.client is not client or cap.seq != seq:
            return  # aborted on the server meanwhile (it already said so), or a stale seq
        self._capture = None
        cap.t_end = now
        self._enqueue(cap)
        self.hub._send_state()

    def _enqueue(self, seg: _Segment) -> None:
        if len(self._queue) >= QUEUE_MAX:
            dropped = self._queue.popleft()
            self._reject(dropped.client, dropped.seq, "busy", dropped.audio_s)
        self._queue.append(seg)
        if not self._draining:
            self._draining = True
            self.hub._spawn(self._drain())

    def abort(self, reason: str, source: str | None = None) -> None:
        """The driver keyed push-to-talk (``reason`` "ptt", ``source`` "screen" / "remote" / "wheel"): cancel a
        capture and forget every pre-roll."""
        if source is not None:
            self._ptt_sources.add(source)
        for dev in self._devices.values():
            dev.ring.clear()
        cap = self._capture
        if cap is not None:
            self._capture = None
            self._reject(cap.client, cap.seq, reason, cap.audio_s)

    def on_spoken(self, msg: RadioMessage, now: float, duration_s: float) -> None:
        """A message goes on air (``hub._deliver``; also a braking call's path: O(1)): remember its words for the echo
        guard, forget every pre-roll (it would hold the radio's own voice) and end a capture. A capture with at least
        ``CUT_CHECK_MIN_S`` of speech is still transcribed: "Say again?" if it was addressed to the radio."""
        keep = now + max(0.0, duration_s) + ECHO_WINDOW_S
        self._spoken.append((keep, tokens(msg.text), tokens(msg.speech)))
        for dev in self._devices.values():
            dev.ring.clear()
        cap = self._capture
        if cap is not None:
            self._capture = None
            if cap.speech_s >= CUT_CHECK_MIN_S and len(self._queue) < QUEUE_MAX:
                cap.cut, cap.t_end = True, now
                self._enqueue(cap)
            else:
                self._reject(cap.client, cap.seq, "speaking", cap.audio_s)

    # ------------------------------------------------------------------ hub hooks: driver, session, tick
    def set_driver(self, driver: Driver | None) -> None:
        """The seated driver's profile sets the scope (nobody seated: stationary only)."""
        allowed = driver is not None and bool(getattr(driver.preferences, "handsfree_while_driving", False))
        self.scope = "driving" if allowed else "stationary"
        self._drop_follow()

    def new_session(self) -> None:
        """A new live session: the "paused while driving" hint may be said once again."""
        self._hint_said = False
        self._hint_word = None
        self._ptt_sources.clear()

    def tick(self, now: float) -> None:
        """10 Hz from the hub's tick: motion (a recording or a follow-up of the stationary scope ends when the car
        moves), the capture watchdog, the wake-word-alone flow, the paused hint, a stalled speech engine, and a state
        frame when what the devices show changed."""
        self._refresh_motion(now)
        if self.paused is not None:
            self._pause_listening()
        cap = self._capture
        if cap is not None and now - cap.t0 >= CAPTURE_WATCHDOG_S:
            self._capture = None
            self._reject(cap.client, cap.seq, "too_long", cap.audio_s)
        self._tick_follow(now)
        self._tick_hint(now)
        self._kick_stt(now)
        while self._spoken and self._spoken[0][0] < now:
            self._spoken.popleft()
        shown = (
            self.available,
            self.unavailable_reason(),
            self.armed,
            self.scope,
            self.active,
            self.paused,
            self.capturing,
            self.follow_up,
        )
        if shown != self._published:
            self._published = shown
            self.hub._send_state()

    def _refresh_motion(self, now: float) -> None:
        live = self.hub.live
        was = self._stationary if self._still_since is not None else False
        self._stationary = self._motion.update(live.frame, live.connection()["status"] == "live", now)
        if not self._stationary:
            self._still_since = None
        elif not was:
            self._still_since = now

    def _pause_listening(self) -> None:
        """The stationary scope and the car moves: a recording in progress is dropped (it would be answered on track)
        and so is a pending follow-up."""
        cap = self._capture
        if cap is not None:
            self._capture = None
            self._reject(cap.client, cap.seq, "paused_moving", cap.audio_s)
        if self._follow is not None:
            self._drop_follow()

    def _drop_follow(self) -> None:
        fu = self._follow
        self._follow = None
        if fu is not None and fu.ack_task is not None and not fu.ack_task.done():
            fu.ack_task.cancel()  # "Go ahead." not on air yet: not said

    def _latency_s(self) -> float:
        lat = getattr(self.hub.scheduler, "speech_latency_s", SPEECH_LATENCY_S)
        return float(lat) if isinstance(lat, int | float) and math.isfinite(lat) else SPEECH_LATENCY_S

    def _may_reply(self) -> bool:
        """ "Go ahead." / "Say again?" may go now: nothing on air or being answered, the driver is not transmitting or
        recording, and the car is stationary or on a calm stretch long enough for it (``speak_window_ok``)."""
        hub = self.hub
        if hub.ptt_down or hub.speaking_id is not None or hub._busy or self._capture is not None:
            return False
        if self._stationary or not hub.moving():
            return True
        return speak_window_ok(hub.driving_state(), REPLY_S, self._latency_s())

    def _task(self, coro: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        task = asyncio.ensure_future(coro)
        self.hub._tasks.add(task)  # strong reference, as ``hub._spawn``
        task.add_done_callback(self.hub._tasks.discard)
        return task

    def _tick_follow(self, now: float) -> None:
        fu = self._follow
        if fu is None:
            return
        if fu.phase == "grace" and now >= fu.deadline:
            if not self._acks.available(now):  # acknowledged a moment ago: just listen
                self._open_window(fu, now)
            elif not self._may_reply():
                if now >= fu.deadline + ACK_WAIT_S:  # no moment for "Go ahead.": listen without it
                    self._open_window(fu, now)
            else:
                self._acks.take(now)
                simple = self.hub.coaching_limits is not None and self.hub.coaching_limits.simple_wording
                msg = self._control(ACK_TEXT_SIMPLE if simple else ACK_TEXT, "hf_ack")
                fu.phase, fu.ack_id = "ack", msg.id
                fu.ack_task = self._task(self.hub.say(msg, None, None))
        elif fu.phase == "ack":
            pending = fu.ack_task
            if (pending is None or pending.done()) and self.hub.speaking_id != fu.ack_id:
                self._open_window(fu, now)
        elif fu.phase == "window" and now > fu.deadline:
            self._follow = None

    def _open_window(self, fu: _FollowUp, now: float) -> None:
        fu.phase, fu.deadline, fu.ack_task = "window", now + FOLLOW_UP_S, None
        self._event(fu.client, "follow_up", fu.seq)

    def _say_again(self, now: float) -> None:
        """A question the radio cut: "Say again?" once the radio is free and, on track, a calm stretch allows it."""
        if self._reply is not None or not self._acks.take(now):
            return
        self._reply = self._task(self._reply_when_free(self._control(SAY_AGAIN_TEXT, "hf_say_again")))

    async def _reply_when_free(self, msg: RadioMessage) -> None:
        try:
            give_up = time.monotonic() + SAY_AGAIN_WAIT_S
            while not self._may_reply():
                if time.monotonic() >= give_up:
                    return
                await asyncio.sleep(REPLY_POLL_S)
            await self.hub.say(msg, None, None)
        finally:
            if self._reply is asyncio.current_task():
                self._reply = None

    def _radio_quiet(self) -> bool:
        hub = self.hub
        if not hub.voice_enabled or not hub.clients or hub.intensity == "quiet":
            return True
        is_quiet = getattr(hub.scheduler, "is_quiet", None)
        if callable(is_quiet):
            f = hub.live.frame
            return bool(is_quiet(f.lap_number if f is not None else None))
        return False

    def _hint_ready(self, now: float) -> bool:
        """The car has been still for ``HINT_SETTLE_S``, the radio is free and has been silent for ``HINT_QUIET_S``,
        nothing is held, hands-free is not busy, and the radio is not quiet."""
        hub = self.hub
        still = self._still_since
        return (
            self._stationary
            and still is not None
            and now - still >= HINT_SETTLE_S
            and hub.speaking_id is None
            and not hub._busy
            and not hub.ptt_down
            and hub._held is None
            and hub._held_urgent is None
            and now - hub._air_free_mono >= HINT_QUIET_S
            and not self.holds_radio
            and not self._radio_quiet()
        )

    def _tick_hint(self, now: float) -> None:
        if self._hint_word is None or self._hint_said or self._hint_task is not None or not self._hint_ready(now):
            return
        self._hint_task = self._task(self._say_hint())

    def _hint_message(self) -> RadioMessage:
        hub = self.hub
        if hub.coaching_limits is not None and hub.coaching_limits.simple_wording:
            text = HINT_TEXT_SIMPLE
        else:
            text = HINT_TEXT + (
                HINT_WHEEL if "wheel" in self._ptt_sources else HINT_REMOTE if "remote" in self._ptt_sources else ""
            )
        # a proactive-style message: not urgent, not a control (a braking call may cut it), never bypasses quiet mode
        msg = hub._msg(MessageKind.INFO, Priority.LOW, text)
        msg.meta = {
            "intent": "handsfree",
            "handsfree": "hf_paused_hint",
            "grounded": True,
            "fallback": True,
            "facts": [],
        }
        return msg

    async def _say_hint(self) -> None:
        """Synthesise the hint, then re-check the moment (the car may have moved off, something may be on air): said
        only if it still holds, else tried again at the next settled stop."""
        try:
            msg = self._hint_message()
            clip = await self.hub._synthesize(msg)
            now = time.monotonic()
            if self._hint_said or self._hint_word is None or not self._hint_ready(now):
                return
            self._hint_said, self._hint_word = True, None
            msg.expires_mono = now  # cut by a braking call: not said again (hub._rehold)
            self.hub._deliver(msg, clip, None, None)
        finally:
            self._hint_task = None

    def _kick_stt(self, now: float) -> None:
        """While a device listens, a speech engine that is not loaded and not loading (its load failed) is retried
        every ``STT_RETRY_S`` (the engine backs off on its own; nothing else would ask it while starts are refused)."""
        stt = self.hub.stt
        if self.armed == 0 or now < self._next_stt_try or getattr(stt, "loaded", True) is not False:
            return
        if getattr(stt, "loading", False):
            return
        self._next_stt_try = now + STT_RETRY_S
        warmup = getattr(stt, "warmup", None)
        if callable(warmup):
            self.hub._spawn(self._warm(warmup))

    @staticmethod
    async def _warm(warmup: Any) -> None:
        try:
            await asyncio.to_thread(warmup)
        except Exception as e:
            log.info("hands-free: speech recognition still not ready (%s)", type(e).__name__)

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
        samples = pcm16_to_float32(pcm)
        level = segment_level(samples)
        if SEGMENT_GATE.speech_span(samples, MIC_SAMPLE_RATE) is None:
            self._reject(client, seq, "no_speech", audio_s, level=level)
            return
        if not self._transcribe.take(time.monotonic()):
            self._reject(client, seq, "rate_limited", audio_s, level=level)
            return
        try:
            res = await asyncio.to_thread(hub.stt.transcribe, AudioClip(pcm, MIC_SAMPLE_RATE), None)
        except Exception as e:
            log.warning("hands-free: speech recognition failed (%s)", type(e).__name__)
            self._reject(client, seq, "stt_error", audio_s, level=level)
            now = time.monotonic()
            if now - self._last_error_mono >= ERROR_FRAME_EVERY_S:
                self._last_error_mono = now
                hub._broadcast({"type": "error", "message": f"hands-free: speech recognition failed: {e}"})
            return
        self.counts["heard"] += 1
        text = res.text.strip()
        now = time.monotonic()
        if not text:
            self._reject(client, seq, "no_speech", audio_s, stt_ms=res.latency_ms, level=level)
            return
        m = match_wake(text, seg.wake, clipped=seg.preroll < CLIPPED_PRE_ROLL_BYTES)
        pre = seg.pre_addressed or self._follows_trigger(seg)
        if self._is_echo(text, now, seg.wake if m is not None else None):
            self._ignore(client, seq, "echo", audio_s, res.latency_ms, level)
            return
        if m is None and (not pre or detect_intent(text).name == "general"):
            # not addressed; after the wake word alone only a question about the car or the race is taken
            self._ignore(client, seq, "not_addressed", audio_s, res.latency_ms, level)
            return
        if seg.cut:  # half a question: never answered; "Say again?" since it was addressed
            self._reject(client, seq, "speaking", audio_s, stt_ms=res.latency_ms, level=level)
            self._say_again(now)
            return
        if m is not None and m.trigger_only:
            self._addressed(seg, res.latency_ms, level)
            self._open_trigger(seg)
            return
        if not self._answers.take(now):
            self._reject(client, seq, "answer_limit", audio_s, stt_ms=res.latency_ms, level=level)
            return
        question = m.question if m is not None else text
        self._addressed(seg, res.latency_ms, level)
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
        if fu is None or fu.client is not seg.client or (fu.phase == "window" and seg.t0 > fu.deadline):
            return False
        self._drop_follow()
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

    def _is_echo(self, text: str, now: float, addressed: str | None) -> bool:
        """The radio's own words. A transcript that starts with the wake word (``addressed``) is only compared with
        lines that themselves start with it: "Pitwall, box this lap?" after "Box this lap." is a question."""
        heard = tokens(text)
        for keep, said, speech in self._spoken:
            if keep < now:
                continue
            if addressed is not None and not any(_starts_with_wake(w, addressed) for w in (said, speech)):
                continue
            if is_echo(heard, said) or is_echo(heard, speech):
                return True
        return False

    # ------------------------------------------------------------------ outcomes (never any text)
    def _addressed(self, seg: _Segment, stt_ms: int, level: tuple[float, float] | None = None) -> None:
        self.counts["addressed"] += 1
        self._event(seg.client, "addressed", seg.seq, audio_s=seg.audio_s, wake=seg.wake, stt_ms=stt_ms, level=level)

    def _ignore(
        self,
        client: RadioClient,
        seq: int,
        reason: str,
        audio_s: float,
        stt_ms: int,
        level: tuple[float, float] | None = None,
    ) -> None:
        self.counts["ignored"] += 1
        self._event(client, "ignored", seq, reason=reason, audio_s=audio_s, stt_ms=stt_ms, level=level)

    def _reject(
        self,
        client: RadioClient,
        seq: int,
        reason: str,
        audio_s: float | None = None,
        stt_ms: int | None = None,
        level: tuple[float, float] | None = None,
    ) -> None:
        self.counts["rejected"] += 1
        self._event(client, "rejected", seq, reason=reason, audio_s=audio_s, stt_ms=stt_ms, level=level)

    def _record(
        self,
        event: str,
        reason: str | None,
        seq: int,
        client: RadioClient,
        audio_s: float | None,
        level: tuple[float, float] | None = None,
    ) -> None:
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
        if level is not None:
            entry["level_dbfs"], entry["voiced_s"] = level
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
        level: tuple[float, float] | None = None,
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
            self._record(event, reason, seq, client, audio_s, level)
        lvl = level[0] if level is not None else None
        log_level = logging.INFO if event in ("addressed", "follow_up") else logging.DEBUG
        log.log(
            log_level,
            "hands-free %s seq=%d reason=%s audio=%s stt_ms=%s level=%s",
            event,
            seq,
            reason,
            audio_s,
            stt_ms,
            lvl,
        )
        self.hub._observe(  # validation kit hook: no text
            "handsfree",
            lambda: {"event": event, "seq": seq, "reason": reason, "audio_s": audio_s, "client": client.name},
        )


__all__ = [
    "DEFAULT_WAKE_WORD",
    "STT_STARTING_REPLY",
    "WAKE_WORDS",
    "HandsFreeController",
    "MotionGate",
    "RateBudget",
    "WakeMatch",
    "is_echo",
    "levenshtein",
    "match_wake",
    "no_session_sheet",
    "segment_level",
    "tokens",
]
