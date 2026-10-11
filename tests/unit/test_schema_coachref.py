"""coachref schema v3: a v2 database (frozen copy of the v2 schema below, as the previous build left it) gains the
``reference_choices`` and ``drills`` tables when it is opened, idempotently and with concurrent openers; deleting a
driver removes their choices but keeps their drills (with no driver), like their laps."""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path

from pitwall.coach import drills as dr
from pitwall.drivers import DriverService
from pitwall.storage import repo
from pitwall.storage.db import SCHEMA_VERSION, Database, DbWriter

# The v2 schema (SCHEMA + the v2 indexes of storage/db.py at schema version 2), frozen here on purpose: the
# migration must keep working on databases written by that build whatever later versions change.
V2_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS drivers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    created_unix REAL NOT NULL,
    preferences TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    driver_id INTEGER REFERENCES drivers(id),
    game TEXT NOT NULL,
    platform TEXT,
    game_session_uid TEXT,
    track_id TEXT,
    track_name TEXT,
    track_length_m REAL,
    session_type TEXT,
    session_type_raw TEXT,
    car_id TEXT,
    car_name TEXT,
    weather TEXT NOT NULL DEFAULT '{}',
    assists TEXT NOT NULL DEFAULT '{}',
    info TEXT NOT NULL DEFAULT '{}',
    started_unix REAL NOT NULL,
    ended_unix REAL,
    source TEXT NOT NULL,              -- live | replay | import
    synthetic INTEGER NOT NULL DEFAULT 0,
    capture_path TEXT,
    capture_t_start_ns INTEGER,
    capture_t_end_ns INTEGER
);
CREATE INDEX IF NOT EXISTS ix_sessions_track ON sessions(game, track_id, car_id);

CREATE TABLE IF NOT EXISTS laps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    lap_number INTEGER NOT NULL,
    lap_time_ms INTEGER,
    s1_ms INTEGER, s2_ms INTEGER, s3_ms INTEGER,
    valid INTEGER,
    clean INTEGER NOT NULL,
    flags TEXT NOT NULL DEFAULT '[]',
    meta TEXT NOT NULL DEFAULT '{}',
    setup_fp TEXT,
    n_samples INTEGER NOT NULL,
    trace BLOB NOT NULL,
    created_unix REAL NOT NULL,
    UNIQUE(session_id, lap_number)
);
CREATE INDEX IF NOT EXISTS ix_laps_session ON laps(session_id);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    t_recv_ns INTEGER,
    session_time_s REAL,
    kind TEXT NOT NULL,
    code TEXT,
    payload TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_events_session ON events(session_id);

CREATE TABLE IF NOT EXISTS setups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    t_recv_ns INTEGER,
    fingerprint TEXT NOT NULL,
    params TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS track_models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game TEXT NOT NULL,
    track_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    created_unix REAL NOT NULL,
    model TEXT NOT NULL,
    UNIQUE(game, track_id, version)
);

CREATE TABLE IF NOT EXISTS reference_laps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lap_id INTEGER NOT NULL REFERENCES laps(id) ON DELETE CASCADE,
    game TEXT NOT NULL,
    track_id TEXT NOT NULL,
    car_id TEXT,
    kind TEXT NOT NULL,                -- pinned | personal_best | median | imported
    label TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_unix REAL NOT NULL,
    driver_id INTEGER REFERENCES drivers(id)   -- v2; last so fresh and migrated tables have the same layout
);

CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    lap_id INTEGER REFERENCES laps(id) ON DELETE CASCADE,
    ref_lap_id INTEGER REFERENCES laps(id) ON DELETE SET NULL,
    obs_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    corner TEXT,
    metric TEXT,
    value REAL,
    unit TEXT,
    impact_s REAL,
    confidence REAL,
    positive INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL,
    evidence TEXT NOT NULL DEFAULT '{}',
    track_model_version INTEGER,
    created_unix REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_obs_session ON observations(session_id);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    created_unix REAL NOT NULL,
    role TEXT NOT NULL,                -- user | engineer
    text TEXT NOT NULL,
    intent TEXT,
    facts TEXT,
    model TEXT,
    latency_ms INTEGER,
    grounded INTEGER,
    fallback INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS setup_experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game TEXT NOT NULL,
    track_id TEXT,
    car_id TEXT,
    created_unix REAL NOT NULL,
    hypothesis TEXT NOT NULL,
    parameter TEXT NOT NULL,
    from_value REAL,
    to_value REAL,
    status TEXT NOT NULL DEFAULT 'proposed',   -- proposed | running | concluded | abandoned
    before_session_id TEXT,
    after_session_id TEXT,
    before_metrics TEXT,
    after_metrics TEXT,
    conclusion TEXT
);

CREATE INDEX IF NOT EXISTS ix_sessions_driver ON sessions(driver_id, started_unix);
CREATE INDEX IF NOT EXISTS ix_reference_lookup ON reference_laps(game, track_id, driver_id, active);
CREATE INDEX IF NOT EXISTS ix_laps_session_clean ON laps(session_id, clean, lap_time_ms);
"""


def make_v2_db(path: Path) -> None:
    with closing(sqlite3.connect(path)) as c:
        c.executescript(V2_SCHEMA)
        c.execute("INSERT INTO meta(key, value) VALUES('schema_version', '2')")
        c.execute("INSERT INTO drivers(id, name, created_unix) VALUES(1, 'Ann', 1.0), (2, 'Sam', 1.0)")
        c.execute("INSERT INTO meta(key, value) VALUES('default_driver_id', '1'), ('active_driver_id', '1')")
        c.execute(
            "INSERT INTO sessions(id, driver_id, game, track_id, car_id, started_unix, source) "
            "VALUES('s1', 2, 'f1_25', 'f1:7', 'f1:team:41', 1000.0, 'udp:20777')"
        )
        c.execute(
            "INSERT INTO laps(session_id, lap_number, lap_time_ms, clean, n_samples, trace, created_unix) "
            "VALUES('s1', 1, 90000, 1, 0, x'', 1000.0)"
        )
        c.execute(
            "INSERT INTO reference_laps(lap_id, game, track_id, car_id, kind, created_unix, driver_id) "
            "VALUES(1, 'f1_25', 'f1:7', 'f1:team:41', 'pinned', 1000.0, 2)"
        )
        c.commit()


def tables(c: sqlite3.Connection) -> set[str]:
    return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'index')")}


def test_v2_database_migrates_idempotently(tmp_path: Path) -> None:
    assert SCHEMA_VERSION >= 3
    path = tmp_path / "v2.sqlite3"
    make_v2_db(path)
    for _run in range(3):
        db = Database(path)
        with db.read() as c:
            assert {"reference_choices", "drills", "ix_drills_driver"} <= tables(c)
            assert repo.get_meta(c, "schema_version") == str(SCHEMA_VERSION)
            assert c.execute("SELECT COUNT(*) FROM laps").fetchone()[0] == 1  # data untouched
            assert repo.pinned_reference(c, "f1_25", "f1:7", "f1:team:41", driver_id=2) == 1
            assert repo.list_drills(c) == []
    writer = DbWriter(db)
    try:
        row = writer.call(lambda c: repo.set_reference_choice(c, 1, "driver_best", target_driver_id=2))
        assert (row["kind"], row["target_driver_id"], row["game"], row["track_id"]) == ("driver_best", 2, "", "")
    finally:
        writer.close()


def test_concurrent_openers(tmp_path: Path) -> None:
    path = tmp_path / "v2.sqlite3"
    make_v2_db(path)
    errors: list[BaseException] = []

    def open_db() -> None:
        try:
            Database(path)
        except BaseException as e:  # pragma: no cover - the assertion reports it
            errors.append(e)

    threads = [threading.Thread(target=open_db) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    with closing(sqlite3.connect(path)) as c:
        assert {"reference_choices", "drills"} <= tables(c)


def test_driver_delete_cascades_choices_and_keeps_drills(tmp_path: Path) -> None:
    db = Database(tmp_path / "fresh.sqlite3")
    writer = DbWriter(db)
    try:
        svc = DriverService(db, writer)
        sam = svc.create("Sam").id
        writer.call(lambda c: repo.set_reference_choice(c, sam, "household_best"))
        writer.call(lambda c: repo.set_reference_choice(c, svc.default_id, "driver_best", target_driver_id=sam))
        spec = dr.DrillSpec(
            id=0,
            driver_id=sam,
            session_id=None,
            game="f1_25",
            track_id="f1:7",
            track_length_m=None,
            car_id=None,
            track_model_version=1,
            corner="T3",
            corner_label="T3",
            corner_voice="Turn 3",
            apex_m=None,
            kind="brake_point",
            source="manual",
            observation_kind=None,
            laps_target=5,
            target=1100.0,
            tolerance=5.0,
            unit="m",
            baseline=None,
            started_unix=time.time(),
        )
        st = dr.DrillState(spec)
        drill_id = writer.call(lambda c: repo.insert_drill(c, dr.spec_row(spec, st)))
        writer.call(lambda c: repo.stop_active_drills(c, "service_restart", time.time()))
        svc.delete(sam)
        with db.read() as c:
            assert repo.reference_choice_rows(c, sam, None, None) == {"all_tracks": None, "track": None}
            other = repo.reference_choice_rows(c, svc.default_id, None, None)["all_tracks"]
            assert other is not None and other["target_driver_id"] is None  # the removed driver: NULL
            row = repo.get_drill(c, drill_id)
            assert row is not None and row["driver_id"] is None and row["status"] == "abandoned"
            assert repo.list_drills(c) == [] and len(repo.list_drills(c, include_empty=True)) == 1
    finally:
        writer.close()
