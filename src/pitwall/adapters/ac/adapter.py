"""Assetto Corsa (original) Remote Telemetry adapter: handshake reply + RTCarInfo (+ RTLap) -> unified model.

Layouts and their evidence are in ``packets.py``. This module only interprets values. Laps, times and distance are
derived from the handshake reply and the continuous RTCarInfo stream alone, because that is all pitwall's live client
subscribes to (``ingest/ac_client.py``). RTLap (SUBSCRIBE_SPOT) decodes on a PS5 (212 B UTF-16; the probe's second
socket), but no RTLap was ever seen at a line crossing - that socket opened after the only one - so how RTLap times
a lap is unverified; when present it is used only where ``lastLap`` is stale, and never completes a lap twice.

Evidence: a recorded PS5 capture (PS4 build, 2026-10-11 live probe by ``scripts/probe_ac.py``, ``ks_audi_r8_plus`` at
``ks_silverstone``, 14,356 RTCarInfo at 59.8 Hz, 0 rejected) replayed through this adapter
(``tests/recorded/test_ac_ps5_real.py``); pitwall's own client -> runtime path has not run against the console yet.
The handshake reply is 408 B UTF-16; RTCarInfo is 328 B with ``'a'`` and ``size`` 328; ``isInPit`` toggles at byte 24
while 26/27 stay 0 (natural alignment); ``speed_Kmh`` == 3.6 x ``speed_Ms``; the ``carCoordinates`` path equals the
integral of ``speed_Ms`` to 0.02 % (metres); ``carPositionNormalized`` wraps 0.99999 -> 0.00018 at the line and
``lapCount`` increments two packets (35.5 ms) later with ``lapTime`` restarting and ``lastLap`` = 138,817 ms in that
same packet - one real crossing. ``trackConfig`` repeated the track name, so the console does not say which layout
is loaded: layouts of one track share a track id, and only lengths tell them apart (here, and in
``analysis.compare.check_compatibility`` / reference choice / track models downstream).

What AC sends, and what pitwall derives (every derivation is labelled in ``AC_INFO.fields``)
-------------------------------------------------------------------------------------------
Identity
    The handshake reply carries car, driver, track and track configuration names. Track id is
    ``ac:<track>[:<config>]`` (lower-cased, so PC folder names and any console spelling of the same name meet),
    car id ``ac:car:<car>``. RTCarInfo carries no identity at all, so frames that arrive without a preceding reply
    get no track or car id: unknown stays unknown. The platform cannot be told from the wire (PS4 and PC send the
    same structures), so it is whatever the caller passes in (``Platform.UNKNOWN`` by default).

Sessions, back to pits, restarts and teleports
    AC has no session id. A session starts at the first RTCarInfo and gets the uid ``ac:<t_recv_ns>`` (deterministic
    on replay). It ends when a handshake reply names a different car/track/config/driver, or when ``lapCount`` goes
    backwards: a session restart, or a return to the pits that resets the lap counter (PS5, t = 165.9 s of the probe:
    ``lapCount`` 1 -> 0, ``lapTime``/``lastLap``/``bestLap`` reset, car in the pit box). Lap numbers are unique per
    stored session, so this must be a new session; the lap in progress ends incomplete (no completion).
    A reply with the *same* identity is a re-subscription and continues the session. A reply naming
    ``SYNTHETIC_CAR_NAME`` maps the session to ``SYNTHETIC_SESSION_UID`` so the session manager flags it synthetic.

    * ``lapCount`` + 1 with ``lapTime`` neither restarting nor running on from the lap before - it jumps - or with a
      teleport is a restored state, not a line crossing. The probe shows one 2.6 s after the reset above: the game
      restored the pre-reset state (``lapCount`` 1, ``lapTime`` 73 s, ``lastLap`` = ``bestLap`` = 138,817 ms, the
      exact position of the last packet before the reset, 534 m from the pit box) and re-sent the RTLap of the lap
      completed 80 s earlier. No completion is emitted (``increment_without_lap_start``); the new lap starts
      unanchored and is completed ``valid=False``.
    * ``lapCount`` + 1 with ``lapTime`` still running on from the lap before (no teleport) is a crossing whose lap
      clock lags the counter (not seen on PS5; PC untested): its completion is held until ``lapTime`` restarts, at
      most ``LAST_LAP_HOLD_S`` - that restart is not a lap reset. If it never restarts the completion is released
      untimed and ``valid=False``, and so is the lap that began there.
    * ``lapTime`` going backwards without an increment (lap reset) or a teleport (the car moved further than its
      speed allows: reset to track, sent to the pit box with the lap clock still running as at t = 173.9 s) marks
      the lap ``valid=False`` and stops its distance trace, so a lap whose time and trace no longer belong together
      can never become a reference.

Clock (``session_time_s``)
    RTCarInfo has no game clock. The adapter uses the host receive clock (``t_recv_ns``, monotonic) relative to the
    session start, but does not advance it while the simulation is *frozen* (position and ``lapTime`` both unchanged
    between packets - AC pausing physics; the PS5 keeps streaming identical packets), and advances one short step
    when it unfreezes. A pause therefore never looks like packet loss to ``LapAssembler``; frozen frames are flagged
    ``PAUSED``. If AC stops sending during a pause the gap stays visible (that lap is flagged incomplete).

Lap number, times, completion
    ``lapCount`` counts completed laps, so pitwall's 1-based lap is ``lapCount + 1``. A crossing completes the
    previous lap with ``lastLap`` as its time when it changed in the crossing packet (PS5: it did). Otherwise an
    RTLap for that lap received at most ``RT_LAP_EARLY_MAX_S`` before the increment times it; otherwise an unchanged
    ``lastLap`` that lies within one packet interval after the lap's own clock just before the line (an equal lap
    time); otherwise the completion and the frames after it are held for up to ``LAST_LAP_HOLD_S`` and released as
    soon as ``lastLap`` changes or an RTLap for that lap arrives, or with ``lap_time_ms=None`` on timeout. The
    completion always precedes the next lap's frames, which is what ``LapAssembler`` needs.

    RTLap (``lap`` = 0-based index of the completed lap; the PS5 re-send after the restore had ``lap`` 0 for the
    ``lapCount`` 0 -> 1 lap) for the player: after the completion it is compared with the emitted time
    (``rt_lap_confirmed`` / ``rt_lap_time_mismatch``). An early RTLap is dropped after ``RT_LAP_EARLY_MAX_S``, on a
    lap reset or a teleport. Exactly one completion per lap: a lap number is never completed twice in a session, and
    an RTLap for a lap this session did not complete is ignored (``rt_lap_unmatched``).

Pit status
    ``isInPit`` was 1 only with the car stationary in the pit box; driving the pit lane (PS5: ~8 s, ~29 m off the
    racing line) it stayed 0. So 1 -> ``pit_status`` 2 and 0 -> ``None``: 0 does not mean "on track".

Lap distance (``lap_distance_m``)
    ``carPositionNormalized`` is AC's spline position (0..1 of a lap) - an *absolute* position on the circuit, so
    unlike GT7/Forza nothing drifts. Two numbers turn it into metres, and neither is on the wire:

    * where the timing line is on the spline (``line_norm``). If a ``lapCount`` increment on a continuous stream
      happens within ``ZERO_LINE_TOL`` of spline position 0 (the spline wrapped at, or a couple of packets before,
      the increment), spline 0 *is* the line for this session (``ac_line_source='spline_zero'``); every later
      crossing is checked against it like any trusted line. PS5 Silverstone: increment at spline 0.00077, 2 packets
      (~2 m) after the wrap. Otherwise (a track whose spline origin is elsewhere) the line is learned from
      increments: the midpoint of the spline positions either side of an increment is a *candidate* (a console might
      increment at a race start or pit exit), trusted once a second increment agrees within the two observations'
      packet spacing; a disagreeing one replaces it;
    * the track length, ``derived`` and never fabricated. An early **estimate** = driven path (3-D
      ``carCoordinates`` steps) / spline progress, accumulated only on laps that began with an observed crossing
      (the out-lap can include the pit lane, which runs off the spline - PS5: path/spline 4 % short there - without
      ``isInPit`` saying so) over clean steps (no receive gap > 0.5 s, no teleport, no pause, spline moving forward
      by < 5 % of a lap per packet, not in the pit box), published once it has covered ``EST_MIN_PROGRESS`` of a lap
      and stayed inside a band ``EST_STABLE_REL`` wide over the last ``EST_STABLE_WINDOW``. That band shows the
      running ratio has settled, not that it is accurate: path/spline varies section to section (PS5, per 5 % of
      the lap: 2834..3247 m), so a partial-lap estimate is good to a few percent (PS5: 2945.3 m after 15 % of lap
      2, 1.0 % below the 2974.5 m of all 1.76 clean laps). The first full lap from line to line (anchored, clean, no
      pit stop) then measures the length over exactly one spline lap - **once per session**: from then on the
      length is fixed, so the same corner sits at the same distance on every lap. A measurement within
      ``EST_CONFIRM_TOL`` of the estimate keeps the estimate's value (the lap it scaled shares the scale); otherwise
      the measurement replaces it. A lap with any distance scaled by an estimate that its own full lap did not
      confirm is completed ``valid=False`` (``estimate_scaled_lap_void``): it can never become a reference or
      track-model material next to laps of another scale. The length is the driven line, about 1 % off the
      centreline, which only scales distances uniformly.

    Until both are known ``lap_distance_m`` is ``None`` (``SessionInfo.extra['lap_distance_status']`` says why).
    Pass ``known_tracks`` (geometry from earlier sessions, published in ``SessionInfo.track_length_m`` /
    ``extra['ac_line_norm']`` / ``extra['track_length_quality']``) to have distances from the first frame and
    identical scaling across sessions. Laps that begin with an observed line crossing start at ~0 m (a few metres
    either side); a lap joined mid-track starts at its true position (``LapAssembler`` flags it incomplete) and
    loses its distance if it crosses the line without an increment, because how the game then counts that lap is
    unknown.

    Stored geometry is a hypothesis the live stream can overturn (the console may send a stale track name, the
    console does not name the layout, or a track update may move the spline origin under the same name):

    * a lap whose ``lapCount`` increment disagrees with the trusted line ends where the line is not, so its time and
      distance trace do not belong together: it is completed ``valid=False``. One such crossing (race start? pit
      exit?) changes nothing else; when the next crossing agrees with it instead of the trusted line, the line is
      rejected (``line_rejected``): it moves to where the two crossings agree, the length is forgotten and
      re-estimated, and the stored entry is dropped;
    * a stored full-lap length is checked on the first anchored full lap: within ``KNOWN_LENGTH_TOLERANCE`` (the
      same layout, driven on another line) it is kept unchanged (identical scaling across sessions); further off it
      is replaced by the measurement (``length_rejected``; that lap is completed ``valid=False``). A stored
      *estimate* is checked like this session's own (``EST_CONFIRM_TOL``), and counts as rejected when more than
      ``KNOWN_LENGTH_TOLERANCE`` off.

    Either rejection sets ``SessionInfo.extra['ac_geometry_rejected']`` for the rest of the session, so older stored
    sessions carrying the bad geometry stop seeding later ones (``core.runtime.ac_known_tracks``). A pit lane that
    makes the console count two consecutive increments at the pit exit (out-lap straight into an in-lap) would move
    a correct line the same way; the next two line crossings move it back (two laps ``valid=False``).

Units and conventions (spec names; see ``AC_INFO`` for what the PS5 capture confirmed)
    speed ``speed_Kmh``; pedals ``gas``/``brake``/``clutch`` 0..1 (the PS5 clutch rests at 1.0, i.e. 1 = engaged);
    gear 0 = R, 1 = N, 2 = 1st -> -1, 0, 1.. (PS5: 1 at standstill, 2..6 rising with speed; R not yet seen);
    ``accG_*`` in g, with the longitudinal sign *learned* by comparing ``accG_frontal`` with the measured change of
    ``speed_Ms`` (``g_lon`` stays ``None`` until the evidence is unambiguous); world position ``carCoordinates``
    (metres, y up). ``steer`` is **not** mapped: its unit is undocumented (PS5 raw range -228..227; the wheel's
    rotation setting during the probe is not recorded, so the unit is not settled), so ``steering`` stays ``None``
    and the observed raw range is reported in ``SessionInfo.extra``. RTCarInfo has no tyre temperatures, pressures,
    wear, fuel, sectors, lap validity or weather - those stay ``None``.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from pitwall.adapters.ac import packets as P
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
)

log = logging.getLogger(__name__)

STANDARD_GRAVITY = 9.80665
SESSION_INFO_INTERVAL_S = 0.5  # periodic SessionInfo (best lap, assists), like F1's 2 Hz session packet
CROSSING_MAX_GAP_S = 0.5  # an increment seen after a longer receive gap is not a usable line observation
LEARN_MAX_GAP_S = 0.5  # a step after a longer receive gap does not measure the track length
LEARN_FRACTION_TOL = 0.05  # a measuring lap must cover 1 +/- this spline fraction from line to line
MIN_TRACK_LENGTH_M = 200.0
MAX_TRACK_LENGTH_M = 30_000.0  # Nordschleife + GP is ~25.4 km
LINE_MAX_STEP = 0.05  # spline step across the line larger than this: not a usable line observation
LINE_CONFIRM_SLACK = 0.0005  # two line observations agree within half their spacings + this (spline fraction)
ZERO_LINE_TOL = 0.002  # an increment this close to spline 0 (circular) makes spline 0 the line (PS5: 0.00064)
LAP_START_SLACK_MS = 500  # a crossing restarts lapTime: it may not exceed the receive gap + this
KNOWN_LENGTH_TOLERANCE = 0.03  # a stored full-lap length this far (relative) from a measured full lap: rejected
EST_CONFIRM_TOL = 0.005  # an estimate a full lap confirms this closely is kept; otherwise the laps it scaled are void
ANCHORED_FRACTION_RANGE = (-0.25, 1.25)  # outside this an anchored lap's distance is no longer trustworthy
EST_MIN_PROGRESS = 0.15  # the length estimate needs at least this much clean spline progress (fraction of a lap)
EST_STABLE_WINDOW = 0.10  # ... and must have stayed within EST_STABLE_REL over the last this much progress
EST_STABLE_REL = 0.005  # width of the band (max - min, relative) the estimate must stay in over the window
EST_MARK_STEP = 0.01  # spline progress between two stability checkpoints
TELEPORT_SLACK_M = 20.0  # displacement beyond 1.5 x speed x dt + this = car reset to the track / pits
TELEPORT_MAX_DT_S = 1.0  # only judge displacement over short receive gaps
FROZEN_EPS_M = 1e-4  # position unchanged within this (and lapTime unchanged): simulation frozen
LEAVE_PAUSE_DT_S = 0.05  # clock step for the first packet after a frozen stretch
LAP_TIME_RESET_MS = 500  # lapTime going back by more than this without an increment: lap reset
LAST_LAP_HOLD_S = 0.5  # max wait for lastLap to update (and for a lagging lapTime to restart) after an increment
RT_LAP_EARLY_MAX_S = 1.0  # an RTLap that came before the increment times it only if it is at most this old
LAST_LAP_HOLD_MAX_FRAMES = 400  # hard bound on held frames (PC reportedly streams up to ~333 Hz)
LAST_LAP_MATCH_MIN_WINDOW_MS = 20.0  # unchanged lastLap: accepted when it lies within one packet interval (at
LAST_LAP_MATCH_SLACK_MS = 5.0  #   least this long) + slack after the lap's own clock just before the line
PEDAL_TOLERANCE = 0.02  # pedal values this far outside 0..1 are clamped; further out -> unknown
NORM_TOLERANCE = 0.01  # carPositionNormalized outside [-tol, 1 + tol] -> unknown for that frame
MAX_GEAR_RAW = 11  # AC gear 11 = 10th; anything higher is reported as unknown, never guessed
G_SIGN_WINDOW_S = 0.1  # g_lon sign check: compare mean accG_frontal with d(speed_Ms)/dt over this window
G_SIGN_MIN_MEASURED_G = 0.3
G_SIGN_MIN_REPORTED_G = 0.2
G_SIGN_MIN_SAMPLES = 20
G_SIGN_RATIO = 9  # one sign must win by this factor before it is trusted

LENGTH_ESTIMATE = "derived:path_over_spline_estimate"  # early estimate from a partial lap
LENGTH_ESTIMATE_CONFIRMED = "derived:estimate_confirmed_by_full_lap"  # kept: a full lap agreed within 0.5 %
LENGTH_FULL_LAPS = "derived:full_lap_path"  # the first full lap measured in this session
LENGTH_KNOWN = "known"  # from an earlier session (``known_tracks``)

_RV = SupportLevel.RECORDED_VALIDATED
_C = SupportLevel.COMMUNITY_DOCUMENTED
_PART = SupportLevel.PARTIAL
_V = SupportLevel.UNVERIFIED
_U = SupportLevel.UNSUPPORTED
_PS5 = "PS5 capture (PS4 build, 2026-10-11 live probe, replayed)"

AC_INFO = AdapterInfo(
    game=Game.AC,
    name="Assetto Corsa Remote Telemetry (UDP 9996: handshake 408 B, RTCarInfo 328 B, RTLap 212 B)",
    transport="udp client (handshake + SUBSCRIBE_UPDATE to the game's port 9996; replies to our ephemeral port)",
    default_port=P.AC_PORT,
    ground_plane=("pos_x_m", "pos_z_m"),  # carCoordinates y is up (community; PS5 y range -6.7..3.9 m)
    platforms={
        Platform.PC: _C,  # same structures as the consoles; not yet tested by pitwall on a PC
        Platform.PS4: _C,  # 2017-2020 community captures: handshake reply + 328-byte stream
        # PS4 build via back-compat. The probe script validated the protocol live (handshake, stream); this adapter's
        # decode and lap logic only ran on its capture (tests/recorded), pitwall's own client/service path not yet
        Platform.PS5: _RV,
        Platform.XBOX: _U,  # Xbox One build has no telemetry interface (game-compatibility.md §1.2)
    },
    fields={
        "speed_kph": FieldSupport(
            _RV, f"RTCarInfo.speed_Kmh @8 (abs); {_PS5}: == 3.6 x speed_Ms in every packet, 0..229 km/h"
        ),
        "throttle": FieldSupport(_RV, f"gas @56, 0..1; {_PS5}: full range, 1 with the car accelerating"),
        "brake": FieldSupport(_RV, f"brake @60, 0..1; {_PS5}: full range, ABS active only with brake > 0.2"),
        "clutch": FieldSupport(
            _V, "clutch @64, 0..1; PS5 rests at 1.0, so 1 = clutch engaged (pedal released) - direction not settled"
        ),
        "steering": FieldSupport(
            _V,
            "steer @72 has no documented unit (PS5 raw -228..227; radians / wheel degrees / normalised all claimed): "
            "not mapped; raw range in SessionInfo.extra['steer_raw_range']",
        ),
        "gear": FieldSupport(
            _C,
            "gear @76: 0 = R, 1 = N, 2.. = 1st.. -> -1, 0, 1.. (MIT clients agree; PS5: 1 at standstill, 2..6 rising "
            "with speed; reverse not yet seen)",
        ),
        "rpm": FieldSupport(_C, "engineRPM @68 (PS5 19..8505)"),
        "max_rpm": FieldSupport(_U, "not sent"),
        "pos_x_m": FieldSupport(_RV, f"carCoordinates[0] @316, metres ({_PS5}: path == integral of speed_Ms, 0.02 %)"),
        "pos_y_m": FieldSupport(_RV, "carCoordinates[1] @320 (up axis)"),
        "pos_z_m": FieldSupport(_RV, "carCoordinates[2] @324"),
        "vel_x_mps": FieldSupport(_U, "only speed magnitudes are sent, no velocity vector"),
        "g_lat": FieldSupport(_C, "accG_horizontal @32 (g; sign convention undocumented)"),
        "g_lon": FieldSupport(
            _C,
            "accG_frontal @36 (g); sign learned online against d(speed_Ms)/dt, None until unambiguous (PS5: +1, "
            "4637 agreeing windows, 0 disagreeing)",
        ),
        "g_vert": FieldSupport(_C, "accG_vertical @28 (g; whether gravity is included is undocumented)"),
        "yaw_rad": FieldSupport(_U, "no orientation in RTCarInfo"),
        "session_time_s": FieldSupport(
            _PART, "derived: host receive clock, not advanced while the simulation is frozen"
        ),
        "frame_id": FieldSupport(_U, "no packet counter"),
        "lap_number": FieldSupport(_RV, f"lapCount @52 + 1 (lapCount = completed laps; {_PS5})"),
        "current_lap_time_ms": FieldSupport(_RV, f"lapTime @40 (ms; restarts at the line; {_PS5})"),
        "last_lap_time_ms": FieldSupport(_RV, "lastLap @44 (ms; 0 -> None; updated in the crossing packet on PS5)"),
        "best_lap_ms": FieldSupport(_C, "bestLap @48 (ms; 0 -> None) in SessionInfo.extra['best_lap_ms']"),
        "lap_completion": FieldSupport(
            _RV,
            "derived: lapCount increment with lapTime restarting (or restarting within 0.5 s), time = lastLap from "
            "the crossing packet, else a just-received RTLap, else held up to 0.5 s; one completion per lap; "
            f"{_PS5}: ONE real crossing (lastLap = 138,817 ms in the crossing packet) plus a restored state that is "
            "correctly not a lap. Not yet run end to end in the service",
        ),
        "lap_distance_m": FieldSupport(
            _PART,
            "derived: (carPositionNormalized @308 - line) x track length; line = spline 0 when the first increment "
            "coincides with the spline wrap (PS5: yes), else learned from two crossings; None until line and "
            "length are known; laps scaled by an unconfirmed length estimate are completed valid=False",
        ),
        "track_length_m": FieldSupport(
            _PART,
            "derived: driven path (carCoordinates) / spline progress - an estimate after >= 15 % of a lap of clean "
            "driving from the first crossing (good to a few %: PS5 2945.3 m vs 2974.5 m over 1.76 laps), then fixed "
            "by the first full lap (the estimate kept if within 0.5 %); or known_tracks (kept if the first full lap "
            "is within 3 %). Layouts share a track id on consoles: only the length tells them apart. No full PS5 lap "
            "measured yet",
        ),
        "pit_status": FieldSupport(
            _PART,
            "isInPit @24: 1 -> 2 (in the pit box), 0 -> None. PS5: byte 24 toggles while 26/27 stay 0 (natural "
            "alignment); 1 only with the car stationary in the pit box, 0 while driving the pit lane (~8 s, ~29 m "
            "off the racing line), so the pit lane is not detected",
        ),
        "abs_active": FieldSupport(_C, "isAbsInAction @21 (PS5: only with brake > 0.2)"),
        "assists": FieldSupport(_C, "isAbsEnabled @20 / isTcEnabled @23 -> SessionInfo.assists"),
        "traction_control": FieldSupport(_U, "only an enabled flag (assists['tc']), no TC level"),
        "track_id": FieldSupport(
            _C,
            "handshake trackName/trackConfig -> 'ac:<track>[:<config>]' (PS5 sends trackConfig = trackName, so the "
            "layout is not on the wire)",
        ),
        "track_name": FieldSupport(_RV, "handshake trackName (+ trackConfig); PS5: UTF-16 strings decode cleanly"),
        "car_id": FieldSupport(_RV, "handshake carName -> 'ac:car:<name>' (PS5: 'ks_audi_r8_plus')"),
        "session_uid": FieldSupport(
            _PART, "derived: no session id (split on handshake identity change / lapCount reset)"
        ),
        "platform": FieldSupport(_U, "not on the wire (PC and PS4 send identical structures); set by configuration"),
        "rt_lap": FieldSupport(
            _RV,
            f"RTLap 212 B UTF-16 (SUBSCRIBE_SPOT on a second socket; {_PS5}): layout and strings decode -> GameEvent. "
            "Timing semantics UNVERIFIED: no RTLap was seen at a line crossing (only a reset marker and a re-send "
            "after a restored state); the service does not subscribe to SPOT. Used only when lastLap is stale",
        ),
        "tyre_surface_temp_c": FieldSupport(_U, "not in RTCarInfo"),
        "tyre_inner_temp_c": FieldSupport(_U, "not in RTCarInfo"),
        "tyre_pressure_psi": FieldSupport(_U, "not in RTCarInfo"),
        "tyre_wear_pct": FieldSupport(_U, "not in RTCarInfo"),
        "brake_temp_c": FieldSupport(_U, "not in RTCarInfo"),
        "fuel_kg": FieldSupport(_U, "not in RTCarInfo"),
        "fuel_litres": FieldSupport(_U, "not in RTCarInfo"),
        "sector": FieldSupport(_U, "no sector data"),
        "lap_invalid": FieldSupport(_U, "no lap validity flag"),
        "race_position": FieldSupport(_U, "not in RTCarInfo"),
        "session_type": FieldSupport(_U, "not sent"),
        "weather": FieldSupport(_U, "not sent"),
        "setup": FieldSupport(_U, "not sent"),
    },
    notes=(
        "Implemented from Kunos' Remote Telemetry spec (field list) + observed sizes and two MIT clients (layout). "
        "PS5 (PS4 build), 2026-10-11: the probe script validated the protocol live (handshake answered, 14,356 "
        "RTCarInfo at 59.8 Hz, 0 rejected); this adapter is validated on that recorded capture "
        "(tests/recorded/test_ac_ps5_real.py: one lap crossing). pitwall's own client/service path, lap storage "
        "and coaching are still to be run on a full AC session.",
        "pitwall must handshake with the game (UDP 9996) - nothing to configure in the game; re-registers per session.",
        "Lap distance = spline position x track length: spline 0 is the line when the first crossing coincides with "
        "the spline wrap (PS5); the length is estimated after ~15-25 % of a lap from that crossing, then fixed by the "
        "first full lap (or known from an earlier session). Laps scaled by an unconfirmed estimate are void.",
        "Steering is not mapped (unit undocumented). No tyre, fuel, sector, validity or weather data in the protocol.",
        "The console's trackConfig repeats the track name: layouts of one track share a track id. Stored geometry "
        "of another layout is rejected by the first full lap's length check; references, comparisons and track "
        "models downstream are restricted to sessions of a compatible track length (within 3 %).",
    ),
)


@dataclass(frozen=True, slots=True)
class AcTrackGeometry:
    """What turns a spline position into metres on one track: total length and the spline position of the line.

    ``estimated``: the length is an early partial-lap estimate (no full lap was measured): a session that starts
    from it refines it with every full lap instead of keeping it fixed.
    """

    length_m: float
    line_norm: float | None = None  # carPositionNormalized at the timing line; None = learn it this session
    estimated: bool = False

    def __post_init__(self) -> None:
        if not (math.isfinite(self.length_m) and MIN_TRACK_LENGTH_M <= self.length_m <= MAX_TRACK_LENGTH_M):
            raise ValueError(f"implausible AC track length {self.length_m!r} m")
        if self.line_norm is not None and not (math.isfinite(self.line_norm) and 0.0 <= self.line_norm < 1.0):
            raise ValueError(f"line_norm must be in [0, 1), got {self.line_norm!r}")

    @classmethod
    def from_session(cls, track_length_m: Any, extra: Mapping[str, Any] | None) -> AcTrackGeometry | None:
        """Rebuild from a stored session (``sessions.track_length_m`` + ``info['ac_line_norm']`` +
        ``info['track_length_quality']``); None if unusable."""
        try:
            length = float(track_length_m)
            raw = (extra or {}).get("ac_line_norm")
            line = None if raw is None or isinstance(raw, bool) else float(raw)
            estimated = (extra or {}).get("track_length_quality") == "estimate"
            return cls(length, line, estimated)
        except (TypeError, ValueError):
            return None


def slug(text: str) -> str:
    """Id component: lower-case, whitespace and ':' replaced so ``ac:<track>:<config>`` always parses back."""
    return "_".join(text.lower().replace(":", "_").split())


@dataclass(frozen=True, slots=True)
class AcIdentity:
    """Who/where, from one handshake reply."""

    car: str | None
    driver: str | None
    track: str | None
    config: str | None
    wide: bool
    status: int
    version: int

    @classmethod
    def from_response(cls, hs: P.HandshakeResponse) -> AcIdentity:
        return cls(hs.car_name, hs.driver_name, hs.track_name, hs.track_config, hs.wide, hs.identifier, hs.version)

    @property
    def key(self) -> tuple[str | None, ...]:
        return (self.car, self.driver, self.track, self.config)

    @property
    def synthetic(self) -> bool:
        return self.car == P.SYNTHETIC_CAR_NAME

    @property
    def track_id(self) -> str | None:
        if not self.track:
            return None
        return f"ac:{slug(self.track)}:{slug(self.config)}" if self.config else f"ac:{slug(self.track)}"

    @property
    def track_label(self) -> str | None:
        if not self.track:
            return None
        return f"{self.track} ({self.config})" if self.config else self.track

    @property
    def car_id(self) -> str | None:
        return f"ac:car:{slug(self.car)}" if self.car else None


# ---------------------------------------------------------------------------------------------- per-session state
@dataclass(slots=True)
class _Lap:
    """Distance state of the lap in progress (the lap pitwall numbers ``lapCount + 1``)."""

    anchored: bool  # began with a lapCount increment seen on a continuous stream
    f: float | None = None  # unwrapped spline fraction since the timing line; None = unknown
    lost: bool = False  # distance no longer trustworthy for the rest of this lap
    compromised: bool = False  # lap reset / teleport / restored state: its completion is reported valid=False
    learn: bool = False  # measures the track length over this full lap
    f_start: float | None = None
    path_m: float = 0.0
    est_scaled: bool = False  # a distance of this lap was scaled by an unconfirmed partial-lap estimate
    scale_confirmed: bool = False  # ... and this lap's own full-lap measurement confirmed it (EST_CONFIRM_TOL)


@dataclass(slots=True)
class _Estimate:
    """Early track-length estimate: driven path / spline progress over clean steps."""

    path_m: float = 0.0
    progress: float = 0.0
    next_mark: float = EST_MARK_STEP
    marks: list[tuple[float, float]] = field(default_factory=list)  # (progress, estimate) inside the window


@dataclass(slots=True)
class _Prev:
    t_ns: int
    lap_raw: int
    lap_ms: int
    last_ms: int
    norm: float | None
    pos: tuple[float, float, float] | None
    speed_ms: float | None
    frozen: bool
    in_pit: bool | None


@dataclass(slots=True)
class _Hold:
    """A completion waiting for its time (stale ``lastLap``) and/or for ``lapTime`` to restart, with the frames
    behind it."""

    completion: LapCompletion
    stale_last_ms: int
    deadline_ns: int
    time_ms: int | None = None  # the lap time, once known
    await_clock: bool = False  # the increment came before lapTime restarted: not a crossing until it does
    items: list[Emitted] = field(default_factory=list)


@dataclass(slots=True)
class _Session:
    uid: str
    identity: AcIdentity | None
    t0_ns: int
    clock_s: float = 0.0
    lap: _Lap = field(default_factory=lambda: _Lap(anchored=False))
    prev: _Prev | None = None
    length_m: float | None = None
    line_norm: float | None = None  # candidate until ``line_confirmed``
    line_confirmed: bool = False  # spline zero, two agreeing increments, or known geometry: distances may use it
    line_source: str | None = None  # "spline_zero" | "crossings" | "known"
    line_step: float = 0.0  # spline step of the crossing that produced the candidate (its uncertainty x 2)
    line_rival: float | None = None  # a crossing that contradicted the trusted line (rejects it if the next agrees)
    line_rival_step: float = 0.0
    length_source: str | None = None
    length_estimated: bool = False  # the length is a partial-lap estimate (own or stored), not a full-lap value
    length_estimate_fraction: float | None = None  # spline progress the own estimate was based on
    length_full_lap_m: float | None = None  # this session's full-lap measurement (one per session)
    length_verified: bool = False  # final for this session: measured, or confirmed, by a full lap of this session
    geometry_rejected: bool = False  # stored/trusted geometry was contradicted by this stream
    estimate: _Estimate | None = None  # running while the length is unknown
    completed: dict[int, int | None] = field(default_factory=dict)  # lap number -> time of its emitted completion
    rt_lap_early: tuple[int, int, int] | None = None  # (lap number, time, t_recv_ns) of an RTLap before the increment
    clock_restart_from_ns: int | None = None  # an increment came before lapTime restarted: expect it shortly
    hold: _Hold | None = None
    last_info_ns: int | None = None
    info_key: tuple[Any, ...] | None = None
    snapshot: dict[str, Any] = field(default_factory=dict)  # latest slow values for SessionInfo
    steer_min: float | None = None
    steer_max: float | None = None
    g_window: list[float] | None = None  # [t0 clock, v0 m/s, sum accG_frontal, n]


def _finite(v: Any) -> float | None:
    f = float(v)
    return f if math.isfinite(f) else None


def _flag(raw: int) -> bool | None:
    """A C ``bool`` byte: only exactly 0 or 1 is trusted (anything else hints at a misread offset)."""
    return None if raw not in (0, 1) else bool(raw)


def _unit(v: Any) -> float | None:
    f = _finite(v)
    if f is None or not -PEDAL_TOLERANCE <= f <= 1.0 + PEDAL_TOLERANCE:
        return None
    return min(1.0, max(0.0, f))


def _gear(raw: int) -> int | None:
    return raw - 1 if 0 <= raw <= MAX_GEAR_RAW else None


def _circ_dist(a: float, b: float) -> float:
    d = abs(a - b) % 1.0
    return min(d, 1.0 - d)


def _circ_mid(a: float, b: float) -> float:
    """Midpoint of two spline positions along the short way round (handles the 0/1 wrap)."""
    d = ((b - a + 0.5) % 1.0) - 0.5
    return (a + 0.5 * d) % 1.0


def _forward_step(a: float, b: float) -> float:
    """Signed spline step from ``a`` to ``b`` along the short way round (positive = forward, across the wrap)."""
    return ((b - a + 0.5) % 1.0) - 0.5


class AcAdapter:
    """Stateful decoder for one AC Remote Telemetry stream (one game instance).

    ``platform``: what the integration knows about the source (the wire cannot tell PC from PS4/PS5).
    ``known_tracks``: ``{track_id: AcTrackGeometry}`` from earlier sessions, so distances are available from the
    first frame and scaled identically across sessions. The geometry registry and the ``g_lon`` sign evidence are
    knowledge about the game, not about a session, so ``reset()`` keeps them.
    """

    def __init__(
        self, platform: Platform = Platform.UNKNOWN, known_tracks: Mapping[str, AcTrackGeometry] | None = None
    ) -> None:
        self.info = AC_INFO
        self.stats = DecodeStats()
        self.platform = platform
        self._geometry: dict[str, AcTrackGeometry] = dict(known_tracks or {})
        self._g_agree = 0
        self._g_disagree = 0
        self._identity: AcIdentity | None = None
        self._s: _Session | None = None

    # ------------------------------------------------------------------ public helpers
    def add_known_track(self, track_id: str, geometry: AcTrackGeometry) -> None:
        self._geometry[track_id] = geometry

    @property
    def known_tracks(self) -> dict[str, AcTrackGeometry]:
        return dict(self._geometry)

    @property
    def identity(self) -> AcIdentity | None:
        return self._identity

    @property
    def g_lon_sign(self) -> float | None:
        """+1/-1 once accG_frontal's sign is established against measured acceleration; None until then."""
        a, d = self._g_agree, self._g_disagree
        if a >= G_SIGN_MIN_SAMPLES and a >= G_SIGN_RATIO * d:
            return 1.0
        if d >= G_SIGN_MIN_SAMPLES and d >= G_SIGN_RATIO * a:
            return -1.0
        return None

    def flush(self) -> list[Emitted]:
        """Release what the adapter still holds because the stream ended: a lap completion waiting for ``lastLap``
        (released without a time) and the frames held behind it. Call before ``reset()``; empty when nothing is held.
        """
        s = self._s
        out: list[Emitted] = []
        if s is not None and s.hold is not None:
            self.stats.count("last_lap_flushed")
            self._release_hold(s, None, out)
        return out

    def reset(self) -> None:
        """Forget the session and the handshake identity (a held completion is dropped: ``flush()`` first)."""
        self._s = None
        self._identity = None

    # ------------------------------------------------------------------ structural validation
    def can_decode(self, data: bytes) -> bool:
        """Exact AC sizes (no other pitwall protocol uses 208/212/328/408 bytes). RTCarInfo additionally needs its
        ``'a'`` identifier or a ``size`` field of 328 - either is enough (both were present on PS5)."""
        try:
            kind = P.kind_of(len(data))
            if kind is None:
                return False
            if kind is P.PacketKind.RT_CAR_INFO:
                return data[0] == P.RT_CAR_INFO_IDENTIFIER or int.from_bytes(data[4:8], "little") == P.RT_CAR_INFO.size
            return True
        except Exception:
            return False

    def _reject(self, msg: str) -> PacketRejected:
        self.stats.rejected += 1
        self.stats.last_error = msg
        return PacketRejected(msg)

    # ------------------------------------------------------------------ main entry point
    def decode(self, data: bytes, t_recv_ns: int) -> list[Emitted]:
        self.stats.packets += 1
        kind = P.kind_of(len(data))
        if kind is None:
            raise self._reject(
                f"unsupported AC remote telemetry size {len(data)} (expected 408/208 handshake reply, 328 RTCarInfo "
                "or 212 RTLap)"
            )
        self.stats.count(kind.value)
        out: list[Emitted] = []
        try:
            if kind is P.PacketKind.HANDSHAKE_RESPONSE:
                ok = self._on_handshake(P.parse_handshake_response(data), t_recv_ns, out)
            elif kind is P.PacketKind.RT_CAR_INFO:
                ok = self._on_car_info(P.parse_rt_car_info(data), t_recv_ns, out)
            else:
                ok = self._on_rt_lap(P.parse_rt_lap(data), t_recv_ns, out)
            if ok:
                self.stats.decoded += 1
            else:
                self.stats.ignored += 1
        except Exception as e:  # never let one bad packet kill the stream
            self.stats.errors += 1
            self.stats.last_error = f"{kind.value}: {e!r}"
            log.exception("AC decode error (%s)", kind.value)
        return out

    # ------------------------------------------------------------------ handshake reply / RTLap
    def _on_handshake(self, hs: P.HandshakeResponse, t: int, out: list[Emitted]) -> bool:
        ident = AcIdentity.from_response(hs)
        self.stats.count(f"handshake_{hs.encoding}")
        if hs.identifier != P.HANDSHAKE_STATUS_OK:
            self.stats.count("handshake_status_unexpected")
        s = self._s
        if s is not None and (s.identity is None or s.identity.key != ident.key):
            self._end_session(s, t, out, "handshake_identity_changed")
        if self._identity is None or self._identity.key != ident.key:
            log.info("AC handshake: car=%r track=%r config=%r (%s)", ident.car, ident.track, ident.config, hs.encoding)
        self._identity = ident
        return True

    def _on_rt_lap(self, lap: P.RtLap, t: int, out: list[Emitted]) -> bool:
        ident = self._identity
        s = self._s
        mine = ident is not None and lap.driver_name == ident.driver and lap.car_name == ident.car
        if not mine or s is None:
            self.stats.count("rt_lap_not_player")
            return False
        out.append(
            GameEvent(
                kind=EventKind.OTHER,
                game=Game.AC,
                t_recv_ns=t,
                session_time_s=s.clock_s,
                code="ac_rt_lap",
                payload={"lap": lap.lap, "time_ms": lap.time_ms, "car_identifier": lap.car_identifier},
            )
        )
        self._match_rt_lap(s, lap, t, out)
        return True

    def _match_rt_lap(self, s: _Session, lap: P.RtLap, t: int, out: list[Emitted]) -> None:
        """Use an RTLap for the player as the time of lap ``lap.lap + 1`` - without ever completing a lap twice."""
        if lap.lap < 0 or lap.time_ms <= 0:
            self.stats.count("rt_lap_without_time")  # PS5: lap -1, time 0 when the session resets
            return
        n = lap.lap + 1
        if n in s.completed:
            emitted = s.completed[n]
            if emitted == lap.time_ms:
                self.stats.count("rt_lap_confirmed")
            else:
                self.stats.count("rt_lap_time_mismatch")
                log.warning("AC: RTLap says lap %d took %d ms, the completion said %s ms", n, lap.time_ms, emitted)
            return
        if s.hold is not None and s.hold.completion.lap_number == n:
            if s.hold.time_ms is None:
                self.stats.count("rt_lap_released_hold")
                s.hold.time_ms = lap.time_ms
            if not s.hold.await_clock:
                self._release_hold(s, s.hold.time_ms, out)
            return
        if s.prev is not None and s.prev.lap_raw + 1 == n:
            # before the increment: kept for up to RT_LAP_EARLY_MAX_S, used only if lastLap is stale at the line
            s.rt_lap_early = (n, lap.time_ms, t)
            self.stats.count("rt_lap_before_increment")
            return
        self.stats.count("rt_lap_unmatched")  # a lap this session did not complete (e.g. re-sent after a restore)

    # ------------------------------------------------------------------ sessions
    def _begin_session(self, p: dict[str, Any], t: int, out: list[Emitted]) -> _Session:
        ident = self._identity
        uid = str(SYNTHETIC_SESSION_UID) if ident is not None and ident.synthetic else f"ac:{t}"
        s = _Session(uid=uid, identity=ident, t0_ns=t)
        track_id = ident.track_id if ident else None
        geo = self._geometry.get(track_id) if track_id else None
        if geo is not None:
            s.length_m, s.line_norm, s.length_source = geo.length_m, geo.line_norm, LENGTH_KNOWN
            s.length_estimated = geo.estimated
            s.line_confirmed = geo.line_norm is not None
            s.line_source = "known" if geo.line_norm is not None else None
        else:
            s.estimate = _Estimate()
        self._s = s
        self.stats.count("sessions")
        self._update_snapshot(s, p)
        out.append(self._session_info(s, t))  # SessionInfo first: it is what opens the session downstream
        out.append(
            GameEvent(
                kind=EventKind.SESSION_STARTED,
                game=Game.AC,
                t_recv_ns=t,
                session_time_s=0.0,
                payload={"source": "derived", "track_id": track_id, "car_id": ident.car_id if ident else None},
            )
        )
        log.info("AC session %s started (track %s)", uid, track_id)
        return s

    def _end_session(self, s: _Session, t: int, out: list[Emitted], reason: str) -> None:
        if s.hold is not None:
            self._release_hold(s, None, out)
        out.append(
            GameEvent(
                kind=EventKind.SESSION_ENDED,
                game=Game.AC,
                t_recv_ns=t,
                session_time_s=s.clock_s,
                payload={"source": "derived", "reason": reason},
            )
        )
        self.stats.count(f"session_end_{reason}")
        self._s = None

    # ------------------------------------------------------------------ RTCarInfo
    def _structure_warnings(self, p: dict[str, Any]) -> bool:
        warn = False
        if p["identifier"] != P.RT_CAR_INFO_IDENTIFIER:
            self.stats.count("identifier_unexpected")
            warn = True
        if p["size"] != P.RT_CAR_INFO.size:
            self.stats.count("size_field_unexpected")
            warn = True
        if any(b not in (0, 1) for b in (p["isAbsEnabled"], p["isAbsInAction"], p["isTcInAction"], p["isTcEnabled"])):
            self.stats.count("flag_byte_not_bool")
            warn = True
        if p["isInPit"] not in (0, 1) or p["isEngineLimiterOn"] not in (0, 1):
            self.stats.count("pit_limiter_byte_not_bool")
            warn = True
        if p["pad_26_27"] != b"\x00\x00":
            self.stats.count("pad_26_27_nonzero")  # evidence for the 26/27 reading (or uninitialised padding)
        return warn

    def _on_car_info(self, p: dict[str, Any], t: int, out: list[Emitted]) -> bool:
        lap_raw = int(p["lapCount"])
        lap_ms = int(p["lapTime"])
        last_ms = int(p["lastLap"])
        s = self._s
        if s is not None and s.prev is not None and lap_raw < s.prev.lap_raw:
            self._end_session(s, t, out, "lap_counter_reset")  # restart / back to the pits with a counter reset
            s = None
        if s is None:
            s = self._begin_session(p, t, out)
        warn = self._structure_warnings(p)
        clock_restarted = self._check_clock_restart(s, lap_raw, lap_ms, t)
        if s.hold is not None:
            self._service_hold(s, last_ms, t, out)

        prev = s.prev
        norm = _finite(p["carPositionNormalized"])
        if norm is not None and not -NORM_TOLERANCE <= norm <= 1.0 + NORM_TOLERANCE:
            self.stats.count("norm_out_of_range")
            norm = None
        coords = tuple(_finite(c) for c in p["carCoordinates"])
        pos: tuple[float, float, float] | None = None
        if coords[0] is not None and coords[1] is not None and coords[2] is not None:
            pos = (coords[0], coords[1], coords[2])
        speed_ms = _finite(p["speed_Ms"])
        speed_ms = abs(speed_ms) if speed_ms is not None else None
        in_pit = _flag(p["isInPit"])

        # --- clock and continuity -----------------------------------------------------------------------------
        host_dt = max(0.0, (t - prev.t_ns) / 1e9) if prev is not None else None
        step_m = math.dist(pos, prev.pos) if prev is not None and pos is not None and prev.pos is not None else None
        frozen = prev is not None and step_m is not None and step_m < FROZEN_EPS_M and lap_ms == prev.lap_ms
        if prev is not None and host_dt is not None and not frozen:
            s.clock_s += min(host_dt, LEAVE_PAUSE_DT_S) if prev.frozen else host_dt
        teleport = False
        if prev is not None and host_dt is not None and step_m is not None and host_dt <= TELEPORT_MAX_DT_S:
            v = max(speed_ms or 0.0, prev.speed_ms or 0.0)
            teleport = step_m > 1.5 * v * max(host_dt, 0.02) + TELEPORT_SLACK_M
            if teleport:
                self.stats.count("teleport")

        # --- lap transitions --------------------------------------------------------------------------------------
        crossed = False  # a lapCount increment that is a line crossing
        lap_reset = False
        if prev is None:
            s.lap = _Lap(anchored=False)
        elif lap_raw == prev.lap_raw + 1:
            gap_ms = 1000.0 * (host_dt or 0.0)
            restarted = lap_ms <= gap_ms + LAP_START_SLACK_MS
            # lapTime still running on from the lap before: the lap clock may lag the counter by a packet or two
            # (not seen on PS5, untested elsewhere). A restored state jumps the clock and/or teleports the car.
            lagging = (
                not teleport and prev.lap_ms - LAP_START_SLACK_MS <= lap_ms <= prev.lap_ms + gap_ms + LAP_START_SLACK_MS
            )
            if restarted or lagging:
                crossed = True
                if not restarted:
                    self.stats.count("increment_before_lap_clock")
                self._on_crossing(s, prev, last_ms, norm, step_m, host_dt, teleport, t, out, not restarted)
            else:
                self._on_increment_without_lap_start(s, prev, lap_ms, out)
        elif lap_raw > prev.lap_raw + 1:
            self.stats.count("laps_skipped")  # laps passed during a gap: no completion, origin unknown
            s.lap = _Lap(anchored=False)
            s.clock_restart_from_ns = None
        else:
            lap = s.lap
            lap_reset = lap_ms < prev.lap_ms - LAP_TIME_RESET_MS and not clock_restarted
            if lap_reset or teleport:
                if lap_reset:
                    self.stats.count("lap_time_reset")
                lap.compromised = lap.lost = True
                lap.learn = False
                s.rt_lap_early = None  # an RTLap from before the reset cannot time a later crossing
            elif host_dt is not None and host_dt > LEARN_MAX_GAP_S:
                lap.learn = False
            elif lap.learn:
                if step_m is None or in_pit is True:  # no position: the path comes out short; pit box: not a lap
                    lap.learn = False
                else:
                    lap.path_m += step_m

        # --- early track length -----------------------------------------------------------------------------------
        # only on laps that began with an observed crossing: the out-lap can start in the pit lane, which runs off
        # the spline (PS5 Silverstone: ~29 m off, path/spline 4 % short) without isInPit telling
        if (
            s.estimate is not None
            and prev is not None
            and (crossed or lap_raw == prev.lap_raw)
            and s.lap.anchored
            and not s.lap.compromised
            and not (lap_reset or teleport or frozen)
            and host_dt is not None
            and host_dt <= LEARN_MAX_GAP_S
            and step_m is not None
            and norm is not None
            and prev.norm is not None
            and in_pit is not True
            and prev.in_pit is not True
        ):
            dn = _forward_step(prev.norm, norm)
            if 0.0 < dn <= LINE_MAX_STEP:
                self._estimate_step(s, s.estimate, step_m, dn)

        # --- distance --------------------------------------------------------------------------------------------
        f = s.lap.f if crossed else self._fraction(s, norm)
        known = s.length_m is not None and s.line_confirmed
        dist_m = f * s.length_m if f is not None and s.length_m is not None and known and not s.lap.lost else None
        if dist_m is not None and s.length_estimated:
            s.lap.est_scaled = True  # void at its line unless its own full lap confirms the estimate

        # --- g_lon sign evidence ----------------------------------------------------------------------------------
        acc_frontal = _finite(p["accG_frontal"])
        if frozen or teleport or speed_ms is None or acc_frontal is None or (host_dt or 0.0) > LEARN_MAX_GAP_S:
            s.g_window = None
        else:
            self._g_evidence(s, speed_ms, acc_frontal)

        # --- slow-changing context --------------------------------------------------------------------------------
        self._update_snapshot(s, p)
        key = self._info_key(s)
        if key != s.info_key or s.last_info_ns is None or t - s.last_info_ns >= SESSION_INFO_INTERVAL_S * 1e9:
            out.append(self._session_info(s, t))

        frame = self._frame(s, p, t, dist_m, acc_frontal, frozen, warn)
        if s.hold is not None:
            s.hold.items.append(frame)
            if len(s.hold.items) >= LAST_LAP_HOLD_MAX_FRAMES:
                self.stats.count("last_lap_timeout")
                self._release_hold(s, None, out)
        else:
            out.append(frame)

        s.prev = _Prev(t, lap_raw, lap_ms, last_ms, norm, pos, speed_ms, frozen, in_pit)
        return True

    # ------------------------------------------------------------------ line crossings / completions
    def _on_increment_without_lap_start(self, s: _Session, prev: _Prev, lap_ms: int, out: list[Emitted]) -> None:
        """``lapCount`` + 1 while ``lapTime`` carries on: the game restored a lap state (PS5, after a counter reset),
        not a line crossing. Nothing is completed; the lap that starts here is unanchored and compromised."""
        self.stats.count("increment_without_lap_start")
        log.info(
            "AC: lapCount %d -> %d without the lap clock restarting (lapTime %d ms): restored state, no lap completed",
            prev.lap_raw,
            prev.lap_raw + 1,
            lap_ms,
        )
        if s.hold is not None:
            self._release_hold(s, None, out)
        s.rt_lap_early = None
        s.clock_restart_from_ns = None
        s.lap = _Lap(anchored=False, compromised=True)

    def _on_crossing(
        self,
        s: _Session,
        prev: _Prev,
        last_ms: int,
        norm: float | None,
        step_m: float | None,
        host_dt: float | None,
        teleport: bool,
        t: int,
        out: list[Emitted],
        await_clock: bool = False,
    ) -> None:
        """``lapCount`` + 1 at a line crossing. ``await_clock``: ``lapTime`` has not restarted yet; the completion is
        held until it does (``_check_clock_restart``) and released void and untimed if it never does."""
        old = s.lap
        s.clock_restart_from_ns = t if await_clock else None
        continuous = (
            host_dt is not None
            and host_dt <= CROSSING_MAX_GAP_S
            and not teleport
            and norm is not None
            and prev.norm is not None
            and _circ_dist(prev.norm, norm) <= LINE_MAX_STEP
        )
        # 1. where the timing line is on the spline (spline zero, or a candidate confirmed by a second increment)
        line_before = s.line_norm  # the line the lap that just ended was measured from (candidate or trusted)
        mismatch = False
        if continuous and norm is not None and prev.norm is not None:
            mismatch = self._observe_line(s, _circ_mid(prev.norm, norm), _circ_dist(prev.norm, norm))
        if mismatch:
            old.compromised = True  # this lap ends where the trusted line is not: time and trace do not match
        # 2. track length from the lap that just ended (a full lap seen from line to line): learned, or the length
        #    in use (an estimate or a stored value) checked - once per session, then it is fixed
        if (
            old.learn
            and continuous
            and not mismatch
            and not old.lost
            and s.line_confirmed
            and line_before is not None
            and old.f_start is not None
            and norm is not None
        ):
            path = old.path_m + (step_m or 0.0)
            g = (norm - line_before) % 1.0
            f_end = g + round((old.f if old.f is not None else 1.0) - g)
            frac = f_end - old.f_start
            measured = path / frac if abs(frac - 1.0) <= LEARN_FRACTION_TOL else None
            if measured is None or not MIN_TRACK_LENGTH_M <= measured <= MAX_TRACK_LENGTH_M:
                self.stats.count("length_learning_rejected")
            else:
                self._on_full_lap(s, old, measured)
        if old.est_scaled and not old.scale_confirmed:
            # its distances came from a partial-lap estimate that no full lap confirmed within EST_CONFIRM_TOL: the
            # next laps use another scale, so this one must never become a reference or track-model material
            self.stats.count("estimate_scaled_lap_void")
            old.compromised = True
        if self._info_key(s) != s.info_key:
            out.append(self._session_info(s, t))  # new geometry must precede the completion and the new lap
        # 3. the completion of pitwall lap ``prev.lap_raw + 1``
        comp = LapCompletion(
            game=Game.AC,
            t_recv_ns=t,
            lap_number=prev.lap_raw + 1,
            lap_time_ms=None,
            sector_times_ms=[],
            valid=False if old.compromised else None,  # AC sends no validity; False only for laps we know are broken
            session_time_s=s.clock_s,
        )
        fresh = last_ms > 0 and last_ms != prev.last_ms
        # An unchanged lastLap is either a lap timed to the same millisecond as the previous one, or a field that
        # lags the counter. The lap's true time lies between its own clock in the previous packet and that clock
        # plus one packet interval, so only a value inside that window is accepted (a stale value is then wrong
        # by less than one packet interval); otherwise the completion is held until lastLap changes.
        window_ms = max(1000.0 * (host_dt or 0.0), LAST_LAP_MATCH_MIN_WINDOW_MS) + LAST_LAP_MATCH_SLACK_MS
        equal_time = last_ms > 0 and last_ms == prev.last_ms and -2.0 <= last_ms - prev.lap_ms <= window_ms
        early, s.rt_lap_early = s.rt_lap_early, None
        rt_ms: int | None = None
        if early is not None and early[0] == comp.lap_number:
            if t - early[2] <= RT_LAP_EARLY_MAX_S * 1e9:
                rt_ms = early[1]
            else:
                self.stats.count("rt_lap_early_expired")
        if s.hold is not None:  # two increments inside one hold window: release the first without a time
            self._release_hold(s, None, out)
        if comp.lap_number in s.completed:
            self.stats.count("completion_duplicate")  # never complete a lap twice
        else:
            # the game's own lastLap from the crossing packet first; an RTLap that came just before the increment
            # only when lastLap is stale; an unchanged lastLap only when the lap's own clock agrees with it
            time_ms: int | None = None
            if fresh:
                time_ms = last_ms
                if rt_ms is not None:
                    self.stats.count("rt_lap_confirmed" if rt_ms == last_ms else "rt_lap_time_mismatch")
            elif rt_ms is not None:
                time_ms = rt_ms
                self.stats.count("rt_lap_timed")
            elif equal_time:
                time_ms = last_ms
            if time_ms is not None and not await_clock:
                comp.lap_time_ms = time_ms
                self._emit_completion(s, comp, out)
            else:
                s.hold = _Hold(
                    comp,
                    stale_last_ms=last_ms,
                    deadline_ns=t + int(LAST_LAP_HOLD_S * 1e9),
                    time_ms=time_ms,
                    await_clock=await_clock,
                )
        # 4. the new lap
        new = _Lap(anchored=continuous)
        if s.line_norm is not None and norm is not None:
            g = (norm - s.line_norm) % 1.0
            new.f = (g if g < 0.5 else g - 1.0) if continuous else g
        new.f_start = new.f
        # measure the lap: to learn the length, or to check the one in use (once per session)
        new.learn = continuous and new.f is not None and not s.length_verified
        s.lap = new

    def _observe_line(self, s: _Session, mid: float, step: float) -> bool:
        """One ``lapCount`` increment seen at spline position ``mid`` (packets ``step`` apart).

        Returns True when the increment contradicts a trusted (spline zero, confirmed or stored) line.
        """
        zero = _circ_dist(mid, 0.0) <= ZERO_LINE_TOL
        if not s.line_confirmed and zero:
            # the spline wrapped at the increment: AC's spline origin is the timing line on this track
            s.line_norm, s.line_step, s.line_confirmed, s.line_source = 0.0, 2.0 * ZERO_LINE_TOL, True, "spline_zero"
            s.line_rival = None
            self.stats.count("line_spline_zero")
            log.info("AC start/finish line at spline 0 (increment at spline position %.5f)", mid)
            if s.length_m is not None:
                self._remember_geometry(s)
            return False
        if s.line_norm is None:
            s.line_norm, s.line_step, s.line_confirmed = mid, step, False
            self.stats.count("line_candidate")
            log.info("AC start/finish line candidate at spline position %.5f", mid)
            return False
        tol = 0.5 * (s.line_step + step) + LINE_CONFIRM_SLACK
        agrees = _circ_dist(s.line_norm, mid) <= tol
        if s.line_confirmed:
            if agrees:
                s.line_rival = None
                return False
            self.stats.count("line_mismatch")
            rival = s.line_rival
            if rival is None or _circ_dist(rival, mid) > 0.5 * (s.line_rival_step + step) + LINE_CONFIRM_SLACK:
                s.line_rival, s.line_rival_step = mid, step  # a one-off (race start? pit exit?) until another agrees
                return True
            # two consecutive increments agree with each other and not with the trusted line: it is wrong here
            self.stats.count("line_rejected")
            log.warning(
                "AC: trusted start/finish line %.5f contradicted by two crossings (%.5f, %.5f): line moved, track "
                "length re-estimated",
                s.line_norm,
                rival,
                mid,
            )
            s.line_norm, s.line_step, s.line_rival, s.line_source = _circ_mid(rival, mid), step, None, "crossings"
            # measured against a wrong line / possibly another layout: forget the length and estimate it again
            s.length_m = s.length_source = s.length_estimate_fraction = s.length_full_lap_m = None
            s.length_verified = s.length_estimated = False
            s.estimate = _Estimate()
            s.geometry_rejected = True
            ident = s.identity
            if ident is not None and ident.track_id is not None:
                self._geometry.pop(ident.track_id, None)  # _remember_geometry stores the relearned entry
            return True
        if agrees:
            s.line_norm, s.line_confirmed, s.line_source = _circ_mid(s.line_norm, mid), True, "crossings"
            self.stats.count("line_learned")
            log.info("AC start/finish line confirmed at spline position %.5f", s.line_norm)
            if s.length_m is not None:  # length was known (earlier session / estimate) without the line: store both
                self._remember_geometry(s)
        else:  # the first increment was not at the line (race start? pit exit?): start again from this one
            s.line_norm, s.line_step = mid, step
            self.stats.count("line_candidate_moved")
            log.info("AC start/finish line candidate moved to spline position %.5f", mid)
        return False

    # ------------------------------------------------------------------ track length
    def _estimate_step(self, s: _Session, e: _Estimate, step_m: float, dn: float) -> None:
        """One clean step for the early length estimate; publish once it has converged."""
        e.path_m += step_m
        e.progress += dn
        if e.progress < e.next_mark:
            return
        est = e.path_m / e.progress
        while e.next_mark <= e.progress:  # checkpoints on a fixed 1 % grid of progress
            e.next_mark += EST_MARK_STEP
        e.marks.append((e.progress, est))
        lo = e.progress - EST_STABLE_WINDOW
        while e.marks and e.marks[0][0] < lo:
            e.marks.pop(0)
        if e.progress < EST_MIN_PROGRESS:
            return
        values = [v for _, v in e.marks]
        if (max(values) - min(values)) / est > EST_STABLE_REL:  # not yet inside a 0.5 % band over the window
            return
        if not MIN_TRACK_LENGTH_M <= est <= MAX_TRACK_LENGTH_M:
            self.stats.count("length_estimate_implausible")
            s.estimate = _Estimate()  # start again rather than publish a value no track can have
            return
        s.length_m = round(est, 1)
        s.length_source, s.length_estimated = LENGTH_ESTIMATE, True
        s.length_estimate_fraction = round(e.progress, 3)
        s.estimate = None
        self.stats.count("length_estimated")
        ident = s.identity
        log.info(
            "AC track length estimated: %.1f m after %.1f %% of a lap (%s)",
            s.length_m,
            100.0 * e.progress,
            ident.track_id if ident else "?",
        )
        self._remember_geometry(s)

    def _on_full_lap(self, s: _Session, lap: _Lap, measured: float) -> None:
        """One full lap measured from line to line (driven path / spline fraction): learn the length, or check the
        one in use. Called once per session: afterwards the length is fixed (``length_verified``), so every lap of
        the session - and of later sessions that start from the stored value - is scaled identically. It changes
        again only through a line rejection, which voids the laps involved."""
        s.length_full_lap_m = round(measured, 1)
        cur = s.length_m
        if cur is None:
            self.stats.count("length_learned")
            self._use_full_lap(s, measured)
            return
        rel = abs(measured / cur - 1.0)
        ident = s.identity
        track = ident.track_id if ident else "?"
        if not s.length_estimated:  # a full-lap length stored by an earlier session: kept unless another layout
            if rel <= KNOWN_LENGTH_TOLERANCE:
                s.length_verified = True
                self.stats.count("known_length_confirmed")
                return
            self.stats.count("length_rejected")
            log.warning(
                "AC: stored track length %.1f m contradicted by a measured lap of %.1f m (%s): using the measurement",
                cur,
                measured,
                track,
            )
            lap.compromised = True  # its distances were scaled by the wrong length
            s.geometry_rejected = True
            self._use_full_lap(s, measured)
            return
        # a partial-lap estimate (this session's or a stored one)
        if rel <= EST_CONFIRM_TOL:
            # kept as it is, so the lap it scaled and every later lap share one scale
            lap.scale_confirmed = True
            s.length_estimated, s.length_verified = False, True
            if s.length_source == LENGTH_ESTIMATE:
                s.length_source = LENGTH_ESTIMATE_CONFIRMED
            self.stats.count("length_estimate_confirmed")
            log.info("AC track length estimate %.1f m confirmed by a full lap of %.1f m (%s)", cur, measured, track)
            self._remember_geometry(s)
            return
        if rel > KNOWN_LENGTH_TOLERANCE:
            if s.length_source == LENGTH_KNOWN:  # a stored estimate of another layout / a stale track name
                self.stats.count("length_rejected")
                s.geometry_rejected = True
            else:
                self.stats.count("length_estimate_off")
        else:
            self.stats.count("length_estimate_replaced")
        log.warning(
            "AC: track length estimate %.1f m was %.2f %% off a measured full lap", cur, 100.0 * (measured / cur - 1.0)
        )
        self._use_full_lap(s, measured)  # the lap scaled by the estimate is void (``_on_crossing``)

    def _use_full_lap(self, s: _Session, measured: float) -> None:
        s.length_m = round(measured, 1)
        s.length_source, s.length_estimated, s.length_estimate_fraction = LENGTH_FULL_LAPS, False, None
        s.length_verified = True
        s.estimate = None
        ident = s.identity
        log.info("AC track length %.1f m from a full lap (%s)", s.length_m, ident.track_id if ident else "?")
        self._remember_geometry(s)

    def _remember_geometry(self, s: _Session) -> None:
        """Keep this track's geometry for later sessions of this adapter (never for synthetic streams)."""
        ident = s.identity
        if ident is None or ident.track_id is None or ident.synthetic or s.length_m is None:
            return
        try:
            line = s.line_norm if s.line_confirmed else None
            self._geometry[ident.track_id] = AcTrackGeometry(s.length_m, line, s.length_estimated)
        except ValueError:
            self.stats.count("geometry_not_stored")

    # ------------------------------------------------------------------ held completions
    def _emit_completion(self, s: _Session, comp: LapCompletion, out: list[Emitted]) -> None:
        s.completed[comp.lap_number] = comp.lap_time_ms
        out.append(comp)

    def _service_hold(self, s: _Session, last_ms: int, t: int, out: list[Emitted]) -> None:
        hold = s.hold
        assert hold is not None
        if hold.time_ms is None and last_ms != hold.stale_last_ms and last_ms > 0:
            self.stats.count("last_lap_late")
            hold.time_ms = last_ms
        if hold.time_ms is not None and not hold.await_clock:
            self._release_hold(s, hold.time_ms, out)
        elif t >= hold.deadline_ns:
            if hold.await_clock:  # lapTime never restarted: whatever this increment was, no lap is timed by it
                hold.completion.valid = False
                self._release_hold(s, None, out)
            else:
                self.stats.count("last_lap_timeout")
                self._release_hold(s, None, out)

    def _check_clock_restart(self, s: _Session, lap_raw: int, lap_ms: int, t: int) -> bool:
        """After an increment that came before ``lapTime`` restarted: True when this packet is that restart (not a lap
        reset). If it does not come within ``LAST_LAP_HOLD_S`` the lap that began there is void."""
        since, prev = s.clock_restart_from_ns, s.prev
        if since is None or prev is None or lap_raw != prev.lap_raw:
            return False
        if lap_ms < prev.lap_ms - LAP_TIME_RESET_MS and lap_ms <= (t - since) / 1e6 + LAP_START_SLACK_MS:
            s.clock_restart_from_ns = None
            self.stats.count("lap_clock_restarted_late")
            if s.hold is not None:
                s.hold.await_clock = False  # a crossing after all: released with its time by ``_service_hold``
            return True
        if t - since > LAST_LAP_HOLD_S * 1e9:
            s.clock_restart_from_ns = None
            s.lap.compromised = True  # its clock carried on from the lap before: time and trace do not match
            self.stats.count("lap_clock_not_restarted")
        return False

    def _release_hold(self, s: _Session, lap_time_ms: int | None, out: list[Emitted]) -> None:
        hold = s.hold
        assert hold is not None
        s.hold = None
        hold.completion.lap_time_ms = lap_time_ms
        self._emit_completion(s, hold.completion, out)
        out.extend(hold.items)

    # ------------------------------------------------------------------ distance
    def _fraction(self, s: _Session, norm: float | None) -> float | None:
        """Unwrapped spline fraction since the line for a packet inside the current lap (None = unknown)."""
        lap = s.lap
        if lap.lost or s.line_norm is None or norm is None:
            return None
        g = (norm - s.line_norm) % 1.0
        if lap.f is None:
            # geometry (or a valid spline position) became available mid-lap: a true position, but not anchored
            lap.anchored = False
            lap.learn = False
            lap.f = g
            return g
        k = round(lap.f - g)
        if not lap.anchored and k != 0:
            self.stats.count("unanchored_line_wrap")  # crossed the line without an increment: lap count unknown
            lap.lost = True
            return None
        f_new = g + k
        lo, hi = ANCHORED_FRACTION_RANGE
        if not lo <= f_new <= hi:
            self.stats.count("fraction_out_of_range")
            lap.lost = True
            return None
        lap.f = f_new
        return f_new

    # ------------------------------------------------------------------ g_lon sign
    def _g_evidence(self, s: _Session, speed_ms: float, acc_frontal: float) -> None:
        w = s.g_window
        if w is None:
            s.g_window = [s.clock_s, speed_ms, 0.0, 0.0]
            return
        w[2] += acc_frontal
        w[3] += 1.0
        dt = s.clock_s - w[0]
        if dt < G_SIGN_WINDOW_S:
            return
        measured = (speed_ms - w[1]) / dt / STANDARD_GRAVITY
        reported = w[2] / w[3]
        if abs(measured) >= G_SIGN_MIN_MEASURED_G and abs(reported) >= G_SIGN_MIN_REPORTED_G:
            if (measured > 0) == (reported > 0):
                self._g_agree += 1
            else:
                self._g_disagree += 1
        s.g_window = [s.clock_s, speed_ms, 0.0, 0.0]

    # ------------------------------------------------------------------ normalisation
    def _frame(
        self,
        s: _Session,
        p: dict[str, Any],
        t: int,
        dist_m: float | None,
        acc_frontal: float | None,
        frozen: bool,
        warn: bool,
    ) -> CarFrame:
        q = FrameQuality.OK
        if frozen:
            q |= FrameQuality.PAUSED
        if warn:
            q |= FrameQuality.DECODE_WARNING
        lap_raw = int(p["lapCount"])
        lap_ms = int(p["lapTime"])
        last_ms = int(p["lastLap"])
        speed = _finite(p["speed_Kmh"])
        rpm = _finite(p["engineRPM"])
        x, y, z = (_finite(c) for c in p["carCoordinates"])
        in_pit = _flag(p["isInPit"])
        sign = self.g_lon_sign
        return CarFrame(
            game=Game.AC,
            t_recv_ns=t,
            session_time_s=s.clock_s,
            quality=q,
            throttle=_unit(p["gas"]),
            brake=_unit(p["brake"]),
            steering=None,  # steer @72: unit undocumented (see AC_INFO)
            clutch=_unit(p["clutch"]),
            speed_kph=abs(speed) if speed is not None else None,
            gear=_gear(int(p["gear"])),
            rpm=rpm if rpm is not None and rpm >= 0.0 else None,
            pos_x_m=x,
            pos_y_m=y,
            pos_z_m=z,
            g_lat=_finite(p["accG_horizontal"]),
            g_lon=acc_frontal * sign if acc_frontal is not None and sign is not None else None,
            g_vert=_finite(p["accG_vertical"]),
            lap_number=lap_raw + 1 if lap_raw >= 0 else None,
            lap_distance_m=dist_m,
            current_lap_time_ms=lap_ms if lap_ms >= 0 else None,
            last_lap_time_ms=last_ms if last_ms > 0 else None,
            # isInPit = 1 only in the pit box; 0 also while driving the pit lane (PS5), so 0 is not "on track"
            pit_status=2 if in_pit is True else None,
            abs_active=_flag(p["isAbsInAction"]),
        )

    # ------------------------------------------------------------------ session info
    def _update_snapshot(self, s: _Session, p: dict[str, Any]) -> None:
        best = int(p["bestLap"])
        steer = _finite(p["steer"])
        if steer is not None:
            s.steer_min = steer if s.steer_min is None else min(s.steer_min, steer)
            s.steer_max = steer if s.steer_max is None else max(s.steer_max, steer)
        s.snapshot = {
            "best_lap_ms": best if best > 0 else None,
            "abs": _flag(p["isAbsEnabled"]),
            "tc": _flag(p["isTcEnabled"]),
            "size_field": int(p["size"]),
        }

    def _info_key(self, s: _Session) -> tuple[Any, ...]:
        ident = s.identity
        return (
            s.uid,
            ident.key if ident else None,
            s.length_m,
            s.length_estimated,
            s.length_source,
            s.line_norm,
            s.line_confirmed,
            s.geometry_rejected,
            s.snapshot.get("abs"),
            s.snapshot.get("tc"),
            s.snapshot.get("best_lap_ms"),
        )

    @staticmethod
    def _distance_status(s: _Session) -> str:
        if s.length_m is not None and s.line_norm is not None and s.line_confirmed:
            return "ok"
        if s.line_norm is None:
            return "waiting for the first start/finish crossing (line position on the spline unknown)"
        if not s.line_confirmed:
            return "confirming the start/finish line position (needs a second crossing)"
        return "estimating the track length (needs about 15-25 % of a lap of clean driving from the line)"

    def _session_info(self, s: _Session, t: int) -> SessionInfo:
        s.info_key = self._info_key(s)
        s.last_info_ns = t
        ident = s.identity
        assists: dict[str, Any] = {k: s.snapshot[k] for k in ("abs", "tc") if s.snapshot.get(k) is not None}
        # "estimate" (partial lap, unconfirmed) | "full_lap" (measured on, or confirmed by, a full lap; or stored so)
        quality = None if s.length_m is None else ("estimate" if s.length_estimated else "full_lap")
        extra: dict[str, Any] = {
            "best_lap_ms": s.snapshot.get("best_lap_ms"),
            "ac_line_norm": s.line_norm if s.line_confirmed else None,  # only a trusted line is reused later
            "ac_line_source": s.line_source if s.line_confirmed else None,
            "track_length_source": s.length_source,
            "track_length_quality": quality,  # "estimate" (partial lap) | "full_lap"; stored and reused
            "track_length_estimate_fraction": s.length_estimate_fraction,
            "track_length_full_lap_m": s.length_full_lap_m,  # this session's full-lap measurement (once)
            "ac_geometry_rejected": s.geometry_rejected,  # stored geometry contradicted: older sessions stop seeding
            "lap_distance_status": self._distance_status(s),
            "rtcarinfo_size_field": s.snapshot.get("size_field"),
            "steer_raw_range": None if s.steer_min is None else [s.steer_min, s.steer_max],
            "g_lon_sign": self.g_lon_sign,
        }
        if ident is not None:
            extra["track_config"] = ident.config
            extra["handshake_encoding"] = "utf-16le" if ident.wide else "8-bit"
            extra["handshake_status"] = ident.status
            extra["protocol_version"] = ident.version
            if ident.synthetic:
                extra["synthetic"] = True
        else:
            extra["identity"] = "unknown: no handshake reply seen before the stream"
        return SessionInfo(
            game=Game.AC,
            t_recv_ns=t,
            platform=self.platform,
            session_uid=s.uid,
            track_id=ident.track_id if ident else None,
            track_name=ident.track_label if ident else None,
            track_length_m=s.length_m,
            session_type=SessionType.UNKNOWN,
            car_id=ident.car_id if ident else None,
            car_name=ident.car if ident else None,
            assists=assists,
            extra=extra,
        )
