"""Car health facts and instant answers (``carhealth.facts`` / ``carhealth.phrasing``, the engineer's new intents):
every sentence grounded, the raw surface-temperature fact replaced, beginners' plain words, the tyres wrapper,
attack / defend and "where will I come out?"."""

from __future__ import annotations

from typing import Any

import pytest

from pitwall.ai.engineer import RaceEngineer, detect_intent
from pitwall.ai.facts import build_fact_sheet
from pitwall.ai.grounding import check_grounding
from pitwall.ai.radio_phrasing import radio_answer
from pitwall.carhealth.engine import CarHealthEngine
from pitwall.core.live import frame_to_dict
from tests.unit.carhealth_helpers import drive, frame, info
from tests.unit.test_ai import _game_analysis

SID = "live-1"


def _cold_engine() -> CarHealthEngine:
    eng = CarHealthEngine(SID)
    eng.feed(info())
    t = drive(eng, 0.0, 100.0, inner=88.0, lap0=2, lap_s=200.0)
    t = drive(eng, t, t + 25.0, inner=88.0, pit=1, speed=70.0, lap0=2, lap_s=1000.0)
    drive(eng, t, t + 8.0, inner=47.0, lap0=2, lap_s=1000.0)
    eng.feed(frame(t + 9.0, lap=3, d=2.0, inner=47.0))
    drive(eng, t + 9.1, t + 12.0, inner=47.0, lap0=3, lap_s=1000.0)
    return eng


def _racecraft(**ahead: Any) -> dict[str, Any]:
    side = {
        "car_index": 13,
        "position": 6,
        "laps_compared": [3, 3],
        "verdict": "clear",
        "corner": {"name": "T2", "text": "Turn 3", "delta_s": -0.42},
        "second": {"name": "T3", "text": "Turn 4", "delta_s": -0.18},
        "margin_s": 0.24,
        "lap_delta_s": -0.9,
        "reason": None,
        **ahead,
    }
    behind = {
        "car_index": 7,
        "position": 8,
        "laps_compared": [3, 2],
        "verdict": "none",
        "corner": None,
        "second": None,
        "margin_s": 0.02,
        "lap_delta_s": -1.3,
        "reason": None,
    }
    return {"version": 1, "session_id": SID, "mode": "race", "reason": None, "ahead": side, "behind": behind}


def _sheet(eng: CarHealthEngine, *, racecraft: dict[str, Any] | None = None, skill: str | None = None) -> Any:
    sa = _game_analysis("f1_25", "ps5")
    if skill:
        sa.driver = {"id": 1, "name": "Sam", "skill_level": skill}
    f = eng.frame
    assert f is not None
    live = {
        "session_id": SID,
        "connection": {"status": "live"},
        "session": {"safety_car_status": "none", "total_laps": 20},
        "marshal_flags": [],
        "frame": frame_to_dict(f),
        "car_health": eng.view(),
        "racecraft": racecraft or eng.racecraft_view(),
    }
    return build_fact_sheet(sa, live)


def test_health_facts_replace_the_raw_surface_temperatures_and_are_grounded() -> None:
    eng = _cold_engine()
    sheet = _sheet(eng)
    kinds = {f.data.get("kind") for f in sheet.facts if f.data.get("src") == "car_health"}
    assert {"tyre_temps", "pressures", "brakes", "engine"} <= kinds
    assert not any(f.text.startswith("Current tyre surface temps") for f in sheet.facts)
    temps = next(f for f in sheet.facts if f.data.get("kind") == "tyre_temps")
    assert temps.plain == "Tyres are cold: inside about 47 degrees, your warm laps run about 88."
    assert "Tyre carcass temperatures (measured" in temps.text
    for f in sheet.facts:
        if f.data.get("src") == "car_health":
            assert check_grounding(f"{f.plain} [{f.id}]", [f]).ok, f.plain


async def test_how_are_my_brakes_and_hows_the_car() -> None:
    eng = _cold_engine()
    sheet = _sheet(eng)
    eng_ = RaceEngineer(None)
    brakes = await eng_.answer("How are my brakes?", sheet, use_llm=False, short=True)
    assert brakes.intent == "car_health" and brakes.grounded
    assert radio_answer("car_health", sheet, "How are my brakes?") == (
        "Brakes peaked about 500 degrees last lap. I need another lap to know your normal."
    )
    warm = CarHealthEngine(SID)
    warm.feed(info())
    drive(warm, 0.0, 200.0, lap_s=60.0)
    wsheet = _sheet(warm)
    assert radio_answer("car_health", wsheet, "How are my brakes?") == (
        "Brakes peaked about 500 degrees last lap, normal for this session."
    )
    assert radio_answer("car_health", wsheet, "engine temperature?") == "Engine 120 degrees, steady."
    car = radio_answer("car_health", sheet, "how's the car?")
    assert car is not None and car.startswith("Tyres are cold: inside about 47 degrees")
    # before the first full lap a brake question is answered about the brakes (a lap is needed), not the tyres
    first = CarHealthEngine(SID)
    first.feed(info())
    drive(first, 0.0, 20.0, lap_s=60.0)
    fsheet = _sheet(first)
    assert not any(f.data.get("kind") == "brakes" for f in fsheet.facts)
    assert radio_answer("car_health", fsheet, "How are my brakes?") == "I need a full lap of brake temperatures first."
    hows = radio_answer("car_health", fsheet, "how's the car?")
    assert hows is not None and "brake" not in hows.lower()


def test_tyres_wrapper_leads_with_the_temperature_when_asked_or_cold() -> None:
    eng = _cold_engine()
    sheet = _sheet(eng)
    assert radio_answer("tyres", sheet, "how are my tyre temps") == (
        "Tyres are cold: inside about 47 degrees, your warm laps run about 88."
    )
    general = radio_answer("tyres", sheet, "How are my tyres?")
    assert general is not None and general.endswith("your warm laps run about 88.")  # cold: always added


def test_beginners_hear_one_plain_idea() -> None:
    eng = _cold_engine()
    sheet = _sheet(eng, skill="beginner")
    assert radio_answer("tyres", sheet, "are my tyres cold?") == (
        "Your tyres are cold, so there's less grip. Take it gently until they warm up."
    )
    sheet = _sheet(eng, racecraft=_racecraft(), skill="beginner")
    assert radio_answer("attack", sheet, "where can I overtake him?") == "You catch the car ahead most at Turn 3."


@pytest.mark.parametrize(
    ("verdict", "expected"),
    [
        ("clear", "You're quickest on the car ahead at Turn 3, about 0.4 a lap. That's your best chance."),
        ("spread", "Nowhere stands out against the car ahead: your gains are spread around the lap."),
        ("none", "You're not clearly quicker than the car ahead anywhere right now."),
    ],
)
def test_attack_answers(verdict: str, expected: str) -> None:
    eng = _cold_engine()
    rc = _racecraft(verdict=verdict, **({"corner": None, "second": None} if verdict == "none" else {}))
    sheet = _sheet(eng, racecraft=rc)
    assert radio_answer("attack", sheet, "where am I faster than the car ahead?") == expected
    f = next(f for f in sheet.facts if f.data.get("kind") == "racecraft_ahead")
    assert check_grounding(f"{f.plain} [{f.id}]", [f]).ok and "P6" in f.text and "name" not in f.text


async def test_defend_and_the_unknown_cases() -> None:
    eng = _cold_engine()
    sheet = _sheet(eng, racecraft=_racecraft())
    ans = await RaceEngineer(None).answer("Where's the car behind quicker than me?", sheet, use_llm=False, short=True)
    assert ans.intent == "defend" and ans.text == "The car behind isn't quicker than you anywhere." and ans.grounded
    rc = _racecraft()
    rc["ahead"] = {**rc["ahead"], "verdict": "unknown", "corner": None, "reason": "leading: there's no car ahead"}
    sheet = _sheet(eng, racecraft=rc)
    assert radio_answer("attack", sheet, "where can I make a move?") == "You're leading: there's no car ahead."
    off = {"version": 1, "session_id": SID, "mode": "off", "reason": "x", "ahead": None, "behind": None}
    sheet = _sheet(eng, racecraft=off)
    assert radio_answer("defend", sheet, "how do I hold him off?") == (
        "Attack and defend need an F1 race with the other cars' positions."
    )


async def test_rejoin_answers_from_the_strategy_facts() -> None:
    from pitwall.ai.facts import FactSheet
    from pitwall.strategy.facts import add_strategy_facts

    view = {
        "mode": "race",
        "pit": {
            "rejoin": {
                "position": 7,
                "position_low": 6,
                "position_high": 8,
                "ahead_position": 6,
                "gap_ahead_s": 1.2,
                "game_position": 8,
                "loss_s": 25.1,
                "loss_n": 12,
                "loss_tier": "measured",
                "traffic": False,
                "unknown_cars": 0,
                "frozen": False,
            }
        },
    }
    fs = FactSheet()
    add_strategy_facts(fs, view)
    f = next(f for f in fs.facts if f.data.get("kind") == "rejoin")
    assert f.text == (
        "Boxing now would rejoin around P7 (P6-P8, estimate from a 25.1 s pit loss measured on 12 stop(s)); "
        "1.2 s behind P6; game says P8."
    )
    assert f.plain == "Box now and you'd come out around P7, between P6 and P8, about 1 second behind P6."
    assert check_grounding(f"{f.plain} [{f.id}]", [f]).ok
    assert radio_answer("rejoin", fs, "where will I come out if I pit now?") == f.plain
    ans = await RaceEngineer(None).answer("Where will I come out if I pit now?", fs, use_llm=False, short=True)
    assert ans.intent == "rejoin" and ans.text == f.plain
    fs2 = FactSheet()
    add_strategy_facts(fs2, {"mode": "race", "pit": {"rejoin": {"position": None, "game_position": 8}}})
    assert radio_answer("rejoin", fs2, "where would I rejoin?") == (
        "No stop measured this race yet, so I can't say. The game's own estimate is P8."
    )


def test_new_intents_route_and_keep_the_pinned_ones() -> None:
    assert detect_intent("how are my tyre temps").name == "tyres"
    assert detect_intent("How are my tyres?").name == "tyres"
    assert detect_intent("Is the car behind catching me?").name == "gaps"
    assert detect_intent("What should I do against the car behind?").name == "gaps"
    assert detect_intent("How is the car handling?").name == "balance"
    assert detect_intent("Is my braking OK in sector two?").name == "braking"
    assert detect_intent("Should I stay out?").name == "strategy"
    assert (
        detect_intent("should I defend into turn 4?").name,
        detect_intent("should I defend into turn 4?").corner,
    ) == (
        "defend",
        "T4",
    )
