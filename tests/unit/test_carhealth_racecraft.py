"""Attack / defend (``carhealth.racecraft``): grid clocks (interpolation inside a lap and over the line, segment sums
equal to the lap time, any corner model derived from them), usable laps, the three verdicts, neighbours changing, a new
model, the held corner, the close flag, and privacy."""

from __future__ import annotations

import ast
import json
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from pitwall.carhealth.engine import CarHealthEngine
from pitwall.carhealth.racecraft import (
    REASON_MY_LAPS,
    REASON_NOT_F1,
    REASON_NOT_RACE,
    REASON_THEIR_LAPS,
    GridClock,
    Racecraft,
    Segments,
    verdict,
)
from pitwall.model.telemetry import Game, RaceTiming, SessionType
from tests.unit.carhealth_helpers import LENGTH, field_sample, frame, info, model
from tests.unit.strategy_helpers import car

STARTS = [0.0, 1000.0, 2500.0]
SEG = Segments(("T1", "T2", "T3"), ("Turn 1", "Turn 2", "Turn 3"), tuple(STARTS), LENGTH)


def lap_samples(lap: int, t0: float, segs: Sequence[float], hz: float = 10.0) -> Iterator[tuple[float, int, float]]:
    """(t, lap, d) of one lap with the given segment times (constant speed in each), sampled at ``hz`` from ``t0``
    (the line) up to, not including, the next line."""
    bounds = [*STARTS, LENGTH]
    total = sum(segs)
    i = 0
    while i / hz < total - 1e-9:
        dt = i / hz
        acc = 0.0
        d = 0.0
        for k, s in enumerate(segs):
            if dt < acc + s:
                d = bounds[k] + (dt - acc) / s * (bounds[k + 1] - bounds[k])
                break
            acc += s
        yield t0 + dt, lap, d
        i += 1


def feed_laps(clock: GridClock, laps: Sequence[Sequence[float]], lap0: int = 2, t0: float = 0.0, **kw: bool) -> float:
    t = t0
    for k, segs in enumerate(laps):
        for tt, lap, d in lap_samples(lap0 + k, t, segs):
            clock.add(lap, d, tt, **kw)
        t += sum(segs)
    clock.add(lap0 + len(laps), 0.0, t, **kw)  # the next line closes the last lap
    return t


def test_interpolated_crossings_give_the_true_segment_times() -> None:
    c = GridClock(LENGTH)
    feed_laps(c, [(20.0, 30.0, 25.0), (21.0, 29.5, 24.8), (20.5, 30.2, 25.1)])
    # the first lap was not seen from its line: two complete laps
    got = [c.segments(lap, SEG) for lap in c.laps]
    assert len(got) == 2
    for segs, truth in zip(got, [(21.0, 29.5, 24.8), (20.5, 30.2, 25.1)], strict=True):
        assert segs == pytest.approx(truth, abs=1e-3)
        assert segs is not None and sum(segs) == pytest.approx(sum(truth), abs=1e-3)  # the segments partition the lap


def test_any_corner_model_is_derived_from_the_same_laps() -> None:
    c = GridClock(LENGTH)
    feed_laps(c, [(20.0, 30.0, 25.0)] * 3)
    other = Segments(("A", "B"), ("A", "B"), (0.0, 1750.0), LENGTH)  # a boundary between grid points, mid-segment
    segs = c.segments(c.laps[-1], other)
    assert segs == pytest.approx((20.0 + 15.0, 15.0 + 25.0), abs=1e-3)  # 1750 m is half way through the 30 s segment


def test_usable_laps_exclude_pit_safety_car_invalid_and_lap_one() -> None:
    for kw in ({"pit": True}, {"sc": True}, {"invalid": True}):
        c = GridClock(LENGTH)
        feed_laps(c, [(20.0, 30.0, 25.0)] * 3, **kw)
        assert c.laps and c.usable(SEG) == [], kw
    c = GridClock(LENGTH)
    feed_laps(c, [(20.0, 30.0, 25.0)] * 3, lap0=0)  # laps 0, 1, 2: lap 1 is race lap 1
    assert [lap.lap for lap in c.laps] == [1, 2] and len(c.usable(SEG)) == 1


def test_a_clock_going_back_drops_the_lap() -> None:
    c = GridClock(LENGTH)
    t = feed_laps(c, [(20.0, 30.0, 25.0)] * 2)
    c.add(4, 500.0, t + 5.0)
    c.add(4, 400.0, t + 3.0)  # flashback
    assert c._open is None


def test_a_reset_to_the_track_leaves_that_lap_untimed() -> None:
    c = GridClock(LENGTH)
    t = feed_laps(c, [(20.0, 30.0, 25.0)] * 2)
    n = len(c.laps)
    for tt, lap, d in list(lap_samples(4, t, (20.0, 30.0, 25.0)))[1:]:  # the line sample was the last add
        c.add(lap, d - 200.0 if 30.0 <= tt - t < 30.2 else d, tt)  # put back 200 m mid-lap (a reset)
    c.add(5, 0.0, t + 75.0)
    assert len(c.laps) == n  # lap 4 was not timed ...
    for tt, lap, d in list(lap_samples(5, t + 75.0, (20.0, 30.0, 25.0)))[1:]:
        c.add(lap, d, tt)
    c.add(6, 0.0, t + 150.0)
    assert len(c.laps) == n + 1 and c.laps[-1].lap == 5  # ... the next one is


@pytest.mark.parametrize(
    ("deltas", "side", "expected"),
    [
        ([-0.42, -0.18, 0.05], "ahead", ("clear", 0, 1)),
        ([-0.42, -0.40, 0.05], "ahead", ("spread", 0, 1)),
        ([-0.05, 0.10, 0.30], "ahead", ("none", 0, 1)),
        ([0.05, 0.25, 0.10], "behind", ("clear", 1, 2)),
        ([0.12, 0.14, -0.3], "behind", ("spread", 1, 0)),
        ([-0.2, 0.02, -0.1], "behind", ("none", 1, 2)),
    ],
)
def test_verdicts(deltas: list[float], side: str, expected: tuple[str, int, int]) -> None:
    v, k1, k2, _ = verdict(deltas, side)
    assert (v, k1, k2) == expected


def _timing(t: float, order: list[int], player: int = 19, gaps: dict[int, int | None] | None = None) -> RaceTiming:
    gaps = gaps or {}
    cars = tuple(
        car(idx, pos, player=idx == player, gap_ms=gaps.get(idx, 1000)) for pos, idx in enumerate(order, start=1)
    )
    return RaceTiming(game=Game.F1_25, t_recv_ns=0, session_time_s=t, frame_id=0, player_index=player, cars=cars)


def _feed_player(rc: Racecraft, laps: Sequence[Sequence[float]], lap0: int = 2) -> None:
    t = 0.0
    for k, segs in enumerate(laps):
        for tt, lap, d in lap_samples(lap0 + k, t, segs):
            rc.on_player(lap, d, tt, pit=False, sc=False, invalid=False)
        t += sum(segs)
    rc.on_player(lap0 + len(laps), 0.0, t, pit=False, sc=False, invalid=False)


def _feed_car(rc: Racecraft, idx: int, laps: Sequence[Sequence[float]], lap0: int = 2) -> None:
    t = 0.0
    for k, segs in enumerate(laps):
        for tt, lap, d in lap_samples(lap0 + k, t, segs):
            rc.on_field(idx, lap, d, tt, pit=False, sc=False, invalid=False)
        t += sum(segs)
    rc.on_field(idx, lap0 + len(laps), 0.0, t, pit=False, sc=False, invalid=False)


def _race(rc: Racecraft, me: list[tuple[float, ...]], others: dict[int, list[tuple[float, ...]]]) -> None:
    _feed_player(rc, me)
    for idx, laps in others.items():
        _feed_car(rc, idx, laps)


def test_attack_and_defend_against_the_cars_either_side() -> None:
    rc = Racecraft()
    rc.set_segments(SEG, LENGTH)
    me = [(20.0, 30.0, 25.0)] * 4
    ahead = [(20.5, 30.05, 25.0)] * 4  # I'm 0.5 s quicker in T1, about level elsewhere: a clear attack corner
    behind = [(20.0, 29.6, 25.3)] * 4  # it is 0.4 s quicker in T2: a clear defend corner
    _race(rc, me, {7: ahead, 3: behind})
    rc.timing = _timing(100.0, [1, 7, 19, 3])
    out = rc.compute()
    a, b = out["ahead"], out["behind"]
    assert a["car_index"] == 7 and a["position"] == 2 and a["verdict"] == "clear" and a["laps_compared"] == [3, 3]
    assert a["corner"] == {"name": "T1", "text": "Turn 1", "delta_s": -0.5}
    assert a["lap_delta_s"] == pytest.approx(-0.55, abs=0.01)
    assert b["car_index"] == 3 and b["verdict"] == "clear" and b["corner"]["name"] == "T2"
    assert b["corner"]["delta_s"] == pytest.approx(0.4, abs=0.01)
    # an overtake: the neighbours change, the answer follows at once
    rc.timing = _timing(101.0, [1, 19, 7, 3])
    out = rc.compute()
    assert out["ahead"]["car_index"] == 1 and out["ahead"]["reason"] == REASON_THEIR_LAPS
    assert out["behind"]["car_index"] == 7 and out["behind"]["verdict"] == "none"
    rc.timing = _timing(102.0, [19, 1, 7, 3])
    assert rc.compute()["ahead"]["reason"] == "leading: there's no car ahead"


def test_the_reason_says_whose_laps_are_missing() -> None:
    rc = Racecraft()
    rc.set_segments(SEG, LENGTH)
    _race(rc, [(20.0, 30.0, 25.0)] * 2, {7: [(20.5, 30.0, 25.0)] * 4})  # the first lap is not seen from its line
    rc.timing = _timing(100.0, [7, 19])
    side = rc.compute()["ahead"]
    assert side["reason"] == REASON_MY_LAPS and side["laps_compared"] == [1, 3]


def test_spread_when_no_corner_stands_out() -> None:
    rc = Racecraft()
    rc.set_segments(SEG, LENGTH)
    _race(rc, [(20.0, 30.0, 25.0)] * 4, {7: [(20.2, 30.21, 25.2)] * 4})
    rc.timing = _timing(100.0, [7, 19])
    assert rc.compute()["ahead"]["verdict"] == "spread"


def test_a_new_model_rederives_the_kept_laps() -> None:
    rc = Racecraft()
    rc.set_segments(SEG, LENGTH)
    _race(rc, [(20.0, 30.0, 25.0)] * 3, {7: [(20.5, 30.0, 25.0)] * 3})
    rc.timing = _timing(100.0, [7, 19])
    assert rc.compute()["ahead"]["corner"]["name"] == "T1"
    rc.set_segments(Segments(SEG.names, ("Turn 1", "Copse", "Turn 3"), SEG.starts, LENGTH), LENGTH)
    assert rc.player is not None and rc.player.laps and rc.cars  # only the names changed: the clocks stay
    rc.set_segments(Segments(("A", "B"), ("A", "B"), (0.0, 2000.0), LENGTH), LENGTH)
    assert rc.player.laps and rc.cars  # a rebuilt model: the clocks still stay ...
    side = rc.compute()["ahead"]
    assert (
        side["verdict"] == "clear" and side["corner"]["name"] == "A" and side["laps_compared"] == [2, 2]
    )  # ... at once


def test_laps_before_the_first_model_count() -> None:
    rc = Racecraft()
    rc.set_length(LENGTH)  # the race starts before any corner is learned
    _race(rc, [(20.0, 30.0, 25.0)] * 3, {7: [(20.5, 30.0, 25.0)] * 3})
    rc.timing = _timing(100.0, [7, 19])
    assert rc.compute()["reason"] == "corners not learned yet"
    rc.set_segments(SEG, LENGTH)
    assert rc.compute()["ahead"]["verdict"] == "clear"


def test_a_named_corner_is_held_through_one_contrary_evaluation() -> None:
    rc = Racecraft()
    rc.set_segments(SEG, LENGTH)
    _feed_player(rc, [(20.0, 30.0, 25.0)] * 8)
    laps = [(20.5, 30.0, 25.0)] * 3 + [(20.0, 30.0, 25.0)] * 3  # clear at T1 on laps 3-4, then level
    t = 0.0
    seen = []
    for k, segs in enumerate(laps):
        for tt, lap, d in list(lap_samples(2 + k, t, segs))[1 if k else 0 :]:  # the line sample went last time
            rc.on_field(7, lap, d, tt, pit=False, sc=False, invalid=False)
        t += sum(segs)
        rc.on_field(7, 3 + k, 0.0, t, pit=False, sc=False, invalid=False)  # the line: a new evaluation
        rc.timing = _timing(t, [7, 19])
        a = rc.compute()["ahead"]
        seen.append((a["verdict"], (a["corner"] or {}).get("name")))
    # laps 3-4 (both 0.5 s slower at T1): clear; with lap 5 (two slow, one level) still clear; laps 4-6 (one slow, two
    # level): the median is level - held once; laps 5-7: dropped out a second time in a row - gone
    assert seen[2:] == [("clear", "T1"), ("clear", "T1"), ("clear", "T1"), ("none", None)]


def test_close_comes_from_the_gap_to_that_car() -> None:
    rc = Racecraft()
    rc.set_segments(SEG, LENGTH)
    _race(rc, [(20.0, 30.0, 25.0)] * 4, {7: [(20.5, 30.0, 25.0)] * 4, 3: [(20.0, 29.6, 25.0)] * 4})
    rc.timing = _timing(100.0, [7, 19, 3], gaps={19: 900, 3: 2500})  # the player 0.9 s behind 7; 3 is 2.5 s back
    out = rc.compute()
    assert out["ahead"]["close"] is True and out["behind"]["close"] is False
    rc.timing = _timing(101.0, [7, 19, 3], gaps={19: None, 3: 1200})
    out = rc.compute()
    assert out["ahead"]["close"] is None and out["behind"]["close"] is True  # unknown stays unknown


def test_segments_from_the_live_model() -> None:
    seg = Segments.from_model(model([0.0, 1000.0, 2500.0]), {"T2": "Turn 3"})
    assert seg is not None and seg.texts == ("T1", "Turn 3", "T3") and seg.starts == (0.0, 1000.0, 2500.0)
    assert Segments.from_model(None) is None
    assert Segments.from_model({"corners": [], "length_m": 4000.0}) is None


def test_engine_feeds_field_samples_only_in_f1_races_and_clears_them_at_the_end() -> None:
    eng = CarHealthEngine("r", track_model=lambda: model(STARTS))
    eng.feed(info())
    assert eng.wants_field
    eng.feed(frame(0.0, d=10.0))
    for lap in range(2, 5):
        for tt, lp, d in lap_samples(lap, (lap - 2) * 75.0, (20.0, 30.0, 25.0)):
            eng.feed(field_sample(7, tt, lp, d))
    assert eng.racecraft.cars[7].laps
    view = eng.racecraft_view()
    assert view["mode"] == "race" and set(view) == {
        "version",
        "session_id",
        "mode",
        "reason",
        "corners_source",
        "ahead",
        "behind",
    }
    eng.end()  # privacy: every per-car buffer goes
    assert eng.racecraft.cars == {} and eng.racecraft.timing is None and not eng.wants_field
    assert eng.racecraft.player is None
    assert eng.racecraft_view()["mode"] == "off" and eng.racecraft_view()["reason"] == "the session ended"
    q = CarHealthEngine("q")
    q.feed(info(session_type=SessionType.QUALIFYING))
    assert not q.wants_field and q.racecraft_view()["reason"] == REASON_NOT_RACE
    g = CarHealthEngine("g")
    g.feed(info(game=Game.GT7))
    assert g.racecraft_view()["reason"] == REASON_NOT_F1


def test_racecraft_and_the_worker_never_touch_storage_or_names() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "pitwall" / "carhealth"
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not any(m.startswith(("pitwall.storage", "sqlite3")) for m in mods), path  # nothing persisted
        if path.name != "worker.py":  # the worker logs its own errors only, never a car
            assert "logging" not in mods, path
    rc = Racecraft()
    rc.set_segments(SEG, LENGTH)
    _race(rc, [(20.0, 30.0, 25.0)] * 3, {7: [(20.5, 30.0, 25.0)] * 3})
    rc.timing = _timing(1.0, [7, 19])
    text = json.dumps(rc.compute())
    assert 'name": "T' in text and "driver" not in text and "participant" not in text
