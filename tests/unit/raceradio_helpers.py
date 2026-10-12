"""Builders for the race radio unit tests: hand-made items in receive-time seconds (test data, not game output)."""

from __future__ import annotations

from typing import Any

from pitwall.model.telemetry import (
    CarDamage,
    CarFrame,
    CarPenalties,
    CarTiming,
    EventKind,
    FrameQuality,
    Game,
    GameEvent,
    LapCompletion,
    MarshalZone,
    Participant,
    Participants,
    RaceTiming,
    SessionInfo,
    SessionType,
    TrackZones,
    Wheels,
)
from pitwall.raceradio.engine import RaceRadioEngine
from pitwall.raceradio.model import RaceCall

PLAYER = 3
L = 5000.0
EVENT_KINDS = {
    "SSTA": EventKind.SESSION_STARTED,
    "SEND": EventKind.SESSION_ENDED,
    "FTLP": EventKind.FASTEST_LAP,
    "FLBK": EventKind.FLASHBACK,
    "PENA": EventKind.PENALTY,
    "SCAR": EventKind.SAFETY_CAR,
    "RDFL": EventKind.RED_FLAG,
    "CHQF": EventKind.CHEQUERED_FLAG,
    "LGOT": EventKind.LIGHTS_OUT,
    "COLL": EventKind.COLLISION,
}


def ns(t: float) -> int:
    return round(t * 1e9)


def info(
    t: float,
    *,
    game: Game = Game.F1_25,
    stype: SessionType = SessionType.RACE,
    total_laps: int | None = 10,
    sc: str | None = "none",
    zones: list[tuple[float, str | None]] | None = None,
    time_left: float | None = 7200.0,
    uid: str = "42",
    extra: dict[str, Any] | None = None,
    length: float | None = L,
) -> SessionInfo:
    tz = None
    if zones is not None:
        tz = TrackZones(
            source="f1_session@2025",
            sector2_start_m=L / 3,
            sector3_start_m=2 * L / 3,
            marshal_zones=tuple(MarshalZone(start_frac=f, flag=flag) for f, flag in zones),
        )
    return SessionInfo(
        game=game,
        t_recv_ns=ns(t),
        session_uid=uid,
        track_id="f1:17",
        track_length_m=length,
        session_type=stype,
        total_laps=total_laps,
        session_time_left_s=time_left,
        safety_car_status=sc,
        track_zones=tz,
        extra=dict(extra or {}),
    )


def frame(
    t: float,
    *,
    lap: int | None = 2,
    d: float | None = 1000.0,
    speed: float | None = 250.0,
    pos: int | None = 5,
    pit: int | None = 0,
    fia: str | None = "none",
    brake: float = 0.0,
    steer: float = 0.0,
    quality: FrameQuality = FrameQuality.OK,
    damage: CarDamage | None = None,
    penalties: CarPenalties | None = None,
    game: Game = Game.F1_25,
) -> CarFrame:
    return CarFrame(
        game=game,
        t_recv_ns=ns(t),
        quality=quality,
        speed_kph=speed,
        brake=brake,
        steering=steer,
        lap_number=lap,
        lap_distance_m=d,
        race_position=pos,
        pit_status=pit,
        fia_flag=fia,
        damage=damage,
        penalties=penalties,
    )


def event(t: float, code: str, **payload: Any) -> GameEvent:
    return GameEvent(
        kind=EVENT_KINDS.get(code, EventKind.OTHER),
        game=Game.F1_25,
        t_recv_ns=ns(t),
        code=code,
        payload={"player_idx": PLAYER, **payload},
    )


def lap_done(t: float, lap: int, *, final: bool | None = None, game: Game = Game.F1_25) -> LapCompletion:
    return LapCompletion(game=game, t_recv_ns=ns(t), lap_number=lap, lap_time_ms=90_000, final=final)


def car(
    idx: int,
    pos: int,
    *,
    lap: int = 2,
    d: float = 1000.0,
    gap_ms: int | None = 1500,
    pit: int = 0,
    result: str = "active",
) -> CarTiming:
    return CarTiming(
        car_index=idx,
        is_player=idx == PLAYER,
        ai_controlled=idx != PLAYER,
        position=pos,
        grid_position=None,
        lap_number=lap,
        lap_distance_m=d,
        sector=0,
        last_lap_ms=None,
        gap_ahead_ms=gap_ms,
        gap_leader_ms=None if pos == 1 else 5000,
        pit_status=pit,
        num_pit_stops=0,
        pit_lane_timer_active=False,
        pit_lane_time_ms=None,
        pit_stop_timer_ms=None,
        serve_penalty=False,
        driver_status="on_track",
        result_status=result,
        lap_invalid=False,
    )


def timing(t: float, cars: list[CarTiming], session_time: float | None = None) -> RaceTiming:
    return RaceTiming(
        game=Game.F1_25,
        t_recv_ns=ns(t),
        session_time_s=t if session_time is None else session_time,
        frame_id=int(t * 60),
        player_index=PLAYER,
        cars=tuple(cars),
    )


def damage(
    *,
    fl: int = 0,
    fr: int = 0,
    rw: int = 0,
    floor: int = 0,
    diffuser: int = 0,
    sidepod: int = 0,
    gearbox: int = 0,
    engine: int = 0,
    brakes: tuple[int, int, int, int] = (0, 0, 0, 0),
    tyres: tuple[int, int, int, int] = (0, 0, 0, 0),
    drs: bool = False,
    ers: bool = False,
    blown: bool = False,
) -> CarDamage:
    """Wheel tuples in FL, FR, RL, RR order."""
    return CarDamage(
        front_left_wing_pct=fl,
        front_right_wing_pct=fr,
        rear_wing_pct=rw,
        floor_pct=floor,
        diffuser_pct=diffuser,
        sidepod_pct=sidepod,
        gearbox_pct=gearbox,
        engine_pct=engine,
        brakes_pct=Wheels.from_fl_fr_rl_rr(brakes),
        tyres_pct=Wheels.from_fl_fr_rl_rr(tyres),
        drs_fault=drs,
        ers_fault=ers,
        engine_blown=blown,
        engine_seized=False,
    )


def pens(*, time_s: int = 0, warnings: int = 0, cc: int = 0, dt: int = 0, sg: int = 0) -> CarPenalties:
    return CarPenalties(
        time_penalties_s=time_s,
        warnings=warnings,
        corner_cutting_warnings=cc,
        unserved_drive_throughs=dt,
        unserved_stop_gos=sg,
        serve_at_stop=False,
    )


def participants(t: float, cars: list[Participant]) -> Participants:
    return Participants(game=Game.F1_25, t_recv_ns=ns(t), session_time_s=t, player_index=PLAYER, cars=tuple(cars))


def participant(
    idx: int,
    *,
    ai: bool | None = True,
    driver: int | None = 54,
    team: int | None = 8,
    number: int | None = 4,
    name: str,
) -> Participant:
    return Participant(
        car_index=idx,
        ai_controlled=ai,
        driver_id=driver,
        team_id=team,
        race_number=number,
        name=name,
        show_online_names=False,
    )


class Run:
    """An engine and the calls it made, fed item by item."""

    def __init__(self, engine: RaceRadioEngine | None = None) -> None:
        self.engine = engine or RaceRadioEngine("s1", clock=lambda: 1_760_000_000.0)
        self.calls: list[RaceCall] = []

    def feed(self, *items: object) -> list[RaceCall]:
        new: list[RaceCall] = []
        for it in items:
            self.engine.feed(it)
            new.extend(self.engine.take_calls())
        self.calls.extend(new)
        return new

    def drive(
        self, t0: float, t1: float, *, hz: float = 10.0, **kw: Any
    ) -> list[RaceCall]:  # frames at hz with fixed fields
        out: list[RaceCall] = []
        n = round((t1 - t0) * hz)
        for i in range(n + 1):
            out.extend(self.feed(frame(t0 + i / hz, **kw)))
        return out

    def named(self, call: str) -> list[RaceCall]:
        return [c for c in self.calls if c.call == call]

    @property
    def names(self) -> list[str]:
        return [c.call for c in self.calls]


def race(t: float = 0.0, **kw: Any) -> Run:
    """An F1 race engine that has seen its session info."""
    r = Run()
    r.feed(info(t, **kw))
    return r
