"""Small O(1)-update statistics for the car health monitors: fixed-bin histograms (medians without keeping samples)
and a time-bounded rolling window."""

from __future__ import annotations

import math
import statistics
from collections import deque


class Hist:
    """Counts per ``bin`` (1 C for temperatures): ``add`` is O(1); ``median`` walks the occupied bins (a few dozen)."""

    __slots__ = ("bin", "counts", "max", "n", "seconds")

    def __init__(self, bin: float = 1.0) -> None:
        self.bin = bin
        self.counts: dict[int, int] = {}
        self.n = 0
        self.max: float | None = None
        self.seconds = 0.0  # racing time the samples stand for (the caller adds each frame's time step)

    def add(self, v: float, dt: float = 0.0) -> None:
        if not math.isfinite(v):
            return
        k = round(v / self.bin)
        self.counts[k] = self.counts.get(k, 0) + 1
        self.n += 1
        self.seconds += dt
        self.max = v if self.max is None or v > self.max else self.max

    def median(self) -> float | None:
        if self.n == 0:
            return None
        half = self.n / 2
        acc = 0
        for k in sorted(self.counts):
            acc += self.counts[k]
            if acc >= half:
                return k * self.bin
        return None  # pragma: no cover - acc reaches n

    def clear(self) -> None:
        self.counts.clear()
        self.n = 0
        self.max = None
        self.seconds = 0.0


class Window:
    """Samples of the last ``span_s`` seconds (game clock), at most one every ``every_s``; the median on demand."""

    __slots__ = ("_last", "every_s", "q", "span_s")

    def __init__(self, span_s: float, every_s: float = 0.1) -> None:
        self.span_s = span_s
        self.every_s = every_s
        self.q: deque[tuple[float, float]] = deque()
        self._last = -math.inf

    def add(self, t: float, v: float) -> None:
        if not math.isfinite(v) or t - self._last < self.every_s:
            return
        self._last = t
        self.q.append((t, v))
        while self.q and self.q[0][0] < t - self.span_s:
            self.q.popleft()

    def spanned(self) -> float:
        return 0.0 if len(self.q) < 2 else self.q[-1][0] - self.q[0][0]

    def median(self) -> float | None:
        return statistics.median(v for _, v in self.q) if self.q else None

    def clear(self) -> None:
        self.q.clear()
        self._last = -math.inf


def median_or_none(vals: list[float]) -> float | None:
    return statistics.median(vals) if vals else None
