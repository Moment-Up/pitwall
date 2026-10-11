"""Builders for the motivation tests: in-memory rows (``SessionRow`` / ``LapRow`` / ``History`` / ``GoalRow``) and
database seeding (sessions with real-shaped laps and events, without lap analysis).

Numbers mirror the real F1 25 PS5 data the lane was designed on (docs: lane motivation spec section 2): Austria in the
Haas, 1:10.549 best, 1:09.962 ideal. Names are fictional ("Sam", "Jo").
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np

from pitwall.analysis.laps import LapTrace
from pitwall.model.telemetry import EventKind, Game, GameEvent, SessionInfo, SessionType
from pitwall.motivation.model import GoalRow, History, LapRow, Scope, SessionRow
from pitwall.storage import repo
from pitwall.storage.db import DbWriter

T0 = datetime(2026, 10, 10, 19, 15).timestamp()  # Sat 10 Oct 2026, local time
DAY = 86_400.0
AUSTRIA = {"game": "f1_25", "track_id": "f1:17", "track_name": "Austria", "track_length_m": 4318.0}
HAAS = {"car_id": "f1:team:7", "car_name": "Haas"}
_ids = iter(range(1, 10_000_000))


def lap(
    n: int,
    ms: int | None,
    *,
    sid: str = "s1",
    clean: bool | None = None,
    flags: Iterable[str] = (),
    valid: bool | None = None,
    sectors: tuple[int | None, int | None, int | None] = (None, None, None),
    lap_id: int | None = None,
) -> LapRow:
    f = frozenset(flags)
    bad = {"flashback", "pit_in", "pit_out", "incomplete", "invalid", "standing_start", "distance_jump"}
    is_clean = (not (f & bad) and valid is not False and ms is not None) if clean is None else clean
    return LapRow(
        id=next(_ids) if lap_id is None else lap_id,
        session_id=sid,
        lap_number=n,
        lap_time_ms=ms,
        s1_ms=sectors[0],
        s2_ms=sectors[1],
        s3_ms=sectors[2],
        valid=valid,
        clean=is_clean,
        flags=f,
    )


def laps(sid: str, times: Sequence[int | None], first: int = 1, **kw: Any) -> list[LapRow]:
    return [lap(first + i, ms, sid=sid, **kw) for i, ms in enumerate(times)]


def sess(sid: str, started: float = T0, **kw: Any) -> SessionRow:
    d: dict[str, Any] = {
        "id": sid,
        "started_unix": started,
        "ended_unix": None,
        **AUSTRIA,
        **HAAS,
        "session_type": "race",
        "synthetic": False,
        "source": "udp:20777",
        "driver_id": 1,
        "total_laps": None,
        "formula": "F1 World",
        "car_class": None,
    }
    d.update(kw)
    return SessionRow.from_row(d)


def history(*pairs: tuple[SessionRow, list[LapRow]], events: dict[str, list[dict[str, Any]]] | None = None) -> History:
    return History([s for s, _ in pairs], {s.id: list(ls) for s, ls in pairs}, events or {})


def goal(
    kind: str,
    target: float,
    *,
    gid: int = 1,
    params: dict[str, Any] | None = None,
    scope: Scope | None = None,
    after: int = 0,
    baseline: float | None = None,
    status: str = "active",
    created: float = T0 - DAY,
    achieved_unix: float | None = None,
    achieved_session_id: str | None = None,
    achieved_lap_id: int | None = None,
    achieved_value: float | None = None,
) -> GoalRow:
    sc = scope if scope is not None else Scope()
    return GoalRow.from_row(
        {
            "id": gid,
            "driver_id": 1,
            "kind": kind,
            "status": status,
            "target": target,
            "params": params or {},
            "game": sc.game,
            "track_id": sc.track_id,
            "track_name": sc.track_name,
            "track_length_m": sc.track_length_m,
            "car_id": sc.car_id,
            "car_class": sc.car_class,
            "car_name": sc.car_name,
            "baseline": baseline,
            "after_lap_id": after,
            "source": "manual",
            "basis": None,
            "created_unix": created,
            "achieved_unix": achieved_unix,
            "achieved_session_id": achieved_session_id,
            "achieved_lap_id": achieved_lap_id,
            "achieved_value": achieved_value,
        }
    )


AUSTRIA_HAAS = Scope(
    game="f1_25", track_id="f1:17", track_name="Austria", track_length_m=4318.0, car_id="f1:team:7", car_name="Haas"
)


def penalty(ptype: int, *, player: int = 19, vehicle: int = 19, infringement: int = 3) -> dict[str, Any]:
    """A real-shaped PENA payload (numbers as seen in the F1 25 PS5 captures)."""
    return {
        "kind": "penalty",
        "code": "PENA",
        "payload": {
            "penaltyType": ptype,
            "infringementType": infringement,
            "vehicleIdx": vehicle,
            "otherVehicleIdx": 4,
            "time": 3,
            "lapNum": 1,
            "placesGained": 0,
            "player_idx": player,
        },
    }


def collision(a: int = 19, b: int = 4, *, player: int | None = 19) -> dict[str, Any]:
    payload: dict[str, Any] = {"vehicle1Idx": a, "vehicle2Idx": b}
    if player is not None:
        payload["player_idx"] = player
    return {"kind": "collision", "code": "COLL", "payload": payload}


# ---------------------------------------------------------------------------------------------- database seeding
@dataclass
class SeedLap:
    n: int
    ms: int | None
    flags: tuple[str, ...] = ()
    valid: bool | None = None
    sectors: tuple[int | None, int | None, int | None] = (None, None, None)
    t_ns: tuple[int, int] | None = None  # the lap's first and last receive time (lap meta), when a test needs it


def trace(seed: SeedLap) -> LapTrace:
    d = np.linspace(0.0, 4318.0, 8)
    meta = {} if seed.t_ns is None else {"t_recv_start_ns": seed.t_ns[0], "t_recv_end_ns": seed.t_ns[1]}
    return LapTrace(
        lap_number=seed.n,
        channels={"distance_m": d, "speed_kph": np.full(8, 200.0), "session_time_s": np.linspace(0, 70, 8)},
        lap_time_ms=seed.ms,
        sector_times_ms=list(seed.sectors),
        valid=seed.valid,
        flags=set(seed.flags),
        meta=meta,
    )


@dataclass
class SeedSession:
    sid: str
    driver_id: int | None
    started: float
    laps: list[SeedLap] = field(default_factory=list)
    game: Game = Game.F1_25
    track_id: str = "f1:17"
    track_name: str = "Austria"
    track_length_m: float = 4318.0
    car_id: str = "f1:team:7"
    car_name: str = "Haas"
    session_type: SessionType = SessionType.RACE
    total_laps: int | None = None
    formula: str | None = "F1 World"
    source: str = "udp:20777"
    synthetic: bool = False
    events: list[GameEvent] = field(default_factory=list)


def seed(writer: DbWriter, s: SeedSession) -> list[int]:
    """Insert a session with its laps and events (no analysis); returns the lap ids."""
    info = SessionInfo(
        game=s.game,
        track_id=s.track_id,
        track_name=s.track_name,
        track_length_m=s.track_length_m,
        session_type=s.session_type,
        total_laps=s.total_laps,
        car_id=s.car_id,
        car_name=s.car_name,
        formula=s.formula,
    )

    def job(c: sqlite3.Connection) -> list[int]:
        repo.insert_session(c, s.sid, s.game.value, s.source, s.synthetic, None, None, driver_id=s.driver_id)
        repo.update_session_info(c, s.sid, info)
        repo.scratch_relabel_session(c, s.sid, source=s.source, started_unix=s.started, ended_unix=s.started + 600)
        ids = [repo.insert_lap(c, s.sid, trace(lp), None) for lp in s.laps]
        for e in s.events:
            repo.insert_event(c, s.sid, e)
        return ids

    return writer.call(job)


def seed_laps(times: Sequence[int | None], first: int = 1, **kw: Any) -> list[SeedLap]:
    return [SeedLap(first + i, ms, **kw) for i, ms in enumerate(times)]


def game_event(kind: EventKind, payload: dict[str, Any], t_recv_ns: int = 0) -> GameEvent:
    return GameEvent(kind=kind, game=Game.F1_25, t_recv_ns=t_recv_ns, code=None, payload=payload)
