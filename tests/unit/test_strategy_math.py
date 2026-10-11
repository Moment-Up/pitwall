"""Strategy maths (``analysis.strategy``): stint projection with quantisation bounds, the extended pit window, the
fuel-burn model and lift and coast. The defaults (``core.report``, ``carsetup.experiments``) are covered by
``test_ai.py`` and must not change."""

from __future__ import annotations

import numpy as np
import pytest

from pitwall.analysis.strategy import (
    BurnModel,
    FuelEstimate,
    TyreEstimate,
    fit_burn_model,
    fuel_estimate,
    ideal_stop_lap,
    lift_coast_target,
    pit_window,
    stint_start_lap,
    tyre_estimate,
)
from tests.unit.strategy_helpers import laps_meta

W0 = (0.0, 0.0, 0.0, 0.0)


def _stint(start: int, n: int, rate: tuple[float, ...], compound: str = "medium", age0: int = 0, w0=W0) -> list:
    rows = []
    w = list(w0)
    for k in range(n):
        ws = tuple(w)
        w = [x + r for x, r in zip(w, rate, strict=True)]
        rows.append((start + k, 50.0 - k, 49.0 - k, ws, tuple(float(int(x)) for x in w), compound, age0 + k))
    return rows


def test_stint_breaks_on_compound_age_reset_and_wear_drop() -> None:
    a = laps_meta(_stint(1, 4, (2.0, 2.0, 1.0, 1.0)) + _stint(5, 3, (2.0, 2.0, 1.0, 1.0), compound="hard"))
    assert stint_start_lap(a) == 5
    b = laps_meta(_stint(1, 4, (2.0, 2.0, 1.0, 1.0)) + _stint(5, 3, (2.0, 2.0, 1.0, 1.0), age0=0))
    assert stint_start_lap(b) == 5  # same compound, age went down
    rows = _stint(1, 4, (2.0, 2.0, 1.0, 1.0))
    rows += [(5, 46.0, 45.0, (0.0, 0.0, 0.0, 0.0), (2.0, 2.0, 1.0, 1.0), "medium", 4)]  # wear dropped: new set
    assert stint_start_lap(laps_meta(rows)) == 5
    assert stint_start_lap([]) is None


def test_stint_projection_quantisation_bounds_and_enough_laps() -> None:
    laps = laps_meta(_stint(1, 9, (1.5, 1.4, 1.0, 1.0), w0=(9.0, 9.0, 8.0, 8.0)))
    te = tyre_estimate(laps, 70.0, stint_only=True, exclude_laps=frozenset({1}))
    assert te.enough_laps and te.stint_start_lap == 1 and te.laps_used == 8
    assert te.limiting_wheel == "front-left"
    now = te.wear_now_pct
    assert now is not None
    rate = te.wear_rate_pct_per_lap[0]  # type: ignore[index]
    total = rate * 8
    assert te.rate_low_pct_per_lap == pytest.approx((total - 1) / 8, abs=1e-3)
    assert te.rate_high_pct_per_lap == pytest.approx((total + 1) / 8, abs=1e-3)
    assert te.laps_to_limit == pytest.approx((70 - now[0]) / rate, abs=0.1)
    assert te.laps_to_limit_low == pytest.approx((70 - now[0]) / te.rate_high_pct_per_lap, abs=0.1)  # type: ignore[operator]
    assert te.laps_to_limit_high == pytest.approx((70 - now[0]) / te.rate_low_pct_per_lap, abs=0.1)  # type: ignore[operator]
    short = tyre_estimate(laps[:3], 70.0, stint_only=True, exclude_laps=frozenset({1}))
    assert not short.enough_laps and short.laps_to_limit is None  # two green laps only


def test_stint_projection_ignores_the_previous_stint_and_excluded_laps() -> None:
    old = _stint(1, 5, (4.0, 4.0, 4.0, 4.0))
    new = _stint(6, 5, (1.0, 1.0, 1.0, 1.0), compound="hard")
    laps = laps_meta(old + new, flags={6: ["pit_out"]})
    te = tyre_estimate(laps, 70.0, stint_only=True, exclude_laps=frozenset({9}))
    assert te.stint_start_lap == 6 and te.compound == "hard"
    assert te.laps_used == 3  # laps 7, 8, 10 (6 is the out-lap, 9 excluded)
    assert te.wear_rate_pct_per_lap == pytest.approx([1.0, 1.0, 1.0, 1.0])
    # the default (reports, setup experiments) still fits every green lap of the session
    default = tyre_estimate(laps)
    assert default.laps_used == 9 and default.stint_start_lap is None


def test_a_tyre_change_lap_is_not_a_wear_lap() -> None:
    rows = _stint(1, 4, (2.0, 2.0, 2.0, 2.0))
    rows.append((5, 46.0, 45.0, (8.0, 8.0, 8.0, 8.0), (1.0, 1.0, 1.0, 1.0), "medium", 4))  # changed mid-lap
    te = tyre_estimate(laps_meta(rows), 70.0, stint_only=True)
    assert te.stint_start_lap == 1 and te.laps_used == 4


def _te(laps_to_limit: float | None) -> TyreEstimate:
    return TyreEstimate("medium", 10, [20.0] * 4, [2.0] * 4, laps_to_limit, "front-left", 70.0, 5)


FE = FuelEstimate(1.4, 5, 20.0, 14.3, None, 10.0, 0.5, 0.7)


def test_pit_window_closes_on_the_earlier_of_measured_and_game() -> None:
    pw = pit_window(10, 40, _te(15.5), FE, game_laps_left=12)
    assert pw is not None and pw["stop_needed_for_tyres"]
    assert pw["window_close_lap"] == 22 and pw["close_source"] == "game"
    assert pw["window_open_lap"] == 19 and pw["tier"] == "game"  # no new-set life: close - 3
    pw = pit_window(10, 40, _te(8.0), FE, game_laps_left=12, new_set_life_laps=25)
    assert pw is not None and pw["close_source"] == "measured" and pw["window_close_lap"] == 18
    assert pw["window_open_lap"] == 15 and not pw["two_stops"]  # 40 - 25 = 15: a new set reaches the flag
    assert pit_window(10, 40, _te(None), FE) is None


def test_pit_window_no_stop_and_two_stops() -> None:
    pw = pit_window(30, 40, _te(15.0), FE, game_laps_left=20)
    assert pw is not None and not pw["stop_needed_for_tyres"] and "reason" in pw
    pw = pit_window(10, 60, _te(8.0), FE, new_set_life_laps=20)
    assert pw is not None and pw["two_stops"] and pw["window_open_lap"] == 10 and pw["window_close_lap"] == 18


def test_ideal_lap_closed_form() -> None:
    # d0 0.692 s, g 0.091 s/lap^2, 5 laps after this one: k* = round((0.091*4 - 0.692) / 0.182) = -2 -> clamped to 0
    assert ideal_stop_lap(10, 15, 0.692, 0.091) == 8
    pw = pit_window(10, 15, _te(3.0), FE, new_set_life_laps=20, ideal_lap=ideal_stop_lap(10, 15, 0.692, 0.091))
    assert pw is not None and pw["ideal_lap"] == 10  # k* = 0: box this lap
    # a long way to go and a small gain now: stay out a while
    assert ideal_stop_lap(10, 40, 0.2, 0.1) == 10 + round((0.1 * 29 - 0.2) / 0.2)
    assert ideal_stop_lap(10, 40, 0.2, None) is None and ideal_stop_lap(10, 40, 0.2, 0.0) is None


def test_fuel_estimate_excludes_laps() -> None:
    rows = [(n, 50.0 - n, 48.6 - n, W0, W0, "medium", n) for n in range(1, 6)]
    rows[2] = (3, 47.0, 44.0, W0, W0, "medium", 3)  # a safety-car lap with an odd burn
    fe = fuel_estimate(laps_meta(rows), 10.0, None, 7.5, exclude_laps=frozenset({1, 3}))
    assert fe.laps_used == 3 and fe.per_lap_kg == pytest.approx(1.4)
    assert fe.margin_laps == pytest.approx(10.0 / 1.4 - 7.5, abs=0.01)


def _windows(b0: float, b1: float, n: int, noise: float = 0.0005, seed: int = 1) -> list[tuple[float, float]]:
    rng = np.random.default_rng(seed)
    thr = np.concatenate([np.full(n // 3, 0.05), np.full(n // 3, 1.0), rng.uniform(0.2, 0.9, n - 2 * (n // 3))])
    rate = b0 + b1 * thr + rng.normal(0, noise, len(thr))
    return list(zip(rate.tolist(), thr.tolist(), strict=True))


def test_burn_model_fit_and_gates() -> None:
    m = fit_burn_model(_windows(0.00118, 0.0238, 300))
    assert m is not None and m.b1 == pytest.approx(0.0238, rel=0.03) and m.b0 == pytest.approx(0.00118, abs=3e-4)
    assert m.r2 > 0.9 and m.windows == 300 and m.full_throttle_kg_per_s == pytest.approx(m.b0 + m.b1)
    assert fit_burn_model(_windows(0.00118, 0.0238, 100)) is None  # too few windows
    flat = [(0.02, 1.0)] * 200  # never lifting: the throttle term cannot be fitted
    assert fit_burn_model(flat) is None
    assert fit_burn_model(_windows(0.00118, 0.0238, 300, noise=0.02)) is None  # R^2 too low


def test_lift_and_coast_target() -> None:
    model = BurnModel(b0=0.0012, b1=0.024, r2=0.9, windows=500)
    lnc = lift_coast_target(-0.4, 1.08, 7.0, model)
    assert lnc is not None
    assert lnc.save_kg_per_lap == pytest.approx(0.5 * 1.08 / 7, abs=1e-3)
    assert lnc.seconds_per_lap == pytest.approx(0.5 * 1.08 / 7 / 0.024, abs=0.05) and lnc.feasible
    assert lift_coast_target(0.5, 1.08, 7.0, model) is None  # nothing to save
    assert lift_coast_target(-0.4, 1.08, 7.0, None) is None  # no burn model: unknown
    far = lift_coast_target(-3.0, 1.4, 2.0, model)
    assert far is not None and not far.feasible  # more than 6 s a lap
