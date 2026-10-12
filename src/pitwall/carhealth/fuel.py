"""Fuel for games that send only how full the tank is (``CarHealthView.fuel``).

* **F1**: unchanged - the race strategy engineer (``strategy.fuel``) and the per-lap facts own it; the block is null.
* **Forza (Motorsport and Horizon)**: ``SessionInfo.extra["fuel_fraction"]`` (Dash.Fuel, 0..1 per the community docs)
  -> ``TankFractionFuel``: laps of fuel from how fast the level falls. No litres or kilos (no tank size is sent), no
  margin (no race length is sent). Community-documented, tested on generated data only.
* **GT7**: the same estimator, switched off by ``thresholds.GT7_FUEL_ENABLED``: all four owner captures read 100 / 100,
  so nothing shows the level falls or what its unit is. Status ``unverified``, with no numbers anywhere.
* **Assetto Corsa**: no fuel in RTCarInfo (``not_sent``).

Per lap: the level at its start and at the next line (the first level seen in the next lap). A lap is usable when the
lap number went up by exactly one, the level did not rise by ``REFUEL_UP`` inside it (a rise is a refuel, rewind or
reset: the stint starts over), its use is within ``LAP_DROP_MIN``..``LAP_DROP_MAX`` and it is not the first lap seen.
``per_lap`` = the median of the last ``FUEL_LAPS_USED`` usable laps (at least ``FUEL_MIN_LAPS``); laps of fuel = level
/ per_lap. The thresholds scale with the range the level is sent in (0..1, or 0..100 if a game sends per cent), so the
unit cancels.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

from pitwall.carhealth import thresholds as T

STATUS_UNKNOWN = "unknown"
STATUS_OK = "ok"
STATUS_LOW = "low"
STATUS_CRITICAL = "critical"
STATUS_NOT_USED = "not_used"
STATUS_UNVERIFIED = "unverified"
STATUS_NOT_SENT = "not_sent"


@dataclass(slots=True)
class _Lap:
    lap: int
    first: float
    last: float
    rise: float = 0.0  # the largest rise inside the lap
    from_prev: bool = False  # the lap number went up by exactly one into this lap


class TankFractionFuel:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.level: float | None = None
        self._scale = 1.0
        self._cur: _Lap | None = None
        self._usable: list[float] = []  # per-lap use of the current stint's usable laps
        self._complete: list[float] = []  # per-lap use of every complete lap of the stint (fuel use off?)
        self.seen = False

    def on_level(self, level: float, lap: int | None, on_track: bool = True) -> None:
        """One level (2 Hz) with the latest frame's lap number; ``on_track``: not paused, not in the menus."""
        if level != level or level < 0:  # NaN / garbage
            return
        self.seen = True
        if level > 1.5:
            self._scale = 100.0
        self.level = level
        if lap is None or not on_track:
            return
        cur = self._cur
        if cur is None:
            self._cur = _Lap(lap, level, level)
            return
        if lap == cur.lap:
            if level > cur.last + T.REFUEL_UP * self._scale:
                self._restart(lap, level)  # refuel, rewind or reset inside the lap
                return
            cur.rise = max(cur.rise, level - cur.last)
            cur.last = level
            return
        if lap == cur.lap + 1:
            if level > cur.last + T.REFUEL_UP * self._scale:
                self._restart(lap, level)  # refuelled across the line
                return
            cur.last = level  # the level at the line ends this lap and starts the next
            self._finish(cur)
            self._cur = _Lap(lap, level, level, from_prev=True)
            return
        self._restart(lap, level)  # a rewind, a skipped lap, a new race

    def _restart(self, lap: int, level: float) -> None:
        self._cur = _Lap(lap, level, level)
        self._usable = []
        self._complete = []

    def _finish(self, lap: _Lap) -> None:
        if not lap.from_prev:
            return  # the first lap seen (joined part-way): never usable
        drop = lap.first - lap.last
        self._complete = [*self._complete, drop][-T.FUEL_LAPS_USED :]
        if T.LAP_DROP_MIN * self._scale <= drop <= T.LAP_DROP_MAX * self._scale:
            self._usable = [*self._usable, drop][-T.FUEL_LAPS_USED :]

    # ------------------------------------------------------------------ outputs
    def per_lap(self) -> float | None:
        if len(self._usable) < T.FUEL_MIN_LAPS:
            return None
        return statistics.median(self._usable)

    def laps_of_fuel(self) -> float | None:
        per = self.per_lap()
        if per is None or per <= 0 or self.level is None:
            return None
        return self.level / per

    def status(self) -> str:
        if not self.enabled:
            return STATUS_UNVERIFIED
        if len(self._complete) >= 2 and sum(self._complete[-2:]) < T.NOT_USED_DROP * self._scale:
            return STATUS_NOT_USED
        laps = self.laps_of_fuel()
        if laps is None:
            return STATUS_UNKNOWN
        if laps <= T.FUEL_CRITICAL_LAPS:
            return STATUS_CRITICAL
        if laps <= T.FUEL_LOW_LAPS:
            return STATUS_LOW
        return STATUS_OK

    def view(self, reason: str | None = None) -> dict[str, Any]:
        status = self.status()
        if status == STATUS_UNVERIFIED:
            return {
                "source": "tank_fraction",
                "status": STATUS_UNVERIFIED,
                "fraction": None,
                "per_lap": None,
                "laps_of_fuel": None,
                "laps_used": None,
                "tier": "unverified",
                "reason": reason,
            }
        per, laps = self.per_lap(), self.laps_of_fuel()
        frac = None if self.level is None else self.level / self._scale
        return {
            "source": "tank_fraction",
            "status": status,
            "fraction": None if frac is None else round(frac, 4),
            "per_lap": None if per is None else round(per / self._scale, 4),
            "laps_of_fuel": None if laps is None else round(laps, 1),
            "laps_used": len(self._usable),
            "tier": "community",
            "reason": "fuel use is off in this race" if status == STATUS_NOT_USED else None,
        }
