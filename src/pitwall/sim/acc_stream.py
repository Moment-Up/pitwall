"""Synthetic Assetto Corsa Competizione shared memory (SYNTHETIC - not real game output; for tests only).

Built on the same encoders the adapter's tests check against Kunos' document (``pitwall.adapters.acc.packets``), so
generator and decoder cannot drift apart:

* ``acc_page_timeline`` - what ACC's three pages hold, tick by tick, for laps of a ``pitwall.sim`` track driven by
  a ``pitwall.sim.driver`` profile: the menus (status OFF) before and after, the session (status LIVE), an optional
  pause (status PAUSE, Physics frozen), with known ground truth (lap times, validity, track length).
* ``generate_acc_session`` - that timeline through the reader's own ``AccPageGate``: exactly the snapshots
  ``AccSharedMemoryReader`` would forward (and record) for it. ``write_acc_capture`` stores them as a ``.pwcap``
  flagged ``synthetic=True`` with the ACC capture hint, so ``pitwall replay`` decodes it.
* ``FakeAccMemory`` - a stand-in for the three named mappings with Windows' lifetime rule (a mapping exists while
  the game holds it or any view of it is open) and an ``opener`` for the reader. Like ``OpenFileMappingW`` it can
  only open what exists: with the game closed and no view open it answers None, and it records every open.

Every Static page names ``SYNTHETIC_CAR_MODEL`` as the car, which the adapter maps to the synthetic session uid
(the session manager then gives the session a ``synthetic:<scenario>`` track id): generated telemetry is flagged
synthetic wherever it travels. The track is not in ``adapters/acc/tracks.py``, so the lap distance comes from
Static's ``trackSplineLength`` (the generator writes the track's length there; the adapter trusts that field for an
unlisted track only in a synthetic stream - real ACC marks it "not used").

What the generator had to choose, because ACC's behaviour is undocumented (these test Pitwall's logic, not the
game): Graphics and Physics get a new ``packetId`` every tick on track; in the menus and while paused Graphics keeps
stepping and Physics does not (the reader must not care either way); ``completedLaps`` and ``iLastTime`` change in
the same page at the line, with ``isValidLap`` of the new lap; the car drives the centreline, so a lap is exactly
the track's length; ``accG`` / ``localAngularVel`` stay zero, so the adapter's runtime checks never map the dynamics
channels.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from pitwall.adapters.acc import packets as P
from pitwall.ingest.acc_shm_reader import CAPTURE_GAME_HINT, NO_PORT, AccPageGate, PageView
from pitwall.ingest.capture import CapturedPacket, CaptureMeta, write_capture
from pitwall.sim.driver import DriverProfile, LapProfile, VehicleModel, solve_lap
from pitwall.sim.track import TrackGeometry, pitwall_park

log = logging.getLogger(__name__)

SYNTHETIC_TRACK_NAME = "synthetic-pitwall-park"  # not in tracks.py: the lap distance uses trackSplineLength
GAME_HINT = CAPTURE_GAME_HINT  # what the runtime's replay requires before decoding a capture as ACC
PLAYER_CAR_ID = 1001
SECTORS = 3


@dataclass(slots=True)
class AccPauseSpec:
    at_time_s: float  # session time (s since the first LIVE page) at which the game pauses
    duration_s: float = 3.0


@dataclass(slots=True)
class AccScenario:
    flying_laps: int = 2
    outlap_fraction: float = 0.35  # (0, 1): part of a lap driven before the first line crossing
    rate_hz: float = 60.0  # ACC rewrites its pages once per graphics frame; the reader samples at 60 Hz
    driver_by_lap: dict[int, DriverProfile] = field(default_factory=dict)  # pitwall lap number -> driver
    # braking-point jitter: lap times differ, as real ones do (the adapter times a lap from iLastTime *changing*)
    default_driver: DriverProfile = field(default_factory=lambda: DriverProfile(noise_m=3.0, seed=7))
    invalid_laps: frozenset[int] = frozenset()  # pitwall lap numbers driven with isValidLap = 0
    car_model: str = P.SYNTHETIC_CAR_MODEL
    track_name: str = SYNTHETIC_TRACK_NAME
    menu_s: float = 0.5  # in the menus (status OFF) before the session and after it
    pause: AccPauseSpec | None = None
    cooldown_s: float = 1.0  # driving after the final crossing
    session_type: int = int(P.AccSessionType.PRACTICE)
    start_ns: int = 1_000_000_000_000


@dataclass(slots=True)
class AccTruth:
    """What the generator did, for assertions. Lap numbers are Pitwall's (1 = out-lap)."""

    lap_times_ms: dict[int, int] = field(default_factory=dict)  # flying laps, exactly as iLastTime reports them
    outlap_time_ms: int = 0
    valid: dict[int, bool] = field(default_factory=dict)  # every completed lap
    track: TrackGeometry | None = None
    lap_length_m: float = 0.0
    live_ticks: int = 0  # ticks with status LIVE (Physics stepping)
    paused_ticks: int = 0
    menu_ticks: int = 0


@dataclass(frozen=True, slots=True)
class AccPageState:
    """ACC's three pages (bodies, no tags) at one instant of the synthetic game."""

    t_ns: int
    physics: bytes
    graphics: bytes
    static: bytes


@dataclass(slots=True)
class _Segment:
    profile: LapProfile
    t0_in_profile: float
    duration_s: float


def _segments(sc: AccScenario, track: TrackGeometry, vehicle: VehicleModel) -> list[_Segment]:
    if not 0.0 < sc.outlap_fraction < 1.0:
        raise ValueError("outlap_fraction must be in (0, 1): the session must start before a line crossing")
    length = track.length_m
    out_prof = solve_lap(track, vehicle, sc.driver_by_lap.get(1, sc.default_driver), lap_index=1)
    t0 = float(np.interp(length * (1.0 - sc.outlap_fraction), out_prof.s, out_prof.t))
    segs = [_Segment(out_prof, t0, out_prof.lap_time_s - t0)]
    for k in range(1, sc.flying_laps + 1):
        prof = solve_lap(track, vehicle, sc.driver_by_lap.get(k + 1, sc.default_driver), lap_index=k + 1)
        segs.append(_Segment(prof, 0.0, prof.lap_time_s))
    cool = solve_lap(track, vehicle, sc.default_driver, lap_index=0)
    segs.append(_Segment(cool, 0.0, max(sc.cooldown_s, 1.0 / sc.rate_hz)))
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
        "x": float(np.interp(s, track.s, track.x)),
        "z": float(np.interp(s, track.s, track.z)),
    }


def static_body(sc: AccScenario, track: TrackGeometry) -> bytes:
    """The Static page of a synthetic session (no player names: the generator has none)."""
    return P.STATIC.pack(
        {
            "smVersion": P.encode_wstring("1.9", 15),
            "acVersion": P.encode_wstring("synthetic", 15),
            "numberOfSessions": 1,
            "numCars": 1,
            "carModel": P.encode_wstring(sc.car_model, 33),
            "track": P.encode_wstring(sc.track_name, 33),
            "sectorCount": SECTORS,
            "maxRpm": 8000,
            "maxFuel": 120.0,
            "trackSplineLength": track.length_m,
            "isOnline": 0,
            "dryTyresName": P.encode_wstring("synthetic_dry", 33),  # made up: lets the adapter trust isOnline
            "wetTyresName": P.encode_wstring("synthetic_wet", 33),
        }
    )


def acc_page_timeline(
    sc: AccScenario | None = None,
    track: TrackGeometry | None = None,
    vehicle: VehicleModel | None = None,
) -> tuple[list[AccPageState], AccTruth]:
    """ACC's pages tick by tick: menus, session (with an optional pause), menus again (module docstring)."""
    sc = sc or AccScenario()
    track = track or pitwall_park()
    vehicle = vehicle or VehicleModel()
    segs = _segments(sc, track, vehicle)
    starts = np.concatenate([[0.0], np.cumsum([sg.duration_s for sg in segs])])
    length = track.length_m
    lap_ms = [round(sg.duration_s * 1000.0) for sg in segs]
    truth = AccTruth(
        track=track,
        lap_length_m=length,
        outlap_time_ms=lap_ms[0],
        lap_times_ms={k + 1: lap_ms[k] for k in range(1, sc.flying_laps + 1)},
        valid={k: k not in sc.invalid_laps for k in range(1, sc.flying_laps + 2)},
    )
    dt = 1.0 / sc.rate_hz
    wall = float(sc.start_ns)
    ppid = gpid = 0
    states: list[AccPageState] = []
    static_on = static_body(sc, track)
    physics = P.PHYSICS.pack({"packetId": 0})
    graphics_values: dict[str, Any] = {"status": int(P.AccStatus.OFF), "session": sc.session_type}

    def emit(static: bytes) -> None:
        nonlocal wall
        states.append(AccPageState(int(wall), physics, P.GRAPHICS.pack({**graphics_values, "packetId": gpid}), static))
        wall += dt * 1e9

    def menus(static: bytes) -> None:
        nonlocal gpid
        graphics_values["status"] = int(P.AccStatus.OFF)
        for _ in range(max(1, round(sc.menu_s * sc.rate_hz))):
            gpid += 1  # the menus are rendered: Graphics steps, Physics does not
            truth.menu_ticks += 1
            emit(static)

    menus(bytes(P.STATIC.size))  # a freshly started game: Static not filled in yet
    t = 0.0
    end_t = float(starts[-1])
    pause_done = sc.pause is None
    best: int | None = None
    while t < end_t - 1e-9:
        if not pause_done and sc.pause is not None and t >= sc.pause.at_time_s:
            pause_done = True
            graphics_values["status"] = int(P.AccStatus.PAUSE)
            for _ in range(round(sc.pause.duration_s * sc.rate_hz)):
                gpid += 1
                truth.paused_ticks += 1
                emit(static_on)
        k = max(0, min(int(np.searchsorted(starts, t, side="right")) - 1, len(segs) - 1))
        seg_t = t - float(starts[k])
        p = _sample(segs[k], track, seg_t)
        if 1 <= k - 1 <= sc.flying_laps and truth.valid.get(k, True):
            best = lap_ms[k - 1] if best is None else min(best, lap_ms[k - 1])
        s_track = p["s"] % length
        frac = s_track / length
        v = p["v"]
        ppid += 1
        gpid += 1
        physics = P.PHYSICS.pack(
            {
                "packetId": ppid,
                "gas": p["throttle"],
                "brake": p["brake"],
                "clutch": 0.0,
                "steerAngle": -float(np.clip(p["steering"], -1.0, 1.0)),  # the adapter negates it (Pitwall: + right)
                "speedKmh": v * 3.6,
                "gear": int(p["gear"]) + 1,  # 0 = R, 1 = N, 2 = 1st
                "rpm": round(p["rpm"]),
                "wheelPressure": (27.5, 27.5, 27.8, 27.8),
                "TyreCoreTemp": (82.0, 83.0, 80.0, 81.0),
                "brakeTemp": (420.0, 425.0, 310.0, 315.0),
                "airTemp": 22.0,
                "roadTemp": 31.0,
                "localVelocity": (0.0, 0.0, v),
            }
        )
        coords = [0.0] * 180
        coords[0:3] = [p["x"], 0.0, p["z"]]
        graphics_values.update(
            {
                "status": int(P.AccStatus.LIVE),
                "sessionIndex": 0,
                "completedLaps": k,
                "position": 1,
                "iCurrentTime": round((t if k == 0 else seg_t) * 1000.0),
                "iLastTime": lap_ms[k - 1] if k >= 1 else P.INT32_MAX,
                "iBestTime": best if best is not None else P.INT32_MAX,
                "isInPit": 0,
                "isInPitLane": 0,
                "currentSectorIndex": min(SECTORS - 1, int(frac * SECTORS)),
                "normalizedCarPosition": frac,
                "activeCars": 1,
                "carCoordinates": coords,
                "carID": [PLAYER_CAR_ID] + [0] * 59,
                "playerCarID": PLAYER_CAR_ID,
                "TC": 3,
                "ABS": 2,
                "rainTyres": 0,
                "fuelEstimatedLaps": 20.0,
                "isValidLap": 1 if truth.valid.get(k + 1, True) else 0,
                "rainIntensity": int(P.AccRainIntensity.NO_RAIN),
            }
        )
        truth.live_ticks += 1
        emit(static_on)
        t += dt
    menus(static_on)  # back to the menus: Static keeps the last session (Kunos: until the instance closes)
    return states, truth


def generate_acc_session(
    sc: AccScenario | None = None,
    track: TrackGeometry | None = None,
    vehicle: VehicleModel | None = None,
) -> tuple[list[CapturedPacket], AccTruth]:
    """The snapshots ``AccSharedMemoryReader`` would forward for ``acc_page_timeline`` (same gate, same order)."""
    states, truth = acc_page_timeline(sc, track, vehicle)
    return gate_states(states), truth


def gate_states(states: Iterable[AccPageState]) -> list[CapturedPacket]:
    """Page states through a fresh ``AccPageGate``, as the reader polls them."""
    gate = AccPageGate()
    out: list[CapturedPacket] = []
    for st in states:
        for snap in gate.offer(st.physics, st.graphics, st.static):
            out.append(CapturedPacket(st.t_ns, NO_PORT, snap))
    return out


def write_acc_capture(path: Path, scenario: AccScenario | None = None, name: str = "acc-synthetic") -> AccTruth:
    """Write a ``.pwcap`` flagged ``synthetic=True`` (replay with ``pitwall replay``)."""
    sc = scenario or AccScenario()
    packets, truth = generate_acc_session(sc)
    meta = CaptureMeta(
        source="synthetic",
        game_hint=GAME_HINT,
        synthetic=True,
        description=f"SYNTHETIC ACC shared-memory snapshots, scenario '{name}' - not real game output",
        extra={
            "track_name": truth.track.name if truth.track else "synthetic",
            "scenario": name,
            "lap_times_ms": truth.lap_times_ms,
        },
    )
    write_capture(path, packets, meta)
    return truth


# ---------------------------------------------------------------------------------------------- fake mappings
class _FakeView:
    def __init__(self, memory: FakeAccMemory, name: str, size: int) -> None:
        self._memory = memory
        self._name: str | None = name
        self.size = size

    def read(self, offset: int = 0, size: int | None = None) -> bytes:
        if self._name is None:
            raise OSError("view closed")
        n = self.size - offset if size is None else size
        return self._memory._read(self._name, offset, n)

    def close(self) -> None:
        name, self._name = self._name, None
        if name is not None:
            self._memory._release(name)


class FakeAccMemory:
    """SYNTHETIC stand-in for ACC's named mappings (module docstring). Thread-safe: a reader thread may read while
    the test writes."""

    def __init__(self, pages: Sequence[P.Page] = P.PAGES) -> None:
        self.pages = {p.mapping: p for p in pages}
        self.running = False
        self.denied = False  # every open raises PermissionError (ACC run as administrator, Pitwall not)
        self.open_calls: list[str] = []
        self._mem: dict[str, bytearray] = {}
        self._views: dict[str, int] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ the game
    def start_game(self) -> None:
        """ACC starts: it creates its pages (zero-filled) unless they still exist because a view kept them."""
        with self._lock:
            self.running = True
            for name, page in self.pages.items():
                self._mem.setdefault(name, bytearray(page.size))

    def quit_game(self) -> None:
        """ACC quits: each page disappears with its last open view (now, if nobody holds one)."""
        with self._lock:
            self.running = False
            for name in list(self._mem):
                if not self._views.get(name):
                    del self._mem[name]

    def write(self, physics: bytes | None = None, graphics: bytes | None = None, static: bytes | None = None) -> None:
        """ACC rewrites pages (bodies without tags); only a running game writes."""
        with self._lock:
            if not self.running:
                raise RuntimeError("the game is not running")
            for page, body in ((P.PHYSICS_PAGE, physics), (P.GRAPHICS_PAGE, graphics), (P.STATIC_PAGE, static)):
                if body is not None:
                    if len(body) != page.size:
                        raise ValueError(f"{page.mapping}: {len(body)} bytes, expected {page.size}")
                    self._mem[page.mapping][:] = body

    def show(self, state: AccPageState) -> None:
        self.write(state.physics, state.graphics, state.static)

    def exists(self, name: str) -> bool:
        with self._lock:
            return name in self._mem

    @property
    def views_open(self) -> int:
        with self._lock:
            return sum(self._views.values())

    # ------------------------------------------------------------------ the reader's side
    def opener(self, name: str, size: int) -> PageView | None:
        """``AccSharedMemoryReader`` opener: open an existing page read-only; None when it does not exist."""
        with self._lock:
            self.open_calls.append(name)
            if self.denied:
                raise PermissionError(5, f"access denied opening {name}")
            mem = self._mem.get(name)
            if mem is None:
                return None
            if size > len(mem):
                raise OSError(f"{name} is {len(mem)} bytes, {size} requested")
            self._views[name] = self._views.get(name, 0) + 1
        return _FakeView(self, name, size)

    def _read(self, name: str, offset: int, size: int) -> bytes:
        with self._lock:
            return bytes(self._mem[name][offset : offset + size])

    def _release(self, name: str) -> None:
        with self._lock:
            self._views[name] = max(0, self._views.get(name, 0) - 1)
            if not self._views[name] and not self.running:
                self._mem.pop(name, None)


__all__ = [
    "GAME_HINT",
    "PLAYER_CAR_ID",
    "SYNTHETIC_TRACK_NAME",
    "AccPageState",
    "AccPauseSpec",
    "AccScenario",
    "AccTruth",
    "FakeAccMemory",
    "acc_page_timeline",
    "gate_states",
    "generate_acc_session",
    "static_body",
    "write_acc_capture",
]
