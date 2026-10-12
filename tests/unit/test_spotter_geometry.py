"""Spotter decoding and geometry with the real spec-checked structs, formats 2025 (60 B per car) and 2026 (54 B)."""

from __future__ import annotations

import dataclasses
import math

import pytest

from pitwall.adapters.f1 import packets as P
from pitwall.model.telemetry import FieldMotion, Game
from pitwall.spotter.geometry import decode, pack_row, relative
from tests.unit.spotter_helpers import row

L, W = 5.5, 2.0


def _packet(fmt: int, rows: dict[int, tuple[float, ...]], player: int = 0) -> bytes:
    lay = P.LAYOUTS[fmt]
    hdr = P.HEADER.pack({"packetFormat": fmt, "packetId": 0, "sessionTime": 12.5, "playerCarIndex": player})
    cars = [pack_row(rows[i], fmt) if i in rows else lay.car_motion.pack({}) for i in range(lay.max_cars)]
    return hdr + b"".join(cars)


def _lap(fmt: int, status: dict[int, tuple[int, int, int]]) -> bytes:
    lay = P.LAYOUTS[fmt]
    hdr = P.HEADER.pack({"packetFormat": fmt, "packetId": 2})
    rows = [
        P.LAP_DATA.pack(
            {"pitStatus": status[i][0], "driverStatus": status[i][1], "resultStatus": status[i][2]}
            if i in status
            else {}
        )
        for i in range(lay.max_cars)
    ]
    return hdr + b"".join(rows) + P.LAP_DATA_TAIL.pack({})


def _fm(fmt: int, rows: dict[int, tuple[float, ...]], status: dict[int, tuple[int, int, int]] | None) -> FieldMotion:
    data = _packet(fmt, rows)
    assert len(data) == P.LAYOUTS[fmt].sizes[P.PacketId.MOTION]
    return FieldMotion(
        game=Game.F1_25,
        t_recv_ns=123,
        session_time_s=12.5,
        frame_id=750,
        player_index=0,
        packet_format=fmt,
        motion=data,
        lap=None if status is None else _lap(fmt, status),
    )


ON = (0, 4, 2)


@pytest.mark.parametrize("fmt", [2025, 2026])
def test_decode_both_formats_by_field_name(fmt: int) -> None:
    rows = {0: row(10.0, 1.0, 20.0, 0.0, 0.0, 50.0, 0.0), 5: row(7.0, 1.5, 21.0, 1.0, 0.5, 52.0, 30.0)}
    m = decode(_fm(fmt, rows, {0: ON, 5: (1, 3, 3)}))
    assert m is not None and m.packet_format == fmt and len(m.cars) == P.LAYOUTS[fmt].max_cars
    assert m.cars[5][:6] == pytest.approx((7.0, 1.5, 21.0, 1.0, 0.5, 52.0))
    assert m.cars[5][6:] == pytest.approx(rows[5][6:])
    assert m.status is not None and m.status[5] == (1, 3, 3) and m.status[0] == ON
    assert m.session_time_s == 12.5 and m.t_recv_ns == 123


def test_decode_rejects_a_wrong_size_and_keeps_lap_unknown() -> None:
    fm = _fm(2025, {0: row(0, 0, 0, 0, 0, 50, 0)}, None)
    m = decode(fm)
    assert m is not None and m.status is None
    bad = FieldMotion(
        game=Game.F1_25,
        t_recv_ns=0,
        session_time_s=0.0,
        frame_id=0,
        player_index=0,
        packet_format=2025,
        motion=fm.motion[:-1],
        lap=None,
    )
    assert decode(bad) is None


@pytest.mark.parametrize("heading_deg", [0.0, 37.0, 180.0, -100.0])
def test_lon_lat_signs_right_is_the_drivers_right_and_up_is_r_cross_f(heading_deg: float) -> None:
    """The player heads ``heading_deg``; a car 5 m ahead and 3 m to the driver's right in the player's own frame."""
    h = math.radians(heading_deg)
    f = (math.sin(h), 0.0, math.cos(h))
    r = (-math.cos(h), 0.0, math.sin(h))  # the real game's convention: f x r points down
    p = (100.0, 2.0, -50.0)
    other = tuple(p[k] + 5.0 * f[k] + 3.0 * r[k] for k in range(3))
    rows = {
        0: row(*p, 40 * f[0], 0.0, 40 * f[2], heading_deg),
        1: row(*other, 42 * f[0], 0.0, 42 * f[2], heading_deg),
    }
    m = decode(_fm(2025, rows, {0: ON, 1: ON}))
    assert m is not None
    b, rels = relative(m, L, W)
    assert b is not None
    assert b.u == pytest.approx((0.0, 1.0, 0.0), abs=1e-4)  # r x f is up
    assert b.speed_kph == pytest.approx(144.0, rel=1e-3)
    (rel,) = rels
    assert rel.lon == pytest.approx(5.0, abs=1e-3) and rel.lat == pytest.approx(3.0, abs=1e-3)
    assert rel.vert == pytest.approx(0.0, abs=1e-3)
    assert rel.vr == pytest.approx(2.0, abs=1e-3) and rel.vl == pytest.approx(0.0, abs=1e-3)
    assert rel.reach == pytest.approx(L, abs=1e-3)  # aligned cars: L/2 + L/2
    assert rel.gap == pytest.approx(3.0 - W, abs=1e-3)  # |lat| - W/2 - W/2


def test_oriented_extents_of_a_spun_car() -> None:
    rows = {0: row(0, 0, 0, 0, 0, 50, 0.0), 1: row(-4.0, 0, 1.0, 0, 0, 0, 90.0)}
    m = decode(_fm(2025, rows, {0: ON, 1: ON}))
    assert m is not None
    _b, (rel,) = relative(m, L, W)
    assert rel.lat == pytest.approx(4.0, abs=1e-3)
    assert rel.reach == pytest.approx(L / 2 + W / 2, abs=1e-3)  # sideways: its width lengthwise
    assert rel.gap == pytest.approx(4.0 - W / 2 - L / 2, abs=1e-3)  # and its length sideways


def test_invalid_vectors_empty_slots_bridges_and_status_filters() -> None:
    rows = {
        0: row(0, 0, 0, 0, 0, 50, 0.0),
        1: row(-3, 0, 0, 0, 0, 50, 0.0),  # racing
        2: row(-3, 8.0, 0, 0, 0, 50, 0.0),  # on a bridge 8 m above
        3: row(-3, 0, 0, 0, 0, 50, 0.0),  # finished (cool-down lap): still on track
        4: row(-3, 0, 0, 0, 0, 50, 0.0),  # in the pit lane
        5: row(-3, 0, 0, 0, 0, 50, 0.0),  # in the garage
        6: row(-3, 0, 0, 0, 0, 50, 0.0),  # retired
        7: (-3.0, 0.0, 0.0, 0.0, 0.0, 50.0, 0.0, 0.0, 16000.0, -32767.0, 0.0, 0.0),  # forward not unit length
    }
    status = {0: ON, 1: ON, 2: ON, 3: (0, 4, 3), 4: (1, 4, 2), 5: (0, 0, 2), 6: (0, 4, 7), 7: ON}
    m = decode(_fm(2025, rows, status))
    assert m is not None
    _b, rels = relative(m, L, W)
    got = {r.idx: r.obstacle for r in rels}
    assert got == {1: True, 2: False, 3: True, 4: False, 5: False, 6: False}  # 7 left out; empty slots too
    m2 = decode(_fm(2025, rows, None))
    assert m2 is not None
    assert not any(r.obstacle for r in relative(m2, L, W)[1])  # no LapData: unknown, never an obstacle


def test_invalid_player_vectors() -> None:
    rows = {0: (0.0, 0.0, 0.0, 0.0, 0.0, 50.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0), 1: row(-3, 0, 0, 0, 0, 50, 0.0)}
    m = decode(_fm(2025, rows, {0: ON, 1: ON}))
    assert m is not None and relative(m, L, W) == (None, [])
    nan = (math.nan, *rows[1][1:])
    m = decode(_fm(2025, {0: nan, 1: rows[1]}, {0: ON, 1: ON}))
    assert m is not None and relative(m, L, W)[0] is None


# --- review fix: relative speeds in the player's turning frame ---
def _circle(t: float, w: float, lon: float, lat: float, speed: float = 50.0) -> tuple[float, ...]:
    """SYNTHETIC: a point ``lon`` ahead and ``lat`` right of a player driving a circle at ``speed``, heading w*t
    (forward (sin h, 0, cos h), right (-cos h, 0, sin h): the game's convention). Velocity: central differences."""

    def pos(tt: float) -> tuple[float, float]:
        h = w * tt
        radius = speed / w
        px, pz = radius * (1 - math.cos(h)), radius * math.sin(h)
        return px + lon * math.sin(h) - lat * math.cos(h), pz + lon * math.cos(h) + lat * math.sin(h)

    e = 1e-4
    (x, z), (xa, za), (xb, zb) = pos(t), pos(t - e), pos(t + e)
    return row(x, 0.0, z, (xb - xa) / (2 * e), 0.0, (zb - za) / (2 * e), math.degrees(w * t))


@pytest.mark.parametrize("w", [0.5, -0.5])
def test_relative_speeds_include_the_frame_rotation(w: float) -> None:
    """SYNTHETIC: two cars holding station through a 100 m corner. Without the rotation terms they read as moving
    sideways at w x lon (1 m/s at 2 m ahead); with them, nothing moves in the player's frame."""
    dt = 1 / 60
    status = {i: (0, 4, 2) for i in range(3)}

    def at(t: float) -> FieldMotion:
        rows = {0: _circle(t, w, 0.0, 0.0), 1: _circle(t, w, 2.0, -2.2), 2: _circle(t, w, -2.0, 2.2)}
        return dataclasses.replace(_fm(2025, rows, status), session_time_s=t)

    m0, m1 = decode(at(10.0)), decode(at(10.0 + dt))
    assert m0 is not None and m1 is not None
    b0, _ = relative(m0, L, W)
    assert b0 is not None
    _b, plain = relative(m1, L, W)
    _b, turning = relative(m1, L, W, prev=(m0.session_time_s, b0))
    assert len(plain) == len(turning) == 2
    for p, q in zip(plain, turning, strict=True):
        assert p.lat == pytest.approx(q.lat) and abs(p.vl) == pytest.approx(abs(w * p.lon), abs=0.05)
        assert abs(q.vl) < 0.05 and abs(q.vr) < 0.05
    _b, gap = relative(m1, L, W, prev=(m0.session_time_s - 0.3, b0))  # more than 0.25 s apart: no rotation term
    assert [g.vl for g in gap] == [p.vl for p in plain]
