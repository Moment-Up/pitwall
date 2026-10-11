"""Assetto Corsa remote telemetry: layouts vs the docs, string decoding, size rejection, normalisation, laps without
RTLap, learned lap distance, the handshake client against a loopback fake server, and the probe's dry run.

Synthetic-tier only: these prove the decoder and client against our reading of the Kunos spec, the observed sizes
and generated streams. They are not evidence that AC on a PS4/PS5 (or PC) is compatible - that needs the live probe
(``scripts/probe_ac.py``) and a recorded capture. Every network test talks to 127.0.0.1 only.
"""

from __future__ import annotations

import contextlib
import ctypes
import dataclasses
import errno
import importlib.util
import itertools
import json
import math
import re
import socket
import sqlite3
import sys
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from pitwall.adapters.ac import packets as P
from pitwall.adapters.ac.adapter import AC_INFO, AcAdapter, AcTrackGeometry, slug
from pitwall.adapters.base import PacketRejected, SupportLevel
from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.adapters.forza.adapter import ForzaAdapter
from pitwall.adapters.gt7.adapter import GT7Adapter
from pitwall.analysis.compare import check_compatibility, lengths_compatible
from pitwall.analysis.laps import LapAssembler, LapFlag, LapTrace
from pitwall.core.lap_processor import LapJob, LapProcessor
from pitwall.ingest.ac_client import AcClientState, AcRemoteClient, validate_console_ip
from pitwall.ingest.capture import CapturedPacket, CaptureReader
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
)
from pitwall.sim.ac_stream import (
    AcPauseSpec,
    AcScenario,
    AcTruth,
    FakeAcServer,
    LoopbackRedirect,
    generate_ac_session,
    simple_car_info_stream,
    write_ac_capture,
)
from pitwall.sim.driver import CornerDeviation, DriverProfile
from pitwall.storage import repo
from pitwall.storage.db import Database, DbWriter
from tests.conftest import DecodedSession

ROOT = Path(__file__).resolve().parents[2]
RESEARCH_DOC = ROOT / "docs" / "research" / "forza-ac-acc-iracing.md"
PROTOCOL_DOC = ROOT / "docs" / "research" / "protocols" / "ac-remote-udp.md"
T0 = 1_000_000_000_000


# ============================================================================================== helpers
def of[T](items: Iterable[Emitted], kind: type[T]) -> list[T]:
    return [e for e in items if isinstance(e, kind)]


def car(**values: Any) -> bytes:
    base: dict[str, Any] = {
        "speed_Kmh": 180.0,
        "speed_Ms": 50.0,
        "gas": 1.0,
        "engineRPM": 7000.0,
        "gear": 4,
        "lapTime": 12_000,
        "carPositionNormalized": 0.5,
        "carCoordinates": (10.0, 1.0, 20.0),
        "isAbsEnabled": 1,
        "isTcEnabled": 1,
    }
    base.update(values)
    return P.encode_rt_car_info(base)


def hello(car_name: str = "ks_ferrari_458", track: str = "ks_monza", config: str = "", driver: str = "Driver") -> bytes:
    return P.encode_handshake_response(car_name, driver, track, config)


def assemble(items: Iterable[Emitted]) -> list[LapTrace]:
    laps: list[LapTrace] = []
    asm = LapAssembler(laps.append)
    for e in items:
        if isinstance(e, SessionInfo):
            asm.set_track_length(e.track_length_m)
        elif isinstance(e, CarFrame):
            asm.feed(e)
        elif isinstance(e, LapCompletion):
            asm.feed_completion(e)
    return laps


class Stream:
    """A car circling a circular 'track' (so the driven path equals the lap length) at constant speed.

    ``s`` is the distance since the timing line; the spline position is ``s / length + line`` (wrapped).
    ``lapCount`` increments in the packet after the car passes the line; ``lastLap`` follows ``last_delay`` packets
    later (0 = same packet).
    """

    def __init__(
        self,
        adapter: AcAdapter | None = None,
        *,
        length: float = 2000.0,
        line: float = 0.0,
        hz: float = 50.0,
        v: float = 50.0,
        start_frac: float = 0.6,
        handshake: bool = True,
        track: str = "ks_test_track",
    ) -> None:
        self.a = adapter or AcAdapter()
        self.length, self.line, self.hz, self.v = length, line, hz, v
        self.s = start_frac * length
        self.lap = 0
        self.lap_ms = 40_000.0
        self.last = 0
        self.t = T0
        self.last_delay = 0
        self.count_line = True  # False: the game does not count the next crossings (lapCount/lapTime carry on)
        self.clock_lag = 0  # lapTime restarts this many packets after lapCount increments
        self._pending: list[int] | None = None
        self._clock_pending = 0
        self.out: list[Emitted] = []
        if handshake:
            self.out += self.a.decode(hello(track=track), self.t)

    def pos(self) -> tuple[float, float, float]:
        r = self.length / (2 * math.pi)
        th = 2 * math.pi * self.s / self.length
        return (r * math.cos(th), 3.0, r * math.sin(th))

    def norm(self) -> float:
        return (self.s / self.length + self.line) % 1.0

    def packet(self, **over: Any) -> bytes:
        vals: dict[str, Any] = {
            "speed_Kmh": self.v * 3.6,
            "speed_Ms": self.v,
            "lapTime": round(self.lap_ms),
            "lastLap": self.last,
            "lapCount": self.lap,
            "carPositionNormalized": self.norm(),
            "carCoordinates": self.pos(),
        }
        vals.update(over)
        return car(**vals)

    def step(self, n: int = 1, **over: Any) -> list[Emitted]:
        out: list[Emitted] = []
        for _ in range(n):
            self.t += round(1e9 / self.hz)
            self.s += self.v / self.hz
            self.lap_ms += 1000.0 / self.hz
            wrapped = self.s >= self.length
            if wrapped:
                self.s -= self.length
            if wrapped and self.count_line:
                at_line = round(self.lap_ms - self.s / self.v * 1000.0)
                self.lap += 1
                if self.clock_lag:
                    self._clock_pending = self.clock_lag
                else:
                    self.lap_ms = self.s / self.v * 1000.0
                self._pending = [at_line, self.last_delay]
            elif self._clock_pending:
                self._clock_pending -= 1
                if not self._clock_pending:
                    self.lap_ms = self.s / self.v * 1000.0  # the time since the line
            if self._pending is not None:
                if self._pending[1] <= 0:
                    self.last = self._pending[0]
                    self._pending = None
                else:
                    self._pending[1] -= 1
            out += self.a.decode(self.packet(**over), self.t)
        self.out += out
        return out

    def to_lap(self, lap_count: int) -> list[Emitted]:
        out: list[Emitted] = []
        while self.lap < lap_count:
            out += self.step()
        return out


# ============================================================================================== layouts vs docs
_TYPES = {"int32": "i", "f32": "f", "u8": "B", "f32×4": "4f", "f32×3": "3f", "u8×2": "2s", "wchar[50]": "100s"}
_ROW = re.compile(r"^\| (\d+)(?: or \d+)? \| ([^|]+?) \| (\w+) \|", re.M)


def _rows(text: str) -> dict[str, tuple[int, str]]:
    out: dict[str, tuple[int, str]] = {}
    for off, typ, name in _ROW.findall(text):
        t = typ.replace(" (100 B)", "").strip()
        out[name] = (int(off), _TYPES.get(t, t))
    return out


def _between(text: str, start: str, end: str | None) -> str:
    i = text.index(start)
    return text[i : text.index(end, i + len(start))] if end else text[i:]


def _check(doc_rows: dict[str, tuple[int, str]], sd: Any) -> None:
    ours = P.field_offsets(sd)
    assert doc_rows, f"no table rows found for {sd.name}"
    for name, (off, typ) in doc_rows.items():
        assert name in ours, f"{sd.name}: documented field {name!r} missing from packets.py"
        o_off, o_fmt = ours[name]
        assert o_off == off, f"{sd.name}.{name}: ours @{o_off}, doc @{off}"
        if name == "identifier" and sd is P.RT_CAR_INFO:
            assert o_fmt == "B"  # 'a' + padding (doc: "wchar (2 B) + 2 pad" / "u8")
        elif typ in _TYPES.values():
            assert o_fmt == typ, f"{sd.name}.{name}: ours {o_fmt!r}, doc {typ!r}"


def test_layouts_match_the_research_doc() -> None:
    if not RESEARCH_DOC.exists():
        pytest.skip("docs/research/forza-ac-acc-iracing.md not present")
    sec = _between(RESEARCH_DOC.read_text(encoding="utf-8"), "### 2.2 UDP", "## 3.")
    _check(_rows(_between(sec, "**handshakerResponse.**", "**RTCarInfo**")), P.HANDSHAKE_RESPONSE_WIDE)
    car_rows = _rows(_between(sec, "**RTCarInfo**", "**RTLap**"))
    _check(car_rows, P.RT_CAR_INFO)
    # the doc lists "24 or 26": ours must be the first (natural-alignment) alternative
    assert P.field_offsets(P.RT_CAR_INFO)["isInPit"][0] == 24 == car_rows["isInPit"][0]
    # every documented RTCarInfo field (bar our explicit padding) is covered by the doc table
    assert set(P.field_offsets(P.RT_CAR_INFO)) - set(car_rows) == {"identifier_pad", "pad_26_27"}


def test_layouts_match_the_protocol_doc() -> None:
    if not PROTOCOL_DOC.exists():
        pytest.skip("docs/research/protocols/ac-remote-udp.md not present")
    text = PROTOCOL_DOC.read_text(encoding="utf-8")
    if not all(h in text for h in ("### 3.1", "### 3.2", "### 3.3", "### 3.4", "### 3.5")):
        pytest.skip("protocols/ac-remote-udp.md no longer has the 3.1-3.5 layout tables (restructured)")
    _check(_rows(_between(text, "### 3.1", "### 3.2")), P.HANDSHAKER)
    _check(_rows(_between(text, "### 3.2", "### 3.3")), P.HANDSHAKE_RESPONSE_WIDE)
    _check(_rows(_between(text, "### 3.3", "### 3.4")), P.RT_CAR_INFO)
    _check(_rows(_between(text, "### 3.4", "### 3.5")), P.RT_LAP)
    assert set(P.field_offsets(P.RT_CAR_INFO)) - set(_rows(_between(text, "### 3.3", "### 3.4"))) == {"identifier_pad"}


def test_struct_sizes() -> None:
    assert (P.HANDSHAKER.size, P.HANDSHAKE_RESPONSE_WIDE.size, P.HANDSHAKE_RESPONSE_NARROW.size) == (12, 408, 208)
    assert (P.RT_CAR_INFO.size, P.RT_LAP.size) == (328, 212)
    narrow = P.field_offsets(P.HANDSHAKE_RESPONSE_NARROW)
    assert [narrow[k][0] for k in ("carName", "driverName", "identifier", "version", "trackName", "trackConfig")] == [
        0,
        50,
        100,
        104,
        108,
        158,
    ]


def _spec_struct(pack: int | None) -> type[ctypes.Structure]:
    """The spec's RTCarInfo field list as a C struct (``char`` identifier, ``bool`` = 1 byte)."""
    f, i = ctypes.c_float, ctypes.c_int32
    fields: list[tuple[str, Any]] = [("identifier", ctypes.c_char), ("size", i)]
    fields += [(n, f) for n in ("speed_Kmh", "speed_Mph", "speed_Ms")]
    fields += [
        (n, ctypes.c_bool)
        for n in ("isAbsEnabled", "isAbsInAction", "isTcInAction", "isTcEnabled", "isInPit", "isEngineLimiterOn")
    ]
    fields += [(n, f) for n in ("accG_vertical", "accG_horizontal", "accG_frontal")]
    fields += [(n, i) for n in ("lapTime", "lastLap", "bestLap", "lapCount")]
    fields += [(n, f) for n in ("gas", "brake", "clutch", "engineRPM", "steer")]
    fields += [("gear", i), ("cgHeight", f)]
    fields += [(f"w{k}", f * 4) for k in range(14)]
    fields += [("carPositionNormalized", f), ("carSlope", f), ("carCoordinates", f * 3)]
    attrs: dict[str, Any] = {"_fields_": fields}
    if pack is not None:
        attrs["_pack_"] = pack
    return type("RTCarInfoSpec", (ctypes.Structure,), attrs)


def test_natural_alignment_explains_the_observed_328_bytes() -> None:
    natural, packed = _spec_struct(None), _spec_struct(1)
    assert ctypes.sizeof(natural) == 328  # observed on PC and PS4
    assert ctypes.sizeof(packed) == 323  # the old "computed from the spec" figure
    assert natural.isInPit.offset == 24 and natural.isEngineLimiterOn.offset == 25
    assert natural.accG_vertical.offset == 28
    ours = P.field_offsets(P.RT_CAR_INFO)
    for entry in natural._fields_:
        name = entry[0]
        if name in ours:
            assert ours[name][0] == getattr(natural, name).offset, name


# ============================================================================================== strings
def test_wide_strings_end_at_percent_or_nul() -> None:
    raw = "magione".encode("utf-16-le") + "%".encode("utf-16-le") * 43
    assert P.decode_string(raw, wide=True) == "magione"
    raw = "ab".encode("utf-16-le") + b"\x00\x00" + "zz".encode("utf-16-le") + b"\x00" * 92
    assert P.decode_string(raw, wide=True) == "ab"
    assert P.decode_string(b"%\x00" * 50, wide=True) is None
    assert P.decode_string(b"\x00" * 100, wide=True) is None
    assert P.decode_string("bad\nname\x07".encode("utf-16-le") + b"\x00" * 80, wide=True) == "badname"


def test_narrow_strings_and_round_trip() -> None:
    assert P.decode_string(b"ks_monza%%%%" + b"%" * 38, wide=False) == "ks_monza"
    assert P.decode_string(b"spa\x00garbage" + b"\x00" * 39, wide=False) == "spa"
    for wide in (True, False):
        for pad in ("%", "\0"):
            enc = P.encode_string("ks_nordschleife", wide, pad)
            assert len(enc) == (100 if wide else 50)
            assert P.decode_string(enc, wide) == "ks_nordschleife"
    with pytest.raises(ValueError):
        P.encode_string("x" * 51, True)


@pytest.mark.parametrize("wide", [True, False])
def test_handshake_response_round_trip(wide: bool) -> None:
    data = P.encode_handshake_response("ks_ferrari_458", "James", "ks_nordschleife", "tourist", wide=wide)
    assert len(data) == (408 if wide else 208)
    hs = P.parse_handshake_response(data)
    assert (hs.car_name, hs.driver_name, hs.track_name, hs.track_config) == (
        "ks_ferrari_458",
        "James",
        "ks_nordschleife",
        "tourist",
    )
    assert hs.identifier == P.HANDSHAKE_STATUS_OK and hs.version == 1 and hs.wide is wide and hs.size == len(data)


def test_parsers_insist_on_exact_sizes() -> None:
    for bad in (b"", b"\x00" * 407, b"\x00" * 409):
        with pytest.raises(P.PacketError):
            P.parse_handshake_response(bad)
    with pytest.raises(P.PacketError):
        P.parse_rt_car_info(b"\x00" * 327)
    with pytest.raises(P.PacketError):
        P.parse_rt_lap(b"\x00" * 213)
    with pytest.raises(P.PacketError):
        P.decode_handshaker(b"\x00" * 11)
    assert P.decode_handshaker(P.encode_handshaker(P.Operation.DISMISS)) == (1, 1, 3)


def test_rt_lap_round_trip() -> None:
    lap = P.parse_rt_lap(P.encode_rt_lap(3, 7, "James", "ks_ferrari_458", 101_234))
    assert (lap.car_identifier, lap.lap, lap.driver_name, lap.car_name, lap.time_ms) == (
        3,
        7,
        "James",
        "ks_ferrari_458",
        101_234,
    )


# ============================================================================================== validation
@pytest.mark.parametrize("size", [0, 12, 207, 209, 211, 213, 327, 329, 407, 409, 1500])
def test_other_sizes_are_rejected(size: int) -> None:
    a = AcAdapter()
    assert not a.can_decode(b"\x61" * size)
    with pytest.raises(PacketRejected):
        a.decode(b"\x61" * size, T0)
    assert a.stats.rejected == 1 and a.stats.last_error is not None


def test_can_decode_known_sizes_and_never_raises() -> None:
    a = AcAdapter()
    assert a.can_decode(car()) and a.can_decode(hello()) and a.can_decode(P.encode_rt_lap(0, 1, "d", "c", 1))
    assert a.can_decode(P.encode_handshake_response("c", "d", "t", wide=False))
    assert not a.can_decode(b"\x00" * 328)  # neither 'a' nor a size field of 328
    assert a.can_decode(car(identifier=0))  # size field alone is enough (identifier unverified on consoles)
    assert not a.can_decode(b"")


def test_no_cross_talk_with_other_adapters(clean_session: Any) -> None:
    ac_packets = [
        car(),
        hello(),
        P.encode_rt_lap(0, 1, "d", "c", 1),
        P.encode_handshake_response("c", "d", "t", wide=False),
    ]
    for other in (F1Adapter(), GT7Adapter(), ForzaAdapter()):
        assert not any(other.can_decode(p) for p in ac_packets), type(other).__name__
    a = AcAdapter()
    assert not any(a.can_decode(p.data) for p in clean_session.packets[:500])  # real-format F1 packets
    for size in (45, 101, 231, 273, 296, 316, 344, 368, 232, 311, 324, 331, 753, 1349):
        assert not a.can_decode(b"\x61" + b"\x00" * (size - 1))


def test_unexpected_identifier_and_size_field_decode_with_a_warning() -> None:
    a = AcAdapter()
    a.decode(hello(), T0)
    out = a.decode(car(identifier=ord("b"), size=323), T0 + 1)
    (frame,) = of(out, CarFrame)
    assert frame.quality & FrameQuality.DECODE_WARNING
    assert a.stats.by_type["identifier_unexpected"] == 1 and a.stats.by_type["size_field_unexpected"] == 1
    assert frame.speed_kph == pytest.approx(180.0)


def test_decode_errors_are_contained(monkeypatch: pytest.MonkeyPatch) -> None:
    a = AcAdapter()

    def boom(*_: Any) -> bool:
        raise RuntimeError("boom")

    monkeypatch.setattr(a, "_on_car_info", boom)
    assert a.decode(car(), T0) == []
    assert a.stats.errors == 1 and "boom" in (a.stats.last_error or "")


# ============================================================================================== normalisation
def test_units_and_conventions() -> None:
    a = AcAdapter(platform=Platform.PS5)
    a.decode(hello(), T0)
    out = a.decode(
        car(
            speed_Kmh=200.0,
            gas=0.5,
            brake=0.25,
            clutch=1.0,
            engineRPM=7300.0,
            steer=-123.0,
            gear=4,
            accG_horizontal=1.2,
            accG_frontal=-0.8,
            accG_vertical=0.1,
            lapCount=2,
            lapTime=34_567,
            lastLap=95_432,
            bestLap=94_000,
            carCoordinates=(-120.5, 7.25, 340.0),
            isInPit=1,
            isAbsInAction=1,
        ),
        T0 + 1,
    )
    (f,) = of(out, CarFrame)
    assert f.game is Game.AC and f.quality == FrameQuality.OK
    assert f.speed_kph == pytest.approx(200.0) and f.rpm == pytest.approx(7300.0)
    assert (f.throttle, f.brake, f.clutch) == (0.5, 0.25, 1.0)
    assert f.steering is None  # steer unit undocumented: never guessed
    assert f.gear == 3  # AC 4 = 3rd
    assert (f.pos_x_m, f.pos_y_m, f.pos_z_m) == (-120.5, 7.25, 340.0)
    assert f.g_lat == pytest.approx(1.2) and f.g_vert == pytest.approx(0.1)
    assert f.g_lon is None  # sign not yet established
    assert f.lap_number == 3 and f.current_lap_time_ms == 34_567 and f.last_lap_time_ms == 95_432
    assert f.pit_status == 2 and f.abs_active is True
    assert f.lap_distance_m is None  # line position / length unknown
    assert f.vel_x_mps is None and f.tyre_surface_temp_c is None and f.fuel_kg is None
    (info,) = of(out, SessionInfo)
    assert info.platform is Platform.PS5 and info.extra["best_lap_ms"] == 94_000
    assert info.assists == {"abs": True, "tc": True}
    assert info.extra["steer_raw_range"] == [-123.0, -123.0]


@pytest.mark.parametrize(("raw", "gear"), [(0, -1), (1, 0), (2, 1), (8, 7), (11, 10), (12, None), (-1, None)])
def test_gear_mapping(raw: int, gear: int | None) -> None:
    a = AcAdapter()
    (f,) = of(a.decode(car(gear=raw), T0), CarFrame)
    assert f.gear == gear


@pytest.mark.parametrize(
    ("gas", "expected"), [(0.0, 0.0), (1.0, 1.0), (1.015, 1.0), (-0.01, 0.0), (1.2, None), (-0.5, None)]
)
def test_pedals_are_clamped_or_unknown(gas: float, expected: float | None) -> None:
    (f,) = of(AcAdapter().decode(car(gas=gas), T0), CarFrame)
    assert f.throttle == expected


def test_non_finite_and_invalid_values_stay_unknown() -> None:
    a = AcAdapter()
    (f,) = of(
        a.decode(
            car(speed_Kmh=math.nan, gas=math.inf, engineRPM=-5.0, isInPit=3, carCoordinates=(math.nan, 0.0, 0.0)), T0
        ),
        CarFrame,
    )
    assert f.speed_kph is None and f.throttle is None and f.rpm is None
    assert f.pit_status is None and f.quality & FrameQuality.DECODE_WARNING
    assert f.pos_x_m is None and f.pos_z_m == 0.0
    assert a.stats.by_type["pit_limiter_byte_not_bool"] == 1


def test_padding_bytes_are_counted_as_evidence() -> None:
    a = AcAdapter()
    a.decode(car(pad_26_27=b"\x01\x00"), T0)
    assert a.stats.by_type["pad_26_27_nonzero"] == 1


def test_adapter_info_is_honest() -> None:
    # PS5 (PS4 build): the probe script validated the protocol live on 2026-10-11, but this adapter has only run on
    # the recording (tests/recorded/test_ac_ps5_real.py), not in pitwall's own service: recorded, not live
    assert AC_INFO.platforms[Platform.PS5] is SupportLevel.RECORDED_VALIDATED
    assert AC_INFO.platforms[Platform.PS4] is SupportLevel.COMMUNITY_DOCUMENTED
    assert AC_INFO.platforms[Platform.PC] is SupportLevel.COMMUNITY_DOCUMENTED
    assert AC_INFO.platforms[Platform.XBOX] is SupportLevel.UNSUPPORTED  # no telemetry in the Xbox One build
    assert AC_INFO.fields["steering"].level is SupportLevel.UNVERIFIED  # raw range seen, unit still undocumented
    assert AC_INFO.fields["clutch"].level is SupportLevel.UNVERIFIED
    # isInPit = 0 while driving the pit lane on PS5: only the pit box is known
    assert AC_INFO.fields["pit_status"].level is SupportLevel.PARTIAL
    recorded = {k for k, fs in AC_INFO.fields.items() if fs.level is SupportLevel.RECORDED_VALIDATED}
    assert {"speed_kph", "lap_number", "lap_completion", "last_lap_time_ms", "rt_lap", "car_id"} <= recorded
    assert "UNVERIFIED" in AC_INFO.fields["rt_lap"].source  # the layout decodes; no RTLap seen at a crossing
    assert "ONE real crossing" in AC_INFO.fields["lap_completion"].source
    # derived values with no full PS5 lap behind them stay partial; the layout is not on the wire
    for k in ("lap_distance_m", "track_length_m", "session_time_s", "session_uid"):
        assert AC_INFO.fields[k].level is SupportLevel.PARTIAL, k
    assert AC_INFO.fields["track_id"].level is SupportLevel.COMMUNITY_DOCUMENTED
    for k in ("tyre_surface_temp_c", "tyre_pressure_psi", "tyre_wear_pct", "fuel_kg", "sector", "lap_invalid"):
        assert AC_INFO.fields[k].level is SupportLevel.UNSUPPORTED, k
    assert all(fs.level is not SupportLevel.LIVE_VALIDATED for fs in AC_INFO.fields.values())
    # every CarFrame field the adapter fills is described
    a = AcAdapter()
    a.decode(hello(), T0)
    (f,) = of(a.decode(car(isInPit=0, isAbsInAction=0), T0 + 1), CarFrame)
    filled = {k for k in f.__slots__ if getattr(f, k) is not None} - {"game", "t_recv_ns", "quality"}
    assert filled <= set(AC_INFO.fields), filled - set(AC_INFO.fields)


# ============================================================================================== identity / sessions
def test_track_and_car_ids_from_the_handshake() -> None:
    a = AcAdapter()
    a.decode(hello(car_name="ks_ferrari_458", track="ks_nordschleife", config="Nordschleife Tourist"), T0)
    (info,) = of(a.decode(car(), T0 + 1), SessionInfo)
    assert info.track_id == "ac:ks_nordschleife:nordschleife_tourist"
    assert info.track_name == "ks_nordschleife (Nordschleife Tourist)"
    assert info.car_id == "ac:car:ks_ferrari_458" and info.car_name == "ks_ferrari_458"
    assert info.extra["handshake_encoding"] == "utf-16le" and info.extra["handshake_status"] == 4242
    assert slug(" Spa:Francorchamps  GP ") == "spa_francorchamps_gp"


def test_without_a_handshake_identity_stays_unknown() -> None:
    a = AcAdapter()
    out = a.decode(car(), T0)
    (info,) = of(out, SessionInfo)
    assert info.track_id is None and info.car_id is None and info.track_name is None
    assert "unknown" in info.extra["identity"]
    assert info.session_uid == f"ac:{T0}"


def test_session_starts_with_info_then_event_then_frame() -> None:
    a = AcAdapter()
    assert a.decode(hello(), T0) == []  # a reply alone opens nothing (no empty sessions)
    out = a.decode(car(), T0 + 1)
    assert [type(e) for e in out] == [SessionInfo, GameEvent, CarFrame]
    assert of(out, GameEvent)[0].kind is EventKind.SESSION_STARTED


def test_same_identity_handshake_continues_the_session() -> None:
    a = AcAdapter()
    a.decode(hello(), T0)
    uid = of(a.decode(car(), T0 + 1), SessionInfo)[0].session_uid
    assert a.decode(hello(), T0 + 2) == []  # re-subscription after a pause
    out = a.decode(car(), T0 + 3)
    assert not of(out, GameEvent) and all(i.session_uid == uid for i in of(out, SessionInfo))


def test_identity_change_ends_the_session() -> None:
    a = AcAdapter()
    a.decode(hello(track="ks_monza"), T0)
    a.decode(car(), T0 + 1)
    out = a.decode(hello(track="ks_vallelunga"), T0 + 2)
    (ev,) = of(out, GameEvent)
    assert ev.kind is EventKind.SESSION_ENDED and ev.payload["reason"] == "handshake_identity_changed"
    out = a.decode(car(), T0 + 3)
    assert of(out, SessionInfo)[0].track_id == "ac:ks_vallelunga"
    assert of(out, SessionInfo)[0].session_uid == f"ac:{T0 + 3}"


def test_lap_counter_reset_is_a_new_session() -> None:
    a = AcAdapter()
    a.decode(hello(), T0)
    a.decode(car(lapCount=3), T0 + 1)
    out = a.decode(car(lapCount=0), T0 + 2)
    kinds = [e.kind for e in of(out, GameEvent)]
    assert kinds == [EventKind.SESSION_ENDED, EventKind.SESSION_STARTED]
    assert of(out, SessionInfo)[0].session_uid == f"ac:{T0 + 2}"


def test_synthetic_car_name_maps_to_the_synthetic_uid() -> None:
    a = AcAdapter()
    a.decode(hello(car_name=P.SYNTHETIC_CAR_NAME), T0)
    (info,) = of(a.decode(car(), T0 + 1), SessionInfo)
    assert info.session_uid == str(SYNTHETIC_SESSION_UID) and info.extra["synthetic"] is True


def test_reset_forgets_session_and_identity_but_keeps_geometry() -> None:
    a = AcAdapter(known_tracks={"ac:ks_monza": AcTrackGeometry(5793.0, 0.01)})
    a.decode(hello(), T0)
    a.decode(car(), T0 + 1)
    a.reset()
    assert a.identity is None
    assert of(a.decode(car(), T0 + 2), SessionInfo)[0].track_id is None
    assert a.known_tracks == {"ac:ks_monza": AcTrackGeometry(5793.0, 0.01)}


def test_rt_lap_for_the_player_becomes_an_event_others_are_ignored() -> None:
    a = AcAdapter()
    a.decode(hello(car_name="ks_ferrari_458", driver="James"), T0)
    a.decode(car(), T0 + 1)
    out = a.decode(P.encode_rt_lap(0, 4, "James", "ks_ferrari_458", 101_000), T0 + 2)
    (ev,) = of(out, GameEvent)
    assert ev.code == "ac_rt_lap" and ev.payload == {"lap": 4, "time_ms": 101_000, "car_identifier": 0}
    assert not of(out, LapCompletion)  # completions come from lapCount only
    assert a.decode(P.encode_rt_lap(5, 4, "Someone", "ks_bmw_m3_e30", 99_000), T0 + 3) == []
    assert a.stats.by_type["rt_lap_not_player"] == 1


def _rt(st: Stream, lap: int, time_ms: int) -> list[Emitted]:
    """An RTLap for the Stream's player (``hello()``: driver 'Driver', car 'ks_ferrari_458')."""
    out = st.a.decode(P.encode_rt_lap(0, lap, "Driver", "ks_ferrari_458", time_ms), st.t + 1)
    st.out += out
    return out


def test_lap_count_and_rt_lap_give_exactly_one_completion() -> None:
    st = Stream()
    st.to_lap(1)  # lastLap updates in the crossing packet: completed at once
    assert [c.lap_time_ms for c in of(st.out, LapCompletion)] == [st.last]
    out = _rt(st, 0, st.last)  # RTLap for the same lap (lap index 0 = pitwall lap 1) arrives afterwards
    assert of(out, GameEvent)[0].code == "ac_rt_lap" and not of(out, LapCompletion)
    assert st.a.stats.by_type["rt_lap_confirmed"] == 1
    out = _rt(st, 0, st.last + 7)  # a disagreeing time is counted, never a second completion
    assert not of(out, LapCompletion) and st.a.stats.by_type["rt_lap_time_mismatch"] == 1
    st.to_lap(2)
    assert [c.lap_number for c in of(st.out, LapCompletion)] == [1, 2]


def test_rt_lap_before_the_increment_times_the_completion() -> None:
    st = Stream(start_frac=0.99)
    st.last_delay = 10_000  # lastLap would lag the counter: without RTLap the completion would be held
    st.step(3)
    _rt(st, 0, 40_123)  # the spot event arrives just before the RTCarInfo with the increment
    out = st.to_lap(1)
    (comp,) = of(out, LapCompletion)
    assert comp.lap_number == 1 and comp.lap_time_ms == 40_123
    assert out.index(comp) < out.index(of(out, CarFrame)[-1])  # not held: frames follow at once
    assert st.a.stats.by_type["rt_lap_before_increment"] == 1 and st.a.stats.by_type["rt_lap_timed"] == 1
    st.step(50)
    assert len(of(st.out, LapCompletion)) == 1


def test_a_fresh_last_lap_wins_over_an_rt_lap_received_before_the_increment() -> None:
    """A stale RTLap re-send (the PS5 re-sends them after state changes) must never time a later crossing."""
    st = Stream(start_frac=0.99)
    st.step(3)
    _rt(st, 0, 99_999)
    st.to_lap(1)
    (comp,) = of(st.out, LapCompletion)
    assert comp.lap_time_ms == st.last != 99_999
    assert st.a.stats.by_type["rt_lap_time_mismatch"] == 1 and "rt_lap_timed" not in st.a.stats.by_type


def test_an_early_rt_lap_expires() -> None:
    st = Stream(start_frac=0.9)
    st.last_delay = 10_000  # lastLap stale at the line: only an RTLap could time it
    st.step(3)
    _rt(st, 0, 99_999)  # ~4 s before the crossing
    st.to_lap(1)
    st.step(30)
    (comp,) = of(st.out, LapCompletion)
    assert comp.lap_time_ms is None and st.a.stats.by_type["rt_lap_early_expired"] == 1


def test_an_early_rt_lap_is_dropped_on_a_lap_reset() -> None:
    st = Stream(start_frac=0.99)
    st.last_delay = 10_000
    st.step()
    _rt(st, 0, 99_999)
    st.lap_ms = 100.0  # the lap clock resets before the line
    st.to_lap(1)
    st.step(30)
    (comp,) = of(st.out, LapCompletion)
    assert comp.lap_time_ms is None and "rt_lap_timed" not in st.a.stats.by_type


def test_rt_lap_releases_a_held_completion_and_a_late_last_lap_adds_nothing() -> None:
    st = Stream()
    st.last_delay = 10  # lastLap updates 10 packets after the counter
    st.to_lap(1)
    assert not of(st.out, LapCompletion)  # held
    out = _rt(st, 0, st._pending[0] if st._pending else st.last)
    (comp,) = of(out, LapCompletion)
    assert comp.lap_number == 1 and comp.lap_time_ms is not None and of(out, CarFrame)  # held frames follow
    st.step(20)  # lastLap catches up: no second completion
    assert len(of(st.out, LapCompletion)) == 1 and st.a.stats.by_type["rt_lap_released_hold"] == 1


def test_rt_lap_for_a_lap_this_session_did_not_complete_is_ignored() -> None:
    st = Stream()
    st.to_lap(2)
    out = _rt(st, 5, 99_000)  # a lap this session never saw end (e.g. re-sent after a restored state)
    assert of(out, GameEvent) and not of(out, LapCompletion)
    assert st.a.stats.by_type["rt_lap_unmatched"] == 1
    out = _rt(st, -1, 0)  # PS5 sends lap -1 / time 0 when the session resets
    assert not of(out, LapCompletion) and st.a.stats.by_type["rt_lap_without_time"] == 1


# ============================================================================================== laps without RTLap
def test_lap_completion_from_lap_count_without_rt_lap() -> None:
    st = Stream()
    st.to_lap(1)
    comps = of(st.out, LapCompletion)
    assert [c.lap_number for c in comps] == [1]
    assert comps[0].lap_time_ms == st.last and comps[0].valid is None
    # the completion precedes every frame of the new lap
    idx = st.out.index(comps[0])
    assert all(f.lap_number == 1 for f in of(st.out[:idx], CarFrame))
    assert all(f.lap_number == 2 for f in of(st.out[idx:], CarFrame))


def test_stale_last_lap_holds_frames_until_it_updates() -> None:
    st = Stream()
    st.last_delay = 3
    out = st.to_lap(1)
    assert not of(out, LapCompletion)  # held: lastLap not updated yet
    out = st.step(3)
    (comp,) = of(out, LapCompletion)
    assert comp.lap_time_ms == st.last and st.last > 0
    assert out.index(comp) < out.index(of(out, CarFrame)[0])
    assert len(of(out, CarFrame)) == 4  # the 3 held frames + this packet's, all after the completion
    assert st.a.stats.by_type["last_lap_late"] == 1


def test_last_lap_that_never_updates_times_out_without_a_time() -> None:
    st = Stream()
    st.last_delay = 10_000
    st.to_lap(1)
    out = st.step(30)  # 0.6 s at 50 Hz
    (comp,) = of(out, LapCompletion)
    assert comp.lap_time_ms is None and st.a.stats.by_type["last_lap_timeout"] == 1


@pytest.mark.parametrize(("clock_before_line", "immediate"), [(89_985, True), (85_000, False)])
def test_unchanged_last_lap_matching_the_lap_clock_is_an_equal_lap_time(
    clock_before_line: int, immediate: bool
) -> None:
    """Two laps of exactly 90.000 s: lastLap does not change at the line, but the lap's own clock just before the
    line agrees with it, so it is this lap's time. If the clock disagrees, the stale value must not be used."""
    a = AcAdapter()
    a.decode(hello(), T0)
    a.decode(car(lapCount=1, lapTime=clock_before_line - 20, lastLap=90_000), T0 + 20_000_000)
    a.decode(car(lapCount=1, lapTime=clock_before_line, lastLap=90_000), T0 + 40_000_000)
    out = a.decode(car(lapCount=2, lapTime=15, lastLap=90_000), T0 + 60_000_000)
    comps = of(out, LapCompletion)
    if immediate:
        assert [(c.lap_number, c.lap_time_ms) for c in comps] == [(2, 90_000)]
    else:
        assert comps == [] and of(out, CarFrame) == []  # held
        out = a.decode(car(lapCount=2, lapTime=35, lastLap=85_010), T0 + 80_000_000)
        assert [(c.lap_number, c.lap_time_ms) for c in of(out, LapCompletion)] == [(2, 85_010)]


def test_lap_time_reset_marks_the_lap_invalid_and_stops_its_distance() -> None:
    st = Stream(adapter=AcAdapter(known_tracks={"ac:ks_test_track": AcTrackGeometry(2000.0, 0.0)}), start_frac=0.95)
    st.to_lap(1)
    st.step(100)  # 2 s into the lap
    st.lap_ms = 100.0  # "back to pits": lap clock restarts without an increment
    out = st.step()
    assert of(out, CarFrame)[0].lap_distance_m is None
    st.to_lap(2)
    comp = of(st.out, LapCompletion)[-1]
    assert comp.lap_number == 2 and comp.valid is False


def test_teleport_marks_the_lap_invalid() -> None:
    st = Stream(adapter=AcAdapter(known_tracks={"ac:ks_test_track": AcTrackGeometry(2000.0, 0.0)}), start_frac=0.95)
    st.to_lap(1)
    st.step(10)
    st.s += 700.0  # reset to track far ahead
    st.step()
    assert st.a.stats.by_type["teleport"] == 1
    st.to_lap(2)
    assert of(st.out, LapCompletion)[-1].valid is False


def test_laps_skipped_during_a_gap_complete_nothing() -> None:
    a = AcAdapter()
    a.decode(hello(), T0)
    a.decode(car(lapCount=1), T0 + 1)
    out = a.decode(car(lapCount=4), T0 + 2)
    assert not of(out, LapCompletion) and a.stats.by_type["laps_skipped"] == 1


def test_an_increment_with_the_lap_clock_jumping_is_not_a_lap() -> None:
    """A restored state: the clock neither restarts nor runs on (PS5: 1.2 s -> 73 s), so nothing is completed."""
    a = AcAdapter()
    a.decode(hello(), T0)
    a.decode(car(lapCount=1, lapTime=50_000, lastLap=90_000), T0 + 20_000_000)
    out = a.decode(car(lapCount=2, lapTime=73_032, lastLap=91_000), T0 + 40_000_000)
    assert not of(out, LapCompletion) and a.stats.by_type["increment_without_lap_start"] == 1
    assert of(out, CarFrame)[0].lap_number == 3  # the lap number still follows the game


def test_an_increment_with_a_teleport_is_not_a_lap_even_if_the_clock_runs_on() -> None:
    a = AcAdapter()
    a.decode(hello(), T0)
    a.decode(car(lapCount=1, lapTime=50_000, carCoordinates=(0.0, 0.0, 0.0)), T0 + 20_000_000)
    out = a.decode(car(lapCount=2, lapTime=50_020, carCoordinates=(534.0, 0.0, 0.0)), T0 + 40_000_000)
    assert not of(out, LapCompletion) and a.stats.by_type["increment_without_lap_start"] == 1


def test_an_increment_whose_lap_clock_never_restarts_completes_nothing_timed() -> None:
    """The clock runs on and never restarts: whatever the increment was, it times no lap. The completion is held
    for the restart window, then released untimed and void, and so is the lap that began there."""
    st = Stream(start_frac=0.95)
    st.to_lap(1)  # a normal first crossing
    st.step(50)
    st.lap += 1  # the counter moves, the clock carries on, the car stays where it is on the circle
    out = st.step(10)
    assert not of(out, LapCompletion)  # held: waiting for the lap clock
    st.step(30)  # > 0.5 s
    comps = of(st.out, LapCompletion)
    assert [(c.lap_number, c.lap_time_ms, c.valid) for c in comps][1:] == [(2, None, False)]
    assert st.a.stats.by_type["lap_clock_not_restarted"] == 1
    st.to_lap(st.lap + 1)
    assert of(st.out, LapCompletion)[-1].valid is False  # the lap that began at that increment


def test_a_lap_clock_lagging_the_counter_by_a_packet_still_completes_every_lap() -> None:
    """lapTime restarts one packet after lapCount (not seen on PS5; PC untested): every lap is still completed,
    timed by lastLap, and the late restart is not a lap reset."""
    st = Stream(start_frac=0.95)
    st.clock_lag = 1
    st.to_lap(4)
    st.step(5)
    comps = of(st.out, LapCompletion)
    assert [(c.lap_number, c.valid) for c in comps] == [(1, None), (2, None), (3, None), (4, None)]
    assert all(c.lap_time_ms is not None and c.lap_time_ms > 0 for c in comps)
    by = st.a.stats.by_type
    assert by["increment_before_lap_clock"] == 4 and by["lap_clock_restarted_late"] == 4
    assert "lap_time_reset" not in by and "increment_without_lap_start" not in by
    # every completion still precedes the frames of the next lap
    for c in comps:
        i = st.out.index(c)
        assert all(f.lap_number == c.lap_number for f in of(st.out[:i], CarFrame)[-3:])
        assert of(st.out[i:], CarFrame)[0].lap_number == c.lap_number + 1


def test_back_to_pits_then_restored_state_completes_each_lap_once() -> None:
    """The PS5 sequence (probe t = 165.4-174 s): counter reset into the pit box, 2.6 s later the exact earlier
    state comes back (with the RTLap of a lap completed long before), then the car is sent to the pit box with the
    lap clock still running."""
    st = Stream(start_frac=0.9)
    st.to_lap(1)  # lap 1 completed with lastLap
    st.step(200)
    saved = (st.s, st.lap_ms, st.last)
    st.lap, st.lap_ms, st.last, st.s = 0, 200.0, 0, 150.0  # counter reset, car in the pit box
    out = st.step(30, isInPit=1, speed_Ms=0.0, speed_Kmh=0.0)
    assert [e.payload["reason"] for e in of(out, GameEvent) if e.kind is EventKind.SESSION_ENDED] == [
        "lap_counter_reset"
    ]
    st.lap, (st.s, st.lap_ms, st.last) = 1, saved  # the earlier state is restored: lapCount 0 -> 1, no lap start
    out = st.step()
    _rt(st, 0, st.last)  # the game re-sends the RTLap of lap 1
    assert not of(out, LapCompletion) and st.a.stats.by_type["increment_without_lap_start"] == 1
    assert st.a.stats.by_type["rt_lap_unmatched"] == 1
    st.step(10)
    st.s = 300.0  # sent to the pit box, lap clock running: a teleport
    st.step(5)
    st.to_lap(2)  # the restored lap ends at the line: completed once, void (restored + teleport)
    comps = of(st.out, LapCompletion)
    assert [(c.lap_number, c.valid) for c in comps] == [(1, None), (2, False)]
    assert comps[0].lap_time_ms is not None and comps[1].lap_time_ms == st.last


# ============================================================================================== spline zero / early length
class WavyStream(Stream):
    """The spline advances unevenly against the driven path (local ratio 2000 / (1 + 0.3 cos)), as on a real track
    where the driven line leaves the AI spline in corners; one full lap is still exactly 2000 m of spline 0..1."""

    def norm(self) -> float:
        k = 3.0
        w = 2 * math.pi * k * self.s / self.length
        return (self.s / self.length + 0.3 * math.sin(w) / (2 * math.pi * k) + self.line) % 1.0


def test_spline_zero_is_the_line_from_the_first_crossing() -> None:
    st = Stream(line=0.0, start_frac=0.6)  # 40 % out-lap: not used for the length (it may include the pit lane)
    st.to_lap(1)
    assert all(f.lap_distance_m is None for f in of(st.out, CarFrame))
    info = of(st.out, SessionInfo)[-1]
    assert info.extra["ac_line_norm"] == 0.0 and info.extra["ac_line_source"] == "spline_zero"
    assert info.track_length_m is None and "estimating the track length" in info.extra["lap_distance_status"]
    assert st.a.stats.by_type["line_spline_zero"] == 1 and "line_candidate" not in st.a.stats.by_type
    st.step(320)  # 16 % of lap 2: the estimate converges and distances start (true positions from the line)
    info = of(st.out, SessionInfo)[-1]
    assert info.extra["lap_distance_status"] == "ok" and info.extra["track_length_quality"] == "estimate"
    assert of(st.out, CarFrame)[-1].lap_distance_m == pytest.approx(st.s, abs=2.0)
    assert st.a.known_tracks["ac:ks_test_track"] == AcTrackGeometry(info.track_length_m or 0.0, 0.0, estimated=True)


def test_spline_zero_line_is_checked_on_every_crossing() -> None:
    st = Stream(line=0.0, start_frac=0.6)
    st.to_lap(1)
    _one_off_increment(st, 600.0)  # the game counts a lap 600 m past spline 0
    st.step(30)  # lastLap does not change at a one-off: the held completion times out
    assert st.a.stats.by_type["line_mismatch"] == 1
    assert [(c.lap_number, c.valid) for c in of(st.out, LapCompletion)] == [(1, None), (2, False)]


class PitLaneOutLap(Stream):
    """The out-lap starts in a pit lane 4 % inside the racing line (PS5 Silverstone: ~29 m off, path/spline 4 % short)
    with ``isInPit`` = 0 - as on the PS5 - and merges before the line; flying laps are on the racing line."""

    def pos(self) -> tuple[float, float, float]:
        x, y, z = super().pos()
        f = self.s / self.length
        if self.lap == 0 and f < 0.95:
            k = 0.96 if f < 0.85 else 0.96 + 0.04 * (f - 0.85) / 0.1
            return (x * k, y, z * k)
        return (x, y, z)


def test_pit_lane_driving_on_the_out_lap_never_biases_the_estimate() -> None:
    st = PitLaneOutLap(line=0.0, start_frac=0.3)
    st.to_lap(1)  # 70 % of a lap, mostly in the "pit lane": would read ~1920 m if it counted
    assert all(i.track_length_m is None for i in of(st.out, SessionInfo))
    assert all(f.pit_status is None for f in of(st.out, CarFrame))  # isInPit 0 is not "on track": unknown
    st.step(280)  # 14 % of the first anchored lap
    assert all(i.track_length_m is None for i in of(st.out, SessionInfo))
    st.step(30)
    est = next(i for i in of(st.out, SessionInfo) if i.track_length_m is not None)
    assert est.extra["track_length_quality"] == "estimate" and est.track_length_m == pytest.approx(2000.0, rel=1e-4)
    assert est.extra["track_length_source"] == "derived:path_over_spline_estimate"
    assert 0.15 <= est.extra["track_length_estimate_fraction"] < 0.17


def test_the_pit_box_is_not_a_full_lap_measurement() -> None:
    st = Stream(line=0.0, start_frac=0.9)
    st.to_lap(1)
    st.step(300)
    st.step(50, isInPit=1)  # a stop in the box (flagged; position frozen in reality, moving here)
    st.to_lap(2)
    info = of(st.out, SessionInfo)[-1]
    assert info.extra["track_length_full_lap_m"] is None and info.extra["track_length_quality"] == "estimate"
    pit = [f for f in of(st.out, CarFrame) if f.pit_status is not None]
    assert len(pit) == 50 and all(f.pit_status == 2 for f in pit)


def test_an_estimate_a_full_lap_confirms_is_kept_and_fixed() -> None:
    st = Stream(line=0.0, start_frac=0.97)  # the line comes first, the length ~15 % of a lap later
    st.to_lap(1)
    assert of(st.out, CarFrame)[-1].lap_distance_m is None
    st.step(320)
    lap2 = [f for f in of(st.out, CarFrame) if f.lap_number == 2]
    assert lap2[0].lap_distance_m is None and lap2[-1].lap_distance_m == pytest.approx(st.s, abs=2.0)
    assert st.a.stats.by_type["length_estimated"] == 1
    est = of(st.out, SessionInfo)[-1].track_length_m
    st.to_lap(2)  # lap 2 began at the line: its full lap confirms the estimate within 0.5 %, which is kept
    info = of(st.out, SessionInfo)[-1]
    assert info.track_length_m == est and info.extra["track_length_quality"] == "full_lap"
    assert info.extra["track_length_source"] == "derived:estimate_confirmed_by_full_lap"
    assert info.extra["track_length_full_lap_m"] == pytest.approx(2000.0, rel=1e-4)
    assert st.a.stats.by_type["length_estimate_confirmed"] == 1
    st.to_lap(4)  # fixed: no further measurement, no re-publication
    assert of(st.out, SessionInfo)[-1].track_length_m == est
    assert st.a.known_tracks["ac:ks_test_track"] == AcTrackGeometry(est or 0.0, 0.0)
    assert [c.valid for c in of(st.out, LapCompletion)] == [None, None, None, None]
    laps = {lap.lap_number: lap for lap in assemble(st.out)}
    assert LapFlag.INCOMPLETE in laps[2].flags  # its distances begin mid-lap: never a reference
    assert laps[3].clean


def test_a_swinging_estimate_is_not_published_before_it_settles() -> None:
    st = WavyStream(line=0.0, start_frac=0.5)
    st.to_lap(1)
    st.step(600)  # 80 % of a lap of progress: the running ratio still swings by more than 0.5 % over 10 % of a lap
    assert all(i.track_length_m is None for i in of(st.out, SessionInfo))
    assert all(f.lap_distance_m is None for f in of(st.out, CarFrame))
    assert "estimating the track length" in of(st.out, SessionInfo)[-1].extra["lap_distance_status"]
    st.to_lap(2)  # the first full lap from the line measures exactly one spline lap
    info = of(st.out, SessionInfo)[-1]
    assert info.track_length_m == pytest.approx(2000.0, rel=1e-3) and info.extra["track_length_quality"] == "full_lap"
    assert of(st.out, CarFrame)[-1].lap_distance_m is not None


class SkewedStream(Stream):
    """The first 30 % of the lap after the line has a path/spline ratio of 1800, the rest 2085.7: a stable but
    biased early estimate (1800 m) that only a full lap (2000 m) corrects."""

    def norm(self) -> float:
        s = self.s
        return (s / 1800.0 if s < 540.0 else 0.3 + (s - 540.0) * 0.7 / 1460.0) % 1.0


def test_a_biased_estimate_is_corrected_by_the_first_full_lap_which_is_void() -> None:
    st = SkewedStream(line=0.0, start_frac=0.999)
    st.to_lap(1)
    st.step(400)
    est = next(i for i in of(st.out, SessionInfo) if i.track_length_m is not None)
    assert est.track_length_m == pytest.approx(1800.0, rel=1e-3)  # what the clean data said so far
    st.to_lap(3)
    info = of(st.out, SessionInfo)[-1]
    assert info.track_length_m == pytest.approx(2000.0, rel=1e-3) and st.a.stats.by_type["length_estimate_off"] == 1
    # lap 2 was scaled by a length 10 % off: void; lap 3 used the measured length
    assert [(c.lap_number, c.valid) for c in of(st.out, LapCompletion)] == [(1, None), (2, False), (3, None)]
    assert info.extra["ac_geometry_rejected"] is False  # nothing stored was contradicted


class MildlySkewedStream(Stream):
    """The first 30 % of the spline after the line has a path/spline ratio of 1950, the rest ~2021: the estimate
    settles at 1950 m (2.5 % short, inside the 3 % "same layout" band) and only a full lap says 2000 m."""

    def norm(self) -> float:
        s = self.s
        return (s / 1950.0 if s < 585.0 else 0.3 + (s - 585.0) * 0.7 / 1415.0) % 1.0


def test_a_lap_scaled_by_an_estimate_off_by_more_than_half_a_percent_is_void() -> None:
    """The reviewer's case: an estimate 2.5 % short scales lap 2; lap 3 uses the measured length. Two clean laps
    with the same corner 40 m apart must not exist, so lap 2 is void."""
    st = MildlySkewedStream(line=0.0, start_frac=0.999)
    st.to_lap(1)
    st.step(400)
    assert of(st.out, SessionInfo)[-1].track_length_m == pytest.approx(1950.0, rel=1e-3)
    st.to_lap(3)
    st.step(5)
    assert of(st.out, SessionInfo)[-1].track_length_m == pytest.approx(2000.0, rel=1e-3)
    assert st.a.stats.by_type["length_estimate_replaced"] == 1 and st.a.stats.by_type["estimate_scaled_lap_void"] == 1
    assert [(c.lap_number, c.valid) for c in of(st.out, LapCompletion)] == [(1, None), (2, False), (3, None)]
    laps = {lap.lap_number: lap for lap in assemble(st.out)}
    assert not laps[2].clean and laps[3].clean
    assert laps[3].channels["distance_m"][-1] == pytest.approx(2000.0, abs=2.0)


class WeaveStream(Stream):
    """Lap 3 (lapCount 2) has a 250 m weave of +/-6 m (a slide / gravel trip): its driven path is ~1.6 % long."""

    def pos(self) -> tuple[float, float, float]:
        x, y, z = super().pos()
        if self.lap == 2 and 500.0 <= self.s <= 750.0:
            k = 1.0 + 6.0 * math.sin(2 * math.pi * (self.s - 500.0) / 50.0) / (self.length / (2 * math.pi))
            return (x * k, y, z * k)
        return (x, y, z)


def test_the_length_is_fixed_by_the_first_full_lap_and_an_odd_lap_cannot_move_it() -> None:
    st = WeaveStream(line=0.0, start_frac=0.999)
    st.to_lap(2)  # lap 2 measures 2000 m: fixed
    length = of(st.out, SessionInfo)[-1].track_length_m
    assert length == pytest.approx(2000.0, rel=1e-4)
    n_info = len(of(st.out, SessionInfo))
    st.to_lap(5)
    st.step(5)
    assert all(i.track_length_m == length for i in of(st.out, SessionInfo)[n_info:])  # the weave changed nothing
    lap3 = [(f.pos_x_m or 0.0, f.pos_y_m or 0.0, f.pos_z_m or 0.0) for f in of(st.out, CarFrame) if f.lap_number == 3]
    assert sum(math.dist(a, b) for a, b in itertools.pairwise(lap3)) > 1.01 * 2000.0  # it is ~1.6 % long
    laps = {lap.lap_number: lap for lap in assemble(st.out)}
    for n in (3, 4, 5):
        assert laps[n].clean, (n, laps[n].flags)
        assert laps[n].channels["distance_m"][-1] == pytest.approx(laps[3].channels["distance_m"][-1], abs=1.0)
    assert st.a.known_tracks["ac:ks_test_track"].length_m == length


@pytest.mark.parametrize(("stored", "kept"), [(2006.0, True), (2030.0, False), (2100.0, False)])
def test_a_stored_estimate_is_kept_only_if_the_first_full_lap_confirms_it(stored: float, kept: bool) -> None:
    a = AcAdapter(known_tracks={"ac:ks_test_track": AcTrackGeometry(stored, 0.0, estimated=True)})
    st = Stream(adapter=a, line=0.0, start_frac=0.9)
    st.to_lap(1)
    st.step(25)
    assert of(st.out, CarFrame)[-1].lap_distance_m == pytest.approx(25.0 * stored / 2000.0, abs=0.01)
    st.to_lap(2)
    st.step(25)
    info = of(st.out, SessionInfo)[-1]
    comps = of(st.out, LapCompletion)
    assert comps[0].valid is False  # the out-lap was scaled by the estimate and never measured
    if kept:  # 0.3 %: confirmed, so lap 2 and every later lap share the stored value
        assert info.track_length_m == stored and comps[1].valid is None
        assert a.known_tracks["ac:ks_test_track"] == AcTrackGeometry(stored, 0.0)
    else:  # 1.5 % / 5 % off: replaced; lap 2 was scaled by it, so it is void
        assert info.track_length_m == pytest.approx(2000.0, rel=1e-4) and comps[1].valid is False
        assert of(st.out, CarFrame)[-1].lap_distance_m == pytest.approx(25.0, abs=0.01)
        assert a.known_tracks["ac:ks_test_track"] == AcTrackGeometry(info.track_length_m or 0.0, 0.0)
    # only a stored estimate more than 3 % off counts as contradicted geometry
    assert info.extra["ac_geometry_rejected"] is (stored == 2100.0)
    assert info.extra["track_length_quality"] == "full_lap"


# ============================================================================================== lap distance
def test_distance_waits_for_a_trusted_line_when_the_spline_origin_is_not_the_line() -> None:
    st = Stream(line=0.37)  # the spline origin sits 740 m before the line: spline 0 is not the line here
    st.to_lap(1)  # out-lap: the line has not been seen, and the out-lap is not used for the length
    assert all(f.lap_distance_m is None for f in of(st.out, CarFrame))
    infos = of(st.out, SessionInfo)
    assert "start/finish crossing" in infos[0].extra["lap_distance_status"]
    assert all(i.track_length_m is None for i in infos)
    assert "line_spline_zero" not in st.a.stats.by_type and st.a.stats.by_type["line_candidate"] == 1
    st.to_lap(2)  # lap 2 (from the candidate) estimates the length; the second crossing confirms the line and
    # measures the full lap from the candidate, which confirms the estimate
    infos = of(st.out, SessionInfo)
    est = next(i for i in infos if i.track_length_m is not None)
    assert est.extra["track_length_quality"] == "estimate" and est.extra["ac_line_norm"] is None
    assert est.extra["track_length_source"] == "derived:path_over_spline_estimate"
    assert all(f.lap_distance_m is None for f in of(st.out, CarFrame) if f.lap_number in (1, 2))
    assert of(st.out, CarFrame)[-1].lap_number == 3 and of(st.out, CarFrame)[-1].lap_distance_m is not None
    learned = [i for i in of(st.out, SessionInfo) if i.extra["ac_line_norm"] is not None]
    assert learned and learned[0].track_length_m == pytest.approx(2000.0, rel=1e-4)
    assert learned[0].extra["ac_line_norm"] == pytest.approx(0.37, abs=1e-3)
    assert learned[0].extra["ac_line_source"] == "crossings"
    assert learned[0].extra["lap_distance_status"] == "ok"
    assert learned[0].extra["track_length_quality"] == "full_lap"
    # the trusted geometry precedes the completion of the measuring lap
    assert st.out.index(learned[0]) < st.out.index(of(st.out, LapCompletion)[-1])
    out = st.step(500)
    for f in of(out, CarFrame):
        assert f.lap_distance_m is not None
    frames = of(out, CarFrame)
    assert frames[-1].lap_distance_m == pytest.approx(st.s, abs=1.5)
    assert st.a.known_tracks["ac:ks_test_track"].length_m == pytest.approx(2000.0, rel=1e-4)


def test_known_track_gives_distance_from_the_first_frame() -> None:
    a = AcAdapter(known_tracks={"ac:ks_test_track": AcTrackGeometry(2000.0, 0.2)})
    st = Stream(adapter=a, line=0.2, start_frac=0.25)
    out = st.step()
    (f,) = of(out, CarFrame)
    assert f.lap_distance_m == pytest.approx(st.s, abs=0.01)
    assert of(st.out, SessionInfo)[0].extra["track_length_source"] == "known"


def test_unanchored_lap_loses_its_distance_when_it_wraps_without_an_increment() -> None:
    a = AcAdapter(known_tracks={"ac:ks_test_track": AcTrackGeometry(2000.0, 0.0)})
    st = Stream(adapter=a, start_frac=0.985)  # joined just before the line: an unanchored lap
    st.step(5)
    assert of(st.out, CarFrame)[-1].lap_distance_m == pytest.approx(st.s, abs=0.01)
    # the game does not count this crossing (e.g. pit exit before the line): position wraps, lapCount does not
    st.count_line = False
    out = st.step(40)
    frames = of(out, CarFrame)
    before = [f for f in frames if f.lap_distance_m is not None]
    assert before and all(f.lap_distance_m is not None and f.lap_distance_m > 1900.0 for f in before)
    assert frames[-1].lap_distance_m is None and len(before) < len(frames)
    assert a.stats.by_type["unanchored_line_wrap"] == 1
    assert a.stats.by_type.get("teleport", 0) == 0


def test_anchored_lap_starts_near_zero_even_when_the_spline_wraps_late() -> None:
    a = AcAdapter(known_tracks={"ac:ks_test_track": AcTrackGeometry(2000.0, 0.002)})  # line 4 m after spline 0
    st = Stream(adapter=a, line=0.0, start_frac=0.9)
    st.to_lap(1)
    first = of(st.out, CarFrame)[-1]
    assert first.lap_number == 2 and first.lap_distance_m is not None and -5.0 < first.lap_distance_m < 2.0


def test_line_is_trusted_only_after_two_agreeing_crossings() -> None:
    st = Stream(line=0.37, start_frac=0.5)
    st.step(10)
    st.lap += 1  # the game counts a lap mid-track (race start / pit exit?): a wrong line candidate
    st.lap_ms = 0.0
    st.step(5)
    st.to_lap(2)  # the first real crossing disagrees: the candidate moves, nothing is trusted yet
    assert all(f.lap_distance_m is None for f in of(st.out, CarFrame))
    assert st.a.stats.by_type["line_candidate_moved"] == 1 and "line_learned" not in st.a.stats.by_type
    assert all(i.extra["ac_line_norm"] is None for i in of(st.out, SessionInfo))  # a candidate is never published
    assert "confirming" in of(st.out, SessionInfo)[-1].extra["lap_distance_status"]
    st.to_lap(3)  # the second real crossing agrees: line confirmed and length measured at the same packet
    learned = [i for i in of(st.out, SessionInfo) if i.extra["ac_line_norm"] is not None]
    assert learned[0].extra["ac_line_norm"] == pytest.approx(0.37, abs=1e-3)
    assert learned[0].track_length_m == pytest.approx(2000.0, rel=1e-4)
    out = st.step(300)
    assert of(out, CarFrame)[-1].lap_distance_m == pytest.approx(st.s, abs=1.5)
    assert st.a.known_tracks["ac:ks_test_track"].line_norm == pytest.approx(0.37, abs=1e-3)


def test_known_length_without_a_line_waits_for_two_crossings() -> None:
    a = AcAdapter(known_tracks={"ac:ks_test_track": AcTrackGeometry(2000.0, None)})
    st = Stream(adapter=a, line=0.6, start_frac=0.5)
    st.to_lap(1)
    st.step(5)
    assert all(f.lap_distance_m is None for f in of(st.out, CarFrame))  # one crossing is only a candidate
    st.to_lap(2)
    out = st.step(5)
    assert of(out, CarFrame)[-1].lap_distance_m == pytest.approx(st.s, abs=1.5)
    geo = a.known_tracks["ac:ks_test_track"]
    assert geo.length_m == 2000.0 and geo.line_norm == pytest.approx(0.6, abs=1e-3)


def _one_off_increment(st: Stream, at_s: float) -> None:
    """Drive to ``at_s`` metres past the line, then let the game count a lap there (race start / pit exit?)."""
    while st.s < at_s:
        st.step()
    st.lap += 1
    st.lap_ms = 0.0
    st.step()


def test_one_disagreeing_crossing_keeps_a_trusted_line_but_voids_that_lap() -> None:
    a = AcAdapter(known_tracks={"ac:ks_test_track": AcTrackGeometry(2000.0, 0.0)})
    st = Stream(adapter=a, line=0.0, start_frac=0.9)
    st.to_lap(1)
    _one_off_increment(st, 600.0)  # lap 2 ends 600 m past the line
    st.step(25)
    assert of(st.out, CarFrame)[-1].lap_distance_m == pytest.approx(st.s, abs=0.01)  # still the trusted line
    st.to_lap(st.lap + 1)  # the next real crossing agrees with the trusted line: the one-off is forgotten
    st.step(25)
    assert of(st.out, CarFrame)[-1].lap_distance_m == pytest.approx(st.s, abs=0.01)
    assert [(c.lap_number, c.valid) for c in of(st.out, LapCompletion)] == [(1, None), (2, False), (3, None)]
    assert a.stats.by_type["line_mismatch"] == 1 and "line_rejected" not in a.stats.by_type
    assert a.known_tracks["ac:ks_test_track"] == AcTrackGeometry(2000.0, 0.0)
    assert of(st.out, SessionInfo)[-1].extra["ac_geometry_rejected"] is False


def test_one_offs_separated_by_an_agreeing_crossing_never_reject_the_line() -> None:
    a = AcAdapter(known_tracks={"ac:ks_test_track": AcTrackGeometry(2000.0, 0.0)})
    st = Stream(adapter=a, line=0.0, start_frac=0.9)
    st.to_lap(1)
    _one_off_increment(st, 600.0)
    st.to_lap(st.lap + 1)  # agrees: clears the rival
    _one_off_increment(st, 600.0)  # the same spot again, but not consecutive
    assert a.stats.by_type["line_mismatch"] == 2 and "line_rejected" not in a.stats.by_type
    assert a.known_tracks["ac:ks_test_track"].line_norm == 0.0


def test_two_agreeing_crossings_reject_a_stored_line_and_the_geometry_is_relearned() -> None:
    """The reviewer's case: a stored line 200 m off (stale track name, or a track update moved the spline origin)."""
    a = AcAdapter(known_tracks={"ac:ks_test_track": AcTrackGeometry(2000.0, 0.1)})
    st = Stream(adapter=a, line=0.0, start_frac=0.9)
    st.to_lap(1)
    st.step(25)
    assert of(st.out, CarFrame)[-1].lap_distance_m == pytest.approx(-175.0, abs=0.01)  # one crossing: kept for now
    st.to_lap(2)  # a second crossing agrees with the first, not with the stored line: rejected
    st.step(25)
    assert a.stats.by_type["line_rejected"] == 1 and "ac:ks_test_track" not in a.known_tracks
    assert of(st.out, CarFrame)[-1].lap_distance_m is None  # length forgotten: unknown, not made up
    info = of(st.out, SessionInfo)[-1]
    assert info.track_length_m is None and info.extra["ac_geometry_rejected"] is True
    assert info.extra["ac_line_norm"] == pytest.approx(0.0, abs=1e-3) or info.extra["ac_line_norm"] > 0.999
    assert "estimating the track length" in info.extra["lap_distance_status"]
    st.to_lap(3)  # re-estimated during the lap, then measured over the full lap from the corrected line
    st.step(25)
    assert of(st.out, CarFrame)[-1].lap_distance_m == pytest.approx(25.0, abs=1.0)
    # both laps measured from the wrong line are void; the relearning lap is not
    assert [(c.lap_number, c.valid) for c in of(st.out, LapCompletion)] == [(1, False), (2, False), (3, None)]
    geo = a.known_tracks["ac:ks_test_track"]
    assert (
        geo.length_m == pytest.approx(2000.0, rel=1e-4) and min(geo.line_norm or 0.0, 1 - (geo.line_norm or 0.0)) < 1e-3
    )
    last = of(st.out, SessionInfo)[-1]
    assert last.track_length_m == pytest.approx(2000.0, rel=1e-4) and last.extra["ac_geometry_rejected"] is True


@pytest.mark.parametrize(("stored", "rejected"), [(2600.0, True), (1400.0, True), (2040.0, False), (1960.0, False)])
def test_a_stored_length_is_checked_against_the_first_full_lap(stored: float, rejected: bool) -> None:
    a = AcAdapter(known_tracks={"ac:ks_test_track": AcTrackGeometry(stored, 0.0)})
    st = Stream(adapter=a, line=0.0, start_frac=0.9)
    st.to_lap(1)
    st.step(25)
    assert of(st.out, CarFrame)[-1].lap_distance_m == pytest.approx(25.0 * stored / 2000.0, abs=0.01)  # unchecked
    st.to_lap(2)  # the first anchored full lap measures the track
    st.step(25)
    (c1, c2) = of(st.out, LapCompletion)
    info = of(st.out, SessionInfo)[-1]
    if rejected:
        assert a.stats.by_type["length_rejected"] == 1 and c2.valid is False  # its distances were mis-scaled
        assert of(st.out, CarFrame)[-1].lap_distance_m == pytest.approx(25.0, abs=0.01)
        assert info.track_length_m == pytest.approx(2000.0, rel=1e-4) and info.extra["ac_geometry_rejected"] is True
        assert a.known_tracks["ac:ks_test_track"].length_m == pytest.approx(2000.0, rel=1e-4)
    else:  # within the driven-line tolerance: the stored value is kept, so scaling stays identical across sessions
        assert a.stats.by_type["known_length_confirmed"] == 1 and c2.valid is None
        assert info.track_length_m == stored and info.extra["ac_geometry_rejected"] is False
        assert a.known_tracks["ac:ks_test_track"] == AcTrackGeometry(stored, 0.0)
    assert c1.valid is None
    st.to_lap(4)  # checked once per session
    assert a.stats.by_type.get("length_rejected", 0) + a.stats.by_type.get("known_length_confirmed", 0) == 1


def test_flush_releases_a_held_completion_when_the_stream_ends() -> None:
    st = Stream()
    st.last_delay = 10_000  # lastLap never updates before the stream stops
    st.to_lap(1)
    st.step(3)
    assert not of(st.out, LapCompletion)
    held = st.a.flush()
    (comp,) = of(held, LapCompletion)
    assert comp.lap_number == 1 and comp.lap_time_ms is None
    assert held.index(comp) == 0 and len(of(held, CarFrame)) == 4  # crossing packet + 3 after it
    assert st.a.flush() == [] and st.a.stats.by_type["last_lap_flushed"] == 1
    st.a.reset()
    assert st.a.flush() == []


def test_a_missing_position_stops_the_full_lap_measurement_for_that_lap() -> None:
    st = Stream(line=0.1)
    st.to_lap(1)
    st.step(20)
    st.step(1, carCoordinates=(math.nan, math.nan, math.nan))  # one packet without a position
    st.to_lap(2)
    info = of(st.out, SessionInfo)[-1]
    # the early estimate skips the two steps around the gap; the full lap would come out short: not measured
    assert info.extra["track_length_quality"] == "estimate" and info.extra["track_length_full_lap_m"] is None
    assert info.track_length_m == pytest.approx(2000.0, rel=1e-3)
    st.to_lap(3)
    info = of(st.out, SessionInfo)[-1]
    assert info.extra["track_length_quality"] == "full_lap"
    assert info.extra["track_length_full_lap_m"] == pytest.approx(2000.0, rel=1e-4)
    assert info.track_length_m == pytest.approx(2000.0, rel=1e-3)


@pytest.mark.parametrize("bad", [0.0, 100.0, 50_000.0, math.nan])
def test_track_geometry_validation(bad: float) -> None:
    with pytest.raises(ValueError):
        AcTrackGeometry(bad)
    with pytest.raises(ValueError):
        AcTrackGeometry(5000.0, 1.0)


def test_track_geometry_from_a_stored_session() -> None:
    assert AcTrackGeometry.from_session(5793.2, {"ac_line_norm": 0.01}) == AcTrackGeometry(5793.2, 0.01)
    assert AcTrackGeometry.from_session(5793.2, None) == AcTrackGeometry(5793.2, None)
    assert AcTrackGeometry.from_session(None, {}) is None
    assert AcTrackGeometry.from_session("x", {}) is None
    assert AcTrackGeometry.from_session(5793.2, {"ac_line_norm": 3.0}) is None
    est = AcTrackGeometry.from_session(2963.6, {"ac_line_norm": 0.0, "track_length_quality": "estimate"})
    assert est == AcTrackGeometry(2963.6, 0.0, estimated=True)


# ============================================================================================== clock / pause / g sign
def test_frozen_simulation_is_paused_and_does_not_advance_the_clock() -> None:
    st = Stream()
    st.step(10)
    clock = of(st.out, CarFrame)[-1].session_time_s
    frozen = st.packet()
    out: list[Emitted] = []
    for k in range(100):  # 2 s of identical packets
        out += st.a.decode(frozen, st.t + (k + 1) * 20_000_000)
    st.t += 100 * 20_000_000
    assert all(f.quality & FrameQuality.PAUSED for f in of(out, CarFrame))
    assert all(f.session_time_s == pytest.approx(clock) for f in of(out, CarFrame))
    (after,) = of(st.step(), CarFrame)
    assert not after.quality & FrameQuality.PAUSED
    assert after.session_time_s is not None and clock is not None
    assert after.session_time_s - clock < 0.1  # one short step, not the 2 s pause


@pytest.mark.synthetic
@pytest.mark.parametrize("sign", [1.0, -1.0])
def test_g_lon_sign_is_learned_against_measured_acceleration(sign: float) -> None:
    packets, _ = generate_ac_session(AcScenario(flying_laps=1, g_frontal_sign=sign))
    a = AcAdapter()
    out: list[Emitted] = []
    for p in packets:
        out += a.decode(p.data, p.t_recv_ns)
    assert a.g_lon_sign == sign
    late = [f for f in of(out, CarFrame) if f.g_lon is not None]
    assert late and min(f.g_lon for f in late if f.g_lon is not None) < -1.0  # braking is negative after the fix


# ============================================================================================== end to end (synthetic)
def _replay(
    sc: AcScenario, adapter: AcAdapter | None = None
) -> tuple[list[Emitted], list[LapTrace], AcTruth, AcAdapter]:
    packets, truth = generate_ac_session(sc)
    a = adapter or AcAdapter()
    out: list[Emitted] = []
    for p in packets:
        out += a.decode(p.data, p.t_recv_ns)
    return out, assemble(out), truth, a


@pytest.mark.synthetic
@pytest.mark.parametrize("offset", [0.0, 0.3, 0.97])
def test_replay_learns_the_track_and_produces_clean_laps(offset: float) -> None:
    sc = AcScenario(
        flying_laps=3,
        spline_offset=offset,
        driver_by_lap={4: DriverProfile(deviations={"T3": CornerDeviation(brake_early_m=15)})},
    )
    out, laps, truth, a = _replay(sc)
    assert a.stats.rejected == 0 and a.stats.errors == 0
    assert {i.session_uid for i in of(out, SessionInfo)} == {str(SYNTHETIC_SESSION_UID)}
    comps = of(out, LapCompletion)
    assert [c.lap_number for c in comps] == [1, 2, 3, 4]
    assert comps[0].lap_time_ms == truth.outlap_time_ms
    assert [c.lap_time_ms for c in comps[1:]] == [truth.lap_times_ms[n] for n in (2, 3, 4)]
    by_lap = {lap.lap_number: lap for lap in laps}
    # 1 = out-lap (line unseen, not used for the length). Spline origin at the line (offset 0): the line is known
    # from the first crossing and the length is estimated ~15 % into lap 2, whose trace therefore starts mid-lap
    # (incomplete, never a reference); otherwise lap 2 confirms the line. From lap 3 on every lap is clean.
    assert sorted(by_lap) == ([2, 3, 4] if offset == 0.0 else [3, 4])
    assert ("line_spline_zero" in a.stats.by_type) is (offset == 0.0)
    assert truth.lap_times_ms[4] > truth.lap_times_ms[3]  # the injected mistake costs time
    if offset == 0.0:
        lap2 = by_lap.pop(2)
        assert LapFlag.INCOMPLETE in lap2.flags and lap2.channels["distance_m"][0] > 0.14 * truth.lap_length_m
        assert lap2.valid is None  # its own full lap confirmed the estimate (exact on synthetic data)
    for n, lap in by_lap.items():
        assert lap.clean and lap.flags == set() and lap.lap_time_ms == truth.lap_times_ms[n]
        d = lap.channels["distance_m"]
        assert d[0] == pytest.approx(0.0, abs=3.0) and d[-1] == pytest.approx(truth.lap_length_m, abs=3.0)
    info = of(out, SessionInfo)[-1]
    assert info.track_length_m == pytest.approx(truth.lap_length_m, rel=2e-3)
    d = abs(info.extra["ac_line_norm"] - truth.line_norm) % 1.0
    assert min(d, 1.0 - d) < 2e-3  # circular: 0.9999 is next to 0.0
    assert info.track_id == "ac:synthetic-pitwall-park" and info.game is Game.AC
    assert not a.known_tracks  # synthetic geometry never enters the registry


@pytest.mark.synthetic
def test_replay_with_known_geometry_assembles_every_flying_lap() -> None:
    geo = {"ac:synthetic-pitwall-park": AcTrackGeometry(3963.86, 0.0)}
    _, laps, truth, _ = _replay(AcScenario(flying_laps=2), AcAdapter(known_tracks=geo))
    by_lap = {lap.lap_number: lap for lap in laps}
    assert 2 in by_lap and 3 in by_lap
    assert by_lap[2].clean and by_lap[3].clean
    assert not by_lap[1].clean  # the out-lap starts mid-track (LapAssembler: standing start / incomplete)
    assert by_lap[1].flags & {LapFlag.INCOMPLETE, LapFlag.STANDING_START}
    ch = by_lap[2].channels
    assert ch["speed_kph"].max() == pytest.approx(3.6 * 95.0, rel=0.02)
    assert ch["gear"].min() >= 1 and ch["brake"].max() > 0.5 and ch["throttle"].max() == pytest.approx(1.0)
    assert all(math.isnan(x) for x in ch["steering"])  # not mapped
    assert truth.lap_times_ms[2] == by_lap[2].lap_time_ms


@pytest.mark.synthetic
def test_replay_with_8bit_handshake_stale_last_lap_and_pause() -> None:
    sc = AcScenario(
        flying_laps=3,
        wide_strings=False,
        string_pad="\0",
        last_lap_delay_packets=4,
        pause=AcPauseSpec(150.0, 4.0),
        driver_by_lap={
            3: DriverProfile(deviations={"T1": CornerDeviation(brake_early_m=10)}),
            4: DriverProfile(deviations={"T3": CornerDeviation(brake_early_m=20)}),
        },
    )
    out, laps, truth, a = _replay(sc)
    info = of(out, SessionInfo)[-1]
    assert info.extra["handshake_encoding"] == "8-bit" and info.track_id == "ac:synthetic-pitwall-park"
    assert a.stats.by_type["last_lap_late"] == 4
    by_lap = {lap.lap_number: lap for lap in laps}
    assert sorted(by_lap) == [2, 3, 4]  # spline origin at the line: distances once the length is estimated in lap 2
    assert LapFlag.INCOMPLETE in by_lap.pop(2).flags
    for n, lap in by_lap.items():
        assert lap.clean and lap.lap_time_ms == truth.lap_times_ms[n], (n, lap.flags)
    assert truth.packets_frozen > 0
    assert sum(1 for f in of(out, CarFrame) if f.quality & FrameQuality.PAUSED) >= truth.packets_frozen - 1


@pytest.mark.synthetic
def test_replay_with_rt_lap_events() -> None:
    out, _, _, _ = _replay(AcScenario(flying_laps=1, rt_lap=True))
    assert len([e for e in of(out, GameEvent) if e.code == "ac_rt_lap"]) == 2


@pytest.mark.synthetic
def test_synthetic_capture_is_flagged_and_replays(tmp_path: Path) -> None:
    path = tmp_path / "ac.pwcap"
    truth = write_ac_capture(path, AcScenario(flying_laps=1))
    r = CaptureReader(path)
    assert r.meta.synthetic and r.meta.game_hint == "ac-remote" and "SYNTHETIC" in r.meta.description
    a = AcAdapter()
    n = sum(1 for p in r if a.can_decode(p.data))
    assert n == truth.packets_car_info + 1


# ============================================================================================== layouts, one track id
def test_compatibility_blocks_laps_of_another_layout_under_the_same_track_id() -> None:
    """The PS5 sends trackConfig == trackName: International and GP share ``ac:ks_silverstone:ks_silverstone``."""
    base = {"game": "ac", "track_id": "ac:ks_silverstone:ks_silverstone", "car_id": "ac:car:x", "track_length_m": 2966}
    assert check_compatibility(base, {**base, "track_length_m": 2990.0}, True).ok  # same layout, another line
    gp = check_compatibility(base, {**base, "track_length_m": 5891.0}, True)
    assert not gp.ok and "another layout" in gp.blocking[0]
    assert check_compatibility(base, {**base, "track_length_m": None}, True).ok  # unknown: no veto
    assert lengths_compatible(None, 5891.0) and lengths_compatible(2966.0, 3050.0)
    assert not lengths_compatible(2966.0, 2640.0) and not lengths_compatible("2966", 5891)


def _stored_session(writer: DbWriter, sid: str, info: SessionInfo) -> None:
    def job(c: sqlite3.Connection) -> None:
        repo.insert_session(c, sid, info.game.value, "test", False, None, None)
        repo.update_session_info(c, sid, info)

    writer.call(job)


def _layout_ctx(info: SessionInfo) -> dict[str, Any]:
    return {
        "game": info.game.value,
        "track_id": info.track_id,
        "track_name": info.track_name,
        "track_length_m": info.track_length_m,
        "car_id": info.car_id,
        "weather": info.weather.condition,
        "assists": dict(info.assists),
        "setup_fp": None,
    }


def _scaled(lap: LapTrace, k: float, lap_number: int | None = None) -> LapTrace:
    """The same driving on a layout ``k`` times as long (only the distance channel matters here)."""
    channels = dict(lap.channels)
    channels["distance_m"] = lap.channels["distance_m"] * k
    n = lap.lap_number if lap_number is None else lap_number
    return LapTrace(n, channels, lap.lap_time_ms, list(lap.sector_times_ms), lap.valid, set(lap.flags), dict(lap.meta))


@pytest.mark.synthetic
def test_references_and_track_models_never_mix_layouts(tmp_path: Path, clean_session: DecodedSession) -> None:
    db = Database(tmp_path / "pitwall.sqlite3")
    writer = DbWriter(db)
    try:
        track, game = "ac:ks_silverstone:ks_silverstone", Game.AC.value
        length, k = clean_session.info.track_length_m or 0.0, 1.9
        laps = clean_session.laps
        info_a = dataclasses.replace(clean_session.info, game=Game.AC, track_id=track, car_id="ac:car:x")
        info_b = dataclasses.replace(info_a, track_length_m=length * k)  # "GP": same id, another length
        proc = LapProcessor(db, writer)
        _stored_session(writer, "s-int", info_a)
        a_ids = [proc.process(LapJob("s-int", _scaled(lap, 1.0), _layout_ctx(info_a)))["lap_id"] for lap in laps]
        with db.read() as c:
            model = repo.load_track_model(c, game, track)
        assert model is not None and model.length_m == length

        _stored_session(writer, "s-gp", info_b)
        first = proc.process(LapJob("s-gp", _scaled(laps[0], k), _layout_ctx(info_b)))
        assert first["comparison"] is None  # no GP reference yet: International laps are not candidates
        with db.read() as c:
            model = repo.load_track_model(c, game, track)
            gp_only = repo.clean_laps_for(c, game, track, None, 50, track_length_m=length * k)
            everything = repo.clean_laps_for(c, game, track, None, 50)
        assert model is not None and model.length_m == pytest.approx(length * k)
        assert model.source_lap_ids == [first["lap_id"]]  # rebuilt from this layout's laps only
        assert [r["id"] for r in gp_only] == [first["lap_id"]] and len(everything) == len(a_ids) + 1
        second = proc.process(LapJob("s-gp", _scaled(laps[1], k, 2), _layout_ctx(info_b)))
        assert second["comparison"]["ref_lap_id"] == first["lap_id"]
        assert second["comparison"]["compatibility"]["ok"]

        # back on the International layout: its laps are the references again, its model is rebuilt from them only
        _stored_session(writer, "s-int2", info_a)
        third = proc.process(LapJob("s-int2", _scaled(laps[2], 1.0, 1), _layout_ctx(info_a)))
        assert third["comparison"]["ref_lap_id"] in a_ids
        with db.read() as c:
            model = repo.load_track_model(c, game, track)
        assert model is not None and model.length_m == length
        assert not {first["lap_id"], second["lap_id"]} & set(model.source_lap_ids)
    finally:
        writer.close()


def test_generator_rejects_a_session_starting_on_the_line() -> None:
    with pytest.raises(ValueError):
        generate_ac_session(AcScenario(outlap_fraction=1.0))


# ============================================================================================== client (loopback only)
def _wait(cond: Callable[[], bool], timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def _client(port: int, sink: list[CapturedPacket], **kw: Any) -> AcRemoteClient:
    opts: dict[str, Any] = {
        "port": port,
        "stream_timeout_s": 0.3,
        "handshake_interval_s": 0.15,
        "min_handshake_interval_s": 0.1,
        "idle_timeout_s": 5.0,
    }
    opts.update(kw)
    return AcRemoteClient("127.0.0.1", sink.append, **opts)


def _closed_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()
    return port


def test_client_handshake_subscribe_stream_and_dismiss_on_stop() -> None:
    got: list[CapturedPacket] = []
    with FakeAcServer(rate_hz=200.0) as srv:
        c = _client(srv.port, got)
        c.start()
        try:
            assert _wait(lambda: c.state is AcClientState.STREAMING and len(got) > 20)
            assert [op for op, _ in srv.ops[:2]] == [P.Operation.HANDSHAKE, P.Operation.SUBSCRIBE_UPDATE]
            assert len(got[0].data) == 408 and all(len(p.data) == 328 for p in got[1:])
            assert all(p.src_port == srv.port for p in got)  # the game's port, as in a real capture
            snap = c.snapshot()
            assert snap["state"] == "streaming" and snap["handshakes_answered"] == 1
            assert snap["last_handshake"]["car"] == P.SYNTHETIC_CAR_NAME and snap["local_port"]
            assert c.received == len(got) and c.source_snapshot()[0]["ip"] == "127.0.0.1"
        finally:
            c.stop()
        assert _wait(lambda: srv.ops_of(P.Operation.DISMISS) == 1)
        assert srv.subscribers == 0 and c.state is AcClientState.STOPPED


def test_client_reregisters_on_a_fresh_port_when_the_stream_stops() -> None:
    got: list[CapturedPacket] = []
    with FakeAcServer(rate_hz=200.0) as srv:
        c = _client(srv.port, got)
        c.start()
        try:
            assert _wait(lambda: c.state is AcClientState.STREAMING)
            first_port = c.local_port
            srv.end_session()  # back to the menu: no stream, handshakes unanswered
            assert _wait(lambda: c.state is AcClientState.HANDSHAKING and c.cycles == 1)
            assert srv.ops_of(P.Operation.DISMISS) == 1
            srv.begin_session()
            assert _wait(lambda: c.state is AcClientState.STREAMING and c.handshakes_answered == 2)
            assert c.local_port != first_port
            ports = {port for op, port in srv.ops if op == P.Operation.SUBSCRIBE_UPDATE}
            assert len(ports) == 2
        finally:
            c.stop()


def test_client_idle_timeout_ends_the_session_and_rotates_the_capture(tmp_path: Path) -> None:
    idle: list[int] = []
    got: list[CapturedPacket] = []
    with FakeAcServer(rate_hz=200.0) as srv:
        srv_port = srv.port
        c = _client(srv_port, got, idle_timeout_s=0.4, capture_dir=tmp_path, on_idle=lambda: idle.append(1))
        c.start()
        try:
            assert _wait(lambda: c.capture is not None and c.state is AcClientState.STREAMING)
            first = c.capture.path if c.capture else None
            srv.end_session()
            assert _wait(lambda: idle == [1])
            assert c.capture is None
            time.sleep(0.3)
            assert idle == [1]  # once per silence
            srv.begin_session()
            assert _wait(lambda: c.capture is not None and c.state is AcClientState.STREAMING)
        finally:
            c.stop()
    assert first is not None
    r = CaptureReader(first)
    assert r.meta.game_hint == "ac-remote" and not r.meta.synthetic
    pkts = list(r)
    assert len(pkts[0].data) == 408 and all(p.src_port == srv_port for p in pkts)


def test_client_reports_refused_quietly_and_rate_limits_handshakes() -> None:
    port = _closed_port()
    c = AcRemoteClient(
        "127.0.0.1",
        lambda _p: None,
        port=port,
        stream_timeout_s=0.3,
        handshake_interval_s=0.1,
        min_handshake_interval_s=0.1,
    )
    c.start()
    try:
        assert _wait(lambda: c.state is AcClientState.REFUSED and c.refused >= 1)
        t0, n0 = time.monotonic(), c.sent_by_op["HANDSHAKE"]
        time.sleep(0.6)
        elapsed = time.monotonic() - t0
        assert c.sent_by_op["HANDSHAKE"] - n0 <= elapsed / 0.1 + 1
        assert c.running and "refused" in (c.snapshot()["last_error"] or "")
    finally:
        c.stop()


def test_client_without_console_ip_is_idle_until_one_is_set() -> None:
    got: list[CapturedPacket] = []
    with FakeAcServer(rate_hz=200.0) as srv:
        c = AcRemoteClient(
            None,
            got.append,
            port=srv.port,
            stream_timeout_s=0.3,
            handshake_interval_s=0.15,
            min_handshake_interval_s=0.1,
        )
        c.start()
        try:
            time.sleep(0.2)
            assert c.state is AcClientState.IDLE and c.sent == 0 and not srv.ops
            c.set_console_ip("127.0.0.1")
            assert _wait(lambda: c.state is AcClientState.STREAMING)
            c.set_console_ip(None)
            assert _wait(lambda: c.state is AcClientState.IDLE)
            assert _wait(lambda: srv.ops_of(P.Operation.DISMISS) == 1)
        finally:
            c.stop()


def test_client_survives_handler_errors() -> None:
    def bad(_p: CapturedPacket) -> None:
        raise RuntimeError("handler bug")

    with FakeAcServer(rate_hz=200.0) as srv:
        c = AcRemoteClient(
            "127.0.0.1",
            bad,
            port=srv.port,
            stream_timeout_s=0.3,
            handshake_interval_s=0.15,
            min_handshake_interval_s=0.1,
        )
        c.start()
        try:
            assert _wait(lambda: c.handler_errors > 5 and c.state is AcClientState.STREAMING)
        finally:
            c.stop()


def test_client_set_console_ip_is_thread_safe() -> None:
    c = AcRemoteClient(
        None, lambda _p: None, stream_timeout_s=0.3, handshake_interval_s=0.15, min_handshake_interval_s=0.1
    )
    threads = [threading.Thread(target=c.set_console_ip, args=(ip,)) for ip in ("127.0.0.1", None, "127.0.0.2") * 5]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    c.stop()  # never started: closes cleanly


@pytest.mark.parametrize(
    "bad",
    [
        "255.255.255.255",
        "224.0.0.1",
        "0.0.0.0",
        "::1",
        "ps5.local",
        "300.1.1.1",
        "8.8.8.8",  # public
        "100.64.0.1",  # Tailscale / CGNAT
        "192.0.2.1",  # documentation range (Python calls it private; it is not a LAN)
        "172.32.0.1",  # just outside 172.16/12
        "10.1.2.255",  # broadcast-looking
        "192.168.1.0",  # network address of a home /24
    ],
)
def test_validate_console_ip_rejects_anything_off_the_lan(bad: str) -> None:
    with pytest.raises(ValueError):
        validate_console_ip(bad)


def test_validate_console_ip_accepts_lan_and_loopback() -> None:
    assert validate_console_ip(" 192.168.1.50 ") == "192.168.1.50"
    for ok in ("10.1.2.3", "172.16.5.4", "172.31.255.1", "169.254.10.20"):
        assert validate_console_ip(ok, allow_loopback=False) == ok
    assert validate_console_ip("127.0.0.1") == "127.0.0.1"
    with pytest.raises(ValueError):
        validate_console_ip("127.0.0.1", allow_loopback=False)
    assert validate_console_ip("") is None and validate_console_ip(None) is None


def test_client_refuses_public_targets_before_sending_anything() -> None:
    with pytest.raises(ValueError):
        AcRemoteClient("8.8.8.8", lambda _p: None)
    c = AcRemoteClient(None, lambda _p: None)
    with pytest.raises(ValueError):
        c.set_console_ip("100.100.1.1")
    assert c.console_ip is None and c.sent == 0
    c.stop()


def _silent_port() -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    return s


def test_client_never_handshakes_a_lan_target_more_than_once_a_second() -> None:
    silent = _silent_port()
    redirect = LoopbackRedirect({"192.168.1.50": int(silent.getsockname()[1])})
    c = AcRemoteClient(
        "192.168.1.50",
        lambda _p: None,
        handshake_interval_s=0.05,
        min_handshake_interval_s=0.02,  # asked for 50 Hz: the LAN floor still applies
        stream_timeout_s=0.3,
        socket_factory=redirect,
    )
    c.start()
    try:
        time.sleep(1.5)
        assert 1 <= c.sent_by_op["HANDSHAKE"] <= 2
    finally:
        c.stop()
        silent.close()
    assert redirect.connects and all(ip == "192.168.1.50" and port == P.AC_PORT for ip, port in redirect.connects)


def test_client_backs_off_when_nothing_answers_for_a_long_time() -> None:
    silent = _silent_port()
    port = int(silent.getsockname()[1])
    c = AcRemoteClient(
        "127.0.0.1",
        lambda _p: None,
        port=port,
        handshake_interval_s=0.05,
        min_handshake_interval_s=0.05,
        stream_timeout_s=0.3,
        backoff_after_s=0.3,
        backoff_interval_s=0.5,
    )
    c.start()
    try:
        time.sleep(1.6)
        n = c.sent_by_op["HANDSHAKE"]
    finally:
        c.stop()
        silent.close()
    assert 4 <= n <= 11  # ~7 in the first 0.3 s, then one per 0.5 s (32 without the back-off)


def test_client_keeps_backing_off_when_sending_fails() -> None:
    """Console in rest mode: macOS fails the send with EHOSTDOWN. The back-off must survive the error path."""
    silent = _silent_port()
    port = int(silent.getsockname()[1])
    attempts: list[int] = []
    sockets: list[socket.socket] = []

    class HostDown(socket.socket):
        def send(self, data: Any, flags: int = 0) -> int:
            attempts.append(len(data))
            raise OSError(errno.EHOSTDOWN, "Host is down")

    def factory() -> socket.socket:
        s = HostDown(socket.AF_INET, socket.SOCK_DGRAM)
        sockets.append(s)
        return s

    c = AcRemoteClient(
        "127.0.0.1",
        lambda _p: None,
        port=port,
        handshake_interval_s=0.1,
        min_handshake_interval_s=0.1,
        stream_timeout_s=0.3,
        backoff_after_s=0.3,
        backoff_interval_s=0.6,
        socket_factory=factory,
    )
    c.start()
    try:
        time.sleep(2.4)
        n = len(attempts)
    finally:
        c.stop()
        silent.close()
    assert 4 <= n <= 10  # ~4 in the first 0.3 s, then one per 0.6 s (24 when the error path reset the schedule)
    assert len(sockets) <= n + 1 and c.sent == 0 and "Host is down" in (c.last_error or "")


def test_client_backs_off_when_the_game_answers_but_never_streams() -> None:
    """Probe outcome B (or a long menu pause): handshake answered, no RTCarInfo. Re-registration cycles back off."""
    with FakeAcServer(rate_hz=200.0, stream=False) as srv:
        c = AcRemoteClient(
            "127.0.0.1",
            lambda _p: None,
            port=srv.port,
            handshake_interval_s=0.05,
            min_handshake_interval_s=0.05,
            stream_timeout_s=0.1,
            backoff_after_s=0.3,
            backoff_interval_s=0.5,
        )
        c.start()
        try:
            time.sleep(2.4)
            n = srv.ops_of(P.Operation.HANDSHAKE)
            assert c.state is not AcClientState.STREAMING and c.handshakes_answered >= 2
        finally:
            c.stop()
    assert 3 <= n <= 10  # ~3 cycles in the first 0.3 s, then one per 0.5 s (~20 without the back-off)
    assert c.cycles >= 3


def test_client_closes_sockets_it_could_not_connect() -> None:
    redirect = LoopbackRedirect({})  # no route: connect() raises like an unreachable network would
    c = AcRemoteClient(
        "192.168.1.50",
        lambda _p: None,
        handshake_interval_s=0.05,
        min_handshake_interval_s=0.05,
        stream_timeout_s=0.3,
        socket_factory=redirect,
    )
    c.start()
    try:
        assert _wait(lambda: len(redirect.sockets) >= 3)
        assert "cannot open socket" in (c.last_error or "") and c.running and c.sent == 0
    finally:
        c.stop()
    assert all(s.fileno() == -1 for s in redirect.sockets)  # every failed socket was closed (no fd leak)


def test_client_rejects_bad_timings() -> None:
    with pytest.raises(ValueError):
        AcRemoteClient(None, lambda _p: None, handshake_interval_s=0.5, min_handshake_interval_s=1.0)
    with pytest.raises(ValueError):
        AcRemoteClient(None, lambda _p: None, stream_timeout_s=0.0)
    with pytest.raises(ValueError):
        AcRemoteClient(None, lambda _p: None, port=0)


def test_fake_server_refuses_non_loopback_addresses() -> None:
    with pytest.raises(ValueError):
        FakeAcServer(host="0.0.0.0")


def test_client_stream_decodes_end_to_end() -> None:
    got: list[CapturedPacket] = []
    stream = simple_car_info_stream(n=300)
    with FakeAcServer(car_info=stream, rate_hz=300.0) as srv:
        c = _client(srv.port, got)
        c.start()
        try:
            assert _wait(lambda: len(got) > 100)
        finally:
            c.stop()
    a = AcAdapter()
    out: list[Emitted] = []
    for p in got:
        out += a.decode(p.data, p.t_recv_ns)
    assert a.stats.rejected == 0 and a.stats.errors == 0
    assert of(out, SessionInfo)[0].session_uid == str(SYNTHETIC_SESSION_UID)
    assert len(of(out, CarFrame)) == len(got) - 1


# ============================================================================================== probe
@pytest.fixture(scope="module")
def probe() -> ModuleType:
    spec = importlib.util.spec_from_file_location("probe_ac", ROOT / "scripts" / "probe_ac.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["probe_ac"] = mod  # dataclasses resolve annotations through sys.modules
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop("probe_ac", None)
        raise
    return mod


def test_probe_dry_run(probe: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "probe.pwcap"
    code = probe.main(["--dry-run", "--seconds", "0.5", "--spot-seconds", "0.5", "--out", str(out)])
    text = capsys.readouterr().out
    assert code == 0, text
    assert "DRY RUN" in text and "VERDICT: STREAMING" in text and "RTLap packets: 1" in text
    r = CaptureReader(out)
    assert r.meta.synthetic and r.meta.game_hint == "ac-remote"
    assert r.meta.extra["handshake"]["car"] == P.SYNTHETIC_CAR_NAME
    pkts = list(r)
    assert len(pkts[0].data) == 408 and sum(len(p.data) == 328 for p in pkts) > 10
    summary = json.loads(out.with_name(out.name + ".json").read_text(encoding="utf-8"))
    assert summary["verdict"] == "streaming" and summary["synthetic"] is True
    assert summary["update"]["size_field"] == {"328": summary["update"]["count"]}
    assert [o["op"] for o in summary["ops"]][:2] == ["HANDSHAKE", "SUBSCRIBE_UPDATE"]
    assert sum(o["op"] == "DISMISS" for o in summary["ops"]) == 2
    # the recording replays through the adapter
    a = AcAdapter()
    for p in pkts:
        a.decode(p.data, p.t_recv_ns)
    assert a.stats.rejected == 0 and a.stats.errors == 0


def test_probe_no_reply(probe: ModuleType, tmp_path: Path) -> None:
    silent = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    silent.bind(("127.0.0.1", 0))
    try:
        res = probe.run_probe(
            "127.0.0.1",
            silent.getsockname()[1],
            tmp_path / "x.pwcap",
            attempts=2,
            attempt_interval_s=0.1,
            printer=lambda _s: None,
        )
    finally:
        silent.close()
    assert res.verdict == "no_reply" and res.exit_code == probe.EXIT_NO_REPLY and res.handshake_attempts == 2
    assert "VERDICT: NO REPLY" in res.lines[-1]
    assert [o["op"] for o in res.ops] == ["HANDSHAKE", "HANDSHAKE", "DISMISS"]


def test_probe_refused(probe: ModuleType, tmp_path: Path) -> None:
    res = probe.run_probe(
        "127.0.0.1", _closed_port(), tmp_path / "x.pwcap", attempts=3, attempt_interval_s=0.1, printer=lambda _s: None
    )
    assert res.verdict == "refused" and res.exit_code == probe.EXIT_REFUSED and res.refused >= 1
    assert "VERDICT: REFUSED" in res.lines[-1]


def test_probe_unexpected_reply(probe: ModuleType, tmp_path: Path) -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    srv.settimeout(2.0)

    def answer() -> None:
        with contextlib.suppress(OSError):
            _, addr = srv.recvfrom(64)
            srv.sendto(b"\x01" * 100, addr)

    t = threading.Thread(target=answer)
    t.start()
    try:
        res = probe.run_probe(
            "127.0.0.1",
            srv.getsockname()[1],
            tmp_path / "x.pwcap",
            attempts=1,
            attempt_interval_s=0.5,
            printer=lambda _s: None,
        )
    finally:
        t.join()
        srv.close()
    assert res.verdict == "unexpected_reply" and res.reply_sizes == [100]
    assert next(iter(CaptureReader(tmp_path / "x.pwcap"))).data == b"\x01" * 100


def test_probe_target_and_argument_checks(probe: ModuleType, tmp_path: Path) -> None:
    assert probe.check_target("192.168.1.50") == "192.168.1.50"
    assert probe.check_target("127.0.0.1") == "127.0.0.1"
    for bad in ("8.8.8.8", "192.168.1.255", "224.0.0.1", "::1", "100.64.0.1", "192.0.2.1", "", "ps5"):
        with pytest.raises(ValueError):
            probe.check_target(bad)
    with pytest.raises(ValueError):  # run_probe checks too: no caller can aim it off the LAN
        probe.run_probe("8.8.8.8", P.AC_PORT, tmp_path / "never.pwcap", printer=lambda _s: None)
    assert not (tmp_path / "never.pwcap").exists()
    out = tmp_path / "p.pwcap"
    assert probe.main(["--out", str(out)]) == probe.EXIT_USAGE  # no --ip, no --dry-run
    assert probe.main(["--ip", "8.8.8.8", "--out", str(out)]) == probe.EXIT_USAGE
    assert probe.main(["--dry-run", "--seconds", "700", "--out", str(out)]) == probe.EXIT_USAGE
    out.write_bytes(b"")
    assert probe.main(["--dry-run", "--out", str(out)]) == probe.EXIT_USAGE  # exists, no --force


def test_probe_handshake_budget_is_five_for_the_whole_run(probe: ModuleType, tmp_path: Path) -> None:
    """A game that answers only the first HANDSHAKE: the SPOT socket gets the 4 that are left, never 5 more."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    srv.settimeout(0.2)
    stop = threading.Event()
    ops: list[int] = []

    def serve() -> None:
        while not stop.is_set():
            try:
                data, addr = srv.recvfrom(64)
            except (TimeoutError, OSError):
                continue
            op = P.decode_handshaker(data)[2]
            ops.append(op)
            if op == P.Operation.HANDSHAKE and ops.count(P.Operation.HANDSHAKE) == 1:
                srv.sendto(hello(), addr)

    t = threading.Thread(target=serve)
    t.start()
    try:
        res = probe.run_probe(
            "127.0.0.1",
            srv.getsockname()[1],
            tmp_path / "b.pwcap",
            seconds=0.2,
            spot_seconds=0.3,
            attempts=5,
            attempt_interval_s=0.02,
            printer=lambda _s: None,
        )
    finally:
        stop.set()
        t.join()
        srv.close()
    sent = [o["op"] for o in res.ops]
    assert sent.count("HANDSHAKE") == probe.MAX_ATTEMPTS == 5 and res.verdict == "handshake_only"
    assert sent.count("DISMISS") == 2


def test_probe_waits_at_least_a_second_between_lan_handshakes(probe: ModuleType, tmp_path: Path) -> None:
    silent = _silent_port()
    redirect = LoopbackRedirect({"192.168.1.50": int(silent.getsockname()[1])})
    t0 = time.monotonic()
    try:
        res = probe.run_probe(
            "192.168.1.50",
            P.AC_PORT,
            tmp_path / "lan.pwcap",
            attempts=2,
            attempt_interval_s=0.01,  # asked for 100 Hz: the LAN floor still applies
            printer=lambda _s: None,
            socket_factory=redirect,
        )
    finally:
        silent.close()
    assert time.monotonic() - t0 >= 2.0 and res.handshake_attempts == 2 and res.verdict == "no_reply"
    assert {ip for ip, _ in redirect.connects} == {"192.168.1.50"}
