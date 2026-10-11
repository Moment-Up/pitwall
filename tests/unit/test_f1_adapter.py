"""Normalisation, unit conversions, session state and lap boundaries in the F1 adapter."""

from __future__ import annotations

import re
import struct
from typing import Any

import pytest

from pitwall.adapters.f1 import packets as P
from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.adapters.f1.spec_check import compare_struct, extract_structs, section
from pitwall.adapters.structdef import StructDef
from pitwall.analysis.track_skeleton import TIER_SYNTHETIC, build_track_skeleton
from pitwall.model.telemetry import (
    CarFrame,
    EventKind,
    FrameQuality,
    GameEvent,
    LapCompletion,
    MarshalZone,
    SessionInfo,
    TrackZones,
    Wheels,
)
from pitwall.sim.f1_stream import F1Scenario, _hdr
from tests.conftest import DecodedSession


def test_wheel_order_is_normalised_from_rl_rr_fl_fr() -> None:
    w = Wheels.from_rl_rr_fl_fr([1, 2, 3, 4])
    assert (w.fl, w.fr, w.rl, w.rr) == (3, 4, 1, 2)


def _telemetry_packet(sc: F1Scenario, values: dict[str, object], player: int = 0) -> bytes:
    L = sc.layout
    cars = [L.car_telemetry.pack({}) for _ in range(L.max_cars)]
    cars[player] = L.car_telemetry.pack(values)
    hdr = P.HEADER.pack(
        {
            "packetFormat": sc.packet_format,
            "packetId": 6,
            "sessionUID": 9,
            "playerCarIndex": player,
            "frameIdentifier": 1,
        }
    )
    return hdr + b"".join(cars) + P.CAR_TELEMETRY_TAIL.pack({})


@pytest.mark.parametrize("fmt", [2025, 2026])
def test_telemetry_units_and_ranges(fmt: int) -> None:
    sc = F1Scenario(packet_format=fmt)
    data = _telemetry_packet(
        sc,
        {
            "speed": 287,
            "throttle": 0.75,
            "steer": -0.4,
            "brake": 0.2,
            "clutch": 50,
            "gear": -1,
            "engineRPM": 11000,
            "tyresSurfaceTemperature": [80, 81, 90, 91],  # RL RR FL FR
            "tyresPressure": [21.0, 21.5, 23.0, 23.5],
            "brakesTemperature": [500, 510, 600, 610],
        },
        player=5,
    )
    (f,) = F1Adapter().decode(data, 123)
    assert isinstance(f, CarFrame)
    assert f.speed_kph == 287 and f.throttle == pytest.approx(0.75) and f.brake == pytest.approx(0.2)
    assert f.steering == pytest.approx(-0.4) and f.clutch == pytest.approx(0.5) and f.gear == -1
    assert f.tyre_surface_temp_c == Wheels(fl=90.0, fr=91.0, rl=80.0, rr=81.0)
    assert f.tyre_pressure_psi is not None and f.tyre_pressure_psi.fl == pytest.approx(23.0)
    assert f.brake_temp_c is not None and f.brake_temp_c.fr == 610
    # nothing else was received yet: unknown must stay unknown (never fabricated)
    assert f.pos_x_m is None and f.lap_number is None and f.fuel_kg is None and f.tyre_wear_pct is None


def test_gforce_quantisation_2026(demo_session: DecodedSession, demo_session_2026: DecodedSession) -> None:
    a = demo_session.frames[4000]
    b = demo_session_2026.frames[4000]
    assert b.g_lat == pytest.approx(a.g_lat, abs=0.001)
    assert b.g_lon == pytest.approx(a.g_lon, abs=0.001)


def test_frames_merge_motion_lap_status_damage(demo_session: DecodedSession) -> None:
    f = demo_session.frames[3000]
    assert f.pos_x_m is not None and f.lap_distance_m is not None and f.fuel_kg is not None
    assert f.tyre_wear_pct is not None and f.tyre_compound == "soft"
    assert f.quality == FrameQuality.OK


def test_lap_completions_carry_official_times_and_sectors(clean_session: DecodedSession) -> None:
    times = clean_session.truth.lap_times_ms
    laps = {lap.lap_number: lap for lap in clean_session.laps}
    for n, ms in times.items():
        assert laps[n].lap_time_ms == ms
        s = laps[n].sector_times_ms
        assert len(s) == 3 and all(s) and sum(s) == ms  # type: ignore[arg-type]


def test_session_info_normalisation(demo_session: DecodedSession) -> None:
    info = demo_session.info
    assert isinstance(info, SessionInfo)
    assert info.track_id == "f1:-1" and info.track_name == "Unknown track"
    assert info.session_type.value == "practice" and info.session_type_raw == "Practice 1"
    assert info.car_name == "McLaren" and info.weather.condition == "clear" and info.weather.track_temp_c == 32
    assert info.track_length_m == pytest.approx(demo_session.truth.track.length_m, abs=1)  # type: ignore[union-attr]


def test_flashback_event_decoded() -> None:
    sc = F1Scenario()
    details = P.EVENT_DETAILS["FLBK"].pack({"flashbackFrameIdentifier": 1200, "flashbackSessionTime": 41.5})
    data = _hdr(P.PacketId.EVENT, sc, 45.0, 1500, 1500) + b"FLBK" + details.ljust(12, b"\0")
    (e,) = F1Adapter().decode(data, 0)
    assert isinstance(e, GameEvent) and e.kind == EventKind.FLASHBACK
    assert e.payload["flashbackFrameIdentifier"] == 1200 and e.payload["flashbackSessionTime"] == pytest.approx(41.5)


def test_new_session_uid_resets_cached_state(demo_session: DecodedSession) -> None:
    a = F1Adapter()
    for p in demo_session.packets[:400]:
        a.decode(p.data, p.t_recv_ns)
    assert a._lap is not None
    sc = F1Scenario(session_uid=0xABCDEF)
    data = _telemetry_packet(sc, {"speed": 100})
    data = data[:7] + (0xABCDEF).to_bytes(8, "little") + data[15:]
    (f,) = a.decode(data, 0)
    assert isinstance(f, CarFrame) and f.lap_number is None  # nothing leaked from the previous session


def test_session_uid_zero_does_not_reset(demo_session: DecodedSession) -> None:
    a = F1Adapter()
    for p in demo_session.packets[:400]:
        a.decode(p.data, p.t_recv_ns)
    data = _telemetry_packet(F1Scenario(session_uid=0), {"speed": 100})
    data = data[:7] + (0).to_bytes(8, "little") + data[15:]
    (f,) = a.decode(data, 0)
    assert isinstance(f, CarFrame) and f.lap_number is not None


def test_invalid_lap_is_reported_invalid(demo_session: DecodedSession) -> None:
    lap7 = next(lap for lap in demo_session.laps if lap.lap_number == 7)
    assert lap7.valid is False and "invalid" in lap7.flags and not lap7.clean


def test_all_demo_packets_decode_without_errors(
    demo_session: DecodedSession, demo_session_2026: DecodedSession
) -> None:
    for s in (demo_session, demo_session_2026):
        st = s.adapter.stats
        assert st.rejected == 0 and st.errors == 0 and st.decoded == st.packets
        completions = [lap for lap in s.laps if lap.lap_time_ms is not None]
        assert len(completions) == 7


def test_lap_completion_object() -> None:
    c = LapCompletion(game=F1Adapter().info.game, t_recv_ns=0, lap_number=1, lap_time_ms=90000)
    assert c.lap_number == 1


# ================================================================ track skeleton (L0a) from the Session packet
# Offsets and sub-struct layouts are machine-checked against the offset tables in docs/research/f1-udp-spec.md, and
# the decoder is fed Session bytes written at the *spec's* offsets (not via our StructDefs), so a wrong StructDef can
# never be hidden by an encoder sharing the same mistake.
_ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*`([\w\[\]]+)`\s*\|\s*`m_(\w+)`\s*\|", re.M)
_CODE = {"uint8": "B", "int8": "b", "uint16": "H", "uint32": "I", "uint64": "Q", "float": "f"}
_SESSION_TABLES = {
    2025: ("`PacketSessionData` offsets (absolute, header included)", "Sub-struct Python: MarshalZone"),
    2026: ("Full offsets (format 2026)", "Python: ActiveAeroZone"),
}


def _spec_table(text: str) -> dict[str, tuple[int, int, str]]:
    """``{field: (offset, size, C type)}`` from one of the spec's offset tables."""
    return {m.group(4): (int(m.group(1)), int(m.group(2)), m.group(3)) for m in _ROW.finditer(text)}


def _spec_session_table(spec_doc: str, fmt: int) -> dict[str, tuple[int, int, str]]:
    return _spec_table(section(spec_doc, *_SESSION_TABLES[fmt]))


def _field_sizes(sd: StructDef) -> list[tuple[str, int]]:
    return [(name, struct.calcsize("<" + f)) for name, f in sd.fields]


def _our_session_rows(layout: P.F1Layout) -> list[tuple[int, int, str]]:
    """Our Session layout as (offset, size, spec field name) rows, sub-struct arrays as single rows like the spec."""
    rows = [(0, P.HEADER.size, "header")]
    off = P.SESSION_HEAD_OFFSET

    def add(name: str, size: int) -> None:
        nonlocal off
        rows.append((off, size, name))
        off += size

    for name, size in _field_sizes(P.SESSION_HEAD):
        add(name, size)
    assert off == P.SESSION_MARSHAL_ZONES_OFFSET
    add("marshalZones", P.NUM_MARSHAL_ZONES * P.MARSHAL_ZONE.size)
    assert off == P.SESSION_MID_OFFSET
    for name, size in _field_sizes(P.SESSION_MID):
        add(name, size)
    assert off == P.SESSION_FORECAST_OFFSET
    add("weatherForecastSamples", P.NUM_WEATHER_SAMPLES * P.WEATHER_FORECAST_SAMPLE.size)
    assert off == P.SESSION_TAIL_OFFSET
    for name, size in _field_sizes(layout.session_tail):
        add(name, size)
    assert off == layout.sizes[P.PacketId.SESSION]
    return rows


@pytest.mark.parametrize("fmt", [2025, 2026])
def test_session_offsets_match_spec_offset_table(spec_doc: str, fmt: int) -> None:
    spec = _spec_session_table(spec_doc, fmt)
    ours = _our_session_rows(P.LAYOUTS[fmt])
    assert [(o, s, n) for o, s, n in ours] == [(o, s, n) for n, (o, s, _t) in spec.items()]
    assert spec["marshalZones"][0] == P.SESSION_MARSHAL_ZONES_OFFSET == 48
    assert spec["sector2LapDistanceStart"][0] == 745 and spec["sector3LapDistanceStart"][0] == 749


def test_2026_zone_structs_and_constants_match_spec(spec_doc: str) -> None:
    sec = section(spec_doc, "### 7.3 Changed and new structs", "### 7.5")
    structs = extract_structs(sec)
    assert compare_struct(P.ACTIVE_AERO_ZONE, structs["ActiveAeroZone"]) == []
    assert compare_struct(P.DRS_ZONE, structs["DRSZone"]) == []
    consts = {m.group(1): int(m.group(2)) for m in re.finditer(r"cs_(\w+)\s*=\s*(\d+);", sec)}
    assert consts["maxMarshalZonesPerLap"] == P.NUM_MARSHAL_ZONES
    assert consts["maxActiveAeroZonesPerLap"] == P.NUM_ACTIVE_AERO_ZONES
    assert consts["maxDRSZonesPerLap"] == P.NUM_DRS_ZONES
    # the 2026 tail flattens ActiveAeroZone[8] / DRSZone[4]; element struct x count must equal the flat field
    tail = dict(_field_sizes(P.SESSION_TAIL_2026))
    assert tail["activeAeroZonesFull"] == tail["activeAeroZonesPartial"] == 8 * P.ACTIVE_AERO_ZONE.size
    assert tail["drsZones"] == P.NUM_DRS_ZONES * P.DRS_ZONE.size


def _spec_session_packet(spec_doc: str, fmt: int, fields: dict[str, Any]) -> bytes:
    """A Session packet written field-by-field at the spec's offsets. Zone arrays take lists of tuples:
    marshal zones ``(zoneStart, zoneFlag)`` as ``<fb``, aero/DRS zones ``(zoneStart, zoneEnd)`` as ``<ff``."""
    hdr = _spec_table(section(spec_doc, "### 4.2 PacketHeader", "### 5."))
    body = _spec_session_table(spec_doc, fmt)
    buf = bytearray(max(o + s for o, s, _ in body.values()))
    header_vals = {"packetFormat": fmt, "gameYear": 25, "packetVersion": 1, "packetId": 1, "sessionUID": 77}
    for name, value in header_vals.items():
        o, _s, ctype = hdr[name]
        struct.pack_into("<" + _CODE[ctype], buf, o, value)
    arrays = {"marshalZones": "<fb", "activeAeroZonesFull": "<ff", "activeAeroZonesPartial": "<ff", "drsZones": "<ff"}
    for name, value in fields.items():
        o, size, ctype = body[name]
        if name in arrays:
            elem = struct.Struct(arrays[name])
            assert len(value) * elem.size <= size
            for i, item in enumerate(value):
                elem.pack_into(buf, o + i * elem.size, *item)
        else:
            struct.pack_into("<" + _CODE[ctype], buf, o, value)
    assert len(buf) == P.LAYOUTS[fmt].sizes[P.PacketId.SESSION]
    return bytes(buf)


def _decode_info(data: bytes) -> SessionInfo:
    (info,) = F1Adapter().decode(data, 0)
    assert isinstance(info, SessionInfo)
    return info


_COMMON = {
    "trackLength": 4323,
    "pitSpeedLimit": 80,
    "trackId": 17,
    "sessionType": 15,
    # 3 meaningful zones in game order (zone 0 wraps the line), plus a stale 4th entry the count excludes
    "numMarshalZones": 3,
    "marshalZones": [(0.99083, 0), (0.07919, 3), (0.5, -1), (0.7, 1)],
    "sector2LapDistanceStart": 1203.962,
    "sector3LapDistanceStart": 2934.932,
}


def test_format_2025_session_skeleton_decoded_from_spec_bytes(spec_doc: str) -> None:
    info = _decode_info(_spec_session_packet(spec_doc, 2025, _COMMON))
    z = info.track_zones
    assert z is not None and z.source == "f1_session@2025"
    assert info.track_length_m == 4323 and info.pit_speed_limit_kph == 80
    assert z.sector2_start_m == pytest.approx(1203.962, abs=1e-3)
    assert z.sector3_start_m == pytest.approx(2934.932, abs=1e-3)
    assert z.marshal_zones is not None
    got = [(round(m.start_frac, 5), m.flag) for m in z.marshal_zones]
    assert got == [(0.99083, "none"), (0.07919, "yellow"), (0.5, None)]  # count respected; flag -1 -> unknown
    # format 2025 has no DRS / active-aero tables: unknown, never an empty list
    assert z.drs_zones_frac is None and z.aero_full_zones_frac is None and z.aero_partial_zones_frac is None
    assert z.active_aero_track_status is None
    # backward-compatible extra keys stay for this release
    assert info.extra["sector2_start_m"] == pytest.approx(1203.962, abs=1e-3)
    assert info.extra["sector3_start_m"] == pytest.approx(2934.932, abs=1e-3)
    sk = build_track_skeleton(info)
    assert sk.marshal_zones is not None and sk.marshal_zones[-1].index == 0 and sk.marshal_zones[-1].wraps
    s2 = z.sector2_start_m
    assert s2 is not None and sk.sector_of(s2) == 1 and sk.sector_of(s2 - 0.01) == 0  # float32 boundary
    assert sk.drs_zones is None


def test_format_2026_session_skeleton_decoded_from_spec_bytes(spec_doc: str) -> None:
    fields = {
        **_COMMON,
        "activeAeroTrackStatus": 1,
        "numActiveAeroZonesFull": 2,
        "activeAeroZonesFull": [(0.95, 0.1), (0.4, 0.45), (0.6, 0.65)],  # third entry beyond the count
        "numActiveAeroZonesPartial": 1,
        "activeAeroZonesPartial": [(0.96, 0.08)],
        "numDRSZones": 1,
        "drsZones": [(0.95, 0.1), (0.3, 0.35)],
        "startReactionTime": 0.25,  # neighbour after the DRS array: catches an overlong decode
    }
    info = _decode_info(_spec_session_packet(spec_doc, 2026, fields))
    z = info.track_zones
    assert z is not None and z.source == "f1_session@2026"
    assert z.marshal_zones is not None and len(z.marshal_zones) == 3
    assert z.sector3_start_m == pytest.approx(2934.932, abs=1e-3)
    assert z.active_aero_track_status == "partial"

    def r(zs: tuple[tuple[float, float], ...] | None) -> list[tuple[float, float]]:
        return [(round(a, 5), round(b, 5)) for a, b in zs or ()]

    assert r(z.aero_full_zones_frac) == [(0.95, 0.1), (0.4, 0.45)]
    assert r(z.aero_partial_zones_frac) == [(0.96, 0.08)]
    assert r(z.drs_zones_frac) == [(0.95, 0.1)]
    sk = build_track_skeleton(info)
    assert sk.drs_zones is not None and sk.drs_zones[0].wraps and sk.drs_zone_at(0.0) is sk.drs_zones[0]


def test_session_zone_counts_are_clamped_and_zero_counts_handled(spec_doc: str) -> None:
    fields = {
        **_COMMON,
        "numMarshalZones": 0,  # real F1 25 sends 0 before the session clock starts: unknown, not "no zones"
        "numDRSZones": 9,  # corrupt count beyond cs_maxDRSZonesPerLap: clamp to the array
        "drsZones": [(0.1, 0.2), (0.3, 0.4), (0.5, 0.6), (0.7, 0.8)],
        "numActiveAeroZonesFull": 0,
    }
    z = _decode_info(_spec_session_packet(spec_doc, 2026, fields)).track_zones
    assert z is not None and z.marshal_zones is None
    assert z.drs_zones_frac is not None and len(z.drs_zones_frac) == P.NUM_DRS_ZONES
    assert z.aero_full_zones_frac == () and z.aero_partial_zones_frac == ()  # 2026 reported zero zones


def test_unpopulated_sector_starts_are_unknown(spec_doc: str) -> None:
    fields = {**_COMMON, "sector2LapDistanceStart": 0.0, "sector3LapDistanceStart": -1.0}
    z = _decode_info(_spec_session_packet(spec_doc, 2025, fields)).track_zones
    assert z is not None and z.sector2_start_m is None and z.sector3_start_m is None


@pytest.mark.synthetic
@pytest.mark.parametrize("fixture", ["demo_session", "demo_session_2026"])
def test_synthetic_skeleton_round_trips_and_matches_lap_data_sectors(
    fixture: str, request: pytest.FixtureRequest
) -> None:
    s: DecodedSession = request.getfixturevalue(fixture)
    got, truth = s.info.track_zones, s.truth.track_zones
    assert got is not None and truth is not None and got.source == truth.source
    assert [m.flag for m in got.marshal_zones or ()] == [m.flag for m in truth.marshal_zones or ()]
    assert [m.start_frac for m in got.marshal_zones or ()] == pytest.approx(
        [m.start_frac for m in truth.marshal_zones or ()], abs=1e-6
    )
    for name in ("drs_zones_frac", "aero_full_zones_frac", "aero_partial_zones_frac"):
        g, t = getattr(got, name), getattr(truth, name)
        assert (g is None) == (t is None), name
        assert [v for p in g or () for v in p] == pytest.approx([v for p in t or () for v in p], abs=1e-6), name
    sk = build_track_skeleton(s.info)
    # generated zones are never labelled game data: the generator's session UID alone tiers them synthetic
    assert sk.tier == TIER_SYNTHETIC and sk.to_dict()["synthetic"] is True
    assert sk.marshal_zones is not None and sk.marshal_zones[-1].wraps  # zone 0 starts just before the line
    if s.info.track_zones and s.info.track_zones.drs_zones_frac is not None:
        assert sk.drs_zones is not None and any(z.wraps for z in sk.drs_zones)  # main-straight zone crosses the line
    frames = [f for f in s.frames if f.sector is not None and f.lap_distance_m is not None]
    assert frames and all(sk.sector_of(f.lap_distance_m) == f.sector for f in frames)


def test_marshal_zone_model_defaults() -> None:
    assert MarshalZone(0.5).flag is None and TrackZones().marshal_zones is None
