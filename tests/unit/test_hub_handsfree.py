"""Hands-free talking through the radio hub (lane handsfree): off by default, every refusal reason, the pre-roll,
half-duplex aborts, privacy of ignored speech, the wake word alone ("Go ahead." and one follow-up), the echo loop,
budgets, the paused-while-driving hint, the scope from the seated driver, and push-to-talk still winning."""

from __future__ import annotations

import asyncio
import math
import time
from typing import Any

import numpy as np
import pytest

from pitwall.core.live import LiveState
from pitwall.drivers import Driver, DriverPreferences
from pitwall.model.telemetry import CarFrame, Game
from pitwall.voice import handsfree as hf_mod
from pitwall.voice.hub import UDP_ACTION_BASE, VOICE_TEST_PHRASE, RadioClient, RadioHub
from pitwall.voice.stt import NullStt, SttError
from pitwall.voice.types import AudioClip, MessageKind, Priority, RadioMessage, SttResult
from tests.unit.test_voice_hub import FakeScheduler, FakeTts, RecordingEngineer, settle, sheet, texts

SR = 16_000


def tone(seconds: float, amp: int = 6000) -> bytes:
    """A 300 Hz tone (speech-like level: about -18 dBFS); constant PCM would have no energy for the gate."""
    t = np.arange(round(seconds * SR)) / SR
    return (amp * np.sin(2 * np.pi * 300 * t)).astype("<i2").tobytes()


def silence(seconds: float) -> bytes:
    return b"\x00\x00" * round(seconds * SR)


class ScriptedStt:
    """Returns the scripted transcripts in order ("" when it runs out); ``fail`` raises instead."""

    name = "fake-stt"

    def __init__(self, *script: str) -> None:
        self.script = list(script)
        self.clips: list[AudioClip] = []
        self.fail: Exception | None = None

    def warmup(self) -> None:
        return None

    def transcribe(self, clip: AudioClip, prompt: str | None = None) -> SttResult:
        self.clips.append(clip)
        if self.fail is not None:
            raise self.fail
        text = self.script.pop(0) if self.script else ""
        return SttResult(text, self.name, 7, clip.duration_s)


class Rig:
    def __init__(self, hub: RadioHub, stt: ScriptedStt, eng: RecordingEngineer, sched: Any) -> None:
        self.hub = hub
        self.stt = stt
        self.eng = eng
        self.sched = sched
        self.sent: dict[RadioClient, list[Any]] = {}
        self.observed: list[tuple[str, dict[str, Any]]] = []
        hub.add_observer(lambda kind, payload: self.observed.append((kind, payload)))

    async def client(self, armed: bool = True, wake: str = "pitwall") -> RadioClient:
        box: list[Any] = []

        async def send(item: Any) -> None:
            box.append(item)

        c = RadioClient(send=send, name=f"dev{len(self.sent)}")
        self.sent[c] = box
        await self.hub.connect(c)
        if armed:
            await self.hub.on_text(c, {"type": "settings", "handsfree": True, "wake_word": wake})
        await settle(2)
        return c

    def events(self, c: RadioClient, event: str | None = None) -> list[dict[str, Any]]:
        return [m for m in texts(self.sent[c], "handsfree") if event is None or m["event"] == event]

    def says(self) -> list[str]:
        return [m["text"] for box in self.sent.values() for m in texts(box, "say")]

    async def segment(
        self, c: RadioClient, seq: int, speech_s: float = 1.0, pre_s: float = 0.5, audio: bytes | None = None
    ) -> None:
        """The device's VAD: pre-roll in the ring, "start", the speech, "end"; then let the server process it."""
        if pre_s:
            self.hub.on_audio(c, tone(pre_s))
        await self.hub.on_text(c, {"type": "vad", "state": "start", "seq": seq})
        self.hub.on_audio(c, audio if audio is not None else tone(speech_s))
        await self.hub.on_text(c, {"type": "vad", "state": "end", "seq": seq, "reason": "silence"})
        await settle(40)

    def end_playback(self) -> None:
        mid = self.hub.speaking_id
        if mid is not None:
            self.hub._on_playback(mid, "ended")
            self.hub._gate_until = 0.0  # skip the 0.3 s echo tail


async def rig(*script: str, stt: Any = None, sched: Any = None, enabled: bool = True, facts: Any = sheet) -> Rig:
    eng = RecordingEngineer()
    s = stt if stt is not None else ScriptedStt(*script)
    sched = sched or FakeScheduler()
    hub = RadioHub(LiveState(), eng, s, FakeTts(), sched, fact_sheet=facts, to_speech=lambda x: x, handsfree=enabled)
    hub.start()
    return Rig(hub, s, eng, sched)


def drive(hub: RadioHub, speed: float, pit: int | None = None, calm: bool = False) -> None:
    """A live frame. ``calm``: off the brakes and straight (a speak window on track); else brake and steering are
    unknown, which is never calm."""
    hub.live.on_packet(accepted=True)
    hub.live.on_frame(
        CarFrame(
            game=Game.F1_25,
            t_recv_ns=0,
            speed_kph=speed,
            pit_status=pit,
            lap_number=3,
            lap_distance_m=400.0,
            brake=0.0 if calm else None,
            steering=0.0 if calm else None,
        )
    )
    hub.handsfree.tick(time.monotonic())


def settled(hub: RadioHub) -> None:
    """The car has been still for the hint's settle time and the radio quiet for long enough."""
    hf = hub.handsfree
    hf._still_since = time.monotonic() - hf_mod.HINT_SETTLE_S - 0.1
    hub._air_free_mono = -math.inf
    hf.tick(time.monotonic())


def _driver(handsfree: bool, skill: str = "advanced") -> Driver:
    return Driver(7, "Sam", 0.0, DriverPreferences(skill_level=skill, handsfree_while_driving=handsfree))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------------- off by default
async def test_off_by_default_nothing_is_kept_or_transcribed() -> None:
    r = await rig("Pitwall, what's my fuel?")
    c = await r.client(armed=False)
    r.hub.on_audio(c, tone(1.0))
    assert r.hub.handsfree.client_info(c) == {"handsfree": False, "wake_word": "pitwall"}
    assert not r.hub.handsfree._devices.get(c)  # no ring for a device that never turned it on
    await r.segment(c, 1)
    assert r.events(c) == [{"type": "handsfree", "event": "rejected", "seq": 1, "reason": "not_armed"}]
    assert r.stt.clips == [] and texts(r.sent[c], "transcript") == []
    st = r.hub.state()
    assert st["listening"] is False
    assert st["handsfree"] == {
        "available": True,
        "reason": None,
        "armed": 0,
        "scope": "stationary",
        "active": False,
        "paused": None,
        "capturing": False,
        "follow_up": False,
        "wake_words": ["pitwall", "radio"],
        "counts": {"heard": 0, "addressed": 0, "ignored": 0, "rejected": 1},
    }
    await r.hub.stop()


async def test_server_switch_and_missing_speech_recognition_make_it_unavailable() -> None:
    r = await rig(enabled=False)
    c = await r.client()
    await r.segment(c, 1)
    assert r.events(c)[-1]["reason"] == "unavailable"
    assert "PITWALL_VOICE_HANDSFREE=false" in r.hub.state()["handsfree"]["reason"]
    await r.hub.stop()
    r = await rig(stt=NullStt("server speech recognition (Parakeet) needs an Apple-silicon Mac or sherpa-onnx"))
    c = await r.client()
    await r.segment(c, 1)
    assert r.events(c)[-1]["reason"] == "unavailable"
    hf = r.hub.state()["handsfree"]
    assert hf["available"] is False and hf["armed"] == 1 and hf["reason"].startswith("needs speech recognition")
    await r.hub.stop()


# ---------------------------------------------------------------------------------------------- the happy path
async def test_addressed_question_is_answered_with_the_pre_roll_included() -> None:
    r = await rig("Pitwall, how are my tyres?")
    c = await r.client()
    r.hub.on_audio(c, tone(2.0))  # only the last 0.5 s is kept
    await r.hub.on_text(c, {"type": "vad", "state": "start", "seq": 3})
    assert r.hub.state()["listening"] is True and r.hub.state()["handsfree"]["capturing"] is True
    r.hub.on_audio(c, tone(1.0))
    await r.hub.on_text(c, {"type": "vad", "state": "end", "seq": 3, "reason": "silence"})
    await settle(40)
    assert len(r.stt.clips) == 1 and r.stt.clips[0].duration_s == pytest.approx(1.5, abs=0.01)
    assert [e["event"] for e in r.events(c)] == ["accepted", "addressed"]
    assert r.events(c, "addressed")[0]["wake"] == "pitwall"
    (tr,) = texts(r.sent[c], "transcript")
    assert tr["text"] == "how are my tyres?" and tr["source"] == "handsfree" and tr["wake"] == "pitwall"
    answer = [m for m in texts(r.sent[c], "say") if m["kind"] == "answer"][-1]
    assert "FL 9.1%" in answer["text"]
    assert r.hub.history[1] == {"role": "driver", "text": "how are my tyres?", "t": r.hub.history[1]["t"]}
    assert r.hub.latency[0].stt_ms == 7 and r.hub.latency[0].kind == "question"
    assert r.hub.state()["handsfree"]["counts"] == {"heard": 1, "addressed": 1, "ignored": 0, "rejected": 0}
    await r.hub.stop()


async def test_the_llm_explains_only_when_stationary_and_every_moving_answer_is_deterministic() -> None:
    r = await rig("Pitwall, where am I losing time?", "Pitwall, where am I losing time?")
    c = await r.client()
    await r.segment(c, 1)  # no telemetry: stationary
    assert r.eng.use_llm[-1] == ("where am I losing time?", True)
    assert "Copy, checking." in r.says()
    r.end_playback()
    r.hub.apply_driver(_driver(handsfree=True))  # the seated driver allows hands-free while driving
    drive(r.hub, 212.0)
    assert r.hub.moving() and r.hub.handsfree.active
    await r.segment(c, 2)
    assert r.eng.use_llm[-1] == ("where am I losing time?", False)
    assert r.says().count("Copy, checking.") == 1
    await r.hub.stop()


# ---------------------------------------------------------------------------------------------- refusals
async def test_every_start_refusal_reason_in_order() -> None:
    r = await rig()
    a = await r.client()
    b = await r.client()
    hf = r.hub.handsfree

    async def start(c: RadioClient, seq: int) -> str | None:
        await r.hub.on_text(c, {"type": "vad", "state": "start", "seq": seq})
        await settle(2)
        ev = r.events(c)[-1]
        return ev.get("reason") if ev["event"] == "rejected" else ev["event"]

    r.hub._ptt_down_now("screen", a)
    assert await start(a, 1) == "ptt"
    r.hub._ptt_up("screen")
    assert await start(a, 2) == "accepted"
    assert await start(b, 1) == "other_device"  # one capture at a time across devices
    await r.hub.on_text(a, {"type": "vad", "state": "abort", "seq": 2, "reason": "suppressed"})
    assert not hf.capturing
    r.hub._gate_until = time.monotonic() + 5  # the gate tail after the radio spoke
    assert await start(b, 2) == "speaking"
    r.hub._gate_until = 0.0
    r.hub._busy = True
    assert await start(b, 3) == "busy"
    r.hub._busy = False
    hf._hint_said = True  # (the paused hint has its own test: keep the radio quiet here)
    drive(r.hub, 150.0)
    assert hf.paused == "moving" and not hf.active
    assert await start(b, 4) == "paused_moving"
    drive(r.hub, 0.0, pit=2)
    for _ in range(hf_mod.TRANSCRIBE_LIMIT):
        assert hf._transcribe.take(time.monotonic())
    assert await start(b, 5) == "rate_limited"
    hf._transcribe.clear()
    assert await start(b, 6) == "accepted"
    assert hf._reasons["suppressed"] == 1  # the device's own abort is only counted
    await r.hub.stop()


async def test_segment_outcomes_too_short_too_long_no_speech_and_the_watchdog() -> None:
    r = await rig("Pitwall, fuel?")
    c = await r.client()
    await r.segment(c, 1, speech_s=0.2, pre_s=0.0)
    assert r.events(c)[-1]["reason"] == "too_short"
    await r.segment(c, 2, speech_s=8.6)
    assert r.events(c)[-1]["reason"] == "too_long"
    await r.segment(c, 3, pre_s=0.0, audio=silence(1.5))
    assert r.events(c)[-1]["reason"] == "no_speech"
    assert r.stt.clips == []  # none of them reached the speech engine
    await r.hub.on_text(c, {"type": "vad", "state": "start", "seq": 4})
    r.hub.on_audio(c, tone(0.5))
    r.hub.handsfree.tick(time.monotonic() + hf_mod.CAPTURE_WATCHDOG_S + 0.1)  # the "end" never came
    await settle(2)
    assert r.events(c)[-1] == {"type": "handsfree", "event": "rejected", "seq": 4, "reason": "too_long", "audio_s": 0.5}
    assert not r.hub.handsfree.capturing
    await r.hub.on_text(c, {"type": "vad", "state": "end", "seq": 4, "reason": "silence"})  # late: ignored
    await settle(10)
    assert r.stt.clips == []
    await r.hub.stop()


async def test_speech_engine_errors_are_reported_once_a_minute() -> None:
    r = await rig()
    r.stt.fail = SttError("speech model downloading (42 %)")
    c = await r.client()
    await r.segment(c, 1)
    await r.segment(c, 2)
    assert [e["reason"] for e in r.events(c, "rejected")] == ["stt_error", "stt_error"]
    errors = texts(r.sent[c], "error")
    assert len(errors) == 1 and "downloading (42 %)" in errors[0]["message"]
    await r.hub.stop()


# ---------------------------------------------------------------------------------------------- privacy
async def test_speech_not_addressed_to_the_radio_leaves_no_trace() -> None:
    r = await rig("What's for dinner tonight?", "")
    c = await r.client()
    history = list(r.hub.history)
    await r.segment(c, 1)
    await r.segment(c, 2)  # the engine heard nothing at all
    assert [e.get("reason") for e in r.events(c) if e["event"] != "accepted"] == ["not_addressed", "no_speech"]
    assert texts(r.sent[c], "transcript") == []
    assert list(r.hub.history) == history
    assert "Say again?" not in r.says() and r.says() == []
    assert [k for k, _ in r.observed if k == "transcript"] == []
    blob = repr(r.observed) + repr(r.hub.status())
    assert "dinner" not in blob
    assert all("text" not in p for k, p in r.observed if k == "handsfree")
    diag = r.hub.status()["handsfree_diag"]
    assert diag["reasons"] == {"not_addressed": 1, "no_speech": 1}
    assert all("text" not in e for e in diag["events"])
    await r.hub.stop()


# ---------------------------------------------------------------------------------------------- half-duplex
async def test_a_message_going_on_air_cuts_a_capture_and_push_to_talk_wins() -> None:
    r = await rig("Pitwall, fuel?")
    c = await r.client()
    await r.hub.on_text(c, {"type": "vad", "state": "start", "seq": 1})
    r.hub.on_audio(c, tone(0.5))
    r.hub.ask_text("how are my tyres")  # a typed question's answer goes on air
    await settle(20)
    assert r.events(c)[-1] == {"type": "handsfree", "event": "rejected", "seq": 1, "reason": "speaking", "audio_s": 0.5}
    assert not r.hub.handsfree._devices[c].ring  # the pre-roll would hold the radio's own voice
    r.end_playback()
    await r.hub.on_text(c, {"type": "vad", "state": "start", "seq": 2})
    await r.hub.on_text(c, {"type": "ptt", "down": True, "source": "remote"})  # a learned Bluetooth button
    await settle(2)
    assert r.events(c)[-1]["reason"] == "ptt"
    assert r.hub.ptt_down and r.hub.ptt_source == "remote" and r.hub.state()["ptt_source"] == "remote"
    r.hub.on_audio(c, tone(0.8))
    await r.hub.on_text(c, {"type": "ptt", "down": False, "source": "remote"})
    await settle(30)
    assert len(r.stt.clips) == 1 and r.stt.clips[0].duration_s == pytest.approx(0.8, abs=0.01)  # the PTT utterance
    assert texts(r.sent[c], "transcript")[-1].get("source") is None  # push-to-talk transcripts are unchanged
    await r.hub.on_text(c, {"type": "ptt", "down": True, "source": "bogus"})
    assert r.hub.ptt_source == "screen"
    await r.hub.stop()


async def test_wheel_push_to_talk_still_works_with_hands_free_armed() -> None:
    r = await rig("box this lap?")
    c = await r.client()
    await r.hub.on_text(c, {"type": "vad", "state": "start", "seq": 1})
    r.hub._on_button(UDP_ACTION_BASE)
    await settle(2)
    assert r.hub.ptt_down and r.hub.ptt_source == "wheel"
    assert r.events(c)[-1]["reason"] == "ptt" and not r.hub.handsfree.capturing
    r.hub.on_audio(c, tone(0.9))
    r.hub._on_button(0)
    await settle(30)
    assert not r.hub.ptt_down and r.stt.clips[-1].duration_s == pytest.approx(0.9, abs=0.01)
    assert texts(r.sent[c], "transcript")[-1]["text"] == "box this lap?"  # PTT needs no wake word
    await r.hub.stop()


async def test_urgent_calls_still_go_out_during_a_capture_while_normal_ones_wait() -> None:
    r = await rig()
    c = await r.client()
    await r.hub.on_text(c, {"type": "vad", "state": "start", "seq": 1})
    now = time.monotonic()
    normal = RadioMessage("n1", MessageKind.LAP_SUMMARY, Priority.NORMAL, "Lap time 1:20.1.", "Lap time.", now)
    r.hub._after_synthesis((normal, None, 0.0), now)
    assert r.hub._held is not None and r.hub._held[0].id == "n1" and r.hub.handsfree.capturing
    r.sched.enqueue(RadioMessage("n2", MessageKind.COACHING, Priority.NORMAL, "Brake earlier.", "Brake.", now))
    await r.hub._tick(time.monotonic())
    assert [m.id for m in r.sched.queue] == ["n2"]  # interrupt-only while capturing: FakeScheduler gives nothing
    urgent = RadioMessage("u1", MessageKind.ALERT, Priority.URGENT, "Safety car.", "Safety car.", now)
    r.hub._after_synthesis((urgent, AudioClip(b"\x01\x00" * 11_025, 22_050), 0.0), now)
    await settle(2)
    assert r.hub.speaking_id == "u1"
    assert r.events(c)[-1]["reason"] == "speaking" and not r.hub.handsfree.capturing
    await r.hub.stop()


# ---------------------------------------------------------------------------------------------- the wake word alone
async def test_wake_word_alone_says_go_ahead_then_takes_one_follow_up_without_it() -> None:
    r = await rig("Pitwall.", "what's my fuel situation?", "how are my tyres?")
    c = await r.client()
    hf = r.hub.handsfree
    await r.segment(c, 1)
    assert [e["event"] for e in r.events(c)][-2:] == ["addressed", "follow_up"]
    assert r.hub.state()["handsfree"]["follow_up"] is True
    assert r.says() == []  # the grace: the question may still come
    hf.tick(time.monotonic() + hf_mod.TRIGGER_GRACE_S + 0.05)
    await settle(20)
    assert r.says() == ["Go ahead."]
    r.end_playback()
    hf.tick(time.monotonic())
    assert hf._follow is not None and hf._follow.phase == "window"
    await r.segment(c, 2)  # no wake word: the follow-up
    tr = texts(r.sent[c], "transcript")
    assert [t["text"] for t in tr] == ["what's my fuel situation?"]
    assert r.eng.use_llm[-1][0] == "what's my fuel situation?"
    r.end_playback()
    await r.segment(c, 3)  # one follow-up per trigger
    assert r.events(c)[-1]["reason"] == "not_addressed"
    await r.hub.stop()


async def test_the_question_within_the_grace_needs_no_go_ahead() -> None:
    r = await rig("Pitwall.", "how are my tyres?")
    c = await r.client()
    await r.segment(c, 1)
    await r.segment(c, 2, pre_s=0.1)
    await settle(20)
    assert "Go ahead." not in r.says()
    assert [t["text"] for t in texts(r.sent[c], "transcript")] == ["how are my tyres?"]
    await r.hub.stop()


async def test_a_question_started_while_the_wake_word_was_still_being_transcribed_is_the_follow_up() -> None:
    r = await rig("Pitwall.", "how are my tyres?")
    c = await r.client()
    r.hub.on_audio(c, tone(0.5))
    for seq in (1, 2):  # the second segment starts before the first one is processed
        await r.hub.on_text(c, {"type": "vad", "state": "start", "seq": seq})
        r.hub.on_audio(c, tone(1.0))
        await r.hub.on_text(c, {"type": "vad", "state": "end", "seq": seq, "reason": "silence"})
    await settle(60)
    assert [t["text"] for t in texts(r.sent[c], "transcript")] == ["how are my tyres?"]
    assert "Go ahead." not in r.says()
    await r.hub.stop()


async def test_simple_wording_acknowledgement() -> None:
    r = await rig("Pitwall.")
    r.hub.apply_driver(_driver(handsfree=False, skill="beginner"))
    c = await r.client()
    await r.segment(c, 1)
    r.hub.handsfree.tick(time.monotonic() + hf_mod.TRIGGER_GRACE_S + 0.05)
    await settle(20)
    assert r.says() == ["Go ahead, I'm listening."]
    await r.hub.stop()


# ---------------------------------------------------------------------------------------------- echo and budgets
async def test_the_radio_check_echo_loop_is_blocked() -> None:
    r = await rig("Radio check, loud and clear.", "Radio check.")
    c = await r.client(wake="radio")
    await r.hub.on_text(c, {"type": "test_voice"})  # "Radio check, loud and clear. Box this lap for mediums."
    await settle(20)
    assert r.says() == [VOICE_TEST_PHRASE]
    r.end_playback()
    await r.segment(c, 1)  # the mic heard the radio's own test phrase
    assert r.events(c)[-1]["reason"] == "echo"
    assert texts(r.sent[c], "transcript") == []
    await r.segment(c, 2)  # the driver's own radio check is answered, with the whole text as the question
    assert [t["text"] for t in texts(r.sent[c], "transcript")] == ["Radio check."]
    assert r.eng.use_llm[-1][0] == "Radio check."
    await r.hub.stop()


async def test_answer_budget_six_a_minute() -> None:
    r = await rig(*(["Pitwall, how are my tyres?"] * 7))
    c = await r.client()
    for seq in range(1, 8):
        await r.segment(c, seq)
        r.end_playback()
    assert len(texts(r.sent[c], "transcript")) == hf_mod.ANSWER_LIMIT
    assert r.events(c)[-1]["reason"] == "answer_limit"
    await r.hub.stop()


# ---------------------------------------------------------------------------------------------- scope and hint
async def test_the_seated_drivers_profile_sets_the_scope() -> None:
    r = await rig()
    c = await r.client()
    hf = r.hub.handsfree
    drive(r.hub, 180.0)
    assert hf.scope == "stationary" and hf.paused == "moving" and not hf.active
    r.hub.apply_driver(_driver(handsfree=True))
    assert str(hf.scope) == "driving" and hf.paused is None and hf.active
    assert r.hub.state()["handsfree"]["scope"] == "driving"
    r.hub.apply_driver(None)  # nobody in the seat: stationary only
    assert hf.scope == "stationary" and not hf.active
    await r.hub.on_text(c, {"type": "settings", "handsfree": False})
    assert hf.paused is None and hf.armed == 0
    await r.hub.stop()


async def test_paused_hint_once_per_session_after_a_settled_stop() -> None:
    r = await rig()
    c = await r.client(wake="radio")
    hf = r.hub.handsfree
    drive(r.hub, 200.0)
    await r.hub.on_text(c, {"type": "vad", "state": "start", "seq": 1})
    await settle(2)
    assert r.events(c)[-1]["reason"] == "paused_moving"
    hf.tick(time.monotonic())
    await settle(10)
    assert r.says() == []  # not while moving
    drive(r.hub, 0.0, pit=1)
    await settle(20)
    assert r.says() == []  # a stop is not yet a settled one (an incident, the grid just before lights out)
    settled(r.hub)
    await settle(20)
    assert r.says() == [hf_mod.HINT_TEXT]
    hint = next(m for m in texts(r.sent[c], "say") if m["text"] == hf_mod.HINT_TEXT)
    assert hint["kind"] == "info"  # not a control message: it never bypasses quiet and a braking call may cut it
    r.end_playback()
    drive(r.hub, 200.0)
    await r.hub.on_text(c, {"type": "vad", "state": "start", "seq": 2})
    drive(r.hub, 0.0, pit=1)
    settled(r.hub)
    await settle(20)
    assert r.says() == [hf_mod.HINT_TEXT]  # once per session
    hf.new_session()
    r.hub._on_button(UDP_ACTION_BASE)  # the F1 wheel button was used this session
    r.hub._on_button(0)
    drive(r.hub, 200.0)
    await r.hub.on_text(c, {"type": "vad", "state": "start", "seq": 3})
    drive(r.hub, 0.0, pit=1)
    settled(r.hub)
    await settle(20)
    assert r.says()[-1] == hf_mod.HINT_TEXT + hf_mod.HINT_WHEEL
    r.end_playback()
    hf.new_session()
    r.hub.apply_driver(_driver(handsfree=False, skill="beginner"))  # simple wording
    drive(r.hub, 200.0)
    await r.hub.on_text(c, {"type": "vad", "state": "start", "seq": 4})
    drive(r.hub, 0.0, pit=1)
    settled(r.hub)
    await settle(20)
    assert r.says()[-1] == "I can't hear you while you drive. Ask me when you stop."
    await r.hub.stop()


async def test_the_hint_waits_for_a_quiet_radio_and_is_rechecked_after_synthesis() -> None:
    """Review finding 1 / UX M1: the hint never cut the final-lap summary, never bypassed quiet mode, and is not said
    when the car moves off while it is being synthesised (it waits for the next settled stop)."""
    r = await rig()
    c = await r.client()
    hf = r.hub.handsfree
    drive(r.hub, 200.0)
    await r.hub.on_text(c, {"type": "vad", "state": "start", "seq": 1})
    drive(r.hub, 0.0, pit=1)
    now = time.monotonic()
    summary = RadioMessage("s1", MessageKind.LAP_SUMMARY, Priority.NORMAL, "Final lap, 1:28.352.", "Final lap.", now)
    r.hub._hold((summary, None, 0.0))  # a held lap summary goes first
    settled(r.hub)
    await settle(10)
    assert hf_mod.HINT_TEXT not in r.says()  # the summary goes out (or stays held); the hint never cuts it
    if r.hub.speaking_id == "s1":
        assert r.says()[-1] == "Final lap, 1:28.352."
        r.end_playback()
    r.hub._held = None
    r.hub.intensity = "quiet"  # minimal radio: alerts and answers only
    settled(r.hub)
    await settle(10)
    assert hf_mod.HINT_TEXT not in r.says()
    r.hub.intensity = "normal"
    original = r.hub._synthesize

    async def moving_off(msg: RadioMessage, verify: bool = False) -> AudioClip | None:
        drive(r.hub, 60.0)  # lights out while the hint is synthesised
        return await original(msg, verify)

    r.hub._synthesize = moving_off  # type: ignore[method-assign]
    settled(r.hub)
    await settle(20)
    assert hf_mod.HINT_TEXT not in r.says() and hf._hint_word is not None and not hf._hint_said
    r.hub._synthesize = original  # type: ignore[method-assign]
    drive(r.hub, 0.0, pit=1)
    settled(r.hub)
    await settle(20)
    assert r.says()[-1] == hf_mod.HINT_TEXT
    await r.hub.stop()


async def test_a_braking_call_never_cuts_the_hint() -> None:
    """v0.3.0 radio policy: only the urgent path interrupts. The hint is said only at a settled stop, where no braking
    call fires; one that did would be dropped, never cut the hint."""
    from pitwall.voice.hub import compose_cue_clip
    from tests.unit.test_cues import make_event

    r = await rig()
    c = await r.client()
    drive(r.hub, 200.0)
    await r.hub.on_text(c, {"type": "vad", "state": "start", "seq": 1})
    drive(r.hub, 0.0, pit=1)
    settled(r.hub)
    await settle(20)
    assert r.says() == [hf_mod.HINT_TEXT] and r.hub.speaking_id is not None
    ev = make_event()
    r.hub._cue_phrases[ev.cue.parts] = compose_cue_clip([AudioClip(tone(0.3), SR) for _ in ev.cue.parts], 1)
    assert r.hub.deliver_cue(ev, time.monotonic()) == "radio busy"
    assert r.hub._held is None  # nothing was cut, nothing is said again
    await r.hub.stop()


# ---------------------------------------------------------------------------------------------- settings and status
async def test_settings_are_per_device_and_validated() -> None:
    r = await rig()
    a = await r.client(wake="radio")
    b = await r.client(armed=False)
    await r.hub.on_text(b, {"type": "settings", "handsfree": True, "wake_word": "engineer"})
    await settle(2)
    assert "unknown wake word" in texts(r.sent[b], "error")[-1]["message"]
    assert r.hub.handsfree.client_info(b) == {"handsfree": False, "wake_word": "pitwall"}  # nothing changed
    await r.hub.on_text(b, {"type": "settings", "handsfree": "yes"})
    await settle(2)
    assert "true or false" in texts(r.sent[b], "error")[-1]["message"]
    await r.hub.on_text(b, {"type": "settings", "wake_word": "Radio"})
    status = r.hub.status()
    by_name = {cl["name"]: cl for cl in status["clients"]}
    assert by_name[a.name]["handsfree"] is True and by_name[a.name]["wake_word"] == "radio"
    assert by_name[b.name]["handsfree"] is False and by_name[b.name]["wake_word"] == "radio"
    assert status["handsfree"]["armed"] == 1
    diag = status["handsfree_diag"]
    assert diag["thresholds"]["pre_roll_s"] == 0.5 and diag["thresholds"]["answers_per_min"] == 6
    await r.hub.on_text(a, {"type": "vad", "state": "start", "seq": "x"})
    await settle(2)
    assert "integer seq" in texts(r.sent[a], "error")[-1]["message"]
    await r.hub.disconnect(a)
    assert r.hub.handsfree.armed == 0
    await r.hub.stop()


async def test_listening_state_and_state_frames_follow_the_capture() -> None:
    r = await rig()
    c = await r.client()
    before = len(texts(r.sent[c], "state"))
    await r.hub.on_text(c, {"type": "vad", "state": "start", "seq": 1})
    await settle(2)
    states = texts(r.sent[c], "state")
    assert len(states) > before and states[-1]["listening"] is True
    await r.hub.on_text(c, {"type": "vad", "state": "abort", "seq": 1, "reason": "suppressed"})
    await settle(2)
    assert texts(r.sent[c], "state")[-1]["listening"] is False
    assert math.isclose(r.hub.handsfree.diagnostics()["thresholds"]["move_above_kph"], 8.0)
    await r.hub.stop()


async def test_queue_holds_two_segments_and_drops_the_oldest() -> None:
    gate = asyncio.Event()

    class SlowStt(ScriptedStt):
        def transcribe(self, clip: AudioClip, prompt: str | None = None) -> SttResult:
            fut = asyncio.run_coroutine_threadsafe(gate.wait(), loop)
            fut.result(timeout=5)
            return super().transcribe(clip, prompt)

    loop = asyncio.get_running_loop()
    r = await rig(stt=SlowStt("not for you", "nor this", "nor that"))
    c = await r.client()
    hf = r.hub.handsfree
    for seq in (1, 2, 3):
        await r.hub.on_text(c, {"type": "vad", "state": "start", "seq": seq})
        r.hub.on_audio(c, tone(1.0))
        await r.hub.on_text(c, {"type": "vad", "state": "end", "seq": seq, "reason": "silence"})
        await settle(5)
    assert len(hf._queue) == 2  # seq 1 is with the speech engine, 2 and 3 wait
    await r.hub.on_text(c, {"type": "vad", "state": "start", "seq": 4})
    await settle(2)
    assert r.events(c)[-1]["reason"] == "busy"
    gate.set()
    await settle(60)
    assert [e["reason"] for e in r.events(c, "ignored")] == ["not_addressed"] * 3
    await r.hub.stop()


async def test_device_abort_reasons_are_bounded_in_the_diagnostics() -> None:
    r = await rig()
    c = await r.client()
    hf = r.hub.handsfree
    for seq, reason in enumerate(["suppressed", "Not A Code!", 42, "x" * 40], start=1):
        await r.hub.on_text(c, {"type": "vad", "state": "start", "seq": seq})
        await r.hub.on_text(c, {"type": "vad", "state": "abort", "seq": seq, "reason": reason})
    assert hf._reasons == {"suppressed": 1, "device": 3}
    for i in range(80):
        hf._record("aborted", f"r{i}", i, c, None)
    assert len(hf._reasons) <= 65 and hf._reasons["other"] > 0
    await r.hub.stop()


async def test_a_braking_cue_cuts_a_capture_and_the_driver_repeats() -> None:
    """Cues are never held back by a capture: on track (hands-free while driving) a cue cuts it."""
    from pitwall.voice.hub import compose_cue_clip
    from tests.unit.test_cues import make_event

    r = await rig()
    c = await r.client()
    r.hub.apply_driver(_driver(handsfree=True))
    drive(r.hub, 250.0)
    await r.hub.on_text(c, {"type": "vad", "state": "start", "seq": 1})
    assert r.hub.handsfree.capturing
    ev = make_event()
    r.hub._cue_phrases[ev.cue.parts] = compose_cue_clip([AudioClip(tone(0.3), SR) for _ in ev.cue.parts], 1)
    assert r.hub.deliver_cue(ev, time.monotonic()) is None  # delivered, not blocked by the capture
    await settle(2)
    assert r.events(c)[-1]["reason"] == "speaking" and not r.hub.handsfree.capturing
    await r.hub.stop()


# ---------------------------------------------------------------------------------------------- review fixes
async def test_the_wake_word_and_a_filler_then_the_question_is_answered() -> None:
    """Review finding 2: "Pitwall, um." is the wake word alone (no answer to "um."), and the question that follows
    after the browser split the sentence is taken without the wake word."""
    r = await rig("Pitwall, um.", "what's my fuel?")
    c = await r.client()
    await r.segment(c, 1)
    await r.segment(c, 2, pre_s=0.1)
    await settle(20)
    assert [e["event"] for e in r.events(c)] == ["accepted", "addressed", "follow_up", "accepted", "addressed"]
    assert [t["text"] for t in texts(r.sent[c], "transcript")] == ["what's my fuel?"]
    assert "Copy, checking." not in r.says() and r.eng.use_llm[-1][0] == "what's my fuel?"
    await r.hub.stop()


async def test_a_question_that_repeats_a_short_engineer_call_is_not_an_echo() -> None:
    """Review finding 3: "Pitwall, box this lap?" after "Box this lap." is a question; the radio's own line that starts
    with the wake word coming back through the mic is still an echo."""
    r = await rig("Pitwall, box this lap?", "Pitwall works with Gran Turismo")
    c = await r.client()
    now = time.monotonic()
    await r.hub.say(
        RadioMessage("b1", MessageKind.STRATEGY, Priority.NORMAL, "Box this lap.", "Box this lap.", now), None, None
    )
    r.end_playback()
    await r.segment(c, 1)
    assert [t["text"] for t in texts(r.sent[c], "transcript")] == ["box this lap?"]
    r.end_playback()
    line = "Pitwall works with Gran Turismo 7 lap times."
    await r.hub.say(RadioMessage("g1", MessageKind.ANSWER, Priority.HIGH, line, line, now), None, None)
    r.end_playback()
    await r.segment(c, 2)
    assert r.events(c)[-1]["reason"] == "echo"
    await r.hub.stop()


async def test_the_wake_word_alone_holds_the_radio_until_the_question() -> None:
    """Review finding 4: after "Pitwall." the grace, "Go ahead." and the window hold scheduled messages, so the
    question is not refused as "speaking"; the lap summary goes out after the answer."""
    r = await rig("Pitwall.", "what's my fuel?")
    c = await r.client()
    hf = r.hub.handsfree
    await r.segment(c, 1)
    assert hf.holds_radio
    hf.tick(time.monotonic() + hf_mod.TRIGGER_GRACE_S + 0.05)
    await settle(20)
    assert r.says() == ["Go ahead."]
    r.end_playback()
    hf.tick(time.monotonic())
    assert hf._follow is not None and hf._follow.phase == "window" and hf.holds_radio
    r.hub._air_free_mono = -math.inf  # the scheduler's 2 s gap has passed
    now = time.monotonic()
    r.sched.enqueue(RadioMessage("s1", MessageKind.LAP_SUMMARY, Priority.NORMAL, "Lap 3, 1:32.4.", "Lap 3.", now))
    await settle(30)
    assert r.says() == ["Go ahead."]  # the summary waits
    await r.segment(c, 2)
    assert r.events(c)[-1]["event"] == "addressed"
    assert [t["text"] for t in texts(r.sent[c], "transcript")] == ["what's my fuel?"]
    r.end_playback()
    r.hub._air_free_mono = -math.inf
    await settle(30)
    assert r.says()[-1] == "Lap 3, 1:32.4."
    await r.hub.stop()


async def test_go_ahead_never_cuts_a_message_on_air() -> None:
    """Review finding 4: "Go ahead." waits for what is on air; with no moment within ACK_WAIT_S it listens silently."""
    r = await rig("Pitwall.", "what's my fuel?")
    c = await r.client()
    hf = r.hub.handsfree
    await r.segment(c, 1)
    now = time.monotonic()
    summary = RadioMessage("s1", MessageKind.LAP_SUMMARY, Priority.NORMAL, "Lap 3, 1:32.4.", "Lap 3.", now)
    r.hub._send_ready((summary, AudioClip(b"\x01\x00" * 22_050, 22_050), 0.0), now)  # already on air
    hf.tick(time.monotonic() + hf_mod.TRIGGER_GRACE_S + 0.05)
    await settle(10)
    assert "Go ahead." not in r.says() and r.hub.speaking_id == "s1"
    assert all(m.get("id") != "s1" for box in r.sent.values() for m in texts(box, "cancel"))
    hf.tick(time.monotonic() + hf_mod.TRIGGER_GRACE_S + hf_mod.ACK_WAIT_S + 0.1)
    assert hf._follow is not None and hf._follow.phase == "window"  # listens without "Go ahead."
    r.end_playback()
    await r.segment(c, 2)
    assert [t["text"] for t in texts(r.sent[c], "transcript")] == ["what's my fuel?"]
    await r.hub.stop()


async def test_go_ahead_waits_for_a_calm_stretch_on_track() -> None:
    """Review finding 7: with hands-free while driving, "Go ahead." is said only in a speak window."""
    r = await rig("Pitwall.", "Pitwall.")
    c = await r.client()
    hf = r.hub.handsfree
    r.hub.apply_driver(_driver(handsfree=True))
    drive(r.hub, 220.0)  # brake and steering unknown: never calm
    await r.segment(c, 1)
    drive(r.hub, 220.0)  # fresh data (stale data would not be "on track")
    hf.tick(time.monotonic() + hf_mod.TRIGGER_GRACE_S + 0.05)
    await settle(10)
    assert r.says() == []
    drive(r.hub, 220.0)
    hf.tick(time.monotonic() + hf_mod.TRIGGER_GRACE_S + hf_mod.ACK_WAIT_S + 0.1)
    assert hf._follow is not None and hf._follow.phase == "window" and r.says() == []
    hf._follow = None
    hf._acks.clear()
    drive(r.hub, 220.0, calm=True)  # off the brakes, straight, no braking zone known
    await r.segment(c, 2)
    drive(r.hub, 220.0, calm=True)
    hf.tick(time.monotonic() + hf_mod.TRIGGER_GRACE_S + 0.05)
    await settle(20)
    assert r.says() == ["Go ahead."]
    await r.hub.stop()


async def test_a_recording_in_progress_is_dropped_when_the_car_moves_off() -> None:
    """Review finding 5: the stationary scope is enforced on a recording that started while stopped."""
    r = await rig("Pitwall, how are my tyres?")
    c = await r.client()
    hf = r.hub.handsfree
    drive(r.hub, 0.0)
    r.hub.on_audio(c, tone(0.5))
    await r.hub.on_text(c, {"type": "vad", "state": "start", "seq": 1})
    r.hub.on_audio(c, tone(0.6))
    drive(r.hub, 150.0)  # lights out mid-sentence
    assert hf.paused == "moving" and not hf.capturing
    await settle(2)
    assert r.events(c)[-1]["reason"] == "paused_moving"
    r.hub.on_audio(c, tone(0.6))
    await r.hub.on_text(c, {"type": "vad", "state": "end", "seq": 1})
    await settle(20)
    assert r.stt.clips == [] and texts(r.sent[c], "transcript") == [] and r.says() == []
    await r.hub.stop()


async def test_a_stalled_stream_while_moving_does_not_open_listening() -> None:
    """Review findings 1, 5 and 9: a 2-4 s gap in the stream mid-race (an incident) is not a stop."""
    r = await rig()
    c = await r.client()
    hf = r.hub.handsfree
    drive(r.hub, 150.0)
    r.hub.live.last_packet_mono -= 2.5  # the hub sees the stream stale
    hf.tick(time.monotonic())
    assert hf.paused == "moving"
    await r.hub.on_text(c, {"type": "vad", "state": "start", "seq": 1})
    await settle(2)
    assert r.events(c)[-1]["reason"] == "paused_moving"
    assert hf._motion.stale_since is not None
    hf._motion.stale_since -= hf_mod.STALE_STILL_AFTER_S  # a menu or a pause: long enough
    hf.tick(time.monotonic())
    assert hf.paused is None and hf.active
    await r.hub.stop()


async def test_a_question_cut_by_a_braking_call_gets_say_again() -> None:
    """UX review H1: a cue cuts a question on track; it is never answered half-heard, the radio asks for it again once
    the cue is over (in a calm stretch). Chatter cut the same way gets nothing."""
    from pitwall.voice.hub import compose_cue_clip
    from tests.unit.test_cues import make_event

    r = await rig("Pitwall, what's my fuel?", "What's for dinner tonight?")
    c = await r.client()
    r.hub.apply_driver(_driver(handsfree=True))
    drive(r.hub, 250.0, calm=True)
    ev = make_event()
    r.hub._cue_phrases[ev.cue.parts] = compose_cue_clip([AudioClip(tone(0.3), SR) for _ in ev.cue.parts], 1)
    for seq in (1, 2):
        r.hub.on_audio(c, tone(0.5))
        await r.hub.on_text(c, {"type": "vad", "state": "start", "seq": seq})
        r.hub.on_audio(c, tone(1.0))
        assert r.hub.deliver_cue(make_event(seq=seq), time.monotonic()) is None  # the cue is never held back
        await settle(20)
        assert r.hub.speaking_id is not None  # the cue is on air: nothing is said over it
        r.end_playback()
        await settle(30)
        r.end_playback()
    rejected = r.events(c, "rejected")
    assert [e["reason"] for e in rejected] == ["speaking"] and rejected[0]["seq"] == 1
    assert r.events(c, "ignored")[-1] == {
        "type": "handsfree",
        "event": "ignored",
        "seq": 2,
        "reason": "not_addressed",
        "audio_s": 1.5,
    }
    assert r.says().count("Say again?") == 1 and texts(r.sent[c], "transcript") == []
    r.hub.on_audio(c, tone(0.5))  # a short capture cut by a cue: dropped at once, never transcribed
    await r.hub.on_text(c, {"type": "vad", "state": "start", "seq": 3})
    r.hub.on_audio(c, tone(0.3))
    r.hub.deliver_cue(make_event(seq=3), time.monotonic())
    await settle(10)
    assert r.events(c)[-1]["reason"] == "speaking" and len(r.stt.clips) == 2
    await r.hub.stop()


async def test_after_go_ahead_only_a_question_about_the_car_or_race_is_taken() -> None:
    """UX review H2: chatter in the follow-up window is not answered, shown or kept."""
    r = await rig("Pitwall.", "Anyway, what are we having for dinner tonight?")
    c = await r.client()
    hf = r.hub.handsfree
    history = list(r.hub.history)
    await r.segment(c, 1)
    hf.tick(time.monotonic() + hf_mod.TRIGGER_GRACE_S + 0.05)
    await settle(20)
    r.end_playback()
    hf.tick(time.monotonic())
    await r.segment(c, 2)
    assert r.events(c)[-1]["reason"] == "not_addressed"
    assert texts(r.sent[c], "transcript") == [] and r.says() == ["Go ahead."]
    assert list(r.hub.history)[: len(history) + 1] == [h for h in r.hub.history if h["text"] == "Go ahead."] + history
    assert "dinner" not in repr(r.observed) + repr(r.hub.status())
    await r.hub.stop()


async def test_a_radio_check_before_any_session_is_answered() -> None:
    """UX review H4: no session yet, "Radio check" gets "Loud and clear", not "No session data yet"."""
    from pitwall.voice.hub import NO_GAME_REPLY, NO_SESSION_REPLY

    r = await rig("Radio check.", "Radio, what's my fuel?", facts=lambda: None)
    c = await r.client(wake="radio")
    await r.segment(c, 1)
    assert r.says()[-1] == "Loud and clear. Radio check OK."
    r.end_playback()
    await r.segment(c, 2)
    assert r.says()[-1] in (NO_SESSION_REPLY, NO_GAME_REPLY)  # a real question still needs a session (or a game)
    await r.hub.stop()


class LoadingStt(ScriptedStt):
    """A speech engine still downloading its model (Windows, first run), as ``SherpaParakeetStt`` reports it."""

    name = "sherpa"

    def __init__(self, *script: str) -> None:
        super().__init__(*script)
        self.loaded = False
        self.loading = True
        self.last_error: str | None = None
        self.percent: int | None = 42
        self.warmups = 0

    def download_percent(self) -> int | None:
        return self.percent

    def warmup(self) -> None:
        self.warmups += 1

    def transcribe(self, clip: AudioClip, prompt: str | None = None) -> SttResult:
        if not self.loaded:
            raise SttError(f"speech model downloading ({self.percent} %)")
        return super().transcribe(clip, prompt)


async def test_a_speech_model_still_downloading_is_shown_and_said() -> None:
    """UX review H5: the first-run download is visible (the percentage reaches the state frame), hands-free waits for
    it, and push-to-talk says why instead of nothing."""
    from pitwall.voice.handsfree import STT_STARTING_REPLY

    stt = LoadingStt("Pitwall, what's my fuel?")
    r = await rig(stt=stt)
    c = await r.client()
    hf = r.hub.handsfree
    st = r.hub.state()["handsfree"]
    assert st["available"] is False and st["reason"] == "starting: downloading the speech model (42 %)"
    await r.segment(c, 1)
    assert r.events(c)[-1]["reason"] == "unavailable"
    stt.percent = 57
    hf.tick(time.monotonic())
    await settle(2)
    assert texts(r.sent[c], "state")[-1]["handsfree"]["reason"] == "starting: downloading the speech model (57 %)"
    r.hub._ptt_down_now("screen", c)
    r.hub.on_audio(c, tone(0.8))
    r.hub._ptt_up("screen")
    await settle(30)
    assert r.says() == [STT_STARTING_REPLY]
    r.end_playback()
    stt.loading, stt.percent = False, None
    stt.last_error = "speech model unavailable: connection reset"
    before = stt.warmups  # the hub warms the engine up once when a radio connects
    hf._next_stt_try = 0.0
    hf.tick(time.monotonic())
    await settle(10)
    assert hf.unavailable_reason() == "speech recognition failed to start: speech model unavailable: connection reset"
    assert stt.warmups == before + 1  # retried (the engine backs off on its own); not again within STT_RETRY_S
    hf.tick(time.monotonic())
    await settle(5)
    assert stt.warmups == before + 1
    stt.loaded, stt.last_error = True, None
    hf.tick(time.monotonic())
    assert hf.available and r.hub.state()["handsfree"]["reason"] is None
    await r.segment(c, 2)
    assert [t["text"] for t in texts(r.sent[c], "transcript")] == ["what's my fuel?"]
    await r.hub.stop()


async def test_the_diagnostics_carry_each_segments_level_never_its_text() -> None:
    """Review finding 10: the server's speech gate matches the browser (-50 dBFS) and the level is in the diagnostics."""
    r = await rig("What's for dinner tonight?")
    c = await r.client()
    assert hf_mod.SEGMENT_GATE.threshold_dbfs == -50.0
    await r.segment(c, 1, pre_s=0.0, audio=tone(1.0, amp=100))  # -53 dBFS: under the gate
    await r.segment(c, 2)
    diag = r.hub.status()["handsfree_diag"]
    by_seq = {e["seq"]: e for e in diag["events"] if e["event"] in ("rejected", "ignored")}
    assert by_seq[1]["reason"] == "no_speech" and by_seq[1]["level_dbfs"] < -45 and by_seq[1]["voiced_s"] < 0.3
    assert by_seq[2]["reason"] == "not_addressed" and by_seq[2]["level_dbfs"] > -25 and by_seq[2]["voiced_s"] > 1
    assert "dinner" not in repr(diag)
    await r.hub.stop()
