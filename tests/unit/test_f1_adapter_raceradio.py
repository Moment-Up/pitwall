"""F1 adapter mappings for the race radio: the player's FIA flag, CarDamage, penalty counters, the Participants table.
Packets packed with the decoder's own spec-checked ``StructDef`` layouts (test data, not game output)."""

from __future__ import annotations

from typing import Any

import pytest

from pitwall.adapters.f1 import packets as P
from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.model.telemetry import CarFrame, Participants, Wheels

PLAYER = 2


def hdr(fmt: int, pid: P.PacketId, frame: int = 1) -> bytes:
    return P.HEADER.pack(
        {"packetFormat": fmt, "packetId": int(pid), "sessionUID": 9, "playerCarIndex": PLAYER, "frameIdentifier": frame}
    )


def cars(sd: Any, n: int, player: dict[str, object], others: dict[str, object] | None = None) -> bytes:
    return b"".join(sd.pack(player if i == PLAYER else (others or {})) for i in range(n))


def telemetry(fmt: int, frame: int = 1) -> bytes:
    L = P.LAYOUTS[fmt]
    return (
        hdr(fmt, P.PacketId.CAR_TELEMETRY, frame)
        + cars(L.car_telemetry, L.max_cars, {"speed": 200})
        + (P.CAR_TELEMETRY_TAIL.pack({}))
    )


def status(fmt: int, flag: int) -> bytes:
    L = P.LAYOUTS[fmt]
    return hdr(fmt, P.PacketId.CAR_STATUS) + cars(L.car_status, L.max_cars, {"vehicleFIAFlags": flag})


def damage_packet(fmt: int, values: dict[str, object]) -> bytes:
    L = P.LAYOUTS[fmt]
    return hdr(fmt, P.PacketId.CAR_DAMAGE) + cars(P.CAR_DAMAGE, L.max_cars, values)


def lap_packet(fmt: int, values: dict[str, object]) -> bytes:
    L = P.LAYOUTS[fmt]
    row = {"currentLapNum": 3, "resultStatus": 2, "driverStatus": 4, "carPosition": 5, **values}
    return hdr(fmt, P.PacketId.LAP_DATA) + cars(P.LAP_DATA, L.max_cars, row) + P.LAP_DATA_TAIL.pack({})


def participants_packet(fmt: int, rows: dict[int, dict[str, object]], n_active: int) -> bytes:
    L = P.LAYOUTS[fmt]
    body = b"".join(L.participant.pack(rows.get(i, {})) for i in range(L.max_cars))
    return hdr(fmt, P.PacketId.PARTICIPANTS) + P.PARTICIPANTS_HEAD.pack({"numActiveCars": n_active}) + body


def frames(a: F1Adapter, *packets: bytes) -> list[Any]:
    out: list[Any] = []
    for i, data in enumerate(packets):
        out.extend(a.decode(data, i))
    return out


@pytest.mark.parametrize("fmt", [2025, 2026])
@pytest.mark.parametrize(
    ("raw", "want"), [(-1, None), (0, "none"), (1, "green"), (2, "blue"), (3, "yellow"), (4, None)]
)
def test_fia_flag_mapping(fmt: int, raw: int, want: str | None) -> None:
    a = F1Adapter(field_hz=0, timing_hz=0)
    [f] = [x for x in frames(a, status(fmt, raw), telemetry(fmt)) if isinstance(x, CarFrame)]
    assert f.fia_flag == want  # -1 and the undocumented 4 ("red" in community code) stay unknown


@pytest.mark.parametrize("fmt", [2025, 2026])
def test_car_damage_wheel_order_and_object_identity(fmt: int) -> None:
    a = F1Adapter(field_hz=0, timing_hz=0)
    values = {
        "tyresWear": [10.0, 11.0, 12.0, 13.0],
        "tyresDamage": [1, 2, 3, 100],  # RL, RR, FL, FR on the wire
        "brakesDamage": [5, 6, 7, 8],
        "frontLeftWingDamage": 58,
        "frontRightWingDamage": 12,
        "rearWingDamage": 3,
        "floorDamage": 33,
        "diffuserDamage": 4,
        "sidepodDamage": 9,
        "gearBoxDamage": 2,
        "engineDamage": 1,
        "drsFault": 1,
        "ersFault": 0,
        "engineBlown": 0,
        "engineSeized": 1,
    }
    got = [x for x in frames(a, damage_packet(fmt, values), telemetry(fmt)) if isinstance(x, CarFrame)]
    d = got[0].damage
    assert d is not None
    assert d.tyres_pct == Wheels(fl=3, fr=100, rl=1, rr=2) and d.brakes_pct == Wheels(fl=7, fr=8, rl=5, rr=6)
    assert (d.front_left_wing_pct, d.front_right_wing_pct, d.rear_wing_pct, d.floor_pct) == (58, 12, 3, 33)
    assert (d.diffuser_pct, d.sidepod_pct, d.gearbox_pct, d.engine_pct) == (4, 9, 2, 1)
    assert (d.drs_fault, d.ers_fault, d.engine_blown, d.engine_seized) == (True, False, False, True)
    assert got[0].tyre_wear_pct == Wheels(fl=12.0, fr=13.0, rl=10.0, rr=11.0)  # unchanged mapping
    worn = {**values, "tyresWear": [11.0, 12.0, 13.0, 14.0]}  # only the wear moved
    again = [x for x in frames(a, damage_packet(fmt, worn), telemetry(fmt, 2)) if isinstance(x, CarFrame)]
    assert again[0].damage is d  # the same object while the damage bytes are unchanged
    broken = {**values, "rearWingDamage": 100}
    third = [x for x in frames(a, damage_packet(fmt, broken), telemetry(fmt, 3)) if isinstance(x, CarFrame)]
    assert third[0].damage is not d and third[0].damage is not None and third[0].damage.rear_wing_pct == 100


def test_penalty_counters() -> None:
    a = F1Adapter(field_hz=0, timing_hz=0)
    lap = {
        "penalties": 5,
        "totalWarnings": 2,
        "cornerCuttingWarnings": 1,
        "numUnservedDriveThroughPens": 1,
        "numUnservedStopGoPens": 0,
        "pitStopShouldServePen": 1,
    }
    [f] = [x for x in frames(a, lap_packet(2025, lap), telemetry(2025)) if isinstance(x, CarFrame)]
    p = f.penalties
    assert p is not None
    assert (p.time_penalties_s, p.warnings, p.corner_cutting_warnings) == (5, 2, 1)
    assert (p.unserved_drive_throughs, p.unserved_stop_gos, p.serve_at_stop) == (1, 0, True)
    [f2] = [x for x in frames(a, lap_packet(2025, lap), telemetry(2025, 2)) if isinstance(x, CarFrame)]
    assert f2.penalties is p


@pytest.mark.parametrize(("fmt", "network"), [(2025, 255), (2026, 65535)])
def test_participants_emitted_only_on_change_names_kept_out_of_reprs(fmt: int, network: int) -> None:
    a = F1Adapter(field_hz=0, timing_hz=0)
    rows: dict[int, dict[str, object]] = {
        0: {"aiControlled": 1, "driverId": 54, "teamId": 8, "raceNumber": 4, "name": b"NORRIS", "showOnlineNames": 1},
        1: {"aiControlled": 1, "driverId": network, "teamId": 41, "raceNumber": 0, "name": b"Zz_Canary"},
        PLAYER: {"aiControlled": 0, "driverId": network, "teamId": 3, "raceNumber": 23, "name": "Mé".encode()},
    }
    out = frames(a, participants_packet(fmt, rows, 3))
    [p] = [x for x in out if isinstance(x, Participants)]
    assert p.player_index == PLAYER and [c.car_index for c in p.cars] == [0, 1, 2]
    c0, c1, c2 = p.cars
    assert (c0.ai_controlled, c0.driver_id, c0.team_id, c0.race_number, c0.show_online_names) == (True, 54, 8, 4, True)
    assert (c1.driver_id, c1.race_number) == (None, None)  # 255 / 65535: a network human (or a player's ID)
    assert (c2.ai_controlled, c2.driver_id, c2.name) == (False, None, "Mé")
    assert "Zz_Canary" not in repr(p) and "NORRIS" not in repr(p)
    assert [x for x in frames(a, participants_packet(fmt, rows, 3)) if isinstance(x, Participants)] == []  # same
    rows[1] = {**rows[1], "aiControlled": 0}
    assert len([x for x in frames(a, participants_packet(fmt, rows, 3)) if isinstance(x, Participants)]) == 1
