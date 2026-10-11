"""Quasi-steady-state lap simulation with an injectable driver model.

Produces a distance-domain speed profile from a simple F1-like vehicle model (grip + downforce,
power-limited acceleration, aero drag), then applies per-corner driver deviations with *known ground truth*
(e.g. "brakes 15 m early into T3"). The synthetic analysis tests assert that the coaching pipeline recovers
exactly these injected deviations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from pitwall.sim.track import FloatArray, TrackGeometry

G = 9.81


@dataclass(frozen=True, slots=True)
class VehicleModel:
    mu_lat: float = 1.65  # mechanical lateral grip (g)
    aero_lat: float = 0.0047  # extra lateral accel per v^2 (1/m)
    brake_base: float = 14.0  # m/s^2 at zero speed
    brake_aero: float = 0.0058  # extra braking decel per v^2 (1/m)
    power_per_mass: float = 920.0  # W/kg
    traction_limit: float = 12.0  # m/s^2
    drag: float = 0.00109  # drag decel per v^2 (1/m)
    v_max: float = 95.0  # m/s hard cap
    gear_top_kph: tuple[float, ...] = (95, 135, 170, 205, 240, 275, 310, 345)
    idle_rpm: float = 4000.0
    max_rpm: float = 12500.0
    wheelbase_m: float = 3.6
    max_steer_rad: float = 0.35

    def corner_speed(self, curvature: float) -> float:
        k = abs(curvature)
        if k < 1e-6:
            return self.v_max
        denom = k - self.aero_lat
        if denom <= 0:
            return self.v_max
        return min(self.v_max, math.sqrt(self.mu_lat * G / denom))

    def accel(self, v: float) -> float:
        return min(self.traction_limit, self.power_per_mass / max(v, 1.0)) - self.drag * v * v

    def brake(self, v: float) -> float:
        return self.brake_base + self.brake_aero * v * v


@dataclass(slots=True)
class CornerDeviation:
    """Ground-truth driver deviations for one corner, relative to the optimal profile."""

    brake_early_m: float = 0.0  # starts braking this much earlier (and coasts at apex speed)
    apex_speed_loss_kph: float = 0.0  # minimum speed this much lower than optimum
    throttle_delay_m: float = 0.0  # holds apex speed this much longer before accelerating
    # --- feat/technique: injected in the synthetic F1 stream only (``F1Scenario.motion_ex``); speed is unchanged ---
    line_offset_m: float = 0.0  # runs this far towards the outside around the apex (raised cosine, apex +/- 120 m)
    understeer_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)  # extra front slip angle at entry, mid, exit
    lockup_s: float = 0.0  # front-left wheel locked (slip ratio -0.35) for this long in the braking zone
    wheelspin_s: float = 0.0  # rear wheels spinning (slip ratio +0.3) for this long on the exit
    body_slip_exit_deg: float = 0.0  # body slip during the exit wheelspin window (a slide)
    # --- end feat/technique ---


@dataclass(slots=True)
class DriverProfile:
    deviations: dict[str, CornerDeviation] = field(default_factory=dict)
    noise_m: float = 0.0  # random per-lap jitter on braking points (m, 1 sigma)
    seed: int = 0


@dataclass(slots=True)
class LapProfile:
    s: FloatArray
    v: FloatArray  # m/s
    throttle: FloatArray
    brake: FloatArray
    steering: FloatArray
    gear: npt.NDArray[np.int64]
    rpm: FloatArray
    g_lat: FloatArray
    g_lon: FloatArray
    t: FloatArray  # cumulative time at each s (s), t[0] == 0
    lap_time_s: float  # including the final step back to the start line


def _limit_profile(track: TrackGeometry, veh: VehicleModel) -> FloatArray:
    return np.array([veh.corner_speed(k) for k in track.curvature])


def _apex_index(track: TrackGeometry, start: float, end: float) -> int:
    lo = int(np.searchsorted(track.s, start))
    hi = max(lo + 1, int(np.searchsorted(track.s, end)))
    return lo + int(np.argmax(np.abs(track.curvature[lo:hi])))


def _solve_periodic(vlim: FloatArray, veh: VehicleModel, ds: float) -> FloatArray:
    """Forward (traction/power) and backward (braking) passes on a closed loop."""
    n = len(vlim)
    v = vlim.copy()
    for _ in range(2):  # second sweep carries the lap-end speed into the lap start
        v[0] = min(v[0], math.sqrt(v[-1] ** 2 + 2 * max(0.0, veh.accel(v[-1])) * ds))
        for i in range(1, n):
            a = veh.accel(v[i - 1])
            v[i] = min(v[i], math.sqrt(max(0.0, v[i - 1] ** 2 + 2 * a * ds)))
    for _ in range(2):
        v[-1] = min(v[-1], math.sqrt(v[0] ** 2 + 2 * veh.brake(v[0]) * ds))
        for i in range(n - 2, -1, -1):
            v[i] = min(v[i], math.sqrt(v[i + 1] ** 2 + 2 * veh.brake(v[i + 1]) * ds))
    return v


def solve_lap(
    track: TrackGeometry,
    veh: VehicleModel,
    driver: DriverProfile | None = None,
    lap_index: int = 0,
    v_start: float | None = None,
) -> LapProfile:
    """Forward/backward pass speed solver with driver deviations applied as extra constraints."""
    driver = driver or DriverProfile()
    rng = np.random.default_rng(driver.seed * 1000 + lap_index)
    n = len(track.s)
    ds = float(track.s[1] - track.s[0])
    base = _limit_profile(track, veh)
    v_opt = _solve_periodic(base, veh, ds)
    vlim = base.copy()
    hold = np.zeros(n, dtype=bool)  # positions where the driver holds constant speed (part throttle)

    for name, start, end in track.corners:
        dev = driver.deviations.get(name)
        if dev is None and driver.noise_m == 0:
            continue
        dev = dev or CornerDeviation()
        apex = _apex_index(track, start, end)
        # Anchor deviations to where the *optimal* profile finishes braking, so an injected
        # "brake_early_m" moves the braking point by exactly that distance (known ground truth).
        brake_end = apex
        while brake_end > 0 and v_opt[brake_end - 1] < v_opt[brake_end] + 0.05:
            brake_end -= 1
        v_target = float(v_opt[apex]) - dev.apex_speed_loss_kph / 3.6
        early = dev.brake_early_m + (rng.normal(0, driver.noise_m) if driver.noise_m else 0.0)
        early_n = max(0, round(early / ds))
        late_n = max(0, round(dev.throttle_delay_m / ds))
        # ...and anchor throttle delay to where the optimal profile starts accelerating again.
        accel_start = apex
        while accel_start < n - 1 and v_opt[accel_start + 1] <= v_opt[accel_start] + 0.05:
            accel_start += 1
        lo = max(0, brake_end - early_n)
        hi = min(n - 1, (accel_start if late_n else apex) + late_n)
        vlim[lo : hi + 1] = np.minimum(vlim[lo : hi + 1], v_target)
        if early_n or late_n:
            hold[lo : hi + 1] = True

    v = _solve_periodic(vlim, veh, ds)
    if v_start is not None:
        v[0] = min(v[0], v_start)

    # derive time and inputs
    v = np.maximum(v, 5.0)
    dv2 = np.diff(v**2, append=v[0] ** 2)
    a_lon = dv2 / (2 * ds)
    throttle = np.zeros(n)
    brake = np.zeros(n)
    for i in range(n):
        vi = v[i]
        drag = veh.drag * vi * vi
        if a_lon[i] > 1e-3:
            avail = veh.accel(vi) + drag
            throttle[i] = min(1.0, (a_lon[i] + drag) / max(avail, 1e-6))
        elif a_lon[i] < -drag - 0.5:
            brake[i] = min(1.0, (-a_lon[i] - drag) / (veh.brake(vi) - drag))
        else:
            throttle[i] = 1.0 if vi >= veh.v_max - 0.5 else min(1.0, 0.25 + drag / 30)
        if hold[i] and brake[i] < 0.05:
            throttle[i] = min(throttle[i], 0.35)
    steering = np.clip(track.curvature * veh.wheelbase_m / veh.max_steer_rad, -1, 1)
    kph = v * 3.6
    gear = np.searchsorted(np.array(veh.gear_top_kph), kph) + 1
    gear = np.clip(gear, 1, len(veh.gear_top_kph))
    lo_kph = np.array((0.0, *veh.gear_top_kph[:-1]))[gear - 1]
    hi_kph = np.array(veh.gear_top_kph)[gear - 1]
    frac = np.clip((kph - lo_kph * 0.75) / (hi_kph - lo_kph * 0.75), 0, 1)
    rpm = veh.idle_rpm + frac * (veh.max_rpm - veh.idle_rpm)
    g_lat = v * v * track.curvature / G
    g_lon = a_lon / G
    t = np.concatenate([[0.0], np.cumsum(ds / ((v[:-1] + v[1:]) / 2))])
    lap_time = float(t[-1] + ds / ((v[-1] + v[0]) / 2))
    return LapProfile(
        s=track.s,
        v=v,
        throttle=throttle,
        brake=brake,
        steering=steering,
        gear=gear,
        rpm=rpm,
        g_lat=g_lat,
        g_lon=g_lon,
        t=t,
        lap_time_s=lap_time,
    )
