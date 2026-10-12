"""The radio policy's race radio additions (voice.scheduler): kind RACE and its own per-lap allowance."""

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


def test_race_allowance_is_its_own_and_never_eats_the_talk_budget() -> None:
    assert RACE_PER_LAP == {"quiet": 0, "normal": 2, "detailed": 3}
    s = RadioScheduler("normal")
    for i in range(4):
        s.enqueue(msg(f"r{i}", MessageKind.RACE))
    for i in range(3):
        s.enqueue(msg(f"c{i}", MessageKind.STRATEGY))
    said = drain(s)
    assert sorted(x for x in said if x.startswith("r")) == ["r0", "r1"]  # 2 race calls on lap 5
    assert len([x for x in said if x.startswith("c")]) == TALK_PER_LAP["normal"]  # and the full talk budget too
    next_lap = DrivingState(True, 200.0, 0.0, 0.0, 6, 100.0, None)
    assert drain(s, next_lap, t0=500.0) == ["r2", "r3", "c2"]  # a new lap, new allowances
    detailed = RadioScheduler("detailed")
    for i in range(5):
        detailed.enqueue(msg(f"r{i}", MessageKind.RACE))
    assert len(drain(detailed)) == 3


def test_off_track_no_allowance_and_urgent_never_counts() -> None:
    off = DrivingState(False, None, None, None, 5, None, None)
    s = RadioScheduler("normal")
    for i in range(5):
        s.enqueue(msg(f"r{i}", MessageKind.RACE))
    assert len(drain(s, off)) == 5


def test_rank_ties_with_the_lap_summary_first_in_first_out() -> None:
    assert KIND_RANK[MessageKind.RACE] == KIND_RANK[MessageKind.LAP_SUMMARY] == 2
    s = RadioScheduler("detailed")
    s.enqueue(msg("race", MessageKind.RACE))
    s.enqueue(msg("summary", MessageKind.LAP_SUMMARY, lap=4))
    s.enqueue(msg("strategy", MessageKind.STRATEGY))
    assert [m.id for m in s.pending()] == ["race", "summary", "strategy"]


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
