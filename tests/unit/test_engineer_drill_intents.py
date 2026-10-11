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


@pytest.mark.parametrize(
    ("question", "intent"),
    [
        # questions that mention a drill ask for its status: they never start or stop one (adversarial review)
        ("How did the drill on T1-4 (1) go?", "drill_status"),
        ("did I hit the drill at T3", "drill_status"),
        ("what was my best drill at turn 3", "drill_status"),
        ("should I do a drill at turn 4", "drill_status"),
        ("what happens at the end of the drill", "drill_status"),
        ("is the drill still running?", "drill_status"),
        # negations do nothing with a drill
        ("don't start a drill on T1-4 (1)", "corner"),
        ("do not start a drill on turn 3", "corner"),
        ("don't stop the drill", "general"),
        ("please don't stop the drill", "general"),
        ("never mind the drill", "general"),
        # another rule's question that mentions a drill
        ("compare my drill at turn 3 with Sam", "compare"),
        # imperatives with a lead-in still act
        ("No, stop the drill", "drill_stop"),
        ("please stop the drill", "drill_stop"),
        ("stop the drill, I'm not enjoying it", "drill_stop"),
        ("can you start a drill on turn 5", "drill_start"),
        ("let's do a drill at turn 2", "drill_start"),
        ("I want to do a drill at turn 4", "drill_start"),
    ],
)
def test_only_an_imperative_starts_or_stops_a_drill(question: str, intent: str) -> None:
    assert detect_intent(question).name == intent


@pytest.mark.parametrize(
    ("question", "intent"),
    [
        ("who am I compared with?", "reference"),
        ("what am I comparing against", "reference"),
        ("who am I racing against", "reference"),
        ("what's the reference", "reference"),
        ("what did I lose against the reference", "compare"),  # a time question stays a comparison
        ("what did I lose against the reference at turn 3", "compare"),
        ("what's my delta to the reference", "compare"),
        ("who am I racing against, the AI?", "general"),
    ],
)
def test_who_am_i_compared_with(question: str, intent: str) -> None:
    assert detect_intent(question).name == intent


def test_other_questions_are_unchanged() -> None:
    assert detect_intent("turn 3").name == "corner"
    assert detect_intent("stop talking for two laps").name == "control_quiet"
    assert detect_intent("what should I work on").name == "focus"
    assert detect_intent("radio check").name == "radio_check"


def test_drill_intents_are_fast() -> None:
    assert {"drill_start", "drill_status", "drill_stop", "reference"} <= FAST_INTENTS


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
