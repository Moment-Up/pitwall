"""Schema v3 (race strategy: ``strategy_laps``, ``pit_stops``) on a v2 database, on a scratch file only.

The v2 database is built from the frozen v2 DDL, and the version is read from ``SCHEMA_VERSION``: when the race
strategy lands next to other new tables it is renumbered (as goals and AI pace were), and this test still holds."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from pitwall.storage import repo
from pitwall.storage.db import SCHEMA_VERSION, Database
from tests.unit.schema_v2_frozen import V2_DDL


def _v2_database(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(V2_DDL)
    conn.execute("INSERT INTO meta(key, value) VALUES('schema_version', '2')")
    conn.execute(
        "INSERT INTO sessions(id, game, started_unix, source, synthetic, session_type) "
        "VALUES('old1', 'f1_25', 1.0, 'udp:20777', 0, 'race')"
    )
    conn.execute(
        "INSERT INTO laps(session_id, lap_number, lap_time_ms, clean, n_samples, trace, created_unix) "
        "VALUES('old1', 1, 80000, 1, 0, x'', 1.0)"
    )
    conn.commit()
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "strategy_laps" not in names and "pit_stops" not in names
    conn.close()


def _tables(db: Database) -> set[str]:
    with db.read() as c:
        return {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_v2_database_migrates_to_v3_and_cascades(tmp_path: Path) -> None:
    path = tmp_path / "v2.sqlite"
    _v2_database(path)
    db = Database(path)
    assert SCHEMA_VERSION >= 3
    assert {"strategy_laps", "pit_stops"} <= _tables(db)
    with db.read() as c:
        assert repo.get_meta(c, "schema_version") == str(SCHEMA_VERSION)
        assert repo.get_session(c, "old1") is not None and len(repo.list_laps(c, "old1")) == 1
    db2 = Database(path)  # reopening is idempotent
    with db2.read() as c:
        assert repo.get_meta(c, "schema_version") == str(SCHEMA_VERSION) and len(repo.list_laps(c, "old1")) == 1
        repo.upsert_strategy_lap(c, "old1", 1, {"v": 1, "lap": 1, "position": 5})
        repo.upsert_strategy_lap(c, "old1", 1, {"v": 1, "lap": 1, "position": 4})  # rewrite after a flashback
        stop = {
            "car_index": 14,
            "is_player": False,
            "entry_lap": 65,
            "exit_lap": 66,
            "laps_ms": [81575, 92836],
            "pit_loss_ms": 18911,
            "lane_time_ms": 20019,
            "stationary_ms": 3353,
            "excluded": None,
        }
        repo.upsert_pit_stop(c, "old1", stop)
        repo.upsert_pit_stop(c, "old1", {**stop, "pace_after_ms": 74324})  # same car and entry lap: an update
        c.commit()
        assert repo.list_strategy_laps(c, "old1") == [{"v": 1, "lap": 1, "position": 4}]
        (row,) = repo.list_pit_stops(c, "old1")
        assert row["laps_ms"] == [81575, 92836] and row["pace_after_ms"] == 74324 and row["is_player"] is False
        c.execute("DELETE FROM sessions WHERE id='old1'")
        c.commit()
        assert repo.list_strategy_laps(c, "old1") == [] and repo.list_pit_stops(c, "old1") == []


def test_fresh_database_has_the_strategy_tables(tmp_path: Path) -> None:
    db = Database(tmp_path / "new.sqlite")
    assert {"strategy_laps", "pit_stops"} <= _tables(db)
