"""Gaps ahead / behind (``strategy.gaps``): the settle rule, line gaps, trends, the within-a-second hysteresis and
rewinds. Unit tier; the real Monza / Austria behaviour is in ``tests/recorded/test_strategy_real.py``."""

from __future__ import annotations

import pytest

from pitwall.strategy.gaps import SETTLE_S, GapTracker, car_gap_view, laps_to_within
from tests.unit.strategy_helpers import car, timing, with_

P = 1  # the player's car index


def field(
    t: float,
    *,
    lap: int = 5,
    dist: float = 1000.0,
    ahead_gap: int | None = 1500,
    behind_gap: int | None = 900,
    player_pos: int = 2,
    ahead_pit: int = 0,
    behind_pit: int = 0,
    ahead_idx: int = 0,
    behind_idx: int = 2,
):
    return timing(
        t,
        [
            car(ahead_idx, player_pos - 1, lap=lap, dist=dist + 80, gap_ms=None, pit=ahead_pit),
            car(P, player_pos, lap=lap, dist=dist, gap_ms=ahead_gap, player=True),
            car(behind_idx, player_pos + 1, lap=lap, dist=dist - 40, gap_ms=behind_gap, pit=behind_pit),
        ],
    )


def test_unsettled_until_settle_s_after_a_change() -> None:
    g = GapTracker()
    g.update(field(0.0))
    assert not g.ahead.settled and g.ahead.value_s is None  # just appeared: a change
    g.update(field(SETTLE_S - 0.5))
    assert not g.ahead.settled
    g.update(field(SETTLE_S))
    assert g.ahead.settled and g.ahead.value_s == pytest.approx(1.5) and g.behind.value_s == pytest.approx(0.9)
    # position change: the old gap is never published as the new car's; settled again 4 s later
    g.update(field(10.0, player_pos=3, ahead_idx=5, ahead_gap=2453))
    assert g.ahead.car_index == 5 and not g.ahead.settled and g.ahead.value_s is None
    g.update(field(10.0 + SETTLE_S, player_pos=3, ahead_idx=5, ahead_gap=1235))
    assert g.ahead.settled and g.ahead.value_s == pytest.approx(1.235)


def test_adjacent_car_in_the_pit_lane_unsettles_and_keeps_the_last_value() -> None:
    g = GapTracker()
    for t in range(0, 6):
        g.update(field(float(t)))
    assert g.ahead.settled
    evs = g.update(field(6.0, ahead_pit=1, ahead_gap=19100))  # real Austria L62: 19.1 s while the car pits
    assert any(e.kind == "pit_entry" and e.side == "ahead" for e in evs)
    assert not g.ahead.settled and g.ahead.value_s == pytest.approx(1.5)
    g.update(field(8.0, ahead_gap=1500))  # out of the lane: a change, so 4 s again
    assert not g.ahead.settled
    g.update(field(12.0, ahead_gap=1600))
    assert g.ahead.settled and g.ahead.value_s == pytest.approx(1.6)


def test_wrapped_or_missing_gap_is_unsettled() -> None:
    g = GapTracker()
    for t in range(0, 6):
        g.update(field(float(t)))
    g.update(field(6.0, ahead_gap=None))  # the adapter turns 65403 (wrapped -133 ms) into None
    assert not g.ahead.settled and g.ahead.value_s == pytest.approx(1.5)


def _laps(g: GapTracker, gaps_ahead: list[int], *, start_lap: int = 2, car_idx: int = 0, t0: float = 0.0) -> float:
    """Drive one lap per value: the line window (first 5 s of the next lap) sees that gap."""
    t = t0
    for k, gap in enumerate(gaps_ahead):
        lap = start_lap + k
        for dt in (0.0, 1.0, 2.0, 3.0, 4.0, 5.5, 30.0):
            g.update(field(t + dt, lap=lap, ahead_gap=gap, ahead_idx=car_idx))
        t += 60.0
    return t


def test_line_window_median_and_trend_need_three_laps_to_the_same_car() -> None:
    g = GapTracker()
    t = _laps(g, [3000, 3000, 2700])
    slope, n = g.trend(g.ahead)
    assert n == 2 and slope is None  # first lap's window still unsettled -> 2 line gaps
    t = _laps(g, [2400, 2100], start_lap=5, t0=t)
    slope, n = g.trend(g.ahead)
    assert n == 4 and slope == pytest.approx(-0.3, abs=0.01)
    lg = g.line_gap("ahead", 4)  # lap 4's line gap: the first 5 s of lap 5
    assert lg is not None and lg.gap_s == pytest.approx(2.4) and lg.car_index == 0
    # a different car ahead: its trend starts again
    _laps(g, [1000, 900], start_lap=7, car_idx=7, t0=t)
    assert g.trend(g.ahead)[0] is None


def test_neutralised_laps_are_left_out_of_the_trend() -> None:
    g = GapTracker()
    t = _laps(g, [3000, 3000, 2700, 2400])
    g.mark_neutral_lap(6)
    _laps(g, [1000, 2100, 1800], start_lap=6, t0=t)
    lg = g.line_gap("ahead", 6)
    assert lg is not None and lg.neutralised
    slope, n = g.trend(g.ahead)
    assert slope == pytest.approx(-0.3, abs=0.01) and n == 5


def test_within_a_second_hysteresis() -> None:
    g = GapTracker()
    for t in range(0, 5):
        g.update(field(float(t), behind_gap=1100))
    assert g.behind.within is False
    ev = g.update(field(5.0, behind_gap=950))
    assert g.behind.within is False and not ev  # one tick is not enough
    ev = g.update(field(5.5, behind_gap=940))
    assert g.behind.within is True and [e.kind for e in ev] == ["within"]
    g.update(field(6.0, behind_gap=1150))
    assert g.behind.within is True  # 1.0-1.2 s: still within
    g.update(field(6.5, behind_gap=1250))
    assert g.behind.within is False


def test_rewind_drops_later_line_gaps_and_unsettles() -> None:
    g = GapTracker()
    _laps(g, [3000, 3000, 2700, 2400])
    assert g.line_gap("ahead", 4) is not None
    g.rewind(150.0)  # back into lap 4's line window time and earlier
    assert g.line_gap("ahead", 4) is None and g.line_gap("ahead", 2) is not None
    assert not g.update(field(151.0, lap=4)) or not g.ahead.settled


def test_laps_to_within_and_view() -> None:
    assert laps_to_within(2.5, -0.3, 20.0) == pytest.approx(5.0)
    assert laps_to_within(2.5, -0.01, 20.0) is None  # closing too slowly
    assert laps_to_within(2.5, -0.3, 3.0) is None  # not before the flag
    assert laps_to_within(0.8, -0.3, 20.0) is None
    g = GapTracker()
    t = _laps(g, [3000, 2700, 2400, 2100])
    for dt in (0.0, 1.0):
        g.update(field(t + dt, lap=6, ahead_gap=2000))
    v = car_gap_view(g, g.ahead, 20.0, drs_enabled=True, packet_format=2025)
    assert v is not None and v["car_index"] == 0 and v["trend_s_per_lap"] == pytest.approx(-0.3, abs=0.01)
    assert v["drs_range"] is False and v["tyre"] == {"compound": "medium", "age_laps": 5}
    assert car_gap_view(g, g.ahead, 20.0, drs_enabled=True, packet_format=2026)["drs_range"] is None  # type: ignore[index]
    assert car_gap_view(g, g.ahead, 20.0, drs_enabled=None, packet_format=2025)["drs_range"] is None  # type: ignore[index]


def test_leader_gap_and_p1() -> None:
    g = GapTracker()
    rt = timing(0.0, [car(P, 2, gap_ms=1500, leader_ms=1500, player=True), car(0, 1, gap_ms=None)])
    g.update(rt)
    g.update(timing(SETTLE_S, [with_(rt.cars[0]), rt.cars[1]]))
    assert g.leader_s == pytest.approx(1.5)
    g.update(timing(10.0, [car(P, 1, gap_ms=None, player=True), car(0, 2, gap_ms=800)]))
    assert g.leader_s is None and g.ahead.car is None and g.behind.car_index == 0
