"""Lock-ups and wheelspin per lap, from the wheel slip ratio (F1 MotionEx), with the technique module's thresholds.

Per frame with a slip ratio (``technique.thresholds``, never copies):

* **lock-up**: any wheel at or under ``LOCKUP_SLIP`` with the brake at ``TRAIL_BRAKE_MIN`` or more for at least
  ``LOCKUP_MIN_S``, counted only while the frame says ABS is off (``abs_active is False``). With ABS on, lock-ups are
  "not applicable". Recorded: F2 Bahrain on PS5 with ABS off had 50 lock-ups in 9 laps (slip -1.0, fully locked);
  with ABS on, 9 slip events in 116 laps (spins), so they are not counted then.
* **wheelspin**: a rear wheel at or over ``SPIN_SLIP`` with the throttle at ``SPIN_THROTTLE`` or more for at least
  ``SPIN_MIN_S``. Each event keeps the traction-control level of its first frame: with full traction control
  (``TC_FULL``) the counts are shown, never spoken (recorded: a median of 1 a lap with TC full, 5 with TC medium).
  The frame's own level is used: the game reports TC 0 in the pit lane. The level is kept only from an F1 game
  (``technique.inputs.tc_scale_is_f1``): another game's TC is a scale of its own (ACC's level runs to about 11), so it
  stays unknown here and its wheelspin is shown, never spoken.

Unlike ``technique.inputs`` (corner exits only), this is the whole lap. Each event is attributed to the learned corner
segment it started in (``seg_start_m``..``seg_end_m``). A flashback drops the lap's counts. Frames slower than
``RACING_MIN_KPH``, in the pit lane, paused or out of the race end a run; each frame counts the time since the
previous one, at most ``SLIP_MAX_DT_S`` (the same rules as the recorded survey these counts were checked against).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pitwall.carhealth import thresholds as T
from pitwall.carhealth.tyres import racing
from pitwall.model.telemetry import CarFrame
from pitwall.technique.inputs import tc_scale_is_f1
from pitwall.technique.thresholds import (
    LOCKUP_MIN_S,
    LOCKUP_SLIP,
    SPIN_MIN_S,
    SPIN_SLIP,
    SPIN_THROTTLE,
    TRAIL_BRAKE_MIN,
)

WHEELS = ("FL", "FR", "RL", "RR")
CornerOf = Callable[[float | None], tuple[str, str] | None]  # lap distance -> (learned name, display text)


@dataclass(slots=True)
class SlipEvent:
    kind: str  # "lockup" | "wheelspin"
    start_m: float | None
    duration_s: float
    wheels: tuple[str, ...]
    tc: int | None
    corner: tuple[str, str] | None

    @property
    def speakable(self) -> bool:
        """Wheelspin is spoken only with traction control off or medium; lock-ups always (ABS was off)."""
        return self.kind == "lockup" or (self.tc is not None and self.tc < T.TC_FULL)


@dataclass(slots=True)
class _Run:
    kind: str
    start_m: float | None
    tc: int | None
    duration: float = 0.0
    wheels: set[str] = field(default_factory=set)


class SlipCounter:
    def __init__(self, corner_of: CornerOf | None = None) -> None:
        self.corner_of = corner_of
        self.seen = False  # a frame carried a slip ratio
        self.abs_on: bool | None = None  # the latest on-track frame's ABS setting
        self.tc: int | None = None  # the latest on-track frame's traction control (F1's scale; None for other games)
        self.lap: int | None = None
        self._events: list[SlipEvent] = []  # the lap in progress
        self._runs: dict[str, _Run | None] = {"lockup": None, "wheelspin": None}
        self._prev_t: float | None = None
        self._pit_lap = False
        self._flashback_lap = False
        self.last_lap: dict[str, Any] | None = None
        self.last_events: list[SlipEvent] = []
        self.session_laps = 0
        self.session_lockups = 0
        self.session_wheelspin = 0

    def on_frame(self, f: CarFrame) -> None:
        if f.lap_number is not None and self.lap is None:
            self.lap = f.lap_number
        if f.pit_status:
            self._pit_lap = True
        t = f.session_time_s
        s = f.wheel_slip_ratio
        if s is None or t is None:
            self._close_all()
            self._prev_t = None
            return
        self.seen = True
        prev, self._prev_t = self._prev_t, t
        if not racing(f):
            self._close_all()
            return
        if f.abs_active is not None:
            self.abs_on = f.abs_active
        tc = f.traction_control if tc_scale_is_f1(f.game) else None  # another game's level is not F1's 0-2
        if tc is not None:
            self.tc = tc
        if prev is not None and t < prev:
            self._close_all()  # the clock went back
        dt = 0.0 if prev is None else min(T.SLIP_MAX_DT_S, max(0.0, t - prev))
        w = s.as_tuple()
        if any(not math.isfinite(x) for x in w):
            return
        brake, throttle = f.brake or 0.0, f.throttle or 0.0
        locked = [WHEELS[k] for k in range(4) if w[k] <= LOCKUP_SLIP] if brake >= TRAIL_BRAKE_MIN else []
        if locked and f.abs_active is False:
            self._extend("lockup", locked, dt, f)
        else:
            self._close("lockup")
        spinning = [WHEELS[k] for k in (2, 3) if w[k] >= SPIN_SLIP] if throttle >= SPIN_THROTTLE else []
        if spinning:
            self._extend("wheelspin", spinning, dt, f)
        else:
            self._close("wheelspin")

    def _extend(self, kind: str, wheels: list[str], dt: float, f: CarFrame) -> None:
        run = self._runs[kind]
        if run is None:
            tc = f.traction_control if tc_scale_is_f1(f.game) else None
            run = self._runs[kind] = _Run(kind, f.lap_distance_m, tc)
        run.duration += dt
        run.wheels.update(wheels)

    def _close(self, kind: str) -> None:
        run = self._runs[kind]
        self._runs[kind] = None
        if run is None:
            return
        need = LOCKUP_MIN_S if kind == "lockup" else SPIN_MIN_S
        if run.duration + 1e-9 < need:
            return
        corner = self.corner_of(run.start_m) if self.corner_of is not None else None
        wheels = tuple(w for w in WHEELS if w in run.wheels)
        self._events.append(SlipEvent(kind, run.start_m, run.duration, wheels, run.tc, corner))

    def _close_all(self) -> None:
        self._close("lockup")
        self._close("wheelspin")

    def rewind(self) -> None:
        """A flashback: the lap's counts are dropped (it is driven again)."""
        self._runs = {"lockup": None, "wheelspin": None}
        self._events = []
        self._flashback_lap = True
        self._prev_t = None

    def on_line(self, finished_lap: int, new_lap: int) -> dict[str, Any] | None:
        """The line: the finished lap's summary (``last_lap``), or None when nothing was measured in it."""
        self._close_all()
        events, self._events = self._events, []
        pit, flashback = self._pit_lap, self._flashback_lap
        self._pit_lap = self._flashback_lap = False
        self.lap = new_lap
        if not self.seen:
            return None
        lockups = [e for e in events if e.kind == "lockup"]
        spins = [e for e in events if e.kind == "wheelspin"]
        corners: dict[str, dict[str, Any]] = {}
        for e in events:
            if e.corner is None:
                continue
            c = corners.setdefault(
                e.corner[0], {"corner": e.corner[0], "text": e.corner[1], "lockups": 0, "wheelspin": 0}
            )
            c["lockups" if e.kind == "lockup" else "wheelspin"] += 1
        self.session_laps += 1
        self.session_lockups += len(lockups)
        self.session_wheelspin += len(spins)
        self.last_events = events
        self.last_lap = {
            "lap": finished_lap,
            "lockups": len(lockups),
            "lockup_s": round(sum(e.duration_s for e in lockups), 2),
            "wheelspin": len(spins),
            "wheelspin_s": round(sum(e.duration_s for e in spins), 2),
            "wheelspin_spoken": sum(1 for e in spins if e.speakable),
            "corners": sorted(corners.values(), key=lambda c: -(c["lockups"] + c["wheelspin"])),
            "pit": pit,
            "flashback": flashback,
        }
        return self.last_lap

    def current(self) -> dict[str, Any]:
        return {
            "lap": self.lap,
            "lockups": sum(1 for e in self._events if e.kind == "lockup"),
            "wheelspin": sum(1 for e in self._events if e.kind == "wheelspin"),
        }

    @staticmethod
    def top_corner(events: list[SlipEvent], kind: str, spoken_only: bool = False) -> tuple[str, str, int] | None:
        """The corner with the most events of ``kind``: (learned name, text, count), or None."""
        counts: dict[tuple[str, str], int] = {}
        for e in events:
            if e.kind != kind or e.corner is None or (spoken_only and not e.speakable):
                continue
            counts[e.corner] = counts.get(e.corner, 0) + 1
        if not counts:
            return None
        (name, text), n = max(counts.items(), key=lambda kv: kv[1])
        return name, text, n
