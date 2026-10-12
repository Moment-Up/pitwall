"""Setup › Controls catalogue: the research copies are verbatim, the overlay covers every research row and validates
(sources resolve, presets assignable, kinds/zones/slots valid), and the words never say "validated"."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from pitwall.controls.catalog import (
    GAMES_PATH,
    OVERLAY_PATH,
    WHEELS_PATH,
    CatalogError,
    load_catalog,
    parse_catalog,
    weakest,
)
from pitwall.controls.model import KIND_SLOTS, ZONE_REACH, valid_slot

REPO = Path(__file__).resolve().parents[2]
CAT = load_catalog()


def docs() -> tuple[Any, Any, Any]:
    return tuple(json.loads(p.read_text(encoding="utf-8")) for p in (GAMES_PATH, WHEELS_PATH, OVERLAY_PATH))  # type: ignore[return-value]


def test_packaged_research_is_the_verbatim_research() -> None:
    # Pitwall never edits the research files: a new revision is copied in whole (docs/research is the source).
    assert GAMES_PATH.read_bytes() == (REPO / "docs/research/controls-games.json").read_bytes()
    assert WHEELS_PATH.read_bytes() == (REPO / "docs/research/controls-wheels.json").read_bytes()


def test_catalog_is_complete() -> None:
    games, wheels, _ov = docs()
    assert len(CAT.functions) == 30 and len(CAT.games) == 11 and len(CAT.templates) == 24
    rows = sum(len(g["controls"]) for g in games["games"])
    assert rows == 142 == sum(len(g.functions) for g in CAT.games.values())
    assert [t["id"] for t in wheels["templates"]] == list(CAT.templates)
    assert {r[0] for r in CAT.reserved} == {"gear_up", "gear_down", "clutch", "system", "wheel_menu", "mode_switch"}
    assert set(CAT.kinds) == set(KIND_SLOTS) and {z[0] for z in CAT.zones} == set(ZONE_REACH)
    assert CAT.games["f1_25"].telemetry_keys == ("f1_25", "f1_25_2026")
    assert CAT.game_for_key("f1_25_2026") is CAT.games["f1_25"] and CAT.game_for_key("f1_24") is None
    assert [g.id for g in CAT.games.values() if g.button_path == "f1_butn"] == ["f1_25"]


def test_every_source_key_resolves_and_community_is_labelled() -> None:
    for g in CAT.games.values():
        for row in g.functions.values():
            assert all(s in CAT.sources for s in row.source_ids), (g.id, row.function)
    for t in CAT.templates.values():
        assert all(s in CAT.sources for s in t.source_ids)
        for c in t.controls:
            for sig in c.signals.values():
                assert all(s in CAT.sources for s in sig.source_ids)
    assert CAT.sources["fan_forum_gt7_extra"].community and CAT.sources["COMM-FAN-GTSTICKS"].community
    assert not CAT.sources["ea26_wheel_ps"].community and not CAT.sources["FAN-MCL"].community


def test_presets_hold_only_what_a_game_allows_mid_race() -> None:
    for g in CAT.games.values():
        for level, fns in g.presets.items():
            for fn in fns:
                row = g.functions[fn]
                assert row.in_race not in ("no", "pause_menu") and row.binding not in ("menu", "none"), (
                    g.id,
                    level,
                    fn,
                )


def test_templates_use_valid_kinds_zones_and_slots() -> None:
    for t in CAT.templates.values():
        ids = [c.id for c in t.controls]
        assert len(ids) == len(set(ids))
        for c in t.controls:
            assert c.kind in KIND_SLOTS and c.zone in ZONE_REACH and len(c.label) <= 32
            for sig in c.signals.values():
                for slot in sig.per_slot:
                    assert valid_slot(c.kind, slot, c.positions), (t.id, c.id, slot)
        assert t.completeness in ("full", "controls", "counts")
        if t.completeness == "counts":
            assert all(c.zone in ("unplaced", "back_left", "back_right") for c in t.controls)
    gt = CAT.templates["fanatec_gt_dd_pro_wheel"]
    assert "xbox" not in gt.signal_platforms
    hub = next(c for c in gt.controls if c.id == "hub_left")
    assert hub.signals["ps"].kind == "unknown" and "probably Create" in hub.note  # a guess stays a note


def test_research_evidence_maps_to_letters() -> None:
    f1 = CAT.games["f1_25"].functions
    assert f1["brake_bias"].evidence == "V"  # official
    assert CAT.games["gt7"].functions["tc"].evidence == "A"  # official+community
    assert CAT.games["ac"].functions["tc"].evidence == "U"  # community
    assert weakest("V", "A") == "A" and weakest("A", "U") == "U" and weakest("V", None) is None
    assert weakest("seen", "V") == "V" and weakest("H", "A") == "H"
    labels = set(CAT.evidence_labels.values())
    assert labels == {"Official", "Inferred", "Community", "Pitwall's suggestion", "Your entry", "Seen by Pitwall"}


def test_menu_paths_and_evidence() -> None:
    f1 = CAT.games["f1_25"].menu
    # inferred from EA's controls hub (official); the screen names on the console are not checked
    assert f1.where == "Controls, then the entry for your wheel" and f1.evidence == "A" and "not checked" in f1.note
    assert f1.groups == ("Control Scheme", "MFD Shortcuts", "UDP Custom Actions")
    assert CAT.games["gt7"].menu.evidence == "A"
    for gid in ("ac", "acc", "iracing", "lmu", "rf2", "ams2", "r3e", "ac_evo", "forza_motorsport"):
        m = CAT.games[gid].menu
        assert m.evidence is None and m.note


def test_api_shape_matches_the_contract() -> None:
    api = CAT.to_api()
    assert set(api) == {
        "version",
        "status",
        "functions",
        "reserved",
        "kinds",
        "zones",
        "games",
        "other_game",
        "templates",
        "not_possible",
        "evidence_labels",
        "sources",
        "diagram",
    }
    assert set(api["functions"][0]) == {"id", "label", "short", "group", "shape", "freq", "synonyms"}
    g = api["games"][0]
    assert set(g) == {
        "id",
        "label",
        "telemetry_keys",
        "platforms",
        "button_path",
        "menu",
        "research_depth",
        "functions",
        "presets",
        "platform_labels",
    }
    forza = CAT.games["forza_motorsport"]
    assert forza.label_on("ps5") == "Forza Horizon (PS5)" and forza.label_on("xbox") == forza.label
    assert set(g["functions"][0]) == {
        "function",
        "in_race",
        "binding",
        "conditions",
        "actions",
        "native_name",
        "menu_group",
        "shares_with",
        "pitwall_sees",
        "evidence",
        "source_ids",
        "platform_note",
        "native_found",
    }
    assert set(api["templates"][0]) == {
        "id",
        "brand",
        "name",
        "type",
        "platforms",
        "completeness",
        "shape",
        "display_name",
        "signal_platforms",
        "controls_total",
        "controls_placed",
    }
    names = {t["id"]: t["display_name"] for t in api["templates"]}
    assert names["thrustmaster_t248"] == "T248 / T248X" and not any("[" in n or "not read" in n for n in names.values())
    assert set(api["kinds"]["encoder"]) == {"label", "slots", "pairs"}
    assert set(api["diagram"]["shapes"]) == {"round", "d", "formula", "box"}
    text = json.dumps({k: v for k, v in api.items() if k != "sources"})
    assert "validated" not in text.replace("nothing here is validated", "")


def test_diagram_zones_fit_and_never_overlap() -> None:
    """The dashboard SVG and the printable card stack markers inside these boxes, so they must not overlap; a button
    box on its own (shape "box") has its box zone as the body, big enough for a large box."""
    vw, vh = CAT.diagram["viewbox"]
    for shape, sd in CAT.diagram["shapes"].items():
        boxes = sd["zones"]
        assert set(boxes) == set(ZONE_REACH), shape
        for z, (x, y, w, h) in boxes.items():
            assert x >= 0 and y >= 0 and x + w <= vw and y + h <= vh, (shape, z)
        items = list(boxes.items())
        for i, (za, (ax, ay, aw, ah)) in enumerate(items):
            for zb, (bx, by, bw, bh) in items[i + 1 :]:
                assert not (ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah), (shape, za, zb)
    box = CAT.diagram["shapes"]["box"]["zones"]
    assert max(box, key=lambda z: box[z][2] * box[z][3]) == "box"


def _broken(mutate: Any) -> str:
    g, w, ov = (copy.deepcopy(x) for x in docs())
    mutate(g, w, ov)
    with pytest.raises(CatalogError) as e:
        parse_catalog(g, w, ov)
    return str(e.value)


def test_the_loader_names_the_first_problem() -> None:
    def preset(_g: Any, _w: Any, ov: Any) -> None:
        ov["games"][1]["presets"]["beginner"].append("stability")  # GT7 ASM: pause menu only

    assert "not assignable mid-race" in _broken(preset)

    def row(_g: Any, _w: Any, ov: Any) -> None:
        del ov["games"][0]["functions"]["brake_bias"]

    assert "research-only ['brake_bias']" in _broken(row)

    def source(g: Any, _w: Any, _ov: Any) -> None:
        g["games"][0]["controls"][0]["sources"].append("nowhere")

    assert "unknown source 'nowhere'" in _broken(source)

    def zone(_g: Any, _w: Any, ov: Any) -> None:
        ov["templates"][0]["controls"][0]["zone"] = "roof"

    assert "zone" in _broken(zone)

    def slot(_g: Any, _w: Any, ov: Any) -> None:
        ov["templates"][1]["controls"][2]["signals"]["pc"]["per_slot"] = {"left": "1"}

    assert "not a slot" in _broken(slot)

    def label(_g: Any, _w: Any, ov: Any) -> None:
        ov["evidence_labels"]["seen"] = "Validated"

    assert "never 'validated'" in _broken(label)
