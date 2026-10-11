"""Engineer facts about goals and progress, the ``goals`` intent, and grounded deterministic answers."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, timedelta
from datetime import time as clock
from pathlib import Path

import pytest

from pitwall.ai.engineer import RaceEngineer, detect_intent
from pitwall.ai.facts import FactSheet, build_fact_sheet
from pitwall.ai.grounding import check_grounding
from pitwall.core.session_analysis import SessionAnalyzer
from pitwall.drivers import DriverService
from pitwall.motivation.facts import add_motivation_facts
from pitwall.motivation.service import MotivationService
from pitwall.storage import repo
from pitwall.storage.db import Database, DbWriter
from tests.unit.motivation_data import SeedSession, seed, seed_laps

# noon on this week's Monday: every session of a test falls in the current week, whatever day the tests run
T = datetime.combine(date.today() - timedelta(days=date.today().weekday()), clock(12)).timestamp()


@pytest.mark.parametrize(
    ("question", "intent"),
    [
        ("How am I doing on my goal?", "goals"),
        ("what's my target lap time", "lap_times"),  # as before goals (motivation review #1, v0.2.0 plan 4.2)
        ("any badges?", "goals"),
        ("how long is my clean lap streak", "goals"),
        ("how many laps this week", "goals"),
        ("how many sessions this week?", "goals"),
        ("what should I work on this week", "focus"),
        ("what's my fuel target", "fuel"),
        ("how was my last lap", "last_lap"),
        ("what's my best lap", "lap_times"),
    ],
)
def test_intents(question: str, intent: str) -> None:
    assert detect_intent(question).name == intent


@pytest.fixture
def store(tmp_path: Path) -> Iterator[tuple[Database, DbWriter, DriverService]]:
    db = Database(tmp_path / "e.sqlite3")
    w = DbWriter(db)
    yield db, w, DriverService(db, w, default_name="Sam")
    w.close()


def sheet_for(db: Database, sid: str) -> FactSheet:
    sa = SessionAnalyzer(db).analyse(sid)
    assert sa is not None
    sheet = build_fact_sheet(sa)
    add_motivation_facts(sheet, db, sa)
    return sheet


async def test_goal_facts_and_a_grounded_answer(store: tuple[Database, DbWriter, DriverService]) -> None:
    db, w, drivers = store
    sam = drivers.default_id
    seed(w, SeedSession("old", sam, T - 600, seed_laps([71_745])))
    svc = MotivationService(db, w)
    gid = int(svc.create_goal(sam, {"kind": "lap_time", "target": 70_000, "from_session_id": "old"})["id"])
    ids = seed(w, SeedSession("s1", sam, T, seed_laps([70_549, 69_981])))
    w.call(lambda c: repo.mark_goal_achieved(c, gid, unix=T + 60, session_id="s1", lap_id=ids[1], value=69_981))
    svc.create_goal(sam, {"kind": "lap_time", "target": 69_500, "from_session_id": "s1"})
    seed(w, SeedSession("s2", sam, T + 600, seed_laps([69_700])))
    sheet = sheet_for(db, "s1")
    goals = [f for f in sheet.facts if f.topic == "goals"]
    assert (
        goals[0].text == "Goal reached this session by Sam: a lap under 1:10.000 at Austria (Haas); 1:09.981 on lap 2."
    )
    assert goals[0].say == "Goal reached this session: a lap under 1:10.000 at Austria, with 1:09.981 on lap 2."
    assert goals[1].text.startswith("Sam's goal (active since ") and goals[1].text.endswith(
        ": a lap under 1:09.500 at Austria (Haas); best since set 1:09.700, 0.200s to go."
    )
    progress = [f for f in sheet.facts if f.topic == "progress"]
    assert progress[0].text == "This week (from Monday): 3 sessions, 4 laps, 4 clean."
    assert (
        progress[1].text == "Clean laps in a row: best this session 2, best ever 2; weeks in a row with a session: 1."
    )
    ans = await RaceEngineer(None).answer("How am I doing on my goal?", sheet)
    assert ans.intent == "goals" and ans.fallback and ans.grounded
    assert check_grounding(ans.cited_text, [f for f in sheet.facts]).ok
    assert ans.text.startswith("Goal reached this session: a lap under 1:10.000 at Austria, with 1:09.981 on lap 2.")
    assert "Your best since you set it is 1:09.700, 0.200s to go." in ans.text
    assert "This week: 3 sessions and 4 laps, 4 of them clean." in ans.text
    assert "[F" not in ans.text


async def test_no_goals(store: tuple[Database, DbWriter, DriverService]) -> None:
    db, w, drivers = store
    seed(w, SeedSession("s1", drivers.default_id, T, seed_laps([71_000])))
    sheet = sheet_for(db, "s1")
    (g,) = [f for f in sheet.facts if f.topic == "goals"]
    assert g.text == "Sam has no active goals." and g.say == "You have no goals set at the moment."
    ans = await RaceEngineer(None).answer("what are my goals", sheet)
    assert ans.text.startswith("You have no goals set at the moment.") and ans.grounded


def test_no_driver_no_facts(store: tuple[Database, DbWriter, DriverService]) -> None:
    db, w, _drivers = store
    seed(w, SeedSession("rep", None, T, seed_laps([71_000]), source="replay:x.pwcap"))
    sheet = sheet_for(db, "rep")
    assert not [f for f in sheet.facts if f.topic in ("goals", "progress")]


def test_errors_never_break_an_answer(store: tuple[Database, DbWriter, DriverService]) -> None:
    db, w, drivers = store
    seed(w, SeedSession("s1", drivers.default_id, T, seed_laps([71_000])))
    sa = SessionAnalyzer(db).analyse("s1")
    assert sa is not None
    sheet = build_fact_sheet(sa)
    n = len(sheet.facts)

    class Broken:
        def read(self) -> None:
            raise RuntimeError("disk on fire")

    add_motivation_facts(sheet, Broken(), sa)  # type: ignore[arg-type]
    assert len(sheet.facts) == n
