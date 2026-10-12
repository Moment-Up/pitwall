"""Gran Turismo 7: Salsa20 (spec vectors), packet framing and layouts (machine-checked against the research doc),
validation, normalisation, derived lap distance / completions / track identity / session boundaries, heartbeat,
and end-to-end replays through the lap assembler, the analysis pipeline and the database.

Synthetic-stream tests (``pytest.mark.synthetic``) validate pitwall's algorithms against generated packets with
known ground truth. They are NOT evidence that GT7 on a real console is compatible.
"""

from __future__ import annotations

import math
import re
import socket
import struct
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from pitwall.adapters.base import GameAdapter, PacketRejected, SupportLevel
from pitwall.adapters.gt7 import packets as P
from pitwall.adapters.gt7.adapter import (
    GT7_INFO,
    OFF_TRACK_END_TICKS,
    OPEN_TICKS,
    RESET_MAX_LOADING_TICKS,
    SF_MATCH_LENGTH_FRAC,
    SF_MATCH_LENGTH_MIN_M,
    STALL_END_TICKS,
    STEER_HALF_LOCK_RAD,
    GT7Adapter,
    TrackSignature,
)
from pitwall.adapters.gt7.salsa20 import Salsa20, quarterround, salsa20_expand, salsa20_hash
from pitwall.adapters.structdef import StructDef
from pitwall.analysis.laps import DERIVED_EDGE_FRAC, EDGE_TOLERANCE_M, LapAssembler, LapFlag, LapTrace
from pitwall.ingest.capture import CapturedPacket, CaptureReader
from pitwall.ingest.gt7_heartbeat import GT7Heartbeat
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
from pitwall.sim.driver import CornerDeviation, DriverProfile
from pitwall.sim.gt7_stream import (
    GT7GroundTruth,
    GT7Scenario,
    generate_gt7_session,
    gt7_coaching_demo,
    write_gt7_capture,
)
from pitwall.sim.track import Arc, Straight, TrackGeometry, build_track, pitwall_park

DOC = Path(__file__).resolve().parents[2] / "docs" / "research" / "gt7-protocol.md"


# =============================================================================================== Salsa20
def _dec(spaced: str) -> bytes:
    """Bytes written as the spec writes them: space-separated decimals."""
    return bytes(int(x) for x in spaced.split())


class TestSalsa20:
    """Vectors from D. J. Bernstein, "Salsa20 specification" (sections 3, 8, 9) and eSTREAM set 1."""

    @pytest.mark.parametrize(
        ("inp", "expected"),
        [
            ((0, 0, 0, 0), (0, 0, 0, 0)),
            ((1, 0, 0, 0), (0x08008145, 0x00000080, 0x00010200, 0x20500000)),
            ((0, 1, 0, 0), (0x88000100, 0x00000001, 0x00000200, 0x00402000)),
            ((0, 0, 1, 0), (0x80040000, 0x00000000, 0x00000001, 0x00002000)),
            ((0, 0, 0, 1), (0x00048044, 0x00000080, 0x00010000, 0x20100001)),
            ((0xE7E8C006, 0xC4F9417D, 0x6479B4B2, 0x68C67137), (0xE876D72B, 0x9361DFD5, 0xF1460244, 0x948541A3)),
            ((0xD3917C5B, 0x55F1C407, 0x52A58A7A, 0x8F887A3B), (0x3E2F308C, 0xD90A8F36, 0x6AB2A923, 0x2883524C)),
        ],
    )
    def test_quarterround_spec_vectors(self, inp: tuple[int, int, int, int], expected: tuple[int, ...]) -> None:
        assert quarterround(*inp) == expected

    def test_hash_spec_vectors(self) -> None:
        assert salsa20_hash(bytes(64)) == bytes(64)
        inp = _dec(
            "211 159 13 115 76 55 82 183 3 117 222 37 191 187 234 136 49 237 179 48 1 106 178 219 175 199 "
            "166 48 86 16 179 207 31 240 32 63 15 83 93 161 116 147 48 113 238 55 204 36 79 201 235 79 3 81 "
            "156 47 203 26 244 243 88 118 104 54"
        )
        out = _dec(
            "109 42 178 168 156 240 248 238 168 196 190 203 26 110 170 154 29 29 150 26 150 30 235 249 190 "
            "163 251 48 69 144 51 57 118 40 152 157 180 57 27 94 107 42 236 35 27 111 114 114 219 236 232 "
            "135 111 155 110 18 24 232 95 158 179 19 48 202"
        )
        assert salsa20_hash(inp) == out

    def test_expansion_spec_vector_32_byte_key(self) -> None:
        key = bytes(range(1, 17)) + bytes(range(201, 217))
        n = bytes(range(101, 117))
        expected = _dec(
            "69 37 68 39 41 15 107 193 255 139 122 6 170 233 217 98 89 144 182 106 21 51 200 65 239 49 222 "
            "34 215 114 40 126 104 197 7 225 197 153 31 2 102 78 76 176 84 245 246 184 177 160 133 130 6 72 "
            "149 119 192 195 132 236 234 103 246 74"
        )
        assert salsa20_expand(key, n) == expected
        # the stream cipher is the expansion with n = nonce || little-endian block counter
        nonce, counter = n[:8], int.from_bytes(n[8:], "little")
        assert Salsa20(key).keystream(nonce, 64, counter=counter) == expected

    def test_estream_set1_vector0(self) -> None:
        ks = Salsa20(b"\x80" + bytes(31)).keystream(bytes(8), 64)
        assert ks.hex().upper() == (
            "E3BE8FDD8BECA2E3EA8EF9475B29A6E7003951E1097A5C38D23B7A5FAD9F6844"
            "B22C97559E2723C7CBBD3FE4FC8D9A0744652A83E72A9C461876AF4D7EF1A117"
        )

    def test_keystream_blocks_are_contiguous_and_xor_is_symmetric(self) -> None:
        c = Salsa20(bytes(range(32)))
        nonce = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        ks = c.keystream(nonce, 200)
        assert ks[:64] == c.keystream(nonce, 64) and ks[64:128] == c.keystream(nonce, 64, counter=1)
        assert ks[128:200] == c.keystream(nonce, 72, counter=2)
        msg = bytes(range(256)) * 2
        assert c.xor(nonce, c.xor(nonce, msg)) == msg and c.xor(nonce, msg) != msg
        assert c.xor(nonce, b"") == b""

    @pytest.mark.parametrize(
        "bad",
        [
            lambda: Salsa20(bytes(31)),
            lambda: Salsa20(bytes(32)).keystream(bytes(7), 10),
            lambda: Salsa20(bytes(32)).keystream(bytes(8), -1),
            lambda: salsa20_hash(bytes(63)),
            lambda: salsa20_expand(bytes(32), bytes(8)),
        ],
    )
    def test_rejects_bad_lengths(self, bad: Any) -> None:
        with pytest.raises(ValueError):
            bad()


# =============================================================================================== layouts vs the doc
def test_variant_sizes_and_constants() -> None:
    assert {n: (v.size, v.xor, v.heartbeat) for n, v in P.VARIANTS.items()} == {
        "A": (296, 0xDEADBEAF, b"A"),
        "B": (316, 0xDEADBEEF, b"B"),
        "~": (344, 0x55FABB4F, b"~"),
        "C": (368, 0xDEADBEEF, b"C"),
    }
    for v in P.VARIANTS.values():
        assert v.layout.size == v.size
    assert P.KEY == b"Simulator Interface Packet GT7 v" and len(P.KEY) == 32


# Our field name -> the doc's "Field" cell for each struct element (one per array element), sections 4-7.
DOC_LABELS: dict[str, str | tuple[str, ...]] = {
    "magic": "magic",
    "position": ("position X", "position Y", "position Z"),
    "velocity": ("velocity X", "velocity Y", "velocity Z"),
    "rotation": ("rotation[0]", "rotation[1]", "rotation[2]", "rotation[3]"),
    "angular_velocity": ("angular velocity X", "angular velocity Y", "angular velocity Z"),
    "body_height": "body height",
    "engine_rpm": "engine RPM",
    "iv": "nonce seed (IV1)",
    "fuel_level": "fuel level",
    "fuel_capacity": "fuel capacity",
    "speed": "speed",
    "turbo_boost": "turbo boost / manifold pressure",
    "oil_pressure": "oil pressure",
    "water_temp": "water temperature",
    "oil_temp": "oil temperature",
    "tyre_surface_temp": tuple(f"tyre surface temp {w}" for w in ("FL", "FR", "RL", "RR")),
    "packet_id": "packet id",
    "lap_count": "lap count",
    "total_laps": "total laps",
    "best_lap_ms": "best lap time",
    "last_lap_ms": "last lap time",
    "time_of_day_ms": "time of day",
    "pre_race_position": "pre-race start position / quali position",
    "num_cars_pre_race": "number of cars (pre-race)",
    "rev_alert_min_rpm": "rev-limiter alert min RPM",
    "rev_alert_max_rpm": "rev-limiter alert max RPM",
    "calc_max_speed_kph": "calculated max speed",
    "flags": "flags",
    "gears": "gears",
    "throttle": "throttle",
    "brake": "brake",
    "unused_93": "unused",
    "road_plane": ("road plane X", "road plane Y", "road plane Z"),
    "road_plane_distance": "road plane distance",
    "wheel_angular_speed": tuple(f"wheel angular speed {w}" for w in ("FL", "FR", "RL", "RR")),
    "tyre_radius": tuple(f"tyre radius {w}" for w in ("FL", "FR", "RL", "RR")),
    "suspension_height": tuple(f"suspension height {w}" for w in ("FL", "FR", "RL", "RR")),
    "reserved": "reserved",
    "clutch_pedal": "clutch pedal",
    "clutch_engagement": "clutch engagement",
    "rpm_clutch_to_gearbox": "RPM from clutch to gearbox",
    "transmission_top_speed": "transmission top speed",
    "gear_ratios": (*(f"gear ratio {i}" for i in range(1, 8)), "gear ratio 8 / unused"),
    "car_code": "car code",
    "wheel_rotation_rad": "steering wheel rotation",
    "wheel_angular_velocity": "steering wheel angular velocity",
    "sway": "sway",
    "heave": "heave",
    "surge": "surge",
    "throttle_alt": "throttle (alt)",
    "brake_alt": "brake (alt)",
    "unknown_13e": "unknown",
    "unknown_13f": "unknown",
    "wheel_torque": tuple(f"per-wheel value {w}" for w in ("FL", "FR", "RL", "RR")),
    "energy_recovery": "energy recovery",
    "unknown_154": "unknown",
    "surface_type": "surface type FL, FR, RL, RR",
    "current_lap_ms": "current lap time",
    "fl_steer_rad": "front-left wheel steer angle",
    "fr_steer_rad": "front-right wheel steer angle",
    "wheelbase_left_m": "left-side wheelbase (dynamic)",
    "car_category": "car category",
}
STRUCT_TO_DOC_TYPE = {"f": "f32", "i": "i32", "I": "u32", "h": "i16", "H": "u16", "B": "u8"}
_DOC_TYPE = re.compile(r"(?:[uif]\d+|char)(?:\[\d+\])?")


@pytest.fixture(scope="module")
def doc_rows() -> dict[int, dict[str, str]]:
    """Every row of the layout tables in doc sections 4-7, keyed by start offset, cells keyed by column header."""
    if not DOC.exists():
        pytest.skip("docs/research/gt7-protocol.md not present")
    doc = DOC.read_text(encoding="utf-8")
    body = doc[doc.index("## 4. Base packet") : doc.index("## 8.")]
    rows: dict[int, dict[str, str]] = {}
    cols: list[str] | None = None
    for line in body.splitlines():
        if line.startswith("| Hex |"):
            cols = [c.strip() for c in line.strip().strip("|").split("|")]
            continue
        m = re.match(r"^\| (0x[0-9A-Fa-f]{3})(?:–0x[0-9A-Fa-f]{3})? \|", line)
        if m:
            assert cols is not None, line
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            off = int(m.group(1), 16)
            assert off not in rows, f"duplicate doc row at {off:#x}"
            rows[off] = dict(zip(cols, cells, strict=True))
    assert len(rows) > 90
    return rows


def layout_problems(layout: StructDef, rows: dict[int, dict[str, str]], size: int) -> list[str]:
    """Compare every element of ``layout`` with the doc row at its offset: label, type (or byte size), and the
    Dec column; and check that the layout covers exactly the doc's rows below ``size``."""
    problems: list[str] = []
    covered: set[int] = set()
    starts = P.field_offsets(layout)
    for name, fmt in layout.fields:
        off = starts[name]
        m = re.fullmatch(r"(\d*)([a-zA-Z])", fmt)
        assert m, fmt
        count, code = int(m.group(1) or 1), m.group(2)
        if code == "s":
            elems = [(off, count)]
        else:
            step = struct.calcsize("<" + code)
            elems = [(off + i * step, step) for i in range(count)]
        labels = DOC_LABELS.get(name)
        if labels is None:
            problems.append(f"{name}: no doc label mapping")
            labels = ("?",) * len(elems)
        elif isinstance(labels, str):
            labels = (labels,)
        if len(labels) != len(elems):
            problems.append(f"{name}: {len(elems)} elements, {len(labels)} doc labels")
        for (eoff, esize), label in zip(elems, labels, strict=False):
            row = rows.get(eoff)
            if row is None:
                problems.append(f"{name}: no doc row at {eoff:#x}")
                continue
            covered.add(eoff)
            if row["Field"] != label:
                problems.append(f"{name} @{eoff:#x}: doc field is {row['Field']!r}, expected {label!r}")
            if int(row["Dec"].split("–")[0]) != eoff:
                problems.append(f"{name} @{eoff:#x}: doc Dec column {row['Dec']!r}")
            types = set(_DOC_TYPE.findall(row["Type"]))
            if name == "iv":
                ok = row["Type"] == "—"  # nonce seed: no type, garbage after decryption
            elif code == "s":
                ok = f"char[{esize}]" in types or row.get("Size") == str(esize)
            else:
                ok = STRUCT_TO_DOC_TYPE[code] in types
            if not ok:
                problems.append(f"{name} @{eoff:#x}: ours {fmt!r}, doc type {row['Type']!r}")
    missing = sorted(o for o in rows if o < size and o not in covered)
    problems += [f"doc row {o:#x} ({rows[o]['Field']}) not decoded" for o in missing]
    return problems


@pytest.mark.parametrize("variant", list(P.VARIANTS))
def test_layouts_match_the_research_doc_tables(variant: str, doc_rows: dict[int, dict[str, str]]) -> None:
    """Machine-check of every struct element against the doc's tables: offset, field label and type."""
    v = P.VARIANTS[variant]
    assert layout_problems(v.layout, doc_rows, v.size) == []


def test_doc_check_catches_swapped_and_retyped_fields(doc_rows: dict[int, dict[str, str]]) -> None:
    fields = list(P.BASE_FIELDS)
    i_best = fields.index(("best_lap_ms", "i"))
    i_last = fields.index(("last_lap_ms", "i"))
    swapped = list(fields)
    swapped[i_best], swapped[i_last] = fields[i_last], fields[i_best]
    assert any("best_lap_ms" in p for p in layout_problems(StructDef("x", swapped), doc_rows, 296))
    retyped = list(fields)
    retyped[i_best] = ("best_lap_ms", "f")
    assert any("doc type" in p for p in layout_problems(StructDef("x", retyped), doc_rows, 296))
    i_level = fields.index(("fuel_level", "f"))
    i_cap = fields.index(("fuel_capacity", "f"))
    fuel = list(fields)
    fuel[i_level], fuel[i_cap] = fields[i_cap], fields[i_level]
    assert len(layout_problems(StructDef("x", fuel), doc_rows, 296)) == 2


def test_variant_table_key_and_magic_match_the_research_doc() -> None:
    if not DOC.exists():
        pytest.skip("docs/research/gt7-protocol.md not present")
    doc = DOC.read_text(encoding="utf-8")
    for v in P.VARIANTS.values():
        line = next(ln for ln in doc.splitlines() if ln.startswith(f"| `{v.name}` |"))
        assert f"{v.size} bytes" in line and f"0x{v.xor:X}" in line, line
    assert "0x47375330" in doc and "Simulator Interface Packet GT7 ver 0.0" in doc


def test_nonce_derivation_follows_the_doc() -> None:
    iv1 = 0x01020304
    assert P.nonce_for(P.VARIANTS["A"], iv1) == (iv1 ^ 0xDEADBEAF).to_bytes(4, "little") + iv1.to_bytes(4, "little")
    assert P.nonce_for(P.VARIANTS["~"], 0xFFFFFFFF)[:4] == (0xFFFFFFFF ^ 0x55FABB4F).to_bytes(4, "little")


def _values(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "packet_id": 1,
        "flags": int(P.Flags.CAR_ON_TRACK),
        "lap_count": 1,
        "last_lap_ms": -1,
        "best_lap_ms": -1,
        "pre_race_position": -1,
        "car_code": 1234,
        "fuel_capacity": 100.0,
        "fuel_level": 50.0,
        "gears": 0xF3,
        "current_lap_ms": -1,  # variant C only (ignored by the smaller layouts)
        "time_of_day_ms": 50_000_000,
    }
    base.update(overrides)
    return base


def _packet(variant: str = "C", iv1: int = 0x9E3779B9, **overrides: Any) -> bytes:
    return P.encrypt(P.pack(P.VARIANTS[variant], _values(**overrides)), iv1)


@pytest.mark.parametrize("variant", list(P.VARIANTS))
def test_decrypt_each_variant_by_the_documented_procedure(variant: str) -> None:
    v = P.VARIANTS[variant]
    plain = P.pack(v, _values(speed=42.5, packet_id=777))
    iv1 = 0xA1B2C3D4
    # build the ciphertext independently of P.encrypt: Salsa20 over the whole datagram, IV1 at 0x40
    ct = bytearray(
        Salsa20(P.KEY).xor(((iv1 ^ v.xor) & 0xFFFFFFFF).to_bytes(4, "little") + iv1.to_bytes(4, "little"), plain)
    )
    ct[0x40:0x44] = iv1.to_bytes(4, "little")
    assert bytes(ct) == P.encrypt(plain, iv1)
    got_v, got = P.decrypt(bytes(ct))
    assert got_v is v and got[:0x40] == plain[:0x40] and got[0x44:] == plain[0x44:]
    fields = P.unpack(v, got)
    assert fields["magic"] == P.MAGIC and fields["packet_id"] == 777 and fields["speed"] == pytest.approx(42.5)
    assert P.has_valid_magic(bytes(ct))


class TestRejection:
    @pytest.mark.parametrize("size", [0, 4, 68, 295, 297, 317, 367, 369, 1500])
    def test_unknown_sizes(self, size: int) -> None:
        a = GT7Adapter()
        data = bytes(size)
        assert not a.can_decode(data)
        with pytest.raises(PacketRejected, match="size"):
            a.decode(data, 0)
        assert a.stats.rejected == 1 and a.stats.packets == 1 and a.stats.decoded == 0

    def test_wrong_magic_random_bytes(self) -> None:
        a = GT7Adapter()
        rng = np.random.default_rng(3)
        for size in (296, 316, 344, 368):
            data = rng.integers(0, 256, size, dtype=np.uint8).tobytes()
            assert not a.can_decode(data)
            with pytest.raises(PacketRejected, match="magic"):
                a.decode(data, 0)
        assert a.stats.rejected == 4

    @pytest.mark.parametrize("offset", [0, 3, 0x40, 0x43])
    def test_corrupted_magic_or_iv_is_rejected(self, offset: int) -> None:
        data = bytearray(_packet())
        data[offset] ^= 0x01
        a = GT7Adapter()
        assert not a.can_decode(bytes(data))
        with pytest.raises(PacketRejected):
            a.decode(bytes(data), 0)

    def test_truncated_packet_is_rejected(self) -> None:
        with pytest.raises(PacketRejected):
            GT7Adapter().decode(_packet()[:-1], 0)

    def test_wrong_variant_constant_is_rejected(self) -> None:
        plain = P.pack(P.VARIANTS["C"], _values())
        iv1 = 1234567
        wrong = P.Variant("C?", b"C", 368, 0x55FABB4F, P.PACKET_C)  # C-sized but encrypted with the ~ constant
        ct = bytearray(Salsa20(P.KEY).xor(P.nonce_for(wrong, iv1), plain))
        ct[0x40:0x44] = iv1.to_bytes(4, "little")
        with pytest.raises(PacketRejected, match="magic"):
            GT7Adapter().decode(bytes(ct), 0)

    def test_valid_packets_are_detected(self) -> None:
        a = GT7Adapter()
        assert isinstance(a, GameAdapter)
        for v in P.VARIANTS:
            assert a.can_decode(_packet(v))

    def test_internal_errors_never_escape_decode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a = GT7Adapter()

        def boom(*_: Any) -> bool:
            raise RuntimeError("bug")

        monkeypatch.setattr(a, "_step", boom)
        assert a.decode(_packet(), 0) == []
        assert a.stats.errors == 1 and "bug" in (a.stats.last_error or "")


# =============================================================================================== normalisation
TICK_NS = 16_666_667


def _open(adapter: GT7Adapter, data: bytes, t: int) -> list[Emitted]:
    """Open a session in front of ``data``, as a real stream does before anything is emitted: OPEN_TICKS live packets
    with its values (on track, not paused, the car moving), their packet ids just below its own. (One more: the first
    packet of a stream cannot be live - nothing shows it advancing.)"""
    v, plain = P.decrypt(data)
    fields = P.unpack(v, plain)
    out: list[Emitted] = []
    n = OPEN_TICKS + 1
    for k in range(n):
        warm = dict(
            fields,
            packet_id=fields["packet_id"] - n + k,
            flags=int(P.Flags.CAR_ON_TRACK),
            position=(float(k), 0.0, 0.0),
        )
        out += adapter.decode(P.encrypt(P.pack(v, warm), 7 + k), t - (n - k) * TICK_NS)
    assert adapter.session_uid is not None
    return out


def _decode_one(data: bytes, adapter: GT7Adapter | None = None, t: int = 0) -> tuple[CarFrame, list[Emitted]]:
    """Decode one packet inside a session (opened first when none is): its frame, and everything emitted."""
    a = adapter or GT7Adapter()
    warm = _open(a, data, t) if a.session_uid is None else []
    out = a.decode(data, t)
    frames = [e for e in out if isinstance(e, CarFrame)]
    assert len(frames) == 1, out
    return frames[0], warm + out


def _info(out: Iterable[Emitted]) -> SessionInfo:
    return [e for e in out if isinstance(e, SessionInfo)][-1]


def test_units_and_wheel_order() -> None:
    f, out = _decode_one(
        _packet(
            speed=50.0,
            throttle=200,  # 0x91: the throttle after TCS (owner's PS5 captures)
            throttle_alt=255,  # 0x13C: the driver's pedal
            brake=128,
            gears=0xF3,
            engine_rpm=7123.0,
            rev_alert_max_rpm=8500,
            position=(1.5, 2.5, -3.5),
            velocity=(10.0, 0.5, -20.0),
            tyre_surface_temp=(81.0, 82.0, 71.0, 72.0),  # documented order: FL, FR, RL, RR
            fuel_level=37.5,
            fuel_capacity=100.0,
            clutch_pedal=0.25,
            lap_count=2,
            last_lap_ms=92_345,
            best_lap_ms=91_000,
            pre_race_position=4,
            packet_id=55,
        )
    )
    assert f.game == Game.GT7 and f.frame_id == 55
    assert f.speed_kph == pytest.approx(180.0) and f.throttle == 1.0 and f.brake == pytest.approx(128 / 255)
    assert f.gear == 3 and f.rpm == pytest.approx(7123.0) and f.max_rpm == 8500.0 and f.clutch == 0.25
    assert (f.pos_x_m, f.pos_y_m, f.pos_z_m) == (1.5, 2.5, -3.5)
    assert (f.vel_x_mps, f.vel_y_mps, f.vel_z_mps) == (10.0, 0.5, -20.0)
    assert f.tyre_surface_temp_c == Wheels(fl=81.0, fr=82.0, rl=71.0, rr=72.0)
    assert f.lap_number == 2 and f.last_lap_time_ms == 92_345 and f.race_position == 4
    assert f.quality == FrameQuality.OK
    # never received / not provided by GT7, or of unknown unit: unknown must stay unknown
    assert f.lap_distance_m is None and f.current_lap_time_ms is None  # not anchored, C timer unset
    for name in (
        "tyre_wear_pct",
        "tyre_pressure_psi",
        "tyre_inner_temp_c",
        "brake_temp_c",
        "g_lat",
        "g_lon",
        "yaw_rad",
        "sector",
        "pit_status",
        "lap_invalid",
        "fuel_kg",
        "fuel_litres",  # litres per PDTools, percent per GT7Eng: conflicting
        "fuel_capacity_litres",
        "abs_active",
        "tyre_compound",
        "drs_open",
    ):
        assert getattr(f, name) is None, name
    info = _info(out)
    assert info.game == Game.GT7 and info.car_id == "gt7:car:1234" and info.track_id is None
    assert info.track_length_m is None and info.extra["best_lap_ms"] == 91_000 and info.extra["packet_variant"] == "C"
    assert info.extra["fuel_fraction"] == pytest.approx(0.375)  # unitless whatever 0x44/0x48 measure


@pytest.mark.parametrize(("variant", "expected"), [("A", 200), ("B", 200), ("~", 255), ("C", 255)])
def test_throttle_is_the_pedal_where_the_packet_has_it(variant: str, expected: int) -> None:
    """0x13C (variants ~ and C) is the driver's pedal, 0x91 the throttle after TCS: on the owner's PS5 captures 0x91
    was below 0x13C on every TCS-active packet. A and B have only 0x91."""
    f, _ = _decode_one(_packet(variant, throttle=200, throttle_alt=255))
    assert f.throttle == pytest.approx(expected / 255)


def test_unset_and_sentinel_values_map_to_none() -> None:
    f, out = _decode_one(
        _packet(
            "A",
            gears=0xFF,
            lap_count=0,
            last_lap_ms=-1,
            pre_race_position=-1,
            fuel_capacity=0.0,
            fuel_level=0.3,
            rev_alert_max_rpm=0,
            car_code=0,
        )
    )
    assert f.gear is None and f.lap_number is None and f.last_lap_time_ms is None and f.race_position is None
    assert f.fuel_litres is None and f.fuel_capacity_litres is None and f.max_rpm is None
    assert f.steering is None  # variant A has no steering
    assert f.quality & FrameQuality.NOT_RACING  # lap 0 is not a timed lap
    info = _info(out)
    assert info.car_id is None and info.total_laps is None and info.extra["fuel_fraction"] is None  # EV: no fuel
    # 0 / 15 = reverse / neutral per Kaitai, unverified: the owner's PS5 captures showed 0 only in spins with the clutch
    # out (no gear engaged fits as well as reverse) and never 15; R and N were never selected
    assert _decode_one(_packet(gears=0xF0))[0].gear is None
    assert [_decode_one(_packet(gears=0xF0 | g))[0].gear for g in (1, 5, 14)] == [1, 5, 14]


def test_non_finite_auxiliary_values_map_to_none() -> None:
    nan = float("nan")
    f, _ = _decode_one(_packet(engine_rpm=nan, clutch_pedal=float("inf"), tyre_surface_temp=(80.0, nan, 70.0, 70.0)))
    assert f.rpm is None and f.clutch is None and f.tyre_surface_temp_c is None
    assert f.speed_kph == 0.0  # the packet itself is still decoded


def test_current_lap_time_comes_from_variant_c_timer() -> None:
    assert _decode_one(_packet("C", current_lap_ms=12_345))[0].current_lap_time_ms == 12_345
    assert _decode_one(_packet("C", current_lap_ms=-1))[0].current_lap_time_ms is None


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        (P.Flags.CAR_ON_TRACK, FrameQuality.OK),
        (P.Flags.CAR_ON_TRACK | P.Flags.PAUSED, FrameQuality.PAUSED),
        (P.Flags(0), FrameQuality.NOT_RACING),
        (P.Flags.PAUSED, FrameQuality.PAUSED | FrameQuality.NOT_RACING),
        (P.Flags.CAR_ON_TRACK | P.Flags.TCS_ACTIVE | P.Flags.HAS_TURBO, FrameQuality.OK),
    ],
)
def test_flags_map_to_frame_quality(flags: P.Flags, expected: FrameQuality) -> None:
    assert _decode_one(_packet(flags=int(flags)))[0].quality == expected


def test_unknown_high_flag_bits_are_ignored() -> None:
    # i16 bitfield: bit 15 set reads as a negative number; bits 12-15 are undocumented and masked off
    assert _decode_one(_packet(flags=-0x8000 | int(P.Flags.CAR_ON_TRACK)))[0].quality == FrameQuality.OK


def test_finished_race_laps_are_not_racing() -> None:
    assert _decode_one(_packet(lap_count=4, total_laps=3))[0].quality & FrameQuality.NOT_RACING


# =============================================================================================== session boundaries
def _drive(a: GT7Adapter, n: int, pid: int, t: int = 0, **values: Any) -> tuple[list[Emitted], int]:
    """``n`` live packets (the car moving along x) from packet id ``pid``; returns what was emitted and the next id."""
    out: list[Emitted] = []
    for _ in range(n):
        fields = {"position": (pid * 0.8, 0.0, 0.0), "velocity": (48.0, 0.0, 0.0), "speed": 48.0, **values}
        out += a.decode(_packet(packet_id=pid, **fields), t + pid * TICK_NS)
        pid += 1
    return out, pid


def _ended(out: Iterable[Emitted]) -> list[str | None]:
    return [e.code for e in out if isinstance(e, GameEvent) and e.kind == EventKind.SESSION_ENDED]


def _uids(out: Iterable[Emitted]) -> list[str | None]:
    return [e.session_uid for e in out if isinstance(e, SessionInfo)]


def _frames(out: Iterable[Emitted]) -> list[CarFrame]:
    return [e for e in out if isinstance(e, CarFrame)]


def test_a_session_opens_only_after_half_a_second_of_live_packets() -> None:
    """Menus, replays and the menus' background laps (CarOnTrack clear), a frozen stream (nothing advancing), paused or
    loading packets and transition blips shorter than OPEN_TICKS never open a session; nothing is emitted for them."""
    a = GT7Adapter()
    out, pid = _drive(a, 600, 1, flags=0)  # replay / background laps: the car moves, CarOnTrack clear
    for _ in range(600):  # menus: one frozen packet, only the id changes
        out += a.decode(_packet(packet_id=pid), pid * TICK_NS)
        pid += 1
    more, pid = _drive(a, OPEN_TICKS - 1, pid)  # a blip of live packets...
    out += more
    more, pid = _drive(a, 10, pid, flags=int(P.Flags.CAR_ON_TRACK | P.Flags.PAUSED))  # ...cut by a pause
    out += more
    assert out == [] and a.session_uid is None and "sessions" not in a.stats.by_type
    assert a.stats.ignored == a.stats.packets == 1200 + OPEN_TICKS - 1 + 10
    out, pid = _drive(a, OPEN_TICKS, pid)
    t_open = (pid - 1) * TICK_NS
    assert a.session_uid == f"gt7:{t_open}" and _uids(out) == [f"gt7:{t_open}"]  # uid: the packet that opened it
    assert len(_frames(out)) == 1 and isinstance(out[0], SessionInfo)  # announced before its first frame


def test_car_reset_keeps_the_session_and_drops_the_anchor() -> None:
    """A car reset (owner's PS5: a 1-packet loading pulse, CarOnTrack on both sides, same car, lap and lap total, the C
    lap timer 17-34 ms further on) is a teleport inside the session, not a new one."""
    a = GT7Adapter()
    out, pid = _drive(a, OPEN_TICKS + 5, 1, current_lap_ms=10_000)
    uid = a.session_uid
    pulse = int(P.Flags.CAR_ON_TRACK | P.Flags.LOADING_OR_PROCESSING)
    assert a.decode(_packet(packet_id=pid, flags=pulse, current_lap_ms=10_017), 0) == []
    out, pid = _drive(a, 5, pid + 1, current_lap_ms=10_034)
    assert a.session_uid == uid and _ended(out) == [] and a.stats.by_type["car_reset"] == 1
    assert len(_frames(out)) == 5


@pytest.mark.parametrize(
    "after",
    [
        {"lap_count": 0, "total_laps": 10},  # a race loaded
        {"current_lap_ms": 90_000},  # the timer did not continue: not the same lap
        {"car_code": 4321},  # another car
        {"flags": 0},  # the car is not on track afterwards
    ],
)
def test_any_other_loading_screen_ends_the_session(after: dict[str, Any]) -> None:
    a = GT7Adapter()
    _, pid = _drive(a, OPEN_TICKS + 5, 1, current_lap_ms=10_000)
    a.decode(_packet(packet_id=pid, flags=int(P.Flags.LOADING_OR_PROCESSING)), 0)
    out, pid = _drive(a, OPEN_TICKS, pid + 1, **{"current_lap_ms": 10_017, **after})
    assert _ended(out) == ["loading"] and "car_reset" not in a.stats.by_type
    i_end = next(i for i, e in enumerate(out) if isinstance(e, GameEvent))
    assert i_end == 0  # nothing of the old session after its end
    assert a.session_uid is None or _uids(out)  # a new session needs its own OPEN_TICKS live packets


def test_a_long_loading_run_ends_the_session_while_loading() -> None:
    a = GT7Adapter()
    _, pid = _drive(a, OPEN_TICKS + 5, 1, current_lap_ms=10_000)
    outs = [a.decode(_packet(packet_id=pid + k, flags=int(P.Flags.LOADING_OR_PROCESSING)), 0) for k in range(60)]
    assert [k for k, o in enumerate(outs) if o] == [RESET_MAX_LOADING_TICKS]
    assert _ended(outs[RESET_MAX_LOADING_TICKS]) == ["loading"] and a.session_uid is None


def test_car_change_ends_the_session() -> None:
    a = GT7Adapter()
    _, pid = _drive(a, OPEN_TICKS + 1, 1, car_code=11)
    out, pid = _drive(a, OPEN_TICKS, pid, car_code=22)
    assert _ended(out) == ["car_change"] and isinstance(out[0], GameEvent)
    assert _info(out).car_id == "gt7:car:22" and a.session_uid is not None


def test_lap_counter_going_back_is_a_retry_that_ends_the_session() -> None:
    a = GT7Adapter()
    _, pid = _drive(a, OPEN_TICKS + 1, 1, lap_count=1)
    out, pid = _drive(a, 1, pid, lap_count=2)  # lap 1 done, its time not there yet: held
    assert not any(isinstance(e, LapCompletion) for e in out)
    out, pid = _drive(a, 1, pid, lap_count=1)  # retry before the time arrived
    comp = next(e for e in out if isinstance(e, LapCompletion))
    assert comp.lap_number == 1 and comp.lap_time_ms is None
    assert out.index(comp) < out.index(next(e for e in out if isinstance(e, GameEvent)))  # old session first
    assert _ended(out) == ["retry_lap_reset"] and a.stats.by_type["retry_lap_reset"] == 1
    # off track the lap counter means nothing (menus send -1): no retry
    b = GT7Adapter()
    _, pid = _drive(b, OPEN_TICKS + 1, 1, lap_count=3)
    out, _ = _drive(b, 5, pid, lap_count=-1, flags=0)
    assert _ended(out) == [] and len(_frames(out)) == 5


@pytest.mark.parametrize(
    ("tod_before", "tod_after", "ends"),
    [
        (50_000_000, 50_000_000 - 30_000, True),  # retry: the in-game clock went back 30 s
        (50_000_000, 50_000_000 - 9_000, False),  # less than the 10 s retry threshold
        (86_399_990, 5, False),  # midnight: a "rewind" of nearly a day is the clock wrapping
        (50_000_000, 50_000_000, False),  # frozen (paused, or on the grid before the start)
        (50_000_000, 0, False),  # 0 / -1: unset, not a rewind
        (50_000_000, -1, False),
    ],
)
def test_time_of_day_rewind_is_a_retry(tod_before: int, tod_after: int, ends: bool) -> None:
    a = GT7Adapter()
    _, pid = _drive(a, OPEN_TICKS + 1, 1, time_of_day_ms=tod_before)
    out, _ = _drive(a, 1, pid, time_of_day_ms=tod_after)
    assert (_ended(out) == ["retry_time_rewind"]) is ends
    assert (a.stats.by_type.get("retry_time_rewind", 0) == 1) is ends


def test_frozen_stream_at_speed_ends_the_session_and_is_never_integrated() -> None:
    """After leaving a race GT7 repeats one packet - CarOnTrack set, not paused, 45.9 m/s on the owner's PS5 - with only
    the packet id changing, for minutes. Those packets are dropped (no frame, no distance, no clock) and after
    STALL_END_TICKS the session ends; a pause (same payload, paused bit set) keeps the session."""
    a = GT7Adapter()
    _, pid = _drive(a, OPEN_TICKS + 1, 1)
    paused = int(P.Flags.CAR_ON_TRACK | P.Flags.PAUSED)
    frozen_fields = {"position": (100.0, 0.0, 0.0), "velocity": (45.9, 0.0, 0.0), "speed": 45.9}
    outs = [a.decode(_packet(packet_id=pid + k, flags=paused, **frozen_fields), 0) for k in range(600)]
    assert all(len(_frames(o)) == 1 and _frames(o)[0].quality & FrameQuality.PAUSED for o in outs)  # a 10 s pause
    pid += 600
    clock = a._clock_s
    outs = [a.decode(_packet(packet_id=pid + k, **frozen_fields), 0) for k in range(STALL_END_TICKS + 60)]
    assert all(o == [] for o in outs[: STALL_END_TICKS - 1])  # never emitted, never integrated
    assert _ended(outs[STALL_END_TICKS - 1]) == ["frozen"] and a.session_uid is None and a._clock_s == clock
    assert all(o == [] for o in outs[STALL_END_TICKS:])  # and no new session from it
    # a car standing still (same payload, not paused) is not a stopped simulation: the session stays
    b = GT7Adapter()
    _, pid = _drive(b, OPEN_TICKS + 1, 1)
    still = {"position": (5.0, 0.0, 0.0), "velocity": (0.0, 0.0, 0.0), "speed": 0.0}
    outs = [b.decode(_packet(packet_id=pid + k, **still), 0) for k in range(STALL_END_TICKS * 3)]
    assert all(len(_frames(o)) == 1 for o in outs) and b.session_uid is not None


def _anchored(a: GT7Adapter) -> tuple[float, int]:
    """Open a session and drive (48 m/s along x) across the line into lap 2: the lap distance is anchored. Returns the
    last frame's lap distance and the next packet id."""
    _, pid = _drive(a, OPEN_TICKS + 5, 1)
    out, pid = _drive(a, 10, pid, lap_count=2, last_lap_ms=60_000)
    dist = _frames(out)[-1].lap_distance_m
    assert dist is not None and dist > 0.0
    return dist, pid


@pytest.mark.parametrize(
    ("speed", "velocity"),
    [
        (2.0, (0.0, 0.0, 25.0)),  # frozen mid-spin: 0x4C (the speed along the car's axis) far below the velocity
        (0.0, (0.0, 0.0, 25.0)),  # ...or 0 while the car slides sideways
        (4.0, (4.0, 0.0, 0.0)),  # frozen while crawling
        (0.6, (0.0, 0.6, 0.0)),  # just above FROZEN_MIN_SPEED_MPS
    ],
)
def test_frozen_stream_is_judged_on_the_velocity_not_the_speed_field(
    speed: float, velocity: tuple[float, float, float]
) -> None:
    """0x4C is |velocity . body forward| on the owner's PS5 (it reads near 0 while the car slides sideways). Judged on
    0x4C, as before, a stream frozen in a spin never looked "at speed": it was integrated at the true velocity for as
    long as it ran (1.5 km a minute at 25 m/s) and its session never ended. The velocity magnitude decides: dropped,
    never integrated, the session ends."""
    a = GT7Adapter()
    dist, pid = _anchored(a)
    first = {"position": (pid * 0.8 + 1.0, 0.0, 0.0), "velocity": velocity, "speed": speed, "lap_count": 2}
    out = a.decode(_packet(packet_id=pid, last_lap_ms=60_000, **first), 0)  # the snapshot itself: still advancing
    (fr,) = _frames(out)
    clock = a._clock_s
    outs = [a.decode(_packet(packet_id=pid + 1 + k, last_lap_ms=60_000, **first), 0) for k in range(3600)]
    assert all(o == [] for o in outs[: STALL_END_TICKS - 1])  # no frame, no distance, no clock
    assert _ended(outs[STALL_END_TICKS - 1]) == ["frozen"] and a.session_uid is None and a._clock_s == clock
    assert not any(_frames(o) for o in outs) and fr.lap_distance_m is not None and fr.lap_distance_m < dist + 2.0


def test_a_short_frozen_run_is_bridged_by_one_tick_never_by_its_length() -> None:
    """A frozen run that ends before STALL_END_TICKS (on the owner's PS5: the first packet after a pause) did not move
    the car: the next advancing packet integrates one tick, as after a pause, and the clock advances one tick."""
    a = GT7Adapter()
    _, pid = _anchored(a)
    frozen = {"position": (pid * 0.8, 0.0, 0.0), "velocity": (48.0, 0.0, 0.0), "speed": 48.0, "lap_count": 2}
    (before,) = _frames(a.decode(_packet(packet_id=pid, last_lap_ms=60_000, **frozen), 0))
    clock = a._clock_s
    for k in range(1, 61):  # 1 s frozen at 48 m/s
        assert a.decode(_packet(packet_id=pid + k, last_lap_ms=60_000, **frozen), 0) == []
    resumed = dict(frozen, position=(pid * 0.8 + 0.8, 0.0, 0.0))
    (after,) = _frames(a.decode(_packet(packet_id=pid + 61, last_lap_ms=60_000, **resumed), 0))
    assert a.session_uid is not None and a.stats.by_type["frozen"] == 60
    assert after.lap_distance_m == pytest.approx((before.lap_distance_m or 0.0) + 0.8)  # one tick, not 61 (48.8 m)
    assert a._clock_s == pytest.approx(clock + 1 / 60)


def test_a_repeated_payload_below_the_frozen_speed_is_never_integrated() -> None:
    """Below FROZEN_MIN_SPEED_MPS a repeated payload may be a car standing still in a running simulation: its frames are
    emitted and the session stays, but it adds no distance (it did not move)."""
    a = GT7Adapter()
    _, pid = _anchored(a)
    crawl = {"position": (pid * 0.8, 0.0, 0.0), "velocity": (0.0, 0.0, 0.4), "speed": 0.0, "lap_count": 2}
    outs = [a.decode(_packet(packet_id=pid + k, last_lap_ms=60_000, **crawl), 0) for k in range(STALL_END_TICKS * 3)]
    frames = [fr for o in outs for fr in _frames(o)]
    assert len(frames) == STALL_END_TICKS * 3 and a.session_uid is not None and "frozen" not in a.stats.by_type
    assert len({fr.lap_distance_m for fr in frames[1:]}) == 1  # 360 ticks at 0.4 m/s would have added 2.4 m


def test_two_seconds_off_track_end_the_session() -> None:
    a = GT7Adapter()
    _, pid = _drive(a, OPEN_TICKS + 1, 1)
    out, pid = _drive(a, OFF_TRACK_END_TICKS - 1, pid, flags=0)  # results screen: still the session's
    assert _ended(out) == [] and all(f.quality & FrameQuality.NOT_RACING for f in _frames(out))
    out, pid = _drive(a, 1, pid, flags=0)
    assert _ended(out) == ["off_track"] and a.session_uid is None


def test_synthetic_marker_flags_the_session() -> None:
    _, out = _decode_one(_packet(reserved=P.SYNTHETIC_MARKER))
    info = _info(out)
    assert info.session_uid == str(SYNTHETIC_SESSION_UID) and info.extra["synthetic"] is True
    _, out = _decode_one(_packet())
    assert "synthetic" not in _info(out).extra


def test_steering_normalisation_and_sign_cross_check() -> None:
    quarter = STEER_HALF_LOCK_RAD / 4
    # left-positive wheel angle (documented road-wheel convention): -angle = turning right = +steering
    assert _decode_one(_packet("B", wheel_rotation_rad=-quarter))[0].steering == pytest.approx(0.25)
    assert _decode_one(_packet("~", wheel_rotation_rad=quarter))[0].steering == pytest.approx(-0.25)
    assert _decode_one(_packet("B", wheel_rotation_rad=-10 * STEER_HALF_LOCK_RAD))[0].steering == 1.0
    assert _decode_one(_packet("B", wheel_rotation_rad=float("nan")))[0].steering is None
    # variant C: if the wheel angle consistently disagrees with the documented road-wheel angles, flip the sign
    a = GT7Adapter()
    f = None
    for i in range(200):
        f, _ = _decode_one(
            _packet(
                "C",
                packet_id=i + 1,
                position=(float(i), 0.0, 0.0),
                wheel_rotation_rad=quarter,
                fl_steer_rad=-0.1,
                fr_steer_rad=-0.1,
            ),
            a,
        )
    assert a.steering_sign == 1.0 and f is not None and f.steering == pytest.approx(0.25)
    agreeing = GT7Adapter()
    for i in range(200):
        _decode_one(
            _packet(
                "C",
                packet_id=i + 1,
                position=(float(i), 0.0, 0.0),
                wheel_rotation_rad=quarter,
                fl_steer_rad=0.1,
                fr_steer_rad=0.1,
            ),
            agreeing,
        )
    assert agreeing.steering_sign == -1.0


def test_duplicate_and_out_of_order_packets_are_ignored() -> None:
    a = GT7Adapter()
    _decode_one(_packet(packet_id=10), a, 1)
    ignored = a.stats.ignored
    assert a.decode(_packet(packet_id=10), 2) == []
    assert a.decode(_packet(packet_id=9), 3) == []
    assert a.stats.ignored == ignored + 2 and a.stats.by_type["duplicate_or_out_of_order"] == 2
    assert len(a.decode(_packet(packet_id=11, position=(1.0, 0.0, 0.0)), 4)) >= 1
    assert "stream_restart" not in a.stats.by_type


def test_restart_just_below_the_last_packet_id_is_not_dropped_for_ever() -> None:
    """Ids restarting 50 below the last one look like reordering at first; a run of them is a restart, which ends the
    session; the restarted stream opens a new one OPEN_TICKS packets later."""
    a = GT7Adapter()
    for pid in range(1000, 1100):
        a.decode(_packet(packet_id=pid, position=(float(pid), 0.0, 0.0)), pid)
    outs = [
        a.decode(_packet(packet_id=pid, position=(-float(pid), 0.0, 0.0)), 10_000 + pid) for pid in range(1050, 1150)
    ]
    assert all(o == [] for o in outs[:30]) and a.stats.by_type["duplicate_or_out_of_order"] == 30
    assert _ended(outs[30]) == ["retry_stream_restart"] and a.stats.by_type["retry_stream_restart"] == 1
    i_open = 30 + OPEN_TICKS - 1
    assert all(not _frames(o) for o in outs[30:i_open])
    assert _uids(outs[i_open]) == [f"gt7:{10_000 + 1050 + i_open}"]
    assert all(_frames(o) for o in outs[i_open:])  # continuous again afterwards


def test_adapter_info_declares_derived_unverified_and_unsupported_fields() -> None:
    f = GT7_INFO.fields
    assert f["lap_distance_m"].source.startswith("derived: velocity magnitude x tick time")
    assert f["lap_distance_m"].level is SupportLevel.RECORDED_VALIDATED  # the owner's PS5 recordings, 2026-10-11
    assert GT7_INFO.platforms == {
        Platform.PS5: SupportLevel.LIVE_VALIDATED,
        Platform.PS4: SupportLevel.COMMUNITY_DOCUMENTED,
    }
    for name, fs in f.items():  # every recorded-validated field names its dated evidence
        assert (fs.level is SupportLevel.RECORDED_VALIDATED) <= ("PS5 recordings 2026-10-11" in fs.source), name
    for name in ("steering", "max_rpm", "race_position", "track_id", "clutch"):  # evidence noted, not enough
        assert f[name].level is SupportLevel.COMMUNITY_DOCUMENTED, name
    for name in ("tyre_wear_pct", "tyre_pressure_psi", "tyre_inner_temp_c", "sector", "lap_invalid"):
        assert f[name].level is SupportLevel.UNSUPPORTED, name
    assert f["fuel_litres"].level is SupportLevel.UNVERIFIED and "conflicting" in f["fuel_litres"].source
    assert "heuristic" in f["track_id"].source
    assert GT7_INFO.default_port == 33740 and GT7_INFO.ground_plane == ("pos_x_m", "pos_z_m")


# =============================================================================================== track identity
def test_track_signature_ids_round_trip_and_match_fuzzily() -> None:
    sig = TrackSignature.measured(-312.4, 1187.6, 359.0, 4563.7, 512.0)
    assert sig.track_id == "gt7:sf:-310:1190:0:4560:510"
    assert TrackSignature.parse(sig.track_id) == sig
    near = TrackSignature.measured(-290.0, 1205.0, 10.0, 4600.0, 530.0)  # other side of the road, 0.8 % longer
    assert sig.matches(near) and near.matches(sig)
    assert not sig.matches(TrackSignature.measured(-312.0, 1187.0, 180.0, 4563.0, 512.0))  # reverse layout
    assert not sig.matches(TrackSignature.measured(-312.0, 1187.0, 0.0, 2600.0, 400.0))  # shorter layout
    assert not sig.matches(TrackSignature.measured(-212.0, 1187.0, 0.0, 4563.0, 512.0))  # another line
    assert not sig.matches(TrackSignature.measured(-312.0, 1187.0, 0.0, 4650.0, 512.0))  # 2 % longer
    assert not sig.matches(TrackSignature.measured(-312.0, 1187.0, 0.0, 4530.0, 620.0))  # same line, + a chicane
    for bad in (
        "f1:10",
        "gt7:sf:1:2:3",
        "gt7:sf:-310:1190:0:4560",  # pre-turning six-part form: never merged with turning-aware ids
        "gt7:sf:a:b:c:d:e",
        "gt7:sf:0:0:0:0:300",
        "gt7:sf:0:0:0:4000:-10",
        "gt7:sf:0:0:0:nan:300",
        "synthetic:x",
    ):
        assert TrackSignature.parse(bad) is None, bad
    a = GT7Adapter(known_track_ids=[sig.track_id, "f1:10"])
    assert a.known_track_ids == [sig.track_id] and not a.add_known_track("nope")


@pytest.mark.parametrize(
    "args",
    [
        (float("nan"), 0.0, 0.0, 4000.0, 300.0),
        (0.0, 0.0, float("nan"), 4000.0, 300.0),
        (0.0, 0.0, 0.0, float("inf"), 300.0),
        (0.0, 0.0, 0.0, 4000.0, float("nan")),
        (0.0, 0.0, 0.0, -1.0, 300.0),
        (0.0, 0.0, 0.0, 4000.0, -5.0),
    ],
)
def test_track_signature_rejects_corrupt_measurements(args: tuple[float, float, float, float, float]) -> None:
    with pytest.raises(ValueError):
        TrackSignature.measured(*args)


@pytest.mark.parametrize("length_m", [800.0, 1180.0, 3964.0, 5793.0, 13_629.0, 25_378.0])
def test_length_match_never_exceeds_the_lap_assemblers_completeness_tolerance(length_m: float) -> None:
    """A registry length may differ from this session's laps by up to the match tolerance; the assembler calls a lap
    incomplete when it ends short of the track length by more than its own tolerance. The two are derived together:
    the match must never be looser (besides, the adapter publishes the session's own, shorter measurement)."""
    assert SF_MATCH_LENGTH_FRAC <= DERIVED_EDGE_FRAC and SF_MATCH_LENGTH_MIN_M <= EDGE_TOLERANCE_M
    asm = LapAssembler(lambda _: None, track_length_m=length_m)
    assert max(SF_MATCH_LENGTH_MIN_M, SF_MATCH_LENGTH_FRAC * length_m) <= asm._end_tolerance_m(Game.GT7)


# =============================================================================================== synthetic streams
@pytest.fixture(scope="module")
def triangle() -> TrackGeometry:
    """A 1.18 km synthetic circuit (30 s laps) that keeps the stream tests fast."""
    return _triangle(chicane=False)


def _triangle(chicane: bool) -> TrackGeometry:
    """The test triangle, optionally with a chicane (right-left-left-right, 40 m radius, 30 deg each) on the
    start straight. The chicane returns to the same line, so both layouts share the start line and everything
    after the chicane; the chicane layout is only ~4 m (0.3 %) longer - far inside the integration drift."""
    first: list[Straight | Arc] = [Straight(300, "S1")]
    if chicane:
        r, a = 40.0, 30.0
        advance = 4 * r * math.sin(math.radians(a))
        first = [
            Straight(100, "S1a"),
            Arc(r, a, "c1"),
            Arc(r, -a, "c2"),
            Arc(r, -a, "c3"),
            Arc(r, a, "c4"),
            Straight(200 - advance, "S1b"),
        ]
    return build_track(
        "Test Triangle with chicane (synthetic)" if chicane else "Test Triangle (synthetic)",
        [*first, Arc(45, 120, "A"), Straight(None), Arc(45, 120, "B"), Straight(None), Arc(45, 120, "C")],
    )


@dataclass
class Run:
    order: list[Emitted]
    frames: list[CarFrame] = field(default_factory=list)
    infos: list[SessionInfo] = field(default_factory=list)
    completions: list[LapCompletion] = field(default_factory=list)
    laps: list[LapTrace] = field(default_factory=list)
    lap_uids: list[str | None] = field(default_factory=list)  # session uid of each assembled lap
    adapter: GT7Adapter = field(default_factory=GT7Adapter)

    def laps_by_session(self) -> dict[str | None, dict[int, LapTrace]]:
        out: dict[str | None, dict[int, LapTrace]] = {}
        for uid, lap in zip(self.lap_uids, self.laps, strict=True):
            out.setdefault(uid, {})[lap.lap_number] = lap
        return out


def run(packets: Iterable[CapturedPacket], adapter: GT7Adapter | None = None) -> Run:
    """Decode a stream and feed it through the lap assembler exactly as the session manager does: ``session_ended``
    or a SessionInfo with a new session uid ends the session (its lap in progress is flushed as incomplete); the next
    SessionInfo starts a new one."""
    r = Run(order=[], adapter=adapter or GT7Adapter())
    uid: str | None = None

    def on_lap(lap: LapTrace) -> None:
        r.laps.append(lap)
        r.lap_uids.append(uid)

    asm = LapAssembler(on_lap)
    for p in packets:
        for e in r.adapter.decode(p.data, p.t_recv_ns):
            r.order.append(e)
            if isinstance(e, GameEvent) and e.kind == EventKind.SESSION_ENDED:
                asm.flush()
                asm = LapAssembler(on_lap)
                uid = None
            elif isinstance(e, SessionInfo):
                if uid is not None and e.session_uid != uid:
                    asm.flush()
                    asm = LapAssembler(on_lap)
                uid = e.session_uid
                r.infos.append(e)
                asm.set_track_length(e.track_length_m)
            elif isinstance(e, CarFrame):
                r.frames.append(e)
                asm.feed(e)
            elif isinstance(e, LapCompletion):
                r.completions.append(e)
                asm.feed_completion(e)
    asm.flush()
    return r


def mutate(pkt: CapturedPacket, **changes: Any) -> CapturedPacket:
    """Re-encrypt a packet with some fields changed (keeps its IV)."""
    v, plain = P.decrypt(pkt.data)
    fields = P.unpack(v, plain)
    fields.update(changes)
    iv1 = int.from_bytes(pkt.data[0x40:0x44], "little")
    return CapturedPacket(pkt.t_recv_ns, pkt.src_port, P.encrypt(P.pack(v, fields), iv1))


def field_of(pkt: CapturedPacket, name: str) -> Any:
    v, plain = P.decrypt(pkt.data)
    return P.unpack(v, plain)[name]


_LAP_STARTS: dict[int, dict[int, int]] = {}  # id(packet list) -> lap -> first index (decrypting is slow)


def first_index_of_lap(packets: list[CapturedPacket], lap: int) -> int:
    starts = _LAP_STARTS.get(id(packets))
    if starts is None:
        starts = {}
        for i, p in enumerate(packets):
            starts.setdefault(int(field_of(p, "lap_count")), i)
        _LAP_STARTS[id(packets)] = starts
    return starts[lap]


def by_lap(laps: list[LapTrace]) -> dict[int, LapTrace]:
    return {lap.lap_number: lap for lap in laps}


def unmarked(**kw: Any) -> GT7Scenario:
    """A scenario without the synthetic marker, to exercise the real-data paths (derived track ids, the registry,
    session uids). Test-only: such streams are never written as captures."""
    return GT7Scenario(synthetic_marker=False, **kw)


@pytest.fixture(scope="module")
def stream(triangle: TrackGeometry) -> tuple[list[CapturedPacket], GT7GroundTruth]:
    sc = GT7Scenario(laps=3, driver_by_lap={2: DriverProfile(deviations={"A": CornerDeviation(brake_early_m=25)})})
    return generate_gt7_session(sc, triangle)


@pytest.fixture(scope="module")
def decoded(stream: tuple[list[CapturedPacket], GT7GroundTruth]) -> Run:
    return run(stream[0])


@pytest.fixture(scope="module")
def plain_stream(triangle: TrackGeometry) -> tuple[list[CapturedPacket], GT7GroundTruth]:
    return generate_gt7_session(unmarked(laps=3), triangle)


@pytest.mark.synthetic
def test_stream_decodes_without_errors(decoded: Run, stream: tuple[list[CapturedPacket], GT7GroundTruth]) -> None:
    st = decoded.adapter.stats
    assert st.packets == len(stream[0]) == st.decoded + st.ignored and st.rejected == st.errors == 0
    # the session opens at the OPEN_TICKS-th live packet; the stream's first packet cannot be live (nothing before it)
    assert st.ignored == st.by_type["no_session"] == OPEN_TICKS
    assert st.by_type["variant_C"] == len(stream[0]) and st.by_type["sessions"] == 1


@pytest.mark.synthetic
def test_lap_completions_on_counter_increment(
    decoded: Run, stream: tuple[list[CapturedPacket], GT7GroundTruth]
) -> None:
    truth = stream[1]
    assert [(c.lap_number, c.lap_time_ms) for c in decoded.completions] == sorted(truth.lap_times_ms.items())
    assert all(c.valid is None and c.sector_times_ms == [] for c in decoded.completions)
    assert truth.lap_times_ms[2] > truth.lap_times_ms[1]  # the injected mistake costs time


@pytest.mark.synthetic
def test_laps_assemble_complete_and_clean(decoded: Run, stream: tuple[list[CapturedPacket], GT7GroundTruth]) -> None:
    truth = stream[1]
    laps = by_lap(decoded.laps)
    for n, ms in truth.lap_times_ms.items():
        assert laps[n].lap_time_ms == ms and laps[n].clean, (n, laps[n].flags)
        d = laps[n].channels["distance_m"]
        assert d[0] < 2.0 and abs(d[-1] - truth.track.length_m) < 3.0
        assert np.all(np.isfinite(laps[n].channels["lap_time_ms"]))  # derived/C timer on every row
    assert LapFlag.INCOMPLETE in laps[4].flags  # the tail into lap 4 was cut by the end of the stream


@pytest.mark.synthetic
def test_distance_integration_accuracy(decoded: Run, stream: tuple[list[CapturedPacket], GT7GroundTruth]) -> None:
    truth = stream[1]
    errs = np.array(
        [
            f.lap_distance_m - truth.distance_by_packet_id[f.frame_id][1]
            for f in decoded.frames
            if f.lap_distance_m is not None and f.frame_id in truth.distance_by_packet_id
        ]
    )
    length = truth.track.length_m
    assert len(errs) > 0.9 * len(truth.distance_by_packet_id)
    assert np.abs(errs).max() < 0.02 * length  # requirement: < 2 %
    assert np.abs(errs).max() < 2.0  # measured: < 1.5 m (anchor sits up to one tick past the line)


@pytest.mark.synthetic
def test_track_identity_learned_from_two_agreeing_laps(
    decoded: Run, stream: tuple[list[CapturedPacket], GT7GroundTruth]
) -> None:
    truth = stream[1]
    tid = decoded.infos[-1].track_id
    assert tid is not None and tid.startswith("gt7:sf:")
    sig = TrackSignature.parse(tid)
    assert sig is not None
    assert math.hypot(sig.sf_x_m - truth.sf_xz[0], sig.sf_z_m - truth.sf_xz[1]) < 10
    assert abs(sig.length_m - truth.track.length_m) <= 10
    assert 320 <= sig.turn_deg <= 360  # a closed circuit turns 360 deg net; no chicanes, minus the dead band
    assert decoded.infos[-1].track_length_m == pytest.approx(truth.track.length_m, abs=3.0)
    # one lap is never enough to define a new track: the id appears with the second (agreeing) lap's completion,
    # published *before* that completion
    i_info = next(i for i, e in enumerate(decoded.order) if isinstance(e, SessionInfo) and e.track_id == tid)
    i_comp1, i_comp2 = (
        next(i for i, e in enumerate(decoded.order) if isinstance(e, LapCompletion) and e.lap_number == n)
        for n in (1, 2)
    )
    assert i_comp1 < i_info < i_comp2
    assert decoded.frames[0].lap_distance_m is None  # out-lap: not anchored


@pytest.mark.synthetic
def test_synthetic_sessions_never_feed_the_track_registry(decoded: Run) -> None:
    assert decoded.infos[-1].track_id is not None  # identified for the session itself...
    assert decoded.adapter.known_track_ids == []  # ...but synthetic geometry never reaches real track identity


@pytest.mark.synthetic
def test_known_track_registry_keeps_ids_stable(triangle: TrackGeometry, decoded: Run) -> None:
    tid = decoded.infos[-1].track_id
    assert tid is not None
    shifted, _ = generate_gt7_session(GT7Scenario(laps=1, origin_xz=(-312.0 + 16.0, 1187.0 - 13.0)), triangle)
    seeded = run(shifted, GT7Adapter(known_track_ids=[tid]))
    assert seeded.infos[-1].track_id == tid  # one lap matching the registry identifies the track
    unseeded = run(generate_gt7_session(GT7Scenario(laps=2, origin_xz=(-312.0 + 16.0, 1187.0 - 13.0)), triangle)[0])
    assert unseeded.infos[-1].track_id not in (None, tid)  # without the registry the rounding differs


@pytest.mark.synthetic
def test_chicane_layout_sharing_the_start_line_gets_its_own_track_id() -> None:
    """Monza / Monza No Chicane, Le Mans / No Chicane: same start line, lengths closer than the integration drift.
    The total-turning component of the signature keeps them apart (and a re-drive of each keeps its own id)."""
    plain, chic = _triangle(chicane=False), _triangle(chicane=True)
    assert 0 < chic.length_m - plain.length_m < 0.01 * plain.length_m
    a = GT7Adapter()
    id_plain = run(generate_gt7_session(unmarked(laps=2), plain)[0], a).infos[-1].track_id
    later = unmarked(laps=2, loading_packets=30, first_packet_id=200_000, start_ns=2_000_000_000_000)
    id_chic = run(generate_gt7_session(later, chic)[0], a).infos[-1].track_id
    assert id_plain is not None and id_chic is not None and id_plain != id_chic
    sig_p, sig_c = TrackSignature.parse(id_plain), TrackSignature.parse(id_chic)
    assert sig_p is not None and sig_c is not None
    assert sig_p.near_line(sig_c.sf_x_m, sig_c.sf_z_m, sig_c.heading_deg)  # same start line...
    assert abs(sig_c.length_m - sig_p.length_m) <= 10  # ...same length on the id grid...
    assert sig_c.turn_deg - sig_p.turn_deg >= 80  # ...told apart by the chicane's turning
    assert a.known_track_ids == [id_plain, id_chic]
    # a later session of each layout, from a fresh process seeded with the registry: a different driver weaving
    # 2 m either side of the line, crossing the line 15 m from where it was learned - one lap identifies it
    for track, tid in ((plain, id_plain), (chic, id_chic)):
        sc = unmarked(laps=1, line_wander_m=2.0, origin_xz=(-312.0 + 12.0, 1187.0 - 9.0))
        assert run(generate_gt7_session(sc, track)[0], GT7Adapter(a.known_track_ids)).infos[-1].track_id == tid


@pytest.mark.synthetic
@pytest.mark.parametrize("variant", ["A", "B", "~"])
def test_every_variant_yields_the_same_laps(variant: str, triangle: TrackGeometry) -> None:
    packets, truth = generate_gt7_session(GT7Scenario(laps=2, variant=variant), triangle)
    assert all(len(p.data) == P.VARIANTS[variant].size for p in packets)
    r = run(packets)
    laps = by_lap(r.laps)
    assert [laps[n].lap_time_ms for n in (1, 2)] == [truth.lap_times_ms[1], truth.lap_times_ms[2]]
    assert laps[1].clean and laps[2].clean
    steer = laps[1].channels["steering"]
    if variant == "A":
        assert np.all(np.isnan(steer))
    else:
        assert np.nanmax(np.abs(steer)) > 0.05  # corners are steered
    # A/B/~ have no game lap timer: the derived one tracks the official lap time within a tick
    assert laps[2].channels["lap_time_ms"][-1] == pytest.approx(truth.lap_times_ms[2], abs=20)


@pytest.mark.synthetic
def test_session_clock_does_not_advance_while_paused(triangle: TrackGeometry) -> None:
    sc = GT7Scenario(laps=2, pause=gt7_coaching_demo().pause)
    assert sc.pause is not None
    sc.pause.lap = 2
    packets, truth = generate_gt7_session(sc, triangle)
    r = run(packets)
    paused = [f for f in r.frames if f.quality & FrameQuality.PAUSED]
    assert len(paused) == 180 and len({f.session_time_s for f in paused}) == 1
    laps = by_lap(r.laps)
    assert laps[2].clean and laps[2].lap_time_ms == truth.lap_times_ms[2]
    assert np.max(np.diff(laps[2].channels["session_time_s"])) < 0.02  # no gap across the pause


@pytest.mark.synthetic
def test_joining_mid_lap_leaves_distance_unknown_until_the_line(
    stream: tuple[list[CapturedPacket], GT7GroundTruth],
) -> None:
    packets, truth = stream
    i2 = first_index_of_lap(packets, 2)
    r = run(packets[i2 - 600 :])  # join 10 s before the end of lap 1
    assert all(f.lap_distance_m is None for f in r.frames if f.lap_number == 1)
    laps = by_lap(r.laps)
    assert laps[2].clean and laps[2].lap_time_ms == truth.lap_times_ms[2]
    assert [c.lap_number for c in r.completions] == [1, 2, 3]  # lap 1's official time is still reported...
    # ...and lap 1 is still stored: the game's time, no trace (never placed on the track), never a reference
    assert laps[1].lap_time_ms == truth.lap_times_ms[1] and laps[1].n == 0
    assert {LapFlag.NO_TRACE, LapFlag.INCOMPLETE} <= laps[1].flags and not laps[1].clean


@pytest.mark.synthetic
def test_small_packet_loss_is_bridged(stream: tuple[list[CapturedPacket], GT7GroundTruth]) -> None:
    packets, truth = stream
    i = first_index_of_lap(packets, 2) + 900
    r = run(packets[:i] + packets[i + 3 :])  # 3 packets (50 ms) lost mid-lap
    laps = by_lap(r.laps)
    assert laps[2].clean and abs(laps[2].channels["distance_m"][-1] - truth.track.length_m) < 3.0


@pytest.mark.synthetic
def test_long_stream_gap_unanchors_until_the_next_crossing(stream: tuple[list[CapturedPacket], GT7GroundTruth]) -> None:
    packets, truth = stream
    i = first_index_of_lap(packets, 2) + 300
    r = run(packets[:i] + packets[i + 600 :])  # 10 s gap mid-lap 2
    assert r.adapter.stats.by_type["stream_gap"] == 1
    assert next(c for c in r.completions if c.lap_number == 2).valid is False  # its trace stops at the gap
    laps = by_lap(r.laps)
    assert not laps[2].clean  # truncated
    assert laps[3].clean and laps[3].lap_time_ms == truth.lap_times_ms[3]


@pytest.mark.synthetic
@pytest.mark.parametrize("seeded", [False, True])
def test_gap_before_the_track_is_known_invalidates_the_truncated_lap(
    seeded: bool, stream: tuple[list[CapturedPacket], GT7GroundTruth], decoded: Run
) -> None:
    """A 7 s Wi-Fi drop 10 s into lap 1, before the track length is known: the LapAssembler cannot see that the
    trace is short, so the adapter must not let the lap pass as clean - it could become the fastest reference."""
    packets, truth = stream
    cut = first_index_of_lap(packets, 1) + 600
    known = [decoded.infos[-1].track_id] if seeded else []
    r = run(packets[:cut] + packets[cut + 420 :], GT7Adapter([t for t in known if t]))
    lap1 = next(c for c in r.completions if c.lap_number == 1)
    assert lap1.valid is False and lap1.lap_time_ms == truth.lap_times_ms[1]
    laps = by_lap(r.laps)
    assert not laps[1].clean and LapFlag.INVALID in laps[1].flags
    assert laps[2].clean and laps[3].clean
    assert r.infos[-1].track_id is not None and r.infos[-1].track_length_m == pytest.approx(
        truth.track.length_m, abs=3.0
    )


@pytest.mark.synthetic
def test_packet_id_restart_is_a_new_session(stream: tuple[list[CapturedPacket], GT7GroundTruth]) -> None:
    packets, _ = stream
    i = first_index_of_lap(packets, 2) + 300
    restarted = packets[:i] + [mutate(p, packet_id=5 + k) for k, p in enumerate(packets[i:])]
    r = run(restarted)
    st = r.adapter.stats.by_type
    assert st["stream_restart"] == 1 and st["retry_stream_restart"] == 1 and st["sessions"] == 2
    assert r.adapter.stats.ignored == st["no_session"] == OPEN_TICKS + OPEN_TICKS - 1  # see the test above
    assert [e.code for e in r.order if isinstance(e, GameEvent)] == ["retry_stream_restart"]
    assert by_lap(r.laps)[3].clean


@pytest.mark.synthetic
def test_retry_without_a_loading_screen_starts_a_new_session(triangle: TrackGeometry) -> None:
    """The driver restarts during lap 2, right after completing lap 1, and drives laps 1 and 2 again - no loading
    screen, packet ids and time of day continuous: only the lap counter going back reveals the retry. The re-driven
    laps must land in a new session (lap numbers repeat) with their completions."""
    a_sc = unmarked(laps=1, tail_s=8.0)
    first, t_a = generate_gt7_session(a_sc, triangle)
    end_tod = int(field_of(first[-1], "time_of_day_ms"))
    b_sc = unmarked(
        laps=2,
        first_packet_id=a_sc.first_packet_id + len(first),
        start_ns=first[-1].t_recv_ns + 16_666_667,
        time_of_day_start_ms=end_tod + 17,
    )
    second, t_b = generate_gt7_session(b_sc, triangle)
    r = run(first + second)
    st = r.adapter.stats.by_type
    assert st["retry_lap_reset"] == 1 and st["sessions"] == 2
    assert "retry_time_rewind" not in st and "retry_stream_restart" not in st
    assert [(c.lap_number, c.lap_time_ms) for c in r.completions] == [
        (1, t_a.lap_times_ms[1]),
        (1, t_b.lap_times_ms[1]),
        (2, t_b.lap_times_ms[2]),
    ]
    sessions = r.laps_by_session()
    # each session's uid is the packet that opened it: OPEN_TICKS live packets after the start / the retry
    uid_a, uid_b = (f"gt7:{first[OPEN_TICKS].t_recv_ns}", f"gt7:{second[OPEN_TICKS - 1].t_recv_ns}")
    assert set(sessions) == {uid_a, uid_b}
    assert sessions[uid_a][1].clean and sessions[uid_a][1].lap_time_ms == t_a.lap_times_ms[1]
    assert not sessions[uid_a][2].clean  # cut short by the retry
    assert [(n, lap.lap_time_ms, lap.clean) for n, lap in sorted(sessions[uid_b].items()) if n <= 2] == [
        (1, t_b.lap_times_ms[1], True),
        (2, t_b.lap_times_ms[2], True),
    ]


@pytest.mark.synthetic
def test_teleport_unanchors_distance(stream: tuple[list[CapturedPacket], GT7GroundTruth]) -> None:
    packets, _ = stream
    i = first_index_of_lap(packets, 2) + 400
    x, y, z = field_of(packets[i], "position")
    tampered = list(packets)
    tampered[i] = mutate(packets[i], position=(x + 250.0, y, z))
    r = run(tampered)
    assert r.adapter.stats.by_type["teleport"] == 1
    lap2 = [f for f in r.frames if f.lap_number == 2]
    assert lap2[399].lap_distance_m is not None and all(f.lap_distance_m is None for f in lap2[400:])
    assert next(c for c in r.completions if c.lap_number == 2).valid is False
    assert not by_lap(r.laps)[2].clean and by_lap(r.laps)[3].clean


@pytest.mark.synthetic
@pytest.mark.parametrize(
    "corrupt",
    [
        {"speed": float("nan")},
        {"position": (float("nan"), 0.0, 0.0)},
        {"velocity": (0.0, 0.0, float("inf"))},
    ],
    ids=["speed", "position", "velocity"],
)
def test_non_finite_motion_is_bridged_like_a_lost_packet(
    corrupt: dict[str, Any], stream: tuple[list[CapturedPacket], GT7GroundTruth], decoded: Run
) -> None:
    packets, truth = stream
    bad = list(packets)
    for lap in (1, 3):  # once before the track is known, once after
        i = first_index_of_lap(packets, lap) + 600
        bad[i] = mutate(packets[i], **corrupt)
    r = run(bad)
    st = r.adapter.stats
    assert st.by_type["non_finite_motion"] == 2 and st.errors == 0 and st.ignored == OPEN_TICKS + 2
    assert [(c.lap_number, c.lap_time_ms, c.valid) for c in r.completions] == [
        (n, ms, None) for n, ms in sorted(truth.lap_times_ms.items())
    ]
    laps = by_lap(r.laps)
    for n in (1, 2, 3):
        assert laps[n].clean, (n, laps[n].flags)
        d = laps[n].channels["distance_m"]
        assert np.all(np.isfinite(d)) and abs(d[-1] - truth.track.length_m) < 3.0
    assert r.infos[-1].track_id == decoded.infos[-1].track_id


@pytest.mark.synthetic
def test_bridged_laps_identify_a_known_track_but_never_teach_a_new_one(
    plain_stream: tuple[list[CapturedPacket], GT7GroundTruth],
) -> None:
    packets, truth = plain_stream
    learned = run(packets).infos[-1].track_id
    assert learned is not None

    def lossy(laps: Iterable[int], lost: int) -> list[CapturedPacket]:
        drop = {first_index_of_lap(packets, n) + 900 + k for n in laps for k in range(lost)}
        return [p for i, p in enumerate(packets) if i not in drop]

    # 10 packets (~170 ms) lost in every lap: too lossy to learn a new track from...
    unseeded = run(lossy((1, 2, 3), 10))
    assert all(i.track_id is None for i in unseeded.infos)
    assert all(by_lap(unseeded.laps)[n].clean for n in (1, 2, 3))  # ...but the laps themselves are fine
    # ...yet good enough to recognise a known one, from the first lap
    seeded = run(lossy((1,), 10), GT7Adapter([learned]))
    i_info = next(i for i, e in enumerate(seeded.order) if isinstance(e, SessionInfo) and e.track_id == learned)
    i_comp1 = next(i for i, e in enumerate(seeded.order) if isinstance(e, LapCompletion) and e.lap_number == 1)
    assert i_info < i_comp1
    # a 40-packet (0.67 s) gap is too long to trust the bridged distance: identified one lap later
    late = run(lossy((1,), 40), GT7Adapter([learned]))
    i_info = next(i for i, e in enumerate(late.order) if isinstance(e, SessionInfo) and e.track_id == learned)
    i_comp1 = next(i for i, e in enumerate(late.order) if isinstance(e, LapCompletion) and e.lap_number == 1)
    assert i_info > i_comp1 and late.infos[-1].track_length_m == pytest.approx(truth.track.length_m, abs=3.0)


@pytest.mark.synthetic
def test_one_odd_lap_cannot_define_a_track(plain_stream: tuple[list[CapturedPacket], GT7GroundTruth]) -> None:
    """The first lap measures 8 % long (a wide, sliding first lap - or a beginner's first try): it must not become the
    track's length, which would make every later lap on the circuit 'incomplete'."""
    packets, truth = plain_stream
    i1, i2 = first_index_of_lap(packets, 1), first_index_of_lap(packets, 2)

    def faster(p: CapturedPacket) -> CapturedPacket:  # lap distance integrates the velocity (module docstring)
        vx, vy, vz = field_of(p, "velocity")
        return mutate(p, speed=1.08 * field_of(p, "speed"), velocity=(1.08 * vx, 1.08 * vy, 1.08 * vz))

    odd = [faster(p) if i1 < i < i2 else p for i, p in enumerate(packets)]
    r = run(odd)
    assert by_lap(r.laps)[1].channels["distance_m"][-1] > 1.07 * truth.track.length_m
    sig = TrackSignature.parse(r.infos[-1].track_id or "")
    assert sig is not None and abs(sig.length_m - truth.track.length_m) <= 10  # learned from laps 2 and 3
    assert r.infos[-1].track_length_m == pytest.approx(truth.track.length_m, abs=3.0)
    assert by_lap(r.laps)[2].clean and by_lap(r.laps)[3].clean


@pytest.fixture(scope="module")
def park_stream() -> tuple[list[CapturedPacket], GT7GroundTruth]:
    return generate_gt7_session(unmarked(laps=2, tail_s=1.0), pitwall_park())


@pytest.fixture(scope="module")
def park_signature(park_stream: tuple[list[CapturedPacket], GT7GroundTruth]) -> TrackSignature:
    sig = TrackSignature.parse(run(park_stream[0]).infos[-1].track_id or "")
    assert sig is not None
    return sig


@pytest.mark.synthetic
@pytest.mark.parametrize(("extra_m", "matched"), [(55.0, True), (0.02 * 3964.0, False)])
def test_registry_length_longer_than_the_driven_laps_never_makes_them_incomplete(
    extra_m: float,
    matched: bool,
    park_stream: tuple[list[CapturedPacket], GT7GroundTruth],
    park_signature: TrackSignature,
) -> None:
    """A registry length learned from longer laps (wider lines, another driver): within the match tolerance the
    session keeps the registry id but publishes its own, shorter measurement; beyond it, a new id is learned. Either
    way no lap on Pitwall Park (3.96 km, where the end-of-lap tolerance is 60 m) becomes incomplete."""
    packets, truth = park_stream
    sig = park_signature
    longer = TrackSignature(sig.sf_x_m, sig.sf_z_m, sig.heading_deg, sig.length_m + round(extra_m), sig.turn_deg)
    r = run(packets, GT7Adapter([longer.track_id]))
    assert (r.infos[-1].track_id == longer.track_id) is matched
    assert r.infos[-1].track_length_m == pytest.approx(truth.track.length_m, abs=3.0)
    laps = by_lap(r.laps)
    assert laps[1].clean and laps[2].clean, (laps[1].flags, laps[2].flags)


@pytest.mark.synthetic
def test_late_last_lap_time_is_held_until_it_updates(stream: tuple[list[CapturedPacket], GT7GroundTruth]) -> None:
    packets, truth = stream
    i3 = first_index_of_lap(packets, 3)
    stale = truth.lap_times_ms[1]  # lap 2 ended, but last_lap_ms still shows lap 1 for two more packets
    late = list(packets)
    for k in range(i3, i3 + 3):
        late[k] = mutate(packets[k], last_lap_ms=stale)
    r = run(late)
    assert r.adapter.stats.by_type["lap_time_late"] == 1
    comp = next(c for c in r.completions if c.lap_number == 2)
    assert comp.lap_time_ms == truth.lap_times_ms[2]
    i_comp = r.order.index(comp)
    i_lap3 = next(i for i, e in enumerate(r.order) if isinstance(e, CarFrame) and e.lap_number == 3)
    assert i_comp < i_lap3  # held frames are released after the completion
    assert by_lap(r.laps)[2].lap_time_ms == truth.lap_times_ms[2] and by_lap(r.laps)[3].clean


@pytest.mark.synthetic
def test_missing_last_lap_time_stays_unknown(stream: tuple[list[CapturedPacket], GT7GroundTruth]) -> None:
    packets, truth = stream
    i3 = first_index_of_lap(packets, 3)
    late = list(packets)
    for k in range(i3, i3 + 40):
        late[k] = mutate(packets[k], last_lap_ms=truth.lap_times_ms[1])
    r = run(late)
    assert r.adapter.stats.by_type["lap_time_missing"] == 1
    assert next(c for c in r.completions if c.lap_number == 2).lap_time_ms is None
    assert not by_lap(r.laps)[2].clean and by_lap(r.laps)[3].clean


@pytest.mark.synthetic
def test_last_lap_time_leading_the_counter_by_one_tick(stream: tuple[list[CapturedPacket], GT7GroundTruth]) -> None:
    packets, truth = stream
    i3 = first_index_of_lap(packets, 3)
    early = list(packets)
    early[i3 - 1] = mutate(packets[i3 - 1], last_lap_ms=truth.lap_times_ms[2])
    r = run(early)
    assert [(c.lap_number, c.lap_time_ms) for c in r.completions] == sorted(truth.lap_times_ms.items())
    laps = by_lap(r.laps)
    assert laps[2].lap_time_ms == truth.lap_times_ms[2] and laps[3].clean


@pytest.mark.synthetic
def test_final_lap_without_counter_increment(stream: tuple[list[CapturedPacket], GT7GroundTruth]) -> None:
    """The F1 25 lesson: the final race lap may be timed without the lap number advancing."""
    packets, truth = stream
    i4 = first_index_of_lap(packets, 4)
    final = packets[:i4] + [mutate(p, lap_count=3) for p in packets[i4:]]
    r = run(final)
    assert [(c.lap_number, c.lap_time_ms) for c in r.completions] == sorted(truth.lap_times_ms.items())
    assert all(f.quality & FrameQuality.NOT_RACING for f in r.frames[-len(packets[i4:]) + 1 :])
    assert sorted(by_lap(r.laps)) == [1, 2, 3] and by_lap(r.laps)[3].clean


@pytest.mark.synthetic
def test_out_lap_counter_flip_away_from_the_line_marks_lap_misaligned(
    stream: tuple[list[CapturedPacket], GT7GroundTruth],
) -> None:
    packets, truth = stream
    i1 = first_index_of_lap(packets, 1)
    flipped = packets[: i1 - 200] + [mutate(p, lap_count=1) for p in packets[i1 - 200 : i1]] + packets[i1:]
    r = run(flipped)
    assert r.adapter.stats.by_type["anchor_mismatch"] == 1
    lap1 = next(c for c in r.completions if c.lap_number == 1)
    assert lap1.valid is False and lap1.lap_time_ms == truth.lap_times_ms[1]
    laps = by_lap(r.laps)
    assert not laps[1].clean and LapFlag.INVALID in laps[1].flags
    assert laps[2].clean and laps[3].clean  # the track is learned from laps 2 and 3 instead
    assert r.infos[-1].track_id is not None


@pytest.mark.synthetic
def test_counter_increment_away_from_the_line_does_not_anchor_the_next_lap(
    stream: tuple[list[CapturedPacket], GT7GroundTruth],
) -> None:
    """Lap 3's counter increments 100 m (~2.5 s) before the learned line: lap 3 must not be anchored there (its
    distance would be offset by 100 m) - it stays unknown until the next real crossing."""
    packets, _ = stream
    i3 = first_index_of_lap(packets, 3)
    early = packets[: i3 - 140] + [mutate(p, lap_count=3) for p in packets[i3 - 140 : i3]] + packets[i3:]
    r = run(early)
    assert r.adapter.stats.by_type["sf_crossing_mismatch"] == 1
    assert all(f.lap_distance_m is None for f in r.frames if f.lap_number == 3)
    lap3 = by_lap(r.laps)[3]  # timed by the game, never placed on the track: its time only, never a reference
    assert lap3.n == 0 and LapFlag.NO_TRACE in lap3.flags and not lap3.clean


@pytest.mark.synthetic
def test_rolling_race_start_anchors_lap_1_as_a_race_start_lap(triangle: TrackGeometry) -> None:
    """A rolling start incremented the lap counter at the line on every real PS5 race (within 1 m of the later
    crossings): race lap 1 is anchored there (provisionally while the line is unknown), stored with the game's time,
    and flagged as a race-start lap - the game times it from the start signal, so it is never a reference."""
    packets, truth = generate_gt7_session(GT7Scenario(laps=2, total_laps=2), triangle)
    r = run(packets)
    lap1 = [f for f in r.frames if f.lap_number == 1]
    assert lap1[0].lap_distance_m == pytest.approx(0.0, abs=2.0) and all(f.lap_distance_m is not None for f in lap1)
    comps = {c.lap_number: c for c in r.completions}
    assert comps[1].race_start is True and comps[2].race_start is None and comps[1].valid is None
    laps = by_lap(r.laps)
    assert laps[1].lap_time_ms == truth.lap_times_ms[1] and LapFlag.RACE_START in laps[1].flags and not laps[1].clean
    assert abs(laps[1].channels["distance_m"][-1] - truth.track.length_m) < 3.0
    assert laps[2].clean and laps[2].lap_time_ms == truth.lap_times_ms[2]
    assert all(f.quality & FrameQuality.NOT_RACING for f in r.frames if f.lap_number == 3)  # after the flag


def test_standing_start_is_not_anchored_but_lap_1_keeps_its_time() -> None:
    a = GT7Adapter()
    asm_laps: list[LapTrace] = []
    asm = LapAssembler(asm_laps.append)
    out: list[Emitted] = []
    pid = 1
    for k in range(60):  # on the grid, lap 0, engine running
        grid = _packet(packet_id=pid, lap_count=0, total_laps=3, speed=0.0, engine_rpm=3000.0 + k, position=(0, 0, -50))
        out += a.decode(grid, pid)
        pid += 1
    z = -50.0
    for k in range(600):  # lights out: lap 1 while stationary, then accelerating
        v = 0.1 * k
        z += v / 60
        out += a.decode(_packet(packet_id=pid, lap_count=1, total_laps=3, speed=v, position=(0, 0, z)), pid)
        pid += 1
    frames = [e for e in out if isinstance(e, CarFrame) and e.lap_number == 1]
    assert len(frames) == 600 and all(f.lap_distance_m is None for f in frames)
    assert a.stats.by_type["lap_start"] == 1
    for e in out:
        if isinstance(e, CarFrame):
            asm.feed(e)
    comp = LapCompletion(game=Game.GT7, t_recv_ns=pid, lap_number=1, lap_time_ms=95_000, race_start=True, untraced=True)
    asm.feed_completion(comp)  # what the adapter emits at the line (the lap 1 -> 2 crossing)
    (lap1,) = asm_laps
    assert lap1.lap_time_ms == 95_000 and lap1.n == 0
    assert {LapFlag.NO_TRACE, LapFlag.INCOMPLETE, LapFlag.RACE_START} <= lap1.flags and not lap1.clean


@pytest.mark.synthetic
def test_two_sessions_in_one_adapter_share_the_track_registry(triangle: TrackGeometry) -> None:
    first, _ = generate_gt7_session(unmarked(laps=2), triangle)
    second, _ = generate_gt7_session(unmarked(laps=1, loading_packets=30, first_packet_id=200_000), triangle)
    a = GT7Adapter()
    r1 = run(first, a)
    a_tid = r1.infos[-1].track_id
    assert a_tid is not None and a.known_track_ids == [a_tid]
    r2 = run(second, a)
    uids = {i.session_uid for i in r2.infos}
    assert len(uids) == 1 and uids != {r1.infos[-1].session_uid} and r2.infos[-1].track_id == a_tid
    assert a.stats.by_type["loading"] == 30


# =============================================================================================== end to end
@pytest.mark.synthetic
def test_end_to_end_replay_through_sessions_and_analysis(tmp_path: Path) -> None:
    """Encrypted synthetic stream -> GT7 adapter -> session manager -> laps -> SQLite -> track model ->
    reference comparison -> coaching observations (known injected mistakes must be recovered)."""
    from pitwall.config import Settings
    from pitwall.core.runtime import Runtime
    from pitwall.core.session import SessionManager
    from pitwall.ingest.router import PacketRouter
    from pitwall.storage import repo

    cap = tmp_path / "gt7.pwcap"
    truth = write_gt7_capture(cap)
    reader = CaptureReader(cap)
    assert reader.meta.synthetic and reader.meta.game_hint == "gt7"
    rt = Runtime(Settings(data_dir=tmp_path / "data", llm_enabled=False))
    try:
        sessions = SessionManager(
            rt.writer,
            rt.live,
            rt.worker,
            source="replay:gt7.pwcap",
            synthetic=True,
            overrides={"track_name": truth.track.name, "scenario": "gt7-coaching-demo"},
        )
        router = PacketRouter([GT7Adapter()], sessions, rt.live)
        for pkt in reader:
            router.handle(pkt)
        router.finish()
        rt.worker.join()
        rt.writer.flush()
        with rt.db.read() as c:
            sid = repo.latest_session_id(c)
            assert sid
            sess = repo.get_session(c, sid)
            laps = repo.list_laps(c, sid)
            obs = repo.list_observations(c, sid)
            assert repo.derived_track_ids(c, ("gt7",)) == []  # synthetic geometry never becomes a real track
        assert (
            sess and sess["game"] == "gt7" and sess["synthetic"] and sess["track_id"] == "synthetic:gt7-coaching-demo"
        )
        timed = [lap for lap in laps if lap["lap_number"] <= 5]
        assert [(lap["lap_number"], lap["lap_time_ms"], lap["clean"]) for lap in timed] == [
            (n, truth.lap_times_ms[n], True) for n in range(1, 6)
        ]
        kinds = {(o["lap_number"], o["kind"]) for o in obs}
        assert (3, "brake_early") in kinds and (4, "low_min_speed") in kinds
        assert not any(o["lap_number"] in (1, 2, 5) for o in obs)  # clean laps (incl. the paused one): no advice
        assert rt.worker.errors == 0 and rt.writer.errors == 0
    finally:
        rt.close()


def test_captures_always_carry_the_synthetic_marker(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="synthetic marker"):
        write_gt7_capture(tmp_path / "x.pwcap", unmarked(laps=1))
    assert not (tmp_path / "x.pwcap").exists()


@pytest.mark.synthetic
def test_end_to_end_derived_track_id_round_trips_through_the_database(tmp_path: Path, triangle: TrackGeometry) -> None:
    """The real-data path (no synthetic marker, non-synthetic session manager, tmp database): the derived track id
    is stored with the session, comes back from ``derived_track_ids`` to seed the next process's adapter, and a
    later session there - crossing the line 20 m away - gets the same id, so both share one track's laps."""
    from pitwall.config import Settings
    from pitwall.core.runtime import Runtime
    from pitwall.core.session import SessionManager
    from pitwall.ingest.router import PacketRouter
    from pitwall.storage import repo

    rt = Runtime(Settings(data_dir=tmp_path / "data", llm_enabled=False))
    try:

        def drive(packets: list[CapturedPacket], known: list[str]) -> None:
            sessions = SessionManager(rt.writer, rt.live, rt.worker, source="test:gt7-unmarked")
            router = PacketRouter([GT7Adapter(known_track_ids=known)], sessions, rt.live)
            for pkt in packets:
                router.handle(pkt)
            router.finish()
            rt.worker.join()
            rt.writer.flush()

        first, truth = generate_gt7_session(unmarked(laps=3), triangle)
        drive(first, [])
        with rt.db.read() as c:
            known = repo.derived_track_ids(c, ("gt7",))
        assert len(known) == 1 and TrackSignature.parse(known[0]) is not None
        later = unmarked(laps=2, origin_xz=(-312.0 + 16.0, 1187.0 - 13.0), start_ns=5_000_000_000_000)
        drive(generate_gt7_session(later, triangle)[0], known)
        with rt.db.read() as c:
            rows = c.execute("SELECT id, track_id, synthetic, track_length_m FROM sessions").fetchall()
            assert len(rows) == 2
            assert {(r["track_id"], r["synthetic"]) for r in rows} == {(known[0], 0)}
            assert all(abs(r["track_length_m"] - truth.track.length_m) < 3.0 for r in rows)
            clean = repo.clean_laps_for(c, "gt7", known[0], None, limit=10)
            assert len(clean) == 5 and {lap["session_id"] for lap in clean} == {r["id"] for r in rows}
            assert repo.load_track_model(c, "gt7", known[0]) is not None
            assert repo.derived_track_ids(c, ("gt7",)) == known
        assert rt.worker.errors == 0 and rt.writer.errors == 0
    finally:
        rt.close()


# =============================================================================================== heartbeat
def _receiver() -> tuple[socket.socket, int]:
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(2.0)
    return rx, int(rx.getsockname()[1])


def test_heartbeat_sends_the_variant_byte_periodically() -> None:
    rx, port = _receiver()
    hb = GT7Heartbeat("127.0.0.1", "C", port=port, interval_s=0.05)
    try:
        hb.start()
        got = [rx.recvfrom(16)[0] for _ in range(3)]
        assert got == [b"C"] * 3
        hb.set_variant("~")
        deadline = time.monotonic() + 2
        while rx.recvfrom(16)[0] != b"~":
            assert time.monotonic() < deadline
        snap = hb.snapshot()
        assert snap["running"] and snap["variant"] == "~" and snap["sent"] >= 4 and snap["errors"] == 0
        assert snap["target"] == f"127.0.0.1:{port}"
    finally:
        hb.stop()
        rx.close()
    assert not hb.running


def test_heartbeat_poke_sends_immediately() -> None:
    rx, port = _receiver()
    hb = GT7Heartbeat("127.0.0.1", "A", port=port, interval_s=60.0)
    try:
        hb.start()
        assert rx.recvfrom(16)[0] == b"A"  # one on start
        hb.poke()
        assert rx.recvfrom(16)[0] == b"A"  # and one on demand, long before the 60 s interval
    finally:
        hb.stop()
        rx.close()


class _FakeSocket:
    """Records calls; ``fail_send`` / ``fail_setsockopt`` make those calls raise like a real socket would."""

    def __init__(self, log: list[str], fail_send: bool = True, fail_setsockopt: bool = False) -> None:
        self.log = log
        self.fail_send = fail_send
        self.fail_setsockopt = fail_setsockopt

    def setsockopt(self, *args: Any) -> None:
        self.log.append(f"setsockopt{args[1:]}")
        if self.fail_setsockopt:
            raise OSError(22, "Invalid argument")

    def sendto(self, data: bytes, addr: tuple[str, int]) -> int:
        self.log.append(f"sendto {addr}")
        if self.fail_send:
            raise OSError(65, "No route to host")
        return len(data)

    def close(self) -> None:
        self.log.append("close")


def test_heartbeat_survives_an_unreachable_console() -> None:
    log: list[str] = []
    made = threading.Semaphore(0)

    def factory() -> socket.socket:
        made.release()
        return _FakeSocket(log)  # type: ignore[return-value]

    hb = GT7Heartbeat("192.168.1.50", port=33739, interval_s=0.02, socket_factory=factory)
    hb.start()
    deadline = time.monotonic() + 3
    while hb.errors < 5:
        assert time.monotonic() < deadline, "heartbeat stopped retrying"
        time.sleep(0.01)
    assert hb.running and hb.sent == 0 and "No route to host" in (hb.last_error or "")
    assert made.acquire(timeout=0) and log.count("close") >= 1  # a fresh socket after each failure
    hb.stop()
    assert not hb.running
    assert hb.send_once() is False  # also safe to call directly, never raises


def test_heartbeat_broadcast_mode_and_validation() -> None:
    log: list[str] = []
    hb = GT7Heartbeat(None, "B", interval_s=1.0, socket_factory=lambda: _FakeSocket(log))  # type: ignore[arg-type,return-value]
    assert hb.console_ip is None and hb.snapshot()["target"] == "255.255.255.255:33739"
    hb.send_once()
    assert f"setsockopt({socket.SO_BROADCAST}, 1)" in log and "sendto ('255.255.255.255', 33739)" in log
    hb.set_console_ip(" 10.0.0.7 ")
    assert hb.console_ip == "10.0.0.7"
    for bad_ip in ("ps5.local", "999.1.1.1", "::1"):
        with pytest.raises(ValueError):
            GT7Heartbeat(bad_ip)
    with pytest.raises(ValueError):
        GT7Heartbeat("10.0.0.7", "D")
    with pytest.raises(ValueError):
        GT7Heartbeat("10.0.0.7", interval_s=0.0)
    with pytest.raises(ValueError):
        hb.set_variant("x")
    hb.stop()  # never started: still safe


def test_heartbeat_broadcasts_from_a_provided_socket() -> None:
    """The docstring's PDTools/gt7dashboard pattern - send from the listener's socket - in discovery mode: the
    provided socket needs SO_BROADCAST too (enabled once), or every beat fails with EACCES."""
    log: list[str] = []
    ext = _FakeSocket(log, fail_send=False)
    hb = GT7Heartbeat(None, sock=ext)  # type: ignore[arg-type]
    assert hb.send_once() and hb.send_once()
    assert log.count(f"setsockopt({socket.SO_BROADCAST}, 1)") == 1
    assert log.count("sendto ('255.255.255.255', 33739)") == 2 and hb.errors == 0
    hb.stop()
    assert "close" not in log  # the caller's socket is never closed
    # a socket that refuses broadcast: the failure is logged and the beats are counted as errors, never raised
    stubborn = GT7Heartbeat(None, sock=_FakeSocket([], fail_send=True, fail_setsockopt=True))  # type: ignore[arg-type]
    assert stubborn.send_once() is False and stubborn.errors == 1


def test_heartbeat_can_send_from_a_provided_socket() -> None:
    rx, port = _receiver()
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tx.bind(("127.0.0.1", 0))
    hb = GT7Heartbeat("127.0.0.1", port=port, interval_s=1.0, sock=tx)
    try:
        assert hb.send_once()
        data, addr = rx.recvfrom(16)
        assert data == b"C" and addr[1] == tx.getsockname()[1]
        hb.stop()
        tx.sendto(b"still open", ("127.0.0.1", port))  # the caller's socket is not closed by stop()
    finally:
        tx.close()
        rx.close()
