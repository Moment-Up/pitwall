"""Forza Data Out adapter: layouts vs the research doc, units, rejection, sessions, laps, track identity and an
end-to-end synthetic replay through ``LapAssembler``.

Synthetic-tier only: these prove the decoder against our own reading of the documentation and against generated
streams. They are not evidence that any Forza title is compatible (that needs tests/recorded captures).
"""

from __future__ import annotations

import math
import re
import struct
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import orjson
import pytest

from pitwall.adapters.base import GameAdapter, PacketRejected, SupportLevel
from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.adapters.forza import adapter as A
from pitwall.adapters.forza import packets as P
from pitwall.adapters.forza.adapter import (
    FORZA_HORIZON_INFO,
    FORZA_MOTORSPORT_INFO,
    ForzaAdapter,
    TrackFingerprint,
)
from pitwall.adapters.forza.packets import LAYOUT_BY_FORMAT, ForzaFormat
from pitwall.analysis.distance import to_distance_domain
from pitwall.analysis.laps import LapAssembler, LapFlag, LapTrace
from pitwall.analysis.track import build_track_model
from pitwall.core.live import frame_to_dict
from pitwall.ingest.capture import CaptureReader
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
from pitwall.sim.driver import CornerDeviation, DriverProfile
from pitwall.sim.f1_stream import F1Scenario, generate_f1_session
from pitwall.sim.forza_stream import (
    ForzaScenario,
    ForzaTruth,
    PauseSpec,
    RewindSpec,
    generate_forza_session,
    lap_fraction_time,
    write_forza_capture,
)

DOC = Path(__file__).resolve().parents[2] / "docs" / "research" / "forza-ac-acc-iracing.md"
DASH_FORMATS = (ForzaFormat.FM7_DASH, ForzaFormat.HORIZON_DASH, ForzaFormat.FM2023_DASH)
G0 = 9.80665
T0 = 1_000_000_000_000
FRAME_NS = 16_666_667


# ---------------------------------------------------------------------------------------------- helpers
def pkt(fmt: ForzaFormat = ForzaFormat.FM2023_DASH, **values: Any) -> bytes:
    base: dict[str, Any] = {
        "IsRaceOn": 1,
        "CarOrdinal": 1234,
        "EngineMaxRpm": 8000.0,
        "EngineIdleRpm": 900.0,
        "CurrentEngineRpm": 5000.0,
        "TrackOrdinal": 77,
    }
    base.update(values)
    return LAYOUT_BY_FORMAT[fmt].pack(base)


def of[T](items: Iterable[Emitted], kind: type[T]) -> list[T]:
    return [e for e in items if isinstance(e, kind)]


def one_frame(items: list[Emitted]) -> CarFrame:
    frames = of(items, CarFrame)
    assert len(frames) == 1, items
    return frames[0]


class Stream:
    """Drives a hand-built lap sequence (60 Hz by default): the caller controls LapNumber/LastLap exactly.

    ``make``/``make_cross`` build the next datagram without decoding it, for delivering packets out of order.
    """

    def __init__(
        self, adapter: ForzaAdapter | None = None, fmt: ForzaFormat = ForzaFormat.FM2023_DASH, hz: int = 60
    ) -> None:
        self.a = adapter or ForzaAdapter()
        self.fmt = fmt
        self.hz = hz
        self.t = T0
        self.race_time = 30.0
        self.cur = 12.0
        self.dist = 5000.0
        self.lap = 0
        self.last = 0.0
        self.v = 50.0
        self.extra: dict[str, Any] = {}

    def values(self) -> dict[str, Any]:
        return {
            "LapNumber": self.lap,
            "LastLap": self.last,
            "CurrentLap": self.cur,
            "CurrentRaceTime": self.race_time,
            "DistanceTraveled": self.dist,
            "Speed": self.v,
            "PositionX": 100.0,
            "PositionZ": -40.0,
            "Yaw": 0.5,
            **self.extra,
        }

    def make(self, **over: Any) -> tuple[int, bytes]:
        self.t += round(1e9 / self.hz)
        self.race_time += 1 / self.hz
        self.cur += 1 / self.hz
        self.dist += self.v / self.hz
        return self.t, pkt(self.fmt, **{**self.values(), **over})

    def make_cross(self, last: float | None = None) -> tuple[int, bytes]:
        self.lap += 1
        self.cur = 0.0
        if last is not None:
            self.last = last
        return self.make()

    def feed(self, *packets: tuple[int, bytes]) -> list[Emitted]:
        out: list[Emitted] = []
        for t, data in packets:
            out += self.a.decode(data, t)
        return out

    def step(self, n: int = 1, **over: Any) -> list[Emitted]:
        out: list[Emitted] = []
        for _ in range(n):
            out += self.feed(self.make(**over))
        return out

    def off(self, n: int = 1, dt_ns: int = FRAME_NS) -> list[Emitted]:
        out: list[Emitted] = []
        for _ in range(n):
            self.t += dt_ns
            out += self.a.decode(pkt(self.fmt, IsRaceOn=0), self.t)
        return out

    def cross(self, last: float | None = None) -> list[Emitted]:
        """Cross the line: LapNumber + 1, CurrentLap restarts; LastLap = ``last`` (None = not updated yet)."""
        return self.feed(self.make_cross(last))


def decode_all(packets: Iterable[Any], adapter: ForzaAdapter | None = None) -> tuple[list[Emitted], ForzaAdapter]:
    a = adapter or ForzaAdapter()
    out: list[Emitted] = []
    for p in packets:
        out += a.decode(p.data, p.t_recv_ns)
    return out, a


def assemble(items: Iterable[Emitted], flush: bool = False) -> list[LapTrace]:
    """Feed ``LapAssembler`` like ``SessionManager`` does; ``flush`` = the session then ends (``router.finish``)."""
    laps: list[LapTrace] = []
    asm = LapAssembler(laps.append)
    for e in items:
        if isinstance(e, SessionInfo):
            asm.set_track_length(e.track_length_m)
        elif isinstance(e, CarFrame):
            asm.feed(e)
        elif isinstance(e, LapCompletion):
            asm.feed_completion(e)
    if flush:
        asm.flush()
    return laps


# ---------------------------------------------------------------------------------------------- layouts vs the doc
TYPE_CODES = {"S32": "i", "U32": "I", "F32": "f", "U16": "H", "U8": "B", "S8": "b"}
_SLED_ROW = re.compile(
    r"^\| (\d+)(?:[–-](\d+))? / 0x([0-9A-Fa-f]+)(?:[–-]0x[0-9A-Fa-f]+)? \| ([SUF]\d+)(?:×(\d+))?[^|]*\| (\w+)", re.M
)
_DASH_ROW = re.compile(r"^\| (\d+) \(0x([0-9A-Fa-f]+)\) \| (\d+) \(0x([0-9A-Fa-f]+)\) \| ([SUF]\d+) \| (\w+) \|", re.M)
_FM23_ROW = re.compile(r"^\| (\d+) \(0x([0-9A-Fa-f]+)\) \| ([SUF]\d+) \| (\w+) \|", re.M)


@pytest.fixture(scope="module")
def doc() -> str:
    if not DOC.exists():
        pytest.skip("docs/research/forza-ac-acc-iracing.md not present")
    return DOC.read_text(encoding="utf-8")


def _section(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i : text.index(end, i)]


def _check_rows(layout: P.FormatLayout, rows: list[tuple[int, str, int, str]]) -> set[int]:
    """Compare documented (offset, type, count, name) rows with our layout; return the offsets they cover."""
    ours = P.field_offsets(layout)
    by_offset = {off: (name, fmt) for name, (off, fmt) in ours.items()}
    covered: set[int] = set()
    for offset, typ, count, doc_name in rows:
        code = TYPE_CODES[typ]
        size = struct.calcsize("<" + code)
        names = []
        for i in range(count):
            off = offset + i * size
            assert off in by_offset, f"{layout.fmt}: no field of ours at documented offset {off} ({doc_name})"
            name, fmt = by_offset[off]
            assert fmt == code, f"{layout.fmt}.{name} @{off}: ours {fmt!r}, doc {typ}"
            names.append(name)
            covered.add(off)
        assert names[0].startswith(doc_name.rstrip("XYZ")), f"@{offset}: ours {names[0]!r}, doc {doc_name!r}"
        if count == 4:
            assert [n.removeprefix(doc_name) for n in names] == list(P.WHEEL_SUFFIXES), names  # FL, FR, RL, RR
        if count == 3:
            assert [n[-1] for n in names] == ["X", "Y", "Z"], names
    return covered


def test_sled_and_horizon_blocks_match_the_doc(doc: str) -> None:
    sled_rows = []
    for m in _SLED_ROW.finditer(_section(doc, "### 1.3", "### 1.4")):
        start, end, hexstart, typ, count, name = m.groups()
        n = int(count or 1)
        assert int(hexstart, 16) == int(start), f"doc hex/dec mismatch for {name}"
        if end is not None:
            assert int(end) == int(start) + (n - 1) * struct.calcsize("<" + TYPE_CODES[typ]), name
        sled_rows.append((int(start), typ, n, name))
    assert len(sled_rows) == 25
    covered = _check_rows(P.SLED_LAYOUT, sled_rows)
    assert covered == {off for off, _ in P.field_offsets(P.SLED_LAYOUT).values()}, "undocumented sled fields"

    hz_rows = []
    for m in _SLED_ROW.finditer(_section(doc, "### 1.4", "### 1.5")):
        start, _end, hexstart, typ, count, name = m.groups()
        assert int(hexstart, 16) == int(start)
        hz_rows.append((int(start), typ, int(count or 1), name))
    assert [r[3] for r in hz_rows] == ["CarGroup", "SmashableVelDiff", "SmashableMass"]
    _check_rows(P.HORIZON_DASH_LAYOUT, hz_rows)


def test_dash_block_matches_the_doc_for_both_offsets(doc: str) -> None:
    sec = _section(doc, "### 1.5", "### 1.6")
    fm_rows, fh_rows = [], []
    for m in _DASH_ROW.finditer(sec):
        fm, fm_hex, fh, fh_hex, typ, name = m.groups()
        assert int(fm_hex, 16) == int(fm) and int(fh_hex, 16) == int(fh), name
        assert int(fh) == int(fm) + 12, f"{name}: Horizon offset must be FM + 12"
        fm_rows.append((int(fm), typ, 1, name))
        fh_rows.append((int(fh), typ, 1, name))
    assert len(fm_rows) == len(P.DASH.fields) == 27
    for layout in (P.FM7_DASH_LAYOUT, P.FM2023_DASH_LAYOUT):
        _check_rows(layout, fm_rows)
    _check_rows(P.HORIZON_DASH_LAYOUT, fh_rows)
    pad = re.search(r"\| — \| (\d+) \(0x[0-9A-Fa-f]+\) \| — \| padding", sec)
    assert pad is not None and int(pad.group(1)) == P.HORIZON_PAD_OFFSET == 323


def test_fm2023_extras_match_the_doc(doc: str) -> None:
    rows = []
    for m in _FM23_ROW.finditer(_section(doc, "### 1.6", "### 1.7")):
        off, off_hex, typ, name = m.groups()
        assert int(off_hex, 16) == int(off)
        rows.append((int(off), typ, 1, name))
    assert [r[3] for r in rows][-1] == "TrackOrdinal" and len(rows) == 5
    _check_rows(P.FM2023_DASH_LAYOUT, rows)


def test_datagram_sizes_match_the_doc(doc: str) -> None:
    sec = _section(doc, "### 1.2", "### 1.3")
    documented = {int(n) for n in re.findall(r"^\| \*\*(\d+)\*\* \|", sec, re.M)}
    assert documented == set(P.LAYOUTS) == {232, 311, 324, 331}
    assert {lay.size: lay.game for lay in P.LAYOUTS.values()} == {
        232: Game.FORZA_MOTORSPORT,
        311: Game.FORZA_MOTORSPORT,
        324: Game.FORZA_HORIZON,
        331: Game.FORZA_MOTORSPORT,
    }


def test_offsets_independent_of_structdef() -> None:
    """Write fields with hand-coded struct.pack_into at the documented offsets; the decoder must read them."""
    hz = bytearray(324)
    struct.pack_into("<i", hz, 0, 1)
    struct.pack_into("<I", hz, 232, 7)  # CarGroup
    struct.pack_into("<f", hz, 256, 25.0)  # Speed
    struct.pack_into("<f", hz, 304, 61.5)  # CurrentLap
    struct.pack_into("<H", hz, 312, 4)  # LapNumber
    struct.pack_into("<B", hz, 315, 255)  # Accel
    struct.pack_into("<B", hz, 319, 3)  # Gear
    struct.pack_into("<b", hz, 320, -127)  # Steer
    struct.pack_into("<f", hz, 268, 212.0)  # TireTempFrontLeft
    out = ForzaAdapter().decode(bytes(hz), T0)
    f = one_frame(out)
    assert f.game is Game.FORZA_HORIZON
    assert f.speed_kph == pytest.approx(90.0) and f.current_lap_time_ms == 61500 and f.lap_number == 5
    assert f.throttle == 1.0 and f.gear == 3 and f.steering == -1.0
    assert f.tyre_surface_temp_c is not None and f.tyre_surface_temp_c.fl == pytest.approx(100.0)
    assert of(out, SessionInfo)[0].extra["car_group"] == 7

    fm = bytearray(331)
    struct.pack_into("<i", fm, 0, 1)
    struct.pack_into("<f", fm, 311, 0.125)  # TireWearFrontLeft, unaligned
    struct.pack_into("<f", fm, 323, 0.5)  # TireWearRearRight
    struct.pack_into("<i", fm, 327, 512)  # TrackOrdinal
    out = ForzaAdapter().decode(bytes(fm), T0)
    f = one_frame(out)
    assert f.tyre_wear_pct is not None
    assert (f.tyre_wear_pct.fl, f.tyre_wear_pct.rr) == pytest.approx((12.5, 50.0))
    assert of(out, SessionInfo)[0].track_id == "forza:512"


# ---------------------------------------------------------------------------------------------- detection / rejection
@pytest.mark.parametrize("fmt", list(ForzaFormat))
def test_each_format_is_detected(fmt: ForzaFormat) -> None:
    a = ForzaAdapter()
    data = pkt(fmt, Speed=10.0)
    assert len(data) == LAYOUT_BY_FORMAT[fmt].size and a.can_decode(data)
    out = a.decode(data, T0)
    game = LAYOUT_BY_FORMAT[fmt].game
    assert one_frame(out).game is game
    assert a.info is (FORZA_HORIZON_INFO if game is Game.FORZA_HORIZON else FORZA_MOTORSPORT_INFO)
    assert a.stats.by_type == {fmt.value: 1} and a.stats.decoded == 1
    assert isinstance(a, GameAdapter)


@pytest.mark.parametrize("size", [0, 4, 231, 233, 310, 312, 323, 325, 330, 332, 1349])
def test_other_sizes_are_rejected(size: int) -> None:
    a = ForzaAdapter()
    data = struct.pack("<i", 1) + bytes(max(0, size - 4)) if size >= 4 else bytes(size)
    assert not a.can_decode(data)
    with pytest.raises(PacketRejected, match="size"):
        a.decode(data, T0)
    assert a.stats.rejected == 1 and a.stats.decoded == 0 and a.stats.last_error


@pytest.mark.parametrize("race_on", [2, -1, 0x01000000])
def test_bad_is_race_on_is_rejected(race_on: int) -> None:
    a = ForzaAdapter()
    data = pkt(IsRaceOn=race_on)
    assert not a.can_decode(data)
    with pytest.raises(PacketRejected, match="IsRaceOn"):
        a.decode(data, T0)
    assert a.stats.rejected == 1


def test_can_decode_requires_plausible_rpm_and_never_raises() -> None:
    a = ForzaAdapter()
    assert not a.can_decode(pkt(EngineMaxRpm=float("nan")))
    assert not a.can_decode(pkt(CurrentEngineRpm=-5.0))
    assert a.can_decode(pkt(IsRaceOn=0))
    for junk in (b"", b"\xff" * 232, b"\x01\x00\x00\x00" + b"\xff" * 327):
        a.can_decode(junk)  # must not raise


def test_no_cross_talk_with_the_f1_adapter() -> None:
    from pitwall.adapters.f1 import packets as F1P

    for layout in F1P.LAYOUTS.values():  # every F1 format: auto-detection by length can never be ambiguous
        assert not set(layout.sizes.values()) & set(P.LAYOUTS), layout.packet_format
    f1_packets, _ = generate_f1_session(F1Scenario(laps=1))
    forza, f1 = ForzaAdapter(), F1Adapter()
    assert not any(forza.can_decode(p.data) for p in f1_packets[:5000])
    assert not any(f1.can_decode(pkt(fmt)) for fmt in ForzaFormat)


def test_decode_errors_are_contained(monkeypatch: pytest.MonkeyPatch) -> None:
    a = ForzaAdapter()

    def boom(*_: Any) -> CarFrame:
        raise RuntimeError("boom")

    monkeypatch.setattr(a, "_frame", boom)
    out = a.decode(pkt(), T0)  # must not raise
    assert a.stats.errors == 1 and "boom" in (a.stats.last_error or "")
    assert of(out, SessionInfo)  # what was produced before the failure still goes out


# ---------------------------------------------------------------------------------------------- units and conventions
def test_dash_units_and_conventions() -> None:
    wheels: dict[str, Any] = {
        "TireTempFrontLeft": 212.0,
        "TireTempFrontRight": 32.0,
        "TireTempRearLeft": 122.0,
        "TireTempRearRight": 194.0,
        "TireWearFrontLeft": 0.1,
        "TireWearFrontRight": 0.2,
        "TireWearRearLeft": 0.3,
        "TireWearRearRight": 0.4,
    }
    out = ForzaAdapter().decode(
        pkt(
            Speed=50.0,
            Accel=255,
            Brake=51,
            Clutch=0,
            HandBrake=255,
            Steer=64,
            Gear=4,
            CurrentEngineRpm=6123.5,
            EngineMaxRpm=8500.0,
            AccelerationX=G0,
            AccelerationY=-0.5 * G0,
            AccelerationZ=-2 * G0,
            VelocityZ=50.0,
            Yaw=1.25,
            Pitch=-0.02,
            Roll=0.03,
            PositionX=-120.5,
            PositionY=14.0,
            PositionZ=980.25,
            LapNumber=2,
            CurrentLap=12.3456,
            LastLap=83.123,
            BestLap=82.5,
            CurrentRaceTime=250.5,
            DistanceTraveled=11_000.0,
            RacePosition=3,
            Fuel=0.42,
            **wheels,
        ),
        T0,
    )
    f = one_frame(out)
    assert f.speed_kph == pytest.approx(180.0)
    assert (f.throttle, f.brake, f.clutch) == pytest.approx((1.0, 0.2, 0.0))
    assert f.steering == pytest.approx(64 / 127) and f.gear == 4
    assert f.rpm == pytest.approx(6123.5) and f.max_rpm == pytest.approx(8500.0)
    assert f.g_lat == pytest.approx(1.0) and f.g_lon == pytest.approx(-2.0) and f.g_vert == pytest.approx(-0.5)
    assert (f.yaw_rad, f.pitch_rad, f.roll_rad) == pytest.approx((1.25, -0.02, 0.03))
    assert (f.pos_x_m, f.pos_y_m, f.pos_z_m) == pytest.approx((-120.5, 14.0, 980.25))
    assert f.lap_number == 3  # LapNumber counts completed laps; pitwall's lap is 1-based
    assert f.current_lap_time_ms == 12346 and f.last_lap_time_ms == 83123
    assert f.session_time_s == pytest.approx(250.5) and f.total_distance_m == pytest.approx(11_000.0)
    assert f.race_position == 3
    assert f.tyre_surface_temp_c is not None  # degF -> degC, FL, FR, RL, RR
    assert f.tyre_surface_temp_c.as_tuple() == pytest.approx((100.0, 0.0, 50.0, 90.0))
    assert f.tyre_wear_pct is not None
    assert f.tyre_wear_pct.as_tuple() == pytest.approx((10.0, 20.0, 30.0, 40.0), abs=1e-4)
    # never fabricated: not in the protocol, or not absolute (fuel is a tank fraction)
    assert f.fuel_kg is None and f.fuel_litres is None and f.tyre_inner_temp_c is None
    assert f.vel_x_mps is None and f.vel_y_mps is None and f.vel_z_mps is None  # car-local only
    assert f.sector is None and f.lap_invalid is None and f.pit_status is None and f.tyre_pressure_psi is None
    assert f.lap_distance_m is None  # no line crossing observed yet
    assert f.quality == FrameQuality.OK
    info = of(out, SessionInfo)[0]
    assert info.extra["fuel_fraction"] == pytest.approx(0.42) and info.extra["best_lap_ms"] == 82500
    assert info.extra["drivetrain"] is None or isinstance(info.extra["drivetrain"], str)


@pytest.mark.parametrize(("raw", "steer"), [(-127, -1.0), (127, 1.0), (-128, -1.0), (0, 0.0), (-32, -32 / 127)])
def test_steering_sign_and_clamp(raw: int, steer: float) -> None:
    assert one_frame(ForzaAdapter().decode(pkt(Steer=raw), T0)).steering == pytest.approx(steer)


@pytest.mark.parametrize(("raw", "gear"), [(0, None), (1, 1), (6, 6), (10, 10), (11, None), (255, None)])
def test_gear_only_maps_documented_forward_gears(raw: int, gear: int | None) -> None:
    assert one_frame(ForzaAdapter().decode(pkt(Gear=raw), T0)).gear == gear


def test_zero_and_non_finite_values_stay_unknown() -> None:
    f = one_frame(
        ForzaAdapter().decode(
            pkt(
                Speed=float("nan"),
                LastLap=0.0,
                RacePosition=0,
                EngineMaxRpm=0.0,
                TireTempRearLeft=float("inf"),
                TireWearFrontRight=float("nan"),
                Yaw=float("nan"),
            ),
            T0,
        )
    )
    assert f.speed_kph is None and f.last_lap_time_ms is None and f.race_position is None and f.max_rpm is None
    assert f.tyre_surface_temp_c is None and f.tyre_wear_pct is None and f.yaw_rad is None


def test_horizon_has_no_tyre_wear_and_reports_car_group() -> None:
    out = ForzaAdapter().decode(pkt(ForzaFormat.HORIZON_DASH, CarGroup=9, TireTempFrontLeft=150.0), T0)
    f = one_frame(out)
    assert f.game is Game.FORZA_HORIZON and f.tyre_wear_pct is None
    info = of(out, SessionInfo)[0]
    assert info.extra["car_group"] == 9 and info.track_id is None and info.car_id == "forza:fh:car:1234"


def test_sled_derives_speed_from_velocity_and_has_no_dash_channels() -> None:
    out = ForzaAdapter().decode(pkt(ForzaFormat.SLED, VelocityX=3.0, VelocityY=0.0, VelocityZ=4.0), T0)
    f = one_frame(out)
    assert f.speed_kph == pytest.approx(18.0) and f.rpm == pytest.approx(5000.0)
    assert f.throttle is None and f.gear is None and f.lap_number is None and f.pos_x_m is None
    assert f.session_time_s is None and f.tyre_surface_temp_c is None
    info = of(out, SessionInfo)[0]
    assert info.car_id == "forza:fm:car:1234" and "fuel_fraction" not in info.extra


def test_adapter_info_is_honest() -> None:
    for info in (FORZA_MOTORSPORT_INFO, FORZA_HORIZON_INFO):
        assert info.ground_plane == ("pos_x_m", "pos_z_m") and info.transport == "udp"
        assert info.default_port is not None and not 5200 <= info.default_port <= 5300  # FH6 doc: avoid 5200-5300
        for key in ("fuel_kg", "fuel_litres", "tyre_pressure_psi", "brake_temp_c", "sector", "vel_x_mps"):
            assert info.fields[key].level is SupportLevel.UNSUPPORTED, key
        assert info.fields["lap_distance_m"].level is SupportLevel.PARTIAL
        assert info.fields["gear"].level is SupportLevel.PARTIAL
        assert info.fields["tyre_surface_temp_c"].level is SupportLevel.COMMUNITY_DOCUMENTED
        assert all(lvl is not SupportLevel.LIVE_VALIDATED for lvl in info.platforms.values())
        assert all(fs.level is not SupportLevel.LIVE_VALIDATED for fs in info.fields.values())
    assert FORZA_HORIZON_INFO.platforms[Platform.PS5] is SupportLevel.UNVERIFIED
    assert Platform.PS5 not in FORZA_MOTORSPORT_INFO.platforms
    assert FORZA_HORIZON_INFO.fields["tyre_wear_pct"].level is SupportLevel.UNSUPPORTED


# ---------------------------------------------------------------------------------------------- sessions
def test_menus_before_driving_create_nothing() -> None:
    tr = Stream()
    assert tr.off(30) == []
    assert tr.a.stats.ignored == 30 and tr.a.stats.decoded == 0


def test_first_race_on_packet_starts_a_session() -> None:
    tr = Stream()
    out = tr.step()
    assert [type(e).__name__ for e in out] == ["SessionInfo", "GameEvent", "CarFrame"]
    info, ev = out[0], out[1]
    assert isinstance(info, SessionInfo) and isinstance(ev, GameEvent)
    assert info.session_uid == f"forza:fm2023_dash:{tr.t}" and info.game is Game.FORZA_MOTORSPORT
    assert info.track_id == "forza:77" and info.extra["track_id_source"] == "track_ordinal"
    assert info.car_id == "forza:fm2023:car:1234" and info.platform is Platform.UNKNOWN
    assert ev.kind is EventKind.SESSION_STARTED and ev.payload["source"] == "derived"


def test_session_info_is_repeated_twice_a_second() -> None:
    tr = Stream()
    out = tr.step(120)  # 2 s
    assert len(of(out, SessionInfo)) in (4, 5)
    assert len({i.session_uid for i in of(out, SessionInfo)}) == 1


def test_pause_inside_a_session_yields_empty_flagged_frames() -> None:
    tr = Stream()
    tr.step(5)
    out = tr.off(3)
    assert len(out) == 3
    for f in of(out, CarFrame):
        assert f.quality == FrameQuality.PAUSED | FrameQuality.NOT_RACING
        assert f.speed_kph is None and f.lap_number is None and f.pos_x_m is None
    resumed = tr.step()
    assert one_frame(resumed).quality == FrameQuality.OK and not of(resumed, GameEvent)


def test_long_race_off_ends_the_session_and_menus_stay_silent() -> None:
    tr = Stream()
    tr.step(5)
    tr.off(1)
    out = tr.off(1, dt_ns=int(A.SESSION_END_IDLE_S * 1e9))
    (ev,) = of(out, GameEvent)
    assert ev.kind is EventKind.SESSION_ENDED and ev.payload["reason"] == "race_off_timeout"
    assert not of(out, CarFrame)
    assert tr.off(10) == []  # back to "menus before driving"
    restarted = tr.step()
    assert of(restarted, SessionInfo)[0].session_uid == f"forza:fm2023_dash:{tr.t}"


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"CarOrdinal": 999}, "car_changed"),
        ({"TrackOrdinal": 78}, "track_changed"),
        ({"CurrentRaceTime": 0.2}, "race_restarted"),
        ({"CurrentRaceTime": 1.5, "LapNumber": 0}, "race_restarted"),
    ],
)
def test_session_splits(change: dict[str, Any], reason: str) -> None:
    tr = Stream()
    tr.race_time = 100.0
    tr.lap = 3
    first = of(tr.step(5), SessionInfo)[0].session_uid
    tr.extra = change
    out = tr.step()
    kinds = [(type(e).__name__, getattr(e, "kind", None)) for e in out]
    assert kinds[0] == ("GameEvent", EventKind.SESSION_ENDED), kinds
    assert of(out, GameEvent)[0].payload["reason"] == reason
    infos = of(out, SessionInfo)
    assert infos and infos[0].session_uid != first
    assert of(out, GameEvent)[1].kind is EventKind.SESSION_STARTED


def test_format_change_starts_a_new_session_and_switches_info() -> None:
    a = ForzaAdapter()
    a.decode(pkt(ForzaFormat.FM2023_DASH), T0)
    assert a.info is FORZA_MOTORSPORT_INFO
    out = a.decode(pkt(ForzaFormat.HORIZON_DASH), T0 + FRAME_NS)
    assert of(out, GameEvent)[0].payload["reason"] == "format_changed"
    assert a.info is FORZA_HORIZON_INFO and one_frame(out).game is Game.FORZA_HORIZON


def test_short_rewind_is_a_flashback_not_a_new_session() -> None:
    tr = Stream()
    tr.race_time = 100.0
    uid = of(tr.step(5), SessionInfo)[0].session_uid
    tr.race_time -= 4.0
    tr.dist -= 200.0
    out = tr.step()
    (ev,) = of(out, GameEvent)
    assert ev.kind is EventKind.FLASHBACK and ev.payload["rewind_s"] == pytest.approx(4.0 - 1 / 60, abs=0.01)
    assert all(i.session_uid == uid for i in of(out, SessionInfo))
    tr.race_time -= 1.0  # the game scrubbing back again straight away: one event per rewind
    assert not of(tr.step(), GameEvent)


def test_synthetic_marker_maps_to_the_synthetic_session_uid() -> None:
    out = ForzaAdapter().decode(pkt(CarOrdinal=P.SYNTHETIC_CAR_ORDINAL), T0)
    assert of(out, SessionInfo)[0].session_uid == str(SYNTHETIC_SESSION_UID)


def test_reset_forgets_the_session() -> None:
    a = ForzaAdapter()
    a.decode(pkt(), T0)
    a.reset()
    assert of(a.decode(pkt(), T0 + FRAME_NS), GameEvent)[0].kind is EventKind.SESSION_STARTED


# ---------------------------------------------------------------------------------------------- laps
def test_lap_distance_is_unknown_until_the_first_crossing_then_derived() -> None:
    tr = Stream()
    assert all(f.lap_distance_m is None for f in of(tr.step(30), CarFrame))
    start = tr.dist + tr.v / 60
    out = tr.cross(last=70.0)
    f = one_frame(out)
    assert f.lap_number == 2 and f.lap_distance_m == pytest.approx(0.0)
    f = one_frame(tr.step(60)[-1:])
    assert f.lap_distance_m == pytest.approx(tr.dist - start, abs=1e-2) and f.total_distance_m == pytest.approx(tr.dist)


def test_completion_precedes_the_new_laps_frame() -> None:
    tr = Stream()
    tr.step(10)
    out = tr.cross(last=71.25)
    kinds = [type(e).__name__ for e in out if not isinstance(e, SessionInfo)]
    assert kinds == ["LapCompletion", "CarFrame"]
    (c,) = of(out, LapCompletion)
    assert (c.lap_number, c.lap_time_ms, c.valid) == (1, 71250, None)
    assert c.session_time_s == pytest.approx(tr.race_time, abs=1e-3)


def test_stale_last_lap_holds_frames_until_it_updates() -> None:
    tr = Stream()
    tr.last = 70.0
    tr.step(10)
    tr.cross(last=70.0)  # first crossing (fresh vs session start? no: unchanged and not matching the lap clock)
    assert tr.a.stats.by_type.get("last_lap_held") == 1
    held_out = tr.step(2)  # still stale
    assert not of(held_out, CarFrame) and not of(held_out, LapCompletion)
    tr.last = 72.5
    out = tr.step()
    seq = [e for e in out if not isinstance(e, SessionInfo)]
    assert isinstance(seq[0], LapCompletion) and seq[0].lap_time_ms == 72500 and seq[0].lap_number == 1
    frames = of(seq, CarFrame)
    assert len(frames) == 4 and all(f.lap_number == 2 for f in frames)  # crossing + 2 held + current, in order
    assert [f.t_recv_ns for f in frames] == sorted(f.t_recv_ns for f in frames)


def test_unchanged_last_lap_matching_the_lap_clock_is_an_equal_lap_time() -> None:
    tr = Stream()
    tr.cur = 0.0
    tr.step(10)
    out = tr.cross(last=60.0)  # first lap: 60.000 s
    assert of(out, LapCompletion)[0].lap_time_ms == 60000
    tr.cur = 59.98  # second lap takes exactly as long: LastLap does not change; the lap clock agrees
    tr.step()
    out = tr.cross()
    (c,) = of(out, LapCompletion)
    assert c.lap_number == 2 and c.lap_time_ms == 60000 and of(out, CarFrame)
    assert "last_lap_held" not in tr.a.stats.by_type


def test_last_lap_that_never_updates_times_out_without_a_time() -> None:
    tr = Stream()
    tr.last = 70.0
    tr.step(10)
    tr.cross()  # LastLap stays 70.0, lap clock says ~12.2 s: stale
    out: list[Emitted] = []
    for _ in range(40):
        out += tr.step()
    (c,) = of(out, LapCompletion)
    assert c.lap_time_ms is None and c.lap_number == 1
    assert tr.a.stats.by_type["last_lap_timeout"] == 1
    assert len(of(out, CarFrame)) == 41  # nothing dropped: the held crossing frame + 40 later frames
    held_until = out.index(c)
    assert all(isinstance(e, (CarFrame, SessionInfo)) for e in out[held_until + 1 :])


def test_late_last_lap_after_timeout_is_absorbed_not_reused() -> None:
    tr = Stream()
    tr.last = 70.0
    tr.step(10)
    tr.cross()
    tr.step(40)  # timed out
    tr.last = 73.0  # arrives late: belongs to lap 1, must not complete anything or leak into lap 2
    assert not of(tr.step(), LapCompletion)
    assert tr.a.stats.by_type["last_lap_absorbed"] == 1
    tr.step(60)
    out = tr.cross(last=74.0)
    (c,) = of(out, LapCompletion)
    assert (c.lap_number, c.lap_time_ms) == (2, 74000)


def test_race_off_during_hold_is_held_then_released_untimed() -> None:
    tr = Stream()
    tr.last = 70.0
    tr.step(10)
    tr.cross()
    assert tr.off() == []  # a brief race-off must not cost the lap its time: still holding
    out = tr.off(10)
    seq = [type(e).__name__ for e in out]
    assert seq[0] == "LapCompletion" and set(seq[1:]) == {"CarFrame"}
    (c,) = of(out, LapCompletion)
    assert c.lap_number == 1 and c.lap_time_ms is None
    frames = of(out, CarFrame)
    assert frames[0].quality == FrameQuality.OK and frames[0].lap_number == 2  # the held crossing frame first
    assert all(f.quality & FrameQuality.PAUSED for f in frames[1:]) and len(frames) == 1 + 11
    assert [f.t_recv_ns for f in frames] == sorted(f.t_recv_ns for f in frames)


def test_race_off_last_lap_counts_only_when_it_matches_the_lap_clock() -> None:
    tr = Stream()
    tr.last = 70.0
    tr.step(10)
    lap_clock = tr.cur  # CurrentLap of the last packet before the line
    tr.cross()
    # Forza Motorsport stops the race at the flag: a LastLap read from that payload is corroborated by the clock
    out = tr.feed((tr.t + FRAME_NS, pkt(IsRaceOn=0, LastLap=lap_clock + 0.01)))
    (c,) = of(out, LapCompletion)
    assert c.lap_number == 1 and c.lap_time_ms == round((lap_clock + 0.01) * 1000)
    assert [type(e).__name__ for e in out] == ["LapCompletion", "CarFrame", "CarFrame"]
    assert tr.a.stats.by_type["last_lap_race_off"] == 1

    tr = Stream()
    tr.last = 70.0
    tr.step(10)
    tr.cross()
    out = tr.feed((tr.t + FRAME_NS, pkt(IsRaceOn=0, LastLap=75.0)))  # new, but not this lap's time: unproven
    assert not of(out, LapCompletion)
    tr.t += FRAME_NS
    out = tr.off(10)
    assert of(out, LapCompletion)[0].lap_time_ms is None and "last_lap_race_off" not in tr.a.stats.by_type


def test_final_lap_without_increment_completes_and_marks_cool_down() -> None:
    tr = Stream()
    tr.step(5)
    tr.cross(last=70.0)
    tr.step(int(A.LATE_LAST_LAP_WINDOW_S * 60) + 60)
    tr.last = 68.75  # chequered flag: LastLap updates, LapNumber does not
    out = tr.step()
    (c,) = of(out, LapCompletion)
    assert (c.lap_number, c.lap_time_ms) == (2, 68750)
    assert one_frame(out).quality & FrameQuality.NOT_RACING
    assert all(f.quality & FrameQuality.NOT_RACING for f in of(tr.step(30), CarFrame))
    out = tr.cross()  # the game counts the lap after all: no duplicate completion
    assert not of(out, LapCompletion) and one_frame(out).quality == FrameQuality.OK


def test_rewind_across_the_line_restores_the_previous_lap_origin() -> None:
    tr = Stream()
    tr.step(5)
    start1 = tr.dist + tr.v / 60
    tr.cross(last=70.0)
    tr.step(600)
    start2 = tr.dist + tr.v / 60
    tr.cross(last=71.0)
    tr.step(60)
    tr.lap -= 1  # rewound to before the line
    tr.race_time -= 3.0
    tr.dist = start2 - 20.0
    tr.cur = 70.5
    tr.last = 70.0
    out = tr.step()
    f = one_frame(out)
    assert f.lap_number == 2 and f.lap_distance_m == pytest.approx(start2 - 20.0 + tr.v / 60 - start1, abs=0.05)
    assert of(out, GameEvent)[0].kind is EventKind.FLASHBACK
    out = tr.cross(last=70.9)  # crosses again: lap 2 completes again with the re-driven time
    assert of(out, LapCompletion)[0].lap_time_ms == 70900


def test_lap_number_jump_leaves_the_origin_unknown() -> None:
    tr = Stream()
    tr.step(5)
    tr.cross(last=70.0)
    tr.lap += 1  # packets lost across a whole lap
    tr.last = 71.0
    out = tr.cross(last=72.0)
    assert not of(out, LapCompletion)
    assert one_frame(out).lap_distance_m is None and tr.a.stats.by_type["lap_skip"] == 1


@pytest.mark.parametrize("hz", [60, 1000])
def test_hold_is_short_and_bounded_in_time_and_frames(hz: int) -> None:
    """Held frames reach the live view and the cue engine late, so the hold is capped by time *and* frame count
    (FH6 streams at the game's frame rate)."""
    tr = Stream(hz=hz)
    tr.last = 70.0
    tr.step(10)
    out = tr.cross()  # LastLap never updates
    t_cross = tr.t
    out += tr.step(hz)
    (c,) = of(out, LapCompletion)
    assert c.lap_time_ms is None and A.LAST_LAP_HOLD_S <= 0.1
    assert c.t_recv_ns - t_cross <= A.LAST_LAP_HOLD_S * 1e9 + 1e9 / hz  # released by the first packet past it
    i = out.index(c)
    held = [f for f in of(out[i + 1 :], CarFrame) if f.t_recv_ns <= c.t_recv_ns]
    assert 1 <= len(held) <= A.LAST_LAP_HOLD_MAX_FRAMES
    assert not of(out[:i], CarFrame) or of(out[:i], CarFrame)[-1].t_recv_ns < t_cross  # nothing overtook the hold


def test_stream_ending_inside_the_hold_is_drained() -> None:
    """FH6 sends nothing after the finish: the crossing can be the last datagram, with LastLap not yet updated."""
    tr = Stream(fmt=ForzaFormat.HORIZON_DASH)
    assert tr.a.drain() == []  # nothing to release before a session
    tr.step(5)
    out = tr.cross(last=70.0)
    out += tr.step(600)
    out += tr.cross(last=71.0)
    out += tr.step(600)
    finish = tr.cross()  # the finish - then silence
    assert not of(finish, CarFrame) and tr.a.stats.by_type["last_lap_held"] == 1
    out += finish
    drained = tr.a.drain()
    assert [type(e).__name__ for e in drained] == ["LapCompletion", "CarFrame"]
    c = drained[0]
    assert isinstance(c, LapCompletion) and (c.lap_number, c.lap_time_ms) == (3, None)
    assert c.t_recv_ns == tr.t and tr.a.stats.by_type["last_lap_drained"] == 1
    assert tr.a.drain() == []  # idempotent

    # router.finish order: drain -> session manager, then the session ends (assembler flush), then reset
    laps = {lap.lap_number: lap for lap in assemble(out + drained, flush=True)}
    assert laps[2].lap_time_ms == 71000 and laps[2].clean
    assert laps[3].lap_time_ms is None and LapFlag.INCOMPLETE not in laps[3].flags  # analysed, just untimed
    # without the drain the race's final lap would be thrown away as incomplete
    assert LapFlag.INCOMPLETE in {lap.lap_number: lap for lap in assemble(out, flush=True)}[3].flags
    tr.a.reset()
    assert tr.a.drain() == []


def test_late_datagram_at_the_line_is_dropped_not_a_second_crossing() -> None:
    tr = Stream()
    tr.step(5)
    out = tr.cross(last=70.0)
    out += tr.step(600)
    before, crossing, after = tr.make(), tr.make_cross(last=71.0), tr.make()
    out += tr.feed(crossing, before, after)  # the network delivered the last pre-line packet late
    out += tr.step(600)
    out += tr.cross(last=72.0)
    assert [(c.lap_number, c.lap_time_ms) for c in of(out, LapCompletion)] == [(1, 70000), (2, 71000), (3, 72000)]
    assert tr.a.stats.by_type["out_of_order"] == 1 and "rewind" not in tr.a.stats.by_type
    assert not of(out, GameEvent)[1:]  # only SESSION_STARTED: no flashback
    assert len(of(out, SessionInfo)[-1].extra["measured_lap_lengths_m"]) == 2  # no duplicate length sample
    laps = assemble(out)
    assert [lap.lap_number for lap in laps] == [2, 3] and all(lap.clean for lap in laps)
    assert laps[0].lap_time_ms == 71000 and laps[0].n == 601  # every lap-2 frame, the late one dropped


def test_late_datagram_mid_lap_does_not_flag_a_flashback() -> None:
    tr = Stream()
    tr.step(5)
    out = tr.cross(last=70.0)
    out += tr.step(300)
    p1, p2 = tr.make(), tr.make()
    out += tr.feed(p2, p1)
    out += tr.step(300)
    out += tr.cross(last=71.0)
    (lap,) = assemble(out)
    assert lap.clean and LapFlag.FLASHBACK not in lap.flags
    assert tr.a.stats.by_type["out_of_order"] == 1 and tr.a.stats.ignored == 1


def test_late_streak_is_bounded_so_nothing_is_dropped_for_good() -> None:
    tr = Stream()
    tr.step(5)
    tr.race_time -= 0.2  # the stream itself steps back a little (no reordering): it must be accepted soon
    out = tr.step(20)
    assert tr.a.stats.by_type["out_of_order"] == A.LATE_MAX_STREAK
    assert tr.a.stats.by_type["late_streak_accepted"] == 1
    assert len(of(out, CarFrame)) == 20 - A.LATE_MAX_STREAK

    tr = Stream()  # unreadable race clock and a lap counter one lower from now on: resynchronised, not starved
    tr.lap = 3
    tr.step(5)
    tr.lap = 2
    tr.extra = {"CurrentRaceTime": float("nan")}
    out = tr.step(20)
    assert tr.a.stats.by_type["out_of_order"] == A.LATE_MAX_STREAK
    frames = of(out, CarFrame)
    assert len(frames) == 20 - A.LATE_MAX_STREAK and all(f.lap_number == 3 for f in frames)


def test_reset_to_track_unanchors_the_lap_and_is_never_measured() -> None:
    tr = Stream(fmt=ForzaFormat.FM7_DASH)  # no TrackOrdinal: the fingerprint path
    tr.step(5)
    out = tr.cross(last=70.0)  # the line, at (100, -40)
    out += tr.step(300)
    tr.extra = {"PositionX": 400.0}  # reset 300 m away; the odometer does not jump
    jump = tr.step()
    assert tr.a.stats.by_type["teleport"] == 1 and one_frame(jump).lap_distance_m is None
    out += jump
    rest = tr.step(298)
    tr.extra = {}
    rest += tr.step()  # and back (another jump inside the same lap)
    assert all(f.lap_distance_m is None for f in of(rest, CarFrame))
    out += rest
    out += tr.cross(last=71.0)
    (c2,) = [c for c in of(out, LapCompletion) if c.lap_number == 2]
    assert c2.valid is False and c2.lap_time_ms == 71000  # timed, but its trace stops at the reset
    info = of(out, SessionInfo)[-1]
    assert info.track_id is None and info.track_length_m is None and info.extra["measured_lap_lengths_m"] == []
    assert tr.a.stats.by_type["lap_length_untrusted"] == 1
    assert one_frame(out[-1:]).lap_distance_m == pytest.approx(0.0)  # re-anchored at the crossing
    out += tr.step(600)
    out += tr.cross(last=72.0)
    info = of(out, SessionInfo)[-1]
    assert info.track_id is not None and info.track_id.startswith("forza_fp:fm7:100:-40:")
    assert len(info.extra["measured_lap_lengths_m"]) == 1
    laps = {lap.lap_number: lap for lap in assemble(out)}
    assert LapFlag.INVALID in laps[2].flags and not laps[2].clean  # never a reference, never trains a model
    assert laps[3].clean


def test_reset_across_the_line_leaves_the_new_lap_unanchored() -> None:
    """LapNumber advancing on the very packet that moved the car: whether it drove to the line is unknown, and the
    new lap's origin is not on the line - neither lap is measured, both are completed valid=False."""
    tr = Stream(fmt=ForzaFormat.FM7_DASH)
    tr.step(5)
    tr.cross(last=70.0)
    tr.step(600)
    tr.extra = {"PositionX": 900.0}
    out = tr.cross(last=71.0)
    (c,) = of(out, LapCompletion)
    assert (c.lap_number, c.valid) == (2, False) and one_frame(out).lap_distance_m is None
    out = tr.step(600) + tr.cross(last=72.0)
    (c,) = of(out, LapCompletion)
    assert (c.lap_number, c.valid) == (3, False) and one_frame(out[-1:]).lap_distance_m == pytest.approx(0.0)
    out += tr.step(600) + tr.cross(last=73.0)
    assert [x.valid for x in of(out, LapCompletion)] == [False, None]  # lap 4 started on the line again
    info = of(out, SessionInfo)[-1]
    assert len(info.extra["measured_lap_lengths_m"]) == 1  # lap 4 only
    assert info.track_id is not None and info.track_id.startswith("forza_fp:fm7:100:-40:")  # the true line


def test_absurd_float_values_are_unknown_and_serialisable() -> None:
    """Forza times are float32: 3e38 s is finite, and as integer milliseconds it would overflow orjson / SQLite."""
    out = ForzaAdapter().decode(
        pkt(
            CurrentLap=3.4e38,
            LastLap=3.0e38,
            BestLap=1e30,
            CurrentRaceTime=3.4e38,
            PositionX=3.0e38,
            DistanceTraveled=-3.0e38,
        ),
        T0,
    )
    f = one_frame(out)
    assert f.current_lap_time_ms is None and f.last_lap_time_ms is None and f.session_time_s is None
    assert f.pos_x_m is None and f.total_distance_m is None and f.lap_distance_m is None
    info = of(out, SessionInfo)[0]
    assert info.extra["best_lap_ms"] is None
    orjson.dumps(frame_to_dict(f))
    orjson.dumps(info.extra)
    for cur, ms in ((-1.0, None), (86_400.5, None), (86_399.0, 86_399_000), (0.0, 0)):
        assert one_frame(ForzaAdapter().decode(pkt(CurrentLap=cur), T0)).current_lap_time_ms == ms

    tr = Stream()
    tr.step(5)
    out = tr.cross(last=3.0e38)  # a garbage LastLap is no lap time
    out += tr.step(10)
    (c,) = of(out, LapCompletion)
    assert c.lap_time_ms is None


@pytest.mark.parametrize(
    ("samples", "length"),
    [
        ([4000.0], 4000.0),
        ([4000.0, 3950.04, 4010.0], 3950.0),  # the shortest normal lap, floored to 0.1 m
        ([4000.0, 4000.0, 3800.0], 4000.0),  # 5 % short: a cut, not a line - ignored
        ([20_800.0, 20_800.0, 20_716.0], 20_716.0),  # Nordschleife, 0.4 % tighter line
    ],
)
def test_derived_track_length_is_the_shortest_plausible_lap(samples: list[float], length: float) -> None:
    assert ForzaAdapter._derived_length(samples) == pytest.approx(length)


# ---------------------------------------------------------------------------------------------- track identity
def test_fingerprint_round_trip_and_tolerances() -> None:
    fp = TrackFingerprint("fh", 101.4, -2050.6, 359.4, 4123.4)
    assert fp.track_id == "forza_fp:fh:101:-2051:359:4123"
    parsed = TrackFingerprint.parse(fp.track_id)
    assert parsed is not None and parsed.track_id == fp.track_id
    assert parsed.matches(TrackFingerprint("fh", 130.0, -2040.0, 2.0, 4090.0))  # heading wraps through 0
    assert not parsed.matches(TrackFingerprint("fh", 101.0, -2051.0, 179.0, 4123.0))  # reverse layout
    assert not parsed.matches(TrackFingerprint("fh", 101.0, -2051.0, 359.0, 4123.0 * 1.1))  # other layout
    assert not parsed.matches(TrackFingerprint("fh", 200.0, -2051.0, 359.0, 4123.0))  # elsewhere
    assert not parsed.matches(TrackFingerprint("fm7", 101.0, -2051.0, 359.0, 4123.0))  # other title's world
    for bad in (
        "forza:12",
        "forza_fp:fh:1:2:3",
        "forza_fp:fh:a:2:3:4",
        "forza_fp:fh:1:2:3:-5",
        "forza_fp:fh:1:nan:3:4",
    ):
        assert TrackFingerprint.parse(bad) is None, bad
    a = ForzaAdapter(known_track_ids=["forza:3", fp.track_id])
    assert a.known_track_ids == [fp.track_id] and not a.register_track_id("f1:10")


@pytest.mark.synthetic
@pytest.mark.parametrize("fmt", [ForzaFormat.FM7_DASH, ForzaFormat.HORIZON_DASH])
def test_fingerprint_track_id_is_stable_across_sessions(fmt: ForzaFormat) -> None:
    sc = ForzaScenario(fmt=fmt, flying_laps=1, car_ordinal=4321)
    out, a = decode_all(generate_forza_session(sc)[0])
    ids = {i.track_id for i in of(out, SessionInfo)} - {None}
    assert len(ids) == 1
    (tid,) = ids
    assert tid is not None
    family = LAYOUT_BY_FORMAT[fmt].family
    assert tid.startswith(f"forza_fp:{family}:0:0:0:")
    first_completion = out.index(of(out, LapCompletion)[1])
    assert any(isinstance(e, SessionInfo) and e.track_id == tid for e in out[:first_completion])

    # same circuit, crossing 25 m to the side: matched, in this process and after a restart (seeded registry)
    again = ForzaScenario(fmt=fmt, flying_laps=1, car_ordinal=4321, origin_m=(25.0, -10.0))
    out2, _ = decode_all(generate_forza_session(again)[0], a)
    assert {i.track_id for i in of(out2, SessionInfo)} - {None} == {tid}
    out3, _ = decode_all(generate_forza_session(again)[0], ForzaAdapter(known_track_ids=[tid]))
    assert {i.track_id for i in of(out3, SessionInfo)} - {None} == {tid}
    # 300 m away is another circuit
    far = ForzaScenario(fmt=fmt, flying_laps=1, car_ordinal=4321, origin_m=(300.0, 0.0))
    out4, _ = decode_all(generate_forza_session(far)[0], ForzaAdapter(known_track_ids=[tid]))
    assert ({i.track_id for i in of(out4, SessionInfo)} - {None}).isdisjoint({tid})


@pytest.mark.synthetic
def test_synthetic_fingerprints_never_touch_the_registry() -> None:
    sc = ForzaScenario(fmt=ForzaFormat.FM7_DASH, flying_laps=1)  # SYNTHETIC_CAR_ORDINAL
    packets, truth = generate_forza_session(sc)
    real_id = TrackFingerprint("fm7", 0.0, 0.0, 0.0, truth.lap_length_m).track_id  # a real circuit right there
    a = ForzaAdapter(known_track_ids=[real_id])
    out, _ = decode_all(packets, a)
    (tid,) = {i.track_id for i in of(out, SessionInfo)} - {None}
    assert tid is not None and tid.startswith("synthetic:forza_fp:fm7:0:0:0:")  # not matched to the real id
    assert a.known_track_ids == [real_id]  # and not added to the registry
    assert TrackFingerprint.parse(tid) is None and not a.register_track_id(tid)

    fresh = ForzaAdapter()
    decode_all(packets, fresh)
    assert fresh.known_track_ids == []
    real = ForzaScenario(fmt=ForzaFormat.FM7_DASH, flying_laps=1, car_ordinal=4321)
    out, _ = decode_all(generate_forza_session(real)[0], fresh)
    (rid,) = {i.track_id for i in of(out, SessionInfo)} - {None}
    assert rid is not None and rid.startswith("forza_fp:fm7:0:0:0:") and fresh.known_track_ids == [rid]


def test_horizon_free_roam_has_no_laps() -> None:
    tr = Stream(fmt=ForzaFormat.HORIZON_DASH)
    tr.race_time = 0.0
    out: list[Emitted] = []
    for _ in range(600):  # 10 s cruising, LapNumber stays 0 and the race clock does not run
        tr.race_time = 0.0
        out += tr.step()
    frames = of(out, CarFrame)
    assert len(frames) == 600 and all(f.speed_kph == pytest.approx(180.0) for f in frames)
    assert all(f.lap_distance_m is None for f in frames)
    assert not of(out, LapCompletion) and {i.track_id for i in of(out, SessionInfo)} == {None}
    assert len({i.session_uid for i in of(out, SessionInfo)}) == 1
    assert assemble(out) == []


# ---------------------------------------------------------------------------------------------- end to end (synthetic)
def _replay(sc: ForzaScenario) -> tuple[list[Emitted], list[LapTrace], ForzaTruth, ForzaAdapter]:
    packets, truth = generate_forza_session(sc)
    out, a = decode_all(packets)
    return out, assemble(out), truth, a


@pytest.mark.synthetic
@pytest.mark.parametrize("fmt", DASH_FORMATS)
def test_replay_produces_clean_laps_with_exact_times(fmt: ForzaFormat) -> None:
    sc = ForzaScenario(
        fmt=fmt,
        flying_laps=3,
        driver_by_lap={3: DriverProfile(deviations={"T3": CornerDeviation(brake_early_m=15)})},
    )
    out, laps, truth, a = _replay(sc)
    assert a.stats.rejected == 0 and a.stats.errors == 0 and a.stats.decoded == truth.packets_race_on
    assert {e.session_uid for e in of(out, SessionInfo)} == {str(SYNTHETIC_SESSION_UID)}
    by_lap = {lap.lap_number: lap for lap in laps}
    assert sorted(by_lap) == [2, 3, 4]  # lap 1 is the out-lap: its start was never observed
    assert truth.lap_times_ms[3] > truth.lap_times_ms[2]  # the injected mistake costs time
    for n, lap in by_lap.items():
        assert lap.lap_time_ms == truth.lap_times_ms[n]
        assert lap.flags == set() and lap.clean
        d = lap.channels["distance_m"]
        assert d[0] == pytest.approx(0.0, abs=2.0) and d[-1] == pytest.approx(truth.lap_length_m, abs=2.0)
    completions = of(out, LapCompletion)
    assert [c.lap_number for c in completions] == [1, 2, 3, 4]
    assert completions[0].lap_time_ms == truth.outlap_time_ms
    info = of(out, SessionInfo)[-1]
    assert info.track_length_m == pytest.approx(truth.lap_length_m, abs=2.0)
    assert info.extra["track_length_source"] == "derived:shortest_recent_driven_lap"
    assert info.extra["track_length_nominal_m"] == pytest.approx(truth.lap_length_m, abs=2.0)
    assert info.extra["lap_distance_source"] == A.LAP_DISTANCE_SOURCE == "derived:distance_traveled"
    assert info.track_id is not None and info.game is sc.game
    if sc.fmt is not ForzaFormat.FM2023_DASH:  # synthetic fingerprints stay out of the real namespace
        assert info.track_id.startswith("synthetic:forza_fp:") and a.known_track_ids == []


@pytest.mark.synthetic
def test_replay_traces_carry_converted_channels() -> None:
    _, laps, truth, _ = _replay(ForzaScenario(flying_laps=1))
    (lap,) = laps
    ch = lap.channels
    assert truth.track is not None
    assert math.isclose(float(ch["speed_kph"].max()), 3.6 * 95.0, rel_tol=0.02)  # vehicle v_max 95 m/s
    assert ch["throttle"].min() >= 0.0 and ch["throttle"].max() == pytest.approx(1.0)
    assert ch["brake"].max() > 0.5 and abs(ch["steering"]).max() <= 1.0
    assert ch["gear"].min() >= 1 and ch["gear"].max() <= 8
    assert 70.0 < float(ch["tyre_temp_fl"].min()) < 110.0  # sent in degF, stored in degC
    assert abs(ch["g_lat"]).max() > 1.5 and ch["g_lon"].min() < -1.0


@pytest.mark.synthetic
def test_replay_with_stale_last_lap_still_times_laps() -> None:
    sc = ForzaScenario(
        flying_laps=3,
        last_lap_delay_packets=3,
        driver_by_lap={3: DriverProfile(deviations={"T1": CornerDeviation(brake_early_m=25)})},
    )
    out, laps, truth, a = _replay(sc)
    assert {lap.lap_number: lap.lap_time_ms for lap in laps} == {n: truth.lap_times_ms[n] for n in (2, 3, 4)}
    assert all(lap.clean for lap in laps)
    assert a.stats.by_type.get("last_lap_held", 0) >= 1 and "last_lap_timeout" not in a.stats.by_type
    frames = of(out, CarFrame)
    assert [f.t_recv_ns for f in frames] == sorted(f.t_recv_ns for f in frames)  # held frames keep their order


@pytest.mark.synthetic
def test_replay_with_rewind_flags_the_lap() -> None:
    out, laps, truth, a = _replay(ForzaScenario(flying_laps=3, rewind=RewindSpec(lap=3, at_fraction=0.5)))
    by_lap = {lap.lap_number: lap for lap in laps}
    assert LapFlag.FLASHBACK in by_lap[3].flags and not by_lap[3].clean
    assert LapFlag.INCOMPLETE not in by_lap[3].flags and by_lap[3].valid is None  # still analysed for coaching
    assert by_lap[2].clean and by_lap[4].clean
    assert [e.kind for e in of(out, GameEvent)].count(EventKind.FLASHBACK) == 1
    assert "teleport" not in a.stats.by_type  # the odometer rolled back with the car: distance stays aligned
    lengths = of(out, SessionInfo)[-1].extra["measured_lap_lengths_m"]
    assert lengths == [pytest.approx(truth.lap_length_m, abs=2.0)] * 2  # laps 2 and 4: the rewound lap is no sample


@pytest.mark.synthetic
def test_replay_rewind_that_keeps_the_odometer_running() -> None:
    """Undocumented either way: if DistanceTraveled keeps counting through a rewind, the lap's distance no longer
    matches the track and its length would be ~5 % long - it must neither be analysed as aligned nor mint the
    circuit's permanent fingerprint."""
    sc = ForzaScenario(
        fmt=ForzaFormat.FM7_DASH,
        flying_laps=3,
        car_ordinal=4321,
        rewind=RewindSpec(lap=2, at_fraction=0.5, odometer_rolls_back=False),
    )
    out, laps, truth, a = _replay(sc)
    assert a.stats.by_type["rewind"] == 1 and a.stats.by_type["teleport"] == 1
    by_lap = {lap.lap_number: lap for lap in laps}
    assert by_lap[2].valid is False and not by_lap[2].clean
    assert by_lap[3].clean and by_lap[4].clean
    assert {n: by_lap[n].lap_time_ms for n in (3, 4)} == {n: truth.lap_times_ms[n] for n in (3, 4)}
    info = of(out, SessionInfo)[-1]
    assert info.extra["measured_lap_lengths_m"] == [pytest.approx(truth.lap_length_m, abs=2.0)] * 2
    assert info.track_id is not None
    fp = TrackFingerprint.parse(info.track_id)
    assert fp is not None and fp.length_m == pytest.approx(truth.lap_length_m, abs=1.0)


@pytest.mark.synthetic
def test_replay_shorter_driven_line_is_not_an_incomplete_lap() -> None:
    sc = ForzaScenario(flying_laps=3, lap_distance_scale={4: 0.982})  # 1.8 % tighter line: ~71 m on this circuit
    out, laps, truth, _ = _replay(sc)
    assert truth.lap_length_m - truth.driven_lengths_m[4] > 60.0  # beyond LapAssembler's absolute tolerance
    by_lap = {lap.lap_number: lap for lap in laps}
    assert all(by_lap[n].clean for n in (2, 3, 4))
    assert {n: by_lap[n].lap_time_ms for n in (2, 3, 4)} == {n: truth.lap_times_ms[n] for n in (2, 3, 4)}
    info = of(out, SessionInfo)[-1]
    assert info.track_length_m == pytest.approx(truth.driven_lengths_m[4], abs=2.0)
    assert info.extra["track_length_nominal_m"] == pytest.approx(truth.lap_length_m, abs=2.0)


@pytest.mark.synthetic
def test_replay_lap_far_shorter_than_the_others_is_still_incomplete() -> None:
    out, laps, truth, _ = _replay(ForzaScenario(flying_laps=3, lap_distance_scale={4: 0.95}))  # a 5 % cut
    by_lap = {lap.lap_number: lap for lap in laps}
    assert by_lap[2].clean and by_lap[3].clean and LapFlag.INCOMPLETE in by_lap[4].flags
    assert of(out, SessionInfo)[-1].track_length_m == pytest.approx(truth.lap_length_m, abs=2.0)


@pytest.mark.synthetic
def test_replay_ending_inside_the_hold_keeps_the_final_lap() -> None:
    sc = ForzaScenario(
        fmt=ForzaFormat.HORIZON_DASH,
        flying_laps=2,
        last_lap_delay_packets=4,
        cooldown_s=0.0,  # the finish-line packet is the last one sent
        # the final lap must differ from the one before, or its stale LastLap would pass the lap-clock check
        driver_by_lap={3: DriverProfile(deviations={"T3": CornerDeviation(brake_early_m=15)})},
    )
    packets, truth = generate_forza_session(sc)
    out, a = decode_all(packets)
    drained = a.drain()
    assert [(c.lap_number, c.lap_time_ms) for c in of(drained, LapCompletion)] == [(3, None)]
    laps = {lap.lap_number: lap for lap in assemble(out + drained, flush=True)}
    assert laps[2].lap_time_ms == truth.lap_times_ms[2] and laps[2].clean
    assert laps[3].lap_time_ms is None and LapFlag.INCOMPLETE not in laps[3].flags


@pytest.mark.synthetic
def test_replay_with_pause_keeps_the_lap_clean() -> None:
    probe = generate_forza_session(ForzaScenario(flying_laps=2))[1]
    pause_at = lap_fraction_time(probe, 2, 0.4)
    out, laps, truth, _ = _replay(ForzaScenario(flying_laps=2, pause=PauseSpec(at_race_time_s=pause_at)))
    assert truth.packets_race_off == 180
    paused = [f for f in of(out, CarFrame) if f.quality & FrameQuality.PAUSED]
    assert len(paused) == 180
    assert {lap.lap_number: (lap.lap_time_ms, lap.clean) for lap in laps} == {
        2: (truth.lap_times_ms[2], True),
        3: (truth.lap_times_ms[3], True),
    }


@pytest.mark.synthetic
def test_replay_final_lap_not_counted_by_the_game() -> None:
    sc = ForzaScenario(
        flying_laps=2,
        final_lap_counted=False,
        cooldown_s=8.0,
        menu_packets=30,
        # the final lap is only visible through LastLap changing, so it must differ from the previous lap
        driver_by_lap={3: DriverProfile(deviations={"T7": CornerDeviation(apex_speed_loss_kph=8)})},
    )
    out, laps, truth, a = _replay(sc)
    assert truth.lap_times_ms[3] != truth.lap_times_ms[2]
    assert {lap.lap_number: lap.lap_time_ms for lap in laps} == {2: truth.lap_times_ms[2], 3: truth.lap_times_ms[3]}
    assert a.stats.by_type["final_lap"] == 1
    tail = of(out, CarFrame)[-(8 * 60 + 30) :]
    assert all(f.quality & FrameQuality.NOT_RACING for f in tail)


@pytest.mark.synthetic
def test_replay_builds_a_track_model_from_derived_distance() -> None:
    _, laps, truth, _ = _replay(ForzaScenario(flying_laps=2))
    assert truth.track is not None
    length = truth.lap_length_m
    model = build_track_model(
        "forza_motorsport",
        "synthetic:forza",
        truth.track.name,
        length,
        [to_distance_domain(lap, length) for lap in laps],
    )
    assert len(model.corners) >= 5  # the synthetic circuit has 8 designed arcs (a chicane may merge)


@pytest.mark.synthetic
def test_sled_replay_has_frames_but_no_laps() -> None:
    out, laps, truth, _ = _replay(ForzaScenario(fmt=ForzaFormat.SLED, flying_laps=1))
    assert laps == [] and not of(out, LapCompletion)
    frames = of(out, CarFrame)
    assert len(frames) == truth.packets_race_on and all(f.speed_kph is not None for f in frames)


@pytest.mark.synthetic
def test_synthetic_capture_is_flagged(tmp_path: Path) -> None:
    path = tmp_path / "forza.pwcap"
    truth = write_forza_capture(path, ForzaScenario(fmt=ForzaFormat.HORIZON_DASH, flying_laps=1), name="unit")
    reader = CaptureReader(path)
    assert reader.meta.synthetic and reader.meta.game_hint == "forza_horizon"
    assert reader.meta.extra["forza_format"] == "horizon_dash"
    assert sum(1 for _ in reader) == truth.packets_race_on + truth.packets_race_off


def test_generator_rejects_a_session_starting_on_the_line() -> None:
    with pytest.raises(ValueError, match="outlap_fraction"):
        generate_forza_session(ForzaScenario(outlap_fraction=0.0))


@pytest.mark.synthetic
def test_full_pipeline_keeps_the_final_lap_when_the_stream_stops_in_the_hold(tmp_path: Path) -> None:
    """Capture -> router -> session manager -> lap processor -> SQLite (tmp dir, no sockets). Draining the adapter
    before the router ends the session is what ``PacketRouter.finish`` must do; it is spelled out here so the test
    holds before and after that integration (``drain()`` is idempotent)."""
    from pitwall.config import Settings
    from pitwall.core.runtime import Runtime
    from pitwall.core.session import SessionManager
    from pitwall.ingest.router import PacketRouter
    from pitwall.storage import repo

    cap = tmp_path / "forza.pwcap"
    sc = ForzaScenario(
        fmt=ForzaFormat.HORIZON_DASH,
        flying_laps=2,
        last_lap_delay_packets=4,
        cooldown_s=0.0,
        driver_by_lap={3: DriverProfile(deviations={"T3": CornerDeviation(brake_early_m=15)})},
    )
    truth = write_forza_capture(cap, sc, name="forza-final-lap")
    rt = Runtime(Settings(data_dir=tmp_path / "data", llm_enabled=False))
    try:
        sessions = SessionManager(
            rt.writer,
            rt.live,
            rt.worker,
            source="replay:forza.pwcap",
            synthetic=True,
            overrides={"scenario": "forza-final-lap"},
        )
        adapter = ForzaAdapter()
        router = PacketRouter([adapter], sessions, rt.live)
        for p in CaptureReader(cap):
            router.handle(p)
        for item in adapter.drain():
            sessions.handle(item)
        router.finish()
        rt.worker.join()
        rt.writer.flush()
        with rt.db.read() as c:
            sid = repo.latest_session_id(c)
            assert sid
            sess = repo.get_session(c, sid)
            laps = {lap["lap_number"]: lap for lap in repo.list_laps(c, sid)}
        assert sess is not None and sess["synthetic"] and sess["track_id"] == "synthetic:forza-final-lap"
        assert (laps[2]["lap_time_ms"], laps[2]["clean"]) == (truth.lap_times_ms[2], True)
        assert laps[3]["lap_time_ms"] is None and LapFlag.INCOMPLETE not in laps[3]["flags"]  # kept, analysed
        assert rt.worker.errors == 0 and rt.writer.errors == 0
    finally:
        rt.close()
