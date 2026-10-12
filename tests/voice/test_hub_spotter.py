"""The radio hub's spotter path (voice.spotter_radio): the cut matrix, the mailbox, heard pairing, device-voice PCM,
mutes, the state frame and the latency stamps. Fake TTS / STT / clients; no real audio."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

import pytest

from pitwall.ai.engineer import RaceEngineer
from pitwall.compat import recv_clock_ns
from pitwall.core.live import LiveState
from pitwall.spotter.model import SpotterCall, SpotterState
from pitwall.spotter.settings import SpotterSettings
from pitwall.spotter.worker import SpotterWorker
from pitwall.voice.hub import RESENT_KEY, RadioClient, RadioHub
from pitwall.voice.types import AudioClip, MessageKind, Priority, RadioMessage
from tests.unit.test_voice_hub import FakeScheduler, FakeStt, FakeTts, settle, sheet, texts

ON = SpotterSettings(enabled=True)
CLIP = AudioClip(b"\x01\x00" * 22_050, 22_050)  # 1 s of something on air


class LoudTts(FakeTts):
    """Speech-like audio: silence, then 0.4 s above the trim threshold, then silence (trimmed to 0.42 s)."""

    def synthesize(self, text: str) -> AudioClip:
        sr = self.sample_rate
        pcm = b"\x00\x00" * int(0.1 * sr) + b"\x00\x10" * int(0.4 * sr) + b"\x00\x00" * int(0.1 * sr)
        return AudioClip(pcm, sr)


@dataclass
class Origin:
    """Stands in for the worker that made a call (validity checks)."""

    st: SpotterState

    def state(self) -> SpotterState:
        return self.st


async def _hub(device_tts: bool = False, n_clients: int = 1) -> tuple[RadioHub, list[list[Any]], SpotterWorker]:
    hub = RadioHub(LiveState(), RaceEngineer(None), FakeStt(), LoudTts(), FakeScheduler(), sheet, lambda s: s)
    hub.start()
    assert hub._tick_task is not None
    hub._tick_task.cancel()  # the tests drive the radio themselves
    outs: list[list[Any]] = []
    for _ in range(n_clients):
        sent: list[Any] = []

        async def send(item: Any, sent: list[Any] = sent) -> None:
            sent.append(item)

        c = RadioClient(send=send, device_tts=device_tts)
        await hub.connect(c)
        outs.append(sent)
    w = SpotterWorker(hub.live, ON, start=False)
    hub.attach_spotter(w)
    await settle(30)  # phrase audio built
    assert hub.spotter.audio.ready()
    return hub, outs, w


def _call(kind: str, side: str | None, seq: int, origin: Origin, epoch: int = 1, age_s: float = 0.0) -> SpotterCall:
    now = recv_clock_ns() - int(age_s * 1e9)
    return SpotterCall(kind, side, seq, epoch, 10.0, now - 2_000_000, now, 50.0, origin=origin)  # type: ignore[arg-type]


def _state(left: bool = False, right: bool = False, seq: tuple[int, int] = (0, 0), epoch: int = 1) -> SpotterState:
    return SpotterState(True, (left, right), (left, right), seq, epoch, left or right)


async def said(sent: list[Any]) -> list[dict[str, Any]]:
    """The spotter's say frames the client has received so far (its pump runs on the loop)."""
    await settle(3)
    return [m for m in texts(sent, "say") if m["kind"] == "spotter"]


async def test_an_idle_radio_plays_the_call_at_once_with_pcm_and_meta() -> None:
    hub, (sent,), _w = await _hub()
    o = Origin(_state(left=True))
    assert hub.spotter.deliver(_call("car_left", "left", 1, o)) is None
    await settle(5)
    (say,) = await said(sent)
    assert say["text"] == "Car left." and say["meta"] == {"spotter": "car_left", "side": "left", "seq": 1}
    assert say["n_bytes"] > 0 and hub.speaking_id == say["id"]
    assert sum(len(b) for b in sent if isinstance(b, bytes)) == say["n_bytes"]
    assert hub.spotter.heard == [True, False]
    assert hub.spotter.queued_ms.summary()["n"] == 1
    await hub.stop()


@pytest.mark.parametrize(
    ("kind", "prio", "reheld"),
    [
        (MessageKind.LAP_SUMMARY, Priority.NORMAL, True),
        (MessageKind.ANSWER, Priority.HIGH, True),
        (MessageKind.CONTROL, Priority.HIGH, True),
        (MessageKind.CUE, Priority.HIGH, False),
    ],
)
async def test_the_cut_matrix(kind: MessageKind, prio: Priority, reheld: bool) -> None:
    hub, (sent,), _w = await _hub()
    on_air = RadioMessage("m900", kind, prio, "On air.", "On air.", 0.0, needs_speak_window=False)
    hub._deliver(on_air, CLIP, None, None)
    assert hub.speaking_id == "m900"
    assert hub.spotter.deliver(_call("car_left", "left", 1, Origin(_state(left=True)))) is None
    await settle(3)
    assert any(m.get("type") == "cancel" and m.get("id") == "m900" for m in sent if isinstance(m, dict))
    if reheld:
        assert hub._held is not None and hub._held[0].text == "On air." and hub._held[0].meta[RESENT_KEY] == 1
    else:
        assert hub._held is None
    await hub.stop()


async def test_a_message_cut_twice_is_not_said_a_third_time() -> None:
    hub, _outs, _w = await _hub()
    msg = RadioMessage("m901", MessageKind.LAP_SUMMARY, Priority.NORMAL, "Lap.", "Lap.", 0.0, meta={RESENT_KEY: 1})
    hub._deliver(msg, CLIP, None, None)
    hub.spotter.deliver(_call("car_left", "left", 1, Origin(_state(left=True))))
    assert hub._held is None
    await hub.stop()


async def test_urgent_and_spotter_calls_never_cut_each_other_the_mailbox_keeps_the_latest() -> None:
    hub, (sent,), _w = await _hub()
    alert = RadioMessage("m950", MessageKind.ALERT, Priority.URGENT, "Red flag.", "Red flag.", 0.0)
    hub._deliver(alert, CLIP, None, None)
    o = Origin(_state(left=True, right=True, seq=(2, 3)))
    assert hub.spotter.deliver(_call("car_left", "left", 2, o)) == "urgent_on_air"
    assert hub.spotter.deliver(_call("car_right", "right", 3, o)) == "urgent_on_air"
    assert (await said(sent)) == [] and hub.speaking_id == "m950"
    assert hub.spotter.dropped["urgent_on_air"] == 1  # the older call was replaced
    await hub.on_text(next(iter(hub.clients)), {"type": "playback", "id": "m950", "state": "ended"})
    (say,) = await said(sent)
    assert say["meta"]["spotter"] == "car_right"
    # a spotter call on air: the next one waits for it
    o.st = _state(left=True, right=True, seq=(4, 3))
    assert hub.spotter.deliver(_call("car_left", "left", 4, o)) == "spotter_on_air"
    await hub.on_text(next(iter(hub.clients)), {"type": "playback", "id": say["id"], "state": "ended"})
    assert [m["meta"]["spotter"] for m in (await said(sent))] == ["car_right", "car_left"]
    await hub.stop()


async def test_still_there_never_cuts_anything() -> None:
    hub, (_sent,), _w = await _hub()
    o = Origin(_state(left=True, seq=(1, 0)))
    hub.spotter.deliver(_call("car_left", "left", 1, o))
    await hub.on_text(next(iter(hub.clients)), {"type": "playback", "id": hub.speaking_id, "state": "ended"})
    hub._deliver(RadioMessage("m960", MessageKind.LAP_SUMMARY, Priority.NORMAL, "Lap.", "Lap.", 0.0), CLIP, None, None)
    assert hub.spotter.deliver(_call("still_there", "left", 2, o)) == "radio_busy"
    assert hub.speaking_id == "m960"
    await hub.stop()


async def test_mailbox_validity_after_ptt_and_maximum_age() -> None:
    hub, (sent,), _w = await _hub()
    client = next(iter(hub.clients))
    o = Origin(_state(left=True, seq=(1, 0)))
    await hub.on_text(client, {"type": "ptt", "down": True})
    assert hub.spotter.deliver(_call("car_left", "left", 1, o)) == "ptt"
    await hub.on_text(client, {"type": "ptt", "down": False})  # released: still valid, said now
    assert [m["meta"]["spotter"] for m in (await said(sent))] == ["car_left"]
    await hub.on_text(client, {"type": "playback", "id": hub.speaking_id, "state": "ended"})
    # held too long (1 s max for a clear), or the car came back: dropped, counted under why it waited
    o.st = _state(seq=(2, 0))
    await hub.on_text(client, {"type": "ptt", "down": True})
    hub.spotter.deliver(_call("clear_left", "left", 2, o, age_s=1.2))
    await hub.on_text(client, {"type": "ptt", "down": False})
    assert len(await said(sent)) == 1 and hub.spotter.dropped["ptt"] == 1
    await hub.stop()


async def test_heard_pairing() -> None:
    hub, (sent,), _w = await _hub()
    client = next(iter(hub.clients))

    async def ended() -> None:
        if hub.speaking_id is not None:
            await hub.on_text(client, {"type": "playback", "id": hub.speaking_id, "state": "ended"})

    o = Origin(_state(seq=(0, 1)))
    assert hub.spotter.deliver(_call("clear_right", "right", 1, o)) == "not_heard"  # its onset was never heard
    o.st = _state(left=True, seq=(2, 1))
    assert hub.spotter.deliver(_call("still_there", "left", 2, o)) is None  # said as the onset
    assert (await said(sent))[-1]["text"] == "Car left." and hub.spotter.heard == [True, False]
    await ended()
    assert hub.spotter.deliver(_call("car_left", "left", 3, replace(o, st=_state(left=True, seq=(3, 1))))) == (
        "already_heard"
    )
    o.st = _state(seq=(4, 1))
    assert hub.spotter.deliver(_call("clear_left", "left", 4, o)) is None
    assert (await said(sent))[-1]["text"] == "Clear left." and hub.spotter.heard == [False, False]
    await ended()
    # a new engine epoch (a gate closed, a flashback): heard is forgotten
    o.st = _state(left=True, seq=(5, 1))
    hub.spotter.deliver(_call("car_left", "left", 5, o))
    await ended()
    o.st = _state(left=True, seq=(6, 1), epoch=2)
    assert hub.spotter.deliver(_call("car_left", "left", 6, o, epoch=2)) is None
    await hub.stop()


async def test_device_voice_clients_get_pcm_too_and_text_without_a_clip() -> None:
    hub, (sent,), _w = await _hub(device_tts=True)
    hub.spotter.deliver(_call("car_left", "left", 1, Origin(_state(left=True))))
    (say,) = await said(sent)
    assert say["n_bytes"] > 0 and not say.get("device_tts")
    await hub.on_text(next(iter(hub.clients)), {"type": "playback", "id": say["id"], "state": "ended"})
    hub.spotter.audio.clear()  # no clip: the device speaks the text with its own voice
    hub.spotter.deliver(_call("car_right", "right", 2, Origin(_state(right=True, seq=(1, 2)))))
    say2 = (await said(sent))[-1]
    assert say2["n_bytes"] == 0 and say2["device_tts"] and say2["speech"] == "Car right."
    await hub.stop()


async def test_a_pcm_radio_without_audio_drops_the_call() -> None:
    hub, (sent,), _w = await _hub()
    hub.spotter.audio.clear()
    assert hub.spotter.deliver(_call("car_left", "left", 1, Origin(_state(left=True)))) == "audio_not_ready"
    assert (await said(sent)) == [] and hub.speaking_id is None
    await hub.stop()


async def test_mutes_and_the_state_frame() -> None:
    hub, (sent,), w = await _hub()
    o = Origin(_state(left=True))
    state = hub.state()
    assert state["spotter"] == {"enabled": True, "audio_ready": True, "voice": None}
    hub.voice_enabled = False
    assert hub.spotter.deliver(_call("car_left", "left", 1, o)) == "voice_off"
    hub.voice_enabled = True
    w.apply_settings(SpotterSettings(enabled=True, audio=False))
    await hub._tick(1e9)
    assert hub.spotter.deliver(_call("car_left", "left", 1, o)) == "audio_off"
    w.apply_settings(SpotterSettings())
    await hub._tick(1e9)
    assert hub.spotter.deliver(_call("car_left", "left", 1, o)) == "disabled"
    assert hub.state()["spotter"]["enabled"] is False
    assert (await said(sent)) == []
    await hub.stop()


async def test_quiet_mode_does_not_mute_the_spotter() -> None:
    hub, (_sent,), _w = await _hub()
    hub.intensity = "quiet"
    hub.scheduler.set_quiet(None, True)
    assert hub.spotter.deliver(_call("car_left", "left", 1, Origin(_state(left=True)))) is None
    await hub.stop()


async def test_latency_stamps_and_ear_latency_feedback() -> None:
    hub, (_sent,), w = await _hub()
    client = next(iter(hub.clients))
    for i in range(3):
        o = Origin(_state(left=True, seq=(i + 1, 0)))
        hub.spotter.heard = [False, False]
        hub.spotter.deliver(_call("car_left", "left", i + 1, o))
        await hub.on_text(client, {"type": "playback", "id": hub.speaking_id, "state": "started"})
        await hub.on_text(client, {"type": "playback", "id": hub.speaking_id, "state": "ended"})
    lat = hub.spotter.latency()
    assert lat["n"] == 3 and lat["queued_ms"]["n"] == 3 and lat["started_ms"]["n"] == 3
    assert lat["queued_ms"]["p50"] >= 2.0  # t0 was 2 ms before the decision
    assert {"decide_ms", "onset_game_ms", "data_age_ms", "handoff_ms"} <= set(lat)
    assert w._ear_latency_s is not None and 0.1 <= w._ear_latency_s <= 1.0
    assert hub.spotter.recent[0]["started_ms"] is not None
    assert hub.spotter.recent[0]["side"] == "left"  # the settings card's diagnostics show the side
    await hub.stop()


async def test_traffic_holds_proactive_messages_only_while_on_and_active() -> None:
    hub, _outs, w = await _hub()
    assert hub.driving_state().traffic_alongside is None  # no live block yet
    hub.live.spotter = {"active": True, "traffic": True}
    assert hub.driving_state().traffic_alongside is True
    w.apply_settings(SpotterSettings())
    await hub._tick(1e9)
    assert hub.driving_state().traffic_alongside is None
    await hub.stop()


async def test_the_test_button_path() -> None:
    hub, (sent,), _w = await _hub()
    hub.spotter.heard = [True, False]  # a real episode is not disturbed
    hub.spotter.test()
    await settle(5)
    assert [m["meta"]["spotter"] for m in (await said(sent))] == ["car_left"]
    assert (await said(sent))[0]["meta"]["test"] is True and hub.spotter.heard == [True, False]
    await hub.stop()
