"""The radio line for a reached goal: wording, the scheduler rules it inherits (LAP_SUMMARY), the per-session cap,
the seat check, voice off, and the hub wiring (``motivation`` notes)."""

from __future__ import annotations

import asyncio
from typing import Any

from pitwall.drivers import coaching_limits
from pitwall.motivation.radio import GoalLineGate, goal_line, goal_message
from pitwall.voice.scheduler import RadioScheduler
from pitwall.voice.speech import to_speech
from pitwall.voice.types import DrivingState, MessageKind, Priority, RadioMessage
from tests.unit.test_voice_hub import make_hub, settle

OFF_TRACK = DrivingState(False, None, None, None, None, None, None)


def note(*goals: dict[str, Any], sid: str = "s1", lap_id: int | None = 187) -> dict[str, Any]:
    return {
        "kind": "goals_achieved",
        "session_id": sid,
        "driver_id": 1,
        "lap_id": lap_id,
        "lap_number": 7 if lap_id is not None else None,
        "t": 0.0,
        "goals": list(goals),
    }


LAP = {"id": 4, "kind": "lap_time", "target": 70_000, "params": {}, "track_name": "Austria"}
STREAK = {"id": 5, "kind": "clean_streak", "target": 8, "params": {}, "track_name": None}
STEADY = {"id": 6, "kind": "consistency", "target": 1100, "params": {"window_laps": 5}, "track_name": None}
RACE = {"id": 7, "kind": "race_clean", "target": 1, "params": {"rule": "no_penalties"}, "track_name": "Miami"}
CONTACT = {"id": 8, "kind": "race_clean", "target": 1, "params": {"rule": "no_contact"}, "track_name": "Miami"}


def test_lines() -> None:
    assert goal_line([LAP], False) == "Goal reached: a lap under 1:10 at Austria."
    assert goal_line([LAP], True) == "You did it: a lap under 1:10 at Austria."
    assert goal_line([{**LAP, "target": 70_300}], False) == "Goal reached: a lap under 1:10.3 at Austria."
    long = {**LAP, "track_name": "Unidentified GT7 circuit (3.80 km)"}
    assert goal_line([long], False) == "Goal reached: a lap under 1:10."
    assert goal_line([STREAK], False) == "Goal reached: 8 clean laps in a row."
    assert goal_line([STREAK], True) == "You did it: 8 clean laps in a row."
    assert goal_line([STEADY], False) == "Goal reached: 5 laps within 1.1 seconds of each other."
    assert goal_line([STEADY], True) == "You did it: 5 steady laps, all within 1.1 seconds."
    assert goal_line([RACE], False) == "Goal reached: a race to the flag with no penalties."
    assert goal_line([RACE], True) == "You did it: a whole race with no penalties."
    assert goal_line([CONTACT], False) == "Goal reached: a race to the flag without touching another car."
    assert goal_line([CONTACT], True) == "You did it: a whole race without touching another car."
    assert (
        goal_line([LAP, STREAK], False) == "Two goals reached: a lap under 1:10 at Austria and 8 clean laps in a row."
    )
    assert to_speech(goal_line([LAP], False) or "") == "Goal reached: a lap under one ten at Austria."
    for g in (LAP, STREAK, STEADY, RACE, CONTACT):
        for simple in (False, True):
            assert "brak" not in (goal_line([g], simple) or "").lower()


def test_message_shape_and_ttl() -> None:
    gate = GoalLineGate()
    m = goal_message(note(LAP), gate, "s1", simple=False, to_speech=to_speech, now_mono=100.0)
    assert m is not None
    assert (m.kind, m.priority, m.needs_speak_window, m.bypass_quiet) == (
        MessageKind.LAP_SUMMARY,
        Priority.NORMAL,
        True,
        False,
    )
    assert m.id == "goal-s1-4" and m.meta["topic"] == "goal:s1" and m.meta["lap_id"] == 187
    assert m.meta["goal_ids"] == [4] and m.expires_mono == 145.0 and m.lap_number == 7
    race = goal_message(note(RACE, lap_id=None), gate, "s1", simple=False, to_speech=to_speech, now_mono=100.0)
    assert race is not None and race.expires_mono == 220.0  # said after the flag, off track


def test_gate_caps_lines_and_checks_the_seat() -> None:
    gate = GoalLineGate()
    args: dict[str, Any] = {"simple": False, "to_speech": to_speech}
    assert goal_message(note(LAP, sid="old"), gate, "s1", **args) is None  # the seat changed since
    assert goal_message(note(LAP), gate, "s1", **args) is not None
    assert goal_message(note(STREAK), gate, "s1", **args) is not None
    assert goal_message(note(STEADY), gate, "s1", **args) is None  # at most 2 per session
    assert goal_message(note(STEADY, sid="s2"), gate, "s2", **args) is not None
    assert goal_message(note(LAP), GoalLineGate(), "s1", voice_enabled=False, **args) is None
    assert goal_message({"kind": "other"}, GoalLineGate(), "s1", **args) is None


def summary(lap_id: int, now: float) -> RadioMessage:
    return RadioMessage(
        f"lap{lap_id}-summary", MessageKind.LAP_SUMMARY, Priority.NORMAL, "Lap 7, 1:09.981.", "Lap 7", now,
        expires_mono=now + 45, lap_number=7, meta={"lap_id": lap_id},
    )  # fmt: skip


def coaching(lap_id: int, now: float) -> RadioMessage:
    return RadioMessage(
        f"lap{lap_id}-c", MessageKind.COACHING, Priority.NORMAL, "Turn 6, losing 0.23 s.", "Turn 6", now,
        expires_mono=now + 45, lap_number=7, meta={"lap_id": lap_id},
    )  # fmt: skip


def test_scheduler_says_it_after_the_summary_and_before_the_coaching() -> None:
    sched = RadioScheduler("normal", min_gap_s=0.0)
    now = 10.0
    goal_msg = goal_message(note(LAP), GoalLineGate(), "s1", simple=False, to_speech=to_speech, now_mono=now)
    assert goal_msg is not None
    sched.enqueue(summary(187, now))
    sched.enqueue(goal_msg)
    sched.enqueue(coaching(187, now))
    said = []
    for i in range(3):
        m = sched.next_message(OFF_TRACK, now + 1 + i * 10, False)
        assert m is not None
        said.append(m.id)
    assert said == ["lap187-summary", "goal-s1-4", "lap187-c"]


def test_quiet_intensity_holds_it_and_a_later_lap_supersedes_it() -> None:
    sched = RadioScheduler("quiet", min_gap_s=0.0)
    m = goal_message(note(LAP), GoalLineGate(), "s1", simple=False, to_speech=to_speech, now_mono=10.0)
    assert m is not None and sched.enqueue(m)
    assert sched.next_message(OFF_TRACK, 11.0, False) is None
    sched.set_intensity("normal")
    sched.enqueue(summary(188, 12.0))  # the next lap's summary: the unsaid goal line is stale now
    assert [x.id for x in sched.pending()] == ["lap188-summary"]
    loud = RadioScheduler("normal", min_gap_s=0.0)
    loud.set_quiet(indefinite=True)
    loud.enqueue(m)
    assert loud.next_message(OFF_TRACK, 11.0, False) is None  # a spoken "quiet" holds it too


async def test_hub_queues_one_line_per_note() -> None:
    hub, _client, _sent, _stt, sched = await make_hub()
    queued: list[RadioMessage] = []
    enqueue = sched.enqueue

    def record(m: RadioMessage) -> None:
        queued.append(m)
        enqueue(m)

    sched.enqueue = record  # type: ignore[method-assign]
    hub.live.reset_session("s1", "udp:20777", False)
    hub.live.notify("motivation", note(LAP, STREAK))
    await settle(5)
    (m,) = queued
    assert m.text == "Two goals reached: a lap under 1:10 at Austria and 8 clean laps in a row."
    hub.coaching_limits = coaching_limits("beginner")
    hub.live.notify("motivation", note(STEADY))
    await settle(5)
    assert queued[-1].text == "You did it: 5 steady laps, all within 1.1 seconds."
    hub.live.notify("motivation", note(RACE))  # the third line this session: capped
    await settle(5)
    assert len(queued) == 2
    hub.live.reset_session("s2", "udp:20777", False)
    hub.voice_enabled = False
    hub.live.notify("motivation", note(LAP, sid="s2"))  # voice off: not queued
    await settle(5)
    assert len(queued) == 2
    await hub.stop()
    await asyncio.sleep(0)
