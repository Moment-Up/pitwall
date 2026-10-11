"""D2: ``snapshot.bests`` = session / driver / household bests for the live game + track + car.

docs/ui/design-spec.md 4.6 and section 13: clean laps only, each sector best on its own, synthetic sessions and
replays never count, recomputed after each lap and sent with every snapshot (a few hundred bytes: a record is
coloured as set, not up to 5 s later with the static payload).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pitwall.core.lap_processor import AnalysisWorker, LapJob, LapProcessor
from pitwall.core.live import BestsRequest, LiveState
from pitwall.storage import repo
from pitwall.storage.db import Database, DbWriter
from tests.conftest import DecodedSession

GAME, TRACK, CAR = "f1_25", "f1:10", "f1:team:8"


@pytest.fixture
def store(tmp_path: Path) -> Iterator[tuple[Database, DbWriter]]:
    db = Database(tmp_path / "bests.sqlite3")
    writer = DbWriter(db)
    yield db, writer
    writer.close()


def add_driver(c: sqlite3.Connection, name: str) -> int:
    return repo.insert_driver(c, name, {})


def add_session(
    c: sqlite3.Connection,
    sid: str,
    driver: int | None,
    *,
    car: str | None = CAR,
    track: str = TRACK,
    length: float | None = 5000.0,
    synthetic: bool = False,
    source: str = "udp:20777",
    started: float = 1000.0,
) -> str:
    repo.insert_session(c, sid, GAME, source, synthetic, None, None, driver_id=driver)
    c.execute(
        "UPDATE sessions SET track_id=?, car_id=?, track_length_m=?, started_unix=? WHERE id=?",
        (track, car, length, started, sid),
    )
    return sid


def add_lap(
    c: sqlite3.Connection,
    sid: str,
    n: int,
    ms: int | None,
    sectors: tuple[int | None, int | None, int | None] = (None, None, None),
    clean: bool = True,
    created: float = 2000.0,
) -> int:
    cur = c.execute(
        "INSERT INTO laps(session_id, lap_number, lap_time_ms, s1_ms, s2_ms, s3_ms, clean, n_samples, trace, "
        "created_unix) VALUES(?,?,?,?,?,?,?,0,x'',?)",
        (sid, n, ms, *sectors, int(clean), created),
    )
    return int(cur.lastrowid or 0)


@pytest.fixture
def family(store: tuple[Database, DbWriter]) -> dict[str, Any]:
    """James and Jo at one track in one car, plus everything that must never count."""
    _db, writer = store

    def job(c: sqlite3.Connection) -> dict[str, Any]:
        james, jo = add_driver(c, "James"), add_driver(c, "Jo")
        ids: dict[str, Any] = {"james": james, "jo": jo}
        add_session(c, "old", james, started=1000)
        ids["james_pb"] = add_lap(c, "old", 1, 90_500, (30_100, 30_200, 30_200), created=1100)
        add_lap(c, "old", 2, 91_000, (29_900, 30_600, 30_500), created=1200)  # James's best S1 on its own
        add_lap(c, "old", 3, 85_000, (28_000, 28_000, 29_000), clean=False, created=1300)  # not clean
        add_session(c, "jo1", jo, started=1500)
        ids["record"] = add_lap(c, "jo1", 1, 90_100, (30_000, 30_300, 29_800), created=1600)
        # never counted: another car, another layout, synthetic, a replay, another track
        add_session(c, "car", james, car="f1:team:1")
        add_lap(c, "car", 1, 80_000, (20_000, 30_000, 30_000))
        add_session(c, "short", james, length=4600.0)
        add_lap(c, "short", 1, 80_000, (20_000, 30_000, 30_000))
        add_session(c, "syn", james, synthetic=True)
        add_lap(c, "syn", 1, 80_000, (20_000, 30_000, 30_000))
        add_session(c, "rep", james, source="replay:x.pwcap")
        add_lap(c, "rep", 1, 80_000, (20_000, 30_000, 30_000))
        add_session(c, "other", james, track="f1:11")
        add_lap(c, "other", 1, 80_000, (20_000, 30_000, 30_000))
        # today's session
        add_session(c, "now", james, started=3000)
        ids["sb"] = add_lap(c, "now", 1, 90_800, (30_050, 30_400, 30_350), created=3100)
        ids["sb_s2"] = add_lap(c, "now", 2, 91_200, (30_300, 30_100, 30_800), created=3200)
        return ids

    return writer.call(job)


def bests(db: Database, sid: str = "now", driver: int | None = None, **kw: Any) -> dict[str, Any]:
    with db.read() as c:
        owner = repo.session_driver_id(c, sid) if driver is None else driver
        return repo.lap_bests(c, sid, GAME, kw.pop("track", TRACK), kw.pop("car", CAR), owner, 5000.0, **kw)


def test_three_tiers_from_clean_real_laps_in_this_car(store: tuple[Database, DbWriter], family: dict[str, Any]) -> None:
    db, _ = store
    b = bests(db)
    assert b["scope"] == {"game": GAME, "track_id": TRACK, "car_id": CAR, "records": True}
    assert b["session"] == {
        "lap_ms": 90_800,
        "sectors_ms": [30_050, 30_100, 30_350],  # each sector on its own
        "lap_id": family["sb"],
        "sector_lap_ids": [family["sb"], family["sb_s2"], family["sb"]],
    }
    driver = b["driver"]
    assert driver["lap_ms"] == 90_500 and driver["lap_id"] == family["james_pb"]
    assert driver["sectors_ms"] == [29_900, 30_100, 30_200]  # S2 from today: the session's laps count too
    assert driver["set_unix"] == 1100 and driver["session_id"] == "old"
    household = b["household"]
    assert household["lap_ms"] == 90_100 and household["driver_id"] == family["jo"]
    assert household["lap_id"] == family["record"] and household["sectors_ms"] == [29_900, 30_100, 29_800]


def test_unknown_car_synthetic_and_replay_sessions_hold_no_records(
    store: tuple[Database, DbWriter], family: dict[str, Any]
) -> None:
    db, _ = store
    unknown_car = bests(db, car=None)
    assert unknown_car["driver"] is None and unknown_car["household"] is None
    assert unknown_car["session"]["lap_ms"] == 90_800  # this session's own laps are still facts
    replayed = bests(db, records=False)
    assert replayed["driver"] is None and replayed["household"] is None and not replayed["scope"]["records"]
    nobody = bests(db, sid="now", driver=None)
    assert nobody["driver"] is not None  # owner read from the session row
    with db.read() as c:
        unowned = repo.lap_bests(c, "now", GAME, TRACK, CAR, None, 5000.0)
    assert unowned["driver"] is None and unowned["household"] is not None


def test_a_session_without_clean_laps_has_an_empty_session_tier(store: tuple[Database, DbWriter]) -> None:
    db, writer = store

    def job(c: sqlite3.Connection) -> None:
        add_session(c, "fresh", add_driver(c, "Kim"))
        add_lap(c, "fresh", 1, 95_000, clean=False)

    writer.call(job)
    b = bests(db, sid="fresh")
    assert b["session"] == {"lap_ms": None, "sectors_ms": [None] * 3, "lap_id": None, "sector_lap_ids": [None] * 3}
    assert b["driver"] is None and b["household"] is None


# ---------------------------------------------------------------------------------------------- live publishing
def test_bests_ride_every_snapshot_and_follow_each_lap(
    store: tuple[Database, DbWriter], clean_session: DecodedSession
) -> None:
    from tests.unit.test_drivers import copy_lap, lap_ctx, new_session

    db, writer = store
    info = clean_session.info
    live = LiveState()
    proc = LapProcessor(db, writer, live)
    james = writer.call(lambda c: add_driver(c, "James"))
    sid = new_session(writer, james, info, "s1")
    live.reset_session(sid, "udp:20777", False)
    ctx = lap_ctx(info)
    assert live.snapshot()["bests"] is None and live.snapshot(include_static=True)["bests"] is None
    first = proc.process(LapJob(sid, copy_lap(clean_session.laps[0], 70_000), ctx))
    b = live.snapshot()["bests"]  # the very next snapshot, not only the 5 s static one
    assert b == live.snapshot(include_static=True)["bests"]
    assert b["session"]["lap_ms"] == 70_000 and b["session"]["lap_id"] == first["lap_id"]
    assert info.car_id is not None and b["scope"]["records"] and b["scope"]["car_id"] == info.car_id
    assert b["driver"]["lap_ms"] == 70_000 and b["household"]["lap_ms"] == 70_000
    proc.process(LapJob(sid, copy_lap(clean_session.laps[1], 69_000), ctx))
    assert live.snapshot()["bests"]["session"]["lap_ms"] == 69_000
    # another session went live meanwhile: its bests are never overwritten by the old session's
    live.reset_session("s2", "udp:20777", False)
    proc.process(LapJob(sid, copy_lap(clean_session.laps[2], 68_000), ctx))
    assert live.snapshot()["bests"] is None


def test_a_synthetic_live_session_gets_no_personal_bests_or_records(
    store: tuple[Database, DbWriter], clean_session: DecodedSession
) -> None:
    from tests.unit.test_drivers import copy_lap, lap_ctx, new_session

    db, writer = store
    live = LiveState()
    proc = LapProcessor(db, writer, live)
    sid = new_session(writer, writer.call(lambda c: add_driver(c, "James")), clean_session.info, "syn")
    live.reset_session(sid, "udp:20777", True)
    proc.process(LapJob(sid, copy_lap(clean_session.laps[0], 70_000), lap_ctx(clean_session.info)))
    b = live.snapshot(include_static=True)["bests"]
    assert b["session"]["lap_ms"] == 70_000
    assert b["driver"] is None and b["household"] is None and not b["scope"]["records"]


def test_a_new_context_is_computed_before_the_first_lap(
    store: tuple[Database, DbWriter], clean_session: DecodedSession
) -> None:
    """The Ready card shows "your best here" and the family record before the first lap of a session."""
    from tests.unit.test_drivers import copy_lap, lap_ctx, new_session

    db, writer = store
    info = clean_session.info
    live = LiveState()
    proc = LapProcessor(db, writer, live)
    worker = AnalysisWorker(proc)
    try:
        james = writer.call(lambda c: add_driver(c, "James"))
        old = new_session(writer, james, info, "old")
        live.reset_session(old, "udp:20777", False)
        proc.process(LapJob(old, copy_lap(clean_session.laps[0], 70_000), lap_ctx(info)))
        sid = new_session(writer, james, info, "today")
        requests: list[BestsRequest] = []
        live.set_bests_requester(lambda r: (requests.append(r), worker.request_bests(r)))
        live.reset_session(sid, "udp:20777", False)
        live.on_driver(james, None)
        live.on_session(info)
        live.on_session(info)  # same context: no second request
        worker.join()
        assert [r.session_id for r in requests] == [sid]
        b = live.snapshot(include_static=True)["bests"]
        assert b["session"]["lap_ms"] is None
        assert b["driver"]["lap_ms"] == 70_000 and b["driver"]["session_id"] == old
    finally:
        worker.close()
    assert live._bests_requester is None
