"""coachref in the lap pipeline (``LapProcessor`` + ``LiveState`` + ``CueEngine`` + ``CoachRef``).

Sam's laps are the synthetic clean session (fast lap times assigned), Ann's the coaching demo with its injected
mistakes. Stored as ordinary non-synthetic rows on purpose (cross-driver resolution); not a compatibility claim.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pitwall.coach.cues import CueEngine
from pitwall.core.coachref import ChoiceRequest, DrillRequest
from pitwall.core.lap_processor import AnalysisWorker, LapProcessor
from pitwall.core.live import LiveState
from pitwall.model.telemetry import CarFrame, Game
from pitwall.storage import repo
from tests.coachref_support import Env, drive, make_env, new_session
from tests.conftest import DecodedSession

LEGACY_REFERENCE_KEYS = {"lap_id", "lap_number", "lap_time_ms", "session_id"}
DESCRIPTOR_KEYS = LEGACY_REFERENCE_KEYS | {
    "kind",
    "own",
    "pinned",
    "driver_id",
    "driver_name",
    "set_unix",
    "label",
    "label_to",
    "ref_name",
    "brake_clamped",
    "frozen",
}


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    e = make_env(tmp_path)
    yield e
    e.close()


def setup_family(env: Env, clean: DecodedSession, demo: DecodedSession) -> tuple[int, int, str]:
    """Sam drives three fast clean laps (they also teach the shared track model); Ann's live session starts."""
    ann = env.drivers.default_id
    sam = env.drivers.create("Sam").id
    ss = new_session(env.writer, sam, clean.info, "s-sam")
    drive(env.proc, ss, clean.info, [(clean.laps[i], 60_000 + i, i + 1) for i in range(3)])
    sa = new_session(env.writer, ann, demo.info, "s-ann")
    env.live.reset_session(sa, "udp:20777", False)
    env.live.on_session(demo.info)
    return ann, sam, sa


def frame(speed: float | None, *, pit: int = 0, lap: int = 1) -> CarFrame:
    return CarFrame(game=Game.F1_25, t_recv_ns=0, speed_kph=speed, pit_status=pit, lap_number=lap)


def set_moving(live: LiveState, speed: float | None, *, pit: int = 0, lap: int = 1) -> None:
    live.frame = frame(speed, pit=pit, lap=lap)
    live.last_packet_mono = time.monotonic()  # connection "live"


def test_cross_driver_reference_descriptor_wording_and_clamp(
    env: Env, clean_session: DecodedSession, demo_session: DecodedSession
) -> None:
    _ann, sam, sa = setup_family(env, clean_session, demo_session)
    env.svc.set_choice(ChoiceRequest(kind="driver_best", target_driver_id=sam))
    laps = demo_session.laps
    (first,) = drive(env.proc, sa, demo_session.info, [(laps[0], 70_000, 1)])
    ref = env.live.reference
    assert ref is not None and set(ref) == DESCRIPTOR_KEYS
    assert (ref["lap_id"], ref["own"], ref["label"], ref["label_to"], ref["ref_name"], ref["brake_clamped"]) == (
        1,
        False,
        "Sam's best",
        "Sam's best",
        "Sam",
        True,
    )
    comp = first["comparison"]
    assert comp["reference"] == ref and comp["brake_clamp_m"] == {}  # Ann has no lap of her own yet
    assert env.live.cues.plan.cues == () and env.live.cues.plan.reason == "no braking points of your own yet"
    assert env.live.coachref is not None and env.live.coachref["used_kind"] == "driver_best"
    res = drive(env.proc, sa, demo_session.info, [(laps[1], 69_500, 2), (laps[2], 70_500, 3)])
    third = res[1]
    clamp = third["comparison"]["brake_clamp_m"]
    assert clamp and all(isinstance(v, float) for v in clamp.values())
    early = [o for o in third["observations"] if o["kind"] == "brake_early"]
    assert early and "earlier than Sam" in early[0]["text"] and early[0]["ref_name"] == "Sam"
    assert all("your reference" not in o["text"] for o in third["observations"])
    env.writer.flush()
    with env.db.read() as c:
        stored = [o["text"] for o in repo.list_observations(c, sa) if o["kind"] == "brake_early"]
    assert stored and all("than Sam" in t for t in stored)  # persisted reworded
    plan = env.live.cues.plan
    assert plan.cues, plan.reason
    for cue in plan.cues:
        assert cue.target_m <= clamp[cue.corner]  # never later than Ann's own braking point
    assert env.live.coach.current is not None
    assert all(p.get("ref_name") == "Sam" for p in env.live.coach.current["picked"])


def test_without_a_service_the_payload_is_unchanged(tmp_path: Path, clean_session: DecodedSession) -> None:
    from pitwall.drivers import DriverService
    from pitwall.storage.db import Database, DbWriter

    db = Database(tmp_path / "legacy.sqlite3")
    writer = DbWriter(db)
    try:
        live = LiveState()
        proc = LapProcessor(db, writer, live)
        drivers = DriverService(db, writer)
        sid = new_session(writer, drivers.default_id, clean_session.info, "s1")
        live.reset_session(sid, "udp:20777", False)
        res = drive(
            proc, sid, clean_session.info, [(lap, 60_000 + i, i + 1) for i, lap in enumerate(clean_session.laps)]
        )
        comp = res[-1]["comparison"]
        assert comp is not None and "reference" not in comp and "brake_clamp_m" not in comp
        assert live.reference is not None and set(live.reference) == LEGACY_REFERENCE_KEYS
        assert live.coachref is None
        assert all(o.get("ref_name") is None for o in res[-1]["observations"])
    finally:
        writer.close()


def test_drill_filters_live_observations_and_freezes_the_reference(
    env: Env, clean_session: DecodedSession, demo_session: DecodedSession
) -> None:
    _ann, sam, sa = setup_family(env, clean_session, demo_session)
    laps, info = demo_session.laps, demo_session.info
    drive(env.proc, sa, info, [(laps[0], 69_000, 1), (laps[1], 69_500, 2)])
    own_ref = env.live.reference
    assert own_ref is not None and own_ref["own"] and own_ref["kind"] == "own_best"
    set_moving(env.live, None, pit=1)  # in the garage: the drill counts from the next lap
    view = env.svc.start_drill(DrillRequest(corner="T2", kind="brake_point", laps=3))
    assert view["status"] == "active" and env.live.cues.drill_corner == "T2"
    assert view["reference"]["lap_id"] == own_ref["lap_id"] and view["target_text"].endswith(
        "your best lap's braking point"
    )
    set_moving(env.live, 250.0, lap=3)
    choice, applies = env.svc.set_choice(ChoiceRequest(kind="driver_best", target_driver_id=sam))
    assert applies == "after_drill" and env.live.coachref is not None and env.live.coachref["pending"] is True
    (r3,) = drive(env.proc, sa, info, [(laps[2], 70_500, 3)])  # brakes 15 m early at the drill corner
    assert env.live.reference is not None and env.live.reference["lap_id"] == own_ref["lap_id"]
    assert env.live.reference["frozen"] is True  # the choice waits for the drill
    assert {o["corner"] for o in env.live.observations} <= {"T2"}
    env.writer.flush()
    with env.db.read() as c:
        stored = {o["corner"] for o in repo.list_observations(c, sa) if o["lap_id"] == r3["lap_id"]}
    assert stored  # every corner's observations are stored
    block = env.live.coach.current
    assert block is not None and block["drill_only"] is True
    assert [p["kind"] for p in block["picked"]] == ["drill"] and set(block["by_corner"]) == {"T2"}
    assert block["picked"][0]["drill"]["attempt"] == 1
    drive(env.proc, sa, info, [(laps[0], 69_000, 4), (laps[1], 69_400, 5)])  # attempts 2 and 3: done
    drill = env.live.coachref["drill"]
    assert drill is not None and drill["status"] == "completed" and len(drill["attempts"]) == 3
    assert env.live.cues.drill_corner is None
    drive(env.proc, sa, info, [(laps[1], 69_300, 6)])  # the drill is over: the waiting choice applies
    assert (
        env.live.reference is not None and env.live.reference["lap_id"] == 1 and env.live.reference["frozen"] is False
    )
    assert env.live.coachref["pending"] is False and env.live.coachref["used_kind"] == "driver_best"
    assert choice["label"] == "Sam's best"


def test_reference_change_applies_now_only_when_stopped(
    env: Env, clean_session: DecodedSession, demo_session: DecodedSession
) -> None:
    _ann, sam, sa = setup_family(env, clean_session, demo_session)
    drive(env.proc, sa, demo_session.info, [(demo_session.laps[0], 69_000, 1), (demo_session.laps[1], 69_500, 2)])
    before = env.live.reference
    assert before is not None and before["own"]
    set_moving(env.live, 210.0)
    _, applies = env.svc.set_choice(ChoiceRequest(kind="driver_best", target_driver_id=sam))
    assert applies == "next_lap"
    assert env.live.reference == before and env.live.coachref is not None and env.live.coachref["pending"]
    set_moving(env.live, None)  # on track with no speed: unknown is never assumed stopped
    assert env.svc.set_choice(ChoiceRequest(kind="household_best"))[1] == "next_lap"
    set_moving(env.live, 12.0)
    _, applies = env.svc.set_choice(ChoiceRequest(kind="driver_best", target_driver_id=sam))
    assert applies == "now"
    after = env.live.reference
    assert after is not None and after["lap_id"] == 1 and after["label"] == "Sam's best"
    assert env.live.coachref["pending"] is False
    set_moving(env.live, 210.0, pit=2)  # in the pits counts as stopped
    assert env.svc.set_choice(ChoiceRequest(kind="own_best"))[1] == "now"
    assert env.live.reference is not None and env.live.reference["own"] is True
    env.live.reset_session("other", "udp:20777", False)
    assert env.svc.set_choice(ChoiceRequest(kind="household_best"))[1] == "next_session"


def test_submit_task_runs_on_the_worker_thread_and_propagates_errors(env: Env) -> None:
    worker = AnalysisWorker(env.proc)
    try:
        assert worker.submit_task(lambda: threading.current_thread().name).result(5) == "lap-analysis"

        def boom() -> None:
            raise ValueError("nope")

        with pytest.raises(ValueError, match="nope"):
            worker.submit_task(boom).result(5)
        assert worker.errors == 0  # a task's error is the caller's, not a lap-processing failure
    finally:
        worker.close()


def test_coachref_never_touches_the_ingest_thread_hooks(
    env: Env, clean_session: DecodedSession, demo_session: DecodedSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Any] = []

    def forbidden(*a: Any, **k: Any) -> None:
        calls.append(a)
        raise AssertionError("ingest-thread hook called from the analysis path")

    monkeypatch.setattr(LiveState, "on_frame", forbidden)
    monkeypatch.setattr(CueEngine, "on_frame", forbidden)
    _ann, sam, sa = setup_family(env, clean_session, demo_session)
    env.svc.set_choice(ChoiceRequest(kind="driver_best", target_driver_id=sam))
    drive(env.proc, sa, demo_session.info, [(demo_session.laps[i], 69_000 + i, i + 1) for i in range(3)])
    env.svc.start_drill(DrillRequest(corner_ref="T2", laps=3))
    drive(env.proc, sa, demo_session.info, [(demo_session.laps[0], 69_000, 4)])
    env.svc.stop_drill()
    assert calls == []


def test_drill_after_the_first_own_lap_uses_that_lap_as_the_own_point(
    env: Env, clean_session: DecodedSession, demo_session: DecodedSession
) -> None:
    """Found on a recorded replay: the last comparison's clamp excludes the lap just driven, so right after Ann's
    first lap it is empty. A drill started then must use the clamp the next lap will use (that lap included)."""
    _ann, sam, sa = setup_family(env, clean_session, demo_session)
    env.svc.set_choice(ChoiceRequest(kind="driver_best", target_driver_id=sam))
    (first,) = drive(env.proc, sa, demo_session.info, [(demo_session.laps[0], 69_000, 1)])
    assert first["comparison"]["brake_clamp_m"] == {}
    view = env.svc.start_drill(DrillRequest(corner="T2", kind="brake_point", laps=3))
    own_t2 = first["comparison"]["corners"]
    ann_point = next(c["cmp"]["brake_start_m"] for c in own_t2 if c["corner"] == "T2")
    assert view["target"] <= ann_point + 1e-9
    assert view["reference"]["label"] == "Sam's best"
