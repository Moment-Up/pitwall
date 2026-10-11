"""Distance-domain resampling: put laps on a common track-distance grid so they can be compared
position-by-position rather than by elapsed time."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from pitwall.analysis.laps import FloatArray, LapTrace

GRID_STEP_M = 1.0
_NEAREST = {"gear"}  # discrete channels: hold previous value instead of interpolating


@dataclass(slots=True)
class DistanceTrace:
    d: FloatArray  # grid (m)
    t_s: FloatArray  # elapsed lap time at each grid point (s)
    ch: dict[str, FloatArray]  # other channels on the grid; NaN outside the lap's coverage
    lap_number: int

    def at(self, channel: str, d: float) -> float:
        arr = self.t_s if channel == "t_s" else self.ch[channel]
        return float(np.interp(d, self.d, arr, left=np.nan, right=np.nan))


def monotonic_mask(distance: FloatArray) -> np.ndarray:
    """Rows where distance strictly increases (drops stationary/backward samples and NaNs)."""
    ok = np.isfinite(distance)
    running = np.maximum.accumulate(np.where(ok, distance, -np.inf))
    prev = np.concatenate([[-np.inf], running[:-1]])
    return ok & (distance > prev)


def to_distance_domain(lap: LapTrace, length_m: float, step_m: float = GRID_STEP_M) -> DistanceTrace:
    c = lap.channels
    dist = c["distance_m"]
    t_ms = c["lap_time_ms"]
    mask = monotonic_mask(dist) & np.isfinite(t_ms)
    d_src = dist[mask]
    grid = np.arange(0.0, length_m, step_m)
    if len(d_src) < 2:
        nan = np.full_like(grid, np.nan)
        return DistanceTrace(d=grid, t_s=nan, ch={k: nan.copy() for k in c}, lap_number=lap.lap_number)
    lo, hi = d_src[0], d_src[-1]
    outside = (grid < lo) | (grid > hi)

    def resample(y: FloatArray, nearest: bool = False) -> FloatArray:
        y = y[mask]
        good = np.isfinite(y)
        if good.sum() < 2:
            return np.full_like(grid, np.nan)
        if nearest:
            idx = np.clip(np.searchsorted(d_src[good], grid, side="right") - 1, 0, good.sum() - 1)
            out = y[good][idx].astype(np.float64)
        else:
            out = np.interp(grid, d_src[good], y[good])
        out[outside] = np.nan
        return out

    t_s = resample(t_ms / 1000.0)
    ch = {k: resample(v, k in _NEAREST) for k, v in c.items() if k not in ("distance_m", "lap_time_ms")}
    _extend_edges(grid, t_s, ch, lo, hi)
    return DistanceTrace(d=grid, t_s=t_s, ch=ch, lap_number=lap.lap_number)


EDGE_EXTEND_M = 25.0


def _extend_edges(grid: FloatArray, t_s: FloatArray, ch: dict[str, FloatArray], lo: float, hi: float) -> None:
    """Fill the small gaps between the line and the first/last sample (samples are ~1-5 m apart, so a lap
    almost never has a sample exactly at 0 m). Time is extrapolated with the measured speed; other channels
    hold their edge value. Larger gaps stay NaN (genuinely missing data)."""
    speed = ch.get("speed_kph")
    for at_start in (True, False):
        edge_d = lo if at_start else hi
        gap = edge_d if at_start else grid[-1] - edge_d
        if gap <= 0 or gap > EDGE_EXTEND_M:
            continue
        idx = np.nonzero(grid < lo)[0] if at_start else np.nonzero(grid > hi)[0]
        ref_i = idx[-1] + 1 if at_start else idx[0] - 1
        if not (0 <= ref_i < len(grid)) or not np.isfinite(t_s[ref_i]):
            continue
        v = speed[ref_i] / 3.6 if speed is not None and np.isfinite(speed[ref_i]) and speed[ref_i] > 1 else None
        if v is None:
            continue
        t_s[idx] = t_s[ref_i] + (grid[idx] - grid[ref_i]) / v
        for arr in ch.values():
            if np.isfinite(arr[ref_i]):
                arr[idx] = arr[ref_i]


def crossing(d: FloatArray, y: FloatArray, threshold: float, start: int, rising: bool = True) -> float | None:
    """Sub-sample distance where ``y`` first crosses ``threshold`` at/after index ``start``."""
    n = len(y)
    for i in range(max(start, 1), n):
        a, b = y[i - 1], y[i]
        if not (np.isfinite(a) and np.isfinite(b)):
            continue
        if (rising and a < threshold <= b) or (not rising and a > threshold >= b):
            if b == a:
                return float(d[i])
            w = (threshold - a) / (b - a)
            return float(d[i - 1] + w * (d[i] - d[i - 1]))
    return None
