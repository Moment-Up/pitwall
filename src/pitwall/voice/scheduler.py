"""Radio scheduler: decides *which* queued message the engineer says next and *whether now is a good moment*.

The product brief ranks coaching by urgency, confidence, performance impact, driver preferences, workload,
track position and whether the advice is still actionable. Confidence and impact are decided upstream when a
message is built (``proactive.py`` only emits observations that clear a confidence bar, ordered by impact);
this module enforces the rest at dispatch time. It is the radio's ONE policy: every producer (lap summaries and
coaching, goal lines, strategy calls, race calls, car health calls, validation prompts) goes through its queue, and
the producers that cannot wait for a 100 ms tick (spotter calls, braking cues, answers) are decided by the hub with
this module's interrupt rule. The whole policy is one table, ``POLICY`` (one ``CallFamily`` row per call family;
docs/voice-protocol.md "Radio policy" prints it and ``GET /api/radio/policy`` serves it to Settings), pinned by
``tests/unit/test_radio_policy.py``:

* **Who may interrupt** (``may_interrupt``, the one rule; the hub and ``voice.spotter_radio`` use it too): only the
  urgent path (``Priority.URGENT``): spotter calls (a car arriving, three wide, hold your line, and the clears), the
  red flag and the race's safety-critical call (a puncture), both through ``voice.urgent``. An urgent call cuts
  anything but another urgent call (a red flag waits for a "Car left." on air and the other way round), and a spotter
  clear (``YIELDS_TO_CUE_KEY``) never cuts a braking cue. Nothing else ever cuts anything: a braking cue only plays on
  a free radio (it is dropped, never said late, when something is on air; proactive messages end before the next cue
  point, see the speak window), and lap summaries, race calls, strategy, car health, goals, coaching and validation
  prompts wait for a free radio. The driver's own answer replaces a proactive message on air (the driver asked; a
  push-to-talk press already cut it) but waits for a cue or an urgent call to end. A proactive message an urgent call
  cut is said again once, in full.
* **Race order** - the queue is ordered by ``Priority``, then by ``KIND_RANK``, then first in first out: alerts, then
  the lap time (carrying the line's race news, see merging), race calls, strategy and car health calls, the goal
  line, the coaching point, detail (INFO), validation prompts last. Practice and qualifying have no race or strategy
  calls: lap time, goal line, coaching. ``URGENT`` skips quiet mode, the speak window and the gap.
* **Intensity** (``ALLOWED_KINDS``) - quiet: answers, acknowledgements, urgent calls, alerts, spotter calls and
  validation prompts (the driver opted into a run); braking cues are muted (the hub). Normal adds the lap time, race
  calls, strategy and car health calls, goal lines and coaching; detailed adds detail (INFO). Quiet intensity is
  "alerts and answers only", as its acknowledgement promises.
* **One per-lap budget** (``TALK_PER_LAP``: quiet 0, normal 3, detailed 5) - while the car is on track, every routine
  message (``BUDGETED``: lap summary, race call, strategy and car health call, goal line, coaching point, detail) said
  during a driving lap (``DrivingState.lap_number``; the message's own lap identity when that is unknown) spends one
  from the same allowance, whoever made it. Alerts (flags, penalties, damage, the safety car, fuel critical) and the
  race milestones said whatever the allowance (``meta["race_allowance"]`` false: the grid brief and lights out, the
  countdown, the finish, a move into P1) are never held by it but spend it too, so a busy lap (a safety car, blue
  flags) leaves less room for routine talk. A message that does not fit stays queued until it expires or is
  superseded and is said from the next lap's allowance if it is still alive then. Off track (garage, menus, paused)
  and standing still (under ``BUDGET_MIN_KPH``: the grid, the pit box) there is no budget: it is the driver's workload
  at speed, and the grid brief, the flag-time goal line or the last lap's summary must not be starved. Never counted:
  urgent calls, spotter calls, cues, answers, acknowledgements, validation prompts. Family caps inside the one
  allowance: race calls ``RACE_PER_LAP`` (normal 2, detailed 3), coaching ``COACHING_PER_LAP`` per
  analysed lap (normal 1); on top, the producers' own limits (strategy and car health: one normal call a lap; goal
  lines: two a session; race radio: its cooldowns).
* **One message per piece of news** (de-duplication across producers):
  - *The line* (``SUMMARY_MERGE_KEY``): race news made at the line about the lap just finished (the lap-one position,
    a position change, the countdown, the race's fastest lap, the finish) waits up to
    ``SUMMARY_MERGE_HOLD_S`` for that lap's summary and goes out inside it ("That lap, 1:25.4, personal best. Fastest
    lap of the race."): one transmission, one budget slot, at most ``MERGE_MAX_WORDS`` spoken words (the rest go on
    their own; the chequered flag always rides in the final lap's summary).
  - *Announcements* (``ANNOUNCE_KEY``): the race radio's "Safety car, safety car. No overtaking." and race
    strategy's box-or-stay call ("Safety car. Pitting this lap is an option: ...") both announce the safety car; the
    strategy call carries it in its first words (``ANNOUNCE_HEAD_KEY``). Queued together they become one message
    ("Safety car, safety car. No overtaking. Pitting this lap is an option: ..."); said after the deployment call
    within ``ANNOUNCE_WINDOW_S``, the strategy call loses its head; a deployment call after the strategy call was said
    is dropped.
  - *Shared topics* (``SHARED_TOPICS``): a newer message on a topic replaces an unsaid one, across producers: fuel
    (race strategy in F1 races, car health's tank fuel elsewhere: one fuel call queued at a time), the gap (race
    radio's gap report, strategy's gap calls).
  - *Answers hold their topic* (``ANSWER_TOPICS``): for ``ANSWER_HOLD_S`` after the driver asked about the fuel, the
    gaps, the laps left or the weather, a proactive message on that topic below ``Priority.HIGH`` is not said.
  - *Identical sentences*: none repeated within ``repeat_window_s`` (exempt: answers, cues, spotter and urgent calls,
    and flags, penalties and damage, ``meta["repeat_ok"]``: their rules space them, a second blue flag is news).
  - *Laps*: a lap summary / coaching point supersedes unspoken ones of any *other* lap (laps are analysed in order:
    the newest arrival is the latest lap); a lap's coaching waits while that lap's summary is queued. After the
    race's chequered flag (the race radio's ``finish`` call) no coaching point is said: no next lap can use it.
* **Still actionable** - messages past ``expires_mono`` are dropped. ``drop_race_calls`` drops unsaid race calls a
  flashback made stale; ``drop_driver_messages`` drops the queued lap summaries, goal lines and coaching points when
  somebody else takes the seat (alerts, strategy, race calls and detail are about the car and stay).
* **Driver preferences** - quiet mode ("stop talking for 3 laps") suppresses everything that has neither
  ``bypass_quiet`` nor urgency (bypass: answers, acknowledgements, the safety-car box-or-stay call, fuel critical, a
  drive-through, stop-go, disqualification or black flag, severe damage, the safety car itself). The coaching
  *intensity* filters by kind, sets the budget and caps coaching points per lap (counted per lap *identity*:
  ``meta["lap_id"]`` when the builder sets it, else the lap number). The groups a driver switched off never reach the
  queue (``raceradio.radio``, ``carhealth.settings``, the spotter's settings).
* **Workload / track position** - ``needs_speak_window`` messages wait for a calm part of the lap: off the
  brake, near-straight steering, no car alongside (``traffic_alongside``), and enough time before the next braking
  zone or braking cue to finish the sentence with a margin to spare. That time covers audio reaching the driver
  (``speech_latency_s``: whole-message synthesis plus transport) as well as the sentence itself. Off track (menus,
  pits, paused) any moment is fine. Unknown inputs on track are *not* assumed calm.
* **Pacing** - proactive messages (validation prompts included) keep ``min_gap_s`` of silence after anything the
  radio said. The scheduler cannot hear playback, so "said" is bounded both by the caller's ``speaking`` flag and
  by the estimated end of the audio from dispatch (covers callers that poll only while idle).

Speech duration is estimated from *spoken* words. ``to_speech`` leaves most numbers as digits for the TTS engine,
and "0.08" is four spoken words, not one. At 2.6 words/s the estimate is 2-31% longer than ``say -v Daniel -r 200``
on real radio lines [measured]. It errs towards not talking into a braking zone.

Messages filtered by quiet mode, intensity or the budget stay queued (the setting may change, the next lap brings a
new allowance) until they expire or are superseded. The queue is bounded by ``max_pending``. Every public method
takes a lock, because messages are enqueued from the lap-analysis side while the radio hub polls ``next_message``
from its own loop. On a session change the caller calls ``reset_session``. The queue, the coaching and talk budgets,
the repeat filter, the announcement and answer memories and a lap-bounded quiet period all belong to the old session.

The caller must report ``speaking=True`` from the moment a returned message is handed to TTS until playback
ended or was cancelled.
"""

from __future__ import annotations

import dataclasses
import math
import re
import threading
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, Literal

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

# CUE (predictive braking, phase 6) is its own opt-in feature, so coaching intensity does not filter it (the hub
# mutes cues at quiet intensity). A validation prompt is said at every intensity: the driver started the validation
# run, and the kit only queues during one. Spotter calls have their own switch; quiet promises "urgent calls only".
_QUIET_KINDS = frozenset(
    {
        MessageKind.ANSWER,
        MessageKind.CONTROL,
        MessageKind.ALERT,
        MessageKind.CUE,
        MessageKind.VALIDATION,
        MessageKind.SPOTTER,
    }
)
_NORMAL_KINDS = _QUIET_KINDS | {
    MessageKind.LAP_SUMMARY,
    MessageKind.RACE,
    MessageKind.STRATEGY,
    MessageKind.GOAL,
    MessageKind.COACHING,
}
_DETAILED_KINDS = _NORMAL_KINDS | {MessageKind.INFO}
ALLOWED_KINDS: dict[Intensity, frozenset[MessageKind]] = {
    "quiet": _QUIET_KINDS,
    "normal": _NORMAL_KINDS,
    "detailed": _DETAILED_KINDS,
}
COACHING_PER_LAP: dict[Intensity, int | None] = {"quiet": 0, "normal": 1, "detailed": None}

# The race order within a priority (then first in first out): alerts, the lap time (with the line's race news), race
# calls, strategy and car health calls, the goal line, the coaching point, detail; validation prompts last, when
# nothing else is eligible. Spotter calls, cues and answers never wait in this queue (defensive ranks).
KIND_RANK: dict[MessageKind, int] = {
    MessageKind.SPOTTER: 0,
    MessageKind.CUE: 0,
    MessageKind.ANSWER: 0,
    MessageKind.CONTROL: 0,
    MessageKind.ALERT: 1,
    MessageKind.LAP_SUMMARY: 2,
    MessageKind.RACE: 3,
    MessageKind.STRATEGY: 4,
    MessageKind.GOAL: 5,
    MessageKind.COACHING: 6,
    MessageKind.INFO: 7,
    MessageKind.VALIDATION: 8,
}

# ONE per-lap allowance for every producer's routine messages while on track [H: tuned on the owner's races,
# docs/voice-protocol.md "Radio policy"]. Alerts and race milestones spend it without waiting for it.
TALK_PER_LAP: dict[Intensity, int] = {"quiet": 0, "normal": 3, "detailed": 5}
BUDGETED = frozenset(
    {
        MessageKind.LAP_SUMMARY,
        MessageKind.RACE,
        MessageKind.STRATEGY,
        MessageKind.GOAL,
        MessageKind.COACHING,
        MessageKind.INFO,
    }
)
_TALK_LAPS_KEPT = 8
BUDGET_MIN_KPH = 10.0  # the budget is the driver's workload at speed: standing on the grid or in the box is not
RACE_PER_LAP: dict[Intensity, int] = {"quiet": 0, "normal": 2, "detailed": 3}  # race calls' share of the allowance
RACE_ALLOWANCE_KEY = "race_allowance"  # meta False: a race milestone said whatever the allowance (it still spends it)
REPEAT_OK_KEY = "repeat_ok"  # meta True: exempt from the repeat window (the race radio rule has its own cooldown)
SUMMARY_MERGE_KEY = "merge_into_summary"  # meta True: race news made at the line, said inside that lap's summary
SUMMARY_MERGE_HOLD_S = 6.0  # [H] such a call waits this long for the lap summary (analysis lands within ~1-2 s)
MERGE_MAX_WORDS = 20  # [H] spoken words of a lap summary carrying the line's news (~7.7 s): the rest go on their own
RACE_CALL_KEY = "race_call"  # meta: the race radio call id (raceradio.radio)
ANNOUNCE_KEY = "announces"  # meta: the news this message announces ("sc": the safety car is out)
ANNOUNCE_HEAD_KEY = "announce_head"  # meta: the leading words of ``text`` that carry the announcement
ANNOUNCE_WINDOW_S = 60.0  # [H] an announcement said this recently is not said again
# Topics shared across producers: a newer message on the topic replaces an unsaid one whoever made it.
SHARED_TOPICS: dict[str, str] = {
    "strategy:fuel": "fuel",  # race strategy: F1 races
    "health:fuel_low": "fuel",  # car health: tank fuel (Forza; GT7 once enabled), never in an F1 race
    "health:fuel_critical": "fuel",
    "strategy:gap": "gap",  # race strategy's gap calls and the race radio's gap report (which uses this topic)
}
# What an answer was about: for ANSWER_HOLD_S a proactive message on that topic is not said (unless HIGH or more).
ANSWER_TOPICS: dict[str, frozenset[str]] = {
    "fuel": frozenset({"fuel"}),
    "gaps": frozenset({"gap"}),
    "laps_left": frozenset({"race:countdown"}),
    "weather": frozenset({"strategy:weather"}),
}
ANSWER_HOLD_S = 30.0  # [H]
FINISH_KEY, FINISH_CALL = "call", "finish"  # the race radio's chequered-flag call: no coaching point after it
INTENT_KEY = "intent"  # meta of an answer: the engineer intent it answered

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
    if state.traffic_alongside:  # never start a sentence while wheel to wheel (the spotter's)
        return False
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
    if msg.meta.get(REPEAT_OK_KEY) is True:  # race radio: a second blue flag or penalty is news
        return False
    return (
        msg.kind not in DRIVER_INITIATED
        and msg.kind is not MessageKind.CUE
        and msg.kind is not MessageKind.SPOTTER
        and not _urgent(msg)
    )


def _at_speed(state: DrivingState) -> bool:
    """The per-lap budget applies: on track and moving (speed unknown counts as moving: never assumed idle)."""
    return state.on_track and (state.speed_kph is None or not state.speed_kph < BUDGET_MIN_KPH)


def _milestone(msg: RadioMessage) -> bool:
    """A race milestone said whatever the allowance (the grid brief, lights out, the countdown, the finish, P1)."""
    return msg.meta.get(RACE_ALLOWANCE_KEY) is False


def _budget_holds(msg: RadioMessage) -> bool:
    """Waits for the lap's allowance: a routine message (urgent calls, milestones and the cold-tyre warning after a
    stop never wait; the cold tyres still spend the allowance, review #3)."""
    if msg.meta.get(TOPIC_KEY) == "health:tyres_cold":
        return False
    return msg.kind in BUDGETED and not _urgent(msg) and not _milestone(msg)


def _spends_budget(msg: RadioMessage) -> bool:
    """Spends the lap's allowance when said on track: every routine message, alert and milestone."""
    return not _urgent(msg) and (msg.kind in BUDGETED or msg.kind is MessageKind.ALERT)


def _race_counted(msg: RadioMessage) -> bool:
    """Counts toward race calls' share of the allowance (urgent calls never do, nor a milestone)."""
    return msg.kind is MessageKind.RACE and not _urgent(msg) and not _milestone(msg)


def _line_call(msg: RadioMessage) -> bool:
    """Race news made at the line that a lap summary may carry ("Two laps to go.", "P5 after lap one.")."""
    return msg.kind is MessageKind.RACE and msg.meta.get(SUMMARY_MERGE_KEY) is True and not _urgent(msg)


def _with_line_call(summary: RadioMessage, call: RadioMessage) -> RadioMessage:
    """The lap summary with the line call after it: one transmission, the summary's kind, budget and lap identity."""
    merged = summary.meta.get("merged_race_calls")
    ids = [*merged] if isinstance(merged, list) else []
    ids.append(call.meta.get(RACE_CALL_KEY))
    return dataclasses.replace(
        summary,
        text=f"{summary.text} {call.text}",
        speech=f"{summary.speech} {call.speech}",
        expires_mono=None  # no expiry on either side: neither drops it
        if summary.expires_mono is None or call.expires_mono is None
        else max(summary.expires_mono, call.expires_mono),
        meta={
            **summary.meta,
            "merged_race_call": ids[0],
            "merged_race_calls": ids,
            # carrying a milestone (the countdown, the finish, P1): never held by the budget either
            **({RACE_ALLOWANCE_KEY: False} if _milestone(call) else {}),
        },
    )


def _fits(merged: RadioMessage, call: RadioMessage) -> bool:
    """Within ``MERGE_MAX_WORDS``; the chequered flag always rides in the final lap's summary (the race is over: a
    longer message costs nothing, two messages about the flag do) [M: 5 of 6 F1 races said them apart]."""
    return call.meta.get(FINISH_KEY) == FINISH_CALL or spoken_word_count(merged.speech) <= MERGE_MAX_WORDS


def _alone(call: RadioMessage) -> RadioMessage:
    """A line call that did not fit in the summary: said on its own, without waiting for it."""
    return dataclasses.replace(call, meta={**call.meta, SUMMARY_MERGE_KEY: False})


def _announces(msg: RadioMessage) -> str | None:
    a = msg.meta.get(ANNOUNCE_KEY)
    return a if isinstance(a, str) and a else None


def _head(msg: RadioMessage) -> str | None:
    h = msg.meta.get(ANNOUNCE_HEAD_KEY)
    return h if isinstance(h, str) and h and msg.text.startswith(h) else None


def _cap_first(s: str) -> str:
    return s[:1].upper() + s[1:]


def _without_head(msg: RadioMessage, head: str) -> RadioMessage:
    """``msg`` without its announcing first words ("Safety car. Pitting this lap ..." -> "Pitting this lap ...")."""
    text = _cap_first(msg.text[len(head) :].lstrip())
    speech = msg.speech
    if speech.startswith(head):
        speech = _cap_first(speech[len(head) :].lstrip())
    meta = {k: v for k, v in msg.meta.items() if k not in (ANNOUNCE_HEAD_KEY, ANNOUNCE_KEY)}  # it announces no more
    return dataclasses.replace(msg, text=text, speech=speech, meta={**meta, "announce_dropped": head})


def _announced_with(bare: RadioMessage, carrier: RadioMessage) -> RadioMessage:
    """One message from a bare announcement and a message that opens with the same news: the bare words, then the
    carrier without its head ("Safety car, safety car. No overtaking. Pitting this lap is an option: ...")."""
    head = _head(carrier)
    rest = carrier if head is None else _without_head(carrier, head)
    return dataclasses.replace(
        rest,
        priority=max(bare.priority, rest.priority),
        text=f"{bare.text} {rest.text}",
        speech=f"{bare.speech} {rest.speech}",
        bypass_quiet=bare.bypass_quiet or rest.bypass_quiet,
        expires_mono=None
        if bare.expires_mono is None or rest.expires_mono is None
        else max(bare.expires_mono, rest.expires_mono),
        meta={**rest.meta, ANNOUNCE_KEY: _announces(bare), "announce_merged": bare.id},
    )


# --- the urgent path: ONE interrupt rule (module docstring, "Who may interrupt"). The scheduler's queue, the hub's
# urgent slot, cue gate and answers, and the spotter's delivery (voice.spotter_radio) all ask it ---
# meta True: never cuts a braking cue (a spotter clear or "still there": information, never a car arriving)
YIELDS_TO_CUE_KEY = "yields_to_cue"


def is_urgent(msg: RadioMessage) -> bool:
    """On the urgent path: ``Priority.URGENT`` (spotter calls but "still there", the red flag and a puncture via
    ``voice.urgent``)."""
    return _urgent(msg)


def interrupt_rank(msg: RadioMessage) -> int:
    """How protected ``msg`` is on air: 2 = urgent (nothing cuts it), 1 = a braking cue (only an urgent call cuts it;
    an answer waits for it), 0 = everything else (an urgent call cuts it; the driver's own answer replaces it)."""
    if _urgent(msg):
        return 2
    return 1 if msg.kind is MessageKind.CUE else 0


def may_interrupt(new: RadioMessage, on_air: RadioMessage | None) -> bool:
    """May ``new`` cut ``on_air`` (None: nothing on air)? An urgent call may, never another urgent call (two spotter
    calls, a red flag and a spotter call never cut each other); a message marked ``YIELDS_TO_CUE_KEY`` (a spotter
    clear) never cuts a braking cue. A braking cue may cut routine talk and a spotter clear (see below). An alert, a
    race call or anything else never interrupts."""
    if new.kind is MessageKind.CUE:
        # a braking cue is time-critical (its key word must land on the braking point): it may cut routine talk (a
        # lap summary, a coaching point, a race, health or strategy call, which is held and said again) and a spotter
        # clear, never an urgent call, an alert, another cue, an answer the driver asked for or a spotter car call
        if on_air is None:
            return True
        if on_air.kind is MessageKind.SPOTTER:  # a clear or "still there" yields to the braking point; a car call never
            return on_air.meta.get(YIELDS_TO_CUE_KEY) is True
        return not (
            _urgent(on_air)
            or on_air.kind in (MessageKind.CUE, MessageKind.ANSWER, MessageKind.CONTROL, MessageKind.ALERT)
        )
    if not _urgent(new):
        return False
    if on_air is None:
        return True
    if _urgent(on_air):
        return False
    return not (on_air.kind is MessageKind.CUE and new.meta.get(YIELDS_TO_CUE_KEY) is True)


# --- end urgent path ---


# ------------------------------------------------------------------ the policy table
@dataclass(slots=True, frozen=True)
class CallFamily:
    """One row of the radio policy: who says it, how it ranks and what holds it."""

    key: str
    label: str  # the family in the driver's words (Settings › Radio & voice)
    source: str  # the producer(s)
    kinds: tuple[MessageKind, ...]
    priority: str
    rank: int  # race order: lower goes first (0 = never queued, decided at once)
    interrupts: bool  # may cut what is on air (only the urgent path)
    intensities: tuple[Intensity, ...]  # said at these coaching intensities
    quiet_mode: str  # during a spoken "quiet for N laps": "said" | "held" | "some" (bypass_quiet calls only)
    speak_window: bool  # waits for a calm stretch
    budget: str  # "waits" (held by and spends the lap's allowance) | "spends" (never held, spends it) | "free"
    setting: str  # what switches it off
    note: str

    def to_dict(self) -> dict[str, Any]:
        out = dataclasses.asdict(self)
        out["kinds"] = [k.value for k in self.kinds]
        out["intensities"] = list(self.intensities)
        return out


_ALL: tuple[Intensity, ...] = INTENSITIES
_NORMAL_UP: tuple[Intensity, ...] = ("normal", "detailed")

POLICY: tuple[CallFamily, ...] = (
    CallFamily(
        "spotter",
        "Spotter",
        "pitwall.spotter + voice.spotter_radio",
        (MessageKind.SPOTTER,),
        "urgent (still there: high)",
        0,
        True,
        _ALL,
        "said",
        False,
        "free",
        "Spotter",
        'Cars alongside, F1 25. A clear never cuts a braking cue; "Still left." never cuts anything.',
    ),
    CallFamily(
        "urgent",
        "Red flag and punctures",
        "raceradio via voice.urgent",
        (MessageKind.ALERT,),
        "urgent",
        0,
        True,
        _ALL,
        "said",
        False,
        "free",
        "always on",
        "Safety-critical: said at once, past every filter.",
    ),
    CallFamily(
        "answer",
        "Answers",
        "voice.hub, voice.handsfree",
        (MessageKind.ANSWER, MessageKind.CONTROL),
        "high",
        0,
        False,
        _ALL,
        "said",
        False,
        "free",
        "always on",
        "The driver asked: replaces a proactive message on air, waits for a cue or an urgent call.",
    ),
    CallFamily(
        "cue",
        "Braking calls",
        "coach.cues",
        (MessageKind.CUE,),
        "high",
        0,
        True,
        _NORMAL_UP,
        "held",
        False,
        "free",
        "Braking calls",
        "Timed to the braking point: cuts routine talk (said again later), never an alert, an answer, an urgent call"
        " or a spotter car call; dropped (never late) when one is on air.",
    ),
    CallFamily(
        "alert",
        "Flags, penalties, damage, safety car, fuel critical",
        "raceradio, strategy.radio, carhealth.radio",
        (MessageKind.ALERT,),
        "high / normal",
        1,
        False,
        _ALL,
        "some",
        True,
        "spends",
        "Race calls (flags, penalties, damage); Car health (fuel)",
        "The safety car, fuel critical, serious penalties and severe damage are said in quiet mode too.",
    ),
    CallFamily(
        "lap_summary",
        "Lap time",
        "voice.proactive",
        (MessageKind.LAP_SUMMARY,),
        "normal",
        2,
        False,
        _NORMAL_UP,
        "held",
        True,
        "waits",
        "Coaching amount",
        "Carries the line's race news: the lap-one position, the countdown, the fastest lap, the gap, the finish.",
    ),
    CallFamily(
        "race",
        "Race calls",
        "raceradio",
        (MessageKind.RACE,),
        "normal / high",
        3,
        False,
        _NORMAL_UP,
        "held",
        True,
        "waits",
        "Race calls",
        "Position, start and countdown, gaps, warnings, minor damage; at most 2 a lap (3 detailed).",
    ),
    CallFamily(
        "strategy",
        "Strategy",
        "strategy.radio",
        (MessageKind.STRATEGY,),
        "from the call",
        4,
        False,
        _NORMAL_UP,
        "held",
        True,
        "waits",
        "Coaching amount",
        "F1 races: pit window, fuel, undercut, weather; one a lap.",
    ),
    CallFamily(
        "health",
        "Car health",
        "carhealth.radio",
        (MessageKind.STRATEGY,),
        "from the call",
        4,
        False,
        _NORMAL_UP,
        "held",
        True,
        "waits",
        "Car health",
        "Cold tyres, wear and tank fuel (fuel in F1 races is strategy's); one a lap.",
    ),
    CallFamily(
        "goal",
        "Goal reached",
        "motivation.radio",
        (MessageKind.GOAL,),
        "normal",
        5,
        False,
        _NORMAL_UP,
        "held",
        True,
        "waits",
        "Coaching amount",
        "At most two a session, never with a lap time.",
    ),
    CallFamily(
        "coaching",
        "Coaching point",
        "voice.proactive (coach.selection)",
        (MessageKind.COACHING,),
        "normal (praise: low)",
        6,
        False,
        _NORMAL_UP,
        "held",
        True,
        "waits",
        "Coaching amount",
        "One a lap at normal; the lap time goes first; none after the chequered flag; a drill point while drilling.",
    ),
    CallFamily(
        "detail",
        "Detail",
        "strategy.radio, raceradio, carhealth.radio",
        (MessageKind.INFO,),
        "low",
        7,
        False,
        ("detailed",),
        "held",
        True,
        "waits",
        "Coaching amount: Detailed",
        "Gap trends, a rival's fastest lap, lock-up and wheelspin notes.",
    ),
    CallFamily(
        "validation",
        "Validation prompts",
        "validate.kit",
        (MessageKind.VALIDATION,),
        "low",
        8,
        False,
        _ALL,
        "held",
        True,
        "free",
        "Setup › Validation run",
        "Only during a validation run, at least 30 s apart.",
    ),
)
POLICY_BY_KEY: dict[str, CallFamily] = {f.key: f for f in POLICY}


def family_of(msg: RadioMessage) -> str:
    """The policy row (``POLICY``) a message belongs to."""
    kind = msg.kind
    if kind is MessageKind.SPOTTER:
        return "spotter"
    if _urgent(msg):
        return "urgent"
    if kind in DRIVER_INITIATED:
        return "answer"
    if kind is MessageKind.CUE:
        return "cue"
    if kind is MessageKind.ALERT:
        return "alert"
    if kind is MessageKind.STRATEGY:
        return "health" if msg.meta.get("source") == "car_health" else "strategy"
    if kind is MessageKind.INFO:
        return "detail"
    return kind.value


def policy_table() -> list[dict[str, Any]]:
    """The policy rows with the live constants (``GET /api/radio/policy``; Settings prints it)."""
    return [f.to_dict() for f in POLICY]


def policy_constants() -> dict[str, Any]:
    return {
        "talk_per_lap": dict(TALK_PER_LAP),
        "race_per_lap": dict(RACE_PER_LAP),
        "coaching_per_lap": dict(COACHING_PER_LAP),
        "min_gap_s": MIN_GAP_S,
        "repeat_window_s": REPEAT_WINDOW_S,
        "merge_max_words": MERGE_MAX_WORDS,
    }


_BUDGET_WORDS = {"waits": "waits for it, spends it", "spends": "never held, spends it", "free": "outside it"}
_QUIET_WORDS = {"said": "said", "held": "held", "some": "safety calls said, the rest held"}


def policy_markdown() -> str:
    """``POLICY`` as the Markdown table docs/voice-protocol.md prints ("Radio policy"; the test keeps them equal)."""
    head = (
        "| Order | Family | Who says it | Kind | Priority | Interrupts | Intensity | Quiet mode | Speak window "
        "| Per-lap budget | Switched off by |"
    )
    rows = [head, "|" + "---|" * 11]
    for f in POLICY:
        rows.append(
            f"| {f.rank} | {f.label} | `{f.source}` | {', '.join(f'`{k.value}`' for k in f.kinds)} | {f.priority} "
            f"| {'yes' if f.interrupts else 'no'} | {', '.join(f.intensities)} | {_QUIET_WORDS[f.quiet_mode]} "
            f"| {'yes' if f.speak_window else 'no'} | {_BUDGET_WORDS[f.budget]} | {f.setting} |"
        )
    return "\n".join(rows)


def _lap_identity(msg: RadioMessage) -> LapKey | None:
    lap_id = msg.meta.get(LAP_ID_KEY)
    if isinstance(lap_id, int | str) and not isinstance(lap_id, bool):
        return ("id", lap_id)
    return None if msg.lap_number is None else ("n", msg.lap_number)


def _topic(msg: RadioMessage) -> str | None:
    """The message's topic, with a topic shared across producers in its common name (``SHARED_TOPICS``)."""
    topic = msg.meta.get(TOPIC_KEY)
    if not isinstance(topic, str) or not topic:
        return None
    return SHARED_TOPICS.get(topic, topic)


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
        "_announced",
        "_answered",
        "_busy_until",
        "_coaching_spoken",
        "_finished",
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
        self._talk_spent: dict[LapKey, int] = {}  # driving lap -> messages that spent the allowance on track
        self._talk_lap: int | None = None  # the driving lap the talk budget is counting
        self._race_spent: dict[LapKey, int] = {}  # driving lap -> race calls dispatched on track during it
        self._announced: dict[str, float] = {}  # announcement -> monotonic time it was said
        self._answered: dict[str, float] = {}  # topic -> monotonic time an answer about it was said
        self._finished = False  # the race's finish was queued: no coaching point any more (no next lap to use it)

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
        """Queue a message. False when it is a duplicate, already said by another producer, or already stale (it
        will not be said). A message may be queued changed: without the words another producer already said, or
        carrying the line's race news."""
        now = msg.created_mono
        with self._lock:
            if msg.expired(now) or any(m.id == msg.id for _, m in self._pending):
                return False
            got = self._announcement(msg, now)
            if got is None:
                return False
            msg = got
            if (
                msg.meta.get(FINISH_KEY) == FINISH_CALL
            ):  # the chequered flag: coaching is for a next lap, and none comes
                self._finished = True
                self._pending = [e for e in self._pending if e[1].kind is not MessageKind.COACHING]
            elif self._finished and msg.kind is MessageKind.COACHING:
                return False
            topic = _topic(msg)
            if topic is not None:
                if self._answered_recently(msg, topic, now):
                    return False  # the driver just asked about it: the answer said it
                # before the repeat check on purpose: if the newest information was just said, the older
                # queued version must not be said after it. Only a message this intensity says replaces one: a
                # detailed-only call never silences a normal one it cannot replace (review #2)
                if msg.kind in ALLOWED_KINDS[self._intensity]:
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
            # the line's race news and the lap summary go out as one message
            if msg.kind is MessageKind.LAP_SUMMARY:
                msg = self._carry_line_calls(msg)
            elif _line_call(msg):
                summaries = [  # this line's summary (a stale one of an earlier lap is superseded, with what it carries)
                    e
                    for e in self._pending
                    if e[1].kind is MessageKind.LAP_SUMMARY and now - e[1].created_mono <= SUMMARY_MERGE_HOLD_S
                ]
                summary = max(summaries, key=lambda e: e[0]) if summaries else None
                if summary is not None:
                    merged = _with_line_call(summary[1], msg)
                    if _fits(merged, msg):
                        i = self._pending.index(summary)
                        self._pending[i] = (summary[0], merged)
                        return True
                    msg = _alone(msg)  # no room in the summary: on its own, at once
            self._seq += 1
            self._pending.append((self._seq, msg))
            if len(self._pending) > self.max_pending:
                # evict the least important, oldest first (possibly the new message itself)
                victim = min(self._pending, key=lambda e: (e[1].priority, e[0]))
                self._pending.remove(victim)
                return victim[1] is not msg
            return True

    def _carry_line_calls(self, summary: RadioMessage) -> RadioMessage:
        """Fold the queued line calls into ``summary`` (lock held), in the order they came, while it stays within
        ``MERGE_MAX_WORDS``; a call that does not fit stays queued on its own."""
        line = [
            e
            for e in self._pending
            if _line_call(e[1]) and 0.0 <= summary.created_mono - e[1].created_mono <= SUMMARY_MERGE_HOLD_S
        ]
        for entry in sorted(line, key=lambda e: e[0]):
            merged = _with_line_call(summary, entry[1])
            i = self._pending.index(entry)
            if _fits(merged, entry[1]):
                summary = merged
                del self._pending[i]
            else:
                self._pending[i] = (entry[0], _alone(entry[1]))
        return summary

    def _announcement(self, msg: RadioMessage, now: float) -> RadioMessage | None:
        """One announcement per piece of news across producers (lock held). None: already said or queued."""
        ann = _announces(msg)
        if ann is None:
            return msg
        said = self._announced.get(ann)
        recently = said is not None and now - said <= ANNOUNCE_WINDOW_S
        head = _head(msg)
        # a queued message announcing the same news the other way (bare <-> carrying it in its first words)
        other = next(
            (e for e in self._pending if _announces(e[1]) == ann and (_head(e[1]) is None) != (head is None)), None
        )
        if other is not None:  # queued together: one message, the bare announcement's words first
            self._pending.remove(other)
            return _announced_with(msg, other[1]) if head is None else _announced_with(other[1], msg)
        if head is None:  # a bare announcement ("Safety car, safety car. No overtaking.")
            if recently or any(_announces(m) == ann for _, m in self._pending):
                return None
            return msg
        return _without_head(msg, head) if recently else msg

    def _answered_recently(self, msg: RadioMessage, topic: str, now: float) -> bool:
        if msg.kind in DRIVER_INITIATED or msg.priority >= Priority.HIGH:
            return False
        t = self._answered.get(topic)
        return t is not None and 0.0 <= now - t <= ANSWER_HOLD_S

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

        Queued messages, the per-lap coaching and talk budgets, the repeat filter and the announcement and answer
        memories belong to the old session, and so does a lap-bounded quiet period (lap numbers restart at 1).
        Indefinite quiet ("until you call me") is the driver's standing instruction and is kept, as are intensity,
        the latency allowance and pacing (the radio may still be talking).
        """
        with self._lock:
            n = len(self._pending)
            self._pending.clear()
            self._coaching_spoken.clear()
            self._talk_spent.clear()
            self._race_spent.clear()
            self._talk_lap = None
            self._recent_text.clear()
            self._announced.clear()
            self._answered.clear()
            self._finished = False
            if self._quiet is not None and not self._quiet.indefinite:
                self._quiet = None
            return n

    def drop_race_calls(self, groups: Collection[str]) -> int:
        """Drop the queued race calls of ``groups`` (a flashback undid what they say); returns how many."""
        with self._lock:
            n = len(self._pending)
            self._pending = [
                e for e in self._pending if not (e[1].meta.get(RACE_CALL_KEY) and e[1].meta.get("group") in groups)
            ]
            return n - len(self._pending)

    def drop_driver_messages(self) -> int:
        """Somebody else took the seat: drop the queued lap summaries, goal lines and coaching points (they are about
        the previous driver's laps); keep alerts, strategy calls, race calls and INFO (they are about the car).
        Returns how many were dropped."""
        with self._lock:
            n = len(self._pending)
            self._pending = [e for e in self._pending if e[1].kind not in DRIVER_LAP_KINDS]
            return n - len(self._pending)

    def note_spoken(self, msg: RadioMessage, now_mono: float) -> None:
        """A message said without this queue (an answer, a cue, a spotter call): what it said is remembered, so a
        proactive message does not repeat it (the repeat filter, an answer's topic, an announcement)."""
        with self._lock:
            self._remember(msg, now_mono)

    # ------------------------------------------------------------------ dispatch
    def next_message(self, state: DrivingState, now_mono: float, speaking: bool) -> RadioMessage | None:
        """The message to say now (removed from the queue), else None.

        While ``speaking`` this is only ever an urgent message that may cut the one on air (``may_interrupt``): the
        caller must cancel the current playback and say it.
        """
        with self._lock:
            self._prune(now_mono)
            if state.lap_number is not None and state.lap_number != self._talk_lap:
                # a new driving lap, or lap numbers restarting in the next session: a new allowance
                self._talk_lap = state.lap_number
                self._talk_spent.clear()
                self._race_spent.clear()
            if self._quiet is not None and not self._quiet.active(state.lap_number):
                self._quiet = None
            quiet = self._quiet is not None
            ordered = self._ordered()
            if speaking:
                self._busy_until = max(self._busy_until, now_mono)
                candidates = [e for e in ordered if may_interrupt(e[1], self._on_air)]  # the one urgent rule
                gap_ok = True  # only urgent messages get here, and they are exempt from the gap
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
                if _line_call(msg) and now_mono - msg.created_mono < SUMMARY_MERGE_HOLD_S:
                    continue  # waiting for the lap summary to carry it
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
        if _at_speed(state) and _budget_holds(msg):
            key = self._talk_key(msg, state)
            if self._talk_spent.get(key, 0) >= TALK_PER_LAP[self._intensity]:
                return False  # this lap's allowance is used up: wait for the next lap (or expiry)
            if _race_counted(msg) and self._race_spent.get(key, 0) >= RACE_PER_LAP[self._intensity]:
                return False  # race calls' share of this lap is used up
        urgent = _urgent(msg)
        gap_exempt = (
            urgent or msg.kind in DRIVER_INITIATED or msg.kind is MessageKind.CUE or msg.kind is MessageKind.SPOTTER
        )
        if not gap_exempt and not gap_ok:
            return False
        if not msg.needs_speak_window or urgent:
            return True
        return speak_window_ok(state, estimate_speech_s(msg.speech), self._latency_s)

    def _dispatched(self, msg: RadioMessage, state: DrivingState, now: float) -> None:
        self._busy_until = max(self._busy_until, now + self._latency_s + estimate_speech_s(msg.speech))
        self._on_air = msg
        self._remember(msg, now)
        if msg.kind is MessageKind.COACHING:
            key = self._budget_key(msg, state)
            self._coaching_spoken[key] = self._coaching_spoken.get(key, 0) + 1
            while len(self._coaching_spoken) > _COACHING_LAPS_KEPT:
                del self._coaching_spoken[next(iter(self._coaching_spoken))]
        if _at_speed(state) and _spends_budget(msg):
            key = self._talk_key(msg, state)
            self._talk_spent[key] = self._talk_spent.get(key, 0) + 1
            while len(self._talk_spent) > _TALK_LAPS_KEPT:
                del self._talk_spent[next(iter(self._talk_spent))]
            if _race_counted(msg):
                self._race_spent[key] = self._race_spent.get(key, 0) + 1
                while len(self._race_spent) > _TALK_LAPS_KEPT:
                    del self._race_spent[next(iter(self._race_spent))]

    def _remember(self, msg: RadioMessage, now: float) -> None:
        # answers are recorded too: a proactive message repeating what the driver just heard is noise
        self._recent_text[_text_key(msg.text)] = now
        ann = _announces(msg)
        if ann is not None:
            self._announced[ann] = now
        if msg.meta.get("call") == "green":  # the period is over: the next deployment is new news (review #5)
            self._announced.pop("sc", None)
        intent = msg.meta.get(INTENT_KEY)
        if msg.kind is MessageKind.ANSWER and isinstance(intent, str):
            for topic in ANSWER_TOPICS.get(intent, ()):
                self._answered[topic] = now

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
            if not e[1].expired(now)
            and not (_repeat_filtered(e[1]) and _text_key(e[1].text) in self._recent_text)
            and not ((t := _topic(e[1])) is not None and self._answered_recently(e[1], t, now))
        ]

    def _prune_recent(self, now: float) -> None:
        horizon = now - self.repeat_window_s
        stale = [k for k, t in self._recent_text.items() if t <= horizon]
        for k in stale:
            del self._recent_text[k]
