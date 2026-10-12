"""Setup › Controls "Map it" steps: the game's menu-group order, research names verbatim, physical and platform words,
and the generic steps for another game."""

from __future__ import annotations

from pitwall.controls.recommend import recommend
from pitwall.controls.steps import guide, physical
from tests.unit.controls_support import CAT, custom_acc_wheel, tmpl


def test_f1_steps_follow_the_menu_groups_with_verbatim_names() -> None:
    w = tmpl("fanatec_gt_dd_pro_wheel")
    rec = recommend(CAT, w, "f1_25", "ps5", "advanced")
    g = guide(CAT, "f1_25", "ps5", w, rec.plain_assignments())
    assert g["where"] == "Controls > [your wheel's preset]" and g["where_evidence"] == "V"
    groups = [s["group"] for s in g["steps"]]
    order = ["Control Scheme", "MFD Shortcuts", "UDP Custom Actions"]
    assert groups == sorted(groups, key=order.index)
    natives = {r.native_name for r in CAT.games["f1_25"].functions.values()} | {"UDP Action 1"}
    assert all(s["native"] in natives for s in g["steps"])
    ptt = next(s for s in g["steps"] if s["native"] == "UDP Action 1")
    assert (
        ptt["label"] == "Talk to Pitwall"
        and ptt["physical"].startswith("Press TRIANGLE")
        and "(Triangle)" in ptt["physical"]
    )
    bb = next(s for s in g["steps"] if s["label"].startswith("Brake bias +"))
    assert "(Brake Bias Increase)" in bb["label"] and bb["evidence"] == "A"
    assert [s["n"] for s in g["steps"]] == list(range(1, len(g["steps"]) + 1))
    assert any("preset for this wheel" in line for line in g["intro"])
    assert g["outro"] == ["Open Test to check each button reaches Pitwall."]


def test_physical_and_platform_words() -> None:
    mcl = tmpl("fanatec_csl_elite_mclaren_gt3_v2")
    enc = mcl.control("enc12")
    assert enc is not None
    assert physical(CAT, enc, "ccw", "ps") == "Turn LEFT ENCODER (12) anticlockwise (GSB 6/7, game-specific)"
    assert physical(CAT, enc, "cw", "pc") == "Turn LEFT ENCODER (12) clockwise (button 33 or 31)"
    b3 = mcl.control("b3")
    assert b3 is not None and physical(CAT, b3, "press", "xbox") == "Press BUTTON 3 (Y)"
    funky = mcl.control("funky5")
    assert funky is not None and physical(CAT, funky, "up", "ps") == "Push FUNKY SWITCH (5) up (D-pad up)"
    assert physical(CAT, funky, "push", "ps") == "Press FUNKY SWITCH (5) in (GSB 1, game-specific)"
    gt = tmpl("fanatec_gt_dd_pro_wheel")
    menu = gt.control("menu_stick")
    assert menu is not None and physical(CAT, menu, "down", "ps") == "Push MENU STICK down (D-pad down)"


def test_gt7_steps_name_the_fixed_sticks_and_the_unresearched_path() -> None:
    w = tmpl("fanatec_gt_dd_pro_wheel")
    rec = recommend(CAT, w, "gt7", "ps5", "advanced")
    g = guide(CAT, "gt7", "ps5", w, rec.plain_assignments())
    assert g["where_evidence"] == "A"
    assert any("sets those itself" in line for line in g["intro"])
    assert all("fixed" not in s["label"] for s in g["steps"])
    assert g["outro"][0].startswith("Check each one on track: Pitwall can't see your wheel in Gran Turismo 7")


def test_other_game_uses_generic_steps_and_synonyms() -> None:
    w = custom_acc_wheel()
    rec = recommend(
        CAT, w, "other", "pc", "advanced", other_functions=["brake_bias", "pit_limiter"], game_name="Rally Sim"
    )
    g = guide(
        CAT,
        "other",
        "pc",
        w,
        rec.plain_assignments(),
        game_name="Rally Sim",
        other_functions=["brake_bias", "pit_limiter"],
    )
    assert g["where"] == "the game's Controls screen" and g["where_evidence"] is None
    assert g["intro"] == list(CAT.other_game_steps)
    bb = next(s for s in g["steps"] if s["label"].startswith("Brake bias"))
    assert bb["native"] == "" and "brake balance" in (bb["note"] or "")
    assert "Rally Sim" in g["outro"][0]
