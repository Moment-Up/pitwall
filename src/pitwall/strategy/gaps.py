"""Gaps to the cars ahead and behind, from the game's own deltas (F1 LapData), with a settle rule and trends.

Real F1 25 (PS5) gaps update stepwise every 0.3-2 s and have three glitches the settle rule exists for:

* after a position change the *old* gap is reported for about 2 s (Monza excerpt: the real value is back 3.4 s
  after the change);
* a negative delta wraps into the uint16 milliseconds part (Monza: 65403 = -133 ms; the adapter makes it ``None``);
* values are wrong while an adjacent car is in the pit lane (Austria lap 62: 19.1 s).

So a sample is *settled* only when, for ``SETTLE_S`` [R], the player's position, the adjacent car and that car's pit
status have not changed, neither the player nor that car is in the pit lane, and the value is known. Unsettled
samples are never published as new: the view keeps the last settled value of the same car with ``settled: false``
(a different car's old gap is never shown against the new car).

Per lap, the *line gap* is the median of the settled samples in the first ``LINE_WINDOW_S`` [H] of the next lap; a
lap on which either car pitted or a safety car / VSC ran is neutralised. The trend is the least-squares slope over
the last <= ``TREND_MAX_LAPS`` non-neutralised line gaps to the same car (at least ``TREND_MIN_LAPS`` [H]).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from pitwall.model.telemetry import CarTiming, RaceTiming

SETTLE_S = 4.0  # [R] Monza excerpt: the real gap is back 3.4 s after a position change
SETTLE_EPS_S = 1e-3  # float32 session clock: 4.0 s apart may read 3.9999 s
LINE_WINDOW_S = 5.0  # [H]
WITHIN_ENTER_S = 1.0  # [H] the "within a second" rule, entered on WITHIN_TICKS consecutive settled samples ...
WITHIN_EXIT_S = 1.2  # ... and left above this (hysteresis)
WITHIN_TICKS = 2
TREND_MIN_LAPS = 3  # [H]
TREND_MAX_LAPS = 5
CLOSING_MIN_S_PER_LAP = 0.05  # [H] slower closing than this gives no "laps to within a second"
RACING = frozenset({"active", "finished"})


@dataclass(slots=True)
class LineGap:
    lap: int
    car_index: int | None
    gap_s: float | None
    neutralised: bool
    t_s: float  # session time it was taken (end of the line window)


@dataclass(slots=True)
class Side:
    """One neighbour (the car ahead or behind) as last seen."""

    name: str  # "ahead" | "behind"
    car_index: int | None = None
    car: CarTiming | None = None
    last_change_t: float = -1e9
    pit_status: int | None = None
    value_s: float | None = None  # last settled gap to ``car_index``
    settled: bool = False
    within: bool | None = None
    within_count: int = 0
    lines: list[LineGap] = field(default_factory=list)


@dataclass(slots=True)
class GapEvent:
    kind: str  # "within" (entered within a second) | "pit_entry" (the neighbour entered the pit lane) | "line"
    side: str
    car_index: int | None
    lap: int | None = None


class GapTracker:
    """Feed every ``RaceTiming`` (``update``); read ``ahead`` / ``behind`` / ``leader_s``. Not thread-safe (the
    strategy worker owns it)."""

    def __init__(self) -> None:
        self.ahead = Side("ahead")
        self.behind = Side("behind")
        self.player: CarTiming | None = None
        self.leader_s: float | None = None
        self.leader_change_t = -1e9
        self._pos: int | None = None
        self._lap: int | None = None
        self._window_lap: int | None = None  # the lap whose line gap is being taken
        self._window_start: float | None = None
        self._window: dict[str, list[tuple[int | None, float]]] = {"ahead": [], "behind": []}
        self._pitted: dict[int, set[int]] = {}  # player lap -> car indices seen in the pit lane during it
        self._neutral_laps: set[int] = set()

    # ------------------------------------------------------------------ input
    def mark_neutral_lap(self, lap: int) -> None:
        """A safety car / VSC ran during ``lap``: its line gaps are neutralised."""
        self._neutral_laps.add(lap)

    def update(self, timing: RaceTiming) -> list[GapEvent]:
        events: list[GapEvent] = []
        me = next((c for c in timing.cars if c.is_player), None)
        if me is None:
            return events
        t = timing.session_time_s
        self.player = me
        by_pos = {c.position: c for c in timing.cars if c.result_status in RACING and not c.is_player}
        if me.position != self._pos:
            self._pos = me.position
            self.ahead.last_change_t = self.behind.last_change_t = self.leader_change_t = t
        lap = me.lap_number
        events.extend(self._lap_change(lap, t))
        pitted = self._pitted.setdefault(lap, set())
        if me.pit_status:
            pitted.add(me.car_index)
        ahead, behind = by_pos.get(me.position - 1), by_pos.get(me.position + 1)
        events.extend(self._update_side(self.ahead, ahead, me.gap_ahead_ms, me, t, pitted))
        events.extend(
            self._update_side(self.behind, behind, None if behind is None else behind.gap_ahead_ms, me, t, pitted)
        )
        # leader gap: same settle rule on the player's own position
        if me.position == 1:
            self.leader_s = None
        elif me.gap_leader_ms is not None and not me.pit_status and t - self.leader_change_t >= SETTLE_S - SETTLE_EPS_S:
            self.leader_s = me.gap_leader_ms / 1000.0
        if self._window_start is not None and t - self._window_start > LINE_WINDOW_S:
            events.extend(self._close_window(t))
        return events

    def _update_side(
        self, side: Side, car: CarTiming | None, raw_ms: int | None, me: CarTiming, t: float, pitted: set[int]
    ) -> list[GapEvent]:
        events: list[GapEvent] = []
        idx = None if car is None else car.car_index
        if idx != side.car_index:
            side.car_index = idx
            side.last_change_t = t
            side.value_s = None
            side.within = None
            side.within_count = 0
            side.pit_status = None if car is None else car.pit_status
        elif car is not None and car.pit_status != side.pit_status:
            if not side.pit_status and car.pit_status:
                events.append(GapEvent("pit_entry", side.name, idx, me.lap_number))
            side.pit_status = car.pit_status
            side.last_change_t = t
        side.car = car
        if car is None:
            side.settled = False
            return events
        if car.pit_status:
            pitted.add(car.car_index)
        settled = (
            raw_ms is not None
            and not car.pit_status
            and not me.pit_status
            and t - side.last_change_t >= SETTLE_S - SETTLE_EPS_S
        )
        side.settled = settled
        if not settled or raw_ms is None:
            return events
        v = raw_ms / 1000.0
        side.value_s = v
        if self._window_start is not None and t - self._window_start <= LINE_WINDOW_S:
            self._window[side.name].append((idx, v))
        # within a second: enter on WITHIN_TICKS consecutive settled samples <= 1.0 s, leave above 1.2 s
        if v <= WITHIN_ENTER_S:
            side.within_count += 1
            if side.within_count >= WITHIN_TICKS and not side.within:
                side.within = True
                events.append(GapEvent("within", side.name, idx, me.lap_number))
        else:
            side.within_count = 0
            if v > WITHIN_EXIT_S or side.within is None:
                side.within = False
        return events

    def _lap_change(self, lap: int, t: float) -> list[GapEvent]:
        """The player started a new lap: close a window still open and open the line window of the lap just done."""
        events: list[GapEvent] = []
        if self._lap is None:
            self._lap = lap
            return events
        if lap > self._lap:
            events.extend(self._close_window(t))
            self._window_lap = lap - 1
            self._window_start = t
            self._window = {"ahead": [], "behind": []}
            for stale in [k for k in self._pitted if k < lap - 3]:
                del self._pitted[stale]
        elif lap < self._lap:
            self._window_lap = self._window_start = None
        self._lap = lap
        return events

    def _close_window(self, t: float) -> list[GapEvent]:
        lap = self._window_lap
        if lap is None:
            return []
        pitted = self._pitted.get(lap, set())
        events: list[GapEvent] = []
        for side in (self.ahead, self.behind):
            samples = self._window[side.name]
            idx = samples[-1][0] if samples else side.car_index
            vals = [v for i, v in samples if i == idx]
            gap = statistics.median(vals) if vals else None
            neutral = (
                lap in self._neutral_laps
                or (idx is not None and idx in pitted)
                or (self.player is not None and self.player.car_index in pitted)
            )
            side.lines = [g for g in side.lines if g.lap != lap]
            side.lines.append(LineGap(lap=lap, car_index=idx, gap_s=gap, neutralised=neutral, t_s=t))
            del side.lines[:-20]
        self._window_lap = self._window_start = None
        events.append(GapEvent("line", "both", None, lap))
        return events

    def flush(self, t: float) -> list[GapEvent]:
        """The session ended: take the line gap of a window still open from the samples it has."""
        return self._close_window(t) if self._window_start is not None else []

    def rewind(self, t: float) -> None:
        """A flashback to session time ``t``: line gaps and windows taken after it are dropped and both sides are
        unsettled again (the game's deltas take a moment to follow the rewind)."""
        for side in (self.ahead, self.behind):
            side.lines = [g for g in side.lines if g.t_s <= t]
            side.last_change_t = t
            side.within_count = 0
        self.leader_change_t = t
        if self._window_start is not None and self._window_start > t:
            self._window_lap = self._window_start = None
        self._lap = None

    # ------------------------------------------------------------------ output
    def line_gap(self, side: str, lap: int) -> LineGap | None:
        s = self.ahead if side == "ahead" else self.behind
        return next((g for g in reversed(s.lines) if g.lap == lap), None)

    def settled_gap(self, side: Side, lap: int, t: float) -> LineGap | None:
        """The last settled gap of ``side`` as a line gap of ``lap`` (the final lap has no next lap)."""
        if side.car_index is None:
            return None
        return LineGap(
            lap=lap, car_index=side.car_index, gap_s=side.value_s, neutralised=lap in self._neutral_laps, t_s=t
        )

    def trend(self, side: Side) -> tuple[float | None, int]:
        """(slope s/lap, laps used) over the last <= TREND_MAX_LAPS non-neutralised line gaps to the current car;
        slope None with fewer than TREND_MIN_LAPS."""
        pts: list[tuple[int, float]] = []
        for g in reversed(side.lines):
            if g.car_index != side.car_index:
                break
            if g.neutralised or g.gap_s is None:
                continue
            pts.append((g.lap, g.gap_s))
            if len(pts) >= TREND_MAX_LAPS:
                break
        if len(pts) < TREND_MIN_LAPS:
            return None, len(pts)
        x = np.array([p[0] for p in pts], dtype=np.float64)
        y = np.array([p[1] for p in pts], dtype=np.float64)
        if np.ptp(x) == 0:
            return None, len(pts)
        slope = float(np.polyfit(x, y, 1)[0])
        return slope, len(pts)


def laps_to_within(gap_s: float | None, slope: float | None, laps_remaining: float | None) -> float | None:
    """Laps until a closing gap is under a second, when it closes by at least ``CLOSING_MIN_S_PER_LAP`` and gets there
    before the flag."""
    if gap_s is None or slope is None or gap_s <= WITHIN_ENTER_S:
        return None
    closing = -slope
    if closing < CLOSING_MIN_S_PER_LAP:
        return None
    laps = (gap_s - WITHIN_ENTER_S) / closing
    if laps_remaining is not None and laps > laps_remaining:
        return None
    return round(laps, 1)


def car_gap_view(
    tracker: GapTracker, side: Side, laps_remaining: float | None, drs_enabled: bool | None, packet_format: int | None
) -> dict[str, Any] | None:
    """The ``CarGap`` JSON of one side (``StrategyView.gaps.ahead`` / ``behind``)."""
    car = side.car
    if car is None or side.car_index is None:
        return None
    slope, n = tracker.trend(side)
    gap = side.value_s
    drs: bool | None = None
    if packet_format == 2025 and drs_enabled is not None and side.within is not None:
        drs = bool(side.within and drs_enabled)
    tyre = None
    if car.tyre_visual is not None or car.tyre_age_laps is not None:
        tyre = {"compound": car.tyre_visual, "age_laps": car.tyre_age_laps}
    return {
        "car_index": side.car_index,
        "gap_s": None if gap is None else round(gap, 3),
        "settled": side.settled,
        "trend_s_per_lap": None if slope is None else round(slope, 3),
        "trend_laps": n,
        "laps_to_1s": laps_to_within(gap, slope, laps_remaining),
        "within_1s": side.within,
        "drs_range": drs,
        "stops": car.num_pit_stops,
        "in_pit": bool(car.pit_status),
        "tyre": tyre,
    }
