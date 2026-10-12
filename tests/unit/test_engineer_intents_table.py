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
DRILL = {"drill_start", "drill_status", "drill_stop"}  # coachref: answered by RaceEngineer.drill_handler


@pytest.mark.parametrize("row", QUESTIONS, ids=[r["question"] for r in QUESTIONS])
def test_route(row: dict[str, Any]) -> None:
    got = detect_intent(row["question"])
    assert (got.name, got.corner) == (row["intent"], row["corner"])


def test_the_fixture_is_well_formed() -> None:
    questions = [r["question"].casefold() for r in QUESTIONS]
    assert len(questions) == len(set(questions)) >= 90
    known = set(_TOPICS) | CONTROL | DRILL
    assert {r["intent"] for r in QUESTIONS} <= known


_QUESTION_WORDS = ("how", "what", "when", "why", "where", "which", "who", "is", "are", "do i", "does", "did", "should")


def test_a_question_never_starts_or_stops_a_drill() -> None:
    """Plan 4.1/4.2: only a command starts or stops a drill; any question about one asks for its status, and a
    negation ("don't start a drill") does neither."""
    drill_rows = [r for r in QUESTIONS if "drill" in r["question"].casefold()]
    assert {r["intent"] for r in drill_rows} >= DRILL
    for r in drill_rows:
        q = r["question"].casefold()
        if q.startswith(_QUESTION_WORDS):
            assert r["intent"] == "drill_status", r
        if "don't" in q or "do not" in q:
            assert r["intent"] not in DRILL, r


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
        if ans.intent not in CONTROL | DRILL:
            assert ans.fallback and ans.grounded, row
            assert check_grounding(ans.cited_text, sheet.facts).ok, row


async def test_every_radio_answer_at_speed_is_short() -> None:
    """Plan 4.3 with the final review's H1: while the car is moving every question gets the deterministic answer, so
    that answer is one or two facts in their spoken form (``short=True``), never a fact list read out through the
    next braking zones (it was 27 s for "How am I doing?" and 42 s for a setup question). Grounded as before."""
    from pitwall.ai.radio_phrasing import radio_answer
    from pitwall.voice.scheduler import estimate_speech_s

    snap = {
        "connection": {"status": "live"},
        "session": {"safety_car_status": "none", "total_laps": 71},
        "marshal_flags": [],
        "frame": {},
    }
    sheet = build_fact_sheet(_game_analysis("f1_25", "ps5"), snap)
    engineer = RaceEngineer(None)
    for row in QUESTIONS:
        ans = await engineer.answer(row["question"], sheet, use_llm=False, short=True)
        said = radio_answer(ans.intent, sheet, row["question"]) or ans.text
        assert estimate_speech_s(said) <= 12.0, (row["question"], said)  # the estimate errs long (2.6 words/s)
        if ans.intent not in CONTROL | DRILL:
            assert check_grounding(ans.cited_text, sheet.facts).ok, row
    summary = await engineer.answer("How am I doing?", sheet, use_llm=False, short=True)
    assert summary.text.count(". ") <= 1 and "Best clean lap" in summary.text  # the best lap and the top point
    setup = await engineer.answer("Should I change my front wing?", sheet, use_llm=False, short=True)
    assert setup.text.startswith("Rule out technique first.")


async def test_the_full_summary_says_a_personal_best_set_this_session_once() -> None:
    """UX review: the summary said the same 1:24.528 twice (the session's best clean lap and the personal best, the
    same lap). Review › Ask's full answer keeps one of them."""
    sa = _game_analysis("f1_25", "ps5")
    best = min((lap for lap in sa.laps if lap["clean"] and lap.get("lap_time_ms")), key=lambda x: x["lap_time_ms"])
    sa.driver = {"id": 1, "name": "Sam", "skill_level": "advanced"}
    sa.personal_best = {**best, "session_id": sa.session["id"]}
    sheet = build_fact_sheet(sa, None)
    ans = await RaceEngineer(None).answer("Give me a summary of this session.", sheet, use_llm=False)
    assert "Best clean lap this session" in ans.text and "personal best" not in ans.text
