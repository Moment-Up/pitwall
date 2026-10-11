"""Weekly digest (pure): totals, improvements, goal changes, Markdown, the printable page, an empty week."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pitwall.motivation import digest as D
from pitwall.motivation import goals as G
from pitwall.motivation.html import digest_html
from pitwall.motivation.model import GoalRow, History
from tests.unit.motivation_data import AUSTRIA_HAAS, DAY, goal, history, lap, laps, sess

WEEK = date(2026, 10, 5)  # Monday
MON = datetime(2026, 10, 5, 19, 0).timestamp()
LAST_WEEK = datetime(2026, 9, 30, 19, 0).timestamp()
NOW = datetime(2026, 10, 12, 9, 0).timestamp()


def gj(g: GoalRow, h: History) -> dict[str, Any]:
    return G.goal_json(g, h)


def week_history() -> History:
    return history(
        (sess("old", LAST_WEEK), laps("old", [71_745, 72_000])),
        (
            sess("a", MON),
            [lap(1, 72_000, sid="a"), lap(2, 70_549, sid="a"), lap(3, 71_000, sid="a", flags=["invalid"])],
        ),
        (sess("b", MON + DAY, track_id="f1:13", track_name="Suzuka", car_name="F1 Generic"), laps("b", [96_360])),
        (sess("c", MON + 2 * DAY), []),  # no timed lap: not a session of the week
    )


def build(
    h: History, goals: list[GoalRow] | None = None, name: str = "Sam", skill: str = "intermediate"
) -> dict[str, Any]:
    return D.build_digest(
        {"id": 2, "name": name, "skill_level": skill}, h, goals or [], WEEK, NOW, include_synthetic=False, goal_json=gj
    )


def test_totals_sessions_and_improvements() -> None:
    d = build(week_history())
    assert (d["week_start"], d["week_end"], d["is_current_week"]) == ("2026-10-05", "2026-10-11", False)
    assert d["totals"] == {"sessions": 2, "laps": 4, "clean_laps": 3, "lap_time_s": 309.909, "tracks": 2}
    assert d["previous_week"] == {"sessions": 1, "laps": 2, "clean_laps": 2}
    assert [(r["session_id"], r["laps"], r["clean_laps"], r["best_clean_ms"], r["pb"]) for r in d["sessions"]] == [
        ("a", 3, 2, 70_549, True),
        ("b", 1, 1, 96_360, False),
    ]
    gain, first = d["improvements"]
    assert (gain["scope_text"], gain["before_ms"], gain["best_ms"], gain["gain_ms"], gain["new_track"]) == (
        "Austria · Haas",
        71_745,
        70_549,
        1196,
        False,
    )
    assert (first["scope_text"], first["gain_ms"], first["new_track"]) == ("Suzuka · F1 Generic", None, True)
    assert (first["first_ms"], first["best_ms"], first["week_gain_ms"]) == (96_360, 96_360, None)
    assert (gain["text"], first["text"]) == ("1:10.549, 1.196 s faster than before", "New this week: 1:36.360")
    # the count says which rule it uses (plan 5.7): the session with no timed lap is not one of them
    assert d["headline"] == "2 sessions with a timed lap, 4 laps, a new best at Austria"
    assert d["headline_simple"] == "You drove 2 times this week"


def test_goal_changes_and_badges() -> None:
    h = week_history()
    g = goal("lap_time", 70_000, scope=AUSTRIA_HAAS, after=0, baseline=71_745, created=LAST_WEEK + 3600)
    reached = goal(
        "clean_streak", 2, gid=2, status="achieved", achieved_unix=MON + 600, achieved_session_id="a", created=LAST_WEEK
    )
    d = build(h, [g, reached])
    (active,) = d["goals"]["active"]
    assert active["goal"]["id"] == 1
    assert active["from_fraction"] == 0.0 and active["to_fraction"] is not None and active["to_fraction"] > 0.6
    assert [x["id"] for x in d["goals"]["achieved"]] == [2]
    keys = {b["key"] for b in d["badges"]}
    assert "under_time:f1_25:f1:17:f1:team:7:71000" in keys and "goals_reached:1" in keys
    assert "first_clean_lap:f1_25:f1:17" not in keys  # earned the week before
    assert d["streaks"]["weekly"]["current_weeks"] == 2


def test_markdown_snapshot() -> None:
    md = build(week_history(), name="Sam_*[x]#")["markdown"]
    assert md == (
        "# Sam\\_\\*\\[x\\]\\#'s week: 5 to 11 October 2026\n"
        "\n"
        "2 sessions with a timed lap, 4 laps, a new best at Austria.\n"
        "\n"
        "3 clean laps · 5 min driving · 2 tracks\n"
        "\n"
        "Week before: 1 session with a timed lap, 2 laps, 2 clean\n"
        "\n"
        "## Sessions\n"
        "- Mon 5 Oct · Austria · Haas · Race · 3 laps (2 clean) · best 1:10.549 (new best)\n"
        "- Tue 6 Oct · Suzuka · F1 Generic · Race · 1 lap (1 clean) · best 1:36.360\n"
        "\n"
        "## Improvements\n"
        "- Austria · Haas: 1:10.549, 1.196 s faster than before\n"
        "\n"
        "## New tracks\n"
        "- Suzuka · F1 Generic: New this week: 1:36.360\n"
        "\n"
        "## Goals\n"
        "- No goals set.\n"
        "\n"
        "## Badges this week\n"
        "- First clean lap at Suzuka (Tue 6 Oct)\n"
        "- First time under 1:11 at Austria in the Haas (Mon 5 Oct)\n"
        "- 2 weeks in a row (Mon 5 Oct)\n"
        "\n"
        "## Streaks\n"
        "- Weeks in a row with a timed lap: 2 (best 2)\n"
        "- Best run of clean laps: 2\n"
        "- New best in a row at Austria · Haas: 1 session (best 1)\n"
    )


def test_html_escapes_names_and_is_self_contained() -> None:
    page = digest_html(build(week_history(), name="<script>alert(1)</script>"))
    assert "<script>" not in page and "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "@page { size: A4; margin: 16mm; }" in page
    assert "http://" not in page and "https://" not in page and "<link" not in page
    assert "Synthetic and replayed sessions are not included." in page
    simple = digest_html(build(week_history(), skill="beginner"))
    assert "You drove 2 times this week" in simple


def test_first_laps_at_a_track_are_the_first_session_there_in_its_car() -> None:
    """Austria first in the F1 Generic (1:18.351), later the same week in the Haas (1:10.549): the first clean laps
    are the F1 Generic's, and say so."""
    generic = sess("g", MON, car_id="f1:team:41", car_name="F1 Generic")
    h = history((generic, laps("g", [78_900, 78_351])), (sess("h", MON + DAY), laps("h", [70_549])))
    d = build(h)
    (first,) = d["improvements"]
    assert (first["scope_text"], first["best_ms"], first["session_id"]) == ("Austria · F1 Generic", 78_351, "g")
    assert "## New tracks\n- Austria · F1 Generic: New this week: 1:18.351\n" in d["markdown"]


def test_a_new_track_says_how_much_faster_that_car_got_there_in_the_week() -> None:
    """Plan 5.8: "New this week: 1:18.351 -> 1:17.155 (1.2 s faster)", from the session that first set a clean lap
    there to that car's best at the end of the week; another car's lap there changes nothing."""
    generic = {"car_id": "f1:team:41", "car_name": "F1 Generic"}
    h = history(
        (sess("g1", MON, **generic), laps("g1", [78_900, 78_351])),
        (sess("h", MON + 3600), laps("h", [70_549])),  # the Haas: another car
        (sess("g2", MON + DAY, **generic), laps("g2", [77_600, 77_155])),
    )
    d = build(h)
    (first,) = d["improvements"]
    assert (first["session_id"], first["first_ms"], first["best_ms"], first["week_gain_ms"]) == (
        "g1",
        78_351,
        77_155,
        1196,
    )
    assert (first["best_session_id"], first["text"]) == ("g2", "New this week: 1:18.351 → 1:17.155 (1.2 s faster)")
    assert "- Austria · F1 Generic: New this week: 1:18.351 → 1:17.155 (1.2 s faster)\n" in d["markdown"]
    page = digest_html(d)
    assert "<h2>New tracks</h2>" in page and "<h2>Improvements</h2>" in page


def test_unidentified_tracks_and_glitch_laps_are_never_new_tracks() -> None:
    """The same rule as the first clean lap badge (plan 5.8): GT7's placeholder name, an unknown F1 track and a lap
    under 30 s are not "new tracks"."""
    gt7 = {"game": "gt7", "car_id": "gt7:car:3361", "car_name": None, "track_length_m": 3800.0}
    h = history(
        (
            sess("u1", MON, track_id="gt7:sf:380", track_name="Unidentified GT7 circuit (3.80 km)", **gt7),
            laps("u1", [105_151]),
        ),
        (sess("u2", MON + 60, track_id="f1:-1", track_name="Unknown track"), laps("u2", [90_000])),
        (sess("u3", MON + 120, track_id="f1:13", track_name="Suzuka"), laps("u3", [23_222])),
    )
    d = build(h)
    assert [i for i in d["improvements"] if i["new_track"]] == []
    assert "## New tracks\n- None this week." in d["markdown"]


def test_id_only_car_names_are_left_out() -> None:
    s = sess("u", MON, car_id="f1:team:214", car_name="Unknown team (id 214)")
    d = build(history((s, laps("u", [70_549]))))
    assert d["sessions"][0]["car_name"] is None
    assert d["improvements"][0]["scope_text"] == "Austria"
    assert "Unknown team" not in d["markdown"]


def test_empty_week() -> None:
    d = build(history((sess("old", LAST_WEEK), laps("old", [71_745]))))
    assert d["totals"]["sessions"] == 0 and d["sessions"] == [] and d["improvements"] == []
    assert d["headline"] == d["headline_simple"] == "No driving this week."
    assert "## Sessions\n- None this week." in d["markdown"]
    assert D.totals_line(d) is None
    assert D.previous_line(d) == "Week before: 1 session with a timed lap, 1 lap, 1 clean"
    assert D.md_escape("a_b*c") == "a\\_b\\*c"
