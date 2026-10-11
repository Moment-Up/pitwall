"""Generate a synthetic, encrypted Gran Turismo 7 packet stream (SYNTHETIC - not real game output).

Packets are built with the same ``StructDef`` layouts the decoder uses and encrypted with the same Salsa20
framing (random IV per packet, written to ciphertext bytes 0x40..0x43), so a synthetic capture exercises the
complete decrypt -> decode -> derived lap distance -> lap assembly -> analysis path. Driving comes from the
shared synthetic track and driver models (``pitwall.sim.track`` / ``pitwall.sim.driver``), so injected driver
mistakes have known ground truth.

Every packet carries ``packets.SYNTHETIC_MARKER`` in the reserved bytes 0xD4..0xF3; the adapter turns that into
the synthetic session UID, so the session manager flags the session synthetic even when streamed over real
UDP. Synthetic results validate pitwall's algorithms; they are never evidence of GT7 compatibility.

Stream shape (mirrors a GT7 time trial): an out-lap on lap 0 over the last ``out_lap_fraction`` of the
circuit, ``laps`` timed laps, then ``tail_s`` seconds into lap ``laps + 1`` so the last lap completes. The
lap counter increments at each line crossing and ``last_lap_ms`` / ``best_lap_ms`` update in the same packet.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from pitwall.adapters.gt7 import packets as P
from pitwall.adapters.gt7.adapter import STEER_HALF_LOCK_RAD, TICK_S
from pitwall.ingest.capture import CapturedPacket, CaptureMeta, write_capture
from pitwall.sim.driver import CornerDeviation, DriverProfile, LapProfile, VehicleModel, solve_lap
from pitwall.sim.track import TrackGeometry, pitwall_park

# A GT3-class car: less grip and power than the F1-like default model, six gears, lower rev range.
GT3_LIKE = VehicleModel(
    mu_lat=1.45,
    aero_lat=0.0019,
    brake_base=11.5,
    brake_aero=0.0022,
    power_per_mass=430.0,
    traction_limit=9.5,
    drag=0.00062,
    v_max=78.0,
    gear_top_kph=(110, 150, 185, 220, 252, 285),
    idle_rpm=2500.0,
    max_rpm=8800.0,
    wheelbase_m=2.7,
    max_steer_rad=0.4,
)
SYNTHETIC_CAR_CODE = 0x5EED  # not a real GT7 car code
ROAD_WHEEL_LOCK_RAD = 0.4  # synthetic road-wheel angle at full steering input


@dataclass(slots=True)
class PauseSpec:
    lap: int  # lap count (1-based) during which the driver pauses
    at_fraction: float  # fraction of that lap's time
    duration_s: float = 3.0


@dataclass(slots=True)
class GT7Scenario:
    laps: int = 3
    variant: str = "C"  # "A", "B", "~" or "C"
    out_lap_fraction: float = 0.25  # lap 0 covers this final fraction of the circuit before the first crossing
    tail_s: float = 2.0  # driving into lap ``laps + 1`` after the last crossing
    driver_by_lap: dict[int, DriverProfile] = field(default_factory=dict)  # lap number -> profile
    default_driver: DriverProfile = field(default_factory=DriverProfile)
    vehicle: VehicleModel = GT3_LIKE
    pause: PauseSpec | None = None
    total_laps: int = 0  # 0 = time trial / free run (doc section 4)
    car_code: int = SYNTHETIC_CAR_CODE
    fuel_capacity_l: float = 100.0
    fuel_start_l: float = 60.0
    fuel_per_lap_l: float = 2.2
    origin_xz: tuple[float, float] = (-312.0, 1187.0)  # offset into "world" coordinates
    first_packet_id: int = 48_000
    loading_packets: int = 0  # LOADING-flagged packets before driving starts
    start_ns: int = 1_000_000_000_000
    time_of_day_start_ms: int = 14 * 3_600_000  # in-game clock (0x80) at the first driving packet
    # Lateral weave of the driven line around the centreline: amplitude (m) and wavelength (m along the lap). The
    # velocity direction follows the weave, so it exercises the turning signature's tolerance to a wandering line.
    line_wander_m: float = 0.0
    line_wander_wavelength_m: float = 250.0
    seed: int = 11
    synthetic_marker: bool = True  # tests may disable it to exercise unflagged decoding (never for captures)


@dataclass(slots=True)
class GT7GroundTruth:
    """What the generator actually did, for test assertions."""

    track: TrackGeometry
    lap_times_ms: dict[int, int] = field(default_factory=dict)
    profiles: dict[int, LapProfile] = field(default_factory=dict)
    # packet id -> (lap count, true distance along the lap in metres)
    distance_by_packet_id: dict[int, tuple[int, float]] = field(default_factory=dict)
    sf_xz: tuple[float, float] = (0.0, 0.0)


@dataclass(slots=True)
class _Segment:
    lap: int  # GT7 lap counter value while driving this segment
    profile: LapProfile
    lap_t0: float  # lap time (s) at which the segment starts
    t_start: float  # session time (s) at which the segment starts
    duration: float


def _sample(seg: _Segment, t: float) -> dict[str, float]:
    prof = seg.profile
    lap_t = seg.lap_t0 + (t - seg.t_start)
    out = {"lap_t": lap_t}
    for name in ("s", "v", "throttle", "brake", "steering", "rpm", "g_lat", "g_lon"):
        out[name] = float(np.interp(lap_t, prof.t, getattr(prof, name)))
    i = int(np.clip(np.searchsorted(prof.t, lap_t, side="right") - 1, 0, len(prof.t) - 1))
    out["gear"] = float(prof.gear[i])
    return out


def _byte(x: float) -> int:
    return round(min(1.0, max(0.0, x)) * 255)


def generate_gt7_session(
    sc: GT7Scenario | None = None, track: TrackGeometry | None = None
) -> tuple[list[CapturedPacket], GT7GroundTruth]:
    sc = sc or GT7Scenario()
    track = track or pitwall_park()
    if sc.variant not in P.VARIANTS:
        raise ValueError(f"unknown GT7 variant {sc.variant!r}")
    if not 0.0 < sc.out_lap_fraction < 1.0:
        raise ValueError("out_lap_fraction must be in (0, 1)")
    truth = GT7GroundTruth(track=track, sf_xz=(sc.origin_xz[0] + track.x[0], sc.origin_xz[1] + track.z[0]))
    segments: list[_Segment] = []
    t = 0.0
    out_prof = solve_lap(track, sc.vehicle, sc.default_driver, lap_index=0)
    t_s0 = float(np.interp(track.length_m * (1.0 - sc.out_lap_fraction), out_prof.s, out_prof.t))
    segments.append(_Segment(0, out_prof, t_s0, t, out_prof.lap_time_s - t_s0))
    t += segments[-1].duration
    for lap in range(1, sc.laps + 1):
        prof = solve_lap(track, sc.vehicle, sc.driver_by_lap.get(lap, sc.default_driver), lap_index=lap)
        truth.profiles[lap] = prof
        truth.lap_times_ms[lap] = round(prof.lap_time_s * 1000)
        segments.append(_Segment(lap, prof, 0.0, t, prof.lap_time_s))
        t += prof.lap_time_s
    tail_prof = solve_lap(track, sc.vehicle, sc.default_driver, lap_index=sc.laps + 1)
    segments.append(_Segment(sc.laps + 1, tail_prof, 0.0, t, sc.tail_s))
    return list(_stream(sc, track, segments, truth)), truth


def _stream(
    sc: GT7Scenario, track: TrackGeometry, segments: list[_Segment], truth: GT7GroundTruth
) -> Iterator[CapturedPacket]:
    variant = P.VARIANTS[sc.variant]
    rng = np.random.default_rng(sc.seed)
    tick = 0
    marker = P.SYNTHETIC_MARKER if sc.synthetic_marker else b""

    def emit(values: dict[str, Any]) -> CapturedPacket:
        nonlocal tick
        values["packet_id"] = sc.first_packet_id + tick
        values["reserved"] = marker
        values["car_code"] = sc.car_code
        iv1 = int(rng.integers(0, 2**32))
        data = P.encrypt(P.pack(variant, values), iv1)
        pkt = CapturedPacket(sc.start_ns + round(tick * TICK_S * 1e9), P.RECEIVE_PORT, data)
        tick += 1
        return pkt

    for _ in range(sc.loading_packets):
        yield emit({"flags": int(P.Flags.LOADING_OR_PROCESSING), "lap_count": 0, "last_lap_ms": -1, "best_lap_ms": -1})

    seg_i = 0
    t = 0.0
    t_end = segments[-1].t_start + segments[-1].duration
    pause = sc.pause
    pause_t = None
    if pause is not None:
        pseg = next(s for s in segments if s.lap == pause.lap)
        pause_t = pseg.t_start + pause.at_fraction * pseg.duration
    completed: dict[int, int] = {}
    while t < t_end - 1e-9:
        while seg_i + 1 < len(segments) and t >= segments[seg_i + 1].t_start:
            seg_i += 1
        seg = segments[seg_i]
        for done in range(1, seg.lap):
            completed.setdefault(done, truth.lap_times_ms[done])
        smp = _sample(seg, t)
        values = _packet_values(sc, track, seg, smp, t, completed, variant)
        paused = pause_t is not None and t >= pause_t
        if paused and pause is not None:
            pause_t = None
            for _ in range(round(pause.duration_s / TICK_S)):  # frozen state, ids keep counting
                frozen = dict(values, flags=values["flags"] | int(P.Flags.PAUSED))
                yield emit(frozen)
        if seg.lap >= 1:
            truth.distance_by_packet_id[sc.first_packet_id + tick] = (seg.lap, smp["s"])
        yield emit(values)
        t += TICK_S


def _packet_values(
    sc: GT7Scenario,
    track: TrackGeometry,
    seg: _Segment,
    smp: dict[str, float],
    t: float,
    completed: dict[int, int],
    variant: P.Variant,
) -> dict[str, Any]:
    s, v = smp["s"], smp["v"]
    heading = float(np.interp(s, track.s, track.heading))
    x = sc.origin_xz[0] + float(np.interp(s, track.s, track.x))
    z = sc.origin_xz[1] + float(np.interp(s, track.s, track.z))
    travel = heading  # direction of the velocity vector
    if sc.line_wander_m:
        k = 2 * math.pi / sc.line_wander_wavelength_m
        off = sc.line_wander_m * math.sin(k * s)  # to the right of the centreline (heading: 0 = +z, clockwise)
        x += off * math.cos(heading)
        z -= off * math.sin(heading)
        travel += math.atan(sc.line_wander_m * k * math.cos(k * s))
    laps_done = max(0.0, seg.lap - 1 + s / track.length_m)
    load = abs(smp["g_lat"]) + abs(smp["g_lon"])
    gear = int(smp["gear"])
    radius = 0.34
    last = completed.get(seg.lap - 1, -1)
    best = min(completed.values()) if completed else -1
    values: dict[str, Any] = {
        "position": (x, 0.0, z),
        "velocity": (v * math.sin(travel), 0.0, v * math.cos(travel)),
        "rotation": (0.0, math.sin(heading / 2), 0.0, math.cos(heading / 2)),
        "body_height": 0.07,
        "engine_rpm": smp["rpm"],
        "fuel_level": sc.fuel_start_l - sc.fuel_per_lap_l * laps_done,
        "fuel_capacity": sc.fuel_capacity_l,
        "speed": v,
        "turbo_boost": 1.0,
        "oil_pressure": 4.5,
        "water_temp": 85.0,
        "oil_temp": 110.0,
        # FL runs hottest, RR coolest: distinct values make wheel-order mistakes visible downstream
        "tyre_surface_temp": (74.0 + 9 * load, 72.0 + 8 * load, 70.0 + 7 * load, 68.0 + 6 * load),
        "lap_count": seg.lap,
        "total_laps": sc.total_laps,
        "best_lap_ms": best,
        "last_lap_ms": last,
        "time_of_day_ms": sc.time_of_day_start_ms + round(t * 1000),
        "pre_race_position": -1,
        "num_cars_pre_race": -1,
        "rev_alert_min_rpm": round(sc.vehicle.max_rpm * 0.85),
        "rev_alert_max_rpm": round(sc.vehicle.max_rpm),
        "calc_max_speed_kph": round(sc.vehicle.gear_top_kph[-1]),
        "flags": int(P.Flags.CAR_ON_TRACK | P.Flags.IN_GEAR),
        "gears": (0xF << 4) | (gear & 0x0F),  # suggested gear 15 = no suggestion
        "throttle": _byte(smp["throttle"]),
        "brake": _byte(smp["brake"]),
        "road_plane": (0.0, 1.0, 0.0),
        "wheel_angular_speed": (v / radius,) * 4,
        "tyre_radius": (radius,) * 4,
        "suspension_height": (0.05,) * 4,
        "clutch_pedal": 0.0,
        "clutch_engagement": 1.0,
        "rpm_clutch_to_gearbox": smp["rpm"],
        "transmission_top_speed": 2.8,
        "gear_ratios": (3.2, 2.3, 1.8, 1.45, 1.2, 1.0, 0.0, 0.0),
    }
    steer = smp["steering"]  # -1 left .. +1 right; GT7 angles are left-positive (doc section 7)
    if variant.name != "A":
        values.update({"wheel_rotation_rad": -steer * STEER_HALF_LOCK_RAD, "sway": 0.0, "heave": 0.0, "surge": 0.0})
    if variant.name in ("~", "C"):
        values.update({"throttle_alt": values["throttle"], "brake_alt": values["brake"]})
    if variant.name == "C":
        values.update(
            {
                "surface_type": b"TTTT",
                "current_lap_ms": round(smp["lap_t"] * 1000) if seg.lap >= 1 else -1,
                "fl_steer_rad": -steer * ROAD_WHEEL_LOCK_RAD,
                "fr_steer_rad": -steer * ROAD_WHEEL_LOCK_RAD,
                "wheelbase_left_m": sc.vehicle.wheelbase_m,
                "car_category": b"GR3\x00",
            }
        )
    return values


# ------------------------------------------------------------------------------------------------ scenarios
def gt7_coaching_demo() -> GT7Scenario:
    """Five timed laps with known mistakes (synthetic design corner names, not pitwall's learned numbering):

    lap 1-2: clean, near-optimal (the reference)
    lap 3:   brakes 15 m early into design-T3
    lap 4:   8 km/h low apex speed at design-T7
    lap 5:   paused mid-lap for 3 s (must stay a clean, complete lap)
    """
    return GT7Scenario(
        laps=5,
        driver_by_lap={
            3: DriverProfile(deviations={"T3": CornerDeviation(brake_early_m=15)}),
            4: DriverProfile(deviations={"T7": CornerDeviation(apex_speed_loss_kph=8)}),
        },
        pause=PauseSpec(lap=5, at_fraction=0.5, duration_s=3.0),
    )


def write_gt7_capture(
    path: Path, scenario: GT7Scenario | None = None, name: str = "gt7-coaching-demo"
) -> GT7GroundTruth:
    """Write a SYNTHETIC GT7 capture (``.pwcap``) flagged synthetic in its metadata.

    The packets must carry the synthetic marker too: a capture can be streamed over real UDP (``pitwall send``),
    where only the marker keeps it from being stored as a real session."""
    sc = scenario or gt7_coaching_demo()
    if not sc.synthetic_marker:
        raise ValueError("synthetic GT7 captures must carry the synthetic marker (synthetic_marker=True)")
    packets, truth = generate_gt7_session(sc)
    meta = CaptureMeta(
        source="synthetic",
        game_hint="gt7",
        synthetic=True,
        description=f"SYNTHETIC Gran Turismo 7 packet stream (variant {sc.variant}), scenario '{name}' - "
        "not real game output",
        extra={"track_name": truth.track.name, "scenario": name, "lap_times_ms": truth.lap_times_ms},
    )
    write_capture(path, packets, meta)
    return truth
