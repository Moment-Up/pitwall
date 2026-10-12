"""Synthetic race for the race radio (SYNTHETIC - not real game output): ``race-radio-demo``.

A packet-level F1 25 (format 2025) stream of a 5-lap race on a 3000 m circle with six cars, scripted to exercise every
race radio rule, including the ones no real capture has (safety car, red flag, drive-through, stop-go served). Every
packet is encoded with the decoder's own ``StructDef`` layouts and carries ``SYNTHETIC_SESSION_UID``, so it is flagged
synthetic everywhere.

The player (car 3) stands on the grid in P4 (lap distance -100 m), the start lights go out at 7 s, and it then drives
at a constant 50 m/s (180 km/h; a lap is 60 s), braking hard and turning in for 300 m before 2700 m every lap (the
scripted braking zone: no race call may be said there except the red flag). Ground truth (``RaceRadioTruth.events``,
receive-time seconds):

* 0 SSTA, 1-5 STLG, 7 LGOT; the leader finishes first; laps cross at 9 + 60 k s;
* 20 zone 6 (1500-1800 m) turns yellow ahead of the car (at 650 m), cleared at 40;
* 30 OVTK: the player passes car 2 (P4 -> P3) on lap 1 (no call: lap 1);
* 80 the player's own FIA flag yellow for 3 s;
* 100 OVTK: the player passes car 1 (P3 -> P2), clean;
* 110 PENA 4/7 time 5 (a 5 s corner-cutting penalty), 130 PENA 5/25 (track limits warning, counters 1);
* 135 PENA 0/17 (drive-through, speeding in the pit lane), 180 DTSV;
* 150 OVTK with a COLL: the player passes car 0 (P2 -> P1) with contact;
* 160 front-left wing 40 %, 165 rear-right tyre damage 100 (a puncture);
* 170-175 the player's FIA flag blue;
* 185 RTMT car 5, 190 FLBK (to 185), 191 RTMT car 5 re-sent;
* 200 SCAR full deployed, 230 returning, 240 returned;
* 260 RDFL; 309 the chequered flag on the player's lap 5 (LapData result "finished").
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from pitwall.adapters.f1 import packets as P
from pitwall.ingest.capture import CapturedPacket
from pitwall.model.synthetic import SYNTHETIC_SESSION_UID

SCENARIO = "race-radio-demo"
TRACK_LENGTH_M = 3000.0
TOTAL_LAPS = 5
PLAYER = 3
N_CARS = 6
RATE_HZ = 10
SPEED_MPS = 50.0
GRID_M = -100.0
LIGHTS_OUT_S = 7.0
BRAKE_FROM_M, BRAKE_TO_M = 2400.0, 2700.0  # the scripted braking zone, every lap
ZONES = 10
YELLOW_ZONE = 5  # index: starts at 1500 m
END_S = 312.0
START_NS = 2_000_000_000_000


@dataclass
class RaceRadioTruth:
    events: list[tuple[float, str]] = field(default_factory=list)
    braking: tuple[float, float] = (BRAKE_FROM_M, BRAKE_TO_M)


def _hdr(pid: P.PacketId, st: float, frame: int) -> bytes:
    return P.HEADER.pack(
        {
            "packetFormat": 2025,
            "gameYear": 25,
            "gameMajorVersion": 1,
            "gameMinorVersion": 0,
            "packetVersion": 1,
            "packetId": int(pid),
            "sessionUID": SYNTHETIC_SESSION_UID,
            "sessionTime": st,
            "frameIdentifier": frame,
            "overallFrameIdentifier": frame,
            "playerCarIndex": PLAYER,
            "secondaryPlayerCarIndex": 255,
        }
    )


def _array(sd: Any, values: Mapping[int, Mapping[str, object]], n: int) -> bytes:
    empty = sd.pack({})
    return b"".join(sd.pack(values[i]) if i in values else empty for i in range(n))


def _event(code: str, details: bytes, st: float, frame: int) -> bytes:
    return _hdr(P.PacketId.EVENT, st, frame) + code.encode() + details.ljust(P.EVENT_DETAILS_SIZE, b"\x00")


def _pack_event(code: str, values: dict[str, object]) -> bytes:
    return P.EVENT_DETAILS[code].pack(values) if code in P.EVENT_DETAILS else b""


def _participants(st: float, frame: int) -> bytes:
    vals = {
        i: {
            "aiControlled": 0 if i == PLAYER else 1,
            "driverId": 255 if i == PLAYER else (54, 7, 9, 0, 58, 50)[i],
            "teamId": (8, 1, 2, 8, 1, 0)[i],
            "raceNumber": 10 + i,
            "name": b"SYNTHETIC",
            "platform": 255,
        }
        for i in range(N_CARS)
    }
    return (
        _hdr(P.PacketId.PARTICIPANTS, st, frame)
        + P.PARTICIPANTS_HEAD.pack({"numActiveCars": N_CARS})
        + _array(P.PARTICIPANT, vals, P.MAX_CARS)
    )


def _session(st: float, frame: int, *, yellow: bool, sc: int) -> bytes:
    head = P.SESSION_HEAD.pack(
        {
            "weather": 0,
            "trackTemperature": 30,
            "airTemperature": 22,
            "totalLaps": TOTAL_LAPS,
            "trackLength": round(TRACK_LENGTH_M),
            "sessionType": 15,
            "trackId": -1,
            "formula": 0,
            "sessionTimeLeft": 7200,
            "sessionDuration": 7200,
            "pitSpeedLimit": 80,
            "numMarshalZones": ZONES,
        }
    )
    zones = [
        P.MARSHAL_ZONE.pack({"zoneStart": i / ZONES, "zoneFlag": 3 if (yellow and i == YELLOW_ZONE) else 1})
        for i in range(ZONES)
    ]
    marshal = b"".join(zones) + P.MARSHAL_ZONE.pack({}) * (P.NUM_MARSHAL_ZONES - ZONES)
    mid = P.SESSION_MID.pack({"safetyCarStatus": sc, "numWeatherForecastSamples": 0})
    fcb = P.WEATHER_FORECAST_SAMPLE.pack({}) * P.NUM_WEATHER_SAMPLES
    tail = P.SESSION_TAIL.pack(
        {
            "gearboxAssist": 3,
            "aiDifficulty": 80,
            "sessionLength": 2,
            "sector2LapDistanceStart": TRACK_LENGTH_M / 3,
            "sector3LapDistanceStart": 2 * TRACK_LENGTH_M / 3,
        }
    )
    return _hdr(P.PacketId.SESSION, st, frame) + head + marshal + mid + fcb + tail


def _player_position(t: float) -> int:
    if t < 30.0:
        return 4
    if t < 100.0:
        return 3
    if t < 150.0:
        return 2
    return 1


def race_radio_demo() -> tuple[list[CapturedPacket], RaceRadioTruth]:
    """The ``race-radio-demo`` scenario: (packets, ground truth). SYNTHETIC."""
    truth = RaceRadioTruth()
    return list(_packets(truth)), truth


def _packets(truth: RaceRadioTruth) -> Iterator[CapturedPacket]:
    def pkt(t: float, data: bytes, offset_us: int = 0) -> CapturedPacket:
        return CapturedPacket(START_NS + int(t * 1e9) + offset_us * 1000, 20777, data)

    def ev(t: float, code: str, frame: int, offset_us: int, **values: object) -> CapturedPacket:
        truth.events.append((t, code))
        return pkt(t, _event(code, _pack_event(code, values), t, frame), offset_us)

    scripted: dict[int, list[tuple[str, dict[str, object]]]] = {}

    def at(t: float, code: str, **values: object) -> None:
        scripted.setdefault(round(t * RATE_HZ), []).append((code, values))

    at(0.0, "SSTA")
    for n in range(1, 6):
        at(float(n), "STLG", numLights=n)
    at(LIGHTS_OUT_S, "LGOT")
    at(30.0, "OVTK", overtakingVehicleIdx=PLAYER, beingOvertakenVehicleIdx=2)
    at(100.0, "OVTK", overtakingVehicleIdx=PLAYER, beingOvertakenVehicleIdx=1)
    at(110.0, "PENA", penaltyType=4, infringementType=7, vehicleIdx=PLAYER, otherVehicleIdx=255, time=5, lapNum=2)
    at(130.0, "PENA", penaltyType=5, infringementType=25, vehicleIdx=PLAYER, otherVehicleIdx=255, time=255, lapNum=3)
    at(135.0, "PENA", penaltyType=0, infringementType=17, vehicleIdx=PLAYER, otherVehicleIdx=255, time=255, lapNum=3)
    at(149.6, "COLL", vehicle1Idx=PLAYER, vehicle2Idx=0)
    at(150.0, "OVTK", overtakingVehicleIdx=PLAYER, beingOvertakenVehicleIdx=0)
    at(180.0, "DTSV", vehicleIdx=PLAYER)
    at(185.0, "RTMT", vehicleIdx=5, reason=0)
    at(190.0, "FLBK", flashbackFrameIdentifier=1850, flashbackSessionTime=185.0)
    at(191.0, "RTMT", vehicleIdx=5, reason=0)
    at(200.0, "SCAR", safetyCarType=1, eventType=0)
    at(230.0, "SCAR", safetyCarType=1, eventType=1)
    at(240.0, "SCAR", safetyCarType=1, eventType=2)
    at(260.0, "RDFL")
    at(129.05, "FTLP", vehicleIdx=PLAYER, lapTime=59.5)
    at(299.0, "CHQF")

    yield pkt(0.0, _participants(0.0, 0))
    frame = 0
    n_ticks = int(END_S * RATE_HZ)
    finished = False
    for k in range(n_ticks + 1):
        t = k / RATE_HZ
        frame += 1
        moving = t >= LIGHTS_OUT_S
        dist = GRID_M + (SPEED_MPS * (t - LIGHTS_OUT_S) if moving else 0.0)
        lap = 1 + math.floor(dist / TRACK_LENGTH_M) if dist >= 0 else 1
        lap_d = dist - (lap - 1) * TRACK_LENGTH_M if dist >= 0 else dist
        if lap > TOTAL_LAPS:
            lap, lap_d, finished = TOTAL_LAPS, TRACK_LENGTH_M + 5.0, True
        braking = moving and BRAKE_FROM_M <= lap_d <= BRAKE_TO_M
        pos = _player_position(t)
        others = [i for i in range(N_CARS) if i != PLAYER]
        order = [*others[: pos - 1], PLAYER, *others[pos - 1 :]]
        lapdata: dict[int, dict[str, object]] = {}
        tel: dict[int, dict[str, object]] = {}
        status: dict[int, dict[str, object]] = {}
        for rank, i in enumerate(order, start=1):
            me = i == PLAYER
            off = (pos - rank) * 60.0  # cars ahead are 60 m up the road (1.2 s)
            d_i = lap_d + off if not me else lap_d
            retired = i == 5 and t >= 185.0
            lapdata[i] = {
                "lastLapTimeInMS": 60_000 if lap > 1 else 0,
                "currentLapTimeInMS": max(0, round((t - LIGHTS_OUT_S - (lap - 1) * 60.0) * 1000)) if moving else 0,
                "sector1TimeMSPart": 20_000 if lap_d > TRACK_LENGTH_M / 3 else 0,
                "sector2TimeMSPart": 20_000 if lap_d > 2 * TRACK_LENGTH_M / 3 else 0,
                "deltaToCarInFrontMSPart": 0 if rank == 1 else 1200,
                "deltaToRaceLeaderMSPart": 0 if rank == 1 else 1200 * (rank - 1),
                "lapDistance": d_i,
                "totalDistance": max(0.0, dist),
                "carPosition": rank,
                "currentLapNum": lap,
                "pitStatus": 0,
                "sector": 0 if d_i < TRACK_LENGTH_M / 3 else (1 if d_i < 2 * TRACK_LENGTH_M / 3 else 2),
                "gridPosition": rank - 1,  # 0-based, as real F1 25 sends it
                "driverStatus": 4,
                "resultStatus": 7 if retired else (3 if (me and finished) else 2),
            }
            if me:
                lapdata[i].update(
                    penalties=5 if t >= 110.0 else 0,
                    totalWarnings=1 if t >= 130.0 else 0,
                    cornerCuttingWarnings=1 if t >= 130.0 else 0,
                    numUnservedDriveThroughPens=1 if 135.0 <= t < 180.0 else 0,
                )
            tel[i] = {
                "speed": round(SPEED_MPS * 3.6) if moving and not (me and braking) else (120 if moving else 0),
                "throttle": 1.0 if moving and not (me and braking) else 0.0,
                "brake": 1.0 if me and braking else 0.0,
                "steer": 0.3 if me and braking else 0.0,
                "gear": 7 if moving else 1,
                "engineRPM": 11000 if moving else 4000,
            }
            fia = 0
            if me and 80.0 <= t < 83.0:
                fia = 3
            elif me and 170.0 <= t < 175.0:
                fia = 2
            status[i] = {"vehicleFIAFlags": fia, "visualTyreCompound": 17, "tyresAgeLaps": lap - 1, "maxRPM": 12500}
        dmg_values: dict[str, object] = {"tyresWear": [5.0, 5.0, 5.0, 5.0]}
        if 160.0 <= t < 190.0:
            dmg_values["frontLeftWingDamage"] = 40
        if 165.0 <= t < 190.0:
            dmg_values["tyresDamage"] = [5, 100, 5, 5]  # RL, RR, FL, FR: the rear right
        L = P.LAYOUT_2025
        yield pkt(
            t,
            _hdr(P.PacketId.LAP_DATA, t, frame)
            + _array(P.LAP_DATA, lapdata, L.max_cars)
            + P.LAP_DATA_TAIL.pack({"timeTrialPBCarIdx": 255, "timeTrialRivalCarIdx": 255}),
            10,
        )
        yield pkt(t, _hdr(P.PacketId.CAR_STATUS, t, frame) + _array(L.car_status, status, L.max_cars), 20)
        yield pkt(t, _hdr(P.PacketId.CAR_DAMAGE, t, frame) + _array(P.CAR_DAMAGE, {PLAYER: dmg_values}, L.max_cars), 30)
        yield pkt(
            t,
            _hdr(P.PacketId.CAR_TELEMETRY, t, frame)
            + _array(L.car_telemetry, tel, L.max_cars)
            + P.CAR_TELEMETRY_TAIL.pack({"mfdPanelIndex": 255, "mfdPanelIndexSecondaryPlayer": 255}),
            40,
        )
        if k % (RATE_HZ // 2) == 0:
            sc = 1 if 200.5 <= t < 240.0 else 0
            yield pkt(t, _session(t, frame, yellow=20.0 <= t < 40.0, sc=sc), 50)
        if k % (5 * RATE_HZ) == 0 and k:
            yield pkt(t, _participants(t, frame), 60)
        for j, (code, values) in enumerate(scripted.get(k, [])):
            yield ev(t, code, frame, 70 + j, **values)
    t_end = END_S + 0.1
    yield ev(t_end, "SEND", frame, 0)
