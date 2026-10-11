"""RECORDED tier: D4 ``session_state`` from a real F1 25 (PS5) race excerpt.

The Austria excerpt carries the game's own ``SSTA`` (session started), ``LGOT`` (lights out) and ``SEND``
(session ended) events; the live state must walk running -> running -> ended from them alone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.core.live import LiveState
from pitwall.ingest.capture import CaptureReader
from pitwall.model.telemetry import EventKind, GameEvent

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "recorded" / "f1_25_2025_ps5_austria_race-excerpt.pwcap"

pytestmark = [
    pytest.mark.recorded,
    pytest.mark.skipif(not FIXTURE.exists(), reason="real PS5 Austria excerpt not present"),
]


def test_session_state_follows_the_games_own_events() -> None:
    live = LiveState()
    live.reset_session("austria", "recorded", False)
    adapter = F1Adapter()
    seen: list[tuple[str, str | None]] = []
    for p in CaptureReader(FIXTURE):
        for e in adapter.decode(p.data, p.t_recv_ns):
            if isinstance(e, GameEvent) and e.kind is not EventKind.BUTTON:
                live.on_event(e)
                if e.kind.value in ("session_started", "lights_out", "session_ended", "red_flag", "chequered_flag"):
                    seen.append((e.kind.value, live.snapshot()["session_state"]))
    assert seen == [("session_started", "running"), ("lights_out", "running"), ("session_ended", "ended")]
    info = live.snapshot()["session_state_info"]
    assert info["cause"] == "session_ended" and info["state"] == "ended"
