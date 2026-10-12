"""Setup › Controls stored data (SettingsStore section "controls"): lenient parsing (one bad item never hides the
rest), strict parsing for API input, caps, the owner's choices, and orphaned drivers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pitwall.controls import model as M
from pitwall.settings_store import SettingsStore
from tests.unit.controls_support import tmpl


def wheel_dict(wid: str = "w_00000001", **kw: Any) -> dict[str, Any]:
    d = tmpl("fanatec_gt_dd_pro_wheel").to_dict()
    d.update({"id": wid, "rev": 1, **kw})
    return d


def layout_dict(lid: str = "l_00000001", wid: str = "w_00000001", **kw: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": lid,
        "rev": 1,
        "game": "f1_25",
        "game_name": None,
        "platform": "ps5",
        "wheel_id": wid,
        "owner": "household",
        "preset": "advanced",
        "other_functions": None,
        "assignments": [
            {
                "key": "ptt_pitwall.hold",
                "function": "ptt_pitwall",
                "action": "hold",
                "control_id": "face_cross",
                "slot": "press",
                "udp_action": 3,
                "origin": "kept",
                "check": None,
            },
        ],
    }
    d.update(kw)
    return d


def test_missing_section_means_defaults_and_nothing_is_written(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    state = M.load_state(store)
    assert state == M.ControlsState() and not (tmp_path / "settings.json").exists()


def test_round_trip_through_the_store(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    state = M.ControlsState.from_stored({"schema": 1, "wheels": [wheel_dict()], "layouts": [layout_dict()]})
    lay = state.layouts[0]
    state = state.with_owner_choice(lay)
    saved = M.save_state(store, state)
    again = M.load_state(store)
    assert again == saved and again.household.layouts == {"f1_25:ps5": "l_00000001"}
    assert store.get("controls")["schema"] == 1
    assert again.layout_for(7, "f1_25", "ps5") == lay  # no driver layout: the household's
    assert again.layout_for(7, "gt7", "ps5") is None


def test_lenient_parse_skips_only_the_bad_items(caplog: pytest.LogCaptureFixture) -> None:
    bad_control = wheel_dict("w_00000002")
    bad_control["controls"].append({"id": "x", "kind": "laser", "label": "Laser"})
    raw = {
        "schema": 1,
        "wheels": [wheel_dict(), {"id": "nope"}, bad_control, "junk"],
        "layouts": [
            layout_dict(),
            layout_dict("l_00000002", wid="w_0000dead"),  # its wheel is gone
            {**layout_dict("l_00000003"), "assignments": [{"function": "BAD!"}, *layout_dict()["assignments"]]},
        ],
        "household": {"wheel_id": "w_00000001", "preset": "sideways", "layouts": {"f1_25:ps5": "l_00000001"}},
        "drivers": {"2": {"wheel_id": "w_00000002", "layouts": {"gt7:ps5": "zzz"}}, "x": {}},
    }
    state = M.ControlsState.from_stored(raw)
    assert [w.id for w in state.wheels] == ["w_00000001", "w_00000002"]
    assert "x" not in {c.id for c in state.wheels[1].controls}  # the bad control only
    assert [x.id for x in state.layouts] == ["l_00000001", "l_00000003"]
    assert len(state.layouts[1].assignments) == 1
    assert state.household.preset is None and state.household.wheel_id == "w_00000001"
    assert state.drivers["2"].layouts == {} and "x" not in state.drivers
    assert "skipping" in caplog.text


def test_orphaned_drivers_are_kept_not_deleted() -> None:
    raw = {
        "schema": 1,
        "wheels": [wheel_dict()],
        "layouts": [layout_dict(owner=9)],
        "drivers": {"9": {"wheel_id": "w_00000001", "layouts": {"f1_25:ps5": "l_00000001"}}},
    }
    state = M.ControlsState.from_stored(raw)
    assert state.layouts[0].owner == 9 and state.driver(9).wheel_id == "w_00000001"
    assert M.ControlsState.from_stored(state.to_section()) == state  # nothing is auto-deleted


def test_strict_parse_reports_plain_english() -> None:
    with pytest.raises(M.ControlsValidationError, match="label: is longer than 32"):
        M.parse_wheel(wheel_dict(controls=[{"id": "a", "kind": "button", "label": "x" * 33}]))
    with pytest.raises(M.ControlsValidationError, match="two controls have the id 'a'"):
        M.parse_wheel(wheel_dict(controls=[{"id": "a", "kind": "button", "label": "A"}] * 2))
    with pytest.raises(M.ControlsValidationError, match=f"at most {M.MAX_CONTROLS} controls"):
        M.parse_wheel(wheel_dict(controls=[{"id": f"c{i}", "kind": "button", "label": "B"} for i in range(97)]))
    with pytest.raises(M.ControlsValidationError, match="name the game"):
        M.parse_layout(layout_dict(game="other"))
    with pytest.raises(M.ControlsValidationError, match="assigned twice"):
        M.parse_layout(layout_dict(assignments=layout_dict()["assignments"] * 2))
    with pytest.raises(M.ControlsValidationError, match="whole number from 1 to 12"):
        M.parse_layout(layout_dict(assignments=[{**layout_dict()["assignments"][0], "udp_action": 13}]))
    lay = M.parse_layout(layout_dict(assignments=[{**layout_dict()["assignments"][0], "control_id": "nope"}]))
    with pytest.raises(M.ControlsValidationError, match="no control 'nope'"):
        M.check_layout_against_wheel(lay, M.parse_wheel(wheel_dict()))


def test_caps() -> None:
    state = M.ControlsState()
    for i in range(M.MAX_WHEELS):
        state = state.with_wheel(M.parse_wheel(wheel_dict(f"w_{i:08x}")))
    with pytest.raises(M.ControlsValidationError, match="at most 12 wheels"):
        state.with_wheel(M.parse_wheel(wheel_dict("w_ffffffff")))
    assert len(state.with_wheel(M.parse_wheel(wheel_dict("w_00000000", name="Renamed"))).wheels) == M.MAX_WHEELS


def test_signals_per_slot_and_kinds() -> None:
    sig = M.parse_signal(
        {
            "kind": "game_specific",
            "value": "GSB 2/3",
            "per_slot": {"up": "pad:dpad_up", "push": "GSB 1", "cw": "none:"},
        },
        "s",
    )
    assert sig.slot("up") == ("pad", "dpad_up") and sig.slot("push") == ("game_specific", "GSB 1")
    assert sig.slot("cw") == ("none", None) and sig.slot("ccw") == ("game_specific", "GSB 2/3")
    assert M.signal_platform("ps4") == "ps" and M.signal_platform("pc") == "pc" and M.signal_platform(None) is None
    enc = M.WheelControl("e", "rim", "encoder", "Enc", "left_thumb")
    assert enc.slots() == ("cw", "ccw") and M.WheelControl("e", "rim", "encoder", "E", "box", push=True).slots() == (
        "cw",
        "ccw",
        "push",
    )
    mps = M.WheelControl("m", "rim", "multi_position", "M", "centre", positions=12, mps_mode="pulse")
    assert mps.slots()[0] == "pos_1" and len(mps.slots()) == 12 and mps.effective_reach == "stretch"
    assert M.valid_slot("multi_position", "pos_12", 12) and not M.valid_slot("multi_position", "pos_13", 12)


def test_deleting_a_layout_clears_every_choice_pointing_at_it() -> None:
    state = M.ControlsState.from_stored({"schema": 1, "wheels": [wheel_dict()], "layouts": [layout_dict(owner=2)]})
    lay = state.layouts[0]
    state = state.with_owner_choice(lay).with_owner_choice(M.parse_layout(layout_dict()))
    assert state.driver(2).layouts == {"f1_25:ps5": "l_00000001"}
    gone = state.without_layout("l_00000001")
    assert gone.layouts == () and gone.driver(2).layouts == {} and gone.household.layouts == {}
    assert state.without_wheel("w_00000001").household.wheel_id is None
