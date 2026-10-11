"""Race strategy API (``api.routes_strategy``): the live view and a stored session's timeline."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pitwall.api.routes_strategy import router
from pitwall.config import Settings
from pitwall.core.live import LiveState
from pitwall.storage import repo
from pitwall.storage.db import Database


@pytest.fixture
def api(tmp_path: Path) -> Iterator[tuple[TestClient, SimpleNamespace]]:
    rt = SimpleNamespace(db=Database(tmp_path / "s.sqlite3"), live=LiveState())
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = rt
    with TestClient(app) as client:
        yield client, rt


def _session(rt: SimpleNamespace, sid: str, session_type: str, ended: bool = True, game: str = "f1_25") -> None:
    with rt.db.read() as c:
        c.execute(
            "INSERT INTO sessions(id, game, started_unix, ended_unix, source, synthetic, session_type) "
            "VALUES(?, ?, ?, ?, 'udp:20777', 0, ?)",
            (sid, game, time.time(), time.time() if ended else None, session_type),
        )
        c.commit()


def _lap_row(rt: SimpleNamespace, sid: str, lap: int, ms: int | None) -> None:
    with rt.db.read() as c:
        c.execute(
            "INSERT INTO laps(session_id, lap_number, lap_time_ms, valid, clean, flags, meta, n_samples, trace, "
            "created_unix) VALUES(?, ?, ?, 1, 1, '[]', '{}', 0, X'', ?)",
            (sid, lap, ms, time.time()),
        )
        c.commit()


def _record(lap: int, **kw: object) -> dict[str, object]:
    return {
        "v": 1,
        "lap": lap,
        "total_laps": 6,
        "grid_position": 8,
        "position": 9 - lap,
        "lap_time_ms": 75000 + lap,
        "pit": None,
        "stops": 0,
        "compound": "medium",
        "tyre_age_laps": lap,
        "wear_pct": [2.0 * lap] * 4,
        "safety_car": "none",
        "weather": "clear",
        "rain_pct": 5,
        "calls": [
            {
                "id": f"c{lap}",
                "topic": "gap",
                "level": "normal",
                "text": "Car behind is within a second.",
                "t_unix": 1.0,
            }
        ]
        if lap == 2
        else [],
        **kw,
    }


def test_live_view_without_and_with_a_session(api: tuple[TestClient, SimpleNamespace]) -> None:
    client, rt = api
    v = client.get("/api/strategy/live").json()
    assert v["mode"] == "off" and v["reason"] == "no live session" and v["calls"] == [] and v["version"] == 1
    rt.live.reset_session("s1", "udp:20777", False)
    assert client.get("/api/strategy/live").json()["reason"] == "waiting for race timing"
    rt.live.set_strategy("s1", {"version": 1, "mode": "race", "session_id": "s1"})
    assert client.get("/api/strategy/live").json() == {"version": 1, "mode": "race", "session_id": "s1"}


def test_timeline_404_not_a_race_and_old_sessions(api: tuple[TestClient, SimpleNamespace]) -> None:
    client, rt = api
    assert client.get("/api/sessions/nope/strategy").status_code == 404
    _session(rt, "q1", "qualifying")
    q = client.get("/api/sessions/q1/strategy").json()
    assert q["available"] is False and q["reason"] == "not a race" and q["laps"] == []
    _session(rt, "old", "race")
    _lap_row(rt, "old", 1, 81000)
    assert client.get("/api/sessions/old/strategy").json()["reason"] == "recorded before strategy tracking"
    _session(rt, "split", "race")  # a short split that ended before any lap was complete
    _lap_row(rt, "split", 2, None)
    assert client.get("/api/sessions/split/strategy").json()["reason"] == "no complete lap in this session"
    _session(rt, "gt7", "race", game="gt7")
    assert client.get("/api/sessions/gt7/strategy").json()["reason"] == "race strategy needs F1 25 timing"
    _session(rt, "live", "race", ended=False)
    assert client.get("/api/sessions/live/strategy").json()["reason"] == "no strategy laps yet"


def test_timeline_from_records_and_stops(api: tuple[TestClient, SimpleNamespace]) -> None:
    client, rt = api
    _session(rt, "r1", "race")
    recs = [
        _record(1),
        _record(2),
        _record(3, pit="in", safety_car="virtual"),
        _record(
            4,
            pit="out",
            stops=1,
            compound="hard",
            tyre_age_laps=0,
            wear_pct=[1.0] * 4,
            safety_car="virtual",
            weather="light_rain",
            rain_pct=60,
        ),
        _record(5, compound="hard", tyre_age_laps=1, wear_pct=[3.0] * 4, stops=1, weather="light_rain"),
        _record(6, compound="hard", tyre_age_laps=2, wear_pct=[5.0] * 4, stops=1, weather="light_rain"),
    ]
    stops = [
        {
            "car_index": 3,
            "is_player": True,
            "entry_lap": 3,
            "exit_lap": 4,
            "laps_ms": [80000, 92000],
            "lane_time_ms": 21000,
            "stationary_ms": 2600,
            "pit_loss_ms": 9800,
            "neutralised": "virtual",
            "compound_before": "medium",
            "compound_after": "hard",
        },
        {
            "car_index": 14,
            "is_player": False,
            "entry_lap": 2,
            "exit_lap": 3,
            "laps_ms": [81575, 92836],
            "lane_time_ms": 20019,
            "stationary_ms": 3353,
            "pit_loss_ms": 18911,
        },
        {
            "car_index": 7,
            "is_player": False,
            "entry_lap": 1,
            "exit_lap": 2,
            "stationary_ms": 8541,
            "excluded": "long stop (repair?)",
        },
    ]
    with rt.db.read() as c:
        for r in recs:
            repo.upsert_strategy_lap(c, "r1", int(r["lap"]), r)  # type: ignore[arg-type]
        for s in stops:
            repo.upsert_pit_stop(c, "r1", s)
        c.commit()
    tl = client.get("/api/sessions/r1/strategy").json()
    assert tl["available"] is True and tl["reason"] is None
    assert (tl["total_laps"], tl["grid_position"], tl["finish_position"]) == (6, 8, 3)
    assert [r["lap"] for r in tl["laps"]] == [1, 2, 3, 4, 5, 6]
    assert [(s["compound"], s["start_lap"], s["end_lap"], s["laps"]) for s in tl["stints"]] == [
        ("medium", 1, 3, 3),
        ("hard", 4, 6, 3),
    ]
    assert tl["stints"][0]["wear_rate_pct_per_lap"] == 2.0 and tl["stints"][0]["median_lap_ms"] == 75002
    (mine,) = tl["stops"]
    assert mine == {
        "car_index": 3,
        "is_player": True,
        "entry_lap": 3,
        "exit_lap": 4,
        "lane_time_s": 21.0,
        "stationary_s": 2.6,
        "pit_loss_s": 9.8,
        "neutralised": "virtual",
        "excluded": None,
        "compound_before": "medium",
        "compound_after": "hard",
    }
    assert [s["car_index"] for s in tl["field_stops"]] == [7, 14]
    assert tl["pit_loss"] == {"median_s": 18.9, "range": {"low": 18.9, "high": 18.9}, "n": 1}
    assert tl["safety_car_periods"] == [{"status": "virtual", "start_lap": 3, "end_lap": 4}]
    assert tl["weather"] == [
        {"lap": 1, "weather": "clear", "rain_pct": 5},
        {"lap": 4, "weather": "light_rain", "rain_pct": 60},
    ]
    assert tl["calls"] == [
        {
            "id": "c2",
            "topic": "gap",
            "level": "normal",
            "text": "Car behind is within a second.",
            "t_unix": 1.0,
            "lap": 2,
        }
    ]


def test_mounted_in_the_app(tmp_path: Path) -> None:
    from pitwall.api.app import create_app

    app = create_app(Settings(data_dir=tmp_path, llm_enabled=False, voice_enabled=False), start_udp=False)
    with TestClient(app, client=("127.0.0.1", 40000)) as client:
        r = client.get("/api/strategy/live")
        assert r.status_code == 200 and r.json()["mode"] == "off"
        assert client.get("/api/live").json()["strategy"] is None
