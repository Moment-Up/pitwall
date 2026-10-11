"""RECORDED tier: F1 25 MotionEx units and signs, and the technique analysis, on real PS5 excerpts (format 2025).

Fixtures (committed, scrubbed): ``f1_25_2025_ps5_monza_race-excerpt.pwcap`` (race lap 3, 560-2250 m, Rettifilo and
Roggia chicanes) and ``f1_25_2025_ps5_austria_race-excerpt.pwcap`` (start, lap changes, finish). Assists in both:
ABS on; traction control full (Monza) and medium (Austria).

What these establish (see docs/research/f1-motion-ex-units.md):

* ``angularVelocityY`` is the yaw rate in rad/s and is negative turning right, so ``yaw_rate_rps`` (its negative)
  has the sign of the steering;
* ``wheelSlipRatio`` is negative under braking and positive with wheelspin; ``wheelSlipAngle`` is radians;
* ``chassisYaw`` is atan2(localVelocityX, localVelocityZ), the body slip angle in radians. Its sign against the yaw
  rate tells a tail-out slide (same sign: the Austria slides at 154-205 km/h with the rear slip angle above the
  front) from the kinematic body slip of a slow, tight turn (opposite sign: Monza's second Rettifilo apex at 28 km/h
  on near-full lock, 8.1 deg with a rear slip angle of 0.5 deg), which is not a slide.

Not established here: lock-ups (ABS was on in every real capture: synthetic tier only), and anything live.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from pitwall.adapters.f1 import packets as P
from pitwall.analysis.braking import detect_braking
from pitwall.analysis.laps import LapAssembler, LapTrace
from pitwall.ingest.capture import CaptureReader
from pitwall.model.telemetry import CarFrame
from pitwall.technique.balance import lap_balance
from pitwall.technique.inputs import corner_inputs
from pitwall.technique.samples import Native, native
from tests.conftest import decode_session

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "recorded"
MONZA = FIXTURES / "f1_25_2025_ps5_monza_race-excerpt.pwcap"
AUSTRIA = FIXTURES / "f1_25_2025_ps5_austria_race-excerpt.pwcap"

pytestmark = [
    pytest.mark.recorded,
    pytest.mark.skipif(not (MONZA.exists() and AUSTRIA.exists()), reason="real PS5 excerpts not present"),
]


def _frames(path: Path) -> list[CarFrame]:
    reader = CaptureReader(path)
    assert not reader.meta.synthetic
    _, frames, _, _ = decode_session(list(reader))
    return frames


def _arr(frames: list[CarFrame], get: object) -> np.ndarray:
    f = get  # callable
    return np.array([np.nan if (v := f(x)) is None else v for x in frames], dtype=np.float64)  # type: ignore[operator]


@pytest.fixture(scope="module")
def monza() -> list[CarFrame]:
    return _frames(MONZA)


@pytest.fixture(scope="module")
def austria() -> list[CarFrame]:
    return _frames(AUSTRIA)


def _lap(frames: list[CarFrame], number: int) -> LapTrace:
    laps: list[LapTrace] = []
    asm = LapAssembler(laps.append)
    for f in frames:
        asm.feed(f)
    asm.flush()
    return next(lap for lap in laps if lap.lap_number == number)


def _slowest(nat: Native, around: float, span: float = 150.0) -> float:
    w = np.flatnonzero(np.abs(nat.d - around) <= span)
    return float(nat.d[w[int(np.nanargmin(nat.speed[w]))]])


def _yaw_steer(frames: list[CarFrame]) -> tuple[np.ndarray, np.ndarray]:
    yaw = _arr(frames, lambda f: f.yaw_rate_rps)
    steer = _arr(frames, lambda f: f.steering)
    v = _arr(frames, lambda f: f.speed_kph) / 3.6
    m = np.isfinite(yaw) & (v >= 20) & (np.abs(steer) >= 0.05)
    return yaw[m], steer[m]


def test_monza_motion_ex_matches_every_frame_and_turns_with_the_steering(monza: list[CarFrame]) -> None:
    yaw = _arr(monza, lambda f: f.yaw_rate_rps)
    assert np.isfinite(yaw).mean() >= 0.99  # MotionEx arrives with every Motion packet, same frame
    y, s = _yaw_steer(monza)
    assert np.corrcoef(s, y)[0, 1] >= 0.9
    assert np.mean(np.sign(s) == np.sign(y)) >= 0.98  # + = turning right, like steering


def test_monza_slip_ratio_signs_and_slip_angle_units(monza: list[CarFrame]) -> None:
    brake = _arr(monza, lambda f: f.brake)
    thr = _arr(monza, lambda f: f.throttle)
    kph = _arr(monza, lambda f: f.speed_kph)
    fl = _arr(monza, lambda f: f.wheel_slip_ratio.fl if f.wheel_slip_ratio else None)
    rl = _arr(monza, lambda f: f.wheel_slip_ratio.rl if f.wheel_slip_ratio else None)
    assert np.nanmedian(fl[brake >= 0.8]) < 0  # braking: the wheel turns slower than the car
    assert np.nanmedian(rl[(thr >= 0.95) & (kph < 150)]) > 0  # driven rear wheels spin up
    angles = np.array([max(abs(a) for a in f.wheel_slip_angle_rad.as_tuple()) for f in monza if f.wheel_slip_angle_rad])
    assert np.max(angles) < 0.35  # radians (degrees would read up to ~9)


def test_monza_body_slip_is_the_velocity_angle() -> None:
    errors = []
    for pkt in CaptureReader(MONZA):
        d = pkt.data
        if len(d) == P.LAYOUT_2025.sizes[P.PacketId.MOTION_EX] and d[6] == P.PacketId.MOTION_EX:
            ex = P.MOTION_EX.unpack_from(d, P.HEADER.size)
            if math.hypot(ex["localVelocityX"], ex["localVelocityZ"]) > 5:
                beta = math.atan2(ex["localVelocityX"], ex["localVelocityZ"])
                errors.append(abs(ex["chassisYaw"] - beta))
    assert len(errors) > 1500
    assert np.percentile(errors, 99) < 1e-3 and max(errors) < 2e-3  # radians: float32 rounding (0.1 deg at most)


def test_monza_rettifilo_exit_wheelspin_and_slow_turn_body_slip(monza: list[CarFrame]) -> None:
    lap = _lap(monza, 3)
    assert lap.meta["abs_active"] is True and lap.meta["traction_control"] == 2
    nat = native(lap)
    apex = _slowest(nat, 983.0)
    assert 975 <= apex <= 995 and float(np.nanmin(nat.speed)) < 35  # the second Rettifilo apex, nearly stopped
    bal = lap_balance(nat, apex, apex - 300, apex + 300)
    assert bal is not None and bal["mid"] is not None
    # 8 degrees of body slip on near-full lock at 28 km/h, but the rear slip angle is tiny and the body slip points
    # the other way to a tail-out slide: the normal geometry of a slow, tight turn, not oversteer
    assert bal["mid"].body_slip_max_deg is not None and bal["mid"].body_slip_max_deg >= 7.5
    assert not bal["mid"].slide and bal["mid"].cls != "oversteer"
    ev = next(e for e in detect_braking(lap) if apex - 450 <= e.start_m <= apex)
    ci = corner_inputs(nat, ev, apex, None, None, None, abs_on=True, tc_level=2)
    assert ci.lockup.status == "abs_on"  # ABS on: lock-ups are not analysed
    spin = ci.wheelspin
    assert spin.status == "measured" and (spin.events or 0) >= 1 and spin.tc_level == 2
    assert spin.at_m and 980 <= spin.at_m[0] <= 1015 and set(spin.wheels) <= {"rl", "rr"}


def test_austria_turns_with_the_steering_and_reports_abs_and_medium_traction_control(
    austria: list[CarFrame],
) -> None:
    y, s = _yaw_steer(austria)
    assert np.corrcoef(s, y)[0, 1] >= 0.6
    decoded, _, _, _ = decode_session(list(CaptureReader(AUSTRIA)))
    lap3 = next(lap for lap in decoded if lap.lap_number == 3)
    assert lap3.meta["abs_active"] is True and lap3.meta["traction_control"] == 1
    nat = native(lap3)
    ev = next(iter(detect_braking(lap3)), None)
    ci = corner_inputs(nat, ev, float(nat.d[len(nat.d) // 2]), None, None, None, abs_on=True, tc_level=1)
    assert ci.lockup.status in ("abs_on", "not_applicable")


def test_austria_tail_out_slides_are_oversteer(austria: list[CarFrame]) -> None:
    decoded, _, _, _ = decode_session(list(CaptureReader(AUSTRIA)))
    lap3 = next(lap for lap in decoded if lap.lap_number == 3)
    nat = native(lap3)
    apex = _slowest(nat, 4045.0)
    bal = lap_balance(nat, apex, apex - 300, apex + 300)
    assert bal is not None and bal["exit"] is not None
    exit_ = bal["exit"]
    # 6 degrees tail out at 154-160 km/h with the rear slip angle above the front (counter-steering)
    assert exit_.slide and exit_.cls == "oversteer" and exit_.slide_deg is not None and exit_.slide_deg >= 5.0
