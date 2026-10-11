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
    assert (first["scope_text"], first["gain_ms"], first["new_track"]) == ("Suzuka", None, True)
    assert d["headline"] == "2 sessions, 4 laps, a new best at Austria"
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
        "2 sessions · 4 timed laps (3 clean) · 5 min of timed laps · 2 tracks · week before: 1 session, 2 laps\n"
        "\n"
        "## Sessions\n"
        "- Mon 5 Oct · Austria · Haas · Race · 3 laps (2 clean) · best 1:10.549 (new best)\n"
        "- Tue 6 Oct · Suzuka · F1 Generic · Race · 1 lap (1 clean) · best 1:36.360\n"
        "\n"
        "## Best improvements\n"
        "- Austria · Haas: 1:10.549, 1.196 s faster than before\n"
        "- First clean laps at Suzuka: 1:36.360\n"
        "\n"
        "## Goals\n"
        "- No goals set.\n"
        "\n"
        "## Badges this week\n"
        "- First clean lap at Suzuka (Tue 6 Oct)\n"
        "- First time under 1:11 at Austria (Mon 5 Oct)\n"
        "- 2 weeks in a row (Mon 5 Oct)\n"
        "\n"
        "## Streaks\n"
        "- Weeks in a row with a session: 2 (best 2)\n"
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


def test_empty_week() -> None:
    d = build(history((sess("old", LAST_WEEK), laps("old", [71_745]))))
    assert d["totals"]["sessions"] == 0 and d["sessions"] == [] and d["improvements"] == []
    assert d["headline"] == d["headline_simple"] == "No driving this week."
    assert "## Sessions\n- None this week." in d["markdown"]
    assert D.md_escape("a_b*c") == "a\\_b\\*c"
