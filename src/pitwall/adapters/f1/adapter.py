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
    CarFrame,
    CarSetup,
    CarTiming,
    Emitted,
    EventKind,
    FieldSample,
    FracZone,
    FrameQuality,
    Game,
    GameEvent,
    LapCompletion,
    MarshalZone,
    Platform,
    RaceTiming,
    SessionInfo,
    SessionType,
    SetupParameter,
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
        "track_zones": FieldSupport(
            _S, "Session sector 2/3 starts (m) + MarshalZone[21]; format 2026 adds DRS and active-aero zones"
        ),
        "field_samples": FieldSupport(
            SupportLevel.RECORDED_VALIDATED,
            "Motion + LapData + CarTelemetry of every racing car, <= 10 Hz per car (FieldSample). Recorded: real PS5 "
            "format 2025 races (Austria, Austria Reverse, Silverstone, Silverstone Reverse, Monza, Montreal, Las "
            "Vegas, Miami, Melbourne): 16-19 AI cars with analog brake and full-lap distance; AI pit stops seen in "
            "the pit lane (Austria, 2 stops); format 2026 synthetic only",
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
SAFETY_CAR_NONE = 0  # Session.safetyCarStatus: 0 none, 1 full, 2 virtual, 3 formation lap
SAFETY_CAR_KNOWN = frozenset({0, 1, 2, 3})

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


def _field_offset(sd: StructDef, name: str) -> int:
    """Byte offset of scalar field ``name`` inside one ``sd`` element (packed, as the spec's offset tables)."""
    fmt = sd.struct.format[0]
    for fname, f in sd.fields:
        if fname == name:
            return struct.calcsize(fmt)
        fmt += f
    raise ValueError(f"{sd.name}: no field {name!r}")


_PIT_STATUS_OFFSET = _field_offset(P.LAP_DATA, "pitStatus")  # 34 (spec 5.2 offset table)
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
        self, field_hz: float = FIELD_HZ, *, field_include_player: bool = False, timing_hz: float = TIMING_HZ
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
        self._sector3: dict[str, Any] | None = None
        self._last_setup_fp: str | None = None
        self._format: int | None = None
        # field model (L0b): latest all-car packets kept by reference, decoded only when a field tick is due
        self._motion_raw: bytes | None = None
        self._lap_raw: bytes | None = None
        self._ai_controlled: tuple[bool | None, ...] = ()
        self._safety_car: bool | None = None
        self._field_last_t: float | None = None
        # race strategy (pitwall.strategy): CarStatus kept by reference, decoded only on a timing tick
        self._timing_last_t: float | None = None
        self._timing_pits: bytes | None = None  # every car's LapData.pitStatus at the last tick
        self._status_raw: bytes | None = None
        self._session_type_id: int | None = None
        self._tyre_sets_key: bytes | None = None

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
        if pid in _FOLLOWERS and uid and self._session_uid and uid != self._session_uid:
            # race strategy (pitwall.strategy): a packet that only follows a session (TyreSets) never starts one,
            # for the same reason as above (a stale-UID packet must not flush the session's caches)
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

    def _on_lap_data(self, data: bytes, h: dict[str, Any], t: int, out: list[Emitted]) -> None:
        idx = h["playerCarIndex"]
        lap = P.LAP_DATA.unpack_from(data, P.HEADER.size + idx * P.LAP_DATA.size)
        self._lap = lap
        self._lap_frame = h["frameIdentifier"]
        self._lap_raw = data
        lap_num = lap["currentLapNum"]
        prev = self._prev_lap_num
        if prev is not None and lap_num == prev + 1 and self._prev_lap_snapshot is not None:
            snap = self._sector_snapshot(prev) or self._prev_lap_snapshot
            last_ms = lap["lastLapTimeInMS"] or None
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
                )
            )
        elif (
            prev is not None
            and lap_num == prev
            and lap["resultStatus"] == RESULT_FINISHED
            and self._prev_result != RESULT_FINISHED
            and lap["lastLapTimeInMS"]
            and self._prev_lap_snapshot is not None
        ):
            # Final lap of a race: the lap number does not advance at the chequered flag; instead the result
            # status turns "finished" and lastLapTimeInMS updates (observed in F1 25 v1.26 on PS5).
            snap = self._sector_snapshot(lap_num) or self._prev_lap_snapshot
            last_ms = lap["lastLapTimeInMS"]
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
                )
            )
        if lap["sector"] == 2:
            # Sector times are zeroed as the car crosses the line - sometimes a packet BEFORE the lap number or
            # result status changes (observed on PS5) - so keep the last sector-3 snapshot of each lap.
            self._sector3 = lap
        self._prev_lap_num = lap_num
        self._prev_result = lap["resultStatus"]
        if lap["resultStatus"] != RESULT_FINISHED:
            self._prev_lap_snapshot = lap  # keep the last in-race snapshot for the final-lap sectors
        if self.timing_period_s is not None:  # race strategy (pitwall.strategy)
            self._timing_tick(data, h, t, out)

    # --- race strategy (pitwall.strategy) ---------------------------------------------------------------------
    def _timing_tick(self, data: bytes, h: dict[str, Any], t: int, out: list[Emitted]) -> None:
        """Emit one ``RaceTiming`` (every racing car) when a timing tick is due, at most once per
        ``timing_period_s`` of game clock (same cadence rules as ``_field_tick``: replays decimate like live play, a
        clock that jumps back re-arms at once), and at once on any car's pit-status change, so pit-lane entry and exit
        are timed to the packet (the pit-lane timer resets at the exit, between two regular ticks). Time trial has no
        field to race, so nothing is emitted there. Cost on the ingest thread: one strided slice of the pit-status
        bytes on every LapData packet; on a tick one ``iter_unpack`` over the LapData array (and over the last
        CarStatus array kept by reference), then one small frozen object per car."""
        if self._session_type_id == SESSION_TYPE_TIME_TRIAL:
            return
        period = self.timing_period_s
        assert period is not None
        layout: P.F1Layout = h["layout"]
        ts = _TIMING_STRUCTS[layout.packet_format]
        base = P.HEADER.size
        pits = data[base + _PIT_STATUS_OFFSET : base + ts.lap_bytes : P.LAP_DATA.size]  # one byte per car
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
            f.ers_store_j = st["ersStoreEnergy"]
            f.ers_deploy_mode = st["ersDeployMode"]
            f.tyre_compound = enums.VISUAL_COMPOUNDS.get(st["visualTyreCompound"])
            f.tyre_age_laps = st["tyresAgeLaps"]
            f.brake_bias_front_pct = float(st["frontBrakeBias"])
            f.traction_control = st["tractionControl"]
            f.abs_active = bool(st["antiLockBrakes"])
        dmg = self._damage
        if dmg is not None:
            f.tyre_wear_pct = Wheels.from_rl_rr_fl_fr(list(dmg["tyresWear"]))
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
        self._damage = P.CAR_DAMAGE.unpack_from(data, P.HEADER.size + idx * P.CAR_DAMAGE.size)

    def _on_participants(self, data: bytes, h: dict[str, Any], t: int, out: list[Emitted]) -> None:
        idx = h["playerCarIndex"]
        pd = h["layout"].participant
        part = pd.unpack_from(data, P.HEADER.size + P.PARTICIPANTS_HEAD.size + idx * pd.size)
        self._team_id = part["teamId"]
        self._platform = enums.PLATFORMS.get(part["platform"], Platform.UNKNOWN)
        if self.field_period_s is not None or self.timing_period_s is not None:
            # Who is AI (every 5 s): the field model learns from AI cars only by default (human opponents' data is a
            # privacy question). Slots past numActiveCars are zero-filled, so their "0" is unknown, not "human".
            fs = _FIELD_STRUCTS[h["layout"].packet_format]
            n_active = P.PARTICIPANTS_HEAD.unpack_from(data, P.HEADER.size)["numActiveCars"]
            start = P.HEADER.size + P.PARTICIPANTS_HEAD.size
            rows = fs.participant.iter_unpack(memoryview(data)[start : start + fs.participant_bytes])
            self._ai_controlled = tuple(bool(r[0]) if i < n_active else None for i, r in enumerate(rows))

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

        self._paused = bool(head["gamePaused"])
        self._spectating = bool(head["isSpectating"])
        self._session_type_id = head["sessionType"]
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
                extra={
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
                },
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
    P.PacketId.SESSION: F1Adapter._on_session,
    P.PacketId.LAP_DATA: F1Adapter._on_lap_data,
    P.PacketId.EVENT: F1Adapter._on_event,
    P.PacketId.PARTICIPANTS: F1Adapter._on_participants,
    P.PacketId.CAR_SETUPS: F1Adapter._on_car_setups,
    P.PacketId.CAR_TELEMETRY: F1Adapter._on_car_telemetry,
    P.PacketId.CAR_STATUS: F1Adapter._on_car_status,
    P.PacketId.CAR_DAMAGE: F1Adapter._on_car_damage,
    P.PacketId.TYRE_SETS: F1Adapter._on_tyre_sets,  # race strategy (pitwall.strategy)
}
# race strategy (pitwall.strategy): decoded only within the current session; never reset it (see ``decode``)
_FOLLOWERS = frozenset({P.PacketId.TYRE_SETS})
