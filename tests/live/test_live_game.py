"""Live validation against a running game (manual; excluded by default).

Run while the game streams UDP telemetry to this machine:

    uv run pytest -m live tests/live -s

See docs/validation.md for the full console checklist. Passing this on a given platform is what allows the
capability matrix to say 'live_validated' for that platform.
"""

from __future__ import annotations

import os
import socket
import time

import pytest

from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.model.telemetry import CarFrame, SessionInfo

pytestmark = pytest.mark.live
PORT = int(os.environ.get("PITWALL_F1_UDP_PORT", "20777"))


def test_receives_and_decodes_live_f1_telemetry() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", PORT))
    sock.settimeout(1.0)
    a = F1Adapter()
    frames: list[CarFrame] = []
    info: SessionInfo | None = None
    deadline = time.time() + 60
    while time.time() < deadline and (len(frames) < 600 or info is None):
        try:
            data, _ = sock.recvfrom(2048)
        except TimeoutError:
            continue
        for e in a.decode(data, time.monotonic_ns()):
            if isinstance(e, CarFrame):
                frames.append(e)
            elif isinstance(e, SessionInfo):
                info = e
    sock.close()
    assert frames, f"no F1 telemetry received on UDP {PORT} within 60 s - check the in-game UDP settings"
    assert info is not None, "no Session packet received"
    assert a.stats.rejected == 0 and a.stats.errors == 0, a.stats
    moving = [f for f in frames if (f.speed_kph or 0) > 30]
    assert moving, "drive the car during the test"
    print(
        f"\nOK: {info.track_name}, {info.session_type_raw}, platform={info.platform.value}, "
        f"format={info.extra.get('packet_format')}, version={info.extra.get('game_version')}, "
        f"{len(frames)} frames, {a.stats.packets} packets"
    )
