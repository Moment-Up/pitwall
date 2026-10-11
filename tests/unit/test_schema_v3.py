"""Schema v3 (lane motivation): the goals table, the migration from a v2 database, and ``total_laps`` in
``sessions.info``. The current version is v4 (pace vs AI difficulty, ``test_db_v4_migration.py``): a database opened
today is stamped 4, with goals."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from pitwall.model.telemetry import Game, SessionInfo, SessionType
from pitwall.storage import repo
from pitwall.storage.db import SCHEMA_VERSION, Database, DbWriter


def version(db: Database) -> str | None:
    with db.read() as c:
        return repo.get_meta(c, "schema_version")


def tables(db: Database) -> set[str]:
    with db.read() as c:
        return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'index')")}


def test_fresh_database_has_goals(tmp_path: Path) -> None:
    db = Database(tmp_path / "fresh.sqlite3")
    assert SCHEMA_VERSION == 4 and version(db) == "4"
    assert {"goals", "ix_goals_driver"} <= tables(db)


def make_v2(path: Path) -> None:
    """A v2 database as an older build leaves it: no goals table (nor v4's session_ai_pace), version 2, with a driver
    and a session."""
    db = Database(path)
    with db.read() as c:
        c.execute("DROP INDEX ix_goals_driver")
        c.execute("DROP TABLE goals")
        c.execute("DROP TABLE session_ai_pace")
        c.execute("UPDATE meta SET value='2' WHERE key='schema_version'")
        c.execute("INSERT INTO drivers(name, created_unix, preferences) VALUES('Sam', 0, '{}')")
        repo.insert_session(c, "s1", "f1_25", "udp:20777", False, None, None, driver_id=1)
        c.commit()


def test_v2_database_migrates_and_reopening_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite3"
    make_v2(path)
    raw = sqlite3.connect(path)
    assert raw.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "2"
    assert raw.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='goals'").fetchone()[0] == 0
    raw.close()
    db = Database(path)
    assert version(db) == "4" and {"goals", "ix_goals_driver", "session_ai_pace"} <= tables(db)
    with db.read() as c:
        assert repo.get_session(c, "s1") is not None and repo.get_driver(c, 1) is not None
    Database(path)  # again: nothing changes
    assert version(Database(path)) == "4"


def test_deleting_a_driver_deletes_their_goals(tmp_path: Path) -> None:
    db = Database(tmp_path / "fk.sqlite3")
    w = DbWriter(db)
    try:

        def job(c: sqlite3.Connection) -> int:
            sam = repo.insert_driver(c, "Sam", {})
            repo.insert_driver(c, "Jo", {})
            return repo.insert_goal(
                c,
                driver_id=sam,
                kind="clean_streak",
                target=8,
                params={},
                game=None,
                track_id=None,
                track_name=None,
                track_length_m=None,
                car_id=None,
                car_class=None,
                car_name=None,
                baseline=None,
                source="manual",
                basis=None,
            )

        gid = w.call(job)
        with db.read() as c:
            g = repo.get_goal(c, gid)
            assert g is not None and g["after_lap_id"] == 0 and g["params"] == {} and g["basis"] is None
        w.call(lambda c: repo.delete_driver(c, 1))
        with db.read() as c:
            assert repo.get_goal(c, gid) is None
    finally:
        w.close()


def test_session_info_stores_total_laps(tmp_path: Path) -> None:
    db = Database(tmp_path / "info.sqlite3")
    info = SessionInfo(game=Game.F1_25, track_id="f1:17", session_type=SessionType.RACE, total_laps=71)
    with db.read() as c:
        repo.insert_session(c, "s1", "f1_25", "udp:20777", False, None, None)
        repo.update_session_info(c, "s1", info)
        c.commit()
        s = repo.get_session(c, "s1")
        assert s is not None and s["info"]["total_laps"] == 71
        m = repo.motivation_session(c, "s1")
        assert m is not None and m["total_laps"] == 71
    unknown = SessionInfo(game=Game.GT7, track_id="gt7:x")
    with db.read() as c:
        repo.insert_session(c, "s2", "gt7", "udp:33740", False, None, None)
        repo.update_session_info(c, "s2", unknown)
        c.commit()
        s2 = repo.get_session(c, "s2")
        assert s2 is not None and "total_laps" not in s2["info"]  # unknown stays unknown
