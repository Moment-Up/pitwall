"""RECORDED tier: goals, race outcomes, recaps and badges on the committed real F1 25 PS5 excerpts.

The excerpts are byte-for-byte windows of real races (gaps between windows are excerpt artefacts), so every lap is
legitimately ``incomplete``: no race is "finished", there is no clean lap, and nothing may be awarded. The real event
payloads must give the player no incidents. Replays are nobody's driving, so for goals and badges the replayed
session is re-tagged as a driver's in the test database only.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from pitwall.config import Settings
from pitwall.core.runtime import Runtime
from pitwall.motivation import rules
from pitwall.motivation.model import LapRow, SessionRow
from pitwall.motivation.service import MotivationService, load_history
from pitwall.storage import repo

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "recorded"
AUSTRIA = FIXTURES / "f1_25_2025_ps5_austria_race-excerpt.pwcap"
MONZA = FIXTURES / "f1_25_2025_ps5_monza_race-excerpt.pwcap"

pytestmark = [
    pytest.mark.recorded,
    pytest.mark.skipif(not (AUSTRIA.exists() and MONZA.exists()), reason="real PS5 excerpts not present"),
]


@pytest.fixture(scope="module")
def replayed(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Runtime, dict[str, str]]]:
    data = tmp_path_factory.mktemp("recorded-motivation")
    rt = Runtime(Settings(data_dir=data, llm_enabled=False, voice_enabled=False))
    sids: dict[str, str] = {}
    try:
        for name, cap in (("austria", AUSTRIA), ("monza", MONZA)):
            r = rt.start_replay(cap, speed=None)
            assert r.done.wait(120)
            rt.worker.join()
            rt.writer.flush()
            with rt.db.read() as c:
                sid = repo.latest_session_id(c)
            assert sid is not None
            sids[name] = sid
        rt.motivation.join()
        yield rt, sids
    finally:
        rt.close()


def test_austria_race_is_not_finished_and_has_no_player_incidents(replayed: tuple[Runtime, dict[str, str]]) -> None:
    rt, sids = replayed
    sid = sids["austria"]
    with rt.db.read() as c:
        row = repo.motivation_session(c, sid)
        assert row is not None
        laps = repo.motivation_laps(c, [sid])[sid]
        events = repo.motivation_events(c, [sid])[sid]
        kinds = {e["kind"] for e in repo.list_events(c, sid)}
    s = SessionRow.from_row(row)
    assert s.session_type == "race" and s.total_laps == 3  # stored from schema v3 on
    assert {"lights_out", "session_ended"} <= kinds
    rows = [LapRow.from_row(d) for d in laps]
    assert rows and all("incomplete" in lap.flags for lap in rows)
    o = rules.race_outcome(s, rows, events)
    assert o.race and o.from_start and not o.finished and not o.evaluable
    assert (o.contacts, o.penalties, o.flashbacks, o.resets) == (0, 0, 0, 0)


def test_recap_of_the_replayed_race(replayed: tuple[Runtime, dict[str, str]]) -> None:
    rt, sids = replayed
    r = MotivationService(rt.db).recap(sids["austria"])
    assert r is not None and r["replay"] and r["driver_id"] is None
    assert r["things"]["went_well"] is None and r["why_empty"]["went_well"]
    assert r["things"]["work_on"]["source"] == "no_clean_lap"
    assert r["things"]["progress"] is None and r["why_empty"]["progress"] == "Replays are not anyone's driving"


def test_no_badges_and_no_race_goal_from_incomplete_laps(replayed: tuple[Runtime, dict[str, str]]) -> None:
    rt, sids = replayed
    driver = rt.drivers.default_id

    def retag(c: sqlite3.Connection) -> None:  # this test database only: the replays become the driver's driving
        for sid in sids.values():
            repo.rewrite_session_origin(c, sid, source="udp:recorded", started_unix=1.79e9, ended_unix=1.79e9 + 600)
            repo.set_session_driver(c, sid, driver)

    rt.writer.call(retag)
    svc = MotivationService(rt.db, rt.writer)
    body = svc.badges_response(driver)
    assert body["badges"] == []
    assert body["streaks"]["clean_laps"]["best"] == 0
    goal = svc.create_goal(driver, {"kind": "race_clean", "target": 1, "params": {"rule": "no_penalties"}})
    assert svc.on_session_end(sids["austria"]) is None
    with rt.db.read() as c:
        g = repo.get_goal(c, int(goal["id"]))
        h = load_history(c, driver)
    assert g is not None and g["status"] == "active"
    assert [s.id for s in h.sessions] and all(not rules.fastest_clean(h.laps_of(s.id)) for s in h.sessions)
