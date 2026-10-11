"""F1 MotionEx (packet 13): decode, merge into CarFrame, wheel order, staleness, reset; lap channels and meta."""

from __future__ import annotations

import io
import time
from typing import Any

import numpy as np
import pytest

from pitwall.adapters.base import SupportLevel
from pitwall.adapters.f1 import packets as P
from pitwall.adapters.f1.adapter import MOTION_EX_MAX_FRAME_SKEW, F1Adapter
from pitwall.analysis.laps import CHANNELS, TECHNIQUE_CHANNELS, LapAssembler, LapTrace
from pitwall.model.telemetry import CarFrame, Game, LapCompletion
from pitwall.sim.f1_stream import F1Scenario

SC = F1Scenario()


def _hdr(pid: P.PacketId, frame: int, uid: int = 9) -> bytes:
    return P.HEADER.pack(
        {"packetFormat": 2025, "packetId": int(pid), "sessionUID": uid, "playerCarIndex": 0, "frameIdentifier": frame}
    )


def _motion_ex(frame: int, uid: int = 9, **values: Any) -> bytes:
    base: dict[str, Any] = {
        "wheelSlipRatio": [0.11, 0.12, 0.13, 0.14],  # RL RR FL FR
        "wheelSlipAngle": [0.021, 0.022, 0.023, 0.024],
        "angularVelocityY": 0.5,
        "chassisYaw": 0.03,
    }
    return _hdr(P.PacketId.MOTION_EX, frame, uid) + P.MOTION_EX.pack({**base, **values})


def _telemetry(frame: int, uid: int = 9) -> bytes:
    L = SC.layout
    cars = [L.car_telemetry.pack({"speed": 100}) for _ in range(L.max_cars)]
    return _hdr(P.PacketId.CAR_TELEMETRY, frame, uid) + b"".join(cars) + P.CAR_TELEMETRY_TAIL.pack({})


def _frame(ad: F1Adapter, frame: int, uid: int = 9) -> CarFrame:
    (f,) = ad.decode(_telemetry(frame, uid), 1)
    assert isinstance(f, CarFrame)
    return f


def test_motion_ex_emits_nothing_and_merges_into_the_next_frame() -> None:
    ad = F1Adapter()
    assert ad.decode(_motion_ex(10), 1) == []
    assert ad.stats.by_type.get("MOTION_EX") == 1 and ad.stats.ignored == 0
    f = _frame(ad, 10)
    assert f.yaw_rate_rps == pytest.approx(-0.5)  # game: + for left turns; pitwall: + = right, like steering
    assert f.body_slip_rad == pytest.approx(0.03)
    # RL, RR, FL, FR on the wire -> FL, FR, RL, RR
    assert f.wheel_slip_ratio is not None and f.wheel_slip_angle_rad is not None
    assert f.wheel_slip_ratio.as_tuple() == pytest.approx((0.13, 0.14, 0.11, 0.12))
    assert f.wheel_slip_angle_rad.as_tuple() == pytest.approx((0.023, 0.024, 0.021, 0.022))


def test_stale_motion_ex_leaves_the_fields_unknown() -> None:
    ad = F1Adapter()
    ad.decode(_motion_ex(10), 1)
    ok = _frame(ad, 10 + MOTION_EX_MAX_FRAME_SKEW)
    assert ok.yaw_rate_rps is not None
    stale = _frame(ad, 11 + MOTION_EX_MAX_FRAME_SKEW)
    assert stale.yaw_rate_rps is None and stale.wheel_slip_ratio is None and stale.body_slip_rad is None
    assert stale.wheel_slip_angle_rad is None


def test_frames_without_motion_ex_stay_unknown() -> None:
    f = _frame(F1Adapter(), 1)
    assert f.yaw_rate_rps is None and f.wheel_slip_ratio is None and f.wheel_slip_angle_rad is None


def test_reset_and_a_new_session_clear_the_motion_ex_cache() -> None:
    ad = F1Adapter()
    ad.decode(_motion_ex(10), 1)
    ad.reset()
    assert _frame(ad, 10).yaw_rate_rps is None
    ad.decode(_motion_ex(10, uid=9), 1)
    assert _frame(ad, 10, uid=9).yaw_rate_rps is not None
    assert _frame(ad, 10, uid=77).yaw_rate_rps is None  # a new session UID resets the adapter


def test_adapter_info_declares_the_new_fields_at_spec_level() -> None:
    fields = F1Adapter().info.fields
    for key in ("yaw_rate_rps", "body_slip_rad", "wheel_slip_ratio", "wheel_slip_angle_rad"):
        assert fields[key].level == SupportLevel.SPEC_IMPLEMENTED
        assert "MotionEx" in fields[key].source


def test_motion_ex_decode_is_cheap() -> None:
    ad = F1Adapter()
    pkt = _motion_ex(1)
    t0 = time.perf_counter()
    for _ in range(10_000):
        ad.decode(pkt, 1)
    assert time.perf_counter() - t0 < 0.5  # lenient: about 0.02 s on the M4 Max


# ---------------------------------------------------------------------------------------------- lap channels
def _lap_frames(n: int = 200, slip: bool = True, abs_on: bool | None = True) -> list[CarFrame]:
    from pitwall.model.telemetry import Wheels

    frames = []
    for i in range(n):
        f = CarFrame(
            game=Game.F1_25,
            t_recv_ns=i,
            session_time_s=i / 60,
            current_lap_time_ms=int(i / 60 * 1000),
            lap_number=1,
            lap_distance_m=float(i * 5),
            speed_kph=200.0,
            abs_active=abs_on,
            traction_control=2,
        )
        if slip:
            f.yaw_rate_rps = 0.1
            f.body_slip_rad = -0.02
            f.wheel_slip_ratio = Wheels(fl=-0.1, fr=-0.2, rl=0.3, rr=0.4)
            f.wheel_slip_angle_rad = Wheels(fl=0.04, fr=-0.02, rl=0.01, rr=-0.03)
        frames.append(f)
    return frames


def _assemble(frames: list[CarFrame]) -> LapTrace:
    laps: list[LapTrace] = []
    asm = LapAssembler(laps.append)
    for f in frames:
        asm.feed(f)
    asm.feed_completion(LapCompletion(game=Game.F1_25, t_recv_ns=0, lap_number=1, lap_time_ms=3300))
    assert len(laps) == 1
    return laps[0]


def test_assembler_stores_the_technique_channels_and_assist_meta() -> None:
    assert set(TECHNIQUE_CHANNELS) <= set(CHANNELS) and len(CHANNELS) == 19 + 8
    lap = _assemble(_lap_frames())
    ch = lap.channels
    assert ch["yaw_rate_rps"][0] == pytest.approx(0.1) and ch["body_slip_rad"][0] == pytest.approx(-0.02)
    assert ch["slip_angle_front_abs_rad"][0] == pytest.approx(0.03)  # mean of |0.04| and |-0.02|
    assert ch["slip_angle_rear_abs_rad"][0] == pytest.approx(0.02)
    assert [ch[f"wheel_slip_{w}"][0] for w in ("fl", "fr", "rl", "rr")] == pytest.approx([-0.1, -0.2, 0.3, 0.4])
    assert lap.meta["abs_active"] is True and lap.meta["traction_control"] == 2
    roundtrip = LapTrace.channels_from_npz(lap.to_npz())
    assert set(TECHNIQUE_CHANNELS) <= set(roundtrip)


def test_games_without_slip_store_nan_and_changed_assists_are_unknown() -> None:
    frames = _lap_frames(slip=False)
    for f in frames[150:]:
        f.abs_active = False  # ABS switched off for the last quarter of the lap: not one value for the lap
    lap = _assemble(frames)
    assert all(np.isnan(lap.channels[k]).all() for k in TECHNIQUE_CHANNELS)
    assert lap.meta["abs_active"] is None and lap.meta["traction_control"] == 2


def test_a_zeroed_car_status_on_the_grid_does_not_hide_the_lap_assists() -> None:
    """Real F1 25 (Miami and Silverstone Reverse races): the first CarStatus of the race lap says ABS off and TC 0
    while the car is still on the grid; from the first frame on the move it is ABS on, TC full all lap."""
    frames = _lap_frames(slip=False)
    for f in frames[:3]:
        f.speed_kph, f.abs_active, f.traction_control = 0.0, False, 0
    lap = _assemble(frames)
    assert lap.meta["abs_active"] is True and lap.meta["traction_control"] == 2
    frames = _lap_frames(slip=False)
    frames[0].speed_kph = 0.0
    for f in frames[100:]:
        f.traction_control = 1  # changed on the move, half the lap each: not one value for the lap
    lap = _assemble(frames)
    assert lap.meta["abs_active"] is True and lap.meta["traction_control"] is None


def test_a_session_joined_at_speed_with_tc_zero_for_a_moment_keeps_the_lap_assist() -> None:
    """Real F1 25 (captures 20261010-221749 and 20261011-183245): a lap first seen at 281 km/h gets CarStatus TC 0
    for 2.4 s, then TC 2 for the rest of the lap. One value covering 90 % of the moving frames is the lap's."""
    frames = _lap_frames(slip=False, n=600)
    for f in frames[:15]:  # 0.25 s of a 10 s lap at 60 Hz, on the move
        f.traction_control, f.abs_active = 0, False
    lap = _assemble(frames)
    assert lap.meta["traction_control"] == 2 and lap.meta["abs_active"] is True
    frames = _lap_frames(slip=False, n=600)
    for f in frames[:90]:  # 15 % of the lap: too much to call it one value
        f.traction_control = 0
    assert _assemble(frames).meta["traction_control"] is None
    frames = _lap_frames(slip=False, n=50, abs_on=None)
    for f in frames:
        f.traction_control = None
    lap = _assemble(frames)  # never sent: unknown
    assert lap.meta["abs_active"] is None and lap.meta["traction_control"] is None


def test_old_laps_without_the_channels_still_load() -> None:
    lap = _assemble(_lap_frames())
    buf = io.BytesIO()
    np.savez_compressed(buf, **{k: v for k, v in lap.channels.items() if k not in TECHNIQUE_CHANNELS})
    old = LapTrace.channels_from_npz(buf.getvalue())
    assert not set(TECHNIQUE_CHANNELS) & set(old)
    from pitwall.technique.samples import Native, native

    nat = native(LapTrace(lap_number=1, channels=old, lap_time_ms=3300))
    assert isinstance(nat, Native) and nat.get("wheel_slip_fl") is None and nat.get("yaw_rate_rps") is None
