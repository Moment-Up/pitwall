"""Setup › Controls push-to-talk: which UDP Actions the radio listens to (the seated driver's F1 25 layout, else the
household's, with the deploy setting kept as a fallback) and the follower that hands changes to the hub."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pitwall.controls import model as M
from pitwall.controls.ptt import PttFollower, effective_ptt, ptt_text, setting_action
from pitwall.settings_store import SettingsStore
from tests.unit.controls_support import tmpl


def state_with(
    owner: str | int, udp: int, platform: str = "ps5", control: str | None = "face_cross"
) -> M.ControlsState:
    w = M.parse_wheel({**tmpl("fanatec_gt_dd_pro_wheel").to_dict(), "id": "w_00000001", "rev": 1})
    lay = M.Layout(
        "l_00000001",
        1,
        "f1_25",
        None,
        platform,
        "w_00000001",
        owner,
        "advanced",
        None,
        (M.Assignment("ptt_pitwall.hold", "ptt_pitwall", "hold", control, "press" if control else None, udp, "kept"),),
    )
    return M.ControlsState(wheels=(w,), layouts=(lay,)).with_owner_choice(lay)


def test_setting_only() -> None:
    assert setting_action("udp_action_4") == 4 and setting_action("bogus") == 1 and setting_action(None) == 1
    got = effective_ptt(M.ControlsState(), "udp_action_1", None, "ps5")
    assert got == {"udp_actions": [1], "from": "default", "layout_id": None, "label": None, "fallback_kept": True}
    assert effective_ptt(M.ControlsState(), "udp_action_5", None, "ps5")["from"] == "setting"


def test_layout_first_and_the_setting_kept_as_fallback() -> None:
    got = effective_ptt(state_with("household", 3), "udp_action_1", 2, "ps5")
    assert got["udp_actions"] == [3, 1] and got["from"] == "layout" and got["label"] == "Cross"
    assert got["fallback_kept"] and got["layout_id"] == "l_00000001"
    same = effective_ptt(state_with("household", 1), "udp_action_1", 2, "ps5")
    assert same["udp_actions"] == [1] and same["from"] == "layout"
    assert ptt_text(got) == "UDP Action 3 or 1 (Cross)"


def test_driver_layout_beats_household_and_platforms() -> None:
    st = state_with(2, 4)
    assert effective_ptt(st, "udp_action_1", 2, "ps5")["udp_actions"] == [4, 1]
    assert effective_ptt(st, "udp_action_1", 3, "ps5")["udp_actions"] == [1]  # another driver: no layout
    assert effective_ptt(st, "udp_action_1", 2, "xbox")["udp_actions"] == [1]  # another platform
    assert effective_ptt(st, "udp_action_1", 2, None)["udp_actions"] == [4, 1]  # platform unknown: any F1 layout
    no_ctl = effective_ptt(state_with("household", 6, control=None), "udp_action_1", None, "ps5")
    assert no_ctl["udp_actions"] == [6, 1] and no_ctl["label"] is None


def test_follower_recomputes_on_store_changes(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    seen: list[tuple[list[int], Any]] = []
    seat = {"id": 2}
    f = PttFollower(store, "udp_action_1", lambda: seat["id"], lambda: "ps5")
    store.subscribe("controls", f.recompute)
    f.attach(lambda acts, label: seen.append((acts, label)))
    assert seen == [([1], None)]
    M.save_state(store, state_with(2, 3))
    assert seen[-1] == ([3, 1], "Cross")
    f.recompute()
    assert len(seen) == 2  # unchanged: not sent again
    seat["id"] = 5
    f.recompute()
    assert seen[-1] == ([1], None)
    store.replace("controls", {"schema": 1, "wheels": "broken"})  # a bad section never takes PTT with it
    assert f.current()["udp_actions"] == [1]
