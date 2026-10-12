"""Undercut / overcut / rejoin (``strategy.cuts``): heuristic bands and the cases where the answer is unknown."""

from __future__ import annotations

import pytest

from pitwall.strategy.cuts import cut_view, neighbour_stop, rejoin, tyre_gain
from tests.unit.strategy_helpers import car

G = (1.0, "game")


def test_gain_prefers_the_game_model_then_measured_stops() -> None:
    assert tyre_gain(("medium", 0.69, 0.09), []) == (pytest.approx(0.78), "game")
    assert tyre_gain(("medium", 0.69, None), []) == (pytest.approx(0.69), "game")
    assert tyre_gain(None, [3.4]) is None  # one measured stop is not enough
    assert tyre_gain(None, [3.4, 2.0, 2.6]) == (pytest.approx(2.6), "measured")
    assert tyre_gain(("soft", 0.0, None), [1.0, 1.2]) == (pytest.approx(1.1), "measured")


@pytest.mark.parametrize(
    ("gap", "status"), [(0.5, "likely"), (0.69, "likely"), (0.7, "marginal"), (1.0, "marginal"), (1.01, "unlikely")]
)
def test_undercut_bands(gap: float, status: str) -> None:
    v = cut_view("undercut", gap, True, G, car=car(0, 1), player_stops=0, stop_needed=True)
    assert v is not None and v["status"] == status and v["gain"] == {"low": 0.7, "high": 1.0} and v["tier"] == "game"


def test_unknown_cases() -> None:
    ahead = car(0, 1)
    assert cut_view("undercut", 0.5, True, None, car=ahead, player_stops=0, stop_needed=True)["status"] == "unknown"  # type: ignore[index]
    assert (
        cut_view("undercut", 0.5, False, G, car=ahead, player_stops=0, stop_needed=True)["reason"] == "gap not settled"
    )  # type: ignore[index]
    pit = cut_view("undercut", 0.5, True, G, car=car(0, 1, pit=1), player_stops=0, stop_needed=True)
    assert pit is not None and pit["status"] == "unknown" and "pit lane" in pit["reason"]
    stopped = cut_view("undercut", 0.5, True, G, car=car(0, 1, stops=2), player_stops=1, stop_needed=True)
    assert stopped is not None and stopped["reason"] == "the car ahead has already stopped"
    no_stop = cut_view("undercut", 0.5, True, G, car=ahead, player_stops=0, stop_needed=False)
    assert no_stop is not None and no_stop["reason"] == "the tyres reach the finish"  # stop rules are not sent
    assert cut_view("undercut", 0.5, True, G, car=None, player_stops=0, stop_needed=True) is None


def test_traffic_downgrades_a_likely_undercut_and_threat_wording() -> None:
    v = cut_view("undercut", 0.5, True, G, car=car(0, 1), player_stops=0, stop_needed=True, rejoin_traffic=True)
    assert v is not None and v["status"] == "marginal" and "traffic" in v["reason"]
    t = cut_view("threat", 0.5, True, G, car=car(2, 3), player_stops=0, stop_needed=True)
    assert t is not None and t["status"] == "likely" and "similar tyres" in t["reason"]


def test_rejoin_position_gaps_and_traffic() -> None:
    me = car(1, 3, leader_ms=4000, player=True)
    cars = [
        car(0, 1),
        car(5, 2, leader_ms=2000),
        me,
        car(2, 4, leader_ms=10000),
        car(3, 5, leader_ms=21500),
        car(4, 6, leader_ms=30000),
        car(6, 7, leader_ms=22000, pit=1),
    ]
    r = rejoin(me, cars, 18.0, game_position=6)
    # race time after the stop 22.0 s: ahead of it the leader, car 5, car 2 and car 3 (21.5); car 6 is in the lane
    assert r == {"position": 5, "gap_ahead_s": 0.5, "gap_behind_s": 8.0, "traffic": True, "game_position": 6}
    assert rejoin(me, cars, None, game_position=0) is None
    assert rejoin(me, cars, None, game_position=6)["game_position"] == 6  # type: ignore[index]


def test_neighbour_stop_statuses() -> None:
    me = car(1, 3, leader_ms=4000, player=True)
    ahead = car(0, 2, leader_ms=2000, pit=1)
    cars = [car(9, 1), ahead, me, car(2, 4, leader_ms=19500)]
    ns = neighbour_stop("ahead", ahead, 2000, me, cars, 18.0)
    assert ns["status"] == "covered" and ns["rejoin_gap_s"] == 16.0 and ns["traffic"] is True  # 0.5 s behind car 2
    assert neighbour_stop("ahead", ahead, 2000, me, cars, 2.5)["status"] == "close"
    assert neighbour_stop("ahead", ahead, 2000, me, cars, 0.5)["status"] == "ahead"
    assert neighbour_stop("ahead", ahead, 2000, me, cars, None)["status"] == "unknown"
