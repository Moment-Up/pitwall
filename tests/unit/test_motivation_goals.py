"""Goals (pure): validation (422) and conflicts (409), titles, progress for each kind, when a goal is reached, and
baselines."""

from __future__ import annotations

from typing import Any

import pytest

from pitwall.motivation import goals as G
from pitwall.motivation.model import Scope
from tests.unit.motivation_data import AUSTRIA_HAAS, DAY, T0, collision, goal, history, lap, laps, penalty, sess


def err(fn: Any, *a: Any, **kw: Any) -> G.GoalError:
    with pytest.raises(G.GoalError) as e:
        fn(*a, **kw)
    return e.value


# ---------------------------------------------------------------------------------------------- validation
def test_titles() -> None:
    assert G.titles("lap_time", 70_000, {}) == ("A lap under 1:10.000", "Beat 1:10.000")
    assert G.titles("clean_streak", 8, {}) == ("8 clean laps in a row", "8 clean laps in a row")
    assert G.titles("consistency", 1100, {"window_laps": 5}) == (
        "5 clean laps within 1.1 s of each other",
        "5 steady laps, all within 1.1 s",
    )
    assert G.titles("race_clean", 1, {"rule": "no_penalties"})[0] == "Finish a race with no penalties"
    assert G.titles("race_clean", 1, {"rule": "no_contact"})[0] == "Finish a race without touching another car"


def test_lap_time_validation() -> None:
    ok = G.validate_new("lap_time", 70_000, None, AUSTRIA_HAAS)
    assert ok.target == 70_000.0 and ok.params == {}
    for target in (9_900, 3_600_100, 70_050, 70_000.5):
        assert err(G.validate_new, "lap_time", target, None, AUSTRIA_HAAS).status == 422
    assert err(G.validate_new, "lap_time", 70_000, None, Scope(game="f1_25")).code == "invalid_scope"
    no_car = Scope(game="f1_25", track_id="f1:17")
    assert err(G.validate_new, "lap_time", 70_000, None, no_car).code == "invalid_scope"
    both = Scope(game="f1_25", track_id="f1:17", car_id="f1:team:7", car_class="f1_25:formula:F1 World")
    assert err(G.validate_new, "lap_time", 70_000, None, both).code == "invalid_scope"
    syn = Scope(game="f1_25", track_id="synthetic:coaching-demo", car_id="x")
    assert err(G.validate_new, "lap_time", 70_000, None, syn).code == "synthetic_scope"
    bad_class = Scope(game="f1_25", track_id="f1:17", car_class="gt7:class:5")
    assert err(G.validate_new, "lap_time", 70_000, None, bad_class).code == "invalid_scope"
    cls = Scope(game="f1_25", track_id="f1:17", car_class="f1_25:formula:F1 World")
    assert G.validate_new("lap_time", 70_000, None, cls).scope.car_class == "f1_25:formula:F1 World"


def test_other_kinds_validation() -> None:
    assert G.validate_new("clean_streak", 8, None, Scope()).target == 8.0
    for target in (1, 51, 7.5):
        assert err(G.validate_new, "clean_streak", target, None, Scope()).status == 422
    c = G.validate_new("consistency", 1100, {"window_laps": 5}, Scope())
    assert c.params == {"window_laps": 5}
    assert err(G.validate_new, "consistency", 1100, {"window_laps": 4}, Scope()).code == "invalid_params"
    assert err(G.validate_new, "consistency", 1100, None, Scope()).code == "invalid_params"
    for target in (0, 10_100, 1150):
        assert err(G.validate_new, "consistency", target, {"window_laps": 5}, Scope()).code == "invalid_target"
    r = G.validate_new("race_clean", 1, {"rule": "no_contact"}, Scope(game="f1_25"))
    assert r.params == {"rule": "no_contact"}
    assert err(G.validate_new, "race_clean", 2, {"rule": "no_contact"}, Scope()).code == "invalid_target"
    assert err(G.validate_new, "race_clean", 1, {"rule": "fast"}, Scope()).code == "invalid_params"
    assert err(G.validate_new, "race_clean", 1, {"rule": "no_contact"}, Scope(game="gt7")).code == "unsupported_game"
    assert err(G.validate_new, "speed", 1, None, Scope()).code == "invalid_kind"
    assert err(G.validate_new, "clean_streak", 5, {"window_laps": 3}, Scope()).code == "invalid_params"
    assert err(G.validate_new, "clean_streak", True, None, Scope()).status == 422
    assert err(G.validate_new, "clean_streak", 5, None, Scope(), source="robot").status == 422


def test_conflicts() -> None:
    new = G.validate_new("lap_time", 70_000, None, AUSTRIA_HAAS)
    full = [goal("clean_streak", 3 + i, gid=i) for i in range(G.MAX_ACTIVE)]
    assert G.conflicts(new, full, None).code == "too_many"  # type: ignore[union-attr]
    same = [goal("lap_time", 70_000, scope=AUSTRIA_HAAS)]
    assert G.conflicts(new, same, None).code == "duplicate"  # type: ignore[union-attr]
    other_target = [goal("lap_time", 69_500, scope=AUSTRIA_HAAS)]
    assert G.conflicts(new, other_target, None).code == "duplicate_scope"  # type: ignore[union-attr]
    beaten = G.conflicts(new, [], 69_981)
    assert (
        beaten is not None and beaten.code == "already_beaten" and beaten.detail == "Your best here is already 1:09.981"
    )
    assert G.conflicts(new, [], 70_549) is None
    assert (
        G.conflicts(new, [goal("lap_time", 70_000, scope=Scope(game="f1_25", track_id="f1:13", car_id="x"))], None)
        is None
    )
    streak = G.validate_new("clean_streak", 8, None, Scope())
    assert G.conflicts(streak, [goal("clean_streak", 8)], None).code == "duplicate"  # type: ignore[union-attr]
    assert G.conflicts(streak, [goal("clean_streak", 9)], None) is None


# ---------------------------------------------------------------------------------------------- lap time
def test_lap_time_progress_and_hit() -> None:
    a = laps("a", [71_745, 71_300, 70_900])
    b = laps("b", [70_700, 70_549, 70_600])
    h = history((sess("a", T0), a), (sess("b", T0 + 60), b))
    g = goal("lap_time", 70_000, scope=AUSTRIA_HAAS, after=a[-1].id, baseline=70_900)
    p = G.progress(g, h)
    assert (p.current, p.met, p.to_go, p.best_session_id, p.best_lap_id) == (70_549, False, 549, "b", b[1].id)
    assert p.fraction == pytest.approx((70_900 - 70_549) / 900)
    assert p.text == "0.549 s to go · best since you set it 1:10.549"
    assert p.text_simple == "About 0.5 s to go"
    assert p.sessions_since == 1
    assert G.first_hit(g, h) is None
    c = [lap(1, 70_400, sid="c"), lap(2, 69_981, sid="c")]
    h2 = history((sess("a", T0), a), (sess("b", T0 + 60), b), (sess("c", T0 + 120), c))
    hit = G.first_hit(g, h2)
    assert hit is not None and (hit.session_id, hit.lap_id, hit.lap_number, hit.value) == ("c", c[1].id, 2, 69_981)
    p2 = G.progress(g, h2)
    assert p2.met and p2.fraction == 1.0 and p2.text == "Reached: 1:09.981" and p2.text_simple == "Done: 1:09.981"


def test_lap_time_only_scope_laps_after_creation_count() -> None:
    a = laps("a", [69_000])  # faster, but before the goal was set
    other_car = [lap(1, 69_500, sid="b")]
    h = history((sess("a"), a), (sess("b", T0 + 60, car_id="f1:team:1"), other_car))
    g = goal("lap_time", 70_000, scope=AUSTRIA_HAAS, after=a[-1].id)
    p = G.progress(g, h)
    assert p.current is None and not p.met and p.fraction is None
    assert p.text == "No clean lap here since you set it"
    assert G.first_hit(g, h) is None
    with_base = goal("lap_time", 70_000, scope=AUSTRIA_HAAS, after=a[-1].id, baseline=70_549)
    assert G.progress(with_base, h).fraction == 0.0


def test_unknown_baseline_uses_the_first_measurement() -> None:
    a = laps("a", [71_000, 70_500, 70_300])
    h = history((sess("a"), a))
    g = goal("lap_time", 70_000, scope=AUSTRIA_HAAS)
    assert G.first_measurement(g, h) == 71_000
    p = G.progress(g, h)
    assert p.baseline == 71_000 and p.fraction == pytest.approx(0.7)


def test_creation_baselines() -> None:
    a = laps("a", [71_000, 70_500, 70_800, 70_600, 70_700])
    h = history((sess("a", T0, session_type="practice"), a))
    now = T0 + DAY
    assert G.creation_baseline("lap_time", AUSTRIA_HAAS, {}, h, now) == 70_500
    assert G.creation_baseline("clean_streak", Scope(), {}, h, now) == 5
    assert G.creation_baseline("consistency", Scope(), {"window_laps": 3}, h, now) == 200
    assert G.creation_baseline("clean_streak", Scope(), {}, h, T0 + 31 * DAY) is None  # older than 30 days
    assert G.creation_baseline("race_clean", Scope(), {"rule": "no_penalties"}, h, now) is None


# ---------------------------------------------------------------------------------------------- clean laps / steady laps
def test_clean_streak_progress_and_hit() -> None:
    a = laps("a", [71_000, 71_100, 71_200])
    b = [*laps("b", [71_000, 71_100]), lap(3, 71_000, sid="b", flags=["invalid"]), *laps("b", [71_000] * 4, first=4)]
    h = history((sess("a"), a), (sess("b", T0 + 60), b))
    g = goal("clean_streak", 6, after=a[0].id)
    p = G.progress(g, h)
    assert (p.current, p.met, p.best_session_id) == (4, False, "b")
    assert p.fraction == pytest.approx(4 / 6)
    assert p.text == "Best since you set it: 4 of 6 laps" and p.text_simple == "4 of 6 clean laps in a row so far"
    assert G.first_hit(g, h) is None
    g4 = goal("clean_streak", 4, after=a[0].id)
    hit = G.first_hit(g4, h)
    assert hit is not None and (hit.session_id, hit.lap_number, hit.value) == ("b", 7, 4)
    assert G.progress(goal("clean_streak", 4, after=10**9), h).text == "No clean laps since you set it"


def test_consistency_progress_and_hit() -> None:
    a = laps("a", [90_000, 71_000, 71_500, 71_300, 71_200, 71_100])  # race lap 1 skipped
    h = history((sess("a", session_type="race"), a))
    g = goal("consistency", 300, params={"window_laps": 3}, baseline=1_000)
    p = G.progress(g, h)
    assert p.current == 200 and p.met  # laps 4-6
    assert G.progress(goal("consistency", 300, params={"window_laps": 5}), h).current == 500
    hit = G.first_hit(g, h)  # the first window within the target: laps 3-5
    assert hit is not None and (hit.lap_number, hit.value) == (5, 300)
    g5 = goal("consistency", 100, params={"window_laps": 5}, baseline=1_000)
    p5 = G.progress(g5, h)
    assert not p5.met and p5.text == "Steadiest 5 laps since you set it: within 0.500 s (target 0.1 s)"
    assert p5.fraction == pytest.approx((1_000 - 500) / 900)


# ---------------------------------------------------------------------------------------------- clean race
def race(sid: str, started: float, total: int = 3) -> Any:
    return sess(sid, started, total_laps=total, formula="F1 Generic", car_id="f1:team:41", car_name="F1 Generic")


def test_race_clean_progress_and_hit() -> None:
    r1 = laps("r1", [88_000, 78_000, 78_100])
    r2 = laps("r2", [88_000, 78_000, 78_100])
    events = {"r1": [penalty(4), collision()], "r2": [collision()]}
    h = history((race("r1", T0), r1), (race("r2", T0 + 60), r2), events=events)
    g = goal("race_clean", 1, params={"rule": "no_contact"})
    p = G.progress(g, h)
    assert not p.met and p.text == "2 races finished since you set it: a penalty in one, contact in both"
    assert p.text_simple == "Not yet: 2 races finished since you set it"
    gp = goal("race_clean", 1, params={"rule": "no_penalties"})
    hit = G.first_hit(gp, h)
    assert hit is not None and (hit.session_id, hit.lap_id, hit.lap_number, hit.value) == ("r2", r2[-1].id, 3, 1.0)
    assert G.progress(gp, h).text.startswith("Done: Austria, ")
    # a race whose lap 1 was stored before the goal was set does not count
    late = goal("race_clean", 1, params={"rule": "no_penalties"}, after=r2[0].id)
    assert G.first_hit(late, h) is None
    assert G.progress(late, h).text == "No race finished since you set it"
    one = history((race("r1", T0), r1), events={"r1": [penalty(4), collision()]})
    assert G.progress(g, one).text == "1 race finished since you set it, with a penalty and contact"


# ---------------------------------------------------------------------------------------------- achieved goals
def test_achieved_goal_progress_and_json() -> None:
    a = laps("a", [70_400, 69_981])
    h = history((sess("a"), a))
    g = goal(
        "lap_time",
        70_000,
        scope=AUSTRIA_HAAS,
        status="achieved",
        achieved_unix=T0 + 300,
        achieved_session_id="a",
        achieved_lap_id=a[1].id,
        achieved_value=69_981,
    )
    p = G.progress(g, h)
    assert p.met and p.fraction == 1.0 and p.current == 69_981 and p.text == "Reached: 1:09.981"
    j = G.goal_json(g, h, owned={"a"}, lap_numbers={a[1].id: 2})
    assert j["title"] == "A lap under 1:10.000" and j["scope_text"] == "Austria · Haas"
    assert j["achieved"]["session_owned"] and j["achieved"]["lap_number"] == 2
    assert j["achieved"]["text"] == "Reached Sat 10 Oct: 1:09.981 on lap 2"
    assert G.goal_json(g, h, owned=set())["achieved"]["session_owned"] is False  # re-assigned since
    assert set(j) == {
        "id", "driver_id", "kind", "status", "target", "params", "scope", "title", "title_simple", "scope_text",
        "source", "basis", "created_unix", "achieved", "progress",
    }  # fmt: skip
    assert set(j["progress"]) == {
        "baseline", "current", "target", "fraction", "to_go", "met", "best_session_id", "best_lap_id",
        "sessions_since", "text", "text_simple",
    }  # fmt: skip


def test_labels_come_from_driving_when_the_goal_was_set_first() -> None:
    bare = Scope(game="f1_25", track_id="f1:17", car_id="f1:team:7")  # set before any session there
    g = goal("lap_time", 72_000, scope=bare)
    assert G.goal_json(g, history())["scope_text"] == "f1:17"
    j = G.goal_json(g, history((sess("a"), laps("a", [71_745]))))
    assert j["scope_text"] == "Austria · Haas" and j["scope"]["track_name"] == "Austria"
