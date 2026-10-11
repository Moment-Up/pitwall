"""F1 adapter: Session History (packet 11) -> ``CarLapHistory``, the per-slot AI flags and the Session packet's AI
difficulty / network fields (pace vs AI difficulty inputs). Packets are built with the spec-checked ``StructDef``s."""

from __future__ import annotations

from typing import Any

import pytest

from pitwall.adapters.f1 import packets as P
from pitwall.adapters.f1.adapter import AI_DIFFICULTY_MAX, F1Adapter
from pitwall.model.telemetry import CarLapHistory, SessionInfo

UID = 7


def hdr(pid: P.PacketId, *, uid: int = UID, t: float = 1.0, player: int = 0, fmt: int = 2025) -> bytes:
    return P.HEADER.pack(
        {
            "packetFormat": fmt,
            "gameYear": 25,
            "packetId": int(pid),
            "sessionUID": uid,
            "sessionTime": t,
            "playerCarIndex": player,
            "secondaryPlayerCarIndex": 255,
        }
    )


def lap(ms: int, bits: int = 0x0F, s1: int = 0, s2: int = 0) -> dict[str, Any]:
    return {
        "lapTimeInMS": ms,
        "sector1TimeMSPart": s1 % 60000,
        "sector1TimeMinutesPart": s1 // 60000,
        "sector2TimeMSPart": s2 % 60000,
        "sector2TimeMinutesPart": s2 // 60000,
        "lapValidBitFlags": bits,
    }


def history(
    car: int,
    laps: list[dict[str, Any]],
    *,
    stints: tuple[int, ...] = (255,),
    uid: int = UID,
    t: float = 1.0,
    player: int = 0,
    fmt: int = 2025,
    best: int = 0,
) -> bytes:
    head = P.SESSION_HISTORY_HEAD.pack(
        {"carIdx": car, "numLaps": len(laps), "numTyreStints": len(stints), "bestLapTimeLapNum": best}
    )
    body = b"".join(P.LAP_HISTORY.pack(v) for v in laps) + P.LAP_HISTORY.pack({}) * (P.NUM_LAP_HISTORY - len(laps))
    st = b"".join(P.TYRE_STINT_HISTORY.pack({"endLap": e}) for e in stints)
    st += P.TYRE_STINT_HISTORY.pack({}) * (P.NUM_TYRE_STINTS - len(stints))
    return hdr(P.PacketId.SESSION_HISTORY, uid=uid, t=t, player=player, fmt=fmt) + head + body + st


def participants(flags: list[int], n_active: int, *, uid: int = UID, fmt: int = 2025) -> bytes:
    layout = P.LAYOUTS[fmt]
    cars = [layout.participant.pack({"aiControlled": f}) for f in flags]
    cars += [layout.participant.pack({})] * (layout.max_cars - len(cars))
    return (
        hdr(P.PacketId.PARTICIPANTS, uid=uid, fmt=fmt)
        + P.PARTICIPANTS_HEAD.pack({"numActiveCars": n_active})
        + (b"".join(cars))
    )


def session(
    *,
    uid: int = UID,
    t: float = 0.0,
    ai: int = 35,
    gearbox: int = 3,
    network: int = 0,
    game_mode: int = 4,
    sc: int = 0,
    fmt: int = 2025,
) -> bytes:
    layout = P.LAYOUTS[fmt]
    head = P.SESSION_HEAD.pack({"trackId": 17, "sessionType": 15, "trackLength": 4318, "formula": 8})
    marshal = P.MARSHAL_ZONE.pack({}) * P.NUM_MARSHAL_ZONES
    mid = P.SESSION_MID.pack({"safetyCarStatus": sc, "networkGame": network})
    fc = P.WEATHER_FORECAST_SAMPLE.pack({}) * P.NUM_WEATHER_SAMPLES
    tail = layout.session_tail.pack({"aiDifficulty": ai, "gearboxAssist": gearbox, "gameMode": game_mode})
    return hdr(P.PacketId.SESSION, uid=uid, t=t, fmt=fmt) + head + marshal + mid + fc + tail


def started(fmt: int = 2025, flags: list[int] | None = None, n_active: int = 20) -> F1Adapter:
    """An adapter inside session ``UID`` (a Session packet seen), with AI flags for 20 slots (slot 0 = player)."""
    a = F1Adapter(field_hz=0)
    a.decode(session(fmt=fmt), 1)
    a.decode(participants(flags if flags is not None else [0] + [1] * 19, n_active, fmt=fmt), 2)
    return a


def hist(a: F1Adapter, data: bytes) -> list[CarLapHistory]:
    out = a.decode(data, 3)
    assert all(isinstance(e, CarLapHistory) for e in out)
    return [e for e in out if isinstance(e, CarLapHistory)]


# ---------------------------------------------------------------------------------------------- Session History
def test_first_sight_sets_first_seen_lap_and_completion_time() -> None:
    a = started()
    (h,) = hist(a, history(3, [lap(80_000), lap(78_500), lap(0)], t=170.5, best=2))
    assert h.car_index == 3 and h.ai_controlled is True and not h.is_player
    assert h.first_seen_lap == 3  # numLaps at first sight: laps 1-3 were not observed from their start
    assert h.session_uid == str(UID) and h.session_time_s == pytest.approx(170.5)
    assert [x.lap_time_ms for x in h.laps] == [80_000, 78_500, None]
    assert [x.completed_session_time_s for x in h.laps] == [pytest.approx(170.5), pytest.approx(170.5), None]
    assert h.laps[2].valid is None and h.laps[2].sector_times_ms == (None, None, None)
    assert h.best_lap_number == 2 and h.pit_laps == frozenset()
    # the next lap completes later: its time is that packet's session time, earlier laps keep theirs
    (h2,) = hist(a, history(3, [lap(80_000), lap(78_500), lap(77_900), lap(0)], t=248.4))
    assert h2.first_seen_lap == 3
    assert [x.completed_session_time_s for x in h2.laps] == [
        pytest.approx(170.5),
        pytest.approx(170.5),
        pytest.approx(248.4),
        None,
    ]


def test_identical_packet_and_partial_lap_sectors_emit_nothing() -> None:
    a = started()
    assert hist(a, history(4, [lap(80_000), lap(0)], t=100.0))
    assert hist(a, history(4, [lap(80_000), lap(0)], t=100.05)) == []
    # the lap in progress gets its sector 1 / 2 times: not a change worth a decode
    assert hist(a, history(4, [lap(80_000), lap(0, s1=25_000)], t=126.0)) == []
    assert hist(a, history(4, [lap(80_000), lap(0, s1=25_000, s2=51_000)], t=152.0)) == []
    # the lap in progress gets its time without numLaps moving (the chequered flag): emitted
    (h,) = hist(a, history(4, [lap(80_000), lap(79_000, s1=25_000, s2=51_000)], t=179.0))
    assert h.laps[1].lap_time_ms == 79_000 and h.laps[1].sector_times_ms == (25_000, 51_000, None)
    assert h.laps[1].completed_session_time_s == pytest.approx(179.0)


def test_lap_time_change_resets_and_zero_clears_the_completion_time() -> None:
    a = started()
    hist(a, history(5, [lap(0)], t=10.0))
    (h,) = hist(a, history(5, [lap(81_000), lap(0)], t=90.0))
    assert h.laps[0].completed_session_time_s == pytest.approx(90.0)
    (h,) = hist(a, history(5, [lap(81_000, bits=0x0E), lap(0)], t=91.0))  # same time, validity changed: kept
    assert h.laps[0].completed_session_time_s == pytest.approx(90.0) and h.laps[0].valid is False
    (h,) = hist(a, history(5, [lap(80_500), lap(0)], t=95.0))  # the time changed: when it changed
    assert h.laps[0].completed_session_time_s == pytest.approx(95.0)
    (h,) = hist(a, history(5, [lap(0), lap(0)], t=96.0))
    assert h.laps[0].lap_time_ms is None and h.laps[0].completed_session_time_s is None


def test_ai_flag_change_re_emits() -> None:
    a = F1Adapter(field_hz=0)
    a.decode(session(), 1)
    (h,) = hist(a, history(6, [lap(80_000), lap(0)]))
    assert h.ai_controlled is None  # no Participants packet yet: unknown
    a.decode(participants([0] + [1] * 19, 20), 2)
    (h,) = hist(a, history(6, [lap(80_000), lap(0)]))
    assert h.ai_controlled is True


def test_stint_end_laps_zero_and_255_are_ignored() -> None:
    a = started()
    (h,) = hist(a, history(7, [lap(80_000)] * 7 + [lap(0)], stints=(5, 0, 255)))
    assert h.pit_laps == frozenset({5, 6})


def test_valid_bit() -> None:
    a = started()
    (h,) = hist(a, history(8, [lap(80_000, bits=0x0F), lap(80_100, bits=0x0E), lap(80_200, bits=0x01), lap(0)]))
    assert [x.valid for x in h.laps] == [True, False, True, None]


def test_flashback_shrinking_num_laps_truncates() -> None:
    a = started()
    hist(a, history(9, [lap(80_000), lap(79_000), lap(0)], t=170.0))
    (h,) = hist(a, history(9, [lap(80_000), lap(0)], t=165.0))  # rewound into lap 2
    assert [x.lap_number for x in h.laps] == [1, 2] and h.laps[1].lap_time_ms is None
    (h,) = hist(a, history(9, [lap(80_000), lap(79_400), lap(0)], t=172.0))
    assert h.laps[1].lap_time_ms == 79_400 and h.laps[1].completed_session_time_s == pytest.approx(172.0)


def test_format_2026_and_car_index_range() -> None:
    flags = [0] + [1] * 23
    a = started(fmt=2026, flags=flags, n_active=24)
    (h,) = hist(a, history(23, [lap(80_000), lap(0)], fmt=2026))
    assert h.car_index == 23 and h.ai_controlled is True
    assert hist(a, history(24, [lap(80_000)], fmt=2026)) == []  # past the 2026 field's 24 slots
    b = started()
    assert hist(b, history(22, [lap(80_000)])) == []  # format 2025 has 22


def test_player_flag() -> None:
    a = started()
    (h,) = hist(a, history(0, [lap(80_000), lap(0)], player=0))
    assert h.is_player and h.ai_controlled is False


def test_old_uid_or_no_session_is_ignored_without_reset() -> None:
    fresh = F1Adapter(field_hz=0)
    assert fresh.decode(history(3, [lap(80_000)], uid=99), 1) == []  # no session yet: never starts one
    assert fresh._session_uid is None and fresh.stats.ignored == 1
    a = started()
    hist(a, history(3, [lap(80_000), lap(0)]))
    before = a.stats.ignored
    # 20 history packets of the PREVIOUS session (real PS5 Suzuka capture): ignored, no reset
    assert a.decode(history(3, [lap(70_000)] * 5, uid=1234), 4) == []
    assert a.stats.ignored == before + 1
    assert a._session_uid == UID and 3 in a._hist and a._ai_flags_raw  # state kept
    # uid 0 belongs to the current session
    (h,) = hist(a, history(3, [lap(80_000), lap(79_000), lap(0)], uid=0))
    assert h.session_uid == str(UID)


def test_slot_rules_for_ai_flags() -> None:
    # numActiveCars 18 while slots 0-19 are occupied (real scenario): a flag of 1 beyond it is still AI
    a = started(flags=[1] * 18 + [1, 0], n_active=18)
    flags = a._ai_flags_raw
    assert flags[17] is True and flags[18] is True  # flag 1 beyond numActiveCars -> AI
    assert flags[19] is None  # flag 0 beyond numActiveCars -> unknown (zero-filled slot)
    b = started(flags=[0, 0, 1], n_active=3)
    assert b._ai_flags_raw[:3] == (False, False, True)  # 0 inside numActiveCars -> human
    # the field model keeps its own rule (slots >= numActiveCars unknown) and is only decoded when it is on
    assert a._ai_controlled == ()
    c = F1Adapter()
    c.decode(participants([1] * 18 + [1, 0], 18), 1)
    assert c._ai_controlled[18] is None and c._ai_flags_raw[18] is True


# ---------------------------------------------------------------------------------------------- Session packet
def _info(a: F1Adapter, data: bytes) -> SessionInfo:
    (info,) = [e for e in a.decode(data, 1) if isinstance(e, SessionInfo)]
    return info


@pytest.mark.parametrize(
    ("ai", "gearbox", "expected"),
    [
        (0, 0, None),  # the unfilled tail of the first Session packets (real PS5: gearboxAssist 0)
        (35, 0, None),  # gearboxAssist 0 is not a defined value: the tail is not trusted
        (35, 1, 35),
        (31, 2, 31),
        (0, 3, 0),  # a filled tail may say 0
        (AI_DIFFICULTY_MAX, 3, AI_DIFFICULTY_MAX),
        (111, 3, None),  # outside the spec's 0-110
        (35, 4, None),
    ],
)
def test_ai_difficulty_guard(ai: int, gearbox: int, expected: int | None) -> None:
    assert _info(F1Adapter(), session(ai=ai, gearbox=gearbox)).ai_difficulty == expected


@pytest.mark.parametrize("fmt", [2025, 2026])
def test_network_game_game_mode_and_session_time(fmt: int) -> None:
    offline = _info(F1Adapter(), session(network=0, game_mode=4, t=12.5, fmt=fmt))
    assert offline.network_game is False and offline.extra["game_mode"] == 4
    assert offline.session_time_s == pytest.approx(12.5) and offline.ai_difficulty == 35
    online = _info(F1Adapter(), session(network=1, game_mode=7, fmt=fmt))
    assert online.network_game is True and online.extra["game_mode"] == 7
    assert _info(F1Adapter(), session(network=2, fmt=fmt)).network_game is None  # not a defined value
