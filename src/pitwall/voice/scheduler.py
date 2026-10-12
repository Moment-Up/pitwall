"""Radio scheduler: decides *which* queued message the engineer says next and *whether now is a good moment*.

The product brief ranks coaching by urgency, confidence, performance impact, driver preferences, workload,
track position and whether the advice is still actionable. Confidence and impact are decided upstream when a
message is built (``proactive.py`` only emits observations that clear a confidence bar, ordered by impact);
this module enforces the rest at dispatch time. It is the radio's one arbitration policy: every proactive source
(lap summaries and coaching, goal lines, strategy calls, validation prompts) goes through it.

**Message kinds** (``MessageKind``) and who builds them. "Budget" = counts toward the per-lap talk budget; every
proactive kind waits for a speak window except urgent alerts and cues:

* ALERT - urgent alerts (red flag; skip quiet mode, the window and the gap) and the strategy alert calls
  (``strategy.radio``; the safety-car box-or-stay call and critical fuel bypass quiet mode). No budget.
* CUE - braking cues (their own timing). ANSWER, CONTROL - answers and acknowledgements (bypass quiet mode). No budget.
* LAP_SUMMARY, COACHING - ``voice.proactive`` (a later lap supersedes them). Budget; coaching is also capped per
  analysed lap.
* STRATEGY (normal calls), INFO (detailed calls) - ``strategy.radio``, topic ``strategy:<topic>``. Budget.
* GOAL - ``motivation.radio``, topic ``goal:<session>``, no lap identity. Budget.
* VALIDATION - ``validate.kit`` prompts during a validation run, topic ``validation``. No budget; said last.
* RACE - race situation calls (``raceradio``: position, countdown, lap 1, gaps, warnings, minor damage; topics
  ``race:<topic>``). Not the talk budget: their own per-lap allowance (``RACE_PER_LAP``). Race control, penalties and
  damage that matter are ALERTs (the red flag the first URGENT producer: ``voice.urgent``).

* **Intensity** (``ALLOWED_KINDS``) - quiet: answers, acknowledgements, alerts, cues and validation prompts (the
  driver opted into a validation run); normal adds the lap summary, goal lines, coaching, strategy calls and race
  calls; detailed adds INFO (strategy detail, race detail). Quiet intensity is "alerts and answers only", as its
  acknowledgement promises.
* **Urgency and order** - the queue is ordered by ``Priority``, then by ``KIND_RANK``, then first in first out. So
  a race lap is said in this order: the lap time, the strategy call, the goal line, the coaching point (practice and
  qualifying have no strategy calls: lap time, goal line, coaching). ``URGENT`` skips quiet mode, the speak window
  and the inter-message gap: by definition it is worth interrupting the driver for, and "urgent calls only" is what
  the quiet-mode acknowledgement promises.
* **Per-lap talk budget** (``TALK_PER_LAP``) - while the car is on track, at most 2 (normal) or 4 (detailed)
  messages of the ``BUDGETED`` kinds (lap summary, goal line, strategy call, coaching point, INFO) are said per
  driving lap: the lap the car is on when they are said (``DrivingState.lap_number``; the message's own lap
  identity when that is unknown). A message that does not fit stays queued until it expires or is superseded, and
  is said from the next lap's allowance if it is still alive then. Off track (garage, menus, paused) there is no
  budget: the speak window is open anyway, and the flag-time goal line or the last lap's summary must not be
  starved. Alerts, urgent calls, cues, answers, acknowledgements and validation prompts never count. The coaching
  cap per analysed lap (``COACHING_PER_LAP``) still applies on top, and so do the strategy planner's own limits and
  the goal lines' per-session cap. Race calls (RACE) have an allowance of their own (``RACE_PER_LAP``: 2 normal, 3
  detailed), counted the same way, so they never starve the lap summary or coaching, nor the other way round.
* **Interrupting** - while the radio is talking, only an ``URGENT`` message or a ``CUE`` is handed out, and only
  when it outranks the message on air (urgent > cue > everything else). The caller cancels the current playback
  and says it, so a red flag does not wait for a 6 s lap summary to finish and a braking cue does not land after
  the braking point. Equal ranks never cut each other off.
* **Still actionable** - messages past ``expires_mono`` are dropped. A lap summary / coaching point supersedes
  unspoken ones of the same kind for any *other* lap: laps are analysed in order, so the newest arrival is the
  latest lap (comparing lap numbers would break when they restart at 1 in the next session). A message with a
  ``meta["topic"]`` replaces a queued one on the same topic: newest information wins, so "fuel critical"
  replaces an unsaid "fuel is tight". An identical sentence is not repeated within ``repeat_window_s``. Three
  kinds are exempt and rely on id dedupe: driver-initiated answers/acks (the driver asked), cues (short and
  repetitive by nature) and urgent alerts (a second incident is news).
* **Order within a lap** - a lap's coaching waits while that lap's summary is still queued and allowed. A short
  straight therefore never puts the coaching point before the lap time it explains. A goal line is a GOAL with no
  lap identity, so it never holds its lap's coaching back.
* **Driver preferences** - quiet mode ("stop talking for 3 laps") suppresses everything that has neither
  ``bypass_quiet`` nor urgency. The coaching *intensity* (quiet / normal / detailed) filters by message kind,
  sets the talk budget and caps coaching points per lap. The coaching cap is counted per lap *identity*:
  ``meta["lap_id"]`` when the builder sets it, else the lap number.
* **Seat change** - ``drop_driver_messages`` drops the queued lap summaries, goal lines and coaching points (they
  are about the previous driver's laps) and keeps alerts, strategy calls, race calls and INFO (about the car).
* **Workload / track position** - ``needs_speak_window`` messages wait for a calm part of the lap: off the
  brake, near-straight steering, and enough time before the next braking zone to finish the sentence with a
  margin to spare. That time covers audio reaching the driver (``speech_latency_s``: whole-message synthesis
  plus transport) as well as the sentence itself. Off track (menus, pits, paused) any moment is fine. Unknown
  inputs on track are *not* assumed calm.
* **Pacing** - proactive messages (validation prompts included) keep ``min_gap_s`` of silence after anything the
  radio said. The scheduler cannot hear playback, so "said" is bounded both by the caller's ``speaking`` flag and
  by the estimated end of the audio from dispatch (covers callers that poll only while idle).

Speech duration is estimated from *spoken* words. ``to_speech`` leaves most numbers as digits for the TTS engine,
and "0.08" is four spoken words, not one. At 2.6 words/s the estimate is 2-31% longer than ``say -v Daniel -r 200``
on real radio lines [measured]. It errs towards not talking into a braking zone.

Messages filtered by quiet mode, intensity or the talk budget stay queued (the setting may change, the next lap
brings a new allowance) until they expire or are superseded. The queue is bounded by ``max_pending``. Every public
method takes a lock, because messages are enqueued from the lap-analysis side while the radio hub polls
``next_message`` from its own loop. On a session change the caller calls ``reset_session``. The queue, the
coaching and talk budgets, the repeat filter and a lap-bounded quiet period all belong to the old session.

The caller must report ``speaking=True`` from the moment a returned message is handed to TTS until playback
ended or was cancelled.
"""

from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass
from typing import Literal

from pitwall.voice.speech import number_words
from pitwall.voice.types import DrivingState, MessageKind, Priority, RadioMessage

Intensity = Literal["quiet", "normal", "detailed"]
INTENSITIES: tuple[Intensity, ...] = ("quiet", "normal", "detailed")

WORDS_PER_S = 2.6  # spoken words (numbers expanded): on the slow side of the TTS voices we use [measured]
MIN_SPEECH_S = 1.0
# Dispatch -> first audio in the driver's ear: whole-message synthesis (``say`` ~0.4 s [measured]) plus Mac ->
# device transport and Bluetooth output (docs/research/voice-stack.md, latency budget).
SPEECH_LATENCY_S = 0.6
MAX_SPEECH_LATENCY_S = 5.0  # a stalled measurement must not close every speak window for good
LATENCY_SMOOTHING = 0.3  # weight of a new measurement in the latency moving average
SPEAK_WINDOW_MARGIN_S = 1.0  # finish talking at least this long before the next braking zone
CALM_BRAKE = 0.05  # brake below this = off the brakes (0..1)
CALM_STEERING = 0.12  # |steering| below this = near-straight (-1..1)
MIN_GAP_S = 2.0
REPEAT_WINDOW_S = 60.0
MAX_PENDING = 32
_COACHING_LAPS_KEPT = 8

TOPIC_KEY = "topic"  # meta key: a newer message on the same topic replaces a queued one
LAP_ID_KEY = "lap_id"  # meta key: unique lap identity (lap numbers restart every session)

DRIVER_INITIATED = frozenset({MessageKind.ANSWER, MessageKind.CONTROL})
SUPERSEDABLE = frozenset({MessageKind.LAP_SUMMARY, MessageKind.COACHING})
# about the seated driver's own laps: dropped when somebody else takes the seat (``drop_driver_messages``)
DRIVER_LAP_KINDS = frozenset({MessageKind.LAP_SUMMARY, MessageKind.GOAL, MessageKind.COACHING})

# CUE (predictive braking, phase 6) is its own opt-in feature, so coaching intensity does not filter it. A validation
# prompt is said at every intensity: the driver started the validation run, and the kit only queues during one.
_QUIET_KINDS = frozenset(
    {MessageKind.ANSWER, MessageKind.CONTROL, MessageKind.ALERT, MessageKind.CUE, MessageKind.VALIDATION}
)
_NORMAL_KINDS = _QUIET_KINDS | {MessageKind.LAP_SUMMARY, MessageKind.GOAL, MessageKind.COACHING, MessageKind.STRATEGY}
# --- race radio ---
_NORMAL_KINDS |= {MessageKind.RACE}
# --- end race radio ---
_DETAILED_KINDS = _NORMAL_KINDS | {MessageKind.INFO}
ALLOWED_KINDS: dict[Intensity, frozenset[MessageKind]] = {
    "quiet": _QUIET_KINDS,
    "normal": _NORMAL_KINDS,
    "detailed": _DETAILED_KINDS,
}
COACHING_PER_LAP: dict[Intensity, int | None] = {"quiet": 0, "normal": 1, "detailed": None}

# Dispatch order within a priority (then first in first out): in a race lap the lap time, then the strategy call,
# then the goal line, then the coaching point. Validation prompts go last, when nothing else is eligible.
KIND_RANK: dict[MessageKind, int] = {
    MessageKind.CUE: 0,
    MessageKind.ANSWER: 0,
    MessageKind.CONTROL: 0,
    MessageKind.ALERT: 1,
    MessageKind.LAP_SUMMARY: 2,
    MessageKind.STRATEGY: 3,
    MessageKind.GOAL: 4,
    MessageKind.COACHING: 5,
    MessageKind.INFO: 6,
    MessageKind.VALIDATION: 7,
    MessageKind.RACE: 2,  # race radio: ties with the lap summary (first in, first out)
}

# Unprompted messages said per driving lap while on track (the driver's workload at speed). Urgent calls, alerts,
# cues, answers, acknowledgements and validation prompts never count.
TALK_PER_LAP: dict[Intensity, int] = {"quiet": 0, "normal": 2, "detailed": 4}
BUDGETED = frozenset(
    {MessageKind.LAP_SUMMARY, MessageKind.GOAL, MessageKind.STRATEGY, MessageKind.COACHING, MessageKind.INFO}
)
_TALK_LAPS_KEPT = 8
# --- race radio --- race calls said per driving lap while on track: their own allowance, counted like the talk budget
RACE_PER_LAP: dict[Intensity, int] = {"quiet": 0, "normal": 2, "detailed": 3}  # [H]
RACE_ALLOWANCE_KEY = "race_allowance"  # meta False: a race call outside the allowance (the finish, after the flag)
# --- end race radio ---

LapKey = tuple[str, int | str | None]


def parse_intensity(value: str) -> Intensity:
    """Validate a coaching intensity from settings / the radio protocol (case-insensitive)."""
    v = value.strip().lower()
    for i in INTENSITIES:
        if v == i:
            return i
    raise ValueError(f"unknown coaching intensity {value!r}; expected one of {', '.join(INTENSITIES)}")


_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")  # letters only: "twenty-nine" is two words, "you're" one
_MAX_GROUPED_DIGITS = 9  # longer digit runs: count one word per digit (and never build a huge int)


def spoken_word_count(text: str) -> int:
    """Words a TTS engine says for speech text: "12" is one, "0.08" four ("zero point zero eight"), "k p h" three."""
    count = len(_WORD.findall(_NUMBER.sub(" ", text)))
    for m in _NUMBER.finditer(text):
        whole, _, frac = m.group().partition(".")
        count += len(whole) if len(whole) > _MAX_GROUPED_DIGITS else len(_WORD.findall(number_words(int(whole))))
        if frac:
            count += 1 + len(frac)  # "point" + one word per digit
    return count


def estimate_speech_s(text: str) -> float:
    """Spoken duration of already speech-normalised text, deliberately on the long side."""
    return max(MIN_SPEECH_S, spoken_word_count(text) / WORDS_PER_S)


def speak_window_ok(state: DrivingState, duration_s: float, lead_s: float = 0.0) -> bool:
    """True when the car is calm now and a ``duration_s`` sentence whose audio starts ``lead_s`` from now ends at
    least ``SPEAK_WINDOW_MARGIN_S`` before the next braking zone."""
    if not state.on_track:
        return True
    brake, steering = state.brake, state.steering
    if brake is None or steering is None:
        return False  # unknown is not calm
    # written so NaN inputs fail the test instead of passing it
    if not (brake < CALM_BRAKE and abs(steering) < CALM_STEERING):
        return False
    ttb = state.time_to_next_braking_s
    return ttb is None or ttb >= lead_s + duration_s + SPEAK_WINDOW_MARGIN_S


def _text_key(text: str) -> str:
    return " ".join(text.split()).casefold()


def _urgent(msg: RadioMessage) -> bool:
    return msg.priority >= Priority.URGENT


def _repeat_filtered(msg: RadioMessage) -> bool:
    """Subject to the identical-sentence repeat window (see module docstring for the exemptions)."""
    return msg.kind not in DRIVER_INITIATED and msg.kind is not MessageKind.CUE and not _urgent(msg)


def _budgeted(msg: RadioMessage) -> bool:
    """Counts toward the per-lap talk budget (urgent calls never do, whatever their kind)."""
    return msg.kind in BUDGETED and not _urgent(msg)


# --- race radio ---
def _race_counted(msg: RadioMessage) -> bool:
    """Counts toward the per-lap race allowance (urgent calls never do, nor a call marked outside it)."""
    return msg.kind is MessageKind.RACE and not _urgent(msg) and msg.meta.get(RACE_ALLOWANCE_KEY) is not False


# --- end race radio ---


def _interrupt_rank(msg: RadioMessage) -> int:
    """How strongly a message may cut into playback: 2 urgent, 1 cue, 0 never."""
    if _urgent(msg):
        return 2
    return 1 if msg.kind is MessageKind.CUE else 0


def _lap_identity(msg: RadioMessage) -> LapKey | None:
    lap_id = msg.meta.get(LAP_ID_KEY)
    if isinstance(lap_id, int | str) and not isinstance(lap_id, bool):
        return ("id", lap_id)
    return None if msg.lap_number is None else ("n", msg.lap_number)


def _topic(msg: RadioMessage) -> str | None:
    topic = msg.meta.get(TOPIC_KEY)
    return topic if isinstance(topic, str) and topic else None


@dataclass(slots=True, frozen=True)
class QuietMode:
    """Quiet until lap ``until_lap`` *starts* (``set_quiet(until_lap=lap + 3)`` = this lap and the next two)."""

    until_lap: int | None
    indefinite: bool

    def active(self, current_lap: int | None) -> bool:
        if self.indefinite or self.until_lap is None:
            return True
        if current_lap is None:
            return True  # cannot tell where we are: keep the promise to stay quiet
        return current_lap < self.until_lap


class RadioScheduler:
    __slots__ = (
        "_busy_until",
        "_coaching_spoken",
        "_intensity",
        "_latency_s",
        "_lock",
        "_on_air",
        "_pending",
        "_quiet",
        "_race_spent",
        "_recent_text",
        "_seq",
        "_talk_lap",
        "_talk_spent",
        "max_pending",
        "min_gap_s",
        "repeat_window_s",
    )

    def __init__(
        self,
        intensity: str = "normal",
        *,
        min_gap_s: float = MIN_GAP_S,
        repeat_window_s: float = REPEAT_WINDOW_S,
        max_pending: int = MAX_PENDING,
        speech_latency_s: float = SPEECH_LATENCY_S,
    ) -> None:
        if not (math.isfinite(speech_latency_s) and 0.0 <= speech_latency_s <= MAX_SPEECH_LATENCY_S):
            raise ValueError(f"speech_latency_s must be 0-{MAX_SPEECH_LATENCY_S} s, got {speech_latency_s}")
        self._intensity: Intensity = parse_intensity(intensity)
        self.min_gap_s = min_gap_s
        self.repeat_window_s = repeat_window_s
        self.max_pending = max_pending
        self._latency_s = speech_latency_s
        self._lock = threading.Lock()
        self._pending: list[tuple[int, RadioMessage]] = []  # (enqueue sequence, message)
        self._seq = 0
        self._quiet: QuietMode | None = None
        self._busy_until = -math.inf  # monotonic time the radio was last known (or estimated) to be talking
        self._on_air: RadioMessage | None = None  # last message handed out; presumed playing while speaking
        self._recent_text: dict[str, float] = {}  # normalised text -> monotonic time it was dispatched
        self._coaching_spoken: dict[LapKey, int] = {}  # lap identity -> coaching points dispatched for it
        self._talk_spent: dict[LapKey, int] = {}  # driving lap -> budgeted messages dispatched on track during it
        self._talk_lap: int | None = None  # the driving lap the talk budget is counting
        self._race_spent: dict[LapKey, int] = {}  # race radio: driving lap -> race calls dispatched on track during it

    # ------------------------------------------------------------------ preferences
    @property
    def intensity(self) -> Intensity:
        return self._intensity

    def set_intensity(self, intensity: str) -> Intensity:
        value = parse_intensity(intensity)
        with self._lock:
            self._intensity = value
        return value

    @property
    def quiet(self) -> QuietMode | None:
        return self._quiet

    def set_quiet(self, until_lap: int | None = None, indefinite: bool = False) -> None:
        if not indefinite and until_lap is None:
            raise ValueError("set_quiet needs until_lap or indefinite=True")
        with self._lock:
            self._quiet = QuietMode(until_lap=None if indefinite else until_lap, indefinite=indefinite)

    def resume(self) -> None:
        with self._lock:
            self._quiet = None

    def is_quiet(self, current_lap: int | None) -> bool:
        q = self._quiet
        return q is not None and q.active(current_lap)

    def quiet_state(self, current_lap: int | None = None) -> dict[str, object]:
        """The ``quiet`` object of the radio protocol's ``state`` frame (an elapsed quiet period reads as off)."""
        q = self._quiet
        if q is None or (current_lap is not None and not q.active(current_lap)):
            return {"until_lap": None, "indefinite": False}
        return {"until_lap": q.until_lap, "indefinite": q.indefinite}

    # ------------------------------------------------------------------ latency
    @property
    def speech_latency_s(self) -> float:
        """Allowance from dispatch to first audio in the driver's ear, used by the speak window and pacing."""
        return self._latency_s

    def observe_speech_latency(self, latency_s: float) -> float:
        """Fold a measured dispatch -> first-audio latency into the allowance; returns the value now in use.

        Non-finite or negative measurements are ignored, and outliers are capped at ``MAX_SPEECH_LATENCY_S``.
        """
        with self._lock:
            if math.isfinite(latency_s) and latency_s >= 0.0:
                sample = min(latency_s, MAX_SPEECH_LATENCY_S)
                self._latency_s += LATENCY_SMOOTHING * (sample - self._latency_s)
            return self._latency_s

    # ------------------------------------------------------------------ queue
    def enqueue(self, msg: RadioMessage) -> bool:
        """Queue a message. False when it is a duplicate or already stale (it will not be said)."""
        now = msg.created_mono
        with self._lock:
            if msg.expired(now) or any(m.id == msg.id for _, m in self._pending):
                return False
            topic = _topic(msg)
            if topic is not None:
                # before the repeat check on purpose: if the newest information was just said, the older
                # queued version must not be said after it
                self._pending = [e for e in self._pending if _topic(e[1]) != topic]
            if msg.kind not in DRIVER_INITIATED:
                key = _text_key(msg.text)
                if _repeat_filtered(msg):
                    self._prune_recent(now)
                    if key in self._recent_text:
                        return False
                if any(m.kind not in DRIVER_INITIATED and _text_key(m.text) == key for _, m in self._pending):
                    return False  # the same sentence is already queued
            lap = _lap_identity(msg)
            if msg.kind in SUPERSEDABLE and lap is not None:
                self._pending = [
                    e for e in self._pending if not (e[1].kind is msg.kind and _lap_identity(e[1]) not in (None, lap))
                ]
            self._seq += 1
            self._pending.append((self._seq, msg))
            if len(self._pending) > self.max_pending:
                # evict the least important, oldest first (possibly the new message itself)
                victim = min(self._pending, key=lambda e: (e[1].priority, e[0]))
                self._pending.remove(victim)
                return victim[1] is not msg
            return True

    def pending(self) -> list[RadioMessage]:
        """Queued messages in dispatch order (ignoring eligibility), for UI / debugging."""
        with self._lock:
            return [m for _, m in self._ordered()]

    def clear(self) -> int:
        """Drop every queued message. Returns how many were dropped. On session change use ``reset_session``."""
        with self._lock:
            n = len(self._pending)
            self._pending.clear()
            return n

    def reset_session(self) -> int:
        """Forget the previous session; returns how many queued messages were dropped.

        Queued messages, the per-lap coaching and talk budgets and the repeat filter belong to the old session, and
        so does a lap-bounded quiet period (lap numbers restart at 1). Indefinite quiet ("until you call me") is the
        driver's standing instruction and is kept, as are intensity, the latency allowance and pacing (the radio
        may still be talking).
        """
        with self._lock:
            n = len(self._pending)
            self._pending.clear()
            self._coaching_spoken.clear()
            self._talk_spent.clear()
            self._race_spent.clear()  # race radio
            self._talk_lap = None
            self._recent_text.clear()
            if self._quiet is not None and not self._quiet.indefinite:
                self._quiet = None
            return n

    def drop_driver_messages(self) -> int:
        """Somebody else took the seat: drop the queued lap summaries, goal lines and coaching points (they are about
        the previous driver's laps); keep alerts, strategy calls and INFO (they are about the car). Returns how many
        were dropped."""
        with self._lock:
            n = len(self._pending)
            self._pending = [e for e in self._pending if e[1].kind not in DRIVER_LAP_KINDS]
            return n - len(self._pending)

    # ------------------------------------------------------------------ dispatch
    def next_message(self, state: DrivingState, now_mono: float, speaking: bool) -> RadioMessage | None:
        """The message to say now (removed from the queue), else None.

        While ``speaking`` this is only ever an urgent message or a cue that outranks the one on air: the caller
        must cancel the current playback and say it.
        """
        with self._lock:
            self._prune(now_mono)
            if state.lap_number is not None and state.lap_number != self._talk_lap:
                # a new driving lap, or lap numbers restarting in the next session: a new allowance
                self._talk_lap = state.lap_number
                self._talk_spent.clear()
                self._race_spent.clear()  # race radio
            if self._quiet is not None and not self._quiet.active(state.lap_number):
                self._quiet = None
            quiet = self._quiet is not None
            ordered = self._ordered()
            if speaking:
                self._busy_until = max(self._busy_until, now_mono)
                floor = 0 if self._on_air is None else _interrupt_rank(self._on_air)
                candidates = [e for e in ordered if _interrupt_rank(e[1]) > floor]
                gap_ok = True  # only urgent messages and cues get here, and both are exempt from the gap
            else:
                self._on_air = None
                candidates = ordered
                gap_ok = now_mono >= self._busy_until + self.min_gap_s
            summary_laps = {
                lap
                for _, m in ordered
                if m.kind is MessageKind.LAP_SUMMARY
                and self._allowed(m, quiet)
                and (lap := _lap_identity(m)) is not None
            }
            for entry in candidates:
                msg = entry[1]
                if self._eligible(msg, state, quiet, gap_ok, summary_laps):
                    self._pending.remove(entry)
                    self._dispatched(msg, state, now_mono)
                    return msg
            return None

    # ------------------------------------------------------------------ internals (lock held)
    def _ordered(self) -> list[tuple[int, RadioMessage]]:
        return sorted(self._pending, key=lambda e: (-e[1].priority, KIND_RANK.get(e[1].kind, len(KIND_RANK)), e[0]))

    def _allowed(self, msg: RadioMessage, quiet: bool) -> bool:
        """Quiet mode and intensity: the filters that hold a message whatever the moment."""
        if quiet and not (msg.bypass_quiet or _urgent(msg)):
            return False
        return msg.kind in ALLOWED_KINDS[self._intensity]

    def _eligible(
        self, msg: RadioMessage, state: DrivingState, quiet: bool, gap_ok: bool, summary_laps: set[LapKey]
    ) -> bool:
        if not self._allowed(msg, quiet):
            return False
        if msg.kind is MessageKind.COACHING:
            if _lap_identity(msg) in summary_laps:
                return False  # the lap time goes first
            cap = COACHING_PER_LAP[self._intensity]
            if cap is not None and self._coaching_spoken.get(self._budget_key(msg, state), 0) >= cap:
                return False
        spent = self._talk_spent.get(self._talk_key(msg, state), 0)
        if state.on_track and _budgeted(msg) and spent >= TALK_PER_LAP[self._intensity]:
            return False  # this lap's allowance is used up: wait for the next lap (or expiry)
        # --- race radio ---
        race_spent = self._race_spent.get(self._talk_key(msg, state), 0)
        if state.on_track and _race_counted(msg) and race_spent >= RACE_PER_LAP[self._intensity]:
            return False  # this lap's race allowance is used up
        # --- end race radio ---
        urgent = _urgent(msg)
        gap_exempt = urgent or msg.kind in DRIVER_INITIATED or msg.kind is MessageKind.CUE
        if not gap_exempt and not gap_ok:
            return False
        if not msg.needs_speak_window or urgent:
            return True
        return speak_window_ok(state, estimate_speech_s(msg.speech), self._latency_s)

    def _dispatched(self, msg: RadioMessage, state: DrivingState, now: float) -> None:
        self._busy_until = max(self._busy_until, now + self._latency_s + estimate_speech_s(msg.speech))
        self._on_air = msg
        # answers are recorded too: a proactive message repeating what the driver just heard is noise
        self._recent_text[_text_key(msg.text)] = now
        if msg.kind is MessageKind.COACHING:
            key = self._budget_key(msg, state)
            self._coaching_spoken[key] = self._coaching_spoken.get(key, 0) + 1
            while len(self._coaching_spoken) > _COACHING_LAPS_KEPT:
                del self._coaching_spoken[next(iter(self._coaching_spoken))]
        if state.on_track and _budgeted(msg):
            key = self._talk_key(msg, state)
            self._talk_spent[key] = self._talk_spent.get(key, 0) + 1
            while len(self._talk_spent) > _TALK_LAPS_KEPT:
                del self._talk_spent[next(iter(self._talk_spent))]
        # --- race radio ---
        if state.on_track and _race_counted(msg):
            key = self._talk_key(msg, state)
            self._race_spent[key] = self._race_spent.get(key, 0) + 1
            while len(self._race_spent) > _TALK_LAPS_KEPT:
                del self._race_spent[next(iter(self._race_spent))]
        # --- end race radio ---

    @staticmethod
    def _budget_key(msg: RadioMessage, state: DrivingState) -> LapKey:
        return _lap_identity(msg) or ("n", state.lap_number)

    @staticmethod
    def _talk_key(msg: RadioMessage, state: DrivingState) -> LapKey:
        """The driving lap a budgeted message is said on: the car's lap now, else the message's own lap identity."""
        if state.lap_number is not None:
            return ("lap", state.lap_number)
        return _lap_identity(msg) or ("lap", None)

    def _prune(self, now: float) -> None:
        self._prune_recent(now)
        self._pending = [
            e
            for e in self._pending
            if not e[1].expired(now) and not (_repeat_filtered(e[1]) and _text_key(e[1].text) in self._recent_text)
        ]

    def _prune_recent(self, now: float) -> None:
        horizon = now - self.repeat_window_s
        stale = [k for k, t in self._recent_text.items() if t <= horizon]
        for k in stale:
            del self._recent_text[k]
