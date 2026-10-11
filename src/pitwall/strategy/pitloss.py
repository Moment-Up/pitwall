"""Pit stops of every car and the pit-lane loss they measure, from the game's own LapData (``RaceTiming``).

Real F1 25 (PS5, full Austria race): car 14 enters the pit lane at 4264 m on lap 65 (pit status 1), is in the box
7.2 s later (status 2), stops 3353 ms, leaves the lane at 257 m on lap 66; the lane timer reads 20019 ms and resets
to 0 at the exit; ``numPitStops`` increments and the driver status goes in-lap -> out-lap at the box.

* A visit opens on pit status 0 -> non-zero (entry lap E, entry distance) and closes on non-zero -> 0 (exit lap X).
  Lane time: the game's pit-lane timer (largest value seen), or the time between the two pit-status changes when
  that is longer (the timer resets at the exit; the adapter times both changes to the packet). Stationary time: the
  game's pit-stop timer (largest value seen).
* Per-car lap times are taken at each lap-number increment (``lastLapTimeInMS``); a lap is neutralised when a
  safety car or VSC ran during it.
* ``loss = sum(lap times E..X) - (X - E + 1) * pre_pace``, ``pre_pace`` = median of the car's last <= 3 green laps
  before E (complete, not lap 1, no pit, no safety car). A stop under a safety car / VSC uses as reference the
  median lap time of the cars that did not pit, lap by lap. Car 14 above: in-lap 81575 + out-lap 92836 - 2 x 77750
  = 18911 ms.
* Excluded stops keep their reason (``excluded``): a long stationary time (repair?), a penalty served, a safety car
  on only some of the stop's laps, no pre-stop green lap observed, an implausible loss, laps not all observed, a
  flashback during the stop, or (session end) the out-lap was never completed.

Nothing is carried across sessions: with no measured stop the pit loss is unknown.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from typing import Any

from pitwall.model.telemetry import CarTiming, RaceTiming

STATIONARY_MAX_MS = 6000  # [H] longer = repair or penalty, not a normal stop
LOSS_MIN_MS, LOSS_MAX_MS = 8_000, 45_000  # [H] plausible green pit loss
PRE_LAPS = 3
POST_LAPS = 3
SC_LOSS_FACTOR = {"full": 0.5, "virtual": 0.6}  # [H] unvalidated in F1 25: shown as an estimate only
NEUTRAL = ("full", "virtual")
_SEVERITY: dict[str | None, int] = {None: 0, "virtual": 1, "full": 2}

EXCLUDED_LONG_STOP = "long stop (repair?)"
EXCLUDED_PENALTY = "penalty served"
EXCLUDED_NO_PRE_LAP = "no pre-stop green lap observed"
EXCLUDED_IMPLAUSIBLE = "implausible loss"
EXCLUDED_LAPS_MISSING = "laps not all observed"
EXCLUDED_FLASHBACK = "flashback during the stop"
EXCLUDED_NOT_COMPLETED = "out-lap not completed"
# The safety car / VSC ran on some laps of the stop and not on others (it started or ended around the stop): the
# other cars' laps then hold different shares of neutralised running, so neither the green pace nor the field's laps
# are a fair reference (synthetic race-strategy-demo: a stop just after a VSC measured 14.9 s against a true 12.8 s).
EXCLUDED_PARTLY_NEUTRAL = "safety car on only part of the stop"


@dataclass(slots=True)
class PitVisit:
    car_index: int
    is_player: bool
    entry_lap: int
    entry_m: float | None
    t_entry: float
    entry_leader_ms: int | None  # the car's gap to the leader at pit entry (rejoin estimates)
    compound_before: str | None
    exit_lap: int | None = None
    exit_m: float | None = None
    t_exit: float | None = None
    compound_after: str | None = None
    lane_time_ms: int | None = None
    stationary_ms: int | None = None
    serve_penalty: bool = False
    laps_ms: list[int] = field(default_factory=list)
    pace_before_ms: int | None = None
    pace_after_ms: int | None = None
    pit_loss_ms: int | None = None
    neutralised: str | None = None
    excluded: str | None = None
    rewound: bool = False
    final: bool = False  # the loss has been worked out (or the stop excluded)
    post_done: bool = False

    def row(self) -> dict[str, Any]:
        """The ``pit_stops`` row (``storage.repo.upsert_pit_stop``)."""
        return {
            "car_index": self.car_index,
            "is_player": self.is_player,
            "entry_lap": self.entry_lap,
            "exit_lap": self.exit_lap,
            "entry_lap_distance_m": None if self.entry_m is None else round(self.entry_m, 1),
            "exit_lap_distance_m": None if self.exit_m is None else round(self.exit_m, 1),
            "lane_time_ms": self.lane_time_ms,
            "stationary_ms": self.stationary_ms,
            "laps_ms": list(self.laps_ms),
            "pace_before_ms": self.pace_before_ms,
            "pace_after_ms": self.pace_after_ms,
            "pit_loss_ms": self.pit_loss_ms,
            "neutralised": self.neutralised,
            "excluded": self.excluded,
            "compound_before": self.compound_before,
            "compound_after": self.compound_after,
            "session_time_s": round(self.t_entry, 3),
            "created_unix": time.time(),
        }


@dataclass(slots=True)
class _Car:
    lap: int | None = None
    pit_status: int = 0
    times: dict[int, int] = field(default_factory=dict)
    neutral: dict[int, str] = field(default_factory=dict)
    pitted: set[int] = field(default_factory=set)
    visit: PitVisit | None = None
    last: CarTiming | None = None


class PitTracker:
    """Feed every ``RaceTiming`` with the safety-car state (``update``). Visits that changed since the last call are
    returned by ``take_changed`` (to persist). Not thread-safe (the strategy worker owns it)."""

    def __init__(self) -> None:
        self.cars: dict[int, _Car] = {}
        self.visits: list[PitVisit] = []
        self._changed: list[PitVisit] = []

    # ------------------------------------------------------------------ input
    def update(self, timing: RaceTiming, safety_car: str | None) -> list[PitVisit]:
        """Returns visits that opened on this tick (pit entries)."""
        opened: list[PitVisit] = []
        t = timing.session_time_s
        neutral = safety_car if safety_car in NEUTRAL else None
        for c in timing.cars:
            st = self.cars.get(c.car_index)
            if st is None:
                st = self.cars[c.car_index] = _Car(lap=c.lap_number, pit_status=c.pit_status)
            elif st.lap is not None and c.lap_number > st.lap:
                if c.last_lap_ms is not None:
                    st.times[c.lap_number - 1] = c.last_lap_ms
                st.lap = c.lap_number
                self._lap_done(c.car_index, st)
            elif st.lap is None or c.lap_number < st.lap:
                if st.lap is not None:
                    # rewound (flashback): the laps from this one on are driven again, so what was seen of them goes
                    st.times = {k: v for k, v in st.times.items() if k < c.lap_number}
                    st.neutral = {k: v for k, v in st.neutral.items() if k <= c.lap_number}
                    st.pitted = {k for k in st.pitted if k <= c.lap_number}
                st.lap = c.lap_number  # rewound (flashback) or first lap seen
            lap = c.lap_number
            if neutral is not None and _SEVERITY[neutral] > _SEVERITY[st.neutral.get(lap)]:
                st.neutral[lap] = neutral
            if c.pit_status:
                st.pitted.add(lap)
            v = st.visit
            if c.result_status != "active" or c.driver_status == "garage":
                # retired / finished / in the garage: parked in the pits is not a pit stop
                st.visit = None
                st.pit_status = c.pit_status
                st.last = c
                continue
            if not st.pit_status and c.pit_status:
                v = st.visit = PitVisit(
                    car_index=c.car_index,
                    is_player=c.is_player,
                    entry_lap=lap,
                    entry_m=c.lap_distance_m,
                    t_entry=t,
                    entry_leader_ms=(st.last.gap_leader_ms if st.last is not None else c.gap_leader_ms),
                    compound_before=(st.last.tyre_visual if st.last is not None else c.tyre_visual),
                )
                opened.append(v)
            if v is not None and c.pit_status:
                if c.pit_lane_time_ms is not None:
                    v.lane_time_ms = max(v.lane_time_ms or 0, c.pit_lane_time_ms)
                if c.pit_stop_timer_ms is not None:
                    v.stationary_ms = max(v.stationary_ms or 0, c.pit_stop_timer_ms)
                v.serve_penalty = v.serve_penalty or c.serve_penalty
                if c.tyre_visual is not None:
                    v.compound_after = c.tyre_visual
            elif v is not None and st.pit_status and not c.pit_status:
                v.exit_lap = lap
                v.exit_m = c.lap_distance_m
                v.t_exit = t
                if c.tyre_visual is not None:
                    v.compound_after = c.tyre_visual
                measured = round((t - v.t_entry) * 1000)
                if v.lane_time_ms is None or measured > v.lane_time_ms:
                    v.lane_time_ms = measured
                st.visit = None
                self.visits.append(v)
                self._changed.append(v)
                self._finalise(st, v)
            st.pit_status = c.pit_status
            st.last = c
        return opened

    def _lap_done(self, idx: int, st: _Car) -> None:
        for v in self.visits:
            if v.car_index == idx and (not v.final or not v.post_done):
                before = (v.final, v.post_done, v.pace_after_ms)
                self._finalise(st, v)
                if (v.final, v.post_done, v.pace_after_ms) != before:
                    self._changed.append(v)

    def _green(self, st: _Car, lap: int) -> bool:
        return lap in st.times and lap != 1 and lap not in st.pitted and lap not in st.neutral

    def _finalise(self, st: _Car, v: PitVisit) -> None:
        """Work out the loss once lap X is complete; the post-stop pace as laps X+1..X+3 come in."""
        x = v.exit_lap
        if x is None:
            return
        if not v.final:
            if v.rewound:
                v.excluded = v.excluded or EXCLUDED_FLASHBACK
                v.final = True
            elif x not in st.times:
                if st.lap is not None and st.lap > x + 1:
                    v.excluded = v.excluded or EXCLUDED_LAPS_MISSING
                    v.final = True
                else:
                    return  # lap X still running
            elif not self._loss(st, v):
                return  # neutralised: waiting for the field's laps to compare with
            else:
                v.final = True
        if v.final and not v.post_done:
            post = [st.times[k] for k in range(x + 1, x + 1 + POST_LAPS) if self._green(st, k)]
            if post:
                v.pace_after_ms = round(statistics.median(post))
            if st.lap is not None and st.lap > x + POST_LAPS:
                v.post_done = True

    def _loss(self, st: _Car, v: PitVisit) -> bool:
        """Work out the loss (or the exclusion); False while a neutralised stop waits for the field's lap X (the cars
        behind finish it after this one), at most until this car finishes lap X + 1."""
        e, x = v.entry_lap, v.exit_lap
        assert x is not None
        laps = list(range(e, x + 1))
        if any(k not in st.times for k in laps):
            v.excluded = v.excluded or EXCLUDED_LAPS_MISSING
            return True
        v.laps_ms = [st.times[k] for k in laps]
        worst = max((st.neutral.get(k) for k in laps), key=lambda s: _SEVERITY.get(s, 0), default=None)
        pre = [st.times[k] for k in range(e - 1, 0, -1) if self._green(st, k)][:PRE_LAPS]
        if pre:
            v.pace_before_ms = round(statistics.median(pre))
        if worst in NEUTRAL:
            v.neutralised = worst
            ref = self._field_reference(laps, v.car_index)
            if ref is None and st.lap is not None and st.lap <= x + 1:
                return False
            if ref is not None:
                v.pit_loss_ms = sum(v.laps_ms) - ref
        elif v.pace_before_ms is not None:
            v.pit_loss_ms = sum(v.laps_ms) - len(laps) * v.pace_before_ms
        partly = v.neutralised is not None and any(st.neutral.get(k) not in NEUTRAL for k in laps)
        if v.stationary_ms is not None and v.stationary_ms > STATIONARY_MAX_MS:
            v.excluded = v.excluded or EXCLUDED_LONG_STOP
        elif partly:
            v.excluded = v.excluded or EXCLUDED_PARTLY_NEUTRAL
        elif v.serve_penalty:
            v.excluded = v.excluded or EXCLUDED_PENALTY
        elif v.neutralised is None and v.pace_before_ms is None:
            v.excluded = v.excluded or EXCLUDED_NO_PRE_LAP
        elif v.pit_loss_ms is None:
            v.excluded = v.excluded or EXCLUDED_LAPS_MISSING
        elif v.neutralised is None and not (LOSS_MIN_MS <= v.pit_loss_ms <= LOSS_MAX_MS):
            v.excluded = v.excluded or EXCLUDED_IMPLAUSIBLE
        return True

    def _field_reference(self, laps: list[int], idx: int) -> int | None:
        """Sum over ``laps`` of the median lap time of the other cars that did not pit on that lap."""
        total = 0
        for k in laps:
            vals = [s.times[k] for i, s in self.cars.items() if i != idx and k in s.times and k not in s.pitted]
            if not vals:
                return None
            total += round(statistics.median(vals))
        return total

    def rewind(self, t: float) -> None:
        """A flashback to session time ``t``: visits that started after it are dropped (they are driven again), one
        that it cuts into is marked (``EXCLUDED_FLASHBACK`` once finalised). A stop the car had already left the pit
        lane from, with ``t`` before that exit, is re-opened: the car is back in the lane, and the next tick must not
        take that for a new pit entry (a one-lap "stop" on the out-lap, with the out-lap's distance as its entry)."""
        for st in self.cars.values():
            v = st.visit
            if v is not None and v.t_entry > t:
                st.visit = None
            elif v is not None:
                v.rewound = True
            st.pit_status = 0 if st.visit is None else st.pit_status
        keep: list[PitVisit] = []
        for v in self.visits:
            if v.t_entry > t:
                continue  # driven again after the rewind
            car = self.cars.get(v.car_index)
            if v.t_exit is not None and t < v.t_exit and car is not None and car.visit is None:
                v.exit_lap = v.exit_m = v.t_exit = None
                v.laps_ms = []
                v.pit_loss_ms = v.pace_after_ms = None
                v.rewound = True
                v.final = v.post_done = False
                car.visit, car.pit_status = v, 1
                continue
            if not v.final and v.t_entry <= t <= (v.t_exit or t) + 1e-6:
                v.rewound = True
            keep.append(v)
        self.visits = keep

    def end_session(self) -> list[PitVisit]:
        """Stops whose loss could not be worked out before the session ended are written as excluded."""
        out: list[PitVisit] = []
        for st in self.cars.values():
            v = st.visit
            if v is not None:
                v.excluded = v.excluded or EXCLUDED_NOT_COMPLETED
                v.final = v.post_done = True
                self.visits.append(v)
                st.visit = None
                out.append(v)
        for v in self.visits:
            if not v.final:
                v.excluded = v.excluded or EXCLUDED_NOT_COMPLETED
                v.final = True
                out.append(v)
            v.post_done = True
        self._changed.extend(out)
        return out

    def take_changed(self) -> list[PitVisit]:
        seen: set[int] = set()
        out = [v for v in self._changed if not (id(v) in seen or seen.add(id(v)))]  # type: ignore[func-returns-value]
        self._changed = []
        return out

    # ------------------------------------------------------------------ output
    def in_lane(self, idx: int) -> PitVisit | None:
        st = self.cars.get(idx)
        return None if st is None else st.visit

    def green_loss(self) -> dict[str, Any] | None:
        """Median and range (s) of the stops measured under green: ``{"median_s", "range", "n"}``, or None."""
        vals = [v.pit_loss_ms for v in self.visits if v.final and not v.excluded and not v.neutralised]
        losses = [x for x in vals if x is not None]
        if not losses:
            return None
        return {
            "median_s": round(statistics.median(losses) / 1000, 1),
            "range": {"low": round(min(losses) / 1000, 1), "high": round(max(losses) / 1000, 1)},
            "n": len(losses),
        }

    def neutral_loss(self) -> dict[str, Any]:
        """Pit loss under a full safety car / VSC: measured neutralised stops of that kind if any, else the green loss
        times ``SC_LOSS_FACTOR`` (heuristic), else unknown. ``{"full_s", "virtual_s", "tier"}``; the tier is
        ``measured`` only when every value given is measured."""
        out: dict[str, Any] = {"full_s": None, "virtual_s": None, "tier": "measured"}
        green = self.green_loss()
        for kind, key in (("full", "full_s"), ("virtual", "virtual_s")):
            vals = [
                v.pit_loss_ms
                for v in self.visits
                if v.final and not v.excluded and v.neutralised == kind and v.pit_loss_ms is not None
            ]
            if vals:
                out[key] = round(statistics.median(vals) / 1000, 1)
            elif green is not None:
                out[key] = round(green["median_s"] * SC_LOSS_FACTOR[kind], 1)
                out["tier"] = "heuristic"
        if out["full_s"] is None and out["virtual_s"] is None:
            out["tier"] = "heuristic"
        return out

    def measured_gains(self) -> list[float]:
        """Fresh-tyre gains (s per lap) the field's stops measured: pre-stop pace minus post-stop pace."""
        return [
            (v.pace_before_ms - v.pace_after_ms) / 1000
            for v in self.visits
            if v.final and not v.excluded and v.pace_before_ms is not None and v.pace_after_ms is not None
        ]

    def pit_entry_m(self) -> float | None:
        vals = [v.entry_m for v in self.visits if v.entry_m is not None and v.entry_m > 0]
        return round(statistics.median(vals), 1) if vals else None

    def pit_exit_m(self) -> float | None:
        vals = [v.exit_m for v in self.visits if v.exit_m is not None and v.exit_m >= 0]
        return round(statistics.median(vals), 1) if vals else None

    def player_stops(self) -> list[PitVisit]:
        return [v for v in self.visits if v.is_player]
