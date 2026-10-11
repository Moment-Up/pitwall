"""The ``flags`` fact (plan 4.4): the safety car / VSC and the yellow marshal zones now, from the live session, only for
a game that sends flags; and the ``safety_car`` / ``flags`` answers built from it (engineer and radio phrasing)."""

from __future__ import annotations

from typing import Any

import pytest

from pitwall.ai.engineer import RaceEngineer, detect_intent, deterministic_answer
from pitwall.ai.facts import FLAGS_PREFIX, FactSheet, build_fact_sheet
from pitwall.ai.grounding import check_grounding
from pitwall.ai.radio_phrasing import radio_answer
from tests.unit.test_ai import _game_analysis


def live(sc: str | None = "none", yellow: tuple[int, ...] = (), status: str = "live") -> dict[str, Any]:
    """The parts of ``LiveState.snapshot()`` the fact reads (``marshal_flags`` lists only non-green zones)."""
    return {
        "connection": {"status": status},
        "session": {"safety_car_status": sc, "total_laps": 71},
        "marshal_flags": [{"game_number": n, "flag": "yellow"} for n in yellow] + [{"game_number": 9, "flag": "blue"}],
        "frame": {},
    }


def flags(sheet: FactSheet) -> list[str]:
    return [f.text for f in sheet.facts if f.topic == "flags"]


@pytest.mark.parametrize(
    ("sc", "yellow", "text", "say"),
    [
        (
            "full",
            (7, 3),
            "Flags now: the safety car is out; yellow flag in marshal zones 3 and 7.",
            "Safety car deployed. Yellow flag in marshal zones 3 and 7.",
        ),
        (
            "virtual",
            (),
            "Flags now: the virtual safety car is out; no yellow flags reported.",
            "Virtual safety car deployed. No yellow flags reported.",
        ),
        (
            "formation_lap",
            (),
            "Flags now: formation lap behind the safety car; no yellow flags reported.",
            "Formation lap, behind the safety car. No yellow flags reported.",
        ),
        (
            "none",
            (12,),
            "Flags now: no safety car or virtual safety car; yellow flag in marshal zone 12.",
            "No safety car. Yellow flag in marshal zone 12.",
        ),
        (
            "none",
            (),
            "Flags now: no safety car or virtual safety car; no yellow flags reported.",
            "No safety car. No yellow flags reported.",
        ),
    ],
)
def test_the_flags_now(sc: str, yellow: tuple[int, ...], text: str, say: str) -> None:
    sheet = build_fact_sheet(_game_analysis("f1_25", "ps5"), live(sc, yellow))
    (fact,) = [f for f in sheet.facts if f.topic == "flags"]
    assert (fact.text, fact.plain) == (text, say)
    assert fact.text.startswith(FLAGS_PREFIX) and fact.data["yellow_zones"] == sorted(yellow)
    assert sheet.facts.index(fact) == 1  # right after the session fact: never cut by a long sheet's selection


@pytest.mark.parametrize(
    "snap",
    [
        None,  # a recorded session: "now" means nothing
        live(status="stale"),  # the last session packet is not "now"
        live(sc=None),  # no session packet yet: nothing is known
        live(sc="weird"),  # an unknown status is not reported as anything
    ],
)
def test_unknown_stays_unknown(snap: dict[str, Any] | None) -> None:
    assert flags(build_fact_sheet(_game_analysis("f1_25", "ps5"), snap)) == []


def test_a_game_that_never_sends_flags_has_no_flags_fact() -> None:
    sheet = build_fact_sheet(_game_analysis("gt7", "ps5"), live("full", (3,)))
    assert flags(sheet) == []
    ans = deterministic_answer(detect_intent("Is the safety car out?"), sheet.facts, sheet)
    assert "GT7 doesn't send" in ans, ans


async def test_safety_car_and_flag_questions_are_answered_from_it() -> None:
    sheet = build_fact_sheet(_game_analysis("f1_25", "ps5"), live("full", (3,)))
    for q, intent in (("Is the safety car out?", "safety_car"), ("Where's the VSC?", "safety_car")):
        ans = await RaceEngineer(None).answer(q, sheet, use_llm=False)
        assert ans.intent == intent and ans.text == "Safety car deployed. Yellow flag in marshal zone 3.", q
        assert check_grounding(ans.cited_text, sheet.facts).ok
        assert radio_answer(intent, sheet) == ans.text
    for q in ("Any yellow flags?", "Is there a yellow?"):
        ans = await RaceEngineer(None).answer(q, sheet, use_llm=False)
        assert ans.intent == "flags" and ans.text == "Safety car deployed. Yellow flag in marshal zone 3.", q
        assert check_grounding(ans.cited_text, sheet.facts).ok
        assert radio_answer("flags", sheet) == ans.text
    clear = build_fact_sheet(_game_analysis("f1_25", "ps5"), live())
    ans = await RaceEngineer(None).answer("Is the safety car out?", clear, use_llm=False)
    assert ans.text == "No safety car. No yellow flags reported."


def test_strategy_box_call_comes_before_the_flags_fact() -> None:
    sheet = FactSheet()
    sheet.add("flags", f"{FLAGS_PREFIX} the safety car is out; no yellow flags reported.", say="Safety car deployed.")
    sheet.add(
        "strategy",
        "Safety car deployed (since lap 12): pitting this lap is an option.",
        {"kind": "sc_box"},
        say="Safety car. Pitting this lap is an option.",
    )
    ans = deterministic_answer(detect_intent("Should I box under the safety car?"), sheet.facts, sheet)
    assert ans.startswith("Safety car. Pitting this lap is an option.")  # strategy intent: box or stay
    ans = deterministic_answer(detect_intent("Is the safety car out?"), sheet.facts, sheet)
    assert ans.startswith("Safety car. Pitting this lap is an option.")


def test_after_the_session_a_flags_question_still_gets_the_general_answer() -> None:
    """F1 sends flags, so without a live flags fact the answer is the general one, never "complete a few laps"."""
    sheet = build_fact_sheet(_game_analysis("f1_25", "ps5"))
    ans = deterministic_answer(detect_intent("Any yellow flags?"), sheet.facts, sheet)
    assert "complete a few clean laps" not in ans and ans
    assert radio_answer("flags", sheet) is None  # nothing to phrase: the engineer's answer is said
