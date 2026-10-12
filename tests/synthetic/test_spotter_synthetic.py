"""The spotter end to end on SYNTHETIC streams (spec section 11.3): capture -> PacketRouter -> SessionManager ->
SpotterWorker -> calls, for every scenario at 60, 20 and 10 Hz, and once through the app to a /ws/radio client.
Synthetic: proves the algorithm on known geometry, never compatibility with the game."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.compat import recv_clock_ns
from pitwall.config import Settings
from pitwall.core.live import LiveState
from pitwall.core.session import SessionManager
from pitwall.ingest.router import PacketRouter
from pitwall.sim.spotter_scenarios import CarPath, SpotterScenario, at_rate, generate, scenarios, write_capture_file
from pitwall.spotter.model import SpotterCall
from pitwall.spotter.settings import SpotterSettings
from pitwall.spotter.worker import SpotterWorker
from pitwall.voice.types import AudioClip

pytestmark = pytest.mark.synthetic


class _Appends:
    def submit(self, *a: Any) -> bool:
        return True

    def submit_ai_pace(self, *_a: Any) -> None:
        return None

    def end_session(self, *a: Any) -> None:
        return None


def _run(sc: SpotterScenario) -> tuple[list[SpotterCall], SpotterWorker, LiveState]:
    live = LiveState()
    calls: list[SpotterCall] = []
    w = SpotterWorker(live, SpotterSettings(enabled=True), sink=calls.append, start=False)
    sm = SessionManager(cast(Any, _Appends()), live, cast(Any, _Appends()), source="udp:20777", spotter=w)
    router = PacketRouter([F1Adapter(field_motion=True)], sm, live)
    for p in generate(sc):
        router.handle(p)
        w.process_pending()  # driven synchronously: the order the worker thread would see
    return calls, w, live


CASES = [(sc, rate) for sc in scenarios() for rate in (60.0, 20.0, 10.0)]


@pytest.mark.parametrize(("sc", "rate"), CASES, ids=[f"{sc.name}@{r:g}" for sc, r in CASES])
def test_scenario_calls(sc: SpotterScenario, rate: float) -> None:
    calls, w, live = _run(sc if rate == 60.0 else at_rate(sc, rate))
    assert tuple(c.kind for c in calls) == sc.expected
    assert live.synthetic  # the synthetic UID flags the session everywhere
    assert w.counters()["invalid"] == 0 and w.errors == 0


def test_the_2026_format_too() -> None:
    import dataclasses

    for sc in scenarios()[:3]:
        calls, _w, _live = _run(dataclasses.replace(sc, packet_format=2026, formula=13))
        assert tuple(c.kind for c in calls) == sc.expected


def test_onset_delay_on_the_game_clock() -> None:
    calls, _w, _live = _run(scenarios()[0])
    assert calls[0].onset_game_ms is not None and 49.9 <= calls[0].onset_game_ms < 67.0  # float32 clock


class LoudTts:
    name = "loud"
    sample_rate = 22_050

    def synthesize(self, text: str) -> AudioClip:
        return AudioClip(b"\x00\x10" * int(0.4 * self.sample_rate), self.sample_rate)


def _recv_until(ws: Any, pred: Any, limit: int = 2000) -> tuple[list[Any], Any]:
    seen: list[Any] = []
    for _ in range(limit):
        m = ws.receive()
        item: Any = m.get("bytes") if m.get("bytes") is not None else json.loads(m["text"])
        seen.append(item)
        if isinstance(item, dict) and pred(item):
            return seen, item
    raise AssertionError(f"condition not met; got {seen[-5:]}")


def test_end_to_end_to_a_device_voice_radio(tmp_path: Path) -> None:
    from pitwall.api.app import create_app

    s = Settings(
        data_dir=tmp_path,
        llm_enabled=False,
        stt_engine="none",
        tts_engine="none",
        tailscale_trust_owner=False,
        access_token="tok",
    )
    app = create_app(s, start_udp=False)
    quick = SpotterScenario(
        "e2e",
        "a car alongside for 1 s, then gone",
        (CarPath(1, lon=((0.0, -12.0), (0.6, -2.0), (1.6, 2.0), (2.0, 14.0)), lat=((0.0, -3.2),)),),
        ("car_left", "clear_left"),
        duration_s=2.6,
    )
    with TestClient(app) as client:
        hub = app.state.hub
        hub.tts = LoudTts()
        assert client.put("/api/spotter/settings", json={"enabled": True}).status_code == 200
        with client.websocket_connect("/ws/radio") as ws:
            ws.receive()
            ws.send_text(json.dumps({"type": "hello", "client": "ipad", "tts_mode": "device", "version": 1}))
            deadline = time.monotonic() + 20
            while not client.get("/api/spotter").json()["status"]["audio"]["ready"]:
                assert time.monotonic() < deadline, "spotter audio never built"
                time.sleep(0.05)
            cap = tmp_path / "e2e.pwcap"
            write_capture_file(cap, quick, start_ns=recv_clock_ns())
            app.state.runtime.start_replay(cap, speed=1.0)
            got = []
            for want in ("car_left", "clear_left"):
                _seen, say = _recv_until(
                    ws,
                    lambda m, want=want: (
                        m.get("type") == "say" and m.get("kind") == "spotter" and m["meta"]["spotter"] == want
                    ),
                )
                assert say["n_bytes"] > 0 and not say.get("device_tts")  # PCM reaches the device-voice iPad
                ws.send_text(json.dumps({"type": "playback", "id": say["id"], "state": "started"}))
                ws.send_text(json.dumps({"type": "playback", "id": say["id"], "state": "ended"}))
                got.append(say["text"])
            assert got == ["Car left.", "Clear left."]
        body = client.get("/api/spotter").json()
        lat = body["latency"]
        assert lat["queued_ms"]["n"] == 2 and lat["started_ms"]["n"] >= 1 and lat["decide_ms"]["n"] == 2
        assert body["counters"]["spoken"] == {"car_left": 1, "clear_left": 1}
        app.state.runtime.stop_replay()
