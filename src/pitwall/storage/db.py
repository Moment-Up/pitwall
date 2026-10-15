"""SQLite persistence (WAL mode).

Write path: a single ``DbWriter`` thread owns the write connection; producers enqueue callables, so the
telemetry ingest thread never blocks on disk I/O. Read path: short-lived connections per request (WAL lets
readers proceed concurrently with the writer).

SQLite is sufficient for a single-host app at these volumes (a session is ~100 laps of compressed traces).
Revisit only if multi-user/multi-host access becomes a requirement.

Migrations are additive and idempotent: ``SCHEMA`` only creates what is missing (``IF NOT EXISTS``), and
``_migrate`` adds columns to tables that pre-date them, then creates the indexes over those columns (an index in
``SCHEMA`` over a new column would fail on an old database before the column exists). Data migrations that need
application knowledge (the default driver profile) live in ``repo.ensure_default_driver``.

Schema history:
* v1 - initial schema.
* v2 - driver profiles: ``reference_laps.driver_id`` (pinned references are per driver) and indexes for the
  per-driver queries (sessions by driver, reference lookup, a covering index for lap counts and best laps).
* v3 - goals (lane motivation): table goals + ix_goals_driver; sessions.info gains total_laps (JSON, no DDL).
* v4 - AI pace: ``sessions.ai_difficulty`` (the game's AI level of the session, NULL = unknown) and the
  ``session_ai_pace`` table (one row per session: the driver's best clean lap against the typical AI car). No
  backfill: sessions recorded before v4 stay unknown (``pitwall ai-pace backfill`` can fill them from captures).
  Developed as "v3" next to goals; renumbered when both landed. Every step is structural (``IF NOT EXISTS`` and
  the ``_ADDED_COLUMNS`` check), so a v2 database gets goals then AI pace, a v3 one (goals) gets AI pace only, and a
  database that already has both (or an AI-pace-only "v3" from the development branch, which gains goals) is
  stamped v4 with nothing else changed.
* v5 - race strategy: ``strategy_laps`` (one row per lap: the strategy engine's record) and ``pit_stops`` (every
  car's stops, with the pit loss) plus ``ix_pit_stops_session``. New tables only (no ``ADD COLUMN``), so ``SCHEMA``
  creates them on any older database: v2 gains goals, AI pace and strategy; v3 (goals, the live database) AI pace
  and strategy; v4 strategy only. Developed as "v3" on its lane and renumbered when it landed after goals and AI pace;
  such a lane database (strategy tables, no goals or AI pace) gains the rest. Nothing reads ``meta.schema_version``.
* v6 - coachref: ``reference_choices`` (what each driver's live delta measures against, per driver and optionally
  per track) and ``drills`` plus ``ix_drills_driver``. New tables only, so ``SCHEMA`` creates them on any older
  database: v2 gains goals, AI pace, strategy and coachref; v3 (the 0.1.0 database) AI pace, strategy and coachref;
  v4 strategy and coachref; v5 coachref only. Developed as "v3" on its lane and renumbered when it landed last; such
  a lane database (coachref tables only) gains the rest.
* v7 - leaderboard: ``session_time_trial`` (one row per session: the latest F1 25 Time Trial data, packet 14 - the EA
  rival's lap, sectors and assists in columns, the three datasets as JSON). A new table only, so ``SCHEMA`` creates it
  on any older database and every state above gains it (v6 that table only). No backfill: no Time Trial session has
  been recorded yet, and packet 14 was never stored.
"""

from __future__ import annotations

import json
import logging
import queue
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, TypeVar

from pitwall.compat import is_windows

log = logging.getLogger(__name__)
T = TypeVar("T")

SCHEMA_VERSION = 7

SCHEMA = """
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
    capture_t_end_ns INTEGER,
    ai_difficulty INTEGER              -- v4; last so fresh and migrated tables have the same layout
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

-- v4: pace vs AI difficulty (core.ai_pace / analysis.ai_pace), one row per session. Touches no column added after v1,
-- so this statement is safe in SCHEMA on an old database.
CREATE TABLE IF NOT EXISTS session_ai_pace (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    status TEXT NOT NULL,             -- analysis.ai_pace.STATUSES (ok, no_driver_lap, too_few_ai_cars, ...)
    ai_difficulty INTEGER,            -- 0-110, NULL unknown
    car_class TEXT,                   -- SessionInfo.formula ("F1 World", "F2", ...)
    weather_class TEXT,               -- dry | wet | mixed | NULL
    online INTEGER,                   -- 0/1/NULL
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

-- v3 motivation (goals). New table: the index can live in SCHEMA (no ADD COLUMN involved). Goals are personal:
-- deleting a driver deletes their goals (ON DELETE CASCADE), even when their sessions move to someone else.
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
-- end v3 motivation

-- v5 race strategy (pitwall.strategy): new tables only, so they and their index can live in SCHEMA.
CREATE TABLE IF NOT EXISTS strategy_laps (
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    lap_number INTEGER NOT NULL,
    data TEXT NOT NULL DEFAULT '{}',          -- StrategyLapRecord JSON (pitwall.strategy.engine)
    updated_unix REAL NOT NULL,
    PRIMARY KEY (session_id, lap_number)
);
CREATE TABLE IF NOT EXISTS pit_stops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    car_index INTEGER NOT NULL,
    is_player INTEGER NOT NULL DEFAULT 0,
    entry_lap INTEGER NOT NULL, exit_lap INTEGER,
    entry_lap_distance_m REAL, exit_lap_distance_m REAL,
    lane_time_ms INTEGER, stationary_ms INTEGER,
    laps_ms TEXT NOT NULL DEFAULT '[]',
    pace_before_ms INTEGER, pace_after_ms INTEGER, pit_loss_ms INTEGER,
    neutralised TEXT, excluded TEXT,
    compound_before TEXT, compound_after TEXT,
    session_time_s REAL, created_unix REAL NOT NULL,
    UNIQUE(session_id, car_index, entry_lap)
);
CREATE INDEX IF NOT EXISTS ix_pit_stops_session ON pit_stops(session_id);
-- end v5 race strategy
-- v6 coachref: what each driver's live delta measures against, and practice drills (core/coachref.py)
CREATE TABLE IF NOT EXISTS reference_choices (
    driver_id INTEGER NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,
    game TEXT NOT NULL DEFAULT '',          -- '' + '' = every track (the driver's default)
    track_id TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL,                     -- own_best | household_best | driver_best | lap
    target_driver_id INTEGER REFERENCES drivers(id) ON DELETE SET NULL,
    lap_id INTEGER REFERENCES laps(id) ON DELETE SET NULL,
    updated_unix REAL NOT NULL,
    PRIMARY KEY (driver_id, game, track_id)
);
CREATE TABLE IF NOT EXISTS drills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_id INTEGER REFERENCES drivers(id) ON DELETE SET NULL,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,   -- session it started in
    game TEXT NOT NULL,
    track_id TEXT NOT NULL,
    track_length_m REAL,
    car_id TEXT,
    track_model_version INTEGER,
    corner TEXT NOT NULL,                   -- learned corner key (join key)
    corner_label TEXT,                      -- official short label at start ("T3"), display only
    corner_voice TEXT,                      -- radio form at start ("Turn 3")
    apex_m REAL,
    kind TEXT NOT NULL,                     -- brake_point | min_speed | exit_speed | entry_speed
    source TEXT NOT NULL,                   -- work_on | manual | radio
    observation_kind TEXT,
    laps_target INTEGER NOT NULL,
    target REAL,                            -- m (brake_point) or km/h
    tolerance REAL NOT NULL,                -- m or km/h (speed drills: the step)
    unit TEXT NOT NULL,                     -- 'm' | 'km/h'
    baseline REAL,
    ref_lap_id INTEGER REFERENCES laps(id) ON DELETE SET NULL,
    ref_kind TEXT,
    ref_driver_id INTEGER REFERENCES drivers(id) ON DELETE SET NULL,
    status TEXT NOT NULL,                   -- active | completed | stopped | abandoned
    stop_reason TEXT,
    started_unix REAL NOT NULL,
    ended_unix REAL,
    attempts INTEGER NOT NULL DEFAULT 0,
    scored INTEGER NOT NULL DEFAULT 0,
    hits INTEGER NOT NULL DEFAULT 0,
    best_value REAL,
    best_delta REAL,
    trend TEXT,
    laps TEXT NOT NULL DEFAULT '[]',        -- JSON DrillAttempt[] (<= 10)
    detail TEXT NOT NULL DEFAULT '{}'       -- JSON: target_source, frozen reference and clamp, texts, note
);
CREATE INDEX IF NOT EXISTS ix_drills_driver ON drills(driver_id, started_unix);
-- end v6 coachref
-- v7 leaderboard: F1 25 Time Trial (packet 14, model.telemetry.TimeTrialInfo), the latest per session. The rival's
-- columns are the board's key and row (repo.latest_tt_rival); 0/1 flags, NULL = unknown or no rival lap.
CREATE TABLE IF NOT EXISTS session_time_trial (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    packet_format INTEGER,
    rival_car_id TEXT,                      -- 'f1:team:<teamId>' of the rival's set; NULL = no rival lap / no team
    rival_lap_ms INTEGER,                   -- NULL = no rival lap (m_lapTimeInMS 0)
    rival_s1_ms INTEGER, rival_s2_ms INTEGER, rival_s3_ms INTEGER,
    rival_tc INTEGER, rival_gearbox INTEGER, rival_abs INTEGER,   -- 0 off | 1 on
    rival_equal_performance INTEGER,        -- 0 realistic | 1 equal
    rival_custom_setup INTEGER,             -- 0 | 1
    rival_valid INTEGER,                    -- 0 | 1
    rival_car_index INTEGER,                -- LapData m_timeTrialRivalCarIdx (NULL: 255 or not seen)
    pb_car_index INTEGER,                   -- LapData m_timeTrialPBCarIdx
    data TEXT NOT NULL DEFAULT '{}',        -- TimeTrialInfo.to_dict(): the three datasets as decoded
    updated_unix REAL NOT NULL
);
-- end v7 leaderboard
"""

# Columns added after v1: (table, column, declaration). ADD COLUMN with a REFERENCES clause is allowed because the
# default is NULL; existing rows read NULL ("unknown driver") until ``repo.ensure_default_driver`` backfills them.
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("reference_laps", "driver_id", "INTEGER REFERENCES drivers(id)"),  # v2
    ("sessions", "ai_difficulty", "INTEGER"),  # v4: NULL (unknown) for every existing session
)

# v2 indexes, created after the columns they cover exist (so they cannot live in ``SCHEMA``).
# ix_laps_session_clean covers the per-session lap counts and best clean laps (sessions list, per-driver stats and
# personal bests) without reading lap rows, whose pages are dominated by the trace blob. Measured on a synthetic
# 1.2 GB database (20k laps): driver stats 63 -> 17 ms, a driver's sessions list 11 -> 2.6 ms, per-driver clean
# laps 4.6 -> 0.24 ms; building it there took ~20 ms.
_MIGRATED_INDEXES = """
CREATE INDEX IF NOT EXISTS ix_sessions_driver ON sessions(driver_id, started_unix);
CREATE INDEX IF NOT EXISTS ix_reference_lookup ON reference_laps(game, track_id, driver_id, active);
CREATE INDEX IF NOT EXISTS ix_laps_session_clean ON laps(session_id, clean, lap_time_ms);
"""


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring an existing database up to ``SCHEMA_VERSION``. Safe to run on every start and from two processes at
    once: the column check and the ALTER run inside one ``BEGIN IMMEDIATE`` transaction (SQLite DDL is
    transactional), so a concurrent opener waits on the lock and then finds the column already present."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        for table, column, decl in _ADDED_COLUMNS:
            if column not in _columns(conn, table):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
                log.info("schema: added %s.%s", table, column)
        for stmt in filter(None, (s.strip() for s in _MIGRATED_INDEXES.split(";"))):
            conn.execute(stmt)
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(SCHEMA_VERSION),),
        )
    except BaseException:
        conn.rollback()
        raise
    conn.commit()


def dumps(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), default=_json_default)


def _json_default(o: Any) -> Any:
    if isinstance(o, set):
        return sorted(o)
    if hasattr(o, "item"):  # numpy scalar
        return o.item()
    raise TypeError(f"not JSON serialisable: {type(o)}")


_OPEN_RETRY_S = (0.1, 0.2, 0.4, 0.8, 1.6)  # Windows only, see Database.__init__
_WAL_SWITCH_TIMEOUT_S = 30.0  # same as the connections' busy timeout


def _set_wal(conn: sqlite3.Connection) -> None:
    """``PRAGMA journal_mode=WAL``. Switching a database that is not in WAL mode yet (a file made by another tool)
    needs exclusive access, and SQLite reports "database is locked" at once, without its busy wait, while another
    opener holds a lock: retry briefly. A database already in WAL mode (every one pitwall made) never waits here."""
    deadline = time.monotonic() + _WAL_SWITCH_TIMEOUT_S
    while True:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            return
        except sqlite3.OperationalError as e:
            if "locked" not in str(e) or time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        for delay in (*(_OPEN_RETRY_S if is_windows() else ()), None):
            try:
                with closing(self.connect()) as conn:
                    # One write transaction taken up front: creating a table that an older database lacks (v3: goals,
                    # v4: session_ai_pace, v5: strategy, v6: coachref, v7: time trial) is a write, and as autocommit
                    # statements concurrent openers could get "database is locked" at once (a read upgraded to a write
                    # is not retried); BEGIN IMMEDIATE waits.
                    conn.executescript(f"BEGIN IMMEDIATE;\n{SCHEMA}\nCOMMIT;")
                    _migrate(conn)
                return
            except sqlite3.OperationalError as e:
                # Windows: openers racing on one file (two processes, or the threads of the concurrent-openers
                # test on the CI runner) can get "database is locked" at once, without the 30 s busy wait - SQLite
                # skips it where waiting could deadlock. Opening is idempotent (IF NOT EXISTS, BEGIN IMMEDIATE
                # migration), so try again. macOS raises at once, as before.
                if delay is None or "locked" not in str(e):
                    raise
                log.info("database %s is locked while opening; retrying in %.1f s", path, delay)
                time.sleep(delay)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        _set_wal(conn)
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()


class DbWriter:
    """Serialises all writes on one thread. ``submit`` returns a Future for callers that need the result."""

    def __init__(self, db: Database, max_queue: int = 10_000) -> None:
        self.db = db
        self._q: queue.Queue[tuple[Callable[[sqlite3.Connection], Any], Future[Any]] | None] = queue.Queue(
            maxsize=max_queue
        )
        self._thread = threading.Thread(target=self._run, name="db-writer", daemon=True)
        self.errors = 0
        self._thread.start()

    def submit(self, fn: Callable[[sqlite3.Connection], T]) -> Future[T]:
        fut: Future[T] = Future()
        self._q.put((fn, fut))  # bounded: blocks only if the DB is stalled for ~10k writes
        return fut

    def call(self, fn: Callable[[sqlite3.Connection], T], timeout: float = 30.0) -> T:
        return self.submit(fn).result(timeout)

    def _run(self) -> None:
        conn = self.db.connect()
        while True:
            item = self._q.get()
            if item is None:
                break
            fn, fut = item
            try:
                with conn:  # one transaction per job
                    res = fn(conn)
                fut.set_result(res)
            except Exception as e:
                self.errors += 1
                log.exception("db write failed")
                fut.set_exception(e)
        conn.close()

    def flush(self, timeout: float = 30.0) -> None:
        self.call(lambda _c: None, timeout)

    def close(self) -> None:
        self._q.put(None)
        self._thread.join(10)
