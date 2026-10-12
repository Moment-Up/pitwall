"""Gran Turismo 7 adapter: decrypts, validates and normalises Simulator Interface packets.

Source: docs/research/gt7-protocol.md (community reverse-engineering, no official spec). Fields the owner's real PS5
captures settled (2026-10-11, ``tests/recorded/test_gt7_ps5_real.py``) are ``RECORDED_VALIDATED``, field by field;
everything else stays at most ``COMMUNITY_DOCUMENTED`` until a real capture or live session validates it.

GT7 sends one self-contained packet per simulation tick (~60 Hz), so unlike F1 there is nothing to merge:
every packet of a session becomes one ``CarFrame``. What GT7 does *not* send is reconstructed here,
deterministically and with documented provenance (``AdapterInfo.fields`` marks each as derived):

* **Tick clock** (``session_time_s``): packet-id deltas x 1/60 s, advanced only while the simulation runs (not
  while paused), so a pause never looks like packet loss to the lap assembler. Lost packets show up as a time
  gap, exactly as with a real game clock. A packet whose speed, position or velocity is not finite is dropped
  and bridged exactly like a lost packet (one bad value must not poison a lap's distance or the track id).
  Real PS5 captures: game lap time = non-paused ticks / 60 within 10 ms on every flying lap.
* **Lap distance** (``lap_distance_m``): trapezoidal integration of the velocity magnitude (0x10..0x18) over tick
  time, reset to 0 at each start/finish crossing. Not the speed field 0x4C: on the real captures 0x4C is the size
  of the velocity's component along the car's longitudinal axis (|velocity . body -Z|, 0x1C..0x2B read as a
  quaternion; within 3.3 mm/s on all 59,242 advancing on-track packets above 1 m/s), so it equals the velocity
  magnitude while the tyres grip and falls towards 0 when the car slides sideways. Integrating it fell 0.09-1.52 %
  short of the position path on the 11 timed laps (the most on the 3 laps with a car reset), the velocity
  magnitude 0.08-0.18 % (reset jumps excluded). A packet that does not advance (``_signature`` equal to the
  previous one's) and is not paused is never integrated (see Session boundaries). The distance is emitted only while
  *anchored* - i.e. after a line crossing was observed while moving with continuous packets.
  Joining mid-lap, a standing start (the grid offset to the line is unknown), a teleport (car reset to track) or a
  stream gap of more than 5 s leave the distance ``None`` until the next crossing: unknown stays unknown.
  Leaving the out-lap (lap 0 -> 1 while moving) or a rolling race start on a track whose line is not yet known
  anchors *provisionally*; the next crossing reveals the line, and a lap that did not start on it is completed
  with ``valid=False`` so its misaligned trace can never become a reference or train a track model (on the real
  captures every rolling start incremented the counter within 1 m of the line). Likewise a lap that *loses* its
  anchor part-way (gap, teleport, car reset) is completed with ``valid=False``: its trace stops at the
  discontinuity, and before the track length is known nothing downstream could tell it from a complete lap.
  A counter increment away from the learned line does not anchor the next lap either.
* **Race lap 1** (``LapCompletion.race_start``): in a lap race (``total_laps`` > 0) the game's lap-1 time starts
  at the start signal, 150-383 ms before the line on the real rolling starts, so lap 1 is timed and stored but
  flagged as a race-start lap: never comparable with a flying lap. (Timed races send no lap total: their lap 1
  cannot be told from a flying lap.)
* **Current lap time** for variants A/B/~: ticks since the anchor (variant C reports the game's own timer).
* **Lap completion**: the lap counter incrementing from >= 1 (doc section 9), timed by ``last_lap_ms``. If
  ``last_lap_ms`` has not updated in the same packet, frames are held for up to ``LAST_LAP_HOLD_TICKS`` so the
  completion still precedes the next lap's frames (``LapAssembler`` needs that order). A ``last_lap_ms`` update
  *without* a counter increment that matches the derived lap time completes the current lap (a final race lap
  that does not advance the counter - the F1 25 lesson - or a timer leading the counter by a tick); frames are
  then ``NOT_RACING`` until the counter changes. Lap counters and times are read only while the car is on track
  (CarOnTrack): in menus GT7 sends -1, in replays and the menus' background laps it runs its own counter.
* **Track identity**: GT7 has no track id; see ``TrackSignature``. Every anchored lap is measured (length and
  total turning). A lap matching a known signature (the registry: ``known_track_ids`` from the database plus
  tracks learned by this process) identifies the track - a lap with small, bridged packet gaps is good enough
  for that. A *new* track is learned only from two gap-free laps that agree closely, so one odd lap (a spin, an
  excursion, a pit lane) can never define a track. The published ``track_length_m`` is never longer than the
  registry length or this session's own measurements: it starts as the shorter of the identifying lap(s) and the
  registry length, and every later gap-free lap that matches the track and measures shorter lowers it (a race lap 1
  on a wider line may identify the track; the next flying lap then sets the length). ``LapAssembler`` calls a lap
  incomplete when it ends short of that length, so an over-estimate would disqualify every lap on the circuit.
  Synthetic sessions never add to the registry. Track *names* are unknown (``track_name`` is a descriptive label).
* **Session boundaries**: GT7 has no session uid, and it streams at 60 Hz in menus, replays, the menus'
  background laps and, after the player leaves a race, as one frozen packet repeated with only the packet id
  changing. On the owner's PS5 the earlier rule (a new session after every load, retry or car reset) turned 4
  races into 28 stored sessions, most of them menus and replays. So a session *opens* only after ``OPEN_TICKS``
  consecutive packets that are live: CarOnTrack set, not loading, not paused, and advancing (the payload differs
  from the previous packet's apart from the packet id, the nonce seed and the paused bit). Nothing is emitted
  outside a session. An open session keeps paused packets and *ends* (``GameEvent`` ``session_ended`` with the
  reason in ``code``, after any held completion) on: a loading run that is not a car reset; a car change; a
  packet-id restart; the lap counter going back or the time of day rewinding 10 s or more while on track (doc
  section 9's retry detector); ``STALL_END_TICKS`` of a frozen payload (not advancing, not paused) with the
  velocity magnitude at or above ``FROZEN_MIN_SPEED_MPS`` (the simulation stopped: a running one moves the car, and
  the position is part of the payload; the velocity, not 0x4C, which reads near 0 while the car slides sideways in a
  spin); or ``OFF_TRACK_END_TICKS`` without CarOnTrack (results, replays, menus). Frozen packets are dropped: no
  frame, no clock, no distance - the next packet that advances integrates one tick, as after a pause. Below
  ``FROZEN_MIN_SPEED_MPS`` a repeated payload cannot be told from a car standing still in a running simulation (never
  seen on the real captures): its frames are emitted and the session stays, but it is never integrated either.
  A **car reset** (the game puts the car back on track after an off) is a loading run of at most
  ``RESET_MAX_LOADING_TICKS`` with the car on track on both sides, the same car, lap count and lap total and, on
  variant C, the lap timer continuing (0 <= delta < 1 s): the session continues and the reset is a teleport (the
  lap keeps the game's time, its trace stops at the reset). A session's uid is ``gt7:<t_recv_ns of the packet
  that opened it>``, deterministic on replay, so a re-driven lap 1 never overwrites the earlier lap 1 of the same
  database session. (Synthetic streams all carry the generator's fixed uid, which the session manager uses to
  flag them, so retries inside one synthetic stream stay in one stored session.)
* **Fuel**: the unit of 0x44/0x48 is conflicting in the doc (litres per PDTools, percent per GT7Eng; the
  capacity is 100 for most cars), so ``fuel_litres`` stays ``None``; the unitless level / capacity goes out as
  ``SessionInfo.extra['fuel_fraction']``. (The real captures showed 100 / 100 throughout: no fuel was used.)

Inputs: the throttle is the driver's pedal - 0x13C on variants ~ and C (on the real captures 0x91 was below it on
every TCS-active packet and above it only during downshift blips: 0x91 is the throttle after TCS), 0x91 on A and B,
which have nothing else. Gears 1..14 are forward gears; 0 and 15 are ``None``: Kaitai reads them as reverse and
neutral, but the real captures never had R or N selected - gear 0 appeared only in spins, with the pedal released
and the clutch out (no gear engaged fits it as well as reverse), and 15 never (doc section 11, question 3).

Steering (B/~/C): the wheel angle at 0x128 is in radians, left positive (the real captures: the sign agreed with
the variant C road-wheel angles at 0x160/0x164 on every packet). It is normalised to -1..+1 by a nominal +/-450 deg
half-lock; on the real captures 0x128 is clamped at +/-pi, so the normalised value never exceeds +/-0.4 (the
magnitude stays approximate). On variant C the sign is still cross-checked against the road-wheel angles and
flipped if they consistently disagree.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from pitwall.adapters.base import AdapterInfo, DecodeStats, FieldSupport, PacketRejected, SupportLevel
from pitwall.adapters.gt7 import packets as P
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
    Wheels,
)

log = logging.getLogger(__name__)

TICK_S = 1.0 / 60.0  # one packet per simulation tick at ~60 Hz (doc section 1); gt7dashboard uses 16.668 ms
MAX_GAP_TICKS = 300  # > 5 s without packets: discontinuity (console sleep, Wi-Fi drop) - distance unanchored
DUPLICATE_WINDOW_TICKS = 120  # an id up to 2 s behind the last one is a duplicate / out-of-order packet...
DUPLICATE_RUN_RESTART = 30  # ...unless 30 arrive in a row: then the stream restarted just below the last id
LENGTH_GAP_TICKS = 6  # a lap with a gap above 0.1 s may be timed and identified, but never teaches a new track
IDENTIFY_GAP_TICKS = 30  # ...and with a gap above 0.5 s its bridged distance cannot identify a known one either
CROSSING_GAP_TICKS = 3  # a lap change seen after a longer gap gives no usable start/finish position
ANCHOR_MIN_SPEED_MPS = 5.0  # a lap change while slower than this is a standing start, not a line crossing
TELEPORT_SLACK_M = 20.0  # displacement beyond 1.5 x speed x dt + this = car reset to track (teleport)
LAST_LAP_HOLD_TICKS = 12  # max frames held (200 ms) waiting for last_lap_ms after a counter increment
LAST_LAP_MATCH_TOL_S = 1.0  # last_lap_ms vs derived lap time, for completions without a counter increment
LAST_LAP_MATCH_TOL_FRAC = 0.02
SAME_LAP_TIME_TOL_S = 0.05  # an unchanged last_ms is accepted only if the derived lap time agrees this well
SESSION_INFO_EVERY = 30  # packets between periodic SessionInfo emissions (~2 Hz, like F1's Session packet)
STEER_HALF_LOCK_RAD = math.radians(450.0)  # nominal: 900 deg lock-to-lock (wheel input; magnitude approximate)
STEER_CHECK_MIN_SAMPLES = 120  # variant C sign cross-check: samples before a flip is allowed
RETRY_TOD_REWIND_MS = 10_000  # time of day going back this much = a retry (GT7Eng, doc section 9)
TOD_WRAP_MS = 12 * 3_600_000  # ...unless it went back by more than half a day: that is the clock passing midnight
DAY_MS = 24 * 3_600_000  # time-of-day values outside (0, DAY_MS) are treated as unset, never as a rewind
# Session boundaries (module docstring). Measured on the owner's PS5 captures (2026-10-11): transition blips between
# menus and replays last <= 0.1 s, a car reset is a 1-packet loading pulse, a frozen post-race stream lasts minutes.
OPEN_TICKS = 30  # 0.5 s of live packets (on track, not loading or paused, advancing) open a session
STALL_END_TICKS = 120  # 2 s of a frozen payload at speed (not paused): the simulation stopped, the session ends
# "At speed" is the velocity magnitude, never 0x4C (which reads near 0 while the car slides sideways): a running
# simulation moves a car this fast >= 8 mm per tick, far above the float32 resolution of the position in the payload.
FROZEN_MIN_SPEED_MPS = 0.5
OFF_TRACK_END_TICKS = 120  # 2 s without CarOnTrack (results, replay, menus): the session ends
RESET_MAX_LOADING_TICKS = 30  # a loading run this short, car on track on both sides, may be a car reset...
RESET_TIMER_MAX_MS = 1_000  # ...if the variant C lap timer continued across it (0 <= delta < 1 s)

# Track identity (see TrackSignature). The length tolerance must not exceed LapAssembler's end-of-lap tolerance
# for derived-distance games (analysis.laps: max(EDGE_TOLERANCE_M, DERIVED_EDGE_FRAC x length)); the tests tie
# the constants together so that neither side can change alone.
SF_MATCH_RADIUS_M = 40.0
SF_MATCH_HEADING_DEG = 45.0
SF_MATCH_LENGTH_FRAC = 0.015
SF_MATCH_LENGTH_MIN_M = 60.0
TURN_SAMPLE_M = 10.0  # heading sampled every 10 m of lap distance
TURN_DEADBAND_DEG = 0.5  # per sample: steering corrections / weaving on straights are not turning
TURN_MATCH_MIN_DEG = 40.0  # a chicane adds ~100 deg or more; weaving and line choice stay well below 40
TURN_MATCH_FRAC = 0.05
LEARN_AGREE_FRAC = 0.005  # two laps teach a new track only if their lengths agree within 0.5 % (10 m minimum)
LEARN_AGREE_MIN_M = 10.0
LEARN_MAX_CANDIDATES = 6  # measured laps remembered per session while waiting for a second agreeing one
MIN_TRACK_LENGTH_M = 200.0  # a measured "lap" outside these bounds is a glitch, not a circuit
MAX_TRACK_LENGTH_M = 50_000.0

_C = SupportLevel.COMMUNITY_DOCUMENTED
_R = SupportLevel.RECORDED_VALIDATED
_U = SupportLevel.UNSUPPORTED
# Evidence for every _R field: the owner's PS5 on 2026-10-11 (4 captures, 277,467 variant C packets, 3 cars, 2
# circuits), pinned by tests/recorded/test_gt7_ps5_real.py. Recorded, not live: nobody compared the dashboard with the
# game's HUD; the live run of that day is the platform's evidence.
_PS5 = "PS5 recordings 2026-10-11"
_DERIVED = "derived: velocity magnitude x tick time"

GT7_INFO = AdapterInfo(
    game=Game.GT7,
    name="Gran Turismo 7 (Simulator Interface, variants A/B/~/C)",
    transport="udp (encrypted, Salsa20; heartbeat to console UDP 33739)",
    default_port=P.RECEIVE_PORT,
    ground_plane=("pos_x_m", "pos_z_m"),  # Y is up (doc section 4)
    platforms={Platform.PS5: SupportLevel.LIVE_VALIDATED, Platform.PS4: _C},
    fields={
        "speed_kph": FieldSupport(
            _R,
            f"0x4C speed (m/s, abs) x 3.6. {_PS5}: 0..59.9 m/s; |velocity . body forward| (within 3.3 mm/s on all "
            "59,242 advancing on-track packets above 1 m/s): the velocity magnitude while the tyres grip, towards 0 "
            "when the car slides sideways (not the path speed)",
        ),
        "throttle": FieldSupport(
            _R,
            "the driver's pedal 0..255 -> 0..1: 0x13C on variants ~/C, 0x91 on A/B (the only one they send: the "
            f"throttle after TCS). {_PS5}: 0x91 below 0x13C on all 6,297 TCS-active packets, above it only during "
            "clutch blips",
        ),
        "brake": FieldSupport(
            _R,
            f"0x92 brake 0..255 -> 0..1. {_PS5}: analog over the full range, above 100 with the car decelerating "
            "in 99.5 % of packets, equal to 0x13D in 7,068 of 7,070 braking packets (input vs after-ABS output not "
            "told apart)",
        ),
        "clutch": FieldSupport(_C, f"0xF4 clutch pedal 0..1 ({_PS5}: only 0 or 1 seen)"),
        "gear": FieldSupport(
            _R,
            "0x90 low nibble: 1..14 forward; 0 and 15 -> None (Kaitai: reverse / neutral, unverified). "
            f"{_PS5}: 1..5 matching each car's ratios. 0 appeared only in spins (4 episodes, 875 packets: pedal "
            "released, in-gear flag clear and clutch out in 477 of 552 live packets, sliding at up to 30.5 m/s); R "
            "and N were never selected, so 0 is not shown to be reverse; 15 never appeared",
        ),
        "rpm": FieldSupport(_R, f"0x3C engine RPM. {_PS5}: 0..8,869, equal to 0xFC with the clutch engaged"),
        "max_rpm": FieldSupport(
            _C,
            f"0x8A rev-limiter alert max RPM (approximates the limiter; {_PS5}: one car reached 7,103 rpm against "
            "7,000)",
        ),
        "steering": FieldSupport(
            _C,
            "B/~/C 0x128 wheel angle (rad, left positive) / nominal 450 deg half-lock; not in variant A. "
            f"{_PS5}: the sign agreed with the C road-wheel angles on 22,643 of 22,643 packets, but 0x128 is "
            "clamped at +/-pi, so the value never exceeds +/-0.4: magnitude approximate",
        ),
        "pos_x_m": FieldSupport(
            _R, f"0x04 position X (m). {_PS5}: closed laps, the line crossing repeating within 1 m over 3 races"
        ),
        "pos_y_m": FieldSupport(_R, f"0x08 position Y (m, up axis). {_PS5}: closed laps (same evidence as X)"),
        "pos_z_m": FieldSupport(_R, f"0x0C position Z (m). {_PS5}: closed laps (same evidence as X)"),
        "vel_x_mps": FieldSupport(
            _R,
            f"0x10..0x18 world velocity (m/s). {_PS5}: its integrated magnitude matches the position path to "
            "-0.08..-0.18 % per lap (11 timed laps, reset jumps excluded)",
        ),
        "session_time_s": FieldSupport(
            _R,
            f"derived: packet-id ticks x 1/60 s while not paused. {_PS5}: the game's lap time = non-paused ticks / 60 "
            "within 10 ms on 7 flying laps (one with a 5.6 s pause)",
        ),
        "frame_id": FieldSupport(_R, f"0x70 packet id ({_PS5}: +1 per packet, continuous across stream pauses)"),
        "lap_number": FieldSupport(
            _R,
            "0x74 lap count (0 = not in a timed lap -> None; read with the car on track only: -1 in menus). "
            f"{_PS5}: 11 of 11 increments at the line",
        ),
        "lap_distance_m": FieldSupport(
            _R,
            f"{_DERIVED} since the last line crossing. {_PS5}: -0.08..-0.18 % from the position path on the 11 timed "
            "laps, reset jumps excluded (integrating the speed field 0x4C: -0.09..-1.52 %, the most on laps with a "
            "car reset)",
        ),
        "current_lap_time_ms": FieldSupport(
            _R,
            f"C: 0x15C; A/B/~: derived from ticks since the line crossing. {_PS5} (C): one tick before the line "
            "within 17 ms of the game's last-lap value on every lap",
        ),
        "last_lap_time_ms": FieldSupport(
            _R,
            f"0x7C last lap (ms; -1 -> None). {_PS5}: updated in the packet of the counter increment on 11 of 11 "
            "laps; Pitwall's lap times equal it to the millisecond",
        ),
        "race_position": FieldSupport(
            _C,
            "0x84 when >= 1 (conflicting docs: pre-race grid position vs live position). "
            f"{_PS5}: during races within 1..the field size (0x86) and moving one place at a time - the live "
            "position reading - but not yet compared with the game's HUD",
        ),
        "tyre_surface_temp_c": FieldSupport(
            _R,
            f"0x60..0x6C surface temps, native FL, FR, RL, RR order. {_PS5}: 37..196 C; on the left-turning oval "
            "the right tyres ran 7-9 C hotter, consistent with the order",
        ),
        "fuel_litres": FieldSupport(
            SupportLevel.UNVERIFIED,
            "0x44 fuel level, unit conflicting (litres per PDTools, % per GT7Eng): not emitted until a capture "
            f"settles it ({_PS5}: 100 / 100 throughout); SessionInfo.extra['fuel_fraction'] = level / capacity",
        ),
        "fuel_capacity_litres": FieldSupport(
            SupportLevel.UNVERIFIED, "0x48 fuel capacity, unit conflicting (100 most cars, 5 karts, 0 EVs)"
        ),
        "track_id": FieldSupport(
            _C,
            "derived heuristic: start/finish position + heading + integrated lap length + total turning; layouts "
            f"differing by < 1.5 % length and < 40 deg turning can still merge. {_PS5}: 2 circuits learned, the "
            "same ids again on replay; layouts sharing a line not yet met",
        ),
        "track_length_m": FieldSupport(
            _R,
            f"{_DERIVED}: the shortest of this session's identifying lap(s) and later gap-free laps matching the "
            f"track, never longer than the registry's length. {_PS5}: 914.7 m (oval) and 3,799.0 m once a flying lap "
            "was measured, each within 0.2 % of its lap's position path",
        ),
        "car_id": FieldSupport(
            _R,
            f"0x124 car code (corrupted for cars with 9+ gears). {_PS5}: constant per race (3 cars), changing only "
            "across a load",
        ),
        "total_laps": FieldSupport(
            _R, f"0x76 (0 for timed races / free runs -> None). {_PS5}: the race length in races, -1 in menus"
        ),
        "best_lap_ms": FieldSupport(
            _R,
            f"0x78, SessionInfo.extra (GT7Eng: unstable in the raw packet). {_PS5}: always the minimum so far, no "
            "instability seen",
        ),
        "tyre_inner_temp_c": FieldSupport(_U, "not sent by GT7"),
        "tyre_pressure_psi": FieldSupport(_U, "not sent (0xD4..0xF3 is reserved, not pressures)"),
        "tyre_wear_pct": FieldSupport(_U, "not sent by GT7"),
        "brake_temp_c": FieldSupport(_U, "not sent by GT7"),
        "sector": FieldSupport(_U, "GT7 has no sectors / split times"),
        "lap_invalid": FieldSupport(_U, "GT7 sends no lap validity"),
        "pit_status": FieldSupport(_U, "GT7 sends no pit state"),
        "abs_active": FieldSupport(_U, "no ABS flag; lockups must be inferred from wheel speed"),
        "g_lat": FieldSupport(_U, "B sway/heave/surge units unverified - not mapped"),
        "yaw_rad": FieldSupport(_U, "0x1C..0x28 rotation naming conflicting (quaternion vs angles) - not mapped"),
        "fuel_kg": FieldSupport(_U, "GT7 reports volume or percent, not mass"),
        "weather": FieldSupport(_U, "GT7 sends time of day only"),
        "setup": FieldSupport(_U, "only gear ratios are sent"),
        "session_type": FieldSupport(_U, "not sent by GT7"),
        "drs_open": FieldSupport(_U, "no DRS field in the documented layout (docs/research/gt7-protocol.md)"),
        "ers_store_j": FieldSupport(
            SupportLevel.UNVERIFIED, "variant ~ 0x150 'energy recovery' (units unknown): not mapped"
        ),
        "track_zones": FieldSupport(_U, "no sectors, marshal zones or race flags (gt7-protocol.md section 8)"),
        "field_samples": FieldSupport(_U, "telemetry covers the player's car only (gt7-protocol.md section 8)"),
        "damage": FieldSupport(_U, "not sent (gt7-protocol.md section 8)"),
        "buttons": FieldSupport(_U, "no wheel-button data (the 0x8E flags are car state)"),
    },
    notes=(
        "Validated live on the owner's PS5 on 2026-10-11 (variant C): Pitwall's heartbeat and UDP 33740 listener "
        "received 277,467 packets in 4 captures, 0 rejected, 59.9 Hz; field-by-field evidence in "
        "tests/recorded/test_gt7_ps5_real.py. PS4: not yet tested (its packets are documented as identical).",
        "No lap distance in the protocol: integrated from the velocity magnitude (within 0.2 % of the driven path on "
        "the PS5 recordings); unanchored until the first start/finish crossing seen while moving (race lap 1 after "
        "a standing start has no distance, but keeps the game's time).",
        "No track id: derived from the start/finish crossing position and direction, the lap length and the lap's "
        "total turning - a heuristic; on the PS5 recordings 2 circuits were learned with the line repeatable within "
        "1 m. A new circuit is learned from two agreeing laps.",
        "Sessions: one opens after 0.5 s of live driving and ends on a load (a car reset is not one), a car change, "
        "a retry, 2 s of the frozen stream GT7 sends after leaving a race, or 2 s off track: menus, replays and "
        "background laps are never sessions.",
        "Fuel unit conflicting (litres vs %): only the level / capacity fraction is reported.",
        "Requires a heartbeat to the console (UDP 33739) every few seconds; telemetry arrives on UDP 33740.",
        "Synthetic streams carry a marker in reserved bytes 0xD4..0xF3 and are flagged synthetic.",
    ),
)


# ------------------------------------------------------------------------------------------------ track identity
def _round_to(v: float, step: float) -> int:
    return round(v / step) * int(step)


def _angle_diff_deg(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def _length_tol_m(a: float, b: float) -> float:
    return max(SF_MATCH_LENGTH_MIN_M, SF_MATCH_LENGTH_FRAC * max(a, b))


def _turn_tol_deg(a: float, b: float) -> float:
    return max(TURN_MATCH_MIN_DEG, TURN_MATCH_FRAC * max(a, b))


@dataclass(frozen=True, slots=True)
class TrackSignature:
    """Derived identity of a GT7 circuit layout, serialised as ``gt7:sf:<x>:<z>:<heading>:<length>:<turn>``.

    * ``sf_x_m`` / ``sf_z_m`` / ``heading_deg``: where and which way the start/finish line is crossed (10 m and
      15 deg grid). Heading separates reverse layouts.
    * ``length_m``: integrated lap length (10 m grid). Separates layouts sharing a line that differ by a whole
      section (Brands Hatch Indy/GP, Nurburgring GP/24h, Suzuka East/full).
    * ``turn_deg``: the lap's total turning - the sum of absolute heading changes of the velocity vector sampled
      every ``TURN_SAMPLE_M`` of lap distance, less a ``TURN_DEADBAND_DEG`` dead band per sample (10 deg grid).
      Layouts that share a start line and differ only by a chicane (Monza / Monza No Chicane 5793 / 5755 m, Le
      Mans 13629 / 13567 m, Fuji 4563 / 4526 m per ddm999/gt7info course.csv) are closer in length than the
      ~1 % integration drift, so length cannot tell them apart; a chicane adds ~100 deg or more of turning.
      Total turning is independent of drift and of where on the lap a sample falls, and through monotone
      corners it is fixed by geometry, not by the line driven. It does vary with the line through chicanes and
      with weaving, hence the tolerance.

    Matching is fuzzy: line within ``SF_MATCH_RADIUS_M`` and ``SF_MATCH_HEADING_DEG``, length within
    ``max(SF_MATCH_LENGTH_MIN_M, SF_MATCH_LENGTH_FRAC x length)``, turning within
    ``max(TURN_MATCH_MIN_DEG, TURN_MATCH_FRAC x turning)``. This is a heuristic, validated on synthetic layouts
    only: two real layouts whose difference stays inside every tolerance would still merge, and a driver whose
    turning differs a lot (heavy weaving) fragments a circuit into a second id. Ids in the older six-part form
    (no turning) are not parsed, so they can never be merged with a turning-aware signature.
    """

    sf_x_m: float
    sf_z_m: float
    heading_deg: float  # direction of travel at the line: atan2(vel_x, vel_z), 0..360
    length_m: float
    turn_deg: float

    @classmethod
    def measured(cls, x: float, z: float, heading_deg: float, length_m: float, turn_deg: float) -> TrackSignature:
        """Quantise a measurement to the id grid so ``parse(id)`` round-trips exactly. Raises ``ValueError`` for
        non-finite or impossible values (a corrupt measurement must never become a track id)."""
        if not all(math.isfinite(v) for v in (x, z, heading_deg, length_m, turn_deg)):
            raise ValueError("non-finite GT7 track measurement")
        if length_m <= 0 or turn_deg < 0:
            raise ValueError(f"impossible GT7 track measurement: length {length_m} m, turning {turn_deg} deg")
        return cls(
            float(_round_to(x, 10.0)),
            float(_round_to(z, 10.0)),
            float(_round_to(heading_deg % 360.0, 15.0) % 360),
            float(_round_to(length_m, 10.0)),
            float(_round_to(turn_deg, 10.0)),
        )

    @property
    def track_id(self) -> str:
        return (
            f"gt7:sf:{int(self.sf_x_m)}:{int(self.sf_z_m)}:{int(self.heading_deg)}:{int(self.length_m)}:"
            f"{int(self.turn_deg)}"
        )

    @classmethod
    def parse(cls, track_id: str) -> TrackSignature | None:
        parts = track_id.split(":")
        if len(parts) != 7 or parts[0] != "gt7" or parts[1] != "sf":
            return None
        try:
            x, z, h, length, turn = (float(p) for p in parts[2:])
        except ValueError:
            return None
        if not all(math.isfinite(v) for v in (x, z, h, length, turn)) or length <= 0 or turn < 0:
            return None
        return cls(x, z, h % 360.0, length, turn)

    def near_line(self, x: float, z: float, heading_deg: float) -> bool:
        return (
            math.hypot(x - self.sf_x_m, z - self.sf_z_m) <= SF_MATCH_RADIUS_M
            and _angle_diff_deg(heading_deg, self.heading_deg) <= SF_MATCH_HEADING_DEG
        )

    def matches(self, other: TrackSignature) -> bool:
        return (
            self.near_line(other.sf_x_m, other.sf_z_m, other.heading_deg)
            and abs(self.length_m - other.length_m) <= _length_tol_m(self.length_m, other.length_m)
            and abs(self.turn_deg - other.turn_deg) <= _turn_tol_deg(self.turn_deg, other.turn_deg)
        )

    def mismatch(self, other: TrackSignature) -> float:
        """How far apart two matching signatures are (sum of each difference over its tolerance)."""
        return (
            math.hypot(self.sf_x_m - other.sf_x_m, self.sf_z_m - other.sf_z_m) / SF_MATCH_RADIUS_M
            + abs(self.length_m - other.length_m) / _length_tol_m(self.length_m, other.length_m)
            + abs(self.turn_deg - other.turn_deg) / _turn_tol_deg(self.turn_deg, other.turn_deg)
        )


@dataclass(frozen=True, slots=True)
class _LapShape:
    """One measured anchored lap: what identification and learning work from."""

    length_m: float
    turn_deg: float
    gap_free: bool  # no packet gap above LENGTH_GAP_TICKS: may teach a new track

    def agrees(self, other: _LapShape) -> bool:
        length_tol = max(LEARN_AGREE_MIN_M, LEARN_AGREE_FRAC * max(self.length_m, other.length_m))
        return abs(self.length_m - other.length_m) <= length_tol and abs(
            self.turn_deg - other.turn_deg
        ) <= _turn_tol_deg(self.turn_deg, other.turn_deg)


# ------------------------------------------------------------------------------------------------ adapter state
@dataclass(slots=True)
class _Motion:
    running: bool  # simulation not paused
    vmag_mps: float  # velocity magnitude (what lap distance integrates; see the module docstring)
    pos: tuple[float, float, float]
    pid: int  # packet id, so a dropped packet is bridged exactly like a lost one


@dataclass(frozen=True, slots=True)
class _Seen:
    """What a car reset is told from: the last packet before a loading run and the first one after it."""

    on_track: bool
    car_code: int
    lap: int
    total_laps: int
    lap_timer_ms: int | None  # variant C 0x15C (None for A/B/~ or when unset)


@dataclass(slots=True)
class _Hold:
    """A completion waiting for ``last_lap_ms`` to update, with the frames that must follow it."""

    completion: LapCompletion
    stale_ms: int
    ticks_left: int
    items: list[Emitted] = field(default_factory=list)


@dataclass(slots=True)
class _SessionState:
    uid: str
    synthetic: bool
    lap: int | None = None
    dist_m: float | None = None  # None = not anchored to a line crossing
    lap_elapsed_s: float = 0.0
    anchor_confirmed: bool = False  # anchored at a crossing known to be on the start/finish line
    anchor_misaligned: bool = False  # a provisional anchor turned out not to be on the line
    anchor_lost: bool = False  # this lap was anchored, then lost the anchor (gap, teleport): its trace is truncated
    anchor_xz: tuple[float, float] | None = None
    max_gap_ticks: int = 0  # largest packet gap since the anchor (learning needs a gap-free lap)
    turn_deg: float = 0.0  # total turning since the anchor (see TrackSignature)
    turn_heading: float | None = None  # heading at the last turning sample
    turn_next_m: float = 0.0  # lap distance of the next turning sample
    sf: tuple[float, float, float] | None = None  # (x, z, heading) of the start/finish crossing
    track: TrackSignature | None = None
    track_length_m: float | None = None  # published length: this session's measurement, <= the registry's
    candidates: list[_LapShape] = field(default_factory=list)  # gap-free laps of a not-yet-known track
    completed_lap: int | None = None  # last lap a LapCompletion was emitted for
    cooldown: bool = False  # lap timed without a counter increment: not racing until the counter changes
    race_start: bool = False  # lap 1 of this session began at a race start (lap 0 -> 1 with a lap total)
    lap_traced: bool = False  # the current lap was anchored at some point (some of its frames have a lap distance)
    car_code: int | None = None  # the session's car (0x124; 0 = not sent)
    prev_tod: int | None = None  # time of day of the last on-track packet (retry detector)
    hold: _Hold | None = None
    info_key: tuple[Any, ...] | None = None
    info_countdown: int = 0


def _gear(byte: int) -> int | None:
    """Low nibble of 0x90 (doc section 4.2): 1..14 forward. 0 and 15 are ``None``: Kaitai reads them as reverse and
    neutral, but on the owner's PS5 captures gear 0 appeared only in spins, with the pedal released and the clutch out
    (no gear engaged fits that as well as reverse), and 15 never; R and N were never selected (doc section 11, 3)."""
    g = byte & 0x0F
    return g if 1 <= g <= 14 else None


def _ascii(raw: bytes) -> str | None:
    s = raw.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()
    return s or None


def _heading_deg(vx: float, vz: float) -> float:
    return math.degrees(math.atan2(vx, vz)) % 360.0


def _fin(v: float) -> float | None:
    return v if math.isfinite(v) else None


_OFF = P.field_offsets(P.PACKET_A)
_PID_AT, _FLAGS_AT = _OFF["packet_id"], _OFF["flags"]
_PAUSED_BIT = int(P.Flags.PAUSED)
assert _PAUSED_BIT < 0x100  # the paused bit lives in the bitfield's low byte (little-endian)


def _signature(plain: bytes) -> bytes:
    """A decrypted packet without what changes when the simulation does not: the packet id (0x70), the nonce seed
    (0x40..0x43, meaningless after decryption) and the paused bit (0x8E bit 1). Two equal signatures in a row mean
    the simulation did not advance between them (a pause, or the frozen stream GT7 sends after leaving a race)."""
    flags_lo = plain[_FLAGS_AT] & ~_PAUSED_BIT & 0xFF
    return b"".join(
        (
            plain[: P.IV_OFFSET],
            plain[P.IV_OFFSET + 4 : _PID_AT],
            plain[_PID_AT + 4 : _FLAGS_AT],
            bytes((flags_lo,)),
            plain[_FLAGS_AT + 1 :],
        )
    )


def _is_car_reset(before: _Seen | None, after: _Seen) -> bool:
    """Was a loading run the game putting the car back on track (same race, same lap, timer running on)?

    On the owner's PS5 captures a reset is a 1-packet loading pulse with CarOnTrack set on both sides, the same car,
    lap count and lap total, and the variant C lap timer 17-34 ms further on. Variants A/B/~ send no lap timer, so
    there the structural checks alone decide."""
    if before is None or not (before.on_track and after.on_track):
        return False
    if (before.car_code, before.lap, before.total_laps) != (after.car_code, after.lap, after.total_laps):
        return False
    if before.lap_timer_ms is None or after.lap_timer_ms is None:
        return before.lap_timer_ms is None and after.lap_timer_ms is None
    return 0 <= after.lap_timer_ms - before.lap_timer_ms < RESET_TIMER_MAX_MS


class GT7Adapter:
    """Stateful decoder for one GT7 telemetry stream (one console).

    ``known_track_ids`` seeds the derived-track registry (e.g. GT7 track ids already in the database) so a
    track keeps the same id across sessions and process restarts. The registry and the steering-sign evidence
    are knowledge about the game, not about a session, so ``reset()`` keeps them.
    """

    def __init__(self, known_track_ids: Iterable[str] = ()) -> None:
        self.info = GT7_INFO
        self.stats = DecodeStats()
        self._known: list[TrackSignature] = []
        for tid in known_track_ids:
            self.add_known_track(tid)
        self._steer_agree = 0
        self._steer_disagree = 0
        self.reset()

    # ------------------------------------------------------------------ public helpers
    def add_known_track(self, track_id: str) -> bool:
        """Register a previously identified GT7 track id; returns False for ids that are not GT7-derived."""
        sig = TrackSignature.parse(track_id)
        if sig is None:
            return False
        if all(k != sig for k in self._known):
            self._known.append(sig)
        return True

    @property
    def known_track_ids(self) -> list[str]:
        return [k.track_id for k in self._known]

    @property
    def session_uid(self) -> str | None:
        """The open session's uid; None while no session is open (menus, replays, loading, a frozen stream)."""
        return None if self._s is None else self._s.uid

    @property
    def steering_sign(self) -> float:
        """Multiplier from the 0x128 wheel angle to the -1 left..+1 right convention."""
        flipped = self._steer_disagree >= STEER_CHECK_MIN_SAMPLES and self._steer_disagree > 9 * self._steer_agree
        return 1.0 if flipped else -1.0

    def reset(self) -> None:
        self._s: _SessionState | None = None
        self._last_pid: int | None = None
        self._dup_run = 0  # consecutive packets dropped as duplicates / out of order
        self._clock_s = 0.0
        self._prev: _Motion | None = None
        self._prev_last_ms: int | None = None
        self._last_t_recv_ns: int | None = None
        self._sig: bytes | None = None  # the previous packet's signature (_signature): is the simulation advancing?
        self._live_run = 0  # consecutive live packets while no session is open (OPEN_TICKS opens one)
        self._stall_run = 0  # consecutive frozen packets at speed in an open session
        self._off_run = 0  # consecutive packets without CarOnTrack in an open session
        self._loading_run = 0  # consecutive LOADING packets
        self._seen: _Seen | None = None  # the last packet that was not loading
        self._before_load: _Seen | None = None  # the last packet before the current loading run
        self._pkt: tuple[P.Variant, dict[str, Any], P.Flags] = (P.VARIANTS["A"], {}, P.Flags(0))

    # ------------------------------------------------------------------ structural validation
    def can_decode(self, data: bytes) -> bool:
        try:
            return P.has_valid_magic(data)
        except Exception:  # must never raise (auto-detection)
            return False

    # ------------------------------------------------------------------ main entry point
    def decode(self, data: bytes, t_recv_ns: int) -> list[Emitted]:
        self.stats.packets += 1
        try:
            variant, plain = P.decrypt(data)
        except P.PacketError as e:
            self.stats.rejected += 1
            self.stats.last_error = str(e)
            raise PacketRejected(str(e)) from e
        self.stats.count(f"variant_{variant.name}")
        out: list[Emitted] = []
        try:
            if self._step(variant, P.unpack(variant, plain), _signature(plain), t_recv_ns, out):
                self.stats.decoded += 1
            else:
                self.stats.ignored += 1
        except Exception as e:  # never let one bad packet kill the stream
            self.stats.errors += 1
            self.stats.last_error = f"{variant.name}: {e!r}"
            log.exception("GT7 decode error (variant %s)", variant.name)
        return out

    # ------------------------------------------------------------------ per-packet state machine
    def _step(self, v: P.Variant, p: dict[str, Any], sig: bytes, t: int, out: list[Emitted]) -> bool:
        """Advance the stream state by one packet. Returns False when the packet is deliberately dropped."""
        pid: int = p["packet_id"]
        flags = P.Flags(p["flags"] & 0x0FFF)
        self._pkt = (v, p, flags)

        # 1. packet ordering (doc section 3.9): duplicates / out-of-order packets are dropped; an id far behind the
        #    last one means the stream restarted (reconnect or retry: the session ends, see 3.)
        restarted = False
        if self._last_pid is not None:
            d = pid - self._last_pid
            if d <= 0 and -d < DUPLICATE_WINDOW_TICKS:
                self._dup_run += 1
                if self._dup_run <= DUPLICATE_RUN_RESTART:
                    self.stats.count("duplicate_or_out_of_order")
                    return False
            if d <= 0:
                self.stats.count("stream_restart")
                restarted = True
        self._dup_run = 0
        self._last_pid = pid
        prev_sig, self._sig = self._sig, sig
        advancing = prev_sig is not None and sig != prev_sig
        on_track = bool(flags & P.Flags.CAR_ON_TRACK)
        paused = bool(flags & P.Flags.PAUSED)

        # 2. loading screens: no meaningful car data. A short run with the car on track on both sides is a car
        #    reset (decided when the run ends); a longer one, or any other, ends the session.
        if flags & P.Flags.LOADING_OR_PROCESSING:
            if self._loading_run == 0:
                self._before_load = self._seen
            self._loading_run += 1
            self._prev = None  # whatever happens next is a discontinuity (a reset is a teleport)
            self._live_run = 0
            self.stats.count("loading")
            if self._s is not None and self._loading_run > RESET_MAX_LOADING_TICKS:
                self._end_session(t, "loading", out)
            return False
        cur_ms: int = p["current_lap_ms"] if v.name == "C" else -1
        seen = _Seen(on_track, p["car_code"], p["lap_count"], p["total_laps"], cur_ms if cur_ms >= 0 else None)
        self._seen = seen
        if self._loading_run:
            self._loading_run = 0
            if self._s is not None:
                if _is_car_reset(self._before_load, seen):
                    self.stats.count("car_reset")
                    log.info("GT7 car reset to track: the session continues, the lap's trace stops here")
                else:
                    self._end_session(t, "loading", out)

        # 3. the open session's boundaries (no session uid in GT7)
        speed: float = p["speed"]
        vel: tuple[float, float, float] = p["velocity"]
        vmag = math.hypot(*vel)  # NaN for a corrupt velocity: never "frozen", and dropped in 4b
        stalled = not paused and not advancing and prev_sig is not None  # nothing changed: never integrated (7.)
        s = self._s
        if s is not None:
            reason = self._end_reason(s, p, on_track, restarted)
            frozen = stalled and vmag >= FROZEN_MIN_SPEED_MPS
            self._stall_run = self._stall_run + 1 if frozen else 0
            self._off_run = 0 if on_track else self._off_run + 1
            if reason is None and self._stall_run >= STALL_END_TICKS:
                reason = "frozen"
            if reason is None and self._off_run >= OFF_TRACK_END_TICKS:
                reason = "off_track"
            if reason is not None:
                self._end_session(t, reason, out)
            elif frozen:  # moving without moving: the simulation is not running. No frame, no clock, no distance.
                self.stats.count("frozen")
                prev = self._prev
                if prev is not None:  # the next packet that advances integrates one tick, as after a pause
                    prev.running = False
                    prev.pid = pid
                return False

        # 4. no session: one opens after OPEN_TICKS live packets (nothing is emitted before)
        if self._s is None:
            live = on_track and not paused and advancing
            self._live_run = self._live_run + 1 if live else 0
            self._prev_last_ms = p["last_lap_ms"]
            if self._live_run < OPEN_TICKS:
                self.stats.count("no_session")
                return False
            self._start_session(t, p["reserved"] == P.SYNTHETIC_MARKER, p)
        s = self._s
        assert s is not None
        car_code: int = p["car_code"]
        if car_code != 0:
            s.car_code = car_code
        tod: int = p["time_of_day_ms"]
        if on_track and 0 < tod < DAY_MS:
            s.prev_tod = tod

        # 4b. corrupt motion: dropped and bridged like a lost packet (the next packet integrates across it)
        pos: tuple[float, float, float] = p["position"]
        if not all(math.isfinite(x) for x in (speed, *pos, *vel)):
            self.stats.count("non_finite_motion")
            return False

        # 5. a completion waiting for last_lap_ms (released before anything of this packet is emitted)
        last_ms: int = p["last_lap_ms"]
        hold_was_active = s.hold is not None
        if hold_was_active:
            self._service_hold(s, last_ms, out)

        # 6. slow-changing session context (~2 Hz and on change), ahead of this packet's frame so the first
        #    frame of a new session never lands in the previous one
        s.info_countdown -= 1
        if s.info_countdown <= 0 or self._info_key(s) != s.info_key:
            self._emit_session_info(s, t, out)

        # 7. tick clock + distance integration
        running = not paused
        prev = self._prev
        gap = 0
        if prev is not None:
            gap = pid - prev.pid
            if gap > MAX_GAP_TICKS:
                self.stats.count("stream_gap")
                prev = None
        if prev is None:
            if self._last_t_recv_ns is not None:
                self._clock_s += max(TICK_S, (t - self._last_t_recv_ns) / 1e9)  # downstream sees the gap
            self._unanchor(s, lost=True)
        elif running:
            ticks = gap if prev.running else 1  # leaving a pause: one tick of motion, not the paused span
            dt = ticks * TICK_S
            self._clock_s += dt
            if s.dist_m is not None:
                disp = math.dist(pos, prev.pos)
                if disp > 1.5 * max(vmag, prev.vmag_mps) * dt + TELEPORT_SLACK_M:
                    self.stats.count("teleport")
                    self._unanchor(s, lost=True)
                else:
                    if not stalled:  # a repeated payload (a car standing still) did not move: never integrated
                        s.dist_m += 0.5 * (vmag + prev.vmag_mps) * dt
                    s.lap_elapsed_s += dt
                    s.max_gap_ticks = max(s.max_gap_ticks, ticks)
                    self._sample_turn(s, speed, vel)

        # 8. lap counter transitions / completions: only while the car is on track (menus send -1, replays and the
        #    menus' background laps run their own counters)
        lap_raw: int = p["lap_count"]
        crossing = prev is not None and gap <= CROSSING_GAP_TICKS and abs(speed) >= ANCHOR_MIN_SPEED_MPS
        if on_track:
            if s.lap is not None and lap_raw != s.lap:
                self._on_lap_change(s, s.lap, lap_raw, last_ms, pos, vel, crossing, t, out)
            elif (
                s.lap is not None
                and lap_raw >= 1
                and last_ms > 0
                and self._prev_last_ms is not None
                and last_ms != self._prev_last_ms
                and not hold_was_active  # that change was the held completion's time, already used
            ):
                self._on_last_lap_update(s, lap_raw, last_ms, pos, vel, crossing, t, out)
            s.lap = lap_raw

        # 9. the frame itself
        frame = self._frame(v, p, flags, s, t, pid)
        if s.hold is not None:
            s.hold.items.append(frame)
        else:
            out.append(frame)

        self._prev = _Motion(running=bool(running), vmag_mps=vmag, pos=pos, pid=pid)
        self._prev_last_ms = last_ms
        self._last_t_recv_ns = t
        return True

    # ------------------------------------------------------------------ sessions
    def _end_reason(self, s: _SessionState, p: dict[str, Any], on_track: bool, restarted: bool) -> str | None:
        """Why this packet ends the open session (None: it does not). A car change, a packet-id restart, or doc
        section 9's retry detector (GT7Eng) while on track: the lap counter going back or the time of day rewinding,
        so the re-driven laps (same lap numbers) never replace the earlier ones in storage."""
        if restarted:
            return "retry_stream_restart"
        car_code: int = p["car_code"]
        if s.car_code is not None and car_code not in (0, s.car_code):
            return "car_change"
        if not on_track:
            return None
        lap_raw: int = p["lap_count"]
        if s.lap is not None and lap_raw < s.lap:
            return "retry_lap_reset"
        tod: int = p["time_of_day_ms"]
        prev_tod = s.prev_tod
        if prev_tod is not None and 0 < tod < DAY_MS and RETRY_TOD_REWIND_MS <= prev_tod - tod < TOD_WRAP_MS:
            return "retry_time_rewind"
        return None

    def _start_session(self, t: int, synthetic: bool, p: dict[str, Any]) -> None:
        uid = str(SYNTHETIC_SESSION_UID) if synthetic else f"gt7:{t}"
        self._s = _SessionState(uid=uid, synthetic=synthetic, car_code=p["car_code"] or None)
        self._prev = None
        self._stall_run = self._off_run = 0
        self.stats.count("sessions")
        log.info("GT7 session %s opened", uid)

    def _end_session(self, t: int, reason: str, out: list[Emitted]) -> None:
        """Close the open session: a held completion first (it never got its time), then ``session_ended`` - the
        session manager flushes the lap in progress as incomplete. The next session opens after OPEN_TICKS live
        packets."""
        s = self._s
        if s is None:
            return
        if s.hold is not None:
            self._flush_hold(s, out, None)
        out.append(
            GameEvent(
                kind=EventKind.SESSION_ENDED,
                game=Game.GT7,
                t_recv_ns=t,
                session_time_s=self._clock_s,
                code=reason,
                payload={"reason": reason},
            )
        )
        self.stats.count(reason if reason.startswith("retry_") else f"session_end_{reason}")
        log.info("GT7 session %s ended (%s)", s.uid, reason)
        self._s = None
        self._prev = None
        self._live_run = self._stall_run = self._off_run = 0

    # ------------------------------------------------------------------ distance anchoring
    @staticmethod
    def _unanchor(s: _SessionState, *, lost: bool = False) -> None:
        """Forget the anchor. ``lost=True``: a discontinuity inside the current lap (its trace is truncated if it
        was anchored); ``lost=False``: a lap boundary, after which the new lap simply starts unanchored."""
        if not lost:
            s.anchor_lost = False
            s.lap_traced = False  # a lap boundary: the new lap starts unplaced
        elif s.dist_m is not None:
            s.anchor_lost = True
        s.dist_m = None
        s.lap_elapsed_s = 0.0
        s.anchor_confirmed = False
        s.anchor_misaligned = False
        s.anchor_xz = None
        s.turn_heading = None

    @staticmethod
    def _anchor(s: _SessionState, pos: tuple[float, float, float], heading: float, confirmed: bool) -> None:
        s.dist_m = 0.0
        s.lap_traced = True
        s.lap_elapsed_s = 0.0
        s.anchor_confirmed = confirmed
        s.anchor_misaligned = False
        s.anchor_lost = False
        s.anchor_xz = (pos[0], pos[2])
        s.max_gap_ticks = 0
        s.turn_deg = 0.0
        s.turn_heading = heading
        s.turn_next_m = TURN_SAMPLE_M

    @staticmethod
    def _sample_turn(s: _SessionState, speed: float, vel: tuple[float, float, float]) -> None:
        """Accumulate the lap's total turning (TrackSignature.turn_deg): O(1), one sample per TURN_SAMPLE_M."""
        if s.dist_m is None or s.dist_m < s.turn_next_m or abs(speed) < ANCHOR_MIN_SPEED_MPS:
            return  # (nearly stopped: the velocity direction is noise; the next sample spans the stop)
        heading = _heading_deg(vel[0], vel[2])
        if s.turn_heading is not None:
            s.turn_deg += max(0.0, _angle_diff_deg(heading, s.turn_heading) - TURN_DEADBAND_DEG)
        s.turn_heading = heading
        s.turn_next_m = s.dist_m + TURN_SAMPLE_M

    def _near_known_line(self, s: _SessionState, x: float, z: float, heading: float) -> bool | None:
        """True/False if a start/finish line is known near here (this session, or the registry); None if
        nothing is known (an unknown track: cannot tell)."""
        if s.sf is not None:
            sx, sz, sh = s.sf
            return math.hypot(x - sx, z - sz) <= SF_MATCH_RADIUS_M and _angle_diff_deg(heading, sh) <= (
                SF_MATCH_HEADING_DEG
            )
        if any(k.near_line(x, z, heading) for k in self._known):
            return True
        return None

    def _on_lap_change(
        self,
        s: _SessionState,
        prev_lap: int,
        lap: int,
        last_ms: int,
        pos: tuple[float, float, float],
        vel: tuple[float, float, float],
        crossing: bool,
        t: int,
        out: list[Emitted],
    ) -> None:
        s.cooldown = False
        heading = _heading_deg(vel[0], vel[2])
        if lap == prev_lap + 1 and prev_lap >= 1:
            # a start/finish crossing that completes lap ``prev_lap``
            on_line, shape = self._measure_lap(s, pos, heading, crossing)
            if shape is not None:
                self._identify_track(s, shape, t, out)  # a new track id must precede the completion
            if s.completed_lap != prev_lap:
                comp = self._completion(s, prev_lap, last_ms, t)
                if self._last_lap_is_current(s, last_ms):
                    out.append(comp)
                else:  # last_ms not updated yet in this packet: hold this lap's frames until it is
                    comp.lap_time_ms = None
                    s.hold = _Hold(completion=comp, stale_ms=last_ms, ticks_left=LAST_LAP_HOLD_TICKS)
                s.completed_lap = prev_lap
            if on_line:
                self._anchor(s, pos, heading, confirmed=True)
            else:  # no usable crossing, or a counter increment away from the learned line
                self._unanchor(s)
            return
        # anything else: lap 0 -> 1, or laps skipped during a gap (a counter going back while on track ends the
        # session, see _end_reason, so it never gets here)
        self.stats.count("lap_reset" if lap <= prev_lap else "lap_start")
        if prev_lap <= 0 and lap == 1 and self._pkt[1]["total_laps"] > 0:
            s.race_start = True  # race lap 1: the game times it from the start signal, not from the line
        near = self._near_known_line(s, pos[0], pos[2], heading) if lap >= 1 and crossing else False
        if near is True:
            self._anchor(s, pos, heading, confirmed=True)
        elif near is None:
            # Unknown line, counter incremented while moving: leaving the out-lap of a time trial / free run, or a
            # rolling race start (every real one incremented within 1 m of the line). Provisional until the next
            # crossing reveals where the line is.
            self._anchor(s, pos, heading, confirmed=False)
        else:
            # standing start (stopped), an increment away from the learned line, or a gap: the offset to the line
            # is unknown
            self._unanchor(s)

    def _measure_lap(
        self, s: _SessionState, pos: tuple[float, float, float], heading: float, crossing: bool
    ) -> tuple[bool, _LapShape | None]:
        """Record the start/finish line from a crossing. Returns whether this crossing is on the line (so the next
        lap may anchor here) and the just-finished lap's measurement if it can be used for track identity."""
        if not crossing:
            return False, None
        x, z = pos[0], pos[2]
        if s.sf is None:
            s.sf = (x, z, heading)
        elif self._near_known_line(s, x, z, heading) is False:
            self.stats.count("sf_crossing_mismatch")
            log.info("GT7 lap change %.0f m from the learned start/finish line", math.hypot(x - s.sf[0], z - s.sf[1]))
            return False, None
        if s.dist_m is not None and not s.anchor_confirmed:
            ax = s.anchor_xz
            if ax is None or math.hypot(ax[0] - s.sf[0], ax[1] - s.sf[1]) > SF_MATCH_RADIUS_M:
                self.stats.count("anchor_mismatch")  # the provisional anchor was not on the line
                log.info("GT7 lap started away from the start/finish line: its distance trace is misaligned")
                s.anchor_misaligned = True
                return True, None
            s.anchor_confirmed = True
        if s.dist_m is None or s.max_gap_ticks > IDENTIFY_GAP_TICKS:
            return True, None
        return True, _LapShape(s.dist_m, s.turn_deg, gap_free=s.max_gap_ticks <= LENGTH_GAP_TICKS)

    def _best_known(self, cand: TrackSignature) -> TrackSignature | None:
        best: TrackSignature | None = None
        for known in self._known:
            if known.matches(cand) and (best is None or known.mismatch(cand) < best.mismatch(cand)):
                best = known
        return best

    def _identify_track(self, s: _SessionState, shape: _LapShape, t: int, out: list[Emitted]) -> None:
        """Identify the session's track from one measured lap (registry match) or learn it from two agreeing
        gap-free laps. Publishes the result (SessionInfo) when the track becomes known. Once it is known, a shorter
        gap-free lap that matches it lowers the published length (``_lower_length``)."""
        assert s.sf is not None
        if not MIN_TRACK_LENGTH_M <= shape.length_m <= MAX_TRACK_LENGTH_M:
            self.stats.count("implausible_lap_length")
            return
        sx, sz, sh = s.sf
        cand = TrackSignature.measured(sx, sz, sh, shape.length_m, shape.turn_deg)
        if s.track is not None:
            self._lower_length(s, s.track, cand, shape, t, out)
            return
        known = self._best_known(cand)
        if known is not None:
            self._set_track(s, known, min(known.length_m, shape.length_m), shape, t, out)
            return
        if not shape.gap_free:
            return  # bridged distance may identify a known track, but never teaches a new one
        other = next((c for c in reversed(s.candidates) if c.agrees(shape)), None)
        if other is None:
            s.candidates.append(shape)
            del s.candidates[:-LEARN_MAX_CANDIDATES]
            return
        learned = TrackSignature.measured(
            sx, sz, sh, 0.5 * (other.length_m + shape.length_m), 0.5 * (other.turn_deg + shape.turn_deg)
        )
        length_m = min(other.length_m, shape.length_m)  # the measurements, not the id's 10 m grid
        track = self._best_known(learned)
        if track is None:
            track = learned
            if not s.synthetic:  # synthetic geometry must never feed real track identity
                self._known.append(learned)
        else:
            length_m = min(length_m, track.length_m)
        self._set_track(s, track, length_m, shape, t, out)

    def _lower_length(
        self,
        s: _SessionState,
        track: TrackSignature,
        cand: TrackSignature,
        shape: _LapShape,
        t: int,
        out: list[Emitted],
    ) -> None:
        """Lower the published length to a later lap's measurement when that lap is gap-free, matches the session's
        track and is shorter (race lap 1 on a wider line, 932.6 m on the owner's oval, can identify a 920 m registry
        id; the next flying lap measured 914.7 m). Never raised: an over-estimate makes complete laps incomplete
        (module docstring). Published at once, ahead of the lap's completion."""
        if s.track_length_m is None or shape.length_m >= s.track_length_m or not shape.gap_free:
            return
        if not track.matches(cand):
            return  # outside the layout's length or turning tolerance (a big cut, a pit lane): not this layout
        log.info("GT7 track %s: published length %.1f m -> %.1f m", track.track_id, s.track_length_m, shape.length_m)
        s.track_length_m = shape.length_m
        self._emit_session_info(s, t, out)

    def _set_track(
        self, s: _SessionState, track: TrackSignature, length_m: float, shape: _LapShape, t: int, out: list[Emitted]
    ) -> None:
        s.track = track
        s.track_length_m = length_m
        s.candidates.clear()
        log.info(
            "GT7 track identified as %s (measured lap %.0f m, %.0f deg turning; published length %.0f m)",
            track.track_id,
            shape.length_m,
            shape.turn_deg,
            length_m,
        )
        self._emit_session_info(s, t, out)

    # ------------------------------------------------------------------ completions
    def _last_lap_is_current(self, s: _SessionState, last_ms: int) -> bool:
        """Is ``last_ms`` (read in the packet where the counter incremented) the time of the lap just finished?

        Yes if it changed in this packet. If it did not, it is either a lap timed to the same millisecond as
        the previous one or a field lagging the counter; an anchored lap disambiguates by its derived time
        (tight tolerance: one tick at each end plus 0.2 % tick-rate error). Otherwise: unknown, so hold.
        """
        if last_ms <= 0:
            return False
        if self._prev_last_ms is None or last_ms != self._prev_last_ms:
            return True
        if s.dist_m is None:
            return False
        return abs(s.lap_elapsed_s - last_ms / 1000.0) <= SAME_LAP_TIME_TOL_S + 0.002 * last_ms / 1000.0

    def _completion(self, s: _SessionState, lap: int, last_ms: int, t: int) -> LapCompletion:
        return LapCompletion(
            game=Game.GT7,
            t_recv_ns=t,
            lap_number=lap,
            lap_time_ms=last_ms if last_ms > 0 else None,
            sector_times_ms=[],
            # GT7 reports no lap validity, so this is None - except for a lap whose derived distance is known to
            # be wrong: a provisional anchor that was not on the line (misaligned), or an anchor lost part-way
            # (truncated). False keeps such a lap out of reference selection and track-model learning, which
            # would otherwise be corrupted by it - also before the track length is known.
            valid=False if s.anchor_misaligned or s.anchor_lost else None,
            session_time_s=self._clock_s,
            race_start=True if lap == 1 and s.race_start else None,
            untraced=not s.lap_traced,  # never anchored: the game's time is stored without a trace
        )

    def _on_last_lap_update(
        self,
        s: _SessionState,
        lap: int,
        last_ms: int,
        pos: tuple[float, float, float],
        vel: tuple[float, float, float],
        crossing: bool,
        t: int,
        out: list[Emitted],
    ) -> None:
        """``last_lap_ms`` changed without a counter increment: the current lap was timed (final race lap, or
        the timer leading the counter by a tick) - but only if it matches the derived time of this lap."""
        if s.completed_lap == lap or s.dist_m is None:
            self.stats.count("last_lap_update_unmatched")
            return
        tol = max(LAST_LAP_MATCH_TOL_S, LAST_LAP_MATCH_TOL_FRAC * last_ms / 1000.0)
        if abs(s.lap_elapsed_s - last_ms / 1000.0) > tol:
            self.stats.count("last_lap_update_unmatched")
            return
        _, shape = self._measure_lap(s, pos, _heading_deg(vel[0], vel[2]), crossing)
        if shape is not None:
            self._identify_track(s, shape, t, out)
        out.append(self._completion(s, lap, last_ms, t))
        s.completed_lap = lap
        s.cooldown = True
        self._unanchor(s)

    def _service_hold(self, s: _SessionState, last_ms: int, out: list[Emitted]) -> None:
        hold = s.hold
        assert hold is not None
        if last_ms != hold.stale_ms:
            self.stats.count("lap_time_late")
            self._flush_hold(s, out, last_ms if last_ms > 0 else None)
        elif hold.ticks_left <= 0:
            self.stats.count("lap_time_missing")
            self._flush_hold(s, out, None)
        else:
            hold.ticks_left -= 1

    @staticmethod
    def _flush_hold(s: _SessionState, out: list[Emitted], lap_time_ms: int | None) -> None:
        hold = s.hold
        assert hold is not None
        hold.completion.lap_time_ms = lap_time_ms
        out.append(hold.completion)
        out.extend(hold.items)
        s.hold = None

    # ------------------------------------------------------------------ normalisation
    def _steering(self, v: P.Variant, p: dict[str, Any]) -> float | None:
        if v.name == "A":
            return None  # steering exists only from variant B (game >= 1.42)
        rot: float = p["wheel_rotation_rad"]
        if not math.isfinite(rot):
            return None
        if v.name == "C":
            road = 0.5 * (p["fl_steer_rad"] + p["fr_steer_rad"])  # documented: left positive
            if abs(road) > 0.02 and abs(rot) > 0.05:
                if (road > 0) == (rot > 0):
                    self._steer_agree += 1
                else:
                    self._steer_disagree += 1
        return max(-1.0, min(1.0, self.steering_sign * rot / STEER_HALF_LOCK_RAD))

    def _frame(self, v: P.Variant, p: dict[str, Any], flags: P.Flags, s: _SessionState, t: int, pid: int) -> CarFrame:
        lap_raw: int = p["lap_count"]
        total: int = p["total_laps"]
        q = FrameQuality.OK
        if flags & P.Flags.PAUSED:
            q |= FrameQuality.PAUSED
        if not flags & P.Flags.CAR_ON_TRACK or lap_raw < 1 or s.cooldown or (total > 0 and lap_raw > total):
            q |= FrameQuality.NOT_RACING
        speed: float = p["speed"]
        px, py, pz = p["position"]
        vx, vy, vz = p["velocity"]
        last_ms: int = p["last_lap_ms"]
        pre_pos: int = p["pre_race_position"]
        rev_max: int = p["rev_alert_max_rpm"]
        temps: tuple[float, ...] = p["tyre_surface_temp"]
        if v.name == "C" and p["current_lap_ms"] >= 0:
            cur_ms: int | None = p["current_lap_ms"]
        elif s.dist_m is not None:
            cur_ms = round(s.lap_elapsed_s * 1000.0)
        else:
            cur_ms = None
        return CarFrame(
            game=Game.GT7,
            t_recv_ns=t,
            session_time_s=self._clock_s,
            frame_id=pid,
            quality=q,
            throttle=(p["throttle_alt"] if v.name in ("~", "C") else p["throttle"]) / 255.0,  # the pedal
            brake=p["brake"] / 255.0,
            steering=self._steering(v, p),
            clutch=_fin(p["clutch_pedal"]),
            speed_kph=abs(speed) * 3.6,
            gear=_gear(p["gears"]),
            rpm=_fin(p["engine_rpm"]),
            max_rpm=float(rev_max) if rev_max > 0 else None,
            pos_x_m=px,
            pos_y_m=py,
            pos_z_m=pz,
            vel_x_mps=vx,
            vel_y_mps=vy,
            vel_z_mps=vz,
            lap_number=lap_raw if lap_raw >= 1 else None,
            lap_distance_m=s.dist_m,
            current_lap_time_ms=cur_ms,
            last_lap_time_ms=last_ms if last_ms > 0 else None,
            race_position=pre_pos if pre_pos >= 1 else None,
            tyre_surface_temp_c=Wheels.from_fl_fr_rl_rr(temps) if all(math.isfinite(x) for x in temps) else None,
            # fuel_litres / fuel_capacity_litres: unit conflicting (see the module docstring) - left unknown
        )

    # ------------------------------------------------------------------ session info
    def _info_key(self, s: _SessionState) -> tuple[Any, ...]:
        v, p, _ = self._pkt
        return (
            s.uid,
            s.track.track_id if s.track else None,
            s.track_length_m,
            p["car_code"],
            p["total_laps"],
            v.name,
        )

    def _emit_session_info(self, s: _SessionState, t: int, out: list[Emitted]) -> None:
        v, p, flags = self._pkt
        s.info_key = self._info_key(s)
        s.info_countdown = SESSION_INFO_EVERY
        car_code: int = p["car_code"]
        total: int = p["total_laps"]
        best: int = p["best_lap_ms"]
        level: float = p["fuel_level"]
        capacity: float = p["fuel_capacity"]
        track = s.track
        extra: dict[str, Any] = {
            "packet_variant": v.name,
            "best_lap_ms": best if best > 0 else None,
            "time_of_day_ms": p["time_of_day_ms"],
            "game_paused": bool(flags & P.Flags.PAUSED),
            "track_id_derived": True,
            "num_cars_pre_race": p["num_cars_pre_race"] if p["num_cars_pre_race"] > 0 else None,
            "calc_max_speed_kph": p["calc_max_speed_kph"] if p["calc_max_speed_kph"] > 0 else None,
            # level / capacity is unitless whichever unit 0x44/0x48 turn out to use; None for EVs (capacity 0)
            "fuel_fraction": (
                level / capacity if capacity > 0 and math.isfinite(level) and math.isfinite(capacity) else None
            ),
        }
        if track is not None:
            extra["track_turn_deg"] = track.turn_deg
            extra["track_length_nominal_m"] = track.length_m
        if v.name == "C":
            extra["car_category"] = _ascii(p["car_category"])
        if s.synthetic:
            extra["synthetic"] = True
        out.append(
            SessionInfo(
                game=Game.GT7,
                t_recv_ns=t,
                platform=Platform.UNKNOWN,  # PS4 and PS5 send identical packets
                session_uid=s.uid,
                track_id=track.track_id if track else None,
                track_name=f"Unidentified GT7 circuit ({track.length_m / 1000:.2f} km)" if track else None,
                track_length_m=s.track_length_m if track else None,
                session_type=SessionType.UNKNOWN,
                total_laps=total if total > 0 else None,
                car_id=f"gt7:car:{car_code}" if car_code != 0 else None,
                extra=extra,
            )
        )
