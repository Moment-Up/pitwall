"""Decode a ``FieldMotion`` for every car, and every car's position relative to the player (worker thread).

Decoding uses ``adapters.f1.adapter.subset_struct`` over the spec-checked ``StructDef``s (never hand-written offsets):
one ``iter_unpack`` C loop per array. Fields are unpacked in the struct's *definition* order and looked up by name.

Geometry (spec section 3.2), in the player's frame:

* ``f = worldForwardDir / 32767`` and ``r = worldRightDir / 32767`` (EA: divide the int16 by 32767). On the owner's
  PS5 F1 25 races ``worldRightDir`` is the driver's RIGHT (it agreed with the steering sign on 87-99.9% of samples)
  and ``f x r`` points down, so ``u = r x f`` is up (handedness-safe; ``analysis/track_geometry.py``: F1's X/Z plane
  is mirrored).
* For each other car j: ``d = p_j - p_player``; ``lon = d.f`` (+ ahead), ``lat = d.r`` (+ right), ``vert = d.u``.
* ``vr`` and ``vl`` are how fast ``lon`` and ``lat`` change in the player's frame, which turns with the player:
  ``vr = (v_j - v_p).f + d.(df/dt)`` and ``vl = (v_j - v_p).r + d.(dr/dt)``. The rotation terms come from the
  player's vectors in the previous packet on the game clock (``prev``, at most ``ROT_MAX_DT_S`` earlier). Without
  them, two cars holding a constant gap through a corner read as closing at (yaw rate x lon): against finite
  differences of ``lat`` on the owner's races the error was 0.63 m/s at the median and 3.7 m/s at p90, with them
  0.02 and 0.16 (docs/research/f1-spotter-data.md). With no usable previous packet (the first packet, a gap, a
  rewind) the terms are left out.
* Every car is the same ``L x W`` rectangle, oriented by its own vectors: ``ext_lon = L/2 |f_j.f| + W/2 |r_j.f|``,
  ``ext_lat = L/2 |f_j.r| + W/2 |r_j.r|``; the bodies overlap lengthwise when ``|lon| < reach = L/2 + ext_lon``,
  and ``gap = |lat| - W/2 - ext_lat`` is the side-to-side clearance.

A packet whose player vectors are not unit length (|f| or |r| outside [0.95, 1.05]) or not finite is invalid; a car
whose own vectors are not unit length (an empty slot sends zeros) is ignored: unknown, never a guess.
Obstacles: LapData resultStatus active (2) or finished (3, cool-down laps are on track), driverStatus not garage (0),
pitStatus 0 (not in the pit lane) and ``|vert| < vert_max_m`` (crossover bridges).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from pitwall.adapters.f1 import packets as P
from pitwall.adapters.f1.adapter import subset_struct
from pitwall.model.telemetry import FieldMotion
from pitwall.spotter.model import DecodedMotion

DIR_SCALE = 32767.0  # EA spec: "divide by 32767.0f" for the normalised int16 direction vectors
VECTOR_MIN, VECTOR_MAX = 0.95, 1.05
ROT_MIN_DT_S, ROT_MAX_DT_S = 1e-3, 0.25  # the frame's rotation from two packets this far apart (game clock)

MOTION_FIELDS = (
    "worldPositionX",
    "worldPositionY",
    "worldPositionZ",
    "worldVelocityX",
    "worldVelocityY",
    "worldVelocityZ",
    "worldForwardDirX",
    "worldForwardDirY",
    "worldForwardDirZ",
    "worldRightDirX",
    "worldRightDirY",
    "worldRightDirZ",
)
LAP_FIELDS = ("pitStatus", "driverStatus", "resultStatus")
RESULT_ACTIVE, RESULT_FINISHED = 2, 3
DRIVER_IN_GARAGE = 0


def _order(sd_fields: Sequence[tuple[str, str]], keep: tuple[str, ...]) -> list[int]:
    """Index of each ``keep`` name in the tuple ``subset_struct`` unpacks (definition order)."""
    defined = [name for name, _ in sd_fields if name in keep]
    return [defined.index(name) for name in keep]


class _Structs:
    __slots__ = ("lap", "lap_order", "lap_size", "max_cars", "motion", "motion_order", "motion_size")

    def __init__(self, layout: P.F1Layout) -> None:
        self.max_cars = layout.max_cars
        self.motion = subset_struct(layout.car_motion, MOTION_FIELDS)
        self.motion_order = _order(layout.car_motion.fields, MOTION_FIELDS)
        self.lap = subset_struct(P.LAP_DATA, LAP_FIELDS)
        self.lap_order = _order(P.LAP_DATA.fields, LAP_FIELDS)
        self.motion_size = layout.sizes[P.PacketId.MOTION]
        self.lap_size = layout.sizes[P.PacketId.LAP_DATA]


_STRUCTS: dict[int, _Structs] = {fmt: _Structs(layout) for fmt, layout in P.LAYOUTS.items()}
_IDENTITY = list(range(len(MOTION_FIELDS)))


def decode(fm: FieldMotion) -> DecodedMotion | None:
    """Every car's motion and LapData statuses. None when the packet does not have its format's exact size."""
    s = _STRUCTS.get(fm.packet_format)
    if s is None or len(fm.motion) != s.motion_size:
        return None
    base = P.HEADER.size
    rows = s.motion.iter_unpack(fm.motion[base : base + s.max_cars * s.motion.size])
    mo = s.motion_order  # the identity for EA's layout: positions, velocities, forward, right
    cars = tuple(rows) if mo == _IDENTITY else tuple(tuple(r[i] for i in mo) for r in rows)
    status: tuple[tuple[int, int, int], ...] | None = None
    lap = fm.lap
    if lap is not None and len(lap) == s.lap_size:
        lo = s.lap_order
        status = tuple(
            (int(r[lo[0]]), int(r[lo[1]]), int(r[lo[2]]))
            for r in s.lap.iter_unpack(lap[base : base + s.max_cars * s.lap.size])
        )
    return DecodedMotion(
        t_recv_ns=fm.t_recv_ns,
        session_time_s=float(fm.session_time_s),
        frame_id=fm.frame_id,
        player_index=fm.player_index,
        packet_format=fm.packet_format,
        cars=cars,
        status=status,
    )


@dataclass(slots=True, frozen=True)
class Basis:
    """The player's frame: forward, right and up unit vectors, position, velocity and speed."""

    f: tuple[float, float, float]
    r: tuple[float, float, float]
    u: tuple[float, float, float]
    p: tuple[float, float, float]
    v: tuple[float, float, float]
    speed_kph: float


@dataclass(slots=True)
class Rel:
    """One other car relative to the player (metres, m/s)."""

    idx: int
    lon: float  # + ahead
    lat: float  # + right
    vert: float  # + above
    reach: float  # bodies overlap lengthwise when |lon| < reach
    gap: float  # side-to-side clearance (negative = the boxes overlap sideways)
    vr: float  # d lon / dt in the player's turning frame (+ the other car moves ahead)
    vl: float  # d lat / dt in the player's turning frame (+ the other car moves to the player's right)
    obstacle: bool  # racing on track (status filters) and not above/below (bridges)


def _unit_ok(x: float, y: float, z: float) -> bool:
    n = math.sqrt(x * x + y * y + z * z)
    return VECTOR_MIN <= n <= VECTOR_MAX  # NaN fails both comparisons


def basis(row: tuple[float, ...]) -> Basis | None:
    """The player's frame from its Motion row; None when its vectors are not unit length or values not finite."""
    if not all(math.isfinite(v) for v in row):
        return None
    fx, fy, fz = row[6] / DIR_SCALE, row[7] / DIR_SCALE, row[8] / DIR_SCALE
    rx, ry, rz = row[9] / DIR_SCALE, row[10] / DIR_SCALE, row[11] / DIR_SCALE
    if not (_unit_ok(fx, fy, fz) and _unit_ok(rx, ry, rz)):
        return None
    u = (ry * fz - rz * fy, rz * fx - rx * fz, rx * fy - ry * fx)  # r x f: up on real data (f x r points down)
    vx, vy, vz = row[3], row[4], row[5]
    return Basis(
        (fx, fy, fz),
        (rx, ry, rz),
        u,
        (row[0], row[1], row[2]),
        (vx, vy, vz),
        math.sqrt(vx * vx + vy * vy + vz * vz) * 3.6,
    )


def relative(
    m: DecodedMotion,
    length_m: float,
    width_m: float,
    vert_max_m: float = 3.0,
    prev: tuple[float, Basis] | None = None,
) -> tuple[Basis | None, list[Rel]]:
    """The player's basis and every other valid car relative to it (cars with invalid vectors are left out).
    ``prev``: (session time, basis) of the player in the previous packet, for the frame's rotation (module doc)."""
    cars = m.cars
    pi = m.player_index
    if pi >= len(cars):
        return None, []
    b = basis(cars[pi])
    if b is None:
        return None, []
    fx, fy, fz = b.f
    rx, ry, rz = b.r
    dfx = dfy = dfz = drx = dry = drz = 0.0
    if prev is not None:
        dt = m.session_time_s - prev[0]
        if ROT_MIN_DT_S < dt <= ROT_MAX_DT_S:
            (pfx, pfy, pfz), (prx, pry, prz) = prev[1].f, prev[1].r
            dfx, dfy, dfz = (fx - pfx) / dt, (fy - pfy) / dt, (fz - pfz) / dt
            drx, dry, drz = (rx - prx) / dt, (ry - pry) / dt, (rz - prz) / dt
    ux, uy, uz = b.u
    px, py, pz = b.p
    pvx, pvy, pvz = b.v
    half_l, half_w = length_m / 2.0, width_m / 2.0
    status = m.status
    out: list[Rel] = []
    for j, c in enumerate(cars):
        if j == pi:
            continue
        ofx, ofy, ofz = c[6] / DIR_SCALE, c[7] / DIR_SCALE, c[8] / DIR_SCALE
        orx, ory, orz = c[9] / DIR_SCALE, c[10] / DIR_SCALE, c[11] / DIR_SCALE
        if not (_unit_ok(ofx, ofy, ofz) and _unit_ok(orx, ory, orz)):
            continue  # an empty slot (zeros) or a broken row: unknown, ignored
        dx, dy, dz = c[0] - px, c[1] - py, c[2] - pz
        dvx, dvy, dvz = c[3] - pvx, c[4] - pvy, c[5] - pvz
        if not all(math.isfinite(v) for v in (dx, dy, dz, dvx, dvy, dvz)):
            continue
        lon = dx * fx + dy * fy + dz * fz
        lat = dx * rx + dy * ry + dz * rz
        vert = dx * ux + dy * uy + dz * uz
        ext_lon = half_l * abs(ofx * fx + ofy * fy + ofz * fz) + half_w * abs(orx * fx + ory * fy + orz * fz)
        ext_lat = half_l * abs(ofx * rx + ofy * ry + ofz * rz) + half_w * abs(orx * rx + ory * ry + orz * rz)
        obstacle = abs(vert) < vert_max_m
        if obstacle:
            if status is None or j >= len(status):
                obstacle = False  # no LapData: whether it is racing is unknown
            else:
                pit, drv, res = status[j]
                obstacle = res in (RESULT_ACTIVE, RESULT_FINISHED) and drv != DRIVER_IN_GARAGE and pit == 0
        out.append(
            Rel(
                j,
                lon,
                lat,
                vert,
                half_l + ext_lon,
                abs(lat) - half_w - ext_lat,
                dvx * fx + dvy * fy + dvz * fz + dx * dfx + dy * dfy + dz * dfz,
                dvx * rx + dvy * ry + dvz * rz + dx * drx + dy * dry + dz * drz,
                obstacle,
            )
        )
    return b, out


def pack_row(values: tuple[float, ...], packet_format: int = P.PACKET_FORMAT_2025) -> bytes:
    """One car's Motion row with the 12 spotter fields set (others zero): tests and synthetic scenarios."""
    sd = P.LAYOUTS[packet_format].car_motion
    out: dict[str, object] = {}
    for name, v in zip(MOTION_FIELDS, values, strict=True):
        out[name] = round(v) if name.startswith(("worldForward", "worldRight")) else float(v)
    return sd.pack(out)
