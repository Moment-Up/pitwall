"""EA SPORTS F1 25 adapter: validates, decodes and normalises UDP packets into the unified model.

Merging strategy: the game sends Motion, LapData, CarTelemetry, CarStatus... as separate packets that
share a ``frameIdentifier``. A ``CarFrame`` is emitted on every CarTelemetry packet (the driver-input
packet), merged with the most recent Motion/LapData/Status/Damage for the player car. If those are from an
older frame the corresponding ``STALE_*`` quality flag is set, so analysis can account for it.
"""

from __future__ import annotations

import logging
import math
import struct
from collections.abc import Sequence
from typing import Any

from pitwall.adapters.base import AdapterInfo, DecodeStats, FieldSupport, PacketRejected, SupportLevel
from pitwall.adapters.f1 import enums
from pitwall.adapters.f1 import packets as P
from pitwall.adapters.structdef import StructDef
from pitwall.model.telemetry import (
    CarDamage,
    CarFrame,
    CarLapHistory,
    CarPenalties,
    CarSetup,
    CarTiming,
    Emitted,
    EventKind,
    FieldMotion,
    FieldSample,
    FracZone,
    FrameQuality,
    Game,
    GameEvent,
    HistoryLap,
    LapCompletion,
    MarshalZone,
    Participant,
    Participants,
    Platform,
    RaceTiming,
    SessionInfo,
    SessionType,
    SetupParameter,
    TimeTrialDataSet,
    TimeTrialInfo,
    TrackZones,
    TyreSet,
    TyreSetsInfo,
    Weather,
    Wheels,
)

log = logging.getLogger(__name__)

_S = SupportLevel.SPEC_IMPLEMENTED
_U = SupportLevel.UNSUPPORTED

F1_25_INFO = AdapterInfo(
    game=Game.F1_25,
    name="EA SPORTS F1 25 (UDP formats 2025 and 2026)",
    transport="udp",
    default_port=20777,
    ground_plane=("pos_x_m", "pos_z_m"),  # F1 world is Y-up
    platforms={
        Platform.PC: SupportLevel.SPEC_IMPLEMENTED,
        Platform.PS5: SupportLevel.LIVE_VALIDATED,  # format 2025, F1 25 v1.26 (2026-10-10)
        Platform.XBOX: SupportLevel.SPEC_IMPLEMENTED,
    },
    fields={
        "speed_kph": FieldSupport(_S, "CarTelemetry.speed (uint16 km/h)"),
        "throttle": FieldSupport(_S, "CarTelemetry.throttle (0..1)"),
        "brake": FieldSupport(_S, "CarTelemetry.brake (0..1)"),
        "steering": FieldSupport(_S, "CarTelemetry.steer (-1 left..+1 right)"),
        "clutch": FieldSupport(_S, "CarTelemetry.clutch (0..100 -> 0..1)"),
        "gear": FieldSupport(_S, "CarTelemetry.gear (-1 R, 0 N, 1..8)"),
        "rpm": FieldSupport(_S, "CarTelemetry.engineRPM"),
        "max_rpm": FieldSupport(_S, "CarStatus.maxRPM"),
        "drs_open": FieldSupport(_S, "CarTelemetry.drs"),
        "drs_allowed": FieldSupport(_S, "CarStatus.drsAllowed (0 not allowed, 1 allowed)"),
        "drs_activation_m": FieldSupport(
            _S, "CarStatus.drsActivationDistance (m until DRS is available; 0 = not available -> None)"
        ),
        "ers_store_j": FieldSupport(_S, "CarStatus.ersStoreEnergy (J)"),
        "pos_x_m": FieldSupport(_S, "Motion.worldPositionX (m)"),
        "pos_y_m": FieldSupport(_S, "Motion.worldPositionY (m, up axis)"),
        "pos_z_m": FieldSupport(_S, "Motion.worldPositionZ (m)"),
        "vel_x_mps": FieldSupport(_S, "Motion.worldVelocityX"),
        "g_lat": FieldSupport(_S, "Motion.gForceLateral (sign convention not documented by EA)"),
        "g_lon": FieldSupport(_S, "Motion.gForceLongitudinal"),
        "yaw_rad": FieldSupport(_S, "Motion.yaw (rad)"),
        "lap_number": FieldSupport(_S, "LapData.currentLapNum"),
        "lap_distance_m": FieldSupport(_S, "LapData.lapDistance (m; negative before first line crossing)"),
        "current_lap_time_ms": FieldSupport(_S, "LapData.currentLapTimeInMS"),
        "sector": FieldSupport(_S, "LapData.sector (0-based)"),
        "lap_invalid": FieldSupport(_S, "LapData.currentLapInvalid"),
        "pit_status": FieldSupport(_S, "LapData.pitStatus"),
        "race_position": FieldSupport(_S, "LapData.carPosition"),
        "tyre_surface_temp_c": FieldSupport(_S, "CarTelemetry.tyresSurfaceTemperature (RL,RR,FL,FR -> FL..RR)"),
        "tyre_inner_temp_c": FieldSupport(_S, "CarTelemetry.tyresInnerTemperature"),
        "tyre_pressure_psi": FieldSupport(_S, "CarTelemetry.tyresPressure (psi)"),
        "brake_temp_c": FieldSupport(_S, "CarTelemetry.brakesTemperature"),
        # --- health lane ---
        "engine_temp_c": FieldSupport(
            _S, "CarTelemetry.engineTemperature (°C; uint16 2025, uint8 2026); PS5 103–132 °C on recorded races"
        ),
        "tyre_wear_pct": FieldSupport(_S, "CarDamage.tyresWear (%)"),
        "tyre_compound": FieldSupport(_S, "CarStatus.visualTyreCompound"),
        "tyre_age_laps": FieldSupport(_S, "CarStatus.tyresAgeLaps"),
        "fuel_kg": FieldSupport(_S, "CarStatus.fuelInTank (kg)"),
        "fuel_capacity_kg": FieldSupport(_S, "CarStatus.fuelCapacity (kg)"),
        "fuel_remaining_laps_game": FieldSupport(_S, "CarStatus.fuelRemainingLaps (game estimate)"),
        "fuel_litres": FieldSupport(_U, "F1 reports fuel mass (kg) only"),
        "brake_bias_front_pct": FieldSupport(_S, "CarStatus.frontBrakeBias (%)"),
        "traction_control": FieldSupport(_S, "CarStatus.tractionControl (0 off, 1 medium, 2 full)"),
        "abs_active": FieldSupport(_S, "CarStatus.antiLockBrakes (assist enabled, not ABS intervention)"),
        "setup": FieldSupport(_S, "CarSetups (player car; other cars' setups are hidden online)"),
        "weather": FieldSupport(_S, "Session.weather/trackTemperature/airTemperature + forecast"),
        "session_type": FieldSupport(_S, "Session.sessionType (enums.SESSION_TYPES)"),
        "buttons": FieldSupport(_S, "Event BUTN buttonStatus (UDP Action 1-12 bit flags)"),
        "track_zones": FieldSupport(
            _S, "Session sector 2/3 starts (m) + MarshalZone[21]; format 2026 adds DRS and active-aero zones"
        ),
        # --- feat/technique: MotionEx (packet 13), player car only ---
        "yaw_rate_rps": FieldSupport(
            _S,
            "-MotionEx.angularVelocityY (rad/s; game sign is + for left turns, flipped so + = right like steering); "
            "units/sign checked on the recorded PS5 Monza excerpt (tests/recorded/test_technique_recorded.py)",
        ),
        "body_slip_rad": FieldSupport(
            _S,
            "MotionEx.chassisYaw (rad, = atan2(localVelocityX, localVelocityZ)); units/sign checked on the recorded "
            "PS5 Monza excerpt (tests/recorded/test_technique_recorded.py)",
        ),
        "wheel_slip_ratio": FieldSupport(
            _S,
            "MotionEx.wheelSlipRatio (RL,RR,FL,FR -> FL..RR; unitless, < 0 braking, > 0 wheelspin; EA states no "
            "unit); units/sign checked on the recorded PS5 Monza excerpt (tests/recorded/test_technique_recorded.py)",
        ),
        "wheel_slip_angle_rad": FieldSupport(
            _S,
            "MotionEx.wheelSlipAngle (RL,RR,FL,FR -> FL..RR; rad, EA states no unit); units/sign checked on the "
            "recorded PS5 Monza excerpt (tests/recorded/test_technique_recorded.py)",
        ),
        # --- end feat/technique ---
        "field_samples": FieldSupport(
            SupportLevel.RECORDED_VALIDATED,
            "Motion + LapData + CarTelemetry of every racing car, <= 10 Hz per car (FieldSample). Recorded: real PS5 "
            "format 2025 races (Austria, Austria Reverse, Silverstone, Silverstone Reverse, Monza, Montreal, Las "
            "Vegas, Miami, Melbourne): 16-19 AI cars with analog brake and full-lap distance; AI pit stops seen in "
            "the pit lane (Austria, 2 stops); format 2026 synthetic only",
        ),
        "ai_difficulty": FieldSupport(
            SupportLevel.RECORDED_VALIDATED,
            "Session.aiDifficulty; real PS5 F1 25 values 31/35/41 (offline and online lobby); the first ~1.5 s of "
            "every session has an unfilled tail (gearboxAssist 0) and is ignored; time trial unverified; format 2026 "
            "spec-only",
        ),
        "lap_history": FieldSupport(
            SupportLevel.RECORDED_VALIDATED,
            "Session History lap times equal LapData last-lap times on 4 real races; F1 25 fills in remaining cars' "
            "final laps when the driver skips to results (detected from all-car LapData: finished away from the "
            "line; timing as a backstop); stint endLap = the lap before the in-lap (2 real AI stops)",
        ),
        # --- race strategy (pitwall.strategy) ---
        "race_timing": FieldSupport(
            _S,
            "LapData of every car (position, gaps to car in front and leader, pit status/stops, pit-lane timer) + "
            "CarStatus visual compound/age, <= 2 Hz plus one at every pit-status change (RaceTiming); decoded on "
            "recorded PS5 races",
        ),
        "tyre_sets": FieldSupport(
            _S, "TyreSets (ID 12), player car: wear, laps left, usable life, lap delta vs fitted (game estimates)"
        ),
        # --- race radio (pitwall.raceradio) ---
        "damage": FieldSupport(
            _S,
            "CarDamage: wings, floor, diffuser, sidepod, gearbox, engine, brakes, tyre damage, DRS/ERS faults, engine "
            "blown/seized (player car; RL,RR,FL,FR -> FL..RR); decoded on recorded PS5 races",
        ),
        "fia_flags": FieldSupport(_S, "CarStatus.vehicleFIAFlags (player car; -1 and undocumented values -> None)"),
        "penalties": FieldSupport(
            _S, "LapData penalties, warnings, corner-cutting warnings, unserved drive-throughs/stop-gos (player car)"
        ),
        "participants": FieldSupport(
            _S, "Participants: AI flag, driverId, team, race number of every car (names: never stored or logged)"
        ),
        # --- end race radio ---
        # --- spotter ---
        "field_motion": FieldSupport(
            SupportLevel.RECORDED_VALIDATED,
            "Motion of every car at the menu send rate: position, velocity, forward and right unit vectors; "
            "worldRightDir = the driver's right (checked against steering on 3 PS5 captures: "
            "docs/research/f1-spotter-data.md; the committed Monza excerpt: tests/recorded/test_spotter_recorded.py); "
            "format 2026 spec only",
        ),
        # --- end spotter ---
        # --- leaderboard ---
        "time_trial": FieldSupport(
            _S,
            "Time Trial (ID 14, 1 Hz, Time Trial mode only): player session best, personal best and rival datasets "
            "(lap and sector times ms, TC / gearbox / ABS on-off, equal performance, custom setup, valid) + LapData "
            "m_timeTrialPBCarIdx / m_timeTrialRivalCarIdx; spec-decoded, not yet seen in a recording",
        ),
        # --- end leaderboard ---
    },
    notes=(
        "Decodes UDP formats 2025 (F1 25) and 2026 (2026 Season Pack); format 2024 is rejected.",
        "Format 2026 Car Telemetry 2 (active aero / overtake mode, ID 16) is recognised but not yet used.",
        "Console (PS5/Xbox) UDP output uses the same protocol; not yet validated on real hardware.",
    ),
)


RESULT_ACTIVE = 2  # LapData.resultStatus: 0 invalid, 1 inactive, 2 active, 3 finished, 4 DNF, 5 DSQ, 6 NC, 7 retired
RESULT_FINISHED = 3
DRIVER_IN_GARAGE = 0  # LapData.driverStatus

# Normalised labels for the field model (``FieldSample``); values the spec does not define stay None.
DRIVER_STATUS: dict[int, str] = {0: "garage", 1: "flying_lap", 2: "in_lap", 3: "out_lap", 4: "on_track"}
RESULT_STATUS: dict[int, str] = {
    0: "invalid",
    1: "inactive",
    2: "active",
    3: "finished",
    4: "dnf",
    5: "dsq",
    6: "not_classified",
    7: "retired",
}

# --- field samples (layer L0b) ---------------------------------------------------------------------------------
FIELD_HZ = 10.0  # default FieldSample rate per car: enough for 5 m bins over many car-laps, cheap to decode
MAX_FIELD_HZ = 60.0
FIELD_MAX_FRAME_SKEW = 2  # Motion / LapData used for a field tick must be this close to the telemetry frame
FIELD_TICK_TOLERANCE_S = 0.005  # game clock jitter allowed when a tick falls due (a 60 Hz frame is 16.7 ms)
FIELD_REWIND_S = 0.05  # the game clock going back by more than this (flashback, restart) re-arms the tick at once
# feat/technique: MotionEx (player car only, sent at the Motion rate) merged into a CarFrame only when this close to
# the telemetry frame; older data leaves the chassis-dynamics fields None (no quality flag: they are optional extras)
MOTION_EX_MAX_FRAME_SKEW = 2
SAFETY_CAR_NONE = 0  # Session.safetyCarStatus: 0 none, 1 full, 2 virtual, 3 formation lap
SAFETY_CAR_KNOWN = frozenset({0, 1, 2, 3})

# --- AI difficulty / lap history (AI pace, core.ai_pace) --------------------------------------------------------------
AI_DIFFICULTY_MAX = 110  # Session.aiDifficulty "0-110" (spec appendix)
# Session.gearboxAssist: 1 manual, 2 manual & suggested gear, 3 auto. Real PS5 F1 25 sends 0 (not a defined value)
# together with aiDifficulty 0 in the first 2-3 Session packets of every session, before the tail is filled in.
GEARBOX_ASSIST_DEFINED = frozenset({1, 2, 3})
NETWORK_GAME: dict[int, bool] = {0: False, 1: True}
# --- health lane: Session.tyreTemperature (spec: 0 = Surface only, 1 = Surface & Carcass); another value is unknown
TYRE_TEMPERATURE_MODEL: dict[int, str] = {0: "surface", 1: "surface_and_carcass"}
LAP_VALID_BIT = 0x01  # LapHistoryData.lapValidBitFlags: 0x01 lap valid (0x02/0x04/0x08 sectors 1-3 valid)
STINT_END_CURRENT = 255  # TyreStintHistoryData.endLap of the tyre currently fitted
# Session History byte layout (spec section 5.11): head at 29, laps at 36 (stride 14), stints at 1436 (stride 3).
HIST_CAR = P.HEADER.size  # 29: m_carIdx
HIST_NUM_LAPS = HIST_CAR + 1  # 30
HIST_NUM_STINTS = HIST_CAR + 2  # 31
HIST_BEST_LAP = HIST_CAR + 3  # 32: m_bestLapTimeLapNum
HIST_LAPS = P.HEADER.size + P.SESSION_HISTORY_HEAD.size  # 36
HIST_LAP_SIZE = P.LAP_HISTORY.size  # 14
HIST_STINTS = HIST_LAPS + P.NUM_LAP_HISTORY * HIST_LAP_SIZE  # 1436
HIST_STINT_SIZE = P.TYRE_STINT_HISTORY.size  # 3
_LAP_HISTORY_STRUCT = P.LAP_HISTORY.struct


def _field_offset(sd: StructDef, name: str) -> int:
    """Byte offset of the scalar field ``name`` inside one ``sd`` element (from the spec-checked definition)."""
    fmt = sd.struct.format[0]  # endianness: no padding
    for fname, f in sd.fields:
        if fname == name:
            return struct.calcsize(fmt)
        fmt += f
    raise ValueError(f"{sd.name}: no field {name!r}")


# LapData of every car, watched for AI pace with one strided byte slice per field and packet (a C-level copy of
# 22-24 bytes, compared with the previous packet's); cars are looked at one by one only when a slice changed.
LD_SIZE = P.LAP_DATA.size
LD_RESULT = _field_offset(P.LAP_DATA, "resultStatus")
LD_PIT = _field_offset(P.LAP_DATA, "pitStatus")
LD_LAP = _field_offset(P.LAP_DATA, "currentLapNum")
LD_DIST = _field_offset(P.LAP_DATA, "lapDistance")
_F32 = struct.Struct("<f")
# A car whose result leaves "active" further than this past the line did not finish its lap on track: the game ended
# the lap in progress (the driver skipped to the results, a retirement) and fills in its time. Real F1 25 (PS5, 10 race
# finishes): a car that crosses the line flips 1-24 m past it (online lobby lag); after a skip, every remaining car
# flips one LapData packet after the player's own finish, wherever it is (up to 3.1 km from the line).
RESULT_OFF_LINE_M = 50.0

_FIELD_MOTION = ("worldPositionX", "worldPositionY", "worldPositionZ", "gForceLongitudinal")
_FIELD_LAP = (
    "deltaToCarInFrontMSPart",
    "deltaToCarInFrontMinutesPart",
    "lapDistance",
    "currentLapNum",
    "pitStatus",
    "sector",
    "currentLapInvalid",
    "driverStatus",
    "resultStatus",
)
_FIELD_TELEMETRY = ("speed", "throttle", "steer", "brake", "gear")


def subset_struct(sd: StructDef, keep: Sequence[str]) -> struct.Struct:
    """A ``struct.Struct`` over one ``sd`` element that unpacks only the scalar fields ``keep`` (in definition order)
    and skips every other byte. Built from the spec-checked ``StructDef`` itself, so its offsets cannot drift from
    the full decoder; ``iter_unpack`` over a car array then decodes all cars in one C loop (field-model hot path)."""
    wanted = set(keep)
    fmt = sd.struct.format[0]  # endianness
    for name, f in sd.fields:
        if name in wanted:
            if f[0].isdigit():
                raise ValueError(f"{sd.name}.{name}: only scalar fields can be kept, got {f!r}")
            fmt += f
            wanted.discard(name)
        else:
            fmt += f"{struct.calcsize(fmt[0] + f)}x"
    if wanted:
        raise ValueError(f"{sd.name}: no field(s) {sorted(wanted)}")
    out = struct.Struct(fmt)
    if out.size != sd.size:  # pragma: no cover - would mean calcsize and StructDef disagree
        raise AssertionError(f"{sd.name}: subset size {out.size} != {sd.size}")
    return out


class _FieldStructs:
    """Per wire format: subset structs for the three all-car arrays the field model reads."""

    __slots__ = (
        "lap",
        "max_cars",
        "motion",
        "motion_bytes",
        "participant",
        "participant_bytes",
        "telemetry",
        "telemetry_bytes",
    )

    def __init__(self, layout: P.F1Layout) -> None:
        self.max_cars = layout.max_cars
        self.motion = subset_struct(layout.car_motion, _FIELD_MOTION)
        self.lap = subset_struct(P.LAP_DATA, _FIELD_LAP)
        self.telemetry = subset_struct(layout.car_telemetry, _FIELD_TELEMETRY)
        self.participant = subset_struct(layout.participant, ("aiControlled",))
        self.motion_bytes = layout.max_cars * layout.car_motion.size
        self.telemetry_bytes = layout.max_cars * layout.car_telemetry.size
        self.participant_bytes = layout.max_cars * layout.participant.size


_FIELD_STRUCTS: dict[int, _FieldStructs] = {fmt: _FieldStructs(layout) for fmt, layout in P.LAYOUTS.items()}

# --- race strategy (pitwall.strategy) ---------------------------------------------------------------------------
TIMING_HZ = 2.0  # RaceTiming rate (game clock): gaps update every 0.3-2 s on real F1 25, so 2 Hz loses nothing
MAX_TIMING_HZ = 10.0
TIMING_GAP_WRAP_MS = 60_000  # a milliseconds part >= this is a negative delta wrapped into the uint16 (Monza: 65403)
SESSION_TYPE_TIME_TRIAL = 18  # Session.sessionType (spec 8.5)
FORMULA_F2 = 2  # Session.formula (spec 8.12): F2 cars have no ERS (the game sends 0 for them)
# a final lap in exactly the previous lap's time (``_on_lap_data``): reported after this much session time without a
# new time, if the car had been on that lap number for at least this fraction of the lap time
FINAL_TIME_GRACE_S = 1.0
FINAL_LAP_MIN_FRAC = 0.5

# (pitStatus is read with AI pace's strided LD_PIT slice: one LapData pass, see ``_on_lap_data``)
_TIMING_LAP = (
    "lastLapTimeInMS",
    "deltaToCarInFrontMSPart",
    "deltaToCarInFrontMinutesPart",
    "deltaToRaceLeaderMSPart",
    "deltaToRaceLeaderMinutesPart",
    "lapDistance",
    "carPosition",
    "currentLapNum",
    "pitStatus",
    "numPitStops",
    "sector",
    "currentLapInvalid",
    "gridPosition",
    "driverStatus",
    "resultStatus",
    "pitLaneTimerActive",
    "pitLaneTimeInLaneInMS",
    "pitStopTimerInMS",
    "pitStopShouldServePen",
)
_TIMING_STATUS = ("visualTyreCompound", "tyresAgeLaps")


class _TimingStructs:
    """Per wire format: subset structs for the all-car LapData / CarStatus arrays the race timing reads."""

    __slots__ = ("lap", "lap_bytes", "max_cars", "status", "status_bytes", "status_packet_size")

    def __init__(self, layout: P.F1Layout) -> None:
        self.max_cars = layout.max_cars
        self.lap = subset_struct(P.LAP_DATA, _TIMING_LAP)
        self.status = subset_struct(layout.car_status, _TIMING_STATUS)
        self.lap_bytes = layout.max_cars * P.LAP_DATA.size
        self.status_bytes = layout.max_cars * layout.car_status.size
        self.status_packet_size = layout.sizes[P.PacketId.CAR_STATUS]


_TIMING_STRUCTS: dict[int, _TimingStructs] = {fmt: _TimingStructs(layout) for fmt, layout in P.LAYOUTS.items()}


# --- race radio (pitwall.raceradio) -------------------------------------------------------------------------------
_DAMAGE_FROM = _field_offset(P.CAR_DAMAGE, "tyresDamage")  # 16: everything after the tyre wear floats
SHOW_ONLINE_NAMES: dict[int, bool] = {0: False, 1: True}  # ParticipantData.showOnlineNames


def _timing_gap(minutes: int, ms: int) -> int | None:
    """A LapData delta in ms; None when not reported (0) or when a negative delta wrapped into the uint16."""
    if ms >= TIMING_GAP_WRAP_MS:
        return None
    v = minutes * 60_000 + ms
    return v if v > 0 else None


# MarshalZone.m_zoneFlag (spec appendix 8.12): -1 = invalid/unknown -> None, like any value the spec does not define.
MARSHAL_ZONE_FLAGS: dict[int, str] = {0: "none", 1: "green", 2: "blue", 3: "yellow"}
ACTIVE_AERO_TRACK_STATUS: dict[int, str] = {0: "full", 1: "partial"}  # m_activeAeroTrackStatus (format 2026)


def _mins_ms(minutes: int, ms: int) -> int:
    return minutes * 60_000 + ms


def _positive_m(v: float) -> float | None:
    """A sector start of 0 (or garbage) is the zero-filled "not populated" value, never a real boundary."""
    return float(v) if math.isfinite(v) and v > 0 else None


def _frac_pairs(flat: tuple[float, ...], count: int, max_count: int) -> tuple[FracZone, ...]:
    """Regroup a flattened ``(zoneStart, zoneEnd) x N`` array, keeping only the ``count`` meaningful entries."""
    n = max(0, min(count, max_count))
    return tuple((float(flat[2 * i]), float(flat[2 * i + 1])) for i in range(n))


def _track_zones(marshal: list[dict[str, Any]], tail: dict[str, Any], packet_format: int) -> TrackZones:
    """Session packet -> typed L0a skeleton, faithful to the wire (no sorting, conversion or invented values).

    * ``numMarshalZones == 0`` stays unknown (``None``), not "no zones": every circuit has marshal zones, and the
      real PS5 Austria capture sends 0 in the first Session packets (session time 0.0) before the real 13.
    * DRS / active-aero tables exist only in the 2026 tail; format 2025 leaves them ``None``. In 2026 a count of 0
      is the game's own statement (e.g. no DRS under the 2026 rules) and is kept as an empty tuple.
    """
    has_2026_tail = "numDRSZones" in tail
    return TrackZones(
        source=f"f1_session@{packet_format}",
        sector2_start_m=_positive_m(tail["sector2LapDistanceStart"]),
        sector3_start_m=_positive_m(tail["sector3LapDistanceStart"]),
        marshal_zones=tuple(
            MarshalZone(start_frac=float(z["zoneStart"]), flag=MARSHAL_ZONE_FLAGS.get(z["zoneFlag"])) for z in marshal
        )
        or None,
        drs_zones_frac=_frac_pairs(tail["drsZones"], tail["numDRSZones"], P.NUM_DRS_ZONES) if has_2026_tail else None,
        aero_full_zones_frac=_frac_pairs(
            tail["activeAeroZonesFull"], tail["numActiveAeroZonesFull"], P.NUM_ACTIVE_AERO_ZONES
        )
        if has_2026_tail
        else None,
        aero_partial_zones_frac=_frac_pairs(
            tail["activeAeroZonesPartial"], tail["numActiveAeroZonesPartial"], P.NUM_ACTIVE_AERO_ZONES
        )
        if has_2026_tail
        else None,
        active_aero_track_status=ACTIVE_AERO_TRACK_STATUS.get(tail["activeAeroTrackStatus"]) if has_2026_tail else None,
    )


# --- leaderboard: Time Trial (packet 14, spec section 5.14) -----------------------------------------------------------
TT_FLAG: dict[int, bool] = {0: False, 1: True}  # TimeTrialDataSet assist / equal / setup / valid flags: 0 or 1
TT_TEAM_NONE = frozenset({255, 65535})  # no team (format 2025 uint8 / 2026 uint16 sentinel, as LobbyInfo's teamId)
TT_CAR_INDEX_NONE = 255  # LapData m_timeTrialPBCarIdx / m_timeTrialRivalCarIdx (and a set's m_carIdx): invalid
TT_SETS = ("player_session_best", "personal_best", "rival")  # the packet's three datasets, in wire order
# LapData's two time trial bytes follow the car array: absolute offsets per wire format (1283 / 1284 in 2025)
LAP_DATA_TAIL_OFFSET: dict[int, int] = {
    fmt: layout.sizes[P.PacketId.LAP_DATA] - P.LAP_DATA_TAIL.size for fmt, layout in P.LAYOUTS.items()
}


def tt_car_index(v: int, max_cars: int) -> int | None:
    """A time trial car index: 255 (the spec's "invalid") or anything past the car array -> None."""
    return v if v != TT_CAR_INDEX_NONE and v < max_cars else None


def _tt_dataset(d: dict[str, Any], max_cars: int) -> TimeTrialDataSet | None:
    """One ``TimeTrialDataSet`` -> model. A lap time of 0 is a set with no lap (the game zero-fills a set it has no
    lap for, e.g. no rival picked: [H], not yet seen in a recording): None, so its other zeroes (team 0 = Mercedes, the
    flags) are never reported as facts."""
    lap = d["lapTimeInMS"]
    if not lap:
        return None
    team = d["teamId"]
    team_id = None if team in TT_TEAM_NONE else team
    return TimeTrialDataSet(
        car_index=tt_car_index(d["carIdx"], max_cars),
        team_id=team_id,
        car_id=None if team_id is None else f"f1:team:{team_id}",
        car_name=None if team_id is None else enums.team_name(team_id),
        lap_time_ms=lap,
        sector_times_ms=(d["sector1TimeInMS"] or None, d["sector2TimeInMS"] or None, d["sector3TimeInMS"] or None),
        traction_control=TT_FLAG.get(d["tractionControl"]),
        gearbox_assist=TT_FLAG.get(d["gearboxAssist"]),
        anti_lock_brakes=TT_FLAG.get(d["antiLockBrakes"]),
        equal_car_performance=TT_FLAG.get(d["equalCarPerformance"]),
        custom_setup=TT_FLAG.get(d["customSetup"]),
        valid=TT_FLAG.get(d["valid"]),
    )


def decode_time_trial_sets(data: bytes, layout: P.F1Layout) -> tuple[TimeTrialDataSet | None, ...]:
    """The three datasets of a whole Time Trial packet (header included), in wire order (``TT_SETS``). Pure: also
    used by ``tt_check``."""
    tt = layout.time_trial
    return tuple(
        _tt_dataset(tt.unpack_from(data, P.HEADER.size + k * tt.size), layout.max_cars) for k in range(len(TT_SETS))
    )


# --- end leaderboard ---


class _CarHist:
    """Session History state of one car (ingest thread only)."""

    __slots__ = ("ai_from_lap", "best_lap", "first_seen_lap", "key", "laps", "non_ai_seen", "raw", "stint_pits")

    def __init__(self, first_seen_lap: int) -> None:
        self.first_seen_lap = first_seen_lap  # numLaps when first seen: those laps were not observed from the start
        self.key: tuple[object, ...] | None = None  # change key of the last emission
        self.raw: list[bytes] = []  # 14-byte LapHistoryData entries, laps 1..numLaps
        self.laps: list[HistoryLap] = []
        self.stint_pits: frozenset[int] = frozenset()  # pit laps from the tyre stints (see _on_session_history)
        self.best_lap: int | None = None
        # AI takeover: a Participants packet said this car was not AI (human, or a 0 flag beyond numActiveCars) while
        # its lap list was being followed; when it turns AI, the laps up to numLaps then were not the AI's.
        self.non_ai_seen = False
        self.ai_from_lap = 0


class F1Adapter:
    """Stateful decoder for one F1 25 telemetry stream (one game instance).

    Field samples (layer L0b): besides the player's ``CarFrame``, every racing car of the field is emitted as a
    ``FieldSample`` at most ``field_hz`` times per second (0 disables them). Cost on the ingest thread: Motion and
    LapData packets only keep a reference to the packet (no copy, no decode); a CarTelemetry packet on which a field
    tick is due decodes the three all-car arrays with ``struct.iter_unpack`` (one C loop each) and builds one sample
    per racing car. Cars in the garage or whose result is not active are skipped, and so is the player's car unless
    ``field_include_player``. Cars in the pit lane are sent (``pit_status`` != 0): the field model needs to see the
    pit visit to drop the lap that led into it (F1 25 reports every racing car as "on track" in a race, so nothing
    else marks an in-lap). Samples are appended after the ``CarFrame`` of the same packet, so whatever consumes the
    list sees the player's frame first.
    """

    def __init__(
        self,
        field_hz: float = FIELD_HZ,
        *,
        field_include_player: bool = False,
        timing_hz: float = TIMING_HZ,
        field_motion: bool = False,  # spotter: emit a FieldMotion (two packet references) per Motion packet
    ) -> None:
        if not (math.isfinite(field_hz) and 0.0 <= field_hz <= MAX_FIELD_HZ):
            raise ValueError(f"field_hz must be 0-{MAX_FIELD_HZ:g} Hz, got {field_hz}")
        if not (math.isfinite(timing_hz) and 0.0 <= timing_hz <= MAX_TIMING_HZ):
            raise ValueError(f"timing_hz must be 0-{MAX_TIMING_HZ:g} Hz, got {timing_hz}")
        self.info = F1_25_INFO
        self.stats = DecodeStats()
        self.field_period_s: float | None = 1.0 / field_hz if field_hz > 0 else None
        self.field_include_player = field_include_player
        self.field_samples = 0  # FieldSamples emitted (all sessions)
        self.field_ticks = 0  # field ticks decoded (all sessions)
        # race strategy (pitwall.strategy): all-car RaceTiming at <= timing_hz of game clock (0 disables)
        self.timing_period_s: float | None = 1.0 / timing_hz if timing_hz > 0 else None
        self.timing_ticks = 0  # RaceTiming items emitted (all sessions)
        self.field_motion = field_motion  # spotter
        self.reset()

    def reset(self) -> None:
        self._session_uid: int | None = None
        self._motion: dict[str, Any] | None = None
        self._motion_frame = -1
        self._gscale = 1.0
        self._lap: dict[str, Any] | None = None
        self._lap_frame = -1
        self._status: dict[str, Any] | None = None
        self._damage: dict[str, Any] | None = None
        self._paused = False
        self._spectating = False
        self._platform = Platform.UNKNOWN
        self._team_id: int | None = None
        self._track_id: str | None = None
        self._prev_lap_num: int | None = None
        self._prev_lap_snapshot: dict[str, Any] | None = None
        self._prev_result: int | None = None
        # the last lap completion reported this session (lap number, the game's lastLapTimeInMS then; at the first
        # LapData packet, the time it showed) and a final lap the result status announced before its new time arrived
        # (see ``_on_lap_data``)
        self._done_lap: int | None = None
        self._done_ms: int | None = None
        self._final_wait: int | None = None
        self._final_wait_s: float | None = None  # session time the wait for a final lap's new time began
        self._lap_since_s: float | None = None  # session time the current lap number began (None: joined mid-lap)
        self._sector3: dict[str, Any] | None = None
        self._last_setup_fp: str | None = None
        self._format: int | None = None
        # field model (L0b): latest all-car packets kept by reference, decoded only when a field tick is due
        self._motion_raw: bytes | None = None
        self._lap_raw: bytes | None = None
        self._ai_controlled: tuple[bool | None, ...] = ()
        self._safety_car: bool | None = None
        self._field_last_t: float | None = None
        # feat/technique: latest MotionEx of the player car (decoded once per packet; merged into the next CarFrame)
        self._motion_ex: dict[str, Any] | None = None
        self._motion_ex_frame = -1
        # AI pace: per-slot AI flags (always decoded) and the per-car Session History state
        self._ai_flags_raw: tuple[bool | None, ...] = ()
        self._hist: dict[int, _CarHist] = {}
        # AI pace from the all-car LapData (``_watch_field_laps``): the previous packet (a reference), its result
        # status bytes, the last pit-lane key, each car's laps seen in the pit lane and the lap the game ended for it
        self._ld_prev: bytes | None = None
        self._ld_result: bytes | None = None
        self._ld_pit_key: bytes | None = None
        self._pit_seen: dict[int, set[int]] = {}
        self._ended_lap: dict[int, int] = {}
        # race strategy (pitwall.strategy): CarStatus kept by reference, decoded only on a timing tick
        self._timing_last_t: float | None = None
        self._timing_pits: bytes | None = None  # every car's LapData.pitStatus at the last tick
        self._status_raw: bytes | None = None
        self._session_type_id: int | None = None
        self._tyre_sets_key: bytes | None = None
        self._formula_raw: int | None = None  # Session.formula as sent (2 = F2: no ERS); None before the first one
        # race radio (pitwall.raceradio): the player's damage and penalty counters as cached objects (rebuilt only when
        # the game's values change, so the CarFrame carries the same object meanwhile), the Participants table key
        self._damage_key: bytes | None = None
        self._damage_obj: CarDamage | None = None
        self._pen_key: tuple[int, ...] | None = None
        self._pen_obj: CarPenalties | None = None
        self._participants_key: bytes | None = None
        # leaderboard: LapData's time trial car indexes (two byte reads per LapData packet); None until the first one
        self._tt_pb_idx: int | None = None
        self._tt_rival_idx: int | None = None

    # ------------------------------------------------------------------ structural validation
    def can_decode(self, data: bytes) -> bool:
        if len(data) < P.HEADER.size:
            return False
        layout = P.LAYOUTS.get(int.from_bytes(data[0:2], "little"))
        if layout is None:
            return False
        try:
            return layout.sizes.get(P.PacketId(data[6])) == len(data)
        except ValueError:
            return False

    def _header(self, data: bytes) -> dict[str, Any]:
        if len(data) < P.HEADER.size:
            raise PacketRejected(f"short packet ({len(data)} bytes)")
        h = P.HEADER.unpack_from(data)
        layout = P.LAYOUTS.get(h["packetFormat"])
        if layout is None:
            raise PacketRejected(
                f"unsupported packetFormat {h['packetFormat']} (supported: {sorted(P.LAYOUTS)}); "
                "set the in-game UDP Format to 2025 or 2026"
            )
        try:
            pid = P.PacketId(h["packetId"])
        except ValueError as e:
            raise PacketRejected(f"unknown packetId {h['packetId']}") from e
        expected = layout.sizes.get(pid)
        if expected is None:
            raise PacketRejected(f"packetId {pid.name} not defined in format {layout.packet_format}")
        if len(data) != expected:
            raise PacketRejected(f"{pid.name}: size {len(data)} != expected {expected} (format {layout.packet_format})")
        if h["playerCarIndex"] >= layout.max_cars:
            raise PacketRejected(f"playerCarIndex {h['playerCarIndex']} out of range")
        h["packetId"] = pid
        h["layout"] = layout
        self._format = layout.packet_format
        return h

    # ------------------------------------------------------------------ main entry point
    def decode(self, data: bytes, t_recv_ns: int) -> list[Emitted]:
        self.stats.packets += 1
        try:
            h = self._header(data)
        except PacketRejected as e:
            self.stats.rejected += 1
            self.stats.last_error = str(e)
            raise
        pid: P.PacketId = h["packetId"]
        self.stats.count(pid.name)
        out: list[Emitted] = []
        handler = _HANDLERS.get(pid)
        if handler is None:
            # Looked up before the session check: a packet pitwall ignores must not reset state. Real F1 25 (PS5,
            # online Suzuka capture) sends LapPositions with the PREVIOUS session's UID; letting it through reset the
            # per-session caches every ~2 s (the player's lap state, and the field model's AI flags / safety car).
            self.stats.ignored += 1
            return out
        uid = h["sessionUID"]
        if pid in _FOLLOWERS and (self._session_uid is None or (uid and uid != self._session_uid)):
            # A follower (Session History, TyreSets) never starts or resets a session: real F1 25 (PS5, Suzuka capture)
            # sends 20 history packets of the PREVIOUS session (its UID) at the start of a new one, and a stale-UID
            # packet must not flush the session's caches. uid 0 belongs to the current session.
            self.stats.ignored += 1
            return out
        if uid and self._session_uid and uid != self._session_uid:
            # A new session: drop per-session caches so nothing leaks across sessions.
            # (uid 0 is sent from menus and must not flush state.)
            self.reset()
        if uid:
            self._session_uid = uid
        try:
            handler(self, data, h, t_recv_ns, out)
            self.stats.decoded += 1
        except PacketRejected:
            self.stats.rejected += 1
            raise
        except Exception as e:  # never let one bad packet kill the stream
            self.stats.errors += 1
            self.stats.last_error = f"{pid.name}: {e!r}"
            log.exception("F1 decode error in %s", pid.name)
        return out

    # ------------------------------------------------------------------ per-packet handlers
    def _on_motion(self, data: bytes, h: dict[str, Any], t: int, out: list[Emitted]) -> None:
        idx = h["playerCarIndex"]
        cm = h["layout"].car_motion
        self._motion = cm.unpack_from(data, P.HEADER.size + idx * cm.size)
        self._gscale = h["layout"].gforce_scale
        self._motion_frame = h["frameIdentifier"]
        self._motion_raw = data  # all cars, for the next field tick: a reference, not a copy
        # --- spotter --- one object holding the Motion and latest LapData references; decoded off this thread
        if self.field_motion:
            out.append(
                FieldMotion(
                    game=Game.F1_25,
                    t_recv_ns=t,
                    session_time_s=h["sessionTime"],
                    frame_id=self._motion_frame,
                    player_index=idx,
                    packet_format=h["packetFormat"],
                    motion=data,
                    lap=self._lap_raw,
                )
            )
        # --- end spotter ---

    def _on_motion_ex(self, data: bytes, h: dict[str, Any], t: int, out: list[Emitted]) -> None:
        """feat/technique: MotionEx (ID 13) is player-car-only extra motion data. One cached ``unpack_from``; it
        emits nothing and is merged into the next CarFrame (``_merge_motion_ex``)."""
        self._motion_ex = P.MOTION_EX.unpack_from(data, P.HEADER.size)
        self._motion_ex_frame = h["frameIdentifier"]

    def _on_lap_data(self, data: bytes, h: dict[str, Any], t: int, out: list[Emitted]) -> None:
        idx = h["playerCarIndex"]
        lap = P.LAP_DATA.unpack_from(data, P.HEADER.size + idx * P.LAP_DATA.size)
        self._lap = lap
        self._lap_frame = h["frameIdentifier"]
        self._lap_raw = data
        # leaderboard: the time trial PB / rival car indexes after the car array (255 outside Time Trial)
        layout: P.F1Layout = h["layout"]
        tail = LAP_DATA_TAIL_OFFSET[layout.packet_format]
        self._tt_pb_idx = tt_car_index(data[tail], layout.max_cars)
        self._tt_rival_idx = tt_car_index(data[tail + 1], layout.max_cars)
        lap_num = lap["currentLapNum"]
        prev = self._prev_lap_num
        last_raw = lap["lastLapTimeInMS"]
        now_s = float(h["sessionTime"])
        if prev is None:
            self._done_ms = last_raw  # joined mid-session: the time shown now belongs to a lap before this one
        if lap_num != prev:
            # when this lap number began; None when joined mid-session (the lap began before Pitwall saw it)
            self._lap_since_s = now_s if prev is not None else None
        if prev is not None and lap_num == prev + 1 and self._prev_lap_snapshot is not None:
            snap = self._sector_snapshot(prev) or self._prev_lap_snapshot
            last_ms = last_raw or None
            s1 = _mins_ms(snap["sector1TimeMinutesPart"], snap["sector1TimeMSPart"]) or None
            s2 = _mins_ms(snap["sector2TimeMinutesPart"], snap["sector2TimeMSPart"]) or None
            s3 = last_ms - s1 - s2 if (last_ms and s1 and s2) else None
            out.append(
                LapCompletion(
                    game=Game.F1_25,
                    t_recv_ns=t,
                    lap_number=prev,
                    lap_time_ms=last_ms,
                    sector_times_ms=[s1, s2, s3],
                    valid=not bool(snap["currentLapInvalid"]),
                    session_time_s=h["sessionTime"],
                    final=lap["resultStatus"] == RESULT_FINISHED,
                )
            )
            self._done_lap, self._done_ms, self._final_wait, self._final_wait_s = prev, last_raw, None, None
        elif (
            prev is not None
            and lap_num == prev
            and lap["resultStatus"] == RESULT_FINISHED
            and (self._prev_result != RESULT_FINISHED or self._final_wait == lap_num)
            and self._prev_lap_snapshot is not None
        ):
            # Final lap of a race: the lap number does not advance at the chequered flag; instead the result status
            # turns "finished" and lastLapTimeInMS updates (observed in F1 25 v1.26 on PS5: the new time arrives in the
            # same packet or one packet earlier). One-shot qualifying (recorded on PS5, 2026-10-11) is different: the
            # lap number advances at the line (that completion is the lap), and 17 ms later the result turns
            # "finished" with lastLapTimeInMS unchanged, on a lap that is never driven. So a final lap is reported
            # only when the game's last-lap time changed since the last completion; with the time unchanged it waits
            # for a new time on this lap number (a race's time arriving a packet late), which never comes after a
            # one-shot lap. O(1) per packet.
            #
            # A final lap driven in exactly the previous lap's time (to the millisecond) never shows a new time: it is
            # reported once the wait has lasted FINAL_TIME_GRACE_S of session time, if the car had been on this lap
            # number for at least FINAL_LAP_MIN_FRAC of that time when the result turned "finished" (a one-shot
            # lap number is 17 ms old then).
            if last_raw and last_raw != self._done_ms:
                self._final_completion(lap, lap_num, last_raw, h, t, out)
            elif self._final_wait != lap_num:
                self._final_wait = lap_num  # finished, no new time yet: report it only if one arrives
                self._final_wait_s = now_s
                self.stats.count("LAP_FINAL_WITHOUT_NEW_TIME")
            elif (
                last_raw
                and self._final_wait_s is not None
                and self._lap_since_s is not None
                and now_s - self._final_wait_s >= FINAL_TIME_GRACE_S
                and self._final_wait_s - self._lap_since_s >= FINAL_LAP_MIN_FRAC * last_raw / 1000.0
            ):
                self._final_completion(lap, lap_num, last_raw, h, t, out)  # the same time, genuinely
                self.stats.count("LAP_FINAL_SAME_TIME")
        if lap["sector"] == 2:
            # Sector times are zeroed as the car crosses the line - sometimes a packet BEFORE the lap number or
            # result status changes (observed on PS5) - so keep the last sector-3 snapshot of each lap.
            self._sector3 = lap
        self._prev_lap_num = lap_num
        self._prev_result = lap["resultStatus"]
        if lap["resultStatus"] != RESULT_FINISHED:
            self._prev_lap_snapshot = lap  # keep the last in-race snapshot for the final-lap sectors
        # race radio (pitwall.raceradio): the player's penalty counters, rebuilt only when one changed (a tuple compare)
        pen_key = (
            lap["penalties"],
            lap["totalWarnings"],
            lap["cornerCuttingWarnings"],
            lap["numUnservedDriveThroughPens"],
            lap["numUnservedStopGoPens"],
            lap["pitStopShouldServePen"],
        )
        if pen_key != self._pen_key:
            self._pen_key = pen_key
            self._pen_obj = CarPenalties(
                time_penalties_s=pen_key[0],
                warnings=pen_key[1],
                corner_cutting_warnings=pen_key[2],
                unserved_drive_throughs=pen_key[3],
                unserved_stop_gos=pen_key[4],
                serve_at_stop=bool(pen_key[5]),
            )
        # One LapData pass for the all-car readers: AI pace watches results and pit laps, and hands the race timing the
        # same strided pit-status slice (one byte per car), so strategy's tick check costs no second slice.
        pits = self._watch_field_laps(data, h, t, out)
        if self.timing_period_s is not None:  # race strategy (pitwall.strategy)
            self._timing_tick(data, h, t, out, pits)

    def _watch_field_laps(self, data: bytes, h: dict[str, Any], t: int, out: list[Emitted]) -> bytes:
        """AI pace: from every car's LapData, the laps each car spent in the pit lane and a lap the game ended for a car
        before it reached the line (the driver skipped to the results, or the car retired). Per packet: two or three
        strided byte slices and compares; the per-car loop runs only when a car's result changed, or while a car is
        in the pit lane and a pit status or lap number changed. Returns every car's pitStatus byte (the race timing's
        tick trigger)."""
        n = h["layout"].max_cars
        base = P.HEADER.size
        end = base + n * LD_SIZE
        res = data[base + LD_RESULT : end : LD_SIZE]
        prev_res, prev = self._ld_result, self._ld_prev
        if res != prev_res:
            if prev is not None and prev_res is not None and len(prev_res) == n:
                for i in range(n):
                    if prev_res[i] != RESULT_ACTIVE or res[i] <= RESULT_ACTIVE or i in self._ended_lap:
                        continue
                    off = base + i * LD_SIZE
                    dist = _F32.unpack_from(data, off + LD_DIST)[0]
                    if not (math.isfinite(dist) and 0.0 <= dist <= RESULT_OFF_LINE_M):
                        # the lap in progress (as of the previous packet) was ended by the game, not on track
                        self._ended_lap[i] = prev[off + LD_LAP]
                        st = self._hist.get(i)
                        if st is not None and st.key is not None:
                            self._emit_history(i, st, h, t, out)  # also when its history came first this frame
            self._ld_result = res
        pit = data[base + LD_PIT : end : LD_SIZE]
        if pit.count(0) != n:  # some car is in the pit lane
            laps = data[base + LD_LAP : end : LD_SIZE]
            key = pit + laps
            if key != self._ld_pit_key:
                self._ld_pit_key = key
                for i in range(n):
                    if pit[i] and laps[i]:
                        self._pit_seen.setdefault(i, set()).add(laps[i])
        self._ld_prev = data
        return pit

    # --- race strategy (pitwall.strategy) ---------------------------------------------------------------------
    def _timing_tick(self, data: bytes, h: dict[str, Any], t: int, out: list[Emitted], pits: bytes) -> None:
        """Emit one ``RaceTiming`` (every racing car) when a timing tick is due, at most once per
        ``timing_period_s`` of game clock (same cadence rules as ``_field_tick``: replays decimate like live play, a
        clock that jumps back re-arms at once), and at once on any car's pit-status change, so pit-lane entry and exit
        are timed to the packet (the pit-lane timer resets at the exit, between two regular ticks). Time trial has no
        field to race, so nothing is emitted there. ``pits``: every car's pitStatus byte, the strided slice
        ``_watch_field_laps`` already took. Cost on the ingest thread: one bytes compare on every LapData packet; on a
        tick one ``iter_unpack`` over the LapData array (and over the last CarStatus array kept by reference), then one
        small frozen object per car."""
        if self._session_type_id == SESSION_TYPE_TIME_TRIAL:
            return
        period = self.timing_period_s
        assert period is not None
        layout: P.F1Layout = h["layout"]
        ts = _TIMING_STRUCTS[layout.packet_format]
        base = P.HEADER.size
        st = float(h["sessionTime"])
        last = self._timing_last_t
        due = not (last is not None and last - FIELD_REWIND_S <= st < last + period - FIELD_TICK_TOLERANCE_S)
        if not due and pits == self._timing_pits:
            return  # not due yet
        self._timing_pits = pits
        self._timing_last_t = st
        rows = ts.lap.iter_unpack(memoryview(data)[base : base + ts.lap_bytes])
        status_raw = self._status_raw
        status: list[tuple[Any, ...]] | None = None
        if status_raw is not None and len(status_raw) == ts.status_packet_size:
            status = list(ts.status.iter_unpack(memoryview(status_raw)[base : base + ts.status_bytes]))
        player = h["playerCarIndex"]
        ai = self._ai_controlled
        cars: list[CarTiming] = []
        for i, row in enumerate(rows):
            (
                last_ms,
                ahead_ms,
                ahead_min,
                leader_ms,
                leader_min,
                dist,
                pos,
                lap_num,
                pit,
                stops,
                sector,
                invalid,
                grid,
                driver,
                result,
                lane_active,
                lane_ms,
                stop_ms,
                serve_pen,
            ) = row
            if result < RESULT_ACTIVE:
                continue  # invalid / inactive slot
            visual = age = None
            if status is not None:
                vis_code, age = status[i]
                visual = enums.VISUAL_COMPOUNDS.get(vis_code)
                if visual is None:
                    age = None  # no compound (restricted online telemetry?): its age would read "0 laps", made up
            cars.append(
                CarTiming(
                    car_index=i,
                    is_player=i == player,
                    ai_controlled=ai[i] if i < len(ai) else None,
                    position=pos,
                    grid_position=grid or None,
                    lap_number=lap_num,
                    lap_distance_m=dist,
                    sector=sector,
                    last_lap_ms=last_ms or None,
                    gap_ahead_ms=_timing_gap(ahead_min, ahead_ms),
                    gap_leader_ms=_timing_gap(leader_min, leader_ms),
                    pit_status=pit,
                    num_pit_stops=stops,
                    pit_lane_timer_active=bool(lane_active),
                    pit_lane_time_ms=lane_ms if lane_active else None,
                    pit_stop_timer_ms=stop_ms or None,
                    serve_penalty=bool(serve_pen),
                    driver_status=DRIVER_STATUS.get(driver),
                    result_status=RESULT_STATUS.get(result),
                    lap_invalid=bool(invalid),
                    tyre_visual=visual,
                    tyre_age_laps=age,
                )
            )
        self.timing_ticks += 1
        out.append(
            RaceTiming(
                game=Game.F1_25,
                t_recv_ns=t,
                session_time_s=st,
                frame_id=h["frameIdentifier"],
                player_index=player,
                cars=tuple(cars),
            )
        )

    def _on_tyre_sets(self, data: bytes, h: dict[str, Any], t: int, out: list[Emitted]) -> None:
        """The player's tyre sets (the game cycles TyreSets through every car): emitted only when they changed."""
        if data[P.HEADER.size] != h["playerCarIndex"]:
            return
        start = P.HEADER.size + P.TYRE_SETS_HEAD.size
        key = bytes(data[start:])  # the 20 sets and m_fittedIdx
        if key == self._tyre_sets_key:
            return
        self._tyre_sets_key = key
        sets: list[TyreSet] = []
        for k in range(P.NUM_TYRE_SETS):
            s = P.TYRE_SET.unpack_from(data, start + k * P.TYRE_SET.size)
            sets.append(
                TyreSet(
                    index=k,
                    actual=enums.ACTUAL_COMPOUNDS.get(s["actualTyreCompound"]),
                    visual=enums.VISUAL_COMPOUNDS.get(s["visualTyreCompound"]),
                    wear_pct=s["wear"],
                    available=bool(s["available"]),
                    recommended_session=s["recommendedSession"],
                    life_span_laps=s["lifeSpan"],
                    usable_life_laps=s["usableLife"],
                    lap_delta_ms=s["lapDeltaTime"],
                    fitted=bool(s["fitted"]),
                )
            )
        fitted = P.TYRE_SETS_TAIL.unpack_from(data, start + P.NUM_TYRE_SETS * P.TYRE_SET.size)["fittedIdx"]
        out.append(
            TyreSetsInfo(
                game=Game.F1_25,
                t_recv_ns=t,
                session_time_s=float(h["sessionTime"]),
                car_index=h["playerCarIndex"],
                sets=tuple(sets),
                fitted_index=fitted if fitted < P.NUM_TYRE_SETS else None,
            )
        )

    # --- leaderboard ---
    def _on_time_trial(self, data: bytes, h: dict[str, Any], t: int, out: list[Emitted]) -> None:
        """Time Trial (ID 14, once a second, Time Trial mode only): the three datasets and LapData's PB / rival car
        indexes, emitted on every packet (three 24-25 byte unpacks a second); the session manager stores a change."""
        layout: P.F1Layout = h["layout"]
        best, pb, rival = decode_time_trial_sets(data, layout)
        uid = h["sessionUID"] or self._session_uid
        out.append(
            TimeTrialInfo(
                game=Game.F1_25,
                t_recv_ns=t,
                session_time_s=float(h["sessionTime"]),
                session_uid=str(uid) if uid else None,
                packet_format=layout.packet_format,
                player_session_best=best,
                personal_best=pb,
                rival=rival,
                pb_car_index=self._tt_pb_idx,
                rival_car_index=self._tt_rival_idx,
            )
        )

    # --- end leaderboard ---

    def _final_completion(
        self, lap: dict[str, Any], lap_num: int, last_ms: int, h: dict[str, Any], t: int, out: list[Emitted]
    ) -> None:
        """The driver's final lap (the chequered flag on ``lap_num``), timed ``last_ms`` by the game."""
        assert self._prev_lap_snapshot is not None
        snap = self._sector_snapshot(lap_num) or self._prev_lap_snapshot
        s1 = _mins_ms(snap["sector1TimeMinutesPart"], snap["sector1TimeMSPart"]) or None
        s2 = _mins_ms(snap["sector2TimeMinutesPart"], snap["sector2TimeMSPart"]) or None
        out.append(
            LapCompletion(
                game=Game.F1_25,
                t_recv_ns=t,
                lap_number=lap_num,
                lap_time_ms=last_ms,
                sector_times_ms=[s1, s2, last_ms - s1 - s2 if (s1 and s2) else None],
                valid=not bool(snap["currentLapInvalid"]),
                session_time_s=h["sessionTime"],
                final=True,  # the driver took the chequered flag on this lap
            )
        )
        self._done_lap, self._done_ms, self._final_wait, self._final_wait_s = lap_num, last_ms, None, None

    def _sector_snapshot(self, lap_number: int) -> dict[str, Any] | None:
        s3 = self._sector3
        return s3 if s3 is not None and s3["currentLapNum"] == lap_number else None

    def _on_car_telemetry(self, data: bytes, h: dict[str, Any], t: int, out: list[Emitted]) -> None:
        idx = h["playerCarIndex"]
        ct = h["layout"].car_telemetry
        tel = ct.unpack_from(data, P.HEADER.size + idx * ct.size)
        frame_id = h["frameIdentifier"]
        q = FrameQuality.OK
        if self._paused:
            q |= FrameQuality.PAUSED
        if self._spectating:
            q |= FrameQuality.REPLAY_OR_SPECTATING
        f = CarFrame(
            game=Game.F1_25,
            t_recv_ns=t,
            session_time_s=h["sessionTime"],
            frame_id=frame_id,
            speed_kph=float(tel["speed"]),
            throttle=tel["throttle"],
            brake=tel["brake"],
            steering=tel["steer"],
            clutch=tel["clutch"] / 100.0,
            gear=tel["gear"],
            rpm=float(tel["engineRPM"]),
            drs_open=bool(tel["drs"]),
            brake_temp_c=Wheels.from_rl_rr_fl_fr([float(v) for v in tel["brakesTemperature"]]),
            tyre_surface_temp_c=Wheels.from_rl_rr_fl_fr([float(v) for v in tel["tyresSurfaceTemperature"]]),
            tyre_inner_temp_c=Wheels.from_rl_rr_fl_fr([float(v) for v in tel["tyresInnerTemperature"]]),
            tyre_pressure_psi=Wheels.from_rl_rr_fl_fr(list(tel["tyresPressure"])),
            engine_temp_c=float(tel["engineTemperature"]),  # --- health lane --- (uint16 2025, uint8 2026)
        )
        m = self._motion
        if m is not None:
            if self._motion_frame != frame_id:
                q |= FrameQuality.STALE_POSITION
            f.pos_x_m, f.pos_y_m, f.pos_z_m = m["worldPositionX"], m["worldPositionY"], m["worldPositionZ"]
            f.vel_x_mps, f.vel_y_mps, f.vel_z_mps = m["worldVelocityX"], m["worldVelocityY"], m["worldVelocityZ"]
            gs = self._gscale
            f.g_lat, f.g_lon, f.g_vert = m["gForceLateral"] * gs, m["gForceLongitudinal"] * gs, m["gForceVertical"] * gs
            f.yaw_rad, f.pitch_rad, f.roll_rad = m["yaw"], m["pitch"], m["roll"]
        ex = self._motion_ex  # feat/technique
        if ex is not None and abs(frame_id - self._motion_ex_frame) <= MOTION_EX_MAX_FRAME_SKEW:
            # Real F1 25 (PS5): angularVelocityY is d(yaw)/dt and negative in right turns; flipped so that + = right,
            # the same sign as steering. Wheel arrays are RL, RR, FL, FR.
            f.yaw_rate_rps = -ex["angularVelocityY"]
            f.body_slip_rad = ex["chassisYaw"]
            f.wheel_slip_ratio = Wheels.from_rl_rr_fl_fr(list(ex["wheelSlipRatio"]))
            f.wheel_slip_angle_rad = Wheels.from_rl_rr_fl_fr(list(ex["wheelSlipAngle"]))
        lap = self._lap
        if lap is not None:
            if self._lap_frame != frame_id:
                q |= FrameQuality.STALE_LAP_DATA
            f.lap_number = lap["currentLapNum"]
            f.lap_distance_m = lap["lapDistance"]
            f.total_distance_m = lap["totalDistance"]
            f.current_lap_time_ms = lap["currentLapTimeInMS"]
            f.last_lap_time_ms = lap["lastLapTimeInMS"] or None
            f.sector = lap["sector"]
            f.lap_invalid = bool(lap["currentLapInvalid"])
            f.pit_status = lap["pitStatus"]
            f.race_position = lap["carPosition"]
            if lap["resultStatus"] != RESULT_ACTIVE or lap["driverStatus"] == DRIVER_IN_GARAGE:
                q |= FrameQuality.NOT_RACING
        st = self._status
        if st is not None:
            f.max_rpm = float(st["maxRPM"])
            f.fuel_kg = st["fuelInTank"]
            f.fuel_capacity_kg = st["fuelCapacity"]
            f.fuel_remaining_laps_game = st["fuelRemainingLaps"]
            if self._formula_raw is not None and self._formula_raw != FORMULA_F2:
                # F2 cars have no ERS: F1 25 sends 0 in every ERS / hybrid field for them (recorded on PS5), which is
                # "not there", not an empty battery. Before the session's first Session packet the formula is unknown,
                # so the car may be an F2 car: no ERS value until then (joining a running F2 session once showed
                # 14 frames of "ERS 0.0 MJ")
                f.ers_store_j = st["ersStoreEnergy"]
                f.ers_deploy_mode = st["ersDeployMode"]
            f.drs_allowed = bool(st["drsAllowed"])
            dist = st["drsActivationDistance"]
            f.drs_activation_m = float(dist) if dist > 0 else None
            f.tyre_compound = enums.VISUAL_COMPOUNDS.get(st["visualTyreCompound"])
            f.tyre_age_laps = st["tyresAgeLaps"]
            f.brake_bias_front_pct = float(st["frontBrakeBias"])
            f.traction_control = st["tractionControl"]
            f.abs_active = bool(st["antiLockBrakes"])
            f.fia_flag = enums.FIA_FLAGS.get(st["vehicleFIAFlags"])  # race radio: -1 / undocumented -> None
        dmg = self._damage
        if dmg is not None:
            f.tyre_wear_pct = Wheels.from_rl_rr_fl_fr(list(dmg["tyresWear"]))
            f.damage = self._damage_obj  # race radio
        if lap is not None:
            f.penalties = self._pen_obj  # race radio
        f.quality = q
        out.append(f)
        if self.field_period_s is not None:
            self._field_tick(data, h, t, out)

    def _field_tick(self, data: bytes, h: dict[str, Any], t: int, out: list[Emitted]) -> None:
        """Emit one ``FieldSample`` per racing car when a field tick is due (at most one per ``field_period_s``).

        The cadence follows the game clock, so replays decimate exactly like live play: consecutive ticks are at
        least ``field_period_s`` (less ``FIELD_TICK_TOLERANCE_S`` of clock jitter) apart, so no car is ever sampled
        faster than ``field_hz``. A clock that jumps back (flashback, restart) re-arms at once. A tick waits for
        Motion and LapData of (nearly) the same frame as this telemetry: on packet loss it is simply taken on the
        next CarTelemetry packet.
        """
        period = self.field_period_s
        assert period is not None
        st = float(h["sessionTime"])
        last = self._field_last_t
        if last is not None and last - FIELD_REWIND_S <= st < last + period - FIELD_TICK_TOLERANCE_S:
            return  # not due yet
        motion, laps = self._motion_raw, self._lap_raw
        frame_id = h["frameIdentifier"]
        if (
            motion is None
            or laps is None
            or abs(frame_id - self._motion_frame) > FIELD_MAX_FRAME_SKEW
            or abs(frame_id - self._lap_frame) > FIELD_MAX_FRAME_SKEW
        ):
            return
        self._field_last_t = st
        fs = _FIELD_STRUCTS[h["layout"].packet_format]
        n = fs.max_cars
        base = P.HEADER.size
        lap_rows = fs.lap.iter_unpack(memoryview(laps)[base : base + n * P.LAP_DATA.size])
        mot_rows = fs.motion.iter_unpack(memoryview(motion)[base : base + fs.motion_bytes])
        tel_rows = fs.telemetry.iter_unpack(memoryview(data)[base : base + fs.telemetry_bytes])
        player = -1 if self.field_include_player else h["playerCarIndex"]
        gs = h["layout"].gforce_scale
        ai = self._ai_controlled
        sc = self._safety_car
        self.field_ticks += 1
        for i, (lap, mot, tel) in enumerate(zip(lap_rows, mot_rows, tel_rows, strict=True)):
            gap_ms, gap_min, dist, lap_num, pit, sector, invalid, driver, result = lap
            if result != RESULT_ACTIVE or driver == DRIVER_IN_GARAGE or i == player:
                continue  # inactive slot or garage (pit lane samples go out: they mark the car's in-lap)
            x, y, z, glon = mot
            speed, throttle, steer, brake, gear = tel
            gap = gap_min * 60_000 + gap_ms
            out.append(
                FieldSample(
                    game=Game.F1_25,
                    t_recv_ns=t,
                    session_time_s=st,
                    frame_id=frame_id,
                    car_index=i,
                    ai_controlled=ai[i] if i < len(ai) else None,
                    lap_number=lap_num,
                    lap_distance_m=dist,
                    pos_x_m=x,
                    pos_y_m=y,
                    pos_z_m=z,
                    speed_kph=float(speed),
                    throttle=throttle,
                    brake=brake,
                    steering=steer,
                    gear=gear,
                    sector=sector,
                    lap_invalid=bool(invalid),
                    pit_status=pit,
                    driver_status=DRIVER_STATUS.get(driver),
                    result_status=RESULT_STATUS.get(result),
                    g_lon=glon * gs,
                    gap_ahead_ms=gap if gap > 0 else None,  # 0 = the leader (or not reported): unknown, not "no gap"
                    safety_car=sc,
                )
            )
            self.field_samples += 1

    def _on_car_status(self, data: bytes, h: dict[str, Any], t: int, out: list[Emitted]) -> None:
        idx = h["playerCarIndex"]
        cs = h["layout"].car_status
        self._status = cs.unpack_from(data, P.HEADER.size + idx * cs.size)
        self._status_raw = data  # all cars, for the next race timing tick: a reference, not a copy

    def _on_car_damage(self, data: bytes, h: dict[str, Any], t: int, out: list[Emitted]) -> None:
        idx = h["playerCarIndex"]
        off = P.HEADER.size + idx * P.CAR_DAMAGE.size
        dmg = self._damage = P.CAR_DAMAGE.unpack_from(data, off)
        # race radio (pitwall.raceradio): one CarDamage object while the damage bytes are unchanged (a 30-byte slice
        # compare; the tyre wear floats before them change every packet and are mapped to tyre_wear_pct as before)
        key = data[off + _DAMAGE_FROM : off + P.CAR_DAMAGE.size]
        if key != self._damage_key:
            self._damage_key = key
            self._damage_obj = CarDamage(
                front_left_wing_pct=dmg["frontLeftWingDamage"],
                front_right_wing_pct=dmg["frontRightWingDamage"],
                rear_wing_pct=dmg["rearWingDamage"],
                floor_pct=dmg["floorDamage"],
                diffuser_pct=dmg["diffuserDamage"],
                sidepod_pct=dmg["sidepodDamage"],
                gearbox_pct=dmg["gearBoxDamage"],
                engine_pct=dmg["engineDamage"],
                brakes_pct=Wheels.from_rl_rr_fl_fr(list(dmg["brakesDamage"])),
                tyres_pct=Wheels.from_rl_rr_fl_fr(list(dmg["tyresDamage"])),
                drs_fault=bool(dmg["drsFault"]),
                ers_fault=bool(dmg["ersFault"]),
                engine_blown=bool(dmg["engineBlown"]),
                engine_seized=bool(dmg["engineSeized"]),
            )

    def _on_participants(self, data: bytes, h: dict[str, Any], t: int, out: list[Emitted]) -> None:
        idx = h["playerCarIndex"]
        pd = h["layout"].participant
        part = pd.unpack_from(data, P.HEADER.size + P.PARTICIPANTS_HEAD.size + idx * pd.size)
        self._team_id = part["teamId"]
        self._platform = enums.PLATFORMS.get(part["platform"], Platform.UNKNOWN)
        # Who is AI (every 5 s), one byte per slot. Slots past numActiveCars are zero-filled, so their "0" is unknown,
        # not "human". numActiveCars is not a slot count, though: in a real F1 25 scenario it read 18, then 17, while
        # slots 0-19 were all occupied (retired cars keep their slots), so a flag of 1 means AI in any slot.
        fs = _FIELD_STRUCTS[h["layout"].packet_format]
        n_active = P.PARTICIPANTS_HEAD.unpack_from(data, P.HEADER.size)["numActiveCars"]
        start = P.HEADER.size + P.PARTICIPANTS_HEAD.size
        flags = [r[0] for r in fs.participant.iter_unpack(memoryview(data)[start : start + fs.participant_bytes])]
        self._ai_flags_raw = tuple(True if f == 1 else (False if i < n_active else None) for i, f in enumerate(flags))
        if self.field_period_s is not None or self.timing_period_s is not None:
            # The field model learns from AI cars only by default (human opponents' data is a privacy question); the
            # race timing (pitwall.strategy) reports the same flags per car.
            # Unchanged rule (slots >= numActiveCars unknown); see docs follow-up on retired cars' slots.
            self._ai_controlled = tuple(bool(f) if i < n_active else None for i, f in enumerate(flags))
        # race radio (pitwall.raceradio): the whole table, emitted only when it changed (a ~1.2 kB bytes compare every
        # 5 s; decoded only on change). Names stay inside ``Participant`` (repr-less) and go to the race radio only.
        key = data[start:]
        if key != self._participants_key:
            self._participants_key = key
            cars: list[Participant] = []
            for i in range(min(n_active, h["layout"].max_cars)):
                row = pd.unpack_from(data, start + i * pd.size)
                driver = row["driverId"]
                raw = row["name"]
                cars.append(
                    Participant(
                        car_index=i,
                        ai_controlled=row["aiControlled"] == 1,
                        driver_id=None if driver in enums.DRIVER_ID_NONE else driver,
                        team_id=row["teamId"],
                        race_number=row["raceNumber"] or None,
                        name=raw.split(b"\0", 1)[0].decode("utf-8", errors="replace").strip(),
                        show_online_names=SHOW_ONLINE_NAMES.get(row["showOnlineNames"]),
                    )
                )
            out.append(
                Participants(
                    game=Game.F1_25,
                    t_recv_ns=t,
                    session_time_s=float(h["sessionTime"]),
                    player_index=idx,
                    cars=tuple(cars),
                )
            )

    def _on_session(self, data: bytes, h: dict[str, Any], t: int, out: list[Emitted]) -> None:
        head = P.SESSION_HEAD.unpack_from(data, P.SESSION_HEAD_OFFSET)
        n_mz = min(head["numMarshalZones"], P.NUM_MARSHAL_ZONES)  # only the first n entries are meaningful
        marshal = [
            P.MARSHAL_ZONE.unpack_from(data, P.SESSION_MARSHAL_ZONES_OFFSET + i * P.MARSHAL_ZONE.size)
            for i in range(n_mz)
        ]
        mid = P.SESSION_MID.unpack_from(data, P.SESSION_MID_OFFSET)
        sc_raw = mid["safetyCarStatus"]
        self._safety_car = sc_raw != SAFETY_CAR_NONE if sc_raw in SAFETY_CAR_KNOWN else None
        n_fc = min(mid["numWeatherForecastSamples"], P.NUM_WEATHER_SAMPLES)
        forecast = [
            P.WEATHER_FORECAST_SAMPLE.unpack_from(data, P.SESSION_FORECAST_OFFSET + i * P.WEATHER_FORECAST_SAMPLE.size)
            for i in range(n_fc)
        ]
        tail = h["layout"].session_tail.unpack_from(data, P.SESSION_TAIL_OFFSET)
        # The tail is unfilled (gearboxAssist 0, aiDifficulty 0) in the first Session packets of every session.
        tail_ok = tail["gearboxAssist"] in GEARBOX_ASSIST_DEFINED
        ai_raw = tail["aiDifficulty"]
        ai_difficulty = ai_raw if tail_ok and 0 <= ai_raw <= AI_DIFFICULTY_MAX else None
        n_weekend = min(int(tail["numSessionsInWeekend"]), len(tail["weekendStructure"])) if tail_ok else 0
        weekend = [int(x) for x in tail["weekendStructure"][:n_weekend]]

        self._paused = bool(head["gamePaused"])
        self._spectating = bool(head["isSpectating"])
        self._session_type_id = head["sessionType"]
        self._formula_raw = head["formula"]
        track_id = head["trackId"]
        self._track_id = f"f1:{track_id}"
        stype_label, stype = enums.SESSION_TYPES.get(
            head["sessionType"], (f"unknown_{head['sessionType']}", SessionType.UNKNOWN)
        )
        team = self._team_id
        out.append(
            SessionInfo(
                game=Game.F1_25,
                t_recv_ns=t,
                platform=self._platform,
                session_uid=str(h["sessionUID"]),
                track_id=self._track_id,
                track_name=enums.track_name(track_id),
                track_length_m=float(head["trackLength"]),
                session_type=stype,
                session_type_raw=stype_label,
                total_laps=head["totalLaps"],
                session_time_left_s=float(head["sessionTimeLeft"]),
                car_id=f"f1:team:{team}" if team is not None else None,
                car_name=enums.team_name(team) if team is not None else None,
                weather=Weather(
                    condition=enums.WEATHER.get(head["weather"]),
                    track_temp_c=float(head["trackTemperature"]),
                    air_temp_c=float(head["airTemperature"]),
                    rain_percentage=float(forecast[0]["rainPercentage"]) if forecast else None,
                ),
                assists={
                    "steering": tail["steeringAssist"],
                    "braking": tail["brakingAssist"],
                    "gearbox": tail["gearboxAssist"],
                    "pit": tail["pitAssist"],
                    "pit_release": tail["pitReleaseAssist"],
                    "ers": tail["ERSAssist"],
                    "drs": tail["DRSAssist"],
                    "dynamic_racing_line": tail["dynamicRacingLine"],
                    "dynamic_racing_line_type": tail["dynamicRacingLineType"],
                    "equal_car_performance": tail["equalCarPerformance"],
                },
                pit_speed_limit_kph=float(head["pitSpeedLimit"]),
                safety_car_status=enums.SAFETY_CAR_STATUS.get(mid["safetyCarStatus"]),
                formula=enums.FORMULA.get(head["formula"]),
                track_zones=_track_zones(marshal, tail, h["packetFormat"]),
                ai_difficulty=ai_difficulty,
                session_time_s=float(h["sessionTime"]),
                network_game=NETWORK_GAME.get(mid["networkGame"]),
                extra={
                    "game_mode": tail["gameMode"],  # raw Session.gameMode (e.g. 4 Grand Prix, 7 Online Custom)
                    "game_paused": self._paused,
                    "is_spectating": self._spectating,
                    # Deprecated: superseded by the typed ``track_zones``; kept (raw) for one release because
                    # stored sessions and the web fallback read them.
                    "sector2_start_m": tail["sector2LapDistanceStart"],
                    "sector3_start_m": tail["sector3LapDistanceStart"],
                    "pit_window_ideal_lap": tail["pitStopWindowIdealLap"],
                    "pit_window_latest_lap": tail["pitStopWindowLatestLap"],
                    "game_version": f"{h['gameMajorVersion']}.{h['gameMinorVersion']:02d}",
                    "packet_format": h["packetFormat"],
                    "forecast": [
                        {
                            "time_offset_min": s["timeOffset"],
                            "weather": enums.WEATHER.get(s["weather"]),
                            "track_temp_c": s["trackTemperature"],
                            "air_temp_c": s["airTemperature"],
                            "rain_pct": s["rainPercentage"],
                            "session_type": s["sessionType"],
                        }
                        for s in forecast
                    ],
                    # race strategy (pitwall.strategy): raw game values
                    "session_type_id": head["sessionType"],
                    "forecast_accuracy": tail["forecastAccuracy"],  # 0 perfect, 1 approximate
                    "pit_rejoin_position": tail["pitStopRejoinPosition"],  # 0 = not set
                    "num_safety_car_periods": tail["numSafetyCarPeriods"],
                    "num_vsc_periods": tail["numVirtualSafetyCarPeriods"],
                    "num_red_flag_periods": tail["numRedFlagPeriods"],
                    # the weekend's session types in order (spec 8.5; F2: a "Race" is the sprint only before a
                    # "Race 2", carclass.f2_race_kind); absent while the tail is unfilled or the game lists none
                    **({"weekend_structure": weekend} if weekend else {}),
                    # --- health lane: game settings (raw), None while the tail is unfilled (first ~1.5 s) ---
                    # tyreTemperature 0 = surface only (the inner temperatures and pressures are then constants the
                    # game holds per compound: 80/85 C on real PS5 captures), 1 = surface & carcass
                    "tyre_temperature_model": TYRE_TEMPERATURE_MODEL.get(tail["tyreTemperature"]) if tail_ok else None,
                    "car_damage_setting": tail["carDamage"] if tail_ok else None,
                    "low_fuel_mode": tail["lowFuelMode"] if tail_ok else None,
                    "pit_lane_tyre_sim": tail["pitLaneTyreSim"] if tail_ok else None,
                },
            )
        )

    def _on_session_history(self, data: bytes, h: dict[str, Any], t: int, out: list[Emitted]) -> None:
        """One car's lap list (Session History, cycled through the cars at 20 Hz): emit ``CarLapHistory`` on change.

        Cost on the ingest thread per packet: a few byte reads, one slice of at most ~1.4 kB, a dict lookup and a
        bytes compare. The change key covers the completed laps, the lap time of the lap in progress (it is filled in
        at the flag without numLaps moving), the tyre stints, the car's AI flag and what LapData added (pit-lane laps,
        a lap the game ended); the lap in progress's sector updates are left out, so a car is decoded and emitted about
        once per lap. Only the 14-byte entries that changed are decoded again.

        Pit laps: real F1 25 (PS5, Austria, two AI stops checked against LapData pitStatus) records a stint's endLap
        as the lap BEFORE the in-lap (the car entered the pit lane on lap e+1 and stopped on lap e+2 after crossing
        the line in the pit lane), so laps e+1 and e+2 are the in- and out-lap; e = 0 is a stop on lap 1. Every lap
        LapData showed the car in the pit lane is a pit lap as well, whatever the stints say.
        """
        car = data[HIST_CAR]
        if car >= h["layout"].max_cars:
            return
        n = min(data[HIST_NUM_LAPS], P.NUM_LAP_HISTORY)
        n_st = min(data[HIST_NUM_STINTS], P.NUM_TYRE_STINTS)
        flags = self._ai_flags_raw
        flag_known = car < len(flags)  # a Participants packet of this session was seen
        ai = flags[car] if flag_known else None
        st = self._hist.get(car)
        if st is None:
            st = self._hist[car] = _CarHist(first_seen_lap=n)
        if flag_known and ai is not True:
            st.non_ai_seen = True  # human, or a 0 flag beyond numActiveCars (a human in a real online lobby)
        elif ai is True and st.non_ai_seen:
            st.ai_from_lap = n  # the AI took the car over: laps up to the one in progress were not (all) the AI's
            st.non_ai_seen = False
        seen = self._pit_seen.get(car)
        last = HIST_LAPS + HIST_LAP_SIZE * (n - 1) if n else HIST_LAPS
        key = (
            ai,
            data[HIST_CAR : HIST_CAR + 3],
            data[HIST_LAPS:last],
            data[last : last + 4] if n else b"",
            data[HIST_STINTS : HIST_STINTS + HIST_STINT_SIZE * n_st],
            len(seen) if seen else 0,
            self._ended_lap.get(car),
            st.ai_from_lap,
        )
        if key == st.key:
            return
        st.key = key
        t_s = float(h["sessionTime"])
        del st.raw[n:]  # a flashback can shrink numLaps
        del st.laps[n:]
        for i in range(n):
            off = HIST_LAPS + HIST_LAP_SIZE * i
            raw = data[off : off + HIST_LAP_SIZE]
            if i < len(st.raw) and st.raw[i] == raw:
                continue
            ms, s1ms, s1m, s2ms, s2m, s3ms, s3m, bits = _LAP_HISTORY_STRUCT.unpack(raw)
            prev = st.laps[i] if i < len(st.laps) else None
            if not ms:
                done: float | None = None
                lap = HistoryLap(i + 1, None, (None, None, None), None, None)
            else:
                same = prev is not None and prev.lap_time_ms == ms
                done = prev.completed_session_time_s if same and prev is not None else t_s
                lap = HistoryLap(
                    i + 1,
                    ms,
                    (_mins_ms(s1m, s1ms) or None, _mins_ms(s2m, s2ms) or None, _mins_ms(s3m, s3ms) or None),
                    bool(bits & LAP_VALID_BIT),
                    done,
                )
            if i < len(st.raw):
                st.raw[i] = raw
                st.laps[i] = lap
            else:
                st.raw.append(raw)
                st.laps.append(lap)
        pit: set[int] = set()
        for k in range(n_st):
            end = data[HIST_STINTS + HIST_STINT_SIZE * k]
            if end < STINT_END_CURRENT:  # 255 = the tyre currently fitted
                pit.update((end + 1, end + 2))
        st.stint_pits = frozenset(pit)
        st.best_lap = data[HIST_BEST_LAP] or None
        self._emit_history(car, st, h, t, out)

    def _emit_history(self, car: int, st: _CarHist, h: dict[str, Any], t: int, out: list[Emitted]) -> None:
        """``CarLapHistory`` of ``car`` from its state (the latest Session History plus what LapData added)."""
        flags = self._ai_flags_raw
        seen = self._pit_seen.get(car)
        uid = h["sessionUID"] or self._session_uid
        out.append(
            CarLapHistory(
                game=Game.F1_25,
                t_recv_ns=t,
                session_time_s=float(h["sessionTime"]),
                session_uid=str(uid) if uid else None,
                car_index=car,
                ai_controlled=flags[car] if car < len(flags) else None,
                is_player=car == h["playerCarIndex"],
                first_seen_lap=st.first_seen_lap,
                laps=tuple(st.laps),
                pit_laps=st.stint_pits | seen if seen else st.stint_pits,
                best_lap_number=st.best_lap,
                ai_from_lap=st.ai_from_lap,
                ended_lap=self._ended_lap.get(car),
            )
        )

    def _on_event(self, data: bytes, h: dict[str, Any], t: int, out: list[Emitted]) -> None:
        off = P.HEADER.size
        code = data[off : off + 4].decode("ascii", errors="replace")
        layout = h["layout"]
        details_def = layout.event_details.get(code)
        payload = details_def.unpack_from(data, off + 4) if details_def else {}
        kind = _EVENT_KIND.get(code, EventKind.OTHER)
        if code not in layout.event_details and code not in layout.event_codes_no_details:
            self.stats.count(f"EVENT_UNKNOWN_{code}")
        out.append(
            GameEvent(
                kind=kind,
                game=Game.F1_25,
                t_recv_ns=t,
                session_time_s=h["sessionTime"],
                code=code,
                payload={**payload, "name": enums.EVENT_NAMES.get(code, code), "player_idx": h["playerCarIndex"]},
            )
        )

    def _on_car_setups(self, data: bytes, h: dict[str, Any], t: int, out: list[Emitted]) -> None:
        idx = h["playerCarIndex"]
        s = P.CAR_SETUP.unpack_from(data, P.HEADER.size + idx * P.CAR_SETUP.size)
        params = {
            "front_wing": SetupParameter(key="front_wing", value=s["frontWing"], label="Front wing"),
            "rear_wing": SetupParameter(key="rear_wing", value=s["rearWing"], label="Rear wing"),
            "diff_on_throttle": SetupParameter(key="diff_on_throttle", value=s["onThrottle"], unit="%"),
            "diff_off_throttle": SetupParameter(key="diff_off_throttle", value=s["offThrottle"], unit="%"),
            "front_camber": SetupParameter(key="front_camber", value=s["frontCamber"], unit="deg"),
            "rear_camber": SetupParameter(key="rear_camber", value=s["rearCamber"], unit="deg"),
            "front_toe": SetupParameter(key="front_toe", value=s["frontToe"], unit="deg"),
            "rear_toe": SetupParameter(key="rear_toe", value=s["rearToe"], unit="deg"),
            "front_suspension": SetupParameter(key="front_suspension", value=s["frontSuspension"]),
            "rear_suspension": SetupParameter(key="rear_suspension", value=s["rearSuspension"]),
            "front_arb": SetupParameter(key="front_arb", value=s["frontAntiRollBar"]),
            "rear_arb": SetupParameter(key="rear_arb", value=s["rearAntiRollBar"]),
            "front_ride_height": SetupParameter(key="front_ride_height", value=s["frontSuspensionHeight"]),
            "rear_ride_height": SetupParameter(key="rear_ride_height", value=s["rearSuspensionHeight"]),
            "brake_pressure": SetupParameter(key="brake_pressure", value=s["brakePressure"], unit="%"),
            "brake_bias": SetupParameter(key="brake_bias", value=s["brakeBias"], unit="% front"),
            "engine_braking": SetupParameter(key="engine_braking", value=s["engineBraking"], unit="%"),
            "tyre_pressure_rl": SetupParameter(key="tyre_pressure_rl", value=s["rearLeftTyrePressure"], unit="psi"),
            "tyre_pressure_rr": SetupParameter(key="tyre_pressure_rr", value=s["rearRightTyrePressure"], unit="psi"),
            "tyre_pressure_fl": SetupParameter(key="tyre_pressure_fl", value=s["frontLeftTyrePressure"], unit="psi"),
            "tyre_pressure_fr": SetupParameter(key="tyre_pressure_fr", value=s["frontRightTyrePressure"], unit="psi"),
            "ballast": SetupParameter(key="ballast", value=s["ballast"]),
            "fuel_load": SetupParameter(key="fuel_load", value=s["fuelLoad"], unit="kg"),
        }
        setup = CarSetup(
            game=Game.F1_25,
            t_recv_ns=t,
            car_id=f"f1:team:{self._team_id}" if self._team_id is not None else None,
            track_id=self._track_id,
            parameters=params,
        )
        fp = setup.fingerprint()
        if fp != self._last_setup_fp:  # setups are re-sent ~2 Hz; only emit changes
            self._last_setup_fp = fp
            out.append(setup)


_EVENT_KIND: dict[str, EventKind] = {
    "SSTA": EventKind.SESSION_STARTED,
    "SEND": EventKind.SESSION_ENDED,
    "FTLP": EventKind.FASTEST_LAP,
    "FLBK": EventKind.FLASHBACK,
    "PENA": EventKind.PENALTY,
    "SCAR": EventKind.SAFETY_CAR,
    "RDFL": EventKind.RED_FLAG,
    "CHQF": EventKind.CHEQUERED_FLAG,
    "LGOT": EventKind.LIGHTS_OUT,
    "COLL": EventKind.COLLISION,
    "BUTN": EventKind.BUTTON,
}

_HANDLERS = {
    P.PacketId.MOTION: F1Adapter._on_motion,
    P.PacketId.MOTION_EX: F1Adapter._on_motion_ex,  # feat/technique
    P.PacketId.SESSION: F1Adapter._on_session,
    P.PacketId.LAP_DATA: F1Adapter._on_lap_data,
    P.PacketId.EVENT: F1Adapter._on_event,
    P.PacketId.PARTICIPANTS: F1Adapter._on_participants,
    P.PacketId.CAR_SETUPS: F1Adapter._on_car_setups,
    P.PacketId.CAR_TELEMETRY: F1Adapter._on_car_telemetry,
    P.PacketId.CAR_STATUS: F1Adapter._on_car_status,
    P.PacketId.CAR_DAMAGE: F1Adapter._on_car_damage,
    P.PacketId.SESSION_HISTORY: F1Adapter._on_session_history,
    P.PacketId.TYRE_SETS: F1Adapter._on_tyre_sets,  # race strategy (pitwall.strategy)
    P.PacketId.TIME_TRIAL: F1Adapter._on_time_trial,  # leaderboard: the EA rival
}
# Followers (AI pace's Session History, race strategy's TyreSets, the leaderboard's Time Trial): decoded only within the
# current session (uid 0 = the current one); they never start or reset a session (see ``decode``).
_FOLLOWERS = frozenset({P.PacketId.SESSION_HISTORY, P.PacketId.TYRE_SETS, P.PacketId.TIME_TRIAL})
