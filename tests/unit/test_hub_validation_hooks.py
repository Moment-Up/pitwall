"""Radio hub hooks of the rig validation kit: each observer event fires with its keys, nothing is built without an
observer, a broken observer never affects the radio, and the command handler answers before the engineer."""

from __future__ import annotations

import time
from typing import Any

from pitwall.coach.cues import CueEvent, CueKind, CueSpec
from pitwall.voice.types import MessageKind, Priority, RadioMessage
from tests.unit.test_voice_hub import make_hub, pcm, settle, texts

KEYS: dict[str, set[str]] = {
    "transcript": {"text", "stt_ms", "audio_s", "ptt_source"},
    "answer": {"msg_id", "question", "text", "intent", "grounded", "fallback", "llm", "use_llm", "engineer_ms"},
    "command": {"msg_id", "question", "text"},
    "synth": {"msg_id", "kind", "engine", "neural", "synth_ms", "fallback_reason"},
    "proactive": {"msg_id", "kind", "priority", "text", "lap_number", "meta", "needs_speak_window", "held_s", "state"},
    "deliver": {"msg_id", "kind", "n_bytes", "audio_clients", "device_clients", "cancelled_id"},
    "playback": {"msg_id", "state", "client", "device_tts", "output_s", "frame", "latency"},
    "cue": {
        "seq",
        "status",
        "reason",
        "msg_id",
        "corner",
        "text",
        "kind",
        "focus",
        "lap",
        "fired_lap",
        "target_m",
        "aim_m",
        "d_m",
        "speed_kph",
        "ttg_s",
        "latency_s",
        "word_offset_s",
        "path",
        "ref_lap_id",
        "engine",
    },
    "cue_timing": {"seq", "error_m", "latency_ms", "output_ms", "output_reported", "predicted_latency_ms"},
}


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, kind: str, payload: dict[str, Any]) -> None:
        self.events.append((kind, payload))

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [p for k, p in self.events if k == kind]


def check_keys(rec: Recorder, kind: str) -> dict[str, Any]:
    (p,) = rec.of(kind)
    assert set(p) == KEYS[kind] | {"t_mono", "t_unix"}, kind
    return p


async def test_question_round_trip_fires_each_hook_once() -> None:
    hub, client, _sent, _stt, _ = await make_hub("how are my tyres")
    rec = Recorder()
    hub.add_observer(rec)
    hub.add_observer(rec)  # idempotent
    await hub.on_text(client, {"type": "ptt", "down": True})
    hub.on_audio(client, pcm(1.0))
    await hub.on_text(client, {"type": "ptt", "down": False})
    await settle()
    t = check_keys(rec, "transcript")
    assert t["text"] == "how are my tyres" and t["ptt_source"] == "screen" and t["audio_s"] == 1.0
    a = check_keys(rec, "answer")
    assert a["intent"] == "tyres" and a["use_llm"] is False and a["llm"] is False
    s = check_keys(rec, "synth")
    assert s["msg_id"] == a["msg_id"] and s["engine"] == "fake-tts" and s["kind"] == "answer"
    d = check_keys(rec, "deliver")
    assert d["msg_id"] == a["msg_id"] and d["n_bytes"] > 0 and d["audio_clients"] == 1 and d["cancelled_id"] is None
    await hub.on_text(client, {"type": "playback", "id": a["msg_id"], "state": "started"})
    p = check_keys(rec, "playback")
    assert p["state"] == "started" and p["latency"]["to_playback_ms"] is not None and p["frame"] is None
    hub.remove_observer(rec)
    await hub.on_text(client, {"type": "playback", "id": a["msg_id"], "state": "ended"})
    assert len(rec.of("playback")) == 1
    await hub.stop()


async def test_no_observer_builds_nothing_and_a_broken_observer_changes_nothing() -> None:
    hub, _client, sent, _stt, _ = await make_hub()
    built: list[str] = []
    hub._observe("x", lambda: built.append("x") or {})  # type: ignore[func-returns-value]
    assert built == []

    def broken(kind: str, payload: dict[str, Any]) -> None:
        raise RuntimeError("observer bug")

    hub.add_observer(broken)
    hub.ask_text("how are my tyres")
    await settle()
    assert [m for m in texts(sent, "say") if m["kind"] == "answer"]  # the answer still went out
    hub.add_observer(lambda k, p: built.append(k))
    hub._observe("x", lambda: 1 / 0)  # type: ignore[arg-type,return-value]  # a failing builder is contained
    await hub.stop()


async def test_proactive_message_hook() -> None:
    hub, _client, _sent, _stt, sched = await make_hub()
    rec = Recorder()
    hub.add_observer(rec)
    now = time.monotonic()
    sched.enqueue(
        RadioMessage(
            "p1",
            MessageKind.COACHING,
            Priority.NORMAL,
            "Turn 3: brake later",
            "Turn 3, brake later",
            now,
            lap_number=4,
            meta={"lap_id": 77, "observation_id": "T3:brake_early:4"},
        )
    )
    await settle(40)
    p = check_keys(rec, "proactive")
    assert p["meta"] == {"lap_id": 77, "observation_id": "T3:brake_early:4"} and p["needs_speak_window"] is True
    assert p["state"]["on_track"] is False and p["held_s"] >= 0.0
    assert rec.of("deliver")[0]["msg_id"] == "p1"
    await hub.stop()


def cue_event(seq: int = 1) -> CueEvent:
    spec = CueSpec("T1", CueKind.BRAKE, 1000.0, "T1 brake", ("T1", "brake"), 1)
    now = time.monotonic()
    return CueEvent(seq, spec, 3, 3, now, None, 900.0, 80.0, 1.25, 0.25, 0.3, "device", 995.0, 12)


async def test_cue_hooks_sent_dropped_and_timing() -> None:
    hub, client, _sent, _stt, _ = await make_hub()
    client.device_tts = True  # the device speaks the call: no server audio needed
    rec = Recorder()
    hub.add_observer(rec)
    ev = cue_event(1)
    assert hub.deliver_cue(ev, ev.fired_mono) is None
    c = check_keys(rec, "cue")
    assert c["status"] == "sent" and c["seq"] == 1 and c["target_m"] == 1000.0 and c["engine"] is None
    assert c["speed_kph"] == 288.0 and c["ref_lap_id"] == 12 and c["msg_id"]
    await hub.on_text(client, {"type": "playback", "id": c["msg_id"], "state": "started"})
    t = check_keys(rec, "cue_timing")
    assert t["seq"] == 1 and t["error_m"] is None and t["latency_ms"] >= 0
    hub.voice_enabled = False
    ev2 = cue_event(2)
    assert hub.deliver_cue(ev2, ev2.fired_mono) == "voice off"
    dropped = rec.of("cue")[-1]
    assert dropped["status"] == "dropped" and dropped["reason"] == "voice off" and dropped["msg_id"] is None
    await hub.stop()


async def test_command_handler_answers_before_the_engineer() -> None:
    hub, _client, sent, _stt, _ = await make_hub()
    rec = Recorder()
    hub.add_observer(rec)
    asked: list[str] = []

    def handler(text: str) -> str | None:
        asked.append(text)
        if text == "boom":
            raise RuntimeError("handler bug")
        return "Next test: push-to-talk." if text == "next test" else None

    hub.command_handler = handler
    hub.ask_text("next test")
    await settle()
    say = texts(sent, "say")[-1]
    assert (
        say["kind"] == "control" and say["text"] == "Next test: push-to-talk." and say["meta"]["intent"] == "validation"
    )
    cmd = check_keys(rec, "command")
    assert cmd["question"] == "next test" and cmd["msg_id"] == say["id"] and not rec.of("answer")
    assert not hub._busy
    hub.ask_text("how are my tyres")  # None: the engineer answers as usual
    await settle()
    assert texts(sent, "say")[-1]["kind"] == "answer" and len(rec.of("answer")) == 1
    hub.ask_text("boom")  # a failing handler falls through to the engineer
    await settle()
    assert asked == ["next test", "how are my tyres", "boom"] and len(rec.of("answer")) == 2
    await hub.stop()
