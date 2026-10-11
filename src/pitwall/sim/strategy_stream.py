"""Synthetic race for the race strategy engineer (SYNTHETIC - not real game output): ``race-strategy-demo``.

A packet-level F1 25 (format 2025) stream of a 12-lap race with six cars on a 3000 m circle, built to exercise every
strategy path whose real-game evidence does not exist yet (safety car / VSC, rain forecast, the player's own stop)
next to the ones that are recorded-validated. Every packet is encoded with the decoder's own ``StructDef`` layouts and
carries ``SYNTHETIC_SESSION_UID``.

Ground truth (``StrategyTruth``):

* the car ahead of the player (car 2) pits at the end of lap 5: pit lane 21.0 s, stationary 2.6 s;
* a VSC runs for two minutes from the player's lap 7 (1000 m), into lap 8; every car slows to 60 % of its racing
  speed;
* the player (car 3) pits at the end of lap 8 (just after the VSC) for a used soft set the game gives two laps;
* the forecast changes to light rain 5 minutes ahead (about 5 laps) on the player's lap 4, and keeps it 5 minutes
  away to the end: the rain call comes on lap 4; from lap 8 the change falls after the chequered flag (no call);
* the player is short of fuel by 0.4 laps (fuel burn ``b0 + b1 * throttle`` with known ``b1``), so lift and coast
  has a known answer at the start of lap 6;
* the car behind the player at lap 10 (car 6) pits at the end of lap 10.

Cars move at constant racing speed within a lap (lap time = base + degradation x tyre age), at the pit speed limit
in the lane; the generator integrates each car exactly between events (line, pit entry, box, pit exit, VSC edges), so
lap times, lane times and the pit loss are known to the millisecond.
"""

from __future__ import annotations

import bisect
import copy
import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from pitwall.adapters.f1 import packets as P
from pitwall.ingest.capture import CapturedPacket
from pitwall.model.synthetic import SYNTHETIC_SESSION_UID

SCENARIO = "race-strategy-demo"
TRACK_LENGTH_M = 3000.0
TOTAL_LAPS = 12
PLAYER = 3
N_CARS = 8
RATE_HZ = 10
PIT_ENTRY_M = 2850.0
PIT_SPEED_MPS = 80.0 / 3.6
LANE_DRIVE_S = 18.4  # 21.0 s lane time with the 2.6 s stop
STOP_S = 2.6
LANE_LEN_M = LANE_DRIVE_S * PIT_SPEED_MPS
PIT_EXIT_M = LANE_LEN_M - (TRACK_LENGTH_M - PIT_ENTRY_M)  # ~258.9 m on the out-lap
BOX_M = 100.0  # the box is just after the line (as at the real Austria)
VSC_FACTOR = 0.6
FUEL_B0 = 0.0012  # kg/s
FUEL_B1 = 0.024  # kg/s at full throttle over coasting
FULL_THROTTLE_FRAC = 0.7  # of every racing lap (by distance)
VSC_THROTTLE = 0.3
FUEL_SHORT_LAPS = 0.4
WEAR_MEDIUM = (6.0, 5.5, 4.0, 4.2)  # % per lap, FL FR RL RR
WEAR_SOFT = (8.0, 7.5, 6.0, 6.0)
USED_SOFT_WEAR = (30.0, 30.0, 28.0, 28.0)
USED_SOFT_AGE = 3
RAIN_FROM_LAP = 4
RAIN_IN_MIN = 5  # the forecast's rain stays this far ahead (it never arrives: a forecast, not the weather)
VSC_START = (7, 1000.0)  # (player lap, lap distance)
VSC_S = 120.0  # ends during the player's lap 8, before its pit entry
COMPOUND_CODE = {"soft": 16, "medium": 17, "hard": 18, "inter": 7, "wet": 8}
ACTUAL_CODE = {"soft": 19, "medium": 18, "hard": 17, "inter": 7, "wet": 8}


@dataclass(slots=True)
class CarPlan:
    index: int
    start_s: float  # session time at which the car crosses the line to start lap 1 (rolling start)
    base_lap_s: float
    deg_s_per_lap: float = 0.08
    pit_lap: int | None = None  # in-lap
    compound: str = "medium"
    after: str = "hard"


PLANS = (
    CarPlan(0, 0.5, 59.0),
    CarPlan(1, 2.0, 59.2),
    CarPlan(2, 3.5, 59.5, pit_lap=5),
    CarPlan(PLAYER, 5.0, 59.4, deg_s_per_lap=0.1, pit_lap=8, after="soft"),
    CarPlan(4, 6.5, 59.6),
    CarPlan(5, 8.0, 59.48),
    CarPlan(6, 14.0, 60.0, pit_lap=10),
    CarPlan(7, 20.0, 60.6),
)


@dataclass(slots=True)
class StopTruth:
    car_index: int
    entry_lap: int
    exit_lap: int
    lane_ms: int
    stationary_ms: int
    loss_s: float  # physical: lane time minus the racing-pace time over the same distance
    neutralised: bool


@dataclass(slots=True)
class StrategyTruth:
    total_laps: int = TOTAL_LAPS
    player_index: int = PLAYER
    track_length_m: float = TRACK_LENGTH_M
    lap_times_ms: dict[int, dict[int, int]] = field(default_factory=dict)
    stops: dict[int, StopTruth] = field(default_factory=dict)
    vsc_s: tuple[float, float] | None = None
    fuel_b1: float = FUEL_B1
    fuel_per_lap_kg: float = 0.0  # player, green lap at the lap-2 pace
    lnc_s_at_lap6: float = 0.0  # lift-and-coast seconds per lap for +0.1 laps, at the start of lap 6
    fuel_margin_at_lap6: float = 0.0  # laps, at the start of lap 6 (median green burn of laps 2-5)
    fuel_at_line: dict[int, float] = field(default_factory=dict)  # player's fuel (kg) at the start of each lap
    rain_call_lap: int = RAIN_FROM_LAP
    threat_lap: int = 10
    threat_car: int = 6
    finish_order: list[int] = field(default_factory=list)


@dataclass(slots=True)
class _Car:
    plan: CarPlan
    d: float  # total distance from the start line (lap n spans [(n-1)L, nL))
    mode: str = "race"  # race | lane | box
    stopped: bool = False
    stop_left: float = 0.0
    t_lane_in: float | None = None
    t_box_in: float | None = None
    stop_ms: int = 0
    stops: int = 0
    stint_start: int = 1
    compound: str = "medium"
    age0: int = 0  # tyre age at the stint start
    lap_start_t: float | None = None
    last_lap_ms: int = 0
    finished_t: float | None = None
    t_hist: list[float] = field(default_factory=list)
    d_hist: list[float] = field(default_factory=list)
    fuel: float = 0.0

    @property
    def lap(self) -> int:
        return max(1, min(TOTAL_LAPS, int(self.d // TRACK_LENGTH_M) + 1)) if self.d >= 0 else 1

    def racing_speed(self, lap: int, vsc: bool) -> float:
        age = self.age0 + max(0, lap - self.stint_start)
        t = self.plan.base_lap_s + self.plan.deg_s_per_lap * age
        return TRACK_LENGTH_M / t * (VSC_FACTOR if vsc else 1.0)


def _player_vsc_times(cars: list[_Car]) -> tuple[float, float]:
    """Session times of the VSC: from the player's lap 7 at 1000 m (worked out from its own racing pace; nothing
    slows it before) for ``VSC_S``, which ends it during lap 8, before the player's stop."""
    p = cars[PLAYER].plan

    def lap_s(lap: int) -> float:
        return p.base_lap_s + p.deg_s_per_lap * (lap - 1)

    t = p.start_s + sum(lap_s(n) for n in range(1, VSC_START[0]))
    t0 = t + lap_s(VSC_START[0]) * VSC_START[1] / TRACK_LENGTH_M
    return t0, t0 + VSC_S


def _simulate(dt: float) -> tuple[list[dict[str, Any]], StrategyTruth, list[_Car]]:
    """Integrate every car; return per-tick snapshots (all cars) and the truth."""
    truth = StrategyTruth()
    cars = [_Car(plan=p, d=-p.start_s * TRACK_LENGTH_M / p.base_lap_s, compound=p.compound) for p in PLANS]
    vsc0, vsc1 = _player_vsc_times(cars)
    truth.vsc_s = (vsc0, vsc1)
    per_lap = FUEL_B0 * 59.5 + FUEL_B1 * 59.5 * FULL_THROTTLE_FRAC  # at the lap-2 pace (base 59.4 + 0.1)
    truth.fuel_per_lap_kg = per_lap
    # fuel at the start of lap 6 is short of the finish (7 laps) by FUEL_SHORT_LAPS; laps 1-5 burn about 5 laps
    pc = cars[PLAYER]
    pc.fuel = per_lap * (TOTAL_LAPS - 5 - FUEL_SHORT_LAPS) + 5 * per_lap
    for c in cars:
        truth.lap_times_ms[c.plan.index] = {}
    snaps: list[dict[str, Any]] = []
    t = 0.0
    end_t: float | None = None
    stop_info: dict[int, dict[str, Any]] = {}
    while end_t is None or t < end_t:
        vsc = vsc0 <= t < vsc1
        for c in cars:
            _advance(c, t, dt, vsc0, vsc1, truth, stop_info)
            c.t_hist.append(t + dt)
            c.d_hist.append(c.d)
        t += dt
        snaps.append(_snapshot(cars, t, vsc))
        if end_t is None and cars[PLAYER].finished_t is not None and all(c.finished_t for c in cars):
            end_t = t + 3.0
        if t > 2000:  # safety net
            break
    # fuel truth at the start of lap 6, with the engine's own definitions (median burn of green laps 2-5)
    fl = truth.fuel_at_line
    burns = sorted(fl[n] - fl[n + 1] for n in range(2, 6))
    per = (burns[1] + burns[2]) / 2
    truth.fuel_per_lap_kg = per
    remaining = TOTAL_LAPS - 5
    truth.fuel_margin_at_lap6 = fl[6] / per - remaining
    truth.lnc_s_at_lap6 = (0.1 - truth.fuel_margin_at_lap6) * per / remaining / FUEL_B1
    finished = sorted((c for c in cars if c.finished_t is not None), key=lambda c: c.finished_t or 0.0)
    truth.finish_order = [c.plan.index for c in finished]
    for idx, info in stop_info.items():
        truth.stops[idx] = StopTruth(
            car_index=idx,
            entry_lap=info["entry_lap"],
            exit_lap=info["exit_lap"],
            lane_ms=round((info["t_out"] - info["t_in"]) * 1000),
            stationary_ms=round(STOP_S * 1000),
            loss_s=info["loss_s"],
            neutralised=info["neutralised"],
        )
    return snaps, truth, cars


def _advance(
    c: _Car, t: float, dt: float, vsc0: float, vsc1: float, truth: StrategyTruth, stops: dict[int, dict[str, Any]]
) -> None:
    """Move one car exactly through [t, t + dt], handling every event inside the step."""
    left = dt
    while left > 1e-12:
        now = t + (dt - left)
        vsc = vsc0 <= now < vsc1
        if c.mode == "box":
            step = min(left, c.stop_left)
            c.stop_left -= step
            left -= step
            if c.stop_left <= 1e-12:
                c.mode = "lane"
                c.stops += 1
                c.stop_ms = round(STOP_S * 1000)
            continue
        lap = c.lap if c.d >= 0 else 1
        v = PIT_SPEED_MPS if c.mode == "lane" else c.racing_speed(lap, vsc)
        # next event distance
        targets: list[tuple[float, str]] = []
        next_line = (math.floor(c.d / TRACK_LENGTH_M) + 1) * TRACK_LENGTH_M if c.d >= 0 else 0.0
        targets.append((next_line, "line"))
        p = c.plan
        if c.mode == "race" and p.pit_lap is not None and not c.stopped and c.finished_t is None:
            entry = (p.pit_lap - 1) * TRACK_LENGTH_M + PIT_ENTRY_M
            if c.d < entry:
                targets.append((entry, "entry"))
        if c.mode == "lane" and p.pit_lap is not None:
            box = p.pit_lap * TRACK_LENGTH_M + BOX_M
            exit_d = p.pit_lap * TRACK_LENGTH_M + PIT_EXIT_M
            if not c.stopped and c.d < box:
                targets.append((box, "box"))
            elif c.stopped:
                targets.append((exit_d, "exit"))
        d_next, what = min(targets)
        t_event = (d_next - c.d) / v
        edge = None
        for e in (vsc0, vsc1):
            if c.mode == "race" and now < e < now + min(left, t_event):
                edge = e - now
        if edge is not None:
            c.d += v * edge
            _burn(c, edge, v, vsc)
            left -= edge
            continue
        if t_event > left:
            c.d += v * left
            _burn(c, left, v, vsc)
            left = 0.0
            continue
        c.d = d_next
        _burn(c, t_event, v, vsc)
        left -= t_event
        te = t + (dt - left)
        if what == "line":
            _line(c, te, truth)
        elif what == "entry":
            c.mode = "lane"
            c.t_lane_in = te
            stops[p.index] = {"entry_lap": p.pit_lap, "t_in": te, "neutralised": vsc0 <= te < vsc1}
        elif what == "box":
            c.mode = "box"
            c.t_box_in = te
            c.stop_left = STOP_S
            c.stopped = True
            c.compound = p.after
            c.stint_start = (p.pit_lap or 0) + 1
            c.age0 = USED_SOFT_AGE if p.index == PLAYER else 0
        elif what == "exit":
            c.mode = "race"
            info = stops[p.index]
            info["t_out"] = te
            info["exit_lap"] = (p.pit_lap or 0) + 1
            lane = te - info["t_in"]
            # racing-pace time over the lane's distance, at the in-lap and out-lap paces
            lap_in, lap_out = p.pit_lap or 0, (p.pit_lap or 0) + 1
            v_in = TRACK_LENGTH_M / (p.base_lap_s + p.deg_s_per_lap * (lap_in - 1))  # every car starts on new tyres
            v_out = c.racing_speed(lap_out, False)
            race_t = (TRACK_LENGTH_M - PIT_ENTRY_M) / v_in + PIT_EXIT_M / v_out
            info["loss_s"] = lane - race_t
            info["neutralised"] = info["neutralised"] or vsc0 <= te < vsc1
            c.t_lane_in = None
            c.t_box_in = None


def _line(c: _Car, te: float, truth: StrategyTruth) -> None:
    n = round(c.d / TRACK_LENGTH_M)  # laps completed
    if c.plan.index == PLAYER:
        truth.fuel_at_line[n + 1] = c.fuel
    if n == 0:
        c.lap_start_t = te
        return
    if c.lap_start_t is not None and n <= TOTAL_LAPS:
        ms = round((te - c.lap_start_t) * 1000)
        truth.lap_times_ms[c.plan.index][n] = ms
        c.last_lap_ms = ms
    c.lap_start_t = te
    if n >= TOTAL_LAPS and c.finished_t is None:
        c.finished_t = te


def _burn(c: _Car, dt: float, v: float, vsc: bool) -> None:
    if c.plan.index != PLAYER or dt <= 0:
        return
    thr = VSC_THROTTLE if vsc and c.mode == "race" else _player_throttle(c)
    c.fuel = max(0.0, c.fuel - (FUEL_B0 + FUEL_B1 * thr) * dt)


def _player_throttle(c: _Car) -> float:
    if c.mode != "race":
        return 0.2
    lap_d = c.d % TRACK_LENGTH_M if c.d >= 0 else c.d + TRACK_LENGTH_M
    return 1.0 if lap_d < FULL_THROTTLE_FRAC * TRACK_LENGTH_M else 0.0


def _snapshot(cars: list[_Car], t: float, vsc: bool) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for c in cars:
        lap = c.lap
        lap_d = c.d - (lap - 1) * TRACK_LENGTH_M
        if c.finished_t is not None:
            lap_d = min(lap_d, TRACK_LENGTH_M + 500.0)
        rows.append(
            {
                "car": c,
                "lap": lap,
                "lap_d": lap_d,
                "pit": 2 if c.mode == "box" else (1 if c.mode == "lane" else 0),
                "speed": 0.0 if c.mode == "box" else (PIT_SPEED_MPS if c.mode == "lane" else c.racing_speed(lap, vsc)),
                "throttle": (VSC_THROTTLE if vsc and c.mode == "race" else _player_throttle(c))
                if c.plan.index == PLAYER
                else 0.8,
            }
        )

    def key(r: dict[str, Any]) -> tuple[float, float]:
        c = r["car"]
        if c.finished_t is not None:
            return (1.0, -c.finished_t)
        return (0.0, c.d)

    order = sorted(rows, key=key, reverse=True)
    for pos, r in enumerate(order, start=1):
        r["pos"] = pos
    leader = order[0]["car"]
    for k, r in enumerate(order):
        c = r["car"]
        if k == 0:
            r["gap_ahead_ms"] = r["gap_leader_ms"] = 0
            continue
        r["gap_ahead_ms"] = _gap_ms(c, order[k - 1]["car"], t)
        r["gap_leader_ms"] = _gap_ms(c, leader, t)
    for r in rows:
        r["car"] = copy.copy(r["car"])  # this tick's state (the packets are encoded after the whole race is run)
    return {"t": t, "rows": sorted(rows, key=lambda r: r["car"].plan.index), "vsc": vsc}


def _gap_ms(c: _Car, ahead: _Car, t: float) -> int:
    """Time since ``ahead`` was where ``c`` is now (race-time gap)."""
    if c.finished_t is not None or c.d <= ahead.d_hist[0]:
        return 0
    i = bisect.bisect_left(ahead.d_hist, c.d)
    if i <= 0 or i >= len(ahead.d_hist):
        return 0
    d0, d1 = ahead.d_hist[i - 1], ahead.d_hist[i]
    t0, t1 = ahead.t_hist[i - 1], ahead.t_hist[i]
    ta = t0 if d1 == d0 else t0 + (c.d - d0) / (d1 - d0) * (t1 - t0)
    return max(0, round((t - ta) * 1000))


# ---------------------------------------------------------------------------------------------------- packets
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


def _forecast(lap: int) -> list[dict[str, int]]:
    rain = lap >= RAIN_FROM_LAP
    out = []
    for off in (0, 5, 10, 15, 30):
        w = 3 if rain and off >= RAIN_IN_MIN else 0
        out.append(
            {
                "sessionType": 15,
                "timeOffset": off,
                "weather": w,
                "trackTemperature": 30,
                "airTemperature": 22,
                "rainPercentage": 60 if w == 3 else 5,
            }
        )
    return out


def _session(st: float, frame: int, lap: int, vsc: bool, vsc_periods: int) -> bytes:
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
            "sessionTimeLeft": 3600,
            "sessionDuration": 3600,
            "pitSpeedLimit": 80,
            "numMarshalZones": 0,
        }
    )
    marshal = P.MARSHAL_ZONE.pack({}) * P.NUM_MARSHAL_ZONES
    fc = _forecast(lap)
    mid = P.SESSION_MID.pack({"safetyCarStatus": 2 if vsc else 0, "numWeatherForecastSamples": len(fc)})
    fcb = b"".join(P.WEATHER_FORECAST_SAMPLE.pack(s) for s in fc) + P.WEATHER_FORECAST_SAMPLE.pack({}) * (
        P.NUM_WEATHER_SAMPLES - len(fc)
    )
    tail = P.SESSION_TAIL.pack(
        {
            "forecastAccuracy": 0,
            "sessionLength": 2,
            "numVirtualSafetyCarPeriods": vsc_periods,
            "sector2LapDistanceStart": TRACK_LENGTH_M / 3,
            "sector3LapDistanceStart": 2 * TRACK_LENGTH_M / 3,
        }
    )
    return _hdr(P.PacketId.SESSION, st, frame) + head + marshal + mid + fcb + tail


def _event(code: str, details: bytes, st: float, frame: int) -> bytes:
    return _hdr(P.PacketId.EVENT, st, frame) + code.encode() + details.ljust(P.EVENT_DETAILS_SIZE, b"\x00")


def _participants(st: float, frame: int) -> bytes:
    vals = {
        i: {"aiControlled": 0 if i == PLAYER else 1, "name": b"SYNTHETIC", "teamId": i, "platform": 255}
        for i in range(N_CARS)
    }
    return (
        _hdr(P.PacketId.PARTICIPANTS, st, frame)
        + P.PARTICIPANTS_HEAD.pack({"numActiveCars": N_CARS})
        + _array(P.PARTICIPANT, vals, P.MAX_CARS)
    )


def _player_wear(c: _Car) -> tuple[float, float, float, float]:
    laps_on = max(0.0, c.d / TRACK_LENGTH_M - (c.stint_start - 1)) if c.d >= 0 else 0.0
    if c.compound == "soft":
        return tuple(int(w0 + r * laps_on) for w0, r in zip(USED_SOFT_WEAR, WEAR_SOFT, strict=True))  # type: ignore[return-value]
    return tuple(int(r * laps_on) for r in WEAR_MEDIUM)  # type: ignore[return-value]


def _tyre_sets(c: _Car, st: float, frame: int, car_idx: int = PLAYER) -> bytes:
    lap = c.lap
    phase2 = c.compound == "soft"
    sets: dict[int, dict[str, object]] = {}

    def tset(i: int, comp: str, *, wear: int = 0, life: int, usable: int, delta_ms: int, fitted: bool = False) -> None:
        sets[i] = {
            "actualTyreCompound": ACTUAL_CODE[comp],
            "visualTyreCompound": COMPOUND_CODE[comp],
            "wear": wear,
            "available": 1,
            "recommendedSession": 15,
            "lifeSpan": max(0, life),
            "usableLife": usable,
            "lapDeltaTime": delta_ms,
            "fitted": int(fitted),
        }

    age = lap - 1
    max_wear = int(max(_player_wear(c)))
    if not phase2:
        tset(0, "medium", wear=max_wear, life=10 - age, usable=10, delta_ms=0, fitted=True)
        tset(1, "medium", life=10, usable=10, delta_ms=-(300 + 100 * age))
        tset(2, "hard", life=20, usable=20, delta_ms=300 - 100 * age)
        tset(3, "soft", life=6, usable=6, delta_ms=-(800 + 100 * age))
        tset(4, "soft", wear=30, life=3, usable=6, delta_ms=-(500 + 100 * age))
    else:
        n = lap - 8  # laps on the used softs (out-lap 9 = 1)
        tset(0, "medium", wear=60, life=0, usable=10, delta_ms=900)
        tset(1, "medium", life=10, usable=10, delta_ms=-(1000 + 100 * n))
        tset(2, "hard", life=20, usable=20, delta_ms=-(600 + 100 * n))
        tset(3, "soft", life=6, usable=6, delta_ms=-(2500 + 100 * n))
        tset(4, "soft", wear=max_wear, life=3 - n, usable=6, delta_ms=0, fitted=True)
    for i in (5, 6, 7):
        tset(i, "inter", life=40, usable=40, delta_ms=3000)
    for i in (8, 9):
        tset(i, "wet", life=30, usable=30, delta_ms=5000)
    rows = [
        P.TYRE_SET.pack(sets[i]) if i in sets else P.TYRE_SET.pack({"available": 0}) for i in range(P.NUM_TYRE_SETS)
    ]
    fitted = 4 if phase2 else 0
    return (
        _hdr(P.PacketId.TYRE_SETS, st, frame)
        + P.TYRE_SETS_HEAD.pack({"carIdx": car_idx})
        + b"".join(rows)
        + P.TYRE_SETS_TAIL.pack({"fittedIdx": fitted})
    )


def _packets(
    snaps: list[dict[str, Any]], truth: StrategyTruth, start_ns: int = 1_000_000_000_000
) -> Iterator[CapturedPacket]:
    frame = 0
    radius = TRACK_LENGTH_M / (2 * math.pi)
    vsc_periods = 0
    last_vsc = False
    drs_sent = False
    chqf_sent = False

    def pkt(t: float, data: bytes, offset_us: int = 0) -> CapturedPacket:
        return CapturedPacket(start_ns + int(t * 1e9) + offset_us * 1000, 20777, data)

    yield pkt(0.0, _participants(0.0, 0))
    yield pkt(0.0, _event("SSTA", b"", 0.0, 0), 50)
    yield pkt(0.0, _event("LGOT", b"", 0.0, 0), 60)
    for k, snap in enumerate(snaps):
        t = snap["t"]
        frame += 1
        rows = snap["rows"]
        me = rows[PLAYER]
        pc: _Car = me["car"]
        vsc = snap["vsc"]
        motion: dict[int, dict[str, object]] = {}
        lapdata: dict[int, dict[str, object]] = {}
        tel: dict[int, dict[str, object]] = {}
        status: dict[int, dict[str, object]] = {}
        for r in rows:
            c: _Car = r["car"]
            i = c.plan.index
            ang = 2 * math.pi * (c.d % TRACK_LENGTH_M) / TRACK_LENGTH_M
            v = r["speed"]
            motion[i] = {
                "worldPositionX": radius * math.cos(ang),
                "worldPositionZ": radius * math.sin(ang),
                "worldVelocityX": -v * math.sin(ang),
                "worldVelocityZ": v * math.cos(ang),
                "gForceLateral": v * v / radius / 9.81,
                "yaw": ang,
            }
            in_lane = c.mode in ("lane", "box")
            lane_ms = round((t - c.t_lane_in) * 1000) if in_lane and c.t_lane_in is not None else 0
            if c.mode == "box" and c.t_box_in is not None:
                stop_ms = round((t - c.t_box_in) * 1000)
            elif c.mode == "lane" and c.stopped and c.t_lane_in is not None:
                stop_ms = c.stop_ms
            else:
                stop_ms = 0
            gap = int(r["gap_ahead_ms"])
            lead = int(r["gap_leader_ms"])
            if c.mode == "lane" and not c.stopped:
                drv = 2
            elif in_lane or (c.stopped and c.plan.pit_lap is not None and r["lap"] == c.plan.pit_lap + 1):
                drv = 3
            else:
                drv = 4
            lapdata[i] = {
                "lastLapTimeInMS": c.last_lap_ms,
                "currentLapTimeInMS": 0 if c.lap_start_t is None else max(0, round((t - c.lap_start_t) * 1000)),
                "deltaToCarInFrontMSPart": gap % 60000,
                "deltaToCarInFrontMinutesPart": gap // 60000,
                "deltaToRaceLeaderMSPart": lead % 60000,
                "deltaToRaceLeaderMinutesPart": lead // 60000,
                "lapDistance": r["lap_d"],
                "totalDistance": c.d,
                "carPosition": r["pos"],
                "currentLapNum": r["lap"],
                "pitStatus": r["pit"],
                "numPitStops": c.stops,
                "sector": 0 if r["lap_d"] < TRACK_LENGTH_M / 3 else (1 if r["lap_d"] < 2 * TRACK_LENGTH_M / 3 else 2),
                "gridPosition": i + 1,
                "driverStatus": drv,
                "resultStatus": 3 if c.finished_t is not None else 2,
                "pitLaneTimerActive": int(in_lane),
                "pitLaneTimeInLaneInMS": min(lane_ms, 65535),
                "pitStopTimerInMS": min(stop_ms, 65535),
            }
            throttle = r["throttle"]
            tel[i] = {
                "speed": round(v * 3.6),
                "throttle": throttle,
                "steer": 0.0,
                "brake": 0.0,
                "gear": 7 if v > 30 else 3,
                "engineRPM": 10500 if v > 30 else 7000,
                "tyresSurfaceTemperature": [95, 95, 95, 95],
                "tyresInnerTemperature": [100, 100, 100, 100],
                "tyresPressure": [22.0, 22.0, 23.5, 23.5],
                "brakesTemperature": [400, 400, 400, 400],
            }
            age = c.age0 + max(0, r["lap"] - c.stint_start)
            status[i] = {
                "fuelMix": 1,
                "visualTyreCompound": COMPOUND_CODE[c.compound],
                "actualTyreCompound": ACTUAL_CODE[c.compound],
                "tyresAgeLaps": age,
                "maxRPM": 12500,
                "idleRPM": 4000,
                "maxGears": 8,
            }
        # player's fuel and the game's own (MFD) margin
        remaining = max(0.0, TOTAL_LAPS - me["lap"] + 1 - max(0.0, me["lap_d"]) / TRACK_LENGTH_M)
        if pc.finished_t is not None:
            remaining = 0.0
        status[PLAYER].update(
            fuelInTank=pc.fuel,
            fuelCapacity=110.0,
            fuelRemainingLaps=pc.fuel / truth.fuel_per_lap_kg - remaining,
            frontBrakeBias=56,
            ersStoreEnergy=3.0e6,
        )
        L = P.LAYOUT_2025
        yield pkt(t, _hdr(P.PacketId.MOTION, t, frame) + _array(L.car_motion, motion, L.max_cars))
        yield pkt(
            t,
            _hdr(P.PacketId.LAP_DATA, t, frame)
            + _array(P.LAP_DATA, lapdata, L.max_cars)
            + P.LAP_DATA_TAIL.pack({"timeTrialPBCarIdx": 255, "timeTrialRivalCarIdx": 255}),
            40,
        )
        yield pkt(
            t,
            _hdr(P.PacketId.CAR_TELEMETRY, t, frame)
            + _array(L.car_telemetry, tel, L.max_cars)
            + P.CAR_TELEMETRY_TAIL.pack({"mfdPanelIndex": 255, "mfdPanelIndexSecondaryPlayer": 255}),
            80,
        )
        yield pkt(t, _hdr(P.PacketId.CAR_STATUS, t, frame) + _array(L.car_status, status, L.max_cars), 120)
        wear = _player_wear(pc)
        dmg = {PLAYER: {"tyresWear": [wear[2], wear[3], wear[0], wear[1]]}}  # RL, RR, FL, FR
        yield pkt(t, _hdr(P.PacketId.CAR_DAMAGE, t, frame) + _array(P.CAR_DAMAGE, dmg, L.max_cars), 160)
        if vsc and not last_vsc:
            vsc_periods += 1
            yield pkt(t, _event("SCAR", bytes([2, 0]), t, frame), 170)
        elif last_vsc and not vsc:
            yield pkt(t, _event("SCAR", bytes([2, 2]), t, frame), 170)
        last_vsc = vsc
        if k % (RATE_HZ // 2) == 0:
            yield pkt(t, _session(t, frame, me["lap"], vsc, vsc_periods), 200)
        if k % RATE_HZ == 0:
            yield pkt(t, _tyre_sets(pc, t, frame), 240)
        if k % (2 * RATE_HZ) == 5:
            yield pkt(t, _tyre_sets(rows[0]["car"], t, frame, car_idx=0), 250)  # another car's sets: ignored
        if k % (5 * RATE_HZ) == 0:
            yield pkt(t, _participants(t, frame), 280)
        if not drs_sent and me["lap"] >= 2:
            drs_sent = True
            yield pkt(t, _event("DRSE", b"", t, frame), 290)
        leader_done = any(r["car"].finished_t is not None for r in rows)
        if leader_done and not chqf_sent:
            chqf_sent = True
            yield pkt(t, _event("CHQF", b"", t, frame), 300)
    t_end = snaps[-1]["t"] + 0.05
    yield pkt(t_end, _event("SEND", b"", t_end, frame), 0)


def race_strategy_demo() -> tuple[list[CapturedPacket], StrategyTruth]:
    """The ``race-strategy-demo`` scenario: (packets, ground truth). SYNTHETIC."""
    snaps, truth, _cars = _simulate(1.0 / RATE_HZ)
    return list(_packets(snaps, truth)), truth


SCENARIOS = {SCENARIO: race_strategy_demo}


def write_strategy_capture(path: Any) -> StrategyTruth:
    """Write the scenario as a ``.pwcap`` flagged synthetic (for replays through the full pipeline)."""
    from pitwall.ingest.capture import CaptureMeta, write_capture

    packets, truth = race_strategy_demo()
    meta = CaptureMeta(
        source="synthetic",
        game_hint="f1_25",
        synthetic=True,
        description=f"SYNTHETIC F1 25 packet stream, scenario '{SCENARIO}' - not real game output",
        extra={"track_name": "Synthetic circle", "scenario": SCENARIO},
    )
    write_capture(path, packets, meta)
    return truth
