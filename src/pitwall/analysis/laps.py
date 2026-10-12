"""Lap assembly: turn a stream of ``CarFrame``s into complete, quality-annotated ``LapTrace``s.

Handles: flashbacks/rewinds (session time going backwards), pit in/out laps, partial laps (joined
mid-lap or packet loss), and pause/spectate frames. Every exclusion is recorded in ``LapTrace.flags`` so
that reference-lap selection can reject compromised laps instead of silently comparing them.

A lap keeps the game's own number (``CarFrame.lap_number``; F1: ``currentLapNum``): race lap 1 is lap 1, a
scenario that starts at lap 62 starts at 62, and in-, out- and opening laps are numbered like any other lap.

* **Pit laps** follow the car's pit-lane state through the lap (``CarFrame.pit_status``: 1 pit lane, 2 pit area;
  0, or unknown, is not known to be in the pit lane). A lap that *starts* in the pit lane is an out lap
  (``pit_out``), the pit lane after running on track makes an in lap (``pit_in``), and only a lap that enters
  and leaves the pit lane (a drive-through, or a stop whose box is inside one lap) is both. Real F1 25 Imola:
  the pit exit is 449 m past the line, so the out lap runs 0-449 m in the pit lane and is an out lap only.
  A flashback rewinds the pit-lane state with the trace: the pit flags are those of the frames the lap keeps
  (rewound from the pit entry back onto the track, an in lap is a clean in lap again until the car re-enters).
* **Standing start**: race lap 1 from the grid is timed by the game but is not a flying lap. It is recognised
  from its first frame, wherever the grid is (real F1 25: Melbourne -164 m, Las Vegas +2.6 m, Austria +132 m):
  lap 1, lap timer under ``STANDING_START_MAX_MS``, car stationary (``STANDING_START_MAX_KPH``) and not in the
  pit lane. A flying first lap (one-shot qualifying from -306 m) or a scenario joined at speed is not one.
* **Race start** (``RACE_START``): race lap 1 that the adapter reports as timed from the start signal rather than
  from the line (``LapCompletion.race_start``; GT7 rolling starts). Timed, never a reference.
* **Laps without a trace** (``NO_TRACE``): a lap the game timed but the adapter could not place on the track
  (``LapCompletion.untraced``: no frame of it had a lap distance - GT7 after a standing start or a session joined
  mid-lap) is still stored, with the game's time and no samples, so a timed lap never disappears from the lap list.
  Only for a lap this assembler saw being driven and never built or finalised, so a late completion can never
  overwrite a lap with a trace.
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

# --- feat/technique: chassis dynamics (F1 MotionEx), appended to CHANNELS; all-NaN for games that do not send them.
# Older laps lack them, so readers use ``channels.get(...)``.
TECHNIQUE_CHANNELS: tuple[str, ...] = (
    "yaw_rate_rps",  # + = turning right (same sign as steering)
    "body_slip_rad",
    "slip_angle_front_abs_rad",  # mean |slip angle| of the two front wheels
    "slip_angle_rear_abs_rad",
    "wheel_slip_fl",  # slip ratio per wheel (names match rig.rig_check)
    "wheel_slip_fr",
    "wheel_slip_rl",
    "wheel_slip_rr",
)
# --- end feat/technique ---

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
    *TECHNIQUE_CHANNELS,  # feat/technique
)

ASSIST_MIN_KPH = 5.0  # feat/technique: lap assist meta counts frames on the move only (see LapAssembler.feed)
ASSIST_COVER_FRAC = 0.9  # feat/technique: an assist value must cover this share of the moving frames to be the lap's
MAX_GAP_M = 60.0  # a distance step larger than this is either data loss or a game-side distance jump
MAX_TIME_GAP_S = 1.0  # a session-time gap larger than this (no flashback) means lost packets -> incomplete
EDGE_TOLERANCE_M = 60.0  # lap must start/end within this distance of the line to count as complete
STANDING_START_MAX_MS = 1000  # race lap 1's timer this close to 0 at its first frame: the lap starts here
STANDING_START_MAX_KPH = 5.0  # ... with the car (nearly) stationary: a grid slot, not a flying start
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
    STANDING_START = "standing_start"  # race lap 1 from the grid: timed, but not comparable to flying laps
    # lap distance jumped with no time gap (e.g. reset to track after an off): timed, but distance alignment is
    # locally broken, so not used as a reference
    DISTANCE_JUMP = "distance_jump"
    RACE_START = "race_start"  # race lap 1 timed from the start signal (rolling start): not comparable either
    NO_TRACE = "no_trace"  # timed by the game, but no frame had a lap distance: stored with its time only


# Race lap 1 in either form: timed by the game, never comparable with a flying lap.
RACE_START_FLAGS = frozenset({LapFlag.STANDING_START, LapFlag.RACE_START})


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
            LapFlag.RACE_START,
            LapFlag.NO_TRACE,
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


def _dominant[T](counts: dict[T, int]) -> T | None:
    """feat/technique: the assist value seen on at least ``ASSIST_COVER_FRAC`` of the lap's moving frames that sent
    one, else ``None`` (changed during the lap, or never sent)."""
    total = sum(counts.values())
    if total <= 0:
        return None
    value, n = max(counts.items(), key=lambda kv: kv[1])
    return value if n >= ASSIST_COVER_FRAC * total else None


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
        *_technique_row(f),  # feat/technique
    )


_NAN8 = (float("nan"),) * 8


def _technique_row(f: CarFrame) -> tuple[float, ...]:
    """feat/technique: the ``TECHNIQUE_CHANNELS`` values of one frame (NaN when the game did not send them)."""
    sr, sa = f.wheel_slip_ratio, f.wheel_slip_angle_rad
    if f.yaw_rate_rps is None and sr is None and sa is None and f.body_slip_rad is None:
        return _NAN8
    nan = float("nan")
    return (
        _val(f.yaw_rate_rps),
        _val(f.body_slip_rad),
        (abs(sa.fl) + abs(sa.fr)) / 2 if sa else nan,
        (abs(sa.rl) + abs(sa.rr)) / 2 if sa else nan,
        sr.fl if sr else nan,
        sr.fr if sr else nan,
        sr.rl if sr else nan,
        sr.rr if sr else nan,
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
    # feat/technique: moving frames per assist value (O(1) per frame; CarStatus can lag or be zeroed at a start)
    abs_moving: dict[bool, int] = field(default_factory=dict)
    tc_moving: dict[int, int] = field(default_factory=dict)
    # pit-lane state through the lap: (session time, in the pit lane) at each change, so a flashback can rewind it
    pit_runs: list[tuple[float, bool]] = field(default_factory=list)


_PIT_FLAGS = frozenset({LapFlag.PIT_IN, LapFlag.PIT_OUT})


def _pit_flags(runs: list[tuple[float, bool]]) -> set[str]:
    """The pit flags of a lap from its pit-lane runs (alternating: in the pit lane or not, in order).

    A first run in the pit lane is an out lap; the pit lane after running on track, an in lap; back on track
    after that entry, both (a drive-through, or a stop whose box is inside the lap)."""
    flags: set[str] = set()
    on_track = entered = False
    for _, in_pit in runs:
        if in_pit:
            if on_track:
                flags.add(LapFlag.PIT_IN)
                entered = True
            else:
                flags.add(LapFlag.PIT_OUT)
        else:
            if entered:
                flags.add(LapFlag.PIT_OUT)
            on_track = True
    return flags


def _standing_start(f: CarFrame) -> bool:
    """Race lap 1 beginning from the grid: the lap timer at ~0 with the car stationary, outside the pit lane.

    Wherever the grid is relative to the line (it can be behind it: negative lap distance). Unknown speed or lap
    time is not a standing start (unknown stays unknown)."""
    return (
        f.lap_number == 1
        and f.current_lap_time_ms is not None
        and f.current_lap_time_ms < STANDING_START_MAX_MS
        and f.speed_kph is not None
        and f.speed_kph < STANDING_START_MAX_KPH
        and not f.pit_status
    )


class LapAssembler:
    """Feeds on frames and lap completions; calls ``on_lap`` with each finished ``LapTrace``."""

    def __init__(self, on_lap: Callable[[LapTrace], None], track_length_m: float | None = None) -> None:
        self.on_lap = on_lap
        self.track_length_m = track_length_m
        self._cur: _Building | None = None
        self._pending_completion: LapCompletion | None = None
        self.laps_emitted = 0
        self._finalised: set[int] = set()  # lap numbers emitted by this assembler (one session)
        self._untraced_lap: int | None = None  # the last lap seen driven with no lap distance

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
        elif (
            c.untraced
            and c.lap_time_ms is not None
            and c.lap_number == self._untraced_lap
            and c.lap_number not in self._finalised
            and (cur is None or cur.lap_number < c.lap_number)
        ):
            self._finalise_untraced(c)  # driven, timed by the game, never anchored: its time is still a lap
        else:
            self._pending_completion = c

    def feed(self, f: CarFrame) -> None:
        if f.quality & (FrameQuality.PAUSED | FrameQuality.REPLAY_OR_SPECTATING | FrameQuality.NOT_RACING):
            return
        if f.lap_number is None:
            return
        if f.lap_distance_m is None:
            self._untraced_lap = f.lap_number  # O(1): a timed lap without any distance is stored without a trace
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
            if _standing_start(f):
                # race start from the grid, wherever the grid is (Melbourne: 164 m behind the line, Austria: 132 m
                # past it): the lap is complete and timed by the game, just not comparable with flying laps
                cur.flags.add(LapFlag.STANDING_START)
            elif f.lap_distance_m > EDGE_TOLERANCE_M:
                if f.lap_number == 1 and (f.current_lap_time_ms or 0) < STANDING_START_MAX_MS:
                    # lap 1 first seen past the line at ~0 lap time while already moving: still the race start
                    cur.flags.add(LapFlag.STANDING_START)
                else:
                    cur.flags.add(LapFlag.INCOMPLETE)  # joined mid-lap
        # flashback / rewind detection: session time went backwards within the lap
        if cur.rows and f.session_time_s is not None:
            t_new = f.session_time_s
            if t_new < cur.rows[-1][0] - 1e-6:
                cur.flags.add(LapFlag.FLASHBACK)
                cur.rows = [r for r in cur.rows if r[0] < t_new]
                # the pit-lane state rewinds too: a pit entry (or exit) the driver flashed back over never happened
                runs = cur.pit_runs = [r for r in cur.pit_runs if r[0] < t_new]
                cur.flags = (cur.flags - _PIT_FLAGS) | _pit_flags(runs)
        in_pit = bool(f.pit_status)  # in the pit lane (1) or pit area (2); 0, or unknown, is not
        if not cur.pit_runs or cur.pit_runs[-1][1] != in_pit:
            cur.pit_runs.append((_val(f.session_time_s), in_pit))
            cur.flags |= _pit_flags(cur.pit_runs)
        if f.quality & (FrameQuality.STALE_LAP_DATA | FrameQuality.STALE_POSITION):
            cur.stale += 1
        if cur.first_fuel_kg is None and f.fuel_kg is not None:
            cur.first_fuel_kg = f.fuel_kg
        if cur.first_wear is None and f.tyre_wear_pct is not None:
            cur.first_wear = f.tyre_wear_pct.as_tuple()
        # feat/technique: assists counted on frames on the move only. Real F1 25 sends a zeroed CarStatus (ABS off,
        # TC 0) on the grid and for the first seconds of a session joined at speed; neither is a change of assist
        if f.speed_kph is not None and f.speed_kph >= ASSIST_MIN_KPH:
            if f.abs_active is not None:
                cur.abs_moving[f.abs_active] = cur.abs_moving.get(f.abs_active, 0) + 1
            if f.traction_control is not None:
                cur.tc_moving[f.traction_control] = cur.tc_moving.get(f.traction_control, 0) + 1
        cur.rows.append(_frame_row(f))
        cur.last = f

    def _finalise(self, b: _Building, completion: LapCompletion | None) -> None:
        if not b.rows:
            return
        arr = np.array(b.rows, dtype=np.float64)
        channels = {name: arr[:, i] for i, name in enumerate(CHANNELS)}
        flags = set(b.flags)
        dist = channels["distance_m"]
        if len(dist) < 2:
            # a lap of one sample covers nothing: real F1 25 one-shot qualifying sent a "lap" that was never driven
            # (one frame past the line), and it once counted as clean. Every game: fewer than 2 samples is incomplete.
            flags.add(LapFlag.INCOMPLETE)
        else:
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
            flags.add(LapFlag.INCOMPLETE)  # the lap does not reach the line (also a one-sample lap)
        if b.stale > 0.2 * len(dist):
            flags.add(LapFlag.STALE_DATA)
        lap_time = completion.lap_time_ms if completion else None
        valid = completion.valid if completion else None
        if valid is False:
            flags.add(LapFlag.INVALID)
        if completion is not None and completion.race_start and not flags & RACE_START_FLAGS:
            flags.add(LapFlag.RACE_START)
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
            # feat/technique: the lap's assists, when one value covers 90 % of the moving frames (None = changed
            # during the lap, or not sent)
            "abs_active": _dominant(b.abs_moving),
            "traction_control": _dominant(b.tc_moving),
            # the driver's last lap of the session (LapCompletion.final; None = the game does not say)
            "final": completion.final if completion else None,
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
        self._emit(lap)

    def _finalise_untraced(self, c: LapCompletion) -> None:
        """A lap the game timed but no frame of which had a lap distance: its time, no samples (``NO_TRACE``, and
        ``INCOMPLETE`` so nothing downstream analyses a trace it does not have)."""
        flags = {LapFlag.INCOMPLETE, LapFlag.NO_TRACE}
        if c.valid is False:
            flags.add(LapFlag.INVALID)
        if c.race_start:
            flags.add(LapFlag.RACE_START)
        empty = np.empty(0, dtype=np.float64)
        meta: dict[str, Any] = {
            "fuel_start_kg": None,
            "fuel_end_kg": None,
            "tyre_compound": None,
            "tyre_age_laps": None,
            "wear_start": None,
            "wear_end": None,
            "t_recv_start_ns": None,
            "t_recv_end_ns": c.t_recv_ns,
            "abs_active": None,
            "traction_control": None,
            "final": c.final,
        }
        self._untraced_lap = None
        self._emit(
            LapTrace(
                lap_number=c.lap_number,
                channels={name: empty.copy() for name in CHANNELS},
                lap_time_ms=c.lap_time_ms,
                sector_times_ms=list(c.sector_times_ms),
                valid=c.valid,
                flags=flags,
                meta=meta,
            )
        )

    def _emit(self, lap: LapTrace) -> None:
        self._finalised.add(lap.lap_number)
        self.laps_emitted += 1
        self.on_lap(lap)

    def flush(self) -> None:
        """Emit the in-progress lap as incomplete (e.g. session ended mid-lap)."""
        if self._cur is not None and self._cur.rows:
            self._cur.flags.add(LapFlag.INCOMPLETE)
            self._finalise(self._cur, None)
        self._cur = None
