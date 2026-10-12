"""What the driver would hear on a REAL capture: the committed Monza race-start excerpt through the engine, the worker
and the real ``SpotterRadio``, with a fake hub that plays each clip for a measured length (no audio, no device).

Recorded tier for the decisions, simulated for the playback: the clip lengths are the review's measurements (Kokoro
and ``say``: car left 0.45 s, a clear 0.5-0.75 s, "Three wide." 0.7 s, 0.2 s to start). The review found the driver
left believing a car that had gone: "Clear left" decided 0.55 s into the old 1.6 s three-wide clip, dropped as too
old, then "Still there", "Hold your line" and "Clear all round" 5.8 s later. Now the radio says what was missed when
it is free (resync), so within an episode the driver's belief never lags the spotter by a second or more.
"""

from __future__ import annotations

import itertools
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.core.session import SPOTTER_EVENTS
from pitwall.ingest.capture import CaptureReader
from pitwall.model.telemetry import FieldMotion, GameEvent, SessionInfo
from pitwall.spotter.model import LEFT, RIGHT
from pitwall.spotter.score import _f1_packets
from pitwall.spotter.settings import SpotterSettings
from pitwall.spotter.worker import SpotterWorker
from pitwall.voice import spotter_radio
from pitwall.voice.spotter_radio import SpotterRadio
from pitwall.voice.types import AudioClip, RadioMessage

pytestmark = pytest.mark.recorded

ROOT = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "recorded"
MONZA_START = ROOT / "f1_25_2025_ps5_monza_race-start-spotter-excerpt.pwcap"
CLIP_S = {
    "car_left": 0.45,
    "car_right": 0.5,
    "clear_left": 0.5,
    "clear_right": 0.55,
    "three_wide": 0.7,
    "clear_all_round": 0.75,
    "still_there_left": 0.5,
    "still_there_right": 0.5,
    "hold_your_line": 0.6,
}
START_S = 0.2


class _Hub:
    """The part of ``RadioHub`` the spotter radio uses: one radio, playback ends after the clip's length."""

    def __init__(self, now: list[int]) -> None:
        self.now = now
        self._loop = None
        self.clients = [SimpleNamespace(device_tts=False)]
        self.voice_enabled = True
        self.ptt_down = False
        self._ids = itertools.count(1)
        self._held = None
        self.coaching_limits = None
        self.tts = SimpleNamespace(name="kokoro")
        self.live = SimpleNamespace(spotter=None)
        self.speaking_id: str | None = None
        self._on_air: tuple[RadioMessage, Any] | None = None
        self.ends: list[tuple[int, str]] = []
        self.said: list[tuple[float, str]] = []

    def _on_air_message(self) -> tuple[RadioMessage, Any] | None:
        if self._on_air is None or self.speaking_id != self._on_air[0].id:
            return None
        return self._on_air

    def _deliver(self, msg: RadioMessage, clip: Any, _rec: Any, _released: Any, *, pcm_to_all: bool = False) -> None:
        self.speaking_id = msg.id
        self._on_air = (msg, clip)
        self.ends.append((self.now[0] + int((START_S + clip.duration_s) * 1e9), msg.id))
        self.said.append((self.now[0] / 1e9, msg.text))

    def _send_state(self) -> None:
        return None


def test_monza_race_start_the_driver_is_never_left_with_a_car_that_has_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    if not MONZA_START.exists():
        pytest.skip(f"{MONZA_START.name} not present")
    now = [0]
    monkeypatch.setattr(spotter_radio, "recv_clock_ns", lambda: now[0])
    hub = _Hub(now)
    radio = SpotterRadio(hub)  # type: ignore[arg-type]
    radio.settings = SpotterSettings(enabled=True)
    radio.audio.get = lambda pid, simple: AudioClip(b"\x01\x00" * int(CLIP_S[pid] * 22_050), 22_050)  # type: ignore[method-assign]
    worker = SpotterWorker(None, radio.settings, start=False, clock_ns=lambda: now[0], sink=radio.deliver)
    radio.worker = worker
    adapter = F1Adapter(field_hz=0.0, timing_hz=0.0, field_motion=True)
    stale_since: list[int | None] = [None, None]
    worst = 0.0
    next_tick = 0
    for pkt in _f1_packets(CaptureReader(MONZA_START)):
        now[0] = pkt.t_recv_ns
        for t_end, mid in sorted(hub.ends):
            if t_end <= now[0]:
                hub.ends.remove((t_end, mid))
                if hub.speaking_id == mid:
                    hub.speaking_id = None
                radio.on_playback(mid, "ended")
        if now[0] >= next_tick:  # the hub's 100 ms tick
            next_tick = now[0] + 100_000_000
            radio.release()
            radio.resync()
        items = adapter.decode(pkt.data, pkt.t_recv_ns)
        for e in items:
            if isinstance(e, FieldMotion | SessionInfo) or (isinstance(e, GameEvent) and e.kind in SPOTTER_EVENTS):
                worker.submit(e)
        worker.process_pending()
        eng = worker.engine
        same_episode = eng.active and radio._epoch == eng.state().epoch
        st = eng.state()
        for x in (LEFT, RIGHT):
            # the driver believes a car that has gone (cleared, nothing there), or has not heard one announced and there
            gone = radio.heard[x] and not st.announced[x] and not st.occupied[x]
            unheard = st.announced[x] and st.occupied[x] and not radio.heard[x]
            wrong = same_episode and (gone or unheard)
            if wrong and stale_since[x] is None:
                stale_since[x] = now[0]
            elif not wrong and stale_since[x] is not None:
                worst = max(worst, (now[0] - stale_since[x]) / 1e9)
                stale_since[x] = None
    texts = [t for _s, t in hub.said]
    assert "Three wide." in texts and "Car left." in texts
    assert worst < 1.0, (worst, hub.said)
    assert sum(worker.calls.values()) >= 6 and radio.dropped.get("already_heard", 0) == 0
