"""The radio hub's side of the v0.2.0 policy: every answer is deterministic while the car is moving (plan 4.3,
decision 2), and a seat change drops the unsaid messages about the previous driver's laps (plan 3.6)."""

from __future__ import annotations

from typing import Any

from pitwall.core.live import LiveState
from pitwall.drivers import Driver, DriverPreferences
from pitwall.model.telemetry import CarFrame, Game
from pitwall.voice.hub import MOVING_KPH, RadioClient, RadioHub
from pitwall.voice.scheduler import RadioScheduler
from pitwall.voice.types import MessageKind, Priority, RadioMessage
from tests.unit.test_voice_hub import FakeScheduler, FakeStt, FakeTts, RecordingEngineer, settle, sheet, texts

LLM_QUESTION = "where am I losing time"  # an LLM intent while stationary (losing_time is not a fast intent)


async def _hub(scheduler: Any | None = None) -> tuple[RadioHub, RecordingEngineer, list[Any]]:
    eng = RecordingEngineer()
    hub = RadioHub(
        LiveState(), eng, FakeStt(), FakeTts(), scheduler or FakeScheduler(), fact_sheet=sheet, to_speech=lambda s: s
    )
    hub.start()
    sent: list[Any] = []

    async def send(item: Any) -> None:
        sent.append(item)

    await hub.connect(RadioClient(send=send))
    return hub, eng, sent


def _frame(hub: RadioHub, speed: float | None) -> None:
    hub.live.on_packet(accepted=True)  # telemetry "live"
    hub.live.on_frame(
        CarFrame(
            game=Game.F1_25,
            t_recv_ns=0,
            speed_kph=speed,
            brake=0.0,
            steering=0.0,
            lap_number=4,
            lap_distance_m=300.0,
        )
    )


async def _ask(hub: RadioHub, question: str) -> None:
    hub.ask_text(question)
    await settle(40)


async def test_every_answer_is_deterministic_while_the_car_is_moving() -> None:
    hub, eng, sent = await _hub()
    _frame(hub, 212.0)
    assert hub.moving()
    await _ask(hub, LLM_QUESTION)
    assert eng.use_llm[-1] == (LLM_QUESTION, False)
    assert "Copy, checking." not in [m["text"] for m in texts(sent, "say")]
    answer = [m for m in texts(sent, "say") if m["kind"] == "answer"][-1]
    assert answer["meta"]["intent"] == "losing_time"
    await hub.stop()


async def test_the_llm_explains_when_the_car_is_stationary_or_off_track() -> None:
    hub, eng, sent = await _hub()
    await _ask(hub, LLM_QUESTION)  # no telemetry at all: not on track
    assert not hub.moving() and eng.use_llm[-1] == (LLM_QUESTION, True)
    _frame(hub, MOVING_KPH - 0.5)  # creeping in the pit box
    assert not hub.moving()
    await _ask(hub, LLM_QUESTION + "?")
    assert eng.use_llm[-1] == (LLM_QUESTION + "?", True)
    assert [m["text"] for m in texts(sent, "say")].count("Copy, checking.") == 2
    _frame(hub, MOVING_KPH)
    assert hub.moving()
    await hub.stop()


async def test_an_unknown_speed_on_track_counts_as_moving() -> None:
    hub, eng, _sent = await _hub()
    _frame(hub, None)
    assert hub.moving()
    await _ask(hub, LLM_QUESTION)
    assert eng.use_llm[-1] == (LLM_QUESTION, False)
    _frame(hub, float("nan"))
    assert hub.moving()
    await hub.stop()


def _msg(msg_id: str, kind: MessageKind, priority: Priority = Priority.NORMAL) -> RadioMessage:
    return RadioMessage(msg_id, kind, priority, f"Message {msg_id}.", f"Message {msg_id}.", 0.0, expires_mono=None)


def _driver(driver_id: int, name: str) -> Driver:
    return Driver(driver_id, name, 0.0, DriverPreferences(skill_level="advanced"))


async def test_a_seat_change_drops_the_previous_drivers_lap_messages() -> None:
    sched = RadioScheduler("detailed")
    hub, _eng, _sent = await _hub(sched)
    assert hub._tick_task is not None
    hub._tick_task.cancel()  # nothing is dispatched while the test looks at the queue
    hub.apply_driver(_driver(1, "James"))  # the first call only says who is in the seat
    for m in (
        _msg("sum", MessageKind.LAP_SUMMARY),
        _msg("goal", MessageKind.GOAL),
        _msg("coach", MessageKind.COACHING),
        _msg("strat", MessageKind.STRATEGY),
        _msg("info", MessageKind.INFO, Priority.LOW),
        _msg("fuel", MessageKind.ALERT, Priority.HIGH),
    ):
        assert sched.enqueue(m)
    hub.apply_driver(_driver(1, "James"))  # James edits his profile: same driver, nothing dropped
    assert len(sched.pending()) == 6
    hub._held = (_msg("held", MessageKind.LAP_SUMMARY), None, None)  # synthesised, waiting for a speak window
    hub.apply_driver(_driver(2, "Sam"))
    assert sorted(m.id for m in sched.pending()) == ["fuel", "info", "strat"]  # about the car: kept
    assert hub._held is None
    hub._held = (_msg("held-strat", MessageKind.STRATEGY), None, None)
    hub.apply_driver(None)  # the seat is empty now
    assert hub._held is not None  # a strategy call is about the car
    await hub.stop()
