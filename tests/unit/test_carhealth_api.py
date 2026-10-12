"""Car health API (``api.routes_carhealth``): the live views (with the thresholds table), the off shapes, the
household settings (400 on a bad value), the worker's counters; the runtime's listener hands settings over."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pitwall.api.routes_carhealth import router
from pitwall.carhealth.settings import SECTION, from_stored
from pitwall.carhealth.worker import CarHealthWorker
from pitwall.core.live import LiveState
from pitwall.settings_store import SettingsStore
from tests.unit.carhealth_helpers import drive, info


@pytest.fixture
def api(tmp_path: Path) -> Iterator[tuple[TestClient, SimpleNamespace]]:
    live = LiveState()
    rt = SimpleNamespace(
        live=live, store=SettingsStore(tmp_path / "settings.json"), health=CarHealthWorker(live, start=False)
    )
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = rt
    with TestClient(app) as client:
        yield client, rt


def test_no_live_session(api: tuple[TestClient, SimpleNamespace]) -> None:
    client, _ = api
    ch = client.get("/api/car-health/live").json()
    assert ch["session_id"] is None and ch["tyres"] == {"available": False, "reason": "no live session"}
    assert ch["thresholds"]
    rc = client.get("/api/racecraft/live").json()
    assert rc["mode"] == "off" and rc["reason"] == "no live session"


def test_live_views_with_the_thresholds(api: tuple[TestClient, SimpleNamespace]) -> None:
    client, rt = api
    rt.live.reset_session("s1", "test", False, "f1_25")
    assert client.get("/api/car-health/live").json()["tyres"]["reason"] == "waiting for car data"
    w: CarHealthWorker = rt.health
    w.submit("s1", info())
    eng_items = []
    from pitwall.carhealth.engine import CarHealthEngine

    probe = CarHealthEngine("probe")
    probe.feed = eng_items.append  # type: ignore[method-assign]
    drive(probe, 0.0, 100.0, lap_s=60.0)
    for it in eng_items:
        w.submit("s1", it)
    w.process_pending()
    ch = client.get("/api/car-health/live").json()
    assert ch["session_id"] == "s1" and ch["tyres"]["available"] and ch["thresholds"][0]["name"]
    assert "thresholds" not in rt.live.snapshot()["car_health"]
    rc = client.get("/api/racecraft/live").json()
    assert rc["session_id"] == "s1" and rc["mode"] == "race" and rc["reason"] == "corners not learned yet"
    stats = client.get("/api/car-health/stats").json()
    assert stats["processed"] == len(eng_items) + 1 and stats["dropped"] == 0


def test_settings_round_trip_and_bad_values(api: tuple[TestClient, SimpleNamespace]) -> None:
    client, rt = api
    assert client.get("/api/car-health/settings").json() == {
        "tyre_calls": True,
        "wear_calls": True,
        "fuel_calls": True,
        "slip_calls": "detailed",
    }
    got = client.put("/api/car-health/settings", json={"slip_calls": "normal", "fuel_calls": False}).json()
    assert got["slip_calls"] == "normal" and got["fuel_calls"] is False and got["tyre_calls"] is True
    assert from_stored(rt.store.get(SECTION)).slip_calls == "normal"
    for bad in ({"slip_calls": "loud"}, {"tyre_calls": "yes"}, {"volume": 3}):
        r = client.put("/api/car-health/settings", json=bad)
        assert r.status_code == 400, bad
    assert client.get("/api/car-health/settings").json()["slip_calls"] == "normal"


def test_runtime_hands_settings_to_its_workers(tmp_path: Path) -> None:
    from pitwall.config import Settings
    from pitwall.core.runtime import Runtime

    rt = Runtime(Settings(data_dir=tmp_path, llm_enabled=False))
    try:
        assert rt.health.settings.slip_calls == "detailed"
        rt.store.replace(SECTION, {"slip_calls": "off", "tyre_calls": False})
        assert rt.health.settings.slip_calls == "off" and rt.health.settings.tyre_calls is False
    finally:
        rt.close()


def test_ws_live_sends_the_health_blocks_only_when_they_changed(tmp_path: Path) -> None:
    from typing import Any

    import orjson

    from pitwall.api.app import create_app
    from pitwall.config import Settings

    def snapshots(ws: Any) -> Any:
        while True:
            msg = orjson.loads(ws.receive_bytes())
            if msg["type"] == "snapshot":
                yield dict(msg["data"])

    app = create_app(Settings(data_dir=tmp_path, llm_enabled=False, voice_enabled=False), start_udp=False)
    with TestClient(app, client=("127.0.0.1", 40000)) as client:
        live = app.state.runtime.live
        live.reset_session("s1", "udp:20777", False)
        with client.websocket_connect("/ws/live") as ws:
            snaps = snapshots(ws)
            first = next(snaps)
            assert first["car_health"] is None and first["racecraft"] is None
            view = {"version": 1, "session_id": "s1", "tyres": {"available": False, "reason": "x"}}
            live.set_car_health("s1", view)
            live.set_car_health("s0", {"session_id": "s0"})  # another session's: dropped
            live.version += 1
            assert next(snaps)["car_health"] == view
            live.version += 1
            assert "car_health" not in next(snaps)
            rc = {"version": 1, "session_id": "s1", "mode": "off", "reason": "y", "ahead": None, "behind": None}
            live.set_racecraft("s1", rc)
            live.version += 1
            assert next(snaps)["racecraft"] == rc
