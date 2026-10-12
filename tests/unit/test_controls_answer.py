"""Setup › Controls engineer answers ("which button is brake bias?"): from the saved layout, at most 30 words, the
live value only from a real F1 stream, and the catalogue's sentences for what can't go on a button."""

from __future__ import annotations

from pitwall.ai.engineer import RaceEngineer, detect_intent
from pitwall.ai.facts import FactSheet
from pitwall.controls import model as M
from pitwall.controls.answer import LiveValues, answer, match_function, speech
from tests.unit.controls_support import CAT, tmpl

F1, GT7 = CAT.games["f1_25"], CAT.games["gt7"]


def owner_state() -> M.ControlsState:
    w = M.parse_wheel({**tmpl("fanatec_gt_dd_pro_wheel").to_dict(), "id": "w_00000001", "rev": 1})
    asg = (
        M.Assignment("ptt_pitwall.hold", "ptt_pitwall", "hold", "face_triangle", "press", 3),
        M.Assignment("brake_bias.inc", "brake_bias", "inc", "tab_r3", "press"),
        M.Assignment("brake_bias.dec", "brake_bias", "dec", "tab_l3", "press"),
        M.Assignment("ers_mode.inc", "ers_mode", "inc", "tab_r2", "press"),
        M.Assignment("ers_mode.dec", "ers_mode", "dec", "tab_l2", "press"),
        M.Assignment("drs_aero.press", "drs_aero", "press", "face_square", "press"),
    )
    lay = M.Layout("l_00000001", 1, "f1_25", None, "ps5", "w_00000001", 1, "advanced", None, asg)
    return M.ControlsState(wheels=(w,), layouts=(lay,)).with_owner_choice(lay)


def test_function_matching_uses_labels_and_game_names() -> None:
    assert match_function(CAT, "Which button is brake bias?") == "brake_bias"
    assert match_function(CAT, "which dial is the brake balance") == "brake_bias"
    assert match_function(CAT, "What button do I press for DRS?") == "drs_aero"
    assert match_function(CAT, "Which button is push to talk?") == "ptt_pitwall"
    assert match_function(CAT, "which button is the game's push to talk") == "ptt_game"
    assert match_function(CAT, "where is ASM on my wheel") == "stability"
    assert match_function(CAT, "which button is it") is None


def test_answers_from_the_saved_layout() -> None:
    st = owner_state()
    live = LiveValues(brake_bias_front_pct=56.0, ers_deploy_mode=2)
    a = answer(CAT, st, "Which button is brake bias?", game=F1, platform="ps5", driver_id=1, live=live)
    assert a == "In your layout, brake bias + is R3 tab and − is L3 tab. It's 56 percent front now."
    assert speech(a) == "In your layout, brake bias plus is R3 tab and minus is L3 tab. It's 56 percent front now."
    e = answer(CAT, st, "which button is ERS mode", game=F1, platform="ps5", driver_id=1, live=live)
    assert e.endswith("ERS mode is hotlap now.")
    no_live = answer(CAT, st, "Which button is brake bias?", game=F1, platform="ps5", driver_id=1, live=None)
    assert "percent" not in no_live
    assert answer(CAT, st, "Which button is push to talk?", game=F1, platform="ps5", driver_id=1) == (
        "Talk to me with Triangle, UDP Action 3."
    )
    assert answer(CAT, st, "What button is DRS?", game=F1, platform="ps5", driver_id=1) == (
        "In your layout, drs / active aero is Square."
    )
    for q in ("which button is brake bias", "where is the diff on my wheel", "button for the pit limiter?"):
        assert len(answer(CAT, st, q, game=F1, platform="ps5", driver_id=1, live=live).split()) <= 30


def test_what_cannot_go_on_a_button() -> None:
    st = owner_state()
    gt7 = answer(CAT, st, "Which button is ASM?", game=GT7, platform="ps5", driver_id=1)
    assert "pause menu" in gt7 and "Assistance Settings" in gt7
    tc = answer(CAT, st, "Which button is traction control?", game=F1, platform="ps5", driver_id=1)
    assert "assists you set in the menu" in tc
    ptt = answer(CAT, st, "Which button is push to talk?", game=GT7, platform="ps5", driver_id=1)
    assert "iPad" in ptt
    diff = answer(CAT, st, "which button is the differential", game=F1, platform="ps5", driver_id=1)
    assert diff == "Differential isn't on your wheel in your F1 25 layout. Use the MFD."


def test_no_layout_no_game() -> None:
    st = M.ControlsState()
    assert answer(CAT, st, "Which button is DRS?", game=F1, platform="ps5", driver_id=1) == (
        "You haven't saved buttons for F1 25 yet. Open Setup, then Controls."
    )
    assert answer(CAT, st, "Which button is DRS?", game=None, platform=None, driver_id=1).startswith("Tell me which")


async def test_the_engineer_routes_it_to_the_handler_never_the_llm() -> None:
    eng = RaceEngineer(None)
    none = await eng.answer("Which button is brake bias?", FactSheet(), use_llm=True)
    assert none.intent == "controls_where" and none.text == "Button layouts aren't available right now."
    eng.controls_handler = lambda intent, q: answer(CAT, owner_state(), q, game=F1, platform="ps5", driver_id=1)
    got = await eng.answer("Which button is brake bias?", FactSheet(), use_llm=True)
    assert got.text.startswith("In your layout, brake bias +") and "plus" in got.speech
    assert got.grounded and not got.fallback and got.model is None and got.facts == []
    assert detect_intent("What brake bias should I run?").name == "setup"


def test_a_long_research_sentence_is_cut_at_a_clause_not_mid_clause() -> None:
    from pitwall.controls.answer import MAX_WORDS, _trim

    long = (
        "No game Pitwall knows lets you change ride height while driving. F1 25 and GT7 only show it in the car "
        "setup; iRacing's weight jacker on some oval cars is the closest thing."
    )
    out = _trim(long)
    assert out == (
        "No game Pitwall knows lets you change ride height while driving. F1 25 and GT7 only show it in the car setup."
    )
    assert len(out.split()) <= MAX_WORDS and _trim("Short answer.") == "Short answer."
