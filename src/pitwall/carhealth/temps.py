"""Brake and engine temperatures (F1 only), against this session's own laps: shown on Drive and answered on request,
never called proactively.

No reliable threshold exists: the games publish no brake or engine windows, and on every recorded F1 25 / F2 race the
values were never abnormal (engine 103-132 C, brake lap peaks 424-1030 C). So:

* **Brakes**: the lap's peak per wheel over racing frames; the session baseline per wheel is the median of the usable
  laps' peaks (at least ``MIN_BASE_LAPS``). The last lap is "normal" within ``BRAKE_NORMAL_C`` of it, else "hotter" /
  "cooler" than usual.
* **Engine**: the lap median; the baseline is the median of the lap medians. "steady" within ``ENGINE_STEADY_C``,
  else "hotter" / "cooler" than earlier.

A usable lap has ``MIN_LAP_RACING_S`` of racing frames, no pit visit and no flashback. GT7's water and oil temperatures
are constants (85 / 110 C, not simulated) and stay unknown; Forza and Assetto Corsa send neither.
"""

from __future__ import annotations

from typing import Any

from pitwall.carhealth import thresholds as T
from pitwall.carhealth.stats import Hist, median_or_none
from pitwall.carhealth.tyres import racing
from pitwall.model.telemetry import CarFrame

KEEP_LAPS = 30
MAX_DT_S = 0.5


class BrakeEngineMonitor:
    def __init__(self) -> None:
        self.brakes_seen = False
        self.engine_seen = False
        self._brake_max: list[float | None] = [None] * 4
        self._engine = Hist()
        self._racing_s = 0.0
        self._prev_t: float | None = None
        self._lap_ok = True  # no pit visit, no flashback in the lap so far
        self.brake_laps: list[tuple[int, tuple[float, ...]]] = []  # usable laps' peaks
        self.engine_laps: list[tuple[int, float, float]] = []  # usable laps' (lap, median, max)
        self.last_brake: tuple[int, tuple[float, ...]] | None = None
        self.last_engine: tuple[int, float, float] | None = None
        self.engine_now: float | None = None

    def on_frame(self, f: CarFrame) -> None:
        if f.brake_temp_c is not None:
            self.brakes_seen = True
        if f.engine_temp_c is not None:
            self.engine_seen = True
            if racing(f):  # on track only: the garage and the menus are not the engine running
                self.engine_now = f.engine_temp_c
        if f.pit_status:
            self._lap_ok = False
        t = f.session_time_s
        if t is None or not racing(f):
            self._prev_t = None
            return
        prev = self._prev_t
        self._prev_t = t
        if prev is not None and 0.0 < t - prev <= MAX_DT_S:
            self._racing_s += t - prev
        if f.brake_temp_c is not None:
            for k, v in enumerate(f.brake_temp_c.as_tuple()):
                cur = self._brake_max[k]
                self._brake_max[k] = v if cur is None or v > cur else cur
        if f.engine_temp_c is not None:
            self._engine.add(f.engine_temp_c)

    def on_line(self, finished_lap: int) -> None:
        usable = self._lap_ok and self._racing_s >= T.MIN_LAP_RACING_S
        peaks = self._brake_max
        if all(p is not None for p in peaks):
            rec_b = (finished_lap, tuple(float(p) for p in peaks if p is not None))
            self.last_brake = rec_b
            if usable:
                self.brake_laps = [*self.brake_laps, rec_b][-KEEP_LAPS:]
        med = self._engine.median()
        if med is not None and self._engine.max is not None:
            rec_e = (finished_lap, med, self._engine.max)
            self.last_engine = rec_e
            if usable:
                self.engine_laps = [*self.engine_laps, rec_e][-KEEP_LAPS:]
        self._reset_lap()

    def rewind(self) -> None:
        """A flashback: the lap in progress is driven again and does not count for the baseline."""
        self._reset_lap()
        self._lap_ok = False

    def _reset_lap(self) -> None:
        self._brake_max = [None] * 4
        self._engine.clear()
        self._racing_s = 0.0
        self._prev_t = None
        self._lap_ok = True

    # ------------------------------------------------------------------ outputs
    def brake_baseline(self) -> tuple[float, ...] | None:
        if len(self.brake_laps) < T.MIN_BASE_LAPS:
            return None
        cols = list(zip(*(peaks for _, peaks in self.brake_laps), strict=True))
        return tuple(float(median_or_none(list(c)) or 0.0) for c in cols)

    def engine_baseline(self) -> float | None:
        if len(self.engine_laps) < T.MIN_BASE_LAPS:
            return None
        return median_or_none([m for _, m, _ in self.engine_laps])

    def brakes_view(self) -> dict[str, Any]:
        last = self.last_brake
        base = self.brake_baseline()
        word = None
        if last is not None and base is not None:
            diffs = [p - b for p, b in zip(last[1], base, strict=True)]
            worst = max(diffs, key=abs)
            word = "normal" if abs(worst) <= T.BRAKE_NORMAL_C else ("hotter" if worst > 0 else "cooler")
        return {
            "available": True,
            "lap": None if last is None else last[0],
            "last_lap_max_c": None if last is None else [round(v) for v in last[1]],
            "baseline_max_c": None if base is None else [round(v) for v in base],
            "laps": len(self.brake_laps),
            "word": word,
            "reason": None if word is not None else "needs two full laps",
        }

    def engine_view(self) -> dict[str, Any]:
        last = self.last_engine
        base = self.engine_baseline()
        word = None
        if last is not None and base is not None:
            d = last[1] - base
            word = "steady" if abs(d) <= T.ENGINE_STEADY_C else ("hotter" if d > 0 else "cooler")
        return {
            "available": True,
            "now_c": None if self.engine_now is None else round(self.engine_now),
            "lap": None if last is None else last[0],
            "lap_median_c": None if last is None else round(last[1], 1),
            "max_c": None if last is None else round(last[2], 1),
            "baseline_c": None if base is None else round(base, 1),
            "laps": len(self.engine_laps),
            "word": word,
            "reason": None if word is not None else "needs two full laps",
        }
