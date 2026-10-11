"""Race strategy inputs from the F1 adapter (``RaceTiming``, ``TyreSetsInfo``, Session extras). Unit tier: packets
built here with the decoder's own layouts; the recorded tier is ``tests/recorded/test_strategy_real.py``."""

from __future__ import annotations

import os
import time

import numpy as np
import pytest

from pitwall.adapters.base import SupportLevel
from pitwall.adapters.f1 import packets as P
from pitwall.adapters.f1.adapter import F1_25_INFO, TIMING_HZ, F1Adapter
from pitwall.model.telemetry import RaceTiming, SessionInfo, TyreSetsInfo
from tests.unit.strategy_helpers import PLAYER, UID, lap_packet, session_packet, status_packet, tyre_sets_packet


def _row(pos: int, **kw: object) -> dict[str, object]:
    return {
        "carPosition": pos,
        "currentLapNum": 3,
        "lapDistance": 100.0 * pos,
        "resultStatus": 2,
        "driverStatus": 4,
        **kw,
    }


def _timings(out: list[object]) -> list[RaceTiming]:
    return [e for e in out if isinstance(e, RaceTiming)]


def test_timing_cadence_follows_the_game_clock_and_rearms_on_rewind() -> None:
    a = F1Adapter(field_hz=0.0)
    cars = {0: _row(1), PLAYER: _row(2)}
    ticks: list[float] = []
    for k in range(300):  # 5 s at 60 Hz
        t = k / 60
        ticks += [r.session_time_s for r in _timings(a.decode(lap_packet(t, cars, frame=k), 0))]
    dt = np.diff(ticks)
    assert len(ticks) == 10 and dt.min() >= 1 / TIMING_HZ - 0.006
    # a flashback (clock back by 2 s) re-arms at once
    back = _timings(a.decode(lap_packet(3.0, cars, frame=400), 0))
    assert len(back) == 1 and back[0].session_time_s == pytest.approx(3.0)


def test_a_pit_status_change_ticks_at_once() -> None:
    a = F1Adapter(field_hz=0.0)
    a.decode(lap_packet(0.0, {0: _row(1), PLAYER: _row(2)}), 0)
    assert not _timings(a.decode(lap_packet(0.1, {0: _row(1), PLAYER: _row(2)}), 0))  # not due
    entry = _timings(a.decode(lap_packet(0.15, {0: _row(1, pitStatus=1), PLAYER: _row(2)}), 0))
    assert len(entry) == 1 and entry[0].cars[0].pit_status == 1


def test_field_mapping_unknowns_stay_unknown() -> None:
    a = F1Adapter(field_hz=0.0)
    cars = {
        0: _row(1, deltaToCarInFrontMSPart=0, deltaToRaceLeaderMSPart=0, gridPosition=0, lastLapTimeInMS=0),
        PLAYER: _row(
            2,
            deltaToCarInFrontMSPart=65403,
            deltaToRaceLeaderMSPart=500,
            deltaToRaceLeaderMinutesPart=1,
            gridPosition=4,
            lastLapTimeInMS=78351,
            pitLaneTimerActive=0,
            pitLaneTimeInLaneInMS=999,
            pitStopTimerInMS=0,
            numPitStops=1,
        ),
        2: _row(
            3,
            pitStatus=2,
            pitLaneTimerActive=1,
            pitLaneTimeInLaneInMS=7157,
            pitStopTimerInMS=283,
            pitStopShouldServePen=1,
            driverStatus=2,
            deltaToCarInFrontMSPart=1235,
        ),
        3: {"carPosition": 4, "resultStatus": 1},  # inactive slot: left out
    }
    (rt,) = _timings(a.decode(lap_packet(1.0, cars), 0))
    assert [c.car_index for c in rt.cars] == [0, PLAYER, 2] and rt.player_index == PLAYER
    leader, me, pitting = rt.cars
    assert leader.gap_ahead_ms is None and leader.gap_leader_ms is None  # 0 = not reported / the leader
    assert leader.grid_position is None and leader.last_lap_ms is None
    assert me.is_player and not leader.is_player
    assert me.gap_ahead_ms is None  # 65403: a negative delta wrapped into the uint16 (real Monza excerpt)
    assert me.gap_leader_ms == 60_500 and me.grid_position == 4 and me.last_lap_ms == 78351 and me.num_pit_stops == 1
    assert me.pit_lane_time_ms is None and me.pit_stop_timer_ms is None  # timer inactive / 0
    assert pitting.pit_status == 2 and pitting.pit_lane_time_ms == 7157 and pitting.pit_stop_timer_ms == 283
    assert pitting.serve_penalty and pitting.driver_status == "in_lap" and pitting.gap_ahead_ms == 1235
    assert me.tyre_visual is None and me.tyre_age_laps is None  # no CarStatus yet: unknown


def test_car_status_compound_and_age_ride_along() -> None:
    a = F1Adapter(field_hz=0.0)
    a.decode(
        status_packet(0.0, {0: {"visualTyreCompound": 17, "tyresAgeLaps": 12}, PLAYER: {"visualTyreCompound": 16}}), 0
    )
    (rt,) = _timings(a.decode(lap_packet(0.0, {0: _row(1), PLAYER: _row(2)}), 0))
    assert (rt.cars[0].tyre_visual, rt.cars[0].tyre_age_laps) == ("medium", 12)
    assert rt.cars[1].tyre_visual == "soft"


def test_format_2026_has_24_cars() -> None:
    a = F1Adapter(field_hz=0.0)
    (rt,) = _timings(a.decode(lap_packet(0.0, {0: _row(1), PLAYER: _row(2), 23: _row(3)}, fmt=2026), 0))
    assert [c.car_index for c in rt.cars] == [0, PLAYER, 23]


def test_no_timing_in_time_trial() -> None:
    a = F1Adapter(field_hz=0.0)
    a.decode(session_packet(0.0, session_type=18), 0)
    assert not _timings(a.decode(lap_packet(0.0, {PLAYER: _row(1)}), 0))
    assert not _timings(F1Adapter(timing_hz=0.0).decode(lap_packet(0.0, {PLAYER: _row(1)}), 0))  # disabled
    with pytest.raises(ValueError):
        F1Adapter(timing_hz=-1.0)


def test_session_extras_for_strategy() -> None:
    a = F1Adapter(field_hz=0.0)
    (info,) = [e for e in a.decode(session_packet(0.0), 0) if isinstance(e, SessionInfo)]
    x = info.extra
    assert x["session_type_id"] == 15 and x["forecast_accuracy"] == 1 and x["pit_rejoin_position"] == 7
    assert (x["num_safety_car_periods"], x["num_vsc_periods"], x["num_red_flag_periods"]) == (2, 1, 0)


SETS = [
    {
        "actualTyreCompound": 19,
        "visualTyreCompound": 16,
        "wear": 11,
        "available": 1,
        "recommendedSession": 5,
        "lifeSpan": 22,
        "usableLife": 27,
        "lapDeltaTime": 0,
        "fitted": 1,
    },
    {
        "actualTyreCompound": 17,
        "visualTyreCompound": 17,
        "available": 1,
        "lifeSpan": 40,
        "usableLife": 40,
        "lapDeltaTime": -158,
    },
    {
        "actualTyreCompound": 7,
        "visualTyreCompound": 7,
        "available": 1,
        "lifeSpan": 73,
        "usableLife": 73,
        "lapDeltaTime": 3325,
    },
]


def test_tyre_sets_player_only_deduplicated() -> None:
    a = F1Adapter(field_hz=0.0)
    a.decode(lap_packet(0.0, {PLAYER: _row(1)}), 0)  # the session is known: TyreSets only follow one
    out = [e for e in a.decode(tyre_sets_packet(0.0, SETS), 0) if isinstance(e, TyreSetsInfo)]
    assert len(out) == 1
    ts = out[0]
    assert ts.car_index == PLAYER and ts.fitted_index == 0 and len(ts.sets) == P.NUM_TYRE_SETS
    s0, s1, s2 = ts.sets[:3]
    assert (s0.visual, s0.actual, s0.wear_pct, s0.life_span_laps, s0.usable_life_laps, s0.fitted) == (
        "soft",
        "C2",
        11,
        22,
        27,
        True,
    )
    assert (s1.visual, s1.lap_delta_ms, s1.available) == ("medium", -158, True)
    assert (s2.visual, s2.lap_delta_ms) == ("inter", 3325)
    assert not ts.sets[5].available
    assert not [e for e in a.decode(tyre_sets_packet(1.0, SETS), 0) if isinstance(e, TyreSetsInfo)]  # unchanged
    assert not a.decode(tyre_sets_packet(1.0, SETS, car_idx=0), 0)  # another car's sets
    changed = [dict(SETS[0], wear=12), *SETS[1:]]
    assert [e for e in a.decode(tyre_sets_packet(2.0, changed), 0) if isinstance(e, TyreSetsInfo)]


def test_tyre_sets_fitted_index_past_the_array_is_unknown() -> None:
    a = F1Adapter(field_hz=0.0)
    a.decode(lap_packet(0.0, {PLAYER: _row(1)}), 0)
    (ts,) = [e for e in a.decode(tyre_sets_packet(0.0, SETS, fitted_idx=255), 0) if isinstance(e, TyreSetsInfo)]
    assert ts.fitted_index is None


def test_tyre_sets_of_another_session_never_reset_the_session() -> None:
    a = F1Adapter(field_hz=0.0)
    a.decode(lap_packet(0.0, {PLAYER: _row(1)}), 0)
    assert a.decode(tyre_sets_packet(0.1, SETS, uid=UID + 1), 0) == []
    assert a._session_uid == UID and a.stats.ignored == 1


def test_tyre_sets_before_any_session_packet_are_ignored() -> None:
    # as Session History on the integration branch: a packet that only follows a session never starts one
    a = F1Adapter(field_hz=0.0)
    assert a.decode(tyre_sets_packet(0.0, SETS), 0) == []
    assert a._session_uid is None and a.stats.ignored == 1


def test_a_car_with_no_compound_has_no_tyre_age() -> None:
    # online lobbies may restrict other cars' telemetry: no compound code, and its age field would read "0 laps"
    a = F1Adapter(field_hz=0.0)
    status = status_packet(
        0.0, {0: {"visualTyreCompound": 0, "tyresAgeLaps": 0}, PLAYER: {"visualTyreCompound": 17, "tyresAgeLaps": 4}}
    )
    a.decode(status, 0)
    (rt,) = _timings(a.decode(lap_packet(0.0, {0: _row(1), PLAYER: _row(2)}), 0))
    other = next(c for c in rt.cars if c.car_index == 0)
    me = next(c for c in rt.cars if c.is_player)
    assert (other.tyre_visual, other.tyre_age_laps) == (None, None)
    assert (me.tyre_visual, me.tyre_age_laps) == ("medium", 4)


def test_capability_rows_are_spec_level_only() -> None:
    for key in ("race_timing", "tyre_sets"):
        assert F1_25_INFO.fields[key].level is SupportLevel.SPEC_IMPLEMENTED


def test_timing_tick_cost_is_well_under_the_ingest_budget() -> None:
    """A timing tick (22 racing cars + CarStatus) adds well under 0.3 ms at p99 (CI-tolerant, like the field tick)."""
    cars = {i: _row(i + 1, deltaToCarInFrontMSPart=900 + i, deltaToRaceLeaderMSPart=1000 * i) for i in range(22)}
    status = status_packet(0.0, {i: {"visualTyreCompound": 17, "tyresAgeLaps": i} for i in range(22)})
    packets = [lap_packet(k * 0.6, cars, frame=k) for k in range(400)]  # every packet is due (0.6 s apart)
    a = F1Adapter(field_hz=0.0)
    b = F1Adapter(field_hz=0.0, timing_hz=0.0)
    a.decode(status, 0)
    b.decode(status, 0)
    with_tick, without = np.empty(len(packets)), np.empty(len(packets))
    for i, p in enumerate(packets):
        t0 = time.perf_counter_ns()
        out = a.decode(p, 0)
        with_tick[i] = time.perf_counter_ns() - t0
        assert _timings(out)
        t0 = time.perf_counter_ns()
        b.decode(p, 0)
        without[i] = time.perf_counter_ns() - t0
    added_us = (with_tick - np.median(without)) / 1e3
    limit = 300.0 * (3 if os.environ.get("CI") else 1)
    assert np.percentile(added_us, 99) < limit, np.percentile(added_us, [50, 99])
