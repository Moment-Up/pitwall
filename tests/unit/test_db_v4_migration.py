"""Schema v4 (pace vs AI difficulty): an existing v2 or v3 database migrates in place, idempotently and safely.

``V2_SCHEMA`` / ``V2_INDEXES`` are frozen copies of ``storage/db.py`` at commit 181d85c (the last v2 build; same as
0a8a911 on the old history), ``V3_GOALS`` the DDL that v3 (goals, commit 61a8721 / aded8ab) added on top: never update
them; they are what the owner's real databases look like before this migration. Pace vs AI was developed as "v3"
next to goals and renumbered v4 when both landed, so an AI-pace-only "v3" database (``V3_AI_PACE``, the development
branch's own scratch databases) must reach v4 too (it gains goals).
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from pathlib import Path

import pytest

from pitwall.storage import repo
from pitwall.storage.db import SCHEMA_VERSION, Database, DbWriter

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
"""

V2_INDEXES = """
CREATE INDEX IF NOT EXISTS ix_sessions_driver ON sessions(driver_id, started_unix);
CREATE INDEX IF NOT EXISTS ix_reference_lookup ON reference_laps(game, track_id, driver_id, active);
CREATE INDEX IF NOT EXISTS ix_laps_session_clean ON laps(session_id, clean, lap_time_ms);
"""

# v3 (goals), frozen from storage/db.py at aded8ab: a new table and its index, nothing else.
V3_GOALS = """
CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_id INTEGER NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,                     -- lap_time | clean_streak | consistency | race_clean
    status TEXT NOT NULL DEFAULT 'active',  -- active | achieved | archived
    target REAL NOT NULL,                   -- lap_time: ms; clean_streak: laps; consistency: ms spread; race_clean: 1
    params TEXT NOT NULL DEFAULT '{}',      -- {"window_laps": 3|5|10} | {"rule": "no_penalties"|"no_contact"}
    game TEXT, track_id TEXT, track_length_m REAL, car_id TEXT, car_class TEXT,
    track_name TEXT, car_name TEXT,         -- labels at creation (display only)
    baseline REAL,                          -- value when set (progress-bar start); NULL until known
    after_lap_id INTEGER NOT NULL DEFAULT 0,-- MAX(laps.id) at creation: only later laps count
    source TEXT NOT NULL DEFAULT 'manual',  -- manual | suggested
    basis TEXT,                             -- JSON GoalBasis of a suggestion
    created_unix REAL NOT NULL,
    achieved_unix REAL,
    achieved_session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    achieved_lap_id INTEGER REFERENCES laps(id) ON DELETE SET NULL,
    achieved_value REAL
);
CREATE INDEX IF NOT EXISTS ix_goals_driver ON goals(driver_id, status);
"""

# The AI pace development branch's "v3" (3a3e3c0 on the old history): the column and the table, no goals.
V3_AI_PACE = """
ALTER TABLE sessions ADD COLUMN ai_difficulty INTEGER;
CREATE TABLE IF NOT EXISTS session_ai_pace (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    ai_difficulty INTEGER,
    car_class TEXT,
    weather_class TEXT,
    online INTEGER,
    ai_cars INTEGER NOT NULL DEFAULT 0,
    ai_laps INTEGER NOT NULL DEFAULT 0,
    ai_ref_ms INTEGER, ai_best_ms INTEGER, ai_p25_ms INTEGER, ai_p75_ms INTEGER, ai_median_lap_ms INTEGER,
    ai_bests_ms TEXT NOT NULL DEFAULT '[]',
    driver_best_ms INTEGER,
    driver_best_lap_id INTEGER REFERENCES laps(id) ON DELETE SET NULL,
    driver_median_ms INTEGER,
    driver_clean_laps INTEGER NOT NULL DEFAULT 0,
    gap_ms INTEGER, gap_pct REAL, gap_to_best_ai_ms INTEGER, race_pace_gap_pct REAL,
    field_rank INTEGER, field_size INTEGER,
    excluded TEXT NOT NULL DEFAULT '{}',
    run_id TEXT NOT NULL,
    method_version INTEGER NOT NULL,
    updated_unix REAL NOT NULL
);
"""

TABLES = ("drivers", "sessions", "laps", "events", "setups", "observations", "reference_laps", "track_models")


def make_v2_db(path: Path) -> None:
    """A database exactly as the v2 build left it, with a driver, two sessions, laps, an event and a pin."""
    with closing(sqlite3.connect(path)) as c:
        c.executescript(V2_SCHEMA)
        c.executescript(V2_INDEXES)
        c.execute("INSERT INTO meta(key, value) VALUES('schema_version', '2')")
        c.execute("INSERT INTO drivers(name, created_unix) VALUES('James', 1.0)")
        for i, track in enumerate(("f1:17", "f1:0")):
            sid = f"old{i}"
            c.execute(
                "INSERT INTO sessions(id, driver_id, game, game_session_uid, track_id, track_name, session_type, "
                "started_unix, source) VALUES(?,?,?,?,?,?,?,?,?)",
                (sid, 1, "f1_25", f"{1000 + i}", track, "Track", "race", 1000.0 + i, "udp:20777"),
            )
            for n in range(1, 4):
                c.execute(
                    "INSERT INTO laps(session_id, lap_number, lap_time_ms, clean, meta, n_samples, trace, created_unix) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (sid, n, 78_000 + n, int(n > 1), '{"t_recv_start_ns": 1, "t_recv_end_ns": 2}', 0, b"", 1.0),
                )
            c.execute("INSERT INTO events(session_id, kind) VALUES(?, 'session_started')", (sid,))
        c.execute(
            "INSERT INTO reference_laps(lap_id, game, track_id, kind, created_unix, driver_id) "
            "VALUES(2, 'f1_25', 'f1:17', 'pinned', 1.0, 1)"
        )
        c.commit()


def make_v3_goals_db(path: Path) -> None:
    """A database as the v3 (goals) build left it: the v2 data plus the goals table with two goals."""
    make_v2_db(path)
    with closing(sqlite3.connect(path)) as c:
        c.executescript(V3_GOALS)
        c.execute("UPDATE meta SET value='3' WHERE key='schema_version'")
        c.execute(
            "INSERT INTO goals(driver_id, kind, target, params, game, track_id, after_lap_id, created_unix) "
            "VALUES(1, 'lap_time', 78000, '{}', 'f1_25', 'f1:17', 6, 2.0)"
        )
        c.execute(
            "INSERT INTO goals(driver_id, kind, status, target, params, created_unix, achieved_unix, "
            "achieved_session_id, achieved_lap_id, achieved_value) "
            "VALUES(1, 'clean_streak', 'achieved', 2, '{}', 1.5, 3.0, 'old0', 3, 2)"
        )
        c.commit()


def make_v3_ai_pace_db(path: Path) -> None:
    """The AI pace development branch's "v3": the v2 data plus the column and the table (one row), no goals."""
    make_v2_db(path)
    with closing(sqlite3.connect(path)) as c:
        c.executescript(V3_AI_PACE)
        c.execute("UPDATE meta SET value='3' WHERE key='schema_version'")
        c.execute("UPDATE sessions SET ai_difficulty=35 WHERE id='old0'")
        c.execute(
            "INSERT INTO session_ai_pace(session_id, status, ai_difficulty, ai_cars, ai_laps, run_id, method_version, "
            "updated_unix) VALUES('old0', 'ok', 35, 19, 300, 'r1', 2, 1.0)"
        )
        c.commit()


def _counts(path: Path) -> dict[str, int]:
    with closing(sqlite3.connect(path)) as c:
        return {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}


def _table_info(path: Path, table: str) -> list[tuple[object, ...]]:
    with closing(sqlite3.connect(path)) as c:
        return [tuple(r) for r in c.execute(f"PRAGMA table_info({table})")]


def _version(path: Path) -> str:
    with closing(sqlite3.connect(path)) as c:
        return str(c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0])


def _names(path: Path) -> set[str]:
    with closing(sqlite3.connect(path)) as c:
        return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'index')")}


def test_v2_database_migrates_to_v4_idempotently(tmp_path: Path) -> None:
    """v2 -> v4 in one open: goals (v3) and then AI pace (v4), the old rows untouched."""
    path = tmp_path / "v2.sqlite3"
    make_v2_db(path)
    before = _counts(path)
    with closing(sqlite3.connect(path)) as c:
        rows_before = [tuple(r) for r in c.execute("SELECT * FROM sessions ORDER BY id")]
    for _ in range(3):  # every start re-runs the migration; only the first changes anything
        Database(path)
        assert _counts(path) == before
        assert _version(path) == "4"
        assert {"goals", "ix_goals_driver", "session_ai_pace"} <= _names(path)
        with closing(sqlite3.connect(path)) as c:
            cols = [r[1] for r in c.execute("PRAGMA table_info(sessions)")]
            assert cols.count("ai_difficulty") == 1 and cols[-1] == "ai_difficulty"
            assert c.execute("SELECT COUNT(*) FROM sessions WHERE ai_difficulty IS NOT NULL").fetchone()[0] == 0
            assert [tuple(r)[:-1] for r in c.execute("SELECT * FROM sessions ORDER BY id")] == rows_before
            assert c.execute("SELECT COUNT(*) FROM session_ai_pace").fetchone()[0] == 0  # no backfill
            assert c.execute("SELECT COUNT(*) FROM goals").fetchone()[0] == 0
    assert SCHEMA_VERSION == 4


def test_v3_goals_database_gains_ai_pace_only(tmp_path: Path) -> None:
    """v3 (goals, the owner's live database) -> v4: the AI pace column and table; goals and old rows untouched."""
    path = tmp_path / "v3.sqlite3"
    make_v3_goals_db(path)
    with closing(sqlite3.connect(path)) as c:
        goals_before = [tuple(r) for r in c.execute("SELECT * FROM goals ORDER BY id")]
        rows_before = [tuple(r) for r in c.execute("SELECT * FROM sessions ORDER BY id")]
    before = _counts(path)
    goals_layout = _table_info(path, "goals")
    for _ in range(3):
        Database(path)
        assert _version(path) == "4"
        assert {"session_ai_pace", "goals", "ix_goals_driver"} <= _names(path)
        assert _counts(path) == before
        assert _table_info(path, "goals") == goals_layout
        with closing(sqlite3.connect(path)) as c:
            assert [tuple(r) for r in c.execute("SELECT * FROM goals ORDER BY id")] == goals_before
            assert [tuple(r)[:-1] for r in c.execute("SELECT * FROM sessions ORDER BY id")] == rows_before
            cols = [r[1] for r in c.execute("PRAGMA table_info(sessions)")]
            assert cols.count("ai_difficulty") == 1 and cols[-1] == "ai_difficulty"
    db = Database(path)
    with db.read() as c:
        assert [g["kind"] for g in repo.list_goals(c, 1)] == ["lap_time", "clean_streak"]
        assert all(r["ai_difficulty"] is None for r in repo.list_sessions(c, 10))


def test_v3_ai_pace_database_gains_goals(tmp_path: Path) -> None:
    """The AI pace development branch's "v3" -> v4: goals are created; the stored AI pace is kept."""
    path = tmp_path / "v3ai.sqlite3"
    make_v3_ai_pace_db(path)
    for _ in range(2):
        Database(path)
        assert _version(path) == "4"
        assert {"goals", "ix_goals_driver", "session_ai_pace"} <= _names(path)
        assert [r[1] for r in _table_info(path, "sessions")].count("ai_difficulty") == 1
    db = Database(path)
    with db.read() as c:
        s = repo.get_session(c, "old0")
        assert s is not None and s["ai_difficulty"] == 35
        row = repo.get_session_ai_pace(c, "old0")
        assert row is not None and row["status"] == "ok" and row["ai_laps"] == 300


def test_fresh_and_migrated_layouts_are_identical(tmp_path: Path) -> None:
    old, fresh = tmp_path / "v2.sqlite3", tmp_path / "fresh.sqlite3"
    make_v2_db(old)
    Database(old)
    Database(fresh)
    for table in ("sessions", "session_ai_pace", "goals", "laps", "reference_laps"):
        assert _table_info(old, table) == _table_info(fresh, table), table


def test_fresh_and_v3_goals_layouts_are_identical(tmp_path: Path) -> None:
    old, fresh = tmp_path / "v3.sqlite3", tmp_path / "fresh.sqlite3"
    make_v3_goals_db(old)
    Database(old)
    Database(fresh)
    for table in ("sessions", "session_ai_pace", "goals"):
        assert _table_info(old, table) == _table_info(fresh, table), table


def test_concurrent_openers_migrate_once(tmp_path: Path) -> None:
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
    assert [r[1] for r in _table_info(path, "sessions")].count("ai_difficulty") == 1


def test_old_sessions_still_load_and_take_ai_pace(tmp_path: Path) -> None:
    path = tmp_path / "v2.sqlite3"
    make_v2_db(path)
    db = Database(path)
    writer = DbWriter(db)
    try:
        with db.read() as c:
            rows = repo.list_sessions(c, 10)
            assert {r["id"] for r in rows} == {"old0", "old1"} and all(r["ai_difficulty"] is None for r in rows)
            assert repo.get_session_ai_pace(c, "old0") is None
            assert [lap["lap_number"] for lap in repo.session_lap_times(c, "old0")] == [1, 2, 3]
        writer.call(lambda c: repo.set_session_ai_difficulty(c, "old0", 35))
        with db.read() as c:
            s = repo.get_session(c, "old0")
        assert s is not None and s["ai_difficulty"] == 35
    finally:
        writer.close()


@pytest.mark.parametrize("statement", [s for s in V2_INDEXES.split(";") if s.strip()])
def test_v2_indexes_survive(tmp_path: Path, statement: str) -> None:
    path = tmp_path / "v2.sqlite3"
    make_v2_db(path)
    Database(path)
    name = statement.split("EXISTS")[1].split()[0]
    with closing(sqlite3.connect(path)) as c:
        assert c.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (name,)).fetchone()
