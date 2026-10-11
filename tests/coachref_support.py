"""Shared builders for the coachref tests: two drivers on the synthetic F1 laps (``tests.conftest`` sessions).

The synthetic laps are stored as ordinary *non-synthetic* rows on purpose: these tests exercise cross-driver
resolution, wording, the braking clamp and drills. They are never evidence of game compatibility.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from pitwall.analysis.laps import LapTrace
from pitwall.core.coachref import CoachRef
from pitwall.core.lap_processor import LapJob, LapProcessor
from pitwall.core.live import LiveState
from pitwall.drivers import DriverService
from pitwall.model.telemetry import SessionInfo, Weather
from pitwall.storage import repo
from pitwall.storage.db import Database, DbWriter
from tests.unit.test_drivers import copy_lap, lap_ctx

__all__ = [
    "CONTRACT",
    "Env",
    "copy_lap",
    "drive",
    "keys",
    "lap_ctx",
    "make_env",
    "new_session",
    "run_now",
    "session_info",
]

T = TypeVar("T")


def run_now[T](fn: Callable[[], T]) -> Future[T]:
    """A synchronous ``run_task``: runs ``fn`` at once on the caller's thread."""
    fut: Future[T] = Future()
    try:
        fut.set_result(fn())
    except BaseException as e:
        fut.set_exception(e)
    return fut


@dataclass
class Env:
    db: Database
    writer: DbWriter
    live: LiveState
    drivers: DriverService
    proc: LapProcessor
    svc: CoachRef

    def close(self) -> None:
        self.svc.close()
        self.writer.close()


def make_env(tmp_path: Path, *, clock: Callable[[], float] | None = None) -> Env:
    db = Database(tmp_path / "coachref.sqlite3")
    writer = DbWriter(db)
    live = LiveState()
    drivers = DriverService(db, writer)
    proc = LapProcessor(db, writer, live)
    kw: dict[str, Any] = {} if clock is None else {"clock": clock}
    svc = CoachRef(db, writer, live, drivers, run_task=run_now, processor=proc, **kw)
    proc.coachref = svc
    return Env(db, writer, live, drivers, proc, svc)


def session_info(
    info: SessionInfo,
    *,
    assists: dict[str, Any] | None = None,
    condition: str | None = None,
    formula: str | None = None,
    car_id: str | None = None,
    track_length_m: float | None = None,
) -> SessionInfo:
    """``info`` with other conditions (a different driver's session at the same synthetic track)."""
    changes: dict[str, Any] = {}
    if assists is not None:
        changes["assists"] = {**info.assists, **assists}
    if condition is not None:
        changes["weather"] = dataclasses.replace(info.weather or Weather(), condition=condition)
    if formula is not None:
        changes["formula"] = formula
    if car_id is not None:
        changes["car_id"] = car_id
    if track_length_m is not None:
        changes["track_length_m"] = track_length_m
    return dataclasses.replace(info, **changes)


def new_session(
    writer: DbWriter,
    driver_id: int | None,
    info: SessionInfo,
    sid: str,
    *,
    source: str = "udp:20777",
    synthetic: bool = False,
) -> str:
    def job(c: sqlite3.Connection) -> None:
        repo.insert_session(c, sid, info.game.value, source, synthetic, None, None, driver_id=driver_id)
        repo.update_session_info(c, sid, info)

    writer.call(job)
    return sid


def drive(
    proc: LapProcessor, sid: str, info: SessionInfo, laps: list[tuple[LapTrace, int, int]]
) -> list[dict[str, Any]]:
    """Process ``(trace, lap time ms, lap number)`` laps in order; returns the processor results."""
    ctx = lap_ctx(info)
    return [proc.process(LapJob(sid, copy_lap(lap, ms, n), ctx)) for lap, ms, n in laps]


# The JSON contract shared with the dashboard (design spec section 6.2 / 6.3): exact key sets. A key added or
# removed on either side must change this table and the dashboard's types together.
CONTRACT: dict[str, frozenset[str]] = {
    "ReferenceChoice": frozenset(
        {"driver_id", "kind", "target_driver_id", "lap_id", "scope", "game", "track_id", "label", "updated_unix"}
    ),
    "ReferenceDescriptor": frozenset(
        {
            "lap_id",
            "lap_number",
            "lap_time_ms",
            "session_id",
            "kind",
            "own",
            "pinned",
            "driver_id",
            "driver_name",
            "set_unix",
            "label",
            "label_to",
            "ref_name",
            "brake_clamped",
            "frozen",
        }
    ),
    "RefOptionLap": frozenset(
        {"lap_id", "lap_number", "lap_time_ms", "set_unix", "driver_id", "driver_name", "session_id", "car_name"}
    ),
    "RefOption": frozenset(
        {"kind", "target_driver_id", "lap_id", "label", "available", "reason", "warnings", "lap", "selected"}
    ),
    "RefOptionsResponse": frozenset({"driver_id", "context", "choice", "has_track_override", "options", "applies"}),
    "RefContext": frozenset({"game", "track_id", "track_name", "car_id", "car_name", "track_length_m"}),
    "CandidatesResponse": frozenset({"lap_id", "driver_id", "groups"}),
    "CandidatesGroup": frozenset({"id", "title", "options"}),
    "ChoiceResponse": frozenset({"choice", "applies"}),
    "ChoiceRows": frozenset({"all_tracks", "track", "effective"}),
    "CompareResponse": frozenset({"comparison", "observations", "track_model", "reference"}),
    "DrillAttempt": frozenset(
        {
            "attempt",
            "lap_id",
            "lap_number",
            "value",
            "target",
            "delta",
            "outcome",
            "reason",
            "corner_time_s",
            "corner_time_delta_s",
            "text",
            "short",
        }
    ),
    "DrillView": frozenset(
        {
            "id",
            "driver_id",
            "session_id",
            "game",
            "track_id",
            "car_id",
            "corner",
            "corner_label",
            "corner_voice",
            "kind",
            "skill_label",
            "source",
            "laps_target",
            "target",
            "tolerance",
            "unit",
            "baseline",
            "target_text",
            "note",
            "reference",
            "status",
            "stop_reason",
            "started_unix",
            "ended_unix",
            "attempts",
            "hits",
            "scored",
            "best",
            "best_delta",
            "trend",
            "summary_text",
            "synthetic",
        }
    ),
    "DrillReference": frozenset({"lap_id", "kind", "driver_name", "label"}),
    "DrillOption": frozenset(
        {
            "kind",
            "skill_label",
            "available",
            "reason",
            "target",
            "unit",
            "tolerance",
            "baseline",
            "target_text",
            "note",
            "tolerance_choices",
            "suggested",
        }
    ),
    "DrillOptionsResponse": frozenset(
        {"corner", "corner_label", "corner_voice", "available", "reason", "laps_choices", "default_laps", "kinds"}
    ),
    "SnapshotCoachref": frozenset({"driver_id", "choice", "used_kind", "reason", "pending", "drill"}),
}


def keys(name: str, obj: object) -> None:
    """Assert ``obj`` has exactly the contract's keys for ``name``."""
    assert isinstance(obj, dict), (name, obj)
    assert set(obj) == CONTRACT[name], (name, sorted(set(obj) ^ CONTRACT[name]))
