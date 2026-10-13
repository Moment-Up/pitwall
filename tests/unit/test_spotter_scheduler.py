"""The radio's interrupt contract (urgent > cue > the rest; equal ranks never cut each other), the SPOTTER kind's
policy, and no speak window while a car is alongside."""

from __future__ import annotations

from pitwall.voice.scheduler import (
    ALLOWED_KINDS,
    BUDGETED,
    DRIVER_LAP_KINDS,
    KIND_RANK,
    RadioScheduler,
    _repeat_filtered,
    interrupt_rank,
    may_interrupt,
    speak_window_ok,
)
from pitwall.voice.types import DrivingState, MessageKind, Priority, RadioMessage


def _m(kind: MessageKind, prio: Priority = Priority.NORMAL, text: str = "x", needs_window: bool = True) -> RadioMessage:
    return RadioMessage(f"{kind}-{prio}-{text}", kind, prio, text, text, 0.0, needs_speak_window=needs_window)


def _state(traffic: bool | None) -> DrivingState:
    return DrivingState(True, 200.0, 0.0, 0.0, 3, 500.0, None, traffic_alongside=traffic)


def test_interrupt_rank_and_may_interrupt() -> None:
    spot = _m(MessageKind.SPOTTER, Priority.URGENT)
    alert = _m(MessageKind.ALERT, Priority.URGENT)
    cue = _m(MessageKind.CUE, Priority.HIGH)
    summary = _m(MessageKind.LAP_SUMMARY)
    still = _m(MessageKind.SPOTTER, Priority.HIGH)
    assert [interrupt_rank(x) for x in (spot, alert, cue, summary, still)] == [2, 2, 1, 0, 0]
    assert may_interrupt(spot, cue) and may_interrupt(spot, summary) and may_interrupt(alert, cue)
    assert not may_interrupt(spot, alert) and not may_interrupt(alert, spot) and not may_interrupt(spot, spot)
    assert not may_interrupt(still, summary)  # still_there never cuts anything
    assert not may_interrupt(cue, summary) and not may_interrupt(cue, cue)  # only the urgent path interrupts


def test_spotter_kind_policy() -> None:
    for intensity in ("quiet", "normal", "detailed"):
        assert MessageKind.SPOTTER in ALLOWED_KINDS[intensity]  # type: ignore[index]
    assert KIND_RANK[MessageKind.SPOTTER] == 0
    assert MessageKind.SPOTTER not in BUDGETED and MessageKind.SPOTTER not in DRIVER_LAP_KINDS
    assert not _repeat_filtered(_m(MessageKind.SPOTTER, Priority.HIGH))


def test_no_speak_window_while_a_car_is_alongside() -> None:
    assert speak_window_ok(_state(None), 2.0)
    assert speak_window_ok(_state(False), 2.0)
    assert not speak_window_ok(_state(True), 2.0)
    off_track = DrivingState(False, None, None, None, None, None, None, traffic_alongside=True)
    assert speak_window_ok(off_track, 2.0)


def test_a_lap_summary_waits_out_traffic_in_the_scheduler() -> None:
    s = RadioScheduler("normal", min_gap_s=0.0)
    s.enqueue(_m(MessageKind.LAP_SUMMARY, text="Lap time one twenty"))
    assert s.next_message(_state(True), 10.0, False) is None
    msg = s.next_message(_state(False), 10.1, False)
    assert msg is not None and msg.kind is MessageKind.LAP_SUMMARY
