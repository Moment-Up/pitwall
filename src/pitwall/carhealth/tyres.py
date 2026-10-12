"""Tyre temperatures against the driver's own warm laps, pressures and wear (``CarHealthView.tyres``).

**Temperature model.** F1 sends a surface and an inner (carcass) temperature per tyre, but when the session's tyre
model is "surface only" (``SessionInfo.extra["tyre_temperature_model"] == "surface"``) the inner value is a constant
per compound (80 C medium and soft, 85 C hard, flat for a whole 32-lap race on PS5) and the pressures are fixed. So
the carcass is used only when the session simulates it; otherwise (and while the setting is not known yet, the first
~1.5 s) the surface. GT7 and Forza send one temperature per tyre (surface). Assetto Corsa sends none.

**Baselines.** Racing frames only (faster than ``RACING_MIN_KPH``, not in the pit lane, not paused / spectating / out of
the race / a rewound segment). Per wheel, a 1 C histogram per lap (its median at the line) and one per stint from
``STINT_SKIP_S`` into it: its median is the stint baseline once it holds ``BASE_MIN_S`` of racing time. A stint starts
with the session and at every pit exit; at a pit entry the stint's baseline is kept as the *warm baseline*. While the
cold-tyre rule is armed nothing is added (after a stop the new stint's clock starts when the rule is done), so the
warm-up laps never make a cold baseline that would show warm tyres as "hot".

**Bands** (display and answers): each wheel's rolling median over ``WINDOW_S`` against the baseline in use - the
cold-tyre rule's baseline while it is armed, else the current stint's, else the warm one - ``cold`` at
``COLD_DROP`` under it, ``hot`` at ``HOT_RISE`` over it (display only, unvalidated), else ``ok``; ``unknown`` without a
baseline. There is no fixed window: no game publishes one (real F1 25 surface lap medians are under 75 C on 93 % of
500 wheel-laps; GT7 runs 37-196 C).

**Cold tyres** (the one proactive temperature rule; F1 only - GT7 and Forza send no pit state): the index is the mean
of the four wheels, as a rolling median, judged once a second. It is *armed* at a pit exit when there is a warm
baseline, and when a safety car or VSC ends (against the current stint's baseline). Armed and the index at or under
baseline - ``COLD_DROP``: ``cold`` (call ``tyres_cold`` once per arm); cold and back within ``WARM_DROP``: ``ok`` (call
``tyres_warm`` once). Armed but already within ``WARM_DROP`` (tyre blankets): disarmed with no call. The rule disarms
``ARM_MAX_LAPS`` laps after the arm. The first judgement after an arm needs only ``ARM_FIRST_SPAN_S`` of racing time
(carcass: new tyres leave 55-59 C under the warm laps, so the call comes before the first corners). Without a warm
baseline (the first stint, a session joined mid-race) it never arms.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from pitwall.carhealth import thresholds as T
from pitwall.carhealth.stats import Hist, Window
from pitwall.model.telemetry import CarFrame, FrameQuality

WHEELS = ("FL", "FR", "RL", "RR")
MODEL_CARCASS = "carcass"
MODEL_SURFACE = "surface"
BAD_QUALITY = (
    FrameQuality.PAUSED | FrameQuality.REPLAY_OR_SPECTATING | FrameQuality.NOT_RACING | FrameQuality.FLASHBACK_SEGMENT
)
REASON_PIT_EXIT = "pit_exit"
REASON_SC_END = "sc_end"
MAX_DT_S = 0.5  # a longer gap between two racing frames counts no racing time


def racing(f: CarFrame) -> bool:
    """A frame of the car racing on track (speed, pit lane, quality)."""
    return (
        f.speed_kph is not None
        and f.speed_kph > T.RACING_MIN_KPH
        and f.pit_status in (None, 0)
        and not (f.quality & BAD_QUALITY)
    )


@dataclass(slots=True)
class TyreEvent:
    """A cold-tyre transition for the call planner: ``tyres_cold`` / ``tyres_warm``."""

    topic: str
    reason: str  # REASON_PIT_EXIT / REASON_SC_END
    lap: int | None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class _Arm:
    reason: str
    lap: int | None
    base_index: float
    base_wheels: tuple[float | None, ...]
    cold: bool = False


@dataclass(slots=True)
class _Stint:
    t0: float | None = None
    wheels: list[Hist] = field(default_factory=lambda: [Hist() for _ in WHEELS])
    index: Hist = field(default_factory=Hist)

    def baseline(self) -> tuple[float | None, tuple[float | None, ...]] | None:
        if self.index.seconds < T.BASE_MIN_S:
            return None
        return self.index.median(), tuple(h.median() for h in self.wheels)


class TyreTempMonitor:
    """One session's tyre temperatures. Not thread-safe (the car health worker owns it)."""

    def __init__(self) -> None:
        self.model: str | None = None  # MODEL_CARCASS / MODEL_SURFACE once a frame carried temperatures
        self.seen_frame = False
        self.lap: int | None = None
        self.compound: str | None = None
        self.age_laps: int | None = None
        self._stint = _Stint()
        self._warm: tuple[float | None, tuple[float | None, ...]] | None = None  # frozen at the last pit entry
        self._lap_hist = [Hist() for _ in WHEELS]
        self.last_lap_median: tuple[float | None, ...] = (None,) * 4
        self._windows: list[Window] = []
        self._index_win = Window(T.WINDOW_S[MODEL_SURFACE], T.WINDOW_SAMPLE_S)
        self._set_windows(MODEL_SURFACE)
        self._arm: _Arm | None = None
        self.state = "unknown"
        self.since: dict[str, Any] | None = None
        self.index_c: float | None = None
        self._last_eval = -math.inf
        self._prev_pit: int | None = None
        self._prev_t: float | None = None
        self._prev_racing_t: float | None = None
        self.pressure_now: tuple[float, ...] | None = None
        self._lap_pressure = [Hist(0.1) for _ in WHEELS]
        self.last_lap_pressure: tuple[float | None, ...] = (None,) * 4
        self.wear_now: tuple[float, ...] | None = None
        self.events: list[TyreEvent] = []

    # ------------------------------------------------------------------ inputs
    def _set_windows(self, model: str) -> None:
        span = T.WINDOW_S[model]
        self._windows = [Window(span, T.WINDOW_SAMPLE_S) for _ in WHEELS]
        self._index_win = Window(span, T.WINDOW_SAMPLE_S)

    def set_model(self, model: str) -> None:
        """The session's temperature model (F1 tyre setting; surface for GT7 / Forza). A change starts over: the two
        models' temperatures are not comparable."""
        if model == self.model:
            return
        self.model = model
        self._stint = _Stint(t0=self._stint.t0)
        self._warm = None
        self._arm = None
        self.state, self.since = "unknown", None
        self._lap_hist = [Hist() for _ in WHEELS]
        self._set_windows(model)

    def on_frame(self, f: CarFrame, model: str | None) -> None:
        self.seen_frame = True
        t = f.session_time_s
        if t is None:
            return
        if f.tyre_compound is not None:
            self.compound = f.tyre_compound
        if f.tyre_age_laps is not None:
            self.age_laps = f.tyre_age_laps
        if f.tyre_pressure_psi is not None:
            self.pressure_now = f.tyre_pressure_psi.as_tuple()
        if f.tyre_wear_pct is not None:
            self.wear_now = f.tyre_wear_pct.as_tuple()
        if f.lap_number is not None:
            self.lap = f.lap_number
        pit = f.pit_status
        if pit is not None and self._prev_pit is not None:
            if not self._prev_pit and pit:
                self._pit_entry()
            elif self._prev_pit and not pit:
                self._pit_exit(t)
        if pit is not None:
            self._prev_pit = pit
        if self._stint.t0 is None:
            self._stint.t0 = t
        self._prev_t = t
        if model is None or f.tyre_surface_temp_c is None:
            return
        self.set_model(model)
        temps = f.tyre_inner_temp_c if model == MODEL_CARCASS else f.tyre_surface_temp_c
        if temps is None or not racing(f):
            self._prev_racing_t = None
            return
        prev = self._prev_racing_t
        dt = 0.0 if prev is None or not 0.0 < t - prev <= MAX_DT_S else t - prev
        self._prev_racing_t = t
        vals = temps.as_tuple()
        index = sum(vals) / 4.0
        for k, v in enumerate(vals):
            self._lap_hist[k].add(v)
            self._windows[k].add(t, v)
        if f.tyre_pressure_psi is not None:
            for k, p in enumerate(f.tyre_pressure_psi.as_tuple()):
                self._lap_pressure[k].add(p)
        self._index_win.add(t, index)
        t0 = self._stint.t0 if self._stint.t0 is not None else t
        if self._arm is None and t - t0 >= T.STINT_SKIP_S:  # never the warm-up after a stop / restart
            for k, v in enumerate(vals):
                self._stint.wheels[k].add(v, dt)
            self._stint.index.add(index, dt)
        if t - self._last_eval >= T.EVAL_EVERY_S:
            self._last_eval = t
            self._evaluate(t)

    def on_line(self, new_lap: int) -> None:
        """The player crossed the line into ``new_lap``: the finished lap's medians; the arm's lap limit."""
        self.last_lap_median = tuple(h.median() for h in self._lap_hist)
        self.last_lap_pressure = tuple(h.median() for h in self._lap_pressure)
        for h in (*self._lap_hist, *self._lap_pressure):
            h.clear()
        self.lap = new_lap
        arm = self._arm
        if arm is not None and arm.lap is not None and new_lap > arm.lap + T.ARM_MAX_LAPS:
            self._disarm(self._prev_t)
            if arm.cold:
                self.state = "ok"
                self.since = {"lap": new_lap, "reason": "timeout"}

    def on_safety_car_end(self) -> None:
        """A safety car / VSC came in: armed against the current stint's baseline (else the warm one)."""
        base = self._stint.baseline() or self._warm
        if base is not None and base[0] is not None:
            self._arm = _Arm(REASON_SC_END, self.lap, base[0], base[1])
            self._index_win.clear()
            for w in self._windows:
                w.clear()

    def rewind(self) -> None:
        """A flashback: the lap in progress and the windows hold rewound data."""
        for h in (*self._lap_hist, *self._lap_pressure):
            h.clear()
        for w in (*self._windows, self._index_win):
            w.clear()
        self._prev_racing_t = None
        self._last_eval = -math.inf

    # ------------------------------------------------------------------ stints
    def _pit_entry(self) -> None:
        base = self._stint.baseline()
        if base is not None and base[0] is not None:
            self._warm = base

    def _pit_exit(self, t: float) -> None:
        self._stint = _Stint(t0=t)
        for w in (*self._windows, self._index_win):
            w.clear()
        self._prev_racing_t = None
        warm = self._warm
        if warm is not None and warm[0] is not None:
            self._arm = _Arm(REASON_PIT_EXIT, self.lap, warm[0], warm[1])
        else:
            self._arm = None

    # ------------------------------------------------------------------ cold-tyre rule
    def _disarm(self, t: float | None) -> None:
        """The rule is done. After a pit exit the new stint's baseline starts now (``STINT_SKIP_S`` from here): its
        warm-up laps never count, or the baseline would be cold and warm tyres would read "hot"."""
        arm, self._arm = self._arm, None
        if arm is not None and arm.reason == REASON_PIT_EXIT and t is not None:
            self._stint.t0 = t

    def _evaluate(self, t: float) -> None:
        model = self.model or MODEL_SURFACE
        self.index_c = self._index_win.median()
        arm = self._arm
        if arm is None:
            if self.state != "cold":
                self.state = "ok" if self.baseline_index() is not None else "unknown"
            return
        span = self._index_win.spanned()
        need = T.WINDOW_SPAN_FRAC * T.WINDOW_S[model]
        if not arm.cold:
            need = min(need, T.ARM_FIRST_SPAN_S.get(model, need))
        med = self.index_c
        if med is None or span < need:
            return
        cold, warm = T.COLD_DROP_C[model], T.WARM_DROP_C[model]
        data = {"index_c": round(med, 1), "baseline_c": round(arm.base_index, 1), "model": model}
        if not arm.cold:
            if med <= arm.base_index - cold:
                arm.cold = True
                self.state = "cold"
                self.since = {"lap": self.lap, "reason": arm.reason}
                self.events.append(TyreEvent("tyres_cold", arm.reason, self.lap, data))
            elif med >= arm.base_index - warm:
                self._disarm(t)  # warm already (tyre blankets): nothing to say
                self.state = "ok"
        elif med >= arm.base_index - warm:
            self._disarm(t)
            self.state = "ok"
            self.since = {"lap": self.lap, "reason": "warm"}
            self.events.append(TyreEvent("tyres_warm", arm.reason, self.lap, data))

    # ------------------------------------------------------------------ outputs
    def take_events(self) -> list[TyreEvent]:
        out, self.events = self.events, []
        return out

    @property
    def armed(self) -> bool:
        return self._arm is not None

    def baseline_index(self) -> float | None:
        arm = self._arm
        if arm is not None:
            return arm.base_index
        base = self._stint.baseline() or self._warm
        return None if base is None else base[0]

    def baseline_source(self) -> str | None:
        if self._arm is not None:
            return "previous_stint" if self._arm.reason == REASON_PIT_EXIT else "this_stint"
        if self._stint.baseline() is not None:
            return "this_stint"
        return "previous_stint" if self._warm is not None else None

    def wheel_baselines(self) -> tuple[float | None, ...]:
        arm = self._arm
        if arm is not None:
            return arm.base_wheels
        base = self._stint.baseline() or self._warm
        return (None,) * 4 if base is None else base[1]

    def bands(self) -> list[dict[str, Any]]:
        model = self.model or MODEL_SURFACE
        bases = self.wheel_baselines()
        out = []
        for k, name in enumerate(WHEELS):
            now = self._windows[k].median() if self._windows else None
            base = bases[k] if k < len(bases) else None
            if base is None or now is None:
                band = "unknown"
            elif now <= base - T.COLD_DROP_C[model]:
                band = "cold"
            elif now >= base + T.HOT_RISE_C[model]:
                band = "hot"
            else:
                band = "ok"
            out.append(
                {
                    "wheel": name,
                    "band": band,
                    "window_c": now,
                    "lap_median_c": self.last_lap_median[k],
                    "baseline_c": base,
                }
            )
        return out
