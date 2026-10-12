"""Attack / defend (``carhealth.racecraft``): segment clocks (interpolation inside a lap and over the line, sums equal
to the lap time), usable laps, the three verdicts, neighbours changing, a new model, and privacy."""

from __future__ import annotations

import ast
import json
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from pitwall.carhealth.engine import CarHealthEngine
from pitwall.carhealth.racecraft import REASON_NOT_RACE, Racecraft, SegmentClock, Segments, verdict
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


def feed_laps(
    clock: SegmentClock, laps: Sequence[Sequence[float]], lap0: int = 2, t0: float = 0.0, **kw: bool
) -> float:
    t = t0
    for k, segs in enumerate(laps):
        for tt, lap, d in lap_samples(lap0 + k, t, segs):
            clock.add(lap, d, tt, **kw)
        t += sum(segs)
    clock.add(lap0 + len(laps), 0.0, t, **kw)  # the next line closes the last lap
    return t


def test_interpolated_crossings_give_the_true_segment_times() -> None:
    c = SegmentClock(SEG)
    feed_laps(c, [(20.0, 30.0, 25.0), (21.0, 29.5, 24.8), (20.5, 30.2, 25.1)])
    # the first lap was not seen from its line: two complete laps
    got = [lap.segs for lap in c.laps]
    assert len(got) == 2
    for segs, truth in zip(got, [(21.0, 29.5, 24.8), (20.5, 30.2, 25.1)], strict=True):
        assert segs == pytest.approx(truth, abs=1e-3)
        assert sum(segs) == pytest.approx(sum(truth), abs=1e-3)  # the segments partition the lap


def test_usable_laps_exclude_pit_safety_car_invalid_and_lap_one() -> None:
    for kw in ({"pit": True}, {"sc": True}, {"invalid": True}):
        c = SegmentClock(SEG)
        feed_laps(c, [(20.0, 30.0, 25.0)] * 3, **kw)
        assert c.laps and c.usable() == [], kw
    c = SegmentClock(SEG)
    feed_laps(c, [(20.0, 30.0, 25.0)] * 3, lap0=0)  # laps 0, 1, 2: lap 1 is race lap 1
    assert [lap.lap for lap in c.laps] == [1, 2] and [lap.lap for lap in c.laps if lap.usable] == [2]


def test_a_clock_going_back_drops_the_lap() -> None:
    c = SegmentClock(SEG)
    t = feed_laps(c, [(20.0, 30.0, 25.0)] * 2)
    c.add(4, 500.0, t + 5.0)
    c.add(4, 400.0, t + 3.0)  # flashback
    assert c._open is None


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


def _timing(t: float, order: list[int], player: int = 19) -> RaceTiming:
    cars = tuple(car(idx, pos, player=idx == player) for pos, idx in enumerate(order, start=1))
    return RaceTiming(game=Game.F1_25, t_recv_ns=0, session_time_s=t, frame_id=0, player_index=player, cars=cars)


def _race(rc: Racecraft, me: list[tuple[float, ...]], others: dict[int, list[tuple[float, ...]]]) -> None:
    assert rc.player is not None
    feed_laps(rc.player, me)
    for idx, laps in others.items():
        t = 0.0
        for k, segs in enumerate(laps):
            for tt, lap, d in lap_samples(2 + k, t, segs):
                rc.on_field(idx, lap, d, tt, pit=False, sc=False, invalid=False)
            t += sum(segs)
        rc.on_field(idx, 2 + len(laps), 0.0, t, pit=False, sc=False, invalid=False)


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
    assert out["ahead"]["car_index"] == 1 and out["ahead"]["reason"] == "needs two clean laps of you and that car"
    assert out["behind"]["car_index"] == 7 and out["behind"]["verdict"] == "none"
    rc.timing = _timing(102.0, [19, 1, 7, 3])
    assert rc.compute()["ahead"]["reason"] == "leading: there's no car ahead"


def test_spread_when_no_corner_stands_out() -> None:
    rc = Racecraft()
    rc.set_segments(SEG, LENGTH)
    _race(rc, [(20.0, 30.0, 25.0)] * 4, {7: [(20.2, 30.21, 25.2)] * 4})
    rc.timing = _timing(100.0, [7, 19])
    assert rc.compute()["ahead"]["verdict"] == "spread"


def test_a_new_model_starts_the_clocks_again() -> None:
    rc = Racecraft()
    rc.set_segments(SEG, LENGTH)
    _race(rc, [(20.0, 30.0, 25.0)] * 3, {7: [(20.5, 30.0, 25.0)] * 3})
    assert rc.player is not None and rc.player.laps and rc.cars
    rc.set_segments(Segments(SEG.names, ("Turn 1", "Copse", "Turn 3"), SEG.starts, LENGTH), LENGTH)
    assert rc.player.laps and rc.cars  # only the names changed: the clocks stay
    rc.set_segments(Segments(("T1", "T2"), ("T1", "T2"), (0.0, 2000.0), LENGTH), LENGTH)
    assert not rc.player.laps and not rc.cars


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
    assert eng.racecraft_view()["mode"] == "off"
    q = CarHealthEngine("q")
    q.feed(info(session_type=SessionType.QUALIFYING))
    assert not q.wants_field and q.racecraft_view()["reason"] == REASON_NOT_RACE


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
