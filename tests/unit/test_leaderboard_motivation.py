"""The family leaderboard in motivation, the engineer and the radio: the family-record badge (badges, recap, digest
and the badge count), the engineer's record fact and its grounded deterministic answer, the worker's
``family_record`` note when a lap takes the record from another driver, and its one radio line through the
goal-line path."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pitwall.ai.engineer import RaceEngineer
from pitwall.ai.facts import FactSheet
from pitwall.ai.grounding import check_grounding
from pitwall.core.live import LiveState
from pitwall.core.session_analysis import SessionAnalysis
from pitwall.leaderboard import service as LS
from pitwall.leaderboard.facts import NO_RECORD_SAY, add_record_facts
from pitwall.motivation import badges as B
from pitwall.motivation.radio import GoalLineGate, goal_message, record_line, record_message
from pitwall.motivation.service import MotivationService, load_history
from pitwall.motivation.worker import MotivationWorker
from pitwall.storage import repo
from pitwall.storage.db import Database, DbWriter
from pitwall.voice.scheduler import TOPIC_KEY
from pitwall.voice.types import MessageKind, Priority
from tests.unit.leaderboard_data import AUSTRIA_KEY, DAY, T0, add_driver, add_lap, add_session

FAMILY_BADGE = f"family_record:{AUSTRIA_KEY}"


class Rig:
    """Sam (1:10.549) and Jo (1:13.616) at Austria in the Haas; Jo drove there a day later (a contested board)."""

    def __init__(self, tmp: Path) -> None:
        self.db = Database(tmp / "lbm.sqlite3")
        self.writer = DbWriter(self.db)

        def job(c: sqlite3.Connection) -> dict[str, Any]:
            sam, jo = add_driver(c, "Sam"), add_driver(c, "Jo")
            add_session(c, "s1", sam, started=T0)
            add_lap(c, "s1", 1, 71_745, created=T0 + 100)
            best = add_lap(c, "s1", 2, 70_549, created=T0 + 200)
            add_session(c, "j1", jo, started=T0 + DAY)
            add_lap(c, "j1", 1, 73_616, created=T0 + DAY + 100)
            return {"sam": sam, "jo": jo, "sam_best": best}

        self.ids = self.writer.call(job)
        self.sam, self.jo = int(self.ids["sam"]), int(self.ids["jo"])
        self.svc = MotivationService(self.db, self.writer, clock=lambda: T0 + 30 * DAY)

    def lap(self, sid: str, n: int, ms: int, created: float, driver: int | None = None, **kw: Any) -> int:
        def job(c: sqlite3.Connection) -> int:
            if repo.get_session(c, sid) is None:
                add_session(c, sid, driver, started=created - 60, **kw)
            return add_lap(c, sid, n, ms, created=created)

        return int(self.writer.call(job))

    def analysis(self, sid: str, driver: int, name: str) -> SessionAnalysis:
        with self.db.read() as c:
            session = repo.get_session(c, sid)
            laps = repo.list_laps(c, sid)
        assert session is not None
        return SessionAnalysis(session, laps, None, None, None, driver={"id": driver, "name": name})

    def close(self) -> None:
        self.writer.close()


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[Rig]:
    r = Rig(tmp_path)
    yield r
    r.close()


# ---------------------------------------------------------------------------------------------- badges
def test_the_holder_of_a_contested_record_gets_the_badge(rig: Rig) -> None:
    sam = rig.svc.badges_response(rig.sam)["badges"]
    (badge,) = [b for b in sam if b["kind"] == "family_record"]
    assert badge["key"] == FAMILY_BADGE and badge["fact_key"] == FAMILY_BADGE
    assert badge["title"] == "Family record at Austria"
    assert badge["title_simple"] == "You set the family record at Austria"
    assert badge["detail"] == "1:10.549 · Haas · Race · Dry"
    assert badge["session_id"] == "s1" and badge["lap_id"] == rig.ids["sam_best"] and badge["earned_unix"] == T0
    assert badge["scope"]["track_id"] == "f1:17" and badge["scope"]["car_id"] == "f1:team:7"
    assert not [b for b in rig.svc.badges_response(rig.jo)["badges"] if b["kind"] == "family_record"]


def test_taking_the_record_earns_it_once_and_names_who_held_it(rig: Rig) -> None:
    rig.lap("j2", 1, 70_400, T0 + 2 * DAY, rig.jo)
    rig.lap("j2", 2, 70_300, T0 + 2 * DAY + 60)  # Jo improves her own record: no second badge
    jo = [b for b in rig.svc.badges_response(rig.jo)["badges"] if b["kind"] == "family_record"]
    assert len(jo) == 1 and jo[0]["session_id"] == "j2"
    assert jo[0]["detail"] == "1:10.400 · Haas · Race · Dry, from Sam"
    # Sam keeps the badge he earned (badges are achievements, derived in time order)
    assert [b["key"] for b in rig.svc.badges_response(rig.sam)["badges"] if b["kind"] == "family_record"] == [
        FAMILY_BADGE
    ]
    recap = rig.svc.recap("j2")
    assert recap is not None and FAMILY_BADGE in [b["key"] for b in recap["badges_earned"]]


def test_the_badge_needs_an_identified_track_and_a_real_lap(rig: Rig) -> None:
    gt7 = {
        "game": "gt7",
        "track": "gt7:sf:0:100:90:920:340",
        "track_name": "Unidentified GT7 circuit (0.92 km)",
        "length": 913.3,
        "car": "gt7:car:919",
        "car_name": None,
        "session_type": "unknown",
        "weather": None,
        "formula": None,
    }
    rig.lap("g1", 1, 23_055, T0 + 3 * DAY, rig.sam, **gt7)
    rig.lap("g2", 1, 22_900, T0 + 4 * DAY, rig.jo, **gt7)
    with rig.db.read() as c:
        takes = LS.record_takes_for(c, rig.jo)
        history = load_history(c, rig.jo)
    assert [t.key.game for t in takes] == ["gt7"]  # the board has a record taken...
    assert B.family_record_badges(history, takes) == []  # ...but no badge: unidentified track, 23 s "lap"


def test_badges_follow_the_history_window(rig: Rig) -> None:
    with rig.db.read() as c:
        takes = LS.record_takes_for(c, rig.sam)
        history = load_history(c, rig.sam)
    assert [b.key for b in B.badges(history, (), takes) if b.kind == "family_record"] == [FAMILY_BADGE]
    assert [b.kind for b in B.badges(history.before(T0), (), takes)] == []
    digest = rig.svc.digest(rig.sam, week=None)
    assert all(b["kind"] != "family_record" for b in digest["badges"])  # earned weeks before "now"


# ---------------------------------------------------------------------------------------------- engineer
def test_record_fact_for_a_driver_behind_and_for_the_holder(rig: Rig) -> None:
    sheet = FactSheet()
    add_record_facts(sheet, rig.db, rig.analysis("j1", rig.jo, "Jo"))
    (fact,) = [f for f in sheet.facts if f.topic == "records"]
    assert fact.text == (
        "Family record on this board (Austria · Haas · Race · Dry; Braking assist medium, ABS on, Traction control "
        "full, Automatic gears, Racing line full): 1:10.549 by Sam, set Sat 10 Oct. Others: Jo 1:13.616 (3.067s "
        "behind)."
    )
    assert fact.say == "The family record here is 1:10.549, by Sam. Your best here is 3.067s off it."
    assert fact.data["gap_s"] == 3.067 and fact.data["board"] == AUSTRIA_KEY
    assert check_grounding(f"{fact.say} [{fact.id}]", sheet.facts).ok
    holder = FactSheet()
    add_record_facts(holder, rig.db, rig.analysis("s1", rig.sam, "Sam"))
    assert holder.facts[0].say == "You hold the family record here: 1:10.549."


def test_no_record_yet_and_sessions_without_a_board(rig: Rig) -> None:
    def wet(c: sqlite3.Connection) -> None:
        add_session(c, "wet", rig.jo, started=T0 + 5 * DAY, weather="heavy_rain")
        add_lap(c, "wet", 1, 80_000, created=T0 + 5 * DAY, clean=False)  # in the rain, but not clean

    rig.writer.call(wet)
    sheet = FactSheet()
    add_record_facts(sheet, rig.db, rig.analysis("wet", rig.jo, "Jo"))
    (fact,) = sheet.facts
    assert fact.say == NO_RECORD_SAY and "Austria · Haas · Race · Wet" in fact.text
    synthetic = rig.analysis("s1", rig.sam, "Sam")
    synthetic.session["synthetic"] = True
    none = FactSheet()
    add_record_facts(none, rig.db, synthetic)
    assert none.facts == []


async def test_record_questions_have_a_grounded_deterministic_answer(rig: Rig) -> None:
    sheet = FactSheet()
    add_record_facts(sheet, rig.db, rig.analysis("j1", rig.jo, "Jo"))
    engineer = RaceEngineer(None)
    for q in ("What's the family record here?", "Who's fastest in the family?"):
        ans = await engineer.answer(q, sheet, use_llm=False)
        assert ans.intent == "records" and ans.grounded
        assert "The family record here is 1:10.549, by Sam" in ans.text
    empty = await engineer.answer("Who holds the record at this track?", FactSheet(), use_llm=False)
    assert empty.text.startswith("There's no family board for this session")


# ---------------------------------------------------------------------------------------------- worker and radio
class LiveRig:
    def __init__(self, rig: Rig) -> None:
        self.rig = rig
        self.live = LiveState()
        self.notes: list[dict[str, Any]] = []
        self.live.subscribe(lambda kind, payload: self.notes.append(payload) if kind == LS.FAMILY_RECORD_NOTE else None)
        self.worker = MotivationWorker(rig.db, rig.writer, self.live)

    def drive(self, sid: str, lap_id: int, source: str = "udp:20777") -> None:
        if self.live.session_id != sid:
            self.live.reset_session(sid, source, False)
        self.live.notify("lap", {"lap": {"lap_id": lap_id}, "observations": [], "coach": None})
        self.worker.join()


def test_the_worker_announces_a_record_taken_from_another_driver_once(rig: Rig) -> None:
    lr = LiveRig(rig)
    try:
        now = time.time()
        slower = rig.lap("j3", 1, 71_000, now, rig.jo)
        lr.drive("j3", slower)
        assert lr.notes == []  # not the record
        took = rig.lap("j3", 2, 70_400, now + 60)
        lr.drive("j3", took)
        (note,) = lr.notes
        assert note["kind"] == "family_record" and note["key"] == AUSTRIA_KEY and note["lap_id"] == took
        assert (note["driver_name"], note["previous_driver_name"], note["previous_ms"]) == ("Jo", "Sam", 70_549)
        assert note["track_name"] == "Austria" and note["session_id"] == "j3" and note["lap_number"] == 2
        own = rig.lap("j3", 3, 70_300, now + 120)
        lr.drive("j3", own)
        assert len(lr.notes) == 1  # improving her own record is a personal best, not a new holder
        replay = rig.lap("rep", 1, 69_000, now + 180, rig.sam, source="replay:x.pwcap")
        lr.drive("rep", replay, source="replay:x.pwcap")
        assert len(lr.notes) == 1 and lr.worker.records == 1 and lr.worker.errors == 0
    finally:
        lr.worker.close()


NOTE = {
    "kind": "family_record",
    "session_id": "j3",
    "lap_id": 12,
    "lap_number": 2,
    "previous_driver_name": "Sam",
    "track_name": "Austria",
}


def test_record_line() -> None:
    assert record_line(NOTE, False) == "New family record at Austria: you took it from Sam."
    assert record_line(NOTE, True) == "You did it: the family record at Austria is yours, faster than Sam."
    long = {**NOTE, "track_name": "Unidentified GT7 circuit (3.80 km)"}
    assert record_line(long, False) == "New family record: you took it from Sam."
    assert record_line({**NOTE, "previous_driver_name": None}, False) is None


def test_record_message_goes_the_goal_line_way() -> None:
    gate = GoalLineGate()
    m = record_message(NOTE, gate, "j3", simple=False, to_speech=str.upper, now_mono=100.0)
    assert m is not None
    assert (m.kind, m.priority, m.bypass_quiet, m.needs_speak_window) == (
        MessageKind.GOAL,
        Priority.NORMAL,
        False,
        True,
    )
    assert m.speech == m.text.upper() and m.lap_number == 2 and m.id == "record-j3-12"
    assert m.meta[TOPIC_KEY] == "record:j3" and "lap_id" not in m.meta  # never holds the lap's coaching back
    assert "1:" not in m.text  # no lap time on the radio
    args: dict[str, Any] = {"simple": False, "to_speech": str, "now_mono": 100.0}
    assert record_message(NOTE, GoalLineGate(), "other", **args) is None  # not the live session
    assert record_message(NOTE, GoalLineGate(), "j3", voice_enabled=False, **args) is None
    assert record_message({**NOTE, "kind": "goals_achieved"}, GoalLineGate(), "j3", **args) is None
    # one gate with the goal lines: at most two such lines per session
    goal = {
        "kind": "goals_achieved",
        "session_id": "j3",
        "lap_id": 11,
        "goals": [{"id": 1, "kind": "clean_streak", "target": 5}],
    }
    assert goal_message(goal, gate, "j3", **args) is not None
    assert record_message(NOTE, gate, "j3", **args) is None


async def test_the_hub_says_the_record_line() -> None:
    from tests.unit.test_voice_hub import make_hub, settle

    hub, _client, sent, _stt, _sched = await make_hub()
    try:
        hub.live.reset_session("j3", "udp:20777", False)
        hub.live.notify(LS.FAMILY_RECORD_NOTE, dict(NOTE))
        await settle()
        said = [m for m in sent if isinstance(m, dict) and m.get("type") == "say" and m.get("id") == "record-j3-12"]
        assert [m["text"] for m in said] == ["New family record at Austria: you took it from Sam."]
    finally:
        await hub.stop()
