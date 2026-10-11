"""Lap assembly: turn a stream of ``CarFrame``s into complete, quality-annotated ``LapTrace``s.

Handles: flashbacks/rewinds (session time going backwards), pit in/out laps, partial laps (joined
mid-lap or packet loss), and pause/spectate frames. Every exclusion is recorded in ``LapTrace.flags`` so
that reference-lap selection can reject compromised laps instead of silently comparing them.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

from pitwall.model.telemetry import CarFrame, FrameQuality, Game, LapCompletion

log = logging.getLogger(__name__)
FloatArray = npt.NDArray[np.float64]

# Channels stored for every lap (all float64; NaN where the game does not provide the value).
CHANNELS: tuple[str, ...] = (
    "session_time_s",
    "lap_time_ms",
    "distance_m",
    "speed_kph",
    "throttle",
    "brake",
    "steering",
    "gear",
    "rpm",
    "pos_x_m",
    "pos_y_m",
    "pos_z_m",
    "g_lat",
    "g_lon",
    "fuel_kg",
    "tyre_temp_fl",
    "tyre_temp_fr",
    "tyre_temp_rl",
    "tyre_temp_rr",
)

MAX_GAP_M = 60.0  # a distance step larger than this is either data loss or a game-side distance jump
MAX_TIME_GAP_S = 1.0  # a session-time gap larger than this (no flashback) means lost packets -> incomplete
EDGE_TOLERANCE_M = 60.0  # lap must start/end within this distance of the line to count as complete
# Games whose lap distance pitwall derives (GT7: integrated speed; Forza: odometer) instead of reading it: the
# end-of-lap check scales with the lap, because ~1% drift is ~70 m at Spa and ~200 m on the Nordschleife.
DERIVED_DISTANCE_GAMES = frozenset({Game.GT7, Game.FORZA_MOTORSPORT, Game.FORZA_HORIZON})
DERIVED_EDGE_FRAC = 0.015


class LapFlag:
    FLASHBACK = "flashback"
    PIT_IN = "pit_in"
    PIT_OUT = "pit_out"
    INCOMPLETE = "incomplete"
    INVALID = "invalid"  # game-declared invalid (track limits etc.)
    PAUSED = "paused"
    STALE_DATA = "stale_data"
    STANDING_START = "standing_start"
    # lap distance jumped with no time gap (e.g. reset to track after an off): timed, but distance alignment is
    # locally broken, so not used as a reference
    DISTANCE_JUMP = "distance_jump"  # race lap 1 from the grid: timed, but not comparable to flying laps


@dataclass(slots=True)
class LapTrace:
    lap_number: int
    channels: dict[str, FloatArray]
    lap_time_ms: int | None
    sector_times_ms: list[int | None] = field(default_factory=list)
    valid: bool | None = None  # game-declared validity
    flags: set[str] = field(default_factory=set)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def n(self) -> int:
        return len(self.channels["distance_m"])

    @property
    def clean(self) -> bool:
        """Usable as a reference: complete, game-valid, no flashback, not a pit lap."""
        bad = {
            LapFlag.FLASHBACK,
            LapFlag.PIT_IN,
            LapFlag.PIT_OUT,
            LapFlag.INCOMPLETE,
            LapFlag.INVALID,
            LapFlag.STANDING_START,
            LapFlag.DISTANCE_JUMP,
        }
        return not (self.flags & bad) and self.valid is not False and self.lap_time_ms is not None

    def to_npz(self) -> bytes:
        buf = io.BytesIO()
        arrays: dict[str, Any] = {k: v.astype(np.float32) for k, v in self.channels.items()}
        np.savez_compressed(buf, **arrays)
        return buf.getvalue()

    @staticmethod
    def channels_from_npz(raw: bytes) -> dict[str, FloatArray]:
        with np.load(io.BytesIO(raw)) as z:
            return {k: z[k].astype(np.float64) for k in z.files}


def _val(v: float | int | None) -> float:
    return float("nan") if v is None else float(v)


def _frame_row(f: CarFrame) -> tuple[float, ...]:
    tt = f.tyre_surface_temp_c
    return (
        _val(f.session_time_s),
        _val(f.current_lap_time_ms),
        _val(f.lap_distance_m),
        _val(f.speed_kph),
        _val(f.throttle),
        _val(f.brake),
        _val(f.steering),
        _val(f.gear),
        _val(f.rpm),
        _val(f.pos_x_m),
        _val(f.pos_y_m),
        _val(f.pos_z_m),
        _val(f.g_lat),
        _val(f.g_lon),
        _val(f.fuel_kg),
        _val(tt.fl if tt else None),
        _val(tt.fr if tt else None),
        _val(tt.rl if tt else None),
        _val(tt.rr if tt else None),
    )


@dataclass(slots=True)
class _Building:
    lap_number: int
    rows: list[tuple[float, ...]] = field(default_factory=list)
    flags: set[str] = field(default_factory=set)
    first: CarFrame | None = None
    last: CarFrame | None = None
    stale: int = 0
    first_fuel_kg: float | None = None  # first *available* values: slow packets may lag the first frame
    first_wear: tuple[float, float, float, float] | None = None


class LapAssembler:
    """Feeds on frames and lap completions; calls ``on_lap`` with each finished ``LapTrace``."""

    def __init__(self, on_lap: Callable[[LapTrace], None], track_length_m: float | None = None) -> None:
        self.on_lap = on_lap
        self.track_length_m = track_length_m
        self._cur: _Building | None = None
        self._pending_completion: LapCompletion | None = None
        self.laps_emitted = 0

    def set_track_length(self, length_m: float | None) -> None:
        self.track_length_m = length_m

    def _end_tolerance_m(self, game: Game | None) -> float:
        if game in DERIVED_DISTANCE_GAMES and self.track_length_m:
            return max(EDGE_TOLERANCE_M, DERIVED_EDGE_FRAC * self.track_length_m)
        return EDGE_TOLERANCE_M

    def feed_completion(self, c: LapCompletion) -> None:
        cur = self._cur
        if cur is not None and cur.lap_number == c.lap_number:
            self._finalise(cur, c)
            self._cur = None
        else:
            self._pending_completion = c

    def feed(self, f: CarFrame) -> None:
        if f.quality & (FrameQuality.PAUSED | FrameQuality.REPLAY_OR_SPECTATING | FrameQuality.NOT_RACING):
            return
        if f.lap_number is None or f.lap_distance_m is None:
            return
        cur = self._cur
        if cur is not None and f.lap_number != cur.lap_number:
            if f.lap_number == cur.lap_number + 1:
                pc = self._pending_completion
                self._finalise(cur, pc if pc and pc.lap_number == cur.lap_number else None)
            elif f.lap_number < cur.lap_number:
                # Rewound across the line into an earlier lap: the partially built lap is unusable.
                log.info("lap %d abandoned: rewind into lap %d", cur.lap_number, f.lap_number)
            else:
                cur.flags.add(LapFlag.INCOMPLETE)
                self._finalise(cur, None)
            self._pending_completion = None
            cur = self._cur = None
        if cur is None:
            cur = self._cur = _Building(lap_number=f.lap_number, first=f)
            if f.lap_distance_m > EDGE_TOLERANCE_M:
                if f.lap_number == 1 and (f.current_lap_time_ms or 0) < 1000:
                    # race start: the grid can be well past the line (Austria: 132 m) - the lap is complete
                    # and timed by the game, just not comparable with flying laps
                    cur.flags.add(LapFlag.STANDING_START)
                else:
                    cur.flags.add(LapFlag.INCOMPLETE)  # joined mid-lap
        # flashback / rewind detection: session time went backwards within the lap
        if cur.rows and f.session_time_s is not None:
            t_new = f.session_time_s
            if t_new < cur.rows[-1][0] - 1e-6:
                cur.flags.add(LapFlag.FLASHBACK)
                cur.rows = [r for r in cur.rows if r[0] < t_new]
        if f.pit_status:
            cur.flags.add(LapFlag.PIT_IN if cur.rows and cur.rows[-1][2] > 100 else LapFlag.PIT_OUT)
        if f.quality & (FrameQuality.STALE_LAP_DATA | FrameQuality.STALE_POSITION):
            cur.stale += 1
        if cur.first_fuel_kg is None and f.fuel_kg is not None:
            cur.first_fuel_kg = f.fuel_kg
        if cur.first_wear is None and f.tyre_wear_pct is not None:
            cur.first_wear = f.tyre_wear_pct.as_tuple()
        cur.rows.append(_frame_row(f))
        cur.last = f

    def _finalise(self, b: _Building, completion: LapCompletion | None) -> None:
        if not b.rows:
            return
        arr = np.array(b.rows, dtype=np.float64)
        channels = {name: arr[:, i] for i, name in enumerate(CHANNELS)}
        flags = set(b.flags)
        dist = channels["distance_m"]
        if len(dist) > 1:
            dd = np.diff(dist)
            dt = np.diff(channels["session_time_s"])
            jumps = dd > MAX_GAP_M
            if np.any(jumps & (dt > MAX_TIME_GAP_S)) or np.any(dt > MAX_TIME_GAP_S * 3):
                flags.add(LapFlag.INCOMPLETE)  # packets missing
            elif np.any(jumps):
                flags.add(LapFlag.DISTANCE_JUMP)
            if self.track_length_m and np.nanmax(dist) < self.track_length_m - self._end_tolerance_m(
                b.first.game if b.first else None
            ):
                flags.add(LapFlag.INCOMPLETE)
        if b.stale > 0.2 * len(dist):
            flags.add(LapFlag.STALE_DATA)
        lap_time = completion.lap_time_ms if completion else None
        valid = completion.valid if completion else None
        if valid is False:
            flags.add(LapFlag.INVALID)
        first, last = b.first, b.last
        meta: dict[str, Any] = {
            "fuel_start_kg": b.first_fuel_kg,
            "fuel_end_kg": last.fuel_kg if last else None,
            "tyre_compound": last.tyre_compound if last else None,
            "tyre_age_laps": last.tyre_age_laps if last else None,
            "wear_start": b.first_wear,
            "wear_end": last.tyre_wear_pct.as_tuple() if last and last.tyre_wear_pct else None,
            "t_recv_start_ns": first.t_recv_ns if first else None,
            "t_recv_end_ns": last.t_recv_ns if last else None,
        }
        lap = LapTrace(
            lap_number=b.lap_number,
            channels=channels,
            lap_time_ms=lap_time,
            sector_times_ms=list(completion.sector_times_ms) if completion else [],
            valid=valid,
            flags=flags,
            meta=meta,
        )
        self.laps_emitted += 1
        self.on_lap(lap)

    def flush(self) -> None:
        """Emit the in-progress lap as incomplete (e.g. session ended mid-lap)."""
        if self._cur is not None and self._cur.rows:
            self._cur.flags.add(LapFlag.INCOMPLETE)
            self._finalise(self._cur, None)
        self._cur = None
