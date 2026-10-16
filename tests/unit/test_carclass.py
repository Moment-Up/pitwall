"""Car classes (``pitwall.carclass``): the formula table, the team-id fallback, labels and the SQL twin in repo.

F2 support: a session's class is worked out from ``SessionInfo.formula`` (EA spec 8.12) and the car id, never stored.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from pitwall import carclass as C
from pitwall.adapters.f1 import enums
from pitwall.model.telemetry import Game, SessionInfo, SessionType
from pitwall.storage import repo
from pitwall.storage.db import Database


@pytest.mark.parametrize(
    ("formula", "car", "fmt", "cls", "family", "certain"),
    [
        ("F2", "f1:team:158", 2025, "f2", "f2", True),
        ("F2", "f1:team:214", 2025, "f2", "f2", True),
        ("F2", None, 2025, "f2", "f2", True),
        ("F1 Modern", "f1:team:8", 2025, "f1_2025", "f1", True),
        ("F1 World", "f1:team:41", 2025, "f1", "f1", False),  # the generic car in format 2025: generation unknown
        ("F1 Generic", "f1:team:41", 2025, "f1", "f1", False),
        ("Esports", "f1:team:3", 2025, "f1_2025", "f1", True),
        ("F1 Elimination", "f1:team:2", 2026, "f1_2025", "f1", True),
        ("F1 26", "f1:team:476", 2026, "f1_2026", "f1", True),
        ("F1 Classic", "f1:team:1", 2025, "f1_classic", "other", True),
        ("Beta", "f1:team:1", 2025, "other", "other", True),
        # no formula stored (older rows): the spec's team ids
        (None, "f1:team:158", 2025, "f2", "f2", True),
        (None, "f1:team:214", 2025, "f2", "f2", True),
        (None, "f1:team:470", 2026, "f2", "f2", True),
        (None, "f1:team:494", 2026, "f2", "f2", True),
        (None, "f1:team:8", 2025, "f1_2025", "f1", True),
        (None, "f1:team:41", 2025, "f1", "f1", False),
        (None, "f1:team:480", 2026, "f1_2026", "f1", True),
        (None, "f1:team:187", 2025, "f1", "f1", False),  # a '24 F1 team: an F1 car, generation not told
    ],
)
def test_formula_table_and_team_fallback(
    formula: str | None, car: str | None, fmt: int, cls: str, family: str, certain: bool
) -> None:
    c = C.classify("f1_25", formula, car, fmt)
    assert c is not None and (c.id, c.family, c.certain) == (cls, family, certain)
    assert C.family_of("f1_25", formula, car, fmt) == family


def test_unknown_stays_unknown() -> None:
    assert C.classify("f1_25", None, None, 2025) is None  # neither a formula nor a team
    assert C.classify("f1_25", None, "f1:team:300", 2025) is None  # a team id the spec does not list
    for game in ("gt7", "forza_motorsport", "ac", "acc", None):
        assert C.classify(game, "F2", "f1:team:158", 2025) is None  # other games never get a class


def test_acc_cars_have_no_class_and_keep_their_names() -> None:
    """ACC (feat/acc): Kunos' car ids say GT3 / GT4 / Cup ..., but Pitwall has no class for them (the classes, their
    track models and the brake prior are F1's): no class, no chip, no family; the car's Appendix 2 name is the label
    and the session's own name (the adapter's words) is the session label."""
    row = {
        "game": "acc",
        "car_id": "acc:car:mclaren_720s_gt3",
        "car_name": "McLaren 720S GT3 2019",
        "session_type": "race",
        "session_type_raw": "Race",
        "info": {"acc_status": "live"},
    }
    assert C.classify_row(row) is None and C.family_of_row(row) is None
    assert C.session_fields(row) == {"car_class": None, "car_label": "McLaren 720S GT3 2019", "session_label": "Race"}
    unknown = {**row, "car_name": "ford_mustang_gt3", "session_type_raw": "unknown_42", "session_type": "unknown"}
    assert C.session_fields(unknown)["car_label"] == "ford_mustang_gt3"  # a car after v1.8.12: the game's own id
    assert C.session_fields(unknown)["session_label"] is None  # never "unknown_42"


def test_class_dict_and_evidence() -> None:
    f2 = C.classify("f1_25", "F2", "f1:team:158", 2025)
    assert f2 is not None and f2.to_dict() == {
        "id": "f2",
        "family": "f2",
        "label": "F2",
        "formula": "F2",
        "certain": True,
        "has_ers": False,
        "chip": True,
        "evidence": "recorded_validated",
        "notes": ["F2 cars have no ERS: F1 25 sends 0 for them."],
    }
    mclaren = C.classify("f1_25", "F1 Modern", "f1:team:8", 2025)
    assert mclaren is not None and mclaren.to_dict()["evidence"] == "live_validated" and not mclaren.chip
    classic = C.classify("f1_25", "F1 Classic", None, 2025)
    assert classic is not None and classic.chip and classic.has_ers is None
    beta = C.classify("f1_25", "Beta", None, 2025)
    assert beta is not None and beta.label is None and not beta.chip and beta.to_dict()["evidence"] == "unverified"


@pytest.mark.parametrize(
    ("formula", "car", "name", "fmt", "label"),
    [
        ("F2", "f1:team:158", "Art GP '24", 2025, "F2 · Art GP '24"),
        ("F2", "f1:team:214", "Unknown team (id 214)", 2025, "F2 · Hitech '25"),
        ("F2", "f1:team:214", "team_214", 2025, "F2 · Hitech '25"),  # an older row's raw name
        (None, "f1:team:214", "Unknown team (id 214)", 2025, "F2 · Hitech '25"),
        ("F2", "f1:team:214", "Unknown team (id 214)", 2026, "F2 car"),  # 209-219 are named in format 2025 only
        ("F2", "f1:team:470", "Hitech '25", 2026, "F2 · Hitech '25"),
        ("F2", None, None, 2025, "F2 car"),
        ("F2", "f1:team:300", "Unknown team (id 300)", 2025, "F2 car"),
        ("F1 Classic", "f1:team:1", "Ferrari", 2025, "Classic F1 · Ferrari"),
        ("F1 Classic", None, None, 2025, "Classic F1 car"),
        ("F1 Modern", "f1:team:8", "McLaren", 2025, "McLaren"),
        ("F1 World", "f1:team:41", "F1 Generic", 2025, "F1 Generic"),
        ("F1 Modern", "f1:team:300", "Unknown team (id 300)", 2025, None),
    ],
)
def test_car_labels_never_show_a_raw_id(
    formula: str | None, car: str | None, name: str | None, fmt: int, label: str | None
) -> None:
    cls = C.classify("f1_25", formula, car, fmt)
    got = C.car_label(cls, name, car, fmt)
    assert got == label
    if got is not None:
        assert "team_" not in got and "f1:team" not in got and "Unknown team" not in got


def test_session_labels() -> None:
    f2 = C.classify("f1_25", "F2", "f1:team:158", 2025)
    f1 = C.classify("f1_25", "F1 Modern", "f1:team:8", 2025)
    sprint_weekend, feature_only = [15, 16], [9, 16]  # recorded: Melbourne; Sakhir and Jeddah
    assert C.session_label(f2, "Race", weekend=sprint_weekend) == "Sprint race"  # a "Race 2" follows
    assert C.session_label(f2, "Race 2", weekend=sprint_weekend) == "Feature race"
    assert C.session_label(f2, "Race 2", weekend=feature_only) == "Feature race"
    assert C.session_label(f2, "Race 2") == "Feature race"  # the 60-minute race with feature points
    # a race-only weekend, or a structure not known (older rows): the game's own name, never a guessed sprint
    assert C.session_label(f2, "Race", weekend=[15]) == "Race" and C.session_label(f2, "Race") == "Race"
    # the F1 game's names in sentence case, as Drive writes them
    assert C.session_label(f2, "One-Shot Qualifying") == "One-shot qualifying"
    assert C.session_label(f1, "Time Trial") == "Time trial" and C.session_label(f1, "Practice 1") == "Practice 1"
    assert C.session_label(f1, "Race 2", weekend=sprint_weekend) == "Race 2"  # only F2 renames the races
    assert C.session_label(None, "Lobby race") == "Lobby race"  # another game's own name: unchanged
    assert C.session_label(None, None, "race") == "Race"  # GT7: no raw name
    assert C.session_label(None, None, "unknown") is None and C.session_label(f2, "Unknown") is None
    assert C.f2_race_kind(f2, "Race 2") == "feature" and C.f2_race_kind(f2, "Race", sprint_weekend) == "sprint"
    assert C.f2_race_kind(f2, "Race") is None and C.f2_race_kind(f2, "Race", [15]) is None
    assert C.f2_race_kind(f1, "Race", sprint_weekend) is None
    assert C.weekend_types([15, 16]) == (15, 16) and C.weekend_types([]) is None and C.weekend_types("x") is None


def test_f2_evidence_per_variant() -> None:
    """Only the recorded F2 variants (UDP format 2025, team ids 158-168 and 209-219) are recorded_validated."""
    for car, fmt in (("f1:team:158", 2025), ("f1:team:214", 2025), (None, 2025), ("f1:team:214", None)):
        cls = C.classify("f1_25", "F2", car, fmt)
        assert cls is not None and cls.evidence == "recorded_validated", (car, fmt)
    for car, fmt in (("f1:team:490", 2026), ("f1:team:470", 2026), ("f1:team:158", 2026), ("f1:team:494", None)):
        cls = C.classify("f1_25", "F2", car, fmt)
        assert cls is not None and cls.evidence == "spec_implemented", (car, fmt)
    assert C.classify("f1_25", "F2", "f1:team:490", 2026) == C.CarClass("f2", "F2")  # team / format: not identity


def test_compound_words() -> None:
    assert C.compound_words("super_soft") == "super soft"
    assert C.compound_words("medium") == "medium" and C.compound_words(None) is None


def test_info_and_row_fields_agree() -> None:
    info = SessionInfo(
        game=Game.F1_25,
        car_id="f1:team:214",
        car_name="Unknown team (id 214)",
        formula="F2",
        session_type=SessionType.RACE,
        session_type_raw="Race",
        extra={"packet_format": 2025, "weekend_structure": [15, 16]},
    )
    row = {
        "game": "f1_25",
        "car_id": "f1:team:214",
        "car_name": "Unknown team (id 214)",
        "session_type": "race",
        "session_type_raw": "Race",
        "info": {"formula": "F2", "packet_format": 2025, "weekend_structure": [15, 16]},
    }
    assert C.info_fields(info) == C.session_fields(row)
    assert C.session_fields(row)["car_label"] == "F2 · Hitech '25"
    assert C.session_fields(row)["session_label"] == "Sprint race"
    assert C.info_fields(None) == {"car_class": None, "car_label": None, "session_label": None}


def test_observed_f2_teams_follow_the_spec_order() -> None:
    """Ids 209-219 (observed in format 2025) are named after EA's 465-475, in the same order, and none of them is in
    the spec's own table (the protocol test keeps that table exact)."""
    assert set(enums.OBSERVED_F2_TEAMS_FMT2025) == set(range(209, 220))
    assert not set(enums.OBSERVED_F2_TEAMS_FMT2025) & set(enums.TEAMS)
    assert [enums.OBSERVED_F2_TEAMS_FMT2025[209 + k] for k in range(11)] == [enums.TEAMS[465 + k] for k in range(11)]
    assert enums.team_name(214) == "Unknown team (id 214)"  # the adapter's car_name stays the spec's fallback


# ---------------------------------------------------------------------------------------------- repo's SQL twin
def _rows() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    formulas = [None, "F2", "F1 Modern", "F1 World", "F1 26", "F1 Classic", "Beta", "Esports"]
    cars = [None, "f1:team:8", "f1:team:41", "f1:team:158", "f1:team:214", "f1:team:470", "f1:team:494"]
    cars += ["f1:team:480", "f1:team:300", "f1:team:187"]
    for game in ("f1_25", "gt7"):
        for f in formulas:
            for car in cars:
                out.append({"game": game, "formula": f, "car_id": car})
    return out


def test_family_sql_matches_the_module(tmp_path: Path) -> None:
    db = Database(tmp_path / "x.sqlite3")
    with closing(db.connect()) as c:
        c.row_factory = sqlite3.Row
        for i, r in enumerate(_rows()):
            info = {"formula": r["formula"]} if r["formula"] else {}
            repo.insert_session(c, f"s{i}", r["game"], "udp:20777", False, None, None)
            c.execute("UPDATE sessions SET car_id=?, info=? WHERE id=?", (r["car_id"], json.dumps(info), f"s{i}"))
        got = {row["id"]: row["fam"] for row in c.execute(f"SELECT s.id, {repo.family_sql()} AS fam FROM sessions s")}
    for i, r in enumerate(_rows()):
        assert got[f"s{i}"] == C.family_of(r["game"], r["formula"], r["car_id"], 2025), r
