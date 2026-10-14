"""SYNTHETIC: habit memory survives a new best (habits spec section 2), and the habit tracker announces the habit once.

A generated session at 'Pitwall Park': laps 1-3 are slow at design-T7 (about 3 s: the reference), laps 4-6 also brake
15 m early into design-T3 (a habit), lap 7 is clean everywhere (a new best, found at T7, not at T3) and laps 8-10
brake early at T3 again, now measured against lap 7. Before, the lap processor cleared its per-corner history on
every new reference, so lap 8's habit had no consistency (and the radio treated it as a one-off).

These prove the pipeline against generated packets with known injected mistakes. They are NOT evidence that a real
game is compatible (see tests/recorded and tests/live).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pitwall.core.lap_processor import LapJob, LapProcessor
from pitwall.core.live import LiveState
from pitwall.sim.driver import CornerDeviation, DriverProfile
from pitwall.sim.f1_stream import F1Scenario, generate_f1_session
from pitwall.storage import repo
from pitwall.storage.db import Database, DbWriter
from pitwall.voice.proactive import lap_messages
from pitwall.voice.types import MessageKind
from tests.conftest import DecodedSession, decode_session
from tests.unit.test_drivers import lap_ctx, new_session

pytestmark = pytest.mark.synthetic

SLOW_T7 = CornerDeviation(apex_speed_loss_kph=25, throttle_delay_m=60)
EARLY_T3 = CornerDeviation(brake_early_m=15)


def _scenario() -> F1Scenario:
    by_lap = {}
    for lap in range(1, 11):
        dev: dict[str, CornerDeviation] = {}
        if lap <= 6:
            dev["T7"] = SLOW_T7
        if 4 <= lap <= 6 or lap >= 8:
            dev["T3"] = EARLY_T3
        by_lap[lap] = DriverProfile(deviations=dev)
    return F1Scenario(laps=10, driver_by_lap=by_lap)


@pytest.fixture(scope="module")
def session() -> DecodedSession:
    packets, truth = generate_f1_session(_scenario())
    laps, frames, info, adapter = decode_session(packets)
    return DecodedSession(packets, truth, laps, frames, info, adapter)


@pytest.fixture
def run(session: DecodedSession, tmp_path: Path) -> Iterator[tuple[LapProcessor, LiveState, DbWriter, list[Any]]]:
    db = Database(tmp_path / "h.sqlite3")
    writer = DbWriter(db)
    live = LiveState()
    notes: list[dict[str, Any]] = []
    live.subscribe(lambda k, p: notes.append(p) if k == "lap" else None)
    proc = LapProcessor(db, writer, live)
    new_session(writer, None, session.info, "h")
    live.reset_session("h", "t", True)
    try:
        yield proc, live, writer, notes
    finally:
        writer.close()


def _early(result: dict[str, Any]) -> dict[str, Any] | None:
    return next((o for o in result["observations"] if o["kind"] == "brake_early"), None)


def test_a_habit_keeps_its_consistency_through_a_new_best(
    session: DecodedSession, run: tuple[LapProcessor, LiveState, DbWriter, list[Any]]
) -> None:
    proc, _live, _writer, notes = run
    results = {lap.lap_number: proc.process(LapJob("h", lap, lap_ctx(session.info))) for lap in session.laps}
    lap_id = {n: r["lap_id"] for n, r in results.items()}
    assert results[7]["comparison"]["ref_lap_id"] in (lap_id[1], lap_id[2], lap_id[3])
    assert results[8]["comparison"]["ref_lap_id"] == lap_id[7]  # lap 7 is the new best: the reference from lap 8
    six, eight = _early(results[6]), _early(results[8])
    assert six is not None and six["consistency"] == "3 of the last 5 laps"
    # against the new reference: laps 3-6 re-based (3 clean, 4-6 early), lap 7 itself left out, lap 8 early
    assert eight is not None and eight["consistency"] == "4 of the last 5 laps" and eight["consistency_ratio"] == 0.8
    corner = eight["corner"]
    kept = [e.lap_id for e in proc._sessions["h"].history[corner]]
    assert lap_id[7] not in kept and kept[-1] == lap_id[10]
    # the tracker announced the habit once (lap 6) and kept it through the new best: no repeat on laps 8-10
    coach = {p["lap"]["lap_number"]: p["coach"] for p in notes}
    events = {n: [(x["corner"], x.get("habit_event")) for x in c["picked"]] for n, c in coach.items()}
    assert events[4] == [(corner, None)]  # the first time: a big one-off
    assert events[5] == []  # the same again: not the same sentence two laps running
    assert events[6] == [(corner, "announce")]
    assert all(events[n] == [] for n in (7, 8, 9, 10))
    assert [(h["corner"], h["kind"], h["status"]) for h in coach[10]["habits"]] == [(corner, "brake_early", "focus")]
    msgs = lap_messages(notes[5]["lap"], notes[5]["observations"], None, None, "normal", 0.0, coach=coach[6])
    (said,) = [m.text for m in msgs if m.kind is MessageKind.COACHING]
    assert said == f"{corner}, losing 0.34 s: braking 13 m earlier. 3 of the last 5 laps."


def test_a_driver_change_clears_the_habit_memory(
    session: DecodedSession, run: tuple[LapProcessor, LiveState, DbWriter, list[Any]]
) -> None:
    proc, _live, writer, _notes = run
    for lap in session.laps[:6]:
        proc.process(LapJob("h", lap, lap_ctx(session.info)))
    assert proc._sessions["h"].history
    other = writer.call(lambda c: repo.insert_driver(c, "Sam", {}))
    writer.call(lambda c: repo.set_session_driver(c, "h", other))
    res = proc.process(LapJob("h", session.laps[7], lap_ctx(session.info)))
    sc = proc._sessions["h"]
    assert sc.driver_id == other and sc.history  # the session's laps are Sam's now: one of them is his reference
    assert {e.lap_id for h in sc.history.values() for e in h} == {res["lap_id"]}  # nothing from before the change
    assert res["observations"] and all(o["consistency"] is None for o in res["observations"])


def test_incidents_never_enter_the_habit_memory(
    session: DecodedSession, run: tuple[LapProcessor, LiveState, DbWriter, list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from pitwall.core import lap_processor

    proc, _live, _writer, _notes = run
    monkeypatch.setattr(lap_processor, "is_incident", lambda cd: cd.corner == "T2")  # every T2 lap an incident
    for lap in session.laps[:6]:
        proc.process(LapJob("h", lap, lap_ctx(session.info)))
    history = proc._sessions["h"].history
    assert history and "T2" not in history


def test_a_reference_chosen_between_laps_re_bases_the_memory(
    session: DecodedSession, run: tuple[LapProcessor, LiveState, DbWriter, list[Any]]
) -> None:
    """``refresh_reference`` (a reference chosen while the car is stopped) re-bases like a new best does."""
    proc, _live, writer, _notes = run
    ids = [proc.process(LapJob("h", lap, lap_ctx(session.info)))["lap_id"] for lap in session.laps[:6]]
    sc = proc._sessions["h"]
    corner = next(k for k, v in sc.history.items() if (v[-1].delta.brake_point_delta_m or 0.0) < -10.0)
    version = sc.history[corner][-1].model_version  # the track model settles after 3 clean laps
    settled = {e.lap_id for e in sc.history[corner] if e.model_version == version}
    assert ids[1] not in settled  # lap 2 was measured on the model built from 2 laps
    writer.call(lambda c: repo.pin_reference(c, ids[4]))  # lap 5, itself braking early there
    proc.refresh_reference("h")
    after = {e.lap_id: e.delta.brake_point_delta_m for e in sc.history[corner]}
    assert sc.history_ref == ids[4] and ids[4] not in after  # the new reference lap leaves its own history
    assert set(after) == settled - {ids[4]}  # and laps measured on other corner definitions
    assert after[ids[3]] == pytest.approx(0.0, abs=2.0) and after[ids[5]] == pytest.approx(0.0, abs=2.0)
    assert after[ids[2]] > 10.0  # a clean lap brakes later than the new (early) reference
