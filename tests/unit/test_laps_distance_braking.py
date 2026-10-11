"""Lap boundaries, flashbacks, partial laps, distance alignment and braking-point detection."""

from __future__ import annotations

import numpy as np
import pytest

from pitwall.analysis.braking import BRAKE_ON, detect_braking
from pitwall.analysis.distance import crossing, monotonic_mask, to_distance_domain
from pitwall.analysis.laps import CHANNELS, LapAssembler, LapFlag, LapTrace
from pitwall.model.telemetry import CarFrame, FrameQuality, Game, LapCompletion
from tests.conftest import DecodedSession


def _frame(t: float, lap: int, d: float, **kw: object) -> CarFrame:
    return CarFrame(
        game=Game.SYNTHETIC,
        t_recv_ns=int(t * 1e9),
        session_time_s=t,
        lap_number=lap,
        lap_distance_m=d,
        current_lap_time_ms=int(t * 1000),
        speed_kph=200.0,
        **kw,  # type: ignore[arg-type]
    )


def _lap_trace(d: np.ndarray, t: np.ndarray, **channels: np.ndarray) -> LapTrace:
    n = len(d)
    ch = {k: np.full(n, np.nan) for k in CHANNELS}
    ch["distance_m"] = d
    ch["session_time_s"] = t
    ch["lap_time_ms"] = t * 1000
    for k, v in channels.items():
        ch[k] = v
    return LapTrace(lap_number=1, channels=ch, lap_time_ms=int(t[-1] * 1000), valid=True)


# ---------------------------------------------------------------- lap assembly
def test_lap_boundary_uses_official_completion() -> None:
    laps: list[LapTrace] = []
    asm = LapAssembler(laps.append, track_length_m=1000)
    for i in range(100):
        asm.feed(_frame(i * 0.5, 1, i * 10.0))
    asm.feed_completion(
        LapCompletion(
            game=Game.SYNTHETIC, t_recv_ns=0, lap_number=1, lap_time_ms=49_900, sector_times_ms=[1, 2, 3], valid=True
        )
    )
    assert len(laps) == 1
    assert laps[0].lap_time_ms == 49_900 and laps[0].valid is True and laps[0].clean
    asm.feed(_frame(50.0, 2, 0.5))
    assert len(laps) == 1  # lap 2 in progress


def test_lap_without_completion_is_finalised_on_lap_change() -> None:
    laps: list[LapTrace] = []
    asm = LapAssembler(laps.append, track_length_m=1000)
    for i in range(100):
        asm.feed(_frame(i * 0.5, 1, i * 10.0))
    asm.feed(_frame(50.0, 2, 1.0))
    assert len(laps) == 1 and laps[0].lap_time_ms is None and not laps[0].clean


def test_flashback_trims_rewound_frames_and_flags_lap() -> None:
    laps: list[LapTrace] = []
    asm = LapAssembler(laps.append, track_length_m=1000)
    for i in range(60):
        asm.feed(_frame(i * 0.5, 1, i * 10.0))
    for i in range(40, 100):  # rewound to t=20 s and drove on
        asm.feed(_frame(i * 0.5, 1, i * 10.0))
    asm.feed_completion(LapCompletion(game=Game.SYNTHETIC, t_recv_ns=0, lap_number=1, lap_time_ms=50_000, valid=True))
    lap = laps[0]
    assert LapFlag.FLASHBACK in lap.flags and not lap.clean
    t = lap.channels["session_time_s"]
    assert np.all(np.diff(t) > 0), "rewound section must not be duplicated"
    assert lap.n == 100


def test_joined_mid_lap_is_incomplete() -> None:
    laps: list[LapTrace] = []
    asm = LapAssembler(laps.append, track_length_m=1000)
    for i in range(50):
        asm.feed(_frame(i * 0.5, 3, 500 + i * 10.0))
    asm.feed_completion(LapCompletion(game=Game.SYNTHETIC, t_recv_ns=0, lap_number=3, lap_time_ms=40_000, valid=True))
    assert LapFlag.INCOMPLETE in laps[0].flags


def test_packet_loss_gap_marks_incomplete() -> None:
    laps: list[LapTrace] = []
    asm = LapAssembler(laps.append, track_length_m=1000)
    for i in list(range(30)) + list(range(45, 100)):  # 150 m hole
        asm.feed(_frame(i * 0.5, 1, i * 10.0))
    asm.feed(_frame(50.0, 2, 0.0))
    assert LapFlag.INCOMPLETE in laps[0].flags


def test_paused_and_spectating_frames_are_ignored() -> None:
    laps: list[LapTrace] = []
    asm = LapAssembler(laps.append, track_length_m=1000)
    asm.feed(_frame(0.0, 1, 0.0, quality=FrameQuality.PAUSED))
    asm.feed(_frame(0.1, 1, 1.0, quality=FrameQuality.REPLAY_OR_SPECTATING))
    asm.flush()
    assert laps == []


def test_pit_out_lap_flagged() -> None:
    laps: list[LapTrace] = []
    asm = LapAssembler(laps.append, track_length_m=1000)
    for i in range(100):
        asm.feed(_frame(i * 0.5, 1, i * 10.0, pit_status=1 if i < 5 else 0))
    asm.feed(_frame(50, 2, 0.0))
    assert LapFlag.PIT_OUT in laps[0].flags and not laps[0].clean


def test_fuel_start_uses_first_available_value() -> None:
    laps: list[LapTrace] = []
    asm = LapAssembler(laps.append, track_length_m=1000)
    asm.feed(_frame(0.0, 1, 0.0))  # status packet not received yet
    for i in range(1, 100):
        asm.feed(_frame(i * 0.5, 1, i * 10.0, fuel_kg=40.0 - i * 0.01))
    asm.feed(_frame(50.0, 2, 0.0))
    assert laps[0].meta["fuel_start_kg"] == pytest.approx(39.99)


def test_npz_roundtrip() -> None:
    d = np.linspace(0, 100, 50)
    lap = _lap_trace(d, d / 50, speed_kph=np.full(50, 123.0))
    back = LapTrace.channels_from_npz(lap.to_npz())
    assert set(back) == set(CHANNELS)
    assert np.allclose(back["speed_kph"], 123.0)


# ---------------------------------------------------------------- distance alignment
def test_monotonic_mask_drops_backward_and_nan() -> None:
    d = np.array([0, 1, 2, 1.5, 3, np.nan, 4, 4])
    assert monotonic_mask(d).tolist() == [True, True, True, False, True, False, True, False]


def test_distance_domain_alignment_and_edges() -> None:
    d = np.arange(0.8, 1000, 1.7)  # first sample 0.8 m past the line, uneven spacing
    v_mps = 50.0
    t = d / v_mps
    lap = _lap_trace(d, t, speed_kph=np.full(len(d), v_mps * 3.6))
    dt = to_distance_domain(lap, 1000.0)
    assert dt.d[0] == 0 and dt.d[1] == 1.0
    assert dt.at("t_s", 500.0) == pytest.approx(10.0, abs=1e-6)
    assert dt.t_s[0] == pytest.approx(0.0, abs=1e-6), "edge before first sample extrapolated with speed"
    assert np.isfinite(dt.t_s).all()


def test_distance_domain_large_gap_stays_nan() -> None:
    d = np.arange(100.0, 1000.0, 2.0)  # first 100 m missing: not extrapolated
    lap = _lap_trace(d, d / 50, speed_kph=np.full(len(d), 180.0))
    dt = to_distance_domain(lap, 1000.0)
    assert np.isnan(dt.t_s[:99]).all() and np.isfinite(dt.t_s[100])


def test_crossing_interpolates() -> None:
    d = np.array([0.0, 10.0, 20.0])
    y = np.array([0.0, 0.0, 1.0])
    assert crossing(d, y, 0.25, 0) == pytest.approx(12.5)


# ---------------------------------------------------------------- braking
def _brake_lap(onset_m: float, release_m: float, stab: bool = False) -> LapTrace:
    d = np.arange(0.0, 1000.0, 1.25)
    v = np.full(len(d), 300.0)
    brake = np.zeros(len(d))
    on = (d >= onset_m) & (d < release_m)
    brake[on] = 1.0
    v[on] = np.linspace(300, 90, on.sum())
    after = d >= release_m
    v[after] = np.linspace(90, 250, after.sum())
    if stab:
        brake[(d >= onset_m - 40) & (d < onset_m - 38)] = 0.5  # 2 m tap, too short to count
    throttle = np.where(d >= release_m + 20, 1.0, 0.0)
    t = np.concatenate([[0], np.cumsum(np.diff(d) / (v[:-1] / 3.6))])
    return _lap_trace(d, t, speed_kph=v, brake=brake, throttle=throttle, steering=np.zeros(len(d)))


def test_braking_onset_and_release_are_sub_sample_precise() -> None:
    (e,) = detect_braking(_brake_lap(500.0, 620.0))
    assert e.start_m == pytest.approx(500.0 - 1.25 * (1 - BRAKE_ON), abs=1.3)
    assert e.end_m == pytest.approx(620.0, abs=1.3)
    assert e.peak_brake == 1.0 and e.min_speed_kph == pytest.approx(90, abs=1)
    assert e.throttle_full_m == pytest.approx(640.0, abs=1.3)


def test_short_brake_tap_is_ignored() -> None:
    events = detect_braking(_brake_lap(500.0, 620.0, stab=True))
    assert len(events) == 1 and events[0].start_m > 490


def test_braking_points_recovered_from_decoded_stream(demo_session: DecodedSession) -> None:
    """Braking onsets found in the decoded packet stream match the generator's ground-truth inputs."""
    truth = demo_session.truth.profiles[1]
    lap1 = next(lap for lap in demo_session.laps if lap.lap_number == 1)
    found = [e.start_m for e in detect_braking(lap1)]
    on = truth.brake >= BRAKE_ON
    true_onsets = truth.s[1:][on[1:] & ~on[:-1]]
    assert len(found) == len(true_onsets)
    for a, b in zip(sorted(found), sorted(true_onsets), strict=True):
        assert a == pytest.approx(b, abs=2.0)  # 60 Hz sampling at ~300 km/h is ~1.4 m per frame


def test_distance_jump_without_time_gap_is_not_incomplete() -> None:
    """Real F1 25 (PS5): lap distance jumped ~150 m in one frame with continuous session time."""
    laps: list[LapTrace] = []
    asm = LapAssembler(laps.append, track_length_m=1000)
    t = 0.0
    for i in range(100):
        d = i * 10.0 + (150.0 if i >= 40 else 0.0)  # jump at frame 40
        if d >= 1000:
            break
        asm.feed(_frame(t, 1, d))
        t += 0.1
    asm.feed_completion(LapCompletion(game=Game.SYNTHETIC, t_recv_ns=0, lap_number=1, lap_time_ms=9000, valid=True))
    assert LapFlag.DISTANCE_JUMP in laps[0].flags
    assert LapFlag.INCOMPLETE not in laps[0].flags and not laps[0].clean and laps[0].lap_time_ms == 9000


def test_standing_start_lap_flagged_not_incomplete() -> None:
    laps: list[LapTrace] = []
    asm = LapAssembler(laps.append, track_length_m=1000)
    for i in range(90):
        asm.feed(_frame(i * 0.5, 1, 132.0 + i * 10.0))  # lap timer starts at 0 on the grid
    asm.feed_completion(LapCompletion(game=Game.SYNTHETIC, t_recv_ns=0, lap_number=1, lap_time_ms=45000, valid=True))
    assert laps[0].flags == {LapFlag.STANDING_START}
