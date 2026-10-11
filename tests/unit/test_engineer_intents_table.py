"""The engineer's one ordered intent table (v0.2.0 plan 4.1-4.8) against ``tests/fixtures/intents.json``: every
question routes to its intent and corner, every rule of the table is exercised, and every question has a grounded
deterministic answer (what the radio says while the car is moving, plan 4.3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pitwall import games
from pitwall.ai.engineer import _RULES, _TOPICS, RaceEngineer, detect_intent
from pitwall.ai.facts import build_fact_sheet
from pitwall.ai.grounding import check_grounding
from pitwall.voice.hub import FAST_INTENTS
from tests.unit.test_ai import _game_analysis

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "intents.json"
QUESTIONS: list[dict[str, Any]] = json.loads(FIXTURE.read_text(encoding="utf-8"))["questions"]
CONTROL = {"radio_check", "control_quiet", "control_resume"}


@pytest.mark.parametrize("row", QUESTIONS, ids=[r["question"] for r in QUESTIONS])
def test_route(row: dict[str, Any]) -> None:
    got = detect_intent(row["question"])
    assert (got.name, got.corner) == (row["intent"], row["corner"])


def test_the_fixture_is_well_formed() -> None:
    questions = [r["question"].casefold() for r in QUESTIONS]
    assert len(questions) == len(set(questions)) >= 90
    known = set(_TOPICS) | CONTROL
    assert {r["intent"] for r in QUESTIONS} <= known
    # coachref's drill rules (and their rows) join with F9: no question may start or stop a drill before then
    assert not any(r["intent"].startswith("drill") for r in QUESTIONS)


def test_every_rule_of_the_table_is_exercised() -> None:
    routed = {r["intent"] for r in QUESTIONS}
    assert {name for name, _rx in _RULES} <= routed


def test_fast_intents_are_intents() -> None:
    names = {name for name, _rx in _RULES}
    assert names.issuperset(FAST_INTENTS)
    assert names.issuperset(games.CAPABILITY_ONLY_INTENTS)


async def test_every_question_has_a_grounded_deterministic_answer() -> None:
    """While the car is moving the radio never asks the LLM: each question gets the engineer's deterministic answer
    (or a control acknowledgement), grounded by construction, from a real-shaped F1 race sheet with live flags."""
    snap = {
        "connection": {"status": "live"},
        "session": {"safety_car_status": "none", "total_laps": 71},
        "marshal_flags": [],
        "frame": {},
    }
    sheet = build_fact_sheet(_game_analysis("f1_25", "ps5"), snap)
    engineer = RaceEngineer(None)
    for row in QUESTIONS:
        ans = await engineer.answer(row["question"], sheet, use_llm=False)
        assert ans.intent == row["intent"], row
        assert ans.text.strip(), row
        if ans.intent not in CONTROL:
            assert ans.fallback and ans.grounded, row
            assert check_grounding(ans.cited_text, sheet.facts).ok, row
