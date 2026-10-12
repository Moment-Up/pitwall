"""Race radio API (``api.routes_race``): the live race view, or why there is none."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pitwall.api.routes_race import router
from pitwall.core.live import LiveState
from pitwall.raceradio.model import off_view
from tests.unit.raceradio_helpers import info


def client() -> tuple[TestClient, LiveState]:
    live = LiveState()
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = SimpleNamespace(live=live)
    return TestClient(app), live


def test_live_view_or_the_reason() -> None:
    c, live = client()
    assert c.get("/api/race/live").json() == off_view("no live session")
    live.reset_session("s1", "test", False, "gt7")
    live.on_session(info(0.0))
    got = c.get("/api/race/live").json()
    assert (got["mode"], got["reason"], got["session_id"], got["game"]) == (
        "off",
        "waiting for the race radio",
        "s1",
        "f1_25",
    )
    view = {**off_view(None, "s1", False, "f1_25"), "mode": "race", "position": 3}
    live.set_race("s1", view)
    assert c.get("/api/race/live").json() == view
