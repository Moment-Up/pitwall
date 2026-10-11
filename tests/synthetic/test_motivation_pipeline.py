"""SYNTHETIC end to end: the coaching demo driven through the live path (session manager tagged with the seated
driver, not a replay) reaches a goal; the ``motivation`` note reaches ``/ws/live`` and the radio queues one line; the
recap and badges are served. The worker counts synthetic driving only because this test builds it with the
test-only ``include_synthetic=True``: in the app, synthetic sessions never count for goals.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pitwall.config import Settings
from pitwall.core.runtime import Runtime, finish_router
from pitwall.core.session import SessionManager
from pitwall.ingest.capture import CaptureReader
from pitwall.ingest.router import PacketRouter
from pitwall.integrations import adapters_for
from pitwall.motivation.worker import MotivationWorker
from pitwall.sim.scenarios import write_synthetic_capture

pytestmark = pytest.mark.synthetic


@pytest.fixture
def app_rig(tmp_path: Path) -> Iterator[tuple[Any, TestClient, Runtime, Path]]:
    from pitwall.api.app import create_app

    s = Settings(
        data_dir=tmp_path,
        llm_enabled=False,
        stt_engine="none",
        tts_engine="none",
        tailscale_trust_owner=False,
        access_token="tok",
    )
    cap = s.capture_dir / "demo.pwcap"
    write_synthetic_capture(cap)
    app = create_app(s, start_udp=False)
    with TestClient(app) as client:
        rt: Runtime = app.state.runtime
        rt.motivation.close()
        rt.motivation = MotivationWorker(rt.db, rt.writer, rt.live, include_synthetic=True)  # test only
        yield app, client, rt, cap


class Recording:
    """The radio scheduler, remembering every message queued (a later lap supersedes an unsaid goal line)."""

    def __init__(self, inner: Any, queued: list[Any]) -> None:
        self.inner = inner
        self.queued = queued

    def enqueue(self, m: Any) -> bool:
        self.queued.append(m)
        return bool(self.inner.enqueue(m))

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


def drive(rt: Runtime, cap: Path) -> None:
    """Stream the capture through a live-source session manager (as the UDP listener does), on this thread."""
    sessions = SessionManager(rt.writer, rt.live, rt.worker, source="udp:test", drivers=rt.drivers)
    router = PacketRouter(adapters_for(("f1",)), sessions, rt.live)
    for pkt in CaptureReader(cap):
        router.handle(pkt)
    finish_router(router)
    rt.worker.join()
    rt.motivation.join()


def test_goal_reached_on_the_live_path(app_rig: tuple[Any, TestClient, Runtime, Path]) -> None:
    app, client, rt, cap = app_rig
    driver = rt.drivers.active
    assert driver is not None
    goal = client.post(f"/api/drivers/{driver.id}/goals", json={"kind": "clean_streak", "target": 2}).json()
    assert goal["status"] == "active"
    hub = app.state.hub
    queued: list[Any] = []
    if hub is not None:
        hub.scheduler = Recording(hub.scheduler, queued)
    notes: list[dict[str, Any]] = []
    with client.websocket_connect("/ws/live") as ws:
        worker = threading.Thread(target=drive, args=(rt, cap))
        worker.start()
        worker.join(120)
        for _ in range(5000):
            m = json.loads(ws.receive_bytes())
            if m["type"] == "motivation":
                notes.append(m["data"])
                break
    (note,) = notes
    assert note["kind"] == "goals_achieved" and note["driver_id"] == driver.id
    assert [g["id"] for g in note["goals"]] == [goal["id"]] and note["goals"][0]["title"] == "2 clean laps in a row"
    sid = note["session_id"]
    (stored,) = client.get(f"/api/drivers/{driver.id}/goals").json()["goals"]
    assert stored["status"] == "achieved" and stored["achieved"]["session_id"] == sid
    assert rt.motivation.notes == 1  # exactly once
    if hub is not None:  # the radio queued one goal line (a later lap's summary supersedes it if still unsaid)
        lines = [m for m in queued if m.id.startswith("goal-")]
        assert [m.text for m in lines] == ["Goal reached: 2 clean laps in a row."]
        assert lines[0].meta["lap_id"] == note["lap_id"] and lines[0].kind.value == "lap_summary"
    recap = client.get(f"/api/sessions/{sid}/recap").json()
    assert recap["synthetic"] and recap["things"]["progress"] is None
    assert recap["why_empty"]["progress"] == "Synthetic sessions do not count towards progress"
    assert recap["things"]["work_on"] is not None
    real_only = client.get(f"/api/drivers/{driver.id}/badges").json()
    assert real_only["badges"] == [] or all(b["key"].startswith("goals_reached") for b in real_only["badges"])
    with_syn = client.get(f"/api/drivers/{driver.id}/badges", params={"synthetic": "true"}).json()
    assert any(b["synthetic"] for b in with_syn["badges"])
