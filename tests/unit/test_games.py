"""Game catalogue (``pitwall.games``): derived from ``capabilities.PLANNED`` and ``AdapterInfo``, never stronger than
the evidence, golden profiles (design spec section 2.6) and the code facts each pinned to the code they restate."""

from __future__ import annotations

import json
import re
from dataclasses import fields as dc_fields
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from pitwall import games
from pitwall.adapters.base import SupportLevel
from pitwall.capabilities import ADAPTER_INFOS, PLANNED, capability_matrix
from pitwall.model.telemetry import CarFrame, Game, Platform

S = SupportLevel
GOLDEN_MATRIX = Path(__file__).resolve().parents[1] / "fixtures" / "golden" / "capability_matrix_0a8a911.json"

ABBR = {
    "live_validated": "live",
    "recorded_validated": "rec",
    "spec_implemented": "spec",
    "community_documented": "comm",
    "partial": "part",
}
CODE = {"supported": "S", "partial": "P", "not_sent": "NS", "not_implemented": "NI", "unknown": "U"}


def code(f: games.GameFeature) -> str:
    c = CODE[f.status]
    if c in ("S", "P"):
        return f"{c}·{ABBR[f.evidence.value] if f.evidence is not None else '-'}"
    return c


# Design spec section 2.6, with two corrections from review: official corner names are partial for F1 25 (only
# hand-checked track sheets count: track_identity shows verified turns only) and GT7's car setup is "not in Pitwall
# yet" rather than "not sent" (GT7 sends its gear ratios; Pitwall doesn't read them as a setup). GT7 on PS5 since
# 2026-10-11: validated live, its lap, distance, input and tyre fields on the owner's recordings, so ·rec where it was
# ·comm (the distance features stay "Estimated": GT7 sends no lap distance).
GOLDEN_COLUMNS = ("f1_25:ps5", "gt7:ps5", "ac:ps5", "forza_motorsport:pc", "forza_horizon:xbox")
GOLDEN = """
lap_timing             S·spec  S·rec   S·rec   P·part  P·part
sectors                S·spec  NS      NS      NS      NS
delta                  S·spec  P·rec   P·part  P·part  P·part
braking_cues           S·spec  P·rec   P·part  P·part  P·part
corner_coaching        S·spec  P·rec   P·part  P·part  P·part
track_map              S·spec  P·rec   P·part  P·part  P·part
official_corner_names  P·-     NI      NI      NI      NI
ai_field               S·rec   NS      NS      NS      NS
flags                  S·spec  NS      NS      NS      NS
fuel                   S·spec  NI      NS      NI      NI
tyre_temps             S·spec  S·rec   NS      S·comm  S·comm
tyre_wear              S·spec  NS      NS      S·comm  NS
tyre_pressures         S·spec  NS      NS      NS      NS
brake_temps            S·spec  NS      NS      NS      NS
damage                 NI      NS      NS      NS      NS
ers                    S·spec  NI      NS      NS      NS
drs                    S·spec  NS      NS      NS      NS
weather                S·spec  NS      NS      NS      NS
session_info           P·spec  NS      NS      NS      NS
field_data             S·rec   NS      NS      NS      NS
setup_telemetry        S·spec  NI      NS      NS      NS
setup_recommendations  P·-     NI      NI      NI      NI
wheel_ptt              S·spec  NS      NS      NS      NS
"""


def golden() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {c: {} for c in GOLDEN_COLUMNS}
    for line in GOLDEN.strip().splitlines():
        fid, *cells = line.split()
        for col, cell in zip(GOLDEN_COLUMNS, cells, strict=True):
            out[col][fid] = cell
    return out


def profile(entry_id: str) -> dict[str, str]:
    e = games.entry(entry_id)
    assert e is not None
    return {f.id: code(f) for f in e.features}


# ---------------------------------------------------------------------------------------------- catalogue shape
def test_ids_are_unique_and_well_formed() -> None:
    ids = [e.id for e in games.entries()]
    assert len(ids) == len(set(ids)) == 23
    for i in ids:
        assert re.fullmatch(r"[a-z0-9_]+:(ps5|ps4|xbox|pc|any)", i), i
    assert [f.id for f in games.FEATURES] == list(games.FEATURE_IDS) and len(games.FEATURES) == 23
    assert {f.group for f in games.FEATURES} == {g for g, _ in games.GROUPS}


def test_every_entry_maps_to_one_row_and_every_row_platform_has_an_entry() -> None:
    keys = {r.key for r in PLANNED}
    by_row: dict[str, set[str]] = {}
    for e in games.entries():
        if e.id == "other:any":
            assert e.row is None
            continue
        assert e.row is not None and e.row.key in keys, e.id
        assert e.platform in e.row.platform_ids, e.id
        by_row.setdefault(e.row.key, set()).add(e.platform)
    for r in PLANNED:
        if r.key == "video_capture":
            assert r.platform_ids == () and r.key not in by_row
            continue
        assert by_row[r.key] == set(r.platform_ids), r.key


def test_short_labels_and_entry_words() -> None:
    shorts = {e.game_key: e.short_label for e in games.entries()}
    assert shorts == {
        "f1_25": "F1 25",
        "f1_25_2026": "F1 25",
        "f1_24": "F1 24",
        "gt7": "GT7",
        "forza_motorsport": "Forza M",
        "forza_horizon": "Forza H",
        "ac": "AC",
        "acc": "ACC",
        "iracing": "iRacing",  # the spec's list; 7 characters
        "other": "Other",
    }
    words = {e.id: e.support_words for e in games.entries()}
    assert words["f1_25:ps5"] == words["gt7:ps5"] == "Tested live"
    assert words["f1_25:pc"] == words["f1_25_2026:ps5"] == "Built from the official spec"
    assert words["ac:ps5"] == "Tested on a recording"
    assert words["gt7:ps4"] == words["ac:pc"] == "Built from community docs"
    assert words["forza_horizon:ps5"] == "Unverified"
    assert words["acc:pc"] == words["iracing:pc"] == "Not in Pitwall yet"
    assert words["acc:ps5"] == words["ac:xbox"] == words["f1_24:any"] == "Not supported"
    assert words["other:any"] == "Records packets only"
    readme = (Path(__file__).resolve().parents[2] / "README.md").read_text(encoding="utf-8")
    for w in (games.WORDS_PARTIAL_NOT_IMPLEMENTED, games.WORDS_RECORD_ONLY):  # the README table's own words
        assert f"| {w} |" in readme, w
    summaries = {e.id: e.support_summary for e in games.entries()}
    assert summaries["f1_25:ps5"].startswith("Checked end to end with the real game")
    assert summaries["gt7:ps5"].startswith("Checked end to end with the real game")
    assert summaries["gt7:ps4"].startswith("Built from community documentation")  # no PS4 tested
    assert summaries["acc:ps5"] == "ACC on PS5 has no telemetry output."
    assert summaries["other:any"].startswith("Pitwall doesn't know what this game sends")
    assert all("Connect page" not in v for v in summaries.values())


def test_integrations_guides_and_rig() -> None:
    by = {e.id: e for e in games.entries()}
    assert {e.id for e in games.entries() if e.integration is None} == {
        "f1_24:any",
        "ac:xbox",
        "acc:pc",
        "acc:ps5",
        "acc:xbox",
        "iracing:pc",
    }
    assert by["other:any"].integration == "record" and by["other:any"].guide_id == "record"
    assert by["f1_25_2026:xbox"].integration == "f1" and by["f1_25_2026:xbox"].guide_id == "f1_25"
    assert by["f1_25:ps5"].rig() == {"game": "f1_25", "platform": "ps5"}
    assert by["f1_25:xbox"].rig() == {"game": "f1_25", "platform": None}
    assert by["f1_25_2026:pc"].rig() == {"game": "f1_25", "platform": "pc"}
    assert by["gt7:ps4"].rig() == {"game": "gt7", "platform": None}
    assert by["ac:ps5"].rig() is None and by["f1_24:any"].rig() is None


# ---------------------------------------------------------------------------------------------- never stronger
def _platform_level(e: games.GameEntry) -> SupportLevel:
    assert e.info is not None
    return e.info.platforms.get(Platform(e.platform), S.UNVERIFIED)


def test_never_stronger_than_the_row_the_adapter_or_any_field() -> None:
    for e in games.entries():
        lvl = e.level
        if e.row is None:
            assert lvl is None
            continue
        assert lvl is not None
        assert not games.stronger(lvl, e.row.status), e.id
        if e.info is not None and e.row.status is not S.UNSUPPORTED:
            assert not games.stronger(lvl, _platform_level(e)), e.id
        for f in e.features:
            if f.status in ("supported", "partial"):
                assert e.implemented, (e.id, f.id)
            if f.evidence is None:
                continue
            assert f.status in ("supported", "partial"), (e.id, f.id)
            assert not games.stronger(f.evidence, lvl), (e.id, f.id)
            assert e.info is not None
            for k in f.fields:
                assert not games.stronger(f.evidence, e.info.fields[k].level), (e.id, f.id, k)
        for k, fd in e.fields_dict().items():
            assert not games.stronger(SupportLevel(fd["level"]), lvl), (e.id, k)


def test_not_sent_and_unknown_follow_the_declarations() -> None:
    for e in games.entries():
        for f in e.features:
            fd = games.feature_def(f.id)
            if f.status == "not_sent":
                assert e.row is not None
                if e.row.no_output:
                    continue
                assert e.info is not None
                sources = [e.info.fields[k] for k in f.fields if k in e.info.fields]
                unsupported = [fs for fs in sources if fs.level is S.UNSUPPORTED]
                assert unsupported, (e.id, f.id)
                assert unsupported[0].source in f.detail, (e.id, f.id)
            if f.status == "unknown":
                if e.row is None or e.level is S.UNVERIFIED:
                    continue
                assert e.info is not None
                keys = (*(e.info.ground_plane if fd.ground_plane else ()), *fd.required)
                assert any(k not in e.info.fields or e.info.fields[k].level is S.UNVERIFIED for k in keys), (
                    e.id,
                    f.id,
                )


def test_an_undeclared_field_is_unknown_never_not_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    from pitwall.adapters.gt7.adapter import GT7_INFO

    trimmed = {k: v for k, v in GT7_INFO.fields.items() if k != "drs_open"}
    monkeypatch.setitem(ADAPTER_INFOS, Game.GT7, replace(GT7_INFO, fields=trimmed))  # AdapterInfo is frozen
    games._features.cache_clear()
    try:
        drs = games.entry("gt7:ps5").feature("drs")  # type: ignore[union-attr]
        assert drs.status == "unknown" and drs.short == "Unknown" and "not declared" in drs.detail
    finally:
        games._features.cache_clear()


# ---------------------------------------------------------------------------------------------- golden profiles
def test_golden_profiles() -> None:
    for col, expected in golden().items():
        assert profile(col) == expected, col


def test_platform_and_variant_profiles() -> None:
    ps5 = profile("f1_25:ps5")
    pc_like = {**ps5, "ai_field": "S·spec", "field_data": "S·spec"}  # the entry level caps the recorded fields
    assert profile("f1_25:pc") == profile("f1_25:xbox") == pc_like
    for p in ("ps5", "xbox", "pc"):  # the corner names were hand-checked with format 2025 only
        assert profile(f"f1_25_2026:{p}") == {**pc_like, "official_corner_names": "NI"}
    gt7_comm = {k: v.replace("·rec", "·comm") for k, v in profile("gt7:ps5").items()}
    assert profile("gt7:ps4") == gt7_comm  # same packets, but only the PS5 was tested
    ac_comm = {k: v.replace("·rec", "·comm") for k, v in profile("ac:ps5").items()}
    assert profile("ac:ps4") == ac_comm
    # AC on PC has this data in its shared memory, which Pitwall doesn't read: "not in Pitwall yet", never "not sent"
    local = set(games.LOCAL_ONLY["ac_pc"])
    assert profile("ac:pc") == {k: ("NI" if k in local else v) for k, v in ac_comm.items()}
    assert {k for k, v in ac_comm.items() if v == "NS"} - local == {
        "ai_field",
        "field_data",
        "setup_telemetry",
        "wheel_ptt",
    }
    fh_ps5 = profile("forza_horizon:ps5")
    assert all(v in ("NS", "NI", "U") for v in fh_ps5.values())
    assert {k for k, v in fh_ps5.items() if v == "U"} == {
        k for k, v in profile("forza_horizon:xbox").items() if v not in ("NS", "NI")
    }
    for eid in ("acc:ps5", "acc:xbox", "ac:xbox"):
        assert set(profile(eid).values()) == {"NS"}, eid
    for eid in ("acc:pc", "iracing:pc", "f1_24:any"):
        assert set(profile(eid).values()) == {"NI"}, eid
    assert set(profile("other:any").values()) == {"U"}


def test_feature_texts() -> None:
    gt7 = games.entry("gt7:ps5")
    assert gt7 is not None
    wear = gt7.feature("tyre_wear").to_dict()
    assert wear == {
        "id": "tyre_wear",
        "label": "Tyre wear",
        "group": "car",
        "status": "not_sent",
        "evidence": None,
        "short": "Not sent by GT7",
        "reason": "GT7 doesn't send tyre wear.",
        "detail": "not sent by GT7 (row gt7_ps5)",
        "note": None,
        "fields": ["tyre_wear_pct"],
    }
    assert gt7.feature("delta").short == "Estimated" and "0.2 %" in gt7.feature("delta").reason
    f1 = games.entry("f1_25:ps5")
    assert f1 is not None
    assert f1.feature("track_map").note is not None  # shipped outline before the first lap
    assert gt7.feature("track_map").note is None
    fm = games.entry("forza_motorsport:pc")
    assert fm is not None and fm.feature("lap_timing").short == "Partial"
    fh = games.entry("forza_horizon:xbox")
    assert fh is not None and fh.feature("lap_timing").reason == games.PARTIAL_FACTS[("forza_horizon", "lap_timing")]
    names = re.compile(r"F1 2[45]")
    for e in games.entries():
        for f in e.features:
            assert len(f.short) <= 32, (e.id, f.id, f.short)
            assert f.reason.endswith("."), (e.id, f.id)
            plain = names.sub("", f.reason)
            assert not re.search(r"\bF\d+\b|_|\bNone\b", plain), (e.id, f.id, f.reason)
            if f.status == "supported":
                assert f.short == ""
            if f.status == "not_sent":
                assert f.short == f"Not sent by {e.text_name}"


# ---------------------------------------------------------------------------------------------- code facts
def test_code_fact_estimated_gt7_distance() -> None:
    from pitwall.adapters.gt7.adapter import GT7_INFO

    assert {("gt7", "lap_distance_m")} == games.ESTIMATED
    assert "derived" in GT7_INFO.fields["lap_distance_m"].source
    assert (
        set(games.DISTANCE_REASON)
        == {g for g in games.DISTANCE_REASON}
        == {
            "gt7",
            "forza_motorsport",
            "forza_horizon",
            "ac",
        }
    )


def test_code_fact_not_implemented() -> None:
    from pitwall.adapters.f1 import packets as P
    from pitwall.adapters.forza.adapter import FORZA_HORIZON_INFO, FORZA_MOTORSPORT_INFO
    from pitwall.adapters.gt7.adapter import GT7_INFO

    damage_fields = {name for name, _ in P.CAR_DAMAGE.fields}
    assert "frontLeftWingDamage" in damage_fields and "tyresWear" in damage_fields  # F1 sends damage ...
    assert not any("damage" in f.name or "wing" in f.name for f in dc_fields(CarFrame))  # ... Pitwall maps none
    assert GT7_INFO.fields["fuel_litres"].level is S.UNVERIFIED
    assert GT7_INFO.fields["ers_store_j"].level is S.UNVERIFIED
    for info in (FORZA_MOTORSPORT_INFO, FORZA_HORIZON_INFO):
        assert "fraction" in info.fields["fuel_kg"].source
    assert "gear ratios" in GT7_INFO.fields["setup"].source  # GT7 sends part of its setup ...
    from pitwall.adapters.gt7 import adapter as gt7_adapter
    from pitwall.adapters.gt7 import packets as gt7_packets

    assert "gear_ratios" in {name for name, _ in gt7_packets.BASE_FIELDS}
    assert "CarSetup" not in Path(gt7_adapter.__file__).read_text(encoding="utf-8")  # ... Pitwall emits no setup
    assert set(games.NOT_IMPLEMENTED) == {
        ("f1_25", "damage"),
        ("gt7", "fuel"),
        ("forza_motorsport", "fuel"),
        ("forza_horizon", "fuel"),
        ("gt7", "ers"),
        ("gt7", "setup_telemetry"),
    }


def test_code_fact_partial() -> None:
    from pitwall.adapters.f1 import packets as P
    from pitwall.adapters.f1.adapter import _HANDLERS
    from pitwall.adapters.forza.adapter import FORZA_HORIZON_INFO

    assert P.PacketId.FINAL_CLASSIFICATION not in _HANDLERS
    assert P.PacketId.SESSION in _HANDLERS
    assert any("free roam" in n.lower() and "no laps" in n.lower() for n in FORZA_HORIZON_INFO.notes)


def test_code_fact_sheets_outlines_and_setups() -> None:
    from pitwall import trackdata
    from pitwall.analysis.track_geometry import OUTLINE_GAMES
    from pitwall.analysis.track_identity import load_sheets
    from pitwall.carsetup.context import F1_GAMES

    sheets = [s for fam in trackdata.sheet_families() for s in load_sheets(fam)]
    verified = [s for s in sheets if any(t.verified for t in s.turns)]  # track_identity shows verified turns only
    assert {g for s in verified for g in s.games} == games.official_name_games() == {"f1_25"}
    f1 = [s for s in sheets if "f1_25" in s.games]
    f1_verified = [s for s in verified if "f1_25" in s.games]
    assert 0 < len(f1_verified) < len(f1)  # some circuits: partial, never "supported"
    assert games.official_name_sheets("f1_25", "2025") == (len(f1_verified), len(f1))
    assert all(s.verified_formats == (2025,) for s in f1_verified)  # format 2026 counts as unchecked
    assert games.official_name_sheets("f1_25", "2026") == (0, len(f1))
    names = games.entry("f1_25:ps5").feature("official_corner_names")  # type: ignore[union-attr]
    assert names.status == "partial" and "some F1 25 circuits" in names.reason
    assert games.entry("f1_25_2026:pc").feature("official_corner_names").status == "not_implemented"  # type: ignore[union-attr]
    assert games.outline_games() == OUTLINE_GAMES
    assert games.setup_games() == F1_GAMES


# Evidence-backed changes since the golden snapshot, each listed here so that no other row or field can change silently.
# 2026-10-11, the owner's PS5 (live run + recordings, tests/recorded/test_gt7_ps5_real.py): the GT7 row split into a
# live-validated PS5 row and a PS4 row that stays community-documented; these GT7 fields became recorded-validated and
# every changed GT7 field source carries that dated evidence.
GT7_EVIDENCE = "PS5 recordings 2026-10-11"
GT7_ROWS = {"gt7_ps5": ("PS5", "live_validated"), "gt7_ps4": ("PS4", "community_documented")}
GT7_OLD_PLATFORM = "PS5 / PS4"
GT7_RECORDED = {
    "speed_kph",
    "throttle",
    "brake",
    "gear",
    "rpm",
    "pos_x_m",
    "pos_y_m",
    "pos_z_m",
    "vel_x_mps",
    "session_time_s",
    "frame_id",
    "lap_number",
    "lap_distance_m",
    "current_lap_time_ms",
    "last_lap_time_ms",
    "tyre_surface_temp_c",
    "track_length_m",
    "car_id",
    "total_laps",
    "best_lap_ms",
}


def _old_key(r: Any) -> tuple[str, str]:
    """A current row's key in the golden snapshot (the GT7 rows were one ``PS5 / PS4`` row then)."""
    return (r.game, GT7_OLD_PLATFORM if r.key in GT7_ROWS else r.platform)


def test_adapter_declarations_added_for_documented_absences() -> None:
    old = {(r["game"], r["platform"]): r for r in json.loads(GOLDEN_MATRIX.read_text(encoding="utf-8"))}
    added = {
        # session_type/buttons: game selection; the MotionEx slip and yaw channels: technique analysis;
        # ai_difficulty/lap_history: pace vs AI difficulty; race_timing/tyre_sets: race strategy;
        # drs_allowed/drs_activation_m: F2 support (the engineer's DRS answers)
        Game.F1_25: {
            "drs_allowed",
            "drs_activation_m",
            "session_type",
            "buttons",
            "yaw_rate_rps",
            "body_slip_rad",
            "wheel_slip_ratio",
            "wheel_slip_angle_rad",
            "ai_difficulty",
            "lap_history",
            "race_timing",
            "tyre_sets",
        },
        Game.GT7: {"drs_open", "ers_store_j", "track_zones", "field_samples", "damage", "buttons"},
        Game.FORZA_MOTORSPORT: {"drs_open", "ers_store_j", "damage", "track_zones", "field_samples", "buttons"},
        Game.FORZA_HORIZON: {"drs_open", "ers_store_j", "damage", "track_zones", "field_samples", "buttons"},
        Game.AC: {"drs_open", "ers_store_j", "damage", "track_zones", "field_samples", "buttons"},
    }
    for r in PLANNED:
        before = old[_old_key(r)]["fields"]
        if r.adapter_game is None or before is None:
            continue
        now = set(ADAPTER_INFOS[r.adapter_game].fields)
        assert now - set(before) == added[r.adapter_game], r.key
        for k, v in before.items():  # no level was upgraded or changed, except the listed evidence-backed upgrades
            fs = ADAPTER_INFOS[r.adapter_game].fields[k]
            if r.adapter_game is Game.GT7 and k in GT7_RECORDED:
                assert (v["level"], fs.level) == ("community_documented", S.RECORDED_VALIDATED), k
                assert GT7_EVIDENCE in fs.source, k
            elif r.adapter_game is Game.GT7 and fs.source != v["source"]:
                assert fs.level.value == v["level"] and GT7_EVIDENCE in fs.source, k  # the note gained evidence
            else:
                assert (fs.level.value, fs.source) == (v["level"], v["source"]), (r.key, k)
    for g in (Game.GT7, Game.FORZA_MOTORSPORT, Game.FORZA_HORIZON, Game.AC):
        new = {k: ADAPTER_INFOS[g].fields[k].level for k in added[g]}
        expected_unverified = {"ers_store_j"} if g is Game.GT7 else set()
        assert {k for k, v in new.items() if v is S.UNVERIFIED} == expected_unverified, g
        assert {k for k, v in new.items() if v is S.UNSUPPORTED} == added[g] - expected_unverified, g


def test_capability_matrix_golden() -> None:
    old = {(r["game"], r["platform"]): r for r in json.loads(GOLDEN_MATRIX.read_text(encoding="utf-8"))}
    new = json.loads(json.dumps(capability_matrix()))
    assert len(old) + 1 == len(new) == len(PLANNED)  # the GT7 row split in two (see GT7_ROWS)
    for r, n in zip(PLANNED, new, strict=True):
        o = old[_old_key(r)]
        n = dict(n)
        assert n.pop("key") == r.key and isinstance(n.pop("platform_ids"), list)
        classes = n.pop("car_classes", None)  # F2 support: the car class rows ride the F1 rows (an addition)
        assert (classes is not None) is (r.adapter_game is Game.F1_25), r.key
        if n["fields"] is not None:  # section 2.2 declarations are the only additions (levels: the test above)
            n["fields"] = {k: v for k, v in n["fields"].items() if k in o["fields"]}
        o = {**o, "notes": o["notes"].replace(" Enable on the Connect page.", "")}  # stale since game selection
        if r.key in GT7_ROWS:
            platform, status = GT7_ROWS[r.key]
            assert (n.pop("platform"), n.pop("status"), o.pop("platform"), o.pop("status")) == (
                platform,
                status,
                GT7_OLD_PLATFORM,
                "community_documented",
            )
            assert "Synthetic tests only" in o.pop("notes") and "Synthetic tests only" not in n["notes"]
            assert ("2026-10-11" in n.pop("notes")) is (r.key == "gt7_ps5")
            assert set(o.pop("fields")) == set(n.pop("fields"))
        assert o == n, o["game"]
    keys = [r["key"] for r in new]
    assert keys == [r.key for r in PLANNED] and len(set(keys)) == len(keys)


# ---------------------------------------------------------------------------------------------- resolve
@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (("f1_25", "ps5", "2025", None), "f1_25:ps5"),
        (("f1_25", "ps5", "2026", None), "f1_25_2026:ps5"),
        (("f1_25", "unknown", "2025", "f1_25:pc"), "f1_25:pc"),
        (("f1_25", "unknown", "2025", None), "f1_25:xbox"),  # ambiguous platform: the weakest main entry
        (("gt7", "unknown", None, "gt7:ps5"), "gt7:ps5"),
        (("gt7", "unknown", None, None), "gt7:ps4"),  # GT7 sends no platform: the weakest of PS5 (live) / PS4
        (("gt7", None, None, "f1_25:ps5"), "gt7:ps4"),  # a preference that is not a candidate is ignored
        (("ac", "ps4", None, None), "ac:ps4"),
        (("ac", None, None, None), "ac:ps4"),  # weakest of PS5 (recorded) / PS4 / PC (community): catalogue order
        (("ac", None, None, None, "pc"), "ac:pc"),  # the configured platform picks the entry
        (("ac", None, None, "f1_25:ps5", "ps5"), "ac:ps5"),
        (("ac", None, None, "ac:ps5", "pc"), "ac:pc"),  # the input is set to PC: that is the entry in use
        (("forza_horizon", None, None, None), "forza_horizon:xbox"),  # FH on PS5 is in "more": never a guess
        (("forza_horizon", "unknown", None, None), "forza_horizon:xbox"),
        (("acc", "pc", None, None), None),  # not implemented: never a detection
        (("synthetic", None, None, None), None),
        ((None, None, None, None), None),
    ],
)
def test_resolve(args: tuple[Any, ...], expected: str | None) -> None:
    assert games.resolve(*args) == expected


def test_entry_for_session_rows() -> None:
    row = {"game": "f1_25", "platform": "ps5", "info": {"packet_format": 2026}}
    assert games.entry_for_session(row).id == "f1_25_2026:ps5"  # type: ignore[union-attr]
    assert games.entry_for_session({"game": "ac", "platform": "pc", "info": {}}).id == "ac:pc"  # type: ignore[union-attr]
    assert games.entry_for_session({"game": "synthetic"}) is None
    assert games.entry_for_session(None) is None


def test_parse_selection_is_lenient(caplog: pytest.LogCaptureFixture) -> None:
    assert games.parse_selection({}) is None and games.parse_selection(None) is None
    sel = games.parse_selection({"selected": "gt7:ps5", "since_unix": 12.5, "source": "cli"})
    assert sel == games.Selection("gt7:ps5", 12.5, "cli")
    assert games.parse_selection({"selected": "fm7:xbox", "since_unix": 1.0}) is None
    assert "fm7:xbox" in caplog.text
    odd = games.parse_selection({"selected": "ac:ps5", "since_unix": "x", "source": "hacker"})
    assert odd == games.Selection("ac:ps5", 0.0, "dashboard")
    # a driver's usual game names the driver (plan 1.3); only that source keeps an id, and an older file has none
    seat = games.parse_selection(
        {"selected": "gt7:ps5", "since_unix": 3.0, "source": "driver_default", "by_driver_id": 2}
    )
    assert seat == games.Selection("gt7:ps5", 3.0, "driver_default", 2)
    assert games.parse_selection(seat.section()) == seat
    assert games.parse_selection(
        {"selected": "gt7:ps5", "since_unix": 3.0, "source": "driver_default"}
    ) == games.Selection("gt7:ps5", 3.0, "driver_default", None)
    for bad in (True, "2", 2.5):
        got = games.parse_selection({"selected": "gt7:ps5", "source": "driver_default", "by_driver_id": bad})
        assert got is not None and got.by_driver_id is None
    cli = games.parse_selection({"selected": "gt7:ps5", "source": "cli", "by_driver_id": 2})
    assert cli is not None and cli.by_driver_id is None
    assert games.new_selection("gt7:ps5", "dashboard", by_driver_id=2).by_driver_id is None
    assert "by_driver_id" not in games.new_selection("gt7:ps5", "cli").section()


# ---------------------------------------------------------------------------------------------- capability sentences
def test_capability_sentences_and_only() -> None:
    ac = games.entry("ac:ps5")
    gt7 = games.entry("gt7:ps5")
    f1 = games.entry("f1_25:ps5")
    assert games.capability_sentence(ac, games.INTENT_FEATURES["tyres"]) == (
        "Assetto Corsa doesn't send tyre temperatures, tyre wear, tyre pressures or brake temperatures."
    )
    assert games.capability_sentence(gt7, games.INTENT_FEATURES["tyres"]) == (
        "GT7 doesn't send tyre wear, tyre pressures or brake temperatures."
    )
    assert games.capability_sentence(f1, games.INTENT_FEATURES["tyres"]) is None
    assert games.capability_only("tyres", ac) and not games.capability_only("tyres", gt7)
    assert games.capability_only("fuel", gt7)  # not read yet: still a known fact, not data
    assert not games.capability_only("setup", ac)  # setup keeps its technique-first answer
    assert not games.capability_only("tyres", None)
    assert games.capability_only("damage", f1) and not games.capability_only("weather", f1)
    acc = games.entry("acc:ps5")
    assert games.capability_sentence(acc, ["fuel", "tyre_wear"]) == "ACC on PS5 has no telemetry output."
    assert [g for g, *_ in games.capability_facts(f1)] == ["damage"]  # type: ignore[arg-type]


def test_games_response_is_json_and_covers_every_entry() -> None:
    body = json.loads(json.dumps(games.games_response()))
    assert body["schema"] == 1
    assert [e["id"] for e in body["entries"]] == [e.id for e in games.entries()]
    assert set(body["support_words"]) == {lvl.value for lvl in SupportLevel}
    assert all("fields" not in e and "guide" not in e for e in body["entries"])
    assert all(len(e["features"]) == 23 for e in body["entries"])


# ---------------------------------------------------------------------------------------------- review fixes
RESEARCH = Path(__file__).resolve().parents[2] / "docs" / "research" / "forza-ac-acc-iracing.md"
# LOCAL_ONLY["ac_pc"] feature -> what AC's shared memory exposes for it (research doc section 2.1)
AC_SHARED_MEMORY = {
    "sectors": "currentSectorIndex, lastSectorTime",
    "flags": "flag",
    "fuel": "fuel",
    "tyre_temps": "tyreTempI/M/O[4]",
    "tyre_wear": "tyreWear[4]",
    "tyre_pressures": "wheelsPressure[4]",
    "brake_temps": "brakeTemp[4]",
    "damage": "carDamage[5]",
    "ers": "ERS/KERS fields",
    "drs": "drs",
    "weather": "airTemp, roadTemp",
    "session_info": "session type",
}


def test_ac_pc_local_only_is_pinned_to_the_research() -> None:
    text = RESEARCH.read_text(encoding="utf-8")
    shared = text[text.index("### 2.1 Shared memory") : text.index("### 2.2")]
    assert "Shared memory does not exist on consoles" in text
    assert set(games.LOCAL_ONLY) == {"ac_pc"} and set(games.LOCAL_ONLY["ac_pc"]) == set(AC_SHARED_MEMORY)
    for fid, token in AC_SHARED_MEMORY.items():
        assert token in shared, (fid, token)
    pc, ps5 = games.entry("ac:pc"), games.entry("ac:ps5")
    assert pc is not None and ps5 is not None
    for fid in AC_SHARED_MEMORY:
        f = pc.feature(fid)
        assert f.status == "not_implemented" and f.short == "Not in Pitwall yet", fid
        assert "only in its shared memory" in f.reason and "Assetto Corsa on PC" in f.reason, fid
        assert ps5.feature(fid).status == "not_sent", fid  # consoles have no shared memory
    assert pc.feature("weather").reason.startswith("Assetto Corsa on PC has air and track temperatures only")
    assert not [f.id for f in pc.features if f.status == "not_sent" and f.id in AC_SHARED_MEMORY]
    assert games.capability_sentence(pc, games.INTENT_FEATURES["tyres"]) == (
        "Assetto Corsa on PC has tyre temperatures, tyre wear, tyre pressures and brake temperatures only in its "
        "shared memory, which Pitwall can't read yet (it uses the UDP remote telemetry)."
    )
    assert games.capability_only("tyres", pc)  # still a known fact: no LLM, no estimate


def test_gt7_setup_wording() -> None:
    gt7 = games.entry("gt7:ps5")
    assert gt7 is not None
    f = gt7.feature("setup_telemetry")
    assert f.status == "not_implemented" and "only its gear ratios" in f.reason and "doesn't send" not in f.reason


def test_where_has_no_double_brackets() -> None:
    assert games.entry("ac:ps5").where == "Assetto Corsa on PS5 (PS4 version)"  # type: ignore[union-attr]
    assert games.entry("gt7:ps5").where == "Gran Turismo 7 (PS5)"  # type: ignore[union-attr]
    assert games.entry("forza_motorsport:pc").where == "Forza Motorsport (2023) on PC"  # type: ignore[union-attr]
    m = games.mismatch("ac:ps5", {"real": True, "status": "live", "adapter_game": "f1_25", "entry_id": "f1_25:ps5"})
    assert m is not None and m["text"] == "Receiving F1 25, but Assetto Corsa on PS5 (PS4 version) is selected."


def test_history_suggestion_skips_replays_and_synthetic() -> None:
    rows = [
        {"game": "ac", "platform": "ps5", "source": "replay:ac_silverstone.pwcap", "synthetic": False},
        {"game": "f1_25", "platform": "pc", "source": "udp:20777", "synthetic": True},
        {"game": "gt7", "platform": "unknown", "source": "udp:33740", "synthetic": False},
    ]
    assert games.history_suggestion(rows) == {
        "id": "gt7:ps4",  # GT7 sends no platform: the weakest entry it could be (PS4: untested; PS5: live)
        "source": "history",
        "text": "You last drove Gran Turismo 7.",
    }


def test_a_paused_mismatch_stays_and_old_data_keeps_only_its_detection() -> None:
    args = ("gt7:ps5", "f1_25", "ps5", "2025", True)
    assert games.snapshot_block(*args, "stale")["mismatch"]["kind"] == "game"  # type: ignore[index]
    old = games.snapshot_block(*args, "stale", stale_mismatch=False)
    assert old["mismatch"] is None and old["effective_id"] == "f1_25:ps5"  # the old data is still that game's
    assert games.snapshot_block(*args, "no_data")["detected"] is None
