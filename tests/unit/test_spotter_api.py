"""``/api/spotter``: defaults Off, validation (422), persistence, the status payload and the test endpoint (409 when
the radio is off). No game, no real audio."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pitwall.config import Settings


def _app(tmp_path: Path, voice: bool = True) -> Any:
    from pitwall.api.app import create_app

    s = Settings(
        data_dir=tmp_path,
        llm_enabled=False,
        stt_engine="none",
        tts_engine="none",
        tailscale_trust_owner=False,
        access_token="tok",
        voice_enabled=voice,
    )
    return create_app(s, start_udp=False)


def test_get_defaults_put_persist_and_validate(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        body = c.get("/api/spotter").json()
        assert body["v"] == 1 and body["settings"]["enabled"] is False
        assert body["availability"] == {"available": True, "game": None, "reason": "no_motion"}
        st = body["status"]
        assert st["active"] is False and st["dims"]["width_m"] == 2.0 and st["send_rate_low"] is False
        assert st["reason"] == "disabled"
        assert set(body["latency"]) >= {"n", "decide_ms", "queued_ms", "started_ms", "onset_game_ms", "data_age_ms"}
        assert set(body["counters"]) >= {"calls", "suppressed_short", "dropped", "items", "skipped", "invalid"}
        r = c.put("/api/spotter/settings", json={"enabled": True, "start_delay_s": 3, "voice": "bm_george"})
        assert r.status_code == 200 and r.json()["settings"]["enabled"] is True
        assert r.json()["status"]["reason"] == "not_available"  # on, but no F1 Motion yet
        rt = app.state.runtime
        assert rt.spotter.settings.enabled and rt.spotter.settings.start_delay_s == 3.0
        saved = json.loads((tmp_path / "settings.json").read_text())["spotter"]
        assert saved["enabled"] is True and saved["voice"] == "bm_george"
        for bad in ({"enabled": "yes"}, {"volume": 1}, {"wording": "loud"}, {"car_length_m": 9}):
            assert c.put("/api/spotter/settings", json=bad).status_code == 422
        assert c.put("/api/spotter/settings", json={"voice": None}).json()["settings"]["voice"] is None
    app2 = _app(tmp_path)
    with TestClient(app2) as c:
        assert c.get("/api/spotter").json()["settings"]["start_delay_s"] == 3.0  # survives a restart


@pytest.mark.parametrize("voice", [True, False])
def test_the_test_endpoint_needs_a_radio(tmp_path: Path, voice: bool) -> None:
    app = _app(tmp_path, voice=voice)
    with TestClient(app) as c:
        r = c.post("/api/spotter/test")
        assert r.status_code == 409


def test_the_live_snapshot_carries_the_spotter_block(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        snap = c.get("/api/live").json()
        assert "spotter" in snap and snap["spotter"] is None  # no F1 Motion yet


def test_a_changed_spotter_block_is_sent_without_a_new_frame() -> None:
    """The worker swaps the block without bumping the version: when Motion stops (a pause) its last swap - the block
    going stale - must reach the iPad at once, not with the 5 s static payload (``api.live_feed``)."""
    from pitwall.api.live_feed import LiveFeed
    from pitwall.core.live import LiveState

    live = LiveState()
    live.reset_session("s1", "udp:20925", False)
    feed = LiveFeed()
    assert feed.next(live, 100.0) is not None  # the first (full) snapshot
    assert feed.next(live, 100.05) is None  # nothing changed: nothing sent
    side = {"state": "alongside", "lon_m": 1.0, "gap_m": 0.8, "cars": 1}
    clear = {"state": "clear", "lon_m": None, "gap_m": None, "cars": 0}
    block = {"v": 1, "enabled": True, "active": True, "reason": None, "left": side, "right": clear}
    live.spotter = block
    sent = feed.next(live, 100.1)
    assert sent is not None and sent["spotter"] == block
    assert feed.next(live, 100.15) is None  # the same block again: nothing new
    live.spotter = {**block, "active": False, "reason": "stale", "left": clear}
    stale = feed.next(live, 100.2)
    assert stale is not None and stale["spotter"]["reason"] == "stale"
