"""A service restart in the middle of a game session must continue the same pitwall session (no split race)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest

from pitwall.core.lap_processor import AnalysisWorker
from pitwall.core.live import LiveState
from pitwall.core.session import SessionManager
from pitwall.model.telemetry import CarFrame, EventKind, Game, GameEvent, SessionInfo
from pitwall.storage import repo
from pitwall.storage.db import Database, DbWriter

SOURCE = "udp:20777"


class _Jobs:
    def __init__(self) -> None:
        self.jobs: list[Any] = []

    def submit(self, job: Any) -> None:
        self.jobs.append(job)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[tuple[Database, DbWriter]]:
    db = Database(tmp_path / "t.sqlite3")
    writer = DbWriter(db)
    yield db, writer
    writer.close()


def manager(writer: DbWriter, db: Database, *, resume: bool = True, cand_driver: int | None = None) -> SessionManager:
    cand = None
    if resume:
        writer.flush()
        with db.read() as c:
            cand = repo.last_live_session(c, SOURCE)
        if cand is not None and cand_driver is not None:
            cand["driver_id"] = cand_driver  # the previous session belonged to someone else
    return SessionManager(writer, LiveState(), cast(AnalysisWorker, _Jobs()), source=SOURCE, resume_candidate=cand)


def info(uid: str, t_ns: int) -> SessionInfo:
    return SessionInfo(game=Game.F1_25, t_recv_ns=t_ns, session_uid=uid, track_id="f1:11", track_length_m=5793.0)


def frame(t_ns: int, d: float) -> CarFrame:
    return CarFrame(game=Game.F1_25, t_recv_ns=t_ns, lap_number=2, lap_distance_m=d, speed_kph=300.0)


def sessions(db: Database) -> list[dict[str, Any]]:
    with db.read() as c:
        return [dict(r) for r in c.execute("SELECT id, game_session_uid, ended_unix FROM sessions ORDER BY rowid")]


def drive_then_stop(writer: DbWriter, db: Database, uid: str) -> str:
    sm = manager(writer, db, resume=False)
    sm.handle(info(uid, 1))
    for i in range(10):
        sm.handle(frame(2 + i, 100.0 + i))
    sid = sm.session_id
    assert sid is not None
    sm.end()  # what Runtime.close() does when the service stops
    writer.flush()
    return sid


def test_restart_mid_session_continues_the_same_session(store: tuple[Database, DbWriter]) -> None:
    db, writer = store
    first = drive_then_stop(writer, db, "4569")
    sm = manager(writer, db)
    sm.handle(frame(100, 900.0))  # frames arrive before the next Session packet (2 Hz): a new row is created...
    sm.handle(GameEvent(game=Game.F1_25, t_recv_ns=101, kind=EventKind.BUTTON, payload={"buttonStatus": 0}))
    assert sm.session_id != first
    sm.handle(info("4569", 102))  # ...and folded back in once the game confirms it is the same session
    writer.flush()
    assert sm.session_id == first and sm.sessions_resumed == 1
    rows = sessions(db)
    assert [r["id"] for r in rows] == [first] and rows[0]["ended_unix"] is None


def test_a_new_game_session_after_restart_is_a_new_pitwall_session(store: tuple[Database, DbWriter]) -> None:
    db, writer = store
    first = drive_then_stop(writer, db, "4569")
    sm = manager(writer, db)
    sm.handle(info("9999", 100))
    writer.flush()
    assert sm.session_id != first and sm.sessions_resumed == 0 and len(sessions(db)) == 2


def test_no_resume_for_another_driver(store: tuple[Database, DbWriter]) -> None:
    db, writer = store
    drive_then_stop(writer, db, "4569")
    sm = manager(writer, db, cand_driver=7)  # the interrupted session was another driver's
    sm.handle(info("4569", 100))
    writer.flush()
    assert sm.sessions_resumed == 0 and len(sessions(db)) == 2


def test_no_resume_for_replays_or_synthetic(store: tuple[Database, DbWriter]) -> None:
    db, writer = store
    drive_then_stop(writer, db, "4569")
    with db.read() as c:
        cand = repo.last_live_session(c, SOURCE)
    replay = SessionManager(
        writer, LiveState(), cast(AnalysisWorker, _Jobs()), source="replay:x.pwcap", resume_candidate=cand
    )
    replay.handle(info("4569", 100))
    synthetic = SessionManager(
        writer, LiveState(), cast(AnalysisWorker, _Jobs()), source=SOURCE, synthetic=True, resume_candidate=cand
    )
    synthetic.handle(info("4569", 200))
    writer.flush()
    assert replay.sessions_resumed == 0 and synthetic.sessions_resumed == 0


def test_resume_refuses_to_merge_a_session_that_has_laps(store: tuple[Database, DbWriter]) -> None:
    _db, writer = store
    with pytest.raises(ValueError, match="already has laps"):
        writer.call(lambda c: _merge_with_laps(c))


def _merge_with_laps(c: Any) -> None:
    repo.insert_session(c, "a", "f1_25", SOURCE, False, None, 0)
    repo.insert_session(c, "b", "f1_25", SOURCE, False, None, 0)
    c.execute(
        "INSERT INTO laps (session_id, lap_number, clean, n_samples, trace, created_unix) VALUES ('b', 1, 0, 0, x'', 0)"
    )
    repo.resume_session(c, "a", "b")


def test_real_stream_after_the_synthetic_demo_is_not_synthetic(store: tuple[Database, DbWriter]) -> None:
    """The synthetic demo streamed over the live listener, then a real game on the same listener (no restart)."""
    db, writer = store
    from pitwall.model.synthetic import SYNTHETIC_SESSION_UID

    live = LiveState()
    sm = SessionManager(writer, live, cast(AnalysisWorker, _Jobs()), source=SOURCE)
    demo = info(str(SYNTHETIC_SESSION_UID), 100)
    sm.handle(demo)
    assert sm.synthetic and demo.track_id.startswith("synthetic:")
    real = info("4569", 200)
    sm.handle(real)
    writer.flush()
    assert not sm.synthetic and not live.synthetic
    assert real.track_id == "f1:11"
    with db.read() as c:
        rows = [
            tuple(r)
            for r in c.execute(
                "SELECT game_session_uid, synthetic, ended_unix IS NOT NULL FROM sessions ORDER BY rowid"
            )
        ]
    assert rows == [(str(SYNTHETIC_SESSION_UID), 1, 1), ("4569", 0, 0)]
