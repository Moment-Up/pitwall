"""Pace vs AI difficulty: the summary algorithm (``analysis.ai_pace``), the ingest-side collector and the session
manager's hand-off (``core.ai_pace``). Inputs are hand-built lap lists with known answers."""

from __future__ import annotations

import statistics
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, cast

import pytest

from pitwall.analysis.ai_pace import (
    DIFFICULTY_CHANGED,
    DIFFICULTY_KNOWN,
    DIFFICULTY_UNKNOWN,
    EXCLUSIONS,
    FAST_OUTLIER,
    MIN_AI_CARS,
    TIMING_TOL_S,
    AiPaceJob,
    ScPeriod,
    resolve_difficulty,
    summarise,
    weather_class,
)
from pitwall.core.ai_pace import UNCHANGED, AiPaceCollector
from pitwall.core.lap_processor import AnalysisWorker
from pitwall.core.live import LiveState
from pitwall.core.session import SessionManager
from pitwall.model.telemetry import (
    CarLapHistory,
    EventKind,
    Game,
    GameEvent,
    HistoryLap,
    SessionInfo,
    SessionType,
    Weather,
)
from pitwall.storage import repo
from pitwall.storage.db import Database, DbWriter

UID = "42"


def car(
    idx: int,
    times_ms: Sequence[int | None],
    *,
    start_s: float = 0.0,
    first_seen: int = 0,
    ai: bool | None = True,
    player: bool = False,
    pit: frozenset[int] = frozenset(),
    invalid: frozenset[int] = frozenset(),
    done_override: dict[int, float | None] | None = None,
    uid: str | None = UID,
    ai_from: int = 0,
    ended: int | None = None,
) -> CarLapHistory:
    """A car that drove ``times_ms`` back to back from ``start_s``; a None time is a lap still in progress."""
    laps: list[HistoryLap] = []
    t = start_s
    for n, ms in enumerate(times_ms, start=1):
        if ms is None:
            laps.append(HistoryLap(n, None, (None, None, None), None, None))
            continue
        t += ms / 1000
        done = (done_override or {}).get(n, t)
        laps.append(HistoryLap(n, ms, (None, None, None), n not in invalid, done))
    return CarLapHistory(
        game=Game.F1_25,
        t_recv_ns=0,
        session_time_s=t,
        session_uid=uid,
        car_index=idx,
        ai_controlled=ai,
        is_player=player,
        first_seen_lap=first_seen,
        laps=tuple(laps),
        pit_laps=pit,
        best_lap_number=None,
        ai_from_lap=ai_from,
        ended_lap=ended,
    )


def job(
    cars: Sequence[CarLapHistory],
    *,
    session_type: SessionType = SessionType.RACE,
    difficulty: int | None = 35,
    status: str = DIFFICULTY_KNOWN,
    sc: Sequence[ScPeriod] = (),
    red: Sequence[ScPeriod] = (),
    flashbacks: Sequence[tuple[float, float]] = (),
) -> AiPaceJob:
    return AiPaceJob(
        session_id="s1",
        histories=tuple(cars),
        sc_periods=tuple(sc),
        red_flags=tuple(red),
        flashbacks=tuple(flashbacks),
        ai_difficulty=difficulty if status == DIFFICULTY_KNOWN else None,
        difficulty_status=status,
        session_type=session_type.value,
        car_class="F1 World",
        weather_class="dry",
        network_game=False,
        run_id="run1",
    )


def field(bests: Sequence[int], laps: int = 3) -> list[CarLapHistory]:
    """AI cars 1..n each driving ``laps`` laps with their best on lap 2 (lap 1 is the race start)."""
    return [car(i + 1, [b + 4000] + [b] + [b + 500] * (laps - 2)) for i, b in enumerate(bests)]


def driver_laps(*times: int, t_recv: Sequence[tuple[int, int]] | None = None) -> list[dict[str, Any]]:
    out = []
    for k, ms in enumerate(times):
        t0, t1 = t_recv[k] if t_recv else (None, None)
        out.append(
            {
                "id": 100 + k,
                "lap_number": k + 2,
                "lap_time_ms": ms,
                "clean": True,
                "t_recv_start_ns": t0,
                "t_recv_end_ns": t1,
            }
        )
    return out


BESTS = [72_730, 73_000, 74_000, 74_579, 75_000, 75_500, 76_000]  # median 74_579


# ---------------------------------------------------------------------------------------------- AI lap eligibility
def test_ok_metrics_rounding_and_rank() -> None:
    s = summarise(job(field(BESTS)), driver_laps(78_351, 80_000), now=123.0)
    assert s.status == "ok" and s.ai_cars == 7 and s.ai_laps == 14  # laps 2 and 3 of 7 cars
    assert s.ai_ref_ms == 74_579 and s.ai_best_ms == 72_730 and s.ai_bests_ms == sorted(BESTS)
    q = statistics.quantiles(BESTS, n=4, method="inclusive")
    assert (s.ai_p25_ms, s.ai_p75_ms) == (round(q[0]), round(q[2]))
    assert s.driver_best_ms == 78_351 and s.driver_best_lap_id == 100 and s.driver_clean_laps == 2
    assert s.gap_ms == 78_351 - 74_579 and s.gap_pct == 5.06 and s.gap_to_best_ai_ms == 78_351 - 72_730
    assert s.field_rank == 8 and s.field_size == 8 and s.excluded == {"race_lap_1": 7}
    assert s.driver_median_ms is None and s.race_pace_gap_pct is None  # 2 driver laps: no median
    assert s.updated_unix == 123.0 and s.run_id == "run1" and s.ai_difficulty == 35
    row = s.row()
    assert row["excluded"] == {"race_lap_1": 7} and row["online"] is False and row["car_class"] == "F1 World"
    assert s.live_payload() == {
        "session_id": "s1",
        "status": "ok",
        "synthetic": False,
        "ai_difficulty": 35,
        "ai_cars": 7,
        "ai_ref_ms": 74_579,
        "driver_best_ms": 78_351,
        "gap_ms": 3772,
        "gap_pct": 5.06,
        "field_rank": 8,
        "field_size": 8,
    }


def test_median_of_even_count_rounds_half_up() -> None:
    s = summarise(job(field([70_000, 70_001, 71_000, 71_001, 72_000, 72_003])), [])
    assert s.ai_ref_ms == 71_001  # median 71_000.5 -> 71_001 (half up)
    assert s.status == "no_driver_lap" and s.gap_ms is None and s.ai_median_lap_ms is not None


def test_each_exclusion_reason() -> None:
    base = field(BESTS[:5])
    lap = 75_000
    cars = [
        *base,
        car(10, [lap, lap, lap], first_seen=2),  # laps 1-2 not observed (lap 1 counts as race_lap_1 first)
        car(11, [lap, lap + 1, lap + 2], invalid=frozenset({2})),
        car(12, [lap, lap, lap, lap], pit=frozenset({2, 3})),  # a stint ended on lap 1: in-lap 2, out-lap 3
        car(13, [lap, lap, lap, lap], ai_from=3),  # the AI took the car over during lap 3: laps 2-3 were a human's
        car(14, [lap, lap, lap, lap], ended=4),  # the game ended lap 4 away from the line (results skip)
    ]
    s = summarise(job(cars), [])
    ex = s.excluded
    assert ex["race_lap_1"] == 10
    assert ex["not_observed"] == 1  # car 10 lap 2
    assert ex["not_ai_driven"] == 2  # car 13 laps 2 and 3
    assert ex["results_skip"] == 1  # car 14 lap 4
    assert ex["invalid"] == 1  # car 11 lap 2
    assert ex["pit_in_out"] == 2  # car 12 laps 2 and 3
    assert s.ai_cars == 10  # 5 + car 10 (lap 3) + car 11 (lap 3) + car 12 (lap 4) + car 13 (lap 4) + car 14 (2-3)
    assert list(s.excluded) == [k for k in EXCLUSIONS if k in s.excluded]  # stored in the documented order


def test_safety_car_windows_open_closed_and_slack() -> None:
    cars = field(BESTS[:5])
    # each car: lap 2 runs ~[lap1, lap1 + lap2]; car 1: lap 1 76.73 s, lap 2 ends at 149.46 s
    c1 = cars[0]
    l2_end = c1.laps[1].completed_session_time_s
    l2_start = c1.laps[0].completed_session_time_s
    assert l2_end is not None and l2_start is not None
    # a closed period ending 1.5 s before lap 2 started still touches the slack -> excluded
    s = summarise(job([c1], sc=[ScPeriod(l2_start - 30.0, 0, l2_start - 1.5, 0)]), [])
    assert s.excluded.get("safety_car") == 1
    # ending 2.5 s before: outside the 2 s slack -> lap 2 counts
    s = summarise(job([c1], sc=[ScPeriod(l2_start - 30.0, 0, l2_start - 2.5, 0)]), [])
    assert "safety_car" not in s.excluded
    # an open period (end None) counts to +infinity: every later lap is excluded
    s = summarise(job([c1], sc=[ScPeriod(l2_end - 5.0, 0)]), [])
    assert s.excluded.get("safety_car") == 2  # laps 2 and 3
    # an unknown start (None) counts from -infinity
    s = summarise(job([c1], sc=[ScPeriod(None, 0, l2_start - 10.0, 0)]), [])
    assert s.excluded.get("safety_car") is None


def test_flashback_window() -> None:
    c = car(1, [80_000, 75_000, 75_500])  # windows: lap 2 [78, 155], lap 3 [153, 230.5]
    s = summarise(job([c], flashbacks=[(140.0, 150.0)]), [])
    assert s.excluded.get("flashback") == 1 and s.ai_laps == 1  # lap 2 only
    s = summarise(job([c], flashbacks=[(160.0, 156.0)]), [])  # (target, at) in either order
    assert s.excluded.get("flashback") == 1 and s.ai_laps == 1  # lap 3 only
    s = summarise(job([c], flashbacks=[(150.0, 154.0)]), [])  # touches both windows
    assert s.excluded.get("flashback") == 2 and s.ai_laps == 0


def test_red_flag_window() -> None:
    c = car(1, [80_000, 75_000, 75_500])  # windows (2 s slack): lap 2 [78, 155], lap 3 [153, 230.5]
    s = summarise(job([c], red=[ScPeriod(140.0, 0, 150.0, 0)]), [])
    assert s.excluded.get("red_flag") == 1 and s.ai_laps == 1  # lap 2
    s = summarise(job([c], red=[ScPeriod(200.0, 0)]), [])  # no lights out after it: open to the end
    assert s.excluded.get("red_flag") == 1 and s.ai_laps == 1  # lap 3
    # the driver's laps under a red flag are left out like under a safety car (by receive time)
    laps = driver_laps(75_000, 70_000, t_recv=[(0, 100), (100, 200)])
    s = summarise(job(field(BESTS), red=[ScPeriod(0.0, 150, 0.0, 180)]), laps)
    assert s.driver_best_ms == 75_000 and s.driver_clean_laps == 1


def test_fast_outlier_guard() -> None:
    # a lap faster than 90 % of the typical AI car's best is not a lap (e.g. a partial lap given a time)
    cars = [*field(BESTS), car(20, [80_000, 75_000, 60_000])]
    s = summarise(job(cars), [])
    floor = FAST_OUTLIER * statistics.median([*BESTS, 60_000])
    assert 60_000 < floor < 72_730
    assert s.excluded["fast_outlier"] == 1 and s.ai_cars == 8 and s.ai_best_ms == 72_730
    only = car(21, [80_000, 60_000, 60_500])  # every lap of the car is garbage: the car goes
    s = summarise(job([*field(BESTS), only]), [])
    assert s.excluded["fast_outlier"] == 2 and s.ai_cars == 7


def test_timing_consistency_catches_simulated_final_laps_and_its_edge() -> None:
    # lap 3 "completed" 10 s too early: F1 25 filling in the results when the driver skips ahead (a backstop for a
    # skip that LapData did not show: results_skip catches the ones it did)
    sim = car(1, [80_000, 75_000, 75_000], done_override={3: 80.0 + 75.0 + 65.0})
    s = summarise(job([sim]), [])
    assert s.excluded == {"race_lap_1": 1, "timing_inconsistent": 1} and s.ai_laps == 1
    assert TIMING_TOL_S == 1.3  # one Session History cycle (1.1 s for 22 cars) plus margin
    # within the tolerance (1.25 s either way: float sums make "exactly 1.3" ambiguous): kept
    edge = car(1, [80_000, 75_000, 75_000], done_override={3: 155.0 + 75.0 - 1.25})
    assert "timing_inconsistent" not in summarise(job([edge]), []).excluded
    late = car(1, [80_000, 75_000, 75_000], done_override={3: 155.0 + 75.0 + 1.25})
    assert "timing_inconsistent" not in summarise(job([late]), []).excluded
    # 1.4 s early: dropped (real Melbourne: a lap filled in 114 m from the line was 1.70 s early)
    early = car(1, [80_000, 75_000, 75_000], done_override={3: 155.0 + 75.0 - 1.4})
    assert summarise(job([early]), []).excluded["timing_inconsistent"] == 1
    beyond = car(1, [80_000, 75_000, 75_000], done_override={3: 155.0 + 75.0 + 1.4})
    assert summarise(job([beyond]), []).excluded["timing_inconsistent"] == 1
    no_prev = car(1, [80_000, 75_000, 75_000], done_override={2: None})  # previous completion never seen
    ex = summarise(job([no_prev]), []).excluded
    assert ex["timing_inconsistent"] == 2  # lap 2 (no completion of its own) and lap 3 (no previous)


def test_slow_car_cutoff_and_min_ai_cars() -> None:
    bests = [70_000, 71_000, 72_000, 73_000, 77_000, 77_001]  # 77_001 > 110% of 70_000 = 77_000
    s = summarise(job(field(bests)), driver_laps(75_000))
    assert s.excluded["slow_car"] == 1 and s.ai_cars == 5 and s.ai_bests_ms[-1] == 77_000
    assert s.status == "ok"
    few = summarise(job(field(bests[: MIN_AI_CARS - 1])), driver_laps(75_000))
    assert few.status == "too_few_ai_cars" and few.ai_cars == MIN_AI_CARS - 1
    assert few.ai_ref_ms is None and few.ai_bests_ms == [] and few.gap_ms is None and few.field_size is None
    assert few.driver_best_ms == 75_000  # the driver's own data is still known


def test_humans_unknown_cars_and_the_player_are_never_used() -> None:
    cars = [
        *field(BESTS[:4]),
        car(20, [70_000, 60_000, 60_000], ai=False),  # human
        car(21, [70_000, 60_000, 60_000], ai=None),  # unknown
        car(0, [70_000, 60_000, 60_000], player=True),  # the player's own history
    ]
    s = summarise(job(cars), driver_laps(75_000))
    assert s.ai_cars == 4 and s.status == "too_few_ai_cars" and s.excluded == {"race_lap_1": 4}


def test_status_precedence() -> None:
    cars = field(BESTS)
    laps = driver_laps(75_000)
    assert summarise(job(cars, session_type=SessionType.TIME_TRIAL), laps).status == "time_trial"
    changed = summarise(job(cars, status=DIFFICULTY_CHANGED), laps)
    assert changed.status == "difficulty_changed" and changed.ai_difficulty is None
    assert changed.ai_cars == 7 and changed.ai_laps == 14 and changed.excluded == {"race_lap_1": 7}
    assert changed.ai_ref_ms is None and changed.gap_ms is None
    unknown = summarise(job(cars, status=DIFFICULTY_UNKNOWN), laps)
    assert unknown.status == "unknown_difficulty" and unknown.ai_ref_ms is None
    assert summarise(job(cars[:3], status=DIFFICULTY_UNKNOWN), laps).status == "unknown_difficulty"
    assert summarise(job(cars[:3]), laps).status == "too_few_ai_cars"
    assert summarise(job(cars), []).status == "no_driver_lap"
    assert summarise(job(cars), laps).status == "ok"


def test_non_race_has_no_race_pace_and_counts_lap_one() -> None:
    # qualifying: no race-start exclusion; lap 1 has no previous completion, so the timing check drops it
    cars = field(BESTS)
    s = summarise(job(cars, session_type=SessionType.QUALIFYING), driver_laps(75_000, 75_100, 75_200))
    assert s.status == "ok" and "race_lap_1" not in s.excluded and s.excluded["timing_inconsistent"] == 7
    assert s.ai_median_lap_ms is None and s.race_pace_gap_pct is None
    assert s.driver_median_ms == 75_100  # still the driver's own median


def test_driver_median_needs_three_laps_and_race_pace() -> None:
    s = summarise(job(field(BESTS)), driver_laps(75_000, 75_100, 75_300))
    assert s.driver_median_ms == 75_100 and s.driver_clean_laps == 3
    assert s.ai_median_lap_ms is not None and s.race_pace_gap_pct == round(100 * (75_100 / s.ai_median_lap_ms - 1), 2)
    two = summarise(job(field(BESTS)), driver_laps(75_000, 75_100))
    assert two.driver_median_ms is None and two.race_pace_gap_pct is None


def test_driver_laps_under_safety_car_are_dropped_by_receive_time() -> None:
    laps = driver_laps(75_000, 70_000, 76_000, t_recv=[(0, 100), (100, 200), (200, 300)])
    laps.append({"id": 200, "lap_number": 9, "lap_time_ms": 77_000, "clean": True})  # no receive times: kept
    laps.append({"id": 201, "lap_number": 10, "lap_time_ms": 60_000, "clean": False})  # not clean
    laps.append({"id": 202, "lap_number": 11, "lap_time_ms": None, "clean": True})  # no time
    s = summarise(job(field(BESTS), sc=[ScPeriod(0.0, 150, 0.0, 180)]), laps)
    assert s.driver_best_ms == 75_000 and s.driver_clean_laps == 3  # the 70.0 lap ran under the SC
    open_sc = summarise(job(field(BESTS), sc=[ScPeriod(0.0, 250)]), laps)
    assert open_sc.driver_clean_laps == 3 and open_sc.driver_best_ms == 70_000  # only the 76.0 lap overlaps


def test_rank_ties_do_not_count_as_faster() -> None:
    s = summarise(job(field(BESTS)), driver_laps(74_579))
    assert s.field_rank == 4  # 72_730, 73_000, 74_000 are faster; the equal 74_579 is not
    assert s.gap_ms == 0 and s.gap_pct == 0.0


# ---------------------------------------------------------------------------------------------- collector
def info(
    uid: str = UID,
    *,
    ai: int | None = 35,
    t: float = 1.0,
    ns: int = 1,
    sc: str | None = "none",
    weather: str | None = "clear",
    session_type: SessionType = SessionType.RACE,
) -> SessionInfo:
    return SessionInfo(
        game=Game.F1_25,
        t_recv_ns=ns,
        session_uid=uid,
        track_id="f1:17",
        track_name="Austria",
        track_length_m=4318.0,
        session_type=session_type,
        ai_difficulty=ai,
        session_time_s=t,
        safety_car_status=sc,
        weather=Weather(condition=weather),
        formula="F1 World",
        network_game=False,
    )


def test_resolve_difficulty() -> None:
    assert resolve_difficulty({35: 9}) == (None, DIFFICULTY_UNKNOWN)
    assert resolve_difficulty({35: 10}) == (35, DIFFICULTY_KNOWN)
    assert resolve_difficulty({35: 1200}) == (35, DIFFICULTY_KNOWN)
    # any second level: the laps at the old and the new level cannot be told apart
    assert resolve_difficulty({35: 9, 40: 1}) == (None, DIFFICULTY_CHANGED)
    assert resolve_difficulty({35: 1080, 60: 120}) == (None, DIFFICULTY_CHANGED)  # 60 for the last minute of 10
    assert resolve_difficulty({35: 1199, 60: 1}) == (None, DIFFICULTY_CHANGED)
    assert resolve_difficulty({35: 8, 40: 2}) == (None, DIFFICULTY_CHANGED)


def test_collector_difficulty_mode_and_unchanged() -> None:
    c = AiPaceCollector()
    c.reset(UID)
    results = [c.on_info(info(ai=None)) for _ in range(3)]  # the unfilled tail of the first packets
    assert results == [UNCHANGED] * 3 and c.diff_unknown == 3
    results = [c.on_info(info(ai=35)) for _ in range(10)]
    assert results[:9] == [UNCHANGED] * 9 and results[9] == 35  # resolved at the 10th known reading
    assert c.difficulty == (35, DIFFICULTY_KNOWN)
    assert c.on_info(info(ai=35)) is UNCHANGED
    assert c.on_info(info(ai=50)) is None  # a second level: changed at once
    assert c.difficulty == (None, DIFFICULTY_CHANGED)
    assert c.on_info(info(ai=35)) is UNCHANGED  # and it stays changed


def test_collector_weather_and_safety_car_transitions() -> None:
    assert weather_class(set()) is None
    assert weather_class({"clear", "overcast"}) == "dry"
    assert weather_class({"light_rain", "storm"}) == "wet"
    assert weather_class({"clear", "light_rain"}) == "mixed"
    c = AiPaceCollector()
    c.reset(UID)
    c.on_info(info(t=10.0, ns=10, sc="none"))
    c.on_info(info(t=20.0, ns=20, sc="full"))
    c.on_info(info(t=21.0, ns=21, sc="virtual"))  # still the same period
    c.on_info(info(t=22.0, ns=22, sc=None))  # unknown changes nothing
    c.on_info(info(t=30.0, ns=30, sc="none"))
    c.on_info(info(t=40.0, ns=40, sc="formation_lap", weather="light_rain"))
    assert c.sc_periods == [ScPeriod(20.0, 20, 30.0, 30)]
    j = c.job("s1", synthetic=False, final=True)
    assert j.sc_periods == (ScPeriod(20.0, 20, 30.0, 30), ScPeriod(40.0, 40)) and j.final
    assert j.weather_class == "mixed" and j.car_class == "F1 World" and j.network_game is False
    assert j.session_type == "race" and j.difficulty_status == DIFFICULTY_UNKNOWN and j.run_id == c.run_id


def test_collector_ignores_stale_uid_history_and_records_flashbacks() -> None:
    c = AiPaceCollector()
    c.reset(UID)
    c.on_history(car(1, [80_000], uid="999"))
    assert c.histories == {} and not c.has_data
    c.on_history(car(1, [80_000]))
    c.on_history(car(1, [80_000, 79_000]))  # the latest list replaces the previous one
    assert len(c.histories[1].laps) == 2 and c.has_data
    c.on_flashback(
        GameEvent(
            kind=EventKind.FLASHBACK,
            game=Game.F1_25,
            t_recv_ns=0,
            session_time_s=120.0,
            payload={"flashbackSessionTime": 115.5},
        )
    )
    c.on_flashback(GameEvent(kind=EventKind.FLASHBACK, game=Game.F1_25, t_recv_ns=0, payload={}))  # unusable
    assert c.flashbacks == [(115.5, 120.0)]
    run = c.run_id
    c.reset("43")
    assert c.histories == {} and c.flashbacks == [] and c.run_id != run and c.game_uid == "43"


def test_collector_red_flag_periods() -> None:
    def ev(kind: EventKind, t: float) -> GameEvent:
        return GameEvent(kind=kind, game=Game.F1_25, t_recv_ns=int(t * 1e9), session_time_s=t)

    c = AiPaceCollector()
    c.reset(UID)
    c.on_event(ev(EventKind.LIGHTS_OUT, 1.0))  # the race start: no red flag open, nothing
    c.on_event(ev(EventKind.RED_FLAG, 300.0))
    c.on_event(ev(EventKind.RED_FLAG, 310.0))  # the same period
    c.on_event(ev(EventKind.LIGHTS_OUT, 900.0))  # the restart
    c.on_event(ev(EventKind.RED_FLAG, 1500.0))  # never restarted: open to the end
    j = c.job("s1", synthetic=False, final=True)
    assert j.red_flags == (
        ScPeriod(300.0, 300_000_000_000, 900.0, 900_000_000_000),
        ScPeriod(1500.0, 1_500_000_000_000),
    )
    assert j.sc_periods == ()


# ---------------------------------------------------------------------------------------------- session manager
class _Worker:
    def __init__(self) -> None:
        self.jobs: list[Any] = []
        self.ai_jobs: list[AiPaceJob] = []

    def submit(self, job: Any) -> None:
        self.jobs.append(job)

    def submit_ai_pace(self, job: AiPaceJob) -> None:
        self.ai_jobs.append(job)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[tuple[Database, DbWriter]]:
    db = Database(tmp_path / "t.sqlite3")
    writer = DbWriter(db)
    yield db, writer
    writer.close()


def test_session_manager_collects_per_game_session(store: tuple[Database, DbWriter]) -> None:
    db, writer = store
    worker = _Worker()
    sm = SessionManager(writer, LiveState(), cast(AnalysisWorker, worker), source="udp:20777")
    sm.handle(car(1, [80_000]))  # no session yet: dropped, never starts one
    assert sm.session_id is None
    for k in range(12):
        sm.handle(info(ai=None if k < 2 else 35, t=float(k)))
    first = sm.session_id
    assert first is not None
    sm.handle(car(1, [80_000, 75_000]))
    sm.handle(car(2, [80_000, 75_000], uid="999"))  # another game session's packet: ignored
    sm.handle(
        GameEvent(
            kind=EventKind.FLASHBACK,
            game=Game.F1_25,
            t_recv_ns=5,
            session_time_s=50.0,
            payload={"flashbackSessionTime": 45.0},
        )
    )
    sm.handle(info(uid="43", ai=40))  # a new game session ends the first one
    assert len(worker.ai_jobs) == 1
    j = worker.ai_jobs[0]
    assert j.session_id == first and j.final and j.ai_difficulty == 35 and [h.car_index for h in j.histories] == [1]
    assert j.flashbacks == ((45.0, 50.0),)
    assert sm._ai.game_uid == "43" and sm._ai.histories == {}  # reset for the new game session
    writer.flush()
    with db.read() as c:
        assert repo.get_session(c, first)["ai_difficulty"] == 35  # type: ignore[index]
        second = repo.get_session(c, str(sm.session_id))
    assert second is not None and second["ai_difficulty"] is None  # 1 reading: not resolved, nothing written
    sm.end()
    assert len(worker.ai_jobs) == 2 and worker.ai_jobs[1].difficulty_status == DIFFICULTY_UNKNOWN


def test_session_manager_never_submits_for_games_without_ai_data(store: tuple[Database, DbWriter]) -> None:
    _, writer = store
    worker = _Worker()
    sm = SessionManager(writer, LiveState(), cast(AnalysisWorker, worker), source="test")
    sm.handle(SessionInfo(game=Game.GT7, t_recv_ns=1, session_uid=None, track_id="gt7:x"))
    sm.end()
    assert worker.ai_jobs == []


def test_session_manager_writes_a_changed_difficulty(store: tuple[Database, DbWriter]) -> None:
    db, writer = store
    sm = SessionManager(writer, LiveState(), cast(AnalysisWorker, _Worker()), source="udp:20777")
    for _ in range(10):
        sm.handle(info(ai=35))
    for _ in range(3):
        sm.handle(info(ai=50))
    writer.flush()
    with db.read() as c:
        assert repo.get_session(c, str(sm.session_id))["ai_difficulty"] is None  # type: ignore[index]


def test_session_manager_hands_red_flags_to_the_collector(store: tuple[Database, DbWriter]) -> None:
    _, writer = store
    worker = _Worker()
    sm = SessionManager(writer, LiveState(), cast(AnalysisWorker, worker), source="udp:20777")
    for k in range(12):
        sm.handle(info(t=float(k)))
    for kind, t in ((EventKind.RED_FLAG, 300.0), (EventKind.LIGHTS_OUT, 900.0)):
        sm.handle(GameEvent(kind=kind, game=Game.F1_25, t_recv_ns=int(t * 1e9), session_time_s=t))
    sm.end()
    (j,) = worker.ai_jobs
    assert j.red_flags == (ScPeriod(300.0, 300_000_000_000, 900.0, 900_000_000_000),)
