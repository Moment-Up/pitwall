"""Pit visits and pit-lane loss (``strategy.pitloss``), on a replica of the real Austria car-14 stop (F1 25, PS5):
in-lap 81575 ms + out-lap 92836 ms against a pre-stop pace of 77750 ms (median of 74646, 77812, 77750) = 18911 ms."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from pitwall.model.telemetry import CarTiming, RaceTiming
from pitwall.strategy.pitloss import (
    EXCLUDED_FLASHBACK,
    EXCLUDED_IMPLAUSIBLE,
    EXCLUDED_LAPS_MISSING,
    EXCLUDED_LONG_STOP,
    EXCLUDED_NO_PRE_LAP,
    EXCLUDED_NOT_COMPLETED,
    EXCLUDED_PARTLY_NEUTRAL,
    EXCLUDED_PENALTY,
    PitTracker,
)
from tests.unit.strategy_helpers import car, timing

AUSTRIA = {62: 74646, 63: 77812, 64: 77750, 65: 81575, 66: 92836, 67: 74324, 68: 74500, 69: 74600}
OTHERS = {n: 75000 + 10 * n for n in range(60, 71)}


def _ticks(
    times: dict[int, int],
    first_lap: int,
    last_lap: int,
    *,
    idx: int = 14,
    pit_lap: int | None = 65,
    stop_ms: int = 3353,
    lane_ms: int = 20019,
    pen: bool = False,
    extra_cars: bool = True,
) -> Iterator[tuple[float, list[CarTiming]]]:
    """(session time, cars) samples: four per lap plus the pit visit of ``idx`` (entry at 4264 m, box, exit 257 m)."""
    t = 0.0
    for lap in range(first_lap, last_lap + 1):
        lap_s = times.get(lap, 75000) / 1000
        last = times.get(lap - 1) if lap > first_lap else None
        for frac in (0.01, 0.4, 0.8, 0.99):
            dist = 4318 * frac
            pit = 0
            lane = stop = None
            if pit_lap is not None and lap == pit_lap and dist > 4264:
                pit, lane = 1, 1000
            if pit_lap is not None and lap == pit_lap + 1 and frac <= 0.01:
                pit, lane, stop = 2, 7157, stop_ms // 2
            row = car(
                idx,
                5,
                lap=lap,
                dist=dist,
                last_ms=last,
                pit=pit,
                lane_ms=lane,
                stop_ms=stop,
                pen=pen,
                stops=1 if (pit_lap is not None and lap > pit_lap) else 0,
            )
            cars = [row]
            if extra_cars:
                cars += [
                    car(k, 6 + k, lap=lap, dist=dist, last_ms=OTHERS.get(lap - 1) if lap > first_lap else None)
                    for k in (1, 2, 3)
                ]
            yield t + lap_s * frac, cars
            if pit_lap is not None and lap == pit_lap + 1 and frac == 0.01:
                yield (
                    t + lap_s * 0.02,
                    [
                        car(idx, 5, lap=lap, dist=150, pit=1, lane_ms=lane_ms - 500, stop_ms=stop_ms, pen=pen, stops=1),
                        *cars[1:],
                    ],
                )
                yield t + lap_s * 0.03, [car(idx, 5, lap=lap, dist=257, pit=0, stops=1), *cars[1:]]
        t += lap_s


def _run(ticks: Iterator[tuple[float, list[CarTiming]]], sc_laps: set[int] | None = None) -> PitTracker:
    pt = PitTracker()
    for t, cars in ticks:
        lap = cars[0].lap_number
        pt.update(timing(t, cars, player=99), "full" if sc_laps and lap in sc_laps else "none")
    return pt


def test_austria_replica_loss_entry_exit_and_post_pace() -> None:
    pt = _run(_ticks(AUSTRIA, 61, 70))
    (v,) = pt.visits
    assert (v.entry_lap, v.exit_lap) == (65, 66)
    assert v.entry_m == pytest.approx(4318 * 0.99) and v.exit_m == 257
    assert v.stationary_ms == 3353 and v.lane_time_ms is not None and v.lane_time_ms >= 19519
    assert v.laps_ms == [81575, 92836] and v.pace_before_ms == 77750 and v.pit_loss_ms == 18911
    assert v.excluded is None and v.neutralised is None
    assert v.pace_after_ms == 74500 and v.post_done  # median of 74324, 74500, 74600
    assert pt.green_loss() == {"median_s": 18.9, "range": {"low": 18.9, "high": 18.9}, "n": 1}
    assert pt.measured_gains() == [pytest.approx(3.25)]
    row = v.row()
    assert row["pit_loss_ms"] == 18911 and row["is_player"] is False and row["laps_ms"] == [81575, 92836]


@pytest.mark.parametrize(
    ("kw", "first", "reason"),
    [
        ({"stop_ms": 8541}, 61, EXCLUDED_LONG_STOP),
        ({"pen": True}, 61, EXCLUDED_PENALTY),
        ({}, 65, EXCLUDED_NO_PRE_LAP),  # first seen on its in-lap (real Austria car 7)
    ],
)
def test_exclusions(kw: dict[str, object], first: int, reason: str) -> None:
    pt = _run(_ticks(AUSTRIA, first, 70, **kw))  # type: ignore[arg-type]
    (v,) = pt.visits
    assert v.excluded == reason
    assert pt.green_loss() is None


def test_implausible_loss_is_excluded() -> None:
    times = {**AUSTRIA, 65: 78000, 66: 80000}  # 2.5 s: not a real stop
    (v,) = _run(_ticks(times, 61, 70)).visits
    assert v.excluded == EXCLUDED_IMPLAUSIBLE


def test_laps_not_all_observed() -> None:
    pt = PitTracker()
    ticks = [(t, cars) for t, cars in _ticks(AUSTRIA, 61, 70) if not (66 < cars[0].lap_number < 68 and t > 0)]
    # car 14 jumps from lap 66 to 68: lap 66's time arrives (last_lap = lap 67's), lap 66 is missing
    for t, cars in ticks:
        pt.update(timing(t, cars, player=99), "none")
    (v,) = pt.visits
    assert v.excluded == EXCLUDED_LAPS_MISSING and v.pit_loss_ms is None


def test_neutralised_stop_uses_the_field_reference() -> None:
    pt = _run(_ticks(AUSTRIA, 61, 70), sc_laps={65, 66})
    (v,) = pt.visits
    assert v.neutralised == "full" and v.excluded is None
    assert v.pit_loss_ms == 81575 + 92836 - (OTHERS[65] + OTHERS[66])
    assert pt.green_loss() is None
    sc = pt.neutral_loss()
    assert sc["full_s"] == pytest.approx(round(v.pit_loss_ms / 1000, 1)) and sc["tier"] == "measured"


def test_stop_with_the_safety_car_on_only_part_of_it_is_excluded() -> None:
    """The safety car on the in-lap but not the out-lap (it ended around the stop): the field's laps hold different
    shares of neutralised running, so the stop is neither a green nor a safety-car measurement."""
    pt = _run(_ticks(AUSTRIA, 61, 70), sc_laps={65})
    (v,) = pt.visits
    assert v.neutralised == "full" and v.excluded == EXCLUDED_PARTLY_NEUTRAL
    assert pt.green_loss() is None
    assert pt.neutral_loss() == {"full_s": None, "virtual_s": None, "tier": "heuristic"}


def test_sc_loss_heuristic_only_without_a_measurement() -> None:
    pt = _run(_ticks(AUSTRIA, 61, 70))
    sc = pt.neutral_loss()
    assert sc == {
        "full_s": pytest.approx(18.9 * 0.5, abs=0.06),
        "virtual_s": pytest.approx(18.9 * 0.6, abs=0.06),
        "tier": "heuristic",
    }
    assert PitTracker().neutral_loss() == {"full_s": None, "virtual_s": None, "tier": "heuristic"}


def test_entry_and_exit_medians() -> None:
    pt = _run(_ticks(AUSTRIA, 61, 70))
    assert pt.pit_entry_m() == pytest.approx(4318 * 0.99, abs=0.1) and pt.pit_exit_m() == 257


def test_rewind_during_the_stop_excludes_it() -> None:
    pt = PitTracker()
    t_entry = None
    for t, cars in _ticks(AUSTRIA, 61, 70):
        pt.update(timing(t, cars, player=99), "none")
        if cars[0].pit_status and t_entry is None:
            t_entry = t
            pt.rewind(t - 0.0)  # a flashback while in the lane
    (v,) = pt.visits
    assert v.excluded == EXCLUDED_FLASHBACK


def test_out_lap_not_completed_at_session_end() -> None:
    pt = PitTracker()
    for t, cars in _ticks(AUSTRIA, 61, 66):
        pt.update(timing(t, cars, player=99), "none")
    out = pt.end_session()
    assert [v.excluded for v in out] == [EXCLUDED_NOT_COMPLETED]


def test_retired_car_parked_in_the_pits_is_not_a_stop() -> None:
    pt = PitTracker()
    pt.update(timing(0.0, [car(2, 3, lap=67, dist=100)], player=99), "none")
    pt.update(timing(1.0, [car(2, 3, lap=67, dist=156, pit=1, result="retired")], player=99), "none")
    pt.update(timing(2.0, [car(2, 3, lap=67, dist=156, pit=2, result="retired")], player=99), "none")
    assert pt.end_session() == [] and pt.visits == []


def test_player_flag_and_rows() -> None:
    pt = PitTracker()
    rows: list[RaceTiming] = []
    for t, cars in _ticks(AUSTRIA, 61, 70, extra_cars=False):
        c = cars[0]
        rows.append(timing(t, [CarTiming(**{**{s: getattr(c, s) for s in c.__slots__}, "is_player": True})]))
    for rt in rows:
        pt.update(rt, "none")
    (v,) = pt.player_stops()
    assert v.is_player and v.row()["is_player"] is True


def test_sc_loss_tier_is_measured_only_when_every_value_is() -> None:
    from pitwall.strategy.pitloss import PitVisit

    pt = PitTracker()
    full = PitVisit(
        14, False, 5, 4264.0, 1.0, None, "medium", exit_lap=6, final=True, pit_loss_ms=9800, neutralised="full"
    )
    green = PitVisit(7, False, 9, 4264.0, 2.0, None, "medium", exit_lap=10, final=True, pit_loss_ms=19000)
    pt.visits = [full]
    assert pt.neutral_loss() == {"full_s": 9.8, "virtual_s": None, "tier": "measured"}
    pt.visits = [full, green]
    assert pt.neutral_loss() == {"full_s": 9.8, "virtual_s": pytest.approx(11.4), "tier": "heuristic"}


def test_a_flashback_into_a_stop_the_car_has_left_reopens_it() -> None:
    """Review exp3: a flashback to a moment inside a car's stop (already closed, loss not yet worked out) used to set
    its pit status to 0; the next tick, the car back in the lane, opened a second "stop" on its out-lap: a 16 s green
    loss from one stop (true 20 s) and the out-lap's distance as the pit entry (2162 m for a true 4264 m)."""

    def car2(t: float, lap: int, dist: float, pit: int, last_ms: int | None) -> list[CarTiming]:
        lane = int((t - 999) * 1000) if pit else None
        return [
            car(1, 1, player=True, lap=lap, dist=dist, gap_ms=None),
            car(2, 2, lap=lap, dist=dist, pit=pit, last_ms=last_ms, lane_ms=lane, stop_ms=2500 if pit else None),
        ]

    pt = PitTracker()
    for lap in range(2, 10):  # green laps of 80 s
        for k in range(160):
            t = (lap - 2) * 80 + k * 0.5 + 360
            pt.update(timing(t, car2(t, lap, k * 27.0, 0, 80000 if lap > 2 else None)), None)
    for t, lap, dist, pit, last in (
        (999.0, 10, 4264.0, 1, 80000),  # pit entry on lap 10
        (1003.0, 11, 10.0, 1, 84000),  # crosses the line in the lane (in-lap 84 s)
        (1010.0, 11, 150.0, 2, 84000),
        (1015.0, 11, 257.0, 0, 84000),  # pit exit
        (1020.0, 11, 400.0, 0, 84000),
    ):
        pt.update(timing(t, car2(t, lap, dist, pit, last)), None)
    pt.rewind(1006.0)  # back into the lane, after the line
    for t, lap, dist, pit in ((1006.0, 11, 60.0, 1), (1010.0, 11, 150.0, 2), (1015.0, 11, 257.0, 0)):
        pt.update(timing(t, car2(t, lap, dist, pit, 84000)), None)
    for k in range(1, 200):
        t = 1015.0 + k * 0.5
        lap = 11 if t < 1099 else 12 if t < 1179 else 13
        pt.update(timing(t, car2(t, lap, 300.0, 0, {11: 84000, 12: 96000, 13: 80000}[lap])), None)
    (v,) = pt.visits
    assert (v.entry_lap, v.exit_lap, v.excluded) == (10, 11, EXCLUDED_FLASHBACK)
    assert pt.green_loss() is None and pt.pit_entry_m() == 4264.0 and pt.pit_exit_m() == 257.0


def test_a_flashback_to_an_earlier_lap_forgets_the_laps_driven_again() -> None:
    pt = PitTracker()
    for t, lap, pit, last in ((0.0, 5, 0, None), (80.0, 6, 0, 80000), (160.0, 7, 0, 81000), (170.0, 7, 1, 81000)):
        pt.update(timing(t, [car(1, 1, player=True, lap=lap), car(2, 2, lap=lap, pit=pit, last_ms=last)]), None)
    st = pt.cars[2]
    assert st.times == {5: 80000, 6: 81000} and 7 in st.pitted
    pt.rewind(100.0)
    pt.update(timing(100.0, [car(1, 1, player=True, lap=6), car(2, 2, lap=6, last_ms=80000)]), None)
    assert st.times == {5: 80000} and 7 not in st.pitted and not pt.visits and pt.in_lane(2) is None
