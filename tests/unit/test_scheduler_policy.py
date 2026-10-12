"""The radio's one arbitration policy (v0.2.0 plan section 3): message kinds and intensity, the dispatch order of a race
lap, the per-lap talk budget (on track only), the seat-change drop, validation prompts and the never-squeezed safety
calls. Every test runs on an injected clock: the scheduler is given ``now`` and never reads ``time.monotonic``."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from pitwall.strategy.radio import strategy_message
from pitwall.voice.proactive import lap_messages
from pitwall.voice.scheduler import (
    ALLOWED_KINDS,
    BUDGETED,
    KIND_RANK,
    MIN_GAP_S,
    TALK_PER_LAP,
    RadioScheduler,
    estimate_speech_s,
)
from pitwall.voice.types import DrivingState, MessageKind, Priority, RadioMessage

ON_TRACK = DrivingState(
    on_track=True,
    speed_kph=250.0,
    brake=0.0,
    steering=0.01,
    lap_number=8,
    lap_distance_m=800.0,
    time_to_next_braking_s=None,
)
OFF_TRACK = DrivingState(False, 0.0, 0.0, 0.0, 8, 0.0, None)
STEP = 12.0  # between polls: longer than any test sentence plus the gap, shorter than a lap message's life


def msg(
    msg_id: str,
    kind: MessageKind,
    priority: Priority = Priority.NORMAL,
    *,
    created: float = 0.0,
    ttl: float | None = None,
    lap: int | None = None,
    meta: dict[str, object] | None = None,
    bypass: bool = False,
    window: bool = True,
) -> RadioMessage:
    text = f"Message {msg_id}."
    return RadioMessage(
        id=msg_id,
        kind=kind,
        priority=priority,
        text=text,
        speech=text,
        created_mono=created,
        expires_mono=None if ttl is None else created + ttl,
        lap_number=lap,
        bypass_quiet=bypass,
        needs_speak_window=window,
        meta=meta or {},
    )


def goal(sid: str = "s1", created: float = 0.0) -> RadioMessage:
    """A goal line as ``motivation.radio.goal_message`` builds it in v0.2.0: GOAL, topic ``goal:<sid>``, no lap id."""
    return msg(f"goal-{sid}-4", MessageKind.GOAL, created=created, ttl=45.0, lap=7, meta={"topic": f"goal:{sid}"})


def call(level: str, topic: str, priority: str = "normal", **kw: Any) -> dict[str, Any]:
    """A ``StrategyCall.to_dict()`` (the ``strategy_call`` live note)."""
    return {
        "id": f"st-{topic}-{level}",
        "topic": topic,
        "level": level,
        "priority": priority,
        "text": kw.pop("text", f"A {level} call about {topic}."),
        "lap": 8,
        "ttl_s": 60.0,
        "bypass_quiet": kw.pop("bypass", False),
        "audience": "all",
        "data": {},
        "t_unix": 0.0,
    }


LAP = {
    "lap_id": 107,
    "lap_number": 7,
    "lap_time_ms": 65_706,
    "sector_times_ms": [20_000, 25_000, 20_706],
    "clean": True,
    "valid": True,
    "flags": [],
}
OBS = [
    {
        "id": 1,
        "lap_id": 107,
        "lap_number": 7,
        "corner": "T4",
        "kind": "low_min_speed",
        "value": -8.0,
        "impact_s": 0.08,
        "confidence": 0.9,
        "priority": 0.07,
        "positive": False,
        "text": "T4: minimum speed 8 km/h lower than your reference.",
    }
]


def race_lap(sched: RadioScheduler, now: float = 0.0) -> list[RadioMessage]:
    """Everything a race lap queues: its summary and coaching point, a goal line and a strategy call (in the order
    they arrive in the hub: the coaching point last but one)."""
    lap_msgs = lap_messages(LAP, OBS, None, None, sched.intensity, now)
    assert [m.kind for m in lap_msgs] == [MessageKind.LAP_SUMMARY, MessageKind.COACHING]
    out = [*lap_msgs, goal(created=now), strategy_message(call("normal", "gap"), now)]
    for m in out:
        assert sched.enqueue(m), m.id
    return out


def drain(sched: RadioScheduler, state: DrivingState, start: float = 1.0, polls: int = 40) -> list[RadioMessage]:
    out: list[RadioMessage] = []
    t = start
    for _ in range(polls):
        m = sched.next_message(state, t, speaking=False)
        if m is not None:
            out.append(m)
        t += STEP
    return out


# ================================================================ kinds and intensity
def test_kinds_per_intensity() -> None:
    quiet = {MessageKind.ANSWER, MessageKind.CONTROL, MessageKind.ALERT, MessageKind.CUE, MessageKind.VALIDATION}
    normal = quiet | {MessageKind.LAP_SUMMARY, MessageKind.GOAL, MessageKind.COACHING, MessageKind.STRATEGY}
    assert ALLOWED_KINDS["quiet"] == quiet
    assert ALLOWED_KINDS["normal"] == normal
    assert ALLOWED_KINDS["detailed"] == normal | {MessageKind.INFO}
    assert set(KIND_RANK) == set(MessageKind)  # every kind has its place in the order
    budgeted = {MessageKind.LAP_SUMMARY, MessageKind.GOAL, MessageKind.STRATEGY, MessageKind.COACHING}
    assert budgeted | {MessageKind.INFO} == BUDGETED
    assert TALK_PER_LAP == {"quiet": 0, "normal": 2, "detailed": 4}


def test_race_lap_order_off_track_is_summary_strategy_goal_coaching() -> None:
    """Off track there is no budget: the whole lap is said, in the race order (decision 3)."""
    sched = RadioScheduler("normal")
    race_lap(sched)
    said = drain(sched, OFF_TRACK)
    assert [m.kind for m in said] == [
        MessageKind.LAP_SUMMARY,
        MessageKind.STRATEGY,
        MessageKind.GOAL,
        MessageKind.COACHING,
    ]


def test_practice_lap_order_is_summary_goal_coaching() -> None:
    sched = RadioScheduler("normal")
    for m in [*lap_messages(LAP, OBS, None, None, "normal", 0.0), goal()]:
        sched.enqueue(m)
    assert [m.kind for m in drain(sched, OFF_TRACK)] == [
        MessageKind.LAP_SUMMARY,
        MessageKind.GOAL,
        MessageKind.COACHING,
    ]


def test_the_goal_line_no_longer_holds_its_laps_coaching_back() -> None:
    """The goal line used to be a LAP_SUMMARY with the lap's identity, so the lap's coaching waited behind it. A long
    goal line that does not fit before the next braking zone now lets the short coaching point go first."""
    sched = RadioScheduler("normal")
    long_goal = replace(goal(), text="Goal reached: " + "a lap under one ten at Austria and " * 6 + "more.")
    long_goal.speech = long_goal.text
    coaching = lap_messages(LAP, OBS, None, None, "normal", 0.0)[1]
    sched.enqueue(long_goal)
    sched.enqueue(coaching)
    room = sched.speech_latency_s + estimate_speech_s(coaching.speech) + 1.5  # the short point fits, the goal not
    assert estimate_speech_s(long_goal.speech) > room
    first = sched.next_message(replace(ON_TRACK, time_to_next_braking_s=room), 1.0, speaking=False)
    assert first is not None and first.kind is MessageKind.COACHING
    second = sched.next_message(ON_TRACK, 1.0 + STEP, speaking=False)
    assert second is not None and second.kind is MessageKind.GOAL


# ================================================================ the per-lap talk budget
@pytest.mark.parametrize(("intensity", "said"), [("normal", 2), ("detailed", 4)])
def test_budget_per_intensity_on_track(intensity: str, said: int) -> None:
    sched = RadioScheduler(intensity)
    for i in range(6):
        sched.enqueue(msg(f"s{i}", MessageKind.STRATEGY, meta={"topic": f"strategy:t{i}"}))
    assert len(drain(sched, ON_TRACK)) == said
    assert len(sched.pending()) == 6 - said  # kept for the next lap (until they expire)
    assert len(drain(sched, replace(ON_TRACK, lap_number=9), start=2000.0)) == min(said, 6 - said)


def test_no_budget_off_track() -> None:
    """In the garage the flag-time goal line and the last lap's summary must not be starved."""
    sched = RadioScheduler("normal")
    for i in range(5):
        sched.enqueue(msg(f"s{i}", MessageKind.STRATEGY, meta={"topic": f"strategy:t{i}"}))
    assert len(drain(sched, OFF_TRACK)) == 5


def test_off_track_messages_do_not_spend_the_laps_allowance() -> None:
    sched = RadioScheduler("normal")
    sched.enqueue(msg("garage", MessageKind.STRATEGY))
    assert [m.id for m in drain(sched, OFF_TRACK)] == ["garage"]
    for i in range(3):
        sched.enqueue(msg(f"s{i}", MessageKind.STRATEGY, created=2000.0, meta={"topic": f"strategy:t{i}"}))
    assert len(drain(sched, ON_TRACK, start=2000.0)) == 2


def test_race_lap_on_track_gives_up_its_coaching_point() -> None:
    """At normal intensity a lap with a summary and a strategy call has no room left for the goal or the coaching."""
    sched = RadioScheduler("normal")
    race_lap(sched)
    said = drain(sched, ON_TRACK, polls=3)
    assert [m.kind for m in said] == [MessageKind.LAP_SUMMARY, MessageKind.STRATEGY]
    assert {m.kind for m in sched.pending()} == {MessageKind.GOAL, MessageKind.COACHING}


def test_detailed_race_lap_fits_in_four() -> None:
    sched = RadioScheduler("detailed")
    race_lap(sched)
    assert len(drain(sched, ON_TRACK)) == 4


def test_a_leftover_is_said_from_the_next_laps_allowance() -> None:
    sched = RadioScheduler("normal")
    race_lap(sched)
    assert len(drain(sched, ON_TRACK, polls=3)) == 2
    next_lap = replace(ON_TRACK, lap_number=9)
    m = sched.next_message(next_lap, 40.0, speaking=False)  # the goal line is still alive (45 s)
    assert m is not None and m.kind is MessageKind.GOAL
    assert sched.next_message(next_lap, 300.0, speaking=False) is None  # the coaching point expired meanwhile
    assert sched.pending() == []


@pytest.mark.parametrize(
    "kind_priority",
    [
        (MessageKind.ALERT, Priority.NORMAL),
        (MessageKind.ALERT, Priority.HIGH),
        (MessageKind.LAP_SUMMARY, Priority.URGENT),
        (MessageKind.VALIDATION, Priority.LOW),
        (MessageKind.ANSWER, Priority.HIGH),
        (MessageKind.CONTROL, Priority.HIGH),
    ],
)
def test_outside_the_budget(kind_priority: tuple[MessageKind, Priority]) -> None:
    kind, priority = kind_priority
    sched = RadioScheduler("normal")
    for i in range(2):
        sched.enqueue(msg(f"s{i}", MessageKind.STRATEGY, meta={"topic": f"strategy:t{i}"}))
    assert len(drain(sched, ON_TRACK, polls=3)) == 2  # the lap's allowance is used up
    sched.enqueue(msg("x", kind, priority, created=2000.0))
    sched.enqueue(msg("over", MessageKind.STRATEGY, created=2000.0))
    assert [m.id for m in drain(sched, ON_TRACK, start=2000.0)] == ["x"]


def test_a_new_session_or_a_lap_restart_is_a_new_allowance() -> None:
    """Lap numbers restart at 1 in the next session; ``reset_session`` (and any change of lap) is a new allowance."""
    sched = RadioScheduler("normal")
    for i in range(2):
        sched.enqueue(msg(f"a{i}", MessageKind.STRATEGY, meta={"topic": f"strategy:a{i}"}))
    assert len(drain(sched, replace(ON_TRACK, lap_number=3))) == 2
    sched.reset_session()
    for i in range(2):
        sched.enqueue(msg(f"b{i}", MessageKind.STRATEGY, created=2000.0, meta={"topic": f"strategy:b{i}"}))
    assert len(drain(sched, replace(ON_TRACK, lap_number=3), start=2000.0)) == 2
    for i in range(2):  # no reset at all: lap numbers going back (a new session, a flashback) are a new lap
        sched.enqueue(msg(f"c{i}", MessageKind.STRATEGY, created=4000.0, meta={"topic": f"strategy:c{i}"}))
    assert len(drain(sched, replace(ON_TRACK, lap_number=1), start=4000.0)) == 2


def test_unknown_lap_number_falls_back_to_the_messages_lap() -> None:
    sched = RadioScheduler("normal")
    nowhere = replace(ON_TRACK, lap_number=None)
    for i in range(3):
        sched.enqueue(msg(f"a{i}", MessageKind.STRATEGY, lap=4, meta={"topic": f"strategy:a{i}"}))
    sched.enqueue(msg("b", MessageKind.STRATEGY, lap=5))
    assert sorted(m.id for m in drain(sched, nowhere)) == ["a0", "a1", "b"]


def test_the_coaching_cap_still_applies_on_top() -> None:
    sched = RadioScheduler("normal")
    for i in range(2):
        sched.enqueue(msg(f"c{i}", MessageKind.COACHING, lap=7, meta={"lap_id": 107}))
    assert [m.id for m in drain(sched, OFF_TRACK)] == ["c0"]  # one coaching point per analysed lap


# ================================================================ seat change
def test_seat_change_drops_the_previous_drivers_lap_messages() -> None:
    sched = RadioScheduler("detailed")
    race_lap(sched)
    sched.enqueue(strategy_message(call("detailed", "gap_trend"), 0.0))
    sched.enqueue(strategy_message(call("alert", "fuel", "high", bypass=True), 0.0))
    assert sched.drop_driver_messages() == 3  # summary, coaching point, goal line
    assert {m.kind for m in sched.pending()} == {MessageKind.STRATEGY, MessageKind.INFO, MessageKind.ALERT}
    assert sched.drop_driver_messages() == 0


# ================================================================ validation prompts
def validation(created: float = 0.0) -> RadioMessage:
    """A prompt as ``validate.kit`` queues it in v0.2.0: VALIDATION, LOW priority, speak window, topic ``validation``."""
    return msg("v1", MessageKind.VALIDATION, Priority.LOW, created=created, ttl=90.0, meta={"topic": "validation"})


def test_validation_prompts_are_said_at_quiet_intensity() -> None:
    sched = RadioScheduler("quiet")
    sched.enqueue(validation())
    m = sched.next_message(ON_TRACK, 1.0, speaking=False)
    assert m is not None and m.kind is MessageKind.VALIDATION


def test_validation_goes_last_and_never_within_the_gap_of_another_message() -> None:
    sched = RadioScheduler("normal")
    sched.enqueue(validation())
    sched.enqueue(msg("sum", MessageKind.LAP_SUMMARY, lap=7))
    first = sched.next_message(OFF_TRACK, 1.0, speaking=False)
    assert first is not None and first.id == "sum"
    end = 1.0 + sched.speech_latency_s + estimate_speech_s(first.speech)
    assert sched.next_message(OFF_TRACK, end + MIN_GAP_S - 0.05, speaking=False) is None
    second = sched.next_message(OFF_TRACK, end + MIN_GAP_S, speaking=False)
    assert second is not None and second.kind is MessageKind.VALIDATION


def test_validation_waits_for_a_speak_window() -> None:
    sched = RadioScheduler("normal")
    sched.enqueue(validation())
    assert sched.next_message(replace(ON_TRACK, brake=0.8), 1.0, speaking=False) is None
    assert sched.next_message(ON_TRACK, 2.0, speaking=False) is not None


# ================================================================ never squeezed
def test_safety_car_box_call_bypasses_quiet_mode_and_the_budget() -> None:
    sched = RadioScheduler("normal")
    sched.set_quiet(indefinite=True)  # "quiet until I call you"
    for i in range(2):
        sched.enqueue(msg(f"s{i}", MessageKind.STRATEGY, meta={"topic": f"strategy:t{i}"}))
    sc = strategy_message(call("alert", "sc_box", "high", text="Safety car. Box this lap.", bypass=True), 0.0)
    assert sc.kind is MessageKind.ALERT and sc.bypass_quiet
    sched.enqueue(sc)
    said = drain(sched, ON_TRACK)
    assert [m.id for m in said] == [sc.id]  # the strategy calls are held by quiet mode
    sched.resume()
    sched.enqueue(msg("s9", MessageKind.STRATEGY, created=2000.0))
    sched.enqueue(
        strategy_message(call("alert", "fuel", "high", text="Fuel critical: save fuel now.", bypass=True), 2000.0)
    )
    said = drain(sched, ON_TRACK, start=2000.0)
    assert said[0].kind is MessageKind.ALERT and said[0].text.startswith("Fuel critical")
    assert len([m for m in said if m.kind is MessageKind.STRATEGY]) == 2  # the alert spent none of the allowance


def test_safety_car_stay_out_call_is_never_squeezed_out_by_the_budget() -> None:
    """Plan 3.1 / 0.3: "no stop needed" under the safety car is an alert like the box call. A lap whose allowance the
    summary and coaching point already spent still says it, and it bypasses quiet mode."""
    from pitwall.strategy.calls import CallContext, CallPlanner

    planner = CallPlanner(clock=lambda: 1.0)
    box = {"pit_loss_s": 10.2, "green_pit_loss_s": 19.4, "stop_needed": False, "this_lap": True, "tier": "heuristic"}
    ctx = CallContext(
        t=100.0, lap=10, total_laps=50, laps_remaining=40.0, player_in_pit=False, blocked=None,
        sc_status="full", sc_period=1, sc_box=box,
    )  # fmt: skip
    (stay,) = planner.plan(ctx)
    sched = RadioScheduler("normal")
    sched.enqueue(msg("sum", MessageKind.LAP_SUMMARY, lap=10))
    sched.enqueue(msg("pt", MessageKind.COACHING, lap=10))
    said = drain(sched, ON_TRACK)
    assert [m.id for m in said] == ["sum", "pt"]  # this lap's allowance is spent
    sched.set_quiet(indefinite=True)
    sc = strategy_message(stay.to_dict(), 20.0)
    assert sc.kind is MessageKind.ALERT and sc.priority is Priority.HIGH and sc.bypass_quiet
    sched.enqueue(sc)
    assert [m.id for m in drain(sched, ON_TRACK, start=20.0)] == [sc.id]
