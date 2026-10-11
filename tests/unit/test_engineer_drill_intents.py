"""coachref: radio drill intents are detected before every other rule and answered without the LLM."""

from __future__ import annotations

from typing import Any

import pytest

from pitwall.ai.engineer import Intent, RaceEngineer, detect_intent
from pitwall.ai.facts import FactSheet
from pitwall.ai.providers import LLMProvider
from pitwall.voice.hub import FAST_INTENTS


@pytest.mark.parametrize(
    ("question", "intent", "corner"),
    [
        ("start a drill on turn 3", "drill_start", "T3"),
        ("Drill turn three", "drill_start", "T3"),
        ("give me a braking drill at turn 9 for three laps", "drill_start", "T9"),
        ("drill at Copse", "drill_start", None),
        ("set up a drill for T12", "drill_start", "T12"),
        ("how's my drill going", "drill_status", None),
        ("how’s the drill going?", "drill_status", None),
        ("how am I doing on the drill", "drill_status", None),
        ("drill status", "drill_status", None),
        ("stop the drill", "drill_stop", None),
        ("cancel my drill", "drill_stop", None),
        ("end this drill please", "drill_stop", None),
    ],
)
def test_drill_phrases(question: str, intent: str, corner: str | None) -> None:
    got = detect_intent(question)
    assert got.name == intent
    assert got.corner == corner


@pytest.mark.parametrize(
    "question",
    [
        "drill turn 3 so I can work on it",  # "work on" is the focus rule
        "start a drill on turn 3 and be quiet",  # "quiet" is the quiet rule
        "stop the drill, turn 3 is fine",  # a bare corner would be the corner rule
    ],
)
def test_drill_rules_take_precedence(question: str) -> None:
    assert detect_intent(question).name.startswith("drill_")


def test_other_questions_are_unchanged() -> None:
    assert detect_intent("turn 3").name == "corner"
    assert detect_intent("stop talking for two laps").name == "control_quiet"
    assert detect_intent("what should I work on").name == "focus"
    assert detect_intent("radio check").name == "radio_check"


def test_drill_intents_are_fast() -> None:
    assert {"drill_start", "drill_status", "drill_stop"} <= FAST_INTENTS


class _NoLLM(LLMProvider):
    name = "no-llm"

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, *a: Any, **k: Any) -> Any:  # pragma: no cover - must never run
        self.calls += 1
        raise AssertionError("the LLM must not be asked about drills")

    async def health(self) -> Any:  # pragma: no cover
        return {}


async def test_handler_answers_without_the_llm() -> None:
    llm = _NoLLM()
    eng = RaceEngineer(llm)
    seen: list[tuple[Intent, str]] = []

    def handler(intent: Intent, question: str) -> tuple[str, dict[str, Any]]:
        seen.append((intent, question))
        return "Copy. Turn 3 brake point drill, 5 laps.", {"action": intent.name, "drill_id": 4}

    eng.drill_handler = handler
    ans = await eng.answer("start a drill on turn 3", FactSheet())
    assert ans.text == "Copy. Turn 3 brake point drill, 5 laps." and ans.speech == ans.text
    assert ans.control == {"action": "drill_start", "drill_id": 4}
    assert ans.grounded is True and ans.fallback is False and ans.facts == [] and ans.model is None
    assert seen[0][0].corner == "T3" and llm.calls == 0


async def test_without_a_handler_drills_are_refused() -> None:
    ans = await RaceEngineer(None).answer("how's my drill going", FactSheet())
    assert ans.text == "Drills aren't available right now." and ans.intent == "drill_status"
    assert ans.control is not None and ans.control["action"] == "drill_status"


async def test_a_failing_handler_is_answered_plainly() -> None:
    eng = RaceEngineer(None)

    def broken(intent: Intent, question: str) -> tuple[str, dict[str, Any]]:
        raise RuntimeError("db gone")

    eng.drill_handler = broken
    ans = await eng.answer("stop the drill", FactSheet())
    assert ans.text == "I couldn't do that with the drill just now." and ans.grounded is True
