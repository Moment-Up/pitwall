"""Where the player comes out (``strategy.rejoin``): chained, last-known and expired gaps, cars in the lane, the range,
road traffic with a lapped car, the freeze on the in-lap, the game-only basis, ``PitTracker``'s entry gap fallback
and the ``cuts.rejoin`` wrapper. Real-data evaluation: ``scripts/carhealth_check.py`` (Imola, 32 stops)."""

from __future__ import annotations

import pytest

from pitwall.strategy import rejoin as rj
from pitwall.strategy.cuts import rejoin as cuts_rejoin
from pitwall.strategy.engine import StrategyEngine
from pitwall.strategy.pitloss import PitTracker
from tests.unit.strategy_helpers import car, session, timing, with_

LOSS = rj.Loss.of(20.0, 19.0, 21.5, 5, "measured")


def test_leader_gaps_game_then_chained_then_last_known() -> None:
    cars = [
        car(0, 1),
        car(1, 2, leader_ms=2000),
        with_(car(2, 3), gap_leader_ms=None, gap_ahead_ms=1500),  # chained: 2.0 + 1.5
        with_(car(3, 4), gap_leader_ms=None, gap_ahead_ms=None),  # zeroed on its in-lap: last known
        with_(car(4, 5), gap_leader_ms=None, gap_ahead_ms=None),  # last known too old
    ]
    last = {3: (95.0, 6.0), 4: (80.0, 9.0)}
    out = rj.resolve_leader_gaps(cars, 100.0, last)
    assert out[0] == (0.0, "game") and out[1] == (2.0, "game")
    assert out[2] == (pytest.approx(3.5), "chained")
    assert out[3] == (6.0, "last_known")
    assert out[4] == (None, None)  # 20 s old: unknown
    known: dict[int, tuple[float, float]] = {}
    rj.remember(known, out, 100.0)
    assert set(known) == {0, 1, 2}  # a stale value is never refreshed as if it were new


def _predict(cars: list, **kw: object) -> dict | None:  # type: ignore[type-arg]
    me = next(c for c in cars if c.is_player)
    resolved = rj.resolve_leader_gaps(cars, 100.0, kw.pop("last_known", None))  # type: ignore[arg-type]
    return rj.predict(me, cars, resolved=resolved, **{"loss": LOSS, "game_position": 8, **kw})  # type: ignore[arg-type]


def test_position_range_neighbours_and_the_unknown_cars() -> None:
    cars = [
        car(0, 1),
        car(5, 2, leader_ms=3000, player=True),
        car(2, 3, leader_ms=10000),
        car(3, 4, leader_ms=22500),
        car(4, 5, leader_ms=23500),
        car(6, 6, leader_ms=30000),
        with_(car(7, 7), gap_leader_ms=None, gap_ahead_ms=None),  # unknown
    ]
    r = _predict(cars)
    assert r is not None
    # out at 23.0 s: ahead the leader, car 2 (10.0) and car 3 (22.5); 19.0..21.5 loss -> 22.0..24.5
    assert r["position"] == 4 and r["position_low"] == 3 and r["position_high"] == 5
    assert r["ahead_position"] == 3 and r["gap_ahead_s"] == 0.5 and r["behind_position"] == 5
    assert r["gap_behind_s"] == 0.5 and r["unknown_cars"] == 1 and r["game_position"] == 8
    assert r["basis"] == "measured_loss" and r["loss_s"] == 20.0 and r["loss_n"] == 5 and r["frozen"] is False


def test_cars_in_the_lane_rejoin_at_their_entry_gap_plus_the_loss() -> None:
    cars = [car(0, 1), car(5, 2, leader_ms=3000, player=True), car(2, 3, leader_ms=10000, pit=1)]
    assert _predict(cars)["position"] == 2  # type: ignore[index]  # car 2 in the lane, entry unknown: left out
    r = _predict(cars, in_lane={2: 1.0})  # it entered 1 s behind the leader: out at 21 s, ahead of 23
    assert r is not None and r["position"] == 3 and r["unknown_cars"] == 0
    r = _predict(cars, in_lane={2: 5.0})  # out at 25 s: behind
    assert r is not None and r["position"] == 2


def test_the_range_without_two_measured_stops_is_ten_percent() -> None:
    one = rj.Loss.of(20.0, 20.0, 20.0, 1, "measured")
    assert (one.low_s, one.high_s) == (pytest.approx(18.0), pytest.approx(22.0))
    assert rj.Loss.of(20.0, 19.0, 21.0, 2, "measured").low_s == 19.0


def test_road_traffic_sees_a_lapped_car() -> None:
    """A car a lap down is no position to lose, but rejoining just behind it on the road is traffic."""
    lapped = with_(car(9, 12), gap_leader_ms=None, gap_ahead_ms=None)
    cars = [car(0, 1), car(5, 2, leader_ms=3000, player=True), lapped]
    last = {9: (99.0, 23.0 + 90.0 - 0.6)}  # race time 0.6 s ahead of us on the road, a lap (90 s) down
    r = _predict(cars, last_known=last, lap_s=90.0)
    assert r is not None and r["position"] == 2  # behind the leader only (the lapped car is far behind on time)
    assert r["traffic"] is True and r["road_ahead_s"] == 0.6 and r["gap_ahead_s"] == 23.0
    r = _predict(cars, last_known={9: (99.0, 23.0 + 90.0 + 0.4)}, lap_s=90.0)
    assert r is not None and r["traffic"] is False and r["road_behind_s"] == 0.4


def test_frozen_on_the_in_lap_and_in_the_lane() -> None:
    p = rj.RejoinPredictor()
    me = car(5, 2, leader_ms=3000, player=True)
    cars = [car(0, 1), me, car(2, 3, leader_ms=10000)]
    resolved = rj.resolve_leader_gaps(cars, 100.0)
    first = p.update(me, cars, 100.0, resolved=resolved, loss=LOSS, game_position=3)
    assert first is not None and first["position"] == 3 and not first["frozen"]
    in_lap = with_(me, driver_status="in_lap", gap_leader_ms=None)
    cars2 = [car(0, 1), in_lap, car(2, 3, leader_ms=10000)]
    r = p.update(in_lap, cars2, 102.0, resolved=rj.resolve_leader_gaps(cars2, 102.0), loss=LOSS, game_position=0)
    assert r == {**first, "frozen": True}
    lane = with_(in_lap, pit_status=1)
    later = p.update(lane, cars2, 100.0 + rj.FROZEN_MAX_S + 1, resolved={}, loss=LOSS, game_position=0)
    assert later is None or later.get("frozen") is False  # too old: never handed out as current
    p.rewind(50.0)
    assert p._last is None


def test_game_only_without_a_measured_loss() -> None:
    cars = [car(0, 1), car(5, 2, leader_ms=3000, player=True)]
    r = _predict(cars, loss=None)
    assert r is not None and r["basis"] == "game_only" and r["position"] is None and r["game_position"] == 8
    assert _predict(cars, loss=None, game_position=0) is None


def test_pit_tracker_entry_gap_falls_back_to_the_last_known_value() -> None:
    """Real F1 25 zeroes the gap 1-2 s before the car turns in: the tick before the entry has none."""
    pt = PitTracker()
    pt.update(timing(100.0, [car(0, 1), car(3, 2, leader_ms=4200)]), None)
    pt.update(
        timing(100.5, [car(0, 1), with_(car(3, 2), gap_leader_ms=None, gap_ahead_ms=None, driver_status="in_lap")]),
        None,
    )
    pt.update(timing(101.0, [car(0, 1), with_(car(3, 2), gap_leader_ms=None, gap_ahead_ms=None, pit_status=1)]), None)
    v = pt.in_lane(3)
    assert v is not None and v.entry_leader_ms == 4200 and pt.in_lane_entries() == {3: 4.2}
    pt2 = PitTracker()
    pt2.update(timing(100.0, [car(0, 1), car(3, 2, leader_ms=4200)]), None)
    pt2.update(timing(120.0, [car(0, 1), with_(car(3, 2), gap_leader_ms=None, gap_ahead_ms=None)]), None)
    pt2.update(timing(120.5, [car(0, 1), with_(car(3, 2), gap_leader_ms=None, gap_ahead_ms=None, pit_status=1)]), None)
    assert pt2.in_lane(3) is not None and pt2.in_lane(3).entry_leader_ms is None  # 20 s old: unknown  # type: ignore[union-attr]
    pt.rewind(50.0)
    assert pt.last_known_leader == {}


def test_the_cuts_wrapper_keeps_the_first_shape() -> None:
    me = car(1, 3, leader_ms=4000, player=True)
    cars = [car(0, 1), car(5, 2, leader_ms=2000), me, car(2, 4, leader_ms=10000), car(3, 5, leader_ms=21500)]
    r = cuts_rejoin(me, cars, 18.0, 6)
    assert r == {"position": 5, "gap_ahead_s": 0.5, "gap_behind_s": None, "traffic": True, "game_position": 6}


def test_the_engine_uses_the_new_estimate() -> None:
    e = StrategyEngine("s")
    e.feed(session())
    me = car(1, 2, leader_ms=3000, player=True)
    e.feed(timing(100.0, [car(0, 1), me, car(2, 3, leader_ms=9000)]))
    rjv = e.view()["pit"]["rejoin"]
    assert rjv is None  # no measured loss and no game value (0): nothing to say
    e.feed(session(pit_rejoin_position=4))
    e.feed(timing(100.5, [car(0, 1), me, car(2, 3, leader_ms=9000)]))
    rjv = e.view()["pit"]["rejoin"]
    assert rjv is not None and rjv["basis"] == "game_only" and rjv["game_position"] == 4


def test_a_pit_exit_forgets_the_gap_from_before_the_stop() -> None:
    """Real Imola: the leader stopped (its 0 s gap remembered in the lane), came out P2 with its gaps zeroed on the
    out-lap: the old 0 s must not be its "last known" gap there."""
    pt = PitTracker()
    pt.update(timing(100.0, [car(1, 1, pit=1), car(0, 2, leader_ms=None)]), None)  # P1 in the lane: 0 by position
    assert pt.last_known_leader[1] == (100.0, 0.0)
    pt.update(timing(104.0, [car(0, 1), with_(car(1, 2), gap_leader_ms=None, gap_ahead_ms=None)]), None)
    assert pt.resolved[1] == (None, None) and 1 not in pt.last_known_leader
