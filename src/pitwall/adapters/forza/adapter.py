"""Forza "Data Out" adapter (FM7, Forza Motorsport 2023, Forza Horizon 4/5/6) -> unified model.

Forza pushes one self-contained datagram per physics/render frame (60 Hz on FM7/FM2023; FH6 at the game's
frame rate) with no header, no session id, no sector data and no "lap completed" event. Everything pitwall
needs beyond the raw channels is therefore *derived* here, deterministically and in O(1) per packet, and every
derivation is labelled as such in ``AdapterInfo``:

Format / game
    Identified by datagram length only (see ``packets.py``): 232 Sled, 311 FM7 Dash, 324 Horizon, 331 FM2023.
    Any other length is rejected. 232 and 311/331 are Forza Motorsport; 324 is Forza Horizon (FH4/5/6 cannot
    be told apart). ``self.info`` switches to the matching ``AdapterInfo`` when a session starts.

Sessions (no session id on the wire)
    A session starts at the first ``IsRaceOn=1`` packet and is split when the title/format, ``CarOrdinal`` or
    (FM2023) ``TrackOrdinal`` changes, when ``CurrentRaceTime`` resets (drops below ``RESTART_RACE_TIME_S`` or by
    more than ``RESTART_RACE_TIME_DROP_S`` - a rewind is shorter than that), or when ``LapNumber`` falls by more
    than one. ``IsRaceOn=0`` packets before any session are ignored (menus must not create empty sessions);
    inside a session they become ``PAUSED | NOT_RACING`` frames with every channel ``None`` (the docs do not
    say the payload is meaningful then). ``SESSION_END_IDLE_S`` of continuous ``IsRaceOn=0`` ends the session
    (Forza Motorsport keeps streaming in menus, so the UDP idle timeout would never fire). The session uid is
    ``forza:<format>:<t_recv_ns of its first packet>`` - deterministic for replays.

Late datagrams
    UDP can deliver a datagram after its successor (Wi-Fi from an Xbox). A Dash packet whose race clock is
    behind the previous packet's by less than ``REWIND_MIN_S`` is such a late packet - a rewind is a deliberate
    jump of seconds - and is dropped whole (``stats.by_type['out_of_order']``). Processed, a late packet at the
    line would re-trigger the crossing (a duplicate ``LapCompletion`` whose one-sample lap overwrites the lap
    already stored under that number) and anywhere else would flag the lap as a flashback. A ``LapNumber``
    regression without a usable race clock is dropped for the same reason. More than ``LATE_MAX_STREAK``
    consecutive "late" packets are not reordering but the stream itself going back, so the next one is accepted
    as the new present: nothing can be dropped for good. ``TimestampMS`` is not used: whether a rewind rolls it
    back is undocumented, and mistaking a rewind for reordering would drop seconds of data.

Lap distance (derived)
    ``DistanceTraveled`` is cumulative metres since driving started (an odometer), so lap distance is
    ``DistanceTraveled - DistanceTraveled at the packet where LapNumber incremented``. It follows the line the
    car actually drove, not a fixed centreline: a 1 % longer line puts the end of a 4 km lap ~40 m further on,
    so corner positions drift by up to that much late in a lap. The origin of a lap is only known if its start
    was *observed*: until the first line crossing of a session (joined mid-lap, out-lap from the pits, race lap
    1 from the grid) ``lap_distance_m`` is ``None`` - unknown stays unknown - so those laps are never assembled
    as if they had started on the line. Start distances are remembered per lap so a rewind back across the line
    restores the earlier lap's origin. A position jump the odometer does not account for (a reset to track, or a
    rewind that does not roll ``DistanceTraveled`` back - both undocumented) un-anchors the lap, as the GT7
    adapter does: ``lap_distance_m`` is ``None`` until the next crossing, and the lap completes with
    ``valid=False`` - its trace stops at the reset, and before the track length is known nothing downstream
    could tell that truncated lap from a complete one, so it must never become a reference.

Track length (derived)
    The driven length of every full lap without a rewind or reset is measured, and ``track_length_m`` is the
    *shortest* of the last ``LAP_LENGTH_SAMPLES`` that lies within ``LAP_LENGTH_SPREAD`` of their median.
    ``LapAssembler`` calls a lap incomplete when it ends more than 60 m short of the track length - a tolerance
    made for F1's fixed centreline (60 m is 0.3 % of the Nordschleife) - so reporting the median would mark
    every lap driven on a slightly tighter line incomplete and keep it out of analysis. Laps shorter than the
    spread allows (a cut, an unnoticed reset) still are. The median goes out as
    ``extra['track_length_nominal_m']`` and ``extra['lap_distance_source']`` marks the distance as derived, so
    consumers can apply a relative tolerance instead.

Lap completion
    ``LapNumber`` (laps completed) incrementing by one completes our 1-based lap ``LapNumber`` with
    ``LastLap`` as its time. Whether ``LastLap`` updates in the same packet is undocumented, so a completion
    is only emitted with a *fresh* ``LastLap``: one that differs from the previous lap's, or - because two laps
    can take exactly as long when a game quantises lap times - an unchanged value that agrees with the lap's own
    clock (``CurrentLap`` of the last packet before the line, within ``LAST_LAP_MATCH_S``; a stale value can then
    be off by at most that much). Otherwise the crossing packet and the frames after it are held back - for at
    most ``LAST_LAP_HOLD_S`` and ``LAST_LAP_HOLD_MAX_FRAMES`` - and released *after* the ``LapCompletion`` as
    soon as ``LastLap`` changes, or with ``lap_time_ms=None`` on timeout. Releasing in that order is what
    ``LapAssembler`` needs to attach the time to the right lap. The hold is deliberately short because held
    frames also delay the live view and braking cues (``CueEngine`` drops a cue rather than call it late); how
    long the game really lags is unverified, and a slower ``LastLap`` costs that lap its time, never its trace.
    ``IsRaceOn=0`` packets during a hold are held as well; their ``LastLap`` (the payload of a stopped race is
    undocumented, and Forza Motorsport stops the race at the flag) is used only if it is fresh *and* agrees
    with the lap's own clock. A stream that stops during a hold (FH6 sends nothing after the finish, so the
    crossing can be the race's last datagram) is settled by ``drain()``, which the router calls before ending
    the session. A ``LastLap`` change *without* an increment more than ``LATE_LAST_LAP_WINDOW_S`` after the
    last crossing is treated as a final race lap that the game did not count (F1 25 behaves that way; Forza's
    behaviour is unverified): the lap completes and later frames are ``NOT_RACING`` (cool-down lap).

Track identity
    FM2023 sends ``TrackOrdinal`` -> ``forza:<ordinal>``. FM7 and Horizon send nothing, so (like GT7 in the
    community tools) the start/finish crossing identifies the circuit: once a full lap has been observed - one
    without a rewind or reset, starting at a crossing without a reset - the track id is
    ``forza_fp:<family>:<x>:<z>:<heading deg>:<lap length m>`` from the first such crossing of the session.
    Ids are matched to previously seen fingerprints with tolerances (``TrackFingerprint.matches``) rather than
    quantised into cells, so a crossing a few metres to one side of a cell boundary cannot split a circuit, and
    layouts that share a start line are kept apart by heading and lap length. Pass the ids already in the
    database as ``known_track_ids`` so they stay stable across restarts. Synthetic sessions get a
    ``synthetic:forza_fp:...`` id and never read or extend that registry. Horizon free roam and sprints have no
    laps, so they get no track id, no lap distance and no completions; frames still flow to the live view.

Units: speed m/s -> km/h; pedals 0..255 -> 0..1; ``Steer`` -127..127 -> -1..1 (left negative, matching
pitwall); accelerations m/s^2 (community) -> g; lap times s -> ms; tyre temperatures degF (community) -> degC;
FM2023 tyre wear 0..1 fraction (community) -> %. Fuel is a 0..1 tank fraction with no capacity, so the absolute
``fuel_kg``/``fuel_litres`` stay ``None`` and the fraction is reported in ``SessionInfo.extra['fuel_fraction']``.
Gear: 1..10 are forward gears; 0 and anything else are ``None`` because the reverse/neutral encoding is
undocumented (settle it with a recorded capture before mapping it). Times are float32 seconds: values outside
[0, ``MAX_TIME_S``) are ``None``, as are world positions beyond ``MAX_WORLD_M`` - one garbage datagram must not
produce an integer that orjson or SQLite cannot store, or mint a track fingerprint.
"""

from __future__ import annotations

import logging
import math
import statistics
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, ClassVar

from pitwall.adapters.base import AdapterInfo, DecodeStats, FieldSupport, PacketRejected, SupportLevel
from pitwall.adapters.forza import packets as P
from pitwall.model.synthetic import SYNTHETIC_SESSION_UID
from pitwall.model.telemetry import (
    CarFrame,
    Emitted,
    EventKind,
    FrameQuality,
    Game,
    GameEvent,
    LapCompletion,
    Platform,
    SessionInfo,
    Wheels,
)

log = logging.getLogger(__name__)

# Suggested listening port. Forza lets the user type any port; FH6's official doc says to avoid 5200-5300
# because the game binds its own socket there, so the suggestion sits just outside that range.
DEFAULT_PORT = 5301

STANDARD_GRAVITY = 9.80665  # m/s^2 per g
MAX_FORWARD_GEAR = 10  # largest gearbox we expect; a higher raw value is reported as unknown, never guessed

LAST_LAP_HOLD_S = 0.1  # max wait for LastLap to update after LapNumber increments (held frames delay live cues)
LAST_LAP_HOLD_MAX_FRAMES = 8  # hard bound on held frames (FH6 can stream faster than 60 Hz)
LAST_LAP_MATCH_S = 0.05  # unchanged LastLap accepted if it is this close above the lap's own clock (3 frames)
LAST_LAP_MATCH_BELOW_S = 0.005  # ...or this close below it (float32 rounding)
LATE_LAST_LAP_WINDOW_S = 5.0  # a LastLap change this soon after a crossing belongs to that crossing
SESSION_INFO_INTERVAL_S = 0.5
SESSION_END_IDLE_S = 300.0  # continuous IsRaceOn=0 that ends a session (long enough to survive a pause)
RESTART_RACE_TIME_S = 1.0  # race clock reset to below this -> restart
RESTART_RACE_TIME_DROP_S = 30.0  # race clock going back further: a restart (rewind length is undocumented; assumed
#   shorter - a longer rewind would split the session, which loses no data)
REWIND_MIN_S = 0.25  # race clock back by less than this: a late (reordered) datagram, not a rewind. UDP reorders
#   by a few frames at most; a rewind is a deliberate jump of seconds.
LATE_MAX_STREAK = 8  # more consecutive "late" packets than this are not reordering: the stream itself went back
#   (a tiny rewind, or a race clock that is unreadable) and the next one is accepted, so nothing is dropped for good
REWIND_EVENT_MIN_INTERVAL_S = 2.0  # one FLASHBACK event per rewind, even if the game scrubs back frame by frame
TELEPORT_FACTOR = 1.5  # a move is a reset/teleport beyond FACTOR x the distance the car can have covered ...
TELEPORT_SLACK_M = 10.0  # ... plus this (60 Hz sampling, position noise)
MIN_LAP_LENGTH_M = 200.0  # measured "laps" shorter than this are glitches, not circuits
MAX_LAP_LENGTH_M = 200_000.0  # ...and longer than this are a corrupt odometer (Horizon's longest circuits: tens of km)
LAP_LENGTH_SAMPLES = 5  # recent measured laps the derived track length is based on
LAP_LENGTH_SPREAD = 0.02  # measured laps more than this fraction below the median are outliers (cut / reset)
LAP_START_MEMORY = 3  # lap origins kept for rewinds back across the line
MAX_TIME_S = 86_400.0  # a Forza clock (float32 s) outside [0, 1 day) is garbage, never a time
MAX_WORLD_M = 1_000_000.0  # world coordinates beyond +-1000 km are garbage (maps are tens of km across)
MAX_ODOMETER_M = 100_000_000.0  # DistanceTraveled beyond 100,000 km is garbage

LAP_DISTANCE_SOURCE = "derived:distance_traveled"  # SessionInfo.extra['lap_distance_source']

DRIVETRAINS = {0: "FWD", 1: "RWD", 2: "AWD"}

_M = SupportLevel.SPEC_IMPLEMENTED  # Turn 10's official field list (FM7 / FM2023)
_C = SupportLevel.COMMUNITY_DOCUMENTED
_P = SupportLevel.PARTIAL
_U = SupportLevel.UNSUPPORTED


def _fields(level: SupportLevel, motorsport: bool) -> dict[str, FieldSupport]:
    """Per-field support. ``level`` is the evidence for the layout itself: official for FM7/FM2023, community for
    FH4/FH5 (FH6 is official but the three Horizon titles cannot be told apart)."""
    return {
        "speed_kph": FieldSupport(level, "Dash.Speed (m/s -> km/h); Sled format: derived |Velocity| (m/s -> km/h)"),
        "throttle": FieldSupport(level, "Dash.Accel (u8 0..255 -> 0..1)"),
        "brake": FieldSupport(level, "Dash.Brake (u8 0..255 -> 0..1)"),
        "clutch": FieldSupport(level, "Dash.Clutch (u8 0..255 -> 0..1)"),
        "steering": FieldSupport(level, "Dash.Steer (s8 -127 full left..127 full right -> -1..1)"),
        "gear": FieldSupport(
            _P, "Dash.Gear: 1..10 forward; 0 / other values -> None (reverse/neutral encoding undocumented)"
        ),
        "rpm": FieldSupport(level, "Sled.CurrentEngineRpm"),
        "max_rpm": FieldSupport(level, "Sled.EngineMaxRpm"),
        "pos_x_m": FieldSupport(level, "Dash.PositionX (world m)"),
        "pos_y_m": FieldSupport(level, "Dash.PositionY (world m, vertical)"),
        "pos_z_m": FieldSupport(level, "Dash.PositionZ (world m)"),
        "vel_x_mps": FieldSupport(_U, "Sled.Velocity* is car-local, not world-frame: not mapped"),
        "g_lat": FieldSupport(_C, "Sled.AccelerationX / 9.80665 (car-local, + = right; m/s^2 per community docs)"),
        "g_lon": FieldSupport(_C, "Sled.AccelerationZ / 9.80665 (+ = accelerating forwards)"),
        "g_vert": FieldSupport(_C, "Sled.AccelerationY / 9.80665 (whether gravity is included is undocumented)"),
        "yaw_rad": FieldSupport(level, "Sled.Yaw (rad); Pitch/Roll likewise"),
        "lap_number": FieldSupport(level, "Dash.LapNumber (laps completed) + 1"),
        "lap_distance_m": FieldSupport(
            _P,
            "derived: Dash.DistanceTraveled minus its value at the observed line crossing (driven line, not a "
            "centreline); None until the first crossing of a session and after a reset to track",
        ),
        "total_distance_m": FieldSupport(level, "Dash.DistanceTraveled (m, cumulative since driving started)"),
        "current_lap_time_ms": FieldSupport(level, "Dash.CurrentLap (s -> ms)"),
        "last_lap_time_ms": FieldSupport(level, "Dash.LastLap (s -> ms; 0 -> None)"),
        "best_lap_ms": FieldSupport(level, "Dash.BestLap (s -> ms; 0 -> None) in SessionInfo.extra['best_lap_ms']"),
        "race_position": FieldSupport(level, "Dash.RacePosition (0 -> None)"),
        "lap_completion": FieldSupport(
            _P,
            f"derived: LapNumber increment, time = Dash.LastLap (held up to {LAST_LAP_HOLD_S:g} s for a stale "
            "LastLap, else untimed); valid=False only for a lap with a reset to track (trace un-anchored)",
        ),
        "tyre_surface_temp_c": FieldSupport(
            _C, "Dash.TireTemp* (one value per tyre; degF per community docs -> degC; surface vs core undocumented)"
        ),
        "tyre_inner_temp_c": FieldSupport(_U, "Forza sends a single temperature per tyre"),
        "tyre_wear_pct": FieldSupport(_C, "FM2023 only: TireWear* (0..1 wear fraction per community -> %)")
        if motorsport
        else FieldSupport(_U, "not sent by Horizon"),
        "tyre_pressure_psi": FieldSupport(_U, "not sent"),
        "brake_temp_c": FieldSupport(_U, "not sent"),
        "fuel_kg": FieldSupport(
            _U, "Dash.Fuel is a 0..1 tank fraction without capacity (fraction in SessionInfo.extra['fuel_fraction'])"
        ),
        "fuel_litres": FieldSupport(_U, "as fuel_kg"),
        "sector": FieldSupport(_U, "no sector data"),
        "lap_invalid": FieldSupport(_U, "no lap validity flag"),
        "pit_status": FieldSupport(_U, "no pit state"),
        "track_id": FieldSupport(
            level if motorsport else _P,
            "FM2023: Dash TrackOrdinal -> 'forza:<ordinal>'; FM7 / Horizon: derived start/finish fingerprint "
            "'forza_fp:...' after the first full lap without a rewind or reset",
        ),
        "track_length_m": FieldSupport(
            _P,
            f"derived: shortest recent driven lap (DistanceTraveled) within {LAP_LENGTH_SPREAD:.0%} of the median; "
            "median in SessionInfo.extra['track_length_nominal_m']",
        ),
        "car_id": FieldSupport(level, "Sled.CarOrdinal -> 'forza:<title>:car:<ordinal>'"),
        "session_uid": FieldSupport(
            _P, "derived: no session id on the wire (split on car/track/format change or race-clock reset)"
        ),
        "session_type": FieldSupport(_U, "not sent"),
        "weather": FieldSupport(_U, "not sent (puddle depth / rumble only)"),
        "setup": FieldSupport(_U, "not sent"),
        "drs_open": FieldSupport(_U, "not in Turn 10's Data Out field list"),
        "ers_store_j": FieldSupport(_U, "not in Turn 10's Data Out field list"),
        "damage": FieldSupport(_U, "not in Turn 10's Data Out field list"),
        "track_zones": FieldSupport(_U, "no sector, marshal-zone or flag data"),
        "field_samples": FieldSupport(_U, "Data Out describes the player's car only"),
        "buttons": FieldSupport(_U, "no wheel-button data"),
    }


FORZA_MOTORSPORT_INFO = AdapterInfo(
    game=Game.FORZA_MOTORSPORT,
    name="Forza Motorsport Data Out (FM7 Dash 311 B, Forza Motorsport 2023 Dash 331 B, Sled 232 B)",
    transport="udp",
    default_port=DEFAULT_PORT,
    ground_plane=("pos_x_m", "pos_z_m"),  # PositionY is vertical
    platforms={
        Platform.PC: SupportLevel.SPEC_IMPLEMENTED,
        Platform.XBOX: SupportLevel.COMMUNITY_DOCUMENTED,
    },
    fields=_fields(_M, motorsport=True),
    notes=(
        "Implemented from Turn 10's official field list + community packet sizes; synthetic-validated only.",
        "Select the 'Dash' packet format in game: 'Sled' (232 B) has no position, lap, input or tyre data.",
        "Lap distance is the driven distance (DistanceTraveled), not a centreline: a 1 % longer line moves the end"
        " of a 4 km lap ~40 m. The first lap of a session (no observed line crossing) is not assembled.",
        "A lap whose time (LastLap) lags the lap counter by more than 0.1 s is stored untimed (unverified game"
        " behaviour: the hold is kept short so live cues are not delayed).",
        "No sector times, lap validity, pit state, weather or setup in the protocol.",
        "Gear 0 / reverse / neutral encoding undocumented: reported as None until verified with a capture.",
    ),
)

FORZA_HORIZON_INFO = AdapterInfo(
    game=Game.FORZA_HORIZON,
    name="Forza Horizon 4/5/6 Data Out (324 B)",
    transport="udp",
    default_port=DEFAULT_PORT,
    ground_plane=("pos_x_m", "pos_z_m"),
    platforms={
        Platform.PC: SupportLevel.COMMUNITY_DOCUMENTED,
        Platform.XBOX: SupportLevel.COMMUNITY_DOCUMENTED,
        Platform.PS5: SupportLevel.UNVERIFIED,  # FH5 on PS5: no source confirms Data Out exists
    },
    fields=_fields(_C, motorsport=False),
    notes=(
        "FH4/FH5 layout is community-documented; FH6's (same 324 B) is official. Synthetic-validated only.",
        "Open world: free roam and sprints have no laps, so no lap distance, completions or track id.",
        "Track identity is a derived start/finish fingerprint (position, heading, measured lap length).",
        "FH6 sends nothing in menus, pauses, replays or rewinds; FH5 on PS5 is unverified.",
    ),
)

_INFO_BY_GAME = {Game.FORZA_MOTORSPORT: FORZA_MOTORSPORT_INFO, Game.FORZA_HORIZON: FORZA_HORIZON_INFO}


# ---------------------------------------------------------------------------------------------- track fingerprints
@dataclass(frozen=True, slots=True)
class TrackFingerprint:
    """Start/finish signature of a circuit for titles that send no track id (FM7, Horizon).

    The id encodes the first observation (rounded to 1 m / 1 deg), so it can be parsed back and matched against
    later observations with tolerances. Tolerances: the crossing point moves with the car's lateral position on
    a wide straight and with 60 Hz sampling (1-2 m); heading at the line varies by a few degrees; the driven lap
    length varies by about 1 % with the racing line.
    """

    family: str  # packets.FormatLayout.family: world coordinates are only comparable within one title family
    x_m: float
    z_m: float
    heading_deg: float  # [0, 360): yaw at the crossing, in Forza's own (undocumented) convention
    length_m: float

    PREFIX: ClassVar[str] = "forza_fp"
    MAX_DISTANCE_M: ClassVar[float] = 60.0
    MAX_HEADING_DEG: ClassVar[float] = 45.0
    LENGTH_TOLERANCE: ClassVar[float] = 0.04

    @property
    def track_id(self) -> str:
        return (
            f"{self.PREFIX}:{self.family}:{round(self.x_m)}:{round(self.z_m)}:"
            f"{round(self.heading_deg) % 360}:{round(self.length_m)}"
        )

    @classmethod
    def parse(cls, track_id: str) -> TrackFingerprint | None:
        parts = track_id.split(":")
        if len(parts) != 6 or parts[0] != cls.PREFIX:
            return None
        try:
            x, z, h, length = (float(p) for p in parts[2:])
        except ValueError:
            return None
        if not all(math.isfinite(v) for v in (x, z, h, length)) or length <= 0:
            return None
        return cls(parts[1], x, z, h % 360.0, length)

    def matches(self, other: TrackFingerprint) -> bool:
        if self.family != other.family:
            return False
        if math.hypot(self.x_m - other.x_m, self.z_m - other.z_m) > self.MAX_DISTANCE_M:
            return False
        dh = abs((self.heading_deg - other.heading_deg + 180.0) % 360.0 - 180.0)
        if dh > self.MAX_HEADING_DEG:
            return False
        return abs(self.length_m - other.length_m) <= self.LENGTH_TOLERANCE * max(self.length_m, other.length_m)


# ---------------------------------------------------------------------------------------------- per-session state
@dataclass(slots=True)
class _PendingLap:
    lap_number: int  # our 1-based number of the lap that just completed
    baseline_s: float | None  # LastLap must differ from this to be the new lap's time
    lap_clock_s: float | None  # CurrentLap just before the line: corroborates a LastLap read while the race is off
    valid: bool | None  # False: the car was reset during the lap (its trace stops there)
    deadline_ns: int
    session_time_s: float | None


@dataclass(slots=True)
class _Session:
    uid: str
    synthetic: bool
    layout: P.FormatLayout
    car_ordinal: int
    track_ordinal: int | None
    track_id: str | None = None
    track_id_source: str | None = None
    lap_lengths: list[float] = field(default_factory=list)  # driven lengths of recent trusted full laps
    track_length_m: float | None = None
    sf_crossing: tuple[float, float, float] | None = None  # (x, z, yaw) at the first trusted crossing
    prev_lap_raw: int | None = None
    prev_race_time_s: float | None = None
    prev_current_lap_s: float | None = None  # CurrentLap of the previous packet: the lap's own clock at the line
    prev_pos: tuple[float, float, float] | None = None
    prev_dist: float | None = None
    prev_speed: float | None = None
    prev_t_ns: int | None = None
    last_t_ns: int | None = None  # receive time of the latest accepted packet (race on or off)
    late_streak: int = 0  # consecutive packets dropped as late (bounded by LATE_MAX_STREAK)
    lap_start_dist: dict[int, float] = field(default_factory=dict)  # raw LapNumber -> DistanceTraveled at its start
    lap_compromised: bool = False  # rewind or reset since the last crossing: no lap length / fingerprint from it
    unanchored: bool = False  # reset since the last crossing: lap distance no longer matches the track
    last_lap_baseline_s: float | None = None
    last_crossing_ns: int | None = None
    finished_lap_raw: int | None = None  # LapNumber at a completion the game did not count (final race lap)
    pending: _PendingLap | None = None
    held: list[CarFrame] = field(default_factory=list)
    race_off_since_ns: int | None = None
    last_info_ns: int | None = None
    last_rewind_event_ns: int | None = None
    snapshot: dict[str, Any] = field(default_factory=dict)  # latest slow values for SessionInfo.extra


def _finite(v: Any) -> float | None:
    """NaN/inf from a corrupt or uninitialised field become unknown rather than poisoning analysis."""
    f = float(v)
    return f if math.isfinite(f) else None


def _bounded(v: Any, limit: float) -> float | None:
    """Finite and within +-``limit``, else unknown (a float32 can hold 3e38 metres)."""
    f = _finite(v)
    return f if f is not None and abs(f) < limit else None


def _time_s(v: Any) -> float | None:
    """A Forza clock value (float32 seconds), or ``None`` outside [0, ``MAX_TIME_S``): converted to integer
    milliseconds, an absurd finite value would overflow orjson (/ws/live) and SQLite (lap rows)."""
    f = _finite(v)
    return f if f is not None and 0.0 <= f < MAX_TIME_S else None


def _ms(seconds: float | None) -> int | None:
    return round(seconds * 1000.0) if seconds is not None and 0.0 < seconds < MAX_TIME_S else None


def _unit(raw: int) -> float:
    return raw / 255.0


def _f_to_c(f: float | None) -> float | None:
    return None if f is None else (f - 32.0) * 5.0 / 9.0


def _g(a: float | None) -> float | None:
    return None if a is None else a / STANDARD_GRAVITY


def _gear(raw: int) -> int | None:
    return raw if 1 <= raw <= MAX_FORWARD_GEAR else None


def _wheels(raw: dict[str, Any], prefix: str) -> list[float | None]:
    return [_finite(raw[f"{prefix}{w}"]) for w in P.WHEEL_SUFFIXES]


def _position(raw: dict[str, Any]) -> tuple[float, float, float] | None:
    x, y, z = (_bounded(raw[k], MAX_WORLD_M) for k in ("PositionX", "PositionY", "PositionZ"))
    return None if x is None or y is None or z is None else (x, y, z)


def _odometer(raw: dict[str, Any]) -> float | None:
    return _bounded(raw["DistanceTraveled"], MAX_ODOMETER_M)


class ForzaAdapter:
    """Stateful decoder for one Forza Data Out stream (one game instance, any supported title).

    ``known_track_ids``: fingerprint track ids already known (e.g. from the database) so FM7/Horizon circuits
    keep the same id across restarts. The fingerprint registry survives ``reset()``; session state does not.

    Beyond the ``GameAdapter`` protocol the adapter has ``drain()``: when the stream stops, the router must call
    it (and handle what it returns) before ending the session, or a lap completion still waiting for its
    ``LastLap`` - typically the last lap of a race - is lost with ``reset()``.
    """

    def __init__(self, known_track_ids: Iterable[str] = ()) -> None:
        self.info = FORZA_MOTORSPORT_INFO
        self.stats = DecodeStats()
        self._known: list[TrackFingerprint] = []
        for tid in known_track_ids:
            self.register_track_id(tid)
        self._session: _Session | None = None

    def reset(self) -> None:
        """Forget the session. Anything still held is discarded: call ``drain()`` first to release it."""
        self._session = None

    def drain(self) -> list[Emitted]:
        """Release what is held back because the stream stopped (the lap completion waiting for ``LastLap``).

        The lap is completed untimed - its time never arrived - and the held frames follow the completion, in
        the order ``LapAssembler`` needs. Without this, a stream that ends inside the hold (FH6 sends nothing
        after the finish, so the crossing can be the race's last datagram) would lose its final lap: the session
        manager would flush it as incomplete and ``reset()`` would drop the completion. Idempotent; the session
        itself is kept (``reset()`` ends it).
        """
        s = self._session
        out: list[Emitted] = []
        if s is not None and s.pending is not None:
            self.stats.count("last_lap_drained")
            t = s.last_t_ns if s.last_t_ns is not None else s.pending.deadline_ns
            self._resolve_pending(s, None, t, out)
        return out

    def register_track_id(self, track_id: str) -> bool:
        """Remember a fingerprint id; returns False if ``track_id`` is not a Forza fingerprint."""
        fp = TrackFingerprint.parse(track_id)
        if fp is None:
            return False
        if fp not in self._known:
            self._known.append(fp)
        return True

    @property
    def known_track_ids(self) -> list[str]:
        return [fp.track_id for fp in self._known]

    # ------------------------------------------------------------------ structural validation
    def can_decode(self, data: bytes) -> bool:
        try:
            if len(data) not in P.LAYOUTS:
                return False
            race_on = int.from_bytes(data[0:4], "little", signed=True)
            if race_on not in (0, 1):
                return False
            rpms = P.SLED.struct.unpack_from(data, 0)[2:5]  # EngineMaxRpm, EngineIdleRpm, CurrentEngineRpm
            return all(math.isfinite(v) and 0.0 <= v < 100_000.0 for v in rpms)
        except Exception:
            return False

    def _reject(self, msg: str) -> PacketRejected:
        self.stats.rejected += 1
        self.stats.last_error = msg
        return PacketRejected(msg)

    # ------------------------------------------------------------------ main entry point
    def decode(self, data: bytes, t_recv_ns: int) -> list[Emitted]:
        self.stats.packets += 1
        layout = P.LAYOUTS.get(len(data))
        if layout is None:
            raise self._reject(
                f"unsupported Forza Data Out size {len(data)} (expected one of {sorted(P.LAYOUTS)}: "
                "232 Sled, 311 FM7 Dash, 324 Horizon, 331 FM2023 Dash)"
            )
        raw = layout.unpack(data)
        if raw["IsRaceOn"] not in (0, 1):
            raise self._reject(f"IsRaceOn={raw['IsRaceOn']} (expected 0 or 1): not a Forza Data Out packet")
        self.stats.count(layout.fmt.value)
        out: list[Emitted] = []
        try:
            if self._step(layout, raw, t_recv_ns, out):
                self.stats.decoded += 1
            else:
                self.stats.ignored += 1
        except Exception as e:  # never let one bad packet kill the stream
            self.stats.errors += 1
            self.stats.last_error = f"{layout.fmt.value}: {e!r}"
            log.exception("Forza decode error (%s)", layout.fmt.value)
        return out

    def _step(self, layout: P.FormatLayout, raw: dict[str, Any], t: int, out: list[Emitted]) -> bool:
        s = self._session
        if raw["IsRaceOn"] == 0:
            if s is None:
                return False  # menus before driving: never create a session from them
            self._on_race_off(s, layout, raw, t, out)
            return True

        if s is not None and layout is s.layout and layout.has_dash:
            if self._out_of_order(s, raw):
                if s.late_streak < LATE_MAX_STREAK:
                    s.late_streak += 1
                    self.stats.count("out_of_order")
                    return False  # dropped whole: no frame, and the previous packet stays the reference
                self.stats.count("late_streak_accepted")
                s.lap_compromised = True  # the stream went back by a sliver: this lap is no length sample
            s.late_streak = 0
        if s is not None:
            reason = self._restart_reason(s, layout, raw)
            if reason is not None:
                self._end_session(s, t, out, reason)
                s = None
        if s is None:
            s = self._begin_session(layout, raw, t, out)
        s.race_off_since_ns = None
        s.last_t_ns = t

        if layout.has_dash:
            self._check_rewind(s, raw, t, out)
            jumped = self._check_jump(s, raw, t)
            self._laps(s, raw, t, out, jumped)
        self._update_snapshot(s, raw)
        if s.last_info_ns is None or t - s.last_info_ns >= SESSION_INFO_INTERVAL_S * 1e9:
            out.append(self._session_info(s, t))

        self._emit_frame(s, self._frame(s, raw, t), t, out)

        if layout.has_dash:
            s.prev_lap_raw = raw["LapNumber"]
            s.prev_race_time_s = _time_s(raw["CurrentRaceTime"])
            s.prev_current_lap_s = _time_s(raw["CurrentLap"])
            s.prev_pos = _position(raw)
            s.prev_dist = _odometer(raw)
            s.prev_speed = _finite(raw["Speed"])
            s.prev_t_ns = t
        return True

    def _emit_frame(self, s: _Session, frame: CarFrame, t: int, out: list[Emitted]) -> None:
        """Out now, or behind a pending lap completion (released by it, at the latest on the hold deadline)."""
        p = s.pending
        if p is None:
            out.append(frame)
            return
        s.held.append(frame)
        if t >= p.deadline_ns or len(s.held) >= LAST_LAP_HOLD_MAX_FRAMES:
            self.stats.count("last_lap_timeout")
            self._resolve_pending(s, None, t, out)

    # ------------------------------------------------------------------ session lifecycle
    def _begin_session(self, layout: P.FormatLayout, raw: dict[str, Any], t: int, out: list[Emitted]) -> _Session:
        car = int(raw["CarOrdinal"])
        synthetic = car == P.SYNTHETIC_CAR_ORDINAL
        uid = str(SYNTHETIC_SESSION_UID) if synthetic else f"forza:{layout.fmt.value}:{t}"
        track_ord = int(raw["TrackOrdinal"]) if "TrackOrdinal" in raw else None
        s = _Session(uid=uid, synthetic=synthetic, layout=layout, car_ordinal=car, track_ordinal=track_ord)
        if track_ord is not None:
            s.track_id, s.track_id_source = f"forza:{track_ord}", "track_ordinal"
        if layout.has_dash:
            s.last_lap_baseline_s = _time_s(raw["LastLap"])
        self._session = s
        self.info = _INFO_BY_GAME[layout.game]
        self._update_snapshot(s, raw)
        out.append(self._session_info(s, t))
        out.append(
            GameEvent(
                kind=EventKind.SESSION_STARTED,
                game=layout.game,
                t_recv_ns=t,
                session_time_s=_time_s(raw["CurrentRaceTime"]) if layout.has_dash else None,
                payload={"source": "derived", "format": layout.fmt.value, "car_ordinal": car},
            )
        )
        log.info("Forza session %s started (%s, car %d)", uid, layout.fmt.value, car)
        return s

    def _end_session(self, s: _Session, t: int, out: list[Emitted], reason: str) -> None:
        if s.pending is not None:
            self._resolve_pending(s, None, t, out)
        out.append(
            GameEvent(
                kind=EventKind.SESSION_ENDED,
                game=s.layout.game,
                t_recv_ns=t,
                session_time_s=s.prev_race_time_s,
                payload={"source": "derived", "reason": reason},
            )
        )
        self.stats.count(f"session_end_{reason}")
        log.info("Forza session %s ended (%s)", s.uid, reason)
        self._session = None

    def _restart_reason(self, s: _Session, layout: P.FormatLayout, raw: dict[str, Any]) -> str | None:
        if layout is not s.layout:
            return "format_changed"
        if int(raw["CarOrdinal"]) != s.car_ordinal:
            return "car_changed"
        if s.track_ordinal is not None and int(raw["TrackOrdinal"]) != s.track_ordinal:
            return "track_changed"
        if layout.has_dash:
            rt, prev = _time_s(raw["CurrentRaceTime"]), s.prev_race_time_s
            if (
                rt is not None
                and prev is not None
                and rt <= prev - REWIND_MIN_S
                and (rt < RESTART_RACE_TIME_S or prev - rt > RESTART_RACE_TIME_DROP_S)
            ):
                return "race_restarted"
            if s.prev_lap_raw is not None and raw["LapNumber"] < s.prev_lap_raw - 1:
                return "race_restarted"
        return None

    def _on_race_off(
        self, s: _Session, layout: P.FormatLayout, raw: dict[str, Any], t: int, out: list[Emitted]
    ) -> None:
        p = s.pending
        if p is not None and layout.has_dash:
            # Forza Motorsport stops the race (IsRaceOn=0) at the flag, possibly before LastLap was seen to
            # update. What a stopped race's payload holds is undocumented, so its LastLap only counts when it is
            # new *and* agrees with the lap's own clock at the line - two independent fields telling one story.
            last_s = _time_s(raw["LastLap"])
            if self._fresh(last_s, p.baseline_s) and self._matches_lap_clock(last_s, p.lap_clock_s):
                self.stats.count("last_lap_race_off")
                self._resolve_pending(s, last_s, t, out)
        s.last_t_ns = t
        if s.race_off_since_ns is None:
            s.race_off_since_ns = t
        elif t - s.race_off_since_ns >= SESSION_END_IDLE_S * 1e9:
            self._end_session(s, t, out, "race_off_timeout")
            return
        frame = CarFrame(game=s.layout.game, t_recv_ns=t, quality=FrameQuality.PAUSED | FrameQuality.NOT_RACING)
        self._emit_frame(s, frame, t, out)  # still held during a hold: a brief race-off must not cost the time

    # ------------------------------------------------------------------ continuity
    @staticmethod
    def _out_of_order(s: _Session, raw: dict[str, Any]) -> bool:
        """A datagram the network delivered after its successor (see "Late datagrams" in the module doc)."""
        rt, prev = _time_s(raw["CurrentRaceTime"]), s.prev_race_time_s
        if rt is not None and prev is not None:
            return prev - REWIND_MIN_S < rt < prev
        # Without both clocks a rewind across the line cannot be confirmed; dropping one packet is harmless, a
        # false crossing is not.
        return s.prev_lap_raw is not None and int(raw["LapNumber"]) < s.prev_lap_raw

    def _check_rewind(self, s: _Session, raw: dict[str, Any], t: int, out: list[Emitted]) -> None:
        rt, prev = _time_s(raw["CurrentRaceTime"]), s.prev_race_time_s
        if rt is None or prev is None or rt > prev - REWIND_MIN_S:
            return
        s.lap_compromised = True  # its driven length now includes (or excludes) the rewound stretch
        last = s.last_rewind_event_ns
        if last is not None and t - last < REWIND_EVENT_MIN_INTERVAL_S * 1e9:
            return
        s.last_rewind_event_ns = t
        self.stats.count("rewind")
        out.append(
            GameEvent(
                kind=EventKind.FLASHBACK,
                game=s.layout.game,
                t_recv_ns=t,
                session_time_s=rt,
                payload={"source": "derived", "rewind_s": round(prev - rt, 3)},
            )
        )

    def _check_jump(self, s: _Session, raw: dict[str, Any], t: int) -> bool:
        """The car moved further than it can have driven since the previous packet: a reset to track, or a rewind
        that left ``DistanceTraveled`` running. Lap distance then no longer matches the track until the next
        crossing re-anchors it.

        "Can have driven" is the larger of the odometer's own step (covers lost packets and an odometer that
        rolls back with a rewind) and speed x elapsed time - by the race clock, or by receive time when that
        clock is not running (Horizon free roam). A rewind contributes no elapsed time: its jump back must be
        matched by the odometer, or the lap's distance is misaligned.
        """
        pos, dist, speed = _position(raw), _odometer(raw), _finite(raw["Speed"])
        prev_pos, prev_dist, prev_speed, prev_t = s.prev_pos, s.prev_dist, s.prev_speed, s.prev_t_ns
        if pos is None or dist is None or speed is None or prev_pos is None or prev_dist is None:
            return False
        if prev_speed is None or prev_t is None:
            return False
        rt, prev_rt = _time_s(raw["CurrentRaceTime"]), s.prev_race_time_s
        if rt is not None and prev_rt is not None and rt != prev_rt:
            dt = max(0.0, rt - prev_rt)
        else:
            dt = max(0.0, (t - prev_t) / 1e9)
        reach = max(abs(dist - prev_dist), max(abs(speed), abs(prev_speed)) * dt)
        if math.dist(pos, prev_pos) <= TELEPORT_FACTOR * reach + TELEPORT_SLACK_M:
            return False
        self.stats.count("teleport")
        s.lap_compromised = True
        s.unanchored = True
        return True

    # ------------------------------------------------------------------ laps
    def _laps(self, s: _Session, raw: dict[str, Any], t: int, out: list[Emitted], jumped: bool) -> None:
        lap_raw = int(raw["LapNumber"])
        last_s = _time_s(raw["LastLap"])
        prev = s.prev_lap_raw
        if prev is None or lap_raw == prev:
            if s.pending is not None:
                if self._fresh(last_s, s.pending.baseline_s):
                    self._resolve_pending(s, last_s, t, out)
            elif self._fresh(last_s, s.last_lap_baseline_s) and prev is not None:
                self._last_lap_changed(s, raw, lap_raw, last_s, t, out)
            return
        if lap_raw == prev + 1:
            self._on_crossing(s, raw, lap_raw, last_s, t, out, jumped)
            return
        # Backwards (a rewind across the line: late datagrams and restarts were dealt with earlier) or forwards
        # by more than one (packets lost across a whole lap): settle any pending lap, then resynchronise on the
        # current LastLap.
        if s.pending is not None:
            self._resolve_pending(s, last_s if self._fresh(last_s, s.pending.baseline_s) else None, t, out)
        if lap_raw > prev + 1:
            self.stats.count("lap_skip")
        s.finished_lap_raw = None
        s.last_lap_baseline_s = last_s

    @staticmethod
    def _fresh(last_s: float | None, baseline_s: float | None) -> bool:
        return last_s is not None and last_s > 0 and (baseline_s is None or abs(last_s - baseline_s) > 1e-6)

    @staticmethod
    def _matches_lap_clock(last_s: float | None, lap_clock_s: float | None) -> bool:
        """``LastLap`` agrees with the lap's own clock at the line (``CurrentLap`` of the packet before it)."""
        if last_s is None or last_s <= 0 or lap_clock_s is None:
            return False
        return -LAST_LAP_MATCH_BELOW_S <= last_s - lap_clock_s <= LAST_LAP_MATCH_S

    def _last_lap_changed(
        self, s: _Session, raw: dict[str, Any], lap_raw: int, last_s: float | None, t: int, out: list[Emitted]
    ) -> None:
        """LastLap changed although LapNumber did not."""
        rt, prev_rt = _time_s(raw["CurrentRaceTime"]), s.prev_race_time_s
        recent = s.last_crossing_ns is not None and t - s.last_crossing_ns < LATE_LAST_LAP_WINDOW_S * 1e9
        rewinding = rt is not None and prev_rt is not None and rt < prev_rt
        s.last_lap_baseline_s = last_s
        if recent or rewinding or s.finished_lap_raw is not None:
            # Late update for the previous crossing (its completion already went out, timed out) or a rewind
            # restoring an older value: absorb it so it is never mistaken for the next lap's time.
            self.stats.count("last_lap_absorbed")
            return
        # A lap completed without LapNumber advancing: the final lap of a race (the game stops counting).
        s.finished_lap_raw = lap_raw
        self.stats.count("final_lap")
        out.append(
            LapCompletion(
                game=s.layout.game,
                t_recv_ns=t,
                lap_number=lap_raw + 1,
                lap_time_ms=_ms(last_s),
                valid=False if s.unanchored else None,
                session_time_s=rt,
            )
        )

    def _on_crossing(
        self,
        s: _Session,
        raw: dict[str, Any],
        lap_raw: int,
        last_s: float | None,
        t: int,
        out: list[Emitted],
        jumped: bool,
    ) -> None:
        """LapNumber advanced by one: the car crossed the line, completing our lap ``lap_raw``.

        ``jumped``: this very packet moved the car further than it can have driven (reset across the line), so
        its position is not the line and the new lap's distance origin is not trusted either.
        """
        if s.pending is not None:  # two crossings inside the hold window: cannot happen on a real circuit
            self._resolve_pending(s, None, t, out)
        valid = False if s.unanchored else None
        dist = _odometer(raw)
        start = s.lap_start_dist.get(lap_raw - 1)
        info_changed = False
        if start is not None and dist is not None:
            measured = dist - start
            if s.lap_compromised:
                self.stats.count("lap_length_untrusted")  # rewind / reset in the lap: not a measurement
            elif MIN_LAP_LENGTH_M <= measured <= MAX_LAP_LENGTH_M:
                s.lap_lengths.append(measured)
                del s.lap_lengths[:-LAP_LENGTH_SAMPLES]
                s.track_length_m = self._derived_length(s.lap_lengths)
                info_changed = True
                if s.track_id is None and s.sf_crossing is not None:
                    self._identify_track(s, measured)
        pos, yaw = _position(raw), _finite(raw["Yaw"])
        if s.sf_crossing is None and not jumped and pos is not None and yaw is not None:
            s.sf_crossing = (pos[0], pos[2], yaw)  # the line's position, whichever lap is later measured from it
        if dist is not None:
            s.lap_start_dist[lap_raw] = dist
            for k in [k for k in s.lap_start_dist if k < lap_raw - LAP_START_MEMORY]:
                del s.lap_start_dist[k]
        s.lap_compromised = s.unanchored = jumped  # a new lap: clean unless it began with a reset
        s.last_crossing_ns = t
        if info_changed:
            out.append(self._session_info(s, t))  # before the completion: the lap must see the new length / id

        if s.finished_lap_raw == lap_raw - 1:
            # The game counted the lap after all, after we already completed it as a final lap.
            s.finished_lap_raw = None
            s.last_lap_baseline_s = last_s
            return
        s.finished_lap_raw = None
        rt = _time_s(raw["CurrentRaceTime"])
        if self._fresh(last_s, s.last_lap_baseline_s) or self._matches_lap_clock(last_s, s.prev_current_lap_s):
            s.last_lap_baseline_s = last_s
            out.append(
                LapCompletion(
                    game=s.layout.game,
                    t_recv_ns=t,
                    lap_number=lap_raw,
                    lap_time_ms=_ms(last_s),
                    valid=valid,
                    session_time_s=rt,
                )
            )
        else:
            self.stats.count("last_lap_held")
            s.pending = _PendingLap(
                lap_number=lap_raw,
                baseline_s=s.last_lap_baseline_s,
                lap_clock_s=s.prev_current_lap_s,
                valid=valid,
                deadline_ns=t + int(LAST_LAP_HOLD_S * 1e9),
                session_time_s=rt,
            )

    def _resolve_pending(self, s: _Session, last_s: float | None, t: int, out: list[Emitted]) -> None:
        p = s.pending
        assert p is not None
        s.pending = None
        if last_s is not None:
            s.last_lap_baseline_s = last_s
        out.append(
            LapCompletion(
                game=s.layout.game,
                t_recv_ns=t,
                lap_number=p.lap_number,
                lap_time_ms=_ms(last_s),
                valid=p.valid,
                session_time_s=p.session_time_s,
            )
        )
        out.extend(s.held)
        s.held = []

    @staticmethod
    def _derived_length(samples: list[float]) -> float:
        """Track length from measured driven laps: the shortest within ``LAP_LENGTH_SPREAD`` of the median (see
        "Track length" in the module doc), floored to 0.1 m so rounding never puts it above that lap."""
        floor = statistics.median(samples) * (1.0 - LAP_LENGTH_SPREAD)
        return math.floor(min(v for v in samples if v >= floor) * 10.0) / 10.0

    def _identify_track(self, s: _Session, length_m: float) -> None:
        assert s.sf_crossing is not None
        x, z, yaw = s.sf_crossing
        fp = TrackFingerprint(s.layout.family, x, z, math.degrees(yaw) % 360.0, length_m)
        s.track_id_source = "fingerprint"
        if s.synthetic:
            # A generated circuit must never claim a real one's id, nor seed the registry later real sessions
            # are matched against. The session manager re-namespaces synthetic ids too; the adapter does not rely
            # on it (and ``TrackFingerprint.parse`` rejects this form, so it cannot come back as a known id).
            s.track_id = f"synthetic:{fp.track_id}"
            return
        for known in self._known:
            if known.matches(fp):
                s.track_id = known.track_id
                break
        else:
            self._known.append(TrackFingerprint.parse(fp.track_id) or fp)  # store the rounded form
            s.track_id = fp.track_id
        log.info("Forza track fingerprint %s", s.track_id)

    # ------------------------------------------------------------------ outputs
    def _update_snapshot(self, s: _Session, raw: dict[str, Any]) -> None:
        snap = s.snapshot
        snap["car_class"] = raw["CarClass"]
        snap["car_performance_index"] = raw["CarPerformanceIndex"]
        snap["drivetrain"] = DRIVETRAINS.get(raw["DrivetrainType"])
        snap["num_cylinders"] = raw["NumCylinders"]
        snap["engine_idle_rpm"] = _finite(raw["EngineIdleRpm"])
        if s.layout.has_dash:
            snap["best_lap_ms"] = _ms(_time_s(raw["BestLap"]))
            fuel = _finite(raw["Fuel"])
            snap["fuel_fraction"] = round(fuel, 4) if fuel is not None else None
        if "CarGroup" in raw:
            snap["car_group"] = raw["CarGroup"]

    def _session_info(self, s: _Session, t: int) -> SessionInfo:
        s.last_info_ns = t
        lay = s.layout
        measured = bool(s.lap_lengths)
        return SessionInfo(
            game=lay.game,
            t_recv_ns=t,
            platform=Platform.UNKNOWN,  # the protocol does not say whether the sender is a PC or an Xbox
            session_uid=s.uid,
            track_id=s.track_id,
            track_length_m=s.track_length_m,
            car_id=f"forza:{lay.family}:car:{s.car_ordinal}",
            extra={
                **s.snapshot,
                "forza_format": lay.fmt.value,
                "car_ordinal": s.car_ordinal,
                "track_ordinal": s.track_ordinal,
                "track_id_source": s.track_id_source,
                "lap_distance_source": LAP_DISTANCE_SOURCE if lay.has_dash else None,
                "track_length_source": "derived:shortest_recent_driven_lap" if measured else None,
                "track_length_nominal_m": round(statistics.median(s.lap_lengths), 1) if measured else None,
                "measured_lap_lengths_m": [round(v, 1) for v in s.lap_lengths],
            },
        )

    def _frame(self, s: _Session, raw: dict[str, Any], t: int) -> CarFrame:
        lay = s.layout
        q = FrameQuality.NOT_RACING if s.finished_lap_raw is not None else FrameQuality.OK
        max_rpm = _finite(raw["EngineMaxRpm"])
        f = CarFrame(
            game=lay.game,
            t_recv_ns=t,
            quality=q,
            rpm=_finite(raw["CurrentEngineRpm"]),
            max_rpm=max_rpm if max_rpm else None,
            g_lat=_g(_finite(raw["AccelerationX"])),
            g_vert=_g(_finite(raw["AccelerationY"])),
            g_lon=_g(_finite(raw["AccelerationZ"])),
            yaw_rad=_finite(raw["Yaw"]),
            pitch_rad=_finite(raw["Pitch"]),
            roll_rad=_finite(raw["Roll"]),
        )
        if not lay.has_dash:
            vel = [_finite(raw[k]) for k in ("VelocityX", "VelocityY", "VelocityZ")]
            if all(v is not None for v in vel):
                f.speed_kph = math.sqrt(sum(v * v for v in vel if v is not None)) * 3.6  # derived: car-local |v|
            return f
        speed = _finite(raw["Speed"])
        f.speed_kph = speed * 3.6 if speed is not None else None
        f.throttle = _unit(raw["Accel"])
        f.brake = _unit(raw["Brake"])
        f.clutch = _unit(raw["Clutch"])
        f.steering = max(-1.0, min(1.0, raw["Steer"] / 127.0))  # s8 can be -128
        f.gear = _gear(raw["Gear"])
        f.pos_x_m = _bounded(raw["PositionX"], MAX_WORLD_M)
        f.pos_y_m = _bounded(raw["PositionY"], MAX_WORLD_M)
        f.pos_z_m = _bounded(raw["PositionZ"], MAX_WORLD_M)
        f.session_time_s = _time_s(raw["CurrentRaceTime"])
        lap_raw = int(raw["LapNumber"])
        f.lap_number = lap_raw + 1
        dist = _odometer(raw)
        f.total_distance_m = dist
        start = s.lap_start_dist.get(lap_raw)
        if start is not None and dist is not None and not s.unanchored:
            f.lap_distance_m = dist - start
        cur = _time_s(raw["CurrentLap"])
        f.current_lap_time_ms = round(cur * 1000.0) if cur is not None else None
        f.last_lap_time_ms = _ms(_time_s(raw["LastLap"]))
        f.race_position = raw["RacePosition"] or None
        temps = [_f_to_c(v) for v in _wheels(raw, "TireTemp")]
        if all(v is not None for v in temps):
            f.tyre_surface_temp_c = Wheels.from_fl_fr_rl_rr([v for v in temps if v is not None])
        if "TireWearFrontLeft" in raw:
            wear = _wheels(raw, "TireWear")
            if all(v is not None for v in wear):
                f.tyre_wear_pct = Wheels.from_fl_fr_rl_rr([v * 100.0 for v in wear if v is not None])
        return f
