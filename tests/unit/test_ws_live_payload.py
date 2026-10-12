"""/ws/live payload size (v0.2.0 plan 8.4 P2, ``api.live_feed``): a key the dashboard keeps goes only when it changed.

Race strategy's view (2-3.5 kB) goes when it changed, at most every ``STRATEGY_EVERY_S``; pace vs the AI, the coachref
block and the lap totals when they changed; the large static keys with the 5 s static payload only when they changed.
A new session's first snapshot carries everything. The dashboard keeps an absent key within the session
(``web-react/src/lib/live.ts`` ``STATIC_KEYS``)."""

from __future__ import annotations

import itertools
import time
from pathlib import Path
from typing import Any

import orjson
import pytest
from fastapi.testclient import TestClient

from pitwall.api import live_feed
from pitwall.api.app import create_app
from pitwall.api.live_feed import DIGEST_KEYS, FULL_EVERY_S, ON_CHANGE_KEYS, STATIC_EVERY_S, LiveFeed
from pitwall.config import Settings
from pitwall.core.live import LiveState


def _snapshots(ws: Any) -> Any:
    while True:
        msg = orjson.loads(ws.receive_bytes())
        if msg["type"] == "snapshot":
            yield dict(msg["data"])


def test_ai_pace_and_coachref_go_only_when_they_changed(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path, llm_enabled=False, voice_enabled=False), start_udp=False)
    with TestClient(app, client=("127.0.0.1", 40000)) as client:
        live = app.state.runtime.live
        live.reset_session("s1", "udp:20777", False)
        with client.websocket_connect("/ws/live") as ws:
            snaps = _snapshots(ws)
            first = next(snaps)
            assert all(k in first for k in ON_CHANGE_KEYS)  # the first snapshot carries them all
            live.version += 1  # a new frame, nothing else changed
            lean = next(snaps)
            assert not any(k in lean for k in ON_CHANGE_KEYS)
            pace = {"session_id": "s1", "status": "ok", "gap_s": 1.2}
            live.set_ai_pace("s1", pace)
            live.version += 1
            assert next(snaps)["ai_pace"] == pace
            live.version += 1
            assert "ai_pace" not in next(snaps)
            live.coachref = {"choice": {"kind": "own_best"}, "drill": None}  # CoachRef swaps the whole block
            assert next(snaps)["coachref"] == {"choice": {"kind": "own_best"}, "drill": None}  # sent without a frame
            live.reset_session("s2", "udp:20777", False)  # a new session: the client starts without kept keys
            fresh = next(snaps)
            assert fresh["session_id"] == "s2" and all(k in fresh for k in (*ON_CHANGE_KEYS, "strategy"))


def test_strategy_changes_go_at_most_every_strategy_every_s(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_feed, "STRATEGY_EVERY_S", 0.4)
    app = create_app(Settings(data_dir=tmp_path, llm_enabled=False, voice_enabled=False), start_udp=False)
    with TestClient(app, client=("127.0.0.1", 40000)) as client:
        live = app.state.runtime.live
        live.reset_session("s1", "udp:20777", False)
        with client.websocket_connect("/ws/live") as ws:
            snaps = _snapshots(ws)
            next(snaps)  # static: carries strategy (None)
            sent: list[float] = []
            for n in range(1, 7):
                live.set_strategy("s1", {"version": 1, "mode": "race", "session_id": "s1", "n": n})
                live.version += 1
                while True:
                    snap = next(snaps)
                    if "strategy" in snap:
                        sent.append(time.monotonic())
                        assert snap["strategy"]["n"] == n  # the newest view, never an older one
                        break
                    live.version += 1
            gaps = [b - a for a, b in itertools.pairwise(sent)]
            assert min(gaps) >= 0.4 - 0.06  # the event loop's sleep granularity


def test_the_static_payload_resends_large_keys_only_when_they_changed() -> None:
    """Paused or in the menus, the 5 s snapshot keeps the connection status current without resending 25 kB of track
    knowledge that did not change; a change, a new session and the one-minute safety net send it again."""
    live = LiveState()
    live.reset_session("s1", "udp:20777", False)
    live.skeleton = {"sector2_start_m": 1813.0}
    live.track_knowledge = {"corners": ["T1"] * 50}
    feed = LiveFeed()
    first = feed.next(live, 100.0)
    assert first is not None and all(k in first for k in (*DIGEST_KEYS, *ON_CHANGE_KEYS, "strategy"))
    assert feed.next(live, 100.05) is None  # nothing changed: nothing sent
    again = feed.next(live, 100.0 + STATIC_EVERY_S)
    assert again is not None and "last_comparison" in again  # the 5 s snapshot still goes (connection status)
    assert not any(k in again for k in DIGEST_KEYS) and "strategy" not in again
    live.track_knowledge = {"corners": ["T1"] * 51}  # learned something new
    moved = feed.next(live, 100.0 + 2 * STATIC_EVERY_S)
    assert moved is not None and moved["track_knowledge"] == {"corners": ["T1"] * 51} and "skeleton" not in moved
    full = feed.next(live, 100.0 + FULL_EVERY_S + 1.0)
    assert full is not None and all(k in full for k in DIGEST_KEYS)
    live.reset_session("s2", "udp:20777", False)
    fresh = feed.next(live, 100.0 + FULL_EVERY_S + 1.5)
    assert fresh is not None and fresh["session_id"] == "s2" and all(k in fresh for k in (*DIGEST_KEYS, "strategy"))
