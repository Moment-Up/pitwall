"""SYNTHETIC technique validation: the technique-demo scenario's injected deviations are recovered end to end
(packets -> MotionEx decode -> laps -> SQLite -> track model -> technique analysis -> setup suggestions).

These prove the algorithms against known ground truth (``pitwall.sim.scenarios.technique_demo``). They are NOT
evidence of game compatibility: the MotionEx stream is generated with the signs measured on real recordings
(``tests/recorded/test_technique_recorded.py``), but its slip model is Pitwall's own.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import pytest

from pitwall.core.session_analysis import SessionAnalyzer
from pitwall.sim.driver import DriverProfile
from pitwall.sim.f1_stream import F1Scenario
from pitwall.sim.scenarios import technique_demo
from pitwall.sim.track import pitwall_park
from pitwall.storage.db import Database
from pitwall.technique.session import SessionTechnique, TechniqueAnalyzer, TechniqueCorner, clear_cache
from tests.technique_fixtures import design_to_learned, f1_writer, replay_into

pytestmark = pytest.mark.synthetic
log = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> tuple[TechniqueAnalyzer, SessionTechnique, dict[str, str]]:
    root: Path = tmp_path_factory.mktemp("technique_synthetic")
    sid = replay_into(root, [("technique-demo", f1_writer(technique_demo(), "technique-demo"))])["technique-demo"]
    db = Database(root / "pitwall.sqlite3")
    ta = TechniqueAnalyzer(db, SessionAnalyzer(db))
    st = ta.analyse(sid)
    assert st.model is not None
    names = design_to_learned(st.model.corners, {n: (a, b) for n, a, b in pitwall_park().corners})
    return ta, st, names


def _corner(st: SessionTechnique, name: str) -> TechniqueCorner:
    return next(c for c in st.corners if c.corner == name)


def test_lap_3_runs_two_metres_wide_at_design_t3_and_nowhere_else(
    run: tuple[TechniqueAnalyzer, SessionTechnique, dict[str, str]],
) -> None:
    _, st, names = run
    assert st.ref_lap_number == 1 and st.available["line"].ok
    t3 = names["T3"]
    for c in st.corners:
        assert c.line is not None and c.line.inside_known
        for lc in c.laps:
            if lc.line is None:
                continue
            if c.corner == t3 and lc.lap_number == 3:
                assert lc.line["apex"] == pytest.approx(-2.0, abs=0.2)
                for k in ("turn_in", "track_out"):
                    v = lc.line[k]
                    assert v is not None and -2.2 <= v <= 0.1
            else:
                assert all(v is None or abs(v) < 0.2 for v in lc.line.values()), (c.corner, lc.lap_number, lc.line)
    summary = _corner(st, t3).line
    assert summary is not None and summary.points["apex"] is not None and summary.points["apex"].laps_wider == 1


def test_lock_up_only_on_lap_4_at_design_t1(run: tuple[TechniqueAnalyzer, SessionTechnique, dict[str, str]]) -> None:
    _, st, names = run
    hits = [
        (c.corner, lc.lap_number, lc.inputs.lockup.wheels)
        for c in st.corners
        for lc in c.laps
        if lc.inputs is not None and lc.inputs.lockup.events
    ]
    assert hits == [(names["T1"], 4, ["fl"])]
    assert all(
        lc.inputs is None or lc.inputs.lockup.status in ("measured", "not_applicable")
        for c in st.corners
        for lc in c.laps
    )  # ABS off in this scenario
    lap4 = next(lc for lc in _corner(st, names["T1"]).laps if lc.lap_number == 4)
    assert any(n.metric == "lockup" and n.notable for n in lap4.notes)


def test_design_t8_mid_understeer_is_the_car_and_the_front_bar_goes_two_softer(
    run: tuple[TechniqueAnalyzer, SessionTechnique, dict[str, str]],
) -> None:
    ta, st, names = run
    t8 = names["T8"]
    c = _corner(st, t8)
    assert c.balance is not None
    mid = c.balance["mid"]
    assert mid.recurring == "understeer" and mid.verdict == "car" and mid.understeer == 6
    assert mid.median_slip_diff_deg == pytest.approx(6.0, abs=0.2)
    assert [s.id for s in st.symptoms] == ["mid-understeer-car"] and st.symptoms[0].corners == [t8]
    eng = ta.setup(st)
    assert eng is not None and eng.car_format == "f1_2025"  # synthetic team 8: a 2025 car
    first = eng.suggestions[0]
    assert first.parameter == "front_arb" and first.direction == "lower" and first.blocked is None
    assert first.from_value is not None and first.to_value == first.from_value - 2


def test_design_t8_exit_slide_on_lap_5_is_a_one_off(
    run: tuple[TechniqueAnalyzer, SessionTechnique, dict[str, str]],
) -> None:
    ta, st, names = run
    c = _corner(st, names["T8"])
    exits = {lc.lap_number: lc.balance["exit"] for lc in c.laps if lc.balance and lc.balance["exit"]}
    assert exits[5].cls == "oversteer" and exits[5].slide
    assert all(pb.cls != "oversteer" for n, pb in exits.items() if n != 5)
    assert c.balance is not None and c.balance["exit"].recurring is None
    lap5 = next(lc for lc in c.laps if lc.lap_number == 5)
    assert lap5.inputs is not None and lap5.inputs.wheelspin.events == 1
    assert lap5.inputs.wheelspin.total_s == pytest.approx(0.5, abs=0.05)
    eng = ta.setup(st)
    assert eng is not None and all(s.symptom_id == "mid-understeer-car" for s in eng.suggestions)


def test_everything_is_flagged_synthetic(run: tuple[TechniqueAnalyzer, SessionTechnique, dict[str, str]]) -> None:
    ta, st, _ = run
    body = st.to_dict(ta.setup(st))
    assert body["synthetic"] is True and st.session.get("synthetic")
    ref = st.ref_lap_id
    lap = next(e.lap_id for e in st.laps if e.lap_number == 3)
    assert ref is not None and ta.compare(ref, lap)["synthetic"] is True


def test_thirty_laps_analyse_in_seconds(tmp_path: Path) -> None:
    sc = F1Scenario(laps=30, default_driver=DriverProfile(noise_m=3.0), motion_ex=True)
    sid = replay_into(tmp_path, [("perf", f1_writer(sc, "perf"))])["perf"]
    db = Database(tmp_path / "pitwall.sqlite3")
    sessions = SessionAnalyzer(db)
    sa = sessions.analyse(sid)
    assert sa is not None and len(sa.laps) == 30
    clear_cache()
    t0 = time.perf_counter()
    st = TechniqueAnalyzer(db, sessions).analyse(sid)
    dt = time.perf_counter() - t0
    log.info("technique analysis of a 30-lap synthetic session: %.0f ms", dt * 1000)
    assert len(st.corners[0].laps) == 30
    assert dt < 3.0 * 3  # target 3 s cold (AC-R4); lenient for shared CI machines


def test_a_concluded_experiment_carries_the_balance_change(tmp_path: Path) -> None:
    from pitwall.carsetup import experiments
    from pitwall.carsetup.catalog import load_catalog
    from pitwall.storage.db import DbWriter

    sids = replay_into(
        tmp_path,
        [
            ("before", f1_writer(technique_demo(), "technique-demo")),
            ("after", f1_writer(technique_demo(), "technique-demo")),
        ],
    )
    db = Database(tmp_path / "pitwall.sqlite3")
    writer = DbWriter(db)
    try:
        cat = load_catalog()
        exp = experiments.propose(db, writer, cat, before_session_id=sids["before"], parameter="front_arb", to_value=8)
        experiments.start(db, writer, exp["id"], sids["after"])
        done = experiments.conclude(db, writer, SessionAnalyzer(db), cat, exp["id"])
    finally:
        writer.close()
    balance = done["after_metrics"]["comparison"]["balance"]
    assert balance["available"] is True and "heuristic" in balance["note"]
    change = next(c for c in balance["changes"] if c["phase"] == "mid")
    assert change["before"]["recurring"] == "understeer" and change["after"]["recurring"] == "understeer"
    assert change["delta_deg"] == pytest.approx(0.0, abs=0.1) and change["changed"] is False
    assert "no change (understeer on 6 of 6 laps both times)" in change["words"]
