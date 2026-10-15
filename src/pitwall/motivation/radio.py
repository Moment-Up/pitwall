"""The radio line for a reached goal: one short, deterministic sentence (no LLM, never about braking).

``goal_message`` turns a ``motivation`` note (``motivation.worker``) into a ``RadioMessage`` of kind ``GOAL``
(normal priority, speak window, never bypassing quiet), so the radio's one policy (``voice.scheduler``) applies:
normal and detailed intensity say it, quiet intensity and a spoken "quiet for N laps" hold it until it expires,
voice off drops it. It follows the lap's summary and a strategy call and comes before the coaching point (the
scheduler's ``KIND_RANK``), and it waits for and spends the radio's one per-lap budget on track. It carries no lap
identity (``meta["lap_id"]``), so it never holds the lap's coaching back and a later lap's summary does not supersede
it; ``meta["topic"] = "goal:<session>"`` makes a newer goal line replace an unsaid one. A seat change drops it unsaid.

Lap goals expire after ``LAP_MESSAGE_TTL_S`` like the lap's other messages; race goals (judged at the flag, off
track) after two minutes. ``GoalLineGate`` (owned by the hub, event loop only) allows at most
``MAX_GOAL_LINES_PER_SESSION`` per session and skips a note of a session that is no longer live (the seat changed).
Several goals on one lap become one line.

The line never states the achieving lap time: the radio rounds lap times to tenths ("1:09.981" is spoken "one ten
point zero"), which would contradict "under 1:10". Targets are said as ``1:10`` (whole seconds) or ``1:10.3``.

A new family record (``record_message``, from the ``family_record`` note of ``motivation.worker``: a lap took its
family board's record from another driver, ``leaderboard.service.record_note``) goes the same way: kind ``GOAL``, the
same speak windows, budget and per-session cap (one ``GoalLineGate``), its own topic ``record:<session>`` so it never
replaces an unsaid goal line, and no lap time: "New family record at Austria: you took it from Sam."
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from pitwall.leaderboard.service import FAMILY_RECORD_NOTE
from pitwall.motivation.model import LONG_TRACK_NAME, lap_time_radio, seconds
from pitwall.voice.proactive import LAP_MESSAGE_TTL_S
from pitwall.voice.scheduler import TOPIC_KEY
from pitwall.voice.types import MessageKind, Priority, RadioMessage

MAX_GOAL_LINES_PER_SESSION = 2
MAX_NAMED = 2  # goals named in one line; more are counted ("and 1 more")
RACE_GOAL_TTL_S = 120.0
_SESSIONS_KEPT = 32
_COUNT_WORDS = {2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six"}


class GoalLineGate:
    """At most ``max_lines`` goal lines per session, and only for the session that is live now."""

    def __init__(self, max_lines: int = MAX_GOAL_LINES_PER_SESSION) -> None:
        self.max_lines = max_lines
        self._said: OrderedDict[str, int] = OrderedDict()

    def allow(self, session_id: object, live_session_id: str | None) -> bool:
        if not isinstance(session_id, str) or session_id != live_session_id:
            return False
        n = self._said.get(session_id, 0)
        if n >= self.max_lines:
            return False
        self._said[session_id] = n + 1
        self._said.move_to_end(session_id)
        while len(self._said) > _SESSIONS_KEPT:
            self._said.popitem(last=False)
        return True


def _num(v: object) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def goal_phrase(goal: Mapping[str, Any], simple: bool) -> str | None:
    """``a lap under 1:10 at Austria``, ``8 clean laps in a row``... (None for an unknown goal)."""
    kind = goal.get("kind")
    target = _num(goal.get("target"))
    params = goal.get("params") if isinstance(goal.get("params"), Mapping) else {}
    assert isinstance(params, Mapping)
    if kind == "lap_time" and target is not None:
        track = goal.get("track_name")
        at = f" at {track}" if isinstance(track, str) and track and len(track) <= LONG_TRACK_NAME else ""
        return f"a lap under {lap_time_radio(target)}{at}"
    if kind == "clean_streak" and target is not None:
        return f"{round(target)} clean laps in a row"
    if kind == "consistency" and target is not None:
        k = params.get("window_laps", 5)
        s = seconds(target)
        return f"{k} steady laps, all within {s} seconds" if simple else f"{k} laps within {s} seconds of each other"
    if kind == "race_clean":
        if params.get("rule") == "no_contact":
            return (
                "a whole race without touching another car"
                if simple
                else "a race to the flag without touching another car"
            )
        return "a whole race with no penalties" if simple else "a race to the flag with no penalties"
    return None


def goal_line(goals: Sequence[Mapping[str, Any]], simple: bool) -> str | None:
    """One short line: ``Goal reached: ...``; several goals name two at most (``... and 1 more``). A beginner always
    hears ``You did it``."""
    phrases = [p for g in goals if (p := goal_phrase(g, simple))]
    if not phrases:
        return None
    if len(phrases) == 1:
        return f"{'You did it' if simple else 'Goal reached'}: {phrases[0]}."
    shown, rest = phrases[:MAX_NAMED], len(phrases) - MAX_NAMED
    joined = f"{', '.join(shown)} and {rest} more" if rest > 0 else " and ".join(shown)
    count = _COUNT_WORDS.get(len(phrases), str(len(phrases)))
    if simple:
        return f"You did it: {count.lower()} goals, {joined}."
    return f"{count} goals reached: {joined}."


def goal_message(
    note: Mapping[str, Any],
    gate: GoalLineGate,
    live_session_id: str | None,
    *,
    simple: bool,
    to_speech: Callable[[str], str],
    voice_enabled: bool = True,
    now_mono: float | None = None,
) -> RadioMessage | None:
    """The radio message for a ``motivation`` note, or None (voice off, not the live session, cap reached)."""
    if not voice_enabled or note.get("kind") != "goals_achieved":
        return None
    goals = [g for g in note.get("goals") or () if isinstance(g, Mapping)]
    text = goal_line(goals, simple)
    if text is None:
        return None
    sid = note.get("session_id")
    if not gate.allow(sid, live_session_id):
        return None
    now = time.monotonic() if now_mono is None else now_mono
    lap_id = note.get("lap_id")
    race = lap_id is None or any(g.get("kind") == "race_clean" for g in goals)
    ids = [str(g.get("id")) for g in goals]
    lap_number = note.get("lap_number")
    return RadioMessage(
        id=f"goal-{sid}-{'-'.join(ids)}",
        kind=MessageKind.GOAL,
        priority=Priority.NORMAL,
        text=text,
        speech=to_speech(text),
        created_mono=now,
        expires_mono=now + (RACE_GOAL_TTL_S if race else LAP_MESSAGE_TTL_S),
        lap_number=lap_number if isinstance(lap_number, int) and not isinstance(lap_number, bool) else None,
        bypass_quiet=False,
        needs_speak_window=True,
        meta={TOPIC_KEY: f"goal:{sid}", "goal_ids": [g.get("id") for g in goals]},
    )


# ---------------------------------------------------------------------------------------------- family record
def record_line(note: Mapping[str, Any], simple: bool) -> str | None:
    """``New family record at Austria: you took it from Sam.`` (a beginner: ``You did it: the family record at Austria
    is yours, faster than Sam.``); None without the previous holder."""
    prev = note.get("previous_driver_name")
    if not isinstance(prev, str) or not prev:
        return None
    track = note.get("track_name")
    at = f" at {track}" if isinstance(track, str) and track and len(track) <= LONG_TRACK_NAME else ""
    if simple:
        return f"You did it: the family record{at} is yours, faster than {prev}."
    return f"New family record{at}: you took it from {prev}."


def record_message(
    note: Mapping[str, Any],
    gate: GoalLineGate,
    live_session_id: str | None,
    *,
    simple: bool,
    to_speech: Callable[[str], str],
    voice_enabled: bool = True,
    now_mono: float | None = None,
) -> RadioMessage | None:
    """The radio message for a ``family_record`` note, or None (voice off, not the live session, cap reached)."""
    if not voice_enabled or note.get("kind") != FAMILY_RECORD_NOTE:
        return None
    text = record_line(note, simple)
    if text is None:
        return None
    sid = note.get("session_id")
    if not gate.allow(sid, live_session_id):
        return None
    now = time.monotonic() if now_mono is None else now_mono
    lap_number = note.get("lap_number")
    return RadioMessage(
        id=f"record-{sid}-{note.get('lap_id')}",
        kind=MessageKind.GOAL,
        priority=Priority.NORMAL,
        text=text,
        speech=to_speech(text),
        created_mono=now,
        expires_mono=now + LAP_MESSAGE_TTL_S,
        lap_number=lap_number if isinstance(lap_number, int) and not isinstance(lap_number, bool) else None,
        bypass_quiet=False,
        needs_speak_window=True,
        meta={TOPIC_KEY: f"record:{sid}", "record_lap_id": note.get("lap_id")},
    )
