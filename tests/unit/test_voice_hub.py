"""Radio hub: push-to-talk (screen + wheel), half-duplex gate, barge-in, question pipeline, quiet control,
proactive release, and slow-client isolation. Uses fake STT/TTS/scheduler so it is fast and deterministic."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from pitwall.ai.engineer import RaceEngineer
from pitwall.ai.facts import FactSheet
from pitwall.core.live import LiveState
from pitwall.model.telemetry import CarFrame, Game
from pitwall.voice.hub import UDP_ACTION_BASE, RadioClient, RadioHub, ptt_button_mask
from pitwall.voice.types import AudioClip, DrivingState, MessageKind, Priority, RadioMessage, SttResult

SR = 16_000


def pcm(seconds: float, value: int = 1000) -> bytes:
    return int(value).to_bytes(2, "little", signed=True) * int(seconds * SR)


class FakeStt:
    name = "fake-stt"

    def __init__(self, text: str = "how are my tyres") -> None:
        self.text = text
        self.clips: list[AudioClip] = []

    def warmup(self) -> None:
        return None

    def transcribe(self, clip: AudioClip, prompt: str | None = None) -> SttResult:
        self.clips.append(clip)
        return SttResult(self.text, self.name, 5, clip.duration_s)


class FakeTts:
    name = "fake-tts"
    sample_rate = 22_050

    def synthesize(self, text: str) -> AudioClip:
        return AudioClip(b"\x01\x00" * int(0.5 * self.sample_rate), self.sample_rate)  # 0.5 s


class FakeScheduler:
    def __init__(self) -> None:
        self.queue: list[RadioMessage] = []
        self.quiet: tuple[int | None, bool] | None = None
        self.intensity = "normal"

    def enqueue(self, m: RadioMessage) -> None:
        self.queue.append(m)

    def next_message(self, state: DrivingState, now: float, speaking: bool) -> RadioMessage | None:
        return None if speaking or not self.queue else self.queue.pop(0)

    def set_quiet(self, until_lap: int | None, indefinite: bool) -> None:
        self.quiet = (until_lap, indefinite)

    def resume(self) -> None:
        self.quiet = None

    def set_intensity(self, i: str) -> None:
        self.intensity = i

    def quiet_state(self, lap: int | None) -> dict[str, Any]:
        return {"until_lap": self.quiet[0] if self.quiet else None, "indefinite": bool(self.quiet and self.quiet[1])}

    def pending(self) -> list[RadioMessage]:
        return list(self.queue)

    def drop_driver_messages(self) -> int:
        kinds = (MessageKind.LAP_SUMMARY, MessageKind.GOAL, MessageKind.COACHING)
        kept = [m for m in self.queue if m.kind not in kinds]
        dropped = len(self.queue) - len(kept)
        self.queue[:] = kept
        return dropped


def sheet() -> FactSheet:
    fs = FactSheet()
    fs.add("tyres", "Tyres: soft, 6 laps old; wear FL 9.1%, FR 10.2%, RL 6.0%, RR 6.3%.")
    fs.add("fuel", "Fuel: using 1.62 kg per lap (median of 4 green laps).")
    return fs


async def make_hub(
    stt_text: str = "how are my tyres",
) -> tuple[RadioHub, RadioClient, list[Any], FakeStt, FakeScheduler]:
    live = LiveState()
    stt = FakeStt(stt_text)
    sched = FakeScheduler()
    hub = RadioHub(
        live, RaceEngineer(None), stt, FakeTts(), sched, fact_sheet=sheet, to_speech=lambda s: s, lap_messages=None
    )
    hub.start()
    sent: list[Any] = []

    async def send(item: Any) -> None:
        sent.append(item)

    client = RadioClient(send=send)
    await hub.connect(client)
    return hub, client, sent, stt, sched


async def settle(n: int = 30) -> None:
    for _ in range(n):
        await asyncio.sleep(0.01)


def texts(sent: list[Any], kind: str) -> list[dict[str, Any]]:
    return [m for m in sent if isinstance(m, dict) and m.get("type") == kind]


def test_ptt_mask() -> None:
    assert ptt_button_mask("udp_action_1") == UDP_ACTION_BASE == 0x00100000
    assert ptt_button_mask("udp_action_12") == 0x80000000
    with pytest.raises(ValueError):
        ptt_button_mask("cross")


async def test_screen_ptt_question_round_trip() -> None:
    hub, client, sent, stt, _ = await make_hub("how are my tyres")
    hub.on_audio(client, pcm(1.0))  # not listening: discarded
    await hub.on_text(client, {"type": "ptt", "down": True})
    hub.on_audio(client, pcm(1.2))
    await hub.on_text(client, {"type": "ptt", "down": False})
    await settle()
    assert len(stt.clips) == 1 and stt.clips[0].duration_s == pytest.approx(1.2, abs=0.01)
    assert texts(sent, "transcript")[0]["text"] == "how are my tyres"
    say = [m for m in texts(sent, "say") if m["kind"] == "answer"][-1]
    assert "FL 9.1%" in say["text"] and say["n_bytes"] == 2 * int(0.5 * 22_050)
    i = sent.index(say)
    audio = [x for x in sent[i + 1 :] if isinstance(x, bytes)]
    assert sum(len(a) for a in audio) == say["n_bytes"]
    assert any(isinstance(m, dict) and m.get("type") == "say_end" and m["id"] == say["id"] for m in sent[i:])
    assert hub.latency and hub.latency[0].stt_ms == 5 and hub.latency[0].to_first_audio_ms is not None
    await hub.stop()


async def test_fast_intent_skips_ack_but_llm_intent_acknowledges() -> None:
    hub, _client, sent, _, _ = await make_hub()
    hub.ask_text("what's my fuel situation")
    await settle()
    assert not [m for m in texts(sent, "say") if m["text"] == "Copy, checking."]
    hub.ask_text("where am I losing time")
    await settle()
    assert [m for m in texts(sent, "say") if m["text"] == "Copy, checking."]
    await hub.stop()


async def test_half_duplex_gate_and_barge_in() -> None:
    hub, client, sent, stt, _ = await make_hub()
    hub.ask_text("how are my tyres")
    await settle()
    assert hub.speaking_id is not None
    speaking = hub.speaking_id
    # PTT while the engineer is talking = barge-in: cancel + listen
    await hub.on_text(client, {"type": "ptt", "down": True})
    assert hub.speaking_id is None
    await settle(5)
    assert texts(sent, "cancel")[-1]["id"] == speaking
    hub.on_audio(client, pcm(0.5))  # within the barge-in gate -> discarded (engineer still audible)
    await asyncio.sleep(0.2)
    hub.on_audio(client, pcm(0.6))
    await hub.on_text(client, {"type": "ptt", "down": False})
    await settle()
    assert stt.clips[-1].duration_s == pytest.approx(0.6, abs=0.01)
    await hub.stop()


async def test_playback_ended_releases_gate_after_tail() -> None:
    hub, client, _sent, _, _ = await make_hub()
    hub.ask_text("how are my tyres")
    await settle()
    mid = hub.speaking_id
    assert mid
    await hub.on_text(client, {"type": "playback", "id": mid, "state": "started"})
    await hub.on_text(client, {"type": "playback", "id": mid, "state": "ended"})
    assert hub.speaking_id is None
    await hub.stop()


async def test_wheel_ptt_via_button_events() -> None:
    hub, client, _sent, stt, _ = await make_hub("fuel")
    hub.on_audio(client, pcm(0.1))  # marks the device mic as live
    hub._on_button(UDP_ACTION_BASE | 0x1)  # UDP Action 1 + another button
    assert hub.ptt_down and hub.ptt_source == "wheel"
    hub.on_audio(client, pcm(0.8))
    hub._on_button(0x1)  # action released, other button still held
    await settle()
    assert not hub.ptt_down and stt.clips[-1].duration_s == pytest.approx(0.8, abs=0.01)
    await hub.stop()


async def test_short_blip_is_ignored_and_max_length_auto_stops() -> None:
    hub, client, _sent, stt, _ = await make_hub()
    await hub.on_text(client, {"type": "ptt", "down": True})
    hub.on_audio(client, pcm(0.1))
    await hub.on_text(client, {"type": "ptt", "down": False})
    await settle()
    assert stt.clips == []
    hub.max_utterance_s = 1.0
    await hub.on_text(client, {"type": "ptt", "down": True})
    for _ in range(40):
        hub.on_audio(client, pcm(0.032))
    await settle()
    assert not hub.ptt_down and stt.clips and stt.clips[-1].duration_s <= 1.05
    await hub.stop()


async def test_quiet_command_sets_scheduler_quiet_relative_to_current_lap() -> None:
    hub, _client, sent, _, sched = await make_hub()
    hub.live.on_frame(CarFrame(game=Game.F1_25, t_recv_ns=0, lap_number=5, lap_distance_m=100.0))
    hub.ask_text("stop talking for 2 laps")
    await settle()
    assert sched.quiet == (7, False)
    ack = texts(sent, "say")[-1]
    assert ack["kind"] == "control" and "quiet" in ack["text"].lower()
    hub.ask_text("ok you can talk again")
    await settle()
    assert sched.quiet is None
    await hub.stop()


async def test_proactive_message_released_by_tick() -> None:
    hub, _client, sent, _, sched = await make_hub()
    sched.enqueue(
        RadioMessage(
            id="p1",
            kind=MessageKind.LAP_SUMMARY,
            priority=Priority.NORMAL,
            text="Lap 4, 1:05.706.",
            speech="Lap 4",
            created_mono=0.0,
        )
    )
    await asyncio.sleep(0.3)
    assert [m for m in texts(sent, "say") if m["id"] == "p1"]
    await hub.stop()


async def test_slow_client_drops_instead_of_blocking() -> None:
    hub, _client, sent, _, _ = await make_hub()
    blocked = asyncio.Event()

    async def never(item: Any) -> None:
        await blocked.wait()

    slow = RadioClient(send=never)
    slow.queue = asyncio.Queue(maxsize=3)
    await hub.connect(slow)
    hub.ask_text("how are my tyres")
    await settle()
    assert slow.dropped > 0  # the slow device lost frames...
    assert texts(sent, "say")  # ...while the healthy one got everything
    await hub.stop()


async def test_empty_transcript_asks_to_repeat() -> None:
    hub, client, sent, _, _ = await make_hub("")
    await hub.on_text(client, {"type": "ptt", "down": True})
    hub.on_audio(client, pcm(1.0))
    await hub.on_text(client, {"type": "ptt", "down": False})
    await settle()
    assert texts(sent, "say")[-1]["text"] == "Say again?"
    await hub.stop()


def _null_stt_hub() -> RadioHub:
    from pitwall.voice.stt import NullStt

    return RadioHub(
        LiveState(),
        RaceEngineer(None),
        NullStt("server speech recognition (Parakeet) needs an Apple-silicon Mac"),
        FakeTts(),
        FakeScheduler(),
        fact_sheet=sheet,
        to_speech=lambda s: s,
        lap_messages=None,
    )


async def test_no_server_stt_on_macos_keeps_say_again(monkeypatch: pytest.MonkeyPatch) -> None:
    """macOS behaviour is unchanged without server STT: the utterance goes to NullStt, which hears nothing."""
    import pitwall.voice.hub as hub_mod

    monkeypatch.setattr(hub_mod, "is_windows", lambda: False)
    hub = _null_stt_hub()
    hub.start()
    sent: list[Any] = []

    async def send(item: Any) -> None:
        sent.append(item)

    client = RadioClient(send=send)
    await hub.connect(client)
    assert hub.state()["stt_reason"]  # the state still says why (additive field)
    await hub.on_text(client, {"type": "ptt", "down": True})
    hub.on_audio(client, pcm(1.0))
    await hub.on_text(client, {"type": "ptt", "down": False})
    await settle()
    assert not texts(sent, "error")
    assert texts(sent, "say")[-1]["text"] == "Say again?"
    await hub.stop()


async def test_no_server_stt_says_why_instead_of_say_again(monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows (no Parakeet): a push-to-talk question gets the reason and a way forward, once, and is never sent to
    an engine that cannot hear it."""
    import pitwall.voice.hub as hub_mod
    from pitwall.voice.hub import NO_STT_REPLY
    from pitwall.voice.stt import NullStt

    monkeypatch.setattr(hub_mod, "is_windows", lambda: True)
    hub = RadioHub(
        LiveState(),
        RaceEngineer(None),
        NullStt("server speech recognition (Parakeet) needs an Apple-silicon Mac"),
        FakeTts(),
        FakeScheduler(),
        fact_sheet=sheet,
        to_speech=lambda s: s,
        lap_messages=None,
    )
    hub.start()
    sent: list[Any] = []

    async def send(item: Any) -> None:
        sent.append(item)

    client = RadioClient(send=send)
    await hub.connect(client)
    assert hub.state()["stt"] == "none" and "Apple-silicon" in hub.state()["stt_reason"]
    await hub.on_text(client, {"type": "ptt", "down": True})
    hub.on_audio(client, pcm(1.0))
    await hub.on_text(client, {"type": "ptt", "down": False})
    await settle()
    errors = texts(sent, "error")
    assert len(errors) == 1 and "Voice questions are unavailable" in errors[0]["message"]
    assert "Apple-silicon Mac" in errors[0]["message"]
    assert [m["text"] for m in texts(sent, "say")] == [NO_STT_REPLY]
    assert not texts(sent, "transcript") and not hub.history  # nothing was "heard"
    hub.ask_text("how are my tyres")  # typed questions still work
    await settle()
    assert any("FL 9.1%" in m["text"] for m in texts(sent, "say"))
    await hub.stop()


async def test_working_stt_has_no_stt_reason() -> None:
    hub, _client, _sent, _, _ = await make_hub()
    assert hub.state()["stt_reason"] is None
    await hub.stop()


async def test_device_tts_client_gets_text_only_and_gate_still_applies() -> None:
    hub, client, sent, _, _ = await make_hub()
    calls: list[str] = []
    real = hub.tts.synthesize

    def counting(text: str) -> AudioClip:
        calls.append(text)
        return real(text)

    hub.tts.synthesize = counting  # type: ignore[method-assign]
    await hub.on_text(client, {"type": "hello", "client": "ipad", "tts_mode": "device"})
    hub.ask_text("how are my tyres")
    await settle()
    say = [m for m in texts(sent, "say") if m["kind"] == "answer"][-1]
    assert say["n_bytes"] == 0 and say["device_tts"] is True and "FL 9.1%" in say["speech"]
    assert not [x for x in sent if isinstance(x, bytes)]
    assert calls == []  # no Mac synthesis needed when every device speaks for itself
    assert hub.speaking_id == say["id"]  # half-duplex gate covers device speech too
    await hub.on_text(client, {"type": "playback", "id": say["id"], "state": "ended"})
    assert hub.speaking_id is None
    await hub.stop()


async def test_proactive_message_held_while_braking_then_delivered_when_calm() -> None:
    hub, _client, sent, _, sched = await make_hub()
    assert hub._tick_task is not None
    hub._tick_task.cancel()  # drive _tick manually for determinism (client stays connected)

    def frame(brake: float, steer: float = 0.0) -> None:
        hub.live.on_packet(accepted=True)  # telemetry "live"
        hub.live.on_frame(
            CarFrame(
                game=Game.F1_25,
                t_recv_ns=0,
                brake=brake,
                steering=steer,
                speed_kph=250.0,
                lap_number=3,
                lap_distance_m=500.0,
            )
        )

    sched.enqueue(
        RadioMessage(
            id="p9",
            kind=MessageKind.LAP_SUMMARY,
            priority=Priority.NORMAL,
            text="Lap 3, 1:05.9.",
            speech="Lap 3",
            created_mono=asyncio.get_running_loop().time(),
        )
    )
    frame(brake=0.9)  # driver hits the brakes while the message is being synthesised
    await hub._tick(time.monotonic())
    assert hub._held is not None and not [m for m in texts(sent, "say") if m["id"] == "p9"]
    frame(brake=0.9, steer=0.4)
    await hub._tick(time.monotonic())
    assert hub._held is not None  # still mid-corner
    frame(brake=0.0)
    await hub._tick(time.monotonic())
    await settle(5)
    assert hub._held is None and [m for m in texts(sent, "say") if m["id"] == "p9"]


def test_time_to_next_braking_treats_entered_zone_as_now() -> None:
    from pitwall.voice.hub import time_to_next_braking

    model = {
        "length_m": 4000.0,
        "corners": [{"entry_m": 707.0, "exit_m": 860.0}, {"entry_m": 1215.0, "exit_m": 1345.0}],
    }
    assert time_to_next_braking(model, 708.4, 330.0) == 0.0  # just started braking: zone is NOW
    assert time_to_next_braking(model, 700.0, 330.0) == 0.0  # within the lead before the braking point
    t = time_to_next_braking(model, 300.0, 360.0)  # 100 m/s, (707-15-300) m away
    assert t == pytest.approx((707 - 15 - 300) / 100.0)
    wrap = time_to_next_braking(model, 3900.0, 360.0)  # next zone is T1 of the next lap
    assert wrap == pytest.approx((4000 - 3900 + 707 - 15) / 100.0)
    assert time_to_next_braking({"corners": []}, 10.0, 200.0) == float("inf")


# ---------------------------------------------------------------------------------------------- game capabilities
class NoLlmEngineer(RaceEngineer):
    """Fails the test if the radio ever asks for an LLM answer."""

    async def answer(
        self, question: str, sheet: Any, history: Any = None, use_llm: bool = True, short: bool = False
    ) -> Any:
        assert not use_llm, question
        assert short, question  # the radio always asks for the short (spoken) answer
        return await super().answer(question, sheet, history, use_llm=False, short=short)


async def _hub_without_session(selected: str | None) -> tuple[RadioHub, list[Any]]:
    from pitwall import games

    live = LiveState()
    if selected is not None:
        live.set_game_selection(games.Selection(selected, 0.0, "dashboard"))
    hub = RadioHub(
        live,
        NoLlmEngineer(None),
        FakeStt(),
        FakeTts(),
        FakeScheduler(),
        fact_sheet=lambda: None,  # no session recorded yet
        to_speech=lambda s: s,
        lap_messages=None,
    )
    hub.start()
    sent: list[Any] = []

    async def send(item: Any) -> None:
        sent.append(item)

    await hub.connect(RadioClient(send=send))
    return hub, sent


async def test_capability_question_with_no_session_answers_from_the_selected_game() -> None:
    hub, sent = await _hub_without_session("ac:ps5")
    hub.ask_text("how are my tyres")
    await settle()
    said = [m["text"] for m in texts(sent, "say")]
    assert "Copy, checking." not in said
    assert said[-1] == "Assetto Corsa doesn't send tyre temperatures, tyre wear, tyre pressures or brake temperatures."
    hub.ask_text("is it going to rain")
    await settle()
    assert [m["text"] for m in texts(sent, "say")][-1] == "Assetto Corsa doesn't send weather."
    hub.ask_text("where am I losing time")  # not about the game: still needs a session
    await settle()
    assert [m["text"] for m in texts(sent, "say")][-1] == "No session data yet. Get a lap in and ask me again."
    await hub.stop()


async def test_capability_question_with_a_game_that_sends_it_waits_for_a_session() -> None:
    hub, sent = await _hub_without_session("gt7:ps5")
    hub.ask_text("how are my tyres")  # GT7 sends tyre temperatures: not a capability-only answer
    await settle()
    assert [m["text"] for m in texts(sent, "say")][-1] == "No session data yet. Get a lap in and ask me again."
    hub.ask_text("what's my fuel situation")  # GT7 fuel is not read yet: a known fact
    await settle()
    assert [m["text"] for m in texts(sent, "say")][-1].startswith("GT7 sends a fuel level, but sources disagree")
    await hub.stop()


async def test_nothing_selected_asks_which_game() -> None:
    hub, sent = await _hub_without_session(None)
    hub.ask_text("how are my tyres")
    await settle()
    msg = texts(sent, "say")[-1]
    assert msg["text"].startswith("Tell me which game you're playing") and msg["kind"] == "control"
    assert "Copy, checking." not in [m["text"] for m in texts(sent, "say")]
    await hub.stop()


class RecordingEngineer(RaceEngineer):
    """Records whether the radio asked for an LLM answer; answers deterministically (no provider)."""

    def __init__(self) -> None:
        super().__init__(None)
        self.use_llm: list[tuple[str, bool]] = []

    async def answer(
        self, question: str, sheet: Any, history: Any = None, use_llm: bool = True, short: bool = False
    ) -> Any:
        self.use_llm.append((question, use_llm))
        return await super().answer(question, sheet, history, use_llm=False, short=short)


async def test_f1_questions_about_data_it_sends_go_to_the_llm_path() -> None:
    """F1 25 sends flags, ERS and sectors: "Any yellow flags?" is not a known "not sent" fact, so it gets the usual
    LLM path ("Copy, checking." first), and never the canned "complete a few clean laps"."""
    from pitwall import games
    from pitwall.ai.facts import build_fact_sheet

    from .test_ai import _game_analysis

    f1_sheet = build_fact_sheet(_game_analysis("f1_25", "ps5"))
    live = LiveState()
    live.set_game_selection(games.Selection("f1_25:ps5", 0.0, "dashboard"))
    eng = RecordingEngineer()
    hub = RadioHub(live, eng, FakeStt(), FakeTts(), FakeScheduler(), fact_sheet=lambda: f1_sheet, to_speech=lambda s: s)
    hub.start()
    sent: list[Any] = []

    async def send(item: Any) -> None:
        sent.append(item)

    await hub.connect(RadioClient(send=send))
    for q in ("Any yellow flags?", "How much battery do I have?"):
        hub.ask_text(q)
        await settle(60)
        assert (q, True) in eng.use_llm, q
    hub.ask_text("What were my splits?")  # race radio: sector deltas are a fast, deterministic answer now
    await settle(60)
    assert ("What were my splits?", False) in eng.use_llm
    said = [m["text"] for m in texts(sent, "say")]
    assert "Copy, checking." in said
    assert not any("complete a few clean laps" in t for t in said), said
    await hub.stop()


# ---------------------------------------------------------------- lap summary: the session's best clean lap
def _clean_lap(n: int, ms: int) -> dict[str, Any]:
    return {"lap_id": 100 + n, "lap_number": n, "lap_time_ms": ms, "valid": True, "clean": True, "flags": []}


async def _summary_after_lap_25(d2_session_best_ms: int | None) -> str:
    """A 25-lap session whose fastest clean lap (lap 2, 1:20.000) is older than the snapshot's 20 laps; lap 25
    (1:20.500) is the fastest of those 20."""
    from pitwall.voice.proactive import lap_messages

    live = LiveState()
    sched = FakeScheduler()
    hub = RadioHub(live, RaceEngineer(None), FakeStt(), FakeTts(), sched, sheet, lambda s: s, lap_messages=lap_messages)
    live.reset_session("s1", "test", False)
    for n in range(1, 26):
        live.laps.appendleft(_clean_lap(n, 80_000 if n == 2 else 80_500 if n == 25 else 81_000 + n))
    if d2_session_best_ms is not None:  # D2 (repo.lap_bests): every clean lap of this session, from the database
        live.bests = {"session": {"lap_ms": d2_session_best_ms, "sectors_ms": [None, None, None]}}
    hub._enqueue_lap({"lap": live.laps[0], "observations": []})
    summaries = [m.text for m in sched.queue if m.kind is MessageKind.LAP_SUMMARY]
    assert len(summaries) == 1
    return summaries[0]


async def test_a_lap_slower_than_an_earlier_one_is_not_the_session_best_after_lap_20() -> None:
    """The snapshot holds only the latest 20 laps: from lap 21 on, the best of those was called "personal best"
    (or "session best") although an earlier lap of the session was faster. The session's D2 best covers them."""
    assert await _summary_after_lap_25(80_000) == "That lap, 1:20.500."
    # D2 not published yet (track unknown): the recent laps alone, as before
    assert await _summary_after_lap_25(None) == "That lap, 1:20.500, personal best."
    # D2 not including this lap yet: this lap is still the best
    assert await _summary_after_lap_25(80_600) == "That lap, 1:20.500, personal best."


# ---------------------------------------------------------------- Setup › Controls: push-to-talk follows the layout
async def test_ptt_actions_swap_without_a_restart() -> None:
    hub, client, sent, _stt, _ = await make_hub("fuel")
    assert hub.ptt_actions == [1] and hub.state()["ptt_actions"] == [1] and hub.state()["ptt_label"] is None
    hub.set_ptt_actions([3, 1], "Right thumb button")
    assert hub.ptt_mask == (UDP_ACTION_BASE << 2) | UDP_ACTION_BASE
    await settle()
    assert texts(sent, "state")[-1]["ptt_actions"] == [3, 1]
    assert texts(sent, "state")[-1]["ptt_label"] == "Right thumb button"
    hub.on_audio(client, pcm(0.1))
    hub._on_button(UDP_ACTION_BASE << 2)  # UDP Action 3 now talks
    assert hub.ptt_down and hub.ptt_source == "wheel"
    hub._on_button(0)
    hub.set_ptt_actions([], None)  # never left with no wheel button
    assert hub.ptt_actions == [3, 1]
    await hub.stop()


async def test_a_held_wheel_transmission_ends_when_its_action_leaves_the_mask() -> None:
    hub, client, _sent, _stt, _ = await make_hub("fuel")
    hub.on_audio(client, pcm(0.1))
    hub._on_button(UDP_ACTION_BASE)
    assert hub.ptt_down
    hub.set_ptt_actions([3], None)  # UDP Action 1 is no longer push-to-talk
    assert not hub.ptt_down
    hub.set_ptt_actions([3, 1], None)
    hub._on_button(UDP_ACTION_BASE)  # still held: no new edge, no new transmission
    assert not hub.ptt_down
    await hub.stop()


async def test_the_button_test_pauses_wheel_ptt_and_the_pause_lapses() -> None:
    hub, client, _sent, _stt, _ = await make_hub("fuel")
    hub.on_audio(client, pcm(0.1))
    hub._on_button(UDP_ACTION_BASE)
    hub.suspend_wheel_ptt(True)
    assert not hub.ptt_down and hub.state()["wheel_ptt_paused"]  # a held transmission ends
    hub._on_button(0)
    hub._on_button(UDP_ACTION_BASE)
    assert not hub.ptt_down  # a press during the test never opens the radio
    hub._on_button(0)
    hub.suspend_wheel_ptt(True, for_s=-1.0)  # lapsed (the page stopped polling)
    hub._on_button(UDP_ACTION_BASE)
    assert hub.ptt_down
    hub._on_button(0)
    hub.suspend_wheel_ptt(False)
    assert not hub.state()["wheel_ptt_paused"]
    await hub.stop()


async def test_which_button_is_answered_without_a_session() -> None:
    """ "Which button is brake bias?" needs the saved layout, not a lap: answered at once, never the LLM."""
    live = LiveState()
    sched = FakeScheduler()
    eng = RaceEngineer(None)
    eng.controls_handler = lambda _i, q: "In your layout, brake bias + is R3 tab and − is L3 tab."
    hub = RadioHub(
        live, eng, FakeStt(), FakeTts(), sched, fact_sheet=lambda: None, to_speech=lambda s: s, lap_messages=None
    )
    hub.start()
    sent: list[Any] = []

    async def send(item: Any) -> None:
        sent.append(item)

    await hub.connect(RadioClient(send=send))
    hub.ask_text("Which button is brake bias?")
    await settle()
    said = [m for m in hub.history if m["role"] == "engineer"]
    assert said and said[0]["text"].startswith("In your layout, brake bias +")
    assert not any("Copy, checking." in str(m) for m in sent)
    await hub.stop()
