"""The radio policy's race radio additions (voice.scheduler): kind RACE, its share of the one per-lap allowance."""

from __future__ import annotations

from pitwall.voice.scheduler import ALLOWED_KINDS, KIND_RANK, RACE_PER_LAP, TALK_PER_LAP, RadioScheduler
from pitwall.voice.types import DrivingState, MessageKind, Priority, RadioMessage

ON_TRACK = DrivingState(True, 200.0, 0.0, 0.0, 5, 100.0, None)


def msg(i: str, kind: MessageKind, prio: Priority = Priority.NORMAL, lap: int | None = None) -> RadioMessage:
    return RadioMessage(i, kind, prio, f"Message {i}.", f"Message {i}.", 0.0, lap_number=lap)


def drain(s: RadioScheduler, state: DrivingState = ON_TRACK, t0: float = 0.0) -> list[str]:
    out = []
    t = t0
    for _ in range(40):
        m = s.next_message(state, t, False)
        if m is not None:
            out.append(m.id)
        t += 10.0
    return out


def test_race_calls_at_normal_and_detailed_not_quiet() -> None:
    assert MessageKind.RACE in ALLOWED_KINDS["normal"] and MessageKind.RACE in ALLOWED_KINDS["detailed"]
    assert MessageKind.RACE not in ALLOWED_KINDS["quiet"]
    s = RadioScheduler("quiet")
    s.enqueue(msg("r1", MessageKind.RACE))
    assert drain(s) == []


def test_race_calls_have_a_share_of_the_one_allowance() -> None:
    """v0.3.0: one per-lap allowance for every producer (TALK_PER_LAP); race calls may use at most RACE_PER_LAP of it."""
    assert RACE_PER_LAP == {"quiet": 0, "normal": 2, "detailed": 3}
    assert TALK_PER_LAP == {"quiet": 0, "normal": 3, "detailed": 5}
    s = RadioScheduler("normal")
    for i in range(4):
        s.enqueue(msg(f"r{i}", MessageKind.RACE))
    for i in range(3):
        s.enqueue(msg(f"c{i}", MessageKind.STRATEGY))
    assert drain(s) == ["r0", "r1", "c0"]  # 2 race calls and 1 strategy call on lap 5: 3 in all
    next_lap = DrivingState(True, 200.0, 0.0, 0.0, 6, 100.0, None)
    assert drain(s, next_lap, t0=500.0) == ["r2", "r3", "c1"]  # a new lap, a new allowance
    detailed = RadioScheduler("detailed")
    for i in range(5):
        detailed.enqueue(msg(f"r{i}", MessageKind.RACE))
    assert len(drain(detailed)) == 3


def test_a_race_milestone_is_never_held_but_spends_the_allowance() -> None:
    s = RadioScheduler("normal")
    for i in range(3):
        s.enqueue(msg(f"c{i}", MessageKind.STRATEGY))
    assert drain(s) == ["c0", "c1", "c2"]
    lead = RadioMessage("p1", MessageKind.RACE, Priority.NORMAL, "Up to P1.", "Up to P 1.", 500.0)
    lead.meta["race_allowance"] = False  # a move into the lead: always heard
    s.enqueue(lead)
    assert drain(s, t0=500.0) == ["p1"]
    s2 = RadioScheduler("normal")
    s2.enqueue(
        RadioMessage("p1", MessageKind.RACE, Priority.HIGH, "Up to P1.", "x", 0.0, meta={"race_allowance": False})
    )
    for i in range(3):
        s2.enqueue(msg(f"c{i}", MessageKind.STRATEGY))
    assert drain(s2) == ["p1", "c0", "c1"]  # it spent one of the lap's three


def test_off_track_no_allowance_and_urgent_never_counts() -> None:
    off = DrivingState(False, None, None, None, 5, None, None)
    s = RadioScheduler("normal")
    for i in range(5):
        s.enqueue(msg(f"r{i}", MessageKind.RACE))
    assert len(drain(s, off)) == 5


def test_race_order_lap_time_then_race_call_then_strategy() -> None:
    assert KIND_RANK[MessageKind.LAP_SUMMARY] < KIND_RANK[MessageKind.RACE] < KIND_RANK[MessageKind.STRATEGY]
    s = RadioScheduler("detailed")
    s.enqueue(msg("race", MessageKind.RACE))
    s.enqueue(msg("summary", MessageKind.LAP_SUMMARY, lap=4))
    s.enqueue(msg("strategy", MessageKind.STRATEGY))
    assert [m.id for m in s.pending()] == ["summary", "race", "strategy"]


def test_race_calls_survive_a_seat_change_and_reset_session_clears_the_allowance() -> None:
    s = RadioScheduler("normal")
    s.enqueue(msg("race", MessageKind.RACE))
    s.enqueue(msg("summary", MessageKind.LAP_SUMMARY, lap=4))
    assert s.drop_driver_messages() == 1 and [m.id for m in s.pending()] == ["race"]
    for i in range(2):
        s.enqueue(msg(f"r{i}", MessageKind.RACE))
    drain(s)
    s.enqueue(msg("r9", MessageKind.RACE))
    assert drain(s, t0=1000.0) == []  # lap 5's race allowance is used up
    s.reset_session()
    s.enqueue(msg("r10", MessageKind.RACE))
    assert drain(s, t0=2000.0) == ["r10"]
