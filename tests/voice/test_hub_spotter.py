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
    assert say["text"] == "Car left." and say["meta"] == {
        "spotter": "car_left",
        "side": "left",
        "seq": 1,
        "phrase": "car_left",
    }
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
    # the car came back while the driver transmitted: the held clear is dropped (counted under why it waited) and
    # nothing is said (the driver already believes a car is there)
    o.st = _state(left=True, seq=(3, 0))
    await hub.on_text(client, {"type": "ptt", "down": True})
    hub.spotter.deliver(_call("clear_left", "left", 2, o))
    await hub.on_text(client, {"type": "ptt", "down": False})
    assert len(await said(sent)) == 1 and hub.spotter.dropped["ptt"] == 1
    # held longer than a clear may wait (1 s): said as the side is now (the resync), not dropped
    o.st = _state(seq=(4, 0))
    await hub.on_text(client, {"type": "ptt", "down": True})
    hub.spotter.deliver(_call("clear_left", "left", 4, o, age_s=1.2))
    await hub.on_text(client, {"type": "ptt", "down": False})
    assert [m["text"] for m in await said(sent)] == ["Car left.", "Clear left."]
    assert hub.spotter.dropped["ptt"] == 1 and hub.spotter.resynced == 1 and hub.spotter.heard == [False, False]
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


# --- review (radio feel): a call lost in the mailbox or through a transmission must not leave the driver wrong ---
async def test_a_clear_lost_while_the_driver_transmits_is_said_after_ptt() -> None:
    """Recorded on the owner's Melbourne F2 race: a clear held through PTT was replaced by a car on the other side
    that came and went; the driver kept "car right" for 12 s and the next real "car right" was dropped."""
    hub, (sent,), _w = await _hub()
    client = next(iter(hub.clients))
    o = Origin(_state(right=True, seq=(0, 1)))
    hub.spotter.deliver(_call("car_right", "right", 1, o))
    await hub.on_text(client, {"type": "playback", "id": hub.speaking_id, "state": "ended"})
    await hub.on_text(client, {"type": "ptt", "down": True})
    o.st = _state(seq=(0, 2))
    assert hub.spotter.deliver(_call("clear_right", "right", 2, o)) == "ptt"
    o.st = _state(left=True, seq=(3, 2))
    hub.spotter.deliver(_call("car_left", "left", 3, o))  # replaces the clear in the mailbox
    o.st = _state(seq=(4, 2))
    hub.spotter.deliver(_call("clear_left", "left", 4, o))  # the left car went before PTT up
    await hub.on_text(client, {"type": "ptt", "down": False})
    await hub._tick(1e9)
    await settle(5)
    assert [m["text"] for m in await said(sent)] == ["Car right.", "Clear right."]
    assert hub.spotter.heard == [False, False]
    await hub.stop()


async def test_an_onset_replaced_in_the_mailbox_is_said_when_the_radio_frees() -> None:
    """Recorded: "Car on your right" on air, three wide decided, then hold your line (right) replaced it: the left
    car (close) was never called and its later episodes were silent."""
    hub, (sent,), _w = await _hub()
    client = next(iter(hub.clients))
    o = Origin(_state(right=True, seq=(0, 1)))
    hub.spotter.deliver(_call("car_right", "right", 1, o))
    o.st = _state(left=True, right=True, seq=(2, 2))
    assert hub.spotter.deliver(_call("three_wide", None, 2, o)) == "spotter_on_air"
    o.st = _state(left=True, right=True, seq=(2, 3))
    hub.spotter.deliver(_call("hold_your_line", "right", 3, o))
    for _ in range(2):
        await hub.on_text(client, {"type": "playback", "id": hub.speaking_id, "state": "ended"})
        await hub._tick(1e9)
        await settle(5)
    kinds = [m["meta"]["spotter"] for m in await said(sent)]
    assert kinds[0] == "car_right" and ("three_wide" in kinds or "car_left" in kinds)
    assert hub.spotter.heard == [True, True]
    await hub.stop()


async def test_hold_your_line_for_a_side_not_heard_is_said_as_its_onset() -> None:
    hub, (sent,), _w = await _hub()
    o = Origin(_state(left=True, seq=(1, 0)))
    assert hub.spotter.deliver(_call("hold_your_line", "left", 1, o)) is None
    assert (await said(sent))[-1]["text"] == "Car left." and hub.spotter.heard == [True, False]
    await hub.stop()


# --- review (correctness): a clear dropped behind a long clip, the mailbox order, clears and braking cues ---
async def test_a_clear_too_old_behind_three_wide_is_said_and_the_next_car_on_that_side_is_called() -> None:
    """Recorded on the committed Monza excerpt: "Car left", "Three wide" (1.6 s), "Clear left" decided 0.55 s into
    it and 1.57 s old when it ended: dropped, so the driver kept the left car and a new one there was "already
    heard". Now the side is said as it is when the radio frees, and the next car on the left is called."""
    hub, (sent,), _w = await _hub()
    client = next(iter(hub.clients))

    async def ended() -> None:
        await hub.on_text(client, {"type": "playback", "id": hub.speaking_id, "state": "ended"})

    o = Origin(_state(left=True, seq=(1, 0)))
    hub.spotter.deliver(_call("car_left", "left", 1, o))
    await ended()
    o.st = _state(left=True, right=True, seq=(2, 2))
    assert hub.spotter.deliver(_call("three_wide", None, 2, o)) is None
    o.st = SpotterState(True, (False, True), (False, True), (3, 2), 1, True)
    assert hub.spotter.deliver(_call("clear_left", "left", 3, o, age_s=1.2)) == "spotter_on_air"
    await ended()  # the held clear is too old: dropped, then said as the side is now
    assert [m["text"] for m in await said(sent)] == ["Car left.", "Three wide.", "Clear left."]
    assert hub.spotter.heard == [False, True] and hub.spotter.resynced == 1
    await ended()
    o.st = SpotterState(True, (True, True), (True, True), (4, 2), 1, True)
    assert hub.spotter.deliver(_call("car_left", "left", 4, o)) is None  # spoken, not "already heard"
    assert (await said(sent))[-1]["text"] == "Car left."
    await hub.stop()


async def test_a_held_onset_is_not_pushed_out_by_a_clear_the_clear_follows() -> None:
    hub, (sent,), _w = await _hub()
    client = next(iter(hub.clients))
    o = Origin(_state(right=True, seq=(0, 1)))
    hub.spotter.deliver(_call("car_right", "right", 1, o))
    await hub.on_text(client, {"type": "playback", "id": hub.speaking_id, "state": "ended"})
    alert = RadioMessage("m970", MessageKind.ALERT, Priority.URGENT, "Red flag.", "Red flag.", 0.0)
    hub._deliver(alert, CLIP, None, None)
    o.st = _state(left=True, right=True, seq=(2, 1))
    assert hub.spotter.deliver(_call("car_left", "left", 2, o)) == "urgent_on_air"
    o.st = SpotterState(True, (True, False), (True, False), (2, 3), 1, True)
    hub.spotter.deliver(_call("clear_right", "right", 3, o))  # matters less than the held onset: not replaced
    assert hub.spotter._mailbox is not None and hub.spotter._mailbox.kind == "car_left"
    await hub.on_text(client, {"type": "playback", "id": "m970", "state": "ended"})
    assert [m["text"] for m in await said(sent)] == ["Car right.", "Car left."]
    await hub.on_text(client, {"type": "playback", "id": hub.speaking_id, "state": "ended"})
    assert [m["text"] for m in await said(sent)][-1] == "Clear right." and hub.spotter.heard == [True, False]
    await hub.stop()


async def test_a_clear_waits_for_a_braking_cue_an_onset_cuts_it() -> None:
    hub, (sent,), _w = await _hub()
    client = next(iter(hub.clients))
    o = Origin(_state(left=True, seq=(1, 0)))
    hub.spotter.deliver(_call("car_left", "left", 1, o))
    await hub.on_text(client, {"type": "playback", "id": hub.speaking_id, "state": "ended"})
    cue = RadioMessage("m980", MessageKind.CUE, Priority.HIGH, "T2 brake", "brake", 0.0, needs_speak_window=False)
    hub._deliver(cue, CLIP, None, None)
    o.st = _state(seq=(2, 0))
    assert hub.spotter.deliver(_call("clear_left", "left", 2, o)) == "cue_on_air"
    assert hub.speaking_id == "m980"  # the cue plays on
    await hub.on_text(client, {"type": "playback", "id": "m980", "state": "ended"})
    assert [m["text"] for m in await said(sent)] == ["Car left.", "Clear left."]
    await hub.on_text(client, {"type": "playback", "id": hub.speaking_id, "state": "ended"})
    hub._deliver(replace(cue, id="m981"), CLIP, None, None)
    o.st = _state(right=True, seq=(2, 3))
    assert hub.spotter.deliver(_call("car_right", "right", 3, o)) is None  # a car arriving cuts the cue
    assert hub.speaking_id != "m981"
    await hub.stop()


async def test_a_braking_cue_never_cuts_a_car_call_but_cuts_a_clear() -> None:
    """The radio policy: a cue is dropped while a car arriving is on air, and cuts a clear (information about a car
    that has gone yields to the braking point); the cut clear is not said again."""
    from tests.unit.test_hub_validation_hooks import cue_event

    hub, (sent,), _w = await _hub(device_tts=True)
    client = next(iter(hub.clients))
    o = Origin(_state(left=True, seq=(1, 0)))
    hub.spotter.deliver(_call("car_left", "left", 1, o))
    ev = cue_event(1)
    assert hub.deliver_cue(ev, ev.fired_mono) == "spotter call on air"  # a car arriving: the cue is dropped
    await hub.on_text(client, {"type": "playback", "id": hub.speaking_id, "state": "ended"})
    o.st = _state(seq=(2, 0))
    assert hub.spotter.deliver(_call("clear_left", "left", 2, o)) is None
    clear_id = hub.speaking_id
    ev = cue_event(2)
    assert hub.deliver_cue(ev, ev.fired_mono) is None  # the cue cuts the clear
    await settle(3)
    assert hub.speaking_id != clear_id and hub._held is None  # a cut spotter call is never said later
    await hub.stop()


async def test_a_final_clear_is_said_after_the_engine_moved_on_but_not_after_a_newer_epoch() -> None:
    hub, (sent,), _w = await _hub()
    client = next(iter(hub.clients))
    o = Origin(_state(left=True, seq=(1, 0)))
    hub.spotter.deliver(_call("car_left", "left", 1, o))
    await hub.on_text(client, {"type": "playback", "id": hub.speaking_id, "state": "ended"})
    o.st = SpotterState(False, (False, False), (False, False), (0, 0), 2, False)  # the gate closed: epoch 2
    final = replace(_call("clear_left", "left", 2, o), final=True)
    assert hub.spotter.deliver(final) is None
    assert (await said(sent))[-1]["text"] == "Clear left." and hub.spotter.heard == [False, False]
    await hub.on_text(client, {"type": "playback", "id": hub.speaking_id, "state": "ended"})
    # a final clear of an older epoch than the radio has already heard from: stale
    o.st = _state(left=True, seq=(3, 0), epoch=3)
    hub.spotter.deliver(_call("car_left", "left", 3, o, epoch=3))
    late = replace(_call("clear_left", "left", 4, o, epoch=2), final=True)
    assert hub.spotter.deliver(late) == "stale"
    await hub.stop()


async def test_resync_waits_for_a_call_on_its_way_and_never_counts_a_drop_without_audio() -> None:
    hub, (sent,), _w = await _hub()
    client = next(iter(hub.clients))
    o = Origin(_state(left=True, seq=(1, 0)))
    hub.spotter.deliver(_call("car_left", "left", 1, o))
    await hub.on_text(client, {"type": "playback", "id": hub.speaking_id, "state": "ended"})
    o.st = _state(seq=(2, 0))  # the engine decided "clear left" (seq 2): not yet on the loop
    assert hub.spotter.resync() is None
    hub.spotter._seen_seq = 2  # it arrived (and was lost): the resync may speak now, but there is no audio
    hub.spotter.audio.clear()
    dropped = sum(hub.spotter.dropped.values())
    for _ in range(3):
        await hub._tick(1e9)
    assert hub.spotter.resync() is None and sum(hub.spotter.dropped.values()) == dropped
    assert len(await said(sent)) == 1
    await hub.stop()


async def test_a_car_arriving_cuts_still_there_and_a_held_clear_becomes_clear_all_round() -> None:
    """Recorded (radio simulated on the owner's races): "Still right." on air when a third car came alongside; and a
    clear of each side queued behind other calls, said one after the other 1.8 s after the first car had gone."""
    hub, (sent,), _w = await _hub()
    client = next(iter(hub.clients))

    async def ended() -> None:
        await hub.on_text(client, {"type": "playback", "id": hub.speaking_id, "state": "ended"})

    o = Origin(_state(right=True, seq=(0, 1)))
    hub.spotter.deliver(_call("car_right", "right", 1, o))
    await ended()
    hub.spotter.deliver(_call("still_there", "right", 2, replace(o, st=_state(right=True, seq=(0, 2)))))
    still_id = hub.speaking_id
    o.st = _state(left=True, right=True, seq=(3, 3))
    assert hub.spotter.deliver(_call("three_wide", None, 3, o)) is None  # cuts "Still right."
    await settle(3)
    assert any(isinstance(m, dict) and m.get("type") == "cancel" and m.get("id") == still_id for m in sent)
    # both cars go while "Three wide." plays: one clear held, the other decided later; one call covers both
    o.st = SpotterState(True, (True, False), (True, False), (3, 4), 1, True)
    assert hub.spotter.deliver(_call("clear_right", "right", 4, o)) == "spotter_on_air"
    o.st = SpotterState(True, (False, False), (False, False), (5, 4), 1, False)
    hub.spotter._seen_seq = 5  # the left clear was decided and lost (replaced) while the right one was held
    await ended()
    assert [m["text"] for m in await said(sent)] == ["Car right.", "Still right.", "Three wide.", "Clear all round."]
    assert hub.spotter.heard == [False, False]
    await hub.stop()
