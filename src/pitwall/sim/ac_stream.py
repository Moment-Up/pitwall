"""Synthetic Assetto Corsa Remote Telemetry (SYNTHETIC - not real game output).

Two tools, both built on the same encoders the decoder's tests check against the documentation
(``pitwall.adapters.ac.packets``), so generator and decoder cannot drift apart:

* ``generate_ac_session`` - a handshake reply followed by an RTCarInfo stream for laps of a ``pitwall.sim`` track
  driven by a ``pitwall.sim.driver`` profile, with known ground truth (lap times, track length, line position), so
  decode -> ``LapAssembler`` can be tested end to end. ``write_ac_capture`` stores it as a ``.pwcap`` flagged
  ``synthetic=True``.
* ``FakeAcServer`` - a loopback-only stand-in for the game's in-session "ACServer" that answers the handshake,
  honours SUBSCRIBE_UPDATE / DISMISS and streams RTCarInfo. It exists for the client tests and the probe's dry run;
  it refuses to bind anything but a loopback address, so it can never act on the LAN.
* ``LoopbackRedirect`` - a client ``socket_factory`` for tests: the client believes it talks to a LAN console
  (so the private-IP gate and the 1 s LAN rate floor apply) while every datagram goes to a loopback fake server.

Every handshake reply carries ``SYNTHETIC_CAR_NAME`` as the car (and driver) name, which the adapter maps to the
synthetic session uid: generated telemetry is flagged synthetic wherever it travels.

What the generator models, and where it had to choose because AC's behaviour is unverified:

* The session starts ``outlap_fraction`` of a lap before the timing line with ``lapCount = 0`` (completed laps);
  ``lapTime`` counts from the session start on the out-lap and from the line afterwards; ``lastLap`` updates in the
  crossing packet (``last_lap_delay_packets`` delays it to exercise the adapter's hold), ``bestLap`` ignores the
  out-lap. These follow the community reading the adapter implements; they test our logic, not the game.
* ``carPositionNormalized`` is the centreline fraction plus ``spline_offset`` (where the spline origin sits relative
  to the timing line), wrapped to 0..1. The car drives the centreline, so a lap is exactly ``track.length_m`` long.
* ``accG_frontal`` is ``g_frontal_sign`` x longitudinal g (the real sign is undocumented; the adapter learns it).
  ``steer`` is ``steering x steer_scale`` - an arbitrary raw scale, because the real unit is undocumented.
* A pause repeats the last packet unchanged (frozen simulation) while the receive clock advances.
"""

from __future__ import annotations

import ipaddress
import logging
import math
import socket
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from pitwall.adapters.ac import packets as P
from pitwall.compat import ignore_udp_port_unreachable
from pitwall.ingest.ac_client import CAPTURE_GAME_HINT
from pitwall.ingest.capture import CapturedPacket, CaptureMeta, write_capture
from pitwall.sim.driver import DriverProfile, LapProfile, VehicleModel, solve_lap
from pitwall.sim.track import TrackGeometry, pitwall_park

log = logging.getLogger(__name__)

SYNTHETIC_DRIVER_NAME = "PITWALL-SYNTHETIC"
SYNTHETIC_TRACK_NAME = "synthetic-pitwall-park"
GAME_HINT = CAPTURE_GAME_HINT  # what the runtime's replay requires before decoding a capture as AC


@dataclass(slots=True)
class AcPauseSpec:
    at_time_s: float  # stream time (s since the first RTCarInfo) at which the simulation freezes
    duration_s: float = 3.0


@dataclass(slots=True)
class AcScenario:
    flying_laps: int = 3
    outlap_fraction: float = 0.35  # (0, 1): part of a lap driven before the first line crossing
    rate_hz: float = 60.0  # the console's real rate is unknown (PC claims range from 20 to ~333 Hz)
    driver_by_lap: dict[int, DriverProfile] = field(default_factory=dict)  # pitwall lap number -> driver
    default_driver: DriverProfile = field(default_factory=DriverProfile)
    car_name: str = P.SYNTHETIC_CAR_NAME
    driver_name: str = SYNTHETIC_DRIVER_NAME
    track_name: str = SYNTHETIC_TRACK_NAME
    track_config: str = ""
    wide_strings: bool = True  # 408-byte UTF-16 reply (PC); False = 208-byte 8-bit reply
    string_pad: str = "%"
    spline_offset: float = 0.0  # carPositionNormalized at the timing line
    last_lap_delay_packets: int = 0
    g_frontal_sign: float = 1.0
    steer_scale: float = 450.0
    pause: AcPauseSpec | None = None
    send_handshake: bool = True
    rt_lap: bool = False  # also emit RTLap at each crossing (PC SUBSCRIBE_SPOT behaviour)
    cooldown_s: float = 1.0  # driving after the final crossing
    origin_m: tuple[float, float] = (0.0, 0.0)  # world (x, z) of the timing line
    start_ns: int = 1_000_000_000_000
    port: int = P.AC_PORT  # source port of the game's datagrams


@dataclass(slots=True)
class AcTruth:
    """What the generator did, for assertions. Lap numbers are pitwall's (1 = out-lap)."""

    lap_times_ms: dict[int, int] = field(default_factory=dict)  # flying laps, exactly as lastLap reports them
    outlap_time_ms: int = 0
    track: TrackGeometry | None = None
    lap_length_m: float = 0.0
    line_norm: float = 0.0
    packets_car_info: int = 0
    packets_frozen: int = 0


@dataclass(slots=True)
class _Segment:
    profile: LapProfile
    t0_in_profile: float
    duration_s: float
    s0_m: float


def _segments(sc: AcScenario, track: TrackGeometry, vehicle: VehicleModel) -> list[_Segment]:
    if not 0.0 < sc.outlap_fraction < 1.0:
        raise ValueError("outlap_fraction must be in (0, 1): the session must start before a line crossing")
    length = track.length_m
    out_prof = solve_lap(track, vehicle, sc.driver_by_lap.get(1, sc.default_driver), lap_index=1)
    s0 = length * (1.0 - sc.outlap_fraction)
    t0 = float(np.interp(s0, out_prof.s, out_prof.t))
    segs = [_Segment(out_prof, t0, out_prof.lap_time_s - t0, s0)]
    for k in range(1, sc.flying_laps + 1):
        prof = solve_lap(track, vehicle, sc.driver_by_lap.get(k + 1, sc.default_driver), lap_index=k + 1)
        segs.append(_Segment(prof, 0.0, prof.lap_time_s, 0.0))
    cool = solve_lap(track, vehicle, sc.default_driver, lap_index=0)
    segs.append(_Segment(cool, 0.0, max(sc.cooldown_s, 1.0 / sc.rate_hz), 0.0))
    return segs


def _sample(seg: _Segment, track: TrackGeometry, seg_t: float) -> dict[str, float]:
    prof = seg.profile
    pt = seg.t0_in_profile + seg_t
    n = len(prof.t)
    fi = float(np.interp(pt, prof.t, np.arange(n, dtype=np.float64)))
    i = min(int(fi), n - 1)
    j = min(i + 1, n - 1)
    w = fi - i

    def lerp(arr: Any) -> float:
        return float(arr[i] * (1.0 - w) + arr[j] * w)

    s = lerp(prof.s)
    return {
        "s": s,
        "v": lerp(prof.v),
        "throttle": lerp(prof.throttle),
        "brake": lerp(prof.brake),
        "steering": lerp(prof.steering),
        "gear": float(prof.gear[i]),
        "rpm": lerp(prof.rpm),
        "g_lat": lerp(prof.g_lat),
        "g_lon": lerp(prof.g_lon),
        "x": float(np.interp(s, track.s, track.x)),
        "z": float(np.interp(s, track.s, track.z)),
    }


def handshake_reply(sc: AcScenario) -> bytes:
    return P.encode_handshake_response(
        sc.car_name, sc.driver_name, sc.track_name, sc.track_config, wide=sc.wide_strings, pad=sc.string_pad
    )


def generate_ac_session(
    sc: AcScenario | None = None,
    track: TrackGeometry | None = None,
    vehicle: VehicleModel | None = None,
) -> tuple[list[CapturedPacket], AcTruth]:
    sc = sc or AcScenario()
    track = track or pitwall_park()
    vehicle = vehicle or VehicleModel()
    segs = _segments(sc, track, vehicle)
    starts = np.concatenate([[0.0], np.cumsum([sg.duration_s for sg in segs])])
    length = track.length_m
    lap_ms = [round(sg.duration_s * 1000.0) for sg in segs]
    truth = AcTruth(
        track=track,
        lap_length_m=length,
        line_norm=sc.spline_offset % 1.0,
        outlap_time_ms=lap_ms[0],
        lap_times_ms={k + 1: lap_ms[k] for k in range(1, sc.flying_laps + 1)},
    )
    packets: list[CapturedPacket] = []
    dt = 1.0 / sc.rate_hz
    wall = float(sc.start_ns)
    if sc.send_handshake:
        packets.append(CapturedPacket(int(wall) - 1_000_000, sc.port, handshake_reply(sc)))
    t = 0.0
    end_t = float(starts[-1])
    seen_seg = 0
    since_increment = 10**9
    pause_done = sc.pause is None
    ox, oz = sc.origin_m
    last_values: dict[str, Any] | None = None

    while t < end_t - 1e-9:
        if not pause_done and sc.pause is not None and t >= sc.pause.at_time_s and last_values is not None:
            pause_done = True
            frozen = P.encode_rt_car_info(last_values)
            for _ in range(round(sc.pause.duration_s * sc.rate_hz)):
                wall += dt * 1e9
                packets.append(CapturedPacket(int(wall), sc.port, frozen))
                truth.packets_frozen += 1
        k = max(0, min(int(np.searchsorted(starts, t, side="right")) - 1, len(segs) - 1))
        seg = segs[k]
        seg_t = t - float(starts[k])
        p = _sample(seg, track, seg_t)
        if k > seen_seg:
            seen_seg = k
            since_increment = 0
            if sc.rt_lap:
                packets.append(
                    CapturedPacket(
                        int(wall), sc.port, P.encode_rt_lap(0, k, sc.driver_name, sc.car_name, lap_ms[k - 1])
                    )
                )
        last_lap = lap_ms[k - 1] if k >= 1 else 0
        if k >= 1 and since_increment < sc.last_lap_delay_packets:
            last_lap = lap_ms[k - 2] if k >= 2 else 0
        flying_done = [lap_ms[j] for j in range(1, min(k, sc.flying_laps + 1))]
        best = min(flying_done) if flying_done else 0
        s_track = p["s"] % length
        lap_time = t if k == 0 else seg_t
        v = p["v"]
        values: dict[str, Any] = {
            "speed_Kmh": v * 3.6,
            "speed_Mph": v * 2.2369363,
            "speed_Ms": v,
            "isAbsEnabled": 1,
            "isAbsInAction": 1 if p["brake"] > 0.9 else 0,
            "isTcInAction": 0,
            "isTcEnabled": 1,
            "isInPit": 0,
            "isEngineLimiterOn": 0,
            "accG_vertical": 0.0,
            "accG_horizontal": p["g_lat"],
            "accG_frontal": sc.g_frontal_sign * p["g_lon"],
            "lapTime": round(lap_time * 1000.0),
            "lastLap": last_lap,
            "bestLap": best,
            "lapCount": k,
            "gas": p["throttle"],
            "brake": p["brake"],
            "clutch": 0.0,
            "engineRPM": p["rpm"],
            "steer": p["steering"] * sc.steer_scale,
            "gear": int(p["gear"]) + 1,  # AC: 0 = R, 1 = N, 2 = 1st
            "cgHeight": 0.3,
            "wheelAngularSpeed": (v / 0.33,) * 4,
            "tyreRadius": (0.33,) * 4,
            "carPositionNormalized": (s_track / length + sc.spline_offset) % 1.0,
            "carCoordinates": (p["x"] + ox, 0.0, p["z"] + oz),
        }
        packets.append(CapturedPacket(int(wall), sc.port, P.encode_rt_car_info(values)))
        truth.packets_car_info += 1
        last_values = values
        since_increment += 1
        t += dt
        wall += dt * 1e9
    return packets, truth


def write_ac_capture(path: Path, scenario: AcScenario | None = None, name: str = "ac-synthetic") -> AcTruth:
    """Write a ``.pwcap`` flagged ``synthetic=True`` (replay with ``pitwall replay``)."""
    sc = scenario or AcScenario()
    packets, truth = generate_ac_session(sc)
    meta = CaptureMeta(
        source="synthetic",
        game_hint=GAME_HINT,
        synthetic=True,
        description=f"SYNTHETIC Assetto Corsa remote telemetry stream, scenario '{name}' - not real game output",
        extra={
            "track_name": truth.track.name if truth.track else "synthetic",
            "scenario": name,
            "lap_times_ms": truth.lap_times_ms,
        },
    )
    write_capture(path, packets, meta)
    return truth


# ---------------------------------------------------------------------------------------------- fake ACServer
def simple_car_info_stream(n: int = 600, rate_hz: float = 100.0, speed_mps: float = 50.0) -> list[bytes]:
    """A cheap RTCarInfo sequence (straight-line motion on a 2 km 'lap') for transport tests and probe dry runs."""
    length = 2000.0
    out: list[bytes] = []
    for i in range(n):
        t = i / rate_hz
        s = (speed_mps * t) % length
        out.append(
            P.encode_rt_car_info(
                {
                    "speed_Kmh": speed_mps * 3.6,
                    "speed_Ms": speed_mps,
                    "lapTime": round(1000.0 * (t % (length / speed_mps))),
                    "lapCount": int(speed_mps * t // length),
                    "gas": 1.0,
                    "engineRPM": 7000.0,
                    "gear": 5,
                    "carPositionNormalized": s / length,
                    "carCoordinates": (s, 0.0, 0.0),
                }
            )
        )
    return out


class FakeAcServer:
    """SYNTHETIC loopback stand-in for AC's in-session telemetry server (tests and ``probe_ac.py --dry-run``).

    Behaviour (the spec's, as far as it goes): HANDSHAKE -> one handshake reply; SUBSCRIBE_UPDATE -> RTCarInfo to
    that client every ``1 / rate_hz``; SUBSCRIBE_SPOT -> ``rt_lap`` (if given) once; DISMISS -> stop sending to that
    client. ``end_session()`` emulates the game leaving the session (subscribers dropped, handshakes unanswered);
    ``begin_session()`` brings it back. ``stream=False`` answers handshakes but never sends RTCarInfo (probe outcome
    B). Binds an ephemeral port on a loopback address only.
    """

    def __init__(
        self,
        handshake: bytes | None = None,
        car_info: Sequence[bytes] | None = None,
        *,
        host: str = "127.0.0.1",
        rate_hz: float = 100.0,
        rt_lap: bytes | None = None,
        stream: bool = True,
    ) -> None:
        if not ipaddress.ip_address(host).is_loopback:
            raise ValueError(f"FakeAcServer only binds loopback addresses, not {host!r}")
        if rate_hz <= 0:
            raise ValueError("rate_hz must be positive")
        self.handshake = handshake or P.encode_handshake_response(
            P.SYNTHETIC_CAR_NAME, SYNTHETIC_DRIVER_NAME, SYNTHETIC_TRACK_NAME
        )
        self.car_info = list(car_info) if car_info else simple_car_info_stream()
        self.rt_lap = rt_lap
        self.rate_hz = rate_hz
        self.stream = stream
        self.ops: list[tuple[int, int]] = []  # (operationId, client port) in arrival order
        self.sent = 0
        self._update: set[tuple[str, int]] = set()
        self._answering = True
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind((host, 0))
        ignore_udp_port_unreachable(self._sock)  # Windows: a client that closed its socket must not fail recvfrom
        self._sock.settimeout(min(0.05, 1.0 / rate_hz))
        self._thread = threading.Thread(target=self._run, name="fake-acserver", daemon=True)
        self._i = 0

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._sock.getsockname()[:2]
        return str(host), int(port)

    @property
    def port(self) -> int:
        return self.address[1]

    @property
    def subscribers(self) -> int:
        with self._lock:
            return len(self._update)

    def ops_of(self, op: P.Operation) -> int:
        return sum(1 for o, _ in list(self.ops) if o == op)

    def start(self) -> FakeAcServer:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(2.0)
        self._sock.close()

    def end_session(self) -> None:
        with self._lock:
            self._answering = False
            self._update.clear()

    def begin_session(self) -> None:
        with self._lock:
            self._answering = True

    def __enter__(self) -> FakeAcServer:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def _send(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            self._sock.sendto(data, addr)
            self.sent += 1
        except OSError:  # the client went away (closed socket): AC would just keep going
            with self._lock:
                self._update.discard(addr)

    def _handle(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            _, _, op = P.decode_handshaker(data)
        except P.PacketError:
            return
        self.ops.append((op, addr[1]))
        with self._lock:
            answering = self._answering
            if op == P.Operation.SUBSCRIBE_UPDATE and answering and self.stream:
                self._update.add(addr)
            elif op == P.Operation.DISMISS:
                self._update.discard(addr)
        if op == P.Operation.HANDSHAKE and answering:
            self._send(self.handshake, addr)
        elif op == P.Operation.SUBSCRIBE_SPOT and answering and self.rt_lap is not None:
            self._send(self.rt_lap, addr)

    def _run(self) -> None:
        period = 1.0 / self.rate_hz
        next_send = time.monotonic()
        while not self._stop.is_set():
            try:
                data, addr = self._sock.recvfrom(2048)
                self._handle(data, (str(addr[0]), int(addr[1])))
            except TimeoutError:
                pass
            except OSError:
                if self._stop.is_set():
                    break
                continue  # e.g. ICMP from a client that closed its socket
            now = time.monotonic()
            if now < next_send:
                continue
            next_send = now + period if now - next_send > 1.0 else next_send + period
            with self._lock:
                targets = list(self._update)
            if targets:
                payload = self.car_info[self._i % len(self.car_info)]
                self._i += 1
                for addr in targets:
                    self._send(payload, addr)


class LoopbackRedirect:
    """SYNTHETIC test seam: an ``AcRemoteClient`` / probe ``socket_factory`` whose sockets are told to connect to a
    LAN console but only ever reach 127.0.0.1.

    ``routes`` maps a console IP to the loopback port of a ``FakeAcServer`` (or a closed port, for "refused").
    Every destination asked for is recorded in ``connects`` so tests can assert nothing was aimed off the LAN, and
    an IP without a route raises ``OSError`` at ``connect``: a datagram can never fall through to the real network.
    """

    def __init__(self, routes: Mapping[str, int]) -> None:
        self.routes = dict(routes)
        self.connects: list[tuple[str, int]] = []
        self.sockets: list[socket.socket] = []
        self._lock = threading.Lock()

    def __call__(self) -> socket.socket:
        s = _RedirectSocket(self)
        with self._lock:
            self.sockets.append(s)
        return s

    def _route(self, ip: str, port: int) -> tuple[str, int]:
        with self._lock:
            self.connects.append((ip, port))
            target = self.routes.get(ip)
        if target is None:
            raise OSError(f"LoopbackRedirect: no loopback route for {ip}")
        return ("127.0.0.1", target)


class _RedirectSocket(socket.socket):
    def __init__(self, owner: LoopbackRedirect) -> None:
        super().__init__(socket.AF_INET, socket.SOCK_DGRAM)
        self._owner = owner

    def connect(self, address: Any, /) -> None:
        super().connect(self._owner._route(str(address[0]), int(address[1])))


def stream_distance_m(packets: Sequence[CapturedPacket]) -> float:
    """Total driven path of a generated stream (sum of carCoordinates steps) - a helper for assertions."""
    total = 0.0
    prev: tuple[float, ...] | None = None
    for p in packets:
        if len(p.data) != P.RT_CAR_INFO.size:
            continue
        pos = tuple(P.parse_rt_car_info(p.data)["carCoordinates"])
        if prev is not None:
            total += math.dist(pos, prev)
        prev = pos
    return total


__all__ = [
    "GAME_HINT",
    "SYNTHETIC_DRIVER_NAME",
    "SYNTHETIC_TRACK_NAME",
    "AcPauseSpec",
    "AcScenario",
    "AcTruth",
    "FakeAcServer",
    "LoopbackRedirect",
    "generate_ac_session",
    "handshake_reply",
    "simple_car_info_stream",
    "stream_distance_m",
    "write_ac_capture",
]
