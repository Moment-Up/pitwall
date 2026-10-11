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


# ---------------------------------------------------------------- pit laps and race starts (real F1 25 geometry)
def _car(t: float, lap: int, d: float, lap_ms: int, kph: float, pit: int = 0) -> CarFrame:
    return CarFrame(
        game=Game.SYNTHETIC,
        t_recv_ns=int(t * 1e9),
        session_time_s=t,
        lap_number=lap,
        lap_distance_m=d,
        current_lap_time_ms=lap_ms,
        speed_kph=kph,
        pit_status=pit,
    )


def _drive_lap(
    asm: LapAssembler,
    lap: int,
    t0: float,
    *,
    length: float = 4910.0,
    start_m: float = 0.0,
    pit: tuple[float, float] | None = None,
    pit_to_end: float | None = None,
    stationary_s: float = 0.0,
) -> float:
    """Feed one lap at 10 m steps (0.1 s apart) and its completion, returning the next session time. ``pit`` = a
    pit-lane stretch (from, to) within the lap; ``pit_to_end`` = pit entry, the rest of the lap in the pit lane;
    ``stationary_s`` = seconds parked at ``start_m`` with the lap timer at 0 (a grid slot) before moving off."""
    t = t0
    for _ in range(int(stationary_s * 10)):
        asm.feed(_car(t, lap, start_m, 0, 0.0))
        t += 0.1
    d, lap_t = start_m, 0.0
    while d < length:
        in_pit = (pit is not None and pit[0] <= d < pit[1]) or (pit_to_end is not None and d >= pit_to_end)
        asm.feed(_car(t, lap, d, int(lap_t * 1000), 80.0 if in_pit else 250.0, 1 if in_pit else 0))
        d += 10.0
        t += 0.1
        lap_t += 0.1
    asm.feed_completion(
        LapCompletion(game=Game.SYNTHETIC, t_recv_ns=0, lap_number=lap, lap_time_ms=int(lap_t * 1000), valid=True)
    )
    return t


def test_imola_pit_stop_in_lap_and_out_lap_are_flagged_once_each() -> None:
    """Real F1 25 Imola race (20261011-195612): pit entry 4810 m on lap 14, the line crossed in the pit lane, pit exit
    449 m into lap 15 (the game's driverStatus: 2 in lap, then 3 out lap). Lap 15 used to be "pit_in, pit_out" (the
    pit lane past 100 m counted as an entry), so the radio called the out lap an in-lap."""
    laps: list[LapTrace] = []
    asm = LapAssembler(laps.append, track_length_m=4910.0)
    t = _drive_lap(asm, 13, 0.0)
    t = _drive_lap(asm, 14, t, pit_to_end=4810.0)
    t = _drive_lap(asm, 15, t, pit=(0.0, 449.0))
    _drive_lap(asm, 16, t)
    flags = {lap.lap_number: lap.flags for lap in laps}
    assert flags == {13: set(), 14: {LapFlag.PIT_IN}, 15: {LapFlag.PIT_OUT}, 16: set()}
    assert [lap.clean for lap in laps] == [True, False, False, True]


def test_drive_through_within_one_lap_is_in_and_out() -> None:
    laps: list[LapTrace] = []
    asm = LapAssembler(laps.append, track_length_m=4910.0)
    _drive_lap(asm, 7, 0.0, pit=(2000.0, 2600.0))
    assert laps[0].flags == {LapFlag.PIT_IN, LapFlag.PIT_OUT}


def test_unknown_pit_status_is_never_a_pit_lap() -> None:
    laps: list[LapTrace] = []
    asm = LapAssembler(laps.append, track_length_m=1000)
    for i in range(100):
        asm.feed(_frame(i * 0.5, 1, i * 10.0))  # pit_status None (GT7, Forza)
    asm.feed(_frame(50, 2, 0.0))
    assert not laps[0].flags & {LapFlag.PIT_IN, LapFlag.PIT_OUT}


@pytest.mark.parametrize(
    ("track", "grid_m"),
    [
        ("Melbourne", -164.2),  # behind the line: lap 1 used to count as clean and became the reference
        ("Austria (Reverse)", -162.5),
        ("Montreal", -49.9),
        ("Las Vegas", 2.6),
        ("Silverstone (Reverse)", 56.2),
        ("Austria", 132.2),  # past the 60 m edge: flagged before too
    ],
)
def test_race_lap_one_from_the_grid_is_a_standing_start_wherever_the_grid_is(track: str, grid_m: float) -> None:
    """Grid slots measured in the owner's real F1 25 races (first frame of lap 1: lap timer 0, speed 0, on track)."""
    laps: list[LapTrace] = []
    asm = LapAssembler(laps.append, track_length_m=4910.0)
    t = _drive_lap(asm, 1, 0.0, start_m=grid_m, stationary_s=3.0)
    _drive_lap(asm, 2, t)
    lap1, lap2 = laps
    assert lap1.flags == {LapFlag.STANDING_START}, track
    assert not lap1.clean and lap1.lap_time_ms is not None  # timed by the game, never a reference
    assert lap2.clean


def test_a_flying_first_lap_and_a_scenario_joined_at_speed_are_not_standing_starts() -> None:
    """Real F1 25: Suzuka one-shot qualifying lap 1 starts flying from -306 m (136 km/h, timer 0); the Austria
    scenario (20261010-221749) starts at lap 62, 27 m past the line at 281 km/h with the timer at 137 ms."""
    laps: list[LapTrace] = []
    asm = LapAssembler(laps.append, track_length_m=5809.0)
    asm.feed(_car(0.0, 1, -306.3, 0, 136.0))
    _drive_lap(asm, 1, 0.1, length=5809.0, start_m=-296.0)
    assert laps[0].flags == set() and laps[0].clean
    laps.clear()
    asm = LapAssembler(laps.append, track_length_m=4323.0)
    asm.feed(_car(0.0, 62, 27.2, 137, 281.0))
    _drive_lap(asm, 62, 0.1, length=4323.0, start_m=37.0)
    assert laps[0].lap_number == 62 and laps[0].flags == set() and laps[0].clean


def test_lap_one_starting_in_the_pit_lane_is_an_out_lap_not_a_standing_start() -> None:
    laps: list[LapTrace] = []
    asm = LapAssembler(laps.append, track_length_m=4910.0)
    asm.feed(_car(0.0, 1, 0.0, 0, 0.0, pit=1))  # a pit-lane start: parked at the pit exit, timer at 0
    _drive_lap(asm, 1, 0.1, pit=(0.0, 449.0))
    assert laps[0].flags == {LapFlag.PIT_OUT}


def test_final_lap_is_carried_from_the_completion() -> None:
    laps: list[LapTrace] = []
    asm = LapAssembler(laps.append, track_length_m=1000)
    for i in range(100):
        asm.feed(_frame(i * 0.5, 32, i * 10.0))
    asm.feed_completion(
        LapCompletion(game=Game.SYNTHETIC, t_recv_ns=0, lap_number=32, lap_time_ms=80_886, valid=True, final=True)
    )
    assert laps[0].meta["final"] is True and laps[0].clean
