"""Unified, game-independent telemetry model.

Three representations with different update rates:

* ``CarFrame``      - high-frequency (10-60 Hz) state of the player's car.
* ``SessionInfo``   - slow-changing session/track/conditions/rules state (~2 Hz).
* ``GameEvent``     - discrete events (session start, flashback, penalty, ...).
* ``FieldSample``   - decimated (<= 10 Hz per car) samples of the *other* cars, from games that report the whole
  field (F1); input of the field model (track knowledge layer L0b).
* ``RaceTiming`` / ``TyreSetsInfo`` - race strategy inputs (F1): every car's position, gaps and pit state at
  <= 2 Hz, and the player's tyre sets on change; consumed by ``pitwall.strategy`` off the ingest thread.

Conventions (every adapter MUST normalise to these):

* SI-ish units are encoded in the field name (``_kph``, ``_m``, ``_ms``, ``_c``, ``_psi``, ``_kg``...).
* Pedals are 0..1. Steering is -1 (full left lock) .. +1 (full right lock).
* Gear: -1 reverse, 0 neutral, 1..n forward.
* Wheel quantities use ``Wheels`` in FL, FR, RL, RR order regardless of the game's native order.
* World position is in the game's own coordinate system (metres). Axes and handedness differ per game;
  the adapter declares which two axes form the ground plane via ``AdapterInfo.ground_plane``.
* ``None`` means "not provided by this game/platform/packet" or "not yet received". Adapters must never
  fabricate a value to satisfy the interface.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import IntFlag, StrEnum
from typing import Any


class Game(StrEnum):
    F1_25 = "f1_25"
    F1_24 = "f1_24"
    GT7 = "gt7"
    FORZA_MOTORSPORT = "forza_motorsport"
    FORZA_HORIZON = "forza_horizon"
    ACC = "acc"
    AC = "ac"
    IRACING = "iracing"
    SYNTHETIC = "synthetic"
    UNKNOWN = "unknown"


class Platform(StrEnum):
    PC = "pc"
    PS5 = "ps5"
    PS4 = "ps4"
    XBOX = "xbox"
    UNKNOWN = "unknown"


@dataclass(slots=True, frozen=True)
class Wheels[T]:
    """Per-wheel values, always in FL, FR, RL, RR order."""

    fl: T
    fr: T
    rl: T
    rr: T

    def as_tuple(self) -> tuple[T, T, T, T]:
        return (self.fl, self.fr, self.rl, self.rr)

    @classmethod
    def from_rl_rr_fl_fr(cls, seq: tuple[T, ...] | list[T]) -> Wheels[T]:
        """Build from the RL, RR, FL, FR order used by the EA F1 UDP protocol."""
        rl, rr, fl, fr = seq[0], seq[1], seq[2], seq[3]
        return cls(fl=fl, fr=fr, rl=rl, rr=rr)

    @classmethod
    def from_fl_fr_rl_rr(cls, seq: tuple[T, ...] | list[T]) -> Wheels[T]:
        return cls(fl=seq[0], fr=seq[1], rl=seq[2], rr=seq[3])


class FrameQuality(IntFlag):
    """Data-quality flags attached to each frame."""

    OK = 0
    STALE_POSITION = 1 << 0  # motion data older than the telemetry it was merged with
    STALE_LAP_DATA = 1 << 1  # lap data older than the telemetry it was merged with
    PAUSED = 1 << 2  # game reports paused / not on track
    REPLAY_OR_SPECTATING = 1 << 3  # player is not driving (spectating, replay)
    FLASHBACK_SEGMENT = 1 << 4  # frame lies in a section rewound by a flashback
    DECODE_WARNING = 1 << 5
    NOT_RACING = 1 << 6  # in the garage, or finished/retired (cool-down lap): not part of any timed lap


@dataclass(slots=True, kw_only=True)
class CarFrame:
    """One high-frequency sample of the player's car. See module docstring for conventions."""

    # --- provenance / timing -------------------------------------------------------------
    game: Game
    t_recv_ns: int  # host monotonic clock (ns) when the source packet was received
    session_time_s: float | None = None  # game session clock (s)
    frame_id: int | None = None  # game frame counter, when provided
    quality: FrameQuality = FrameQuality.OK

    # --- driver inputs ---------------------------------------------------------------------
    throttle: float | None = None  # 0..1
    brake: float | None = None  # 0..1
    steering: float | None = None  # -1 left .. +1 right (normalised wheel input, not road-wheel angle)
    clutch: float | None = None  # 0..1

    # --- powertrain --------------------------------------------------------------------------
    speed_kph: float | None = None
    gear: int | None = None  # -1 R, 0 N, 1..n
    rpm: float | None = None
    max_rpm: float | None = None
    drs_open: bool | None = None
    ers_store_j: float | None = None
    ers_deploy_mode: int | None = None  # game-specific enum, documented by adapter

    # --- motion (world frame, game coordinates) --------------------------------------------------
    pos_x_m: float | None = None
    pos_y_m: float | None = None
    pos_z_m: float | None = None
    vel_x_mps: float | None = None
    vel_y_mps: float | None = None
    vel_z_mps: float | None = None
    g_lat: float | None = None  # lateral g (sign per game; see adapter docs)
    g_lon: float | None = None  # longitudinal g (+ accelerating, - braking)
    g_vert: float | None = None
    yaw_rad: float | None = None
    pitch_rad: float | None = None
    roll_rad: float | None = None
    # --- feat/technique: chassis dynamics (F1 MotionEx). None = not sent by this game / packet, or stale ---
    yaw_rate_rps: float | None = None  # + = rotating clockwise seen from above (turning right): same sign as steering
    body_slip_rad: float | None = None  # angle between heading and direction of travel (sign per adapter; use |x|)
    wheel_slip_ratio: Wheels[float] | None = None  # (wheel - car speed) / car speed: < 0 braking (-1 locked), > 0 spin
    wheel_slip_angle_rad: Wheels[float] | None = None  # per wheel; sign per adapter docs (analysis uses magnitudes)
    # --- end feat/technique ---

    # --- lap -----------------------------------------------------------------------------------
    lap_number: int | None = None  # current lap, 1-based
    lap_distance_m: float | None = None  # distance along current lap (can be < 0 before first line crossing)
    total_distance_m: float | None = None
    current_lap_time_ms: int | None = None
    last_lap_time_ms: int | None = None
    sector: int | None = None  # 0-based
    lap_invalid: bool | None = None
    pit_status: int | None = None  # 0 none, 1 pitting/in pit lane, 2 in pit area
    race_position: int | None = None

    # --- tyres / brakes ----------------------------------------------------------------------------
    tyre_surface_temp_c: Wheels[float] | None = None
    tyre_inner_temp_c: Wheels[float] | None = None
    tyre_pressure_psi: Wheels[float] | None = None
    brake_temp_c: Wheels[float] | None = None
    tyre_wear_pct: Wheels[float] | None = None  # 0 = new, 100 = fully worn
    tyre_compound: str | None = None  # normalised label, e.g. "soft", "medium", "hard", "inter", "wet"
    tyre_age_laps: int | None = None

    # --- fuel ---------------------------------------------------------------------------------------
    fuel_kg: float | None = None
    fuel_litres: float | None = None
    fuel_capacity_kg: float | None = None
    fuel_capacity_litres: float | None = None
    fuel_remaining_laps_game: float | None = None  # the game's own estimate, if provided

    # --- assists / setup snapshot --------------------------------------------------------------------
    brake_bias_front_pct: float | None = None
    traction_control: int | None = None
    abs_active: bool | None = None


class SessionType(StrEnum):
    PRACTICE = "practice"
    QUALIFYING = "qualifying"
    RACE = "race"
    TIME_TRIAL = "time_trial"
    UNKNOWN = "unknown"


@dataclass(slots=True, kw_only=True)
class Weather:
    condition: str | None = None  # "clear", "light_cloud", "overcast", "light_rain", "heavy_rain", "storm"
    track_temp_c: float | None = None
    air_temp_c: float | None = None
    rain_percentage: float | None = None


type FracZone = tuple[float, float]  # (start, end) lap fractions 0..1; end < start = the zone runs through the line


@dataclass(slots=True, frozen=True)
class MarshalZone:
    """One marshal zone as the game reports it.

    Games send only the *start* of each zone; a zone runs until the next zone's start in lap order, so the zone
    that contains the start/finish line wraps (real F1 25 Austria: zone 0 starts at 0.9908 of the lap).
    """

    start_frac: float  # fraction 0..1 of the lap where the zone starts
    flag: str | None = None  # "none" | "green" | "blue" | "yellow"; None = invalid/unknown (live state)


@dataclass(slots=True, frozen=True, kw_only=True)
class TrackZones:
    """Game-native track skeleton (layer L0a): sector starts and zone tables exactly as the game reports them.

    Values are the game's own, unsorted and unconverted; ``pitwall.analysis.track_skeleton`` sorts them, converts
    fractions to metres (fraction x ``SessionInfo.track_length_m``) and handles zones that run through the line.

    ``None`` means "not reported" (by this game, this wire format, or not yet in this session), which is different
    from an empty tuple ("the game reported zero zones"). Example: F1 UDP format 2025 has no DRS/active-aero tables,
    so those stay ``None`` - never an empty list presented as fact.
    """

    source: str | None = None  # provenance, e.g. "f1_session@2025"
    sector2_start_m: float | None = None  # lap distance where sector 2 starts
    sector3_start_m: float | None = None
    marshal_zones: tuple[MarshalZone, ...] | None = None  # game array order (unsorted; may wrap)
    drs_zones_frac: tuple[FracZone, ...] | None = None
    aero_full_zones_frac: tuple[FracZone, ...] | None = None  # active aero, "full" track status zones
    aero_partial_zones_frac: tuple[FracZone, ...] | None = None  # active aero, "partial" track status zones
    active_aero_track_status: str | None = None  # "full" | "partial"

    def geometry_key(self) -> tuple[Any, ...]:
        """Hashable identity of the static geometry, excluding live marshal flags (for change detection)."""
        return (
            self.source,
            self.sector2_start_m,
            self.sector3_start_m,
            None if self.marshal_zones is None else tuple(z.start_frac for z in self.marshal_zones),
            self.drs_zones_frac,
            self.aero_full_zones_frac,
            self.aero_partial_zones_frac,
            self.active_aero_track_status,
        )

    def without_flags(self) -> TrackZones:
        """The static geometry only: every marshal flag set to ``None`` (unknown).

        Marshal flags are live state that the game refreshes every 0.5 s. A copy persisted with the session (which
        is rewritten whenever other session info changes) would freeze one arbitrary moment, e.g. a yellow that
        lasted seconds, and later read as a fact about the whole session. Persist ``without_flags().to_dict()``.
        """
        if not self.marshal_zones or all(z.flag is None for z in self.marshal_zones):
            return self
        return replace(self, marshal_zones=tuple(MarshalZone(start_frac=z.start_frac) for z in self.marshal_zones))

    def to_dict(self) -> dict[str, Any]:
        """Strict-JSON-safe dict (non-finite floats become ``None``); inverse of ``from_dict``."""

        def pairs(zs: tuple[FracZone, ...] | None) -> list[list[float | None]] | None:
            return None if zs is None else [[_finite(a), _finite(b)] for a, b in zs]

        return {
            "source": self.source,
            "sector2_start_m": _finite(self.sector2_start_m),
            "sector3_start_m": _finite(self.sector3_start_m),
            "marshal_zones": None
            if self.marshal_zones is None
            else [{"start_frac": _finite(z.start_frac), "flag": z.flag} for z in self.marshal_zones],
            "drs_zones_frac": pairs(self.drs_zones_frac),
            "aero_full_zones_frac": pairs(self.aero_full_zones_frac),
            "aero_partial_zones_frac": pairs(self.aero_partial_zones_frac),
            "active_aero_track_status": self.active_aero_track_status,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any] | None) -> TrackZones | None:
        """Tolerant inverse of ``to_dict`` for stored rows: malformed entries are skipped, missing keys stay None."""
        if not isinstance(d, Mapping):
            return None

        def num(v: Any) -> float | None:
            return float(v) if isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) else None

        def pairs(v: Any) -> tuple[FracZone, ...] | None:
            if not isinstance(v, list | tuple):
                return None
            out: list[FracZone] = []
            for p in v:
                if isinstance(p, list | tuple) and len(p) == 2:
                    a, b = num(p[0]), num(p[1])
                    if a is not None and b is not None:
                        out.append((a, b))
            return tuple(out)

        marshal: tuple[MarshalZone, ...] | None = None
        raw = d.get("marshal_zones")
        if isinstance(raw, list | tuple):
            zones: list[MarshalZone] = []
            for z in raw:
                start = num(z.get("start_frac")) if isinstance(z, Mapping) else None
                if start is not None:
                    flag = z.get("flag")
                    zones.append(MarshalZone(start_frac=start, flag=flag if isinstance(flag, str) else None))
            marshal = tuple(zones)
        source, status = d.get("source"), d.get("active_aero_track_status")
        return cls(
            source=source if isinstance(source, str) else None,
            sector2_start_m=num(d.get("sector2_start_m")),
            sector3_start_m=num(d.get("sector3_start_m")),
            marshal_zones=marshal,
            drs_zones_frac=pairs(d.get("drs_zones_frac")),
            aero_full_zones_frac=pairs(d.get("aero_full_zones_frac")),
            aero_partial_zones_frac=pairs(d.get("aero_partial_zones_frac")),
            active_aero_track_status=status if isinstance(status, str) else None,
        )


def _finite(v: float | None) -> float | None:
    return v if v is not None and math.isfinite(v) else None


@dataclass(slots=True, kw_only=True)
class SessionInfo:
    """Slow-changing session context. Fields are ``None`` until the game has reported them."""

    game: Game
    t_recv_ns: int = 0
    platform: Platform = Platform.UNKNOWN
    session_uid: str | None = None
    track_id: str | None = None  # stable game-scoped identifier, e.g. "f1:10" (Spa)
    track_name: str | None = None
    track_length_m: float | None = None
    session_type: SessionType = SessionType.UNKNOWN
    session_type_raw: str | None = None
    total_laps: int | None = None
    session_time_left_s: float | None = None
    car_id: str | None = None  # stable game-scoped identifier for car/team
    car_name: str | None = None
    weather: Weather = field(default_factory=Weather)
    assists: dict[str, Any] = field(default_factory=dict)  # game-specific assist settings
    pit_speed_limit_kph: float | None = None
    safety_car_status: str | None = None
    formula: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    # Typed game-native skeleton (sectors, marshal/DRS/aero zones). Kept last with a default so adapters that build
    # SessionInfo by keyword are unaffected. None = this game/adapter does not report a skeleton.
    track_zones: TrackZones | None = None
    # Game AI difficulty 0-110 (F1 Session.aiDifficulty); None = not (yet) reported or out of the spec's range.
    # F1 25 sends an unfilled Session tail for the first ~1.5 s of every session (aiDifficulty 0, gearboxAssist 0):
    # the adapter reports None then, never that 0.
    ai_difficulty: int | None = None
    session_time_s: float | None = None  # game session clock of the packet (F1 header sessionTime)
    network_game: bool | None = None  # F1 Session.networkGame (0 offline / 1 online); None = unknown


class EventKind(StrEnum):
    SESSION_STARTED = "session_started"
    SESSION_ENDED = "session_ended"
    LAP_COMPLETED = "lap_completed"
    FASTEST_LAP = "fastest_lap"
    FLASHBACK = "flashback"
    PENALTY = "penalty"
    PIT_ENTRY = "pit_entry"
    PIT_EXIT = "pit_exit"
    SAFETY_CAR = "safety_car"
    RED_FLAG = "red_flag"
    CHEQUERED_FLAG = "chequered_flag"
    LIGHTS_OUT = "lights_out"
    COLLISION = "collision"
    BUTTON = "button"
    OTHER = "other"


@dataclass(slots=True, kw_only=True)
class GameEvent:
    kind: EventKind
    game: Game
    t_recv_ns: int
    session_time_s: float | None = None
    code: str | None = None  # raw game event code
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, kw_only=True)
class SetupParameter:
    key: str  # normalised key, e.g. "front_wing", "brake_bias", "front_arb"
    value: float
    unit: str | None = None
    label: str | None = None
    min_value: float | None = None
    max_value: float | None = None


@dataclass(slots=True, kw_only=True)
class CarSetup:
    game: Game
    t_recv_ns: int
    car_id: str | None
    track_id: str | None
    parameters: dict[str, SetupParameter] = field(default_factory=dict)

    def fingerprint(self) -> str:
        """Stable string identifying this exact setup (used for reference-lap compatibility)."""
        items = sorted((k, round(p.value, 4)) for k, p in self.parameters.items())
        return ";".join(f"{k}={v}" for k, v in items)


@dataclass(slots=True, kw_only=True)
class LapCompletion:
    """Emitted by an adapter when the game reports that a lap was completed."""

    game: Game
    t_recv_ns: int
    lap_number: int  # the lap that was just completed
    lap_time_ms: int | None
    sector_times_ms: list[int | None] = field(default_factory=list)
    valid: bool | None = None
    session_time_s: float | None = None


@dataclass(slots=True, kw_only=True)
class FieldSample:
    """One decimated sample of one car of the session's *field* (layer L0b: learn the track from the other cars).

    Emitted only by adapters whose game reports every car (F1: Motion, LapData and CarTelemetry carry all slots),
    at most ``field_hz`` per car (default 10 Hz, see the adapter), and only for cars that are racing: never for a
    car in the garage or whose result is not active. Cars in the pit lane are sent (``pit_status`` != 0) so the
    field model can drop the lap that led into the pit. The player's own car is left out by default: it already
    streams full-rate ``CarFrame``s and is learned from its own laps (layer L3).

    Same conventions as ``CarFrame`` (units in field names, pedals 0..1, steering -1..+1, game world frame).
    ``driver_status`` / ``result_status`` are normalised labels; a raw value the game's spec does not define becomes
    ``None``. Field samples are never persisted; ``pitwall.analysis.field_model`` consumes them off the ingest thread
    and labels everything it learns ``tier="field_observed"`` (an AI reference, never the driver's target).
    """

    game: Game
    t_recv_ns: int
    session_time_s: float
    frame_id: int
    car_index: int
    ai_controlled: bool | None  # None until the game has said (F1: Participants packet, every 5 s)
    lap_number: int
    lap_distance_m: float  # can be < 0 before the car's first line crossing
    pos_x_m: float
    pos_y_m: float
    pos_z_m: float
    speed_kph: float
    throttle: float
    brake: float
    steering: float
    gear: int
    sector: int  # 0-based
    lap_invalid: bool
    pit_status: int  # same convention as CarFrame.pit_status: 0 none, 1 pitting / in pit lane, 2 in pit area
    driver_status: str | None  # "garage" | "flying_lap" | "in_lap" | "out_lap" | "on_track"
    result_status: str | None  # "active" | "finished" | "dnf" | "dsq" | "not_classified" | "retired" | ...
    g_lon: float | None = None  # longitudinal g (+ accelerating, - braking)
    gap_ahead_ms: int | None = None  # time gap to the car in front; None = no car in front or not reported
    safety_car: bool | None = None  # any safety car / VSC / formation lap in the session; None = not yet known


@dataclass(slots=True, frozen=True)
class HistoryLap:
    """One lap of a car's lap list as the game reports it (F1: Session History ``LapHistoryData``)."""

    lap_number: int  # 1-based
    lap_time_ms: int | None  # None = not complete (0 on the wire)
    sector_times_ms: tuple[int | None, int | None, int | None]  # None = not set; all None while the lap is incomplete
    valid: bool | None  # lapValidBitFlags & 0x01; None while incomplete
    # Game session time (header sessionTime) of the first packet that showed this lap time; set again when the time
    # changes, None while the lap is incomplete. Pitwall's own observation, not a game field: the timing check of
    # ``analysis.ai_pace`` compares the gap between consecutive completions with the lap time.
    completed_session_time_s: float | None


@dataclass(slots=True, frozen=True, kw_only=True)
class CarLapHistory:
    """The game's own lap list for one car (F1: Session History, packet ID 11). Emitted only when it changed.

    Input of the AI pace comparison (``core.ai_pace``): never persisted as such, never starts a session. Human
    opponents (``ai_controlled`` False) and cars whose control is unknown are never used for AI statistics.
    """

    game: Game
    t_recv_ns: int
    session_time_s: float
    session_uid: str | None
    car_index: int
    ai_controlled: bool | None  # True = AI; False = human; None = unknown (no Participants packet yet / empty slot)
    is_player: bool
    first_seen_lap: int  # numLaps of the first packet seen for this car: laps <= it were NOT observed from their start
    laps: tuple[HistoryLap, ...]  # laps 1..numLaps (the last one usually in progress)
    # In- and out-laps: e+1 and e+2 for each tyre-stint endLap e <= 254 (real F1 25 records the lap before the in-lap;
    # 255 = the tyre fitted now), plus every lap LapData showed the car in the pit lane.
    pit_laps: frozenset[int]
    best_lap_number: int | None  # bestLapTimeLapNum; 0 -> None
    # Laps <= this were not (entirely) driven by the AI: the car was seen not AI-controlled (a human, e.g. in an online
    # lobby) and the AI took it over while this lap was in progress. 0 = AI whenever seen.
    ai_from_lap: int = 0
    # The lap the game ended for this car before it reached the line (LapData: its result left "active" away from the
    # line, i.e. the driver skipped to the results or the car retired): this lap's time, and any later one, was filled
    # in by the game, not driven. None = not seen.
    ended_lap: int | None = None


# --- race strategy inputs (pitwall.strategy) ---------------------------------------------------------------------
@dataclass(slots=True, frozen=True, kw_only=True)
class CarTiming:
    """One car's race timing as the game reports it (F1: LapData of every car, plus CarStatus tyre fields).

    Values the game marks as "not set" are ``None`` (gap 0, grid 0, lap time 0, a lane time while the lane timer is
    off). A gap whose milliseconds part is 60000 or more is a negative delta wrapped into the uint16 (real F1 25 Monza:
    65403 = -133 ms) and is ``None`` too: unknown, never a 65 s gap.
    """

    car_index: int
    is_player: bool
    ai_controlled: bool | None
    position: int  # LapData.carPosition
    grid_position: int | None  # gridPosition; 0 -> None (no grid slot)
    lap_number: int
    lap_distance_m: float
    sector: int
    last_lap_ms: int | None  # lastLapTimeInMS; 0 -> None
    gap_ahead_ms: int | None  # deltaToCarInFront (minutes*60000 + ms); None if not reported or wrapped negative
    gap_leader_ms: int | None  # deltaToRaceLeader, same rules
    pit_status: int  # 0 none, 1 pitting / in the pit lane, 2 in the pit area
    num_pit_stops: int
    pit_lane_timer_active: bool
    pit_lane_time_ms: int | None  # pitLaneTimeInLaneInMS, only while the timer is active
    pit_stop_timer_ms: int | None  # pitStopTimerInMS; 0 -> None
    serve_penalty: bool  # pitStopShouldServePen
    driver_status: str | None  # adapter DRIVER_STATUS labels
    result_status: str | None  # adapter RESULT_STATUS labels
    lap_invalid: bool
    tyre_visual: str | None = None  # CarStatus.visualTyreCompound (enums.VISUAL_COMPOUNDS)
    tyre_age_laps: int | None = None  # CarStatus.tyresAgeLaps (None before the first CarStatus packet)


@dataclass(slots=True, frozen=True, kw_only=True)
class RaceTiming:
    """Every racing car's timing at one moment (decimated to <= 2 Hz of game clock). Input of ``pitwall.strategy``,
    which runs it off the ingest thread; never persisted as such."""

    game: Game
    t_recv_ns: int
    session_time_s: float
    frame_id: int
    player_index: int
    cars: tuple[CarTiming, ...]  # every car whose result status is active or later (>= 2), in car-index order


@dataclass(slots=True, frozen=True, kw_only=True)
class TyreSet:
    """One tyre set of the player's allocation (F1 TyreSets packet). Lap figures are the game's own estimates."""

    index: int
    actual: str | None
    visual: str | None
    wear_pct: int
    available: bool
    recommended_session: int
    life_span_laps: int  # "laps left in this tyre set" (game)
    usable_life_laps: int  # "max number of laps recommended for this compound" (game)
    lap_delta_ms: int  # lap time delta versus the fitted set (game estimate)
    fitted: bool


@dataclass(slots=True, frozen=True, kw_only=True)
class TyreSetsInfo:
    """The player's tyre sets, emitted only when they change (wear, availability, life or lap deltas)."""

    game: Game
    t_recv_ns: int
    session_time_s: float
    car_index: int
    sets: tuple[TyreSet, ...]
    fitted_index: int | None  # m_fittedIdx; an index past the array -> None


# Union of everything an adapter can emit after decoding one packet.
type Emitted = (
    CarFrame
    | SessionInfo
    | GameEvent
    | CarSetup
    | LapCompletion
    | FieldSample
    | CarLapHistory
    | RaceTiming
    | TyreSetsInfo
)
