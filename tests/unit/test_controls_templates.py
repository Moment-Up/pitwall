"""Setup › Controls templates: research templates expanded to wheel drafts, and the wheel a page opens on."""

from __future__ import annotations

from collections import Counter

import pytest

from pitwall.controls import model as M
from pitwall.controls.templates import default_wheel, resolve_wheel, template_wheel, virtual_wheel_id
from tests.unit.controls_support import CAT, tmpl


def test_gt_dd_pro_expands_to_its_researched_controls() -> None:
    """11 buttons + the menu stick + 4 game-specific coloured sticks + 2 paddles + the Tuning button; no Xbox."""
    w = tmpl("fanatec_gt_dd_pro_wheel")
    kinds = Counter(c.kind for c in w.controls)
    assert kinds == {"button": 11, "dpad_hat": 5, "shift_paddle": 2, "device_menu": 1}
    sticks = [c for c in w.controls if c.id.startswith("stick_")]
    assert len(sticks) == 4 and all(c.signals["ps"].kind == "game_specific" for c in sticks)
    assert all(c.signals["ps"].evidence == "U" for c in sticks)  # community
    menu = w.control("menu_stick")
    assert menu is not None and menu.signals["ps"].kind == "pad" and menu.signals["ps"].evidence == "A"
    assert w.platforms == ("ps", "pc") and all("xbox" not in c.signals for c in w.controls)
    assert w.template == "fanatec_gt_dd_pro_wheel" and w.template_version == CAT.version and w.rev == 0


def test_mclaren_on_xbox_rotary_switches_send_nothing_and_encoders_fold() -> None:
    w = tmpl("fanatec_csl_elite_mclaren_gt3_v2")
    for cid in ("mps18", "mps19"):
        c = w.control(cid)
        assert c is not None and c.signals["xbox"].kind == "none"
    for cid in ("enc11", "enc12"):
        c = w.control(cid)
        assert c is not None and c.signals["xbox"].kind == "folded" and c.signals["xbox"].value == "lt/rt"
        assert c.signals["ps"].kind == "game_specific"


def test_g923_ps_extra_buttons_are_game_specific() -> None:
    w = tmpl("logitech_g923_ps")
    for cid in ("l3", "r3", "plus", "minus"):
        c = w.control(cid)
        assert c is not None and c.signals["ps"].kind == "game_specific" and c.signals["ps"].evidence == "V"


@pytest.mark.parametrize("tid", ["moza_ks", "simagic_gt_neo", "cammus_c12", "simucube_tahko_gt21", "moza_es_esx"])
def test_counts_only_templates_come_out_unplaced(tid: str) -> None:
    t = CAT.templates[tid]
    assert t.completeness == "counts"
    w = tmpl(tid)
    movable = [c for c in w.controls if c.kind not in ("shift_paddle", "analogue_paddle")]
    assert movable and all(c.zone == "unplaced" for c in movable)
    assert all(s.kind in ("unknown", "none") for c in w.controls for s in c.signals.values())
    assert any("only says how many controls" in n for n in t.notes)


def test_every_template_expands_and_parses() -> None:
    for tid in CAT.templates:
        w = template_wheel(CAT, tid, wheel_id="w_12345678", now=1.0)
        assert M.parse_wheel(w.to_dict(), default_evidence="A") == w
    assert tmpl("custom").controls == ()


def test_default_wheel_order() -> None:
    wheel = M.parse_wheel({**tmpl("fanatec_csl_p1_v2").to_dict(), "id": "w_0000aaaa", "rev": 1})
    state = M.ControlsState(wheels=(wheel,))
    assert default_wheel(state, 1, "gt_dd_pro_bundled") == default_wheel(M.ControlsState(), 1, "gt_dd_pro_bundled")
    assert default_wheel(M.ControlsState(), 1, "gt_dd_pro_bundled").template == "fanatec_gt_dd_pro_wheel"
    assert default_wheel(M.ControlsState(), 1, "other").source == "none"
    hh = M.ControlsState(wheels=(wheel,), household=M.DriverControls(wheel_id="w_0000aaaa"))
    assert default_wheel(hh, 1, "gt_dd_pro_bundled").wheel_id == "w_0000aaaa"
    mine = M.ControlsState(wheels=(wheel,), drivers={"1": M.DriverControls(wheel_id="w_0000aaaa")})
    assert default_wheel(mine, 1, None).source == "driver" and default_wheel(mine, 2, None).source == "none"


def test_resolve_wheel() -> None:
    state = M.ControlsState()
    d = resolve_wheel(CAT, state, None, "logitech_g923_ps")
    assert d.id == virtual_wheel_id("logitech_g923_ps") and d.rev == 0
    assert resolve_wheel(CAT, state, "logitech_g923_ps", None) == d
    with pytest.raises(M.NotFound):
        resolve_wheel(CAT, state, "w_00000000", None)
    with pytest.raises(M.NotFound):
        resolve_wheel(CAT, state, None, None)
