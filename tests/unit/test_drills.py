"""coachref: practice drill rules (``coach.drills``, pure): targets, attempts, summary, texts, the coaching point."""

from __future__ import annotations

import dataclasses
import re

import pytest

from pitwall.analysis.coaching import SHORT_MAX_CHARS
from pitwall.analysis.compare import CornerDelta, CornerMetrics
from pitwall.coach import drills as dr
from pitwall.coach.selection import COACH_FIELDS

FORBIDDEN = re.compile(r"\bbrake later\b|\blater braking\b|\bbrake (?:at|on|by)\b", re.I)


def cm(**kw: float | None) -> CornerMetrics:
    base: dict[str, float | None] = {
        "segment_time_s": 6.0,
        "brake_start_m": 1100.0,
        "brake_peak": 0.9,
        "entry_speed_kph": 250.0,
        "min_speed_kph": 90.0,
        "exit_speed_kph": 160.0,
    }
    base.update(kw)
    return CornerMetrics(corner="T3", **base)  # type: ignore[arg-type]


def cdelta(time_delta: float = 0.1, ref_min: float = 90.0, cmp_min: float = 88.0) -> CornerDelta:
    return CornerDelta(
        corner="T3",
        time_delta_s=time_delta,
        brake_point_delta_m=None,
        brake_release_delta_m=None,
        min_speed_delta_kph=cmp_min - ref_min,
        min_speed_pos_delta_m=None,
        entry_speed_delta_kph=None,
        exit_speed_delta_kph=None,
        throttle_pickup_delta_m=None,
        throttle_full_delta_m=None,
        coast_delta_m=None,
        release_time_delta_s=None,
        ref=cm(min_speed_kph=ref_min),
        cmp=cm(min_speed_kph=cmp_min),
    )


def spec(
    kind: dr.DrillKind = "brake_point", *, target: float = 1100.0, tol: float = 5.0, laps: int = 5, **kw: object
) -> dr.DrillSpec:
    fields: dict[str, object] = {
        "id": 7,
        "driver_id": 1,
        "session_id": "s1",
        "game": "f1_25",
        "track_id": "f1:17",
        "track_length_m": 4318.0,
        "car_id": "f1:team:41",
        "track_model_version": 2,
        "corner": "T3",
        "corner_label": "T3",
        "corner_voice": "Turn 3",
        "apex_m": 1180.0,
        "kind": kind,
        "source": "manual",
        "observation_kind": None,
        "laps_target": laps,
        "target": target,
        "tolerance": tol,
        "unit": dr.UNITS[kind],
        "baseline": None,
        "started_unix": 1000.0,
        "target_text": "target",
    }
    fields.update(kw)
    return dr.DrillSpec(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------------- targets
def test_brake_point_targets_and_the_clamp() -> None:
    own = dr.plan_target("brake_point", dr.DrillInputs("T3", ref=cm(brake_start_m=1100.0), ref_zone=True))
    assert isinstance(own, dr.DrillTarget)
    assert (own.target, own.tolerance, own.target_source) == (1100.0, 5.0, "own_reference")
    assert own.target_text == "Brake within 5 m of your reference's braking point"
    # another driver brakes LATER than the driver ever did: the call is the driver's own point
    later = dr.plan_target(
        "brake_point",
        dr.DrillInputs(
            "T3", ref=cm(brake_start_m=1155.8), ref_zone=True, ref_other=True, ref_name="Ben", clamp_m=1140.9
        ),
    )
    assert isinstance(later, dr.DrillTarget)
    assert (later.target, later.target_source) == (1140.9, "own_point")
    assert later.target_text == "Brake within 5 m of your own braking point"
    earlier = dr.plan_target(
        "brake_point",
        dr.DrillInputs(
            "T3", ref=cm(brake_start_m=2787.8), ref_zone=True, ref_other=True, ref_name="Ben", clamp_m=2799.2
        ),
    )
    assert isinstance(earlier, dr.DrillTarget)
    assert (earlier.target, earlier.target_source) == (2787.8, "other_reference")
    assert earlier.target_text == "Brake within 5 m of Ben's braking point"


def test_brake_point_unavailable_and_tolerance_floor() -> None:
    no_zone = dr.plan_target("brake_point", dr.DrillInputs("T3", ref=cm(), ref_zone=False))
    assert no_zone == dr.Unavailable("The reference has no braking point at T3.")
    no_own = dr.plan_target("brake_point", dr.DrillInputs("T3", ref=cm(), ref_zone=True, ref_other=True, clamp_m=None))
    assert no_own == dr.Unavailable("No braking point of your own at T3 yet.")
    coarse = dr.plan_target(
        "brake_point", dr.DrillInputs("T3", ref=cm(), ref_zone=True, spacing_p90_m=3.2, tolerance=3.0)
    )
    assert isinstance(coarse, dr.DrillTarget) and coarse.tolerance == 7.0  # ceil(2 x 3.2)
    noted = dr.plan_target(
        "brake_point", dr.DrillInputs("T7", ref=cm(), ref_zone=True, braking_assist=2, shares_with="T8")
    )
    assert isinstance(noted, dr.DrillTarget)
    assert noted.note == f"{dr.ASSIST_NOTE} T7 shares its braking point with T8."
    assert dr.plan_target("brake_point", dr.DrillInputs("T3", ref=cm(), ref_zone=True, braking_assist=0)).note is None  # type: ignore[union-attr]


def test_speed_targets_baseline_cap_and_guard() -> None:
    recent = tuple(cm(min_speed_kph=v, exit_speed_kph=x) for v, x in ((80, 150), (84, 152), (82, 151), (90, 149)))
    t = dr.plan_target(
        "min_speed", dr.DrillInputs("T3", ref=cm(min_speed_kph=92.0), own_best=cm(min_speed_kph=88.0), recent=recent)
    )
    assert isinstance(t, dr.DrillTarget)
    assert t.baseline == 83.0  # median of the recent laps
    assert t.target == 86.0 and t.cap == 92.0 and t.tolerance == 3.0
    assert t.exit_guard == pytest.approx(150.5 - 3.0)
    assert t.target_text == "Minimum speed 86 km/h or more (usually 83)"
    capped = dr.plan_target("min_speed", dr.DrillInputs("T3", ref=cm(min_speed_kph=84.0), recent=recent, tolerance=5.0))
    assert isinstance(capped, dr.DrillTarget) and capped.target == 84.0  # never above the best demonstrated
    # fewer than two recent laps: the own best lap's value
    one = dr.plan_target(
        "exit_speed",
        dr.DrillInputs("T3", ref=cm(exit_speed_kph=170.0), own_best=cm(exit_speed_kph=160.0), recent=recent[:1]),
    )
    assert isinstance(one, dr.DrillTarget) and one.baseline == 160.0 and one.target == 163.0 and one.exit_guard is None
    assert one.target_text == "Exit speed 163 km/h or more (usually 160)"
    assert dr.plan_target("min_speed", dr.DrillInputs("T3")) == dr.Unavailable("Drive a clean lap first.")
    matched = dr.plan_target("min_speed", dr.DrillInputs("T3", ref=cm(min_speed_kph=83.0), recent=recent))
    assert matched == dr.Unavailable("You already match the best minimum speed here (83 km/h).")


def test_entry_speed_anchors_on_own_laps_only() -> None:
    recent = tuple(cm(entry_speed_kph=v) for v in (251.0, 239.0, 228.0))
    t = dr.plan_target(
        "entry_speed", dr.DrillInputs("T6", ref=cm(entry_speed_kph=280.0), ref_other=True, recent=recent)
    )
    assert isinstance(t, dr.DrillTarget)
    assert t.target == 239.0 and t.baseline == 239.0  # median of own laps, never the other driver's 280
    assert t.target_text == "Arrive at 239 km/h, within 5 km/h"
    own = dr.plan_target("entry_speed", dr.DrillInputs("T6", own_best=cm(entry_speed_kph=245.0)))
    assert isinstance(own, dr.DrillTarget) and own.target == 245.0


def test_observation_kinds_map_to_drills() -> None:
    assert dr.kind_for_observation("brake_early") == "brake_point"
    assert dr.kind_for_observation("brake_late_overdrive") == "brake_point"
    assert dr.kind_for_observation("low_min_speed") == "min_speed"
    assert {dr.kind_for_observation(k) for k in ("overspeed_apex", "late_throttle", "coasting")} == {"exit_speed"}
    assert dr.kind_for_observation("exit_gain") is None and dr.kind_for_observation("incident") is None


# ---------------------------------------------------------------------------------------------- attempts
def attempt(state: dr.DrillState, m: CornerMetrics | None, cd: CornerDelta | None = None) -> dr.DrillAttempt:
    return dr.evaluate_attempt(state, m, cd, lap_id=10 + len(state.attempts), lap_number=3 + len(state.attempts))


@pytest.mark.parametrize(
    ("value", "outcome", "phrase"),
    [
        (1100.4, "hit", "on the point"),
        (1103.0, "hit", "on the point, 3 m late"),
        (1096.0, "hit", "on the point, 4 m early"),
        (1092.0, "miss", "8 m before the point"),
        (1111.0, "miss", "11 m past the point"),
        (None, "unmeasured", "no braking measured"),
    ],
)
def test_brake_point_evaluation(value: float | None, outcome: str, phrase: str) -> None:
    st = dr.DrillState(spec())
    a = attempt(st, cm(brake_start_m=value))
    assert a.outcome == outcome
    assert a.text.startswith(f"Turn 3 drill, lap 1 of 5: {phrase}.")
    assert len(a.short) <= SHORT_MAX_CHARS and a.short.startswith("Drill 1/5: ")
    assert not FORBIDDEN.search(a.text)


def test_incident_min_speed_guard_and_entry_both_sides() -> None:
    inc = attempt(dr.DrillState(spec()), cm(), cdelta(time_delta=2.6))
    assert (inc.outcome, inc.reason) == ("miss", "incident")
    assert "incident there" in inc.text
    s = spec("min_speed", target=86.0, tol=3.0, baseline=83.0, exit_guard=147.5)
    hit = attempt(dr.DrillState(s), cm(min_speed_kph=87.0, exit_speed_kph=150.0))
    assert hit.outcome == "hit" and "minimum 87 km/h, on target" in hit.text
    guard = attempt(dr.DrillState(s), cm(min_speed_kph=88.0, exit_speed_kph=145.0))
    assert (guard.outcome, guard.reason) == ("miss", "exit 6 km/h down")
    assert "minimum 88 km/h but exit 6 km/h down" in guard.text
    short = attempt(dr.DrillState(s), cm(min_speed_kph=84.0))
    assert short.outcome == "miss" and "minimum 84 km/h, 2 short" in short.text
    e = spec("entry_speed", target=240.0, tol=5.0, baseline=240.0)
    assert attempt(dr.DrillState(e), cm(entry_speed_kph=244.0)).outcome == "hit"
    fast = attempt(dr.DrillState(e), cm(entry_speed_kph=247.0))
    assert fast.outcome == "miss" and "arrived 7 km/h faster than usual" in fast.text
    slow = attempt(dr.DrillState(e), cm(entry_speed_kph=232.0))
    assert "arrived 8 km/h slower than usual" in slow.text
    x = spec("exit_speed", target=163.0, tol=3.0, baseline=160.0)
    assert attempt(dr.DrillState(x), cm(exit_speed_kph=163.0)).outcome == "hit"
    assert attempt(dr.DrillState(x), cm(exit_speed_kph=None)).outcome == "unmeasured"


def run(s: dr.DrillSpec, values: list[float | None], attr: str = "brake_start_m") -> dr.DrillState:
    st = dr.DrillState(s, last_activity_unix=1000.0)
    for v in values:
        a = attempt(st, cm(**{attr: v}))
        st = st.with_attempt(a, 2000.0)
    return st


def test_summary_best_and_trend_thresholds() -> None:
    st = run(spec(laps=5), [1110.0, 1108.0, 1101.0, 1099.0, 1100.0])
    s = st.summary
    assert st.status == "completed" and (s.hits, s.scored) == (3, 5)
    assert s.best == 1100.0 and s.best_delta == 0.0
    assert s.trend == "closer"  # first half |9|,|8| vs second half |1|,|0|: -8 <= -2.5
    assert run(spec(laps=4), [1101.0, 1102.0, 1101.0, 1103.0]).summary.trend == "steady"
    assert run(spec(laps=4), [1100.0, 1100.0, 1102.5, 1102.5]).summary.trend == "further"  # +2.5 = +tol/2
    assert run(spec(laps=4), [1100.0, 1100.0, 1102.4, 1102.4]).summary.trend == "steady"
    assert run(spec(laps=3), [1100.0, 1110.0, 1100.0]).summary.trend is None  # < 4 scored attempts
    sp = spec("min_speed", target=86.0, tol=3.0, laps=4)
    assert run(sp, [84.0, 85.0, 86.0, 86.0], "min_speed_kph").summary.trend == "rising"  # +1.5
    assert run(sp, [86.0, 86.0, 85.0, 85.0], "min_speed_kph").summary.trend == "falling"  # -1.0
    assert run(sp, [86.0, 86.0, 85.5, 85.5], "min_speed_kph").summary.trend == "steady"
    # odd count: the middle attempt counts in neither half; unmeasured attempts are not scored
    odd = run(spec(laps=6), [1110.0, 1109.0, None, 1150.0, 1101.0, 1100.0])
    assert odd.summary.scored == 5 and odd.summary.trend == "closer"  # |10|,|9| vs |1|,|0|; the 50 m miss is the middle


def test_result_texts_and_last_attempt() -> None:
    st = run(spec(laps=3), [1092.0, 1101.0, 1100.0])
    last = st.attempts[-1]
    assert last.text == "Turn 3 drill done: 2 of 3 on the point. Best 0 m."
    assert last.short == "Drill done: 2/3 · best 0 m"
    assert last.text_simple == "Turn 3 drill done: 2 of 3 on the point."
    stopped = run(spec(laps=5), [1092.0, 1101.0]).stopped("driver", 3000.0)
    assert stopped.status == "stopped"
    assert (
        dr.drill_view(stopped)["summary_text"]
        == "Turn 3 drill stopped after 2 of 5 laps: 1 of 2 on the point. Best 1 m."
    )
    assert dr.stop_text(stopped) == "Copy, Turn 3 drill stopped: 1 of 2 on the point."
    assert dr.DrillState(spec()).stopped("driver", 1.0).status == "abandoned"
    active = run(spec(laps=5), [1092.0])
    assert dr.status_text(active) == "Turn 3 brake point drill: 1 of 5 done, 0 hits. Last one 8 m before the point."
    sp = run(spec("min_speed", target=86.0, tol=3.0, laps=3), [84.0, 87.0, 88.0], "min_speed_kph")
    assert sp.attempts[-1].text == "Turn 3 drill done: 2 of 3 on target. Best 88 km/h."


def test_texts_are_british_short_and_never_instructions() -> None:
    long_voice = spec(corner_voice="Turns 2 to 4, Eau Rouge and Raidillon")
    for s in (spec(), long_voice, spec("entry_speed", target=240.0), spec("exit_speed", target=160.0)):
        st = dr.DrillState(s)
        for v in (s.target - 30, s.target, s.target + 30, None):
            attr = dr.METRICS[s.kind]
            a = dr.evaluate_attempt(st, cm(**{attr: v}), None, lap_id=1, lap_number=2)
            assert len(a.short) <= SHORT_MAX_CHARS
            for t in (a.text, a.short, a.text_simple):
                assert not FORBIDDEN.search(t)
                assert "you should" not in t.lower()


def test_drill_point_and_with_drill() -> None:
    st = run(spec(laps=5, ref_name="Sam"), [1101.0])
    point = dr.drill_point(st, st.attempts[0])
    assert set(COACH_FIELDS) <= set(point)
    assert point["kind"] == "drill" and point["positive"] is False and point["confidence"] == 1.0
    assert point["priority"] == dr.DRILL_PRIORITY and point["id"] == "drill7:a1"
    assert point["ref_name"] == "Sam"
    assert point["drill"] == {"id": 7, "attempt": 1, "of": 5, "hits": 1, "outcome": "hit", "done": False}
    block = {"lap_id": 9, "lap_number": 4, "radio_quiet": False, "picked": [{"id": "x"}], "by_corner": {"T9": {}}}
    out = dr.with_drill(block, point, "T3")
    assert out["picked"] == [point] and out["by_corner"] == {"T3": point} and out["drill_only"] is True
    assert block["picked"] == [{"id": "x"}]  # the original block is not changed
    quiet = dr.with_drill({**block, "radio_quiet": True}, point, "T3")
    assert quiet["picked"] == [] and quiet["by_corner"] == {"T3": point}
    none = dr.with_drill(block, None, "T3")
    assert none["picked"] == [] and none["by_corner"] == {} and none["drill_only"] is True


def test_attempt_laps() -> None:
    s = spec(start_lap_number=4)
    assert not dr.is_attempt_lap(s, "s1", 4, set())  # the lap the drill started on
    assert dr.is_attempt_lap(s, "s1", 5, {"invalid"})  # track limits count
    for flag in ("incomplete", "pit_in", "pit_out", "flashback"):
        assert not dr.is_attempt_lap(s, "s1", 6, {flag})
    assert dr.is_attempt_lap(s, "s2", 1, set())  # a later session: every lap


def test_rows_round_trip() -> None:
    st = run(spec(laps=5, ref_name="Sam", clamp={"T3": 1100.0}, ref_desc={"lap_id": 4, "own": False}), [1092.0, 1101.0])
    row = {"id": 7, **dr.spec_row(st.spec, st)}
    back = dr.state_from_row(row)
    assert dr.drill_view(back) == dr.drill_view(st)
    assert back.spec.clamp == {"T3": 1100.0} and back.spec.ref_desc == {"lap_id": 4, "own": False}
    assert dataclasses.replace(back.spec, ref_desc=None).ref_name == "Sam"
