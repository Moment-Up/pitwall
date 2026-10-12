"""Builders for the car health tests (``pitwall.carhealth``): frames, session info and laps with known values."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from pitwall.carhealth.engine import CarHealthEngine
from pitwall.model.telemetry import (
    CarFrame,
    EventKind,
    FieldSample,
    FrameQuality,
    Game,
    GameEvent,
    SessionInfo,
    SessionType,
    Wheels,
)

LENGTH = 4000.0


def w4(v: float | tuple[float, float, float, float]) -> Wheels[float]:
    return Wheels(*v) if isinstance(v, tuple) else Wheels(v, v, v, v)


def frame(
    t: float,
    *,
    lap: int = 2,
    d: float = 1000.0,
    surf: float | tuple[float, float, float, float] | None = 80.0,
    inner: float | tuple[float, float, float, float] | None = 90.0,
    pit: int = 0,
    speed: float = 200.0,
    brake: float = 0.0,
    throttle: float = 1.0,
    slip: tuple[float, float, float, float] | None = None,
    abs_on: bool | None = False,
    tc: int | None = 1,
    brakes_c: float | tuple[float, float, float, float] | None = 500.0,
    engine_c: float | None = 120.0,
    wear: tuple[float, float, float, float] | None = (10.0, 10.0, 10.0, 10.0),
    pressure: float | None = 23.0,
    invalid: bool = False,
    game: Game = Game.F1_25,
    quality: FrameQuality = FrameQuality.OK,
    compound: str = "medium",
    age: int = 3,
) -> CarFrame:
    return CarFrame(
        game=game,
        t_recv_ns=int(t * 1e9),
        session_time_s=t,
        quality=quality,
        speed_kph=speed,
        throttle=throttle,
        brake=brake,
        steering=0.0,
        lap_number=lap,
        lap_distance_m=d,
        pit_status=pit,
        lap_invalid=invalid,
        tyre_surface_temp_c=None if surf is None else w4(surf),
        tyre_inner_temp_c=None if inner is None else w4(inner),
        tyre_pressure_psi=None if pressure is None else w4(pressure),
        brake_temp_c=None if brakes_c is None else w4(brakes_c),
        engine_temp_c=engine_c,
        tyre_wear_pct=None if wear is None else Wheels(*wear),
        wheel_slip_ratio=None if slip is None else Wheels(*slip),
        abs_active=abs_on,
        traction_control=tc,
        tyre_compound=compound,
        tyre_age_laps=age,
    )


def info(
    *,
    game: Game = Game.F1_25,
    session_type: SessionType = SessionType.RACE,
    model: str | None = "surface_and_carcass",
    sc: str | None = "none",
    total_laps: int = 20,
    t: float = 0.0,
    **extra: Any,
) -> SessionInfo:
    return SessionInfo(
        game=game,
        session_uid="4242",
        track_id="f1:17",
        track_length_m=LENGTH,
        session_type=session_type,
        total_laps=total_laps,
        safety_car_status=sc,
        session_time_s=t,
        extra={"packet_format": 2025, "tyre_temperature_model": model, **extra},
    )


def flashback(t: float, target: float) -> GameEvent:
    return GameEvent(
        kind=EventKind.FLASHBACK,
        game=Game.F1_25,
        t_recv_ns=int(t * 1e9),
        session_time_s=t,
        code="FLBK",
        payload={"flashbackSessionTime": target},
    )


def drive(
    eng: CarHealthEngine,
    t0: float,
    t1: float,
    *,
    hz: float = 10.0,
    lap0: int = 2,
    lap_s: float = 80.0,
    **kw: Any,
) -> float:
    """Feed frames from ``t0`` to ``t1`` (exclusive) at ``hz``; the lap number and distance follow the clock (a lap is
    ``lap_s`` long, starting at ``t0`` at distance 0 of ``lap0``). Returns the next time."""
    t = t0
    step = 1.0 / hz
    while t < t1:
        k = int((t - t0) // lap_s)
        d = (t - t0 - k * lap_s) / lap_s * LENGTH
        eng.feed(frame(t, lap=lap0 + k, d=d, **kw))
        t = round(t + step, 6)
    return t


def ramp(start: float, end: float, n: int) -> Iterator[float]:
    for i in range(n):
        yield start + (end - start) * i / max(1, n - 1)


def field_sample(
    idx: int, t: float, lap: int, d: float, *, pit: int = 0, sc: bool = False, invalid: bool = False
) -> FieldSample:
    return FieldSample(
        game=Game.F1_25,
        t_recv_ns=int(t * 1e9),
        session_time_s=t,
        frame_id=int(t * 60),
        car_index=idx,
        ai_controlled=True,
        lap_number=lap,
        lap_distance_m=d,
        pos_x_m=0.0,
        pos_y_m=0.0,
        pos_z_m=0.0,
        speed_kph=200.0,
        throttle=1.0,
        brake=0.0,
        steering=0.0,
        gear=6,
        sector=0,
        lap_invalid=invalid,
        pit_status=pit,
        driver_status="on_track",
        result_status="active",
        safety_car=sc,
    )


def model(starts: list[float], length: float = LENGTH) -> dict[str, Any]:
    """A track model payload whose corners partition the lap at ``starts`` (``starts[0]`` = 0)."""
    corners = []
    for k, s in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else length
        corners.append(
            {
                "name": f"T{k + 1}",
                "apex_m": (s + end) / 2,
                "entry_m": s,
                "exit_m": end,
                "seg_start_m": s,
                "seg_end_m": end,
                "direction": None,
                "ref_min_speed_kph": 100.0,
            }
        )
    return {"game": "f1_25", "track_id": "f1:17", "length_m": length, "corners": corners}
