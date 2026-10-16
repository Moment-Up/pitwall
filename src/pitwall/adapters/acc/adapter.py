"""Assetto Corsa Competizione (PC) shared-memory adapter: Physics / Graphics / Static snapshots -> unified model.

Started from the ACC adapter Ed (Pitwall tester) wrote and sent on 2026-10-14 (``acc-adapter-for-james.patch`` plus
the ACC part of ``body-slip-and-cadence-for-james.patch``); reworked against Kunos' official "ACC Shared Memory
v1.8.12" (``packets.py``, ``docs/research/acc-shared-memory-spec.md``). Pure decoder: the transport is
``pitwall.ingest.acc_shm_reader``, which copies whole pages and tags them ``PHYS`` / ``GRPH`` / ``STAT``.

Evidence
    Ed's live cross-checks with his own build of this adapter are a TESTER'S REPORT, not Pitwall-recorded evidence:
    Spa, GT3, 2026-10-09 (gas, brake, steering, speed: eight braking zones with brake 1 / gas 0, speed coherent up to
    254 km/h) and Brands Hatch, McLaren 720S GT3, 2026-10-13/14 (track and car names decode; the raw gear reads one
    high, so 0 = R; the raw steering sign is the opposite of Pitwall's - a right-hander came out as a left). No
    recorded ACC capture exists in ``tests/fixtures/recorded`` yet, so everything else is as documented by Kunos and
    tested with generated pages only.

What the pages give, and what pitwall derives (every field and its evidence is in ``ACC_INFO.fields``)
-----------------------------------------------------------------------------------------------------------
Sessions
    ACC has no session id. A session opens on the first Graphics page whose ``status`` is LIVE or PAUSE and gets the
    uid ``acc:<t_recv_ns>`` (deterministic on replay; ``SYNTHETIC_SESSION_UID`` when Static's ``carModel`` is
    ``SYNTHETIC_CAR_MODEL``). It ends when ``status`` goes OFF, when ``session`` (type) or ``sessionIndex`` changes
    (the next session of an event opens at once), when ``completedLaps`` goes backwards (a restart), or when Static
    names another track or car. REPLAY never opens a session; inside one it keeps it open, its frames are flagged
    ``REPLAY_OR_SPECTATING`` (no lap distance) and its laps are ignored (a replay shows other moments: its
    ``completedLaps`` may go back without a restart). PAUSE frames are flagged ``PAUSED``. Physics pages outside a
    session are ignored, so a game sitting in its menus produces no frames and no session.

Clock (``session_time_s``)
    The pages carry no session clock. The adapter uses the host receive clock relative to the session start and
    holds it still while Graphics says PAUSE or REPLAY, so a pause never looks like lost packets downstream.

Laps
    Pitwall's lap number is ``completedLaps + 1``. An increment completes the previous lap: its validity is
    ``isValidLap`` of the last Graphics page *before* the increment (the new page already describes the new lap) and
    its time is ``iLastTime`` if that changed in the incrementing page; otherwise the completion, and every item after
    it, is held up to ``LAST_LAP_HOLD_S`` for ``iLastTime`` to change, then released untimed. ``INT32_MAX`` (ACC's
    "no value") and negative times are ``None``. A jump of more than one lap completes nothing.

Lap distance
    ``normalizedCarPosition`` (0 at the start, 1 at the finish, per Kunos) x the track length. The length is Static's
    ``trackSplineLength`` only when it is plausible - within ``TRACK_LENGTH_TOLERANCE`` of ``tracks.py``'s length for
    the track, or inside ``MIN/MAX_TRACK_LENGTH_M`` for a track the table does not list (Kunos marks the field "not
    used in ACC", so expect the table); else the table; else ``None``. Within a lap the spline position is unwrapped
    for continuity, so a spline that wraps a frame before (or after) ``completedLaps`` increments gives a distance a
    little above the length (or below 0) instead of a jump. A lap first seen away from a crossing with the spline at
    ``GRID_FRACTION`` or more is on a grid behind the line (negative distance). A teleport (a step of more than a
    quarter lap), or a spline that runs on past ``LAP_FRACTION_RANGE`` with no lap counted, stops that lap's distance
    (``None``) until the next lap: how the game counts such a lap is unknown.

Units and conventions (Kunos' names)
    ``gas`` / ``brake`` / ``clutch`` 0..1; ``steerAngle`` -1..1 is negated (Pitwall: -1 left .. +1 right; sign from
    Ed's tester report); ``gear`` 0 = R, 1 = N, 2 = 1st -> -1, 0, 1.. (encoding not printed in the ACC PDF; AC's
    convention, confirmed by Ed); wheel arrays are FL, FR, RL, RR (Kunos' order table and ``ACC_WHEELS_TYPE``).
    ``TyreCoreTemp`` goes to ``tyre_core_temp_c`` (the inner/middle/outer tread temperatures are "not shown in ACC",
    so the surface and inner fields stay ``None``); ``wheelPressure`` is taken as psi only when every value is in
    the psi range (bar and kPa values cannot fall there). Temperatures are taken as degrees C (Kunos prints no unit;
    AC/ACC convention). Not mapped, with the reason in ``ACC_INFO``: ``fuel`` (Kunos: kg; its own ``fuelXLap`` and the
    game's HUD: litres), ``fuelEstimatedLaps`` (laps the fuel on board lasts: another quantity than Pitwall's
    ``fuel_remaining_laps_game``, F1's margin at the finish), ``brakeBias`` (the dash value needs Kunos' per-car
    offset), ``abs`` / ``tc`` (intervention: Pitwall's ``abs_active`` means the ABS assist is on), ``velocity``
    (world axes, no unit), ``heading`` / ``pitch`` / ``roll`` (no unit), the player's names (personal data: never
    decoded).

Checked-at-runtime channels (UNVERIFIED until a recording confirms them)
    Kunos says ``accG`` is "in global coordinates" and gives no unit or axis order for it, ``localAngularVel``,
    ``localVelocity``, ``slipAngle`` or ``slipRatio``. Rather than guess, the adapter collects evidence while the car
    is driven and maps a channel only once the evidence is unambiguous (``EVIDENCE_MIN_VOTES``, one answer winning
    ``EVIDENCE_RATIO`` to 1), like the AC adapter's ``g_lon`` sign. The evidence is knowledge about the game, so
    ``reset()`` keeps it; ``SessionInfo.extra['acc_evidence']`` shows the counts.

    * ``g_lon``: ``accG[2]`` against the measured change of ``speedKmh`` (sign and size, in g). Agreement also shows
      that ``accG`` is in the car's axes: a world-axis component would follow the car's heading, not its speed.
    * ``g_lat`` / ``g_vert`` / yaw unit: in a corner ``|accG[0]|`` g must equal speed x ``|localAngularVel[1]|``
      (centripetal acceleration; rad/s). One check confirms ``accG[0]`` lateral in g and ``localAngularVel[1]`` the
      yaw rate in rad/s; with ``g_lon`` confirmed, ``accG[1]`` is the remaining (vertical) axis.
    * ``yaw_rate_rps`` sign: ``localAngularVel[1]`` against the (Pitwall-signed) steering when cornering: the same
      sign in normal cornering, so the sign that wins becomes Pitwall's (+ = turning right).
    * ``body_slip_rad``: ``localVelocity[2]`` must be the forward speed (it matches ``speedKmh``) and the yaw sign
      must be known: a raw yaw that is + for right turns means a left-handed frame (x to the right), - means x to the
      left. Body slip = atan2(-lateral-to-the-right, forward), so it has the yaw rate's sign when the tail steps out
      (F1's convention, which ``technique.balance`` relies on).
    * ``wheel_slip_angle_rad``: with the lateral g confirmed, front slip angles in a loaded corner must look like
      radians (0.005..0.35) or like degrees (0.5..20) - a factor of 57 apart. Degrees are converted.
    * ``wheel_slip_ratio``: with ``g_lon`` confirmed, front tyres under braking and rear tyres under power must give
      opposite signs; the sign that matches Pitwall's (< 0 braking, > 0 wheelspin) in both is used.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

from pitwall.adapters.acc import packets as P
from pitwall.adapters.acc import tracks
from pitwall.adapters.base import AdapterInfo, DecodeStats, FieldSupport, PacketRejected, SupportLevel
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
    SessionType,
    Weather,
    Wheels,
)

log = logging.getLogger(__name__)

STANDARD_GRAVITY = 9.80665
STALE_GRAPHICS_S = 0.25  # a Physics frame merged with Graphics older than this is flagged STALE_LAP_DATA
LAST_LAP_HOLD_S = 0.5  # max wait for iLastTime to change after completedLaps incremented
LAST_LAP_HOLD_MAX_ITEMS = 400  # hard bound on items held behind a completion
PEDAL_TOLERANCE = 0.02  # pedal / steering values this far outside their range are clamped; further out -> None
NORM_TOLERANCE = 0.01  # normalizedCarPosition outside [-tol, 1 + tol] -> no distance for that frame
DISTANCE_JUMP_FRACTION = 0.25  # a spline step larger than this within a lap: teleport, the lap's trace stops
GRID_FRACTION = 0.9  # a lap first seen (not at a crossing) at a spline position this high: on the grid, before the line
LAP_FRACTION_RANGE = (-0.25, 1.05)  # an unwrapped position outside this: the lap's trace stops (a wrap with no lap)
MAX_GEAR_RAW = 11
TRACK_LENGTH_TOLERANCE = 0.03  # Static.trackSplineLength is used only within 3 % of tracks.py's length
MIN_TRACK_LENGTH_M = 1000.0  # ... or, for a track the table does not list, inside this range
MAX_TRACK_LENGTH_M = 30_000.0  # Nordschleife + GP is ~25.4 km
TYRE_PSI_RANGE = (5.0, 60.0)  # wheelPressure is psi only if every wheel is in here (bar < 5, kPa > 100)
TYRE_CORE_RANGE_C = (-40.0, 250.0)
BRAKE_TEMP_RANGE_C = (-40.0, 1500.0)
AMBIENT_RANGE_C = (-40.0, 80.0)

# Runtime evidence (module docstring)
EVIDENCE_MIN_VOTES = 60
EVIDENCE_RATIO = 9
G_WINDOW_S = 0.1  # g_lon: mean accG[2] vs d(speed)/dt over windows this long
G_WINDOW_MAX_S = 0.3  # a longer window (frames missing) is discarded
G_MIN_MEASURED_G = 0.3
G_RATIO_RANGE = (0.5, 2.0)  # reported / measured (and centripetal) magnitudes this close count as the same unit
CENTRIPETAL_MIN_KPH = 60.0
CENTRIPETAL_MIN_G = 0.5
CENTRIPETAL_MIN_RPS = 0.05
CENTRIPETAL_RANGE = (0.6, 1.6)
YAW_MIN_KPH = 40.0
YAW_MIN_STEER = 0.03
YAW_MIN_RPS = 0.05
FORWARD_MIN_KPH = 30.0
FORWARD_TOLERANCE = 0.1  # |localVelocity[2]| within 10 % (+ 0.5 m/s) of speedKmh
BODY_SLIP_MIN_MPS = 3.0  # below this the direction of travel is noise: body slip None
SLIP_ANGLE_MIN_KPH = 80.0
SLIP_ANGLE_MIN_G = 0.8
SLIP_ANGLE_RAD_RANGE = (0.005, 0.35)
SLIP_ANGLE_DEG_RANGE = (0.5, 20.0)
SLIP_RATIO_MIN_KPH = 30.0
SLIP_RATIO_MIN = 0.003  # smaller slip says nothing about the sign
SLIP_RATIO_BAD = 2.0  # larger is no slip ratio at speed (a percentage, say): counts against the reading

LENGTH_SPLINE = "static_track_spline_length"
LENGTH_TABLE = "tracks_table"
LENGTH_UNKNOWN = "unknown"

_LIVE_LIKE = (P.AccStatus.LIVE, P.AccStatus.PAUSE)
_FROZEN = (P.AccStatus.PAUSE, P.AccStatus.REPLAY)
_SESSION_TYPES = {
    P.AccSessionType.PRACTICE: SessionType.PRACTICE,
    P.AccSessionType.QUALIFY: SessionType.QUALIFYING,
    P.AccSessionType.RACE: SessionType.RACE,
    P.AccSessionType.HOTLAP: SessionType.TIME_TRIAL,
    P.AccSessionType.TIMEATTACK: SessionType.TIME_TRIAL,
}
# ACC_SESSION_TYPE in words for SessionInfo.session_type_raw (the session's own name on the dashboard, the report and
# the leaderboard, as F1's names are): Kunos' enum names, spelled out. Any other value is "unknown_<n>" (no name).
SESSION_NAMES: dict[P.AccSessionType, str] = {
    P.AccSessionType.PRACTICE: "Practice",
    P.AccSessionType.QUALIFY: "Qualifying",
    P.AccSessionType.RACE: "Race",
    P.AccSessionType.HOTLAP: "Hotlap",
    P.AccSessionType.TIMEATTACK: "Time attack",
    P.AccSessionType.DRIFT: "Drift",
    P.AccSessionType.DRAG: "Drag",
    P.AccSessionType.HOTSTINT: "Hotstint",
    P.AccSessionType.HOTSTINTSUPERPOLE: "Hotstint superpole",
}
_RAIN = {  # ACC_RAIN_INTENSITY -> Weather.condition (no rain says nothing about cloud: None)
    P.AccRainIntensity.DRIZZLE: "light_rain",
    P.AccRainIntensity.LIGHT_RAIN: "light_rain",
    P.AccRainIntensity.MEDIUM_RAIN: "heavy_rain",
    P.AccRainIntensity.HEAVY_RAIN: "heavy_rain",
    P.AccRainIntensity.THUNDERSTORM: "storm",
}

# Raw fields the adapter reads, per page (tests/unit/test_acc_protocol.py checks each one is a field Kunos marks as
# used by ACC - except trackSplineLength, read only under the plausibility check above - and that the research doc's
# "Pitwall" column lists exactly these).
FIELDS_READ: dict[str, frozenset[str]] = {
    "SPageFilePhysics": frozenset(
        {
            "packetId",
            "gas",
            "brake",
            "gear",
            "rpm",
            "steerAngle",
            "speedKmh",
            "accG",
            "wheelPressure",
            "TyreCoreTemp",
            "airTemp",
            "roadTemp",
            "localAngularVel",
            "brakeTemp",
            "clutch",
            "localVelocity",
            "slipRatio",
            "slipAngle",
        }
    ),
    "SPageFileGraphic": frozenset(
        {
            "status",
            "session",
            "completedLaps",
            "position",
            "iCurrentTime",
            "iLastTime",
            "iBestTime",
            "isInPit",
            "currentSectorIndex",
            "normalizedCarPosition",
            "activeCars",
            "carCoordinates",
            "carID",
            "playerCarID",
            "isInPitLane",
            "TC",
            "rainTyres",
            "sessionIndex",
            "isValidLap",
            "rainIntensity",
        }
    ),
    "SPageFileStatic": frozenset(
        {"smVersion", "acVersion", "carModel", "track", "sectorCount", "maxRpm", "trackSplineLength", "isOnline"}
    ),
}
READ_DESPITE_UNUSED: frozenset[tuple[str, str]] = frozenset({("SPageFileStatic", "trackSplineLength")})

_S = SupportLevel.SPEC_IMPLEMENTED
_C = SupportLevel.COMMUNITY_DOCUMENTED
_PART = SupportLevel.PARTIAL
_V = SupportLevel.UNVERIFIED
_U = SupportLevel.UNSUPPORTED
_DOC = "Kunos ACC Shared Memory v1.8.12"
_TESTER_SPA = "tester's report (Ed, his own build, live ACC at Spa 2026-10-09): checked in 8 braking zones"
_TESTER_BRANDS = "tester's report (Ed, his own build, live ACC at Brands Hatch 2026-10-13/14)"
_RUNTIME = "mapped only once runtime evidence is unambiguous (module docstring); no recording yet"

ACC_INFO = AdapterInfo(
    game=Game.ACC,
    name="Assetto Corsa Competizione (shared memory: Physics 800 B, Graphics 1588 B, Static 820 B)",
    transport="Windows shared memory read on the gaming PC (Local\\acpmf_physics / _graphics / _static)",
    default_port=None,
    ground_plane=("pos_x_m", "pos_z_m"),  # carCoordinates: y up (AC convention; Kunos does not say)
    platforms={
        Platform.PC: _S,  # built from Kunos' official document; tested with generated pages only
        Platform.PS5: _U,  # console ACC has no shared memory or telemetry output (research doc)
        Platform.PS4: _U,
        Platform.XBOX: _U,
    },
    fields={
        "throttle": FieldSupport(_S, f"Physics.gas 0..1 ({_DOC}); {_TESTER_SPA}"),
        "brake": FieldSupport(_S, f"Physics.brake 0..1 ({_DOC}); {_TESTER_SPA}"),
        "clutch": FieldSupport(_S, f"Physics.clutch, 'clutch pedal input' 0..1 ({_DOC}); not live-checked"),
        "steering": FieldSupport(
            _S,
            f"-Physics.steerAngle: Kunos documents a normalised input -1..1 but no sign; negated so + = right "
            f"({_TESTER_BRANDS}: unnegated, a right-hander was labelled left)",
        ),
        "speed_kph": FieldSupport(_S, f"Physics.speedKmh ({_DOC}); {_TESTER_SPA}"),
        "gear": FieldSupport(
            _C,
            f"Physics.gear - 1: 0 = R, 1 = N, 2 = 1st (encoding not printed in the ACC document; AC convention; "
            f"{_TESTER_BRANDS}: the raw value read one gear high)",
        ),
        "rpm": FieldSupport(_S, f"Physics.rpm ({_DOC})"),
        "max_rpm": FieldSupport(
            _S,
            f"Static.maxRpm ({_DOC}); checked against Kunos' Appendix 7 for listed cars "
            "(SessionInfo.extra['static_layout_check'])",
        ),
        "frame_id": FieldSupport(_S, "Physics.packetId (a new value per graphics step)"),
        "session_time_s": FieldSupport(
            _PART, "derived: host receive clock since the session opened, held while Graphics says PAUSE / REPLAY"
        ),
        "g_lon": FieldSupport(
            _V,
            "Physics.accG[2] x learned sign; Kunos: 'acceleration vector in global coordinates', no unit. "
            f"Checked against d(speedKmh)/dt in g; {_RUNTIME}",
        ),
        "g_lat": FieldSupport(
            _V,
            "Physics.accG[0] (sign per game) once speed x yaw rate matches it in g (centripetal check) and g_lon is "
            f"confirmed; {_RUNTIME}",
        ),
        "g_vert": FieldSupport(
            _V, f"Physics.accG[1], the remaining axis once g_lat and g_lon are confirmed; {_RUNTIME}"
        ),
        "yaw_rate_rps": FieldSupport(
            _V,
            "Physics.localAngularVel[1] x learned sign (+ = turning right, like steering); unit (rad/s) and axis by "
            f"the centripetal check; Kunos gives neither; {_RUNTIME}",
        ),
        "body_slip_rad": FieldSupport(
            _V,
            "derived: atan2(lateral, forward) of Physics.localVelocity (local axes per Kunos), lateral direction from "
            "the yaw sign, forward axis checked against speedKmh; same sign as yaw when the tail steps out; "
            + _RUNTIME,
        ),
        "wheel_slip_angle_rad": FieldSupport(
            _V,
            "Physics.slipAngle[4] FL..RR; Kunos gives no unit: radians or degrees decided from loaded-corner "
            f"magnitudes (degrees converted); {_RUNTIME}",
        ),
        "wheel_slip_ratio": FieldSupport(
            _V,
            "Physics.slipRatio[4] FL..RR x learned sign; Kunos: 'in radians', no sign convention: braking (front) and "
            f"traction (rear) must both agree; {_RUNTIME}",
        ),
        "tyre_core_temp_c": FieldSupport(
            _C, f"Physics.TyreCoreTemp[4] FL..RR ({_DOC}: core temperature, no unit printed; degrees C by convention)"
        ),
        "tyre_surface_temp_c": FieldSupport(_U, "Physics.tyreTempI/M/O: 'not shown in ACC' (Kunos)"),
        "tyre_inner_temp_c": FieldSupport(_U, "not in ACC's pages (the core temperature is tyre_core_temp_c)"),
        "tyre_pressure_psi": FieldSupport(
            _S, f"Physics.wheelPressure[4] FL..RR ({_DOC}, no unit printed): psi only when all four are 5-60"
        ),
        "tyre_wear_pct": FieldSupport(_U, "Physics.tyreWear: 'not used by ACC' (Kunos)"),
        "brake_temp_c": FieldSupport(_C, f"Physics.brakeTemp[4] FL..RR ({_DOC}, no unit printed; degrees C)"),
        "tyre_compound": FieldSupport(_S, "Graphics.rainTyres -> 'wet' / 'dry'"),
        "engine_temp_c": FieldSupport(_V, "Physics.waterTemp is coolant, not engine temperature; no unit: not mapped"),
        "fuel_kg": FieldSupport(
            _V,
            "Physics.fuel: Kunos says kg, but its own fuelXLap and the game's HUD use litres: not mapped until a "
            "recording settles the unit",
        ),
        "fuel_litres": FieldSupport(_V, "see fuel_kg"),
        "fuel_remaining_laps_game": FieldSupport(
            _V,
            "not mapped: Graphics.fuelEstimatedLaps is how many laps the fuel on board lasts, while Pitwall's field is "
            "F1's MFD figure, the fuel margin at the finish in laps (the race strategy reads it so)",
        ),
        "brake_bias_front_pct": FieldSupport(
            _V, "Physics.brakeBias needs Kunos' per-car dash offset (Appendix 4) to mean the shown %: not mapped"
        ),
        "traction_control": FieldSupport(_S, "Graphics.TC: the TC level setting (ACC's scale, not F1's 0-2)"),
        "abs_active": FieldSupport(
            _V,
            "not mapped: Physics.abs is ABS intervention and Graphics.ABS a level whose 'off' value is not "
            "documented; Pitwall's abs_active means the ABS assist is on",
        ),
        "lap_number": FieldSupport(_S, f"Graphics.completedLaps + 1 ({_DOC})"),
        "current_lap_time_ms": FieldSupport(_S, "Graphics.iCurrentTime (ms; INT32_MAX -> None)"),
        "last_lap_time_ms": FieldSupport(_S, "Graphics.iLastTime (ms; INT32_MAX -> None)"),
        "lap_completion": FieldSupport(
            _S,
            "derived: completedLaps increment; time = iLastTime when it changed in that page (else held up to 0.5 s); "
            "valid = isValidLap of the page before the increment",
        ),
        "lap_invalid": FieldSupport(_S, "not Graphics.isValidLap"),
        "sector": FieldSupport(
            _C, "Graphics.currentSectorIndex, 0-based (AC convention; Kunos gives no base): None unless < sectorCount"
        ),
        "pit_status": FieldSupport(_S, "Graphics.isInPit -> 2, isInPitLane -> 1, else 0"),
        "race_position": FieldSupport(_S, "Graphics.position"),
        "lap_distance_m": FieldSupport(
            _PART,
            "derived: Graphics.normalizedCarPosition (0 start .. 1 finish) x track length, unwrapped within a lap; "
            "None for a track tracks.py does not list (Static.trackSplineLength is 'not used in ACC')",
        ),
        "track_length_m": FieldSupport(
            _PART,
            "tracks.py (Ed's table; a tester's report: Spa, Monza, Brands Hatch checked against public sources, others "
            "approximate), or Static.trackSplineLength when within 3 % of it",
        ),
        "total_distance_m": FieldSupport(_V, "Graphics.distanceTraveled is per stint and has no unit: not mapped"),
        "pos_x_m": FieldSupport(
            _C, "Graphics.carCoordinates[k][0] where carID[k] == playerCarID (metres by AC convention)"
        ),
        "pos_y_m": FieldSupport(_C, "carCoordinates[k][1] (up axis, AC convention)"),
        "pos_z_m": FieldSupport(_C, "carCoordinates[k][2]"),
        "vel_x_mps": FieldSupport(
            _V, "Physics.velocity: world axes, no unit (tester's report: Ed saw it behave like local axes): not mapped"
        ),
        "yaw_rad": FieldSupport(_V, "Physics.heading: no unit or zero direction documented: not mapped"),
        "track_id": FieldSupport(_S, f"'acc:<Static.track>' ({_TESTER_BRANDS}: the name decodes)"),
        "track_name": FieldSupport(
            _S,
            f"Static.track ({_TESTER_BRANDS}), shown as the circuit's name for the tracks tracks.py lists, else as "
            "the game sends it",
        ),
        "car_id": FieldSupport(_S, f"'acc:car:<Static.carModel>' (Kunos id, Appendix 2; {_TESTER_BRANDS})"),
        "car_name": FieldSupport(_S, "Appendix 2 name for Static.carModel; the raw id for cars after v1.8.12"),
        "session_type": FieldSupport(_S, "Graphics.session (ACC_SESSION_TYPE; hotlap / time attack -> time trial)"),
        "session_uid": FieldSupport(_PART, "derived: no session id (status / session / sessionIndex / laps / Static)"),
        "weather": FieldSupport(
            _S,
            "Physics.airTemp / roadTemp (degrees C by convention); Graphics.rainIntensity: drizzle / light -> "
            "light_rain, medium / heavy -> heavy_rain, thunderstorm -> storm, no rain -> None (cloud not sent)",
        ),
        "platform": FieldSupport(_S, "PC only: shared memory exists only on the gaming PC"),
        "setup": FieldSupport(_U, "not in shared memory (setups are JSON files on the PC)"),
        "drs_open": FieldSupport(_U, "Physics.drs: 'not used by ACC' (GT cars have no DRS)"),
        "ers_store_j": FieldSupport(_U, "ERS fields: 'not used by ACC'"),
        "damage": FieldSupport(_U, "Physics.carDamage[5] is per zone; Pitwall's damage model is F1's: not mapped"),
        "track_zones": FieldSupport(_U, "no marshal-zone or DRS-zone data"),
        "field_samples": FieldSupport(_U, "only the other cars' world positions (carCoordinates), no laps or inputs"),
        "field_motion": FieldSupport(_U, "no other-car motion data"),
        "participants": FieldSupport(_U, "no driver list"),
        "buttons": FieldSupport(_U, "no wheel-button data"),
        "fia_flags": FieldSupport(
            _V, "Graphics.flag is documented, but Kunos' sample header calls flag and penalty 'not working': not mapped"
        ),
        "penalties": FieldSupport(_V, "Graphics.penalty: see fia_flags; not mapped"),
    },
    notes=(
        "Built from Kunos' official ACC Shared Memory v1.8.12 (docs/research/acc-shared-memory-spec.md); synthetic "
        "tests only. Started from the adapter Ed (Pitwall tester) wrote: his live checks at Spa and Brands Hatch are a "
        "tester's report, not Pitwall-recorded evidence.",
        "Windows only: the pages exist only on the PC running ACC, so Pitwall must run on that PC. Console ACC has no "
        "telemetry.",
        "Lap distance needs a track length: Kunos marks trackSplineLength 'not used in ACC', so it comes from a table "
        "(three tracks checked); unlisted tracks get lap times but no distance.",
        "g-forces, yaw rate, body slip and wheel slip have no documented unit or axes: each is mapped only after the "
        "car has been driven enough for runtime checks to settle it (SessionInfo.extra['acc_evidence']).",
        "Not mapped: fuel (unit conflict; the game's laps-of-fuel figure is not F1's margin at the finish), brake bias "
        "(per-car offset), ABS on/off, flags and penalties.",
    ),
)


# ---------------------------------------------------------------------------------------------- parsed pages
@dataclass(frozen=True, slots=True)
class _Static:
    sm_version: str | None
    ac_version: str | None
    car_model: str | None
    track: str | None
    sector_count: int | None
    max_rpm: int | None
    spline_length_m: float | None  # trackSplineLength when finite and > 0 (Kunos: not used in ACC)
    is_online: bool | None

    @classmethod
    def parse(cls, d: dict[str, Any]) -> _Static:
        spline = _finite(d["trackSplineLength"])
        return cls(
            sm_version=P.decode_wstring(d["smVersion"]),
            ac_version=P.decode_wstring(d["acVersion"]),
            car_model=P.decode_wstring(d["carModel"]),
            track=P.decode_wstring(d["track"]),
            sector_count=int(d["sectorCount"]) if int(d["sectorCount"]) > 0 else None,
            max_rpm=int(d["maxRpm"]) if int(d["maxRpm"]) > 0 else None,
            spline_length_m=spline if spline is not None and spline > 0 else None,
            is_online=_flag(int(d["isOnline"])),
        )

    @property
    def key(self) -> tuple[str | None, str | None]:
        return (self.track, self.car_model)

    @property
    def empty(self) -> bool:
        return self.track is None and self.car_model is None

    @property
    def synthetic(self) -> bool:
        return self.car_model == P.SYNTHETIC_CAR_MODEL

    @property
    def track_id(self) -> str | None:
        return f"acc:{slug(self.track)}" if self.track else None

    @property
    def car_id(self) -> str | None:
        return f"acc:car:{slug(self.car_model)}" if self.car_model else None

    @property
    def car_name(self) -> str | None:
        if not self.car_model:
            return None
        return P.CAR_MODELS.get(self.car_model.lower(), self.car_model)

    @property
    def layout_check(self) -> str | None:
        """maxRpm against Kunos' Appendix 7 for a listed car: proof that Static is laid out as documented."""
        expected = P.CAR_MAX_RPM.get((self.car_model or "").lower())
        if expected is None or self.max_rpm is None:
            return None
        return "max_rpm_matches_appendix_7" if self.max_rpm == expected else "max_rpm_differs_from_appendix_7"


@dataclass(frozen=True, slots=True)
class _Graphics:
    t_ns: int
    status: int
    session: int
    session_index: int
    completed_laps: int
    position: int | None
    current_ms: int | None
    last_ms: int | None
    best_ms: int | None
    in_pit: bool | None
    in_pit_lane: bool | None
    sector: int  # raw: checked against Static.sectorCount when a frame is built
    npos: float | None
    pos: tuple[float, float, float] | None
    tc: int | None
    valid: bool | None
    rain_tyres: bool | None
    rain: int

    @classmethod
    def parse(cls, d: dict[str, Any], t: int) -> _Graphics:
        npos = _finite(d["normalizedCarPosition"])
        if npos is not None and not -NORM_TOLERANCE <= npos <= 1.0 + NORM_TOLERANCE:
            npos = None
        return cls(
            t_ns=t,
            status=int(d["status"]),
            session=int(d["session"]),
            session_index=int(d["sessionIndex"]),
            completed_laps=int(d["completedLaps"]),
            position=int(d["position"]) if int(d["position"]) >= 1 else None,
            current_ms=_ms(int(d["iCurrentTime"])),
            last_ms=_ms(int(d["iLastTime"])),
            best_ms=_ms(int(d["iBestTime"])),
            in_pit=_flag(int(d["isInPit"])),
            in_pit_lane=_flag(int(d["isInPitLane"])),
            sector=int(d["currentSectorIndex"]),
            npos=None if npos is None else min(1.0, max(0.0, npos)),
            pos=_player_position(d),
            tc=int(d["TC"]) if int(d["TC"]) >= 0 else None,
            valid=_flag(int(d["isValidLap"])),
            rain_tyres=_flag(int(d["rainTyres"])),
            rain=int(d["rainIntensity"]),
        )


def _player_position(d: dict[str, Any]) -> tuple[float, float, float] | None:
    """The player's row of carCoordinates: the k (below activeCars) whose carID is playerCarID; None if absent."""
    n = min(max(int(d["activeCars"]), 0), 60)
    player = int(d["playerCarID"])
    ids = d["carID"]
    for k in range(n):
        if ids[k] == player:
            xyz = d["carCoordinates"][3 * k : 3 * k + 3]
            x, y, z = (_finite(v) for v in xyz)
            return None if x is None or y is None or z is None else (x, y, z)
    return None


# ---------------------------------------------------------------------------------------------- runtime evidence
@dataclass(slots=True)
class Votes:
    """Evidence for one channel: +1 / -1 answers, and observations that fit neither (wrong axis or unit)."""

    plus: int = 0
    minus: int = 0
    bad: int = 0

    def add(self, vote: int | None) -> None:
        if vote is None:
            return
        if vote > 0:
            self.plus += 1
        elif vote < 0:
            self.minus += 1
        else:
            self.bad += 1

    def verdict(self) -> int | None:
        """+1 or -1 once that answer has ``EVIDENCE_MIN_VOTES`` and beats everything else ``EVIDENCE_RATIO`` to 1."""
        p, m, b = self.plus, self.minus, self.bad
        if p >= EVIDENCE_MIN_VOTES and p >= EVIDENCE_RATIO * (m + b):
            return 1
        if m >= EVIDENCE_MIN_VOTES and m >= EVIDENCE_RATIO * (p + b):
            return -1
        return None

    def as_dict(self) -> dict[str, int | None]:
        return {"plus": self.plus, "minus": self.minus, "bad": self.bad, "verdict": self.verdict()}


EVIDENCE_CHECKS = (
    "g_lon",
    "centripetal",
    "yaw",
    "forward",
    "slip_angle_unit",
    "slip_ratio_braking",
    "slip_ratio_traction",
)


# ---------------------------------------------------------------------------------------------- session state
@dataclass(slots=True)
class _Hold:
    """A lap completion waiting for iLastTime to change, and the items emitted behind it."""

    completion: LapCompletion
    stale_last_ms: int | None
    deadline_ns: int
    items: list[Emitted] = field(default_factory=list)


@dataclass(slots=True)
class _Session:
    uid: str
    t0_ns: int
    session_raw: int
    session_index: int
    static_key: tuple[str | None, str | None] | None
    synthetic: bool
    length_m: float | None = None
    length_source: str = LENGTH_UNKNOWN
    frozen_ns: int = 0
    frozen_since: int | None = None
    prev_g: _Graphics | None = None  # the last Graphics page of this session
    anchored_lap: int | None = None  # the lap that began at a completedLaps increment seen in this session
    dist_lap: int | None = None  # lap of the unwrapped spline position below
    dist_f: float | None = None
    dist_lost: bool = False  # the lap's trace stopped (teleport / wrap without a lap): None until the next lap
    hold: _Hold | None = None
    info_key: tuple[Any, ...] | None = None
    g_window: list[float] | None = None  # [t0 clock s, v0 m/s, sum accG[2], n]
    completed: set[int] = field(default_factory=set)

    def clock_s(self, t: int) -> float:
        frozen = self.frozen_ns + (t - self.frozen_since if self.frozen_since is not None else 0)
        return max(0.0, (t - self.t0_ns - frozen) / 1e9)


# ---------------------------------------------------------------------------------------------- helpers
def session_type_of(raw: int) -> tuple[SessionType, str]:
    """Pitwall's session type and the session's name in words (``SESSION_NAMES``) for a Graphics ``session`` value;
    ``unknown_<n>`` for a value Kunos does not list (``carclass.session_label`` shows no name for it)."""
    try:
        kind = P.AccSessionType(raw)
    except ValueError:
        return SessionType.UNKNOWN, f"unknown_{raw}"
    if kind is P.AccSessionType.UNKNOWN:
        return SessionType.UNKNOWN, f"unknown_{raw}"
    return _SESSION_TYPES.get(kind, SessionType.UNKNOWN), SESSION_NAMES[kind]


def slug(text: str) -> str:
    """Id component: lower-case, whitespace and ':' replaced so ``acc:<track>`` always parses back."""
    return "_".join(text.lower().replace(":", "_").split())


def _finite(v: Any) -> float | None:
    f = float(v)
    return f if math.isfinite(f) else None


def _flag(raw: int) -> bool | None:
    """A documented 0/1 int: anything else is unknown (it would hint at a misread page)."""
    return None if raw not in (0, 1) else bool(raw)


def _ms(raw: int) -> int | None:
    """An integer time in ms; ACC's INT32_MAX "no value" sentinel and negative values are None."""
    return None if raw == P.INT32_MAX or raw < 0 else raw


def _unit(v: Any, lo: float = 0.0) -> float | None:
    """A value documented as ``lo``..1, clamped within ``PEDAL_TOLERANCE``; further out -> None."""
    f = _finite(v)
    if f is None or not lo - PEDAL_TOLERANCE <= f <= 1.0 + PEDAL_TOLERANCE:
        return None
    return min(1.0, max(lo, f))


def _gear(raw: int) -> int | None:
    return raw - 1 if 0 <= raw <= MAX_GEAR_RAW else None


def _wheels(raw: Any, lo: float, hi: float, *, zero_is_unknown: bool = False) -> Wheels[float] | None:
    """Four per-wheel values in Kunos' FL, FR, RL, RR order, all finite and in ``lo``..``hi``; else None."""
    vals = [_finite(v) for v in raw]
    if any(v is None or not lo <= v <= hi for v in vals):
        return None
    if zero_is_unknown and all(v == 0.0 for v in vals):
        return None  # an all-zero array is "no data yet" (garage, loading), not four tyres at exactly 0
    return Wheels.from_fl_fr_rl_rr([float(v) for v in vals if v is not None])


def resolve_track_length(track: str | None, spline_length_m: float | None) -> tuple[float | None, str]:
    """``(length, source)``: a plausible ``trackSplineLength``, else ``tracks.py``'s length, else unknown."""
    table = tracks.track_length_m(track)
    s = spline_length_m
    plausible = s is not None and MIN_TRACK_LENGTH_M <= s <= MAX_TRACK_LENGTH_M
    if plausible and s is not None and (table is None or abs(s / table - 1.0) <= TRACK_LENGTH_TOLERANCE):
        return s, LENGTH_SPLINE
    if table is not None:
        return table, LENGTH_TABLE
    return None, LENGTH_UNKNOWN


# ---------------------------------------------------------------------------------------------- adapter
class AccAdapter:
    """Stateful decoder for one ACC shared-memory stream (one game instance on this PC)."""

    def __init__(self) -> None:
        self.info = ACC_INFO
        self.stats = DecodeStats()
        self.evidence: dict[str, Votes] = {name: Votes() for name in EVIDENCE_CHECKS}
        self._verdicts: dict[str, int | None] = dict.fromkeys(EVIDENCE_CHECKS)
        self._static: _Static | None = None
        self._g: _Graphics | None = None
        self._s: _Session | None = None
        self._temps: tuple[float | None, float | None] = (None, None)  # (air, road) of the latest Physics page

    # ------------------------------------------------------------------ public helpers
    def reset(self) -> None:
        """Forget the session and the latest pages (a held completion is dropped: ``flush()`` first). The runtime
        evidence is knowledge about the game, not a session, so it is kept."""
        self._static = None
        self._g = None
        self._s = None
        self._temps = (None, None)

    def flush(self) -> list[Emitted]:
        """Release a completion still waiting for ``iLastTime`` (untimed) and the items behind it."""
        s = self._s
        out: list[Emitted] = []
        if s is not None and s.hold is not None:
            self.stats.count("last_lap_flushed")
            self._release_hold(s, None, out)
        return out

    def verdict(self, check: str) -> int | None:
        return self._verdicts[check]

    def can_decode(self, data: bytes) -> bool:
        try:
            return P.page_of(data) is not None
        except Exception:
            return False

    # ------------------------------------------------------------------ main entry point
    def decode(self, data: bytes, t_recv_ns: int) -> list[Emitted]:
        self.stats.packets += 1
        page = P.page_of(data)
        if page is None:
            self.stats.rejected += 1
            msg = (
                f"not an ACC snapshot: tag {bytes(data[: P.TAG_SIZE])!r}, {len(data)} bytes "
                "(expected PHYS+800, GRPH+1588 or STAT+820)"
            )
            self.stats.last_error = msg
            raise PacketRejected(msg)
        self.stats.count(page.kind)
        out: list[Emitted] = []
        try:
            s = self._s
            if s is not None and s.hold is not None and t_recv_ns >= s.hold.deadline_ns:
                self.stats.count("last_lap_timeout")
                self._release_hold(s, None, out)
            raw = page.layout.unpack_from(data, P.TAG_SIZE)
            if page is P.PHYSICS_PAGE:
                ok = self._on_physics(raw, t_recv_ns, out)
            elif page is P.GRAPHICS_PAGE:
                ok = self._on_graphics(raw, t_recv_ns, out)
            else:
                ok = self._on_static(raw, t_recv_ns, out)
            if ok:
                self.stats.decoded += 1
            else:
                self.stats.ignored += 1
        except Exception as e:  # never let one bad page kill the stream
            self.stats.errors += 1
            self.stats.last_error = f"{page.kind}: {e!r}"
            log.exception("ACC decode error (%s)", page.kind)
        return out

    # ------------------------------------------------------------------ Static
    def _on_static(self, d: dict[str, Any], t: int, out: list[Emitted]) -> bool:
        st = _Static.parse(d)
        if st.empty:  # a zeroed page (the game loading or closing): keep what the last real page said
            self.stats.count("static_empty")
            return False
        old, self._static = self._static, st
        s = self._s
        if old is None or old.key != st.key:
            log.info("ACC static: track=%r car=%r sm_version=%r", st.track, st.car_model, st.sm_version)
            check = st.layout_check
            if check is not None:
                self.stats.count(check)
            if check == "max_rpm_differs_from_appendix_7":
                log.warning(
                    "ACC Static.maxRpm %s for %s is not Kunos' %s: the Static layout may differ from the document",
                    st.max_rpm,
                    st.car_model,
                    P.CAR_MAX_RPM.get((st.car_model or "").lower()),
                )
        if s is None:
            return True
        if (s.static_key is not None and s.static_key != st.key) or s.synthetic != st.synthetic:
            g = self._g
            self._end(s, t, out, "static_changed")
            if g is not None and g.status in _LIVE_LIKE:
                self._open(g, t, out)
            return True
        s.static_key = st.key
        s.length_m, s.length_source = resolve_track_length(st.track, st.spline_length_m)
        self._maybe_info(s, t, out)
        return True

    # ------------------------------------------------------------------ Graphics
    def _on_graphics(self, d: dict[str, Any], t: int, out: list[Emitted]) -> bool:
        g = _Graphics.parse(d, t)
        self._g = g
        s = self._s
        replay = g.status == P.AccStatus.REPLAY
        if s is not None:
            reason = None
            if g.status not in (*_LIVE_LIKE, P.AccStatus.REPLAY):
                reason = "status_off"
            elif replay:
                pass  # a replay inside the session shows other moments: its laps and session say nothing new
            elif (g.session, g.session_index) != (s.session_raw, s.session_index):
                reason = "session_changed"
            elif s.prev_g is not None and g.completed_laps < s.prev_g.completed_laps:
                reason = "laps_went_back"
            if reason is not None:
                self._end(s, t, out, reason)
                s = None
        if s is None:
            if g.status not in _LIVE_LIKE:
                return False  # menus or a replay with no session: nothing to report
            s = self._open(g, t, out)
        # the session clock stands still while the game is paused or replaying
        if g.status in _FROZEN and s.frozen_since is None:
            s.frozen_since = t
        elif g.status not in _FROZEN and s.frozen_since is not None:
            s.frozen_ns += t - s.frozen_since
            s.frozen_since = None
        if replay:
            self._maybe_info(s, t, out)
            return True
        prev = s.prev_g
        s.prev_g = g
        if s.hold is not None and g.last_ms is not None and g.last_ms != s.hold.stale_last_ms:
            self._release_hold(s, g.last_ms, out)
        if prev is not None and g.completed_laps != prev.completed_laps:
            self._on_increment(s, prev, g, t, out)
        self._maybe_info(s, t, out)
        return True

    def _on_increment(self, s: _Session, prev: _Graphics, g: _Graphics, t: int, out: list[Emitted]) -> None:
        if s.hold is not None:  # a second crossing before the first lap's time arrived
            self._release_hold(s, None, out)
        if g.completed_laps != prev.completed_laps + 1 or prev.completed_laps < 0:
            self.stats.count("lap_jump")  # missed pages or a restored state: no lap can be timed honestly
            s.anchored_lap = None
            return
        lap = prev.completed_laps + 1  # Pitwall's 1-based number of the lap that just ended
        s.anchored_lap = lap + 1
        if lap in s.completed:
            self.stats.count("lap_completed_twice")
            return
        s.completed.add(lap)
        comp = LapCompletion(
            game=Game.ACC,
            t_recv_ns=t,
            lap_number=lap,
            lap_time_ms=None,
            valid=prev.valid,  # the last page before the line still describes the lap that ended
            session_time_s=s.clock_s(t),
        )
        if g.last_ms is not None and g.last_ms != prev.last_ms:
            comp.lap_time_ms = g.last_ms
            self._emit(s, comp, out)
            return
        self.stats.count("last_lap_held")
        s.hold = _Hold(comp, prev.last_ms, t + int(LAST_LAP_HOLD_S * 1e9))

    # ------------------------------------------------------------------ Physics
    def _on_physics(self, d: dict[str, Any], t: int, out: list[Emitted]) -> bool:
        s, g = self._s, self._g
        if s is None or g is None:
            self.stats.count("physics_outside_session")
            return False
        q = FrameQuality.OK
        if g.status == P.AccStatus.PAUSE:
            q |= FrameQuality.PAUSED
        elif g.status == P.AccStatus.REPLAY:
            q |= FrameQuality.REPLAY_OR_SPECTATING
        if t - g.t_ns > STALE_GRAPHICS_S * 1e9:
            q |= FrameQuality.STALE_LAP_DATA
        speed = _finite(d["speedKmh"])
        speed = speed if speed is not None and speed >= 0 else None
        steer = _unit(-float(d["steerAngle"]), lo=-1.0)
        throttle, brake = _unit(d["gas"]), _unit(d["brake"])
        clock = s.clock_s(t)
        acc = [_finite(v) for v in d["accG"]]
        w = [_finite(v) for v in d["localAngularVel"]]
        lv = [_finite(v) for v in d["localVelocity"]]
        if q == FrameQuality.OK and speed is not None:
            self._collect(s, d, clock, speed, steer, throttle, brake, acc, w, lv)
        self._temps = (_finite(d["airTemp"]), _finite(d["roadTemp"]))
        g_lon, g_lat, g_vert, yaw, body_slip = self._dynamics(acc, w, lv)
        lap = g.completed_laps + 1 if g.completed_laps >= 0 else None
        st = self._static
        sector = g.sector if st is not None and st.sector_count and 0 <= g.sector < st.sector_count else None
        pit = None if g.in_pit is None or g.in_pit_lane is None else (2 if g.in_pit else 1 if g.in_pit_lane else 0)
        rpm = int(d["rpm"])
        frame = CarFrame(
            game=Game.ACC,
            t_recv_ns=t,
            session_time_s=clock,
            frame_id=int(d["packetId"]),
            quality=q,
            throttle=throttle,
            brake=brake,
            steering=steer,
            clutch=_unit(d["clutch"]),
            speed_kph=speed,
            gear=_gear(int(d["gear"])),
            rpm=float(rpm) if rpm >= 0 else None,
            max_rpm=float(st.max_rpm) if st is not None and st.max_rpm else None,
            pos_x_m=g.pos[0] if g.pos else None,
            pos_y_m=g.pos[1] if g.pos else None,
            pos_z_m=g.pos[2] if g.pos else None,
            g_lat=g_lat,
            g_lon=g_lon,
            g_vert=g_vert,
            yaw_rate_rps=yaw,
            body_slip_rad=body_slip,
            wheel_slip_ratio=self._slip_ratio(d["slipRatio"]),
            wheel_slip_angle_rad=self._slip_angle(d["slipAngle"]),
            lap_number=lap,
            lap_distance_m=None if q & FrameQuality.REPLAY_OR_SPECTATING else self._distance(s, g, lap),
            current_lap_time_ms=g.current_ms,
            last_lap_time_ms=g.last_ms,
            sector=sector,
            lap_invalid=None if g.valid is None else not g.valid,
            pit_status=pit,
            race_position=g.position,
            tyre_core_temp_c=_wheels(d["TyreCoreTemp"], *TYRE_CORE_RANGE_C, zero_is_unknown=True),
            tyre_pressure_psi=_wheels(d["wheelPressure"], *TYRE_PSI_RANGE),
            brake_temp_c=_wheels(d["brakeTemp"], *BRAKE_TEMP_RANGE_C, zero_is_unknown=True),
            tyre_compound=None if g.rain_tyres is None else ("wet" if g.rain_tyres else "dry"),
            traction_control=g.tc,
        )
        self._emit(s, frame, out)
        self._maybe_info(s, t, out)
        return True

    def _distance(self, s: _Session, g: _Graphics, lap: int | None) -> float | None:
        """``normalizedCarPosition`` x length, unwrapped within the lap (see the module docstring)."""
        length, f = s.length_m, g.npos
        if length is None or f is None or lap is None:
            return None
        if s.dist_lap != lap:
            s.dist_lap, s.dist_lost = lap, False
            # at an observed crossing the spline wrapped just after or just before; a lap joined otherwise is where
            # the spline says, unless the car sits just behind the line (a grid)
            wrap_from = 0.5 if s.anchored_lap == lap else GRID_FRACTION
            u = f - 1.0 if f >= wrap_from else f
        elif s.dist_lost or s.dist_f is None:
            return None
        else:
            prev = s.dist_f
            u = min((f - 1.0, f, f + 1.0), key=lambda c: abs(c - prev))
            if abs(u - prev) > DISTANCE_JUMP_FRACTION:
                self._lose_distance(s, "distance_jump")
                return None
        if not LAP_FRACTION_RANGE[0] <= u <= LAP_FRACTION_RANGE[1]:
            self._lose_distance(s, "distance_out_of_lap")
            return None
        s.dist_f = u
        return u * length

    def _lose_distance(self, s: _Session, reason: str) -> None:
        """This lap's distance is no longer trustworthy (teleport, or the spline wrapped with no lap counted)."""
        self.stats.count(reason)
        s.dist_lost, s.dist_f = True, None

    # ------------------------------------------------------------------ runtime evidence
    def _collect(
        self,
        s: _Session,
        d: dict[str, Any],
        clock: float,
        speed_kph: float,
        steer: float | None,
        throttle: float | None,
        brake: float | None,
        acc: list[float | None],
        w: list[float | None],
        lv: list[float | None],
    ) -> None:
        """Update the runtime evidence from one live, fresh frame (O(1))."""
        v = speed_kph / 3.6
        ev = self.evidence
        # g_lon: mean accG[2] against the measured change of speed, sign and size in g
        a_lon = acc[2]
        win = s.g_window
        if a_lon is not None:
            if win is None or clock - win[0] > G_WINDOW_MAX_S:
                s.g_window = [clock, v, 0.0, 0.0]
            else:
                win[2] += a_lon
                win[3] += 1.0
                dt = clock - win[0]
                if dt >= G_WINDOW_S:
                    measured = (v - win[1]) / dt / STANDARD_GRAVITY
                    reported = win[2] / win[3]
                    if abs(measured) >= G_MIN_MEASURED_G:
                        ratio = abs(reported) / abs(measured)
                        if G_RATIO_RANGE[0] <= ratio <= G_RATIO_RANGE[1]:
                            ev["g_lon"].add(1 if (reported > 0) == (measured > 0) else -1)
                        else:
                            ev["g_lon"].add(0)
                    s.g_window = [clock, v, 0.0, 0.0]
        a_lat, w_yaw = acc[0], w[1]
        # centripetal: |accG[0]| g == v |w[1]| (rad/s) while cornering
        if (
            a_lat is not None
            and w_yaw is not None
            and speed_kph >= CENTRIPETAL_MIN_KPH
            and abs(a_lat) >= CENTRIPETAL_MIN_G
            and abs(w_yaw) >= CENTRIPETAL_MIN_RPS
        ):
            r = v * abs(w_yaw) / (abs(a_lat) * STANDARD_GRAVITY)
            ev["centripetal"].add(1 if CENTRIPETAL_RANGE[0] <= r <= CENTRIPETAL_RANGE[1] else 0)
        # yaw sign: the same sign as the steering in normal cornering
        if (
            w_yaw is not None
            and steer is not None
            and speed_kph >= YAW_MIN_KPH
            and abs(steer) >= YAW_MIN_STEER
            and abs(w_yaw) >= YAW_MIN_RPS
        ):
            ev["yaw"].add(1 if (w_yaw > 0) == (steer > 0) else -1)
        # forward axis: localVelocity[2] carries the speed
        vz = lv[2]
        if vz is not None and speed_kph >= FORWARD_MIN_KPH:
            if abs(abs(vz) - v) <= FORWARD_TOLERANCE * v + 0.5:
                ev["forward"].add(1 if vz > 0 else -1)
            else:
                ev["forward"].add(0)
        # slip angle unit: front slip angles in a loaded corner, radians or degrees
        if (
            self._verdicts["centripetal"] == 1
            and a_lat is not None
            and speed_kph >= SLIP_ANGLE_MIN_KPH
            and abs(a_lat) >= SLIP_ANGLE_MIN_G
        ):
            fa = [_finite(x) for x in d["slipAngle"][:2]]
            if fa[0] is not None and fa[1] is not None:
                m = max(abs(fa[0]), abs(fa[1]))
                if SLIP_ANGLE_RAD_RANGE[0] <= m <= SLIP_ANGLE_RAD_RANGE[1]:
                    ev["slip_angle_unit"].add(1)
                elif SLIP_ANGLE_DEG_RANGE[0] <= m <= SLIP_ANGLE_DEG_RANGE[1]:
                    ev["slip_angle_unit"].add(-1)
                else:
                    ev["slip_angle_unit"].add(0)
        # slip ratio sign: front under braking (expected < 0), rear under power (expected > 0)
        sign = self._verdicts["g_lon"]
        if sign is not None and a_lon is not None and speed_kph >= SLIP_RATIO_MIN_KPH:
            g_lon = sign * a_lon
            sr = [_finite(x) for x in d["slipRatio"]]
            if brake is not None and brake >= 0.5 and g_lon <= -0.5 and sr[0] is not None and sr[1] is not None:
                ev["slip_ratio_braking"].add(_slip_vote((sr[0] + sr[1]) / 2.0, expected=-1))
            elif (
                throttle is not None
                and throttle >= 0.8
                and (brake or 0.0) < 0.05
                and g_lon >= 0.2
                and sr[2] is not None
                and sr[3] is not None
            ):
                ev["slip_ratio_traction"].add(_slip_vote((sr[2] + sr[3]) / 2.0, expected=1))
        self._update_verdicts()

    def _update_verdicts(self) -> None:
        for name, votes in self.evidence.items():
            v = votes.verdict()
            if v != self._verdicts[name]:
                self._verdicts[name] = v
                self.stats.count(f"evidence_{name}_{'none' if v is None else ('plus' if v > 0 else 'minus')}")
                log.info("ACC runtime evidence: %s -> %s (%s)", name, v, votes.as_dict())

    def _dynamics(
        self, acc: list[float | None], w: list[float | None], lv: list[float | None]
    ) -> tuple[float | None, float | None, float | None, float | None, float | None]:
        """(g_lon, g_lat, g_vert, yaw_rate_rps, body_slip_rad) - each None until its evidence is unambiguous."""
        vd = self._verdicts
        lon_sign, lateral_ok, yaw_sign, fwd = vd["g_lon"], vd["centripetal"] == 1, vd["yaw"], vd["forward"]
        g_lon = lon_sign * acc[2] if lon_sign is not None and acc[2] is not None else None
        local_g = lon_sign is not None and lateral_ok
        g_lat = acc[0] if local_g else None
        g_vert = acc[1] if local_g else None
        yaw = yaw_sign * w[1] if yaw_sign is not None and lateral_ok and w[1] is not None else None
        body_slip = None
        vx, vz = lv[0], lv[2]
        if (
            yaw_sign is not None
            and fwd == 1
            and vx is not None
            and vz is not None
            and math.hypot(vx, vz) >= BODY_SLIP_MIN_MPS
        ):
            right = yaw_sign * vx  # yaw + for right turns (raw) = left-handed axes: x points right
            body_slip = math.atan2(-right, vz)
        return g_lon, g_lat, g_vert, yaw, body_slip

    def _slip_angle(self, raw: Any) -> Wheels[float] | None:
        unit = self._verdicts["slip_angle_unit"]
        if unit is None:
            return None
        vals = [_finite(v) for v in raw]
        if any(v is None for v in vals):
            return None
        scale = 1.0 if unit > 0 else math.pi / 180.0
        return Wheels.from_fl_fr_rl_rr([float(v) * scale for v in vals if v is not None])

    def _slip_ratio(self, raw: Any) -> Wheels[float] | None:
        b, tr = self._verdicts["slip_ratio_braking"], self._verdicts["slip_ratio_traction"]
        if b is None or b != tr:
            return None
        vals = [_finite(v) for v in raw]
        if any(v is None for v in vals):
            return None
        return Wheels.from_fl_fr_rl_rr([b * float(v) for v in vals if v is not None])

    # ------------------------------------------------------------------ sessions
    def _open(self, g: _Graphics, t: int, out: list[Emitted]) -> _Session:
        st = self._static
        synthetic = st is not None and st.synthetic
        uid = str(SYNTHETIC_SESSION_UID) if synthetic else f"acc:{t}"
        s = _Session(
            uid=uid,
            t0_ns=t,
            session_raw=g.session,
            session_index=g.session_index,
            static_key=None if st is None or st.empty else st.key,
            synthetic=synthetic,
        )
        if st is not None:
            s.length_m, s.length_source = resolve_track_length(st.track, st.spline_length_m)
        self._s = s
        self.stats.count("sessions")
        info = self._session_info(s, t)
        s.info_key = self._info_key(s)
        out.append(info)  # SessionInfo first: it is what opens the session downstream
        out.append(
            GameEvent(
                kind=EventKind.SESSION_STARTED,
                game=Game.ACC,
                t_recv_ns=t,
                session_time_s=0.0,
                payload={"source": "derived", "track_id": info.track_id, "car_id": info.car_id},
            )
        )
        log.info("ACC session %s started (track %s, session type %s)", uid, info.track_id, g.session)
        return s

    def _end(self, s: _Session, t: int, out: list[Emitted], reason: str) -> None:
        if s.hold is not None:
            self._release_hold(s, None, out)
        out.append(
            GameEvent(
                kind=EventKind.SESSION_ENDED,
                game=Game.ACC,
                t_recv_ns=t,
                session_time_s=s.clock_s(t),
                payload={"source": "derived", "reason": reason},
            )
        )
        self.stats.count(f"session_end_{reason}")
        self._s = None

    def _emit(self, s: _Session, item: Emitted, out: list[Emitted]) -> None:
        h = s.hold
        if h is None:
            out.append(item)
            return
        h.items.append(item)
        if len(h.items) >= LAST_LAP_HOLD_MAX_ITEMS:
            self.stats.count("last_lap_hold_overflow")
            self._release_hold(s, None, out)

    def _release_hold(self, s: _Session, time_ms: int | None, out: list[Emitted]) -> None:
        h, s.hold = s.hold, None
        if h is None:
            return
        h.completion.lap_time_ms = time_ms
        if time_ms is None:
            self.stats.count("last_lap_untimed")
        out.append(h.completion)
        out.extend(h.items)

    def _info_key(self, s: _Session) -> tuple[Any, ...]:
        st, g = self._static, self._g
        air, road = self._temps
        return (
            s.uid,
            None if st is None else st.key,
            s.length_m,
            None if g is None else (g.session, g.status, g.rain, g.best_ms),
            None if air is None else round(air),
            None if road is None else round(road),
            tuple(self._verdicts.values()),
        )

    def _maybe_info(self, s: _Session, t: int, out: list[Emitted]) -> None:
        key = self._info_key(s)
        if key != s.info_key:
            s.info_key = key
            self._emit(s, self._session_info(s, t), out)

    def _session_info(self, s: _Session, t: int) -> SessionInfo:
        st, g = self._static, self._g
        air, road = self._temps
        rain = None if g is None else g.rain
        extra: dict[str, Any] = {
            "acc_status": None if g is None else g.status,
            "acc_session_index": s.session_index,
            "track_length_source": s.length_source,
            "lap_distance_status": "ok" if s.length_m is not None else "track_length_unknown",
            "best_lap_ms": None if g is None else g.best_ms,
            "acc_rain_intensity": rain,
            "acc_evidence": {name: votes.as_dict() for name, votes in self.evidence.items()},
        }
        if st is not None:
            extra.update(
                sm_version=st.sm_version,
                ac_version=st.ac_version,
                sector_count=st.sector_count,
                track_spline_length_m=st.spline_length_m,
                static_layout_check=st.layout_check,
            )
        stype, sname = session_type_of(s.session_raw)
        condition = None
        if rain is not None:
            try:
                condition = _RAIN.get(P.AccRainIntensity(rain))
            except ValueError:
                condition = None
        return SessionInfo(
            game=Game.ACC,
            t_recv_ns=t,
            platform=Platform.PC,
            session_uid=s.uid,
            track_id=None if st is None else st.track_id,
            track_name=None if st is None else tracks.track_label(st.track),
            track_length_m=s.length_m,
            session_type=stype,
            session_type_raw=sname,
            car_id=None if st is None else st.car_id,
            car_name=None if st is None else st.car_name,
            weather=Weather(
                condition=condition,
                air_temp_c=round(air) if air is not None and AMBIENT_RANGE_C[0] <= air <= AMBIENT_RANGE_C[1] else None,
                track_temp_c=round(road)
                if road is not None and AMBIENT_RANGE_C[0] <= road <= AMBIENT_RANGE_C[1]
                else None,
            ),
            network_game=None if st is None else st.is_online,
            session_time_s=s.clock_s(t),
            extra=extra,
        )


def _slip_vote(x: float, expected: int) -> int | None:
    """+1 when a slip ratio has Pitwall's expected sign, -1 when the opposite, 0 when its size fits no ratio (a
    percentage, say); None when it is too small to say anything."""
    if abs(x) > SLIP_RATIO_BAD:
        return 0
    if abs(x) < SLIP_RATIO_MIN:
        return None
    return 1 if (x > 0) == (expected > 0) else -1
