"""Braking-event detection (Stage A of the braking model).

Works on the lap's native samples (not the resampled grid) so onset/release points keep the game's
temporal resolution; crossing points are interpolated between samples for sub-sample precision.

Trail braking (``trail_brake_m``) needs the steering: a lap whose steering has no finite sample over a braking event
(Assetto Corsa and GT7 variant A send none) leaves it ``None``, not a measured 0 m, so a game without steering never
reads as a driver who brakes in a straight line (unknown stays unknown). Coasting needs only the pedals.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from pitwall.analysis.distance import monotonic_mask
from pitwall.analysis.laps import FloatArray, LapTrace

BRAKE_ON = 0.10  # pedal fraction that starts a braking event
BRAKE_OFF = 0.05  # pedal fraction that ends it (hysteresis avoids chatter)
MIN_DURATION_S = 0.15
MERGE_GAP_S = 0.25  # re-application within this time is the same braking event (e.g. a stab)
THROTTLE_PICKUP = 0.20
THROTTLE_FULL = 0.95
TRAIL_STEER = 0.08  # |steering| above which braking counts as trail-braking


@dataclass(slots=True, frozen=True)
class BrakingEvent:
    start_m: float  # distance where brake crossed BRAKE_ON
    end_m: float  # distance where brake fell below BRAKE_OFF
    start_speed_kph: float
    end_speed_kph: float
    min_speed_kph: float  # minimum speed between onset and throttle pickup (apex proxy)
    min_speed_m: float
    peak_brake: float
    time_to_peak_s: float  # onset -> 90% of peak (initial application aggressiveness)
    release_s: float  # last time >= 90% peak -> below BRAKE_OFF (release progressiveness)
    duration_s: float
    # distance braking while |steering| > TRAIL_STEER; None = the lap's steering was not measured over the event
    trail_brake_m: float | None
    throttle_pickup_m: float | None  # first throttle > THROTTLE_PICKUP after min speed
    throttle_full_m: float | None  # first throttle > THROTTLE_FULL after min speed
    coast_m: float  # distance with neither brake nor throttle between release and pickup

    @property
    def braking_distance_m(self) -> float:
        return self.end_m - self.start_m


def _interp_cross(d: FloatArray, y: FloatArray, i: int, thr: float) -> float:
    """Distance of the crossing of ``thr`` between samples i-1 and i."""
    a, b = y[i - 1], y[i]
    if i == 0 or b == a:
        return float(d[i])
    w = float(np.clip((thr - a) / (b - a), 0.0, 1.0))
    return float(d[i - 1] + w * (d[i] - d[i - 1]))


def detect_braking(lap: LapTrace) -> list[BrakingEvent]:
    c = lap.channels
    mask = monotonic_mask(c["distance_m"])
    d = c["distance_m"][mask]
    t = c["session_time_s"][mask]
    b = np.nan_to_num(c["brake"][mask], nan=0.0)
    thr = np.nan_to_num(c["throttle"][mask], nan=0.0)
    v = c["speed_kph"][mask]
    steer_raw = c["steering"][mask]
    steered = np.isfinite(steer_raw)  # samples whose steering was measured
    steer = np.nan_to_num(steer_raw, nan=0.0)
    n = len(d)
    if n < 3:
        return []

    # 1. raw on/off intervals with hysteresis
    intervals: list[list[int]] = []
    on = False
    start = 0
    for i in range(n):
        if not on and b[i] >= BRAKE_ON:
            on, start = True, i
        elif on and b[i] < BRAKE_OFF:
            on = False
            intervals.append([start, i])
    if on:
        intervals.append([start, n - 1])
    # 2. merge stabs
    merged: list[list[int]] = []
    for iv in intervals:
        if merged and t[iv[0]] - t[merged[-1][1]] < MERGE_GAP_S:
            merged[-1][1] = iv[1]
        else:
            merged.append(iv)

    events: list[BrakingEvent] = []
    for k, (i0, i1) in enumerate(merged):
        if t[i1] - t[i0] < MIN_DURATION_S:
            continue
        nxt = merged[k + 1][0] if k + 1 < len(merged) else n - 1
        seg = slice(i0, i1 + 1)
        peak = float(b[seg].max())
        i_peak90 = i0 + int(np.argmax(b[seg] >= 0.9 * peak))
        last_hi = i0 + int(np.nonzero(b[seg] >= 0.9 * peak)[0][-1])
        # apex proxy: min speed between onset and the next braking event (or lap end)
        search_end = max(i1 + 1, nxt)
        j_min = i0 + int(np.nanargmin(v[i0:search_end]))
        pickup = full = None
        pickup_i = None
        for j in range(j_min, search_end):
            if pickup is None and thr[j] >= THROTTLE_PICKUP:
                pickup = _interp_cross(d, thr, j, THROTTLE_PICKUP)
                pickup_i = j
            if thr[j] >= THROTTLE_FULL:
                full = _interp_cross(d, thr, j, THROTTLE_FULL)
                break
        coast_end = pickup_i if pickup_i is not None else search_end
        coast = 0.0
        for j in range(i1, min(coast_end, n - 1)):
            if b[j] < BRAKE_OFF and thr[j] < 0.05:
                coast += float(d[j + 1] - d[j])
        trail: float | None = None
        if steered[i0 : i1 + 1].any():
            trail = float(
                sum(
                    d[j + 1] - d[j]
                    for j in range(i0, min(i1, n - 1))
                    if abs(steer[j]) > TRAIL_STEER and b[j] >= BRAKE_OFF
                )
            )
        events.append(
            BrakingEvent(
                start_m=_interp_cross(d, b, i0, BRAKE_ON),
                end_m=_interp_cross(d, b, i1, BRAKE_OFF),
                start_speed_kph=float(v[i0]),
                end_speed_kph=float(v[i1]),
                min_speed_kph=float(v[j_min]),
                min_speed_m=float(d[j_min]),
                peak_brake=peak,
                time_to_peak_s=float(t[i_peak90] - t[i0]),
                release_s=float(t[i1] - t[last_hi]),
                duration_s=float(t[i1] - t[i0]),
                trail_brake_m=trail,
                throttle_pickup_m=pickup,
                throttle_full_m=full,
                coast_m=coast,
            )
        )
    return events
