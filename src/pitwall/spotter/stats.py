"""Bounded rings with percentiles computed on read (spotter latency and data-age diagnostics)."""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable

RING_SIZE = 200


def percentile(values: Iterable[float], q: float) -> float | None:
    """Nearest-rank percentile (``q`` 0-100) of finite values; None when there are none."""
    ordered = sorted(v for v in values if math.isfinite(v))
    if not ordered:
        return None
    k = min(len(ordered) - 1, max(0, math.ceil(q / 100.0 * len(ordered)) - 1))
    return ordered[k]


class Ring:
    """The last ``size`` samples of one measure. ``add`` is O(1) (one deque append) from a single writer thread;
    readers copy it first (``list(deque)`` is atomic in CPython), so no lock is needed."""

    __slots__ = ("_d",)

    def __init__(self, size: int = RING_SIZE) -> None:
        self._d: deque[float] = deque(maxlen=size)

    def add(self, value: float) -> None:
        if math.isfinite(value):
            self._d.append(value)

    def values(self) -> list[float]:
        return list(self._d)

    def __len__(self) -> int:
        return len(self._d)

    def median(self) -> float | None:
        return percentile(self.values(), 50)

    def summary(self, digits: int = 1) -> dict[str, float | int | None]:
        vals = self.values()
        p50, p95 = percentile(vals, 50), percentile(vals, 95)
        top = max(vals) if vals else None
        return {
            "p50": None if p50 is None else round(p50, digits),
            "p95": None if p95 is None else round(p95, digits),
            "max": None if top is None else round(top, digits),
            "n": len(vals),
        }
