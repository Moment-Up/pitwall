"""Gran Turismo 7 adapter: decrypts, validates and normalises Simulator Interface packets.

Source: docs/research/gt7-protocol.md (community reverse-engineering, no official spec), so every decoded field
is at most ``COMMUNITY_DOCUMENTED`` until a real capture or live session validates it.

GT7 sends one self-contained packet per simulation tick (~60 Hz), so unlike F1 there is nothing to merge:
every packet becomes one ``CarFrame``. What GT7 does *not* send is reconstructed here, deterministically and
with documented provenance (``AdapterInfo.fields`` marks each as derived):

* **Tick clock** (``session_time_s``): packet-id deltas x 1/60 s, advanced only while the simulation runs (not
  while paused), so a pause never looks like packet loss to the lap assembler. Lost packets show up as a time
  gap, exactly as with a real game clock. A packet whose speed, position or velocity is not finite is dropped
  and bridged exactly like a lost packet (one bad value must not poison a lap's distance or the track id).
* **Lap distance** (``lap_distance_m``): trapezoidal integration of the reported speed over tick time,
  reset to 0 at each start/finish crossing. It is emitted only while *anchored* - i.e. after a line crossing
  was observed while moving with continuous packets. Joining mid-lap, a race start (standing: the grid offset
  to the line is unknown; rolling: the release point may not be the line), a teleport (car reset to track) or a
  stream gap of more than 5 s leave the distance ``None`` until the next crossing: unknown stays unknown.
  Leaving the out-lap (lap 0 -> 1 while moving, no race) on a track whose line is not yet known anchors
  *provisionally*; the next crossing reveals the line, and a lap that did not start on it is completed with
  ``valid=False`` so its misaligned trace can never become a reference or train a track model. Likewise a lap
  that *loses* its anchor part-way (gap, teleport) is completed with ``valid=False``: its trace stops at the
  discontinuity, and before the track length is known nothing downstream could tell it from a complete lap.
  A counter increment away from the learned line does not anchor the next lap either.
  Accuracy: exact to <0.1 % on synthetic streams; on real data expect ~1 % drift (speed vs. path length,
  nominal tick period). The error is systematic per track, and the track length is learned with the same
  integration, so laps on the same track stay mutually comparable.
* **Current lap time** for variants A/B/~: ticks since the anchor (variant C reports the game's own timer).
* **Lap completion**: the lap counter incrementing from >= 1 (doc section 9), timed by ``last_lap_ms``. If
  ``last_lap_ms`` has not updated in the same packet, frames are held for up to ``LAST_LAP_HOLD_TICKS`` so the
  completion still precedes the next lap's frames (``LapAssembler`` needs that order). A ``last_lap_ms`` update
  *without* a counter increment that matches the derived lap time completes the current lap (a final race lap
  that does not advance the counter - the F1 25 lesson - or a timer leading the counter by a tick); frames are
  then ``NOT_RACING`` until the counter changes.
* **Track identity**: GT7 has no track id; see ``TrackSignature``. Every anchored lap is measured (length and
  total turning). A lap matching a known signature (the registry: ``known_track_ids`` from the database plus
  tracks learned by this process) identifies the track - a lap with small, bridged packet gaps is good enough
  for that. A *new* track is learned only from two gap-free laps that agree closely, so one odd lap (a spin, an
  excursion, a pit lane) can never define a track. The published ``track_length_m`` is this session's own
  measurement - the shorter of the identifying lap(s) and the registry length - never the registry length
  alone: ``LapAssembler`` calls a lap incomplete when it ends short of that length, so an over-estimate would
  disqualify every lap on the circuit. Synthetic sessions never add to the registry. Track *names* are unknown
  (``track_name`` is a descriptive label).
* **Session boundaries**: GT7 has no session uid. A new session starts after a load (``LOADING`` flag), on a
  car change, on a retry without a load - the lap counter going backwards, the time of day rewinding by 10 s or
  more, or the packet id restarting (doc section 9's retry detector) - and on ``reset()``. Its uid is
  ``gt7:<t_recv_ns of its first packet>``, deterministic on replay, so a re-driven lap 1 never overwrites the
  earlier lap 1 of the same database session. (Synthetic streams all carry the generator's fixed uid, which the
  session manager uses to flag them, so retries inside one synthetic stream stay in one stored session.)
* **Fuel**: the unit of 0x44/0x48 is conflicting in the doc (litres per PDTools, percent per GT7Eng; the
  capacity is 100 for most cars), so ``fuel_litres`` stays ``None``; the unitless level / capacity goes out as
  ``SessionInfo.extra['fuel_fraction']``.

Steering (B/~/C): the wheel angle at 0x128 is in radians with an unverified sign. It is normalised to -1..+1 by
a nominal +/-450 deg half-lock (magnitude approximate) assuming the documented road-wheel convention (left
positive, doc section 7); on variant C the sign is cross-checked against the road-wheel angles at 0x160/0x164
and flipped if they consistently disagree.
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
    FrameQuality,
    Game,
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
_U = SupportLevel.UNSUPPORTED
_DERIVED = "derived by integration; drifts ~1%"

GT7_INFO = AdapterInfo(
    game=Game.GT7,
    name="Gran Turismo 7 (Simulator Interface, variants A/B/~/C)",
    transport="udp (encrypted, Salsa20; heartbeat to console UDP 33739)",
    default_port=P.RECEIVE_PORT,
    ground_plane=("pos_x_m", "pos_z_m"),  # Y is up (doc section 4)
    platforms={Platform.PS5: _C, Platform.PS4: _C},
    fields={
        "speed_kph": FieldSupport(_C, "0x4C speed (m/s, abs) x 3.6"),
        "throttle": FieldSupport(_C, "0x91 throttle 0..255 -> 0..1 (input vs post-TCS output unverified)"),
        "brake": FieldSupport(_C, "0x92 brake 0..255 -> 0..1"),
        "clutch": FieldSupport(_C, "0xF4 clutch pedal 0..1"),
        "gear": FieldSupport(_C, "0x90 low nibble 1..14; 0/15 (R/N encoding unverified) -> None"),
        "rpm": FieldSupport(_C, "0x3C engine RPM"),
        "max_rpm": FieldSupport(_C, "0x8A rev-limiter alert max RPM (approximates the limiter)"),
        "steering": FieldSupport(
            _C,
            "B/~/C 0x128 wheel angle (rad) / nominal 450 deg half-lock; sign assumed left-positive, "
            "cross-checked against C road-wheel angles. Not in variant A",
        ),
        "pos_x_m": FieldSupport(_C, "0x04 position X (m)"),
        "pos_y_m": FieldSupport(_C, "0x08 position Y (m, up axis)"),
        "pos_z_m": FieldSupport(_C, "0x0C position Z (m)"),
        "vel_x_mps": FieldSupport(_C, "0x10..0x18 world velocity (m/s)"),
        "session_time_s": FieldSupport(_C, "derived: packet-id ticks x 1/60 s while not paused"),
        "frame_id": FieldSupport(_C, "0x70 packet id"),
        "lap_number": FieldSupport(_C, "0x74 lap count (0 = not in a timed lap -> None)"),
        "lap_distance_m": FieldSupport(_C, f"{_DERIVED}; speed x tick time since the last line crossing"),
        "current_lap_time_ms": FieldSupport(_C, "C: 0x15C; A/B/~: derived from ticks since the line crossing"),
        "last_lap_time_ms": FieldSupport(_C, "0x7C last lap (ms; -1 -> None)"),
        "race_position": FieldSupport(_C, "0x84 when >= 1 (conflicting: pre-race grid position vs live position)"),
        "tyre_surface_temp_c": FieldSupport(_C, "0x60..0x6C surface temps, native FL, FR, RL, RR order"),
        "fuel_litres": FieldSupport(
            SupportLevel.UNVERIFIED,
            "0x44 fuel level, unit conflicting (litres per PDTools, % per GT7Eng): not emitted until a capture "
            "settles it; SessionInfo.extra['fuel_fraction'] = level / capacity",
        ),
        "fuel_capacity_litres": FieldSupport(
            SupportLevel.UNVERIFIED, "0x48 fuel capacity, unit conflicting (100 most cars, 5 karts, 0 EVs)"
        ),
        "track_id": FieldSupport(
            _C,
            "derived heuristic: start/finish position + heading + integrated lap length + total turning; layouts "
            "differing by < 1.5 % length and < 40 deg turning can still merge (unvalidated on real data)",
        ),
        "track_length_m": FieldSupport(
            _C, f"{_DERIVED}; this session's identifying lap(s), never longer than the registry's length"
        ),
        "car_id": FieldSupport(_C, "0x124 car code (corrupted for cars with 9+ gears)"),
        "total_laps": FieldSupport(_C, "0x76 (0 for timed races / free runs -> None)"),
        "best_lap_ms": FieldSupport(_C, "0x78, SessionInfo.extra (GT7Eng: unstable in the raw packet)"),
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
    },
    notes=(
        "Community-documented protocol (docs/research/gt7-protocol.md); not yet validated on a real console.",
        "No lap distance in the protocol: integrated from speed x tick time; drifts ~1 %, unanchored until the "
        "first start/finish crossing seen while moving (race lap 1 after a standing start has no distance).",
        "No track id: derived from the start/finish crossing position and direction, the lap length and the "
        "lap's total turning - a heuristic that separates chicane / no-chicane layouts on synthetic data but is "
        "unvalidated on real circuits. A new circuit is learned from two agreeing laps.",
        "Retries without a loading screen (lap counter reset, time-of-day rewind, packet-id restart) start a "
        "new session.",
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
    speed_mps: float
    pos: tuple[float, float, float]
    pid: int  # packet id, so a dropped packet is bridged exactly like a lost one


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
    hold: _Hold | None = None
    info_key: tuple[Any, ...] | None = None
    info_countdown: int = 0


def _gear(byte: int) -> int | None:
    g = byte & 0x0F
    return g if 1 <= g <= 14 else None  # 0 / 15: reverse / neutral encoding unverified (doc section 4.2)


def _ascii(raw: bytes) -> str | None:
    s = raw.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()
    return s or None


def _heading_deg(vx: float, vz: float) -> float:
    return math.degrees(math.atan2(vx, vz)) % 360.0


def _fin(v: float) -> float | None:
    return v if math.isfinite(v) else None


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
        self._prev_tod: int | None = None
        self._last_t_recv_ns: int | None = None
        self._loading = False
        self._car_code: int | None = None
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
            if self._step(variant, P.unpack(variant, plain), t_recv_ns, out):
                self.stats.decoded += 1
            else:
                self.stats.ignored += 1
        except Exception as e:  # never let one bad packet kill the stream
            self.stats.errors += 1
            self.stats.last_error = f"{variant.name}: {e!r}"
            log.exception("GT7 decode error (variant %s)", variant.name)
        return out

    # ------------------------------------------------------------------ per-packet state machine
    def _step(self, v: P.Variant, p: dict[str, Any], t: int, out: list[Emitted]) -> bool:
        """Advance the stream state by one packet. Returns False when the packet is deliberately dropped."""
        pid: int = p["packet_id"]
        flags = P.Flags(p["flags"] & 0x0FFF)
        self._pkt = (v, p, flags)

        # 1. packet ordering (doc section 3.9): duplicates / out-of-order packets are dropped; an id far behind the
        #    last one means the stream restarted (reconnect or retry: a new session, see 3.)
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

        # 2. loading screens: no meaningful car data; the next session starts once loading ends
        if flags & P.Flags.LOADING_OR_PROCESSING:
            self._loading = True
            self._prev = None
            self.stats.count("loading")
            return False

        # 3. session boundaries (no session uid in GT7: loads, car changes and retries delimit sessions)
        car_code: int = p["car_code"]
        lap_raw: int = p["lap_count"]
        tod: int = p["time_of_day_ms"]
        car_changed = self._car_code not in (None, 0) and car_code not in (0, self._car_code)
        retry = None if self._s is None or self._loading else self._retry_reason(self._s, lap_raw, tod, restarted)
        if self._s is None or self._loading or car_changed or retry is not None:
            if retry is not None:
                self.stats.count(retry)
                log.info("GT7 %s: starting a new session", retry)
            self._start_session(t, p["reserved"] == P.SYNTHETIC_MARKER, out)
        self._loading = False
        self._car_code = car_code
        if 0 < tod < DAY_MS:
            self._prev_tod = tod
        s = self._s
        assert s is not None

        # 3b. corrupt motion: dropped and bridged like a lost packet (the next packet integrates across it)
        speed: float = p["speed"]
        pos: tuple[float, float, float] = p["position"]
        vel: tuple[float, float, float] = p["velocity"]
        if not all(math.isfinite(x) for x in (speed, *pos, *vel)):
            self.stats.count("non_finite_motion")
            return False

        # 4. a completion waiting for last_lap_ms (released before anything of this packet is emitted)
        last_ms: int = p["last_lap_ms"]
        hold_was_active = s.hold is not None
        if hold_was_active:
            self._service_hold(s, last_ms, out)

        # 5. slow-changing session context (~2 Hz and on change), ahead of this packet's frame so the first
        #    frame of a new session never lands in the previous one
        s.info_countdown -= 1
        if s.info_countdown <= 0 or self._info_key(s) != s.info_key:
            self._emit_session_info(s, t, out)

        # 6. tick clock + distance integration
        running = not flags & P.Flags.PAUSED
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
                if disp > 1.5 * max(abs(speed), abs(prev.speed_mps)) * dt + TELEPORT_SLACK_M:
                    self.stats.count("teleport")
                    self._unanchor(s, lost=True)
                else:
                    s.dist_m += 0.5 * (speed + prev.speed_mps) * dt
                    s.lap_elapsed_s += dt
                    s.max_gap_ticks = max(s.max_gap_ticks, ticks)
                    self._sample_turn(s, speed, vel)

        # 7. lap counter transitions / completions
        crossing = prev is not None and gap <= CROSSING_GAP_TICKS and abs(speed) >= ANCHOR_MIN_SPEED_MPS
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

        # 8. the frame itself
        frame = self._frame(v, p, flags, s, t, pid)
        if s.hold is not None:
            s.hold.items.append(frame)
        else:
            out.append(frame)

        self._prev = _Motion(running=bool(running), speed_mps=speed, pos=pos, pid=pid)
        self._prev_last_ms = last_ms
        self._last_t_recv_ns = t
        return True

    # ------------------------------------------------------------------ sessions
    def _retry_reason(self, s: _SessionState, lap_raw: int, tod: int, restarted: bool) -> str | None:
        """Doc section 9 (GT7Eng's retry detector): a retry / restart without a loading screen. Treated as a new
        session so the re-driven laps (same lap numbers) never replace the earlier ones in storage."""
        if restarted:
            return "retry_stream_restart"
        if s.lap is not None and lap_raw < s.lap:
            return "retry_lap_reset"
        prev_tod = self._prev_tod
        if prev_tod is not None and 0 < tod < DAY_MS and RETRY_TOD_REWIND_MS <= prev_tod - tod < TOD_WRAP_MS:
            return "retry_time_rewind"
        return None

    def _start_session(self, t: int, synthetic: bool, out: list[Emitted]) -> None:
        old = self._s
        if old is not None and old.hold is not None:
            self._flush_hold(old, out, None)  # the old session's completion never got its time
        uid = str(SYNTHETIC_SESSION_UID) if synthetic else f"gt7:{t}"
        self._s = _SessionState(uid=uid, synthetic=synthetic)
        self._prev = None
        self.stats.count("sessions")

    # ------------------------------------------------------------------ distance anchoring
    @staticmethod
    def _unanchor(s: _SessionState, *, lost: bool = False) -> None:
        """Forget the anchor. ``lost=True``: a discontinuity inside the current lap (its trace is truncated if it
        was anchored); ``lost=False``: a lap boundary, after which the new lap simply starts unanchored."""
        if not lost:
            s.anchor_lost = False
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
        # anything else: lap 0 -> 1, or laps skipped during a gap (a counter going back is a new session, see
        # _retry_reason, so it never gets here)
        self.stats.count("lap_reset" if lap <= prev_lap else "lap_start")
        near = self._near_known_line(s, pos[0], pos[2], heading) if lap >= 1 and crossing else False
        is_race = self._pkt[1]["total_laps"] > 0
        if near is True:
            self._anchor(s, pos, heading, confirmed=True)
        elif near is None and not is_race:
            # Unknown line on a time trial / free run: leaving the out-lap (lap 0) is a line crossing. Provisional
            # until the next crossing reveals where the line is.
            self._anchor(s, pos, heading, confirmed=False)
        else:
            # standing start (stopped), a race start (rolling starts may release away from the line), a reset
            # or a gap: the offset to the line is unknown
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
        gap-free laps. Publishes the result (SessionInfo) when the track becomes known."""
        if s.track is not None:
            return
        assert s.sf is not None
        if not MIN_TRACK_LENGTH_M <= shape.length_m <= MAX_TRACK_LENGTH_M:
            self.stats.count("implausible_lap_length")
            return
        sx, sz, sh = s.sf
        cand = TrackSignature.measured(sx, sz, sh, shape.length_m, shape.turn_deg)
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
            throttle=p["throttle"] / 255.0,
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
