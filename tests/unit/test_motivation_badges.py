"""Badges and streaks (pure): every kind and level, cross-session rules, stable keys and order."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from pitwall.motivation import badges as B
from pitwall.motivation.model import GoalRow, History, in_car
from tests.unit.motivation_data import DAY, T0, collision, goal, history, lap, laps, penalty, sess

WEEK = 7 * DAY


def keys(h: History, goals: Sequence[GoalRow] = ()) -> list[str]:
    return sorted(b.key for b in B.badges(h, goals))


def test_first_clean_lap_per_track_and_under_time_across_sessions_only() -> None:
    a = laps("a", [72_300, 71_800])  # within a session: crossing 1:12 does not count
    b = laps("b", [71_900, 70_549])  # beats 1:11.800 from session a: crosses 1:11 and 1:12 -> the lowest, 1:11
    c = laps("c", [70_400])  # beats 1:10.549 but crosses no whole second
    h = history((sess("a", T0), a), (sess("b", T0 + 60), b), (sess("c", T0 + 120), c))
    got = {x.key: x for x in B.badges(h)}
    assert "first_clean_lap:f1_25:f1:17" in got and got["first_clean_lap:f1_25:f1:17"].session_id == "a"
    assert got["first_clean_lap:f1_25:f1:17"].title == "First clean lap at Austria"
    under = [k for k in got if k.startswith("under_time")]
    assert under == ["under_time:f1_25:f1:17:f1:team:7:71000"]
    u = got[under[0]]
    assert (u.title, u.title_simple, u.session_id, u.lap_id, u.level) == (
        "First time under 1:11 at Austria in the Haas",
        "You beat 1:11 at Austria in the Haas for the first time",
        "b",
        b[1].id,
        71_000,
    )
    assert u.detail == "1:10.549 on lap 2"


def test_under_time_names_the_car_and_hides_id_only_names() -> None:
    """Bests are per car: a slower car's first time under 1:19 at Austria is about that car, and says so."""
    haas = sess("a", T0)
    generic = [sess(x, T0 + i * 60, car_id="f1:team:41", car_name="F1 Generic") for i, x in ((1, "b"), (2, "c"))]
    h = history((haas, laps("a", [69_900])), (generic[0], laps("b", [80_400])), (generic[1], laps("c", [78_900])))
    (u,) = [b for b in B.badges(h) if b.kind == "under_time"]
    assert u.title == "First time under 1:19 at Austria in the F1 Generic"
    unknown = [sess(x, T0 + i * 60, car_id="f1:team:214", car_name="Unknown team (id 214)") for i, x in enumerate("de")]
    h2 = history((unknown[0], laps("d", [80_400])), (unknown[1], laps("e", [78_900])))
    (u2,) = [b for b in B.badges(h2) if b.kind == "under_time"]
    assert u2.title == "First time under 1:19 at Austria"  # an id-only name is left out, never shown


def test_track_badges_need_an_identified_track_and_a_real_lap() -> None:
    """Plan 5.8: no track badge for GT7's placeholder circuit, an unknown F1 track or a "lap" under 30 s; the other
    badges (clean laps in a row) still count. Junk badges older code awarded simply stop being listed."""
    gt7 = {"game": "gt7", "car_id": "gt7:car:3361", "car_name": None, "session_type": "unknown"}
    h = history(
        (
            sess("g", T0, track_id="gt7:sf:380", track_name="Unidentified GT7 circuit (3.80 km)", **gt7),
            laps("g", [105_151, 104_000, 103_500]),
        ),
        (sess("u", T0 + 60, track_id="f1:-1", track_name="Unknown track"), laps("u", [90_000, 89_000])),
        (sess("x", T0 + 120, track_id="f1:99", track_name="Unknown track (id 99)"), laps("x", [90_000, 89_000])),
        (sess("n", T0 + 180, track_id="f1:13", track_name=None), laps("n", [90_000])),
        (sess("t", T0 + 240, track_id="f1:13", track_name="Suzuka"), laps("t", [23_222, 22_000])),
    )
    got = keys(h)
    assert not [k for k in got if k.startswith(("first_clean_lap", "under_time", "pb_streak"))]
    assert "clean_streak:3" in got
    assert B.streaks(h, T0 + DAY)["pb"] == []  # no PB streak at a placeholder or a glitch either
    # a real lap at the same, identified track earns the first clean lap (the glitch did not use it up)
    h2 = history((sess("t", T0, track_id="f1:13", track_name="Suzuka"), laps("t", [23_222, 96_360])))
    (first,) = [b for b in B.badges(h2) if b.kind == "first_clean_lap"]
    assert (first.title, first.detail, first.lap_id) == (
        "First clean lap at Suzuka",
        "1:36.360 on lap 2 in the Haas",
        h2.laps["t"][1].id,
    )


def test_raw_car_ids_are_never_shown() -> None:
    """An older F1 build stored the team id as the car name ("team_214"); GT7 sends only a car code."""
    old = sess("o", T0, car_id="f1:team:214", car_name="team_214")
    h = history(
        (old, laps("o", [80_400])), (sess("p", T0 + 60, car_id="f1:team:214", car_name="team_214"), laps("p", [78_900]))
    )
    texts = [t for b in B.badges(h) for t in (b.title, b.title_simple, b.detail or "")]
    assert texts and not [t for t in texts if "team_214" in t]
    for raw in ("team_214", "car_12", "gt7:car:3361", "f1:team:7"):
        assert in_car(raw) == ""
    assert in_car("Art GP '24") == " in the Art GP '24" and in_car("McLaren") == " in the McLaren"


def test_fact_keys_match_the_recap() -> None:
    """The Session complete card shows each fact once (plan 2.6): badges carry the recap's keys."""
    a, b = laps("a", [72_300, 71_800]), laps("b", [71_900, 70_549])
    h = history((sess("a", T0), a), (sess("b", T0 + 60), b))
    got = {x.kind: x.to_dict()["fact_key"] for x in B.badges(h)}
    assert got["first_clean_lap"] == "first_clean:f1_25:f1:17:f1:team:7"
    assert got["under_time"] == f"pb:{b[1].id}"
    c = laps("c", [70_400])  # a second new best in a row: the streak is its own fact, as the recap's progress item
    h3 = history((sess("a", T0), a), (sess("b", T0 + 60), b), (sess("c", T0 + 120), c))
    (streak,) = [x for x in B.badges(h3) if x.kind == "pb_streak"]
    assert streak.to_dict()["fact_key"] == "pb_streak:f1_25:f1:17:f1:team:7:2"
    reached = goal("clean_streak", 2, gid=4, status="achieved", achieved_unix=T0 + 100, achieved_session_id="b")
    (g,) = [x for x in B.badges(h, [reached]) if x.kind == "goals_reached"]
    assert g.to_dict()["fact_key"] == "goal:4"


def test_clean_streak_levels_and_ten_clean() -> None:
    run10 = laps("a", [71_000] * 10)
    run3 = laps("b", [71_000] * 3)
    h = history((sess("b", T0), run3), (sess("a", T0 + 60), run10))
    got = {x.key: x for x in B.badges(h)}
    assert got["clean_streak:3"].session_id == "b"
    assert got["clean_streak:5"].session_id == "a" and got["clean_streak:10"].session_id == "a"
    assert got["clean_streak:5"].lap_id == run10[4].id
    assert "clean_streak:20" not in got
    assert got["ten_clean_session"].lap_id == run10[9].id
    assert got["clean_streak:5"].title_simple == "5 clean laps in a row"  # one word for "clean" everywhere


def test_pb_streak_levels() -> None:
    times = [73_000, 72_500, 72_400, 72_300, 72_200, 72_100]
    pairs = [(sess(f"s{i}", T0 + i * 60), [lap(1, ms, sid=f"s{i}")]) for i, ms in enumerate(times)]
    got = {x.key: x for x in B.badges(history(*pairs))}
    assert got["pb_streak:2"].session_id == "s2"  # s1 beat s0 (1), s2 beat s1 (2)
    assert got["pb_streak:3"].session_id == "s3" and got["pb_streak:5"].session_id == "s5"
    assert got["pb_streak:3"].title == "New best in 3 sessions in a row"
    assert got["pb_streak:3"].title_simple == "Faster than ever, 3 times in a row"


def test_weekly_streak_and_busy_week() -> None:
    monday = datetime(2026, 9, 7, 19, 0).timestamp()
    pairs = [(sess(f"w{i}", monday + i * WEEK), [lap(1, 71_000, sid=f"w{i}")]) for i in range(4)]
    pairs += [(sess(f"x{i}", monday + 3 * WEEK + DAY + i * 60), [lap(1, 71_000, sid=f"x{i}")]) for i in range(4)]
    pairs.append((sess("empty", monday + 3 * WEEK + 2 * DAY), []))  # no timed lap: does not count
    got = {x.key: x for x in B.badges(history(*pairs))}
    assert got["weekly_streak:2"].session_id == "w1" and got["weekly_streak:4"].session_id == "w3"
    assert got["weekly_streak:4"].title == "4 weeks in a row" and "weekly_streak:8" not in got
    assert got["busy_week:3"].session_id == "x1" and got["busy_week:5"].session_id == "x3"
    # a gap week restarts the count
    gap = [(sess(f"g{i}", monday + i * 2 * WEEK), [lap(1, 71_000, sid=f"g{i}")]) for i in range(3)]
    assert not any(k.startswith("weekly_streak") for k in keys(history(*gap)))


def test_clean_race_and_goals_reached() -> None:
    r1 = laps("r1", [88_000, 78_000, 78_100])
    r2 = laps("r2", [88_000, 78_000, 78_100])
    race = {"total_laps": 3, "formula": "F1 Generic"}
    h = history(
        (sess("r1", T0, **race), r1),
        (sess("r2", T0 + 60, **race), r2),
        events={"r1": [penalty(4), collision()], "r2": [collision(), penalty(5)]},
    )
    got = {x.key: x for x in B.badges(h)}
    assert got["clean_race:no_penalties"].session_id == "r2" and "clean_race:no_contact" not in got
    assert got["clean_race:no_penalties"].lap_id == r2[-1].id
    reached = [
        goal("clean_streak", 3, gid=i, status="achieved", achieved_unix=T0 + i, achieved_session_id="r1")
        for i in range(1, 4)
    ]
    got2 = {x.key: x for x in B.badges(h, reached)}
    assert got2["goals_reached:1"].earned_unix == T0 + 1 and got2["goals_reached:1"].title == "First goal reached"
    assert got2["goals_reached:3"].earned_unix == T0 + 3 and "goals_reached:10" not in got2


def test_order_is_newest_first_and_stable() -> None:
    suzuka = sess("a", T0, track_id="f1:13", track_name="Suzuka")
    h = history((suzuka, [lap(1, 96_000, sid="a")]), (sess("b", T0 + 60), [lap(1, 71_000, sid="b")]))
    first = [b.key for b in B.badges(h)]
    assert first == ["first_clean_lap:f1_25:f1:17", "first_clean_lap:f1_25:f1:13"]
    assert first == [b.key for b in B.badges(h)]
    assert all(set(b.to_dict()) >= {"key", "kind", "level", "title", "earned_unix", "synthetic"} for b in B.badges(h))


def test_synthetic_badges_are_flagged() -> None:
    h = history((sess("syn", T0, synthetic=True, track_id="synthetic:demo"), [lap(1, 71_000, sid="syn")]))
    (b,) = B.badges(h)
    assert b.synthetic


def test_streaks() -> None:
    monday = datetime(2026, 9, 7, 19, 0).timestamp()
    pairs = [
        (sess(f"w{i}", monday + i * WEEK, track_id="f1:17"), laps(f"w{i}", [72_000 - 100 * i, 72_100 - 100 * i]))
        for i in range(3)
    ]
    h = history(*pairs)
    now = monday + 3 * WEEK + DAY  # Tuesday of the next week: no session yet, the streak still counts
    st = B.streaks(h, now)
    assert st["weekly"] == {"current_weeks": 3, "best_weeks": 3, "this_week_sessions": 0}
    assert st["week_start"] == datetime.fromtimestamp(monday + 3 * WEEK).date().isoformat()
    assert st["clean_laps"]["best"] == 2 and st["clean_laps"]["last_session_id"] == "w2"
    (pb,) = st["pb"]
    assert (pb["current_sessions"], pb["best_sessions"], pb["scope_text"]) == (2, 2, "Austria · Haas")
    later = B.streaks(h, monday + 5 * WEEK)  # a whole week without driving ends it
    assert later["weekly"]["current_weeks"] == 0 and later["weekly"]["best_weeks"] == 3
    empty = B.streaks(history(), now)
    assert empty["weekly"]["current_weeks"] == 0 and empty["clean_laps"]["best"] == 0 and empty["pb"] == []
