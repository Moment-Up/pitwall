"""Brake and throttle technique on hand-made traces: release shapes, trail braking, coasting, throttle ramp and
lifts, lock-ups and wheelspin, pedal tolerances, braking-assist muting and missing data."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest

from pitwall.analysis.braking import BrakingEvent, detect_braking
from pitwall.analysis.laps import LapTrace
from pitwall.technique.inputs import CornerInputs, Tolerances, compare_inputs, corner_inputs, habits, top_notes
from pitwall.technique.rig import pedal_info
from pitwall.technique.samples import native

HZ = 60
V = 30.0  # m/s, constant: distance = 30 * t
T_END = 12.0
APEX_T = 5.0  # slowest point (s): 150 m


def _lap(
    brake: Callable[[np.ndarray], np.ndarray],
    throttle: Callable[[np.ndarray], np.ndarray] | None = None,
    steer: Callable[[np.ndarray], np.ndarray] | None = None,
    slip: dict[str, Callable[[np.ndarray], np.ndarray]] | None = None,
    with_slip: bool = True,
) -> LapTrace:
    t = np.arange(0, T_END, 1 / HZ)
    ch = {
        "session_time_s": t,
        "lap_time_ms": t * 1000,
        "distance_m": V * t,
        "speed_kph": np.full(len(t), 150.0),
        "brake": brake(t),
        "throttle": throttle(t) if throttle else np.where(t >= 6.0, 1.0, 0.0),
        "steering": steer(t) if steer else np.where((t > 3.5) & (t < 7.0), 0.4, 0.0),
    }
    if with_slip:
        for w in ("fl", "fr", "rl", "rr"):
            f = (slip or {}).get(w)
            ch[f"wheel_slip_{w}"] = f(t) if f else np.zeros(len(t))
    return LapTrace(lap_number=1, channels=ch, lap_time_ms=12000)


def _inputs(lap: LapTrace, abs_on: bool | None = False, tc: int | None = None) -> CornerInputs:
    ev: BrakingEvent | None = next(iter(detect_braking(lap)), None)
    return corner_inputs(native(lap), ev, V * APEX_T, V * 3.8, V * 7.0, None, abs_on=abs_on, tc_level=tc)


def _pulse(t0: float, t1: float, level: float = 1.0) -> Callable[[np.ndarray], np.ndarray]:
    return lambda t: np.where((t >= t0) & (t < t1), level, 0.0)


def step(t: np.ndarray) -> np.ndarray:  # full brake 2.0-4.0 s, off in one go
    return np.where((t >= 2.0) & (t < 4.0), 1.0, 0.0)


def steady(t: np.ndarray) -> np.ndarray:  # full brake 2.0-3.5 s, then a straight ramp to zero over 1 s
    return np.clip(np.where(t < 2.0, 0.0, np.where(t < 3.5, 1.0, 1.0 - (t - 3.5))), 0, 1)


def drop_then_trail(t: np.ndarray) -> np.ndarray:  # drop to 25 % at once, then trail it away over 1 s
    out = np.where((t >= 2.0) & (t < 3.5), 1.0, 0.0)
    trail = (t >= 3.5) & (t < 4.5)
    return np.where(trail, 0.25 * (1 - (t - 3.5)), out)


def late_drop(t: np.ndarray) -> np.ndarray:  # hold 85 % for 0.8 s after the peak, then let go
    out = np.where((t >= 2.0) & (t < 3.0), 1.0, 0.0)
    return np.where((t >= 3.0) & (t < 3.8), 0.85, out)


@pytest.mark.parametrize(
    ("brake", "shape"),
    [(step, "step"), (steady, "steady"), (drop_then_trail, "drop_then_trail"), (late_drop, "late_drop")],
)
def test_release_shapes(brake: Callable[[np.ndarray], np.ndarray], shape: str) -> None:
    ci = _inputs(_lap(brake))
    assert ci.braked and ci.release_shape == shape
    assert ci.brake_peak == pytest.approx(1.0)


def test_step_release_is_short_and_steady_release_takes_the_ramp() -> None:
    assert (_inputs(_lap(step)).release_s or 0) < 0.05
    assert _inputs(_lap(steady)).release_s == pytest.approx(0.8, abs=0.05)  # 90 % -> 10 % of peak on a 1 s ramp


def test_time_to_peak_hold_trail_overlap_and_brake_at_turn_in() -> None:
    def ramp_on(t: np.ndarray) -> np.ndarray:
        return np.clip(np.where(t < 2.0, 0.0, np.where(t < 4.5, (t - 2.0) / 0.5, 0.0)), 0, 1)

    ci = _inputs(_lap(ramp_on))
    assert ci.time_to_peak_s == pytest.approx(0.37, abs=0.05)  # 10 % -> 90 % of a 0.5 s ramp
    assert ci.peak_hold_s == pytest.approx(2.05, abs=0.05)
    assert ci.trail_overlap_s == pytest.approx(1.0, abs=0.05)  # steering from 3.5 s, brake off at 4.5 s
    assert ci.brake_at_turn_in == pytest.approx(1.0)  # turn-in at 3.8 s: still on the brake
    assert ci.brake_at_apex == pytest.approx(0.0)


def test_coasting_throttle_ramp_and_lifts() -> None:
    def thr(t: np.ndarray) -> np.ndarray:
        ramp = np.clip((t - 6.0) / 1.0, 0, 1)  # 0 -> 1 over 6.0-7.0 s
        dip = (t >= 6.5) & (t < 6.7)
        return np.where(dip, ramp - 0.3, ramp)

    ci = _inputs(_lap(step, throttle=thr))
    assert ci.coast_s == pytest.approx(2.05, abs=0.05)  # brake off at 4.0 s, throttle above 5 % from 6.05 s
    assert ci.pickup_vs_apex_m == pytest.approx(V * 1.2, abs=1.0)  # 20 % at 6.2 s; slowest point at 5.0 s
    assert ci.throttle_ramp_s == pytest.approx(0.75, abs=0.03)  # 20 % at 6.2 s, 95 % at 6.95 s
    assert ci.throttle_lifts == 1


def test_part_throttle_until_the_next_corner_has_no_full_throttle() -> None:
    ci = _inputs(_lap(step, throttle=lambda t: np.where(t >= 6.0, 0.6, 0.0)))
    assert ci.pickup_m is not None and ci.full_throttle_m is None and ci.throttle_ramp_s is None


def test_lock_ups_are_measured_with_abs_off_and_not_analysed_with_abs_on() -> None:
    locked = _lap(step, slip={"fl": _pulse(2.5, 2.7, -0.4)})
    ci = _inputs(locked, abs_on=False)
    assert ci.lockup.status == "measured" and ci.lockup.events == 1 and ci.lockup.wheels == ["fl"]
    assert ci.lockup.total_s == pytest.approx(0.2, abs=0.03) and ci.lockup.peak_slip == pytest.approx(-0.4)
    assert _inputs(locked, abs_on=True).lockup.status == "abs_on"
    short = _inputs(_lap(step, slip={"fl": _pulse(2.5, 2.55, -0.4)}))
    assert short.lockup.events == 0  # shorter than 0.1 s: a twitch, not a lock-up


def test_wheelspin_on_the_exit_carries_the_traction_control_level() -> None:
    spin = _lap(step, slip={"rl": _pulse(6.5, 6.9, 0.3), "rr": _pulse(6.5, 6.9, 0.3)})
    ci = _inputs(spin, tc=2)
    assert ci.wheelspin.status == "measured" and ci.wheelspin.events == 1 and ci.wheelspin.tc_level == 2
    assert ci.wheelspin.total_s == pytest.approx(0.4, abs=0.03) and ci.wheelspin.wheels == ["rl", "rr"]


def test_missing_slip_channels_are_no_data() -> None:
    ci = _inputs(_lap(step, with_slip=False))
    assert ci.lockup.status == "no_data" and ci.wheelspin.status == "no_data"
    no_brake = _inputs(_lap(lambda t: np.zeros(len(t))))
    assert not no_brake.braked and no_brake.lockup.status == "not_applicable" and no_brake.release_s is None


def _two(
    lap_brake: Callable[[np.ndarray], np.ndarray], ref_brake: Callable[[np.ndarray], np.ndarray]
) -> tuple[CornerInputs, CornerInputs]:
    return _inputs(_lap(lap_brake)), _inputs(_lap(ref_brake))


def test_notes_describe_the_difference_and_never_say_brake_later() -> None:
    lap, ref = _two(step, steady)
    notes = compare_inputs(lap, ref, Tolerances(0.08, 0.10))
    release = next(n for n in notes if n.metric == "release")
    assert release.notable and release.delta is not None and release.delta < 0
    assert "let off in one go vs eased off steadily" in release.text
    assert release.text_simple == "You let off the brake more quickly than on your reference."
    for n in notes:
        assert "brake later" not in n.text.lower() and "brake earlier" not in n.text.lower()
    assert len(top_notes(notes)) <= 3 and all(n.notable for n in top_notes(notes))


def test_pedal_tolerances_change_what_is_notable() -> None:
    def soft(t: np.ndarray) -> np.ndarray:
        return 0.90 * step(t)

    def softer(t: np.ndarray) -> np.ndarray:
        return 0.84 * step(t)

    lap, ref = _two(soft, softer)
    hall = pedal_info("csl")
    lc = pedal_info("csl_load_cell")
    assert hall.peak_tol == 0.08 and lc.peak_tol == 0.05 and lc.brake_sensor == "load_cell"
    peak_hall = next(n for n in compare_inputs(lap, ref, hall.tolerances) if n.metric == "brake_peak")
    peak_lc = next(n for n in compare_inputs(lap, ref, lc.tolerances) if n.metric == "brake_peak")
    assert not peak_hall.notable and peak_lc.notable  # 6 points: noise for pedal travel, real for force
    changed = pedal_info("csl_load_cell", "csl", ref_known=True)
    assert changed.changed_since_reference and changed.peak_tol == 0.08 and "not like-for-like" in changed.note
    unknown = pedal_info(None)
    assert unknown.pedals is None and unknown.peak_tol == 0.08 and unknown.changed_since_reference is None


def test_braking_assist_mutes_brake_notes_only() -> None:
    lap, ref = _two(step, steady)
    lap.coast_s, ref.coast_s = 1.0, 0.2
    notes = compare_inputs(lap, ref, Tolerances(0.08, 0.10), muted=True)
    brake = [n for n in notes if n.metric in ("release", "brake_peak", "time_to_peak", "trail_overlap")]
    assert brake and all(n.muted for n in brake)
    assert next(n for n in notes if n.metric == "coast").muted is False
    assert top_notes(notes)[0].metric == "coast"  # unmuted notes first


def test_habits_need_the_same_sign_on_half_the_laps() -> None:
    lap, ref = _two(step, steady)
    per_lap = [compare_inputs(lap, ref, Tolerances(0.08, 0.10)) for _ in range(3)]
    per_lap.append(compare_inputs(ref, ref, Tolerances(0.08, 0.10)))
    hs = habits(per_lap)
    release = next(h for h in hs if h.metric == "release")
    assert release.laps == 3 and release.laps_total == 4 and release.text.startswith("On 3 of 4 laps")
    assert not habits(per_lap[:1])  # one lap is not a habit
