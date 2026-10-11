"""Strategy calls on the radio (``strategy.radio`` + ``voice.scheduler``): level -> kind / priority / bypass / topic /
TTL, which coaching intensity says what, speak windows and topic replacement; the hub's audience filter."""

from __future__ import annotations

from typing import Any

import pytest

from pitwall.strategy.radio import strategy_message
from pitwall.voice.scheduler import ALLOWED_KINDS, RadioScheduler
from pitwall.voice.types import DrivingState, MessageKind, Priority

CALM = DrivingState(True, 250.0, 0.0, 0.0, 10, 500.0, 20.0)
BRAKING = DrivingState(True, 250.0, 0.8, 0.0, 10, 500.0, 0.0)


def call(level: str, topic: str = "gap", **kw: Any) -> dict[str, Any]:
    return {
        "id": f"st-{topic}-{level}",
        "topic": topic,
        "level": level,
        "priority": kw.pop("priority", "normal"),
        "text": kw.pop("text", f"A {level} call about {topic}."),
        "lap": 10,
        "ttl_s": kw.pop("ttl_s", 30.0),
        "bypass_quiet": kw.pop("bypass", False),
        "audience": "all",
        "data": {},
        "t_unix": 0.0,
        **kw,
    }


@pytest.mark.parametrize(
    ("level", "prio", "kind", "priority"),
    [
        ("alert", "high", MessageKind.ALERT, Priority.HIGH),
        ("normal", "normal", MessageKind.STRATEGY, Priority.NORMAL),
        ("detailed", "low", MessageKind.INFO, Priority.LOW),
    ],
)
def test_level_to_kind_priority_topic_ttl(level: str, prio: str, kind: MessageKind, priority: Priority) -> None:
    m = strategy_message(call(level, priority=prio, ttl_s=45.0), 100.0)
    assert m.kind is kind and m.priority is priority and m.needs_speak_window
    assert m.expires_mono == 145.0 and m.lap_number == 10 and m.id == f"strategy-st-gap-{level}"
    assert m.meta["topic"] == "strategy:gap" and m.meta["strategy_call"] == f"st-gap-{level}"
    assert strategy_message(call(level, bypass=True), 0.0).bypass_quiet


def test_strategy_kind_is_normal_and_detailed_not_quiet() -> None:
    assert MessageKind.STRATEGY in ALLOWED_KINDS["normal"] and MessageKind.STRATEGY in ALLOWED_KINDS["detailed"]
    assert MessageKind.STRATEGY not in ALLOWED_KINDS["quiet"]
    assert MessageKind.INFO not in ALLOWED_KINDS["normal"] and MessageKind.ALERT in ALLOWED_KINDS["quiet"]


@pytest.mark.parametrize(
    ("intensity", "said"),
    [("quiet", {"alert"}), ("normal", {"alert", "normal"}), ("detailed", {"alert", "normal", "detailed"})],
)
def test_intensity_filters_by_level(intensity: str, said: set[str]) -> None:
    s = RadioScheduler(intensity, min_gap_s=0.0)
    for lvl, topic in (("alert", "fuel"), ("normal", "gap"), ("detailed", "neighbour_stop")):
        s.enqueue(strategy_message(call(lvl, topic), 0.0))
    out = set()
    for k in range(5):
        m = s.next_message(CALM, 10.0 + 10 * k, speaking=False)
        if m is not None:
            out.add(m.meta.get("strategy_call", "").split("-")[-1])  # type: ignore[union-attr]
    assert out == said


def test_calls_wait_for_a_speak_window() -> None:
    s = RadioScheduler("normal")
    s.enqueue(strategy_message(call("alert", "sc_box", priority="high", bypass=True), 0.0))
    assert s.next_message(BRAKING, 1.0, speaking=False) is None
    m = s.next_message(CALM, 2.0, speaking=False)
    assert m is not None and m.meta["topic"] == "strategy:sc_box"


def test_newer_call_on_the_same_topic_replaces_the_unsaid_one() -> None:
    s = RadioScheduler("normal")
    s.enqueue(strategy_message(call("normal", "fuel", text="Fuel is tight: plus 0.2 laps to the finish."), 0.0))
    s.enqueue(strategy_message(call("alert", "fuel", text="Fuel critical: 0.3 laps short."), 1.0))
    (only,) = s.pending()
    assert only.text == "Fuel critical: 0.3 laps short."


def test_quiet_mode_lets_bypassing_alerts_through_only() -> None:
    s = RadioScheduler("normal", min_gap_s=0.0)
    s.set_quiet(indefinite=True)
    s.enqueue(strategy_message(call("alert", "weather"), 0.0))
    s.enqueue(strategy_message(call("alert", "sc_box", bypass=True, priority="high"), 0.0))
    m = s.next_message(CALM, 1.0, speaking=False)
    assert m is not None and m.meta["topic"] == "strategy:sc_box"
    assert s.next_message(CALM, 30.0, speaking=False) is None


class _Limits:
    simple_wording = True


def test_hub_drops_experienced_calls_for_simple_wording() -> None:
    from pitwall.voice.hub import RadioHub

    class FakeHub:
        coaching_limits: Any = None

        def __init__(self) -> None:
            self.scheduler = RadioScheduler("detailed")

    hub = FakeHub()
    enqueue = RadioHub._enqueue_strategy
    enqueue(hub, call("detailed", "neighbour_stop", audience="experienced"))  # type: ignore[arg-type]
    assert len(hub.scheduler.pending()) == 1
    hub.coaching_limits = _Limits()
    enqueue(hub, call("normal", "undercut_threat", audience="experienced"))  # type: ignore[arg-type]
    enqueue(hub, call("normal", "gap"))  # type: ignore[arg-type]
    assert [m.meta["topic"] for m in hub.scheduler.pending()] == ["strategy:neighbour_stop", "strategy:gap"]
