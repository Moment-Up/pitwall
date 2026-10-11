"""Corner identity (layer L2): track-sheet schema, shipped sheets, mapping onto learned models, display text,
and the licence/provenance records of the vendored seed data."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import re
from collections.abc import Iterator, Sequence
from dataclasses import astuple, replace
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pytest

from pitwall import trackdata
from pitwall.adapters.f1.enums import TRACKS
from pitwall.analysis import track_identity as ti
from pitwall.analysis.track import IDENTITY_FIELDS, Corner, TrackModel
from pitwall.analysis.track_identity import (
    DEFAULT_MIN_TIER,
    EDGE_MARGIN_M,
    MAX_SECTOR_MISMATCH_M,
    TIER_SEEDED,
    TIER_VERIFIED,
    CornerText,
    IdentityMapping,
    SheetError,
    TrackSheet,
    apply_identity,
    corner_display,
    corner_texts,
    find_sheet,
    format_label,
    identify,
    load_sheets,
    map_identity,
    parse_sheet,
    parse_sheet_text,
    resolve_corner_ref,
    sector_mismatch_m,
    track_model_payload,
)
from pitwall.model.telemetry import TrackZones
from pitwall.trackdata import (
    PITS_N_GIGGLES_COMMIT,
    PITS_N_GIGGLES_SOURCE,
    pits_n_giggles_dir,
    pits_n_giggles_segment_documents,
)

ROOT = Path(__file__).resolve().parents[2]
EXCERPT = ROOT / "tests" / "fixtures" / "recorded" / "f1_25_2025_ps5_austria_race-excerpt.pwcap"
REVERSE = {39: 7, 40: 17, 41: 26}
# Sheets with verified turns (hand-reviewed against a real capture and an FIA map; the importer leaves them alone).
HAND_REVIEWED = {6, 7, 11, 13, 17, 31, 39, 40}


# ============================================================================================ helpers
def _corner(
    name: str, apex: float, direction: str | None = None, vmin: float = 100.0, entry: float | None = None
) -> Corner:
    return Corner(
        name=name,
        apex_m=apex,
        entry_m=apex - 60.0 if entry is None else entry,
        exit_m=apex + 60.0,
        seg_start_m=apex - 100.0,
        seg_end_m=apex + 100.0,
        direction=direction,
        ref_min_speed_kph=vmin,
    )


def _model(
    corners: Sequence[tuple[float, str | None]], length: float = 1000.0, track_id: str = "f1:99", game: str = "f1_25"
) -> TrackModel:
    """A learned-model stand-in: corners named T1..Tn in lap order, as ``build_track_model`` names them."""
    cs = [_corner(f"T{i + 1}", apex, d) for i, (apex, d) in enumerate(corners)]
    return TrackModel(game=game, track_id=track_id, track_name="test", length_m=length, corners=cs, version=3)


def _with(c: Corner, **kw: Any) -> Corner:
    return replace(c, **kw)


def _doc(**over: Any) -> dict[str, Any]:
    """A small valid sheet: T1 (right), T2 flat kink, T3-5 complex, T6 (left, verified) on a 1000 m lap."""
    doc: dict[str, Any] = {
        "schema_version": 1,
        "game_family": "f1",
        "games": ["f1_25"],
        "game_track_id": 99,
        "layout": "Test Ring",
        "lap_length_m": 1000,
        "official_turn_count": 6,
        "sources": ["test"],
        "turns": [
            {"numbers": [1], "names": [{"text": "Alpha", "kind": "traditional"}], "game_segment_m": [100, 200],
             "direction": "right", "voice_ok": True, "sources": ["test"]},
            {"numbers": [2], "game_segment_m": [250, 300], "direction": "left", "sources": ["test"]},
            {"numbers": [3, 4, 5], "names": [{"text": "Esses", "kind": "nickname"}], "game_segment_m": [400, 600],
             "sources": ["test"]},
            {"numbers": [6], "names": [{"text": "Omega", "kind": "sponsor"}], "game_segment_m": [700, 800],
             "direction": "left", "verified": True, "checked_against": ["test capture"], "sources": ["test"]},
        ],
    }  # fmt: skip
    doc.update(over)
    return doc


def _sheet(**over: Any) -> TrackSheet:
    return parse_sheet(_doc(**over), "test.toml")


def _verified_doc(**over: Any) -> dict[str, Any]:
    """``_doc`` with every turn verified (and voice_ok only where it was), to exercise the default min tier."""
    doc = _doc(**over)
    for t in doc["turns"]:
        t["verified"] = True
        t["checked_against"] = ["test capture"]
    return doc


def _map(model: TrackModel, sheet: TrackSheet | None = None, **kw: Any) -> IdentityMapping:
    """Map with every tier allowed: the mechanics tests below use the mostly seeded test sheet."""
    return map_identity(model, sheet or _sheet(), min_tier=TIER_SEEDED, **kw)


def _positions(m: TrackModel) -> list[tuple[Any, ...]]:
    return [(c.name, c.apex_m, c.entry_m, c.exit_m, c.seg_start_m, c.seg_end_m, c.direction) for c in m.corners]


def _git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _importer() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "import_track_segments", ROOT / "scripts" / "import_track_segments.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _zones(s2: float | None, s3: float | None, source: str | None = "f1_session@2025") -> TrackZones:
    return TrackZones(source=source, sector2_start_m=s2, sector3_start_m=s3)


# ============================================================================================ schema
def test_minimal_sheet_parses() -> None:
    s = _sheet()
    assert s.track_id == "f1:99" and not s.is_reverse
    assert [t.label for t in s.turns] == ["T1", "T2", "T3-5", "T6"]
    assert [t.tier for t in s.turns] == [TIER_SEEDED, TIER_SEEDED, TIER_SEEDED, TIER_VERIFIED]
    assert s.turns[0].display_name == "Alpha" and s.turns[1].display_name is None
    assert s.verified_formats == ()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d.update(extra=1), "unknown key"),
        (lambda d: d.pop("layout"), "missing key"),
        (lambda d: d.update(schema_version=2), "schema_version"),
        (lambda d: d.update(schema_version=True), "schema_version"),
        (lambda d: d.update(schema_version=[1]), "schema_version"),
        (lambda d: d.update(game_family="F1"), "game_family"),
        (lambda d: d.update(games=[]), "games"),
        (lambda d: d.update(lap_length_m=0), "lap_length_m"),
        (lambda d: d.update(official_turn_count=0), "official_turn_count"),
        (lambda d: d.update(sector_starts_m=[600, 300]), "sector_starts_m"),
        (lambda d: d.update(verified_formats=[]), "verified_formats"),
        (lambda d: d.update(verified_formats=["2025"]), "verified_formats"),
        (lambda d: d.update(verified_formats=[True]), "verified_formats"),
        (lambda d: d.update(turns=[]), "turns"),
        (lambda d: d["turns"][0].update(colour="red"), "unknown key"),
        (lambda d: d["turns"][0].pop("sources"), "missing key"),
        (lambda d: d["turns"][0].update(numbers=[7]), "outside 1..official_turn_count"),
        (lambda d: d["turns"][2].update(numbers=[3, 5]), "contiguous"),
        (lambda d: d["turns"][0].update(numbers=[True]), "integers"),
        (lambda d: d["turns"][0]["names"][0].update(kind="marketing"), "kind"),
        (lambda d: d["turns"][0]["names"][0].update(kind=["sponsor"]), "kind"),  # a list: SheetError, not TypeError
        (lambda d: d["turns"][0]["names"][0].update(text=" Alpha"), "whitespace"),
        (lambda d: d["turns"][0].update(direction="up"), "direction"),
        (lambda d: d["turns"][0].update(direction=["left"]), "direction"),
        (lambda d: d["turns"][0].update(direction={"x": 1}), "direction"),
        (lambda d: d["turns"][0].update(game_segment_m=[200, 100]), "start < end"),
        (lambda d: d["turns"][3].update(game_segment_m=[700, 1001]), "beyond lap_length_m"),
        (lambda d: d["turns"][1].update(game_segment_m=[150, 300]), "lap order without overlap"),
        (lambda d: d["turns"].reverse(), "lap order"),
        (lambda d: d["turns"][3].update(numbers=[2]), "must increase along the lap"),
        (lambda d: d["turns"][1].update(numbers=[]), "numbers or at least one name"),
        (lambda d: d["turns"][1].update(voice_ok=True), "no names to speak"),
        (lambda d: d["turns"][3].update(checked_against=[]), "requires checked_against"),
        (lambda d: d["turns"][3]["names"][0].update(kind="unclassified"), "classify every name"),
        (lambda d: d["turns"][0].update(label="T2a"), "does not match numbers"),
        (lambda d: d["turns"][0].update(label="T2"), "form T5a"),  # overrides are for lettered sub-turns only
        (lambda d: d["turns"][0].update(label="Turn 1"), "form T5a"),
        (lambda d: d["turns"][2].update(label="T3a"), "does not match numbers"),  # never on a complex
        (lambda d: d["turns"][0].update(voice_ok="yes"), "true/false"),
        (lambda d: d.update(reverse_of=5), "must be 0 for a reverse layout"),
        (lambda d: d.update(reverse_of=99, official_turn_count=0), "another layout"),
    ],
)
def test_invalid_sheets_are_rejected(mutate: Any, message: str) -> None:
    doc = _doc()
    mutate(doc)
    with pytest.raises(SheetError, match=message):
        parse_sheet(doc, "bad.toml")


def test_verified_formats_need_a_verified_turn() -> None:
    doc = _doc(verified_formats=[2025])
    doc["turns"][3]["verified"] = False
    with pytest.raises(SheetError, match="no turn is verified"):
        parse_sheet(doc)
    assert _sheet(verified_formats=[2026, 2025, 2025]).verified_formats == (2025, 2026)


def test_reverse_sheet_rejects_numbers_and_accepts_names_only() -> None:
    names_only = [
        {"names": [{"text": "Omega", "kind": "sponsor"}], "game_segment_m": [100, 200], "sources": ["test"]},
        {"names": [{"text": "Alpha", "kind": "traditional"}], "game_segment_m": [700, 800], "sources": ["test"]},
    ]
    s = _sheet(reverse_of=98, official_turn_count=0, turns=names_only)
    assert s.is_reverse and all(t.numbers == () and t.label is None for t in s.turns)
    with pytest.raises(SheetError, match="reverse layouts have no official numbering"):
        _sheet(reverse_of=98, official_turn_count=0, turns=[{**names_only[0], "numbers": [1]}])


def _lettered_doc(*turns: tuple[list[int], str | None, list[float]]) -> dict[str, Any]:
    out = []
    for numbers, label, seg in turns:
        t: dict[str, Any] = {"numbers": numbers, "game_segment_m": seg, "sources": ["test"]}
        if label:
            t["label"] = label
        out.append(t)
    return _doc(turns=out)


def test_lettered_sub_turns_follow_their_base_turn() -> None:
    """Madrid's FIA numbering (5, 5A, 6) fits the schema: a lettered sub-turn may repeat the base number."""
    ok = parse_sheet(_lettered_doc(([2], None, [100, 200]), ([2], "T2a", [200, 300]), ([3], None, [300, 400])))
    assert [t.label for t in ok.turns] == ["T2", "T2a", "T3"]
    assert [t.lettered for t in ok.turns] == [False, True, False]
    assert parse_sheet(_lettered_doc(([2], "T2a", [100, 200]), ([2], "T2b", [200, 300]))).turns[1].label == "T2b"
    for bad in (
        _lettered_doc(([2], None, [100, 200]), ([2], None, [200, 300])),  # same number twice
        _lettered_doc(([2], "T2a", [100, 200]), ([2], None, [200, 300])),  # base after its sub-turn
        _lettered_doc(([2], "T2a", [100, 200]), ([2], "T2a", [200, 300])),  # same sub-turn twice
        _lettered_doc(([2, 3], None, [100, 200]), ([2], "T2a", [200, 300])),  # sub-turn after a later number
    ):
        with pytest.raises(SheetError, match="must increase along the lap"):
            parse_sheet(bad)


def test_invalid_toml_text_is_a_sheet_error() -> None:
    with pytest.raises(SheetError, match="invalid TOML"):
        parse_sheet_text("schema_version = = 1", "broken.toml")


def test_format_label() -> None:
    assert format_label([]) is None
    assert format_label([3]) == "T3"
    assert format_label([10, 11, 12, 13]) == "T10-13"


# ============================================================================================ shipped sheets
def test_every_vendored_layout_has_a_valid_sheet() -> None:
    sheets = load_sheets("f1")
    png_ids = sorted(int(doc["circuit_number"]) for _, doc in pits_n_giggles_segment_documents())
    assert len(png_ids) == 28
    assert sorted(s.game_track_id for s in sheets) == png_ids
    for s in sheets:
        assert s.game_track_id in TRACKS, s.source
        assert s.games == ("f1_25",), s.source
        assert find_sheet("f1_25", s.track_id) is s


def test_turn_counts_and_numbering_are_sane() -> None:
    for s in load_sheets("f1"):
        numbers = [n for t in s.turns for n in t.numbers]
        if s.is_reverse:
            assert s.official_turn_count == 0 and numbers == [], s.source
            continue
        assert 8 <= s.official_turn_count <= 30, s.source
        plain = [n for t in s.turns if not t.lettered for n in t.numbers]
        assert plain == sorted(set(plain)), s.source  # each official number once, in lap order
        assert max(numbers) <= s.official_turn_count, s.source
        assert len({t.label for t in s.turns if t.label}) == sum(1 for t in s.turns if t.label), s.source
        for t in s.turns:
            assert t.segment_m[1] <= s.lap_length_m and t.segment_m[1] - t.segment_m[0] >= 20, s.source
        if s.sector_starts_m is not None:
            assert 0 < s.sector_starts_m[0] < s.sector_starts_m[1] < s.lap_length_m


def test_sheets_cite_the_current_pin() -> None:
    """Every Pits n' Giggles provenance tag in every sheet names the vendored commit (no stale pins)."""
    tag = re.compile(r"pits_n_giggles@([0-9a-f]+)")
    assert f"pits_n_giggles@{PITS_N_GIGGLES_COMMIT[:7]}" == PITS_N_GIGGLES_SOURCE
    for p in sorted((ROOT / "src" / "pitwall" / "trackdata" / "track_sheets" / "f1").glob("*.toml")):
        found = set(tag.findall(p.read_text(encoding="utf-8")))
        assert found == {PITS_N_GIGGLES_COMMIT[:7]}, (p.name, found)


def test_repin_fixed_the_upstream_numbering() -> None:
    """The five files changed by PnG release-v5.0.0 (research Action 1) are the ones pitwall ships."""
    mel = find_sheet("f1_25", "f1:0")
    assert mel is not None and mel.official_turn_count == 14
    assert next(t.label for t in mel.turns if t.display_name == "Ascari") == "T11"  # was T13 at 3490db9
    mtl = find_sheet("f1_25", "f1:6")
    assert mtl is not None and [n for t in mtl.turns for n in t.numbers] == list(range(1, 15))
    assert next(t.label for t in mtl.turns if t.display_name == "Wall of Champions") == "T13-14"  # was T12-13
    baku = find_sheet("f1_25", "f1:20")
    assert baku is not None and {13, 14} <= {n for t in baku.turns for n in t.numbers}


def test_reverse_layouts_carry_names_only() -> None:
    generic = re.compile(r"(?i)^(bocht|turn|curva|virage|kurve|corner)\s*\d")
    for rev_id, fwd_id in REVERSE.items():
        rev = find_sheet("f1_25", f"f1:{rev_id}")
        fwd = find_sheet("f1_25", f"f1:{fwd_id}")
        assert rev is not None and fwd is not None
        assert rev.reverse_of == fwd_id and rev.official_turn_count == 0
        assert all(t.numbers == () and t.label is None and t.names for t in rev.turns)
        rev_names = {n.text for t in rev.turns for n in t.names}
        fwd_names = {n.text for t in fwd.turns for n in t.names}
        shown = {n.text for t in rev.turns if t.verified for n in t.names}
        assert shown <= fwd_names  # a displayed reverse name is a verified forward name of the same corner
        if fwd_id == 17:  # Austria's PnG-era sponsor names were dropped from the forward sheet (stale or wrong turn);
            # the reverse keeps them only on seeded turns, which are never shown or voiced
            fwd_names |= {"Schlossgold", "Rauch", "Remus", "Würth Kurve", "Red Bull Mobile"}
        assert rev_names and rev_names <= fwd_names  # same physical corners
        assert not any(generic.match(n) for n in rev_names)


def test_seeded_sheets_never_voice_names() -> None:
    for s in load_sheets("f1"):
        for t in s.turns:
            if not t.verified:
                assert not t.voice_ok and all(n.kind == "unclassified" for n in t.names), s.source


def test_austria_sheet_is_hand_reviewed() -> None:
    s = find_sheet("f1_25", "f1:17")
    assert s is not None and s.official_turn_count == 10 and s.lap_length_m == 4323
    assert [t.numbers for t in s.turns] == [(n,) for n in range(1, 11)]
    assert all(t.verified and t.checked_against for t in s.turns)
    assert s.verified_formats == (2025,)  # evidence is a format-2025 capture only
    dirs = [t.direction for t in s.turns]
    assert dirs.count("right") == 7 and dirs.count("left") == 3  # FIA drawing and de.wikipedia: 7 right / 3 left
    assert [i + 1 for i, d in enumerate(dirs) if d == "left"] == [2, 6, 7]
    voiced = {t.label: t.display_name for t in s.turns if t.voice_ok}
    assert voiced == {"T1": "Niki Lauda Kurve", "T9": "Rindt Kurve"}
    # only the honorific names are displayed: the 2021-era sponsor names (Remus, Würth Kurve, Red Bull Mobile) are
    # no longer the circuit's names (its 2025 media kit and website), and the sponsor-name policy is open
    assert {t.label: t.display_name for t in s.turns if t.names} == voiced
    assert all("Rauch" in (t.notes or "") for t in s.turns if t.label in ("T4", "T6"))
    # the review kept PnG's windows: they must still equal the vendored seed
    png = next(doc for _, doc in pits_n_giggles_segment_documents() if doc["circuit_number"] == 17)
    png_windows = [(float(g["start_m"]), float(g["end_m"])) for g in png["segments"] if g["type"] != "straight"]
    assert [t.segment_m for t in s.turns] == png_windows


def test_unreviewed_sheets_match_the_importer_output() -> None:
    """Seeded sheets are exactly what the importer produces from the pinned data (no silent hand edits)."""
    imp = _importer()
    out_dir = ROOT / "src" / "pitwall" / "trackdata" / "track_sheets" / "f1"
    checked = 0
    reviewed: set[int] = set()
    for _, doc in pits_n_giggles_segment_documents():
        name, sheet = imp.convert(doc)
        path = out_dir / name
        assert path.exists(), name
        if imp.reviewed(path):
            reviewed.add(int(doc["circuit_number"]))
            continue
        assert path.read_text(encoding="utf-8") == imp.render(sheet), f"{name} drifted from the importer"
        checked += 1
    assert reviewed >= HAND_REVIEWED  # a hand-reviewed sheet never silently falls back to the seed
    assert checked + len(reviewed) == 28


def test_find_sheet_never_matches_synthetic_or_other_games() -> None:
    assert find_sheet("f1_25", "f1:17") is not None
    assert find_sheet("synthetic", "synthetic:coaching_demo") is None
    assert find_sheet("f1_25", "synthetic:17") is None
    assert find_sheet("f1_24", "f1:17") is None  # metres validated for F1 25 only
    assert find_sheet("f1_25", "f1:-1") is None
    assert find_sheet("f1_25", "f1:８") is None  # non-ASCII digits are not a track id
    assert find_sheet("f1_25", "f1:8") is None  # legacy Hockenheim: no sheet
    assert find_sheet("gt7", "gt7:17") is None
    assert find_sheet(None, "f1:17") is None and find_sheet("f1_25", None) is None


# ============================================================================================ mapping
def test_merged_complex_and_flat_kink() -> None:
    """Two minima in the T3-5 complex share its label; the flat T2 kink has no corner and is not invented."""
    sheet = _sheet()
    model = _model([(150, "right"), (450, "left"), (550, "right"), (750, "left")])
    mapping = _map(model, sheet)
    assert mapping.ok and mapping.scale == 1.0
    assert [(a.label, a.part, a.match) for a in mapping.assignments] == [
        ("T1", None, "inside"),
        ("T3-5", 1, "inside"),
        ("T3-5", 2, "inside"),
        ("T6", None, "inside"),
    ]
    assert [sheet.turns[i].label for i in mapping.absent_turns] == ["T2"]
    out = apply_identity(model, mapping)
    assert len(out.corners) == 4  # nothing added for the kink
    assert out.corners[1].official_numbers == [3, 4, 5] and out.corners[1].display_name == "Esses"
    assert [c.identity_tier for c in out.corners] == [TIER_SEEDED] * 3 + [TIER_VERIFIED]
    assert [c.identity_match for c in out.corners] == ["inside"] * 4
    assert _positions(out) == _positions(model)


def test_default_min_tier_attaches_only_verified_turns() -> None:
    """Seeded (unreviewed) turns label nothing by default: their corners stay unlabelled, never pulled elsewhere."""
    assert DEFAULT_MIN_TIER == TIER_VERIFIED
    model = _model([(150, "right"), (450, "left"), (750, "left")])
    mapping = map_identity(model, _sheet())
    assert [(a.label, a.match, a.candidate) for a in mapping.assignments] == [
        (None, "below_min_tier", "T1 (sheet_seeded)"),
        (None, "below_min_tier", "T3-5 (sheet_seeded)"),
        ("T6", "inside", None),
    ]
    out = apply_identity(model, mapping)
    texts = corner_texts(out)
    assert texts["T1"].long == "Corner at 150 m" and texts["T1"].voice == "Corner at 150 metres"  # mapped model
    assert texts["T3"].long == "Turn 6 (Omega)"
    with pytest.raises(ValueError, match="min_tier"):
        map_identity(model, _sheet(), min_tier="best")


def test_fully_seeded_sheet_changes_nothing() -> None:
    """The reviewer's Melbourne case: a seeded sheet attaches no number, so nothing unreviewed is shown or spoken."""
    mel = find_sheet("f1_25", "f1:0")
    assert mel is not None and not any(t.verified for t in mel.turns)
    model = _model([(335.0, "right"), (4100.0, "right")], length=5276.0, track_id="f1:0")
    out, mapping = identify(model)
    assert mapping is not None and mapping.ok and mapping.labelled == 0
    assert all(c.label is None and c.identity_tier is None for c in out.corners)
    assert corner_texts(out) == corner_texts(model)  # learned names everywhere, as without a sheet
    assert {t.voice for t in corner_texts(out).values()} == {"T1", "T2"}
    assert "below_min_tier:T11 (sheet_seeded)" in mapping.summary()  # review tooling still sees the candidate
    preview, _ = identify(model, min_tier=TIER_SEEDED)
    assert [c.label for c in preview.corners] == ["T1", "T11"] and preview.corners[1].display_name == "Ascari"


def test_missing_minimum_and_unlabelled_corner() -> None:
    """A sheet turn without a learned corner is absent; a learned corner in no window stays unlabelled."""
    model = _model([(150, "right"), (650, None)])  # 650: 50 m from T3-5 and T6 windows, beyond the margin
    mapping = _map(model)
    assert [(a.label, a.match) for a in mapping.assignments] == [("T1", "inside"), (None, "none")]
    assert len(mapping.absent_turns) == 3
    out = apply_identity(model, mapping)
    texts = corner_texts(out)
    assert texts["T2"].short == "650 m" and texts["T2"].long == "Corner at 650 m"  # never a colliding "T2"
    assert texts["T2"].voice == "Corner at 650 metres"


def test_absent_turn_merges_into_the_minimum_it_brakes_for() -> None:
    """Research 6.3 step 5: several official turns can map to one learned corner ("Turns 1-2")."""
    sheet = _sheet(
        turns=[
            {"numbers": [1], "names": [{"text": "Alpha", "kind": "traditional"}], "game_segment_m": [250, 420],
             "voice_ok": True, "sources": ["test"]},
            {"numbers": [2], "names": [{"text": "Beta", "kind": "traditional"}], "game_segment_m": [421, 580],
             "voice_ok": True, "sources": ["test"]},
            {"numbers": [3], "game_segment_m": [700, 800], "sources": ["test"]},
        ]
    )  # fmt: skip
    # one minimum at 430 m (Beta's window) whose braking starts at 300 m, inside Alpha's window (centre 335 m)
    model = replace(_model([(430.0, "right")]), corners=[_corner("T1", 430.0, "right", entry=300.0)])
    mapping = _map(model, sheet)
    row = mapping.assignments[0]
    assert (row.label, row.numbers, row.match, row.merged_turns) == ("T1-2", (1, 2), "inside", (0,))
    assert row.display_name == "Beta" and row.voice_ok is False  # composite: name not voiced
    assert [sheet.turns[i].label for i in mapping.absent_turns] == ["T3"]
    assert mapping.table()[0]["merged"] == ["T1"] and "[merged]" in mapping.summary()
    out = apply_identity(model, mapping)
    assert out.corners[0].identity_match == "merged" and out.corners[0].official_numbers == [1, 2]
    assert corner_texts(out)["T1"] == CornerText("T1-2", "Turns 1-2 (Beta)", "Turns 1 to 2")
    assert resolve_corner_ref(out, "Turn 1") == ["T1"] and resolve_corner_ref(out, "Turn 2") == ["T1"]
    # braking starts after Alpha's centre: Alpha is a separate (flat) turn and stays absent
    later = replace(model, corners=[_corner("T1", 430.0, "right", entry=345.0)])
    assert _map(later, sheet).assignments[0].label == "T2"


def test_merging_never_crosses_a_present_turn_or_a_shared_one() -> None:
    sheet = _sheet()  # T1 [100,200), T2 [250,300) flat, T3-5 [400,600), T6 [700,800)
    # T2's centre (275 m) is in the T3-5 corner's braking phase, but T2 + T3-5 = T2-5 is contiguous: merged
    one = replace(_model([(450.0, None)]), corners=[_corner("T1", 450.0, entry=260.0)])
    assert _map(one, sheet).assignments[0].label == "T2-5"
    # two minima share T3-5 (parts): neither absorbs T2, the parts would no longer describe one turn
    two = replace(
        _model([(450.0, None), (550.0, None)]),
        corners=[_corner("T1", 450.0, entry=260.0), _corner("T2", 550.0, entry=500.0)],
    )
    assert [a.label for a in _map(two, sheet).assignments] == ["T3-5", "T3-5"]
    # an edge-matched corner never hosts a merge
    edge = replace(_model([(215.0, "right")]), corners=[_corner("T1", 215.0, "right", entry=100.0)])
    rows = _map(edge, sheet).assignments
    assert (rows[0].label, rows[0].match, rows[0].merged_turns) == ("T1", "edge", ())


def test_length_scaling_within_tolerance() -> None:
    """Windows scale with model/sheet length, so a +/-1 % lap-length difference shifts no label."""
    sheet = _sheet()
    longer = _model([(201.5, "right")], length=1010.0)  # T1 window [100, 200) scales to [101, 202)
    m = _map(longer, sheet, edge_margin_m=0)
    assert m.ok and m.scale == pytest.approx(1.01)
    assert (m.assignments[0].label, m.assignments[0].match) == ("T1", "inside")
    shorter = _model([(198.5, "right")], length=990.0)  # T1 window scales to [99, 198)
    assert _map(shorter, sheet, edge_margin_m=0).assignments[0].match == "none"
    assert _map(shorter, sheet).assignments[0].match == "edge"


def test_length_gate_refuses_other_layouts() -> None:
    sheet = _sheet()
    model = _model([(150, "right"), (750, "left")], length=1020.0)  # +2 %: a different layout
    mapping = _map(model, sheet)
    assert not mapping.ok and mapping.labelled == 0 and "length_mismatch" in mapping.summary()
    out = apply_identity(model, mapping)
    assert all(c.label is None and c.identity_tier is None for c in out.corners)


def test_sector_gate_uses_the_game_session_lines() -> None:
    """The game's own S2/S3 starts (L0a) must agree with the sheet's, or a moved layout would mislabel silently."""
    sheet = _sheet(sector_starts_m=[300, 650])
    model = _model([(150, "right"), (750, "left")])
    ok = _map(model, sheet, zones=_zones(300.4, 649.8))
    assert ok.ok and ok.sector_mismatch_m == pytest.approx(0.4) and ok.labelled == 2
    moved = _map(model, sheet, zones=_zones(300.0, 650.0 + MAX_SECTOR_MISMATCH_M + 1))
    assert moved.status == "sector_mismatch" and moved.labelled == 0 and "sector_mismatch" in moved.summary()
    assert all(c.label is None for c in apply_identity(model, moved).corners)
    assert _map(model, sheet, zones=_zones(None, None)).ok  # game did not report sectors: no gate
    assert _map(model, _sheet(), zones=_zones(10.0, 20.0)).ok  # sheet has no sector values: no gate
    longer = _model([(150, "right")], length=1010.0)  # sheet sectors scale with the windows
    assert _map(longer, sheet, zones=_zones(303.0, 656.5)).sector_mismatch_m == pytest.approx(0.0)
    assert sector_mismatch_m(sheet, 310.0, 640.0) == pytest.approx(10.0)


def test_unverified_wire_format_downgrades_verified_turns() -> None:
    """F1 25 and its 2026 Season Pack are both Game.F1_25; verification evidence is per wire format."""
    sheet = parse_sheet(_verified_doc(verified_formats=[2025]))
    model = _model([(150, "right"), (750, "left")])
    same = map_identity(model, sheet, zones=_zones(None, None, "f1_session@2025"))
    assert same.format_verified and same.packet_format == 2025 and same.labelled == 2
    other = map_identity(model, sheet, zones=_zones(None, None, "f1_session@2026"))
    assert not other.format_verified and other.labelled == 0 and "format 2026 not verified" in other.summary()
    seeded = map_identity(model, sheet, packet_format=2026, min_tier=TIER_SEEDED)
    assert [a.tier for a in seeded.assignments] == [TIER_SEEDED, TIER_SEEDED]
    unknown = map_identity(model, sheet, zones=_zones(None, None, "legacy_session_info"))
    assert unknown.packet_format is None and unknown.labelled == 2  # unknown format: the games gate applies


def test_edge_margin_only_for_apexes_outside_every_window() -> None:
    sheet = _sheet()
    near = _model([(200 + EDGE_MARGIN_M - 5, "right")])
    far = _model([(200 + EDGE_MARGIN_M + 5, "right")])
    assert _map(near, sheet).assignments[0].match == "edge"
    assert _map(far, sheet).assignments[0].label is None
    # an apex inside a window keeps it even if another window edge is closer
    inside = _model([(251, "left")])
    assert _map(inside, sheet).assignments[0].label == "T2"


def test_edge_matches_keep_the_number_but_never_speak_the_name() -> None:
    sheet = _sheet()  # T1 "Alpha" is voice_ok
    model = _model([(150, "right"), (210, "right")])
    out = apply_identity(model, _map(model, sheet))
    assert [(c.label, c.label_part, c.identity_match, c.voice_ok) for c in out.corners] == [
        ("T1", 1, "inside", True),
        ("T1", 2, "edge", False),
    ]
    texts = corner_texts(out)
    assert texts["T1"].voice == "Turn 1, Alpha, first part"
    assert texts["T2"].voice == "Turn 1, second part" and texts["T2"].long == "Turn 1, part 2 (Alpha)"


def test_direction_conflict_vetoes_the_label() -> None:
    model = _model([(150, "left"), (500, "left"), (750, None)])  # T1 is a right; complexes have no direction
    rows = _map(model).assignments
    assert (rows[0].label, rows[0].match) == (None, "direction_conflict")
    assert rows[1].label == "T3-5" and rows[2].label == "T6"


def test_parts_follow_lap_order_whatever_the_list_order() -> None:
    model = _model([(560, None), (420, None)])
    rows = _map(model).assignments
    assert [(r.corner, r.part) for r in rows] == [("T1", 2), ("T2", 1)]


def test_apply_identity_is_pure_idempotent_and_clears_stale_labels() -> None:
    model = _model([(150, "right"), (750, "left")])
    before = [astuple(c) for c in model.corners]
    labelled = apply_identity(model, _map(model))
    assert [astuple(c) for c in model.corners] == before  # input untouched
    again = apply_identity(labelled, _map(labelled))
    assert [astuple(c) for c in again.corners] == [astuple(c) for c in labelled.corners]
    cleared = apply_identity(labelled, None)
    assert [astuple(c) for c in cleared.corners] == before
    assert cleared.corners[0].official_numbers is not cleared.corners[1].official_numbers  # no shared lists


def test_apply_identity_rejects_a_mapping_for_another_model() -> None:
    model = _model([(150, "right")])
    other = _model([(160, "right")])
    with pytest.raises(ValueError, match="does not belong"):
        apply_identity(other, _map(model))


def test_identify_without_a_sheet_clears_identity() -> None:
    model = _model([(150, "right")], track_id="synthetic:coaching_demo", game="synthetic")
    stale = apply_identity(model, _map(model))
    assert stale.corners[0].label == "T1"
    out, mapping = identify(stale)
    assert mapping is None and out.corners[0].label is None and out.corners[0].identity_tier is None
    assert corner_texts(out)["T1"] == corner_texts(model)["T1"]


# ---------------------------------------------------------------------------- identify never fails the caller
class _FakeFamily:
    """Sheet documents for a fake game family "zz", served in place of the packaged files."""

    def __init__(self, real: Any) -> None:
        self.real = real
        self.docs: list[tuple[str, dict[str, Any]]] = []
        self.calls = 0

    def __call__(self, family: str) -> list[tuple[str, dict[str, Any]]]:
        if family != "zz":
            return list(self.real(family))
        self.calls += 1
        return self.docs


@pytest.fixture
def fake_family(monkeypatch: pytest.MonkeyPatch) -> Iterator[_FakeFamily]:
    """Serve family "zz" from the test; restores the sheet cache and the failure registry afterwards."""
    fake = _FakeFamily(trackdata.sheet_documents)
    monkeypatch.setattr(trackdata, "sheet_documents", fake)
    load_sheets.cache_clear()
    ti._failed_families.discard("zz")
    yield fake
    load_sheets.cache_clear()
    ti._failed_families.discard("zz")
    ti._failed_models.clear()


def test_a_broken_sheet_disables_identity_once_without_raising(
    fake_family: _FakeFamily, caplog: pytest.LogCaptureFixture
) -> None:
    doc = _doc(game_family="zz", game_track_id=1)
    doc["turns"][0]["direction"] = ["left"]  # the reviewer's hand-edit: a list where a string belongs
    fake_family.docs = [("track_sheets/zz/01.toml", doc)]
    model = _model([(150, "right")], track_id="zz:1")
    with pytest.raises(SheetError, match="direction"):
        find_sheet("f1_25", "zz:1")
    calls_before = fake_family.calls
    with caplog.at_level(logging.ERROR, logger="pitwall.analysis.track_identity"):
        for _ in range(3):
            out, mapping = identify(model)
            assert mapping is None and out.corners[0].label is None
    assert fake_family.calls == calls_before + 1  # read once, then the family stays disabled
    assert sum("failed to load" in r.getMessage() for r in caplog.records) == 1
    assert identify(_model([(750, "left")], track_id="f1:99"))[1] is None  # other families unaffected
    assert identify(_austria())[1] is not None


def test_unreadable_sheet_files_are_sheet_errors(fake_family: _FakeFamily, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(family: str) -> list[tuple[str, dict[str, Any]]]:
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    monkeypatch.setattr(trackdata, "sheet_documents", boom)
    with pytest.raises(SheetError, match="unreadable"):
        find_sheet("f1_25", "zz:1")
    out, mapping = identify(_model([(150, "right")], track_id="zz:1"))
    assert mapping is None and out.corners[0].label is None


def test_identify_survives_a_mapping_error(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    def boom(*_: Any, **__: Any) -> IdentityMapping:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(ti, "map_identity", boom)
    model = _model(AUSTRIA_APEXES, length=4323.0, track_id="f1:17")
    try:
        with caplog.at_level(logging.ERROR, logger="pitwall.analysis.track_identity"):
            for _ in range(2):
                out, mapping = identify(model)
                assert mapping is None and all(c.label is None for c in out.corners)
        assert sum("corner identity failed" in r.getMessage() for r in caplog.records) == 1
    finally:
        ti._failed_models.clear()


# Learned Austria model from the real capture data/captures/20261010-191501_udp20777.pwcap (F1 25 v1.26 PS5,
# format 2025): build_track_model on the one clean race lap (lap 2), replayed read-only. Values copied from that
# replay (apex, entry, exit, segment, direction, min speed); recorded-derived input, not synthetic. Note the real
# exits: no full throttle between Turn 4 and Turn 7, so learned T4-T7 all exit at 3217 m.
AUSTRIA_LEARNED: list[tuple[float, float, float, float, float, str, float]] = [
    (443.0, 332.0, 491.0, 0.0, 504.0, "right", 119.0),
    (565.0, 332.0, 588.0, 504.0, 998.0, "right", 129.0),
    (1431.0, 1235.0, 1449.0, 998.0, 1822.0, "right", 63.0),
    (2213.0, 2066.0, 3217.0, 1822.0, 2442.5, "right", 71.0),
    (2672.0, 2605.0, 3217.0, 2442.5, 2713.5, "left", 119.0),
    (2755.0, 2605.0, 3217.0, 2713.5, 2904.0, "left", 128.0),
    (3053.0, 2974.0, 3217.0, 2904.0, 3426.5, "left", 116.0),
    (3800.0, 3700.0, 3857.0, 3426.5, 3913.5, "right", 150.0),
    (4027.0, 3944.0, 4063.0, 3913.5, 4323.0, "right", 125.0),
]
AUSTRIA_APEXES = [(a, d) for a, _e, _x, _s, _t, d, _v in AUSTRIA_LEARNED]
AUSTRIA_ZONES = _zones(1203.9620361328125, 2934.93212890625)  # the capture's Session packet (TrackZones)


def _austria() -> TrackModel:
    corners = [
        Corner(f"T{i + 1}", apex, entry, exit_, s0, s1, d, v)
        for i, (apex, entry, exit_, s0, s1, d, v) in enumerate(AUSTRIA_LEARNED)
    ]
    return TrackModel(game="f1_25", track_id="f1:17", track_name="Austria", length_m=4323.0, corners=corners)


def test_austria_real_learned_corners_get_official_labels() -> None:
    model = _austria()
    out, mapping = identify(model, zones=AUSTRIA_ZONES)
    assert mapping is not None and mapping.ok and mapping.format_verified
    assert mapping.sector_mismatch_m is not None and mapping.sector_mismatch_m < 0.1
    rows = [(r["corner"], r["label"], r["part"], r["match"], r["merged"], r["voice_ok"]) for r in mapping.table()]
    assert rows == [
        ("T1", "T1", 1, "inside", [], True),
        ("T2", "T1", 2, "edge", [], False),  # a lift on the exit, 20 m past the T1 window: name not spoken
        ("T3", "T3", None, "inside", [], False),  # stale sponsor names (Remus, Würth, Red Bull Mobile) dropped
        ("T4", "T4", None, "inside", [], False),  # sponsor name (Rauch) not shown while the policy is open
        ("T5", "T6", 1, "inside", [], False),  # double-apex T6 (no name)
        ("T6", "T6", 2, "inside", [], False),
        ("T7", "T7", None, "inside", [], False),
        ("T8", "T9", None, "inside", [], True),
        ("T9", "T10", None, "inside", [], False),  # the "T9" the coach said on the real race is Turn 10
    ]
    # flat/part-throttle turns: absent, never merged (T5 lies 1000 m before learned T4's exit, but after its apex)
    assert [mapping.sheet.turns[i].label for i in mapping.absent_turns] == ["T2", "T5", "T8"]
    assert all(c.identity_tier == TIER_VERIFIED for c in out.corners)
    assert _positions(out) == _positions(model)
    texts = corner_texts(out)
    assert texts["T9"] == CornerText("T10", "Turn 10", "Turn 10")
    assert texts["T8"] == CornerText("T9", "Turn 9 (Rindt Kurve)", "Turn 9, Rindt Kurve")
    assert texts["T2"] == CornerText("T1 (2)", "Turn 1, part 2 (Niki Lauda Kurve)", "Turn 1, second part")
    assert texts["T4"] == CornerText("T4", "Turn 4", "Turn 4")
    assert texts["T3"].long == "Turn 3"
    # the same model in a 2026 Season Pack session: format-2025 evidence does not carry over
    pack, pack_map = identify(model, zones=_zones(1203.96, 2934.93, "f1_session@2026"))
    assert pack_map is not None and pack_map.labelled == 0 and corner_texts(pack) == corner_texts(model)


def test_corner_references_resolve_to_learned_corners() -> None:
    """What the driver/LLM says ("Turn 10", "Lauda") finds the learned corner keys used by facts and analysis."""
    unmapped = _austria()
    assert resolve_corner_ref(unmapped, "T9") == ["T9"] and resolve_corner_ref(unmapped, "Remus") == []
    out, _ = identify(unmapped)
    assert resolve_corner_ref(out, "Turn 10") == ["T9"]
    assert resolve_corner_ref(out, "t10") == ["T9"] and resolve_corner_ref(out, "10") == ["T9"]
    assert resolve_corner_ref(out, "T6") == ["T5", "T6"]  # double apex: both learned corners
    assert resolve_corner_ref(out, "T2") == []  # official flat kink, not the learned "T2"
    assert resolve_corner_ref(out, "rindt") == ["T8"] and resolve_corner_ref(out, "Lauda") == ["T1", "T2"]
    assert resolve_corner_ref(out, "Schlossgold") == []  # disputed name is not identity
    assert resolve_corner_ref(out, "remus") == [] and resolve_corner_ref(out, "Wurth") == []  # stale names neither
    assert resolve_corner_ref(out, "Parabolica") == [] and resolve_corner_ref(out, "  ") == []
    learned = _model([(500, None)])
    complex_model = apply_identity(learned, _map(learned))
    assert resolve_corner_ref(complex_model, "Turn 4") == ["T1"]  # a number inside the T3-5 complex


def test_lettered_sub_turns_resolve_separately() -> None:
    sheet = parse_sheet(_lettered_doc(([2], None, [100, 200]), ([2], "T2a", [200, 300]), ([3], None, [400, 500])))
    model = _model([(150, None), (250, None), (450, None)])
    out = apply_identity(model, _map(model, sheet))
    assert [c.label for c in out.corners] == ["T2", "T2a", "T3"]
    assert resolve_corner_ref(out, "Turn 2") == ["T1"] and resolve_corner_ref(out, "T2a") == ["T2"]
    assert corner_texts(out)["T2"] == CornerText("T2a", "Turn 2a", "Turn 2a")


def test_reverse_layout_mapping_gives_names_not_numbers() -> None:
    """Austria Reverse (id 40, hand-reviewed): names only, never a forward number. Only the corners whose forward
    names are verified (Rindt, Niki Lauda) are named by default; the windows of the stale or wrong sponsor names
    (Red Bull Mobile, Würth, Rauch/Schlossgold, Remus) stay seeded: physically confirmed, never shown or voiced."""
    model = _model(
        [(353.0, "left"), (504.0, "left"), (1598.0, "right"), (2929.0, "left"), (3861.0, "left")], 4323.0, "f1:40"
    )
    out, mapping = identify(model)
    assert mapping is not None and mapping.ok
    assert [c.display_name for c in out.corners] == [None, "Rindt Kurve", None, None, "Niki Lauda Kurve"]
    assert all(c.label is None and c.official_numbers == [] for c in out.corners)
    assert [c.identity_tier for c in out.corners] == [None, TIER_VERIFIED, None, None, TIER_VERIFIED]
    texts = corner_texts(out)
    assert texts["T2"].short == "Rindt Kurve" and texts["T2"].voice == "Rindt Kurve"  # verified, inside: voiced
    assert texts["T4"].voice == "Corner at 2930 metres"  # the old 'Remus' window: seeded, not named
    preview, _ = identify(model, min_tier=TIER_SEEDED)
    assert [c.display_name for c in preview.corners] == ["Red Bull Mobile", "Rindt Kurve", "Rauch", "Remus",
                                                         "Niki Lauda Kurve"]  # fmt: skip
    assert [c.voice_ok for c in preview.corners] == [False, True, False, False, True]
    sheet = find_sheet("f1_25", "f1:40")
    assert sheet is not None and sheet.reverse_of == 17 and sheet.verified_formats == (2025,)


# ============================================================================================ display
def test_corner_display_forms() -> None:
    c = _corner("T5", 2672.0, "left")
    assert corner_display(c) == "T5" and corner_display(c, "voice") == "T5"  # no identity: today's behaviour
    named = _with(c, label="T3", official_numbers=[3], display_name="Remus", voice_ok=True, identity_tier=TIER_VERIFIED)
    assert [corner_display(named, s) for s in ("short", "long", "voice")] == ["T3", "Turn 3 (Remus)", "Turn 3, Remus"]
    silent = _with(named, voice_ok=False)
    assert corner_display(silent, "voice") == "Turn 3" and corner_display(silent, "long") == "Turn 3 (Remus)"
    cx = _with(c, label="T2-4", official_numbers=[2, 3, 4], display_name="Eau Rouge", voice_ok=True,
               identity_tier=TIER_VERIFIED, label_part=2)  # fmt: skip
    assert corner_display(cx, "short") == "T2-4 (2)"
    assert corner_display(cx, "long") == "Turns 2-4, part 2 (Eau Rouge)"
    assert corner_display(cx, "voice") == "Turns 2 to 4, Eau Rouge, second part"
    rev = _with(c, display_name="Remus", identity_tier=TIER_SEEDED)
    assert [corner_display(rev, s) for s in ("short", "long", "voice")] == ["Remus", "Remus", "Corner at 2670 metres"]
    unl = _with(c, identity_tier=None)
    assert corner_display(unl, "long", mapped=True) == "Corner at 2672 m"


def test_track_model_payload_carries_display_text() -> None:
    out, _ = identify(_austria())
    payload = json.loads(json.dumps(track_model_payload(out)))
    assert payload["corners"][8]["label"] == "T10" and payload["corners"][8]["name"] == "T9"
    assert payload["corners"][1]["identity_match"] == "edge" and payload["corners"][1]["voice_ok"] is False
    assert payload["corner_text"]["T9"] == {"short": "T10", "long": "Turn 10", "voice": "Turn 10"}
    assert payload["corner_text"]["T8"] == {
        "short": "T9",
        "long": "Turn 9 (Rindt Kurve)",
        "voice": "Turn 9, Rindt Kurve",
    }


def test_short_labels_are_spoken_as_turns() -> None:
    from pitwall.voice.speech import to_speech

    assert to_speech("T2-4: braking 5 m earlier").startswith("turns 2 to 4")
    assert to_speech("T10, losing 0.12 s").startswith("turn 10")


# ============================================================================================ persistence
def test_stored_model_shape_is_learned_only() -> None:
    """``to_dict()`` (what ``storage.repo.save_track_model`` stores) is exactly the pre-identity shape."""
    model = _model([(150, "right"), (450, "left"), (550, "right")])
    labelled = apply_identity(model, _map(model))
    stored = json.loads(json.dumps(labelled.to_dict()))
    assert stored == json.loads(json.dumps(model.to_dict()))
    assert all(set(c) == {"name", "apex_m", "entry_m", "exit_m", "seg_start_m", "seg_end_m", "direction",
                          "ref_min_speed_kph"} for c in stored["corners"])  # fmt: skip
    assert all(set(IDENTITY_FIELDS) <= set(c) for c in labelled.to_dict(identity=True)["corners"])
    back = TrackModel.from_dict(stored)
    assert _positions(back) == _positions(model) and [astuple(c) for c in back.corners] == [
        astuple(c) for c in model.corners
    ]


def test_from_dict_reads_rows_of_any_version() -> None:
    model = _model([(150, "right"), (750, "left")])
    raw = json.loads(json.dumps(apply_identity(model, _map(model)).to_dict(identity=True)))
    # rows written on 2026-10-10 while identity was persisted (null values included), plus a future key
    raw["corners"][0].update(official_numbers=None, label="T13", identity_tier="sheet_seeded", future_field=1)
    raw["future_model_field"] = {"x": 1}
    back = TrackModel.from_dict(raw)
    assert [(c.label, c.official_numbers, c.identity_tier) for c in back.corners] == [(None, [], None)] * 2
    assert _positions(back) == _positions(model)


# ============================================================================================ licence files
def test_vendored_data_ships_with_licence_and_provenance() -> None:
    root = pits_n_giggles_dir()
    licence = root.joinpath("LICENSE").read_text(encoding="utf-8")
    assert licence.startswith("MIT License")
    assert "Copyright (c) [2024] [Ashwin Natarajan]" in licence
    assert 'THE SOFTWARE IS PROVIDED "AS IS"' in licence
    provenance = root.joinpath("PROVENANCE.md").read_text(encoding="utf-8")
    assert PITS_N_GIGGLES_COMMIT in provenance and PITS_N_GIGGLES_COMMIT.startswith("72f78aaf")
    assert "release-v5.0.0" in provenance
    assert "review before any commercial release" in provenance.lower()
    # every vendored file is byte-identical to the pinned upstream blob recorded in PROVENANCE.md
    recorded = dict(re.findall(r"\| `([A-Za-z_]+\.json)` \| `([0-9a-f]{40})` \|", provenance))
    files = sorted(
        (p for p in root.joinpath("track-segments").iterdir() if p.name.endswith(".json")), key=lambda p: p.name
    )
    assert len(files) == 28 and sorted(recorded) == [p.name for p in files]
    for p in files:
        assert _git_blob_sha1(p.read_bytes()) == recorded[p.name], p.name
    assert _git_blob_sha1(licence.encode("utf-8")) == "8d23eef7c81cc358ae7e6d4b33186cc6704fa5b8"
    register = (ROOT / "docs" / "licences.md").read_text(encoding="utf-8")
    assert "Pits n' Giggles" in register and PITS_N_GIGGLES_COMMIT in register


def test_seeded_sheets_carry_the_mit_notice() -> None:
    sheet_dir = ROOT / "src" / "pitwall" / "trackdata" / "track_sheets" / "f1"
    for p in sorted(sheet_dir.glob("*.toml")):
        head = p.read_text(encoding="utf-8")[:600]
        assert "Copyright (c) 2024 Ashwin Natarajan" in head and "MIT" in head, p.name


# ============================================================================================ recorded tier
@pytest.mark.recorded
@pytest.mark.skipif(not EXCERPT.exists(), reason="Austria excerpt fixture not present")
def test_austria_sheet_matches_the_recorded_session() -> None:
    """The committed real F1 25 excerpt: the game's lap length and sector lines (typed ``track_zones``) match the
    sheet and pass the identity gates, and the car steers right inside the sheet's T10 window on the flying laps
    (the excerpt has no complete lap, so no learned model can be built from it; lap 1 is skipped because the
    standing-start lap had an off at T10)."""
    from pitwall.ingest.capture import CaptureReader
    from tests.conftest import decode_session

    laps, _frames, info, _ = decode_session(list(CaptureReader(EXCERPT)))
    sheet = find_sheet(str(info.game), info.track_id)
    assert sheet is not None and info.track_id == "f1:17"
    assert info.track_length_m == sheet.lap_length_m
    zones = info.track_zones
    assert zones is not None and zones.source == "f1_session@2025"
    mismatch = sector_mismatch_m(sheet, zones.sector2_start_m, zones.sector3_start_m)
    assert mismatch is not None and mismatch < 1.0
    _, mapping = identify(_austria(), zones=zones)
    assert mapping is not None and mapping.ok and mapping.format_verified and mapping.labelled == 9
    t10 = next(t for t in sheet.turns if t.label == "T10")
    lo, hi = t10.segment_m
    steer = [
        lap.channels["steering"][(lap.channels["distance_m"] >= lo) & (lap.channels["distance_m"] < hi)]
        for lap in laps
        if lap.lap_number >= 2
    ]
    samples = np.concatenate(steer)
    assert len(samples) > 20 and float(np.nanmean(samples)) > 0.05 and t10.direction == "right"
