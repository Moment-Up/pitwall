"""ValidationKit: radio prompts (spec 6.5), item navigation and voice commands on a fake runtime and radio."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pitwall.core.live import LiveState
from pitwall.validate import evidence as E
from pitwall.validate.catalog import BY_ID
from pitwall.validate.kit import PROMPT_GAP_S, PROMPT_TTL_S, KitError, ValidationKit
from pitwall.validate.model import AutoState
from pitwall.voice.types import MessageKind, Priority, RadioMessage


class _Drivers:
    active_id = 1
    active = SimpleNamespace(id=1, name="Sam")

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
    assert brief.text == BY_ID["ipad_home_screen"].radio_brief and brief.kind is MessageKind.VALIDATION
    assert brief.priority is Priority.LOW and brief.needs_speak_window and not brief.bypass_quiet
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


async def test_a_prompt_never_replaces_the_reply_to_a_command(kit: tuple[ValidationKit, FakeRadio]) -> None:
    """The reply to the driver's own command and the run's prompts are on different topics: a prompt queued before
    the reply is said must not replace it (topic replacement, ``RadioScheduler.enqueue``)."""
    from pitwall.voice.scheduler import RadioScheduler

    k, radio = kit
    k.start_run(["ipad_home_screen"], None, True)
    (brief,) = radio.queued
    k._announce("Report saved.")
    reply = radio.queued[-1]
    assert reply.meta == {"topic": "validation:reply"} and reply.id != brief.id
    sched = RadioScheduler("normal")
    sched.enqueue(reply)
    sched.enqueue(brief)
    assert {m.id for m in sched.pending()} == {reply.id, brief.id}


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
    k, radio = kit
    # no run: only "start validation" is a command; a child's "passed!" after an overtake reaches the engineer
    for said in ("next test", "passed", "failed", "it worked", "repeat the instructions", "stop validation"):
        assert k.voice_command(said) is None, said
    assert k.voice_command("where should I brake in turn 3") is None
    reply = k.voice_command("start validation")
    assert reply is not None and reply.startswith("Validation started. First test: screen test.")
    run = k.run
    assert (
        run is not None
        and k.voice_command("start validation") == "Validation is already running. Current test: screen test."
    )
    assert k.voice_command("worked") == "Screen test: noted as worked."
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
    status = k.voice_command("repeat the instructions")  # the test's brief, not what is missing
    n = len(run.selected_items)
    assert (
        status == f"Test 2 of {n}: glance test. Three laps on Drive, Coach. Glance at the iPad as you would in a race."
    )
    didnt = "Glance test: noted as didn't work for Sam. Add a note on the iPad when you stop."
    assert k.voice_command("didn't work") == didnt  # each driver answers the glance test: named
    for _ in range(len(run.selected_items)):
        k.next_item(run.id, brief=False)
        if run.current_item is None:
            break
    assert run.current_item is None  # linear: after the last test there is no "next"
    k.set_current(run.id, run.selected_items[-1])
    assert k.voice_command("next test") == "That was the last test. Say finish validation, or tap Finish on the iPad."
    back = k.voice_command("next test")  # an earlier test is still to do: said as going back, not as "next"
    assert back == "Back to the one message test. Five laps; check the coach card matches what I say."
    assert run.current_item == "ipad_one_message"
    radio.queued.clear()
    assert k.voice_command("finish validation") == "Finishing validation."  # the counts come once saved
    report_md = Path(k.store.run_dir(run.id)) / "report.md"
    for _ in range(250):  # the report is written in a worker thread after the reply
        await asyncio.sleep(0.02)
        if k.run is None and report_md.is_file() and radio.queued:
            break
    assert k.run is None and run.status == "finished"
    assert report_md.is_file()
    counts = {r: sum(1 for it in run.items if it.result == r) for r in ("pass", "fail", "needs_review")}
    (said,) = [m.text for m in radio.queued]
    assert said == (
        f"Validation finished. {counts['pass']} passed, {counts['fail']} failed, {counts['needs_review']} to check. "
        "Report saved."
    )
    assert k.voice_command("worked") is None  # no run any more: the engineer answers


async def test_verdict_prompt_only_for_the_current_test(
    kit: tuple[ValidationKit, FakeRadio], monkeypatch: pytest.MonkeyPatch
) -> None:
    """'worked' on the radio marks the current test, so only the current test may ask for it: a prompt about another
    test followed by "didn't work" would mark the wrong one."""
    k, _radio = kit
    run = k.start_run(["radio_kokoro", "cues_timing"], None, True)
    assert run.current_item == "radio_kokoro"
    k._pending_prompt = None
    real = E.compute_auto
    passing: set[str] = set()

    def fake(item_id: str, vs: Any, ctx: Any) -> AutoState:
        return AutoState("pass", ["enough"], [], {}, "live", 0.0) if item_id in passing else real(item_id, vs, ctx)

    monkeypatch.setattr(E, "compute_auto", fake)
    passing.add("cues_timing")  # enough data for a test that is not current
    k.recompute()
    assert k._pending_prompt is None and run.prompted == []
    passing.add("radio_kokoro")  # the current test
    k.recompute()
    assert k._pending_prompt is not None and k._pending_prompt[0].startswith("Natural voice: enough data.")
    assert run.prompted == ["radio_kokoro"]


async def test_a_failed_finish_leaves_the_run_active(
    kit: tuple[ValidationKit, FakeRadio], monkeypatch: pytest.MonkeyPatch
) -> None:
    k, _radio = kit
    run = k.start_run(["ipad_home_screen"], None, False)

    def broken(*_a: Any, **_k: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(k.store, "save_report", broken)
    with pytest.raises(OSError):
        await k.finish(run.id, "notes")
    assert k.run is run and run.status == "active" and run.ended_unix is None and k.collector is not None
    assert run.timeline[-1].text == "Saving the report failed: the run is still active"
    monkeypatch.undo()
    done = await k.finish(run.id, None)  # the retry works (was a 409 "this run is not active")
    assert done.status == "finished" and k.run is None
    assert (Path(k.store.run_dir(run.id)) / "report.md").is_file()


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


async def test_collector_keeps_only_what_each_test_judges(kit: tuple[ValidationKit, FakeRadio]) -> None:
    """Speak windows: lap summaries and coaching only. Calls without a position are dropped, never stored as zeros.
    Question ids carry the start-up tag. A lap during which the call mode changed is "mixed" (never a calls-off
    baseline lap)."""
    k, _radio = kit
    run = k.start_run(["radio_speak_windows", "cues_timing", "radio_ptt"], None, False)
    c = k.collector
    assert c is not None
    base = {"needs_speak_window": True, "priority": 50, "state": {"on_track": True}, "meta": {}}
    for kind in ("control", "alert", "lap_summary", "coaching", "info"):
        c._on_radio("proactive", {**base, "msg_id": f"m-{kind}", "kind": kind, "text": kind})
    assert [p.kind for p in run.evidence.proactive] == ["lap_summary", "coaching"]

    cue = {"seq": 1, "lap": 2, "target_m": 1000.0, "aim_m": 995.0, "d_m": 900.0, "speed_kph": 250.0, "ttg_s": 1.4}
    c._on_radio("cue", {**cue, "status": "sent", "ref_lap_id": 5})
    c._on_radio("cue", {**cue, "seq": 2, "target_m": None, "status": "sent", "ref_lap_id": 5})
    c._on_radio("cue", {**cue, "seq": 3, "lap": None, "status": "sent", "ref_lap_id": 5})
    assert [x.seq for x in run.evidence.cues] == [1] and run.evidence.cues[0].target_m == 1000.0

    c._on_radio("transcript", {"text": "how are my tyres", "ptt_source": "screen"})
    c._on_radio("answer", {"msg_id": "m7", "question": "how are my tyres", "text": "Fine."})
    (q,) = run.evidence.ptt
    assert q.id == f"{k.boot_tag}-m7" and q.answer_source == "deterministic"
    k.mark_ptt(run.id, q.id, True)
    assert q.heard_right is True

    live = k.rt.live
    live.cues.set_mode("off")
    c._sample_live(0.0)
    lap = {"lap_id": 1, "lap_number": 1, "lap_time_ms": 90000, "clean": True, "flags": []}
    snap = {
        "lap": lap,
        "session_id": "s1",
        "source": None,
        "synthetic": False,
        "picked": [],
        "n_obs": 0,
        "game": "f1_25",
        "track_id": "t",
        "track_name": "T",
    }
    c._on_lap({**snap, "cue_mode": "off"})
    live.cues.set_mode("all")
    c._sample_live(0.0)
    c._on_lap({**snap, "lap": {**lap, "lap_id": 2, "lap_number": 2}, "cue_mode": "all"})
    c._on_lap({**snap, "lap": {**lap, "lap_id": 3, "lap_number": 3}, "cue_mode": "all"})
    assert [x.cue_mode for x in run.evidence.laps] == ["off", "mixed", "all"]


async def test_input_check_keeps_no_raw_range_without_samples(kit: tuple[ValidationKit, FakeRadio]) -> None:
    """The session's raw steering range is a whole-session figure: with no input read it is not this check's."""
    k, _radio = kit
    run = k.start_run(["ac_ps5"], None, False)
    k.rt.live.session = SimpleNamespace(extra={"steer_raw_range": [-4.29, 39.68]}, game=SimpleNamespace(value="ac"))
    k.input_check(run.id, "ac_ps5", "left", 900.0)
    k.input_check(run.id, "ac_ps5", "stop", None)
    (rec,) = run.evidence.input_phases
    assert rec.samples == 0 and rec.steer_raw_range is None
