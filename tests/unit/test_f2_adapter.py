"""F2 support in the F1 adapter and the lap assembler: one lap per completion (one-shot qualifying), no ERS for F2
cars, the DRS fields, and a one-sample lap never counting as clean.

The one-shot sequence is the one recorded on the owner's PS5 (F1 25 v1.26, 2026-10-11, Sakhir one-shot qualifying):
at the line the lap number advances 1 -> 2 with the lap's time, and 17 ms later the result turns "finished" with
lastLapTimeInMS unchanged, on a lap that is never driven.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from pitwall.adapters.f1 import packets as P
from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.analysis.laps import CHANNELS, LapAssembler, LapFlag, LapTrace
from pitwall.core.live import frame_to_dict
from pitwall.model.telemetry import CarFrame, Game, LapCompletion
from tests.unit.strategy_helpers import PLAYER, header, lap_packet, status_packet

FINISHED = 3
ACTIVE = 2


def _lap(t: float, adapter: F1Adapter, **row: object) -> list[LapCompletion]:
    base: dict[str, object] = {"resultStatus": ACTIVE, "driverStatus": 1, "sector": 0, "lapDistance": 1.0}
    out = adapter.decode(lap_packet(t, {PLAYER: {**base, **row}}), int(t * 1e9))
    return [e for e in out if isinstance(e, LapCompletion)]


def _session_packet(t: float, formula: int, session_type: int = 9) -> bytes:
    layout = P.LAYOUTS[2025]
    head = P.SESSION_HEAD.pack(
        {"totalLaps": 1, "trackLength": 5408, "sessionType": session_type, "trackId": 3, "formula": formula}
    )
    mid = P.SESSION_MID.pack({"numWeatherForecastSamples": 0})
    rest = P.MARSHAL_ZONE.pack({}) * P.NUM_MARSHAL_ZONES + mid
    rest += P.WEATHER_FORECAST_SAMPLE.pack({}) * P.NUM_WEATHER_SAMPLES
    return header(P.PacketId.SESSION, t) + head + rest + layout.session_tail.pack({})


def _telemetry(t: float) -> bytes:
    layout = P.LAYOUTS[2025]
    rows = b"".join(layout.car_telemetry.pack({"speed": 200}) for _ in range(layout.max_cars))
    return header(P.PacketId.CAR_TELEMETRY, t) + rows + P.CAR_TELEMETRY_TAIL.pack({})


def test_one_shot_qualifying_reports_one_lap() -> None:
    a = F1Adapter(field_hz=0, timing_hz=0)
    assert _lap(100.0, a, currentLapNum=1, lastLapTimeInMS=0, sector=2, lapDistance=5400.0) == []
    done = _lap(121.794, a, currentLapNum=2, lastLapTimeInMS=116_133)
    assert [(c.lap_number, c.lap_time_ms, c.final) for c in done] == [(1, 116_133, False)]
    # the result turns "finished" 17 ms later, the last-lap time unchanged: no second (made-up) lap
    assert _lap(121.811, a, currentLapNum=2, lastLapTimeInMS=116_133, resultStatus=FINISHED) == []
    for k in range(20):  # the game keeps sending the same: still nothing
        assert _lap(121.83 + k * 0.02, a, currentLapNum=2, lastLapTimeInMS=116_133, resultStatus=FINISHED) == []
    assert a.stats.by_type.get("LAP_FINAL_WITHOUT_NEW_TIME") == 1


def test_race_final_lap_is_reported_when_its_time_arrives_first_or_a_packet_late() -> None:
    # recorded order (Sakhir feature race): the new time one packet before the result turns "finished"
    a = F1Adapter(field_hz=0, timing_hz=0)
    _lap(460.0, a, currentLapNum=4, lastLapTimeInMS=108_052, sector=2, lapDistance=5400.0)
    assert [c.lap_number for c in _lap(466.195, a, currentLapNum=5, lastLapTimeInMS=132_809)] == [4]
    assert _lap(575.036, a, currentLapNum=5, lastLapTimeInMS=108_847) == []
    final = _lap(575.052, a, currentLapNum=5, lastLapTimeInMS=108_847, resultStatus=FINISHED)
    assert [(c.lap_number, c.lap_time_ms, c.final) for c in final] == [(5, 108_847, True)]
    assert _lap(575.07, a, currentLapNum=5, lastLapTimeInMS=108_847, resultStatus=FINISHED) == []  # once
    # the new time a packet after "finished": still kept
    b = F1Adapter(field_hz=0, timing_hz=0)
    _lap(460.0, b, currentLapNum=4, lastLapTimeInMS=108_052)
    _lap(466.195, b, currentLapNum=5, lastLapTimeInMS=132_809)
    assert _lap(575.036, b, currentLapNum=5, lastLapTimeInMS=132_809, resultStatus=FINISHED) == []
    late = _lap(575.052, b, currentLapNum=5, lastLapTimeInMS=108_847, resultStatus=FINISHED)
    assert [(c.lap_number, c.lap_time_ms, c.final) for c in late] == [(5, 108_847, True)]
    # the same packet (the code before this fix): still reported
    c = F1Adapter(field_hz=0, timing_hz=0)
    _lap(460.0, c, currentLapNum=4, lastLapTimeInMS=108_052)
    _lap(466.195, c, currentLapNum=5, lastLapTimeInMS=132_809)
    same = _lap(575.05, c, currentLapNum=5, lastLapTimeInMS=108_847, resultStatus=FINISHED)
    assert [(x.lap_number, x.final) for x in same] == [(5, True)]


def test_final_lap_in_exactly_the_previous_laps_time_is_reported_after_a_grace() -> None:
    """Review C7: a final lap driven in the previous lap's time to the millisecond shows no new time; it is reported
    once FINAL_TIME_GRACE_S of session time has passed, because the car had been on that lap for most of a lap. The
    one-shot lap number (17 ms old at "finished") never is."""
    a = F1Adapter(field_hz=0, timing_hz=0)
    _lap(460.0, a, currentLapNum=4, lastLapTimeInMS=108_052, sector=2, lapDistance=5400.0)
    assert [c.lap_number for c in _lap(466.195, a, currentLapNum=5, lastLapTimeInMS=108_847)] == [4]
    assert _lap(575.04, a, currentLapNum=5, lastLapTimeInMS=108_847, resultStatus=FINISHED) == []  # waits
    assert _lap(575.5, a, currentLapNum=5, lastLapTimeInMS=108_847, resultStatus=FINISHED) == []
    same = _lap(576.1, a, currentLapNum=5, lastLapTimeInMS=108_847, resultStatus=FINISHED)
    assert [(c.lap_number, c.lap_time_ms, c.final) for c in same] == [(5, 108_847, True)]
    assert _lap(577.0, a, currentLapNum=5, lastLapTimeInMS=108_847, resultStatus=FINISHED) == []  # once
    assert a.stats.by_type.get("LAP_FINAL_SAME_TIME") == 1
    # one-shot qualifying: seconds of "finished" packets after the line still report nothing
    b = F1Adapter(field_hz=0, timing_hz=0)
    _lap(100.0, b, currentLapNum=1, lastLapTimeInMS=0, sector=2, lapDistance=5400.0)
    assert [c.lap_number for c in _lap(121.794, b, currentLapNum=2, lastLapTimeInMS=116_133)] == [1]
    for k in range(60):
        assert _lap(121.811 + k * 0.1, b, currentLapNum=2, lastLapTimeInMS=116_133, resultStatus=FINISHED) == []
    # joined mid-lap: when the lap began is not known, so an unchanged time is never taken for the final lap's
    c = F1Adapter(field_hz=0, timing_hz=0)
    _lap(10.0, c, currentLapNum=5, lastLapTimeInMS=95_000)
    for k in range(30):
        assert _lap(80.0 + k * 0.1, c, currentLapNum=5, lastLapTimeInMS=95_000, resultStatus=FINISHED) == []


def test_joined_mid_race_the_old_time_is_not_the_final_lap() -> None:
    a = F1Adapter(field_hz=0, timing_hz=0)
    _lap(10.0, a, currentLapNum=5, lastLapTimeInMS=95_000)  # first LapData: lap 4's time on show
    assert _lap(80.0, a, currentLapNum=5, lastLapTimeInMS=95_000, resultStatus=FINISHED) == []
    assert [x.lap_time_ms for x in _lap(80.02, a, currentLapNum=5, lastLapTimeInMS=96_100, resultStatus=FINISHED)] == [
        96_100
    ]


def _frame(a: F1Adapter, t: float) -> CarFrame:
    frames = [e for e in a.decode(_telemetry(t), int(t * 1e9)) if isinstance(e, CarFrame)]
    assert len(frames) == 1
    return frames[0]


def _status(t: float, values: Mapping[str, object]) -> bytes:
    return status_packet(t, {PLAYER: values})


def test_f2_cars_have_no_ers_and_drs_fields_are_read() -> None:
    a = F1Adapter(field_hz=0, timing_hz=0)
    zeros = {"ersStoreEnergy": 0.0, "ersDeployMode": 0, "drsAllowed": 0, "drsActivationDistance": 120}
    a.decode(_status(1.0, zeros), 1)
    f = _frame(a, 1.01)
    # before the first Session packet the formula is not known (joining a running F2 session): no ERS value yet
    assert f.ers_store_j is None and f.ers_deploy_mode is None
    a.decode(_session_packet(1.1, formula=2), 2)
    a.decode(_status(1.2, zeros), 3)
    f = _frame(a, 1.21)
    assert f.ers_store_j is None and f.ers_deploy_mode is None  # F2: no ERS, not an empty store
    assert f.drs_allowed is False and f.drs_activation_m == 120.0
    d = frame_to_dict(f)
    assert d["ers_store_j"] is None and d["drs_allowed"] is False and d["drs_activation_m"] == 120
    a.decode(_status(1.3, {**zeros, "drsAllowed": 1, "drsActivationDistance": 0}), 4)
    f = _frame(a, 1.31)
    assert f.drs_allowed is True and f.drs_activation_m is None  # 0 = not counting down: unknown, not 0 m


def test_f1_cars_keep_their_ers() -> None:
    a = F1Adapter(field_hz=0, timing_hz=0)
    a.decode(_session_packet(1.0, formula=0, session_type=15), 1)
    a.decode(_status(1.1, {"ersStoreEnergy": 3.2e6, "ersDeployMode": 1}), 2)
    f = _frame(a, 1.11)
    assert f.ers_store_j == 3.2e6 and f.ers_deploy_mode == 1


# ---------------------------------------------------------------------------------------------- lap assembler
def _cf(t: float, d: float, lap: int) -> CarFrame:
    return CarFrame(
        game=Game.F1_25,
        t_recv_ns=int(t * 1e9),
        session_time_s=t,
        lap_number=lap,
        lap_distance_m=d,
        current_lap_time_ms=int(t * 1000),
        speed_kph=200.0,
        throttle=1.0,
        brake=0.0,
        steering=0.0,
    )


def test_a_one_sample_lap_is_incomplete_whatever_the_track_length() -> None:
    for length in (5408.0, None):
        laps: list[LapTrace] = []
        asm = LapAssembler(laps.append, track_length_m=length)
        asm.feed(_cf(1.0, 1.0, 2))  # one frame of a lap that is never driven
        asm.feed_completion(
            LapCompletion(game=Game.F1_25, t_recv_ns=2, lap_number=2, lap_time_ms=116_133, valid=True, final=True)
        )
        assert len(laps) == 1 and laps[0].n == 1
        assert LapFlag.INCOMPLETE in laps[0].flags and not laps[0].clean, length


def test_a_session_ending_one_frame_into_a_lap_stores_no_lap() -> None:
    """Review U1: one-shot qualifying ends one frame into "lap 2"; flushing that frame stored an untimed one-sample lap
    (Review: "0 of 2 clean · 2 not used"). A lap of fewer than 2 samples is dropped at flush; 2 or more stay."""
    laps: list[LapTrace] = []
    asm = LapAssembler(laps.append, track_length_m=5408.0)
    asm.feed(_cf(121.8, 2.0, 2))
    asm.flush()
    assert laps == []
    asm.feed(_cf(200.0, 2.0, 3))
    asm.feed(_cf(200.1, 9.0, 3))
    asm.flush()
    assert [(lap.lap_number, lap.n, lap.lap_time_ms) for lap in laps] == [(3, 2, None)]
    assert LapFlag.INCOMPLETE in laps[0].flags


def test_a_full_lap_is_still_clean() -> None:
    laps: list[LapTrace] = []
    asm = LapAssembler(laps.append, track_length_m=1000.0)
    for k in range(101):
        asm.feed(_cf(k * 0.1, k * 9.99 + 0.5, 1))
    asm.feed_completion(LapCompletion(game=Game.F1_25, t_recv_ns=2, lap_number=1, lap_time_ms=10_000, valid=True))
    assert len(laps) == 1 and laps[0].clean


def test_channels_cover_the_frame() -> None:  # the trace row layout is unchanged by the DRS fields
    assert "drs_allowed" not in CHANNELS and np.isfinite(_cf(1.0, 1.0, 1).lap_distance_m or 0.0)
