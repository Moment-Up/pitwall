"""The car health engine: one per session, pure and deterministic, driven by the game clock (no I/O, never blocks).

``feed`` takes the session's items in stream order (``CarFrame``, ``LapCompletion``, ``SessionInfo``, ``GameEvent``,
F1 ``RaceTiming`` and, in F1 races, ``FieldSample``). It runs the monitors - tyre temperatures (``tyres``), brakes and
engine (``temps``), lock-ups and wheelspin (``slip``), tank-level fuel (``fuel``), attack / defend (``racecraft``) - and
the call planner (``calls``). ``view`` / ``racecraft_view`` are the live blocks (``carhealth.view``), ``take_calls``
hands out the proactive calls made since the last call. ``end`` clears every per-car buffer (privacy).

Laps are the player's: a lap-number change of the frames by one is the line. A flashback (``FLBK``, or the game clock
going back more than ``REWIND_S``) drops what the monitors held for the lap in progress.
"""

from __future__ import annotations

import bisect
import time
from collections import deque
from collections.abc import Callable, Mapping
from typing import Any

from pitwall.carhealth import thresholds as T
from pitwall.carhealth.calls import CallContext, HealthCall, HealthCallPlanner
from pitwall.carhealth.fuel import TankFractionFuel
from pitwall.carhealth.racecraft import Racecraft, Segments
from pitwall.carhealth.settings import DEFAULTS, HealthSettings
from pitwall.carhealth.slip import SlipCounter
from pitwall.carhealth.temps import BrakeEngineMonitor
from pitwall.carhealth.tyres import MODEL_CARCASS, MODEL_SURFACE, TyreTempMonitor
from pitwall.coach.cues import cue_labels
from pitwall.model.telemetry import (
    CarFrame,
    FieldSample,
    FrameQuality,
    Game,
    GameEvent,
    LapCompletion,
    RaceTiming,
    SessionInfo,
    SessionType,
)

REWIND_S = 0.5
RED_FLAG_TIMEOUT_S = 300.0  # as core.live / strategy.engine
CALLS_SHOWN = 2  # the view's recent calls (the size budget: ~1.5 kB)
NEUTRAL = ("full", "virtual")
FUEL_GAMES = frozenset({Game.FORZA_MOTORSPORT, Game.FORZA_HORIZON, Game.GT7})
_OFF_TRACK = FrameQuality.PAUSED | FrameQuality.REPLAY_OR_SPECTATING | FrameQuality.NOT_RACING


class CarHealthEngine:
    def __init__(
        self,
        session_id: str,
        *,
        track_model: Callable[[], Mapping[str, Any] | None] | None = None,
        settings: HealthSettings = DEFAULTS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.session_id = session_id
        self.track_model = track_model
        self.info: SessionInfo | None = None
        self.game: Game | None = None
        self.frame: CarFrame | None = None
        self.tyres = TyreTempMonitor()
        self.temps = BrakeEngineMonitor()
        self.slip = SlipCounter(self._corner_of)
        self.fuel: TankFractionFuel | None = None
        self.racecraft = Racecraft()
        self.planner = HealthCallPlanner(clock, settings)
        self.recent_calls: deque[HealthCall] = deque(maxlen=CALLS_SHOWN)
        self._pending: list[HealthCall] = []
        self._lap: int | None = None
        self._t: float | None = None
        self._sc: str | None = None
        self._red_flag_t: float | None = None
        self._stint = 0
        self._prev_pit: int | None = None
        self._prev_age: int | None = None
        self._model_ref: object | None = None
        self._seg: Segments | None = None
        self.ended = False
        self.lines = 0  # line crossings seen (publish cadence)
        self.rewinds = 0

    # ================================================================== properties
    @property
    def settings(self) -> HealthSettings:
        return self.planner.settings

    @settings.setter
    def settings(self, s: HealthSettings) -> None:
        self.planner.settings = s

    @property
    def f1(self) -> bool:
        return self.game is Game.F1_25

    @property
    def race(self) -> bool:
        return self.info is not None and self.info.session_type is SessionType.RACE

    @property
    def wants_field(self) -> bool:
        """F1 races only: the other cars' samples feed attack / defend (read on the ingest thread: a plain bool)."""
        return self.f1 and self.race and not self.ended

    def tyre_model(self) -> str | None:
        """Carcass only when the F1 session simulates it (else the inner temperature is a constant); surface for the
        other games that send tyre temperatures; None for a game that sends none."""
        if self.game is Game.F1_25:
            m = None if self.info is None else self.info.extra.get("tyre_temperature_model")
            return MODEL_CARCASS if m == "surface_and_carcass" else MODEL_SURFACE
        if self.game in (Game.GT7, Game.FORZA_MOTORSPORT, Game.FORZA_HORIZON):
            return MODEL_SURFACE
        return None

    # ================================================================== input
    def feed(self, item: object) -> None:
        if self.ended:
            return
        if isinstance(item, CarFrame):
            self._on_frame(item)
        elif isinstance(item, FieldSample):
            self._on_field(item)
        elif isinstance(item, RaceTiming):
            self._clock_check(item.session_time_s)
            self.racecraft.timing = item
        elif isinstance(item, SessionInfo):
            self._on_session(item)
        elif isinstance(item, GameEvent):
            self._on_event(item)
        elif isinstance(item, LapCompletion):
            self._clock_check(item.session_time_s)

    def _clock_check(self, t: float | None) -> None:
        if t is None:
            return
        if self._t is not None and t < self._t - REWIND_S:
            self.rewind()
        self._t = t if self._t is None or t > self._t else self._t

    def rewind(self) -> None:
        self.rewinds += 1
        self.tyres.rewind()
        self.temps.rewind()
        self.slip.rewind()
        self.racecraft.flashback()
        self._t = None

    def _on_session(self, info: SessionInfo) -> None:
        self._clock_check(info.session_time_s)
        self.info = info
        self.game = info.game
        if self.game in FUEL_GAMES and self.fuel is None:
            self.fuel = TankFractionFuel(enabled=self.game is not Game.GT7 or T.GT7_FUEL_ENABLED)
        sc = info.safety_car_status
        if self.f1 and self._sc in NEUTRAL and sc == "none":
            self.tyres.on_safety_car_end()
        self._sc = sc
        if info.track_length_m:
            self.racecraft.line_length_m = info.track_length_m
        frac = info.extra.get("fuel_fraction")
        if self.fuel is not None and isinstance(frac, int | float) and not isinstance(frac, bool):
            f = self.frame
            on_track = f is not None and not (f.quality & _OFF_TRACK)
            self.fuel.on_level(float(frac), None if f is None else f.lap_number, on_track)

    def _on_event(self, e: GameEvent) -> None:
        code = e.code
        if code == "FLBK":
            self.rewind()
            target = e.payload.get("flashbackSessionTime")
            if isinstance(target, int | float):
                self._t = float(target)
        elif code == "RDFL":
            self._red_flag_t = e.session_time_s if e.session_time_s is not None else (self._t or 0.0)
        elif code in ("LGOT", "SSTA", "SEND"):
            self._red_flag_t = None

    def _on_field(self, s: FieldSample) -> None:
        if not self.wants_field:
            return
        self.racecraft.on_field(
            s.car_index,
            s.lap_number,
            s.lap_distance_m,
            s.session_time_s,
            pit=bool(s.pit_status),
            sc=bool(s.safety_car),
            invalid=s.lap_invalid,
        )

    def _on_frame(self, f: CarFrame) -> None:
        self._clock_check(f.session_time_s)
        if self.game is None:
            self.game = f.game
        self.frame = f
        self._refresh_model()
        pit = f.pit_status
        if pit is not None and self._prev_pit and not pit:
            self._stint += 1  # a pit exit: a new stint (tyres changed or not)
        if pit is not None:
            self._prev_pit = pit
        age = f.tyre_age_laps
        if age is not None and self._prev_age is not None and age < self._prev_age:
            self._stint += 1
        if age is not None:
            self._prev_age = age
        self.tyres.on_frame(f, self.tyre_model())
        self.temps.on_frame(f)
        self.slip.on_frame(f)
        if self.f1 and self.race:
            self.racecraft.on_player(
                f.lap_number,
                f.lap_distance_m,
                f.session_time_s,
                pit=bool(f.pit_status),
                sc=self._sc in (*NEUTRAL, "formation_lap"),
                invalid=bool(f.lap_invalid),
            )
        lap = f.lap_number
        if lap is not None:
            if self._lap is not None and lap == self._lap + 1:
                self._line(self._lap, lap)
            self._lap = lap
        for ev in self.tyres.take_events():
            self._emit(self.planner.tyres(self._ctx(), ev))

    def _line(self, finished: int, new: int) -> None:
        self.lines += 1
        self.tyres.on_line(new)
        self.temps.on_line(finished)
        last = self.slip.on_line(finished, new)
        ctx = self._ctx(lap=new)
        for c in self.planner.slip(ctx, last, self.slip.last_events):
            self._emit(c)
        self._emit(self.planner.wear(ctx, self.tyres.wear_now, self._stint))
        fuel = self.fuel
        if fuel is not None and fuel.enabled:
            per = fuel.view()["per_lap"]  # a fraction of the tank, whatever range the game sends the level in
            self._emit(self.planner.fuel(ctx, fuel.status(), fuel.laps_of_fuel(), per))

    def _emit(self, call: HealthCall | None) -> None:
        if call is None:
            return
        self._pending.append(call)
        self.recent_calls.appendleft(call)

    def _ctx(self, lap: int | None = None) -> CallContext:
        f, info = self.frame, self.info
        lap = lap if lap is not None else self._lap
        total = None if info is None or not self.race else info.total_laps
        return CallContext(
            lap=lap,
            blocked=self.blocked(),
            in_pit=bool(f is not None and f.pit_status),
            final_lap=bool(total and lap is not None and lap >= total),
            f1_race=self.f1 and self.race,
        )

    def blocked(self) -> str | None:
        if self.info is not None and self.info.safety_car_status == "formation_lap":
            return "formation lap"
        if self._red_flag_t is not None:
            if self._t is not None and self._t - self._red_flag_t > RED_FLAG_TIMEOUT_S:
                self._red_flag_t = None
            else:
                return "red flag"
        return None

    # ================================================================== track model
    def _refresh_model(self) -> None:
        """The live track model changed (an attribute read per frame; work only when the object changed)."""
        if self.track_model is None:
            return
        model = self.track_model()
        if model is self._model_ref:
            return
        self._model_ref = model
        labels = {name: (lab.spoken or lab.text) for name, lab in cue_labels(model).items()}
        seg = Segments.from_model(model, labels)
        self._seg = seg
        length = None if self.info is None else self.info.track_length_m
        self.racecraft.set_segments(seg, length)

    def _corner_of(self, d: float | None) -> tuple[str, str] | None:
        seg = self._seg
        if seg is None or d is None or d < 0:
            return None
        k = bisect.bisect_right(seg.starts, d) - 1
        if k < 0:
            return None
        return seg.names[k], seg.texts[k]

    # ================================================================== output
    def take_calls(self) -> list[HealthCall]:
        out, self._pending = self._pending, []
        return out

    def end(self) -> None:
        """The session ended: every per-car buffer goes (privacy); the player's own blocks stay for the last view."""
        self.ended = True
        self.racecraft.clear()

    def view(self) -> dict[str, Any]:
        from pitwall.carhealth.view import build_view

        return build_view(self)

    def racecraft_view(self) -> dict[str, Any]:
        from pitwall.carhealth.view import build_racecraft_view

        return build_racecraft_view(self)
