"""Builders for the race strategy tests (``pitwall.strategy``): F1 packets and strategy items with known values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from pitwall.adapters.f1 import packets as P
from pitwall.model.telemetry import (
    CarFrame,
    CarTiming,
    FrameQuality,
    Game,
    LapCompletion,
    RaceTiming,
    SessionInfo,
    SessionType,
    TyreSet,
    TyreSetsInfo,
    Weather,
    Wheels,
)

UID = 4242
PLAYER = 1


# ---------------------------------------------------------------------------------------------------- packets
def header(pid: P.PacketId, t: float, fmt: int = 2025, frame: int = 1, player: int = PLAYER, uid: int = UID) -> bytes:
    return P.HEADER.pack(
        {
            "packetFormat": fmt,
            "gameYear": 25,
            "gameMajorVersion": 1,
            "gameMinorVersion": 26,
            "packetVersion": 1,
            "packetId": int(pid),
            "sessionUID": uid,
            "sessionTime": t,
            "frameIdentifier": frame,
            "overallFrameIdentifier": frame,
            "playerCarIndex": player,
            "secondaryPlayerCarIndex": 255,
        }
    )


def lap_packet(
    t: float, cars: Mapping[int, Mapping[str, object]], fmt: int = 2025, frame: int = 1, player: int = PLAYER
) -> bytes:
    layout = P.LAYOUTS[fmt]
    rows = b"".join(P.LAP_DATA.pack(cars.get(i, {})) for i in range(layout.max_cars))
    tail = P.LAP_DATA_TAIL.pack({"timeTrialPBCarIdx": 255, "timeTrialRivalCarIdx": 255})
    return header(P.PacketId.LAP_DATA, t, fmt, frame, player) + rows + tail


def status_packet(t: float, cars: Mapping[int, Mapping[str, object]], fmt: int = 2025) -> bytes:
    layout = P.LAYOUTS[fmt]
    rows = b"".join(layout.car_status.pack(cars.get(i, {})) for i in range(layout.max_cars))
    return header(P.PacketId.CAR_STATUS, t, fmt) + rows


def session_packet(
    t: float, session_type: int = 15, fmt: int = 2025, *, total_laps: int = 10, sc: int = 0, forecast=None
) -> bytes:
    layout = P.LAYOUTS[fmt]
    head = P.SESSION_HEAD.pack(
        {
            "weather": 1,
            "trackTemperature": 33,
            "airTemperature": 22,
            "totalLaps": total_laps,
            "trackLength": 4318,
            "sessionType": session_type,
            "trackId": 17,
        }
    )
    marshal = P.MARSHAL_ZONE.pack({}) * P.NUM_MARSHAL_ZONES
    fc = forecast or [{"sessionType": session_type, "timeOffset": 0, "weather": 1, "rainPercentage": 7}]
    mid = P.SESSION_MID.pack({"safetyCarStatus": sc, "numWeatherForecastSamples": len(fc)})
    fcb = b"".join(P.WEATHER_FORECAST_SAMPLE.pack(s) for s in fc) + P.WEATHER_FORECAST_SAMPLE.pack({}) * (
        P.NUM_WEATHER_SAMPLES - len(fc)
    )
    tail = layout.session_tail.pack(
        {
            "forecastAccuracy": 1,
            "pitStopRejoinPosition": 7,
            "numSafetyCarPeriods": 2,
            "numVirtualSafetyCarPeriods": 1,
            "numRedFlagPeriods": 0,
        }
    )
    return header(P.PacketId.SESSION, t, fmt) + head + marshal + mid + fcb + tail


def tyre_sets_packet(
    t: float, sets: Sequence[Mapping[str, object]], car_idx: int = PLAYER, fitted_idx: int = 0, uid: int = UID
) -> bytes:
    rows = [P.TYRE_SET.pack(sets[i]) if i < len(sets) else P.TYRE_SET.pack({}) for i in range(P.NUM_TYRE_SETS)]
    return (
        header(P.PacketId.TYRE_SETS, t, uid=uid)
        + P.TYRE_SETS_HEAD.pack({"carIdx": car_idx})
        + b"".join(rows)
        + P.TYRE_SETS_TAIL.pack({"fittedIdx": fitted_idx})
    )


# ---------------------------------------------------------------------------------------------------- items
def car(
    idx: int,
    pos: int,
    *,
    lap: int = 5,
    dist: float = 1000.0,
    gap_ms: int | None = 1000,
    leader_ms: int | None = None,
    pit: int = 0,
    stops: int = 0,
    last_ms: int | None = None,
    player: bool = False,
    result: str = "active",
    lane_ms: int | None = None,
    stop_ms: int | None = None,
    pen: bool = False,
    tyre: str | None = "medium",
    age: int | None = 5,
) -> CarTiming:
    return CarTiming(
        car_index=idx,
        is_player=player,
        ai_controlled=not player,
        position=pos,
        grid_position=pos,
        lap_number=lap,
        lap_distance_m=dist,
        sector=0,
        last_lap_ms=last_ms,
        gap_ahead_ms=gap_ms,
        gap_leader_ms=leader_ms if leader_ms is not None else (None if pos == 1 else (pos - 1) * 1000),
        pit_status=pit,
        num_pit_stops=stops,
        pit_lane_timer_active=bool(pit),
        pit_lane_time_ms=lane_ms if pit else None,
        pit_stop_timer_ms=stop_ms,
        serve_penalty=pen,
        driver_status="on_track",
        result_status=result,
        lap_invalid=False,
        tyre_visual=tyre,
        tyre_age_laps=age,
    )


def timing(t: float, cars: Sequence[CarTiming], player: int = PLAYER) -> RaceTiming:
    return RaceTiming(
        game=Game.F1_25,
        t_recv_ns=int(t * 1e9),
        session_time_s=t,
        frame_id=int(t * 60),
        player_index=player,
        cars=tuple(cars),
    )


def with_(c: CarTiming, **kw: Any) -> CarTiming:
    return replace(c, **kw)


def session(
    session_type: SessionType = SessionType.RACE,
    total_laps: int = 10,
    sc: str | None = "none",
    game: Game = Game.F1_25,
    forecast: list[dict[str, Any]] | None = None,
    weather: str = "clear",
    rain: float | None = 5.0,
    **extra: Any,
) -> SessionInfo:
    return SessionInfo(
        game=game,
        session_uid=str(UID),
        track_id="f1:17",
        track_length_m=4318.0,
        session_type=session_type,
        total_laps=total_laps,
        safety_car_status=sc,
        weather=Weather(condition=weather, track_temp_c=33.0, air_temp_c=22.0, rain_percentage=rain),
        extra={
            "packet_format": 2025,
            "session_type_id": 15 if session_type is SessionType.RACE else 1,
            "forecast": forecast or [],
            "forecast_accuracy": 0,
            "pit_rejoin_position": 0,
            **extra,
        },
    )


def frame(
    t: float,
    lap: int,
    dist: float,
    *,
    fuel: float | None = 20.0,
    wear: tuple[float, float, float, float] | None = (10.0, 10.0, 10.0, 10.0),
    compound: str = "medium",
    age: int = 5,
    pit: int = 0,
    throttle: float = 1.0,
    speed: float = 250.0,
    game_margin: float | None = 1.0,
    quality: FrameQuality = FrameQuality.OK,
) -> CarFrame:
    return CarFrame(
        game=Game.F1_25,
        t_recv_ns=int(t * 1e9),
        session_time_s=t,
        quality=quality,
        throttle=throttle,
        brake=0.0,
        steering=0.0,
        speed_kph=speed,
        lap_number=lap,
        lap_distance_m=dist,
        pit_status=pit,
        fuel_kg=fuel,
        fuel_remaining_laps_game=game_margin,
        tyre_wear_pct=None if wear is None else Wheels(*wear),
        tyre_compound=compound,
        tyre_age_laps=age,
    )


def completion(lap: int, ms: int, t: float) -> LapCompletion:
    return LapCompletion(game=Game.F1_25, t_recv_ns=int(t * 1e9), lap_number=lap, lap_time_ms=ms, session_time_s=t)


def tyre_set(
    index: int,
    visual: str,
    *,
    life: int = 20,
    usable: int = 20,
    delta_ms: int = 0,
    wear: int = 0,
    available: bool = True,
    fitted: bool = False,
) -> TyreSet:
    return TyreSet(
        index=index,
        actual=None,
        visual=visual,
        wear_pct=wear,
        available=available,
        recommended_session=15,
        life_span_laps=life,
        usable_life_laps=usable,
        lap_delta_ms=delta_ms,
        fitted=fitted,
    )


def tyre_sets(t: float, sets: Sequence[TyreSet], fitted: int | None = 0) -> TyreSetsInfo:
    return TyreSetsInfo(
        game=Game.F1_25,
        t_recv_ns=int(t * 1e9),
        session_time_s=t,
        car_index=PLAYER,
        sets=tuple(sets),
        fitted_index=fitted,
    )


def laps_meta(
    rows: Sequence[tuple[int, float, float, tuple[float, ...], tuple[float, ...], str, int]],
    flags: Mapping[int, list[str]] | None = None,
) -> list[dict[str, Any]]:
    """Stored-lap shape: (lap, fuel_start, fuel_end, wear_start, wear_end, compound, age)."""
    flags = flags or {}
    return [
        {
            "lap_number": n,
            "flags": flags.get(n, []),
            "meta": {
                "fuel_start_kg": fs,
                "fuel_end_kg": fe,
                "wear_start": list(ws),
                "wear_end": list(we),
                "tyre_compound": comp,
                "tyre_age_laps": age,
            },
        }
        for n, fs, fe, ws, we, comp, age in rows
    ]
