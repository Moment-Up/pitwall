"""The race radio engine's shared per-session state (worker thread only), read by every rule module."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pitwall.analysis.track_skeleton import TrackSkeleton
from pitwall.model.telemetry import CarFrame, CarTiming, Game, RaceTiming, SessionInfo
from pitwall.raceradio.roster import Roster
from pitwall.strategy.laps_left import laps_remaining_detail

IN_PITS = (1, 2)  # CarFrame.pit_status: 1 pitting / in the pit lane, 2 in the pit area
F1_GAMES = (Game.F1_25, Game.F1_24)
OUT_OF_RACE = frozenset({"retired", "dnf", "dsq", "not_classified"})  # CarTiming.result_status of a car that stopped


@dataclass(slots=True)
class RaceState:
    session_id: str
    track_model: Callable[[], Mapping[str, Any] | None] | None = None
    game: Game | None = None
    mode: str = "off"  # "race" | "session" (F1 practice / qualifying) | "off"
    reason: str | None = "no session information yet"
    synthetic: bool = False
    info: SessionInfo | None = None
    frame: CarFrame | None = None
    timing: RaceTiming | None = None
    me: CarTiming | None = None  # the player's row of the latest RaceTiming (F1)
    t: float = 0.0  # latest receive time (s, host monotonic clock of the stream)
    t0: float | None = None  # the session's first item
    lap: int | None = None  # the player's current lap (frames)
    crossing_t: float = -math.inf  # the last time the player's lap number went up
    position: int | None = None  # the player's race position (frames; None = unknown)
    grid: int | None = None  # the player's starting position (see engine: position before the start)
    lights_out_t: float | None = None
    in_pits: bool = False
    racing: bool = False  # the latest frame is the player driving: not paused, a replay or out of the race
    slow_t: float = -math.inf  # last frame under raceradio.flags.SLOW_KPH
    flbk_t: float = -math.inf  # last flashback
    retired: bool = False  # the player is out of the race (PENA 16 / result status): only urgent calls
    finished: bool = False  # the finish call was made: only urgent calls
    red_flag_t: float | None = None
    neutral: str | None = None  # "full" | "virtual" while a safety car / VSC runs (raceradio.flags)
    skeleton: TrackSkeleton | None = None
    roster: Roster = field(default_factory=Roster)

    @property
    def f1(self) -> bool:
        return self.game in F1_GAMES

    @property
    def race(self) -> bool:
        return self.mode == "race"

    @property
    def speed_kph(self) -> float | None:
        f = self.frame
        return None if f is None else f.speed_kph

    @property
    def total_laps(self) -> int | None:
        info = self.info
        return info.total_laps if info is not None and info.total_laps else None

    @property
    def track_length_m(self) -> float | None:
        info = self.info
        return info.track_length_m if info is not None and info.track_length_m else None

    @property
    def cars(self) -> int | None:
        """The field size: F1 race timing's cars, else the game's own count (GT7 0x86)."""
        if self.timing is not None and self.timing.cars:
            return len(self.timing.cars)
        n = None if self.info is None else self.info.extra.get("num_cars_pre_race")
        return n if isinstance(n, int) and not isinstance(n, bool) and n > 0 else None

    def laps_left(self, lap: int | None = None, lap_frac: float | None = None) -> tuple[float | None, str | None]:
        """(laps left, source) with ``strategy.laps_left`` (the lapped-car rule from F1 timing; GT7 without cars)."""
        f = self.frame
        if lap_frac is None:
            d = None if f is None else f.lap_distance_m
            length = self.track_length_m
            lap_frac = 0.0 if d is None or not length or d <= 0 else min(1.0, d / length)
        return laps_remaining_detail(
            total_laps=self.total_laps,
            lap=self.lap if lap is None else lap,
            lap_frac=lap_frac,
            cars=() if self.timing is None or not self.f1 else self.timing.cars,
            track_length_m=self.track_length_m,
            took_flag=self.finished,
            player_result=None if self.me is None else self.me.result_status,
        )
