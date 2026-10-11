"""Track reconstruction, corner segmentation, reference compatibility, time deltas and coaching rules."""

from __future__ import annotations

import pytest

from pitwall.analysis.coaching import observations_for_comparison, top_focus
from pitwall.analysis.compare import (
    Compatibility,
    CornerDelta,
    CornerMetrics,
    LapComparison,
    analyse_lap,
    check_compatibility,
    compare,
)
from pitwall.analysis.distance import to_distance_domain
from pitwall.analysis.track import TrackModel, build_track_model
from tests.conftest import DecodedSession


def _model(s: DecodedSession) -> TrackModel:
    clean = [lap for lap in s.laps if lap.clean][:2]
    L = s.info.track_length_m
    assert L
    return build_track_model("f1_25", "test", "t", L, [to_distance_domain(lap, L) for lap in clean])


# ---------------------------------------------------------------- track model
def test_corners_detected_at_speed_minima(clean_session: DecodedSession) -> None:
    m = _model(clean_session)
    truth = clean_session.truth.profiles[1]
    # design: 8 arcs, of which T2 (flat-out sweeper) and T6 (fast kink) are not speed minima,
    # and the T4/T5 chicane is one braking complex -> 5 speed-minimum corners
    assert [c.name for c in m.corners] == ["T1", "T2", "T3", "T4", "T5"]
    for c in m.corners:
        i = int(c.apex_m)
        assert truth.v[i] * 3.6 == pytest.approx(c.ref_min_speed_kph, abs=2)
        assert c.seg_start_m < c.entry_m <= c.apex_m <= c.exit_m <= c.seg_end_m
    assert m.corners[0].seg_start_m == 0 and m.corners[-1].seg_end_m == pytest.approx(m.length_m)
    assert m.corners[0].direction == "right"


def test_track_model_serialises(clean_session: DecodedSession) -> None:
    m = _model(clean_session)
    back = TrackModel.from_dict(m.to_dict())
    assert back.corners == m.corners and len(back.centreline) == len(m.centreline) > 100


def test_corner_lookup_by_distance(clean_session: DecodedSession) -> None:
    m = _model(clean_session)
    c = m.corner_at(m.corners[2].apex_m)
    assert c is not None and c.name == "T3"
    assert m.corner("t3") is c


# ---------------------------------------------------------------- comparison
def test_identical_laps_have_zero_delta(clean_session: DecodedSession) -> None:
    m = _model(clean_session)
    a = analyse_lap(clean_session.laps[0], m)
    b = analyse_lap(clean_session.laps[1], m)
    comp = compare(a, b, Compatibility(ok=True))
    assert comp.total_delta_s == 0
    assert max(abs(x) for x in comp.delta_s) < 0.01
    for cd in comp.corners:
        assert abs(cd.time_delta_s or 0) < 0.01
        assert abs(cd.brake_point_delta_m or 0) < 1.5
    assert observations_for_comparison(comp) == []


def test_injected_errors_recovered_against_ground_truth(demo_session: DecodedSession) -> None:
    """Every injected mistake is found, at the right corner, with the magnitude the generator produced."""
    m = _model(demo_session)
    ref = analyse_lap(demo_session.laps[0], m)
    laps = {lap.lap_number: lap for lap in demo_session.laps}
    truth = demo_session.truth.profiles

    def true_brake_onset(lap: int, near: float) -> float:
        p = truth[lap]
        on = p.brake >= 0.10
        onsets = p.s[1:][on[1:] & ~on[:-1]]
        return float(min(onsets, key=lambda x: abs(x - near)))

    # lap 3: brakes early into design-T3 (pitwall T2)
    comp3 = compare(ref, analyse_lap(laps[3], m), Compatibility(ok=True))
    t2 = next(c for c in comp3.corners if c.corner == "T2")
    expected = true_brake_onset(3, t2.ref.brake_start_m or 0) - true_brake_onset(1, t2.ref.brake_start_m or 0)
    assert t2.brake_point_delta_m == pytest.approx(expected, abs=1.5)
    assert expected < -10
    obs = observations_for_comparison(comp3)
    assert obs and obs[0].kind == "brake_early" and obs[0].corner == "T2"
    assert obs[0].impact_s == pytest.approx(0.341, abs=0.02)  # == lap-time difference in the truth
    # lap 4: low apex speed at design-T7 (pitwall T4)
    comp4 = compare(ref, analyse_lap(laps[4], m), Compatibility(ok=True))
    o4 = observations_for_comparison(comp4)
    assert [(o.kind, o.corner) for o in o4] == [("low_min_speed", "T4")]
    assert o4[0].value == pytest.approx(-8.0, abs=0.6)
    # lap 5: late throttle at design-T8 (pitwall T5)
    o5 = observations_for_comparison(compare(ref, analyse_lap(laps[5], m), Compatibility(ok=True)))
    assert o5[0].kind == "late_throttle" and o5[0].corner == "T5" and o5[0].value == pytest.approx(40, abs=3)
    # corner time deltas partition the lap: they sum to the total lap delta
    assert sum(c.time_delta_s or 0 for c in comp3.corners) == pytest.approx(comp3.total_delta_s, abs=0.01)


def test_time_delta_matches_lap_time_difference(demo_session: DecodedSession) -> None:
    m = _model(demo_session)
    ref = analyse_lap(demo_session.laps[0], m)
    for lap in demo_session.laps[1:]:
        comp = compare(ref, analyse_lap(lap, m), Compatibility(ok=True))
        assert comp.delta_s[-1] == pytest.approx(comp.total_delta_s, abs=0.02)


# ---------------------------------------------------------------- compatibility
def test_compatibility_rules() -> None:
    base = {"game": "f1_25", "track_id": "f1:10", "car_id": "f1:team:8", "weather": "clear", "tyre_compound": "soft"}
    assert check_compatibility(base, dict(base), True).ok
    assert not check_compatibility(base, {**base, "track_id": "f1:11"}, True).ok
    assert not check_compatibility(base, {**base, "car_id": "f1:team:1"}, True).ok
    assert not check_compatibility(base, {**base, "weather": "heavy_rain"}, True).ok
    assert not check_compatibility({**base, "braking_assist": 0}, {**base, "braking_assist": 2}, True).ok
    assert not check_compatibility(base, base, ref_clean=False).ok
    tyre = check_compatibility(base, {**base, "tyre_compound": "hard"}, True)
    assert tyre.ok and any("compound" in w for w in tyre.warnings)
    setup = check_compatibility({**base, "setup_fp": "a"}, {**base, "setup_fp": "b"}, True)
    assert setup.ok and setup.warnings


def test_incompatible_comparison_yields_no_coaching(demo_session: DecodedSession) -> None:
    m = _model(demo_session)
    ref = analyse_lap(demo_session.laps[0], m)
    comp = compare(ref, analyse_lap(demo_session.laps[2], m), Compatibility(ok=False, blocking=["x"]))
    assert observations_for_comparison(comp) == []


# ---------------------------------------------------------------- coaching rules (unit level)
def _cd(**kw: float | None) -> CornerDelta:
    base: dict[str, float | None] = dict(
        time_delta_s=0.0,
        brake_point_delta_m=0.0,
        brake_release_delta_m=0.0,
        min_speed_delta_kph=0.0,
        min_speed_pos_delta_m=0.0,
        entry_speed_delta_kph=0.0,
        exit_speed_delta_kph=0.0,
        throttle_pickup_delta_m=0.0,
        throttle_full_delta_m=0.0,
        coast_delta_m=0.0,
        release_time_delta_s=0.0,
    )
    base.update(kw)
    m = CornerMetrics(corner="T1", segment_time_s=10.0, min_speed_kph=100.0)
    return CornerDelta(corner="T1", ref=m, cmp=m, **base)  # type: ignore[arg-type]


def _comp(*cds: CornerDelta) -> LapComparison:
    return LapComparison(
        ref_lap_number=1,
        cmp_lap_number=2,
        total_delta_s=0.1,
        delta_d=[],
        delta_s=[],
        corners=list(cds),
        compatibility=Compatibility(ok=True),
    )


def test_later_braking_is_never_suggested_as_a_fix() -> None:
    # braking later AND faster: no corrective observation (and certainly not "brake even later")
    assert not [
        o for o in observations_for_comparison(_comp(_cd(brake_point_delta_m=12, time_delta_s=-0.08))) if not o.positive
    ]
    # braking later but losing exit speed and time: flagged as over-driving
    (o,) = observations_for_comparison(_comp(_cd(brake_point_delta_m=12, exit_speed_delta_kph=-6, time_delta_s=0.1)))
    assert o.kind == "brake_late_overdrive" and "isn't paying off" in o.text


def test_overspeed_into_apex_rule() -> None:
    obs = observations_for_comparison(_comp(_cd(min_speed_delta_kph=6, exit_speed_delta_kph=-5, time_delta_s=0.07)))
    assert [o.kind for o in obs] == ["overspeed_apex"]


def test_below_threshold_or_not_losing_time_is_silent() -> None:
    assert observations_for_comparison(_comp(_cd(brake_point_delta_m=-5, time_delta_s=0.05))) == []
    assert observations_for_comparison(_comp(_cd(brake_point_delta_m=-20, time_delta_s=0.005))) == []


def test_positive_feedback_and_focus_selection() -> None:
    obs = observations_for_comparison(
        _comp(_cd(exit_speed_delta_kph=6, time_delta_s=-0.1), _cd(coast_delta_m=30, time_delta_s=0.2))
    )
    kinds = {o.kind for o in obs}
    assert kinds == {"exit_gain", "coasting"}
    (focus,) = top_focus(obs)
    assert focus.kind == "coasting"


def test_consistency_reported_separately_from_confidence() -> None:
    hist = {"T1": [_cd(brake_point_delta_m=-15), _cd(brake_point_delta_m=-12), _cd(brake_point_delta_m=0)]}
    (o,) = observations_for_comparison(_comp(_cd(brake_point_delta_m=-20, time_delta_s=0.1)), history=hist)
    assert o.consistency == "3 of the last 4 laps" and o.consistency_ratio == 0.75
    assert o.confidence == 1.0
