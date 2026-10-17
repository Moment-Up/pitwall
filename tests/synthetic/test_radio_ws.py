"""End-to-end radio over the real /ws/radio WebSocket (SYNTHETIC session data, fake speech engines)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from pitwall.config import Settings
from pitwall.core.runtime import Runtime
from pitwall.sim.scenarios import write_synthetic_capture
from pitwall.voice.types import AudioClip, SttResult

pytestmark = pytest.mark.synthetic


class ScriptedStt:
    name = "scripted"

    def __init__(self) -> None:
        self.next_text = "how are my tyres"

    def warmup(self) -> None:
        return None

    def transcribe(self, clip: AudioClip, prompt: str | None = None) -> SttResult:
        return SttResult(self.next_text, self.name, 3, clip.duration_s)


class ToneTts:
    name = "tone"
    sample_rate = 22_050

    def synthesize(self, text: str) -> AudioClip:
        return AudioClip(b"\x10\x00" * 40_000, self.sample_rate)  # ~1.8 s, > one 16 KB chunk


def _recv_until(ws: Any, pred: Any, limit: int = 200) -> tuple[list[Any], Any]:
    seen: list[Any] = []
    for _ in range(limit):
        m = ws.receive()
        item: Any = m.get("bytes") if m.get("bytes") is not None else json.loads(m["text"])
        seen.append(item)
        if isinstance(item, dict) and pred(item):
            return seen, item
    raise AssertionError(f"condition not met; got {seen[-5:]}")


@pytest.fixture
def app_with_session(tmp_path: Path) -> Any:
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
        rt.start_replay(cap, speed=None).done.wait(60)
        rt.worker.join()
        rt.writer.flush()
        app.state.hub.stt = ScriptedStt()
        app.state.hub.tts = ToneTts()
        # The replay leaves its last lap summary and coaching point queued (45 s to live). Once the live connection
        # is stale (2 s after the replay's last packet: a slower machine such as the Windows CI runner gets there),
        # the radio says them as soon as a client connects; a push-to-talk then is a barge-in whose 0.15 s gate
        # drops the audio these tests send all at once, and no transcript ever comes. These tests are about
        # questions, so proactive messages are held (quiet mode; answers and controls are not affected).
        app.state.hub.scheduler.set_quiet(indefinite=True)
        yield app, client


def test_radio_question_over_websocket(app_with_session: Any) -> None:
    _app, client = app_with_session
    with client.websocket_connect("/ws/radio") as ws:
        first = json.loads(ws.receive()["text"])
        assert first["type"] == "state" and first["stt"] == "scripted"
        ws.send_text(json.dumps({"type": "hello", "client": "test-ipad", "sample_rate": 16000, "version": 1}))
        ws.send_text(json.dumps({"type": "ptt", "down": True}))
        ws.send_bytes(b"\x00\x01" * 16_000)  # 1 s of audio
        ws.send_text(json.dumps({"type": "ptt", "down": False}))
        _seen, transcript = _recv_until(ws, lambda m: m.get("type") == "transcript")
        assert transcript["text"] == "how are my tyres" and transcript["audio_s"] == pytest.approx(1.0)
        _seen, say = _recv_until(ws, lambda m: m.get("type") == "say" and m.get("kind") == "answer")
        assert "most worn" in say["text"] and say["n_bytes"] == 80_000 and say["sample_rate"] == 22_050
        audio: list[bytes] = []
        while True:
            m = ws.receive()
            if m.get("bytes") is not None:
                audio.append(m["bytes"])
                continue
            end = json.loads(m["text"])
            if end.get("type") == "say_end":
                break
        assert end["id"] == say["id"] and sum(map(len, audio)) == 80_000 and len(audio) >= 2
        ws.send_text(json.dumps({"type": "playback", "id": say["id"], "state": "started"}))
        ws.send_text(json.dumps({"type": "playback", "id": say["id"], "state": "ended"}))
        ws.send_text(json.dumps({"type": "ping", "t": 1.5}))
        _, pong = _recv_until(ws, lambda m: m.get("type") == "pong")
        assert pong["t"] == 1.5
    status = client.get("/api/voice/status").json()
    # latency[0] is the newest spoken message: a proactive one (lap summary, coaching) spoken after the answer can
    # come first, so check the question's own record
    question = next(r for r in status["latency"] if r["kind"] == "question")
    assert status["enabled"] and question["stt_ms"] == 3


def test_radio_typed_question_and_quiet_command(app_with_session: Any) -> None:
    _app, client = app_with_session
    with client.websocket_connect("/ws/radio") as ws:
        ws.receive()
        ws.send_text(json.dumps({"type": "ask", "text": "stop talking for a few laps"}))
        _, say = _recv_until(ws, lambda m: m.get("type") == "say")
        assert say["kind"] == "control" and "quiet" in say["text"].lower()


def test_radio_requires_auth_for_lan_clients(tmp_path: Path) -> None:
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
    with TestClient(app, client=("192.168.1.77", 5000)) as c:
        with pytest.raises(WebSocketDisconnect) as exc, c.websocket_connect("/ws/radio") as ws:
            ws.receive()
        assert exc.value.code == 4401
        with c.websocket_connect("/ws/radio?token=tok") as ws:
            assert json.loads(ws.receive()["text"])["type"] == "state"


def test_voice_say_and_ask_accept_a_json_body(app_with_session: Any) -> None:
    """Regression: SayRequest was defined inside create_app, so FastAPI read ``body`` as a query param (422)."""
    _app, client = app_with_session
    r = client.post("/api/voice/say", json={"text": "Radio check"})
    assert r.status_code == 200 and r.json()["clients"] == 0
    assert client.post("/api/voice/ask", json={"text": "how are my tyres"}).json() == {"queued": True}
    assert client.post("/api/voice/say", json={"text": ""}).status_code == 422  # validation still applies
