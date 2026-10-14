"""D5: ``GET /api/drivers/{id}/progress`` - per-session progress and PB history for Review > Progress / Coaching.

The laps are the synthetic one-offs session's traces (``tests.conftest.one_offs_scenario``: known injected
mistakes, flashback lap 6, invalid lap 7) with chosen lap times, so lap statistics are exact and corner trends come
from the real session analysis.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pitwall.api.routes_drivers import corner_trends, lap_stats, router
from pitwall.core.lap_processor import LapJob, LapProcessor
from pitwall.core.live import LiveState
from pitwall.core.session_analysis import SessionAnalyzer
from pitwall.drivers import DriverService
from pitwall.storage import repo
from pitwall.storage.db import Database, DbWriter
from tests.conftest import DecodedSession
from tests.unit.test_drivers import copy_lap, lap_ctx


@pytest.fixture
def api(tmp_path: Path) -> Iterator[tuple[TestClient, SimpleNamespace]]:
    db = Database(tmp_path / "progress.sqlite3")
    writer = DbWriter(db)
    rt = SimpleNamespace(db=db, writer=writer, live=LiveState(), drivers=DriverService(db, writer))
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = rt
    with TestClient(app) as client:
        yield client, rt
    writer.close()


def session(
    rt: SimpleNamespace,
    sid: str,
    driver: int | None,
    info: object,
    *,
    source: str = "udp:20777",
    synthetic: bool = False,
) -> str:
    def job(c: sqlite3.Connection) -> None:
        repo.insert_session(c, sid, "f1_25", source, synthetic, None, None, driver_id=driver)
        repo.update_session_info(c, sid, info)  # type: ignore[arg-type]

    rt.writer.call(job)
    return sid


def drive(proc: LapProcessor, sid: str, s: DecodedSession, laps: list[tuple[int, int]]) -> None:
    """(demo lap index, stored lap time) per lap, numbered from 1."""
    for n, (i, ms) in enumerate(laps, start=1):
        proc.process(LapJob(sid, copy_lap(s.laps[i], ms, lap_number=n), lap_ctx(s.info)))


@pytest.fixture
def history(api: tuple[TestClient, SimpleNamespace], one_offs_session: DecodedSession) -> dict[str, int]:
    _client, rt = api
    proc = LapProcessor(rt.db, rt.writer)
    james = rt.drivers.default_id
    jo = rt.drivers.create("Jo").id
    info = one_offs_session.info
    drive(proc, session(rt, "a", james, info), one_offs_session, [(0, 70_000), (1, 69_000)])
    drive(proc, session(rt, "b", james, info), one_offs_session, [(2, 69_500), (3, 68_000), (4, 68_900)])
    drive(proc, session(rt, "c", james, info), one_offs_session, [(5, 60_000), (6, 61_000)])  # flashback, invalid
    drive(proc, session(rt, "rep", james, info, source="replay:x.pwcap"), one_offs_session, [(0, 50_000)])
    drive(proc, session(rt, "syn", james, info, synthetic=True), one_offs_session, [(1, 67_000)])
    drive(proc, session(rt, "jo", jo, info), one_offs_session, [(0, 66_000)])
    return {"james": james, "jo": jo}


def test_lap_stats_unknown_is_none() -> None:
    assert lap_stats([]) == {"best_clean_ms": None, "median_clean_ms": None, "spread_ms": None}
    assert lap_stats([70_000]) == {"best_clean_ms": 70_000, "median_clean_ms": 70_000, "spread_ms": None}
    assert lap_stats([69_500, 68_000, 68_900]) == {
        "best_clean_ms": 68_000,
        "median_clean_ms": 68_900,
        "spread_ms": 1500,
    }
    assert lap_stats([1, 2])["median_clean_ms"] == 2  # rounded to the ms (1.5 -> 2)
    assert corner_trends(None) == (None, None)


def test_progress_per_session_and_pb_history(api: tuple[TestClient, SimpleNamespace], history: dict[str, int]) -> None:
    client, _rt = api
    r = client.get(f"/api/drivers/{history['james']}/progress")
    assert r.status_code == 200
    body = r.json()
    assert body["driver_id"] == history["james"] and not body["include_synthetic"]
    rows = body["sessions"]
    assert [s["session_id"] for s in rows] == ["a", "b", "c"]  # oldest first; never replays or synthetic
    a, b, c = rows
    assert (a["laps"], a["clean_laps"], a["best_clean_ms"], a["median_clean_ms"], a["spread_ms"]) == (
        2,
        2,
        69_000,
        69_500,
        1000,
    )
    assert (b["laps"], b["clean_laps"], b["best_clean_ms"], b["spread_ms"]) == (3, 3, 68_000, 1500)
    assert (c["laps"], c["clean_laps"], c["best_clean_ms"], c["median_clean_ms"], c["spread_ms"]) == (
        2,
        0,
        None,
        None,
        None,
    )
    assert not any(s["synthetic"] for s in rows)
    # corner trends: every session against the same reference lap (James's fastest clean lap)
    assert {s["ref_lap_id"] for s in rows} == {b["ref_lap_id"]} and b["ref_lap_id"] is not None
    compared = [s for s in rows if s["corners"] is not None]
    assert compared and all(isinstance(v, float) for s in compared for v in s["corners"].values())
    assert any(s["habits"] for s in compared)
    assert all(k != "incident" for s in compared for k in s["habits"])
    (track_key,) = body["corner_text"]
    names = set(body["corner_text"][track_key])
    assert all(set(s["corners"]) <= names for s in compared)
    # PB history: the first lap at the track, then each lap that beat it
    assert [(p["session_id"], p["lap_ms"], p["previous_ms"], p["gain_ms"]) for p in body["pb_history"]] == [
        ("a", 70_000, None, None),
        ("a", 69_000, 70_000, 1000),
        ("b", 68_000, 69_000, 1000),
    ]


def test_progress_filters_and_options(api: tuple[TestClient, SimpleNamespace], history: dict[str, int]) -> None:
    client, _rt = api
    james = history["james"]
    with_syn = client.get(f"/api/drivers/{james}/progress", params={"synthetic": "true"}).json()
    assert [s["session_id"] for s in with_syn["sessions"]] == ["a", "b", "c", "syn"]
    assert with_syn["sessions"][-1]["synthetic"] and with_syn["pb_history"][-1]["synthetic"]
    newest = client.get(f"/api/drivers/{james}/progress", params={"limit": 2, "corners": "false"}).json()
    assert [s["session_id"] for s in newest["sessions"]] == ["b", "c"]
    assert all(s["corners"] is None and s["habits"] is None for s in newest["sessions"])
    assert newest["corner_text"] == {}
    other_track = client.get(f"/api/drivers/{james}/progress", params={"track_id": "f1:99"}).json()
    assert other_track["sessions"] == [] and other_track["pb_history"] == []
    jo = client.get(f"/api/drivers/{history['jo']}/progress").json()
    assert [s["session_id"] for s in jo["sessions"]] == ["jo"]
    assert client.get("/api/drivers/999/progress").status_code == 404


def test_progress_uses_the_apps_analyzer(api: tuple[TestClient, SimpleNamespace], history: dict[str, int]) -> None:
    client, rt = api
    client.get(f"/api/drivers/{history['james']}/progress")
    analyzer = client.app.state.analyzer  # type: ignore[attr-defined]
    assert isinstance(analyzer, SessionAnalyzer) and analyzer.analyse("b") is not None
    assert rt.db is analyzer.db


def test_session_lists_carry_the_clean_lap_count(
    api: tuple[TestClient, SimpleNamespace], history: dict[str, int]
) -> None:
    client, rt = api
    rows = {r["id"]: r for r in client.get(f"/api/drivers/{history['james']}/sessions").json()}
    assert (rows["a"]["lap_count"], rows["a"]["clean_lap_count"]) == (2, 2)
    assert (rows["c"]["lap_count"], rows["c"]["clean_lap_count"]) == (2, 0)
    rt.writer.call(lambda c: repo.insert_session(c, "empty", "f1_25", "udp:20777", False, None, None))
    with rt.db.read() as c:
        empty = next(r for r in repo.list_sessions(c) if r["id"] == "empty")
    assert (empty["lap_count"], empty["clean_lap_count"]) == (0, 0)
