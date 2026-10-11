"""F1 packet layouts, spec conformance, version detection and validation."""

from __future__ import annotations

import struct

import pytest

from pitwall.adapters.base import PacketRejected
from pitwall.adapters.f1 import packets as P
from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.adapters.f1.spec_check import compare_struct, extract_structs, section
from pitwall.adapters.structdef import StructDef


@pytest.mark.parametrize("layout", list(P.LAYOUTS.values()), ids=lambda layout: str(layout.packet_format))
def test_computed_sizes_match_ea_published_sizes(layout: P.F1Layout) -> None:
    assert layout.sizes == layout.published_sizes


def test_header_is_29_bytes() -> None:
    assert P.HEADER.size == 29


def test_event_union_is_largest_member() -> None:
    for layout in P.LAYOUTS.values():
        assert max(d.size for d in layout.event_details.values()) == P.EVENT_DETAILS_SIZE


# ---------------------------------------------------------------- machine-checked conformance with EA's structs
SPEC_2025 = {
    "CarMotionData": P.CAR_MOTION,
    "MarshalZone": P.MARSHAL_ZONE,
    "WeatherForecastSample": P.WEATHER_FORECAST_SAMPLE,
    "LapData": P.LAP_DATA,
    "ParticipantData": P.PARTICIPANT,
    "CarSetupData": P.CAR_SETUP,
    "CarTelemetryData": P.CAR_TELEMETRY,
    "CarStatusData": P.CAR_STATUS,
    "FinalClassificationData": P.FINAL_CLASSIFICATION,
    "LobbyInfoData": P.LOBBY_INFO,
    "CarDamageData": P.CAR_DAMAGE,
    "LapHistoryData": P.LAP_HISTORY,
    "TyreStintHistoryData": P.TYRE_STINT_HISTORY,
    "TyreSetData": P.TYRE_SET,
    "PacketMotionExData": P.MOTION_EX,
    "TimeTrialDataSet": P.TIME_TRIAL_DATASET,
}
SPEC_2026 = {
    "CarMotionData": P.CAR_MOTION_2026,
    "ParticipantData": P.PARTICIPANT_2026,
    "CarTelemetryData": P.CAR_TELEMETRY_2026,
    "CarStatusData": P.CAR_STATUS_2026,
    "LobbyInfoData": P.LOBBY_INFO_2026,
    "TimeTrialDataSet": P.TIME_TRIAL_DATASET_2026,
    "CarTelemetry2Data": P.CAR_TELEMETRY_2,
}


def test_2025_structs_conform_to_ea_spec(spec_doc: str) -> None:
    structs = extract_structs(section(spec_doc, "## 4. Constants", "## 6."))
    assert compare_struct(P.HEADER, structs["PacketHeader"]) == []
    problems = {name: compare_struct(ours, structs[name]) for name, ours in SPEC_2025.items()}
    assert {k: v for k, v in problems.items() if v} == {}


def test_2026_structs_conform_to_ea_spec(spec_doc: str) -> None:
    structs = extract_structs(section(spec_doc, "### 7.3 Changed and new structs", "### 7.5"))
    problems = {name: compare_struct(ours, structs[name]) for name, ours in SPEC_2026.items()}
    assert {k: v for k, v in problems.items() if v} == {}
    # Session: our 2026 tail must list the spec's fields after numSessionsInWeekend, in order
    spec_session = [f.name for f in structs["PacketSessionData"]]
    tail_names = [n for n, _ in P.SESSION_TAIL_2026.fields]
    assert spec_session[-len(tail_names) :] == tail_names


def test_event_payloads_conform_to_ea_spec(spec_doc: str) -> None:
    import re

    names = {
        "FastestLap": "FTLP",
        "Retirement": "RTMT",
        "DRSDisabled": "DRSD",
        "TeamMateInPits": "TMPT",
        "RaceWinner": "RCWN",
        "Penalty": "PENA",
        "SpeedTrap": "SPTP",
        "StartLights": "STLG",
        "DriveThroughPenaltyServed": "DTSV",
        "StopGoPenaltyServed": "SGSV",
        "Flashback": "FLBK",
        "Buttons": "BUTN",
        "Overtake": "OVTK",
        "SafetyCar": "SCAR",
        "Collision": "COLL",
    }
    sec = section(spec_doc, "### 5.3 Event", "### 5.4")
    found = 0
    for m in re.finditer(r"struct\s*\{(.*?)\}\s*(\w+);", sec, re.S):
        body, nm = m.group(1), m.group(2)
        spec_fields = [f.group(2) for f in re.finditer(r"^\s*(\w+)\s+(\w+)\s*;", re.sub(r"//.*", "", body), re.M)]
        ours = [n for n, _ in P.EVENT_DETAILS[names[nm]].fields]
        assert ours == spec_fields, nm
        found += 1
    assert found == len(names)


# ---------------------------------------------------------------- structdef
def test_structdef_roundtrip_with_arrays_and_strings() -> None:
    sd = StructDef("T", [("a", "H"), ("b", "4f"), ("name", "8s"), ("c", "b")])
    raw = sd.pack({"a": 7, "b": [1.0, 2.0, 3.0, 4.0], "name": b"abc", "c": -3})
    assert len(raw) == sd.size == 2 + 16 + 8 + 1
    d = sd.unpack_from(raw)
    assert d["a"] == 7 and d["b"] == (1.0, 2.0, 3.0, 4.0) and d["name"].rstrip(b"\0") == b"abc" and d["c"] == -3


def test_structdef_rejects_wrong_array_length() -> None:
    sd = StructDef("T", [("b", "4f")])
    with pytest.raises(ValueError):
        sd.pack({"b": [1.0]})


# ---------------------------------------------------------------- validation / version detection
def _header(fmt: int, pid: int, player: int = 0, uid: int = 1) -> bytes:
    return P.HEADER.pack(
        {"packetFormat": fmt, "gameYear": 25, "packetId": pid, "sessionUID": uid, "playerCarIndex": player}
    )


def test_rejects_unsupported_format_with_actionable_message() -> None:
    a = F1Adapter()
    data = _header(2024, 6) + b"\0" * (1352 - 29)
    with pytest.raises(PacketRejected, match="UDP Format"):
        a.decode(data, 0)
    assert a.stats.rejected == 1


def test_rejects_wrong_size() -> None:
    a = F1Adapter()
    data = _header(2025, 6) + b"\0" * 100
    with pytest.raises(PacketRejected, match="size"):
        a.decode(data, 0)


def test_rejects_unknown_packet_id_and_short_packets() -> None:
    a = F1Adapter()
    with pytest.raises(PacketRejected):
        a.decode(_header(2025, 42) + b"\0" * 10, 0)
    with pytest.raises(PacketRejected):
        a.decode(b"\x01\x02", 0)
    with pytest.raises(PacketRejected, match="not defined in format 2025"):
        a.decode(_header(2025, 16) + b"\0" * (269 - 29), 0)  # Car Telemetry 2 exists only in 2026


def test_rejects_out_of_range_player_index() -> None:
    a = F1Adapter()
    with pytest.raises(PacketRejected, match="playerCarIndex"):
        a.decode(_header(2025, 6, player=30) + b"\0" * (1352 - 29), 0)


def test_can_decode_detects_both_formats_and_ignores_garbage() -> None:
    a = F1Adapter()
    assert a.can_decode(_header(2025, 6) + b"\0" * (1352 - 29))
    assert a.can_decode(_header(2026, 6) + b"\0" * (1448 - 29))
    assert not a.can_decode(_header(2026, 6) + b"\0" * (1352 - 29))  # 2025 size under a 2026 header
    assert not a.can_decode(b"\0" * 296)  # e.g. a GT7 packet
    assert not a.can_decode(b"")


def test_ignored_packet_types_are_counted_not_errors() -> None:
    a = F1Adapter()
    a.decode(_header(2025, int(P.PacketId.TYRE_SETS)) + b"\0" * (231 - 29), 0)
    assert a.stats.ignored == 1 and a.stats.errors == 0


def test_unknown_event_code_is_tolerated() -> None:
    a = F1Adapter()
    data = _header(2025, int(P.PacketId.EVENT)) + b"ZZZZ" + b"\0" * 12
    out = a.decode(data, 0)
    assert out and out[0].code == "ZZZZ" and a.stats.errors == 0


def test_struct_alignment_is_packed_little_endian() -> None:
    # uint16 speed=300 then float throttle=0.5 must sit at offsets 0 and 2 (no padding)
    raw = P.CAR_TELEMETRY.pack({"speed": 300, "throttle": 0.5})
    assert struct.unpack_from("<H", raw, 0)[0] == 300
    assert struct.unpack_from("<f", raw, 2)[0] == 0.5


# ---------------------------------------------------------------- appendix 8.1: team ids
def _spec_teams(spec_doc: str) -> dict[int, str]:
    """Every team id the spec lists: the three-column table plus the "2026 doc v1.2 only" line, with the
    "*(2026)*" / "*(2026 doc)*" provenance notes removed."""
    import re

    text = section(spec_doc, "### 8.1 Team IDs", "### 8.2")
    out: dict[int, str] = {}
    for line in text.splitlines():
        if not line.startswith("|") or "---" in line or "ID | Team" in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        for tid, name in zip(cells[0::2], cells[1::2], strict=True):
            if tid:
                out[int(tid)] = re.sub(r"\s*\*\([^)]*\)\*$", "", name)
    extra = re.search(r"2026 doc v1\.2 only[^:]*:\s*(.+?)\.\n", text)
    assert extra is not None
    for item in extra.group(1).split(", "):
        tid, name = item.split(" ", 1)
        out[int(tid)] = name
    return out


def test_team_names_match_the_spec_appendix(spec_doc: str) -> None:
    from pitwall.adapters.f1 import enums

    spec = _spec_teams(spec_doc)
    assert len(spec) >= 70 and spec[0] == "Mercedes" and spec[167] == "Van Amersfoort Racing '24"
    assert spec == enums.TEAMS  # every listed id, named exactly as the spec names it, and nothing invented
    assert enums.team_name(214) == "Unknown team (id 214)"  # the F2 car in the README screenshots: not in the spec
    assert enums.team_name(8) == "McLaren" and enums.team_name(162) == "DAMS '24"


def test_session_car_name_comes_from_the_team_table() -> None:
    """Synthetic packets, only to exercise the id -> name mapping (no game-compatibility claim)."""
    from pitwall.sim.f1_stream import F1Scenario, generate_f1_session
    from tests.conftest import decode_session

    for tid, expected in ((165, "Prema '24"), (214, "Unknown team (id 214)")):
        packets, _truth = generate_f1_session(F1Scenario(laps=1, team_id=tid))
        _laps, _frames, info, _adapter = decode_session(packets)
        assert (info.car_id, info.car_name) == (f"f1:team:{tid}", expected)
