"""Setup engineer (F1 25): which symptoms qualify, one-parameter trial steps on the real catalogue, range ends,
conflicts, unknown car format / setup, running experiments, never-suggested parameters, and the experiments flow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pitwall.carsetup import experiments
from pitwall.carsetup.catalog import Catalog, load_catalog
from pitwall.carsetup.recommend import CAVEAT
from pitwall.model.telemetry import Game, SessionInfo
from pitwall.storage import repo
from pitwall.storage.db import Database, DbWriter
from pitwall.technique.balance import BalanceSymptom
from pitwall.technique.setup_map import (
    CANDIDATES,
    FORMAT_UNKNOWN,
    LOCKUP_CANDIDATES,
    NEVER_SUGGESTED,
    NOTE_BRAKING_ASSIST,
    LockupSymptom,
    qualifies,
    suggest,
)


@pytest.fixture(scope="module")
def cat() -> Catalog:
    return load_catalog()


def _sym(
    phase: str = "mid",
    cls: str = "understeer",
    verdict: str = "car",
    corners: tuple[str, ...] = ("T4", "T11"),
    speeds: tuple[str, ...] = ("medium",),
    laps: int = 3,
    median: float = 4.5,
    with_braking: bool = False,
    slide_every_lap: bool = False,
) -> BalanceSymptom:
    return BalanceSymptom(
        id=f"{phase}-{cls}-{verdict}",
        phase=phase,  # type: ignore[arg-type]
        cls=cls,  # type: ignore[arg-type]
        verdict=verdict,  # type: ignore[arg-type]
        speed_class="mixed" if len(speeds) > 1 else speeds[0],  # type: ignore[arg-type]
        corners=list(corners),
        corner_labels=list(corners),
        laps=laps,
        laps_total=laps,
        median_slip_diff_deg=median,
        with_braking=with_braking,
        with_wheelspin=False,
        text="Mid-corner understeer at T4 and T11.",
        text_simple="At T4 and T11 the car pushed wide (understeer) mid-corner on 3 of 3 laps, even on your best lap.",
        corner_speed_classes=set(speeds),
        per_corner_laps=dict.fromkeys(corners, laps),
        slide_every_lap=slide_every_lap,
    )


STORED = {
    "front_arb": 9.0,
    "rear_arb": 10.0,
    "front_wing": 30.0,
    "rear_wing": 20.0,
    "diff_on_throttle": 60.0,
    "diff_off_throttle": 50.0,
    "brake_bias": 56.0,
    "brake_pressure": 100.0,
    "rear_suspension": 10.0,
}


def test_qualification_rules() -> None:
    assert qualifies(_sym())  # two corners
    assert not qualifies(_sym(verdict="driving"))  # the best lap did not have it: the driving
    assert not qualifies(_sym(corners=("T3",), laps=2, median=5.8))
    assert qualifies(_sym(corners=("T3",), laps=3))
    assert qualifies(_sym(corners=("T3",), laps=2, median=6.6))  # strong
    assert qualifies(_sym(cls="oversteer", corners=("T8",), laps=2, median=-0.5, slide_every_lap=True))
    assert not qualifies(_sym(cls="oversteer", corners=("T8",), laps=2, median=-1.5))


def test_mid_understeer_moves_the_front_bar_two_clicks_softer(cat: Catalog) -> None:
    eng = suggest([_sym()], [], cat=cat, car_format="f1_2025", stored=STORED)
    assert eng.caveat == CAVEAT and eng.setup_known
    first = eng.suggestions[0]
    assert (first.parameter, first.direction, first.from_value, first.to_value) == ("front_arb", "lower", 9.0, 7.0)
    assert first.steps == 2 and first.blocked is None and first.rank == 1
    assert first.effect == cat.param("front_arb").lower  # type: ignore[union-attr]
    assert first.hypothesis.startswith("Front Anti-Roll Bar 9 → 7: At T4 and T11")
    assert len(first.hypothesis) <= 500 and "Expected:" in first.hypothesis
    assert [s.parameter for s in eng.suggestions] == ["front_arb", "front_wing", "rear_arb"]
    diff = suggest([_sym(phase="entry")], [], cat=cat, car_format="f1_2025", stored=STORED).suggestions[0]
    assert (diff.parameter, diff.from_value, diff.to_value) == ("diff_off_throttle", 50.0, 40.0)  # 10 %


def test_speed_class_and_braking_filter_the_candidates(cat: Catalog) -> None:
    fast = suggest([_sym(speeds=("fast",))], [], cat=cat, car_format="f1_2025", stored=STORED)
    assert [s.parameter for s in fast.suggestions] == ["front_wing"]  # anti-roll bars are for slow/medium corners
    entry = suggest([_sym(phase="entry", speeds=("slow",))], [], cat=cat, car_format="f1_2025", stored=STORED)
    assert "brake_bias" not in [s.parameter for s in entry.suggestions]  # only with braking
    braking = suggest(
        [_sym(phase="entry", speeds=("slow",), with_braking=True)], [], cat=cat, car_format="f1_2025", stored=STORED
    )
    assert [s.parameter for s in braking.suggestions][:2] == ["diff_off_throttle", "brake_bias"]
    assert all(len(v) for v in CANDIDATES.values())


def test_range_ends_are_blocked(cat: Catalog) -> None:
    at_min = suggest([_sym()], [], cat=cat, car_format="f1_2025", stored={**STORED, "front_arb": 1.0})
    s = at_min.suggestions[0]
    assert s.parameter == "front_arb" and s.to_value is None and s.blocked and "minimum" in s.blocked
    near = suggest([_sym()], [], cat=cat, car_format="f1_2025", stored={**STORED, "front_arb": 2.0})
    assert near.suggestions[0].to_value == 1.0  # snapped to the range


def test_conflicting_directions_drop_the_parameter(cat: Catalog) -> None:
    us = _sym(phase="mid", cls="understeer", speeds=("slow",))
    os_ = _sym(phase="mid", cls="oversteer", speeds=("slow",), corners=("T2", "T5"))
    eng = suggest([us, os_], [], cat=cat, car_format="f1_2025", stored=STORED)
    assert "rear_arb" not in [s.parameter for s in eng.suggestions]  # higher for one, lower for the other
    assert eng.note and "Rear Anti-Roll Bar" in eng.note


def test_unknown_car_format_and_setup_leave_no_target(cat: Catalog) -> None:
    unknown_fmt = suggest([_sym()], [], cat=cat, car_format=None, stored=STORED)
    assert all(s.to_value is None and s.blocked == FORMAT_UNKNOWN for s in unknown_fmt.suggestions)
    assert unknown_fmt.suggestions[0].from_value == 9.0
    no_setup = suggest([_sym()], [], cat=cat, car_format="f1_2025", stored=None)
    assert not no_setup.setup_known and all(s.from_value is None and s.to_value is None for s in no_setup.suggestions)


def test_a_running_experiment_blocks_its_parameter(cat: Catalog) -> None:
    eng = suggest([_sym()], [], cat=cat, car_format="f1_2025", stored=STORED, testing=frozenset({"front_arb"}))
    s = eng.suggestions[0]
    assert s.parameter == "front_arb" and s.blocked and "already proposed or running" in s.blocked
    assert s.to_value == 7.0  # still shown, but not offered


def test_driving_symptoms_and_pressures_camber_toe_ride_height_are_never_suggested(cat: Catalog) -> None:
    eng = suggest([_sym(verdict="driving")], [], cat=cat, car_format="f1_2025", stored=STORED)
    assert eng.suggestions == [] and eng.note and "best lap" in eng.note
    every = [c.key for cands in [*CANDIDATES.values(), *LOCKUP_CANDIDATES.values()] for c in cands]
    assert not set(every) & NEVER_SUGGESTED
    assert {"tyre_pressure_fl", "front_camber", "rear_toe", "front_ride_height"} <= NEVER_SUGGESTED


def test_braking_assist_drops_brake_settings_and_symptoms_under_braking(cat: Catalog) -> None:
    """With the game's braking assist on the brake figures are not all the driver's (technique.rig): no brake bias or
    pressure change, nothing that needs the symptom under braking, and a note that says why."""
    entry = _sym(phase="entry", speeds=("slow",), with_braking=True)
    twice = LockupSymptom("lockups-front", "front", ["T1", "T5"], ["T1", "T5"], 2, 2, "x", "The fronts locked.")
    eng = suggest([entry], [twice], cat=cat, car_format="f1_2025", stored=STORED, braking_assist=True)
    params = [s.parameter for s in eng.suggestions]
    assert "brake_bias" not in params and "brake_pressure" not in params and params[0] == "diff_off_throttle"
    assert not any(s.symptom_id == "lockups-front" for s in eng.suggestions)
    assert eng.note and NOTE_BRAKING_ASSIST in eng.note
    without = suggest([entry], [twice], cat=cat, car_format="f1_2025", stored=STORED)
    assert "brake_bias" in [s.parameter for s in without.suggestions] and NOTE_BRAKING_ASSIST not in (
        without.note or ""
    )
    mid = suggest([_sym()], [], cat=cat, car_format="f1_2025", stored=STORED, braking_assist=True)
    assert NOTE_BRAKING_ASSIST not in (mid.note or "")  # nothing brake-related was dropped: no note


def test_lock_ups_qualify_only_when_they_recur(cat: Catalog) -> None:
    once = LockupSymptom("lockups-front", "front", ["T1"], ["T1"], 1, 1, "x", "The front wheels locked at T1.")
    twice = LockupSymptom("lockups-front", "front", ["T1", "T5"], ["T1", "T5"], 2, 2, "x", "The fronts locked.")
    assert suggest([], [once], cat=cat, car_format="f1_2025", stored=STORED).suggestions == []
    eng = suggest([], [twice], cat=cat, car_format="f1_2025", stored=STORED)
    assert [(s.parameter, s.to_value) for s in eng.suggestions] == [("brake_pressure", 97.0), ("brake_bias", 55.0)]


def test_a_suggestion_feeds_the_experiments_flow(tmp_path: Path, cat: Catalog) -> None:
    db = Database(tmp_path / "t.sqlite3")
    writer = DbWriter(db)
    try:
        info = SessionInfo(game=Game.F1_25, track_id="f1:10", car_id="f1:team:0", formula="F1 Modern")

        def seed(c: Any) -> None:
            repo.insert_session(c, "s1", "f1_25", "test", False, None, None)
            repo.update_session_info(c, "s1", info)

        writer.call(seed)
        eng = suggest([_sym()], [], cat=cat, car_format="f1_2025", stored=STORED)
        s = eng.suggestions[0]
        assert s.to_value is not None
        exp = experiments.propose(
            db, writer, cat, before_session_id="s1", parameter=s.parameter, to_value=s.to_value, hypothesis=s.hypothesis
        )
        assert exp["parameter"] == "front_arb" and exp["to_value"] == 7.0 and exp["status"] == "proposed"
        assert exp["hypothesis"] == s.hypothesis
    finally:
        writer.close()
