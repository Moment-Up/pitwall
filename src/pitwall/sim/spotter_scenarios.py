"""Synthetic F1 25 streams for the spotter (SYNTHETIC - never evidence of game compatibility).

Each scenario puts the player on a straight (world +Z, at ``speed_mps``) or on a constant-radius corner
(``yaw_rate_dps``), and moves other cars around it on known paths given RELATIVE to the player's direction of travel
(``lon`` metres ahead, ``lat`` metres to the right, keyframes linearly interpolated; their world velocities are the
exact derivatives, so a car holding station in a corner turns with the player), with the expected spotter calls.
``player_slip_deg`` turns the player's body away from its direction of travel (a spin). Packets are encoded with the
same spec-checked ``StructDef``s the decoder uses (Motion, LapData, Session, Event), with ``worldRightDir = (-cos h, 0,
sin h)`` for heading ``h``: the real game's convention (forward x right points down; docs/research/f1-spotter-data.md),
so ``lat`` > 0 is world -X on the straight.

Streams carry ``SYNTHETIC_SESSION_UID`` and are flagged synthetic everywhere. The F1 stream generator
(``sim.f1_stream``) is not used: it encodes no right vector, and these scenarios need exact relative motion.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from pitwall.adapters.f1 import packets as P
from pitwall.ingest.capture import CapturedPacket, CaptureMeta, write_capture
from pitwall.model.synthetic import SYNTHETIC_SESSION_UID
from pitwall.spotter.geometry import pack_row
from pitwall.spotter.model import (
    CAR_LEFT,
    CAR_RIGHT,
    CLEAR_ALL_ROUND,
    CLEAR_LEFT,
    CLEAR_RIGHT,
    HOLD_YOUR_LINE,
    STILL_THERE,
    THREE_WIDE,
)

Keys = Sequence[tuple[float, float]]  # (session time s, value), linearly interpolated, held outside the range
PLAYER = 0
SRC_PORT = 52000


def _at(keys: Keys, t: float) -> float:
    ts = [k[0] for k in keys]
    vs = [k[1] for k in keys]
    return float(np.interp(t, ts, vs))


@dataclass(slots=True)
class CarPath:
    """One other car, relative to the player."""

    index: int
    lon: Keys  # metres ahead (centre to centre)
    lat: Keys  # metres to the player's right
    yaw_deg: Keys = ((0.0, 0.0),)  # heading relative to the player's (90 = spun sideways)
    up_m: float = 0.0  # height above the player (a crossover bridge)
    pit_status: int = 0
    driver_status: int = 4  # on track
    result_status: int = 2  # active


@dataclass(slots=True)
class SpotterScenario:
    name: str
    description: str
    cars: tuple[CarPath, ...]
    expected: tuple[str, ...]  # call kinds, in order
    duration_s: float = 10.0
    rate_hz: float = 60.0
    speed_mps: float = 60.0  # the player's speed (constant, or ``speed_keys``)
    speed_keys: Keys | None = None  # the player's speed over time (m/s), instead of ``speed_mps``
    yaw_rate_dps: float = 0.0  # the player's direction of travel turns at this rate (+ left, - right): a corner
    player_slip_deg: Keys = ((0.0, 0.0),)  # the player's heading minus its direction of travel (a spin)
    session_type: int = 15  # Race
    formula: int = 0  # F1 Modern
    packet_format: int = P.PACKET_FORMAT_2025
    safety_car: Keys = ((0.0, 0.0),)  # Session.safetyCarStatus over time (step: the value at or before t)
    lights_out_s: float | None = None  # LGOT at this session time (None: joined after the start)
    flashback: tuple[float, float] | None = None  # (at session time, rewound to)
    start_ns: int = 2_000_000_000_000
    expected_sides: tuple[str | None, ...] = field(default_factory=tuple)


def _step(keys: Keys, t: float) -> int:
    v = keys[0][1]
    for kt, kv in keys:
        if kt <= t:
            v = kv
    return int(v)


class _Gen:
    def __init__(self, sc: SpotterScenario) -> None:
        self.sc = sc
        self.layout = P.LAYOUTS[sc.packet_format]
        self.frame = 0
        self.overall = 0

    def header(self, pid: P.PacketId, t: float) -> bytes:
        sc = self.sc
        return P.HEADER.pack(
            {
                "packetFormat": sc.packet_format,
                "gameYear": 25,
                "gameMajorVersion": 1,
                "gameMinorVersion": 0,
                "packetVersion": 1,
                "packetId": int(pid),
                "sessionUID": SYNTHETIC_SESSION_UID,
                "sessionTime": t,
                "frameIdentifier": self.frame,
                "overallFrameIdentifier": self.overall,
                "playerCarIndex": PLAYER,
                "secondaryPlayerCarIndex": 255,
            }
        )

    def session(self, t: float) -> bytes:
        sc = self.sc
        lay = self.layout
        head = P.SESSION_HEAD.pack(
            {
                "trackLength": 5000,
                "totalLaps": 10,
                "sessionType": sc.session_type,
                "trackId": -1,
                "formula": sc.formula,
                "sessionTimeLeft": 3600,
                "sessionDuration": 3600,
                "pitSpeedLimit": 80,
            }
        )
        marshal = P.MARSHAL_ZONE.pack({}) * P.NUM_MARSHAL_ZONES
        mid = P.SESSION_MID.pack({"safetyCarStatus": _step(sc.safety_car, t), "numWeatherForecastSamples": 0})
        fc = P.WEATHER_FORECAST_SAMPLE.pack({}) * P.NUM_WEATHER_SAMPLES
        tail = lay.session_tail.pack({"gearboxAssist": 3})
        return self.header(P.PacketId.SESSION, t) + head + marshal + mid + fc + tail

    def event(self, code: str, t: float, details: dict[str, object] | None = None) -> bytes:
        sd = self.layout.event_details.get(code)
        body = sd.pack(details or {}) if sd is not None else b""
        return self.header(P.PacketId.EVENT, t) + code.encode() + body.ljust(P.EVENT_DETAILS_SIZE, b"\x00")

    def distance(self, t: float) -> float:
        """The player's distance travelled (m)."""
        sc = self.sc
        if sc.speed_keys is None:
            return sc.speed_mps * t
        if t <= 0:
            return 0.0
        ts = np.linspace(0.0, t, max(2, round(t * 200) + 1))
        vs = np.interp(ts, [k[0] for k in sc.speed_keys], [k[1] for k in sc.speed_keys])
        return float(np.sum((vs[1:] + vs[:-1]) * np.diff(ts)) / 2.0)

    def travel(self, t: float) -> tuple[tuple[float, float, float], float]:
        """The player's position and direction of travel (heading, rad: forward = (sin h, 0, cos h))."""
        sc = self.sc
        d = self.distance(t)
        if not sc.yaw_rate_dps:
            return (0.0, 0.0, d), 0.0
        w = math.radians(sc.yaw_rate_dps)
        speed = sc.speed_mps if sc.speed_keys is None else _at(sc.speed_keys, t)
        h = w * t
        radius = speed / w  # constant speed on a corner (``speed_keys`` is for straights)
        return (radius * (1.0 - math.cos(h)), 0.0, radius * math.sin(h)), h

    def place(self, c: CarPath, t: float) -> tuple[float, float, float]:
        """A car's world position from its path relative to the player's direction of travel."""
        (px, _py, pz), h = self.travel(t)
        lon, lat = _at(c.lon, t), _at(c.lat, t)
        f = (math.sin(h), math.cos(h))
        r = (-math.cos(h), math.sin(h))  # the game's right vector for heading h (x, z)
        return (px + lon * f[0] + lat * r[0], c.up_m, pz + lon * f[1] + lat * r[1])

    def lap(self, t: float) -> bytes:
        sc = self.sc
        lay = self.layout
        rows = [P.LAP_DATA.pack({}) for _ in range(lay.max_cars)]
        dist = self.distance(t)
        rows[PLAYER] = P.LAP_DATA.pack({"currentLapNum": 1, "lapDistance": dist, "driverStatus": 4, "resultStatus": 2})
        for c in sc.cars:
            rows[c.index] = P.LAP_DATA.pack(
                {
                    "currentLapNum": 1,
                    "lapDistance": dist + _at(c.lon, t),
                    "pitStatus": c.pit_status,
                    "driverStatus": c.driver_status,
                    "resultStatus": c.result_status,
                }
            )
        return self.header(P.PacketId.LAP_DATA, t) + b"".join(rows) + P.LAP_DATA_TAIL.pack({})

    def motion(self, t: float) -> bytes:
        sc = self.sc
        lay = self.layout
        empty = lay.car_motion.pack({})
        rows = [empty] * lay.max_cars
        e = 1e-3  # velocities: central differences of the exact paths

        def row(pos: tuple[float, float, float], vel: tuple[float, ...], heading: float) -> bytes:
            fwd = (math.sin(heading), 0.0, math.cos(heading))
            right = (-math.cos(heading), 0.0, math.sin(heading))
            return pack_row((*pos, *vel, *(32767 * x for x in fwd), *(32767 * x for x in right)), sc.packet_format)

        (p0, h) = self.travel(t)
        a, _ = self.travel(t - e)
        b, _ = self.travel(t + e)
        vel = tuple((b[i] - a[i]) / (2 * e) for i in range(3))
        rows[PLAYER] = row(p0, vel, h + math.radians(_at(sc.player_slip_deg, t)))
        for c in sc.cars:
            a, b = self.place(c, t - e), self.place(c, t + e)
            cvel = tuple((b[i] - a[i]) / (2 * e) for i in range(3))
            rows[c.index] = row(self.place(c, t), cvel, h + math.radians(_at(c.yaw_deg, t)))
        return self.header(P.PacketId.MOTION, t) + b"".join(rows)


def _times(sc: SpotterScenario) -> Iterator[tuple[float, bool]]:
    """(session time, after a flashback) of every frame; a flashback rewinds the clock once."""
    dt = 1.0 / sc.rate_hz
    n = round(sc.duration_s * sc.rate_hz)
    fb = sc.flashback
    for i in range(n + 1):
        t = i * dt
        if fb is not None and t > fb[0]:
            break
        yield t, False
    if fb is not None:
        at, to = fb
        n2 = round((sc.duration_s - at) * sc.rate_hz)
        for i in range(1, n2 + 1):
            yield to + i * dt, True


def generate(sc: SpotterScenario) -> list[CapturedPacket]:
    """The scenario as received packets (Session every 0.5 s and at a safety-car change; LapData then Motion every
    frame, as F1 25 sends them; LGOT and FLBK events)."""
    g = _Gen(sc)
    out: list[CapturedPacket] = []
    t_ns = sc.start_ns
    dt_ns = round(1e9 / sc.rate_hz)
    last_session = -1e9
    last_sc: int | None = None
    lights_done = sc.lights_out_s is None
    fb_done = False

    def emit(data: bytes) -> None:
        nonlocal t_ns
        t_ns += 50_000  # 50 us between packets of a frame
        out.append(CapturedPacket(t_ns, SRC_PORT, data))

    for t, after_fb in _times(sc):
        if after_fb and not fb_done:
            fb_done = True
            assert sc.flashback is not None
            emit(
                g.event(
                    "FLBK",
                    sc.flashback[0],
                    {"flashbackFrameIdentifier": 0, "flashbackSessionTime": sc.flashback[1]},
                )
            )
        sc_now = _step(sc.safety_car, t)
        if t - last_session >= 0.5 or sc_now != last_sc or t < last_session:
            emit(g.session(t))
            last_session, last_sc = t, sc_now
        if not lights_done and sc.lights_out_s is not None and t >= sc.lights_out_s:
            emit(g.event("LGOT", t))
            lights_done = True
        emit(g.lap(t))
        emit(g.motion(t))
        g.frame += 1
        g.overall += 1
        t_ns += dt_ns
    return out


def _lr(lat: float) -> Keys:
    return ((0.0, lat),)


# ---------------------------------------------------------------------------------------------- the scenarios
def scenarios() -> list[SpotterScenario]:
    """Spec section 11.3 (a)-(m), with the calls each must produce (in order)."""
    left_pass = CarPath(1, lon=((0.0, -20.0), (10.0, 30.0)), lat=_lr(-3.2))
    return [
        SpotterScenario(
            "a_pass_left",
            "a car passes on the left at +5 m/s",
            (left_pass,),
            (CAR_LEFT, CLEAR_LEFT),
            duration_s=8.0,
        ),
        SpotterScenario(
            "b_three_wide_middle",
            "three wide with the player in the middle: left first, the right car leaves first",
            (
                CarPath(1, lon=((0.0, -12.0), (1.0, -5.0), (3.5, -2.0), (4.5, 8.0), (5.5, 15.0)), lat=_lr(-3.2)),
                CarPath(2, lon=((0.0, 20.0), (2.0, 4.0), (3.5, 2.0), (4.0, 12.0), (6.0, 25.0)), lat=_lr(3.2)),
            ),
            (CAR_LEFT, THREE_WIDE, CLEAR_RIGHT, CLEAR_ALL_ROUND),
            duration_s=7.0,
        ),
        SpotterScenario(
            "c_outside_of_three_wide",
            "the player on the outside of a three-wide (two cars on the right): one car right, one clear",
            (
                CarPath(1, lon=((0.0, -15.0), (6.0, 15.0)), lat=_lr(3.2)),
                CarPath(2, lon=((0.0, -15.5), (6.0, 14.5)), lat=_lr(6.4)),
            ),
            (CAR_RIGHT, CLEAR_RIGHT),
            duration_s=7.0,
        ),
        SpotterScenario(
            "d_nose_to_tail",
            "a car nose to tail, in line: no calls",
            (CarPath(1, lon=((0.0, -9.0), (4.0, -5.7), (8.0, -6.0)), lat=_lr(0.3)),),
            (),
            duration_s=8.0,
        ),
        SpotterScenario(
            "e_boundary_hover",
            "a car hovering at the overlap boundary (+-0.5 m at 1 Hz): one call, no flapping",
            (
                CarPath(
                    1,
                    lon=tuple((i * 0.05, -5.5 - 0.5 * math.cos(2 * math.pi * i * 0.05)) for i in range(241)),
                    lat=_lr(-3.2),
                ),
            ),
            (CAR_LEFT, STILL_THERE, STILL_THERE),
            duration_s=12.0,
        ),
        SpotterScenario(
            "f_squeeze",
            "side by side, then the car squeezes the player: hold your line",
            (
                CarPath(
                    1,
                    lon=((0.0, 0.0), (3.2, 0.0), (4.2, 12.0)),
                    lat=((0.0, -3.0), (1.5, -3.0), (2.6, -1.95), (3.2, -1.95)),  # ~1 m/s in, to contact
                ),
            ),
            (CAR_LEFT, HOLD_YOUR_LINE, CLEAR_LEFT),
            duration_s=6.0,
        ),
        SpotterScenario(
            "g_bridge",
            "a car on a crossover bridge 8 m above: no calls",
            (CarPath(1, lon=((0.0, -20.0), (8.0, 20.0)), lat=_lr(-3.2), up_m=8.0),),
            (),
            duration_s=8.0,
        ),
        SpotterScenario(
            "h_pit_lane",
            "a car in the pit lane beside the straight (pitStatus 1): no calls",
            (CarPath(1, lon=((0.0, 20.0), (8.0, -20.0)), lat=_lr(-6.0), pit_status=1),),
            (),
            duration_s=8.0,
        ),
        SpotterScenario(
            "i_safety_car",
            "a safety car starts during an overlap: silent, no clear",
            (CarPath(1, lon=((0.0, 0.0), (8.0, 0.0)), lat=_lr(-3.2)),),
            (CAR_LEFT,),
            duration_s=8.0,
            safety_car=((0.0, 0.0), (2.0, 1.0)),
        ),
        SpotterScenario(
            "j_flashback",
            "a flashback during an overlap: reset, 1 s mute, the same car called again",
            (CarPath(1, lon=((0.0, 0.0), (10.0, 0.0)), lat=_lr(-3.2)),),
            (CAR_LEFT, CAR_LEFT),
            duration_s=5.0,
            flashback=(3.0, 1.0),
        ),
        SpotterScenario(
            "l_spun_car",
            "the player passes a car spun sideways",
            (CarPath(1, lon=((0.0, 8.0), (3.0, -8.0)), lat=_lr(-4.0), yaw_deg=((0.0, 90.0),)),),
            (CAR_LEFT, CLEAR_LEFT),
            duration_s=5.0,
        ),
        SpotterScenario(
            "m_time_trial",
            "time trial with a ghost car alongside: never",
            (CarPath(1, lon=((0.0, -20.0), (10.0, 30.0)), lat=_lr(-3.2)),),
            (),
            duration_s=8.0,
            session_type=18,
        ),
        SpotterScenario(
            "n_start",
            "lights out with a car alongside: silent for the start delay, then called",
            (CarPath(1, lon=((0.0, 0.5), (12.0, 0.5)), lat=_lr(-3.2)),),
            (CAR_LEFT,),
            duration_s=6.0,
            lights_out_s=0.0,
        ),
        SpotterScenario(
            "o_corner_side_by_side",
            "three wide through a 100 m right-hander, both cars holding a constant 0.2 m gap (one ahead, one"
            " behind): nothing closes in the player's turning frame, so no hold your line (without the frame's"
            " rotation both read as closing at 1 m/s)",
            (
                CarPath(1, lon=_lr(2.0), lat=_lr(-2.2)),
                CarPath(2, lon=_lr(-2.0), lat=_lr(2.2)),
            ),
            (THREE_WIDE,),
            duration_s=3.9,
            speed_mps=50.0,
            yaw_rate_dps=-math.degrees(0.5),  # 50 m/s on a 100 m radius, turning right
        ),
        SpotterScenario(
            "p_spin",
            "a car alongside, then the player spins (360 degrees in 1 s): silent from the slide until 0.3 s after"
            " it ends, then the car is called again (a new episode)",
            (CarPath(1, lon=_lr(0.0), lat=_lr(-3.2)),),
            (CAR_LEFT, CAR_LEFT),
            duration_s=5.0,
            speed_mps=25.0,
            player_slip_deg=((0.0, 0.0), (2.0, 0.0), (3.0, 360.0)),
        ),
        SpotterScenario(
            "q_slow_clear",
            "a car alongside drops back as the player slows below 20 km/h: the gate closes before the clear's"
            " 150 ms, and the clear is still said (the positions are valid)",
            (CarPath(1, lon=((0.0, 0.0), (1.9, 0.0), (2.1, -9.0)), lat=_lr(-3.2)),),  # gone at 2.06 s
            (CAR_LEFT, CLEAR_LEFT),
            duration_s=4.0,
            speed_keys=((0.0, 10.0), (2.0, 10.0), (2.2, 5.0)),
        ),
    ]


def at_rate(sc: SpotterScenario, rate_hz: float) -> SpotterScenario:
    """(k) the same scenario at another send rate (the game's 20 Hz default, or 10 Hz)."""
    return dataclasses.replace(sc, name=f"{sc.name}@{rate_hz:g}Hz", rate_hz=rate_hz)


def by_name(name: str) -> SpotterScenario:
    for sc in scenarios():
        if sc.name == name:
            return sc
    raise KeyError(name)


def write_capture_file(path: Path, sc: SpotterScenario, start_ns: int | None = None) -> int:
    """Write the scenario as a SYNTHETIC ``.pwcap`` (receive stamps from ``start_ns``: pass ``recv_clock_ns()`` for
    a real-time replay whose latency stamps are on this process's clock). Returns the packet count."""
    if start_ns is not None:
        sc = dataclasses.replace(sc, start_ns=start_ns)
    meta = CaptureMeta(
        source="synthetic",
        game_hint="f1_25",
        synthetic=True,
        description=f"SYNTHETIC F1 25 spotter scenario '{sc.name}' - not real game output",
        extra={"scenario": f"spotter-{sc.name}", "track_name": "synthetic straight"},
    )
    return write_capture(path, generate(sc), meta)
