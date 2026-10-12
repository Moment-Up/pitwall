"""Tank-level fuel (``carhealth.fuel``, Forza; GT7 switched off): the per-lap median, refuels and rewinds, fuel use
off, low / critical, the GT7 gate and the unit cancelling. Generated values only (Forza is community-documented)."""

from __future__ import annotations

import pytest

from pitwall.carhealth import thresholds as T
from pitwall.carhealth.engine import CarHealthEngine
from pitwall.carhealth.fuel import TankFractionFuel
from pitwall.model.telemetry import Game, SessionType
from tests.unit.carhealth_helpers import frame, info


def _laps(f: TankFractionFuel, start: float, per_lap: float, laps: int, lap0: int = 1, scale: float = 1.0) -> None:
    """Two samples a second over 60 s laps, the level falling evenly."""
    for lap in range(lap0, lap0 + laps):
        for k in range(120):
            level = start - per_lap * ((lap - lap0) + k / 120)
            f.on_level(level * scale, lap)


def test_per_lap_is_the_median_of_usable_laps() -> None:
    f = TankFractionFuel()
    _laps(f, 0.9, 0.04, 2)
    assert f.per_lap() is None and f.status() == "unknown"  # the first lap seen never counts
    _laps(f, 0.82, 0.04, 2, lap0=3)
    f.on_level(0.74, 5)  # the line into lap 5 finishes lap 4
    assert f.per_lap() == pytest.approx(0.04) and f.laps_of_fuel() == pytest.approx(0.74 / 0.04)
    assert f.status() == "ok"


def test_a_refuel_or_a_rewind_starts_over() -> None:
    f = TankFractionFuel()
    _laps(f, 0.5, 0.05, 4)
    f.on_level(0.3, 5)
    assert f.per_lap() is not None
    f.on_level(0.9, 5)  # refuelled inside the lap
    assert f.per_lap() is None
    g = TankFractionFuel()
    _laps(g, 0.5, 0.05, 4)
    g.on_level(0.6, 2)  # back to lap 2: a rewind
    assert g.per_lap() is None


def test_fuel_use_off() -> None:
    f = TankFractionFuel()
    for lap in range(1, 5):
        for _ in range(20):
            f.on_level(1.0, lap)
    assert f.status() == "not_used" and f.view()["reason"] == "fuel use is off in this race"


@pytest.mark.parametrize(("left", "status"), [(0.2, "ok"), (0.11, "low"), (0.045, "critical")])
def test_low_and_critical(left: float, status: str) -> None:
    f = TankFractionFuel()
    _laps(f, left + 0.04 * 3, 0.04, 3)
    f.on_level(left, 4)
    assert f.status() == status
    laps = f.laps_of_fuel()
    assert laps is not None
    assert (laps <= T.FUEL_CRITICAL_LAPS) is (status == "critical")


def test_the_unit_cancels() -> None:
    """A level sent in per cent (0..100) gives the same laps as a fraction: the thresholds scale with the range."""
    a, b = TankFractionFuel(), TankFractionFuel()
    _laps(a, 0.9, 0.04, 4)
    a.on_level(0.74, 5)
    _laps(b, 0.9, 0.04, 4, scale=100.0)
    b.on_level(74.0, 5)
    assert a.laps_of_fuel() == pytest.approx(b.laps_of_fuel())
    assert a.view()["per_lap"] == pytest.approx(b.view()["per_lap"]) and a.view()["fraction"] == b.view()["fraction"]


def test_gt7_is_unverified_with_no_numbers() -> None:
    eng = CarHealthEngine("g")
    for k in range(600):
        lap = 1 + k // 120
        eng.feed(frame(k / 2, lap=lap, game=Game.GT7, inner=None, brakes_c=None, engine_c=None, slip=None))
        eng.feed(info(game=Game.GT7, model=None, session_type=SessionType.RACE, fuel_fraction=0.9 - 0.022 * k / 120))
    fuel = eng.view()["fuel"]
    assert fuel["status"] == "unverified" and fuel["tier"] == "unverified"
    assert fuel["fraction"] is None and fuel["per_lap"] is None and fuel["laps_of_fuel"] is None
    assert "hasn't yet seen a recording" in fuel["reason"]
    assert not T.GT7_FUEL_ENABLED


def test_forza_view_and_ac_not_sent_and_f1_null() -> None:
    eng = CarHealthEngine("fz")
    for k in range(600):
        lap = 1 + k // 120
        eng.feed(frame(k / 2, lap=lap, game=Game.FORZA_MOTORSPORT, inner=None, brakes_c=None, engine_c=None))
        eng.feed(
            info(
                game=Game.FORZA_MOTORSPORT,
                model=None,
                session_type=SessionType.RACE,
                fuel_fraction=0.9 - 0.04 * k / 120,
            )
        )
    fuel = eng.view()["fuel"]
    assert fuel["source"] == "tank_fraction" and fuel["status"] == "ok" and fuel["tier"] == "community"
    assert fuel["laps_used"] >= 2 and fuel["per_lap"] == pytest.approx(0.04, abs=0.001)
    ac = CarHealthEngine("ac")
    ac.feed(info(game=Game.AC, model=None))
    ac.feed(frame(1.0, game=Game.AC, surf=None, inner=None))
    assert ac.view()["fuel"]["status"] == "not_sent"
    f1 = CarHealthEngine("f1")
    f1.feed(info())
    assert f1.view()["fuel"] is None
