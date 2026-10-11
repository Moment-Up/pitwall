"""coachref review fixes in the lap pipeline: a drill stops when the conditions change (wet/dry, assists, car) and its
frozen reference is never used in other conditions; grid starts, resets, stale data and safety-car laps are no
attempts and no baseline; a timed-out request never takes effect later; the last result waits for its driver until
Done; the chosen reference is published before the session's first lap.

Ann's laps are the synthetic coaching demo, Sam's the clean synthetic session, stored as ordinary non-synthetic rows
on purpose (cross-driver rules). Not a game-compatibility claim.
"""

from __future__ import annotations

import dataclasses
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future
from pathlib import Path
from typing import Any

import pytest

from pitwall.core import coachref as cr
from pitwall.core.coachref import ChoiceRequest, CoachRef, DrillRequest
from pitwall.core.lap_processor import LapJob, _Task
from pitwall.model.telemetry import SessionInfo
from pitwall.storage import repo
from tests.coachref_support import Env, copy_lap, drive, lap_ctx, make_env, new_session, session_info
from tests.conftest import DecodedSession
from tests.unit.test_lap_processor_coachref import set_moving, setup_family


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    e = make_env(tmp_path)
    yield e
    e.close()


def start_t2_drill(env: Env, sa: str, info: SessionInfo, laps: list[Any], n: int = 3) -> dict[str, Any]:
    """Ann drives two laps (her own reference and baselines), then starts a brake-point drill at T2 in the garage."""
    drive(env.proc, sa, info, [(laps[0], 69_000, 1), (laps[1], 69_500, 2)])
    set_moving(env.live, None, pit=1)
    view = env.svc.start_drill(DrillRequest(corner="T2", kind="brake_point", laps=n))
    assert view["status"] == "active" and env.live.cues.drill_corner == "T2"
    return view


def drill_row(env: Env, drill_id: int) -> dict[str, Any]:
    env.writer.flush()
    with env.db.read() as c:
        row = repo.get_drill(c, drill_id)
    assert row is not None
    return row


def other_braking(info: SessionInfo) -> SessionInfo:
    return session_info(info, assists={"braking": (int(info.assists.get("braking") or 0) + 1) % 3})


# ---------------------------------------------------------------------------------------------- conditions
@pytest.mark.parametrize("change", ["wet", "braking_assist"])
def test_a_lap_in_other_conditions_stops_the_drill(
    env: Env, clean_session: DecodedSession, demo_session: DecodedSession, change: str
) -> None:
    """Adversarial review S2: a heavy-rain lap (or another braking assist) was scored against the dry target."""
    _ann, _sam, sa = setup_family(env, clean_session, demo_session)
    laps, info = demo_session.laps, demo_session.info
    view = start_t2_drill(env, sa, info, laps)
    other = session_info(info, condition="heavy_rain") if change == "wet" else other_braking(info)
    drive(env.proc, sa, other, [(laps[2], 70_500, 3)])
    row = drill_row(env, view["id"])
    assert (row["status"], row["stop_reason"], row["attempts"]) == ("abandoned", "context_changed", 0)
    assert env.live.coachref is not None and env.live.coachref["drill"] is None  # nothing driven: no result
    assert env.live.cues.drill_corner is None
    ref = env.live.reference
    assert ref is not None and ref["frozen"] is False  # the frozen reference was not used for that lap


def test_a_drill_with_attempts_stopped_by_the_conditions_keeps_its_result(
    env: Env, clean_session: DecodedSession, demo_session: DecodedSession
) -> None:
    _ann, _sam, sa = setup_family(env, clean_session, demo_session)
    laps, info = demo_session.laps, demo_session.info
    view = start_t2_drill(env, sa, info, laps)
    drive(env.proc, sa, info, [(laps[0], 69_000, 3)])  # attempt 1 in the same conditions
    drive(env.proc, sa, session_info(info, condition="heavy_rain"), [(laps[1], 69_500, 4)])
    row = drill_row(env, view["id"])
    assert (row["status"], row["stop_reason"], row["attempts"]) == ("stopped", "context_changed", 1)
    drill = env.live.coachref["drill"] if env.live.coachref else None
    assert drill is not None and drill["status"] == "stopped" and len(drill["attempts"]) == 1


def test_the_frozen_reference_is_only_for_the_drills_conditions(
    env: Env, clean_session: DecodedSession, demo_session: DecodedSession
) -> None:
    ann, _sam, sa = setup_family(env, clean_session, demo_session)
    laps, info = demo_session.laps, demo_session.info
    start_t2_drill(env, sa, info, laps)
    ctx = {**lap_ctx(info), "formula": info.formula}
    assert env.svc.frozen_for(ann, ctx) is not None
    assert env.svc.frozen_for(ann, {**ctx, "car_id": "f1:team:99"}) is None  # the first lap in another car
    assert env.svc.frozen_for(ann, {**ctx, "weather": "heavy_rain"}) is None
    assert env.svc.frozen_for(ann, lap_ctx(other_braking(info))) is None
    assert env.svc.frozen_for(ann, {**ctx, "track_temp_c": 45.0}) is not None  # a warning, not a blocker


def test_the_drill_records_its_start_conditions(
    env: Env, clean_session: DecodedSession, demo_session: DecodedSession
) -> None:
    _ann, _sam, sa = setup_family(env, clean_session, demo_session)
    laps, info = demo_session.laps, demo_session.info
    view = start_t2_drill(env, sa, info, laps)
    st = env.svc._drills[env.drivers.default_id]
    assert st.spec.context is not None
    assert (st.spec.context["game"], st.spec.context["car_id"], st.spec.context["weather"]) == (
        info.game.value,
        info.car_id,
        info.weather.condition,
    )
    assert st.spec.context["assists"] == dict(info.assists)
    assert drill_row(env, view["id"])["detail"]["context"] == st.spec.context  # stored with the drill


# ---------------------------------------------------------------------------------------------- unrepresentative laps
@pytest.mark.parametrize("flag", ["standing_start", "distance_jump", "stale_data"])
def test_unrepresentative_laps_are_no_attempts_and_no_baseline(
    env: Env, clean_session: DecodedSession, demo_session: DecodedSession, flag: str
) -> None:
    """Adversarial review S3: race lap 1 from the grid and a reset lap counted as attempts and baselines."""
    _ann, _sam, sa = setup_family(env, clean_session, demo_session)
    laps, info = demo_session.laps, demo_session.info
    start_t2_drill(env, sa, info, laps)
    before = {k: len(v) for k, v in env.proc._sessions[sa].recent.items()}
    lap = copy_lap(laps[2], 70_500, 3)
    lap.flags = {flag}
    env.proc.process(LapJob(sa, lap, lap_ctx(info)))
    drill = env.live.coachref["drill"] if env.live.coachref else None
    assert drill is not None and drill["status"] == "active" and drill["attempts"] == []
    assert {k: len(v) for k, v in env.proc._sessions[sa].recent.items()} == before
    drive(env.proc, sa, info, [(laps[0], 69_000, 4)])  # a normal lap is attempt 1
    drill = env.live.coachref["drill"] if env.live.coachref else None
    assert drill is not None and [a["lap_number"] for a in drill["attempts"]] == [4]


def test_safety_car_laps_are_no_attempts_and_no_baseline(
    env: Env, clean_session: DecodedSession, demo_session: DecodedSession
) -> None:
    _ann, _sam, sa = setup_family(env, clean_session, demo_session)
    laps, info = demo_session.laps, demo_session.info
    start_t2_drill(env, sa, info, laps)
    before = {k: len(v) for k, v in env.proc._sessions[sa].recent.items()}
    env.live.on_session(dataclasses.replace(info, safety_car_status="full"))
    drive(env.proc, sa, info, [(laps[2], 90_500, 3)])
    drill = env.live.coachref["drill"] if env.live.coachref else None
    assert drill is not None and drill["attempts"] == []
    assert {k: len(v) for k, v in env.proc._sessions[sa].recent.items()} == before
    env.live.on_session(dataclasses.replace(info, safety_car_status="none"))
    drive(env.proc, sa, info, [(laps[0], 69_000, 4)])
    drill = env.live.coachref["drill"] if env.live.coachref else None
    assert drill is not None and [a["lap_number"] for a in drill["attempts"]] == [4]


# ---------------------------------------------------------------------------------------------- busy analysis
def test_a_request_that_times_out_is_withdrawn(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    """Adversarial review: a 503 "busy" answer used to be followed by the change anyway."""
    queued: list[Future[Any]] = []

    def stuck(fn: Callable[[], Any]) -> Future[Any]:
        fut: Future[Any] = Future()
        queued.append(fut)
        return fut  # never picked up while the caller waits

    monkeypatch.setattr(cr, "TASK_TIMEOUT_S", 0.05)
    svc = CoachRef(env.db, env.writer, env.live, env.drivers, run_task=stuck)
    try:
        with pytest.raises(cr.Busy):
            svc.set_choice(ChoiceRequest(kind="household_best"))
        assert queued[-1].cancelled()
        ran: list[int] = []
        _Task(lambda: ran.append(1), queued[-1]).run()  # the analysis thread reaches it later: it does nothing
        assert ran == []
        with env.db.read() as c:
            assert repo.reference_choice_rows(c, env.drivers.default_id, None, None)["all_tracks"] is None
    finally:
        svc.close()


def test_a_request_already_running_is_answered(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    def slow(fn: Callable[[], Any]) -> Future[Any]:
        fut: Future[Any] = Future()
        fut.set_running_or_notify_cancel()

        def go() -> None:
            time.sleep(0.2)
            fut.set_result(fn())

        threading.Thread(target=go, daemon=True).start()
        return fut

    monkeypatch.setattr(cr, "TASK_TIMEOUT_S", 0.05)
    svc = CoachRef(env.db, env.writer, env.live, env.drivers, run_task=slow)
    try:
        choice, _ = svc.set_choice(ChoiceRequest(kind="household_best"))  # past the timeout, but running
        assert choice["kind"] == "household_best"
    finally:
        svc.close()


# ---------------------------------------------------------------------------------------------- results until Done
def test_the_last_result_waits_for_its_driver_until_done(
    env: Env, clean_session: DecodedSession, demo_session: DecodedSession
) -> None:
    """UX review M4: Sam's drill stopped when Alex sat in, and Sam never saw its result."""
    ann, sam, sa = setup_family(env, clean_session, demo_session)
    laps, info = demo_session.laps, demo_session.info
    view = start_t2_drill(env, sa, info, laps, n=5)
    drive(env.proc, sa, info, [(laps[0], 69_000, 3)])
    env.drivers.set_active(sam)  # another driver sits in: Ann's drill stops with one attempt
    assert env.live.coachref is not None and env.live.coachref["drill"] is None  # not Sam's
    env.drivers.set_active(ann)
    drill = env.live.coachref["drill"] if env.live.coachref else None
    assert drill is not None and drill["id"] == view["id"] and drill["status"] == "stopped"
    assert drill["stop_reason"] == "driver_changed"
    env.svc.on_context("another-session")  # a new session keeps it too
    assert env.live.coachref is not None and env.live.coachref["drill"] is not None
    text, _ = env.svc.radio_command(cr_intent("drill_status"), "how did the drill go")
    assert text.startswith("T2 drill stopped after 1 of 5 laps")
    assert env.svc.dismiss_result(view["id"] + 1) is False  # not the last result
    assert env.svc.dismiss_result(view["id"]) is True
    assert env.live.coachref is not None and env.live.coachref["drill"] is None


@dataclasses.dataclass(frozen=True)
class _Intent:
    name: str
    corner: str | None = None


def cr_intent(name: str) -> _Intent:
    return _Intent(name)


# ---------------------------------------------------------------------------------------------- early reference
def test_the_chosen_reference_is_published_before_the_first_lap(
    env: Env, clean_session: DecodedSession, demo_session: DecodedSession
) -> None:
    """UX review M1: with a choice saved earlier, the whole first lap had no delta."""
    ann, sam, sa = setup_family(env, clean_session, demo_session)
    env.writer.call(lambda c: repo.set_reference_choice(c, ann, "driver_best", target_driver_id=sam))
    env.proc._models.clear()  # a fresh start: the track model is only in the database
    assert env.live.reference is None
    req = env.live.bests_request()
    assert req is not None
    env.proc.refresh_bests(req)  # the session's context is complete (what AnalysisWorker runs)
    ref = env.live.reference
    assert ref is not None and ref["label"] == "Sam's best" and ref["own"] is False
    assert env.live.cues.plan.cues == ()  # braking calls still wait for a lap's comparison
    (first,) = drive(env.proc, sa, demo_session.info, [(demo_session.laps[0], 70_000, 1)])
    assert first["comparison"]["reference"]["lap_id"] == ref["lap_id"]


def test_no_early_reference_without_a_known_car_or_for_replays(
    env: Env, clean_session: DecodedSession, demo_session: DecodedSession
) -> None:
    ann, sam, _sa = setup_family(env, clean_session, demo_session)
    env.writer.call(lambda c: repo.set_reference_choice(c, ann, "driver_best", target_driver_id=sam))
    env.live.on_session(dataclasses.replace(demo_session.info, car_id=None))
    req = env.live.bests_request()
    assert req is not None
    env.proc.refresh_bests(req)
    assert env.live.reference is None
    rep = new_session(env.writer, ann, demo_session.info, "s-replay", source="replay:x.pwcap")
    env.live.reset_session(rep, "replay:x.pwcap", False)
    env.live.on_session(demo_session.info)
    req = env.live.bests_request()
    assert req is not None
    env.proc.refresh_bests(req)
    assert env.live.reference is None


def test_the_early_reference_follows_the_real_assists(
    env: Env, clean_session: DecodedSession, demo_session: DecodedSession
) -> None:
    """F1 sends default assists (0) in a session's first packets and the real ones about a second later (seen on the
    owner's Las Vegas capture): the reference chosen before the first lap is resolved again when they change."""
    ann, sam, _sa = setup_family(env, clean_session, demo_session)
    env.writer.call(lambda c: repo.set_reference_choice(c, ann, "driver_best", target_driver_id=sam))
    real = demo_session.info
    braking = int(real.assists.get("braking") or 0)
    defaults = session_info(real, assists={"braking": (braking + 1) % 3})  # what the first packets say
    requests: list[Any] = []
    env.live.set_bests_requester(lambda r: (requests.append(r), env.proc.refresh_bests(r)))
    env.live.on_session(defaults)
    assert (
        env.live.coachref is not None
        and env.live.coachref["reason"] == "Sam's laps here used a different braking assist"
    )
    env.live.on_session(defaults)  # the same conditions: no new request
    n = len(requests)
    env.live.on_session(real)  # the real assists arrive before the first lap
    assert len(requests) == n + 1
    ref = env.live.reference
    assert ref is not None and ref["label"] == "Sam's best"
    assert env.live.coachref["reason"] is None and env.live.coachref["used_kind"] == "driver_best"
    env.live.set_bests_requester(None)
