"""MotivationWorker: a goal is marked reached once and announced once, only for the seated owner's real driving;
the note handler never blocks or touches the database; earlier achievements are reconciled silently; race goals are
judged at the end of the session."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pitwall.core.live import LiveState
from pitwall.drivers import DriverService
from pitwall.model.telemetry import EventKind
from pitwall.motivation.service import MotivationService
from pitwall.motivation.worker import QUEUE_SIZE, MotivationWorker
from pitwall.storage import repo
from pitwall.storage.db import Database, DbWriter
from tests.unit.motivation_data import SeedLap, SeedSession, game_event, seed, seed_laps

T = time.time() - 3600


class Rig:
    def __init__(self, tmp: Path, include_synthetic: bool = False) -> None:
        self.db = Database(tmp / "w.sqlite3")
        self.writer = DbWriter(self.db)
        self.drivers = DriverService(self.db, self.writer, default_name="Sam")
        self.sam = self.drivers.default_id
        self.jo = self.drivers.create("Jo").id
        self.live = LiveState()
        self.notes: list[dict[str, Any]] = []
        self.live.subscribe(lambda kind, payload: self.notes.append(payload) if kind == "motivation" else None)
        self.worker = MotivationWorker(self.db, self.writer, self.live, include_synthetic=include_synthetic)
        self.svc = MotivationService(self.db, self.writer)

    def goal(self, driver: int, **body: Any) -> int:
        return int(self.svc.create_goal(driver, body)["id"])

    def go_live(self, sid: str, source: str = "udp:20777", synthetic: bool = False) -> None:
        self.live.reset_session(sid, source, synthetic)

    def lap(self, lap_id: int) -> None:
        self.live.notify("lap", {"lap": {"lap_id": lap_id}, "observations": [], "coach": None})
        self.worker.join()

    def end(self) -> None:
        self.live.on_event(game_event(EventKind.SESSION_ENDED, {}))
        self.worker.join()

    def status(self, gid: int) -> dict[str, Any]:
        with self.db.read() as c:
            g = repo.get_goal(c, gid)
        assert g is not None
        return g

    def close(self) -> None:
        self.worker.close()
        self.writer.close()


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[Rig]:
    r = Rig(tmp_path)
    yield r
    r.close()


def test_a_lap_reaches_a_goal_once(rig: Rig) -> None:
    seed(rig.writer, SeedSession("old", rig.sam, T - 600, seed_laps([71_745])))
    gid = rig.goal(rig.sam, kind="lap_time", target=70_000, from_session_id="old")
    ids = seed(rig.writer, SeedSession("s1", rig.sam, T, seed_laps([70_400, 69_981, 69_900])))
    rig.go_live("s1")
    rig.lap(ids[0])
    assert rig.notes == [] and rig.status(gid)["status"] == "active"
    assert rig.status(gid)["baseline"] == 71_745  # the PB when the goal was set
    rig.lap(ids[1])
    (note,) = rig.notes
    assert note["kind"] == "goals_achieved" and note["session_id"] == "s1" and note["driver_id"] == rig.sam
    assert (note["lap_id"], note["lap_number"]) == (ids[1], 2)
    (g,) = note["goals"]
    assert (g["id"], g["title"], g["title_simple"], g["value"]) == (
        gid,
        "A lap under 1:10.000",
        "Beat 1:10.000",
        69_981,
    )
    assert g["scope_text"] == "Austria · Haas" and g["track_name"] == "Austria"
    stored = rig.status(gid)
    assert (stored["status"], stored["achieved_session_id"], stored["achieved_lap_id"], stored["achieved_value"]) == (
        "achieved",
        "s1",
        ids[1],
        69_981,
    )
    rig.lap(ids[2])  # evaluated again: nothing new
    rig.lap(ids[1])
    assert len(rig.notes) == 1


def test_replays_synthetic_and_other_drivers_are_ignored(rig: Rig) -> None:
    gid = rig.goal(rig.sam, kind="clean_streak", target=2)
    rep = seed(rig.writer, SeedSession("rep", rig.sam, T, seed_laps([70_000] * 3), source="replay:x.pwcap"))
    rig.go_live("rep", "replay:x.pwcap")
    rig.lap(rep[-1])
    syn = seed(rig.writer, SeedSession("syn", rig.sam, T + 60, seed_laps([70_000] * 3), synthetic=True))
    rig.go_live("syn", synthetic=True)
    rig.lap(syn[-1])
    jo = seed(rig.writer, SeedSession("jo", rig.jo, T + 120, seed_laps([70_000] * 3)))
    rig.go_live("jo")
    rig.lap(jo[-1])
    assert rig.notes == [] and rig.status(gid)["status"] == "active"


def test_synthetic_counts_only_with_the_test_flag(tmp_path: Path) -> None:
    r = Rig(tmp_path, include_synthetic=True)
    try:
        gid = r.goal(r.sam, kind="clean_streak", target=2)
        syn = seed(r.writer, SeedSession("syn", r.sam, T, seed_laps([70_000] * 3), synthetic=True))
        r.go_live("syn", synthetic=True)
        r.lap(syn[1])
        assert len(r.notes) == 1 and r.status(gid)["status"] == "achieved"
    finally:
        r.close()


def test_a_goal_met_earlier_is_reconciled_silently(rig: Rig) -> None:
    gid = rig.goal(rig.sam, kind="clean_streak", target=3)
    # driving the worker never saw (a session re-assigned to Sam later, or a dropped note)
    seed(rig.writer, SeedSession("missed", rig.sam, T, seed_laps([70_000] * 4)))
    now = seed(rig.writer, SeedSession("now", rig.sam, T + 600, seed_laps([71_000])))
    rig.go_live("now")
    rig.lap(now[0])
    assert rig.notes == []
    stored = rig.status(gid)
    assert stored["status"] == "achieved" and stored["achieved_session_id"] == "missed"


def test_race_goal_at_session_end(rig: Rig) -> None:
    gid = rig.goal(rig.sam, kind="race_clean", target=1, params={"rule": "no_contact"})
    events = [game_event(EventKind.PENALTY, {"penaltyType": 5, "vehicleIdx": 19, "player_idx": 19})]  # a warning
    ids = seed(
        rig.writer,
        SeedSession("race", rig.sam, T, seed_laps([88_000, 78_000, 78_100]), total_laps=3, events=events),
    )
    rig.go_live("race")
    rig.lap(ids[-1])
    assert rig.notes == []  # judged at the end, not on a lap
    rig.end()
    (note,) = rig.notes
    assert note["lap_id"] is None and note["goals"][0]["kind"] == "race_clean"
    assert rig.status(gid)["achieved_lap_id"] == ids[-1]
    rig.end()
    assert len(rig.notes) == 1


def test_race_last_lap_after_the_end(rig: Rig) -> None:
    rig.goal(rig.sam, kind="race_clean", target=1, params={"rule": "no_penalties"})
    ids = seed(rig.writer, SeedSession("race", rig.sam, T, seed_laps([88_000, 78_000]), total_laps=3))
    rig.go_live("race")
    rig.end()  # the last lap is still being analysed
    assert rig.notes == []
    last = rig.writer.call(lambda c: repo.insert_lap(c, "race", _trace(3, 78_100), None))
    assert last > ids[-1]
    rig.lap(last)
    assert len(rig.notes) == 1 and rig.notes[0]["goals"][0]["kind"] == "race_clean"


def _trace(n: int, ms: int) -> Any:
    from tests.unit.motivation_data import trace

    return trace(SeedLap(n, ms))


class _Untouchable:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the note handler touched the database ({name})")


def test_note_handler_is_o1_and_never_blocks(tmp_path: Path) -> None:
    live = LiveState()
    w = MotivationWorker(_Untouchable(), _Untouchable(), live)  # type: ignore[arg-type]
    w.close()  # no consumer: the queue fills up
    for i in range(QUEUE_SIZE):
        w._q.put_nowait(("lap", "x", i))
    live.reset_session("s", "udp:20777", False)
    t0 = time.perf_counter()
    w._on_note("lap", {"lap": {"lap_id": 1}})
    w._on_note("event", {"kind": "session_ended"})
    w._on_note("event", {"kind": "lights_out"})  # ignored
    w._on_note("motivation", {"kind": "goals_achieved"})  # its own notes are ignored
    assert time.perf_counter() - t0 < 0.05
    assert w.dropped == 2
