"""Habits (spec: habits and corner reminders, sections 1, 3 and 5): one definition of a habit, the per-session habit
tracker (``coach.habits``), the coach block contract and the radio's wording of its events.

Deterministic and pure: observation dicts are built by hand here; tests/synthetic/test_habit_memory.py runs the
same through the real pipeline on a SYNTHETIC session.
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any

import pytest

from pitwall.analysis import coaching
from pitwall.analysis.coaching import (
    BIG_ONE_OFF_CONFIDENCE,
    BIG_ONE_OFF_S,
    HABIT_MIN_LAPS,
    HABIT_RATIO,
    MIN_TIME_LOSS_S,
    Observation,
    is_big_one_off,
    is_corrective,
    is_habit,
    keeps_point,
    observations_for_comparison,
)
from pitwall.analysis.compare import (
    Compatibility,
    CornerDelta,
    CornerMetrics,
    LapComparison,
    analyse_lap,
    compare,
    corner_delta,
)
from pitwall.analysis.distance import to_distance_domain
from pitwall.analysis.track import build_track_model
from pitwall.coach.cues import CueEngine
from pitwall.coach.habits import (
    EVENT_ORDER,
    HABIT_WINDOW,
    STILL_AFTER,
    HabitTracker,
    focus_slots,
    progress_amount,
    reminder,
    reminder_phrase,
)
from pitwall.coach.selection import COACH_FIELDS, CoachSelection, coach_block
from pitwall.core.lap_processor import _HistoryEntry, _rebase_history, _SessionCache
from pitwall.core.live import LiveState
from pitwall.drivers import coaching_limits
from pitwall.voice import proactive
from pitwall.voice.proactive import lap_messages
from pitwall.voice.types import MessageKind
from tests.conftest import DecodedSession

LATER_BRAKING_ADVICE = re.compile(r"\b(brake|braking) (a bit |a little |even )?later\b(?! (than|but|did|now))", re.I)
COMP = {"compatibility": {"ok": True, "blocking": [], "warnings": []}}


# ---------------------------------------------------------------------------------------------- section 1
def test_the_constants_live_in_one_place() -> None:
    assert (HABIT_RATIO, HABIT_MIN_LAPS, BIG_ONE_OFF_S, BIG_ONE_OFF_CONFIDENCE) == (0.6, 3, 0.30, 0.8)
    assert proactive.HABIT_RATIO is HABIT_RATIO  # the radio imports it, it does not define its own


def test_predicates_on_observation_dicts() -> None:
    o = {"kind": "brake_early", "positive": False, "impact_s": 0.31, "confidence": 0.8, "consistency_ratio": None}
    assert is_corrective(o) and not is_habit(o) and is_big_one_off(o)
    assert not is_big_one_off({**o, "impact_s": 0.29}) and not is_big_one_off({**o, "confidence": 0.79})
    assert not is_big_one_off({**o, "impact_s": None}) and not is_big_one_off({**o, "confidence": None})
    habit = {**o, "consistency_ratio": 0.6}
    assert is_habit(habit) and not is_big_one_off(habit)  # a habit is never a one-off
    assert not is_habit({**o, "consistency_ratio": 0.59})
    for not_corrective in ({**habit, "positive": True}, {**habit, "kind": "incident"}):
        assert not is_corrective(not_corrective) and not is_habit(not_corrective)
        assert not is_big_one_off(not_corrective)
    assert not is_habit({**o, "consistency_ratio": True})  # not a number


def _obs(kind: str, impact: float | None, positive: bool = False, ratio: float | None = None) -> Observation:
    return Observation(
        id="x",
        kind=kind,
        corner="T1",
        lap_number=2,
        ref_lap_number=1,
        metric="m",
        value=-10.0,
        unit="m",
        impact_s=impact,
        confidence=0.8,
        text="t",
        consistency_ratio=ratio,
        positive=positive,
    )


def test_priority_ranks_a_corrective_point_by_the_time_it_lost() -> None:
    assert _obs("brake_early", 0.2).priority == pytest.approx(0.16)
    assert _obs("brake_early", -0.2).priority == 0.0  # it gained time: never a big fix
    assert _obs("brake_early", 0.2, ratio=1.0).priority == pytest.approx(0.16)  # the consistency boost is unchanged
    assert _obs("brake_early", 0.2, ratio=0.0).priority == pytest.approx(0.16 * 0.6)
    assert _obs("exit_gain", -0.2, positive=True).priority == pytest.approx(0.08)  # praise: the gain, half weight


def test_the_loss_guard_itself() -> None:
    """Every rule checks its loss; ``keeps_point`` makes it structural for any future rule."""
    assert not keeps_point(_obs("brake_early", None))
    assert not keeps_point(_obs("brake_early", MIN_TIME_LOSS_S - 0.001))
    assert not keeps_point(_obs("future_rule", -0.3))
    assert keeps_point(_obs("brake_early", MIN_TIME_LOSS_S))
    assert keeps_point(_obs("exit_gain", -0.1, positive=True)) and keeps_point(_obs("incident", 3.0))


def test_observations_pass_through_the_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def spy(o: Observation) -> bool:
        calls.append(o.kind)
        return o.kind != "brake_early"

    monkeypatch.setattr(coaching, "keeps_point", spy)
    m = CornerMetrics(corner="T1", segment_time_s=10.0, min_speed_kph=100.0)
    cd = CornerDelta("T1", 0.11, -12.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, m, m)
    comp = LapComparison(1, 2, 0.1, [], [], [cd], Compatibility(ok=True))
    assert observations_for_comparison(comp) == [] and calls == ["brake_early"]


def test_consistency_needs_habit_min_laps() -> None:
    m = CornerMetrics(corner="T1", segment_time_s=10.0, min_speed_kph=100.0)

    def cd(bp: float) -> CornerDelta:
        return CornerDelta("T1", 0.11, bp, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, m, m)

    comp = LapComparison(1, 2, 0.1, [], [], [cd(-12.0)], Compatibility(ok=True))
    (o,) = observations_for_comparison(comp, history={"T1": [cd(-12.0)]})  # two values: unknown
    assert o.consistency_ratio is None
    (o,) = observations_for_comparison(comp, history={"T1": [cd(-12.0)] * (HABIT_MIN_LAPS - 1)})
    assert o.consistency_ratio == 1.0 and o.consistency == "3 of the last 3 laps"


def test_corner_delta_is_what_compare_does(demo_session: DecodedSession) -> None:
    laps = [lap for lap in demo_session.laps if lap.clean]
    length = demo_session.info.track_length_m
    assert length is not None
    model = build_track_model("f1", "t", None, length, [to_distance_domain(lap, length) for lap in laps[:2]])
    ref, cur = analyse_lap(demo_session.laps[0], model), analyse_lap(demo_session.laps[2], model)
    comp = compare(ref, cur, Compatibility(ok=True))
    assert comp.corners and comp.corners == [corner_delta(c.corner, ref.corners[c.corner], c.cmp) for c in comp.corners]


# ---------------------------------------------------------------------------------------------- section 2 (pure part)
def _metrics(brake: float) -> CornerMetrics:
    return CornerMetrics(corner="T1", segment_time_s=10.0, brake_start_m=brake, min_speed_kph=100.0)


def test_rebase_keeps_habits_against_a_new_reference() -> None:
    old_ref = _metrics(500.0)
    sc = _SessionCache()
    for lap_id, brake in ((2, 488.0), (3, 487.0), (4, 500.0), (5, 499.0)):
        sc.history.setdefault("T1", []).append(_HistoryEntry(lap_id, 3, corner_delta("T1", old_ref, _metrics(brake))))
    sc.history["T9"] = [_HistoryEntry(2, 3, corner_delta("T9", old_ref, _metrics(480.0)))]
    sc.history["T1"].insert(0, _HistoryEntry(1, 2, corner_delta("T1", old_ref, _metrics(470.0))))  # older model
    sc.history_ref = 1
    new_ref = SimpleNamespace(corners={"T1": _metrics(501.0)})  # lap 5 is the new best
    _rebase_history(sc, 5, new_ref, 3)  # type: ignore[arg-type]
    t1 = sc.history["T1"]
    assert [e.lap_id for e in t1] == [2, 3, 4]  # the new reference itself and the other model's lap are gone
    assert [e.delta.brake_point_delta_m for e in t1] == [-13.0, -14.0, -1.0]  # re-based on the new reference
    assert "T9" not in sc.history and sc.history_ref == 5  # a corner the new reference lacks is dropped
    before = list(t1)
    _rebase_history(sc, 5, new_ref, 3)  # type: ignore[arg-type]
    assert sc.history["T1"] == before  # the same reference: nothing to do


# ---------------------------------------------------------------------------------------------- section 3: tracker
def pt(
    corner: str,
    kind: str,
    lap: int,
    value: float = -12.0,
    impact: float = 0.25,
    conf: float = 0.9,
    ratio: float | None = 0.8,
) -> dict[str, Any]:
    """An observation dict (``Observation.to_dict()`` shape)."""
    return {
        "id": f"L{lap}:{corner}:{kind}",
        "kind": kind,
        "corner": corner,
        "corner_label": corner,
        "corner_voice": f"Turn {corner[1:]}",
        "lap_number": lap,
        "ref_lap_number": 1,
        "metric": "min_speed_delta_kph",
        "value": value,
        "unit": "km/h",
        "impact_s": impact,
        "confidence": conf,
        "priority": round(impact * conf, 4),
        "positive": False,
        "consistency": None if ratio is None else "some laps",
        "consistency_ratio": ratio,
        "text": f"{corner}: minimum speed is {abs(value):.0f} km/h lower than your reference.",
        "text_simple": f"{corner}: you were {abs(value):.0f} km/h slower at the slowest point of the corner.",
        "short": f"{corner}: {abs(value):.0f} km/h slower mid-corner",
        "evidence": {"time_delta_s": impact},
    }


CORNERS = ["T1", "T2", "T3", "T4", "T5", "T6"]


def drive(
    tr: HabitTracker, lap: int, *points: dict[str, Any], slots: int = 1, commit: bool = True
) -> list[dict[str, Any]]:
    """One compared lap of every corner; the radio picks (commits) every event."""
    events = tr.update(lap, list(points), CORNERS, slots=slots)
    if commit:
        tr.commit(events)
    return events


def kinds(events: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return [(e["corner"], e["habit_event"]) for e in events]


def test_a_habit_is_announced_improves_and_is_sorted() -> None:
    tr = HabitTracker()
    assert drive(tr, 1, pt("T6", "low_min_speed", 1, ratio=None)) == []  # consistency unknown: a one-off
    assert drive(tr, 2, pt("T6", "low_min_speed", 2, ratio=None)) == []
    (ann,) = drive(tr, 3, pt("T6", "low_min_speed", 3, value=-14.0, ratio=1.0))
    assert ann["habit_event"] == "announce" and ann["id"] == "L3:T6:low_min_speed:announce"
    assert ann["consistency"] == "3 of the last 3 laps" and ann["value"] == -14.0 and ann["impact_s"] == 0.25
    assert tr.focus()[0]["corner"] == "T6" and tr.habit_info("T6", "low_min_speed") == {
        "status": "focus",
        "laps_seen": 3,
        "laps": 3,
    }
    assert drive(tr, 4, pt("T6", "low_min_speed", 4, value=-13.0)) == []  # in focus: not repeated in full
    (better,) = drive(tr, 5, pt("T6", "low_min_speed", 5, value=-6.0, impact=0.06, conf=0.7))
    assert better["habit_event"] == "improving" and better["value"] == -6.0 and better["was_value"] == -14.0
    assert (better["impact_s"], better["confidence"]) == (0.25, 0.9)  # the announcement's: its floors still pass
    assert drive(tr, 6, pt("T6", "low_min_speed", 6, value=-5.0)) == []  # "better" is said once
    assert drive(tr, 7) == []  # one clean lap: not sorted yet
    (fixed,) = drive(tr, 8)
    assert fixed["habit_event"] == "fixed" and (fixed["clean_laps"], fixed["clean_of"]) == (2, 3)
    assert fixed["text"] == "T6: sorted - clean on 2 of the last 3 laps." and fixed["short"] == "T6: sorted"
    assert tr.focus() == [] and [h["status"] for h in tr.habits()] == ["fixed"]
    for _ in range(HABIT_WINDOW):
        drive(tr, 9)
    assert tr.habits() == []  # a clean window: forgotten


def test_sorted_needs_two_clean_laps_after_the_announcement() -> None:
    """F F C F(announce) C: the gap inside "3 of the last 4" is no proof of a fix; two laps after it are."""
    tr = HabitTracker()
    drive(tr, 1, pt("T3", "brake_early", 1, ratio=None))
    drive(tr, 2, pt("T3", "brake_early", 2, ratio=None))
    drive(tr, 3)
    assert kinds(drive(tr, 4, pt("T3", "brake_early", 4, ratio=0.75))) == [("T3", "announce")]
    assert drive(tr, 5) == []  # clean on 2 of the last 3, but only one lap since the announcement
    assert kinds(drive(tr, 6)) == [("T3", "fixed")]


def test_still_after_five_laps_without_progress() -> None:
    tr = HabitTracker()
    for lap in (1, 2):
        drive(tr, lap, pt("T2", "late_throttle", lap, value=40.0, ratio=None))
    assert kinds(drive(tr, 3, pt("T2", "late_throttle", 3, value=40.0))) == [("T2", "announce")]
    said = {lap: kinds(drive(tr, lap, pt("T2", "late_throttle", lap, value=38.0))) for lap in range(4, 14)}
    assert said[3 + STILL_AFTER] == [("T2", "still")] and said[3 + 2 * STILL_AFTER] == [("T2", "still")]
    assert sum(len(v) for v in said.values()) == 2  # once per STILL_AFTER laps


def _three_laps(tr: HabitTracker, *points: dict[str, Any], slots: int = 1, commit: bool = True) -> list[Any]:
    for lap in (1, 2):
        drive(tr, lap, *({**p, "lap_number": lap, "consistency_ratio": None} for p in points), slots=slots)
    return drive(tr, 3, *points, slots=slots, commit=commit)


def test_slots_one_focus_per_corner_and_biggest_first() -> None:
    small, big = pt("T1", "brake_early", 3, impact=0.1), pt("T4", "late_throttle", 3, impact=0.4)
    assert kinds(_three_laps(HabitTracker(), small, big)) == [("T4", "announce")]
    assert kinds(_three_laps(HabitTracker(), small, big, slots=2)) == [("T4", "announce"), ("T1", "announce")]
    same_corner = pt("T4", "low_min_speed", 3, impact=0.4)
    tr = HabitTracker()
    assert kinds(_three_laps(tr, big, same_corner, slots=2)) == [("T4", "announce")]  # one focus per corner
    assert [h["status"] for h in tr.habits()] == ["focus", "seen"]
    tr = HabitTracker()
    assert _three_laps(tr, small, big, slots=0) == []  # quiet radio: tracked, not announced
    assert [h["status"] for h in tr.habits()] == ["seen", "seen"]


def test_an_announcement_the_radio_did_not_pick_waits() -> None:
    tr = HabitTracker()
    assert kinds(_three_laps(tr, pt("T5", "coasting", 3), commit=False)) == [("T5", "announce")]
    assert tr.focus() == [] and tr.habits()[0]["status"] == "seen"
    assert kinds(drive(tr, 4, pt("T5", "coasting", 4))) == [("T5", "announce")]  # proposed again
    assert tr.focus()[0]["corner"] == "T5"


def test_eligible_lets_the_next_habit_take_the_slot() -> None:
    tr = HabitTracker()
    pts = [pt("T1", "coasting", 3, impact=0.4), pt("T2", "brake_early", 3, impact=0.2)]
    for lap in (1, 2):
        tr.update(lap, [{**p, "lap_number": lap, "consistency_ratio": None} for p in pts], CORNERS)
    events = tr.update(3, pts, CORNERS, slots=1, eligible=lambda e: e["kind"] != "coasting")
    assert kinds(events) == [("T2", "announce")]


def test_fewer_slots_demote_the_smaller_focus() -> None:
    tr = HabitTracker()
    small, big = pt("T1", "brake_early", 3, impact=0.1), pt("T4", "late_throttle", 3, impact=0.4)
    _three_laps(tr, small, big, slots=2)
    assert [f["corner"] for f in tr.focus()] == ["T4", "T1"]
    drive(tr, 4, {**small, "lap_number": 4}, {**big, "lap_number": 4}, slots=1)
    assert [f["corner"] for f in tr.focus()] == ["T4"]
    drive(tr, 5, {**small, "lap_number": 5}, {**big, "lap_number": 5}, slots=0)  # quiet keeps the focus
    assert [f["corner"] for f in tr.focus()] == ["T4"]


def test_incidents_and_uncompared_corners_are_not_laps_of_the_corner() -> None:
    tr = HabitTracker()
    for lap in (1, 2):
        drive(tr, lap, pt("T3", "brake_early", lap, ratio=None))
    incident = {**pt("T3", "incident", 3), "kind": "incident"}
    assert drive(tr, 3, incident) == []
    assert tr.update(4, [], ["T1"]) == []  # T3 not in the comparison
    assert kinds(drive(tr, 5, pt("T3", "brake_early", 5))) == [("T3", "announce")]
    assert tr.habits()[0]["laps"] == 3  # laps 1, 2 and 5
    # unknown corners: only corners with a point count as compared
    tr2 = HabitTracker()
    for lap in (1, 2, 3):
        tr2.update(lap, [pt("T3", "brake_early", lap, ratio=None if lap < 3 else 1.0)], None)
    assert tr2.habits()[0]["laps"] == 3


def test_the_window_includes_the_clean_laps_before_the_first_fault() -> None:
    tr = HabitTracker()
    drive(tr, 1)
    drive(tr, 2)
    for lap in (3, 4):
        drive(tr, lap, pt("T6", "low_min_speed", lap, ratio=None))
    (ann,) = drive(tr, 5, pt("T6", "low_min_speed", 5, ratio=0.6))
    assert ann["consistency"] == "3 of the last 5 laps"  # as the analysis counts it, not "3 of the last 3"


def test_a_habit_the_window_does_not_back_is_not_announced() -> None:
    tr = HabitTracker()  # the analysis says habit, but this tracker saw one lap of the corner: nothing to back it
    assert drive(tr, 5, pt("T6", "low_min_speed", 5, ratio=1.0)) == [] and tr.habits() == []


def test_a_new_best_with_the_same_fault_never_makes_it_sorted() -> None:
    """Reference-relative evidence: a new best set with the habit cannot show it, so laps compared with it (and with
    any lap that could not show it either) are not counted; after a whole window of that the habit is forgotten
    without a word, never called sorted."""
    tr = HabitTracker()

    def lap(n: int, ref: int, *points: dict[str, Any]) -> list[dict[str, Any]]:
        events = tr.update(n, list(points), CORNERS, lap_id=100 + n, ref_lap_id=100 + ref)
        tr.commit(events)
        return events

    for n in (2, 3):
        lap(n, 1, pt("T2", "brake_early", n, ratio=None))
    assert kinds(lap(4, 1, pt("T2", "brake_early", 4))) == [("T2", "announce")]
    assert lap(5, 4) == [] and lap(6, 4) == []  # lap 4 (with the fault) is the new best: no evidence of a fix
    assert lap(7, 6) == []  # lap 6 could not show it either
    assert tr.habits()[0]["laps"] == 3 and tr.focus()  # not counted, still the focus
    assert lap(8, 6) == []
    assert lap(9, 6) == [] and tr.habits() == []  # a whole window unmeasurable: forgotten, the slot is free
    # against a clean reference the same laps would have been a fix
    tr = HabitTracker()
    for n in (2, 3):
        lap(n, 1, pt("T2", "brake_early", n, ratio=None))
    lap(4, 1, pt("T2", "brake_early", 4))
    assert lap(5, 1) == [] and kinds(lap(6, 1)) == [("T2", "fixed")]


def test_repeated_is_a_pattern_in_the_making() -> None:
    tr = HabitTracker()
    drive(tr, 1, pt("T2", "brake_early", 1, ratio=None))
    assert not tr.repeated("T2", "brake_early")
    drive(tr, 2, pt("T2", "brake_early", 2, ratio=None))
    assert tr.repeated("T2", "brake_early")
    drive(tr, 3)
    assert not tr.repeated("T2", "brake_early") and not tr.repeated("T9", "x")


def test_focus_slots_follow_the_radio() -> None:
    assert focus_slots(coaching_limits("advanced", "normal"), quiet=False) == 1
    assert focus_slots(coaching_limits("intermediate", "detailed"), quiet=False) == 2
    assert focus_slots(coaching_limits("beginner", "detailed"), quiet=False) == 1
    assert focus_slots(coaching_limits("advanced", "detailed"), quiet=True) == 0
    assert focus_slots(coaching_limits("advanced", "quiet"), quiet=False) == 0


def test_reminder_phrases_are_descriptive_and_rounded() -> None:
    assert reminder_phrase("low_min_speed", -12.4) == "apex speed, 12 down"
    assert reminder_phrase("late_throttle", 38.0) == "throttle, 40 metres late"
    assert reminder_phrase("coasting", 27.0) == "coasting, 25 metres"
    assert reminder_phrase("brake_early", -12.0) is None  # braking habits get a braking call, not a reminder
    assert reminder_phrase("low_min_speed", None) is None
    entry = {"corner": "T6", "corner_label": "T6", "corner_voice": "Turn 6", "kind": "low_min_speed", "value": -12.0}
    assert reminder(entry) == {"parts": ["Turn 6", "apex speed, 12 down"], "text": "T6: apex speed, 12 down"}
    for kind in ("brake_early", "brake_late_overdrive", "low_min_speed", "overspeed_apex", "late_throttle"):
        for v in (-14.0, 14.0):
            amount = progress_amount(kind, v)
            assert amount is not None and not LATER_BRAKING_ADVICE.search(f"{amount} now"), amount


def test_habit_and_focus_entries() -> None:
    tr = HabitTracker()
    for lap, v in ((1, -10.0), (2, -14.0)):
        drive(tr, lap, pt("T6", "low_min_speed", lap, value=v, impact=0.2, ratio=None))
    drive(tr, 3, pt("T6", "low_min_speed", 3, value=-12.0, impact=0.3))
    (entry,) = tr.habits()
    assert entry == {
        "corner": "T6",
        "corner_label": "T6",
        "corner_voice": "Turn 6",
        "kind": "low_min_speed",
        "status": "focus",
        "laps_seen": 3,
        "laps": 3,
        "value": -12.0,  # median of the laps it fired
        "unit": "km/h",
        "impact_s": 0.233,  # mean
        "since_lap": 3,
        "short": "T6: 12 km/h slower mid-corner",
    }
    (focus,) = tr.focus()
    assert focus["reminder"] == {"parts": ["Turn 6", "apex speed, 12 down"], "text": "T6: apex speed, 12 down"}


def test_events_come_in_the_spec_order_and_never_advise_later_braking() -> None:
    assert EVENT_ORDER == ("fixed", "improving", "announce", "still")
    tr = HabitTracker()
    a, b = pt("T1", "brake_late_overdrive", 3, value=12.0, impact=0.4), pt("T2", "low_min_speed", 3, impact=0.3)
    _three_laps(tr, a, b, slots=2)
    c = pt("T3", "coasting", 4, value=30.0, impact=0.2)
    for lap in (4, 5):
        pts = [{**a, "lap_number": lap, "value": 5.0}, {**c, "lap_number": lap, "consistency_ratio": None}]
        drive(tr, lap, *pts, *([{**b, "lap_number": 4}] if lap == 4 else []), slots=2)
    events = drive(tr, 6, {**c, "lap_number": 6}, slots=2)  # T2 sorted, T3 takes the free slot
    assert kinds(events) == [("T2", "fixed"), ("T3", "announce")]
    for e in events:
        assert set(COACH_FIELDS) <= set(e) and e["lap_number"] == 6 and e["positive"] is False
        for t in (e["text"], e["text_simple"], e["short"]):
            assert t and not LATER_BRAKING_ADVICE.search(t), t


# ---------------------------------------------------------------------------------------------- selection + block
def lap_points(lap: int, *points: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return {"lap_id": 100 + lap, "lap_number": lap}, [{**p, "lap_number": lap} for p in points]


def test_the_block_carries_habits_focus_and_tags() -> None:
    sel = CoachSelection()
    sel.set_limits(None, None)
    habit = pt("T6", "low_min_speed", 0, impact=0.25)
    small = pt("T2", "coasting", 0, value=20.0, impact=0.05, ratio=None)
    for lap in (1, 2):
        sel.select(*lap_points(lap, {**habit, "consistency_ratio": None}), compared=True, corners=CORNERS)
    block = sel.select(*lap_points(3, habit, small), compared=True, corners=CORNERS)
    (p,) = block["picked"]
    assert p["habit_event"] == "announce" and p["habit"] == {"status": "focus", "laps_seen": 3, "laps": 3}
    assert p["one_off"] is False and block["by_corner"]["T6"]["id"] == p["id"]
    assert block["by_corner"]["T2"]["one_off"] is True and block["by_corner"]["T2"]["habit"] is None
    assert [h["corner"] for h in block["habits"]] == ["T6"] and block["focus"][0]["reminder"]["text"] == (
        "T6: apex speed, 12 down"
    )
    # next lap the focus habit is not said again, even as big as a one-off
    big = {**habit, "impact_s": 0.5, "confidence": 0.95, "consistency_ratio": 0.4}
    block = sel.select(*lap_points(4, big), compared=True, corners=CORNERS)
    assert block["picked"] == [] and block["by_corner"]["T6"]["habit"]["status"] == "focus"


def test_a_big_fault_two_laps_running_is_said_once() -> None:
    sel = CoachSelection()
    big = pt("T2", "brake_early", 0, value=-13.0, impact=0.34, conf=0.85, ratio=None)
    first = sel.select(*lap_points(1, big), compared=True, corners=CORNERS)
    assert [p["kind"] for p in first["picked"]] == ["brake_early"] and first["picked"][0]["one_off"]
    second = sel.select(*lap_points(2, {**big, "consistency_ratio": 0.5}), compared=True, corners=CORNERS)
    assert second["picked"] == []  # not the same sentence two laps running
    third = sel.select(*lap_points(3, {**big, "consistency_ratio": 0.67}), compared=True, corners=CORNERS)
    assert [p["habit_event"] for p in third["picked"]] == ["announce"]  # the habit, once it is one


def test_the_tracker_follows_the_session_and_the_seat_not_profile_edits() -> None:
    def three(sel: CoachSelection, first: int) -> dict[str, Any]:
        for lap in (first, first + 1):
            sel.select(*lap_points(lap, pt("T6", "low_min_speed", 0, ratio=None)), compared=True, corners=CORNERS)
        return sel.select(*lap_points(first + 2, pt("T6", "low_min_speed", 0)), compared=True, corners=CORNERS)

    sel = CoachSelection()
    sel.set_limits(1, coaching_limits("advanced"))
    assert three(sel, 1)["focus"]
    sel.set_limits(1, coaching_limits("intermediate"))  # the same driver edits their profile: habits stay
    assert sel.select(*lap_points(4, pt("T6", "low_min_speed", 0)), compared=True)["focus"]
    sel.set_limits(2, coaching_limits("advanced"))  # someone else in the seat
    assert sel.select(*lap_points(5, pt("T6", "low_min_speed", 0)), compared=True)["habits"] == []
    assert three(sel, 6)["focus"]
    sel.reset()  # a new session
    assert sel.select(*lap_points(9, pt("T6", "low_min_speed", 0)), compared=True)["habits"] == []


def test_uncompared_and_drill_laps_do_not_update_the_tracker() -> None:
    sel = CoachSelection()
    for lap in (1, 2, 3):
        block = sel.select(*lap_points(lap, pt("T6", "low_min_speed", 0)), compared=False, corners=CORNERS)
    assert block["habits"] == [] and block["picked"] == []


def test_without_a_tracker_the_block_is_stateless() -> None:
    block = coach_block({"lap_id": 1, "lap_number": 5}, [pt("T6", "low_min_speed", 5)], coaching_limits("advanced"))
    (p,) = block["picked"]
    assert p["habit_event"] is None and p["habit"] is None and not p["one_off"]  # a habit, said as it is
    assert block["habits"] == [] and block["focus"] == []


# ---------------------------------------------------------------------------------------------- live state + cues
def test_live_state_passes_corners_focus_and_habits_on() -> None:
    live = LiveState()
    calls: list[dict[str, Any]] = []
    original = live.cues.on_lap_result

    def spy(*args: Any, **kw: Any) -> None:
        calls.append(kw)
        original(*args, **kw)

    live.cues.on_lap_result = spy  # type: ignore[method-assign]
    live.reset_session("s1", "test", False)
    comp = {**COMP, "corners": [{"corner": c} for c in CORNERS], "ref_lap_id": 1}
    for lap in (1, 2):
        live.on_lap_result(*lap_points(lap, pt("T6", "low_min_speed", 0, ratio=None)), comp)
    live.on_lap_result(*lap_points(3, pt("T6", "low_min_speed", 0)), comp)
    assert [c["focus"] for c in calls[:2]] == [[], []]
    assert [f["corner"] for f in calls[2]["focus"]] == ["T6"] and calls[2]["habits"][0]["status"] == "focus"
    assert live.cues._focus is not None and live.cues._focus[0]["corner"] == "T6"
    assert live.cues._habits is not None and live.cues._habits[0]["kind"] == "low_min_speed"
    # corners the comparison had and drove clean count: T6 is sorted after two clean laps
    for lap in (4, 5):
        live.on_lap_result(*lap_points(lap), comp)
    assert live.snapshot()["coach"]["habits"][0]["status"] == "fixed"


def test_the_cue_engine_keeps_focus_and_habits_with_the_comparison() -> None:
    eng = CueEngine()
    focus, habits = [{"corner": "T6"}], [{"corner": "T6"}, {"corner": "T2"}]
    eng.on_lap_result([], None, 4000.0, focus=focus, habits=habits)  # no comparison: nothing kept
    assert eng._focus is None and eng._habits is None
    eng.on_lap_result([], {"ref_lap_id": 1, "corners": []}, 4000.0, focus=focus, habits=habits)
    assert eng._focus == tuple(focus) and eng._habits == tuple(habits)
    eng.on_lap_result([], {"ref_lap_id": 1, "corners": []}, 4000.0)  # an older caller: none given
    assert eng._focus is None and eng._habits is None
    eng.on_lap_result([], {"ref_lap_id": 1, "corners": []}, 4000.0, focus=focus, habits=habits)
    eng.reset_session()
    assert eng._focus is None and eng._habits is None


# ---------------------------------------------------------------------------------------------- section 5: radio
def test_the_radio_says_the_tracker_events_from_the_block() -> None:
    sel = CoachSelection()
    sel.set_limits(None, None)
    for lap in (1, 2):
        sel.select(*lap_points(lap, pt("T6", "low_min_speed", 0, ratio=None)), compared=True, corners=CORNERS)
    lap, obs = lap_points(3, pt("T6", "low_min_speed", 0, impact=0.31))
    block = sel.select(lap, obs, compared=True, corners=CORNERS)
    msgs = lap_messages({**lap, "lap_time_ms": 65_000}, obs, None, None, "normal", 0.0, coach=block)
    (m,) = [m for m in msgs if m.kind is MessageKind.COACHING]
    assert m.text == "Turn 6, losing 0.31 s: minimum speed 12 km/h down. 3 of the last 3 laps."
    assert m.meta["habit_event"] == "announce" and m.corner == "T6"
    simple = lap_messages(
        {**lap, "lap_time_ms": 65_000}, obs, None, None, "normal", 0.0, limits=coaching_limits("beginner"), coach=block
    )
    (s,) = [m for m in simple if m.kind is MessageKind.COACHING]
    assert s.text == "Turn 6: you were 12 km/h slower at the slowest point of the corner. Most laps."
