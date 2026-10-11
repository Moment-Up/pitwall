"""Generate a synthetic Forza "Data Out" stream (SYNTHETIC - not real game output).

Every datagram is encoded with the same ``StructDef`` blocks the decoder uses (``adapters/forza/packets.py``), so
the stream exercises the full replay -> decode -> lap assembly path for each of the four formats (Sled 232,
FM7 Dash 311, Horizon 324, FM2023 Dash 331). Synthetic captures validate our algorithms against known ground
truth; they are never evidence of compatibility with any Forza title.

What the generator models, and where it had to choose because Forza's behaviour is undocumented:

* A session starts on track ``outlap_fraction`` of a lap before the start/finish line (an out-lap), so the
  adapter must wait for the first crossing before it knows where a lap begins. ``LapNumber`` counts completed
  laps, ``LastLap`` updates on the crossing packet (``last_lap_delay_packets`` delays it, to exercise the
  adapter's hold logic) and ``BestLap`` ignores the out-lap.
* ``DistanceTraveled`` is the cumulative driven distance. The synthetic car drives the centreline, so a lap is
  ``track.length_m`` long - unless ``lap_distance_scale`` makes the odometer read a lap as driven on a longer or
  shorter line (positions stay on the centreline: what matters to the adapter is the odometer).
* Accelerations are car-local m/s^2 (X right, Z forward) without gravity; velocity is car-local (0, 0, v).
  Tyre temperatures are sent in degF; FM2023 tyre wear as a 0..1 fraction. These follow the community
  interpretation the adapter implements - they test our conversions, not the game.
* A rewind jumps the race clock and position back with no packets in between, and by default rolls
  ``DistanceTraveled`` back too (``RewindSpec.odometer_rolls_back=False`` keeps the odometer running instead -
  which one the games do is undocumented). A pause sends ``IsRaceOn=0`` datagrams that are zero apart from
  that flag.
* Every packet carries ``SYNTHETIC_CAR_ORDINAL`` (and FM2023 ``TrackOrdinal = -1``) so the stream is flagged
  synthetic wherever it travels and can never masquerade as a real car or track.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from pitwall.adapters.forza.adapter import DEFAULT_PORT, STANDARD_GRAVITY
from pitwall.adapters.forza.packets import (
    LAYOUT_BY_FORMAT,
    SYNTHETIC_CAR_ORDINAL,
    WHEEL_SUFFIXES,
    ForzaFormat,
)
from pitwall.ingest.capture import CapturedPacket, CaptureMeta, write_capture
from pitwall.model.telemetry import Game
from pitwall.sim.driver import DriverProfile, LapProfile, VehicleModel, solve_lap
from pitwall.sim.track import TrackGeometry, pitwall_park


@dataclass(slots=True)
class RewindSpec:
    lap: int  # pitwall lap number (1 = out-lap, 2 = first flying lap...) during which the driver rewinds
    at_fraction: float  # fraction of that lap's duration at which the rewind happens
    rewind_s: float = 4.0
    odometer_rolls_back: bool = True  # False: DistanceTraveled keeps counting through the rewind


@dataclass(slots=True)
class PauseSpec:
    at_race_time_s: float  # race clock at which the game is paused (IsRaceOn = 0)
    duration_s: float = 3.0


@dataclass(slots=True)
class ForzaScenario:
    fmt: ForzaFormat = ForzaFormat.FM2023_DASH
    flying_laps: int = 3
    outlap_fraction: float = 0.35  # (0, 1]: part of a lap driven before the first line crossing
    rate_hz: int = 60
    driver_by_lap: dict[int, DriverProfile] = field(default_factory=dict)  # pitwall lap number -> driver
    lap_distance_scale: dict[int, float] = field(default_factory=dict)  # pitwall lap -> odometer metres per track m
    default_driver: DriverProfile = field(default_factory=DriverProfile)
    rewind: RewindSpec | None = None
    pause: PauseSpec | None = None
    car_ordinal: int = SYNTHETIC_CAR_ORDINAL
    track_ordinal: int = -1  # FM2023 only; -1 never matches a real track
    car_class: int = 5
    performance_index: int = 800
    drivetrain: int = 1  # RWD
    num_cylinders: int = 8
    car_group: int = 3  # Horizon only
    fuel_start_fraction: float = 0.9
    fuel_per_lap_fraction: float = 0.04
    wear_per_lap: tuple[float, float, float, float] = (0.020, 0.022, 0.015, 0.016)  # 0..1 fraction FL..RR
    last_lap_delay_packets: int = 0  # LastLap updates this many packets after LapNumber increments
    final_lap_counted: bool = True  # False: LastLap updates at the finish but LapNumber does not advance
    cooldown_s: float = 1.0  # driving after the final crossing
    menu_packets: int = 0  # IsRaceOn=0 datagrams after the cool-down
    origin_m: tuple[float, float] = (0.0, 0.0)  # world (x, z) of the start/finish line
    start_ns: int = 1_000_000_000_000
    port: int = DEFAULT_PORT

    @property
    def game(self) -> Game:
        return LAYOUT_BY_FORMAT[self.fmt].game


@dataclass(slots=True)
class ForzaTruth:
    """What the generator actually did, for test assertions. Lap numbers are pitwall's (1 = out-lap)."""

    lap_times_ms: dict[int, int] = field(default_factory=dict)  # flying laps, as float32 LastLap reports them
    driven_lengths_m: dict[int, float] = field(default_factory=dict)  # flying laps: odometer m (rewinds aside)
    outlap_time_ms: int = 0
    track: TrackGeometry | None = None
    lap_length_m: float = 0.0
    start_line_xz: tuple[float, float] = (0.0, 0.0)
    packets_race_on: int = 0
    packets_race_off: int = 0


@dataclass(slots=True)
class _Segment:
    profile: LapProfile
    t0_in_profile: float  # profile time at which this segment starts (the out-lap starts mid-profile)
    duration_s: float
    dist_before_m: float  # DistanceTraveled at the segment start
    s0_m: float  # track position at the segment start
    dist_scale: float = 1.0  # odometer metres per metre of track (the driven line's length / the centreline's)


def _f32(v: float) -> float:
    return float(np.float32(v))


def _clamp_int(v: float, lo: int, hi: int) -> int:
    return max(lo, min(hi, round(v)))


def _segments(sc: ForzaScenario, track: TrackGeometry, vehicle: VehicleModel) -> list[_Segment]:
    if not 0.0 < sc.outlap_fraction <= 1.0:
        raise ValueError("outlap_fraction must be in (0, 1]: the session must start before a line crossing")
    length = track.length_m
    for lap, scale in sc.lap_distance_scale.items():
        if not 0.5 <= scale <= 1.5:
            raise ValueError(f"lap_distance_scale[{lap}]={scale}: a driven line is within 50 % of the centreline")
    out_prof = solve_lap(track, vehicle, sc.driver_by_lap.get(1, sc.default_driver), lap_index=1)
    s0 = length * (1.0 - sc.outlap_fraction)
    t0 = float(np.interp(s0, out_prof.s, out_prof.t))
    out_scale = sc.lap_distance_scale.get(1, 1.0)
    segs = [_Segment(out_prof, t0, out_prof.lap_time_s - t0, 0.0, s0, out_scale)]
    dist = (length - s0) * out_scale
    for k in range(1, sc.flying_laps + 1):
        lap = k + 1
        prof = solve_lap(track, vehicle, sc.driver_by_lap.get(lap, sc.default_driver), lap_index=lap)
        scale = sc.lap_distance_scale.get(lap, 1.0)
        segs.append(_Segment(prof, 0.0, prof.lap_time_s, dist, 0.0, scale))
        dist += length * scale
    cool = solve_lap(track, vehicle, sc.default_driver, lap_index=0)
    segs.append(_Segment(cool, 0.0, max(sc.cooldown_s, 1.0 / sc.rate_hz), dist, 0.0))
    return segs


def _sample(seg: _Segment, track: TrackGeometry, seg_t: float) -> dict[str, float]:
    """Interpolate the profile at ``seg_t`` seconds into the segment."""
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
        "heading": float(np.interp(s, track.s, track.heading)),
        "curvature": float(np.interp(s, track.s, track.curvature)),
    }


def generate_forza_session(
    sc: ForzaScenario | None = None,
    track: TrackGeometry | None = None,
    vehicle: VehicleModel | None = None,
) -> tuple[list[CapturedPacket], ForzaTruth]:
    sc = sc or ForzaScenario()
    track = track or pitwall_park()
    vehicle = vehicle or VehicleModel()
    layout = LAYOUT_BY_FORMAT[sc.fmt]
    segs = _segments(sc, track, vehicle)
    starts = np.concatenate([[0.0], np.cumsum([sg.duration_s for sg in segs])])
    n_flying = sc.flying_laps
    truth = ForzaTruth(
        track=track,
        lap_length_m=track.length_m,
        start_line_xz=sc.origin_m,
        outlap_time_ms=round(_f32(segs[0].duration_s) * 1000),
        lap_times_ms={k + 1: round(_f32(segs[k].duration_s) * 1000) for k in range(1, n_flying + 1)},
        driven_lengths_m={k + 1: track.length_m * segs[k].dist_scale for k in range(1, n_flying + 1)},
    )
    packets: list[CapturedPacket] = []
    dt = 1.0 / sc.rate_hz
    wall = float(sc.start_ns)
    t = 0.0
    end_t = float(starts[-1])
    rw = sc.rewind
    rw_t = float(starts[rw.lap - 1] + rw.at_fraction * segs[rw.lap - 1].duration_s) if rw else None
    rw_done = False
    pause_done = sc.pause is None
    seen_seg = 0
    packets_since_increment = 10**9
    ox, oz = sc.origin_m
    off_packet = layout.pack({"IsRaceOn": 0})
    odometer_offset = 0.0  # added to DistanceTraveled after a rewind that does not roll it back
    last_dist: float | None = None  # odometer (without offset) of the latest packet
    keep_odometer_from: float | None = None

    def emit(data: bytes) -> None:
        packets.append(CapturedPacket(int(wall), sc.port, data))

    while t < end_t - 1e-9:
        if not pause_done and sc.pause is not None and t >= sc.pause.at_race_time_s:
            pause_done = True
            for _ in range(round(sc.pause.duration_s * sc.rate_hz)):
                emit(off_packet)
                truth.packets_race_off += 1
                wall += dt * 1e9
        if rw is not None and rw_t is not None and not rw_done and t >= rw_t:
            rw_done = True  # the game sends nothing while the rewind UI is open, then resumes earlier
            if not rw.odometer_rolls_back:
                keep_odometer_from = last_dist
            t = max(0.0, t - rw.rewind_s)
            wall += 2.0e9
            continue

        k = int(np.searchsorted(starts, t, side="right")) - 1
        k = max(0, min(k, len(segs) - 1))
        seg = segs[k]
        seg_t = t - float(starts[k])
        p = _sample(seg, track, seg_t)
        if k > seen_seg:
            seen_seg = k
            packets_since_increment = 0
        is_cooldown = k == len(segs) - 1
        lap_number = k if (not is_cooldown or sc.final_lap_counted) else k - 1
        last_lap = _f32(segs[k - 1].duration_s) if k >= 1 else 0.0
        if k >= 1 and packets_since_increment < sc.last_lap_delay_packets and lap_number == k:
            last_lap = _f32(segs[k - 2].duration_s) if k >= 2 else 0.0
        flying_done = [segs[j].duration_s for j in range(1, min(k, n_flying + 1))]
        best = _f32(min(flying_done)) if flying_done else 0.0
        current_lap = t if k == 0 else seg_t
        if is_cooldown and not sc.final_lap_counted:
            current_lap = t - float(starts[k - 1])  # the game never closed the last lap
        dist = seg.dist_before_m + (p["s"] - seg.s0_m) * seg.dist_scale
        if keep_odometer_from is not None:  # carry on counting from where the rewind started (plus one frame)
            odometer_offset += keep_odometer_from - dist + p["v"] * dt
            keep_odometer_from = None
        last_dist = dist
        dist += odometer_offset
        laps_done = dist / track.length_m
        load = abs(p["g_lat"]) + abs(p["g_lon"])
        tyre_c = [82.0 + 7.0 * load + 0.5 * i for i in range(4)]
        wear = [w * laps_done for w in sc.wear_per_lap]
        values: dict[str, Any] = {
            "IsRaceOn": 1,
            "TimestampMS": int(wall // 1_000_000) & 0xFFFFFFFF,
            "EngineMaxRpm": vehicle.max_rpm,
            "EngineIdleRpm": vehicle.idle_rpm,
            "CurrentEngineRpm": p["rpm"],
            "AccelerationX": p["g_lat"] * STANDARD_GRAVITY,
            "AccelerationY": 0.0,
            "AccelerationZ": p["g_lon"] * STANDARD_GRAVITY,
            "VelocityZ": p["v"],
            "AngularVelocityY": p["v"] * p["curvature"],
            "Yaw": p["heading"],
            "CarOrdinal": sc.car_ordinal,
            "CarClass": sc.car_class,
            "CarPerformanceIndex": sc.performance_index,
            "DrivetrainType": sc.drivetrain,
            "NumCylinders": sc.num_cylinders,
            "CarGroup": sc.car_group,
            "PositionX": p["x"] + ox,
            "PositionY": 0.0,
            "PositionZ": p["z"] + oz,
            "Speed": p["v"],
            "Fuel": max(0.0, sc.fuel_start_fraction - sc.fuel_per_lap_fraction * laps_done),
            "DistanceTraveled": dist,
            "BestLap": best,
            "LastLap": last_lap,
            "CurrentLap": current_lap,
            "CurrentRaceTime": t,
            "LapNumber": lap_number,
            "RacePosition": 1,
            "Accel": _clamp_int(p["throttle"] * 255, 0, 255),
            "Brake": _clamp_int(p["brake"] * 255, 0, 255),
            "Gear": int(p["gear"]),
            "Steer": _clamp_int(p["steering"] * 127, -127, 127),
            "TrackOrdinal": sc.track_ordinal,
        }
        for i, w in enumerate(WHEEL_SUFFIXES):
            values[f"TireTemp{w}"] = tyre_c[i] * 9.0 / 5.0 + 32.0
            values[f"TireWear{w}"] = wear[i]
            values[f"WheelRotationSpeed{w}"] = p["v"] / 0.33
        emit(layout.pack(values))
        truth.packets_race_on += 1
        packets_since_increment += 1
        t += dt
        wall += dt * 1e9

    for _ in range(sc.menu_packets):
        emit(off_packet)
        truth.packets_race_off += 1
        wall += dt * 1e9
    return packets, truth


def write_forza_capture(path: Path, scenario: ForzaScenario | None = None, name: str = "forza-synthetic") -> ForzaTruth:
    """Write a ``.pwcap`` flagged ``synthetic=True`` (replay with ``pitwall replay``)."""
    sc = scenario or ForzaScenario()
    packets, truth = generate_forza_session(sc)
    meta = CaptureMeta(
        source="synthetic",
        game_hint=sc.game.value,
        synthetic=True,
        description=f"SYNTHETIC Forza Data Out stream ({sc.fmt.value}), scenario '{name}' - not real game output",
        extra={
            "track_name": truth.track.name if truth.track else "synthetic",
            "scenario": name,
            "forza_format": sc.fmt.value,
            "lap_times_ms": truth.lap_times_ms,
        },
    )
    write_capture(path, packets, meta)
    return truth


def lap_fraction_time(truth: ForzaTruth, lap: int, fraction: float) -> float:
    """Race-clock time at ``fraction`` of pitwall lap ``lap`` (flying laps only), for building scenarios."""
    if lap not in truth.lap_times_ms:
        raise KeyError(f"lap {lap} is not a flying lap")
    t = truth.outlap_time_ms / 1000.0
    for k in range(2, lap):
        t += truth.lap_times_ms[k] / 1000.0
    return t + fraction * truth.lap_times_ms[lap] / 1000.0


__all__ = [
    "ForzaScenario",
    "ForzaTruth",
    "PauseSpec",
    "RewindSpec",
    "generate_forza_session",
    "lap_fraction_time",
    "write_forza_capture",
]
