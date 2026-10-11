"""Handling balance: phases, the at-limit filter, class thresholds, slides (tail-out body slip, counter-steer),
recurring classes, the best-lap verdict, speed classes and symptom grouping."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest

from pitwall.analysis.laps import LapTrace
from pitwall.technique.balance import (
    CornerPhaseInput,
    LapPhase,
    PhaseBalance,
    build_symptoms,
    lap_balance,
    speed_class,
    summarise,
)
from pitwall.technique.samples import native

HZ = 60
APEX = 500.0
V_KPH = 100.0  # 27.8 m/s: mid-corner = apex +/- 13.9 m
Arr = Callable[[np.ndarray], np.ndarray]


def _lap(
    diff_deg: Arr,
    *,
    glat: Arr | None = None,
    beta_deg: Arr | None = None,
    yaw: Arr | None = None,
    steer: Arr | None = None,
    brake: Arr | None = None,
    slip: bool = True,
) -> LapTrace:
    v = V_KPH / 3.6
    t = np.arange(0, 40, 1 / HZ)
    d = v * t
    rear = np.full(len(t), np.radians(2.0))
    ch = {
        "session_time_s": t,
        "distance_m": d,
        "speed_kph": np.full(len(t), V_KPH),
        "g_lat": glat(d) if glat else np.where(np.abs(d - APEX) < 120, 2.0, 0.1),
        "steering": steer(d) if steer else np.where(np.abs(d - APEX) < 120, 0.3, 0.0),
        "brake": brake(d) if brake else np.zeros(len(t)),
        "throttle": np.full(len(t), 0.5),
        "yaw_rate_rps": yaw(d) if yaw else np.where(np.abs(d - APEX) < 120, 0.5, 0.0),
        "body_slip_rad": np.radians(beta_deg(d)) if beta_deg else np.zeros(len(t)),
    }
    if slip:
        ch["slip_angle_rear_abs_rad"] = rear
        ch["slip_angle_front_abs_rad"] = rear + np.radians(diff_deg(d))
    return LapTrace(lap_number=1, channels=ch, lap_time_ms=40000)


def _bal(lap: LapTrace) -> dict[str, PhaseBalance | None]:
    out = lap_balance(native(lap), APEX, APEX - 400, APEX + 400)
    assert out is not None
    return dict(out)


def const(x: float) -> Arr:
    return lambda d: np.full(len(d), x)


def test_classes_follow_the_thresholds() -> None:
    for diff, cls in ((1.0, "neutral"), (2.9, "neutral"), (3.0, "understeer"), (-1.0, "oversteer"), (-0.5, "neutral")):
        b = _bal(_lap(const(diff)))
        assert b["mid"] is not None and b["mid"].cls == cls, diff
        assert b["mid"].slip_diff_deg == pytest.approx(diff)


def test_phases_split_at_the_slowest_point() -> None:
    def by_phase(d: np.ndarray) -> np.ndarray:
        return np.where(d < APEX - 13.9, 4.0, np.where(d <= APEX + 13.9, 1.0, -2.0))

    b = _bal(_lap(by_phase))
    assert b["entry"] is not None and b["entry"].cls == "understeer"
    assert b["mid"] is not None and b["mid"].cls == "neutral"
    assert b["exit"] is not None and b["exit"].cls == "oversteer"


def test_only_at_limit_samples_count() -> None:
    # the understeer reading is only where the car is not cornering hard (lateral g low): ignored
    def glat(d: np.ndarray) -> np.ndarray:
        return np.where(np.abs(d - APEX) <= 5, 0.2, 2.0)

    def diff(d: np.ndarray) -> np.ndarray:
        return np.where(np.abs(d - APEX) <= 5, 8.0, 1.0)

    b = _bal(_lap(diff, glat=glat))
    assert b["mid"] is not None and b["mid"].cls == "neutral"


def test_too_few_samples_is_unknown_and_no_slip_data_is_none() -> None:
    def glat(d: np.ndarray) -> np.ndarray:  # nothing at the limit in mid-corner
        return np.where(np.abs(d - APEX) <= 14, 0.1, 2.0)

    b = _bal(_lap(const(1.0), glat=glat))
    assert b["mid"] is not None and b["mid"].cls is None and b["mid"].samples == 0
    assert lap_balance(native(_lap(const(1.0), slip=False)), APEX, 0, 1000) is None


def test_a_tail_out_slide_is_oversteer_but_slow_corner_body_slip_is_not() -> None:
    def burst(sign: float) -> Arr:
        return lambda d: np.where((d > APEX + 20) & (d < APEX + 30), sign * 6.0, 0.0)

    tail_out = _bal(_lap(const(1.0), beta_deg=burst(+1)))  # same sign as the rotation (yaw +0.5)
    assert tail_out["exit"] is not None and tail_out["exit"].slide and tail_out["exit"].cls == "oversteer"
    assert tail_out["exit"].slide_deg == pytest.approx(6.0)
    kinematic = _bal(_lap(const(1.0), beta_deg=burst(-1)))  # opposite sign: the slow-turn body slip
    assert kinematic["exit"] is not None and not kinematic["exit"].slide and kinematic["exit"].cls == "neutral"
    assert kinematic["exit"].body_slip_max_deg == pytest.approx(6.0)
    brief = _bal(_lap(const(1.0), beta_deg=lambda d: np.where((d > APEX + 20) & (d < APEX + 21.5), 6.0, 0.0)))
    assert brief["exit"] is not None and not brief["exit"].slide  # under 0.1 s


def test_counter_steer_is_a_slide() -> None:
    def steer(d: np.ndarray) -> np.ndarray:
        base = np.where(np.abs(d - APEX) < 120, 0.3, 0.0)
        return np.where((d > APEX + 20) & (d < APEX + 30), -0.2, base)  # 0.36 s against the rotation

    b = _bal(_lap(const(1.0), steer=steer))
    assert b["exit"] is not None and b["exit"].slide and b["exit"].cls == "oversteer"


def _rows(classes: list[str | None], best: int, laps_ms: list[int] | None = None) -> list[LapPhase]:
    out = []
    for i, cls in enumerate(classes):
        diff = {"understeer": 5.0, "neutral": 1.0, "oversteer": -2.0, None: None}[cls]
        pb = PhaseBalance(cls, diff, 0.5, False, 20)  # type: ignore[arg-type]
        ms = (laps_ms or [90000 + 100 * k for k in range(len(classes))])[i]
        out.append(
            LapPhase(lap_id=i + 1, lap_number=i + 1, lap_time_ms=ms if i + 1 != best else 80000, clean=True, pb=pb)
        )
    return out


def test_recurring_needs_two_laps_and_half_the_laps() -> None:
    assert summarise(_rows(["understeer", "understeer", "neutral"], best=1)).recurring == "understeer"
    assert summarise(_rows(["understeer", "neutral", "neutral", "neutral", "neutral"], best=1)).recurring is None
    assert summarise(_rows(["understeer", "understeer", "neutral", "neutral", "neutral"], best=1)).recurring is None


def test_the_best_lap_decides_car_or_driving() -> None:
    car = summarise(_rows(["understeer", "understeer", "understeer"], best=3))
    assert car.verdict == "car" and car.best_lap == "understeer"
    driving = summarise(_rows(["understeer", "understeer", "neutral"], best=3))
    assert driving.recurring == "understeer" and driving.best_lap == "neutral" and driving.verdict == "driving"
    assert driving.best_lap_number == 3


def test_speed_classes() -> None:
    assert [speed_class(x) for x in (80, 119.9, 120, 199, 200, None)] == [
        "slow",
        "slow",
        "medium",
        "medium",
        "fast",
        None,
    ]


def test_symptoms_group_by_phase_class_and_verdict() -> None:
    def item(corner: str, speed: str, classes: list[str | None], best: int) -> CornerPhaseInput:
        rows = _rows(classes, best)
        return CornerPhaseInput(corner, corner, speed, "mid", summarise(rows), rows)  # type: ignore[arg-type]

    syms = build_symptoms(
        [
            item("T4", "medium", ["understeer"] * 3, best=2),
            item("T11", "slow", ["understeer"] * 3, best=2),
            item("T1", "slow", ["understeer", "understeer", "neutral"], best=3),
            item("T9", "slow", ["neutral"] * 3, best=1),
        ]
    )
    assert [(s.id, s.corners) for s in syms] == [
        ("mid-understeer-car", ["T4", "T11"]),
        ("mid-understeer-driving", ["T1"]),
    ]
    car, driving = syms
    assert car.speed_class == "mixed" and car.laps == 3 and car.laps_total == 3
    assert "including your best lap" in car.text and "heuristic threshold" in car.text
    assert "not on your best lap (lap 3)" in driving.text and "how the corner was driven" in driving.text
    assert driving.speed_class == "slow"
