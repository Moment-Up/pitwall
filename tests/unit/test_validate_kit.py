"""ValidationKit: radio prompts (spec 6.5), item navigation and voice commands on a fake runtime and radio."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pitwall.core.live import LiveState
from pitwall.validate.catalog import BY_ID
from pitwall.validate.kit import PROMPT_GAP_S, PROMPT_TTL_S, KitError, ValidationKit
from pitwall.voice.types import MessageKind, Priority, RadioMessage


class _Drivers:
    active_id = 1

    def list_drivers(self) -> list[Any]:
        return [object()]

    def subscribe(self, fn: Any) -> None:
        pass

    def unsubscribe(self, fn: Any) -> None:
        pass


class FakeRadio:
    def __init__(self) -> None:
        self.stt = SimpleNamespace(name="scripted")
        self.tts = SimpleNamespace(name="kokoro")
        self.clients: list[Any] = [object()]
        self.observers: list[Any] = []
        self.command_handler: Any = None
        self.queued: list[RadioMessage] = []
        self.scheduler = SimpleNamespace(enqueue=self.queued.append)

    def state(self) -> dict[str, Any]:
        return {"stt_reason": None}

    def to_speech(self, text: str) -> str:
        return text

    def add_observer(self, fn: Any) -> None:
        self.observers.append(fn)

    def remove_observer(self, fn: Any) -> None:
        self.observers.remove(fn)


@pytest.fixture
async def kit(tmp_path: Path) -> AsyncIterator[tuple[ValidationKit, FakeRadio]]:
    rt = SimpleNamespace(
        live=LiveState(),
        drivers=_Drivers(),
        input_status=lambda: [],
        settings=SimpleNamespace(data_dir=tmp_path, llm_enabled=False),
    )
    radio = FakeRadio()
    k = ValidationKit(rt.settings, rt, radio, asyncio.get_running_loop())
    assert radio.command_handler == k.voice_command
    yield k, radio
    await k.close()
    assert radio.command_handler is None


async def test_briefs_are_rate_limited_and_wait_for_a_speak_window(kit: tuple[ValidationKit, FakeRadio]) -> None:
    k, radio = kit
    run = k.start_run(["ipad_home_screen", "radio_ptt", "gt7_ps5"], None, True)
    (brief,) = radio.queued
    assert brief.text == BY_ID["ipad_home_screen"].radio_brief and brief.kind is MessageKind.CONTROL
    assert brief.priority is Priority.NORMAL and brief.needs_speak_window and not brief.bypass_quiet
    assert brief.meta == {"topic": "validation"} and brief.expires_mono == pytest.approx(
        brief.created_mono + PROMPT_TTL_S
    )
    k.set_current(run.id, "radio_ptt")
    k.set_current(run.id, "gt7_ps5")
    assert len(radio.queued) == 1  # within 30 s: only the newest brief waits
    k._last_prompt_mono -= PROMPT_GAP_S + 1
    k.flush_prompt(0.0)
    assert [m.text for m in radio.queued][1] == BY_ID["gt7_ps5"].radio_brief
    k._verdict_prompt("gt7_ps5", "pass")
    k._verdict_prompt("gt7_ps5", "fail")  # once per item
    k._last_prompt_mono -= PROMPT_GAP_S + 1
    k.flush_prompt(0.0)
    assert radio.queued[-1].text == "Gran Turismo 7: enough data. Say worked or didn't work, or tap on the iPad."
    assert len(radio.queued) == 3


async def test_no_radio_or_prompts_off_means_silence(kit: tuple[ValidationKit, FakeRadio]) -> None:
    k, radio = kit
    radio.clients = []
    run = k.start_run(["ipad_home_screen", "gt7_ps5"], None, True)
    assert radio.queued == [] and k._pending_prompt is not None
    k._pending_prompt = (k._pending_prompt[0], k._pending_prompt[1], k._pending_prompt[2] - PROMPT_TTL_S - 1)
    radio.clients = [object()]
    k.flush_prompt(0.0)
    assert radio.queued == [] and k._pending_prompt is None  # a stale brief is dropped, never said late
    await k.finish(run.id, None)
    k.start_run(["ipad_home_screen"], None, False)
    assert radio.queued == []


async def test_navigation_skip_and_voice_commands(kit: tuple[ValidationKit, FakeRadio]) -> None:
    k, _radio = kit
    assert k.voice_command("next test") == "No validation running. Say start validation."
    assert k.voice_command("where should I brake in turn 3") is None
    reply = k.voice_command("start validation")
    assert reply is not None and reply.startswith("Validation started. First test: screen test.")
    run = k.run
    assert (
        run is not None
        and k.voice_command("start validation") == "Validation is already running. Current test: screen test."
    )
    assert k.voice_command("worked") == "Marked screen test as worked."
    assert run.items[0].marks[-1].source == "voice"
    nxt = k.voice_command("next test")
    assert nxt == "Next test: glance test. Three laps on Drive, Coach. Glance at the iPad as you would in a race."
    assert run.items[0].status == "done" and run.current_item == "ipad_glance"
    k.skip(run.id, "ipad_glance", "no second driver today")
    assert run.items[1].status == "skipped" and run.current_item == "ipad_one_message"
    k.set_current(run.id, "ipad_glance")  # un-skip
    assert run.items[1].status == "current" and run.items[1].skip_reason is None
    with pytest.raises(KitError) as e:
        k.input_check(run.id, "ipad_glance", "left", None)
    assert e.value.status == 409
    status = k.voice_command("what's the test")
    assert status is not None and status.startswith(f"Test 2 of {len(run.selected_items)}: glance test.")
    assert k.voice_command("didn't work") == "Marked glance test as didn't work. Add a note on the iPad when you stop."
    for _ in range(len(run.selected_items)):
        k.next_item(run.id, brief=False)
        if run.current_item is None:
            break
    assert run.current_item is None  # linear: after the last test there is no "next"
    k.set_current(run.id, run.selected_items[-1])
    assert k.voice_command("next test") == "That was the last test. Say finish validation, or tap Finish on the iPad."
    done = k.voice_command("finish validation")
    assert done is not None and done.startswith("Validation finished.")
    report_md = Path(k.store.run_dir(run.id)) / "report.md"
    for _ in range(250):  # the spoken reply comes first; the report is written in a worker thread after it
        await asyncio.sleep(0.02)
        if k.run is None and report_md.is_file():
            break
    assert k.run is None and run.status == "finished"
    assert report_md.is_file()


async def test_input_check_counts_only_fresh_frames(
    kit: tuple[ValidationKit, FakeRadio], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stopped stream leaves its last frame in place: the input check must not read it as the driver's inputs."""
    k, _radio = kit
    run = k.start_run(["gt7_ps5"], None, False)
    live = k.rt.live
    status = {"status": "stale"}
    monkeypatch.setattr(live, "connection", lambda: dict(status))

    def frame(steering: float) -> SimpleNamespace:
        return SimpleNamespace(steering=steering, throttle=0.0, brake=0.0, gear=1)

    live.frame = frame(-0.9)
    k.input_check(run.id, "gt7_ps5", "left", None)
    await asyncio.sleep(0.35)
    k.input_check(run.id, "gt7_ps5", "stop", None)
    stale = run.evidence.input_phases[-1]
    assert stale.samples == 0 and stale.steer_mean is None  # telemetry not live: nothing read

    status["status"] = "live"
    k.input_check(run.id, "gt7_ps5", "right", None)
    live.frame = frame(0.95)
    await asyncio.sleep(0.35)
    k.input_check(run.id, "gt7_ps5", "stop", None)
    same = run.evidence.input_phases[-1]
    assert same.phase == "right" and same.samples == 1 and same.steer_max == pytest.approx(0.95)  # one frame, once
