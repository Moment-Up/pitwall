"""F2 support in the engineer, its facts, the race strategy view and the game / capability catalogues.

* "How much ERS?" in an F2 car: no ERS (F1 25 sends 0 for F2 cars), never a made-up store.
* "Was a pit stop mandatory?": the game sends no stop rules, so the answer says they are not known, then the F2 note,
  then the tyre statement, and never "no". Only rule words ask it: "do I need to pit (this lap / under the safety
  car)?" stays strategy, "do I need to stop braking early?" braking; under a safety car the box call comes first.
* "Is DRS available?": its own intent (no longer ERS's), answered from the game's DRS fields.
"""

from __future__ import annotations

from typing import Any

import pytest

from pitwall import games
from pitwall.ai.engineer import RaceEngineer, detect_intent
from pitwall.ai.facts import build_fact_sheet
from pitwall.capabilities import CAR_CLASSES, capability_matrix, car_class_status
from pitwall.core.session_analysis import SessionAnalysis
from pitwall.strategy.facts import add_strategy_facts
from pitwall.strategy.view import F2_FEATURE_NOTE, F2_SPRINT_NOTE, RULES_TEXT, off_view, pit_rules

F2_SESSION: dict[str, Any] = {
    "id": "f2race",
    "game": "f1_25",
    "platform": "ps5",
    "track_name": "Jeddah",
    "track_id": "f1:29",
    "session_type": "race",
    "session_type_raw": "Race 2",
    "car_id": "f1:team:158",
    "car_name": "Art GP '24",
    "weather": {"condition": "light_cloud", "track_temp_c": 32, "air_temp_c": 26},
    "info": {"formula": "F2", "packet_format": 2025, "weekend_structure": [15, 16]},  # recorded: Melbourne
}


def _sa(session: dict[str, Any] | None = None) -> SessionAnalysis:
    laps = [
        {"lap_number": 1, "lap_time_ms": 112_550, "clean": False, "flags": ["standing_start"]},
        {"lap_number": 2, "lap_time_ms": 106_072, "clean": True, "flags": []},
    ]
    return SessionAnalysis(session=session or F2_SESSION, laps=laps, model=None, ref_lap_id=None, ref_lap=None)


def _view(stop_needed: bool | None = False, drs: bool | None = True) -> dict[str, Any]:
    v = off_view(None, "f2race")
    v.update(mode="race", lap=3, total_laps=5, drs_enabled=drs)
    v["pit"] = {"stop_needed": stop_needed, "window": None, "two_stops": None, "pit_loss": None}
    v["pit"]["rules"] = pit_rules(None, "Race 2")
    return v


def _live(**frame: Any) -> dict[str, Any]:
    return {
        "connection": {"status": "live"},
        "session_id": "f2race",
        "session": {"total_laps": 5, "safety_car_status": "none"},
        "frame": {"lap_number": 3, "ers_store_j": None, **frame},
        "strategy": _view(),
        "marshal_flags": [],
    }


@pytest.mark.parametrize(
    ("q", "intent"),
    [
        ("Is DRS available?", "drs"),
        ("Did I get DRS?", "drs"),
        ("Can I use DRS?", "drs"),
        ("Am I in DRS range?", "gaps"),  # the gaps rule keeps "DRS range"
        ("Was a pit stop mandatory?", "stop_rules"),
        ("Do I need to use both compounds?", "stop_rules"),
        ("What are the stop rules?", "stop_rules"),
        ("What are the pit stop rules here?", "stop_rules"),
        ("Is a pit stop required in this race?", "stop_rules"),
        ("Do I have to run both tyres?", "stop_rules"),
        ("When should I pit?", "strategy"),
        # a plain "do I need to pit / box" is strategy (F1 and F2 alike); no rule words, no rules answer
        ("Do I have to pit?", "strategy"),
        ("Must I pit this race?", "strategy"),
        ("Do I need to pit under the safety car?", "strategy"),
        ("Do I need to box this lap?", "strategy"),
        ("When do I need to pit?", "strategy"),
        ("Do I need to stop braking so early into turn 1?", "braking"),
        ("Do I have to stop lifting in turn 3?", "corner"),
        ("Are both tyres on the left worn?", "tyres"),
        ("How much ERS have I got?", "ers"),
        ("Should I use overtake mode?", "ers"),
    ],
)
def test_intents(q: str, intent: str) -> None:
    assert detect_intent(q).name == intent


def test_session_fact_names_the_class_and_the_f2_race() -> None:
    sheet = build_fact_sheet(_sa())
    s = next(f for f in sheet.facts if f.topic == "session")
    assert "Feature race (the game calls it Race 2)" in s.text
    # the car's name already says F2: no "(car class F2)" after it
    assert "car F2 · Art GP '24, weather" in s.text and s.data["car_class"] == "f2" and "car class" not in s.text
    osq = {**F2_SESSION, "session_type": "qualifying", "session_type_raw": "One-Shot Qualifying"}
    s2 = next(f for f in build_fact_sheet(_sa(osq)).facts if f.topic == "session")
    assert ", One-shot qualifying, car" in s2.text and "the game calls it" not in s2.text
    mclaren = {**F2_SESSION, "car_id": "f1:team:8", "car_name": "McLaren", "info": {"formula": "F1 Modern"}}
    s1 = next(f for f in build_fact_sheet(_sa(mclaren)).facts if f.topic == "session")
    assert ", Race 2, car McLaren (car class F1)," in s1.text  # only F2 renames the race


async def test_ers_questions_in_an_f2_car() -> None:
    sheet = build_fact_sheet(_sa(), _live())
    assert not any(f.topic == "ers" and "MJ" in f.text for f in sheet.facts)  # never a made-up store
    for q in ("How much ERS have I got?", "Should I use overtake mode?"):
        ans = await RaceEngineer(None).answer(q, sheet)
        assert ans.text == "F2 cars have no ERS, so there's nothing to deploy." and ans.grounded, q
        short = await RaceEngineer(None).answer(q, sheet, use_llm=False, short=True)
        assert short.text == "F2 cars have no ERS, so there's nothing to deploy."


_NO = ("not mandatory", "isn't mandatory", "no stop needed", "no tyre stop needed", "you don't need to")


async def test_stop_rules_are_never_answered_no() -> None:
    sheet = build_fact_sheet(_sa(), _live())
    ans = await RaceEngineer(None).answer("Was a pit stop mandatory?", sheet)
    assert ans.text == (
        "I don't know this race's stop rules: the game doesn't send them. " + F2_FEATURE_NOTE + " The tyres reach "
        "the finish."
    )
    assert ans.grounded and not any(n in ans.text.lower() for n in _NO)
    radio = await RaceEngineer(None).answer("Is a stop mandatory?", sheet, use_llm=False, short=True)
    assert radio.text.startswith("I don't know this race's stop rules") and not any(
        n in radio.text.lower() for n in _NO
    )
    # the LLM never answers it: deterministic even with a provider
    from tests.unit.test_ai import FakeProvider

    p = FakeProvider(["No, the stop is not mandatory [F1]."])
    llm = await RaceEngineer(p).answer("Do I need to use both compounds?", sheet, use_llm=True)
    assert not p.calls and llm.text.startswith("I don't know this race's stop rules")
    # the sprint, and an F1 race: the rules are still not known
    sprint = {**F2_SESSION, "session_type_raw": "Race"}
    s_ans = await RaceEngineer(None).answer("Is the stop compulsory?", build_fact_sheet(_sa(sprint)))
    assert F2_SPRINT_NOTE in s_ans.text and s_ans.text.startswith("I don't know this race's stop rules")
    # a race-only weekend (or one whose structure is not known): not called a sprint, no sprint note
    alone = {**sprint, "info": {"formula": "F2", "packet_format": 2025, "weekend_structure": [15]}}
    a_ans = await RaceEngineer(None).answer("Is the stop compulsory?", build_fact_sheet(_sa(alone)))
    assert "sprint" not in a_ans.text and a_ans.text.startswith("I don't know this race's stop rules")
    f1 = {**F2_SESSION, "car_id": "f1:team:8", "info": {"formula": "F1 Modern"}, "session_type_raw": "Race"}
    f1_ans = await RaceEngineer(None).answer("Was a pit stop mandatory?", build_fact_sheet(_sa(f1)))
    assert f1_ans.text.startswith("I don't know this race's stop rules") and "F2" not in f1_ans.text


async def test_drs_answers() -> None:
    allowed = build_fact_sheet(_sa(), _live(drs_allowed=True, drs_activation_m=None))
    a = await RaceEngineer(None).answer("Is DRS available?", allowed)
    assert a.text.startswith("DRS is allowed now.") and "DRS is enabled in this race." in a.text and a.grounded
    waiting = build_fact_sheet(_sa(), _live(drs_allowed=False, drs_activation_m=120))
    w = await RaceEngineer(None).answer("Can I use DRS?", waiting, use_llm=False, short=True)
    assert w.text.startswith("DRS isn't allowed yet: available in 120 m.")
    gt7 = {**F2_SESSION, "game": "gt7", "car_id": None, "info": {}}
    g = await RaceEngineer(None).answer("Is DRS available?", build_fact_sheet(_sa(gt7)))
    assert "DRS" in g.text and "doesn't send" in g.text  # a game that never sends DRS says so


def test_legacy_pit_window_says_the_rules_are_not_known() -> None:
    from pitwall.ai.facts import FactSheet

    fs = FactSheet()
    v = _view(stop_needed=False)
    assert add_strategy_facts(fs, v)
    no_stop = next(f for f in fs.facts if f.data.get("kind") == "no_stop")
    assert (
        no_stop.text.endswith("The race's stop rules are not known.") and no_stop.say == "The tyres reach the finish."
    )


def test_strategy_rules_block() -> None:
    from pitwall.carclass import classify

    f2 = classify("f1_25", "F2", "f1:team:158", 2025)
    assert pit_rules(f2, "Race 2") == {
        "race": "feature",
        "known": False,
        "text": RULES_TEXT,
        "class_note": F2_FEATURE_NOTE,
    }
    sprint = pit_rules(f2, "Race", [15, 16])
    assert sprint["race"] == "sprint" and sprint["class_note"] == F2_SPRINT_NOTE
    assert pit_rules(f2, "Race")["race"] is None and pit_rules(f2, "Race", [15])["class_note"] is None
    f1 = classify("f1_25", "F1 Modern", "f1:team:8", 2025)
    assert pit_rules(f1, "Race") == {"race": None, "known": False, "text": RULES_TEXT, "class_note": None}
    assert off_view(None)["drs_enabled"] is None


def test_compounds_in_words_reach_the_model() -> None:
    from pitwall.ai.facts import FactSheet

    fs = FactSheet()
    v = _view()
    v["tyres"] = {"compound": "super_soft", "age_laps": 1, "wear_pct": None, "enough_laps": False, "note": None}
    v["gaps"] = {
        "ahead": {
            "car_index": 3,
            "gap_s": 0.8,
            "within_1s": True,
            "drs_range": True,
            "tyre": {"compound": "super_soft"},
        },
        "behind": None,
        "leader_s": None,
        "note": None,
    }
    add_strategy_facts(fs, v)
    texts = " ".join(f.text for f in fs.facts)
    assert "super_soft" not in texts and "super soft" in texts


def test_games_and_capabilities_list_the_car_classes() -> None:
    assert car_class_status("f1_25", "f2") == "recorded_validated"
    assert car_class_status("f1_25", "f1_2025") == "live_validated"
    assert car_class_status("f1_25", "f1_2026") == car_class_status("f1_25", "f1_classic") == "spec_implemented"
    assert car_class_status("f1_25", "other") == "unverified" and car_class_status("gt7", "f2") is None
    assert {c.id for c in CAR_CLASSES} == {"f1_2025", "f1", "f1_2026", "f2", "f1_classic", "other"}
    rows = {r["key"]: r for r in capability_matrix()}
    assert [c["id"] for c in rows["f1_25_2025_ps5"]["car_classes"]][:4] == ["f1_2025", "f1", "f1_2026", "f2"]
    assert "car_classes" not in rows["gt7_ps5"]
    f1 = games.entry("f1_25:ps5")
    assert f1 is not None
    d = f1.to_dict()
    assert any(c["id"] == "f2" and c["status"] == "recorded_validated" for c in d["car_classes"])
    ers = next(f for f in d["features"] if f["id"] == "ers")
    assert ers["note"] == "F2 cars have no ERS: F1 25 sends 0 for them, so Pitwall shows none (recorded on PS5)."
    assert games.INTENT_FEATURES["ers"] == ("ers",) and games.INTENT_FEATURES["drs"] == ("drs",)
    gt7 = games.entry("gt7:ps5")
    assert gt7 is not None and "car_classes" not in gt7.to_dict()


async def test_rules_and_strategy_questions_under_a_safety_car_and_outside_a_race() -> None:
    """Review C1: "do I need to pit under the safety car?" gets the box call (strategy), as before F2 support; a rules
    question under a safety car leads with the box call too; outside a race there is no rules fact."""
    v = _view(stop_needed=True)
    v["safety_car"] = {
        "status": "full",
        "since_lap": 2,
        "box": {"stop_needed": True, "this_lap": True, "pit_loss_s": 11.0, "green_pit_loss_s": 21.0, "tier": "game"},
    }
    f1_race = {**F2_SESSION, "car_id": "f1:team:8", "car_name": "McLaren", "info": {"formula": "F1 Modern"}}
    live = {**_live(), "strategy": v}
    sheet = build_fact_sheet(_sa(f1_race), live)
    for q in ("Do I need to pit under the safety car?", "Do I need to box this lap?"):
        ans = await RaceEngineer(None).answer(q, sheet, use_llm=False, short=True)
        assert ans.text.startswith("Safety car. Pitting this lap is an option"), (q, ans.text)
        assert "stop rules" not in ans.text
    rules = await RaceEngineer(None).answer("Is a pit stop mandatory?", sheet, use_llm=False)
    assert rules.text.startswith("Safety car. Pitting this lap is an option")
    assert "I don't know this race's stop rules" in rules.text
    radio = await RaceEngineer(None).answer("Is a pit stop mandatory?", sheet, use_llm=False, short=True)
    assert radio.text.startswith("Safety car. Pitting this lap is an option")
    # practice / qualifying: no rules fact, and the plain question is strategy
    osq = {**F2_SESSION, "session_type": "qualifying", "session_type_raw": "One-Shot Qualifying"}
    q_sheet = build_fact_sheet(_sa(osq))
    assert not any(f.topic == "rules" for f in q_sheet.facts)
    q_ans = await RaceEngineer(None).answer("Do I need to pit?", q_sheet, use_llm=False)
    assert "stop rules" not in q_ans.text


async def test_drs_open_beats_the_momentary_allowed_flag() -> None:
    """Review U4: F1 25 sets the DRS-allowed flag only for a moment before the flap opens (recorded: 2 samples a lap,
    hundreds open), so an open flap is said to be open, never "DRS isn't allowed now"."""
    sheet = build_fact_sheet(_sa(), _live(drs_open=True, drs_allowed=False, drs_activation_m=None))
    a = await RaceEngineer(None).answer("Can I use DRS?", sheet, use_llm=False, short=True)
    assert a.text.startswith("DRS is open.") and "isn't allowed" not in a.text
