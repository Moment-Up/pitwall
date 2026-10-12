"""Car health calls (``carhealth.calls`` + ``carhealth.radio``): every topic's trigger and cooldown, the per-lap caps,
F1 races leaving wear and fuel to race strategy, the blocked moments, the lap-1 rule, the wording lint, and the
radio side (kinds, topics, quiet mode, simple wording, the hub)."""

from __future__ import annotations

import re
from typing import Any

import pytest

from pitwall.ai.facts import FactSheet
from pitwall.carhealth import thresholds as T
from pitwall.carhealth.calls import CallContext, HealthCallPlanner, sample_calls
from pitwall.carhealth.facts import add_car_health_facts
from pitwall.carhealth.radio import health_message
from pitwall.carhealth.settings import HealthSettings
from pitwall.carhealth.slip import SlipEvent
from pitwall.carhealth.tyres import TyreEvent
from pitwall.voice.scheduler import ALLOWED_KINDS, RadioScheduler
from pitwall.voice.types import DrivingState, MessageKind, Priority

# The coaching rule: nothing here ever tells the driver to brake later (or deeper, or to dive in).
BRAKE_LATER = re.compile(r"brake\w* (?:a (?:bit|little) )?later|later on the brakes|brake deeper|\bdive\b", re.I)
CALM = DrivingState(True, 250.0, 0.0, 0.0, 10, 500.0, 20.0)
COLD = TyreEvent("tyres_cold", "pit_exit", 3, {"index_c": 30.0, "baseline_c": 89.0})
WARM = TyreEvent("tyres_warm", "pit_exit", 4, {"index_c": 82.0, "baseline_c": 89.0})
LOCK = SlipEvent("lockup", 100.0, 0.3, ("FL",), 1, ("T1", "Turn 1"))
SPIN = SlipEvent("wheelspin", 900.0, 0.4, ("RR",), 1, ("T9", "Turn 9"))


def ctx(lap: int = 5, **kw: Any) -> CallContext:
    return CallContext(lap=lap, **kw)


def test_every_template_is_short_plain_and_never_says_brake_later() -> None:
    calls = sample_calls()
    assert {c.topic for c in calls} == {
        "tyres_cold",
        "tyres_warm",
        "wear_high",
        "fuel_low",
        "fuel_critical",
        "slip_lockups",
        "slip_wheelspin",
    }
    for c in calls:
        assert len(c.text) <= T.MAX_TEXT and c.text_simple and len(c.text_simple) <= T.MAX_TEXT, c
        for text in (c.text, c.text_simple):
            assert not BRAKE_LATER.search(text), text
            assert "  " not in text and text.endswith("."), text
        assert c.audience == "all" and c.id.startswith(f"hc-{c.topic}-")
        nums = {n for n in re.findall(r"\d+(?:\.\d+)?", c.text)}
        flat = " ".join(str(v) for v in c.data.values())
        assert all(n in flat or n == "1" for n in nums), (c.text, c.data)  # numbers only from data


def test_fact_says_pass_the_lint_too() -> None:
    fs = FactSheet()
    live = {
        "session_id": "s",
        "car_health": {
            "session_id": "s",
            "tyres": {
                "available": True,
                "model": "carcass",
                "state": "cold",
                "since": {"lap": 3, "reason": "pit_exit"},
                "index_c": 47.0,
                "baseline_c": 87.0,
                "wheels": [{"window_c": 47.0, "band": "cold", "baseline_c": 87.0, "pressure_psi": 19.5}] * 4,
            },
            "brakes": {
                "available": True,
                "last_lap_max_c": [982, 979, 961, 960],
                "baseline_max_c": [975] * 4,
                "word": "normal",
            },
            "engine": {"available": True, "now_c": 124, "lap_median_c": 124.0, "baseline_c": 123.0, "word": "steady"},
            "slip": {
                "available": True,
                "lockups_applicable": True,
                "tc": 1,
                "last_lap": {
                    "lap": 3,
                    "lockups": 3,
                    "wheelspin": 4,
                    "wheelspin_s": 1.6,
                    "corners": [{"corner": "T1", "text": "Turn 1", "lockups": 2, "wheelspin": 0}],
                },
                "session": {"laps": 5, "lockups": 11, "wheelspin": 9},
            },
        },
    }
    add_car_health_facts(fs, live)
    assert len(fs.facts) >= 5
    for f in fs.facts:
        assert not BRAKE_LATER.search(f.plain), f.plain
        simple = f.data.get("simple")
        assert simple is None or not BRAKE_LATER.search(simple)


def test_tyres_cold_on_lap_one_but_nothing_else_there() -> None:
    p = HealthCallPlanner(clock=lambda: 0.0)
    assert p.tyres(ctx(1), COLD) is not None  # cold tyres after a lap-1 stop: the one lap-1 call
    assert p.tyres(ctx(1), WARM) is None
    assert p.wear(ctx(1), (75.0, 1.0, 1.0, 1.0), 1) is None


@pytest.mark.parametrize(
    "c", [ctx(blocked="red flag"), ctx(blocked="formation lap"), ctx(in_pit=True), ctx(final_lap=True)]
)
def test_nothing_when_blocked_in_the_pits_or_on_the_final_lap(c: CallContext) -> None:
    p = HealthCallPlanner(clock=lambda: 0.0)
    assert p.tyres(c, COLD) is None
    assert p.fuel(c, "critical", 1.0, 0.05) is None
    assert p.slip(c, {"lap": 4, "lockups": 5, "wheelspin_spoken": 5}, [LOCK]) == []


def test_one_normal_and_one_detailed_call_per_lap() -> None:
    p = HealthCallPlanner(clock=lambda: 0.0)
    assert p.tyres(ctx(5), COLD) is not None  # normal
    assert p.wear(ctx(5), (75.0, 1.0, 1.0, 1.0), 1) is None  # a second normal on the same lap
    assert p.tyres(ctx(5), WARM) is not None  # detailed
    assert p.slip(ctx(5), {"lap": 4, "lockups": 4, "wheelspin_spoken": 0}, [LOCK] * 4) == []  # a second detailed
    assert p.wear(ctx(6), (75.0, 1.0, 1.0, 1.0), 1) is not None  # the next lap


def test_wear_once_per_stint_and_never_in_f1_races() -> None:
    p = HealthCallPlanner(clock=lambda: 0.0)
    assert p.wear(ctx(5), (60.0, 69.9, 1.0, 1.0), 1) is None
    c = p.wear(ctx(6), (60.0, 72.4, 1.0, 1.0), 1)
    assert c is not None and c.text == "Front right is at 72 percent wear." and c.level == "normal"
    assert c.text_simple == "Your front right tyre is getting worn: 72 percent."
    assert p.wear(ctx(9), (60.0, 80.0, 1.0, 1.0), 1) is None  # once per stint
    assert p.wear(ctx(12), (75.0, 1.0, 1.0, 1.0), 2) is not None  # a new stint
    assert HealthCallPlanner().wear(ctx(6, f1_race=True), (60.0, 72.0, 1.0, 1.0), 1) is None


def test_fuel_low_repeats_after_three_laps_or_half_a_lap_worse() -> None:
    p = HealthCallPlanner(clock=lambda: 0.0)
    c = p.fuel(ctx(10), "low", 2.6, 0.041)
    assert c is not None and c.text == "Fuel for about 3 more laps, at 4.1 percent a lap." and c.level == "normal"
    assert c.text_simple == "You've got fuel for about 3 more laps."
    assert p.fuel(ctx(11), "low", 2.3, 0.041) is None
    assert p.fuel(ctx(12), "low", 2.0, 0.041) is not None  # 0.6 lap worse
    assert p.fuel(ctx(13), "low", 1.8, 0.041) is None
    assert p.fuel(ctx(15), "low", 1.7, 0.041) is not None  # three laps on
    assert HealthCallPlanner().fuel(ctx(10, f1_race=True), "low", 2.6, 0.04) is None


def test_fuel_critical_is_an_alert_that_bypasses_quiet_mode() -> None:
    p = HealthCallPlanner(clock=lambda: 0.0)
    c = p.fuel(ctx(10), "critical", 1.1, 0.04)
    assert c is not None and c.level == "alert" and c.priority == "high" and c.bypass_quiet
    assert c.text == "Fuel for about one more lap." and c.text_simple == "Almost out of fuel: about one lap left."
    assert p.fuel(ctx(11), "critical", 0.9, 0.04) is None
    assert p.fuel(ctx(12), "critical", 0.6, 0.04) is not None  # two laps on


def test_slip_notes_detailed_by_default_and_the_setting() -> None:
    lap = {"lap": 4, "lockups": 3, "wheelspin": 0, "wheelspin_spoken": 0}
    p = HealthCallPlanner(clock=lambda: 0.0)
    (c,) = p.slip(ctx(5), lap, [LOCK, LOCK, SPIN.__class__("lockup", 300.0, 0.2, ("FR",), 1, ("T3", "Turn 3"))])
    assert c.level == "detailed" and c.text == "Three lock-ups that lap, two into Turn 1."
    assert c.text_simple == "The wheels locked three times, mostly into Turn 1. Squeeze the brake more gently there."
    assert p.slip(ctx(6), lap, [LOCK] * 3) == []  # once per three laps
    assert len(p.slip(ctx(8), lap, [LOCK] * 3)) == 1
    normal = HealthCallPlanner(clock=lambda: 0.0, settings=HealthSettings(slip_calls="normal"))
    assert normal.slip(ctx(5), lap, [LOCK] * 3)[0].level == "normal"
    off = HealthCallPlanner(clock=lambda: 0.0, settings=HealthSettings(slip_calls="off"))
    assert off.slip(ctx(5), lap, [LOCK] * 3) == []


def test_slip_never_on_lap_one_a_pit_lap_or_a_flashback_lap() -> None:
    p = HealthCallPlanner(clock=lambda: 0.0)
    assert p.slip(ctx(2), {"lap": 1, "lockups": 9}, [LOCK] * 9) == []
    assert p.slip(ctx(5), {"lap": 4, "lockups": 9, "pit": True}, [LOCK] * 9) == []
    assert p.slip(ctx(5), {"lap": 4, "lockups": 9, "flashback": True}, [LOCK] * 9) == []


def test_wheelspin_only_when_spoken_eligible() -> None:
    p = HealthCallPlanner(clock=lambda: 0.0)
    full_tc = SlipEvent("wheelspin", 900.0, 0.4, ("RR",), 2, ("T9", "Turn 9"))
    assert p.slip(ctx(5), {"lap": 4, "lockups": 0, "wheelspin": 6, "wheelspin_spoken": 0}, [full_tc] * 6) == []
    (c,) = p.slip(ctx(6), {"lap": 5, "lockups": 0, "wheelspin": 4, "wheelspin_spoken": 4}, [SPIN] * 4)
    assert c.text == "Wheelspin four times that lap, most out of Turn 9."


def test_settings_switch_topics_off() -> None:
    p = HealthCallPlanner(
        clock=lambda: 0.0, settings=HealthSettings(tyre_calls=False, wear_calls=False, fuel_calls=False)
    )
    assert p.tyres(ctx(5), COLD) is None and p.wear(ctx(5), (90.0,) * 4, 1) is None
    assert p.fuel(ctx(5), "critical", 0.5, 0.04) is None


# ---------------------------------------------------------------------------------------------------- radio
@pytest.mark.parametrize(
    ("level", "kind"), [("alert", MessageKind.ALERT), ("normal", MessageKind.STRATEGY), ("detailed", MessageKind.INFO)]
)
def test_level_to_existing_kinds_and_the_health_topic(level: str, kind: MessageKind) -> None:
    call = {"id": "hc-x-1", "topic": "x", "level": level, "priority": "high", "text": "T.", "ttl_s": 40.0, "lap": 3}
    m = health_message(call, 100.0)
    assert m.kind is kind and m.priority is Priority.HIGH and m.needs_speak_window and m.expires_mono == 140.0
    assert m.meta["topic"] == "health:x" and m.meta["source"] == "car_health" and m.meta["health_call"] == "hc-x-1"


def test_quiet_keeps_only_the_critical_fuel_alert() -> None:
    sched = RadioScheduler("quiet", min_gap_s=0.0)
    p = HealthCallPlanner(clock=lambda: 0.0)
    calls = [p.tyres(ctx(5), COLD), p.fuel(ctx(5), "critical", 1.0, 0.05)]
    for c in calls:
        assert c is not None
        sched.enqueue(health_message(c.to_dict(), 0.0))
    said = []
    for k in range(4):
        m = sched.next_message(CALM, 1.0 + 10 * k, speaking=False)
        if m is not None:
            said.append(m.meta["topic"])
    assert said == ["health:fuel_critical"]
    assert MessageKind.INFO not in ALLOWED_KINDS["normal"]  # detailed slip notes: detailed radio only


def test_the_hub_queues_health_calls_in_plain_words_for_a_beginner() -> None:
    from pitwall.voice.hub import RadioHub

    class FakeHub:
        coaching_limits: Any = None

        def __init__(self) -> None:
            self.scheduler = RadioScheduler("detailed")

    class Limits:
        simple_wording = True

    p = HealthCallPlanner(clock=lambda: 0.0)
    c = p.tyres(ctx(5), COLD)
    assert c is not None
    hub = FakeHub()
    RadioHub._enqueue_health(hub, c.to_dict())  # type: ignore[arg-type]
    hub.coaching_limits = Limits()
    RadioHub._enqueue_health(hub, {**c.to_dict(), "id": "hc-2"})  # type: ignore[arg-type]
    texts = [m.text for m in hub.scheduler.pending()]
    assert c.text_simple in texts and len(texts) == 1  # the same topic: the newer replaces the unsaid older one


async def test_a_health_call_notification_reaches_the_scheduler_and_the_answers_are_instant() -> None:
    """``health_call`` on the live notifications -> the hub -> the scheduler (kind, topic, bypass); the four new
    intents are fast: answered at once, never by the LLM."""
    from pitwall.core.live import LiveState
    from pitwall.voice.hub import FAST_INTENTS, RadioHub
    from tests.unit.test_voice_hub import FakeScheduler, FakeStt, FakeTts, RecordingEngineer, settle, sheet

    assert {"car_health", "rejoin", "attack", "defend"} <= FAST_INTENTS
    live = LiveState()
    sched = FakeScheduler()
    eng = RecordingEngineer()
    hub = RadioHub(live, eng, FakeStt(), FakeTts(), sched, fact_sheet=sheet, to_speech=lambda s: s)  # type: ignore[arg-type]
    hub.start()
    try:
        p = HealthCallPlanner(clock=lambda: 0.0)
        c = p.fuel(ctx(10), "critical", 1.0, 0.05)
        assert c is not None
        live.notify("health_call", {**c.to_dict(), "session_id": "s"})
        await settle(5)
        (m,) = sched.queue
        assert m.kind is MessageKind.ALERT and m.bypass_quiet and m.meta["topic"] == "health:fuel_critical"
        hub.ask_text("how are my brakes?")
        await settle(40)
        assert eng.use_llm[-1] == ("how are my brakes?", False)
    finally:
        await hub.stop()
