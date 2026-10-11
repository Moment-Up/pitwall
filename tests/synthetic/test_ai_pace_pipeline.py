"""Pace vs AI difficulty, end to end on a SYNTHETIC race: capture -> F1 adapter -> SessionManager -> AnalysisWorker ->
SQLite -> live snapshot -> engineer. The generator writes known AI lap times (Session History), a known AI difficulty
(after two unfilled Session tails, like real F1 25), a safety car period, an AI pit stop, an invalid AI lap and the
results skip (every AI car marked finished where it is, its last lap filled in at once). The stored summary must match
the ground truth exactly.

SYNTHETIC: this proves the pipeline against generated packets; it is not evidence of game compatibility.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pitwall.ai.facts import build_fact_sheet
from pitwall.ai.radio_phrasing import radio_answer
from pitwall.config import Settings
from pitwall.core.runtime import Runtime
from pitwall.core.session_analysis import SessionAnalyzer
from pitwall.sim.driver import CornerDeviation, DriverProfile
from pitwall.sim.f1_stream import AiCarSpec, F1Scenario, GroundTruth
from pitwall.sim.scenarios import write_synthetic_capture
from pitwall.storage import repo

pytestmark = pytest.mark.synthetic

SC = (150.0, 170.0)
SLACK_S = 2.0
PIT_CAR, PIT_LAP = 4, 2
INVALID_CAR, INVALID_LAP = 6, 4
DIFFICULTY = 42


def scenario() -> F1Scenario:
    ai = tuple(
        AiCarSpec(
            index=i,
            start_s=5.0 + 1.0 * i,  # every AI car is mid-lap (5+ s to go) when the player finishes
            lap_index_seed=i,
            driver=DriverProfile(deviations={"T3": CornerDeviation(brake_early_m=6.0 * i)}),
            pit_laps=frozenset({PIT_LAP}) if i == PIT_CAR else frozenset(),
            invalid_laps=frozenset({INVALID_LAP}) if i == INVALID_CAR else frozenset(),
        )
        for i in range(1, 8)
    )
    return F1Scenario(
        laps=5,
        session_type=15,  # Race
        ai_cars=ai,
        ai_difficulty=DIFFICULTY,
        session_history=True,
        safety_car_periods=(SC,),
        skip_results_after_player_finish=True,
    )


def expected(truth: GroundTruth) -> tuple[dict[int, int], dict[str, int], int]:
    """Per-car best eligible lap, exclusion counts and eligible laps, from the generator's ground truth."""
    excluded: dict[str, int] = {}
    bests: dict[int, int] = {}
    laps_used = 0
    for c, times in truth.ai_lap_times_ms.items():
        eligible = []
        for n, ms in sorted(times.items()):
            end = truth.ai_lap_end_s[c][n]
            window = (end - ms / 1000 - SLACK_S, end)
            if n == 1:
                reason = "race_lap_1"
            elif n in truth.ai_simulated_laps.get(c, frozenset()):
                reason = "results_skip"  # LapData showed the car finished away from the line
            elif c == INVALID_CAR and n == INVALID_LAP:
                reason = "invalid"
            elif c == PIT_CAR and n in (PIT_LAP, PIT_LAP + 1):
                reason = "pit_in_out"
            elif window[0] < SC[1] and SC[0] < window[1]:
                reason = "safety_car"
            else:
                eligible.append(ms)
                continue
            excluded[reason] = excluded.get(reason, 0) + 1
        if eligible:
            bests[c] = min(eligible)
            laps_used += len(eligible)
    return bests, excluded, laps_used


@pytest.fixture(scope="module")
def captured(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, GroundTruth]:
    cap = tmp_path_factory.mktemp("cap") / "captures" / "ai-pace.pwcap"
    truth = write_synthetic_capture(cap, scenario(), name="ai-pace-race")
    return cap, truth


def _replay(cap: Path, data: Path) -> Iterator[tuple[Runtime, str]]:
    rt = Runtime(Settings(_env_file=None, data_dir=data, llm_enabled=False, voice_enabled=False))  # type: ignore[call-arg]
    try:
        r = rt.start_replay(cap, speed=None)
        assert r.done.wait(120)
        rt.worker.join()
        rt.writer.flush()
        with rt.db.read() as c:
            sid = repo.latest_session_id(c)
        assert sid
        yield rt, sid
    finally:
        rt.close()


@pytest.fixture(scope="module")
def replayed(captured: tuple[Path, GroundTruth], tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    yield from _replay(captured[0], tmp_path_factory.mktemp("run1"))


def test_ground_truth_is_what_the_test_needs(captured: tuple[Path, GroundTruth]) -> None:
    _, truth = captured
    assert sorted(truth.ai_simulated_laps) == list(range(1, 8))  # every AI car's lap 5 was filled in at once
    for c, laps in truth.ai_simulated_laps.items():
        (n,) = laps
        end_as_driven = truth.ai_lap_end_s[c][n - 1] + truth.ai_lap_times_ms[c][n] / 1000
        assert end_as_driven - truth.ai_lap_end_s[c][n] > 5.0  # far beyond the 1.3 s timing tolerance too


def test_summary_matches_ground_truth(replayed: tuple[Runtime, str], captured: tuple[Path, GroundTruth]) -> None:
    rt, sid = replayed
    _, truth = captured
    bests, excluded, laps_used = expected(truth)
    assert excluded == {"race_lap_1": 7, "results_skip": 7, "invalid": 1, "pit_in_out": 2, "safety_car": 6}
    with rt.db.read() as c:
        s = repo.get_session(c, sid)
        a = repo.get_session_ai_pace(c, sid)
        laps = repo.session_lap_times(c, sid)
        points = repo.driver_ai_pace_points(c, rt.drivers.default_id)
    assert s is not None and s["synthetic"] and s["ai_difficulty"] == DIFFICULTY
    assert a is not None and a["status"] == "ok" and a["ai_difficulty"] == DIFFICULTY
    assert a["ai_cars"] == len(bests) == 7 and a["ai_laps"] == laps_used == 12
    assert a["ai_bests_ms"] == sorted(bests.values())
    assert a["ai_ref_ms"] == statistics.median(bests.values())  # 7 cars: an exact lap time
    assert a["ai_best_ms"] == min(bests.values())
    assert a["excluded"] == excluded
    # the driver: clean laps that did not run under the safety car (lap 3 spans 131-197 s)
    clean = {lap["lap_number"]: lap["lap_time_ms"] for lap in laps if lap["clean"]}
    used = {n: ms for n, ms in clean.items() if n != 3}
    assert 3 in clean and a["driver_clean_laps"] == len(used)
    assert a["driver_best_ms"] == min(used.values()) and a["gap_ms"] == a["driver_best_ms"] - a["ai_ref_ms"]
    assert a["field_rank"] == 1 + sum(1 for b in bests.values() if b < a["driver_best_ms"])
    assert a["field_size"] == 8 and a["weather_class"] == "dry" and a["online"] is False
    assert points == []  # synthetic sessions never feed a driver's AI pace series or suggestions
    assert rt.worker.errors == 0 and rt.writer.errors == 0 and rt.worker.ai_dropped == 0


def test_live_snapshot_and_radio(replayed: tuple[Runtime, str]) -> None:
    rt, sid = replayed
    snap = rt.live.snapshot()["ai_pace"]
    with rt.db.read() as c:
        a = repo.get_session_ai_pace(c, sid)
    assert a is not None and snap is not None
    assert snap["session_id"] == sid and snap["synthetic"] is True and snap["status"] == "ok"
    assert {k: snap[k] for k in ("ai_difficulty", "ai_cars", "ai_ref_ms", "driver_best_ms", "gap_ms")} == {
        k: a[k] for k in ("ai_difficulty", "ai_cars", "ai_ref_ms", "driver_best_ms", "gap_ms")
    }
    sa = SessionAnalyzer(rt.db).analyse(sid)
    assert sa is not None and sa.ai_suggestion is None  # never for synthetic data
    sheet = build_fact_sheet(sa)
    fact = next(f for f in sheet.facts if f.topic == "ai")
    assert fact.text.endswith("NOTE: SYNTHETIC data.")
    msg = radio_answer("ai_pace", sheet)
    assert msg is not None and msg.startswith(f"Against the AI at {DIFFICULTY}: ")
    assert msg.endswith(f"position {a['field_rank']} of 8 on best laps.")


def test_two_runs_give_identical_rows(
    replayed: tuple[Runtime, str], captured: tuple[Path, GroundTruth], tmp_path: Path
) -> None:
    rt, sid = replayed
    with rt.db.read() as c:
        first = repo.get_session_ai_pace(c, sid)
    for rt2, sid2 in _replay(captured[0], tmp_path / "run2"):
        with rt2.db.read() as c:
            second = repo.get_session_ai_pace(c, sid2)
    assert first is not None and second is not None
    first.pop("updated_unix")
    second.pop("updated_unix")
    assert first == second
