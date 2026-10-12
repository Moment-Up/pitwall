"""The radio hub's race radio side: race_call notes through the driver's preferences, name addressing at dispatch,
and the urgent path end to end (another thread's notify -> a ``say`` frame in under 250 ms with an instant TTS)."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

from pitwall.ai.engineer import RaceEngineer
from pitwall.ai.facts import FactSheet
from pitwall.core.live import LiveState
from pitwall.drivers import Driver, DriverPreferences, RadioCallPrefs
from pitwall.voice.hub import RadioClient, RadioHub
from pitwall.voice.scheduler import RadioScheduler
from pitwall.voice.speech import to_speech
from pitwall.voice.types import AudioClip, MessageKind, Priority, RadioMessage
from pitwall.voice.urgent import URGENT_NOTE
from tests.unit.test_voice_hub import FakeStt, FakeTts


async def make(intensity: str = "normal") -> tuple[RadioHub, RadioClient, list[tuple[float, Any]]]:
    hub = RadioHub(
        LiveState(),
        RaceEngineer(None),
        FakeStt(),
        FakeTts(),
        RadioScheduler(intensity),
        fact_sheet=FactSheet,
        to_speech=to_speech,
        lap_messages=None,
    )
    hub.start()
    sent: list[tuple[float, Any]] = []

    async def send(item: Any) -> None:
        sent.append((time.monotonic(), item))

    client = RadioClient(send=send)
    await hub.connect(client)
    return hub, client, sent


def says(sent: list[tuple[float, Any]], kind: str | None = None) -> list[dict[str, Any]]:
    return [
        m for _t, m in sent if isinstance(m, dict) and m.get("type") == "say" and (kind is None or m["kind"] == kind)
    ]


def note(**kw: Any) -> dict[str, Any]:
    base = {
        "id": "rc-1-3",
        "group": "position",
        "call": "position_change",
        "kind": "race",
        "priority": "normal",
        "text": "Up to P5.",
        "text_simple": "You're up to 5th.",
        "speech_source": "Up to P 5.",
        "ttl_s": 15.0,
        "needs_window": True,
        "bypass_quiet": False,
        "topic": "race:position",
        "lap": 3,
        "addressable": True,
        "defer_to_strategy_detail": False,
        "audience": None,
        "tier": "recorded",
        "synthetic": False,
    }
    return {**base, **kw}


URGENT = {
    "id": "rc-9-4",
    "source": "raceradio",
    "text": "Red flag, red flag. Slow down, back to the pits.",
    "text_simple": "Red flag: the race is stopped. Slow down and drive back to the pits.",
    "speech_source": None,
    "ttl_s": 15.0,
    "meta": {"group": "flags", "call": "red_flag", "tier": "synthetic", "synthetic": True, "race_call": "rc-9-4"},
}


async def until(cond: Any, timeout: float = 2.0) -> None:
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        await asyncio.sleep(0.005)


def driver(name: str, **prefs: Any) -> Driver:
    return Driver(1, name, 0.0, DriverPreferences(skill_level="advanced", **prefs))


async def test_a_race_call_note_is_said_with_its_meta() -> None:
    hub, _c, sent = await make()
    hub.live.notify("race_call", note())
    await until(lambda: says(sent))
    [m] = says(sent)
    assert (m["kind"], m["text"], m["speech"]) == ("race", "Up to P5.", "Up to P 5.")
    assert m["meta"]["race_call"] == "rc-1-3" and m["meta"]["urgent"] is False and m["meta"]["group"] == "position"
    await hub.stop()


async def test_a_new_sessions_first_call_survives_the_session_change() -> None:
    # e2e on a real GT7 capture: the rolling-start brief comes with the session's first frame, before the hub's tick
    # notices the new session; the tick's reset then dropped it with the old session's messages
    hub, _c, sent = await make()
    hub.live.reset_session("s1", "udp:20777", False)
    await until(lambda: hub._radio_sid == "s1")
    hub.live.reset_session("s2", "udp:20777", False)
    hub._enqueue_race(note(id="rc-old", session_id="s1", text="Old session."))  # an earlier session's: dropped
    hub._enqueue_race(note(session_id="s2"))  # on the loop, before the next tick
    await until(lambda: says(sent))
    await asyncio.sleep(2 * 0.1)  # a tick or two: nothing more, nothing dropped
    assert [m["text"] for m in says(sent)] == ["Up to P5."]
    await hub.stop()


async def test_the_drivers_groups_wording_and_name() -> None:
    hub, client, sent = await make()
    hub.apply_driver(driver("Sam Reid", radio_calls=RadioCallPrefs(position=False)))
    hub.live.notify("race_call", note())
    hub.live.notify("race_call", note(id="rc-2-3", group="flags", call="blue_flag", kind="alert", priority="high",
                                      text="Blue flag. Let the car behind through.", addressable=False))  # fmt: skip
    await until(lambda: says(sent))
    assert [m["text"] for m in says(sent)] == ["Blue flag. Let the car behind through."]  # position switched off
    await hub.on_text(client, {"type": "playback", "id": says(sent)[0]["id"], "state": "ended"})
    hub.apply_driver(driver("Sam Reid", radio_wording="simple"))
    hub.live.notify("race_call", note(id="rc-3-4"))
    await until(lambda: len(says(sent)) == 2, timeout=5.0)
    assert says(sent)[-1]["text"] == "You're up to 5th, Sam."  # simple words, and the name (addressable)
    await hub.stop()


async def test_urgent_end_to_end_from_another_thread_under_250_ms() -> None:
    hub, _c, sent = await make()
    t0: list[float] = []

    def produce() -> None:
        t0.append(time.monotonic())
        hub.live.notify(URGENT_NOTE, {**URGENT, "t_mono": t0[0]})

    threading.Thread(target=produce).start()
    await until(lambda: says(sent))
    [(t_say, m)] = [(t, m) for t, m in sent if isinstance(m, dict) and m.get("type") == "say"]
    assert m["kind"] == "alert" and m["meta"]["urgent"] is True and m["text"].startswith("Red flag, red flag.")
    assert t_say - t0[0] <= 0.25, t_say - t0[0]
    rec = hub.latency[0]
    assert rec.kind == "urgent" and rec.to_first_audio_ms is not None and rec.to_first_audio_ms <= 250
    assert hub.status()["latency"][0]["kind"] == "urgent"
    await hub.stop()


async def test_urgent_at_quiet_intensity_in_quiet_mode_and_never_addressed() -> None:
    hub, _c, sent = await make("quiet")
    hub.apply_driver(driver("Sam", coaching_intensity="quiet"))
    hub.apply_driver(driver("Sam", coaching_intensity="quiet"))
    hub.scheduler.set_quiet(indefinite=True)
    hub.live.notify("race_call", note())  # a race call is not said at quiet intensity
    hub.live.notify(URGENT_NOTE, URGENT)
    await until(lambda: says(sent))
    await asyncio.sleep(0.3)
    assert [m["text"] for m in says(sent)] == ["Red flag, red flag. Slow down, back to the pits."]
    await hub.stop()


async def test_urgent_cuts_a_lap_summary_which_is_said_again_once() -> None:
    hub, _client, sent = await make()
    summary = RadioMessage(
        "sum1", MessageKind.LAP_SUMMARY, Priority.NORMAL, "That lap, 1:31.2.", "That lap.", time.monotonic()
    )
    hub._deliver(summary, AudioClip(b"\x01\x00" * 44100, 22050), None, None)  # 2 s on air
    assert hub.speaking_id == "sum1"
    hub.live.notify(URGENT_NOTE, URGENT)
    await until(lambda: says(sent, "alert"))
    assert any(isinstance(m, dict) and m.get("type") == "cancel" and m["id"] == "sum1" for _t, m in sent)
    held = hub._held
    assert held is not None and held[0].text == "That lap, 1:31.2." and held[0].meta.get("resent") == 1  # said again
    await hub.stop()


async def test_no_urgent_audio_with_the_voice_off_and_it_waits_for_the_drivers_transmission() -> None:
    hub, client, sent = await make()
    hub.voice_enabled = False
    hub.live.notify(URGENT_NOTE, URGENT)
    await asyncio.sleep(0.4)
    assert says(sent) == []  # on screen only (Drive's red flag band)
    hub.voice_enabled = True
    await hub.on_text(client, {"type": "ptt", "down": True})
    hub.live.notify(URGENT_NOTE, {**URGENT, "id": "rc-10-4"})
    await asyncio.sleep(0.4)
    assert says(sent) == []  # the driver is talking
    await hub.on_text(client, {"type": "ptt", "down": False})
    await until(lambda: says(sent))
    assert [m["id"] for m in says(sent)] == ["urgent-rc-10-4"]
    await hub.stop()
