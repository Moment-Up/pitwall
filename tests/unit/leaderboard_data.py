"""Seeding for the family leaderboard tests: sessions with full control of what a board key reads (session type,
weather, assists, formula, lap meta) and of when each lap was stored (``created_unix``: the record history's order).

Shapes mirror the owner's real F1 25 data (Austria in the Haas, braking assist medium, automatic gears, full racing
line, 1:10.549 best, sectors 16.662 / 31.149 / 22.151 at best) and GT7's start-line track ids. Names are fictional.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from pitwall.storage import repo

T0 = datetime(2026, 10, 10, 19, 15).timestamp()  # Sat 10 Oct 2026, local time
HOUR = 3600.0
DAY = 86_400.0
# the Session tail of a real F1 25 race (owner's Austria session; equal performance off)
F1_ASSISTS: dict[str, Any] = {
    "steering": 0,
    "braking": 2,
    "gearbox": 3,
    "pit": 1,
    "pit_release": 1,
    "ers": 1,
    "drs": 1,
    "dynamic_racing_line": 2,
    "dynamic_racing_line_type": 1,
    "equal_car_performance": 0,
}
UNFILLED_TAIL = {k: 0 for k in F1_ASSISTS}  # the first ~1.5 s of every F1 25 session
F1_META: dict[str, Any] = {"abs_active": True, "traction_control": 2}
AUSTRIA_KEY = "f1_25~f1:17~4318~f1:team:7~f1~0~race~dry~b2.a1.t2.g3.l2"


def add_driver(c: sqlite3.Connection, name: str) -> int:
    return repo.insert_driver(c, name, {})


def add_session(
    c: sqlite3.Connection,
    sid: str,
    driver: int | None,
    *,
    game: str = "f1_25",
    track: str | None = "f1:17",
    track_name: str | None = "Austria",
    length: float | None = 4318.0,
    car: str | None = "f1:team:7",
    car_name: str | None = "Haas",
    session_type: str = "race",
    weather: str | None = "clear",
    assists: dict[str, Any] | None = None,
    formula: str | None = "F1 World",
    synthetic: bool = False,
    source: str = "udp:20777",
    started: float = T0,
    version: str | None = "1.26",
    capture_path: str | None = None,
) -> str:
    repo.insert_session(c, sid, game, source, synthetic, capture_path, None, driver_id=driver)
    info: dict[str, Any] = {}
    if formula is not None:
        info["formula"] = formula
    if game.startswith("f1"):
        info["packet_format"] = 2025
        if version is not None:
            info["game_version"] = version
    c.execute(
        """UPDATE sessions SET track_id=?, track_name=?, track_length_m=?, car_id=?, car_name=?, session_type=?,
               weather=?, assists=?, info=?, started_unix=?, platform=? WHERE id=?""",
        (
            track,
            track_name,
            length,
            car,
            car_name,
            session_type,
            json.dumps({} if weather is None else {"condition": weather}),
            json.dumps(F1_ASSISTS if assists is None and game.startswith("f1") else (assists or {})),
            json.dumps(info),
            started,
            "ps5" if game.startswith("f1") else "unknown",
            sid,
        ),
    )
    return sid


def add_lap(
    c: sqlite3.Connection,
    sid: str,
    n: int,
    ms: int | None,
    *,
    created: float,
    sectors: tuple[int | None, int | None, int | None] = (None, None, None),
    clean: bool = True,
    valid: bool | None = True,
    meta: dict[str, Any] | None = None,
    flags: tuple[str, ...] = (),
) -> int:
    """A stored lap (no trace). ``meta`` None: F1 25's ABS on / TC full for an F1 session, nothing otherwise."""
    if meta is None:
        game = c.execute("SELECT game FROM sessions WHERE id=?", (sid,)).fetchone()["game"]
        meta = dict(F1_META) if str(game).startswith("f1") else {}
    cur = c.execute(
        """INSERT INTO laps(session_id, lap_number, lap_time_ms, s1_ms, s2_ms, s3_ms, valid, clean, flags, meta,
               n_samples, trace, created_unix) VALUES(?,?,?,?,?,?,?,?,?,?,0,x'',?)""",
        (
            sid,
            n,
            ms,
            *sectors,
            None if valid is None else int(valid),
            int(clean),
            json.dumps(list(flags)),
            json.dumps(meta),
            created,
        ),
    )
    return int(cur.lastrowid or 0)
