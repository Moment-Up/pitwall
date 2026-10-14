"""Corner reminders and habit-based braking calls (habits spec section 4): focus-mode planning from the coach block's
``focus`` / ``habits``, the reminder phrase and its evidence rules, the timing rule (the phrase ENDS at least
``REMINDER_END_MARGIN_S`` before the reference braking point, or is dropped), the speak window protecting a cue's
start, and the radio hub's pre-synthesis and gating of reminders.

Synthetic approaches at 150-300 km/h (constant speed and accelerating on the straight) make every expected point
exact. SYNTHETIC: they prove the trigger and timing model, not behaviour with a real game.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np
import pytest

from pitwall.analysis.distance import DistanceTrace
from pitwall.coach import cues as cues_mod
from pitwall.coach.cues import (
    MARGIN_M,
    NO_HABITS,
    REMINDER_CALM_SLACK_S,
    REMINDER_END_MARGIN_S,
    CueEngine,
    CueEvent,
    CueKind,
    CueLabel,
    CuePlan,
    CueSpec,
    CueTiming,
    FocusLimits,
    build_cue_plan,
    estimate_phrase_s,
    select_habit_corners,
)
from pitwall.core.live import LiveState
from pitwall.drivers import coaching_limits
from pitwall.voice.scheduler import (
    POLICY_BY_KEY,
    SPEAK_WINDOW_MARGIN_S,
    WORDS_PER_S,
    DrivingState,
    speak_window_ok,
)
from tests.unit.test_cues import (
    LENGTH,
    REF_ID,
    CountingTts,
    V,
    comparison,
    flat_trace,
    focus_of,
    frame,
    habit,
    habit_obs,
    install_plan,
    laps,
    make_hub,
    obs,
    reference,
    run,
    says,
    settle,
)

W = cues_mod.DEFAULT_WORD_S
P = cues_mod.PART_PAUSE_S
APEX = ("T1", "apex speed, 12 down")  # learned name (no track identity) + phrase
APEX_S = 6 * W + 2 * P  # "turn 1" (2 words) + "apex speed, twelve down" (4); pauses between the parts and at the comma


def low(corner: str = "T1", value: float = -12.0, status: str = "focus", **kw: Any) -> dict[str, Any]:
    return habit(corner, "low_min_speed", status, value, **kw)


def plan_for(
    habits: list[dict[str, Any]],
    *,
    zones: dict[str, float] | None = None,
    mode: str = "focus",
    trace: DistanceTrace | None = None,
    limits: FocusLimits | None = None,
    labels: dict[str, CueLabel] | None = None,
    focus: list[dict[str, Any]] | None = None,
) -> CuePlan:
    return build_cue_plan(
        mode,
        comparison(zones),
        length_m=LENGTH,
        reference=reference(),
        trace=trace if trace is not None else flat_trace(),
        focus=focus_of(habits) if focus is None else focus,
        habits=habits,
        focus_limits=limits or FocusLimits(),
        labels=labels,
    )


def habit_engine(
    habits: list[dict[str, Any]],
    *,
    zones: dict[str, float] | None = None,
    trace: DistanceTrace | None = None,
    v: float = V,
    latency: float = 0.3,
    durations: dict[tuple[str, ...], float] | None = None,
) -> tuple[CueEngine, list[CueEvent]]:
    e = CueEngine("focus")
    e.on_reference(reference(v=v), trace if trace is not None else flat_trace(v=v))
    e.on_lap_result([], comparison(zones, entry=v * 3.6), LENGTH, focus=focus_of(habits), habits=habits)
    e.set_timing(CueTiming(latency_s=latency, durations_s=durations or {}))
    fired: list[CueEvent] = []
    e.set_sink(fired.append)
    return e, fired


def trace_from(v_mps: np.ndarray, brake: np.ndarray | None = None) -> DistanceTrace:
    """A reference lap on the 1 m grid from its speed (m/s) per metre: time is the integral of 1 / v."""
    d = np.arange(0.0, LENGTH, 1.0)
    t = np.concatenate([[0.0], np.cumsum(1.0 / v_mps[:-1])])
    ch = {"speed_kph": v_mps * 3.6, "brake": np.zeros_like(d) if brake is None else brake}
    return DistanceTrace(d=d, t_s=t, ch=ch, lap_number=3)


def accelerating(v0_kph: float, v1_kph: float, start: float, target: float) -> np.ndarray:
    """v0 until ``start``, constant acceleration to v1 at ``target`` (the braking point), then a braking zone."""
    d = np.arange(0.0, LENGTH, 1.0)
    v0, v1 = v0_kph / 3.6, v1_kph / 3.6
    a = (v1**2 - v0**2) / (2.0 * (target - start))
    v = np.where(d < start, v0, np.sqrt(np.maximum(v0**2, v0**2 + 2.0 * a * (d - start))))
    after = d >= target
    v[after] = np.maximum(30.0, v1 - 0.5 * (d[after] - target))
    return v


# ============================================================================================== planning
def test_estimate_phrase_s_counts_spoken_words_and_errs_long() -> None:
    assert estimate_phrase_s(APEX) == pytest.approx(APEX_S)
    assert estimate_phrase_s(("Turn 6", "coasting, 30 metres")) == pytest.approx(5 * W + 2 * P)
    assert estimate_phrase_s(("Turn 21", "throttle, 105 metres late")) == pytest.approx((3 + 1 + 4 + 2) * W + 2 * P)
    assert estimate_phrase_s(("one",)) == pytest.approx(W)
    # 2.6 words/s is slower than the voices: "turn one, apex speed, twelve down" takes under 2.5 s to say
    assert estimate_phrase_s(APEX) > 6 / 3.0


@pytest.mark.parametrize(
    ("kind", "value", "phrase"),
    [
        ("low_min_speed", -12.4, "apex speed, 12 down"),
        ("late_throttle", 38.0, "throttle, 40 metres late"),
        ("coasting", 31.0, "coasting, 30 metres"),
    ],
)
def test_a_focus_habit_gets_a_reminder_that_ends_before_its_braking_point(kind: str, value: float, phrase: str) -> None:
    plan = plan_for([habit("T1", kind, "focus", value)])
    assert plan.reason is None and plan.focus == ("T1",)
    (c,) = plan.cues
    assert (c.corner, c.kind, c.target_m, c.parts, c.key_index, c.focus) == (
        "T1",
        CueKind.REMINDER,
        1000.0,
        ("T1", phrase),
        0,
        True,
    )
    assert c.text == f"T1: {phrase}"
    # the phrase starts its own spoken length plus the margin before the point: it ends the margin before it
    assert c.anticipation_s == pytest.approx(estimate_phrase_s(c.parts) + REMINDER_END_MARGIN_S)
    assert c.calm_s == pytest.approx(cues_mod.WINDOW_M / V)  # the reference never braked on the approach
    assert "habit (focus), 3 of the last 4 laps" in c.reason
    assert c.to_dict()["kind"] == "reminder"


def test_reminders_never_tell_the_driver_to_brake_later() -> None:
    """Braking habits get a braking call at the reference point (where the driver braked on their best lap), never a
    phrase; reminder phrases are descriptive."""
    for kind in sorted(cues_mod.BRAKE_CUE_OBSERVATIONS):
        plan = plan_for([habit("T1", kind, "focus", -15.0)])
        assert [(c.kind, c.parts) for c in plan.cues] == [(CueKind.BRAKE, ("T1", "brake"))]
    plan = plan_for([low(), habit("T2", "late_throttle", "focus", 40.0)])
    for c in plan.cues:
        assert "brake" not in " ".join(c.parts).lower() and "later" not in " ".join(c.parts).lower()


def test_one_call_per_corner_the_focus_reminder_wins() -> None:
    habits = [low("T1"), habit("T1", "brake_early", "seen"), habit("T2", "overspeed_apex", "seen", 12.0)]
    plan = plan_for(habits)
    assert [(c.corner, c.kind) for c in plan.cues] == [("T1", CueKind.REMINDER), ("T2", CueKind.BRAKE)]
    assert plan.focus == ("T1", "T2")
    # two focus habits at one corner: one reminder (the first, in the block's order)
    plan = plan_for([low("T1"), habit("T1", "late_throttle", "focus", 40.0)])
    assert [c.parts for c in plan.cues] == [APEX]


def test_reminder_only_where_the_reference_was_off_the_brakes_for_the_whole_phrase() -> None:
    """The reference braked into a corner shortly before T1's braking point: a reminder there would talk through that
    braking zone (and a braking call there would be dropped while it plays). No reminder; a braking habit at T1 still
    gets its call."""
    d = np.arange(0.0, LENGTH, 1.0)
    need = APEX_S + REMINDER_END_MARGIN_S + REMINDER_CALM_SLACK_S  # seconds of calm the phrase needs
    for calm_s, ok in ((need - 0.1, False), (need + 0.1, True)):
        brake = np.where((d >= 500.0) & (d < 1000.0 - calm_s * V), 1.0, 0.0)
        trace = DistanceTrace(d=d, t_s=d / V, ch={"speed_kph": np.full_like(d, V * 3.6), "brake": brake}, lap_number=3)
        plan = plan_for([low("T1"), habit("T1", "brake_early", "seen")], trace=trace)
        kinds = [c.kind for c in plan.cues]
        assert kinds == ([CueKind.REMINDER] if ok else [CueKind.BRAKE]), calm_s
        if ok:
            assert plan.cues[0].calm_s == pytest.approx(calm_s, abs=0.02)
    # no brake channel on the reference: the stretch is unknown, and unknown is not calm
    no_pedal = DistanceTrace(d=d, t_s=d / V, ch={"speed_kph": np.full_like(d, V * 3.6)}, lap_number=3)
    assert plan_for([low()], trace=no_pedal).cues == ()


def test_the_calm_check_uses_the_longer_spoken_name() -> None:
    """A corner said "Turn 1, second part" when another Turn 1 call is planned: the room is checked with the longer
    name, so the final phrase always fits."""
    labels = {"T1": CueLabel("T1 (2)", "Turn 1", "Turn 1, second part")}
    plan = plan_for([low()], labels=labels)
    (c,) = plan.cues
    assert c.parts == ("Turn 1", "apex speed, 12 down") and c.text == "T1 (2): apex speed, 12 down"
    unnamed = {"T1": CueLabel("565 m", None, "Corner at 570 metres")}  # no short name: a reminder names it anyway
    (c,) = plan_for([low()], labels=unnamed).cues
    assert c.parts == ("Corner at 570 metres", "apex speed, 12 down")


@pytest.mark.parametrize(
    "case",
    [
        "no_zone",  # no measured reference braking zone at the corner: nothing to time it to
        "seen",  # a habit not being worked on: on the screen only
        "fixed",
        "no_template",  # a kind without a reminder phrase
        "no_value",  # unknown size: nothing said
        "kind_not_allowed",
    ],
)
def test_no_reminder_without_a_focus_habit_a_phrase_and_evidence(case: str) -> None:
    h = low("T9" if case == "no_zone" else "T1")
    limits = FocusLimits()
    if case in ("seen", "fixed"):
        h["status"] = case
    elif case == "no_template":
        h["kind"] = "exit_gain"
    elif case == "no_value":
        h["value"] = None
    elif case == "kind_not_allowed":
        limits = FocusLimits(allowed_kinds=frozenset({"brake_early", "late_throttle"}))
    plan = plan_for([h], limits=limits)
    assert plan.cues == () and plan.reason == NO_HABITS


def test_braking_calls_follow_braking_habits_up_to_the_profile_cap() -> None:
    zones = {"T1": 1000.0, "T2": 2000.0, "T3": 2600.0, "T4": 2800.0}
    habits = [
        habit("T3", "brake_late_overdrive", "seen", 12.0, impact=0.3),
        habit("T1", "brake_early", "seen", impact=0.2),
        habit("T2", "overspeed_apex", "focus", 9.0, impact=0.12),  # being worked on: first
        habit("T4", "brake_early", "fixed", impact=0.5),  # sorted: no call
        low("T4", status="seen", impact=0.6),  # not a braking habit, not the focus: no call
    ]
    plan = plan_for(habits, zones=zones)
    assert [c.corner for c in sorted(plan.cues, key=lambda c: c.target_m)] == ["T1", "T2", "T3"]
    assert plan.focus == ("T2", "T3", "T1")  # focus first, then the block's order (bigger impact first)
    assert all(c.kind is CueKind.BRAKE and c.parts[1:] == ("brake",) for c in plan.cues)
    beginner = FocusLimits.from_profile(coaching_limits("beginner"))
    assert [c.corner for c in plan_for(habits, zones=zones, limits=beginner).cues] == ["T2"]  # one, the focus
    intermediate = FocusLimits.from_profile(coaching_limits("intermediate"))
    assert len(plan_for(habits, zones=zones, limits=intermediate).cues) == 3
    floor = FocusLimits(min_impact_s=0.15)  # the impact floor applies to the habit's mean impact
    assert [c for c, _ in select_habit_corners(habits, zones, limits=floor)] == ["T3", "T1"]
    unknown = [habit("T1", impact=None)]
    assert select_habit_corners(unknown, zones, limits=floor) == []  # unknown is not small
    assert [c for c, _ in select_habit_corners(unknown, zones)] == ["T1"]
    narrowed = FocusLimits(allowed_kinds=frozenset({"overspeed_apex", "low_min_speed"}))
    assert [c for c, _ in select_habit_corners(habits, zones, limits=narrowed)] == ["T2"]
    assert [c for c, _ in select_habit_corners(habits, zones, max_corners=1)] == ["T2"]
    assert [c for c, _ in select_habit_corners(habits, zones, skip={"T2"})] == ["T3", "T1"]
    assert select_habit_corners(habits, {"T9": 1.0}) == []  # no measured zone: no call
    reason = dict(select_habit_corners(habits, zones))["T1"]
    assert reason == "brake_early habit (seen), 3 of the last 4 laps"


def test_one_offs_get_no_focus_call_when_habits_are_given() -> None:
    """The lap's observations no longer pick focus corners when the coach block's habits are given: a single lap's
    early braking is screen-only."""
    e = CueEngine("focus")
    e.on_reference(reference(), flat_trace())
    e.on_lap_result([obs("T2", prio=0.9)], comparison(), LENGTH, focus=[], habits=[])
    assert e.plan.cues == () and e.plan.reason == NO_HABITS
    e.on_lap_result([obs("T2")], comparison(), LENGTH, focus=[], habits=[habit("T2")])
    assert [c.text for c in e.plan.cues] == ["T2 brake"]
    # only one list given: the other is taken as empty (habits stand in for focus and the other way round)
    e.on_lap_result([], comparison(), LENGTH, focus=focus_of([low("T1")]), habits=None)
    assert [c.kind for c in e.plan.cues] == [CueKind.REMINDER]


def test_without_habits_the_fallback_picks_from_recent_observations_as_before() -> None:
    """A caller that predates habits (no focus, no habits) keeps select_focus_corners."""
    e = CueEngine("focus")
    e.on_reference(reference(), flat_trace())
    e.on_lap_result([obs("T2"), obs("T1", "late_throttle")], comparison(), LENGTH)
    assert [(c.corner, c.kind) for c in e.plan.cues] == [("T2", CueKind.BRAKE)]
    assert e.plan.cues[0].reason == "brake_early on 1 of the last 1 lap(s)"
    direct = build_cue_plan(
        "focus", comparison(), length_m=LENGTH, history=[[obs("T1")]], reference=reference(), trace=flat_trace()
    )
    assert [c.corner for c in direct.cues] == ["T1"]
    empty = build_cue_plan("focus", comparison(), length_m=LENGTH, reference=reference(), trace=flat_trace())
    assert empty.reason == "no braking corrections to focus on"


def test_markers_all_and_drills_have_no_reminders() -> None:
    habits = [low("T1"), habit("T2", "brake_early", "seen")]
    markers = plan_for(habits, mode="markers")
    assert {c.kind for c in markers.cues} == {CueKind.MARKER} and len(markers.cues) == 2
    every = plan_for(habits, mode="all")
    assert {c.kind for c in every.cues} == {CueKind.BRAKE} and len(every.cues) == 2
    drill = build_cue_plan(  # --- coachref --- a drill's corner is the focus (a braking call), habits or not
        "focus",
        comparison(),
        length_m=LENGTH,
        reference=reference(),
        trace=flat_trace(),
        focus=focus_of(habits),
        habits=habits,
        only_corner="T1",
    )
    assert [(c.corner, c.kind, c.reason) for c in drill.cues] == [("T1", CueKind.BRAKE, "drill")]


def test_habits_are_kept_with_the_comparison_and_dropped_with_the_reference() -> None:
    e, _ = habit_engine([low("T1"), habit("T2")])
    assert [c.kind for c in e.plan.cues] == [CueKind.REMINDER, CueKind.BRAKE]
    e.set_mode("all")
    e.set_mode("focus")  # a replan from the stored inputs keeps the habits
    assert [c.kind for c in e.plan.cues] == [CueKind.REMINDER, CueKind.BRAKE]
    e.on_lap_result([], None, LENGTH)  # a lap without a comparison keeps them (and the plan)
    assert len(e.plan.cues) == 2
    e.set_driver(1)
    e.set_driver(2)  # someone else in the seat: the previous driver's habits go with their reference
    e.on_lap_result([], comparison(), LENGTH)  # their first lap from a caller without a block: the fallback
    assert e.plan.cues == () and e.plan.reason == "no braking corrections to focus on"
    e2, _ = habit_engine([low("T1")])
    e2.reset_session()
    e2.on_lap_result([], comparison(), LENGTH)
    assert e2.plan.reason == "no braking corrections to focus on"


def test_live_state_plans_from_the_coach_blocks_habits() -> None:
    """LiveState -> CoachSelection (habit tracker) -> CueEngine: three laps with the same two faults make two habits;
    the first one (one focus slot at normal intensity) gets a reminder, the other is seen and gets a braking call."""
    live = LiveState()
    live.set_track_model({"length_m": LENGTH, "corners": []})
    live.cues.set_mode("focus")
    live.set_reference(reference(), flat_trace())
    observations = [habit_obs("T1", "low_min_speed", -12.0), habit_obs("T2")]
    live.on_lap_result({"lap_id": 3, "lap_number": 3}, observations, comparison())
    assert live.cues.plan.cues == () and live.cues.plan.reason == NO_HABITS  # one lap: no habit yet
    for n in (4, 5):
        live.on_lap_result({"lap_id": n, "lap_number": n}, observations, comparison())
    coach = live.coach.current
    assert coach is not None and [h["status"] for h in coach["habits"]] == ["focus", "seen"]
    assert [(c.corner, c.kind, c.parts) for c in live.cues.plan.cues] == [
        ("T1", CueKind.REMINDER, APEX),
        ("T2", CueKind.BRAKE, ("T2", "brake")),
    ]


# ============================================================================================== timing
def _speech_end_spare_s(ev: CueEvent, latency: float, spoken_s: float, v: float) -> float:
    """Constant speed: seconds between the end of the phrase and the car reaching the braking point."""
    reach = (ev.cue.target_m - ev.d_m) / v
    return reach - (latency + spoken_s)


@pytest.mark.parametrize("kph", [150.0, 200.0, 250.0, 300.0])
@pytest.mark.parametrize("hz", [60.0, 20.0])
def test_reminder_ends_at_least_the_margin_before_the_braking_point(kph: float, hz: float) -> None:
    v = kph / 3.6
    e, fired = habit_engine([low("T1")], v=v, latency=0.3)
    laps(e, 2, hz=hz, v_kph=kph)
    assert [(ev.lap, ev.cue.kind) for ev in fired] == [(1, CueKind.REMINDER), (2, CueKind.REMINDER)]
    for ev in fired:
        spare = _speech_end_spare_s(ev, 0.3, APEX_S, v)
        assert spare >= REMINDER_END_MARGIN_S  # ends a second before the point, at any speed
        # and not needlessly early: the margin plus MARGIN_M at this speed, quantised by at most half a frame
        assert spare <= REMINDER_END_MARGIN_S + MARGIN_M / v + 0.5 / hz + 1e-6
        assert ev.lead_anticipation_s == pytest.approx(APEX_S + REMINDER_END_MARGIN_S)
        assert ev.word_offset_s == 0.0 and ev.aim_m == pytest.approx(
            ev.cue.target_m - MARGIN_M - (APEX_S + REMINDER_END_MARGIN_S) * v, abs=1.0
        )
        # the hub must start it by its deadline: later and the phrase would run into the margin
        late_start = ev.deadline_mono - ev.fired_mono
        assert late_start == pytest.approx(ev.ttg_s - 0.3 - ev.lead_anticipation_s)
        assert 0.0 <= late_start <= 0.5 / hz + MARGIN_M / v + 1e-6


def straight_engine(trace: DistanceTrace, target: float, latency: float) -> tuple[CueEngine, list[CueEvent]]:
    """A focus-mode engine with a minimum-speed habit at "T2" (braking point ``target``) on ``trace``."""
    e = CueEngine("focus")
    e.on_reference({"lap_id": REF_ID, "lap_time_ms": round(float(trace.t_s[-1]) * 1000)}, trace)
    e.on_lap_result(
        [], comparison({"T2": target}, entry=300.0), LENGTH, focus=focus_of([low("T2")]), habits=[low("T2")]
    )
    e.set_timing(CueTiming(latency_s=latency))
    fired: list[CueEvent] = []
    e.set_sink(fired.append)
    return e, fired


def drive_straight(
    e: CueEngine, speed: Any, target: float, hz: float, d0: float = 300.0, d1: float = 2300.0
) -> tuple[float, list[float], list[float]]:
    """Drive from ``d0`` to ``d1`` at ``speed(d)`` (m/s) in time, fine sub-steps between frames at ``hz``. Returns
    when the car reached ``target`` and the frames' (times, distances)."""
    t, d, dt, sub = 100.0, d0, 1.0 / hz, 20
    path_t: list[float] = []
    path_d: list[float] = []
    reach_t = None
    while d < d1:
        e.on_frame(frame(3, d, t, speed(d) * 3.6), t)
        path_t.append(t)
        path_d.append(d)
        for _ in range(sub):
            nd = d + speed(d) * dt / sub
            if reach_t is None and nd >= target:
                reach_t = t + (target - d) / speed(d)
            d, t = nd, t + dt / sub
    assert reach_t is not None
    return reach_t, path_t, path_d


@pytest.mark.parametrize("hz", [60.0, 20.0])
@pytest.mark.parametrize("pace", [1.0, 0.95, 1.05])
def test_reminder_on_an_accelerating_straight_ends_before_the_braking_point(hz: float, pace: float) -> None:
    """150 -> 300 km/h on the straight into T2's braking point: the car covers far more ground per second at the end
    of the phrase than at its start. Timing on the reference lap's own time (scaled to the driver's pace when faster,
    the reference's own when slower: ``_time_to_go(catch_up=True)``) ends the phrase a second before the point,
    whether the driver is the reference's pace, 5% slower or 5% faster."""
    target, latency = 2000.0, 0.3
    v_ref = accelerating(150.0, 300.0, 1000.0, target)
    brake = np.where((np.arange(0.0, LENGTH) >= target) & (np.arange(0.0, LENGTH) < target + 120.0), 1.0, 0.0)
    trace = trace_from(v_ref, brake)
    e, fired = straight_engine(trace, target, latency)
    (spec,) = e.plan.cues
    assert spec.kind is CueKind.REMINDER and spec.calm_s is not None and spec.calm_s > 8.0

    def speed(d: float) -> float:
        return pace * float(np.interp(d, trace.d, v_ref))

    reach_t, path_t, path_d = drive_straight(e, speed, target, hz)
    (ev,) = fired
    assert ev.v_mps * 3.6 > 150.0 * pace
    spare = reach_t - (ev.fired_mono + latency + APEX_S)
    assert spare >= REMINDER_END_MARGIN_S, spare
    # not needlessly early; a slower driver is assumed to catch up, so their phrase ends that much earlier
    assert spare <= REMINDER_END_MARGIN_S + 0.2 + max(0.0, 1.0 / pace - 1.0) * ev.ttg_s, spare
    # the speak window's view of it agreed with the trigger: sampled two seconds before it fired
    k = int(np.searchsorted(path_t, ev.fired_mono - 2.0))
    e2, _ = straight_engine(trace, target, latency)
    for i in range(k + 1):
        e2.on_frame(frame(3, path_d[i], path_t[i], speed(path_d[i]) * 3.6), path_t[i])
    due = e2.seconds_to_next_cue()
    assert due is not None
    v_k = speed(path_d[k])
    constant_speed = (target - path_d[k]) / v_k - latency - spec.anticipation_s - MARGIN_M / v_k
    predicted = path_t[k] + due  # when the radio thinks the reminder starts: never after it really does
    assert predicted <= ev.fired_mono + 1.0 / hz
    # within a frame or two; a slower driver assumed to catch up makes it start sooner than predicted (safe side)
    assert ev.fired_mono - predicted <= 2.0 / hz + max(0.0, 1.0 / pace - 1.0) * 2.5
    assert due < constant_speed - 0.1  # still accelerating: constant speed would think there is more time


@pytest.mark.parametrize("hz", [60.0, 20.0])
def test_reminder_for_a_driver_who_catches_up_on_the_straight_still_ends_in_time(hz: float) -> None:
    """Seen on real laps: the driver leaves the previous corner slower than the reference, then is as fast by the end of
    the straight. Scaling the reference's time by ``v_ref / v`` where the reminder fires assumes the car stays slower
    all the way, which made the phrase end only 0.5 s before the point on a recorded lap. The reminder assumes the car
    reaches the reference's pace instead: the phrase still ends a second before the point."""
    target, latency = 2000.0, 0.3
    v_ref = accelerating(150.0, 300.0, 1000.0, target)
    trace = trace_from(v_ref)
    e, fired = straight_engine(trace, target, latency)

    def speed(d: float) -> float:  # 75% of the reference's speed until 380 m before the point, its speed from 260 m
        f = float(np.interp(d, [target - 380.0, target - 260.0], [0.75, 1.0]))
        return f * float(np.interp(d, trace.d, v_ref))

    reach_t, _path_t, _path_d = drive_straight(e, speed, target, hz)
    (ev,) = fired
    k = ev.cue.target_m - ev.d_m
    app = e.plan.approaches[0]
    scaled, _ = cues_mod._time_to_go(app, k, ev.v_mps)
    assert ev.v_mps < 0.95 * float(np.interp(ev.d_m, trace.d, v_ref))  # slower than the reference where it fired
    assert ev.ttg_s < scaled - 0.3  # the reference's own time, not the slower-pace scaling
    spare = reach_t - (ev.fired_mono + latency + APEX_S)
    assert REMINDER_END_MARGIN_S <= spare <= REMINDER_END_MARGIN_S + 0.4, spare
    # a braking call keeps the scaled estimate (its lead is about a second): unchanged behaviour
    assert cues_mod._time_to_go(app, k, ev.v_mps, catch_up=False) == (scaled, _)


def test_reminder_is_dropped_not_late_after_lost_frames() -> None:
    """300 km/h: the reminder's start is due at 1000 - 83.3 * (0.3 + 3.61) - 5 = 669 m. The last frame before a 0.6 s
    gap is at 660 m, the next at 710 m: the phrase would end less than a second before the point. Dropped."""
    v = 300 / 3.6
    e, fired = habit_engine([low("T1")], v=v, latency=0.3)
    t = run(e, 1, 0.0, 661.0, 100.0, v_kph=300.0)
    assert fired == []
    e.on_frame(frame(1, 710.0, t + 0.6, 300.0), t + 0.6)
    run(e, 1, 711.0, LENGTH, t + 0.61, v_kph=300.0)
    assert fired == [] and e.missed == 1
    laps(e, 1, v_kph=300.0, start_lap=2)  # the next lap is on time again
    assert [ev.lap for ev in fired] == [2]


def test_reminder_from_a_plan_that_arrives_mid_approach_is_dropped() -> None:
    v = 250 / 3.6
    e, fired = habit_engine([low("T1")], v=v)
    plan = e.plan
    e.set_plan(None)
    t = run(e, 1, 0.0, 900.0, 100.0, v_kph=250.0)  # 1.4 s before the point when the plan lands: no room left
    e.set_plan(plan)
    run(e, 1, 900.0, LENGTH, t, v_kph=250.0)
    assert fired == [] and e.missed == 1


def test_a_longer_measured_phrase_starts_the_reminder_earlier() -> None:
    """The hub measured the pre-synthesised phrase at 3.0 s (longer than the 2.61 s estimate): the reminder starts
    4.0 s before its point. A shorter measurement never makes it start later than planned."""
    e, fired = habit_engine([low("T1")], durations={APEX: 3.0})
    laps(e, 1)
    (ev,) = fired
    assert ev.lead_anticipation_s == pytest.approx(4.0)
    assert _speech_end_spare_s(ev, 0.3, 3.0, V) >= REMINDER_END_MARGIN_S
    e2, fired2 = habit_engine([low("T1")], durations={APEX: 1.0})
    laps(e2, 1)
    assert fired2[0].lead_anticipation_s == pytest.approx(APEX_S + REMINDER_END_MARGIN_S)
    assert CueTiming(durations_s={APEX: float("nan")}).anticipation(fired2[0].cue) == fired2[0].cue.anticipation_s


def test_a_measured_phrase_longer_than_the_calm_stretch_is_suppressed() -> None:
    """The reference was off the brakes for 5 s before T1; the radio's phrase turned out to need 4.5 s + 1 s: it would
    start inside the previous braking zone. Suppressed (never said there), counted, nothing fired."""
    d = np.arange(0.0, LENGTH, 1.0)
    brake = np.where((d >= 400.0) & (d < 1000.0 - 5.0 * V), 1.0, 0.0)
    trace = DistanceTrace(d=d, t_s=d / V, ch={"speed_kph": np.full_like(d, V * 3.6), "brake": brake}, lap_number=3)
    e, fired = habit_engine([low("T1")], trace=trace, durations={APEX: 4.5})
    (spec,) = e.plan.cues
    assert spec.calm_s == pytest.approx(5.0, abs=0.02)
    laps(e, 1)
    assert fired == [] and e.suppressed == 1 and e.missed == 0


@pytest.mark.parametrize(
    "case",
    ["muted", "safety_car", "pit", "standing_start"],
)
def test_reminders_follow_every_cue_suppression_rule(case: str) -> None:
    e, fired = habit_engine([low("T1")])
    if case == "muted":
        e.set_muted("minimal radio (quiet intensity)")  # the hub's gate at quiet intensity
        laps(e, 1)
    elif case == "safety_car":
        e.on_session_info("virtual")
        laps(e, 1)
    elif case == "pit":
        run(e, 2, 0.0, LENGTH, 100.0, pit=1)  # an out lap
    else:
        run(e, 1, 100.0, LENGTH, 100.0, lap_t0_ms=0)  # the grid: lap 1 first seen past the line at ~0 lap time
    assert [ev for ev in fired if ev.lap <= 2] == []


def test_one_reminder_per_corner_per_lap_over_many_laps() -> None:
    e, fired = habit_engine([low("T1"), habit("T2")])
    laps(e, 5)
    per_lap: dict[tuple[int, str, str], int] = {}
    for ev in fired:
        key = (ev.lap, ev.cue.corner, ev.cue.kind.value)
        per_lap[key] = per_lap.get(key, 0) + 1
    assert per_lap == {(lap, c, k): 1 for lap in range(1, 6) for c, k in (("T1", "reminder"), ("T2", "brake"))}


# ============================================================================================== speak window
def test_speak_window_closes_before_a_reminder_starts() -> None:
    """Routine talk must end before a reminder STARTS (its length plus a second before the braking point), not just
    before the braking point."""
    e, _ = habit_engine([low("T1")], latency=0.3)
    run(e, 1, 0.0, 200.0, 100.0)
    s = e.sample()
    assert s is not None
    due = e.seconds_to_next_cue()
    lead = 0.3 + APEX_S + REMINDER_END_MARGIN_S
    assert due == pytest.approx((1000.0 - s.d_m) / V - lead - MARGIN_M / V, abs=1e-6)
    calm = DrivingState(True, V * 3.6, 0.0, 0.0, 1, s.d_m, time_to_next_braking_s=due)
    longest = due - SPEAK_WINDOW_MARGIN_S
    assert speak_window_ok(calm, longest - 0.05) and not speak_window_ok(calm, longest + 0.05)
    to_point = (1000.0 - s.d_m) / V
    assert speak_window_ok(calm, to_point - 1.5) is False  # would have fitted before the point, not before the start


def test_speak_window_sees_a_reminder_that_starts_before_a_closer_braking_call() -> None:
    """Lookahead: T1's braking call is the next cue by distance, but T2's reminder (a 3.8 s lead) starts first."""
    spec_brake = CueSpec("T1", CueKind.BRAKE, 1000.0, "T1 brake", ("brake",), 0)
    spec_rem = CueSpec("T2", CueKind.REMINDER, 1150.0, "T2: apex speed, 12 down", APEX, 0, APEX_S + 1.0, calm_s=9.0)
    base = build_cue_plan("all", comparison({"T1": 1000.0, "T2": 1150.0}), length_m=LENGTH, reference=reference(),
                          trace=flat_trace())  # fmt: skip
    plan = CuePlan(
        mode="focus",
        cues=(spec_brake, spec_rem),
        approaches=base.approaches,
        targets=(1000.0, 1150.0),
        length_m=LENGTH,
        ref_lap_id=REF_ID,
    )
    e = CueEngine("focus")
    e.set_plan(plan)
    e.set_timing(CueTiming(latency_s=0.3))
    fired: list[CueEvent] = []
    e.set_sink(fired.append)
    run(e, 1, 0.0, 500.0, 100.0)
    s = e.sample()
    assert s is not None
    due = e.seconds_to_next_cue()
    rem_due = (1150.0 - s.d_m) / V - (0.3 + APEX_S + 1.0) - MARGIN_M / V
    brake_due = (1000.0 - s.d_m) / V - 0.3 - MARGIN_M / V
    assert rem_due < brake_due and due == pytest.approx(rem_due, abs=1e-6)
    run(e, 1, 500.0, LENGTH, 110.0)
    assert [ev.cue.corner for ev in fired] == ["T2", "T1"]  # the reminder really went first


# ============================================================================================== radio hub
async def test_hub_presynthesises_reminder_parts_and_pushes_their_length() -> None:
    hub, _client, _sent, tts = await make_hub("focus")
    install_plan(hub, [low("T1"), habit("T2")])
    await settle()
    assert sorted(tts.calls) == ["apex speed, 12 down", "brake", "turn 1", "turn 2"]
    clip, offset = hub._cue_phrases[APEX]
    assert offset == 0.0
    timing = hub.cues.timing
    assert timing.durations_s[APEX] == pytest.approx(clip.duration_s)  # the measured phrase
    assert ("T2", "brake") not in timing.durations_s  # a braking call is timed by its key word, not its end
    assert clip.duration_s < APEX_S  # this voice is quicker than the estimate: the estimate stands
    assert timing.anticipation(hub.cues.plan.cues[0]) == pytest.approx(APEX_S + REMINDER_END_MARGIN_S)
    await hub.stop()


async def test_device_voices_time_a_reminder_by_its_spoken_words() -> None:
    hub, _client, _sent, tts = await make_hub("focus", device=True, tts=CountingTts())
    install_plan(hub, [low("T1")])
    await settle()
    assert tts.calls == []
    # "turn 1, apex speed, 12 down": six words at 2.6 words/s plus the device's pause at each comma
    assert hub.cues.timing.durations_s[APEX] == pytest.approx(6 / WORDS_PER_S + 2 * 0.15)
    await hub.stop()


async def test_hub_says_a_reminder_from_the_ingest_hook() -> None:
    hub, _client, sent, _ = await make_hub("focus")
    install_plan(hub, [low("T1")])
    await settle()
    v, dt, d, t = V, 1 / 60, 0.0, 10.0
    while d < 1100.0:
        hub.live.on_frame(frame(3, d, t))
        d, t = d + v * dt, t + dt
    await settle(5)
    (say,) = says(sent, "cue")
    assert say["text"] == "T1: apex speed, 12 down" and say["speech"] == "turn 1, apex speed, 12 down"
    assert say["meta"]["cue"] == "reminder" and say["meta"]["corner"] == "T1" and say["meta"]["focus"] is True
    assert say["n_bytes"] > 0 and hub.cues.snapshot()["last"]["kind"] == "reminder"
    await hub.stop()


async def test_quiet_intensity_mutes_reminders() -> None:
    hub, client, sent, _ = await make_hub("focus")
    install_plan(hub, [low("T1")])
    await settle()
    await hub.on_text(client, {"type": "settings", "intensity": "quiet"})
    assert hub.cues.snapshot()["muted"] == "minimal radio (quiet intensity)"
    assert hub.cues.seconds_to_next_cue() is None  # nothing will be said: no speak window to protect
    v, dt, d, t = V, 1 / 60, 0.0, 10.0
    while d < 1100.0:
        hub.live.on_frame(frame(3, d, t))
        d, t = d + v * dt, t + dt
    await settle(5)
    assert says(sent, "cue") == [] and hub.cues.suppressed == 1
    await hub.stop()


async def test_a_reminder_handed_over_after_its_deadline_is_dropped() -> None:
    hub, _client, sent, _ = await make_hub("focus")
    install_plan(hub, [low("T1")])
    await settle()
    (spec,) = hub.cues.plan.cues
    now = time.monotonic()
    ev = CueEvent(1, spec, 3, 3, now - 0.2, None, 600.0, V, spec.anticipation_s + 0.35, 0.3, 0.0, "pcm", 0.0, REF_ID)
    assert ev.deadline_mono == pytest.approx(now - 0.2 + 0.05)  # 50 ms of slack when it fired
    assert hub.deliver_cue(ev, now) == "late hand-off"
    await settle(3)
    assert says(sent, "cue") == []
    await hub.stop()


def test_policy_row_names_braking_calls_and_corner_reminders() -> None:
    row = POLICY_BY_KEY["cue"]
    assert row.label == "Braking calls and corner reminders" and row.setting == "Braking calls"
    assert "corner reminder" in row.note and "ends 1 s before" in row.note
    assert f"{REMINDER_END_MARGIN_S:.0f} s" in row.note
