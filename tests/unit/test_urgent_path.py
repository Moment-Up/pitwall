"""The v0.3.0 urgent path: ONE interrupt rule (``voice.scheduler.may_interrupt``) for the race radio's red flag and
the spotter. Spotter calls, the red flag and a puncture may interrupt anything except another urgent call (so neither
cuts the other); a spotter clear never cuts a braking cue; nothing else interrupts (a braking cue plays on a free radio
only; race calls, car health, lap summaries wait for the budget and a speak window). The hub's urgent slot and cue
gate, the scheduler's queue and ``voice.spotter_radio`` all decide with it."""

from __future__ import annotations

import time

from pitwall.coach.cues import CueEvent, CueKind, CueSpec
from pitwall.voice.hub import RadioHub
from pitwall.voice.scheduler import YIELDS_TO_CUE_KEY, RadioScheduler, interrupt_rank, may_interrupt
from pitwall.voice.spotter_radio import _PROBE_CLEAR, _PROBE_HIGH, _PROBE_URGENT
from pitwall.voice.types import AudioClip, DrivingState, MessageKind, Priority, RadioMessage
from pitwall.voice.urgent import URGENT_NOTE, urgent_message
from tests.unit.test_hub_race_calls import URGENT, make, says, until

NOW = 100.0
RED = urgent_message(URGENT, NOW)  # the red flag as the hub queues it (voice.urgent)


def _m(kind: MessageKind, prio: Priority = Priority.NORMAL, **meta: object) -> RadioMessage:
    return RadioMessage(f"{kind}-{prio}", kind, prio, "x", "x", NOW, needs_speak_window=False, meta=dict(meta))


ONSET = _m(MessageKind.SPOTTER, Priority.URGENT, phrase="car_left")
CLEAR = _m(MessageKind.SPOTTER, Priority.URGENT, phrase="clear_left", **{YIELDS_TO_CUE_KEY: True})
STILL = _m(MessageKind.SPOTTER, Priority.HIGH, phrase="still_there_left", **{YIELDS_TO_CUE_KEY: True})
CUE = _m(MessageKind.CUE, Priority.HIGH)
SUMMARY = _m(MessageKind.LAP_SUMMARY)
RACE = _m(MessageKind.RACE)  # a race call ("Up to P5.")
HEALTH = _m(MessageKind.STRATEGY)  # a car health call ("Tyres are cold.") at normal level
ANSWER = _m(MessageKind.ANSWER, Priority.HIGH)


def test_the_red_flag_and_spotter_calls_cut_anything_but_each_other() -> None:
    assert RED.priority is Priority.URGENT and interrupt_rank(RED) == interrupt_rank(ONSET) == 2
    for urgent in (RED, ONSET, CLEAR):
        for other in (SUMMARY, RACE, HEALTH, ANSWER, STILL):
            assert may_interrupt(urgent, other), (urgent.kind, other.kind)
        for other in (RED, ONSET, CLEAR):
            assert not may_interrupt(urgent, other), (urgent.meta, other.meta)  # never another urgent call
    assert may_interrupt(RED, CUE) and may_interrupt(ONSET, CUE)


def test_the_braking_point_rules_and_everything_else_never_interrupts() -> None:
    assert not may_interrupt(CLEAR, CUE)  # a clear waits for the braking cue
    for on_air in (CLEAR, STILL, SUMMARY, RACE, HEALTH):
        assert may_interrupt(CUE, on_air), on_air.meta  # a cue cuts routine talk and a spotter clear / still there
    for on_air in (ONSET, RED, ANSWER, CUE):
        assert not may_interrupt(CUE, on_air), on_air.meta  # never a car call, an urgent call, an answer or a cue
    for quiet in (SUMMARY, RACE, HEALTH, STILL):
        for on_air in (None, SUMMARY, RACE, HEALTH, ANSWER, CUE):
            assert not may_interrupt(quiet, on_air), (quiet.kind, on_air)


def test_the_spotters_probes_are_the_rules_messages() -> None:
    """voice.spotter_radio decides with the same rule through stand-in messages: an onset and a clear never cut the
    red flag, a clear never cuts a cue, a still there never cuts anything."""
    assert not may_interrupt(_PROBE_URGENT, RED) and not may_interrupt(_PROBE_CLEAR, RED)
    assert may_interrupt(_PROBE_URGENT, CUE) and not may_interrupt(_PROBE_CLEAR, CUE)
    assert not may_interrupt(_PROBE_HIGH, SUMMARY)
    assert may_interrupt(RED, STILL) and not may_interrupt(RED, ONSET)


def test_while_speaking_the_queue_hands_out_only_the_urgent_call() -> None:
    s = RadioScheduler("normal", min_gap_s=0.0)
    on_track = DrivingState(True, 200.0, 0.0, 0.0, 3, 500.0, 5.0)
    s.enqueue(RadioMessage("sum", MessageKind.LAP_SUMMARY, Priority.NORMAL, "Lap 3, 1:30.1.", "Lap 3.", NOW))
    s.enqueue(RadioMessage("race", MessageKind.RACE, Priority.NORMAL, "Up to P5.", "Up to P 5.", NOW))
    first = s.next_message(DrivingState(False, None, None, None, 3, None, None), NOW, False)
    assert first is not None and first.id == "sum"  # off track: a free radio says the queue in order
    s.enqueue(RED)
    got = s.next_message(on_track, NOW + 0.1, True)  # the summary is on air: only what outranks it
    assert got is not None and got.id == RED.id
    assert s.next_message(on_track, NOW + 0.2, True) is None  # the race call waits for a free radio


def _cue() -> CueEvent:
    spec = CueSpec("T1", CueKind.BRAKE, 1000.0, "T1 brake", ("T1", "brake"), 1)
    return CueEvent(1, spec, 3, 3, time.monotonic(), None, 900.0, 80.0, 1.25, 0.25, 0.3, "device", 995.0, 12)


def _on_air(hub: RadioHub, msg: RadioMessage) -> None:
    hub._deliver(msg, AudioClip(b"\x01\x00" * 44_100, 22_050), None, None)  # 2 s on air
    assert hub.speaking_id == msg.id


async def test_the_hubs_cue_gate_asks_the_same_rule() -> None:
    hub, _client, _sent = await make()
    for msg, reason in (
        (CLEAR, None),  # a braking call cuts a clear or a "still there"
        (STILL, None),
        (ONSET, "spotter call on air"),
        (SUMMARY, None),  # and routine talk
        (RACE, None),
        (ANSWER, "answer on air"),
    ):
        _on_air(hub, msg)
        assert hub._cue_block_reason(_cue(), time.monotonic()) == reason, msg.meta
    _on_air(hub, RED)
    assert hub._cue_block_reason(_cue(), time.monotonic()) == "urgent message on air"
    await hub.stop()


async def test_a_red_flag_waits_for_a_spotter_call_on_air_then_goes_at_once() -> None:
    hub, client, sent = await make()
    spot = RadioMessage(
        "spot1", MessageKind.SPOTTER, Priority.URGENT, "Car left.", "Car left.", time.monotonic(), meta={"phrase": "x"}
    )
    _on_air(hub, spot)
    assert not hub._urgent_may_cut(RED)
    hub.live.notify(URGENT_NOTE, URGENT)
    await until(lambda: hub._held_urgent is not None)
    assert says(sent, "alert") == [] and hub.speaking_id == "spot1"  # never cut: equal ranks
    assert not any(isinstance(m, dict) and m.get("type") == "cancel" for _t, m in sent)
    await hub.on_text(client, {"type": "playback", "id": "spot1", "state": "ended"})
    await until(lambda: says(sent, "alert"))
    assert [m["id"] for m in says(sent, "alert")] == ["urgent-rc-9-4"]
    await hub.stop()


async def test_a_red_flag_cuts_a_race_call_on_air() -> None:
    hub, _client, sent = await make()
    race = RadioMessage("race1", MessageKind.RACE, Priority.NORMAL, "Up to P5.", "Up to P 5.", time.monotonic())
    _on_air(hub, race)
    assert hub._urgent_may_cut(RED)
    hub.live.notify(URGENT_NOTE, URGENT)
    await until(lambda: says(sent, "alert"))
    assert any(isinstance(m, dict) and m.get("type") == "cancel" and m["id"] == "race1" for _t, m in sent)
    await hub.stop()
