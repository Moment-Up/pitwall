"""coachref in the cue planner: the braking clamp (another driver's lap is never called later than the driver's own
point), the "no braking points of your own" reason and the practice-drill corner. ``on_frame`` is unchanged (the
existing timing tests in ``test_cues.py`` are the regression check)."""

from __future__ import annotations

import random
from typing import Any

import pytest

from pitwall.coach.cues import (
    FALLBACK_REASONS,
    NO_OWN_POINTS,
    CueEngine,
    CueKind,
    CueLabel,
    CuePlan,
    CueSpec,
    build_cue_plan,
    reference_braking_zones,
)
from tests.unit.test_cues import LENGTH, REF_ID, comparison, flat_trace, obs, reference


def clamped(zones: dict[str, float], clamp: dict[str, float] | None) -> dict[str, Any]:
    comp = comparison(zones)
    if clamp is not None:
        comp["brake_clamp_m"] = clamp
    return comp


def plan(mode: str, comp: dict[str, Any], **kw: Any) -> CuePlan:
    return build_cue_plan(mode, comp, length_m=LENGTH, reference=reference(), trace=flat_trace(), **kw)


def heads_up() -> CuePlan:
    cue = CueSpec("T1", CueKind.MARKER, 600.0, "heavy braking ahead", ("heavy braking ahead",), 0, 2.0)
    return CuePlan(mode="all", cues=(cue,), approaches=(None,), targets=(600.0,), length_m=LENGTH, focus=("T1",))


def test_clamp_takes_the_earlier_point_and_drops_corners_without_one() -> None:
    zones = reference_braking_zones(
        clamped({"T1": 1000.0, "T2": 2000.0, "T3": 2600.0}, {"T1": 950.0, "T2": 2100.0}), LENGTH
    )
    assert [(z.corner, z.brake_m) for z in zones] == [("T1", 950.0), ("T2", 2000.0)]  # T3: no own point
    assert [z.brake_m for z in reference_braking_zones(clamped({"T1": 1000.0}, None), LENGTH)] == [1000.0]
    p = plan("all", clamped({"T1": 1000.0, "T2": 2000.0}, {"T1": 950.0, "T2": 2100.0}))
    assert [(c.corner, c.target_m) for c in p.cues] == [("T1", 950.0), ("T2", 2000.0)]


def test_no_own_points_reason_lets_the_field_stand_in() -> None:
    assert NO_OWN_POINTS in FALLBACK_REASONS
    assert plan("all", clamped({"T1": 1000.0, "T2": 2000.0}, {})).reason == NO_OWN_POINTS
    e = CueEngine("all")
    e.on_reference(reference(), flat_trace())
    e.set_fallback_plan(heads_up())
    e.on_lap_result([], clamped({"T1": 1000.0, "T2": 2000.0}, {}), LENGTH)
    assert [c.text for c in e.plan.cues] == ["heavy braking ahead"]  # early markers, never targets
    assert e.plan.reason == f"AI field heads-ups ({NO_OWN_POINTS})"


@pytest.mark.parametrize("mode", ["all", "markers", "focus"])
def test_property_every_cue_is_at_or_before_the_drivers_own_point(mode: str) -> None:
    rnd = random.Random(20261011)
    for _ in range(200):
        n = rnd.randint(1, 6)
        names = [f"T{i + 1}" for i in range(n)]
        ref = {c: rnd.uniform(100.0, LENGTH - 50.0) for c in names}
        clamp = {c: rnd.uniform(50.0, LENGTH - 50.0) for c in names if rnd.random() < 0.8}
        history = [[obs(c, prio=rnd.uniform(0.05, 0.5)) for c in names]]
        p = plan(mode, clamped(ref, clamp), history=history)
        for cue in p.cues:
            assert cue.corner in clamp
            assert cue.target_m <= clamp[cue.corner] + 1e-9
            assert cue.target_m <= ref[cue.corner] + 1e-9


def test_drill_corner_in_every_mode() -> None:
    comp = comparison({"T1": 1000.0, "T2": 2000.0})
    focus = plan("focus", comp, only_corner="T2")  # no observation history needed
    assert [(c.corner, c.focus, c.reason) for c in focus.cues] == [("T2", True, "drill")] and focus.focus == ("T2",)
    assert [c.corner for c in plan("markers", comp, only_corner="T2").cues] == ["T2"]
    assert [c.corner for c in plan("all", comp, only_corner="T2").cues] == ["T2"]
    assert plan("off", comp, only_corner="T2").cues == ()
    labels = {"T9": CueLabel("T10", "Turn 10", "Turn 10")}
    assert plan("all", comp, only_corner="T9", labels=labels).reason == "drill: no braking call at T10"
    # a drill corner without an own braking point (another driver's lap) gets no call either
    assert plan("all", clamped({"T1": 1000.0, "T2": 2000.0}, {"T1": 990.0}), only_corner="T2").reason == (
        "drill: no braking call at T2"
    )


def test_engine_drill_corner_survives_resets_and_blocks_heads_ups() -> None:
    e = CueEngine("focus")
    e.on_reference(reference(), flat_trace())
    e.on_lap_result([], comparison({"T1": 1000.0, "T2": 2000.0}, ref_lap_id=REF_ID), LENGTH)
    assert e.plan.cues == ()  # focus mode, no corrections
    e.set_drill_corner("T2")
    assert [c.corner for c in e.plan.cues] == ["T2"] and e.snapshot()["drill_corner"] == "T2"
    e.reset_session()
    assert e.drill_corner == "T2" and e.snapshot()["drill_corner"] == "T2"
    e.set_fallback_plan(heads_up())
    assert e.plan.cues == ()  # no own plan yet, but the field never stands in during a drill
    e.set_drill_corner(None)
    assert [c.text for c in e.plan.cues] == ["heavy braking ahead"]
    assert e.snapshot()["drill_corner"] is None
