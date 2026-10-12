"""RECORDED tier, lane handsfree (A2): real F1 25 button and motion data through the hands-free gates.

* The committed Melbourne and Austria excerpts carry real ``BUTN`` events (Right Stick Up/Down presses; no "UDP
  Action" is pressed in them, so the hub is pointed at the Right Stick bits as a stand-in for the wheel button).
  Replayed through ``LiveState`` into the radio hub with hands-free armed, every press keys push-to-talk and every
  release ends it, exactly as recorded, and a hands-free capture in progress is cut by the press. With the default
  UDP Action 1 mask none of these buttons keys the mic. (The owner's full races, scratch copies only, press UDP
  Action 1 itself: docs/research/handsfree.md, A2.)
* The excerpts' frames through the shipped ``MotionGate``: no frame above 8 km/h is ever classed stationary (unless
  the game flags it paused or replay), and the Melbourne grid before lights out is stationary.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.core.live import LiveState
from pitwall.ingest.capture import CaptureReader
from pitwall.model.telemetry import CarFrame, EventKind, FrameQuality, GameEvent
from pitwall.voice.handsfree import MOVE_ABOVE_KPH, MotionGate
from pitwall.voice.hub import UDP_ACTION_BASE, RadioClient, RadioHub
from tests.unit.test_voice_hub import FakeScheduler, FakeStt, FakeTts, RecordingEngineer, settle, sheet, texts

ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "recorded"
MELBOURNE = ROOT / "f1_25_2025_ps5_melbourne_race-start-excerpt.pwcap"
AUSTRIA = ROOT / "f1_25_2025_ps5_austria_race-excerpt.pwcap"
RIGHT_STICK = 0x00060000  # Right Stick Up | Down: the excerpts' pressed buttons (EA spec appendix: button flags)

pytestmark = [
    pytest.mark.recorded,
    pytest.mark.skipif(not (MELBOURNE.exists() and AUSTRIA.exists()), reason="real F1 25 excerpts not present"),
]


def decode(path: Path) -> tuple[list[int], list[CarFrame]]:
    reader = CaptureReader(path)
    assert not reader.meta.synthetic
    adapter = F1Adapter()
    buttons: list[int] = []
    frames: list[CarFrame] = []
    for pk in reader:
        for e in adapter.decode(pk.data, pk.t_recv_ns):
            if isinstance(e, GameEvent) and e.kind == EventKind.BUTTON:
                buttons.append(int(e.payload["buttonStatus"]))
            elif isinstance(e, CarFrame):
                frames.append(e)
    return buttons, frames


def edges(statuses: list[int], mask: int) -> tuple[int, int]:
    downs = ups = 0
    was = False
    for s in statuses:
        now = bool(s & mask)
        downs += now and not was
        ups += was and not now
        was = now
    return downs, ups


@pytest.mark.parametrize("path", [MELBOURNE, AUSTRIA], ids=["melbourne", "austria"])
async def test_real_button_events_key_push_to_talk_with_hands_free_armed(path: Path) -> None:
    statuses, _frames = decode(path)
    assert statuses and not any(s & (UDP_ACTION_BASE * 0xFFF) for s in statuses)  # no UDP Action in the excerpt
    want_downs, want_ups = edges(statuses, RIGHT_STICK)
    assert want_downs >= 2

    hub = RadioHub(LiveState(), RecordingEngineer(), FakeStt("fuel"), FakeTts(), FakeScheduler(), sheet, lambda s: s)
    hub.start()
    sent: list[Any] = []

    async def send(item: Any) -> None:
        sent.append(item)

    client = RadioClient(send=send)
    await hub.connect(client)
    await hub.on_text(client, {"type": "settings", "handsfree": True})
    hub.handsfree._hint_said = True  # keep the radio quiet: this test is about the button path
    assert hub.handsfree.active

    async def replay(mask: int) -> tuple[int, int, int, int]:
        hub.ptt_mask = mask
        hub._last_button_status = None
        downs = ups = mid_sentence = cut = 0
        seq = 0
        for status in statuses:
            was = hub.ptt_down
            if not was:
                await settle(3)  # the last question's answer is out: end its playback, as the device reports
                if hub.speaking_id is not None:
                    hub._on_playback(hub.speaking_id, "ended")
                hub._gate_until = 0.0
                if not hub.handsfree.capturing:
                    seq += 1  # the driver is mid-sentence hands-free when the press comes
                    await hub.on_text(client, {"type": "vad", "state": "start", "seq": seq})
            capturing = hub.handsfree.capturing
            hub.live.on_button(status)  # the session manager's call, as on the ingest thread
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            if hub.ptt_down and not was:
                downs += 1
                mid_sentence += capturing
                cut += capturing and not hub.handsfree.capturing
                assert hub.ptt_source == "wheel"
                hub.on_audio(client, b"\x10\x00" * 8000)
            elif was and not hub.ptt_down:
                ups += 1
        if hub.handsfree.capturing:
            await hub.on_text(client, {"type": "vad", "state": "abort", "seq": seq, "reason": "suppressed"})
        await settle(5)
        return downs, ups, mid_sentence, cut

    assert (await replay(UDP_ACTION_BASE))[:2] == (0, 0)  # the default wheel button is never pressed here
    downs, ups, mid_sentence, cut = await replay(RIGHT_STICK)
    assert (downs, ups) == (want_downs, want_ups)
    assert mid_sentence == want_downs and cut == mid_sentence  # every press cut the capture in progress
    assert sum(1 for m in texts(sent, "handsfree") if m.get("reason") == "ptt") == cut
    await hub.stop()


@pytest.mark.parametrize("path", [MELBOURNE, AUSTRIA], ids=["melbourne", "austria"])
def test_no_moving_frame_is_classed_stationary(path: Path) -> None:
    _statuses, frames = decode(path)
    gate = MotionGate()
    flagged = int(FrameQuality.PAUSED | FrameQuality.REPLAY_OR_SPECTATING)
    still = moving_fast = 0
    for f in frames:
        stationary = gate.update(f, True, f.t_recv_ns / 1e9)
        v = f.speed_kph
        if v is not None and v > MOVE_ABOVE_KPH and not int(f.quality) & flagged:
            moving_fast += 1
            assert not stationary, (f.lap_number, f.lap_distance_m, v)
        still += stationary
    assert moving_fast > 1000 and still > 0
    if path == MELBOURNE:  # the grid, before lights out: stationary from the first frames
        assert MotionGate().update(frames[0], True, 0.0)
        assert frames[0].speed_kph is not None and frames[0].speed_kph < 3
