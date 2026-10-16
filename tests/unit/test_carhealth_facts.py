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
        ("clear", "You're quickest on the car ahead at Turn 3, about four tenths a lap. That's your best chance."),
        ("spread", "You're nine tenths a lap quicker than the car ahead, but no one corner stands out."),
        ("none", "You're nine tenths a lap quicker than the car ahead, but not clearly quicker in any one corner."),
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
    assert ans.intent == "defend" and ans.grounded
    assert ans.text == "You're 1.3 seconds a lap quicker than the car behind; it isn't clearly quicker anywhere."
    rc = _racecraft()
    rc["ahead"] = {**rc["ahead"], "verdict": "unknown", "corner": None, "reason": "leading: there's no car ahead"}
    sheet = _sheet(eng, racecraft=rc)
    assert radio_answer("attack", sheet, "where can I make a move?") == "You're leading: there's no car ahead."
    for reason, said in (
        ("the session ended", "The race is over."),
        ("attack and defend work in races only", "Attack and defend work in races only."),
        ("x", "Attack and defend aren't available right now."),
    ):
        off = {"version": 1, "session_id": SID, "mode": "off", "reason": reason, "ahead": None, "behind": None}
        assert radio_answer("defend", _sheet(eng, racecraft=off), "how do I hold him off?") == said


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
        "I haven't timed a stop this race yet. The game says you'd come out about P8."
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


# ------------------------------------------------------------------------------------- the review fixes (health lane)
def _side_sheet(side: str, **s: Any) -> Any:
    from pitwall.ai.facts import FactSheet
    from pitwall.carhealth.facts import add_car_health_facts

    base = {"car_index": 3, "position": 4, "laps_compared": [3, 3], "corner": None, "second": None, "reason": None}
    rc = {"version": 1, "session_id": "s", "mode": "race", "reason": None, "ahead": None, "behind": None}
    rc[side] = {**base, **s}
    fs = FactSheet()
    add_car_health_facts(fs, {"session_id": "s", "racecraft": rc})
    return fs


@pytest.mark.parametrize(
    ("side", "s", "say"),
    [
        # every corner +0.08: no corner stands out, but the car behind is half a second a lap quicker
        (
            "behind",
            {"verdict": "none", "lap_delta_s": 0.48},
            "The car behind is five tenths a lap quicker, but it isn't clearly quicker in any one corner.",
        ),
        # the car ahead 3 s a lap quicker
        (
            "ahead",
            {"verdict": "none", "lap_delta_s": 3.0},
            "The car ahead is 3 seconds a lap quicker: you're not clearly quicker anywhere.",
        ),
        (
            "ahead",
            {"verdict": "spread", "lap_delta_s": 0.79, "corner": {"name": "T1", "text": "Turn 1", "delta_s": -0.12}},
            "No one corner stands out, and the car ahead is eight tenths a lap quicker overall.",
        ),
        (
            "ahead",
            {"verdict": "clear", "lap_delta_s": 0.6, "corner": {"name": "T1", "text": "Turn 1", "delta_s": -0.3}},
            "You're quickest on the car ahead at Turn 1, three tenths a lap, but it's six tenths a lap quicker overall.",
        ),
        (
            "ahead",
            {"verdict": "none", "lap_delta_s": 0.05},
            "You're level on pace with the car ahead; no one corner stands out.",
        ),
    ],
)
def test_racecraft_words_never_overstate(side: str, s: dict[str, Any], say: str) -> None:
    fs = _side_sheet(side, **s)
    (f,) = [f for f in fs.facts if f.data.get("kind") == f"racecraft_{side}"]
    assert f.plain == say
    assert "everywhere" not in f.plain and "all around the lap" not in str(f.data["simple"])
    assert check_grounding(f"{f.plain} [{f.id}]", [f]).ok


@pytest.mark.parametrize(
    ("close", "pace", "look"),
    [(True, 0.2, True), (True, -0.4, True), (False, 0.2, False), (None, 0.2, False), (True, -3.0, False)],
)
def test_expect_a_look_only_when_close_and_not_much_slower(close: bool | None, pace: float, look: bool) -> None:
    corner = {"name": "T4", "text": "Turn 4", "delta_s": 0.12}
    fs = _side_sheet("behind", verdict="clear", lap_delta_s=pace, corner=corner, close=close)
    (f,) = [f for f in fs.facts if f.data.get("kind") == "racecraft_behind"]
    assert ("Expect a look there." in f.plain) is look, f.plain
    if pace <= -3.0:  # Imola lap 31: 53 s back and 3 s a lap slower
        assert (
            f.plain
            == "The car behind is quickest through Turn 4, about a tenth a lap, but you're 3 seconds a lap quicker overall."
        )


def test_the_two_missing_lap_reasons() -> None:
    for reason, said in (
        ("needs two clean laps of you", "I need two clean laps from you first."),
        ("needs two clean laps of that car", "I need two clean laps of that car first."),
    ):
        fs = _side_sheet("ahead", verdict="unknown", lap_delta_s=None, reason=reason)
        assert radio_answer("attack", fs, "where can I pass?") == said


def _gt7_sheet() -> Any:
    from pitwall.model.telemetry import Game, SessionType

    eng = CarHealthEngine(SID)
    eng.feed(info(game=Game.GT7, session_type=SessionType.RACE, model=None))
    common = {"game": Game.GT7, "inner": None, "brakes_c": None, "engine_c": None, "wear": None, "pressure": None}
    drive(eng, 0.0, 200.0, abs_on=None, tc=None, surf=70.0, **common)
    sa = _game_analysis("gt7", "ps5")
    f = eng.frame
    assert f is not None
    live = {
        "session_id": SID,
        "connection": {"status": "live"},
        "session": {"safety_car_status": None},
        "marshal_flags": [],
        "frame": frame_to_dict(f),
        "car_health": eng.view(),
        "racecraft": eng.racecraft_view(),
    }
    return build_fact_sheet(sa, live)


async def test_a_brake_or_engine_question_is_never_answered_with_the_tyres() -> None:
    sheet = _gt7_sheet()
    for q in ("how are my brakes?", "is my engine overheating?", "brake temps?"):
        intent = detect_intent(q)
        said = radio_answer(intent.name, sheet, q)
        assert intent.name == "car_health" and said is not None and said.startswith("GT7 doesn't send brake"), (q, said)
        ans = await RaceEngineer(None).answer(q, sheet, use_llm=False, short=True)
        assert "Tyres" not in ans.text and "GT7 doesn't send" in ans.text, (q, ans.text)


def _warm_sheet(skill: str | None = None, *, laps: float = 200.0) -> Any:
    warm = CarHealthEngine(SID)
    warm.feed(info())
    drive(warm, 0.0, laps, lap_s=60.0)
    return _sheet(warm, skill=skill)


def test_hows_the_car_is_short_when_nothing_stands_out() -> None:
    sheet = _warm_sheet()
    assert radio_answer("car_health", sheet, "how's the car?") == "All normal: tyres, brakes and engine."
    assert radio_answer("car_health", sheet, "is anything overheating?") == "No. All normal: tyres, brakes and engine."
    assert radio_answer("car_health", _warm_sheet("beginner"), "is the car ok?") == "The car's fine."
    # nothing judged yet: the first part's own sentence alone, never another "need another lap" after it
    early = _warm_sheet(laps=70.0)
    assert radio_answer("car_health", early, "how's the car?") == (
        "Tyres: inside about 90 degrees. I need a few more laps to know your normal."
    )
    # the engine judged, the brakes not yet: "so far", naming only what was judged
    mid = _warm_sheet(laps=130.0)
    said = radio_answer("car_health", mid, "how's the car?")
    assert said is not None and said.startswith("All normal") and "need" not in said, said


def test_are_my_tyres_cold_is_a_yes_or_a_no() -> None:
    sheet = _warm_sheet()
    assert radio_answer("tyres", sheet, "are my tyres cold?") == "No, they're in their normal range: inside about 90."
    assert radio_answer("tyres", _warm_sheet("beginner"), "are my tyres cold?") == (
        "No, your tyres are at their normal temperature."
    )
    cold = _sheet(_cold_engine())
    yes = radio_answer("tyres", cold, "are my tyres cold?")
    assert yes == "Yes. Tyres are cold: inside about 47 degrees, your warm laps run about 88."


def test_beginners_hear_no_numbers_about_brakes_engine_or_tyres() -> None:
    sheet = _warm_sheet("beginner")
    assert radio_answer("car_health", sheet, "how are my brakes?") == "Your brakes are fine."
    assert radio_answer("car_health", sheet, "engine temperature?") == "The engine's fine."
    assert radio_answer("tyres", sheet, "are my tyres ok?") == "Your tyres are at their normal temperature."
    first = CarHealthEngine(SID)
    first.feed(info())
    drive(first, 0.0, 20.0, lap_s=60.0)
    assert radio_answer("tyres", _sheet(first, skill="beginner"), "how are my tyres?") == (
        "I can't tell yet: give me a lap or two."
    )


def test_unknown_abs_is_never_said_as_abs_on() -> None:
    from pitwall.ai.facts import FactSheet
    from pitwall.carhealth.facts import add_car_health_facts

    eng = CarHealthEngine(SID)
    eng.feed(info())
    eng.feed(frame(1.0, slip=(0.0, 0.0, 0.0, 0.0), abs_on=None, speed=30.0))
    slip = eng.view()["slip"]
    assert slip["abs"] is None and slip["reason"] == "ABS setting not known yet: lock-ups are not counted"
    view = {**slip, "last_lap": {"lap": 3, "lockups": 0, "wheelspin": 1, "wheelspin_s": 0.4, "corners": []}}
    fs = FactSheet()
    add_car_health_facts(fs, {"session_id": SID, "car_health": {"session_id": SID, "slip": view}})
    (f,) = fs.facts
    assert "ABS setting is not known yet" in f.text and "ABS on" not in f.text


def test_traction_control_is_worded_on_f1_s_scale_for_f1_only() -> None:
    """The slip block's ``tc`` is F1's CarStatus scale (0 off, 1 medium, 2 full): an ACC session's level (its own
    scale) is never said as "full" or "medium"."""
    from pitwall.ai.facts import FactSheet
    from pitwall.carhealth.facts import add_car_health_facts

    last = {"lap": 3, "lockups": 0, "wheelspin": 1, "wheelspin_s": 0.4, "corners": []}
    slip = {"available": True, "abs": True, "tc": 2, "lockups_applicable": False, "last_lap": last, "session": {}}

    def text(game: str) -> str:
        fs = FactSheet()
        add_car_health_facts(fs, {"session_id": SID, "car_health": {"session_id": SID, "game": game, "slip": slip}})
        (f,) = fs.facts
        return f.text

    assert ", traction control full;" in text("f1_25")
    acc = text("acc")
    assert "traction control" not in acc and "full" not in acc and "medium" not in acc, acc


async def test_rejoin_words_for_the_leader_a_missing_gap_and_beginners() -> None:
    from pitwall.ai.facts import FactSheet
    from pitwall.strategy.facts import add_strategy_facts

    lead = {
        "position": 1,
        "position_low": 1,
        "position_high": 1,
        "behind_position": 2,
        "gap_behind_s": 32.4,
        "game_position": 1,
        "loss_s": 22.0,
        "loss_n": 12,
        "loss_tier": "measured",
        "traffic": False,
    }
    fs = FactSheet()
    add_strategy_facts(fs, {"mode": "race", "pit": {"rejoin": lead, "pit_loss": None}})
    f = next(f for f in fs.facts if f.data.get("kind") == "rejoin")
    assert f.plain == "Box now and you'd stay in the lead, about 32 seconds clear of P2."
    assert check_grounding(f"{f.plain} [{f.id}]", [f]).ok and f.data["simple"] == "You'd still be in the lead."
    # 12 stops timed, but the player's own gap is not known this moment (right after their own stop)
    no_gap = {"position": None, "game_position": 19, "basis": "game_only", "reason": "no_gap"}
    fs = FactSheet()
    add_strategy_facts(fs, {"mode": "race", "pit": {"rejoin": no_gap, "pit_loss": {"median_s": 22.0, "n": 12}}})
    assert radio_answer("rejoin", fs, "where would I rejoin?") == (
        "Give me a few seconds to place you. The game says you'd come out about P19."
    )
    fs = FactSheet()
    add_strategy_facts(fs, {"mode": "race", "pit": {"rejoin": None, "pit_loss": {"median_s": 22.0, "n": 12}}})
    assert radio_answer("rejoin", fs, "where would I rejoin?") == "Give me a few seconds to place you."
    sa = _game_analysis("f1_25", "ps5")
    sa.driver = {"id": 1, "name": "Sam", "skill_level": "beginner"}
    fs = build_fact_sheet(
        sa,
        {
            "session_id": SID,
            "strategy": {
                "mode": "race",
                "session_id": SID,
                "pit": {"rejoin": {"position": None, "game_position": 19, "basis": "game_only", "reason": "no_loss"}},
            },
        },
    )
    assert radio_answer("rejoin", fs, "where would I rejoin?") == "The game thinks you'd come out about 19th."


def test_new_tyres_not_judged_yet_are_never_called_normal() -> None:
    from tests.unit.test_carhealth_tyres import _stop_with_a_change

    eng = CarHealthEngine(SID)
    eng.feed(info())
    t = _stop_with_a_change(eng, 78.0)  # 12 C under the warm laps: neither cold nor warm yet
    drive(eng, t, t + 3.0, inner=78.0, age=0, lap0=2, lap_s=1000.0)
    sheet = _sheet(eng)
    temps = next(f for f in sheet.facts if f.data.get("kind") == "tyre_temps")
    assert temps.plain == "Tyres: inside about 78 degrees; your warm laps run about 90."
    assert radio_answer("tyres", sheet, "are my tyres cold?") == temps.plain  # no "no, normal range" claim
    said = radio_answer("car_health", sheet, "how's the car?")
    assert said is not None and "tyres" not in said.split(":")[-1], said  # the tyres are not listed as normal
