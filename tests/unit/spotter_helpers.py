"""Builders for spotter unit tests: decoded Motion packets with cars placed relative to the player (SYNTHETIC)."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from pitwall.model.telemetry import Game, SessionInfo
from pitwall.spotter.engine import SpotterEngine
from pitwall.spotter.model import DecodedMotion, SpotterCall
from pitwall.spotter.settings import SpotterSettings

N_CARS = 22
PLAYER_SPEED = 60.0  # m/s (216 km/h)
EMPTY = (0.0,) * 12


@dataclass(slots=True)
class Car:
    lon: float  # m ahead
    lat: float  # m right
    vlon: float = 0.0  # relative m/s (+ moves ahead)
    vlat: float = 0.0  # relative m/s (+ moves right)
    yaw_deg: float = 0.0
    up: float = 0.0
    status: tuple[int, int, int] = (0, 4, 2)  # pitStatus, driverStatus, resultStatus


def row(x: float, y: float, z: float, vx: float, vy: float, vz: float, yaw_deg: float) -> tuple[float, ...]:
    h = math.radians(yaw_deg)
    return (
        x,
        y,
        z,
        vx,
        vy,
        vz,
        round(32767 * math.sin(h)),
        0.0,
        round(32767 * math.cos(h)),
        round(-32767 * math.cos(h)),
        0.0,
        round(32767 * math.sin(h)),
    )


def motion(
    t: float,
    cars: Mapping[int, Car],
    *,
    speed: float = PLAYER_SPEED,
    player_status: tuple[int, int, int] = (0, 4, 2),
    lap: bool = True,
    t_recv_ns: int | None = None,
    player: int = 0,
) -> DecodedMotion:
    rows: list[tuple[float, ...]] = [EMPTY] * N_CARS
    rows[player] = row(0.0, 0.0, 0.0, 0.0, 0.0, speed, 0.0)
    status = [(0, 0, 0)] * N_CARS
    status[player] = player_status
    for i, c in cars.items():
        rows[i] = row(-c.lat, c.up, c.lon, -c.vlat, 0.0, speed + c.vlon, c.yaw_deg)
        status[i] = c.status
    return DecodedMotion(
        t_recv_ns=t_recv_ns if t_recv_ns is not None else int(1e12 + t * 1e9),
        session_time_s=t,
        frame_id=round(t * 60),
        player_index=player,
        packet_format=2025,
        cars=tuple(rows),
        status=tuple(status) if lap else None,
    )


def race_info(
    *, session_type: int = 15, safety_car: str | None = "none", paused: bool = False, formula: str = "F1 Modern"
) -> SessionInfo:
    return SessionInfo(
        game=Game.F1_25,
        safety_car_status=safety_car,
        formula=formula,
        extra={"session_type_id": session_type, "game_paused": paused, "is_spectating": False},
    )


def engine(settings: SpotterSettings | None = None, **info: object) -> SpotterEngine:
    e = SpotterEngine(settings or SpotterSettings(enabled=True))
    e.feed_session(race_info(**info))  # type: ignore[arg-type]
    return e


def run(
    e: SpotterEngine,
    cars_at: Callable[[float], Mapping[int, Car]],
    t0: float,
    t1: float,
    hz: float = 60.0,
    **kw: object,
) -> list[SpotterCall]:
    """Feed packets from t0 to t1 (inclusive) at ``hz``; return every call."""
    out: list[SpotterCall] = []
    n = round((t1 - t0) * hz)
    for i in range(n + 1):
        t = t0 + i / hz
        out.extend(e.feed_motion(motion(t, cars_at(t), **kw), int(t * 1e9)))  # type: ignore[arg-type]
    return out


def kinds(calls: list[SpotterCall]) -> list[str]:
    return [c.kind for c in calls]


def passing(lat: float, v: float, start_lon: float, t_start: float = 0.0) -> Callable[[float], dict[int, Car]]:
    """One car (slot 1) moving past at relative speed ``v`` from ``start_lon``."""

    def f(t: float) -> dict[int, Car]:
        return {1: Car(start_lon + v * (t - t_start), lat, vlon=v)}

    return f
