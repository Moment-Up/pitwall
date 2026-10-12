"""Race calls as radio messages (raceradio.radio.race_message): kind / priority / window / TTL / topic, the driver's
groups and wording."""

from __future__ import annotations

from typing import Any

import pytest

from pitwall.drivers import RadioCallPrefs
from pitwall.raceradio.radio import race_message
from pitwall.voice.scheduler import TOPIC_KEY
from pitwall.voice.types import MessageKind, Priority


def call(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "rc-7-3",
        "session_id": "s1",
        "group": "position",
        "call": "position_change",
        "kind": "race",
        "priority": "normal",
        "text": "Up to P5.",
        "text_simple": "You're up to 5th.",
        "speech_source": "Up to P 5.",
        "ttl_s": 15.0,
        "needs_window": True,
        "bypass_quiet": False,
        "topic": "race:position",
        "lap": 3,
        "addressable": True,
        "defer_to_strategy_detail": False,
        "audience": None,
        "data": {},
        "tier": "recorded",
        "synthetic": False,
        "t_unix": 0.0,
    }
    return {**base, **kw}


@pytest.mark.parametrize(
    ("kind", "priority", "want_kind", "want_priority"),
    [
        ("race", "normal", MessageKind.RACE, Priority.NORMAL),
        ("race", "high", MessageKind.RACE, Priority.HIGH),
        ("alert", "high", MessageKind.ALERT, Priority.HIGH),
        ("info", "low", MessageKind.INFO, Priority.LOW),
    ],
)
def test_kind_and_priority(kind: str, priority: str, want_kind: MessageKind, want_priority: Priority) -> None:
    m = race_message(call(kind=kind, priority=priority), 100.0)
    assert m is not None and (m.kind, m.priority) == (want_kind, want_priority)


def test_mapping_and_meta() -> None:
    m = race_message(call(), 100.0)
    assert m is not None
    assert (m.id, m.text, m.speech, m.lap_number) == ("race-rc-7-3", "Up to P5.", "Up to P 5.", 3)
    assert (m.created_mono, m.expires_mono, m.needs_speak_window, m.bypass_quiet) == (100.0, 115.0, True, False)
    assert m.meta == {
        TOPIC_KEY: "race:position",
        "group": "position",
        "call": "position_change",
        "urgent": False,
        "tier": "recorded",
        "synthetic": False,
        "addressable": True,
        "race_call": "rc-7-3",
    }
    grid = race_message(call(call="grid_brief", group="start", needs_window=False, topic=None, ttl_s=1.9), 0.0)
    assert grid is not None and not grid.needs_speak_window and TOPIC_KEY not in grid.meta and grid.expires_mono == 1.9
    severe = race_message(call(kind="alert", priority="high", bypass_quiet=True, group="damage"), 0.0)
    assert severe is not None and severe.bypass_quiet


def test_simple_wording() -> None:
    m = race_message(call(), 0.0, simple=True)
    assert m is not None and (m.text, m.speech) == ("You're up to 5th.", "You're up to 5th.")
    no_plain = race_message(call(text_simple=None), 0.0, simple=True)
    assert no_plain is not None and no_plain.text == "Up to P5."


def test_group_toggles_and_the_red_flag_is_immune() -> None:
    prefs = RadioCallPrefs(position=False, flags=False)
    assert race_message(call(), 0.0, prefs=prefs) is None
    assert race_message(call(group="flags", call="blue_flag"), 0.0, prefs=prefs) is None
    assert race_message(call(group="flags", call="red_flag"), 0.0, prefs=prefs) is not None
    assert race_message(call(group="rivals"), 0.0, prefs=prefs) is not None


def test_detailed_defers_to_strategy_and_experienced_only_calls() -> None:
    pit = call(group="rivals", call="car_ahead_pitting", defer_to_strategy_detail=True)
    assert race_message(pit, 0.0, intensity="detailed") is None
    assert race_message(pit, 0.0, intensity="normal") is not None
    assert race_message(pit, 0.0, intensity="detailed", simple=True) is not None  # strategy's detail is not theirs
    info = call(kind="info", priority="low", audience="experienced", text_simple=None)
    assert race_message(info, 0.0, simple=True) is None and race_message(info, 0.0) is not None
