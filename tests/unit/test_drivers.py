"""Driver profiles: migration, active driver, session tagging/splitting, per-driver isolation, API.

The core guarantee under test: one driver's lap is never another driver's reference, personal best or coaching
history, while track models stay shared. Session streams are SYNTHETIC (generated packets); they exercise the
pipeline's bookkeeping, not game compatibility.
"""

from __future__ import annotations

import dataclasses
import logging
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TypeVar, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.ai.facts import build_fact_sheet
from pitwall.analysis.laps import LapTrace
from pitwall.api.routes_drivers import router
from pitwall.core import session_analysis
from pitwall.core.lap_processor import AnalysisWorker, LapJob, LapProcessor
from pitwall.core.live import LiveState
from pitwall.core.session import SessionManager
from pitwall.core.session_analysis import SessionAnalyzer
from pitwall.drivers import (
    BEGINNER_KINDS,
    DEFAULT_DRIVER_NAME,
    NO_INITIALS,
    PALETTE,
    CoachingLimits,
    Driver,
    DriverConflictError,
    DriverPreferences,
    DriverService,
    DriverValidationError,
    NotFoundError,
    SeatState,
    apply_coaching_limits,
    coaching_limits,
    default_initials,
)
from pitwall.ingest.capture import CapturedPacket
from pitwall.model.telemetry import EventKind, Game, GameEvent, SessionInfo
from pitwall.storage import repo
from pitwall.storage.db import SCHEMA, SCHEMA_VERSION, Database, DbWriter
from tests.conftest import DecodedSession

T = TypeVar("T")

# reference_laps exactly as schema v1 created it (before per-driver pins)
V1_REFERENCE_LAPS = """
CREATE TABLE reference_laps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lap_id INTEGER NOT NULL REFERENCES laps(id) ON DELETE CASCADE,
    game TEXT NOT NULL,
    track_id TEXT NOT NULL,
    car_id TEXT,
    kind TEXT NOT NULL,
    label TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_unix REAL NOT NULL
);
"""


# ---------------------------------------------------------------------------------------------- fixtures / helpers
@pytest.fixture
def store(tmp_path: Path) -> Iterator[tuple[Database, DbWriter]]:
    db = Database(tmp_path / "pitwall.sqlite3")
    writer = DbWriter(db)
    yield db, writer
    writer.close()


@pytest.fixture
def svc(store: tuple[Database, DbWriter]) -> DriverService:
    return DriverService(*store)


def make_v1_db(path: Path) -> None:
    """A database as the v1 build left it: no drivers, sessions without driver_id, v1 reference_laps."""
    with closing(sqlite3.connect(path)) as c:
        c.execute(V1_REFERENCE_LAPS)
        c.executescript(SCHEMA)  # reference_laps already exists, so its v1 layout is kept
        c.execute("INSERT INTO meta(key, value) VALUES('schema_version', '1')")
        for i in range(3):
            c.execute(
                "INSERT INTO sessions(id, game, track_id, car_id, started_unix, source) VALUES(?,?,?,?,?,?)",
                (f"legacy{i}", "f1_25", "f1:10", "f1:team:8", 1000.0 + i, "udp:20777"),
            )
            c.execute(
                "INSERT INTO laps(session_id, lap_number, lap_time_ms, clean, n_samples, trace, created_unix) "
                "VALUES(?,?,?,?,?,?,?)",
                (f"legacy{i}", 1, 90_000 + i, 1, 0, b"", 1000.0),
            )
        c.execute(
            "INSERT INTO reference_laps(lap_id, game, track_id, car_id, kind, created_unix) "
            "VALUES(1, 'f1_25', 'f1:10', 'f1:team:8', 'pinned', 1000.0)"
        )
        c.commit()


def copy_lap(lap: LapTrace, lap_time_ms: int | None = None, lap_number: int | None = None) -> LapTrace:
    return LapTrace(
        lap_number=lap.lap_number if lap_number is None else lap_number,
        channels=lap.channels,
        lap_time_ms=lap.lap_time_ms if lap_time_ms is None else lap_time_ms,
        sector_times_ms=list(lap.sector_times_ms),
        valid=lap.valid,
        flags=set(lap.flags),
        meta=dict(lap.meta),
    )


def new_session(writer: DbWriter, driver_id: int | None, info: SessionInfo, sid: str) -> str:
    def job(c: sqlite3.Connection) -> None:
        repo.insert_session(c, sid, info.game.value, "test", False, None, None, driver_id=driver_id)
        repo.update_session_info(c, sid, info)

    writer.call(job)
    return sid


def add_laps(writer: DbWriter, sid: str, laps: list[LapTrace]) -> list[int]:
    def insert(lap: LapTrace) -> Callable[[sqlite3.Connection], int]:
        return lambda c: repo.insert_lap(c, sid, lap, None)

    return [writer.call(insert(lap)) for lap in laps]


def lap_ctx(info: SessionInfo) -> dict[str, Any]:
    return {
        "game": info.game.value,
        "track_id": info.track_id,
        "track_name": info.track_name,
        "track_length_m": info.track_length_m,
        "car_id": info.car_id,
        "weather": info.weather.condition,
        "track_temp_c": info.weather.track_temp_c,
        "assists": dict(info.assists),
        "setup_fp": None,
    }


def teach_track_model(writer: DbWriter, db: Database, driver_id: int, session: DecodedSession) -> str:
    """James's laps build the shared track model, so session analyses run in full (and are cached)."""
    proc = LapProcessor(db, writer)
    sid = new_session(writer, driver_id, session.info, "s-model")
    for lap in session.laps:
        proc.process(LapJob(sid, copy_lap(lap), lap_ctx(session.info)))
    return sid


def session_driver(db: Database, sid: str) -> int | None:
    with db.read() as c:
        return repo.session_driver_id(c, sid)


# ---------------------------------------------------------------------------------------------- migration
def test_fresh_database_gets_default_driver_active(svc: DriverService, store: tuple[Database, DbWriter]) -> None:
    db, _ = store
    drivers = svc.list_drivers()
    assert [d.name for d in drivers] == [DEFAULT_DRIVER_NAME]
    james = drivers[0]
    assert james.preferences.skill_level == "intermediate"  # a fresh install starts in the middle (decision 5)
    assert james.preferences.coaching_intensity == "normal"
    assert james.preferences.initials == "D"
    assert svc.active_id == james.id == svc.default_id
    with db.read() as c:
        assert repo.get_meta(c, "schema_version") == str(SCHEMA_VERSION)
        assert repo.get_meta(c, repo.ACTIVE_DRIVER_KEY) == str(james.id)


def test_v1_database_migrates_idempotently(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    make_v1_db(path)
    for _run in range(3):  # every start re-runs the migration; only the first may change anything
        db = Database(path)
        writer = DbWriter(db)
        svc = DriverService(db, writer)
        writer.close()
        with db.read() as c:
            drivers = repo.list_drivers(c)
            assert [d["name"] for d in drivers] == [DEFAULT_DRIVER_NAME]
            james = int(drivers[0]["id"])
            rows = c.execute("SELECT id, driver_id FROM sessions ORDER BY id").fetchall()
            assert [(r["id"], r["driver_id"]) for r in rows] == [(f"legacy{i}", james) for i in range(3)]
            ref = c.execute("SELECT driver_id, active FROM reference_laps").fetchone()
            assert (ref["driver_id"], ref["active"]) == (james, 1)  # legacy pin kept, now James's
            assert repo.get_meta(c, "schema_version") == str(SCHEMA_VERSION)
            idx = {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'")}
            assert {"ix_sessions_driver", "ix_reference_lookup", "ix_laps_session_clean"} <= idx
            assert repo.pinned_reference(c, "f1_25", "f1:10", "f1:team:8", driver_id=james) == 1
        assert svc.active_id == james


def test_deleting_the_default_driver_moves_the_default(svc: DriverService, store: tuple[Database, DbWriter]) -> None:
    db, writer = store
    sam = svc.create("Sam").id
    svc.delete(svc.default_id)
    assert svc.default_id == sam and svc.active_id == sam
    writer.call(lambda c: c.execute("INSERT INTO sessions(id, game, started_unix, source) VALUES('old','f1_25',1,'x')"))
    DriverService(db, writer)  # restart: no default driver is re-created, NULL sessions go to the new default
    with db.read() as c:
        assert [d["name"] for d in repo.list_drivers(c)] == ["Sam"]
    assert session_driver(db, "old") == sam


def test_first_profile_is_generic_or_named_from_settings(tmp_path: Path) -> None:
    """A fresh install never names the first profile after anyone: "Driver", or settings.driver_name when set."""
    assert DEFAULT_DRIVER_NAME == "Driver"
    for i, (setting, expected) in enumerate(
        [(None, "Driver"), ("  Alex   Kim ", "Alex Kim"), ("", "Driver"), ("x" * 99, "Driver"), ("a\x07b", "Driver")]
    ):
        db = Database(tmp_path / f"fresh{i}.sqlite3")
        writer = DbWriter(db)
        try:
            svc = DriverService(db, writer, default_name=setting)  # a bad setting never stops start-up
            assert [d.name for d in svc.list_drivers()] == [expected] and svc.active_id == svc.default_id
        finally:
            writer.close()


def test_driver_name_setting_never_touches_an_existing_database(tmp_path: Path) -> None:
    db = Database(tmp_path / "pitwall.sqlite3")
    writer = DbWriter(db)
    try:
        first = DriverService(db, writer, default_name="Alex")
        sam = first.create("Sam", skill_level="beginner")
        before = [dataclasses.asdict(d) for d in first.list_drivers()]
        again = DriverService(db, writer, default_name="Someone Else")  # restart with another setting
        assert [dataclasses.asdict(d) for d in again.list_drivers()] == before
        assert [d.name for d in again.list_drivers()] == ["Alex", "Sam"] and again.default_id == first.default_id
        again.delete(again.default_id, reassign_to=sam.id)
        DriverService(db, writer, default_name="Alex")  # no driver called Alex any more: none is re-created
        assert [d.name for d in DriverService(db, writer).list_drivers()] == ["Sam"]
    finally:
        writer.close()


def test_runtime_names_the_first_profile_from_settings(tmp_path: Path) -> None:
    from pitwall.config import Settings
    from pitwall.core.runtime import Runtime

    rt = Runtime(Settings(_env_file=None, data_dir=tmp_path / "data", llm_enabled=False, driver_name="Alex"))  # type: ignore[call-arg]
    try:
        assert [d.name for d in rt.drivers.list_drivers()] == ["Alex"]
    finally:
        rt.close()


def test_concurrent_openers_migrate_once(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    make_v1_db(path)
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
        cols = [r[1] for r in c.execute("PRAGMA table_info(reference_laps)")]
    assert cols.count("driver_id") == 1 and cols[-1] == "driver_id"


def test_null_sessions_from_an_older_build_go_to_the_default_driver(store: tuple[Database, DbWriter]) -> None:
    db, writer = store
    svc = DriverService(db, writer)
    sam = svc.create("Sam", skill_level="beginner")
    svc.set_active(sam.id)
    # a row written by a build without profile support (no driver resolution in the INSERT)
    writer.call(lambda c: c.execute("INSERT INTO sessions(id, game, started_unix, source) VALUES('old','f1_25',1,'x')"))
    DriverService(db, writer)  # next start
    assert session_driver(db, "old") == svc.default_id  # the owner's, not whoever is active now
    assert DriverService(db, writer).active_id == sam.id  # active driver survives restarts


# ---------------------------------------------------------------------------------------------- service rules
def test_create_validates_and_picks_distinct_colours(svc: DriverService) -> None:
    sam = svc.create("  Sam   Racer ", skill_level="Beginner")
    assert sam.name == "Sam Racer" and sam.preferences.initials == "SR"
    assert sam.preferences.skill_level == "beginner"
    assert sam.preferences.colour != PALETTE[0]  # James already has the first palette colour
    kate = svc.create("Kate", colour="#AABBCC", initials="kt", coaching_intensity="detailed", voice_enabled=False)
    assert kate.preferences.colour == "#aabbcc" and kate.preferences.initials == "KT"
    assert kate.preferences.voice_enabled is False
    with pytest.raises(DriverConflictError):
        svc.create("sam racer")  # names are unique case-insensitively
    bads: list[dict[str, Any]] = [
        {"colour": "red"},
        {"initials": "ABCD"},
        {"skill_level": "pro"},
        {"coaching_intensity": "loud"},
    ]
    for bad in bads:
        with pytest.raises(DriverValidationError):
            svc.create("Other", **bad)
    for bad_name in ("", "   ", "x" * 41, "bad\x00name"):
        with pytest.raises(DriverValidationError):
            svc.create(bad_name)


def test_the_first_run_level_never_touches_an_existing_profile(store: tuple[Database, DbWriter]) -> None:
    """Decision 5: only a fresh install's first profile starts at intermediate. A database that already has a
    driver (an older install's "advanced" one) keeps it as it is on every later start, and gets no second profile."""
    first = DriverService(*store)
    james = first.active
    assert james is not None and james.preferences.skill_level == "intermediate"
    first.update(james.id, skill_level="advanced")  # as a 0.1.0 install created it
    again = DriverService(*store)
    assert [(d.id, d.preferences.skill_level) for d in again.list_drivers()] == [(james.id, "advanced")]
    assert again.default_id == james.id


def test_update_is_partial_and_refreshes_the_active_cache(svc: DriverService) -> None:
    seen: list[str | None] = []
    svc.subscribe(lambda d: seen.append(None if d is None else d.preferences.coaching_intensity))
    james = svc.active
    assert james is not None
    updated = svc.update(james.id, coaching_intensity="quiet")
    assert updated.preferences.coaching_intensity == "quiet"
    assert updated.preferences.skill_level == "intermediate" and updated.name == DEFAULT_DRIVER_NAME  # untouched
    assert svc.active is not None and svc.active.preferences.coaching_intensity == "quiet"
    assert seen == ["quiet"]  # listeners (the radio) hear about the active driver's change
    svc.create("Sam")
    with pytest.raises(DriverConflictError):
        svc.update(james.id, name="SAM")
    with pytest.raises(NotFoundError):
        svc.update(999, name="Nobody")
    assert (
        svc.update(james.id, name=DEFAULT_DRIVER_NAME).name == DEFAULT_DRIVER_NAME
    )  # renaming to your own name is fine


def test_stored_preferences_are_parsed_leniently() -> None:
    p = DriverPreferences.from_stored(
        {"colour": "not-a-colour", "skill_level": "beginner", "voice_enabled": "yes", "unknown": 1}, "Sam Racer"
    )
    assert p == DriverPreferences(colour=PALETTE[0], initials="SR", skill_level="beginner")
    assert default_initials("  ") == "?" and default_initials("james") == "J"


def test_active_driver_persists_and_versions_bump(svc: DriverService, store: tuple[Database, DbWriter]) -> None:
    sam = svc.create("Sam")
    v0 = svc.version
    assert svc.set_active(sam.id).id == sam.id
    assert svc.version == v0 + 1 and svc.active_id == sam.id
    svc.set_active(sam.id)  # idempotent: no version bump, no spurious session split
    assert svc.version == v0 + 1
    with pytest.raises(NotFoundError):
        svc.set_active(12345)
    assert svc.active_id == sam.id
    assert DriverService(*store).active_id == sam.id


def test_delete_rules(svc: DriverService, store: tuple[Database, DbWriter], clean_session: DecodedSession) -> None:
    db, writer = store
    james = svc.default_id
    sam = svc.create("Sam").id
    kate = svc.create("Kate").id
    sid = new_session(writer, sam, clean_session.info, "s-sam")
    (lap_id,) = add_laps(writer, sid, [copy_lap(clean_session.laps[0])])
    writer.call(lambda c: repo.pin_reference(c, lap_id))
    with pytest.raises(DriverConflictError, match="reassign_to"):
        svc.delete(sam)
    with pytest.raises(NotFoundError):
        svc.delete(sam, reassign_to=999)
    with pytest.raises(DriverValidationError):
        svc.delete(sam, reassign_to=sam)
    svc.set_active(sam)
    assert svc.delete(sam, reassign_to=kate) == 1
    assert session_driver(db, sid) == kate
    assert svc.active_id == kate  # the seat goes to whoever received the sessions
    assert svc.session_owner(sid, sam) == kate  # a live session tagged for Sam follows the move
    with db.read() as c:
        ref = c.execute("SELECT driver_id, active FROM reference_laps").fetchone()
        assert (ref["driver_id"], ref["active"]) == (kate, 0)  # moved but never overrides Kate's own pin
    assert svc.delete(kate, reassign_to=james) == 1
    temp = svc.create("Temp").id
    svc.set_active(temp)
    assert svc.delete(temp) == 0  # no sessions: no reassignment needed ...
    assert svc.active_id == james  # ... and the seat goes back to the default driver
    with pytest.raises(DriverConflictError, match="only driver"):
        svc.delete(james)
    with pytest.raises(NotFoundError):
        svc.delete(sam)


# ---------------------------------------------------------------------------------------------- isolation
def test_repo_queries_are_driver_scoped(
    svc: DriverService, store: tuple[Database, DbWriter], clean_session: DecodedSession
) -> None:
    db, writer = store
    info, base = clean_session.info, clean_session.laps[0]
    james, sam = svc.default_id, svc.create("Sam").id
    sj = new_session(writer, james, info, "s-james")
    ss = new_session(writer, sam, info, "s-sam")
    j_ids = add_laps(writer, sj, [copy_lap(base, 60_000, 1), copy_lap(base, 61_000, 2)])
    s_ids = add_laps(writer, ss, [copy_lap(base, 70_000, 1), copy_lap(base, 69_000, 2)])
    game, track, car = info.game.value, info.track_id, info.car_id
    assert track is not None
    with db.read() as c:
        assert [r["id"] for r in repo.clean_laps_for(c, game, track, car, driver_id=sam)] == [s_ids[1], s_ids[0]]
        assert [r["id"] for r in repo.clean_laps_for(c, game, track, car)][:2] == j_ids  # unscoped = legacy
        pb = repo.personal_best(c, sam, game, track, car)
        assert pb is not None and pb["id"] == s_ids[1] and pb["lap_time_ms"] == 69_000
        assert repo.personal_best(c, james, game, track, "other-car") is None
        stats = repo.driver_stats(c)
        assert stats[sam]["sessions"] == 1 and stats[sam]["laps"] == 2 and stats[sam]["tracks"] == 1
        assert [b["lap_time_ms"] for b in stats[sam]["best_laps"]] == [69_000]
        assert [b["lap_id"] for b in stats[james]["best_laps"]] == [j_ids[0]]
        assert [s["id"] for s in repo.list_sessions(c, driver_id=sam)] == [ss]
        assert {s["driver_name"] for s in repo.list_sessions(c)} == {DEFAULT_DRIVER_NAME, "Sam"}
    writer.call(lambda c: repo.pin_reference(c, j_ids[1]))  # James pins his slower lap
    with db.read() as c:
        assert repo.pinned_reference(c, game, track, car, driver_id=james) == j_ids[1]
        assert repo.pinned_reference(c, game, track, car, driver_id=sam) is None  # never James's pin
    writer.call(lambda c: repo.pin_reference(c, s_ids[0]))
    with db.read() as c:  # Sam's pin does not replace James's
        assert repo.pinned_reference(c, game, track, car, driver_id=james) == j_ids[1]
        assert repo.pinned_reference(c, game, track, car, driver_id=sam) == s_ids[0]


def test_lap_processor_never_uses_another_drivers_lap(
    svc: DriverService, store: tuple[Database, DbWriter], clean_session: DecodedSession
) -> None:
    db, writer = store
    info, laps = clean_session.info, clean_session.laps
    live = LiveState()
    proc = LapProcessor(db, writer, live)
    james, sam = svc.default_id, svc.create("Sam", skill_level="beginner").id
    ctx = lap_ctx(info)
    sj = new_session(writer, james, info, "s-james")
    for lap in laps:  # James sets the pace and teaches the shared track model
        proc.process(LapJob(sj, copy_lap(lap), ctx))
    ss = new_session(writer, sam, info, "s-sam")
    live.reset_session(ss, "test", False)  # what SessionManager does when a session starts
    first = proc.process(LapJob(ss, copy_lap(laps[0], 70_000), ctx))
    assert first["comparison"] is None  # Sam has no clean lap yet: no reference, James's laps are off limits
    assert live.reference is None
    second = proc.process(LapJob(ss, copy_lap(laps[1], 69_500), ctx))
    assert second["comparison"] is not None
    assert second["comparison"]["ref_lap_id"] == first["lap_id"]  # Sam's own lap
    assert live.reference is not None and live.reference["session_id"] == ss
    with db.read() as c:
        model = repo.load_track_model(c, info.game.value, str(info.track_id))
    assert model is not None and model.n_laps >= 3  # shared model, built from James's laps

    # Sam's session was really James driving: re-assign it; the next lap compares against James's best
    svc.assign_session(ss, james)
    third = proc.process(LapJob(ss, copy_lap(laps[2], 69_000), ctx))
    with db.read() as c:
        james_ids = {r["id"] for r in repo.clean_laps_for(c, info.game.value, str(info.track_id), info.car_id, 50)}
    assert third["comparison"]["ref_lap_id"] in james_ids
    with db.read() as c:
        ref_session = repo.get_lap(c, third["comparison"]["ref_lap_id"], with_trace=False)
    assert ref_session is not None and session_driver(db, ref_session["session_id"]) == james


def test_session_analysis_and_facts_are_driver_scoped(
    svc: DriverService, store: tuple[Database, DbWriter], clean_session: DecodedSession
) -> None:
    db, writer = store
    info, base = clean_session.info, clean_session.laps[0]
    james, sam = svc.default_id, svc.create("Sam", skill_level="beginner").id
    proc = LapProcessor(db, writer)
    sm = new_session(writer, james, info, "s-model")
    for lap in clean_session.laps:  # James's laps build the shared track model (so analyses are cached)
        proc.process(LapJob(sm, copy_lap(lap), lap_ctx(info)))
    sj = new_session(writer, james, info, "s-james")
    ss_old = new_session(writer, sam, info, "s-sam-old")
    ss = new_session(writer, sam, info, "s-sam")
    j_ids = add_laps(writer, sj, [copy_lap(base, 60_000, 1)])
    old_ids = add_laps(writer, ss_old, [copy_lap(base, 68_000, 1)])
    add_laps(writer, ss, [copy_lap(base, 70_000, 1), copy_lap(base, 69_000, 2)])
    analyzer = SessionAnalyzer(db)
    sa = analyzer.analyse(ss)
    assert sa is not None and sa.model is not None and sa.comparisons
    assert sa.ref_lap_id == old_ids[0]  # Sam's best, not James's faster laps
    assert sa.driver is not None and sa.driver["name"] == "Sam" and sa.driver["skill_level"] == "beginner"
    assert sa.personal_best is not None and sa.personal_best["id"] == old_ids[0]
    texts = [f.text for f in build_fact_sheet(sa).facts]
    assert "Driver: Sam (beginner level)." in texts[0]
    assert any("Sam's personal best" in t and "1:08.000" in t and "1.000s off it" in t for t in texts)
    assert any(t.startswith("Reference lap for comparisons: Sam's own lap 1") for t in texts)

    # re-assign James's session to Sam: Sam's other sessions now reference that lap once caches are invalidated
    svc.assign_session(sj, sam)
    assert analyzer.analyse(ss) is sa  # cached: the key (session, laps, ref, owner) did not change ...
    analyzer.invalidate(ss_old)
    assert analyzer.analyse(ss) is sa  # ... and invalidating another session leaves it alone
    analyzer.invalidate()  # what the API does after any change of session ownership
    fresh = analyzer.analyse(ss)
    assert fresh is not None and fresh.ref_lap_id == j_ids[0]


def test_unowned_session_keeps_legacy_facts(store: tuple[Database, DbWriter], clean_session: DecodedSession) -> None:
    db, writer = store  # no DriverService: no drivers exist, so the session cannot be tagged
    sid = new_session(writer, None, clean_session.info, "s-anon")
    add_laps(writer, sid, [copy_lap(clean_session.laps[0])])
    assert session_driver(db, sid) is None
    sa = SessionAnalyzer(db).analyse(sid)
    assert sa is not None and sa.driver is None and sa.personal_best is None
    texts = [f.text for f in build_fact_sheet(sa).facts]
    assert "Driver:" not in texts[0] and not any("personal best" in t for t in texts)


def test_reassignment_deactivates_pins_on_the_session(
    svc: DriverService, store: tuple[Database, DbWriter], clean_session: DecodedSession
) -> None:
    db, writer = store
    james, sam = svc.default_id, svc.create("Sam").id
    sid = new_session(writer, james, clean_session.info, "s1")
    (lap_id,) = add_laps(writer, sid, [copy_lap(clean_session.laps[0])])
    writer.call(lambda c: repo.pin_reference(c, lap_id))
    v = svc.version
    res = svc.assign_session(sid, sam)
    assert res.previous_driver_id == james and res.changed and not res.active_changed
    assert svc.version == v + 1 and svc.session_owner(sid, james) == sam
    again = svc.assign_session(sid, sam)
    assert again.previous_driver_id == sam and not again.changed and svc.version == v + 1  # no-op re-assignment
    info = clean_session.info
    with db.read() as c:
        for d in (james, sam):
            assert repo.pinned_reference(c, info.game.value, str(info.track_id), info.car_id, driver_id=d) is None
    with pytest.raises(NotFoundError):
        svc.assign_session("missing", sam)
    with pytest.raises(NotFoundError):
        svc.assign_session(sid, 999)


# ---------------------------------------------------------------------------------------------- live tagging
class _Jobs:
    def __init__(self) -> None:
        self.jobs: list[LapJob] = []

    def submit(self, job: LapJob) -> None:
        self.jobs.append(job)


def _manager(store: tuple[Database, DbWriter], drivers: DriverService | None) -> tuple[SessionManager, _Jobs]:
    jobs = _Jobs()
    sm = SessionManager(store[1], LiveState(), cast(AnalysisWorker, jobs), source="test", drivers=drivers)
    return sm, jobs


def _feed(
    sm: SessionManager, adapter: F1Adapter, packets: list[CapturedPacket], until: Callable[[], bool] | None = None
) -> int:
    for i, p in enumerate(packets):
        for e in adapter.decode(p.data, p.t_recv_ns):
            sm.handle(e)
        if until is not None and until():
            return i + 1
    return len(packets)


def _sessions(db: Database) -> list[dict[str, Any]]:
    with db.read() as c:
        return [dict(r) for r in c.execute("SELECT id, driver_id, track_id FROM sessions ORDER BY rowid")]


def test_sessions_are_tagged_with_the_active_driver(
    svc: DriverService, store: tuple[Database, DbWriter], clean_session: DecodedSession
) -> None:
    db, writer = store
    sam = svc.create("Sam").id
    svc.set_active(sam)
    sm, jobs = _manager(store, svc)
    _feed(sm, F1Adapter(), clean_session.packets)
    sm.end()
    writer.flush()
    assert [(s["driver_id"]) for s in _sessions(db)] == [sam]
    assert sm.driver_splits == 0 and len(jobs.jobs) == 3


def test_switch_before_first_lap_retags_the_session(
    svc: DriverService, store: tuple[Database, DbWriter], clean_session: DecodedSession
) -> None:
    db, writer = store
    sam = svc.create("Sam").id
    sm, jobs = _manager(store, svc)
    adapter, packets = F1Adapter(), clean_session.packets
    n = _feed(sm, adapter, packets, until=lambda: sm.session_id is not None)
    n += _feed(sm, adapter, packets[n : n + 500])
    assert not jobs.jobs and sm.driver_id == svc.default_id
    svc.set_active(sam)
    _feed(sm, adapter, packets[n:])
    sm.end()
    writer.flush()
    (only,) = _sessions(db)
    assert only["driver_id"] == sam and sm.sessions_started == 1 and sm.driver_splits == 0
    assert {j.session_id for j in jobs.jobs} == {only["id"]}


def test_switch_mid_session_splits_so_no_lap_is_misattributed(
    svc: DriverService, store: tuple[Database, DbWriter], clean_session: DecodedSession
) -> None:
    db, writer = store
    james, sam = svc.default_id, svc.create("Sam").id
    sm, jobs = _manager(store, svc)
    adapter, packets = F1Adapter(), clean_session.packets
    n = _feed(sm, adapter, packets, until=lambda: len(jobs.jobs) == 1)  # James completes lap 1 ...
    n += _feed(sm, adapter, packets[n : n + len(packets) // 6])  # ... and is half way round lap 2
    first_sid = sm.session_id
    assert first_sid is not None
    sm.live.set_track_model({"track_id": "shared"})
    sm.live.set_reference({"lap_id": 1, "session_id": first_sid}, None)
    svc.set_active(sam)
    _feed(sm, adapter, packets[n : n + 10])
    assert sm.session_id != first_sid and sm.live.session_id == sm.session_id
    assert sm.live.track_model == {"track_id": "shared"} and sm.live.reference is None  # James's ref is gone
    _feed(sm, adapter, packets[n + 10 :])
    sm.end()
    writer.flush()
    sessions = _sessions(db)
    assert [s["driver_id"] for s in sessions] == [james, sam] and sm.driver_splits == 1
    second_sid = sessions[1]["id"]
    assert sessions[0]["id"] == first_sid and sessions[1]["track_id"] == sessions[0]["track_id"]  # context kept
    by_session: dict[str, list[LapJob]] = {}
    for j in jobs.jobs:
        by_session.setdefault(j.session_id, []).append(j)
    assert [j.lap.lap_number for j in by_session[first_sid] if j.lap.clean] == [1]
    assert not any(j.lap.clean for j in by_session[first_sid][1:])  # the lap in progress is not attributed
    assert [j.lap.lap_number for j in by_session[second_sid] if j.lap.clean] == [3]
    assert all(j.context["track_length_m"] for j in by_session[second_sid])
    with db.read() as c:
        assert len(repo.setup_history(c, second_sid)) == 1  # setup carried over (the game only re-sends changes)


class _SteppingWriter:
    """Runs one ingest step after every writer round trip of the service: the ingest thread handles a packet every
    few milliseconds, so it must be assumed to observe every intermediate state an API call goes through."""

    def __init__(self, writer: DbWriter, step: Callable[[], None]) -> None:
        self.writer, self.step = writer, step

    def call(self, fn: Callable[[sqlite3.Connection], T], timeout: float = 30.0) -> T:
        out = self.writer.call(fn, timeout)
        self.step()
        return out


def _step_after_every_state_change(
    svc: DriverService, monkeypatch: pytest.MonkeyPatch, step: Callable[[], None]
) -> None:
    publish = svc._publish

    def publish_then_step(**changes: Any) -> SeatState:
        seat = publish(**changes)
        step()
        return seat

    monkeypatch.setattr(svc, "_publish", publish_then_step)
    monkeypatch.setattr(svc, "writer", _SteppingWriter(svc.writer, step))


@pytest.mark.parametrize("laps_done", [0, 1])
def test_reassigning_the_live_session_is_atomic_for_ingest(
    svc: DriverService,
    store: tuple[Database, DbWriter],
    clean_session: DecodedSession,
    monkeypatch: pytest.MonkeyPatch,
    laps_done: int,
) -> None:
    """Regression: assign + activate as two calls let ingest see "owner Sam, James seated" in between and hand
    the session back to James (0 laps: the DB ended up James's while everything else said Sam) or split it."""
    db, writer = store
    sam = svc.create("Sam").id
    sm, jobs = _manager(store, svc)
    adapter, packets = F1Adapter(), clean_session.packets
    if laps_done:
        n = _feed(sm, adapter, packets, until=lambda: len(jobs.jobs) == laps_done)
    else:
        n = _feed(sm, adapter, packets, until=lambda: sm.session_id is not None)
        n += _feed(sm, adapter, packets[n : n + 300])
        assert not jobs.jobs
    sid = sm.session_id
    assert sid is not None
    it = iter(packets[n:])

    def step() -> None:  # packets through the ingest path until at least one item was handled
        handled = 0
        while not handled:
            p = next(it)
            for e in adapter.decode(p.data, p.t_recv_ns):
                sm.handle(e)
                handled += 1

    retags: list[tuple[str, int]] = []
    set_session_driver = repo.set_session_driver

    def spy(c: sqlite3.Connection, session_id: str, driver_id: int) -> int | None:
        retags.append((session_id, driver_id))
        return set_session_driver(c, session_id, driver_id)

    monkeypatch.setattr(repo, "set_session_driver", spy)
    _step_after_every_state_change(svc, monkeypatch, step)
    res = svc.assign_session(sid, sam, activate=True)  # "that was Sam driving": what the API does when live
    assert retags == [(sid, sam)]  # the manager never handed the session back, not even transiently
    assert res.active_changed and res.previous_driver_id == svc.default_id
    for p in it:
        for e in adapter.decode(p.data, p.t_recv_ns):
            sm.handle(e)
    sm.end()
    writer.flush()
    assert [(s["id"], s["driver_id"]) for s in _sessions(db)] == [(sid, sam)]
    assert sm.driver_id == sam and svc.active_id == sam
    assert sm.driver_splits == 0 and len(jobs.jobs) == 3 and {j.session_id for j in jobs.jobs} == {sid}


def test_live_session_follows_the_seat_unless_the_assignment_activates(
    svc: DriverService, store: tuple[Database, DbWriter], clean_session: DecodedSession
) -> None:
    """The invariant ``activate`` exists for: the live session belongs to whoever is seated, so assigning it
    without seating that driver is undone by the very next packet (this is what the two-call API used to do)."""
    db, writer = store
    sam = svc.create("Sam").id
    sm, _ = _manager(store, svc)
    adapter, packets = F1Adapter(), clean_session.packets
    n = _feed(sm, adapter, packets, until=lambda: sm.session_id is not None)
    sid = sm.session_id
    assert sid is not None
    svc.assign_session(sid, sam)  # not activated: Sam owns the live session while James is still seated
    _feed(sm, adapter, packets[n : n + 1])
    writer.flush()
    assert session_driver(db, sid) == svc.default_id  # the manager handed the 0-lap session straight back


def test_stale_reassignment_never_overrides_the_managers_own_retag(
    svc: DriverService, store: tuple[Database, DbWriter], clean_session: DecodedSession
) -> None:
    """Live S (0 laps) assigned to Sam via the API; the chip goes to Kate before the first lap (the manager
    re-tags S itself); Kate drives; the chip goes back to Sam. Sam's old tag must not hide that Kate owns S now."""
    db, writer = store
    sam, kate = svc.create("Sam").id, svc.create("Kate").id
    sm, jobs = _manager(store, svc)
    adapter, packets = F1Adapter(), clean_session.packets
    n = _feed(sm, adapter, packets, until=lambda: sm.session_id is not None)
    n += _feed(sm, adapter, packets[n : n + 300])
    sid = sm.session_id
    assert sid is not None
    svc.assign_session(sid, sam, activate=True)
    n += _feed(sm, adapter, packets[n : n + 10])
    svc.set_active(kate)
    n += _feed(sm, adapter, packets[n:], until=lambda: len(jobs.jobs) == 1)  # Kate completes a lap in S
    assert sm.driver_id == kate and session_driver(db, sid) == kate
    svc.set_active(sam)
    _feed(sm, adapter, packets[n:])
    sm.end()
    writer.flush()
    sessions = _sessions(db)
    assert [s["driver_id"] for s in sessions] == [kate, sam] and sessions[0]["id"] == sid
    assert sm.driver_splits == 1
    assert [j.lap.lap_number for j in jobs.jobs if j.session_id == sid and j.lap.clean] == [1]


def test_seat_state_owner_resolution() -> None:
    seat = SeatState(version=7, active_id=2, tags={"s": (2, 5)}, redirects={3: 4})
    assert seat.owner("s", 1) == 2  # the caller knew nothing: the re-assignment wins
    assert seat.owner("s", 1, known_version=4) == 2  # published after what the caller knew
    assert seat.owner("s", 1, known_version=5) == 1  # already taken into account: the caller's own view stands
    assert seat.owner("other", 3, known_version=7) == 4  # deleted owner -> the driver their sessions moved to
    assert seat.owner("other", None) is None


def test_without_a_driver_source_sessions_use_the_persisted_active_driver(
    svc: DriverService, store: tuple[Database, DbWriter], clean_session: DecodedSession
) -> None:
    db, writer = store
    sam = svc.create("Sam").id
    svc.set_active(sam)
    sm, _ = _manager(store, None)  # e.g. a headless replay tool that has no DriverService
    _feed(sm, F1Adapter(), clean_session.packets[:2000])
    sm.end()
    writer.flush()
    assert [s["driver_id"] for s in _sessions(db)] == [sam]
    # a stale explicit id (driver deleted meanwhile) falls back instead of failing the insert and losing the session
    writer.call(lambda c: repo.insert_session(c, "stale", "f1_25", "t", False, None, None, driver_id=999))
    assert session_driver(db, "stale") == sam


# ---------------------------------------------------------------------------------------------- coaching limits
def test_default_profile_reproduces_pre_profile_radio() -> None:
    from pitwall.analysis.coaching import MIN_TIME_LOSS_S
    from pitwall.voice.proactive import CORRECTIVE_PER_LAP, MIN_COACHING_CONFIDENCE, POSITIVE_PER_LAP

    for intensity in ("quiet", "normal", "detailed"):
        lim = coaching_limits("advanced", intensity)
        assert lim.min_confidence == MIN_COACHING_CONFIDENCE and lim.min_impact_s == MIN_TIME_LOSS_S
        assert lim.max_corrective_per_lap == CORRECTIVE_PER_LAP[intensity]
        assert lim.max_positive_per_lap == POSITIVE_PER_LAP[intensity]
        assert lim.allowed_kinds is None and not lim.simple_wording


def test_skill_levels_are_ordered_and_beginners_get_one_point_a_lap() -> None:
    b, i, a = (coaching_limits(s) for s in ("beginner", "intermediate", "advanced"))
    assert b.min_confidence > i.min_confidence > a.min_confidence
    assert b.min_impact_s > i.min_impact_s > a.min_impact_s
    for intensity in ("normal", "detailed"):
        beginner = coaching_limits("beginner", intensity)
        assert beginner.max_per_lap == 1 and beginner.simple_wording and not beginner.mention_consistency
        assert beginner.allowed_kinds == BEGINNER_KINDS and "coasting" not in BEGINNER_KINDS
    for skill in ("beginner", "intermediate", "advanced"):
        quiet = coaching_limits(skill, "quiet")
        assert quiet.max_per_lap == quiet.max_corrective_per_lap == quiet.max_positive_per_lap == 0
    assert coaching_limits(" Advanced ", "DETAILED").to_dict()["allowed_kinds"] is None
    assert coaching_limits("beginner").to_dict()["allowed_kinds"] == sorted(BEGINNER_KINDS)
    with pytest.raises(DriverValidationError):
        coaching_limits("pro")
    with pytest.raises(DriverValidationError):
        coaching_limits("advanced", "loud")


def _obs(
    oid: str, kind: str, corner: str, conf: float | None, impact: float | None, prio: float, positive: bool = False
) -> dict[str, Any]:
    return {
        "id": oid,
        "kind": kind,
        "corner": corner,
        "lap_number": 5,
        "confidence": conf,
        "impact_s": impact,
        "priority": prio,
        "positive": positive,
    }


def test_apply_coaching_limits_filters_and_budgets() -> None:
    obs = [
        _obs("a", "brake_early", "T1", 0.9, 0.20, 0.18),
        _obs("b", "coasting", "T2", 0.95, 0.30, 0.28),  # beginners: not a fundamentals rule
        _obs("c", "low_min_speed", "T3", 0.7, 0.25, 0.30),  # below the beginner confidence floor
        _obs("d", "late_throttle", "T4", 0.9, 0.06, 0.05),  # below the beginner impact floor
        _obs("e", "exit_gain", "T5", 0.9, -0.15, 0.07, positive=True),
        _obs("f", "brake_early", "T6", None, 0.4, 0.5),  # unknown confidence: never spoken
        {**_obs("g", "brake_early", "T7", 0.99, 0.9, 0.9), "lap_number": 4},  # another lap
    ]
    beginner = coaching_limits("beginner")
    assert [o["id"] for o in apply_coaching_limits(obs, beginner, lap_number=5)] == ["a"]
    # nothing corrective left -> the beginner hears the praise instead
    assert [o["id"] for o in apply_coaching_limits([obs[4]], beginner, lap_number=5)] == ["e"]
    # T1 was coached last lap: give the driver a lap to try it
    assert [o["id"] for o in apply_coaching_limits(obs, beginner, 5, {"T1": 4})] == ["e"]
    assert [o["id"] for o in apply_coaching_limits(obs, beginner, 5, {"T1": 3})] == ["a"]
    advanced_detailed = coaching_limits("advanced", "detailed")
    assert [o["id"] for o in apply_coaching_limits(obs, advanced_detailed, lap_number=5)] == ["c", "b", "e"]
    assert [o["id"] for o in apply_coaching_limits(obs, coaching_limits("advanced"), lap_number=5)] == ["c"]
    assert apply_coaching_limits(obs, coaching_limits("advanced", "quiet"), lap_number=5) == []
    tie = [_obs("z", "brake_early", "T1", 0.9, 0.2, 0.1), _obs("y", "brake_early", "T2", 0.9, 0.2, 0.1)]
    assert [o["id"] for o in apply_coaching_limits(tie, coaching_limits("advanced"))] == ["y"]  # deterministic


def test_limits_for_and_to_dict(svc: DriverService) -> None:
    sam = svc.create("Sam", skill_level="beginner")
    active = svc.limits_for()
    assert isinstance(active, CoachingLimits) and active.skill_level == "intermediate"  # the fresh-install profile
    sam_limits = svc.limits_for(sam.id)
    assert sam_limits is not None and sam_limits.max_per_lap == 1
    assert svc.limits_for(999) is None
    d = sam.to_dict()
    assert d["coaching"]["skill_level"] == "beginner" and d["preferences"]["initials"] == "S"


# ---------------------------------------------------------------------------------------------- API
@pytest.fixture
def api(tmp_path: Path) -> Iterator[tuple[TestClient, SimpleNamespace]]:
    db = Database(tmp_path / "api.sqlite3")
    writer = DbWriter(db)
    rt = SimpleNamespace(db=db, writer=writer, live=LiveState(), drivers=DriverService(db, writer))
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = rt
    app.state.analyzer = SessionAnalyzer(db)
    with TestClient(app) as client:
        yield client, rt
    writer.close()


def test_api_crud_and_active(api: tuple[TestClient, SimpleNamespace]) -> None:
    client, rt = api
    body = client.get("/api/drivers").json()
    assert [d["name"] for d in body["drivers"]] == [DEFAULT_DRIVER_NAME] and body["active_id"] == body["drivers"][0][
        "id"
    ]
    james = body["drivers"][0]
    assert james["active"] is True and james["stats"]["sessions"] == 0 and james["coaching"]["max_per_lap"] == 1
    r = client.post("/api/drivers", json={"name": "Sam", "skill_level": "beginner", "colour": "#38bdf8"})
    assert r.status_code == 201
    sam = r.json()
    assert sam["preferences"] == {
        "colour": "#38bdf8",
        "initials": "S",
        "skill_level": "beginner",
        "coaching_intensity": "normal",
        "voice_enabled": True,
        "default_game": None,
        # race radio: every group on, the wording follows the skill level
        "radio_calls": {
            "flags": True,
            "start": True,
            "position": True,
            "rivals": True,
            "penalties": True,
            "damage": True,
            "name": True,
        },
        "radio_wording": "auto",
        "handsfree_while_driving": False,
    }
    assert client.post("/api/drivers", json={"name": "SAM"}).status_code == 409
    assert client.post("/api/drivers", json={"name": "X", "colour": "blue"}).status_code == 422
    assert client.post("/api/drivers", json={"name": "X", "skill_level": "pro"}).status_code == 422
    assert client.post("/api/drivers", json={"name": "X", "admin": True}).status_code == 422  # unknown field
    assert client.post("/api/drivers", json={"name": "   "}).status_code == 422  # service-side validation

    r = client.patch(f"/api/drivers/{sam['id']}", json={"coaching_intensity": "detailed", "initials": "sr"})
    assert r.status_code == 200
    assert r.json()["preferences"]["coaching_intensity"] == "detailed" and r.json()["preferences"]["initials"] == "SR"
    assert client.patch("/api/drivers/999", json={"name": "Nobody"}).status_code == 404
    assert client.get(f"/api/drivers/{sam['id']}").json()["name"] == "Sam"
    assert client.get("/api/drivers/999").status_code == 404

    assert client.get("/api/drivers/active").json()["id"] == james["id"]
    r = client.put("/api/drivers/active", json={"driver_id": sam["id"]})
    assert r.status_code == 200 and r.json()["active"] is True
    assert rt.drivers.active_id == sam["id"]
    assert client.put("/api/drivers/active", json={"driver_id": 999}).status_code == 404
    assert client.get("/api/drivers/active").json()["name"] == "Sam"


def test_api_delete_and_assign(api: tuple[TestClient, SimpleNamespace], clean_session: DecodedSession) -> None:
    client, rt = api
    james = rt.drivers.default_id
    sam = client.post("/api/drivers", json={"name": "Sam"}).json()["id"]
    sid = new_session(rt.writer, james, clean_session.info, "s1")
    add_laps(rt.writer, sid, [copy_lap(clean_session.laps[0])])

    r = client.post(f"/api/drivers/sessions/{sid}/assign", json={"driver_id": sam})
    assert r.status_code == 200
    assert r.json() == {
        "session_id": sid,
        "driver_id": sam,
        "previous_driver_id": james,
        "live": False,
        "active_changed": False,
    }
    assert rt.drivers.active_id == james  # a finished session does not change who is in the seat
    assert [s["id"] for s in client.get(f"/api/drivers/{sam}/sessions").json()] == [sid]
    assert client.get(f"/api/drivers/{james}/sessions").json() == []
    assert client.get("/api/drivers/999/sessions").status_code == 404
    assert client.post("/api/drivers/sessions/nope/assign", json={"driver_id": sam}).status_code == 404
    assert client.post(f"/api/drivers/sessions/{sid}/assign", json={"driver_id": 999}).status_code == 404

    rt.live.session_id = sid  # the session being driven right now
    r = client.post(f"/api/drivers/sessions/{sid}/assign", json={"driver_id": james})
    assert r.json()["live"] is True and r.json()["active_changed"] is False  # James already in the seat
    r = client.post(f"/api/drivers/sessions/{sid}/assign", json={"driver_id": sam})
    assert r.json()["active_changed"] is True and rt.drivers.active_id == sam

    rt.writer.call(lambda c: repo.end_session(c, sid, None))  # live state still shows it, but it has ended
    r = client.post(f"/api/drivers/sessions/{sid}/assign", json={"driver_id": james})
    assert r.json()["live"] is False and r.json()["active_changed"] is False and rt.drivers.active_id == sam
    assert client.post(f"/api/drivers/sessions/{sid}/assign", json={"driver_id": sam}).status_code == 200

    stats = {d["id"]: d["stats"] for d in client.get("/api/drivers").json()["drivers"]}
    assert stats[sam]["sessions"] == 1 and stats[sam]["laps"] == 1 and stats[james]["sessions"] == 0

    r = client.delete(f"/api/drivers/{sam}")
    assert r.status_code == 409 and "reassign_to" in r.json()["detail"]
    r = client.delete(f"/api/drivers/{sam}", params={"reassign_to": james})
    assert r.status_code == 200
    assert r.json() == {"deleted": sam, "reassigned_to": james, "sessions_moved": 1, "active_id": james}
    assert client.delete(f"/api/drivers/{james}").status_code == 409  # the last driver stays
    assert client.delete("/api/drivers/999").status_code == 404


def test_api_driver_sessions_are_the_same_rows_as_the_sessions_api(api: tuple[TestClient, SimpleNamespace]) -> None:
    """Review > Sessions reads this route when a driver filter is on: an F2 session must carry its class there too
    ("F2 · Hitech '25", "Sprint race"), never the raw "Race" / "Unknown team (id 214)"."""
    client, rt = api
    james = rt.drivers.default_id
    rt.writer.call(lambda c: repo.insert_session(c, "f2s", "f1_25", "udp:20777", False, None, None, driver_id=james))
    rt.writer.call(
        lambda c: c.execute(
            "UPDATE sessions SET car_id='f1:team:214', car_name='Unknown team (id 214)', session_type_raw='Race', "
            'info=\'{"formula": "F2", "packet_format": 2025, "weekend_structure": [15, 16]}\' WHERE id=\'f2s\''
        )
    )
    (row,) = client.get(f"/api/drivers/{james}/sessions").json()
    assert row["car_label"] == "F2 · Hitech '25" and row["session_label"] == "Sprint race"
    assert row["car_class"]["id"] == "f2" and row["car_class"]["has_ers"] is False
    assert "game_entry_id" in row


def test_api_creates_a_service_when_the_runtime_has_none(tmp_path: Path) -> None:
    db = Database(tmp_path / "lazy.sqlite3")
    writer = DbWriter(db)
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = SimpleNamespace(db=db, writer=writer, live=LiveState())
    with TestClient(app) as client:
        assert [d["name"] for d in client.get("/api/drivers").json()["drivers"]] == [DEFAULT_DRIVER_NAME]
        assert client.get("/api/drivers").json()["active_id"] is not None
        assert isinstance(app.state.drivers, DriverService)
    writer.close()


# ---------------------------------------------------------------------------------------------- menus / on track
def _button(t_ns: int) -> GameEvent:
    return GameEvent(kind=EventKind.BUTTON, game=Game.F1_25, t_recv_ns=t_ns, code="BUTN", payload={"buttonStatus": 0})


def test_switch_in_the_menus_ends_the_session_without_a_junk_one(
    svc: DriverService, store: tuple[Database, DbWriter], clean_session: DecodedSession
) -> None:
    """James quits to the menus (no frames, button events keep coming); Sam is seated. The next button event must
    not start a session in the menus carrying James's track and car: James's session just ends."""
    db, writer = store
    james, sam = svc.default_id, svc.create("Sam").id
    sm, jobs = _manager(store, svc)
    adapter, packets = F1Adapter(), clean_session.packets
    n = _feed(sm, adapter, packets, until=lambda: len(jobs.jobs) == 1)
    first = sm.session_id
    menu_t = packets[n - 1].t_recv_ns + 5_000_000_000  # 5 s after the last frame: in the menus
    sm.handle(_button(menu_t))
    assert sm.session_id == first  # nothing changed yet: buttons alone never end a session
    svc.set_active(sam)
    sm.handle(_button(menu_t + 1_000_000))
    sm.handle(_button(menu_t + 2_000_000))
    assert sm.session_id is None and sm.driver_splits == 0  # ended, and no session started in the menus
    writer.flush()
    assert [(s["id"], s["driver_id"]) for s in _sessions(db)] == [(first, james)]
    _feed(sm, adapter, packets[n:])  # Sam drives (here: the same game session, so the setup is carried)
    sm.end()
    writer.flush()
    sessions = _sessions(db)
    assert [s["driver_id"] for s in sessions] == [james, sam] and sm.driver_splits == 0
    second = sessions[1]["id"]
    assert sessions[1]["track_id"] == sessions[0]["track_id"]  # from Sam's own session packets, not carried
    with db.read() as c:
        assert len(repo.setup_history(c, second)) == 1  # the game does not re-send an unchanged setup
    assert all(j.session_id == second for j in jobs.jobs[1:] if j.lap.clean)


def test_switch_before_any_frame_hands_the_session_over(
    svc: DriverService, store: tuple[Database, DbWriter], clean_session: DecodedSession
) -> None:
    """A session that has only seen session packets (loading screen) is nobody's yet: re-tag, never end."""
    db, writer = store
    sam = svc.create("Sam").id
    sm, _ = _manager(store, svc)
    info = clean_session.info
    sm.handle(dataclasses.replace(info, t_recv_ns=1_000))
    sid = sm.session_id
    svc.set_active(sam)
    sm.handle(_button(60_000_000_000))  # a minute later, still no frame
    assert sm.session_id == sid and sm.driver_id == sam
    writer.flush()
    assert [(s["id"], s["driver_id"]) for s in _sessions(db)] == [(sid, sam)]


# ---------------------------------------------------------------------------------------------- live publishing
def test_results_of_a_previous_session_are_not_published_live(
    svc: DriverService, store: tuple[Database, DbWriter], clean_session: DecodedSession
) -> None:
    db, writer = store
    info, laps = clean_session.info, clean_session.laps
    live = LiveState()
    notes: list[str] = []
    live.subscribe(lambda kind, _payload: notes.append(kind))
    proc = LapProcessor(db, writer, live)
    james, sam = svc.default_id, svc.create("Sam").id
    ctx = lap_ctx(info)
    sj = new_session(writer, james, info, "s-james")
    live.reset_session(sj, "test", False)
    for lap in laps:
        proc.process(LapJob(sj, copy_lap(lap), ctx))
    assert notes.count("lap") == 3 and live.track_model is not None
    ss = new_session(writer, sam, info, "s-sam")
    live.reset_session(ss, "test", False)  # the driver change: Sam's session is live now
    sentinel = {"lap_id": -1, "session_id": ss}
    live.set_reference(sentinel, None)
    partial = copy_lap(laps[0], lap_number=4)
    partial.flags.add("incomplete")
    late = proc.process(LapJob(sj, partial, ctx))  # James's flushed partial lap, processed after the change
    complete = proc.process(LapJob(sj, copy_lap(laps[1], 59_000, 5), ctx))  # a lap still being analysed
    assert late["lap_id"] and complete["comparison"] is not None  # stored and analysed as usual ...
    assert list(live.laps) == [] and notes.count("lap") == 3  # ... but nothing reached Sam's live state / radio
    assert live.reference is sentinel and live.track_model is None
    proc.process(LapJob(ss, copy_lap(laps[0], 70_000), ctx))
    assert [lap["lap_number"] for lap in live.laps] == [1] and notes.count("lap") == 4


# ---------------------------------------------------------------------------------------------- replays
def test_replays_are_nobodys_driving(
    svc: DriverService, store: tuple[Database, DbWriter], clean_session: DecodedSession
) -> None:
    db, writer = store
    james, sam = svc.default_id, svc.create("Sam").id
    svc.set_active(sam)
    jobs = _Jobs()
    sm = SessionManager(writer, LiveState(), cast(AnalysisWorker, jobs), source="replay:james.pwcap", drivers=svc)
    adapter, packets = F1Adapter(), clean_session.packets
    n = _feed(sm, adapter, packets, until=lambda: len(jobs.jobs) == 1)
    svc.set_active(james)  # a seat change during a replay neither splits nor re-tags it
    _feed(sm, adapter, packets[n:])
    sm.end()
    headless = SessionManager(writer, LiveState(), cast(AnalysisWorker, _Jobs()), source="replay:x", drivers=None)
    _feed(headless, F1Adapter(), packets[:500])  # no driver source: no fallback to the seated driver either
    headless.end()
    writer.flush()
    sessions = _sessions(db)
    assert [s["driver_id"] for s in sessions] == [None, None] and sm.driver_splits == 0
    DriverService(db, writer)  # restart: the default-driver backfill leaves replays alone
    assert [s["driver_id"] for s in _sessions(db)] == [None, None]


def test_replays_never_count_toward_a_drivers_records(
    svc: DriverService, store: tuple[Database, DbWriter], clean_session: DecodedSession
) -> None:
    db, writer = store
    info, base = clean_session.info, clean_session.laps[0]
    sam = svc.create("Sam").id
    real = new_session(writer, sam, info, "s-real")
    add_laps(writer, real, [copy_lap(base, 70_000, 1)])

    def replay_job(c: sqlite3.Connection) -> None:  # e.g. a replay backfilled to a driver by an older build
        repo.insert_session(c, "s-replay", info.game.value, "replay:sam.pwcap", False, None, None, driver_id=sam)
        repo.update_session_info(c, "s-replay", info)

    writer.call(replay_job)
    add_laps(writer, "s-replay", [copy_lap(base, 60_000, 1), copy_lap(base, 61_000, 2)])
    game, track, car = info.game.value, str(info.track_id), info.car_id
    with db.read() as c:
        assert session_driver(db, "s-replay") == sam  # an explicit driver is kept ...
        pb = repo.personal_best(c, sam, game, track, car)
        assert pb is not None and pb["session_id"] == real  # ... but the replay's faster laps are not Sam's PB
        assert [r["session_id"] for r in repo.clean_laps_for(c, game, track, car, driver_id=sam)] == [real]
        assert repo.clean_laps_for(c, game, track, car)[0]["session_id"] == "s-replay"  # shared geometry: yes
        stats = repo.driver_stats(c)[sam]
        assert stats["sessions"] == 2  # ownership (what delete refuses on) counts every session ...
        assert stats["laps"] == stats["clean_laps"] == 1 and stats["tracks"] == 1  # ... driving does not
        assert [b["session_id"] for b in stats["best_laps"]] == [real]


# ---------------------------------------------------------------------------------------------- questions
def test_questions_are_about_the_seated_drivers_sessions(
    svc: DriverService, store: tuple[Database, DbWriter], clean_session: DecodedSession
) -> None:
    db, writer = store
    info = clean_session.info
    james, sam = svc.default_id, svc.create("Sam").id
    sj = new_session(writer, james, info, "s-james")
    assert svc.session_for_questions(sj) == sj  # James's (just ended) session, James seated
    assert svc.session_for_questions(None) == sj
    svc.set_active(sam)
    assert svc.session_for_questions(sj) is None  # Sam has no session yet: never answer with James's numbers
    ss = new_session(writer, sam, info, "s-sam")
    assert svc.session_for_questions(sj) == ss and svc.session_for_questions(None) == ss
    writer.call(lambda c: repo.insert_session(c, "s-replay", "f1_25", "replay:x", False, None, None))
    assert svc.session_for_questions("s-replay") == "s-replay"  # a replay being watched belongs to nobody
    with db.read() as c:
        assert repo.latest_session_id(c, driver_id=james) == sj
        assert repo.latest_session_id(c) == "s-replay"  # unfiltered: the pre-profile behaviour
        assert repo.latest_session_id(c, driver_id=999) is None


# ---------------------------------------------------------------------------------------------- analysis cache / facts
def test_profile_edits_reach_cached_analyses(
    svc: DriverService, store: tuple[Database, DbWriter], clean_session: DecodedSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, writer = store
    info, base = clean_session.info, clean_session.laps[0]
    sam = svc.create("Sam", skill_level="beginner").id
    teach_track_model(writer, db, svc.default_id, clean_session)
    ss = new_session(writer, sam, info, "s-sam")
    add_laps(writer, ss, [copy_lap(base, 70_000, 1), copy_lap(base, 69_500, 2)])
    analyzer = SessionAnalyzer(db)
    first = analyzer.analyse(ss)
    assert first is not None and first.driver is not None and first.driver["skill_level"] == "beginner"
    assert analyzer.analyse(ss) is first
    svc.update(sam, skill_level="intermediate", name="Samuel")  # not through the API: no invalidate() call
    fresh = analyzer.analyse(ss)
    assert fresh is not first and fresh is not None and fresh.driver is not None
    assert (fresh.driver["name"], fresh.driver["skill_level"]) == ("Samuel", "intermediate")
    assert "Driver: Samuel (intermediate level)." in build_fact_sheet(fresh).facts[0].text

    monkeypatch.setattr(session_analysis, "CACHE_ENTRIES", 2)
    for i in range(3):
        add_laps(writer, ss, [copy_lap(base, 69_000 - i, 3 + i)])
        analyzer.analyse(ss)
    assert len(analyzer._cache) == 2  # bounded: each new lap is a new key


def test_personal_best_is_only_same_car_when_the_car_is_known(
    svc: DriverService, store: tuple[Database, DbWriter], clean_session: DecodedSession
) -> None:
    db, writer = store
    info, base = clean_session.info, clean_session.laps[0]
    sam = svc.create("Sam").id
    other_car = new_session(writer, sam, dataclasses.replace(info, car_id="f1:team:other"), "s-other-car")
    add_laps(writer, other_car, [copy_lap(base, 65_000, 1)])
    no_car = new_session(writer, sam, dataclasses.replace(info, car_id=None), "s-no-car")
    add_laps(writer, no_car, [copy_lap(base, 70_000, 1)])
    sa = SessionAnalyzer(db).analyse(no_car)
    assert sa is not None and sa.personal_best is not None and sa.personal_best["session_id"] == other_car
    (pb_fact,) = [f for f in build_fact_sheet(sa).facts if "personal best" in f.text]
    assert "in any car (this session's car is unknown)" in pb_fact.text and "in this car" not in pb_fact.text
    assert "off it" not in pb_fact.text and "gap_s" not in pb_fact.data and pb_fact.data["same_car"] is False


# ---------------------------------------------------------------------------------------------- refusals / initials
def test_refusals_are_not_logged_as_failed_writes(
    svc: DriverService,
    store: tuple[Database, DbWriter],
    clean_session: DecodedSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, writer = store
    sam = svc.create("Sam").id
    new_session(writer, sam, clean_session.info, "s1")
    caplog.set_level(logging.ERROR, logger="pitwall.storage.db")
    errors = writer.errors
    refusals: list[Callable[[], object]] = [
        lambda: svc.create("SAM"),
        lambda: svc.update(sam, name=DEFAULT_DRIVER_NAME),
        lambda: svc.update(999, name="X"),
        lambda: svc.delete(sam),
        lambda: svc.delete(999),
        lambda: svc.delete(sam, reassign_to=999),
        lambda: svc.set_active(999),
        lambda: svc.assign_session("missing", sam),
        lambda: svc.assign_session("s1", 999, activate=True),
    ]
    for refuse in refusals:
        with pytest.raises((DriverConflictError, NotFoundError)):
            refuse()
    assert writer.errors == errors and not [r for r in caplog.records if r.name == "pitwall.storage.db"]
    assert [d.name for d in svc.list_drivers()] == [DEFAULT_DRIVER_NAME, "Sam"] and svc.active_id == svc.default_id


def test_initials_are_ascii_and_the_fallback_round_trips(svc: DriverService, caplog: pytest.LogCaptureFixture) -> None:
    assert default_initials("Émile Zoë") == "EZ" and default_initials("Ørjan") == NO_INITIALS
    assert default_initials("李 Sam") == "S" and default_initials("李") == NO_INITIALS
    caplog.set_level(logging.WARNING, logger="pitwall.drivers")
    emile, li = svc.create("Émile"), svc.create("李")
    assert emile.preferences.initials == "E" and li.preferences.initials == NO_INITIALS
    assert {d.name: d.preferences.initials for d in svc.list_drivers()}["李"] == NO_INITIALS
    assert not caplog.records  # the stored fallback is valid storage, not a bad value logged on every read
    with pytest.raises(DriverValidationError):
        svc.update(li.id, initials=NO_INITIALS)  # but never accepted as input


# ---------------------------------------------------------------------------------------------- radio
def test_attach_radio_follows_the_seat(svc: DriverService) -> None:
    sam = svc.create("Sam", coaching_intensity="quiet").id
    seen: list[str | None] = []
    assert not svc.radio_follows_driver

    def apply(d: Driver | None) -> None:
        seen.append(None if d is None else f"{d.name}:{d.preferences.coaching_intensity}")

    def broken(_d: Driver | None) -> None:
        raise RuntimeError("radio down")

    detach = svc.attach_radio(apply)
    detach_broken = svc.attach_radio(broken)
    assert svc.radio_follows_driver and seen == [f"{DEFAULT_DRIVER_NAME}:normal"]  # applied at once
    svc.set_active(sam)  # a failing radio never fails the switch
    svc.update(sam, coaching_intensity="detailed")
    svc.update(svc.default_id, coaching_intensity="quiet")  # not seated: the radio does not care
    assert seen == [f"{DEFAULT_DRIVER_NAME}:normal", "Sam:quiet", "Sam:detailed"]
    detach()
    detach()  # idempotent
    detach_broken()
    svc.set_active(svc.default_id)
    assert not svc.radio_follows_driver and len(seen) == 3


def test_api_reports_radio_following_and_invalidates_on_patch(
    api: tuple[TestClient, SimpleNamespace], clean_session: DecodedSession
) -> None:
    client, rt = api
    assert client.get("/api/drivers").json()["radio_follows_driver"] is False
    detach = rt.drivers.attach_radio(lambda _d: None)
    assert client.get("/api/drivers").json()["radio_follows_driver"] is True
    detach()
    teach_track_model(rt.writer, rt.db, rt.drivers.default_id, clean_session)
    sid = new_session(rt.writer, rt.drivers.default_id, clean_session.info, "s1")
    add_laps(rt.writer, sid, [copy_lap(clean_session.laps[0], 70_000, 1), copy_lap(clean_session.laps[1], 69_000, 2)])
    analyzer = client.app.state.analyzer  # type: ignore[attr-defined]
    assert analyzer.analyse(sid) is not None and analyzer._cache
    assert client.patch(f"/api/drivers/{rt.drivers.default_id}", json={"skill_level": "beginner"}).status_code == 200
    assert not analyzer._cache


# ---------------------------------------------------------------------------------------------- lane handsfree
def test_handsfree_while_driving_round_trips_and_parses_leniently(svc: DriverService) -> None:
    """Hands-free talking listens only while the car is stationary unless the seated driver's profile allows it while
    driving: an additive preference (no schema change), off by default, told to the radio like any profile edit."""
    james = svc.active
    assert james is not None and james.preferences.handsfree_while_driving is False
    seen: list[bool | None] = []
    svc.subscribe(lambda d: seen.append(None if d is None else d.preferences.handsfree_while_driving))
    on = svc.update(james.id, handsfree_while_driving=True)
    assert on.preferences.handsfree_while_driving is True and on.summary()["handsfree_while_driving"] is True
    assert seen == [True]  # the radio re-applies the seated driver (scope "driving")
    assert svc.get(james.id).preferences.handsfree_while_driving is True  # stored
    assert svc.update(james.id, coaching_intensity="detailed").preferences.handsfree_while_driving is True  # kept
    sam = svc.create("Sam", handsfree_while_driving=True)
    assert sam.preferences.handsfree_while_driving is True
    with pytest.raises(DriverValidationError):
        svc.update(james.id, handsfree_while_driving="yes")  # type: ignore[arg-type]
    assert DriverPreferences.from_stored({"handsfree_while_driving": True}, "Sam").handsfree_while_driving is True
    assert DriverPreferences.from_stored({"handsfree_while_driving": "on"}, "Sam").handsfree_while_driving is False
    assert DriverPreferences.from_stored({"voice_enabled": False}, "Sam").handsfree_while_driving is False  # old rows


def test_api_patch_handsfree_while_driving(api: tuple[TestClient, SimpleNamespace]) -> None:
    client, _rt = api
    james = client.get("/api/drivers").json()["drivers"][0]
    r = client.patch(f"/api/drivers/{james['id']}", json={"handsfree_while_driving": True})
    assert r.status_code == 200 and r.json()["preferences"]["handsfree_while_driving"] is True
    assert client.get(f"/api/drivers/{james['id']}").json()["preferences"]["handsfree_while_driving"] is True
    assert client.patch(f"/api/drivers/{james['id']}", json={"handsfree_while_driving": "maybe"}).status_code == 422
    sam = client.post("/api/drivers", json={"name": "Sam", "handsfree_while_driving": True}).json()
    assert sam["preferences"]["handsfree_while_driving"] is True
