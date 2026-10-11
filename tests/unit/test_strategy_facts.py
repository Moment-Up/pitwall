"""Strategy facts, intents and instant radio answers (``strategy.facts``, ``strategy.phrasing``, ``ai.engineer``):
every deterministic answer and every instant phrasing is grounded in the facts it came from."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from pitwall.ai.engineer import RaceEngineer, detect_intent
from pitwall.ai.facts import FactSheet, build_fact_sheet
from pitwall.ai.grounding import check_grounding
from pitwall.ai.radio_phrasing import radio_answer
from pitwall.core.session_analysis import SessionAnalysis
from pitwall.strategy.facts import add_strategy_facts
from pitwall.strategy.phrasing import strategy_radio_answer
from pitwall.strategy.view import off_view
from pitwall.voice.hub import FAST_INTENTS

VIEW: dict[str, Any] = {
    "version": 1,
    "mode": "race",
    "reason": None,
    "session_id": "s1",
    "synthetic": False,
    "lap": 34,
    "total_laps": 52,
    "laps_remaining": 18.6,
    "position": 6,
    "cars": 20,
    "gaps": {
        "ahead": {
            "car_index": 7,
            "gap_s": 1.8,
            "settled": True,
            "trend_s_per_lap": -0.3,
            "trend_laps": 4,
            "laps_to_1s": 2.7,
            "within_1s": False,
            "drs_range": False,
            "stops": 1,
            "in_pit": False,
            "tyre": {"compound": "hard", "age_laps": 12},
        },
        "behind": {
            "car_index": 14,
            "gap_s": 0.8,
            "settled": True,
            "trend_s_per_lap": None,
            "trend_laps": 2,
            "laps_to_1s": None,
            "within_1s": True,
            "drs_range": True,
            "stops": 1,
            "in_pit": False,
            "tyre": None,
        },
        "leader_s": 12.0,
        "note": "not enough laps for a trend yet",
    },
    "tyres": {
        "compound": "medium",
        "age_laps": 12,
        "stint_laps": 11,
        "wear_pct": [20.0, 21.0, 18.0, 20.0],
        "limiting_wheel": "FR",
        "rate_pct_per_lap": 1.5,
        "rate_range": {"low": 1.4, "high": 1.6},
        "limit_pct": 70.0,
        "laps_to_limit": {"low": 30.6, "high": 35.0},
        "enough_laps": True,
        "note": None,
        "game_laps_left": 26,
        "game_usable_life": 37,
        "new_set": {"compound": "medium", "gain_s": 0.69, "deg_s_per_lap": 0.091, "tier": "game"},
    },
    "fuel": {
        "fuel_kg": 12.3,
        "per_lap_kg": 1.41,
        "laps_used": 8,
        "margin_laps": 0.4,
        "margin_kg": 0.56,
        "game_margin_laps": 0.3,
        "status": "ok",
        "lift_coast": None,
        "burn_model": {"full_throttle_kg_per_s": 0.0249, "r2": 0.85, "windows": 701},
    },
    "pit": {
        "stops_done": 1,
        "stop_needed": True,
        "two_stops": False,
        "window": {"open_lap": 38, "close_lap": 44, "ideal_lap": 41, "close_source": "measured", "tier": "game"},
        "game_window": None,
        "pit_loss": {"median_s": 18.9, "range": {"low": 18.7, "high": 19.1}, "n": 2},
        "pit_loss_sc": {"full_s": 9.5, "virtual_s": 11.3, "tier": "heuristic"},
        "pit_entry_m": 4264.0,
        "rejoin": {"position": 9, "gap_ahead_s": 1.6, "gap_behind_s": 2.2, "traffic": False, "game_position": 8},
        "undercut_ahead": {
            "status": "marginal",
            "gap_s": 1.8,
            "gain": {"low": 0.63, "high": 0.9},
            "reason": "gap 1.8 s, new tyres 0.6-0.9 s a lap",
            "tier": "game",
        },
        "undercut_threat": {
            "status": "likely",
            "gap_s": 0.8,
            "gain": {"low": 0.63, "high": 0.9},
            "reason": "gap 0.8 s, new tyres 0.6-0.9 s a lap, similar tyres assumed",
            "tier": "game",
        },
        "neighbour_stop": None,
        "note": None,
    },
    "safety_car": {"status": "none", "since_lap": None, "box": None},
    "weather": {
        "now": "light_cloud",
        "rain_pct": 7,
        "track_temp_c": 34.0,
        "accuracy": "approximate",
        "forecast": [{"in_min": 5, "weather": "light_cloud", "rain_pct": 7, "in_laps": 4}],
        "next_change": None,
        "crossover": None,
    },
    "calls": [],
}


def _sheet(view: dict[str, Any]) -> FactSheet:
    fs = FactSheet()
    assert add_strategy_facts(fs, view)
    return fs


def _grounded(text: str, fs: FactSheet) -> None:
    g = check_grounding(text, fs.facts)
    assert g.ok, (text, g.ungrounded_numbers)


def test_facts_from_a_race_view_in_topic_order() -> None:
    fs = _sheet(VIEW)
    topics = [f.topic for f in fs.facts]
    assert topics.index("strategy") < topics.index("gaps") < topics.index("fuel") < topics.index("tyres")
    assert topics.index("tyres") < topics.index("weather")
    window = next(f for f in fs.facts if f.data.get("kind") == "window")
    assert window.say == "Pit window lap 38 to 44, best around lap 41." and "estimate" in window.text
    for f in fs.facts:
        assert f.data.get("src") == "strategy"
        if f.say is not None:  # every number said is in the fact itself
            assert check_grounding(f.say, [f]).ok, (f.say, f.text, f.data)


def test_no_view_or_off_mode_keeps_the_old_facts() -> None:
    assert not add_strategy_facts(FactSheet(), None)
    assert not add_strategy_facts(FactSheet(), off_view("qualifying"))
    sa = SessionAnalysis(
        session={"id": "s1", "session_type": "race", "game": "f1_25"},
        laps=[],
        model=None,
        ref_lap_id=None,
        ref_lap=None,
    )
    live = {
        "frame": {"lap_number": 34, "tyre_surface_temp_c": [90, 91, 92, 93]},
        "session": {"total_laps": 52},
        "strategy": VIEW,
    }
    with_strategy = build_fact_sheet(sa, live)
    texts = " ".join(f.text for f in with_strategy.facts)
    assert "Fuel (measured)" in texts and "Fuel usage per lap is not yet known" not in texts
    assert "Current tyre surface temps" in texts  # still from the frame
    legacy = build_fact_sheet(sa, {**live, "strategy": off_view("qualifying")})
    assert "Fuel usage per lap is not yet known" in " ".join(f.text for f in legacy.facts)


def test_practice_view() -> None:
    practice = copy.deepcopy(VIEW)
    practice.update(mode="practice", gaps=None, pit=None, safety_car=None)
    fs = _sheet(practice)
    assert strategy_radio_answer("strategy", fs) == (
        "No pit window in practice. Mediums, 12 laps old. Front right is the most worn at 21 percent, about 1.5 percent "
        "a lap: about 31 to 35 laps to 70 percent."
    )
    assert not [f for f in fs.facts if f.topic == "gaps"]


@pytest.mark.parametrize(
    ("q", "intent"),
    [
        ("when should I pit?", "strategy"),
        ("gap to the car ahead?", "gaps"),
        ("what's the gap to my best lap", "compare"),
        ("is it going to rain", "weather"),
        ("safety car, should I box?", "strategy"),
        ("fuel?", "fuel"),
        ("how far behind is the car behind me", "gaps"),
        ("what position am I", "gaps"),
        ("should we go to inters", "weather"),
        ("How are my tyres?", "tyres"),
        ("are we staying out?", "general"),
        ("stay out or box?", "strategy"),
    ],
)
def test_intents(q: str, intent: str) -> None:
    assert detect_intent(q).name == intent


@pytest.mark.parametrize("intent", ["strategy", "gaps", "fuel", "tyres", "weather"])
async def test_deterministic_answers_are_grounded(intent: str) -> None:
    sa = SessionAnalysis(
        session={"id": "s1", "session_type": "race", "game": "f1_25"},
        laps=[],
        model=None,
        ref_lap_id=None,
        ref_lap=None,
    )
    sheet = build_fact_sheet(sa, {"frame": {"lap_number": 34}, "session": {"total_laps": 52}, "strategy": VIEW})
    q = {
        "strategy": "when should I pit?",
        "gaps": "gap to the car ahead?",
        "fuel": "fuel?",
        "tyres": "how are my tyres?",
        "weather": "is it going to rain?",
    }[intent]
    ans = await RaceEngineer(None).answer(q, sheet, use_llm=False)
    assert ans.intent == intent and ans.grounded and ans.fallback
    assert check_grounding(ans.cited_text, [f for f in sheet.facts if f.id in ans.cited_text]).ok
    assert "[F" not in ans.text


def test_instant_phrasings() -> None:
    fs = _sheet(VIEW)
    answers = {i: strategy_radio_answer(i, fs) for i in ("strategy", "gaps", "fuel", "tyres", "weather")}
    assert answers["strategy"] == (
        "Pit window lap 38 to 44, best around lap 41. Undercut on the car ahead is marginal: gap 1.8 s, new tyres "
        "worth about 0.9 s a lap."
    )
    assert answers["gaps"] == "Car ahead plus 1.8, closing 0.3 s a lap. Car behind 0.8, within a second, DRS range."
    assert answers["fuel"] == "Using 1.41 kilos a lap, plus 0.4 laps to the finish."
    assert answers["weather"] == "Light cloud, rain 7 percent. Forecast: no change for the next 15 minutes."
    for text in answers.values():
        assert text is not None
        _grounded(text, fs)
    assert radio_answer("gaps", fs) == answers["gaps"]  # the radio tries the strategy phrasing first
    assert strategy_radio_answer("lap_times", fs) is None and strategy_radio_answer("fuel", FactSheet()) is None


def test_short_of_fuel_answer_brings_lift_and_coast() -> None:
    short = copy.deepcopy(VIEW)
    short["fuel"].update(
        margin_laps=-0.3,
        margin_kg=-0.42,
        status="short",
        lift_coast={"save_kg_per_lap": 0.05, "seconds_per_lap": 2.1, "feasible": True, "corners": ["T3", "T4"]},
    )
    fs = _sheet(short)
    ans = strategy_radio_answer("fuel", fs)
    assert ans == (
        "Using 1.41 kilos a lap, minus 0.3 laps to the finish. Lift and coast about 2.1 seconds a lap before T3 and T4: "
        "brake at your normal point."
    )
    _grounded(ans, fs)
    assert "later" not in ans


def test_safety_car_answer_and_not_enough_laps() -> None:
    sc = copy.deepcopy(VIEW)
    sc["safety_car"] = {
        "status": "virtual",
        "since_lap": 33,
        "box": {
            "pit_loss_s": 11.3,
            "green_pit_loss_s": 18.9,
            "stop_needed": True,
            "this_lap": True,
            "tier": "heuristic",
        },
    }
    fs = _sheet(sc)
    ans = strategy_radio_answer("strategy", fs)
    assert ans == "Virtual safety car. Pitting this lap is an option: a stop costs about 11 s now, 19 s under green."
    _grounded(ans, fs)
    unknown = copy.deepcopy(sc)
    unknown["safety_car"]["box"]["this_lap"] = None  # no stop seen yet: the pit entry is unknown
    ans = strategy_radio_answer("strategy", _sheet(unknown))
    assert ans == "Virtual safety car. Pitting is an option: a stop costs about 11 s now, 19 s under green."
    early = copy.deepcopy(VIEW)
    early["pit"].update(window=None, stop_needed=None)
    assert strategy_radio_answer("strategy", _sheet(early)).startswith(  # type: ignore[union-attr]
        "Not enough laps on this set yet: I need three green laps."
    )


def test_fast_intents() -> None:
    assert {"gaps", "weather", "strategy", "fuel", "tyres"} <= FAST_INTENTS


def test_leading_gap_answer_says_so() -> None:
    """P1 has no car ahead: the gaps answer starts with the position instead of only the car behind (real Austria
    race, e2e: "gap to the car ahead?" got only "Car behind 0.3, within a second.")."""
    lead = copy.deepcopy(VIEW)
    lead["position"] = 1
    lead["gaps"]["ahead"] = None
    lead["gaps"]["leader_s"] = None
    fs = _sheet(lead)
    ans = strategy_radio_answer("gaps", fs)
    assert ans == "P1, leading. Car behind 0.8, within a second, DRS range."
    _grounded(ans, fs)


async def test_leading_engineer_answer_mentions_the_lead() -> None:
    lead = copy.deepcopy(VIEW)
    lead["position"] = 1
    lead["gaps"]["ahead"] = None
    lead["gaps"]["leader_s"] = None
    sa = SessionAnalysis(
        session={"id": "s1", "session_type": "race", "game": "f1_25"},
        laps=[],
        model=None,
        ref_lap_id=None,
        ref_lap=None,
    )
    sheet = build_fact_sheet(sa, {"frame": {"lap_number": 34}, "session": {"total_laps": 52}, "strategy": lead})
    ans = await RaceEngineer(None).answer("gap to the car ahead?", sheet, use_llm=False)
    assert ans.intent == "gaps" and ans.grounded and "leading" in ans.text and "behind" in ans.text


def test_one_lap_old_tyres_in_the_singular() -> None:
    young = copy.deepcopy(VIEW)
    young["tyres"]["age_laps"] = 1
    fs = _sheet(young)
    ans = strategy_radio_answer("tyres", fs)
    assert ans is not None and "1 lap old" in ans and "1 laps" not in ans
    _grounded(ans, fs)


def test_unsettled_gaps_keep_their_qualifier_on_the_radio() -> None:
    # review: the radio said "Car ahead plus 1.4." while that car was in the pit lane
    v = copy.deepcopy(VIEW)
    v["gaps"]["ahead"].update(settled=False, in_pit=True)
    v["gaps"]["behind"].update(settled=False)
    ans = strategy_radio_answer("gaps", _sheet(v))
    assert ans == "Car ahead is in the pit lane. Car behind 0.8 (last settled), within a second, DRS range."
    _grounded(ans, _sheet(v))


def _tyre_say(**over: Any) -> str:
    v = copy.deepcopy(VIEW)
    v["tyres"].update(over)
    ans = strategy_radio_answer("tyres", _sheet(v))
    assert ans is not None
    return ans


def test_tyre_wording_on_real_data() -> None:
    # review M7, from real Melbourne (super soft) and the first lap of a late-joined Austria race
    assert _tyre_say(compound=None, age_laps=None, wear_pct=None, new_set=None, game_laps_left=None).startswith(
        "No tyre data yet."
    )
    assert _tyre_say(compound="super_soft", age_laps=0, enough_laps=False).startswith("Super softs, new.")
    one = _tyre_say(laps_to_limit={"low": 7.2, "high": 7.4})
    assert "about 7 laps to 70 percent" in one and "7 to 7" not in one
    assert "The game gives this set 1 more lap;" in _tyre_say(game_laps_left=1)
    assert "The game says this set is at its limit" in _tyre_say(game_laps_left=0)
    flat = _tyre_say(new_set={"compound": "hard", "gain_s": 0.02, "deg_s_per_lap": None, "tier": "game"})
    assert "worth" not in flat
    fresh = _tyre_say(wear_pct=[0.0, 0.4, 0.0, 0.0], enough_laps=False)
    assert "most worn" not in fresh


def test_one_lap_and_overdue_windows_and_rain_after_the_flag() -> None:
    v = copy.deepcopy(VIEW)
    v["pit"]["window"] = {"open_lap": 41, "close_lap": 41, "ideal_lap": 41, "close_source": "game", "tier": "game"}
    assert strategy_radio_answer("strategy", _sheet(v)).startswith(  # type: ignore[union-attr]
        "Pit window: lap 41, on the game's tyre figure."
    )
    v["pit"]["window"]["overdue"] = True
    assert strategy_radio_answer("strategy", _sheet(v)).startswith(  # type: ignore[union-attr]
        "Tyres at the wear limit: the window is this lap"
    )
    w = copy.deepcopy(VIEW)
    w["laps_remaining"] = 3.9
    w["weather"]["next_change"] = {"in_min": 10, "weather": "light_rain", "rain_pct": 60, "in_laps": 10}
    ans = strategy_radio_answer("weather", _sheet(w))
    assert ans is not None and ans.endswith("around 10 laps, after the flag.")


def test_lift_and_coast_beyond_a_realistic_save_says_so() -> None:
    v = copy.deepcopy(VIEW)
    v["fuel"].update(
        margin_laps=-1.2,
        status="short",
        lift_coast={"save_kg_per_lap": 0.4, "seconds_per_lap": 8.5, "feasible": False, "corners": []},
    )
    ans = strategy_radio_answer("fuel", _sheet(v))
    assert ans is not None and ans.endswith(
        "Lift and coast would need about 8.5 seconds a lap: more than you can realistically save."
    )
    _grounded(ans, _sheet(v))
