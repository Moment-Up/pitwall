"""Repository functions: all SQL lives here. Functions take an explicit connection so they can run on the
writer thread (writes) or a short-lived read connection (reads).

Driver scoping: a session belongs to one driver (``sessions.driver_id``); laps, personal bests and pinned
references follow their session's driver. Query functions take ``driver_id: int | None = None`` where ``None``
means "no driver filter" (the pre-profile behaviour, kept for callers that have no driver, such as sessions
recorded before profiles existed). Track models are deliberately never driver-scoped: geometry is shared.

Replays (``source`` starting with ``REPLAY_SOURCE_PREFIX``) re-process laps that were already recorded, so they
are nobody's driving: they are stored without a driver unless one is named explicitly, the default-driver
backfill leaves them alone, and a driver's *records* (personal best, automatic reference laps, stats) never count
them, whoever they were assigned to. They still feed the shared, driver-independent track models.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import asdict
from typing import Any

from pitwall.analysis.coaching import Observation
from pitwall.analysis.laps import LapTrace
from pitwall.analysis.track import TrackModel
from pitwall.model.telemetry import CarSetup, GameEvent, SessionInfo
from pitwall.storage.db import dumps

ACTIVE_DRIVER_KEY = "active_driver_id"  # meta key: who is in the seat (survives restarts)
DEFAULT_DRIVER_KEY = "default_driver_id"  # meta key: owner of sessions recorded before profiles existed
REPLAY_SOURCE_PREFIX = "replay:"  # sessions.source of a capture replay (core.runtime.Runtime.start_replay)


def _driven(table: str = "s") -> str:
    """SQL predicate over a ``sessions`` row (alias ``table``): real driving, not a replay."""
    return f"substr({table}.source, 1, {len(REPLAY_SOURCE_PREFIX)}) != '{REPLAY_SOURCE_PREFIX}'"


_DRIVEN = _driven()


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


def is_replay_source(source: str) -> bool:
    return source.startswith(REPLAY_SOURCE_PREFIX)


# ---------------------------------------------------------------- meta
def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    r = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return None if r is None else r["value"]


def set_meta(conn: sqlite3.Connection, key: str, value: str | None) -> None:
    """Upsert a meta value; ``None`` deletes the key."""
    if value is None:
        conn.execute("DELETE FROM meta WHERE key=?", (key,))
    else:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def _meta_driver_id(conn: sqlite3.Connection, key: str) -> int | None:
    """A driver id stored in meta, or None when unset, malformed or pointing at a deleted driver."""
    r = conn.execute(
        "SELECT d.id FROM drivers d JOIN meta m ON m.key=? AND CAST(m.value AS INTEGER)=d.id", (key,)
    ).fetchone()
    return None if r is None else int(r["id"])


# ---------------------------------------------------------------- sessions
# A session row's driver is the explicit id when it names an existing driver, else the persisted active driver.
# Resolving it inside the INSERT means a stale cached id (driver deleted a moment ago) can never violate the
# foreign key and lose the session, and callers that have no driver source still tag sessions correctly.
_EXPLICIT_DRIVER_SQL = "(SELECT id FROM drivers WHERE id=?)"
_SESSION_DRIVER_SQL = (
    f"COALESCE({_EXPLICIT_DRIVER_SQL}, "
    f"(SELECT d.id FROM drivers d JOIN meta m ON m.key='{ACTIVE_DRIVER_KEY}' AND CAST(m.value AS INTEGER)=d.id))"
)


def insert_session(
    conn: sqlite3.Connection,
    session_id: str,
    game: str,
    source: str,
    synthetic: bool,
    capture_path: str | None,
    capture_t_start_ns: int | None,
    driver_id: int | None = None,
) -> None:
    """Insert a session. A replay never falls back to the seated driver (only an explicit, existing driver)."""
    driver_sql = _EXPLICIT_DRIVER_SQL if is_replay_source(source) else _SESSION_DRIVER_SQL
    conn.execute(
        "INSERT INTO sessions(id, game, started_unix, source, synthetic, capture_path, capture_t_start_ns, driver_id) "
        f"VALUES(?,?,?,?,?,?,?,{driver_sql})",
        (session_id, game, time.time(), source, int(synthetic), capture_path, capture_t_start_ns, driver_id),
    )


def session_driver_id(conn: sqlite3.Connection, session_id: str) -> int | None:
    r = conn.execute("SELECT driver_id FROM sessions WHERE id=?", (session_id,)).fetchone()
    return None if r is None or r["driver_id"] is None else int(r["driver_id"])


def set_session_driver(conn: sqlite3.Connection, session_id: str, driver_id: int) -> int | None:
    """Re-assign a session to ``driver_id``; returns the previous driver id.

    Pinned references on the session's laps are deactivated when the owner changes: they were chosen by (and
    for) the previous owner, and a lap of the new owner must not stay the previous owner's reference.
    Raises ``KeyError`` for an unknown session or driver.
    """
    r = conn.execute("SELECT driver_id FROM sessions WHERE id=?", (session_id,)).fetchone()
    if r is None:
        raise KeyError(f"session {session_id} not found")
    if conn.execute("SELECT 1 FROM drivers WHERE id=?", (driver_id,)).fetchone() is None:
        raise KeyError(f"driver {driver_id} not found")
    previous = None if r["driver_id"] is None else int(r["driver_id"])
    if previous != driver_id:
        conn.execute("UPDATE sessions SET driver_id=? WHERE id=?", (driver_id, session_id))
        conn.execute(
            "UPDATE reference_laps SET active=0 WHERE lap_id IN (SELECT id FROM laps WHERE session_id=?)",
            (session_id,),
        )
    return previous


def update_session_info(conn: sqlite3.Connection, session_id: str, info: SessionInfo) -> None:
    conn.execute(
        """UPDATE sessions SET platform=?, game_session_uid=?, track_id=?, track_name=?, track_length_m=?,
           session_type=?, session_type_raw=?, car_id=COALESCE(?, car_id), car_name=COALESCE(?, car_name),
           weather=?, assists=?, info=? WHERE id=?""",
        (
            info.platform.value,
            info.session_uid,
            info.track_id,
            info.track_name,
            info.track_length_m,
            info.session_type.value,
            info.session_type_raw,
            info.car_id,
            info.car_name,
            dumps(asdict(info.weather)),
            dumps(info.assists),
            dumps(_session_info_extra(info)),
            session_id,
        ),
    )


def _session_info_extra(info: SessionInfo) -> dict[str, Any]:
    """The ``info`` JSON column: adapter extras plus the game-native track skeleton.

    Marshal-zone flags are live state, so only the geometry is stored (``without_flags``); a session page must
    never show an old yellow flag as a fact.
    """
    extra = {k: v for k, v in info.extra.items() if k != "forecast"}
    if info.formula is not None:  # tells 2025 from 2026 Season Pack cars (``carsetup.context``)
        extra["formula"] = info.formula
    if info.track_zones is not None:
        extra["track_zones"] = info.track_zones.without_flags().to_dict()
    if info.pit_speed_limit_kph is not None:
        extra["pit_speed_limit_kph"] = info.pit_speed_limit_kph
    return extra


def last_live_session(c: sqlite3.Connection, source: str) -> dict[str, Any] | None:
    """The most recent real session from a live source: the candidate to resume after a service restart."""
    r = c.execute(
        "SELECT id, game_session_uid, started_unix, ended_unix, driver_id FROM sessions "
        "WHERE source=? AND synthetic=0 ORDER BY started_unix DESC, rowid DESC LIMIT 1",
        (source,),
    ).fetchone()
    return dict(r) if r else None


def resume_session(c: sqlite3.Connection, keep_id: str, drop_id: str) -> None:
    """Fold a just-started session (no laps yet) into the session it continues, and reopen that one.

    Used when the service restarted mid-session: the game kept the same session UID, so the driver's race must
    stay one pitwall session. Rows written to the new session in its first moments (events, setups) move over.
    """
    if c.execute("SELECT COUNT(*) FROM laps WHERE session_id=?", (drop_id,)).fetchone()[0]:
        raise ValueError(f"session {drop_id} already has laps; refusing to merge it into {keep_id}")
    for table in ("events", "setups", "observations", "conversations"):
        c.execute(f"UPDATE {table} SET session_id=? WHERE session_id=?", (keep_id, drop_id))
    c.execute("UPDATE sessions SET ended_unix=NULL WHERE id=?", (keep_id,))
    c.execute("DELETE FROM sessions WHERE id=?", (drop_id,))


def end_session(conn: sqlite3.Connection, session_id: str, t_end_ns: int | None) -> None:
    conn.execute(
        "UPDATE sessions SET ended_unix=?, capture_t_end_ns=COALESCE(?, capture_t_end_ns) WHERE id=?",
        (time.time(), t_end_ns, session_id),
    )


def _session_row(r: sqlite3.Row) -> dict[str, Any]:
    d = dict(r)
    for k in ("weather", "assists", "info"):
        d[k] = json.loads(d[k] or "{}")
    d["synthetic"] = bool(d["synthetic"])
    return d


def list_sessions(conn: sqlite3.Connection, limit: int = 50, driver_id: int | None = None) -> list[dict[str, Any]]:
    """Most recent sessions first, with lap count, clean lap count, best clean lap and the owning driver's name."""
    where, args = ("WHERE s.driver_id=?", [driver_id]) if driver_id is not None else ("", [])
    rows = conn.execute(
        f"""SELECT s.*, d.name AS driver_name, COUNT(l.id) AS lap_count,
                  COALESCE(SUM(l.clean), 0) AS clean_lap_count,
                  MIN(CASE WHEN l.clean=1 THEN l.lap_time_ms END) AS best_clean_ms
           FROM sessions s LEFT JOIN laps l ON l.session_id = s.id LEFT JOIN drivers d ON d.id = s.driver_id
           {where} GROUP BY s.id ORDER BY s.started_unix DESC, s.rowid DESC LIMIT ?""",
        [*args, limit],
    ).fetchall()
    return [_session_row(r) for r in rows]


def get_session(conn: sqlite3.Connection, session_id: str) -> dict[str, Any] | None:
    r = conn.execute(
        "SELECT s.*, d.name AS driver_name FROM sessions s LEFT JOIN drivers d ON d.id = s.driver_id WHERE s.id=?",
        (session_id,),
    ).fetchone()
    return _session_row(r) if r else None


def latest_session_id(conn: sqlite3.Connection, driver_id: int | None = None) -> str | None:
    """The most recently started session (of ``driver_id`` when given). Equal ``started_unix`` values (Python 3.12's
    ``time.time()`` ticks every 15.6 ms on Windows) go to the session inserted last (``rowid``)."""
    if driver_id is None:
        r = conn.execute("SELECT id FROM sessions ORDER BY started_unix DESC, rowid DESC LIMIT 1").fetchone()
    else:
        r = conn.execute(
            "SELECT id FROM sessions WHERE driver_id=? ORDER BY started_unix DESC, rowid DESC LIMIT 1", (driver_id,)
        ).fetchone()
    return r["id"] if r else None


# ---------------------------------------------------------------- laps
def insert_lap(conn: sqlite3.Connection, session_id: str, lap: LapTrace, setup_fp: str | None) -> int:
    s = ([*lap.sector_times_ms, None, None, None])[:3]
    cur = conn.execute(
        """INSERT INTO laps(session_id, lap_number, lap_time_ms, s1_ms, s2_ms, s3_ms, valid, clean, flags, meta,
                            setup_fp, n_samples, trace, created_unix)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(session_id, lap_number) DO UPDATE SET
             lap_time_ms=excluded.lap_time_ms, s1_ms=excluded.s1_ms, s2_ms=excluded.s2_ms, s3_ms=excluded.s3_ms,
             valid=excluded.valid, clean=excluded.clean, flags=excluded.flags, meta=excluded.meta,
             setup_fp=excluded.setup_fp, n_samples=excluded.n_samples, trace=excluded.trace""",
        (
            session_id,
            lap.lap_number,
            lap.lap_time_ms,
            s[0],
            s[1],
            s[2],
            None if lap.valid is None else int(lap.valid),
            int(lap.clean),
            dumps(sorted(lap.flags)),
            dumps(lap.meta),
            setup_fp,
            lap.n,
            lap.to_npz(),
            time.time(),
        ),
    )
    row = conn.execute(
        "SELECT id FROM laps WHERE session_id=? AND lap_number=?", (session_id, lap.lap_number)
    ).fetchone()
    return int(row["id"]) if row else int(cur.lastrowid or 0)


def _lap_row(r: sqlite3.Row, with_trace: bool) -> dict[str, Any]:
    d = dict(r)
    d["flags"] = json.loads(d["flags"])
    d["meta"] = json.loads(d["meta"])
    d["clean"] = bool(d["clean"])
    d["valid"] = None if d["valid"] is None else bool(d["valid"])
    if not with_trace:
        d.pop("trace", None)
    return d


def list_laps(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM laps WHERE session_id=? ORDER BY lap_number", (session_id,)).fetchall()
    return [_lap_row(r, with_trace=False) for r in rows]


def get_lap(conn: sqlite3.Connection, lap_id: int, with_trace: bool = True) -> dict[str, Any] | None:
    r = conn.execute("SELECT * FROM laps WHERE id=?", (lap_id,)).fetchone()
    return _lap_row(r, with_trace) if r else None


def load_lap_trace(conn: sqlite3.Connection, lap_id: int) -> LapTrace | None:
    d = get_lap(conn, lap_id, with_trace=True)
    if d is None:
        return None
    return LapTrace(
        lap_number=d["lap_number"],
        channels=LapTrace.channels_from_npz(d["trace"]),
        lap_time_ms=d["lap_time_ms"],
        sector_times_ms=[d["s1_ms"], d["s2_ms"], d["s3_ms"]],
        valid=d["valid"],
        flags=set(d["flags"]),
        meta={**d["meta"], "lap_id": d["id"], "session_id": d["session_id"], "setup_fp": d["setup_fp"]},
    )


def clean_laps_for(
    conn: sqlite3.Connection,
    game: str,
    track_id: str,
    car_id: str | None,
    limit: int = 10,
    driver_id: int | None = None,
    track_length_m: float | None = None,
    length_tolerance: float = 0.03,
) -> list[dict[str, Any]]:
    """Fastest clean laps for a game/track(/car), across all sessions (of ``driver_id`` when given).

    Unscoped (``driver_id=None``: track models, unowned sessions) every session counts; scoped to a driver, only
    their driving does (replays are excluded, see the module docstring). Ties on lap time are broken by lap id so
    the choice is deterministic. ``track_length_m``: only sessions whose stored length is within
    ``length_tolerance`` (relative) of it, or unknown - layouts that share a track id (Assetto Corsa on a console
    sends no layout name) differ in length (``analysis.compare.LAYOUT_LENGTH_TOLERANCE``)."""
    q = """SELECT l.*, s.car_id, s.track_id, s.track_length_m, s.game, s.weather, s.assists, s.driver_id FROM laps l
           JOIN sessions s ON s.id = l.session_id
           WHERE l.clean=1 AND s.game=? AND s.track_id=? AND l.lap_time_ms IS NOT NULL"""
    args: list[Any] = [game, track_id]
    if car_id is not None:
        q += " AND s.car_id=?"
        args.append(car_id)
    if track_length_m is not None and track_length_m > 0:
        q += " AND (s.track_length_m IS NULL OR ABS(s.track_length_m - ?) <= ? * MAX(s.track_length_m, ?))"
        args += [track_length_m, length_tolerance, track_length_m]
    if driver_id is not None:
        q += f" AND s.driver_id=? AND {_DRIVEN}"
        args.append(driver_id)
    q += " ORDER BY l.lap_time_ms ASC, l.id ASC LIMIT ?"
    args.append(limit)
    out = []
    for r in conn.execute(q, args).fetchall():
        d = dict(r)
        d.pop("trace", None)
        d["meta"] = json.loads(d["meta"])
        d["flags"] = json.loads(d["flags"])
        d["weather"] = json.loads(d["weather"] or "{}")
        d["assists"] = json.loads(d["assists"] or "{}")
        out.append(d)
    return out


def personal_best(
    conn: sqlite3.Connection, driver_id: int, game: str, track_id: str, car_id: str | None = None
) -> dict[str, Any] | None:
    """A driver's fastest clean lap at a track (optionally in one car; ``car_id=None`` = any car), with its
    session's id and start time. Replays never count (they re-process laps already recorded)."""
    q = f"""SELECT l.id, l.session_id, l.lap_number, l.lap_time_ms, l.s1_ms, l.s2_ms, l.s3_ms,
                  s.car_id, s.car_name, s.track_name, s.started_unix, s.synthetic
           FROM laps l JOIN sessions s ON s.id = l.session_id
           WHERE l.clean=1 AND l.lap_time_ms IS NOT NULL AND s.driver_id=? AND s.game=? AND s.track_id=?
             AND {_DRIVEN}"""
    args: list[Any] = [driver_id, game, track_id]
    if car_id is not None:
        q += " AND s.car_id=?"
        args.append(car_id)
    r = conn.execute(q + " ORDER BY l.lap_time_ms ASC, l.id ASC LIMIT 1", args).fetchone()
    if r is None:
        return None
    d = dict(r)
    d["synthetic"] = bool(d["synthetic"])
    return d


# ---------------------------------------------------------------- drivers
def _driver_row(r: sqlite3.Row) -> dict[str, Any]:
    d = dict(r)
    try:
        prefs = json.loads(d.get("preferences") or "{}")
    except json.JSONDecodeError:
        prefs = {}
    d["preferences"] = prefs if isinstance(prefs, dict) else {}
    return d


def list_drivers(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [_driver_row(r) for r in conn.execute("SELECT * FROM drivers ORDER BY id").fetchall()]


def get_driver(conn: sqlite3.Connection, driver_id: int) -> dict[str, Any] | None:
    r = conn.execute("SELECT * FROM drivers WHERE id=?", (driver_id,)).fetchone()
    return _driver_row(r) if r else None


def find_driver_by_name(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    """Case-insensitive lookup ("sam" and "Sam" would be the same person on a shared iPad)."""
    r = conn.execute("SELECT * FROM drivers WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    return _driver_row(r) if r else None


def insert_driver(conn: sqlite3.Connection, name: str, preferences: dict[str, Any]) -> int:
    cur = conn.execute(
        "INSERT INTO drivers(name, created_unix, preferences) VALUES(?,?,?)", (name, time.time(), dumps(preferences))
    )
    return int(cur.lastrowid or 0)


def update_driver(
    conn: sqlite3.Connection, driver_id: int, name: str | None = None, preferences: dict[str, Any] | None = None
) -> bool:
    """Update name and/or the whole preferences object; returns False for an unknown driver."""
    cur = conn.execute(
        "UPDATE drivers SET name=COALESCE(?, name), preferences=COALESCE(?, preferences) WHERE id=?",
        (name, None if preferences is None else dumps(preferences), driver_id),
    )
    return cur.rowcount > 0


def count_driver_sessions(conn: sqlite3.Connection, driver_id: int) -> int:
    r = conn.execute("SELECT COUNT(*) AS n FROM sessions WHERE driver_id=?", (driver_id,)).fetchone()
    return int(r["n"])


def delete_driver(conn: sqlite3.Connection, driver_id: int, reassign_to: int | None = None) -> int:
    """Delete a driver, first moving their sessions to ``reassign_to``; returns the number of sessions moved.

    Without ``reassign_to`` a driver who still owns sessions is refused (``ValueError``): recorded laps are never
    deleted as a side effect of removing a profile. Their pinned references move with the sessions but are
    deactivated, so they cannot override the receiving driver's own choice. Meta keys naming the deleted driver
    are moved to the receiving driver (or cleared). Raises ``KeyError`` for an unknown driver or target.
    """
    if conn.execute("SELECT 1 FROM drivers WHERE id=?", (driver_id,)).fetchone() is None:
        raise KeyError(f"driver {driver_id} not found")
    if reassign_to is not None:
        if reassign_to == driver_id:
            raise ValueError("cannot reassign a driver's sessions to the same driver")
        if conn.execute("SELECT 1 FROM drivers WHERE id=?", (reassign_to,)).fetchone() is None:
            raise KeyError(f"driver {reassign_to} not found")
        moved = conn.execute("UPDATE sessions SET driver_id=? WHERE driver_id=?", (reassign_to, driver_id)).rowcount
        conn.execute("UPDATE reference_laps SET driver_id=?, active=0 WHERE driver_id=?", (reassign_to, driver_id))
    else:
        n = count_driver_sessions(conn, driver_id)
        if n:
            raise ValueError(f"driver {driver_id} still owns {n} session(s)")
        moved = 0
        conn.execute("DELETE FROM reference_laps WHERE driver_id=?", (driver_id,))
    for key in (ACTIVE_DRIVER_KEY, DEFAULT_DRIVER_KEY):
        if get_meta(conn, key) == str(driver_id):
            set_meta(conn, key, None if reassign_to is None else str(reassign_to))
    conn.execute("DELETE FROM drivers WHERE id=?", (driver_id,))
    return int(moved)


def ensure_default_driver(conn: sqlite3.Connection, name: str, preferences: dict[str, Any]) -> int:
    """Idempotent data migration for driver profiles; returns the default driver's id.

    1. With no drivers at all, create ``name`` and remember it as the default driver (meta).
    2. Give every session without a driver to the default driver. Before profiles existed every session was the
       owner's; afterwards ``insert_session`` always resolves a driver, so this only ever catches rows written
       by an older build (for example a service still running the previous version during an upgrade).
       Replays are left unowned: they are nobody's driving (see the module docstring).
    3. Give pre-v2 pinned references the driver of the session their lap belongs to.
    4. Make the default driver active when no valid active driver is stored.
    Every step only touches rows that are still missing data, so re-running changes nothing.
    """
    default_id = _meta_driver_id(conn, DEFAULT_DRIVER_KEY)
    if default_id is None:
        r = conn.execute("SELECT MIN(id) AS id FROM drivers").fetchone()
        default_id = None if r["id"] is None else int(r["id"])
    if default_id is None:
        default_id = insert_driver(conn, name, preferences)
    set_meta(conn, DEFAULT_DRIVER_KEY, str(default_id))
    conn.execute(
        f"UPDATE sessions SET driver_id=? WHERE driver_id IS NULL AND {_driven('sessions')}",
        (default_id,),
    )
    conn.execute(
        """UPDATE reference_laps SET driver_id = (
               SELECT s.driver_id FROM laps l JOIN sessions s ON s.id = l.session_id WHERE l.id = reference_laps.lap_id)
           WHERE driver_id IS NULL"""
    )
    if _meta_driver_id(conn, ACTIVE_DRIVER_KEY) is None:
        set_meta(conn, ACTIVE_DRIVER_KEY, str(default_id))
    return default_id


def active_driver_id(conn: sqlite3.Connection) -> int | None:
    return _meta_driver_id(conn, ACTIVE_DRIVER_KEY)


def default_driver_id(conn: sqlite3.Connection) -> int | None:
    return _meta_driver_id(conn, DEFAULT_DRIVER_KEY)


def driver_stats(conn: sqlite3.Connection) -> dict[int, dict[str, Any]]:
    """Per-driver totals and best clean lap per track, keyed by driver id (drivers with no sessions are absent).

    ``sessions`` counts every session the driver owns (it is what ``delete_driver`` refuses on, and what their
    session list shows); ``laps``, ``clean_laps``, ``tracks`` and ``best_laps`` count driving only, never replays.
    The best lap per (game, track) is picked with a window function (fastest, then lowest lap id) so the lap id,
    session and car returned all belong to that one lap."""
    out: dict[int, dict[str, Any]] = {}
    for r in conn.execute(
        f"""SELECT s.driver_id, COUNT(DISTINCT s.id) AS sessions,
                  COUNT(CASE WHEN {_DRIVEN} THEN l.id END) AS laps,
                  COALESCE(SUM(CASE WHEN {_DRIVEN} THEN l.clean END), 0) AS clean_laps,
                  COUNT(DISTINCT CASE WHEN s.track_id IS NOT NULL AND {_DRIVEN}
                                      THEN s.game || '/' || s.track_id END) AS tracks,
                  MAX(s.started_unix) AS last_session_unix
           FROM sessions s LEFT JOIN laps l ON l.session_id = s.id
           WHERE s.driver_id IS NOT NULL GROUP BY s.driver_id"""
    ).fetchall():
        out[int(r["driver_id"])] = {
            "sessions": int(r["sessions"]),
            "laps": int(r["laps"]),
            "clean_laps": int(r["clean_laps"]),
            "tracks": int(r["tracks"]),
            "last_session_unix": r["last_session_unix"],
            "best_laps": [],
        }
    for r in conn.execute(
        f"""SELECT driver_id, game, track_id, track_name, lap_time_ms, lap_id, session_id, car_name, synthetic,
                  started_unix
           FROM (SELECT s.driver_id, s.game, s.track_id, s.track_name, l.lap_time_ms, l.id AS lap_id,
                        s.id AS session_id, s.car_name, s.synthetic, s.started_unix,
                        ROW_NUMBER() OVER (PARTITION BY s.driver_id, s.game, s.track_id
                                           ORDER BY l.lap_time_ms ASC, l.id ASC) AS rn
                 FROM laps l JOIN sessions s ON s.id = l.session_id
                 WHERE l.clean=1 AND l.lap_time_ms IS NOT NULL AND s.track_id IS NOT NULL
                   AND s.driver_id IS NOT NULL AND {_DRIVEN})
           WHERE rn = 1 ORDER BY driver_id, synthetic, track_name"""
    ).fetchall():
        stats = out.get(int(r["driver_id"]))
        if stats is not None:
            stats["best_laps"].append(
                {
                    "game": r["game"],
                    "track_id": r["track_id"],
                    "track_name": r["track_name"],
                    "lap_time_ms": r["lap_time_ms"],
                    "lap_id": r["lap_id"],
                    "session_id": r["session_id"],
                    "car_name": r["car_name"],
                    "synthetic": bool(r["synthetic"]),
                    "set_unix": r["started_unix"],
                }
            )
    return out


# ---------------------------------------------------------------- events / setups
def insert_event(conn: sqlite3.Connection, session_id: str, e: GameEvent) -> None:
    conn.execute(
        "INSERT INTO events(session_id, t_recv_ns, session_time_s, kind, code, payload) VALUES(?,?,?,?,?,?)",
        (session_id, e.t_recv_ns, e.session_time_s, e.kind.value, e.code, dumps(e.payload)),
    )


def insert_setup(conn: sqlite3.Connection, session_id: str, s: CarSetup) -> None:
    conn.execute(
        "INSERT INTO setups(session_id, t_recv_ns, fingerprint, params) VALUES(?,?,?,?)",
        (session_id, s.t_recv_ns, s.fingerprint(), dumps({k: asdict(p) for k, p in s.parameters.items()})),
    )


def latest_setup(conn: sqlite3.Connection, session_id: str) -> dict[str, Any] | None:
    r = conn.execute("SELECT * FROM setups WHERE session_id=? ORDER BY id DESC LIMIT 1", (session_id,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["params"] = json.loads(d["params"])
    return d


def setup_history(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM setups WHERE session_id=? ORDER BY id", (session_id,)).fetchall()
    return [{**dict(r), "params": json.loads(r["params"])} for r in rows]


# ---------------------------------------------------------------- setup experiments
# Lifecycle and metrics live in ``carsetup.experiments``; these functions only store and read rows.
_EXPERIMENT_UPDATABLE = frozenset(
    {"status", "before_session_id", "after_session_id", "before_metrics", "after_metrics", "conclusion"}
)


def _experiment_row(r: sqlite3.Row) -> dict[str, Any]:
    d = dict(r)
    for k in ("before_metrics", "after_metrics"):
        d[k] = json.loads(d[k]) if d[k] else None
    return d


def insert_setup_experiment(
    conn: sqlite3.Connection,
    *,
    game: str,
    track_id: str | None,
    car_id: str | None,
    hypothesis: str,
    parameter: str,
    from_value: float | None,
    to_value: float | None,
    before_session_id: str | None,
) -> int:
    cur = conn.execute(
        """INSERT INTO setup_experiments(game, track_id, car_id, created_unix, hypothesis, parameter, from_value,
                                         to_value, status, before_session_id)
           VALUES(?,?,?,?,?,?,?,?,'proposed',?)""",
        (game, track_id, car_id, time.time(), hypothesis, parameter, from_value, to_value, before_session_id),
    )
    return int(cur.lastrowid or 0)


def get_setup_experiment(conn: sqlite3.Connection, experiment_id: int) -> dict[str, Any] | None:
    r = conn.execute("SELECT * FROM setup_experiments WHERE id=?", (experiment_id,)).fetchone()
    return _experiment_row(r) if r else None


def list_setup_experiments(
    conn: sqlite3.Connection,
    *,
    game: str | None = None,
    track_id: str | None = None,
    car_id: str | None = None,
    status: str | None = None,
    session_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Newest first. ``session_id`` matches experiments that use the session as their before or after run."""
    where: list[str] = []
    args: list[Any] = []
    for col, val in (("game", game), ("track_id", track_id), ("car_id", car_id), ("status", status)):
        if val is not None:
            where.append(f"{col}=?")
            args.append(val)
    if session_id is not None:
        where.append("(before_session_id=? OR after_session_id=?)")
        args += [session_id, session_id]
    sql = "SELECT * FROM setup_experiments" + (f" WHERE {' AND '.join(where)}" if where else "")
    rows = conn.execute(sql + " ORDER BY id DESC LIMIT ?", [*args, limit]).fetchall()
    return [_experiment_row(r) for r in rows]


def update_setup_experiment(conn: sqlite3.Connection, experiment_id: int, **fields: Any) -> None:
    """Update lifecycle columns (status, sessions, metrics, conclusion); metrics dicts are stored as JSON."""
    bad = set(fields) - _EXPERIMENT_UPDATABLE
    if bad:
        raise ValueError(f"not updatable: {sorted(bad)}")
    if not fields:
        return
    cols = sorted(fields)
    vals = [dumps(fields[c]) if c.endswith("_metrics") and fields[c] is not None else fields[c] for c in cols]
    conn.execute(f"UPDATE setup_experiments SET {', '.join(f'{c}=?' for c in cols)} WHERE id=?", [*vals, experiment_id])


def list_events(conn: sqlite3.Connection, session_id: str, limit: int = 500) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM events WHERE session_id=? AND kind != 'button' ORDER BY id LIMIT ?", (session_id, limit)
    ).fetchall()
    return [{**dict(r), "payload": json.loads(r["payload"])} for r in rows]


# ---------------------------------------------------------------- track models
def save_track_model(conn: sqlite3.Connection, model: TrackModel) -> int:
    r = conn.execute(
        "SELECT COALESCE(MAX(version), 0) AS v FROM track_models WHERE game=? AND track_id=?",
        (model.game, model.track_id),
    ).fetchone()
    model.version = int(r["v"]) + 1
    conn.execute(
        "INSERT INTO track_models(game, track_id, version, created_unix, model) VALUES(?,?,?,?,?)",
        (model.game, model.track_id, model.version, time.time(), dumps(model.to_dict())),
    )
    return model.version


def load_track_model(conn: sqlite3.Connection, game: str, track_id: str) -> TrackModel | None:
    r = conn.execute(
        "SELECT model FROM track_models WHERE game=? AND track_id=? ORDER BY version DESC LIMIT 1",
        (game, track_id),
    ).fetchone()
    return TrackModel.from_dict(json.loads(r["model"])) if r else None


# ---------------------------------------------------------------- references
def pin_reference(conn: sqlite3.Connection, lap_id: int, label: str | None = None) -> int:
    """Pin a lap as the reference for its game/track/car *and its driver* (the owner of the lap's session).

    Pins are per driver so pinning a lap never changes what another driver is compared against; a driver can
    only pin their own laps this way, since the pin's driver is derived from the lap."""
    r = conn.execute(
        "SELECT s.game, s.track_id, s.car_id, s.driver_id FROM laps l JOIN sessions s ON s.id=l.session_id "
        "WHERE l.id=?",
        (lap_id,),
    ).fetchone()
    if r is None:
        raise KeyError(f"lap {lap_id} not found")
    conn.execute(
        "UPDATE reference_laps SET active=0 WHERE game=? AND track_id=? AND COALESCE(car_id,'')=COALESCE(?, '') "
        "AND driver_id IS ?",
        (r["game"], r["track_id"], r["car_id"], r["driver_id"]),
    )
    cur = conn.execute(
        "INSERT INTO reference_laps(lap_id, game, track_id, car_id, kind, label, created_unix, driver_id) "
        "VALUES(?,?,?,?,'pinned',?,?,?)",
        (lap_id, r["game"], r["track_id"], r["car_id"], label, time.time(), r["driver_id"]),
    )
    return int(cur.lastrowid or 0)


def pinned_reference(
    conn: sqlite3.Connection, game: str, track_id: str, car_id: str | None, driver_id: int | None = None
) -> int | None:
    """The active pinned reference lap. With ``driver_id`` only that driver's pin counts, and only while the
    pinned lap's session still belongs to them (a re-assigned session can never leave a cross-driver pin)."""
    q = """SELECT r.lap_id FROM reference_laps r WHERE r.active=1 AND r.game=? AND r.track_id=?
           AND COALESCE(r.car_id,'')=COALESCE(?, '')"""
    args: list[Any] = [game, track_id, car_id]
    if driver_id is not None:
        q += """ AND r.driver_id=? AND EXISTS (SELECT 1 FROM laps l JOIN sessions s ON s.id = l.session_id
                                               WHERE l.id = r.lap_id AND s.driver_id = r.driver_id)"""
        args.append(driver_id)
    r = conn.execute(q + " ORDER BY r.id DESC LIMIT 1", args).fetchone()
    return int(r["lap_id"]) if r else None


# ---------------------------------------------------------------- observations
def insert_observations(
    conn: sqlite3.Connection,
    session_id: str,
    lap_id: int,
    ref_lap_id: int | None,
    obs: list[Observation],
    model_version: int | None,
) -> None:
    now = time.time()
    conn.executemany(
        """INSERT INTO observations(session_id, lap_id, ref_lap_id, obs_key, kind, corner, metric, value, unit,
                impact_s, confidence, positive, text, evidence, track_model_version, created_unix)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            (
                session_id,
                lap_id,
                ref_lap_id,
                o.id,
                o.kind,
                o.corner,
                o.metric,
                o.value,
                o.unit,
                o.impact_s,
                o.confidence,
                int(o.positive),
                o.text,
                dumps({**o.evidence, "consistency": o.consistency}),
                model_version,
                now,
            )
            for o in obs
        ],
    )


def list_observations(conn: sqlite3.Connection, session_id: str, limit: int = 200) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT o.*, l.lap_number FROM observations o LEFT JOIN laps l ON l.id = o.lap_id
           WHERE o.session_id=? ORDER BY o.id DESC LIMIT ?""",
        (session_id, limit),
    ).fetchall()
    return [{**dict(r), "evidence": json.loads(r["evidence"]), "positive": bool(r["positive"])} for r in rows]


# ---------------------------------------------------------------- conversations
def insert_message(
    conn: sqlite3.Connection,
    session_id: str | None,
    role: str,
    text: str,
    intent: str | None = None,
    facts: Any = None,
    model: str | None = None,
    latency_ms: int | None = None,
    grounded: bool | None = None,
    fallback: bool = False,
) -> None:
    conn.execute(
        """INSERT INTO conversations(session_id, created_unix, role, text, intent, facts, model, latency_ms,
               grounded, fallback) VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (
            session_id,
            time.time(),
            role,
            text,
            intent,
            dumps(facts) if facts is not None else None,
            model,
            latency_ms,
            None if grounded is None else int(grounded),
            int(fallback),
        ),
    )


def list_messages(conn: sqlite3.Connection, session_id: str | None, limit: int = 50) -> list[dict[str, Any]]:
    if session_id:
        rows = conn.execute(
            "SELECT * FROM conversations WHERE session_id=? ORDER BY id DESC LIMIT ?", (session_id, limit)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM conversations ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in reversed(rows):
        d = dict(r)
        d["facts"] = json.loads(d["facts"]) if d["facts"] else None
        out.append(d)
    return out


def derived_track_ids(c: sqlite3.Connection, games: tuple[str, ...]) -> list[str]:
    """Track ids pitwall derived itself (GT7 / Forza start-line fingerprints) for re-matching on a new session."""
    marks = ",".join("?" * len(games))
    rows = c.execute(
        f"SELECT DISTINCT track_id FROM sessions WHERE game IN ({marks}) AND track_id IS NOT NULL "
        "AND synthetic = 0 ORDER BY track_id",
        games,
    ).fetchall()
    return [str(r[0]) for r in rows]


# ---------------------------------------------------------------- bests (dashboard D2)
# Same layout rule as ``clean_laps_for``: layouts that share a track id differ in length.
BESTS_LENGTH_TOLERANCE = 0.03
_SECTOR_COLUMNS = ("s1_ms", "s2_ms", "s3_ms")


def _layout_sql(track_length_m: float | None, alias: str = "s") -> tuple[str, list[Any]]:
    """SQL predicate (with a leading AND) keeping sessions of the same layout as ``track_length_m`` (or unknown)."""
    if track_length_m is None or track_length_m <= 0:
        return "", []
    length = f"{alias}.track_length_m"
    return (
        f" AND ({length} IS NULL OR ABS({length} - ?) <= ? * MAX({length}, ?))",
        [track_length_m, BESTS_LENGTH_TOLERANCE, track_length_m],
    )


def _bests(conn: sqlite3.Connection, where: str, args: list[Any]) -> dict[str, Any] | None:
    """The fastest clean lap and the fastest clean time in each sector on its own (``laps l JOIN sessions s``
    rows matching ``where``). Ties go to the lower lap id (the earlier lap). None when nothing clean has a time."""
    base = f"FROM laps l JOIN sessions s ON s.id = l.session_id WHERE l.clean=1 AND ({where})"
    lap = conn.execute(
        "SELECT l.id, l.lap_time_ms, l.created_unix, l.session_id, s.driver_id "
        f"{base} AND l.lap_time_ms IS NOT NULL AND l.lap_time_ms > 0 ORDER BY l.lap_time_ms, l.id LIMIT 1",
        args,
    ).fetchone()
    sectors: list[int | None] = []
    sector_ids: list[int | None] = []
    for col in _SECTOR_COLUMNS:
        r = conn.execute(
            f"SELECT l.id, l.{col} AS ms {base} AND l.{col} IS NOT NULL AND l.{col} > 0 ORDER BY l.{col}, l.id LIMIT 1",
            args,
        ).fetchone()
        sectors.append(None if r is None else int(r["ms"]))
        sector_ids.append(None if r is None else int(r["id"]))
    if lap is None and all(v is None for v in sectors):
        return None
    return {
        "lap_ms": None if lap is None else int(lap["lap_time_ms"]),
        "sectors_ms": sectors,
        "lap_id": None if lap is None else int(lap["id"]),
        "sector_lap_ids": sector_ids,
        "session_id": None if lap is None else lap["session_id"],
        "driver_id": None if lap is None or lap["driver_id"] is None else int(lap["driver_id"]),
        "set_unix": None if lap is None else lap["created_unix"],
    }


def _tier(b: dict[str, Any] | None, *extra: str) -> dict[str, Any] | None:
    if b is None:
        return None
    keep = ("lap_ms", "sectors_ms", "lap_id", "sector_lap_ids", *extra)
    return {k: b[k] for k in keep}


def lap_bests(
    conn: sqlite3.Connection,
    session_id: str,
    game: str | None,
    track_id: str | None,
    car_id: str | None,
    driver_id: int | None,
    track_length_m: float | None = None,
    *,
    records: bool = True,
) -> dict[str, Any]:
    """D2 ``snapshot.bests`` for a live session: clean laps only, each sector best on its own.

    * ``session`` - this session's own laps (always an object; values ``None`` until a clean lap).
    * ``driver`` - ``driver_id``'s best here (``set_unix`` = when that lap was stored), ``household`` - anyone's
      (``driver_id`` = who set the lap record). Both for this game + track + car + layout only, from real driving:
      synthetic sessions and replays never count. ``None`` when there is nothing yet, when the car is unknown (a
      record in another car is not a record here), when the session has no driver (``driver``), and for every
      synthetic or replayed live session (``records=False``: never a record or a personal best).
    """
    session = _tier(_bests(conn, "l.session_id=?", [session_id])) or {
        "lap_ms": None,
        "sectors_ms": [None, None, None],
        "lap_id": None,
        "sector_lap_ids": [None, None, None],
    }
    driver: dict[str, Any] | None = None
    household: dict[str, Any] | None = None
    if records and game and track_id and car_id is not None:
        layout, layout_args = _layout_sql(track_length_m)
        scope = f"s.game=? AND s.track_id=? AND s.car_id=? AND s.synthetic=0 AND {_DRIVEN}{layout}"
        scope_args: list[Any] = [game, track_id, car_id, *layout_args]
        if driver_id is not None:
            driver = _tier(
                _bests(conn, f"s.driver_id=? AND {scope}", [driver_id, *scope_args]), "set_unix", "session_id"
            )
        household = _tier(_bests(conn, scope, scope_args), "driver_id", "set_unix", "session_id")
    return {
        "scope": {"game": game, "track_id": track_id, "car_id": car_id, "records": records},
        "session": session,
        "driver": driver,
        "household": household,
    }


# ---------------------------------------------------------------- driver progress (dashboard D5)
def _progress_where(
    driver_id: int, game: str | None, track_id: str | None, car_id: str | None, include_synthetic: bool
) -> tuple[str, list[Any]]:
    """A driver's own driving (never replays), optionally one game / track / car; synthetic only on request."""
    where = [f"s.driver_id=? AND {_DRIVEN}"]
    args: list[Any] = [driver_id]
    if not include_synthetic:
        where.append("s.synthetic=0")
    for col, value in (("game", game), ("track_id", track_id), ("car_id", car_id)):
        if value is not None:
            where.append(f"s.{col}=?")
            args.append(value)
    return " AND ".join(where), args


def driver_progress_sessions(
    conn: sqlite3.Connection,
    driver_id: int,
    game: str | None = None,
    track_id: str | None = None,
    car_id: str | None = None,
    *,
    include_synthetic: bool = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """The driver's newest ``limit`` sessions with at least one lap, returned oldest first, each with ``laps``
    (every stored lap) and ``clean_lap_ms`` (clean lap times in lap order) for the per-session statistics."""
    where, args = _progress_where(driver_id, game, track_id, car_id, include_synthetic)
    rows = conn.execute(
        f"""SELECT s.id AS session_id, s.started_unix, s.game, s.track_id, s.track_name, s.car_id, s.car_name,
                  s.session_type, s.synthetic, COUNT(l.id) AS laps
           FROM sessions s JOIN laps l ON l.session_id = s.id
           WHERE {where} GROUP BY s.id ORDER BY s.started_unix DESC, s.id DESC LIMIT ?""",
        [*args, limit],
    ).fetchall()
    out = [{**dict(r), "synthetic": bool(r["synthetic"]), "clean_lap_ms": []} for r in reversed(rows)]
    by_id = {d["session_id"]: d for d in out}
    if by_id:
        marks = ",".join("?" * len(by_id))
        for r in conn.execute(
            f"""SELECT session_id, lap_time_ms FROM laps
                WHERE session_id IN ({marks}) AND clean=1 AND lap_time_ms IS NOT NULL AND lap_time_ms > 0
                ORDER BY session_id, lap_number""",
            list(by_id),
        ).fetchall():
            by_id[r["session_id"]]["clean_lap_ms"].append(int(r["lap_time_ms"]))
    return out


def pb_history(
    conn: sqlite3.Connection,
    driver_id: int,
    game: str | None = None,
    track_id: str | None = None,
    car_id: str | None = None,
    *,
    include_synthetic: bool = False,
) -> list[dict[str, Any]]:
    """Every clean lap that beat the driver's earlier best for its game + track + car, in the order driven:
    ``{game, track_id, track_name, car_id, car_name, lap_id, session_id, lap_number, lap_ms, set_unix,
    previous_ms, gain_ms, synthetic}``. The first lap at a track is a PB with ``previous_ms`` None."""
    where, args = _progress_where(driver_id, game, track_id, car_id, include_synthetic)
    rows = conn.execute(
        f"""SELECT l.id, l.session_id, l.lap_number, l.lap_time_ms, l.created_unix, s.game, s.track_id,
                  s.track_name, s.car_id, s.car_name, s.started_unix, s.synthetic
           FROM laps l JOIN sessions s ON s.id = l.session_id
           WHERE l.clean=1 AND l.lap_time_ms IS NOT NULL AND l.lap_time_ms > 0 AND s.track_id IS NOT NULL
             AND {where}
           ORDER BY s.started_unix, s.id, l.lap_number, l.id""",
        args,
    ).fetchall()
    best: dict[tuple[Any, ...], int] = {}
    out: list[dict[str, Any]] = []
    for r in rows:
        key = (r["game"], r["track_id"], r["car_id"])
        ms = int(r["lap_time_ms"])
        prev = best.get(key)
        if prev is not None and ms >= prev:
            continue
        best[key] = ms
        out.append(
            {
                "game": r["game"],
                "track_id": r["track_id"],
                "track_name": r["track_name"],
                "car_id": r["car_id"],
                "car_name": r["car_name"],
                "lap_id": int(r["id"]),
                "session_id": r["session_id"],
                "lap_number": r["lap_number"],
                "lap_ms": ms,
                "set_unix": r["created_unix"] if r["created_unix"] is not None else r["started_unix"],
                "previous_ms": prev,
                "gain_ms": None if prev is None else prev - ms,
                "synthetic": bool(r["synthetic"]),
            }
        )
    return out


# ---------------------------------------------------------------- coachref (schema v3)
# Reference choices (what a driver's live delta measures against) and practice drills; the rules live in
# ``core.coachref`` and ``coach.drills``, these functions only store and read rows.
_DRILL_UPDATABLE = frozenset(
    {
        "status",
        "stop_reason",
        "ended_unix",
        "attempts",
        "scored",
        "hits",
        "best_value",
        "best_delta",
        "trend",
        "laps",
        "detail",
    }
)
_DRILL_COLUMNS = (
    "driver_id",
    "session_id",
    "game",
    "track_id",
    "track_length_m",
    "car_id",
    "track_model_version",
    "corner",
    "corner_label",
    "corner_voice",
    "apex_m",
    "kind",
    "source",
    "observation_kind",
    "laps_target",
    "target",
    "tolerance",
    "unit",
    "baseline",
    "ref_lap_id",
    "ref_kind",
    "ref_driver_id",
    "status",
    "stop_reason",
    "started_unix",
    "ended_unix",
    "attempts",
    "scored",
    "hits",
    "best_value",
    "best_delta",
    "trend",
    "laps",
    "detail",
)


def _choice_row(r: sqlite3.Row | None) -> dict[str, Any] | None:
    return None if r is None else dict(r)


def reference_choice_rows(
    conn: sqlite3.Connection, driver_id: int, game: str | None, track_id: str | None
) -> dict[str, dict[str, Any] | None]:
    """``{"all_tracks": row | None, "track": row | None}`` for a driver (``track`` only when game and track are
    given). Rows: ``driver_id, game, track_id, kind, target_driver_id, lap_id, updated_unix``."""
    q = "SELECT * FROM reference_choices WHERE driver_id=? AND game=? AND track_id=?"
    all_tracks = _choice_row(conn.execute(q, (driver_id, "", "")).fetchone())
    track = None
    if game and track_id:
        track = _choice_row(conn.execute(q, (driver_id, game, track_id)).fetchone())
    return {"all_tracks": all_tracks, "track": track}


def set_reference_choice(
    conn: sqlite3.Connection,
    driver_id: int,
    kind: str,
    *,
    game: str = "",
    track_id: str = "",
    target_driver_id: int | None = None,
    lap_id: int | None = None,
) -> dict[str, Any]:
    """Upsert a driver's choice for one track (``game``/``track_id``) or every track (both ``''``)."""
    conn.execute(
        """INSERT INTO reference_choices(driver_id, game, track_id, kind, target_driver_id, lap_id, updated_unix)
           VALUES(?,?,?,?,?,?,?)
           ON CONFLICT(driver_id, game, track_id) DO UPDATE SET kind=excluded.kind,
             target_driver_id=excluded.target_driver_id, lap_id=excluded.lap_id, updated_unix=excluded.updated_unix""",
        (driver_id, game, track_id, kind, target_driver_id, lap_id, time.time()),
    )
    row = conn.execute(
        "SELECT * FROM reference_choices WHERE driver_id=? AND game=? AND track_id=?", (driver_id, game, track_id)
    ).fetchone()
    return dict(row)


def delete_reference_choice(conn: sqlite3.Connection, driver_id: int, game: str, track_id: str) -> bool:
    cur = conn.execute(
        "DELETE FROM reference_choices WHERE driver_id=? AND game=? AND track_id=?", (driver_id, game, track_id)
    )
    return cur.rowcount > 0


_WET_CONDITIONS = ("light_rain", "heavy_rain", "storm")  # analysis.compare.check_compatibility's wet set
_MATCHED_ASSISTS = ("braking", "gearbox", "abs", "tc")  # check_compatibility + core.coachref.extra_blocking


def _scalar(v: object) -> bool:
    return isinstance(v, str | int | float) and v == v  # bool is an int; NaN != NaN


def _compat_sql(match: dict[str, Any] | None) -> tuple[str, list[Any]]:
    """SQL predicates (each with a leading AND) dropping the laps ``core.coachref.comparable`` would block for the
    live context ``match``: wet/dry, the braking / gearbox / ABS / TC assists and F1's formula. Only known values on
    both sides block (unknown never excludes a lap), exactly as the Python check, which still runs on every row."""
    if not match:
        return "", []
    sql: list[str] = []
    args: list[Any] = []
    weather = match.get("weather")
    if isinstance(weather, dict):
        weather = weather.get("condition")
    if isinstance(weather, str) and weather:
        cond = "json_extract(s.weather, '$.condition')"
        sql.append(f" AND (COALESCE({cond}, '') = '' OR ({cond} IN ({', '.join('?' * len(_WET_CONDITIONS))})) = ?)")
        args += [*_WET_CONDITIONS, int(weather in _WET_CONDITIONS)]
    assists = match.get("assists")
    if isinstance(assists, dict):
        for key in _MATCHED_ASSISTS:
            v = assists.get(key)
            if v is not None and _scalar(v):
                path = f"json_extract(s.assists, '$.{key}')"
                sql.append(f" AND ({path} IS NULL OR {path} = ?)")
                args.append(v)
    formula = match.get("formula")
    if formula is not None and _scalar(formula):
        sql.append(" AND (json_extract(s.info, '$.formula') IS NULL OR json_extract(s.info, '$.formula') = ?)")
        args.append(formula)
    return "".join(sql), args


def reference_candidates(
    conn: sqlite3.Connection,
    game: str,
    track_id: str,
    car_id: str | None,
    track_length_m: float | None,
    *,
    per_driver: int = 10,
    exclude_lap_id: int | None = None,
    driver_id: int | None = None,
    match: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Clean laps of real driving by any driver (or ``driver_id``) at a game + track (+ car) + layout, the fastest
    ``per_driver`` per driver, fastest first (ties: lower lap id). Never synthetic, never replays, never unowned.
    ``car_id=None`` lists every car and ``track_length_m=None`` every layout (``core.coachref`` uses that only to
    say *why* a driver has no comparable lap). ``match`` (a live lap context): laps in other conditions (wet/dry,
    assists, formula: ``_compat_sql``) are left out *before* the per-driver limit, so a driver's ten fastest laps in
    other conditions never hide a slower comparable one. Rows: ``lap_id, lap_number, lap_time_ms, s1_ms..s3_ms,
    session_id, created_unix, meta, setup_fp, driver_id, driver_name, game, track_id, car_id, car_name,
    track_length_m, weather, assists, formula, started_unix``."""
    where = [
        "l.clean=1",
        "l.lap_time_ms IS NOT NULL",
        "l.lap_time_ms > 0",
        "s.game=?",
        "s.track_id=?",
        "s.synthetic=0",
        _DRIVEN,
        "s.driver_id IS NOT NULL",
    ]
    args: list[Any] = [game, track_id]
    if car_id is not None:
        where.append("s.car_id=?")
        args.append(car_id)
    if exclude_lap_id is not None:
        where.append("l.id != ?")
        args.append(exclude_lap_id)
    if driver_id is not None:
        where.append("s.driver_id=?")
        args.append(driver_id)
    layout, layout_args = _layout_sql(track_length_m)
    conds, cond_args = _compat_sql(match)
    rows = conn.execute(
        f"""SELECT * FROM (
              SELECT l.id AS lap_id, l.lap_number, l.lap_time_ms, l.s1_ms, l.s2_ms, l.s3_ms, l.session_id,
                     l.created_unix, l.meta, l.setup_fp, s.driver_id, d.name AS driver_name, s.game, s.track_id,
                     s.car_id, s.car_name, s.track_length_m, s.weather, s.assists,
                     json_extract(s.info, '$.formula') AS formula, s.started_unix,
                     ROW_NUMBER() OVER (PARTITION BY s.driver_id ORDER BY l.lap_time_ms ASC, l.id ASC) AS rn
              FROM laps l JOIN sessions s ON s.id = l.session_id JOIN drivers d ON d.id = s.driver_id
              WHERE {" AND ".join(where)}{layout}{conds})
           WHERE rn <= ? ORDER BY lap_time_ms ASC, lap_id ASC""",
        [*args, *layout_args, *cond_args, per_driver],
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d.pop("rn", None)
        d["meta"] = json.loads(d["meta"] or "{}")
        d["weather"] = json.loads(d["weather"] or "{}")
        d["assists"] = json.loads(d["assists"] or "{}")
        out.append(d)
    return out


def lap_with_context(conn: sqlite3.Connection, lap_id: int) -> dict[str, Any] | None:
    """A lap (no trace) with its session's context and its driver's name: ``lap_id, lap_number, lap_time_ms,
    s1_ms..s3_ms, clean, valid, flags, meta, setup_fp, session_id, created_unix, driver_id, driver_name, game,
    track_id, track_name, track_length_m, car_id, car_name, weather, assists, formula, synthetic, source,
    started_unix``. None for an unknown lap."""
    r = conn.execute(
        """SELECT l.id AS lap_id, l.lap_number, l.lap_time_ms, l.s1_ms, l.s2_ms, l.s3_ms, l.clean, l.valid, l.flags,
                  l.meta, l.setup_fp, l.session_id, l.created_unix, s.driver_id, d.name AS driver_name, s.game,
                  s.track_id, s.track_name, s.track_length_m, s.car_id, s.car_name, s.weather, s.assists,
                  json_extract(s.info, '$.formula') AS formula, s.synthetic, s.source, s.started_unix
           FROM laps l JOIN sessions s ON s.id = l.session_id LEFT JOIN drivers d ON d.id = s.driver_id
           WHERE l.id=?""",
        (lap_id,),
    ).fetchone()
    if r is None:
        return None
    d = dict(r)
    d["clean"] = bool(d["clean"])
    d["valid"] = None if d["valid"] is None else bool(d["valid"])
    d["synthetic"] = bool(d["synthetic"])
    d["flags"] = json.loads(d["flags"] or "[]")
    d["meta"] = json.loads(d["meta"] or "{}")
    d["weather"] = json.loads(d["weather"] or "{}")
    d["assists"] = json.loads(d["assists"] or "{}")
    return d


def _drill_row(r: sqlite3.Row) -> dict[str, Any]:
    d = dict(r)
    d["laps"] = json.loads(d.get("laps") or "[]")
    d["detail"] = json.loads(d.get("detail") or "{}")
    return d


def insert_drill(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    """Insert a drill (``coach.drills.spec_row``); ``laps`` / ``detail`` are stored as JSON. Returns its id."""
    cols = [c for c in _DRILL_COLUMNS if c in row]
    vals = [dumps(row[c]) if c in ("laps", "detail") else row[c] for c in cols]
    cur = conn.execute(f"INSERT INTO drills({', '.join(cols)}) VALUES({','.join('?' * len(cols))})", vals)
    return int(cur.lastrowid or 0)


def update_drill(conn: sqlite3.Connection, drill_id: int, **fields: Any) -> None:
    """Update a drill's changing columns (``coach.drills.state_fields``); ``laps`` / ``detail`` are stored as JSON."""
    bad = set(fields) - _DRILL_UPDATABLE
    if bad:
        raise ValueError(f"not updatable: {sorted(bad)}")
    if not fields:
        return
    cols = sorted(fields)
    vals = [dumps(fields[c]) if c in ("laps", "detail") else fields[c] for c in cols]
    conn.execute(f"UPDATE drills SET {', '.join(f'{c}=?' for c in cols)} WHERE id=?", [*vals, drill_id])


def get_drill(conn: sqlite3.Connection, drill_id: int) -> dict[str, Any] | None:
    r = conn.execute("SELECT * FROM drills WHERE id=?", (drill_id,)).fetchone()
    return _drill_row(r) if r else None


def list_drills(
    conn: sqlite3.Connection,
    driver_id: int | None = None,
    game: str | None = None,
    track_id: str | None = None,
    car_id: str | None = None,
    *,
    include_empty: bool = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Drills newest first, optionally one driver / game / track / car. ``abandoned`` drills (stopped with no
    attempt) only with ``include_empty``."""
    where: list[str] = []
    args: list[Any] = []
    for col, val in (("driver_id", driver_id), ("game", game), ("track_id", track_id), ("car_id", car_id)):
        if val is not None:
            where.append(f"{col}=?")
            args.append(val)
    if not include_empty:
        where.append("status != 'abandoned'")
    sql = "SELECT * FROM drills" + (f" WHERE {' AND '.join(where)}" if where else "")
    rows = conn.execute(sql + " ORDER BY started_unix DESC, id DESC LIMIT ?", [*args, limit]).fetchall()
    return [_drill_row(r) for r in rows]


def stop_active_drills(conn: sqlite3.Connection, reason: str, now: float) -> int:
    """End every drill still marked active (service start-up: drills never survive a restart). A drill with
    attempts becomes ``stopped``, one without ``abandoned``. Returns how many were ended."""
    cur = conn.execute(
        """UPDATE drills SET status = CASE WHEN attempts > 0 THEN 'stopped' ELSE 'abandoned' END,
               stop_reason=?, ended_unix=? WHERE status='active'""",
        (reason, now),
    )
    return int(cur.rowcount)
