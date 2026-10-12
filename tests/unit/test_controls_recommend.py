"""Setup › Controls recommendations (spec 3): golden layouts for the owner's rig and other wheels and games, plus the
invariants that must hold for every template, game, platform and preset."""

from __future__ import annotations

import itertools

import pytest

from pitwall.controls.catalog import PTT_FUNCTION
from pitwall.controls.model import Assignment, signal_platform
from pitwall.controls.recommend import MAX_REASON, Recommendation, expand_slots, recommend
from tests.unit.controls_support import CAT, custom_acc_wheel, golden, summary, tmpl

CASES = {
    "f1_ps5_gt_dd_pro_beginner": ("f1_25", "ps5", "fanatec_gt_dd_pro_wheel", "beginner"),
    "f1_ps5_gt_dd_pro_advanced": ("f1_25", "ps5", "fanatec_gt_dd_pro_wheel", "advanced"),
    "f1_pc_mclaren_advanced": ("f1_25", "pc", "fanatec_csl_elite_mclaren_gt3_v2", "advanced"),
    "f1_xbox_mclaren_advanced": ("f1_25", "xbox", "fanatec_csl_elite_mclaren_gt3_v2", "advanced"),
    "gt7_ps5_gt_dd_pro_advanced": ("gt7", "ps5", "fanatec_gt_dd_pro_wheel", "advanced"),
}


def _rec(name: str) -> Recommendation:
    game, platform, tid, preset = CASES[name]
    return recommend(CAT, tmpl(tid), game, platform, preset)


@pytest.mark.parametrize("name", sorted(CASES))
def test_golden_layouts(name: str) -> None:
    got = summary(_rec(name))
    assert got == golden(name, got)


def test_golden_acc_custom_box_and_other_game() -> None:
    acc = recommend(CAT, custom_acc_wheel(), "acc", "pc", "advanced")
    got = summary(acc)
    assert got == golden("acc_pc_custom_advanced", got)
    keys = {a.assignment.key: a for a in acc.assignments}
    assert {keys["tc.inc"].assignment.control_id, keys["brake_bias.inc"].assignment.control_id} == {"enc_l", "enc_r"}
    assert acc.pitwall_ptt["path"] == "screen"
    other = recommend(
        CAT,
        custom_acc_wheel(),
        "other",
        "pc",
        "advanced",
        other_functions=["brake_bias", "tc", "pit_limiter", "lights", "ptt_pitwall"],
        game_name="Rally Sim",
    )
    got_o = summary(other)
    assert got_o == golden("other_pc_custom_advanced", got_o)
    assert other.pitwall_ptt["path"] == "screen" and "Rally Sim" in other.pitwall_ptt["text"]
    assert all(a.evidence is None for a in other.assignments)  # nothing researched for that game
    assert all(a.assignment.function != PTT_FUNCTION for a in other.assignments)


def test_the_owners_f1_layout() -> None:
    """Spec 3, worked through: F1 25 on PS5 with the GT DD Pro wheel, Advanced."""
    rec = _rec("f1_ps5_gt_dd_pro_advanced")
    by_key = {a.assignment.key: a for a in rec.assignments}
    on = {a.assignment.function for a in rec.assignments}
    assert {"ptt_pitwall", "drs_aero", "overtake", "brake_bias", "ers_mode", "pit_limiter"} <= on
    assert by_key["pit_limiter.press"].assignment.control_id == by_key["drs_aero.press"].assignment.control_id
    assert "F1 25 does this by default" in by_key["pit_limiter.press"].reason
    assert {u["function"] for u in rec.unplaced} >= {"diff", "engine_map"}
    assert all("Use the MFD." in u["text"] for u in rec.unplaced if u["function"] in ("diff", "engine_map"))
    face = {"face_triangle", "face_square", "face_circle", "face_cross", "tab_l2", "tab_r2", "tab_l3", "tab_r3"}
    used = {a.assignment.control_id for a in rec.assignments if a.assignment.function != "mfd"}
    assert used <= face  # the four coloured sticks are GT7's (community): not used in F1 25
    assert any("Green-ring stick" in n for n in rec.notes)
    reserved = {r["control_id"]: r["as"] for r in rec.reserved}
    assert reserved["ps"] == reserved["hub_left"] == reserved["hub_right"] == "system"
    assert reserved["paddle_left"] == "gear_down" and reserved["paddle_right"] == "gear_up"
    assert {a.assignment.control_id for a in rec.assignments if a.assignment.function == "mfd"} == {"menu_stick"}
    ptt = by_key["ptt_pitwall.hold"]
    assert ptt.assignment.udp_action == 1 and ptt.native == "UDP Action 1" and ptt.menu_group == "UDP Custom Actions"
    assert rec.pitwall_ptt["path"] == "udp_action" and rec.pitwall_ptt["control_id"] == ptt.assignment.control_id
    preset_warning = CAT.games["f1_25"].preset_warning
    assert all(preset_warning in a.warnings for a in rec.assignments)
    assert {x["function"] for x in rec.not_on_wheel} == {"tc", "abs", "wing", "ride_height"}
    assert {x["function"] for x in rec.not_in_game} == {"stability", "lights"}
    assert all(
        a.evidence == "A" for a in rec.assignments if a.assignment.function != "mfd" or a.assignment.slot != "push"
    )


def test_mclaren_encoders_get_brake_bias_and_ers_on_pc() -> None:
    rec = _rec("f1_pc_mclaren_advanced")
    ctl = {a.assignment.key: (a.assignment.control_id, a.assignment.slot) for a in rec.assignments}
    assert {ctl["brake_bias.inc"][0], ctl["ers_mode.inc"][0]} == {"enc11", "enc12"}
    assert ctl["brake_bias.inc"][1] == "cw" and ctl["brake_bias.dec"][1] == "ccw"


def test_mclaren_on_xbox_uses_one_folded_encoder_and_no_rotary_switch() -> None:
    rec = _rec("f1_xbox_mclaren_advanced")
    used = {a.assignment.control_id for a in rec.assignments}
    assert not {"mps18", "mps19"} & used  # they send nothing on Xbox
    assert len({"enc11", "enc12"} & used) == 1  # both send LT/RT: one per fold group
    folded = [a for a in rec.assignments if a.assignment.control_id in ("enc11", "enc12")]
    assert all(any("can't tell them apart" in w for w in a.warnings) for a in folded)


def test_gt7_fixed_sticks_screen_ptt_and_pause_menu_assists() -> None:
    rec = _rec("gt7_ps5_gt_dd_pro_advanced")
    fixed = {
        a.assignment.function: a.assignment.control_id for a in rec.assignments if a.assignment.origin == "game_fixed"
    }
    assert fixed == {"tc": "stick_blue", "brake_bias": "stick_red", "engine_map": "stick_green", "diff": "stick_yellow"}
    assert all(a.evidence == "U" for a in rec.assignments if a.assignment.origin == "game_fixed")
    assert rec.pitwall_ptt["path"] == "screen" and "iPad" in rec.pitwall_ptt["text"]
    nw = {x["function"]: x for x in rec.not_on_wheel}
    assert nw["stability"]["why"] == "pause_menu" and "ASM" in nw["stability"]["text"]
    assert nw["abs"]["why"] == "pause_menu"
    assert "pit_limiter" in {x["function"] for x in rec.not_in_game}


def test_kept_push_to_talk_and_kept_controls() -> None:
    """ "I already have this on a button": the owner's UDP Action 1 button is kept as is."""
    kept = [
        Assignment("ptt_pitwall.hold", "ptt_pitwall", "hold", "face_cross", "press", 1, "kept"),
        Assignment("drs_aero.press", "drs_aero", "press", "tab_r2", "press", None, "kept"),
    ]
    rec = recommend(CAT, tmpl("fanatec_gt_dd_pro_wheel"), "f1_25", "ps5", "advanced", kept)
    by_key = {a.assignment.key: a.assignment for a in rec.assignments}
    assert by_key["ptt_pitwall.hold"].control_id == "face_cross" and by_key["ptt_pitwall.hold"].origin == "kept"
    assert by_key["drs_aero.press"].control_id == "tab_r2" and by_key["drs_aero.press"].origin == "kept"
    others = [a for a in rec.assignments if a.assignment.origin == "recommended"]
    assert all(
        a.assignment.control_id not in ("face_cross", "tab_r2") or a.assignment.function == "pit_limiter"
        for a in others
    )
    kept3 = [Assignment("ptt_pitwall.hold", "ptt_pitwall", "hold", None, None, 3, "kept")]
    rec3 = recommend(CAT, tmpl("fanatec_gt_dd_pro_wheel"), "f1_25", "ps5", "advanced", kept3)
    assert rec3.pitwall_ptt["udp_action"] == 3 and rec3.pitwall_ptt["control_id"] is None
    assert (
        recommend(CAT, tmpl("fanatec_gt_dd_pro_wheel"), "f1_25", "ps5", "advanced", udp_action=5).pitwall_ptt[
            "udp_action"
        ]
        == 5
    )


# ---------------------------------------------------------------------------------------------- invariants
def _all_cases() -> list[tuple[str, str, str, str]]:
    out = []
    for tid, gid, preset in itertools.product(CAT.templates, CAT.games, ("beginner", "advanced")):
        for platform in CAT.games[gid].platforms:
            out.append((tid, gid, platform, preset))
    return out


ALL = _all_cases()


def test_invariants_for_every_template_game_platform_and_preset() -> None:
    assert len(ALL) > 500
    for tid, gid, platform, preset in ALL:
        wheel = tmpl(tid)
        rec = recommend(CAT, wheel, gid, platform, preset)
        assert summary(rec) == summary(recommend(CAT, wheel, gid, platform, preset)), (tid, gid, platform, preset)
        game = CAT.games[gid]
        sp = signal_platform(platform)
        keys = [a.assignment.key for a in rec.assignments]
        assert len(keys) == len(set(keys)), (tid, gid)
        for a in rec.assignments:
            row = game.functions.get(a.assignment.function)
            if a.assignment.function != PTT_FUNCTION:
                assert row is not None
                assert row.in_race not in ("no", "pause_menu") and row.binding not in ("menu", "none"), (gid, a)
            assert 0 < len(a.reason) <= MAX_REASON, a.reason
            assert "validat" not in a.reason.lower()
            c = wheel.control(a.assignment.control_id)
            if a.assignment.function == PTT_FUNCTION and c is not None:
                assert game.button_path == "f1_butn"
                assert c.kind == "button" and a.assignment.slot == "press", (tid, a)
                ref = next(s for s in expand_slots(wheel, sp, set()) if s.key == (c.id, "press"))
                assert not ref.folded and ref.kind != "none"
            if c is not None:
                assert c.kind not in (
                    "shift_paddle",
                    "device_menu",
                    "mode_selector",
                    "virtual_layer",
                    "analogue_paddle",
                )
        if game.button_path != "f1_butn":
            assert rec.pitwall_ptt["path"] == "screen"
            assert all(a.assignment.function != PTT_FUNCTION for a in rec.assignments)
        shared = [a for a in rec.assignments if a.assignment.function == "pit_limiter"]
        drs = [a for a in rec.assignments if a.assignment.function == "drs_aero"]
        if shared and drs and shared[0].assignment.control_id == drs[0].assignment.control_id:
            used = {(a.assignment.control_id, a.assignment.slot) for a in rec.assignments}
            reserved = {r["control_id"] for r in rec.reserved}
            slots = expand_slots(wheel, sp, reserved)
            used_folds = {s.fold_key for s in slots if s.key in used and s.fold_key is not None}
            free = [
                s
                for s in slots
                if s.control.kind == "button"
                and s.key not in used
                and s.kind != "game_specific"
                and (s.fold_key is None or s.fold_key not in used_folds)
            ]
            assert not free, (tid, gid, platform, preset, [s.key for s in free])


def test_an_encoder_out_of_thumb_reach_is_not_said_to_be_under_the_thumb() -> None:
    from pitwall.controls.model import parse_wheel

    def enc(cid: str, zone: str, order: int) -> dict[str, object]:
        return {"id": cid, "kind": "encoder", "label": cid, "zone": zone, "order": order}

    wheel = parse_wheel(
        {
            "id": "w_0000b0c5",
            "rev": 1,
            "name": "Rim and box",
            "shape": "round",
            "platforms": ["pc"],
            "parts": [{"id": "rim", "kind": "rim", "name": "Rim"}, {"id": "box", "kind": "button_box", "name": "Box"}],
            "controls": [enc("thumb_enc", "left_thumb", 0), enc("box_enc", "box", 1)],
        }
    )
    rec = recommend(CAT, wheel, "acc", "pc", "advanced")
    reasons = {a.assignment.control_id: a.reason for a in rec.assignments if a.assignment.slot == "cw"}
    assert "under your thumb" in reasons["thumb_enc"]
    assert "under your thumb" not in reasons["box_enc"] and "turning one encoder" in reasons["box_enc"]
