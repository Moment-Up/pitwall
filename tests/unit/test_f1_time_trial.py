"""F1 25 Time Trial (packet 14) and LapData's time trial car indexes: decoded exactly per EA's spec (leaderboard).

Packets here are written field by field at the *spec's* offsets (docs/research/f1-udp-spec.md: the 2025 offset table of
section 5.14, its "Layout:" line, the 2026 Python format of section 7.3, LapData's stated tail offsets), never through
our ``StructDef``s, so a wrong definition cannot be hidden by an encoder sharing the mistake. Spec-decoded only: no
recorded Time Trial capture exists yet; the synthetic stream tests at the end are SYNTHETIC.
"""

from __future__ import annotations

import re
import struct
from typing import Any

import numpy as np
import pytest

from pitwall.adapters.base import SupportLevel
from pitwall.adapters.f1 import packets as P
from pitwall.adapters.f1.adapter import (
    _FOLLOWERS,
    _HANDLERS,
    F1_25_INFO,
    LAP_DATA_TAIL_OFFSET,
    F1Adapter,
    decode_time_trial_sets,
)
from pitwall.adapters.f1.spec_check import section
from pitwall.model.telemetry import SessionInfo, SessionType, TimeTrialDataSet, TimeTrialInfo
from pitwall.sim.f1_stream import F1Scenario, generate_f1_session, time_trial_session_best
from pitwall.sim.scenarios import TT_DEMO_PERSONAL_BEST, TT_DEMO_RIVAL, TT_DEMO_RIVAL_INDEX, time_trial_demo

_ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*`([\w\[\]]+)`\s*\|\s*`m_(\w+)`\s*\|", re.M)
_CODE = {"uint8": "B", "int8": "b", "uint16": "H", "uint32": "I", "uint": "I", "uint64": "Q", "float": "f"}
UID = 4242


def _table(text: str) -> dict[str, tuple[int, int, str]]:
    return {m.group(4): (int(m.group(1)), int(m.group(2)), m.group(3)) for m in _ROW.finditer(text)}


def _tt_section(spec_doc: str) -> str:
    return section(spec_doc, "### 5.14 Time Trial", "### 5.15")


def _set_starts(spec_doc: str) -> tuple[list[int], int]:
    m = re.search(
        r"player session best at (\d+), personal best at (\d+), rival at (\d+) \(each (\d+) bytes\)",
        _tt_section(spec_doc),
    )
    assert m is not None
    return [int(m.group(i)) for i in (1, 2, 3)], int(m.group(4))


def _spec_header(spec_doc: str, buf: bytearray, fmt: int, pid: int, uid: int = UID, player: int = 0) -> None:
    hdr = _table(section(spec_doc, "### 4.2 PacketHeader", "### 5."))
    values = {"packetFormat": fmt, "gameYear": 25, "packetId": pid, "sessionUID": uid, "playerCarIndex": player}
    for name, value in values.items():
        o, _s, ctype = hdr[name]
        struct.pack_into("<" + _CODE[ctype], buf, o, value)


def _spec_python_2026(spec_doc: str) -> struct.Struct:
    m = re.search(r"TimeTrialDataSet `(<[A-Za-z0-9]+)` \(calcsize = (\d+)\)", spec_doc)
    assert m is not None
    st = struct.Struct(m.group(1))
    assert st.size == int(m.group(2)) == 25
    return st


# spec field order of a TimeTrialDataSet (both formats; only m_teamId's width changes in 2026)
_ORDER = (
    "carIdx",
    "teamId",
    "lapTimeInMS",
    "sector1TimeInMS",
    "sector2TimeInMS",
    "sector3TimeInMS",
    "tractionControl",
    "gearboxAssist",
    "antiLockBrakes",
    "equalCarPerformance",
    "customSetup",
    "valid",
)
RIVAL = {
    "carIdx": 1,
    "teamId": 3,
    "lapTimeInMS": 64_215,
    "sector1TimeInMS": 16_012,
    "sector2TimeInMS": 28_004,
    "sector3TimeInMS": 20_199,
    "tractionControl": 0,
    "gearboxAssist": 0,
    "antiLockBrakes": 1,
    "equalCarPerformance": 1,
    "customSetup": 1,
    "valid": 1,
}
BEST = {**RIVAL, "carIdx": 0, "teamId": 8, "lapTimeInMS": 66_100, "antiLockBrakes": 0, "customSetup": 0}
PB = {**BEST, "lapTimeInMS": 65_480, "sector1TimeInMS": 16_300}


def spec_tt_packet(spec_doc: str, fmt: int, sets: list[dict[str, int] | None], uid: int = UID) -> bytes:
    """A Time Trial packet written at the spec's offsets (2025: the offset table + "Layout:" line; 2026: the spec's
    Python format, sets back to back after the header as ``PacketTimeTrialData`` declares them)."""
    if fmt == 2025:
        starts, each = _set_starts(spec_doc)
        table = _table(_tt_section(spec_doc))
        buf = bytearray(P.HEADER.size + 3 * each)
        for start, values in zip(starts, sets, strict=True):
            for name, v in (values or {}).items():
                o, _size, ctype = table[name]
                struct.pack_into("<" + _CODE[ctype], buf, start + o, v)
    else:
        st = _spec_python_2026(spec_doc)
        buf = bytearray(P.HEADER.size + 3 * st.size)
        for k, values in enumerate(sets):
            if values is not None:
                st.pack_into(buf, P.HEADER.size + k * st.size, *(values[n] for n in _ORDER))
    _spec_header(spec_doc, buf, fmt, int(P.PacketId.TIME_TRIAL), uid)
    return bytes(buf)


def spec_lap_data_tail(spec_doc: str, fmt: int, pb: int, rival: int, uid: int = UID) -> bytes:
    """A LapData packet that is zero but for the two time trial bytes, at the spec's stated offsets (2025: "at 1283 /
    1284"; 2026: the last two bytes of the 29 + 24 x 57 + 2 packet)."""
    if fmt == 2025:
        m = re.search(r"`m_timeTrialPBCarIdx` at (\d+), `m_timeTrialRivalCarIdx` at (\d+)", spec_doc)
        assert m is not None
        pb_at, rival_at = int(m.group(1)), int(m.group(2))
        size = P.SPEC_PUBLISHED_SIZES[P.PacketId.LAP_DATA]
    else:
        size = P.LAYOUT_2026.published_sizes[P.PacketId.LAP_DATA]
        pb_at, rival_at = size - 2, size - 1
    buf = bytearray(size)
    buf[pb_at], buf[rival_at] = pb, rival
    _spec_header(spec_doc, buf, fmt, int(P.PacketId.LAP_DATA), uid)
    return bytes(buf)


def _adapter() -> F1Adapter:
    return F1Adapter(field_hz=0, timing_hz=0)  # no field samples or race timing: only what these tests look at


def _decode(a: F1Adapter, data: bytes) -> list[Any]:
    return a.decode(data, 1_000)


# ---------------------------------------------------------------- layout checks against the spec
def test_packet_14_set_offsets_and_lap_data_tail_match_the_spec(spec_doc: str) -> None:
    starts, each = _set_starts(spec_doc)
    assert each == P.TIME_TRIAL_DATASET.size == 24 and P.TIME_TRIAL_DATASET_2026.size == 25
    assert starts == [P.HEADER.size + k * P.TIME_TRIAL_DATASET.size for k in range(3)] == [29, 53, 77]
    assert _spec_python_2026(spec_doc).size == P.TIME_TRIAL_DATASET_2026.size
    table = _table(_tt_section(spec_doc))
    assert list(table) == list(_ORDER) == [n for n, _ in P.TIME_TRIAL_DATASET.fields]
    m = re.search(r"`m_timeTrialPBCarIdx` at (\d+), `m_timeTrialRivalCarIdx` at (\d+)", spec_doc)
    assert m is not None and (int(m.group(1)), int(m.group(2))) == (1283, 1284)
    assert LAP_DATA_TAIL_OFFSET[2025] == 1283
    assert LAP_DATA_TAIL_OFFSET[2026] == P.LAYOUT_2026.published_sizes[P.PacketId.LAP_DATA] - 2 == 1397


def test_packet_14_has_a_handler_and_follows_the_session() -> None:
    assert P.PacketId.TIME_TRIAL in _HANDLERS and P.PacketId.TIME_TRIAL in _FOLLOWERS
    support = F1_25_INFO.fields["time_trial"]
    assert support.level is SupportLevel.SPEC_IMPLEMENTED and "not yet seen in a recording" in support.source


# ---------------------------------------------------------------- decoding
@pytest.mark.parametrize("fmt", [2025, 2026])
def test_time_trial_packet_decodes_every_field_and_the_car_indexes(spec_doc: str, fmt: int) -> None:
    a = _adapter()
    assert _decode(a, spec_lap_data_tail(spec_doc, fmt, pb=255, rival=1)) == []  # starts the session, emits nothing
    (tt,) = _decode(a, spec_tt_packet(spec_doc, fmt, [BEST, PB, RIVAL]))
    assert isinstance(tt, TimeTrialInfo)
    assert (tt.session_uid, tt.packet_format, tt.pb_car_index, tt.rival_car_index) == (str(UID), fmt, None, 1)
    assert tt.rival == TimeTrialDataSet(
        car_index=1,
        team_id=3,
        car_id="f1:team:3",
        car_name="Williams",
        lap_time_ms=64_215,
        sector_times_ms=(16_012, 28_004, 20_199),
        traction_control=False,
        gearbox_assist=False,
        anti_lock_brakes=True,
        equal_car_performance=True,
        custom_setup=True,
        valid=True,
    )
    assert tt.player_session_best is not None and tt.player_session_best.lap_time_ms == 66_100
    assert tt.player_session_best.car_id == "f1:team:8" and tt.player_session_best.car_index == 0
    assert tt.personal_best is not None and tt.personal_best.sector_times_ms[0] == 16_300
    assert a.stats.errors == 0 and a.stats.rejected == 0


@pytest.mark.parametrize("fmt", [2025, 2026])
def test_unknown_stays_unknown(spec_doc: str, fmt: int) -> None:
    """A set with no lap is None (its zero team would read "Mercedes"); flags other than 0/1, team 255 / 65535, car
    index 255 and zero sectors are None; LapData's 255 is no car."""
    odd = {**RIVAL, "tractionControl": 2, "valid": 7, "carIdx": 255, "teamId": 65535 if fmt == 2026 else 255}
    odd |= {"sector2TimeInMS": 0}
    a = _adapter()
    _decode(a, spec_lap_data_tail(spec_doc, fmt, pb=255, rival=255))
    (tt,) = _decode(a, spec_tt_packet(spec_doc, fmt, [None, None, odd]))
    assert tt.player_session_best is None and tt.personal_best is None
    r = tt.rival
    assert r is not None and r.lap_time_ms == 64_215
    assert (r.traction_control, r.valid, r.anti_lock_brakes) == (None, None, True)
    assert (r.car_index, r.team_id, r.car_id, r.car_name) == (None, None, None, None)
    assert r.sector_times_ms == (16_012, None, 20_199)
    assert (tt.pb_car_index, tt.rival_car_index) == (None, None)


def test_car_indexes_are_unknown_before_the_first_lap_data_and_past_the_array(spec_doc: str) -> None:
    a = _adapter()
    a.decode(P.HEADER.pack({"packetFormat": 2025, "packetId": 6, "sessionUID": UID}) + b"\0" * (1352 - 29), 0)
    (tt,) = _decode(a, spec_tt_packet(spec_doc, 2025, [None, None, RIVAL]))
    assert (tt.pb_car_index, tt.rival_car_index) == (None, None)  # no LapData yet: unknown
    _decode(a, spec_lap_data_tail(spec_doc, 2025, pb=3, rival=22))  # 22 is past the 2025 array (0-21)
    (tt,) = _decode(a, spec_tt_packet(spec_doc, 2025, [None, None, RIVAL]))
    assert (tt.pb_car_index, tt.rival_car_index) == (3, None)


def test_a_time_trial_packet_never_starts_or_resets_a_session(spec_doc: str) -> None:
    """A follower: before any other packet it is ignored; with another session's UID it is ignored and the adapter's
    state is kept."""
    a = _adapter()
    assert _decode(a, spec_tt_packet(spec_doc, 2025, [None, None, RIVAL])) == []
    assert a.stats.ignored == 1
    _decode(a, spec_lap_data_tail(spec_doc, 2025, pb=255, rival=1))
    assert _decode(a, spec_tt_packet(spec_doc, 2025, [None, None, RIVAL], uid=9999)) == []  # a stale UID
    (tt,) = _decode(a, spec_tt_packet(spec_doc, 2025, [None, None, RIVAL], uid=0))  # 0 = the current session
    assert tt.session_uid == str(UID) and tt.rival_car_index == 1


def test_decode_time_trial_sets_is_the_adapters_decoder(spec_doc: str) -> None:
    sets = decode_time_trial_sets(spec_tt_packet(spec_doc, 2026, [BEST, None, RIVAL]), P.LAYOUT_2026)
    assert [None if s is None else s.lap_time_ms for s in sets] == [66_100, None, 64_215]


def test_info_key_and_dict() -> None:
    d = TimeTrialDataSet(
        car_index=1,
        team_id=3,
        car_id="f1:team:3",
        car_name="Williams",
        lap_time_ms=64_215,
        sector_times_ms=(1, None, 3),
        traction_control=None,
        gearbox_assist=False,
        anti_lock_brakes=True,
        equal_car_performance=False,
        custom_setup=False,
        valid=True,
    )
    kw: dict[str, Any] = {
        "game": F1Adapter().info.game,
        "session_uid": "1",
        "packet_format": 2025,
        "player_session_best": None,
        "personal_best": None,
        "rival": d,
        "pb_car_index": None,
        "rival_car_index": 1,
    }
    a = TimeTrialInfo(t_recv_ns=1, session_time_s=1.0, **kw)
    b = TimeTrialInfo(t_recv_ns=2, session_time_s=2.0, **kw)
    assert a.key() == b.key() and a != b  # the receive time is not news
    assert a.to_dict() == {
        "packet_format": 2025,
        "session_best": None,
        "personal_best": None,
        "rival": {
            "car_index": 1,
            "team_id": 3,
            "car_id": "f1:team:3",
            "car_name": "Williams",
            "lap_time_ms": 64_215,
            "sector_times_ms": [1, None, 3],
            "traction_control": None,
            "gearbox_assist": False,
            "anti_lock_brakes": True,
            "equal_car_performance": False,
            "custom_setup": False,
            "valid": True,
        },
        "pb_car_index": None,
        "rival_car_index": 1,
    }


# ---------------------------------------------------------------- SYNTHETIC stream (the generator's Time Trial mode)
@pytest.mark.parametrize("fmt", [2025, 2026])
def test_synthetic_time_trial_stream_decodes_end_to_end(fmt: int) -> None:
    """SYNTHETIC: exercises the generator and the decoder together; says nothing about what F1 25 sends."""
    sc = time_trial_demo()
    sc.packet_format = fmt
    packets, truth = generate_f1_session(sc)
    a = F1Adapter()
    infos: list[SessionInfo] = []
    tts: list[TimeTrialInfo] = []
    for p in packets:
        for e in a.decode(p.data, p.t_recv_ns):
            if isinstance(e, SessionInfo):
                infos.append(e)
            elif isinstance(e, TimeTrialInfo):
                tts.append(e)
    assert a.stats.errors == 0 and a.stats.rejected == 0
    assert infos[-1].session_type is SessionType.TIME_TRIAL
    duration_s = sum(truth.lap_times_ms.values()) / 1000
    assert abs(len(tts) - duration_s) <= 2  # once a second
    last = tts[-1]
    assert last.rival_car_index == TT_DEMO_RIVAL_INDEX and last.pb_car_index is None
    assert last.rival is not None and last.rival.lap_time_ms == TT_DEMO_RIVAL.lap_ms
    assert last.rival.sector_times_ms == TT_DEMO_RIVAL.sectors_ms and last.rival.anti_lock_brakes is True
    assert last.personal_best is not None and last.personal_best.lap_time_ms == TT_DEMO_PERSONAL_BEST.lap_ms
    # the session best follows the player's laps: none before the first one ends, then the best valid lap
    assert tts[0].player_session_best is None
    best = last.player_session_best
    assert best is not None and best.lap_time_ms == min(truth.lap_times_ms.values()) and best.car_index == 0
    assert sum(s or 0 for s in best.sector_times_ms) == best.lap_time_ms


def test_session_best_skips_invalid_laps() -> None:
    sc = F1Scenario(laps=2, invalid_laps=frozenset({1}))
    _packets, truth = generate_f1_session(sc)
    starts = np.concatenate([[0.0], np.cumsum([truth.lap_times_ms[n] / 1000 for n in (1, 2)])])
    assert time_trial_session_best(sc, truth, starts, starts[1] + 1) is None  # lap 1 was invalid
    best = time_trial_session_best(sc, truth, starts, starts[2] + 1)
    assert best is not None and best.lap_ms == truth.lap_times_ms[2]


def test_default_streams_keep_lap_data_tails_at_255() -> None:
    packets, _truth = generate_f1_session(F1Scenario(laps=1))
    tails = {p.data[-2:] for p in packets if p.data[6] == int(P.PacketId.LAP_DATA) and len(p.data) == 1285}
    assert tails == {b"\xff\xff"}
    assert not any(p.data[6] == int(P.PacketId.TIME_TRIAL) for p in packets)
