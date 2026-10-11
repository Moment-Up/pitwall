"""Shared helpers: a lap's native samples (monotonic in distance), runs of a condition, and JSON rounding."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from pitwall.analysis.distance import monotonic_mask
from pitwall.analysis.laps import FloatArray, LapTrace

BoolArray = npt.NDArray[np.bool_]


@dataclass(slots=True)
class Native:
    """A lap's samples where distance strictly increases (as ``analysis.braking`` uses them)."""

    d: FloatArray
    t: FloatArray
    brake: FloatArray  # NaN -> 0
    throttle: FloatArray  # NaN -> 0
    steer: FloatArray  # NaN -> 0
    speed: FloatArray  # km/h, may hold NaN
    channels: dict[str, FloatArray]  # every other stored channel on the same samples (may hold NaN)

    @property
    def n(self) -> int:
        return len(self.d)

    def get(self, name: str) -> FloatArray | None:
        """A channel on these samples, or None when the lap does not store it or it is all NaN."""
        arr = self.channels.get(name)
        if arr is None or not np.isfinite(arr).any():
            return None
        return arr

    def index_at(self, dist: float) -> int:
        """Index of the first sample at or after ``dist`` (clipped)."""
        return int(min(self.n - 1, max(0, int(np.searchsorted(self.d, dist)))))

    def dt(self) -> FloatArray:
        """Duration of each sample (time to the next one; the last repeats the previous step)."""
        if self.n < 2:
            return np.zeros(self.n)
        step = np.diff(self.t)
        step = np.where(np.isfinite(step) & (step > 0) & (step < 1.0), step, 0.0)
        return np.concatenate([step, step[-1:]])


def native(lap: LapTrace) -> Native:
    c = lap.channels
    mask = monotonic_mask(c["distance_m"])
    d = c["distance_m"][mask]
    t = c["session_time_s"][mask]

    def z(name: str) -> FloatArray:
        arr = c.get(name)
        return np.zeros(len(d)) if arr is None else np.nan_to_num(arr[mask], nan=0.0)

    speed = c["speed_kph"][mask] if "speed_kph" in c else np.full(len(d), np.nan)
    rest = {k: v[mask] for k, v in c.items() if k not in ("distance_m", "session_time_s")}
    return Native(d=d, t=t, brake=z("brake"), throttle=z("throttle"), steer=z("steering"), speed=speed, channels=rest)


def runs(mask: BoolArray) -> list[tuple[int, int]]:
    """``(start, end_inclusive)`` index pairs of consecutive True values."""
    if len(mask) == 0:
        return []
    m = np.concatenate([[False], mask.astype(bool), [False]])
    edges = np.flatnonzero(np.diff(m.astype(np.int8)))
    return [(int(a), int(b) - 1) for a, b in zip(edges[::2], edges[1::2], strict=True)]


def run_duration(t: FloatArray, dt: FloatArray, a: int, b: int) -> float:
    """Duration of samples a..b (inclusive), counting each sample's own step."""
    return float(np.sum(dt[a : b + 1]))


def rnd(x: float | None, nd: int) -> float | None:
    """Rounded for JSON; None for missing or non-finite values."""
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return round(f, nd) + 0.0  # + 0.0 turns -0.0 into 0.0


def m2(x: float | None) -> float | None:
    return rnd(x, 2)


def s2(x: float | None) -> float | None:
    return rnd(x, 2)


def deg1(x: float | None) -> float | None:
    return rnd(x, 1)


def xz_list(a: FloatArray, b: FloatArray) -> list[list[float] | None]:
    """Ground-plane points as ``[[a, b] | null, ...]`` rounded to 0.01 m."""
    out: list[list[float] | None] = []
    for x, y in zip(a, b, strict=True):
        if np.isfinite(x) and np.isfinite(y):
            out.append([round(float(x), 2), round(float(y), 2)])
        else:
            out.append(None)
    return out


def finite_or_none(x: Any) -> float | None:
    if x is None:
        return None
    f = float(x)
    return f if math.isfinite(f) else None
