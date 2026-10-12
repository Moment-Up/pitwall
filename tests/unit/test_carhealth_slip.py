"""Lock-ups and wheelspin per lap (``carhealth.slip``): the technique thresholds, ABS, traction control per frame,
corner attribution and flashbacks."""

from __future__ import annotations

from pitwall.carhealth.engine import CarHealthEngine
from pitwall.carhealth.slip import SlipCounter
from pitwall.technique.thresholds import LOCKUP_MIN_S, LOCKUP_SLIP, SPIN_MIN_S, SPIN_SLIP
from tests.unit.carhealth_helpers import frame, info, model

LOCKED = (LOCKUP_SLIP - 0.5, 0.0, 0.0, 0.0)
SPIN = (0.0, 0.0, SPIN_SLIP + 0.1, 0.0)
CLEAN = (0.0, 0.0, 0.0, 0.0)


def _run(
    c: SlipCounter,
    t: float,
    seconds: float,
    slip: tuple[float, float, float, float],
    *,
    d: float = 500.0,
    brake: float = 0.0,
    throttle: float = 0.0,
    lap: int = 2,
    abs_on: bool | None = False,
    tc: int | None = 1,
    pit: int = 0,
) -> float:
    n = round(seconds * 60)
    for k in range(n):
        c.on_frame(
            frame(
                t + k / 60, lap=lap, d=d + k, slip=slip, brake=brake, throttle=throttle, abs_on=abs_on, tc=tc, pit=pit
            )
        )
    return t + n / 60


def test_lockup_needs_the_slip_the_brake_and_the_time() -> None:
    c = SlipCounter()
    t = _run(c, 0.0, 1.0, CLEAN)
    t = _run(c, t, LOCKUP_MIN_S + 0.05, LOCKED, brake=0.8)  # long enough
    t = _run(c, t, 0.5, CLEAN)
    t = _run(c, t, LOCKUP_MIN_S / 2, LOCKED, brake=0.8)  # too short
    t = _run(c, t, 0.5, CLEAN)
    t = _run(c, t, 0.5, LOCKED, brake=0.0)  # no brake: a wheel hopping, not a lock-up
    t = _run(c, t, 0.5, CLEAN)
    last = c.on_line(2, 3)
    assert last is not None and last["lockups"] == 1 and last["wheelspin"] == 0
    assert c.last_events[0].wheels == ("FL",)


def test_abs_on_never_counts_lockups() -> None:
    c = SlipCounter()
    t = _run(c, 0.0, 0.5, LOCKED, brake=0.9, abs_on=True)
    _run(c, t, 0.5, CLEAN, abs_on=True)
    last = c.on_line(2, 3)
    assert last is not None and last["lockups"] == 0 and c.abs_on is True
    eng = CarHealthEngine("a")
    eng.feed(info())
    for k in range(120):
        eng.feed(frame(k / 60, slip=LOCKED, brake=0.9, abs_on=True))
    slip = eng.view()["slip"]
    assert slip["available"] and slip["lockups_applicable"] is False and "ABS is on" in slip["reason"]


def test_wheelspin_keeps_the_traction_control_of_its_first_frame() -> None:
    c = SlipCounter()
    t = _run(c, 0.0, SPIN_MIN_S + 0.1, SPIN, throttle=0.9, tc=2)  # full TC: shown, not spoken
    t = _run(c, t, 0.5, CLEAN, throttle=0.9)
    t = _run(c, t, SPIN_MIN_S + 0.1, SPIN, throttle=0.9, tc=1)  # medium: spoken
    t = _run(c, t, 0.5, CLEAN, throttle=0.9)
    t = _run(c, t, SPIN_MIN_S - 0.05, SPIN, throttle=0.9, tc=0)  # too short
    _run(c, t, 0.5, CLEAN, throttle=0.9)
    last = c.on_line(2, 3)
    assert last is not None and last["wheelspin"] == 2 and last["wheelspin_spoken"] == 1
    assert [e.tc for e in c.last_events] == [2, 1]


def test_pit_lane_frames_never_count_nor_set_the_level() -> None:
    """The game reports TC 0 in the pit lane: those frames neither count nor change the level used for speaking."""
    c = SlipCounter()
    t = _run(c, 0.0, 0.5, CLEAN, throttle=0.9, tc=2)
    _run(c, t, 1.0, SPIN, throttle=0.9, tc=0, pit=1)
    last = c.on_line(2, 3)
    assert last is not None and last["wheelspin"] == 0 and c.tc == 2 and last["pit"] is True


def test_events_are_attributed_to_the_corner_they_start_in() -> None:
    eng = CarHealthEngine("c", track_model=lambda: model([0.0, 1000.0, 2500.0]))
    eng.feed(info())
    t = 0.0
    for d0 in (1200.0, 1300.0, 2600.0):
        for k in range(30):
            eng.feed(frame(t + k / 60, d=d0 + k, slip=LOCKED, brake=0.8))
        t += 0.5
        for k in range(30):
            eng.feed(frame(t + k / 60, d=d0 + 100 + k, slip=CLEAN))
        t += 0.5
    eng.feed(frame(t, lap=3, d=5.0, slip=CLEAN))
    last = eng.slip.last_lap
    assert last is not None and last["lockups"] == 3
    assert [(c["corner"], c["lockups"]) for c in last["corners"]] == [("T2", 2), ("T3", 1)]
    assert SlipCounter.top_corner(eng.slip.last_events, "lockup") == ("T2", "T2", 2)


def test_a_flashback_drops_the_lap_counts() -> None:
    c = SlipCounter()
    t = _run(c, 0.0, 0.5, LOCKED, brake=0.8)
    t = _run(c, t, 0.5, CLEAN)
    c.rewind()
    _run(c, t - 1.0, 0.5, CLEAN)
    last = c.on_line(2, 3)
    assert last is not None and last["lockups"] == 0 and last["flashback"] is True
    eng = CarHealthEngine("f")
    eng.feed(info())
    for k in range(60):
        eng.feed(frame(10 + k / 60, slip=LOCKED, brake=0.8))
    eng.feed(frame(5.0, slip=CLEAN))  # the clock went back 5 s: a rewind
    assert eng.slip.current()["lockups"] == 0 and eng.rewinds == 1


def test_no_slip_ratio_no_block() -> None:
    eng = CarHealthEngine("g")
    eng.feed(info())
    eng.feed(frame(1.0, slip=None))
    assert eng.view()["slip"]["available"] is False
