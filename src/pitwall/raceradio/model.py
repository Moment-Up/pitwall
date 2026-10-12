"""Race radio contracts: the call (``RaceCall``, the ``race_call`` live note), the urgent note and the ``RaceView``.

``RaceCall.to_dict()`` is the ``race_call`` live note (docs/voice-protocol.md, "Race radio"), meant for the radio hub.
Like every ``live.notify`` note it also reaches ``/ws/live`` subscribers as ``{"type": "race_call", ...}``; the
dashboard ignores it and reads the snapshot's ``race`` block (the last three calls) instead. ``text`` and
``text_simple`` never contain a personal name; ``data`` holds only numbers, codes and non-personal labels.

``tier`` is the evidence tier of the call's rule (docs/status.md): ``recorded`` (checked on the owner's real captures),
``synthetic`` (only on generated data, or the session itself is synthetic) or ``community`` (Forza: community docs,
no recording). ``synthetic`` says whether the session is a synthetic stream.

``RaceView`` (snapshot key ``race``, ``GET /api/race/live``; version 1, at most ~1.3 kB): every key always present,
unknown values ``null`` (never NaN), units in key names. ``ahead`` / ``behind`` carry the car's index (``car_index``:
an opt-in online name is only said for that same car, ``raceradio.names``); ``leader`` (F1 races, the player not P1)
the leader's non-personal label and the player's gap to it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

VIEW_VERSION = 1
GROUPS: tuple[str, ...] = ("flags", "start", "position", "rivals", "penalties", "damage")
PREF_GROUPS: tuple[str, ...] = (*GROUPS, "name")  # the per-driver toggles (drivers.RadioCallPrefs)
CALLS_SHOWN = 3
URGENT_SOURCE = "raceradio"

CallKind = Literal["alert", "race", "info"]
CallPriority = Literal["urgent", "high", "normal", "low"]

# Evidence tier of each call's rule (spec section 0.8; docs/status.md). Anything not listed is "synthetic".
# Only calls the owner's real captures produced (scripts/race_radio_check.py): never car_ahead_pitting, the lap
# invalidations (PENA 11/13/14/15), SC/VSC, the red flag, reminders, faults or minutes left.
RECORDED_CALLS = frozenset(
    {
        "yellow_ahead",
        "yellow_here",
        "blue_flag",
        "grid_brief",
        "lights_out",
        "laps_5",
        "laps_2",
        "last_lap",
        "finish",
        "lap1_summary",
        "position_change",
        "pit_exit_position",
        "clean_pass",
        "gap_report",
        "own_fastest_lap",
        "rival_fastest_lap",
        "retirement",
        "warning",
        "damage",
        "penalty_served",  # DTSV after the real drive-through (Sakhir sprint, 2026-10-11)
    }
)
# time penalties (4/3, 4/4, 4/7, 4/29 on real captures) and a drive-through (0/34, a jump start, Sakhir, then DTSV)
RECORDED_PENALTY_TYPES = frozenset({0, 4})


@dataclass(slots=True)
class CallSpec:
    """What a rule wants to say; the engine turns it into a ``RaceCall`` (id, lap, tier, time)."""

    group: str
    call: str
    kind: CallKind
    priority: CallPriority
    text: str
    text_simple: str | None
    ttl_s: float
    needs_window: bool = True
    bypass_quiet: bool = False
    topic: str | None = None
    addressable: bool = False
    defer_to_strategy_detail: bool = False
    audience: str | None = None  # "experienced": not given to a driver with simple wording (as strategy calls)
    allowance: bool = (
        True  # counts toward (and waits for) the per-lap race allowance; False: the finish, after the flag
    )
    data: dict[str, Any] = field(default_factory=dict)
    tier: str | None = None  # None: from the call (RECORDED_CALLS)

    @property
    def urgent(self) -> bool:
        return self.priority == "urgent"


@dataclass(slots=True, frozen=True, kw_only=True)
class RaceCall:
    id: str
    session_id: str
    group: str
    call: str
    kind: CallKind
    priority: CallPriority
    text: str
    text_simple: str | None
    speech_source: str | None
    ttl_s: float
    needs_window: bool
    bypass_quiet: bool
    topic: str | None
    lap: int | None
    addressable: bool
    defer_to_strategy_detail: bool
    audience: str | None
    allowance: bool
    data: Mapping[str, Any]
    tier: str
    synthetic: bool
    t_unix: float

    @property
    def urgent(self) -> bool:
        return self.priority == "urgent"

    def to_dict(self) -> dict[str, Any]:
        """The ``race_call`` live note (contract: module docstring)."""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "group": self.group,
            "call": self.call,
            "kind": self.kind,
            "priority": self.priority,
            "text": self.text,
            "text_simple": self.text_simple,
            "speech_source": self.speech_source,
            "ttl_s": round(self.ttl_s, 2),
            "needs_window": self.needs_window,
            "bypass_quiet": self.bypass_quiet,
            "topic": self.topic,
            "lap": self.lap,
            "addressable": self.addressable,
            "defer_to_strategy_detail": self.defer_to_strategy_detail,
            "audience": self.audience,
            "allowance": self.allowance,
            "data": clean(dict(self.data)),
            "tier": self.tier,
            "synthetic": self.synthetic,
            "t_unix": round(self.t_unix, 3),
        }

    def urgent_payload(self, t_mono: float | None = None) -> dict[str, Any]:
        """The ``radio_urgent`` note (``voice.urgent``): spoken at once, past every filter. ``t_mono`` is the
        ``time.monotonic()`` of the notify (the hub measures notify -> first audio from it)."""
        return {
            "id": self.id,
            "source": URGENT_SOURCE,
            "text": self.text,
            "text_simple": self.text_simple,
            "speech_source": self.speech_source,
            "ttl_s": self.ttl_s,
            "t_mono": t_mono,
            "meta": {
                "group": self.group,
                "call": self.call,
                "tier": self.tier,
                "synthetic": self.synthetic,
                "race_call": self.id,
            },
        }

    def entry(self) -> dict[str, Any]:
        """One of the view's ``calls``."""
        return {"t_unix": round(self.t_unix, 1), "group": self.group, "call": self.call, "text": self.text}


def clean(v: Any) -> Any:
    """NaN / infinity -> None, recursively (strict JSON)."""
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [clean(x) for x in v]
    return v


def off_view(
    reason: str | None, session_id: str | None = None, synthetic: bool = False, game: str | None = None
) -> dict[str, Any]:
    """The view when the race radio has nothing (no live session, time trial, another game)."""
    return {
        "version": VIEW_VERSION,
        "session_id": session_id,
        "game": game,
        "mode": "off",
        "reason": reason,
        "synthetic": synthetic,
        "position": None,
        "cars": None,
        "grid_position": None,
        "position_tier": None,
        "position_note": None,
        "lap": None,
        "total_laps": None,
        "laps_left": None,
        "final_lap": False,
        "time_left_s": None,
        "flags": {"track": None, "you": None, "yellow_ahead": None},
        "penalties": None,
        "damage": None,
        "ahead": None,
        "behind": None,
        "leader": None,
        "calls": [],
    }
